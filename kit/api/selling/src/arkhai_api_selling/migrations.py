"""A quota-backed storefront's migration chain.

The chain composes core storefront's baseline, the settlement runtime's, and
the family's own, in that order, followed by core storefront's later
migrations. The family's tables are named from the domain's table prefix, a
constant of the composing storefront and not a setting, so one storefront's
database migrates to one schema under any configuration. The composing
storefront also names the family baseline's identifier: compatibility is the
exact set of recorded identifiers, so two storefronts whose prefixes differ
must record different ones for each to refuse the other's database. The chain
names no floor: no
database from before its baseline is supported, so the migration command
refuses every non-empty database it did not build. A later change to the
family's tables is a migration appended to :data:`MIGRATIONS`, never an edit to
the baseline.
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

from arkhai_api_selling.contributions import family_table

#: The purchase terms recorded for each thread: quantity and key target. The
#: terms are the vocabulary's shape, the same for every domain, so the table
#: carries no prefix.
TERMS_TABLE = "credit_deal_terms"

_PREFIXED_TABLES = (
    "settlement_evidence",
    "issuance_progress",
    "issuance_evidence",
    "private_results",
)


def _baseline_ddl(table_prefix: str) -> tuple[str, ...]:
    evidence = family_table(table_prefix, "settlement_evidence")
    progress = family_table(table_prefix, "issuance_progress")
    issuance_evidence = family_table(table_prefix, "issuance_evidence")
    private_results = family_table(table_prefix, "private_results")
    return (
        f"""
        CREATE TABLE {TERMS_TABLE} (
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
        f"""
        CREATE TABLE {evidence} (
          negotiation_id TEXT PRIMARY KEY,
          mechanism TEXT NOT NULL,
          agreement_digest TEXT NOT NULL,
          settlement_ref TEXT UNIQUE,
          status TEXT NOT NULL CHECK(status IN ('pending', 'verified', 'failed', 'refunding', 'refunded')),
          evidence TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE {progress} (
          negotiation_id TEXT PRIMARY KEY,
          public_ref TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL CHECK(status IN ('provisioning', 'ready', 'failed')),
          fulfillment_uid TEXT,
          public_result TEXT NOT NULL DEFAULT '{{}}',
          credentials_ref TEXT,
          reason TEXT,
          delivery_started_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE {issuance_evidence} (
          evidence_digest TEXT PRIMARY KEY,
          fulfillment_id TEXT NOT NULL UNIQUE,
          signed_evidence TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE {private_results} (
          credentials_ref TEXT PRIMARY KEY,
          fulfillment_id TEXT NOT NULL UNIQUE,
          owner_scheme TEXT NOT NULL,
          owner_id TEXT NOT NULL,
          key_id TEXT NOT NULL,
          secret TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """,
        f"CREATE INDEX idx_{table_prefix}_private_result_owner"
        f" ON {private_results}(owner_scheme, owner_id, credentials_ref)",
    )


def baseline_tables(table_prefix: str) -> frozenset[str]:
    """The tables the family baseline creates; it also adds the obligation
    columns and indexes to core's ``escrows``."""
    return frozenset(
        {TERMS_TABLE, *(family_table(table_prefix, name) for name in _PREFIXED_TABLES)}
    )


def storefront_baseline(
    table_prefix: str, *, baseline_id: str
) -> Migration[sqlite3.Connection]:
    """The family's tables under ``table_prefix``: accepted purchase terms,
    settlement evidence, issuance progress and evidence, and private results.

    ``baseline_id`` is the storefront's own and permanent once a database
    records it.
    """
    ddl = _baseline_ddl(table_prefix)

    def _create(connection: sqlite3.Connection) -> None:
        for statement in ddl:
            connection.execute(statement)

    return Migration(baseline_id, _create)


MIGRATIONS: tuple[Migration[sqlite3.Connection], ...] = ()
"""The family's migrations after its baseline, in the order they apply."""


def storefront_chain(
    table_prefix: str, *, baseline_id: str, service: str, command: str
) -> Chain[sqlite3.Connection]:
    """The chain a storefront whose bundle names ``table_prefix`` migrates and
    checks, named for that storefront and its migration command in every refusal.

    ``baseline_id`` identifies the family baseline in this storefront's
    databases; a storefront with another prefix names another, so neither
    reads the other's database as compatible. The chain takes constants alone,
    so a migration command builds it without composing the storefront's bundle
    or resolving its settings.
    """
    return Chain(
        service=service,
        command=command,
        baselines=(
            core_migrations.BASELINE,
            settlement_migrations.BASELINE,
            storefront_baseline(table_prefix, baseline_id=baseline_id),
        ),
        migrations=(*core_migrations.MIGRATIONS, *MIGRATIONS),
    )


def migrate_storefront_database(
    chain: Chain[sqlite3.Connection], db_path: str | Path
) -> MigrateReport:
    """Apply ``chain`` to the database at ``db_path``, creating it if absent.

    Refuses an ahead or unsupported database applying nothing
    (``MigrationRefused``), every database it did not build among them; a
    failing migration leaves the ones before it recorded (``MigrationFailed``).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        return migrate(chain, SqliteMigrationConnection(connection))
    finally:
        connection.close()


class IncompatibleStorefrontDatabase(RuntimeError):
    """The database is not exactly at the chain this image carries."""

    def __init__(self, chain: Chain[sqlite3.Connection], result: CheckResult) -> None:
        super().__init__(
            refusal_message(result, service=chain.service, command=chain.command)
        )
        self.result = result


def check_storefront_database(
    chain: Chain[sqlite3.Connection], db_path: str | Path
) -> CheckResult:
    """The database's state against ``chain``, read without changing it.

    The file is opened read-only, so a missing database is *absent* and is not
    created.
    """
    return check_sqlite_file(chain, db_path)


def require_compatible_storefront_database(
    chain: Chain[sqlite3.Connection], db_path: str | Path
) -> None:
    """Refuse to serve a database not exactly at ``chain``, naming the command."""
    result = check_storefront_database(chain, db_path)
    if not result.compatible:
        raise IncompatibleStorefrontDatabase(chain, result)


__all__ = [
    "MIGRATIONS",
    "TERMS_TABLE",
    "IncompatibleStorefrontDatabase",
    "baseline_tables",
    "check_storefront_database",
    "migrate_storefront_database",
    "require_compatible_storefront_database",
    "storefront_baseline",
    "storefront_chain",
]
