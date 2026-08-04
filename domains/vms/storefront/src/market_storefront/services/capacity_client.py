"""Site-authority capacity client wiring.

The authoritative capacity ledger lives in site authorities (hosted by
the provisioning service —
docs/development/ARCHITECTURE.md, "Capacity and the Site Authority");
the storefront is strictly a client. ``SiteCapacityClient`` speaks
one authority's ``/api/v1/capacity`` HTTP surface;
``build_capacity_client`` assembles the configured authorities behind
one ``AggregateCapacityClient``. Capacity deltas arrive by tailing each
authority's versioned event feed (``capacity_events_poller_loop``) —
the client verbs themselves emit nothing locally, so a *different*
storefront's reservation triggers exactly the same listing
reconciliation ours does.

The storefront's own SQLite holds market state only (listings, pricing,
pools, negotiations, deals); physical truth — reservations and their
lease tails — is the ledger's.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, Iterable, Mapping

from compute_provisioning import (
    ComputeProvisioningClient,
    ComputeProvisioningError,
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
)
from core_storefront.aggregation import (
    PLACEMENT_POLICIES,
    AggregateCapacityClient,
    fill_first,
    most_available,
)
from core_storefront.capacity import (
    CapacityDelta,
    CapacitySubscriber,
)
from core_storefront.capacity_remote import site_events_poller  # noqa: F401 — re-exported
from market_fulfillment import VersionedEnvelope
from market_site import dict_resource_satisfies_claim
from market_site_client import SiteCapacityClient
from market_storefront.utils.config import settings

logger = logging.getLogger(__name__)

VM_UNIT_CLAIM_KEYS: tuple[str, ...] = ("units", "gpu_count")
"""Must match the VM capacity authority's legacy unit-claim aliases:
``provisioning/compute/service/container.py``'s
``CapacityLedgerService(unit_claim_keys=("units", "gpu_count"))``. The
provisioning service is domain-neutral and cannot import this value from
a VM-domain package, so it is necessarily duplicated at this composition
site.
"""

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

# A mixed-direction capacity registration (e.g. GPU count grew while RAM
# shrank -- POOLS-6 pass 1) can simultaneously strand some listings and
# free up others; neither "consuming" nor "released" alone is safe, so
# both reconciliation passes run.
_MIXED_DIRECTION_DELTA_KINDS = frozenset({"capacity_changed"})


def _make_listing_reconcile_subscriber(
    sqlite_client_factory: SQLiteClientFactory,
    client: Any,
) -> CapacitySubscriber:
    """Reconcile derived listings against site-authority availability.

    This is the storefront's *reaction* to a capacity delta, not part of
    the moving deal's flow — another seller's reservation invalidates
    our listings just the same. Consuming deltas close stranded
    listings, "released" reopens ones that fit again, and a mixed-
    direction "capacity_changed" registration runs both passes since it
    can do both at once.
    """

    async def _reconcile_listings(delta: CapacityDelta) -> None:
        from core_storefront.stage_log import stage_event
        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
            reopen_available_compute_listings_after_capacity_change,
        )

        sites = remote_site_clients(client)
        home_site = next(iter(sites), None)
        if home_site is None:
            return
        db_path = sqlite_client_factory().db_path
        availability = await member_availability_view(client, db_path)
        # Structural capacity source is local tables unless this site is
        # explicitly opted into the projection-sourced path -- see
        # reconciler.available_compute_slices' own docstring for what
        # each source actually provides.
        projection = (
            site_pool_projection()
            if bool(getattr(getattr(settings, "capacity", None), "use_site_projection_for_listings", False))
            else None
        )
        if delta.kind in _CONSUMING_DELTA_KINDS or delta.kind in _MIXED_DIRECTION_DELTA_KINDS:
            closed = await close_stale_compute_listings_after_capacity_change(
                db_path, home_site=home_site, configured_site_count=len(sites),
                member_availability=availability, site_pool_projection=projection,
            )
            if closed:
                stage_event(
                    "provision", "stale_compute_listings_closed",
                    resource_id=delta.resource_id,
                    site=delta.site,
                    capacity_version=delta.version,
                    closed_listing_ids=closed,
                )
        if delta.kind == "released" or delta.kind in _MIXED_DIRECTION_DELTA_KINDS:
            reopened = await reopen_available_compute_listings_after_capacity_change(
                db_path, home_site=home_site, member_availability=availability,
                site_pool_projection=projection,
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
# the reservation→site routing cache must survive across build calls
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
    if placement is most_available:
        # This domain's backing site is kit/site, which owns the only
        # full claim-parsing and feasibility semantics — inject its exact
        # matcher rather than ranking against the aggregator's own
        # deliberately coarse default (pool/resource/dimensions only,
        # not region/gpu_model/etc). PLACEMENT_POLICIES itself stays
        # generic; this substitution is domain-composition-local, not a
        # change to what other domains get when they select
        # "most_available".
        placement = functools.partial(
            most_available,
            claim_matcher=functools.partial(
                dict_resource_satisfies_claim,
                unit_claim_keys=VM_UNIT_CLAIM_KEYS,
            ),
        )
    aggregate = AggregateCapacityClient(
        {
            name: SiteCapacityClient(url, admin_key)
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


# ---------------------------------------------------------------------------
# Fulfillment (schedule/begin/status/result) aggregation.
#
# Sibling to ``AggregateCapacityClient`` above, not an extension of it:
# ``CapacityClient``/``SiteCapacityClient`` are deliberately scoped to the
# site authority's ``/api/v1/capacity`` surface (see their own docstrings),
# while schedule/begin/status/result live on the compute-provisioning
# service's ``/fulfillment`` surface, reached through
# ``ComputeProvisioningClient`` — a different wire contract
# (``compute_provisioning.contracts``), already used for that service's
# other domain-neutral surfaces (jobs, leases).
# ---------------------------------------------------------------------------


class AggregateFulfillmentClient:
    """Routes fulfillment scheduling/acceptance calls to the owning site.

    Shares its ``capacity_reservation_id`` → site routing cache with the
    paired ``AggregateCapacityClient`` (same dict instance, via
    ``build_fulfillment_client``'s ``reservation_sites=``), so a
    reservation's site is learned once, at ``reserve()`` time, and reused
    for both the capacity and fulfillment surfaces — not re-learned or
    tracked twice.

    A cold cache (process restart) falls back to trying every configured
    site in turn, same as ``AggregateCapacityClient.commit``/``release``.
    This is safe, not just convenient: `schedule_resource`/`begin_fulfillment`
    retries are idempotent by `capacity_reservation_id` (see
    `openspec/specs/fulfillment/spec.md`, "Durable settlement persistence" --
    an equivalent retry returns the existing row rather than erroring), so a
    wrong-site attempt before the right one costs latency, not correctness. A
    site that doesn't recognize the reservation answers 404
    (`SettlementEntityNotFoundError`), which routes to the next site exactly
    like a capacity `commit`/`release` refusal does today.
    """

    def __init__(
        self,
        sites: Mapping[str, ComputeProvisioningClient],
        *,
        reservation_sites: dict[str, str],
    ) -> None:
        if not sites:
            raise ValueError("AggregateFulfillmentClient needs at least one site")
        self._sites = dict(sites)
        self._reservation_sites = reservation_sites

    @property
    def site_names(self) -> list[str]:
        return list(self._sites)

    def _route_order(self, capacity_reservation_id: str | None) -> Iterable[str]:
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

    async def schedule_resource(
        self, request: FulfillmentScheduleRequest,
    ) -> FulfillmentScheduleResponse:
        last_error: Exception | None = None
        for name in self._route_order(request.capacity_reservation_id):
            try:
                result = await self._sites[name].schedule_resource(request)
            except ComputeProvisioningError as exc:
                logger.warning(
                    "[FULFILLMENT_AGGREGATOR] schedule at site %r failed, "
                    "trying next: %s", name, exc,
                )
                last_error = exc
                continue
            self._reservation_sites[str(request.capacity_reservation_id)] = name
            return result
        assert last_error is not None
        raise last_error

    async def begin_fulfillment(
        self, body: FulfillmentRequestBody,
    ) -> FulfillmentAcceptanceResponse:
        last_error: Exception | None = None
        for name in self._route_order(body.capacity_reservation_id):
            try:
                result = await self._sites[name].begin_fulfillment(body)
            except ComputeProvisioningError as exc:
                logger.warning(
                    "[FULFILLMENT_AGGREGATOR] begin at site %r failed, "
                    "trying next: %s", name, exc,
                )
                last_error = exc
                continue
            self._reservation_sites[str(body.capacity_reservation_id)] = name
            return result
        assert last_error is not None
        raise last_error

    async def get_fulfillment_status(
        self, fulfillment_id: str, *, capacity_reservation_id: str | None = None,
    ) -> FulfillmentStatusResponse:
        """Read fulfillment status, routed by ``capacity_reservation_id`` if
        the caller has it (it's keyed on that, not ``fulfillment_id``, in the
        shared routing cache — pass it whenever available, e.g. from the
        storefront's own persisted workflow state)."""
        last_error: Exception | None = None
        for name in self._route_order(capacity_reservation_id):
            try:
                return await self._sites[name].get_fulfillment_status(fulfillment_id)
            except ComputeProvisioningError as exc:
                logger.warning(
                    "[FULFILLMENT_AGGREGATOR] status at site %r failed, "
                    "trying next: %s", name, exc,
                )
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    async def get_fulfillment_result(
        self, fulfillment_id: str, *, capacity_reservation_id: str | None = None,
    ) -> VersionedEnvelope[dict[str, Any]]:
        """Read fulfillment result; see ``get_fulfillment_status`` on routing."""
        last_error: Exception | None = None
        for name in self._route_order(capacity_reservation_id):
            try:
                return await self._sites[name].get_fulfillment_result(fulfillment_id)
            except ComputeProvisioningError as exc:
                logger.warning(
                    "[FULFILLMENT_AGGREGATOR] result at site %r failed, "
                    "trying next: %s", name, exc,
                )
                last_error = exc
                continue
        assert last_error is not None
        raise last_error


_fulfillment_aggregate_state: dict[str, Any] = {"key": None, "client": None}


def build_fulfillment_client(
    capacity_client: AggregateCapacityClient,
) -> AggregateFulfillmentClient:
    """Assemble the storefront's fulfillment client, paired with ``capacity_client``.

    Reuses ``capacity_client``'s own site configuration (same names, same
    URLs — the site authority and the compute-provisioning fulfillment
    surface are the same deployed service, per
    ``ARCHITECTURE.md``, "Runtime service map") and its exact
    ``reservation_sites`` dict instance, so routing knowledge learned by one
    aggregator is immediately visible to the other.
    """
    sites, admin_key, _ = _capacity_settings()
    key = tuple(sorted(sites.items())), admin_key
    if _fulfillment_aggregate_state["key"] == key:
        return _fulfillment_aggregate_state["client"]
    aggregate = AggregateFulfillmentClient(
        {
            name: ComputeProvisioningClient(url, admin_key=admin_key)
            for name, url in sites.items()
        },
        reservation_sites=capacity_client.reservation_sites,
    )
    _fulfillment_aggregate_state["key"] = key
    _fulfillment_aggregate_state["client"] = aggregate
    return aggregate


def remote_site_clients(client: Any) -> dict[str, SiteCapacityClient]:
    """The per-site remote clients behind a capacity client, by site name.

    Used by callers that need the beyond-the-protocol surface
    (reservation lists, event feeds) — those are per-site conversations,
    not aggregate ones.
    """
    if isinstance(client, AggregateCapacityClient):
        return {
            name: client.site(name)
            for name in client.site_names
            if isinstance(client.site(name), SiteCapacityClient)
        }
    if isinstance(client, SiteCapacityClient):
        return {"default": client}
    return {}


def site_pool_projection() -> dict[str, list[dict[str, Any]]]:
    """Resource-pool projection rows per site, from the storefront's own
    background poller cache (``site_projection_cache``).

    Only sites whose projection has ever loaded contribute -- ``None``
    (never loaded, or currently unavailable/invalid) is excluded, but a
    successfully loaded site is included *even when its own rows list is
    empty* -- an authoritative "this site currently has zero pools"
    answer, distinct from "this site's answer isn't known yet". Losing
    that distinction (checking the rows list's truthiness instead of
    whether it is ``None``) would make a site's genuine zero-pools state
    indistinguishable from a site that hasn't loaded at all, and
    `reconciler`'s projection-sourced path would then fall back to
    stale local tables instead of correctly registering zero capacity --
    the empty *result* mapping is meaningful too, and is what actually
    signals "fall back to local data" one level up.
    """
    from market_storefront.services.site_projection_cache import projection_caches

    result: dict[str, list[dict[str, Any]]] = {}
    for site, caches in projection_caches().items():
        value = caches.resource_pools.view().value
        if value is not None:
            result[site] = value
    return result


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
