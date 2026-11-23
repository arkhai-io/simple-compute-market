"""The VM guest-isolation proof's probes, and the judgements made of what they report.

The probes are ``guest_isolation_probe.py``, fixed Python carried with a JSON
argument over the shared SSH seam (``ssh_access.SshSession.run``): in a guest,
under ``sudo`` as its buyer; on the host, as ``sudo -n -- python3 -c <probe>
<arguments>`` through the operator route the VM target's ``guest_isolation``
section names, whose key is referenced, never copied. What they report is
judged here, by pure functions over what the host and the guests printed:

- a refusal counts only when the guest policy rule that should make it counted
  a packet across the probe, since a destination that does not exist, or a
  packet that never reached the policy, goes unanswered too;
- the listed private destination counts as forwarded only when its accept
  rule's counter rose and the guest's packet to it was seen leaving the host on
  the interface the host routes it through: an accept ends the filter table's
  ``FORWARD`` traversal, but the packet still meets every other table's chain at
  that hook, libvirt's own among them;
- the chain itself must admit the listed destination and refuse the other;
- live filter restoration (O9) is made only when the fixture detached the
  filter live and convergence bound it live again; a refused live removal or a
  filter left for the guest's next start leaves it unproven, naming the
  libvirt version.

Counters are per rule, so the run's guests are expected to be alone on the
host, a precondition the controlled target guarantees and the run states.
"""
from __future__ import annotations

import ipaddress
import json
import re
import shlex
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from e2e_harness.real_provisioning_target import (
    GUEST_POLICY_PRIVATE_RANGES,
    GUESTS_NETWORK,
    SECTION,
    GuestIsolation,
    PrivateDestinations,
    VmHost,
)
from tests.e2e.roles.helpers.ssh_access import SshEndpoint, SshKey, SshSession
from tests.e2e.roles.scenarios.bare_metal.working_data_qualification import checked_key_reference

PROBE = Path(__file__).with_name("guest_isolation_probe.py")
#: The guests' bridge, and the host's address on it: libvirt's ``default``
#: network, which every guest is attached to.
BRIDGE = "virbr0"
GATEWAY = "192.168.122.1"
METADATA = "169.254.169.254"
#: The host port a guest probes, which the guest policy must refuse.
HOST_PORT = 22
#: The port a guest probes a private destination on; neither needs to answer.
DESTINATION_PORT = 80
#: The longest pause a converged guest's buyer session may show.
MAX_GAP_SECONDS = 5.0
#: How long the host watches for the guest's packets to the listed
#: destination, and how the guest spaces its attempts within that window: the
#: watch begins only once its own SSH connection is made, so attempts started
#: at least three seconds apart, rather than at once, cannot all precede it.
EGRESS_WATCH_SECONDS = 30
LISTED_ATTEMPTS = 5
LISTED_ATTEMPT_INTERVAL_SECONDS = 3

GUEST_ISOLATION_FIELD = f"{SECTION}.hosts.vm.guest_isolation"
DESTINATIONS_FIELD = f"{GUEST_ISOLATION_FIELD}.private_destinations"
PRIVATE_SOURCE_ROUTE = "a buyer route from a private address to the guest's forwarded port"

#: TCP outcomes that show the destination was reached: it accepted, or it
#: answered with a refusal of its own.
REACHED = ("connected", "reset")
#: ``iptables -n`` prints a rule's protocol by name in some versions and by
#: number in others.
_PROTOCOLS = {"0": "all", "1": "icmp", "6": "tcp", "17": "udp"}
_CLEAN_TRAFFIC = {"CTRL_IP_LEARNING": "dhcp", "DHCPSERVER": GATEWAY}


# ===========================================================================
# What the target names
# ===========================================================================


def operator_route(target: VmHost) -> GuestIsolation:
    """The target's guest-isolation inputs, or a skip naming the section."""
    if target.guest_isolation is None:
        pytest.skip(f"{GUEST_ISOLATION_FIELD} is not set, so the host-side steps have no "
                    "operator route")
    return target.guest_isolation


def private_destinations(target: VmHost) -> PrivateDestinations:
    """The target's private destinations, or a skip naming the field."""
    destinations = operator_route(target).private_destinations
    if destinations is None:
        pytest.skip(f"{DESTINATIONS_FIELD} is not set, so no private destination is probed")
    return destinations


# ===========================================================================
# Carrying the probe
# ===========================================================================


