## Context

`docs/development/ARCHITECTURE.md` (Build, packaging, and initialization) places
config-driven operational seeding in runtime initialization and allows a
migration to seed only deterministic rows a new schema constraint needs.
`openspec/specs/deployment-state/architecture.md#migration-and-initialization-boundary`
gives the reason: a migration's result depends only on code and existing data, and
runtime initialization reconciles operator configuration idempotently.

Compute provisioning broke that rule. With no pool document configured, migration
`20260713_002_resource_pools_and_hosts_pool_id` wrote the `default` pool and its
`ansible_pool_configs` row from settings (`playbook_path`,
`default_pool_inventory_group`), and `run_migrations` read
`pool_definitions_path` to decide whether to seed at all. The job-envelope
migration `20261002_002_job_envelopes` read `default_host_id` the same way.

Reading the code behind that seed showed the implicit `default` pool doing more
than the proposal described:

- A host written without a pool landed in `default`
  (`provisioning/compute/src/compute_provisioning/hosts/service.py`, the INI
  parser in `provisioning/compute/ansible/src/compute_provisioning_ansible/inventory.py`).
  Applying INI inventory, at startup or through `POST /api/v1/hosts/import`,
  derived a capacity declaration for every host with GPUs, in the host's pool
  (`services/capacity_derivation.py`). On a fresh VM site the seeded `default`
  advertised VMs, so a GPU host listed in the inventory was sold on the next
  publication cycle, before its administrator could decide how to sell it. A host
  registered through the host API derived nothing, so the same host behaved
  differently by entry point.
- Nothing that admits, schedules, dispatches, or sells reads a host's pool: those
  paths read the capacity declaration's pool (`kit/site` ledger,
  `kit/fulfillment` scheduler, the VM plan's relay lease). A host's pool is
  placement intent, read by the pool-change hooks, by host reads, and by
  derivation.
- `default_pool_inventory_group` fed a column nothing reads: the VM pool handler
  writes the placeholder `__unused__` on every write. `default_host_id` was read
  only by the job-envelope migration; the job engine fails a job naming no
  registered host rather than falling back.
- The specification said `default` must remain present and enabled; the code
  allows disabling it and its tests assert so. Only a pool document omitting
  `default` was refused.
- `kit/site` read a declaration with no stored pool as `default`, though
  `20260921_002_capacity_declaration_contract` backfilled every such row and every
  write names a pool.
- The VM pool handler required a pool-local `playbook_path`, though the VM
  executor already falls back to the service's playbook; bare metal takes its
  playbook only from service configuration (`bare_metal_playbook_path`). VM e2e
  scenarios copied the seeded `default`'s playbook to create their own pools.

Every provisioning database has applied every migration through
`20260921_004_legacy_host_capacity_declarations`.

## Goals / Non-Goals

**Goals:**

- Migration reads no operational configuration and seeds no pool.
- No host write places a host in a pool or declares its capacity, whatever its
  entry point; a host sells only through capacity an operator has explicitly
  declared.
- A fresh site starts with usable pools for each compute domain, from a packaged
  seed document an operator can override or disable.
- A job's playbook is resolved and frozen when the job is prepared, for every
  provider.

**Non-Goals:**

- Retiring the host's GPU fields or making the `gpu` family optional
  (`gpu-optional-compute-shapes`).
- Removing the data rewrites of migrations before 2026-09-21, or the upgrade floor
  that would guard them (`hollow-pre-floor-provisioning-migrations`).
- Deriving a full compute shape from host facts (a change not yet proposed).
- Changing how host inventory enters the registry
  (`bring-host-inventory-under-definition-documents`), the API-credits service's
  own pool seed, or pool provider and backing immutability.

## Decisions

### D1. A host's pool is optional

`hosts.pool_id` becomes nullable with no server default. A host written without a
pool is unplaced; a pool it names must exist. On update, an omitted `pool_id`
leaves the host's pool unchanged and an explicit `null` unplaces it. In INI
inventory, `pool_id=<id>` places or moves a host, an empty `pool_id=` unplaces it,
and an absent key leaves an existing host's pool unchanged and a new host
unplaced. Unplacing runs the pool-change hooks like any move, so it is refused
where a hook refuses (the VM hook refuses a relay change while relay leases are
held), and a refusal rolls back the whole update or import.

