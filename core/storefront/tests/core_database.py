"""A database migrated through core storefront's baseline and later migrations.

Every storefront composition's chain includes core's migrations; core's own
tests compose only those, since core's client reads only its own tables.
Constructing a client issues no DDL, so a test migrates its database first, as a
storefront's migration command does.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from market_schema_migrations import Chain, SqliteMigrationConnection, migrate

from core_storefront.migrations import BASELINE, MIGRATIONS

CORE_CHAIN: Chain[sqlite3.Connection] = Chain(
    service="core storefront",
    command="(core storefront's tests)",
    baselines=(BASELINE,),
    migrations=MIGRATIONS,
)


def core_database(path: str | Path) -> str:
    """Migrate the database at ``path`` through :data:`CORE_CHAIN`; return it."""
    connection = sqlite3.connect(path)
    try:
        migrate(CORE_CHAIN, SqliteMigrationConnection(connection))
    finally:
        connection.close()
    return str(path)
