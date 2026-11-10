"""The resource-pool registry's migrations, for a migration chain holding the table.

A chain holding ``resource_pools`` composes :data:`BASELINE` before every
baseline whose tables refer to a pool. The baseline is
fixed DDL reproducing the table as the marketplace v0.3.0 release built it; a
later change to the table is a migration after it, never an edit to it, since
an adopted v0.3.0 database records the baseline without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_schema_migrations import Migration

_BASELINE_DDL = (
    """
    CREATE TABLE resource_pools (
        id VARCHAR NOT NULL,
        label VARCHAR NOT NULL,
        provider VARCHAR NOT NULL,
        enabled BOOLEAN NOT NULL,
        policy_tags JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (id)
    )
    """,
)


def _create_baseline(connection: Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.exec_driver_sql(statement)


BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_resource_pools", _create_baseline
)
"""``resource_pools`` as the v0.3.0 release built it."""
