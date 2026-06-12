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
from datetime import datetime
from typing import Any

from core_storefront.sqlite_client import (  # noqa: F401 — re-exported
    SQLiteClient as CoreSQLiteClient,
    _amount_from_db_text,
    _amount_to_db_text,
    _publication_row_to_dict,
)
from core_storefront.sqlite_migrations import Migration
from domains.vms.listings.host_csv_importer import upsert_hosts_from_csv
from domains.vms.listings.resource_csv_importer import (
    upsert_resources_from_csv,
    upsert_resources_from_csv_content,
)

from .config import settings
from .migrations import (  # noqa: F401 — re-exported (tests import via here)
    VM_MIGRATIONS,
    synthesize_accepted_escrows_from_demand,
)

logger = logging.getLogger(__name__)


class SQLiteClient(CoreSQLiteClient):
    """Core market-state client + the VM domain's inventory tables."""

    def _domain_migrations(self) -> tuple[Migration, ...]:
        return VM_MIGRATIONS

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
        # Compute allocation ledger. Resource rows describe advertised or
        # import-time capacity; this table records execution holds against
        # that capacity so a 4x GPU pool can satisfy smaller leases without
        # treating the entire row as unavailable.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS compute_allocations (
              allocation_id TEXT PRIMARY KEY,
              pool_id TEXT,
              member_id TEXT,
              resource_id TEXT NOT NULL,
              listing_id TEXT,
              escrow_uid TEXT,
              gpu_count INTEGER NOT NULL,
              state TEXT NOT NULL,
              provider_id TEXT,
              provider_job_id TEXT,
              provider_lease_id TEXT,
              provider_resource_id TEXT,
              vm_host TEXT,
              vm_target TEXT,
              lease_end_utc TEXT,
              hold_expires_at TEXT,
              failure_reason TEXT,
              failure_message TEXT,
              logs_ref TEXT,
              check_job_id TEXT,
              created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
              updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
              released_at TEXT,
              FOREIGN KEY(resource_id) REFERENCES resources(resource_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_compute_allocations_updated_at
            AFTER UPDATE ON compute_allocations
            FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
            BEGIN
              UPDATE compute_allocations
              SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
              WHERE allocation_id = NEW.allocation_id;
            END
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS derived_compute_listings (
              listing_id TEXT PRIMARY KEY,
              pool_id TEXT,
              resource_id TEXT NOT NULL,
              gpu_count INTEGER NOT NULL,
              status TEXT NOT NULL,
              derivation_key TEXT NOT NULL UNIQUE,
              last_reconciled_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )

    def _ensure_domain_indexes(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_resource "
            "ON derived_compute_listings(resource_id, gpu_count)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_pool "
            "ON derived_compute_listings(pool_id, gpu_count)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_status "
            "ON derived_compute_listings(status)"
        )
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
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_compute_allocations_resource_state ON compute_allocations(resource_id, state)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_compute_allocations_pool_state ON compute_allocations(pool_id, state)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_compute_allocations_member_state ON compute_allocations(member_id, state)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_compute_allocations_escrow_uid ON compute_allocations(escrow_uid)"
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
            from domains.vms.provisioning.capacity import check_slice_fits_host
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
                      min_price, token, max_duration_seconds, accepted_escrows, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(accepted_escrows) if accepted_escrows is not None else None,
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
                           min_price, token, max_duration_seconds, accepted_escrows, created_at, updated_at
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
                    if isinstance(row_accepted_escrows, str) and row_accepted_escrows.strip():
                        try:
                            parsed_ae = json.loads(row_accepted_escrows)
                            if isinstance(parsed_ae, list):
                                accepted = parsed_ae
                        except Exception:
                            accepted = None
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
                            "created_at": row_created_at,
                            "updated_at": row_updated_at,
                        }
                    )
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def get_resource(self, *, resource_id: str) -> dict[str, Any] | None:
        """Fetch a single resource row by resource_id."""
        def _load_one() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                           min_price, token, max_duration_seconds, created_at, updated_at
                    FROM resources
                    WHERE resource_id = ?
                    LIMIT 1
                    """,
                    (resource_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                (
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
                    row_created_at,
                    row_updated_at,
                ) = row
                attrs: dict[str, Any] = {}
                if isinstance(row_attributes, str) and row_attributes.strip():
                    try:
                        parsed = json.loads(row_attributes)
                        if isinstance(parsed, dict):
                            attrs = parsed
                    except Exception:
                        attrs = {}

                return {
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
                    "created_at": row_created_at,
                    "updated_at": row_updated_at,
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_load_one)

    async def delete_resource(
        self,
        *,
        resource_id: str,
        idempotency_key: str | None = None,
        event_type: str = "delete_resource",
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Delete a resource by transitioning it to state='deleted'."""
        set_attribute: dict[str, Any] | None = None
        if reason:
            set_attribute = {"$.deleted_reason": reason}
        return await self.apply_resource_set_transition(
            resource_id=resource_id,
            event_type=event_type,
            idempotency_key=idempotency_key or f"delete_resource:{resource_id}",
            set_state="deleted",
            set_attribute=set_attribute,
        )

    async def upsert_resources_from_csv(
        self,
        *,
        csv_path: str,
        dry_run: bool = False,
        templates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Import resources from CSV file and upsert rows into the resources table."""
        report = await upsert_resources_from_csv(
            csv_path=csv_path,
            sqlite_client=self,
            dry_run=dry_run,
            templates=templates,
        )
        return report.to_dict()

    async def upsert_resources_from_csv_content(
        self,
        *,
        csv_content: str,
        source_label: str = "<inline>",
        dry_run: bool = False,
        templates: dict[str, Any] | None = None,
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
        for col, val in zip(SQLiteClient._HOST_COLUMNS, row):
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

    async def list_hosts(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List host rows. Defaults to enabled hosts only."""
        cols = ", ".join(self._HOST_COLUMNS)

        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                where = "WHERE enabled = 1" if enabled_only else ""
                cur.execute(f"SELECT {cols} FROM hosts {where} ORDER BY name")
                return [self._host_row_to_dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def host_capacity_remaining(self, *, name: str) -> dict[str, Any] | None:
        """Compute remaining capacity for a host: host totals minus the sum
        of active (non-deleted) compute slices currently allocated.

        Returns ``None`` if the host doesn't exist. Returns a dict with the
        four capacity dimensions (gpu_count, vcpu_count, ram_gb, disk_gb)
        plus their host limits and the sum of currently-allocated values.
        """
        host = await self.get_host(name=name)
        if host is None:
            return None

        def _sum_allocations() -> dict[str, int]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT value, attributes
                    FROM resources
                    WHERE resource_type = 'compute.gpu'
                      AND (state IS NULL OR state != 'deleted')
                    """
                )
                totals = {"gpu_count": 0, "vcpu_count": 0, "ram_gb": 0, "disk_gb": 0}
                for row_value, row_attrs in cur.fetchall():
                    attrs = {}
                    if isinstance(row_attrs, str) and row_attrs.strip():
                        try:
                            attrs = json.loads(row_attrs)
                        except json.JSONDecodeError:
                            continue
                    if attrs.get("vm_host") != name:
                        continue
                    if row_value is not None:
                        totals["gpu_count"] += int(row_value)
                    for k in ("vcpu_count", "ram_gb", "disk_gb"):
                        v = attrs.get(k)
                        if v is not None:
                            totals[k] += int(v)
                return totals
            finally:
                conn.close()

        used = await asyncio.to_thread(_sum_allocations)
        return {
            "host_name": name,
            "limits": {
                "gpu_count": host.get("total_gpu_count"),
                "vcpu_count": host.get("host_cpu_cores"),
                "ram_gb": host.get("host_ram_gb"),
                "disk_gb": host.get("host_disk_gb"),
            },
            "used": used,
            "remaining": {
                k: (host_limit - used[k]) if (host_limit := host.get({
                    "gpu_count": "total_gpu_count",
                    "vcpu_count": "host_cpu_cores",
                    "ram_gb": "host_ram_gb",
                    "disk_gb": "host_disk_gb",
                }[k])) is not None else None
                for k in ("gpu_count", "vcpu_count", "ram_gb", "disk_gb")
            },
        }

    def ensure_default_resources(self, resources: list[dict[str, Any]]) -> None:
        """Seed default resources only when the resources table is empty."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM resources")
            count = int(cur.fetchone()[0] or 0)
            if count > 0:
                return

            now_iso = datetime.now().isoformat()
            for resource in resources:
                cur.execute(
                    """
                    INSERT INTO resources(
                      resource_id, resource_type, resource_subtype, unit, value, state, attributes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource.get("resource_id"),
                        resource.get("resource_type"),
                        resource.get("resource_subtype"),
                        resource.get("unit"),
                        resource.get("value"),
                        resource.get("state"),
                        json.dumps(resource.get("attributes"))
                        if isinstance(resource.get("attributes"), dict)
                        else None,
                        now_iso,
                        now_iso,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    async def apply_resource_transition(
        self,
        *,
        resource_id: str,
        event_type: str,
        idempotency_key: str,
        set_value: int | float | None = None,
        set_state: str | None = None,
        set_attribute: dict[str, Any] | None = None,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """Insert one transition event and apply one resource snapshot update.

        Supports direct-set semantics only: set_value, set_state, set_attribute.
        """
        if set_value is None and set_state is None and not set_attribute:
            raise ValueError("Transition must include set_value, set_state, or set_attribute")

        resolved_event_id = event_id or str(uuid.uuid4())
        set_attribute_json = json.dumps(set_attribute) if set_attribute else None

        def _apply() -> dict[str, Any]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO resource_transition_events(
                      event_id, resource_id, event_type, set_value, set_state, set_attribute_json, idempotency_key, occurred_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')))
                    ON CONFLICT(idempotency_key) DO NOTHING
                    """,
                    (
                        resolved_event_id,
                        resource_id,
                        event_type,
                        set_value,
                        set_state,
                        set_attribute_json,
                        idempotency_key,
                        occurred_at,
                    ),
                )

                # Duplicate command retry: already applied.
                if cur.rowcount == 0:
                    conn.rollback()
                    return {
                        "applied": False,
                        "duplicate": True,
                        "resource_id": resource_id,
                        "event_id": resolved_event_id,
                        "idempotency_key": idempotency_key,
                    }

                updates: list[str] = []
                values: list[Any] = []

                if set_value is not None:
                    updates.append("value = ?")
                    values.append(set_value)

                if set_state is not None:
                    updates.append("state = ?")
                    values.append(set_state)

                if set_attribute:
                    attr_expr = "COALESCE(attributes, '{}')"
                    for path, path_value in set_attribute.items():
                        if not isinstance(path, str) or not path.startswith("$."):
                            raise ValueError(f"Invalid JSON path for set_attribute: {path}")
                        if path in ("$.allocation_id", "$.compute_allocation_id"):
                            continue
                        attr_expr = f"json_set({attr_expr}, ?, json(?))"
                        values.append(path)
                        values.append(json.dumps(path_value))
                    updates.append(f"attributes = {attr_expr}")

                updates.append("updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')")

                cur.execute(
                    f"UPDATE resources SET {', '.join(updates)} WHERE resource_id = ?",
                    (*values, resource_id),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"Resource not found: {resource_id}")

                if set_state == "available":
                    allocation_id = None
                    if set_attribute:
                        raw_allocation_id = (
                            set_attribute.get("$.allocation_id")
                            or set_attribute.get("$.compute_allocation_id")
                        )
                        if isinstance(raw_allocation_id, str) and raw_allocation_id.strip():
                            allocation_id = raw_allocation_id.strip()
                    if allocation_id:
                        cur.execute(
                            """
                            UPDATE compute_allocations
                            SET state = 'released',
                                released_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                            WHERE allocation_id = ?
                              AND resource_id = ?
                              AND state IN ('reserved', 'provisioning', 'leased', 'releasing', 'held')
                            """,
                            (allocation_id, resource_id),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE compute_allocations
                            SET state = 'released',
                                released_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                            WHERE resource_id = ?
                              AND state IN ('reserved', 'provisioning', 'leased', 'releasing', 'held')
                            """,
                            (resource_id,),
                        )

                conn.commit()
                return {
                    "applied": True,
                    "duplicate": False,
                    "resource_id": resource_id,
                    "event_id": resolved_event_id,
                    "idempotency_key": idempotency_key,
                }
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(_apply)

    async def apply_resource_set_transition(
        self,
        *,
        resource_id: str,
        event_type: str,
        idempotency_key: str,
        set_value: int | float | None = None,
        set_state: str | None = None,
        set_attribute: dict[str, Any] | None = None,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """Convenience wrapper for absolute-value transitions."""
        return await self.apply_resource_transition(
            resource_id=resource_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            set_value=set_value,
            set_state=set_state,
            set_attribute=set_attribute,
            event_id=event_id,
            occurred_at=occurred_at,
        )


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
            INSERT INTO compute_inventory_pools(
              pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
              status, allocation_policy, min_price, token, max_duration_seconds,
              accepted_escrows, created_at, updated_at
            )
            VALUES (?, 'compute.gpu', ?, ?, ?, ?, ?, 'first_fit', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pool_id) DO UPDATE SET
              gpu_model=COALESCE(excluded.gpu_model, compute_inventory_pools.gpu_model),
              region=COALESCE(excluded.region, compute_inventory_pools.region),
              sla=COALESCE(excluded.sla, compute_inventory_pools.sla),
              total_gpu_count=excluded.total_gpu_count,
              status=excluded.status,
              min_price=COALESCE(excluded.min_price, compute_inventory_pools.min_price),
              token=COALESCE(excluded.token, compute_inventory_pools.token),
              max_duration_seconds=COALESCE(excluded.max_duration_seconds, compute_inventory_pools.max_duration_seconds),
              accepted_escrows=COALESCE(excluded.accepted_escrows, compute_inventory_pools.accepted_escrows),
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
                now_iso,
                now_iso,
            ),
        )
        return pool_id


    # ------------------------------------------------------------------
    # Capacity holds — two-phase reserve bookkeeping. The hold itself
    # lives in the capacity ledger (a TTL'd reserved allocation); this
    # table only remembers which allocation a negotiation's acceptance
    # placed, so settlement can commit it instead of reserving fresh.
    # ------------------------------------------------------------------



_sqlite_client: SQLiteClient | None = None


def get_sqlite_client() -> SQLiteClient:
    global _sqlite_client
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(db_path=settings.db_path)
    return _sqlite_client
