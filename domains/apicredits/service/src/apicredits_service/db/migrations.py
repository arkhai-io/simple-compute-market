"""The API-credit service's migration chain.

The chain begins with one baseline per package whose tables the database
holds, each fixed DDL, composed in foreign-key order: the resource pools, this
service's keys, grants and consumption, and the site ledger it hosts as its
quota ledger. The site ledger's later migrations follow. The chain names no
floor: no API-credit database from before its baseline is supported, so the
migration command refuses every non-empty database it did not build. A later
change to any of these tables is a migration appended to :data:`CHAIN`, never
an edit to a baseline.

No migration seeds a row: the ``default`` pool is configuration-free but no
schema constraint requires it, so the service's startup inserts it.
See openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history.
"""

from __future__ import annotations

from sqlalchemy import Connection

from market_resource_pools.migrations import BASELINE as POOLS_BASELINE
from market_schema_migrations import Chain, Migration
from market_site.migrations import BASELINE as SITE_BASELINE
from market_site.migrations import MIGRATIONS as SITE_MIGRATIONS

SERVICE = "the API-credit service"
COMMAND = "apicredits-service-migrate"

_SERVICE_BASELINE_DDL = (
    """
    CREATE TABLE api_keys (
        key_id VARCHAR NOT NULL,
        secret_hash VARCHAR NOT NULL,
        owner_scheme VARCHAR,
        owner_id VARCHAR,
        status VARCHAR NOT NULL,
        balance INTEGER NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (key_id)
    )
    """,
    """
    CREATE TABLE credit_grants (
        id INTEGER NOT NULL,
        key_id VARCHAR NOT NULL,
        fulfillment_id VARCHAR,
        negotiation_id VARCHAR,
        service VARCHAR,
        resource_id VARCHAR,
        key_mode VARCHAR,
        key_target_id VARCHAR,
        owner_scheme VARCHAR,
        owner_id VARCHAR,
        request_digest VARCHAR,
        capacity_reservation_id VARCHAR,
        result_balance INTEGER,
        quantity INTEGER NOT NULL,
        reason VARCHAR NOT NULL,
        granted_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(key_id) REFERENCES api_keys (key_id),
        UNIQUE (fulfillment_id),
        UNIQUE (negotiation_id)
    )
    """,
    "CREATE INDEX ix_credit_grants_key_id ON credit_grants (key_id)",
    """
    CREATE TABLE consumption_events (
        id INTEGER NOT NULL,
        key_id VARCHAR NOT NULL,
        amount INTEGER NOT NULL,
        idempotency_key VARCHAR,
        occurred_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_consumption_idem UNIQUE (key_id, idempotency_key),
        FOREIGN KEY(key_id) REFERENCES api_keys (key_id)
    )
    """,
    "CREATE INDEX ix_consumption_events_key_id ON consumption_events (key_id)",
)


def _create_service_baseline(connection: Connection) -> None:
    for statement in _SERVICE_BASELINE_DDL:
        connection.exec_driver_sql(statement)


SERVICE_BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_apicredits_service", _create_service_baseline
)
"""This service's keys, credit grants, and consumption events."""

CHAIN: Chain[Connection] = Chain(
    service=SERVICE,
    command=COMMAND,
    baselines=(POOLS_BASELINE, SERVICE_BASELINE, SITE_BASELINE),
    migrations=SITE_MIGRATIONS,
)
