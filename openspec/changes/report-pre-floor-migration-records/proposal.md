## Why

Every stateful service's migrate command adopts a database recording every migration
ID of the floor release's chain (v0.3.0) and refuses anything older as unsupported, to
start on a fresh database ([`DEPLOYMENT_AND_CONFIG.md`, "Migrations at
startup"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup);
the operator handbook's "Supported databases"). Its classifier,
`market_schema_migrations.engine.classify`, decides which: a database recording every
floor ID and no baseline is adopted, but any other ID its chain does not know makes it
*ahead*, and the command tells the operator to restore the backup taken before the
upgrade that wrote it or to run the image that wrote it.

A database a v0.2.x release built and v0.3.0 has since run records exactly such IDs.
v0.3.0 retired seven VM storefront migrations that every v0.2.x release applied
(`20260604_001_compute_allocation_callback_metadata`,
`20260604_002_compute_inventory_pools`, `20260611_006_pool_member_sites`,
`20260611_007_allocation_hold_expiry`, `20260716_008_rename_compute_capacity_pools`,
`20260813_010_resource_settlement_clauses` and
`20260815_005_hosted_settlement_funding_profile`). v0.3.0's runner tolerated their
records, so such a deployment ran v0.3.0 normally. Marketplace 0.4.0 refuses it as
ahead.

Neither remedy the message names helps. No backup predates those records except one
taken under v0.2.x, and no image that wrote them is supported. By the handbook the
database predates the floor, and its service starts on a fresh database.

This was observed on 2026-11-25, upgrading a pre-production deployment to 0.4.0. Its
VM storefront's database, built under v0.2.x, was refused as ahead. Its provisioning and
registry databases were adopted, and its bare-metal storefront's records are all ones
0.4.0 knows. The deployment's VM
storefront was started on a fresh database, as the handbook directs. 0.4.0's
upgrade notes say a database first built before v0.3.0 starts fresh even if v0.3.0
has run on it.

## What Changes

- A database recording the floor's IDs together with IDs that a release before the
  floor wrote and the floor retired is never reported as ahead. Ahead keeps its
  meaning: an image older than the database.

Open for design, not decided here:

- whether such a database is reported as predating the floor, with the
  fresh-database remedy, or adopted with the retired records set aside. Adoption
  must account for the tables the retired migrations created: "tables the chain did
  not build" is otherwise unsupported;
- where each chain declares the IDs its floor retired, and how a floor move
  regenerates that list (the release handbook's "The migration floor");
- whether the bare-metal storefront, compute provisioning or registry chains carry
  retired pre-floor IDs of their own.

## Capabilities

### Modified Capabilities

- `deployment-state`: how a migrate command classifies a database recording
  migrations a pre-floor release wrote.

### New Capabilities

None.

## Non-Goals

- Do not move the migration floor.
- Do not change how a database an image older than it meets is reported.

## Impact

- `kit/schema-migrations` (`engine.classify`, `result` messages) and its tests, each
  service's chain declaration, and the floor fixtures under
  [`migration-chain-tests.md`](../../../docs/guidance/repository/migration-chain-tests.md).
- `docs/operator-handbook.md` ("Supported databases") and
  `DEPLOYMENT_AND_CONFIG.md` ("Migrations at startup").

## Dependencies and Related Changes

- Follows `add-database-migration-commands` (archived 2026-11-09), which introduced
  the packaged commands and the classifier, and
  `hollow-pre-floor-provisioning-migrations` (archived 2026-11-09).

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