def probe_command(request: dict[str, Any], *, sudo: bool = True) -> str:
    """The probe's own text and its JSON argument as one remote command, run
    as ``sudo -n -- python3 -c <probe> <arguments>`` unless SUDO is false."""
    argv = ["python3", "-c", PROBE.read_text(), json.dumps(request)]
    if sudo:
        argv = ["sudo", "-n", "--", *argv]
    return shlex.join(argv)


def _answer(output: str, operation: str) -> dict[str, Any]:
    answer = json.loads(output)
    if "error" in answer:
        raise AssertionError(f"the {operation} probe could not run: {answer['error']}")
    return answer


@dataclass
class IsolationProbes:
    """The run's routes to the probes: the operator route to the host, and the
    buyer's session to each guest."""

    target: VmHost
    operator_ssh: SshSession
    guest_ssh: SshSession
    buyer_key: SshKey

    def operator(self, operation: str, **arguments: Any) -> dict[str, Any]:
        route = operator_route(self.target).operator
        endpoint = SshEndpoint(route.host, route.port, route.user)
        key = checked_key_reference(route.key_path)
        request = {"operation": operation, **arguments}
        return _answer(self.operator_ssh.run(endpoint, key, probe_command(request)), operation)

    def guest(self, endpoint: SshEndpoint, operation: str, *, sudo: bool = True,
              **arguments: Any) -> dict[str, Any]:
        request = {"operation": operation, **arguments}
        output = self.guest_ssh.run(endpoint, self.buyer_key, probe_command(request, sudo=sudo))
        return _answer(output, operation)

    def guest_while_egress_is_watched(
        self, endpoint: SshEndpoint, destination: str, **arguments: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The guest's ``policy`` probe of DESTINATION, run while the host
        watches for its packets leaving on the interface routing it. Each side
        begins only once its own SSH connection is made, in no set order, so the
        guest spaces its attempts over most of the watch's window."""
        seconds = EGRESS_WATCH_SECONDS
        watched: dict[str, Any] = {}

        def watch() -> None:
            try:
                watched["answer"] = self.operator(
                    "egress", destination=destination, port=DESTINATION_PORT, seconds=seconds)
            except BaseException as error:  # re-raised in the stage's own thread
                watched["error"] = error

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            guest = self.guest(endpoint, "policy", destinations=[destination],
                               port=DESTINATION_PORT, attempts=LISTED_ATTEMPTS,
                               interval=LISTED_ATTEMPT_INTERVAL_SECONDS, **arguments)
        finally:
            watcher.join(timeout=seconds + 120)
        if "error" in watched:
            raise watched["error"]
        assert "answer" in watched, "the host's egress watch did not end"
        return guest, watched["answer"]


# ===========================================================================
# The policy's chains, as the host prints them
# ===========================================================================


@dataclass(frozen=True)
class Rule:
    """One rule of a chain as ``iptables -L <chain> -v -x -n`` prints it."""

    packets: int
    target: str
    protocol: str
    in_interface: str
    out_interface: str
    source: str
    destination: str
    options: str

    def same_rule(self, other: "Rule") -> bool:
        """Whether OTHER is this rule, whatever either's counter."""
        return (self.target, self.protocol, self.in_interface, self.out_interface,
                self.source, self.destination, self.options) == (
            other.target, other.protocol, other.in_interface, other.out_interface,
            other.source, other.destination, other.options)

    def __str__(self) -> str:
        parts = [self.target, self.protocol, f"in {self.in_interface}",
                 f"out {self.out_interface}", f"to {self.destination}", self.options]
        return " ".join(part for part in parts if part)


def parse_rules(listing: str) -> tuple[Rule, ...]:
    """A chain's rules, in order. The ``opt`` column, which some iptables
    versions omit, is told from an interface by its leading ``-`` or ``!``."""
    rules = []
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) < 8 or not fields[0].isdigit():
            continue
        packets, _bytes, target, protocol, *rest = fields
        if rest[0].startswith(("-", "!")):
            rest = rest[1:]
        in_interface, out_interface, source, destination, *options = rest
        rules.append(Rule(int(packets), target, _PROTOCOLS.get(protocol, protocol),
                          in_interface, out_interface, source, destination, " ".join(options)))
    return tuple(rules)


def _network(destination: str) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(destination if "/" in destination else f"{destination}/32",
                                 strict=False)


