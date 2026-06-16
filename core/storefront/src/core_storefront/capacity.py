"""Site-authority capacity client contract.

In the target topology
(docs/development/ARCHITECTURE.md, "Capacity and the Site Authority")
the storefront does not own capacity: a per-site *site authority* keeps
the authoritative resource ledger (hosts, allocations, lease timing) and
the storefront reaches it only through this client interface —

- an advisory availability ``snapshot`` at negotiation-round start,
- an authoritative check-and-``reserve`` at fulfillment time (with an
  optional TTL for two-phase reserve),
- ``commit``/``release``/``truncate_lease`` for the allocation
  lifecycle, and
- anonymous, versioned capacity-change events that drive each
  storefront's derived-listing reconciliation (a *different*
  storefront's sale must also invalidate your listings, so closure
  cannot stay inline-after-own-reservation).

Core owns only the contract: the method shapes, the event carrier, and
the in-process subscription mechanics. Every payload is a
resource-domain dict whose vocabulary the implementation defines — core
stays schema-free. The first implementation is an embedded adapter over
the storefront's own tables (single-storefront deployments); the
boundary becomes a real service the moment two storefronts sell from
the same pool.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapacityDelta:
    """Anonymous capacity-change notification.

    Carries *that* availability changed and where — never whose deal
    caused it (deal context is point-to-point, not pub/sub; broadcasting
    it would leak one buyer's activity to every subscribed storefront).
    ``version`` increases monotonically per event source so subscribers
    can detect gaps and fall back to a full snapshot resync; with
    multiple sites aggregated, ``(site, version)`` is the unique key —
    versions from different sites are unrelated sequences.
    """

    kind: str  # "reserved" | "committed" | "released" | "lease_truncated"
    version: int
    resource_id: str | None = None
    pool_id: str | None = None
    site: str | None = None  # which site authority's ledger moved


CapacitySubscriber = Callable[[CapacityDelta], Awaitable[None]]


@dataclass
class CapacityEventBus:
    """In-process fan-out for capacity deltas.

    Subscriber failures are logged and swallowed: a listing-reconcile
    error must not roll back or fail the reservation that triggered it
    (same stance as today's inline closure, which is best-effort).
    """

    _subscribers: list[CapacitySubscriber] = field(default_factory=list)
    _versions: "itertools.count[int]" = field(
        default_factory=lambda: itertools.count(1),
    )

    def subscribe(self, subscriber: CapacitySubscriber) -> Callable[[], None]:
        self._subscribers.append(subscriber)

        def _unsubscribe() -> None:
            try:
                self._subscribers.remove(subscriber)
            except ValueError:
                pass

        return _unsubscribe

    def next_version(self) -> int:
        return next(self._versions)

    async def emit(self, delta: CapacityDelta) -> None:
        for subscriber in list(self._subscribers):
            try:
                await subscriber(delta)
            except Exception as exc:
                logger.warning(
                    "[CAPACITY] subscriber %r failed on %s delta (resource=%s): %s",
                    getattr(subscriber, "__name__", subscriber),
                    delta.kind,
                    delta.resource_id,
                    exc,
                )


@runtime_checkable
class CapacityClient(Protocol):
    """What a storefront may ask of a site authority.

    ``claim`` and ``deal_ref`` are opaque mappings: the claim speaks the
    site's resource-domain vocabulary (e.g. required attributes), the
    deal ref carries the storefront's bookkeeping keys, recorded on the
    allocation at reserve time so deal-scoped events can be routed back
    to the owning storefront.
    """

    async def snapshot(self) -> list[dict[str, Any]]:
        """Advisory availability view for negotiation-time policy input."""
        ...

    async def probe(
        self, *, claim: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Dry-run match for ``claim`` — consumes nothing."""
        ...

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically check-and-reserve capacity matching ``claim``.

        Returns the allocation payload, or None when nothing matches.
        ``ttl_seconds`` requests a soft hold that auto-expires unless
        committed (two-phase reserve).
        """
        ...

    async def commit(
        self,
        *,
        resource_id: str,
        allocation_id: str | None = None,
        lease_end_utc: str,
        idempotency_ref: str | None = None,
    ) -> None:
        """Confirm a reservation into an active lease."""
        ...

    async def release(
        self,
        *,
        allocation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return a held/leased allocation's capacity to the pool."""
        ...

    async def truncate_lease(
        self,
        *,
        allocation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        """End a lease early (settlement lifecycle decided the deal is over)."""
        ...

    def subscribe(self, subscriber: CapacitySubscriber) -> Callable[[], None]:
        """Register for capacity deltas; returns an unsubscribe handle."""
        ...
