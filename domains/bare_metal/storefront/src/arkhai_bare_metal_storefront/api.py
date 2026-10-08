"""Schema-opaque HTTP routes owned by the bare-metal composition."""

from __future__ import annotations

from collections.abc import Mapping
import json
from urllib.parse import quote, urlencode
from typing import Annotated, Any

from arkhai_bare_metal import CanonicalPrincipal
from arkhai_bare_metal.evidence_routes import (
    EVIDENCE_OPERATION,
    EVIDENCE_PATH,
    BareMetalEvidenceContractError,
    BareMetalEvidenceRouteError,
    BareMetalEvidenceRouteService,
    BareMetalSignedLeaseReadyEvidence,
    evidence_resource,
)
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
from core_storefront.models.system_models import STAGE_EVENT_PAGE_CAP, AdminPauseResponse
from fastapi import APIRouter, Body, HTTPException, Query, Request

from market_contact_exchange import (
    DELETE_INTRODUCTION_PAYLOADS_OPERATION,
    INTRODUCTION_PAYLOADS_ROUTE,
    AuthorizedIntroductionRequest,
    IntroductionRouteError,
    IntroductionStart,
)
from market_identity import EMPTY_BODY, Identity
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
from market_negotiation_runtime import (
    NegotiationStateError,
    NegotiationUnavailableError,
    OfferUnfulfillableError,
    StorefrontPausedError,
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
from market_capacity_publication import CapacityAdminRouteError
from market_settlement_runtime import (
    MAX_WAIT_SECONDS,
    HostedSettlementRouteError,
    HostedSettlementStart,
    SettlementAdminRouteError,
)
from .models import (
    BareMetalAccessDeliveryResponse,
    BareMetalCapacityEventResponse,
    BareMetalCapacityReleasedEvent,
    BareMetalEvaluateSettleRequest,
    BareMetalEvaluateSettleResponse,
    BareMetalReserveCapacityRequest,
    BareMetalSettleWaitResponse,
    BareMetalVerifyEscrowRequest,
    BareMetalVerifyEscrowResponse,
    BareMetalFulfillmentResponse,
    BareMetalFulfillmentResultResponse,
    BareMetalHealthResponse,
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettleStatusResponse,
)
from .deal_controls import capacity_admin_routes, settlement_admin_routes
from .fulfillment_service import BareMetalFulfillmentError
from .negotiation_runtime import BareMetalNegotiationRefusal, exact_selection
from .runtime import BareMetalStorefrontRuntime
from .settlement_service import SettlementRequestError
from .hosted_routes import build_bare_metal_hosted_route_service
from .response_auth import bind_response_auth, bind_response_contract

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


async def _authorize_hosted_request(
    request: Request,
    operation: str,
    resource: str,
    expected_principal: Identity,
    body: Mapping[str, Any] | None,
) -> Any:
    runtime = _runtime(request)
    bind_response_contract(request, operation=operation, resource=resource)
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource,
            body=body if body is not None else EMPTY_BODY,
            expected_role="buyer",
            replay_store=runtime.db,
            expected_principal=expected_principal,
        )
    except AuthError as exc:
        raise HostedSettlementRouteError(exc.status_code, exc.detail) from exc
    bind_response_auth(
        request,
        authenticated,
        operation=operation,
        resource=resource,
    )
    return authenticated


def _hosted_service(request: Request) -> Any:
    runtime = _runtime(request)
    if runtime.settlement_composition is None:
        raise HTTPException(status_code=404, detail="hosted settlement is disabled")
    if runtime.hosted_domain_callbacks is None:
        raise HTTPException(
            status_code=503,
            detail="bare-metal hosted lifecycle is unavailable",
        )
    return build_bare_metal_hosted_route_service(
        repository=runtime.settlement_repository,
        runtime=runtime.settlement_runtime,
        domain_callbacks=runtime.hosted_domain_callbacks,
        authorize_request=_authorize_hosted_request,
    )


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


@router.post("/api/v1/settlements")
async def start_hosted_settlement(
    body: HostedSettlementStart,
    request: Request,
) -> Mapping[str, Any]:
    try:
        return await _hosted_service(request).start(request, body)
    except HostedSettlementRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/v1/settlements/{settlement_ref}")
