"""Schema-opaque HTTP routes owned by the bare-metal composition."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any
from urllib.parse import quote, urlencode

from core_storefront.auth import AuthError, authenticate_request
from core_storefront.models.listing_models import (
    EvaluateNegotiateRequest,
    EvaluateNegotiateResponse,
    ListingListResponse,
    ListingResponse,
)
from core_storefront.models.negotiation_models import (
    ForceAcceptRequest,
    ForceAcceptResponse,
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from core_storefront.models.settle_models import RefundSettlementResponse
from core_storefront.models.system_models import (
    STAGE_EVENT_PAGE_CAP,
    AdminPauseResponse,
)
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from market_contact_exchange import (
    DELETE_INTRODUCTION_PAYLOADS_OPERATION,
    INTRODUCTION_PAYLOADS_ROUTE,
    AuthorizedIntroductionRequest,
    IntroductionRouteError,
    IntroductionStart,
)
from market_identity import EMPTY_BODY, Identity
from market_negotiation_runtime import (
    NegotiationStateError,
    NegotiationUnavailableError,
    OfferUnfulfillableError,
    StorefrontPausedError,
)
from market_pool_overrides import (
    POOL_OVERRIDES_PATH,
    PoolOverrideContractError,
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideResponse,
    PoolOverrideRouteError,
    PoolOverrideRouteService,
    PoolOverrideWriteResponse,
    pool_override_contract,
)
from market_storefront_kit import (
    DealControlRouteError,
    LifecycleRouteError,
    NegotiationControlRouteService,
    StageEventRouteService,
    StorefrontLifecycleRouteService,
    TradingPauseRouteService,
    get_storefront_container,
    opening_proposal,
)
from storefront_client.settlement_routes import REFUND, SETTLE, SETTLE_STATUS

from .fulfillment_service import BareMetalFulfillmentError
from .models import (
    BareMetalAccessDeliveryResponse,
    BareMetalFulfillmentResponse,
    BareMetalFulfillmentResultResponse,
    BareMetalFulfillRequest,
    BareMetalHealthResponse,
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettleStatusResponse,
)
from .negotiation_runtime import BareMetalNegotiationRefusal, exact_selection
from .response_auth import bind_response_auth, bind_response_contract
from .runtime import BareMetalStorefrontRuntime
from .settlement_service import PaymentSettleResult, SettlementRequestError

router = APIRouter()


def _runtime(request: Request) -> BareMetalStorefrontRuntime:
    try:
        runtime = get_storefront_container(request)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="storefront runtime unavailable",
        ) from exc
    if not isinstance(runtime, BareMetalStorefrontRuntime):
        raise HTTPException(status_code=503, detail="storefront runtime unavailable")
    return runtime


async def _principal(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    operation: str,
    resource: str,
    expected_role: str,
    expected_principal: Identity | None = None,
    allowed_principals: tuple[Identity, ...] | None = None,
    body: Any = EMPTY_BODY,
) -> Identity:
    bind_response_contract(request, operation=operation, resource=resource)
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource,
            body=body,
            expected_role=expected_role,
            replay_store=runtime.db,
            expected_principal=expected_principal,
            allowed_principals=allowed_principals,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    bind_response_auth(
        request,
        authenticated,
        operation=operation,
        resource=resource,
    )
    if not authenticated.dispatch_allowed:
        raise HTTPException(status_code=409, detail="request was already dispatched")
    return authenticated.principal


async def _buyer(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    operation: str,
    resource: str,
    expected_principal: Identity,
    body: Any = EMPTY_BODY,
) -> Identity:
    return await _principal(
        request=request,
        runtime=runtime,
        operation=operation,
        resource=resource,
        body=body,
        expected_role="buyer",
        expected_principal=expected_principal,
    )


async def _seller(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    operation: str,
    resource: str,
) -> Identity:
    return await _principal(
        request=request,
        runtime=runtime,
        operation=operation,
        resource=resource,
        expected_role="seller",
        expected_principal=runtime.seller_principal,
    )


async def _admin(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
) -> Identity:
    """Authenticate an administrator for one route's exact signed contract.

    ``operation`` and ``resource`` are the ones the canonical storefront client
    signs for the route, the same on every storefront, so one administrator
    client works against any of them.
    """
    return await _principal(
        request=request,
        runtime=runtime,
        operation=operation,
        resource=resource,
        expected_role="admin",
        allowed_principals=runtime.admin_principals.identities,
        body=body,
    )


# The query parameters a negotiation list may carry. Each is bound into the
# signed resource, so any other parameter, or a repeated one, could change what
# is returned without changing what was signed, and is refused.
_NEGOTIATION_LIST_QUERY = frozenset(
    {"limit", "offset", "buyer_identifier", "buyer_scheme", "terminal_state"}
)


def _negotiation_list_resource(request: Request, listing_id: str) -> str:
    """The signed resource of a negotiation list, rebuilt from its query.

    The canonical storefront client builds the same string: the listing, then
    the sorted, percent-encoded query with ``limit`` and ``offset`` defaulted.
    """
    query = request.query_params
    if not set(query.keys()) <= _NEGOTIATION_LIST_QUERY or any(
        len(query.getlist(name)) != 1 for name in query.keys()
    ):
        raise HTTPException(
            status_code=400,
            detail="negotiation query contains an unauthenticated alias",
        )
    values = {"limit": query.get("limit", "50"), "offset": query.get("offset", "0")}
    for name in ("buyer_identifier", "buyer_scheme", "terminal_state"):
        value = query.get(name)
        if value is not None:
            values[name] = value
    return f"{listing_id}/negotiations?" + urlencode(
        sorted(values.items()), quote_via=quote, safe=""
    )


async def _request_body(request: Request) -> Any:
    """The JSON body a signed request carried, or the empty-body marker.

    A request is verified against exactly the body its caller sent, never a
    re-serialization of the parsed model: a parsed model may drop an explicit
    ``null`` or a defaulted field, and a signature over the caller's body would
    then fail for a conforming client.
    """
    raw = await request.body()
    if not raw:
        return EMPTY_BODY
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="request body must be JSON") from exc


async def _authorize_introduction_request(
    request: Request,
    operation: str,
    resource: str,
    allowed_principals: tuple[Identity, ...],
    body: Mapping[str, Any] | None,
) -> AuthorizedIntroductionRequest:
    runtime = _runtime(request)
    bind_response_contract(request, operation=operation, resource=resource)
    role = request.headers.get("X-Market-Role", "buyer")
    if role not in {"buyer", "seller"}:
        raise IntroductionRouteError(403, "caller is not an introduction party")
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource,
            body=body if body is not None else EMPTY_BODY,
            expected_role=role,
            replay_store=runtime.db,
            allowed_principals=allowed_principals,
        )
    except AuthError as exc:
        raise IntroductionRouteError(exc.status_code, exc.detail) from exc
    bind_response_auth(
        request,
        authenticated,
        operation=operation,
        resource=resource,
    )
    return AuthorizedIntroductionRequest(
        principal=authenticated.principal,
        exact_retry=bool(authenticated.exact_retry),
        recorded_outcome=authenticated.recorded_outcome,
    )


def _introduction_service(request: Request) -> Any:
    service = _runtime(request).contact_exchange.reveal_service(
        _authorize_introduction_request
    )
    if service is None:
        raise HTTPException(status_code=404, detail="contact exchange is disabled")
    return service


@router.post("/api/v1/introductions")
async def start_introduction(
    body: IntroductionStart,
    request: Request,
) -> Mapping[str, Any]:
    try:
        return await _introduction_service(request).start(request, body)
    except IntroductionRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/v1/introductions/{obligation_ref}")
async def read_introduction(
    obligation_ref: str,
    request: Request,
) -> Mapping[str, Any]:
    try:
        return await _introduction_service(request).read(request, obligation_ref)
    except IntroductionRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.delete(INTRODUCTION_PAYLOADS_ROUTE)
async def delete_introduction_payloads(
    obligation_ref: str,
    request: Request,
) -> Mapping[str, Any]:
    """Delete one introduction's contact payloads now, whatever the window says.

    The same deletion operation the retention sweep runs. The deal and its
    obligation record remain; repeating the request converges.
    """
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation=DELETE_INTRODUCTION_PAYLOADS_OPERATION,
        resource=obligation_ref,
    )
    retention = runtime.introduction_retention()
    if retention is None:
        raise HTTPException(status_code=404, detail="contact exchange is disabled")
    return await retention.delete_one(obligation_ref)


def _listing_response(
    runtime: BareMetalStorefrontRuntime, row: dict[str, Any]
) -> dict[str, Any]:
    raw = row.get("listing_resource")
    if isinstance(raw, str):
        raw = json.loads(raw)
    runtime.domain.codecs.listing(raw)
    normalized = dict(row)
    normalized["listing_resource"] = raw
    return normalized


@router.get("/api/v1/listings", response_model=ListingListResponse)
async def list_listings(
    request: Request,
    status: str | None = None,
    paused: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListingListResponse:
    runtime = _runtime(request)
    rows = await runtime.db.list_listings(
        status=status,
        paused=paused,
        limit=limit,
        offset=offset,
    )
    listings = [_listing_response(runtime, row) for row in rows]
    return ListingListResponse(
        listings=listings,
        count=len(listings),
        limit=limit,
        offset=offset,
        total_after_filter=len(listings),
    )


@router.get("/api/v1/listings/{listing_id}", response_model=ListingResponse)
async def get_listing(listing_id: str, request: Request) -> ListingResponse:
    runtime = _runtime(request)
    row = await runtime.db.load_listing(listing_id=listing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="listing not found")
    return ListingResponse.model_validate(_listing_response(runtime, row))


def _negotiation_error(exc: Exception) -> HTTPException:
    """The HTTP answer to a negotiation the runtime or the domain refused."""
    if isinstance(exc, BareMetalNegotiationRefusal):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    if isinstance(exc, StorefrontPausedError):
        return HTTPException(
            status_code=503, detail={"error": "paused", "reason": exc.reason}
        )
    if isinstance(exc, NegotiationUnavailableError):
        # The listing's source could not be confirmed; a retry may succeed.
        return HTTPException(
            status_code=503,
            detail={"error": "listing_source_unavailable", "reason": exc.reason},
        )
    if isinstance(exc, OfferUnfulfillableError):
        return HTTPException(
            status_code=409,
            detail={"error": "offer_unfulfillable", "reason": exc.reason},
        )
    if isinstance(exc, NegotiationStateError):
        message = str(exc)
        status = 404 if message.startswith("Unknown negotiation") else 409
        return HTTPException(status_code=status, detail=message)
    return HTTPException(status_code=400, detail=str(exc))


_NEGOTIATION_REFUSALS = (
    BareMetalNegotiationRefusal,
    StorefrontPausedError,
    NegotiationUnavailableError,
    OfferUnfulfillableError,
    NegotiationStateError,
    ValueError,
)


@router.post("/api/v1/negotiate/new", response_model=NegotiateNewResponse)
async def negotiate_new(
    body: NegotiateNewRequest,
    request: Request,
) -> NegotiateNewResponse:
    runtime = _runtime(request)
    try:
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation="negotiate_new",
            resource=body.listing_id,
            body=await _request_body(request),
            expected_principal=body.buyer_principal,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        selection = exact_selection(body.proposal, body.settlement_selection)
        result = await runtime.negotiation_runtime.start(
            repository=runtime.db,
            listing_id=body.listing_id,
            buyer_principal=identity,
            seller_principal=runtime.seller_principal,
            actor_principal=identity,
            proposal=opening_proposal(body.proposal, selection),
            terms=body.provision_terms,
            seller_agent_url=runtime.storefront_url,
            buyer_agent_url=body.buyer_agent_url,
        )
    except _NEGOTIATION_REFUSALS as exc:
        raise _negotiation_error(exc) from exc
    return NegotiateNewResponse(**result)


@router.post(
    "/api/v1/negotiate/{negotiation_id}",
    response_model=NegotiateContinueResponse,
)
async def negotiate_continue(
    negotiation_id: str,
    body: NegotiateContinueRequest,
    request: Request,
) -> NegotiateContinueResponse:
    runtime = _runtime(request)
    identity = await _buyer(
        request=request,
        runtime=runtime,
        operation="negotiate_continue",
        resource=negotiation_id,
        body=await _request_body(request),
        expected_principal=body.buyer_principal,
    )
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    if Identity.model_validate(thread.get("buyer_principal")) != identity:
        raise HTTPException(status_code=403, detail="negotiation buyer mismatch")
    if body.action == "counter" and body.proposal is None and body.settlement_selection is None:
        raise HTTPException(
            status_code=400,
            detail="'proposal' or 'settlement_selection' required for counter",
        )
    try:
        result = await runtime.negotiation_runtime.continue_negotiation(
            repository=runtime.db,
            negotiation_id=negotiation_id,
            buyer_action=body.action,
            buyer_proposal=opening_proposal(body.proposal, body.settlement_selection),
            buyer_reason=body.reason,
            buyer_principal=body.buyer_principal,
            actor_principal=identity,
            actor_role="buyer",
            seller_principal=runtime.seller_principal,
        )
    except _NEGOTIATION_REFUSALS as exc:
        raise _negotiation_error(exc) from exc
    return NegotiateContinueResponse(**result)


def _negotiation_controls(runtime: BareMetalStorefrontRuntime) -> NegotiationControlRouteService:
    return NegotiationControlRouteService(
        runtime=runtime.negotiation_runtime,
        repository=runtime.db,
        seller_principal=lambda: runtime.seller_principal,
    )


@router.post(
    "/api/v1/admin/listings/{listing_id}/evaluate-negotiate",
    response_model=EvaluateNegotiateResponse,
)
async def evaluate_negotiate(
    listing_id: str,
    body: EvaluateNegotiateRequest,
    request: Request,
) -> EvaluateNegotiateResponse:
    """Preview the opening ``negotiate/new`` would receive, writing nothing."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_evaluate_negotiation",
        resource=listing_id,
        body=await _request_body(request),
    )
    return await _negotiation_controls(runtime).evaluate_negotiate(listing_id, body)


