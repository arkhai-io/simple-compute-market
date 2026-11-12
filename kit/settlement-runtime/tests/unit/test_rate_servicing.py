"""The composition's rate servicing declaration and the option gate it backs."""

from __future__ import annotations

from typing import get_args

import pytest
from market_core.schemas import RateValue, SettlementOption, SettlementPrice, derive_settlement_option_id
from market_deal_lifecycle.terms import (
    Adjudication, DisputeAuthority, EarlyTermination, Entitlement, LifecycleTerms, encode_terms,
)
from market_settlement_runtime.rate_servicing import (
    TREATMENTS, RateServicing, RateServicingDeclaration, RateServicingUnavailable, Treatment,
)

MECHANISM = "fixture.rate.v1"
# A fictional authority: the origin is a reserved name that resolves nowhere.
AUTHORITY = DisputeAuthority(
    interface="fixture.mediation.v1", origin="https://mediation.invalid",
    account="fixture-account", record_key="fixture-record", params={},
)
KEYS = {"fixture_rate": MECHANISM}


def _option(*, term_end="last_boundary", payee=None, setup=None, rate=True) -> SettlementOption:
    entitlements = {"payer": Entitlement(notice_seconds=0, settles_through="started_period")}
    if payee is not None:
        entitlements["payee"] = Entitlement(notice_seconds=0, settles_through=payee)
    lifecycle = encode_terms(LifecycleTerms(
        adjudication=Adjudication(version=1, dispute=AUTHORITY, dispute_window_seconds=604800,
                                  case_hold_max_seconds=None),
        early_termination=EarlyTermination(version=1, settles_through=term_end, entitlements=entitlements),
        delivery_deadline_seconds=1200,
    ))
    price = SettlementPrice(asset="USD/6", rates=[RateValue(field="amount", per="hour", value=2500000)])
    settlement = {"schema": MECHANISM}
    if rate:
        settlement |= {"period": "PT15M", "reserve_ahead_seconds": 1800}
    if setup is not None:
        settlement["setup_amount"] = setup
    return SettlementOption(
        option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
        price=price, settlement=settlement, lifecycle=lifecycle,
    )


def _servicing(*treatments: str, setup: bool = False) -> RateServicing:
    return RateServicing({MECHANISM: RateServicingDeclaration(MECHANISM, frozenset(treatments), setup)})


def test_a_table_declares_a_mechanism_s_treatments_and_setup():
    servicing = RateServicing.from_tables(
        {"fixture_rate": {"treatments": ["charged", "returned"], "setup": True}}, mechanism_for=KEYS,
    )
    assert servicing.select(MECHANISM) == RateServicingDeclaration(
        MECHANISM, frozenset({"charged", "returned"}), True,
    )
    assert RateServicing.from_tables(
        {"fixture_rate": {"treatments": ["charged"]}}, mechanism_for=KEYS,
    ).select(MECHANISM).setup is False


@pytest.mark.parametrize("tables", [{}, {"fixture_rate": {}}, {"fixture_rate": {"treatments": []}}],
                         ids=["absent", "no-treatments", "empty"])
def test_an_absent_or_empty_declaration_services_nothing(tables):
    servicing = RateServicing.from_tables(tables, mechanism_for=KEYS)
    with pytest.raises(RateServicingUnavailable, match="settlement_option_withdrawn_refetch"):
        servicing.select(MECHANISM)
    with pytest.raises(RateServicingUnavailable):
        servicing.require_option(_option())


@pytest.mark.parametrize(("tables", "message"), [
    ({"ghost": {"treatments": ["charged"]}}, "names no installed mechanism"),
    ({"fixture_rate": ["charged"]}, "must be a table"),
    ({"fixture_rate": {"treatments": ["charged"], "lane": "x"}}, r"rate_servicing\.fixture_rate\.lane"),
    ({"fixture_rate": {"treatments": "charged"}}, r"rate_servicing\.fixture_rate\.treatments"),
    ({"fixture_rate": {"treatments": ["charged"], "setup": "yes"}}, r"rate_servicing\.fixture_rate\.setup"),
    ({"fixture_rate": {"treatments": ["started_period"]}}, r"rate_servicing\.fixture_rate\.treatments\.0"),
])
def test_a_malformed_table_is_refused(tables, message):
    with pytest.raises(ValueError, match=message):
        RateServicing.from_tables(tables, mechanism_for=KEYS)


def test_the_table_names_the_payment_authority_s_treatments():
    assert frozenset(get_args(Treatment)) == TREATMENTS


def test_a_once_option_needs_no_declaration():
    RateServicing().require_option(_option(rate=False))


def test_a_declared_option_is_admitted():
    _servicing("charged", "returned").require_option(_option(payee="last_boundary"))
    _servicing("charged").require_option(_option(term_end="started_period"))


def test_an_undeclared_entitlement_treatment_is_refused():
    # The term end is charged, as declared; the seller's stop returns its period.
    with pytest.raises(RateServicingUnavailable, match="does not declare returned"):
        _servicing("charged").require_option(_option(term_end="started_period", payee="last_boundary"))


def test_an_undeclared_term_end_treatment_is_refused():
    with pytest.raises(RateServicingUnavailable, match="does not declare prorated"):
        _servicing("charged", "returned").require_option(_option(term_end="stop"))


def test_a_setup_charge_needs_setup_declared():
    with pytest.raises(RateServicingUnavailable, match="does not declare a setup charge"):
        _servicing("charged", "returned").require_option(_option(setup="100"))
    _servicing("charged", "returned", setup=True).require_option(_option(setup="100"))


@pytest.mark.parametrize("marker", [{"period": "PT15M"}, {"reserve_ahead_seconds": 1800}])
def test_either_rate_marker_alone_requires_servicing(marker):
    price = SettlementPrice(asset="USD/6", rates=[RateValue(field="amount", per="hour", value=1)])
    settlement = {"schema": MECHANISM, **marker}
    half = SettlementOption(
        option_id=derive_settlement_option_id(price=price, settlement=settlement),
        price=price, settlement=settlement,
    )
    with pytest.raises(RateServicingUnavailable):
        RateServicing().require_option(half.model_dump(mode="json"))
