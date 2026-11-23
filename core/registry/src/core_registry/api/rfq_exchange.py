"""The HTTP boundary shared by account-authenticated RFQ routes."""

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from market_core.rfq import RfqOperation, RfqTarget
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from core_registry.api.market_auth import (
    REQUEST_ID_HEADER,
    SIGNATURE_HEADER,
    registry_authority_signer,
    signed_context_response,
    wire_body,
)
from core_registry.rfq_context import VerifiedRfqRequest
from core_registry.rfq_replay import (
    RfqReplayConflict,
    RfqReplayKeyUnavailable,
    execute_rfq_request,
)


async def rfq_exchange(
    request: Request,
    session: Session,
    target: RfqTarget,
    prepare: Callable[[VerifiedRfqRequest], Callable[[], Any]],
    *,
    available: bool = True,
) -> Response:
    """Authenticate before touching request history or domain records."""
    trust = getattr(request.app.state, "rfq_trust", None)
    keys = getattr(request.app.state, "rfq_replay_keys", None)
    try:
        if trust is None or keys is None:
            raise HTTPException(503, "rfq_not_available")
        if not request.headers.get(SIGNATURE_HEADER):
            raise HTTPException(401, "rfq_auth_required")
        verified = trust.verify(
            headers=request.headers, method=request.method, target=target,
            body=wire_body(await request.body()),
        )
        if not available:
            raise HTTPException(503, "rfq_not_available")
        dispatch = prepare(verified)
        result = execute_rfq_request(session, verified, keys, dispatch)
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json", exclude_none=True)
        status, body = 200, result
    except RfqReplayConflict:
        status, body = 409, {"detail": "rfq_request_id_reused"}
    except RfqReplayKeyUnavailable:
        status, body = 503, {"detail": "rfq_receipt_key_unavailable"}
    except HTTPException as error:
        status, body = error.status_code, {"detail": error.detail}

    return rfq_reply(request, target.operation, target.resource, status, body)


def rfq_reply(
    request: Request, operation: RfqOperation, resource: str, status: int, body: Any,
) -> Response:
    signer = registry_authority_signer(request)
    try:
        response = signed_context_response(
            method=request.method, operation=operation.value, resource=resource,
            request_id=request.headers.get(REQUEST_ID_HEADER, ""),
            signer=signer, status=status, body=body,
        )
    except ValidationError:
        # A request outside the signed envelope's bounds cannot bind a proof.
        response = JSONResponse(status_code=status, content=body)
    response.headers["Cache-Control"] = "no-store"
    return response
