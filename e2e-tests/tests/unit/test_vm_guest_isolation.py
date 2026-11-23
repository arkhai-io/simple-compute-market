"""The VM guest-isolation proof's judgements, its probe's carriage, and its wiring.

The module itself needs the real-provisioning target, a real KVM host and its
operator route, which no lane has. Here its judgements run over samples of what
the host and the guests print (``iptables -L -v -x -n``, ``bridge -d link
show``, ``virsh`` and the convergence command's lines), its stages run with
their fixtures stood in for to show which skip naming what, and the module is
collected and run without a target as pytest runs it.
"""

from __future__ import annotations

import copy
import inspect
import json
import os
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from e2e_harness.real_provisioning_target import (
    SECTION,
    PrivateDestinations,
    load_real_provisioning_target,
)
from tests.e2e.roles.helpers.qualification import (
    StageResult,
    declared_stages,
    observation_outcomes,
    stage_observations,
)
from tests.e2e.roles.scenarios.vms import guest_isolation_probe as probe
from tests.e2e.roles.scenarios.vms import test_real_provisioning_deal as real_deal
from tests.e2e.roles.scenarios.vms import test_vm_guest_isolation as module
from tests.e2e.roles.scenarios.vms.guest_isolation import (
    DESTINATIONS_FIELD,
    GUEST_ISOLATION_FIELD,
    METADATA,
    PRIVATE_SOURCE_ROUTE,
    PROBE,
    admission_faults,
    binding_bound,
    claim_faults,
    converged_faults,
    deciding_rule,
    filter_faults,
    guest_to_guest_faults,
    host_service_faults,
    input_drop,
    jump_faults,
    live_restoration,
    metadata_faults,
    parse_rules,
    planted_faults,
    port_isolated,
    private_buyer_skip,
    private_destination_faults,
    probe_command,
    refusal_faults,
)
from tests.unit.test_qualification_modules import _lane_modules, _registered_markers
from tests.unit.test_real_provisioning_target import EXAMPLE

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = Path(module.__file__).relative_to(PROJECT)
MARKER = "e2e_vm_guest_isolation"

DESTINATIONS = PrivateDestinations(refused="10.20.0.7", listed="10.20.0.8")
FIRST = {"device": "enp1s0", "address": "192.168.122.10", "mac": "52:54:00:00:00:0a"}
SECOND = {"device": "enp1s0", "address": "192.168.122.11", "mac": "52:54:00:00:00:0b"}


# ---------------------------------------------------------------------------
# Samples of what the host prints
# ---------------------------------------------------------------------------

def guest_in(*, drop: int = 0, dhcp: int = 2) -> str:
    """``iptables -L ARKHAI-GUEST-IN -v -x -n`` as iptables prints it with its
    ``opt`` column and protocol names."""
    return f"""Chain ARKHAI-GUEST-IN (1 references)
    pkts      bytes target     prot opt in     out     source               destination
      40     2400 ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            ctstate RELATED,ESTABLISHED
    {dhcp:4}      656 ACCEPT     udp  --  *      *       0.0.0.0/0            0.0.0.0/0            udp dpt:67
       4      240 ACCEPT     udp  --  *      *       0.0.0.0/0            192.168.122.1        udp dpt:53
       0        0 ACCEPT     tcp  --  *      *       0.0.0.0/0            192.168.122.1        tcp dpt:53
    {drop:4}      180 DROP       all  --  *      *       0.0.0.0/0            0.0.0.0/0            /* arkhai-guest-isolation */
"""


def guest_fwd(*, listed: int = 0, metadata: int = 0, ten: int = 0, accept_listed: bool = True) -> str:
    """``iptables -L ARKHAI-GUEST-FWD -v -x -n`` as a later iptables prints it,
    with no ``opt`` column and numeric protocols."""
    accepted = (f"    {listed:4}      240 ACCEPT     0    *      *       0.0.0.0/0            10.20.0.8\n"
                if accept_listed else "")
    return f"""Chain ARKHAI-GUEST-FWD (1 references)
    pkts      bytes target     prot in     out     source               destination
       0        0 DROP       0    *      virbr0  0.0.0.0/0            0.0.0.0/0            /* arkhai-guest-isolation */
      10      800 ACCEPT     0    *      *       0.0.0.0/0            0.0.0.0/0            ctstate RELATED,ESTABLISHED
{accepted}    {metadata:4}      120 DROP       0    *      *       0.0.0.0/0            169.254.0.0/16
    {ten:4}      120 DROP       0    *      *       0.0.0.0/0            10.0.0.0/8
       0        0 DROP       0    *      *       0.0.0.0/0            172.16.0.0/12
       0        0 DROP       0    *      *       0.0.0.0/0            192.168.0.0/16
       0        0 DROP       0    *      *       0.0.0.0/0            100.64.0.0/10
"""


INPUT_FIRST = "-P INPUT ACCEPT\n-A INPUT -i virbr0 -j ARKHAI-GUEST-IN\n-A INPUT -j ufw-before-input\n"
FORWARD_FIRST = "-P FORWARD ACCEPT\n-A FORWARD -i virbr0 -j ARKHAI-GUEST-FWD\n-A FORWARD -j LIBVIRT_FWO\n"


