"""Shared RFQ entry points for private responses and introductions."""

from collections.abc import Callable
from functools import partial
from typing import Any

from fastapi import APIRouter, Request, Response
from market_core.rfq import OfferResponse, ResponseVersion, RfqInput, RfqOperation, RfqTarget, ShareContact

from core_registry.api.rfq_exchange import rfq_reply
from core_registry.api.rfq_routes import DbSession, rfq_action_exchange
from core_registry.rfq_spec import RfqSpec
from core_registry.rfq_context import VerifiedRfqRequest
from core_registry.rfq_responses import RfqResponses

router = APIRouter(tags=["rfqs"])


async def _exchange(
    request: Request, db: DbSession, operation: RfqOperation,
    rfq_id: str | None = None, response_id: str | None = None, introduction_id: str | None = None,
) -> Response:
    try:
        target = RfqTarget(operation, rfq_id, response_id, introduction_id)
    except ValueError:
        return rfq_reply(
            request, operation, RfqTarget.bind_resource(rfq_id, response_id, introduction_id),
            422, {"detail": "invalid_rfq_reference"},
        )
    keys = getattr(request.app.state, "rfq_contact_keys", None)

    def handler(spec: RfqSpec, verified: VerifiedRfqRequest) -> Callable[[], Any]:
        assert keys is not None
        invocation = verified.invocation
        service = RfqResponses(db, spec, invocation.account, invocation.audience, keys)
        inputs = invocation.inputs
        action = target.operation

        if target.introduction_id is not None:
            if action is RfqOperation.READ_INTRODUCTION:
                RfqInput.model_validate(inputs)
                return partial(service.read_introduction, target.introduction_id)
            return partial(service.end_introduction, target.introduction_id, ResponseVersion.model_validate(inputs))

        rfq_id = target.rfq_id
        assert rfq_id is not None
        if action is RfqOperation.RESPOND:
            return partial(service.respond, rfq_id, OfferResponse.model_validate(inputs))
        if action is RfqOperation.LIST_RESPONSES:
            RfqInput.model_validate(inputs)
            return partial(service.inbox, rfq_id)

        response_id = target.response_id
        assert response_id is not None
        if action is RfqOperation.READ_RESPONSE:
            RfqInput.model_validate(inputs)
            return partial(service.read, rfq_id, response_id)
        if action is RfqOperation.RECONFIRM:
            return partial(service.reconfirm, rfq_id, response_id, OfferResponse.model_validate(inputs))
        if action is RfqOperation.SELECT:
            return partial(service.select, rfq_id, response_id, ShareContact.model_validate(inputs))
        if action is RfqOperation.WITHDRAW:
            return partial(service.finish_pending, rfq_id, response_id, ResponseVersion.model_validate(inputs), "withdrawn")
        if action is RfqOperation.DISMISS:
            return partial(service.finish_pending, rfq_id, response_id, ResponseVersion.model_validate(inputs), "dismissed")
        raise AssertionError("unsupported response operation")

    return await rfq_action_exchange(request, db, target, handler)


@router.post(RfqOperation.RESPOND.route)
async def respond(request: Request, rfq_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.RESPOND, rfq_id=rfq_id)


@router.post(RfqOperation.LIST_RESPONSES.route)
async def list_responses(request: Request, rfq_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.LIST_RESPONSES, rfq_id=rfq_id)


@router.post(RfqOperation.READ_RESPONSE.route)
async def read_response(request: Request, rfq_id: str, response_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.READ_RESPONSE, rfq_id, response_id)


@router.post(RfqOperation.RECONFIRM.route)
async def reconfirm(request: Request, rfq_id: str, response_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.RECONFIRM, rfq_id, response_id)


@router.post(RfqOperation.WITHDRAW.route)
async def withdraw(request: Request, rfq_id: str, response_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.WITHDRAW, rfq_id, response_id)


@router.post(RfqOperation.DISMISS.route)
async def dismiss(request: Request, rfq_id: str, response_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.DISMISS, rfq_id, response_id)


@router.post(RfqOperation.SELECT.route)
async def select(request: Request, rfq_id: str, response_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.SELECT, rfq_id, response_id)


@router.post(RfqOperation.READ_INTRODUCTION.route)
async def read_introduction(request: Request, introduction_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.READ_INTRODUCTION, introduction_id=introduction_id)


@router.post(RfqOperation.END_INTRODUCTION.route)
async def end_introduction(request: Request, introduction_id: str, db: DbSession) -> Response:
    return await _exchange(request, db, RfqOperation.END_INTRODUCTION, introduction_id=introduction_id)
