"""Compute provisioning's migration command and startup check, over SQLite.

The command applies the chain, adopting a v0.3.0 database at its baseline and
refusing, applying nothing, a database ahead of the chain or older than that
release. The startup check reads the database without changing it and accepts
only one recording exactly the chain's migrations, refusing any other with the
migration command and the migration IDs that differ. ``--check`` reports the
check's result and exits successfully only for a compatible database.

External boundary: file-backed SQLite in a temp directory, or a shared
in-memory database; the command runs through its real entry point with its
settings loaded by the service's own loader. No application.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from market_schema_migrations import CheckState, MigrationRefused, schema_snapshot

from compute_provisioning_service import config as config_module
from compute_provisioning_service.config import settings
from compute_provisioning_service.db import migrate
from compute_provisioning_service.db.database import (
    IncompatibleDatabase,
    check_database,
    migrate_database,
    require_compatible_database,
)
from compute_provisioning_service.db.migrations import CHAIN, FLOOR_IDS

from .floor_database import create_floor_database

_COMMAND = "compute-provisioning-migrate"
_LATER_IDS = tuple(m.id for m in CHAIN.migrations)
_UNKNOWN_ID = "20990101_001_written_by_a_newer_image"


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _file_engine(path: Path):
    return create_engine(f"sqlite:///{path}")


def _recorded(engine) -> list[str]:
    with engine.connect() as connection:
        return sorted(row[0] for row in connection.execute(text("SELECT id FROM schema_migrations")))


def _schema(engine) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ))]


def _refusal(engine) -> str:
    with pytest.raises(IncompatibleDatabase) as refused:
        require_compatible_database(engine)
    message = str(refused.value)
    assert f"`{_COMMAND}`" in message
    assert "migrate-job.yaml" not in message
    return message


# ---------------------------------------------------------------------------
# The migration command's chain
# ---------------------------------------------------------------------------


def test_a_fresh_database_is_migrated_compatible_and_holds_no_pool():
    engine = _sqlite_memory_engine()

    report = migrate_database(engine)

    assert report.applied == CHAIN.ids
    assert check_database(engine).state is CheckState.COMPATIBLE
    require_compatible_database(engine)
    with engine.connect() as connection:
        for table in ("resource_pools", "ansible_pool_configs", "hosts"):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_a_rerun_changes_nothing():
    engine = _sqlite_memory_engine()
    migrate_database(engine)
    schema, recorded = _schema(engine), _recorded(engine)

    assert migrate_database(engine).applied == ()

    assert _schema(engine) == schema
    assert _recorded(engine) == recorded == sorted(CHAIN.ids)


def test_a_v0_3_0_database_is_behind_with_its_adoption_pending_then_adopted(tmp_path):
    engine = _file_engine(create_floor_database(tmp_path / "provisioning.db"))

    result = check_database(engine)
    assert result.state is CheckState.BEHIND
    assert result.adopting == CHAIN.baseline_ids
    assert result.pending == _LATER_IDS
    message = _refusal(engine)
    assert "supported baseline is to be adopted" in message
    for migration_id in (*CHAIN.baseline_ids, *_LATER_IDS):
        assert migration_id in message

    report = migrate_database(engine)

    assert report.adopted
    assert report.applied == _LATER_IDS
    assert _recorded(engine) == sorted(CHAIN.ids)
    require_compatible_database(engine)


def test_a_database_older_than_v0_3_0_is_refused_and_left_unchanged(tmp_path):
    """It lacks the release's last migration: no step of the chain reaches it."""
    engine = _file_engine(create_floor_database(tmp_path / "provisioning.db"))
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"), {"id": FLOOR_IDS[-1]}
        )
    schema, recorded = _schema(engine), _recorded(engine)

    result = check_database(engine)
    assert result.state is CheckState.UNSUPPORTED
    assert result.missing == (FLOOR_IDS[-1],)
    assert FLOOR_IDS[-1] in _refusal(engine)
    with pytest.raises(MigrationRefused) as refused:
        migrate_database(engine)

    assert "fresh database" in str(refused.value)
    assert FLOOR_IDS[-1] in str(refused.value)
    assert _schema(engine) == schema
    assert _recorded(engine) == recorded


