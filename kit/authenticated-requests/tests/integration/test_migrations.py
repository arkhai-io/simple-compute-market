"""The replay table's migration, applied to an empty database by each adapter."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from market_schema_migrations import Chain, SqliteMigrationConnection, migrate, schema_snapshot
from market_schema_migrations.sqlalchemy_adapter import SqlAlchemyMigrationConnection
from request_replay import Dispatch, Entry, Policy, RequestReplay, Resolution
from sqlalchemy import create_engine

from market_authenticated_requests import (
    REPLAY_TABLE,
    REPLAY_TABLE_MIGRATION_ID,
    SQLITE_REPLAY_TABLE_MIGRATION,
    sqlite_replay_store,
)
from market_authenticated_requests.sqlalchemy_support import (
    SQLALCHEMY_REPLAY_TABLE_MIGRATION,
    sqlalchemy_replay_store,
)

POLICY = Policy(skew_seconds=300, retention_seconds=86_400, lease_seconds=30)
ENTRY = Entry(principal="ed25519:caller", request_id="r-1", request_hash="h", resolution=Resolution.RERUN, origin=1_800_000_000)


def objects(path: Path) -> set[tuple[str, str]]:
    with sqlite3.connect(path) as connection:
        return {
            (str(kind), str(name))
            for kind, name in connection.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
        }


def snapshot(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


EXPECTED = {
    ("table", "schema_migrations"),
    ("table", REPLAY_TABLE),
    ("index", f"ix_{REPLAY_TABLE}_expires_at"),
}


def test_the_sqlite3_migration_creates_the_replay_table_its_store_uses(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    chain = Chain(service="authority", command="authority-migrate", baselines=(SQLITE_REPLAY_TABLE_MIGRATION,))
    connection = sqlite3.connect(path)
    try:
        report = migrate(chain, SqliteMigrationConnection(connection))
        before = schema_snapshot(connection)
    finally:
        connection.close()

    assert report.applied == (REPLAY_TABLE_MIGRATION_ID,)
    assert objects(path) == EXPECTED
    replay = RequestReplay(sqlite_replay_store(lambda: sqlite3.connect(path)), POLICY, clock=lambda: 1_800_000_000)
    assert isinstance(replay.admit(ENTRY), Dispatch)
    connection = sqlite3.connect(path)
    try:
        assert schema_snapshot(connection) == before
    finally:
        connection.close()


def test_the_sqlalchemy_migration_creates_the_replay_table_its_store_uses(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite3"
    engine = create_engine(f"sqlite:///{path}")
    try:
        chain = Chain(service="authority", command="authority-migrate", baselines=(SQLALCHEMY_REPLAY_TABLE_MIGRATION,))
        with engine.connect() as connection:
            report = migrate(chain, SqlAlchemyMigrationConnection(connection))
        before = snapshot(path)

        assert report.applied == (REPLAY_TABLE_MIGRATION_ID,)
        assert objects(path) == EXPECTED
        replay = RequestReplay(sqlalchemy_replay_store(engine), POLICY, clock=lambda: 1_800_000_000)
        assert isinstance(replay.admit(ENTRY), Dispatch)
        assert snapshot(path) == before
    finally:
        engine.dispose()
