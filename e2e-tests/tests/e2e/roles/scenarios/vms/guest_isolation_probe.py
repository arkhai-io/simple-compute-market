"""Fixed observer code for the VM guest-isolation proof.

Carried as text over the shared SSH seam with one JSON argument naming its
``operation`` (``guest_isolation.probe_command``), and run either in a guest,
under ``sudo`` as its buyer, or on the guest's host, under ``sudo -n`` through
the target's operator route. It needs only Python's standard library and the
host's or guest's own commands, prints one JSON object, and judges nothing:
the scenario reads what it reports. Every operation exits 0 having reported
what it saw, so a probe that observed a refusal is told apart from one that
could not run.

Guest operations: ``interface`` (the guest's own interface, address and MAC),
``peers`` (ARP, ICMP and TCP to another guest, directly and through the
gateway), ``claim`` (gratuitous ARP replies claiming another guest's address),
``policy`` (DHCP, DNS, a host port, and TCP to listed destinations), and
``peer`` (the buyer session's peer address, run without ``sudo``).

Host operations: ``version``, ``counters``, ``restart_libvirtd``,
``reload_ufw``, ``refresh_neighbour``, ``neighbour``, ``guest_state``,
``plant``, ``converge`` and ``egress``.
"""
from __future__ import annotations

import errno
import json
import os
import random
import socket
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

CONVERGE = "/usr/local/sbin/arkhai-guest-converge"
#: Every operation ends within the shared SSH seam's attempt of 70 seconds,
#: since the seam runs a command again once an attempt outlasts it, and a
#: libvirtd restart or a convergence run twice is not the observation made.
RESTART_SECONDS = 35
POLICY_RERUN_SECONDS = 20
CONVERGE_SECONDS = 60
ETH_P_ALL = 0x0003
ETH_P_IP = 0x0800
ETH_P_ARP = 0x0806
PACKET_OUTGOING = 4
BROADCAST_MAC = b"\xff" * 6
CLEAN_TRAFFIC = "clean-traffic"


def run(argv, *, timeout=60):
    """A command's exit status and output; never raises for a failed command."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, "LC_ALL": "C"})
    except FileNotFoundError:
        return {"rc": 127, "stdout": "", "stderr": f"{argv[0]}: not found"}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "stdout": "", "stderr": f"{argv[0]}: timed out after {timeout}s"}
    return {"rc": result.returncode, "stdout": result.stdout, "stderr": result.stderr.strip()}


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def mac_bytes(text):
    return bytes(int(part, 16) for part in text.split(":"))


def mac_text(raw):
    return ":".join(f"{byte:02x}" for byte in raw)


# ---------------------------------------------------------------------------
# In the guest
# ---------------------------------------------------------------------------

def own_interface():
    """The interface of the guest's default route, its IPv4 address and MAC."""
    routes = json.loads(run(["ip", "-j", "-4", "route", "show", "default"])["stdout"] or "[]")
    device = routes[0]["dev"]
    addresses = json.loads(run(["ip", "-j", "-4", "addr", "show", "dev", device])["stdout"])
    address = next(info["local"] for entry in addresses for info in entry["addr_info"]
                   if info.get("family") == "inet")
    with open(f"/sys/class/net/{device}/address", encoding="utf-8") as stream:
        mac = stream.read().strip()
    return {"device": device, "address": address, "mac": mac}


def arp_frame(own, op, sender_ip, target_ip, destination=BROADCAST_MAC, target_mac=b"\0" * 6):
    """An Ethernet frame carrying one ARP packet from OWN's MAC: a request
    (OP 1) or a reply (OP 2)."""
    source = mac_bytes(own["mac"])
    return (destination + source + struct.pack("!H", ETH_P_ARP)
            + struct.pack("!HHBBH", 1, ETH_P_IP, 6, 4, op) + source
            + socket.inet_aton(sender_ip) + target_mac + socket.inet_aton(target_ip))


def is_arp_reply_from(frame, address):
    """Whether FRAME is an ARP reply whose sender is ADDRESS."""
    return (len(frame) >= 42 and struct.unpack("!H", frame[12:14])[0] == ETH_P_ARP
            and struct.unpack("!H", frame[20:22])[0] == 2
            and frame[28:32] == socket.inet_aton(address))


