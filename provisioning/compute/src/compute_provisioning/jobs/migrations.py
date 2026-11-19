"""The job authority's migrations, for the chain of the database holding it.

The provisioning service composes :data:`BASELINE` into its chain. The baseline
is fixed DDL reproducing the job tables as the marketplace v0.3.0 release
built them, the index that release still carried under the reservation's
earlier column name included; a later change to a table is a migration after
it, never an edit to it, since an adopted v0.3.0 database records the baseline
without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_schema_migrations import Migration

_BASELINE_DDL = (
    """
    CREATE TABLE ansible_jobs (
        id VARCHAR PRIMARY KEY,
        status VARCHAR NOT NULL,
        params JSON NOT NULL,
        host_id VARCHAR,
        result JSON,
        logs TEXT,
        error TEXT,
        execution_handle JSON,
        retry_count INTEGER NOT NULL,
        max_retries INTEGER NOT NULL,
        next_retry_at DATETIME,
        capacity_reservation_id VARCHAR,
        offering_mode VARCHAR,
        action_kind VARCHAR,
        executor_action VARCHAR,
        idempotency_key VARCHAR,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX ix_ansible_jobs_allocation_id ON ansible_jobs (capacity_reservation_id)",
    "CREATE INDEX ix_ansible_jobs_capacity_reservation_id "
    "ON ansible_jobs (capacity_reservation_id)",
    "CREATE INDEX ix_ansible_jobs_host_id ON ansible_jobs (host_id)",
    "CREATE UNIQUE INDEX uq_ansible_jobs_contract_idempotency "
    "ON ansible_jobs (capacity_reservation_id, action_kind, idempotency_key)",
    """
    CREATE TABLE credentials (
        id VARCHAR NOT NULL,
        job_id VARCHAR NOT NULL,
        envelope JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(job_id) REFERENCES ansible_jobs (id)
    )
    """,
    "CREATE INDEX ix_credentials_job_id ON credentials (job_id)",
)


def _create_baseline(connection: Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.exec_driver_sql(statement)


BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_compute_provisioning_jobs", _create_baseline
)
"""``ansible_jobs`` and ``credentials`` as the v0.3.0 release built them."""
