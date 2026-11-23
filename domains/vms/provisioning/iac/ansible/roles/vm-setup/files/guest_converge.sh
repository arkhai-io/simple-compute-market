#!/bin/sh
# Converges every running VM guest to the interface a guest is created with
# (vm-management's templates/guest-interface-args.j2): an isolated bridge port
# under libvirt's clean-traffic filter. A guest created before guests were
# isolated holds neither, and an isolated port can still be reached from one
# that is not, so each running guest is converged while it runs:
#
#   - its tap's bridge port is set isolated (`bridge link set ... isolated on`),
#     which does not drop the link;
#   - clean-traffic is applied live (`virsh update-device --live`) where libvirt
#     accepts it, and otherwise waits for the guest's next start;
#   - both are written into its saved definition (`virsh update-device
#     --config`), so a restart, an autostart or a host reboot keeps them.
#
# The live update leaves the interface's <port> element as libvirt holds it:
# the port is isolated through the bridge, and whether libvirt accepts a live
# change of <port> depends on its version; asking for one where it does not
# would refuse the filter with it.
#
# The running definition still says the port is not isolated, so a tap libvirt
# attaches to the bridge again before the guest restarts, as after the network
# is restarted, comes up not isolated; the saved definition keeps the isolation
# from the guest's next start.
#
# It prints one JSON line per running guest, and nothing else on stdout:
#
#   {"name": ..., "port_isolated": true|false,
#    "filter": "live"|"next_start"|"none", "saved_definition": true|false,
#    "changed": true|false, "error": null|"..."}
#
# `filter` is `live` when the filter is bound to the running interface,
# `next_start` when it is not but the saved definition carries it, and `none`
# when neither holds it. `error` joins the reason of every step that failed, a
# live filter libvirt refused included. A guest already converged is reported
# with nothing changed. Its callers read these lines rather than virsh, and name
# each guest left unconverged; so the command exits non-zero only when it
# cannot run at all (virsh, bridge or python3 missing, no working directory, or
# the running guests unreadable), never because one guest could not be
# converged.
set -u

for required in virsh bridge python3; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "arkhai-guest-converge: $required is not installed; no guest was converged" >&2
    exit 1
  fi
done

NETWORK=default

# Reads and edits libvirt's XML, and writes the report's JSON, where a shell
# would have to parse or quote them by hand. Each mode but report reads a
# domain's XML on stdin:
#   check MAC NETWORK  prints "<port isolated: yes|no> <filter bound: yes|no>"
#                      for the interface with MAC on NETWORK; exits 3 without one
#   live MAC NETWORK   prints that interface with clean-traffic and its parameters
#   saved MAC NETWORK  prints it with the isolated port and the filter as well
#   report NAME PORT FILTER SAVED CHANGED ERROR   prints the guest's JSON line
HELPER='
import json
import sys
import xml.etree.ElementTree as ET

FILTER = "clean-traffic"
PARAMETERS = {"CTRL_IP_LEARNING": "dhcp", "DHCPSERVER": "192.168.122.1"}


def interface(mac):
    root = ET.fromstring(sys.stdin.read())
    for element in root.findall("./devices/interface"):
        address = element.find("mac")
        source = element.find("source")
        if (address is not None and address.get("address", "").lower() == mac.lower()
                and source is not None and source.get("network") == sys.argv[3]):
            return element
    sys.exit(3)


def port_isolated(element):
    port = element.find("port")
    return port is not None and port.get("isolated") == "yes"


def filter_bound(element):
    ref = element.find("filterref")
    if ref is None or ref.get("filter") != FILTER:
        return False
    held = {p.get("name"): p.get("value") for p in ref.findall("parameter")}
    return all(held.get(name) == value for name, value in PARAMETERS.items())


def with_filter(element):
    for ref in element.findall("filterref"):
        element.remove(ref)
    ref = ET.SubElement(element, "filterref", {"filter": FILTER})
    for name, value in PARAMETERS.items():
        ET.SubElement(ref, "parameter", {"name": name, "value": value})
    return element


def with_isolated_port(element):
    for port in element.findall("port"):
        element.remove(port)
    ET.SubElement(element, "port", {"isolated": "yes"})
    return element


def printed(element):
    element.tail = None
    print(ET.tostring(element, encoding="unicode"))


mode = sys.argv[1]
if mode == "check":
    element = interface(sys.argv[2])
    print("yes" if port_isolated(element) else "no", "yes" if filter_bound(element) else "no")
elif mode == "live":
    printed(with_filter(interface(sys.argv[2])))
elif mode == "saved":
    printed(with_isolated_port(with_filter(interface(sys.argv[2]))))
elif mode == "report":
    name, port, filter_state, saved, changed, error = sys.argv[2:8]
    print(json.dumps({
        "name": name,
        "port_isolated": port == "true",
        "filter": filter_state,
        "saved_definition": saved == "true",
        "changed": changed == "true",
        "error": error or None,
    }))
'

if ! WORK="$(mktemp -d)"; then
  echo "arkhai-guest-converge: cannot create a working directory; no guest was converged" >&2
  exit 1