def link(isolated: bool, tap: str = "vnet0") -> str:
    return (f"7: {tap}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master virbr0 state forwarding\n"
            f"    hairpin off guard off learning on flood on isolated {'on' if isolated else 'off'} "
            "locked off\n")


def bindings(*taps: str) -> str:
    return " Port Dev   Filter\n----------------------------\n" + "".join(
        f" {tap}      clean-traffic\n" for tap in taps)


def domain(*, port: bool, filtered: bool, mac: str = FIRST["mac"], parameters=None) -> str:
    parameters = parameters if parameters is not None else {
        "CTRL_IP_LEARNING": "dhcp", "DHCPSERVER": "192.168.122.1"}
    ref = ("<filterref filter='clean-traffic'>" + "".join(
        f"<parameter name='{key}' value='{value}'/>" for key, value in parameters.items())
        + "</filterref>") if filtered else ""
    return (f"<domain><devices><interface type='network'><mac address='{mac}'/>"
            f"<source network='default'/><model type='virtio'/>"
            f"{'<port isolated=\"yes\"/>' if port else ''}{ref}</interface></devices></domain>")


def state(*, isolated: bool, bound: bool, saved_port: bool, saved_filter: bool,
          live_filter: bool | None = None) -> dict:
    live_filter = bound if live_filter is None else live_filter
    ok = lambda stdout: {"rc": 0, "stdout": stdout, "stderr": ""}  # noqa: E731
    return {
        "tap": "vnet0", "mac": FIRST["mac"], "link": ok(link(isolated)),
        "bindings": ok(bindings("vnet0") if bound else bindings()),
        "live": ok(domain(port=False, filtered=live_filter)),
        "saved": ok(domain(port=saved_port, filtered=saved_filter)),
    }


def plant(*, live_refused: bool = False) -> dict:
    return {
        "tap": "vnet0", "mac": FIRST["mac"], "libvirt": "8.0.0",
        "isolation_cleared": {"rc": 0, "stdout": "", "stderr": ""},
        "live_filter_detached": (
            {"rc": 1, "stdout": "", "stderr": "error: Operation not supported"} if live_refused
            else {"rc": 0, "stdout": "Device updated successfully", "stderr": ""}),
        "saved_stripped": {"rc": 0, "stdout": "Device updated successfully", "stderr": ""},
    }


def convergence(**line) -> dict:
    reported = {"name": "guest-1", "port_isolated": True, "filter": "live",
                "saved_definition": True, "changed": True, "error": None, **line}
    return {"rc": 0, "stderr": "", "lines": [reported]}


# ---------------------------------------------------------------------------
# The chains, and refusals counted by them
# ---------------------------------------------------------------------------

def test_both_listing_forms_parse_into_the_same_rules():
    """With the ``opt`` column and protocol names, or without it and with
    protocol numbers, one chain reads as the same rules."""
    named = guest_in(drop=3)
    numbered = (named.replace(" opt", "").replace("all  --", "0   ").replace("udp  --", "17  ")
                .replace("tcp  --", "6   "))
    assert numbered != named
    assert parse_rules(numbered) == parse_rules(named)
    rules = parse_rules(named)
    assert [(rule.target, rule.protocol) for rule in rules] == [
        ("ACCEPT", "all"), ("ACCEPT", "udp"), ("ACCEPT", "udp"), ("ACCEPT", "tcp"), ("DROP", "all")]
    assert input_drop(rules).packets == 3
    forward = parse_rules(guest_fwd(listed=1))
    assert forward[0].out_interface == "virbr0" and forward[0].protocol == "all"
    assert deciding_rule(forward, DESTINATIONS.listed).target == "ACCEPT"
    assert deciding_rule(forward, DESTINATIONS.refused).destination == "10.0.0.0/8"
    assert deciding_rule(forward, METADATA).destination == "169.254.0.0/16"
    assert deciding_rule(forward, "203.0.113.9") is None


def test_a_refusal_counts_when_its_drop_counted_a_packet():
    before, after = parse_rules(guest_fwd(ten=4)), parse_rules(guest_fwd(ten=7))
    rule = deciding_rule(after, DESTINATIONS.refused)
    assert refusal_faults("10.20.0.7", ["timeout"], rule, before, after) == []


def test_a_refusal_the_policy_did_not_make_fails():
    """No answer, but the drop's counter is unchanged: the destination did not
    exist, or the packet never reached the policy."""
    before = after = parse_rules(guest_fwd(ten=4))
    (fault,) = refusal_faults("10.20.0.7", ["timeout"], deciding_rule(after, "10.20.0.7"),
                              before, after)
    assert "counted no packet" in fault and "not the policy's" in fault


@pytest.mark.parametrize("outcome", ["connected", "reset"])
def test_a_destination_that_answered_was_reached(outcome):
    before, after = parse_rules(guest_fwd(ten=4)), parse_rules(guest_fwd(ten=5))
    faults = refusal_faults("10.20.0.7", [outcome], deciding_rule(after, "10.20.0.7"), before, after)
    assert faults == [f"10.20.0.7 was reached ({outcome})"]


