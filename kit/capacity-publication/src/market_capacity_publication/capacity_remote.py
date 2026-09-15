"""Site-authority capacity event-feed poller, and one cycle of it.

``site_events_poller`` tails one site authority's versioned capacity-event
feed into the aggregate's local bus; ``drain_site_events_once`` is a single
cycle of that loop, and ``preview_site_events`` reports what the next cycle
would do without doing it. Domain-neutral: the storefront composition root
supplies settings resolution, aggregation, and the listing-reconcile
reaction (``full_reconcile``) -- see the VM storefront's
``services/capacity_client.py`` for the composed shape.

Lives beside its only caller. ARCHITECTURE.md gives this kit "the
storefront-side multi-site capacity source, exact site projections,
capacity-event reconciliation loop, registry fan-out, durable publication
result recording, and close-before-reopen lifecycle" -- this module is that
reconciliation loop, and it sat in ``core_storefront`` instead, where a
market with no capacity authority still carried it. The site *coordinate*
stays in core deliberately: core persists and compares ``site_id`` on a
listing's durable binding without interpreting it, and ``CapacityDelta`` is
a carrier in the same spirit. What moved is the mechanism that walks a
feed, not the vocabulary.

The buyer-facing HTTP client it polls through (``SiteCapacityClient``) lives
in ``kit/site-client``, alongside the site-authority's other typed client
(``SiteCapacityAdminClient``, operator resource registration/update). In this
package that client can be named in the annotations; in core it could only be
``Any``, to avoid a dependency core had no other reason to hold.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core_storefront.aggregation import AggregateCapacityClient
from core_storefront.capacity import CapacityDelta
from market_site_client import SiteCapacityClient

logger = logging.getLogger(__name__)


#: Cadence for re-reading a held gate; idle work only.
_PAUSED_POLL_SECONDS = 0.05


@dataclass
class SiteEventCursor:
    """One site's position in its authority's capacity-event feed.

    ``last_applied`` of ``None`` means unpositioned: the next cycle reads the
    feed head and runs a full reconcile to converge with anything that
    happened while this process was down, rather than replaying the feed.
    """

    site_name: str
    last_applied: int | None = None


#: One position per site per process. The position used to live in the
#: poller's closure, which is why a single cycle was not callable from
#: anywhere else: an advance with its own cursor would either replay events
#: the poller had applied or skip past ones it had not. The poller and the
#: admin advance address the same cursor, and the pause is what makes that
#: safe -- a cycle either runs completely or never starts, so an advance
#: while the loop is held has the feed to itself.
_CURSORS: dict[str, SiteEventCursor] = {}


def site_event_cursor(site_name: str) -> SiteEventCursor:
    """Return this process's cursor for ``site_name``, creating it if new."""
    cursor = _CURSORS.get(site_name)
    if cursor is None:
        cursor = SiteEventCursor(site_name=site_name)
        _CURSORS[site_name] = cursor
    return cursor


def reset_site_event_cursors() -> None:
    """Drop every cursor. For tests composing a fresh process-like state."""
    _CURSORS.clear()


@dataclass(frozen=True)
class SiteEventCycle:
    """What one drain of a site's feed did, in the order it did it."""

    site_name: str
    #: This cycle positioned at the feed head and ran the full reconcile.
    positioned: bool = False
    #: The feed head moved backwards (ledger reset), so this cycle resynced
    #: from the snapshot instead of replaying.
    resynced: bool = False
    #: Deltas emitted onto the aggregate bus, oldest first.
    applied: tuple[dict[str, Any], ...] = ()
    feed_head: int | None = None
    #: Position after the cycle.
    cursor: int | None = None
    #: The page was truncated: more events are already waiting.
    truncated: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site_name,
            "positioned": self.positioned,
            "resynced": self.resynced,
            "applied": [dict(event) for event in self.applied],
            "applied_count": len(self.applied),
            "feed_head": self.feed_head,
            "cursor": self.cursor,
            "truncated": self.truncated,
            "error": self.error,
        }


@dataclass(frozen=True)
class SiteEventPreview:
    """What the next drain of a site's feed would do, having done nothing.

    Read-only by construction: it reads the feed and reports, emitting no
    delta, reconciling nothing, and leaving the cursor where it was. A caller
    stepping a held loop can check what is about to happen before it does.
    """

    site_name: str
    cursor: int | None = None
    feed_head: int | None = None
    #: Events the next cycle would emit, oldest first.
    pending: tuple[dict[str, Any], ...] = ()
    #: The next cycle would position and full-reconcile rather than replay.
    would_position: bool = False
    would_resync: bool = False
    truncated: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site_name,
            "cursor": self.cursor,
            "feed_head": self.feed_head,
            "pending": [dict(event) for event in self.pending],
            "pending_count": len(self.pending),
            "would_position": self.would_position,
            "would_resync": self.would_resync,
            "truncated": self.truncated,
            "error": self.error,
        }


def _delta_fields(event: Any) -> dict[str, Any]:
    return {
        "kind": str(event.get("kind") or ""),
        "version": int(event.get("version") or 0),
        "resource_id": (
            str(event["resource_id"]) if event.get("resource_id") else None
        ),
    }


