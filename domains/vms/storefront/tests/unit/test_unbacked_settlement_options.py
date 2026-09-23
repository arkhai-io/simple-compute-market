"""An unbacked listing publishes only options VM does not fulfil through capacity."""

from __future__ import annotations

import pytest

from market_storefront.services.listing_service import ListingService
from market_storefront.settlement_composition import (
    UndeclaredMechanismFulfillmentError,
    VM_MECHANISM_FULFILLS_THROUGH_CAPACITY,
    admissible_settlement_clauses,
    mechanism_fulfills_through_capacity,
)

_DECLARED = {"alkahest.v1": True, "fiat.stripe.v1": True, "contact-exchange.v1": False}


def _option(mechanism):
    return {"option_id": mechanism, "mechanism": mechanism}


def test_every_mechanism_the_vm_storefront_composes_is_declared():
    assert set(VM_MECHANISM_FULFILLS_THROUGH_CAPACITY) == {
        "alkahest.v1",
        "fiat.stripe.v1",
    }


def test_an_undeclared_mechanism_is_refused_not_defaulted():
    with pytest.raises(UndeclaredMechanismFulfillmentError):
        mechanism_fulfills_through_capacity("new.v1", _DECLARED)


def test_a_backed_candidate_keeps_every_option():
    options = [_option("alkahest.v1"), _option("fiat.stripe.v1")]

    kept, dropped = admissible_settlement_clauses(
        options, capacity_backing="backed", declarations=_DECLARED
    )

    assert (kept, dropped) == (options, [])


def test_an_unbacked_candidate_drops_capacity_fulfilled_options():
    options = [_option("fiat.stripe.v1"), _option("contact-exchange.v1")]

    kept, dropped = admissible_settlement_clauses(
        options, capacity_backing="unbacked", declarations=_DECLARED
    )

    assert kept == [_option("contact-exchange.v1")]
    assert dropped == ["fiat.stripe.v1"]


def test_an_unbacked_listing_left_with_no_option_is_refused():
    composition = type("C", (), {"mechanism_fulfillment": _DECLARED})()

    with pytest.raises(ValueError, match="no settlement option"):
        ListingService._unbacked_settlement_terms(
            accepted_escrows=[{"chain_name": "anvil"}],
            settlement_options=[_option("fiat.stripe.v1")],
            clauses=(),
            demands=[{"arbiter": "x"}],
            composition=composition,
            source="site-a/broker-a",
        )


def test_an_unbacked_listing_keeps_its_escrow_free_option():
    composition = type("C", (), {"mechanism_fulfillment": _DECLARED})()

    escrows, options, _clauses, demands = ListingService._unbacked_settlement_terms(
        accepted_escrows=[{"chain_name": "anvil"}],
        settlement_options=[_option("contact-exchange.v1")],
        clauses=(),
        demands=[{"arbiter": "x"}],
        composition=composition,
        source="site-a/broker-a",
    )

    assert escrows == [] and demands == []
    assert options == [_option("contact-exchange.v1")]