def deciding_rule(forward: tuple[Rule, ...], address: str) -> Rule | None:
    """The rule of ``ARKHAI-GUEST-FWD`` deciding a guest's new connection to
    ADDRESS: the first naming a destination holding it, past the hairpin drop
    and the accept of established connections, which a new connection to a
    destination off the bridge does not meet."""
    for rule in forward:
        if rule.out_interface == BRIDGE or "ESTABLISHED" in rule.options:
            continue
        if ipaddress.IPv4Address(address) in _network(rule.destination):
            return rule
    return None


def input_drop(guest_in: tuple[Rule, ...]) -> Rule | None:
    """``ARKHAI-GUEST-IN``'s closing drop, which refuses every host port but
    DHCP and DNS."""
    drops = [rule for rule in guest_in if rule.target == "DROP"]
    return drops[-1] if drops else None


def risen(before: tuple[Rule, ...], after: tuple[Rule, ...], rule: Rule) -> int | None:
    """How many packets RULE counted between two reads of its chain, or None
    when either read lacks it."""
    was = next((candidate for candidate in before if candidate.same_rule(rule)), None)
    now = next((candidate for candidate in after if candidate.same_rule(rule)), None)
    if was is None or now is None:
        return None
    return now.packets - was.packets


def refusal_faults(name: str, outcomes: list[str], rule: Rule | None,
                   before: tuple[Rule, ...], after: tuple[Rule, ...]) -> list[str]:
    """A refusal of NAME, which the guest saw as OUTCOMES, counts only when
    RULE, the drop that should make it, counted a packet across the probe."""
    faults = [f"{name} was reached ({outcome})" for outcome in outcomes if outcome in REACHED]
    if rule is None or rule.target != "DROP":
        faults.append(f"no drop of the guest policy decides {name}; it is decided by {rule}")
        return faults
    counted = risen(before, after, rule)
    if counted is None:
        faults.append(f"the rule `{rule}` deciding {name} is missing from a read of its chain")
    elif counted <= 0:
        faults.append(f"{name} got no answer ({', '.join(outcomes)}), but the rule `{rule}` "
                      "that should refuse it counted no packet, so the refusal is not the policy's")
    return faults


def host_service_faults(before_in: tuple[Rule, ...], after_in: tuple[Rule, ...],
                        result: dict[str, Any]) -> list[str]:
    """O3: DHCP and DNS on the host answer the guest; another host port is
    refused by the policy."""
    faults = []
    if not result.get("dhcp_offered"):
        faults.append(f"no DHCP offer from {GATEWAY} answered the guest's discover")
    if not result.get("dns_answered"):
        faults.append(f"no DNS answer from {GATEWAY} reached the guest")
    faults += refusal_faults(f"the host's port {HOST_PORT} at {GATEWAY}", [result["host_port"]],
                             input_drop(after_in), before_in, after_in)
    return faults


def metadata_faults(before_fwd: tuple[Rule, ...], after_fwd: tuple[Rule, ...],
                    result: dict[str, Any]) -> list[str]:
    """O4: the link-local metadata address is refused by the policy."""
    return refusal_faults(METADATA, result["destinations"][METADATA],
                          deciding_rule(after_fwd, METADATA), before_fwd, after_fwd)


def admission_faults(forward: tuple[Rule, ...], destinations: PrivateDestinations) -> list[str]:
    """O5, from the chain alone: the listed destination is admitted and the
    refused one is not."""
    faults = []
    listed = deciding_rule(forward, destinations.listed)
    if listed is None or listed.target != "ACCEPT":
        faults.append(f"the guest policy does not admit the listed destination "
                      f"{destinations.listed}: it is decided by {listed}; host preparation "
                      "must be given it in guest_allowed_private_destinations")
    refused = deciding_rule(forward, destinations.refused)
    if refused is None or refused.target != "DROP":
        faults.append(f"the guest policy does not refuse {destinations.refused}: it is decided "
                      f"by {refused}")
    return faults


def private_destination_faults(
    before_fwd: tuple[Rule, ...], after_fwd: tuple[Rule, ...], destinations: PrivateDestinations,
    result: dict[str, Any], egress: dict[str, Any],
) -> list[str]:
    """O5: the refused destination is refused by the policy; the listed one is
    admitted by its accept, and the guest's packet to it seen leaving the host."""
    faults = admission_faults(after_fwd, destinations)
    faults += refusal_faults(destinations.refused, result["destinations"][destinations.refused],
                             deciding_rule(after_fwd, destinations.refused), before_fwd, after_fwd)
    listed = deciding_rule(after_fwd, destinations.listed)
    if listed is not None and listed.target == "ACCEPT":
        counted = risen(before_fwd, after_fwd, listed)
        if counted is None or counted <= 0:
            faults.append(f"the accept of {destinations.listed} counted no packet while the "
                          "guest connected to it")
    if not egress.get("seen"):
        faults.append(f"no packet from the guest to {destinations.listed}:{DESTINATION_PORT} was "
                      f"seen leaving the host on {egress.get('device')}, the interface routing it")
    return faults


