"""A uint256 amount survives scaling, the policy chain, and canonical JSON.

The three layers were each correct in isolation and disagreed at the seams:
the CLI scaled a display price into base units through a float, the policy
wrote the result as a JSON number, and canonicalization — correctly — refused
to emit a number it could not round-trip. The failure surfaced as
``CanonicalizationError: body is not canonicalizable JSON`` at the moment of
signing, with the escrow amount already agreed.

These tests bind the seam rather than each layer: an 18-decimal price goes in
as a human types it, and the body that comes out is signable and carries the
exact integer both parties will settle on.
"""

from __future__ import annotations

import pytest
from market_identity import canonical_body_hash, canonical_json
from market_policy.negotiation_middleware import NegotiationContext
from market_policy.scalar_policies import bisection_middleware

from core_buyer.negotiation_client import display_to_base_units, scaled_base_units

#: 18 decimals, the ordinary case the wire contract exists for. 7000 whole
#: units is 7e21 base units — past 2^53-1, so it has no JSON number form.
_DECIMALS = 18
_SAFE_INTEGER_MAX = 2**53 - 1


def _round_zero_body(*, initial_price: float, max_price: float, hours: float) -> dict:
    """The buyer's round-0 body, built the way the negotiation client builds it."""
    opening = scaled_base_units(
        display_to_base_units(initial_price, _DECIMALS, field="--initial-price"),
        hours,
        field="initial_price",
    )
    ceiling = scaled_base_units(
        display_to_base_units(max_price, _DECIMALS, field="--max-price"),
        hours,
        field="max_price",
    )
    decision, _ = bisection_middleware(
        [],
        NegotiationContext(
            direction="minimize",
            our_reference_amount=ceiling,
            our_opening_amount=opening,
            our_escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {"amount": "0", "token": "0x" + "22" * 20},
                "expiration_unix": 1_900_000_000,
            },
        ),
    )
    return {
        "listing_id": "listing-1",
        "buyer_principal": {"scheme": "eip191", "identifier": "0x" + "33" * 20},
        "proposal": decision.proposal,
    }


class TestAnEighteenDecimalDealCanBeSigned:
    def test_the_round_zero_body_canonicalizes(self):
        body = _round_zero_body(initial_price=7000, max_price=12000, hours=1)

        # The assertion that was failing in the stack: signing hashes the
        # canonical form, and this body had no canonical form at all.
        assert canonical_json(body)
        assert len(canonical_body_hash(body)) == 64

    def test_the_amount_is_exact_and_past_the_safe_integer_range(self):
        body = _round_zero_body(initial_price=7000, max_price=12000, hours=1)

        amount = body["proposal"]["fields"]["amount"]

        assert isinstance(amount, str), "a JSON number here is unsignable"
        assert int(amount) == 7000 * 10**_DECIMALS
        assert int(amount) > _SAFE_INTEGER_MAX

    def test_a_fractional_lease_scales_without_rounding(self):
        body = _round_zero_body(initial_price=1, max_price=2, hours=1.5)

        assert int(body["proposal"]["fields"]["amount"]) == 15 * 10**17


class TestScalingRefusesWhatItCannotRepresent:
    def test_a_price_finer_than_the_base_unit_is_refused(self):
        """Two decimals of a zero-decimal asset is not a payable amount."""
        with pytest.raises(ValueError, match="finer than"):
            display_to_base_units(1.25, 0, field="--initial-price")

    def test_a_whole_price_at_zero_decimals_passes_through(self):
        assert display_to_base_units(10_000, 0, field="--initial-price") == 10_000

    def test_eighteen_decimals_keeps_every_digit(self):
        """`7000 * 10**18` via float is the value that started this."""
        assert display_to_base_units(7000, 18, field="--initial-price") == (
            7000 * 10**18
        )

    def test_a_lease_that_does_not_divide_into_base_units_is_refused(self):
        with pytest.raises(RuntimeError, match="whole number of base units"):
            scaled_base_units(1, 0.5, field="initial_price")

    def test_a_negative_price_is_refused(self):
        with pytest.raises(ValueError, match="non-negative"):
            display_to_base_units(-1, 18, field="--initial-price")
