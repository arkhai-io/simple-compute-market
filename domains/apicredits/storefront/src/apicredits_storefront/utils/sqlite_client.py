"""API-credits storefront SQLite client.

The domain-neutral market-state persistence lives in
``core_storefront.sqlite_client``. This subclass adds
``credit_deal_terms`` and the immutable public-row link to the shared
settlement obligation. Quantity and key disposition are fixed at round
zero and read back when settlement submits issuance.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import Any

from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from core_storefront.sqlite_migrations import MigrationLike
from market_identity import Identity
from market_settlement_runtime import settlement_migrations

from .config import settings
from .migrations import APICREDITS_MIGRATIONS


class SQLiteClient(CoreSQLiteClient):
    """Core market-state client + the API-credits deal-terms table."""

    _ESCROW_COLS = (
        *CoreSQLiteClient._ESCROW_COLS,
        "obligation_ref",
        "obligation_index",
    )

    def _domain_migrations(self) -> tuple[MigrationLike, ...]:
        return (*settlement_migrations(), *APICREDITS_MIGRATIONS)

    def _ensure_domain_tables(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_deal_terms (
              negotiation_id TEXT PRIMARY KEY,
              quantity INTEGER NOT NULL,
              key_mode TEXT NOT NULL DEFAULT 'new',
              key_id TEXT,
              created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
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


def get_sqlite_client(
    *,
    local_listing_principal: Identity | None = None,
    expected_legacy_sellers: tuple[str, ...] | None = None,
) -> SQLiteClient:
    global _sqlite_client
    if _sqlite_client is None and (
        local_listing_principal is None or expected_legacy_sellers is None
    ):
        raise RuntimeError(
            "initial SQLite composition requires local listing migration context",
        )
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(
            db_path=settings.db_path,
            local_listing_principal=local_listing_principal,
            expected_legacy_sellers=expected_legacy_sellers,
        )
    return _sqlite_client
