"""The API-credit storefront's migration chain.

The chain composes core storefront's baseline, the settlement runtime's, and
the API-credit domain's own, in that order. The chain names no floor: no
API-credit database from before its baseline is supported, so the migration
command refuses every non-empty database it did not build. A later change to
any of these tables is a migration appended to :data:`CHAIN`, never an edit to
a baseline.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core_storefront import migrations as core_migrations
from market_schema_migrations import (
    Chain,
    CheckResult,
    MigrateReport,
    Migration,
    SqliteMigrationConnection,
    check_sqlite_file,
    migrate,
    refusal_message,
)
from market_settlement_runtime import migrations as settlement_migrations

MIGRATION_COMMAND = "apicredits-storefront-migrate"
"""The storefront's migration command's name, which every refusal names as the
remedy; the command applies :data:`CHAIN` through :func:`migrate_storefront_database`."""

_BASELINE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE credit_deal_terms (
      negotiation_id TEXT PRIMARY KEY,
      quantity INTEGER NOT NULL,
      key_mode TEXT NOT NULL DEFAULT 'new',
      key_id TEXT,
      created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
    """,
    # Each public settlement job is bound to its exact accepted obligation;
    # core's escrows table carries no obligation identity of its own.
    "ALTER TABLE escrows ADD COLUMN obligation_ref TEXT",
    "ALTER TABLE escrows ADD COLUMN obligation_index INTEGER",
    "CREATE UNIQUE INDEX idx_credit_escrows_obligation_ref"
    " ON escrows(obligation_ref) WHERE obligation_ref IS NOT NULL",
    "CREATE INDEX idx_credit_escrows_negotiation_obligation"
    " ON escrows(negotiation_id, obligation_index)",
    """
    CREATE TABLE api_credit_settlement_evidence (
      negotiation_id TEXT PRIMARY KEY,
      mechanism TEXT NOT NULL,
      agreement_digest TEXT NOT NULL,
      settlement_ref TEXT UNIQUE,
      status TEXT NOT NULL CHECK(status IN ('pending', 'verified', 'failed', 'refunding', 'refunded')),
      evidence TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE api_credit_issuance_progress (
      negotiation_id TEXT PRIMARY KEY,
      public_ref TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL CHECK(status IN ('provisioning', 'ready', 'failed')),
      fulfillment_uid TEXT,
      public_result TEXT NOT NULL DEFAULT '{}',
      credentials_ref TEXT,
      reason TEXT,
      delivery_started_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE api_credit_issuance_evidence (
      evidence_digest TEXT PRIMARY KEY,
      fulfillment_id TEXT NOT NULL UNIQUE,
      signed_evidence TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE api_credit_private_results (
      credentials_ref TEXT PRIMARY KEY,
      fulfillment_id TEXT NOT NULL UNIQUE,
      owner_scheme TEXT NOT NULL,
      owner_id TEXT NOT NULL,
      key_id TEXT NOT NULL,
      secret TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_api_credit_private_result_owner"
    " ON api_credit_private_results(owner_scheme, owner_id, credentials_ref)",
)

BASELINE_TABLES: frozenset[str] = frozenset(
    {
        "credit_deal_terms",
        "api_credit_settlement_evidence",
        "api_credit_issuance_progress",
        "api_credit_issuance_evidence",
        "api_credit_private_results",
    }
)
"""The tables :data:`BASELINE` creates; it also adds the obligation columns and
indexes to core's ``escrows``."""


def _create_baseline(connection: sqlite3.Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.execute(statement)


BASELINE: Migration[sqlite3.Connection] = Migration(
    "v0_3_0_baseline_apicredits_storefront", _create_baseline
)
"""The API-credit domain's tables: accepted credit terms, settlement evidence,
issuance progress and evidence, and private delivery results."""

CHAIN: Chain[sqlite3.Connection] = Chain(
    service="the API-credit storefront",
    command=MIGRATION_COMMAND,
    baselines=(
        core_migrations.BASELINE,
        settlement_migrations.BASELINE,
        BASELINE,
    ),
)


def migrate_storefront_database(db_path: str | Path) -> MigrateReport:
    """Apply :data:`CHAIN` to the database at ``db_path``, creating it if absent.

    Refuses an ahead or unsupported database applying nothing
    (``MigrationRefused``), every database it did not build among them; a
    failing migration leaves the ones before it recorded (``MigrationFailed``).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        return migrate(CHAIN, SqliteMigrationConnection(connection))
    finally:
        connection.close()


class IncompatibleStorefrontDatabase(RuntimeError):
    """The database is not exactly at the chain this image carries."""

    def __init__(self, result: CheckResult) -> None:
        super().__init__(
            refusal_message(result, service=CHAIN.service, command=CHAIN.command)
        )
        self.result = result


def check_storefront_database(db_path: str | Path) -> CheckResult:
    """The database's state against :data:`CHAIN`, read without changing it.

    The file is opened read-only, so a missing database is *absent* and is not
    created.
    """
    return check_sqlite_file(CHAIN, db_path)


def require_compatible_storefront_database(db_path: str | Path) -> None:
    """Refuse to serve a database not exactly at :data:`CHAIN`, naming the command."""
    result = check_storefront_database(db_path)
    if not result.compatible:
        raise IncompatibleStorefrontDatabase(result)
