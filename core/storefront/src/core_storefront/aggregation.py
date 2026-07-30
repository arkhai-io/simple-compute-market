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


ClaimMatcher = Callable[[Mapping[str, Any], Mapping[str, Any] | None], bool]
"""Whether a plain-dict ``snapshot()`` row could serve a claim.

A ranking hint, not an enforcement point — ``probe()``/``reserve()`` on
the chosen site remain the real, authoritative check (see
ARCHITECTURE.md's layered-ownership model). This package deliberately
does not import ``kit/site``: it must stay usable against any
``CapacityClient`` implementation, not just the one that happens to
exist today, so its own default (``_coarse_resource_matches_claim``)
only understands a small, explicitly-documented claim subset. Domains
whose backing site needs exact claim semantics (matching every
attribute a claim names, not just identity and quantity) inject a
stronger matcher at composition time — see
``dict_resource_satisfies_claim`` in ``kit/site`` for the one built
against that package's own requirement-parsing and feasibility
semantics.
"""


def _coarse_resource_matches_claim(
    row: Mapping[str, Any], claim: Mapping[str, Any] | None,
) -> bool:
    """Match a row's identity and quantitative capacity against a claim.

    Intentionally incomplete: checks an optional pool_id/resource_id pin
    and either a multidimensional ``dimensions`` map or a legacy
    single-quantity claim, but not arbitrary categorical claim attributes
    (e.g. a buyer-selectable region or hardware model) — those require
    knowing which claim keys are quantitative versus exact-match, which
    is backing-site-specific. This is the default ``ClaimMatcher`` for
    callers that have not injected a stronger one; it costs an extra,
    avoidable round-trip on a wrong rank, never an incorrect admission.
    """
    if not claim:
        return True
    pool_id = claim.get("pool_id")
    if pool_id is not None and row.get("pool_id") != pool_id:
        return False
    resource_id = claim.get("resource_id")
    if resource_id is not None and row.get("resource_id") != resource_id:
        return False
    requested = claim.get("dimensions")
    if isinstance(requested, Mapping) and requested:
        available = row.get("available") or {}
        for dimension, quantity in requested.items():
            try:
                if float(available.get(dimension, 0) or 0) < float(quantity):
                    return False
            except (TypeError, ValueError):
                return False
        return True
    # Legacy, non-dimensional claim (the shape apicredits still sends):
    # compare against the row's single reported available_units value.
    requested_units = claim.get("units", claim.get("gpu_count"))
    if requested_units is None:
        return True
    try:
        return float(row.get("available_units") or 0) >= float(requested_units)
    except (TypeError, ValueError):
        return False


def _site_available_units(
    snapshot: list[dict[str, Any]],
    claim: Mapping[str, Any] | None,
    claim_matcher: ClaimMatcher,
) -> int:
    return sum(
        max(int(row.get("available_units") or 0), 0)
        for row in snapshot
        if claim_matcher(row, claim)
    )