def test_a_rule_missing_from_a_read_of_its_chain_is_named():
    before = parse_rules(guest_fwd(ten=4).replace("10.0.0.0/8", "10.0.0.0/9"))
    after = parse_rules(guest_fwd(ten=6))
    (fault,) = refusal_faults("10.20.0.7", ["timeout"], deciding_rule(after, "10.20.0.7"),
                              before, after)
    assert "missing from a read of its chain" in fault


def test_a_refilled_chain_whose_counters_fell_counts_no_admission():
    """The policy's unit refills its chains on every libvirtd start, so a
    counter read across one may fall; a fall is no packet counted."""
    (fault,) = _o5(listed_before=5, listed_after=1)
    assert "the accept of 10.20.0.8 counted no packet" in fault


def test_a_destination_an_accept_decides_is_no_refusal():
    rules = parse_rules(guest_fwd(listed=3))
    (fault,) = refusal_faults("10.20.0.8", ["timeout"], deciding_rule(rules, "10.20.0.8"),
                              rules, rules)
    assert "no drop of the guest policy decides 10.20.0.8" in fault


def test_dhcp_and_dns_answered_and_the_host_port_refused_make_o3():
    result = {"dhcp_offered": True, "dns_answered": True, "host_port": "timeout"}
    assert host_service_faults(parse_rules(guest_in(drop=1)), parse_rules(guest_in(drop=3)),
                               result) == []


def test_unanswered_dhcp_or_dns_or_an_uncounted_host_port_fails_o3():
    result = {"dhcp_offered": False, "dns_answered": False, "host_port": "timeout"}
    faults = host_service_faults(parse_rules(guest_in(drop=1)), parse_rules(guest_in(drop=1)), result)
    assert len(faults) == 3
    assert "no DHCP offer" in faults[0] and "no DNS answer" in faults[1]
    assert "counted no packet" in faults[2]


def test_the_metadata_address_refused_by_its_drop_makes_o4():
    result = {"destinations": {METADATA: ["timeout"]}}
    assert metadata_faults(parse_rules(guest_fwd()), parse_rules(guest_fwd(metadata=2)), result) == []
    assert metadata_faults(parse_rules(guest_fwd()), parse_rules(guest_fwd()), result)


def _o5(*, listed_before=0, listed_after=2, ten_before=0, ten_after=2, seen=3, accept=True):
    result = {"destinations": {DESTINATIONS.refused: ["timeout"],
                               DESTINATIONS.listed: ["timeout", "timeout", "timeout"]}}
    return private_destination_faults(
        parse_rules(guest_fwd(listed=listed_before, ten=ten_before, accept_listed=accept)),
        parse_rules(guest_fwd(listed=listed_after, ten=ten_after, accept_listed=accept)),
        DESTINATIONS, result, {"device": "eth0", "seen": seen})


def test_the_refused_destination_refused_and_the_listed_one_seen_leaving_make_o5():
    assert _o5() == []


def test_a_listed_destinations_packet_that_does_not_leave_the_host_fails_o5():
    """Its accept counted the packet, but nothing left on the routed interface."""
    (fault,) = _o5(seen=0)
    assert "no packet from the guest to 10.20.0.8:80 was seen leaving the host on eth0" in fault


def test_a_listed_destination_whose_accept_counted_nothing_fails_o5():
    (fault,) = _o5(listed_after=0)
    assert "the accept of 10.20.0.8 counted no packet" in fault


def test_the_chain_must_admit_the_listed_destination_and_refuse_the_other():
    assert admission_faults(parse_rules(guest_fwd()), DESTINATIONS) == []
    (fault,) = admission_faults(parse_rules(guest_fwd(accept_listed=False)), DESTINATIONS)
    assert "does not admit the listed destination 10.20.0.8" in fault
    assert "guest_allowed_private_destinations" in fault
    swapped = PrivateDestinations(refused="10.20.0.8", listed="10.20.0.7")
    assert len(admission_faults(parse_rules(guest_fwd()), swapped)) == 2


def test_both_jumps_first_make_o7s_order():
    assert jump_faults(INPUT_FIRST, FORWARD_FIRST) == []
    ufw_ahead = "-P INPUT ACCEPT\n-A INPUT -j ufw-before-input\n-A INPUT -i virbr0 -j ARKHAI-GUEST-IN\n"
    (fault,) = jump_faults(ufw_ahead, FORWARD_FIRST)
    assert fault.startswith("INPUT's first rule is '-A INPUT -j ufw-before-input'")


# ---------------------------------------------------------------------------
# Between the guests
# ---------------------------------------------------------------------------

def _peers(*, arp=False, icmp=False, tcp="unreachable", via_icmp=False, via_tcp="timeout",
           route=True):
    return {"peer": SECOND["address"],
            "direct": {"arp_answered": arp, "icmp_answered": icmp, "tcp": tcp},
            "gateway": {"route_added": route, "route_error": "" if route else "RTNETLINK answers",
                        "icmp_answered": via_icmp, "tcp": via_tcp}}


