"""Observation 2: two concurrent VM purchases on the real-provisioning target's host.

The runbook's observation 2
(``docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes``),
made as an external-topology extension of the VM lane's buyer purchase
(``test_vm_payment_purchase.py``): the run's buyer, with no wallet, buys two
CPU-only guests through ``market buy`` in ``arkhai.payments.v1``, against the
payments target the run names (``PAYMENTS``) and the KVM host the
real-provisioning target names. An SSH heartbeat on the first guest runs across
the second guest's create and teardown and shows no gap over five seconds; the
host's diagnostics are read before, during and after, and its management unit
and libvirtd keep their generation (``host_generations.py``); both leases end by
back-dating and a stepped lease-watchdog cycle, never an early teardown.

The first purchase runs the shared purchase stages and the canonical deal's
stages from fulfillment onwards, each declared once, ``RealVmPurchaseDriver``
supplying VM's real part. The second runs the same definitions on its own
state and driver, from stages of this module (``run_stage``), between the
first purchase's delivery and its ending. Its own stages:

  00e1      The service executes VM jobs for real
  00f2      The registered host is the target's
  02b, 03b  The resource's one listing, created or adopted, offering Arkhai
            payments, then published
  03c       Host diagnostics, before any guest
  08b3      The first create job ran on the target and succeeded
  09a2      Capacity events stepped
  09d–09f   The first guest: the negotiated shape and no GPU passed through,
            an unrelated key refused,
            the grant admitted, the heartbeat opened, diagnostics
  09g–09p   The second purchase: bought, created, its payment and the sum of
            both, delivered with the negotiated shape and no GPU passed
            through, admitted, its lease expired, released; the
            heartbeat checked after its create and its removal, diagnostics
  10b2, 11a3, 11c, 11d  The first guest's real teardown, gone from the host
  12a, 12b  libvirtd and the management unit kept their generations

Every stage requires observation 2, and the module logs its outcome
(``helpers/qualification.py``): unproven, naming the field, without the
target's ``management_unit`` (12b skips) or, on a relayed target, its
``admission_log``. The module is in no lane. Without the payments target or
the real-provisioning target's VM host it is a blocked skip before any hold or
write. A failure after the buyer's approval refunds the payment as the seller
and ends a delivered guest through its lease's expiry, and reports by
negotiation and transaction what it cannot. The payer is funded by the
deployment, never here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pytest
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, ArkhaiPaymentsConfig
from vm_provisioning_operator import HostDiagnostics

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
    PurchaseState,
)
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.compute_deal import advance_fulfillment_to, wait_for_stage_event
from tests.e2e.roles.helpers.compute_deal_stages import (
    DURATION_HOURS,
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
    Stage10a_LeaseExpirySetup,
    Stage10b_LeaseCycleBeginsTeardown,
    Stage11a_TeardownDispatch,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.payment_compensation import PurchaseCompensation, refund_may_clear
from tests.e2e.roles.helpers.payments import buyer_payments_client, configured_payments, payment_setting
from tests.e2e.roles.helpers.qualification import check_admission, run_stage, target_host
from tests.e2e.roles.helpers.real_provisioning import JobWatch, configured_relay
from tests.e2e.roles.helpers.ssh_access import (
    SshEndpoint,
    SshHeartbeat,
    memory_within_tolerance,
    ssh_session,
)
from tests.e2e.roles.scenarios.vms.composed_listing import (
    create_or_adopt_listing,
    listing_mechanisms,
    listing_settlements,
    real_target_resource,
)
from tests.e2e.roles.scenarios.vms.conftest import (
    capacity_site_id,
    capacity_source_for,
    step_listing_reconciliation,
)
from tests.e2e.roles.scenarios.vms.host_generations import (
    DiagnosticsRead,
    libvirtd_faults,
    management_unit_faults,
)
from tests.e2e.roles.scenarios.vms.purchase_driver import vm_purchase_cli
from tests.e2e.roles.scenarios.vms.real_compute_deal_driver import (
    assert_registered_as_target,
    created_guest_name,
    vm_executor_is_real,
)
from tests.e2e.roles.scenarios.vms.real_purchase_driver import RealVmPurchaseDriver

log = logging.getLogger(__name__)

#: The runbook observation every stage of this module requires.
OBSERVATIONS = ("2",)

pytestmark = [
    # The payments target and the real-provisioning target first, then the
    # service's VM execution, so a run without either target, or against a
    # mocked service, holds and writes nothing. The holds follow, so they are
    # released after every other fixture; the lane's cleanup and the
    # purchases' compensation follow them, so they run while the holds stand.
    pytest.mark.usefixtures(
        "payments_config", "real_vm_target", "real_vm_execution",
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "purchase_cleanup",
    ),
    pytest.mark.e2e_vm_qualification,
]


@dataclass
class VmQualificationState(PurchaseState):
    """One purchase's state in the VM qualification, beside the purchase's."""

    domain_identity: str = "vms.compute"
    _target_host_confirmed: bool = False
    #: The create job this purchase's reservation ran, once it succeeded.
    create_job_id: Optional[str] = None
    #: The guest the create job reported creating.
    vm_name: Optional[str] = None
    #: Where the buyer connects, as the storefront delivered it.
    delivered_access: Optional[SshEndpoint] = None
    #: A VM list job on the host has run without naming the guest.
    _guest_absent: bool = False
    #: The first guest's SSH heartbeat, across the second guest's create and removal.
    heartbeat: Optional[SshHeartbeat] = None


# ---------------------------------------------------------------------------
# The targets, and what the module writes nothing before
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    """The run's payments target, or a blocked skip naming it."""
    config = configured_payments()
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the listing"
    return config


