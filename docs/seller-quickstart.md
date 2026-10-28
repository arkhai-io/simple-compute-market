# VM seller quickstart

How to bring up a compute storefront, publish typed settlement options under a
canonical marketplace identity, and optionally provision real KVM VMs.

For the buyer side see [`buyer-quickstart.md`](./buyer-quickstart.md).
To run your own listing registry instead of pointing at an existing one,
see [`indexer-quickstart.md`](./indexer-quickstart.md). To expose VMs
through a tunnel relay when your host has no inbound route, see
[`seller-frp-setup.md`](./seller-frp-setup.md). To sell whole-machine
SSH access instead of VM slices, see
[`bare-metal-seller-quickstart.md`](./bare-metal-seller-quickstart.md).
To sell request quota for an OpenAI-compatible vLLM server instead, see the
[`vLLM API-credits cookbook`](./cookbooks/vllm-apicredits-seller.md).

## Supported settlement methods

A VM storefront publishes Alkahest settlement options. See the
[`buyer quickstart`](./buyer-quickstart.md#supported-settlement-methods) for
buyer-side escrow requirements.

## Prerequisites

- A canonical public marketplace identity and matching signing material
  injected through `ARKHAI_IDENTITY_CREDENTIAL`.
- A listing registry URL, authority principal pin, and any write-scoped bearer
  token required to publish.
- For Alkahest settlement only: an EVM wallet funded with gas and the accepted
  token, an RPC URL, and the deployed Alkahest address file.
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
agent_id = "seller_one"                  # Python identifier; no dashes
port = 8001
base_url = "http://<YOUR_PUBLIC_IP>:8001/"
db_path = "./src/market_storefront/data/storefront/agent.db"
log_file_path = "./logs/seller.log"

[identity.principal]
scheme = "ed25519"
identifier = "<unpadded-base64url-public-key>"

[provisioning]
service_url = "http://seller-provisioning:8081"

[capacity.sites]
# Each site the storefront sells from, by stable ID, and its authority's origin.
default = "http://seller-provisioning:8081"

# The one service peer the site is bound to: the provisioning authority's
# public principal. Its responses and callbacks are verified against it.
[Identity.service_peers.provisioning_default]
role = "service"
site_id = "default"
principals = [{ scheme = "ed25519", identifier = "<provisioning-authority-public-key>" }]

[registry]
# The listing registry to publish to (a placeholder: use the URL its operator publishes):
urls = ["https://registry.example.com"]
# Or point at any other listing registry, e.g. a self-hosted one:
# urls = ["http://<REGISTRY_HOST>:8080"]

# Required: one pin per registry URL, keyed by the string in `urls`,
# naming the registry's authority and the principal its responses are signed
# with. A storefront refuses to start with a registry it cannot verify. Replace
# both placeholders with the values the registry's operator publishes, and
# re-key the table if you change `urls`.
[registry.authorities."https://registry.example.com"]
authority  = "<registry-authority>"
principals = [{ scheme = "eip191", identifier = "<registry-principal>" }]

[registry.auth]
# Supply any write token through the deployment Secret overlay. Its key must
# match the registry URL exactly.

[Settlement]
schema_version = 1
priority = ["alkahest.v1"]

[Settlement.alkahest]
enabled = true
address_config_path = "/path/to/alkahest.json"

[wallet]
address = "0x<YOUR_SELLER_ADDRESS>"
# Supply private_key through the deployment Secret overlay.

[chains.base_sepolia]
chain_id = 84532
rpc_url = "https://sepolia.base.org"

[negotiation]
policies = ["has_matching_inventory_guard", "escrow_shape_guard", "bisection"]

[pricing]
# Complete option-construction clauses. Each mechanism has its own asset/rate.
settlements = [
  { mechanism = "alkahest.v1", asset = "0x036CbD53842c5426634e7929541eC2318f3dCF7e", rate = "2", per = "hour", mechanism_input = { chain = "base_sepolia", escrow_kind = "erc20_escrow_obligation_default" } },
]
default_min_price = "2"                 # negotiation floor only
default_max_duration_seconds = 86400
```

The storefront refuses to start, naming each problem, when it cannot publish:
with no registry or a registry without its pin, no enabled settlement mechanism,
or no site, or a site not bound to exactly one service peer.

For payments-only publication, set priority to `["arkhai.payments.v1"]`,
configure `[Settlement.arkhai_payments]`, omit wallet and chains, and publish a
complete clause for each asset and rate you offer:

```toml
[Settlement]
schema_version = 1
priority = ["arkhai.payments.v1"]

[Settlement.arkhai_payments]
enabled = true
service_url = "https://<PAYMENTS_SERVICE>"
service_identity = { scheme = "ed25519", identifier = "<RECEIPT_SIGNING_KEY>" }
fee_bps = 250
dispute_authority = "<DISPUTE_AUTHORITY_ACCOUNT>"
api_key_env = "ARKHAI_PAYMENTS_API_KEY"   # names the variable; the key stays in the environment
livemode = true                          # false against the public test-mode service

[pricing]
settlements = [
  { mechanism = "arkhai.payments.v1", asset = "USD/2", rate = "200", per = "hour", mechanism_input = { payee_account = "<YOUR_PAYEE_ACCOUNT>", asset = "USD/2" } },
]
```

These clauses are the storefront-wide terms. A pool's own `pricing` declaration
at its site, and the storefront's per-pool overrides, take precedence over them;
there is no command-level override, because the storefront republishes on its
own and must reach the same terms every cycle.

The receipt-signing identity, fee policy, and dispute authority are trusted
configuration that both settlement and refunds check against; the API key is
read from the named environment variable and is never written to
configuration.

The full schema is at
[`domains/vms/storefront/src/market_storefront/settings.toml`](../domains/vms/storefront/src/market_storefront/settings.toml).

## 3. Commercial listing input and capacity identity

Capacity declarations are authoritative for what a site sells; a provisioning
Host record is only how the site reaches a machine. The storefront holds no
inventory of its own: it loads trusted `site_resource_pools` and
`site_capacity_buckets` projections from each configured site and derives every
listing from them. A listing names its projected `pool_id`, never a host
identity (`host_id`), an authority URL, an API key, or an internal
capacity-bucket ID.

A listing's commercial terms come from three places, highest first:

- the storefront's own pool override for that site and pool
  (`market-storefront pool-override`), which may state listing shapes,
  settlement clauses, asking rates, `sla`, `max_duration_seconds`, and family
  rates;
- the pool's own `policy_tags`, declared at provisioning: `region`,
  `listing_shapes`, `asking_rates`, `pricing`, and `sla`, which is read only
  when `[pricing].accept_pool_declared_sla` is on;
- the storefront configuration's defaults, such as `[pricing].settlements`.

Region is a physical fact, so only the pool states it; no override does. A
pool that states no region publishes nothing new and leaves the listings it
already published unrefreshed; system status reports it among its site's
`publication_derivation` holds as `pool_region_missing`.
`DEPLOYMENT_AND_CONFIG.md`'s "Storefront listing shapes and pool overrides"
describes each term. Capacity admission, physical selection, prepared
execution, and teardown are owned by the selected provisioning site.

### Declaring capacity

VM pools declare provider `vm.ansible`. Provisioning migrations canonicalize
stored `ansible` routing names while preserving pool configuration and existing
fulfillment state. Use `vm.ansible` in mounted pool documents and operator
requests before starting the upgraded service; the old name is not a runtime
alias.

A fresh site starts with pools from the provisioning service's seed: with no
pool document mounted and no pool stored, startup creates `vm-default`
(`vm.ansible`) and `bare-metal-default` (`bare_metal.ansible`), each backed and
delivering and advertising its own mode. They sell nothing until you declare
capacity into them. A VM pool, seeded or your own, may omit `playbook_path`:
its jobs then run the service's `vm_playbook_path`, fixed into each job when it
is prepared. A mounted pool document replaces the seed, and creates its own
pools before host inventory is imported; no pool name, `default` included, is
required. To start a fresh site with other pools while keeping pools
administrable through the API, point `pool_seed_path` at your own pool
document: under compose, mount the file into `seller-provisioning` and set
`PROVISIONING_POOL_SEED_PATH` to its path in an override file; under Helm, put
the document in the provisioning chart's `configFiles` (for example as
`pool-seed.yaml`) and set `config.pool_seed_path` to
`/app/config/pool-seed.yaml`. An empty `pool_seed_path` starts a fresh site with
no pool. The seed is applied once, to a site storing no pool; a site that
already holds pools is never seeded.

A site sells what its capacity declarations say. A declaration names its Resource
Pool, a `capacity` map of the dimensions it sells (`gpu_count`, `vcpu_count`,
`ram_gb`, …), the categorical `attributes` claims match (`gpu_model`, `region`),
and, when it is delivered through a host, that host's `host_id`. A host that no
declaration names is not published, whatever pool it is placed in: registering
or importing a host declares none of its capacity.

There are two ways to declare, and they describe the same declaration:

- `PUT /api/v1/capacity/resources/{resource_id}` for one declaration.
- A capacity-definitions document, submitted with
  `POST /api/v1/capacity/definitions/import` (add `"validate_only": true` to
  preview the changes), or mounted at startup through the chart's
  `definitions.capacity` value:

  ```yaml
  resources:
    - resource_id: compute-kvm1
      pool_id: vm-default
      resource_type: compute.gpu
      host_id: kvm1
      capacity: {gpu_count: 8, vcpu_count: 192, ram_gb: 2048}
      attributes: {gpu_model: H200, region: "California, US"}
  ```

Every entry replaces the whole declaration it names, so restate everything you
want to keep. Declarations a document does not name are left as they are. Every
declared attribute is published to storefronts. `DEPLOYMENT_AND_CONFIG.md`'s
"Capacity definitions" describes the document's rules in full.

A host's GPU count and model are descriptive and never change what is sold:
editing a host's inventory line leaves its declaration as it is. Change the
declaration instead.

## 4. Bring it up

`compose/seller.yml` bundles the storefront and provisioning services.
For mock mode it needs one operator-provided file, `config.seller.toml`. Pass
an absolute path via env to avoid docker compose's
relative-path-resolves-from-the-compose-file gotcha:

```bash
SELLER_CONFIG_PATH="$PWD/config.seller.toml" \
docker compose -f compose/seller.yml up -d

docker compose -f compose/seller.yml logs -f seller-storefront
```

Keep `admin_api_key`, `ARKHAI_IDENTITY_CREDENTIAL`, and any Alkahest wallet
private key in the deployment's secret boundary rather than a committed
configuration. The storefront has no provisioning mode: whether a deal's
delivery is mocked or live is the provisioning service's to decide.

There is no publisher preregistration step. Every publication is signed by the
configured canonical marketplace principal, and the registry creates the
stable publisher subject on its first valid publication.

## 5. Preview and publish

Legacy settlement configuration and publication pricing require separate,
explicit migrations:

```bash
market-storefront config migrate --scope settlement --check
market-storefront config migrate --scope settlement --write --backup
market-storefront config migrate --scope publication --check
market-storefront config migrate --scope publication --write --backup
```

The storefront then publishes on its own. It derives listings from every
advertisable pool its trusted sites project, publishes them, refreshes open
listings when their terms change, and closes those whose source no longer
supports them. To see what its next publication cycle would do, or to run one
now rather than wait for the timer:

```bash
docker compose -f compose/seller.yml exec seller-storefront \
  market-storefront publish --dry-run
docker compose -f compose/seller.yml exec seller-storefront \
  market-storefront publish
```

`market-storefront publish --abort-all` closes every open listing as the seller.
Publication never reopens a listing its seller closed; resume a listing to re-list
it. The storefront's lifecycle pause (`POST /api/v1/admin/lifecycle/pause`) holds
publication with its other loops without affecting trading, and a cycle can still
be run or previewed while held. Inspect readiness without publishing:

```bash
market-storefront settlement status --json
```

The storefront does not wait for its registry, chain, or site at startup: a
registry it cannot reach marks its system status `degraded`, a chain its Alkahest
probe cannot reach leaves Alkahest unready until a probe reaches it, and a site
it cannot reach holds that site's listings. An Alkahest section that cannot
settle — no trusted oracle for `oracle_gated`, an oracle equal to the seller
wallet, no wallet address or key, no `[Chains]` — leaves Alkahest unready rather
than stopping the storefront; system status's `settlement` names each mechanism's
blockers. `GET /api/v1/system/status` also reports, under `publication_derivation`,
each site's `holds`, `refusals`, and `reports` from the last publication cycle,
each a reason code with the pool it concerns: `pool_region_missing` for a pool
stating no region; `no_settlement_option` for a pool whose configuration rules
out every settlement mechanism its clauses name, whose open listings then close
until an option returns; `settlement_mechanism_unknown` while such a mechanism
only cannot be reached, its open listings held. A site no cycle has derived since
start is absent, and an entry is logged when it first appears and when it clears.

A buyer can now run
`market buy --resource 'gpu_model=H200' --settlement 'mechanism=alkahest.v1'`
and, in mock mode, receive simulated VM credentials.

## 6. Live KVM provisioning

Mock mode validates the storefront ↔ chain ↔ registry surface without
touching libvirt. To create real VMs:

1. Generate an SSH keypair the provisioning container will use to reach
   your KVM hosts, install the pubkey on each host, and put the privkey
   at `./keys/id_ed25519`:

   ```bash
   ssh-keygen -t ed25519 -N "" -f ./keys/id_ed25519
   ssh-copy-id -i ./keys/id_ed25519 <ansible_user>@<ssh_host>
   chmod 600 ./keys/id_ed25519
   ```

2. List the execution hosts the service registers:

   ```bash
   cd domains/vms/provisioning/iac/ansible/inventory
   cp provisioning-hosts.example provisioning-hosts.ini
   # edit provisioning-hosts.ini with your real KVM host(s)
   ```

   The provisioning service registers every host entry in this file as a host,
   whatever section it is listed under. A host line's `pool_id=<id>` places the
   host in that pool, which must exist; an empty `pool_id=` unplaces it; a line
   with no `pool_id` leaves a new host unplaced and an existing host's pool as it
   is. List only execution hosts: relay proxies and other infrastructure you
   manage with the IaC playbooks go in `hosts` in the same directory
   (`cp hosts.example hosts`), which the service is never given. Storefront listings reference trusted projected
   `pool_id`/`resource_id`; they do not carry a `host_id`. Each host line's
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

   `provisioning-hosts.ini` seeds the host registry when the provisioning service starts with
   no hosts registered. Work then runs only against registered hosts, never
   against the file. To add a host to a running deployment, import the file
   again (`POST /api/v1/hosts/import`) or register the host (`POST
   /api/v1/hosts`). A host that is only in the file is refused at dispatch.

   An inventory line's `gpus=` and `gpu_model=` are stored on the host and
   declare nothing: neither applying the inventory nor `POST /api/v1/hosts`
   creates a capacity declaration. Declare each host's capacity yourself, as
   "Declaring capacity" describes, naming the host's `host_id`. A host that
   existed when its site upgraded to declared capacity received a declaration
   derived from its GPUs then (`resource_id` and `host_id` both the host's name,
   `capacity` `{gpu_count: <gpus>}`, `gpu_model` as an attribute, in the host's
   pool); that declaration is an ordinary one, and stays reservable if the code
   is rolled back.
   The provisioning image bakes the inventory in at build time — rebuild
   after edits:

   ```bash
   make build-seller
   ```

3. Bring the stack up with the live overlay — adds the SSH-key
   bind-mount that mock mode doesn't need:

   ```bash
   SELLER_CONFIG_PATH="$PWD/config.seller.toml" \
   SELLER_SSH_PRIVKEY="$PWD/keys/id_ed25519" \
   docker compose -f compose/seller.yml -f compose/seller.live.yml \
     up -d --force-recreate seller-provisioning
   ```

4. KVM host prerequisites: ansible user has passwordless sudo
   (`sudo -n true && echo ok`), is in the `libvirt` group, and
   `libvirtd` is running. The playbook handles cloud-init, virt-install,
   and SSH port-forward NAT.

5. Smoke-test reachability:

   ```bash
   docker compose -f compose/seller.yml -f compose/seller.live.yml exec \
     seller-provisioning ansible \
     -i /opt/domains/vms/provisioning/iac/ansible/inventory/provisioning-hosts.ini \
     <your_host_alias> -m ping
   ```

   `SUCCESS / ping: pong` means the next buy will actually create a VM.


## Upgrading from CSV inventory

Earlier storefronts could hold their own inventory: a resource CSV seeded at
startup (`resources_csv_path`, `resources_csv_inline`, or a file at
`/app/resources.csv`) or imported through
`POST /api/v1/admin/portfolio/resources/import`, with per-row prices drawn from
`[escrow_templates]`. A storefront now reads inventory only from its sites'
provisioning services, and nothing warns when the old source is still
configured: an unmigrated storefront starts, finds no pools, and publishes
nothing. The upgrade is one-way; there is no supported downgrade.

Before upgrading, declare at provisioning everything the CSV described:

1. **Hosts and capacity.** Register each host in the provisioning service's
   host inventory and declare what it sells as capacity, as "Declaring
   capacity" above describes. A CSV row's `attribute.vm_host` names the host,
   and its `value` and `attribute.vcpu_count`, `ram_gb`, and `disk_gb` become
   the declaration's `capacity`.
2. **Pools and their terms.** Put each resource in a pool, and declare the
   pool's `region` in its `policy_tags`, with its `listing_shapes` and
   `asking_rates` where you state them. Region can only be declared there, and
   a pool without it is held until it states one. A
   pool's `sla` hint is read only by a storefront with
   `[pricing].accept_pool_declared_sla` on; otherwise state the SLA as an
   override term.
3. **Storefront terms.** Re-enter, with `market-storefront pool-override set`,
   any pool term the storefront itself supplied. System status on the release
   you are upgrading from lists, under `publication_derivation`, each field a
   pool still took from the storefront's own pool record
   (`legacy_overrides_in_effect`): `sla`, `max_duration_seconds`, and pricing
   left there fall through to the pool's hint and then to the configured
   default once you upgrade. A per-row `accepted_escrows` value has no
   equivalent; state the clauses it priced as a `settlements` clause list in
   the override or in `[pricing].settlements`.
4. **Configuration.** Remove `resources_csv_path`, `resources_csv_inline`,
   `[escrow_templates]`, and `capacity.use_site_projection_for_listings` from
   every storefront configuration file, and the chart's
   `secret.resourcesCsvInline` value. The chart refuses to render with any of
   them, and `market-storefront config set` refuses to write them.

After upgrading, the storefront's database keeps the tables the old inventory
lived in (`resources`, `hosts`, `resource_transition_events`,
`compute_capacity_pools`, and `compute_pool_members`) exactly as they were. The
storefront never reads or writes them again; they remain so you can extract
anything you did not declare beforehand. Their rows are history, not current
state: reconcile each against what the provisioning service already holds
before declaring it there, through the provisioning service's own
administration API or definition documents. Nothing copies them across
automatically, and nothing should overwrite a declaration that is already live.

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
- **A site whose projection never loads publishes nothing.** The storefront
  derives listings only from its sites' projections; check `site_projections`
  in `GET /api/v1/system/status` before looking for missing inventory.
- **Do not publish a `host_id`.** Listings use trusted projected `pool_id` or
  `resource_id`; physical host selection is provisioning-owned. The admin
  settle evaluate endpoint validates canonical schedule/begin requests without
  reserving or probing a host.
- **When co-selling VM slices and bare metal, configure one stable physical
  host identity in authoritative provisioning inventory.** Domain projections
  preserve that identity so the site ledger prevents cross-mode double selling.
- **`agent_id` must be a Python identifier** — no dashes.