def test_nothing_reaching_the_other_guest_makes_o1():
    assert guest_to_guest_faults(_peers()) == []


@pytest.mark.parametrize(("changes", "named"), [
    ({"arp": True}, "answered the guest's ARP request directly"),
    ({"icmp": True}, "answered the guest's ICMP echo directly"),
    ({"tcp": "reset"}, "reached 192.168.122.11 directly (reset)"),
    ({"via_icmp": True}, "ICMP echo through 192.168.122.1"),
    ({"via_tcp": "connected"}, "through 192.168.122.1 (connected)"),
    ({"route": False}, "could not be added"),
])
def test_any_path_to_the_other_guest_fails_o1(changes, named):
    (fault,) = guest_to_guest_faults(_peers(**changes))
    assert named in fault


def test_a_dropped_claim_leaves_the_host_holding_the_guests_own_mac():
    assert claim_faults({"lladdr": SECOND["mac"]}, SECOND, FIRST, True) == []
    (poisoned,) = claim_faults({"lladdr": FIRST["mac"]}, SECOND, FIRST, True)
    assert "names the claimant's MAC" in poisoned
    (unread,) = claim_faults({"lladdr": None}, SECOND, FIRST, True)
    assert "the claim's effect is unread" in unread
    (unreached,) = claim_faults({"lladdr": SECOND["mac"]}, SECOND, FIRST, False)
    assert "does not reach it after the claim" in unreached


def test_the_filters_parameters_are_read_from_the_live_definition():
    assert filter_faults(domain(port=False, filtered=True), FIRST["mac"], "guest-1") == []
    (absent,) = filter_faults(domain(port=False, filtered=False), FIRST["mac"], "guest-1")
    assert "binds no clean-traffic filter" in absent
    (short,) = filter_faults(domain(port=False, filtered=True, parameters={"CTRL_IP_LEARNING": "any"}),
                             FIRST["mac"], "guest-1")
    assert "lacks" in short and "DHCPSERVER" in short


@pytest.mark.parametrize("peer", ["10.1.2.3", "172.20.0.4", "192.168.5.6", "100.70.0.1"])
def test_a_private_buyer_address_makes_o6(peer):
    assert private_buyer_skip(peer) is None


@pytest.mark.parametrize(("peer", "named"), [
    ("192.168.122.1", "the host's own address on the guests' network"),
    ("192.168.122.40", "masquerades the buyer's forwarded connection"),
    ("203.0.113.9", "from 203.0.113.9, not a private address"),
    ("192.0.2.4", "not a private address"),
    (None, "reads no buyer address"),
    ("fd00::1", "reads no buyer address"),
])
def test_any_other_peer_address_skips_o6_naming_the_route(peer, named):
    reason = private_buyer_skip(peer)
    assert named in reason and PRIVATE_SOURCE_ROUTE in reason


# ---------------------------------------------------------------------------
# Convergence: O8 and O9
# ---------------------------------------------------------------------------

def test_the_host_reports_a_port_and_a_binding_as_bridge_and_virsh_print_them():
    assert port_isolated(link(True)) and not port_isolated(link(False))
    assert binding_bound(bindings("vnet0", "vnet1"), "vnet1")
    assert not binding_bound(bindings("vnet1"), "vnet0")


def test_a_planted_guest_converged_makes_o8():
    planted = state(isolated=False, bound=False, saved_port=False, saved_filter=False)
    converged = state(isolated=True, bound=True, saved_port=True, saved_filter=True)
    assert planted_faults(plant(), planted) == []
    assert converged_faults("guest-1", convergence(), converged, 1.2) == []


def test_a_fixture_that_did_not_plant_fails_o8():
    still = state(isolated=True, bound=True, saved_port=True, saved_filter=True)
    faults = planted_faults(plant(), still)
    assert any("still isolated" in fault for fault in faults)
    assert any("still holds the isolation or the filter" in fault for fault in faults)


def test_a_fixture_step_that_failed_fails_o8():
    planted = state(isolated=False, bound=False, saved_port=False, saved_filter=False)
    failed = {**plant(), "isolation_cleared": {"rc": 2, "stdout": "", "stderr": "RTNETLINK"},
              "saved_stripped": {"rc": 1, "stdout": "", "stderr": "error: XML error"}}
    faults = planted_faults(failed, planted)
    assert len(faults) == 2
    assert "could not clear the port's isolation: RTNETLINK" in faults[0]
    assert "could not strip the saved definition: error: XML error" in faults[1]


def test_a_guest_the_host_lists_no_tap_for_fails_o8():
    missing = {**state(isolated=False, bound=False, saved_port=False, saved_filter=False),
               "tap": None, "link": None}
    assert planted_faults(plant(), missing) == [
        "the host lists no interface of the guest on the default network"]
    assert "lists no interface" in converged_faults("guest-1", convergence(), missing, 1.0)[-1]


