"""The relay registry's migrations, for the chain of the database holding it.

The provisioning service composes :data:`BASELINE` into its chain after the
resource-pool baseline, since a pool's relay binding names its pool. The
baseline is fixed DDL reproducing the relay tables as the marketplace v0.3.0
release built them; a later change to a table is a migration after it, never
an edit to it, since an adopted v0.3.0 database records the baseline without
running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_schema_migrations import Migration

_BASELINE_DDL = (
    """
    CREATE TABLE relays (
        id VARCHAR NOT NULL,
        label VARCHAR,
        relay_addr VARCHAR NOT NULL,
        relay_port INTEGER NOT NULL,
        vm_port_range_start INTEGER NOT NULL,
        vm_port_range_count INTEGER NOT NULL,
        relay_token_encrypted VARCHAR,
        grant_key_encrypted VARCHAR,
        grant_key_id VARCHAR,
        grant_key_public VARCHAR,
        grant_key_activated_at DATETIME,
        staged_grant_key_encrypted VARCHAR,
        staged_grant_key_id VARCHAR,
        staged_grant_key_public VARCHAR,
        enabled BOOLEAN DEFAULT 1 NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME,
        PRIMARY KEY (id),
        CONSTRAINT uq_relays_endpoint UNIQUE (relay_addr, relay_port)
    )
    """,
    """
    CREATE TABLE relay_port_leases (
        id VARCHAR NOT NULL,
        relay_id VARCHAR NOT NULL,
        remote_port INTEGER NOT NULL,
        host_id VARCHAR,
        pool_id VARCHAR,
        owner_kind VARCHAR NOT NULL,
        owner_id VARCHAR NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        released_at DATETIME,
        grant_expires_at DATETIME,
        grant_key_id VARCHAR,
        PRIMARY KEY (id),
        CONSTRAINT uq_relay_port_leases_endpoint UNIQUE (relay_id, remote_port),
        FOREIGN KEY(relay_id) REFERENCES relays (id)
    )
    """,
    "CREATE INDEX ix_relay_port_leases_owner_id ON relay_port_leases (owner_id)",
    "CREATE INDEX ix_relay_port_leases_relay_id ON relay_port_leases (relay_id)",
    "CREATE UNIQUE INDEX uq_relay_port_leases_active_owner "
    "ON relay_port_leases (owner_kind, owner_id) WHERE released_at IS NULL",
    """
    CREATE TABLE relay_retired_grant_keys (
        relay_id VARCHAR NOT NULL,
        key_id VARCHAR NOT NULL,
        retired_at DATETIME NOT NULL,
        PRIMARY KEY (relay_id, key_id),
        FOREIGN KEY(relay_id) REFERENCES relays (id)
    )
    """,
    """
    CREATE TABLE pool_relays (
        pool_id VARCHAR NOT NULL,
        relay_id VARCHAR NOT NULL,
        PRIMARY KEY (pool_id),
        FOREIGN KEY(pool_id) REFERENCES resource_pools (id),
        FOREIGN KEY(relay_id) REFERENCES relays (id)
    )
    """,
    "CREATE INDEX ix_pool_relays_relay_id ON pool_relays (relay_id)",
)


def _create_baseline(connection: Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.exec_driver_sql(statement)


BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_compute_provisioning_relays", _create_baseline
)
"""The relay tables as the v0.3.0 release built them."""
