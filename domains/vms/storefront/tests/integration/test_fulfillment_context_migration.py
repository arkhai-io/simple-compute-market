"""Stored fulfillment requests lose the guest name, so a replay still matches.

Restart convergence replays an escrow's stored request verbatim, and
provisioning accepts a repeat only when it equals its own stored copy, which the
provisioning service rewrites the same way.
"""

from __future__ import annotations

import json
import sqlite3

from market_storefront.utils.migrations import _migrate_fulfillment_context_names_no_guest


def _context(request_payload: dict, *, kind: str = "vm.storefront.fulfillment-context") -> dict:
    return {
        "kind": kind,
        "schema_version": 1,
        "payload": {
            "escrow_uid": "escrow-1",
            "listing_id": "listing-1",
            "duration_seconds": 3600,
            "fulfillment_request": {
                "kind": "vm.fulfillment.request",
                "schema_version": 1,
                "payload": request_payload,
            },
        },
        "storefront_domain_binding": {"negotiation_id": "neg-1", "site_id": "site-1"},
    }


_NAMED = _context({"vm_target": "tenant-ab12", "ssh_pubkey": "ssh-ed25519 AAAA"})
_CURRENT = _context({"ssh_pubkey": "ssh-ed25519 AAAA"})
_OTHER_KIND = _context({"vm_target": "x"}, kind="another.context")


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE escrows (escrow_uid TEXT PRIMARY KEY, status TEXT, "
        "fulfillment_context TEXT)"
    )
    rows = {
        "named-pending": ("pending", json.dumps(_NAMED)),
        "named-ready": ("ready", json.dumps(_NAMED)),
        "current": ("pending", json.dumps(_CURRENT)),
        "other-kind": ("pending", json.dumps(_OTHER_KIND)),
        "unreadable": ("pending", "not json"),
        "empty": ("pending", None),
    }
    for key, (status, value) in rows.items():
        conn.execute("INSERT INTO escrows VALUES (?, ?, ?)", (key, status, value))
    return conn


def _stored(conn, escrow_uid: str):
    raw = conn.execute(
        "SELECT fulfillment_context FROM escrows WHERE escrow_uid = ?", (escrow_uid,)
    ).fetchone()[0]
    try:
        return json.loads(raw) if raw is not None else None
    except ValueError:
        return raw


def test_every_escrow_s_stored_request_loses_the_guest_name_and_nothing_else():
    conn = _database()

    _migrate_fulfillment_context_names_no_guest(conn)

    for escrow_uid in ("named-pending", "named-ready"):
        assert _stored(conn, escrow_uid) == _CURRENT


def test_other_values_are_left_alone_and_a_rerun_changes_nothing():
    conn = _database()

    _migrate_fulfillment_context_names_no_guest(conn)
    first = {
        uid: _stored(conn, uid)
        for uid in ("named-pending", "current", "other-kind", "unreadable", "empty")
    }
    _migrate_fulfillment_context_names_no_guest(conn)

    assert first["current"] == _CURRENT
    assert first["other-kind"] == _OTHER_KIND
    assert first["unreadable"] == "not json"
    assert first["empty"] is None
    assert {uid: _stored(conn, uid) for uid in first} == first


def test_a_database_without_contexts_is_left_alone():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE escrows (escrow_uid TEXT PRIMARY KEY)")

    _migrate_fulfillment_context_names_no_guest(conn)
