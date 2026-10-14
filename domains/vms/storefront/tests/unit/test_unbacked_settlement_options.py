"""An unbacked listing publishes only options VM does not fulfil through capacity."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_resource_pools_contracts.backing import BACKED, UNBACKED

from market_storefront.domain_runtime import build_vm_seller_stages
from market_storefront.services.listing_service import ListingService
from market_storefront.settlement_stages import VmPaymentsSellerStage


def _option(mechanism):
    return {"option_id": mechanism, "mechanism": mechanism}


def _composition():
    return SimpleNamespace(seller_stages=build_vm_seller_stages())


def _terms(backing, *, accepted_escrows, settlement_options, demands=()):
    return ListingService._admissible_settlement_terms(
        backing=backing,
        accepted_escrows=list(accepted_escrows),
        settlement_options=list(settlement_options),
        clauses=(),
        demands=list(demands),
        composition=_composition(),
        source="site-a/broker-a",
    )


def test_every_vm_seller_stage_declares_whether_it_fulfils_through_capacity():
    declared = {
        mechanism: stage.fulfils_through_capacity
        for mechanism, stage in build_vm_seller_stages().items()
    }

    assert declared == {
        "alkahest.v1": True,
        "arkhai.payments.v1": True,
        "contact-exchange.v1": False,
    }


def test_a_stage_without_the_declaration_cannot_be_constructed():
    with pytest.raises(TypeError, match="fulfils_through_capacity"):
        VmPaymentsSellerStage()


def test_a_backed_listing_keeps_every_option():
    options = [_option("alkahest.v1"), _option("arkhai.payments.v1")]

    escrows, kept, _clauses, _demands = _terms(
        BACKED, accepted_escrows=[{"chain_name": "anvil"}], settlement_options=options
    )

    assert kept == options
    assert escrows == [{"chain_name": "anvil"}]


def test_an_unbacked_listing_drops_capacity_fulfilled_options():
    _escrows, kept, _clauses, _demands = _terms(
        UNBACKED,
        accepted_escrows=[],
        settlement_options=[_option("arkhai.payments.v1"), _option("contact-exchange.v1")],
    )

    assert kept == [_option("contact-exchange.v1")]


def test_an_unbacked_listing_left_with_no_option_is_refused():
    with pytest.raises(ValueError, match="no settlement option"):
        _terms(
            UNBACKED,
            accepted_escrows=[{"chain_name": "anvil"}],
            settlement_options=[_option("arkhai.payments.v1")],
            demands=[{"arbiter": "x"}],
        )


def test_an_unbacked_listing_keeps_its_escrow_free_option():
    escrows, options, _clauses, demands = _terms(
        UNBACKED,
        accepted_escrows=[{"chain_name": "anvil"}],
        settlement_options=[_option("contact-exchange.v1")],
        demands=[{"arbiter": "x"}],
    )

    assert escrows == [] and demands == []
    assert options == [_option("contact-exchange.v1")]
