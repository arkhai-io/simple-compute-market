"""The API-credit storefront's chain: its baselines, adoption at the floor, and refusals.

Library integration: real SQLite files migrated through the chain's engine, no
application. A v0.3.0 database is built from the floor fixture's stored DDL
with every ID that release's chain recorded.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest
from market_schema_migrations import (
    CheckState,
    Migration,
    MigrationFailed,
    MigrationRefused,
    SqliteMigrationConnection,
    UnsupportedCause,
    check,
    check_sqlite_file,
    migrate,
    schema_snapshot,
)

from arkhai_api_selling.migrations import migrate_storefront_database

from apicredits_storefront.migrate import CHAIN, FLOOR_IDS

_FLOOR = Path(__file__).resolve().parents[1] / "fixtures" / "v0_3_0_floor"
# SQLite records the sequence table it creates for an AUTOINCREMENT key among
# the stored DDL, but refuses to create it by name.
_SEQUENCE_TABLE = "CREATE TABLE sqlite_sequence(name,seq);"


def _floor_ids() -> list[str]:
    return json.loads((_FLOOR / "floor_ids.json").read_text(encoding="utf-8"))


def _recorded(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return sorted(row[0] for row in connection.execute("SELECT id FROM schema_migrations"))
    finally:
        connection.close()


def _snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def _release_database(path: Path, *, recorded: list[str] | None = None) -> Path:
    """A database as the v0.3.0 release's API-credit storefront left it, its
    ledger recording ``recorded`` in place of the release's IDs where given."""
    ddl = (_FLOOR / "ddl.sql").read_text(encoding="utf-8").replace(_SEQUENCE_TABLE, "")
    ids = _floor_ids() if recorded is None else recorded
    connection = sqlite3.connect(path)
    try:
        connection.executescript(ddl)
        with connection:
            connection.executemany(
                "INSERT INTO schema_migrations (id) VALUES (?)", [(i,) for i in ids]
            )
    finally:
        connection.close()
    return path


def test_the_baselines_reproduce_the_release_schema() -> None:
    expected = json.loads((_FLOOR / "schema.json").read_text(encoding="utf-8"))
    connection = sqlite3.connect(":memory:")
    try:
        for baseline in CHAIN.baselines:
            baseline.apply(connection)
        assert schema_snapshot(connection) == expected
    finally:
        connection.close()


def test_a_fresh_database_gets_every_baseline_and_a_rerun_changes_nothing(tmp_path) -> None:
    path = tmp_path / "storefront.db"

    report = migrate_storefront_database(CHAIN, path)

    assert report.adopted is False
    assert report.applied == CHAIN.ids
    before = path.read_bytes()
    assert migrate_storefront_database(CHAIN, path).applied == ()
    assert path.read_bytes() == before


def test_the_chain_floor_is_the_fixture_floor() -> None:
    assert CHAIN.floor.release == "marketplace 0.3.0"
    assert list(CHAIN.floor.recorded) == list(FLOOR_IDS) == _floor_ids()


def test_a_database_from_the_release_is_adopted_and_ends_as_a_fresh_one(tmp_path) -> None:
    path = _release_database(tmp_path / "release.db")
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "INSERT INTO stage_events (ts, stage, event, data) "
            "VALUES ('t', 'kept', 'kept', '{}')"
        )
    connection.close()
    later = tuple(migration.id for migration in CHAIN.migrations)
    assert check_sqlite_file(CHAIN, path).adopting == CHAIN.baseline_ids

    report = migrate_storefront_database(CHAIN, path)

    assert report.adopted is True
    assert report.applied == later
    assert check_sqlite_file(CHAIN, path).state is CheckState.COMPATIBLE
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT stage FROM stage_events").fetchall() == [("kept",)]
    finally:
        connection.close()
    fresh = tmp_path / "fresh.db"
    migrate_storefront_database(CHAIN, fresh)
    assert _snapshot(path) == _snapshot(fresh)
    assert _recorded(path) == _recorded(fresh) == sorted(CHAIN.ids)


def test_a_database_from_the_release_carrying_an_earlier_record_and_table_is_adopted(
    tmp_path,
) -> None:
    earlier = "20250101_001_recorded_by_an_earlier_release"
    path = _release_database(tmp_path / "upgraded.db", recorded=[*FLOOR_IDS, earlier])
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE earlier_release_extension (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO earlier_release_extension VALUES ('kept')")
    connection.close()
    result = check_sqlite_file(CHAIN, path)
    assert result.state is CheckState.BEHIND
    assert result.floor == "marketplace 0.3.0"
    assert result.set_aside == (earlier,)

    report = migrate_storefront_database(CHAIN, path)

    assert report.adopted is True
    assert report.set_aside == (earlier,)
    assert report.applied == tuple(migration.id for migration in CHAIN.migrations)
    assert check_sqlite_file(CHAIN, path).state is CheckState.COMPATIBLE
    assert _recorded(path) == sorted(CHAIN.ids)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT id FROM earlier_release_extension").fetchall() == [
            ("kept",)
        ]
    finally:
        connection.close()


def test_a_database_missing_a_floor_id_is_refused_as_older_or_shared(tmp_path) -> None:
    missing = FLOOR_IDS[-1]
    path = _release_database(
        tmp_path / "older.db", recorded=[i for i in FLOOR_IDS if i != missing]
    )
    before = path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_storefront_database(CHAIN, path)

    assert refused.value.result.cause is UnsupportedCause.OLDER_OR_SHARED
    assert refused.value.result.missing == (missing,)
    message = str(refused.value)
    assert "upgrade it through marketplace 0.3.0 first" in message
    assert "apicredits-storefront-migrate" in message
    assert path.read_bytes() == before


def test_a_ledger_recording_none_of_the_floor_is_refused_as_not_the_storefronts(
    tmp_path,
) -> None:
    path = _release_database(tmp_path / "other.db", recorded=["20250101_001_another_service"])
    before = path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_storefront_database(CHAIN, path)

    assert refused.value.result.cause is UnsupportedCause.NOT_THIS_CHAIN
    assert "was not built by `apicredits-storefront-migrate`" in str(refused.value)
    assert "upgrade" not in str(refused.value)
    assert path.read_bytes() == before


def test_tables_without_a_ledger_are_refused_and_unchanged(tmp_path) -> None:
    path = tmp_path / "unledgered.db"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE listings (listing_id TEXT PRIMARY KEY)")
    connection.close()
    before = path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_storefront_database(CHAIN, path)

    assert refused.value.result.state is CheckState.UNSUPPORTED
    assert refused.value.result.cause is UnsupportedCause.NOT_THIS_CHAIN
    assert path.read_bytes() == before
    assert "schema_migrations" not in _snapshot(path)["tables"]


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

        result = check(failing, SqliteMigrationConnection(connection))
        assert result.state is CheckState.BEHIND
        assert result.pending == ("29990101_001_fails",)
        assert "half_done" not in schema_snapshot(connection)["tables"]
    finally:
        connection.close()
