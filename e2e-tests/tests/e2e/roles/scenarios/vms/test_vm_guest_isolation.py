"""VM guest isolation, proven on the real-provisioning target's KVM host.

An external-topology extension of the real VM deal
(``test_real_provisioning_deal.py``): every one of its stages runs here as it
runs there, on its fixtures, driver and recovery, so the two deals, the
first guest's heartbeat and the teardown are its own. Inside the window in
which both guests run and the first holds its heartbeat, after ``09k`` and
before ``09l``, this module adds its own stages, each declaring the
observations it requires (``guest_isolation.py`` judges what the probes
report):

  09k1      Each guest's address and MAC, from a probe in each
  09k2      The host's libvirt version and UFW state, through the operator route
  09k3      O1  ARP, ICMP and TCP from the first guest to the second refused,
                directly and through the gateway
  09k4      O2  The first guest's ARP claim of the second's address dropped,
                the second's buyer still reaching it, each guest's filter
                parameters in its live definition
  09k5      O3  DHCP and DNS answered; the host's port 22 refused by the policy
  09k6      O4  169.254.169.254 refused by the policy
  09k7      O5  The refused private destination refused, the listed one admitted
                and seen leaving the host
  09k8      O6  The buyer's session comes from a private address, as the guest
                sees it; a VM create masquerades a forwarded buyer connection,
                so a guest reached that way sees only the host's address, and
                the stage skips naming the route it lacks
  09k9-12   O7  libvirtd restarted, then UFW reloaded: both jumps first and
                O3 to O5 again after each
  09k13     O8  The first guest planted unconverged, then converged by the host
                kit's command: its port isolated, its saved definition carrying
                both, its heartbeat's longest gap at most five seconds, and the
                probes of the second guest refused again
  09k14     O9  The filter the fixture detached live bound live again

Every host-side stage reaches the host only through the operator route the VM
target's ``guest_isolation`` section names, and skips naming it when the
target has none; O5's stages skip naming ``private_destinations`` when it names
none. The module logs each observation as made, failed or unproven once its
last stage has reported (``helpers/qualification.py``). It runs in no lane,
and without the real-provisioning target every stage is a blocked skip before
any hold or write. The policy's counters are per rule, so the run's two guests
are expected alone on the host, which the controlled target guarantees and the
run states beside the host's libvirt version.
"""

from __future__ import annotations

import logging

import pytest

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.qualification import target_host
from tests.e2e.roles.helpers.ssh_access import ssh_session
from tests.e2e.roles.scenarios.vms import test_real_provisioning_deal as real_deal
# The shared scenario's fixtures, found by name in this module, so the deals,
# their recovery and their teardown are the shared scenario's own. Its target
# fixture is replaced below by one whose absence is a blocked skip.
from tests.e2e.roles.scenarios.vms.test_real_provisioning_deal import (  # noqa: F401
    _ensure_provisioning_host_registered,
    buyer_key,
    deal_driver,
    deal_state,
    offer_resource,
    real_vm_execution,
    recover_failed_run,
    ssh,
)
from tests.e2e.roles.scenarios.vms.guest_isolation import (
    BRIDGE,
    DESTINATION_PORT,
    GATEWAY,
    HOST_PORT,
    MAX_GAP_SECONDS,
    METADATA,
    PRIVATE_SOURCE_ROUTE,
    IsolationProbes,
    IsolationState,
    claim_faults,
    converged_faults,
    deal_tenant_passwords,
    filter_faults,
    guest_to_guest_faults,
    host_service_faults,
    jump_faults,
    live_restoration,
    metadata_faults,
    operator_route,
    parse_rules,
    planted_faults,
    private_buyer_skip,
    private_destination_faults,
    private_destinations,
)

log = logging.getLogger(__name__)

#: The observations this module makes, as its docstring lists them.
OBSERVATIONS = ("O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8", "O9")
#: The observations a stage reaching the host through the operator route
#: serves; every one but O1 and O6, which the guests alone show.
HOST_SIDE = ("O2", "O3", "O4", "O5", "O7", "O8", "O9")

pytestmark = [
    # As the shared scenario's: the target and the service's VM execution are
    # checked first, so a run without its profile, with a malformed target, or
    # against a mocked service holds and registers nothing; the recovery
    # follows the holds, so it runs while they stand.
    pytest.mark.usefixtures(
        "real_vm_execution",
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "recover_failed_run",
    ),
    pytest.mark.e2e_vm_guest_isolation,
]


