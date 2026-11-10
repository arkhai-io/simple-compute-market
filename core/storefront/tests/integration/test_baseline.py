"""Core storefront's baseline creates exactly its market-state tables.

A real SQLite database, no application. That the baseline reproduces the v0.3.0
schema column for column is proven against the bare-metal storefront's floor
fixture, which only that storefront holds.
"""

import sqlite3

from core_storefront.migrations import BASELINE, BASELINE_TABLES


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def test_the_baseline_creates_exactly_cores_tables() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        BASELINE.apply(conn)
        assert _tables(conn) == BASELINE_TABLES
    finally:
        conn.close()


def test_the_baseline_has_a_stable_id() -> None:
    assert BASELINE.id == "v0_3_0_baseline_core_storefront"