@pytest.fixture(scope="module")
def real_vm_target():
    return target_host(settings, "vm")


@pytest.fixture(scope="module")
def real_vm_execution(real_vm_target, provisioning_client):
    """The service's VM executor, required real, and the target's relay
    configured, before anything is written."""
    executor = vm_executor_is_real(provisioning_client.get_system_status().execution)
    configured_relay(provisioning_client, real_vm_target)
    return executor


@pytest.fixture(scope="module", autouse=True)
def _ensure_provisioning_host_registered():
    """Registers nothing: the only host this module writes is the target's,
    registered with its connection at 00f1."""


@pytest.fixture(scope="module")
def deal_state() -> VmQualificationState:
    return VmQualificationState()


@pytest.fixture(scope="module")
def second_state() -> VmQualificationState:
    return VmQualificationState()


@pytest.fixture(scope="module")
def diagnostics() -> list[DiagnosticsRead]:
    """The host's diagnostics reads, in the order the stages take them."""
    return []


@pytest.fixture(scope="module")
def ssh():
    """This run's SSH keys and known hosts, removed when the module ends."""
    with ssh_session() as session:
        yield session


@pytest.fixture(scope="module")
def buyer_key(ssh):
    return ssh.new_key("buyer-first")


@pytest.fixture(scope="module")
def second_buyer_key(ssh):
    return ssh.new_key("buyer-second")


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    return vm_purchase_cli(payments_config, buyer_cli_binary,
                           tmp_path_factory.mktemp("vm_qualification_first_buyer"))


@pytest.fixture(scope="module")
def second_purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    return vm_purchase_cli(payments_config, buyer_cli_binary,
                           tmp_path_factory.mktemp("vm_qualification_second_buyer"))


@pytest.fixture(scope="module")
def offer_resource(real_vm_target) -> dict:
    return real_target_resource(real_vm_target)


@pytest.fixture(scope="module")
def deal_driver(
    real_vm_target, buyer_key, offer_resource, provisioning_client, vm_operator_client,
    storefront_client, storefront_admin_client, storefront_service_client,
    site_capacity_admin_client, site_capacity, registry_client,
) -> RealVmPurchaseDriver:
    return RealVmPurchaseDriver(
        provisioning_client=provisioning_client,
        storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client,
        storefront_service_client=storefront_service_client,
        site_capacity_admin_client=site_capacity_admin_client,
        site_capacity=site_capacity,
        site_id=capacity_site_id(),
        vm_operator_client=vm_operator_client,
        target=real_vm_target,
        buyer_public_key=buyer_key.public_line,
        listing_shape=capacity_source_for(offer_resource)["listing_shape"],
        jobs=JobWatch(provisioning_client),
        purchase_registry=registry_client,
        seller_account=str(payment_setting("SELLER_ACCOUNT")),
        dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
    )


@pytest.fixture(scope="module")
def second_driver(deal_driver: RealVmPurchaseDriver, second_buyer_key) -> RealVmPurchaseDriver:
    return deal_driver.second_purchase(second_buyer_key.public_line)


