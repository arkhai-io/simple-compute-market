"""Observable contracts for domain-neutral E2E deal state."""

from __future__ import annotations

import pytest

from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    ordered_events,
)


def test_complete_deal_carries_opaque_domain_results():
    state = DomainDealState(domain_identity="api_credits.v1")

    state.complete(DealStage.DISCOVERY, listing_id="listing-1")
    state.complete(DealStage.NEGOTIATION, negotiation_id="negotiation-1")
    state.complete(DealStage.SETTLEMENT, settlement_id="settlement-1")
    state.complete(
        DealStage.DELIVERY,
        fulfillment_ref="grant-1",
        delivery={"domain_result": {"safe_key_id": "key-1"}},
    )
    state.complete(
        DealStage.TEARDOWN,
        teardown={"domain_result": {"status_code": 402}},
    )

    state.assert_complete()
    assert state.delivery == {"domain_result": {"safe_key_id": "key-1"}}
    assert state.teardown == {"domain_result": {"status_code": 402}}


def test_deal_stage_order_cannot_skip_a_boundary():
    state = DomainDealState(domain_identity="bare_metal.v1")

    with pytest.raises(AssertionError, match="discovery.*expected"):
        state.complete(DealStage.SETTLEMENT, settlement_id="settlement-1")


def test_stable_binding_cannot_change():
    state = DomainDealState(domain_identity="vms.compute")
    state.listing_id = "listing-1"

    with pytest.raises(AssertionError, match="changed listing_id"):
        state.complete(DealStage.DISCOVERY, listing_id="listing-2")


def test_ordered_events_ignores_domain_specific_events_between_boundaries():
    events = [
        {"event": "discover"},
        {"event": "api_credit_key_challenge"},
        {"event": "negotiation_completed"},
        {"event": "settlement_submitted"},
    ]

    matched = ordered_events(
        events,
        "discover",
        "negotiation_completed",
        "settlement_submitted",
    )

    assert [event["event"] for event in matched] == [
        "discover",
        "negotiation_completed",
        "settlement_submitted",
    ]