@pytest.fixture(scope="module")
def real_vm_target():
    """The target's VM host, or a blocked skip naming what is missing."""
    return target_host(settings, "vm")


@pytest.fixture(scope="module")
def operator_ssh(real_vm_target):
    """The operator route's own SSH session. The route reaches the VM host's
    own sshd, so it is pinned to the host's management key where the target
    states one; otherwise the key it first presents is trusted for this run."""
    with ssh_session(host_key=real_vm_target.ssh_host_public_key) as session:
        yield session


@pytest.fixture(scope="module")
def probes(real_vm_target, operator_ssh, ssh, buyer_key, deal_driver, deal_state) -> IsolationProbes:
    """The probes' routes; a guest probe gets root with the tenant password its
    own deal delivered."""
    return IsolationProbes(real_vm_target, operator_ssh, ssh, buyer_key,
                           deal_tenant_passwords(deal_driver, deal_state))


@pytest.fixture(scope="module")
def isolation() -> IsolationState:
    return IsolationState()


def _chains(counters: dict) -> tuple:
    """``ARKHAI-GUEST-IN`` and ``ARKHAI-GUEST-FWD`` from a counters read."""
    for name in ("guest_in", "guest_fwd"):
        assert counters[name]["rc"] == 0, (
            f"the host could not list the guest policy's chain ({name}): {counters[name]['stderr']}"
        )
    return parse_rules(counters["guest_in"]["stdout"]), parse_rules(counters["guest_fwd"]["stdout"])


def _host_policy_faults(probes: IsolationProbes, deal_state, label: str) -> list[str]:
    """O3 and O4 from the first guest, with the counters read on each side of
    its probe, and both jumps' places from the first read."""
    before = probes.operator("counters")
    result = probes.guest(deal_state.delivered_access, "policy", gateway=GATEWAY, dhcp_dns=True,
                          host_port=HOST_PORT, destinations=[METADATA], port=DESTINATION_PORT)
    after = probes.operator("counters")
    (in_before, fwd_before), (in_after, fwd_after) = _chains(before), _chains(after)
    faults = jump_faults(before["input"]["stdout"], before["forward"]["stdout"])
    faults += host_service_faults(in_before, in_after, result)
    faults += metadata_faults(fwd_before, fwd_after, result)
    log.info("[%s] DHCP offered %s, DNS answered %s, host port %s: %s, %s: %s", label,
             result.get("dhcp_offered"), result.get("dns_answered"), HOST_PORT,
             result["host_port"], METADATA, result["destinations"][METADATA])
    return faults


def _private_destination_faults(probes: IsolationProbes, deal_state, destinations,
                                label: str) -> list[str]:
    """O5 from the first guest: the refused destination's probe, then the
    listed one's while the host watches for its packet leaving."""
    before = probes.operator("counters")
    refused = probes.guest(deal_state.delivered_access, "policy", gateway=GATEWAY,
                           destinations=[destinations.refused], port=DESTINATION_PORT)
    listed, egress = probes.guest_while_egress_is_watched(
        deal_state.delivered_access, destinations.listed, gateway=GATEWAY)
    after = probes.operator("counters")
    (_, fwd_before), (_, fwd_after) = _chains(before), _chains(after)
    result = {"destinations": {**refused["destinations"], **listed["destinations"]}}
    log.info("[%s] %s: %s; %s: %s, seen leaving on %s %s time(s)", label, destinations.refused,
             refused["destinations"][destinations.refused], destinations.listed,
             listed["destinations"][destinations.listed], egress.get("device"), egress.get("seen"))
    return private_destination_faults(fwd_before, fwd_after, destinations, result, egress)


# ===========================================================================
# The shared scenario's stages, to the window in which both guests run
# ===========================================================================

class TestStage00_LifecycleHeld(real_deal.TestStage00_LifecycleHeld):
    pass


class TestStage00a_StorefrontHealth(real_deal.TestStage00a_StorefrontHealth):
    pass


class TestStage00b_RegistryReachable(real_deal.TestStage00b_RegistryReachable):
    pass


class TestStage00c_ProvisioningHealth(real_deal.TestStage00c_ProvisioningHealth):
    pass


class TestStage00c2_ProvisioningContractPins(real_deal.TestStage00c2_ProvisioningContractPins):
    pass


