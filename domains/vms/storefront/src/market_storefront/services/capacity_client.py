"""Site-authority capacity clients: embedded and remote.

Two implementations of ``core_storefront.capacity.CapacityClient``
(docs/development/design-settlement-lifecycle-and-capacity.md, Part II),
selected by ``[capacity] mode`` in settings:

- ``EmbeddedCapacityClient`` (default): the single-storefront degenerate
  deployment — the ``hosts``/``compute_allocations`` ledger still lives
  in this storefront's SQLite. Embedded mode is for a provably single
  consumer; another storefront must never reach this ledger through
  this process.
- ``RemoteCapacityClient`` (``mode = "site"``): the ledger lives in the
  site authority (hosted by the provisioning service) and this client
  speaks its ``/api/v1/capacity`` HTTP surface. Capacity deltas arrive
  by tailing the authority's versioned event feed
  (``capacity_events_poller_loop``) — the remote verbs themselves emit
  nothing locally, so a *different* storefront's reservation triggers
  exactly the same listing reconciliation ours does.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Mapping

import httpx

from core_storefront.aggregation import (
    PLACEMENT_POLICIES,
    AggregateCapacityClient,
    fill_first,
)
from core_storefront.capacity import (
    CapacityDelta,
    CapacityEventBus,
    CapacitySubscriber,
)

logger = logging.getLogger(__name__)

SQLiteClientFactory = Callable[[], Any]


class EmbeddedCapacityClient:
    """``CapacityClient`` over the storefront's local allocation tables.

    Takes a factory rather than a client so it always sees the same
    SQLite handle its caller would have used directly (tests monkeypatch
    the module-level ``get_sqlite_client`` and expect every code path to
    follow it).
    """

    def __init__(
        self,
        sqlite_client_factory: SQLiteClientFactory,
        *,
        bus: CapacityEventBus | None = None,
    ) -> None:
        self._db_factory = sqlite_client_factory
        self._bus = bus or CapacityEventBus()

    @property
    def db_path(self) -> str:
        return self._db_factory().db_path

    async def snapshot(self) -> list[dict[str, Any]]:
        return await self._db_factory().list_resources() or []

    async def probe(
        self, *, claim: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await self._db_factory().select_available_compute_vm(
            required_attributes=dict(claim) if claim else None,
        )

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        if ttl_seconds is not None:
            raise NotImplementedError(
                "TTL soft holds (two-phase reserve) are not implemented by "
                "the embedded adapter yet",
            )
        deal = dict(deal_ref or {})
        reserved = await self._db_factory().reserve_available_compute_vm(
            required_attributes=dict(claim) if claim else None,
            listing_id=deal.get("listing_id"),
            escrow_uid=deal.get("escrow_uid"),
        )
        if reserved:
            await self._emit(
                kind="reserved",
                resource_id=reserved.get("resource_id"),
                pool_id=reserved.get("pool_id"),
            )
        return reserved

    async def commit(
        self,
        *,
        resource_id: str,
        allocation_id: str | None = None,
        lease_end_utc: str,
        idempotency_ref: str | None = None,
    ) -> None:
        db = self._db_factory()
        ref = idempotency_ref or (allocation_id or resource_id)
        if allocation_id:
            await db.update_compute_allocation_state(
                allocation_id=allocation_id,
                state="leased",
            )
            await db.apply_resource_set_transition(
                resource_id=resource_id,
                event_type="lease_started_after_provisioning",
                idempotency_key=f"lease-attrs:{ref}:{resource_id}",
                set_attribute={"$.lease_end_utc": lease_end_utc},
            )
        else:
            # Legacy aggregate-state path for rows without an allocation.
            await db.apply_resource_set_transition(
                resource_id=resource_id,
                event_type="lease_started_after_provisioning",
                idempotency_key=f"lease:{ref}:{resource_id}",
                set_state="leased",
                set_attribute={"$.lease_end_utc": lease_end_utc},
            )
        await self._emit(kind="committed", resource_id=resource_id)

    async def release(
        self,
        *,
        allocation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        deal = dict(deal_ref or {})
        released = await self._db_factory().update_compute_allocation_state(
            allocation_id=allocation_id,
            escrow_uid=None if allocation_id else deal.get("escrow_uid"),
            state="released",
        )
        if released:
            await self._emit(
                kind="released",
                resource_id=released.get("resource_id"),
                pool_id=released.get("pool_id"),
            )
        return released

    async def truncate_lease(
        self,
        *,
        allocation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        """Shorten an active lease; teardown stays with the lease watchdog.

        The settlement lifecycle's early-termination signal lands here;
        until the site authority owns the job queue (work item II.4), the
        watchdog picks the new ``lease_end_utc`` up through the existing
        expiry path.
        """
        truncated = await self._db_factory().update_compute_allocation_state(
            allocation_id=allocation_id,
            state="leased",
            lease_end_utc=lease_end_utc,
        )
        if truncated and truncated.get("resource_id"):
            await self._db_factory().apply_resource_set_transition(
                resource_id=str(truncated["resource_id"]),
                event_type="lease_truncated",
                idempotency_key=f"truncate:{allocation_id}:{lease_end_utc}",
                set_attribute={"$.lease_end_utc": lease_end_utc},
            )
            await self._emit(
                kind="lease_truncated",
                resource_id=truncated.get("resource_id"),
                pool_id=truncated.get("pool_id"),
            )
        return truncated

    def subscribe(self, subscriber: CapacitySubscriber) -> Callable[[], None]:
        return self._bus.subscribe(subscriber)

    async def _emit(
        self,
        *,
        kind: str,
        resource_id: Any = None,
        pool_id: Any = None,
    ) -> None:
        await self._bus.emit(CapacityDelta(
            kind=kind,
            version=self._bus.next_version(),
            resource_id=str(resource_id) if resource_id else None,
            pool_id=str(pool_id) if pool_id else None,
        ))


# Delta kinds that shrink availability and can strand open derived
# listings whose GPU slice no longer fits.
_CONSUMING_DELTA_KINDS = frozenset({"reserved", "committed", "lease_truncated"})


def _make_stale_listing_subscriber(
    sqlite_client_factory: SQLiteClientFactory,
) -> CapacitySubscriber:
    """Close stale derived listings whenever capacity shrinks.

    This is the storefront's *reaction* to a capacity delta, not part of
    the reserving deal's flow — in the multi-storefront topology another
    seller's reservation invalidates our listings just the same, so the
    reconcile must hang off the event channel.
    """

    async def _close_stale_listings(delta: CapacityDelta) -> None:
        if delta.kind not in _CONSUMING_DELTA_KINDS:
            return
        # Late imports: publication machinery pulls registry/config
        # wiring this module shouldn't load just to snapshot capacity.
        from core_storefront.stage_log import stage_event
        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
        )

        closed_listing_ids = await close_stale_compute_listings_after_capacity_change(
            sqlite_client_factory().db_path,
        )
        if closed_listing_ids:
            stage_event(
                "provision", "stale_compute_listings_closed",
                resource_id=delta.resource_id,
                pool_id=delta.pool_id,
                capacity_version=delta.version,
                closed_listing_ids=closed_listing_ids,
            )

    return _close_stale_listings


class RemoteCapacityClient:
    """``CapacityClient`` over the site authority's HTTP capacity API.

    Verbs map one-to-one onto ``/api/v1/capacity/*`` (see the
    provisioning service's capacity controller — the payload shapes are
    the wire contract). Mutations do NOT emit into the local bus: the
    event-feed poller is the single source of deltas, so reactions fire
    identically whether this storefront or another one moved capacity.
    """

    def __init__(
        self,
        base_url: str,
        admin_key: str = "",
        *,
        bus: CapacityEventBus | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_key = admin_key
        self._bus = bus or CapacityEventBus()
        self._timeout = timeout
        self._transport = transport  # test seam (httpx.MockTransport / ASGI)

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        return {"X-Admin-Key": self._admin_key} if self._admin_key else {}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        async with self._http() as http:
            resp = await http.get(
                f"{self._base_url}{path}", params=params, headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        async with self._http() as http:
            return await http.post(
                f"{self._base_url}{path}", json=body, headers=self._headers(),
            )

    async def snapshot(self) -> list[dict[str, Any]]:
        data = await self._get("/api/v1/capacity/snapshot")
        return list(data.get("resources") or [])

    async def probe(
        self, *, claim: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        resp = await self._post(
            "/api/v1/capacity/probe", {"claim": dict(claim or {})},
        )
        resp.raise_for_status()
        return resp.json().get("match")

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "claim": dict(claim or {}),
            "deal_ref": dict(deal_ref or {}),
        }
        if ttl_seconds is not None:
            body["ttl_seconds"] = float(ttl_seconds)
        resp = await self._post("/api/v1/capacity/reservations", body)
        resp.raise_for_status()
        return resp.json().get("allocation")

    async def commit(
        self,
        *,
        resource_id: str,
        allocation_id: str | None = None,
        lease_end_utc: str,
        idempotency_ref: str | None = None,
    ) -> None:
        if not allocation_id:
            raise ValueError(
                "remote capacity commit requires the allocation_id the "
                "reserve returned (the site ledger has no aggregate path)",
            )
        resp = await self._post(
            f"/api/v1/capacity/allocations/{allocation_id}/commit",
            {
                "resource_id": resource_id,
                "lease_end_utc": str(lease_end_utc),
                "idempotency_ref": idempotency_ref,
            },
        )
        resp.raise_for_status()

    async def release(
        self,
        *,
        allocation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "allocation_id": allocation_id,
            "deal_ref": dict(deal_ref or {}),
        }
        if failure_reason is not None:
            body["failure_reason"] = failure_reason
        if failure_message is not None:
            body["failure_message"] = failure_message
        resp = await self._post("/api/v1/capacity/releases", body)
        resp.raise_for_status()
        return resp.json().get("allocation")

    async def truncate_lease(
        self,
        *,
        allocation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        resp = await self._post(
            f"/api/v1/capacity/allocations/{allocation_id}/truncate-lease",
            {"lease_end_utc": str(lease_end_utc)},
        )
        resp.raise_for_status()
        return resp.json().get("allocation")

    def subscribe(self, subscriber: CapacitySubscriber) -> Callable[[], None]:
        return self._bus.subscribe(subscriber)

    # Beyond the protocol: the feed the poller tails and the registry
    # mirror used by inventory seeding.

    async def list_allocations(
        self,
        *,
        state: str | None = None,
        escrow_uid: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if state is not None:
            params["state"] = state
        if escrow_uid is not None:
            params["escrow_uid"] = escrow_uid
        data = await self._get("/api/v1/capacity/allocations", params=params)
        return list(data.get("allocations") or [])

    async def events_after(
        self, after_version: int, *, limit: int = 500,
    ) -> tuple[list[dict[str, Any]], int]:
        data = await self._get(
            "/api/v1/capacity/events",
            params={"after": int(after_version), "limit": int(limit)},
        )
        return list(data.get("events") or []), int(data.get("latest_version") or 0)

    async def register_resource(
        self,
        resource_id: str,
        *,
        total_units: int,
        resource_subtype: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        async with self._http() as http:
            resp = await http.put(
                f"{self._base_url}/api/v1/capacity/resources/{resource_id}",
                json={
                    "total_units": int(total_units),
                    "resource_subtype": resource_subtype,
                    "attributes": dict(attributes or {}),
                    "enabled": enabled,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def emit_local(self, delta: CapacityDelta) -> None:
        """Feed a delta from the poller into local subscribers."""
        await self._bus.emit(delta)


def _capacity_settings() -> tuple[str, dict[str, str], str, str]:
    """Resolve (mode, sites{name→url}, admin_key, placement) from settings.

    Read at call time so tests that patch
    ``market_storefront.utils.config.settings`` are honored. Sites come
    from the ``[capacity.sites]`` table (name → authority URL); with no
    table, the single ``authority_url`` becomes the site named
    "default", falling back to the provisioning service — that process
    hosts the site authority.
    """
    from market_storefront.utils import config

    cap = getattr(config.settings, "capacity", None)
    mode = str(getattr(cap, "mode", "") or "").strip().lower()
    admin_key = str(getattr(config.settings, "admin_api_key", "") or "")
    placement = str(getattr(cap, "placement", "") or "fill_first").strip()

    sites: dict[str, str] = {}
    raw_sites = getattr(cap, "sites", None)
    if raw_sites:
        for name, url in dict(raw_sites).items():
            url = str(url or "").strip()
            if url:
                sites[str(name)] = url.rstrip("/")
    if not sites and mode == "site":
        url = str(getattr(cap, "authority_url", "") or "").strip()
        if not url:
            url = str(getattr(
                getattr(config.settings, "provisioning", None), "service_url", "",
            ) or "")
        if url:
            sites["default"] = url.rstrip("/")
    return mode, sites, admin_key, placement


def site_capacity_mode_active() -> bool:
    """True when the authoritative ledger is in remote site authorities."""
    mode, sites, _, _ = _capacity_settings()
    return mode == "site" and bool(sites)


async def site_held_by_resource(client: Any) -> dict[str, int]:
    """Per-resource held units derived from a site snapshot.

    The listing reconciler keeps totals and market attributes local (the
    aggregator view) but must take consumption from the authority's
    ledger in remote mode.
    """
    held: dict[str, int] = {}
    for row in await client.snapshot():
        resource_id = row.get("resource_id")
        available = row.get("available_units")
        if not resource_id or available is None:
            continue
        total = int(row.get("value") or 0)
        held[str(resource_id)] = max(total - int(available), 0)
    return held


def _local_held_by_resource(db_path: str) -> dict[str, int]:
    import sqlite3

    from domains.vms.listings.reconciler import held_gpu_counts

    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5,
        )
    except sqlite3.Error as exc:
        logger.warning(
            "[CAPACITY] Could not read local holds from %s: %s", db_path, exc,
        )
        return {}
    try:
        return held_gpu_counts(conn)
    except sqlite3.Error as exc:
        logger.warning(
            "[CAPACITY] Could not read local holds from %s: %s", db_path, exc,
        )
        return {}
    finally:
        conn.close()


async def combined_held_by_resource(
    client: Any, db_path: str,
) -> dict[str, int]:
    """Union of site-ledger and local holds, per resource.

    In remote mode deal reservations live in the site ledger, but
    operator reservations (the admin portfolio endpoints) still write
    the local tables. A hold is recorded in exactly one of the two, so
    the sum is the truth the listing reconciler needs. This is the
    fallback keying (resource_id only) for members the site snapshots
    don't cover — see ``member_availability_view`` for the primary,
    ``(site, resource_id)``-keyed answer.
    """
    held = await site_held_by_resource(client)
    for resource_id, units in _local_held_by_resource(db_path).items():
        held[resource_id] = held.get(resource_id, 0) + units
    return held


async def member_availability_view(
    client: Any, db_path: str,
) -> dict[tuple[str | None, str], int]:
    """Available units per pool member, from the aggregated snapshots.

    Keyed ``(site, resource_id)`` — the aggregator's member key. The
    home site (the first configured one) is also keyed ``(None, rid)``,
    matching members that carry no site tag, and has local operator
    holds subtracted (those still live in the storefront's own tables).
    """
    view: dict[tuple[str | None, str], int] = {}
    sites = remote_site_clients(client)
    if not sites:
        return view
    home_site = next(iter(sites))
    local_held = _local_held_by_resource(db_path)
    for row in await client.snapshot():
        resource_id = row.get("resource_id")
        available = row.get("available_units")
        if not resource_id or available is None:
            continue
        site = row.get("site") or home_site
        available = max(int(available), 0)
        if site == home_site:
            available = max(available - local_held.get(str(resource_id), 0), 0)
            view[(None, str(resource_id))] = available
        view[(str(site), str(resource_id))] = available
    return view


def _make_remote_listing_subscriber(
    sqlite_client_factory: SQLiteClientFactory,
    client: Any,
) -> CapacitySubscriber:
    """Reconcile derived listings against site-authority availability.

    Handles both directions — consuming deltas close stranded listings,
    "released" reopens ones that fit again (in embedded mode the reopen
    leg is driven by the admin fulfillment-event handlers instead).
    """

    async def _reconcile_listings(delta: CapacityDelta) -> None:
        from core_storefront.stage_log import stage_event
        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
            reopen_available_compute_listings_after_capacity_change,
        )

        db_path = sqlite_client_factory().db_path
        held = await combined_held_by_resource(client, db_path)
        availability = await member_availability_view(client, db_path)
        if delta.kind in _CONSUMING_DELTA_KINDS:
            closed = await close_stale_compute_listings_after_capacity_change(
                db_path,
                held_by_resource=held,
                member_availability=availability,
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
                db_path,
                held_by_resource=held,
                member_availability=availability,
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


# Remote mode keeps one aggregator per configuration: deltas come from
# the per-site pollers (not from whichever client instance happened to
# mutate), and the allocation→site routing cache must survive across
# build calls within the process.
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
        _make_remote_listing_subscriber(sqlite_client_factory, aggregate),
    )
    _aggregate_state["key"] = key
    _aggregate_state["client"] = aggregate
    return aggregate


def build_capacity_client(
    sqlite_client_factory: SQLiteClientFactory,
) -> Any:
    """Assemble the storefront's capacity client with default subscribers.

    Mode comes from ``[capacity]`` in settings: "" → embedded (local
    tables); "site" → an AggregateCapacityClient over the configured
    site authorities (one site is just the degenerate aggregation).
    """
    mode, sites, admin_key, placement_name = _capacity_settings()
    if mode == "site" and sites:
        return _aggregate_for(
            sqlite_client_factory, sites, admin_key, placement_name,
        )
    client = EmbeddedCapacityClient(sqlite_client_factory)
    client.subscribe(_make_stale_listing_subscriber(sqlite_client_factory))
    return client


def remote_site_clients(client: Any) -> dict[str, RemoteCapacityClient]:
    """The per-site remote clients behind a capacity client, by site name.

    Empty for embedded clients. Used by callers that need the
    beyond-the-protocol surface (allocation lists, event feeds) — those
    are per-site conversations, not aggregate ones.
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


def is_remote_capacity_client(client: Any) -> bool:
    """True when capacity writes land in site authorities, not local tables."""
    return bool(remote_site_clients(client))


async def sync_site_resources(
    sqlite_client_factory: SQLiteClientFactory | None = None,
) -> int:
    """Mirror local compute inventory into the site authority's ledger.

    Remote mode only (no-op otherwise). Local rows keep the market view
    (pricing, escrows, pools); the ledger gets the resource-domain core:
    unit totals and attributes. Deleted rows are mirrored as disabled so
    the authority stops matching them. Returns the number of rows
    synced.
    """
    mode, sites, admin_key, _ = _capacity_settings()
    if mode != "site" or not sites:
        return 0
    if sqlite_client_factory is None:
        from market_storefront.utils.sqlite_client import get_sqlite_client
        sqlite_client_factory = get_sqlite_client

    import json as _json

    # The storefront's local CSV inventory belongs to its home site —
    # the first configured one. Other sites register their own
    # inventory; the aggregator only ever *references* it.
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
            if k != "lease_end_utc"  # lease tail belongs to the ledger now
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

    Remote mode's delivery half: one poller per configured site, each
    positioning at its feed head, running one full listing reconcile to
    converge with anything missed while down, then polling for new
    versions and emitting each as a site-tagged ``CapacityDelta`` on the
    aggregate bus. A feed head that moves backwards (ledger reset)
    re-runs the full reconcile instead of replaying.
    """
    mode, sites, admin_key, _ = _capacity_settings()
    if mode != "site" or not sites:
        return

    from market_storefront.utils import config
    from market_storefront.utils.sqlite_client import get_sqlite_client

    interval = float(getattr(
        getattr(config.settings, "capacity", None), "poll_interval", 5,
    ) or 5)
    aggregate = build_capacity_client(lambda: get_sqlite_client())
    site_clients = remote_site_clients(aggregate)
    await asyncio.gather(*(
        _site_events_poller(aggregate, name, client, interval)
        for name, client in site_clients.items()
    ))


async def _site_events_poller(
    aggregate: Any,
    site_name: str,
    client: RemoteCapacityClient,
    interval: float,
) -> None:
    from market_storefront.utils.sqlite_client import get_sqlite_client

    async def _full_reconcile() -> None:
        from market_storefront.services.publication_service import (
            close_stale_compute_listings_after_capacity_change,
            reopen_available_compute_listings_after_capacity_change,
        )
        db_path = get_sqlite_client().db_path
        held = await combined_held_by_resource(aggregate, db_path)
        availability = await member_availability_view(aggregate, db_path)
        await close_stale_compute_listings_after_capacity_change(
            db_path,
            held_by_resource=held,
            member_availability=availability,
        )
        await reopen_available_compute_listings_after_capacity_change(
            db_path,
            held_by_resource=held,
            member_availability=availability,
        )

    last_applied: int | None = None
    logger.info(
        "[CAPACITY] Event poller started for site %r at %s (interval=%ss)",
        site_name, client.base_url, interval,
    )
    while True:
        try:
            if last_applied is None:
                _, last_applied = await client.events_after(0, limit=1)
                await _full_reconcile()
            events, latest = await client.events_after(last_applied)
            if latest < last_applied:
                logger.warning(
                    "[CAPACITY] Site %r feed head moved backwards (%d -> %d) "
                    "— ledger reset? Resyncing from snapshot.",
                    site_name, last_applied, latest,
                )
                last_applied = latest
                await _full_reconcile()
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
