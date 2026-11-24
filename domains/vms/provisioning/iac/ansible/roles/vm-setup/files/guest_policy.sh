#!/bin/sh
# Installs the VM guest policy: the chains ARKHAI-GUEST-IN and ARKHAI-GUEST-FWD
# from the rules file host preparation renders, each jumped to from the first
# position of INPUT and FORWARD for packets arriving from the guests' bridge;
# and ARKHAI-GUEST-V6, which drops every IPv6 packet from the bridge, jumped to
# from the first position of ip6tables' INPUT and FORWARD.
#
# A guest under libvirt's clean-traffic filter sends no IPv6: the filter drops
# every frame that is not IPv4 or ARP. A running guest whose filter waits for
# its next start has only its port isolation, and a bridge carrying IPv6 would
# deliver its packets to the host and forward them past the IPv4 chains. So
# the bridge's IPv6 is dropped whatever the network declares; no guest loses
# anything its filter would have let through. A kernel without IPv6 has no
# ip6tables filter table and no IPv6 to drop, and is left as it is.
#
# The jumps must lead their built-in chains: an accept installed ahead of them
# by UFW (its ufw-before-* chains) or libvirt (LIBVIRT_INP, LIBVIRT_FWO) would
# admit a guest's packet before the policy could drop it. libvirt re-adds its
# rules when it starts and UFW when it reloads, so this runs again after each
# (arkhai-guest-policy.service, /etc/ufw/after.init) and at boot, and is
# idempotent: every run leaves exactly one jump from each built-in chain to its
# policy chain, at position one.
#
# Each family is one restore transaction without a flush of the table:
# declaring each chain flushes and refills it, any jump to it already present is
# deleted, and a new one is inserted first. No packet sees the chains empty or
# the jumps missing, as a delete followed by a separate insert would allow.
set -eu

RULES="${1:-/etc/arkhai/guest-policy.rules}"
BRIDGE=virbr0
# Where the kernel's /proc is; a test points it at a tree of its own.
PROC="${PROC_ROOT:-/proc}"

if [ ! -r "$RULES" ]; then
  echo "arkhai-guest-policy: cannot read the guest policy rules at $RULES" >&2
  exit 1
fi

# Every call waits for the xtables lock (-w): this runs just after libvirtd or
# UFW has started, either of which may still hold it.

# How many of BUILTIN's rules jump to CHAIN from the guests' bridge, as COMMAND
# (iptables or ip6tables) lists them: existing_jumps COMMAND BUILTIN CHAIN.
existing_jumps() {
  "$1" -w -S "$2" | grep -cxF -- "-A $2 -i $BRIDGE -j $3" || true
}

# One delete per jump present, by its rule rather than its position: a rule
# another process inserts meanwhile cannot be deleted in its place, and a jump
# another process deleted meanwhile fails the transaction whole, changing
# nothing.
deletes() {
  count="$1"
  while [ "$count" -gt 0 ]; do
    echo "-D $2 -i $BRIDGE -j $3"
    count=$((count - 1))
  done
}

input_jumps="$(existing_jumps iptables INPUT ARKHAI-GUEST-IN)"
forward_jumps="$(existing_jumps iptables FORWARD ARKHAI-GUEST-FWD)"

{
  echo '*filter'
  cat "$RULES"
  deletes "$input_jumps" INPUT ARKHAI-GUEST-IN
  deletes "$forward_jumps" FORWARD ARKHAI-GUEST-FWD
  echo "-I INPUT 1 -i $BRIDGE -j ARKHAI-GUEST-IN"
  echo "-I FORWARD 1 -i $BRIDGE -j ARKHAI-GUEST-FWD"
  echo 'COMMIT'
} | iptables-restore -w --noflush

echo "arkhai-guest-policy: guest policy installed first in INPUT and FORWARD"

if [ ! -d "$PROC/sys/net/ipv6" ]; then
  echo "arkhai-guest-policy: this kernel has no IPv6; no IPv6 policy installed"
  exit 0
fi

input6_jumps="$(existing_jumps ip6tables INPUT ARKHAI-GUEST-V6)"
forward6_jumps="$(existing_jumps ip6tables FORWARD ARKHAI-GUEST-V6)"

{
  echo '*filter'
  echo ':ARKHAI-GUEST-V6 - [0:0]'
  echo '-A ARKHAI-GUEST-V6 -m comment --comment arkhai-guest-isolation -j DROP'
  deletes "$input6_jumps" INPUT ARKHAI-GUEST-V6
  deletes "$forward6_jumps" FORWARD ARKHAI-GUEST-V6
  echo "-I INPUT 1 -i $BRIDGE -j ARKHAI-GUEST-V6"
  echo "-I FORWARD 1 -i $BRIDGE -j ARKHAI-GUEST-V6"
  echo 'COMMIT'
} | ip6tables-restore -w --noflush

echo "arkhai-guest-policy: IPv6 from the guests' bridge dropped first in INPUT and FORWARD"
