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

from compute_provisioning_client import (
    ComputeProvisioningClient,
    ComputeProvisioningError,
)
from compute_provisioning_contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
    LeaseTermination,
    LeaseView,
)
from core_storefront.aggregation import (
    PLACEMENT_POLICIES,
    AggregateCapacityClient,
    most_available,
)
from core_storefront.service_peers import ServicePeerTrust
from market_capacity_publication import (
    CAPACITY_BUCKET,
    RESOURCE_POOL,
    run_capacity_event_pollers,
    CapacityReconcileContext,
    CapacityRuntime,
    CapacitySite,
    PublicationBinding,
    SiteProjectionState,
    publication_binding,
)
from market_core import VersionedEnvelope
from market_identity import TrustedIdentitySet
from market_site import dict_resource_satisfies_claim
from market_site_client import SiteCapacityClient

from market_storefront import container

logger = logging.getLogger(__name__)

VM_UNIT_CLAIM_KEYS: tuple[str, ...] = ("units", "gpu_count")
"""Must match the VM capacity authority's legacy unit-claim aliases:
``provisioning/compute/service/container.py``'s
``CapacityLedgerService(unit_claim_keys=("units", "gpu_count"))``. The
provisioning service is domain-neutral and cannot import this value from
a VM-domain package, so it is necessarily duplicated at this composition
site.
"""

VM_MIRROR_DIMENSION = "gpu_count"
"""Must match the VM capacity authority's mirror dimension, for the same
reason as ``VM_UNIT_CLAIM_KEYS``: a legacy single-quantity claim is
translated into this dimension on both sides of the boundary.
"""

SQLiteClientFactory = Callable[[], Any]


def _capacity_settings() -> tuple[dict[str, str], str]:
    """Resolve explicit stable site IDs and the configured placement policy."""
    from market_storefront.utils import config

    cap = getattr(config.settings, "capacity", None)
    placement = str(getattr(cap, "placement", "") or "fill_first").strip()
    return config.configured_capacity_sites(config.settings), placement


_CONSUMING_DELTA_KINDS = frozenset({"reserved", "committed", "lease_truncated"})
_MIXED_DIRECTION_DELTA_KINDS = frozenset({"capacity_changed"})


SiteProjectionsProvider = Callable[[], SiteProjectionState | None]


class _LateSiteProjections:
    """The projection state a runtime's reconciler reads, bound after the runtime.

    The state is composed over the runtime's own aggregate, so it cannot exist
    when the runtime's reconciler does; the composition root binds it here once
    it has built it. A runtime nothing has bound reconciles no delta.
    """

    def __init__(self) -> None:
        self.provider: SiteProjectionsProvider = lambda: None

    def __call__(self) -> SiteProjectionState | None:
        return self.provider()


class _LateServicePeerTrust:
    """The service-peer trust a runtime's site clients verify against, bound
    after the runtime is built.

    The runtime is cached across compositions in one process, so each
    composition root binds its own trust here; a site's provider reads whichever
    is bound at each response. A runtime nothing has bound verifies no response.
    The fulfillment clients built beside the runtime read the same binding, so
    a site's capacity and fulfillment responses verify against one trust.
    """

    def __init__(self) -> None:
        self.trust: ServicePeerTrust | None = None

    def site_authorities(self, site_id: str) -> Callable[[], TrustedIdentitySet]:
        def authorities() -> TrustedIdentitySet:
            trust = self.trust
            if trust is None:
                raise RuntimeError("no service-peer trust is bound to the capacity runtime")
            return trust.site_trusted_set(site_id)

        return authorities


def _capacity_reconciler(
    sqlite_client_factory: SQLiteClientFactory,
    *,
    site_projections: SiteProjectionsProvider,
) -> Callable[[CapacityReconcileContext], Any]:
    """Supply VM candidate semantics to the kit-owned reconciliation loop.

    ``site_projections`` is read when a delta arrives, not when the reconciler
    is built, so a state composed after the runtime reaches it.
    """

    async def _reconcile(context: CapacityReconcileContext) -> None:
        from core_storefront.stage_log import stage_event

        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
            reopen_available_compute_listings_after_capacity_change,
        )

        state = site_projections()
        if state is None:
            # No site's projection is held, so every listing's source is
            # unknown and nothing may be closed or reopened on it.
            logger.warning("[CAPACITY] no site projection state; delta not reconciled")
            return
        # A fungible listing's availability is read from its site's capacity
        # buckets, which change with the event being reconciled; the held
        # generation is the last poll's, older than the event. Refresh the
        # event's site (every site, for a full reconcile) first, as inline
        # reconciliation refreshes what it reconciles: this never wakes
        # publication, and a failed fetch leaves the held generation stale,
        # which is reconciled over as it stands.
        delta_site = context.delta.site if context.delta is not None else None
        for site_id in (
            [delta_site]
            if delta_site is not None
            else [projection.site_id for projection in context.projections]
        ):
            await state.refresh_site(site_id, families=[CAPACITY_BUCKET])
        db = sqlite_client_factory()
        projection = site_pool_projection(state)
        buckets = site_capacity_buckets(state)
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
                configured_sites=[site.site_id for site in context.projections],
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
                configured_sites=[site.site_id for site in context.projections],
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


