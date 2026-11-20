"""The VM buyer's watchdog against a delivered rate deal, on the mock VM lane.

The lane's buyer, with no wallet and a default buyer's terms, buys a recurring
on-demand option through ``market buy --watchdog --watchdog-interval 1
--watchdog-threshold 2``, run in the harness's process with its probe and every
wait it makes programmed by the harness (``helpers/in_process_buyer.py``). The
module runs the recurring purchase's stages through the rate part's start while
``buy`` waits for its deal at the harness's gate, then the watchdog's four
cases on that one deal (``helpers/rate_watchdog_stages.py``): monitored from
available, a killed command reading ``unmonitored`` once its last probe is
stale, the resumed run reading ``monitored``, and the access lost while the
storefront's loops are held, which yields one buyer stop at the payments double
and the teardown. Its resource, host, pool and GPU model are its own
(``host_registry.py``). The storefront's loops, fulfillment convergence and the
lease watchdog are held for the module; blocked off injected lane time or the
lane's own payments double. Lane-double evidence; mock delivery is never
evidence of a real guest.
"""

from __future__ import annotations

import pytest

from tests.e2e.roles.helpers.buyer_purchase_stages import (
    Purchase01_PayerBalanceBefore,
    Purchase02_ListingDiscovered,
    Purchase03_Bought,
    Purchase04_PurchaseCorrelated,
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
from tests.e2e.roles.helpers.rate_watchdog_stages import (
    Watchdog01_MonitoredFromAvailable,
    Watchdog02_IntoTheFirstPeriod,
    Watchdog03_KilledCommandGoesStale,
    Watchdog04_ResumedRunMonitored,
    Watchdog05_AccessLostStopsOnce,
)
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    Recurring04_MandateApproved,
    Recurring05_DeliveryRecoveredAtTheStart,
    Recurring06_RateStartedAfterActivation,
)
from tests.e2e.roles.scenarios.vms.rate_servicing.stages import (
    VmRateCapacityEventCycle,
    VmRateListingCreated,
)

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
    pytest.mark.e2e_vm_rate_watchdog,
]


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


class TestWatchdog01_MonitoredFromAvailable(Watchdog01_MonitoredFromAvailable):
    pass


class TestWatchdog02_IntoTheFirstPeriod(Watchdog02_IntoTheFirstPeriod):
    pass


class TestWatchdog03_KilledCommandGoesStale(Watchdog03_KilledCommandGoesStale):
    pass


class TestWatchdog04_ResumedRunMonitored(Watchdog04_ResumedRunMonitored):
    pass


class TestStage09c2_ArmTeardownGate(Stage09c2_ArmTeardownGate):
    pass


class TestWatchdog05_AccessLostStopsOnce(Watchdog05_AccessLostStopsOnce):
    pass


class TestStage11a2_ReleaseTeardownGateAndDrain(Stage11a2_ReleaseTeardownGateAndDrain):
    pass


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass
