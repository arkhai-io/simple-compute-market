"""Framework-free route services for a quota-backed storefront's routes.

Each service validates and performs one router's routes over the collaborators
its storefront injects and reports a refusal as ``RouteRefusal``, carrying the
status code and detail the storefront serves. A storefront's binding maps each
route to its service and the refusal to a response, and holds nothing else.
Every collaborator is read when a route runs, since most exist only while the
storefront's lifespan runs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from typing import Any

from core_storefront.auth import AuthenticatedPrincipal
from core_storefront.models.listing_models import (
    CloseListingResponse,
    ListingListResponse,
    ListingResponse,
    PauseListingResponse,
)
from core_storefront.models.negotiation_models import (
    AdvanceRequest,
    AdvanceResponse,
    ForceAcceptRequest,
    ForceAcceptResponse,
    NegotiateContinueRequest,
    NegotiateContinueResponse,
    NegotiateNewRequest,
    NegotiateNewResponse,
    NegotiationDetailResponse,
    NegotiationListResponse,
)
from core_storefront.models.settle_models import (
    SettleRequest,
    SettleStatusResponse,
    SettleWaitResponse,
)
from core_storefront.models.system_models import HealthResponse
from core_storefront.services.negotiation_service import NegotiationServiceError
from market_identity import Identity, Signer
from market_negotiation_runtime import (
    NegotiationRuntime,
    NegotiationUnavailableError,
    OfferUnfulfillableError,
    StorefrontPausedError,
)
from market_settlement_runtime import SettlementAdminRouteService
from market_storefront_kit import (
    LifecycleRouteError,
    NegotiationControlRouteService,
    StageEventRouteService,
    StorefrontLoopController,
    TradingPause,
    opening_proposal,
)
from pydantic import ValidationError

from arkhai_api_selling.issuance import SettlementRefusal, accepted_agreement
from arkhai_api_selling.listings import ListingService
from arkhai_api_selling.publish_route import PublishFromQuotaRequest, PublishFromQuotaResponse
from arkhai_api_selling.system import SystemService

logger = logging.getLogger(__name__)

NOT_INITIALIZED = "storefront is not initialized"


class RouteRefusal(Exception):
    """A route refused; ``status_code`` and ``detail`` are the response as served."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class SettleOutcome:
    """A settlement route's answer: the stage's payload at the stage's status."""

    __slots__ = ("payload", "status_code")

    def __init__(self, status_code: int, payload: Mapping[str, Any]) -> None:
        self.status_code = status_code
        self.payload = dict(payload)


def _required(value: Any, detail: str = NOT_INITIALIZED) -> Any:
    if value is None:
        raise RouteRefusal(503, detail)
    return value


def _kit_refusal(exc: LifecycleRouteError) -> RouteRefusal:
    return RouteRefusal(exc.status_code, exc.detail)


class QuotaSettleRequest(SettleRequest):
    """Settlement input for Alkahest or payments by negotiation ID."""

    buyer_evm_address: str | None = None
    chain_name: str | None = None
    settlement_mechanism: str | None = None


