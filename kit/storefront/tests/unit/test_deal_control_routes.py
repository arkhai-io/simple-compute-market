from __future__ import annotations

from types import SimpleNamespace

import pytest
from core_storefront.models.listing_models import EvaluateNegotiateRequest
from core_storefront.models.negotiation_models import ForceAcceptRequest
from market_identity import Ed25519Signer
from market_negotiation_runtime import NegotiationStateError
from market_storefront_kit import (
    DealControlRouteError,
    NegotiationControlRouteService,
    StageEventRouteService,
    opening_proposal,
)

BUYER = Ed25519Signer(b"\x11" * 32).identity
SELLER = Ed25519Signer(b"\x21" * 32).identity
ADMIN = Ed25519Signer(b"\x31" * 32).identity
TERMS = {"kind": "compute.vm", "version": 1, "payload": {"gpu_count": 1}}


class FakeRuntime:
    def __init__(self) -> None:
        self.previews: list[dict] = []
        self.accepts: list[dict] = []
        self.preview = SimpleNamespace(
            refused=False,
            refusal=None,
            our_amount=15,
            their_amount=10,
            strategy="bisection",
            decision="counter",
            decision_amount=12,
            decision_proposal={"fields": {"amount": "12"}},
            decision_reason=None,
        )
        self.accept_error: Exception | None = None

    async def preview_opening(self, **values):
        self.previews.append(values)
        return self.preview

    async def accept_administratively(self, **values):
        self.accepts.append(values)
        if self.accept_error is not None:
            raise self.accept_error
        return {"action": "accept", "amount": values["amount"], "source": "admin_force_accept"}


def _service(runtime: FakeRuntime) -> NegotiationControlRouteService:
    return NegotiationControlRouteService(
        runtime=runtime, repository=object(), seller_principal=lambda: SELLER
    )


def _opening(**overrides) -> EvaluateNegotiateRequest:
    values = {
        "buyer_principal": BUYER,
        "provision_terms": TERMS,
        "proposal": {"fields": {"amount": "10"}},
    }
    values.update(overrides)
    return EvaluateNegotiateRequest.model_validate(values)


async def test_evaluate_previews_the_opening_negotiate_new_would_send() -> None:
    runtime = FakeRuntime()

    response = await _service(runtime).evaluate_negotiate("listing-1", _opening())

    call = runtime.previews[0]
    assert call["listing_id"] == "listing-1"
    assert call["buyer_principal"] == BUYER
    assert call["seller_principal"] == SELLER
    assert call["proposal"] == {"fields": {"amount": "10"}}
    assert response.decision == "counter"
    assert response.would_negotiate is True
    assert response.refused is False
    assert response.our_reference_amount == 15
    assert response.decision_amount == 12


async def test_evaluate_reports_a_refused_opening() -> None:
    runtime = FakeRuntime()
    runtime.preview = SimpleNamespace(refused=True, refusal="OfferUnfulfillableError: listing_not_open")

    response = await _service(runtime).evaluate_negotiate("listing-1", _opening())

    assert response.refused is True
    assert response.decision == "refused"
    assert response.would_negotiate is False
    assert response.our_reference_amount is None
    assert "listing_not_open" in response.decision_reason


async def test_force_accept_goes_through_administrative_acceptance() -> None:
    runtime = FakeRuntime()

    response = await _service(runtime).force_accept(
        "listing-1",
        "neg-1",
        ForceAcceptRequest(amount="13"),
        actor_principal=ADMIN,
    )

    assert runtime.accepts[0]["negotiation_id"] == "neg-1"
    assert runtime.accepts[0]["amount"] == 13
    assert runtime.accepts[0]["actor_principal"] == ADMIN
    assert response.action == "accept"
    assert response.amount == 13


@pytest.mark.parametrize(
    ("message", "status"),
    [
        ("Unknown negotiation neg-1", 404),
        ("Negotiation neg-1 does not belong to listing listing-1", 404),
        ("Negotiation neg-1 is already in terminal state 'success'", 409),
    ],
)
async def test_force_accept_maps_refusals(message: str, status: int) -> None:
    runtime = FakeRuntime()
    runtime.accept_error = NegotiationStateError(message)

    with pytest.raises(DealControlRouteError) as refused:
        await _service(runtime).force_accept(
            "listing-1", "neg-1", ForceAcceptRequest(amount="13"), actor_principal=ADMIN
        )
    assert refused.value.status_code == status


def test_opening_proposal_carries_an_exact_selection() -> None:
    selection = SimpleNamespace(model_dump=lambda mode: {"option": "a"})

    assert opening_proposal({"x": 1}, None) == {"x": 1}
    assert opening_proposal(None, selection) == {"settlement_selection": {"option": "a"}}
    assert opening_proposal({"x": 1}, selection) == {
        "x": 1,
        "settlement_selection": {"option": "a"},
    }


class EventLog:
    def __init__(self, rows):
        self.rows = rows

    async def list_stage_events_page(self, *, after_id, limit, **_filters):
        page = [row for row in self.rows if row["id"] > after_id][:limit]
        return page, len([row for row in self.rows if row["id"] > after_id]) > limit

    async def list_stage_events(self, *, after_id, limit, **_filters):
        return [row for row in self.rows if row["id"] > after_id][:limit]


async def test_stage_event_page_reports_truncation() -> None:
    service = StageEventRouteService(EventLog([{"id": 1}, {"id": 2}, {"id": 3}]))

    page = await service.page(since_id=0, limit=2)

    assert page.count == 2
    assert page.truncated is True


async def test_stage_event_stream_yields_events_from_the_resume_point() -> None:
    service = StageEventRouteService(EventLog([{"id": 1}, {"id": 2}]), poll_seconds=0)

    since = service.resume_point(0, "1")
    stream = service.stream(since_id=since)
    first = await stream.__anext__()
    await stream.aclose()

    assert first.startswith("id: 2\n")
    assert service.resume_point(5, "not-a-number") == 5
