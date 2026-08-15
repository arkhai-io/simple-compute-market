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

import functools
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

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
    most_available,
)
from market_capacity_publication import (
    CapacityBinding,
    CapacityReconcileContext,
    CapacityRuntime,
    CapacitySite,
)
from market_fulfillment import VersionedEnvelope
from market_site import dict_resource_satisfies_claim
from market_resource_pools import pool_delivers_offering_mode
from market_site_client import SiteCapacityClient

from market_storefront.utils.config import get_provisioning_authorities, settings

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


def _capacity_settings() -> tuple[dict[str, str], str]:
    """Resolve explicit stable site IDs and the configured placement policy."""
    from market_storefront.utils import config

    cap = getattr(config.settings, "capacity", None)
    placement = str(getattr(cap, "placement", "") or "fill_first").strip()
    raw_sites = getattr(cap, "sites", None)
    if not raw_sites:
        raise RuntimeError(
            "No capacity site authority configured: [capacity.sites] must map "
            "each stable site ID to an authority URL."
        )
    sites: dict[str, str] = {}
    for raw_name, raw_url in dict(raw_sites).items():
        site_id = str(raw_name).strip()
        url = str(raw_url or "").strip().rstrip("/")
        if not site_id or not url:
            raise RuntimeError("capacity site IDs and authority URLs must be non-empty")
        sites[site_id] = url
    return sites, placement


_CONSUMING_DELTA_KINDS = frozenset({"reserved", "committed", "lease_truncated"})
_MIXED_DIRECTION_DELTA_KINDS = frozenset({"capacity_changed"})


def _capacity_reconciler(
    sqlite_client_factory: SQLiteClientFactory,
) -> Callable[[CapacityReconcileContext], Any]:
    """Supply VM candidate semantics to the kit-owned reconciliation loop."""

    async def _reconcile(context: CapacityReconcileContext) -> None:
        from core_storefront.stage_log import stage_event

        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
            reopen_available_compute_listings_after_capacity_change,
        )

        home_site = context.projections[0].site_id
        db = sqlite_client_factory()
        projection = (
            site_pool_projection()
            if bool(
                getattr(
                    getattr(settings, "capacity", None),
                    "use_site_projection_for_listings",
                    False,
                )
            )
            else None
        )
        buckets = site_capacity_buckets() if projection is not None else None
        delta = context.delta
        close = (
            delta is None
            or delta.kind in _CONSUMING_DELTA_KINDS
            or delta.kind in _MIXED_DIRECTION_DELTA_KINDS
        )
        reopen = (
            delta is None
            or delta.kind == "released"
            or delta.kind in _MIXED_DIRECTION_DELTA_KINDS
        )
        if close:
            closed = await close_stale_compute_listings_after_capacity_change(
                db.db_path,
                sqlite_client=db,
                home_site=home_site,
                configured_site_count=len(context.projections),
                member_availability=dict(context.availability),
                site_pool_projection=projection,
                site_capacity_buckets=buckets,
            )
            if closed:
                stage_event(
                    "provision",
                    "stale_compute_listings_closed",
                    resource_id=delta.resource_id if delta is not None else None,
                    site=delta.site if delta is not None else None,
                    capacity_version=delta.version if delta is not None else None,
                    closed_listing_ids=closed,
                )
        if reopen:
            reopened = await reopen_available_compute_listings_after_capacity_change(
                db.db_path,
                sqlite_client=db,
                home_site=home_site,
                member_availability=dict(context.availability),
                site_pool_projection=projection,
                site_capacity_buckets=buckets,
            )
            if reopened:
                stage_event(
                    "provision",
                    "compute_listings_reopened",
                    resource_id=delta.resource_id if delta is not None else None,
                    site=delta.site if delta is not None else None,
                    capacity_version=delta.version if delta is not None else None,
                    reopened_listing_ids=reopened,
                )

    return _reconcile


