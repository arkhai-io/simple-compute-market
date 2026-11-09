"""The pool-override store's migrations, for a storefront chain holding its table.

A storefront composition composes :data:`BASELINE` after core storefront's. The
baseline is fixed DDL reproducing ``pool_overrides`` as the marketplace v0.3.0
release's storefronts built it; a later change to the table is a migration
after it, never an edit to it, since an adopted v0.3.0 database records the
baseline without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

import sqlite3

from market_schema_migrations import Migration

_BASELINE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE pool_overrides (
      site_id TEXT NOT NULL,
      pool_id TEXT NOT NULL,
      offering_mode TEXT NOT NULL,
      listing_shapes TEXT,
      settlements TEXT,
      terms TEXT,
      created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
      updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
      asking_rates TEXT,
      PRIMARY KEY (site_id, pool_id, offering_mode)
    )
    """,
)

BASELINE_TABLES: frozenset[str] = frozenset({"pool_overrides"})
"""The tables :data:`BASELINE` creates."""


def _create_baseline(connection: sqlite3.Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.execute(statement)


BASELINE: Migration[sqlite3.Connection] = Migration(
    "v0_3_0_baseline_pool_overrides", _create_baseline
)
"""``pool_overrides`` as the v0.3.0 release's storefronts built it."""
