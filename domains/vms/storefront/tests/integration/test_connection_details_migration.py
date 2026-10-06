"""Stored connection details are rewritten into what a delivery records."""

from __future__ import annotations

import json
import sqlite3

from arkhai_vms import VmConnectionDetails

from market_storefront.utils.migrations import _migrate_connection_details_to_delivery

# Recorded before deliveries existed: the job's own result, buyer address included.
_BEFORE_DELIVERIES = {
    "ssh_port": "2222", "tenant_user": "tenant1", "host_ip": "203.0.113.1",
    "ssh_command": "ssh -p 2222 tenant1@203.0.113.1", "timestamp": "2030-01-01T00:00:01Z",
    "ansible_result": {"vm_name": "vm-1"},
}
# Recorded since: the KVM host's inventory name, never a buyer-facing address.
_SINCE_FULFILLMENT = {
    "vm_name": "tenant-abc", "host": "kvm1", "timestamp": "2030-01-01T00:00:01Z",
    "tenant_user": "tenant2", "vm_ip_internal": "192.168.122.9", "ssh_port": "40001",
    "provisioned_resource_ids": ["res-2"],
}
_CURRENT = {"host": "203.0.113.5", "port": 22, "user": "t", "provisioned_resource_ids": []}


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE escrows (escrow_uid TEXT PRIMARY KEY, connection_details TEXT)")
    conn.execute("CREATE TABLE listings (listing_id TEXT PRIMARY KEY, fulfillment_resource TEXT)")
    rows = {
        "before": json.dumps(_BEFORE_DELIVERIES),
        "since": json.dumps(_SINCE_FULFILLMENT),
        "current": json.dumps(_CURRENT),
        "unreadable": "not json",
        "empty": None,
    }
    for key, value in rows.items():
        conn.execute("INSERT INTO escrows VALUES (?, ?)", (key, value))
        conn.execute("INSERT INTO listings VALUES (?, ?)", (key, value))
    return conn


def _stored(conn, table: str, column: str, key_column: str, key: str):
    return conn.execute(
        f"SELECT {column} FROM {table} WHERE {key_column} = ?", (key,)
    ).fetchone()[0]


def test_escrows_and_listings_are_rewritten_into_the_delivery_shape():
    conn = _database()

    _migrate_connection_details_to_delivery(conn)

    for table, column, key_column in (
        ("escrows", "connection_details", "escrow_uid"),
        ("listings", "fulfillment_resource", "listing_id"),
    ):
        before = VmConnectionDetails.model_validate_json(
            _stored(conn, table, column, key_column, "before")
        )
        assert before.connect == "ssh -p 2222 tenant1@203.0.113.1"
        since = json.loads(_stored(conn, table, column, key_column, "since"))
        # The KVM host's name never granted access, so no host is recorded.
        assert since == {
            "port": 40001, "user": "tenant2", "ready_at": "2030-01-01T00:00:01Z",
            "provisioned_resource_ids": ["res-2"],
        }
        assert VmConnectionDetails.model_validate(since).connect is None
        assert json.loads(_stored(conn, table, column, key_column, "current")) == _CURRENT
        assert _stored(conn, table, column, key_column, "unreadable") == "not json"
        assert _stored(conn, table, column, key_column, "empty") is None


def test_a_second_run_changes_nothing():
    conn = _database()
    _migrate_connection_details_to_delivery(conn)
    before = conn.execute("SELECT * FROM escrows ORDER BY escrow_uid").fetchall()

    _migrate_connection_details_to_delivery(conn)

    assert conn.execute("SELECT * FROM escrows ORDER BY escrow_uid").fetchall() == before