def test_tables_with_no_migration_record_are_refused_and_left_unchanged():
    """A database from before the service recorded migrations at all."""
    engine = _sqlite_memory_engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE hosts (name VARCHAR PRIMARY KEY)"))

    assert check_database(engine).state is CheckState.UNSUPPORTED
    assert "fresh database" in _refusal(engine)
    with pytest.raises(MigrationRefused) as refused:
        migrate_database(engine)

    assert f"`{_COMMAND}`" in str(refused.value)
    assert set(inspect(engine).get_table_names()) == {"hosts"}


def test_a_database_behind_the_chain_is_refused_at_startup_naming_what_is_pending():
    engine = _sqlite_memory_engine()
    migrate_database(engine)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"), {"id": CHAIN.ids[-1]}
        )
    schema = _schema(engine)

    result = check_database(engine)
    assert result.state is CheckState.BEHIND
    assert result.pending == (CHAIN.ids[-1],)
    assert CHAIN.ids[-1] in _refusal(engine)
    assert _schema(engine) == schema

    assert migrate_database(engine).applied == (CHAIN.ids[-1],)
    require_compatible_database(engine)


@pytest.mark.parametrize("also_missing", [False, True], ids=["unknown", "unknown-and-missing"])
def test_a_database_ahead_of_the_chain_is_refused_and_left_unchanged(also_missing):
    """An unknown migration takes precedence over pending ones: this image
    cannot vouch for the database, and neither the check nor the command
    changes it."""
    engine = _sqlite_memory_engine()
    migrate_database(engine)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": _UNKNOWN_ID}
        )
        if also_missing:
            connection.execute(
                text("DELETE FROM schema_migrations WHERE id = :id"), {"id": CHAIN.ids[-1]}
            )
    schema, recorded = _schema(engine), _recorded(engine)

    result = check_database(engine)
    assert result.state is CheckState.AHEAD
    assert result.unknown == (_UNKNOWN_ID,)
    assert result.pending == ((CHAIN.ids[-1],) if also_missing else ())
    message = _refusal(engine)
    assert _UNKNOWN_ID in message
    assert (f"It also lacks migrations {CHAIN.ids[-1]}" in message) is also_missing
    with pytest.raises(MigrationRefused):
        migrate_database(engine)

    assert _schema(engine) == schema
    assert _recorded(engine) == recorded


def test_a_missing_database_is_absent_and_the_check_creates_no_file(tmp_path):
    path = tmp_path / "data" / "provisioning.db"
    engine = _file_engine(path)

    assert check_database(engine).state is CheckState.ABSENT
    assert "found no migrated database" in _refusal(engine)

    assert not path.exists()
    assert not path.parent.exists()


# ---------------------------------------------------------------------------
# The placement key, the one schema change after the baseline
# ---------------------------------------------------------------------------

_RESERVATION_COLUMNS = (
    "capacity_reservation_id, units, state, offering_mode, hold_expires_at, "
    "executor_target, lease_start_utc, lease_end_utc, release_requested_at, "
    "released_at"
)

_V0_3_0_RESERVATIONS = (
    ("r-leased", 1, "leased", "vm", None, "tenant-leased",
     "2026-11-01T00:00:00+00:00", "2026-12-01T00:00:00+00:00", None, None),
    ("r-releasing", 2, "releasing", "vm", None, "tenant-releasing",
     "2026-10-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00",
     "2026-11-01T00:00:05+00:00", None),
    ("r-released", 1, "released", "bare_metal", "2026-08-31T00:05:00+00:00",
     "host-released",
     "2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00",
     "2026-10-01T00:00:05+00:00", "2026-10-01T00:10:00+00:00"),
)


def _v0_3_0_database_with_reservations(tmp_path: Path):
    engine = _file_engine(create_floor_database(tmp_path / "provisioning.db"))
    with engine.begin() as connection:
        for row in _V0_3_0_RESERVATIONS:
            connection.execute(
                text(
                    f"INSERT INTO capacity_reservations ({_RESERVATION_COLUMNS}) "
                    "VALUES (:id, :units, :state, :mode, :hold, :target, "
                    ":start, :end, :requested, :released)"
                ),
                dict(zip(
                    ("id", "units", "state", "mode", "hold", "target", "start",
                     "end", "requested", "released"),
                    row,
                )),
            )
    return engine