def most_available(
    site_names: list[str],
    snapshots: Mapping[str, list[dict[str, Any]]],
    *,
    claim: Mapping[str, Any] | None = None,
    claim_matcher: ClaimMatcher = _coarse_resource_matches_claim,
) -> list[str]:
    """Spread: prefer the site with the most free units matching ``claim``
    per ``claim_matcher`` (ties keep configuration order; sites without a
    snapshot go last).

    The one defaulting point for ``claim_matcher`` — everything this
    function calls receives it explicitly rather than re-defaulting on
    its own, so an internal caller can't accidentally fall back to the
    coarse matcher a composition root deliberately overrode.
    """
    def _key(idx_name: tuple[int, str]) -> tuple[int, int]:
        idx, name = idx_name
        snapshot = snapshots.get(name)
        if snapshot is None:
            return (1, idx)  # unknown availability — try after known sites
        available = _site_available_units(snapshot, claim, claim_matcher)
        return (0, -available * len(site_names) + idx)

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
        reservation_sites: dict[str, str] | None = None,
    ) -> None:
        if not sites:
            raise ValueError("AggregateCapacityClient needs at least one site")
        self._sites = dict(sites)
        self._placement = placement or fill_first
        self._bus = bus or CapacityEventBus()
        # capacity_reservation_id → site name, learned at reserve time. A cache,
        # not a ledger: misses (process restart) fall back to asking
        # every site, and the answer is re-learned. Externally-owned when
        # ``reservation_sites`` is supplied, so a sibling aggregator over a
        # different per-site client (e.g. the compute-provisioning
        # fulfillment surface) can share the exact same learned mapping
        # instead of maintaining an independent copy — see
        # ``market_storefront/services/capacity_client.py``.
        self._reservation_sites: dict[str, str] = (
            reservation_sites if reservation_sites is not None else {}
        )

    @property
    def site_names(self) -> list[str]:
        return list(self._sites)

    @property
    def reservation_sites(self) -> dict[str, str]:
        """The learned ``capacity_reservation_id`` → site name mapping.

        Exposed so a sibling aggregator over a different per-site client
        can be constructed with this exact dict instance (see
        ``reservation_sites=`` on ``__init__``), not a copy.
        """
        return self._reservation_sites

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
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        snapshots = await self._snapshots()
        for name in self._placement(self.site_names, snapshots, claim=claim):
            try:
                match = await self._sites[name].probe(
                    claim=claim,
                    lease_start_utc=lease_start_utc,
                    lease_duration_seconds=lease_duration_seconds,
                )
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
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
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
                    claim=claim,
                    deal_ref=deal_ref,
                    ttl_seconds=ttl_seconds,
                    lease_start_utc=lease_start_utc,
                    lease_duration_seconds=lease_duration_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "[AGGREGATOR] reserve at site %r failed, trying next: %s",
                    name, exc,
                )
                continue
            if reserved is None:
                continue
            capacity_reservation_id = reserved.get("capacity_reservation_id")
            if capacity_reservation_id:
                self._reservation_sites[str(capacity_reservation_id)] = name
            return _tagged(name, reserved)
        return None

    async def commit(
        self,
        *,
        resource_id: str | None = None,
        capacity_reservation_id: str | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        idempotency_ref: str | None = None,
    ) -> None:
        """Commit at the owning site (cache-first, then the rest).

        A site that doesn't know the reservation raises/refuses and the
        next is tried; if every site refuses, the last error propagates
        — a commit that lands nowhere must not look like success.
        """
        last_error: Exception | None = None
        for name in self._route_order(capacity_reservation_id):
            try:
                await self._sites[name].commit(
                    resource_id=resource_id,
                    capacity_reservation_id=capacity_reservation_id,
                    lease_start_utc=lease_start_utc,
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
        capacity_reservation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any] | None:
        """Release wherever the reservation lives; None if no site holds it.

        ``extra`` passes through implementation-specific keywords (e.g.
        failure metadata) to sites that accept them.
        """
        for name in self._route_order(capacity_reservation_id):
            try:
                released = await self._sites[name].release(
                    capacity_reservation_id=capacity_reservation_id, deal_ref=deal_ref, **extra,
                )
            except Exception as exc:
                logger.warning(
                    "[AGGREGATOR] release at site %r failed: %s", name, exc,
                )
                continue
            if released is not None:
                if capacity_reservation_id:
                    self._reservation_sites.pop(str(capacity_reservation_id), None)
                return _tagged(name, released)
        return None

    async def truncate_lease(
        self,
        *,
        capacity_reservation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        for name in self._route_order(capacity_reservation_id):
            try:
                truncated = await self._sites[name].truncate_lease(
                    capacity_reservation_id=capacity_reservation_id, lease_end_utc=lease_end_utc,
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

    def _route_order(self, capacity_reservation_id: str | None) -> Iterable[str]:
        """Owning site first when known, then everyone else.

        The cache is populated at reserve time; after a restart the
        cache is cold and the write fans out — sites that don't hold
        the reservation refuse, the one that does answers.
        """
        cached = (
            self._reservation_sites.get(str(capacity_reservation_id))
            if capacity_reservation_id else None
        )
        if cached and cached in self._sites:
            yield cached
            for name in self._sites:
                if name != cached:
                    yield name
        else:
            yield from self._sites
