#!/bin/bash
# authorize_member.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found at $ENV_FILE"
  echo "Copy infra/zerotier/.env.sample to $ENV_FILE and set values."
  exit 1
fi

# Load network configuration from .env
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for var in CONTROLLER_URL ZEROTIER_NETWORK; do
  if [[ -z "${!var:-}" ]]; then
    echo "Missing required env var: $var in $ENV_FILE" >&2
    exit 1
  fi
done

NETWORK_ID="${1:-$ZEROTIER_NETWORK}"
MEMBER_ID="${2:-}"

if [[ -z "$NETWORK_ID" ]] || [[ -z "$MEMBER_ID" ]]; then
  echo "Usage: $0 [NETWORK_ID] MEMBER_ID" >&2
  echo "  NETWORK_ID defaults to ZEROTIER_NETWORK from .env ($ZEROTIER_NETWORK)" >&2
  exit 1
fi
# Check if ZeroTier controller API is accessible
echo "Checking ZeroTier controller API..."
if ! curl -s --max-time 2 $CONTROLLER_URL/status &> /dev/null; then
  echo "Error: ZeroTier controller API is not accessible at $CONTROLLER_URL" >&2
  echo "" >&2
  echo "The ZeroTier controller service needs to be running to authorize members." >&2
  exit 1
fi
echo "ZeroTier controller API is accessible"

# Resolve auth token: prefer CONTROLLER_AUTH_TOKEN from env, fall back to auth token file
if [[ -n "${CONTROLLER_AUTH_TOKEN:-}" ]]; then
  echo "Using CONTROLLER_AUTH_TOKEN from environment" >&2
  AUTH_TOKEN="$CONTROLLER_AUTH_TOKEN"
else
  echo "CONTROLLER_AUTH_TOKEN not set, reading from auth token file..." >&2

  # Determine auth token file location based on OS
  if [[ "$OSTYPE" == "darwin"* ]]; then
    AUTH_TOKEN_FILE="/Library/Application Support/ZeroTier/One/authtoken.secret"
  else
    AUTH_TOKEN_FILE="/var/lib/zerotier-one/authtoken.secret"
  fi

  # Check if auth token file exists
  if [[ ! -f "$AUTH_TOKEN_FILE" ]]; then
    echo "Error: ZeroTier auth token not found at $AUTH_TOKEN_FILE" >&2
    echo "Make sure ZeroTier is installed and running, or set CONTROLLER_AUTH_TOKEN in your .env file." >&2
    if [[ "$OSTYPE" == "darwin"* ]]; then
      echo "On macOS, start ZeroTier from System Preferences or run: sudo launchctl load /Library/LaunchDaemons/com.zerotier.one.plist" >&2
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

  CONTROLLER_AUTH_TOKEN="$AUTH_TOKEN"
fi

echo "Authorizing member $MEMBER_ID on network $NETWORK_ID..."

set +e
RESPONSE=$(curl -s --max-time 10 -X POST $CONTROLLER_URL/controller/network/${NETWORK_ID}/member/${MEMBER_ID} \
  -H "X-ZT1-Auth: $CONTROLLER_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"authorized": true}' \
  -w "\n%{http_code}" 2>&1)
CURL_EXIT=$?
set -e

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ $CURL_EXIT -ne 0 ]]; then
  echo "Error: Failed to authorize member (curl exit code: $CURL_EXIT)" >&2
  if [[ -n "$BODY" ]]; then
    echo "Response: $BODY" >&2
  fi
  echo "Check that ZeroTier controller is reachable at $CONTROLLER_URL" >&2
  exit 1
fi

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "Error: Failed to authorize member (HTTP $HTTP_CODE)" >&2
  if [[ -n "$BODY" ]]; then
    echo "Response: $BODY" >&2
  fi
  exit 1
fi

echo "Member $MEMBER_ID authorized successfully!"