def arp_answered(own, target_ip, timeout):
    """Whether an ARP request for TARGET_IP is answered on the guest's segment."""
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ARP)) as sock:
        sock.bind((own["device"], 0))
        sock.send(arp_frame(own, 1, own["address"], target_ip))
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                frame = sock.recv(2048)
            except socket.timeout:
                break
            if is_arp_reply_from(frame, target_ip):
                return True
    return False


def icmp_echo(ident):
    """An ICMP echo request, its checksum filled in."""
    payload = b"arkhai-guest-isolation"
    header = struct.pack("!BBHHH", 8, 0, 0, ident, 1)
    return struct.pack("!BBHHH", 8, 0, checksum(header + payload), ident, 1) + payload


def is_echo_reply(packet, ident):
    """Whether PACKET, an IPv4 packet as a raw ICMP socket reads it, is the
    echo reply to the request with IDENT."""
    offset = (packet[0] & 0x0F) * 4
    if len(packet) < offset + 8:
        return False
    kind, _, _, reply_ident, _ = struct.unpack("!BBHHH", packet[offset:offset + 8])
    return kind == 0 and reply_ident == ident


def icmp_answered(target_ip, timeout):
    """Whether an ICMP echo request to TARGET_IP is answered."""
    ident = random.randrange(1, 0xFFFF)
    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
        sock.sendto(icmp_echo(ident), (target_ip, 0))
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                data, (source, _) = sock.recvfrom(2048)
            except socket.timeout:
                break
            if source == target_ip and is_echo_reply(data, ident):
                return True
    return False


def tcp_outcome(address, port, timeout):
    """``connected``, ``reset`` (the destination answered with a refusal),
    ``unreachable`` or ``timeout``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((address, port))
        except socket.timeout:
            return "timeout"
        except OSError as error:
            if error.errno == errno.ECONNREFUSED:
                return "reset"
            if error.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH):
                return "unreachable"
            if error.errno == errno.ETIMEDOUT:
                return "timeout"
            return f"error: {error.strerror}"
    return "connected"


def accept_redirects(device, value=None):
    """The guest's ``accept_redirects`` for all interfaces and DEVICE, set to
    VALUE first when one is given; the old values are returned."""
    old = {}
    for scope in ("all", device):
        path = f"/proc/sys/net/ipv4/conf/{scope}/accept_redirects"
        with open(path, encoding="utf-8") as stream:
            old[scope] = stream.read().strip()
        if value is not None:
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(value[scope] if isinstance(value, dict) else value)
    return old


def peers(request):
    """ARP, ICMP and TCP to another guest, directly, then through the gateway
    by a host route the probe adds and removes.

    The host answers a packet it would forward back out of the bridge with an
    ICMP redirect before its filter drops it, and a guest accepting the redirect
    sends what follows straight to the other guest. So the guest accepts no
    redirect while the route stands, and the route, added afresh, carries none
    an earlier probe cached; both are restored after."""
    own, peer, gateway = own_interface(), request["peer"], request["gateway"]
    timeout, port = request.get("timeout", 3), request.get("port", 22)
    result = {"own": own, "peer": peer, "direct": {
        "arp_answered": arp_answered(own, peer, timeout),
        "icmp_answered": icmp_answered(peer, timeout),
        "tcp": tcp_outcome(peer, port, timeout),
    }}
    redirects = accept_redirects(own["device"], "0")
    route = ["ip", "-4", "route", "replace", f"{peer}/32", "via", gateway, "dev", own["device"]]
    added = run(route)
    try:
        result["gateway"] = {
            "route_added": added["rc"] == 0, "route_error": added["stderr"],
            "icmp_answered": icmp_answered(peer, timeout) if added["rc"] == 0 else None,
            "tcp": tcp_outcome(peer, port, timeout) if added["rc"] == 0 else None,
        }
    finally:
        if added["rc"] == 0:
            run(["ip", "-4", "route", "del", f"{peer}/32", "via", gateway, "dev", own["device"]])
        accept_redirects(own["device"], redirects)
    return result


def claim(request):
    """Gratuitous ARP replies, broadcast, claiming PEER's address with this
    guest's MAC."""
    own, peer = own_interface(), request["peer"]
    sent = 0
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ARP)) as sock:
        sock.bind((own["device"], 0))
        for _ in range(request.get("count", 5)):
            sock.send(arp_frame(own, 2, peer, peer, target_mac=BROADCAST_MAC))
            sent += 1
            time.sleep(0.2)
    return {"own": own, "claimed": peer, "sent": sent}