def jump_faults(input_rules: str, forward_rules: str) -> list[str]:
    """O7: each policy chain's jump is its built-in chain's first rule, from
    ``iptables -S INPUT`` and ``iptables -S FORWARD``."""
    faults = []
    for chain, rules, jump in (
        ("INPUT", input_rules, f"-A INPUT -i {BRIDGE} -j ARKHAI-GUEST-IN"),
        ("FORWARD", forward_rules, f"-A FORWARD -i {BRIDGE} -j ARKHAI-GUEST-FWD"),
    ):
        first = next((line.strip() for line in rules.splitlines() if line.startswith("-A ")), None)
        if first != jump:
            faults.append(f"{chain}'s first rule is {first!r}, not the guest policy's jump")
    return faults


# ===========================================================================
# Between the guests
# ===========================================================================


def guest_to_guest_faults(result: dict[str, Any]) -> list[str]:
    """O1, and O8's probes once converged: neither ARP, ICMP nor TCP reaches
    the other guest, directly or through the gateway."""
    peer = result["peer"]
    direct, gateway = result["direct"], result["gateway"]
    faults = []
    if direct["arp_answered"]:
        faults.append(f"{peer} answered the guest's ARP request directly")
    if direct["icmp_answered"]:
        faults.append(f"{peer} answered the guest's ICMP echo directly")
    if direct["tcp"] in REACHED:
        faults.append(f"TCP from the guest reached {peer} directly ({direct['tcp']})")
    if not gateway["route_added"]:
        faults.append(f"the guest's route to {peer} through {GATEWAY} could not be added: "
                      f"{gateway['route_error']}")
        return faults
    if gateway["icmp_answered"]:
        faults.append(f"{peer} answered the guest's ICMP echo through {GATEWAY}")
    if gateway["tcp"] in REACHED:
        faults.append(f"TCP from the guest reached {peer} through {GATEWAY} ({gateway['tcp']})")
    return faults


def _interface(xml: str, mac: str | None) -> ET.Element | None:
    if mac is None:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for element in root.findall("./devices/interface"):
        address = element.find("mac")
        if address is not None and address.get("address", "").lower() == mac.lower():
            return element
    return None


def filter_parameters(xml: str, mac: str | None) -> dict[str, str] | None:
    """The clean-traffic parameters of the interface with MAC in a domain's
    definition, or None when no clean-traffic filter is bound to it."""
    element = _interface(xml, mac)
    ref = None if element is None else element.find("filterref")
    if ref is None or ref.get("filter") != "clean-traffic":
        return None
    return {parameter.get("name"): parameter.get("value") for parameter in ref.findall("parameter")}


def filter_faults(xml: str, mac: str | None, name: str) -> list[str]:
    """NAME's definition binds clean-traffic to its interface with both of the
    parameters every guest is created with."""
    parameters = filter_parameters(xml, mac)
    if parameters is None:
        return [f"{name} binds no clean-traffic filter to its interface {mac}"]
    missing = {key: value for key, value in _CLEAN_TRAFFIC.items() if parameters.get(key) != value}
    return [f"{name}'s clean-traffic filter lacks {missing}; it holds {parameters}"] if missing else []


def claim_faults(neighbour: dict[str, Any], peer: dict[str, Any], claimant: dict[str, Any],
                 buyer_reached: bool) -> list[str]:
    """O2: after one guest claimed the other's address, the host still holds
    the other's own MAC for it, and the other's buyer still reaches it."""
    faults = []
    held = (neighbour.get("lladdr") or "").lower()
    if held == claimant["mac"].lower():
        faults.append(f"the host's neighbour entry for {peer['address']} names the claimant's "
                      f"MAC {claimant['mac']}")
    elif held != peer["mac"].lower():
        faults.append(f"the host's neighbour entry for {peer['address']} holds {held or 'nothing'}, "
                      f"not the guest's own MAC {peer['mac']}, so the claim's effect is unread")
    if not buyer_reached:
        faults.append("the other guest's buyer does not reach it after the claim")
    return faults


