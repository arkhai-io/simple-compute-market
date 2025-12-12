
# Creating Your Own ZeroTier Network Using CLI Tools

Here's how to create and manage your own ZeroTier network using only command-line tools:

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

