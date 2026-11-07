"""Observations 4 and 5: a bare-metal normal cycle, then a successor's refusal and retry.

The runbook's observations 4 and 5
(``docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes``),
made as an external-topology extension of the bare-metal lane's buyer purchase
(``test_bare_metal_payment_deal.py``): a profiled buyer with no wallet buys the
real-provisioning target's whole machine through ``market bare-metal buy`` in
``arkhai.payments.v1``, against the payments target the run names
(``PAYMENTS``), and ends it through ``market bare-metal teardown``.

The module runs once per cycle (``cleanup_cycle``), in order, on one machine:

- **normal** (observation 4): the pinned relay endpoint, a nonroot tenant, an
  unrelated key refused, the grant admitted, bounded working data and tenant
  activity seeded beside operator sentinels through the working-data probe
  (``working_data_qualification.py``), and after the ordinary reclaim the
  covered data absent, the sentinels unchanged, access ended and capacity
  restored;
- **refusal** (observation 5): a successor with a fresh UID and key, a foreign
  descendant planted in a tenant directory cleanup selects, the reclaim job
  queued for retry with its error and a next retry time, its log naming the
  descendant, the lease still ``releasing`` and its capacity unadvertised; then
  only that fixture repaired, and the same job completing.

Each cycle runs the shared purchase stages, the canonical deal's stages from
fulfillment onwards and the buyer-teardown ending, each declared once,
``RealBareMetalPurchaseDriver`` supplying bare metal's real part, with its own
stages in place of the lane purchase's re-drive and refund. No GPU is checked.

Every stage of a cycle requires that cycle's observation, and the module logs
each outcome (``helpers/qualification.py``): unproven, naming the field,
without the target's ``cleanup_qualification`` (the working-data stages skip,
and the refusal cycle skips whole) or its ``admission_log``. The module is in no
lane. Without the payments target or the real-provisioning target's bare-metal
host it is a blocked skip before any hold or write. A failure after the buyer's
approval refunds the payment as the seller and ends a delivered tenancy through
its lease's own reclaim, and reports by negotiation and transaction what it
cannot. The payer is funded by the deployment, never here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig

from e2e_harness.real_provisioning_target import SECTION
from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.buyer_purchase_stages import (
    Purchase01_PayerBalanceBefore,
    Purchase02_ListingDiscovered,
    Purchase03_Bought,
    Purchase04_PurchaseCorrelated,
    Purchase05_PaymentRecordsChecked,
    Purchase09_PurchaseRunEnded,
    Purchase10_BuyerTeardown,
    PurchaseState,
)
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.compute_deal import advance_storefront, dry_run_storefront
from tests.e2e.roles.helpers.compute_deal_stages import (
    Stage00_LifecycleHeld,
    Stage00a_StorefrontHealth,
    Stage00b_RegistryReachable,
    Stage00c2_ProvisioningContractPins,
    Stage00c_ProvisioningHealth,
    Stage00f1_ExecutorHostRegistry,
    Stage00h_ProvisioningStorefrontLink,
    Stage09a_FulfillmentConvergesToActive,
    Stage09b_SettlementReadyAndCredentials,
    Stage09c_LeaseRecorded,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.payment_compensation import PurchaseCompensation, refund_may_clear
from tests.e2e.roles.helpers.payments import configured_payments
from tests.e2e.roles.helpers.qualification import check_admission, target_host
from tests.e2e.roles.helpers.real_provisioning import JobWatch, configured_relay
from tests.e2e.roles.helpers.ssh_access import SshEndpoint, ssh_session
from tests.e2e.roles.scenarios.bare_metal.conftest import _pinned, lane_setting
from tests.e2e.roles.scenarios.bare_metal.publication_stages import (
    BareMetalPublicationClosesListing,
)
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import (
    bare_metal_purchase_cli,
    purchase_fulfillment_transport,
    purchase_registry_client,
    seller_refund,
)
from tests.e2e.roles.scenarios.bare_metal.real_compute_deal_driver import (
    bare_metal_executor_is_real,
)
from tests.e2e.roles.scenarios.bare_metal.real_purchase_driver import RealBareMetalPurchaseDriver
from tests.e2e.roles.scenarios.bare_metal.working_data_qualification import (
    WorkingDataQualification,
)

log = logging.getLogger(__name__)

#: The runbook observations this module makes, one per cycle; every stage of
#: a cycle requires that cycle's.
OBSERVATIONS = ("4", "5")
CYCLE_PARAM = "cleanup_cycle"
CYCLE_OBSERVATIONS = {"normal": ("4",), "refusal": ("5",)}
#: Where the target names the working-data probe's inputs.
CLEANUP_FIELD = f"{SECTION}.hosts.bare_metal.cleanup_qualification"

pytestmark = [
    # The payments target and the real-provisioning target first, then the
    # cycle's working-data preflight and the service's bare-metal execution,
    # so a run without either target, or against a mocked service, holds and
    # writes nothing. The holds follow, so they are released after every
    # other fixture; the cycle's working-data observer and its compensation
    # follow them, so they run while the holds stand.
    pytest.mark.usefixtures(
        "payments_config", "real_bare_metal_target", "real_bare_metal_execution",
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
        "cleanup_qualification", "purchase_cleanup",
    ),
    pytest.mark.e2e_bare_metal_qualification,
]


def pytest_generate_tests(metafunc):
    if "cleanup_cycle" in metafunc.fixturenames:
        metafunc.parametrize("cleanup_cycle", tuple(CYCLE_OBSERVATIONS), scope="module",
                             indirect=True)


@dataclass
class BareMetalQualificationState(PurchaseState):
    """One cycle's state, beside the purchase's."""

    domain_identity: str = "bare_metal.v1"
    _target_host_confirmed: bool = False
    _publication_previewed: bool = False
    #: The grant job this cycle's reservation ran, once it succeeded.
    create_job_id: Optional[str] = None
    #: Where the buyer connects, as the storefront delivered it.
    delivered_access: Optional[SshEndpoint] = None
    _working_data_seeded: bool = False
    #: The delivered access refused and the relay holding released.
    _access_ended: bool = False
    #: The cycle's last stage has run its compensation.
    _outstanding_checked: bool = False


# ---------------------------------------------------------------------------
# The targets, the cycle, and what the module writes nothing before
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cleanup_cycle(request):
    return request.param


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    """The run's payments target, or a blocked skip naming it."""
    return configured_payments()


