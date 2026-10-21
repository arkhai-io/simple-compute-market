"""A proposal settles under exactly the release condition its listing authorizes."""

from __future__ import annotations

import inspect
import json

import pytest

from market_alkahest.alkahest import (
    encode_recipient_demand,
    get_erc20_escrow_obligation_default,
    get_recipient_arbiter,
    materialize_escrow_terms_from_proposal,
    materialize_escrow_terms_payload_from_proposal,
)
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.escrow_verification import (
    EscrowVerificationError,
    verify_escrow_for_settlement,
)
from market_alkahest.plans import (
    materialize_settlement_plan_from_proposal,
    settlement_plan_payload_from_proposal,
)
from market_alkahest.proposals import (
    ReleaseConditionError,
    accepted_escrow_artifacts_from_proposal,
    authorize_escrow_proposal,
    authorized_release_conditions,
    escrow_proposal_from_accepted_entry,
)
from market_alkahest.schemas import EscrowProposal

_BOOK = str(anvil_address_book_path())
_ARBITER = get_recipient_arbiter("anvil", config_path=_BOOK)
_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "aa" * 20
_SELLER = "0x" + "bb" * 20
_BUYER = "0x" + "77" * 20
_ZERO = "0x" + "00" * 20


def _condition(recipient: str = _SELLER, **overrides) -> dict:
    return {
        "chain_name": "anvil",
        "arbiter": _ARBITER,
        "demand_data": {"recipient": recipient},
        **overrides,
    }


_LISTING = {"demands": [_condition()]}


def _proposal(**overrides) -> EscrowProposal:
    data = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "fields": {"token": _TOKEN, "amount": 100},
        "literal_fields": {"token": _TOKEN},
        "expiration_unix": 1_800_000_000,
    }
    data.update(overrides)
    return EscrowProposal.model_validate(data)


def test_a_proposal_selecting_no_condition_takes_the_listings() -> None:
    authorized = authorize_escrow_proposal(_proposal(), listing=_LISTING)

    assert authorized.demand is not None
    assert authorized.demand.model_dump(exclude_none=True) == _condition()
    # Nothing else about the proposal changes.
    assert authorized.fields == _proposal().fields
    assert authorized.escrow_address == _ESCROW


def test_an_authorized_selection_is_kept_in_the_listings_form() -> None:
    shouted = _condition(
        _SELLER.upper().replace("0X", "0x"), arbiter=_ARBITER.upper().replace("0X", "0x")
    )
    authorized = authorize_escrow_proposal(
        _proposal(demand=shouted), listing=_LISTING
    )

    assert authorized.demand.model_dump(exclude_none=True) == _condition()


@pytest.mark.parametrize(
    "selected",
    [
        _condition(_BUYER),
        _condition(arbiter="0x" + "55" * 20),
        _condition(demand_data={"recipient": _SELLER, "extra": 1}),
    ],
    ids=["substituted recipient", "another arbiter", "other demand data"],
)
def test_a_selection_the_listing_does_not_authorize_is_refused(selected) -> None:
    with pytest.raises(ReleaseConditionError, match="release_condition_not_authorized"):
        authorize_escrow_proposal(_proposal(demand=selected), listing=_LISTING)


def test_an_unpinned_escrow_is_held_to_the_listing_all_the_same() -> None:
    with pytest.raises(ReleaseConditionError, match="release_condition_not_authorized"):
        authorize_escrow_proposal(
            _proposal(escrow_address=_ZERO, demand=_condition(_BUYER)), listing=_LISTING
        )
    assert authorize_escrow_proposal(
        _proposal(escrow_address=_ZERO), listing=_LISTING
    ).demand.model_dump(exclude_none=True) == _condition()


@pytest.mark.parametrize(
    "listing",
    [
        {},
        {"demands": None},
        {"demands": []},
        {"demands": [_condition(chain_name="base_sepolia")]},
    ],
    ids=["no demands", "null demands", "empty demands", "another chain only"],
)
def test_a_listing_authorizing_no_condition_on_the_chain_refuses(listing) -> None:
    with pytest.raises(ReleaseConditionError, match="release_condition_not_advertised"):
        authorize_escrow_proposal(_proposal(), listing=listing)
    with pytest.raises(ReleaseConditionError, match="release_condition_not_advertised"):
        authorize_escrow_proposal(_proposal(demand=_condition(_BUYER)), listing=listing)


