"""A 'deal' is one full buyer-seller transaction lifecycle.

In the current (coupled, event-driven) implementation, a deal starts when
the buyer creates a matching order and cascades automatically through
negotiation, settlement, and provision. Stage boundaries are observable
via SQLite + registry state transitions — this module polls for each
boundary so tests can assert properties at each milestone.

After the planned rewrite, each stage will be independently triggered,
but the observable properties (and therefore the test assertions) remain
the same. This module's contract is stable; its internals will simplify.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from tests.helpers.polling import poll_until

log = logging.getLogger(__name__)


# Milestone predicates are pure functions from (buyer_db, seller_db,
# registry_url) → snapshot | None. They return None while the milestone
# hasn't been reached, and a snapshot dict when it has.


def _load_order(db_path: str, order_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT order_id, status, order_maker, order_taker, matched_offer_id,
                      maker_attestation, taker_attestation, escrow_uid, oracle_address,
                      offer_resource, demand_resource, fulfillment_resource, duration_hours
               FROM orders WHERE order_id = ?""",
            (order_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _load_negotiation_terminal_state(db_path: str, our_order_id: str) -> str | None:
    """Return the terminal_state for the negotiation thread tied to our order, or None."""
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT terminal_state FROM negotiation_threads
               WHERE our_order_id = ? AND terminal_state IS NOT NULL
               LIMIT 1""",
            (our_order_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _load_credentials(db_path: str, order_id: str, role: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT password, ssh_commands, key_type FROM credentials
               WHERE order_id = ? AND role = ? LIMIT 1""",
            (order_id, role),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


@dataclass
class Deal:
    """One buyer-seller transaction lifecycle.

    The buyer_order_id and seller_order_id are the two sides of the matched
    pair. Both agent DBs record the same deal, one as buyer (maker) and
    one as seller (taker), or vice versa depending on who created first.
    """
    buyer_node: dict
    seller_node: dict
    buyer_order_id: str
    seller_order_id: str
    registry_url: str

    # ------------------------------------------------------------------
    # Milestones: block until the named stage has produced its signal
    # ------------------------------------------------------------------

    def wait_for_negotiation_complete(
        self, *, timeout_s: float = 60, interval_s: float = 2,
    ) -> dict:
        """Block until both sides' negotiation thread reaches terminal_state=success.

        Returns a snapshot of what the negotiation produced.
        """
        def _check():
            buyer_state = _load_negotiation_terminal_state(
                self.buyer_node["agent_db_path"], self.buyer_order_id,
            )
            seller_state = _load_negotiation_terminal_state(
                self.seller_node["agent_db_path"], self.seller_order_id,
            )
            if buyer_state == "success" and seller_state == "success":
                return {"buyer_terminal_state": buyer_state,
                        "seller_terminal_state": seller_state}
            return None

        return poll_until(
            _check, timeout_s=timeout_s, interval_s=interval_s,
            description="both sides negotiation terminal_state=success",
        )

    def wait_for_settlement(
        self, *, timeout_s: float = 60, interval_s: float = 2,
    ) -> dict:
        """Block until both orders have escrow_uid and status=accepted.

        Returns a snapshot of the settled orders.
        """
        def _check():
            buyer = _load_order(self.buyer_node["agent_db_path"], self.buyer_order_id)
            seller = _load_order(self.seller_node["agent_db_path"], self.seller_order_id)
            if not buyer or not seller:
                return None
            if (buyer.get("escrow_uid") and buyer["status"] == "accepted"
                    and seller.get("escrow_uid") and seller["status"] in ("accepted", "matched")):
                return {"buyer_order": buyer, "seller_order": seller}
            return None

        return poll_until(
            _check, timeout_s=timeout_s, interval_s=interval_s,
            description="both orders have escrow_uid and are accepted",
        )

    def wait_for_provision(
        self, *, timeout_s: float = 120, interval_s: float = 3,
    ) -> dict:
        """Block until the buyer has taker_attestation set and credentials stored.

        Returns a snapshot including the tenant credentials the buyer can
        use to SSH into the provisioned machine.
        """
        def _check():
            buyer = _load_order(self.buyer_node["agent_db_path"], self.buyer_order_id)
            if not buyer or not buyer.get("taker_attestation"):
                return None
            tenant = _load_credentials(
                self.buyer_node["agent_db_path"], self.buyer_order_id, role="tenant",
            )
            if not tenant:
                return None
            return {"buyer_order": buyer, "tenant_credentials": tenant}

        return poll_until(
            _check, timeout_s=timeout_s, interval_s=interval_s,
            description="buyer has taker_attestation and tenant credentials",
        )

    def wait_for_closed(
        self, *, timeout_s: float = 60, interval_s: float = 2,
    ) -> dict:
        """Block until both orders reach status=closed (deal fully complete)."""
        def _check():
            buyer = _load_order(self.buyer_node["agent_db_path"], self.buyer_order_id)
            seller = _load_order(self.seller_node["agent_db_path"], self.seller_order_id)
            if buyer and seller and buyer["status"] == "closed" and seller["status"] == "closed":
                return {"buyer_order": buyer, "seller_order": seller}
            return None

        return poll_until(
            _check, timeout_s=timeout_s, interval_s=interval_s,
            description="both orders closed",
        )
