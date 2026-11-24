"""The engine over a SQLAlchemy connection.

Only a consumer holding SQLAlchemy imports this module, through the package's
``sqlalchemy`` extra; nothing else in the package imports it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, Engine, inspect, text

from market_schema_migrations.engine import LEDGER_DDL, LEDGER_TABLE, Chain, check
from market_schema_migrations.result import CheckResult
from market_schema_migrations.sqlite import check_sqlite_file


class SqlAlchemyMigrationConnection:
    """Adapts a SQLAlchemy connection; migrations receive the connection itself.

    On SQLite each transaction also issues an explicit ``BEGIN``: the Python
    driver opens a transaction only before a data change, so DDL a migration
    runs first would otherwise commit on its own and survive the migration's
    failure. The connection must be outside a transaction when the engine
    starts one.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    @property
    def native(self) -> Connection:
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._connection.begin():
            if self._connection.dialect.name == "sqlite":
                self._connection.exec_driver_sql("BEGIN")
            yield

    def table_names(self) -> set[str]:
        return set(inspect(self._connection).get_table_names())

    def recorded_ids(self) -> list[str]:
        rows = self._connection.execute(text(f"SELECT id FROM {LEDGER_TABLE}"))
        return [str(value) for value in rows.scalars()]

    def create_ledger(self) -> None:
        self._connection.execute(text(LEDGER_DDL))

    def record(self, ids: Iterable[str]) -> None:
        rows = [{"id": i} for i in ids]
        if rows:
            self._connection.execute(
                text(f"INSERT INTO {LEDGER_TABLE} (id) VALUES (:id)"), rows
            )

    def forget(self, ids: Iterable[str]) -> None:
        rows = [{"id": i} for i in ids]
        if rows:
            self._connection.execute(
                text(f"DELETE FROM {LEDGER_TABLE} WHERE id = :id"), rows
            )


def check_engine(chain: Chain[Any], engine: Engine) -> CheckResult:
    """Check the database ``engine`` names without changing or creating it.

    A file-backed SQLite database is read through a read-only connection of its
    own, so a missing file is *absent* and is not created. Any other database,
    an in-memory one included, is read through the engine; the check only
    reads.
    """

    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        return check_sqlite_file(chain, url.database)
    with engine.connect() as connection:
        return check(chain, SqlAlchemyMigrationConnection(connection))
