"""The host registry's migrations, for the chain of the database holding it.

The provisioning service composes :data:`BASELINE` into its chain after the
resource-pool baseline, since a host names its pool. The baseline is fixed DDL
reproducing ``hosts`` as the marketplace v0.3.0 release built it; a later
change to the table is a migration after it, never an edit to it, since an
adopted v0.3.0 database records the baseline without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_schema_migrations import Migration

_BASELINE_DDL = (
    """
    CREATE TABLE hosts (
        host_id VARCHAR PRIMARY KEY,
        connection_kind VARCHAR NOT NULL,
        connection_version INTEGER NOT NULL DEFAULT '1',
        connection_public JSON NOT NULL,
        connection_protected JSON NOT NULL,
        enabled BOOLEAN NOT NULL,
        pool_id VARCHAR,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (pool_id) REFERENCES resource_pools (id)
    )
    """,
)


def _create_baseline(connection: Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.exec_driver_sql(statement)


BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_compute_provisioning_hosts", _create_baseline
)
"""``hosts`` as the v0.3.0 release built it."""