@pytest.mark.parametrize(("ran", "named"), [
    ({"rc": 1, "stderr": "arkhai-guest-converge: bridge is not installed", "lines": []},
     "the convergence command failed (exit 1)"),
    ({"rc": 0, "stderr": "", "lines": []}, "reported no line for guest-1"),
])
def test_a_convergence_that_could_not_run_or_named_nothing_fails_o8(ran, named):
    converged = state(isolated=True, bound=True, saved_port=True, saved_filter=True)
    assert any(named in fault for fault in converged_faults("guest-1", ran, converged, 1.0))


@pytest.mark.parametrize(("line", "converged", "gap", "named"), [
    ({"port_isolated": False}, dict(isolated=True, bound=True, saved_port=True, saved_filter=True),
     1.0, "reported guest-1 unconverged"),
    ({}, dict(isolated=False, bound=True, saved_port=True, saved_filter=True), 1.0, "not isolated"),
    ({}, dict(isolated=True, bound=True, saved_port=False, saved_filter=True), 1.0,
     "does not carry the isolation and the filter"),
    ({}, dict(isolated=True, bound=True, saved_port=True, saved_filter=True), 6.5,
     "paused 6.500s, over 5s"),
])
def test_an_unconverged_guest_or_an_interrupted_session_fails_o8(line, converged, gap, named):
    (fault,) = converged_faults("guest-1", convergence(**line), state(**converged), gap)
    assert named in fault


def _restoration(*, live_refused=False, still_bound=False, filter="live", bound_after=True,
                 live_after=None):
    planted = state(isolated=False, bound=still_bound, saved_port=False, saved_filter=False)
    converged = state(isolated=True, bound=bound_after, saved_port=True, saved_filter=True,
                      live_filter=live_after)
    return live_restoration(plant(live_refused=live_refused), planted,
                            convergence(filter=filter, error="libvirt did not bind the filter live"),
                            converged, "guest-1", "8.0.0")


def test_a_filter_detached_live_and_bound_live_again_makes_o9():
    outcome, reason = _restoration()
    assert outcome == "made" and "8.0.0" in reason


def test_a_live_removal_libvirt_refused_leaves_o9_unproven_naming_its_version():
    outcome, reason = _restoration(live_refused=True)
    assert outcome == "unproven"
    assert "libvirt 8.0.0 refused the fixture's live filter removal" in reason


def test_a_live_removal_that_failed_otherwise_fails_o9():
    """Only libvirt's refusal of the operation leaves O9 unproven; a fixture
    whose own update failed, an XML or configuration error among the causes,
    fails it."""
    planted = state(isolated=False, bound=True, saved_port=False, saved_filter=False)
    converged = state(isolated=True, bound=True, saved_port=True, saved_filter=True)
    for stderr in ("error: XML error: missing source information",
                   "error: unsupported configuration: filterref is not allowed here"):
        broken = {**plant(), "live_filter_detached": {"rc": 1, "stdout": "", "stderr": stderr}}
        outcome, reason = live_restoration(broken, planted, convergence(), converged, "guest-1",
                                           "8.0.0")
        assert outcome == "failed" and "other than by libvirt refusing it" in reason, stderr


def test_a_host_read_that_failed_is_named_rather_than_judged():
    """A failed ``bridge`` or ``virsh`` read is no port left open, no filter
    detached, and no definition stripped."""
    planted = state(isolated=False, bound=False, saved_port=False, saved_filter=False)
    converged = state(isolated=True, bound=True, saved_port=True, saved_filter=True)
    unreadable = {**planted, "bindings": {"rc": 1, "stdout": "", "stderr": "error: no connection"},
                  "saved": {"rc": 1, "stdout": "", "stderr": "error: domain not found"}}
    faults = planted_faults(plant(), unreadable)
    assert faults == ["the host could not read its filter bindings: error: no connection",
                      "the host could not read its saved definition: error: domain not found"]
    assert live_restoration(plant(), unreadable, convergence(), converged, "guest-1",
                            "8.0.0")[0] == "failed"
    unreadable_after = {**converged, "link": {"rc": 1, "stdout": "", "stderr": "Cannot find device"}}
    assert converged_faults("guest-1", convergence(), unreadable_after, 1.0) == [
        "the host could not read its tap's bridge port: Cannot find device"]


def test_a_filter_left_for_the_next_start_leaves_o9_unproven_naming_the_version():
    outcome, reason = _restoration(filter="next_start", bound_after=False)
    assert outcome == "unproven" and "for its next start on libvirt 8.0.0" in reason


def test_a_live_filter_libvirt_took_but_does_not_bind_fails_o9():
    """Convergence reports such a filter waiting for the next start, but
    libvirt did not refuse it: the live definition names it, and no binding
    holds it."""
    outcome, reason = _restoration(filter="next_start", bound_after=False, live_after=True)
    assert outcome == "failed" and "binds no clean-traffic filter to vnet0" in reason


@pytest.mark.parametrize(("changes", "named"), [
    ({"still_bound": True}, "still binds clean-traffic"),
    ({"bound_after": False}, "binds no clean-traffic filter to vnet0"),
    ({"filter": "none"}, "filter as 'none'"),
])
def test_a_restoration_reported_but_not_observed_fails_o9(changes, named):
    outcome, reason = _restoration(**changes)
    assert outcome == "failed" and named in reason


