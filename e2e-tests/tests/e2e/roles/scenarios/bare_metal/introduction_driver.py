"""Bare metal's part of the introduction scenario: what the shared stages ask of it.

The shared stages in ``helpers/introduction_stages.py`` hold the scenario's
control flow and every assertion that is not bare metal's. This driver holds
bare metal's: whole machines declared at the site -- a backed pool's machine
naming its host, an unbacked pool's machine naming none, and a backed machine
whose pool states no rate -- the override offering the unbacked pool by
introduction, discovery through the production ``market bare-metal list``, and
the bare-metal buyer's CLI verbs, which sit under ``market bare-metal`` and
read their own ``[bare_metal]`` section from the buyer's configuration.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arkhai_bare_metal import derive_bare_metal_shape
from market_pool_overrides import SyncPoolOverrideClient
from market_resource_pools_contracts import PoolCreate

from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.compute_deal import assert_storefront_loops_held
from tests.e2e.roles.helpers.introduction_stages import (
    BACKED_RATE,
    CONTACT_MECHANISM,
    UNBACKED_RATE,
    SeededSupply,
)

BARE_METAL = "bare_metal"
PUBLICATION = "publication"
SITE_PROJECTIONS = "site-projections"
REGION = "us-west"
GPU_MODEL = "H200"
#: One whole machine: the unit a bare-metal listing sells and the hardware in it.
WHOLE_HOST_CAPACITY = {"units": 1, "gpu_count": 8, "ram_gb": 2048}
#: The shape a whole-machine declaration reads as, which an asking rate is keyed by.
MACHINE_SHAPE = derive_bare_metal_shape(WHOLE_HOST_CAPACITY, {"gpu_model": GPU_MODEL})


def _rate(amount: str) -> dict[str, Any]:
    return {"shape": MACHINE_SHAPE, "amount": amount, "asset": "usd", "period": "hour"}


def _declarations(*, backed: bool, rate: str | None) -> dict[str, Any]:
    """A pool's declarations: a backed pool delivers bare metal, an unbacked one
    delivers nothing and only advertises it."""
    declarations: dict[str, Any] = {
        "deliverable_modes": [BARE_METAL] if backed else [],
        "advertisable_modes": [BARE_METAL],
        "capacity_backing": "backed" if backed else "unbacked",
        "region": REGION,
    }
    if rate is not None:
        declarations["asking_rates"] = {BARE_METAL: [_rate(rate)]}
    return declarations


def _machine(resource_id: str, *, backed: bool) -> dict[str, Any]:
    """A whole machine's attributes. A backed machine states what delivering it
    needs -- its physical host and access methods; an unbacked one only opts
    into bare-metal publication, since nothing stands behind delivering it."""
    publication: dict[str, Any] = {"enabled": True}
    attributes: dict[str, Any] = {
        "gpu_model": GPU_MODEL,
        "allocation_mode": "exclusive",
        "bare_metal_publication": publication,
    }
    if backed:
        attributes["physical_host_id"] = f"physical-{resource_id}"
        publication["access_methods"] = ["ssh"]
    return attributes


def _listing_ids(output: str) -> set[str]:
    """The listing IDs ``market bare-metal list`` printed."""
    for line in reversed(output.strip().splitlines()):
        if line.startswith("{"):
            listings = json.loads(line).get("listings") or []
            return {str(item.get("listing_id") or item.get("id")) for item in listings}
    raise AssertionError(f"no listing page in output: {output[-2000:]}")


@dataclass
class BareMetalIntroductionDriver:
    """Bare metal's ``IntroductionDriver``, over the bare-metal lane's clients."""

    buyer: BuyerCli
    delivered: Path
    mailpit_url: str
    seller_contact_email: str
    site_id: str
    storefront_admin: Any
    storefront_public: Any
    site_operator: Any
    site_capacity: Any
    registry: Any

    def assert_loops_held(self) -> None:
        assert_storefront_loops_held(self.storefront_admin)

    def retention_disclosure(self) -> dict[str, Any] | None:
        return self.storefront_public.get_health().disclosures.get("introduction_retention")

    def seed_supply(self, run: str) -> SeededSupply:
        pools = {
            "backed": (f"bm-intro-backed-{run}", True, BACKED_RATE),
            "unbacked": (f"bm-intro-unbacked-{run}", False, UNBACKED_RATE),
            "rateless": (f"bm-intro-rateless-{run}", True, None),
        }
        resources = {}
        for name, (pool_id, backed, rate) in pools.items():
            self.site_operator.create_pool(
                PoolCreate(
                    id=pool_id,
                    label=pool_id,
                    # The bare-metal provider takes no provider configuration, as
                    # the lane's other bare-metal pools state; the unbacked pool
                    # names it too, although it delivers nothing.
                    provider="bare_metal.ansible",
                    policy_tags=_declarations(backed=backed, rate=rate),
                    provider_config={},
                )
            )
            resources[name] = (f"{pool_id}-machine", pool_id, backed)

        async def declare() -> None:
            for resource_id, pool_id, backed in resources.values():
                await self.site_capacity.register_resource(
                    resource_id,
                    pool_id=pool_id,
                    # The unbacked machine names no host: nothing connects to it.
                    **({"host_id": f"host-{resource_id}"} if backed else {}),
                    capacity=dict(WHOLE_HOST_CAPACITY),
                    attributes=_machine(resource_id, backed=backed),
                )

        asyncio.run(declare())
        # The held poller does not see the new pools; one step of it does, and
        # an override is checked against the pools the storefront holds.
        self.storefront_admin.admin_run_lifecycle_cycle(SITE_PROJECTIONS)
        SyncPoolOverrideClient(self.storefront_admin).put_pool_override(
            {
                "site_id": self.site_id,
                "pool_id": pools["unbacked"][0],
                "offering_mode": BARE_METAL,
                "settlements": [
                    {
                        "mechanism": CONTACT_MECHANISM,
                        "asset": "introduction",
                        "mechanism_input": {"profile": "default"},
                    }
                ],
            }
        )

        report = self.storefront_admin.admin_run_lifecycle_cycle(PUBLICATION)

        published = {
            item["source"]["physical_resource_id"]: str(item["listing_id"])
            for item in report["actions"]
            if item["action"] == "publish"
        }
        machines = {name: resource[0] for name, resource in resources.items()}
        assert set(machines.values()) <= set(published), report
        return SeededSupply(
            backed_listing=published[machines["backed"]],
            unbacked_listing=published[machines["unbacked"]],
            rateless_listings=(published[machines["rateless"]],),
        )

    def _config(self) -> list[str]:
        return ["--config", str(self.buyer.config_path)]

    def discover(self, query: str) -> set[str]:
        """Listings the production ``market bare-metal list`` returns."""
        listed = self.buyer.run(
            ["bare-metal", "list", "--limit", "200", "--resource", query, *self._config()],
            timeout=60.0,
        )
        assert listed.returncode == 0, listed.stdout()[-2000:] + listed.stderr()[-2000:]
        return _listing_ids(listed.stdout())

    def listing(self, listing_id: str) -> Any:
        return self.registry.get_listing(listing_id)

    def request_introduction_args(self, listing_id: str, option_id: str) -> list[str]:
        return [
            "bare-metal", "request-introduction", listing_id,
            "--option-id", option_id,
            *self._config(),
        ]

    def introduce_args(self, run_id: str, contact_email: str) -> list[str]:
        return [
            "bare-metal", "settlement", "contact", "introduce",
            "--run-id", run_id,
            "--contact", f"email={contact_email}",
            *self._config(),
        ]
