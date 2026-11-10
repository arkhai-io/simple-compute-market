"""VM storefront SQLite client.

Domain-neutral market-state persistence (listings, negotiations,
escrows, claims, publications, …) lives in
``core_storefront.sqlite_client``; this subclass adds the VM domain's
settlement records and listing-source reads, plus the settings-bound
module factory. The schema is the VM storefront's chain
(``market_storefront.utils.migrations``). It holds no physical inventory:
that is read from site projections.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from core_storefront.domain_registry import StorefrontDomainRegistry
from core_storefront.sqlite_client import (
    SQLiteClient as CoreSQLiteClient,
)

from market_storefront.payment_repository import VmSettlementRepository

from .config import settings

logger = logging.getLogger(__name__)


class SQLiteClient(VmSettlementRepository, CoreSQLiteClient):
    """Core market-state client + the VM domain's settlement and listing state."""

    def __init__(
        self,
        db_path: str,
        *,
        registry: StorefrontDomainRegistry,
    ) -> None:
        if not isinstance(registry, StorefrontDomainRegistry):
            raise TypeError("registry must be a StorefrontDomainRegistry")
        self._domain_registry = registry
        super().__init__(db_path)

    @property
    def domain_registry(self) -> StorefrontDomainRegistry:
        """Return the immutable startup registry governing durable bindings."""

        return self._domain_registry

    _ESCROW_COLS = (
        *CoreSQLiteClient._ESCROW_COLS,
        "obligation_ref",
        "obligation_index",
    )

    async def list_listing_source_envelopes(
        self, *, offering_mode: str
    ) -> list[tuple[str, dict[str, Any]]]:
        """Each bound listing of ``offering_mode`` with its parsed source envelope.

        A binding whose stored envelope is not a JSON object is skipped: it names
        no source a reader could act on.
        """

        def _load() -> list[tuple[str, dict[str, Any]]]:
            conn = sqlite3.connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT listing_id, source_envelope_json "
                    "FROM storefront_listing_bindings WHERE offering_mode = ?",
                    (offering_mode,),
                ).fetchall()
            finally:
                conn.close()
            out: list[tuple[str, dict[str, Any]]] = []
            for listing_id, raw in rows:
                try:
                    envelope = json.loads(raw or "")
                except json.JSONDecodeError:
                    continue
                if isinstance(envelope, dict):
                    out.append((str(listing_id), envelope))
            return out

        return await asyncio.to_thread(_load)

    async def bind_escrow_obligation(
        self,
        *,
        escrow_uid: str,
        obligation_ref: str,
        obligation_index: int,
    ) -> dict[str, Any]:
        """Persist the verified obligation identity without permitting rebinding."""
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

    # ------------------------------------------------------------------
    # Capacity holds — two-phase reserve bookkeeping. The hold itself
    # lives in the capacity ledger (a TTL'd reserved allocation); this
    # table only remembers which allocation a negotiation's acceptance
    # placed, so settlement can commit it instead of reserving fresh.
    # ------------------------------------------------------------------


_sqlite_client: SQLiteClient | None = None


def get_sqlite_client(*, registry: StorefrontDomainRegistry) -> SQLiteClient:
    global _sqlite_client
    if not isinstance(registry, StorefrontDomainRegistry):
        raise TypeError("registry must be a StorefrontDomainRegistry")
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(db_path=settings.db_path, registry=registry)
    elif _sqlite_client.domain_registry is not registry:
        raise RuntimeError(
            "SQLite client is already bound to a different storefront "
            "domain registry object"
        )
    return _sqlite_client