# ---------------------------------------------------------------------------
# Carrying the probe
# ---------------------------------------------------------------------------

def test_the_operator_command_is_sudo_n_python3_with_the_probes_text_and_json():
    request = {"operation": "counters"}
    argv = shlex.split(probe_command(request))
    assert argv[:5] == ["sudo", "-n", "--", "python3", "-c"]
    assert argv[5] == PROBE.read_text()
    assert json.loads(argv[6]) == request
    assert shlex.split(probe_command(request, sudo=False))[:2] == ["python3", "-c"]


def test_every_operation_the_scenario_asks_for_is_one_the_probe_offers():
    sources = Path(module.__file__).read_text() + PROBE.with_name("guest_isolation.py").read_text()
    asked = set(re.findall(r'\.operator\(\s*"(\w+)"', sources))
    asked |= set(re.findall(r'\.guest\([^,()]+,\s*"(\w+)"', sources))
    asked |= set(re.findall(r'self\.operator\(\s*"(\w+)"', sources))
    assert {"version", "counters", "plant", "converge", "egress", "peers", "claim",
            "policy", "peer", "interface"} <= asked
    assert asked <= set(probe.OPERATIONS)


def test_the_probe_checksums_as_the_internet_checksum_does():
    # RFC 1071's worked example: the one's-complement sum of these words is 0xddf2.
    assert probe.checksum(bytes.fromhex("0001f203f4f5f6f7")) == (~0xddf2 & 0xFFFF)


OWN = {"device": "enp1s0", "address": FIRST["address"], "mac": FIRST["mac"]}


def test_the_probes_arp_request_and_claim_are_the_frames_arp_defines():
    request = probe.arp_frame(OWN, 1, OWN["address"], SECOND["address"])
    assert len(request) == 42 and request[:6] == b"\xff" * 6
    assert request[6:12] == probe.mac_bytes(OWN["mac"]) and request[12:14] == b"\x08\x06"
    assert request[14:22] == bytes.fromhex("0001080006040001")
    assert request[28:32] == bytes([192, 168, 122, 10]) and request[38:42] == bytes([192, 168, 122, 11])
    claim = probe.arp_frame(OWN, 2, SECOND["address"], SECOND["address"], target_mac=b"\xff" * 6)
    assert claim[20:22] == b"\x00\x02" and claim[28:32] == claim[38:42] == bytes([192, 168, 122, 11])


def test_the_probe_knows_an_arp_reply_from_the_address_it_asked_for():
    peer = {"device": "enp1s0", "address": SECOND["address"], "mac": SECOND["mac"]}
    reply = probe.arp_frame(peer, 2, SECOND["address"], FIRST["address"],
                            destination=probe.mac_bytes(FIRST["mac"]))
    assert probe.is_arp_reply_from(reply, SECOND["address"])
    assert not probe.is_arp_reply_from(reply, "192.168.122.12")
    request = probe.arp_frame(peer, 1, SECOND["address"], FIRST["address"])
    assert not probe.is_arp_reply_from(request, SECOND["address"])


def test_the_probes_echo_request_checks_out_and_its_reply_is_known():
    echo = probe.icmp_echo(0x1234)
    assert echo[0] == 8 and probe.checksum(echo) == 0
    header = bytes([0x45]) + b"\0" * 19
    reply = header + bytes([0]) + echo[1:]
    assert probe.is_echo_reply(reply, 0x1234)
    assert not probe.is_echo_reply(reply, 0x4321)
    assert not probe.is_echo_reply(header + echo, 0x1234)


def _offer(discover: bytes, xid: int, server: str) -> bytes:
    """The discover turned into SERVER's reply: BOOTREPLY, from the server's
    address, to the client port."""
    ip = bytearray(discover[14:])
    ip[12:16] = bytes(map(int, server.split(".")))
    udp = bytearray(ip[20:])
    udp[0:4] = (67).to_bytes(2, "big") + (68).to_bytes(2, "big")
    udp[8] = 2
    return discover[:14] + bytes(ip[:20]) + bytes(udp)


def test_the_probes_dhcp_discover_is_a_broadcast_bootp_request_from_its_own_mac():
    frame = probe.dhcp_discover_frame(OWN["mac"], 0xA1B2C3D4, ip_id=7)
    assert frame[:6] == b"\xff" * 6 and frame[12:14] == b"\x08\x00"
    ip = frame[14:]
    assert probe.checksum(ip[:20]) == 0 and ip[9] == 17 and ip[16:20] == b"\xff" * 4
    bootp = ip[28:]
    assert bootp[0] == 1 and bootp[4:8] == bytes.fromhex("a1b2c3d4")
    assert bootp[28:34] == probe.mac_bytes(OWN["mac"])
    assert bootp[236:240] == bytes([99, 130, 83, 99]) and bootp[240:243] == bytes([53, 1, 1])
    assert ip[20:24] == (68).to_bytes(2, "big") + (67).to_bytes(2, "big")


