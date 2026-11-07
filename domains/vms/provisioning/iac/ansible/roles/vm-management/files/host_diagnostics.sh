#!/usr/bin/env bash
# Print one JSON document describing this KVM host: its boot ID, uptime, kernel,
# the number of running guests, and for libvirtd.service, frpc-buyers.service and
# the unit named by the optional first argument, the state `systemctl show`
# reports. The host-diagnostics task runs it on the host and adds the action,
# host and status.
#
# It changes no service or configuration on the host itself (Ansible's `script`
# module copies it to a temporary file to run it), but counting guests through
# `virsh` starts libvirtd if the
# socket-activated daemon had exited while idle. So the units are read first,
# and the read reports libvirtd as it was found; a later read may then see the
# generation this one started.
#
# A failed read fails the script, naming what failed, rather than printing a
# fact with the value missing. A value systemd reports where a number belongs is
# printed as a string when it is not one, so the fact's typed reader refuses the
# field by name rather than this script inventing a number. PROC_ROOT stands in
# for /proc under test.
set -euo pipefail

PROC="${PROC_ROOT:-/proc}"
MANAGEMENT_UNIT="${1:-}"

json_string() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\t'/\\t}
  value=${value//$'\r'/\\r}
  value=${value//$'\n'/\\n}
  printf '"%s"' "$value"
}

json_integer() {
  if [[ $1 =~ ^[0-9]+$ ]]; then
    printf '%s' "$1"
  else
    json_string "$1"
  fi
}

json_number() {
  if [[ $1 =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    printf '%s' "$1"
  else
    json_string "$1"
  fi
}

# Runs in a command substitution, where `set -e` does not apply, so a failed
# `systemctl show` is returned explicitly.
unit_state() {
  local unit=$1 properties line key value
  local active_state="" invocation_id="" main_pid="" restarts="" entered="" result=""
  if ! properties=$(systemctl show \
    --property=ActiveState,InvocationID,MainPID,NRestarts,ActiveEnterTimestamp,Result \
    -- "$unit"); then
    echo "host diagnostics: systemctl show failed for $unit" >&2
    return 1
  fi
  while IFS= read -r line; do
    key=${line%%=*}
    value=${line#*=}
    case "$key" in
      ActiveState) active_state=$value ;;
      InvocationID) invocation_id=$value ;;
      MainPID) main_pid=$value ;;
      NRestarts) restarts=$value ;;
      ActiveEnterTimestamp) entered=$value ;;
      Result) result=$value ;;
    esac
  done <<< "$properties"
  printf '{"active_state": %s, "invocation_id": %s, "main_pid": %s, "restart_count": %s, "active_enter_timestamp": %s, "result": %s}' \
    "$(json_string "$active_state")" "$(json_string "$invocation_id")" \
    "$(json_integer "$main_pid")" "$(json_integer "$restarts")" \
    "$(json_string "$entered")" "$(json_string "$result")"
}

units=(libvirtd.service frpc-buyers.service)
case "$MANAGEMENT_UNIT" in
  ""|libvirtd.service|frpc-buyers.service) ;;
  *) units+=("$MANAGEMENT_UNIT") ;;
esac

unit_entries=""
for unit in "${units[@]}"; do
  # A plain assignment, so a failed read stops the script under `set -e`.
  state=$(unit_state "$unit")
  [ -z "$unit_entries" ] || unit_entries="$unit_entries, "
  unit_entries="$unit_entries$(json_string "$unit"): $state"
done

boot_id=$(cat "$PROC/sys/kernel/random/boot_id")
read -r uptime _ < "$PROC/uptime"
kernel=$(uname -r)
# grep's status only says it counted none; a failed virsh call fails the script.
guests=$(virsh list --state-running --name)
running_guests=$(printf '%s\n' "$guests" | grep -c . || true)

if [ -n "$MANAGEMENT_UNIT" ]; then
  management=$(json_string "$MANAGEMENT_UNIT")
else
  management=null
fi

printf '{"timestamp": %s, "boot_id": %s, "uptime_seconds": %s, "kernel": %s, "running_guests": %s, "management_unit": %s, "units": {%s}}\n' \
  "$(json_string "$(date -u +%Y-%m-%dT%H:%M:%SZ)")" "$(json_string "$boot_id")" \
  "$(json_number "$uptime")" "$(json_string "$kernel")" \
  "$(json_integer "$running_guests")" "$management" "$unit_entries"
