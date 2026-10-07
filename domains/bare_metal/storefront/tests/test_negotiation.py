from __future__ import annotations

from copy import deepcopy

import pytest

from arkhai_bare_metal_storefront.negotiation import (
    DEFAULT_SELLER_POLICIES,
    default_seller_round_hook,
    seller_policy_names,
)
from market_policy.listing_source import ListingSourceVerdict
from market_policy.negotiation_middleware import NegotiationRound
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE


#: The verdict the negotiation runtime supplies for a listing its source supports.
MATCHES = ListingSourceVerdict("matches")


def _listing(**overrides):
    listing_resource = {
        "capacity_backing": "backed",
        **LISTING_HARDWARE,
        "kind": "bare_metal.v2",
        "host_id": "machine-trusted",
        "physical_host_id": "host-trusted",
        "access_methods": ["ssh"],
        "min_duration_seconds": 900,
        "max_duration_seconds": 7200,
    }
    listing_resource.update(overrides.pop("listing_resource", {}))
    return {"listing_id": "listing-1", "listing_resource": listing_resource, **overrides}


def _message(**overrides):
    message = {
        "kind": "bare_metal.v2",
        "duration_seconds": 3600,
        "access_method": "ssh",
        "ssh_public_key": "ssh-ed25519 buyer-key",
    }
    message.update(overrides)
    return message


def _history(proposal=None):
    return [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=proposal if proposal is not None else {"kind": "exact"},
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [900, 7200])
async def test_policy_accepts_ssh_request_at_duration_boundaries(duration) -> None:
    result = await default_seller_round_hook()(
        listing=_listing(),
        message=_message(duration_seconds=duration),
        history=_history(),
        seller_reference_amount=0,
        listing_ref="trusted-listing",
        listing_source=MATCHES,
    )

    assert result.decision.action == "accept"
    terms = result.intermediate["bare_metal_terms"]
    assert terms == {
        "kind": "bare_metal.v2",
        "host_id": "machine-trusted",
        "physical_host_id": "host-trusted",
        "duration_seconds": duration,
        "access_method": "ssh",
        "ssh_public_key": "ssh-ed25519 buyer-key",
        "listing_ref": "trusted-listing",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("listing_overrides", "message_overrides", "reason"),
    [
        ({}, {"duration_seconds": 899}, "bare_metal_duration_below_listing_min"),
        ({}, {"duration_seconds": 7201}, "bare_metal_duration_above_listing_max"),
        (
            {},
            {"access_method": "ipmi", "ssh_public_key": None},
            "bare_metal_access_method_not_listed",
        ),
        (
            {"listing_resource": {"access_methods": ["ssh", "ipmi"]}},
            {"access_method": "ipmi", "ssh_public_key": None},
            "bare_metal_access_method_unsupported",
        ),
        (
            {},
            {"ssh_public_key": None, "access_ref": {"credential": "buyer"}},
            "bare_metal_buyer_access_ref_forbidden",
        ),
        (
            {},
            {"ssh_public_key": "   ", "access_ref": None},
            "bare_metal_ssh_public_key_required",
        ),
    ],
)
async def test_policy_rejects_invalid_physical_request(
    listing_overrides,
    message_overrides,
    reason,
) -> None:
    result = await default_seller_round_hook()(
        listing=_listing(**listing_overrides),
        message=_message(**message_overrides),
        history=_history(),
        seller_reference_amount=100,
        listing_source=MATCHES,
    )

    assert result.decision.action == "reject"
    assert result.decision.reason == reason
    assert "bare_metal_terms" not in result.intermediate


@pytest.mark.asyncio
async def test_policy_applies_shared_listed_price_after_domain_guards() -> None:
    accepted = {
        "chain_name": "base",
        "escrow_address": "0x1111111111111111111111111111111111111111",
        "literal_fields": {"token": "0x2222222222222222222222222222222222222222"},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }
    proposal = {
        "chain_name": accepted["chain_name"],
        "escrow_address": accepted["escrow_address"],
        "literal_fields": dict(accepted["literal_fields"]),
        "fields": {"amount": "100"},
    }

    result = await default_seller_round_hook()(
        listing=_listing(accepted_escrows=[accepted]),
        message=_message(),
        history=_history(proposal),
        seller_reference_amount=100,
        listing_source=MATCHES,
    )

    assert result.decision.action == "accept"
    assert result.decision.reason == "listed_price"
    assert result.our_amount == 100
    assert result.intermediate["uses_scalar_amount"] is True


@pytest.mark.asyncio
async def test_policy_is_deterministic_and_does_not_mutate_history() -> None:
    listing = _listing()
    message = _message()
    history = _history()
    original = deepcopy(history)
    hook = default_seller_round_hook()

    first = await hook(
        listing=listing,
        message=message,
        history=history,
        seller_reference_amount=0,
        listing_source=MATCHES,
    )
    second = await hook(
        listing=listing,
        message=message,
        history=history,
        seller_reference_amount=0,
        listing_source=MATCHES,
    )

    assert first == second
    assert history == original


_ACCEPTED = {
    "chain_name": "base",
    "escrow_address": "0x1111111111111111111111111111111111111111",
    "literal_fields": {"token": "0x2222222222222222222222222222222222222222"},
    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
}


def _escrow(amount: str) -> dict:
    return {
        "chain_name": _ACCEPTED["chain_name"],
        "escrow_address": _ACCEPTED["escrow_address"],
        "literal_fields": dict(_ACCEPTED["literal_fields"]),
        "fields": {"amount": amount},
    }


def test_every_chain_begins_with_the_inventory_guard() -> None:
    assert seller_policy_names() == [
        "has_matching_inventory_guard",
        *DEFAULT_SELLER_POLICIES,
    ]
    assert seller_policy_names(["escrow_shape_guard", "bisection"]) == [
        "has_matching_inventory_guard",
        "escrow_shape_guard",
        "bisection",
    ]
    assert seller_policy_names(
        ["has_matching_inventory_guard", "listed_price"]
    ) == ["has_matching_inventory_guard", "listed_price"]


def test_an_unknown_policy_is_refused_when_the_chain_is_composed() -> None:
    with pytest.raises(KeyError):
        default_seller_round_hook(["no_such_policy"])


@pytest.mark.asyncio
async def test_a_round_without_a_source_verdict_is_rejected() -> None:
    result = await default_seller_round_hook()(
        listing=_listing(accepted_escrows=[_ACCEPTED]),
        message=_message(),
        history=_history(_escrow("100")),
        seller_reference_amount=100,
    )

    assert (result.decision.action, result.decision.reason) == (
        "reject",
        "no_matching_declaration",
    )


@pytest.mark.asyncio
async def test_the_default_chain_exits_below_the_listed_rate() -> None:
    result = await default_seller_round_hook()(
        listing=_listing(accepted_escrows=[_ACCEPTED]),
        message=_message(),
        history=_history(_escrow("80")),
        seller_reference_amount=100,
        listing_source=MATCHES,
    )

    assert result.decision.action == "exit"


@pytest.mark.asyncio
async def test_a_bisection_chain_counters_below_the_listed_rate() -> None:
    result = await default_seller_round_hook(["escrow_shape_guard", "bisection"])(
        listing=_listing(accepted_escrows=[_ACCEPTED]),
        message=_message(),
        history=_history(_escrow("80")),
        seller_reference_amount=100,
        listing_source=MATCHES,
    )

    assert result.decision.action == "counter"
    assert result.chain_label == "has_matching_inventory_guard,escrow_shape_guard,bisection"
