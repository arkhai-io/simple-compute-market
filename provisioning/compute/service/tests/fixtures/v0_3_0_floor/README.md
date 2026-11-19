# Compute provisioning's v0.3.0 floor

The database the marketplace v0.3.0 release's own `compute-provisioning-migrate`
builds on a fresh SQLite file: the schema the service's migration chain is supported
from, and that its baselines reproduce.

- `schema.json` — the database's `market_schema_migrations.schema_snapshot`: every
  table, column, key, index, trigger, and view, the ledger left out.
- `floor_ids.json` — the migration IDs its `schema_migrations` records, in the order
  it recorded them. A database recording all of them is adopted at the baseline.
- `ddl.sql` — every object's DDL as SQLite stored it, the ledger's included. The
  tests build a v0.3.0 database from it to prove adoption; the baselines are written
  from it.

The release's service code is dev `9fffe41e9` (`main` at `d595f0c2e` holds the same
tree). The database was built from the release's published wheels rather than from a
build of that commit, since a rebuild may resolve different dependencies than the
release shipped. In an isolated uv project:

1. Install `arkhai-compute-provisioning-service[adapters]==0.24.0` from PyPI, with
   every distribution, third-party ones included, constrained to the version
   `provisioning/compute/service/uv.lock` names at `9fffe41e9` (SQLAlchemy 2.0.51
   among them), and `kit/schema-migrations` from this repository for the snapshot.
2. Run the release's `compute-provisioning-migrate` with only
   `PROVISIONING_DATABASE_URL=sqlite:///<a fresh file>` set, no profile.
3. Write the file's `schema_snapshot` as `schema.json` (sorted keys, two-space
   indent), the ledger's IDs in `rowid` order as `floor_ids.json`, and each
   `sqlite_master` entry's `sql` as `ddl.sql`.

The release built 23 tables and recorded 43 IDs, ending at
`20261106_001_reservation_activated_at`. These files are regenerated only to
correct them against that release; a later floor is a new fixture.
