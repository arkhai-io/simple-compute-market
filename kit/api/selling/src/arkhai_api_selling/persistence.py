"""A quota-backed storefront's persistence: the core market-state client plus the family's tables.

The settlement-evidence, issuance-progress, issuance-evidence, and private-result
tables are named from the bundle's prefix. The purchase terms a thread records
are the vocabulary's shape, the same for every domain, so their table carries
no prefix. The client issues no DDL: ``arkhai_api_selling.migrations`` owns the
schema, which the storefront's migration command builds before it serves.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from core_storefront.sqlite_client import store_timestamp
from market_core import SettlementEvidence

from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.migrations import TERMS_TABLE
from arkhai_api_selling.settlement_store import SettlementRepository


def refuse_unbound_listings(db_path: str, contributions: SellingContributions) -> None:
    """Refuse a database holding a listing with no durable binding.

    Every capacity path reads a listing's durable binding, and none can be
    derived for a listing recorded without one. The refusal concerns data, not
    schema, so it runs at startup on a migrated database.
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
            f"{contributions.refusal_noun} listing {unbound[0]!r} has no durable listing binding; "
            "this storefront requires a fresh database"
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

    def __init__(self, db_path: str, contributions: SellingContributions) -> None:
        super().__init__(db_path)
        self._contributions = contributions

    @property
    def contributions(self) -> SellingContributions:
        return self._contributions

    def _settlement(self) -> SettlementRepository:
        return SettlementRepository(self.db_path, self._contributions)

    async def save_settlement_evidence(self, evidence: SettlementEvidence) -> SettlementEvidence:
        return await asyncio.to_thread(self._settlement().store, evidence)

    async def load_settlement_evidence(self, *, negotiation_id: str) -> SettlementEvidence | None:
        return await asyncio.to_thread(self._settlement().get, negotiation_id)

    async def load_settlement_evidence_by_ref(self, *, settlement_ref: str) -> SettlementEvidence | None:
        return await asyncio.to_thread(self._settlement().get_by_reference, settlement_ref)

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
                        store_timestamp(),
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
    "TERMS_TABLE",
    "StorefrontSQLiteClient",
    "refuse_unbound_listings",
    "write_credit_terms",
]