@pytest.fixture(scope="module")
def real_bare_metal_target():
    if not settings.get("BARE_METAL_LANE"):
        pytest.skip("blocked: settings hold no BARE_METAL_LANE section for the bare-metal "
                    "storefront and site")
    host = target_host(settings, "bare_metal")
    assert host.access.mode == "relay", "the bare-metal qualification requires access.mode=relay"
    return host


@pytest.fixture(scope="module")
def cleanup_history() -> list[int]:
    """The UIDs each verified cycle's tenant had, across the module's cycles."""
    return []


@pytest.fixture(scope="module")
def cleanup_preflight(real_bare_metal_target, cleanup_cycle, cleanup_history):
    """The working-data probe's established policy, read before the cycle's
    purchase, and before any hold in the first cycle.

    Without the target's ``cleanup_qualification`` the normal cycle runs its
    purchase with the working-data stages skipped, and the refusal cycle,
    which proves nothing without them, skips whole, naming the field. The
    refusal cycle also skips, as any stage missing a prerequisite does, when
    the normal cycle's cleanup was not verified: observation 5 is then
    unproven, never failed by inference from observation 4.
    """
    if real_bare_metal_target.cleanup_qualification is None:
        if cleanup_cycle == "refusal":
            pytest.skip(f"{CLEANUP_FIELD} is not set, so the refusal cycle has no fixture to plant")
        return None
    if cleanup_cycle == "refusal" and len(cleanup_history) != 1:
        pytest.skip("Prerequisite not satisfied: the normal cycle's cleanup was not verified, "
                    "and the successor needs its consumed UID")
    # Finish the temporary local SSH context before the purchase, so an
    # authentication, sudo or host-key failure triggers none.
    with ssh_session(host_key=real_bare_metal_target.ssh_host_public_key) as session:
        observer = WorkingDataQualification(real_bare_metal_target, session, [], cleanup_cycle)
        observer.preflight()
        return observer.state


