"""The canonical compute deal, provisioned for real on an operator-provided KVM host.

VM's run of the compute family's canonical deal against a provisioning service
outside its mock profile. It proves what the mock lanes cannot: the service's VM
execution is not mocked; the create and teardown jobs ran on the target host and
succeeded; the buyer, with the key negotiated for this run, reaches the guest at
the delivered access as the delivered user and finds the negotiated vCPUs,
memory within tolerance, and at least the negotiated disk; an unrelated key is
refused for that user; and once the lease expires and its capacity is released,
a VM list job on the host no longer names the guest and the delivered access no
longer connects. It claims nothing about the guest's other credentials, which a
batch-mode client never tries.

The target is the ``REAL_PROVISIONING_TARGET`` settings section
(``e2e_harness.real_provisioning_target``), loaded from ``config-real-provisioning-target.yml`` when
the run selects the ``real-provisioning-target`` profile. Without it every stage skips,
naming the profile and file, and nothing is written to the stack: the target is
validated, and the service's VM execution found real, before the module's holds
are taken or anything is registered. The module is in no lane.

Every shared stage runs here unchanged; the mock-lane stages do not. Where a
mock lane holds a job at a gate and releases it, this lane waits for the real
job instead, found through the fulfillment's capacity reservation. Its own
stages:

  00e1 The service executes VM jobs for real (in place of the mock lanes' 00e)
  00f2 The registered host is the target's, connection and all
  02b  Create the GPU-less listing paused, offering every ready mechanism, or
       adopt the one an earlier run left, which must offer Alkahest
  03b  Resume it into publication at the registry
  08a2 The settlement preview chose the target host, so 08b may settle
  08b3 The create job ran on the target host and succeeded; its guest recorded
  09a2 Step capacity events; a second guest shape remains sellable
  09c3 The lease names the create job found
  09d  The buyer reaches the negotiated shape with the delivered access
  09e  An unrelated key is refused for the delivered user
  09f–09n A second deal creates and removes a guest while the first session stays open
  10b2 Management remains reachable before the first guest's teardown
  11a3 The teardown job ran on the target host and succeeded
  11c  A VM list job on the host no longer names the guest
  11d  The delivered access no longer connects

A run that fails after the storefront accepted its settlement, before the guest
is confirmed gone, has its lease truncated by the module's recovery so the
provisioning service tears the guest down through its own lifecycle; where that
cannot be confirmed, or the dispatched fulfillment cannot be found, the run
fails naming what an operator needs to recover it.
The module never releases reservations fleet-wide: the host's capacity must not
return to the market while its guest may still run.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pytest
from market_alkahest.plans import ALKAHEST_MECHANISM

from e2e_harness.real_provisioning_target import TargetNotConfigured, load_real_provisioning_target
from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal_stages import (
    DEAL_TOKEN,
    BUYER_INITIAL_PRICE,
    BUYER_MAX_PRICE,
    ESCROW_TTL_SECONDS,
    E2E_LEASE_EXPIRY_BACKDATE,
    alkahest_opening,
    DURATION_HOURS,
    Stage00_LifecycleHeld,
    Stage00a_StorefrontHealth,
    Stage00b_RegistryReachable,
    Stage00c_ProvisioningHealth,
    Stage00c2_ProvisioningContractPins,
    Stage00d_NegotiationStrategy,
    Stage00f1_ExecutorHostRegistry,
    Stage00g_AlkahestConfigured,
    Stage00h_ProvisioningStorefrontLink,
    Stage04a_PrimaryRegistryPublish,
    Stage05a_EvaluateNegotiate,
    Stage05b_NegotiationStartsAndVisible,
    Stage06b_ForceAcceptAndTerminal,
    Stage07_OnChainEscrow,
    Stage07b_VerifyEscrow,
    Stage08a_EvaluateSettle,
    Stage08b_SettlementSubmittedAndJobQueued,
    Stage09a_FulfillmentConvergesToActive,
    Stage09b_SettlementReadyAndCredentials,
    Stage09c1_LateSettlementKeepsTheWindow,
    Stage09c_LeaseRecorded,
    Stage10a_LeaseExpirySetup,
    Stage10b_LeaseCycleBeginsTeardown,
    Stage11a_TeardownDispatch,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.compute_deal import (
    advance_fulfillment_to, latest_stage_event_id, wait_for_stage_event,
)
from tests.e2e.roles.helpers.escrow import create_buyer_escrow
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.ssh_access import memory_within_tolerance, ssh_session
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
from tests.e2e.roles.scenarios.vms.real_compute_deal_driver import (
    JobWatch,
    RealVmComputeDealDriver,
    RealVmDealState,
    assert_registered_as_target,
    created_guest_name,
    configured_relay,
    vm_executor_is_real,
)

log = logging.getLogger(__name__)

pytestmark = [
    # The target and the service's VM execution are checked first, so a run
    # without its profile, with a malformed target, or against a mocked service
    # holds and registers nothing. The holds follow, so they are released after
    # every other fixture, and the recovery after them, so it runs while they
    # stand.
    pytest.mark.usefixtures(
        "real_vm_execution",
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "recover_failed_run",
    ),
    pytest.mark.e2e_vm_real_provisioning,
]

# ---------------------------------------------------------------------------
# The target, and what the module writes nothing before
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_vm_target():
    """The validated target, or a skip naming the profile and file it needs.

    A section that is present and invalid fails here, naming the field.
    """
    target = load_real_provisioning_target(settings)
    if isinstance(target, TargetNotConfigured):
        pytest.skip(target.reason)
    host = target.host_for("vm")
    if host is None:
        pytest.skip("REAL_PROVISIONING_TARGET.hosts holds no vm host")
    return host


@pytest.fixture(scope="module")
def real_vm_execution(real_vm_target, provisioning_client):
    """The service's VM executor, required real before anything is written.

    A fixture, not only a stage, because the module's holds pause the shared
    services when they are set up, before the first stage runs.
    """
    executor = vm_executor_is_real(provisioning_client.get_system_status().execution)
    configured_relay(provisioning_client, real_vm_target)
    return executor


@pytest.fixture(scope="module", autouse=True)
def _ensure_provisioning_host_registered():
    """Registers nothing: the only host this module writes is the target's,
    registered with its connection at 00f1."""


@pytest.fixture(scope="module")
def deal_state() -> RealVmDealState:
    return RealVmDealState()


@pytest.fixture(scope="module")
def ssh():
    """This run's SSH keys and known hosts, removed when the module ends."""
    with ssh_session() as session:
        yield session


