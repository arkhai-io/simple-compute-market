"""The API-credit storefront's chain: its baselines, and the refusal of every
database it did not build.

Library integration: real SQLite files migrated through the chain's engine, no
application. The chain names no floor: no API-credit database from before its
baseline is supported.
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
    check,
    migrate,
    schema_snapshot,
)

from apicredits_storefront.utils.migrations import CHAIN, migrate_storefront_database

_FLOOR = Path(__file__).resolve().parents[1] / "fixtures" / "v0_3_0_floor"
# SQLite records the sequence table it creates for an AUTOINCREMENT key among
# the stored DDL, but refuses to create it by name.
_SEQUENCE_TABLE = "CREATE TABLE sqlite_sequence(name,seq);"


def _snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def _release_database(path: Path) -> Path:
    """A database as the v0.3.0 release's API-credit storefront left it."""
    ddl = (_FLOOR / "ddl.sql").read_text(encoding="utf-8").replace(_SEQUENCE_TABLE, "")
    ids = json.loads((_FLOOR / "floor_ids.json").read_text(encoding="utf-8"))
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

    report = migrate_storefront_database(path)

    assert report.adopted is False
    assert report.applied == CHAIN.ids
    before = path.read_bytes()
    assert migrate_storefront_database(path).applied == ()
    assert path.read_bytes() == before


def test_a_database_from_the_release_is_refused_and_unchanged(tmp_path) -> None:
    path = _release_database(tmp_path / "release.db")
    before = path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_storefront_database(path)

    assert refused.value.result.state is CheckState.UNSUPPORTED
    assert "apicredits-storefront-migrate" in str(refused.value)
    assert path.read_bytes() == before


def test_tables_without_a_ledger_are_refused_and_unchanged(tmp_path) -> None:
    path = tmp_path / "unledgered.db"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE listings (listing_id TEXT PRIMARY KEY)")
    connection.close()
    before = path.read_bytes()

    with pytest.raises(MigrationRefused) as refused:
        migrate_storefront_database(path)

    assert refused.value.result.state is CheckState.UNSUPPORTED
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
