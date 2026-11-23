"""Stateful fakes of the host commands a VM teardown, the guest policy's
installer, and guest convergence call.

`shell_harness` runs a task's real shell with its external commands replaced on
`PATH`. A teardown reads state back and acts on it — it lists rules and deletes
the ones it lists, reads a network's reservations and deletes one — so its
fakes keep that state between calls, in files under one directory, and answer
as the real commands answer:

- `iptables -S` prints rules in `iptables -S` form, a comment quoted as
  iptables 1.8 quotes it, and `-D` deletes the first rule equal to its
  arguments, or fails as iptables does when none is; `-w`, waiting for the
  xtables lock, is accepted and changes nothing;
- `iptables-restore --noflush` applies a table's chain declarations, appends,
  inserts and deletes to those rules in one transaction, changing nothing when
  a command fails;
- `virsh` keeps domains with their state, address, MAC, and storage, and the
  `default` network's DHCP reservations in `net-dumpxml` form; a domain given
  `interfaces` also has its running and saved definitions, each interface's
  `<port>` and `<filterref>` in each, which `dumpxml [--inactive]` prints,
  `domiflist` lists, and `update-device --live|--config` replaces, refusing
  any live change of `<port>`;
- `bridge` reads and sets a running guest's tap port isolation flag;
- `ufw` keeps numbered rules with their comments;
- `curl` exits with each status a test queued, in order, then succeeds;
- a `virsh` subcommand, or `rm` of one path, fails as many times as a test asked
  (`FakeHost.refuse`), then behaves as before.

Every call is appended to `calls`, so a test can assert what was never run.
Addresses are RFC 5737 documentation addresses and names are synthetic.

`FakeGpuHost` fakes what a create reads to choose a GPU: a sysfs PCI tree whose
devices carry their own `boot_vga` flag and `driver` link, `lspci` printing
`-vmm` records in a real host's field order, and the host devices each defined
guest has attached. Its GPUs are synthetic devices at arbitrary addresses,
not any real machine's.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path


_PREAMBLE = f"""#!{sys.executable}
import json, os, shlex, sys
from pathlib import Path
STATE = Path(os.environ["FAKE_HOST_STATE"])
with open(STATE / "calls", "a", encoding="utf-8") as calls:
    calls.write(" ".join([Path(sys.argv[0]).name] + [shlex.quote(a) for a in sys.argv[1:]]) + "\\n")

def refused(key):
    # Whether `FakeHost.refuse` queued a refusal of KEY, using one up if so.
    path = STATE / "refusals.json"
    refusals = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {{}}
    if refusals.get(key, 0) < 1:
        return False
    refusals[key] -= 1
    path.write_text(json.dumps(refusals), encoding="utf-8")
    return True