@pytest.fixture(scope="module")
def real_bare_metal_execution(real_bare_metal_target, provisioning_client, cleanup_preflight):
    executor = bare_metal_executor_is_real(provisioning_client.get_system_status().execution)
    configured_relay(provisioning_client, real_bare_metal_target)
    return executor


@pytest.fixture(scope="module")
def cleanup_qualification(real_bare_metal_target, cleanup_preflight, cleanup_cycle,
                          cleanup_history, ssh):
    if cleanup_preflight is None:
        return None
    return WorkingDataQualification(real_bare_metal_target, ssh, cleanup_history,
                                    cleanup_cycle, state=dict(cleanup_preflight))


@pytest.fixture(scope="module", autouse=True)
def _ensure_provisioning_host_registered():
    """Registers nothing: the only host this module writes is the target's,
    registered with its connection at 00f1."""


@pytest.fixture(scope="module")
def deal_state(cleanup_cycle) -> BareMetalQualificationState:
    return BareMetalQualificationState()


@pytest.fixture(scope="module")
def ssh(real_bare_metal_target):
    with ssh_session(host_key=real_bare_metal_target.ssh_host_public_key) as session:
        yield session


@pytest.fixture(scope="module")
def buyer_key(ssh, cleanup_cycle):
    """A key of the cycle's own, so the successor's is fresh."""
    return ssh.new_key("buyer-" + cleanup_cycle)


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory, cleanup_cycle) -> BuyerCli:
    return bare_metal_purchase_cli(
        payments_config, buyer_cli_binary,
        tmp_path_factory.mktemp(f"bare_metal_qualification_{cleanup_cycle}_buyer"),
    )


@pytest.fixture(scope="module")
def purchase_registry(purchase_cli):
    client = purchase_registry_client(purchase_cli)
    yield client
    client.close()


@pytest.fixture(scope="module")
def deal_driver(
    real_bare_metal_target, buyer_key, purchase_cli, purchase_registry,
    bare_metal_site_operator, bare_metal_site_capacity, provisioning_client,
    storefront_admin_client, site_capacity,
) -> RealBareMetalPurchaseDriver:
    return RealBareMetalPurchaseDriver(
        site_operator=bare_metal_site_operator, site_capacity_admin=bare_metal_site_capacity,
        provisioning_client=provisioning_client, storefront_admin_client=storefront_admin_client,
        fulfillment=purchase_fulfillment_transport(purchase_cli), site_capacity=site_capacity,
        buyer_config={"ssh_public_key": buyer_key.public_line},
        site_id=lane_setting("site_id"), target=real_bare_metal_target,
        jobs=JobWatch(provisioning_client),
        purchase_registry=purchase_registry, storefront_pins=_pinned("storefront"),
        config_path=str(purchase_cli.config_path),
    )


def _outstanding_steps(purchase_cli, deal_driver: RealBareMetalPurchaseDriver,
                       deal_state: BareMetalQualificationState, cleanup_qualification) -> list:
    """Whatever the cycle's purchase left: a command still running, a planted
    fixture, an unrefunded payment, a tenancy still on the machine.

    A cycle whose delivered access the module confirmed ended needs nothing.
    A planted foreign descendant still in place is repaired first, as the
    refusal stage would, so the reclaim can complete. A purchase the buyer
    approved is refunded as the seller, retried while its receipt may still
    verify, unless the buyer's teardown had been asked for, and its tenancy
    ended through its lease's own reclaim; what cannot be refunded or ended
    fails naming its negotiation and transaction.
    """
    compensation = PurchaseCompensation(
        run_dir=purchase_cli.run_dir, status=deal_driver.purchase_status,
        refund=seller_refund,
        release=lambda negotiation_id, status: deal_driver.end_purchase(
            negotiation_id, status, deal_state),
        retryable=refund_may_clear,
    )
    return [
        ("stop the purchase's market bare-metal buy",
         lambda: deal_state.purchase_run and deal_state.purchase_run.terminate()),
        ("repair a planted fixture still in place",
         lambda: cleanup_qualification and cleanup_qualification.repair_planted_fixture()),
        *compensation.steps(settled=deal_state._access_ended,
                            ending_begun=deal_state._buyer_teardown_requested),
    ]


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: RealBareMetalPurchaseDriver,
                     deal_state: BareMetalQualificationState, cleanup_qualification):
    """The cycle's compensation where its last stage, which runs it, did not run.

    pytest finalizes a cycle's fixtures as the next cycle's first stage sets
    up, so a failure here is reported against that stage; the cycle's own last
    stage runs the compensation first, so a failure there is its own cycle's.
    """
    yield
    if not deal_state._outstanding_checked:
        run_cleanup(_outstanding_steps(purchase_cli, deal_driver, deal_state,
                                       cleanup_qualification))


