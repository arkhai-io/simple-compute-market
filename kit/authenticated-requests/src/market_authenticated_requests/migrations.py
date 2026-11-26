"""The replay table, as migrations each authority's chain composes.

The table belongs to this kit: an authority adds the migration for its adapter to
its own chain, in the chain's fixed order, and holds the table in its own
database. An authority whose schema Alembic migrates mirrors the same statements
in a revision of its own (:func:`replay_table_statements`). No store creates it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from market_schema_migrations import Migration
from request_replay import SqliteReplayStore
from request_replay.ddl import statements

REPLAY_TABLE = "authenticated_request_replay"
REPLAY_TABLE_MIGRATION_ID = "authenticated_requests_0001_replay_table"


def replay_table_statements(dialect: str) -> tuple[str, ...]:
    """The replay table and its expiry index, for ``sqlite`` or ``postgresql``."""

    return statements(dialect, table=REPLAY_TABLE)


def _create_replay_table(connection: sqlite3.Connection) -> None:
    for statement in replay_table_statements("sqlite"):
        connection.execute(statement)


SQLITE_REPLAY_TABLE_MIGRATION: Migration[sqlite3.Connection] = Migration(
    id=REPLAY_TABLE_MIGRATION_ID, apply=_create_replay_table
)
"""The replay table's migration for a chain over ``sqlite3`` connections."""


def sqlite_replay_store(connect: Callable[[], sqlite3.Connection]) -> SqliteReplayStore:
    """The replay store over the table this kit's migration created."""

    return SqliteReplayStore(connect, table=REPLAY_TABLE)