def private_buyer_skip(peer: str | None) -> str | None:
    """Why a buyer session's peer address, as the guest sees it, shows no buyer
    from a private address, or None when it does.

    A VM create masquerades the buyer's forwarded connection to the guest, so a
    guest reached at its forwarded port sees the host's own address on the
    guests' network; that address is private, and is not the buyer's."""
    try:
        address = ipaddress.IPv4Address(peer or "")
    except ValueError:
        return f"the guest reads no buyer address ({peer!r}), so O6 lacks {PRIVATE_SOURCE_ROUTE}"
    if address in GUESTS_NETWORK:
        return (f"the guest sees the buyer's session from {address}, the host's own address on "
                f"the guests' network, since a VM create masquerades the buyer's forwarded "
                f"connection; the buyer's own address is unread, so O6 lacks {PRIVATE_SOURCE_ROUTE} "
                "that a guest can observe")
    if not any(address in block for block in GUEST_POLICY_PRIVATE_RANGES):
        return (f"the buyer's session reaches the guest from {address}, not a private address, "
                f"so O6 lacks {PRIVATE_SOURCE_ROUTE}")
    return None


# ===========================================================================
# Convergence
# ===========================================================================


def port_isolated(link: str) -> bool:
    """Whether ``bridge -d link show`` reports the port isolated."""
    return re.search(r"(^|\s)isolated on(\s|$)", link) is not None


def binding_bound(bindings: str, tap: str) -> bool:
    """Whether ``virsh nwfilter-binding-list`` binds clean-traffic to TAP."""
    return any(line.split() == [tap, "clean-traffic"] for line in bindings.splitlines())


def saved_carries_both(xml: str, mac: str) -> bool:
    """Whether a saved definition holds the interface's isolated port and its
    clean-traffic filter with both parameters."""
    element = _interface(xml, mac)
    port = None if element is None else element.find("port")
    return (port is not None and port.get("isolated") == "yes"
            and not filter_faults(xml, mac, "the saved definition"))


_READS = {"link": "its tap's bridge port", "bindings": "its filter bindings",
          "live": "its running definition", "saved": "its saved definition"}


def _tap_faults(state: dict[str, Any]) -> list[str]:
    """A guest state holds nothing to judge when the host listed no tap for
    it, or could not read one of what it reports: a failed read is not a
    port that is not isolated, nor a filter that is not bound."""
    if state.get("tap") is None or state.get("link") is None:
        return ["the host lists no interface of the guest on the default network"]
    return [f"the host could not read {what}: {state[key]['stderr']}"
            for key, what in _READS.items() if state[key]["rc"] != 0]


def planted_faults(plant: dict[str, Any], planted: dict[str, Any]) -> list[str]:
    """The fixture planted the state of a guest created without the isolated,
    filtered interface: a port that is not isolated and a saved definition
    holding neither the isolation nor the filter. Its live filter removal may
    be refused; that is O9's."""
    if _tap_faults(planted):
        return _tap_faults(planted)
    faults = []
    if plant["isolation_cleared"]["rc"] != 0:
        faults.append(f"the fixture could not clear the port's isolation: "
                      f"{plant['isolation_cleared']['stderr']}")
    if plant["saved_stripped"]["rc"] != 0:
        faults.append(f"the fixture could not strip the saved definition: "
                      f"{plant['saved_stripped']['stderr']}")
    if port_isolated(planted["link"]["stdout"]):
        faults.append(f"the planted guest's port {planted['tap']} is still isolated")
    element = _interface(planted["saved"]["stdout"], planted["mac"])
    if element is None or element.find("port") is not None or element.find("filterref") is not None:
        faults.append("the planted guest's saved definition still holds the isolation or the filter")
    return faults


def convergence_line(convergence: dict[str, Any], guest: str) -> dict[str, Any] | None:
    return next((line for line in convergence["lines"] if line.get("name") == guest), None)