async def hosted_settlement_status(
    settlement_ref: str,
    request: Request,
) -> Mapping[str, Any]:
    try:
        return await _hosted_service(request).status(request, settlement_ref)
    except HostedSettlementRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/v1/settlements/{settlement_ref}/reclaim")
async def reclaim_hosted_settlement(
    settlement_ref: str,
    request: Request,
    mechanism_options: dict[str, Any] | None = Body(default=None),
) -> Mapping[str, Any]:
    """Reclaim one eligible expired hosted settlement.

    The body is the mechanism's own vocabulary for this one reclaim -- a
    push-funded profile needs somewhere to address the payer's return -- so it
    is relayed opaquely rather than parsed into a model here.
    """
    try:
        return await _hosted_service(request).reclaim(
            request, settlement_ref, mechanism_options
        )
    except HostedSettlementRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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
    response_model=BareMetalSettleResponse,
)
async def settle(
    escrow_uid: str,
    body: BareMetalSettleRequest,
    request: Request,
) -> BareMetalSettleResponse:
    runtime = _runtime(request)
    try:
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation="settle_escrow",
            resource=escrow_uid,
            body=await _request_body(request),
            expected_principal=body.buyer_principal,
        )
        return await runtime.settlement_service().verify(
            escrow_uid=escrow_uid,
            request=body,
            buyer_principal=identity,
        )
    except (AuthError, SettlementRequestError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
        escrow = await runtime.db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise SettlementRequestError("escrow not found", status_code=404)
        thread = await runtime.db.load_negotiation_thread_row(
            negotiation_id=str(escrow["negotiation_id"]),
        )
        if thread is None:
            raise SettlementRequestError("negotiation not found", status_code=404)
        identity = await _buyer(
            request=request,
            runtime=runtime,
            operation="settle_status",
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
        return BareMetalFulfillmentResponse.model_validate(lifecycle)
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
        return BareMetalFulfillmentResponse.model_validate(lifecycle)
    except BareMetalFulfillmentError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


def _evidence_route_service(runtime: BareMetalStorefrontRuntime) -> Any:
    """The evidence route service over this storefront's store, trust, and signer."""

    def canonical(identity: Identity) -> CanonicalPrincipal:
        return CanonicalPrincipal.model_validate(identity.model_dump(mode="json"))

    composition = runtime.settlement_composition
    stripe = (
        composition.config.mechanism_config("stripe") if composition is not None else None
    )
    trust = getattr(stripe, "authority", None)
    return BareMetalEvidenceRouteService(
        load_evidence=lambda digest: runtime.db.load_bare_metal_lease_ready_evidence(
            evidence_digest=digest
        ),
        seller_principal=canonical(runtime.seller_principal),
        sign=runtime.marketplace_signer.sign,
        admin_principals=tuple(
            canonical(identity) for identity in runtime.admin_principals.identities
        ),
        hosted_authority_principals=(
            tuple(canonical(identity) for identity in trust.principals)
            if trust is not None
            else ()
        ),
    )


@router.get(EVIDENCE_PATH, response_model=BareMetalSignedLeaseReadyEvidence)
async def lease_ready_evidence(
    evidence_digest: str,
    request: Request,
) -> BareMetalSignedLeaseReadyEvidence:
    """Resolve one content-addressed lease-ready document with seller proof."""
    runtime = _runtime(request)
    service = _evidence_route_service(runtime)
    try:
        resource = evidence_resource(evidence_digest)
    except BareMetalEvidenceContractError as exc:
        raise HTTPException(status_code=404, detail="evidence not found") from exc
    # Bound before anything can refuse, so every answer, a refusal included,
    # carries the storefront's response signature.
    bind_response_contract(request, operation=EVIDENCE_OPERATION, resource=resource)
    try:
        evidence = await service.evidence(evidence_digest)
    except BareMetalEvidenceRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    role = request.headers.get("X-Market-Role", "")
    if not role:
        raise HTTPException(status_code=401, detail="a signed request is required")
    # A role with no reader is refused by authentication itself.
    allowed = tuple(
        Identity.model_validate(principal.model_dump(mode="json"))
        for principal in service.readers(evidence).get(role, ())
    )
    await _principal(
        request=request,
        runtime=runtime,
        operation=EVIDENCE_OPERATION,
        resource=resource,
        expected_role=role,
        allowed_principals=allowed,
    )
    return service.respond(evidence)


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
    status["settlement_manual_required"] = (
        await runtime.settlement_runtime.manual_required_count()
    )
    return BareMetalHealthResponse.model_validate(status)


# -- deal controls ------------------------------------------------------------
# The kit's route services own these contracts; ``deal_controls`` supplies what
# is bare metal's own. Each route authenticates the signed contract the
# canonical storefront client sends.


@router.post(
    "/api/v1/admin/settle/{escrow_uid}/verify",
    response_model=BareMetalVerifyEscrowResponse,
)
async def admin_verify_settlement(
    escrow_uid: str, body: BareMetalVerifyEscrowRequest, request: Request
) -> BareMetalVerifyEscrowResponse:
    """Read the escrow from chain against a listing's terms, writing nothing."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_verify_settlement",
        resource=escrow_uid,
        body=await _request_body(request),
    )
    try:
        result = await settlement_admin_routes(runtime).verify(
            escrow_uid, body.model_dump(mode="python")
        )
    except SettlementAdminRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return BareMetalVerifyEscrowResponse.model_validate(result)


@router.post(
    "/api/v1/admin/settle/{escrow_uid}/evaluate",
    response_model=BareMetalEvaluateSettleResponse,
)
async def admin_evaluate_settlement(
    escrow_uid: str, body: BareMetalEvaluateSettleRequest, request: Request
) -> BareMetalEvaluateSettleResponse:
    """Preview the fulfillment settlement would start, writing nothing."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_evaluate_settlement",
        resource=escrow_uid,
        body=await _request_body(request),
    )
    try:
        result = await settlement_admin_routes(runtime).evaluate(
            escrow_uid, body.model_dump(mode="python")
        )
    except SettlementAdminRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return BareMetalEvaluateSettleResponse.model_validate(result)


@router.get(
    "/api/v1/admin/settle/{escrow_uid}/wait",
    response_model=BareMetalSettleWaitResponse,
)
async def admin_settle_wait(
    escrow_uid: str,
    request: Request,
    timeout: float = Query(default=60.0, gt=0, le=MAX_WAIT_SECONDS),
) -> BareMetalSettleWaitResponse:
    """Block until the settlement's fulfillment is delivered or cannot be."""
    runtime = _runtime(request)
    raw_timeout = request.query_params.get("timeout", "60.0")
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_settle_wait",
        resource=f"{escrow_uid}?timeout={raw_timeout}",
    )
    waited = await settlement_admin_routes(runtime).wait(escrow_uid, timeout=timeout)
    return BareMetalSettleWaitResponse.model_validate(waited)


