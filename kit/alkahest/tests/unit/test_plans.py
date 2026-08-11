"""alkahest.v1 settlement-plan codec: converters + materialization parity."""

from __future__ import annotations

import pytest

from market_alkahest.plans import (
    ALKAHEST_MECHANISM,
    build_penalty_bond_obligation,
    SettlementObligation,
    SettlementPlan,
    interval_amount_schedule,
    escrow_terms_from_settlement_plan,
    escrow_terms_to_settlement_obligation,
    materialize_settlement_plan_from_proposal,
    settlement_obligation_to_escrow_terms,
    split_settlement_obligation_into_intervals,
)
from market_alkahest.schemas import EscrowProposal, EscrowTerms

_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "aa" * 20
_SELLER = "0x" + "bb" * 20


def _terms(**overrides) -> EscrowTerms:
    data = {
        "maker": "buyer",
        "chain_name": "base_sepolia",
        "escrow_contract": _ESCROW,
        "obligation_data": {
            "arbiter": "0x" + "22" * 20,
            "demand": "0x" + "cd" * 32,
            "token": _TOKEN,
            "amount": 5_000_000,
        },
        "expiration_unix": 1_800_000_000,
    }
    data.update(overrides)
    return EscrowTerms(**data)


def test_terms_obligation_round_trip_is_lossless() -> None:
    terms = _terms()
    ob = escrow_terms_to_settlement_obligation(terms)
    assert ob.mechanism == ALKAHEST_MECHANISM
    assert ob.payer == "buyer"
    assert ob.claimant == "seller"
    assert ob.amount == 5_000_000
    assert ob.asset == _TOKEN
    back = settlement_obligation_to_escrow_terms(ob)
    assert back == terms


def test_seller_bond_round_trips_maker() -> None:
    terms = _terms(maker="seller")
    ob = escrow_terms_to_settlement_obligation(terms)
    assert (ob.payer, ob.claimant) == ("seller", "buyer")
    assert settlement_obligation_to_escrow_terms(ob).maker == "seller"


def test_unwrap_rejects_foreign_mechanisms() -> None:
    ob = SettlementObligation(
        payer="buyer",
        claimant="seller",
        expiration_unix=1_800_000_000,
        mechanism="fiat.stripe.v1",
        params={},
    )
    with pytest.raises(ValueError, match="alkahest.v1"):
        settlement_obligation_to_escrow_terms(ob)
    with pytest.raises(ValueError, match="alkahest.v1"):
        escrow_terms_from_settlement_plan(SettlementPlan(obligations=[ob]))


def test_plan_view_accepts_legacy_terms_list() -> None:
    terms = _terms()
    out = escrow_terms_from_settlement_plan([terms.model_dump()])
    assert out == [terms]


def test_plan_materialization_matches_terms_materialization() -> None:
    """Both sides may derive either artifact; they must agree byte-for-byte."""
    from market_alkahest.alkahest import materialize_escrow_terms_from_proposal

    proposal = EscrowProposal(
        chain_name="base_sepolia",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": 7_200_000},
        literal_fields={"token": _TOKEN},
        rates=[],
        expiration_unix=1_800_000_000,
    )
    kwargs = dict(
        proposal=proposal,
        seller_wallet_address=_SELLER,
        agreed_amount=7_200_000,
        duration_seconds=3600,
    )
    plan = materialize_settlement_plan_from_proposal(**kwargs)
    terms = materialize_escrow_terms_from_proposal(**kwargs)
    assert [
        settlement_obligation_to_escrow_terms(ob).model_dump()
        for ob in plan.obligations
    ] == [t.model_dump() for t in terms]
    assert plan.obligations[0].amount == 7_200_000
    assert plan.obligations[0].asset == _TOKEN
    assert plan.service_terms == {}


def test_interval_schedule_conserves_total_and_allocates_remainder_earliest() -> None:
    schedule = interval_amount_schedule(
        total_amount=11,
        start_unix=100,
        duration_seconds=10,
        interval_seconds=4,
    )

    assert [item.duration_seconds for item in schedule] == [4, 4, 2]
    assert [item.expiration_unix for item in schedule] == [104, 108, 110]
    assert [item.amount for item in schedule] == [5, 4, 2]
    assert sum(item.amount for item in schedule) == 11


def test_interval_obligations_preserve_abi_demand_and_direction() -> None:
    template = escrow_terms_to_settlement_obligation(
        _terms(
            obligation_data={
                "arbiter": "0x" + "22" * 20,
                "demand": "0x1234",
                "token": _TOKEN,
                "amount": 11,
            },
            expiration_unix=110,
        )
    )

    obligations = split_settlement_obligation_into_intervals(
        template,
        start_unix=100,
        duration_seconds=10,
        interval_seconds=4,
    )

    assert [item.amount for item in obligations] == [5, 4, 2]
    assert [item.expiration_unix for item in obligations] == [104, 108, 110]
    assert [(item.payer, item.claimant) for item in obligations] == [
        ("buyer", "seller"),
        ("buyer", "seller"),
        ("buyer", "seller"),
    ]
    assert [item.params["obligation_data"]["demand"] for item in obligations] == [
        "0x1234",
        "0x1234",
        "0x1234",
    ]
    assert template.amount == 11
    assert template.params["obligation_data"]["amount"] == 11


def test_interval_schedule_rejects_zero_value_obligations() -> None:
    with pytest.raises(ValueError, match="positive amount for every interval"):
        interval_amount_schedule(
            total_amount=2,
            start_unix=100,
            duration_seconds=10,
            interval_seconds=4,
        )


def test_penalty_bond_is_seller_funded_and_preserves_condition_bytes() -> None:
    payment = escrow_terms_to_settlement_obligation(_terms())
    bond = build_penalty_bond_obligation(payment, amount=700_000)

    assert (bond.payer, bond.claimant) == ("seller", "buyer")
    assert bond.amount == 700_000
    assert bond.params["obligation_data"]["amount"] == 700_000
    assert (
        bond.params["obligation_data"]["demand"]
        == payment.params["obligation_data"]["demand"]
    )
    assert payment.amount == 5_000_000
    assert payment.params["obligation_data"]["amount"] == 5_000_000
