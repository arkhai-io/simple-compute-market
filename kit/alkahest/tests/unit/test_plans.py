"""alkahest.v1 settlement-plan codec: converters + materialization parity."""

from __future__ import annotations

import json

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
    require_escrow_terms_fund_plan,
    settlement_obligation_to_escrow_terms,
    split_settlement_obligation_into_intervals,
)
from market_alkahest.alkahest import (
    encode_recipient_demand,
    get_recipient_arbiter,
    materialize_escrow_terms_from_proposal,
)
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.proposals import (
    ReleaseConditionError,
    ReleaseConditionsUnrecordedError,
    SettlementPlanMaterializationError,
    accepted_escrow_artifacts_from_proposal,
    authorized_escrow_proposal_at_amount,
    derive_accepted_escrow_terms,
    escrow_proposal_from_accepted_entry,
)
from market_alkahest.release_authorization import (
    advertised_release_conditions,
    recorded_release_conditions,
    release_conditions_record,
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


# The listing the proposals are negotiated against: it accepts their escrow
# and authorizes the dev chain's recipient condition paying the seller.
_LISTING = {
    "accepted_escrows": [
        {"chain_name": "anvil", "escrow_address": _ESCROW, "literal_fields": {"token": _TOKEN}}
    ],
    "demands": [_recipient_condition(_SELLER)],
}


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


def test_plan_view_refuses_a_bare_terms_list() -> None:
    """A plan is read only in its own shape, never from flat terms."""
    with pytest.raises(ValueError):
        escrow_terms_from_settlement_plan([_terms().model_dump()])


def test_an_obligation_is_read_only_in_its_own_shape_never_from_flat_terms() -> None:
    with pytest.raises(ValueError):
        SettlementObligation.model_validate(_terms().model_dump(mode="json"))


def test_plan_materialization_matches_terms_materialization() -> None:
    """Both sides may derive either artifact; they must agree byte-for-byte."""
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
    # The listing authorizes the condition, so the refusal comes from
    # materializing it, not from authorization.
    with pytest.raises(ValueError, match="release_condition_unreadable"):
        accepted_escrow_artifacts_from_proposal(
            proposal=_anvil_proposal(),
            listing={**_LISTING, "demands": [_recipient_condition("")]},
            agreed_amount=7_200_000,
            duration_seconds=3600,
            chain_config_paths={"anvil": _ANVIL_BOOK},
        )


# A rate the codecs cannot price: the plan fails after its release condition
# is authorized and encoded, so the failure is the plan's, not the condition's.
_UNPRICEABLE_RATE = {"field": "bonus", "per": "fortnight", "value": "1"}


def test_a_plan_that_cannot_be_materialized_refuses_the_artifacts() -> None:
    """No artifacts are returned without their plan: the acceptance is refused."""
    with pytest.raises(SettlementPlanMaterializationError) as refused:
        accepted_escrow_artifacts_from_proposal(
            proposal=_anvil_proposal(rates=[_UNPRICEABLE_RATE]),
            listing=_LISTING,
            agreed_amount=7_200_000,
            duration_seconds=3600,
            chain_config_paths={"anvil": _ANVIL_BOOK},
        )

    assert str(refused.value).startswith("settlement_plan_unmaterializable: ")
    assert "fortnight" in str(refused.value)
    assert refused.value.__cause__ is not None
    assert not isinstance(refused.value, ReleaseConditionError)


def test_accepted_artifacts_always_carry_their_plan() -> None:
    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=_anvil_proposal(),
        listing=_LISTING,
        agreed_amount=7_200_000,
        duration_seconds=3600,
        chain_config_paths={"anvil": _ANVIL_BOOK},
    )

    (obligation,) = artifacts["settlement_plan"]["obligations"]
    assert int(obligation["params"]["obligation_data"]["amount"]) == 7_200_000
    # The plan is the seller's committed copy; no escrow terms travel beside it.
    assert set(artifacts) == {"proposal", "accepted_escrow_proposal", "settlement_plan"}


def _accepted() -> EscrowProposal:
    return EscrowProposal.model_validate(
        accepted_escrow_artifacts_from_proposal(
            proposal=_anvil_proposal(),
            listing=_LISTING,
            agreed_amount=7_200_000,
            duration_seconds=3600,
            chain_config_paths={"anvil": _ANVIL_BOOK},
        )["accepted_escrow_proposal"]
    )


def _derived(amount: int = 7_200_000) -> list[EscrowTerms]:
    return materialize_escrow_terms_from_proposal(
        proposal=_accepted(),
        listing=_LISTING,
        agreed_amount=amount,
        duration_seconds=3600,
        addr_config_path=_ANVIL_BOOK,
    )


def _plan_paying_another_recipient() -> SettlementPlan:
    """A seller's plan released to a recipient the listing does not advertise."""
    other = _recipient_condition(_BUYER_RECIPIENT)
    return _materialize(_anvil_proposal(demand=other), listing={"demands": [other]})


def test_the_buyers_derivation_funds_the_sellers_plan() -> None:
    require_escrow_terms_fund_plan(_derived(), _materialize(_accepted()))


@pytest.mark.parametrize(
    ("derived", "plan", "field"),
    [
        pytest.param(_derived, _plan_paying_another_recipient, "demand", id="another recipient"),
        pytest.param(
            lambda: _derived(amount=1), lambda: _materialize(_accepted()), "amount",
            id="another amount",
        ),
        pytest.param(lambda: [], lambda: _materialize(_accepted()), "escrow(s)", id="no escrow"),
    ],
)
def test_a_plan_the_buyer_did_not_derive_is_refused(derived, plan, field) -> None:
    with pytest.raises(ValueError, match="seller_plan_mismatch") as refused:
        require_escrow_terms_fund_plan(derived(), plan())
    assert field in str(refused.value)


