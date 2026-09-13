"""alkahest.v1 settlement-plan codec: converters + materialization parity."""

from __future__ import annotations

import pytest

from market_alkahest.plans import (
    ALKAHEST_MECHANISM,
    decode_accepted_alkahest_obligation,
    build_penalty_bond_obligation,
    SettlementObligation,
    SettlementPlan,
    interval_amount_schedule,
    escrow_terms_from_settlement_plan,
    escrow_terms_to_settlement_obligation,
    materialize_settlement_plan_from_proposal,
    settlement_obligation_to_escrow_terms,
    split_settlement_obligation_into_intervals,
    validate_accepted_alkahest_obligation,
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

def test_terms_obligation_uses_uint256_strings_in_mechanism_params() -> None:
    amount = 150 * 10**18
    ob = escrow_terms_to_settlement_obligation(
        _terms(
            obligation_data={
                "arbiter": "0x" + "22" * 20,
                "demand": "0x" + "cd" * 32,
                "token": _TOKEN,
                "amount": amount,
            }
        )
    )

    assert ob.model_dump(mode="json")["params"]["obligation_data"]["amount"] == str(
        amount
    )
    assert settlement_obligation_to_escrow_terms(ob).obligation_data["amount"] == amount


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


def test_accepted_obligation_projection_preserves_exact_funded_terms() -> None:
    proposal = EscrowProposal(
        chain_name="base_sepolia",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": 7_200_000},
        literal_fields={"token": _TOKEN},
        rates=[],
        expiration_unix=1_800_000_000,
    )
    plan = materialize_settlement_plan_from_proposal(
        proposal=proposal,
        seller_wallet_address=_SELLER,
        agreed_amount=7_200_000,
        duration_seconds=3600,
    )
    obligation = plan.obligations[0]

    accepted = decode_accepted_alkahest_obligation(obligation)

    assert accepted.escrow_terms == settlement_obligation_to_escrow_terms(obligation)
    assert accepted.obligation_data == obligation.params["obligation_data"]
    assert accepted.amount == 7_200_000
    assert accepted.asset == _TOKEN
    assert accepted.payout_address.lower() == _SELLER.lower()
    assert accepted.verifier_proposal.model_dump(mode="json") == {
        "chain_name": "base_sepolia",
        "escrow_address": _ESCROW,
        "fields": {"token": _TOKEN},
        "literal_fields": {"token": _TOKEN},
        "rates": None,
        "demand": None,
        "demands": None,
        "expiration_unix": 1_800_000_000,
    }


@pytest.mark.parametrize("expiration_unix", [True, "1800000000", 1_800_000_000.0])
def test_accepted_obligation_projection_requires_raw_integer_expiry(
    expiration_unix,
) -> None:
    proposal = EscrowProposal(
        chain_name="base_sepolia",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": 7_200_000},
        literal_fields={"token": _TOKEN},
        rates=[],
        expiration_unix=1_800_000_000,
    )
    obligation = materialize_settlement_plan_from_proposal(
        proposal=proposal,
        seller_wallet_address=_SELLER,
        agreed_amount=7_200_000,
        duration_seconds=3600,
    ).model_dump(mode="json")["obligations"][0]
    obligation["expiration_unix"] = expiration_unix

    with pytest.raises(ValueError, match="integer expiry"):
        decode_accepted_alkahest_obligation(obligation)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("mechanism",), "fiat.stripe.v1"),
        (("amount",), "7200001"),
        (("asset",), "0x" + "ff" * 20),
        (("conditions",), [{"kind": "unverified"}]),
        (("params", "chain_name"), ""),
        (("params", "chain_name"), " base_sepolia"),
        (("params", "escrow_contract"), ""),
        (("params", "obligation_data", "amount"), "7200001"),
        (("params", "obligation_data", "token"), "0x" + "ff" * 20),
        (("params", "obligation_data", "arbiter"), None),
        (("params", "obligation_data", "demand"), "not-hex"),
        (("params", "obligation_data", "demand"), "0x00 00"),
    ],
)
def test_accepted_obligation_projection_rejects_incoherent_terms(path, value) -> None:
    proposal = EscrowProposal(
        chain_name="base_sepolia",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": 7_200_000},
        literal_fields={"token": _TOKEN},
        rates=[],
        expiration_unix=1_800_000_000,
    )
    plan = materialize_settlement_plan_from_proposal(
        proposal=proposal,
        seller_wallet_address=_SELLER,
        agreed_amount=7_200_000,
        duration_seconds=3600,
    ).model_dump(mode="json")
    target = plan["obligations"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError):
        decode_accepted_alkahest_obligation(plan["obligations"][0])


def test_accepted_obligation_validator_rederives_the_whole_mechanism_payload() -> None:
    proposal = EscrowProposal(
        chain_name="base_sepolia",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": 7_200_000},
        literal_fields={"token": _TOKEN},
        rates=[],
        expiration_unix=1_800_000_000,
    )
    plan = materialize_settlement_plan_from_proposal(
        proposal=proposal,
        seller_wallet_address=_SELLER,
        agreed_amount=7_200_000,
        duration_seconds=3600,
    )

    accepted = validate_accepted_alkahest_obligation(
        obligation=plan.obligations[0],
        proposal=proposal,
        duration_seconds=3600,
        seller_payout_address=_SELLER,
    )

    assert accepted.payout_address.lower() == _SELLER.lower()
    substituted = plan.obligations[0].model_dump(mode="json")
    substituted["params"]["obligation_data"]["demand"] = "0x" + "00" * 32
    with pytest.raises(ValueError, match="accepted Alkahest"):
        validate_accepted_alkahest_obligation(
            obligation=substituted,
            proposal=proposal,
            duration_seconds=3600,
            seller_payout_address=_SELLER,
        )


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
    assert template.params["obligation_data"]["amount"] == "11"


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
    assert bond.params["obligation_data"]["amount"] == "700000"
    assert (
        bond.params["obligation_data"]["demand"]
        == payment.params["obligation_data"]["demand"]
    )
    assert payment.amount == 5_000_000
    assert payment.params["obligation_data"]["amount"] == "5000000"
