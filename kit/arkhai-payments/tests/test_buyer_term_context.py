"""The buyer helper's term context takes what a seller's rate presets publish."""

from __future__ import annotations

from dataclasses import replace

import pytest
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import TermContext, validate_terms

from market_arkhai_payments.buyer import approvable_terms
from market_arkhai_payments.fixtures import dispute_lifecycle, recurring_options

from payment_terms import OTHER


def test_the_buyer_term_context_takes_the_spot_and_on_demand_options_a_seller_publishes():
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle(OTHER)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": ["arkhai.payments.v1"],
                          "minimum_dispute_window_seconds": 0, "minimum_case_hold_seconds": None},
    })
    plain = TermContext(
        mechanism="arkhai.payments.v1", has_adapter=True, compute=True,
        dispute_interfaces=frozenset({authority.interface}), authority=authority.requirements,
    )
    for option in recurring_options(authority, payee=OTHER).values():
        with pytest.raises(ValueError, match="stoppable part"):
            validate_terms(option["lifecycle"], plain)
        assert validate_terms(option["lifecycle"], approvable_terms(plain)) is not None
    with pytest.raises(ValueError):
        approvable_terms(replace(plain, mechanism="alkahest.v1"))
