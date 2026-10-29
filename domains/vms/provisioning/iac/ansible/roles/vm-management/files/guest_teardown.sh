# Shell functions every VM teardown path shares: the cleanup script a create
# writes onto the host, vm_remove's teardown of a guest whose create left no
# such script, and vm_undefine. Each path includes this file verbatim, so one
# implementation decides what belongs to a guest.
#
# What a teardown may remove is what it can attribute to its own guest, and
# nothing else. A host runs several guests and keeps rules of its own, so every
# match here is exact: a guest's rules by the comment marker its create gave
# them, or, for a rule written before rules carried a marker, by one of the
# shapes a create writes naming exactly the guest's address, never a prefix of
# it; a relay proxy block and a DHCP reservation by the guest's exact name. The
# masquerade rule for the whole guest subnet is shared by every guest and is
# never one guest's to remove.
#
# Every function returns 0 unless the host refused a removal, so a caller
# running under `set -e` stops at the first removal that did not happen rather
# than reporting a guest torn down while its effects remain. The functions that
# remove report through variables and are called directly, never inside `$(...)`:
# bash clears `set -e` in a command substitution, where a refused removal would
# go unnoticed.

# The chains a create adds rules to, as table:chain.
GUEST_RULE_CHAINS="nat:PREROUTING nat:POSTROUTING filter:FORWARD filter:INPUT"

# The value following OPTION in one `iptables -S` rule, without the quotes
# iptables puts around a comment; empty when the rule has no OPTION.
_rule_option() {
  local option="$2" take="" token
  local -a tokens
  read -ra tokens <<< "$1"
  for token in "${tokens[@]}"; do
    if [ -n "$take" ]; then
      token="${token#\"}"
      printf '%s' "${token%\"}"
      return 0
    fi
    if [ "$token" = "$option" ]; then
      take=1
    fi
  done
  return 0
}

