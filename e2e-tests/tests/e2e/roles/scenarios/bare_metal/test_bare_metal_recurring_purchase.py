"""A whole-host recurring purchase, delivered, on the mock bare-metal lane.

A profiled Ed25519 buyer with no wallet and a default buyer's terms buys a
recurring on-demand option on one whole host through ``market bare-metal buy``
in ``arkhai.payments.v1`` against the lane's payments double. The lane's
storefront declares rate servicing for ``charged`` and ``returned``
(``domains/bare_metal/storefront/storefront.dev.toml``), a lane fixture that lets
it publish, accept and service the option. The module runs the shared purchase
stages (``helpers/buyer_purchase_stages.py``), the canonical deal's delivery
and teardown stages (``helpers/compute_deal_stages.py``) and the recurring
purchase's stages (``helpers/recurring_purchase_stages.py``), with
``BareMetalRecurringPurchaseDriver`` supplying bare metal's part, and inserts
bare metal's publication close (09a2, shared with the canonical deal's
bare-metal lanes) and its own:

  03  Publication:  one pass publishes the purchase's machine, offered by a
                    pool override stating the recurring option alone

The buyer ends the deal by its own ``market bare-metal end``, and the seller's
list shows it ended once released. Every instant is reached by setting lane
time, never by waiting, and the scenario does not wait for the delivery
deadline. The storefront's loops, fulfillment
convergence and the lease watchdog are held for the module. This is lane-double
evidence: it proves the money a buyer is shown and approves for a per-period
Agreement, rate delivery and the buyer's end. Mock access is never evidence of
real SSH.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass

import pytest
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from market_arkhai_payments import ArkhaiPaymentsConfig
from market_identity import Ed25519Signer
from market_pool_overrides import SyncPoolOverrideClient

from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.buyer_purchase_stages import (
    Purchase01_PayerBalanceBefore,
    Purchase02_ListingDiscovered,
    Purchase03_Bought,
    Purchase04_PurchaseCorrelated,
    Purchase09_PurchaseRunEnded,
)
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.compute_deal import advance_storefront, dry_run_storefront
from tests.e2e.roles.helpers.compute_deal_stages import (
    Stage00_LifecycleHeld,
    Stage00a_StorefrontHealth,
    Stage00b_RegistryReachable,
    Stage00c2_ProvisioningContractPins,
    Stage00c_ProvisioningHealth,
    Stage00e_ProvisioningMockMode,
    Stage00f1_ExecutorHostRegistry,
    Stage00h_ProvisioningStorefrontLink,
    Stage07a_ArmCreateGate,
    Stage08b2_ReleaseCreateGateAndDrain,
    Stage09a_FulfillmentConvergesToActive,
    Stage09b_SettlementReadyAndCredentials,
    Stage09c2_ArmTeardownGate,
    Stage09c_LeaseRecorded,
    Stage11a2_ReleaseTeardownGateAndDrain,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.payments import configured_payments, payment_setting
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    Recurring04_MandateApproved,
    Recurring05_DeliveryRecoveredAtTheStart,
    Recurring06_RateStartedAfterActivation,
    Recurring07_AcceptedMoneyShown,
    Recurring08_BuyerEnds,
    Recurring09_PayerChargedOnePeriod,
    Recurring10_SellerListsTheDealEnded,
    RecurringPurchaseState,
    recurring_purchase_cleanup,
)
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import WHOLE_HOST_CAPACITY
from tests.e2e.roles.scenarios.bare_metal.conftest import _pinned, lane_setting
from tests.e2e.roles.scenarios.bare_metal.publication_stages import (
    BareMetalPublicationClosesListing,
)
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import (
    BareMetalRecurringPurchaseDriver,
    bare_metal_purchase_cli,
    purchase_fulfillment_transport,
    purchase_registry_client,
)

pytestmark = [
    # The payments target first, so a run without one is a blocked skip before
    # any hold or write. Then the holds, taken before, and released after,
    # every other fixture of the module; the purchase's cleanup follows them,
    # so it runs while the holds stand.
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "fulfillment_convergence_held",
        "lease_watchdog_held", "purchase_cleanup", "lane_doubles_evidence",
    ),
    pytest.mark.e2e_bare_metal_recurring_purchase,
]

PUBLICATION = "publication"

log = logging.getLogger(__name__)


@dataclass
class BareMetalRecurringPurchaseState(RecurringPurchaseState):
    """The bare-metal recurring purchase's state, under bare metal's domain identity."""

    domain_identity: str = "bare_metal.v1"


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    lane_setting("registry_url")
    lane_setting("storefront_url")
    config = configured_payments()
    assert config.livemode is False
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the pool override"
    return config


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    return bare_metal_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("bare_metal_recurring_buyer"),
    )


@pytest.fixture(scope="module")
def deal_state() -> BareMetalRecurringPurchaseState:
    return BareMetalRecurringPurchaseState()


@pytest.fixture(scope="module")
def purchase_fulfillment(purchase_cli) -> BareMetalFulfillmentTransport:
    """The purchase profile's own fulfillment transport."""
    return purchase_fulfillment_transport(purchase_cli)


