# Operator Handbook

This handbook is for the operator of a deployment: the formats of the documents
a deployment is given, the procedures for changing them, and the steps for
upgrading and recovering a site. It describes the system as it is and is
corrected in place when the system changes.

It sits beside three other kinds of document:

- [`docs/development/DEPLOYMENT_AND_CONFIG.md`](development/DEPLOYMENT_AND_CONFIG.md)
  says how a service resolves its configuration and how that maps onto
  Kubernetes and Compose, including the method every definition document
  follows.
- The specifications under [`openspec/specs/`](../openspec/specs/README.md) are
  the contracts: what a service must do, stated as requirements and scenarios.
  Where this handbook and a specification disagree, the specification is right
  and this handbook is corrected.
- The seller quickstarts, [`seller-quickstart.md`](seller-quickstart.md) and
  [`bare-metal-seller-quickstart.md`](bare-metal-seller-quickstart.md), walk
  through a first setup under Compose.

## Definition documents

The provisioning service can be given three documents describing what its site
holds: a pool document, a host document, and a capacity document. A fourth, the
relay document, belongs to the VM domain; this chapter covers the first three.
Each is a YAML file mounted like any
configuration file, named by its path setting, and under Helm supplied as the
provisioning chart's `definitions.<kind>` value, which the chart renders,
mounts, and names for the service. The method every kind follows, the order
startup imports them in, and what each does to entries it stops naming are in
`DEPLOYMENT_AND_CONFIG.md`,
["Definition documents"](development/DEPLOYMENT_AND_CONFIG.md#definition-documents).

What that method means for running a site:

- **Editing a mounted document and rolling the deployment applies the edit.**
  Under Helm, a release that changes a `definitions` value changes the
  ConfigMap, whose checksum rolls the pod.
- **Restarting against an unchanged document changes nothing**, so whatever you
  have changed through the API survives a restart, an eviction, or a crash.
- **A document the service cannot apply keeps it from starting.** It names
  every problem, records nothing, and tries the document again on the next
  start.
- **An import through the API reconciles whatever startup last applied**, and
  records nothing startup reads: the next start still applies a mounted
  document only if it changed.

### Validate a changed document before the release that mounts it

The provisioning chart replaces its pod with the `Recreate` strategy, so a
release whose document the service refuses leaves nothing serving until the
document is corrected. Before such a release, submit the changed document to its
validation route, which reports the same problems against the site's live state
and applies nothing:

| Document | Validate | Apply |
|---|---|---|
| Pools | `POST /api/v1/pools/validate` | `POST /api/v1/pools/import` |
| Hosts | `POST /api/v1/hosts/definitions/import` with `"validate_only": true` | the same, without `validate_only` |
| Capacity | `POST /api/v1/capacity/definitions/import` with `"validate_only": true` | the same, without `validate_only` |

Each takes the document's text as `yaml_text`, and each admits the
administrator alone. A clean validation is the release's go-ahead; a refusal
names each problem by its location in the document.

### Pool definitions

A pool document holds a top-level `pools` list. It is configured by
`pool_definitions_path`, under Helm `definitions.pools`:

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

The contract is
[`openspec/specs/resource-pool-management/spec.md`](../openspec/specs/resource-pool-management/spec.md).

- **The document is the whole set.** A pool it stops naming is disabled, never
  deleted. It need not name any particular pool, `default` included, and any
  pool may be disabled.
- **Pools come first.** A mounted pool document creates its pools, with their
  providers, before any host or capacity declaration can name them. One that is
  missing or cannot be applied fails startup, and the seed does not stand in for
  it.
- **Every entry declares `advertisable_modes` and `capacity_backing`** in its
  `policy_tags`; nothing defaults either, and an entry lacking one is refused
  with the rest of its document. After the pool document, startup checks every
  stored pool and refuses to start, naming each pool, if any lacks valid
  declarations. A pool written without them by an older release is repaired by a
  changed pool document that declares them, since the document is imported
  before the check; an unchanged document is not applied again, so it neither
  repairs nor trips the check on its own. The API-credits service seeds its own
  pool with both declarations and checks its pools the same way.
- **A pool's provider is fixed at creation.** A changed document naming another
  provider for an existing pool is refused whole: validation reports
  `provider_immutable` at that entry's `provider`, import applies nothing, and a
  start with it fails naming the entry. See "Moving a pool's members to another
  provider" below.
- **A VM pool may state the shapes its listings are sold in**, as
  `listing_shapes` in `policy_tags`, mapping an offering mode to family-grouped
  shapes: `listing_shapes: {vm: [{gpu: {count: 1, model: H100}, memory: {gib:
  32}}]}`. The pool write checks only their structure; the storefront judges
  whether their families exist, and reports a shape it cannot read while holding
  that pool's listings. A pool stating no shapes publishes the VM default: one
  GPU-only shape per GPU count, per GPU model, from the members declaring GPUs.
  A shape need not state GPUs — `{cpu: {count: 8}, memory: {gib: 32}}` sells a
  VM without GPUs on any member with the vCPUs and memory free, a GPU host
  included — but the default generates none, so a VM pool whose enabled members
  declare no GPUs publishes nothing until it states shapes, on its hint or a
  storefront override; system status reports such a pool once, by site and
  pool, under `publication_derivation` as `listing_shapes_required`.
- **A shape commits only what it states.** A reservation holds every quantity
  the shape states. A dimension it omits is outside the listing's commitment:
  the VM pool's configured defaults (`default_vm_ram`, `default_vm_vcpus`,
  `default_vm_disk_size`) supply it where set, and otherwise the provisioning
  playbook does. Keep capacity for every dimension a pool's shapes omit.

