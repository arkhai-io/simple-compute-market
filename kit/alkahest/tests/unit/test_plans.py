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
from market_alkahest.alkahest import encode_recipient_demand, get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.proposals import (
    accepted_escrow_artifacts_from_proposal,
    escrow_proposal_from_accepted_entry,
)
from market_alkahest.schemas import EscrowProposal, EscrowTerms

_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "aa" * 20
_SELLER = "0x" + "bb" * 20
_BUYER_RECIPIENT = "0x" + "77" * 20
_ANVIL_BOOK = str(anvil_address_book_path())


def _recipient_condition(recipient: str) -> dict:
    """The recipient release condition on the dev chain paying ``recipient``."""
    return {
        "chain_name": "anvil",
        "arbiter": get_recipient_arbiter("anvil", config_path=_ANVIL_BOOK),
        "demand_data": {"recipient": recipient},
    }


def _anvil_proposal(**overrides) -> EscrowProposal:
    data = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "fields": {"token": _TOKEN, "amount": 7_200_000},
        "literal_fields": {"token": _TOKEN},
        "expiration_unix": 1_800_000_000,
    }
    data.update(overrides)
    return EscrowProposal(**data)


# The listing the proposals are negotiated against: it authorizes the dev
# chain's recipient condition paying the seller.
_LISTING = {"demands": [_recipient_condition(_SELLER)]}


def _materialize(proposal: EscrowProposal, listing: dict = _LISTING) -> SettlementPlan:
    return materialize_settlement_plan_from_proposal(
        proposal=proposal,
        listing=listing,
        agreed_amount=7_200_000,
        duration_seconds=3600,
        addr_config_path=_ANVIL_BOOK,
    )


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
        mechanism="example.payment.v1",
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
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": 7_200_000},
        literal_fields={"token": _TOKEN},
        rates=[],
        demand=_recipient_condition(_SELLER),
        expiration_unix=1_800_000_000,
    )
    kwargs = dict(
        proposal=proposal,
        listing=_LISTING,
        agreed_amount=7_200_000,
        duration_seconds=3600,
        addr_config_path=_ANVIL_BOOK,
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


# A plan is materialized only under a release condition its listing
# authorizes: the condition the proposal selected, when the listing authorizes
# it, or the listing's own, never one the proposal implies some other way.


def _condition_of(plan: SettlementPlan) -> tuple[str, str]:
    (obligation,) = plan.obligations
    data = obligation.params["obligation_data"]
    return data["arbiter"], data["demand"]


_SELLER_CONDITION = (
    _recipient_condition(_SELLER)["arbiter"],
    "0x" + encode_recipient_demand(_SELLER).hex(),
)


def test_a_proposal_selecting_no_condition_takes_the_listings() -> None:
    """No recipient fallback: not the buyer's named recipient, not the wallet."""
    assert _condition_of(
        _materialize(
            _anvil_proposal(
                literal_fields={"token": _TOKEN, "recipient": _BUYER_RECIPIENT}
            )
        )
    ) == _SELLER_CONDITION
    assert _condition_of(_materialize(_anvil_proposal())) == _SELLER_CONDITION


def test_a_condition_stated_in_escrow_fields_is_not_materialized() -> None:
    buyer_condition = {
        "arbiter": "0x" + "55" * 20,
        "demand": "0x" + encode_recipient_demand(_BUYER_RECIPIENT).hex(),
    }
    assert _condition_of(
        _materialize(
            _anvil_proposal(literal_fields={"token": _TOKEN, **buyer_condition})
        )
    ) == _SELLER_CONDITION


def test_the_selected_condition_is_the_one_materialized() -> None:
    plan = _materialize(
        _anvil_proposal(
            literal_fields={"token": _TOKEN, "arbiter": "0x" + "55" * 20},
            demand=_recipient_condition(_SELLER),
        )
    )
    (obligation,) = plan.obligations
    data = obligation.params["obligation_data"]
    assert data["arbiter"] == _recipient_condition(_SELLER)["arbiter"]
    assert data["demand"] == "0x" + encode_recipient_demand(_SELLER).hex()


def test_a_condition_paying_no_recipient_is_not_materialized() -> None:
    """A listing derived for an empty seller wallet advertises a recipient
    condition with no recipient; no escrow can be settled under it."""
    empty = _recipient_condition("")
    with pytest.raises(ValueError, match="release_condition_unreadable"):
        _materialize(_anvil_proposal(demand=empty), listing={"demands": [empty]})
    with pytest.raises(ValueError, match="release_condition_unreadable"):
        _materialize(_anvil_proposal(), listing={"demands": [empty]})


def test_a_listing_authorizing_no_condition_builds_no_proposal() -> None:
    entry = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN},
    }
    for listing in (
        {"accepted_escrows": [entry]},
        {"accepted_escrows": [entry], "demands": []},
        {"accepted_escrows": [entry], "demands": [
            {**_recipient_condition(_SELLER), "chain_name": "base_sepolia"},
        ]},
    ):
        with pytest.raises(ValueError, match="release condition"):
            escrow_proposal_from_accepted_entry(
                listing=listing, entry=entry, expiration_unix=1_800_000_000
            )


def test_an_unmaterializable_condition_refuses_the_artifacts() -> None:
    """A refusal is raised to the seller, never recorded beside empty artifacts."""
    with pytest.raises(ValueError, match="release condition"):
        accepted_escrow_artifacts_from_proposal(
            proposal=_anvil_proposal(),
            listing={"demands": []},
            agreed_amount=7_200_000,
            duration_seconds=3600,
            chain_config_paths={"anvil": _ANVIL_BOOK},
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