_capacity_runtime_state: dict[str, Any] = {
    "key": None,
    "runtime": None,
    "site_projections": None,
    "service_peer_trust": _LateServicePeerTrust(),
}


def build_capacity_runtime_for(
    sqlite_client_factory: SQLiteClientFactory,
    *,
    signer: Any,
    site_projections: SiteProjectionsProvider | None = None,
    service_peer_trust: ServicePeerTrust | None = None,
    site_client_factory: Callable[[CapacitySite, Any], Any] | None = None,
) -> CapacityRuntime:
    """Compose the kit runtime from explicit repository and signer collaborators.

    ``site_projections`` is the composition root's provider of the projection
    state its capacity reconciliation reads, and ``service_peer_trust`` the
    trust each site's responses are verified against, that site's own service
    peer's active principals; a caller that is not the root passes neither and
    leaves the root's bindings in place. ``site_client_factory`` replaces how a
    configured site's client is built, as the kit runtime's constructor allows,
    and is part of what the cached runtime is keyed by.
    """

    if signer is None:
        raise RuntimeError("storefront marketplace signer is unavailable")
    sites, placement_name = _capacity_settings()
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
                mirror_dimension=VM_MIRROR_DIMENSION,
            ),
        )
    db_path = str(getattr(sqlite_client_factory(), "db_path", ""))
    # No principal is part of the key: each site's trust is read from the bound
    # service-peer trust at every response, so a rotation reuses the runtime.
    key = (
        tuple(sorted(sites.items())),
        placement_name,
        signer.identity.scheme.value,
        signer.identity.identifier,
        db_path,
        site_client_factory,
    )
    if _capacity_runtime_state["key"] != key:
        late = _LateSiteProjections()
        # A fresh binding for a fresh runtime, which verifies nothing until a
        # root binds its trust; the fulfillment clients follow it.
        late_trust = _LateServicePeerTrust()
        _capacity_runtime_state["key"] = key
        _capacity_runtime_state["site_projections"] = late
        _capacity_runtime_state["service_peer_trust"] = late_trust
        _capacity_runtime_state["runtime"] = CapacityRuntime(
            sites=tuple(
                CapacitySite(site_id, url, late_trust.site_authorities(site_id))
                for site_id, url in sites.items()
            ),
            signer=signer,
            placement=placement,
            reconcile=_capacity_reconciler(sqlite_client_factory, site_projections=late),
            **(
                {}
                if site_client_factory is None
                else {"site_client_factory": site_client_factory}
            ),
        )
    if site_projections is not None:
        _capacity_runtime_state["site_projections"].provider = site_projections
    if service_peer_trust is not None:
        _capacity_runtime_state["service_peer_trust"].trust = service_peer_trust
    return _capacity_runtime_state["runtime"]


def build_capacity_runtime(
    sqlite_client_factory: SQLiteClientFactory,
) -> CapacityRuntime:
    """Return the root-composed runtime for legacy non-root VM call sites."""

    return build_capacity_runtime_for(
        sqlite_client_factory,
        signer=container.resolved_marketplace_signer,
    )


def build_capacity_client(
    sqlite_client_factory: SQLiteClientFactory,
) -> AggregateCapacityClient:
    """Return the kit-owned runtime's aggregate capacity transport."""
    return build_capacity_runtime(sqlite_client_factory).client()

