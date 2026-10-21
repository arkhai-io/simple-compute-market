"""The escrow-shape guard and the exact-listing policy hold a proposal to its listing.

Both refuse a release condition the listing does not advertise on the
proposal's chain, including when it advertises none there: an escrow is
released only under an advertised condition, so there is nothing to skip to.
"""

from __future__ import annotations

from typing import Any

import pytest

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationRound,
)
from market_policy.scalar_policies import (
    accept_exact_listing_middleware,
    escrow_shape_guard,
    pinned_proposal,
)

_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "aa" * 20
_ARBITER = "0x" + "22" * 20
_SELLER = "0x" + "bb" * 20
_BUYER = "0x" + "77" * 20
_ZERO = "0x" + "00" * 20

_ENTRY = {
    "chain_name": "anvil",
    "escrow_address": _ESCROW,
    "literal_fields": {"token": _TOKEN},
    "rates": [],
}


def _condition(recipient: str = _SELLER, chain: str = "anvil") -> dict[str, Any]:
    return {
        "chain_name": chain,
        "arbiter": _ARBITER,
        "demand_data": {"recipient": recipient},
    }


def _listing(demands: Any = None) -> dict[str, Any]:
    listing: dict[str, Any] = {"accepted_escrows": [_ENTRY]}
    if demands is not None:
        listing["demands"] = demands
    return listing


def _proposal(**overrides: Any) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "fields": {},
        "literal_fields": {"token": _TOKEN},
        "rates": [],
        "expiration_unix": 1_900_000_000,
    }
    proposal.update(overrides)
    return proposal


def _run(policy, listing: dict[str, Any], proposal: dict[str, Any] | None):
    history = (
        [NegotiationRound(round_number=0, sender="them", action="initial", proposal=proposal)]
        if proposal is not None
        else []
    )
    context = NegotiationContext(
        direction="maximize", our_reference_amount=0, listing=listing
    )
    decision, _context = policy(history, context)
    return decision


_NO_CONDITION_ON_THE_CHAIN = [
    pytest.param(None, id="no demands"),
    pytest.param([], id="empty demands"),
    pytest.param([_condition(chain="base_sepolia")], id="another chain only"),
]


@pytest.mark.parametrize("demands", _NO_CONDITION_ON_THE_CHAIN)
@pytest.mark.parametrize(
    "selected",
    [pytest.param(None, id="none selected"), pytest.param(_condition(_BUYER), id="buyer's")],
)
def test_the_guard_refuses_a_listing_advertising_no_condition(demands, selected) -> None:
    proposal = _proposal(demand=selected) if selected is not None else _proposal()

    decision = _run(escrow_shape_guard, _listing(demands), proposal)

    assert decision is not None and decision.action == "reject"
    assert decision.reason.startswith("release_condition_not_advertised")


def test_the_guard_passes_the_advertised_condition() -> None:
    listing = _listing([_condition(), _condition(_BUYER, chain="base_sepolia")])

    assert _run(escrow_shape_guard, listing, _proposal(demand=_condition())) is None
    # The deprecated one-element list form selects the same condition.
    assert _run(escrow_shape_guard, listing, _proposal(demands=[_condition()])) is None


@pytest.mark.parametrize(
    "proposal",
    [
        pytest.param(_proposal(demand=_condition(_BUYER)), id="substituted recipient"),
        pytest.param(_proposal(), id="none selected"),
    ],
)
def test_the_guard_refuses_a_condition_the_listing_does_not_advertise(proposal) -> None:
    decision = _run(escrow_shape_guard, _listing([_condition()]), proposal)

    assert decision is not None and decision.action == "reject"
    assert decision.reason.startswith("selected_demand_not_allowed")