@router.post(
    "/api/v1/listings/{listing_id}/negotiations/{negotiation_id}/force-accept",
    response_model=ForceAcceptResponse,
)
async def force_accept_negotiation(
    listing_id: str,
    negotiation_id: str,
    body: ForceAcceptRequest,
    request: Request,
) -> ForceAcceptResponse:
    """Accept a negotiation at an administrator's amount, as a negotiated acceptance would."""
    runtime = _runtime(request)
    actor = await _admin(
        request=request,
        runtime=runtime,
        operation="admin_force_accept_negotiation",
        resource=f"{listing_id}/{negotiation_id}",
        body=await _request_body(request),
    )
    try:
        return await _negotiation_controls(runtime).force_accept(
            listing_id, negotiation_id, body, actor_principal=actor
        )
    except DealControlRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except BareMetalNegotiationRefusal as exc:
        # Acceptance builds the domain's artifacts, so it can refuse for a
        # reason the domain owns; it answers as negotiate/{id} would.
        raise _negotiation_error(exc) from exc


@router.get("/api/v1/system/events")
async def read_events(
    request: Request,
    since_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=STAGE_EVENT_PAGE_CAP)] = 100,
    stage: Annotated[str | None, Query()] = None,
    listing_id: Annotated[str | None, Query()] = None,
    negotiation_id: Annotated[str | None, Query()] = None,
) -> Any:
    """A page of this storefront's stage-event log; a signed read is never a stream."""
    runtime = _runtime(request)
    try:
        resource = StageEventRouteService.signed_resource(request.query_params.multi_items())
    except DealControlRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_system_events",
        resource=resource,
    )
    events = StageEventRouteService(runtime.db)
    return await events.page(
        since_id=events.resume_point(since_id, request.headers.get("last-event-id")),
        limit=limit,
        stage=stage,
        listing_id=listing_id,
        negotiation_id=negotiation_id,
    )