class ListingRoutes:
    """The listing routes: reads, the administrator's pause and resume, the seller's publish and close."""

    def __init__(
        self,
        *,
        repository: Callable[[], Any | None],
        listing_service: Callable[[], ListingService | None],
        publication: Any,
    ) -> None:
        self._repository = repository
        self._listing_service = listing_service
        self._publication = publication

    async def _listing(self, listing_id: str) -> tuple[Any, dict[str, Any]]:
        db = _required(self._repository())
        row = await db.load_listing(listing_id=listing_id)
        if not row:
            raise RouteRefusal(404, f"Listing {listing_id} not found")
        return db, row

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None,
        paused: bool | None,
    ) -> ListingListResponse:
        db = _required(self._repository())
        listings = await db.list_listings(
            status=status, paused=paused, limit=limit, offset=offset
        )
        return ListingListResponse(
            listings=listings, count=len(listings), limit=limit, offset=offset
        )

    async def get(self, listing_id: str) -> ListingResponse:
        _db, row = await self._listing(listing_id)
        if "paused" not in row:
            row["paused"] = False
        return ListingResponse(**row)

    async def pause(self, listing_id: str) -> PauseListingResponse:
        db, _row = await self._listing(listing_id)
        await db.set_listing_paused(listing_id=listing_id, paused=True)
        return PauseListingResponse(
            listing_id=listing_id,
            paused=True,
            message="Listing paused. New negotiations will receive 503.",
        )

    async def resume(self, listing_id: str) -> PauseListingResponse:
        """Resume and republish; a listing the domain's guards refuse stays paused."""
        db, row = await self._listing(listing_id)
        refusal = self._publication.refusal(row)
        if refusal is not None:
            raise RouteRefusal(409, refusal)
        await db.set_listing_paused(listing_id=listing_id, paused=False)
        publish_result = await self._publication.publish(db, row)
        registry_status = publish_result.get("status", "unknown")
        return PauseListingResponse(
            listing_id=listing_id,
            paused=False,
            registry_status=registry_status,
            message=f"Listing resumed and {registry_status} to registry.",
        )

    async def publish_from_quota(self, body: PublishFromQuotaRequest) -> PublishFromQuotaResponse:
        service = _required(self._listing_service())
        try:
            result = await service.publish_from_quota(
                resource_id=body.resource_id,
                accepted_escrows=body.accepted_escrows,
                settlement_clauses=body.settlement_clauses,
                paused=body.paused,
                **body.listing_request(),
            )
        except ValueError as exc:
            raise RouteRefusal(400, str(exc)) from exc
        except Exception as exc:
            logger.error("[LISTINGS] publish unexpected: %s", exc, exc_info=True)
            raise RouteRefusal(500, str(exc)) from exc
        return PublishFromQuotaResponse(**result)

    async def close(self, listing_id: str) -> CloseListingResponse:
        service = _required(self._listing_service())
        try:
            result = await service.close_listing(listing_id)
        except ValueError as exc:
            raise RouteRefusal(400, str(exc)) from exc
        except Exception as exc:
            logger.error("[LISTINGS] close unexpected: %s", exc, exc_info=True)
            raise RouteRefusal(500, str(exc)) from exc
        return CloseListingResponse(**result)


def _replayed(auth: AuthenticatedPrincipal) -> Any | None:
    """A recorded exact retry's successful payload, or None when the request is new.

    A recorded refusal is re-raised as it was served; a retry whose first
    dispatch has not finished is refused as pending.
    """
    if not auth.exact_retry:
        return None
    if auth.recorded_outcome is None:
        raise RouteRefusal(409, "request retry is pending")
    status_code, payload = auth.recorded_outcome
    if status_code >= 400:
        raise RouteRefusal(status_code, payload)
    return payload