def test_the_probe_knows_its_offer_by_its_xid_and_server():
    discover = probe.dhcp_discover_frame(OWN["mac"], 0xA1B2C3D4)
    offer = _offer(discover, 0xA1B2C3D4, "192.168.122.1")
    assert probe.is_offer(offer, 0xA1B2C3D4, "192.168.122.1")
    assert not probe.is_offer(offer, 0x01020304, "192.168.122.1")
    assert not probe.is_offer(offer, 0xA1B2C3D4, "192.168.122.2")
    assert not probe.is_offer(discover, 0xA1B2C3D4, "0.0.0.0")


def test_the_probe_counts_only_outgoing_tcp_to_the_listed_address_and_port():
    def packet(destination: str, port: int, protocol: int = 6) -> bytes:
        header = bytes([0x45, 0, 0, 40, 0, 0, 0, 0, 64, protocol, 0, 0, 10, 0, 0, 5])
        return header + bytes(map(int, destination.split("."))) + (40000).to_bytes(2, "big") \
            + port.to_bytes(2, "big") + b"\0" * 16

    assert probe.is_outgoing_tcp_to(packet("10.20.0.8", 80), probe.PACKET_OUTGOING, "10.20.0.8", 80)
    assert not probe.is_outgoing_tcp_to(packet("10.20.0.8", 80), 0, "10.20.0.8", 80)
    assert not probe.is_outgoing_tcp_to(packet("10.20.0.8", 443), probe.PACKET_OUTGOING,
                                        "10.20.0.8", 80)
    assert not probe.is_outgoing_tcp_to(packet("10.20.0.9", 80), probe.PACKET_OUTGOING,
                                        "10.20.0.8", 80)
    assert not probe.is_outgoing_tcp_to(packet("10.20.0.8", 80, protocol=17),
                                        probe.PACKET_OUTGOING, "10.20.0.8", 80)


def test_the_probe_reads_the_hosts_virsh_and_systemctl_output():
    domiflist = (" Interface   Type      Source    Model    MAC\n"
                 "-------------------------------------------------------\n"
                 " vnet7       network   default   virtio   52:54:00:00:00:0a\n")
    assert probe.default_network_interface(domiflist) == ("vnet7", "52:54:00:00:00:0a")
    assert probe.default_network_interface(domiflist.replace("default", "other")) == (None, None)
    assert probe.daemon_version("Compiled against library: libvirt 8.0.0\n"
                                "Running against daemon: 8.0.0\n") == "8.0.0"
    assert probe.daemon_version("error: failed to connect\n") is None
    assert probe.unit_properties("ExecMainExitTimestampMonotonic=123\nResult=success\n") == {
        "ExecMainExitTimestampMonotonic": "123", "Result": "success"}


# ---------------------------------------------------------------------------
# The module's wiring
# ---------------------------------------------------------------------------

def _target(**vm_changes):
    section = copy.deepcopy(yaml.safe_load(EXAMPLE.read_text())[SECTION])
    section["hosts"][0].update(vm_changes)
    return load_real_provisioning_target({SECTION: section}).host_for("vm")


WITH_ROUTE = {"guest_isolation": {
    "operator": {"host": "127.0.0.1", "port": 16002, "user": "example-observer",
                 "key_path": "/run/secrets/example-observer-key"},
    "private_destinations": {"refused": "10.20.0.7", "listed": "10.20.0.8"},
}}


class _Reached(Exception):
    """A stage went past every check of its target to its first fixture use."""


class _Unreached:
    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attribute):
        raise _Reached(f"{self._name}.{attribute}")


def _own(cls) -> bool:
    return not any(base.__module__ == real_deal.__name__ for base in cls.__mro__[1:])


def stage_results_against(target) -> list[StageResult]:
    """Each declared stage's outcome as far as its target decides it: a skip
    its own checks of the target make, or ``passed`` once it reaches its first
    fixture. The shared scenario's stages are taken as passed."""
    results = []
    for cls, name in declared_stages(module):
        observations = frozenset(stage_observations(module, cls))
        label = f"{cls.__name__}::{name}"
        if _own(cls):
            function = getattr(cls(), name)
            arguments = {parameter: target if parameter == "real_vm_target" else _Unreached(parameter)
                         for parameter in inspect.signature(function).parameters}
            try:
                function(**arguments)
            except pytest.skip.Exception as skipped:
                results.append(StageResult(label, observations, "skipped", str(skipped)))
                continue
            except _Reached:
                pass
        results.append(StageResult(label, observations, "passed"))
    return results


def _outcomes(target) -> dict:
    return {outcome.observation: outcome
            for outcome in observation_outcomes(module.OBSERVATIONS, stage_results_against(target))}


def test_a_target_without_guest_isolation_leaves_all_but_o1_and_o6_unproven_naming_it():
    outcomes = _outcomes(_target())
    assert {name for name, outcome in outcomes.items() if outcome.outcome == "made"} == {"O1", "O6"}
    for name in ("O2", "O3", "O4", "O5", "O7", "O8", "O9"):
        assert outcomes[name].outcome == "unproven", outcomes[name]
        assert all(GUEST_ISOLATION_FIELD in reason for reason in outcomes[name].reasons)


