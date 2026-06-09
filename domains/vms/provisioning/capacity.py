"""Host capacity enforcement for compute slices.

When an operator commits a new compute slice to a host (via CSV import or
programmatic upsert), the sum of all active slices' GPU count, vCPU count,
RAM, and disk must not exceed the host's totals. This module provides the
check; ``SQLiteClient.upsert_resource`` calls it before writing.

The check is best-effort: it activates only when the slice carries a
``vm_host`` referring to a known host in the local DB. Resources without
``vm_host``, or pointing at hosts the operator hasn't registered, pass
through unchecked — those flows pre-date the hosts table or come from
remote listings being mirrored into the local DB and aren't ours to gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class CapacityStore(Protocol):
    db_path: str

    async def get_host(self, *, name: str) -> dict[str, Any] | None:
        ...


@dataclass
class CapacityViolation:
    dimension: str
    requested: int
    limit: int
    used_excluding_this: int

    def __str__(self) -> str:
        return (
            f"{self.dimension}: requested={self.requested} would push host "
            f"usage to {self.used_excluding_this + self.requested} "
            f"(other slices use {self.used_excluding_this}, host limit={self.limit})"
        )


class CapacityExceededError(ValueError):
    """Raised when a slice commitment would exceed host capacity."""

    def __init__(self, host_name: str, violations: list[CapacityViolation]):
        self.host_name = host_name
        self.violations = violations
        joined = "; ".join(str(v) for v in violations)
        super().__init__(
            f"Host '{host_name}' over-committed: {joined}"
        )


async def check_slice_fits_host(
    *,
    sqlite_client: CapacityStore,
    resource_id: str,
    host_name: str | None,
    gpu_count: int | None,
    vcpu_count: int | None,
    ram_gb: int | None,
    disk_gb: int | None,
) -> None:
    """Verify that committing this slice (id ``resource_id``) to ``host_name``
    keeps the host within its capacity limits.

    Pass-through (no-op) cases:
      - ``host_name`` is None or empty (slice not pinned to a known host)
      - host doesn't exist in the local hosts table
      - host has no limit declared for a given dimension (limit is None)

    Otherwise, sums the dimension across all active compute.gpu rows for the
    same host *excluding* the row being upserted (so re-imports of the same
    CSV are idempotent). Raises ``CapacityExceededError`` if any dimension
    would be exceeded.
    """
    if not host_name:
        return
    host = await sqlite_client.get_host(name=host_name)
    if host is None:
        return

    # Sum of currently-committed dimensions across all active slices on this
    # host, excluding the one being upserted.
    used = await _sum_active_slices_for_host(
        sqlite_client=sqlite_client,
        host_name=host_name,
        exclude_resource_id=resource_id,
    )

    limits = {
        "gpu_count": host.get("total_gpu_count"),
        "vcpu_count": host.get("host_cpu_cores"),
        "ram_gb": host.get("host_ram_gb"),
        "disk_gb": host.get("host_disk_gb"),
    }
    requested = {
        "gpu_count": gpu_count or 0,
        "vcpu_count": vcpu_count or 0,
        "ram_gb": ram_gb or 0,
        "disk_gb": disk_gb or 0,
    }

    violations: list[CapacityViolation] = []
    for dim, lim in limits.items():
        if lim is None:
            continue
        if requested[dim] + used[dim] > lim:
            violations.append(CapacityViolation(
                dimension=dim,
                requested=requested[dim],
                limit=lim,
                used_excluding_this=used[dim],
            ))

    if violations:
        raise CapacityExceededError(host_name=host_name, violations=violations)


async def _sum_active_slices_for_host(
    *,
    sqlite_client: CapacityStore,
    host_name: str,
    exclude_resource_id: str | None,
) -> dict[str, int]:
    """Sum gpu_count/vcpu_count/ram_gb/disk_gb across active compute.gpu
    slices on ``host_name``, excluding ``exclude_resource_id`` if given."""
    import asyncio
    import json
    import sqlite3

    def _query() -> dict[str, int]:
        conn = sqlite3.connect(sqlite_client.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT resource_id, value, attributes
                FROM resources
                WHERE resource_type = 'compute.gpu'
                  AND (state IS NULL OR state != 'deleted')
                """
            )
            totals = {"gpu_count": 0, "vcpu_count": 0, "ram_gb": 0, "disk_gb": 0}
            for rid, row_value, row_attrs in cur.fetchall():
                if exclude_resource_id is not None and rid == exclude_resource_id:
                    continue
                attrs: dict[str, Any] = {}
                if isinstance(row_attrs, str) and row_attrs.strip():
                    try:
                        attrs = json.loads(row_attrs)
                    except json.JSONDecodeError:
                        continue
                if attrs.get("vm_host") != host_name:
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

    return await asyncio.to_thread(_query)
