#!/bin/bash
# create_zerotier_network.sh

set -euo pipefail

JOIN=false
for arg in "$@"; do
  case "$arg" in
    --join) JOIN=true ;;
  esac
done

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

for var in NETWORK_NAME IP_RANGE_START IP_RANGE_END NETWORK_CIDR; do
  if [[ -z "${!var:-}" ]]; then
    echo "Missing required env var: $var in $ENV_FILE" >&2
    exit 1
  fi
done

# Get node ID and auth token
if [[ "$JOIN" == true ]]; then
  # Check if ZeroTier is installed
  if ! command -v zerotier-cli &> /dev/null; then
    echo "Error: ZeroTier CLI not found. Install with: make install" >&2
    exit 1
  fi

  # Check if ZeroTier service is running
  echo "Checking ZeroTier service status..."
  if ! zerotier-cli info &> /dev/null; then
    echo "Error: ZeroTier service is not running." >&2
    echo "" >&2
    echo "The ZeroTier service needs to be running to create networks." >&2
    echo "" >&2
    if [[ "$OSTYPE" == "darwin"* ]]; then
      echo "On macOS:" >&2
      echo "  1. Open ZeroTier from Applications or System Preferences" >&2
      echo "  2. Make sure ZeroTier is running (check the menu bar icon)" >&2
      echo "  3. Or start it with: sudo launchctl load /Library/LaunchDaemons/com.zerotier.one.plist" >&2
      echo "" >&2
      echo "Note: On macOS, ZeroTier runs as a regular app, not a system service." >&2
      echo "The controller API may only be available when ZeroTier is actively running." >&2
    else
      echo "On Linux:" >&2
      echo "  Start it with: sudo systemctl start zerotier-one" >&2
      echo "  Enable it with: sudo systemctl enable zerotier-one" >&2
    fi
    exit 1
  fi
  echo "ZeroTier service is running"
fi

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

echo "Retrieving node ID from controller status..." >&2
set +e
STATUS_RESPONSE=$(curl -s --max-time 5 -H "X-ZT1-Auth: $CONTROLLER_AUTH_TOKEN" $CONTROLLER_URL/status 2>&1)
STATUS_EXIT=$?
set -e

if [[ $STATUS_EXIT -ne 0 ]]; then
  echo "Error: Failed to fetch controller status (curl exit code: $STATUS_EXIT)" >&2
  echo "Response: $STATUS_RESPONSE" >&2
  echo "Check that the controller is reachable at $CONTROLLER_URL" >&2
  exit 1
fi

NODE_ID=$(echo "$STATUS_RESPONSE" | grep -o '"address":"[^"]*"' | head -1 | cut -d'"' -f4)

if [[ -z "$NODE_ID" ]] || [[ ${#NODE_ID} -ne 10 ]]; then
  echo "Error: Failed to parse node address from /status response." >&2
  echo "Expected a 10-character address, got: '${NODE_ID:-<empty>}'" >&2
  echo "Full /status response: $STATUS_RESPONSE" >&2
  exit 1
fi

# Generate network ID (node ID + random suffix)
SUFFIX=$(openssl rand -hex 3)
NETWORK_ID="${NODE_ID}${SUFFIX}"

echo "Creating ZeroTier Network..."
echo "Node ID: $NODE_ID"
echo "Network ID: $NETWORK_ID"
echo "IP Range: $IP_RANGE_START - $IP_RANGE_END"

# Create the network
echo -e "\n1. Creating network..."
echo "   Network ID: $NETWORK_ID"
echo "   This may take a few seconds..."

# Use timeout and better error handling
set +e
RESPONSE=$(curl -s --max-time 10 -X POST $CONTROLLER_URL/controller/network/${NETWORK_ID} \
  -H "X-ZT1-Auth: $CONTROLLER_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$NETWORK_NAME\",
    \"private\": true,
    \"mtu\": 1300,
    \"v4AssignMode\": {
      \"zt\": true
    },
    \"ipAssignmentPools\": [{
      \"ipRangeStart\": \"$IP_RANGE_START\",
      \"ipRangeEnd\": \"$IP_RANGE_END\"
    }],
    \"routes\": [{
      \"target\": \"$NETWORK_CIDR\"
    }]
  }" \
  -w "\n%{http_code}" 2>&1)
CURL_EXIT=$?
set -e

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ $CURL_EXIT -ne 0 ]]; then
  echo "Error: Failed to create network (curl exit code: $CURL_EXIT)" >&2
  if [[ -n "$BODY" ]]; then
    echo "Response: $BODY" >&2
  fi
  echo "This might mean:" >&2
  echo "  - ZeroTier controller API is not accessible at $CONTROLLER_URL" >&2
  echo "  - Network already exists (try a different network ID)" >&2
  echo "  - ZeroTier service needs to be restarted" >&2
  exit 1
