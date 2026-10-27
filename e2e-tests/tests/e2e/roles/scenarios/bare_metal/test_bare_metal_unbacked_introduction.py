"""Unbacked bare-metal discovery reaching a usable introduction, on the bare-metal lane.

The compute family's introduction scenario, on bare metal: the shared stages of
``helpers/introduction_stages.py`` through bare metal's driver
(``introduction_driver.py``), with bare metal's own stages between them. Against
a mock-profile site, the bare-metal storefront, and its registry, the site's
operator declares three whole machines: one in a capacity-backed pool naming its
host, one in an unbacked pool -- no deliverable mode, a configuration-free
provider -- naming none, each pool at an asking rate, and one in a backed pool
that states no rate. A storefront pool override offers the unbacked pool by
introduction alone. A rate-bounded ``market bare-metal list`` returns the backed
and unbacked listings together and leaves out the rateless one; a
``capacity_backing=unbacked`` query returns the unbacked one and neither backed
one; and the unbacked listing publishes ``capacity_backing: unbacked``, no host,
no access methods, and only ``contact-exchange.v1``. The buyer reveals the
introduction through ``market bare-metal settlement contact introduce``, its own
file sink receiving the seller's contact, and the storefront mails the buyer's
contact to the seller through the lane's Mailpit. The deal has no fulfillment:
its status route answers 404.

The storefront's loops are held for the module, so every publication the
scenario observes is one it stepped.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from e2e_harness.settings import settings

from tests.e2e.roles.buyer_cli import _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.introduction_stages import (
    IntroductionState,
    Stage00_DisclosureBeforeCommitment,
    Stage01_BackedAndUnbackedSupply,
    Stage02_Reveal,
    Stage03_SellerDelivery,
)
from tests.e2e.roles.scenarios.bare_metal.conftest import lane_setting
from tests.e2e.roles.scenarios.bare_metal.introduction_driver import (
    BareMetalIntroductionDriver,
)

pytestmark = [
    # Listed first, so the hold is taken before, and released after, every
    # other fixture of the module.
    pytest.mark.usefixtures("storefront_loops_held"),
    pytest.mark.e2e_bare_metal_unbacked_introduction,
]

#: Delivery terms: what a backed listing commits to and an unbacked one never states.
DELIVERY_TERMS = ("host_id", "physical_host_id", "access_methods")


@pytest.fixture(scope="module")
def introduction_state() -> IntroductionState:
    return IntroductionState(run=uuid.uuid4().hex[:8])


@pytest.fixture(scope="module")
def introduction_driver(
    buyer_cli_binary: Path,
    tmp_path_factory,
    bare_metal_storefront_admin,
    bare_metal_storefront_public,
    bare_metal_site_operator,
    bare_metal_site_capacity,
    bare_metal_registry,
) -> BareMetalIntroductionDriver:
    """Bare metal's driver, with a buyer whose own sink is a file the scenario
    reads and whose ``[bare_metal]`` section pins the lane's registry."""
    mailpit_url = str(settings.get("MAILPIT.API_URL", "") or "").rstrip("/")
    if not mailpit_url:
        pytest.fail("MAILPIT.API_URL is not configured for this lane")
    base = tmp_path_factory.mktemp("bare_metal_introduction_buyer")
    delivered = base / "delivered.jsonl"
    registry_url = lane_setting("registry_url").rstrip("/")
    registry_authority = lane_setting("registry_authority_id")
    registry_principal = (
        "{ scheme = " + _toml_quote(lane_setting("registry_scheme"))
        + ", identifier = " + _toml_quote(lane_setting("registry_identifier")) + " }"
    )
    buyer = create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=base,
        domain_identity="bare_metal.v1",
        marketplace_scheme=lane_setting("buyer_scheme"),
        marketplace_credential=lane_setting("buyer_credential"),
        registries=(registry_url,),
        registry_authorities={
            registry_url: {
                "authority": registry_authority,
                "identities": [
                    {
                        "scheme": lane_setting("registry_scheme"),
                        "identifier": lane_setting("registry_identifier"),
                    }
                ],
            }
        },
        toml_sections=(
            "[bare_metal]",
            f"registry_url = {_toml_quote(registry_url)}",
            f"registry_authority = {_toml_quote(registry_authority)}",
            f"registry_principals = [{registry_principal}]",
            "",
            "[Delivery]",
            'enabled = ["file"]',
            "",
            "[Delivery.file]",
            f"path = {_toml_quote(str(delivered))}",
            "",
        ),
    )
    return BareMetalIntroductionDriver(
        buyer=buyer,
        delivered=delivered,
        mailpit_url=mailpit_url,
        seller_contact_email=lane_setting("seller_contact_email"),
        site_id=lane_setting("site_id"),
        storefront_admin=bare_metal_storefront_admin,
        storefront_public=bare_metal_storefront_public,
        site_operator=bare_metal_site_operator,
        site_capacity=bare_metal_site_capacity,
        registry=bare_metal_registry,
    )


class TestStage00_DisclosureBeforeCommitment(Stage00_DisclosureBeforeCommitment):
    pass


class TestStage01_BackedAndUnbackedSupply(Stage01_BackedAndUnbackedSupply):
    pass


class TestStage01b_UnbackedListingTerms:
    def test_03b_a_backing_filter_returns_only_unbacked_supply(
        self,
        introduction_driver: BareMetalIntroductionDriver,
        introduction_state: IntroductionState,
    ):
        """The registry filters backing exactly, so a buyer can ask for supply
        no admission authority stands behind."""
        require_state(
            introduction_state, "unbacked_listing", "backed_listing", "rateless_listings"
        )
        found = introduction_driver.discover("capacity_backing=unbacked")
        assert introduction_state.unbacked_listing in found, found
        assert not {
            introduction_state.backed_listing, *introduction_state.rateless_listings
        } & found, found
        for listing_id in found:
            listing = introduction_driver.listing(listing_id)
            assert listing.listing_resource.get("capacity_backing") == "unbacked", listing_id

    def test_03c_the_unbacked_listing_states_no_delivery_term(
        self,
        introduction_driver: BareMetalIntroductionDriver,
        introduction_state: IntroductionState,
    ):
        require_state(introduction_state, "unbacked_listing", "backed_listing")
        unbacked = introduction_driver.listing(introduction_state.unbacked_listing)
        assert unbacked.listing_resource["capacity_backing"] == "unbacked"
        assert not set(DELIVERY_TERMS) & set(unbacked.listing_resource), (
            unbacked.listing_resource
        )
        # The backed machine's listing, from the same site, commits to them all.
        backed = introduction_driver.listing(introduction_state.backed_listing)
        assert backed.listing_resource["capacity_backing"] == "backed"
        assert set(DELIVERY_TERMS) <= set(backed.listing_resource), backed.listing_resource


class TestStage02_Reveal(Stage02_Reveal):
    pass


class TestStage03_SellerDelivery(Stage03_SellerDelivery):
    pass


class TestStage04_NoFulfillment:
    def test_06_the_introduction_deal_has_no_fulfillment(
        self, buyer_fulfillment, introduction_state: IntroductionState
    ):
        """A deal settled by introduction has no fulfillment to read, and the
        storefront says so rather than failing on a binding that names no host."""
        require_state(introduction_state, "revealed", "negotiation_id")
        with pytest.raises(RuntimeError) as refused:
            buyer_fulfillment.status(introduction_state.negotiation_id)
        assert "404" in str(refused.value), refused.value
        assert "has no fulfillment" in str(refused.value), refused.value
