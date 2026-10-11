"""VM storefront SQLite client.

Domain-neutral market-state persistence (listings, negotiations,
escrows, claims, publications, …) lives in
``core_storefront.sqlite_client``; this subclass adds the VM domain's
inventory surface — resources/hosts/pools, the embedded compute
allocation ledger and derived-listing bookkeeping — plus the
settings-bound module factory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from core_storefront.domain_registry import StorefrontDomainRegistry
from core_storefront.sqlite_client import (
    SQLiteClient as CoreSQLiteClient,
)
from core_storefront.sqlite_migrations import MigrationLike
from market_contact_exchange import CONTACT_EXCHANGE_MIGRATIONS
from market_pool_overrides import pool_override_migrations
from market_settlement_runtime import settlement_migrations
from market_identity import Identity

from market_storefront.payment_repository import VmSettlementRepository, add_vm_settlement_records

from .config import BASE_URL_OVERRIDE, resolve_marketplace_signer, settings
from .migrations import (  # noqa: F401 — re-exported (tests import via here)
    VM_LEGACY_MIGRATION_INPUTS,
    VM_MIGRATIONS,
    synthesize_accepted_escrows_from_demand,
)

logger = logging.getLogger(__name__)


class SQLiteClient(VmSettlementRepository, CoreSQLiteClient):
    """Core market-state client + the VM domain's inventory tables."""

    def __init__(
        self,
        db_path: str,
        *,
        registry: StorefrontDomainRegistry,
        local_listing_principal: Identity | None = None,
        expected_legacy_sellers: Collection[str] = (),
        extra_migrations: Sequence[MigrationLike] = (),
    ) -> None:
        if not isinstance(registry, StorefrontDomainRegistry):
            raise TypeError("registry must be a StorefrontDomainRegistry")
        self._domain_registry = registry
        super().__init__(
            db_path,
            local_listing_principal=local_listing_principal,
            expected_legacy_sellers=expected_legacy_sellers,
            extra_migrations=extra_migrations,
            legacy_migration_inputs=VM_LEGACY_MIGRATION_INPUTS,
        )

    @property
    def domain_registry(self) -> StorefrontDomainRegistry:
        """Return the immutable startup registry governing durable bindings."""

        return self._domain_registry

    _ESCROW_COLS = (
        *CoreSQLiteClient._ESCROW_COLS,
        "obligation_ref",
        "obligation_index",
    )

    def _domain_migrations(self) -> tuple[MigrationLike, ...]:
        return (
            *settlement_migrations(),
            *CONTACT_EXCHANGE_MIGRATIONS,
            *pool_override_migrations(),
            *VM_MIGRATIONS,
        )

    def _ensure_domain_tables(self, cur: sqlite3.Cursor) -> None:
        # Resources table (local source of truth across all resource types).
        # min_price/token/max_duration_seconds are per-offering: each row
        # carries the price + max-duration ceiling the operator wants per
        # published listing for that resource. NULLs fall back to
        # [seller.pricing] defaults at publish time.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
              pk INTEGER PRIMARY KEY AUTOINCREMENT,
              resource_id TEXT NOT NULL UNIQUE,
              resource_type TEXT NOT NULL,
              resource_subtype TEXT,
              unit TEXT,
              value NUMERIC,
              state TEXT,
              attributes TEXT,
              min_price TEXT,
              token TEXT,
              max_duration_seconds INTEGER,
              accepted_escrows TEXT,
              settlements TEXT,
              created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
              updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        # Idempotent migration for existing databases that pre-date these
        # columns. ALTER TABLE ADD COLUMN raises OperationalError if the
        # column already exists.
        for col_ddl in (
            "ALTER TABLE resources ADD COLUMN min_price TEXT",
            "ALTER TABLE resources ADD COLUMN token TEXT",
            "ALTER TABLE resources ADD COLUMN max_duration_seconds INTEGER",
            "ALTER TABLE resources ADD COLUMN accepted_escrows TEXT",
            "ALTER TABLE resources ADD COLUMN settlements TEXT",
        ):
            try:
                cur.execute(col_ddl)
            except sqlite3.OperationalError:
                pass
        # Keep resources.updated_at fresh whenever rows are updated.
        cur.execute("DROP TRIGGER IF EXISTS trg_resources_updated_at")
        cur.execute(
            """
            CREATE TRIGGER trg_resources_updated_at
            AFTER UPDATE ON resources
            FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
            BEGIN
              UPDATE resources
              SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
              WHERE resource_id = NEW.resource_id;
            END
            """
        )
        # Hosts table (one row per physical host the seller owns).
        # Mirrors provisioning-service's hosts inventory + adds marketing
        # metadata (cpu_type, motherboard, host capacity totals, network)
        # that the provisioning-service doesn't track. Compute slice
        # resources reference a host by name via attributes.vm_host.
        #
        # Capacity invariants are checked at publish time, not enforced
        # by SQLite — sum of active resources' gpu_count/vcpu_count/
        # ram_gb/disk_gb per host must not exceed the host totals.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS hosts (
              name TEXT PRIMARY KEY,
              cpu_type TEXT,
              host_cpu_cores INTEGER,
              host_ram_gb INTEGER,
              host_disk_gb INTEGER,
              host_disk_type TEXT,
              motherboard TEXT,
              total_gpu_count INTEGER,
              gpu_model TEXT,
              gpu_interconnect TEXT,
              nic_speed_gbps INTEGER,
              internet_download_mbps INTEGER,
              internet_upload_mbps INTEGER,
              static_ip INTEGER,
              open_ports_count INTEGER,
              region TEXT,
              datacenter_grade INTEGER,
              attributes TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
              updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_hosts_updated_at
            AFTER UPDATE ON hosts
            FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
            BEGIN
              UPDATE hosts
              SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
              WHERE name = NEW.name;
            END
            """
        )
        # Resource transition events (append-only, idempotent)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_transition_events (
              pk INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT NOT NULL UNIQUE,
              resource_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              set_value NUMERIC,
              set_state TEXT,
              set_attribute_json TEXT,
              idempotency_key TEXT NOT NULL UNIQUE,
              occurred_at TIMESTAMPTZ NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
              FOREIGN KEY(resource_id) REFERENCES resources(resource_id)
            )
            """
        )
        add_vm_settlement_records(cur)

    def _ensure_domain_indexes(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_resources_resource_id ON resources(resource_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_resources_type_subtype ON resources(resource_type, resource_subtype)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_resources_state ON resources(state)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_resources_updated_at ON resources(updated_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_resource_transition_events_resource_time ON resource_transition_events(resource_id, occurred_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_resource_transition_events_type_time ON resource_transition_events(event_type, occurred_at)"
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
        signer = resolve_marketplace_signer()
        _sqlite_client = SQLiteClient(
            db_path=settings.db_path,
            registry=registry,
            local_listing_principal=signer.identity,
            expected_legacy_sellers=(BASE_URL_OVERRIDE,),
        )
    elif _sqlite_client.domain_registry is not registry:
        raise RuntimeError(
            "SQLite client is already bound to a different storefront "
            "domain registry object"
        )
    return _sqlite_client
