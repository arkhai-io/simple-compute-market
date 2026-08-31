from __future__ import annotations

import json
import sqlite3

import pytest
from market_identity import Identity

from core_storefront.sqlite_migrations import (
    _migrate_marketplace_principals,
    apply_schema_migrations,
)


def test_principal_migration_is_transactional_and_idempotent(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    valid = "0x" + "a1" * 20
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE stage_events (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO stage_events (id, data) VALUES (?, ?)",
        (1, json.dumps({"version": 1, "buyer_address": valid, "operation_id": "op-1"})),
    )
    conn.execute(
        "INSERT INTO stage_events (id, data) VALUES (?, ?)",
        (2, json.dumps({"version": 1, "seller_address": "malformed"})),
    )
    conn.commit()

    with pytest.raises(ValueError, match="valid legacy EIP-191 address"):
        apply_schema_migrations(conn)
    unchanged = json.loads(conn.execute("SELECT data FROM stage_events WHERE id=1").fetchone()[0])
    assert unchanged["buyer_address"] == valid
    assert "buyer_principal" not in unchanged

    conn.execute(
        "UPDATE stage_events SET data=? WHERE id=2",
        (json.dumps({"version": 1, "seller_address": "0x" + "b2" * 20}),),
    )
    apply_schema_migrations(conn)
    first = conn.execute("SELECT id, data FROM stage_events ORDER BY id").fetchall()
    apply_schema_migrations(conn)
    second = conn.execute("SELECT id, data FROM stage_events ORDER BY id").fetchall()
    conn.close()

    assert second == first
    migrated = json.loads(first[0][1])
    assert migrated == {
        "buyer_principal": {"scheme": "eip191", "identifier": valid},
        "operation_id": "op-1",
        "version": 2,
    }



def test_principal_migration_rejects_checksum_drift_atomically(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "checksum-drift.db")
    conn.execute("CREATE TABLE stage_events (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    lower = "0x" + "a1" * 20
    upper = "0x" + "A1" * 20
    original = [
        (1, json.dumps({"buyer_address": lower, "operation_id": "op-1"})),
        (2, json.dumps({"seller_address": upper, "operation_id": "op-2"})),
    ]
    conn.executemany("INSERT INTO stage_events (id, data) VALUES (?, ?)", original)
    conn.commit()

    with pytest.raises(ValueError, match="checksum/casing drift"):
        apply_schema_migrations(conn)

    assert conn.execute("SELECT id, data FROM stage_events ORDER BY id").fetchall() == original
    conn.close()


def test_principal_migration_rejects_duplicate_service_peer_ownership(
    tmp_path,
) -> None:
    conn = sqlite3.connect(tmp_path / "duplicate-peer.db")
    conn.execute(
        """
        CREATE TABLE service_peers (
          peer_id TEXT PRIMARY KEY,
          role TEXT NOT NULL,
          site_id TEXT NOT NULL,
          address TEXT NOT NULL
        )
        """
    )
    address = "0x" + "c3" * 20
    original = [
        ("peer-a", "service", "site-a", address),
        ("peer-b", "service", "site-b", address),
    ]
    conn.executemany(
        "INSERT INTO service_peers (peer_id, role, site_id, address) VALUES (?, ?, ?, ?)",
        original,
    )
    conn.commit()

    with pytest.raises(ValueError, match="duplicate active service-peer"):
        apply_schema_migrations(conn)

    assert conn.execute(
        "SELECT peer_id, role, site_id, address FROM service_peers ORDER BY peer_id"
    ).fetchall() == original
    conn.close()


def test_legacy_replay_primary_key_is_rebuilt_without_losing_outcome(
    tmp_path,
) -> None:
    conn = sqlite3.connect(tmp_path / "legacy-replay.db")
    conn.execute(
        """
        CREATE TABLE auth_replay_reservations (
          principal TEXT NOT NULL,
          request_id TEXT NOT NULL,
          request_hash TEXT NOT NULL,
          response_status INTEGER,
          response_body TEXT,
          created_at TEXT NOT NULL,
          PRIMARY KEY (principal, request_id)
        )
        """
    )
    address = "0x" + "ab" * 20
    conn.execute(
        "INSERT INTO auth_replay_reservations VALUES (?, ?, ?, ?, ?, ?)",
        (address, "request-1", "semantic-hash", 201, '{"ok":true}', "2026-01-01"),
    )
    conn.commit()

    apply_schema_migrations(conn)
    first = conn.execute(
        """
        SELECT principal_scheme, principal_identifier, request_id, request_hash,
               response_status, response_body, attempt_token, lease_until, created_at
        FROM auth_replay_reservations
        """
    ).fetchone()
    apply_schema_migrations(conn)
    second = conn.execute(
        """
        SELECT principal_scheme, principal_identifier, request_id, request_hash,
               response_status, response_body, attempt_token, lease_until, created_at
        FROM auth_replay_reservations
        """
    ).fetchone()

    assert first == second == (
        "eip191",
        address,
        "request-1",
        "semantic-hash",
        201,
        '{"ok":true}',
        None,
        None,
        "2026-01-01",
    )
    assert "principal" not in {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(auth_replay_reservations)"
        ).fetchall()
    }
    conn.close()


def test_legacy_service_peer_is_rebuilt_with_canonical_identity(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "legacy-peer.db")
    conn.execute(
        """
        CREATE TABLE service_peers (
          peer_id TEXT PRIMARY KEY,
          role TEXT NOT NULL,
          site_id TEXT NOT NULL,
          address TEXT NOT NULL,
          UNIQUE (role, address)
        )
        """
    )
    address = "0x" + "c3" * 20
    conn.execute(
        "INSERT INTO service_peers VALUES (?, ?, ?, ?)",
        ("peer-a", "service", "site-a", address),
    )
    conn.commit()

    apply_schema_migrations(conn)
    first = conn.execute(
        """
        SELECT peer_id, role, site_id, principal_scheme, principal_identifier,
               status, created_at, updated_at
        FROM service_peers
        """
    ).fetchone()
    apply_schema_migrations(conn)
    second = conn.execute(
        """
        SELECT peer_id, role, site_id, principal_scheme, principal_identifier,
               status, created_at, updated_at
        FROM service_peers
        """
    ).fetchone()

    assert first == second == (
        "peer-a",
        "service",
        "site-a",
        "eip191",
        address,
        "active",
        "1970-01-01T00:00:00+00:00",
        "1970-01-01T00:00:00+00:00",
    )
    assert "address" not in {
        row[1] for row in conn.execute("PRAGMA table_info(service_peers)").fetchall()
    }
    conn.close()


def test_legacy_heartbeat_resolves_parties_through_escrow(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "heartbeat.db")
    conn.execute(
        "CREATE TABLE listings (listing_id TEXT PRIMARY KEY, seller TEXT NOT NULL)"
    )
    conn.execute(
        """
        CREATE TABLE negotiation_threads (
          negotiation_id TEXT PRIMARY KEY,
          our_listing_id TEXT NOT NULL,
          buyer TEXT NOT NULL,
          settlement_plan TEXT
        )
        """
    )
    conn.execute(
        "CREATE TABLE escrows (escrow_uid TEXT PRIMARY KEY, negotiation_id TEXT NOT NULL)"
    )
    conn.execute(
        """
        CREATE TABLE deal_heartbeats (
          id INTEGER PRIMARY KEY,
          deal_ref TEXT NOT NULL,
          signer TEXT NOT NULL
        )
        """
    )
    buyer = "0x" + "11" * 20
    seller = "0x" + "22" * 20
    storefront_url = "http://seller-storefront:8001"
    conn.execute(
        "INSERT INTO listings VALUES (?, ?)",
        ("listing-1", storefront_url),
    )
    conn.execute(
        "INSERT INTO negotiation_threads VALUES (?, ?, ?, NULL)",
        ("negotiation-1", "listing-1", buyer),
    )
    conn.execute(
        "INSERT INTO escrows VALUES (?, ?)",
        ("escrow-1", "negotiation-1"),
    )
    conn.execute(
        "INSERT INTO deal_heartbeats VALUES (?, ?, ?)",
        (1, "escrow-1", buyer),
    )

    _migrate_marketplace_principals(
        conn,
        Identity(scheme="eip191", identifier=seller),
        (storefront_url,),
    )

    assert conn.execute(
        """
        SELECT buyer_scheme, buyer_identifier, seller_scheme, seller_identifier
        FROM deal_heartbeats WHERE id=1
        """
    ).fetchone() == ("eip191", buyer, "eip191", seller)
    assert "seller" not in {
        row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()
    }
    assert conn.execute(
        "SELECT storefront_url FROM listings WHERE listing_id='listing-1'"
    ).fetchone() == (storefront_url,)
    conn.close()


def test_listing_locator_mismatch_rolls_back_identity_cutover(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "listing-url-mismatch.db")
    conn.execute(
        """
        CREATE TABLE listings (
          listing_id TEXT PRIMARY KEY,
          seller TEXT NOT NULL,
          storefront_url TEXT
        )
        """
    )
    expected_url = "http://seller-storefront:8001"
    foreign_url = "http://other-storefront:8001"
    conn.execute(
        "INSERT INTO listings VALUES (?, ?, ?)",
        ("listing-1", expected_url, foreign_url),
    )
    conn.commit()
    principal = Identity(
        scheme="eip191",
        identifier="0x" + "22" * 20,
    )

    with pytest.raises(ValueError, match="conflicts with its legacy value"):
        apply_schema_migrations(
            conn,
            local_listing_principal=principal,
            expected_legacy_sellers=(expected_url,),
        )

    assert conn.execute(
        "SELECT seller, storefront_url FROM listings WHERE listing_id='listing-1'"
    ).fetchone() == (expected_url, foreign_url)
    assert "seller" in {
        row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()
    }
    conn.close()