@pytest.fixture(scope="module")
def purchase_registry(purchase_cli):
    """The registry, signed as the purchase profile rather than the lane buyer."""
    client = purchase_registry_client(purchase_cli)
    yield client
    client.close()


@pytest.fixture(scope="module")
def deal_driver(
    payments_config, purchase_cli, purchase_fulfillment, purchase_registry,
    bare_metal_site_operator, bare_metal_site_capacity, provisioning_client,
    provisioning_test_client, storefront_admin_client, site_capacity,
) -> BareMetalRecurringPurchaseDriver:
    # Only the public SSH key leaves this fixture's memory.
    public = Ed25519Signer(os.urandom(32)).identity.identifier
    public_bytes = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
    ssh_blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + public_bytes
    return BareMetalRecurringPurchaseDriver(
        site_operator=bare_metal_site_operator,
        site_capacity_admin=bare_metal_site_capacity,
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_admin_client=storefront_admin_client,
        fulfillment=purchase_fulfillment,
        site_capacity=site_capacity,
        buyer_config={"ssh_public_key": "ssh-ed25519 " + base64.b64encode(ssh_blob).decode("ascii")},
        site_id=lane_setting("site_id"),
        purchase_registry=purchase_registry,
        pool_overrides=SyncPoolOverrideClient(storefront_admin_client),
        storefront_pins=_pinned("storefront"),
        config_path=str(purchase_cli.config_path),
        seller_account=str(payment_setting("SELLER_ACCOUNT")),
        dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
    )


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: BareMetalRecurringPurchaseDriver,
                     deal_state: BareMetalRecurringPurchaseState, provisioning_test_client):
    """Whatever the stages left: a held job, a purchase command still running,
    an approved deal the stages did not end, ended by the buyer's own stop, the
    gates' rules, a provisioning job still running, and the pool override.

    The gates are opened first, since a removed rule leaves a job it holds
    waiting.
    """
    yield
    rules = provisioning_test_client.bare_metal_rules
    run_cleanup([
        ("open the purchase's mock gates", deal_driver.open_gates),
        *recurring_purchase_cleanup(purchase_cli, deal_driver, deal_state),
        # Deleting a rule that is already gone reports it not deleted; only a
        # real failure raises, and it is reported like any step's.
        ("remove the access-grant mock rule", lambda: rules.delete_rule(deal_driver.create_rule_id)),
        ("remove the access-reclaim mock rule",
         lambda: rules.delete_rule(deal_driver.teardown_rule_id)),
        ("drain provisioning", lambda: provisioning_test_client.drain(timeout=30)),
        ("remove the pool override", deal_driver.remove_pool_override),
    ])


# ===========================================================================
# Readiness and supply
# ===========================================================================

