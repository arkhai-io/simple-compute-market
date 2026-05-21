# Seller quickstart

How to stand up a storefront on Base Sepolia, register on-chain, publish a
compute listing, and (optionally) drive real KVM provisioning from the same
machine. Tested end-to-end on a fresh Ubuntu 24.04 host, May 2026.

This walks the same path as `deploy-base-sepolia/` in the repo — that
directory is a working reference deployment you can copy/diff against if
anything below doesn't match what you see.

For the buyer side see [`buyer-quickstart.md`](./buyer-quickstart.md).

---

## What you'll have at the end

A `docker compose` stack with three services:

- **`registry`** — your own private indexer (or you can point at a shared one;
  see the addendum)
- **`sell_agent`** — the storefront HTTP server, registered on-chain via
  ERC-8004, publishing one or more listings
- **`provisioning`** — the ansible runner that creates VMs when a buyer settles

A buyer running `market buy --gpu-model …` from somewhere else on the
internet can discover your listing through the indexer, negotiate, escrow on
chain, and (in live mode) end up with SSH access to a fresh Ubuntu VM you
provisioned on this same host.

## Prerequisites

- Linux host with Docker + `docker compose` v2.
- Ethereum wallet on Base Sepolia with **some test ETH** (for gas) and
  whatever test token you plan to accept as payment. The reference deploy
  uses USDC on Base Sepolia
  (`0x036CbD53842c5426634e7929541eC2318f3dCF7e`). Get testnet ETH from any
  Base Sepolia faucet; USDC test funds from
  [faucet.circle.com](https://faucet.circle.com).
- A Base Sepolia RPC URL. The public `https://sepolia.base.org` works for
  light load; for anything sustained get an Infura or Alchemy key.
- (Live provisioning only) KVM-capable host — `egrep -c "(vmx|svm)"
  /proc/cpuinfo` > 0, `libvirtd` running, `ubuntu` (or whatever ansible user
  you choose) has passwordless sudo and is in the `libvirt` group.

If you're only doing the mock-provisioning rehearsal, any Linux box with
Docker works.

## 1. Get the code and build images

```bash
git clone <this repo>
cd simple-compute-market
make build-runtime-images
```

`build-runtime-images` produces the three images you need
(`arkhai:registry`, `arkhai:storefront`, `arkhai:provisioning`) and skips
the dev-only things (`build-buyer`, `build-market-contract-deployer`,
`build-test-env`, `build-test-image`) that the bare `make build` target
also pulls in. The full target takes ~10 minutes; this one is ~3.

If `make build-runtime-images` fails on cross-platform torch resolution
during a `reinit` step, that's a known issue on macOS/arm64; build on a
Linux host instead.

## 2. Configure the seller

`market-storefront` (and the storefront server) reads a single TOML file
from `$XDG_CONFIG_HOME/arkhai/config.toml`. In the container we set
`XDG_CONFIG_HOME=/etc` and mount the file at `/etc/arkhai/config.toml`.

Start from this skeleton (`deploy-base-sepolia/config.seller.toml` is the
working reference):

```toml
[wallet]
address     = "0xYourSellerAddress"
private_key = "0xYourSellerPrivateKey"
# Placeholder; the seller's ssh_public_key isn't used in buyer-driven flows.
ssh_public_key = "ssh-ed25519 AAAA…placeholder seller@host"

[chain]
name     = "base_sepolia"
chain_id = 84532
rpc_url  = "https://base-sepolia.infura.io/v3/<YOUR_KEY>"
# alkahest-py has built-in addresses for base_sepolia; omit alkahest_address_config_path.

[registry]
# Where to publish listings. One URL = single private indexer.
# Multiple = fan out to several indexers.
urls                      = ["http://registry:8080"]
identity_registry_address = "0x8004A818BFB912233c491871b3d84c89A494BD9e"

[registry.auth]
# If you're running your own private indexer with REGISTRY_REQUIRE_API_KEY=true
# (see the addendum), bearer-token here. For a fully public indexer, omit.
"http://registry:8080" = "your-shared-token"

[seller]
agent_id            = "seller_one"             # any Python-identifier string (no dashes!)
port                = 8001
base_url            = "http://<PUBLIC_IP>:8001/"
db_path             = "/app/agent.db"
log_file_path       = "./logs/seller.log"
resources_csv_path  = "/app/resources.csv"
admin_api_key       = "rehearsal-admin-key"
# Pin AFTER your first successful registration — see §5 below.
# onchain_agent_id  = "5955"

[seller.provisioning]
service_url   = "http://provisioning:8081"
mode          = "http"                          # "mock" for dry-run
poll_interval = 2

[seller.negotiation]
policy_mode = "bisection"

[seller.pricing]
default_min_price            = "2"              # raw token base units, per hour
# 0x ERC-20 address used when a CSV row has no `token` column.
# Decimals + symbol are resolved on chain via [chain].rpc_url and cached
# at $XDG_CACHE_HOME/arkhai/tokens/<chain_id>.json.
default_token_address        = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
default_max_duration_seconds = 86400
```

A few non-obvious points:

- `agent_id` must be a Python identifier. `seller-one` will be rejected;
  `seller_one` is fine.
- `base_url` is what buyers (and the indexer's "well-known" probes) hit.
  Use the public IP/hostname of this host, not `localhost`.
- Prices throughout the codebase are **raw token base units**, not whole
  tokens. For USDC (6 decimals), `min_price = "2"` means 0.000002 USDC/hr.
  Use `"2000000"` to mean 2 USDC/hr.
- `[registry.auth]` keys must exactly match the URLs in `[registry] urls`,
  including the scheme and trailing-slash treatment.

## 3. resources.csv

This is what the seller offers. One row = one slice the storefront can
sell:

```csv
resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host
compute-bs-001,compute.gpu,H200,count,1,available,2,0x036CbD53842c5426634e7929541eC2318f3dCF7e,86400,H200,99.0,"California, US",btc1
```

The critical column for live provisioning is **`attribute.vm_host`** — it
must match a host alias in the provisioning service's ansible inventory
(see §7). The bundled inventory currently has `piknik1`, `nodeinfra1`,
`btc1`, `ww1`; if you're deploying on a new machine you either add an
inventory entry or reuse one of those aliases and re-seed.

The `token` column is a 0x ERC-20 contract address — symbol shorthand
("USDC") was removed in favour of chain-resolved metadata. The storefront
eth-calls `symbol()` and `decimals()` against your `[chain].rpc_url` the
first time it sees a token address; results are cached at
`$XDG_CACHE_HOME/arkhai/tokens/<chain_id>.json`. Rows can omit the
`token` column to fall back to `[seller.pricing].default_token_address`.

`attribute.gpu_model` and `attribute.region` are free-form strings — the
indexer's `filter-spec.yaml` is the authoritative vocabulary (v2 ships with
~40 common NVIDIA models).

## 4. docker-compose.yml

A minimal seller-side compose looks like this. The full reference is
[`deploy-base-sepolia/docker-compose.yml`](../deploy-base-sepolia/docker-compose.yml);
copy from there if you want the production-ish version with healthchecks
and memory limits.

```yaml
services:
  registry:
    image: arkhai:registry
    ports: ["8080:8080"]
    environment:
      - DATABASE_URL=sqlite:///./indexer.db
      - CHAIN_ID=84532
      - RPC_URL=https://base-sepolia.infura.io/v3/<YOUR_KEY>
      - IDENTITY_REGISTRY_ADDRESS=0x8004A818BFB912233c491871b3d84c89A494BD9e
      - REPUTATION_REGISTRY_ADDRESS=0x8004B663056A597Dffe9eCcC1965A193B7388713
      - REGISTRY_START_BLOCK=41707000      # see §5
      - REGISTRY_REQUIRE_API_KEY=true
      - REGISTRY_ADMIN_API_KEY=rehearsal-admin-token
      - REGISTRY_BOOTSTRAP_API_KEY=rehearsal-shared-token
    networks: [market-network]

  sell_agent:
    image: arkhai:storefront
    container_name: market-agent-sell
    ports: ["8001:8001"]
    cap_add: [NET_ADMIN, SYS_MODULE]
    devices: ["/dev/net/tun:/dev/net/tun"]
    environment:
      - XDG_CONFIG_HOME=/etc
      - ARKHAI_PROVISIONING_MODE=http        # "mock" to skip ansible
      - PYTHONPATH=/app:/app/src
    volumes:
      - ./config.seller.toml:/etc/arkhai/config.toml:ro
      - ./resources.csv:/app/resources.csv:ro
    depends_on:
      registry:
        condition: service_healthy
    networks: [market-network]

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
    networks: [market-network]

  provisioning:
    image: arkhai:provisioning
    container_name: market-provisioning
    environment:
      - DATABASE_URL=sqlite:////app/data/provisioning.db
      - REDIS_URL=redis://redis:6379
      # Drop ACTIVE_PROFILES=mock — Dockerfile default ("docker") drives real KVM.
      - PROVISIONING_STOREFRONT_URL=http://sell_agent:8001
      - PROVISIONING_STOREFRONT_ADMIN_KEY=rehearsal-admin-key
    volumes:
      # SSH key the container uses to reach the KVM host. See §7.
      - ./keys/id_ed25519:/home/appuser/.ssh/id_ed25519:ro
      - ../compute-provisioning-iac:/app/compute-provisioning-iac
    depends_on:
      redis: { condition: service_healthy }
      registry: { condition: service_healthy }
    networks: [market-network]

networks:
  market-network: { driver: bridge }
```

## 5. Bring it up, register, publish

```bash
docker compose up -d
docker compose logs -f sell_agent
```

The storefront auto-runs `register` on startup if `onchain_agent_id` isn't
pinned. Watch for `Registering agent on-chain...` followed by either:

- `[STARTUP] Registered as agent N` — first time, costs gas, you'll see a
  TX hash.
- `[STARTUP] ✓ No Changes Detected` — pinned to an existing agent_id, no
  gas.

**Pin the on-chain ID after the first successful registration.** Add
`onchain_agent_id = "<N>"` under `[seller]` in your config — otherwise
every container restart burns gas re-registering. The indexer also needs
to discover this agent; if you set up a fresh private registry, set
`REGISTRY_START_BLOCK` to a block number before your registration tx so
the initial sync picks it up (the default 1000-block lookback misses
historical registrations).

Now publish a listing:

```bash
docker compose exec sell_agent market-storefront publish --inventory /app/resources.csv
```

The `publish` CLI signs `create_listing` requests with the seller's
private key from config and POSTs to the storefront, which then fans out
to every URL in `[registry] urls`. Successful output:

```
✓ compute-bs-001 → listing f0ba3664-… (status: created)
```

## 6. Verify

```bash
# Listing is in the indexer
curl -sH "Authorization: Bearer rehearsal-shared-token" \
  http://<HOST>:8080/agents/<onchain_agent_id>/listings | jq '.listings[]'

# Storefront returns it directly too
curl -s http://<HOST>:8001/api/v1/listings | jq '.listings[]'

# Agent card is discoverable on chain → off chain
curl -s http://<HOST>:8001/.well-known/agent-card.json | jq
```

At this point a buyer somewhere else can `market buy --gpu-model H200`
and (in mock mode) get back simulated VM credentials. Real KVM
provisioning is one more step.

## 7. Switching to live KVM provisioning

Mock mode validates the storefront ↔ chain ↔ registry surface without
touching libvirt. To actually create a VM on real hardware:

1. **Drop `ACTIVE_PROFILES=mock` on the provisioning service** — the
   Dockerfile default is `docker`, which loads
   `config-docker.yml` pointing at the baked-in IaC at
   `/opt/compute-provisioning-iac/`.

2. **Drop `MOCK_PROVISIONING_SUCCESS=true` on the storefront** and set
   `ARKHAI_PROVISIONING_MODE=http` (or just leave the toml's
   `[seller.provisioning] mode = "http"` and don't override via env).

3. **Mount an SSH key** at `/home/appuser/.ssh/id_ed25519` in the
   provisioning container. The bundled ansible inventory points
   `ansible_ssh_private_key_file=~/.ssh/id_ed25519`, which inside the
   container expands to `/home/appuser/.ssh/id_ed25519`. Generate a
   dedicated keypair, install the pubkey in the KVM host's
   `authorized_keys`, mount the privkey:

   ```bash
   ssh-keygen -t ed25519 -N "" -f ./keys/id_ed25519
   ssh-copy-id -i ./keys/id_ed25519 ubuntu@<KVM_HOST>
   chmod 600 ./keys/id_ed25519
   ```

4. **Make sure `attribute.vm_host` in `resources.csv` matches an inventory
   alias.** The bundled inventory in
   `compute-provisioning-iac/ansible/inventory/hosts` ships with a few
   hardcoded hosts (`piknik1`, `nodeinfra1`, `btc1`, `ww1`). If you're
   deploying on a new box either:
   - Pick the alias that points at the right IP/user and use that in
     `resources.csv`. **The inventory file is baked into the image at
     build time** — `/opt/compute-provisioning-iac/ansible/inventory/hosts`
     — so it has to be right when you build, or you have to seed manually
     via `POST /api/v1/hosts/import`.
   - Or edit `compute-provisioning-iac/ansible/inventory/hosts`, add your
     entry, rebuild the provisioning image.

5. **Host-side prerequisites:** the ansible user (default `ubuntu`) needs
   passwordless sudo (`sudo -n true && echo ok`), must be in the
   `libvirt` group, and `libvirtd` must be running. The playbook handles
   the rest (cloud-init, virt-install, iptables DNAT for port-forwarding
   the VM's SSH port to the host's public IP).

To verify the provisioning container can reach the host:

```bash
docker compose exec provisioning ansible \
  -i /opt/compute-provisioning-iac/ansible/inventory/hosts \
  <your_host_alias> -m ping
```

Should return `SUCCESS / ping: pong`. After that, the next `market buy`
that hits this seller will actually create a VM, return SSH credentials
to the buyer, and bill them on chain.

## Common sharp edges

- **`onchain_agent_id` unpinned + storefront restarts** = ETH burned on
  every restart. Always pin after the first registration.
- **`REGISTRY_START_BLOCK` unset on a fresh indexer** = your agent doesn't
  show up in `GET /agents/<id>` because the default 1000-block lookback
  missed your registration tx. Set it to ~1000 blocks before your reg tx.
- **`resources.csv` `vm_host` set to an inventory alias the indexer or
  provisioning DB doesn't know about** = your listing won't be reachable
  and settle will fail with "host not found". Match the alias exactly.
- **`resources.csv` `token` column must be a 0x ERC-20 address** —
  symbol shorthand ("USDC") is rejected at import time. Decimals are
  resolved on chain from `[chain].rpc_url`, so make sure that's set
  and reachable.
- **`agent_id` with a dash** = rejected. Python identifiers only.
- **`ARKHAI_PROVISIONING_MODE=mock` env var on the storefront overrides
  the toml's `mode = "http"`** — env wins. Make sure both agree (the
  cleanest is to drop the env var and let the toml drive it).
- **Mounting `agent.db` as a docker named volume** = root-owned dir,
  appuser-in-container can't write, storefront crashes on startup. Keep
  the db inside container-owned paths (`/app/agent.db`) and accept loss
  on `compose down`, or use bind-mount + chown 1000:1000 in advance.

---

## Addendum A: Deploying your own private indexer registry

The reference deployment includes a `registry` service alongside the
seller, with `REGISTRY_REQUIRE_API_KEY=true`. Reasons to run your own
indexer rather than rely on a shared one:

- **Privacy / curation** — you control who can query, who can publish.
- **No rate limits** — public indexers throttle.
- **Custom `filter-spec.yaml`** — vocabulary for `gpu_model`, `region`,
  etc. is per-indexer.
- **You're testing alone** and don't need fanout.

### Stand-alone or co-located

The compose example in §4 has the registry co-located with the seller. To
run a stand-alone indexer (sellers and buyers elsewhere on the internet
all point at it), use the same `arkhai:registry` image with these env
vars:

```yaml
registry:
  image: arkhai:registry
  ports: ["8080:8080"]
  environment:
    - DATABASE_URL=sqlite:///./indexer.db
    - CHAIN_ID=84532
    - RPC_URL=https://base-sepolia.infura.io/v3/<YOUR_KEY>
    # Use the CREATE2 vanity addresses for ERC-8004 v0.1 on Base Sepolia:
    - IDENTITY_REGISTRY_ADDRESS=0x8004A818BFB912233c491871b3d84c89A494BD9e
    - REPUTATION_REGISTRY_ADDRESS=0x8004B663056A597Dffe9eCcC1965A193B7388713
    # Optional but recommended on a fresh indexer — backfill past your
    # earliest agent registration. Without this, the indexer's first sync
    # walks only the last 1000 blocks and silently drops historical
    # agents. Set it once at deploy time, ignore after that (only
    # consulted when the agents table is empty).
    - REGISTRY_START_BLOCK=41707000
    - PORT=8080
    - HOST=0.0.0.0
    # Auth: bearer-token gated. Without these, every endpoint is public.
    - REGISTRY_REQUIRE_API_KEY=true
    # The admin key: gates /admin/api-keys for minting/revoking per-user keys.
    - REGISTRY_ADMIN_API_KEY=admin-secret-rotate-this
    # Bootstrap: seeds a single api_keys row on first boot if the table
    # is empty. Lets the registry come up with one operator-known key
    # without an admin orchestration step. Safe to leave set after first
    # run; the row persists across restarts.
    - REGISTRY_BOOTSTRAP_API_KEY=shared-bootstrap-token
```

### Auth flow

- **Admin mints/revokes keys** at `POST /admin/api-keys`, using
  `Authorization: Bearer <REGISTRY_ADMIN_API_KEY>` (set above, separate
  from the api_keys table).
- **Sellers publish** with `Authorization: Bearer <api_key>` where the
  api_key is either the bootstrap value (first time) or one minted via
  the admin endpoint. Storefront config picks it up via
  `[registry.auth]`.
- **Buyers query** with the same auth — `[registry.auth]` on the buyer
  side mirrors the seller's config.

### Operational checks

```bash
# Healthy?
curl -sf http://<INDEXER_HOST>:8080/health

# Sync caught up?
docker compose logs registry | grep -i "Synced up to block"

# Filter-spec served (what vocabulary your listings must match)?
curl -s http://<INDEXER_HOST>:8080/filter-spec | jq

# Listings visible?
curl -sH "Authorization: Bearer <key>" \
  http://<INDEXER_HOST>:8080/agents/<onchain_agent_id>/listings | jq
```

### Hooking sellers and buyers up to it

In every seller's `[registry]` block:

```toml
[registry]
urls = ["http://<INDEXER_HOST>:8080"]
identity_registry_address = "0x8004A818BFB912233c491871b3d84c89A494BD9e"

[registry.auth]
"http://<INDEXER_HOST>:8080" = "<api_key>"
```

In every buyer's `~/.config/arkhai/config.toml`, the same. The
`[registry.auth]` key has to exactly match the URL in `[registry] urls`,
including scheme and any trailing slash.

That's the full registry deployment story. Once it's up, multiple sellers
can publish into it and any buyer with credentials can discover their
listings — `simple-compute-market` itself doesn't run a global indexer,
operators run their own.
