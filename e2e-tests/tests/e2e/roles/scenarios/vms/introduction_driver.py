"""VM's part of the introduction scenario: what the shared stages ask of it.

The shared stages in ``helpers/introduction_stages.py`` hold the scenario's
control flow and every assertion that is not VM's. This driver holds VM's: the
executor host and capacity behind the backed pool, the unbacked pool and the
override offering it by introduction, discovery through the VM registry's own
filter specification, and the VM buyer's root-level CLI verbs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_pool_overrides import SyncPoolOverrideClient
from market_resource_pools_contracts import PoolCreate, PoolUpdate
from registry_client.query import compile_resource_query

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.compute_deal import (
    advance_storefront,
    assert_storefront_loops_held,
)
from tests.e2e.roles.helpers.introduction_stages import (
    BACKED_RATE,
    CONTACT_MECHANISM,
    UNBACKED_RATE,
    SeededSupply,
)
from tests.e2e.roles.scenarios.vms.conftest import capacity_site_id
from tests.e2e.roles.scenarios.vms.host_registry import (
    declare_e2e_capacity,
    provision_e2e_executor,
    refresh_storefront_projections,
)

VM = "vm"
PUBLICATION = "publication"
REGION = "us-west"
GPU_MODEL = "H100"
SHAPE = {"gpu": {"count": 1, "model": GPU_MODEL}}
#: Bob's contact for the lane's one site, a development value on a reserved
#: domain (``domains/vms/storefront/storefront.bob.toml``).
SELLER_CONTACT_EMAIL = "bob-sales@seller.invalid"


def _rate(amount: str) -> dict[str, Any]:
    return {"shape": SHAPE, "amount": amount, "asset": "usd", "period": "hour"}


def _with_rate(pool: Any, amount: str) -> Any:
    tags = dict(pool.policy_tags or {})
    tags["asking_rates"] = {VM: [_rate(amount)]}
    return PoolUpdate(policy_tags=tags)


def _pool_listing(storefront_admin_client, pool_id: str, cycle: dict[str, Any]) -> str:
    """The one open listing published from ``pool_id``.

    A cycle's publish action names its derivation key rather than its pool, so
    the listing is found by the pool its resource records; the cycle is reported
    when it is not there, so a failure says what publication did instead.
    """
    page = storefront_admin_client.list_listings(status="open", limit=200)
    found = []
    for listing in page.listings:
        resource = listing.listing_resource
        if isinstance(resource, str):
            resource = json.loads(resource)
        if (resource or {}).get("pool_id") == pool_id:
            found.append(str(listing.listing_id))
    assert len(found) == 1, f"listings for {pool_id}: {found}; cycle: {cycle}"
    return found[0]


@dataclass
class VmIntroductionDriver:
    """VM's ``IntroductionDriver``, over the VM lane's clients."""

    buyer: BuyerCli
    delivered: Path
    mailpit_url: str
    storefront_admin_client: Any
    registry_client: Any
    provisioning_client: Any
    resource_pool_client: Any
    site_capacity_admin_client: Any
    seller_contact_email: str = SELLER_CONTACT_EMAIL

    def assert_loops_held(self) -> None:
        assert_storefront_loops_held(self.storefront_admin_client)

    def retention_disclosure(self) -> dict[str, Any] | None:
        return self.storefront_admin_client.get_health().disclosures.get(
            "introduction_retention"
        )

    def seed_supply(self, run: str) -> SeededSupply:
        backed_pool = f"vm-intro-backed-{run}"
        unbacked_pool = f"vm-intro-unbacked-{run}"
        # Backed supply: a pool, an executor host, and its capacity declaration.
        provision_e2e_executor(
            self.provisioning_client,
            self.site_capacity_admin_client,
            host=f"{backed_pool}-host",
            resource_id=f"{backed_pool}-res",
            attributes={"gpu_model": GPU_MODEL, "region": REGION},
            pool_id=backed_pool,
            sellable_units=1,
            listing_mode="fungible",
            listing_shapes={VM: [SHAPE]},
            region=REGION,
        )
        backed = self.resource_pool_client.get_pool(backed_pool)
        self.resource_pool_client.patch_pool(backed_pool, _with_rate(backed, BACKED_RATE))
        # Unbacked supply: declared and advertised, never delivered, so no
        # executor stands behind it.
        self.resource_pool_client.create_pool(
            PoolCreate(
                id=unbacked_pool,
                label=unbacked_pool,
                provider="vm.ansible",
                policy_tags={
                    "listing_mode": "fungible",
                    "deliverable_modes": [],
                    "advertisable_modes": [VM],
                    "capacity_backing": "unbacked",
                    "region": REGION,
                    "listing_shapes": {VM: [SHAPE]},
                    "asking_rates": {VM: [_rate(UNBACKED_RATE)]},
                },
                provider_config=dict(backed.provider_config or {}),
            )
        )
        declare_e2e_capacity(
            self.site_capacity_admin_client,
            resource_id=f"{unbacked_pool}-res",
            host_id=f"{unbacked_pool}-declared",
            attributes={"gpu_model": GPU_MODEL, "region": REGION},
            pool_id=unbacked_pool,
            sellable_units=1,
        )
        # The storefront's pollers are held, so it pulls the site's new pools
        # now; an override is checked against the pools it has pulled.
        refresh_storefront_projections(self.storefront_admin_client)
        # Only the unbacked pool offers introduction; the lane's configured
        # clauses still govern every other listing.
        SyncPoolOverrideClient(self.storefront_admin_client).put_pool_override(
            {
                "site_id": capacity_site_id(),
                "pool_id": unbacked_pool,
                "offering_mode": VM,
                "settlements": [
                    {
                        "mechanism": CONTACT_MECHANISM,
                        "asset": "introduction",
                        "mechanism_input": {"profile": "default"},
                    }
                ],
            }
        )

        cycle = advance_storefront(self.storefront_admin_client, PUBLICATION)

        # No rateless listing of the scenario's own: the lane's default listings
        # publish no rate, and the stage holds every listing a rate bound
        # returns to publishing one.
        return SeededSupply(
            backed_listing=_pool_listing(self.storefront_admin_client, backed_pool, cycle),
            unbacked_listing=_pool_listing(
                self.storefront_admin_client, unbacked_pool, cycle
            ),
        )

    def discover(self, query: str) -> set[str]:
        """Listings a buyer finds, compiled against the registry's own specification."""
        compiled = compile_resource_query(
            query,
            filter_spec=self.registry_client.get_filter_spec(),
            registry_url=str(settings.REGISTRY.API_URL),
        )
        response = self.registry_client.list_listings(
            offering_mode=VM, etag=compiled.etag, **compiled.as_params()
        )
        return {listing.id for listing in response.listings}

    def listing(self, listing_id: str) -> Any:
        return self.registry_client.get_listing(listing_id)

    def request_introduction_args(self, listing_id: str, option_id: str) -> list[str]:
        return ["request-introduction", listing_id, "--option-id", option_id]

    def introduce_args(self, run_id: str, contact_email: str) -> list[str]:
        return [
            "settlement", "contact", "introduce",
            "--run-id", run_id,
            "--contact", f"email={contact_email}",
        ]
