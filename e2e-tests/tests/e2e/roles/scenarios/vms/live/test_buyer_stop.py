"""Live verification: the buyer's stop of a VM on-demand rate deal.

Extends ``e2e_vm_recurring_purchase`` in the live verification form, against the
run's external payments target in test mode, on wall time, with mock
provisioning. The run's buyer buys a recurring on-demand option through ``market
buy`` under the run's period and term, and the deal is delivered, through the
recurring purchase's shared stages; the buyer's own ``market end`` then gives the
payments authority the payer's stop its lane twin gave the payments double, and
the authority's snapshot, polled until it carries the stop, is held to the lane
twin's assertion: the part stopped by its payer with ``charged``, the started
period settled (``producer_assertions.assert_payer_stop``). No stage runs after
it. Every stage requires the module's one observation, whose outcome the module
logs at its end (``helpers/qualification.py``). In no lane: a lane-owned payments
target is a blocked skip. Its topology requirements are ``e2e-tests/README.md``'s
"Live verification".
"""

from __future__ import annotations

import pytest

from tests.e2e.roles.helpers.buyer_purchase_stages import (
    Purchase01_PayerBalanceBefore,
    Purchase02_ListingDiscovered,
    Purchase03_Bought,
    Purchase04_PurchaseCorrelated,
    Purchase09_PurchaseRunEnded,
)
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
)
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    Recurring04_MandateApproved,
    Recurring05_DeliveryRecoveredAtTheStart,
    Recurring06_RateStartedAfterActivation,
    Recurring07_AcceptedMoneyShown,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_LIVE_BUYER_STOP_GPU_MODEL,
    E2E_LIVE_BUYER_STOP_HOST,
    E2E_LIVE_BUYER_STOP_POOL_ID,
    E2E_LIVE_BUYER_STOP_RESOURCE_ID,
)
from tests.e2e.roles.scenarios.vms.live.stages import (
    Live00_LabelledLiveEvidence,
    LiveBuyerStop_PayerStopCharged,
)
from tests.e2e.roles.scenarios.vms.rate_servicing.conftest import RateRow
from tests.e2e.roles.scenarios.vms.rate_servicing.stages import (
    VmRateCapacityEventCycle,
    VmRateListingCreated,
)

#: The observation every stage of this module requires.
OBSERVATIONS = ("the buyer's stop",)

pytestmark = [
    # The prerequisites first — the payments target, the provenance, mock
    # provisioning and the buyer's balance — so a topology missing one is a
    # blocked skip naming it before the module's holds or purchase. Then the
    # holds, taken before, and released after, every other fixture of the
    # module; the cleanup follows them, so it runs while the holds stand.
    pytest.mark.usefixtures(
        "payments_config", "live_provenance", "mock_provisioning", "funded_buyer",
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess",
        "release_reserved_resources", "purchase_cleanup",
    ),
    pytest.mark.e2e_vm_live_rate_servicing,
]


@pytest.fixture(scope="module")
def rate_row() -> RateRow:
    return RateRow(host=E2E_LIVE_BUYER_STOP_HOST, pool_id=E2E_LIVE_BUYER_STOP_POOL_ID,
                   resource_id=E2E_LIVE_BUYER_STOP_RESOURCE_ID,
                   gpu_model=E2E_LIVE_BUYER_STOP_GPU_MODEL)


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


class TestLive00_LabelledLiveEvidence(Live00_LabelledLiveEvidence):
    pass


class TestStage03_ListingCreated(VmRateListingCreated):
    pass


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


class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_CapacityEventCycle(VmRateCapacityEventCycle):
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


class TestStage09c2_ArmTeardownGate(Stage09c2_ArmTeardownGate):
    pass


class TestLiveBuyerStop_PayerStopCharged(LiveBuyerStop_PayerStopCharged):
    pass