@router.get(
    "/api/v1/listings/{listing_id}/negotiations",
    response_model=NegotiationListResponse,
)
async def list_negotiations(
    listing_id: str,
    request: Request,
    terminal_state: str | None = None,
    buyer_scheme: str | None = None,
    buyer_identifier: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NegotiationListResponse:
    """A listing's negotiation threads, for the storefront's administrator.

    Threads carry buyer principals and agreed terms, so they are read only
    through the administrator's signed contract, whose response is signed.
    """
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_list_negotiations",
        resource=_negotiation_list_resource(request, listing_id),
    )
    if (buyer_scheme is None) != (buyer_identifier is None):
        raise HTTPException(
            status_code=422,
            detail="buyer_scheme and buyer_identifier must be supplied together",
        )
    try:
        buyer_principal = (
            Identity(scheme=buyer_scheme, identifier=buyer_identifier)
            if buyer_scheme is not None and buyer_identifier is not None
            else None
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid buyer principal") from exc
    if await runtime.db.load_listing(listing_id=listing_id) is None:
        raise HTTPException(status_code=404, detail="listing not found")
    rows = await runtime.db.list_negotiations_for_listing(
        listing_id=listing_id,
        terminal_state=terminal_state,
        buyer_principal=buyer_principal,
        limit=limit,
        offset=offset,
    )
    return NegotiationListResponse(
        listing_id=listing_id,
        negotiations=rows,
        count=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/v1/listings/{listing_id}/negotiations/{negotiation_id}",
    response_model=NegotiationDetailResponse,
)
async def get_negotiation(
    listing_id: str,
    negotiation_id: str,
    request: Request,
) -> NegotiationDetailResponse:
    """One negotiation thread, for the storefront's administrator."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_get_negotiation",
        resource=f"{listing_id}/negotiations/{negotiation_id}",
    )
    detail = await runtime.db.load_negotiation_detail(
        listing_id=listing_id,
        neg_id=negotiation_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    return NegotiationDetailResponse.model_validate(detail)


@router.post(
    "/api/v1/settle/{escrow_uid}",
    response_model=None,
)
async def settle(
    escrow_uid: str,
    body: BareMetalSettleRequest,
    request: Request,
) -> BareMetalSettleResponse | JSONResponse:
    runtime = _runtime(request)
    try:
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation=SETTLE.operation,
            resource=escrow_uid,
            body=await _request_body(request),
            expected_principal=body.buyer_principal,
        )
        result = await runtime.settlement_service().verify(
            escrow_uid=escrow_uid,
            request=body,
            buyer_principal=identity,
        )
    except (AuthError, SettlementRequestError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if isinstance(result, PaymentSettleResult):
        return JSONResponse(content=result.payload, status_code=result.status_code)
    return result


@router.post(
    "/api/v1/settlements/{negotiation_id}/refund",
    response_model=RefundSettlementResponse,
)
async def refund_settlement(negotiation_id: str, request: Request) -> JSONResponse:
    """Refund an accepted deal through its seller entry; only the seller may ask."""
    runtime = _runtime(request)
    await _seller(
        request=request,
        runtime=runtime,
        operation=REFUND.operation,
        resource=negotiation_id,
    )
    try:
        result = await runtime.settlement_service().refund(
            negotiation_id=negotiation_id
        )
    except SettlementRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(content=result.payload, status_code=result.status_code)


@router.get(
    "/api/v1/settle/{escrow_uid}/status",
    response_model=BareMetalSettleStatusResponse,
)
async def settle_status(
    escrow_uid: str,
    request: Request,
) -> BareMetalSettleStatusResponse:
    runtime = _runtime(request)
    try:
        record = await runtime.db.load_bare_metal_settlement_record_by_ref(
            settlement_ref=escrow_uid
        ) or await runtime.db.load_bare_metal_settlement_record(negotiation_id=escrow_uid)
        if record is None:
            raise SettlementRequestError("settlement not found", status_code=404)
        thread = await runtime.db.load_negotiation_thread_row(
            negotiation_id=str(record["negotiation_id"]),
        )
        if thread is None:
            raise SettlementRequestError("negotiation not found", status_code=404)
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation=SETTLE_STATUS.operation,
            expected_principal=Identity.model_validate(thread["buyer_principal"]),
            resource=escrow_uid,
        )
        return await runtime.settlement_service().status(
            escrow_uid=escrow_uid,
            buyer_principal=identity,
        )
    except (AuthError, SettlementRequestError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def _fulfillment_identity(
    *,
    request: Request,
    runtime: BareMetalStorefrontRuntime,
    negotiation_id: str,
    operation: str,
) -> Identity:
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if thread is None:
        raise BareMetalFulfillmentError(
            "negotiation not found",
            status_code=404,
        )
    return await _buyer(
        request=request,
        runtime=runtime,
        operation=operation,
        resource=negotiation_id,
        expected_principal=Identity.model_validate(thread["buyer_principal"]),
    )


@router.post(
    "/api/v1/fulfillments/begin",
    response_model=BareMetalFulfillmentResponse,
)
async def begin_fulfillment(
    body: BareMetalFulfillRequest,
    request: Request,
) -> BareMetalFulfillmentResponse:
    runtime = _runtime(request)
    try:
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation="bare_metal_fulfillment_begin",
            resource=body.negotiation_id,
            expected_principal=body.buyer_principal,
            body=await _request_body(request),
        )
        lifecycle = await runtime.fulfillment_service().begin(
            negotiation_id=body.negotiation_id,
            settlement_ref=body.escrow_uid,
            buyer_principal=identity,
        )
        return BareMetalFulfillmentResponse.model_validate(
            {**lifecycle, "escrow_uid": lifecycle["settlement_ref"]}
        )
    except BareMetalFulfillmentError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@router.get(
    "/api/v1/fulfillments/{negotiation_id}/status",
    response_model=BareMetalFulfillmentResponse,
)
async def fulfillment_status(
    negotiation_id: str,
    request: Request,
) -> BareMetalFulfillmentResponse:
    runtime = _runtime(request)
    try:
        identity = await _fulfillment_identity(
            request=request,
            runtime=runtime,
            negotiation_id=negotiation_id,
            operation="bare_metal_fulfillment_status",
        )
        lifecycle = await runtime.fulfillment_service().status(
            negotiation_id=negotiation_id,
            buyer_principal=identity,
        )
        return BareMetalFulfillmentResponse.model_validate(
            {**lifecycle, "escrow_uid": lifecycle["settlement_ref"]}
        )
    except BareMetalFulfillmentError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@router.get(
    "/api/v1/fulfillments/{negotiation_id}/access",
    response_model=BareMetalAccessDeliveryResponse,
)
async def fulfillment_access(
    negotiation_id: str,
    request: Request,
) -> BareMetalAccessDeliveryResponse:
    runtime = _runtime(request)
    try:
        identity = await _fulfillment_identity(
            request=request,
            runtime=runtime,
            negotiation_id=negotiation_id,
            operation="bare_metal_fulfillment_access",
        )
        access = await runtime.fulfillment_service().access(
            negotiation_id=negotiation_id,
            buyer_principal=identity,
        )
        return BareMetalAccessDeliveryResponse.model_validate(access)
    except BareMetalFulfillmentError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@router.get(
    "/api/v1/fulfillments/{negotiation_id}/result",
    response_model=BareMetalFulfillmentResultResponse,
)
async def fulfillment_result(
    negotiation_id: str,
    request: Request,
) -> BareMetalFulfillmentResultResponse:
    runtime = _runtime(request)
    try:
        identity = await _fulfillment_identity(
            request=request,
            runtime=runtime,
            negotiation_id=negotiation_id,
            operation="bare_metal_fulfillment_result",
        )
        lifecycle = await runtime.fulfillment_service().status(
            negotiation_id=negotiation_id,
            buyer_principal=identity,
        )
        if lifecycle["state"] not in {
            "active",
            "teardown_dispatch_pending",
            "tearing_down",
            "teardown_failed",
            "torn_down",
            "released",
        }:
            raise BareMetalFulfillmentError(
                "bare-metal fulfillment result is not ready"
            )
        receipt = await runtime.db.load_bare_metal_receipt(
            negotiation_id=negotiation_id,
        )
        result = await runtime.db.load_bare_metal_result(
            negotiation_id=negotiation_id,
        )
        if receipt is None or result is None:
            raise BareMetalFulfillmentError(
                "bare-metal fulfillment result is not ready"
            )
        return BareMetalFulfillmentResultResponse(
            negotiation_id=negotiation_id,
            receipt=receipt,
            result=result,
        )
    except BareMetalFulfillmentError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@router.post(
    "/api/v1/fulfillments/{negotiation_id}/teardown",
    response_model=BareMetalFulfillmentResponse,
)
async def teardown_fulfillment(
    negotiation_id: str,
    request: Request,
) -> BareMetalFulfillmentResponse:
    runtime = _runtime(request)
    try:
        identity = await _fulfillment_identity(
            request=request,
            runtime=runtime,
            negotiation_id=negotiation_id,
            operation="bare_metal_fulfillment_teardown",
        )
        lifecycle = await runtime.fulfillment_service().teardown(
            negotiation_id=negotiation_id,
            buyer_principal=identity,
        )
        return BareMetalFulfillmentResponse.model_validate(
            {**lifecycle, "escrow_uid": lifecycle["settlement_ref"]}
        )
    except BareMetalFulfillmentError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@router.get("/health", response_model=BareMetalHealthResponse)
@router.get("/api/v1/system/health", response_model=BareMetalHealthResponse)
async def health(request: Request) -> BareMetalHealthResponse:
    return BareMetalHealthResponse.model_validate(await _runtime(request).health())


@router.get("/api/v1/system/status", response_model=BareMetalHealthResponse)
async def system_status(request: Request) -> BareMetalHealthResponse:
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_system_status",
        resource="system/status",
    )
    status = await runtime.health()
    overrides = runtime.pool_override_service()
    if overrides is not None:
        status["pool_overrides"] = await overrides.statuses()
    return BareMetalHealthResponse.model_validate(status)


# -- storefront pool overrides ----------------------------------------------
# Site and pool identifiers are operator-chosen strings with no character
# restriction, so they travel in the body or query, never the path. Each route
# authenticates against the kit's contract, the one its client signs.


async def _pool_override_request(request: Request) -> tuple[Any, PoolOverrideRouteService]:
    runtime = _runtime(request)
    body = await _request_body(request) if request.method == "PUT" else EMPTY_BODY
    try:
        contract = pool_override_contract(
            request.method, request.query_params.multi_items(), body
        )
    except PoolOverrideContractError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _admin(
        request=request,
        runtime=runtime,
        operation=contract.operation,
        resource=contract.resource,
        body=contract.body,
    )
    return contract.body, PoolOverrideRouteService(runtime.pool_override_service())


@router.put(POOL_OVERRIDES_PATH, response_model=PoolOverrideWriteResponse)
async def put_pool_override(request: Request) -> PoolOverrideWriteResponse:
    body, routes = await _pool_override_request(request)
    try:
        return await routes.replace(body)
    except PoolOverrideRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    POOL_OVERRIDES_PATH,
    response_model=PoolOverrideResponse | PoolOverrideListResponse,
)
async def get_pool_overrides(
    request: Request,
) -> PoolOverrideResponse | PoolOverrideListResponse:
    _, routes = await _pool_override_request(request)
    query = request.query_params
    try:
        return await routes.read(
            site_id=query.get("site_id"),
            pool_id=query.get("pool_id"),
            offering_mode=query.get("offering_mode"),
        )
    except PoolOverrideRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.delete(POOL_OVERRIDES_PATH, response_model=PoolOverrideDeleteResponse)
async def delete_pool_override(request: Request) -> PoolOverrideDeleteResponse:
    _, routes = await _pool_override_request(request)
    query = request.query_params
    try:
        return await routes.delete(
            site_id=query.get("site_id"),
            pool_id=query.get("pool_id"),
            offering_mode=query.get("offering_mode"),
        )
    except PoolOverrideRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/v1/admin/pause", response_model=AdminPauseResponse)
async def pause(request: Request) -> AdminPauseResponse:
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_pause",
        resource="",
        body=await _request_body(request),
    )
    return TradingPauseRouteService(runtime.trading_pause).pause()


@router.post("/api/v1/admin/resume", response_model=AdminPauseResponse)
async def resume(request: Request) -> AdminPauseResponse:
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_resume",
        resource="",
        body=await _request_body(request),
    )
    return TradingPauseRouteService(runtime.trading_pause).resume()


# Lifecycle controls: one pause holding the timer loops, and one step per loop.
# Publication has no timer, so it is stepped and never held. The signed
# operations and resources are the canonical storefront client's, so one
# administrator client drives every storefront.


def _lifecycle_routes(runtime: BareMetalStorefrontRuntime) -> StorefrontLifecycleRouteService:
    return StorefrontLifecycleRouteService(runtime.loops)


def _lifecycle_http_error(exc: LifecycleRouteError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/api/v1/admin/lifecycle/pause")
async def pause_lifecycle_loops(request: Request) -> dict[str, Any]:
    """Hold every timer loop at its next cycle boundary; trading is unaffected."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_pause_lifecycle_loops",
        resource="lifecycle",
        body=await _request_body(request),
    )
    return await _lifecycle_routes(runtime).pause()


