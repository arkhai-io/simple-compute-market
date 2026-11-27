"""RFQ posting and open discovery routes."""

from collections.abc import Callable
from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from market_core.rfq import (
    CloseRfq, CreateRfq, EditRfq, RfqInput, RfqOperation, RfqReference, RfqSearchPage, RfqSummary, RfqTarget, SearchRfqs,
)
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from core_registry.api.market_auth import (
    IDENTITY_IDENTIFIER_HEADER, IDENTITY_SCHEME_HEADER, REQUEST_ID_HEADER, ROLE_HEADER,
    SIGNATURE_HEADER, SIGNATURE_VERSION_HEADER, TIMESTAMP_HEADER, wire_body,
)
from core_registry.api.rfq_exchange import rfq_exchange, rfq_reply
from core_registry.rfq_spec import RfqInputError, RfqSpec
from core_registry.db.database import get_db
from core_registry.rfq_contact_crypto import RfqContactUnavailable
from core_registry.rfq_context import VerifiedRfqRequest
from core_registry.rfq_requests import RfqActionError, RfqDiscovery, RfqRequests

router = APIRouter(tags=["rfqs"])
DbSession = Annotated[Session, Depends(get_db)]
_ACCOUNT_HEADERS = (
    "Authorization", IDENTITY_IDENTIFIER_HEADER, IDENTITY_SCHEME_HEADER, ROLE_HEADER,
    SIGNATURE_HEADER, SIGNATURE_VERSION_HEADER, TIMESTAMP_HEADER,
)
_PUBLIC_OPERATIONS = frozenset({RfqOperation.SEARCH, RfqOperation.READ})
_REQUEST_ID = TypeAdapter(RfqReference)


async def rfq_action_exchange(
    request: Request,
    db: Session,
    target: RfqTarget,
    handler: Callable[[RfqSpec, VerifiedRfqRequest], Callable[[], Any]],
) -> Response:
    spec = getattr(request.app.state, "rfq_spec", None)
    contact_keys = getattr(request.app.state, "rfq_contact_keys", None)

    def prepare(verified: VerifiedRfqRequest) -> Callable[[], Any]:
        assert spec is not None
        try:
            action = handler(spec, verified)
        except ValidationError as exc:
            raise HTTPException(422, "invalid_rfq_input") from exc

        def dispatch() -> Any:
            try:
                return action()
            except RfqInputError as exc:
                raise HTTPException(422, str(exc)) from exc
            except RfqActionError as exc:
                raise HTTPException(exc.status, exc.code) from exc
            except RfqContactUnavailable as exc:
                raise HTTPException(503, "rfq_contact_unavailable") from exc

        return dispatch

    return await rfq_exchange(request, db, target, prepare, available=spec is not None and contact_keys is not None)


async def _public_exchange(request: Request, db: Session, target: RfqTarget) -> Response:
    state = request.app.state
    try:
        trust = state.rfq_trust
        spec = state.rfq_spec
        if trust is None or spec is None or state.rfq_replay_keys is None or state.rfq_contact_keys is None:
            raise HTTPException(503, "rfq_not_available")
        if state.registry_descriptor.access.posture != "public":
            raise HTTPException(401, "rfq_auth_required")
        _REQUEST_ID.validate_python(request.headers.get(REQUEST_ID_HEADER))
        discovery = RfqDiscovery(db, spec, trust.audience)
        raw = await request.body()
        inputs = wire_body(raw) if raw else {}
        result: RfqSearchPage | RfqSummary
        if target.operation is RfqOperation.SEARCH:
            result = discovery.search(SearchRfqs.model_validate(inputs))
        else:
            assert target.rfq_id is not None
            RfqInput.model_validate(inputs)
            result = discovery.read_open(target.rfq_id)
        status, body = 200, result.model_dump(mode="json", exclude_none=True)
    except ValidationError:
        status, body = 422, {"detail": "invalid_rfq_input"}
    except RfqInputError as error:
        status, body = 422, {"detail": str(error)}
    except RfqActionError as error:
        status, body = error.status, {"detail": error.code}
    except HTTPException as error:
        status, body = error.status_code, {"detail": error.detail}
    return rfq_reply(request, target.operation, target.resource, status, body)


async def _exchange(request: Request, db: Session, target: RfqTarget) -> Response:
    if target.operation in _PUBLIC_OPERATIONS and not any(header in request.headers for header in _ACCOUNT_HEADERS):
        return await _public_exchange(request, db, target)

    def handler(spec: RfqSpec, verified: VerifiedRfqRequest) -> Callable[[], Any]:
        invocation = verified.invocation
        service = RfqRequests(db, spec, invocation.account, invocation.audience)
        inputs = invocation.inputs
        if target.operation is RfqOperation.CREATE:
            return partial(service.create, CreateRfq.model_validate(inputs))
        if target.operation is RfqOperation.SEARCH:
            return partial(service.search, SearchRfqs.model_validate(inputs))
        assert target.rfq_id is not None
        if target.operation is RfqOperation.READ:
            RfqInput.model_validate(inputs)
            return partial(service.read, target.rfq_id)
        if target.operation is RfqOperation.EDIT:
            return partial(service.edit, target.rfq_id, EditRfq.model_validate(inputs))
        if target.operation is RfqOperation.CLOSE:
            return partial(service.close, target.rfq_id, CloseRfq.model_validate(inputs))
        raise AssertionError("unsupported request operation")

    return await rfq_action_exchange(request, db, target, handler)


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