"""

_IPTABLES = _PREAMBLE + r'''
args = [a for a in sys.argv[1:] if a != "-w"]
table = "filter"
if args[:1] == ["-t"]:
    table, args = args[1], args[2:]
path = STATE / f"iptables.{table}"
rules = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
op = args[0]
if op == "-S":
    chains = [args[1]] if len(args) > 1 else sorted({shlex.split(r)[1] for r in rules})
    for chain in chains:
        print(f"-P {chain} ACCEPT")
        for rule in rules:
            if shlex.split(rule)[1] == chain:
                print(rule)
    sys.exit(0)
if op == "-D":
    for index, rule in enumerate(rules):
        if shlex.split(rule)[1:] == args[1:]:
            del rules[index]
            path.write_text("".join(r + "\n" for r in rules), encoding="utf-8")
            sys.exit(0)
    print("iptables: Bad rule (does a matching rule exist in that chain?).", file=sys.stderr)
    sys.exit(1)
print(f"fake iptables: unsupported {args}", file=sys.stderr)
sys.exit(2)
'''

# `iptables-restore --noflush`: a table's commands apply to a copy of its rules,
# written back only at COMMIT, so a failing command changes nothing, as the real
# command's one transaction per table does. A chain declaration (`:CHAIN`)
# flushes that chain, `-A` appends to it, `-I CHAIN N` inserts at position N,
# and `-D CHAIN rule` deletes the first rule equal to it, or fails. Unlike the
# real command, it stores each rule as written, not as iptables normalises it
# (no implicit `-m udp`, no `/32`), and flushes a built-in chain declared too.
_IPTABLES_RESTORE = _PREAMBLE + r'''
if sorted(a for a in sys.argv[1:] if a != "-w") != ["--noflush"]:
    print(f"fake iptables-restore: unsupported {sys.argv[1:]}", file=sys.stderr)
    sys.exit(2)
rules, path = None, None
for number, line in enumerate(sys.stdin.read().splitlines(), start=1):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("*"):
        path = STATE / f"iptables.{line[1:]}"
        rules = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        continue
    if line == "COMMIT":
        path.write_text("".join(r + "\n" for r in rules), encoding="utf-8")
        rules = None
        continue
    if line.startswith(":"):
        chain = line[1:].split()[0]
        rules = [r for r in rules if shlex.split(r)[1] != chain]
        continue
    tokens = shlex.split(line)
    op, chain = tokens[0], tokens[1]
    positions = [i for i, r in enumerate(rules) if shlex.split(r)[1] == chain]
    if op == "-A":
        rules.insert(positions[-1] + 1 if positions else len(rules), line)
    elif op == "-I":
        index = int(tokens[2]) - 1
        spec = shlex.join(["-A", chain] + tokens[3:])
        rules.insert(positions[index] if index < len(positions) else len(rules), spec)
    elif op == "-D":
        for i in positions:
            if shlex.split(rules[i])[2:] == tokens[2:]:
                del rules[i]
                break
        else:
            print(f"iptables-restore: line {number} failed", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"fake iptables-restore: unsupported {line}", file=sys.stderr)
        sys.exit(2)
'''

_IPTABLES_SAVE = _PREAMBLE + r'''
for table in ("filter", "nat"):
    path = STATE / f"iptables.{table}"
    if path.exists():
        print(f"*{table}")
        print(path.read_text(encoding="utf-8"), end="")
        print("COMMIT")
'''

_VIRSH = _PREAMBLE + r'''
import xml.etree.ElementTree as ET
state_path = STATE / "virsh.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
domains, hosts = state["domains"], state["hosts"]
args = sys.argv[1:]
command = args[0]
if refused(f"virsh {command}"):
    print(f"error: Failed to {command} domain '{args[-1]}'", file=sys.stderr)
    sys.exit(1)

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

def domain(name):
    if name not in domains:
        print(f"error: failed to get domain '{name}'", file=sys.stderr)
        sys.exit(1)
    return domains[name]

def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)

def domain_xml(name, found, live):
    # A domain's running or saved definition, as `dumpxml` and `dumpxml
    # --inactive` print it: only the running one names the tap, the bridge, and
    # the device's alias.
    lines = ["<domain type='kvm'>", f"  <name>{name}</name>", "  <devices>"]
    for nic in found["interfaces"]:
        held = nic["live" if live else "saved"]
        lines += ["    <interface type='network'>", f"      <mac address='{nic['mac']}'/>"]
        if live:
            lines += [
                f"      <source network='{nic['source']}' bridge='virbr0'/>",
                f"      <target dev='{nic['tap']}'/>",
            ]
        else:
            lines.append(f"      <source network='{nic['source']}'/>")
        lines.append("      <model type='virtio'/>")
        if held["port"]:
            lines.append("      <port isolated='yes'/>")
        if held["filterref"]:
            lines.append(f"      <filterref filter='{held['filterref']['filter']}'>")
            for key, value in held["filterref"]["parameters"].items():
                lines.append(f"        <parameter name='{key}' value='{value}'/>")
            lines.append("      </filterref>")
        if live:
            lines.append("      <alias name='net0'/>")
        lines += [
            "      <address type='pci' domain='0x0000' bus='0x01' slot='0x00' function='0x0'/>",
            "    </interface>",
        ]
    return "\n".join(lines + ["  </devices>", "</domain>"])

def update_device(name, found, path, flags):
    # Replaces the interface the file names by its MAC, in the running
    # definition (--live) or the saved one (--config). A live change of its
    # filter, where the domain says libvirt refuses one, fails as libvirt's
    # refusal does, changing nothing. So does any live change of its <port>,
    # which libvirt accepts in some versions and not in others, so that a
    # command asking for one is caught here.
    element = ET.parse(path).getroot()
    mac = element.find("mac").get("address")
    nic = next((n for n in found["interfaces"] if n["mac"].lower() == mac.lower()), None)
    if nic is None:
        fail(f"operation failed: no device matching MAC address {mac} found")
    source, model = element.find("source"), element.find("model")
    if source is None or source.get("network") != nic["source"] or model is None:
        fail("Operation not supported: cannot change network interface type or model")
    port = element.find("port")
    port = port is not None and port.get("isolated") == "yes"
    ref = element.find("filterref")
    if ref is not None:
        ref = {"filter": ref.get("filter"),
               "parameters": {p.get("name"): p.get("value") for p in ref.findall("parameter")}}
    if flags == ["--live"]:
        if found["state"] != "running":
            fail("Requested operation is not valid: domain is not running")
        if port != nic["live"]["port"]:
            fail("Operation not supported: cannot modify network device port isolation")
        if ref != nic["live"]["filterref"] and found.get("live_filter_refused"):
            fail("Operation not supported: cannot modify network device filter")
        nic["live"]["filterref"] = ref
    elif flags == ["--config"]:
        if found.get("transient"):
            fail("Requested operation is not valid: cannot modify device on transient domain")
        nic["saved"] = {"port": port, "filterref": ref}
    else:
        print(f"fake virsh: unsupported update-device {flags}", file=sys.stderr)
        sys.exit(2)
    save()
    print("Device updated successfully")

if command == "net-dumpxml":
    if state.get("network_unreadable"):
        print("error: network 'default' not found", file=sys.stderr)
        sys.exit(1)
    print("<network>\n  <name>default</name>\n  <ip address='192.0.2.254' netmask='255.255.255.0'>\n    <dhcp>")
    for host in hosts:
        print(f"      <host mac='{host['mac']}' name='{host['name']}' ip='{host['ip']}'/>")
    print("    </dhcp>\n  </ip>\n</network>")
elif command == "net-update":
    element = args[args.index("ip-dhcp-host") + 1]
    mac = element.split("mac='", 1)[1].split("'", 1)[0]
    kept = [h for h in hosts if h["mac"] != mac]
    if len(kept) == len(hosts):
        print("error: couldn't locate a matching dhcp host entry", file=sys.stderr)
        sys.exit(1)
    state["hosts"] = kept
    save()
elif command == "list" and "--state-running" in args:
    for name, found in domains.items():
        if found["state"] == "running":
            print(name)
    print()
elif command == "list":
    for name in domains:
        print(name)
elif command == "dominfo":
    domain(args[1])
    print(f"Name:           {args[1]}")
elif command == "domstate":
    print(domain(args[1])["state"])
elif command == "domifaddr":
    found = domain(args[1])
    if found["state"] == "running" and found.get("address"):
        print(" Name       MAC address          Protocol     Address")
        print(f" vnet0      {found['mac']}    ipv4         {found['address']}/24")
elif command == "domiflist" and "interfaces" in domain(args[1]):
    print(" Interface   Type      Source    Model    MAC")
    print("-------------------------------------------------------")
    for nic in domain(args[1])["interfaces"]:
        print(f" {nic['tap']:<11} network   {nic['source']:<9} virtio   {nic['mac']}")
elif command == "domiflist":
    found = domain(args[1])
    print(f" vnet0      network   default   virtio   {found['mac']}")
elif command == "dumpxml" and "interfaces" in domain(next(a for a in args[1:] if not a.startswith("-"))):
    name = next(a for a in args[1:] if not a.startswith("-"))
    print(domain_xml(name, domain(name), live="--inactive" not in args))
elif command == "dumpxml":
    domain(args[1])
    print("<domain/>")
elif command == "update-device":
    update_device(args[1], domain(args[1]), args[2], args[3:])
elif command == "destroy":
    domain(args[1])["state"] = "shut off"
    save()
elif command == "undefine":
    found = domain(args[1])
    if "--remove-all-storage" in args:
        for path in found.get("storage", []):
            Path(path).unlink(missing_ok=True)
    del domains[args[1]]
    save()
else:
    print(f"fake virsh: unsupported {args}", file=sys.stderr)
    sys.exit(2)
'''

_UFW = _PREAMBLE + r'''
state_path = STATE / "ufw.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]
if args == ["status"]:
    print("Status: active" if state["active"] else "Status: inactive")
elif args == ["status", "numbered"]:
    print("Status: active\n\n     To                         Action      From\n     --                         ------      ----")
    for number, rule in enumerate(state["rules"], start=1):
        to = rule["to"]
        source = "Anywhere (v6)" if to.endswith("(v6)") else "Anywhere"
        line = f"[{number:2}] {to:<26} ALLOW IN    {source:<26}"
        if rule.get("comment"):
            line += f" # {rule['comment']}"
        print(line)
elif args[:2] == ["--force", "delete"]:
    del state["rules"][int(args[2]) - 1]
    state_path.write_text(json.dumps(state), encoding="utf-8")
else:
    print(f"fake ufw: unsupported {args}", file=sys.stderr)
    sys.exit(2)
'''

# `bridge` reads and sets a running guest's tap port flag, kept on the guest's
# interface in the `virsh` state as `bridge_isolated`, apart from the `<port>`
# element of either definition, as the kernel keeps it apart from libvirt. A
# tap the state lists under `isolation_refused` refuses the flag as a kernel
# without bridge port isolation does.
_BRIDGE = _PREAMBLE + r'''
state_path = STATE / "virsh.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]

def port(tap):
    for found in state["domains"].values():
        for nic in found.get("interfaces", []):
            if nic["tap"] == tap and found["state"] == "running":
                return nic
    print(f'Cannot find device "{tap}"', file=sys.stderr)
    sys.exit(1)

if args[:4] == ["-d", "link", "show", "dev"] and len(args) == 5:
    nic = port(args[4])
    flag = "on" if nic["bridge_isolated"] else "off"
    print(f"7: {args[4]}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master virbr0 "
          "state forwarding priority 32 cost 100 ")
    print("    hairpin off guard off root_block off fastleave off learning on flood on "
          "mcast_flood on bcast_flood on mcast_router 1 mcast_to_unicast off "
          f"neigh_suppress off vlan_tunnel off isolated {flag} locked off")
elif args[:3] == ["link", "set", "dev"] and args[4:] == ["isolated", "on"]:
    nic = port(args[3])
    if args[3] in state.get("isolation_refused", []):
        print("RTNETLINK answers: Operation not supported", file=sys.stderr)
        sys.exit(2)
    nic["bridge_isolated"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")
else:
    print(f"fake bridge: unsupported {args}", file=sys.stderr)
    sys.exit(2)
'''

# Each call takes the next exit status `set_curl_exits` queued, and succeeds
# once the queue is empty: 7 is curl's exit when nothing listens, 22 its exit
# under `-f` when the server answers with an error status.
_CURL = _PREAMBLE + r'''
path = STATE / "curl.exits"
exits = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
code = exits.pop(0) if exits else 0
path.write_text(json.dumps(exits), encoding="utf-8")
sys.exit(code)
'''

_RM = _PREAMBLE + r'''
import shutil
for target in sys.argv[1:]:
    if target.startswith("-"):
        continue
    if refused(f"rm {target}"):
        print(f"rm: cannot remove '{target}': Operation not permitted", file=sys.stderr)
        sys.exit(1)
os.execv(shutil.which("rm", path=os.defpath), ["rm"] + sys.argv[1:])
'''

# A host with neither firewalld nor a service manager the teardown can ask.
_ABSENT = _PREAMBLE + "sys.exit(3)\n"


class FakeHost:
    """One fake host's state under ``root``, and the fake commands that read it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.state.mkdir(parents=True)
        (self.state / "calls").write_text("", encoding="utf-8")
        self.set_rules("filter", [])
        self.set_rules("nat", [])
        self.set_virsh(domains={}, hosts=[])
        self.set_ufw(active=False, rules=[])

    def binaries(self) -> dict[str, str]:
        return {
            "iptables": _IPTABLES,
            "iptables-restore": _IPTABLES_RESTORE,
            "iptables-save": _IPTABLES_SAVE,
            "virsh": _VIRSH,
            "bridge": _BRIDGE,
            "ufw": _UFW,
            "curl": _CURL,
            "systemctl": _ABSENT,
            "firewall-cmd": _ABSENT,
        }

    def environment(self, base: dict[str, str]) -> dict[str, str]:
        return {**base, "FAKE_HOST_STATE": str(self.state)}

    def set_rules(self, table: str, rules: list[str]) -> None:
        (self.state / f"iptables.{table}").write_text(
            "".join(rule + "\n" for rule in rules), encoding="utf-8"
        )

    def rules(self, table: str) -> list[str]:
        return (self.state / f"iptables.{table}").read_text(encoding="utf-8").splitlines()

    def set_virsh(
        self,
        *,
        domains: dict,
        hosts: list[dict],
        network_unreadable: bool = False,
        isolation_refused: tuple[str, ...] = (),
    ) -> None:
        (self.state / "virsh.json").write_text(
            json.dumps(
                {"domains": domains, "hosts": hosts, "network_unreadable": network_unreadable,
                 "isolation_refused": list(isolation_refused)}
            ),
            encoding="utf-8",
        )

    def virsh(self) -> dict:
        return json.loads((self.state / "virsh.json").read_text(encoding="utf-8"))

    def set_ufw(self, *, active: bool, rules: list[dict]) -> None:
        (self.state / "ufw.json").write_text(
            json.dumps({"active": active, "rules": rules}), encoding="utf-8"
        )

    def refuse(self, key: str, times: int = 1) -> None:
        """Make the next TIMES calls of KEY fail as the host would refuse them:
        `virsh <subcommand>`, or `rm <path>` with `refusing_rm` installed."""
        path = self.state / "refusals.json"
        refusals = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        refusals[key] = refusals.get(key, 0) + times
        path.write_text(json.dumps(refusals), encoding="utf-8")

    def refusing_rm(self) -> dict[str, str]:
        """The host's commands with `rm` failing for each path `refuse` names as
        `rm <path>`, and removing everything else as the real `rm` does."""
        return {**self.binaries(), "rm": _RM}

    def set_curl_exits(self, exits: list[int]) -> None:
        """The exit statuses the next `curl` calls return, in order."""
        (self.state / "curl.exits").write_text(json.dumps(exits), encoding="utf-8")

    def ufw_rules(self) -> list[dict]:
        return json.loads((self.state / "ufw.json").read_text(encoding="utf-8"))["rules"]

    def calls(self) -> list[str]:
        return (self.state / "calls").read_text(encoding="utf-8").splitlines()