class TestStage00_LifecycleHeld(Stage00_LifecycleHeld):
    pass


class TestStage00a_StorefrontHealth(Stage00a_StorefrontHealth):
    pass


class TestStage00b_RegistryReachable(Stage00b_RegistryReachable):
    pass


class TestStage00c_ProvisioningHealth(Stage00c_ProvisioningHealth):
    pass


class TestStage00c2_ProvisioningContractPins(Stage00c2_ProvisioningContractPins):
    pass


class TestStage00e_ProvisioningMockMode(Stage00e_ProvisioningMockMode):
    pass


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


class TestStage03_PublicationPublishesTheMachine:
    def test_03_one_publication_pass_publishes_the_recurring_listing(
        self, storefront_admin_client, deal_driver: BareMetalRecurringPurchaseDriver,
        deal_state: BareMetalRecurringPurchaseState,
    ):
        """The dry run would publish the machine, and one pass publishes it,
        which the lane's servicing declaration lets publication do for its
        recurring option."""
        require_state(deal_state, "_supply_seeded")
        resource_id = deal_driver.reserved_resource_id
        preview = dry_run_storefront(storefront_admin_client, PUBLICATION)
        assert any(
            item.get("action") == "publish"
            and item.get("source", {}).get("physical_resource_id") == resource_id
            for item in preview["actions"]
        ), preview
        report = advance_storefront(storefront_admin_client, PUBLICATION)
        listings = [
            str(item["listing_id"]) for item in report["actions"]
            if item["action"] == "publish"
            and item["source"]["physical_resource_id"] == resource_id
        ]
        assert len(listings) == 1, report
        assert deal_driver.available_units() == WHOLE_HOST_CAPACITY["units"]
        deal_state.seller_listing_id = listings[0]
        deal_state.listing_published = True
        log.info("[03] Recurring listing %s published for machine %s", listings[0], resource_id)


# ===========================================================================
# The purchase
# ===========================================================================

class TestPurchase01_PayerBalanceBefore(Purchase01_PayerBalanceBefore):
    pass


class TestPurchase02_ListingDiscovered(Purchase02_ListingDiscovered):
    pass


class TestStage07a_ArmCreateGate(Stage07a_ArmCreateGate):
    pass


class TestPurchase03_Bought(Purchase03_Bought):
    pass


class TestPurchase04_PurchaseCorrelated(Purchase04_PurchaseCorrelated):
    pass


class TestStage08b2_ReleaseCreateGateAndDrain(Stage08b2_ReleaseCreateGateAndDrain):
    pass


class TestRecurring04_MandateApproved(Recurring04_MandateApproved):
    pass


# ===========================================================================
# Delivery
# ===========================================================================

class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_PublicationClosesTheListing(BareMetalPublicationClosesListing):
    pass


class TestRecurring05_DeliveryRecoveredAtTheStart(Recurring05_DeliveryRecoveredAtTheStart):
    pass


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


class TestRecurring06_RateStartedAfterActivation(Recurring06_RateStartedAfterActivation):
    pass


class TestPurchase09_PurchaseRunEnded(Purchase09_PurchaseRunEnded):
    pass


class TestRecurring07_AcceptedMoneyShown(Recurring07_AcceptedMoneyShown):
    pass


# ===========================================================================
# The buyer's end, teardown and release
# ===========================================================================

class TestStage09c2_ArmTeardownGate(Stage09c2_ArmTeardownGate):
    pass


class TestRecurring08_BuyerEnds(Recurring08_BuyerEnds):
    pass


class TestStage11a2_ReleaseTeardownGateAndDrain(Stage11a2_ReleaseTeardownGateAndDrain):
    pass


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestRecurring09_PayerChargedOnePeriod(Recurring09_PayerChargedOnePeriod):
    pass


class TestRecurring10_SellerListsTheDealEnded(Recurring10_SellerListsTheDealEnded):
    pass
