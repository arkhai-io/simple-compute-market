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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found at $ENV_FILE"
  echo "Copy infra/zerotier/.env.sample to $ENV_FILE and set values."
  exit 1
fi

# Load configuration from .env
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Require CONTROLLER_AUTH_TOKEN from environment
if [[ -z "${CONTROLLER_AUTH_TOKEN:-}" ]]; then
  echo "Error: CONTROLLER_AUTH_TOKEN is not set." >&2
  echo "Please set CONTROLLER_AUTH_TOKEN in your .env file." >&2
  exit 1
fi
TOKEN="$CONTROLLER_AUTH_TOKEN"

API="$CONTROLLER_URL"

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

