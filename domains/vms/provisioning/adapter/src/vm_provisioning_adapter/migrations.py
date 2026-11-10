"""VM's migrations, for the chain of the provisioning database holding its table.

The provisioning service composes :data:`BASELINE` into its chain after the
resource-pool baseline, since a pool's VM configuration names its pool. The
baseline is fixed DDL reproducing ``ansible_pool_configs`` as the marketplace
v0.3.0 release built it; a later change to the table is a migration after it,
never an edit to it, since an adopted v0.3.0 database records the baseline
without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_schema_migrations import Migration

_BASELINE_DDL = (
    """
    CREATE TABLE ansible_pool_configs (
        pool_id VARCHAR NOT NULL,
        playbook_path VARCHAR,
        requirement_delegate VARCHAR DEFAULT 'vm_management_v1' NOT NULL,
        extra_vars JSON NOT NULL,
        default_vm_ram INTEGER,
        default_vm_vcpus INTEGER,
        default_vm_disk_size VARCHAR,
        PRIMARY KEY (pool_id),
        FOREIGN KEY(pool_id) REFERENCES resource_pools (id)
    )
    """,
)


def _create_baseline(connection: Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.exec_driver_sql(statement)


BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_vm_provisioning", _create_baseline
)
"""``ansible_pool_configs`` as the v0.3.0 release built it."""
