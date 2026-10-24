"""Reconciliation reads every listing, against the storefront's real persistence."""

from __future__ import annotations

from core_storefront.sqlite_client import SQLiteClient
from market_resource_pools import ResolvedPool
from market_resource_pools_contracts.backing import BACKED

from arkhai_api_selling.publication import LISTING_PAGE, QuotaPublication, RegistryPublication
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
            created_at=f"2026-01-01T00:00:00.{index:06d}",
            updated_at=f"2026-01-01T00:00:00.{index:06d}",
            listing_resource=resource,
            fulfillment_resource=None,
            max_duration_seconds=None,
            storefront_url="https://seller.example",
            seller_principal=CLAIMANT,
        )
    return client


async def _statuses(client: SQLiteClient) -> dict[str, int]:
    counts: dict[str, int] = {}
    for offset in range(0, COUNT, LISTING_PAGE):
        for row in await client.list_listings(limit=LISTING_PAGE, offset=offset):
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


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
