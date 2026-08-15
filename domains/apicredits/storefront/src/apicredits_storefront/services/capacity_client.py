"""API-credit configuration and candidate hooks for kit-owned capacity."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core_storefront.aggregation import PLACEMENT_POLICIES, AggregateCapacityClient
from market_capacity_publication import (
    CapacityBinding,
    CapacityReconcileContext,
    CapacityRuntime,
    CapacitySite as KitCapacitySite,
)
from market_identity import Identity, TrustedIdentitySet

SQLiteClientFactory = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class CapacitySite:
    url: str
    expected_authorities: TrustedIdentitySet


def _capacity_settings() -> tuple[dict[str, CapacitySite], str]:
    from apicredits_storefront.utils import config
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
        sites[site_id] = CapacitySite(
            url,
            TrustedIdentitySet(
                identities=tuple(Identity.model_validate(value) for value in identities)
            ),
        )
    return sites, placement


_CONSUMING = frozenset({"reserved", "committed", "lease_truncated"})
_MIXED = frozenset({"capacity_changed"})


def _capacity_reconciler(sqlite_client_factory: SQLiteClientFactory):
    async def reconcile(context: CapacityReconcileContext) -> None:
        from apicredits_storefront.services.publication_service import (
            close_token_listings_after_capacity_change,
            reopen_token_listings_after_capacity_change,
        )
        delta = context.delta
        db = sqlite_client_factory()
        if delta is None or delta.kind in _CONSUMING or delta.kind in _MIXED:
            await close_token_listings_after_capacity_change(db, dict(context.availability))
        if delta is None or delta.kind == "released" or delta.kind in _MIXED:
            await reopen_token_listings_after_capacity_change(db, dict(context.availability))
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


def capacity_binding_from_offer(offer: dict[str, Any] | str) -> CapacityBinding:
    if isinstance(offer, str):
        import json
        offer = json.loads(offer)
    return CapacityBinding(
        str(offer.get("capacity_site_id") or ""),
        str(offer.get("offering_mode") or ""),
        str(offer.get("resource_id") or ""),
    )


async def capacity_events_poller_loop() -> None:
    from apicredits_storefront.utils import config
    from apicredits_storefront.utils.sqlite_client import get_sqlite_client
    interval = float(config.settings.get("capacity.poll_interval", 5) or 5)
    await build_capacity_runtime(get_sqlite_client).poll_events(interval_seconds=interval)
