# Seller quickstart

How to stand up a storefront on Base Sepolia, register on-chain, publish a
compute listing, and (optionally) drive real KVM provisioning from the same
machine. Tested end-to-end on a fresh Ubuntu 24.04 host, May 2026.

For the buyer side see [`buyer-quickstart.md`](./buyer-quickstart.md).

---

## What you'll have at the end

A `docker compose` stack with three services (defined in
[`compose/seller.yml`](../compose/seller.yml)):

- **`seller-agent`** — the storefront HTTP server, registered on-chain via
  ERC-8004, publishing one or more listings
- **`seller-redis`** — job queue for the provisioning service
- **`seller-provisioning`** — the ansible runner that creates VMs when a
  buyer settles

Plus an **indexer registry** somewhere — either a shared/public one (you just
point `[registry] urls` at its URL) or your own private one running in a
sibling compose (see Addendum A). The seller compose itself stays
registry-agnostic.

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
git clone https://github.com/arkhai-io/simple-compute-market.git
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

The storefront reads its config from `$XDG_CONFIG_HOME/arkhai/storefront.toml`.
The compose sets `XDG_CONFIG_HOME=/etc` and mounts your file at
`/etc/arkhai/storefront.toml`. The default mount source is
`./config.seller.toml` relative to the directory you run `docker compose`
from — override with the `SELLER_CONFIG_PATH` env var if you keep it
elsewhere.

`market-storefront config init-user` writes a commented-out skeleton with
every supported key, but its template is Anvil-flavored. The TOML below is
the Base Sepolia version you'll actually deploy:

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
# Where to publish listings. One URL = single indexer.
# Multiple = fan out to several indexers.
urls                      = ["http://<INDEXER_HOST>:8080"]
identity_registry_address = "0x8004A818BFB912233c491871b3d84c89A494BD9e"

[registry.auth]
# If the indexer requires API keys (REGISTRY_REQUIRE_API_KEY=true; see
# Addendum A), put the bearer token here. For a fully public indexer, omit.
"http://<INDEXER_HOST>:8080" = "your-shared-token"

[seller]
agent_id            = "seller_one"             # any Python-identifier string (no dashes!)
port                = 8001
base_url            = "http://<PUBLIC_IP>:8001/"
db_path             = "./src/market_storefront/data/sell-agent/agent.db"
log_file_path       = "./logs/seller.log"
resources_csv_path  = "/app/resources.csv"
admin_api_key       = "rehearsal-admin-key"
# Pin AFTER your first successful registration — see §5 below.
# onchain_agent_id  = "5955"

[seller.provisioning]
service_url   = "http://seller-provisioning:8081"
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
- `db_path` is the storefront's SQLite location *inside* the container.
  The compose mounts a named volume at
  `/app/src/market_storefront/data/sell-agent`; keeping `db_path` inside
  that directory means state survives `docker compose down`.
- Prices throughout the codebase are **raw token base units**, not whole
  tokens. For USDC (6 decimals), `min_price = "2"` means 0.000002 USDC/hr.
  Use `"2000000"` to mean 2 USDC/hr.
- `[registry.auth]` keys must exactly match the URLs in `[registry] urls`,
  including the scheme and trailing-slash treatment.
- `admin_api_key` must match the `STOREFRONT_ADMIN_KEY` env var you set
  for the compose stack (see §4) — the provisioning service uses it to
  call back on lease expiry.

## 3. resources.csv

This is what the seller offers. One row = one slice the storefront can
sell. The compose mounts whatever file you put at `./resources.csv` (or
the path in `SELLER_RESOURCES_CSV`) into the container at `/app/resources.csv`.

A starter with a few example rows is in the tree at
[`storefront/src/market_storefront/data/resources.sample.csv`](../storefront/src/market_storefront/data/resources.sample.csv);
copy it and trim to what you actually want to sell. Minimal row:

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

## 4. The stack

[`compose/seller.yml`](../compose/seller.yml) bundles the three seller
services. It expects three operator-provided files next to where you run
`docker compose` from, all overridable via env:

| File | Default path | Env override |
|---|---|---|
| Seller TOML | `./config.seller.toml` | `SELLER_CONFIG_PATH` |
| Inventory CSV | `./resources.csv` | `SELLER_RESOURCES_CSV` |
| KVM-host SSH key | `./keys/id_ed25519` | `SELLER_SSH_PRIVKEY` |

And one required env var:

- `STOREFRONT_ADMIN_KEY` — must equal `[seller].admin_api_key` in your TOML.
  The provisioning service uses it to call back to the storefront on lease
  expiry. Compose refuses to start without it.

Create a `.env` file in the directory you'll run compose from so the env
vars persist across invocations:

```bash
# .env
STOREFRONT_ADMIN_KEY=rehearsal-admin-key
PROVISIONING_MODE=http       # or "mock" for a dry run before wiring up KVM
```

The compose itself is registry-agnostic. Two options for the indexer:

- **Use an external indexer** — point `[registry] urls` in your TOML at
  the URL someone else operates. Nothing else to set up here.