class TestStage00d_NegotiationStrategy(real_deal.TestStage00d_NegotiationStrategy):
    pass


class TestStage00e1_VmExecutionIsReal(real_deal.TestStage00e1_VmExecutionIsReal):
    pass


class TestStage00f1_ExecutorHostRegistry(real_deal.TestStage00f1_ExecutorHostRegistry):
    pass


class TestStage00f2_RegisteredHostIsTheTarget(real_deal.TestStage00f2_RegisteredHostIsTheTarget):
    pass


class TestStage00g_AlkahestConfigured(real_deal.TestStage00g_AlkahestConfigured):
    pass


class TestStage00h_ProvisioningStorefrontLink(real_deal.TestStage00h_ProvisioningStorefrontLink):
    pass


class TestStage02b_ListingCreated(real_deal.TestStage02b_ListingCreated):
    pass


class TestStage03b_ListingPublished(real_deal.TestStage03b_ListingPublished):
    pass


class TestStage04a_PrimaryRegistryPublish(real_deal.TestStage04a_PrimaryRegistryPublish):
    pass


class TestStage05a_EvaluateNegotiate(real_deal.TestStage05a_EvaluateNegotiate):
    pass


class TestStage05b_NegotiationStartsAndVisible(real_deal.TestStage05b_NegotiationStartsAndVisible):
    pass


class TestStage06b_ForceAcceptAndTerminal(real_deal.TestStage06b_ForceAcceptAndTerminal):
    pass


class TestStage07_OnChainEscrow(real_deal.TestStage07_OnChainEscrow):
    pass


class TestStage07b_VerifyEscrow(real_deal.TestStage07b_VerifyEscrow):
    pass


class TestStage08a_EvaluateSettle(real_deal.TestStage08a_EvaluateSettle):
    pass


class TestStage08a2_SettlementPreviewChoseTheTarget(
    real_deal.TestStage08a2_SettlementPreviewChoseTheTarget
):
    pass


class TestStage08b_SettlementSubmittedAndJobQueued(
    real_deal.TestStage08b_SettlementSubmittedAndJobQueued
):
    pass


class TestStage08b3_CreateJobSucceeded(real_deal.TestStage08b3_CreateJobSucceeded):
    pass


