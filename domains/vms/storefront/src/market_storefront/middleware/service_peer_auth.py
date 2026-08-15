"""V2 authentication and signed responses for provisioning service callbacks."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from starlette.responses import JSONResponse, Response

from core_storefront.auth import (
    AuthError,
    AuthenticatedPrincipal,
    authenticate_request,
    signed_response_headers,
)
from core_storefront.identity_authority import (
    SERVICE_PEER_AUTHORITY,
    StorefrontIdentityAuthority,
)
from market_identity import EMPTY_BODY, Identity

import market_storefront.container as _container
from market_storefront.utils.config import get_service_peer_configs

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ServiceCallback:
    method: str
    operation: str
    resource: str
    site_id: str
    body: Any


_CALLBACK_OPERATIONS = {
    "/api/v1/admin/fulfillment/events/started": "fulfillment_started",
    "/api/v1/admin/fulfillment/events/release-started": "fulfillment_release_started",
    "/api/v1/admin/fulfillment/events/capacity-released": (
        "fulfillment_capacity_released"
    ),
    "/api/v1/admin/fulfillment/events/usage-started": "fulfillment_usage_started",
    "/api/v1/admin/fulfillment/events/failed": "fulfillment_failed",
}


def initialize_service_peer_identities(
    db_path: str, *, now: int | None = None
) -> None:
    """Idempotently materialize configured service-peer trust pins."""

    timestamp = int(time.time()) if now is None else now
    authority = StorefrontIdentityAuthority(db_path)
    for peer_id, (role, site_id, principals) in get_service_peer_configs().items():
        try:
            status = authority.status(
                authority=SERVICE_PEER_AUTHORITY,
                subject=peer_id,
            )
        except KeyError:
            if len(principals.identities) != 1:
                raise AuthError(
                    "A new service peer requires exactly one primary principal"
                ) from None
            status = authority.register_service_peer(
                peer_id=peer_id,
                role=role,
                site_id=site_id,
                principal=principals.identities[0],
                now=timestamp,
            )
        conn = sqlite3.connect(db_path)
        try:
            durable_peer = conn.execute(
                "SELECT role, site_id FROM service_peers WHERE peer_id=?",
                (peer_id,),
            ).fetchone()
        finally:
            conn.close()
        if durable_peer != (role, site_id):
            raise AuthError(
                "Service-peer config role/site differs from durable identity state"
            )
        configured = frozenset(principals.identities)
        active = status.active_principals(timestamp)
        if status.primary not in configured or not active.issubset(configured):
            raise AuthError(
                "Service-peer config does not cover durable active identities"
            )


def _storefront_signer():
    signer = _container.resolved_marketplace_signer
    if signer is None:
        raise AuthError("Storefront marketplace signer is unavailable", status_code=503)
    return signer


def _callback(request: Request, body: Any) -> ServiceCallback | None:
    path = request.url.path.rstrip("/")
    if request.method == "GET" and path == "/api/v1/system/status":
        configured = [
            (site_id, principal)
            for role, site_id, principal in get_service_peer_configs().values()
            if role == "service"
        ]
        if len(configured) != 1:
            raise AuthError(
                "System status requires exactly one configured service peer",
                status_code=503,
            )
        return ServiceCallback(
            "GET",
            "admin_system_status",
            "system/status",
            configured[0][0],
            EMPTY_BODY,
        )
    operation = _CALLBACK_OPERATIONS.get(path)
    if operation is None or request.method != "POST":
        return None
    if not isinstance(body, dict):
        raise AuthError("Malformed provisioning callback body", status_code=400)
    resource = body.get("capacity_reservation_id")
    site_id = body.get("site_id")
    if not isinstance(resource, str) or not resource:
        raise AuthError(
            "Provisioning callback requires capacity_reservation_id",
            status_code=400,
        )
    if not isinstance(site_id, str) or not site_id:
        raise AuthError("Provisioning callback requires site_id", status_code=400)
    return ServiceCallback("POST", operation, resource, site_id, body)


def _allowed_service_principals(
    *, db_path: str, site_id: str, now: int
) -> frozenset[Identity]:
    configured = [
        peer_id
        for peer_id, (role, configured_site, _principal) in
        get_service_peer_configs().items()
        if role == "service" and configured_site == site_id
    ]
    if len(configured) != 1:
        raise AuthError(
            "Provisioning site must have exactly one configured service peer"
        )
    configured_peer_id = configured[0]
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT role, site_id, principal_scheme, principal_identifier, status
            FROM service_peers WHERE peer_id=?
            """,
            (configured_peer_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AuthError("Configured provisioning service peer is not materialized")
    role, durable_site, scheme, identifier, peer_status = row
    if role != "service" or durable_site != site_id:
        raise AuthError("Provisioning service peer binding differs from public config")
    if peer_status != "active":
        raise AuthError("Provisioning service peer is not active")
    try:
        status = StorefrontIdentityAuthority(db_path).status(
            authority=SERVICE_PEER_AUTHORITY,
            subject=configured_peer_id,
        )
    except KeyError as exc:
        raise AuthError("Provisioning service peer trust binding is incomplete") from exc
    durable_primary = Identity(scheme=scheme, identifier=identifier)
    if status.primary != durable_primary:
        raise AuthError(
            "Provisioning service peer row differs from its durable primary binding"
        )
    principals = status.active_principals(now)
    if not principals:
        raise AuthError("Provisioning service peer has no active principal")
    return principals


async def _authenticate(
    *, request: Request, callback: ServiceCallback
) -> AuthenticatedPrincipal:
    db = _container.resolved_sqlite_client
    if db is None:
        raise AuthError("Storefront identity state is unavailable", status_code=503)
    now = int(time.time())
    allowed = await asyncio.to_thread(
        _allowed_service_principals,
        db_path=db.db_path,
        site_id=callback.site_id,
        now=now,
    )
    return await authenticate_request(
        headers=request.headers,
        method=callback.method,
        operation=callback.operation,
        resource=callback.resource,
        body=callback.body,
        expected_role="service",
        allowed_principals=allowed,
        replay_store=db,
        now=now,
    )


def _decoded_body(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw.decode("utf-8", errors="replace")


def _signed_response(
    *, callback: ServiceCallback, auth: AuthenticatedPrincipal, status: int, body: Any
) -> dict[str, str]:
    return signed_response_headers(
        signer=_storefront_signer(),
        role="seller",
        method=callback.method,
        operation=callback.operation,
        resource=callback.resource,
        request_id=auth.request_id,
        status=status,
        body=body,
    )


async def _completed_response(
    *, response: Response, callback: ServiceCallback, auth: AuthenticatedPrincipal
) -> Response:
    raw = b"".join([chunk async for chunk in response.body_iterator])
    body = _decoded_body(raw)
    db = _container.resolved_sqlite_client
    if db is None:
        raise RuntimeError("Storefront replay state is unavailable")
    await db.record_replay_outcome(
        auth.reservation,
        attempt_token=auth.attempt_token,
        status=response.status_code,
        body=body,
    )
    headers = dict(response.headers)
    headers.update(
        _signed_response(
            callback=callback,
            auth=auth,
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


def _retry_response(
    *, callback: ServiceCallback, auth: AuthenticatedPrincipal
) -> Response:
    if auth.recorded_outcome is None:
        status = 409
        body: Any = {"detail": "request retry is pending"}
    else:
        status, body = auth.recorded_outcome
    return JSONResponse(
        status_code=status,
        content=body,
        headers=_signed_response(
            callback=callback,
            auth=auth,
            status=status,
            body=body,
        ),
    )


async def service_peer_callback_middleware(request: Request, call_next):
    """Authenticate service callbacks before dispatch and sign their responses."""

    path = request.url.path.rstrip("/")
    is_callback = request.method == "POST" and path in _CALLBACK_OPERATIONS
    is_status = (
        request.method == "GET"
        and path == "/api/v1/system/status"
        and request.headers.get("X-Market-Role") == "service"
    )
    if not is_callback and not is_status:
        return await call_next(request)
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else EMPTY_BODY
    except (TypeError, ValueError):
        body = None
    try:
        callback = _callback(request, body)
        assert callback is not None
        auth = await _authenticate(request=request, callback=callback)
        if auth.exact_retry:
            return _retry_response(callback=callback, auth=auth)
        _storefront_signer()
        request.state.service_peer_authenticated = True
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Provisioning service callback failed after authentication")
            response = JSONResponse(
                status_code=500,
                content={"detail": "Provisioning callback failed"},
            )
        return await _completed_response(
            response=response,
            callback=callback,
            auth=auth,
        )
    except AuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