@pytest.fixture(scope="module")
def buyer_key(ssh):
    """The key the buyer negotiates and connects with, generated for this run."""
    return ssh.new_key("buyer")


@pytest.fixture(scope="module")
def offer_resource(real_vm_target) -> dict:
    """The target's explicit guest listing shape, and no GPU."""
    return real_target_resource(real_vm_target)


@pytest.fixture(scope="module")
def deal_driver(
    real_vm_target,
    buyer_key,
    offer_resource,
    provisioning_client,
    vm_operator_client,
    storefront_client,
    storefront_admin_client,
    storefront_service_client,
    site_capacity_admin_client,
    site_capacity,
) -> RealVmComputeDealDriver:
    return RealVmComputeDealDriver(
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
    )


@pytest.fixture(scope="module")
def recover_failed_run(deal_driver, deal_state: RealVmDealState):
    """Tear down the guest a failed run left on the host, or fail naming it.

    Acts once the module has run, when settlement was submitted and the lane
    did not confirm its guest gone. Keyed to submission rather than to the
    fulfillment 08b records, because 08b records it only after its own
    assertions, and a create is already running once settle dispatches it.
    """
    yield
    first_pending = deal_state._settle_preflight_passed and not deal_state._guest_absent
    second_pending = deal_state._second_settlement_submitted and not deal_state._second_guest_absent
    if first_pending or second_pending:
        deal_driver.recover_both(deal_state)


# ===========================================================================
# Phase 0 — readiness
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


class TestStage00d_NegotiationStrategy(Stage00d_NegotiationStrategy):
    pass