- **Run your own private indexer** — see Addendum A; bring it up via
  `docker run` or in your own sibling compose, then point your TOML at
  it.

## 5. Bring it up, register, publish

```bash
docker compose -f compose/seller.yml up -d
docker compose -f compose/seller.yml logs -f seller-agent
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
docker compose -f compose/seller.yml exec seller-agent \
  market-storefront publish --inventory /app/resources.csv
```

The `publish` CLI signs `create_listing` requests with the seller's
private key from config and POSTs to the storefront, which then fans out
to every URL in `[registry] urls`. Successful output:

```
✓ compute-bs-001 → listing f0ba3664-… (status: created)
```

## 6. Verify

```bash
# Storefront returns the listing directly
curl -s http://<HOST>:8001/api/v1/listings | jq '.listings[]'

# Agent card is discoverable on chain → off chain
curl -s http://<HOST>:8001/.well-known/agent-card.json | jq

# (If you're running your own indexer) listing also reached the indexer
curl -sH "Authorization: Bearer <api_key>" \
  http://<INDEXER_HOST>:8080/agents/<onchain_agent_id>/listings | jq '.listings[]'
```

At this point a buyer somewhere else can `market buy --gpu-model H200`
and (in mock mode) get back simulated VM credentials. Real KVM
provisioning is one more step.

## 7. Switching to live KVM provisioning

Mock mode validates the storefront ↔ chain ↔ registry surface without
touching libvirt. To actually create a VM on real hardware:

1. **Set `PROVISIONING_MODE=http` in `.env`** (the default) and make sure
   your TOML's `[seller.provisioning] mode = "http"` agrees. The
   ARKHAI_PROVISIONING_MODE env wins if they disagree.

2. **Generate a dedicated SSH keypair, install the pubkey on the KVM host,
   put the privkey at `./keys/id_ed25519`** (or set `SELLER_SSH_PRIVKEY`
   to point elsewhere). The bundled ansible inventory points
   `ansible_ssh_private_key_file=~/.ssh/id_ed25519`, which inside the
   container expands to `/home/appuser/.ssh/id_ed25519` — and that's
   where the compose mounts your privkey.

   ```bash
   ssh-keygen -t ed25519 -N "" -f ./keys/id_ed25519
   ssh-copy-id -i ./keys/id_ed25519 ubuntu@<KVM_HOST>
   chmod 600 ./keys/id_ed25519
   ```

3. **Make sure `attribute.vm_host` in `resources.csv` matches an inventory
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

4. **Host-side prerequisites:** the ansible user (default `ubuntu`) needs
   passwordless sudo (`sudo -n true && echo ok`), must be in the
   `libvirt` group, and `libvirtd` must be running. The playbook handles
   the rest (cloud-init, virt-install, iptables DNAT for port-forwarding
   the VM's SSH port to the host's public IP).

To verify the provisioning container can reach the host:

```bash
docker compose -f compose/seller.yml exec seller-provisioning ansible \
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
- **`STOREFRONT_ADMIN_KEY` differs from `[seller].admin_api_key`** = lease
  expiry callbacks from the provisioning service get rejected 403, leases
  never transition to `released`, resources stay locked.
- **`resources.csv` `vm_host` set to an inventory alias the indexer or
  provisioning DB doesn't know about** = your listing won't be reachable
  and settle will fail with "host not found". Match the alias exactly.
- **`resources.csv` `token` column must be a 0x ERC-20 address** —
  symbol shorthand ("USDC") is rejected at import time. Decimals are
  resolved on chain from `[chain].rpc_url`, so make sure that's set
  and reachable.
- **`agent_id` with a dash** = rejected. Python identifiers only.
- **`ARKHAI_PROVISIONING_MODE` env on the storefront overrides the TOML's
  `mode`.** Easy to forget and end up in mock mode when you wanted live.
  Cleanest is to drop the env and let the TOML drive it, or set both to
  the same value.

---

## Addendum A: Deploying your own private indexer registry

`compose/seller.yml` is registry-agnostic. Reasons to run your own indexer
rather than rely on a shared one:

- **Privacy / curation** — you control who can query, who can publish.
- **No rate limits** — public indexers throttle.
- **Custom `filter-spec.yaml`** — vocabulary for `gpu_model`, `region`,
  etc. is per-indexer.
- **You're testing alone** and don't need fanout.

### Run it alongside your seller

The simplest setup is a sibling compose file (call it `compose.registry.yml`)
in the same directory, sharing a network with `compose/seller.yml`:

```yaml
# compose.registry.yml
services:
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
    networks:
      - seller
    restart: unless-stopped

networks:
  seller:
    external: true
    name: ${COMPOSE_PROJECT_NAME:-deploy}_seller
```

Then bring both up together:

```bash
docker compose -f compose/seller.yml -f compose.registry.yml up -d
```

In your seller TOML, `[registry] urls = ["http://registry:8080"]` since
they share the `seller` network — the service name resolves inside the
compose stack.

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