def dhcp_discover_frame(mac, xid, ip_id=0):
    """A broadcast DHCPDISCOVER from MAC, as an Ethernet frame: BOOTP with the
    broadcast flag, MAC as its client address, and the DHCP magic cookie, a
    message type of discover and a parameter request list."""
    source = mac_bytes(mac)
    bootp = (struct.pack("!BBBBIHH", 1, 1, 6, 0, xid, 0, 0x8000) + b"\0" * 16
             + source + b"\0" * 10 + b"\0" * 192 + bytes([99, 130, 83, 99])
             + bytes([53, 1, 1, 55, 3, 1, 3, 6, 255]))
    udp = struct.pack("!HHHH", 68, 67, 8 + len(bootp), 0) + bootp
    header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), ip_id, 0,
                         64, socket.IPPROTO_UDP, 0, b"\0" * 4, b"\xff" * 4)
    header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
    return BROADCAST_MAC + source + struct.pack("!H", ETH_P_IP) + header + udp


def is_offer(frame, xid, server):
    """Whether FRAME is SERVER's BOOTP reply to the client port for XID."""
    ip = frame[14:]
    if len(frame) < 14 or struct.unpack("!H", frame[12:14])[0] != ETH_P_IP \
            or len(ip) < 28 or ip[9] != socket.IPPROTO_UDP:
        return False
    offset = (ip[0] & 0x0F) * 4
    if struct.unpack("!H", ip[offset + 2:offset + 4])[0] != 68:
        return False
    reply = ip[offset + 8:]
    return (len(reply) > 240 and reply[0] == 2 and struct.unpack("!I", reply[4:8])[0] == xid
            and ip[12:16] == socket.inet_aton(server))


def dhcp_offered(own, server, timeout):
    """Whether a DHCPDISCOVER from the guest's own MAC is answered by an offer
    from SERVER. A discover takes no lease, so the guest's own is untouched."""
    xid = random.randrange(1, 0xFFFFFFFF)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP)) as sock:
        sock.bind((own["device"], 0))
        sock.send(dhcp_discover_frame(own["mac"], xid, random.randrange(0xFFFF)))
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                data = sock.recv(4096)
            except socket.timeout:
                break
            if is_offer(data, xid, server):
                return True
    return False


