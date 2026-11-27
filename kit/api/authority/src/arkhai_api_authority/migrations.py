"""The authority's migration chain, composed by each service root.

The chain begins with one baseline per package whose tables the database
holds, each fixed DDL, composed in foreign-key order: the resource pools, the
authority's keys, grants and consumption, and the site ledger it hosts as its
quota ledger. The site ledger's later migrations follow, then its repair of a
bucket's host index, then the authority's own. The baselines reproduce the
database the marketplace v0.3.0 release's API-credit service built at startup,
but for that index, which the site ledger's baseline names and that release,
building the ledger from its models, left out; the repair creates it on an
adopted database. Each service root declares its chain's floor: a root whose
service that release shipped names the IDs the release recorded, and a
database recording every one of them is adopted at the baseline without
running it; a root with no earlier history declares ``0.0.0`` and adopts
nothing. A later change to any of these tables is a migration appended to the
chain, never an edit to a baseline.

No migration seeds a row: the profile's pool is configuration, and no schema
constraint requires it, so the service's startup inserts it.
See openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history.
"""

from __future__ import annotations

from market_resource_pools.migrations import BASELINE as POOLS_BASELINE
from market_schema_migrations import Chain, Floor, Migration
from market_site.migrations import BASELINE as SITE_BASELINE
from market_site.migrations import CAPACITY_BUCKET_HOST_INDEX
from market_site.migrations import MIGRATIONS as SITE_MIGRATIONS
from sqlalchemy import Connection

_AUTHORITY_BASELINE_DDL = (
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

_GRANT_TERMS_DDL = """
    CREATE TABLE grant_terms (
        grant_id INTEGER NOT NULL,
        accepted_terms TEXT NOT NULL,
        terms_digest VARCHAR NOT NULL,
        request_charge INTEGER NOT NULL,
        PRIMARY KEY (grant_id),
        FOREIGN KEY(grant_id) REFERENCES credit_grants (id)
    )
"""


def _create_authority_baseline(connection: Connection) -> None:
    for statement in _AUTHORITY_BASELINE_DDL:
        connection.exec_driver_sql(statement)


def _create_grant_terms(connection: Connection) -> None:
    """Create ``grant_terms``; a grant without a row reads as unpinned."""
    connection.exec_driver_sql(_GRANT_TERMS_DDL)


AUTHORITY_BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_apicredits_service", _create_authority_baseline
)
"""The authority's keys, credit grants, and consumption events."""

GRANT_TERMS: Migration[Connection] = Migration(
    "20261109_001_grant_terms", _create_grant_terms
)

MIGRATIONS: tuple[Migration[Connection], ...] = (GRANT_TERMS,)
"""The authority's own migrations after :data:`AUTHORITY_BASELINE`, in order."""


def authority_chain(*, service: str, command: str, floor: Floor) -> Chain[Connection]:
    """The chain for one service root; refusals name ``service`` and ``command``.

    ``floor`` is the root's: the release its service is supported from, with
    the IDs that release recorded, or ``Floor("0.0.0")`` for a service no
    release shipped.
    """
    return Chain(
        service=service,
        command=command,
        baselines=(POOLS_BASELINE, AUTHORITY_BASELINE, SITE_BASELINE),
        migrations=(*SITE_MIGRATIONS, CAPACITY_BUCKET_HOST_INDEX, *MIGRATIONS),
        floor=floor,
    )
