# Seller quickstart

How to bring up a compute storefront: register on-chain, publish a
listing, and (optionally) provision real KVM VMs to buyers.

For the buyer side see [`buyer-quickstart.md`](./buyer-quickstart.md).
To run your own indexer registry instead of pointing at an existing one,
see [`indexer-quickstart.md`](./indexer-quickstart.md). To expose VMs
via wildcard subdomains instead of direct port-forward NAT, see
[`seller-frp-setup.md`](./seller-frp-setup.md).

## Prerequisites

- Linux host with Docker + `docker compose` v2.
- A wallet on the EVM chain you'll operate on, funded with gas plus
  whatever ERC-20 you'll accept as payment. The examples in this guide
  use Base Sepolia + USDC at `0x036CbD53842c5426634e7929541eC2318f3dCF7e`
  (test funds from [faucet.circle.com](https://faucet.circle.com)), but
  any EVM chain with ERC-8004 + Alkahest contracts deployed works.
- An RPC URL for that chain.
- An indexer URL + (if private) bearer token to publish to.
- **Live provisioning only** — KVM-capable host: `egrep -c "(vmx|svm)"
  /proc/cpuinfo > 0`, `libvirtd` running, your ansible user has
  passwordless sudo and is in the `libvirt` group.

## 1. Get the code and build

```bash
git clone --recurse-submodules https://github.com/arkhai-io/simple-compute-market.git
cd simple-compute-market
make build-seller
```

`build-seller` builds the two images you need (`arkhai:storefront`,
`arkhai:provisioning`) and the wheels they consume — ~3 minutes on a
warm machine. Build on Linux; macOS hits a known cross-platform
`uv sync` issue.

## 2. Configure

The storefront reads `/etc/arkhai/storefront.toml` inside the container,
which the compose mounts from `./config.seller.toml` (override with
`SELLER_CONFIG_PATH=$PWD/your-path.toml`).

```toml
agent_id         = "seller_one"          # Python identifier; no dashes
# onchain_agent_id = "<N>"                # pin after first registration (§4)

port             = 8001
base_url         = "http://<YOUR_PUBLIC_IP>:8001/"

db_path          = "./src/market_storefront/data/storefront/agent.db"
log_file_path    = "./logs/seller.log"
admin_api_key    = "<choose-a-secret>"   # used by the provisioning service for lease-expiry callbacks

[wallet]
private_key    = "0x<YOUR_SELLER_PRIVATE_KEY>"
# placeholder; not used in buyer-driven flows
ssh_public_key = "ssh-ed25519 AAAA...placeholder seller@host"

[chain]
chain_id = 84532
rpc_url  = "https://base-sepolia.infura.io/v3/<YOUR_KEY>"

[registry]
urls = ["http://<INDEXER_HOST>:8080"]

[registry.auth]
# Required when the indexer runs with REGISTRY_REQUIRE_API_KEY=true.
# Keys must exactly match the URLs in [registry] urls (scheme, host,
# port, trailing slash).
"http://<INDEXER_HOST>:8080" = "<your-token>"

[provisioning]
service_url = "http://seller-provisioning:8081"
mode        = "http"                     # "mock" for a dry run

[negotiation]
# Ordered policy chain run per round. Guards short-circuit
# (`reject`/`exit`); the terminal policy (`bisection` here; `rl` for the
# trained pufferlib checkpoint — requires torch) always returns
# counter/accept/exit. See docs/configuration.md for the full list of
# bundled policies + how to register custom ones.
policies = ["has_matching_inventory_guard", "escrow_shape_guard", "bisection"]

[pricing]
# Human / whole-token units, per hour. The publish CLI scales by the
# token's on-chain decimals — "2" with 6-decimal USDC = $2/hr.
default_min_price            = "2"
default_token_address        = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
default_max_duration_seconds = 86400
```

The full schema is at
[`storefront/src/market_storefront/settings.toml`](../storefront/src/market_storefront/settings.toml).

## 3. resources.csv

What you offer for sale. One row per slice. The compose mounts
`./resources.csv` (override with `SELLER_RESOURCES_CSV`) at
`/app/resources.csv`; the storefront auto-seeds from it on first start.

```csv
resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host
slice-001,compute.gpu,H200,count,1,available,2,0x036CbD53842c5426634e7929541eC2318f3dCF7e,86400,H200,99.0,"California, US",<vm_host_alias>
```

- `min_price` — human / whole-token units, scaled by token decimals on
  publish (`2` = $2/hr with USDC).
- `token` — 0x ERC-20 contract address. The storefront eth-calls
  `symbol()` and `decimals()` and caches the result. Omit to use
  `[pricing].default_token_address`.
- `attribute.vm_host` — must match a host alias in the provisioning
  service's ansible inventory (§6). For mock mode any string works.

A larger sample is at
[`storefront/src/market_storefront/data/resources.sample.csv`](../storefront/src/market_storefront/data/resources.sample.csv).

## 4. Bring it up

`compose/seller.yml` bundles the storefront and provisioning services.
For mock mode it needs two operator-provided files: `config.seller.toml`
and `resources.csv`. Pass absolute paths via env to avoid docker compose's
relative-path-resolves-from-the-compose-file gotcha:

```bash
SELLER_CONFIG_PATH="$PWD/config.seller.toml" \
SELLER_RESOURCES_CSV="$PWD/resources.csv" \
docker compose -f compose/seller.yml up -d

docker compose -f compose/seller.yml logs -f seller-storefront
```

The `admin_api_key` you set in §2 is the only secret — the
provisioning service reads it from the same mounted TOML, so you
don't repeat it anywhere else. Likewise `[provisioning].mode` in
the TOML drives mock-vs-live; no separate env knob.

Wait for `Started heartbeat for eip155:...:<N>` — that's your numeric
agent ID. **Pin it now** to skip re-registering on every restart:

```toml
onchain_agent_id = "<N>"
```

## 5. Publish

```bash
docker compose -f compose/seller.yml exec seller-storefront \
  market-storefront publish --inventory /app/resources.csv
```

Verify directly against the storefront and the indexer:

```bash
curl -s http://<YOUR_PUBLIC_IP>:8001/api/v1/listings | jq '.listings[]'

# Indexer requires the full canonical agent ID, URL-encoded:
curl -sH "Authorization: Bearer <your-token>" \
  "http://<INDEXER_HOST>:8080/agents/eip155%3A84532%3A0x8004A818BFB912233c491871b3d84c89A494BD9e%3A<N>/listings" \
  | jq '.items[]'
```

A buyer can now `market buy --gpu-model H200` and (in mock mode) get
simulated VM credentials.

## 6. Live KVM provisioning

Mock mode validates the storefront ↔ chain ↔ registry surface without
touching libvirt. To create real VMs:

1. Set `[provisioning].mode = "http"` in the TOML (the default for fresh
   configs).

2. Generate an SSH keypair the provisioning container will use to reach
   your KVM hosts, install the pubkey on each host, and put the privkey
   at `./keys/id_ed25519`:

   ```bash
   ssh-keygen -t ed25519 -N "" -f ./keys/id_ed25519
   ssh-copy-id -i ./keys/id_ed25519 <ansible_user>@<kvm_host>
   chmod 600 ./keys/id_ed25519
   ```

3. Customize your KVM inventory:

   ```bash
   cd compute-provisioning-iac/ansible/inventory
   cp hosts.example hosts
   # edit hosts with your real KVM host(s)
   ```

   `attribute.vm_host` in `resources.csv` must match an alias under
   `[kvm_hosts]` in this file. The provisioning image bakes the
   inventory in at build time — rebuild after edits:

   ```bash
   make build-seller
   ```

4. Bring the stack up with the live overlay — adds the SSH-key
   bind-mount that mock mode doesn't need:

   ```bash
   SELLER_CONFIG_PATH="$PWD/config.seller.toml" \
   SELLER_RESOURCES_CSV="$PWD/resources.csv" \
   SELLER_SSH_PRIVKEY="$PWD/keys/id_ed25519" \
   docker compose -f compose/seller.yml -f compose/seller.live.yml \
     up -d --force-recreate seller-provisioning
   ```

5. KVM host prerequisites: ansible user has passwordless sudo
   (`sudo -n true && echo ok`), is in the `libvirt` group, and
   `libvirtd` is running. The playbook handles cloud-init, virt-install,
   and SSH port-forward NAT.

6. Smoke-test reachability:

   ```bash
   docker compose -f compose/seller.yml -f compose/seller.live.yml exec \
     seller-provisioning ansible \
     -i /opt/compute-provisioning-iac/ansible/inventory/hosts \
     <your_host_alias> -m ping
   ```

   `SUCCESS / ping: pong` means the next buy will actually create a VM.

## Common pitfalls

- **Don't restart without pinning `onchain_agent_id`** — every fresh
  start that finds an empty pin re-registers (gas cost).
- **`[registry.auth]` keys must match `[registry] urls` exactly** —
  scheme, host, port, no trailing slash.
- **`admin_api_key` empty or missing** — provisioning service can't
  call back on lease expiry, leases never release.
- **`resources.csv` prices are human / whole-token units.** Use
  fractional strings (`"0.50"`) for sub-token rates. `0` is a literal
  free offering.
- **`attribute.vm_host` must match an inventory alias.** Wrong alias =
  settle fails with "host not found".
- **`agent_id` must be a Python identifier** — no dashes.