#### The pool seed

A site that configures no pool document and stores no pool, enabled or
disabled, is seeded at startup from the document `pool_seed_path` names. The
packaged default, `seed/pools.yaml` beside the service's `settings.toml`,
declares `vm-default` (`vm.ansible`) and `bare-metal-default`
(`bare_metal.ansible`), each backed and delivering and advertising its own mode,
with no provider configuration, so a VM job in `vm-default` runs the service's
`vm_playbook_path`. The seed pools sell nothing until capacity is declared into
them.

The seed applies once: it records no digest, a site holding pools is never
seeded, and an edit to the seed reaches no existing site. To start a fresh site
with other pools while administering them through the API, point
`pool_seed_path` at your own pool document:

- under Helm, put the document in the provisioning chart's `configFiles` (for
  example as `pool-seed.yaml`) and set `config.pool_seed_path` to
  `/app/config/pool-seed.yaml`;
- under Compose, mount the file into the provisioning service and set
  `PROVISIONING_POOL_SEED_PATH` to its path in an override file.

A relative path resolves against the directory of `settings.toml`. An empty
`pool_seed_path` starts a fresh site with no pool. A seed that applies and is
missing or invalid fails startup; where it does not apply it is not read, so a
dangling path never fails a serving site. Start one process against a fresh
database: two starting together can both find no pool, and the second then
fails its start and, restarted, finds the pools and skips the seed.

#### Moving a pool's members to another provider

A pool's provider cannot change, so inventory moves to another provider through
a second pool:

1. Declare the new pool, with the provider you want, in the pool document or
   through the API.
2. Move each host to it: restate the host's entry with the new `pool_id` in the
   host document, or update it through the host API. The move runs the host
   pool-change hooks; the relays' hook refuses moving a host whose relayed
   delivery a buyer holds to a pool dialling another relay, so wait for those
   leases to end.
3. Move each capacity declaration to it once it holds no live reservation: a
   declaration does not move pools while a hold, reservation, assignment, or
   workload is resolved through its pool.
4. Disable the old pool, or stop naming it in the pool document.

### Host definitions

A host document holds a top-level `hosts` list. It is configured by
`host_definitions_path`, under Helm `definitions.hosts`, and under the Compose
stacks by the file the stack mounts and names with
`PROVISIONING_HOST_DEFINITIONS_PATH`. Each entry has the host registration
API's field names: `host_id`, an optional `pool_id`, an optional `enabled`, and
a `connection` of `kind`, a required `version`, and `public` — for `ssh`,
`ssh_host`, `ssh_user`, `ssh_port`, `public_host`, `public_port`, and
`key_path`:

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

The addresses are documentation values. The contract is the
[`physical-provisioning` specification](../openspec/specs/physical-provisioning/spec.md),
and a host's pool rule is resource-pool management's "Explicit valid host
membership".

- **An entry declares its whole host.** It registers the host or replaces all
  of its non-secret state: an omitted `pool_id`, or `pool_id: null`, unplaces
  the host, and an omitted `enabled` enables it. So a host you disabled or moved
  through the API is restored to the document's statement by the next change to
  the document, unless the document restates it. A pool change runs the host
  pool-change hooks, as an update through the API does. `hosts: []` is a valid
  document that applies nothing.
