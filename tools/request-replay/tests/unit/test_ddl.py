from __future__ import annotations

import pytest

from request_replay import DIALECTS, statements


@pytest.mark.parametrize("dialect", DIALECTS)
def test_each_dialect_creates_the_table_then_its_expiry_index(dialect: str) -> None:
    table, index = statements(dialect, table="replay_rows")

    assert table.startswith("CREATE TABLE replay_rows (")
    assert "PRIMARY KEY (principal, request_id)" in table
    assert index == "CREATE INDEX ix_replay_rows_expires_at ON replay_rows (expires_at)"


def test_postgresql_holds_instants_as_big_integers_and_bodies_as_bytes() -> None:
    table, _ = statements("postgresql")

    assert "expires_at BIGINT NOT NULL" in table
    assert "outcome_body BYTEA" in table


@pytest.mark.parametrize("table", ["Replay", "replay-rows", "replay; DROP TABLE x", ""])
def test_a_table_name_that_is_no_plain_identifier_is_refused(table: str) -> None:
    with pytest.raises(ValueError, match="plain lower-case SQL identifier"):
        statements("sqlite", table=table)


def test_an_unknown_dialect_is_refused() -> None:
    with pytest.raises(ValueError, match="mysql"):
        statements("mysql")
