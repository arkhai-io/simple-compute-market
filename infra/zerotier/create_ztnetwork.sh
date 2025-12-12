#!/bin/bash
# create_zerotier_network.sh

# Configuration
NETWORK_NAME="My Private Network"
IP_RANGE_START="10.10.10.1"
IP_RANGE_END="10.10.10.254"
NETWORK_CIDR="10.10.10.0/24"

# Get node ID and auth token
NODE_ID=$(sudo zerotier-cli info | awk '{print $3}')
AUTH_TOKEN=$(sudo cat /var/lib/zerotier-one/authtoken.secret)

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
