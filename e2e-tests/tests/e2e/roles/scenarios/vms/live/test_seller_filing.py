"""Live verification: a seller's filing on a running VM rate deal, ruled mechanically.

Extends ``e2e_vm_rate_dispute``'s seller's filing in the live verification form,
against the run's external payments target in test mode and its hosted dispute
authority, on wall time, with mock provisioning. The run's buyer buys a
recurring on-demand option through ``market buy`` under the run's period and
term, and the deal is delivered, through the recurring purchase's shared stages;
once the payments authority holds the first period's earnings, the storefront's
administrator ends the delivery as a failure and the storefront files
``delivery_end`` as the payee, the input its lane twin gave the mediation
double. The hosted authority rules the filing mechanically on its own schedule,
as it documents; its signed record, polled until the case is closed, and the
payments snapshot are held to the lane twin's assertion: the part protected,
the authority's stop returning its period with any earnings since the end
reversed, the Agreement's penalty capped at what the part then held, the
extension lifted and the case closed
(``producer_assertions.assert_payee_filing_ruled``). No operator endpoint is
called, and no stage runs after the assertion. Every stage requires
the module's one observation, whose outcome the module logs at its end
(``helpers/qualification.py``). In no lane: a lane-owned payments or mediation
target is a blocked skip. Its topology requirements are ``e2e-tests/README.md``'s
"Live verification".
"""

from __future__ import annotations

import pytest

from tests.e2e.roles.helpers import live_verification
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
from tests.e2e.roles.helpers.live_verification import Provenance
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    Recurring04_MandateApproved,
    Recurring05_DeliveryRecoveredAtTheStart,
    Recurring06_RateStartedAfterActivation,
    Recurring07_AcceptedMoneyShown,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_LIVE_SELLER_FILING_GPU_MODEL,
    E2E_LIVE_SELLER_FILING_HOST,
    E2E_LIVE_SELLER_FILING_POOL_ID,
    E2E_LIVE_SELLER_FILING_RESOURCE_ID,
)
from tests.e2e.roles.scenarios.vms.live.stages import (
    SELLERS_FILING,
    Live00_LabelledLiveEvidence,
    LiveDispute07_FirstPeriodHeld,
    LiveSellerFiling09_StorefrontFilesAsPayee,
    LiveSellerFiling10_MechanicalRulingRead,
)
from tests.e2e.roles.scenarios.vms.rate_servicing.conftest import RateRow
from tests.e2e.roles.scenarios.vms.rate_servicing.stages import (
    VmRateCapacityEventCycle,
    VmRateListingCreated,
)

#: The observation every stage of this module requires.
OBSERVATIONS = (SELLERS_FILING,)

pytestmark = [
    # The prerequisites first — the payments and mediation targets, the
    # provenance, mock provisioning and the buyer's balance — so a topology
    # missing one is a blocked skip naming it before the module's holds or
    # purchase. Then the holds, taken before, and released after, every other
    # fixture of the module; the cleanup follows them, so it runs while the
    # holds stand.
    pytest.mark.usefixtures(
        "payments_config", "mediation_target", "live_provenance", "mock_provisioning",
        "funded_buyer",
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess",
        "release_reserved_resources", "purchase_cleanup",
    ),
    pytest.mark.e2e_vm_live_dispute,
]


@pytest.fixture(scope="module")
def rate_row() -> RateRow:
    return RateRow(host=E2E_LIVE_SELLER_FILING_HOST, pool_id=E2E_LIVE_SELLER_FILING_POOL_ID,
                   resource_id=E2E_LIVE_SELLER_FILING_RESOURCE_ID,
                   gpu_model=E2E_LIVE_SELLER_FILING_GPU_MODEL)


@pytest.fixture(scope="module")
def live_provenance() -> Provenance:
    """The run's provenance with the mediation authority's revision, since
    the evidence is also that authority's."""
    return live_verification.live_provenance(mediation=True)


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


class TestLiveDispute07_FirstPeriodHeld(LiveDispute07_FirstPeriodHeld):
    pass


class TestLiveSellerFiling09_StorefrontFilesAsPayee(LiveSellerFiling09_StorefrontFilesAsPayee):
    pass


class TestLiveSellerFiling10_MechanicalRulingRead(LiveSellerFiling10_MechanicalRulingRead):
    pass
