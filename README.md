# Simple Market Service

End-to-end example of an ERC-8004-powered agent market. It includes smart contracts, a FastAPI registry/indexer, a ZeroTier-based overlay network, and an A2A agent that auto-registers responds to.

## Repository Layout

- `agents/a2a-agent-trader/` — agent app (Starlette A2A server) and local test-chain helper
- `erc-8004-contracts/` — ERC-8004 Identity/Reputation/Validation registries (Hardhat)
- `erc-8004-registry-py/` — registry/indexer API (FastAPI) for on-chain/off-chain sync
- `infra/zerotier/` — ZeroTier controller scripts

## Prerequisites

- make, curl, git
- Python 3.10+ with `uv`
- Node.js 12+ with npm
- ZeroTier CLI (`make install` in `infra/` installs it; requires sudo)
- Anvil/Foundry (for local chain via `make test-env`)

## Local Development Setup
Start local chain (keep this terminal open)
```bash
cd agents/a2a-agent-trader
make test-env
```

Note the RPC URL, especially the port.

## Market + ZeroTier Setup

### Registry and Indexer
Deploy ERC-8004 contracts to the local chain:
```bash
cd ../../erc-8004-contracts
npm install
ANVIL_RPC_URL=<rpc_url from local chain> npm run deploy:anvil
```

Run the Registry/Indexer (separate terminal):
```bash
cd erc-8004-registry-py
uv sync
uv run uvicorn src.main:app --host 0.0.0.0 --port 8080
```

## ZeroTier Setup
As the ZeroTier Controller, create a ZeroTier network:
```bash
cd infra
make install             # installs zerotier (sudo)
make create-network      # prints the new network ID
```

Populate `infra/zerotier/.env` with `ZEROTIER_NETWORK=<network-id>` so other make targets can use it.

Authorize new Agents (ZeroTier nodes) joining the network:
```bash
cd infra
make add-node NODE_ID=<member-id-from-zerotier-cli-info>
```

Agents join the market network automatically:
- Set `ZEROTIER_NETWORK=<network-id>` in `agents/a2a-agent-trader/.env`
- Run `make serve-a2a`; the agent joins ZeroTier automatically
- Send the agent’s ZeroTier node ID to the market controller so they can authorize it, in order to participate in the network and obtain an IP.

## Agent Setup
Install agent deps:
```bash
cd agents/a2a-agent-trader
make install
```

Start the agent (auto-joins ZeroTier if ZEROTIER_NETWORK is set)
```bash
cd agents/a2a-agent-trader
make serve-a2a # optional ENV_FILE=alice.env
```

Note that ZeroTier requires `sudo`.

Configure the agent:
```bash
cd ../agents/a2a-agent-trader
cp .env.sample .env
# Set:
# IDENTITY_REGISTRY_ADDRESS / REPUTATION_REGISTRY_ADDRESS / VALIDATION_REGISTRY_ADDRESS (from deployment)
# CHAIN_RPC_URL (same rpc_url as step 2)
# REGISTRY_URL=http://localhost:8080/
# AGENT_PRIV_KEY / AGENT_WALLET_ADDRESS (use test keys from step 2)
# ZEROTIER_NETWORK=<your network ID if using ZeroTier>
```

On CTRL+C (`SIGINT`), `serve-a2a` will leave the ZeroTier network, also requiring `sudo`.

## Useful Commands
Agent playground (no A2A): `make playground` in agents/a2a-agent-trader
ZeroTier network info: `sudo zerotier-cli listnetworks`