fi

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "Error: Failed to create network (HTTP $HTTP_CODE)" >&2
  if [[ -n "$BODY" ]]; then
    echo "Response: $BODY" >&2
  fi
  if [[ "$HTTP_CODE" == "409" ]]; then
    echo "Network already exists. Try deleting it first or use a different network ID." >&2
  fi
  exit 1
fi

echo "   Network created successfully!"

# Verify
echo -e "\n\n2. Verifying network..."
sleep 3
set +e
NETWORK_LIST=$(curl -s --max-time 5 -H "X-ZT1-Auth: $CONTROLLER_AUTH_TOKEN" $CONTROLLER_URL/controller/network 2>&1)
VERIFY_EXIT=$?
set -e

if [[ $VERIFY_EXIT -ne 0 ]]; then
  echo "Warning: Failed to fetch network list for verification (curl exit code: $VERIFY_EXIT)" >&2
  echo "Response: $NETWORK_LIST" >&2
elif echo "$NETWORK_LIST" | grep -q "$NETWORK_ID"; then
  echo "   Verified: Network $NETWORK_ID found in controller network list."
else
  echo "Warning: Network $NETWORK_ID not found in controller network list." >&2
  echo "Response: $NETWORK_LIST" >&2
fi

echo -e "\n\nNetwork created successfully!"
echo "Network ID: $NETWORK_ID"
echo "Share this ID with others to join your network"
echo ""

if [[ "$JOIN" == true ]]; then
  # Join the network
  echo -e "\n3. Joining network..."
  sudo zerotier-cli join ${NETWORK_ID}

  # Authorize ourselves
  echo -e "\n4. Authorizing local node..."
  LOCAL_NODE_ID=$(zerotier-cli info | awk '{print $3}')
  if [[ -z "$LOCAL_NODE_ID" ]] || [[ ${#LOCAL_NODE_ID} -ne 10 ]]; then
    echo "Error: Failed to get local node ID from zerotier-cli info" >&2
    echo "Got: '${LOCAL_NODE_ID:-<empty>}'" >&2
    exit 1
  fi
  echo "   Local Node ID: $LOCAL_NODE_ID"
  sleep 2
  # Use set +e to allow curl to fail without exiting the script
  set +e
  RESPONSE=$(curl -s -X POST $CONTROLLER_URL/controller/network/${NETWORK_ID}/member/${LOCAL_NODE_ID} \
    -H "X-ZT1-Auth: $CONTROLLER_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"authorized": true}' \
    -w "\n%{http_code}" 2>&1)
  CURL_EXIT=$?
  set -e

  HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
  BODY=$(echo "$RESPONSE" | sed '$d')

  if [[ $CURL_EXIT -ne 0 ]] || [[ "$HTTP_CODE" != "200" ]]; then
    echo "Warning: Failed to authorize local node" >&2
    if [[ $CURL_EXIT -ne 0 ]]; then
      echo "Curl exit code: $CURL_EXIT" >&2
    fi
    if [[ -n "$HTTP_CODE" ]] && [[ "$HTTP_CODE" != "200" ]]; then
      echo "HTTP status: $HTTP_CODE" >&2
    fi
    if [[ -n "$BODY" ]]; then
      echo "Response: $BODY" >&2
    fi
    echo "You may need to authorize manually or the node may already be authorized." >&2
    echo "Try running: make add-node NODE_ID=$LOCAL_NODE_ID" >&2
    # Don't exit here as network creation succeeded
  else
    echo "Local node authorized successfully!"
  fi
fi

# Try to update .env file with the network ID
ENV_FILE="${SCRIPT_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  if grep -q "^ZEROTIER_NETWORK=" "$ENV_FILE"; then
    # Update existing ZEROTIER_NETWORK line
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' "s/^ZEROTIER_NETWORK=.*/ZEROTIER_NETWORK=$NETWORK_ID/" "$ENV_FILE"
    else
      sed -i "s/^ZEROTIER_NETWORK=.*/ZEROTIER_NETWORK=$NETWORK_ID/" "$ENV_FILE"
    fi
    echo "✓ Updated $ENV_FILE with network ID: $NETWORK_ID"
  else
    # Append if it doesn't exist
    echo "ZEROTIER_NETWORK=$NETWORK_ID" >> "$ENV_FILE"
    echo "✓ Added network ID to $ENV_FILE: $NETWORK_ID"
  fi
else
  echo "Note: .env file not found at $ENV_FILE"
  echo "Create it and set: ZEROTIER_NETWORK=$NETWORK_ID"
fi

echo ""
echo "To authorize new members:"
echo "  make add-node NODE_ID=<member-id>"
echo ""
echo "Or manually:"
echo "  curl -X POST $CONTROLLER_URL/controller/network/${NETWORK_ID}/member/MEMBER_ID \\"
echo "    -H \"X-ZT1-Auth: $CONTROLLER_AUTH_TOKEN\" \\"
echo "    -d '{\"authorized\": true}'"