# ===========================================================================
# Readiness, supply and the published listing
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


class TestStage00e1_BareMetalExecutionIsReal:
    def test_00e1_bare_metal_execution_is_real(
        self, real_bare_metal_execution, deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "_provisioning_healthy", "_contract_pins_agree")
        assert not real_bare_metal_execution.mocked
        deal_state._provisioning_execution_confirmed = True
        log.info("[00e1] Bare-metal execution is real: %s", real_bare_metal_execution)


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00f2_RegisteredHostIsTheTarget:
    def test_00f2_the_registered_host_is_the_target(
        self, deal_driver: RealBareMetalPurchaseDriver, deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "_supply_seeded")
        deal_driver.assert_registered_as_target()
        deal_state._target_host_confirmed = True
        log.info("[00f2] Host %s registered as the target, machine %s",
                 deal_driver.target.host_id, deal_driver.physical_host_id)


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


class TestStage03a_PublicationDryRun:
    def test_03a_preview_allows_publication_or_an_existing_listing(
        self, storefront_admin_client, deal_driver: RealBareMetalPurchaseDriver,
        deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "_target_host_confirmed", "_registry_reachable")
        report = dry_run_storefront(storefront_admin_client, "publication")
        assert report.get("dry_run") is True, report
        ours = [item for item in report.get("actions") or []
                if (item.get("source") or {}).get("physical_resource_id")
                == deal_driver.reserved_resource_id]
        assert not any(item.get("action") == "fail" for item in ours), report
        assert len([item for item in ours if item.get("action") == "publish"]) <= 1, report
        deal_state._publication_previewed = True
        log.info("[03a] Publication preview for resource %s: %s", deal_driver.reserved_resource_id,
                 [item.get("action") for item in ours])


class TestStage03b_PublicationPublishesOrAdopts:
    def test_03b_publish_or_adopt_the_machines_one_open_listing(
        self, storefront_admin_client, deal_driver: RealBareMetalPurchaseDriver,
        deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "_publication_previewed")
        report = advance_storefront(storefront_admin_client, "publication")
        listing = deal_driver.open_listing_for_run()
        assert not any(item.get("listing_id") == listing.listing_id and item.get("action") == "fail"
                       for item in report.get("actions") or []), report
        deal_state.seller_listing_id = str(listing.listing_id)
        deal_state.listing_published = True
        log.info("[03b] Listing %s open for machine %s", listing.listing_id,
                 deal_driver.physical_host_id)


# ===========================================================================
# The purchase
# ===========================================================================

class TestPurchase01_PayerBalanceBefore(Purchase01_PayerBalanceBefore):
    pass


class TestPurchase02_ListingDiscovered(Purchase02_ListingDiscovered):
    pass


class TestPurchase03_Bought(Purchase03_Bought):
    pass


class TestPurchase04_PurchaseCorrelated(Purchase04_PurchaseCorrelated):
    pass


class TestStage08b3_GrantJobSucceeded:
    def test_08b3_the_grant_job_ran_on_the_target_and_succeeded(
        self, deal_driver: RealBareMetalPurchaseDriver, deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "fulfillment_id")
        job = deal_driver.create_job(deal_state.fulfillment_id)
        deal_state.create_job_id = job.job_id
        deal_state._create_job_completed = True
        log.info("[08b3] Grant job %s succeeded on %s for Agreement %s", job.job_id, job.host_id,
                 deal_state.negotiation_id)


