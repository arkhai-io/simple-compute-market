"""Multi-site capacity aggregation.

The aggregator answers the design doc's "two machines in two
datacenters, one listing, depletes only when both are depleted"
(docs/development/ARCHITECTURE.md, "Capacity and the Site Authority"):
a soft-state view over N hard-state site ledgers, reached only through
their ``CapacityClient`` interfaces. It holds no capacity itself —
availability is a union over member sites, a reserve is routed to one
site and falls back to the next on refusal, and there are no
distributed transactions to invent: cross-site contention resolves at
whichever single site's local transaction the placement policy picked.

It lives in the storefront process, not in a site and not in a shared
service, because pooling/placement is a commercial judgment per seller
(the fungibility rule: resources may pool exactly when no advertised
attribute distinguishes them — only the seller's market schema knows
which attributes those are).

``AggregateCapacityClient`` implements the same ``CapacityClient``
protocol it consumes, so a storefront wired against one site and one
wired against five run identical code. Every payload and delta is
tagged with the site name it came from; pool members reference
``(site, resource_id)``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Mapping, Protocol, runtime_checkable

from core_storefront.capacity import (
    CapacityClient,
    CapacityDelta,
    CapacityEventBus,
    CapacitySubscriber,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Placement policies
# ---------------------------------------------------------------------------

@runtime_checkable
class PlacementPolicy(Protocol):
    """Orders candidate sites for a reserve/probe.

    Takes the configured site names (in configuration order) and the
    latest per-site snapshots the aggregator could obtain (absent for a
    site whose snapshot failed); returns the site names to try, in
    order. Sites omitted from the result are not tried.
    """

    def __call__(
        self,
        site_names: list[str],
        snapshots: Mapping[str, list[dict[str, Any]]],
        *,
        claim: Mapping[str, Any] | None = None,
    ) -> list[str]:
        ...


def fill_first(
    site_names: list[str],
    snapshots: Mapping[str, list[dict[str, Any]]],
    *,
    claim: Mapping[str, Any] | None = None,
) -> list[str]:
    """Configuration order: pack the first site before touching the next."""
    return list(site_names)


def _site_available_units(snapshot: list[dict[str, Any]]) -> int:
    total = 0
    for row in snapshot:
        available = row.get("available_units")
        if available is None:
            continue
        total += max(int(available), 0)
    return total


def most_available(
    site_names: list[str],
    snapshots: Mapping[str, list[dict[str, Any]]],
    *,
    claim: Mapping[str, Any] | None = None,
) -> list[str]:
    """Spread: prefer the site with the most free units (ties keep
    configuration order; sites without a snapshot go last)."""
    def _key(idx_name: tuple[int, str]) -> tuple[int, int]:
        idx, name = idx_name
        snapshot = snapshots.get(name)
        if snapshot is None:
            return (1, idx)  # unknown availability — try after known sites
        return (0, -_site_available_units(snapshot) * len(site_names) + idx)

    # Sort by (known first, descending availability), stable on config order.
    ordered = sorted(enumerate(site_names), key=_key)
    return [name for _, name in ordered]


PLACEMENT_POLICIES: dict[str, PlacementPolicy] = {
    "fill_first": fill_first,
    "most_available": most_available,
}


# ---------------------------------------------------------------------------
# The aggregate client
# ---------------------------------------------------------------------------

def _tagged(site: str, payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["site"] = site
    return out


class AggregateCapacityClient:
    """``CapacityClient`` over N named site clients.

    Reads union, writes route. A site that errors is skipped (logged):
    the aggregator is a soft-state view and one site's outage must not
    take down the seller's whole market — the listing closes only when
    every member refuses.
    """

    def __init__(
        self,
        sites: Mapping[str, CapacityClient],
        *,
        placement: PlacementPolicy | None = None,
        bus: CapacityEventBus | None = None,
    ) -> None:
        if not sites:
            raise ValueError("AggregateCapacityClient needs at least one site")
        self._sites = dict(sites)
        self._placement = placement or fill_first
        self._bus = bus or CapacityEventBus()
        # allocation_id → site name, learned at reserve time. A cache,
        # not a ledger: misses (process restart) fall back to asking
        # every site, and the answer is re-learned.
        self._allocation_sites: dict[str, str] = {}

    @property
    def site_names(self) -> list[str]:
        return list(self._sites)

    def site(self, name: str) -> CapacityClient:
        return self._sites[name]

    # -- reads ----------------------------------------------------------

    async def snapshot(self) -> list[dict[str, Any]]:
        """Union of per-site snapshots, each row tagged with its site."""
        rows: list[dict[str, Any]] = []
        for name, snapshot in (await self._snapshots()).items():
            rows.extend(_tagged(name, row) for row in snapshot)
        return rows

    async def probe(
        self, *, claim: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        snapshots = await self._snapshots()
        for name in self._placement(self.site_names, snapshots, claim=claim):
            try:
                match = await self._sites[name].probe(claim=claim)
            except Exception as exc:
                logger.warning("[AGGREGATOR] probe at site %r failed: %s", name, exc)
                continue
            if match is not None:
                return _tagged(name, match)
        return None

    # -- writes ----------------------------------------------------------

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        """Route to one site in placement order; fall back on refusal.

        A refusal is a None (no capacity) or an error; either way the
        next site gets the claim. Returns None only when every member
        refused.
        """
        snapshots = await self._snapshots()
        for name in self._placement(self.site_names, snapshots, claim=claim):
            try:
                reserved = await self._sites[name].reserve(
                    claim=claim, deal_ref=deal_ref, ttl_seconds=ttl_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "[AGGREGATOR] reserve at site %r failed, trying next: %s",
                    name, exc,
                )
                continue
            if reserved is None:
                continue
            allocation_id = reserved.get("allocation_id")
            if allocation_id:
                self._allocation_sites[str(allocation_id)] = name
            return _tagged(name, reserved)
        return None

    async def commit(
        self,
        *,
        resource_id: str,
        allocation_id: str | None = None,
        lease_end_utc: str,
        idempotency_ref: str | None = None,
    ) -> None:
        """Commit at the owning site (cache-first, then the rest).

        A site that doesn't know the allocation raises/refuses and the
        next is tried; if every site refuses, the last error propagates
        — a commit that lands nowhere must not look like success.
        """
        last_error: Exception | None = None
        for name in self._route_order(allocation_id):
            try:
                await self._sites[name].commit(
                    resource_id=resource_id,
                    allocation_id=allocation_id,
                    lease_end_utc=lease_end_utc,
                    idempotency_ref=idempotency_ref,
                )
                return
            except Exception as exc:
                logger.warning(
                    "[AGGREGATOR] commit at site %r failed: %s", name, exc,
                )
                last_error = exc
        if last_error is not None:
            raise last_error

    async def release(
        self,
        *,
        allocation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any] | None:
        """Release wherever the allocation lives; None if no site holds it.

        ``extra`` passes through implementation-specific keywords (e.g.
        failure metadata) to sites that accept them.
        """
        for name in self._route_order(allocation_id):
            try:
                released = await self._sites[name].release(
                    allocation_id=allocation_id, deal_ref=deal_ref, **extra,
                )
            except Exception as exc:
                logger.warning(
                    "[AGGREGATOR] release at site %r failed: %s", name, exc,
                )
                continue
            if released is not None:
                if allocation_id:
                    self._allocation_sites.pop(str(allocation_id), None)
                return _tagged(name, released)
        return None

    async def truncate_lease(
        self,
        *,
        allocation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        for name in self._route_order(allocation_id):
            try:
                truncated = await self._sites[name].truncate_lease(
                    allocation_id=allocation_id, lease_end_utc=lease_end_utc,
                )
            except Exception as exc:
                logger.warning(
                    "[AGGREGATOR] truncate at site %r failed: %s", name, exc,
                )
                continue
            if truncated is not None:
                return _tagged(name, truncated)
        return None

    # -- events ----------------------------------------------------------

    def subscribe(self, subscriber: CapacitySubscriber) -> Callable[[], None]:
        return self._bus.subscribe(subscriber)

    async def emit_site_delta(self, site: str, delta: CapacityDelta) -> None:
        """Feed a site's delta (from its poller/bus) to aggregate subscribers."""
        await self._bus.emit(CapacityDelta(
            kind=delta.kind,
            version=delta.version,
            resource_id=delta.resource_id,
            pool_id=delta.pool_id,
            site=site,
        ))

    # -- internals ---------------------------------------------------------

    async def _snapshots(self) -> dict[str, list[dict[str, Any]]]:
        """Best-effort per-site snapshots; a failed site is omitted."""
        snapshots: dict[str, list[dict[str, Any]]] = {}
        for name, client in self._sites.items():
            try:
                snapshots[name] = await client.snapshot() or []
            except Exception as exc:
                logger.warning(
                    "[AGGREGATOR] snapshot at site %r failed: %s", name, exc,
                )
        return snapshots

    def _route_order(self, allocation_id: str | None) -> Iterable[str]:
        """Owning site first when known, then everyone else.

        The cache is populated at reserve time; after a restart the
        cache is cold and the write fans out — sites that don't hold
        the allocation refuse, the one that does answers.
        """
        cached = (
            self._allocation_sites.get(str(allocation_id))
            if allocation_id else None
        )
        if cached and cached in self._sites:
            yield cached
            for name in self._sites:
                if name != cached:
                    yield name
        else:
            yield from self._sites
