# Simple Market Service

End-to-end example of an ERC-8004-powered agent market. Includes smart contracts, a FastAPI registry/indexer, ZeroTier overlay network, and an A2A agent that auto-registers and responds to requests.

## Repository Layout

- `agents/a2a-agent-trader/` — A2A agent server and local test-chain helper
- `erc-8004-contracts/` — ERC-8004 Identity/Reputation/Validation registries (Hardhat)
- `erc-8004-registry-py/` — Registry/indexer API (FastAPI) for on-chain/off-chain sync
- `infra/zerotier/` — ZeroTier controller scripts

## Prerequisites

- make, curl, git
- Python 3.10+ with `uv`
- Node.js 12+ with npm
- ZeroTier CLI (optional, requires sudo)
- Anvil/Foundry (for local chain)

## Quick Start

### 1. Start Local Chain

```bash
cd agents/a2a-agent-trader
make test-env
```

Note the RPC URL and port (keep this terminal open).

### 2. Deploy Contracts

In a new terminal:

```bash
cd erc-8004-contracts
npm install
ANVIL_RPC_URL=<rpc_url from step 1> npm run deploy:anvil
```

Note the deployed contract addresses.

### 3. Start Registry/Indexer

In a new terminal:

```bash
cd erc-8004-registry-py
uv sync
make serve
```

The registry runs on `http://localhost:8080` by default.

### 4. Configure and Start Agent

In a new terminal:

```bash
cd agents/a2a-agent-trader
make install
cp .env.sample .env
```

Edit `.env` with:

- Contract addresses from step 2
- `CHAIN_RPC_URL` (from step 1)
- `REGISTRY_URL=http://localhost:8080/`
- `AGENT_PRIV_KEY` and `AGENT_WALLET_ADDRESS` (use test keys)

Start the agent:

```bash
make serve-a2a
```

## ZeroTier Setup (Optional)

For ZeroTier overlay network:

1. **Create Network** (as controller):

   ```bash
   cd infra
   make install
   make create-network
   ```

   Note the network ID.

2. **Configure Indexer**:
   Add `ZEROTIER_NETWORK=<network-id>` to `erc-8004-registry-py/.env`

3. **Configure Agent**:
   Add `ZEROTIER_NETWORK=<network-id>` to `agents/a2a-agent-trader/.env`

4. **Authorize Nodes**:

   ```bash
   cd infra
   make add-node NODE_ID=<node-id-from-zerotier-cli-info>
   ```

Both registry and agent will auto-join ZeroTier when started if `ZEROTIER_NETWORK` is set.

**Note**: ZeroTier operations require `sudo`.

## Useful Commands

- Agent playground: `make playground` in `agents/a2a-agent-trader`
- ZeroTier network info: `sudo zerotier-cli listnetworks`
