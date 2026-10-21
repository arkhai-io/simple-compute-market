"""API-credit configuration and candidate hooks for kit-owned capacity."""
from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Callable

from core_storefront.aggregation import PLACEMENT_POLICIES, AggregateCapacityClient
from market_capacity_publication import (
    run_capacity_event_pollers,
    CapacityReconcileContext,
    CapacityRuntime,
    CapacitySite as KitCapacitySite,
)
from market_identity import Identity, TrustedIdentitySet
from market_storefront_kit import StorefrontLoopController

from apicredits_storefront.utils import config

SQLiteClientFactory = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class CapacitySite:
    url: str
    expected_authorities: TrustedIdentitySet


def _capacity_settings() -> tuple[dict[str, CapacitySite], str]:
    """Each configured site's URL and trusted authorities, and the placement.

    A site that cannot be read is refused by its key, naming no configured
    value, so the storefront's startup refusal reports it.
    """
    placement = str(config.settings.get("capacity.placement", "") or "fill_first").strip()
    raw_sites = config.settings.get("capacity.sites")
    if not raw_sites or not hasattr(raw_sites, "items"):
        raise RuntimeError("[capacity.sites] must define explicit trusted site IDs")
    sites: dict[str, CapacitySite] = {}
    for raw_name, raw_site in dict(raw_sites).items():
        site_id = str(raw_name).strip()
        values = dict(raw_site) if hasattr(raw_site, "items") else {}
        url = str(values.get("url") or "").strip().rstrip("/")
        raw_authorities = dict(values.get("expected_authorities") or {})
        identities = raw_authorities.get("identities")
        if not site_id or not url or not isinstance(identities, (list, tuple)):
            raise RuntimeError(f"capacity site {site_id!r} is incomplete")
        try:
            trusted = TrustedIdentitySet(
                identities=tuple(Identity.model_validate(value) for value in identities)
            )
        except (TypeError, ValueError):
            trusted = None
        if trusted is None:
            # Raised outside the handler: a validation error keeps the value it
            # refused.
            raise RuntimeError(
                f"[capacity.sites.{site_id}.expected_authorities] must list one or two "
                "valid principals"
            )
        sites[site_id] = CapacitySite(url, trusted)
    return sites, placement


def configured_sites() -> dict[str, CapacitySite]:
    """Each configured capacity site by its ID, in configuration order."""
    return _capacity_settings()[0]


def configured_site_ids() -> tuple[str, ...]:
    """The configured capacity sites' IDs, in configuration order."""
    return tuple(configured_sites())


def capacity_poll_interval() -> float:
    """Seconds between each site's capacity-event poller cycles:
    `[capacity].poll_interval`, five unless stated, and refused by its key
    unless it is a positive, finite number of seconds, so the kit's pollers
    never wait on zero, a negative, NaN, or infinity."""
    return config.seconds_setting("capacity.poll_interval", 5)


_CONSUMING = frozenset({"reserved", "committed", "lease_truncated"})
_MIXED = frozenset({"capacity_changed"})


def _capacity_reconciler(sqlite_client_factory: SQLiteClientFactory):
    async def reconcile(context: CapacityReconcileContext) -> None:
        from apicredits_storefront.services.publication_service import (
            close_token_listings_after_capacity_change,
            close_token_listings_on_source_mismatch,
            converge_registries,
            reopen_token_listings_after_capacity_change,
        )
        delta = context.delta
        db = sqlite_client_factory()
        # Source reconciliation runs on every pass, whatever the event: moving
        # a resource to another pool changes no capacity and is fed as a
        # release, which the availability close never sees.
        await close_token_listings_on_source_mismatch(db)
        if delta is None or delta.kind in _CONSUMING or delta.kind in _MIXED:
            await close_token_listings_after_capacity_change(db, dict(context.availability))
        if delta is None or delta.kind == "released" or delta.kind in _MIXED:
            await reopen_token_listings_after_capacity_change(db, dict(context.availability))
        await converge_registries(db)
    return reconcile


_runtime_state: dict[str, Any] = {"key": None, "runtime": None}


def build_capacity_runtime(sqlite_client_factory: SQLiteClientFactory) -> CapacityRuntime:
    from apicredits_storefront import container
    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("marketplace signer must be resolved before capacity runtime")
    sites, placement_name = _capacity_settings()
    placement = PLACEMENT_POLICIES.get(placement_name)
    if placement is None:
        raise RuntimeError(f"unknown capacity placement policy {placement_name!r}")
    key = (tuple((name, site.url, repr(site.expected_authorities)) for name, site in sites.items()), repr(signer.identity), placement_name, str(getattr(sqlite_client_factory(), "db_path", "")))
    if _runtime_state["key"] != key:
        _runtime_state["key"] = key
        _runtime_state["runtime"] = CapacityRuntime(
            sites=tuple(KitCapacitySite(name, site.url, site.expected_authorities) for name, site in sites.items()),
            signer=signer,
            placement=placement,
            reconcile=_capacity_reconciler(sqlite_client_factory),
        )
    return _runtime_state["runtime"]


def build_capacity_client(sqlite_client_factory: SQLiteClientFactory) -> AggregateCapacityClient:
    return build_capacity_runtime(sqlite_client_factory).client()


async def capacity_events_poller_loop(
    loops: StorefrontLoopController, *, runtime: CapacityRuntime | None = None
) -> None:
    """Tail every quota authority's capacity-event feed under the loop controller.

    The aggregate name is what the advance route addresses; each site's poller
    gates under its own name, declared as the aggregate loop's child since the
    kit owns the fan-out, and each site's timer cycles record their outcomes
    under that name. ``runtime`` is the capacity runtime the pollers drain, the
    one the storefront's configuration composes unless given.
    """
    # Imported when the loop starts: the steps module imports this one for the
    # capacity runtime its step drains.
    from apicredits_storefront.lifecycle_steps import (
        CAPACITY_EVENTS_POLLER,
        capacity_site_cycle_recorder,
        capacity_site_gate,
    )
    from apicredits_storefront.utils.sqlite_client import get_sqlite_client
    interval = capacity_poll_interval()
    if runtime is None:
        runtime = build_capacity_runtime(get_sqlite_client)
    await run_capacity_event_pollers(
        functools.partial(runtime.poll_events, interval_seconds=interval),
        gate=loops.loop_gate(CAPACITY_EVENTS_POLLER),
        site_gate=functools.partial(capacity_site_gate, loops),
        wait=loops.idle,
        record_site_cycle=functools.partial(capacity_site_cycle_recorder, loops),
    )
