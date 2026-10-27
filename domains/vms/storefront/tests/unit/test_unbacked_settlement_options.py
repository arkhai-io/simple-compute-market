"""An unbacked listing publishes only options VM does not fulfil through capacity."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core_storefront.publication_runner import NoSettlementOption
from market_resource_pools_contracts.backing import BACKED, UNBACKED
from market_settlement_runtime import MechanismReadiness, ReadinessBlocker

from market_storefront.domain_runtime import build_vm_seller_stages
from market_storefront.services.listing_service import ListingService
from market_storefront.settlement_stages import (
    VmAlkahestSellerStage,
    VmContactSellerStage,
    VmPaymentsSellerStage,
)


def _option(mechanism):
    return {"option_id": mechanism, "mechanism": mechanism}


def _composition():
    return SimpleNamespace(seller_stages=build_vm_seller_stages())


def _terms(
    backing,
    *,
    accepted_escrows,
    settlement_options,
    demands=(),
    clauses=(),
    readiness=(),
    escrows_supplied=False,
):
    return ListingService._admissible_settlement_terms(
        backing=backing,
        accepted_escrows=list(accepted_escrows),
        settlement_options=list(settlement_options),
        clauses=tuple(clauses),
        demands=list(demands),
        composition=_composition(),
        source="site-a/broker-a",
        readiness=tuple(readiness),
        escrows_supplied=escrows_supplied,
    )


def _clause(mechanism):
    return {"mechanism": mechanism}


def _unready(mechanism, *kinds):
    return MechanismReadiness(
        mechanism=mechanism,
        configured=True,
        enabled=True,
        ready=False,
        blockers=tuple(
            ReadinessBlocker(code=f"{kind}.blocker", message="unready", kind=kind)
            for kind in kinds
        ),
    )


def _ready(mechanism):
    return MechanismReadiness(mechanism=mechanism, configured=True, enabled=True, ready=True)


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


def test_every_vm_seller_stage_declares_whether_it_completes_outside_settlement():
    declared = {
        mechanism: stage.completes_outside_settlement
        for mechanism, stage in build_vm_seller_stages().items()
    }

    assert declared == {
        "alkahest.v1": False,
        "arkhai.payments.v1": False,
        "contact-exchange.v1": True,
    }


@pytest.mark.parametrize(
    "build_stage",
    [
        pytest.param(
            lambda **declarations: VmAlkahestSellerStage(
                build_plan=lambda **_: None, release_models=frozenset(), **declarations
            ),
            id="alkahest",
        ),
        pytest.param(VmPaymentsSellerStage, id="payments"),
        pytest.param(VmContactSellerStage, id="contact"),
    ],
)
@pytest.mark.parametrize(
    "declaration", ["fulfils_through_capacity", "completes_outside_settlement"]
)
def test_a_stage_without_a_declaration_cannot_be_constructed(build_stage, declaration):
    declarations = {"fulfils_through_capacity": True, "completes_outside_settlement": False}
    del declarations[declaration]

    with pytest.raises(TypeError, match=declaration):
        build_stage(**declarations)


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
    with pytest.raises(NoSettlementOption, match="no settlement option") as refused:
        _terms(
            UNBACKED,
            accepted_escrows=[{"chain_name": "anvil"}],
            settlement_options=[_option("arkhai.payments.v1")],
            demands=[{"arbiter": "x"}],
            clauses=[_clause("arkhai.payments.v1")],
        )

    # Nothing it could publish remains, so configuration rules every mechanism out.
    assert refused.value.mechanisms == ()
    assert refused.value.ruled_out_by_configuration is True


def test_a_mechanism_with_only_reachability_blockers_is_unknown():
    with pytest.raises(NoSettlementOption) as refused:
        _terms(
            BACKED,
            accepted_escrows=[],
            settlement_options=[],
            clauses=[_clause("alkahest.v1"), _clause("contact-exchange.v1")],
            readiness=[
                _unready("alkahest.v1", "reachability"),
                _ready("contact-exchange.v1"),
            ],
        )

    assert refused.value.mechanisms == ("alkahest.v1", "contact-exchange.v1")
    assert refused.value.unknown == ("alkahest.v1",)
    assert refused.value.ruled_out_by_configuration is False


def test_a_configuration_blocker_rules_a_mechanism_out_whatever_else_it_reports():
    with pytest.raises(NoSettlementOption) as refused:
        _terms(
            BACKED,
            accepted_escrows=[],
            settlement_options=[],
            clauses=[_clause("alkahest.v1")],
            readiness=[_unready("alkahest.v1", "configuration", "reachability")],
        )

    assert refused.value.unknown == ()
    assert refused.value.ruled_out_by_configuration is True


def test_an_unknown_mechanism_the_listing_could_never_publish_holds_nothing():
    """Unbacked VM listings cannot publish Alkahest, so its unreachable chain
    says nothing about the offer; contact exchange building nothing rules the
    listing's only admissible mechanism out."""
    with pytest.raises(NoSettlementOption) as refused:
        _terms(
            UNBACKED,
            accepted_escrows=[],
            settlement_options=[],
            clauses=[_clause("alkahest.v1"), _clause("contact-exchange.v1")],
            readiness=[
                _unready("alkahest.v1", "reachability"),
                _ready("contact-exchange.v1"),
            ],
        )

    assert refused.value.mechanisms == ("contact-exchange.v1",)
    assert refused.value.ruled_out_by_configuration is True


def test_supplied_escrows_count_alkahest_among_the_mechanisms():
    with pytest.raises(NoSettlementOption) as refused:
        _terms(
            BACKED,
            accepted_escrows=[],
            settlement_options=[],
            readiness=[_unready("alkahest.v1", "reachability")],
            escrows_supplied=True,
        )

    assert refused.value.mechanisms == ("alkahest.v1",)
    assert refused.value.unknown == ("alkahest.v1",)


def test_an_unbacked_listing_keeps_its_escrow_free_option():
    escrows, options, _clauses, demands = _terms(
        UNBACKED,
        accepted_escrows=[{"chain_name": "anvil"}],
        settlement_options=[_option("contact-exchange.v1")],
        demands=[{"arbiter": "x"}],
    )

    assert escrows == [] and demands == []
    assert options == [_option("contact-exchange.v1")]
