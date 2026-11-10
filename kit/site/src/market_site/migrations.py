"""The site ledger's migrations, for a migration chain holding the ledger.

A chain holding the ledger composes :data:`BASELINE`, followed by every later
migration this module exports, in the order :data:`MIGRATIONS` lists them. The baseline is fixed DDL reproducing the
ledger's tables as the marketplace v0.3.0 release built them; a later change
to a table is a migration after it, never an edit to it, since an adopted
v0.3.0 database records the baseline without running it. A later migration
of the ledger's tables is written here, beside the tables' baseline, so every
chain composing the ledger takes it from one place.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_schema_migrations import Migration

_BASELINE_DDL = (
    """
    CREATE TABLE capacity_buckets (
        capacity_bucket_id VARCHAR NOT NULL,
        backing_resource_id VARCHAR NOT NULL,
        pool_id VARCHAR,
        host_id VARCHAR,
        resource_type VARCHAR NOT NULL,
        resource_subtype VARCHAR,
        total_units INTEGER,
        capacity JSON NOT NULL,
        attributes JSON NOT NULL,
        enabled BOOLEAN NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (capacity_bucket_id),
        CONSTRAINT uq_capacity_buckets_backing_resource UNIQUE (backing_resource_id),
        UNIQUE (host_id)
    )
    """,
    "CREATE INDEX ix_capacity_buckets_backing_resource_id "
    "ON capacity_buckets (backing_resource_id)",
    "CREATE INDEX ix_capacity_buckets_pool_id ON capacity_buckets (pool_id)",
    "CREATE UNIQUE INDEX uq_capacity_buckets_host_id ON capacity_buckets (host_id)",
    """
    CREATE TABLE capacity_reservations (
        capacity_reservation_id VARCHAR NOT NULL,
        settlement_resource_id VARCHAR,
        units INTEGER NOT NULL,
        dimensions JSON,
        claim_attributes JSON,
        state VARCHAR NOT NULL,
        deal_ref JSON,
        escrow_uid VARCHAR,
        hold_expires_at VARCHAR,
        offering_mode VARCHAR,
        executor_target VARCHAR,
        release_job_id VARCHAR,
        executor_ref JSON,
        lease_start_utc VARCHAR,
        lease_end_utc VARCHAR,
        create_job_id VARCHAR,
        failure_reason VARCHAR,
        failure_message TEXT,
        released_at VARCHAR,
        release_requested_at VARCHAR,
        activated_at_utc VARCHAR,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (capacity_reservation_id)
    )
    """,
    "CREATE INDEX ix_capacity_reservations_escrow_uid "
    "ON capacity_reservations (escrow_uid)",
    "CREATE INDEX ix_capacity_reservations_settlement_resource_id "
    "ON capacity_reservations (settlement_resource_id)",
    "CREATE INDEX ix_capacity_reservations_state ON capacity_reservations (state)",
    """
    CREATE TABLE capacity_reservation_debits (
        capacity_reservation_id VARCHAR NOT NULL,
        capacity_bucket_id VARCHAR NOT NULL,
        dimensions JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (capacity_reservation_id),
        CONSTRAINT uq_capacity_reservation_debits_reservation UNIQUE (capacity_reservation_id),
        FOREIGN KEY(capacity_reservation_id)
            REFERENCES capacity_reservations (capacity_reservation_id) ON DELETE CASCADE,
        FOREIGN KEY(capacity_bucket_id)
            REFERENCES capacity_buckets (capacity_bucket_id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_capacity_reservation_debits_capacity_bucket_id "
    "ON capacity_reservation_debits (capacity_bucket_id)",
    """
    CREATE TABLE capacity_events (
        version INTEGER NOT NULL,
        kind VARCHAR NOT NULL,
        resource_id VARCHAR,
        dimensions JSON,
        claim_attributes JSON,
        occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (version)
    )
    """,
    "CREATE INDEX ix_capacity_events_resource_id ON capacity_events (resource_id)",
    """
    CREATE TABLE site_lease_ended_events (
        event_id VARCHAR NOT NULL,
        capacity_reservation_id VARCHAR NOT NULL,
        transition_key VARCHAR NOT NULL,
        payload JSON NOT NULL,
        PRIMARY KEY (event_id),
        UNIQUE (capacity_reservation_id, transition_key)
    )
    """,
    "CREATE INDEX ix_site_lease_ended_events_capacity_reservation_id "
    "ON site_lease_ended_events (capacity_reservation_id)",
)


def _create_baseline(connection: Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.exec_driver_sql(statement)


def _add_reservation_placement_key(connection: Connection) -> None:
    """Add ``capacity_reservations.placement_key`` and ``placement_request``.

    A reserve's placement key is looked up on every keyed reserve, so it gets
    a unique index rather than a scan of ``deal_ref``. Nothing is backfilled:
    no reserve carried a placement key before the column existed, so every
    existing row records none, and is found only as it was before.
    """
    connection.exec_driver_sql(
        "ALTER TABLE capacity_reservations ADD COLUMN placement_key VARCHAR"
    )
    connection.exec_driver_sql(
        "ALTER TABLE capacity_reservations ADD COLUMN placement_request JSON"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX ix_capacity_reservations_placement_key "
        "ON capacity_reservations (placement_key)"
    )


BASELINE: Migration[Connection] = Migration("v0_3_0_baseline_site", _create_baseline)
"""The ledger's tables as the v0.3.0 release built them."""

RESERVATION_PLACEMENT_KEY: Migration[Connection] = Migration(
    "20261106_002_reservation_placement_key", _add_reservation_placement_key
)

MIGRATIONS: tuple[Migration[Connection], ...] = (RESERVATION_PLACEMENT_KEY,)
"""Every migration after :data:`BASELINE`, in the order a chain applies them."""
