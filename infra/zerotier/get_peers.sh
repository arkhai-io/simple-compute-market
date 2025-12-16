#!/usr/bin/env bash

# Usage: ./zt-list-ips.sh <NETWORK_ID>
NWID="${1:-}"

if [[ -z "$NWID" ]]; then
  echo "Usage: $0 <network-id>" >&2
  exit 1
fi

# Where your ZeroTier state lives (default for most installs)
TOKEN=$(sudo cat /var/lib/zerotier-one/authtoken.secret)

API="http://127.0.0.1:9993"

echo "Using ZeroTier controller at: $API"
echo "Network ID: $NWID"
echo

echo "Fetching member list..."
MEMBERS_JSON="$(curl -sf -H "X-ZT1-Auth: $TOKEN" \
  "$API/controller/network/$NWID/member")"

if [[ -z "$MEMBERS_JSON" ]] || [[ "$MEMBERS_JSON" == "null" ]]; then
  echo "Error: Failed to fetch members or network not found" >&2
  exit 1
fi

# Get just the member IDs
MEMBER_IDS=($(printf '%s' "$MEMBERS_JSON" | jq -r 'keys[]'))

if [[ ${#MEMBER_IDS[@]} -eq 0 ]]; then
  echo "No members found on this network."
  exit 0
fi

echo "Found ${#MEMBER_IDS[@]} members:"
printf '  %s\n' "${MEMBER_IDS[@]}"
echo
echo "Member IP assignments:"
echo "======================"

for id in "${MEMBER_IDS[@]}"; do
  MEMBER_JSON="$(curl -s -H "X-ZT1-Auth: $TOKEN" \
    "$API/controller/network/$NWID/member/$id")"

  # Extract all IPs for this member (if any)
  IPS=($(printf '%s' "$MEMBER_JSON" | jq -r '.ipAssignments[]?'))

  if [[ ${#IPS[@]} -eq 0 ]]; then
    echo "Node $id: (no IP assignments)"
    continue
  fi

  # Echo one line per IP for clarity
  for ip in "${IPS[@]}"; do
    echo "Node $id: $ip"
  done
done