@pytest.mark.parametrize(
    "demands",
    [
        "not json",
        '{"arbiter": "0x"}',
        {"arbiter": _ARBITER},
        ["a condition"],
        [{"chain_name": "anvil", "demand_data": {}}],
        [{"chain_name": "anvil", "arbiter": _ARBITER, "demand_data": "recipient"}],
        [{"chain_name": 1, "arbiter": _ARBITER, "demand_data": {}}],
    ],
    ids=[
        "unparseable",
        "json object",
        "mapping",
        "non-object entry",
        "no arbiter",
        "demand data not an object",
        "chain not a string",
    ],
)
def test_a_listing_whose_conditions_cannot_be_read_refuses(demands) -> None:
    with pytest.raises(ReleaseConditionError, match="release_condition_unreadable"):
        authorize_escrow_proposal(_proposal(), listing={"demands": demands})


def test_conditions_stored_as_json_and_unscoped_ones_are_read() -> None:
    unscoped = {"arbiter": _ARBITER, "demand_data": {"recipient": _SELLER}}
    stored = {"demands": json.dumps([_condition(chain_name="base_sepolia"), unscoped])}

    (condition,) = authorized_release_conditions(stored, chain_name="anvil")

    assert condition.model_dump(exclude_none=True) == unscoped


def test_a_proposal_selecting_two_conditions_is_refused() -> None:
    proposal = {**_proposal().model_dump(mode="json"), "demand": None}
    proposal["demands"] = [_condition()]
    assert authorize_escrow_proposal(proposal, listing=_LISTING).demand is not None
    # The deprecated list form may select one condition, never several.
    proposal["demands"] = [_condition(), _condition()]
    with pytest.raises(ValueError):
        authorize_escrow_proposal(proposal, listing=_LISTING)


def test_a_listing_entry_builds_its_proposal_under_the_authorized_condition() -> None:
    entry = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN},
    }

    built = escrow_proposal_from_accepted_entry(
        listing=_LISTING, entry=entry, expiration_unix=1_800_000_000
    )
    selected = escrow_proposal_from_accepted_entry(
        listing=_LISTING,
        entry=entry,
        expiration_unix=1_800_000_000,
        demand=_condition(),
    )

    assert built.demand.model_dump(exclude_none=True) == _condition()
    assert selected.demand == built.demand
    with pytest.raises(ReleaseConditionError, match="release_condition_not_authorized"):
        escrow_proposal_from_accepted_entry(
            listing=_LISTING,
            entry=entry,
            expiration_unix=1_800_000_000,
            demand=_condition(_BUYER),
        )


# Materialization authorizes the condition itself. A caller that skips
# ``authorize_escrow_proposal`` and materializes a buyer's proposal directly is
# refused all the same, so no acceptance path can forget the check.


def _materialize_terms(proposal, listing):
    return materialize_escrow_terms_from_proposal(
        proposal=proposal, listing=listing, agreed_amount=100,
        duration_seconds=3600, addr_config_path=_BOOK,
    )


def _materialize_terms_payload(proposal, listing):
    return materialize_escrow_terms_payload_from_proposal(
        proposal=proposal, listing=listing, agreed_amount=100,
        duration_seconds=3600, addr_config_path=_BOOK,
    )


def _materialize_plan(proposal, listing):
    return materialize_settlement_plan_from_proposal(
        proposal=proposal, listing=listing, agreed_amount=100,
        duration_seconds=3600, addr_config_path=_BOOK,
    )


def _materialize_plan_payload(proposal, listing):
    return settlement_plan_payload_from_proposal(
        proposal=proposal, listing=listing, agreed_amount=100,
        duration_seconds=3600, addr_config_path=_BOOK,
    )


def _accepted_artifacts(proposal, listing):
    return accepted_escrow_artifacts_from_proposal(
        proposal=proposal, listing=listing, agreed_amount=100,
        duration_seconds=3600, chain_config_paths={"anvil": _BOOK},
    )