`HostResponse.pool_id` becomes `str | None`; `HostCreate` describes an omitted pool
as unplaced; `InventoryHost` carries three states (a pool, unplace, unstated); the
typed client sends an explicitly set `null`. The table is rebuilt from the model
on SQLite, following `_migrate_capacity_declaration_contract`.

*Rationale.* A site administrator who names no pool must not have a host leased by
accident, and every entry point that writes a host must have the same effect.
Making the key optional is cheaper than inventing a neutral pool to hold
unplaced hosts, and no reader needs a host's pool to be non-null: the readers
that do read it already accept `None` (`ExecutionHost.pool_id`, the VM pool-change
hook) or change with this decision.

*Rejected.* An inert `default` with a service-owned `unassigned` provider adds a
provider concept only to park hosts. Requiring `pool_id` on every host write
closes the same gap but forbids registering a host before its pool exists.
Treating an absent INI key as "unplace" for existing hosts would make re-importing
an old inventory silently unplace hosts placed through the API. A sentinel such as
`pool_id=none` could collide with a real pool id.

### D2. Host writes never declare capacity

Capacity derivation from host inventory is removed: neither startup seeding nor
host import derives a declaration, and neither does the host API. The runtime
derivation module and the host authority's derivation port go. Capacity is
declared only through registration, a capacity-definitions document, or capacity
import. The host's `gpu_count` and `gpu_model`, and INI `gpus=` and `gpu_model=`,
stay as descriptive fields that affect no capacity.

The upgrade derivation in `20260921_004` is untouched here; it ran on every
database, and its removal belongs to `hollow-pre-floor-provisioning-migrations`.

*Rationale.* Derivation was the implicit sale D1 must prevent, and the cause of the
API/import difference. Every existing host's GPUs were already declared by the
upgrade migration, the condition `docs/seller-quickstart.md` set for retiring the
inventory values. No in-repo deployment or e2e lane depends on it: the e2e
scenarios declare capacity explicitly. A later derivation of a full shape from
host facts stays compatible if declarations remain the only statement of what
sells, it targets an explicit pool, and it runs as an operator's act.

*Rejected.* Keeping derivation for placed hosts keeps the side effect and the
API/import difference. Making the host API derive too widens the implicit sale.
Deferring to `bring-host-inventory-under-definition-documents` leaves the side
effect in place until a change with nothing decided lands. Retiring the host GPU
fields here would pre-empt `gpu-optional-compute-shapes`, which decides what a
host describes about its hardware.

### D3. `default` is an ordinary pool name

A pool document need not name `default` (the `missing_default_pool` check goes),
and `default` may be disabled like any pool, as the code already allows. Existing
sites keep their pool named `default`, with its members, as an ordinary pool.
`DEFAULT_POOL_ID` stays exported for the API-credits service, which seeds and
uses its own. `kit/site` and the capacity projection stop reading a declaration
with no stored pool as `default`; such a row is malformed. The
`capacity_buckets.pool_id` column keeps its nullability.

*Rationale.* With no implicit membership and no implicit creation, nothing depends
on `default` being special.

*Rejected.* Keeping the document rule forces every site's first document to declare
a pool nothing needs. Keeping `default` present and enabled would need something
to create it on a fresh site, with a provider fixed for life, which is the defect
that led here.

### D4. A fresh site is seeded from a packaged seed document

A new setting, `pool_seed_path`, names a pool document packaged with the
provisioning service (`seed/pools.yaml` beside `settings.toml`, which relative
paths resolve against); an empty value disables seeding. A startup step,
`seed-initial-pools`, after `import-pool-definitions` and before
`verify-pool-declarations`, applies it only when no `pool_definitions_path` is
configured and no pool is stored. It goes through the document validation and the
existing `import_pools_in_session` in one transaction; on an empty pool table the
import only creates. No digest is recorded. A seed document that fails validation
fails startup.

The packaged document:

```yaml
pools:
  - id: vm-default
    label: VM default
    provider: vm.ansible
    policy_tags:
      deliverable_modes: [vm]
      advertisable_modes: [vm]
      capacity_backing: backed
    provider_config: {}
  - id: bare-metal-default
    label: Bare-metal default
    provider: bare_metal.ansible
    policy_tags:
      deliverable_modes: [bare_metal]
      advertisable_modes: [bare_metal]
      capacity_backing: backed
    provider_config: {}
```

