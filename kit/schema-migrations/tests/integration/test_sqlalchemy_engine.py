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
    Floor,
    Migration,
    MigrationFailed,
    MigrationRefused,
    UnsupportedCause,
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


def _chain(
    *migrations: Migration[Connection],
    floor: Floor = Floor("example 1.0.0", ("floor_hosts",)),
) -> Chain[Connection]:
    return Chain(
        service="example-service",
        command="example-service-migrate",
        baselines=(Migration("base_hosts", _create_hosts),),
        migrations=migrations or (Migration("later_port", _add_port),),
        floor=floor,
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


def _seed_floor_database(path: Path, *extra_ids: str) -> None:
    seed = sqlite3.connect(path)
    seed.executescript(
        """
        CREATE TABLE schema_migrations (id VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE hosts (host_id VARCHAR PRIMARY KEY);
        INSERT INTO hosts VALUES ('h1');
        INSERT INTO schema_migrations (id) VALUES ('floor_hosts');
        """
    )
    for migration_id in extra_ids:
        seed.execute("INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,))
    seed.commit()
    seed.close()


def test_a_floor_database_is_adopted(tmp_path: Path) -> None:
    path = tmp_path / "service.db"
    _seed_floor_database(path)
    engine = create_engine(f"sqlite:///{path}")

    with engine.connect() as connection:
        report = migrate(_chain(), SqlAlchemyMigrationConnection(connection))

    assert report.adopted is True
    assert report.applied == ("later_port",)
    assert _recorded(path) == {"base_hosts", "later_port"}


def test_a_floor_database_carrying_earlier_records_is_adopted_with_them_forgotten(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.db"
    _seed_floor_database(path, "retired_b", "retired_a")
    seed = sqlite3.connect(path)
    seed.execute("CREATE TABLE retired_lifecycle (id TEXT)")
    seed.execute("INSERT INTO retired_lifecycle VALUES ('kept')")
    seed.commit()
    seed.close()
    engine = create_engine(f"sqlite:///{path}")

    with engine.connect() as connection:
        report = migrate(_chain(), SqlAlchemyMigrationConnection(connection))

    assert report.adopted is True
    assert report.applied == ("later_port",)
    assert report.set_aside == ("retired_a", "retired_b")
    assert _recorded(path) == {"base_hosts", "later_port"}
    rows = sqlite3.connect(path)
    try:
        assert rows.execute("SELECT host_id FROM hosts").fetchall() == [("h1",)]
        assert rows.execute("SELECT id FROM retired_lifecycle").fetchall() == [("kept",)]
    finally:
        rows.close()
    before = path.read_bytes()
    with engine.connect() as connection:
        assert migrate(_chain(), SqlAlchemyMigrationConnection(connection)).applied == ()
    assert path.read_bytes() == before


def test_the_check_of_a_floor_database_carrying_earlier_records_changes_nothing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.db"
    _seed_floor_database(path, "retired_1")
    before = path.read_bytes()
    siblings = set(tmp_path.iterdir())

    result = check_engine(_chain(), create_engine(f"sqlite:///{path}"))

    assert result.state is CheckState.BEHIND
    assert result.set_aside == ("retired_1",)
    assert result.floor == "example 1.0.0"
    assert path.read_bytes() == before
    assert set(tmp_path.iterdir()) == siblings


def test_a_zero_floor_chain_builds_a_fresh_database_and_refuses_a_foreign_one(
    tmp_path: Path,
) -> None:
    chain = _chain(floor=Floor("0.0.0"))
    fresh = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    with fresh.connect() as connection:
        assert migrate(chain, SqlAlchemyMigrationConnection(connection)).applied == chain.ids
    assert check_engine(chain, fresh).state is CheckState.COMPATIBLE

    path = tmp_path / "service.db"
    _seed_floor_database(path)
    before = path.read_bytes()
    engine = create_engine(f"sqlite:///{path}")

    with engine.connect() as connection:
        with pytest.raises(MigrationRefused) as refused:
            migrate(chain, SqlAlchemyMigrationConnection(connection))

    assert refused.value.result.cause is UnsupportedCause.NOT_THIS_CHAIN
    engine.dispose()
    assert path.read_bytes() == before


def test_an_ahead_database_is_refused_and_left_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "service.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        migrate(_chain(), SqlAlchemyMigrationConnection(connection))
    newer = sqlite3.connect(path)
    newer.execute("INSERT INTO schema_migrations (id) VALUES ('newer')")
    newer.commit()
    newer.close()
    engine.dispose()
    before = path.read_bytes()

    with engine.connect() as connection:
        with pytest.raises(MigrationRefused) as refused:
            migrate(_chain(), SqlAlchemyMigrationConnection(connection))

    assert refused.value.result.unknown == ("newer",)
    engine.dispose()
    assert path.read_bytes() == before


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
