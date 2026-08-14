# Bare-metal seller quickstart

How to bring up a bare-metal storefront: publish whole-machine SSH access
listings, grant a buyer SSH access after settlement, and reclaim that access
when the lease ends.

The operator model is one storefront per domain. To sell VM slices and
bare-metal access for the same physical host, run a VM storefront and a
bare-metal storefront against the same provisioning/site authority. Use the
same `attribute.physical_host_id` in both storefront inventories so shared
host accounting can prevent double selling.

For VM slices, see [`seller-quickstart.md`](./seller-quickstart.md). To run
your own listing registry instead of pointing at an existing one, see
[`indexer-quickstart.md`](./indexer-quickstart.md).

> Transitional packaging note: the bare-metal domain schema lives in
> `domains/bare_metal`, while the current runnable provisioning/site authority
> still lives under `provisioning/compute/service`. Until the storefront
> package split is complete, some compose service names and commands still use
> the VM seller image.

## Prerequisites

- Linux host with Docker + `docker compose` v2.
- A canonical public marketplace identity and matching signer credential
  injected through `ARKHAI_IDENTITY_CREDENTIAL`.
- A wallet on the EVM chain you'll operate on, funded with gas plus whatever
  ERC-20 you'll accept as payment. The examples use Base Sepolia + USDC at
  `0x036CbD53842c5426634e7929541eC2318f3dCF7e`.
- An RPC URL for that chain.
- A listing registry URL + write token if the registry gates writes.
- A physical machine that the provisioning service can reach over SSH.
- An SSH keypair for the provisioning container, with the public key installed
  on each bare-metal node and passwordless sudo enabled for the Ansible user.

## 1. Get the code and build

```bash
git clone https://github.com/arkhai-io/simple-compute-market.git
cd simple-compute-market
make build-seller
```

`build-seller` currently builds the shared seller images used by the
transitional VM and bare-metal paths.

## 2. Configure

The storefront reads `/etc/arkhai/storefront.toml` inside the container,
which the compose mounts from `./config.seller.toml`:

```toml
agent_id         = "bare_metal_seller_one"

port             = 8001
base_url         = "http://<YOUR_PUBLIC_IP>:8001/"

db_path          = "./src/market_storefront/data/storefront/agent.db"
log_file_path    = "./logs/seller.log"

[identity.principal]
scheme = "ed25519"
identifier = "<unpadded-base64url-public-key>"

[wallet]
address = "0x<YOUR_SELLER_ADDRESS>"
# Supply private_key through the deployment Secret overlay.
ssh_public_key = "ssh-ed25519 AAAA...placeholder seller@host"

[chains.base_sepolia]
chain_id = 84532
rpc_url  = "https://sepolia.base.org"
alkahest_address_config_path = "/path/to/alkahest.json"

[registry]
urls = ["http://34.41.205.175/registry"]

[registry.auth]
# Supply any write token through the deployment Secret overlay. Its key must
# match the registry URL exactly.

[provisioning]
service_url = "http://seller-provisioning:8081"
mode        = "http"

[Settlement]
schema_version = 1
priority = ["alkahest.v1"]

[Settlement.alkahest]
enabled = true
address_config_path = "/path/to/alkahest.json"

[pricing]
default_min_price = "10"                # negotiation floor only
default_max_duration_seconds = 86400
```

For co-selling with a VM storefront, use a distinct `agent_id`, `base_url`,
port, database, and canonical marketplace principal for the bare-metal
storefront. Both storefronts can point at the same provisioning service.

## 3. resources.csv

Use one `resources.csv` row per whole machine:

```csv
resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host,attribute.physical_host_id,attribute.allocation_mode,attribute.machine_id,attribute.vcpu_count,attribute.ram_gb,attribute.disk_gb,attribute.virtualization_type,settlements
whole-host-001,compute.gpu,H200,count,8,available,10,,86400,H200,99.0,"California, US",,host-ca-h200-01,exclusive,bm-host-ca-h200-01,192,2048,20000,bare_metal,"[{""mechanism"":""alkahest.v1"",""asset"":""0x036CbD53842c5426634e7929541eC2318f3dCF7e"",""rate"":""10"",""per"":""hour"",""mechanism_input"":{""chain"":""base_sepolia"",""escrow_kind"":""erc20_escrow_obligation_default""}}]"
```

Important fields:

- `attribute.allocation_mode = exclusive` marks the row as a whole-host
  listing candidate.
- `attribute.physical_host_id` is the stable physical identity used for
  cross-domain accounting. VM slice rows for the same host must use the same
  value in the VM storefront inventory.
- `attribute.machine_id` is the provisioning executor's bare-metal node alias.
  It must match `[bare_metal_nodes]` in the provisioning inventory. If omitted,
  `resource_id` is used.