_capacity_runtime_state: dict[str, Any] = {"key": None, "runtime": None}


def build_capacity_runtime(
    sqlite_client_factory: SQLiteClientFactory,
) -> CapacityRuntime:
    """Compose VM codecs/configuration onto the kit-owned capacity runtime."""
    from market_storefront import container

    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is unavailable")
    sites, placement_name = _capacity_settings()
    expected_authorities = get_provisioning_authorities()
    placement = PLACEMENT_POLICIES.get(placement_name)
    if placement is None:
        raise RuntimeError(
            f"unknown capacity placement policy {placement_name!r}; "
            f"expected one of {sorted(PLACEMENT_POLICIES)}"
        )
    if placement is most_available:
        placement = functools.partial(
            most_available,
            claim_matcher=functools.partial(
                dict_resource_satisfies_claim,
                unit_claim_keys=VM_UNIT_CLAIM_KEYS,
            ),
        )
    db_path = str(getattr(sqlite_client_factory(), "db_path", ""))
    key = (
        tuple(sorted(sites.items())),
        placement_name,
        signer.identity.scheme.value,
        signer.identity.identifier,
        tuple(
            (principal.scheme.value, principal.identifier)
            for principal in expected_authorities.identities
        ),
        db_path,
    )
    if _capacity_runtime_state["key"] != key:
        _capacity_runtime_state["key"] = key
        _capacity_runtime_state["runtime"] = CapacityRuntime(
            sites=tuple(
                CapacitySite(site_id, url, expected_authorities)
                for site_id, url in sites.items()
            ),
            signer=signer,
            placement=placement,
            reconcile=_capacity_reconciler(sqlite_client_factory),
        )
    return _capacity_runtime_state["runtime"]


def build_capacity_client(
    sqlite_client_factory: SQLiteClientFactory,
) -> AggregateCapacityClient:
    """Return the kit-owned runtime's aggregate capacity transport."""
    return build_capacity_runtime(sqlite_client_factory).client()

