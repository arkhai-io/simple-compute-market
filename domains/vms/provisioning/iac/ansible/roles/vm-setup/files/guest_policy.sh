#!/bin/sh
# Installs the VM guest policy: the chains ARKHAI-GUEST-IN and ARKHAI-GUEST-FWD
# from the rules file host preparation renders, each jumped to from the first
# position of INPUT and FORWARD for packets arriving from the guests' bridge.
#
# The jumps must lead their built-in chains: an accept installed ahead of them
# by UFW (its ufw-before-* chains) or libvirt (LIBVIRT_INP, LIBVIRT_FWO) would
# admit a guest's packet before the policy could drop it. libvirt re-adds its
# rules when it starts and UFW when it reloads, so this runs again after each
# (arkhai-guest-policy.service, /etc/ufw/after.init) and at boot, and is
# idempotent: every run leaves exactly one jump to each chain, at position one.
#
# Everything is one iptables-restore transaction without a flush of the table:
# declaring each chain flushes and refills it, any jump to it already present is
# deleted, and a new one is inserted first. No packet sees the chains empty or
# the jumps missing, as a delete followed by a separate insert would allow.
set -eu

RULES="${1:-/etc/arkhai/guest-policy.rules}"
BRIDGE=virbr0

if [ ! -r "$RULES" ]; then
  echo "arkhai-guest-policy: cannot read the guest policy rules at $RULES" >&2
  exit 1
fi

# Every call waits for the xtables lock (-w): this runs just after libvirtd or
# UFW has started, either of which may still hold it.

# How many of BUILTIN's rules jump to CHAIN from the guests' bridge.
existing_jumps() {
  iptables -w -S "$1" | grep -cxF -- "-A $1 -i $BRIDGE -j $2" || true
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

input_jumps="$(existing_jumps INPUT ARKHAI-GUEST-IN)"
forward_jumps="$(existing_jumps FORWARD ARKHAI-GUEST-FWD)"

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
