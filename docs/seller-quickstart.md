# VM seller quickstart

How to bring up a compute storefront, publish typed settlement options under a
canonical marketplace identity, and provision KVM VMs on your own hosts.

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
- A KVM-capable host: `egrep -c "(vmx|svm)" /proc/cpuinfo > 0`, `libvirtd`
  running, your ansible user has passwordless sudo and is in the `libvirt`
  group.

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

[Settlement.alkahest.address_books]
# One entry per chain whose Alkahest contracts are a deployment of your own;
# a chain not listed uses the SDK's built-in addresses.
# base_sepolia = "/path/to/alkahest.json"

[wallet]
# Supply private_key through the deployment Secret overlay. The address is
# derived from it; state one only to check it, since an address naming another
# account leaves Alkahest unready.
# address = "0x<YOUR_SELLER_ADDRESS>"

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
livemode = true                          # false against the public test-mode service
# api_key goes in the Secret overlay, storefront.secrets.toml, never here.
# ca_bundle_path = "/path/to/ca-bundle.pem"   # only for a service under a private CA

[pricing]
settlements = [
  { mechanism = "arkhai.payments.v1", asset = "USD/2", rate = "200", per = "hour", mechanism_input = { payee_account = "<YOUR_PAYEE_ACCOUNT>", asset = "USD/2" } },
]
```

These clauses are the storefront-wide terms. A pool's own `pricing` declaration
at its site, and the storefront's per-pool overrides, take precedence over them;
there is no command-level override, because the storefront republishes on its
own and must reach the same terms every cycle.

The receipt-signing identity and fee policy are trusted service configuration.
Dispute authorities are root `[[Dispute]]` preferences followed by the registry's
recommendations (enabled by default for a storefront), not a payments-service
setting; an empty resolved list is reported at startup. See
[dispute authority preferences](development/DEPLOYMENT_AND_CONFIG.md#dispute-authority-preferences).
The accepted option fixes its dispute authority for settlement and refunds.
The API key is a secret setting: state it as `[Settlement.arkhai_payments]`
`api_key` in the Secret overlay `storefront.secrets.toml`, never in the public
file and never as a variable the configuration names. A `ca_bundle_path` makes the
payments client, and nothing else in the process, trust a private CA for the
service. Once the storefront runs, `market-storefront check-payments --account
<YOUR_PAYEE_ACCOUNT>` reads that account's balance with exactly the client the
storefront builds, and reports the first step that failed (see
[settlement consumer configuration](development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover)).
A seller holding a `[[DisputeCredential]]` in the same overlay — with its own
`ca_bundle_path` when the authority's certificate chains to a private CA — runs
`market-storefront check-mediation --origin <the authority's origin>` the same
way: one authenticated read at that authority with exactly the credential the
storefront would use.

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
pools before host definitions are imported; no pool name, `default` included, is
required. To start a fresh site with other pools while keeping pools
administrable through the API, point `pool_seed_path` at your own pool
document: under compose, mount the file into `seller-provisioning` and set
`PROVISIONING_POOL_SEED_PATH` to its path in an override file. An empty
`pool_seed_path` starts a fresh site with no pool. The seed is applied once, to
a site storing no pool; a site that already holds pools is never seeded. The
operator handbook's ["Pool definitions"](operator-handbook.md#pool-definitions)
covers the pool document and the seed, under Helm too.

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
declared attribute is published to storefronts. The operator handbook's
["Capacity definitions"](operator-handbook.md#capacity-definitions) describes the
document's rules in full.

A host record describes how to reach a machine, never its hardware: editing a
host's entry leaves its declaration as it is. Change the declaration instead.

A machine without GPUs omits `gpu_count` and `gpu_model` from its declaration;
the two are stated together or not at all. Its pool then states the shapes it
sells, such as `listing_shapes: {vm: [{cpu: {count: 8}, memory: {gib: 32}}]}`,
because the VM default generates GPU shapes only: a VM pool that states no
shapes and has enabled members, none declaring GPUs, publishes nothing, and the
storefront's system status names it (`listing_shapes_required`). A stated shape
without GPUs may also land on a GPU host's spare vCPUs and memory.

## 4. Prepare your KVM hosts

The provisioning service creates VMs by running Ansible against your KVM hosts
over SSH, so the stack needs a key that reaches them and a host definitions
document declaring them before it starts.

1. Generate an SSH keypair the provisioning container will use to reach
   your KVM hosts, install the pubkey on each host, and put the privkey
   at `./keys/id_ed25519`:

   ```bash
   ssh-keygen -t ed25519 -N "" -f ./keys/id_ed25519
   ssh-copy-id -i ./keys/id_ed25519 <ansible_user>@<ssh_host>
   chmod 600 ./keys/id_ed25519
   ```

2. Declare the execution hosts the service registers, in a host definitions
   document, for example `./host-definitions.yaml`:

   ```yaml
   hosts:
     - host_id: kvm1
       pool_id: vm-default
       connection:
         kind: ssh
         version: 2
         public:
           ssh_host: 10.0.0.5
           public_host: 203.0.113.9
           ssh_user: ubuntu
           key_path: /home/appuser/.ssh/id_ed25519
   ```

   The provisioning service reconciles this document at startup whenever it
   changes: edit it and restart the service, and the hosts it names are
   registered or replaced as it states them; a restart with the document
   unchanged leaves alone whatever you have changed through the API. Each entry
   declares its whole host: an omitted `pool_id` unplaces the host, and an
   omitted `enabled` enables it. A host the document does not name is left as it
   is, and the service logs it as not named. `key_path` is the key's path inside
   the container — compose mounts `./keys/id_ed25519` there — and the document
   never carries a key. A document the service cannot apply, such as one naming
   a pool that does not exist, stops the service from starting, naming the
   problem; check a changed document first with `POST
   /api/v1/hosts/definitions/import` and `"validate_only": true`. The operator
   handbook's ["Host definitions"](operator-handbook.md#host-definitions)
   describes the document's rules in full.

   List only execution hosts. `ssh_host` is how the provisioning service
   reaches the host over SSH. If buyers reach that host on a **different**
   address than the provisioner does (e.g. the provisioner is on a
   private/overlay network but the VM port-forwards are exposed on a public IP),
   state `public_host` — that's the address put in the tenant's connection
   details; without it, they fall back to `ssh_host`. The port a VM's buyer is
   given is always that guest's own forwarded or relay port, never the host's: a
   host's `public_port` is a bare-metal tenant's route, and a VM create ignores
   it. Storefront listings reference trusted projected `pool_id`/`resource_id`;
   they do not carry a `host_id`. Work runs only against registered hosts, and
   a host named only in a file the service has not applied is refused at
   dispatch.

   A host entry describes how to reach the machine, not its hardware: neither
   the document, `POST /api/v1/hosts`, nor the INI import creates a capacity
   declaration. Declare each host's capacity yourself, as "Declaring capacity"
   describes, naming the host's `host_id`. A host that existed when its site
   upgraded to declared capacity received a declaration derived from its GPUs
   then (`resource_id` and `host_id` both the host's name, `capacity`
   `{gpu_count: <gpus>}`, `gpu_model` as an attribute, in the host's pool); that
   declaration is an ordinary one, and stays reservable if the code is rolled
   back.

   The Ansible INI inventory is Ansible's own host list, for preparing hosts
   with the IaC playbooks from your own machine; the service does not read it
   at startup, and the provisioning image does not include it:

   ```bash
   cd domains/vms/provisioning/iac/ansible/inventory
   cp provisioning-hosts.example provisioning-hosts.ini
   # edit provisioning-hosts.ini with the same KVM host(s)
   ```

   Relay proxies and other infrastructure you manage with the IaC playbooks go
   in `hosts` in the same directory (`cp hosts.example hosts`). To register
   hosts from an INI file on a running deployment instead, submit it to
   `POST /api/v1/hosts/import`.

   **Upgrading a seller stack whose provisioning service already registers
   hosts.** The service refuses to start while `inventory_path` or
   `inventory_ini` is stated, even empty, and keeps every registered host once
   upgraded: start it once with a document holding `hosts: []`, then turn its
   export into your document. The operator handbook's
   ["Upgrading from an INI inventory"](operator-handbook.md#upgrading-from-an-ini-inventory)
   gives the steps.

3. KVM host prerequisites: ansible user has passwordless sudo
   (`sudo -n true && echo ok`), is in the `libvirt` group, and
   `libvirtd` is running. The playbook handles cloud-init, virt-install,
   and SSH port-forward NAT.

   The host is x86-64 with hardware virtualization (`vmx` or `svm` in its CPU
   flags) and outbound network access. A scratch create uses one pinned, dated
   release of the Ubuntu Noble x86-64 cloud image and checks its SHA-256 before it
   backs any disk, so it refuses another architecture before touching the host, and
   refuses an image file at the pinned path whose digest differs until you remove
   it. The VM IaC README's "Prerequisites" says how to move the pin.

## 5. Bring it up

`compose/seller.yml` bundles the storefront and provisioning services. It needs
three operator-provided files: `config.seller.toml`, and the SSH private key and
host definitions document from the previous section, which it mounts into the
provisioning service and names with `PROVISIONING_HOST_DEFINITIONS_PATH`. Pass
absolute paths via env to avoid docker compose's
relative-path-resolves-from-the-compose-file gotcha:

```bash
SELLER_CONFIG_PATH="$PWD/config.seller.toml" \
SELLER_SSH_PRIVKEY="$PWD/keys/id_ed25519" \
SELLER_HOST_DEFINITIONS="$PWD/host-definitions.yaml" \
docker compose -f compose/seller.yml up -d

docker compose -f compose/seller.yml logs -f seller-storefront
```

Smoke-test that the provisioning container reaches each host with the mounted
key, naming the host's `ssh_host` and `ssh_user` from its entry:

```bash
docker compose -f compose/seller.yml exec seller-provisioning ansible all \
  -i '<ssh_host>,' -u <ssh_user> \
  --private-key /home/appuser/.ssh/id_ed25519 -m ping
```

`SUCCESS / ping: pong` means a settled deal will create a VM on that host.

Keep `admin_api_key`, `ARKHAI_IDENTITY_CREDENTIAL`, and any Alkahest wallet
private key in the deployment's secret boundary rather than a committed
configuration. The storefront has no provisioning mode: whether a deal's
delivery is mocked or live is the provisioning service's to decide.

There is no publisher preregistration step. Every publication is signed by the
configured canonical marketplace principal, and the registry creates the
stable publisher subject on its first valid publication.

## 6. Preview and publish

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
wallet, no wallet key, a wallet address naming another account than the key's, an
address book for a chain not under `[Chains]`, no `[Chains]` — leaves Alkahest unready rather
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
and receive the connection details of a VM created on one of your hosts.

## Upgrading from CSV inventory

A storefront reads inventory only from its sites' provisioning services; it
holds no inventory of its own, and no setting replaces the retired resource CSV
(`resources_csv_path`, `resources_csv_inline`), its pricing templates
(`[escrow_templates]`), or `capacity.use_site_projection_for_listings`. Remove
them from every storefront configuration file, and the chart's
`secret.resourcesCsvInline` value: the chart refuses to render with any of them,
and `market-storefront config set` refuses to write them. A storefront that
still states them starts, finds no pools, and publishes nothing.

Declare at provisioning what such a CSV described:

1. **Hosts and capacity.** Register each host with the provisioning service, in
   its host definitions document or through the host API, and declare what it
   sells as capacity, as "Declaring capacity" above describes. A CSV row's
   `attribute.vm_host` names the host, and its `value` and
   `attribute.vcpu_count`, `ram_gb`, and `disk_gb` become the declaration's
   `capacity`.
2. **Pools and their terms.** Put each resource in a pool, and declare the
   pool's `region` in its `policy_tags`, with its `listing_shapes` and
   `asking_rates` where you state them. Region can only be declared there, and
   a pool without it is held until it states one. A pool's `sla` hint is read
   only by a storefront with `[pricing].accept_pool_declared_sla` on; otherwise
   state the SLA as an override term.
3. **Storefront terms.** State, with `market-storefront pool-override set`, any
   pool term the storefront itself supplies. A per-row `accepted_escrows` value
   has no equivalent; state the clauses it priced as a `settlements` clause list
   in the override or in `[pricing].settlements`.

The storefront's database keeps none of the tables a storefront-held inventory
lived in: the migration after its v0.3.0 baseline drops them
([operator handbook, "Upgrading a deployment"](operator-handbook.md#upgrading-a-deployment)).

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
