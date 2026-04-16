"""Negotiation — buyer perspective.

User-visible property: "after negotiating with a seller, my agent has
agreed on a price within my acceptable range."

What the buyer observes after negotiation completes:
  - Their negotiation thread has terminal_state=success.
  - The agreed price is at or below their ceiling.
  - The negotiation terminated in a bounded number of rounds.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from tests.roles.helpers.deal import Deal

log = logging.getLogger(__name__)


def _buyer_negotiation_thread(db_path: str, buyer_order_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT negotiation_id FROM negotiation_threads
               WHERE our_order_id = ? LIMIT 1""",
            (buyer_order_id,),
        )
        row = cur.fetchone()
        if not row:
            return []
        neg_id = row["negotiation_id"]
        cur.execute(
            """SELECT round, sender, our_price, their_price, proposed_price,
                      action_taken, message_type, timestamp
               FROM negotiation_messages
               WHERE negotiation_id = ? ORDER BY round ASC""",
            (neg_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@pytest.mark.roles_negotiation_buyer
class TestBuyerReachesAgreement:
    """The buyer's negotiation completes at a price they accept."""

    def test_negotiation_reaches_terminal_success(
        self, negotiation_output: dict,
    ):
        """Buyer's negotiation thread has terminal_state=success."""
        assert negotiation_output["buyer_terminal_state"] == "success"

    def test_agreed_price_is_at_or_below_ceiling(
        self, negotiation_output: dict,
    ):
        """The final price reached is at or below the buyer's starting bid.

        As the minimizer, the buyer's initial offer is their ceiling; they
        should not have agreed to a price above it.
        """
        deal: Deal = negotiation_output["deal"]
        thread = _buyer_negotiation_thread(
            deal.buyer_node["agent_db_path"], deal.buyer_order_id,
        )
        assert thread, "Buyer has no negotiation thread recorded"

        our_initial = next(
            (m for m in thread if m.get("our_price") is not None), None,
        )
        accepted_final = next(
            (m for m in reversed(thread) if m["action_taken"] == "ACCEPT_OFFER"), None,
        )
        assert our_initial and accepted_final

        ceiling = our_initial["our_price"]
        agreed_price = accepted_final["proposed_price"] or accepted_final["their_price"]
        assert agreed_price is not None
        assert agreed_price <= ceiling, (
            f"Buyer agreed to {agreed_price}, above their ceiling {ceiling}"
        )

    def test_round_count_within_bounded_limit(
        self, negotiation_output: dict,
    ):
        """Negotiation terminated in a finite number of rounds."""
        deal: Deal = negotiation_output["deal"]
        thread = _buyer_negotiation_thread(
            deal.buyer_node["agent_db_path"], deal.buyer_order_id,
        )
        assert 0 < len(thread) <= 20


@pytest.mark.roles_negotiation_buyer
class TestBothSidesAgreeOnSamePrice:
    """Cross-side check: what buyer agreed to == what seller agreed to."""

    def test_final_prices_match(self, negotiation_output: dict):
        """The last ACCEPT_OFFER price in the buyer's thread equals the
        last ACCEPT_OFFER price in the seller's thread."""
        deal: Deal = negotiation_output["deal"]
        buyer_thread = _buyer_negotiation_thread(
            deal.buyer_node["agent_db_path"], deal.buyer_order_id,
        )
        # seller thread lookup from the other test file's helper — inlined
        # here to avoid a cross-file import
        conn = sqlite3.connect(deal.seller_node["agent_db_path"], timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT negotiation_id FROM negotiation_threads WHERE our_order_id = ? LIMIT 1",
                (deal.seller_order_id,),
            )
            row = cur.fetchone()
            assert row, "Seller has no negotiation thread"
            cur.execute(
                """SELECT proposed_price, their_price, action_taken FROM negotiation_messages
                   WHERE negotiation_id = ? ORDER BY round ASC""",
                (row["negotiation_id"],),
            )
            seller_msgs = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        buyer_final = next(
            (m for m in reversed(buyer_thread) if m["action_taken"] == "ACCEPT_OFFER"), None,
        )
        seller_final = next(
            (m for m in reversed(seller_msgs) if m["action_taken"] == "ACCEPT_OFFER"), None,
        )
        assert buyer_final and seller_final

        buyer_price = buyer_final["proposed_price"] or buyer_final["their_price"]
        seller_price = seller_final["proposed_price"] or seller_final["their_price"]
        assert buyer_price == seller_price, (
            f"Disagreement: buyer accepted {buyer_price}, seller accepted {seller_price}"
        )
