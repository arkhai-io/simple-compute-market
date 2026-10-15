"""A proposal settles under exactly the release condition its listing authorizes."""

from __future__ import annotations

import json

import pytest

from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.proposals import (
    ReleaseConditionError,
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
