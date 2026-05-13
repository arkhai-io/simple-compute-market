# Simple Market Service (SMS)

Simple Market Service (SMS) is a reference implementation of Arkhai's vision for generalized agent-driven marketplaces. The goal is to support open markets for assets and services such as compute, storage, bandwidth, energy, information, real-world assets, and, in practice, almost anything that can be described, negotiated, and exchanged by autonomous buyers and sellers over open network infrastructure instead of a centralized marketplace.

More concretely, this repo packages a marketplace architecture inspired by Arkhai's [Compositional Game Theory docs](https://github.com/arkhai-io/cgt) into working software: an ERC-8004-based agent registry, a market storefront, CLI workflows for orders and operations, and supporting services for settlement, networking, and provisioning. The original direction was to model the system more formally through CGT, but both the docs and this implementation operate at a higher level of granularity rather than using compositional game theory in a strict mathematical sense.

## Technology Stack

- [Alkahest](https://github.com/arkhai-io/alkahest) for programmable peer-to-peer agreements and escrow-backed settlement flows used by the market agent.
- [Compositional Game Theory (CGT)](https://github.com/arkhai-io/cgt) as design inspiration for the marketplace, negotiation, and distributed-systems patterns in this repo; the docs and implementation are CGT-inspired rather than strict formalizations.
- [ZeroTier](https://www.zerotier.com/) for optional overlay networking between agents and supporting services.
- [FastAPI](https://fastapi.tiangolo.com/) for the registry/indexer and async provisioning HTTP services.
- [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) for on-chain agent identity, metadata, and discovery.

## Repository Layout

- `buyer/` — Buyer-side CLI (`market` console script)
- `storefront/` — Provider-side server + admin CLI (`market-storefront` console script)
- `service/` — Shared infra clients (chain, alkahest, registry indexer)
- `policy/` — Domain-agnostic negotiation policy engine
- `erc-8004-contracts/` — ERC-8004 Identity/Reputation/Validation registries (Hardhat)
- `erc-8004-registry-py/` — Registry/indexer API (FastAPI) for on-chain/off-chain sync
- `infra/zerotier/` — ZeroTier controller scripts

## Prerequisites

- make, curl, git
- Python 3.12+ with `uv`
- Node.js 12+ with npm
- ZeroTier CLI (optional, requires sudo)
- Anvil/Foundry (for local chain)

## CLI

To build the CLI and add `market` to your PATH:

```bash
make build-buyer
```

This will make the cli at ./buyer/dist/market

You can then run it using e.g. market -v

If `market` isn't found, ensure the dist folder is on PATH.

## Order Creation (CLI)

Create a market order via the agent endpoint:

```bash
market listing create \
  -o '{"gpu_model":"H200","gpu_count":1,"sla":99.9,"region":"California, US"}' \
  -d '{"token":"MOCK","amount":9.0}'
```

Optional flags:

- `--agent-url` (or `AGENT_URL`/`BASE_URL_OVERRIDE`) to target a specific agent
- `--duration-hours` to set duration (defaults to `1`)
- `token` may be a known symbol or contract address; amount is a float and converted using token decimals

## Portfolio Import (CLI)

Seed/update the local resource portfolio from CSV:

```bash
market portfolio import-csv path/to/resources.csv
```

Try the bundled sample:

```bash
market portfolio import-csv storefront/src/market_storefront/data/resources.sample.csv --dry-run
```

Optional flags:

- `--dry-run` validate and report without writing to DB
- `--env` path to env file used by storefront import script (defaults to `storefront/.env`)
- `--db-path` override target SQLite DB path (otherwise uses `AGENT_DB_PATH` from env)

CSV columns:

- Core columns: `resource_id` (optional, UUID auto-generated if blank), `resource_type` (required), `resource_subtype`, `unit`, `value`, `state`
- Attribute columns: any `attribute.*` column maps into `attributes` JSON (e.g., `attribute.region`, `attribute.vm_host`)

## Publishing Artifacts to Artifact Registry

Built artifacts (Docker images, Helm chart, Python wheels, CLI binary) are
pushed to GCP Artifact Registry in `compute-market-internal-infra`. Registry URLs and
IAM are managed there; this repo only pushes.

### One-time machine setup

Configure the Docker credential helper so `docker push` and `helm push` (OCI)
authenticate via your `gcloud` identity:

```sh
gcloud auth configure-docker us-central1-docker.pkg.dev
```

`gcloud` ADC must also be configured (see ADC setup in the `compute-market-internal-infra`
README). The Python wheel push and CLI upload use ADC directly; no additional
setup is needed for those.

### Build before pushing

```sh
make build
```

### Push to dev (default)

```sh
make push-runtime-artifacts
```

### Push to a specific environment

Override `AR_PROJECT` to target preprod or prod:

```sh
make push-runtime-artifacts AR_PROJECT=compute-market-1-preprod
make push-runtime-artifacts AR_PROJECT=compute-market-1-prod
```

### Push individual artifact types

```sh
make push-images   # Docker images (registry, storefront, provisioning)
make push-helm     # Helm chart (OCI push to helm repo)
make push-wheels   # Python wheels (storefront-client, registry-client, provisioning-service)
make push-cli      # CLI binary (market executable)
```

Artifacts are tagged with the current git short SHA. The SHA tag is the only
tag written at push time; semver tags are applied at promotion time by the
CI/CD pipeline in `compute-market-internal-infra`.

## Quick Start

### 1. Start Local Chain

```bash
cd agent
make test-env
```

Note the RPC URL and port (keep this terminal open). It runs on `http://localhost:45165` by default.

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

### 4. Configure and Start the Seller Agent

In a new terminal:

```bash
cd storefront
uv sync --find-links ../.dist
market-storefront config init-user   # scaffolds $XDG_CONFIG_HOME/arkhai/config.toml
```

Edit the rendered config with:

- Contract addresses from step 2 (`registry.identity_registry_address`,
  `chain.alkahest_address_config_path`)
- `chain.rpc_url` (from step 1)
- `registry.url = "http://localhost:8080"`
- `wallet.private_key` and `wallet.address` (test keys)

Register on-chain (one-shot), then start the server:

```bash
market-storefront register
market-storefront serve
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

Required env vars in `infra/zerotier/.env`: `NETWORK_NAME`, `IP_RANGE_START`, `IP_RANGE_END`, `NETWORK_CIDR`, `CONTROLLER_URL`. Optionally set `CONTROLLER_AUTH_TOKEN` (falls back to reading the local auth token file). Requires `sudo`.

#### `authorize_zt_member.sh`

Authorizes a pending member on an existing network. The member must have already run `zerotier-cli join <NETWORK_ID>`.

```bash
# Uses ZEROTIER_NETWORK from .env as the network ID
./infra/zerotier/authorize_zt_member.sh <MEMBER_ID>

# Explicit network ID
./infra/zerotier/authorize_zt_member.sh <NETWORK_ID> <MEMBER_ID>
```

Required env vars in `infra/zerotier/.env`: `CONTROLLER_URL`, `ZEROTIER_NETWORK`. Requires `sudo`.

## Useful Commands

- ZeroTier network info: `sudo zerotier-cli listnetworks`
- Inspect/edit user config: `market-storefront config show`
- Reclaim an expired buyer escrow: `market escrow reclaim --escrow-uid 0x...`
