"""Settlement — seller perspective.

User-visible property: 'after settlement, the buyer's tokens are safely
locked in escrow; I can proceed to provision knowing I'll be paid once
I deliver and arbitration completes.'

What the seller observes after settlement completes:
  - Their local order records the escrow_uid (pointing at the buyer's
    on-chain deposit).
  - Their order's status is accepted/matched (depending on flow).
  - Their own token balance is unchanged (they haven't collected yet).
"""

from __future__ import annotations

import logging

import pytest

from tests.roles.helpers.deal import Deal

log = logging.getLogger(__name__)


@pytest.mark.roles_settlement_seller
class TestSellerObservesEscrow:
    """The seller knows the buyer has locked tokens in an escrow."""

    def test_seller_order_records_escrow_uid(self, settlement_output: dict):
        """Seller's local order has the escrow_uid populated."""
        seller_order = settlement_output["seller_order"]
        assert seller_order["escrow_uid"], (
            f"Seller order has no escrow_uid: {seller_order}"
        )

    def test_seller_token_balance_did_not_decrease(self, settlement_output: dict):
        """Seller's MOCK balance does not decrease from settlement onward.

        Strict settlement locks tokens in escrow; arbitration+collect later
        transfers them to the seller. In the current implementation these
        phases can run in one sub-second cascade, so by the time we observe,
        the seller may already hold the transferred tokens. Either state is
        a user-acceptable outcome; the user-visible invariant is that the
        seller is never worse off for having agreed.
        """
        deal: Deal = settlement_output["deal"]
        seller_after = deal.seller_balance()
        assert seller_after >= deal.seller_balance_before, (
            f"Seller lost MOCK at settlement "
            f"(before={deal.seller_balance_before}, after={seller_after})"
        )

    def test_seller_order_reached_post_open_state(self, settlement_output: dict):
        """After settlement the seller's order is no longer 'open' — it's matched,
        accepted, or already closed (in fast mock runs provision may cascade
        through before we observe)."""
        assert settlement_output["seller_order"]["status"] in ("matched", "accepted", "closed")


@pytest.mark.roles_settlement_seller
class TestEscrowCrossCheck:
    """Both sides reference the same escrow (not two separate on-chain objects)."""

    def test_buyer_and_seller_agree_on_escrow_uid(self, settlement_output: dict):
        """The buyer's escrow_uid == seller's escrow_uid."""
        assert (
            settlement_output["buyer_order"]["escrow_uid"]
            == settlement_output["seller_order"]["escrow_uid"]
        )

    def test_attestation_cross_map(self, settlement_output: dict):
        """Buyer's maker_attestation (they put up escrow) corresponds to
        seller's taker_attestation (they received escrow notice)."""
        buyer = settlement_output["buyer_order"]
        seller = settlement_output["seller_order"]
        # Buyer is maker, so maker_attestation = escrow_uid.
        # Seller is taker on buyer's order → their taker_attestation should
        # equal the escrow_uid too.
        assert buyer["maker_attestation"] == seller["taker_attestation"], (
            f"Buyer maker_attestation ({buyer['maker_attestation']}) "
            f"!= seller taker_attestation ({seller['taker_attestation']})"
        )
