"""Settlement terms through the bare-metal storefront app and its typed client.

The real app, database, settlement composition, and Alkahest option builder run,
and publication is the administrator's step route composing its payload as the
production composition does. The site and the registry are the in-process
doubles the cycle tests use, standing where this codebase wraps those services.
The published listing is read back as a buyer fetches it.
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.publication import BareMetalPublicationCycle
from arkhai_bare_metal_storefront.publication_composition import (
    publication_payload_builder,
)
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_registry
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from held_loops import held_loop_controller
from test_http_system import ADMIN_SIGNER, SELLER_SIGNER, _app, _runtime
from test_publication_cycle import (
    RECIPIENT_CONDITION,
    REGISTRY_URL,
    SELLER_WALLET,
    RecordingRegistries,
    Site,
    projections_over,
    alkahest_publication,
    member,
    pool,
)

pytestmark = pytest.mark.asyncio

SITE = "site-a"


class _Sites:
    def __init__(self, site: Site) -> None:
        self._site = site

    def site(self, site_id: str) -> Site:
        assert site_id == SITE
        return self._site


async def test_a_buyer_reads_the_release_condition_an_alkahest_listing_advertises(
    tmp_path, monkeypatch
):
    composition, clauses = alkahest_publication(tmp_path, monkeypatch, SELLER_SIGNER)
    site = Site(pool("pool-1", member("r1", "pool-1")))

    def cycle(runtime):
        return BareMetalPublicationCycle(
            sqlite_client=runtime.db,
            registry=build_bare_metal_storefront_registry(
                domain=get_market_domain_contract()
            ),
            site_projections=runtime.site_projections,
            site_ids=[SITE],
            registry_client_factory=RecordingRegistries(),
            registry_urls=(REGISTRY_URL,),
            storefront_url=runtime.storefront_url,
            seller_principal=runtime.seller_principal,
            build_payload=publication_payload_builder(runtime),
            publication_clauses=runtime.publication_clauses,
            default_max_duration_seconds=runtime.default_max_duration_seconds,
        )

    runtime = dataclasses.replace(
        _runtime(str(tmp_path / "storefront.db")),
        seller_evm_address=SELLER_WALLET,
        settlement_composition=composition,
        publication_clauses=clauses,
        default_max_duration_seconds=3600,
        # Servicing sweeps on an interval no test waits out.
        settlement_servicing_interval_seconds=3600,
        site_bindings=(
            BareMetalSiteBinding(
                site_id=SITE,
                service_peer=f"{SITE}-peer",
                authority_url="http://site-a",
            ),
        ),
        capacity_client=_Sites(site),
        # The storefront's held projection of the site, which startup loads.
        site_projections=projections_over({SITE: site}),
        loop_controller_factory=held_loop_controller,
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
            report = await admin.admin_run_lifecycle_cycle("publication")
            (published,) = [
                item for item in report["actions"] if item["action"] == "publish"
            ]
            listing = await public.get_listing(str(published["listing_id"]))

    assert [escrow["chain_name"] for escrow in listing.extra["accepted_escrows"]] == [
        "anvil"
    ]
    assert listing.extra["demands"] == [RECIPIENT_CONDITION]