class TestPurchase05_PaymentRecordsChecked(Purchase05_PaymentRecordsChecked):
    pass


# ===========================================================================
# Delivery
# ===========================================================================

class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_PublicationClosesTheListing(BareMetalPublicationClosesListing):
    pass


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


class TestPurchase09_PurchaseRunEnded(Purchase09_PurchaseRunEnded):
    pass


class TestStage09d_TenantConnectsThroughThePinnedRelay:
    def test_09d_the_buyer_connects_as_a_nonroot_tenant(
        self, deal_driver: RealBareMetalPurchaseDriver, deal_state: BareMetalQualificationState,
        ssh, buyer_key,
    ):
        """At the pinned relay endpoint, with the machine's pinned host key,
        as the delivered tenant, which is not root."""
        require_state(deal_state, "settlement_status", "create_job_id")
        endpoint = deal_driver.delivered_access(deal_state)
        assert ssh.run(endpoint, buyer_key, "id -un").strip() == endpoint.user
        uid = int(ssh.run(endpoint, buyer_key, "id -u").strip())
        assert uid != 0, f"the delivered tenant {endpoint.user!r} is root"
        deal_state.delivered_access = endpoint
        log.info("[09d] Tenant %s (uid %s) connects at %s:%s", endpoint.user, uid,
                 endpoint.host, endpoint.port)


class TestStage09e_UnrelatedKeyRefused:
    def test_09e_an_unrelated_key_is_refused(
        self, deal_state: BareMetalQualificationState, ssh, cleanup_cycle,
    ):
        require_state(deal_state, "delivered_access")
        reason = ssh.assert_key_refused(deal_state.delivered_access,
                                        ssh.new_key("unrelated-" + cleanup_cycle))
        log.info("[09e] An unrelated key is refused at port %s: %s",
                 deal_state.delivered_access.port, reason)


class TestStage09e2_GrantAdmitted:
    def test_09e2_the_relay_admitted_the_tenancys_grant(
        self, deal_driver: RealBareMetalPurchaseDriver, provisioning_client,
        deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "delivered_access", "fulfillment_id")
        reservation, _state = deal_driver.reservation_of(deal_state.fulfillment_id)
        check_admission(deal_driver.target, provisioning_client, reservation)


class TestStage09f_WorkingDataSeeded:
    def test_09f_tenant_activity_and_working_data_seeded(
        self, cleanup_qualification, deal_driver: RealBareMetalPurchaseDriver,
        deal_state: BareMetalQualificationState, ssh, buyer_key,
    ):
        """Through the bounded probe: tenant activity and working data beside
        operator sentinels, a fresh UID for a successor, and for the refusal
        cycle the foreign descendant planted."""
        if cleanup_qualification is None:
            pytest.skip(f"{CLEANUP_FIELD} is not set, so no working data is seeded or observed")
        require_state(deal_state, "delivered_access", "fulfillment_id", "create_job_id")
        reservation, _state = deal_driver.reservation_of(deal_state.fulfillment_id)
        cleanup_qualification.seed(ssh=ssh, endpoint=deal_state.delivered_access,
                                   key=buyer_key, reservation_id=reservation)
        deal_state._working_data_seeded = True
        log.info("[09f] Working data seeded for reservation %s, tenant uid %s",
                 reservation, cleanup_qualification.state.get("uid"))


class TestStage09g_ManagementBeforeReclaim:
    def test_09g_management_connected_before_the_buyers_teardown(
        self, deal_driver: RealBareMetalPurchaseDriver, cleanup_qualification,
        deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "delivered_access")
        if cleanup_qualification is not None:
            require_state(deal_state, "_working_data_seeded")
            cleanup_qualification.heartbeat.assert_alive()
        deal_driver.assert_management_connected()
        log.info("[09g] Management of %s connected before the buyer's teardown",
                 deal_driver.target.host_id)


# ===========================================================================
# The buyer's teardown, the reclaim, and its effects
# ===========================================================================

class TestPurchase10_BuyerTeardown(Purchase10_BuyerTeardown):
    pass