@pytest.fixture(scope="module")
def purchase_cleanup(
    purchase_cli, second_purchase_cli, deal_driver, second_driver, storefront_seller_client,
    deal_state: VmQualificationState, second_state: VmQualificationState,
):
    """Whatever the purchases left: a ``market buy`` still running, an
    unrefunded payment, a guest still on the host.

    A purchase whose guest the module confirmed gone needs nothing. Any other
    that the buyer approved is refunded as the seller, retried while its
    receipt may still verify, unless its lease's expiry had begun ending it,
    and its guest ended through that expiry; what cannot be refunded or ended
    fails naming its negotiation and transaction. The second purchase is
    compensated first, as it began last.
    """
    yield
    steps = []
    for name, cli, state, driver in (
        ("second", second_purchase_cli, second_state, second_driver),
        ("first", purchase_cli, deal_state, deal_driver),
    ):
        steps.append((f"stop the {name} purchase's market buy",
                      lambda state=state: state.purchase_run and state.purchase_run.terminate()))
        compensation = PurchaseCompensation(
            run_dir=cli.run_dir, status=driver.purchase_status,
            refund=storefront_seller_client.refund_settlement,
            release=lambda negotiation_id, status, driver=driver, state=state: (
                driver.end_purchase(negotiation_id, status, state)),
            retryable=refund_may_clear,
        )
        steps += [(f"{label} ({name} purchase)", step)
                  for label, step in compensation.steps(
                      settled=state._guest_absent,
                      ending_begun=bool(state._termination_requested))]
    steps.append(("close the heartbeat",
                  lambda: deal_state.heartbeat is not None and deal_state.heartbeat.close()))
    run_cleanup(steps)


def _read_diagnostics(vm_operator_client, driver: RealVmPurchaseDriver, label: str,
                      *, first_guest_running: bool) -> DiagnosticsRead:
    """One host diagnostics job on the target, waited for and parsed, beside a
    check of the service's management connection."""
    driver.assert_management_connected()
    target = driver.target
    submitted = vm_operator_client.diagnose_host(target.host_id, management_unit=target.management_unit)
    job = driver.jobs.until_succeeded(submitted.job_id, describe="host diagnostics job")
    diagnostics = HostDiagnostics.from_job_result(job.result)
    management = diagnostics.management
    log.info("[%s] Diagnostics job %s: boot %s, %s guest(s); libvirtd invocation %s, "
             "%s restart(s); management %s", label, submitted.job_id, diagnostics.boot_id,
             diagnostics.running_guests, diagnostics.libvirtd.invocation_id,
             diagnostics.libvirtd.restart_count,
             "not named" if management is None
             else f"invocation {management.invocation_id}, {management.restart_count} restart(s)")
    return DiagnosticsRead(label, diagnostics, first_guest_running)


def _assert_negotiated_shape(ssh, endpoint: SshEndpoint, key, target, label: str) -> None:
    shape = ssh.probe(endpoint, key)
    sold = target.listing_shape
    log.info("[%s] %s@%s:%s (host key %s) shows %s against %s", label, endpoint.user,
             endpoint.host, endpoint.port, ssh.host_key_fingerprint(endpoint), shape, sold)
    assert shape.user == endpoint.user, (shape.user, endpoint.user)
    assert shape.vcpu_count == sold.vcpu_count, (
        f"the guest has {shape.vcpu_count} vCPUs; {sold.vcpu_count} were sold")
    assert memory_within_tolerance(shape.memory_gib, sold.ram_gb), (
        f"the guest has {shape.memory_gib:.2f} GiB of memory; {sold.ram_gb} GiB were sold")
    assert shape.root_disk_gib >= sold.disk_gb, (
        f"the guest's root disk is {shape.root_disk_gib:.2f} GiB; {sold.disk_gb} GiB were sold")
    # The listing selling no GPU proves only what was offered; the guest's own
    # PCI devices show what was delivered. A list the guest cannot read fails
    # the probe rather than reading as no GPU.
    devices = ssh.pci_devices(endpoint, key)
    gpus = [device for device in devices if device.is_gpu]
    log.info("[%s] the guest lists %d PCI device(s), %d of them a GPU", label, len(devices),
             len(gpus))
    assert not gpus, f"the guest was sold no GPU but has one passed through: {gpus}"


def _gross(state: PurchaseState) -> dict[str, int]:
    agreement = state.agreement
    return {agreement["asset"]: int(str(agreement["amount"]))}


