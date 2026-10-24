"""Reconciliation reads every listing, and publishes none a guard refuses, against the storefront's real persistence."""

from __future__ import annotations

from dataclasses import replace

import pytest
from core_storefront.sqlite_client import SQLiteClient
from market_resource_pools import ResolvedPool
from market_resource_pools_contracts.backing import BACKED

from arkhai_api_selling.publication import (
    LISTING_PAGE,
    PublicationRefused,
    QuotaPublication,
    RegistryPublication,
    all_listings,
)
from arkhai_api_selling.quota_listing import QuotaPool, prepare_listing_binding
from tests.bundles import CLAIMANT, DOMAIN, EXAMPLE

COUNT = LISTING_PAGE + 50
SITE = "quota"


class _Site:
    """The quota site's pool projection: one pool holding ``quota-a``."""

    def __init__(self, *, advertised: tuple[str, ...] = ("example",)) -> None:
        self._advertised = advertised

    def site_client(self, site_id: str) -> "_Site":
        assert site_id == SITE
        return self

    async def resource_pool_projection(self) -> dict:
        return {
            "resource_pools": [
                {
                    "pool_id": "default",
                    "resources": [{"physical_resource_id": "quota-a"}],
                    "pool_metadata": {
                        "enabled": True,
                        "policy_tags": {
                            "deliverable_modes": ["example"],
                            "advertisable_modes": list(self._advertised),
                            "capacity_backing": "backed",
                        },
                    },
                }
            ]
        }


class _Capacity:
    def __init__(self, site: _Site) -> None:
        self._site = site

    def runtime(self, _factory) -> _Site:
        return self._site


def _publication(site: _Site | None = None) -> QuotaPublication:
    return QuotaPublication(
        EXAMPLE,
        capacity=_Capacity(site or _Site()),
        registry=lambda: RegistryPublication(
            enabled=False,
            registry_urls=(),
            storefront_url="https://seller.example",
            client_factory=lambda: None,
        ),
    )


async def _storefront(tmp_path) -> SQLiteClient:
    """More open listings over one quota resource than one page holds."""
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    resource = {"product": "alpha", "quota": "quota-a", "offering_mode": "example"}
    pool = QuotaPool("default", ResolvedPool(BACKED, frozenset({"example"}), True))
    for index in range(COUNT):
        listing_id = f"L-{index:03d}"
        await client.upsert_listing_with_binding(
            binding=prepare_listing_binding(
                EXAMPLE,
                listing_id=listing_id,
                site_id=SITE,
                listing_resource=resource,
                pool=pool,
                domain=DOMAIN,
            ),
            status="open",
            # Every listing shares one instant, so pages split ties.
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            listing_resource=resource,
            fulfillment_resource=None,
            max_duration_seconds=None,
            storefront_url="https://seller.example",
            seller_principal=CLAIMANT,
        )
    return client


async def _statuses(client: SQLiteClient) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in await client.list_listings(limit=COUNT + 1):
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


class _ClosingBetweenPages:
    """The store, closing every listing on the page it just served before the next read."""

    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def list_listings(self, **query):
        page = await self._client.list_listings(**query)
        for row in page:
            await self._client.update_listing(
                listing_id=row["listing_id"], status="closed", closed_by="reconciliation"
            )
        return page


async def test_every_listing_is_read_once_while_statuses_change_between_pages(tmp_path):
    client = await _storefront(tmp_path)

    rows = await all_listings(_ClosingBetweenPages(client), status="open")

    ids = [row["listing_id"] for row in rows]
    assert len(ids) == len(set(ids)) == COUNT


async def test_exhausted_quota_closes_every_open_listing_and_replenished_quota_reopens_them(
    tmp_path,
):
    client = await _storefront(tmp_path)
    publication = _publication()

    closed = await publication.close_after_capacity_change(client, {(SITE, "quota-a"): 0})

    assert len(closed) == COUNT
    assert await _statuses(client) == {"closed": COUNT}

    reopened = await publication.reopen_after_capacity_change(client, {(SITE, "quota-a"): 5})

    assert len(reopened) == COUNT
    assert await _statuses(client) == {"open": COUNT}


async def test_a_source_mismatch_closes_every_open_listing(tmp_path):
    client = await _storefront(tmp_path)

    closed = await _publication(_Site(advertised=())).close_on_source_mismatch(client)

    assert len(closed) == COUNT
    assert await _statuses(client) == {"closed": COUNT}


def _guarded(site: _Site | None = None, *, blocked: str = "L-000") -> QuotaPublication:
    """Publication under a bundle whose guard refuses one listing's resource."""
    guarded = replace(
        EXAMPLE, publication_guards=(lambda resource: "blocked" if resource.get("product") == blocked else None,)
    )
    return QuotaPublication(
        guarded,
        capacity=_Capacity(site or _Site()),
        registry=lambda: RegistryPublication(
            enabled=False,
            registry_urls=(),
            storefront_url="https://seller.example",
            client_factory=lambda: None,
        ),
    )


async def _with_blocked_product(client: SQLiteClient) -> None:
    await client.update_listing(
        listing_id="L-000",
        listing_resource={"product": "L-000", "quota": "quota-a", "offering_mode": "example"},
    )


async def test_publishing_a_listing_its_guard_refuses_is_refused(tmp_path):
    client = await _storefront(tmp_path)
    await _with_blocked_product(client)

    with pytest.raises(PublicationRefused, match="^blocked$"):
        await _guarded().publish(client, await client.load_listing(listing_id="L-000"))
    assert _guarded().refusal(await client.load_listing(listing_id="L-000")) == "blocked"
    assert _guarded().refusal(await client.load_listing(listing_id="L-001")) is None


async def test_reconciliation_reopens_every_listing_but_one_its_guard_refuses(tmp_path):
    client = await _storefront(tmp_path)
    await _with_blocked_product(client)
    await _publication().close_after_capacity_change(client, {(SITE, "quota-a"): 0})

    reopened = await _guarded().reopen_after_capacity_change(client, {(SITE, "quota-a"): 5})

    assert len(reopened) == COUNT - 1
    assert "L-000" not in reopened
    assert (await client.load_listing(listing_id="L-000"))["status"] == "closed"
