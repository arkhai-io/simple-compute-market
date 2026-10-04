"""Introduction reveal routes: the contact-exchange kit's service, bound here.

The buyer of an accepted introduction deal starts the reveal, and either party
may read it; authorization admits the buyer and seller roles against the
principals the kit names for each request, which for a start is the buyer
alone. The response is signed and its outcome recorded
by the listing lifecycle middleware, which recognizes both routes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core_storefront.auth import AuthError, authenticate_request
from fastapi import APIRouter, HTTPException, Request
from market_contact_exchange import (
    AuthorizedIntroductionRequest,
    IntroductionRouteError,
    IntroductionStart,
)
from market_identity import EMPTY_BODY, Identity

import market_storefront.container as _container

router = APIRouter(prefix="/api/v1", tags=["introductions"])

_PARTY_ROLES = frozenset({"buyer", "seller"})


async def authorize_introduction_request(
    request: Request,
    operation: str,
    resource: str,
    allowed_principals: tuple[Identity, ...],
    body: Mapping[str, Any] | None,
) -> AuthorizedIntroductionRequest:
    """Authenticate one introduction party against the deal's own principals."""

    role = request.headers.get("X-Market-Role", "buyer")
    if role not in _PARTY_ROLES:
        raise IntroductionRouteError(403, "caller is not an introduction party")
    replay_store = _container.resolved_sqlite_client
    if replay_store is None:
        raise IntroductionRouteError(503, "authentication store is unavailable")
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource,
            body=dict(body) if body is not None else EMPTY_BODY,
            expected_role=role,
            replay_store=replay_store,
            allowed_principals=allowed_principals,
        )
    except AuthError as exc:
        raise IntroductionRouteError(exc.status_code, exc.detail) from exc
    request.state.marketplace_authenticated = authenticated
    return AuthorizedIntroductionRequest(
        principal=authenticated.principal,
        exact_retry=bool(authenticated.exact_retry),
        recorded_outcome=authenticated.recorded_outcome,
    )


def _service() -> Any:
    composition = _container.resolved_contact_exchange
    service = (
        composition.reveal_service(authorize_introduction_request)
        if composition is not None
        else None
    )
    if service is None:
        raise HTTPException(status_code=404, detail="contact exchange is disabled")
    return service


@router.post("/introductions", summary="Start one accepted introduction")
async def start_introduction(body: IntroductionStart, request: Request) -> Mapping[str, Any]:
    try:
        return await _service().start(request, body)
    except IntroductionRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/introductions/{obligation_ref}", summary="Re-read one revealed introduction"
)
async def read_introduction(obligation_ref: str, request: Request) -> Mapping[str, Any]:
    try:
        return await _service().read(request, obligation_ref)
    except IntroductionRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
