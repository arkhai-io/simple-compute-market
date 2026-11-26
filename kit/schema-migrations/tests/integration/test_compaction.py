"""A run that applied a migration freeing space compacts the database after it.

Library integration over real SQLite files, through both adapters and, for the
``sqlite3`` adapter, under every transaction control: a chain whose later
migration drops a populated table, declared as freeing space or not. A dropped
table's pages stay in the file, on SQLite's free list, until it is compacted.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text

from market_schema_migrations import (
    Chain,
    CheckState,
    CompactionFailed,
    MigrateReport,
    Migration,
    SqliteMigrationConnection,
    check_sqlite_file,
    migrate,
)
from market_schema_migrations.sqlalchemy_adapter import SqlAlchemyMigrationConnection

ROWS = 400
ROW_BYTES = 4_000

# Each transaction control the sqlite3 driver offers.
SQLITE3_CONTROLS: dict[str, Callable[[Path], sqlite3.Connection]] = {
    "default": lambda path: sqlite3.connect(path),
    "isolation_level=None": lambda path: sqlite3.connect(path, isolation_level=None),
    "autocommit=True": lambda path: sqlite3.connect(path, autocommit=True),
}


def _execute(connection: Any, statement: str) -> None:
    if isinstance(connection, sqlite3.Connection):
        connection.execute(statement)
    else:
        connection.execute(text(statement))


def _create(connection: Any) -> None:
    _execute(connection, "CREATE TABLE kept (id INTEGER PRIMARY KEY)")
    _execute(connection, "CREATE TABLE dropped (id INTEGER PRIMARY KEY, payload BLOB)")


def _drop(connection: Any) -> None:
    _execute(connection, "DROP TABLE dropped")


def _chain(*, frees_space: bool) -> Chain[Any]:
    return Chain(
        service="example-service",
        command="example-service-migrate",
        baselines=(Migration("base_tables", _create),),
        migrations=(Migration("drop_dropped", _drop, frees_space=frees_space),),
    )


def _populated(path: Path) -> None:
    """A database at the baseline, its doomed table holding rows."""

    baseline = Chain(
        service="example-service",
        command="example-service-migrate",
        baselines=(Migration("base_tables", _create),),
    )
    connection = sqlite3.connect(path)
    try:
        migrate(baseline, SqliteMigrationConnection(connection))
        connection.executemany(
            "INSERT INTO dropped (payload) VALUES (?)",
            [(bytes(ROW_BYTES),) for _ in range(ROWS)],
        )
        connection.commit()
    finally:
        connection.close()


def _run_sqlite3(
    control: str, adapter: type[SqliteMigrationConnection] = SqliteMigrationConnection
) -> Callable[[Path, Chain[Any]], MigrateReport]:
    def run(path: Path, chain: Chain[Any]) -> MigrateReport:
        connection = SQLITE3_CONTROLS[control](path)
        try:
            return migrate(chain, adapter(connection))
        finally:
            connection.close()

    return run


def _run_sqlalchemy(
    adapter: type[SqlAlchemyMigrationConnection] = SqlAlchemyMigrationConnection,
) -> Callable[[Path, Chain[Any]], MigrateReport]:
    def run(path: Path, chain: Chain[Any]) -> MigrateReport:
        engine: Engine = create_engine(f"sqlite:///{path}")
        try:
            with engine.connect() as connection:
                return migrate(chain, adapter(connection))
        finally:
            engine.dispose()

    return run


RUNS: dict[str, Callable[[Path, Chain[Any]], MigrateReport]] = {
    **{f"sqlite3 {control}": _run_sqlite3(control) for control in SQLITE3_CONTROLS},
    "sqlalchemy": _run_sqlalchemy(),
}


def _pragma(path: Path, name: str) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f"PRAGMA {name}").fetchone()[0])
    finally:
        connection.close()


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(name) for (name,) in rows}
    finally:
        connection.close()


@pytest.mark.parametrize("run", sorted(RUNS))
def test_a_chain_dropping_a_populated_table_that_frees_space_leaves_a_smaller_file(
    tmp_path: Path, run: str
) -> None:
    path = tmp_path / "service.sqlite3"
    _populated(path)
    before = path.stat().st_size

    report = RUNS[run](path, _chain(frees_space=True))

    assert report.applied == ("drop_dropped",) and report.compacted
    assert "dropped" not in _tables(path)
    assert path.stat().st_size < before - ROWS * ROW_BYTES // 2
    assert _pragma(path, "freelist_count") == 0
    assert _pragma(path, "user_version") == 0


@pytest.mark.parametrize("run", sorted(RUNS))
def test_a_chain_with_no_migration_freeing_space_does_not_compact(
    tmp_path: Path, run: str
) -> None:
    path = tmp_path / "service.sqlite3"
    _populated(path)

    report = RUNS[run](path, _chain(frees_space=False))

    assert report.applied == ("drop_dropped",) and not report.compacted
    assert "dropped" not in _tables(path)
    assert _pragma(path, "freelist_count") > 0


@pytest.mark.parametrize("run", sorted(RUNS))
def test_a_run_that_applies_nothing_and_owes_nothing_does_not_compact(
    tmp_path: Path, run: str
) -> None:
    path = tmp_path / "service.sqlite3"
    _populated(path)
    RUNS[run](path, _chain(frees_space=True))

    assert RUNS[run](path, _chain(frees_space=True)).compacted is False


class _FailingOnceSqlite3(SqliteMigrationConnection):
    """A connection whose first compaction fails, as when the volume is full."""

    failed = False

    def compact(self) -> None:
        if not type(self).failed:
            type(self).failed = True
            raise sqlite3.OperationalError("database or disk is full")
        super().compact()


class _FailingOnceSqlAlchemy(SqlAlchemyMigrationConnection):
    """A connection whose first compaction fails, as when the volume is full."""

    failed = False

    def compact(self) -> None:
        if not type(self).failed:
            type(self).failed = True
            raise sqlite3.OperationalError("database or disk is full")
        super().compact()


@pytest.mark.parametrize(
    "run",
    [_run_sqlite3("default", _FailingOnceSqlite3), _run_sqlalchemy(_FailingOnceSqlAlchemy)],
    ids=["sqlite3", "sqlalchemy"],
)
def test_a_compaction_that_fails_stays_owed_and_the_next_run_performs_it(
    tmp_path: Path, run: Callable[[Path, Chain[Any]], MigrateReport]
) -> None:
    _FailingOnceSqlite3.failed = _FailingOnceSqlAlchemy.failed = False
    path = tmp_path / "service.sqlite3"
    _populated(path)

    with pytest.raises(CompactionFailed, match="example-service-migrate"):
        run(path, _chain(frees_space=True))
    assert check_sqlite_file(_chain(frees_space=True), path).compatible
    assert _pragma(path, "user_version") == 1 and _pragma(path, "freelist_count") > 0

    report = run(path, _chain(frees_space=True))

    assert report.applied == () and report.compacted
    assert _pragma(path, "user_version") == 0 and _pragma(path, "freelist_count") == 0


def test_the_check_lists_the_pending_migration_and_neither_drops_nor_compacts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.sqlite3"
    _populated(path)
    before = path.read_bytes()

    result = check_sqlite_file(_chain(frees_space=True), path)

    assert result.state is CheckState.BEHIND and result.pending == ("drop_dropped",)
    assert path.read_bytes() == before
    assert "dropped" in _tables(path)


@pytest.mark.parametrize("isolation_level", [None, "AUTOCOMMIT"])
def test_the_sqlalchemy_connection_keeps_its_isolation_level_after_compacting(
    tmp_path: Path, isolation_level: str | None
) -> None:
    path = tmp_path / "service.sqlite3"
    _populated(path)
    options = {} if isolation_level is None else {"isolation_level": isolation_level}
    engine = create_engine(f"sqlite:///{path}", **options)
    try:
        with engine.connect() as connection:
            driver = connection.connection.driver_connection
            assert isinstance(driver, sqlite3.Connection)
            level = driver.isolation_level

            report = migrate(_chain(frees_space=True), SqlAlchemyMigrationConnection(connection))

            assert report.compacted
            assert driver.isolation_level == level
            assert not connection.in_transaction()
    finally:
        engine.dispose()