def test_a_target_without_private_destinations_leaves_o5_and_o7_unproven_naming_it():
    route = copy.deepcopy(WITH_ROUTE)
    del route["guest_isolation"]["private_destinations"]
    outcomes = _outcomes(_target(**route))
    assert {name for name, outcome in outcomes.items() if outcome.outcome == "unproven"} == {"O5", "O7"}
    for name in ("O5", "O7"):
        assert all(DESTINATIONS_FIELD in reason for reason in outcomes[name].reasons)


def test_a_relayed_target_leaves_o6_unproven_naming_the_route():
    outcomes = _outcomes(_target(**WITH_ROUTE, access={"mode": "relay", "relay_id": "example-relay"}))
    assert outcomes["O6"].outcome == "unproven"
    assert PRIVATE_SOURCE_ROUTE in outcomes["O6"].reasons[0]
    assert {name for name, outcome in outcomes.items() if outcome.outcome == "made"} == \
        set(module.OBSERVATIONS) - {"O6"}


@pytest.mark.parametrize("peer", ["10.1.2.3", "192.168.122.1", "203.0.113.9"])
def test_under_direct_access_o6_is_made_only_from_a_private_buyer_address(peer):
    """The guest's peer is the buyer's own address only where nothing between
    rewrote it; the host's address on the guests' network is never a buyer's."""
    stage = module.TestStage09k8_PrivateSourceBuyer()
    probes = SimpleNamespace(guest=lambda endpoint, operation, sudo: {"peer": peer})
    deal_state = SimpleNamespace(delivered_access=object())
    run = lambda: stage.test_09k8_a_buyer_from_a_private_address_reaches_their_guest(  # noqa: E731
        _target(), probes, deal_state)
    if private_buyer_skip(peer) is None:
        run()
    else:
        with pytest.raises(pytest.skip.Exception) as skipped:
            run()
        assert str(skipped.value) == private_buyer_skip(peer)


def test_the_shared_stages_run_unchanged_with_the_isolation_stages_inside_the_two_guest_window():
    base = [name for name, value in vars(real_deal).items()
            if isinstance(value, type) and name.startswith("TestStage")]
    ours = [value for name, value in vars(module).items()
            if isinstance(value, type) and name.startswith("TestStage")]
    shared = [cls for cls in ours if not _own(cls)]
    assert [cls.__name__ for cls in shared] == base
    for cls in shared:
        assert cls.__bases__ == (getattr(real_deal, cls.__name__),)
        assert not {key for key in vars(cls) if not key.startswith("__")}, cls.__name__
    names = [cls.__name__ for cls in ours]
    own = [index for index, cls in enumerate(ours) if _own(cls)]
    assert names[own[0] - 1] == "TestStage09k_HeartbeatSurvivedCreate"
    assert names[own[-1] + 1] == "TestStage09l_SecondLeaseCutShort"
    assert own == list(range(own[0], own[-1] + 1))


def test_every_isolation_stage_declares_its_observations_and_each_is_required():
    required = set()
    for cls in (value for value in vars(module).values()
                if isinstance(value, type) and value.__name__.startswith("TestStage") and _own(value)):
        assert "observations" in vars(cls), cls.__name__
        assert set(cls.observations) <= set(module.OBSERVATIONS), cls.__name__
        required |= set(cls.observations)
    assert required == set(module.OBSERVATIONS) == {f"O{n}" for n in range(1, 10)}


def test_the_module_is_registered_under_its_marker_and_in_no_lane():
    assert MARKER in _registered_markers()
    assert f"pytest.mark.{MARKER}" in Path(module.__file__).read_text()
    assert MARKER not in _lane_modules()


def _pytest(*arguments: str) -> subprocess.CompletedProcess:
    environment = {**os.environ, "ACTIVE_PROFILES": "local"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-p", "no:cacheprovider", *arguments],
        cwd=PROJECT, env=environment, capture_output=True, text=True, timeout=600, check=False,
    )


def test_the_module_collects_every_stage_under_its_marker():
    result = _pytest("--collect-only", "-q", "-m", MARKER, str(MODULE_PATH))
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    collected = [line for line in result.stdout.splitlines() if line.startswith(f"{MODULE_PATH}::")]
    assert len(collected) == len(declared_stages(module))


def test_without_the_target_every_stage_is_a_blocked_skip(tmp_path):
    report = tmp_path / "report.xml"
    result = _pytest("-q", "-m", MARKER, f"--junit-xml={report}", str(MODULE_PATH))
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    cases = ET.parse(report).getroot().iter("testcase")
    reasons = {case.get("name"): [skipped.get("message", "") for skipped in case.iter("skipped")]
               for case in cases}
    assert len(reasons) == len(declared_stages(module))
    for name, skips in reasons.items():
        assert len(skips) == 1 and "blocked: no real-provisioning target" in skips[0], (name, skips)