The seed pools are ordinary pools. They are usable at once, and sell nothing until
an operator declares capacity into them, because no host write places a host or
declares capacity (D1, D2). The VM e2e scenarios create their pools with an empty
provider configuration (D5) and stop reading a system pool.

*Rationale.* A site must start, and pass its smoke tests, without the operator
supplying a pool document; pools named for their own providers commit a site to
nothing and never collide with the operator's own. Applying only on an empty site
keeps existing sites, which hold pools, untouched. A later change may make seeding
follow changes to the seed document.

*Rejected.* Making the packaged document the default `pool_definitions_path` would
make it every document-less site's authoritative pool document: the first startup
after upgrade would import it and disable every existing site's pools, including
`default` with its members, and every release editing it would reconcile again,
reverting API-created pools. Seeding when a seed id is missing would add the seeds
to every existing document-less site on upgrade. Each adapter contributing its own
seed pool through its bundle adds a kit field the document makes unnecessary.
Seeding inert pools would make the seed do nothing without an edit.

*Settled in the triage of implementation review 37.*

- **9.4a — a seed is read only where it applies.** A seed document that applies
  and is missing or invalid fails startup; on a site holding pools, or with a pool
  document configured, the seed is not read, so a dangling `pool_seed_path` never
  fails a serving site. Rejected: validating the seed on every start, which fails
  a serving site over a file it will never use; reading it on every start and only
  warning, a code path for a dangling path's sake.
- **9.4b — the seed stays packaged, and an operator overrides it by path.** The
  seed is a service default, so it ships beside `settings.toml` and `config/`, the
  service's other defaults; every way of running the service finds it. Every
  stack starting without a pool document reads it from the installed wheel, which
  is the guard that it is packaged; no packaging check is added. An operator
  replaces it by pointing `pool_seed_path` at another document, or turns seeding
  off with an empty value. In Kubernetes the provisioning chart gains a generic
  `configFiles` map: each entry is rendered verbatim into the ConfigMap and
  mounted read-only at `/app/config/<name>`, and the operator names the file in
  `config`. The chart stays config-neutral: it gives a file no meaning and derives
  no setting from it. Its schema refuses names that are not single file names,
  names the chart mounts itself, and `config.yml` or `config-*.yml` (and their
  `.yaml` forms), which the service would load as profiles around `config`. Its
  templates render the whole map with `toYaml` and quote each mount's name, so a
  file's content and name survive exactly. The seller quickstarts document
  the override. Rejected: a loose seed file copied into the image and named by
  path per deployment, which leaves a service run any other way without a seed; a
  chart value for the seed, `definitions.poolSeed`, which makes the chart aware of
  one setting; a `pool_seed` setting holding the document inline, a larger rework
  depending on Dynaconf replacing rather than merging a nested mapping; and
  documenting only `definitions.pools` and an empty `pool_seed_path`, which gives
  no way to change a fresh site's starting pools with seed behaviour.
- **37 F1 / 9.4f — one process initializes a database.** The seed's emptiness
  check and import share a transaction but are not serialized across processes,
  as the pool-document import and the inventory seed are not. Two processes
  starting together on one fresh database can both find no pool; the second to
  write fails its start, and, restarted, finds the pools and skips. No shipped deployment starts two processes against one database. The
  assumption and its outcome are documented, not changed.

### D5. A job's playbook is resolved and frozen when the job is prepared

A VM pool's `playbook_path` becomes optional: `ansible_pool_configs.playbook_path`
becomes nullable, the handler accepts an omitted value, and the VM fulfillment
model's field becomes optional. When a pool states none, the VM plan writes the
service's `vm_playbook_path` into the job's parameters when it prepares the job,
exactly as it writes a pool's own. Bare metal does the same with
`bare_metal_playbook_path`: `BareMetalJobParams` gains an optional `playbook_path`,
`BareMetalFulfillmentPlan` takes the setting as it takes `bare_metal_reclaim_policy`
and writes it into each grant and reclaim, and the codec passes it to the
executor. Jobs prepared before the change carry no playbook and keep the
executor's configured one. Bare-metal pools still accept no pool-local
configuration.

The setting `playbook_path` is renamed `vm_playbook_path`, beside
`bare_metal_playbook_path`, with no alias. Startup refuses a configuration that
still sets `playbook_path`, naming its replacement, and the provisioning chart's
values schema refuses `config.playbook_path`.

