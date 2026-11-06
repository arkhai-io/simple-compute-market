# Bare-metal seller quickstart

This stack composes the services required to publish exclusive whole-host
capacity, schedule fulfillment through one explicitly trusted site authority,
grant SSH access after settlement, and revoke that access at teardown. It uses
the dedicated wheel-only `arkhai:bare-metal-storefront` image and the ordinary
compute provisioning service; it does not use a direct executor or mock
provisioning.

For VM slices, see [`seller-quickstart.md`](./seller-quickstart.md). A single
Physical Resource may back VM and bare-metal offers only when both listings
use the same stable physical-host identity and their Resource Pools explicitly
declare the relevant `deliverable_modes`.

Whole-host listings may publish Alkahest settlement options. See the
[`buyer quickstart`](./buyer-quickstart.md#supported-settlement-methods) for
buyer-side escrow requirements.

## Prerequisites

- Docker/Podman with Compose v2.24 or later on a Linux host.
- The staged internal wheels and the images built from this checkout.
- Canonical marketplace principals and matching role-scoped signer files for
  the registry, storefront, and selected-site provisioning authority.
- A host definitions document declaring a real whole-host SSH target, and a
  dedicated provisioning SSH private-key file.
- A Resource Pool document that explicitly declares `bare_metal`; absence is
  not a permissive default.
- One strict shared settlement configuration, the `[Settlement]` section of the storefront's configuration. Alkahest roles require chain configuration and the wallet key in the storefront's Secret overlay, whose account, funded, is the public seller address. Payments-only roles use public service, account, and receipt-trust settings without wallet or RPC inputs. Never put a wallet private key, payment credential, or provider object in Compose, the public configuration file, or this document.

The installed `arkhai-bare-metal-buyer` contribution supplies `market bare-metal` discovery, negotiation, contact introduction, and physical lifecycle commands. A running seller stack is not end-to-end evidence until the public path also observes authenticated access, teardown, and access revocation against a disposable host.

## Build the images

```bash
make dist build-registry build-provisioning build-bare-metal-storefront
```

`domains/bare_metal/storefront/Dockerfile` installs the
`arkhai-bare-metal-storefront` wheel from `.dist`. The runtime image does not
copy repository source or resolve an editable sibling package, and it sets no
application setting: the storefront reads every setting from its mounted
configuration files.

## Define the selected site

Create an operator-owned host definitions document outside the repository:

```yaml
hosts:
  - host_id: host-ca-h200-01
    pool_id: whole-host-california
    connection:
      kind: ssh
      version: 2
      public:
        ssh_host: 10.0.0.25
        ssh_user: ubuntu
        public_host: 203.0.113.25
        public_port: 22
        key_path: /home/appuser/.ssh/id_ed25519
```

The addresses are documentation values; use your own. `key_path` is the
provisioning SSH key's path inside the container, where your overlay mounts the
site's key (below); the document never carries a key.

The provisioning service reconciles the document at startup whenever it
changes, after the pool document. List only execution hosts. Each entry declares
its whole host: its `pool_id` places it in that pool, which must exist, and an
entry with none unplaces it; an omitted `enabled` enables it. A host the
document does not name is left as it is and logged as not named. A document the
service cannot apply — one naming a pool that does not exist, say — stops it
from starting, naming the problem. Registering a host declares none of its
capacity: a machine is sold only once you register it as a Physical Resource,
as "Start and inspect" below describes. The operator handbook's
["Host definitions"](operator-handbook.md#host-definitions) describes the
document's rules in full.

Create a Resource Pool document outside the repository. The pool id must match
the host entry's `pool_id`; executor connectivity remains service-owned:

```yaml
pools:
  - id: whole-host-california
    label: Whole Host California
    provider: bare_metal.ansible
    enabled: true
    policy_tags:
      deliverable_modes: [bare_metal]
      advertisable_modes: [bare_metal]
      capacity_backing: backed
      region: California, US
    provider_config: {}
```

The document is authoritative: pools it stops naming are disabled. It need not
name any particular pool, `default` included. A mounted pool document also
replaces the provisioning service's seed. Without one, a fresh site storing no
pool is seeded at startup with `vm-default` and `bare-metal-default`, which sell
nothing until capacity is declared into them; set `pool_seed_path` to another
pool document to seed different pools while administering them through the API,
or to an empty value to start with none. The operator handbook's
["Pool definitions"](operator-handbook.md#pool-definitions) covers the pool
document and the seed, under Helm too.

Every pool must declare `advertisable_modes` — the offering modes its listings
may name — and `capacity_backing`. A `backed` pool may advertise only modes it
also delivers. The service refuses a pool document, and refuses to start, when
an entry omits either declaration; nothing is defaulted.

The bare-metal provider rejects pool-local playbook paths, inventory groups,
credentials, and executor targets. The service-owned
`bare_metal_playbook_path`, the selected Physical Resource, and the registered
host record it names determine execution. The playbook is fixed into each grant
and reclaim when it is prepared, so changing the setting affects only jobs
prepared afterwards.

Edit the document and restart the provisioning service to add or change a host;
a restart with the document unchanged applies nothing, so changes made through
the API survive it. Check a changed document first with `POST
/api/v1/hosts/definitions/import` and `"validate_only": true`. Work runs only
against registered hosts, never against the file. A host's `public_host` and
`public_port` are the endpoint a buyer is given: the route a tenant takes to the
machine, each falling back to the connection's own address and port when the
entry states none. For a relay-backed pool, the buyer receives the leased relay
endpoint instead. The provisioning service's own route stays `ssh_host` and
`ssh_port`. Every host is stored as an `ssh` connection at version 2; a host
stored at version 1 runs nothing until it is submitted again at version 2.

The Ansible INI inventory remains Ansible's own host list for preparing hosts,
and the input of `POST /api/v1/hosts/import`, which registers hosts from it on a
running service; the service does not read it at startup. A site that stated
`inventory_path` or `inventory_ini` must remove it before upgrading, since the
service refuses to start while either is stated; the upgraded service keeps
every registered host. The operator handbook's
["Upgrading from an INI inventory"](operator-handbook.md#upgrading-from-an-ini-inventory)
gives the steps, from a first start with `hosts: []` to a document made from
the registry's export.

For a relay-backed pool, set `provider_config.relay_id` to the registered
buyer relay id. Keep the host's management connection independent of its
buyer route. The relay must already have its token, active grant key and checked
admission plugin; follow [seller relay setup](seller-frp-setup.md). Grant creates
a per-lease proxy through `frpc-buyers`, carrying the signed port grant; the
result names the relay endpoint rather than the management SSH address.

Prepare a relay-backed host with
`domains/bare_metal/provisioning/iac/ansible/playbooks/host-kit/host-setup.yaml`
from `domains/bare_metal/provisioning/iac` with
`ANSIBLE_CONFIG=ansible/ansible.cfg`, the operator-owned inventory and relay
connection variables `frp_server_addr`, `frp_server_port` and `frp_auth_token`.
This prepares `frpc-buyers`; granting a relayed lease also ensures that client
is prepared. If a bounded working-data policy is selected, supply its separate
`bare_metal_working_data_policy` during host preparation. Do not put relay
tokens or grant keys in pool provider extras. A host reached through a management tunnel in a pool without a
buyer relay must explicitly set a tenant-reachable `public_host` and `public_port`;
the management tunnel's endpoint is not an implicit buyer route.

Reclaim removes the lease's proxy, terminates tenant processes and sessions,
checks activity has ended, and applies the configured key/account policy. It does
not merely remove an SSH key while leaving an established tenant session alive.
A relay port remains quarantined until its grant expiry plus the reuse margin;
released capacity does not imply immediate port reuse. Working-data deletion is
an additional configured policy, not a promise implied by key revocation.

### Bounded working-data policy

Use the operator-only `bare-metal-working-data` host-preparation role to
install the protected helper and policy. Create the required protected state
and cleanup roots in the host's actual mount namespace before initialization.
Initialize only through the explicit host-preparation option; normal grant and
reclaim never initialize, reset, adopt or rebuild the UID/GID ledger. Select the
bounded policy and its policy ID in provisioning configuration before new
grants. Existing grants retain their selected policy through reclaim, and
existing grants cannot be adopted into bounded cleanup.

The helper removes only attributable data under its configured roots and
refuses unknown activity or ownership rather than widening its scope. A refusal
keeps the teardown failed and capacity held for recovery. On rollback, disable
new bounded grants and preserve the host ledger; a structurally valid older
ledger cannot identify itself as rolled back. Quarantine a host after known or
suspected ledger rollback until its history is verified or the host is
decommissioned. Do not restore the host ledger from a service database backup.

The pool declaration is authoritative. Do not add `vm` merely to make a
request pass; add it only if the same pool and executor can actually deliver
that mode.

## Prepare role credentials

Use separate owner-readable files:

- the registry's signing credential, only the credential its configured public
  principal expects;
- `storefront-identity.env`, holding the storefront's
  `ARKHAI_IDENTITY_CREDENTIAL`, the one value the storefront reads from its
  environment besides its configuration directory;
- the storefront's Secret overlay, `storefront.secrets.toml`: for Alkahest, the
  seller wallet's `[Wallet] private_key`, and any other secret setting, such as a
  delivery sink's credentials;
- `provisioning-identity.env`, holding the provisioning authority's
  `ARKHAI_IDENTITY_CREDENTIAL`;
- the Ansible key for the selected host. It is not a marketplace credential.

The files must be regular owner-readable files. Do not reuse one principal or
credential across roles, and do not commit credential values.

## Configure public bindings

`compose.bare-metal.yml` holds the stack's topology only, and its services
refuse to start without a deployment's bindings. Write your own overlay beside it
binding your files, with a registry profile and a site profile holding the
public principals. Values shown in angle brackets are required deployment
inputs, not defaults; paths in the overlay resolve against the directory of the
first `-f` file, the repository root.

`/run/operator/registry/config-registry.env`, the registry's profile:

```bash
REGISTRY_AUTHORITY_ID=bare-metal-registry
REGISTRY_AUTHORITY_SCHEME=<scheme>
REGISTRY_AUTHORITY_IDENTIFIER=<canonical-identifier>
REGISTRY_AUTHORITY_CREDENTIAL_FILE=/run/secrets/arkhai/registry-identity/credential
REGISTRY_DESCRIPTOR_BASE_URL=<externally reachable registry URL>
REGISTRY_DESCRIPTOR_DISPLAY_NAME="<display name>"
REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY="<public operator identity>"
```

`/run/operator/config-site.yml`, the site's profile. The provisioning service
trusts the storefront's principal and binds it to the site:

```yaml
identity:
  scheme: "<scheme>"
  identifier: "<canonical-site-authority-identifier>"
storefront_identity:
  scheme: "<scheme>"
  identifier: "<canonical-identifier>"
storefront_site_id: "california-1"
admin_identity:
  scheme: "<scheme>"
  identifier: "<canonical-admin-identifier>"
```

`compose.bare-metal-site.yml`, the overlay:

```yaml
services:
  bare-metal-registry:
    environment:
      - CONFIG_DIRECTORY=/etc/arkhai/registry
      - ACTIVE_PROFILES=registry
    volumes:
      - /run/operator/registry:/etc/arkhai/registry:ro
      - /run/operator/registry-credential:/run/secrets/arkhai/registry-identity/credential:ro
  bare-metal-provisioning:
    env_file:
      - /run/operator/provisioning-identity.env
    environment:
      - CONFIG_DIRECTORY=/app/config
      - ACTIVE_PROFILES=docker,site
    volumes:
      - ./provisioning/compute/service/src/compute_provisioning_service/config/config.yml:/app/config/config.yml:ro
      - ./provisioning/compute/service/src/compute_provisioning_service/config/config-docker.yml:/app/config/config-docker.yml:ro
      - /run/operator/config-site.yml:/app/config/config-site.yml:ro
      - /run/operator/host-definitions.yaml:/run/config/host-definitions.yaml:ro
      - /run/operator/resource-pools.yaml:/run/config/resource-pools.yaml:ro
      - /run/operator/site-ssh-key:/home/appuser/.ssh/id_ed25519:ro
  bare-metal-storefront:
    env_file:
      - /run/operator/storefront-identity.env
    volumes:
      - /run/operator/storefront.toml:/etc/arkhai/storefront.toml:ro
      - /run/operator/storefront.secrets.toml:/etc/arkhai/storefront.secrets.toml:ro
```

The site starts without its SSH key, which Ansible reads only when a job runs, so
a missing key fails the first delivery rather than startup.

The storefront itself reads its settings only from files under
`$XDG_CONFIG_HOME/arkhai/`: the operator's `storefront.toml`, the Compose stack
mounting it and the Secret overlay at `/etc/arkhai/`. The keys are the VM
storefront's for the same concepts; the packaged `settings.toml` documents every
key and its default. A minimal Alkahest seller's `storefront.toml`:

```toml
base_url = "https://seller.example"

[Identity.principal]
scheme     = "<scheme>"
identifier = "<canonical-identifier>"   # the storefront principal the site profile names

[Identity.administrators.operator]
principals = [{ scheme = "<scheme>", identifier = "<canonical-admin-identifier>" }]

# The site's service peer: the provisioning authority's principal.
[Identity.service_peers.california_1_site]
role       = "service"
site_id    = "california-1"
principals = [{ scheme = "<scheme>", identifier = "<canonical-site-authority-identifier>" }]

[capacity]
placement = "fill_first"

[capacity.sites]
california-1 = "http://bare-metal-provisioning:8081"

[registry]
urls = ["http://bare-metal-registry:8080"]

[registry.authorities."http://bare-metal-registry:8080"]
authority  = "bare-metal-registry"
principals = [{ scheme = "<scheme>", identifier = "<canonical-registry-identifier>" }]

[Settlement]
schema_version = 1
priority = ["alkahest.v1"]

[Settlement.alkahest]
enabled = true

[Settlement.alkahest.address_books]
# <chain> = "<address book>", unless the chain's addresses are built in

[Wallet]
# Optional: derived from the key; an address naming another account leaves
# Alkahest unready.
# address = "<public-settlement-address>"

[Chains.<chain>]
rpc_url = "<rpc-url>"

[pricing]
# Each publication clause is complete; a pool's storefront override may replace them.
settlements = [
  { mechanism = "alkahest.v1", asset = "<token-address>", rate = "<rate>", per = "hour", mechanism_input = { chain = "<chain>", escrow_kind = "erc20_escrow_obligation_default" } },
]
default_max_duration_seconds = 7200
```

and its `storefront.secrets.toml`, mounted read-only from the overlay file:

```toml
[Wallet]
private_key = "<seller wallet key>"
```

Each `[capacity.sites]` entry is an exact trust binding: the site's URL, an
HTTP(S) origin with no path, credentials, query, or fragment, and exactly one
service peer bound to it. The storefront seeds the peer into its durable identity
state when it starts; from then on the site's responses and callbacks are verified
against the peer's active principals, which rotate through the storefront's
identity routes (`admin_initiate_identity_rotation`,
`admin_complete_identity_rotation`, `admin_get_identity_status`). After a rotation,
update the peer's `principals` to name the replacement before the next restart:
startup refuses configuration that no longer covers the peer's durable principals.
The storefront does not infer a site from inventory, payload fields, reachability,
or list order. With `most_available`, it compares authoritative capacity
projections only among the listed trusted sites.

## Start and inspect

```bash
docker compose -f compose.bare-metal.yml -f compose.bare-metal-site.yml up -d
docker compose -f compose.bare-metal.yml -f compose.bare-metal-site.yml ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8081/health
curl -fsS http://localhost:8080/health
```

Register the same host as one exclusive Physical Resource through
`SiteCapacityAdminClient.register_resource` using the configured provisioning
administrator signer and exact provisioning-authority trust. The authenticated
`PUT /api/v1/capacity/resources/<physical-resource-id>` body is:

```json
{
  "resource_type": "compute.bare-metal",
  "pool_id": "whole-host-california",
  "host_id": "host-ca-h200-01",
  "capacity": {"units": 1, "gpu_count": 8, "vcpu_count": 192, "ram_gb": 2048, "disk_gb": 7680},
  "attributes": {
    "gpu_model": "H200",
    "physical_host_id": "<provider-stable-host-id>",
    "allocation_mode": "exclusive",
    "bare_metal_publication": {
      "enabled": true,
      "access_methods": ["ssh"]
    }
  },
  "enabled": true
}
```

The declaration is where the listing's hardware comes from. `capacity` holds
exactly one `units`, which is the machine a buyer reserves, and the hardware that
machine contains, under the compute family's names: `gpu_count`, `vcpu_count`,
`ram_gb`, and `disk_gb`. `attributes.gpu_model` names its GPU. The listing
publishes those values where the compute registry's filters read them, so a
buyer asking for `gpu_model=H200 gpu_count>=8` finds it. `gpu_count` and
`gpu_model` are stated together or not at all: a machine without GPUs omits
both, publishes no GPU key, and is found by a buyer bounding `vcpu_count` or
`ram_gb` but by no query bounding a GPU field. Every quantity is optional, but a
declaration must state at least one besides `units`. A capacity key outside
those names, a `units` other than one, a quantity that is not a positive integer
(`gpu_count: 0` included), a GPU count without a model or a model without a
count, or a declaration stating nothing besides `units` holds the machine's
listing and is reported by name.

The URL path's Physical Resource id, the `host_id`, and `physical_host_id` are
separate fields with the exact values shown by their roles. `host_id` is the
host's registered id, its entry's `host_id` in the host definitions document;
`physical_host_id` identifies the physical machine for cross-mode accounting.
Do not substitute the provider id or public IP for the host id.
`physical_host_id` and `allocation_mode` belong at the top level of
`attributes`, where the site authority's exclusive/shareable accounting reads
them; `bare_metal_publication` carries only whether the machine is offered and
how it is reached. Hardware stated anywhere else, such as a `capabilities` map
inside `bare_metal_publication`, is not published, and the round reports it as
ignored.
Everything in `attributes` is published to storefronts. Registration is
independently idempotent and must complete before publication.

A declaration the site cannot build a bare-metal view from — a backed one with no
`host_id`, no `access_methods`, or no `physical_host_id`, a missing or invalid
`allocation_mode`, or a private-looking capacity or capability key — is still
projected, without the view and with the reason, and the storefront reports it as
`publication_view_unbuildable`. Its open listing is held until you correct the
declaration; disabling the declaration still closes it.

**Listing machines the marketplace does not deliver.** A machine you arrange
directly with the buyer, outside this site's provisioning, is listed from an
unbacked pool. Declare one that delivers nothing and advertises bare metal:

```yaml
pools:
  - id: whole-host-direct
    label: Whole Host, arranged directly
    provider: bare_metal.ansible
    enabled: true
    policy_tags:
      deliverable_modes: []
      advertisable_modes: [bare_metal]
      capacity_backing: unbacked
      region: California, US
    provider_config: {}
```

and register each machine in it as a Physical Resource whose `bare_metal_publication`
opts it in, with no host:

```json
{
  "resource_type": "compute.bare-metal",
  "pool_id": "whole-host-direct",
  "capacity": {"units": 1, "gpu_count": 8, "vcpu_count": 192, "ram_gb": 2048, "disk_gb": 7680},
  "attributes": {
    "gpu_model": "H200",
    "allocation_mode": "exclusive",
    "bare_metal_publication": {"enabled": true}
  },
  "enabled": true
}
```

The shape, region, and asking-rate rules are a backed machine's. Its listing
publishes `capacity_backing: unbacked` and carries no `host_id`,
`physical_host_id`, or `access_methods`, even where the declaration names a host,
since nothing the marketplace delivers stands behind them; a buyer finds it with
`capacity_backing=unbacked`. It is never judged against availability, so it never
closes as leased, and it is never reserved, scheduled, or fulfilled. It publishes
only settlement options bare metal does not fulfil through capacity, which today
means contact exchange: enable `[Settlement.contact]` with a contact for the site
and a profile, here `[Settlement.contact.profiles.default]` (see
`docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Contact-exchange contacts"), and offer it to
the pool through a `contact-exchange.v1` clause, in `[pricing].settlements` or, to
keep it to this pool, a pool override:

```bash
bare-metal-storefront pool-override set --file override.json
```

```json
{
  "site_id": "california-1",
  "pool_id": "whole-host-direct",
  "offering_mode": "bare_metal",
  "settlements": [
    {"mechanism": "contact-exchange.v1", "asset": "introduction", "mechanism_input": {"profile": "default"}}
  ]
}
```

A deal on it settles by introduction: once the buyer reveals it, each party
receives the other's contact through its `[Delivery]` sinks, and the deal has no
settlement or fulfillment, so a settle request is answered 409 and its fulfillment
routes 404. A pool whose clauses leave such a listing no option refuses it, as the
cycle below describes.

The stack persists registry, Redis, provisioning, and storefront state in
separate named volumes. Do not treat an HTTP 200 alone as deal readiness:
inspect the storefront health projection and stop if database, fulfillment, or
the configured settlement mechanism is unavailable. Each configured site is
reported separately under `site_projections`, from the projections the storefront
holds and with no call to the site: its resource-pool and capacity-bucket
families each `loaded` (with its revision and digest), `stale` (an earlier
generation kept through a failed poll, with the error), or not yet loaded. A site
that is down is reported there and does not mark the whole storefront degraded.

The storefront refuses to start, naming every problem, when it cannot publish at
all: no `[registry].urls`, or a registry without its `[registry.authorities]`
pin; no enabled `[Settlement]` mechanism; no `[capacity.sites]`, a site bound to
no service peer or to several, or a site URL that is not an origin. It does not
wait for its registry, chains, or site: a registry it cannot reach marks its status
`degraded`, a chain it cannot reach leaves Alkahest unready, and a site it cannot
reach is reported under `site_projections`, its listings held. Missing storefront-wide
terms are not a refusal: a pool whose override and configuration state no positive
maximum lease duration is held and reported instead, and one whose override and
configuration state no settlement clause has its machines refused as
`no_settlement_option`, closing any listing it had open. An Alkahest section that
cannot settle — no `[Chains]` or wallet key, a `[Wallet].address` naming another
account than the key's, or an address book for a chain not under `[Chains]` — leaves
Alkahest unready, its options unpublished, rather than stopping the storefront. A
section listing the `interruptible` release model, which bare metal cannot deliver,
refuses startup, enabled or not. Its administrator's system status
(`get_system_status()` through the canonical storefront client) reports each
lifecycle loop's state and last cycle as `lifecycle`, each settlement mechanism's
readiness and blockers as `settlement`, and as `publication_derivation` each
site's `holds`, `refusals`, and `reports` from the latest publication cycle, each
a reason code with the pool or machine it concerns. A site no cycle has derived
since start is absent from it, and an entry is logged when it first appears and
when it clears, not every cycle.

The storefront publishes on its own. Its projection poller loads every
configured site's projections at startup and every `[capacity].poll_interval`
seconds, and its publication loop runs a cycle every
`[capacity].publication_interval_seconds` and whenever a poll sees a site's
resource-pool generation change, so a machine a site declares is published
without any command. To run or preview one cycle by hand, use
`bare-metal-storefront publish` (`--dry-run` to preview), which signs as the
storefront's administrator and calls the running storefront's
`POST /api/v1/admin/lifecycle/publication/run-cycle` (or `.../dry-run`), the
routes the canonical storefront client calls as
`admin_run_lifecycle_cycle("publication")`; it opens no database and prints the
cycle's report as JSON. `publish --abort-all` closes every open listing as its
seller. The storefront runs one cycle at a time, timer and command alike, and
the lifecycle pause holds the loop without stopping trading. Each cycle:

- Reads the resource-pool projection the storefront holds for every configured
  site, calling no site, and derives one listing per Physical Resource from the
  bare-metal view the site projects for it.
- Lists a resource only if its pool advertises `bare_metal` and is enabled, as
  the Resource Pool document above declares, whether the pool is backed or
  unbacked; each listing publishes its pool's `capacity_backing`. The listing's
  region is the pool's `region`; a pool that states none is held and reported as
  `pool_region_missing`, since the compute registry requires a region.
- Publishes each machine's declared hardware as the listing's shape. A machine
  whose declaration cannot be read as one is held and reported with the reason;
  other machines in its pool are unaffected. Correcting a machine's declared
  hardware closes its listing and publishes a successor under the new shape.
- Closes a listing whose capacity declaration is disabled, or whose pool stops
  advertising `bare_metal` or is disabled.
- Closes a backed listing whose machine is leased, and reopens it once the machine
  is free again. An unbacked listing is never judged against availability.
- Refuses a machine whose listing would carry no settlement option, as
  `no_settlement_option` when the configuration rules out every mechanism its
  clauses name, closing its open listing, which reopens under the same identity
  once an option returns. While one of those mechanisms only cannot be reached, its
  chain or service unreachable, the open listing is held instead, as
  `settlement_mechanism_unknown`.
- Treats a Physical Resource moved to another pool as a new listing: the old
  one closes and a new one is published under the new pool.
- Leaves a listing its seller closed as it is.
- Holds, without closing or refreshing, the listings of a site whose projection
  the storefront does not hold or whose projection is malformed, and of a pool
  whose declarations do not resolve or that resolves no lease bound. A site that
  stops answering keeps its last generation, reported stale,
  and its listings keep deriving from it. The cycle reports each hold; every other
  site is reconciled as usual.
- Writes every new listing locally before any registry is told of it, records
  each registry's answer, and resends to any registry that missed a publish,
  close, or reopen. A later cycle repairs a registry that was unreachable.

The cycle reports every publish, refresh, reopen, close (with its reason), hold,
refusal, and registry repair. It publishes independent typed
settlement options; it does not manufacture availability or substitute a
different site or resource.

While the configuration has an Alkahest section, enabled or not, it settles with at least one `[Chains.<name>]` and the overlay's `[Wallet].private_key`, since a disabled section still services accepted deals; Alkahest readiness names each one missing. The key's account is the seller's address, so `[Wallet].address` is optional, and one naming another account is a blocker too. With no Alkahest section they must be absent, or the storefront refuses to start. Payments-only startup constructs no wallet, RPC, chain, or Alkahest client, and with Alkahest configured, startup constructs no chain client either: the `alkahest-chain-probe` loop builds each and probes each chain every `[Settlement.alkahest].probe_interval_seconds`, so the storefront starts while a chain is down and its Alkahest listings wait for it. The public `[Settlement]` section contains service, account, and trust settings only. An Alkahest listing advertises the release condition its escrow will use on each chain, the recipient arbiter paying the seller's wallet by default; configured for the interruptible release model, which bare metal cannot deliver, the storefront refuses to start. The runtime composes obligation servicing for Alkahest and contact exchange, and receipt-based settlement and reconciliation for Arkhai payments.

### Resetting the storefront database

The bare-metal storefront refuses to start against a database written under a
listing kind it can no longer decode, or one whose reservation table records no
service peer for each reservation's site, and names this section. Accepted
bare-metal state is signed or pinned by content digest, so it is never rewritten
in place, and no decoder for a retired listing kind is kept. The remedy is to
remove the bare-metal deployment and install it fresh:

1. Terminate every active bare-metal lease through the provisioning service's
   lease API, force-releasing any whose teardown cannot complete after
   verifying the node externally. The provisioning service outlives the reset,
   so a lease left active there is orphaned rather than removed.
2. `helm uninstall` the bare-metal release and delete its persistent volume
   claims. Its registry listings go with it only if the registry belongs to
   that release. A registry shared with other roles keeps them, and nothing in
   a fresh storefront knows their listing ids; before uninstalling, disable the
   bare-metal capacity declarations at the provisioning service and let one
   publication cycle run (or run `bare-metal-storefront publish`) after the
   storefront's next poll, which closes every listing the storefront tracks once
   its sites report no bare-metal resources.
3. Deploy the upgrade. The provisioning service migrates its own database in
   place. It is shared with VM fulfillment and is never reset.
4. Install the bare-metal release fresh, re-enable its capacity declarations,
   and publish.
5. Discard bare-metal buyer run logs that reference deals made before the
   reset; nothing can decode them afterwards.

This applies only while bare metal is unreleased. A released deployment cannot
drain long-running contracts to patch, so a retired kind must keep a read-only
decoder until nothing references it. The reservation check is a refusal, not an
upgrade: a reservation recorded before reservations named their site's peer cannot
be rebound to one without guessing.

## Release-qualified deal evidence

Once signed registry publication, the buyer contribution, selected-site
authority, settlement authority, and real host are available, inject the E2E
role inputs and run:

```bash
uv run pytest -m e2e_bare_metal_deal -v
```

The scenario drives the installed `market bare-metal` command as it ships. Its
role inputs are the buyer's marketplace credential
(`ARKHAI_E2E_BARE_METAL_MARKETPLACE_CREDENTIAL`), the tenant's SSH private key
(`ARKHAI_E2E_BARE_METAL_SSH_PRIVATE_KEY_FILE`), a known-hosts file pinning the
delivered host's key (`ARKHAI_E2E_BARE_METAL_KNOWN_HOSTS_FILE`), and the registry and
purchase settings under `BARE_METAL`; without any of them it skips, naming it.

It buys through `buy`, then reads the run back with `result`, `access`, and
`teardown`, each given `--run-id` and the id `buy` printed. Every access attempt is
a fresh SSH process that reads no configuration and checks the host's key strictly
against the pinned file. Teardown repeats `teardown --run-id` until the lease is
`released`, failing at once on `teardown_failed` and at its bound with the last
state. Revocation is proven only by that pinned host refusing the same key for its
public key afterwards; a refused or timed-out connection, an unreachable host, or a
host-key mismatch fails the scenario instead. A mock job, unit result, Compose
render, health response, or provisioning database row is not substitute evidence.

## Operational rules

- Keep Physical Resource, Resource Pool, site, listing, negotiation, and
  fulfillment identities stable through recovery.
- Never provision or reserve a whole host before the accepted settlement
  lifecycle permits it.
- `remove_lease_key`, `lock_user`, and `delete_user` have different blast
  radii. Configure the reclaim policy deliberately for the selected site.
- Teardown releases whole-host access; it is not VM destruction. Collection
  and post-collection lease teardown remain independent of payment reclaim.
- Preserve the storefront and provisioning volumes while a listing,
  negotiation, reservation, fulfillment, or teardown is recoverable.