@pytest.mark.parametrize(
    ("listing", "proposal"),
    [
        pytest.param(_listing(), None, id="no proposal"),
        pytest.param(
            _listing(), {"settlement_selection": {"option_id": "x"}}, id="selection only"
        ),
        pytest.param(_listing(), {"fields": {"amount": "5"}}, id="fields only"),
    ],
)
def test_the_guard_passes_what_carries_no_escrow_to_compare(listing, proposal) -> None:
    """Nothing to compare; materialization still holds the release condition."""
    assert _run(escrow_shape_guard, listing, proposal) is None


@pytest.mark.parametrize(
    "listing",
    [
        pytest.param({}, id="no accepted escrows"),
        pytest.param({"accepted_escrows": []}, id="an empty list"),
        pytest.param({"accepted_escrows": "[]"}, id="empty stored JSON text"),
    ],
)
def test_the_guard_refuses_an_escrow_a_listing_accepting_none_is_offered(listing) -> None:
    """The seller prices such an escrow from no entry, so the guard stops it."""
    decision = _run(escrow_shape_guard, listing, _proposal(demand=_condition()))

    assert decision is not None and decision.action == "reject"
    assert decision.reason.startswith("escrow_not_in_accepted_set")


@pytest.mark.parametrize(
    "proposal",
    [
        pytest.param(_proposal(escrow_address=_ZERO), id="zero address"),
        pytest.param(_proposal(escrow_address=""), id="empty address"),
        pytest.param(
            {key: value for key, value in _proposal().items() if key != "escrow_address"},
            id="no address",
        ),
        pytest.param(
            _proposal(escrow_address=_ZERO, settlement_selection={"option_id": "x"}),
            id="beside a selection",
        ),
    ],
)
@pytest.mark.parametrize(
    "listing",
    [
        pytest.param(_listing([_condition()]), id="listing accepts the escrow"),
        pytest.param({}, id="listing accepts no escrow"),
    ],
)
def test_the_guard_refuses_an_escrow_naming_no_contract(listing, proposal) -> None:
    decision = _run(escrow_shape_guard, listing, proposal)

    assert decision is not None and decision.action == "reject"
    assert decision.reason.startswith("escrow_contract_unpinned")


def test_the_pinned_proposal_is_the_buyers_opening() -> None:
    """Neither a counter naming another escrow or option nor the seller's own
    rounds change the proposal an acceptance settles."""
    opening = _proposal()
    history = [
        NegotiationRound(round_number=0, sender="them", action="initial", proposal=opening),
        NegotiationRound(
            round_number=1,
            sender="us",
            action="counter",
            proposal=_proposal(escrow_address="0x" + "33" * 20, fields={"amount": "9"}),
        ),
        NegotiationRound(
            round_number=2,
            sender="them",
            action="counter",
            proposal={"settlement_selection": {"option_id": "x"}, "fields": {"amount": "1"}},
        ),
    ]

    assert pinned_proposal(history) == opening
    assert pinned_proposal(history[1:2]) is None
    assert pinned_proposal([]) is None
    # An opening carrying no proposal pins none; no later counter stands in.
    empty_opening = NegotiationRound(
        round_number=0, sender="them", action="initial", proposal=None
    )
    assert pinned_proposal([empty_opening, *history[1:]]) is None


@pytest.mark.parametrize("demands", _NO_CONDITION_ON_THE_CHAIN)
def test_the_exact_listing_policy_refuses_a_listing_advertising_no_condition(
    demands,
) -> None:
    decision = _run(accept_exact_listing_middleware, _listing(demands), _proposal())

    assert decision.action == "reject"
    assert decision.reason == "exact_listing:release_condition_not_advertised"


def test_the_exact_listing_policy_accepts_only_the_advertised_condition() -> None:
    listing = _listing([_condition()])

    accepted = _run(accept_exact_listing_middleware, listing, _proposal(demand=_condition()))
    substituted = _run(
        accept_exact_listing_middleware, listing, _proposal(demand=_condition(_BUYER))
    )

    assert accepted.action == "accept"
    assert substituted.action == "reject"
    assert substituted.reason.startswith("exact_listing:demands_mismatch")
