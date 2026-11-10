"""The bare-metal storefront's chain: its baselines, adoption at the floor, and refusals.

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
from floor_database import create_floor_database, floor_ids, floor_snapshot
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

from arkhai_bare_metal_storefront.migrations import (
    CHAIN,
    FLOOR_IDS,
    migrate_storefront_database,
)

_LATER = tuple(migration.id for migration in CHAIN.migrations)


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


def test_a_floor_database_whose_store_never_opened_gains_its_tables(tmp_path) -> None:
    path = create_floor_database(tmp_path / "quiet.db")
    tables = _snapshot(path)["tables"]
    assert "bare_metal_lifecycle_cursor" not in tables
    assert not any(name.startswith("servicing_") for name in tables)

    migrate_storefront_database(path)

    fresh = tmp_path / "fresh.db"
    migrate_storefront_database(fresh)
    assert _snapshot(path) == _snapshot(fresh)
    assert "bare_metal_lifecycle_cursor" in _snapshot(path)["tables"]


def test_store_open_tables_already_present_are_left_as_they_are(tmp_path) -> None:
    path = create_floor_database(tmp_path / "opened.db")
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS bare_metal_lifecycle_cursor "
            "(id INTEGER PRIMARY KEY CHECK (id=1), continuation TEXT)"
        )
        connection.execute("INSERT INTO bare_metal_lifecycle_cursor VALUES (1, 'page-7')")
    connection.close()

    migrate_storefront_database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT continuation FROM bare_metal_lifecycle_cursor"
        ).fetchall() == [("page-7",)]
    finally:
        connection.close()


def test_the_accepted_site_generations_table_is_dropped(tmp_path) -> None:
    path = create_floor_database(tmp_path / "old.db")
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "CREATE TABLE bare_metal_accepted_site_generations (site_id TEXT PRIMARY KEY)"
        )
        connection.execute("INSERT INTO bare_metal_accepted_site_generations VALUES ('site')")
    connection.close()

    migrate_storefront_database(path)

    assert "bare_metal_accepted_site_generations" not in _snapshot(path)["tables"]


def test_a_database_missing_a_floor_id_is_refused_and_unchanged(tmp_path) -> None:
    path = create_floor_database(tmp_path / "older.db")
    missing = FLOOR_IDS[-1]
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
    assert "bare-metal-storefront-migrate" in str(refused.value)
    assert path.read_bytes() == before


def test_a_failing_later_migration_is_named_and_left_pending(tmp_path) -> None:
    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE half_done (id TEXT)")
        raise RuntimeError("domain migration failed")

    failing = dataclasses.replace(
        CHAIN,
        migrations=(*CHAIN.migrations, Migration("bare-metal-storefront-9999-fails", fail)),
    )
    path = tmp_path / "storefront.db"
    connection = sqlite3.connect(path)
    try:
        with pytest.raises(MigrationFailed) as failed:
            migrate(failing, SqliteMigrationConnection(connection))
        assert failed.value.migration_id == "bare-metal-storefront-9999-fails"

        result = check(failing, SqliteMigrationConnection(connection))
        assert result.state is CheckState.BEHIND
        assert result.pending == ("bare-metal-storefront-9999-fails",)
        assert "half_done" not in schema_snapshot(connection)["tables"]
    finally:
        connection.close()


def test_delivery_activation_marks_a_requested_delivery_dispatched_and_strips_access(
    tmp_path,
) -> None:
    path = create_floor_database(tmp_path / "floor.db")
    connection = sqlite3.connect(path)
    with connection:
        # The migration reads only whether a materialization artifact exists;
        # the artifact is planted without the listing, binding, and negotiation
        # its owner trigger requires.
        connection.execute("DROP TRIGGER storefront_domain_artifact_owner_insert")
        for negotiation_id, materialized in (("requested", True), ("unrequested", False)):
            connection.execute(
                "INSERT INTO bare_metal_fulfillment_lifecycle (negotiation_id, "
                "settlement_ref, site_id, physical_resource_id, capacity_reservation_id, "
                "state) VALUES (?, ?, 'site', 'host', ?, 'capacity_reserved')",
                (negotiation_id, f"ref-{negotiation_id}", f"reservation-{negotiation_id}"),
            )
            if materialized:
                connection.execute(
                    "INSERT INTO storefront_domain_artifacts (negotiation_id, "
                    "artifact_slot, offering_mode, domain_identity, contract_major, "
                    "contract_minor, artifact_json) VALUES (?, 'materialization', "
                    "'bare_metal', 'arkhai.bare_metal', 1, 0, '{}')",
                    (negotiation_id,),
                )
        # A private-range address standing for a host; nothing here reaches it.
        connection.execute(
            "INSERT INTO auth_replay_reservations (principal_scheme, principal_identifier, "
            "request_id, request_hash, response_status, response_body, created_at) "
            "VALUES ('eip191', 'buyer', 'access', 'hash', 200, ?, 't')",
            (json.dumps({"method": "ssh", "host": "10.0.0.1", "port": 22, "username": "u"}),),
        )
    connection.close()

    migrate_storefront_database(path)

    connection = sqlite3.connect(path)
    try:
        states = dict(
            connection.execute(
                "SELECT negotiation_id, state FROM bare_metal_fulfillment_lifecycle"
            ).fetchall()
        )
        assert states == {"requested": "dispatch", "unrequested": "capacity_reserved"}
        (status, body), = connection.execute(
            "SELECT response_status, response_body FROM auth_replay_reservations"
        ).fetchall()
        assert status == 200
        assert json.loads(body) == {"method": "ssh"}
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(bare_metal_fulfillment_lifecycle)")
        }
        assert "activated_at_utc" in columns
    finally:
        connection.close()
