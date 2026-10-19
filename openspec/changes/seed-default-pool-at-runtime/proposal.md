## Why

`docs/development/ARCHITECTURE.md` states the migration boundary: config-driven
operational seeding belongs in runtime initialization, and migrations may seed
only deterministic system rows required to satisfy a new schema constraint.
`openspec/specs/deployment-state/architecture.md#migration-and-initialization-boundary`
gives its reason: migration deterministically transforms the data model, while
runtime initialization reconciles operator configuration idempotently. A
migration's result then depends only on the code and the existing data, and
operator configuration has one authority.

The compute provisioning service's default-pool bootstrap breaks that rule. The
migration `20260713_002_resource_pools_and_hosts_pool_id`
(`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`),
on its first application with no pool definition document configured, writes:

- the `resource_pools` row `default`, whose values are fixed in code. The rule
  allows this row where existing hosts need it for the `hosts.pool_id NOT NULL
  DEFAULT 'default' REFERENCES resource_pools(id)` backfill. On a fresh
  database no host exists, so no schema constraint needs it at migration time;
  what needs it is the runtime invariant that `default` exists before host
  inventory is admitted.
- the `ansible_pool_configs` row for `default`, whose playbook path and
  inventory group come from the service's settings
  (`db/migrate.py` passes `settings.resolved_playbook_path` and
  `settings.default_pool_inventory_group`). No schema constraint requires it.
  This is config-driven operational seeding in a migration.

`run_migrations` (`db/database.py`) also reads `pool_definitions_path` to decide
whether to seed at all, and the `resource-pool-management` requirement "The
default pool is created with its intended provider" states that, without a
configured document, schema initialization retains the VM bootstrap.

The consequences are concrete. A migration that seeded a VM default before a
site's pool document could declare one left a bare-metal site with a default it
could not correct, since a pool's provider is fixed at creation. Gating the seed
on the document path removed that symptom by making migration read more
configuration and judge whether the database is fresh, which needed its own
correction for an interrupted first migration. The seeded default's playbook and
inventory group are a snapshot taken at first migration that later configuration
never revisits, and a schema-migration process needs operational configuration
to run.

## What Changes

- Migration seeds the `default` pool row only where existing hosts need it for
  the `hosts.pool_id` constraint, with values fixed in code, and reads no
  operational configuration: `run_migrations` stops taking the default playbook,
  default inventory group and pool-document path, and judges nothing about a
  configured document.
- Startup ensures `default` between contributed-definition import and host
  inventory. A configured pool document creates it, as today. Without one,
  startup creates the VM default from the configured playbook and inventory
  group, with valid declarations.
- The `resource-pool-management` default-pool requirement says which phase
  creates `default` in each case.

Open for design, not decided here:

- who writes the configuration row of a default a legacy upgrade backfilled
  (hosts but no pools);
- what declarations a runtime-created default carries, and whether it passes
  through the same atomic import path as a document;
- whether a fresh site should instead be required to configure a pool document,
  removing the implicit VM default altogether;
- whether the job-envelope migration's read of `default_host_id` from settings,
  the same rule broken elsewhere, belongs in this change.

## Capabilities

### Modified Capabilities

- `resource-pool-management`: which phase creates the default pool.
- `deployment-state`: the migration and initialization boundary, if its
  statement changes.

### New Capabilities

None.

## Non-Goals

- Do not change a pool's provider immutability or the definition-document
  import contract.
- Do not change the migration/initialization rule itself; the code comes into
  line with it.

## Impact

- Compute provisioning migrations (`db/migrations.py`, `db/database.py`,
  `db/migrate.py`) and startup (`app_runtime.py`, `services/definition_documents.py`).
- The provisioning chart's migration init container, which would no longer need
  operational configuration for the default pool.
- Tests of migration and startup bootstrap, and every VM site's end-to-end
  bootstrap path.
- `docs/development/DEPLOYMENT_AND_CONFIG.md`'s definition-document and
  migration sections, and `resource-pool-management`'s companion architecture.

## Dependencies and Related Changes

- Independent. Follows the archived `fix-resource-pool-provider-at-creation`,
  whose closeout review found the conflict.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `resource-pool-management`, and possibly
      `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