def test_a_plan_is_compared_case_insensitively_only_in_its_hex() -> None:
    data = _terms().obligation_data
    plan = SettlementPlan(obligations=[escrow_terms_to_settlement_obligation(
        _terms(obligation_data={**data, "token": _TOKEN.upper().replace("0X", "0x"), "label": "Seller"})
    )])

    require_escrow_terms_fund_plan([_terms(obligation_data={**data, "label": "Seller"})], plan)
    with pytest.raises(ValueError, match="seller_plan_mismatch"):
        require_escrow_terms_fund_plan([_terms(obligation_data={**data, "label": "seller"})], plan)


def test_a_resumed_run_derives_from_its_recorded_conditions() -> None:
    plan = _materialize(_accepted())

    terms = derive_accepted_escrow_terms(
        accepted_proposal=_accepted().model_dump(mode="json"),
        listing_record=release_conditions_record(_LISTING),
        agreed_amount=7_200_000,
        duration_seconds=3600,
        settlement_plan=plan.model_dump(mode="json"),
        addr_config_path=_ANVIL_BOOK,
    )

    assert terms == escrow_terms_from_settlement_plan(plan)


def test_a_resumed_run_refuses_a_plan_its_conditions_do_not_derive() -> None:
    """The seller's recorded plan pays another recipient than the advertised one."""
    with pytest.raises(ValueError, match="seller_plan_mismatch"):
        derive_accepted_escrow_terms(
            accepted_proposal=_accepted(),
            listing_record=release_conditions_record(_LISTING),
            agreed_amount=7_200_000,
            duration_seconds=3600,
            settlement_plan=_plan_paying_another_recipient(),
            addr_config_path=_ANVIL_BOOK,
        )


def test_a_resumed_run_that_recorded_no_seller_plan_is_refused() -> None:
    """A seller accepts an escrow only with its plan, so a run recording none
    is refused rather than funded without the skew check."""
    with pytest.raises(ValueError, match="^seller_plan_missing"):
        derive_accepted_escrow_terms(
            accepted_proposal=_accepted(),
            listing_record=release_conditions_record(_LISTING),
            agreed_amount=7_200_000,
            duration_seconds=3600,
            settlement_plan=None,
            addr_config_path=_ANVIL_BOOK,
        )


@pytest.mark.parametrize(
    "record", [None, {}], ids=["no record", "a record without conditions"]
)
def test_a_run_accepted_before_conditions_were_recorded_is_refused(record) -> None:
    with pytest.raises(ReleaseConditionsUnrecordedError, match="release_conditions_unrecorded"):
        derive_accepted_escrow_terms(
            accepted_proposal=_accepted(),
            listing_record=record,
            agreed_amount=7_200_000,
            duration_seconds=3600,
            settlement_plan=_materialize(_accepted()),
            addr_config_path=_ANVIL_BOOK,
        )


def test_a_listing_record_reads_back_the_conditions_it_recorded() -> None:
    record = release_conditions_record(_LISTING)

    assert recorded_release_conditions(record) == [_recipient_condition(_SELLER)]
    assert recorded_release_conditions(None) is None
    assert recorded_release_conditions({}) is None


@pytest.mark.parametrize(
    "record",
    [["not", "an", "object"], {"release_conditions": "not a list"}],
    ids=["a record that is not an object", "conditions that are not a list"],
)
def test_an_unreadable_listing_record_is_refused(record) -> None:
    with pytest.raises(ValueError, match="release_conditions_unreadable"):
        recorded_release_conditions(record)


@pytest.mark.parametrize(
    ("demands", "recorded"),
    [
        pytest.param([_recipient_condition(_SELLER)], [_recipient_condition(_SELLER)], id="a list"),
        pytest.param(
            json.dumps([_recipient_condition(_SELLER)]),
            [_recipient_condition(_SELLER)],
            id="stored JSON text",
        ),
        pytest.param(None, [], id="absent"),
        pytest.param("not json", [], id="unreadable"),
    ],
)
def test_a_listing_records_the_conditions_it_advertises(demands, recorded) -> None:
    assert advertised_release_conditions({"demands": demands}) == recorded


def test_the_proposal_at_an_amount_is_authorized_without_building_a_plan() -> None:
    """A round that does not accept offers the proposal back without its plan,
    so a plan that could not yet be materialized does not refuse it; the
    release condition is authorized all the same."""
    offered = authorized_escrow_proposal_at_amount(
        proposal=_anvil_proposal(rates=[_UNPRICEABLE_RATE]),
        listing=_LISTING,
        agreed_amount=5_000_000,
    )

    assert offered["fields"]["amount"] == "5000000"
    assert offered["demand"] == _recipient_condition(_SELLER)
    assert "demands" not in offered
    unscaled = authorized_escrow_proposal_at_amount(
        proposal=_anvil_proposal(),
        listing=_LISTING,
        agreed_amount=5_000_000,
        uses_scalar_amount=False,
    )
    assert unscaled["fields"]["amount"] == 7_200_000
    with pytest.raises(ReleaseConditionError, match="release_condition_not_authorized"):
        authorized_escrow_proposal_at_amount(
            proposal=_anvil_proposal(demand=_recipient_condition(_BUYER_RECIPIENT)),
            listing=_LISTING,
            agreed_amount=5_000_000,
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