# ===========================================================================
# Readiness and the listing
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


class TestStage00e1_VmExecutionIsReal:
    def test_00e1_provisioning_executes_vm_jobs_for_real(
        self, provisioning_client, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "_provisioning_healthy")
        executor = vm_executor_is_real(provisioning_client.get_system_status().execution)
        deal_state._provisioning_execution_confirmed = True
        log.info("[00e1] VM execution is real: %s", executor)


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00f2_RegisteredHostIsTheTarget:
    def test_00f2_the_registered_host_is_the_target(
        self, deal_driver: RealVmPurchaseDriver, real_vm_target, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "_supply_seeded")
        assert_registered_as_target(deal_driver.registered_host(), real_vm_target)
        deal_state._target_host_confirmed = True
        log.info("[00f2] Host %s registered as the target", real_vm_target.host_id)


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


class TestStage02b_ListingCreatedOrAdopted:
    def test_02b_the_resources_listing_offers_arkhai_payments(
        self, deal_driver: RealVmPurchaseDriver, storefront_seller_client,
        storefront_admin_client, offer_resource, deal_state: VmQualificationState,
    ):
        """The resource's one listing, created paused offering every ready deal
        mechanism, or adopted from another run, which must offer Arkhai
        payments (``composed_listing.py``)."""
        require_state(deal_state, "_registry_reachable", "_target_host_confirmed")
        listing, adopted = create_or_adopt_listing(
            storefront_admin_client=storefront_admin_client,
            storefront_seller_client=storefront_seller_client,
            resource=offer_resource,
            shape=deal_driver.target.listing_shape.model_dump(),
            mechanism=ARKHAI_PAYMENTS_MECHANISM,
            settlements=listing_settlements(),
            max_duration_seconds=DURATION_HOURS * 3600,
        )
        deal_state.seller_listing_id = listing.listing_id
        log.info("[02b] Listing %s %s paused, offering %s", listing.listing_id,
                 "adopted" if adopted else "created", list(listing_mechanisms(listing)))


class TestStage03b_ListingPublished:
    def test_03b_resume_publishes_the_listing(
        self, storefront_admin_client, registry_client, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "seller_listing_id")
        result = storefront_admin_client.resume_listing(deal_state.seller_listing_id)
        assert result.paused is False and result.registry_status == "published", result
        published = registry_client.get_listing(deal_state.seller_listing_id)
        assert str(published.id) == deal_state.seller_listing_id, published
        deal_state.listing_published = True
        log.info("[03b] Listing %s published", deal_state.seller_listing_id)


class TestStage03c_DiagnosticsBeforeAnyGuest:
    def test_03c_the_hosts_diagnostics_before_the_purchases(
        self, vm_operator_client, deal_driver: RealVmPurchaseDriver, diagnostics,
        deal_state: VmQualificationState,
    ):
        require_state(deal_state, "_target_host_confirmed")
        diagnostics.append(_read_diagnostics(
            vm_operator_client, deal_driver, "03c before", first_guest_running=False,
        ))


# ===========================================================================
# The first purchase
# ===========================================================================

class TestPurchase01_PayerBalanceBefore(Purchase01_PayerBalanceBefore):
    pass


class TestPurchase02_ListingDiscovered(Purchase02_ListingDiscovered):
    pass


class TestPurchase03_Bought(Purchase03_Bought):
    pass


class TestPurchase04_PurchaseCorrelated(Purchase04_PurchaseCorrelated):
    pass


class TestStage08b3_CreateJobSucceeded:
    def test_08b3_the_first_create_job_ran_on_the_target_and_succeeded(
        self, deal_driver: RealVmPurchaseDriver, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "fulfillment_id")
        job = deal_driver.create_job(deal_state.fulfillment_id)
        deal_state.create_job_id = job.job_id
        deal_state.vm_name = created_guest_name(job)
        deal_state._create_job_completed = True
        log.info("[08b3] Create job %s succeeded on %s: guest %s for Agreement %s",
                 job.job_id, job.host_id, deal_state.vm_name, deal_state.negotiation_id)


class TestPurchase05_PaymentRecordsChecked(Purchase05_PaymentRecordsChecked):
    pass


class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_CapacityEventCycle:
    def test_09a2_capacity_events_dry_run_then_advance(
        self, storefront_admin_client, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "seller_listing_id", "provisioning_result_injected")
        pending, applied = step_listing_reconciliation(storefront_admin_client)
        deal_state._listing_reconciled = True
        log.info("[09a2] Capacity events stepped: %s pending, %s applied", pending, applied)


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


