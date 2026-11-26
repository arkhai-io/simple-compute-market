"""The SQLAlchemy adapter owes and performs a compaction only on SQLite.

No database other than SQLite is at hand in this suite, so the connection to one
is doubled: what is shown is that the adapter issues nothing to it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from market_schema_migrations.sqlalchemy_adapter import SqlAlchemyMigrationConnection


def test_a_database_other_than_sqlite_owes_and_runs_no_compaction() -> None:
    connection = MagicMock()
    connection.dialect.name = "postgresql"
    adapter = SqlAlchemyMigrationConnection(connection)

    adapter.owe_compaction()
    owed = adapter.compaction_owed()
    adapter.compact()

    assert owed is False
    assert connection.method_calls == []
