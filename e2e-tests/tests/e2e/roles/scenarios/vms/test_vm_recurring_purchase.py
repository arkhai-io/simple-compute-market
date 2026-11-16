"""A VM recurring purchase through ``market buy``, delivered, on the mock VM lane.

The lane's buyer, with no wallet and a default buyer's terms, buys a recurring
on-demand option through ``market buy`` in ``arkhai.payments.v1`` against the
lane's payments double. The lane's storefront declares rate servicing for
``charged`` and ``returned`` (``domains/vms/storefront/storefront.bob.lane.toml``),
a lane fixture that lets it publish, accept and service the option. The module
runs the shared purchase stages (``helpers/buyer_purchase_stages.py``), the
canonical deal's delivery and teardown stages
(``helpers/compute_deal_stages.py``) and the recurring purchase's stages
(``helpers/recurring_purchase_stages.py``), with ``VmRecurringPurchaseDriver``
supplying VM's part, and inserts its own:

  03    Listing:         its resource listed with one recurring payments settlement
  09a2  Reconciliation:  the capacity-event loop stepped, closing the listing

``market buy`` polls its settlement until delivery, so it runs in the
background from ``Purchase03`` until ``Purchase09`` while the stages step
delivery. The buyer ends the deal by its own ``market end``, which the
storefront's servicing step carries out at the site, and the scenario does not
wait for the delivery deadline. Its resource, host, pool and GPU model are its
own (``host_registry.py``), since a listing's binding to its resource outlives
the listing and ``market buy`` selects its listing by discovery. The
storefront's loops, fulfillment convergence and the lease watchdog are held for
the module. This is lane-double evidence: it proves the money a buyer is shown
and approves for a per-period Agreement, rate delivery and the buyer's end.
Mock delivery is never evidence of a real guest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.buyer_purchase_stages import (
    Purchase01_PayerBalanceBefore,
    Purchase02_ListingDiscovered,
    Purchase03_Bought,
    Purchase04_PurchaseCorrelated,
    Purchase09_PurchaseRunEnded,
)
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.compute_deal_stages import (
    DURATION_HOURS,
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
    Recurring05_RateStartedAfterActivation,
    Recurring06_AcceptedMoneyShown,
    Recurring07_BuyerEnds,
    Recurring08_PayerChargedOnePeriod,
    RecurringPurchaseState,
    recurring_purchase_cleanup,
)
from tests.e2e.roles.scenarios.vms.conftest import (
    capacity_site_id,
    capacity_source_for,
    step_listing_reconciliation,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_RECURRING_PURCHASE_HOST,
    E2E_RECURRING_PURCHASE_POOL_ID,
)
from tests.e2e.roles.scenarios.vms.purchase_driver import (
    VmRecurringPurchaseDriver,
    vm_purchase_cli,
)

#: This purchase's own resource, and the GPU model only it declares, which
#: ``market buy``'s discovery query names.
PURCHASE_RESOURCE_ID = "compute-e2e-recurring-purchase-001"
PURCHASE_GPU_MODEL = "RTX 4070"

pytestmark = [
    # The payments target first, so a run without one is a blocked skip before
    # any hold or write. Then the holds, taken before, and released after,
    # every other fixture of the module; the lane's cleanup and the purchase's
    # follow them, so they run while the holds stand.
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "purchase_cleanup", "lane_doubles_evidence",
    ),
    pytest.mark.e2e_vm_recurring_purchase,
]

log = logging.getLogger(__name__)


@dataclass
class VmRecurringPurchaseState(RecurringPurchaseState):
    """The VM recurring purchase's state, under VM's domain identity."""

    domain_identity: str = "vms.compute"


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    config = configured_payments()
    assert config.livemode is False
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the listing"
    return config


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    """The lane's buyer, profiled with no wallet and no waivers, buying through
    Arkhai payments alone."""
    return vm_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("vm_recurring_purchase_buyer"),
    )


@pytest.fixture(scope="module")
def deal_state() -> VmRecurringPurchaseState:
    return VmRecurringPurchaseState()


@pytest.fixture(scope="module")
def deal_driver(
    payments_config, provisioning_client, provisioning_test_client, storefront_client,
    storefront_admin_client, storefront_service_client, site_capacity_admin_client,
    site_capacity, registry_client,
) -> VmRecurringPurchaseDriver:
    """VM's part of the purchase, over its own resource, host, pool and GPU model.

    The buyer has no wallet, so of the lane buyer's configuration it takes only
    the SSH public key its provision terms carry.
    """
    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None)
        or "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    return VmRecurringPurchaseDriver(
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client,
        storefront_service_client=storefront_service_client,
        site_capacity_admin_client=site_capacity_admin_client,
        site_capacity=site_capacity,
        buyer_config={"ssh_public_key": ssh_public_key},
        site_id=capacity_site_id(),
        reserved_resource_id=PURCHASE_RESOURCE_ID,
        host=E2E_RECURRING_PURCHASE_HOST,
        pool_id=E2E_RECURRING_PURCHASE_POOL_ID,
        gpu_model=PURCHASE_GPU_MODEL,
        purchase_registry=registry_client,
        seller_account=str(payment_setting("SELLER_ACCOUNT")),
        dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
    )


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: VmRecurringPurchaseDriver,
                     deal_state: VmRecurringPurchaseState, provisioning_test_client):
    """Resume a job the purchase's gates still hold, stop a ``market buy``
    still running, end an approved deal the stages did not end, by the buyer's
    own stop, then remove the gates' rules; the lane's cleanup releases the
    module's holds and its reserved resources.

    The gates are opened before their rules are removed, since a removed rule
    leaves a job it holds waiting.
    """
    yield
    rules = provisioning_test_client.vm_rules
    run_cleanup([
        ("open the purchase's mock gates", deal_driver.open_gates),
        *recurring_purchase_cleanup(purchase_cli, deal_driver, deal_state),
        # Deleting a rule that is already gone reports it not deleted; only a
        # real failure raises, and it is reported like any step's.
        ("remove the create mock rule", lambda: rules.delete_rule(deal_driver.create_rule_id)),
        ("remove the teardown mock rule", lambda: rules.delete_rule(deal_driver.teardown_rule_id)),
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


class TestStage03_ListingCreated:
    def test_03_the_recurring_listing_is_created_and_published(
        self, storefront_seller_client, storefront_admin_client, registry_client,
        deal_driver: VmRecurringPurchaseDriver, deal_state: VmRecurringPurchaseState,
    ):
        """The seller lists the purchase's resource with one recurring payments
        settlement; creating it open publishes it to the registry, which the
        lane's servicing declaration lets publication do."""
        require_state(deal_state, "_registry_reachable", "_supply_seeded")
        resource = deal_driver.listing_resource()
        listing_id = storefront_seller_client.create_listing(
            listing_resource=resource,
            capacity_source=capacity_source_for(resource),
            max_duration_seconds=DURATION_HOURS * 3600,
            settlements=[deal_driver.listing_settlement()],
        ).listing_id
        assert listing_id, "listing creation returned no listing id"
        listing = storefront_admin_client.get_listing(listing_id)
        assert listing.status == "open" and listing.paused is False, listing
        published = registry_client.get_listing(listing_id)
        assert str(published.id) == listing_id, published
        deal_state.seller_listing_id = listing_id
        deal_state.listing_published = True
        log.info("[03] Recurring listing %s created for resource %s and published",
                 listing_id, deal_driver.reserved_resource_id)


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


