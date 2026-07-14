"""Site-authority capacity client wiring.

The authoritative capacity ledger lives in site authorities (hosted by
the provisioning service —
docs/development/ARCHITECTURE.md, "Capacity and the Site Authority");
the storefront is strictly a client. ``RemoteCapacityClient`` speaks
one authority's ``/api/v1/capacity`` HTTP surface;
``build_capacity_client`` assembles the configured authorities behind
one ``AggregateCapacityClient``. Capacity deltas arrive by tailing each
authority's versioned event feed (``capacity_events_poller_loop``) —
the client verbs themselves emit nothing locally, so a *different*
storefront's reservation triggers exactly the same listing
reconciliation ours does.

The storefront's own SQLite holds market state only (listings, pricing,
pools, negotiations, deals); physical truth — allocations and their
lease tails — is the ledger's.
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
from core_storefront.capacity import (
    CapacityDelta,
    CapacitySubscriber,
)
from core_storefront.capacity_remote import (  # noqa: F401 — re-exported
    RemoteCapacityClient,
    site_events_poller,
)

logger = logging.getLogger(__name__)

SQLiteClientFactory = Callable[[], Any]


def _capacity_settings() -> tuple[dict[str, str], str, str]:
    """Resolve (sites{name→url}, admin_key, placement) from settings.

    Read at call time so tests that patch
    ``market_storefront.utils.config.settings`` are honored. Sites come
    from the ``[capacity.sites]`` table (name → authority URL); with no
    table, ``authority_url`` becomes the single site named "default",
    falling back to the provisioning service — that process hosts the
    site authority.
    """
    from market_storefront.utils import config

    cap = getattr(config.settings, "capacity", None)
    admin_key = str(getattr(config.settings, "admin_api_key", "") or "")
    placement = str(getattr(cap, "placement", "") or "fill_first").strip()

    sites: dict[str, str] = {}
    raw_sites = getattr(cap, "sites", None)
    if raw_sites:
        for name, url in dict(raw_sites).items():
            url = str(url or "").strip()
            if url:
                sites[str(name)] = url.rstrip("/")
    if not sites:
        url = str(getattr(cap, "authority_url", "") or "").strip()
        if not url:
            url = str(getattr(
                getattr(config.settings, "provisioning", None), "service_url", "",
            ) or "")
        if url:
            sites["default"] = url.rstrip("/")
    if not sites:
        raise RuntimeError(
            "No capacity site authority configured: set "
            "[capacity].authority_url / [capacity.sites], or "
            "[provisioning].service_url (the provisioning service hosts "
            "the site authority).",
        )
    return sites, admin_key, placement


async def member_availability_view(
    client: Any, db_path: str | None = None,
) -> dict[tuple[str | None, str], int]:
    """Available units per pool member, from the aggregated snapshots.

    Keyed ``(site, resource_id)`` — the aggregator's member key. The
    home site (the first configured one) is also keyed ``(None, rid)``,
    matching members that carry no site tag.
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


# Delta kinds that shrink availability and can strand open derived
# listings whose GPU slice no longer fits.
_CONSUMING_DELTA_KINDS = frozenset({"reserved", "committed", "lease_truncated"})


def _make_listing_reconcile_subscriber(
    sqlite_client_factory: SQLiteClientFactory,
    client: Any,
) -> CapacitySubscriber:
    """Reconcile derived listings against site-authority availability.

    This is the storefront's *reaction* to a capacity delta, not part of
    the moving deal's flow — another seller's reservation invalidates
    our listings just the same. Consuming deltas close stranded
    listings, "released" reopens ones that fit again.
    """

    async def _reconcile_listings(delta: CapacityDelta) -> None:
        from core_storefront.stage_log import stage_event
        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
            reopen_available_compute_listings_after_capacity_change,
        )

        db_path = sqlite_client_factory().db_path
        availability = await member_availability_view(client, db_path)
        if delta.kind in _CONSUMING_DELTA_KINDS:
            closed = await close_stale_compute_listings_after_capacity_change(
                db_path, member_availability=availability,
            )
            if closed:
                stage_event(
                    "provision", "stale_compute_listings_closed",
                    resource_id=delta.resource_id,
                    site=delta.site,
                    capacity_version=delta.version,
                    closed_listing_ids=closed,
                )
        elif delta.kind == "released":
            reopened = await reopen_available_compute_listings_after_capacity_change(
                db_path, member_availability=availability,
            )
            if reopened:
                stage_event(
                    "provision", "compute_listings_reopened",
                    resource_id=delta.resource_id,
                    site=delta.site,
                    capacity_version=delta.version,
                    reopened_listing_ids=reopened,
                )

    return _reconcile_listings


