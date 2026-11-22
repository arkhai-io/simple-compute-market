"""The HTTP boundary shared by account-authenticated RFQ routes."""

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from market_core.rfq import RfqMutationReceipt, RfqTarget
from pydantic import ValidationError
from sqlalchemy.orm import Session

from core_registry.api.market_auth import (
    REQUEST_ID_HEADER,
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
    dispatch: Callable[[VerifiedRfqRequest], Any],
) -> Response:
    """Authenticate before touching request history or domain records."""
    request_id = request.headers.get(REQUEST_ID_HEADER, "")
    signer = registry_authority_signer(request)
    trust = request.app.state.rfq_trust
    keys = request.app.state.rfq_replay_keys
    try:
        if trust is None or keys is None:
            raise HTTPException(503, "rfq_not_available")
        verified = trust.verify(
            headers=request.headers, method=request.method, target=target,
            body=wire_body(await request.body()),
        )
        result = execute_rfq_request(session, verified, keys, lambda: dispatch(verified))
        if isinstance(result, RfqMutationReceipt):
            result = result.model_dump(mode="json", exclude_none=True)
        status, body = 200, result
    except RfqReplayConflict:
        status, body = 409, {"detail": "rfq_request_id_reused"}
    except RfqReplayKeyUnavailable:
        status, body = 503, {"detail": "rfq_receipt_key_unavailable"}
    except HTTPException as error:
        status, body = error.status_code, {"detail": error.detail}

    try:
        response = signed_context_response(
            method=request.method, operation=target.operation.value, resource=target.resource,
            request_id=request_id, signer=signer, status=status, body=body,
        )
    except ValidationError:
        # An absent or malformed request ID cannot bind a signed response.
        response = JSONResponse(status_code=status, content=body)
    response.headers["Cache-Control"] = "no-store"
    return response
