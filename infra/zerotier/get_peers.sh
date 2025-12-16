#!/usr/bin/env bash

set -euo pipefail
# Usage: ./get_peers.sh <NETWORK_ID>
NWID="${1:-}"

if [[ -z "$NWID" ]]; then
  echo "Usage: $0 <network-id>" >&2
  exit 1
fi

# Check for jq dependency
if ! command -v jq &> /dev/null; then
  echo "Error: jq is required but not installed." >&2
  echo "Install with: brew install jq (macOS) or apt-get install jq (Linux)" >&2
  exit 1
fi

# Check if ZeroTier is installed
if ! command -v zerotier-cli &> /dev/null; then
  echo "Error: ZeroTier CLI not found. Install with: cd infra && make install" >&2
  exit 1
fi

# Check if ZeroTier service is running (skip on macOS as it requires password prompt)
if [[ "$OSTYPE" != "darwin"* ]]; then
  if ! sudo zerotier-cli info &> /dev/null; then
    echo "Error: ZeroTier service is not running." >&2
    echo "Start it with: sudo systemctl start zerotier-one" >&2
    exit 1
  fi
fi

# Determine auth token file location based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS
  AUTH_TOKEN_FILE="/Library/Application Support/ZeroTier/One/authtoken.secret"
else
  # Linux
  AUTH_TOKEN_FILE="/var/lib/zerotier-one/authtoken.secret"
fi

# Check if auth token file exists
if [[ ! -f "$AUTH_TOKEN_FILE" ]]; then
  echo "Error: ZeroTier auth token not found at $AUTH_TOKEN_FILE" >&2
  echo "Make sure ZeroTier is installed and running." >&2
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "On macOS, start ZeroTier from System Preferences or run: sudo launchctl load /Library/LaunchDaemons/com.zerotier.one.plist" >&2
  else
    echo "On Linux, start with: sudo systemctl start zerotier-one" >&2
  fi
  exit 1
fi
# Where your ZeroTier state lives (default for most installs)
TOKEN=$(sudo cat "$AUTH_TOKEN_FILE")

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
  MEMBER_JSON="$(curl -sf -H "X-ZT1-Auth: $TOKEN" \
    "$API/controller/network/$NWID/member/$id")"
  
  if [[ -z "$MEMBER_JSON" ]] || [[ "$MEMBER_JSON" == "null" ]]; then
    echo "Warning: Failed to fetch details for member $id" >&2
    continue
  fi


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