class TestPurchase09_PurchaseRunEnded(Purchase09_PurchaseRunEnded):
    pass


class TestStage09d_FirstGuestHasTheNegotiatedShape:
    def test_09d_the_buyer_reaches_the_first_guests_negotiated_shape(
        self, deal_driver: RealVmPurchaseDriver, ssh, buyer_key,
        deal_state: VmQualificationState,
    ):
        require_state(deal_state, "settlement_status", "create_job_id")
        endpoint = deal_driver.delivered_access(deal_state)
        _assert_negotiated_shape(ssh, endpoint, buyer_key, deal_driver.target, "09d")
        deal_state.delivered_access = endpoint


class TestStage09e_UnrelatedKeyRefused:
    def test_09e_an_unrelated_key_is_refused(self, ssh, deal_state: VmQualificationState):
        require_state(deal_state, "delivered_access")
        reason = ssh.assert_key_refused(deal_state.delivered_access, ssh.new_key("unrelated"))
        log.info("[09e] An unrelated key is refused: %s", reason)


class TestStage09e2_FirstGrantAdmitted:
    def test_09e2_the_relay_admitted_the_first_guests_grant(
        self, deal_driver: RealVmPurchaseDriver, provisioning_client,
        deal_state: VmQualificationState,
    ):
        require_state(deal_state, "delivered_access", "fulfillment_id")
        reservation, _state = deal_driver.reservation_of(deal_state.fulfillment_id)
        check_admission(deal_driver.target, provisioning_client, reservation)


class TestStage09f_HeartbeatOpened:
    def test_09f_keep_a_session_open_on_the_first_guest(
        self, ssh, buyer_key, vm_operator_client, deal_driver: RealVmPurchaseDriver,
        diagnostics, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "delivered_access")
        deal_state.heartbeat = ssh.heartbeat(deal_state.delivered_access, buyer_key)
        deal_state.heartbeat.assert_alive()
        diagnostics.append(_read_diagnostics(
            vm_operator_client, deal_driver, "09f first guest running", first_guest_running=True,
        ))


# ===========================================================================
# The second purchase, while the first guest runs
# ===========================================================================

class TestStage09g_SecondPurchaseBought:
    def test_09g_the_buyer_buys_a_second_guest(
        self, payments_config, second_purchase_cli, second_driver: RealVmPurchaseDriver,
        deal_state: VmQualificationState, second_state: VmQualificationState,
    ):
        """The purchase stages' own definitions, on the second purchase's state:
        its balance, the listing still open beside the first guest, the buy."""
        require_state(deal_state, "heartbeat", "seller_listing_id", "listing_published",
                      "_provisioning_storefront_ok")
        second_state.seller_listing_id = deal_state.seller_listing_id
        second_state.listing_published = True
        second_state._provisioning_storefront_ok = True
        run_stage(Purchase01_PayerBalanceBefore, payments_config=payments_config,
                  deal_state=second_state)
        run_stage(Purchase02_ListingDiscovered, deal_driver=second_driver, deal_state=second_state)
        run_stage(Purchase03_Bought, purchase_cli=second_purchase_cli, deal_driver=second_driver,
                  deal_state=second_state)


class TestStage09h_SecondPurchaseCreated:
    def test_09h_the_second_purchase_correlates_and_its_create_job_succeeds(
        self, provisioning_client, second_driver: RealVmPurchaseDriver,
        second_state: VmQualificationState,
    ):
        require_state(second_state, "purchase_run")
        run_stage(Purchase04_PurchaseCorrelated, provisioning_client=provisioning_client,
                  deal_driver=second_driver, deal_state=second_state)
        job = second_driver.create_job(second_state.fulfillment_id)
        second_state.create_job_id = job.job_id
        second_state.vm_name = created_guest_name(job)
        second_state._create_job_completed = True
        log.info("[09h] Second create job %s succeeded on %s: guest %s for Agreement %s",
                 job.job_id, job.host_id, second_state.vm_name, second_state.negotiation_id)