async def capacity_binding_for_listing(
    sqlite_client: Any,
    listing_id: str,
) -> CapacityBinding:
    """Resolve and validate the VM candidate's exact durable pool binding."""
    from domains.vms.listings.models import Listing
    from domains.vms.listings.reconciler import (
        pool_id_for_listing,
        site_id_for_listing,
    )
    from market_storefront.utils.sync_negotiation import lookup_pool_policy_tags

    site_id = site_id_for_listing(sqlite_client.db_path, listing_id)
    source_id = pool_id_for_listing(sqlite_client.db_path, listing_id)
    row = await sqlite_client.load_listing(listing_id=listing_id)
    if site_id is None or source_id is None or row is None:
        raise RuntimeError(
            f"listing {listing_id!r} has no complete durable capacity binding"
        )
    listing = Listing.model_validate(row)
    mode = listing.offer_resource.virtualization_type
    offering_mode = mode.value if hasattr(mode, "value") else str(mode or "")
    if not offering_mode:
        raise RuntimeError(f"listing {listing_id!r} has no offering mode")
    policy_tags = lookup_pool_policy_tags(sqlite_client, listing_id)
    if not pool_delivers_offering_mode(policy_tags, offering_mode):
        raise RuntimeError(
            f"pool {source_id!r} does not declare offering mode {offering_mode!r}"
        )
    return CapacityBinding(site_id, offering_mode, source_id)


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
            if capacity_reservation_id
            else None
        )
        if cached and cached in self._sites:
            yield cached
            for name in self._sites:
                if name != cached:
                    yield name
        else:
            yield from self._sites

    async def schedule_resource(
        self,
        request: FulfillmentScheduleRequest,
    ) -> FulfillmentScheduleResponse:
        last_error: Exception | None = None
        for name in self._route_order(request.capacity_reservation_id):
            try:
                result = await self._sites[name].schedule_resource(request)
            except ComputeProvisioningError as exc:
                logger.warning(
                    "[FULFILLMENT_AGGREGATOR] schedule at site %r failed, "
                    "trying next: %s",
                    name,
                    exc,
                )
                last_error = exc
                continue
            self._reservation_sites[str(request.capacity_reservation_id)] = name
            return result
        assert last_error is not None
        raise last_error

    async def begin_fulfillment(
        self,
        body: FulfillmentRequestBody,
    ) -> FulfillmentAcceptanceResponse:
        last_error: Exception | None = None
        for name in self._route_order(body.capacity_reservation_id):
            try:
                result = await self._sites[name].begin_fulfillment(body)
            except ComputeProvisioningError as exc:
                logger.warning(
                    "[FULFILLMENT_AGGREGATOR] begin at site %r failed, trying next: %s",
                    name,
                    exc,
                )
                last_error = exc
                continue
            self._reservation_sites[str(body.capacity_reservation_id)] = name
            return result
        assert last_error is not None
        raise last_error

    async def get_fulfillment_status(
        self,
        fulfillment_id: str,
        *,
        capacity_reservation_id: str | None = None,
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
                    "trying next: %s",
                    name,
                    exc,
                )
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    async def get_fulfillment_result(
        self,
        fulfillment_id: str,
        *,
        capacity_reservation_id: str | None = None,
    ) -> VersionedEnvelope[dict[str, Any]]:
        """Read fulfillment result; see ``get_fulfillment_status`` on routing."""
        last_error: Exception | None = None
        for name in self._route_order(capacity_reservation_id):
            try:
                return await self._sites[name].get_fulfillment_result(fulfillment_id)
            except ComputeProvisioningError as exc:
                logger.warning(
                    "[FULFILLMENT_AGGREGATOR] result at site %r failed, "
                    "trying next: %s",
                    name,
                    exc,
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
    sites, _ = _capacity_settings()
    from market_storefront import container

    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is unavailable")
    expected_authorities = get_provisioning_authorities()
    key = (
        tuple(sorted(sites.items())),
        signer.identity.scheme.value,
        signer.identity.identifier,
        tuple(
            (principal.scheme.value, principal.identifier)
            for principal in expected_authorities.identities
        ),
    )
    if _fulfillment_aggregate_state["key"] == key:
        return _fulfillment_aggregate_state["client"]
    aggregate = AggregateFulfillmentClient(
        {
            name: ComputeProvisioningClient(
                url,
                signer=signer,
                caller_role="seller",
                expected_authorities=expected_authorities,
            )
            for name, url in sites.items()
        },
        reservation_sites=capacity_client.reservation_sites,
    )
    _fulfillment_aggregate_state["key"] = key
    _fulfillment_aggregate_state["client"] = aggregate
    return aggregate




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


def site_capacity_buckets() -> dict[str, list[dict[str, Any]]]:
    """Grouped capacity-bucket rows per site, same cache/inclusion rule as
    ``site_pool_projection`` (above) -- only a site whose capacity-bucket
    family has ever loaded contributes, including an authoritative empty
    list, for the same reason: `reconciler`'s fungible-mode row builder
    (`_projected_pool_rows`) must be able to tell "no bucket data yet" from
    "genuinely zero buckets" and falls back to its own resource-list
    computation only in the former case.
    """
    from market_storefront.services.site_projection_cache import projection_caches

    result: dict[str, list[dict[str, Any]]] = {}
    for site, caches in projection_caches().items():
        value = caches.capacity_buckets.view().value
        if value is not None:
            result[site] = value
    return result


async def capacity_events_poller_loop(sqlite_client: Any) -> None:
    """Delegate multi-site event delivery and reconciliation to the kit."""
    from market_storefront.utils import config

    interval = float(
        getattr(
            getattr(config.settings, "capacity", None),
            "poll_interval",
            5,
        )
        or 5
    )
    await build_capacity_runtime(lambda: sqlite_client).poll_events(
        interval_seconds=interval
    )
