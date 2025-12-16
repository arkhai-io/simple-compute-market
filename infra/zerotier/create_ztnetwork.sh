#!/bin/bash
# create_zerotier_network.sh

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

for var in NETWORK_NAME IP_RANGE_START IP_RANGE_END NETWORK_CIDR; do
  if [[ -z "${!var:-}" ]]; then
    echo "Missing required env var: $var in $ENV_FILE" >&2
    exit 1
  fi
done

# Get node ID and auth token
# Check if ZeroTier is installed
if ! command -v zerotier-cli &> /dev/null; then
  echo "Error: ZeroTier CLI not found. Install with: make install" >&2
  exit 1
fi

# Check if ZeroTier controller API is accessible
echo "Checking ZeroTier controller API..."
if ! curl -s --max-time 2 http://localhost:9993/status &> /dev/null; then
  echo "Error: ZeroTier controller API is not accessible at http://localhost:9993" >&2
  echo "" >&2
  echo "The ZeroTier controller service needs to be running to create networks." >&2
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
echo "ZeroTier controller API is accessible"

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

# Get node ID from identity file (requires sudo but avoids zerotier-cli password prompt)
# The node ID is the first 10 characters of the identity.public file
IDENTITY_FILE="${AUTH_TOKEN_FILE%/*}/identity.public"

if [[ ! -f "$IDENTITY_FILE" ]]; then
  echo "Error: ZeroTier identity file not found at $IDENTITY_FILE" >&2
  echo "Make sure ZeroTier is installed and running." >&2
  exit 1
fi

# Read node ID from identity file (first 10 chars)
NODE_ID=$(sudo cat "$IDENTITY_FILE" 2>/dev/null | head -1 | cut -c 1-10)

# If that failed, try zerotier-cli info as fallback
if [[ -z "$NODE_ID" ]] || [[ ${#NODE_ID} -ne 10 ]]; then
  echo "Trying alternative method to get node ID..." >&2
  NODE_ID=$(sudo zerotier-cli info 2>/dev/null | awk '{print $3}')
fi

if [[ -z "$NODE_ID" ]] || [[ ${#NODE_ID} -ne 10 ]]; then
  echo "Error: Failed to get ZeroTier node ID." >&2
  echo "This script requires sudo access. Please run it interactively." >&2
  echo "You can get your node ID manually with: sudo zerotier-cli info" >&2
  exit 1
fi

AUTH_TOKEN=$(sudo cat "$AUTH_TOKEN_FILE" 2>/dev/null)
if [[ -z "$AUTH_TOKEN" ]]; then
  echo "Error: Failed to read auth token from $AUTH_TOKEN_FILE" >&2
  echo "This script requires sudo access. Please run it interactively." >&2
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
curl -X POST http://localhost:9993/controller/network/${NETWORK_ID} \
  -H "X-ZT1-Auth: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$NETWORK_NAME\",
    \"private\": true,
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
  }"

# Join the network
echo -e "\n\n2. Joining network..."
sudo zerotier-cli join ${NETWORK_ID}

# Authorize ourselves
echo -e "\n3. Authorizing controller node..."
sleep 2
curl -X POST http://localhost:9993/controller/network/${NETWORK_ID}/member/${NODE_ID} \
  -H "X-ZT1-Auth: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"authorized": true}'

# Verify
echo -e "\n\n4. Verifying network..."
sleep 3
sudo zerotier-cli listnetworks

echo -e "\n\nNetwork created successfully!"
echo "Network ID: $NETWORK_ID"
echo "Share this ID with others to join your network"
echo ""
echo "To authorize new members:"
echo "curl -X POST http://localhost:9993/controller/network/${NETWORK_ID}/member/MEMBER_ID \\"
echo "  -H \"X-ZT1-Auth: $AUTH_TOKEN\" \\"
echo "  -d '{\"authorized\": true}'"
