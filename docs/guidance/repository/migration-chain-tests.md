---
tags: [repository, testing, persistence]
---

# Migration chain tests

How each stateful service's migration chain is proven here, as
[`migration-tests.md`](../engineering/migration-tests.md) requires. How each chain
runs is [`migrations-at-startup.md`](migrations-at-startup.md); what each holds —
its floor, the databases it adopts, its later migrations — is
[`DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup"](../../development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup).

Each stateful service's migration chain is proven against
real SQLite files
([`deployment-state`, "Migration and initialization boundary"](../../../openspec/specs/deployment-state/architecture.md#migration-and-initialization-boundary)):

- **The engine.** `kit/schema-migrations`' unit tests and its library integration
  tests, which run the engine through both adapters, under every transaction
  control, and prove that `schema_snapshot` sees what a schema comparison must and
  ignores how a column was added.
- **The floor fixture.** Every chain declares its `Floor`, a test's chain
  included. Each in-house service commits its floor release's schema under its
  `tests/fixtures/v0_3_0_floor/`: `schema.json` (the snapshot), the release's
  recorded IDs or revision, and `ddl.sql`, as each fixture's README states. That
  covers compute provisioning, the VM, bare-metal and API-credit storefronts, the
  API-credit service, and the registry. v0.3.0's runner kept records outside its
  chain, so the VM storefront also commits `upgraded/`: a database v0.2.29 built and
  v0.3.0 then ran on, with its `schema.json`, its `recorded_ids.json` in `rowid`
  order, its `ddl.sql`, and a README giving how it was built. Bare metal's records
  v0.3.0 does not list, `bare-metal-storefront-0008-hosted-physical-lifecycle` and
  `bare-metal-storefront-0011-accepted-site-generations`, are proven by its
  synthetic case alone. A new floor is a
  release's decision
  ([the release handbook, "The migration floor"](../../release-handbook.md#the-migration-floor)).
- **The chain.** Each service's `tests/integration/test_migration_chain.py` (the
  API-credit service's and the registry's `test_migrations.py`) proves its chain:
  - it compares `CHAIN.floor.recorded` with its fixture's IDs;
  - it adopts a database its floor-database helper builds from `ddl.sql`, also
    carrying a recorded ID and a table no release of the chain lists;
  - it refuses a partial floor as older-or-shared and a ledger of none of the floor's
    IDs as not the service's, asserting the result's `cause`;
  - its later-migration tests start from a `ddl.sql` database.

  The VM storefront's test also adopts its `upgraded/` database. Tests reach a
  migration by its ID, never by its position in the chain, so appending a migration
  breaks none of them. Where the API-credit service's baselines differ from its
  fixture is `deployment-state`'s
  ["Migration chains"](../../../openspec/specs/deployment-state/migration-chains.md).
- **The command and the startup check.** Each service's command is driven
  through its entry point with its settings in the loader's environment layer,
  and is shown to import none of the application's configuration. The startup
  check is proven at the function the application's startup calls, and through the
  application's own startup for an absent database.
- **The store-open test.** Each storefront's `tests/integration/test_store_open.py`
  compares the `schema_snapshot` before and after opening every store it composes.
- **The init containers.** Each chart's render test asserts its one migration
  init container ([`chart-render-tests.md`](chart-render-tests.md)).

In a kit, a test that needs a migrated database migrates it through the kit's own
baseline. The end-to-end lanes start every service through its migration phase on
a fresh database; no lane holds a release's database.
