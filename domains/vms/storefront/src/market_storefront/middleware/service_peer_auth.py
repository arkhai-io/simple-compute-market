"""V2 authentication and signed responses for provisioning service callbacks.

A callback is verified against its site's service-peer principals, held by the
process's :class:`core_storefront.service_peers.ServicePeerTrust` -- the same
principals that site's responses are verified against. The service-role status
read names no site, so any configured site's peer may make it.
"""

from __future__ import annotations

import json
import logging
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
from core_storefront.service_peers import SERVICE_PEER_ROLE, ServicePeerTrust
from market_identity import EMPTY_BODY, Identity

import market_storefront.container as _container

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ServiceCallback:
    method: str
    operation: str
    resource: str
    #: The sites whose service peers may send the request: the one a callback
    #: names, or every configured site for the status read.
    site_ids: tuple[str, ...]
    body: Any


_CALLBACK_OPERATIONS = {
    "/api/v1/admin/fulfillment/events/capacity-released": (
        "fulfillment_capacity_released"
    ),
}


def _service_peer_trust() -> ServicePeerTrust:
    trust = _container.resolved_service_peer_trust
    if trust is None:
        raise AuthError("Storefront service-peer trust is unavailable", status_code=503)
    return trust


def _storefront_signer():
    signer = _container.resolved_marketplace_signer
    if signer is None:
        raise AuthError("Storefront marketplace signer is unavailable", status_code=503)
    return signer


def _callback(request: Request, body: Any) -> ServiceCallback | None:
    path = request.url.path.rstrip("/")
    # System status is readable by two callers, and the middlewares dispatch on
    # the asserted role: the administrator middleware hands a request asserting
    # `service` straight through to this one. A service peer reads status to
    # confirm its own signing path works, which is the only side-effect-free
    # service operation there is — the other is the capacity-released
    # callback. The read names no site and returns readiness alone, so every
    # configured site's peer may make it.
    if request.method == "GET" and path == "/api/v1/system/status":
        site_ids = tuple(
            sorted(
                {
                    site_id
                    for role, site_id, _principals in _service_peer_trust().peers.values()
                    if role == SERVICE_PEER_ROLE
                }
            )
        )
        return ServiceCallback(
            "GET",
            "admin_system_status",
            "system/status",
            site_ids,
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
    return ServiceCallback("POST", operation, resource, (site_id,), body)


async def _authenticate(
    *, request: Request, callback: ServiceCallback
) -> AuthenticatedPrincipal:
    db = _container.resolved_sqlite_client
    if db is None:
        raise AuthError("Storefront identity state is unavailable", status_code=503)
    now = int(time.time())
    allowed = _allowed_principals(_service_peer_trust(), callback.site_ids, now=now)
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


def _allowed_principals(
    trust: ServicePeerTrust, site_ids: tuple[str, ...], *, now: int
) -> frozenset[Identity]:
    """The principals that may send a request on behalf of ``site_ids`` at ``now``.

    A request naming one site is verified against that site's peer, and the
    trust's own refusal is returned when it has none to offer. A request any of
    several sites may make, the status read, is verified against the union of
    their peers' principals, skipping a site the trust cannot answer for; it is
    refused as unavailable only when the trust can answer for none of them.
    """
    if len(site_ids) == 1:
        return trust.site_active_principals(site_ids[0], now=now)
    principals: set[Identity] = set()
    answered = False
    for site_id in site_ids:
        try:
            principals |= trust.site_active_principals(site_id, now=now)
        except AuthError as exc:
            if exc.status_code == 503:
                raise
            continue
        answered = True
    if not answered:
        raise AuthError(
            "No configured site's service peer can be trusted", status_code=503
        )
    return frozenset(principals)


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