@router.post("/api/v1/admin/portfolio/reservations")
async def admin_reserve_capacity(
    body: BareMetalReserveCapacityRequest, request: Request
) -> dict[str, Any]:
    """Reserve a listing's machine administratively, without negotiating."""
    runtime = _runtime(request)
    await _admin(
        request=request,
        runtime=runtime,
        operation="admin_reserve_capacity",
        resource=body.listing_id or body.escrow_uid or "",
        body=await _request_body(request),
    )
    try:
        return await capacity_admin_routes(runtime).reserve(
            body.model_dump(mode="python")
        )
    except CapacityAdminRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/api/v1/admin/fulfillment/events/capacity-released",
    response_model=BareMetalCapacityEventResponse,
)
async def capacity_released(
    body: BareMetalCapacityReleasedEvent, request: Request
) -> BareMetalCapacityEventResponse:
    """Record a site's report that a reservation's capacity is free again.

    Only the authority of the site the event names may send it, signed as the
    service that site runs.
    """
    runtime = _runtime(request)
    caller = await _principal(
        request=request,
        runtime=runtime,
        operation="fulfillment_capacity_released",
        resource=body.capacity_reservation_id,
        expected_role="service",
        allowed_principals=tuple(
            binding.authority_principal for binding in runtime.site_bindings
        ),
        body=await _request_body(request),
    )
    if not any(
        binding.site_id == body.site_id and binding.authority_principal == caller
        for binding in runtime.site_bindings
    ):
        raise HTTPException(
            status_code=403, detail="only the named site's authority may report it"
        )
    try:
        recorded = await capacity_admin_routes(runtime).capacity_released(
            body.model_dump(mode="python", exclude_none=True)
        )
    except CapacityAdminRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return BareMetalCapacityEventResponse.model_validate(recorded)


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
