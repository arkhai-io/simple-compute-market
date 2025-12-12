#!/bin/bash
# authorize_member.sh

NETWORK_ID="$1"
MEMBER_ID="$2"
AUTH_TOKEN=$(sudo cat /var/lib/zerotier-one/authtoken.secret)

if [ -z "$NETWORK_ID" ] || [ -z "$MEMBER_ID" ]; then
    echo "Usage: $0 NETWORK_ID MEMBER_ID"
    exit 1
fi

echo "Authorizing member $MEMBER_ID on network $NETWORK_ID..."

curl -X POST http://localhost:9993/controller/network/${NETWORK_ID}/member/${MEMBER_ID} \
  -H "X-ZT1-Auth: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"authorized": true}'

echo -e "\nDone!"
