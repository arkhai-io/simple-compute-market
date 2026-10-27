"""Settlement by introduction on the VM lane, from discovery to the seller's inbox.

The compute family's introduction scenario, on VM: every stage is one of
``helpers/introduction_stages.py``'s, run through VM's driver
(``introduction_driver.py``). The site's operator declares two VM pools at an
asking rate, one capacity-backed and one unbacked, and a storefront pool
override offers the unbacked pool by introduction alone; the lane's default
listing publishes no rate. The buyer negotiates and reveals the introduction
through the production ``market`` CLI, and Bob's storefront mails the buyer's
contact to the seller through the lane's Mailpit.

The storefront's timer loops are held for the module and publication is stepped,
so the cycle the scenario observes is the one it ran.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from e2e_harness.settings import settings
from market_identity import IdentityScheme

from tests.e2e.roles.buyer_cli import _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.introduction_stages import (
    IntroductionState,
    Stage00_DisclosureBeforeCommitment,
    Stage01_BackedAndUnbackedSupply,
    Stage02_Reveal,
    Stage03_SellerDelivery,
)
from tests.e2e.roles.scenarios.vms.introduction_driver import VmIntroductionDriver

pytestmark = [
    # Listed first, so the hold is taken before, and released after, every
    # other fixture of the module; the lane's cleanup follows it, so it runs
    # while the hold stands.
    pytest.mark.usefixtures(
        "storefront_loops_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
    ),
    pytest.mark.e2e_vm_introduction,
]


@pytest.fixture(scope="module")
def introduction_state() -> IntroductionState:
    return IntroductionState(run=uuid.uuid4().hex[:8])


@pytest.fixture(scope="module")
def introduction_driver(
    buyer_cli_binary: Path,
    tmp_path_factory,
    storefront_admin_client,
    registry_client,
    provisioning_client,
    resource_pool_client,
    site_capacity_admin_client,
) -> VmIntroductionDriver:
    """VM's driver, with a buyer whose own sink is a file the scenario reads."""
    mailpit_url = str(settings.get("MAILPIT.API_URL", "") or "").rstrip("/")
    if not mailpit_url:
        pytest.fail("MAILPIT.API_URL is not configured for this lane")
    credential = str(getattr(settings.BUYER, "MARKETPLACE_CREDENTIAL", None) or "")
    if not credential:
        pytest.fail("BUYER.MARKETPLACE_CREDENTIAL is not configured for this lane")
    base = tmp_path_factory.mktemp("vm_introduction_buyer")
    delivered = base / "delivered.jsonl"
    registry_url = str(settings.REGISTRY.API_URL).rstrip("/")
    buyer = create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=base,
        domain_identity="vms.compute",
        marketplace_scheme=IdentityScheme.EIP191,
        marketplace_credential=credential,
        registries=(registry_url,),
        registry_authorities={
            registry_url: {
                "authority": str(settings.REGISTRY.get("authority_id", "") or ""),
                "identities": [
                    {
                        "scheme": "eip191",
                        "identifier": str(settings.REGISTRY.get("identifier", "") or ""),
                    }
                ],
            }
        },
        toml_sections=(
            "[Delivery]",
            'enabled = ["file"]',
            "",
            "[Delivery.file]",
            f"path = {_toml_quote(str(delivered))}",
            "",
        ),
        credential_variable="ARKHAI_E2E_BUYER_MARKETPLACE_CREDENTIAL",
    )
    return VmIntroductionDriver(
        buyer=buyer,
        delivered=delivered,
        mailpit_url=mailpit_url,
        storefront_admin_client=storefront_admin_client,
        registry_client=registry_client,
        provisioning_client=provisioning_client,
        resource_pool_client=resource_pool_client,
        site_capacity_admin_client=site_capacity_admin_client,
    )


class TestStage00_DisclosureBeforeCommitment(Stage00_DisclosureBeforeCommitment):
    pass


class TestStage01_BackedAndUnbackedSupply(Stage01_BackedAndUnbackedSupply):
    pass


class TestStage02_Reveal(Stage02_Reveal):
    pass


class TestStage03_SellerDelivery(Stage03_SellerDelivery):
    pass
