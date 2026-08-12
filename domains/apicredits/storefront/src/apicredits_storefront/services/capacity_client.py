"""Quota-ledger capacity client wiring.

The authoritative quota ledger lives in the credits service (it mounts
the shared ``market_site`` ledger); the storefront is strictly a client.
The composed shape mirrors the VM storefront: per-site
``SiteCapacityClient``s behind one ``AggregateCapacityClient``, with
capacity deltas arriving by tailing each authority's versioned event
feed, and the storefront's reaction — credit-listing close/reopen —
subscribed on the aggregate bus.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Callable, Mapping

from core_storefront.aggregation import (
    PLACEMENT_POLICIES,
    AggregateCapacityClient,
    fill_first,
)
from core_storefront.capacity import CapacityDelta, CapacitySubscriber
from core_storefront.capacity_remote import site_events_poller
from market_site_client import SiteCapacityClient
from market_identity import Identity, TrustedIdentitySet

logger = logging.getLogger(__name__)

SQLiteClientFactory = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class CapacitySite:
    url: str
    expected_authorities: TrustedIdentitySet


def _capacity_settings() -> tuple[dict[str, CapacitySite], str]:
    """Resolve stable site IDs to URLs and ordered public authority sets."""
    from apicredits_storefront.utils import config

    placement = str(
        config.settings.get("capacity.placement", "") or "fill_first"
    ).strip()
    raw_sites = config.settings.get("capacity.sites")
    if not raw_sites or not hasattr(raw_sites, "items"):
        raise RuntimeError(
            "No quota authority configured: [capacity.sites] must map each "
            "stable site ID to url and expected_authorities.",
        )
    sites: dict[str, CapacitySite] = {}
    for raw_name, raw_site in dict(raw_sites).items():
        name = str(raw_name)
        if not name or not hasattr(raw_site, "items"):
            raise RuntimeError(f"capacity site {name!r} must be a table")
        values = dict(raw_site)
        url = str(values.get("url") or "").strip().rstrip("/")
        try:
            raw_authorities = dict(values.get("expected_authorities") or {})
            identities = raw_authorities.get("identities")
            if not isinstance(identities, (list, tuple)):
                raise TypeError("identities must be a list")
            expected_authorities = TrustedIdentitySet(
                identities=tuple(
                    Identity.model_validate(value) for value in identities
                ),
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"capacity site {name!r} has malformed expected_authorities"
            ) from exc
        if not url:
            raise RuntimeError(f"capacity site {name!r} requires url")
        sites[name] = CapacitySite(
            url=url,
            expected_authorities=expected_authorities,
        )
    return sites, placement


# Delta kinds that shrink availability and can strand open listings.
_CONSUMING_DELTA_KINDS = frozenset({"reserved", "committed", "lease_truncated"})


def _make_listing_reconcile_subscriber(
    sqlite_client_factory: SQLiteClientFactory,
    client: Any,
) -> CapacitySubscriber:
    """Close exhausted credit listings / reopen replenished ones on deltas."""

    async def _reconcile_listings(delta: CapacityDelta) -> None:
        from core_storefront.stage_log import stage_event

        from apicredits_storefront.services.publication_service import (
            close_token_listings_after_capacity_change,
            reopen_token_listings_after_capacity_change,
        )

        db = sqlite_client_factory()
        if delta.kind in _CONSUMING_DELTA_KINDS:
            closed = await close_token_listings_after_capacity_change(db, client)
            if closed:
                stage_event(
                    "provision",
                    "token_listings_closed",
                    resource_id=delta.resource_id,
                    site=delta.site,
                    capacity_version=delta.version,
                    closed_listing_ids=closed,
                )
        elif delta.kind == "released":
            reopened = await reopen_token_listings_after_capacity_change(db, client)
            if reopened:
                stage_event(
                    "provision",
                    "token_listings_reopened",
                    resource_id=delta.resource_id,
                    site=delta.site,
                    capacity_version=delta.version,
                    reopened_listing_ids=reopened,
                )

    return _reconcile_listings


_aggregate_state: dict[str, Any] = {"key": None, "client": None}


def _aggregate_for(
    sqlite_client_factory: SQLiteClientFactory,
    sites: Mapping[str, CapacitySite],
    signer: Any,
    placement_name: str,
) -> AggregateCapacityClient:
    key = (
        tuple(
            sorted(
                (
                    name,
                    site.url,
                    tuple(site.expected_authorities.identities),
                )
                for name, site in sites.items()
            )
        ),
        signer.identity,
        placement_name,
    )
    if _aggregate_state["key"] == key:
        return _aggregate_state["client"]
    placement = PLACEMENT_POLICIES.get(placement_name)
    if placement is None:
        logger.warning(
            "[CAPACITY] Unknown placement policy %r — using fill_first (known: %s)",
            placement_name,
            sorted(PLACEMENT_POLICIES),
        )
        placement = fill_first
    aggregate = AggregateCapacityClient(
        {
            name: SiteCapacityClient(
                site.url,
                signer=signer,
                expected_authorities=site.expected_authorities,
            )
            for name, site in sites.items()
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
    from apicredits_storefront import container

    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("marketplace signer must be resolved before capacity client")
    sites, placement_name = _capacity_settings()
    return _aggregate_for(sqlite_client_factory, sites, signer, placement_name)


def remote_site_clients(client: Any) -> dict[str, SiteCapacityClient]:
    """Per-site remote clients behind a capacity client, by site name."""
    if isinstance(client, AggregateCapacityClient):
        return {
            name: client.site(name)
            for name in client.site_names
            if isinstance(client.site(name), SiteCapacityClient)
        }
    if isinstance(client, SiteCapacityClient):
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
    from apicredits_storefront.utils import config
    from apicredits_storefront.utils.sqlite_client import get_sqlite_client

    interval = float(config.settings.get("capacity.poll_interval", 5) or 5)
    aggregate = build_capacity_client(lambda: get_sqlite_client())
    site_clients = remote_site_clients(aggregate)

    async def _full_reconcile() -> None:
        from apicredits_storefront.services.publication_service import (
            close_token_listings_after_capacity_change,
            reopen_token_listings_after_capacity_change,
        )

        db = get_sqlite_client()
        await close_token_listings_after_capacity_change(db, aggregate)
        await reopen_token_listings_after_capacity_change(db, aggregate)

    await asyncio.gather(
        *(
            site_events_poller(
                aggregate,
                name,
                client,
                interval,
                full_reconcile=_full_reconcile,
            )
            for name, client in site_clients.items()
        )
    )