async def capacity_binding_for_listing(
    sqlite_client: Any,
    listing_id: str,
) -> PublicationBinding:
    """Resolve the VM listing's exact durable site, mode, source, and backing.

    Every capacity effect takes this binding, and the capacity runtime's guard
    refuses one whose backing admits no effect before any site call.
    """
    from arkhai_vms_listings.models import Listing

    durable = await sqlite_client.load_listing_binding(listing_id=listing_id)
    row = await sqlite_client.load_listing(listing_id=listing_id)
    source_id = (
        durable.pool_id or durable.physical_resource_id
        if durable is not None
        else None
    )
    if durable is None or source_id is None or row is None:
        raise RuntimeError(
            f"listing {listing_id!r} has no complete durable capacity binding"
        )
    listing = Listing.model_validate(row)
    mode = listing.listing_resource.offering_mode
    offering_mode = mode.value if hasattr(mode, "value") else str(mode or "")
    if offering_mode != durable.binding.offering_mode:
        raise RuntimeError(
            f"listing {listing_id!r} offering mode disagrees with its durable binding"
        )
    return publication_binding(
        capacity_backing=durable.capacity_backing,
        site_id=durable.site_id,
        offering_mode=offering_mode,
        source_id=source_id,
    )


# ---------------------------------------------------------------------------
# Fulfillment (schedule/begin/status/result) aggregation.
#
# Sibling to ``AggregateCapacityClient`` above, not an extension of it:
# ``CapacityClient``/``SiteCapacityClient`` are deliberately scoped to the
# site authority's ``/api/v1/capacity`` surface (see their own docstrings),
# while schedule/begin/status/result live on the compute-provisioning
# service's ``/fulfillment`` surface, reached through
# ``ComputeProvisioningClient`` — a different wire contract
# (``compute_provisioning_contracts``), already used for that service's
# other domain-neutral surfaces (jobs, leases).
# ---------------------------------------------------------------------------


class AggregateFulfillmentClient:
    """Routes fulfillment calls to an explicitly recorded trusted site.

    The shared reservation cache remains available to legacy callers, but
    record-bound storefront flows pass ``site_id`` on every call.  A targeted
    call addresses exactly that configured client and propagates its refusal
    or error without consulting the cache or another site.
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
        *,
        site_id: str | None = None,
    ) -> FulfillmentScheduleResponse:
        if site_id is not None:
            result = await self._sites[site_id].schedule_resource(request)
            self._reservation_sites[str(request.capacity_reservation_id)] = site_id
            return result
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
        *,
        site_id: str | None = None,
    ) -> FulfillmentAcceptanceResponse:
        if site_id is not None:
            result = await self._sites[site_id].begin_fulfillment(body)
            self._reservation_sites[str(body.capacity_reservation_id)] = site_id
            return result
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
        site_id: str | None = None,
    ) -> FulfillmentStatusResponse:
        """Read fulfillment status, routed by ``capacity_reservation_id`` if
        the caller has it (it's keyed on that, not ``fulfillment_id``, in the
        shared routing cache — pass it whenever available, e.g. from the
        storefront's own persisted workflow state)."""
        if site_id is not None:
            return await self._sites[site_id].get_fulfillment_status(fulfillment_id)
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
        site_id: str | None = None,
    ) -> VersionedEnvelope[dict[str, Any]]:
        """Read fulfillment result; see ``get_fulfillment_status`` on routing."""
        if site_id is not None:
            return await self._sites[site_id].get_fulfillment_result(fulfillment_id)
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

    async def begin_fulfillment_teardown(
        self,
        fulfillment_id: str,
        *,
        site_id: str,
    ) -> Any:
        """Begin teardown only at the accepted fulfillment's recorded site."""

        return await self._sites[site_id].begin_fulfillment_teardown(fulfillment_id)

    async def terminate_lease(
        self,
        capacity_reservation_id: str,
        *,
        site_id: str,
        reason: str | None = None,
    ) -> LeaseView:
        """End the reservation's lease at its recorded site, and only there.

        The site converges teardown through the lease's fulfillment and releases
        the capacity once; terminating a lease already ending returns it as it is.
        """

        return await self._sites[site_id].terminate_lease(
            capacity_reservation_id, LeaseTermination(reason=reason)
        )


_fulfillment_aggregate_state: dict[str, Any] = {"key": None, "client": None}


#: Builds one site's fulfillment client from its site ID, authority URL, the
#: storefront's signer, and the provider of that site's trusted principals.
ProvisioningSiteClientFactory = Callable[
    [str, str, Any, Callable[[], TrustedIdentitySet]], Any
]


def _provisioning_site_client(
    _site_id: str,
    url: str,
    signer: Any,
    authorities: Callable[[], TrustedIdentitySet],
) -> ComputeProvisioningClient:
    return ComputeProvisioningClient(
        url,
        signer=signer,
        caller_role="seller",
        expected_authorities=authorities,
    )


