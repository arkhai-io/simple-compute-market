#!/usr/bin/env bash
# Start or stop the background port-forwards of one release's Services. Run by
# `make -C helm forward` and `make -C helm unforward`, which pass the inputs
# below.
#
#   port-forward.sh start <service>:<port>...  forward each Service's port to the
#                                             same local port, in NAMESPACE
#   port-forward.sh stop                      stop the forwards PID_FILE records
#
# The local ports are the same for every namespace, so a host forwards one
# namespace at a time. A port another checkout's forward already holds fails to
# bind, and `start` then names the port and kubectl's error, stops every forward
# it started, and fails, rather than leave one Service silently unforwarded.
# `stop` waits until its forwards have exited, so a `start` straight after it
# does not fail on ports they still hold, and fails, keeping their processes in
# PID_FILE, when one outlives the wait.
#
# Inputs:
#   NAMESPACE     the namespace whose Services `start` forwards
#   PID_FILE      where the forwards' processes are recorded
#   WAIT_SECONDS  how long `start` waits for its forwards to listen, and `stop`
#                 for them to exit (default 15)
set -euo pipefail

PID_FILE="${PID_FILE:?PID_FILE is not set}"
WAIT_SECONDS="${WAIT_SECONDS:-15}"

alive() {
    kill -0 "$1" 2>/dev/null
}

stop() {
    [ -f "$PID_FILE" ] || return 0
    local pids pid survivors="" deadline=$((SECONDS + WAIT_SECONDS))
    pids="$(cat "$PID_FILE")"
    for pid in $pids; do
        kill "$pid" 2>/dev/null || true
    done
    for pid in $pids; do
        while alive "$pid" && [ "$SECONDS" -lt "$deadline" ]; do
            sleep 0.2
        done
        if alive "$pid"; then
            survivors="$survivors $pid"
        fi
    done
    if [ -n "$survivors" ]; then
        # Kept in the file, so that stopping again still finds them.
        printf '%s\n' $survivors >"$PID_FILE"
        echo "ERROR: port-forward process(es)$survivors still running ${WAIT_SECONDS}s after being stopped; if they are not this checkout's port-forwards (the file outlived a restart), remove $PID_FILE" >&2
        return 1
    fi
    rm -f "$PID_FILE"
}

start() {
    : "${NAMESPACE:?NAMESPACE is not set}"
    local spec service port
    # Global, for the exit trap; each forward goes on writing to its unlinked log.
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    local -a ports=() pids=()
    for spec in "$@"; do
        service="${spec%:*}"
        port="${spec##*:}"
        kubectl port-forward --namespace "$NAMESPACE" "svc/$service" "$port:$port" \
            >"$work/$port.log" 2>&1 &
        pids+=("$!")
        ports+=("$port")
        echo "$!" >>"$PID_FILE"
    done
    # kubectl prints "Forwarding from" once it listens, and exits when it cannot.
    # Every forward is waited for, so a failure names every port that failed.
    local deadline=$((SECONDS + WAIT_SECONDS)) index failed="" waiting
    local -a settled=()
    while :; do
        waiting=""
        for index in "${!ports[@]}"; do
            [ -n "${settled[$index]:-}" ] && continue
            port="${ports[$index]}"
            if grep -q "Forwarding from" "$work/$port.log"; then
                settled[$index]=listening
            elif ! alive "${pids[$index]}"; then
                settled[$index]=failed
                failed="$failed"$'\n'"  port $port: $(tr '\n' ' ' <"$work/$port.log")"
            else
                waiting="$waiting $port"
            fi
        done
        [ -z "$waiting" ] && break
        if [ "$SECONDS" -ge "$deadline" ]; then
            failed="$failed"$'\n'"  port(s)$waiting did not start listening within ${WAIT_SECONDS}s"
            break
        fi
        sleep 0.2
    done
    if [ -n "$failed" ]; then
        echo "ERROR: could not forward namespace $NAMESPACE; is another namespace forwarded on this host?$failed" >&2
        stop || true
        exit 1
    fi
}

case "${1:-}" in
    start) shift; start "$@" ;;
    stop) stop ;;
    *) echo "usage: $0 start <service>:<port>... | stop" >&2; exit 2 ;;
esac
