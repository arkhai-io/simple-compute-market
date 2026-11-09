# The VM storefront's v0.3.0 floor

The database the marketplace v0.3.0 release's VM storefront database client builds
on a fresh SQLite file, before any store opens: the schema the storefront's chain is
supported from, and that its baselines, with the store-open migration's tables set
aside, reproduce.

- `schema.json` — the database's `market_schema_migrations.schema_snapshot`: every
  table, column, key, index, trigger, and view, the ledger left out.
- `floor_ids.json` — the migration IDs its `schema_migrations` records, in the order
  it recorded them. A database recording all of them is adopted at the baseline.
- `ddl.sql` — every object's DDL as SQLite stored it, the ledger's included: what
  the baselines are written from, and what a v0.3.0 database is built from to prove
  adoption.

The release's service code is dev `9fffe41e9`. The database was built from the
release's published wheels rather than from a build of that commit, since a rebuild
may resolve different dependencies than the release shipped. In an isolated
environment:

1. Install `arkhai-vms-storefront==0.27.0` from PyPI, with every distribution,
   third-party ones included, constrained to the version
   `domains/vms/storefront/uv.lock` names at `9fffe41e9`, and `kit/schema-migrations`
   from this repository for the snapshot.
2. With no configuration file and no `STOREFRONT_` environment, construct the
   release's `market_storefront.utils.sqlite_client.SQLiteClient` on a fresh file
   with its one-registration VM registry,
   `build_vm_storefront_registry(build_vm_storefront_domain())`, and open no store.
3. Write the file's `schema_snapshot` as `schema.json` (sorted keys, two-space
   indent), the ledger's IDs in `rowid` order as `floor_ids.json`, and each
   `sqlite_master` entry's `sql` in `rowid` order as `ddl.sql`.

The release built 26 tables and recorded 29 IDs, ending at
`20261027_001_fulfillment_context_carries_no_connectivity`. A fresh v0.3.0 database
holds none of the frozen inventory tables an older one may: those are dropped by a
migration after the baseline where present. These files are regenerated only to
correct them against that release; a later floor is a new fixture.
