"""Approval expiry is one term under two names: `window` and `approval_window`."""

from __future__ import annotations

import asyncio

import pytest
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_deal_lifecycle.configuration import DisputeEntry
from market_settlement_runtime import SettlementPublicationClause

from market_arkhai_payments.fixtures import dispute_lifecycle
from market_arkhai_payments.mandates import PaymentsOptionParams
from market_arkhai_payments.settlement_config import (
    ARKHAI_PAYMENTS_MECHANISM, ArkhaiPaymentsPublicationInput, arkhai_payments_option_builder,
    arkhai_payments_preflight, create_arkhai_payments_registration,
)

from payment_terms import DISPUTE, PAYEE, config

RATE = {"period": "PT1H", "reserve_ahead_seconds": 3600}


def _resources(clause):
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": [ARKHAI_PAYMENTS_MECHANISM],
                          "minimum_dispute_window_seconds": 0, "minimum_case_hold_seconds": None},
    })
    return {"publication_clause": clause, "dispute_authorities": (authority,),
            "dispute_interfaces": frozenset({authority.interface})}


@pytest.mark.parametrize("name", ["window", "approval_window"])
def test_either_name_is_the_one_approval_term(name):
    params = PaymentsOptionParams.model_validate({"payee_account": PAYEE, name: "PT10M"})
    assert params.approval_term == "PT10M" and params.approval_seconds == 600


def test_a_document_naming_both_is_refused_even_when_they_agree():
    for window in ("PT10M", "P7D"):
        with pytest.raises(ValueError, match="one term"):
            PaymentsOptionParams.model_validate({"payee_account": PAYEE, "window": window, "approval_window": "PT10M"})


def test_a_null_name_beside_a_given_one_names_nothing():
    params = PaymentsOptionParams.model_validate({"payee_account": PAYEE, "window": "PT10M", "approval_window": None})
    assert params.approval_seconds == 600


def test_neither_name_keeps_the_released_default():
    assert PaymentsOptionParams.model_validate({"payee_account": PAYEE}).approval_term == "P7D"


@pytest.mark.parametrize("mode", ["python", "json"])
def test_a_dump_names_the_approval_term_it_was_given_and_validates_again(mode):
    # A storefront compiles a clause's dumped publication input again, so the
    # dump must not carry `window`'s default beside a given `approval_window`.
    given = {"payee_account": PAYEE, "asset": "USD/6", "approval_window": "PT5M",
             "dispute_window_seconds": 900, "delivery_deadline_seconds": 300, **RATE}
    dumped = ArkhaiPaymentsPublicationInput.model_validate(given).model_dump(mode=mode)
    assert "window" not in dumped and dumped["approval_window"] == "PT5M"
    assert ArkhaiPaymentsPublicationInput.model_validate(dumped).approval_seconds == 300
    assert PaymentsOptionParams.model_validate(
        {"payee_account": PAYEE, "approval_window": "PT5M"}).model_dump()["approval_window"] == "PT5M"


def test_a_dump_of_a_model_given_window_is_unchanged():
    dumped = PaymentsOptionParams.model_validate({"payee_account": PAYEE, "window": "PT10M"}).model_dump(mode="json")
    assert dumped == {"payee_account": PAYEE, "window": "PT10M", "deposit_agreement": False,
                      "approval_window": None, "period": None, "reserve_ahead_seconds": None,
                      "setup_amount": None}
    assert PaymentsOptionParams.model_validate(dumped).approval_seconds == 600


@pytest.mark.parametrize("name", ["window", "approval_window"])
def test_a_once_option_is_written_with_window_whichever_name_its_clause_used(name):
    settings = config()
    readiness = asyncio.run(arkhai_payments_preflight(settings, {}, "seller"))
    clause = SettlementPublicationClause.model_validate({
        "mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": "USD/2", "rate": "1.25", "per": "hour",
        "mechanism_input": {"payee_account": PAYEE, "asset": "USD/2", name: "PT10M",
                            "dispute_window_seconds": 604800},
    })
    option = arkhai_payments_option_builder(settings, readiness, _resources(clause), "seller")["settlement_options"][0]
    assert option["settlement"]["window"] == "PT10M" and "approval_window" not in option["settlement"]
    # A released reader, which knows only `window`, reads the same expiry.
    assert PaymentsOptionParams.model_validate(
        {k: v for k, v in option["settlement"].items() if k != "schema"}).approval_seconds == 600


def _option(settlement: dict) -> SettlementOption:
    price = {"asset": "USD/2", "rates": []}
    full = {"schema": ARKHAI_PAYMENTS_MECHANISM, "payee_account": PAYEE, **settlement}
    return SettlementOption(option_id=derive_settlement_option_id(price=price, settlement=full),
                            price=price, settlement=full)


def test_approval_window_is_discovered_on_every_option_and_window_only_on_once_options():
    projectors = {field.descriptor.name: field.projector
                  for field in create_arkhai_payments_registration().clause_fields}
    once, rate = _option({"window": "PT10M"}), _option({"approval_window": "PT10M", **RATE})
    assert projectors["arkhai_payments.approval_window"](once) == "PT10M"
    assert projectors["arkhai_payments.approval_window"](rate) == "PT10M"
    assert projectors["arkhai_payments.window"](once) == "PT10M"
    assert projectors["arkhai_payments.window"](rate) is None
