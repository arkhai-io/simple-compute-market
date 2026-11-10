"""A SQLite database holding the settlement runtime's tables, for its tests.

The repository issues no DDL: the tables are a storefront chain's, built by the
runtime's baseline, so a test builds them the same way before it opens one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from market_settlement_runtime.migrations import BASELINE


def settlement_database(path: str | Path) -> str:
    """Create the settlement tables in the database at ``path`` and return it."""
    connection = sqlite3.connect(path)
    try:
        with connection:
            BASELINE.apply(connection)
    finally:
        connection.close()
    return str(path)