def build_fulfillment_client(
    capacity_client: AggregateCapacityClient,
    *,
    client_factory: ProvisioningSiteClientFactory | None = None,
) -> AggregateFulfillmentClient:
    """Assemble the storefront's fulfillment client, paired with ``capacity_client``.

    Reuses ``capacity_client``'s own site configuration (same names, same
    URLs — the site authority and the compute-provisioning fulfillment
    surface are the same deployed service, per
    ``ARCHITECTURE.md``, "Runtime service map") and its exact
    ``reservation_sites`` dict instance, so routing knowledge learned by one
    aggregator is immediately visible to the other.

    Each site's client verifies its responses against that site's own service
    peer's active principals, through the trust the capacity runtime's site
    clients read, so a rotation reaches both and one site's principal verifies
    no other site's responses. ``client_factory`` replaces how a site's client
    is built from its ID, URL, signer, and provider of trusted principals, and
    is part of what the cached aggregate is keyed by.
    """
    sites, _ = _capacity_settings()
    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is unavailable")
    trust = _capacity_runtime_state["service_peer_trust"]
    # No principal is part of the key, as for the capacity runtime: each
    # site's trust is read from the bound service-peer trust at every response.
    key = (
        tuple(sorted(sites.items())),
        signer.identity.scheme.value,
        signer.identity.identifier,
        trust,
        client_factory,
    )
    if _fulfillment_aggregate_state["key"] == key:
        return _fulfillment_aggregate_state["client"]
    build = client_factory or _provisioning_site_client
    aggregate = AggregateFulfillmentClient(
        {
            name: build(name, url, signer, trust.site_authorities(name))
            for name, url in sites.items()
        },
        reservation_sites=capacity_client.reservation_sites,
    )
    _fulfillment_aggregate_state["key"] = key
    _fulfillment_aggregate_state["client"] = aggregate
    return aggregate


def site_pool_projection(state: SiteProjectionState) -> dict[str, list[dict[str, Any]]]:
    """Resource-pool projection rows per site, from the storefront's one
    per-site projection state.

    Only sites holding a generation contribute, loaded or stale; a site that
    has never loaded, or whose load failed with no earlier value, is absent. A
    loaded site is included *even when its rows list is empty*: that is an
    authoritative "this site has zero pools" answer, distinct from "this site's
    answer is not known". Derivation holds the listings of every configured
    site absent here rather than reading it as empty, and an empty mapping
    derives nothing.

    Publication, capacity reconciliation, the inventory guard, and override
    status all read listing sources through this, so they never disagree about
    which sites are known.
    """
    return dict(state.values(RESOURCE_POOL))


def site_capacity_buckets(state: SiteProjectionState) -> dict[str, list[dict[str, Any]]]:
    """Grouped capacity-bucket rows per site, under ``site_pool_projection``'s
    inclusion rule -- only a site whose capacity-bucket family holds a
    generation contributes, including an authoritative empty list, for the
    same reason: `reconciler`'s fungible-mode row builder
    (`_projected_pool_rows`) must be able to tell "no bucket data yet" from
    "genuinely zero buckets" and falls back to its own resource-list
    computation only in the former case.
    """
    return dict(state.values(CAPACITY_BUCKET))


def site_projection_status(
    state: SiteProjectionState,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Per-site, per-family load state as operator surfaces report it.

    State and identity only, never the held rows. A missing site or a
    `not_loaded`/`unavailable`/`invalid` state means the family has not been
    confirmed; it must never be read as authoritative empty capacity.
    """
    return {
        site_id: {family: status.model_dump() for family, status in families.items()}
        for site_id, families in state.status().items()
    }


async def capacity_events_poller_loop(sqlite_client: Any) -> None:
    """Delegate multi-site event delivery and reconciliation to the kit.

    The aggregate name is what the admin advance route addresses and what a
    storefront with no site configured still reports; the per-site gates are
    what actually hold the pollers, since the kit owns their fan-out, and each
    site's timer cycles record their outcomes under the same per-site names,
    declared as the aggregate loop's children.
    """
    from market_storefront.utils import config
    from market_storefront.lifecycle import (
        CAPACITY_EVENTS_POLLER,
        capacity_site_cycle_recorder,
        capacity_site_gate,
        gate,
        idle,
    )

    interval = config.site_projection_poll_interval()
    # The runtime the capacity-events step drains, so the timer and the step
    # address one runtime's sites.
    runtime = container.resolved_capacity_runtime or build_capacity_runtime(
        lambda: sqlite_client
    )
    await run_capacity_event_pollers(
        functools.partial(runtime.poll_events, interval_seconds=interval),
        gate=functools.partial(gate, CAPACITY_EVENTS_POLLER),
        site_gate=capacity_site_gate,
        wait=idle,
        record_site_cycle=capacity_site_cycle_recorder,
    )
