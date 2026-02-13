# Simple Market Service

End-to-end example of an ERC-8004-powered agent market. Includes smart contracts, a FastAPI registry/indexer, ZeroTier overlay network, and an A2A agent that auto-registers and responds to requests.

## Repository Layout

- `agent/` — A2A agent server and local test-chain helper
- `erc-8004-contracts/` — ERC-8004 Identity/Reputation/Validation registries (Hardhat)
- `erc-8004-registry-py/` — Registry/indexer API (FastAPI) for on-chain/off-chain sync
- `infra/zerotier/` — ZeroTier controller scripts

## Prerequisites

- make, curl, git
- Python 3.10+ with `uv`
- Node.js 12+ with npm
- ZeroTier CLI (optional, requires sudo)
- Anvil/Foundry (for local chain)

## CLI

Install the CLI and add `market` to your PATH:

```bash
cd cli
uv venv
uv pip install -e .
```

If `market` isn't found, ensure your user bin is on PATH (common default is `~/.local/bin`).

Install all component dependencies and venvs:

```bash
market install
```

## Order Creation (CLI)

Create a market order via the agent endpoint:

```bash
market order create \
  -o '{"gpu_model":"H200","quantity":1,"sla":99.9,"region":"California, US"}' \
  -d '{"token":"MOCK","amount":9.0}'
```

Optional flags:

- `--agent-url` (or `AGENT_URL`/`BASE_URL_OVERRIDE`) to target a specific agent
- `--duration-hours` to set duration (defaults to `1`)
- `token` may be a known symbol or contract address; amount is a float and converted using token decimals

## Quick Start

### 1. Start Local Chain

```bash
cd agent
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
cd agent
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
   Add `ZEROTIER_NETWORK=<network-id>` to `agent/.env`

4. **Authorize Nodes**:

   ```bash
   cd infra
   make add-node NODE_ID=<node-id-from-zerotier-cli-info>
   ```

Both registry and agent will auto-join ZeroTier when started if `ZEROTIER_NETWORK` is set.

**Note**: ZeroTier operations require `sudo`.

5. **Authorize Approved Waitlist Members**:

   Copy `infra/zerotier/.env.sample` to `infra/zerotier/.env` and set `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME`, and `ZEROTIER_NETWORK`. Requires `jq`.

   ```bash
   # Authorize all approved waitlist entries
   ./infra/zerotier/authorize_approved_members.sh

   # Retry entries that previously failed
   ./infra/zerotier/authorize_approved_members.sh --retry-errors

   # Limit records processed
   ./infra/zerotier/authorize_approved_members.sh --max-entries 10
   ```

### Direct Script Usage

The `make` targets above wrap the following scripts in `infra/zerotier/`. You can run them directly if needed.

#### `create_ztnetwork.sh`

Creates a new private ZeroTier network and writes the generated network ID back to `infra/zerotier/.env`. Pass `--join` to also join the network and authorize the local node.

```bash
./infra/zerotier/create_ztnetwork.sh          # create only
./infra/zerotier/create_ztnetwork.sh --join    # create network then join and authorize local node
```

Required env vars in `infra/zerotier/.env`: `NETWORK_NAME`, `IP_RANGE_START`, `IP_RANGE_END`, `NETWORK_CIDR`, `CONTROLLER_URL`, `CONTROLLER_PORT`. Optionally set `CONTROLLER_AUTH_TOKEN` (falls back to reading the local auth token file). Requires `sudo`.

#### `authorize_zt_member.sh`

Authorizes a pending member on an existing network. The member must have already run `zerotier-cli join <NETWORK_ID>`.

```bash
# Uses ZEROTIER_NETWORK from .env as the network ID
./infra/zerotier/authorize_zt_member.sh <MEMBER_ID>

# Explicit network ID
./infra/zerotier/authorize_zt_member.sh <NETWORK_ID> <MEMBER_ID>
```

Required env vars in `infra/zerotier/.env`: `CONTROLLER_URL`, `CONTROLLER_PORT`, `ZEROTIER_NETWORK`. Requires `sudo`.

## Useful Commands

- Agent playground: `make playground` in `agent`
- ZeroTier network info: `sudo zerotier-cli listnetworks`
