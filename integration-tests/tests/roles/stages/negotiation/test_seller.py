"""Negotiation — seller perspective.

User-visible property: "after negotiating with a buyer, my agent has
agreed on a price that is within my acceptable range, and the agreement
is durably recorded."

What the seller observes after negotiation completes:
  - Their negotiation thread has terminal_state=success.
  - The final agreed price in the thread is >= their floor.
  - Their order is marked 'matched' in local SQLite (the settlement
    stage, which follows, will move it to 'accepted').

Cross-role properties (both sides agree) are tested separately.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from tests.roles.helpers.deal import Deal

log = logging.getLogger(__name__)


def _seller_negotiation_thread(db_path: str, seller_order_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # Find the negotiation tied to this seller order
        cur.execute(
            """SELECT negotiation_id FROM negotiation_threads
               WHERE our_order_id = ? LIMIT 1""",
            (seller_order_id,),
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


@pytest.mark.roles_negotiation_seller
class TestSellerReachesAgreement:
    """The seller's negotiation completes successfully at an acceptable price."""

    def test_negotiation_reaches_terminal_success(
        self, negotiation_output: dict,
    ):
        """Seller's negotiation thread has terminal_state=success."""
        assert negotiation_output["seller_terminal_state"] == "success"

    def test_agreed_price_is_at_or_above_initial_ask(
        self, negotiation_output: dict,
    ):
        """The final price reached is at or above the seller's starting ask.

        As the maximizer, the seller's initial ask is their floor; they
        should not have agreed to a price below it.
        """
        deal: Deal = negotiation_output["deal"]
        thread = _seller_negotiation_thread(
            deal.seller_node["agent_db_path"], deal.seller_order_id,
        )
        assert thread, "Seller has no negotiation thread recorded"

        # Find the seller's initial proposal (first message where sender is us)
        our_initial = next(
            (m for m in thread if m["sender"] != "buyer" and m.get("our_price") is not None),
            None,
        )
        accepted_final = next(
            (m for m in reversed(thread) if m["action_taken"] == "ACCEPT_OFFER"),
            None,
        )
        assert our_initial and accepted_final, (
            f"Could not identify initial/final messages in thread: {thread}"
        )

        initial_ask = our_initial["our_price"]
        agreed_price = accepted_final["proposed_price"] or accepted_final["their_price"]
        assert agreed_price is not None, f"Accepted message has no price: {accepted_final}"
        assert agreed_price >= initial_ask, (
            f"Seller agreed to {agreed_price}, below their initial ask {initial_ask}"
        )

    def test_round_count_within_bounded_limit(
        self, negotiation_output: dict,
    ):
        """Negotiation terminated in a finite number of rounds (not runaway).

        The policy has a hard cap (typically 10 rounds). Agreement should
        have happened well inside it for the matched price pair used in
        these tests.
        """
        deal: Deal = negotiation_output["deal"]
        thread = _seller_negotiation_thread(
            deal.seller_node["agent_db_path"], deal.seller_order_id,
        )
        assert 0 < len(thread) <= 20, (
            f"Unexpected round count: {len(thread)} (rounds={[m['round'] for m in thread]})"
        )