*Rationale.* A static seed document can name a VM pool only if VM, like bare metal,
may leave its playbook to the service, and portable pool documents follow. An
accepted operation keeps the provider inputs it was prepared with
(`openspec/specs/resource-pool-management/architecture.md#provider-configuration`),
so the service's playbook is frozen at preparation rather than read when the job
runs; bare metal already froze its reclaim policy that way. A setting that belongs
to one domain is named for it. An ignored retired key would silently run the
default playbook, so it is refused, as the repository's earlier renames refused
aliases.

*Rejected.* Reading the service's playbook when the job runs would let a
configuration change rewrite an accepted operation's playbook on retry. Keeping
`playbook_path` as the name leaves VM's setting unlike bare metal's.

### D6. Migration reads no operational configuration

`run_migrations(engine)` and `apply_schema_migrations(engine)` take only the
engine; `compute-provisioning-migrate` passes only the engine. The parameters
`default_playbook_path`, `default_inventory_group`, `default_host_id`, and
`pool_definitions_path`, the `seed_default_pool` flag,
`_has_existing_pool_or_host_state`, and the special dispatch for `20260713_002` and
`20261002_002` go. `20260713_002` seeds no pool row and no configuration row. It
refuses, with an actionable `SchemaDriftError`, a database that holds hosts but no
`default` pool: such a database predates resource pools, which every live database
has passed. The settings `default_pool_inventory_group` and `default_host_id` are
retired from `settings.toml`, both Helm values files, and the test fixtures.

