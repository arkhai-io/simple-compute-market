"""Asking rates through the bare-metal storefront app and its typed clients.

The real app, database, and composition run; publication is the administrator's
step route. Each site and the registry are the in-process doubles the cycle
tests use, standing where this codebase wraps those services. A declared rate
and a storefront override are each read back as the published listing a buyer
fetches, and each refreshes the same listing in place.
"""

from __future__ import annotations

import contextlib
import dataclasses

import httpx
import pytest
from market_identity import TrustedIdentitySet
from market_pool_overrides import PoolOverrideClient
from storefront_client import StorefrontClient

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.publication import BareMetalPublicationCycle
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_registry
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from test_http_system import ADMIN_SIGNER, SELLER_SIGNER, _app, _runtime
from test_publication_cycle import (
    REGISTRY_URL,
    RecordingRegistries,
    Site,
    Terms,
    _priced,
    _rate,
)

pytestmark = pytest.mark.asyncio

SITE = "site-a"


class _Sites:
    def __init__(self, site: Site) -> None:
        self._site = site

    def site(self, site_id: str) -> Site:
        assert site_id == SITE
        return self._site


@contextlib.asynccontextmanager
async def _storefront(tmp_path, site: Site):
    registries = RecordingRegistries()

    def cycle(runtime):
        return BareMetalPublicationCycle(
            sqlite_client=runtime.db,
            registry=build_bare_metal_storefront_registry(domain=get_market_domain_contract()),
            site_clients={SITE: site},
            registry_client_factory=registries,
            registry_url=REGISTRY_URL,
            storefront_url=runtime.storefront_url,
            seller_principal=runtime.seller_principal,
            build_payload=Terms(),
        )

    runtime = dataclasses.replace(
        _runtime(str(tmp_path / "storefront.db")),
        site_bindings=(
            BareMetalSiteBinding(
                site_id=SITE,
                authority_principal=SELLER_SIGNER.identity,
                authority_url="http://site-a",
            ),
        ),
        capacity_client=_Sites(site),
        publication_cycle_factory=cycle,
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=app),
        ) as admin, StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as public:
            yield admin, public


def _listing_id(report: dict) -> str:
    (published,) = [item for item in report["actions"] if item["action"] == "publish"]
    return str(published["listing_id"])


async def test_a_declared_rate_and_an_override_reach_the_listing_a_buyer_reads(tmp_path):
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site) as (admin, public):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        declared = await public.get_listing(listing_id)

        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "asking_rates": [_rate("9.00")]}
        )
        await admin.admin_run_lifecycle_cycle("publication")
        overridden = await public.get_listing(listing_id)

        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "asking_rates": []}
        )
        await admin.admin_run_lifecycle_cycle("publication")
        withheld = await public.get_listing(listing_id)

    assert declared.listing_resource["asking_rate"] == {
        "amount": "12.50", "asset": "usd", "period": "hour",
    }
    assert overridden.listing_resource["asking_rate"]["amount"] == "9.00"
    assert "asking_rate" not in withheld.listing_resource
    assert withheld.status == "open"
