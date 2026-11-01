# Remove the guest's block from a buyer tunnel client configuration, matched by
# its exact BEGIN and END lines, and apply the change by reloading the client
# through RELOAD_URL. A reload, never a restart: a restart closes the client's
# control connection, and the relay then drops every proxy the client holds,
# ending every other guest's sessions.
#
# The proxy, and the relay port it holds, is gone only once the running client
# has reloaded without the block; the file alone proves nothing. So the block
# is not removed until a pending record beside the configuration names the
# guest, and the record goes only after a reload succeeds. A call that finds
# the block gone but the record still there reloads before it reports
# anything, so a retry after a failed reload never mistakes the missing block
# for proof.
#
# Sets GUEST_PROXY to `absent` (neither block nor pending record) or `removed`
# (the client reloaded without the block), and returns 0. When the reload
# fails it sets `reload_failed` and returns 1, keeping the record, so the
# teardown fails and a retry reloads again. Every step is checked here rather
# than left to the caller's `set -e`, which bash ignores in a function called
# as a condition.
remove_guest_proxy() {
  local config="$1" name="$2" reload_url="$3"
  local begin="# BEGIN ANSIBLE MANAGED RELAY PROXY $2"
  local end="# END ANSIBLE MANAGED RELAY PROXY $2"
  local pending="$config.reload-pending.$2"
  local rest
  GUEST_PROXY="absent"
  if [ -f "$config" ] && grep -qxF "$begin" "$config"; then
    # A block with no end would take every block after it, other guests'
    # included, so it is refused rather than removed.
    if ! grep -qxF "$end" "$config"; then
      echo "$config has '$begin' with no matching end line" >&2
      return 1
    fi
    : > "$pending" || return 1
    # The configuration holds the client's credential: the copy is written
    # owner-only, and the original is rewritten in place to keep its mode.
    rest="$(mktemp "$config.XXXXXX")" || return 1
    if ! awk -v begin="$begin" -v end="$end" '
      $0 == begin { skipping = 1; next }
      skipping && $0 == end { skipping = 0; next }
      !skipping { print }
    ' "$config" > "$rest" || ! cat "$rest" > "$config"; then
      rm -f "$rest"
      return 1
    fi
    rm -f "$rest"
  elif [ ! -e "$pending" ]; then
    return 0
  fi
  local password
  password="$(awk -F ' = ' '$1 == "webServer.password" {gsub(/"/, "", $2); print $2; exit}' "$config")" || return 1
  if ! [[ "$password" =~ ^[a-f0-9]{64}$ ]]; then
    echo "the buyer tunnel client has no valid admin password" >&2
    return 1
  fi
  # Supply the credential through stdin, never a process argument.
  if ! printf 'user = "admin:%s"\n' "$password" | curl --config - --connect-timeout 5 --max-time 30 --noproxy '*' -fsS "$reload_url" >/dev/null 2>&1; then
    GUEST_PROXY="reload_failed"
    echo "the buyer tunnel client did not reload, so it may still hold the proxy for $name" >&2
    return 1
  fi
  rm -f "$pending" || return 1
  GUEST_PROXY="removed"
  return 0
}
