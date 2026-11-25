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

- **Adoption follows the upgrade path.** A database the floor release has run on is
  adopted, whatever earlier releases recorded in it. A floor release's chain declares
  the migrations the floor retired, those ancestors' records and the tables they
  created. Adoption sets them aside instead of judging the database ahead or
  unsupported.
- **A database older than the floor is told to upgrade through it.** The command and
  the guidance say to upgrade to the floor release first, then to this one. Starting
  on a fresh database is never the remedy for a database that can upgrade.
- **The messages say what happened.** "Ahead" keeps its meaning: an image older than
  the database, which runs the image that wrote it or restores a backup. A database
  that predates the floor is told to upgrade through the floor release.
- **The tests hold the upgrade path.** Each floor fixture adds a database built by a
  release before the floor and then run by the floor release, which the chain must
  adopt.
- **The guidance and handbooks say this.** The release handbook's "The migration
  floor", `migration-chain-tests.md`, `migrations-at-startup.md`,
  `DEPLOYMENT_AND_CONFIG.md`'s "Migrations at startup" and the operator handbook's
  "Supported databases".

Open for design, not decided here:

- whether the retired tables are dropped at adoption or left untouched, and how
  `schema_snapshot` comparisons treat them;
- how far back a floor's declaration reaches: every release before it, or the
  releases a supported upgrade path started from;
- how a floor move carries this forward: what the new floor's chain declares about
  the floors before it;
- whether the bare-metal storefront, compute provisioning or registry chains carry
  retired pre-floor records of their own;
- the API-credit storefront and service: whether they gain a v0.3.0 floor, so that an
  existing database upgrades in place, or why they cannot.

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

## Impact

- `kit/schema-migrations` (`engine.classify`, adoption, `result` messages) and its
  tests; each service's chain declaration; each service's floor fixtures and
  migration chain tests.
- The guidance and handbooks named above.

## Dependencies and Related Changes

- Follows `add-database-migration-commands` (archived 2026-11-09), which introduced
  the packaged commands, the classifier and the v0.3.0 floor, and
  `hollow-pre-floor-provisioning-migrations` (archived 2026-11-09).
- Marketplace 0.4.0 ships before this change. Its upgrade notes tell a deployment
  whose database 0.4.0 refuses this way what to do in the meantime.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. The guidance and handbook edits above are
this change's own.