def quoted(rule: str) -> str:
    """A rule as `iptables -S` prints it: a comment holding a character outside
    letters, digits, `_` and `-` is quoted, as iptables 1.8 quotes it."""
    tokens = shlex.split(rule)
    for index, token in enumerate(tokens[:-1]):
        if token == "--comment":
            tokens[index + 1] = f'"{tokens[index + 1]}"'
    return " ".join(tokens)


_GPU_VIRSH = _PREAMBLE + r'''
state = json.loads((STATE / "gpu-virsh.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
if args[:1] == ["list"]:
    if state.get("list_fails"):
        print("error: failed to connect to the hypervisor", file=sys.stderr)
        sys.exit(1)
    for name in state["guests"]:
        print(name)
elif args[:1] == ["dumpxml"]:
    print("<domain type='kvm'>\n  <devices>")
    for device in state["guests"][args[1]]:
        source = device["source"]
        domain, bus, rest = source.split(":")
        slot, function = rest.split(".")
        guest_bus = device.get("guest_bus", "0x05")
        print("    <hostdev mode='subsystem' type='pci' managed='yes'>")
        print("      <source>")
        print(f"        <address domain='0x{domain}' bus='0x{bus}' slot='0x{slot}' function='0x{function}'/>")
        print("      </source>")
        print(f"      <address type='pci' domain='0x0000' bus='{guest_bus}' slot='0x00' function='0x0'/>")
        print("    </hostdev>")
    print("  </devices>\n</domain>")
else:
    print(f"fake virsh: unsupported {args}", file=sys.stderr)
    sys.exit(2)
'''