# One aggregator per configuration: deltas come from the per-site
# pollers (not from whichever client instance happened to mutate), and
# the allocation→site routing cache must survive across build calls
# within the process.
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
    """Assemble the storefront's capacity client with default subscribers.

    Always an ``AggregateCapacityClient`` over the configured site
    authorities (one site is just the degenerate aggregation).
    """
    sites, admin_key, placement_name = _capacity_settings()
    return _aggregate_for(sqlite_client_factory, sites, admin_key, placement_name)


def remote_site_clients(client: Any) -> dict[str, RemoteCapacityClient]:
    """The per-site remote clients behind a capacity client, by site name.

    Used by callers that need the beyond-the-protocol surface
    (allocation lists, event feeds) — those are per-site conversations,
    not aggregate ones.
    """
    if isinstance(client, AggregateCapacityClient):
        return {
            name: client.site(name)
            for name in client.site_names
            if isinstance(client.site(name), RemoteCapacityClient)
        }
    if isinstance(client, RemoteCapacityClient):
        return {"default": client}
    return {}


async def sync_site_resources(
    sqlite_client_factory: SQLiteClientFactory | None = None,
) -> int:
    """Mirror local compute inventory into the home site's ledger.

    Local rows keep the market view (pricing, escrows, pools); the
    ledger gets the resource-domain core: unit totals and attributes.
    The storefront's local CSV inventory belongs to its home site — the
    first configured one; other sites register their own inventory and
    the aggregator only ever *references* it. Deleted rows are mirrored
    as disabled so the authority stops matching them. Returns the
    number of rows synced.
    """
    sites, admin_key, _ = _capacity_settings()
    if sqlite_client_factory is None:
        from market_storefront.utils.sqlite_client import get_sqlite_client
        sqlite_client_factory = get_sqlite_client

    import json as _json

    default_site, url = next(iter(sites.items()))
    client = RemoteCapacityClient(url, admin_key)
    rows = await sqlite_client_factory().list_resources() or []
    synced = 0
    for row in rows:
        if str(row.get("resource_type") or "") != "compute.gpu":
            continue
        attrs_raw = row.get("attributes") or {}
        if isinstance(attrs_raw, str):
            try:
                attrs_raw = _json.loads(attrs_raw)
            except (ValueError, TypeError):
                attrs_raw = {}
        attrs = {
            k: v for k, v in dict(attrs_raw or {}).items()
            if k != "lease_end_utc"  # lease tail belongs to the ledger
        }
        total = row.get("value")
        if total is None:
            total = attrs.get("gpu_count", 1)
        try:
            total_units = max(int(total), 0)
        except (TypeError, ValueError):
            total_units = 0
        await client.register_resource(
            str(row["resource_id"]),
            total_units=total_units,
            resource_subtype=row.get("resource_subtype"),
            attributes=attrs,
            enabled=str(row.get("state") or "") != "deleted",
        )
        synced += 1
    if synced:
        logger.info(
            "[CAPACITY] Synced %d compute resource(s) to site authority "
            "%r (%s)", synced, default_site, url,
        )
    return synced


async def capacity_events_poller_loop() -> None:
    """Tail every site authority's capacity-event feed into the local bus.

    The delivery half of capacity-scoped events: one poller per
    configured site, each positioning at its feed head, running one full
    listing reconcile to converge with anything missed while down, then
    polling for new versions and emitting each as a site-tagged
    ``CapacityDelta`` on the aggregate bus. A feed head that moves
    backwards (ledger reset) re-runs the full reconcile instead of
    replaying.
    """
    from market_storefront.utils import config
    from market_storefront.utils.sqlite_client import get_sqlite_client

    interval = float(getattr(
        getattr(config.settings, "capacity", None), "poll_interval", 5,
    ) or 5)
    aggregate = build_capacity_client(lambda: get_sqlite_client())
    site_clients = remote_site_clients(aggregate)

    async def _full_reconcile() -> None:
        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
            reopen_available_compute_listings_after_capacity_change,
        )
        db_path = get_sqlite_client().db_path
        availability = await member_availability_view(aggregate, db_path)
        await close_stale_compute_listings_after_capacity_change(
            db_path, member_availability=availability,
        )
        await reopen_available_compute_listings_after_capacity_change(
            db_path, member_availability=availability,
        )

    await asyncio.gather(*(
        site_events_poller(
            aggregate, name, client, interval, full_reconcile=_full_reconcile,
        )
        for name, client in site_clients.items()
    ))
