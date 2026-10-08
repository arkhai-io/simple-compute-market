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
import uuid
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from core_storefront.domain_registry import StorefrontDomainRegistry
from core_storefront.sqlite_client import (
    SQLiteClient as CoreSQLiteClient,
)
from core_storefront.sqlite_migrations import MigrationLike
from arkhai_vms_listings.host_csv_importer import upsert_hosts_from_csv
from arkhai_vms_listings.resource_csv_importer import (
    SettlementClauseCompiler,
    upsert_resources_from_csv,
    upsert_resources_from_csv_content,
)
from market_contact_exchange import CONTACT_EXCHANGE_MIGRATIONS
from market_pool_overrides import pool_override_migrations
from market_settlement_runtime import settlement_migrations
from market_identity import Identity
from market_settlement_runtime import settlement_migrations

from market_storefront.payment_repository import VmPaymentRepository

from .config import BASE_URL_OVERRIDE, resolve_marketplace_signer, settings
from .migrations import (  # noqa: F401 — re-exported (tests import via here)
    VM_LEGACY_MIGRATION_INPUTS,
    VM_MIGRATIONS,
    synthesize_accepted_escrows_from_demand,
)

logger = logging.getLogger(__name__)


class SQLiteClient(VmPaymentRepository, CoreSQLiteClient):
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

    async def upsert_resource(
        self,
        *,
        resource_id: str,
        resource_type: str,
        resource_subtype: str | None = None,
        unit: str | None = None,
        value: int | float | None = None,
        state: str | None = None,
        attributes: dict[str, Any] | None = None,
        min_price: str | None = None,
        token: str | None = None,
        max_duration_seconds: int | None = None,
        accepted_escrows: list[dict[str, Any]] | None = None,
        settlements: list[dict[str, Any]] | None = None,
    ) -> None:
        """Create or update a generic resource snapshot row.

        For ``compute.gpu`` rows that reference a known local host via
        ``attributes.vm_host``, runs a capacity check against the host's
        gpu_count / vcpu_count / ram_gb / disk_gb totals. Raises
        ``CapacityExceededError`` if the new commitment would over-allocate
        the host. Slices without ``vm_host`` or pointing at unknown hosts
        pass through unchecked.
        """
        # Capacity gate — only for active compute.gpu slices.
        if resource_type == "compute.gpu" and (state is None or state != "deleted"):
            from market_storefront.services.resource_capacity_validator import (
                check_slice_fits_host,
            )

            attrs = attributes or {}
            await check_slice_fits_host(
                sqlite_client=self,
                resource_id=resource_id,
                host_name=attrs.get("vm_host"),
                gpu_count=int(value) if value is not None else None,
                vcpu_count=attrs.get("vcpu_count"),
                ram_gb=attrs.get("ram_gb"),
                disk_gb=attrs.get("disk_gb"),
            )

        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                now_iso = datetime.now().isoformat()
                cur.execute(
                    """
                    INSERT INTO resources(
                      resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                      min_price, token, max_duration_seconds, accepted_escrows, settlements,
                      created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(resource_id) DO UPDATE SET
                      resource_type=excluded.resource_type,
                      resource_subtype=excluded.resource_subtype,
                      unit=excluded.unit,
                      value=excluded.value,
                      state=excluded.state,
                      attributes=excluded.attributes,
                      min_price=excluded.min_price,
                      token=excluded.token,
                      max_duration_seconds=excluded.max_duration_seconds,
                      accepted_escrows=excluded.accepted_escrows,
                      settlements=excluded.settlements,
                      updated_at=excluded.updated_at
                    """,
                    (
                        resource_id,
                        resource_type,
                        resource_subtype,
                        unit,
                        value,
                        state,
                        json.dumps(attributes) if attributes is not None else None,
                        min_price,
                        token,
                        max_duration_seconds,
                        json.dumps(accepted_escrows)
                        if accepted_escrows is not None
                        else None,
                        json.dumps(settlements) if settlements is not None else None,
                        now_iso,
                        now_iso,
                    ),
                )
                if resource_type == "compute.gpu":
                    self._sync_compute_pool_for_resource(
                        cur,
                        resource_id=resource_id,
                        resource_subtype=resource_subtype,
                        value=value,
                        state=state,
                        attributes=attributes,
                        min_price=min_price,
                        token=token,
                        max_duration_seconds=max_duration_seconds,
                        accepted_escrows_json=(
                            json.dumps(accepted_escrows)
                            if accepted_escrows is not None
                            else None
                        ),
                        settlements_json=(
                            json.dumps(settlements) if settlements is not None else None
                        ),
                        now_iso=now_iso,
                    )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def list_resources(
        self,
        *,
        resource_type: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """List resource rows from local DB as generic DB-resource dicts."""

        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                clauses: list[str] = []
                params: list[Any] = []
                if resource_type is not None:
                    clauses.append("resource_type = ?")
                    params.append(resource_type)
                if state is not None:
                    clauses.append("state = ?")
                    params.append(state)
                else:
                    # Default listing omits soft-deleted resources.
                    clauses.append("(state IS NULL OR state != 'deleted')")
                where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                cur.execute(
                    f"""
                    SELECT resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                           min_price, token, max_duration_seconds, accepted_escrows, settlements,
                           created_at, updated_at
                    FROM resources
                    {where_clause}
                    ORDER BY updated_at DESC
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
                result: list[dict[str, Any]] = []
                for (
                    row_resource_id,
                    row_resource_type,
                    row_resource_subtype,
                    row_unit,
                    row_value,
                    row_state,
                    row_attributes,
                    row_min_price,
                    row_token,
                    row_max_duration_seconds,
                    row_accepted_escrows,
                    row_settlements,
                    row_created_at,
                    row_updated_at,
                ) in rows:
                    attrs: dict[str, Any] = {}
                    if isinstance(row_attributes, str) and row_attributes.strip():
                        try:
                            parsed = json.loads(row_attributes)
                            if isinstance(parsed, dict):
                                attrs = parsed
                        except Exception:
                            attrs = {}
                    accepted: list[dict[str, Any]] | None = None
                    if (
                        isinstance(row_accepted_escrows, str)
                        and row_accepted_escrows.strip()
                    ):
                        try:
                            parsed_ae = json.loads(row_accepted_escrows)
                            if isinstance(parsed_ae, list):
                                accepted = parsed_ae
                        except Exception:
                            accepted = None
                    parsed_settlements: list[dict[str, Any]] | None = None
                    if isinstance(row_settlements, str) and row_settlements.strip():
                        try:
                            value = json.loads(row_settlements)
                            if isinstance(value, list):
                                parsed_settlements = value
                        except Exception:
                            parsed_settlements = None
                    result.append(
                        {
                            "resource_id": row_resource_id,
                            "resource_type": row_resource_type,
                            "resource_subtype": row_resource_subtype,
                            "unit": row_unit,
                            "value": row_value,
                            "state": row_state,
                            "attributes": attrs,
                            "min_price": row_min_price,
                            "token": row_token,
                            "max_duration_seconds": row_max_duration_seconds,
                            "accepted_escrows": accepted,
                            "settlements": parsed_settlements,
                            "created_at": row_created_at,
                            "updated_at": row_updated_at,
                        }
                    )
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def upsert_resources_from_csv(
        self,
        *,
        csv_path: str,
        dry_run: bool = False,
        templates: dict[str, Any] | None = None,
        settlement_compiler: SettlementClauseCompiler | None = None,
    ) -> dict[str, Any]:
        """Import resources from CSV file and upsert rows into the resources table."""
        report = await upsert_resources_from_csv(
            csv_path=csv_path,
            sqlite_client=self,
            dry_run=dry_run,
            templates=templates,
            settlement_compiler=settlement_compiler,
        )
        return report.to_dict()

    async def upsert_resources_from_csv_content(
        self,
        *,
        csv_content: str,
        source_label: str = "<inline>",
        dry_run: bool = False,
        templates: dict[str, Any] | None = None,
        settlement_compiler: SettlementClauseCompiler | None = None,
    ) -> dict[str, Any]:
        """Import resources from a CSV string and upsert rows into the resources table.

        Used when CSV content is delivered via config injection (e.g. the Helm
        ``resources_csv_inline`` value in the per-agent Secret) rather than a
        file path baked into the container image.
        """
        report = await upsert_resources_from_csv_content(
            csv_content=csv_content,
            source_label=source_label,
            sqlite_client=self,
            dry_run=dry_run,
            templates=templates,
            settlement_compiler=settlement_compiler,
        )
        return report.to_dict()

    async def upsert_hosts_from_csv(
        self,
        *,
        csv_path: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import hosts from CSV and upsert rows into the hosts table."""
        report = await upsert_hosts_from_csv(
            csv_path=csv_path,
            sqlite_client=self,
            dry_run=dry_run,
        )
        return report.to_dict()

    # ------------------------------------------------------------------
    # Hosts CRUD — physical hosts owned by the seller
    # ------------------------------------------------------------------

    _HOST_COLUMNS = (
        "name",
        "cpu_type",
        "host_cpu_cores",
        "host_ram_gb",
        "host_disk_gb",
        "host_disk_type",
        "motherboard",
        "total_gpu_count",
        "gpu_model",
        "gpu_interconnect",
        "nic_speed_gbps",
        "internet_download_mbps",
        "internet_upload_mbps",
        "static_ip",
        "open_ports_count",
        "region",
        "datacenter_grade",
        "attributes",
        "enabled",
    )

    @staticmethod
    def _host_row_to_dict(row: tuple) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for col, val in zip(SQLiteClient._HOST_COLUMNS, row, strict=True):
            d[col] = val
        # Normalize types: bools come back as 0/1 ints
        for bcol in ("static_ip", "datacenter_grade", "enabled"):
            if d.get(bcol) is not None:
                d[bcol] = bool(d[bcol])
        # JSON-decode attributes if present
        raw_attrs = d.get("attributes")
        if isinstance(raw_attrs, str) and raw_attrs.strip():
            try:
                d["attributes"] = json.loads(raw_attrs)
            except json.JSONDecodeError:
                d["attributes"] = {}
        elif raw_attrs is None:
            d["attributes"] = None
        return d

    async def upsert_host(
        self,
        *,
        name: str,
        cpu_type: str | None = None,
        host_cpu_cores: int | None = None,
        host_ram_gb: int | None = None,
        host_disk_gb: int | None = None,
        host_disk_type: str | None = None,
        motherboard: str | None = None,
        total_gpu_count: int | None = None,
        gpu_model: str | None = None,
        gpu_interconnect: str | None = None,
        nic_speed_gbps: int | None = None,
        internet_download_mbps: int | None = None,
        internet_upload_mbps: int | None = None,
        static_ip: bool | None = None,
        open_ports_count: int | None = None,
        region: str | None = None,
        datacenter_grade: bool | None = None,
        attributes: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> None:
        """Create or update a host row."""

        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO hosts(
                      name, cpu_type, host_cpu_cores, host_ram_gb, host_disk_gb,
                      host_disk_type, motherboard, total_gpu_count, gpu_model,
                      gpu_interconnect, nic_speed_gbps, internet_download_mbps,
                      internet_upload_mbps, static_ip, open_ports_count, region,
                      datacenter_grade, attributes, enabled
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                      cpu_type=excluded.cpu_type,
                      host_cpu_cores=excluded.host_cpu_cores,
                      host_ram_gb=excluded.host_ram_gb,
                      host_disk_gb=excluded.host_disk_gb,
                      host_disk_type=excluded.host_disk_type,
                      motherboard=excluded.motherboard,
                      total_gpu_count=excluded.total_gpu_count,
                      gpu_model=excluded.gpu_model,
                      gpu_interconnect=excluded.gpu_interconnect,
                      nic_speed_gbps=excluded.nic_speed_gbps,
                      internet_download_mbps=excluded.internet_download_mbps,
                      internet_upload_mbps=excluded.internet_upload_mbps,
                      static_ip=excluded.static_ip,
                      open_ports_count=excluded.open_ports_count,
                      region=excluded.region,
                      datacenter_grade=excluded.datacenter_grade,
                      attributes=excluded.attributes,
                      enabled=excluded.enabled,
                      updated_at=STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        name,
                        cpu_type,
                        host_cpu_cores,
                        host_ram_gb,
                        host_disk_gb,
                        host_disk_type,
                        motherboard,
                        total_gpu_count,
                        gpu_model,
                        gpu_interconnect,
                        nic_speed_gbps,
                        internet_download_mbps,
                        internet_upload_mbps,
                        int(static_ip) if static_ip is not None else None,
                        open_ports_count,
                        region,
                        int(datacenter_grade) if datacenter_grade is not None else None,
                        json.dumps(attributes) if attributes is not None else None,
                        int(bool(enabled)),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

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

    async def get_host(self, *, name: str) -> dict[str, Any] | None:
        """Read a single host row by name."""
        cols = ", ".join(self._HOST_COLUMNS)

        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT {cols} FROM hosts WHERE name = ?", (name,))
                row = cur.fetchone()
                if row is None:
                    return None
                return self._host_row_to_dict(row)
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def apply_resource_transition(
        self,
        *,
        resource_id: str,
        event_type: str,
        idempotency_key: str,
        set_state: str,
    ) -> dict[str, Any]:
        """Record one state-transition event and set the resource's state.

        The event insert and the row update commit together. A repeated
        ``idempotency_key`` changes nothing and reports ``duplicate``; an
        unknown ``resource_id`` raises ``ValueError`` and rolls the event
        back, so no event outlives the row it describes.
        """
        event_id = str(uuid.uuid4())

        def _apply() -> dict[str, Any]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO resource_transition_events(
                      event_id, resource_id, event_type, set_state, idempotency_key
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(idempotency_key) DO NOTHING
                    """,
                    (event_id, resource_id, event_type, set_state, idempotency_key),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    return {
                        "applied": False,
                        "duplicate": True,
                        "resource_id": resource_id,
                        "event_id": event_id,
                        "idempotency_key": idempotency_key,
                    }

                cur.execute(
                    """
                    UPDATE resources
                    SET state = ?,
                        updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE resource_id = ?
                    """,
                    (set_state, resource_id),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"Resource not found: {resource_id}")

                conn.commit()
                return {
                    "applied": True,
                    "duplicate": False,
                    "resource_id": resource_id,
                    "event_id": event_id,
                    "idempotency_key": idempotency_key,
                }
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(_apply)

    @classmethod
    def _sync_compute_pool_for_resource(
        cls,
        cur: sqlite3.Cursor,
        *,
        resource_id: str,
        resource_subtype: str | None,
        value: Any,
        state: str | None,
        attributes: dict[str, Any] | None,
        min_price: str | None,
        token: str | None,
        max_duration_seconds: int | None,
        accepted_escrows_json: str | None,
        settlements_json: str | None,
        now_iso: str,
    ) -> str:
        attrs = attributes or {}
        pool_id = str(attrs.get("pool_id") or resource_id)
        try:
            gpu_count = int(value if value is not None else attrs.get("gpu_count", 1))
        except (TypeError, ValueError):
            gpu_count = 0
        gpu_count = max(gpu_count, 0)
        member_status = "deleted" if state == "deleted" else "active"
        cur.execute(
            """
            INSERT INTO compute_pool_members(
              member_id, pool_id, resource_id, site, provider_id, provider_resource_id,
              provider_host_id, gpu_count, status, attributes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(resource_id) DO UPDATE SET
              pool_id=excluded.pool_id,
              site=excluded.site,
              provider_id=excluded.provider_id,
              provider_resource_id=excluded.provider_resource_id,
              provider_host_id=excluded.provider_host_id,
              gpu_count=excluded.gpu_count,
              status=excluded.status,
              attributes=excluded.attributes,
              updated_at=excluded.updated_at
            """,
            (
                f"resource:{resource_id}",
                pool_id,
                resource_id,
                # (site, resource_id) is the aggregator's member key; NULL
                # means the storefront's home site.
                attrs.get("site"),
                attrs.get("provider_id"),
                attrs.get("provider_resource_id") or resource_id,
                attrs.get("vm_host"),
                gpu_count,
                member_status,
                json.dumps(attrs) if attrs else None,
                now_iso,
                now_iso,
            ),
        )
        cur.execute(
            """
            SELECT COALESCE(SUM(gpu_count), 0)
            FROM compute_pool_members
            WHERE pool_id = ? AND status = 'active'
            """,
            (pool_id,),
        )
        total_gpu_count = int(cur.fetchone()[0] or 0)
        pool_status = "active" if total_gpu_count > 0 else "deleted"
        cur.execute(
            """
            INSERT INTO compute_capacity_pools(
              pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
              status, allocation_policy, min_price, token, max_duration_seconds,
              accepted_escrows, settlements, created_at, updated_at
            )
            VALUES (?, 'compute.gpu', ?, ?, ?, ?, ?, 'first_fit', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pool_id) DO UPDATE SET
              gpu_model=COALESCE(excluded.gpu_model, compute_capacity_pools.gpu_model),
              region=COALESCE(excluded.region, compute_capacity_pools.region),
              sla=COALESCE(excluded.sla, compute_capacity_pools.sla),
              total_gpu_count=excluded.total_gpu_count,
              status=excluded.status,
              min_price=COALESCE(excluded.min_price, compute_capacity_pools.min_price),
              token=COALESCE(excluded.token, compute_capacity_pools.token),
              max_duration_seconds=COALESCE(excluded.max_duration_seconds, compute_capacity_pools.max_duration_seconds),
              accepted_escrows=COALESCE(excluded.accepted_escrows, compute_capacity_pools.accepted_escrows),
              settlements=COALESCE(excluded.settlements, compute_capacity_pools.settlements),
              updated_at=excluded.updated_at
            """,
            (
                pool_id,
                attrs.get("gpu_model") or resource_subtype,
                attrs.get("region"),
                attrs.get("sla"),
                total_gpu_count,
                pool_status,
                min_price,
                token,
                max_duration_seconds,
                accepted_escrows_json,
                settlements_json,
                now_iso,
                now_iso,
            ),
        )
        return pool_id

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