# `lspci -D -vmm` prints each record's Slot: before its Class:, the order a
# real host's lspci prints them in.
_GPU_LSPCI = _PREAMBLE + r'''
devices = json.loads((STATE / "lspci.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
if "-vmm" in args:
    for device in devices:
        print(f"Slot:\t{device['address']}")
        print(f"Class:\t{device['class']}")
        print("Vendor:\tSynthetic Vendor")
        print(f"Device:\t{device['name']}")
        print()
elif "-s" in args:
    wanted = args[args.index("-s") + 1]
    for device in devices:
        if device["address"].endswith(wanted):
            print(f"{device['address'][5:]} {device['class']}: {device['name']}")
            if "-nnk" in args and device.get("driver"):
                print(f"\tKernel driver in use: {device['driver']}")
else:
    for device in devices:
        print(f"{device['address']} {device['class']}: {device['name']}")
'''


class FakeGpuHost:
    """A host's GPUs: its sysfs PCI tree under ``root``, `lspci`, and the
    defined guests `virsh` reports with the host devices each has attached."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.state.mkdir(parents=True)
        (self.state / "calls").write_text("", encoding="utf-8")
        self.devices = root / "sys/bus/pci/devices"
        self.devices.mkdir(parents=True)
        self.drivers = root / "sys/bus/pci/drivers"
        self.drivers.mkdir(parents=True)
        self._lspci: list[dict] = []
        (self.state / "lspci.json").write_text("[]", encoding="utf-8")
        self.set_guests({})

    def add_gpu(self, address: str, *, boot: bool, driver: str | None) -> None:
        device = self.devices / address
        device.mkdir()
        (device / "boot_vga").write_text("1\n" if boot else "0\n", encoding="utf-8")
        if driver is not None:
            (self.drivers / driver).mkdir(exist_ok=True)
            (device / "driver").symlink_to(self.drivers / driver)
        self._lspci.append({"address": address, "class": "VGA compatible controller",
                            "name": "Synthetic GPU", "driver": driver})
        (self.state / "lspci.json").write_text(json.dumps(self._lspci), encoding="utf-8")

    def set_guests(self, guests: dict[str, list[dict]], *, list_fails: bool = False) -> None:
        (self.state / "gpu-virsh.json").write_text(
            json.dumps({"guests": guests, "list_fails": list_fails}), encoding="utf-8"
        )

    def binaries(self) -> dict[str, str]:
        return {"virsh": _GPU_VIRSH, "lspci": _GPU_LSPCI}

    def environment(self, base: dict[str, str]) -> dict[str, str]:
        return {**base, "FAKE_HOST_STATE": str(self.state)}