@router.post("/api/v1/admin/lifecycle/resume")
async def resume_lifecycle_loops(request: Request) -> dict[str, Any]:
    """Return every timer loop to work."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_resume_lifecycle_loops",
        resource="lifecycle",
        body=await _request_body(request),
    )
    return await _lifecycle_routes(runtime).resume()


@router.post("/api/v1/admin/lifecycle/{loop}/run-cycle")
async def run_lifecycle_cycle(loop: str, request: Request) -> dict[str, Any]:
    """Run one cycle of a lifecycle loop and return what it reports.

    The publication pass is exactly the one the publication command runs,
    composed the same way. Passes are serialized within this process.
    """
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_run_lifecycle_cycle",
        resource=loop,
        body=await _request_body(request),
    )
    try:
        return dict(await _lifecycle_routes(runtime).run_cycle(loop))
    except LifecycleRouteError as exc:
        raise _lifecycle_http_error(exc) from exc


@router.post("/api/v1/admin/lifecycle/{loop}/dry-run")
async def dry_run_lifecycle_cycle(loop: str, request: Request) -> dict[str, Any]:
    """Report one cycle of a lifecycle loop without applying it, where it offers a preview."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_dry_run_lifecycle_cycle",
        resource=loop,
        body=await _request_body(request),
    )
    try:
        return dict(await _lifecycle_routes(runtime).dry_run(loop))
    except LifecycleRouteError as exc:
        raise _lifecycle_http_error(exc) from exc