class TestStage00e1_VmExecutionIsReal:
    def test_00e1_provisioning_executes_vm_jobs_for_real(
        self, provisioning_client, deal_state: RealVmDealState
    ):
        """GET /api/v1/system/status → the `vm` executor is not mocked.

        Read per offering mode rather than as `execution.mocked`, which is
        false whenever any composed executor is real. The module's
        `real_vm_execution` fixture made the same check before anything was
        written; this records it in the run's results and the deal's state.
        """
        require_state(deal_state, "_provisioning_healthy")
        executor = vm_executor_is_real(provisioning_client.get_system_status().execution)
        deal_state._provisioning_execution_confirmed = True
        log.info("[00e1] VM execution is real: %s", executor)


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00f2_RegisteredHostIsTheTarget:
    def test_00f2_the_registered_host_is_the_target(
        self, deal_driver: RealVmComputeDealDriver, real_vm_target,
        deal_state: RealVmDealState,
    ):
        """The host the service reaches is the target's, read back after 00f1.

        A host an earlier run left behind has its connection replaced at 00f1;
        this is the check that the replacement holds before any deal stage.
        """
        require_state(deal_state, "_supply_seeded")
        assert_registered_as_target(deal_driver.registered_host(), real_vm_target)
        deal_state._target_host_confirmed = True
        log.info("[00f2] Host %s registered as the target", real_vm_target.host_id)


class TestStage00g_AlkahestConfigured(Stage00g_AlkahestConfigured):
    pass


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


# ===========================================================================
# Phases 2 and 3 — the GPU-less listing
# ===========================================================================

class TestStage02b_ListingCreated:
    def test_02b_create_the_listing_paused(
        self, deal_driver: RealVmComputeDealDriver, storefront_seller_client,
        storefront_admin_client, offer_resource, deal_state: RealVmDealState,
    ):
        """Create the resource's listing paused, offering every mechanism the
        storefront reports ready, or adopt the one another run against this
        stack left (``composed_listing.py``).

        Its capacity source states the GPU-less shape the pool states, derived
        from the same resource, so the storefront finds the listing's shape and
        its source's in agreement. That source backs one listing for good, so
        an earlier run, or a module dealing on the resource by another
        mechanism, leaves the listing this run adopts: the only one on the
        resource, open, of the target's shape, offering Alkahest. Any other
        fails naming the listings and their options.
        """
        require_state(deal_state, "_registry_reachable", "_target_host_confirmed")
        listing, adopted = create_or_adopt_listing(
            storefront_admin_client=storefront_admin_client,
            storefront_seller_client=storefront_seller_client,
            resource=offer_resource,
            shape=deal_driver.target.listing_shape.model_dump(),
            mechanism=ALKAHEST_MECHANISM,
            settlements=listing_settlements(),
            max_duration_seconds=DURATION_HOURS * 3600,
        )
        deal_state.seller_listing_id = listing.listing_id
        log.info("[02b] Listing %s %s paused, offering %s", listing.listing_id,
                 "adopted" if adopted else "created", list(listing_mechanisms(listing)))


class TestStage03b_ListingPublished:
    def test_03b_resume_publishes_the_listing(
        self, storefront_admin_client, registry_client, deal_state: RealVmDealState
    ):
        """Resume the listing; the registry holds it once resume answers.

        Resume publishes before it answers, so the registry read needs no wait.
        """
        require_state(deal_state, "seller_listing_id")
        result = storefront_admin_client.resume_listing(deal_state.seller_listing_id)
        assert result.paused is False and result.registry_status == "published", result
        listed = registry_client.list_listings(status="open", limit=200)
        assert deal_state.seller_listing_id in {o.id for o in listed.listings}, (
            f"listing {deal_state.seller_listing_id} absent from the registry after "
            "resume reported it published"
        )
        deal_state.listing_published = True
        log.info("[03b] Listing %s published", deal_state.seller_listing_id)


# ===========================================================================
# Phases 4 to 8 — publication seen, negotiation, escrow, settlement
# ===========================================================================

class TestStage04a_PrimaryRegistryPublish(Stage04a_PrimaryRegistryPublish):
    pass


class TestStage05a_EvaluateNegotiate(Stage05a_EvaluateNegotiate):
    pass


class TestStage05b_NegotiationStartsAndVisible(Stage05b_NegotiationStartsAndVisible):
    pass


class TestStage06b_ForceAcceptAndTerminal(Stage06b_ForceAcceptAndTerminal):
    pass


class TestStage07_OnChainEscrow(Stage07_OnChainEscrow):
    pass


class TestStage07b_VerifyEscrow(Stage07b_VerifyEscrow):
    pass


