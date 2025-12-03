# Using Anvil for Local Development

Anvil is a local Ethereum node that comes with Foundry. It's perfect for local development and testing of the ERC-8004 registry without needing testnet access or spending gas.

## Prerequisites

1. Install Foundry (which includes Anvil):
   ```bash
   curl -L https://foundry.paradigm.xyz | bash
   foundryup
   ```

2. Clone the ERC-8004 contracts repository:
   ```bash
   git clone https://github.com/erc-8004/erc-8004-contracts.git
   cd erc-8004-contracts
   ```

## Starting Anvil

Start Anvil in a separate terminal:

```bash
anvil
```

This will start a local Ethereum node on `http://127.0.0.1:8545` with:
- 10 test accounts pre-funded with 10,000 ETH each
- Chain ID: 31337
- Block time: instant (no mining delay)

You'll see output like:
```
Available Accounts
==================
(0) 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 (10000 ETH)
(1) 0x70997970C51812dc3A010C7d01b50e0d17dc79C8 (10000 ETH)
...

Private Keys
==================
(0) 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
(1) 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
...

Listening on 127.0.0.1:8545
```

## Deploying ERC-8004 Contracts to Anvil

### Option 1: Using Hardhat (Recommended)

If the erc-8004-contracts repo uses Hardhat:

```bash
cd erc-8004-contracts
npm install

# Deploy to Anvil
npx hardhat run scripts/deploy.js --network localhost
```

Or create a deployment script:

```bash
# Set Anvil as the network in hardhat.config.ts
# Then deploy:
npx hardhat run scripts/deploy.ts --network localhost
```

### Option 2: Using Foundry Scripts

If using Foundry, create a deployment script:

```solidity
// script/Deploy.s.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Script} from "forge-std/Script.sol";
import {IdentityRegistry} from "../contracts/IdentityRegistry.sol";
import {ReputationRegistry} from "../contracts/ReputationRegistry.sol";
import {ValidationRegistry} from "../contracts/ValidationRegistry.sol";

contract Deploy is Script {
    function run() external {
        vm.startBroadcast();
        
        IdentityRegistry identityRegistry = new IdentityRegistry();
        ReputationRegistry reputationRegistry = new ReputationRegistry();
        ValidationRegistry validationRegistry = new ValidationRegistry();
        
        vm.stopBroadcast();
        
        console.log("IdentityRegistry:", address(identityRegistry));
        console.log("ReputationRegistry:", address(reputationRegistry));
        console.log("ValidationRegistry:", address(validationRegistry));
    }
}
```

Then deploy:
```bash
forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --broadcast
```

### Option 3: Manual Deployment via web3.py/web3.js

You can also deploy contracts manually using web3 libraries, but the above methods are recommended.

## Configuring the Registry to Use Anvil

### Python Version

Update `.env`:

```env
# Anvil Configuration
CHAIN_ID=31337
RPC_URL=http://127.0.0.1:8545

# Deployed Contract Addresses (from deployment output)
IDENTITY_REGISTRY_ADDRESS=0x...  # Replace with deployed address
REPUTATION_REGISTRY_ADDRESS=0x...  # Replace with deployed address
VALIDATION_REGISTRY_ADDRESS=0x...  # Replace with deployed address
```

## Quick Start Script

Create a helper script to deploy contracts and update config:

```bash
#!/bin/bash
# scripts/setup-anvil.sh

# Start Anvil in background
anvil &
ANVIL_PID=$!

# Wait for Anvil to start
sleep 2

# Deploy contracts (adjust based on your deployment method)
cd erc-8004-contracts
npx hardhat run scripts/deploy.js --network localhost > /tmp/deployment.log 2>&1

# Extract addresses (adjust based on your deployment output format)
IDENTITY_REGISTRY=$(grep "IdentityRegistry" /tmp/deployment.log | awk '{print $NF}')
REPUTATION_REGISTRY=$(grep "ReputationRegistry" /tmp/deployment.log | awk '{print $NF}')
VALIDATION_REGISTRY=$(grep "ValidationRegistry" /tmp/deployment.log | awk '{print $NF}')

# Update .env files
echo "CHAIN_ID=31337" > .env.local
echo "RPC_URL=http://127.0.0.1:8545" >> .env.local
echo "IDENTITY_REGISTRY_ADDRESS=$IDENTITY_REGISTRY" >> .env.local
echo "REPUTATION_REGISTRY_ADDRESS=$REPUTATION_REGISTRY" >> .env.local
echo "VALIDATION_REGISTRY_ADDRESS=$VALIDATION_REGISTRY" >> .env.local

echo "Anvil setup complete!"
echo "Anvil PID: $ANVIL_PID"
echo "Contract addresses saved to .env.local"
```

## Testing with Anvil

### Using Test Accounts

Anvil provides test accounts you can use:

```python
# Python example
from web3 import Web3

w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:8545'))
account = w3.eth.account.from_key('0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80')
```

### Resetting Anvil State

To reset Anvil to a fresh state:

```bash
# Stop Anvil (Ctrl+C) and restart
anvil

# Or use --fork-block-number to reset to a specific block
anvil --fork-block-number 0
```

## Advantages of Using Anvil

1. **Fast**: Instant block times, no waiting for confirmations
2. **Free**: No gas costs, unlimited test ETH
3. **Deterministic**: Same accounts and state every time
4. **Isolated**: Doesn't affect testnet/mainnet
5. **Debuggable**: Can inspect state easily

## Troubleshooting

### Anvil not starting
- Check if port 8545 is already in use: `lsof -i :8545`
- Kill existing process: `kill -9 <PID>`

### Contracts not deploying
- Ensure Anvil is running before deployment
- Check RPC URL matches Anvil's address
- Verify contract addresses in deployment logs

### Registry can't connect
- Verify `RPC_URL` is `http://127.0.0.1:8545`
- Check Anvil is running: `curl http://127.0.0.1:8545`
- Ensure `CHAIN_ID` is `31337`

## Switching Between Anvil and Testnet

Create separate environment files:

- `.env.local` - For Anvil development
- `.env.testnet` - For Base Sepolia testnet
- `.env.production` - For production

Then use:
```bash
# Development
cp .env.local .env
uvicorn src.main:app --reload

# Testnet
cp .env.testnet .env
uvicorn src.main:app
```