_MATERIALIZERS = pytest.mark.parametrize(
    "materialize",
    [
        _materialize_terms,
        _materialize_terms_payload,
        _materialize_plan,
        _materialize_plan_payload,
        _accepted_artifacts,
    ],
    ids=[
        "escrow terms",
        "escrow terms payload",
        "settlement plan",
        "settlement plan payload",
        "accepted artifacts",
    ],
)


@_MATERIALIZERS
@pytest.mark.parametrize(
    ("selected", "listing", "reason"),
    [
        (_condition(_BUYER), _LISTING, "release_condition_not_authorized"),
        (
            _condition(arbiter="0x" + "55" * 20),
            _LISTING,
            "release_condition_not_authorized",
        ),
        (_condition(), {"demands": []}, "release_condition_not_advertised"),
        (None, {}, "release_condition_not_advertised"),
        (
            _condition(),
            {"demands": [_condition(chain_name="base_sepolia")]},
            "release_condition_not_advertised",
        ),
        (None, {"demands": "not json"}, "release_condition_unreadable"),
    ],
    ids=[
        "substituted recipient",
        "another arbiter",
        "listing authorizes none",
        "listing states no demands",
        "another chain only",
        "unreadable demands",
    ],
)
def test_materialization_called_directly_refuses_an_unauthorized_condition(
    materialize, selected, listing, reason
) -> None:
    proposal = _proposal(demand=selected) if selected is not None else _proposal()
    with pytest.raises(ReleaseConditionError, match=reason):
        materialize(proposal, listing)


@_MATERIALIZERS
def test_materialization_called_directly_encodes_the_listings_condition(
    materialize,
) -> None:
    expected = {
        "arbiter": _ARBITER,
        "demand": "0x" + encode_recipient_demand(_SELLER).hex(),
    }
    shouted = _condition(_SELLER.upper().replace("0X", "0x"))
    for proposal in (_proposal(), _proposal(demand=shouted)):
        out = materialize(proposal, _LISTING)
        if isinstance(out, dict) and "settlement_plan" in out:
            assert out["accepted_escrow_proposal"]["demand"] == _condition()
            out = out["settlement_plan"]
        if isinstance(out, list):
            (term,) = out
            data = term["obligation_data"] if isinstance(term, dict) else term.obligation_data
        else:
            plan = out if isinstance(out, dict) else out.model_dump(mode="json")
            (obligation,) = plan["obligations"]
            data = obligation["params"]["obligation_data"]
        assert {key: data[key] for key in expected} == expected


@pytest.mark.parametrize(
    "materialize",
    [
        materialize_escrow_terms_from_proposal,
        materialize_escrow_terms_payload_from_proposal,
        materialize_settlement_plan_from_proposal,
        settlement_plan_payload_from_proposal,
        accepted_escrow_artifacts_from_proposal,
    ],
)
def test_no_materializer_can_be_called_without_its_listing(materialize) -> None:
    listing = inspect.signature(materialize).parameters["listing"]
    assert listing.default is inspect.Parameter.empty


async def test_settlement_verification_refuses_a_condition_its_listing_does_not_authorize(
) -> None:
    async def _never_read(_client, _uid):
        raise AssertionError("the chain is read only for an authorized condition")

    escrow = get_erc20_escrow_obligation_default("anvil", config_path=_BOOK)
    for proposal, listing in (
        (_proposal(escrow_address=escrow, demand=_condition(_BUYER)), _LISTING),
        (_proposal(escrow_address=escrow), {"demands": []}),
    ):
        with pytest.raises(EscrowVerificationError, match="release_condition_"):
            await verify_escrow_for_settlement(
                escrow_uid="0x" + "ab" * 32,
                seller_wallet=_SELLER,
                agreed_price=100,
                agreed_duration_seconds=3600,
                listing=listing,
                alkahest_client=object(),
                chain_name="anvil",
                alkahest_address_config_path=_BOOK,
                escrow_proposal=proposal,
                get_obligation_fn=_never_read,
            )
