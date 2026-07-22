from __future__ import annotations

from copy import deepcopy

import pytest

from arkhai_bare_metal_storefront.negotiation import default_seller_round_hook
from market_policy.negotiation_middleware import NegotiationRound


def _listing(**overrides):
    offer = {
        "kind": "bare_metal.v1",
        "machine_id": "machine-trusted",
        "physical_host_id": "host-trusted",
        "access_methods": ["ssh"],
        "min_duration_seconds": 900,
        "max_duration_seconds": 7200,
    }
    offer.update(overrides.pop("offer_resource", {}))
    return {"listing_id": "listing-1", "offer_resource": offer, **overrides}


def _message(**overrides):
    message = {
        "kind": "bare_metal.v1",
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
    )

    assert result.decision.action == "accept"
    terms = result.intermediate["bare_metal_terms"]
    assert terms == {
        "kind": "bare_metal.v1",
        "machine_id": "machine-trusted",
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
        ({}, {"access_method": "ipmi", "ssh_public_key": None}, "bare_metal_access_method_not_listed"),
        (
            {"offer_resource": {"access_methods": ["ssh", "ipmi"]}},
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
    )
    second = await hook(
        listing=listing,
        message=message,
        history=history,
        seller_reference_amount=0,
    )

    assert first == second
    assert history == original
