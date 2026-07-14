"""Physical settlement resource selection.

Binds an already-reserved capacity allocation to exactly one durable,
idempotent settlement resource. See
openspec/changes/pools-2-physical-settlement-scheduler/design.md for the
full design rationale (scheduler/provider split, naming, algorithm).

Persistence is intentionally process-local this round (see that design's
"No persistence this change" decision) — bindings live in an in-memory
dict keyed by allocation_id. pools-3 replaces this with a durable
SettlementRecord extending the same key.
"""

from __future__ import annotations

import threading
from typing import Any

from compute_provisioning.physical_settlement import (
    PhysicalSettlementRequest,
    SettlementResource,
)
from market_resource_pools import ResourcePoolService
from market_site.ledger import CapacityLedgerService

from db.models import Host


class NoEligiblePoolError(Exception):
    """No enabled, non-exhausted pool can satisfy the request."""


class ResourceNotFoundError(Exception):
    """An explicitly-requested resource_id does not exist or isn't eligible."""


class PhysicalSettlementScheduler:
    """Selects and durably (for this process's lifetime) binds settlement resources.

    Dimension-agnostic bottleneck-normalized selection: for each eligible
    pool, utilization is the maximum of (used_units / total_units) across
    whatever ``resource_type`` values that pool's resources actually have —
    not a fixed CPU/RAM/GPU/disk set, since the site ledger's resource model
    doesn't have fixed dimensions (see design.md's "Discovery" note carried
    into this session's plan). The pool with the lowest bottleneck
    utilization is selected.
    """

    def __init__(
        self,
        pool_service: ResourcePoolService,
        capacity_ledger: CapacityLedgerService,
        session_factory: Any,
    ) -> None:
        self._pool_service = pool_service
        self._capacity_ledger = capacity_ledger
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._bindings: dict[str, SettlementResource] = {}

    def has_active_binding(self, pool_id: str) -> bool:
        """Used by ResourcePoolService's disable_pool guardrail."""
        with self._lock:
            return any(
                resource.pool_id == pool_id for resource in self._bindings.values()
            )

    def select_resource(
        self, request: PhysicalSettlementRequest
    ) -> SettlementResource:
        """Atomically bind request.allocation_id to a settlement resource.

        Repeated calls for the same allocation_id return the existing
        binding rather than selecting another resource.
        """
        with self._lock:
            existing = self._bindings.get(request.allocation_id)
            if existing is not None:
                return existing

            if request.resource_id is not None:
                resource = self._bind_explicit_resource(request)
            else:
                resource = self._bind_pool_selected_resource(request)

            self._bindings[request.allocation_id] = resource
            return resource

    # ------------------------------------------------------------------
    # Explicit resource_id path
    # ------------------------------------------------------------------

    def _bind_explicit_resource(
        self, request: PhysicalSettlementRequest
    ) -> SettlementResource:
        for payload in self._capacity_ledger.list_resources():
            if payload["resource_id"] != request.resource_id:
                continue
            if not payload.get("enabled"):
                raise ResourceNotFoundError(
                    f"resource '{request.resource_id}' is disabled"
                )
            pool_id = self._pool_id_for(payload)
            return SettlementResource(
                settlement_resource_id=payload["resource_id"],
                pool_id=pool_id or "",
                resource_kind=payload["resource_type"],
                provider=self._provider_for_pool(pool_id),
                attributes=payload.get("attributes") or {},
            )
        raise ResourceNotFoundError(
            f"resource '{request.resource_id}' does not exist"
        )

    # ------------------------------------------------------------------
    # Fungible pool-selection path
    # ------------------------------------------------------------------

    def _bind_pool_selected_resource(
        self, request: PhysicalSettlementRequest
    ) -> SettlementResource:
        eligible_pool_ids = {
            pool.id
            for pool in self._pool_service.list_pools(enabled_only=True)
            if request.pool_id is None or pool.id == request.pool_id
        }
        if not eligible_pool_ids:
            raise NoEligiblePoolError(
                "no enabled pool matches this request"
                if request.pool_id is None
                else f"pool '{request.pool_id}' does not exist or is disabled"
            )

        by_pool = self._group_resources_by_pool(eligible_pool_ids)
        best_pool_id: str | None = None
        best_utilization: float | None = None
        best_resource: dict[str, Any] | None = None

        for pool_id in eligible_pool_ids:
            resources = by_pool.get(pool_id, [])
            candidate = next(
                (r for r in resources if r.get("enabled") and r["available_units"] > 0),
                None,
            )
            if candidate is None:
                continue
            utilization = self._pool_bottleneck_utilization(resources)
            if best_utilization is None or utilization < best_utilization:
                best_pool_id, best_utilization, best_resource = (
                    pool_id,
                    utilization,
                    candidate,
                )

        if best_pool_id is None or best_resource is None:
            raise NoEligiblePoolError(
                "every eligible pool is disabled or exhausted"
            )

        return SettlementResource(
            settlement_resource_id=best_resource["resource_id"],
            pool_id=best_pool_id,
            resource_kind=best_resource["resource_type"],
            provider=self._provider_for_pool(best_pool_id),
            attributes=best_resource.get("attributes") or {},
        )

    @staticmethod
    def _pool_bottleneck_utilization(resources: list[dict[str, Any]]) -> float:
        totals: dict[str, int] = {}
        useds: dict[str, int] = {}
        for r in resources:
            if not r.get("enabled"):
                continue
            rtype = r["resource_type"]
            total = int(r["value"])
            available = int(r["available_units"])
            totals[rtype] = totals.get(rtype, 0) + total
            useds[rtype] = useds.get(rtype, 0) + max(total - available, 0)
        if not totals:
            return 1.0
        return max(
            (useds[rtype] / totals[rtype]) if totals[rtype] else 1.0
            for rtype in totals
        )

    def _group_resources_by_pool(
        self, eligible_pool_ids: set[str]
    ) -> dict[str, list[dict[str, Any]]]:
        resources = self._capacity_ledger.list_resources()
        # attributes["vm_host"] identifies the physical host a resource rides
        # on (legacy naming; conceptually "the host name" for any executor
        # kind sharing this Host table). Hostless resources (e.g. an
        # api-credits market's quota rows) never join to a pool and are
        # correctly excluded from pool-based scheduling.
        host_names = {
            r["attributes"].get("vm_host")
            for r in resources
            if r.get("attributes")
        }
        host_names.discard(None)
        with self._session_factory() as db:
            hosts = (
                db.query(Host).filter(Host.name.in_(host_names)).all()
                if host_names
                else []
            )
        pool_by_host = {h.name: h.pool_id for h in hosts}

        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in resources:
            host_name = (r.get("attributes") or {}).get("vm_host")
            pool_id = pool_by_host.get(host_name)
            if pool_id is None or pool_id not in eligible_pool_ids:
                continue
            grouped.setdefault(pool_id, []).append(r)
        return grouped

    def _pool_id_for(self, resource_payload: dict[str, Any]) -> str | None:
        host_name = (resource_payload.get("attributes") or {}).get("vm_host")
        if host_name is None:
            return None
        with self._session_factory() as db:
            host = db.query(Host).filter(Host.name == host_name).one_or_none()
        return host.pool_id if host else None

    def _provider_for_pool(self, pool_id: str | None) -> str:
        if pool_id is None:
            return ""
        pool = self._pool_service.get_pool(pool_id)
        return pool.provider if pool else ""