`_migrate_job_envelopes` takes a job's `host_id` only from evidence that names its
physical host: the row's `host_id`, then `params.host_id` (which the host-identity
migration `20260921` renamed from `vm_host`), then `params.executor_target` for a
bare-metal job alone, where the bare-metal plan writes the machine. A VM job's
`vm_target`, and its `executor_target`, which defaults to `vm_target`, name its
guest and are never read as its host. A job with none of these keeps `host_id`
NULL, and the migration logs each such job, by ID, at WARNING; if one is queued,
the job engine fails it at execution as naming no host (a failure message of its
own since implementation review 37's triage, 7.6h). The migration's
tests cover a VM job with only a guest target, and one whose guest name matches a
registered host: both keep `host_id` NULL.

`ansible_pool_configs.inventory_group`, which nothing reads, is dropped in the same
table rebuild that makes `playbook_path` nullable.

*Rationale.* A migration's result then depends only on code and data, and
operator configuration has one authority. Whether any database still lacks
`20261002_002` cannot be confirmed, so the fallback fails a job visibly rather than
blocking the upgrade or running it on a guessed host.

*Rejected.* Keeping the parameters as unused defaults leaves an interface that
suggests migration reads configuration. Writing a configuration row with values
fixed in code would serve no live database. Refusing the job-envelope migration
when an active job lacks a host would block an uncertain upgrade until job rows
were edited by hand.

### D7. Smoke tests

`test_host_crud_round_trip` is deleted: it writes state, which `TESTING.md`'s smoke
tier excludes, and integration tests cover it. The authentication check, renamed
`test_an_unsigned_read_is_refused` in implementation review 37's triage (9.4c),
sends an unsigned request to a protected read route instead of a VM create, takes
a new marker, `provisioning_security`, and the provisioning Helm test hook selects
`provisioning_readonly or provisioning_security`. The `provisioning_write` marker
is removed.

### D8. Scope

The API-credits service's own `default` seed stays: it reads no configuration, and
that service runs migration and initialization in one startup step.
`gpu-optional-compute-shapes` and `hollow-pre-floor-provisioning-migrations` were
opened from this design. `bring-host-inventory-under-definition-documents` designs
on the host contract this change settles: it depends on this change at design, and
its non-goal "Do not change the INI format's capacity derivation rule" no longer
applies.

## Risks / Trade-offs

- [Operators who relied on `gpus=` to declare capacity lose it] → Seller
  quickstarts state that capacity is declared explicitly; existing hosts' capacity
  was already declared at upgrade.
- [Fresh e2e stacks have no `default`] → The VM scenarios create their pools with
  an empty provider configuration and read no system pool, so they run the same on
  a fresh stack and on one upgraded in place.
- [An older typed client reads a `null` host pool] → It fails validation. Sites
  and clients are upgraded together by one operator.
- [The playbook rename breaks an operator profile] → Startup refuses the retired
  key by name rather than ignoring it.
- [A host's pool still does not govern selling] → Declaring capacity is an explicit
  act; see Open Questions.

## Migration Plan

Two table rebuilds, each following `_migrate_capacity_declaration_contract`
(foreign keys off, create from the model under a temporary name, copy, drop,
rename, `foreign_key_check`, one transaction): `hosts` with `pool_id` nullable and
no default, and `ansible_pool_configs` with `playbook_path` nullable and
`inventory_group` dropped. Existing rows keep their values. Existing sites keep
their pools and are not seeded. An older image writes the dropped
`inventory_group` column, so recovery after the migration rolls forward.

## Open Questions

- Should a capacity declaration naming a host be required to sit in that host's
  pool, so that placement governs selling and unplacing a host is refused while a
  declaration names it? Today a host's pool is placement intent. Revisit when host
  inventory becomes a reconciled document
  (`bring-host-inventory-under-definition-documents`) or when shape derivation from
  host facts is designed.

## Implementation cadence

One round of two sessions, then closeout:

1. **Service playbooks.** The `vm_playbook_path` rename and the refusal of the
   retired key; the optional VM pool playbook, with the `ansible_pool_configs`
   rebuild and `inventory_group` dropped; the VM and bare-metal plans freezing the
   service's playbook at preparation.
2. **Hosts, pools, and seeding.** The optional host pool and its rebuild, API,
   client, and INI semantics; the removal of inventory derivation; `default` as an
   ordinary pool and the `kit/site` fallbacks; the seed document, `pool_seed_path`,
   and the startup step; the migration entrypoint, `20260713_002`, and the
   job-envelope host; the retired settings; the e2e pool helper and the smoke
   tests.

The second session depends on the first: the seed document's empty VM
configuration needs the optional playbook.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 optional host placement | `openspec/specs/resource-pool-management/spec.md` (Explicit valid host membership); `docs/development/ARCHITECTURE.md` (One name per concept: a host belongs to at most one pool) |
| D1, D2 no implicit placement or capacity (owner principle) | `docs/development/ARCHITECTURE.md` (Resource pools) |
| D2 no derivation from host writes | `openspec/specs/physical-provisioning/spec.md` (Host writes declare no capacity, renamed from Legacy host capacity is derived into declarations); `openspec/specs/site-capacity/architecture.md`; `docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md` |
| D3 `default` ordinary | `openspec/specs/resource-pool-management/spec.md` (Non-destructive pool lifecycle; Strict lossless YAML validation); `openspec/specs/site-capacity/spec.md` (Operator-administered capacity declarations) |
| D4 seed document | `openspec/specs/resource-pool-management/spec.md` (A fresh site is seeded from its seed document); `openspec/specs/resource-pool-management/architecture.md` (Administrative reconciliation); `docs/development/ARCHITECTURE.md` (Resource pools); `docs/development/DEPLOYMENT_AND_CONFIG.md` (Definition documents) |
| D4 amendments (37 triage: 9.4a, 9.4b, 37 F1 / 9.4f) | `openspec/specs/resource-pool-management/spec.md` (A fresh site is seeded from its seed document: read only where it applies; overridden by path); `openspec/specs/deployment-state/spec.md` (The provisioning chart mounts operator files it gives no meaning); `openspec/specs/resource-pool-management/architecture.md` (Administrative reconciliation: one process initializes a database); `docs/development/DEPLOYMENT_AND_CONFIG.md` (Kubernetes: ConfigMap and Secret mounting; Definition documents); `docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md` (overriding the seed) |
| D5 playbooks frozen at preparation, VM pool playbook optional, `vm_playbook_path` | `openspec/specs/physical-provisioning/spec.md`; `openspec/specs/resource-pool-management/architecture.md` (Provider configuration); `docs/development/DEPLOYMENT_AND_CONFIG.md` (Profile-based configuration), including the convention that a setting belonging to one domain is named for it |
| D6 migration reads no configuration | `openspec/specs/deployment-state/spec.md` (Service-owned migration history); `docs/development/DEPLOYMENT_AND_CONFIG.md` (Migrations at startup) |
| D7 smoke tests | `docs/development/TESTING.md` |
| Roadmap gap closed | `docs/development/ROADMAP.md` (Goal 1) |
