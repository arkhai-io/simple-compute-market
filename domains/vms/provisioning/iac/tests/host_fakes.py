"""Stateful fakes of the host commands a VM teardown calls.

`shell_harness` runs a task's real shell with its external commands replaced on
`PATH`. A teardown reads state back and acts on it — it lists rules and deletes
the ones it lists, reads a network's reservations and deletes one — so its
fakes keep that state between calls, in files under one directory, and answer
as the real commands answer:

- `iptables -S` prints rules in `iptables -S` form, a comment quoted as
  iptables 1.8 quotes it, and `-D` deletes the first rule equal to its
  arguments, or fails as iptables does when none is;
- `virsh` keeps domains with their state, address, MAC, and storage, and the
  `default` network's DHCP reservations in `net-dumpxml` form;
- `ufw` keeps numbered rules with their comments;
- `curl` exits with each status a test queued, in order, then succeeds.

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
"""

_IPTABLES = _PREAMBLE + r'''
args = sys.argv[1:]
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

_IPTABLES_SAVE = _PREAMBLE + r'''
for table in ("filter", "nat"):
    path = STATE / f"iptables.{table}"
    if path.exists():
        print(f"*{table}")
        print(path.read_text(encoding="utf-8"), end="")
        print("COMMIT")
'''

_VIRSH = _PREAMBLE + r'''
state_path = STATE / "virsh.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
domains, hosts = state["domains"], state["hosts"]
args = sys.argv[1:]
command = args[0]

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

def domain(name):
    if name not in domains:
        print(f"error: failed to get domain '{name}'", file=sys.stderr)
        sys.exit(1)
    return domains[name]

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
elif command == "domiflist":
    found = domain(args[1])
    print(f" vnet0      network   default   virtio   {found['mac']}")
elif command == "dumpxml":
    domain(args[1])
    print("<domain/>")
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
            "iptables-save": _IPTABLES_SAVE,
            "virsh": _VIRSH,
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
        self, *, domains: dict, hosts: list[dict], network_unreadable: bool = False
    ) -> None:
        (self.state / "virsh.json").write_text(
            json.dumps(
                {"domains": domains, "hosts": hosts, "network_unreadable": network_unreadable}
            ),
            encoding="utf-8",
        )

    def virsh(self) -> dict:
        return json.loads((self.state / "virsh.json").read_text(encoding="utf-8"))

    def set_ufw(self, *, active: bool, rules: list[dict]) -> None:
        (self.state / "ufw.json").write_text(
            json.dumps({"active": active, "rules": rules}), encoding="utf-8"
        )

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