class TestStage11a1_RefusedReclaimKeepsCapacity:
    #: The refusal cycle's alone.
    observations = {"refusal": ("5",)}

    def test_11a1_the_reclaim_refuses_the_planted_descendant_until_repaired(
        self, cleanup_cycle, cleanup_qualification, deal_driver: RealBareMetalPurchaseDriver,
        deal_state: BareMetalQualificationState, storefront_admin_client,
    ):
        """The reclaim job queued for retry, its error recorded and a next
        retry set, its log naming the foreign descendant, the lease
        ``releasing`` and its capacity unadvertised; then only the fixture
        repaired. The recorded error and scheduled retry, read through the
        operator's typed job API, are the actionable operator notification."""
        if cleanup_cycle != "refusal":
            pytest.skip("the normal cycle plants no foreign descendant")
        if cleanup_qualification is None:
            pytest.skip(f"{CLEANUP_FIELD} is not set, so no foreign descendant is planted")
        require_state(deal_state, "_working_data_seeded", "teardown_fulfillment_id",
                      "create_job_id")
        cleanup_qualification.observe_refusal_and_repair(
            driver=deal_driver, deal_state=deal_state,
            storefront_admin_client=storefront_admin_client,
        )


class TestStage11a3_ReclaimJobSucceeded:
    def test_11a3_the_reclaim_job_ran_on_the_target_and_succeeded(
        self, deal_driver: RealBareMetalPurchaseDriver, deal_state: BareMetalQualificationState,
    ):
        require_state(deal_state, "teardown_fulfillment_id", "create_job_id")
        job = deal_driver.teardown_job(deal_state.teardown_fulfillment_id,
                                       create_job_id=deal_state.create_job_id)
        deal_state._teardown_job_completed = True
        log.info("[11a3] Reclaim job %s succeeded on %s", job.job_id, job.host_id)


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestStage11c_DeliveredAccessEnded:
    def test_11c_access_closed_and_relay_holding_released(
        self, deal_driver: RealBareMetalPurchaseDriver, deal_state: BareMetalQualificationState,
        ssh, buyer_key,
    ):
        require_state(deal_state, "delivered_access", "_teardown_job_completed", "deal_lease")
        assert deal_state.deal_lease.refresh().get("status") == "released"
        reason = ssh.assert_refused(deal_state.delivered_access, buyer_key)
        deal_driver.assert_relay_released(deal_state.fulfillment_id, deal_state.delivered_access)
        deal_state._access_ended = True
        log.info("[11c] Lease %s released; port %s refuses the tenant's key (%s) and its relay "
                 "holding is released", deal_state.lease_id, deal_state.delivered_access.port,
                 reason)


class TestStage11d_WorkingDataAbsent:
    def test_11d_covered_data_absent_and_sentinels_unchanged(
        self, cleanup_qualification, deal_driver: RealBareMetalPurchaseDriver,
        deal_state: BareMetalQualificationState,
    ):
        if cleanup_qualification is None:
            pytest.skip(f"{CLEANUP_FIELD} is not set, so the reclaim's cleanup is unobserved")
        require_state(deal_state, "_working_data_seeded", "_access_ended")
        cleanup_qualification.verify()
        deal_driver.assert_management_connected()
        log.info("[11d] Tenant uid %s's covered data and activity absent, sentinels unchanged",
                 cleanup_qualification.state.get("uid"))


class TestStage12_NothingLeftOutstanding:
    def test_12_the_cycle_leaves_no_payment_or_tenancy_outstanding(
        self, purchase_cli, deal_driver: RealBareMetalPurchaseDriver,
        deal_state: BareMetalQualificationState, cleanup_qualification,
    ):
        """The cycle's compensation, run as its last stage: nothing for a
        purchase the cycle ended; otherwise the payment refunded and the
        tenancy ended, or the purchase named for the operator. A stage, so a
        compensation failure counts against this cycle's observation alone."""
        deal_state._outstanding_checked = True
        run_cleanup(_outstanding_steps(purchase_cli, deal_driver, deal_state,
                                       cleanup_qualification))
        log.info("[12] Nothing outstanding for Agreement %s", deal_state.negotiation_id)
