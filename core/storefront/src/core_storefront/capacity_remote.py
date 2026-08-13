"""Site-authority capacity event-feed poller.

``site_events_poller`` tails one site authority's versioned capacity-event
feed into the aggregate's local bus. Domain-neutral: the storefront
composition root supplies settings resolution, aggregation, and the
listing-reconcile reaction (``full_reconcile``) -- see the VM storefront's
``services/capacity_client.py`` for the composed shape. The buyer-facing
HTTP client it polls through (``SiteCapacityClient``) lives in
``kit/site-client``, alongside the site-authority's other typed client
(``SiteCapacityAdminClient``, operator resource registration/update).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from core_storefront.capacity import CapacityDelta

logger = logging.getLogger(__name__)


async def site_events_poller(
    aggregate: Any,
    site_name: str,
    client: Any,
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
    ``client`` is a ``kit/site-client`` ``SiteCapacityClient`` (typed
    here as ``Any`` to avoid a dependency this package doesn't otherwise
    need); only ``events_after`` and ``base_url`` are used.

    ``paused``, when supplied, is consulted once per cycle before any work.
    A paused cycle does nothing at all: it does not read the feed, advance
    the position, emit a delta, or reconcile. Checking at the top of the
    cycle rather than interrupting one is what makes the pause safe -- the
    feed position and any in-flight reconcile belong to a cycle that either
    ran completely or did not begin, never to one stopped halfway. The
    position is loop-local and survives a pause for the same reason, so a
    resumed poller continues from where it left off rather than
    re-converging from the feed head.
    """
    last_applied: int | None = None
    logger.info(
        "[CAPACITY] Event poller started for site %r at %s (interval=%ss)",
        site_name, client.base_url, interval,
    )
    while True:
        try:
            if paused is not None and paused():
                await asyncio.sleep(interval)
                continue
            if last_applied is None:
                _, last_applied = await client.events_after(0, limit=1)
                await full_reconcile()
            events, latest = await client.events_after(last_applied)
            if latest < last_applied:
                logger.warning(
                    "[CAPACITY] Site %r feed head moved backwards (%d -> %d) "
                    "— ledger reset? Resyncing from snapshot.",
                    site_name, last_applied, latest,
                )
                last_applied = latest
                await full_reconcile()
                events = []
            for event in events:
                await aggregate.emit_site_delta(site_name, CapacityDelta(
                    kind=str(event.get("kind") or ""),
                    version=int(event.get("version") or 0),
                    resource_id=(
                        str(event["resource_id"])
                        if event.get("resource_id") else None
                    ),
                ))
                last_applied = int(event.get("version") or last_applied)
            if events and latest > last_applied:
                continue  # truncated page — keep draining before sleeping
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[CAPACITY] Site %r poller cycle failed: %s", site_name, exc,
            )
        await asyncio.sleep(interval)
