"""A database migrated through a chain of core storefront's baseline alone.

Every storefront composition's chain begins with core's baseline; core's own
tests need nothing beyond it, since core's client reads only its own tables.
Constructing a client issues no DDL, so a test migrates its database first, as a
storefront's migration command does.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from market_schema_migrations import Chain, SqliteMigrationConnection, migrate

from core_storefront.migrations import BASELINE

CORE_CHAIN: Chain[sqlite3.Connection] = Chain(
    service="core storefront",
    command="(core storefront's tests)",
    baselines=(BASELINE,),
)


def core_database(path: str | Path) -> str:
    """Migrate the database at ``path`` through :data:`CORE_CHAIN`; return it."""
    connection = sqlite3.connect(path)
    try:
        migrate(CORE_CHAIN, SqliteMigrationConnection(connection))
    finally:
        connection.close()
    return str(path)
