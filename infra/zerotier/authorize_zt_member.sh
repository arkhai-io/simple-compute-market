#!/bin/bash
# authorize_member.sh

set -euo pipefail

NETWORK_ID="${1:-}"
MEMBER_ID="${2:-}"

if [[ -z "$NETWORK_ID" ]] || [[ -z "$MEMBER_ID" ]]; then
  echo "Usage: $0 NETWORK_ID MEMBER_ID" >&2
  exit 1
fi

# Determine auth token file location based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS
  AUTH_TOKEN_FILE="/Library/Application Support/ZeroTier/One/authtoken.secret"
else
  # Linux
  AUTH_TOKEN_FILE="/var/lib/zerotier-one/authtoken.secret"
fi

if [[ ! -f "$AUTH_TOKEN_FILE" ]]; then
  echo "Error: ZeroTier auth token not found at $AUTH_TOKEN_FILE" >&2
  echo "Make sure ZeroTier is installed and running." >&2
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "On macOS, start ZeroTier from System Settings or run: sudo launchctl load /Library/LaunchDaemons/com.zerotier.one.plist" >&2
  else
    echo "On Linux, start with: sudo systemctl start zerotier-one" >&2
  fi
  exit 1
fi

AUTH_TOKEN=$(sudo cat "$AUTH_TOKEN_FILE" 2>/dev/null)
if [[ -z "$AUTH_TOKEN" ]]; then
  echo "Error: Failed to read auth token from $AUTH_TOKEN_FILE" >&2
  echo "This script requires sudo access. Please run it interactively." >&2
  exit 1
fi

echo "Authorizing member $MEMBER_ID on network $NETWORK_ID..."

curl -X POST http://localhost:9993/controller/network/${NETWORK_ID}/member/${MEMBER_ID} \
  -H "X-ZT1-Auth: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"authorized": true}'

echo -e "\nDone!"
