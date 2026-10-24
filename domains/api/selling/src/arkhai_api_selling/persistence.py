"""A quota-backed storefront's persistence: the core market-state client plus the family's tables.

The settlement-evidence, issuance-progress, issuance-evidence, and private-result
tables are named from the bundle's prefix. The purchase terms a thread records
are the vocabulary's shape, the same for every domain, so their table carries
no prefix.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import Any

from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from core_storefront.sqlite_migrations import Migration, MigrationLike
from market_core import SettlementEvidence
from market_identity import Identity
from market_settlement_runtime import settlement_migrations

from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.settlement_store import SettlementRepository

ESCROW_SETTLEMENT_IDENTITY_MIGRATION = "20260810_001_escrow_settlement_identity"
ISSUANCE_EVIDENCE_MIGRATION = "20260815_002_issuance_evidence"

#: The purchase terms recorded for each thread: quantity and key target.
TERMS_TABLE = "credit_deal_terms"


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


def _migrate_issuance_evidence(conn: sqlite3.Connection, contributions: SellingContributions) -> None:
    evidence = contributions.table("settlement_evidence")
    progress = contributions.table("issuance_progress")
    issuance_evidence = contributions.table("issuance_evidence")
    private_results = contributions.table("private_results")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {evidence} (
          negotiation_id TEXT PRIMARY KEY,
          mechanism TEXT NOT NULL,
          agreement_digest TEXT NOT NULL,
          settlement_ref TEXT UNIQUE,
          status TEXT NOT NULL CHECK(status IN ('pending', 'verified', 'failed', 'refunding', 'refunded')),
          evidence TEXT NOT NULL
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {progress} (
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
    """)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {issuance_evidence} (
          evidence_digest TEXT PRIMARY KEY,
          fulfillment_id TEXT NOT NULL UNIQUE,
          signed_evidence TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {private_results} (
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
        f"CREATE INDEX IF NOT EXISTS idx_{contributions.table_prefix}_private_result_owner "
        f"ON {private_results}(owner_scheme, owner_id, credentials_ref)"
    )


def migrations(contributions: SellingContributions) -> tuple[Migration, ...]:
    """The storefront's own migration chain, its identifiers fixed whatever the prefix."""
    return (
        Migration(ESCROW_SETTLEMENT_IDENTITY_MIGRATION, _migrate_escrow_settlement_identity),
        Migration(
            ISSUANCE_EVIDENCE_MIGRATION,
            lambda conn: _migrate_issuance_evidence(conn, contributions),
        ),
    )


def write_credit_terms(
    conn: sqlite3.Connection,
    *,
    negotiation_id: str,
    quantity: int,
    key_mode: str,
    key_id: str | None = None,
) -> None:
    """Record a thread's purchase terms inside the caller's open transaction."""
    conn.execute(
        f"""
        INSERT INTO {TERMS_TABLE}(negotiation_id, quantity, key_mode, key_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(negotiation_id) DO UPDATE SET
          quantity=excluded.quantity,
          key_mode=excluded.key_mode,
          key_id=excluded.key_id
        """,
        (negotiation_id, int(quantity), key_mode, key_id),
    )


class StorefrontSQLiteClient(CoreSQLiteClient):
    """Core market-state client plus the family's deal-terms, settlement, and escrow identity."""

    _ESCROW_COLS = (
        *CoreSQLiteClient._ESCROW_COLS,
        "obligation_ref",
        "obligation_index",
    )

    def __init__(
        self,
        db_path: str,
        contributions: SellingContributions,
        *,
        local_listing_principal: Identity | None = None,
        expected_legacy_sellers: tuple[str, ...] = (),
    ) -> None:
        # The core constructor migrates the database, which reads the bundle.
        self._contributions = contributions
        super().__init__(
            db_path,
            local_listing_principal=local_listing_principal,
            expected_legacy_sellers=expected_legacy_sellers,
        )

    @property
    def contributions(self) -> SellingContributions:
        return self._contributions

    def _domain_migrations(self) -> tuple[MigrationLike, ...]:
        return (*settlement_migrations(), *migrations(self._contributions))

    def _ensure_domain_tables(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TERMS_TABLE} (
              negotiation_id TEXT PRIMARY KEY,
              quantity INTEGER NOT NULL,
              key_mode TEXT NOT NULL DEFAULT 'new',
              key_id TEXT,
              created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )

    def _ensure_domain_indexes(self, cur: sqlite3.Cursor) -> None:
        noun = self._contributions.refusal_noun
        for table, columns in {
            self._contributions.table("settlement_evidence"): {
                "negotiation_id", "mechanism", "agreement_digest", "settlement_ref", "status", "evidence",
            },
            self._contributions.table("issuance_progress"): {
                "negotiation_id", "public_ref", "status", "fulfillment_uid", "public_result",
                "credentials_ref", "delivery_started_at",
            },
        }.items():
            actual = {str(row[1]) for row in cur.execute(f"PRAGMA table_info({table})")}
            if not columns <= actual:
                raise RuntimeError(
                    f"incompatible {noun} settlement schema; explicitly reset the database"
                )
        # Every capacity effect, reconciliation, and recheck reads a listing's
        # durable binding, and a listing created before bindings were recorded
        # has none to read. There is no record to derive one from, so such a
        # database is refused rather than adopted.
        unbound = cur.execute(
            """
            SELECT l.listing_id FROM listings l
            LEFT JOIN storefront_listing_bindings b ON b.listing_id = l.listing_id
            WHERE b.listing_id IS NULL
            ORDER BY l.listing_id LIMIT 1
            """
        ).fetchone()
        if unbound is not None:
            raise RuntimeError(
                f"{noun} listing {unbound[0]!r} has no durable listing binding; "
                "this storefront requires a fresh database"
            )

    def _settlement(self) -> SettlementRepository:
        return SettlementRepository(self.db_path, self._contributions)

    async def save_settlement_evidence(self, evidence: SettlementEvidence) -> SettlementEvidence:
        return await asyncio.to_thread(self._settlement().store, evidence)

    async def load_settlement_evidence(self, *, negotiation_id: str) -> SettlementEvidence | None:
        return await asyncio.to_thread(self._settlement().get, negotiation_id)

    async def load_issuance_progress(self, *, reference: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._settlement().progress, reference)

    async def save_issuance_progress(self, *, negotiation_id: str, **fields: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._settlement().checkpoint, negotiation_id, **fields)

    async def claim_credit_delivery_start(self, *, negotiation_id: str) -> bool:
        return await asyncio.to_thread(self._settlement().claim_delivery_start, negotiation_id)

    async def record_credit_refund_intent(self, *, negotiation_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._settlement().record_refund_intent, negotiation_id)

    async def abandon_credit_refund_intent(self, *, negotiation_id: str, prior_status: str) -> None:
        await asyncio.to_thread(
            self._settlement().abandon_refund_intent, negotiation_id, prior_status=prior_status,
        )

    async def complete_credit_refund(self, *, negotiation_id: str) -> None:
        await asyncio.to_thread(self._settlement().complete_refund, negotiation_id)

    async def list_unsettled_payment_negotiations(self, *, mechanism: str, limit: int) -> list[str]:
        """Accepted deals of ``mechanism`` with no verified receipt, open credit issuance, or a refund left `refunding`."""
        return await asyncio.to_thread(
            self._settlement().unsettled_negotiations, mechanism=mechanism, limit=limit,
        )

    async def save_credit_terms(
        self,
        *,
        negotiation_id: str,
        quantity: int,
        key_mode: str,
        key_id: str | None = None,
    ) -> None:
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                write_credit_terms(
                    conn,
                    negotiation_id=negotiation_id,
                    quantity=quantity,
                    key_mode=key_mode,
                    key_id=key_id,
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def load_credit_terms(
        self,
        *,
        negotiation_id: str,
    ) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT negotiation_id, quantity, key_mode, key_id "
                    f"FROM {TERMS_TABLE} WHERE negotiation_id = ?",
                    (negotiation_id,),
                ).fetchone()
            finally:
                conn.close()
            if row is None:
                return None
            return {
                "negotiation_id": row[0],
                "quantity": int(row[1]),
                "key_mode": row[2],
                "key_id": row[3],
            }

        return await asyncio.to_thread(_load)

    async def bind_escrow_obligation(
        self,
        *,
        escrow_uid: str,
        obligation_ref: str,
        obligation_index: int,
    ) -> dict[str, Any]:
        """Persist verified obligation identity without permitting rebinding."""
        if not obligation_ref.strip():
            raise ValueError("obligation_ref must not be empty")
        if obligation_index < 0:
            raise ValueError("obligation_index must be non-negative")

        def _bind() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT obligation_ref, obligation_index FROM escrows "
                    "WHERE escrow_uid = ?",
                    (escrow_uid,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown escrow {escrow_uid}")
                existing_ref, existing_index = row
                if existing_ref is not None and (
                    str(existing_ref) != obligation_ref
                    or int(existing_index) != obligation_index
                ):
                    raise ValueError(
                        f"escrow {escrow_uid} is already bound to a different obligation"
                    )
                conn.execute(
                    "UPDATE escrows SET obligation_ref = ?, obligation_index = ?, "
                    "updated_at = ? WHERE escrow_uid = ?",
                    (
                        obligation_ref,
                        obligation_index,
                        datetime.now().isoformat(),
                        escrow_uid,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        await asyncio.to_thread(_bind)
        row = await self.load_escrow(escrow_uid=escrow_uid)
        if row is None:
            raise RuntimeError(f"escrow {escrow_uid} disappeared after binding")
        return row


__all__ = [
    "ESCROW_SETTLEMENT_IDENTITY_MIGRATION",
    "ISSUANCE_EVIDENCE_MIGRATION",
    "TERMS_TABLE",
    "StorefrontSQLiteClient",
    "migrations",
    "write_credit_terms",
]
