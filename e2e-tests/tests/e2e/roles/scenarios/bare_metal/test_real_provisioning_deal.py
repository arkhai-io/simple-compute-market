"""Canonical whole-host deal through real grant/reclaim jobs and pinned relay SSH.

This opt-in module writes nothing before target, executor and relay validation.
It adopts the declaration's published listing and recovers only its own lease.
"""
from __future__ import annotations

import pytest

from e2e_harness.real_provisioning_target import TargetNotConfigured, load_real_provisioning_target
from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import advance_storefront, dry_run_storefront
from tests.e2e.roles.helpers.compute_deal_stages import (
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
    Stage09c_LeaseRecorded,
    Stage10a_LeaseExpirySetup,
    Stage10b_LeaseCycleBeginsTeardown,
    Stage11a_TeardownDispatch,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.real_provisioning import JobWatch, configured_relay
from tests.e2e.roles.helpers.ssh_access import ssh_session
from tests.e2e.roles.scenarios.bare_metal.conftest import buyer_wallet_config, lane_setting
from tests.e2e.roles.scenarios.bare_metal.publication_stages import (
    BareMetalPublicationClosesListing, BareMetalEvidencePublished,
)
from tests.e2e.roles.scenarios.bare_metal.working_data_qualification import (
    WorkingDataQualification, qualification_cycles, qualification_requested,
)
from tests.e2e.roles.scenarios.bare_metal.real_compute_deal_driver import (
    RealBareMetalComputeDealDriver, RealBareMetalDealState, bare_metal_executor_is_real,
)

pytestmark = [
    pytest.mark.usefixtures(
        "real_bare_metal_execution", "storefront_loops_held", "fulfillment_convergence_held",
        "lease_watchdog_held", "cleanup_qualification", "recover_failed_run",
    ),
    pytest.mark.e2e_bare_metal_real_provisioning,
    pytest.mark.e2e_bare_metal_bounded_cleanup,
]


def pytest_generate_tests(metafunc):
    if "cleanup_cycle" not in metafunc.fixturenames:
        return
    target = load_real_provisioning_target(settings)
    host = None if isinstance(target, TargetNotConfigured) else target.host_for("bare_metal")
    required = qualification_requested(metafunc.config.option.markexpr or "")
    cycles = qualification_cycles(host, required=required)
    metafunc.parametrize("cleanup_cycle", cycles, scope="module", indirect=True)


@pytest.fixture(scope="module")
def cleanup_cycle(request):
    return request.param


@pytest.fixture(scope="module")
def cleanup_history():
    return []


@pytest.fixture(scope="module")
def cleanup_preflight(real_bare_metal_target, cleanup_cycle, cleanup_history):
    if cleanup_cycle == "baseline":
        return None
    if cleanup_cycle == "refusal":
        assert len(cleanup_history) == 1, "successor purchase requires independently verified predecessor cleanup"
    # Finish the temporary local SSH context before taking any service hold.
    # Authentication, sudo and host-key failures cannot trigger a purchase.
    with ssh_session(host_key=real_bare_metal_target.ssh_host_public_key) as session:
        observer = WorkingDataQualification(real_bare_metal_target, session, [], cleanup_cycle)
        observer.preflight()
        return observer.state


@pytest.fixture(scope="module")
def cleanup_qualification(real_bare_metal_target, cleanup_preflight, cleanup_cycle,
                          cleanup_history, ssh):
    if cleanup_cycle == "baseline":
        return None
    return WorkingDataQualification(real_bare_metal_target, ssh, cleanup_history,
                                    cleanup_cycle, state=dict(cleanup_preflight))


@pytest.fixture(scope="module")
def real_bare_metal_target():
    target = load_real_provisioning_target(settings)
    if isinstance(target, TargetNotConfigured):
        pytest.skip(target.reason)
    host = target.host_for("bare_metal")
    if host is None:
        pytest.skip("REAL_PROVISIONING_TARGET.hosts holds no bare_metal host; select real-provisioning-target profile")
    assert host.access.mode == "relay", "real bare-metal scenario requires access.mode=relay"
    return host


@pytest.fixture(scope="module")
def real_bare_metal_execution(real_bare_metal_target, provisioning_client, cleanup_preflight):
    executor = bare_metal_executor_is_real(provisioning_client.get_system_status().execution)
    configured_relay(provisioning_client, real_bare_metal_target)
    return executor


@pytest.fixture(scope="module", autouse=True)
def _ensure_provisioning_host_registered():
    """The real module registers only its target, after validation, at its supply stage."""


@pytest.fixture(scope="module")
def deal_state(cleanup_cycle):
    return RealBareMetalDealState()


@pytest.fixture(scope="module")
def ssh(real_bare_metal_target):
    with ssh_session(host_key=real_bare_metal_target.ssh_host_public_key) as session:
        yield session


@pytest.fixture(scope="module")
def buyer_key(ssh, cleanup_cycle):
    return ssh.new_key("buyer-" + cleanup_cycle)


@pytest.fixture(scope="module")
def buyer_config(buyer_key):
    return buyer_wallet_config(buyer_key.public_line)


@pytest.fixture(scope="module")
def deal_driver(real_bare_metal_target, bare_metal_site_operator, bare_metal_site_capacity,
                provisioning_client, storefront_admin_client, buyer_fulfillment, site_capacity, buyer_config):
    return RealBareMetalComputeDealDriver(
        site_operator=bare_metal_site_operator, site_capacity_admin=bare_metal_site_capacity,
        provisioning_client=provisioning_client, storefront_admin_client=storefront_admin_client,
        fulfillment=buyer_fulfillment, site_capacity=site_capacity, buyer_config=buyer_config,
        site_id=lane_setting("site_id"), target=real_bare_metal_target, jobs=JobWatch(provisioning_client),
    )


@pytest.fixture(scope="module")
def recover_failed_run(deal_driver, deal_state):
    yield
    if deal_state._settle_preflight_passed and not deal_state._access_ended:
        deal_driver.tear_down_after_failure(deal_state)


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


class TestStage00e1_BareMetalExecutionIsReal:
    def test_00e1_bare_metal_execution_is_real(self, real_bare_metal_execution, deal_state):
        require_state(deal_state, "_provisioning_healthy", "_contract_pins_agree")
        assert not real_bare_metal_execution.mocked
        deal_state._provisioning_execution_confirmed = True


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00f2_RegisteredHostIsTheTarget:
    def test_00f2_registered_host_matches_target(self, deal_driver, deal_state):
        require_state(deal_state, "_supply_seeded")
        deal_driver.assert_registered_as_target()
        deal_state._target_host_confirmed = True


class TestStage00g_AlkahestConfigured(Stage00g_AlkahestConfigured):
    pass


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


class TestStage03a_PublicationDryRun:
    def test_03a_preview_allows_publication_or_an_existing_listing(self, storefront_admin_client, deal_driver, deal_state):
        require_state(deal_state, "_target_host_confirmed", "_registry_reachable")
        report = dry_run_storefront(storefront_admin_client, "publication")
        assert report.get("dry_run") is True, report
        ours = [item for item in report.get("actions") or []
                if (item.get("source") or {}).get("physical_resource_id") == deal_driver.reserved_resource_id]
        assert not any(item.get("action") == "fail" for item in ours), report
        assert len([item for item in ours if item.get("action") == "publish"]) <= 1, report
        deal_state._publication_previewed = True


class TestStage03b_PublicationStepPublishes:
    def test_03b_publish_or_adopt_one_open_listing(self, storefront_admin_client, deal_driver, deal_state):
        require_state(deal_state, "_publication_previewed")
        report = advance_storefront(storefront_admin_client, "publication")
        listing = deal_driver.open_listing_for_run()
        assert not any(item.get("listing_id") == listing.listing_id and item.get("action") == "fail"
                       for item in report.get("actions") or []), report
        deal_state.seller_listing_id = str(listing.listing_id)
        deal_state.listing_published = True


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
    def test_08a2_preview_selected_target(self, deal_driver, deal_state):
        require_state(deal_state, "_evaluate_settle_passed")
        assert deal_state._evaluate_settle_host_id == deal_driver.target.host_id, (
            "settlement preview selected another host; settlement is not submitted"
        )
        deal_driver.assert_management_connected()
        deal_state._settle_preflight_passed = True


class TestStage08b_SettlementSubmittedAndJobQueued(Stage08b_SettlementSubmittedAndJobQueued):
    pass


class TestStage08b3_GrantJobSucceeded:
    def test_08b3_grant_job_succeeded_on_target(self, deal_driver, deal_state):
        require_state(deal_state, "fulfillment_id")
        job = deal_driver.create_job(deal_state.fulfillment_id)
        deal_state.create_job_id = job.job_id
        deal_state._create_job_completed = True


class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_PublicationClosesTheListing(BareMetalPublicationClosesListing):
    pass


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09bb_EvidencePublishedForTheFulfilledEscrow(BareMetalEvidencePublished):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


class TestStage09c3_LeaseNamesTheGrantJob:
    def test_09c3_lease_names_the_observed_grant(self, deal_state):
        require_state(deal_state, "deal_lease", "create_job_id")
        assert deal_state.deal_lease.refresh().get("create_job_id") == deal_state.create_job_id


class TestStage09d_BuyerConnectsWithPinnedHostKey:
    def test_09d_buyer_connects_as_delivered_tenant(self, deal_driver, deal_state, ssh, buyer_key):
        require_state(deal_state, "settlement_status", "create_job_id")
        endpoint = deal_driver.delivered_access(deal_state)
        assert ssh.run(endpoint, buyer_key, "id -un").strip() == endpoint.user
        deal_state.delivered_access = endpoint


class TestStage09e_UnrelatedKeyRefused:
    def test_09e_unrelated_key_is_refused(self, deal_state, ssh, cleanup_cycle):
        require_state(deal_state, "delivered_access")
        ssh.assert_key_refused(deal_state.delivered_access, ssh.new_key("unrelated-" + cleanup_cycle))


class TestStage09f_BoundedWorkingDataSeeded:
    def test_09f_seed_bounded_working_data(self, cleanup_qualification, deal_driver,
                                         deal_state, ssh, buyer_key):
        if cleanup_qualification is None:
            pytest.skip("bounded cleanup qualification was not requested")
        require_state(deal_state, "delivered_access", "fulfillment_id", "create_job_id")
        reservation, _state = deal_driver.reservation_of(deal_state.fulfillment_id)
        cleanup_qualification.seed(ssh=ssh, endpoint=deal_state.delivered_access,
                                   key=buyer_key, reservation_id=reservation)
        deal_state._working_data_seeded = True


class TestStage10a_LeaseExpirySetup(Stage10a_LeaseExpirySetup):
    pass


class TestStage10b_LeaseCycleBeginsTeardown(Stage10b_LeaseCycleBeginsTeardown):
    pass


class TestStage10b2_ManagementBeforeReclaim:
    def test_10b2_management_connected_before_reclaim(self, deal_driver, deal_state, cleanup_qualification):
        require_state(deal_state, "teardown_fulfillment_id")
        if cleanup_qualification is not None:
            require_state(deal_state, "_working_data_seeded")
            cleanup_qualification.heartbeat.assert_alive()
        deal_driver.assert_management_connected()


class TestStage11a_TeardownDispatch(Stage11a_TeardownDispatch):
    pass


class TestStage11a2_RefusedCleanupKeepsCapacity:
    def test_11a2_refusal_and_fixture_only_repair(self, cleanup_qualification,
                                               deal_driver, deal_state,
                                               storefront_admin_client):
        if cleanup_qualification is None:
            pytest.skip("bounded cleanup qualification was not requested")
        require_state(deal_state, "_working_data_seeded", "teardown_fulfillment_id", "create_job_id")
        cleanup_qualification.observe_refusal_and_repair(
            driver=deal_driver, deal_state=deal_state,
            storefront_admin_client=storefront_admin_client,
        )


class TestStage11a3_ReclaimJobSucceeded:
    def test_11a3_reclaim_succeeded_on_target(self, deal_driver, deal_state):
        require_state(deal_state, "teardown_fulfillment_id", "create_job_id")
        deal_driver.teardown_job(deal_state.teardown_fulfillment_id, create_job_id=deal_state.create_job_id)
        deal_state._teardown_job_completed = True


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestStage11c_DeliveredAccessEnded:
    def test_11c_released_access_is_closed_and_relay_holding_released(self, deal_driver, deal_state, ssh, buyer_key):
        require_state(deal_state, "delivered_access", "_teardown_job_completed", "deal_lease")
        assert deal_state.deal_lease.refresh().get("status") == "released"
        ssh.assert_refused(deal_state.delivered_access, buyer_key)
        deal_driver.assert_relay_released(deal_state.fulfillment_id, deal_state.delivered_access)
        deal_state._access_ended = True


class TestStage11d_BoundedWorkingDataAbsent:
    def test_11d_independent_cleanup_observations(self, cleanup_qualification,
                                               deal_driver, deal_state):
        if cleanup_qualification is None:
            pytest.skip("bounded cleanup qualification was not requested")
        require_state(deal_state, "_working_data_seeded", "_access_ended")
        cleanup_qualification.verify()
        deal_driver.assert_management_connected()
