## Why

`docs/development/ARCHITECTURE.md` states the migration boundary: config-driven
operational seeding belongs in runtime initialization, and migrations may seed
only deterministic system rows required to satisfy a new schema constraint.
`openspec/specs/deployment-state/architecture.md#migration-and-initialization-boundary`
gives its reason: migration deterministically transforms the data model, while
runtime initialization reconciles operator configuration idempotently.

The compute provisioning service's default-pool bootstrap breaks that rule. With
no pool definition document configured, the migration
`20260713_002_resource_pools_and_hosts_pool_id`
(`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`)
writes the `default` pool and its `ansible_pool_configs` row from the service's
settings, and `run_migrations` (`db/database.py`) reads `pool_definitions_path`
to decide whether to seed at all. The job-envelope migration reads
`default_host_id` from settings the same way.

The implicit `default` also does more than bootstrap. A host written without a
pool lands in it, and applying INI host inventory derives a capacity declaration
for every host with GPUs in the host's pool, so on a fresh VM site a listed GPU
host is sold before its administrator decides how to sell it, while the same host
registered through the API derives nothing. And a VM pool must restate a
deployment-specific playbook path the service already holds, which is why the VM
e2e scenarios copy it from the seeded `default`.

## What Changes

- Migration reads no operational configuration and seeds no pool:
  `run_migrations` takes only the engine, `20260713_002` refuses a database with
  hosts but no `default` pool instead of seeding, and the job-envelope migration
  takes a job's host only from fields that name its physical host, never from a
  VM job's guest target. The settings
  `default_pool_inventory_group` and `default_host_id` are retired.
- A host's pool is optional. A host written without one is unplaced; an explicit
  `null` on update, or an empty `pool_id=` in INI inventory, unplaces a host
  through the pool-change hooks; an absent INI key leaves an existing host
  unchanged. `hosts.pool_id` becomes nullable.
- No host write declares capacity: capacity derivation from host inventory is
  removed, and capacity is declared only explicitly. The host's GPU fields remain
  descriptive.
- `default` becomes an ordinary pool name: pool documents need not name it, it may
  be disabled, and `kit/site` stops reading a declaration with no stored pool as
  `default`.
- A fresh site that configures no pool document and stores no pool is seeded from
  a packaged seed document, named by the new setting `pool_seed_path`, holding
  `vm-default` and `bare-metal-default`.
- A VM pool's playbook is optional; the service's playbook is frozen into a job
  when it is prepared, for VM and bare metal alike. The setting `playbook_path`
  becomes `vm_playbook_path`, and the retired name is refused.
  `ansible_pool_configs.playbook_path` becomes nullable and its unread
  `inventory_group` is dropped.
- The write-path host smoke test is removed, and the authentication smoke test
  runs under a new `provisioning_security` marker the Helm test selects.

## Capabilities

### Modified Capabilities

- `resource-pool-management`: optional host placement, `default` as an ordinary
  pool, and fresh-site seeding from a seed document.
- `physical-provisioning`: no capacity derivation from host writes, playbooks
  frozen at preparation, the optional VM pool playbook, and domain-named playbook
  settings.
- `site-capacity`: a declaration with no stored pool is malformed rather than read
  as `default`.
- `deployment-state`: the provisioning migration entrypoint reads no operational
  configuration.

### New Capabilities

None.

## Non-Goals

- Do not retire the host's GPU fields or make the `gpu` family optional
  (`gpu-optional-compute-shapes`).
- Do not remove the data rewrites of migrations before 2026-09-21
  (`hollow-pre-floor-provisioning-migrations`).
- Do not derive capacity shapes from host facts.
- Do not change how host inventory enters the registry, the API-credits service's
  own pool seed, or pool provider and backing immutability.
- Do not change the migration/initialization rule itself; the code comes into
  line with it.

## Impact

- Compute provisioning: migrations and the migration CLI (`db/migrations.py`,
  `db/database.py`, `db/migrate.py`), startup (`app_runtime.py`), settings and
  configuration profiles, the packaged seed document, and capacity derivation's
  removal.
- `provisioning/compute`: the host authority, contracts, typed client, and the
  Ansible INI parser.
- `kit/resource-pools` document validation and `kit/site`'s pool fallbacks.
- The VM and bare-metal provisioning adapters: pool configuration, fulfillment
  plans, job parameters, codecs, and runtimes.
- The provisioning Helm chart's values and schema; the umbrella values; the e2e
  VM pool helper and the provisioning smoke tests.
- Two table rebuilds: `hosts` and `ansible_pool_configs`.

## Dependencies and Related Changes

- Independent. Follows the archived `fix-resource-pool-provider-at-creation`,
  whose closeout review found the conflict.
- Opened from this design: `gpu-optional-compute-shapes`, which depends on this
  change, and `hollow-pre-floor-provisioning-migrations`, which is independent.
- `bring-host-inventory-under-definition-documents` designs on the host contract
  this change settles, and depends on it at design.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `resource-pool-management`,
      `physical-provisioning`, `site-capacity`, `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Optional host placement, explicit-`null` and empty-INI unplacing →
  `openspec/specs/resource-pool-management/spec.md` (Explicit valid host
  membership); `docs/development/ARCHITECTURE.md` (One name per concept).
- No host write places a host or declares capacity; a host sells only through an
  explicit capacity declaration → `docs/development/ARCHITECTURE.md` (Storefront capacity boundary
  or Resource pools); `openspec/specs/physical-provisioning/spec.md`.
- `default` as an ordinary pool → `openspec/specs/resource-pool-management/spec.md`;
  `openspec/specs/site-capacity/spec.md`.
- Fresh-site seeding from a packaged seed document →
  `openspec/specs/resource-pool-management/spec.md`,
  `openspec/specs/resource-pool-management/architecture.md` (Administrative
  reconciliation), `docs/development/ARCHITECTURE.md` (Resource pools),
  `docs/development/DEPLOYMENT_AND_CONFIG.md` (Definition documents).
- Playbooks frozen at preparation and the optional VM pool playbook →
  `openspec/specs/physical-provisioning/spec.md`,
  `openspec/specs/resource-pool-management/architecture.md` (Provider
  configuration).
- A setting that belongs to one domain is named for it (`vm_playbook_path`) →
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- The migration entrypoint reads no operational configuration →
  `openspec/specs/deployment-state/spec.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`
  (Migrations at startup).
- Smoke markers → `docs/development/TESTING.md`.
- Operator guidance → `docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md`.
