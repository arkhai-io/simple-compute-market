"""Version 2 marketplace authentication for the provisioning boundary."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from compute_provisioning.client import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    canonical_provisioning_request_body,
    resolve_provisioning_route_contract,
)
from fastapi import Request, status
from fastapi.responses import JSONResponse, Response
from market_identity import (
    EMPTY_BODY,
    REQUEST_PROTOCOL,
    AuthenticatedRequest,
    Identity,
    ReplayIdentity,
    ReplayReservation,
    ResponseEnvelope,
    SignatureProof,
    VerificationCode,
    canonical_body_hash,
    classify_replay,
    sign_response,
    verify_request,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware

from compute_provisioning_service.db.models import ProvisioningReplayReservation
from compute_provisioning_service.identity import ProvisioningIdentityContext

logger = logging.getLogger(__name__)

EXCLUDED_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class SqlAlchemyProvisioningReplayStore:
    """Atomic durable replay reservations, dispatch leases, and outcomes."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        dispatch_lease_seconds: int = 30,
    ) -> None:
        if dispatch_lease_seconds <= 0:
            raise ValueError("dispatch_lease_seconds must be positive")
        self._session_factory = session_factory
        self._dispatch_lease_seconds = dispatch_lease_seconds

    def get(
        self,
        principal: Identity,
        request_id: str,
    ) -> ReplayReservation | None:
        with self._session_factory() as session:
            row = session.get(
                ProvisioningReplayReservation,
                (principal.scheme.value, principal.identifier, request_id),
            )
            return _reservation(row, principal) if row is not None else None

    def reserve(
        self,
        reservation: ReplayReservation,
    ) -> ReplayReservation | None:
        principal = reservation.identity.principal
        try:
            with self._session_factory() as session:
                session.add(
                    ProvisioningReplayReservation(
                        principal_scheme=principal.scheme.value,
                        principal_identifier=principal.identifier,
                        request_id=reservation.identity.request_id,
                        request_hash=reservation.request_hash,
                        dispatch_lease_expires_at=self._lease_expiry(),
                    )
                )
                session.commit()
            return None
        except IntegrityError:
            existing = self.get(principal, reservation.identity.request_id)
            if existing is None:
                raise RuntimeError("replay reservation conflict disappeared")
            return existing

    def claim_stale(self, reservation: ReplayReservation) -> bool:
        """Atomically resume one exact request after its dispatch lease expires."""

        principal = reservation.identity.principal
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            updated = (
                session.query(ProvisioningReplayReservation)
                .filter(
                    ProvisioningReplayReservation.principal_scheme
                    == principal.scheme.value,
                    ProvisioningReplayReservation.principal_identifier
                    == principal.identifier,
                    ProvisioningReplayReservation.request_id
                    == reservation.identity.request_id,
                    ProvisioningReplayReservation.request_hash
                    == reservation.request_hash,
                    ProvisioningReplayReservation.response_status.is_(None),
                    ProvisioningReplayReservation.dispatch_lease_expires_at <= now,
                )
                .update(
                    {
                        ProvisioningReplayReservation.dispatch_lease_expires_at:
                            self._lease_expiry(),
                        ProvisioningReplayReservation.dispatch_attempt_count:
                            ProvisioningReplayReservation.dispatch_attempt_count + 1,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return updated == 1

    def load_outcome(
        self,
        principal: Identity,
        request_id: str,
    ) -> tuple[int, Any, str | None] | None:
        with self._session_factory() as session:
            row = session.get(
                ProvisioningReplayReservation,
                (principal.scheme.value, principal.identifier, request_id),
            )
            if row is None or row.response_status is None:
                return None
            return (
                int(row.response_status),
                EMPTY_BODY if row.response_body_empty else row.response_body,
                row.response_media_type,
            )

    def record_outcome(
        self,
        reservation: ReplayReservation,
        *,
        response_status: int,
        response_body: Any,
        response_media_type: str | None,
    ) -> None:
        principal = reservation.identity.principal
        with self._session_factory() as session:
            row = session.get(
                ProvisioningReplayReservation,
                (
                    principal.scheme.value,
                    principal.identifier,
                    reservation.identity.request_id,
                ),
            )
            if row is None or row.request_hash != reservation.request_hash:
                raise RuntimeError("replay reservation changed before outcome recording")
            row.response_status = response_status
            row.response_body_empty = response_body is EMPTY_BODY
            row.response_body = None if response_body is EMPTY_BODY else response_body
            row.response_media_type = response_media_type
            row.completed_at = datetime.now(timezone.utc)
            session.commit()

    def _lease_expiry(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(
            seconds=self._dispatch_lease_seconds
        )


def _reservation(
    row: ProvisioningReplayReservation,
    principal: Identity,
) -> ReplayReservation:
    return ReplayReservation(
        identity=ReplayIdentity(
            principal=principal,
            request_id=str(row.request_id),
        ),
        request_hash=str(row.request_hash),
    )


class ProvisioningAuthMiddleware(BaseHTTPMiddleware):
    """Verify the route's durable caller-role trust set and sign its response."""

    def __init__(
        self,
        app,
        *,
        identity_provider: Callable[[], ProvisioningIdentityContext],
        replay_store_provider: Callable[[], SqlAlchemyProvisioningReplayStore],
        principal_authority_provider: Callable[[], Any],
        max_timestamp_skew: int = 300,
    ) -> None:
        super().__init__(app)
        if max_timestamp_skew < 0:
            raise ValueError("max_timestamp_skew must not be negative")
        self._identity_provider = identity_provider
        self._replay_store_provider = replay_store_provider
        self._principal_authority_provider = principal_authority_provider
        self._max_timestamp_skew = max_timestamp_skew

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        identity = self._identity_provider()
        replay_store = self._replay_store_provider()
        body, body_error = await _request_body(request)
        if body_error is not None:
            return _rejection(body_error, status.HTTP_400_BAD_REQUEST)
        try:
            route, resource = resolve_provisioning_route_contract(
                request.method,
                request.url.path,
                body,
            )
            operation = route.operation
        except ValueError as exc:
            return _rejection(str(exc), status.HTTP_404_NOT_FOUND)

        try:
            authenticated = _authenticated_request(
                request,
                operation=operation,
                resource=resource,
                body=body,
            )
        except (TypeError, ValueError) as exc:
            return _signed_rejection(
                identity,
                request=request,
                operation=operation,
                resource=resource,
                body={"detail": str(exc)},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        if authenticated.role not in route.allowed_roles:
            return _signed_rejection(
                identity,
                request=request,
                operation=operation,
                resource=resource,
                body={"detail": "Marketplace role is not authorized"},
                status_code=status.HTTP_403_FORBIDDEN,
                request_id=authenticated.request_id,
            )

        existing = replay_store.get(
            authenticated.principal,
            authenticated.request_id,
        )
        expected_principals = (
            self._principal_authority_provider().active_principals(
                authenticated.role
            )
        )
        verification = verify_request(
            authenticated,
            body=body,
            now=int(time.time()),
            max_skew=self._max_timestamp_skew,
            expected_role=authenticated.role,
            expected_method=request.method,
            expected_operation=operation,
            expected_resource=resource,
            expected_principals=expected_principals,
            existing_replay=existing,
        )
        if not verification.verified or verification.reservation is None:
            return _signed_rejection(
                identity,
                request=request,
                operation=operation,
                resource=resource,
                body={"detail": _verification_detail(verification.code)},
                status_code=_verification_status(verification.code),
                request_id=authenticated.request_id,
            )

        exact_retry = verification.code == VerificationCode.EXACT_RETRY
        if verification.code == VerificationCode.VERIFIED:
            conflict = replay_store.reserve(verification.reservation)
            if conflict is not None:
                replay = classify_replay(authenticated, conflict)
                if replay.code.value == "changed_reuse":
                    return _signed_rejection(
                        identity,
                        request=request,
                        operation=operation,
                        resource=resource,
                        body={
                            "detail": "Request ID was reused with changed signed content"
                        },
                        status_code=status.HTTP_409_CONFLICT,
                        request_id=authenticated.request_id,
                    )
                exact_retry = True

        if exact_retry:
            outcome = replay_store.load_outcome(
                authenticated.principal,
                authenticated.request_id,
            )
            if outcome is not None:
                response_status, response_body, response_media_type = outcome
                return _signed_outcome_response(
                    identity,
                    method=request.method,
                    operation=operation,
                    resource=resource,
                    request_id=authenticated.request_id,
                    status_code=response_status,
                    body=response_body,
                    media_type=response_media_type,
                )
            if not replay_store.claim_stale(verification.reservation):
                return _signed_rejection(
                    identity,
                    request=request,
                    operation=operation,
                    resource=resource,
                    body={"detail": "The authenticated request is still in progress"},
                    status_code=status.HTTP_409_CONFLICT,
                    request_id=authenticated.request_id,
                )

        request.state.marketplace_principal = authenticated.principal
        request.state.marketplace_role = authenticated.role
        request.state.marketplace_request_id = authenticated.request_id
        request.state.agent_id = (
            f"{authenticated.principal.scheme.value}:"
            f"{authenticated.principal.identifier}"
        )
        response = await call_next(request)
        response_body_bytes = b"".join(
            [chunk async for chunk in response.body_iterator]
        )
        response_body = _response_body(response, response_body_bytes)
        replay_store.record_outcome(
            verification.reservation,
            response_status=response.status_code,
            response_body=response_body,
            response_media_type=response.headers.get("content-type"),
        )
        headers = dict(response.headers)
        headers.update(
            _signed_response_headers(
                identity,
                method=request.method,
                operation=operation,
                resource=resource,
                request_id=authenticated.request_id,
                status_code=response.status_code,
                body=response_body,
            )
        )
        return Response(
            content=response_body_bytes,
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )


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
        request.headers.get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if raw and (
        content_type == "application/json" or content_type.endswith("+json")
    ):
        try:
            body: Any = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EMPTY_BODY, "Authenticated provisioning bodies must be valid JSON"
    elif raw:
        body = {
            "content_type": content_type or "application/octet-stream",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    else:
        body = EMPTY_BODY

    query: dict[str, Any] = {}
    for key in sorted(set(request.query_params.keys())):
        values = request.query_params.getlist(key)
        query[key] = values[0] if len(values) == 1 else values
    try:
        return canonical_provisioning_request_body(
            request.method,
            request.url.path,
            body,
            query=query,
        ), None
    except (TypeError, ValueError):
        return EMPTY_BODY, "Authenticated provisioning query values are invalid"


def _response_body(response: Response, raw: bytes) -> Any:
    if not raw:
        return EMPTY_BODY
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        return json.loads(raw)
    return raw.decode("utf-8")


def _signed_outcome_response(
    identity: ProvisioningIdentityContext,
    *,
    method: str,
    operation: str,
    resource: str,
    request_id: str,
    status_code: int,
    body: Any,
    media_type: str | None,
) -> Response:
    if body is EMPTY_BODY:
        response = Response(status_code=status_code)
    elif media_type is not None and "json" not in media_type.lower():
        response = Response(
            content=body,
            status_code=status_code,
            headers={"content-type": media_type},
        )
    else:
        response = JSONResponse(content=body, status_code=status_code)
    response.headers.update(
        _signed_response_headers(
            identity,
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
    identity: ProvisioningIdentityContext,
    *,
    request: Request,
    operation: str,
    resource: str,
    body: dict[str, str],
    status_code: int,
    request_id: str | None = None,
) -> JSONResponse:
    response = JSONResponse(content=body, status_code=status_code)
    resolved_request_id = request_id or request.headers.get(REQUEST_ID_HEADER)
    if not resolved_request_id:
        return response
    try:
        response.headers.update(
            _signed_response_headers(
                identity,
                method=request.method,
                operation=operation,
                resource=resource,
                request_id=resolved_request_id,
                status_code=status_code,
                body=body,
            )
        )
    except (TypeError, ValueError):
        logger.warning("Could not sign authentication rejection with malformed request ID")
    return response


def _signed_response_headers(
    identity: ProvisioningIdentityContext,
    *,
    method: str,
    operation: str,
    resource: str,
    request_id: str,
    status_code: int,
    body: Any,
) -> dict[str, str]:
    authenticated = sign_response(
        signer=identity.signer,
        envelope=ResponseEnvelope(
            role="service",
            principal=identity.signer.identity,
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


def _rejection(detail: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _verification_detail(code: VerificationCode) -> str:
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
