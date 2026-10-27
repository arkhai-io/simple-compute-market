"""The route services validate and perform each route over injected collaborators and refuse with the status and detail the storefront serves."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from core_storefront.models.negotiation_models import (
    AdvanceRequest,
    NegotiateContinueRequest,
    NegotiateNewRequest,
)
from core_storefront.services.negotiation_service import NegotiationServiceError
from market_core.schemas import ProvisionTerms
from market_identity import Ed25519Signer
from market_negotiation_runtime import (
    NegotiationUnavailableError,
    OfferUnfulfillableError,
    StorefrontPausedError,
)
from market_storefront_kit import StageEventRouteService, TradingPause
from pydantic import ValidationError

from arkhai_api_selling.issuance import SettlementRefusal, SettleResult
from arkhai_api_selling.publish_route import PublishFromQuotaRequest
from arkhai_api_selling.route_services import (
    ListingRoutes,
    NegotiateRoutes,
    NegotiationRoutes,
    QuotaSettleRequest,
    RouteRefusal,
    SettleRoutes,
    SystemRoutes,
)
from tests.bundles import BUYER, CLAIMANT, EXAMPLE, STRANGER, accepted_agreement

CLAIMANT_SIGNER = Ed25519Signer(bytes(range(2, 34)))


def _auth(principal=BUYER, *, exact_retry=False, recorded=None) -> Any:
    return SimpleNamespace(
        principal=principal, exact_retry=exact_retry, recorded_outcome=recorded
    )


async def _refused(coro) -> RouteRefusal:
    with pytest.raises(RouteRefusal) as refused:
        await coro
    return refused.value


# --- listings ---------------------------------------------------------------


class _Listings:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self.rows = rows or {}
        self.paused: dict[str, bool] = {}

    async def list_listings(self, **query):
        self.query = query
        return list(self.rows.values())

    async def load_listing(self, *, listing_id):
        return self.rows.get(listing_id)

    async def set_listing_paused(self, *, listing_id, paused):
        self.paused[listing_id] = paused


class _Publication:
    def __init__(self, refusal: str | None = None) -> None:
        self._refusal = refusal
        self.published: list[dict] = []

    def refusal(self, listing):
        return self._refusal

    async def publish(self, db, listing):
        self.published.append(listing)
        return {"status": "published"}


class _ListingService:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.error = error

    async def publish_from_quota(self, **request):
        if self.error is not None:
            raise self.error
        self.calls.append(request)
        return {"status": "created", "listing_id": "L-1", "registry_status": "published"}

    async def close_listing(self, listing_id):
        if self.error is not None:
            raise self.error
        return {"status": "closed", "listing_id": listing_id}


def _listing_row(listing_id="L-1") -> dict:
    return {
        "listing_id": listing_id,
        "status": "open",
        "listing_resource": {"product": "alpha", "quota": "quota-a"},
        "storefront_url": "https://seller.example",
        "seller_principal": CLAIMANT.model_dump(mode="json"),
    }


def _listing_routes(db, publication=None, service=None) -> ListingRoutes:
    return ListingRoutes(
        repository=lambda: db,
        listing_service=lambda: service,
        publication=publication or _Publication(),
    )


async def test_listing_reads_and_a_missing_listing():
    db = _Listings({"L-1": _listing_row()})
    routes = _listing_routes(db)

    page = await routes.list(limit=5, offset=10, status="open", paused=None)
    assert (page.count, page.limit, page.offset) == (1, 5, 10)
    assert db.query == {"status": "open", "paused": None, "limit": 5, "offset": 10}
    assert (await routes.get("L-1")).paused is False

    refused = await _refused(routes.get("L-9"))
    assert (refused.status_code, refused.detail) == (404, "Listing L-9 not found")


async def test_pause_and_resume_republish_only_what_the_guards_admit():
    db = _Listings({"L-1": _listing_row()})
    publication = _Publication()
    routes = _listing_routes(db, publication)

    paused = await routes.pause("L-1")
    assert (paused.paused, db.paused["L-1"]) == (True, True)
    assert paused.message == "Listing paused. New negotiations will receive 503."

    resumed = await routes.resume("L-1")
    assert (resumed.paused, db.paused["L-1"], resumed.registry_status) == (False, False, "published")
    assert resumed.message == "Listing resumed and published to registry."
    assert publication.published == [_listing_row()]


async def test_a_resume_the_guards_refuse_leaves_the_listing_paused():
    db = _Listings({"L-1": _listing_row()})
    db.paused["L-1"] = True
    publication = _Publication(refusal="blocked")
    routes = _listing_routes(db, publication)

    refused = await _refused(routes.resume("L-1"))

    assert (refused.status_code, refused.detail) == (409, "blocked")
    assert db.paused["L-1"] is True
    assert publication.published == []


async def test_publish_passes_the_request_to_the_listing_service_and_maps_its_refusals():
    service = _ListingService()
    routes = _listing_routes(_Listings(), service=service)
    clauses = [{"mechanism": "opaque.future.v1", "asset": "usd"}]

    class Request(PublishFromQuotaRequest):
        product: str

    created = await routes.publish_from_quota(
        Request(resource_id="quota-a", product="alpha", settlement_clauses=clauses, paused=True)
    )
    assert (created.status, created.listing_id) == ("created", "L-1")
    assert service.calls == [
        {
            "resource_id": "quota-a",
            "accepted_escrows": [],
            "settlement_clauses": clauses,
            "paused": True,
            "product": "alpha",
        }
    ]

    invalid = _listing_routes(_Listings(), service=_ListingService(ValueError("no quota")))
    refused = await _refused(invalid.publish_from_quota(Request(resource_id="quota-a", product="alpha")))
    assert (refused.status_code, refused.detail) == (400, "no quota")
    broken = _listing_routes(_Listings(), service=_ListingService(RuntimeError("boom")))
    assert (await _refused(broken.close("L-1"))).status_code == 500
    assert (await _refused(_listing_routes(_Listings()).close("L-1"))).status_code == 503


# --- negotiate --------------------------------------------------------------


def _terms(quantity=3) -> ProvisionTerms:
    return ProvisionTerms(kind=EXAMPLE.kind, version=1, payload={"quantity": quantity, "key": {"mode": "new"}})


def _new_request(**overrides) -> NegotiateNewRequest:
    values = {
        "listing_id": "L-1",
        "buyer_principal": BUYER,
        "provision_terms": _terms(),
        "proposal": {"fields": {"amount": 300}},
    }
    values.update(overrides)
    return NegotiateNewRequest(**values)


class _Runtime:
    def __init__(self, error: Exception | None = None, result: dict | None = None) -> None:
        self.error = error
        self.result = result
        self.calls: list[dict] = []

    async def start(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    async def continue_negotiation(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _negotiate(runtime, db=None) -> NegotiateRoutes:
    return NegotiateRoutes(
        repository=lambda: db if db is not None else object(),
        runtime=lambda: runtime,
        signer=lambda: CLAIMANT_SIGNER,
        storefront_url=lambda: "https://seller.example",
    )


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (
            StorefrontPausedError("listing_paused"),
            503,
            {"error": "paused", "reason": "listing_paused", "hint": "Storefront or listing is paused."},
        ),
        (
            OfferUnfulfillableError("quota_exhausted: no", listing_id="L-1"),
            409,
            {
                "error": "offer_unfulfillable",
                "reason": "quota_exhausted: no",
                "listing_id": "L-1",
                "hint": (
                    "Seller refused: listing is closed, the quota cannot cover the requested "
                    "quantity, or the key claim was rejected. See `reason`."
                ),
            },
        ),
        (
            NegotiationUnavailableError("source unreachable", listing_id="L-1"),
            503,
            {
                "error": "listing_source_unavailable",
                "reason": "source unreachable",
                "listing_id": "L-1",
                "hint": "The seller could not confirm the listing; retry later.",
            },
        ),
        (ValueError("Order L-1 not found locally"), 404, "Order L-1 not found locally"),
        (RuntimeError("boom"), 500, "boom"),
    ],
)
async def test_an_opening_refusal_is_served_as_the_storefront_served_it(error, status, detail):
    routes = _negotiate(_Runtime(error=error))

    refused = await _refused(routes.new(_new_request(), _auth()))

    assert (refused.status_code, refused.detail) == (status, detail)


async def test_incompatible_terms_are_a_400_naming_the_buyers_terms():
    try:
        ProvisionTerms(kind=EXAMPLE.kind, version="x")
    except ValidationError as exc:
        error = exc
    routes = _negotiate(_Runtime(error=error))

    refused = await _refused(routes.new(_new_request(), _auth()))

    assert refused.status_code == 400
    assert refused.detail["error"] == "incompatible_provision_terms"


async def test_an_opening_runs_the_runtime_with_the_actor_and_the_storefronts_url():
    runtime = _Runtime(
        result={
            "negotiation_id": "neg-1",
            "action": "counter",
            "buyer_principal": BUYER.model_dump(mode="json"),
            "seller_principal": CLAIMANT.model_dump(mode="json"),
            "proposal": {"fields": {"amount": 300}},
        }
    )
    db = object()
    routes = _negotiate(runtime, db)

    response = await routes.new(_new_request(), _auth())

    assert (response.negotiation_id, response.action) == ("neg-1", "counter")
    (call,) = runtime.calls
    assert call["repository"] is db
    assert call["actor_principal"] == BUYER
    assert call["seller_principal"] == CLAIMANT
    assert call["seller_agent_url"] == "https://seller.example"
    assert call["proposal"] == {"fields": {"amount": 300}}


async def test_an_exact_retry_answers_from_its_record_and_runs_nothing():
    runtime = _Runtime()
    routes = _negotiate(runtime)
    recorded = {
        "negotiation_id": "neg-1",
        "action": "accept",
        "buyer_principal": BUYER.model_dump(mode="json"),
        "seller_principal": CLAIMANT.model_dump(mode="json"),
    }

    replayed = await routes.new(_new_request(), _auth(exact_retry=True, recorded=(200, recorded)))
    assert replayed.negotiation_id == "neg-1"

    pending = await _refused(routes.new(_new_request(), _auth(exact_retry=True)))
    assert (pending.status_code, pending.detail) == (409, "request retry is pending")

    recorded_refusal = await _refused(
        routes.new(_new_request(), _auth(exact_retry=True, recorded=(404, "gone")))
    )
    assert (recorded_refusal.status_code, recorded_refusal.detail) == (404, "gone")
    assert runtime.calls == []


async def test_an_uncomposed_storefront_refuses_an_opening():
    routes = NegotiateRoutes(
        repository=lambda: None, runtime=lambda: None, signer=lambda: None, storefront_url=lambda: ""
    )
    assert (await _refused(routes.new(_new_request(), _auth()))).status_code == 503


class _Threads:
    def __init__(self, thread: dict | None) -> None:
        self.thread = thread

    async def load_negotiation_thread_row(self, *, negotiation_id):
        return self.thread


async def test_a_counter_needs_a_proposal_and_an_accept_keeps_its_opening_selection():
    runtime = _Runtime(result={})
    pinned = {"mechanism": "opaque.future.v1", "option_id": "a" * 64, "expiration_unix": 2_000_000_000}
    db = _Threads({"buyer_escrow_proposal": {"settlement_selection": pinned}})
    routes = _negotiate(runtime, db)

    counter = await _refused(
        routes.continue_negotiation("neg-1", NegotiateContinueRequest(action="counter", buyer_principal=BUYER), _auth())
    )
    assert (counter.status_code, counter.detail) == (400, "'proposal' required for counter")

    switched = await _refused(
        routes.continue_negotiation(
            "neg-1",
            NegotiateContinueRequest(
                action="accept",
                buyer_principal=BUYER,
                settlement_selection={**pinned, "option_id": "b" * 64},
            ),
            _auth(),
        )
    )
    assert (switched.status_code, switched.detail) == (
        409, "opening settlement selection cannot change during negotiation"
    )
    assert runtime.calls == []


async def test_a_continuation_refusal_carries_no_hint():
    routes = _negotiate(_Runtime(error=OfferUnfulfillableError("capacity_taken", listing_id="L-1")), _Threads(None))

    refused = await _refused(
        routes.continue_negotiation("neg-1", NegotiateContinueRequest(action="accept", buyer_principal=BUYER), _auth())
    )

    assert refused.status_code == 409
    assert refused.detail == {"error": "offer_unfulfillable", "reason": "capacity_taken", "listing_id": "L-1"}


# --- negotiations -----------------------------------------------------------


class _NegotiationService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def list_for_order(self, **query):
        if self.error:
            raise self.error
        return [{"negotiation_id": "neg-1"}]

    async def advance(self, **kwargs):
        if self.error:
            raise self.error
        return {"action": "counter"}


async def test_negotiation_introspection_maps_the_services_refusals():
    error = NegotiationServiceError("listing gone")
    error.status_code = 404
    routes = NegotiationRoutes(
        repository=lambda: object(),
        negotiation_service=lambda: _NegotiationService(error),
        runtime=lambda: None,
        signer=lambda: CLAIMANT_SIGNER,
    )
    refused = await _refused(routes.list("L-1", terminal_state="", limit=50, offset=0))
    assert (refused.status_code, refused.detail) == (404, "listing gone")
    refused = await _refused(routes.advance("L-1", "neg-1", AdvanceRequest(action="exit")))
    assert refused.status_code == 404

    listed = NegotiationRoutes(
        repository=lambda: object(),
        negotiation_service=lambda: _NegotiationService(),
        runtime=lambda: None,
        signer=lambda: CLAIMANT_SIGNER,
    )
    page = await listed.list("L-1", terminal_state=None, limit=50, offset=0)
    assert (page.count, page.listing_id) == (1, "L-1")
    unavailable = await _refused(listed.force_accept("L-1", "neg-1", SimpleNamespace(amount=1), actor_principal=BUYER))
    assert (unavailable.status_code, unavailable.detail) == (503, "storefront negotiation is unavailable")


# --- settle -----------------------------------------------------------------


class _Stage:
    def __init__(self, *, settle=None, status=None, refund=None) -> None:
        self._settle = settle
        self._status = status
        self._refund = refund
        self.contexts: list[dict] = []

    async def settle(self, **context):
        self.contexts.append(context)
        if isinstance(self._settle, Exception):
            raise self._settle
        return self._settle

    async def status(self, **context):
        self.contexts.append(context)
        if isinstance(self._status, Exception):
            raise self._status
        return self._status

    async def refund(self, **context):
        self.contexts.append(context)
        if isinstance(self._refund, Exception):
            raise self._refund
        return self._refund


def _accepted_thread(listing_id="L-1", buyer=BUYER) -> tuple[dict, bytes]:
    agreement, raw = accepted_agreement(listing_id)
    thread = {
        "negotiation_id": agreement.negotiation_id,
        "our_listing_id": listing_id,
        "terminal_state": "success",
        "agreement_bytes": raw,
        "buyer_principal": buyer.model_dump(mode="json"),
        "seller_principal": CLAIMANT.model_dump(mode="json"),
    }
    return thread, raw


class _SettleDb(_Threads):
    def __init__(self, thread, progress=None) -> None:
        super().__init__(thread)
        self.progress = progress

    async def load_issuance_progress(self, *, reference):
        return self.progress


def _settle_routes(db, stage, *, signer=CLAIMANT_SIGNER, composition=None) -> SettleRoutes:
    composition = composition or SimpleNamespace(stages={"opaque.future.v1": stage})
    return SettleRoutes(
        repository=lambda: db,
        composition=lambda: composition,
        coordinator=lambda: "coordinator",
        signer=lambda: signer,
    )


def _settle_request(**overrides) -> QuotaSettleRequest:
    values = {"negotiation_id": "neg-accepted", "buyer_principal": BUYER}
    values.update(overrides)
    return QuotaSettleRequest(**values)


async def test_settle_runs_the_accepted_stage_with_the_routes_context():
    thread, _raw = _accepted_thread()
    stage = _Stage(settle=SettleResult(202, {"status": "provisioning"}))
    db = _SettleDb(thread)
    routes = _settle_routes(db, stage)

    outcome = await routes.settle("0xescrow", _settle_request())

    assert (outcome.status_code, outcome.payload) == (202, {"status": "provisioning"})
    (context,) = stage.contexts
    assert context["db"] is db
    assert (context["reference"], context["coordinator"], context["thread"]) == ("0xescrow", "coordinator", thread)
    assert context["signer"] is CLAIMANT_SIGNER


@pytest.mark.parametrize(
    ("request_overrides", "signer", "status", "detail"),
    [
        ({"buyer_principal": STRANGER}, CLAIMANT_SIGNER, 403, "settlement parties differ from accepted Agreement"),
        ({}, Ed25519Signer(bytes(range(3, 35))), 403, "settlement parties differ from accepted Agreement"),
        ({"settlement_mechanism": "other.v1"}, CLAIMANT_SIGNER, 400, "settlement mechanism conflicts with accepted Agreement"),
    ],
)
async def test_settle_refuses_a_request_that_disagrees_with_the_agreement(request_overrides, signer, status, detail):
    thread, _raw = _accepted_thread()
    stage = _Stage(settle=SettleResult(200, {}))
    routes = _settle_routes(_SettleDb(thread), stage, signer=signer)

    refused = await _refused(routes.settle("0xescrow", _settle_request(**request_overrides)))

    assert (refused.status_code, refused.detail) == (status, detail)
    assert stage.contexts == []


async def test_settle_refuses_an_unaccepted_or_unsupported_deal():
    thread, _raw = _accepted_thread()
    unaccepted = _settle_routes(_SettleDb({**thread, "terminal_state": None}), _Stage())
    refused = await _refused(unaccepted.settle("0xescrow", _settle_request()))
    assert (refused.status_code, refused.detail) == (409, "accepted Agreement is unavailable or invalid")

    unsupported = _settle_routes(_SettleDb(thread), _Stage(), composition=SimpleNamespace(stages={}))
    refused = await _refused(unsupported.settle("0xescrow", _settle_request()))
    assert (refused.status_code, refused.detail) == (400, "unsupported accepted settlement mechanism")

    uncomposed = SettleRoutes(
        repository=lambda: _SettleDb(thread), composition=lambda: None, coordinator=lambda: None, signer=lambda: None
    )
    refused = await _refused(uncomposed.settle("0xescrow", _settle_request()))
    assert (refused.status_code, refused.detail) == (503, "settlement composition is not initialized")


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (SettlementRefusal(409, "no verified payment"), 409, "no verified payment"),
        (ValueError("amount mismatch"), 400, "amount mismatch"),
        (RuntimeError("authority down"), 502, "settlement authority is unavailable"),
    ],
)
async def test_a_stages_settle_failure_is_served_by_its_kind(error, status, detail):
    thread, _raw = _accepted_thread()
    routes = _settle_routes(_SettleDb(thread), _Stage(settle=error))

    refused = await _refused(routes.settle("0xescrow", _settle_request()))

    assert (refused.status_code, refused.detail) == (status, detail)


async def test_status_resolves_the_deal_then_admits_its_buyer_before_reporting():
    thread, _raw = _accepted_thread()
    payload = {
        "escrow_uid": "0xescrow",
        "buyer_principal": BUYER.model_dump(mode="json"),
        "seller_principal": CLAIMANT.model_dump(mode="json"),
        "status": "ready",
    }
    stage = _Stage(status=SettleResult(200, payload))
    db = _SettleDb(thread, progress={"negotiation_id": "neg-accepted"})
    routes = _settle_routes(db, stage)
    admitted = []

    async def verify(buyer):
        admitted.append(buyer)

    response = await routes.status("0xescrow", verify_buyer=verify)

    assert admitted == [BUYER]
    assert response.status == "ready"
    (context,) = stage.contexts
    assert context["body"].negotiation_id == "neg-accepted"
    assert context["body"].buyer_principal == BUYER


async def test_status_of_an_unknown_reference_is_not_found_before_authentication():
    routes = _settle_routes(_SettleDb(None), _Stage())

    async def verify(buyer):
        raise AssertionError("nothing to admit")

    refused = await _refused(routes.status("0xunknown", verify_buyer=verify))
    assert (refused.status_code, refused.detail) == (404, "settlement progress is unavailable")

    thread, _raw = _accepted_thread()
    silent = _settle_routes(_SettleDb(thread), _Stage(status=None))

    async def admit(buyer):
        return None

    refused = await _refused(silent.status("neg-accepted", verify_buyer=admit))
    assert (refused.status_code, refused.detail) == (404, "settlement progress is unavailable")


async def test_a_wait_must_state_its_timeout_and_signs_it_as_sent():
    routes = _settle_routes(_SettleDb(None), _Stage())

    assert await routes.wait_resource("0xescrow", "5") == "0xescrow?timeout=5"
    refused = await _refused(routes.wait_resource("0xescrow", None))
    assert (refused.status_code, refused.detail) == (400, "admin settlement wait requires explicit timeout")


async def test_a_wait_returns_once_the_progress_is_terminal():
    thread, _raw = _accepted_thread()
    routes = _settle_routes(_SettleDb(thread, progress={"status": "ready"}), _Stage())

    waited = await routes.wait("0xescrow", timeout=1.0)

    assert (waited.ready, waited.status) == (True, "ready")


async def test_refund_runs_the_accepted_stage_and_refuses_an_unaccepted_deal():
    thread, _raw = _accepted_thread()
    stage = _Stage(refund=SettleResult(200, {"negotiation_id": "neg-accepted", "settlement_ref": "tx", "status": "refunded"}))
    routes = _settle_routes(_SettleDb(thread), stage)

    outcome = await routes.refund("neg-accepted")
    assert outcome.payload["status"] == "refunded"
    assert stage.contexts[0]["negotiation_id"] == "neg-accepted"

    refused = await _refused(_settle_routes(_SettleDb({**thread, "terminal_state": None}), stage).refund("neg-accepted"))
    assert (refused.status_code, refused.detail) == (404, "accepted negotiation not found")


# --- system -----------------------------------------------------------------


class _System:
    async def get_health(self, *, include_registry=False):
        return {"status": "ok", "checks": {"api": "ok"}}

    async def status(self, *, paused, loops):
        return {"status": "ok", "checks": {"api": "ok"}, "paused": paused, "lifecycle": None}


async def test_system_health_and_the_administrators_status():
    pause = TradingPause()
    pause.pause()
    routes = SystemRoutes(repository=lambda: object(), system_service=lambda: _System(), trading_pause=pause, loops=lambda: None)

    assert (await routes.health()).status == "ok"
    assert (await routes.status()).paused is True
    query = [("since_id", "3"), ("stage", "negotiation")]
    assert await routes.events_resource(query) == StageEventRouteService.signed_resource(query)
    refused = await _refused(routes.events_resource([("stream", "true")]))
    assert refused.status_code == 400

    uncomposed = SystemRoutes(repository=lambda: None, system_service=lambda: None, trading_pause=pause, loops=lambda: None)
    assert (await _refused(uncomposed.health())).status_code == 503