fi
trap 'rm -rf "$WORK"' EXIT

# A command's standard error as one line, for a report's reason.
reason() {
  tr '\n' ' ' < "$WORK/stderr" | sed 's/  */ /g; s/ *$//'
}

add_error() {
  if [ -n "$errors" ]; then
    errors="$errors; $1"
  else
    errors="$1"
  fi
}

# The guest's line. A filter not bound live waits for the next start only when
# the saved definition carries it, which `saved` true says.
report() {
  if [ "$live_bound" = true ]; then
    filter=live
  elif [ "$saved" = true ]; then
    filter=next_start
  else
    filter=none
  fi
  python3 -c "$HELPER" report "$1" "$port_isolated" "$filter" "$saved" "$changed" "$errors"
}

# Sets TAP's bridge port isolated unless it is already.
converge_port() {
  if ! bridge -d link show dev "$1" > "$WORK/link" 2> "$WORK/stderr"; then
    port_isolated=false
    add_error "cannot read the bridge port of $1: $(reason)"
    return
  fi
  if grep -Eq '(^|[[:space:]])isolated on([[:space:]]|$)' "$WORK/link"; then
    return
  fi
  if bridge link set dev "$1" isolated on 2> "$WORK/stderr"; then
    changed=true
  else
    port_isolated=false
    add_error "cannot isolate the bridge port of $1: $(reason)"
  fi
}

# Binds clean-traffic to the running interface with MAC unless it is bound.
converge_live_filter() {
  if ! python3 -c "$HELPER" check "$2" "$NETWORK" < "$WORK/live.xml" > "$WORK/state" 2> "$WORK/stderr"; then
    live_bound=false
    add_error "its running definition holds no interface $2 on the $NETWORK network"
    return
  fi
  if [ "$(cut -d' ' -f2 "$WORK/state")" = yes ]; then
    return
  fi
  python3 -c "$HELPER" live "$2" "$NETWORK" < "$WORK/live.xml" > "$WORK/live-interface.xml"
  if virsh update-device "$1" "$WORK/live-interface.xml" --live > /dev/null 2> "$WORK/stderr"; then
    changed=true
  else
    live_bound=false
    add_error "libvirt did not bind the filter live: $(reason)"
  fi
}

# Writes the isolated port and the filter into the saved definition of the
# interface with MAC unless it carries both.
converge_saved_definition() {
  if ! python3 -c "$HELPER" check "$2" "$NETWORK" < "$WORK/saved.xml" > "$WORK/state" 2> "$WORK/stderr"; then
    saved=false
    add_error "its saved definition holds no interface $2 on the $NETWORK network"
    return
  fi
  if [ "$(cat "$WORK/state")" = "yes yes" ]; then
    return
  fi
  python3 -c "$HELPER" saved "$2" "$NETWORK" < "$WORK/saved.xml" > "$WORK/saved-interface.xml"
  if virsh update-device "$1" "$WORK/saved-interface.xml" --config > /dev/null 2> "$WORK/stderr"; then
    changed=true
  else
    saved=false
    add_error "cannot write the saved definition of $2: $(reason)"
  fi
}

converge_guest() {
  name="$1"
  port_isolated=true
  live_bound=true
  saved=true
  changed=false
  errors=""

  if ! virsh domiflist "$name" > "$WORK/interfaces" 2> "$WORK/stderr"; then
    port_isolated=false live_bound=false saved=false
    add_error "cannot read its interfaces: $(reason)"
    report "$name"
    return
  fi
  # A row is "<tap> <type> <source> <model> <mac>"; the header's type is "Type".
  awk -v network="$NETWORK" '$2 == "network" && $3 == network { print $1, $5 }' \
    "$WORK/interfaces" > "$WORK/taps"
  if [ ! -s "$WORK/taps" ]; then
    port_isolated=false live_bound=false saved=false
    add_error "it has no interface on the $NETWORK network"
    report "$name"
    return
  fi
  if ! virsh dumpxml "$name" > "$WORK/live.xml" 2> "$WORK/stderr"; then
    live_bound=false
    add_error "cannot read its running definition: $(reason)"
    : > "$WORK/live.xml"
  fi
  if ! virsh dumpxml --inactive "$name" > "$WORK/saved.xml" 2> "$WORK/stderr"; then
    saved=false
    add_error "cannot read its saved definition: $(reason)"
    : > "$WORK/saved.xml"
  fi

  while read -r tap mac <&4; do
    converge_port "$tap"
    if [ -s "$WORK/live.xml" ]; then
      converge_live_filter "$name" "$mac"
    fi
    if [ -s "$WORK/saved.xml" ]; then
      converge_saved_definition "$name" "$mac"
    fi
  done 4< "$WORK/taps"

  report "$name"
}

if ! virsh list --state-running --name > "$WORK/running" 2> "$WORK/stderr"; then
  echo "arkhai-guest-converge: cannot list the running guests: $(reason)" >&2
  exit 1
fi

while IFS= read -r guest <&3; do
  if [ -n "$guest" ]; then
    converge_guest "$guest"
  fi
done 3< "$WORK/running"
