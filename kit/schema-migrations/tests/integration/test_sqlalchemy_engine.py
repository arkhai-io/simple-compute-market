"""The engine against real SQLite databases through the SQLAlchemy adapter."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.pool import StaticPool

from market_schema_migrations import (
    Chain,
    CheckState,
    Migration,
    MigrationFailed,
    MigrationRefused,
    migrate,
    schema_snapshot,
)
from market_schema_migrations.sqlalchemy_adapter import (
    SqlAlchemyMigrationConnection,
    check_engine,
)


def _create_hosts(connection: Connection) -> None:
    connection.execute(text("CREATE TABLE hosts (host_id VARCHAR PRIMARY KEY)"))


def _add_port(connection: Connection) -> None:
    connection.execute(text("ALTER TABLE hosts ADD COLUMN port INTEGER"))


def _ddl_then_fail(connection: Connection) -> None:
    connection.execute(text("CREATE TABLE half_done (id INTEGER)"))
    connection.execute(text("ALTER TABLE hosts ADD COLUMN half_column VARCHAR"))
    raise RuntimeError("the migration broke")


def _chain(*migrations: Migration[Connection]) -> Chain[Connection]:
    return Chain(
        service="example-service",
        command="example-service-migrate",
        baselines=(Migration("base_hosts", _create_hosts),),
        migrations=migrations or (Migration("later_port", _add_port),),
        floor_ids=("floor_hosts",),
    )


def _recorded(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT id FROM schema_migrations")}
    finally:
        connection.close()


def _snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def test_a_fresh_file_database_migrates_and_checks_compatible(tmp_path: Path) -> None:
    path = tmp_path / "service.db"
    engine = create_engine(f"sqlite:///{path}")

    with engine.connect() as connection:
        report = migrate(_chain(), SqlAlchemyMigrationConnection(connection))

    assert report.applied == ("base_hosts", "later_port")
    assert _recorded(path) == {"base_hosts", "later_port"}
    assert check_engine(_chain(), engine).state is CheckState.COMPATIBLE


def test_ddl_before_a_failure_is_rolled_back_with_the_migration(tmp_path: Path) -> None:
    path = tmp_path / "service.db"
    engine = create_engine(f"sqlite:///{path}")
    chain = _chain(Migration("later_port", _add_port), Migration("later_broken", _ddl_then_fail))

    with engine.connect() as connection:
        with pytest.raises(MigrationFailed) as failed:
            migrate(chain, SqlAlchemyMigrationConnection(connection))

    assert failed.value.migration_id == "later_broken"
    assert _recorded(path) == {"base_hosts", "later_port"}
    snapshot = _snapshot(path)
    assert "half_done" not in snapshot["tables"]
    assert [c["name"] for c in snapshot["tables"]["hosts"]["columns"]] == ["host_id", "port"]
    result = check_engine(chain, engine)
    assert result.state is CheckState.BEHIND
    assert result.pending == ("later_broken",)


def test_a_floor_database_is_adopted(tmp_path: Path) -> None:
    path = tmp_path / "service.db"
    seed = sqlite3.connect(path)
    seed.executescript(
        """
        CREATE TABLE schema_migrations (id VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE hosts (host_id VARCHAR PRIMARY KEY);
        INSERT INTO schema_migrations (id) VALUES ('floor_hosts');
        """
    )
    seed.close()
    engine = create_engine(f"sqlite:///{path}")

    with engine.connect() as connection:
        report = migrate(_chain(), SqlAlchemyMigrationConnection(connection))

    assert report.adopted is True
    assert report.applied == ("later_port",)
    assert _recorded(path) == {"base_hosts", "later_port"}


def test_an_ahead_database_is_refused_and_left_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "service.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        migrate(_chain(), SqlAlchemyMigrationConnection(connection))
    newer = sqlite3.connect(path)
    newer.execute("INSERT INTO schema_migrations (id) VALUES ('newer')")
    newer.commit()
    newer.close()
    before = (_snapshot(path), _recorded(path))

    with engine.connect() as connection:
        with pytest.raises(MigrationRefused) as refused:
            migrate(_chain(), SqlAlchemyMigrationConnection(connection))

    assert refused.value.result.unknown == ("newer",)
    assert (_snapshot(path), _recorded(path)) == before


def test_checking_a_missing_file_is_absent_and_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    engine = create_engine(f"sqlite:///{path}")

    assert check_engine(_chain(), engine).state is CheckState.ABSENT
    assert not path.exists()


def test_an_in_memory_database_is_checked_through_its_engine() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    assert check_engine(_chain(), engine).state is CheckState.ABSENT

    with engine.connect() as connection:
        migrate(_chain(), SqlAlchemyMigrationConnection(connection))

    assert check_engine(_chain(), engine).state is CheckState.COMPATIBLE