class TestStage09a2_CapacityEventCycle:
    def test_09a2_capacity_events_dry_run_then_advance(
        self, storefront_admin_client, deal_state: VmRecurringPurchaseState,
    ):
        """Step the held capacity-event loop, which closes the listing the
        purchase's reservation leaves unsatisfiable (``step_listing_reconciliation``)."""
        require_state(deal_state, "seller_listing_id", "provisioning_result_injected")
        pending, applied = step_listing_reconciliation(storefront_admin_client)
        deal_state._listing_reconciled = True
        log.info("[09a2] Capacity events for listing %s stepped: %s pending, %s applied",
                 deal_state.seller_listing_id, pending, applied)


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


class TestRecurring05_RateStartedAfterActivation(Recurring05_RateStartedAfterActivation):
    pass


class TestPurchase09_PurchaseRunEnded(Purchase09_PurchaseRunEnded):
    pass


class TestRecurring06_AcceptedMoneyShown(Recurring06_AcceptedMoneyShown):
    pass


# ===========================================================================
# The buyer's end, teardown and release
# ===========================================================================

class TestStage09c2_ArmTeardownGate(Stage09c2_ArmTeardownGate):
    pass


class TestRecurring07_BuyerEnds(Recurring07_BuyerEnds):
    pass


class TestStage11a2_ReleaseTeardownGateAndDrain(Stage11a2_ReleaseTeardownGateAndDrain):
    pass


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestRecurring08_PayerChargedOnePeriod(Recurring08_PayerChargedOnePeriod):
    pass