def dns_answered(server, timeout):
    """Whether a DNS query to SERVER is answered, whatever its answer."""
    ident = random.randrange(0xFFFF)
    query = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0) + b"\x09localhost\x00" \
        + struct.pack("!HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.sendto(query, (server, 53))
            while True:
                data, (source, _) = sock.recvfrom(2048)
                if source == server and data[:2] == struct.pack("!H", ident):
                    return True
        except (socket.timeout, OSError):
            return False


def policy(request):
    """What the guest policy decides for this guest: DHCP and DNS on its
    host, a host port, and TCP to each destination named."""
    own, gateway = own_interface(), request["gateway"]
    timeout = request.get("timeout", 3)
    result = {"own": own}
    if request.get("dhcp_dns"):
        result["dhcp_offered"] = dhcp_offered(own, gateway, timeout)
        result["dns_answered"] = dns_answered(gateway, timeout)
    if request.get("host_port"):
        result["host_port"] = tcp_outcome(gateway, request["host_port"], timeout)
    result["destinations"] = {}
    for address in request.get("destinations", []):
        attempts = []
        for attempt in range(request.get("attempts", 1)):
            if attempt:
                time.sleep(request.get("interval", 0))
            attempts.append(tcp_outcome(address, request.get("port", 80), timeout))
        result["destinations"][address] = attempts
    return result


def peer_address(_request):
    """The buyer session's peer, as the guest sees it."""
    connection = os.environ.get("SSH_CONNECTION", "").split()
    return {"peer": connection[0] if connection else None}


# ---------------------------------------------------------------------------
# On the host
# ---------------------------------------------------------------------------

def daemon_version(printed):
    """The libvirt daemon's version from ``virsh version --daemon``."""
    for line in printed.splitlines():
        if line.startswith("Running against daemon:"):
            return line.split(":", 1)[1].strip()
    return None


def libvirt_version():
    return daemon_version(run(["virsh", "version", "--daemon"])["stdout"])


def version(_request):
    ufw = run(["ufw", "status"])
    return {"libvirt": libvirt_version(),
            "ufw_active": ufw["rc"] == 0 and "Status: active" in ufw["stdout"]}


def counters(_request):
    """The policy's chains with their counters, and the built-in chains' rules."""
    return {
        "guest_in": run(["iptables", "-w", "-L", "ARKHAI-GUEST-IN", "-v", "-x", "-n"]),
        "guest_fwd": run(["iptables", "-w", "-L", "ARKHAI-GUEST-FWD", "-v", "-x", "-n"]),
        "input": run(["iptables", "-w", "-S", "INPUT"]),
        "forward": run(["iptables", "-w", "-S", "FORWARD"]),
    }


def unit_properties(printed):
    """``systemctl show -p …`` as a mapping of property to value."""
    return dict(line.split("=", 1) for line in printed.splitlines() if "=" in line)


def unit_exit(unit):
    return unit_properties(run(["systemctl", "show", "-p", "ExecMainExitTimestampMonotonic",
                                "-p", "Result", "-p", "ActiveState", unit])["stdout"])


def restart_libvirtd(request):
    """Restart libvirtd, then wait, bounded, for the guest policy's unit, which
    every libvirtd start runs, to have run again."""
    unit = "arkhai-guest-policy.service"
    before = unit_exit(unit).get("ExecMainExitTimestampMonotonic")
    restarted = run(["systemctl", "restart", "libvirtd.service"], timeout=RESTART_SECONDS)
    deadline = time.monotonic() + request.get("bound", POLICY_RERUN_SECONDS)
    after = unit_exit(unit)
    while after.get("ExecMainExitTimestampMonotonic") == before and time.monotonic() < deadline:
        time.sleep(0.5)
        after = unit_exit(unit)
    return {"restart": restarted, "policy_unit": after,
            "policy_unit_ran": after.get("ExecMainExitTimestampMonotonic") != before,
            "libvirtd_active": run(["systemctl", "is-active", "libvirtd.service"])["stdout"].strip()}


def reload_ufw(_request):
    """Reload UFW, whose after.init hook runs while it reloads."""
    status = run(["ufw", "status"])
    if status["rc"] != 0 or "Status: active" not in status["stdout"]:
        return {"ufw_active": False, "status": status}
    return {"ufw_active": True, "reload": run(["ufw", "reload"], timeout=RESTART_SECONDS)}


def refresh_neighbour(request):
    """The host's neighbour entry for a guest, made fresh by a ping the host
    sends; the guest's reply reaches the host through the guest policy's
    accept of established connections."""
    return {"ping": run(["ping", "-c", "1", "-W", "2", request["address"]])}


def neighbour(request):
    shown = run(["ip", "-j", "-4", "neigh", "show", request["address"], "dev", request["bridge"]])
    entries = json.loads(shown["stdout"] or "[]")
    return {"lladdr": entries[0].get("lladdr") if entries else None,
            "state": entries[0].get("state") if entries else None}


def default_network_interface(printed):
    """The tap and MAC of the interface on the default network that ``virsh
    domiflist`` lists, or ``(None, None)``."""
    for line in printed.splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[1] == "network" and fields[2] == "default":
            return fields[0], fields[4]
    return None, None


def default_interface(guest):
    return default_network_interface(run(["virsh", "domiflist", guest])["stdout"])


def guest_state(request):
    """A guest's tap port, its live filter binding, and its live and saved
    definitions, as the host reports them."""
    guest = request["guest"]
    tap, mac = default_interface(guest)
    return {
        "tap": tap, "mac": mac,
        "link": run(["bridge", "-d", "link", "show", "dev", tap]) if tap else None,
        "bindings": run(["virsh", "nwfilter-binding-list"]),
        "live": run(["virsh", "dumpxml", guest]),
        "saved": run(["virsh", "dumpxml", "--inactive", guest]),
    }


def interface_element(xml, mac):
    root = ET.fromstring(xml)
    for element in root.findall("./devices/interface"):
        address = element.find("mac")
        if address is not None and address.get("address", "").lower() == mac.lower():
            element.tail = None
            return element
    raise LookupError(f"no interface {mac}")


def update_device(guest, element, flag, directory):
    path = os.path.join(directory, "interface.xml")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(ET.tostring(element, encoding="unicode"))
    return run(["virsh", "update-device", guest, path, flag])


def plant(request):
    """A running guest given the state of one created without the isolated,
    filtered interface: its port's isolation cleared, its filter detached live
    where libvirt allows that, and its saved definition without either."""
    guest = request["guest"]
    tap, mac = default_interface(guest)
    if tap is None:
        raise LookupError(f"{guest} has no interface on the default network")
    result = {"tap": tap, "mac": mac,
              "isolation_cleared": run(["bridge", "link", "set", "dev", tap, "isolated", "off"])}
    with tempfile.TemporaryDirectory(prefix="arkhai-plant-") as directory:
        live = interface_element(run(["virsh", "dumpxml", guest])["stdout"], mac)
        for ref in live.findall("filterref"):
            live.remove(ref)
        result["live_filter_detached"] = update_device(guest, live, "--live", directory)
        saved = interface_element(run(["virsh", "dumpxml", "--inactive", guest])["stdout"], mac)
        for child in saved.findall("filterref") + saved.findall("port"):
            saved.remove(child)
        result["saved_stripped"] = update_device(guest, saved, "--config", directory)
    result["libvirt"] = libvirt_version()
    return result


def converge(_request):
    """The host kit's installed convergence command, and the lines it printed."""
    ran = run([CONVERGE], timeout=CONVERGE_SECONDS)
    lines = []
    for line in ran["stdout"].splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            lines.append({"unparsed": line})
    return {"rc": ran["rc"], "stderr": ran["stderr"], "lines": lines}


def egress(request):
    """How many TCP packets to DESTINATION and PORT left the host on the
    interface the host routes DESTINATION through, within SECONDS. The packet
    leaves after masquerade, so its source is the host's, not the guest's."""
    route = json.loads(run(["ip", "-j", "-4", "route", "get", request["destination"]])["stdout"] or "[]")
    device = route[0]["dev"] if route else None
    if device is None:
        return {"device": None, "seen": 0}
    seen = watch_egress(device, request["destination"], request["port"], request.get("seconds", 15))
    return {"device": device, "seen": seen}


#: The egress watch's socket: cooked, and bound to every protocol, since Linux
#: hands a transmitted frame only to packet sockets bound to ``ETH_P_ALL``; one
#: bound to IPv4 alone sees received frames and never a sent one.
EGRESS_SOCKET = (socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(ETH_P_ALL))


def packet_socket():
    """A packet socket for the egress watch, as ``EGRESS_SOCKET`` opens it."""
    return socket.socket(*EGRESS_SOCKET)


def watch_egress(device, destination, port, seconds):
    """How many TCP packets to DESTINATION and PORT left on DEVICE within
    SECONDS. The socket takes every frame, so each is matched on its direction,
    link-layer protocol, destination and port."""
    seen = 0
    with packet_socket() as sock:
        sock.bind((device, 0))
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                data, address = sock.recvfrom(4096)
            except socket.timeout:
                break
            if is_outgoing_tcp_to(data, address[1], address[2], destination, port):
                seen += 1
    return seen


def is_outgoing_tcp_to(packet, protocol, packet_type, destination, port):
    """Whether PACKET, a frame's payload as a cooked packet socket reads it with
    its link-layer PROTOCOL and PACKET_TYPE, left this host as IPv4 TCP to
    DESTINATION and PORT."""
    if (packet_type != PACKET_OUTGOING or protocol != ETH_P_IP or len(packet) < 24
            or packet[9] != socket.IPPROTO_TCP):
        return False
    offset = (packet[0] & 0x0F) * 4
    return (packet[16:20] == socket.inet_aton(destination) and len(packet) >= offset + 4
            and struct.unpack("!H", packet[offset + 2:offset + 4])[0] == port)


OPERATIONS = {
    "interface": lambda request: own_interface(),
    "peers": peers,
    "claim": claim,
    "policy": policy,
    "peer": peer_address,
    "version": version,
    "counters": counters,
    "restart_libvirtd": restart_libvirtd,
    "reload_ufw": reload_ufw,
    "refresh_neighbour": refresh_neighbour,
    "neighbour": neighbour,
    "guest_state": guest_state,
    "plant": plant,
    "converge": converge,
    "egress": egress,
}


if __name__ == "__main__":
    REQUEST = json.loads(sys.argv[1])
    OPERATION = REQUEST.get("operation")
    try:
        ANSWER = OPERATIONS[OPERATION](REQUEST)
    except Exception as error:  # reported to the scenario, which fails naming it
        ANSWER = {"error": f"{OPERATION}: {type(error).__name__}: {error}"}
    print(json.dumps(ANSWER))
