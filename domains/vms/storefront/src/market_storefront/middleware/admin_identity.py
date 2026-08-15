"""Marketplace v2 authentication for VM storefront administrator routes."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import quote, urlencode

from core_storefront.auth import (
    AuthenticatedPrincipal,
    AuthError,
    authenticate_request,
    signed_response_headers,
)
from core_storefront.identity_authority import (
    ADMINISTRATOR_AUTHORITY,
    StorefrontIdentityAuthority,
)
from core_storefront.identity_lifecycle import (
    identity_status_resource,
    identity_subject_resource,
)
from fastapi import Request
from market_identity import EMPTY_BODY, Identity
from starlette.responses import JSONResponse, Response

import market_storefront.container as _container
from market_storefront.utils.config import get_administrator_configs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdminRouteContract:
    operation: str
    resource: str
    body: Any


def initialize_administrator_identities(
    db_path: str, *, now: int | None = None
) -> None:
    """Idempotently materialize configured administrator trust pins."""

    timestamp = int(time.time()) if now is None else now
    authority = StorefrontIdentityAuthority(db_path)
    for subject, principals in get_administrator_configs().items():
        try:
            status = authority.status(
                authority=ADMINISTRATOR_AUTHORITY,
                subject=subject,
            )
        except KeyError:
            if len(principals.identities) != 1:
                raise AuthError(
                    "A new administrator requires exactly one primary principal"
                ) from None
            status = authority.register_subject(
                authority=ADMINISTRATOR_AUTHORITY,
                subject=subject,
                role="admin",
                principal=principals.identities[0],
                now=timestamp,
            )
        configured = frozenset(principals.identities)
        active = status.active_principals(timestamp)
        if status.primary not in configured or not active.issubset(configured):
            raise AuthError(
                "Administrator config does not cover durable active identities"
            )


def _active_administrators(db_path: str, *, now: int) -> frozenset[Identity]:
    authority = StorefrontIdentityAuthority(db_path)
    principals: set[Identity] = set()
    for subject in get_administrator_configs():
        principals.update(
            authority.status(
                authority=ADMINISTRATOR_AUTHORITY,
                subject=subject,
            ).active_principals(now)
        )
    return frozenset(principals)


def _resource_import_descriptor(request: Request, raw: bytes) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise AuthError("resource import requires multipart/form-data", status_code=400)
    message = BytesParser(policy=policy.default).parsebytes(
        (f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode("ascii")
        + raw
    )
    files = [
        part
        for part in message.iter_parts()
        if part.get_param("name", header="content-disposition") == "file"
    ]
    if len(files) != 1:
        raise AuthError("resource import requires exactly one file", status_code=400)
    part = files[0]
    payload = part.get_payload(decode=True) or b""
    return {
        "filename": part.get_filename() or "",
        "media_type": part.get_content_type(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _system_events_resource(request: Request) -> str:
    query = request.query_params
    allowed = {
        "limit",
        "since_id",
        "stream",
        "listing_id",
        "negotiation_id",
        "stage",
    }
    if not set(query.keys()).issubset(allowed) or any(
        len(query.getlist(name)) != 1 for name in query.keys()
    ):
        raise AuthError(
            "system event query contains an unauthenticated alias", status_code=400
        )
    if query.get("stream", "false").lower() != "false":
        raise AuthError(
            "signed event streaming is unsupported; use authenticated polling",
            status_code=400,
        )
    values: dict[str, str] = {
        "limit": query.get("limit", "100"),
        "since_id": query.get("since_id", "0"),
        "stream": query.get("stream", "false").lower(),
    }
    for name in ("listing_id", "negotiation_id", "stage"):
        value = query.get(name)
        if value is not None:
            values[name] = value
    return "system-events?" + urlencode(
        sorted(values.items()), quote_via=quote, safe=""
    )


def _negotiation_list_resource(request: Request, listing_id: str) -> str:
    query = request.query_params
    allowed = {
        "limit",
        "offset",
        "buyer_identifier",
        "buyer_scheme",
        "terminal_state",
    }
    if not set(query.keys()).issubset(allowed) or any(
        len(query.getlist(name)) != 1 for name in query.keys()
    ):
        raise AuthError(
            "negotiation query contains an unauthenticated alias",
            status_code=400,
        )
    values: dict[str, str] = {
        "limit": query.get("limit", "50"),
        "offset": query.get("offset", "0"),
    }
    for name in (
        "buyer_identifier",
        "buyer_scheme",
        "terminal_state",
    ):
        value = query.get(name)
        if value is not None:
            values[name] = value
    return f"{listing_id}/negotiations?" + urlencode(
        sorted(values.items()), quote_via=quote, safe=""
    )


def _identity_contract(
    request: Request,
    *,
    path: str,
    method: str,
    body: Any,
) -> AdminRouteContract | None:
    if method == "GET" and path == "/api/v1/admin/identity/status":
        query = request.query_params
        if set(query.keys()) != {"authority", "subject"} or any(
            len(query.getlist(name)) != 1 for name in ("authority", "subject")
        ):
            raise AuthError(
                "identity status requires exactly one authority and subject",
                status_code=400,
            )
        authority = query["authority"]
        subject = query["subject"]
        try:
            resource = identity_status_resource(authority, subject)
        except ValueError as exc:
            raise AuthError(str(exc), status_code=400) from exc
        return AdminRouteContract("admin_identity_status", resource, EMPTY_BODY)
    operation = {
        ("POST", "/api/v1/admin/identity/rotations"): "admin_rotate_identity",
        ("POST", "/api/v1/admin/identity/retirements"): "admin_retire_identity",
    }.get((method, path))
    if operation is None:
        return None
    if not isinstance(body, dict):
        raise AuthError("identity lifecycle body must be an object", status_code=400)
    carrier = body.get("intent") if operation == "admin_rotate_identity" else body
    if not isinstance(carrier, dict):
        raise AuthError("identity lifecycle subject is missing", status_code=400)
    authority = carrier.get("authority")
    subject = carrier.get("subject")
    try:
        resource = identity_subject_resource(authority, subject)
    except (TypeError, ValueError) as exc:
        raise AuthError(str(exc), status_code=400) from exc
    return AdminRouteContract(operation, resource, body)


def _contract(request: Request, body: Any) -> AdminRouteContract | None:
    path = request.url.path.rstrip("/")
    method = request.method
    identity_contract = _identity_contract(
        request,
        path=path,
        method=method,
        body=body,
    )
    if identity_contract is not None:
        return identity_contract
    exact: dict[tuple[str, str], tuple[str, str]] = {
        ("POST", "/api/v1/admin/pause"): ("admin_pause", ""),
        ("POST", "/api/v1/admin/resume"): ("admin_resume", ""),
        ("POST", "/api/v1/admin/portfolio/release-reservations"): (
            "admin_release_reservations",
            "",
        ),
        ("POST", "/api/v1/admin/portfolio/reservations"): (
            "admin_reserve_capacity",
            str(
                (body.get("listing_id") or body.get("escrow_uid") or "")
                if isinstance(body, dict)
                else ""
            ),
        ),
    }
    matched = exact.get((method, path))
    if matched is not None:
        return AdminRouteContract(*matched, body)

    if method == "GET" and path == "/api/v1/system/events":
        if request.headers.get("last-event-id") is not None:
            raise AuthError("Last-Event-ID is not an authenticated query alias")
        return AdminRouteContract(
            "admin_system_events", _system_events_resource(request), EMPTY_BODY
        )

    if method == "POST" and path == "/api/v1/admin/portfolio/resources/import":
        return AdminRouteContract("admin_import_resources", "portfolio/resources", body)

    prefix = "/api/v1/admin/deals/"
    if method == "POST" and path.startswith(prefix) and path.endswith("/interrupt"):
        return AdminRouteContract(
            "admin_interrupt_deal", path[len(prefix) : -len("/interrupt")], body
        )

    prefix = "/api/v1/admin/portfolio/resources/"
    if path.startswith(prefix) and "/" not in path[len(prefix) :]:
        resource = path[len(prefix) :]
        if method == "GET":
            return AdminRouteContract("admin_get_resource", resource, EMPTY_BODY)
        if method == "PATCH":
            return AdminRouteContract("admin_patch_resource", resource, body)

    prefix = "/api/v1/listings/"
    if method == "GET" and path.startswith(prefix):
        suffix = path[len(prefix) :]
        if suffix.endswith("/negotiations") and suffix.count("/") == 1:
            listing_id = suffix[: -len("/negotiations")]
            return AdminRouteContract(
                "admin_list_negotiations",
                _negotiation_list_resource(request, listing_id),
                EMPTY_BODY,
            )
        if "/negotiations/" in suffix:
            listing_id, neg_id = suffix.split("/negotiations/", 1)
            if neg_id and "/" not in neg_id:
                return AdminRouteContract(
                    "admin_get_negotiation",
                    f"{listing_id}/negotiations/{neg_id}",
                    EMPTY_BODY,
                )

    prefix = "/api/v1/listings/"
    if method == "POST" and path.startswith(prefix):
        suffix = path[len(prefix) :]
        if suffix.endswith("/pause"):
            return AdminRouteContract(
                "admin_pause_listing", suffix[: -len("/pause")], body
            )
        if suffix.endswith("/resume"):
            return AdminRouteContract(
                "admin_resume_listing", suffix[: -len("/resume")], body
            )
        if "/negotiations/" in suffix:
            listing_id, tail = suffix.split("/negotiations/", 1)
            if tail.endswith("/advance"):
                neg_id = tail[: -len("/advance")]
                return AdminRouteContract(
                    "admin_advance_negotiation", f"{listing_id}/{neg_id}", body
                )
            if tail.endswith("/force-accept"):
                neg_id = tail[: -len("/force-accept")]
                return AdminRouteContract(
                    "admin_force_accept_negotiation", f"{listing_id}/{neg_id}", body
                )

    prefix = "/api/v1/admin/listings/"
    if (
        method == "POST"
        and path.startswith(prefix)
        and path.endswith("/evaluate-negotiate")
    ):
        return AdminRouteContract(
            "admin_evaluate_negotiation",
            path[len(prefix) : -len("/evaluate-negotiate")],
            body,
        )

    prefix = "/api/v1/admin/settle/"
    if path.startswith(prefix):
        suffix = path[len(prefix) :]
        if method == "POST" and suffix.endswith("/verify"):
            return AdminRouteContract(
                "admin_verify_settlement", suffix[: -len("/verify")], body
            )
        if method == "POST" and suffix.endswith("/evaluate"):
            return AdminRouteContract(
                "admin_evaluate_settlement", suffix[: -len("/evaluate")], body
            )
        if method == "GET" and suffix.endswith("/wait"):
            timeout = request.query_params.get("timeout")
            if timeout is None:
                raise AuthError("admin settlement wait requires explicit timeout")
            return AdminRouteContract(
                "admin_settle_wait",
                f"{suffix[: -len('/wait')]}?timeout={timeout}",
                EMPTY_BODY,
            )
    return None


def _claimed_administrator(request: Request) -> Identity:
    scheme = request.headers.get("X-Market-Identity-Scheme")
    identifier = request.headers.get("X-Market-Identity-Identifier")
    if scheme is None or identifier is None:
        raise AuthError(
            "Administrator principal authentication is required", status_code=401
        )
    try:
        return Identity(scheme=scheme, identifier=identifier)
    except (TypeError, ValueError) as exc:
        raise AuthError("Malformed administrator principal", status_code=400) from exc


def _wire_body(raw: bytes) -> Any:
    if not raw:
        return EMPTY_BODY
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw.decode("utf-8", errors="replace")


def _storefront_signer():
    signer = _container.resolved_marketplace_signer
    if signer is None:
        raise AuthError("storefront marketplace signer is unavailable", status_code=503)
    return signer


def _authenticated_error_response(
    *,
    request: Request,
    contract: AdminRouteContract,
    error: AuthError,
) -> JSONResponse:
    """Sign errors for complete authenticated requests, even before trust succeeds."""

    body = {"detail": error.detail}
    request_id = request.headers.get("X-Market-Request-ID")
    if not request_id:
        return JSONResponse(status_code=error.status_code, content=body)
    return JSONResponse(
        status_code=error.status_code,
        content=body,
        headers=signed_response_headers(
            signer=_storefront_signer(),
            role="seller",
            method=request.method,
            operation=contract.operation,
            resource=contract.resource,
            request_id=request_id,
            status=error.status_code,
            body=body,
        ),
    )


async def _signed_response(
    *,
    request: Request,
    response: Response,
    contract: AdminRouteContract,
    auth: AuthenticatedPrincipal,
) -> Response:
    raw = (
        b"".join([chunk async for chunk in response.body_iterator])
        if hasattr(response, "body_iterator")
        else bytes(response.body)
    )
    body = _wire_body(raw)
    db = _container.resolved_sqlite_client
    await db.record_replay_outcome(
        auth.reservation,
        attempt_token=auth.attempt_token,
        status=response.status_code,
        body=body,
    )
    headers = dict(response.headers)
    headers.update(
        signed_response_headers(
            signer=_storefront_signer(),
            role="seller",
            method=request.method,
            operation=contract.operation,
            resource=contract.resource,
            request_id=auth.request_id,
            status=response.status_code,
            body=body,
        )
    )
    headers.pop("content-length", None)
    return Response(
        content=raw,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
        background=response.background,
    )


async def administrator_identity_middleware(request: Request, call_next):
    """Authenticate and replay-protect supported administrator routes."""
    if (
        request.method == "GET"
        and request.url.path.rstrip("/") == "/api/v1/system/status"
        and request.headers.get("X-Market-Role") == "service"
    ):
        return await call_next(request)

    raw = await request.body()
    if (
        request.method == "POST"
        and request.url.path.rstrip("/") == "/api/v1/admin/portfolio/resources/import"
    ):
        try:
            body = _resource_import_descriptor(request, raw)
        except AuthError as exc:
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )
    else:
        body = _wire_body(raw)
    try:
        contract = _contract(request, body)
        if contract is None:
            return await call_next(request)
        db = _container.resolved_sqlite_client
        if db is None:
            raise AuthError("authentication store unavailable", status_code=503)
        _storefront_signer()
        now = int(time.time())
        claimed = _claimed_administrator(request)
        if claimed not in _active_administrators(db.db_path, now=now):
            raise AuthError(
                "Administrator principal is not authorized", status_code=403
            )
        auth = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=contract.operation,
            resource=contract.resource,
            body=contract.body,
            expected_role="admin",
            expected_principal=claimed,
            replay_store=db,
            now=now,
        )
        request.state.marketplace_authenticated = auth
        request.state.administrator_authenticated = True
        if auth.exact_retry:
            if auth.recorded_outcome is None:
                raise AuthError("request retry is pending", status_code=409)
            status, replay_body = auth.recorded_outcome
            return JSONResponse(
                status_code=status,
                content=replay_body,
                headers=signed_response_headers(
                    signer=_storefront_signer(),
                    role="seller",
                    method=request.method,
                    operation=contract.operation,
                    resource=contract.resource,
                    request_id=auth.request_id,
                    status=status,
                    body=replay_body,
                ),
            )
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Administrator route failed after authentication")
            response = JSONResponse(
                status_code=500,
                content={"detail": "Storefront administrator request failed"},
            )
        return await _signed_response(
            request=request, response=response, contract=contract, auth=auth
        )
    except AuthError as exc:
        if "contract" in locals() and contract is not None:
            return _authenticated_error_response(
                request=request,
                contract=contract,
                error=exc,
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
