"""The replay table's migration and store over SQLAlchemy.

Only an authority holding SQLAlchemy imports this module, through the package's
``sqlalchemy`` extra; nothing else in the package imports it.
"""

from __future__ import annotations

from market_schema_migrations import Migration
from request_replay.sqlalchemy_store import SqlAlchemyReplayStore
from sqlalchemy import Connection, Engine

from market_authenticated_requests.migrations import (
    REPLAY_TABLE,
    REPLAY_TABLE_MIGRATION_ID,
    replay_table_statements,
)


def _create_replay_table(connection: Connection) -> None:
    for statement in replay_table_statements(connection.dialect.name):
        connection.exec_driver_sql(statement)


SQLALCHEMY_REPLAY_TABLE_MIGRATION: Migration[Connection] = Migration(
    id=REPLAY_TABLE_MIGRATION_ID, apply=_create_replay_table
)
"""The replay table's migration for a chain over SQLAlchemy connections."""


def sqlalchemy_replay_store(engine: Engine) -> SqlAlchemyReplayStore:
    """The replay store over the table this kit's migration created."""

    return SqlAlchemyReplayStore(engine, table=REPLAY_TABLE)
