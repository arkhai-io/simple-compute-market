# Simple Compute Market

Simple Compute Market is a reference implementation of Arkhai's vision for generalized agent-driven marketplaces. The goal is to support open markets for assets and services such as compute, storage, bandwidth, energy, information, real-world assets, and, in practice, almost anything that can be described, negotiated, and exchanged by autonomous buyers and sellers over open network infrastructure instead of a centralized marketplace.

More concretely, this repo packages a marketplace architecture inspired by Arkhai's [Compositional Game Theory docs](https://github.com/arkhai-io/cgt) into working software: an ERC-8004-based agent registry, a market storefront, CLI workflows for orders and operations, and supporting services for settlement, networking, and provisioning. The original direction was to model the system more formally through CGT, but both the docs and this implementation operate at a higher level of granularity rather than using compositional game theory in a strict mathematical sense.

## Technology Stack

- [Alkahest](https://github.com/arkhai-io/alkahest) for programmable peer-to-peer agreements and escrow-backed settlement flows used by the market agent.
- [Compositional Game Theory (CGT)](https://github.com/arkhai-io/cgt) as design inspiration for the marketplace, negotiation, and distributed-systems patterns in this repo; the docs and implementation are CGT-inspired rather than strict formalizations.
- [ZeroTier](https://www.zerotier.com/) for optional overlay networking between agents and supporting services.
- [FastAPI](https://fastapi.tiangolo.com/) for the registry/indexer and async provisioning HTTP services.
- [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) for on-chain agent identity, metadata, and discovery.

## Repository Layout

- `buyer/` — Buyer-side CLI (`market` console script)
- `storefront/` — Seller-side server + admin CLI (`market-storefront` console script)
- `provisioning-service/` — KVM provisioning microservice (Ansible-driven)
- `service/` — Shared infra clients (chain, alkahest, registry indexer)
- `policy/` — Domain-agnostic negotiation policy engine
- `erc-8004-contracts/` — ERC-8004 Identity/Reputation/Validation registries (Hardhat)
- `erc-8004-registry-py/` — Registry/indexer API (FastAPI) for on-chain/off-chain sync
- `compose/` — Docker Compose stacks for the seller side
- `infra/zerotier/` — ZeroTier controller scripts
- `docs/` — Operator quickstarts and architecture notes

## Quickstarts

Pick the role you're standing up:

- **Buy compute** → [`docs/buyer-quickstart.md`](./docs/buyer-quickstart.md)
- **Sell compute** → [`docs/seller-quickstart.md`](./docs/seller-quickstart.md)
- **Run your own indexer registry** → [`docs/indexer-quickstart.md`](./docs/indexer-quickstart.md)
- **Add FRP reverse-proxy for VM subdomains** → [`docs/seller-frp-setup.md`](./docs/seller-frp-setup.md)

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

## ZeroTier Setup (Optional)

ZeroTier provides an optional overlay network between buyers, sellers, and
indexers. Buyers join it via `market network join`; operators run the
controller scripts below. All controller operations require `sudo`.

1. **Create Network** (as controller):

   ```bash
   cd infra
   make install
   make create-network
   ```

   Note the network ID.

2. **Authorize Nodes**:

   ```bash
   cd infra
   make add-node NODE_ID=<node-id-from-zerotier-cli-info>
   ```

3. **Authorize Approved Waitlist Members**:

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
