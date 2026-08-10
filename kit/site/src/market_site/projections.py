"""Canonical storefront projections derived from authoritative site capacity."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return format(Decimal(str(value)).normalize(), "f")
    return str(value)


def canonical_digest(records: Iterable[Mapping[str, Any]]) -> str:
    """Hash a stable JSON representation of a projection generation."""
    normalized = [_canonical(record) for record in records]
    normalized.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProjectionIdentity:
    revision: int
    digest: str


class ProjectionRevisionTracker:
    """Maintain one independent monotonic revision for a projection family."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revision = 0
        self._digest = canonical_digest([])

    def observe(self, records: list[dict[str, Any]]) -> ProjectionIdentity:
        digest = canonical_digest(records)
        with self._lock:
            if digest != self._digest:
                self._revision += 1
                self._digest = digest
            return ProjectionIdentity(self._revision, self._digest)


_POOL_METADATA_FIELDS = ("label", "enabled", "mechanism", "policy_tags", "pool_views")


def _project_pool_metadata(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist the pool-level fields a publication reader may see.

    Provider credentials and other provider-specific configuration must
    never reach a storefront cache. A field not in `_POOL_METADATA_FIELDS`
    (e.g. a provider's raw config) is silently dropped, not merely
    undocumented -- this allowlist is the structural enforcement, not the
    caller's responsibility alone. `policy_tags`/`pool_views` are deep-
    copied, not shallow-copied -- `pool_views` in particular nests a
    second level (view name -> opaque content dict), and a shallow copy
    would still let a caller mutate cached state through that inner dict.
    """
    projected: dict[str, Any] = {}
    for field in _POOL_METADATA_FIELDS:
        if field in meta and meta[field] is not None:
            projected[field] = meta[field]
    if "policy_tags" in projected:
        projected["policy_tags"] = copy.deepcopy(projected["policy_tags"])
    if "pool_views" in projected:
        projected["pool_views"] = copy.deepcopy(projected["pool_views"])
    return projected


def resource_pool_projection(
    resources: Iterable[Mapping[str, Any]],
    *,
    pool_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Project per-resource inventory grouped by authoritative resource pool.

    `pool_metadata` is an optional `pool_id -> {label, enabled, mechanism,
    policy_tags, pool_views}` mapping supplied by the mounting service. A
    pool absent from `pool_metadata` (including when `pool_metadata` is
    `None`, an older producer's default) is projected with inventory only
    -- no `pool_metadata` key at all, not an empty one -- so omitting a
    pool directory reproduces exactly what this function already returned
    before pool metadata existed.
    """
    pools: dict[str, list[dict[str, Any]]] = {}
    for raw in resources:
        resource = dict(raw)
        pool_id = str(resource.get("pool_id") or resource["resource_id"])
        attrs = dict(resource.get("attributes") or {})
        projected = {
            "physical_resource_id": str(resource["resource_id"]),
            "resource_type": resource.get("resource_type"),
            "resource_subtype": resource.get("resource_subtype"),
            "capacity": dict(resource.get("capacity") or {}),
            "attributes": attrs,
            "enabled": bool(resource.get("enabled", True)),
        }
        if resource.get("available") is not None:
            projected["available"] = dict(resource.get("available") or {})
        if resource.get("publication_views") is not None:
            projected["publication_views"] = dict(
                resource.get("publication_views") or {},
            )
        pools.setdefault(pool_id, []).append(projected)
    result: list[dict[str, Any]] = []
    for pool_id in sorted(pools):
        inventory = sorted(pools[pool_id], key=lambda row: row["physical_resource_id"])
        row: dict[str, Any] = {"resource_pool_id": pool_id, "resources": inventory}
        meta = (pool_metadata or {}).get(pool_id)
        if meta is not None:
            row["pool_metadata"] = _project_pool_metadata(meta)
        result.append(row)
    return result


def _grouping_attributes(resource: Mapping[str, Any]) -> dict[str, Any]:
    attrs = dict(resource.get("attributes") or {})
    # Identity and volatile operational details are intentionally excluded.
    for key in ("resource_id", "physical_resource_id", "vm_host", "updated_at", "created_at"):
        attrs.pop(key, None)
    return attrs


def capacity_bucket_projection(resources: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Vertically group resources with identical current capacity and criteria."""
    groups: dict[str, dict[str, Any]] = {}
    for resource in resources:
        if not resource.get("enabled", True):
            continue
        criteria = {
            "resource_pool_id": str(resource.get("pool_id") or resource["resource_id"]),
            "resource_type": resource.get("resource_type"),
            "resource_subtype": resource.get("resource_subtype"),
            "available": dict(resource.get("available") or {}),
            "grouping_attributes": _grouping_attributes(resource),
        }
        key = canonical_digest([criteria])
        group = groups.setdefault(
            key,
            {
                "capacity_group_key": key,
                **criteria,
                "resource_count": 0,
            },
        )
        group["resource_count"] += 1
    return [groups[key] for key in sorted(groups)]


class SiteProjectionService:
    """Produce independently versioned resource-pool and capacity projections."""

    def __init__(
        self,
        ledger: Any,
        *,
        resource_inventory: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
        pool_directory: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None,
    ) -> None:
        self._ledger = ledger
        self._resource_inventory = resource_inventory or ledger.list_resources
        self._pool_directory = pool_directory
        self._resource_pools = ProjectionRevisionTracker()
        self._capacity_buckets = ProjectionRevisionTracker()

    def resource_pools(self) -> tuple[ProjectionIdentity, list[dict[str, Any]]]:
        pool_metadata = self._pool_directory() if self._pool_directory else None
        rows = resource_pool_projection(self._resource_inventory(), pool_metadata=pool_metadata)
        return self._resource_pools.observe(rows), rows

    def capacity_buckets(self) -> tuple[ProjectionIdentity, list[dict[str, Any]]]:
        rows = capacity_bucket_projection(self._ledger.list_resources())
        return self._capacity_buckets.observe(rows), rows
