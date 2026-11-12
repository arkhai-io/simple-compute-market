"""The bare-metal buyer takes the spot and on-demand options a seller publishes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle, recurring_options
from market_core.schemas import SettlementOption
from market_deal_lifecycle.configuration import DisputeEntry

from arkhai_bare_metal_buyer.settlement_composition import (
    buyer_lifecycle_disclosure,
    validate_authority,
)


@pytest.mark.parametrize("kind", ["spot", "on-demand"])
def test_a_recurring_option_a_seller_publishes_passes_the_buyers_authority_check(kind):
    # Development accounts, never used on a public network.
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle("33333333-3333-4333-8333-333333333333")["adjudication"]["dispute"],
        "interface": MEDIATION_INTERFACE,
        "advertisement": {"mechanisms": ["arkhai.payments.v1"],
                          "minimum_dispute_window_seconds": 0, "minimum_case_hold_seconds": None},
    })
    option = SettlementOption.model_validate(recurring_options(
        authority, payee="22222222-2222-4222-8222-222222222222",
    )[kind])
    config = SimpleNamespace(
        registry_url="https://registry.example",
        dispute_authorities_by_registry={"https://registry.example": (authority,)},
    )

    validate_authority(option, config)

    rows = dict(buyer_lifecycle_disclosure(option))
    assert rows["Seller stop"].startswith(
        "Entitled with 120 seconds' notice" if kind == "spot" else "No entitled payment stop"
    )