class TestStage08a_EvaluateSettle(Stage08a_EvaluateSettle):
    pass


class TestStage08a2_SettlementPreviewChoseTheTarget:
    def test_08a2_the_settlement_preview_chose_the_target_host(
        self, real_vm_target, deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState
    ):
        """The lane's last check before settlement: the preview chose the target.

        Another host registered on the same stack could otherwise take the
        deal, and a real create would run where nobody looks for it. 08b
        submits settlement only once this passes.
        """
        require_state(deal_state, "_evaluate_settle_passed")
        chosen = deal_state.expected_host_id
        assert chosen == real_vm_target.host_id, (
            f"the settlement preview chose host {chosen!r}, not the target "
            f"{real_vm_target.host_id!r}; settlement is not submitted"
        )
        deal_driver.assert_management_connected()
        deal_state._settle_preflight_passed = True
        log.info("[08a2] Settlement preview chose the target host %s", chosen)


class TestStage08b_SettlementSubmittedAndJobQueued(Stage08b_SettlementSubmittedAndJobQueued):
    pass


# ===========================================================================
# Phase 9 — the real create, delivery, and access
# ===========================================================================

class TestStage08b3_CreateJobSucceeded:
    def test_08b3_the_create_job_ran_on_the_target_and_succeeded(
        self, deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState
    ):
        """Wait for the deal's create job where a mock lane releases its gate.

        The job is the one its reservation ran, on the target host, read to a
        terminal status within the bound. Convergence is held, so the
        fulfillment stays dispatching however soon the job finishes, until
        09a advances it.
        """
        require_state(deal_state, "fulfillment_id")
        job = deal_driver.create_job(deal_state.fulfillment_id)
        deal_state.create_job_id = job.job_id
        deal_state.vm_name = created_guest_name(job)
        deal_state._create_job_completed = True
        log.info(
            "[08b3] Create job %s succeeded on %s: guest %s",
            job.job_id, job.host_id, deal_state.vm_name,
        )


class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_CapacityEventCycle:
    def test_09a2_capacity_events_dry_run_then_advance(
        self, storefront_admin_client, deal_state: RealVmDealState
    ):
        """Apply capacity events; the first guest leaves a second shape sellable."""
        require_state(deal_state, "seller_listing_id", "provisioning_result_injected")
        pending, applied = step_listing_reconciliation(storefront_admin_client)
        deal_state._listing_reconciled = True
        log.info("[09a2] Capacity events stepped: %s pending, %s applied", pending, applied)


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


class TestStage09c1_LateSettlementKeepsTheWindow(Stage09c1_LateSettlementKeepsTheWindow):
    pass


class TestStage09c3_LeaseNamesTheCreateJob:
    def test_09c3_the_lease_names_the_create_job_found(self, deal_state: RealVmDealState):
        """The lease's create job is the one 08b3 found through the reservation."""
        require_state(deal_state, "deal_lease", "create_job_id")
        lease = deal_state.deal_lease.refresh()
        assert lease.get("create_job_id") == deal_state.create_job_id, (
            f"the lease names create job {lease.get('create_job_id')!r}; the "
            f"reservation ran {deal_state.create_job_id!r}. Lease: {lease}"
        )


class TestStage09d_BuyerReachesTheNegotiatedShape:
    def test_09d_the_buyer_reaches_the_negotiated_shape(
        self, deal_driver: RealVmComputeDealDriver, ssh, buyer_key, real_vm_target,
        deal_state: RealVmDealState,
    ):
        """Connect with the delivered access and the negotiated key, and read
        the guest's user, vCPUs, memory, and root disk.

        Retried within the helper's bound while the new guest finishes its
        first boot and cloud-init's reboot. The guest's host key is trusted on
        first contact for this run only, and its fingerprint logged.
        """
        require_state(deal_state, "settlement_status", "create_job_id")
        endpoint = deal_driver.delivered_access(deal_state)
        shape = ssh.probe(endpoint, buyer_key)
        capacity = real_vm_target.listing_shape
        log.info(
            "[09d] %s@%s:%s (host key %s) shows %s against %s",
            endpoint.user, endpoint.host, endpoint.port,
            ssh.host_key_fingerprint(endpoint), shape, capacity,
        )
        assert shape.user == endpoint.user, (
            f"connected as {shape.user!r}, not the delivered user {endpoint.user!r}"
        )
        assert shape.vcpu_count == capacity.vcpu_count, (
            f"the guest has {shape.vcpu_count} vCPUs; {capacity.vcpu_count} were sold"
        )
        assert memory_within_tolerance(shape.memory_gib, capacity.ram_gb), (
            f"the guest has {shape.memory_gib:.2f} GiB of memory; "
            f"{capacity.ram_gb} GiB were sold"
        )
        assert shape.root_disk_gib >= capacity.disk_gb, (
            f"the guest's root disk is {shape.root_disk_gib:.2f} GiB; "
            f"{capacity.disk_gb} GiB were sold"
        )
        deal_state.delivered_access = endpoint


