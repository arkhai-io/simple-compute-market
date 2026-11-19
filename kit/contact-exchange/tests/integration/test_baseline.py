"""Contact exchange's baseline creates exactly its introduction tables.

A real SQLite database, no application. That the baseline reproduces the v0.3.0
schema column for column is proven against the bare-metal storefront's floor
fixture, which only that storefront holds.
"""

import sqlite3

from market_contact_exchange.migrations import BASELINE, BASELINE_TABLES


def test_the_baseline_creates_exactly_the_introduction_tables() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        BASELINE.apply(conn)
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == BASELINE_TABLES
        assert BASELINE.id == "v0_3_0_baseline_contact_exchange"
    finally:
        conn.close()
