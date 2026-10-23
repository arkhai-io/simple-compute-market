## Why

Every compute provisioning database has applied every migration up to and
including `20260921_004_legacy_host_capacity_declarations`. Those 21 entries,
from `20260603_001_ansible_jobs_escrow_uid` onward
(`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`),
are skipped on every live database and run only on a fresh one, where
`run_migrations` has already created the current schema from the models. Their
data rewrites therefore act on no data, yet they are maintained, tested, and
described as current upgrade behaviour in permanent specifications: the legacy
VM lease conversion and the VM adapter's `legacy_backfill.py` that only it
calls, the capacity-model cutover, the executor-identity quarantine, the
host-identity rewrite, the capacity-declaration contract and attribute
rewrites, and the legacy host capacity derivation, among others.

Their schema work cannot simply be deleted: some of it exists nowhere else.
`20260901_001_relay_reachable_hosts` creates the partial unique index
`uq_relay_port_leases_active_owner`, which keeps two concurrent retries from
both taking a relay port, and no model declares it.

## What Changes

- Keep the 21 entries and their IDs, and reduce each body to its schema work,
  removing every data rewrite and the code only those rewrites use.
- Refuse, before any migration runs, a database that holds service rows but has
  not recorded all 21 IDs: such a database predates the supported upgrade floor,
  and running schema-only bodies against it would migrate its schema without
  its data.
- Remove from permanent specifications and documents every statement that
  describes those data rewrites as current upgrade behaviour, and state the
  upgrade floor instead.

## Capabilities

### Modified Capabilities

- `deployment-state`: the provisioning upgrade floor.
- `resource-pool-management`, `physical-provisioning`, `site-capacity`, and any
  other capability whose requirements describe one of the 21 migrations' data
  rewrites.

### New Capabilities

None.

## Non-Goals

- Do not decide the long-term policy for retiring migrations every database has
  applied, such as baselining the chain from the models; that is a separate
  strategy decision this change does not pre-empt.
- Do not change migrations after `20260921_004`, or other services' migration
  chains.

## Impact

- `db/migrations.py`, `db/database.py`, the VM adapter's legacy backfill module,
  and the migration test modules for the 21 entries.
- Permanent specifications and `docs/development/ARCHITECTURE.md`'s "Atomic
  workload-lifecycle cutovers", which describes the legacy VM lease conversion.

## Dependencies and Related Changes

- Independent. Split from `seed-default-pool-at-runtime`'s design, which stops
  `20260713_002_resource_pools_and_hosts_pool_id` seeding a default pool and
  removes capacity derivation from host inventory; either may land first.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deployment-state`,
      `resource-pool-management`, `physical-provisioning`, `site-capacity`, and
      others found by the sweep
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
