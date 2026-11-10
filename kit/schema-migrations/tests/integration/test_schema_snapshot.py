"""The snapshot compares structure, not the SQL text that built it."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from market_schema_migrations import schema_snapshot


@pytest.fixture
def pair() -> Iterator[tuple[sqlite3.Connection, sqlite3.Connection]]:
    first, second = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    yield first, second
    first.close()
    second.close()


def test_an_altered_column_equals_a_created_one(pair) -> None:
    created, altered = pair
    created.execute(
        "CREATE TABLE hosts (host_id VARCHAR NOT NULL, port INTEGER DEFAULT 22, "
        "PRIMARY KEY (host_id))"
    )
    altered.execute("CREATE TABLE hosts (\n  host_id VARCHAR NOT NULL,\n  PRIMARY KEY (host_id)\n)")
    altered.execute("ALTER TABLE hosts ADD COLUMN port INTEGER DEFAULT 22")

    assert schema_snapshot(created) == schema_snapshot(altered)


@pytest.mark.parametrize(
    "other",
    [
        "CREATE TABLE hosts (host_id VARCHAR NOT NULL PRIMARY KEY, port TEXT DEFAULT 22)",
        "CREATE TABLE hosts (host_id VARCHAR NOT NULL PRIMARY KEY, port INTEGER NOT NULL DEFAULT 22)",
        "CREATE TABLE hosts (host_id VARCHAR NOT NULL PRIMARY KEY, port INTEGER DEFAULT 2222)",
        "CREATE TABLE hosts (host_id VARCHAR NOT NULL PRIMARY KEY, port INTEGER DEFAULT 22, "
        "name VARCHAR)",
        "CREATE TABLE hosts (host_id VARCHAR NOT NULL, port INTEGER DEFAULT 22)",
    ],
    ids=["type", "not-null", "default", "extra-column", "no-primary-key"],
)
def test_a_column_difference_is_seen(pair, other: str) -> None:
    first, second = pair
    first.execute(
        "CREATE TABLE hosts (host_id VARCHAR NOT NULL PRIMARY KEY, port INTEGER DEFAULT 22)"
    )
    second.execute(other)

    assert schema_snapshot(first) != schema_snapshot(second)


def test_unique_constraints_compare_by_columns_not_generated_names(pair) -> None:
    inline, table_level = pair
    inline.execute("CREATE TABLE pools (pool_id VARCHAR UNIQUE, site_id VARCHAR UNIQUE)")
    table_level.execute(
        "CREATE TABLE pools (pool_id VARCHAR, site_id VARCHAR, UNIQUE (pool_id), UNIQUE (site_id))"
    )
    assert schema_snapshot(inline) == schema_snapshot(table_level)

    inline.execute("CREATE TABLE extra (a INTEGER, b INTEGER, UNIQUE (a, b))")
    table_level.execute("CREATE TABLE extra (a INTEGER, b INTEGER, UNIQUE (b, a))")
    assert schema_snapshot(inline) != schema_snapshot(table_level)


def test_indexes_foreign_keys_and_partial_clauses_are_seen(pair) -> None:
    first, second = pair
    for connection in pair:
        connection.execute("CREATE TABLE pools (pool_id VARCHAR PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE hosts (host_id VARCHAR PRIMARY KEY, "
            "pool_id VARCHAR REFERENCES pools (pool_id) ON DELETE CASCADE, enabled INTEGER)"
        )
    first.execute("CREATE INDEX ix_hosts_pool ON hosts (pool_id) WHERE enabled = 1")
    second.execute("CREATE INDEX ix_hosts_pool ON hosts(pool_id)   WHERE   enabled = 1")
    assert schema_snapshot(first) == schema_snapshot(second)

    second.execute("DROP INDEX ix_hosts_pool")
    second.execute("CREATE INDEX ix_hosts_pool ON hosts (pool_id) WHERE enabled = 0")
    assert schema_snapshot(first) != schema_snapshot(second)

    key = schema_snapshot(first)["tables"]["hosts"]["foreign_keys"]
    assert key == [
        {
            "table": "pools",
            "columns": ["pool_id"],
            "references": ["pool_id"],
            "on_update": "NO ACTION",
            "on_delete": "CASCADE",
            "match": "NONE",
        }
    ]


def test_check_constraints_compare_by_their_text_without_whitespace(pair) -> None:
    first, second = pair
    first.execute(
        "CREATE TABLE deals (state TEXT CHECK (state IN ('open', 'closed')), "
        "amount INTEGER, CHECK (amount >= 0))"
    )
    second.execute(
        "CREATE TABLE deals (state TEXT CHECK(state IN ('open','closed')),\n"
        "  amount INTEGER,\n  CHECK ( amount >= 0 ))"
    )
    assert schema_snapshot(first) == schema_snapshot(second)
    assert schema_snapshot(first)["tables"]["deals"]["checks"] == [
        "amount >= 0",
        "state IN('open','closed')",
    ]

    second.execute("DROP TABLE deals")
    second.execute("CREATE TABLE deals (state TEXT, amount INTEGER, CHECK (amount >= 0))")
    assert schema_snapshot(first) != schema_snapshot(second)


@pytest.mark.parametrize(
    ("first_sql", "second_sql"),
    [
        (
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT)",
            "CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT)",
        ),
        (
            "CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT) STRICT",
            "CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT)",
        ),
        (
            "CREATE TABLE events (id TEXT PRIMARY KEY, kind TEXT) WITHOUT ROWID",
            "CREATE TABLE events (id TEXT PRIMARY KEY, kind TEXT)",
        ),
    ],
    ids=["autoincrement", "strict", "without-rowid"],
)
def test_table_options_only_the_text_states_are_seen(pair, first_sql: str, second_sql: str) -> None:
    first, second = pair
    first.execute(first_sql)
    second.execute(second_sql)

    assert schema_snapshot(first) != schema_snapshot(second)


def test_an_expression_index_is_compared_by_its_definition(pair) -> None:
    first, second = pair
    for connection in pair:
        connection.execute("CREATE TABLE hosts (host_id TEXT, name TEXT)")
    first.execute("CREATE INDEX ix_hosts_name ON hosts (lower(name))")
    second.execute("CREATE INDEX ix_hosts_name ON hosts (upper(name))")

    assert schema_snapshot(first) != schema_snapshot(second)


def test_triggers_and_views_are_seen_and_the_ledger_is_not(pair) -> None:
    first, second = pair
    for connection in pair:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT)")
        connection.execute(
            "CREATE TRIGGER events_immutable BEFORE UPDATE ON events "
            "BEGIN SELECT RAISE(ABORT, 'immutable'); END"
        )
        connection.execute("CREATE VIEW kinds AS SELECT DISTINCT kind FROM events")
    first.execute("CREATE TABLE schema_migrations (id VARCHAR PRIMARY KEY)")
    second.execute(
        "CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    snapshot = schema_snapshot(first)
    assert snapshot == schema_snapshot(second)
    assert set(snapshot["tables"]) == {"events"}
    assert snapshot["triggers"]["events_immutable"]["table"] == "events"
    assert "kinds" in snapshot["views"]

    second.execute("DROP TRIGGER events_immutable")
    assert schema_snapshot(first) != schema_snapshot(second)
