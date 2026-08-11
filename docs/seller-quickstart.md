# VM seller quickstart

How to bring up a compute storefront: publish listings (signed with
your wallet key), and (optionally) provision real KVM VMs to buyers.

For the buyer side see [`buyer-quickstart.md`](./buyer-quickstart.md).
To run your own listing registry instead of pointing at an existing one,
see [`indexer-quickstart.md`](./indexer-quickstart.md). To expose VMs
via wildcard subdomains instead of direct port-forward NAT, see
[`seller-frp-setup.md`](./seller-frp-setup.md). To sell whole-machine
SSH access instead of VM slices, see
[`bare-metal-seller-quickstart.md`](./bare-metal-seller-quickstart.md).
To sell request quota for an OpenAI-compatible vLLM server instead, see the
[`vLLM API-credits cookbook`](./cookbooks/vllm-apicredits-seller.md).

## Prerequisites

- Linux host with Docker + `docker compose` v2.
- A wallet on the EVM chain you'll operate on, funded with gas plus
  whatever ERC-20 you'll accept as payment. The examples in this guide
  use Base Sepolia + USDC at `0x036CbD53842c5426634e7929541eC2318f3dCF7e`
  (test funds from [faucet.circle.com](https://faucet.circle.com)), but
  any EVM chain with Alkahest contracts deployed works.
- An RPC URL for that chain.
- A listing registry URL + (if private) bearer token to publish to.
- **Live provisioning only** — KVM-capable host: `egrep -c "(vmx|svm)"
  /proc/cpuinfo > 0`, `libvirtd` running, your ansible user has
  passwordless sudo and is in the `libvirt` group.

## 1. Get the code and build

```bash
git clone https://github.com/arkhai-io/simple-compute-market.git
cd simple-compute-market
make build-seller
```

`build-seller` builds the two images you need (`arkhai:storefront`,
`arkhai:compute-provisioning`) and the wheels they consume — ~3 minutes on a
warm machine. Build on Linux; macOS hits a known cross-platform
`uv sync` issue.

## 2. Configure

The storefront reads `/etc/arkhai/storefront.toml` inside the container,
which the compose mounts from `./config.seller.toml` (override with
`SELLER_CONFIG_PATH=$PWD/your-path.toml`).

```toml
agent_id         = "seller_one"          # Python identifier; no dashes

port             = 8001
base_url         = "http://<YOUR_PUBLIC_IP>:8001/"

db_path          = "./src/market_storefront/data/storefront/agent.db"
log_file_path    = "./logs/seller.log"
admin_api_key    = "<choose-a-secret>"   # storefront credential for configured provisioning sites

[wallet]
private_key    = "0x<YOUR_SELLER_PRIVATE_KEY>"
# placeholder; not used in buyer-driven flows
ssh_public_key = "ssh-ed25519 AAAA...placeholder seller@host"

[chains.base_sepolia]
chain_id = 84532
rpc_url  = "https://sepolia.base.org"   # public RPC; or your own provider

[registry]
# The Arkhai public listing registry (preprod, Base Sepolia listings):
urls = ["http://34.41.205.175/registry"]
# Or point at any other listing registry, e.g. a self-hosted one:
# urls = ["http://<REGISTRY_HOST>:8080"]

[registry.auth]
# Required when the listing registry gates writes (REGISTRY_REQUIRE_WRITE_API_KEY=true);
# the key must be write-scoped. The Arkhai public listing registry gates writes —
# request a write key from the operator, or run your own listing registry.
# Keys must exactly match the URLs in [registry] urls (scheme, host,
# port, trailing slash).
"http://34.41.205.175/registry" = "<your-write-token>"

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
[`domains/vms/storefront/src/market_storefront/settings.toml`](../domains/vms/storefront/src/market_storefront/settings.toml).

## 3. Commercial listing input and capacity identity

Provisioning Host, Resource Pool, and capacity tables are authoritative for
physical inventory. The storefront loads trusted `site_resource_pools` and
`site_capacity_buckets` projections from each configured site. Commercial
listing input may still be supplied through `resources.csv`, but each VM row
must reference a projected `pool_id` or `resource_id` and declare its sellable
shape (`gpu_count`, `vcpu_count`, `ram_gb`, and `disk_gb`). Do not publish
`vm_host`, authority URLs, API keys, or internal capacity-bucket IDs.

```csv
resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.pool_id,attribute.gpu_model,attribute.region,attribute.gpu_count,attribute.vcpu_count,attribute.ram_gb,attribute.disk_gb
listing-slice-001,compute.gpu,H200,count,1,available,2,0x036CbD53842c5426634e7929541eC2318f3dCF7e,86400,default,H200,"California, US",1,8,32,100
```

`min_price` remains a human whole-token hourly rate and `token` is the ERC-20
contract. Capacity admission, physical selection, prepared execution, and
teardown are owned by the selected provisioning site rather than this CSV.

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

There is no registration step: your identity is the wallet. Every
publish is EIP-191-signed, and the listing registry creates your publisher
record from the signature the first time you publish.

## 5. Publish

```bash
docker compose -f compose/seller.yml exec seller-storefront \
  market-storefront publish --inventory /app/resources.csv
```

Verify directly against the storefront and the listing registry:

```bash
curl -s http://<YOUR_PUBLIC_IP>:8001/api/v1/listings | jq '.listings[]'

# Registry: filter listings by your publishing wallet address:
curl -s "http://34.41.205.175/registry/listings?publisher=<YOUR_WALLET_ADDRESS>" \
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
   cd domains/vms/provisioning/iac/ansible/inventory
   cp hosts.example hosts
   # edit hosts with your real KVM host(s)
   ```

   The provisioning service imports these aliases into its authoritative Host
   and Resource Pool tables. Storefront listings reference trusted projected
   `pool_id`/`resource_id`; they do not carry `vm_host`. Each host line's
   `ansible_host` is how the provisioning service reaches the host over SSH.
   If buyers reach that host
   on a **different** address than the provisioner does (e.g. the provisioner
   is on a private/overlay network but the VM port-forwards are exposed on a
   public IP), add a `public_host=` var — that's the address put in the
   tenant's connection details:

   ```ini
   [kvm_hosts]
   kvm1  ansible_host=10.0.0.5  public_host=203.0.113.9  ansible_user=ubuntu  ansible_ssh_private_key_file=~/.ssh/id_ed25519
   ```

   Without `public_host`, the connection details fall back to `ansible_host`.
   The provisioning image bakes the inventory in at build time — rebuild
   after edits:

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
     -i /opt/domains/vms/provisioning/iac/ansible/inventory/hosts \
     <your_host_alias> -m ping
   ```

   `SUCCESS / ping: pong` means the next buy will actually create a VM.

## Optional hosted fiat publication

Hosted settlement is disabled by default. Configure the storefront's
`[hosted_settlement]` consumer trust/API pin plus an operator-owned condition
profile, resolver ID, connected-account reference, lowercase currency, and
positive integer minor-unit rate. Publication preflights the account and
condition capability. A failed hosted preflight suppresses only the fiat
option and continues serving valid Alkahest listings.

The storefront never receives Stripe credentials or provider IDs and never
stores Checkout or account-link URLs. It persists one opaque settlement
reference and drives funded VM fulfillment, condition check/collect, and
eligible reclaim through the shared settlement worker. Stripe funds remain
platform-custodied by the separately operated authority; an EAS condition
anchor is audit/predicate evidence, not custody.

## Common pitfalls

- **Don't restart without pinning `onchain_agent_id`** — every fresh
  start that finds an empty pin re-registers (gas cost).
- **`[registry.auth]` keys must match `[registry] urls` exactly** —
  scheme, host, port, no trailing slash.
- **`admin_api_key` empty or missing** — authenticated reservation,
  scheduling, result, and teardown calls to the configured site fail closed.
  Lease expiry is provisioning-owned and does not depend on a storefront callback.
- **A globally paused storefront rejects every new negotiation with
  `503 {"reason":"global"}`.** Global pause is durably persisted and separate
  from per-listing pause. Resume it through the authenticated
  `POST /admin/resume` endpoint before accepting buyers.
- **The resource importer and storefront must use the same SQLite path.**
  A mismatch leaves the running storefront with no resources and causes
  `409 no_matching_inventory`. Check `resource_count` in
  `GET /api/v1/system/status`; zero usually means the importer wrote a
  different database. Prefer an explicit importer `--db-path` or
  `STOREFRONT_DB_PATH`.
- **`resources.csv` prices are human / whole-token units.** Use
  fractional strings (`"0.50"`) for sub-token rates. `0` is a literal
  free offering.
- **Do not publish `vm_host`.** Listings use trusted projected `pool_id` or
  `resource_id`; physical host selection is provisioning-owned. The admin
  settle evaluate endpoint validates canonical schedule/begin requests without
  reserving or probing a host.
- **When co-selling VM slices and bare metal, configure one stable physical
  host identity in authoritative provisioning inventory.** Domain projections
  preserve that identity so the site ledger prevents cross-mode double selling.
- **`agent_id` must be a Python identifier** — no dashes.