- **An entry equal to the stored host writes nothing.** Equality is judged after
  the connection's codec fills in its defaults — `ssh_port` 22 and `ssh_user`
  `root` for `ssh` — so an entry omitting them equals a host stored with them.
- **Values are typed strictly.** A quoted number, such as `ssh_port: "22"`, is
  refused, as is `enabled: null`.
- **A host the document does not name is left as it is**, its enabled state
  included, and each apply reports it as registered and not named: in the
  startup log, and in the import response's `not_named`. Hosts are never
  deleted. To stop a host, state `enabled: false` in the document or through the
  API. Disabling a host does not stop its capacity declarations selling.
- **The document names a key; it never carries one.** `key_path` is a file on
  the service's filesystem — under Helm a Secret volume you mount, under Compose
  the key file the stack mounts. An entry naming no `key_path` keeps the stored
  host's protected key, and is refused for a host whose key is a key file, or
  for a new host. An entry stating `connection.secrets` is refused. Registering
  a host with key material is done through the API: `POST /api/v1/hosts` with
  `secrets`, or the INI import route's `embedded` mode.
- **Every `ssh` connection is version 2.** A host stored at version 1 runs
  nothing until it is submitted again at version 2: through the host API's
  update (`PUT /api/v1/hosts/{host_id}`), restating every stored public field,
  `key_path` included where the host has one, or an import naming the same key.
- **A host record describes how to reach a machine, not its hardware.** No host
  write, from a document, an import route, or the host API, declares capacity;
  declare the machine in a capacity document or through the capacity API, naming
  its `host_id`. Work runs only against registered hosts: a host named only in a
  file, or in a document the service refused, is refused at dispatch.

Hosts are imported after pools and the stored-pool check, so every pool an entry
names exists, and before capacity. A site that has never applied a host
document applies the first one configured, as any changed document; a site that
configures none keeps its registered hosts as they are.

#### A refused host move keeps the service down

The relays' host hooks refuse moving a host whose relayed delivery a buyer holds
to a pool dialling another relay, or to no pool, and refuse a host in a
relay-backed pool whose connection address is that pool's relay's. A changed
document making such a write fails the start, and under the chart's `Recreate`
no pod serves while it does, so a buyer's leases cannot drain. Revert the edit
and roll the release again to recover. Validating the changed document first
reports the refusal, coded `pool_change_refused`, without the outage.

#### Exporting and importing the registry

`GET /api/v1/hosts/definitions/export` returns every registered host as a host
document (`application/yaml`), ordered by `host_id`, stating each host's
`pool_id` and `enabled` and no secret; a host holding a protected key appears
with no `key_path`. A host whose connection kind or stored version the service
does not serve gets no entry, so importing the export reports it as not named
and leaves it as it is. Importing an unedited export changes nothing.

`POST /api/v1/hosts/definitions/import` takes `yaml_text` and `validate_only`.
Its response states whether it applied, the created, updated, and unchanged
hosts (`diff`), the registered hosts not named (`not_named`), and every problem
with a `path`, a `code`, and a message. An applying request with any problem
answers 422, carrying that response under `detail`, and applies nothing;
`validate_only` answers 200 with the problems and the planned changes. An
applying request whose commit meets a host another request registered at the
same moment answers 409 and applies nothing; submit it again. The typed family
client's `export_hosts()` and `import_host_definitions()` call the two routes.

#### Upgrading from an INI inventory

The provisioning service reads no INI at startup. `inventory_ini` and
`inventory_path` are retired: a configuration stating either, in any layer and
with any value, an empty one included, refuses to start, naming
`host_definitions_path`. The upgraded service keeps every registered host and,
until a host document is configured, applies none.

Under Helm:

1. Before upgrading, drop `inventory_ini` from the provisioning-secrets Secret
   the release mounts, even where it is empty, and any `inventory_path` you set.
2. Upgrade the release. The service starts with the hosts it had.
3. Export the registry with `GET /api/v1/hosts/definitions/export`.
4. Edit the export into the site's host document, and validate it.
5. Set it as `definitions.hosts` and upgrade the release again. The first start
   with it applies it.

Under Compose, both seller stacks require a host document, so:

1. Remove `inventory_path` and `inventory_ini` from the provisioning service's
   configuration, including any `PROVISIONING_INVENTORY_PATH` or
   `PROVISIONING_INVENTORY_INI` variable an override file sets.
