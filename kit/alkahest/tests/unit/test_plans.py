"""alkahest.v1 settlement-plan codec: converters + materialization parity."""

from __future__ import annotations

import pytest

from market_alkahest.plans import (
    ALKAHEST_MECHANISM,
    SettlementObligation,
    SettlementPlan,
    escrow_terms_from_settlement_plan,
    escrow_terms_to_settlement_obligation,
    materialize_settlement_plan_from_proposal,
    settlement_obligation_to_escrow_terms,
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
