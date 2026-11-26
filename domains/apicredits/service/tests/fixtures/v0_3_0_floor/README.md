# The API-credit service's v0.3.0 floor

The database the marketplace v0.3.0 release's API-credit service builds at startup on a
fresh SQLite file: the schema the service's chain is supported from.

- `schema.json` — the database's `market_schema_migrations.schema_snapshot`: every
  table, column, key, index, trigger, and view, the ledger left out.
- `floor_ids.json` — the migration IDs its `schema_migrations` records, in the order
  it recorded them. A database recording all of them is adopted at the baseline.
- `ddl.sql` — every object's DDL as SQLite stored it, the ledger's included: what a
  v0.3.0 database is built from to prove adoption.

The service's baselines reproduce this schema but for one index: the site ledger's
baseline names `uq_capacity_buckets_host_id`, a unique index on a capacity bucket's
host that the table's own `UNIQUE (host_id)` already enforces, which the release built
from its models without. A migration after the baseline, the site ledger's
`20261126_001_capacity_bucket_host_index`, gives an adopted database that index.

The release's service code is dev `9fffe41e9`. The database was built from the
release's published wheels rather than from a build of that commit, since a rebuild
may resolve different dependencies than the release shipped. In an isolated
environment:

1. Install `arkhai-apicredits-service==0.7.0` from PyPI, with every distribution,
   third-party ones included, constrained to the version
   `domains/apicredits/service/uv.lock` names at `9fffe41e9`, and
   `kit/schema-migrations` from this repository for the snapshot.
2. With no configuration file and no `APICREDITS_` environment, run the release's
   startup schema path, `apicredits_service.db.database.run_migrations`, over an engine
   from its `create_db_engine` on a fresh file. That path builds the service's, the
   resource pools' and the site ledger's tables from their models, inserts the
   `default` pool, and records the service's own migration IDs.
3. Write the file's `schema_snapshot` as `schema.json` (sorted keys, two-space
   indent), the ledger's IDs in `rowid` order as `floor_ids.json`, and each
   `sqlite_master` entry's `sql` in `rowid` order as `ddl.sql`.

The release built 9 tables and recorded 7 IDs, from
`20260731_001_apicredits_schema_baseline` to `20261106_007_reservation_activated_at`.
These files are regenerated only to correct them against that release.