def converged_faults(guest: str, convergence: dict[str, Any], converged: dict[str, Any],
                     longest_gap: float) -> list[str]:
    """O8, but for the probes between the guests: the command reported the
    guest's port isolated and its saved definition written, the host shows
    both, and the guest's buyer session's longest pause is at most five
    seconds."""
    faults = []
    if convergence["rc"] != 0:
        faults.append(f"the convergence command failed (exit {convergence['rc']}): "
                      f"{convergence['stderr']}")
    line = convergence_line(convergence, guest)
    if line is None:
        faults.append(f"the convergence command reported no line for {guest}")
    elif not (line.get("port_isolated") and line.get("saved_definition")):
        faults.append(f"the convergence command reported {guest} unconverged: {line}")
    if _tap_faults(converged):
        return faults + _tap_faults(converged)
    if not port_isolated(converged["link"]["stdout"]):
        faults.append(f"{guest}'s port {converged['tap']} is not isolated after convergence")
    if not saved_carries_both(converged["saved"]["stdout"], converged["mac"]):
        faults.append(f"{guest}'s saved definition does not carry the isolation and the filter")
    if longest_gap > MAX_GAP_SECONDS:
        faults.append(f"{guest}'s buyer session paused {longest_gap:.3f}s, over "
                      f"{MAX_GAP_SECONDS:.0f}s")
    return faults


def live_restoration(plant: dict[str, Any], planted: dict[str, Any],
                     convergence: dict[str, Any], converged: dict[str, Any],
                     guest: str, libvirt: str | None) -> tuple[str, str]:
    """O9's outcome and its reason: ``made`` only when the fixture detached the
    filter live and convergence bound it live again; ``unproven`` when libvirt
    refused the live removal, or convergence left the filter for the guest's
    next start with the live definition not naming it, naming the libvirt
    version; otherwise ``failed``."""
    version = libvirt or "of unknown version"
    unread = _tap_faults(planted) + _tap_faults(converged)
    if unread:
        return ("failed", "; ".join(unread))
    detached = plant["live_filter_detached"]
    if detached["rc"] != 0:
        # libvirt reports an operation it does not make on a running guest as
        # "Operation not supported"; any other failure, an XML or configuration
        # error among them, is the fixture's own, not a refusal.
        if not re.search(r"operation not supported", detached["stderr"], re.IGNORECASE):
            return ("failed", f"the fixture's live filter removal failed on libvirt {version}, "
                              f"other than by libvirt refusing it: {detached['stderr']}")
        return ("unproven", f"libvirt {version} refused the fixture's live filter removal "
                            f"({detached['stderr']}), so no live restoration was observed")
    if binding_bound(planted["bindings"]["stdout"], planted["tap"]):
        return ("failed", f"the fixture's live filter removal reported success, but libvirt "
                          f"{version} still binds clean-traffic to {planted['tap']}")
    line = convergence_line(convergence, guest) or {}
    # The command reports the filter waiting for the next start both when
    # libvirt refused it live and when libvirt took it into the live
    # definition but holds no binding of it; only the first is the fallback
    # that leaves O9 unproven, and the second is judged by the binding below.
    named_live = filter_parameters(converged["live"]["stdout"], converged["mac"]) is not None
    if line.get("filter") == "next_start" and not named_live:
        return ("unproven", f"convergence left {guest}'s filter for its next start on libvirt "
                            f"{version} ({line.get('error')}), so nothing was restored live")
    if line.get("filter") not in ("live", "next_start"):
        return ("failed", f"convergence reported {guest}'s filter as {line.get('filter')!r}: {line}")
    faults = filter_faults(converged["live"]["stdout"], converged["mac"], f"{guest}'s live definition")
    if not binding_bound(converged["bindings"]["stdout"], converged["tap"]):
        faults.append(f"libvirt {version} binds no clean-traffic filter to {converged['tap']}")
    if faults:
        return ("failed", "; ".join(faults))
    return ("made", f"the filter was bound live again on libvirt {version}")


# ===========================================================================
# What the stages carry between them
# ===========================================================================


@dataclass
class IsolationState:
    """What the isolation stages learn, in the order they learn it."""

    #: Each guest's own interface, address and MAC, as its probe reported them.
    first: dict[str, Any] | None = None
    second: dict[str, Any] | None = None
    #: The host's libvirt version and whether UFW is enabled.
    libvirt: str | None = None
    ufw_active: bool | None = None
    _host_read: bool = False
    #: The fixture planted on the first guest, and the host's account of it.
    plant: dict[str, Any] | None = None
    planted: dict[str, Any] | None = None
    _libvirtd_restarted: bool = False
    _ufw_reloaded: bool = False
    #: The convergence command's report, and the host's account after it.
    convergence: dict[str, Any] | None = None
    converged: dict[str, Any] | None = None