- `attribute.vm_host` is for VM slices; leave it empty in bare-metal rows.
- `value` is the total units on the physical host. For GPU hosts, this is
  normally the total GPU count.

## 4. Add the bare-metal inventory group

Edit the provisioning inventory and add each bare-metal node under
`[bare_metal_nodes]`:

```bash
cd domains/vms/provisioning/iac/ansible/inventory
cp hosts.example hosts
# edit hosts with your real bare-metal node(s)
```

```ini
[bare_metal_nodes]
bm-host-ca-h200-01  ansible_host=10.0.0.25  public_host=203.0.113.25  ansible_user=ubuntu  ansible_ssh_private_key_file=~/.ssh/id_ed25519
```

The alias (`bm-host-ca-h200-01`) must match `attribute.machine_id`.
`ansible_host` is how the provisioning service reaches the node.
`public_host` is optional; set it when buyers should SSH to a different
address than the one Ansible uses. Rebuild after editing the baked inventory:

```bash
make build-seller
```

## 5. Choose reclaim behavior

Bare-metal grant installs the buyer's SSH public key for a tenant account.
On release, the provisioning service runs `node_reclaim_access` using one
of these policies:

- `remove_lease_key` removes only the SSH key recorded for the lease.
- `lock_user` removes the lease key and locks the tenant account.
- `delete_user` deletes the tenant account and home directory.

The default is `remove_lease_key`. Override with provisioning config:

```yaml
bare_metal_reclaim_policy: "lock_user"
```

or with an environment variable:

```bash
PROVISIONING_BARE_METAL_RECLAIM_POLICY=lock_user
```

Use `delete_user` only for machines where tenant home directories are
expected to be disposable.

## 6. Bring it up

```bash
SELLER_CONFIG_PATH="$PWD/config.seller.toml" \
SELLER_RESOURCES_CSV="$PWD/resources.csv" \
SELLER_SSH_PRIVKEY="$PWD/keys/id_ed25519" \
docker compose -f compose/seller.yml -f compose/seller.live.yml up -d
```

For co-selling, run the VM and bare-metal storefronts as separate deployments
with separate configs and public ports, while pointing both at the same
provisioning/site authority.

## 7. Validate the live node

Before publishing, check that the provisioning container can reach the
bare-metal node:

```bash
docker compose -f compose/seller.yml -f compose/seller.live.yml exec \
  seller-provisioning ansible \
  -i /opt/domains/vms/provisioning/iac/ansible/inventory/hosts \
  bm-host-ca-h200-01 -m ping
```

Then verify the host is registered and enabled in the provisioning service:

```bash
docker compose -f compose/seller.yml -f compose/seller.live.yml exec \
  seller-provisioning curl -s \
  -H "X-Admin-Key: <admin_api_key>" \
  http://localhost:8081/api/v1/hosts/bm-host-ca-h200-01 | jq .
```

Bare-metal grant/reclaim refuses to queue work for a missing or disabled
machine.

## 8. Publish and inspect

```bash
docker compose -f compose/seller.yml exec seller-storefront \
  market-storefront publish --inventory /app/resources.csv
```

Bare-metal listing payloads have `kind = "bare_metal.v1"` and include
`machine_id`, `physical_host_id`, `access_method = "ssh"`, and the advertised
duration/price constraints. Inspect local listings:

```bash
curl -s http://<YOUR_PUBLIC_IP>:8001/api/v1/listings \
  | jq '.listings[] | select(.offer_resource.kind == "bare_metal.v1")'
```

## Operational notes

- Do not use the same machine as a general-purpose operator login and a
  bare-metal tenant target unless the tenant account is tightly isolated.
- `remove_lease_key` is safest for preserving tenant data; `lock_user` and
  `delete_user` are stronger cleanup actions with more operational blast
  radius.
- Keep `physical_host_id` stable across CSV edits. Changing it breaks
  cross-domain accounting for existing rows.
- Keep `machine_id` stable while leases are active. It is the executor target
  used for grant/reclaim.
- Re-run publish after importing resource or capacity changes so stale listings
  close and newly available listings reopen.

## Common pitfalls

- **`attribute.machine_id` must match `[bare_metal_nodes]`.** Wrong alias =
  grant/reclaim fails before Ansible runs.
- **Bare-metal and VM rows for one physical host must share
  `attribute.physical_host_id`.** Otherwise the site ledger cannot prevent
  cross-mode double selling.
- **Do not put VM slice and bare-metal rows in the same storefront inventory
  once the storefront split is complete.** Run one storefront per domain and
  let the shared site authority coordinate host accounting.
- **`agent_id` must be a Python identifier** — no dashes.