def _placement_rows(engine) -> set[tuple]:
    with engine.connect() as connection:
        return {
            tuple(row)
            for row in connection.execute(text(
                f"SELECT {_RESERVATION_COLUMNS}, placement_key, placement_request "
                "FROM capacity_reservations"
            ))
        }


def test_v0_3_0_reservations_migrate_with_no_placement_key(tmp_path):
    """No backfill: every reservation migrates recording no placement key,
    its state, window and release fields unchanged, and a rerun changes
    nothing."""
    engine = _v0_3_0_database_with_reservations(tmp_path)
    expected = {row + (None, None) for row in _V0_3_0_RESERVATIONS}

    migrate_database(engine)

    assert _placement_rows(engine) == expected
    migrate_database(engine)
    assert _placement_rows(engine) == expected


def test_the_placement_key_is_uniquely_indexed(tmp_path):
    engine = _v0_3_0_database_with_reservations(tmp_path)

    migrate_database(engine)

    indexes = {
        index["name"]: index
        for index in inspect(engine).get_indexes("capacity_reservations")
    }
    placement = indexes["ix_capacity_reservations_placement_key"]
    assert placement["column_names"] == ["placement_key"]
    assert placement["unique"]
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE capacity_reservations SET placement_key = 'neg-1:settlement' "
            "WHERE capacity_reservation_id = 'r-leased'"
        ))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE capacity_reservations SET placement_key = 'neg-1:settlement' "
                "WHERE capacity_reservation_id = 'r-released'"
            ))


# ---------------------------------------------------------------------------
# The command's entry point and its --check mode
# ---------------------------------------------------------------------------


def _run_command(monkeypatch, database: Path, *arguments: str) -> int:
    """Run ``compute-provisioning-migrate`` against ``database``; its exit status."""
    monkeypatch.setenv("PROVISIONING_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setattr(
        settings, "_source", config_module._load_bootstrap(os.environ).settings
    )
    try:
        migrate.main(list(arguments))
    except SystemExit as exit_:
        return int(exit_.code or 0)
    return 0


def _file_snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def test_check_exits_unsuccessfully_on_a_behind_database_listing_its_pending_migrations(
    tmp_path, monkeypatch, capsys,
):
    database = create_floor_database(tmp_path / "provisioning.db")
    before = database.read_bytes()

    assert _run_command(monkeypatch, database, "--check") == 1

    output = capsys.readouterr()
    assert "behind" in output.out
    for migration_id in _LATER_IDS:
        assert migration_id in output.out
    assert f"`{_COMMAND}`" in output.err
    assert database.read_bytes() == before


def test_check_exits_unsuccessfully_on_a_missing_database_and_creates_none(
    tmp_path, monkeypatch, capsys,
):
    database = tmp_path / "provisioning.db"

    assert _run_command(monkeypatch, database, "--check") == 1

    assert "absent" in capsys.readouterr().out
    assert not database.exists()


def test_check_exits_successfully_once_the_command_has_migrated(tmp_path, monkeypatch, capsys):
    database = create_floor_database(tmp_path / "provisioning.db")

    assert _run_command(monkeypatch, database) == 0
    migrated = _file_snapshot(database)
    assert _run_command(monkeypatch, database) == 0
    assert _run_command(monkeypatch, database, "--check") == 0

    assert "compatible" in capsys.readouterr().out
    assert _file_snapshot(database) == migrated


def test_the_command_exits_unsuccessfully_on_an_ahead_database_changing_nothing(
    tmp_path, monkeypatch, capsys,
):
    database = tmp_path / "provisioning.db"
    assert _run_command(monkeypatch, database) == 0
    engine = _file_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": _UNKNOWN_ID}
        )
    engine.dispose()
    before = database.read_bytes()

    assert _run_command(monkeypatch, database) == 1
    assert _run_command(monkeypatch, database, "--check") == 1

    output = capsys.readouterr()
    assert _UNKNOWN_ID in output.err
    assert "ahead" in output.out
    assert database.read_bytes() == before
