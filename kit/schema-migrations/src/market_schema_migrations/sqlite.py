"""The engine over a standard-library ``sqlite3`` connection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from market_schema_migrations.engine import LEDGER_DDL, LEDGER_TABLE, Chain, check
from market_schema_migrations.result import CheckResult, CheckState


class SqliteMigrationConnection:
    """Adapts a ``sqlite3`` connection; migrations receive the connection itself.

    Each transaction is an explicit ``BEGIN`` ended by ``COMMIT`` or
    ``ROLLBACK`` statements, so a migration's DDL commits or rolls back with its
    record: SQLite's DDL is transactional, and the driver neither commits
    before DDL nor opens a transaction for it on its own. Statements rather
    than the driver's ``commit()`` end it because under ``autocommit=True`` that
    method does nothing. The connection must be outside a transaction when the
    engine starts one, which holds for the driver's default transaction
    control, ``isolation_level=None``, and ``autocommit=True``.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def native(self) -> sqlite3.Connection:
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._connection.in_transaction:
            raise RuntimeError(
                "the migration engine opens its own transactions; "
                "the sqlite3 connection is already inside one"
            )
        self._connection.execute("BEGIN")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")

    def table_names(self) -> set[str]:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {str(row[0]) for row in rows}

    def recorded_ids(self) -> list[str]:
        rows = self._connection.execute(f"SELECT id FROM {LEDGER_TABLE}").fetchall()
        return [str(row[0]) for row in rows]

    def create_ledger(self) -> None:
        self._connection.execute(LEDGER_DDL)

    def record(self, ids: Iterable[str]) -> None:
        self._connection.executemany(
            f"INSERT INTO {LEDGER_TABLE} (id) VALUES (?)", [(i,) for i in ids]
        )

    def forget(self, ids: Iterable[str]) -> None:
        self._connection.executemany(
            f"DELETE FROM {LEDGER_TABLE} WHERE id = ?", [(i,) for i in ids]
        )


def connect_read_only(path: str | Path) -> sqlite3.Connection:
    """Open an existing database file so that nothing can write to it.

    SQLite's read-only mode never creates the file: opening a path that does
    not exist fails rather than leaving an empty database behind.
    """

    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def check_sqlite_file(chain: Chain[Any], path: str | Path) -> CheckResult:
    """Check the database at ``path`` read-only; no file is *absent*.

    The chain's migrations may take any kind of connection, since the check
    runs none of them.
    """

    if not Path(path).is_file():
        return CheckResult(CheckState.ABSENT)
    connection = connect_read_only(path)
    try:
        return check(chain, SqliteMigrationConnection(connection))
    finally:
        connection.close()
