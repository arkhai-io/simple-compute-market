"""Server half of the site-authority wire contract.

``kit/site`` ships the capacity routes; ``kit/site-client`` ships a client that
signs every request and requires a signed response. Until this module existed
the server half of that contract lived once, hand-rolled inside the
provisioning service and entangled with a SQLAlchemy replay store and durable
principal rotation, so any second service mounting the router got a surface the
kit's own client refuses to talk to.

Three things follow from where this sits in the package graph:

- **The roles table lives beside the router that defines the paths**, keyed by
  the operation names the client already signs with. The client owns the same
  method/path/operation mapping, but a router depending on its own caller is
  the wrong direction, so the two tables are kept honest by a parity test
  rather than by one importing the other.
- **The replay store is a port**, with an in-memory default. A service with
  durable replay requirements supplies its own; a service without one still
  gets replay rejection within a process lifetime instead of none.
- **Refusals are signed too.** An unauthenticated refusal cannot be told from
  a network fault or an impostor by a client that requires signed responses --
  it fails on a missing header rather than reporting the 401 it was sent.

Scoped by route table, not by mounting position: a composing service passes the
tables covering its own paths, and anything unmatched is refused rather than
waved through, so adding a route without a contract fails loudly.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import Request, status
from fastapi.responses import JSONResponse, Response
from market_identity import (
    EMPTY_BODY,
    REQUEST_PROTOCOL,
    AuthenticatedRequest,
    Identity,
    ReplayReservation,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    VerificationCode,
    canonical_body_hash,
    classify_replay,
    sign_response,
    verify_request,
)
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"

#: Liveness and documentation only. Deliberately short: every route carrying
#: or changing site state is authenticated, and a path is excluded here rather
#: than by lacking a contract, so an unlisted route is a refusal.
EXCLUDED_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})

#: The operator's own role. Accepted on every contract rather than enumerated
#: route by route: `admin` exists for manual operation, debugging and
#: intervention, and a role that can read a site's whole ledger but not one
#: named route is a gate that only ever obstructs the person holding it.
#: Service components use their own role and do not hold this one.
ADMIN_ROLE = "admin"


@dataclass(frozen=True, slots=True)
class SiteRouteContract:
    """One authenticated route, its semantic operation, and who may call it.

    ``resource`` is the thing being acted on, extracted from the path or the
    body, because it is signed: a signature over an operation without its
    resource would verify for the same operation against a different object.
    """

    method: str
    pattern: re.Pattern[str]
    operation: str
    allowed_roles: frozenset[str]
    path_resource: str | None = None
    body_resource: str | None = None
    optional_body_resource: bool = False

    def match(self, method: str, path: str, body: Any) -> str | None:
        if method.upper() != self.method:
            return None
        matched = self.pattern.fullmatch(path)
        if matched is None:
            return None
        if self.path_resource is not None:
            return matched.group(self.path_resource)
        if self.body_resource is not None:
            if not isinstance(body, dict):
                raise ValueError(
                    f"{self.operation} requires a JSON object request body"
                )
            resource = body.get(self.body_resource)
            if resource is None and self.optional_body_resource:
                return ""
            if not isinstance(resource, str) or not resource:
                raise ValueError(
                    f"{self.operation} requires body.{self.body_resource}"
                )
            return resource
        return ""

    def permits(self, role: str) -> bool:
        return role == ADMIN_ROLE or role in self.allowed_roles


def _seller(
    method: str,
    pattern: str,
    operation: str,
    **kwargs: Any,
) -> SiteRouteContract:
    """A capacity route the storefront this site sells for may call.

    Every capacity route is `seller`-scoped because a site authority's caller
    is the storefront selling its inventory; `admin` is admitted by
    `permits()` everywhere and is not restated here.
    """
    return SiteRouteContract(
        method=method,
        pattern=re.compile(pattern),
        operation=operation,
        allowed_roles=frozenset({"seller"}),
        **kwargs,
    )


#: Method and path to operation, resource and roles for every capacity route.
#: Order matters where patterns overlap: the collection routes precede the
#: identified ones they prefix, matching the client's own ordering.
CAPACITY_ROUTE_CONTRACTS: tuple[SiteRouteContract, ...] = (
    _seller(
        "PUT",
        r"/api/v1/capacity/resources/(?P<resource_id>[^/]+)",
        "capacity_resource_put",
        path_resource="resource_id",
    ),
    _seller("GET", r"/api/v1/capacity/resources", "capacity_resources_list"),
    _seller(
        "GET",
        r"/api/v1/capacity/site-resource-pools/version",
        "capacity_resource_pools_version",
    ),
    _seller(
        "GET",
        r"/api/v1/capacity/site-resource-pools",
        "capacity_resource_pools_get",
    ),
    _seller(
        "GET",
        r"/api/v1/capacity/site-capacity-buckets/version",
        "capacity_buckets_version",
    ),
    _seller(
        "GET",
        r"/api/v1/capacity/site-capacity-buckets",
        "capacity_buckets_get",
    ),
    _seller("GET", r"/api/v1/capacity/snapshot", "capacity_snapshot"),
    _seller("POST", r"/api/v1/capacity/probe", "capacity_probe"),
    _seller("POST", r"/api/v1/capacity/reservations", "capacity_reserve"),
    _seller(
        "POST",
        r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)/commit",
        "capacity_commit",
        path_resource="reservation_id",
    ),
    _seller(
        "POST",
        r"/api/v1/capacity/releases",
        "capacity_release",
        body_resource="capacity_reservation_id",
        optional_body_resource=True,
    ),
    _seller(
        "POST",
        r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)/truncate-lease",
        "capacity_truncate_lease",
        path_resource="reservation_id",
    ),
    _seller(
        "GET",
        r"/api/v1/capacity/reservations",
        "capacity_reservations_list",
    ),
    _seller(
        "GET",
        r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)",
        "capacity_reservation_get",
        path_resource="reservation_id",
    ),
    _seller("GET", r"/api/v1/capacity/events", "capacity_events"),
)


def resolve_site_route(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
    *,
    contracts: Sequence[SiteRouteContract] = CAPACITY_ROUTE_CONTRACTS,
) -> tuple[SiteRouteContract, str]:
    """Return the server-owned contract and resource for a route."""

    for contract in contracts:
        resource = contract.match(method, path, body)
        if resource is not None:
            return contract, resource
    raise ValueError(f"no authenticated site contract for {method} {path}")


class SiteReplayStore(Protocol):
    """Reservation of a caller's request id, so a replay is refused once seen.

    A port because durability is a deployment property, not a contract one: a
    service holding a database can make reservations survive a restart, and one
    without a database should still refuse replays inside a process rather than
    accept them because the strong option was unavailable.
    """

    def get(self, principal: Identity, request_id: str) -> ReplayReservation | None:
        ...

    def reserve(self, reservation: ReplayReservation) -> ReplayReservation | None:
        ...


@dataclass
class InMemoryReplayStore:
    """Process-local replay reservations.

    The default, and honest about its limit: reservations do not survive a
    restart, so a replay arriving across one is accepted. That is strictly
    better than no replay check, and a service that cannot tolerate the gap
    supplies a durable store instead of relying on this.
    """

    _entries: dict[tuple[str, str, str], ReplayReservation] = field(
        default_factory=dict
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @staticmethod
    def _key(principal: Identity, request_id: str) -> tuple[str, str, str]:
        return (principal.scheme.value, principal.identifier, request_id)

    def get(self, principal: Identity, request_id: str) -> ReplayReservation | None:
        with self._lock:
            return self._entries.get(self._key(principal, request_id))

    def reserve(self, reservation: ReplayReservation) -> ReplayReservation | None:
        key = self._key(
            reservation.identity.principal, reservation.identity.request_id
        )
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                return existing
            self._entries[key] = reservation
            return None


class SiteAuthMiddleware(BaseHTTPMiddleware):
    """Verify a signed site-authority request and sign the response.

    Every collaborator is injected as a provider rather than a value because
    composition order is not startup order: a service resolves its signing
    credential and its trust sets during lifespan, after middleware is added.
    """

    def __init__(
        self,
        app,
        *,
        signer_provider: Callable[[], Any],
        expected_principals: Callable[[str], TrustedIdentitySet],
        contracts: Sequence[SiteRouteContract] = CAPACITY_ROUTE_CONTRACTS,
        replay_store_provider: Callable[[], SiteReplayStore] | None = None,
        max_timestamp_skew: int = 300,
        excluded_paths: frozenset[str] = EXCLUDED_PATHS,
    ) -> None:
        super().__init__(app)
        if max_timestamp_skew < 0:
            raise ValueError("max_timestamp_skew must not be negative")
        self._signer_provider = signer_provider
        self._expected_principals = expected_principals
        self._contracts = tuple(contracts)
        store = InMemoryReplayStore()
        self._replay_store_provider = replay_store_provider or (lambda: store)
        self._max_timestamp_skew = max_timestamp_skew
        self._excluded_paths = excluded_paths

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._excluded_paths:
            return await call_next(request)

        signer = self._signer_provider()
        body, body_error = await _request_body(request)
        if body_error is not None:
            return _rejection(body_error, status.HTTP_400_BAD_REQUEST)

        try:
            contract, resource = resolve_site_route(
                request.method,
                request.url.path,
                body,
                contracts=self._contracts,
            )
        except ValueError as exc:
            # Unsigned: with no contract there is no operation to sign over,
            # and inventing one would put a signature on a claim about a route
            # this service does not define.
            return _rejection(str(exc), status.HTTP_404_NOT_FOUND)
        operation = contract.operation

        try:
            authenticated = _authenticated_request(
                request, operation=operation, resource=resource, body=body
            )
        except (TypeError, ValueError) as exc:
            return self._signed_rejection(
                signer,
                request=request,
                operation=operation,
                resource=resource,
                body={"detail": str(exc)},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        if not contract.permits(authenticated.role):
            return self._signed_rejection(
                signer,
                request=request,
                operation=operation,
                resource=resource,
                body={"detail": "Marketplace role is not authorized"},
                status_code=status.HTTP_403_FORBIDDEN,
                request_id=authenticated.request_id,
            )

        replay_store = self._replay_store_provider()
        verification = verify_request(
            authenticated,
            body=body,
            now=int(time.time()),
            max_skew=self._max_timestamp_skew,
            expected_role=authenticated.role,
            expected_method=request.method,
            expected_operation=operation,
            expected_resource=resource,
            expected_principals=self._expected_principals(authenticated.role),
            existing_replay=replay_store.get(
                authenticated.principal, authenticated.request_id
            ),
        )
        if not verification.verified or verification.reservation is None:
            return self._signed_rejection(
                signer,
                request=request,
                operation=operation,
                resource=resource,
                body={"detail": _verification_detail(verification.code)},
                status_code=_verification_status(verification.code),
                request_id=authenticated.request_id,
            )

        if verification.code == VerificationCode.VERIFIED:
            conflict = replay_store.reserve(verification.reservation)
            if conflict is not None:
                # Lost a race with a concurrent identical request. Only
                # reuse with *changed* signed content is a conflict; an
                # exact retry is the caller resending what it already sent,
                # and is allowed through to the handler. This store keeps no
                # outcomes, so the retry is re-executed rather than replayed
                # -- correct for idempotent capacity routes, and the reason a
                # service needing replayed outcomes supplies its own store.
                replay = classify_replay(authenticated, conflict)
                if replay.code == VerificationCode.CHANGED_REUSE:
                    return self._signed_rejection(
                        signer,
                        request=request,
                        operation=operation,
                        resource=resource,
                        body={
                            "detail": (
                                "Request ID was reused with changed signed content"
                            )
                        },
                        status_code=status.HTTP_409_CONFLICT,
                        request_id=authenticated.request_id,
                    )

        response = await call_next(request)
        raw = b"".join([chunk async for chunk in response.body_iterator])
        return self._signed_outcome(
            signer,
            method=request.method,
            operation=operation,
            resource=resource,
            request_id=authenticated.request_id,
            status_code=response.status_code,
            body=_response_body(response, raw),
            raw=raw,
            media_type=response.headers.get("content-type"),
        )

    def _signed_outcome(
        self,
        signer: Any,
        *,
        method: str,
        operation: str,
        resource: str,
        request_id: str,
        status_code: int,
        body: Any,
        raw: bytes,
        media_type: str | None,
    ) -> Response:
        if body is EMPTY_BODY:
            response: Response = Response(status_code=status_code)
        elif media_type is not None and "json" not in media_type.lower():
            response = Response(
                content=raw,
                status_code=status_code,
                headers={"content-type": media_type},
            )
        else:
            response = JSONResponse(content=body, status_code=status_code)
        response.headers.update(
            _signed_headers(
                signer,
                method=method,
                operation=operation,
                resource=resource,
                request_id=request_id,
                status_code=status_code,
                body=body,
            )
        )
        return response

    def _signed_rejection(
        self,
        signer: Any,
        *,
        request: Request,
        operation: str,
        resource: str,
        body: dict[str, str],
        status_code: int,
        request_id: str | None = None,
    ) -> JSONResponse:
        response = JSONResponse(content=body, status_code=status_code)
        resolved = request_id or request.headers.get(REQUEST_ID_HEADER)
        if not resolved:
            # Nothing to bind a signature to. A response signed over an
            # invented request id would verify against a request nobody sent.
            return response
        try:
            response.headers.update(
                _signed_headers(
                    signer,
                    method=request.method,
                    operation=operation,
                    resource=resource,
                    request_id=resolved,
                    status_code=status_code,
                    body=body,
                )
            )
        except (TypeError, ValueError):
            logger.warning(
                "Could not sign site-authority refusal for %s %s",
                request.method,
                request.url.path,
            )
        return response


def _signed_headers(
    signer: Any,
    *,
    method: str,
    operation: str,
    resource: str,
    request_id: str,
    status_code: int,
    body: Any,
) -> dict[str, str]:
    authenticated = sign_response(
        signer=signer,
        envelope=ResponseEnvelope(
            role="service",
            principal=signer.identity,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
            timestamp=int(time.time()),
            status=status_code,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }


def _authenticated_request(
    request: Request,
    *,
    operation: str,
    resource: str,
    body: Any,
) -> AuthenticatedRequest:
    protocol = _required_header(request, SIGNATURE_VERSION_HEADER)
    if protocol != REQUEST_PROTOCOL:
        raise ValueError("Unsupported marketplace request signature version")
    principal = Identity(
        scheme=_required_header(request, IDENTITY_SCHEME_HEADER),
        identifier=_required_header(request, IDENTITY_IDENTIFIER_HEADER),
    )
    try:
        timestamp = int(_required_header(request, TIMESTAMP_HEADER))
    except ValueError as exc:
        raise ValueError(f"Invalid {TIMESTAMP_HEADER} header") from exc
    return AuthenticatedRequest(
        protocol=protocol,
        role=_required_header(request, ROLE_HEADER),
        principal=principal,
        method=request.method,
        operation=operation,
        resource=resource,
        request_id=_required_header(request, REQUEST_ID_HEADER),
        timestamp=timestamp,
        body_hash=canonical_body_hash(body),
        proof=SignatureProof(
            scheme=principal.scheme,
            value=_required_header(request, SIGNATURE_HEADER),
        ),
    )


def _required_header(request: Request, name: str) -> str:
    value = request.headers.get(name)
    if not value:
        raise ValueError(f"Missing {name} header")
    return value


async def _request_body(request: Request) -> tuple[Any, str | None]:
    raw = await request.body()
    content_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if raw and (content_type == "application/json" or content_type.endswith("+json")):
        try:
            return json.loads(raw), None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EMPTY_BODY, "Authenticated site bodies must be valid JSON"
    if raw:
        return EMPTY_BODY, "Authenticated site bodies must be JSON"
    return EMPTY_BODY, None


def _response_body(response: Response, raw: bytes) -> Any:
    if not raw:
        return EMPTY_BODY
    media_type = (response.headers.get("content-type") or "").lower()
    if "json" in media_type:
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EMPTY_BODY
    return raw


def _rejection(detail: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _verification_detail(code: VerificationCode) -> str:
    """Say which check refused, without saying what would have passed it.

    Mirrors the provisioning service's wording for the same codes: two site
    authorities refusing the same caller for the same reason in different
    language is a debugging cost paid by whoever holds both logs.
    """
    if code == VerificationCode.CHANGED_REUSE:
        return "Request ID was reused with changed signed content"
    if code == VerificationCode.TIMESTAMP_SKEW:
        return "Marketplace authentication timestamp is outside the allowed skew"
    if code == VerificationCode.BODY_HASH_MISMATCH:
        return "Marketplace authentication does not match the request body"
    if code == VerificationCode.CONTEXT_MISMATCH:
        return "Marketplace authentication role, principal, or route does not match"
    return "Invalid marketplace authentication"


def _verification_status(code: VerificationCode) -> int:
    if code == VerificationCode.CHANGED_REUSE:
        return status.HTTP_409_CONFLICT
    if code in {
        VerificationCode.MALFORMED_ENVELOPE,
        VerificationCode.UNSUPPORTED_VERSION,
    }:
        return status.HTTP_401_UNAUTHORIZED
    return status.HTTP_403_FORBIDDEN