async def preview_site_events(
    client: SiteCapacityClient,
    cursor: SiteEventCursor,
) -> SiteEventPreview:
    """Report what the next cycle would do without doing any of it."""
    try:
        if cursor.last_applied is None:
            _, head = await client.events_after(0, limit=1)
            return SiteEventPreview(
                site_name=cursor.site_name,
                cursor=None,
                feed_head=head,
                would_position=True,
            )
        events, latest = await client.events_after(cursor.last_applied)
        if latest < cursor.last_applied:
            return SiteEventPreview(
                site_name=cursor.site_name,
                cursor=cursor.last_applied,
                feed_head=latest,
                would_resync=True,
            )
        pending = tuple(_delta_fields(event) for event in events)
        applied_through = (
            max(int(event["version"]) for event in pending)
            if pending
            else cursor.last_applied
        )
        return SiteEventPreview(
            site_name=cursor.site_name,
            cursor=cursor.last_applied,
            feed_head=latest,
            pending=pending,
            truncated=bool(pending) and latest > applied_through,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # reported, not raised: this is a read
        return SiteEventPreview(site_name=cursor.site_name, error=str(exc))


async def drain_site_events_once(
    aggregate: AggregateCapacityClient,
    client: SiteCapacityClient,
    cursor: SiteEventCursor,
    *,
    full_reconcile: Callable[[], Awaitable[None]],
) -> SiteEventCycle:
    """Run exactly one cycle of one site's feed and report what it did.

    The body the poller used to run inline. Extracted so a single cycle is
    callable -- a held loop that cannot be stepped can only be waited on, and
    waiting on a poller is the sleep this suite forbids.
    """
    positioned = False
    resynced = False
    applied: list[dict[str, Any]] = []
    feed_head: int | None = None
    try:
        if cursor.last_applied is None:
            _, cursor.last_applied = await client.events_after(0, limit=1)
            positioned = True
            await full_reconcile()
        events, latest = await client.events_after(cursor.last_applied)
        feed_head = latest
        if latest < cursor.last_applied:
            logger.warning(
                "[CAPACITY] Site %r feed head moved backwards (%d -> %d) "
                "— ledger reset? Resyncing from snapshot.",
                cursor.site_name, cursor.last_applied, latest,
            )
            cursor.last_applied = latest
            resynced = True
            await full_reconcile()
            events = []
        for event in events:
            fields = _delta_fields(event)
            await aggregate.emit_site_delta(
                cursor.site_name,
                CapacityDelta(
                    kind=fields["kind"],
                    version=fields["version"],
                    resource_id=fields["resource_id"],
                ),
            )
            applied.append(fields)
            cursor.last_applied = int(event.get("version") or cursor.last_applied)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(
            "[CAPACITY] Site %r poller cycle failed: %s", cursor.site_name, exc,
        )
        return SiteEventCycle(
            site_name=cursor.site_name,
            positioned=positioned,
            resynced=resynced,
            applied=tuple(applied),
            feed_head=feed_head,
            cursor=cursor.last_applied,
            error=str(exc),
        )
    return SiteEventCycle(
        site_name=cursor.site_name,
        positioned=positioned,
        resynced=resynced,
        applied=tuple(applied),
        feed_head=feed_head,
        cursor=cursor.last_applied,
        truncated=bool(applied)
        and feed_head is not None
        and cursor.last_applied is not None
        and feed_head > cursor.last_applied,
    )


async def site_events_poller(
    aggregate: AggregateCapacityClient,
    site_name: str,
    client: SiteCapacityClient,
    interval: float,
    *,
    full_reconcile: Callable[[], Awaitable[None]],
    paused: Callable[[], bool] | None = None,
) -> None:
    """Tail one site authority's capacity-event feed into the local bus.

    Positions at the feed head, runs ``full_reconcile`` once to converge
    with anything missed while down, then polls for new versions and
    emits each as a site-tagged ``CapacityDelta`` on the aggregate bus.
    A feed head that moves backwards (ledger reset) re-runs the full
    reconcile instead of replaying. ``full_reconcile`` is the domain's
    listing-reconciliation reaction — core never interprets listings.
    Only ``events_after`` and ``base_url`` are used of ``client``.

    ``paused`` is consulted once per cycle before any request, so a cycle
    either runs completely or never starts: the feed position is loop-local,
    and a poller interrupted mid-cycle would either replay or skip events.
    Core supplies no gate of its own -- the caller owns the pause, because only
    it knows what the loop is registered as.
    """
    cursor = site_event_cursor(site_name)
    logger.info(
        "[CAPACITY] Event poller started for site %r at %s (interval=%ss)",
        site_name, client.base_url, interval,
    )
    while True:
        if paused is not None and paused():
            await asyncio.sleep(_PAUSED_POLL_SECONDS)
            continue
        cycle = await drain_site_events_once(
            aggregate,
            client,
            cursor,
            full_reconcile=full_reconcile,
        )
        if cycle.truncated:
            continue  # truncated page — keep draining before sleeping
        await asyncio.sleep(interval)
