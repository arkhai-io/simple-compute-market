"""The harness's state snapshots over real databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

from request_replay.harness import sqlite_snapshot
from request_replay.sqlalchemy_store import table_snapshot

SCHEMA = (
    "CREATE TABLE things (id INTEGER, name TEXT);"
    "CREATE TABLE replay (k TEXT);"
    "INSERT INTO things VALUES (2, 'b'), (1, 'a');"
    "INSERT INTO replay VALUES ('x');"
)


def test_a_sqlite_snapshot_reads_every_table_but_those_excluded(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "state.sqlite3")
    connection.executescript(SCHEMA)

    snapshot = sqlite_snapshot(connection, exclude={"replay"})

    assert snapshot == {"things": [(1, "a"), (2, "b")]}
    connection.execute("INSERT INTO replay VALUES ('y')")
    assert sqlite_snapshot(connection, exclude={"replay"}) == snapshot
    connection.execute("INSERT INTO things VALUES (3, 'c')")
    assert sqlite_snapshot(connection, exclude={"replay"}) != snapshot


def test_a_table_snapshot_reads_every_table_but_those_excluded(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.close()
    engine = create_engine(f"sqlite:///{path}")
    try:
        snapshot = table_snapshot(engine, exclude={"replay"})

        assert snapshot == {"things": [(1, "a"), (2, "b")]}
        with engine.begin() as writer:
            writer.exec_driver_sql("INSERT INTO replay VALUES ('y')")
        assert table_snapshot(engine, exclude={"replay"}) == snapshot
    finally:
        engine.dispose()
