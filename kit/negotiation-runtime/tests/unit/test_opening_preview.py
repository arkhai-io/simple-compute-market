from __future__ import annotations

import pytest
from market_policy.negotiation_middleware import NegotiationDecision

from test_runtime import _BUYER, _SELLER, HookHarness, RecordingRepository, runtime_for


async def _preview(repository, harness, **overrides):
    values = {
        "repository": repository,
        "listing_id": "listing-1",
        "buyer_principal": _BUYER,
        "seller_principal": _SELLER,
        "proposal": {"price": 10},
        "terms": {"units": 7},
    }
    values.update(overrides)
    return await runtime_for(repository, harness).preview_opening(**values)


@pytest.mark.asyncio
async def test_preview_reports_the_round_zero_decision_and_writes_nothing() -> None:
    repository = RecordingRepository()
    harness = HookHarness()

    preview = await _preview(repository, harness)

    assert preview.refused is False
    assert preview.decision == "counter"
    assert preview.our_amount == 15
    assert preview.their_amount == 10
    assert preview.decision_amount == 12
    assert preview.strategy == "domain-policy"
    assert repository.threads == {}
    assert repository.agreements == []
    assert repository.effects == []
    assert harness.events == []
    assert len(harness.policy_calls) == 1


@pytest.mark.asyncio
async def test_preview_of_an_accepting_opening_places_no_hold() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
    harness.next_decision = NegotiationDecision(action="accept", proposal={"price": 10})

    preview = await _preview(repository, harness)

    assert preview.decision == "accept"
    assert repository.effects == []
    assert repository.agreements == []


@pytest.mark.asyncio
async def test_preview_reports_an_opening_validation_refusal() -> None:
    repository = RecordingRepository()
    harness = HookHarness()

    preview = await _preview(repository, harness, terms={"units": 0})

    assert preview.refused is True
    assert "units must be positive" in preview.refusal
    assert harness.policy_calls == []


@pytest.mark.asyncio
async def test_preview_reports_a_closed_listing_as_start_would() -> None:
    repository = RecordingRepository()
    repository.listings["listing-1"]["open"] = False
    harness = HookHarness()

    preview = await _preview(repository, harness)

    assert preview.refused is True
    assert "listing_not_open" in preview.refusal


@pytest.mark.asyncio
async def test_preview_reports_a_policy_rejection() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
    harness.next_decision = NegotiationDecision(action="reject", reason="no_inventory")

    preview = await _preview(repository, harness)

    assert preview.refused is True
    assert "no_inventory" in preview.refusal
    assert repository.threads == {}
