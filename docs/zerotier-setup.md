# ZeroTier setup

## Why ZeroTier?

A storefront needs a routable URL — the one it registers on-chain so buyers and indexers can reach `/negotiate`, `/settle`, etc. The standard ways to get one are a public IP plus DNS and port-forwarding, a cloud-hosted reverse proxy (Cloudflare Tunnel, ngrok, FRP — see [`seller-frp-setup.md`](./seller-frp-setup.md)), or a private overlay where every participant has a virtual IP and can route to every other without anyone being publicly reachable.

ZeroTier is the third option, wired in as a built-in. If `[seller] zerotier_network` is set in `storefront.toml`, the storefront joins the configured network at startup, reads its assigned ZT IP via `zerotier-cli`, and substitutes it into `base_url` (which accepts a `{ZEROTIER_IP}` template). The advertised URL points at that IP; buyers join the same overlay with `market network join <network-id>` to reach it. To the rest of the protocol it's an ordinary HTTP URL.

Use it when:

- The storefront runs on a residential / CGNAT / home-network host where port forwarding is awkward.
- You want the service visible only to authorized members — the ZT controller authorizes each node before it can join, so there's no public listener.
- You're running a private or invite-only marketplace and want the whole participant set on a private overlay.

The trade-off is that every participant on the overlay has to install ZeroTier and join the network. For an open public marketplace, public DNS or a reverse proxy is usually simpler.

This runbook is for the **controller operator** — the party creating the network and authorizing members (typically the marketplace operator, or a seller hosting their own private registry alongside their storefront). Participants joining an existing network don't need this doc.

## Prerequisites

1. ZeroTier must be installed and running
2. You need to be on the machine that will act as the controller
3. The controller feature is built into ZeroTier by default

## Step 1: Get Your Node ID

First, find your node ID which will be the prefix for your network:

```bash
# Get your node ID
NODE_ID=$(sudo zerotier-cli info | awk '{print $3}')
echo "Your node ID: $NODE_ID"

# Your networks must start with this ID
# Example: if NODE_ID is "1234567890", networks can be:
# - 1234567890000001
# - 1234567890abcdef
# - etc.
```

## Step 2: Create the Network

Use the create_ztnetwork.sh script to create a ZeroTier network.

> **MTU note:** `create_ztnetwork.sh` sets `mtu: 1300` on new networks. This is required to avoid
> IP fragmentation when routing A2A traffic (HTTP POST bodies ~2KB) over ZeroTier's UDP overlay on
> internet paths with physical MTU 1500. The default ZeroTier MTU of 2800 causes large payloads to
> be silently dropped.
>
> For changing this value on the network, patch the MTU manually:
> ```bash
> AUTH=$(sudo cat /var/lib/zerotier-one/authtoken.secret)
> curl -X POST "$CONTROLLER_URL/controller/network/<NETWORK_ID>" \
>   -H "X-ZT1-Auth: $AUTH" \
>   -H "Content-Type: application/json" \
>   -d '{"mtu": 1300}'
> ```
> Nodes pick up the new MTU within ~60 seconds. Verify with `ip link show | grep zt`.

Modify NETWORK_NAME IP_RANGE_START IP_RANGE_END NETWORK_CIDR script variables as appropriate

join the network from the client:

zerotier-cli join 96247cd977000001

authorize the client on the controller:

use the authorize_ztmember.sh script to authorize each client

authorize_zt_member. sh NETWORK_ID MEMBER_ID

## Step 3: Create moon(s)

Moons are additional root servers that supplement the default planet:

```bash
# 1. On your root server, generate a moon definition
cd /var/lib/zerotier-one
sudo zerotier-idtool initmoon identity.public > moon.json

# 2. Edit moon.json to add your server's IP
sudo nano moon.json
# Update "stableEndpoints" with your server's public IP:
# "stableEndpoints": [ "YOUR.PUBLIC.IP.HERE/9993" ]

# 3. Generate the moon file
sudo zerotier-idtool genmoon moon.json
# This creates a file like: 000000xxxxxxxxxxxx.moon

# 4. Distribute to all nodes
# Copy the .moon file to each node's moons.d directory:
sudo mkdir -p /var/lib/zerotier-one/moons.d
sudo cp 000000xxxxxxxxxxxx.moon /var/lib/zerotier-one/moons.d/
sudo systemctl restart zerotier-one
```

## Using zerotier-idtool Commands

Common zerotier-idtool commands for planet/moon creation:

```bash
# Generate a new identity
zerotier-idtool generate identity.secret identity.public

# Initialize a moon from an identity
zerotier-idtool initmoon identity.public > moon.json

# Generate a moon file from JSON
zerotier-idtool genmoon moon.json

# Get public key from secret
zerotier-idtool getpublic identity.secret

# Sign data (if needed)
zerotier-idtool sign identity.secret data.bin
```

## 4. Use Your Own Moons as Relays

Moons can act as relay servers without replacing the planet:

```bash
# Create moons on your servers
sudo zerotier-idtool initmoon identity.public > moon.json
# Edit and add your IPs
sudo zerotier-idtool genmoon moon.json

# Distribute to nodes - they'll prefer your m
```

## Installation Steps on the client side:

### 1. Create the moons.d directory
```bash
sudo mkdir -p /var/lib/zerotier-one/moons.d
````

### 2. Copy the moon file

```bash
# If you have the moon file locally
sudo cp YOUR_MOON_FILE.moon /var/lib/zerotier-one/moons.d/

# Or download it from a server
sudo wget -O /var/lib/zerotier-one/moons.d/YOUR_MOON_FILE.moon https://your-server.com/YOUR_MOON_FILE.moon
```

### 3. Set proper permissions

```bash
sudo chown zerotier-one:zerotier-one /var/lib/zerotier-one/moons.d/*.moon
sudo chmod 600 /var/lib/zerotier-one/moons.d/*.moon
```

### 4. Restart ZeroTier

```bash
sudo systemctl restart zerotier-one
```

### 5. Verify the moon is loaded

```bash
sudo zerotier-cli listmoons
```