class NegotiateRoutes:
    """The buyer's negotiation routes over the composed negotiation runtime."""

    def __init__(
        self,
        *,
        repository: Callable[[], Any | None],
        runtime: Callable[[], NegotiationRuntime | None],
        signer: Callable[[], Signer | None],
        storefront_url: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._runtime = runtime
        self._signer = signer
        self._storefront_url = storefront_url

    def _seller_principal(self) -> Identity:
        return _required(self._signer()).identity

    def _composed(self) -> tuple[Any, NegotiationRuntime]:
        return _required(self._repository()), _required(
            self._runtime(), "storefront negotiation is unavailable"
        )

    async def new(self, body: NegotiateNewRequest, auth: AuthenticatedPrincipal) -> NegotiateNewResponse:
        replayed = _replayed(auth)
        if replayed is not None:
            return NegotiateNewResponse.model_validate(replayed)
        seller_principal = self._seller_principal()
        db, runtime = self._composed()
        try:
            result = await runtime.start(
                repository=db,
                listing_id=body.listing_id,
                buyer_principal=body.buyer_principal,
                seller_principal=seller_principal,
                actor_principal=auth.principal,
                terms=body.provision_terms,
                proposal=opening_proposal(body.proposal, body.settlement_selection),
                seller_agent_url=self._storefront_url() or "",
                buyer_agent_url=body.buyer_agent_url,
            )
        except StorefrontPausedError as exc:
            raise RouteRefusal(
                503,
                {
                    "error": "paused",
                    "reason": exc.reason,
                    "hint": "Storefront or listing is paused.",
                },
            ) from exc
        except OfferUnfulfillableError as exc:
            raise RouteRefusal(
                409,
                {
                    "error": "offer_unfulfillable",
                    "reason": exc.reason,
                    "listing_id": exc.listing_id,
                    "hint": (
                        "Seller refused: listing is closed, the quota cannot "
                        "cover the requested quantity, or the key claim was "
                        "rejected. See `reason`."
                    ),
                },
            ) from exc
        except NegotiationUnavailableError as exc:
            # The listing's source could not be confirmed; nothing is known to be
            # wrong, so a retry may succeed.
            raise RouteRefusal(503, _source_unavailable(exc)) from exc
        except ValidationError as exc:
            raise RouteRefusal(
                400, {"error": "incompatible_provision_terms", "reason": str(exc)}
            ) from exc
        except ValueError as exc:
            raise RouteRefusal(404, str(exc)) from exc
        except Exception as exc:
            logger.error("[NEGOTIATE/new] %s", exc, exc_info=True)
            raise RouteRefusal(500, str(exc)) from exc

        # The response is validated under its own handler, not the one above:
        # that one maps a `ValidationError` to a 400 about the buyer's terms,
        # and a wire-shape defect on this side must not blame the caller.
        try:
            return NegotiateNewResponse(**result)
        except Exception as exc:
            logger.error(
                "[NEGOTIATE/new] response does not satisfy NegotiateNewResponse: %s",
                exc,
                exc_info=True,
            )
            raise RouteRefusal(500, str(exc)) from exc

    async def continue_negotiation(
        self, neg_id: str, body: NegotiateContinueRequest, auth: AuthenticatedPrincipal
    ) -> NegotiateContinueResponse:
        replayed = _replayed(auth)
        if replayed is not None:
            return NegotiateContinueResponse.model_validate(replayed)
        seller_principal = self._seller_principal()
        db, runtime = self._composed()
        if (
            body.action == "counter"
            and body.proposal is None
            and body.settlement_selection is None
        ):
            raise RouteRefusal(400, "'proposal' required for counter")

        proposal_payload = opening_proposal(body.proposal, body.settlement_selection)
        candidate_selection = (
            proposal_payload.get("settlement_selection")
            if isinstance(proposal_payload, Mapping)
            else None
        )
        if body.action == "accept" and candidate_selection is not None:
            thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
            carrier = (
                thread.get("buyer_escrow_proposal")
                if isinstance(thread, Mapping)
                and isinstance(thread.get("buyer_escrow_proposal"), Mapping)
                else {}
            )
            pinned_selection = carrier.get("settlement_selection")
            if (
                not isinstance(candidate_selection, Mapping)
                or not isinstance(pinned_selection, Mapping)
                or dict(candidate_selection) != dict(pinned_selection)
            ):
                raise RouteRefusal(
                    409, "opening settlement selection cannot change during negotiation"
                )

        try:
            result = await runtime.continue_negotiation(
                repository=db,
                negotiation_id=neg_id,
                buyer_action=body.action,
                buyer_proposal=proposal_payload,
                buyer_reason=body.reason,
                buyer_principal=body.buyer_principal,
                actor_principal=auth.principal,
                actor_role="buyer",
                seller_principal=seller_principal,
            )
        except OfferUnfulfillableError as exc:
            # A buyer's accept on a listing its source no longer supports, or
            # whose capacity is taken.
            raise RouteRefusal(
                409,
                {
                    "error": "offer_unfulfillable",
                    "reason": exc.reason,
                    "listing_id": exc.listing_id,
                },
            ) from exc
        except NegotiationUnavailableError as exc:
            raise RouteRefusal(503, _source_unavailable(exc)) from exc
        except ValueError as exc:
            raise RouteRefusal(404, str(exc)) from exc
        except Exception as exc:
            logger.error("[NEGOTIATE/%s] %s", neg_id, exc, exc_info=True)
            raise RouteRefusal(500, str(exc)) from exc
        return NegotiateContinueResponse(**result)


def _source_unavailable(exc: NegotiationUnavailableError) -> dict[str, Any]:
    return {
        "error": "listing_source_unavailable",
        "reason": exc.reason,
        "listing_id": exc.listing_id,
        "hint": "The seller could not confirm the listing; retry later.",
    }


class NegotiationRoutes:
    """The administrator's negotiation introspection, advance, and force-accept."""

    def __init__(
        self,
        *,
        repository: Callable[[], Any | None],
        negotiation_service: Callable[[], Any | None],
        runtime: Callable[[], NegotiationRuntime | None],
        signer: Callable[[], Signer | None],
    ) -> None:
        self._repository = repository
        self._negotiation_service = negotiation_service
        self._runtime = runtime
        self._signer = signer

    def _service(self) -> Any:
        return _required(self._negotiation_service())

    async def list(
        self,
        listing_id: str,
        *,
        terminal_state: str | None,
        limit: int,
        offset: int,
    ) -> NegotiationListResponse:
        try:
            threads = await self._service().list_for_order(
                listing_id=listing_id,
                terminal_state=terminal_state or None,
                limit=limit,
                offset=offset,
            )
        except NegotiationServiceError as exc:
            raise RouteRefusal(exc.status_code, str(exc)) from exc
        return NegotiationListResponse(
            listing_id=listing_id,
            negotiations=threads,
            count=len(threads),
            limit=limit,
            offset=offset,
        )

    async def get(self, listing_id: str, neg_id: str) -> NegotiationDetailResponse:
        try:
            detail = await self._service().get_detail(listing_id=listing_id, neg_id=neg_id)
        except NegotiationServiceError as exc:
            raise RouteRefusal(exc.status_code, str(exc)) from exc
        return NegotiationDetailResponse(**detail)

    async def advance(self, listing_id: str, neg_id: str, body: AdvanceRequest) -> AdvanceResponse:
        try:
            result = await self._service().advance(
                listing_id=listing_id,
                neg_id=neg_id,
                action=body.action,
                proposal=body.proposal,
                reason=body.reason,
            )
        except NegotiationServiceError as exc:
            raise RouteRefusal(exc.status_code, str(exc)) from exc
        except Exception as exc:
            logger.error("[NEGOTIATIONS] advance: %s", exc, exc_info=True)
            raise RouteRefusal(500, str(exc)) from exc
        return AdvanceResponse(**result)

    async def force_accept(
        self,
        listing_id: str,
        neg_id: str,
        body: ForceAcceptRequest,
        *,
        actor_principal: Identity,
    ) -> ForceAcceptResponse:
        runtime = _required(self._runtime(), "storefront negotiation is unavailable")
        controls = NegotiationControlRouteService(
            runtime=runtime,
            repository=_required(self._repository()),
            seller_principal=lambda: _required(self._signer()).identity,
        )
        try:
            return await controls.force_accept(
                listing_id, neg_id, body, actor_principal=actor_principal
            )
        except LifecycleRouteError as exc:
            raise _kit_refusal(exc) from exc


class SettleRoutes:
    """The buyer's settle and status, the administrator's wait, and the seller's refund.

    Each route resolves the seller stage the accepted Agreement selects and
    answers with that stage's response; mechanism behaviour is the stage's.
    """

    def __init__(
        self,
        *,
        repository: Callable[[], Any | None],
        composition: Callable[[], Any | None],
        coordinator: Callable[[], Any | None],
        signer: Callable[[], Signer | None],
    ) -> None:
        self._repository = repository
        self._composition = composition
        self._coordinator = coordinator
        self._signer = signer
        # Settle and status for one negotiation are serialized here, so a
        # status poll never re-drives a delivery a settle call is driving.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, negotiation_id: str) -> asyncio.Lock:
        return self._locks.setdefault(negotiation_id, asyncio.Lock())

    @staticmethod
    def _accepted_stage(composition: Any, thread: Any) -> tuple[Any, Any]:
        try:
            agreement, _raw = accepted_agreement(thread or {})
        except (KeyError, TypeError, ValueError) as exc:
            raise RouteRefusal(409, "accepted Agreement is unavailable or invalid") from exc
        stage = composition.stages.get(agreement.settlement.mechanism)
        if stage is None:
            raise RouteRefusal(400, "unsupported accepted settlement mechanism")
        return agreement, stage

    async def _context(
        self, negotiation_id: str, reference: str, body: Any
    ) -> tuple[Any, dict[str, Any]]:
        composition = self._composition()
        signer = self._signer()
        if composition is None or signer is None:
            raise RouteRefusal(503, "settlement composition is not initialized")
        db = _required(self._repository())
        thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        agreement, stage = self._accepted_stage(composition, thread)
        if (
            Identity.model_validate(agreement.buyer) != body.buyer_principal
            or Identity.model_validate(agreement.seller) != signer.identity
        ):
            raise RouteRefusal(403, "settlement parties differ from accepted Agreement")
        if (
            body.settlement_mechanism is not None
            and body.settlement_mechanism != agreement.settlement.mechanism
        ):
            raise RouteRefusal(400, "settlement mechanism conflicts with accepted Agreement")
        return stage, {
            "db": db,
            "composition": composition,
            "coordinator": self._coordinator(),
            "reference": reference,
            "body": body,
            "signer": signer,
            "thread": thread,
        }

    async def settle(self, escrow_uid: str, body: QuotaSettleRequest) -> SettleOutcome:
        stage, context = await self._context(body.negotiation_id, escrow_uid, body)
        try:
            async with self._lock(body.negotiation_id):
                result = await stage.settle(**context)
        except SettlementRefusal as exc:
            raise RouteRefusal(exc.status_code, exc.detail) from exc
        except ValueError as exc:
            raise RouteRefusal(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("Settlement is unavailable for %s", body.negotiation_id)
            raise RouteRefusal(502, "settlement authority is unavailable") from exc
        return SettleOutcome(result.status_code, result.payload)

    async def status(
        self,
        escrow_uid: str,
        *,
        verify_buyer: Callable[[Identity], Awaitable[Any]],
    ) -> SettleStatusResponse:
        """The deal's settlement status, once ``verify_buyer`` has admitted the thread's buyer.

        The buyer is known only from the thread the reference resolves, so the
        route resolves state before it authenticates. A payment settlement is
        keyed by negotiation ID and may have no issuance progress yet; other
        references resolve through their progress row.
        """
        db = _required(self._repository())
        row = await db.load_issuance_progress(reference=escrow_uid)
        negotiation_id = str(row["negotiation_id"]) if row is not None else escrow_uid
        thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if thread is None:
            raise RouteRefusal(404, "settlement progress is unavailable")
        buyer = Identity.model_validate(thread["buyer_principal"])
        await verify_buyer(buyer)
        body = QuotaSettleRequest(negotiation_id=negotiation_id, buyer_principal=buyer)
        stage, context = await self._context(negotiation_id, escrow_uid, body)
        try:
            async with self._lock(negotiation_id):
                result = await stage.status(**context)
        except SettlementRefusal as exc:
            raise RouteRefusal(exc.status_code, exc.detail) from exc
        if result is None:
            raise RouteRefusal(404, "settlement progress is unavailable")
        return SettleStatusResponse(**result.payload)

    @staticmethod
    async def wait_resource(escrow_uid: str, stated_timeout: str | None) -> str:
        """The resource an administrator's wait signs: the reference and the timeout as sent.

        The canonical client signs the timeout exactly as it sends it, so the
        wait it authorizes cannot be lengthened by rewriting the query; a wait
        stating none is refused before it is authenticated.
        """
        if stated_timeout is None:
            raise RouteRefusal(400, "admin settlement wait requires explicit timeout")
        return f"{escrow_uid}?timeout={stated_timeout}"

    async def wait(self, escrow_uid: str, *, timeout: float) -> SettleWaitResponse:
        """Long-poll until the settlement reaches a terminal state."""
        db = _required(self._repository())

        async def settle_status(uid: str):
            return await db.load_issuance_progress(reference=uid)

        waited = await SettlementAdminRouteService(
            settle_status=settle_status,
            is_terminal=lambda status: status.get("status") in {"ready", "failed"},
        ).wait(escrow_uid, timeout=timeout)
        return SettleWaitResponse(
            ready=waited["ready"], status=waited["status"], elapsed_ms=waited["elapsed_ms"]
        )

    async def refund(self, negotiation_id: str) -> SettleOutcome:
        composition = self._composition()
        db = self._repository()
        if composition is None or db is None:
            raise RouteRefusal(503, "settlement composition is not initialized")
        thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if not thread or thread.get("terminal_state") != "success":
            raise RouteRefusal(404, "accepted negotiation not found")
        _agreement, stage = self._accepted_stage(composition, thread)
        # Deliberately not serialized behind an in-flight settle: refund intent and
        # delivery start are ordered by their durable transitions, and a refund must
        # be able to land while issuance is under way.
        try:
            result = await stage.refund(db=db, composition=composition, negotiation_id=negotiation_id)
        except SettlementRefusal as exc:
            raise RouteRefusal(exc.status_code, exc.detail) from exc
        return SettleOutcome(result.status_code, result.payload)


class SystemRoutes:
    """Health, the administrator's status read, and the stage-event log."""

    def __init__(
        self,
        *,
        repository: Callable[[], Any | None],
        system_service: Callable[[], SystemService | None],
        trading_pause: TradingPause,
        loops: Callable[[], StorefrontLoopController | None],
    ) -> None:
        self._repository = repository
        self._system_service = system_service
        self._trading_pause = trading_pause
        self._loops = loops

    async def health(self) -> HealthResponse:
        return HealthResponse(**(await _required(self._system_service()).get_health()))

    async def status(self) -> HealthResponse:
        """The administrator's read: every check, the storefront's principal, the trading pause, and every loop."""
        service = _required(self._system_service())
        return HealthResponse(
            **await service.status(paused=self._trading_pause.paused, loops=self._loops())
        )

    @staticmethod
    async def events_resource(query: Iterable[tuple[str, str]]) -> str:
        """The resource the administrator's event read signs, rebuilt from the query."""
        try:
            return StageEventRouteService.signed_resource(query)
        except LifecycleRouteError as exc:
            raise _kit_refusal(exc) from exc

    async def events(
        self,
        *,
        since_id: int,
        last_event_id: str | None,
        limit: int,
        stream: bool,
        stage: str | None,
        listing_id: str | None,
        negotiation_id: str | None,
    ) -> Any | AsyncIterator[str]:
        """A page of stage events, or the stream a binding serves as server-sent events."""
        events = StageEventRouteService(_required(self._repository()))
        since_id = events.resume_point(since_id, last_event_id)
        filters = {"stage": stage, "listing_id": listing_id, "negotiation_id": negotiation_id}
        if not stream:
            return await events.page(since_id=since_id, limit=limit, **filters)
        return events.stream(since_id=since_id, **filters)


__all__ = [
    "ListingRoutes",
    "NOT_INITIALIZED",
    "NegotiateRoutes",
    "NegotiationRoutes",
    "QuotaSettleRequest",
    "RouteRefusal",
    "SettleOutcome",
    "SettleRoutes",
    "SystemRoutes",
]