class TestStage09e_UnrelatedKeyRefused:
    def test_09e_an_unrelated_key_is_refused(self, ssh, deal_state: RealVmDealState):
        """The delivered user's host denies a key the buyer did not negotiate.

        That the account admits the negotiated key and not an arbitrary one,
        not that the key is the only way in.
        """
        require_state(deal_state, "delivered_access")
        reason = ssh.assert_key_refused(deal_state.delivered_access, ssh.new_key("unrelated"))
        log.info("[09e] An unrelated key is refused: %s", reason)


class TestStage09f_HeartbeatOpened:
    def test_09f_keep_one_session_open(self, ssh, buyer_key, deal_state: RealVmDealState):
        require_state(deal_state, "delivered_access")
        deal_state.heartbeat = ssh.heartbeat(deal_state.delivered_access, buyer_key)


class TestStage09g_SecondDealAccepted:
    def test_09g_negotiate_second_guest(
        self, storefront_client, storefront_admin_client, registry_client,
        deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState,
    ):
        require_state(deal_state, "heartbeat", "seller_listing_id", "listing_published")
        deal_state.heartbeat.assert_alive()
        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status == "open", "the first guest left no sellable second shape"
        option, escrow = alkahest_opening(registry_client.get_listing(deal_state.seller_listing_id))
        deal_state._second_escrow_expiration_unix = int(time.time()) + ESCROW_TTL_SECONDS
        opened = storefront_client.negotiate_new(
            listing_id=deal_state.seller_listing_id,
            initial_amount=BUYER_INITIAL_PRICE,
            escrow_expiration_unix=deal_state._second_escrow_expiration_unix,
            provision_terms=deal_driver.provision_terms(),
            token=DEAL_TOKEN["contract_address"], chain_name=escrow["chain_name"],
            escrow_address=escrow["escrow_address"], literal_fields=escrow["literal_fields"],
            demands=[escrow["demand"]],
            settlement_selection=deal_driver.opening_selection(option, deal_state._second_escrow_expiration_unix),
        )
        negotiation = opened.get("negotiation_id") if isinstance(opened, dict) else None
        assert negotiation, opened
        accepted = storefront_admin_client.force_accept_negotiation(
            deal_state.seller_listing_id, negotiation,
            amount=(BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2,
        )
        assert accepted.action == "accept", accepted
        detail = storefront_admin_client.get_negotiation(deal_state.seller_listing_id, negotiation)
        assert detail.terminal_state == "success", detail
        deal_state.second_negotiation_id = negotiation


class TestStage09h_SecondEscrowCreated:
    def test_09h_create_second_escrow(
        self, buyer_config, seller_wallet, deal_state: RealVmDealState,
    ):
        require_state(deal_state, "second_negotiation_id", "_second_escrow_expiration_unix", "_alkahest_configured")
        deal_state.second_escrow_uid = create_buyer_escrow(
            buyer_private_key=buyer_config["private_key"], seller_wallet_address=seller_wallet,
            agreed_amount=(BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2,
            duration_seconds=DURATION_HOURS * 3600,
            token_contract_address=DEAL_TOKEN["contract_address"], rpc_url=buyer_config["rpc_url"],
            expiration_unix=deal_state._second_escrow_expiration_unix,
        )


class TestStage09i_SecondSettlementSubmitted:
    def test_09i_preview_target_and_settle_second_guest(
        self, storefront_client, storefront_admin_client, buyer_config,
        deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState,
    ):
        require_state(deal_state, "second_negotiation_id", "second_escrow_uid", "seller_listing_id")
        preview = storefront_admin_client.evaluate_settle(
            deal_state.second_escrow_uid, listing_id=deal_state.seller_listing_id,
            negotiation_id=deal_state.second_negotiation_id,
            **deal_driver.evaluate_settle_arguments(),
        )
        assert preview.get("would_submit") is True, preview
        assert deal_driver.check_evaluate_settle(preview) == deal_driver.target.host_id, preview
        deal_driver.assert_management_connected()
        since = latest_stage_event_id(storefront_admin_client, negotiation_id=deal_state.second_negotiation_id)
        # Record submission intent before crossing the network: recovery must
        # find accepted work even if the client never receives the response.
        deal_state._second_settlement_submitted = True
        settled = storefront_client.settle_evm(
            deal_state.second_escrow_uid, negotiation_id=deal_state.second_negotiation_id,
            buyer_evm_address=buyer_config["wallet_address"],
        )
        second = deal_driver.second_deal_state(deal_state)
        deal_state.second_fulfillment_id = deal_driver.settle_dispatched(settled, second, events_since=since)


class TestStage09j_SecondGuestAccessible:
    def test_09j_second_guest_has_its_own_access(
        self, storefront_admin_client, provisioning_client, ssh, buyer_key,
        deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState,
    ):
        require_state(deal_state, "second_fulfillment_id", "second_escrow_uid", "delivered_access", "_second_settlement_submitted")
        created = deal_driver.create_job(deal_state.second_fulfillment_id)
        deal_state.second_create_job_id = created.job_id
        deal_state.second_vm_name = created_guest_name(created)
        advance_fulfillment_to(provisioning_client, deal_state.second_fulfillment_id, "active")
        ready = storefront_admin_client.wait_for_settlement(deal_state.second_escrow_uid, timeout=60)
        assert ready.ready and ready.status == "ready", ready
        second = deal_driver.second_deal_state(deal_state)
        deal_driver.assert_delivery(second)
        endpoint = deal_driver.delivered_access(second)
        assert endpoint.port != deal_state.delivered_access.port, "two guests received the same buyer port"
        assert ssh.run(endpoint, buyer_key, "id -un").strip() == endpoint.user
        deal_state.second_access = endpoint


class TestStage09k_HeartbeatSurvivedCreate:
    def test_09k_first_session_survived_second_create(self, deal_state: RealVmDealState):
        require_state(deal_state, "heartbeat", "second_access")
        deal_state.heartbeat.assert_alive()
        log.info("First session survived second create; longest gap %.3fs", deal_state.heartbeat.longest_gap)
        deal_state._second_create_preserved_session = True


class TestStage09l_SecondLeaseCutShort:
    def test_09l_expire_only_the_second_lease(
        self, provisioning_client, deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState,
    ):
        require_state(deal_state, "second_fulfillment_id", "second_create_job_id", "_second_create_preserved_session")
        deal_driver.assert_management_connected()
        reservation, _state = deal_driver.reservation_of(deal_state.second_fulfillment_id)
        end = datetime.now(timezone.utc) - E2E_LEASE_EXPIRY_BACKDATE
        assert deal_driver.site_capacity.truncate_lease(reservation, end.isoformat().replace("+00:00", "Z")) is not None
        provisioning_client.check_leases()
        lease = provisioning_client.get_lease(reservation)
        assert lease.release_job_id, lease
        deal_state.second_teardown_fulfillment_id = lease.release_job_id
        advance_fulfillment_to(provisioning_client, lease.release_job_id, "tearing_down")


class TestStage09m_SecondGuestReleased:
    def test_09m_second_guest_capacity_and_port_released(
        self, provisioning_client, storefront_admin_client, ssh, buyer_key,
        deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState,
    ):
        require_state(deal_state, "second_teardown_fulfillment_id", "second_create_job_id",
                      "second_vm_name", "second_access", "second_fulfillment_id", "seller_listing_id", "second_escrow_uid")
        deal_driver.teardown_job(deal_state.second_teardown_fulfillment_id, create_job_id=deal_state.second_create_job_id)
        sync_stage, sync_event = deal_driver.lease_view(deal_driver.second_deal_state(deal_state)).released_stage_event
        existing = storefront_admin_client.get_events(limit=500, stage=sync_stage)
        since = max((event.id for event in existing.events), default=0)
        advance_fulfillment_to(provisioning_client, deal_state.second_teardown_fulfillment_id, "torn_down")
        provisioning_client.check_leases()
        wait_for_stage_event(storefront_admin_client, sync_stage, sync_event, since_id=since, timeout=10)
        reservation, _state = deal_driver.reservation_of(deal_state.second_fulfillment_id)
        assert provisioning_client.get_lease(reservation).status == "released"
        deal_driver.assert_guest_absent(deal_state.second_vm_name)
        ssh.assert_refused(deal_state.second_access, buyer_key)
        deal_driver.assert_relay_released(deal_state.second_fulfillment_id, deal_state.second_access)
        # Reserve only the returned guest shape: the first guest still owns its
        # slice, so asking for the whole host would incorrectly report failure.
        capacity = storefront_admin_client.admin_reserve_capacity(
            required_attributes={"resource_id": deal_driver.reserved_resource_id,
                                 "dimensions": deal_driver.target.listing_shape.model_dump()},
            listing_id=deal_state.seller_listing_id,
            escrow_uid=f"{deal_state.second_escrow_uid}-reuse",
        )
        assert capacity.capacity_reservation_id, capacity
        deal_driver.release_reserved(capacity)
        deal_state._second_guest_absent = True


class TestStage09n_HeartbeatSurvivedRemoval:
    def test_09n_first_session_survived_second_removal(self, deal_state: RealVmDealState):
        require_state(deal_state, "heartbeat", "_second_guest_absent")
        deal_state.heartbeat.assert_alive()
        log.info("First session survived second removal; longest gap %.3fs", deal_state.heartbeat.longest_gap)
        deal_state.heartbeat.close()
        deal_state._second_removal_preserved_session = True


# ===========================================================================
# Phases 10 and 11 — lease expiry, the real teardown, and its effects
# ===========================================================================

class TestStage10a_LeaseExpirySetup(Stage10a_LeaseExpirySetup):
    pass


class TestStage10b_LeaseCycleBeginsTeardown(Stage10b_LeaseCycleBeginsTeardown):
    pass


class TestStage10b2_ManagementBeforeTeardown:
    def test_10b2_management_still_connects_before_first_teardown(
        self, deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState,
    ):
        require_state(deal_state, "teardown_fulfillment_id", "_second_removal_preserved_session")
        deal_driver.assert_management_connected()


class TestStage11a_TeardownDispatch(Stage11a_TeardownDispatch):
    pass


class TestStage11a3_TeardownJobSucceeded:
    def test_11a3_the_teardown_job_ran_on_the_target_and_succeeded(
        self, deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState
    ):
        """Wait for the deal's teardown job where a mock lane releases its gate.

        The one job the reservation ran besides its create, on the target host.
        """
        require_state(deal_state, "teardown_fulfillment_id", "create_job_id")
        job = deal_driver.teardown_job(
            deal_state.teardown_fulfillment_id, create_job_id=deal_state.create_job_id
        )
        deal_state._teardown_job_completed = True
        log.info("[11a3] Teardown job %s succeeded on %s", job.job_id, job.host_id)


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestStage11c_GuestGoneFromHost:
    def test_11c_the_host_no_longer_lists_the_guest(
        self, deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState
    ):
        """A VM list job on the host succeeds without naming the guest."""
        require_state(deal_state, "vm_name", "_teardown_job_completed")
        guests = deal_driver.assert_guest_absent(deal_state.vm_name)
        deal_state._guest_absent = True
        log.info("[11c] Guest %s gone from the host, which lists %s", deal_state.vm_name, guests)


class TestStage11d_DeliveredAccessEnded:
    def test_11d_the_delivered_access_no_longer_connects(
        self, ssh, buyer_key, deal_driver: RealVmComputeDealDriver, deal_state: RealVmDealState
    ):
        """The delivered access with the negotiated key fails within its bound.

        That access ended, not that the guest is gone, which 11c shows; so it
        does not wait on 11c's result.
        """
        require_state(deal_state, "delivered_access", "_teardown_job_completed")
        reason = ssh.assert_refused(deal_state.delivered_access, buyer_key)
        deal_driver.assert_relay_released(deal_state.fulfillment_id, deal_state.delivered_access)
        log.info("[11d] The delivered access no longer connects: %s", reason)
