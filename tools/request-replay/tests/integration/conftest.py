"""Both stores over real SQLite files, each table created from the published DDL."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from request_replay import SqliteReplayStore, statements
from request_replay.sqlalchemy_store import SqlAlchemyReplayStore


def migrate(path: Path) -> None:
    """Create the table as a consumer's migration would, from the statements."""
    connection = sqlite3.connect(path)
    try:
        for statement in statements("sqlite"):
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def connector(path: Path) -> Callable[[], sqlite3.Connection]:
    return lambda: sqlite3.connect(path, timeout=10)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "replay.sqlite3"
    migrate(path)
    return path


@pytest.fixture(params=["sqlite3", "sqlalchemy"])
def store_kind(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def make_store(database: Path, store_kind: str) -> Iterator[Callable[[], object]]:
    """Open another store over the same database, as another process would."""
    engines = []

    def make() -> object:
        if store_kind == "sqlite3":
            return SqliteReplayStore(connector(database))
        engine = create_engine(f"sqlite:///{database}")
        engines.append(engine)
        return SqlAlchemyReplayStore(engine)

    yield make
    for engine in engines:
        engine.dispose()


@pytest.fixture
def store(make_store: Callable[[], object]) -> object:
    return make_store()