class TestStage09i_SecondPaymentAndTheSum:
    def test_09i_the_second_payment_and_the_payers_debits_over_both(
        self, payments_config, deal_state: VmQualificationState,
        second_state: VmQualificationState,
    ):
        """The second transaction's records, then the payer's available balance
        since before the first purchase, against the two purchases' debits.

        The sum holds only while nothing else spends from the payer account,
        which is dedicated to the run: a topology guarantee, logged beside the
        result."""
        require_state(deal_state, "agreement", "payer_available_before")
        require_state(second_state, "agreement", "settlement_id")
        run_stage(Purchase05_PaymentRecordsChecked, payments_config=payments_config,
                  deal_state=second_state)
        payer = str(payment_setting("BUYER_ACCOUNT"))
        with buyer_payments_client(payments_config, payer) as client:
            after = {asset: int(amount.root)
                     for asset, amount in client.get_balance(payer).available.items()}
        debits: dict[str, int] = {}
        for state in (deal_state, second_state):
            for asset, amount in _gross(state).items():
                debits[asset] = debits.get(asset, 0) + amount
        before = deal_state.payer_available_before
        dropped = {asset: before.get(asset, 0) - after.get(asset, 0)
                   for asset in sorted(set(before) | set(after))
                   if before.get(asset, 0) != after.get(asset, 0)}
        log.info("[09i] Payer %s is assumed dedicated to this run (a topology guarantee); "
                 "available fell by %s; transactions %s and %s debited %s", payer, dropped,
                 deal_state.settlement_id, second_state.settlement_id, debits)
        assert dropped == debits, (
            f"payer {payer}'s available balance fell by {dropped} since before the first "
            f"purchase; its transactions {deal_state.settlement_id} and "
            f"{second_state.settlement_id} debited {debits}"
        )


class TestStage09j_SecondGuestDelivered:
    def test_09j_the_second_guest_is_delivered(
        self, provisioning_client, storefront_admin_client,
        second_driver: RealVmPurchaseDriver, second_state: VmQualificationState,
    ):
        """Convergence, settlement readiness, the lease and the command's end,
        through the canonical deal's definitions, on the second purchase."""
        require_state(second_state, "fulfillment_id", "_create_job_completed")
        run_stage(Stage09a_FulfillmentConvergesToActive,
                  provisioning_client=provisioning_client, deal_state=second_state)
        pending, applied = step_listing_reconciliation(storefront_admin_client)
        second_state._listing_reconciled = True
        log.info("[09j] Capacity events stepped: %s pending, %s applied", pending, applied)
        run_stage(Stage09b_SettlementReadyAndCredentials,
                  storefront_admin_client=storefront_admin_client,
                  deal_driver=second_driver, deal_state=second_state)
        run_stage(Stage09c_LeaseRecorded, deal_driver=second_driver, deal_state=second_state)
        run_stage(Purchase09_PurchaseRunEnded, deal_driver=second_driver, deal_state=second_state)


class TestStage09k_SecondGuestAccessibleAndAdmitted:
    def test_09k_the_second_guest_has_its_own_access_and_shape(
        self, ssh, second_buyer_key, provisioning_client, second_driver: RealVmPurchaseDriver,
        deal_state: VmQualificationState, second_state: VmQualificationState,
    ):
        require_state(deal_state, "delivered_access")
        require_state(second_state, "settlement_status", "fulfillment_id")
        endpoint = second_driver.delivered_access(second_state)
        assert endpoint.port != deal_state.delivered_access.port, (
            "the two guests were delivered the same buyer port"
        )
        _assert_negotiated_shape(ssh, endpoint, second_buyer_key, second_driver.target, "09k")
        reason = ssh.assert_key_refused(endpoint, ssh.new_key("unrelated-second"))
        log.info("[09k] An unrelated key is refused for the second guest: %s", reason)
        second_state.delivered_access = endpoint
        reservation, _state = second_driver.reservation_of(second_state.fulfillment_id)
        check_admission(second_driver.target, provisioning_client, reservation)


class TestStage09l_HeartbeatSurvivedSecondCreate:
    def test_09l_the_first_session_survived_the_second_create(
        self, vm_operator_client, deal_driver: RealVmPurchaseDriver, diagnostics,
        deal_state: VmQualificationState, second_state: VmQualificationState,
    ):
        require_state(deal_state, "heartbeat")
        require_state(second_state, "delivered_access")
        deal_state.heartbeat.assert_alive()
        log.info("[09l] First session survived the second create; longest gap %.3fs",
                 deal_state.heartbeat.longest_gap)
        diagnostics.append(_read_diagnostics(
            vm_operator_client, deal_driver, "09l second guest created", first_guest_running=True,
        ))


