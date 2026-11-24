"""A buyer's contested case on a running VM rate deal, ruled by an operator, on the mock VM lane.

The lane's buyer buys a recurring on-demand option through ``market buy``, and
the deal is delivered at the Agreement's start. A minute into the second period,
with the first period's earnings held, the buyer files ``delivery_end`` through
the mediation kit's dispute adapter, as its lifecycle would; the mediation double
holds the part and rules nothing, and the storefront's respondent discovery
contests the case. An operator decision through the typed control client then
rules a stop returning the period in progress and a reverse of the held first
period, closing the case. The storefront records the ruled end with no filing,
the deal is torn down, the payer gets back everything the ruling did not leave
the seller, and the seller's list shows the deal ended. The stages are the
recurring purchase's through its accepted money, then
``rate_dispute/stages.py``'s. Lane-double evidence; mock delivery is never
evidence of a real guest.
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
    Stage11a2_ReleaseTeardownGateAndDrain,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    Recurring04_MandateApproved,
    Recurring05_DeliveryRecoveredAtTheStart,
    Recurring06_RateStartedAfterActivation,
    Recurring07_AcceptedMoneyShown,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_RATE_CONTESTED_CASE_GPU_MODEL,
    E2E_RATE_CONTESTED_CASE_HOST,
    E2E_RATE_CONTESTED_CASE_POOL_ID,
    E2E_RATE_CONTESTED_CASE_RESOURCE_ID,
)
from tests.e2e.roles.scenarios.vms.rate_dispute.stages import (
    ContestedCase08_BuyerFiles,
    ContestedCase09_StorefrontContests,
    ContestedCase10_OperatorRules,
    ContestedCase11_StorefrontRecordsTheRuling,
    RateDispute07_FirstPeriodHeld,
    RateDispute12_PayerReturned,
    RateDispute13_DealEnded,
)
from tests.e2e.roles.scenarios.vms.rate_servicing.conftest import RateRow
from tests.e2e.roles.scenarios.vms.rate_servicing.stages import (
    VmRateCapacityEventCycle,
    VmRateListingCreated,
)

pytestmark = [
    # The payments target first, so a run without one is a blocked skip before
    # any hold or write. Then the holds, taken before, and released after,
    # every other fixture of the module; the lane's cleanup, the row's and the
    # doubles' rules follow them, so they run while the holds stand.
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "purchase_cleanup", "lane_doubles_evidence", "lane_double_rules",
    ),
    pytest.mark.e2e_vm_rate_dispute,
]


@pytest.fixture(scope="module")
def rate_row() -> RateRow:
    return RateRow(host=E2E_RATE_CONTESTED_CASE_HOST, pool_id=E2E_RATE_CONTESTED_CASE_POOL_ID,
                   resource_id=E2E_RATE_CONTESTED_CASE_RESOURCE_ID,
                   gpu_model=E2E_RATE_CONTESTED_CASE_GPU_MODEL)


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


class TestRateDispute07_FirstPeriodHeld(RateDispute07_FirstPeriodHeld):
    pass


class TestContestedCase08_BuyerFiles(ContestedCase08_BuyerFiles):
    pass


class TestContestedCase09_StorefrontContests(ContestedCase09_StorefrontContests):
    pass


class TestContestedCase10_OperatorRules(ContestedCase10_OperatorRules):
    pass


class TestContestedCase11_StorefrontRecordsTheRuling(ContestedCase11_StorefrontRecordsTheRuling):
    pass


class TestStage11a2_ReleaseTeardownGateAndDrain(Stage11a2_ReleaseTeardownGateAndDrain):
    pass


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestRateDispute12_PayerReturned(RateDispute12_PayerReturned):
    pass


class TestRateDispute13_DealEnded(RateDispute13_DealEnded):
    pass
