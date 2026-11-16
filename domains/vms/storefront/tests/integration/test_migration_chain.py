"""The VM storefront's chain: its baselines, adoption at the floor, and refusals.

Library integration: real SQLite files migrated through the chain's engine, no
application. A v0.3.0 database is built from the floor fixture's stored DDL
with every ID that release's chain recorded (``tests/floor_database.py``).
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest
from market_deal_servicing import create_schema as create_servicing_schema
from market_identity import Ed25519Signer
from market_schema_migrations import (
    CheckState,
    Migration,
    MigrationFailed,
    MigrationRefused,
    SqliteMigrationConnection,
    check,
    check_sqlite_file,
    migrate,
    schema_snapshot,
)

from market_storefront.utils.migrations import CHAIN, FLOOR_IDS, migrate_storefront_database
from tests.floor_database import create_floor_database, floor_ids, floor_snapshot

_LATER = tuple(migration.id for migration in CHAIN.migrations)
#: The seller a planted listing names; a development key, never used on a
#: public network.
_SELLER = Ed25519Signer(b"\x5d" * 32).identity


def _snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def _recorded(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return sorted(row[0] for row in connection.execute("SELECT id FROM schema_migrations"))
    finally:
        connection.close()


def test_the_baselines_reproduce_the_floor() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        for baseline in CHAIN.baselines:
            baseline.apply(connection)
        assert schema_snapshot(connection) == floor_snapshot()
    finally:
        connection.close()


def test_the_chain_floor_is_the_fixture_floor() -> None:
    assert list(FLOOR_IDS) == floor_ids()


def test_a_fresh_database_gets_the_floor_and_every_later_migration(tmp_path) -> None:
    fresh = tmp_path / "fresh.db"
    report = migrate_storefront_database(fresh)
    assert report.adopted is False
    assert report.applied == CHAIN.ids

    adopted = create_floor_database(tmp_path / "floor.db")
    migrate_storefront_database(adopted)

    assert _snapshot(fresh) == _snapshot(adopted)
    assert _recorded(fresh) == _recorded(adopted) == sorted(CHAIN.ids)


def test_a_floor_database_is_adopted_and_only_the_later_migrations_run(tmp_path) -> None:
    path = create_floor_database(tmp_path / "floor.db")
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "INSERT INTO stage_events (ts, stage, event, data) "
            "VALUES ('t', 'kept', 'kept', '{}')"
        )
    connection.close()

    report = migrate_storefront_database(path)

    assert report.adopted is True
    assert report.applied == _LATER
    assert check_sqlite_file(CHAIN, path).state is CheckState.COMPATIBLE
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT stage FROM stage_events").fetchall() == [("kept",)]
    finally:
        connection.close()


def test_a_rerun_changes_nothing(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    migrate_storefront_database(path)
    before = path.read_bytes()

    report = migrate_storefront_database(path)

    assert report.applied == ()
    assert path.read_bytes() == before


def test_a_floor_database_that_never_opened_a_store_gains_its_tables(tmp_path) -> None:
    """No deal was ever delivered, so no deal-servicing table exists."""
    path = create_floor_database(tmp_path / "quiet.db")
    assert not any(name.startswith("servicing_") for name in _snapshot(path)["tables"])

    migrate_storefront_database(path)

    fresh = tmp_path / "fresh.db"
    migrate_storefront_database(fresh)
    assert _snapshot(path) == _snapshot(fresh)


def test_store_open_tables_already_present_are_left_as_they_are(tmp_path) -> None:
    path = create_floor_database(tmp_path / "delivered.db")
    connection = sqlite3.connect(path)
    with connection:
        create_servicing_schema(connection)
    tables = sorted(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'servicing_%'"
        )
    )
    connection.close()
    assert tables, "the deal-servicing schema creates servicing tables"
    with_tables = _snapshot(path)

    migrate_storefront_database(path)

    migrated = _snapshot(path)
    for table in tables:
        assert migrated["tables"][table] == with_tables["tables"][table]


def test_the_frozen_inventory_tables_are_dropped(tmp_path) -> None:
    path = create_floor_database(tmp_path / "old.db")
    frozen = (
        "compute_allocations",
        "resource_transition_events",
        "compute_pool_members",
        "resources",
        "hosts",
        "compute_capacity_pools",
        "compute_inventory_pools",
    )
    connection = sqlite3.connect(path)
    with connection:
        for table in frozen:
            connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
            connection.execute(f"INSERT INTO {table} VALUES ('retained')")
    connection.close()

    migrate_storefront_database(path)

    assert not set(frozen) & set(_snapshot(path)["tables"])


def test_a_database_missing_a_floor_id_is_refused_and_unchanged(tmp_path) -> None:
    path = create_floor_database(tmp_path / "older.db")
    missing = FLOOR_IDS[5]
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("DELETE FROM schema_migrations WHERE id = ?", (missing,))
    connection.close()
    before = path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_storefront_database(path)

    assert refused.value.result.state is CheckState.UNSUPPORTED
    assert refused.value.result.missing == (missing,)
    assert missing in str(refused.value)
    assert "market-storefront-migrate" in str(refused.value)
    assert path.read_bytes() == before


def test_a_failing_later_migration_is_named_and_left_pending(tmp_path) -> None:
    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE half_done (id TEXT)")
        raise RuntimeError("domain migration failed")

    failing = dataclasses.replace(
        CHAIN, migrations=(*CHAIN.migrations, Migration("29990101_001_fails", fail))
    )
    path = tmp_path / "storefront.db"
    connection = sqlite3.connect(path)
    try:
        with pytest.raises(MigrationFailed) as failed:
            migrate(failing, SqliteMigrationConnection(connection))
        assert failed.value.migration_id == "29990101_001_fails"
        assert "29990101_001_fails" in str(failed.value)

        result = check(failing, SqliteMigrationConnection(connection))
        assert result.state is CheckState.BEHIND
        assert result.pending == ("29990101_001_fails",)
        assert "half_done" not in schema_snapshot(connection)["tables"]
    finally:
        connection.close()


def test_delivery_activation_reads_a_provider_ready_phase_as_ready(tmp_path) -> None:
    path = create_floor_database(tmp_path / "floor.db")
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "INSERT INTO vm_settlement_evidence VALUES "
            "('neg-1', 'arkhai.payments.v1', 'digest', 'ref-1', 'verified', '{}')"
        )
        connection.execute(
            "INSERT INTO vm_settlement_evidence VALUES "
            "('neg-2', 'arkhai.payments.v1', 'digest', 'ref-2', 'verified', '{}')"
        )
        connection.executemany(
            "INSERT INTO vm_delivery_records (negotiation_id, status, fulfillment_phase, "
            "created_at, updated_at) VALUES (?, 'provisioning', ?, 't', 't')",
            [("neg-1", "activate"), ("neg-2", "dispatch")],
        )
    connection.close()

    migrate_storefront_database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT negotiation_id, fulfillment_phase, activated_at_utc "
            "FROM vm_delivery_records ORDER BY negotiation_id"
        ).fetchall() == [("neg-1", "ready", None), ("neg-2", "dispatch", None)]
    finally:
        connection.close()


def test_a_recorded_publication_gains_no_published_payload(tmp_path) -> None:
    """A v0.3.0 row's payload is the last attempt's, not one known accepted, so
    its listing has no published payload until its next successful publish."""
    path = create_floor_database(tmp_path / "floor.db")
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "INSERT INTO publications (listing_id, registry_url, payload_json, "
            "published_at, status) VALUES ('L1', 'http://registry.test', '{}', 1, "
            "'published')"
        )
    connection.close()

    migrate_storefront_database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT payload_json, published_payload_json FROM publications"
        ).fetchall() == [("{}", None)]
    finally:
        connection.close()


def test_a_recorded_thread_keeps_its_negotiated_scalar(tmp_path) -> None:
    """A v0.3.0 thread's accepted scalar is read under ``negotiated_scalar``,
    exact and unchanged, after the chain runs."""
    path = create_floor_database(tmp_path / "floor.db")
    scalar = str(150 * 10**18)
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "INSERT INTO negotiation_threads (negotiation_id, buyer_scheme, "
            "buyer_identifier, seller_scheme, seller_identifier, terminal_state, "
            "agreed_price) VALUES ('neg-1', ?, ?, ?, ?, 'success', ?)",
            (_SELLER.scheme.value, "buyer", _SELLER.scheme.value, _SELLER.identifier, scalar),
        )
    connection.close()

    migrate_storefront_database(path)

    connection = sqlite3.connect(path)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(negotiation_threads)")
        }
        assert "negotiated_scalar" in columns
        assert "agreed_price" not in columns
        assert connection.execute(
            "SELECT negotiation_id, typeof(negotiated_scalar), negotiated_scalar "
            "FROM negotiation_threads"
        ).fetchall() == [("neg-1", "text", scalar)]
    finally:
        connection.close()


def test_stored_vm_credentials_are_cleared(tmp_path) -> None:
    path = create_floor_database(tmp_path / "floor.db")
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "INSERT INTO vm_settlement_evidence VALUES "
            "('neg-1', 'arkhai.payments.v1', 'digest', 'ref-1', 'verified', '{}')"
        )
        connection.execute(
            "INSERT INTO vm_delivery_records (negotiation_id, status, tenant_credentials, "
            "created_at, updated_at) VALUES ('neg-1', 'ready', 'secret', 't', 't')"
        )
        connection.execute(
            "INSERT INTO escrows (escrow_uid, negotiation_id, status, tenant_credentials, "
            "created_at, updated_at) VALUES ('escrow-1', 'neg-1', 'ready', 'secret', 't', 't')"
        )
        connection.execute(
            "INSERT INTO listings (listing_id, status, created_at, updated_at, "
            "listing_resource, seller_scheme, seller_identifier, storefront_url) "
            "VALUES ('bm-listing', 'open', 't', 't', '{}', ?, ?, 'http://seller.test')",
            (_SELLER.scheme.value, _SELLER.identifier),
        )
        connection.execute(
            "INSERT INTO storefront_listing_bindings (listing_id, site_id, offering_mode, "
            "domain_identity, contract_major, contract_minor, derivation_key, "
            "source_envelope_json, last_reconciled_at, capacity_backing) VALUES "
            "('bm-listing', 'site', 'bare_metal', 'bare_metal.v1', 1, 0, 'key', '{}', 't', "
            "'backed')"
        )
        connection.executemany(
            "INSERT INTO credentials (id, listing_id, role, granted_to, password, created_at) "
            "VALUES (?, ?, 'tenant', 'buyer', 'secret', 't')",
            [("cred-vm", "vm-listing"), ("cred-bm", "bm-listing")],
        )
        connection.execute(
            "INSERT INTO auth_replay_reservations (principal_scheme, principal_identifier, "
            "request_id, request_hash, response_status, response_body, created_at) "
            "VALUES ('eip191', 'buyer', 'req-1', 'hash', 200, ?, 't')",
            (json.dumps({"status": "ready", "tenant_credentials": {"password": "secret"}}),),
        )
        connection.execute(
            "INSERT INTO auth_replay_reservations (principal_scheme, principal_identifier, "
            "request_id, request_hash, response_status, response_body, created_at) "
            "VALUES ('eip191', 'buyer', 'req-2', 'hash', 200, ?, 't')",
            (json.dumps({"action": "accept"}),),
        )
    connection.close()

    migrate_storefront_database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT tenant_credentials FROM vm_delivery_records"
        ).fetchall() == [(None,)]
        assert connection.execute("SELECT tenant_credentials FROM escrows").fetchall() == [
            (None,)
        ]
        # Only a listing another offering mode binds keeps its rows.
        assert connection.execute("SELECT id FROM credentials").fetchall() == [("cred-bm",)]
        recorded = {
            request_id: (status, json.loads(body))
            for request_id, status, body in connection.execute(
                "SELECT request_id, response_status, response_body FROM auth_replay_reservations"
            )
        }
        assert recorded == {
            "req-1": (200, {"status": "ready"}),
            "req-2": (200, {"action": "accept"}),
        }
    finally:
        connection.close()
