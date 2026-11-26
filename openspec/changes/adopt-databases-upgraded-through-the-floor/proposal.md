## Why

A migration floor is meant to say which release a deployment must reach before it can
take a later one. A deployment on an older release upgrades to the floor release
first, then to the later release. What a database recorded before it reached the
floor should not matter once the floor release has run on it.

The migrate commands do not hold to that. Each stateful service's chain adopts a
database recording every migration ID that a *fresh* database built by the floor
release (v0.3.0) records
([`DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup)).
Its classifier, `market_schema_migrations.engine.classify`, judges any other recorded
ID *ahead*. A database that reached v0.3.0 by upgrading from an earlier release
carries records that a fresh v0.3.0 database lacks, so it is refused. The guidance
then gives the wrong remedy for anything it refuses as older than the floor: the
release handbook's "The migration floor" leaves such deployments "to start from a
fresh database", the operator handbook's "Supported databases" says the same, and the
API-credit storefront and service, which have no floor at all, refuse every existing
database. Starting fresh discards a deployment's state, so it cannot be the standing
answer to an upgrade.

It has been observed. On 2026-11-25 a pre-production deployment was upgraded to
marketplace 0.4.0. Its VM storefront's database had been built under v0.2.x and had
run on v0.3.0 since, so it recorded seven VM storefront migrations that every v0.2.x
release applied and v0.3.0 retired:
- `20260604_001_compute_allocation_callback_metadata`;
- `20260604_002_compute_inventory_pools`;
- `20260611_006_pool_member_sites`;
- `20260611_007_allocation_hold_expiry`;
- `20260716_008_rename_compute_capacity_pools`;
- `20260813_010_resource_settlement_clauses`;
- `20260815_005_hosted_settlement_funding_profile`.

v0.3.0's runner tolerated those records, and the deployment ran v0.3.0 normally.
0.4.0's command refused the database as ahead of the image. It told the operator to
restore the backup taken before the upgrade that wrote those records, or to run the
image that wrote them. Neither remedy can help. The deployment's provisioning and
registry databases were adopted. Its VM storefront was started on a fresh database for
this one release, which is not an acceptable remedy to repeat.

The floor fixtures could not have caught it. Each is the schema and recorded IDs of a
fresh database built by the floor release
([`migration-chain-tests.md`](../../../docs/guidance/repository/migration-chain-tests.md),
"The floor fixture"). No test holds a database that reached the floor by upgrading.

## What Changes

- **Adoption follows the upgrade path.** A database the floor release has run on —
  one recording every ID the floor release's chain recorded and none of the chain's
  baselines — is adopted, whatever earlier releases recorded in it. Adoption forgets
  every recorded ID the chain does not list and records the baselines, in one
  transaction, without running them. Nothing is declared about the records it sets
  aside, and `--check` lists them.
- **Every chain declares a floor.** `market_schema_migrations.Chain` requires a
  `Floor` naming the release it is supported from and the IDs that release's chain
  recorded; a chain that truly needs no minimum declares `0.0.0`, recording
  nothing. Floors may differ between chains.
- **The API-credit storefront and service gain the v0.3.0 floor**, so an existing
  database upgrades in place: the storefront from its committed floor fixture, the
  service from a new one, generated from its v0.3.0 wheels, with a repair migration
  where its baselines do not reproduce it. The pair upgrades in the order its Compose
  deployment already enforces: the service first, the storefront once it is healthy.
- **A database older than the floor is told to upgrade through it.** The command and
  the guidance say to upgrade to the floor release first, then to this one, once the
  operator has confirmed the database is the service's, since a ledger cannot tell an
  older database from another service's that shares its history. Starting on a fresh
  database is never the remedy for a database that can upgrade; a database recording
  none of the floor's migrations is refused as not the service's own.
- **The messages say what happened.** "Ahead" keeps its meaning: an image older than
  the database, which runs the image that wrote it or restores a backup. It arises
  only on a database recording the chain's baselines.
- **Tables a retired migration created are dropped by an ordinary later migration**:
  the VM storefront's already are; the bare-metal storefront drops
  `bare_metal_hosted_lifecycle`, which nothing has read since v0.3.0.
- **The tests hold the upgrade path.** The engine and every chain's tests adopt a
  floor database carrying unknown records and tables; the VM storefront commits one
  real database built by v0.2.29 and then run by v0.3.0, which its chain must adopt
  and bring to the same schema and ledger as a fresh database.
- **The guidance and handbooks say this.** The engineering guidance's
  `migrations.md` and `migration-tests.md` state the floor rule; the repository's
  `migration-chain-tests.md` and `migrations-at-startup.md`,
  `DEPLOYMENT_AND_CONFIG.md`'s "Migrations at startup", the release handbook's "The
  migration floor" and the operator handbook's "Supported databases" and upgrade
  procedure describe it.

## Capabilities

### Modified Capabilities

- `deployment-state`: what each migrate command adopts and refuses, and the remedy it
  names.

### New Capabilities

None.

## Non-Goals

- Do not move the migration floor.
- Do not support skipping the floor release: an older database still upgrades
  through it.
- Do not carry a database that records no migrations, or one the chain did not
  build.
- Do not give a chain more than one floor: a package whose tables join a chain after
  its floor arrives through a later migration.

## Impact

- `kit/schema-migrations` (`Floor`, `Chain`, `engine.classify`, adoption,
  `CheckResult`, `MigrateReport`, `result` messages) and its tests: an incompatible
  change to the kit's API (`Chain.floor_ids` becomes the required `Chain.floor`),
  taking a minor bump before 1.0.0, with every chain in the repository moving with
  it.
- Each in-house service's chain declaration and chain tests; the registry's
  `CheckResult` naming its floor release; the API-credit service's new floor fixture
  and any repair migration; the bare-metal storefront's drop migration; the VM
  storefront's upgraded-database fixture.
- Persistence: databases 0.4.0 refused are adopted in place; no wire or
  configuration change.
- The guidance and handbooks named above, and `deployment-state`'s specification and
  companion.

## Dependencies and Related Changes

- Follows `add-database-migration-commands` (archived 2026-11-09), which introduced
  the packaged commands, the classifier and the v0.3.0 floor, and
  `hollow-pre-floor-provisioning-migrations` (archived 2026-11-09).
- Marketplace 0.4.0 ships before this change. Its release notes tell a deployment
  whose database 0.4.0 refuses this way to keep that service on v0.3.0 until a later
  release adopts its database, which this change does.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 — a database the floor release ran on is adopted whatever else it records:
  `openspec/specs/deployment-state/spec.md` (archive) and
  `openspec/specs/deployment-state/architecture.md`, "Compatibility is the exact set"
  and "The baseline and adoption"; `docs/guidance/engineering/migrations.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup";
  `docs/operator-handbook.md`, "Supported databases".
- D2: no permanent destination — resolved by D1; nothing is declared.
- D3 — both API-credit chains have the v0.3.0 floor:
  `openspec/specs/deployment-state/spec.md` (archive) and its architecture companion;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup";
  `docs/operator-handbook.md`, "Supported databases" and "What the upgrade from
  v0.3.0 changes"; the API-credit service's floor fixture README.
- D4: no permanent destination — resolved by D1; ahead's meaning is D10's.
- D5 — retired tables dropped by an ordinary later migration, bare metal's
  `bare_metal_hosted_lifecycle` among them:
  `openspec/specs/deployment-state/spec.md` (archive) and its architecture companion;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup";
  `docs/operator-handbook.md`, "What the upgrade from v0.3.0 changes".
- D6 — the required `Floor` naming its release:
  `openspec/specs/deployment-state/architecture.md`, "One engine, one contract"; the
  kit's own docstrings.
- D7 — the preview names every record set aside:
  `openspec/specs/deployment-state/spec.md` (archive);
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup";
  `docs/operator-handbook.md`, "The procedure".
- D8 — a floor move carries nothing forward and the rule has no retirement row:
  `docs/release-handbook.md`, "The migration floor".
- D9 — the upgrade path proven synthetically and against a real upgraded VM database:
  `docs/guidance/engineering/migration-tests.md`;
  `docs/guidance/repository/migration-chain-tests.md`; the VM storefront's
  `tests/fixtures/v0_3_0_floor/upgraded/README.md`.
- D10 — the refusals' causes and remedies, and upgrading through the floor:
  `openspec/specs/deployment-state/spec.md` (archive);
  `docs/guidance/engineering/migrations.md`;
  `docs/guidance/repository/migrations-at-startup.md`;
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup";
  `docs/release-handbook.md`, "The migration floor"; `docs/operator-handbook.md`,
  "Supported databases" and "The procedure".
- D11: no permanent destination — the implementation cadence is this change's plan.
- D12 — every chain declares a floor, `0.0.0` where no minimum is owed:
  `openspec/specs/deployment-state/spec.md` (archive) and its architecture companion;
  `docs/guidance/engineering/migrations.md`;
  `docs/guidance/repository/migration-chain-tests.md`.
