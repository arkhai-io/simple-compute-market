"""Quota-ledger capacity client wiring.

The authoritative quota ledger lives in the tokens service (it mounts
the shared ``core_site`` ledger); the storefront is strictly a client.
The composed shape mirrors the VM storefront: per-site
``RemoteCapacityClient``s behind one ``AggregateCapacityClient``, with
capacity deltas arriving by tailing each authority's versioned event
feed, and the storefront's reaction — token-listing close/reopen —
subscribed on the aggregate bus.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Mapping

from core_storefront.aggregation import (
    PLACEMENT_POLICIES,
    AggregateCapacityClient,
    fill_first,
)
from core_storefront.capacity import CapacityDelta, CapacitySubscriber
from core_storefront.capacity_remote import (
    RemoteCapacityClient,
    site_events_poller,
)

logger = logging.getLogger(__name__)

SQLiteClientFactory = Callable[[], Any]


def _capacity_settings() -> tuple[dict[str, str], str, str]:
    """Resolve (sites{name→url}, admin_key, placement) from settings.

    Sites come from the ``[capacity.sites]`` table; with no table,
    ``authority_url`` becomes the single site "default", falling back to
    the tokens service — that process hosts the quota ledger.
    """
    from apitokens_storefront.utils import config

    admin_key = config.tokens_admin_key()
    placement = str(
        config.settings.get("capacity.placement", "") or "fill_first"
    ).strip()

    sites: dict[str, str] = {}
    raw_sites = config.settings.get("capacity.sites")
    if raw_sites and hasattr(raw_sites, "items"):
        for name, url in dict(raw_sites).items():
            url = str(url or "").strip()
            if url:
                sites[str(name)] = url.rstrip("/")
    if not sites:
        url = str(config.settings.get("capacity.authority_url", "") or "").strip()
        if not url:
            url = config.tokens_service_url()
        if url:
            sites["default"] = url.rstrip("/")
    if not sites:
        raise RuntimeError(
            "No quota authority configured: set [capacity].authority_url / "
            "[capacity.sites], or [tokens].service_url (the tokens service "
            "hosts the quota ledger).",
        )
    return sites, admin_key, placement


# Delta kinds that shrink availability and can strand open listings.
_CONSUMING_DELTA_KINDS = frozenset({"reserved", "committed", "lease_truncated"})


def _make_listing_reconcile_subscriber(
    sqlite_client_factory: SQLiteClientFactory,
    client: Any,
) -> CapacitySubscriber:
    """Close exhausted token listings / reopen replenished ones on deltas."""

    async def _reconcile_listings(delta: CapacityDelta) -> None:
        from core_storefront.stage_log import stage_event

        from apitokens_storefront.services.publication_service import (
            close_token_listings_after_capacity_change,
            reopen_token_listings_after_capacity_change,
        )

        db = sqlite_client_factory()
        if delta.kind in _CONSUMING_DELTA_KINDS:
            closed = await close_token_listings_after_capacity_change(db, client)
            if closed:
                stage_event(
                    "provision", "token_listings_closed",
                    resource_id=delta.resource_id,
                    site=delta.site,
                    capacity_version=delta.version,
                    closed_listing_ids=closed,
                )
        elif delta.kind == "released":
            reopened = await reopen_token_listings_after_capacity_change(db, client)
            if reopened:
                stage_event(
                    "provision", "token_listings_reopened",
                    resource_id=delta.resource_id,
                    site=delta.site,
                    capacity_version=delta.version,
                    reopened_listing_ids=reopened,
                )

    return _reconcile_listings


_aggregate_state: dict[str, Any] = {"key": None, "client": None}


def _aggregate_for(
    sqlite_client_factory: SQLiteClientFactory,
    sites: Mapping[str, str],
    admin_key: str,
    placement_name: str,
) -> AggregateCapacityClient:
    key = (tuple(sorted(sites.items())), admin_key, placement_name)
    if _aggregate_state["key"] == key:
        return _aggregate_state["client"]
    placement = PLACEMENT_POLICIES.get(placement_name)
    if placement is None:
        logger.warning(
            "[CAPACITY] Unknown placement policy %r — using fill_first "
            "(known: %s)", placement_name, sorted(PLACEMENT_POLICIES),
        )
        placement = fill_first
    aggregate = AggregateCapacityClient(
        {
            name: RemoteCapacityClient(url, admin_key)
            for name, url in sites.items()
        },
        placement=placement,
    )
    aggregate.subscribe(
        _make_listing_reconcile_subscriber(sqlite_client_factory, aggregate),
    )
    _aggregate_state["key"] = key
    _aggregate_state["client"] = aggregate
    return aggregate


def build_capacity_client(
    sqlite_client_factory: SQLiteClientFactory,
) -> AggregateCapacityClient:
    """Assemble the storefront's quota capacity client with subscribers."""
    sites, admin_key, placement_name = _capacity_settings()
    return _aggregate_for(sqlite_client_factory, sites, admin_key, placement_name)


def remote_site_clients(client: Any) -> dict[str, RemoteCapacityClient]:
    """Per-site remote clients behind a capacity client, by site name."""
    if isinstance(client, AggregateCapacityClient):
        return {
            name: client.site(name)
            for name in client.site_names
            if isinstance(client.site(name), RemoteCapacityClient)
        }
    if isinstance(client, RemoteCapacityClient):
        return {"default": client}
    return {}


async def availability_view(
    client: Any,
) -> dict[tuple[str | None, str], int]:
    """Available units per quota resource, keyed ``(site, resource_id)``.

    Home-site rows are also keyed ``(None, rid)`` — the same convention
    as the VM storefront's member view, which the token reconciler
    consumes.
    """
    view: dict[tuple[str | None, str], int] = {}
    sites = remote_site_clients(client)
    if not sites:
        return view
    home_site = next(iter(sites))
    for row in await client.snapshot():
        resource_id = row.get("resource_id")
        available = row.get("available_units")
        if not resource_id or available is None:
            continue
        site = row.get("site") or home_site
        available = max(int(available), 0)
        if site == home_site:
            view[(None, str(resource_id))] = available
        view[(str(site), str(resource_id))] = available
    return view


async def capacity_events_poller_loop() -> None:
    """Tail every quota authority's capacity-event feed into the local bus."""
    from apitokens_storefront.utils import config
    from apitokens_storefront.utils.sqlite_client import get_sqlite_client

    interval = float(config.settings.get("capacity.poll_interval", 5) or 5)
    aggregate = build_capacity_client(lambda: get_sqlite_client())
    site_clients = remote_site_clients(aggregate)

    async def _full_reconcile() -> None:
        from apitokens_storefront.services.publication_service import (
            close_token_listings_after_capacity_change,
            reopen_token_listings_after_capacity_change,
        )

        db = get_sqlite_client()
        await close_token_listings_after_capacity_change(db, aggregate)
        await reopen_token_listings_after_capacity_change(db, aggregate)

    await asyncio.gather(*(
        site_events_poller(
            aggregate, name, client, interval, full_reconcile=_full_reconcile,
        )
        for name, client in site_clients.items()
    ))
