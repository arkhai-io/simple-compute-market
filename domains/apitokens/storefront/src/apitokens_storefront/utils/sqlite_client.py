"""API-tokens storefront SQLite client.

The domain-neutral market-state persistence lives in
``core_storefront.sqlite_client``; this subclass adds the one
domain-owned table: ``token_deal_terms``, the per-negotiation record of
what is being bought (quantity + key disposition, fixed at round 0).
The VM analog keeps duration on the shared thread row; tokens terms are
richer, so they live beside the thread keyed by negotiation_id —
settlement reads them back when it submits issuance.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient

from .config import settings


class SQLiteClient(CoreSQLiteClient):
    """Core market-state client + the API-tokens deal-terms table."""

    def _ensure_domain_tables(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS token_deal_terms (
              negotiation_id TEXT PRIMARY KEY,
              quantity INTEGER NOT NULL,
              key_mode TEXT NOT NULL DEFAULT 'new',
              key_id TEXT,
              created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )

    async def save_token_terms(
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
                    INSERT INTO token_deal_terms(negotiation_id, quantity, key_mode, key_id)
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

    async def load_token_terms(
        self, *, negotiation_id: str,
    ) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT negotiation_id, quantity, key_mode, key_id "
                    "FROM token_deal_terms WHERE negotiation_id = ?",
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


_sqlite_client: SQLiteClient | None = None


def get_sqlite_client() -> SQLiteClient:
    global _sqlite_client
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(db_path=settings.db_path)
    return _sqlite_client