class TestStage09m_SecondLeaseExpires:
    def test_09m_the_second_lease_expires_and_its_teardown_dispatches(
        self, provisioning_client, storefront_admin_client, second_state: VmQualificationState,
    ):
        """Back-dated, one stepped watchdog cycle, and its teardown dispatched:
        the canonical deal's expiry stages, on the second purchase."""
        require_state(second_state, "deal_lease", "lease_id")
        run_stage(Stage10a_LeaseExpirySetup, provisioning_client=provisioning_client,
                  deal_state=second_state)
        run_stage(Stage10b_LeaseCycleBeginsTeardown, provisioning_client=provisioning_client,
                  storefront_admin_client=storefront_admin_client, deal_state=second_state)
        run_stage(Stage11a_TeardownDispatch, provisioning_client=provisioning_client,
                  storefront_admin_client=storefront_admin_client, deal_state=second_state)


class TestStage09n_SecondTeardownJobSucceeded:
    def test_09n_the_second_teardown_job_ran_on_the_target_and_succeeded(
        self, second_driver: RealVmPurchaseDriver, second_state: VmQualificationState,
    ):
        require_state(second_state, "teardown_fulfillment_id", "create_job_id")
        job = second_driver.teardown_job(
            second_state.teardown_fulfillment_id, create_job_id=second_state.create_job_id,
        )
        second_state._teardown_job_completed = True
        log.info("[09n] Second teardown job %s succeeded on %s", job.job_id, job.host_id)


class TestStage09o_SecondGuestReleased:
    def test_09o_the_second_guest_is_released_gone_and_unreachable(
        self, provisioning_client, storefront_admin_client, ssh, second_buyer_key,
        second_driver: RealVmPurchaseDriver, second_state: VmQualificationState,
    ):
        """The second guest's teardown completed and its lease released by a
        stepped lease cycle, its shape reservable again, the guest gone from
        the host and its access and relay holding ended.

        Not the canonical deal's ``Stage11b``, which requires the whole
        resource free: the first guest still holds its own slice.
        """
        require_state(second_state, "_teardown_job_completed", "vm_name", "delivered_access",
                      "deal_lease", "settlement_ref")
        lease = second_state.deal_lease
        sync_stage, sync_event = lease.released_stage_event
        existing = storefront_admin_client.get_events(limit=500, stage=sync_stage)
        since = max((event.id for event in existing.events), default=0)
        advance_fulfillment_to(provisioning_client, second_state.teardown_fulfillment_id, "torn_down")
        summary = provisioning_client.check_leases()
        assert summary.released >= 1, summary
        assert lease.refresh().get("status") == "released", lease.refresh()
        wait_for_stage_event(storefront_admin_client, sync_stage, sync_event,
                             since_id=since, timeout=10.0)
        reserved = second_driver.reserve_guest_shape(
            storefront_admin_client, listing_id=second_state.seller_listing_id,
            escrow_uid=f"{second_state.settlement_ref}-reuse",
        )
        assert reserved.capacity_reservation_id, reserved
        second_driver.release_reserved(reserved)
        second_driver.assert_guest_absent(second_state.vm_name)
        ssh.assert_refused(second_state.delivered_access, second_buyer_key)
        second_driver.assert_relay_released(second_state.fulfillment_id,
                                            second_state.delivered_access)
        second_state._guest_absent = True
        log.info("[09o] Second guest %s gone; Agreement %s released",
                 second_state.vm_name, second_state.negotiation_id)


class TestStage09p_HeartbeatSurvivedSecondRemoval:
    def test_09p_the_first_session_survived_the_second_removal(
        self, vm_operator_client, deal_driver: RealVmPurchaseDriver, diagnostics,
        deal_state: VmQualificationState, second_state: VmQualificationState,
    ):
        require_state(deal_state, "heartbeat")
        require_state(second_state, "_guest_absent")
        deal_state.heartbeat.assert_alive()
        log.info("[09p] First session survived the second removal; longest gap %.3fs",
                 deal_state.heartbeat.longest_gap)
        deal_state.heartbeat.close()
        diagnostics.append(_read_diagnostics(
            vm_operator_client, deal_driver, "09p second guest removed", first_guest_running=True,
        ))


# ===========================================================================
# The first guest's lease expiry, the real teardown, and its effects
# ===========================================================================

