# Operator Handbook

This handbook is for the operator of a deployment: the formats of the documents
a deployment is given, the procedures for changing them, and the steps for
upgrading and recovering a site. It describes the system as it is and is
corrected in place when the system changes.

It sits beside three other kinds of document:

- [`docs/development/DEPLOYMENT_AND_CONFIG.md`](development/DEPLOYMENT_AND_CONFIG.md)
  says how a service resolves its configuration and how that maps onto
  Kubernetes and Compose.
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
mounts, and names for the service. The method every kind follows is
[`definition-documents.md`](guidance/engineering/definition-documents.md); the
order startup imports them in, and how each kind here applies the method, are
`physical-provisioning`'s
["Definition documents"](../openspec/specs/physical-provisioning/configuration.md#definition-documents).

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
`ssh_host`, `ssh_user`, `ssh_port`, `public_host`, `public_port`, `key_path`,
and `host_keys`:

```yaml
hosts:
  - host_id: kvm1
    pool_id: vm-default
    connection:
      kind: ssh
      version: 3
      public:
        ssh_host: 10.0.0.5
        public_host: 203.0.113.9
        ssh_user: ubuntu
        key_path: /home/appuser/.ssh/id_ed25519
        host_keys:
          - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK0p…
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
  API. Disabling a host keeps new deliveries off it: a capacity declaration
  naming it, in a backed pool whose provider needs a host, is neither reserved
  against nor scheduled onto, and is projected not enabled, so storefronts close
  its listings. Work already placed on the host keeps it: its create waits until
  the host is enabled, and teardown runs. Enabling the host reopens those
  listings under their original identities. The capacity listing
  (`GET /api/v1/capacity/resources`) still reports each declaration's own
  `enabled`. A declaration naming a host that is not registered is treated the
  same way, so register a host before declaring its capacity.
- **The document names a key; it never carries one.** `key_path` is a file on
  the service's filesystem — under Helm a Secret volume you mount, under Compose
  the key file the stack mounts. An entry naming no `key_path` keeps the stored
  host's protected key, and is refused for a host whose key is a key file, or
  for a new host. An entry stating `connection.secrets` is refused. Registering
  a host with key material is done through the API: `POST /api/v1/hosts` with
  `secrets`, or the INI import route's `embedded` mode.
- **`host_keys` is the host's pin.** It lists the host's OpenSSH public keys,
  each its type and base64 without a comment; an empty list, a malformed key or
  an unknown type is refused, naming the field. The Ansible executor checks the
  host against its pin before every job and connectivity check, and refuses a
  host with no pin ([Capturing and rotating a host key](#capturing-and-rotating-a-host-key)).
  An entry omitting `host_keys` keeps the stored pin, whatever else it changes,
  `ssh_host` and `ssh_port` included, since the key identifies the machine
  rather than its route; an entry stating it replaces the pin. The export
  carries each host's pin, and the INI import, which carries none, keeps it.
- **Every `ssh` connection is version 3.** A host stored at an earlier version
  runs nothing until it is submitted again at version 3: through the host API's
  update (`PUT /api/v1/hosts/{host_id}`), restating every stored public field,
  `key_path` included where the host has one, or an import naming the same key.
  Until then, once any Ansible executor is real, system status's `ansible`
  component is not ready, its reasons naming the host and the version served,
  and the host has no `ssh_keys` entry. The upgrade's migration rewrites every
  stored connection to version 3
  ([What the upgrade from v0.3.0 changes](#what-the-upgrade-from-v030-changes)).
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

#### A host's protected key no longer decrypts

A key registered with a host is protected under the service's
`ssh_decryption_key` and decrypted only for the operation that uses it. Under
another key — after the key is rotated, or the database is restored into a
deployment holding a different one — or with none configured, it cannot be
decrypted, and every surface names the host with one message, carrying no
ciphertext or key material:

```text
host 'kvm1': its protected private key cannot be decrypted under the configured ssh_decryption_key; restore the ssh_decryption_key it was protected under, or submit the host's private key again
```

- **A job against the host fails and is not retried**, its error carrying the
  message after `Internal error: `, since a retry meets the same configuration.
  No playbook starts, and nothing the job wrote remains.
- **Its connectivity check** (`GET /api/v1/hosts/{host_id}/connectivity`)
  answers `reachable: false` with the message as its `detail`, and runs no
  ping.
- **System status** (`GET /api/v1/system/status`) reports the `ansible`
  component's `ssh_keys` entry for the host, `<encrypted>`, with `exists:
  false`. Once any Ansible executor is real, the message is among the
  component's `not_ready_reasons` and the component is not ready; every other
  host is reported as it would be without this one. Readiness decrypts each
  enabled host's key in memory to say so, and writes nothing.

To recover, restore the `ssh_decryption_key` the key was protected under, or
submit the host's private key again under the configured key: update the host
through `PUT /api/v1/hosts/{host_id}` with a connection carrying the key in its
`secrets`, which replaces the whole connection, or import it through the INI
import route's `embedded` mode. A host document cannot carry a key. With no
`ssh_decryption_key` configured, the message says so. No private key can be
submitted until a key is configured to protect it, but it need not be the
original: configure the key the host's key was protected under, which recovers
every host it protected, or configure a new one and submit each affected host's
private key again.

#### Capturing and rotating a host key

The Ansible executor reaches a host only when the key it presents matches the
host's pin, its connection's `host_keys`. Before a job's recorded start it makes
one SSH connection that runs nothing on the host, against a transient
`known_hosts` holding the pin under `[ssh_host]:ssh_port`; a host behind a
management tunnel is checked at its tunnel port. A host is pinned in one of two
ways:

- **State the key** at registration, in the host document or the host API's
  connection, read from the host's console or its provider — on the host,
  `/etc/ssh/ssh_host_ed25519_key.pub` — rather than over the network the pin
  protects.
- **Capture it** once the host is registered. Its connectivity check
  (`GET /api/v1/hosts/{host_id}/connectivity`) reports, for an unpinned host,
  the key the host presents, storing nothing:

  ```json
  {"host": "kvm1", "reachable": true, "detail": "kvm1 | SUCCESS …",
   "host_key": {"endpoint": "[10.0.0.5]:22", "pinned": false,
                "presented": "ssh-ed25519 SHA256:Q1m9xkP3…"}}
  ```

  Compare that fingerprint with the one the host shows you independently, such
  as `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` at its console, and only
  when they match record it, with the `admin` role:

  ```bash
  curl … -X POST /api/v1/hosts/kvm1/host-keys/capture \
    -d '{"fingerprint": "SHA256:Q1m9xkP3…"}'
  ```

  The family client's `capture_host_key(host_id, fingerprint, replace=False)`
  makes the same call. The capture probes the host again and records the key
  only when it presents the fingerprint you named, answering the endpoint and
  the pinned fingerprints. It answers 404 for an unknown host, 422 for a host
  whose connection kind presents no key or for a malformed fingerprint (not
  `SHA256:` and a base64 digest), and, recording nothing, 409 with a `code`:
  `host_key_mismatch`, with the endpoint and the fingerprint presented;
  `host_key_pinned`, with the pinned fingerprints, for a host already pinned;
  or `no_host_key_presented`, with the endpoint and the probe's reason, when the
  probe reached no SSH handshake.

For a pinned host the connectivity check reports whether the key matched, and a
mismatch answers `reachable: false` with the refusal as its `detail`. A probe
that reaches no handshake reports `host_key` null with its reason in `detail`.
Once any Ansible executor is real, system status's `ansible` component is not
ready while an enabled host has no pin, naming the host and its endpoint, and
lists the hosts pending adoption ([What the upgrade from v0.3.0
changes](#what-the-upgrade-from-v030-changes)) in `hosts_pending_key_adoption`,
which do not make it not ready.

**Rotating a key.** State the new keys in the host document or through the host
API, or capture the new key with `"replace": true`. To rotate without a refusal
between, state the old key and the new one together, change the host's key, and
then state the new key alone.

**Recovering a host-key refusal.** A job against a host presenting another key,
or with no pin, fails before its execution starts, unretried, and runs nothing on
the host. Its error names the host, its endpoint, the presented and pinned
fingerprints, and how to recover:

```text
host 'kvm1' at '[10.0.0.5]:22': SSH host key verification refused (presented: ssh-ed25519 SHA256:…; pinned: ssh-ed25519 SHA256:…). Verify the host fingerprint independently and capture or state its host key.
```

Find out why the key changed before trusting it: a reinstalled or replaced
machine, a port forwarded to another machine, or an interception. Once you have
confirmed the new key from the host itself, replace the pin as for a rotation. A
teardown refused this way counts as never started, so it runs again under a new
job once the host is pinned, while its lease stays `releasing`
([`physical-provisioning`, "Proof-driven release"](../openspec/specs/physical-provisioning/architecture.md#proof-driven-release)).
A key that changes
between that check and the playbook fails the playbook as started, and a teardown
so failed waits for you to verify the host and force-release its lease.

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

## Ansible configuration

The provisioning service runs every playbook and connectivity check under the
Ansible configuration it exports as `ANSIBLE_CONFIG` at startup: the file the
profile's `ansible_cfg` names, used as it is, or, when `ansible_cfg` is empty,
the configuration packaged with the service's Ansible distribution. The
contract is the `physical-provisioning` requirement "Ansible output is kept only
redacted unless an operator configures otherwise".

- **The packaged configuration keeps no log file.** Ansible's output is kept
  only where the service redacts it: a job's logs, and a connectivity check's
  result.
- **A job's logs are redacted** with the value of every `password` field and of
  the secret fields the job's domain names, an SSH identity-file argument, and
  an `sshpass` password replaced.
- **A connectivity check's result is redacted** the same way, with the generic
  fields only: its detail, whether Ansible's output or the text of an error
  running it, carries no `password` value, identity-file path or `sshpass`
  password. A probe runs no domain's playbook and names a key only by the path
  of a transient file, so no other secret reaches it.
- **To keep Ansible's own log, name a configuration of your own.** Point
  `ansible_cfg` at an `ansible.cfg` stating `log_path`. The service exports it
  unchanged and sets no `ANSIBLE_LOG_PATH`, so Ansible writes its log where
  that file says. The log receives Ansible's unredacted output, including any
  value a role prints, and it is written in the provisioning container, which
  is the Ansible controller, never on a managed host: whoever can read that
  container's filesystem can read it. Your file replaces the packaged one whole,
  so restate any of its settings you rely on.
- **Host-key verification is rendered per host, and no configuration turns it
  off.** Each inventory line the service writes states
  `ansible_host_key_checking=true`, `ansible_ssh_args` with the service's own
  baseline, and `ansible_ssh_common_args` naming the job's transient
  `known_hosts` with `GlobalKnownHostsFile=/dev/null` and
  `StrictHostKeyChecking=yes`. Host variables outrank any configuration, so a
  file of your own stating `host_key_checking = False`, or its own `ssh_args`,
  changes neither, and neither does the packaged configuration's own
  `host_key_checking = False`
  ([Capturing and rotating a host key](#capturing-and-rotating-a-host-key)).

## Payments access

A storefront settling in `arkhai.payments.v1` needs three things from its
deployment, beside `[Settlement.arkhai_payments]` in its public `config`: its
payments key, the CA its payments service's certificate chains to when that is
not a public one, and a way to prove the two work together. How the storefront
resolves them is in `settlement-configuration`'s
["Settlement consumer configuration and cutover"](../openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover).

**The key goes in the runtime Secret's overlay.** State it as
`[Settlement.arkhai_payments] api_key` in the `storefront.secrets.toml` key of the
Secret the agent's `secret.secretName` names (`secret.secretName` at the top level
of the bare-metal chart), beside the wallet key:

```toml
[Settlement.arkhai_payments]
api_key = "<the seller's payments API key>"
```

No chart value carries the key, and the values schema refuses `api_key`,
`api_key_env`, and any `[[DisputeCredential]]` entry in public `config`; a
dispute credential the storefront needs goes whole in the same overlay. A Secret
written without the key still deploys: the storefront reports its payments
readiness blocked by `arkhai_payments.api_key_missing`.

**A private CA is a ConfigMap the deployment supplies.** Put the PEM bundle in a
ConfigMap key, or a Secret key, and name it with the agent's `caBundle`:

```yaml
caBundle:
  configMapName: payments-ca-bundle   # or secretName, never both
  key: ca-bundle.pem
```

The chart mounts it and sets `[Settlement.arkhai_payments].ca_bundle_path` to the
mounted file; a `config` stating another path, or stating no payments section, is
refused at render. Only the payments client trusts the bundle. The chart has no
default and creates no ConfigMap: a pod naming a missing one never starts. A
service with a publicly trusted certificate needs no `caBundle`.

**Prove it with `check-payments`.** Set the agent's `tests.paymentsAccount` to the
seller's payee account, and `helm test <release>` runs the agent's
`<agent>-payments-check` pod: `market-storefront check-payments --account
<account>` (`bare-metal-storefront check-payments` for the bare-metal chart) from
the storefront's own image, configuration, overlay, credential and CA mount. Rerun
it after any change to the key, the CA or `service_url`. When the exact conditions
of the running pod matter, run the same command in it:

```console
kubectl exec deploy/<storefront deployment> -- market-storefront check-payments --account <payee account>
```

It prints one JSON line and exits 0 when the read succeeded:

| `step` | What failed | Look at |
|---|---|---|
| `configuration` | the storefront cannot read its configuration, or the section is absent, invalid or disabled, names no `service_url` or no key, or its CA bundle cannot be loaded | `config`, the overlay, the `caBundle` source |
| `credential` | the variable a buyer-style `api_key_env` names is unset, empty, or not a single-line key | the overlay: a storefront states `api_key` |
| `transport` | the service could not be reached over a trusted connection, or answered outside its contract | `service_url`, the network path, the CA bundle |
| `refused` | the service refused the read; `code` is its error code | the key, and that `--account` is the key's own account |

The line never contains the key.

**A dispute authority is proven with `check-mediation`.** A VM storefront's
`[[DisputeCredential]]` for an authority whose certificate chains to a private CA
names the bundle as `ca_bundle_path`, a file the pod mounts; the chart's CA mount,
`/etc/arkhai/ca/ca-bundle.pem`, serves when the same bundle covers it. Set the
agent's `tests.mediationOrigin` to the authority's origin, and `helm test
<release>` runs the agent's `<agent>-mediation-check` pod: `market-storefront
check-mediation --origin <origin>`, one authenticated read of the authority's
respondent listing with the credential whose `origin` is exactly that one. Rerun
it after any change to the credential or its bundle, or run it in the running
pod:

```console
kubectl exec deploy/<storefront deployment> -- market-storefront check-mediation --origin <authority origin>
```

It prints one JSON line, `{"check": "mediation", "outcome": …, "origin": …}`, and
exits 0 when the read succeeded, whatever the listing held; 1 when a step failed,
the line naming the `step` and a fixed-text `detail`; and 2 on a malformed origin.
It files, rules and changes nothing, and never prints the token:

| `step` | What failed | Look at |
|---|---|---|
| `configuration` | no credential, or more than one, names the origin; its identity or origin is refused; or its CA bundle cannot be loaded | the overlay's `[[DisputeCredential]]`, its `ca_bundle_path`, the pod's mounts |
| `credential` | the variable a buyer-style `api_key_env` names is unset or empty | the overlay: a storefront states `api_key` |
| `transport` | the authority could not be reached over a trusted connection, or answered outside its contract | the origin, the network path, the CA bundle |
| `refused` | the authority refused the read; `code` is its error code | the token |

### Changing the payments service mode

Pointing a buyer and a storefront at a live payments service from a test-mode one,
or back, is a cutover: a receipt verifies only under the mode its process is set
to, so a payment deal accepted under the old mode never reaches delivery or
issuance afterwards (`settlement-configuration`'s
["Settlement consumer configuration and cutover"](../openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover)).

1. Drain the open payment deals, letting each reach delivery or issuance, or
   refund them.
2. Set `livemode` in `[Settlement.arkhai_payments]` (`[bare_metal.arkhai_payments]`
   in the bare-metal buyer's configuration file) on both buyer and storefront, in
   the same release that points them at the new service's `service_url` and
   receipt identity.
3. Rerun the storefront's `check-payments` against the new service.

## Serving rate deals

A VM storefront declaring `[Settlement.rate_servicing.arkhai_payments]` sells
on-demand and spot deals paid period by period
([seller quickstart, "Offering on-demand and spot"](seller-quickstart.md#offering-on-demand-and-spot)).
Such a deal runs until a stop at the payment authority — the buyer's, a spot seller's,
its funds running out, its term end, or the dispute authority's — and its storefront
services it for as long as it runs. The storefront's administrator reads its deals
through the signed seller lifecycle routes, each request signed by a principal of
the storefront's `Identity.administrators`:

- `GET /api/v1/admin/lifecycle` lists them a page at a time (`limit`,
  `continuation`), each with its `state`, its `ending` codes, its payment `parts`, its
  `open_cases` and `has_open_extension`;
- `GET /api/v1/admin/lifecycle/{negotiation_id}` reads one: the payment and dispute
  authorities' views (`authority`), the recorded end and physical progress
  (`delivery`), and the filings the storefront sent (`filings`).

### Leases the storefront has not delivered

A deal's delivery deadline is the one its payments clause publishes, and the
storefront enforces it: once a payment read made after the deadline shows no lawful
end before it, the storefront records the deal's non-delivery, files it with the
deal's dispute authority as the payee, and ends its lease at the site. The site does
not enforce the deadline. A committed lease the storefront never delivers therefore
keeps its capacity, as long as the deal's term, whenever the storefront stops
servicing that deal: the storefront is down, its loops are held, its database is
lost, or the payment authority is out of its reach, which leaves the deal waiting
for a payment read made after the deadline (`deal-lifecycle`'s
["One end instant, transactional admission"](../openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission)
describes that barrier).

**Watch for them at the site.** As the provisioning service's administrator, list
the VM leases still active:

```text
GET /api/v1/contract/leases?status=active&offering_mode=vm
```

A lease with no `activated_at_utc` has no activation recorded, and the storefront
activates every lease it delivers before the deal is available. It is overdue once
its `lease_start_utc` plus the clause's `delivery_deadline_seconds` has passed — for
a deal committed after its agreed start, the commitment plus the deadline, at most
the clause's approval window later — or its `lease_end_utc`, if that comes first.
Its `deal_ref.negotiation_id` names the storefront's deal.

**Read the deal at its storefront**, with `GET /api/v1/admin/lifecycle/{negotiation_id}`:

- A `delivery.recorded_end` with progress `end_recorded` or `tearing_down` is a deal
  the storefront is ending; the lease ends when its teardown completes.
- No recorded end: run a servicing cycle,
  `POST /api/v1/admin/lifecycle/deal-servicing/run-cycle`, and read again; each cycle
  services one page of deals, so a storefront holding many may need several. The
  cycle that services the deal with a successful payment read records the
  non-delivery. While the payment authority
  is out of reach no cycle does: prove the storefront's access with
  `market-storefront check-payments` ("Payments access" above). A storefront whose
  loops are held resumes them with `POST /api/v1/admin/lifecycle/resume`.
- To end the deal at once, `POST /api/v1/admin/deals/{negotiation_id}/interrupt`
  with `{"interruption_kind": "failure", "reason": "<why>"}` records the operator's
  end, files `delivery_end` as the payee, undelivered, and ends the lease.

**End a lease its storefront cannot service.** When the storefront is gone or has
lost the deal, end the lease at the site, as the provisioning service's
administrator:

```text
POST /api/v1/contract/leases/{capacity_reservation_id}/terminate
{"reason": "<why>"}
```

Termination ends the lease now and tears down whatever its fulfillment created;
the capacity returns once the teardown is proven, and a lease left `release_failed`
waits for an operator's `retry-release` or `force-release`. A storefront that later
learns of the termination from the site's report classifies it as the seller's own
withdrawal and files the payee's `delivery_end`, as its deadline would have.

### Draining payment deals before a receipt key change

Each environment's payments receipt identity is assumed stable for a deal's life. A
deal approved under an identity stops verifying once that identity leaves the
storefront's configuration — its snapshot reads, its admission, its stored receipt's
revalidation and its refund are each refused — and nothing re-anchors it to a new
key (`settlement-configuration`'s
["Settlement consumer configuration and cutover"](../openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover)).
A rate deal runs until a stop, up to its term, so drain the storefront before the
change:

1. Stop new deals: `POST /api/v1/admin/pause` refuses every new negotiation while
   the storefront goes on servicing its deals. A negotiation already open may still
   become a deal, which step 3 waits for too.
2. Let the running deals end. An on-demand deal ends at its buyer's stop, when its
   funds run out, or at its term end at the latest. A spot deal ends sooner with
   `market-storefront deals preempt <negotiation-id> --operation-key <key>` once its
   notice has run. Let each open once-only payment deal reach delivery or issuance,
   or refund it, as "Changing the payments service mode" says.
3. Wait until `GET /api/v1/admin/lifecycle` lists every payment deal `ended`. A case
   can still be filed on an ended deal while its dispute window runs; after the
   change the storefront cannot verify that deal's payments, and the case is followed
   at the dispute authority.
4. Change the identity. For the moment of the switch, `receipt_identities` in
   `[Settlement.arkhai_payments]` may list the new identity, as `service_identity`
   names it, beside the old one marked `retiring = true`. A retiring entry must state
   `valid_until`, the Unix second from which it verifies no receipt approved at or
   after it. Removing the retiring entry ends the cutover. Buyers update their receipt
   identity before approving again.
5. Rerun `check-payments`, then resume trading with `POST /api/v1/admin/resume`.

### What each dispute outcome shows

The storefront learns of every decision by reading the payment and dispute
authorities each servicing cycle; neither calls it. A deal with a recorded end is
listed `ended` only once its resource is released, every payment part has stopped
or reached its end, and the dispute authority's saved view shows no open case
(`deal-lifecycle`'s
["One end instant, transactional admission"](../openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission),
"When a deal is ended"). Until then it is `ending`, and `ending` names what is
outstanding:

| Code | What is outstanding | What the operator does |
|---|---|---|
| `release_pending` | The resource is not yet proven released | Follow the lease at the site |
| `payment_running` | A payment part has no verified stop or end at the payment authority | See the ruled end with no stop below; otherwise wait for the stop the deal's terms give |
| `case_open` | A case is open at the dispute authority | Nothing: the authority rules or dismisses it |
| `case_unobserved` | The dispute authority has not yet been read | Wait for the next servicing cycle; if it persists, prove the storefront's reach of the authority with `check-mediation` ("Payments access" above) |

What the read and the list show for each outcome:

| Outcome | What the operator sees |
|---|---|
| No case | `ended` once released and every part stopped |
| A case filed by either party | `ending` with `case_open`, the case in `open_cases`, and `has_open_extension` while the authority holds the money it protects. A case filed after the deal is listed `ended` returns it to `ending` at the next read. The storefront answers a buyer's case itself, appending the seller's concurrence or contesting evidence |
| The storefront's own filing — a missed deadline, an operator's failure end, a lease the site ended without it | The recorded end is the failure's, and `filings` lists the filing with its outcome. A payee's `delivery_end` is the claim the authority may rule without a person |
| A ruling that ends delivery and stops the rate parts | `delivery.recorded_end` with cause `ruling` at the ruled instant, each part's `final_stop` with cause `authority`, and the teardown; `ended` once released and the case closed. No filing follows a ruled end |
| A ruling that ends delivery with no stop | The recorded end with cause `ruling` and the teardown, but a part still billing: the deal stays `ending` with `payment_running`. The storefront sends no money operation of its own, so the correction is the dispute authority's: raise it with the authority |
| A ruling of reversals only | Delivery goes on; the reversals show in the payment authority's view (`authority.events`) |
| No usable credential for the deal's dispute authority | `repair_required`: supply its `[[DisputeCredential]]` in the runtime Secret's overlay and prove it with `check-mediation` |

How a dispute authority dismisses and rules cases, any advisory time to rule it
publishes, and its continuity are its own published policy and procedures; read them
where the authority publishes them. An `arkhai.mediation.v1` authority's description
names the `contact` where its people are reached. This handbook restates none of
them.

## Registry secret profile

The registry chart takes the registry's secret settings — the bootstrap key
`REGISTRY_BOOTSTRAP_API_KEY`, which seeds one write-scoped key when the key table
is empty, and the administrator key `REGISTRY_ADMIN_API_KEY` — from a Secret
holding a profile env file, named by `secretProfile`. It mounts the file beside the
profile it renders from its values and appends its profile to `ACTIVE_PROFILES`,
so a setting the file states overrides the rendered one
([`deployment-state`'s "Registry profile configuration"](../openspec/specs/deployment-state/configuration.md#registry-profile-configuration)).

A values file naming `auth.bootstrapKeySecret` or `auth.adminKeySecret` is refused
at render, naming `secretProfile`. To move off them:

1. Create a Secret whose key is `config-<profile>.env`, holding each setting on a
   dotenv line, with any profile name but `production`, the rendered profile's:

   ```console
   kubectl create secret generic registry-secret-profile \
     --from-file=config-secret.env=./config-secret.env
   ```

   where `config-secret.env` holds

   ```
   REGISTRY_BOOTSTRAP_API_KEY='<the bootstrap key>'
   REGISTRY_ADMIN_API_KEY='<the administrator key>'
   ```

   An External Secrets `ExternalSecret` writing that key into that Secret serves
   equally.
2. In the release's values, remove `auth` and name the Secret:

   ```yaml
   registry:
     secretProfile:
       secretName: registry-secret-profile
       profile: secret
   ```

3. Upgrade the release. The pod's environment holds only `CONFIG_DIRECTORY` and
   `ACTIVE_PROFILES`, which reads `production,secret`.

A bootstrap key seeds a key only into an empty table, so moving an existing
registry changes no key it already holds.

### Operate and recover RFQs

To override the 30-day retrieval window, set `REGISTRY_RFQ_CONTACT_WINDOW_SECONDS` in the registry profile or `registry.config.rfqContactWindowSeconds` in Helm. The registry applies the setting when a new introduction completes, and each earlier introduction retains its recorded cutoff.

Use separate Secret-backed keyrings for retry digests and contact encryption. The contact keyring contains a current writer ID and retained readers. Keep the keys available for every eligible payload and store key material separately from database backups. The registry logs expired-row counts, oldest overdue age and sweep failures. Escalate repeated failures or overdue age above one hour.

For key rotation, drain the deployment and stop all its registry writers. Add a new current writer key to the mounted keyring and keep every current reader. Run `registry-rfq-contact rotate` with the same database, registry authority and mixed keyring. The command re-encrypts retained payloads in batches and checks that every retained row has a reader. After it succeeds, retire the old key from the live keyring and restart the registry. Handle keys held for backups according to the deployment's restore policy.

Keep RFQ admission closed throughout restoration. If you can establish each payload's current eligibility, reconcile intervening terminations and expiries before starting ordinary service. If you lack authoritative intervening history, set `REGISTRY_RFQ_REDACT_RESTORED_CONTACTS=true` in the registry profile and start the restored registry behind closed admission. With Helm, supply this setting in the environment profile selected by `registry.secretProfile`. Startup deletes restored contact payloads, ends restored introductions, clears pending consent, and keeps RFQ operations unavailable in this mode. After redaction succeeds, clear the setting and restart with admission still closed. Verify that the authorized participant cannot retrieve a previously accessible contact before reopening admission. The normal startup sweep also removes expired ciphertext before serving traffic.

## Storefront configuration under Helm

How the VM and bare-metal storefront charts render an agent's configuration is
[`DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through configuration"](development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration).

- **Setting a value to `None`.** A `null` in a values file removes the key rather
  than setting it to `None`. Where the storefront accepts `None` for a setting,
  state it in the storefront's own file, `storefront.toml`, or in the Secret
  overlay, `storefront.secrets.toml`.
- **A refused configuration.** The storefront Deployment uses the `Recreate`
  strategy, so a release whose configuration the storefront refuses at startup
  leaves no running pod. Recover with `helm rollback` to the previous release,
  which restores that release's own values, then correct the values before
  upgrading again.

## Injected time

Every service reads the time from one source its configuration names: wall time,
the default, or injected time, an instant its administrator sets. A production
deployment never sets injected time; leave each service's time-source setting
unset ([`DEPLOYMENT_AND_CONFIG.md`, "The time source"](development/DEPLOYMENT_AND_CONFIG.md#the-time-source)
names each one). Nothing refuses it, because no service can tell it runs in
production, so check instead:

- **The status says which time a service runs on.** Each service's status carries a
  time section: `{"source": "wall"}`, or `{"source": "injected", "now": <Unix
  seconds>}`. Read it on the storefronts' and the provisioning service's signed
  `GET /api/v1/system/status`, the API-credits service's
  `GET /api/v1/system/status` as `admin`, and the registry's `GET /admin/status`
  with its administrator key.
- **A service with injected time says so at startup.** It logs that its time is
  injected and the instant it starts at; beside an Arkhai payments section with
  `livemode = true` it also logs a warning. Either line in a production log means
  the configuration is wrong: unset the setting and restart.
- **The setting routes exist only under injected time.** On an instance configured
  for it, an administrator moves its time forward with `POST /api/v1/admin/time`
  on a storefront, `POST /api/v1/system/time` on the provisioning service and the
  API-credits service, or `POST /admin/time` on the registry, each taking
  `{"now": <Unix seconds>}` behind the service's administrator authentication. An
  earlier instant is refused `409 time_moves_forward` and an invalid body
  `422 invalid_time`, with nothing changed. A wall-time instance has no such route.

A live service's time is never changed, not even to diagnose or recover: its time
is a claim it signs and exchanges, and moving it would date its records and
evidence falsely, break every signed exchange with counterparties on real time,
and stop none of the payment or dispute authorities' deadlines. Switching a
service's source is a reconfiguration and restart. To diagnose or recover a
deployment, pause its loops and use the explicit operator actions — ending a deal,
terminating or force-releasing a lease, stepping one loop cycle. To reproduce an
incident at a chosen instant, restore its databases into a local or lane stack
configured for injected time and set that stack's time there
([injected time, "No live change"](../openspec/specs/injected-time/architecture.md#no-live-change)).

## Upgrading a deployment

Every stateful service — compute provisioning, the VM, bare-metal and API-credit
storefronts, the API-credit service, and the registry — migrates its database
through its own command before its application starts, and its application
refuses a database its command has not migrated
([`migrations-at-startup.md`, "The command and its phase"](guidance/repository/migrations-at-startup.md#the-command-and-its-phase)
names each command and where it runs). A release can therefore fail to start a
service; it never starts one on a database it does not understand. A release that
retires configuration settings is also cut over to a migrated configuration
(["Migrating settlement and publication configuration"](#migrating-settlement-and-publication-configuration)).

### Supported databases

A database the marketplace v0.3.0 release built, or one a later release
migrated, is upgraded in place: compute provisioning's, the VM and bare-metal
storefronts', and the registry's. A database from before v0.3.0 is refused as
unsupported, and so is every existing API-credit storefront or service database:
those services start from a fresh database, and the state in the old one is not
carried. An image older than the database's last migration refuses it as ahead.

### The procedure

For each service, in its own deployment:

1. **Back up its database.** The backup is the only rollback: a migrated database
   cannot be served by the image it was migrated from.
2. **Preview the upgrade** with the new image's command and `--check`, over the
   backup or the live database, for example
   `compute-provisioning-migrate --check`. It changes nothing, exits 0 only for a
   database already compatible, and lists what the upgrade will do: the pending
   migration IDs, a v0.3.0 baseline to be adopted, or why the database is refused.
   A database it reports as unsupported will not start under the new release;
   decide before deploying whether that service starts fresh.
3. **Deploy.** Under Helm the init container runs the command before the
   application; under Compose the service's command runs it before the
   application. A v0.3.0 database is adopted — its v0.3.0 records are replaced by
   the baseline's, without running the baselines — and the migrations after the
   baseline are applied. If the migration fails, the application does not start;
   the init container's or the container's log names the migration that failed,
   and the migrations before it stay applied.
4. **Verify** with `--check`, which now exits 0, and the service's health.
5. **For compute provisioning, pin or adopt its hosts.** The upgrade marks every
   host it holds pending adoption; check system status's
   `hosts_pending_key_adoption`, and pin any host you would rather not adopt on
   first contact, as "What the upgrade from v0.3.0 changes" describes.
6. **Prepare every VM host again with this release's host kit** (`vm-setup.yaml`)
   before the release at which guest convergence retires
   ([the release handbook, "Compatibility to retire"](release-handbook.md#compatibility-to-retire)):
   it installs the guest policy and converges the guests already running.

To roll back, deploy the earlier image over the backup taken in step 1, never
over the migrated database.

### Rolling back past pool constraints

A storefront or provisioning service of a release without pool constraints holds
a pool whose hint carries a constraint, and refuses any write that keeps one
(`storefront-publication`'s
["Storefront listing shapes and pool overrides"](../openspec/specs/storefront-publication/configuration.md#storefront-listing-shapes-and-pool-overrides)).
Before rolling sites and storefronts back to such a release, remove every
constraint mapping from the pools' hints and from the storefronts' stored
overrides, then roll back both together.

### Migrating settlement and publication configuration

The VM and bare-metal storefronts' and the buyer's `config migrate` rewrite
retired settlement and publication settings; the API-credit storefront has no
migration command, and its operators edit its configuration by hand. What the
settlement migration maps and refuses is `settlement-configuration`'s
["Settlement consumer configuration and cutover"](../openspec/specs/settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover)
and
["Alkahest release models"](../openspec/specs/settlement-configuration/configuration.md#alkahest-release-models),
and what the publication migration converts and refuses is
`storefront-publication`'s
["Migrating publication configuration"](../openspec/specs/storefront-publication/configuration.md#migrating-publication-configuration).
For each buyer and storefront configuration overlay, use this production
sequence:

1. Stage the release containing the migration commands without activating the
   new workload.
2. Preview every mounted or generated file. Select a storefront file with the
   root `--config` option; select a buyer overlay through its normal
   `XDG_CONFIG_HOME` mount.

   ```console
   market-storefront --config /path/storefront.toml config migrate \
     --scope settlement --check
   XDG_CONFIG_HOME=/path/to/buyer-overlay market config migrate \
     --scope settlement --check
   ```

3. Resolve every reported conflict and legacy environment-name rename. Then
   create backups and migrate every overlay atomically.

   ```console
   market-storefront --config /path/storefront.toml config migrate \
     --scope settlement --write --backup
   XDG_CONFIG_HOME=/path/to/buyer-overlay market config migrate \
     --scope settlement --write --backup
   ```

   Preview and migrate storefront publication defaults:

   ```console
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --check
   market-storefront --config /path/storefront.toml config migrate \
     --scope publication --write --backup
   ```

4. Repeat `--check` for every file and render the Helm or Compose deployment.
   Do not proceed if a migration, typed configuration validation, generated
   schema check or image/config schema check fails.
   Validation reaches beyond what `config migrate` reads: rendering applies the
   values schema, and at startup
   the storefront applies its typed validation — refusing, for example, a
   settlement schema version other than its own. Untyped settings are not
   checked key by key.
5. Quiesce publication, negotiation, settlement, and recovery automation.
   Deploy the coordinated marketplace configuration, wheels, image, Secret,
   and ConfigMap set. Keep automation quiesced while every storefront reports
   at least one ready mechanism:

   ```console
   market-storefront --config /path/storefront.toml settlement status --json
   ```

6. Resume automation only after the configured ready mechanisms and blocker
   set match the intended overlay. Before activation or new settlement effects,
   rollback restores each same-directory `.bak` and the previous pinned
   artifacts together. After effects resume, recover forward from accepted
   settlement plans and operation identities; never change mechanism priority
   to redirect an accepted deal.

### What the upgrade from v0.3.0 changes

- **Host connections.** Compute provisioning rewrites every host's `ssh`
  connection stored at version 1 — which v0.3.0 itself wrote, and refuses, so that
  every job dispatched to such a host failed before any playbook ran — to version
  2, and then every connection at version 2 to version 3, with the same address,
  user, port and key and no `host_keys`. A host whose stored fields version 3
  refuses fails the migration naming it, and nothing is rewritten: correct that
  host from the backup's values, or remove it, then upgrade again. After the
  upgrade a host submission must state its connection's `version`, 3; one stating
  none, or another, is refused.
- **Hosts are adopted by their first check.** Every host the migration rewrites
  is marked pending adoption. Its first job, before its recorded start, or its
  first connectivity check connects running nothing and sending no credential,
  records the key the host presents as its pin, and clears the mark; whichever
  adoption commits first wins, and every job then checks against that committed
  pin. What it trusts is the host's first answer after the upgrade, which is
  what the host was trusted with on every contact before it. To trust none, pin
  each host before its first job, by stating its `host_keys` or capturing its
  key ([Capturing and rotating a host key](#capturing-and-rotating-a-host-key));
  either clears the mark, and a capture after an adoption answers
  `host_key_pinned` unless it states `replace`. A host registered after the
  upgrade is never marked, so it is refused until pinned. Adoption retires at a
  stated release ([the release handbook, "Compatibility to retire"](release-handbook.md#compatibility-to-retire));
  a host still pending then is refused until you pin it.
- **VM guests are isolated.** This release's host kit puts every new guest on an
  isolated bridge port under libvirt's `clean-traffic` filter and installs the
  guest policy, so a guest reaches no other guest, only DHCP and DNS on its host,
  and no link-local or private destination unless
  `guest_allowed_private_destinations` lists it; it needs libvirt 6.1,
  virt-install 3.0, and `ebtables`, and refuses a host lacking any. Preparing an
  upgraded host again with it converges every running guest live, naming any it
  could not, and removes the per-port guest rules an earlier release installed
  (the VM IaC README's "Guest network isolation"). Prepare every VM host again
  before guest convergence retires: a guest never converged keeps a port that
  is not isolated until it is torn down.
- **The stalled-teardown grace.** `lease_watchdog_grace_period_seconds` defaults
  to 3600 in the service and both charts, sized for teardowns of expected length:
  a lease still `releasing` past it is marked `release_failed` with
  `teardown_timeout`. A deployment that pinned 300 should raise it, else a
  teardown that succeeds on a job retry, or on a rerun, is timed out first. Raise
  it, and `relay_grant_expiry_grace_seconds` with it, when you raise
  `teardown_rerun_limit`, the job retries (`default_max_retries` and the retry
  backoff) or `ansible_timeout_seconds`, or when your teardowns run long.
- **Teardowns that never started are run again.** A teardown job refused before
  anything acted on its host is run again under a new job, up to
  `teardown_rerun_limit` times (3 by default; 0 disables it), and its lease stays
  `releasing` meanwhile. A lease that reaches `release_failed` with a failure
  saying the teardown's execution never started and how many reruns were spent
  is not helped by retry-release, which re-observes the same spent teardown.
  Its workload is still on the host: read the last teardown job's error (as in
  step 1 of the version-1 steps below), fix its cause, remove from the host what
  the domain's teardown would have removed (step 2), and force-release the
  lease with a `reason` and `evidence` (step 3).
- **A lease timed out while its teardown went on.** A lease marked
  `release_failed` with `teardown_timeout` whose teardown later finished is
  released by one retry-release
  (`POST /api/v1/contract/leases/<reservation>/retry-release`) once its
  fulfillment is torn down; the retry re-observes the same fulfillment and
  begins no second teardown. One retried while a rerun is pending returns to
  `releasing` and waits for it.
- **Leases left `release_failed` on a version-1 host.** The migration repairs the
  host, not a release that already failed on it. A teardown job is run again only
  when its record proves its execution never started, and these jobs finished
  before the service recorded a job's start or finish: v0.3.0 recorded only a
  handle, after spawning the playbook, so nothing on them proves their playbooks
  never ran. Retry-release therefore re-observes the failed job rather than
  running another.
  A teardown that failed this way never ran, so the deal's guest or tenant account
  is still on the host, and a force-release alone would return the capacity while
  that workload still runs. For each provisioning lease `release_failed` at the
  upgrade:
  1. List the service's leases (`GET /api/v1/contract/leases`, with the `admin`
     role) and read the lease's teardown job and its error. A job refused for its
     host's connection version failed before any playbook ran.
  2. Remove from the host what the domain's teardown would have removed: for a VM
     lease the deal's guest and the artifacts and port forwards it created, for a
     bare-metal lease the tenant's account and its working data.
  3. Force-release the lease
     (`POST /api/v1/contract/leases/<reservation>/force-release`) with a `reason`
     and `evidence` saying what you removed and how you checked.

  A create that failed on a version-1 host never ran either, so its compensating
  teardown, which failed the same way, left nothing to remove: check the host
  holds nothing of the deal, then force-release it.
- **Registry listings.** Each storefront's publication pass closes, at every
  configured registry it reaches, an open listing under its own principal and of
  an offering mode it serves that it does not hold open — such as a superseded
  listing an earlier release left open. A listing it holds open, including one
  held while its site is unreachable, is never closed.
- **Registries and storefronts upgrade together.** A registry keeps each
  listing's whole published document with the seller's signed publication,
  validates every publication against its listing schema, and takes a compute
  listing's prices only in its top-level `pricing` object: it refuses a
  storefront that still publishes an asking rate in the listing's capacity
  description, or a rate structure beside `pricing`, naming the field's place in
  `pricing`. A registry of an earlier release keeps only the fields it names, so
  it drops a newer storefront's `pricing`. Upgrade a registry and every
  storefront that publishes to it in the same window, wherever their releases
  are deployed. A listing the registry already holds stays readable from its
  earlier fields, with no seller publication evidence and outside every
  asking-rate filter, until its storefront republishes it. The registry's
  migration cannot be downgraded; roll back from the backup, as for every
  service.
- **Option identifiers.** The option envelope is a forward-only wire boundary: an
  option's identifier is not stable across a release that changes the envelope.
  Buyers re-read listings after such an upgrade; a closed listing at a registry
  keeps its older shape as history, and nothing rewrites it.
- **Open negotiations cross the upgrade one way.** A shape-priced VM listing
  negotiates a basis-point multiplier over its rates rather than an amount, every
  storefront stores that negotiated quantity under a renamed column, and a VM
  storefront pins and prices each negotiation from the rates it last published
  successfully. None of this is read by an earlier image. Before upgrading a VM
  storefront, drain it:
  1. Pause new negotiations (`POST /api/v1/admin/pause`, with the `admin` role).
  2. Let open negotiation threads end — accepted, exited, or expired.
  3. Settle the deals already accepted.
  4. Take the backup (step 1 of the procedure).

  A shape-priced thread left open does not carry across: the upgraded storefront
  refuses its next round or acceptance — `rate_structure_unpublished` until the
  listing's next successful publication records what it published, then
  `rate_structure_changed_reopen` for having no rate pin — and the buyer
  reopens. A shape-priced listing takes no new negotiation until that
  publication has succeeded at every configured registry the listing was
  published to before the upgrade: until then the others may still serve rates
  the storefront did not record, and it refuses as `rate_structure_divergent`.
  Registry convergence resends the listing to a registry whose last publish
  failed; one whose last publish before the upgrade succeeded is sent the
  listing again only when the listing next changes. Roll back only by deploying
  the earlier image over that backup; a deal negotiated after the upgrade
  cannot be carried back.
- **Bare-metal lease bounds.** A bare-metal pool resolving no positive maximum
  lease duration — from its storefront override, its `capacity_bounds.bare_metal`
  hint, or `[pricing].default_max_duration_seconds` — is no longer held as
  `pool_lease_bound_missing`: its listings publish with no relative maximum, and
  each reserved deal is bounded only by the duration its buyer names and the
  pool's `available_until_utc`. To keep a ceiling, set
  `[pricing].default_max_duration_seconds`, the pool's override, or its hint
  before upgrading. The derivation no longer reports that hold.
- **Bare-metal clauses from the pool's `pricing` hint.** A bare-metal storefront
  resolves a listing's settlement clauses as a VM storefront does: its pool's
  override, then the pool's `pricing.gpu.<model>.settlements` hint for the
  machine's GPU model, then the pool's `pricing.settlements`, then
  `[pricing.defaults.gpu.<model>].settlements`, then `[pricing].settlements`,
  each list whole. A pool advertising both VM and bare metal whose `pricing`
  hint states clauses for VM therefore publishes them on its bare-metal
  listings too; give the bare-metal storefront an override for that pool to
  keep its own.
- **Storefront tables.** A storefront creates the tables v0.3.0 created only when
  a store first opened, where they are absent, and drops the inventory tables
  v0.3.0 kept frozen, with their rows; inventory is declared at provisioning
  ([`seller-quickstart.md`, "Upgrading from CSV inventory"](seller-quickstart.md#upgrading-from-csv-inventory)).