2. Start the upgraded stack once with a host document holding `hosts: []`,
   which applies nothing and leaves every host as it is.
3. Export the registry, edit the export into the site's host document, and
   validate it.
4. Mount it in place of the empty one and restart the provisioning service.

#### The INI import route

The Ansible INI inventory remains Ansible's own host list for preparing hosts,
and the input of `POST /api/v1/hosts/import`, which registers its entries on a
running service. The route keeps the INI format's rules and is not a
reconciled declaration: it reads and records no digest, and it upserts. An
entry's `pool_id=<id>` places or moves the host, an empty `pool_id=` unplaces
it, and an entry with no `pool_id` leaves an existing host's pool unchanged and
a new host unplaced. `public_host=` and `public_port=` name the address and
port a buyer reaches the host on, each falling back to the connection's own;
like `ansible_port=`, a `public_port=` that is not a port from 1 to 65535
rejects its entry with a warning, while the other entries are imported. An
entry's `gpus=` and `gpu_model=`, like every variable the parser does not read,
are ignored without a warning.

### Capacity definitions

A capacity document holds a top-level `resources` list. It is configured by
`capacity_definitions_path`, under Helm `definitions.capacity`. Each entry is a
whole declaration with the registration API's field names — `resource_id`,
`pool_id`, `resource_type`, and a `capacity` map of at least one dimension, plus
optional `resource_subtype`, `host_id`, `attributes`, and `enabled` — and
applying it has exactly the effect of the same
`PUT /api/v1/capacity/resources/{resource_id}`:

```yaml
resources:
  - resource_id: compute-kvm1
    pool_id: vm-default
    resource_type: compute.gpu
    host_id: kvm1
    capacity: {gpu_count: 8, vcpu_count: 192, ram_gb: 2048}
    attributes: {gpu_model: H200, region: "California, US"}
```

The contract is the `physical-provisioning` requirement "Capacity definitions
are imported from a mounted document" and the
[`site-capacity` specification](../openspec/specs/site-capacity/spec.md); what a
storefront publishes from a declaration is in the
[`storefront-publication` specification](../openspec/specs/storefront-publication/spec.md).

- **An entry replaces the declaration it names.** A field it omits is cleared,
  not kept: an entry adopting a declaration the upgrade migration derived from a
  host's GPUs restates its `host_id`, and an omitted `enabled` re-enables a
  declaration disabled through the API. A declaration the document does not
  name is left as it is; disabling one is an explicit `enabled: false`.
- **An entry equal to the stored declaration writes nothing** and emits no
  capacity event, so reapplying a document, or one changed only in comments or
  layout, does not make storefronts republish.
- **Validation is strict and whole.** A quoted number is an error. Every
  structural problem is reported with its location, and a document with any is
  checked no further; a structurally valid document reports every refusal
  stored state decides — an unknown pool, a host another declaration already
  names, a move between pools while the declaration holds a live reservation.
  Any problem applies nothing.
- **Exchanging hosts between two declarations takes two imports**, because
  entries apply in order and the first would briefly name a host the second
  still holds, which is refused.
- **Every declared attribute is published to storefronts.** Attributes are the
  categorical facts claims match (`gpu_model`, `region`); none may repeat a
  declaration field such as `host_id`.
- **For VM, state a region twice: on the pool, which listings advertise, and on
  its declarations, which reservations match.** A VM listing's claim requests
  the region and model it publishes, so a pool whose listings claim a region or
  model no member declares publishes nothing and is reported per pool. A pool
  stating no region is held: nothing new publishes, its listings are neither
  refreshed nor closed except for availability, and system status names it
  (`pool_region_missing`).
- **A bare-metal declaration describes one whole machine.** Set
  `capacity.units` to `1`, and state its hardware under the compute family's
  capacity names — `gpu_count`, `vcpu_count`, `ram_gb`, and `disk_gb` — with
  `attributes.gpu_model` naming its GPUs. State `gpu_count` and `gpu_model`
  together or not at all: a machine without GPUs omits both. A declaration
  stating `gpu_count: 0`, one GPU field without the other, or nothing besides
  `units` cannot be read as a shape, so its storefront publishes nothing from
  it, holds its listing, and reports it by name. The machine's pool must state
  a `region`. Do not put authoritative hardware in `bare_metal_publication`:
  publication-only data is never a source of the listing's shape.