class TestStage10a_LeaseExpirySetup(Stage10a_LeaseExpirySetup):
    pass


class TestStage10b_LeaseCycleBeginsTeardown(Stage10b_LeaseCycleBeginsTeardown):
    pass


class TestStage10b2_ManagementBeforeTeardown:
    def test_10b2_management_still_connects_before_the_first_teardown(
        self, deal_driver: RealVmPurchaseDriver, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "teardown_fulfillment_id")
        deal_driver.assert_management_connected()
        log.info("[10b2] Management of %s connected before tearing down fulfillment %s",
                 deal_driver.target.host_id, deal_state.teardown_fulfillment_id)


class TestStage11a_TeardownDispatch(Stage11a_TeardownDispatch):
    pass


class TestStage11a3_TeardownJobSucceeded:
    def test_11a3_the_first_teardown_job_ran_on_the_target_and_succeeded(
        self, deal_driver: RealVmPurchaseDriver, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "teardown_fulfillment_id", "create_job_id")
        job = deal_driver.teardown_job(
            deal_state.teardown_fulfillment_id, create_job_id=deal_state.create_job_id,
        )
        deal_state._teardown_job_completed = True
        log.info("[11a3] Teardown job %s succeeded on %s", job.job_id, job.host_id)


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestStage11c_FirstGuestGoneFromHost:
    def test_11c_the_host_no_longer_lists_the_first_guest(
        self, deal_driver: RealVmPurchaseDriver, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "vm_name", "_teardown_job_completed")
        guests = deal_driver.assert_guest_absent(deal_state.vm_name)
        deal_state._guest_absent = True
        log.info("[11c] Guest %s gone from the host, which lists %s", deal_state.vm_name, guests)


class TestStage11d_FirstAccessEnded:
    def test_11d_the_first_guests_access_no_longer_connects(
        self, ssh, buyer_key, vm_operator_client, deal_driver: RealVmPurchaseDriver,
        diagnostics, deal_state: VmQualificationState,
    ):
        require_state(deal_state, "delivered_access", "_teardown_job_completed")
        reason = ssh.assert_refused(deal_state.delivered_access, buyer_key)
        deal_driver.assert_relay_released(deal_state.fulfillment_id, deal_state.delivered_access)
        log.info("[11d] The first guest's access no longer connects: %s", reason)
        diagnostics.append(_read_diagnostics(
            vm_operator_client, deal_driver, "11d after", first_guest_running=False,
        ))


# ===========================================================================
# The host's services across the reads
# ===========================================================================

#: The diagnostics reads the criterion compares: before, three while the first
#: guest runs, and after.
EXPECTED_READS = 5


def _all_reads(reads: list[DiagnosticsRead]) -> list[DiagnosticsRead]:
    """The module's diagnostics reads, skipping where an earlier stage took
    fewer, as a missing prerequisite does."""
    if len(reads) != EXPECTED_READS:
        pytest.skip(f"Prerequisite not satisfied: {len(reads)} of {EXPECTED_READS} diagnostics "
                    f"reads were taken ({[read.label for read in reads]}). An earlier stage "
                    "likely failed.")
    return reads


class TestStage12a_LibvirtdKeptItsGeneration:
    def test_12a_libvirtd_added_no_restart_and_kept_its_generation(self, diagnostics):
        reads = _all_reads(diagnostics)
        faults = libvirtd_faults(reads)
        assert not faults, "libvirtd.service: " + "; ".join(faults)
        log.info("[12a] libvirtd.service across %s: invocations %s, restarts %s",
                 [read.label for read in reads],
                 [read.diagnostics.libvirtd.invocation_id for read in reads],
                 [read.diagnostics.libvirtd.restart_count for read in reads])


class TestStage12b_ManagementUnitKeptItsGeneration:
    def test_12b_the_management_unit_kept_one_active_generation(
        self, real_vm_target, diagnostics,
    ):
        unit = real_vm_target.management_unit
        if unit is None:
            pytest.skip(f"{SECTION}.hosts.vm.management_unit is not set, so the management "
                        "unit's generation is unread")
        reads = _all_reads(diagnostics)
        faults = management_unit_faults(reads, unit)
        assert not faults, f"{unit}: " + "; ".join(faults)
        log.info("[12b] %s kept invocation %s, active, %s restart(s), across %s", unit,
                 reads[0].diagnostics.management.invocation_id,
                 reads[0].diagnostics.management.restart_count, [read.label for read in reads])
