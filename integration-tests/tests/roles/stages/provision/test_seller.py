"""Provision — seller perspective.

User-visible property: 'after I provisioned the machine, my resource
is marked as leased (not available for other buyers) and I have proof
on-chain that I delivered.'

What the seller observes after provision completes:
  - One of their compute resources transitioned to state=leased with a
    lease_end_utc timestamp.
  - Their local order has maker_attestation (fulfillment UID) populated.
  - Their own tenant credentials (root + tenant SSH) are stored locally
    so they can administer the VM during the lease.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from tests.roles.helpers.deal import Deal

log = logging.getLogger(__name__)


def _seller_resources(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT resource_id, state, value, attributes
               FROM resources WHERE resource_type = 'compute.gpu'"""
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _seller_credentials(db_path: str, order_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT role, password, ssh_commands, ssh_key_path_host, key_type
               FROM credentials WHERE order_id = ? AND granted_to = 'self'""",
            (order_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _load_seller_order(db_path: str, order_id: str) -> dict:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()


@pytest.mark.roles_provision_seller
class TestSellerDeliversMachine:
    """The seller has provisioned a VM and marked its resource as leased."""

    def test_seller_resource_transitioned_to_leased(self, provision_output: dict):
        """At least one compute resource is in state=leased with lease_end_utc set."""
        deal: Deal = provision_output["deal"]
        resources = _seller_resources(deal.seller_node["agent_db_path"])
        assert resources, "Seller has no compute resources"

        leased = [r for r in resources if r["state"] == "leased"]
        assert leased, (
            f"No seller resource is in state=leased. "
            f"States: {[r['state'] for r in resources]}"
        )

        # lease_end_utc should be populated in attributes
        import json
        for r in leased:
            attrs = json.loads(r["attributes"]) if isinstance(r["attributes"], str) else r["attributes"]
            assert attrs.get("lease_end_utc"), (
                f"Leased resource {r['resource_id']} has no lease_end_utc: {attrs}"
            )

    def test_seller_order_records_fulfillment(self, provision_output: dict):
        """Seller's order has maker_attestation (fulfillment_uid) set,
        proving on-chain that they delivered."""
        deal: Deal = provision_output["deal"]
        seller_order = _load_seller_order(
            deal.seller_node["agent_db_path"], deal.seller_order_id,
        )
        assert seller_order["maker_attestation"], (
            f"Seller order has no maker_attestation: {seller_order}"
        )
        # Should be distinct from the escrow_uid (which is taker_attestation)
        assert seller_order["maker_attestation"] != seller_order["escrow_uid"]

    def test_seller_stored_own_credentials(self, provision_output: dict):
        """Seller stored root + tenant credentials locally for the VM they provisioned."""
        deal: Deal = provision_output["deal"]
        creds = _seller_credentials(
            deal.seller_node["agent_db_path"], deal.seller_order_id,
        )
        roles = {c["role"] for c in creds}
        assert "tenant" in roles, f"No tenant credentials stored: {creds}"
        # Root credentials help the seller administer the VM if needed;
        # they may or may not be present depending on provisioning mode.

    def test_seller_balance_still_locked(self, provision_output: dict):
        """Seller's MOCK balance is still unchanged at provision —
        they collect only after arbitration completes (post-settlement)."""
        deal: Deal = provision_output["deal"]
        seller_current = deal.seller_balance()
        assert seller_current == deal.seller_balance_before, (
            f"Seller balance changed during provision "
            f"(before={deal.seller_balance_before}, now={seller_current}); "
            f"seller should collect only in post-settlement"
        )
