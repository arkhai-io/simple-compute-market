"""The fulfillment aggregate's migrations, for the chain of each database holding it.

A service whose database holds the aggregate composes :data:`BASELINE` into its
chain. The baseline is fixed DDL reproducing the aggregate's tables as the
marketplace v0.3.0 release built them; a later change to a table is a
migration after it, never an edit to it, since an adopted v0.3.0 database
records the baseline without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_schema_migrations import Migration

_BASELINE_DDL = (
    """
    CREATE TABLE settlement_records (
        capacity_reservation_id VARCHAR NOT NULL,
        fulfillment_id VARCHAR,
        market VARCHAR NOT NULL,
        scheduling_requirements JSON NOT NULL,
        resource_id_constraint VARCHAR,
        settlement_resource_id VARCHAR,
        pool_id VARCHAR,
        provider VARCHAR,
        resource_attributes JSON,
        resource_host_id VARCHAR,
        fulfillment_request JSON,
        prepared_create_operation JSON,
        prepared_teardown_operation JSON,
        provider_metadata JSON NOT NULL,
        teardown_provider_metadata JSON,
        state VARCHAR NOT NULL,
        failure_reason VARCHAR,
        failure_message TEXT,
        claimed_by VARCHAR,
        claim_expires_at DATETIME,
        attempt_count INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (capacity_reservation_id)
    )
    """,
    "CREATE UNIQUE INDEX ix_settlement_records_fulfillment_id "
    "ON settlement_records (fulfillment_id)",
    "CREATE INDEX ix_settlement_records_settlement_resource_id "
    "ON settlement_records (settlement_resource_id)",
    """
    CREATE TABLE provisioned_resources (
        provisioned_resource_id VARCHAR NOT NULL,
        capacity_reservation_id VARCHAR NOT NULL,
        fulfillment_id VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (provisioned_resource_id),
        FOREIGN KEY(capacity_reservation_id)
            REFERENCES settlement_records (capacity_reservation_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_provisioned_resources_capacity_reservation_id "
    "ON provisioned_resources (capacity_reservation_id)",
    "CREATE INDEX ix_provisioned_resources_fulfillment_id "
    "ON provisioned_resources (fulfillment_id)",
    """
    CREATE TABLE scheduling_cursors (
        resource_kind VARCHAR NOT NULL,
        last_pool_id VARCHAR,
        last_resource_by_pool JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (resource_kind)
    )
    """,
)


def _create_baseline(connection: Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.exec_driver_sql(statement)


BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_fulfillment", _create_baseline
)
"""The aggregate's tables as the v0.3.0 release built them."""
