"""API-credits storefront SQLite client.

The domain-neutral market-state persistence lives in
``core_storefront.sqlite_client``. This subclass adds
accepted credit terms, negotiation-bound settlement evidence and issuance
progress. Source evidence, shared Alkahest servicing and private delivery
results have separate repositories.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import Any

from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient

from apicredits_storefront.settlement_repository import SettlementRepository
from market_core import SettlementEvidence

from .config import settings


class SQLiteClient(CoreSQLiteClient):
    """Core market-state client + the API-credits deal-terms table."""

    _ESCROW_COLS = (
        *CoreSQLiteClient._ESCROW_COLS,
        "obligation_ref",
        "obligation_index",
    )

    async def save_settlement_evidence(self, evidence: SettlementEvidence) -> SettlementEvidence:
        return await asyncio.to_thread(SettlementRepository(self.db_path).store, evidence)

    async def load_settlement_evidence(self, *, negotiation_id: str) -> SettlementEvidence | None:
        return await asyncio.to_thread(SettlementRepository(self.db_path).get, negotiation_id)

    async def load_settlement_evidence_by_ref(self, *, settlement_ref: str) -> SettlementEvidence | None:
        return await asyncio.to_thread(SettlementRepository(self.db_path).get_by_reference, settlement_ref)

    async def load_issuance_progress(self, *, reference: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(SettlementRepository(self.db_path).progress, reference)

    async def save_issuance_progress(self, *, negotiation_id: str, **fields: Any) -> dict[str, Any]:
        return await asyncio.to_thread(SettlementRepository(self.db_path).checkpoint, negotiation_id, **fields)

    async def claim_credit_delivery_start(self, *, negotiation_id: str) -> bool:
        return await asyncio.to_thread(SettlementRepository(self.db_path).claim_delivery_start, negotiation_id)

    async def record_credit_refund_intent(self, *, negotiation_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(SettlementRepository(self.db_path).record_refund_intent, negotiation_id)

    async def abandon_credit_refund_intent(self, *, negotiation_id: str, prior_status: str) -> None:
        await asyncio.to_thread(
            SettlementRepository(self.db_path).abandon_refund_intent, negotiation_id, prior_status=prior_status,
        )

    async def complete_credit_refund(self, *, negotiation_id: str) -> None:
        await asyncio.to_thread(SettlementRepository(self.db_path).complete_refund, negotiation_id)

    async def list_unsettled_payment_negotiations(self, *, mechanism: str, limit: int) -> list[str]:
        """Accepted deals of ``mechanism`` with no verified receipt, open credit issuance, or a refund left `refunding`."""
        return await asyncio.to_thread(
            SettlementRepository(self.db_path).unsettled_negotiations, mechanism=mechanism, limit=limit,
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
                conn.execute(
                    """
                    INSERT INTO credit_deal_terms(negotiation_id, quantity, key_mode, key_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(negotiation_id) DO UPDATE SET
                      quantity=excluded.quantity,
                      key_mode=excluded.key_mode,
                      key_id=excluded.key_id
                    """,
                    (negotiation_id, int(quantity), key_mode, key_id),
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
                    "FROM credit_deal_terms WHERE negotiation_id = ?",
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


_sqlite_client: SQLiteClient | None = None


def refuse_unbound_listings(db_path: str) -> None:
    """Refuse a database holding a listing with no durable binding.

    Every capacity effect, reconciliation, and recheck reads a listing's
    durable binding, and a listing created before bindings were recorded has
    none to read. There is no record to derive one from, so such a database is
    refused rather than served. The refusal concerns data, not schema, so it
    runs at startup on a migrated database.
    """
    conn = sqlite3.connect(db_path)
    try:
        unbound = conn.execute(
            """
            SELECT l.listing_id FROM listings l
            LEFT JOIN storefront_listing_bindings b ON b.listing_id = l.listing_id
            WHERE b.listing_id IS NULL
            ORDER BY l.listing_id LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if unbound is not None:
        raise RuntimeError(
            f"API-credit listing {unbound[0]!r} has no durable listing binding; "
            "this storefront requires a fresh database"
        )


def get_sqlite_client() -> SQLiteClient:
    global _sqlite_client
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(db_path=settings.db_path)
    return _sqlite_client
