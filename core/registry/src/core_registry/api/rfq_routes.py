"""Account-authenticated RFQ posting and discovery routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from market_core.rfq import (
    CloseRfq, CreateRfq, EditRfq, RfqInput, RfqOperation, RfqTarget, SearchRfqs,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session

from core_registry.api.rfq_exchange import rfq_exchange, rfq_reply
from core_registry.rfq_spec import RfqInputError
from core_registry.db.database import get_db
from core_registry.rfq_context import VerifiedRfqRequest
from core_registry.rfq_requests import RfqActionError, RfqRequests

router = APIRouter(tags=["rfqs"])
DbSession = Annotated[Session, Depends(get_db)]


async def _exchange(request: Request, db: Session, target: RfqTarget) -> Response:
    spec = getattr(request.app.state, "rfq_spec", None)

    def dispatch(verified: VerifiedRfqRequest) -> Any:
        assert spec is not None
        invocation = verified.invocation
        service = RfqRequests(db, spec, invocation.account, invocation.audience)
        inputs = invocation.inputs
        try:
            if target.operation is RfqOperation.CREATE:
                return service.create(CreateRfq.model_validate(inputs))
            if target.operation is RfqOperation.SEARCH:
                return service.search(SearchRfqs.model_validate(inputs))
            assert target.rfq_id is not None
            if target.operation is RfqOperation.READ:
                RfqInput.model_validate(inputs)
                return service.read(target.rfq_id)
            if target.operation is RfqOperation.EDIT:
                return service.edit(target.rfq_id, EditRfq.model_validate(inputs))
            if target.operation is RfqOperation.CLOSE:
                return service.close(target.rfq_id, CloseRfq.model_validate(inputs))
            raise AssertionError("unsupported request operation")
        except ValidationError as exc:
            raise HTTPException(422, "invalid_rfq_input") from exc
        except RfqInputError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RfqActionError as exc:
            raise HTTPException(exc.status, exc.code) from exc

    return await rfq_exchange(request, db, target, dispatch, available=spec is not None)


async def _keyed_exchange(request: Request, db: Session, operation: RfqOperation, rfq_id: str) -> Response:
    try:
        target = RfqTarget(operation, rfq_id)
    except ValueError:
        return rfq_reply(
            request, operation, RfqTarget.bind_resource(rfq_id), 422, {"detail": "invalid_rfq_reference"},
        )
    return await _exchange(request, db, target)


@router.post(RfqOperation.CREATE.route)
async def create_rfq(request: Request, db: DbSession) -> Response:
    return await _exchange(request, db, RfqTarget(RfqOperation.CREATE))


@router.post(RfqOperation.SEARCH.route)
async def search_rfqs(request: Request, db: DbSession) -> Response:
    return await _exchange(request, db, RfqTarget(RfqOperation.SEARCH))


@router.post(RfqOperation.READ.route)
async def read_rfq(request: Request, rfq_id: str, db: DbSession) -> Response:
    return await _keyed_exchange(request, db, RfqOperation.READ, rfq_id)


@router.post(RfqOperation.EDIT.route)
async def edit_rfq(request: Request, rfq_id: str, db: DbSession) -> Response:
    return await _keyed_exchange(request, db, RfqOperation.EDIT, rfq_id)


@router.post(RfqOperation.CLOSE.route)
async def close_rfq(request: Request, rfq_id: str, db: DbSession) -> Response:
    return await _keyed_exchange(request, db, RfqOperation.CLOSE, rfq_id)