class TestStage09a_FulfillmentConvergesToActive(real_deal.TestStage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_CapacityEventCycle(real_deal.TestStage09a2_CapacityEventCycle):
    pass


class TestStage09b_SettlementReadyAndCredentials(real_deal.TestStage09b_SettlementReadyAndCredentials):
    pass


class TestStage09c_LeaseRecorded(real_deal.TestStage09c_LeaseRecorded):
    pass


class TestStage09c1_LateSettlementKeepsTheWindow(real_deal.TestStage09c1_LateSettlementKeepsTheWindow):
    pass


class TestStage09c3_LeaseNamesTheCreateJob(real_deal.TestStage09c3_LeaseNamesTheCreateJob):
    pass


class TestStage09d_BuyerReachesTheNegotiatedShape(real_deal.TestStage09d_BuyerReachesTheNegotiatedShape):
    pass


class TestStage09e_UnrelatedKeyRefused(real_deal.TestStage09e_UnrelatedKeyRefused):
    pass


class TestStage09f_HeartbeatOpened(real_deal.TestStage09f_HeartbeatOpened):
    pass


class TestStage09g_SecondDealAccepted(real_deal.TestStage09g_SecondDealAccepted):
    pass


class TestStage09h_SecondEscrowCreated(real_deal.TestStage09h_SecondEscrowCreated):
    pass


class TestStage09i_SecondSettlementSubmitted(real_deal.TestStage09i_SecondSettlementSubmitted):
    pass


class TestStage09j_SecondGuestAccessible(real_deal.TestStage09j_SecondGuestAccessible):
    pass


class TestStage09k_HeartbeatSurvivedCreate(real_deal.TestStage09k_HeartbeatSurvivedCreate):
    pass


# ===========================================================================
# Isolation, while both guests run and the first holds its heartbeat
# ===========================================================================

class TestStage09k1_GuestsAddressed:
    observations = ("O1", *HOST_SIDE)

    def test_09k1_each_guest_reports_its_address(self, probes, deal_state, isolation):
        require_state(deal_state, "delivered_access", "second_access")
        isolation.first = probes.guest(deal_state.delivered_access, "interface")
        isolation.second = probes.guest(deal_state.second_access, "interface")
        assert isolation.first["address"] != isolation.second["address"], (
            isolation.first, isolation.second)
        log.info("[09k1] First guest %s at %s (%s); second guest %s at %s (%s)",
                 deal_state.vm_name, isolation.first["address"], isolation.first["mac"],
                 deal_state.second_vm_name, isolation.second["address"], isolation.second["mac"])


class TestStage09k2_HostRead:
    observations = HOST_SIDE

    def test_09k2_the_host_reports_its_libvirt_version(self, real_vm_target, probes, isolation):
        operator_route(real_vm_target)
        version = probes.operator("version")
        isolation.libvirt, isolation.ufw_active = version["libvirt"], version["ufw_active"]
        isolation._host_read = True
        log.info("[09k2] Host %s runs libvirt %s, UFW %s. The run's two guests are expected "
                 "alone on the host, since the guest policy's counters are per rule; the "
                 "controlled target guarantees it", real_vm_target.host_id, isolation.libvirt,
                 "enabled" if isolation.ufw_active else "not enabled")


class TestStage09k3_NoGuestReachesTheOther:
    observations = ("O1",)

    def test_09k3_the_first_guest_reaches_the_second_neither_directly_nor_through_the_gateway(
        self, probes, deal_state, isolation,
    ):
        require_state(isolation, "first", "second")
        require_state(deal_state, "delivered_access")
        result = probes.guest(deal_state.delivered_access, "peers",
                              peer=isolation.second["address"], gateway=GATEWAY, port=HOST_PORT)
        log.info("[09k3] Direct %s; through %s %s", result["direct"], GATEWAY, result["gateway"])
        faults = guest_to_guest_faults(result)
        assert not faults, "; ".join(faults)


class TestStage09k4_AddressClaimDropped:
    observations = ("O2",)

    def test_09k4_a_claim_of_the_other_guests_address_is_dropped(
        self, real_vm_target, probes, ssh, buyer_key, deal_state, isolation,
    ):
        operator_route(real_vm_target)
        require_state(isolation, "first", "second", "_host_read")
        require_state(deal_state, "vm_name", "second_vm_name", "second_access")
        second = isolation.second["address"]
        probes.operator("refresh_neighbour", address=second)
        held_before = probes.operator("neighbour", address=second, bridge=BRIDGE)
        claimed = probes.guest(deal_state.delivered_access, "claim", peer=second, count=5)
        held_after = probes.operator("neighbour", address=second, bridge=BRIDGE)
        reached = ssh.run(deal_state.second_access, buyer_key, "id -un").strip() == \
            deal_state.second_access.user
        faults = claim_faults(held_after, isolation.second, isolation.first, reached)
        for guest in (deal_state.vm_name, deal_state.second_vm_name):
            state = probes.operator("guest_state", guest=guest)
            assert state["mac"] is not None, f"the host lists no interface of {guest} on default"
            assert state["live"]["rc"] == 0, state["live"]["stderr"]
            faults += filter_faults(state["live"]["stdout"], state["mac"], guest)
        log.info("[09k4] %s claims sent; the host held %s for %s before and %s after",
                 claimed["sent"], held_before, second, held_after)
        assert not faults, "; ".join(faults)


class TestStage09k5_HostServices:
    observations = ("O3",)

    def test_09k5_dhcp_and_dns_pass_and_another_host_port_is_refused(
        self, real_vm_target, probes, deal_state, isolation,
    ):
        operator_route(real_vm_target)
        require_state(isolation, "_host_read")
        require_state(deal_state, "delivered_access")
        before = probes.operator("counters")
        result = probes.guest(deal_state.delivered_access, "policy", gateway=GATEWAY,
                              dhcp_dns=True, host_port=HOST_PORT)
        after = probes.operator("counters")
        (in_before, _), (in_after, _) = _chains(before), _chains(after)
        log.info("[09k5] DHCP offered %s, DNS answered %s, host port %s: %s",
                 result["dhcp_offered"], result["dns_answered"], HOST_PORT, result["host_port"])
        faults = host_service_faults(in_before, in_after, result)
        assert not faults, "; ".join(faults)


class TestStage09k6_MetadataRefused:
    observations = ("O4",)

    def test_09k6_the_metadata_address_is_refused(self, real_vm_target, probes, deal_state, isolation):
        operator_route(real_vm_target)
        require_state(isolation, "_host_read")
        require_state(deal_state, "delivered_access")
        before = probes.operator("counters")
        result = probes.guest(deal_state.delivered_access, "policy", gateway=GATEWAY,
                              destinations=[METADATA], port=DESTINATION_PORT)
        after = probes.operator("counters")
        (_, fwd_before), (_, fwd_after) = _chains(before), _chains(after)
        log.info("[09k6] %s: %s", METADATA, result["destinations"][METADATA])
        faults = metadata_faults(fwd_before, fwd_after, result)
        assert not faults, "; ".join(faults)


class TestStage09k7_PrivateDestinations:
    observations = ("O5",)

    def test_09k7_the_refused_destination_is_refused_and_the_listed_one_forwarded(
        self, real_vm_target, probes, deal_state, isolation,
    ):
        destinations = private_destinations(real_vm_target)
        require_state(isolation, "_host_read")
        require_state(deal_state, "delivered_access")
        faults = _private_destination_faults(probes, deal_state, destinations, "09k7")
        assert not faults, "; ".join(faults)


class TestStage09k8_PrivateSourceBuyer:
    observations = ("O6",)

    def test_09k8_a_buyer_from_a_private_address_reaches_their_guest(
        self, real_vm_target, probes, deal_state,
    ):
        if real_vm_target.access.mode != "direct":
            pytest.skip(f"the target's buyers reach its guests through a relay, so O6 lacks "
                        f"{PRIVATE_SOURCE_ROUTE}")
        require_state(deal_state, "delivered_access")
        peer = probes.guest(deal_state.delivered_access, "peer", sudo=False)["peer"]
        skipped = private_buyer_skip(peer)
        if skipped:
            pytest.skip(skipped)
        log.info("[09k8] The buyer reached the first guest from the private address %s", peer)


class TestStage09k9_AfterLibvirtdRestart:
    observations = ("O7",)

    def test_09k9_the_policy_holds_after_libvirtd_restarts(
        self, real_vm_target, probes, deal_state, isolation,
    ):
        operator_route(real_vm_target)
        require_state(isolation, "_host_read")
        require_state(deal_state, "delivered_access")
        restarted = probes.operator("restart_libvirtd")
        assert restarted["restart"]["rc"] == 0, restarted["restart"]["stderr"]
        assert restarted["libvirtd_active"] == "active", restarted
        assert restarted["policy_unit_ran"], (
            f"arkhai-guest-policy.service did not run again after libvirtd started: "
            f"{restarted['policy_unit']}")
        assert restarted["policy_unit"].get("Result") == "success", (
            f"arkhai-guest-policy.service ran again after libvirtd started, but failed: "
            f"{restarted['policy_unit']}")
        isolation._libvirtd_restarted = True
        faults = _host_policy_faults(probes, deal_state, "09k9")
        assert not faults, "; ".join(faults)


class TestStage09k10_PrivateDestinationsAfterLibvirtdRestart:
    observations = ("O7",)

    def test_09k10_the_private_destinations_hold_after_libvirtd_restarts(
        self, real_vm_target, probes, deal_state, isolation,
    ):
        destinations = private_destinations(real_vm_target)
        require_state(isolation, "_libvirtd_restarted")
        require_state(deal_state, "delivered_access")
        faults = _private_destination_faults(probes, deal_state, destinations, "09k10")
        assert not faults, "; ".join(faults)


class TestStage09k11_AfterUfwReload:
    observations = ("O7",)

    def test_09k11_the_policy_holds_after_ufw_reloads(
        self, real_vm_target, probes, deal_state, isolation,
    ):
        operator_route(real_vm_target)
        require_state(isolation, "_libvirtd_restarted")
        require_state(deal_state, "delivered_access")
        reloaded = probes.operator("reload_ufw")
        if not reloaded["ufw_active"]:
            pytest.skip("UFW is not enabled on the host, so its reload, which the guest policy "
                        "must survive, cannot be observed")
        assert reloaded["reload"]["rc"] == 0, reloaded["reload"]["stderr"]
        isolation._ufw_reloaded = True
        faults = _host_policy_faults(probes, deal_state, "09k11")
        assert not faults, "; ".join(faults)


class TestStage09k12_PrivateDestinationsAfterUfwReload:
    observations = ("O7",)

    def test_09k12_the_private_destinations_hold_after_ufw_reloads(
        self, real_vm_target, probes, deal_state, isolation,
    ):
        destinations = private_destinations(real_vm_target)
        require_state(isolation, "_ufw_reloaded")
        require_state(deal_state, "delivered_access")
        faults = _private_destination_faults(probes, deal_state, destinations, "09k12")
        assert not faults, "; ".join(faults)


class TestStage09k13_PlantedGuestConverged:
    observations = ("O8",)

    def test_09k13_a_guest_planted_unconverged_is_converged_without_interrupting_its_buyer(
        self, real_vm_target, probes, deal_state, isolation,
    ):
        """The first guest, holding the heartbeat, is given the state of a guest
        created without the isolated, filtered interface, and the host kit's
        command converges it. Convergence is attempted whatever the fixture
        managed, even when it failed partway."""
        operator_route(real_vm_target)
        require_state(isolation, "first", "second", "_host_read")
        require_state(deal_state, "vm_name", "heartbeat", "delivered_access")
        guest = deal_state.vm_name
        try:
            isolation.plant = probes.operator("plant", guest=guest)
            isolation.planted = probes.operator("guest_state", guest=guest)
        finally:
            isolation.convergence = probes.operator("converge")
        isolation.converged = probes.operator("guest_state", guest=guest)
        again = probes.guest(deal_state.delivered_access, "peers",
                             peer=isolation.second["address"], gateway=GATEWAY, port=HOST_PORT)
        heartbeat = deal_state.heartbeat
        log.info("[09k13] Planted %s on libvirt %s: %s; convergence reported %s; the heartbeat's "
                 "longest gap %.3fs", guest, isolation.libvirt,
                 {key: value["rc"] for key, value in isolation.plant.items()
                  if isinstance(value, dict) and "rc" in value},
                 isolation.convergence["lines"], heartbeat.longest_gap)
        faults = planted_faults(isolation.plant, isolation.planted)
        faults += converged_faults(guest, isolation.convergence, isolation.converged,
                                   heartbeat.longest_gap)
        faults += guest_to_guest_faults(again)
        if not heartbeat.running:
            faults.append(f"{guest}'s buyer session ended")
        assert not faults, "; ".join(faults)
        heartbeat.assert_alive(max_gap=MAX_GAP_SECONDS)


class TestStage09k14_LiveFilterRestored:
    observations = ("O9",)

    def test_09k14_the_filter_detached_live_is_bound_live_again(
        self, real_vm_target, deal_state, isolation,
    ):
        operator_route(real_vm_target)
        require_state(isolation, "plant", "planted", "convergence", "converged")
        outcome, reason = live_restoration(isolation.plant, isolation.planted,
                                           isolation.convergence, isolation.converged,
                                           deal_state.vm_name, isolation.libvirt)
        if outcome == "unproven":
            pytest.skip(reason)
        assert outcome == "made", reason
        log.info("[09k14] %s", reason)


# ===========================================================================
# The shared scenario's stages, from the second lease's end
# ===========================================================================

class TestStage09l_SecondLeaseCutShort(real_deal.TestStage09l_SecondLeaseCutShort):
    pass


class TestStage09m_SecondGuestReleased(real_deal.TestStage09m_SecondGuestReleased):
    pass


class TestStage09n_HeartbeatSurvivedRemoval(real_deal.TestStage09n_HeartbeatSurvivedRemoval):
    pass


class TestStage10a_LeaseExpirySetup(real_deal.TestStage10a_LeaseExpirySetup):
    pass


class TestStage10b_LeaseCycleBeginsTeardown(real_deal.TestStage10b_LeaseCycleBeginsTeardown):
    pass


class TestStage10b2_ManagementBeforeTeardown(real_deal.TestStage10b2_ManagementBeforeTeardown):
    pass


class TestStage11a_TeardownDispatch(real_deal.TestStage11a_TeardownDispatch):
    pass


class TestStage11a3_TeardownJobSucceeded(real_deal.TestStage11a3_TeardownJobSucceeded):
    pass


class TestStage11b_TeardownCompletion(real_deal.TestStage11b_TeardownCompletion):
    pass


class TestStage11c_LeaseEventsRecorded(real_deal.TestStage11c_LeaseEventsRecorded):
    pass


class TestStage11c_GuestGoneFromHost(real_deal.TestStage11c_GuestGoneFromHost):
    pass


class TestStage11d_DeliveredAccessEnded(real_deal.TestStage11d_DeliveredAccessEnded):
    pass
