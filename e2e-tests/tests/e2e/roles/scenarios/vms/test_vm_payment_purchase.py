"""A VM buyer purchase through ``market buy`` in Arkhai payments, on the mock VM lane.

The VM lane's buyer purchase: the lane's buyer, with no wallet, buys one hour
of a VM through ``market buy`` in ``arkhai.payments.v1`` against the lane's
payments double. It runs the shared buyer-purchase stages
(``helpers/buyer_purchase_stages.py``) and the canonical deal's stages from
fulfillment onwards, ``VmPurchaseDriver`` supplying VM's part, and its lease
ends by the canonical deal's expiry: back-dated, then one stepped watchdog
cycle. It inserts its own:

  03    Listing:         its resource listed with one Arkhai payments settlement
  09a2  Reconciliation:  the capacity-event loop stepped, closing the listing

Its resource, host and pool are its own (``host_registry.py``), since a
listing's binding to its resource outlives the listing, and so is its GPU
model, since ``market buy`` selects its listing by discovery.

``market buy`` polls its settlement until delivery, so it runs in the
background from ``Purchase03`` until ``Purchase09`` while the stages step
delivery. The storefront's loops, fulfillment convergence and the lease watchdog
are held for the whole module. Mock delivery is never evidence of a real guest.
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
    Purchase05_PaymentRecordsChecked,
    Purchase09_PurchaseRunEnded,
    PurchaseState,
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
    Stage10a_LeaseExpirySetup,
    Stage10b_LeaseCycleBeginsTeardown,
    Stage11a2_ReleaseTeardownGateAndDrain,
    Stage11a_TeardownDispatch,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.payments import configured_payments, payment_setting
from tests.e2e.roles.scenarios.vms.conftest import (
    capacity_site_id,
    capacity_source_for,
    step_listing_reconciliation,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_PAYMENT_PURCHASE_HOST,
    E2E_PAYMENT_PURCHASE_POOL_ID,
)
from tests.e2e.roles.scenarios.vms.purchase_driver import VmPurchaseDriver, vm_purchase_cli

#: This purchase's own resource, and the GPU model only it declares, which
#: ``market buy``'s discovery query names.
PURCHASE_RESOURCE_ID = "compute-e2e-payment-purchase-001"
PURCHASE_GPU_MODEL = "RTX 4080"

pytestmark = [
    # The payments target first, so a run without one is a blocked skip before
    # any hold or write. Then the holds, taken before, and released after,
    # every other fixture of the module; the lane's cleanup and the purchase's
    # follow them, so they run while the holds stand.
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "purchase_cleanup",
    ),
    pytest.mark.e2e_vm_payment_purchase,
]

log = logging.getLogger(__name__)


@dataclass
class VmPurchaseState(PurchaseState):
    """The VM purchase's state: the purchase's, under VM's domain identity."""

    domain_identity: str = "vms.compute"


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    config = configured_payments()
    assert config.livemode is False
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the listing"
    return config


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    """The lane's buyer, profiled with no wallet, buying through Arkhai payments alone."""
    return vm_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("vm_payment_purchase_buyer"),
    )


@pytest.fixture(scope="module")
def deal_state() -> VmPurchaseState:
    return VmPurchaseState()


@pytest.fixture(scope="module")
def deal_driver(
    payments_config, provisioning_client, provisioning_test_client, storefront_client,
    storefront_admin_client, storefront_service_client, site_capacity_admin_client,
    site_capacity, registry_client,
) -> VmPurchaseDriver:
    """VM's part of the purchase, over its own resource, host, pool and GPU model.

    The buyer has no wallet, so of the lane buyer's configuration it takes only
    the SSH public key its provision terms carry.
    """
    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None)
        or "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    return VmPurchaseDriver(
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
        host=E2E_PAYMENT_PURCHASE_HOST,
        pool_id=E2E_PAYMENT_PURCHASE_POOL_ID,
        gpu_model=PURCHASE_GPU_MODEL,
        purchase_registry=registry_client,
        seller_account=str(payment_setting("SELLER_ACCOUNT")),
        dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
    )


@pytest.fixture(scope="module")
def purchase_cleanup(deal_driver: VmPurchaseDriver, provisioning_test_client):
    """Resume a job the purchase's gates still hold, then remove its rules; the
    lane's cleanup stops a ``market buy`` still running and releases the
    module's holds.

    The gates are opened before their rules are removed, since a removed rule
    leaves a job it holds waiting.
    """
    yield
    rules = provisioning_test_client.vm_rules
    run_cleanup([
        ("open the purchase's mock gates", deal_driver.open_gates),
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
    def test_03_the_purchase_listing_is_created_and_published(
        self, storefront_seller_client, storefront_admin_client, registry_client,
        deal_driver: VmPurchaseDriver, deal_state: VmPurchaseState,
    ):
        """The seller lists the purchase's resource with one Arkhai payments
        settlement; creating it open publishes it to the registry."""
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
        log.info("[03] Listing %s created for resource %s and published",
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


class TestPurchase05_PaymentRecordsChecked(Purchase05_PaymentRecordsChecked):
    pass


# ===========================================================================
# Delivery
# ===========================================================================

class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_CapacityEventCycle:
    def test_09a2_capacity_events_dry_run_then_advance(
        self, storefront_admin_client, deal_state: VmPurchaseState,
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


class TestPurchase09_PurchaseRunEnded(Purchase09_PurchaseRunEnded):
    pass


# ===========================================================================
# Lease expiry, teardown and release
# ===========================================================================

class TestStage09c2_ArmTeardownGate(Stage09c2_ArmTeardownGate):
    pass


class TestStage10a_LeaseExpirySetup(Stage10a_LeaseExpirySetup):
    pass


class TestStage10b_LeaseCycleBeginsTeardown(Stage10b_LeaseCycleBeginsTeardown):
    pass


class TestStage11a_TeardownDispatch(Stage11a_TeardownDispatch):
    pass


class TestStage11a2_ReleaseTeardownGateAndDrain(Stage11a2_ReleaseTeardownGateAndDrain):
    pass


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass
