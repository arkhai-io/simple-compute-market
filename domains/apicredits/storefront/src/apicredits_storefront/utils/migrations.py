"""API-credit storefront schema migrations."""

from __future__ import annotations

import sqlite3

from core_storefront.sqlite_migrations import Migration


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_escrow_settlement_identity(conn: sqlite3.Connection) -> None:
    """Bind each public settlement job to its exact accepted obligation."""
    columns = _column_names(conn, "escrows")
    if "obligation_ref" not in columns:
        conn.execute("ALTER TABLE escrows ADD COLUMN obligation_ref TEXT")
    if "obligation_index" not in columns:
        conn.execute("ALTER TABLE escrows ADD COLUMN obligation_index INTEGER")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_escrows_obligation_ref "
        "ON escrows(obligation_ref) WHERE obligation_ref IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_credit_escrows_negotiation_obligation "
        "ON escrows(negotiation_id, obligation_index)"
    )


def _migrate_issuance_evidence(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_credit_issuance_evidence (
          evidence_digest TEXT PRIMARY KEY,
          fulfillment_id TEXT NOT NULL UNIQUE,
          signed_evidence TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_credit_private_results (
          credentials_ref TEXT PRIMARY KEY,
          fulfillment_id TEXT NOT NULL UNIQUE,
          owner_scheme TEXT NOT NULL,
          owner_id TEXT NOT NULL,
          key_id TEXT NOT NULL,
          secret TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_credit_private_result_owner "
        "ON api_credit_private_results(owner_scheme, owner_id, credentials_ref)"
    )


APICREDITS_MIGRATIONS = (
    Migration(
        "20260810_001_escrow_settlement_identity",
        _migrate_escrow_settlement_identity,
    ),
    Migration(
        "20260815_002_issuance_evidence",
        _migrate_issuance_evidence,
    ),
)
