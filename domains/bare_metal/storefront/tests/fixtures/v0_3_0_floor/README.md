# The bare-metal storefront's v0.3.0 floor

The database the marketplace v0.3.0 release's bare-metal storefront database client
builds on a fresh SQLite file, before any store opens: the schema the storefront's
chain is supported from, and that its baselines, with the store-open migration's
tables set aside, reproduce.

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

1. Install `arkhai-bare-metal-storefront==0.27.0` from PyPI, with every
   distribution, third-party ones included, constrained to the version
   `domains/bare_metal/storefront/uv.lock` names at `9fffe41e9`, and
   `kit/schema-migrations` from this repository for the snapshot.
2. With no configuration, construct the release's
   `arkhai_bare_metal_storefront.sqlite_client.SQLiteClient` on a fresh file, and
   open no store.
3. Write the file's `schema_snapshot` as `schema.json` (sorted keys, two-space
   indent), the ledger's IDs in `rowid` order as `floor_ids.json`, and each
   `sqlite_master` entry's `sql` in `rowid` order as `ddl.sql`.

The release built 28 tables and recorded 37 IDs, ending at
`bare-metal-storefront-0015-opening-listings`. The lifecycle cursor the release
created when its lifecycle store opened is not among them, and neither is the frozen
`bare_metal_accepted_site_generations` an older database may hold. These files are
regenerated only to correct them against that release; a later floor is a new
fixture.
