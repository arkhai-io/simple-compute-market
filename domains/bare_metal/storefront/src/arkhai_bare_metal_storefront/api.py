"""Schema-opaque HTTP routes owned by the bare-metal composition."""

from __future__ import annotations
import base64

from collections.abc import Mapping
import json
from typing import Annotated, Any

from core_storefront.auth import AuthError, authenticate_request
from core_storefront.models.listing_models import ListingListResponse, ListingResponse
from core_storefront.models.negotiation_models import (
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from core_storefront.models.system_models import AdminPauseResponse
from fastapi import APIRouter, Body, HTTPException, Query, Request

from market_contact_exchange import (
    AuthorizedIntroductionRequest,
    ContactSettlementConfig,
    IntroductionRouteError,
    IntroductionStart,
)
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_identity import EMPTY_BODY, Identity
from market_storefront_kit import get_storefront_container
from market_settlement_runtime import (
    HostedSettlementRouteError,
    HostedSettlementStart,
)
from .models import (
    BareMetalAccessDeliveryResponse,
    BareMetalFulfillRequest,
    BareMetalFulfillmentResponse,
    BareMetalFulfillmentResultResponse,
    BareMetalHealthResponse,
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettleStatusResponse,
)
from .fulfillment_service import BareMetalFulfillmentError
from .negotiation_service import NegotiationRequestError
from .runtime import BareMetalStorefrontRuntime
from .settlement_service import SettlementRequestError
from .hosted_routes import build_bare_metal_hosted_route_service
from .introduction_routes import build_bare_metal_introduction_service
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
) -> Identity:
    return await _principal(
        request=request,
        runtime=runtime,
        operation=operation,
        resource=request.url.path,
        expected_role="admin",
        allowed_principals=runtime.admin_principals.identities,
    )


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
    runtime = _runtime(request)
    composition = runtime.settlement_composition
    if (
        composition is None
        or CONTACT_MECHANISM not in composition.enabled_mechanisms
    ):
        raise HTTPException(status_code=404, detail="contact exchange is disabled")
    section = composition.config.mechanism_config("contact")
    if not isinstance(section, ContactSettlementConfig) or not section.contact_payload:
        raise HTTPException(
            status_code=503,
            detail="contact-exchange reveal is unavailable",
        )
    return build_bare_metal_introduction_service(
        db=runtime.db,
        repository=runtime.settlement_repository,
        settlement_runtime=runtime.settlement_runtime,
        seller_contact=section.contact_payload,
        authorize_request=_authorize_introduction_request,
        deliver=runtime.introduction_delivery,
    )


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
    raw = row.get("offer_resource")
    if isinstance(raw, str):
        raw = json.loads(raw)
    runtime.domain.codecs.listing(raw)
    normalized = dict(row)
    normalized["offer_resource"] = raw
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
            body=body.model_dump(mode="json", exclude_none=True, exclude_unset=True),
            expected_principal=body.buyer_principal,
        )
        return await runtime.negotiation_service().open(
            request=body,
            buyer_principal=identity,
        )
    except (AuthError, NegotiationRequestError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
        body=body.model_dump(mode="json", exclude_none=True, exclude_unset=True),
        expected_principal=body.buyer_principal,
    )
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    if Identity.model_validate(thread.get("buyer_principal")) != identity:
        raise HTTPException(status_code=403, detail="negotiation buyer mismatch")
    if thread.get("terminal_state") is not None:
        raise HTTPException(status_code=409, detail="negotiation is terminal")
    raise HTTPException(
        status_code=409,
        detail="default bare-metal policy does not support additional rounds",
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
    runtime = _runtime(request)
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
    detail = await _runtime(request).db.load_negotiation_detail(
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
            body=body.model_dump(mode="json", exclude_none=True, exclude_unset=True),
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
            body=body.model_dump(mode="json"),
        )
        lifecycle = await runtime.fulfillment_service().begin(
            negotiation_id=body.negotiation_id,
            escrow_uid=body.escrow_uid,
            buyer_principal=identity,
        )
        return BareMetalFulfillmentResponse.model_validate(lifecycle)
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


@router.get("/api/v1/evidence/bare-metal/{evidence_digest}")
async def hosted_lease_evidence(
    evidence_digest: str,
    request: Request,
) -> dict[str, Any]:
    """Resolve one content-addressed lease-ready document with seller proof."""

    if len(evidence_digest) != 64 or any(
        char not in "0123456789abcdef" for char in evidence_digest
    ):
        raise HTTPException(status_code=404, detail="evidence not found")
    runtime = _runtime(request)
    evidence = await runtime.db.load_bare_metal_hosted_evidence(
        evidence_digest="sha256:" + evidence_digest
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    material = evidence.canonical_json().encode("utf-8")
    proof = (
        base64.urlsafe_b64encode(runtime.marketplace_signer.sign(material))
        .rstrip(b"=")
        .decode("ascii")
    )
    return {
        "protocol": "arkhai.bare-metal-evidence-signature.v1",
        "seller_principal": runtime.seller_principal.model_dump(mode="json"),
        "evidence": evidence.model_dump(mode="json"),
        "proof": proof,
    }


@router.get("/health", response_model=BareMetalHealthResponse)
@router.get("/api/v1/system/health", response_model=BareMetalHealthResponse)
async def health(request: Request) -> BareMetalHealthResponse:
    return BareMetalHealthResponse.model_validate(await _runtime(request).health())


@router.get("/api/v1/system/status", response_model=BareMetalHealthResponse)
async def system_status(request: Request) -> BareMetalHealthResponse:
    runtime = _runtime(request)
    await _admin(request=request, runtime=runtime, operation="system_status")
    return BareMetalHealthResponse.model_validate(await runtime.health())


@router.post("/api/v1/admin/pause", response_model=AdminPauseResponse)
async def pause(request: Request) -> AdminPauseResponse:
    runtime = _runtime(request)
    await _admin(request=request, runtime=runtime, operation="pause")
    await runtime.db.set_global_paused(paused=True)
    return AdminPauseResponse(paused=True, message="storefront paused")


@router.post("/api/v1/admin/resume", response_model=AdminPauseResponse)
async def resume(request: Request) -> AdminPauseResponse:
    runtime = _runtime(request)
    await _admin(request=request, runtime=runtime, operation="resume")
    await runtime.db.set_global_paused(paused=False)
    return AdminPauseResponse(paused=False, message="storefront resumed")