# The address an unmarked rule of CHAIN names, when the rule has one of the
# shapes a create writes for a guest; empty otherwise. INPUT rules name a port
# and no address, so they never have one.
_guest_shaped_address() {
  local chain="$1" rule="$2" address=""
  case "$chain" in
    PREROUTING)
      if [ "$(_rule_option "$rule" -j)" = "DNAT" ]; then
        case "$(_rule_option "$rule" --to-destination)" in
          *:22) address="$(_rule_option "$rule" --to-destination)"; address="${address%:22}" ;;
        esac
      fi
      ;;
    POSTROUTING)
      if [ "$(_rule_option "$rule" -j)" = "MASQUERADE" ] \
        && [ "$(_rule_option "$rule" --dport)" = "22" ]; then
        address="$(_rule_option "$rule" -d)"
      fi
      ;;
    FORWARD)
      if [ "$(_rule_option "$rule" -j)" = "ACCEPT" ]; then
        if [ "$(_rule_option "$rule" --dport)" = "22" ]; then
          address="$(_rule_option "$rule" -d)"
        elif [ "$(_rule_option "$rule" --sport)" = "22" ]; then
          address="$(_rule_option "$rule" -s)"
        fi
      fi
      ;;
  esac
  case "$address" in
    */32) printf '%s' "${address%/32}" ;;
    *:*|*/*) ;;
    *) printf '%s' "$address" ;;
  esac
  return 0
}

# Whether one rule of CHAIN belongs to the guest: it carries MARKER, or it
# carries no marker at all and is a create's rule naming exactly ADDRESS, or,
# on INPUT, opening exactly PORT. A rule carrying any other comment is not the
# guest's. ADDRESS and PORT may be empty, and then match nothing.
_rule_is_guests() {
  local chain="$1" rule="$2" marker="$3" address="$4" port="$5" comment
  comment="$(_rule_option "$rule" --comment)"
  if [ -n "$comment" ]; then
    [ "$comment" = "$marker" ]
    return
  fi
  if [ -n "$address" ] && [ "$(_guest_shaped_address "$chain" "$rule")" = "$address" ]; then
    return 0
  fi
  if [ "$chain" = "INPUT" ] && [ -n "$port" ] \
    && [ "$(_rule_option "$rule" -p)" = "tcp" ] \
    && [ "$(_rule_option "$rule" --dport)" = "$port" ] \
    && [ "$(_rule_option "$rule" -j)" = "ACCEPT" ]; then
    return 0
  fi
  return 1
}

# Delete one rule exactly as `iptables -S` printed it.
_delete_rule() {
  local table="$1" token
  local -a tokens arguments=()
  read -ra tokens <<< "$2"
  for token in "${tokens[@]}"; do
    token="${token#\"}"
    arguments+=("${token%\"}")
  done
  arguments[0]="-D"
  iptables -t "$table" "${arguments[@]}"
}

# The external port of the guest's forwarding rule: the --dport of its DNAT
# rule, found by MARKER or, unmarked, by its exact ADDRESS. Empty when the
# guest has none.
guest_forwarded_port() {
  local marker="$1" address="$2" rules rule
  rules="$(iptables -t nat -S PREROUTING)"
  while IFS= read -r rule; do
    [ "${rule%% *}" = "-A" ] || continue
    if [ "$(_rule_option "$rule" -j)" = "DNAT" ] \
      && _rule_is_guests PREROUTING "$rule" "$marker" "$address" ""; then
      _rule_option "$rule" --dport
      return 0
    fi
  done <<< "$rules"
  return 0
}

# Remove every iptables rule the guest's create added. Prints one line per rule
# removed, `table rule`, and counts them in GUEST_RULES_REMOVED.
remove_guest_rules() {
  local marker="$1" address="$2" port="$3" spec table chain rules rule
  GUEST_RULES_REMOVED=0
  for spec in $GUEST_RULE_CHAINS; do
    table="${spec%%:*}"
    chain="${spec#*:}"
    rules="$(iptables -t "$table" -S "$chain")"
    while IFS= read -r rule; do
      [ "${rule%% *}" = "-A" ] || continue
      if _rule_is_guests "$chain" "$rule" "$marker" "$address" "$port"; then
        _delete_rule "$table" "$rule"
        printf '%s %s\n' "$table" "$rule"
        GUEST_RULES_REMOVED=$((GUEST_RULES_REMOVED + 1))
      fi
    done <<< "$rules"
  done
  return 0
}

# Unmarked rules shaped as a create writes them whose address is none of the
# space-separated KNOWN addresses: rules that may be some guest's, but which
# guest's cannot be told. Prints one line per rule, `table rule`.
unattributable_guest_rules() {
  local known=" $1 " spec table chain rules rule address
  for spec in $GUEST_RULE_CHAINS; do
    table="${spec%%:*}"
    chain="${spec#*:}"
    rules="$(iptables -t "$table" -S "$chain")"
    while IFS= read -r rule; do
      [ "${rule%% *}" = "-A" ] || continue
      [ -z "$(_rule_option "$rule" --comment)" ] || continue
      address="$(_guest_shaped_address "$chain" "$rule")"
      [ -n "$address" ] || continue
      case "$known" in
        *" $address "*) ;;
        *) printf '%s %s\n' "$table" "$rule" ;;
      esac
    done <<< "$rules"
  done
  return 0
}

# The guest's UFW rules while UFW is active, as `ufw status numbered` lists
# them, one per line: each whose comment is MARKER, and each with no comment
# opening exactly PORT/tcp, over IPv4 or IPv6.
guest_ufw_rules() {
  local marker="$1" port="$2" line rest comment
  command -v ufw >/dev/null 2>&1 || return 0
  case "$(ufw status)" in
    *"Status: active"*) ;;
    *) return 0 ;;
  esac
  while IFS= read -r line; do
    [[ "$line" =~ ^\[\ *[0-9]+\]\ +(.*)$ ]] || continue
    rest="${BASH_REMATCH[1]}"
    comment=""
    if [[ "$rest" == *"# "* ]]; then
      comment="${rest#*# }"
      comment="${comment%"${comment##*[![:space:]]}"}"
    fi
    if [ "$comment" = "$marker" ] \
      || { [ -z "$comment" ] && [ -n "$port" ] \
        && [[ "$rest" =~ ^${port}/tcp(\ \(v6\))?\ +ALLOW ]]; }; then
      printf '%s\n' "$line"
    fi
  done <<< "$(ufw status numbered)"
  return 0
}

# Remove the guest's UFW rules (guest_ufw_rules). Prints one line per rule
# removed and counts them in GUEST_UFW_RULES_REMOVED. Rules are removed one at a
# time by number, re-read after each, since numbering shifts on every delete.
remove_guest_ufw_rules() {
  local marker="$1" port="$2" line number
  GUEST_UFW_RULES_REMOVED=0
  while true; do
    line="$(guest_ufw_rules "$marker" "$port" | head -n 1)"
    [ -n "$line" ] || return 0
    if [ "$GUEST_UFW_RULES_REMOVED" -ge 64 ]; then
      echo "UFW still lists a rule of this guest after 64 deletions: $line" >&2
      return 1
    fi
    number="${line#*[}"
    number="${number%%]*}"
    ufw --force delete $((number)) >/dev/null
    printf 'ufw %s\n' "$line"
    GUEST_UFW_RULES_REMOVED=$((GUEST_UFW_RULES_REMOVED + 1))
  done
}

# Remove the guest's block from a VM tunnel client configuration, matched by
# its exact BEGIN and END lines, and apply the change by reloading the client
# through RELOAD_URL. A reload, never a restart: a restart closes the client's
# control connection, and the relay then drops every proxy the client holds,
# ending every other guest's sessions. Sets GUEST_PROXY to `absent`, `removed`,
# or `reload_failed`.
remove_guest_proxy() {
  local config="$1" name="$2" reload_url="$3"
  local begin="# BEGIN ANSIBLE MANAGED BLOCK FOR VM $2"
  local end="# END ANSIBLE MANAGED BLOCK FOR VM $2"
  local rest
  GUEST_PROXY="absent"
  if [ ! -f "$config" ] || ! grep -qxF "$begin" "$config"; then
    return 0
  fi
  # A block with no end would take every block after it, other guests'
  # included, so it is refused rather than removed.
  if ! grep -qxF "$end" "$config"; then
    echo "$config has '$begin' with no matching end line" >&2
    return 1
  fi
  # The configuration holds the client's credential: the copy is written
  # owner-only, and the original is rewritten in place to keep its mode.
  rest="$(mktemp "$config.XXXXXX")"
  awk -v begin="$begin" -v end="$end" '
    $0 == begin { skipping = 1; next }
    skipping && $0 == end { skipping = 0; next }
    !skipping { print }
  ' "$config" > "$rest"
  cat "$rest" > "$config"
  rm -f "$rest"
  if curl -fsS "$reload_url" >/dev/null 2>&1; then
    GUEST_PROXY="removed"
  else
    GUEST_PROXY="reload_failed"
  fi
  return 0
}

# The DHCP reservations in libvirt's `default` network whose name is exactly
# NAME, one `<host .../>` element per line.
guest_dhcp_reservations() {
  local name="$1" xml host
  xml="$(virsh net-dumpxml default)"
  while IFS= read -r host; do
    if [ "$(_host_attribute "$host" name)" = "$name" ]; then
      printf '%s\n' "$host"
    fi
  done <<< "$(grep -o "<host [^>]*>" <<< "$xml" || true)"
  return 0
}

# The addresses reserved in the `default` network for every name but NAME.
other_guests_reserved_addresses() {
  local name="$1" xml host
  xml="$(virsh net-dumpxml default)"
  while IFS= read -r host; do
    [ -n "$host" ] || continue
    if [ "$(_host_attribute "$host" name)" != "$name" ]; then
      printf '%s ' "$(_host_attribute "$host" ip)"
    fi
  done <<< "$(grep -o "<host [^>]*>" <<< "$xml" || true)"
  return 0
}

_host_attribute() {
  local host="$1" attribute="$2" value
  case "$host" in
    *" $attribute='"*) ;;
    *) return 0 ;;
  esac
  value="${host#* $attribute=\'}"
  printf '%s' "${value%%\'*}"
  return 0
}
