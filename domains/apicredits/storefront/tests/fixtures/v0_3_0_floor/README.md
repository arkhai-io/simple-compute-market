# The API-credit storefront's v0.3.0 schema

The database the marketplace v0.3.0 release's API-credit storefront database client
builds on a fresh SQLite file, before any store opens: the schema the storefront's
baselines reproduce. Unlike the VM and bare-metal storefronts, the API-credit
storefront adopts no existing database, so `floor_ids.json` records what that release
recorded without its chain naming them as a floor: every existing database is
refused.

- `schema.json` — the database's `market_schema_migrations.schema_snapshot`: every
  table, column, key, index, trigger, and view, the ledger left out.
- `floor_ids.json` — the migration IDs its `schema_migrations` records, in the order
  it recorded them.
- `ddl.sql` — every object's DDL as SQLite stored it, the ledger's included; the
  baselines are written from it.

The release's service code is dev `9fffe41e9`. The database was built from the
release's published wheels rather than from a build of that commit, since a rebuild
may resolve different dependencies than the release shipped. In an isolated
environment:

1. Install `arkhai-apicredits-storefront==0.20.0` from PyPI, with every
   distribution, third-party ones included, constrained to the version
   `domains/apicredits/storefront/uv.lock` names at `9fffe41e9`, and
   `kit/schema-migrations` from this repository for the snapshot.
2. With no configuration, construct the release's
   `apicredits_storefront.utils.sqlite_client.SQLiteClient` on a fresh file, and open
   no store.
3. Write the file's `schema_snapshot` as `schema.json` (sorted keys, two-space
   indent), the ledger's IDs in `rowid` order as `floor_ids.json`, and each
   `sqlite_master` entry's `sql` in `rowid` order as `ddl.sql`.

The release built 26 tables and recorded 20 IDs. These files are regenerated only to
correct them against that release.
