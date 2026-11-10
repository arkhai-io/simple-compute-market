# The registry's v0.3.0 floor

The database the marketplace v0.3.0 release's registry builds when it starts on a
fresh SQLite file: the schema its Alembic chain is supported from, and that its
baseline revision reproduces.

- `schema.json` — the database's `market_schema_migrations.schema_snapshot`: every
  table, column, key, index, trigger, and view, `alembic_version` included.
- `floor_revision.json` — the revision its `alembic_version` records. A database at
  this revision is adopted at the baseline.
- `ddl.sql` — every object's DDL as SQLite stored it, in `rowid` order. The tests
  build a v0.3.0 database from it to prove adoption; the baseline is written from it.

The release's service code is dev `9fffe41e9`; its `core/registry/src/core_registry/db/`,
`core/registry/alembic/` and `core/registry/pyproject.toml` are unchanged since. The
database was built from the release's published wheel rather than from a build of that
commit, since a rebuild may resolve different dependencies than the release shipped. In
an isolated environment on Python 3.13:

1. Install `arkhai-core-registry==0.5.0` from PyPI, with every distribution,
   third-party ones included, constrained to the version `core/registry/uv.lock` names
   at `9fffe41e9` (SQLAlchemy 2.0.44 and Alembic 1.17.2 among them), and
   `kit/schema-migrations` from this repository for the snapshot. Check that the
   installed package's `db/database.py`, `db/models.py`, and `config.py` are the
   commit's.
2. The published wheel carries no Alembic scripts: the release image copied
   `core/registry/alembic` beside the package's source, where `db/database.py` looks
   for it, three directories above the package. Place `9fffe41e9`'s
   `core/registry/alembic` there, at the environment's `lib/python3.13/alembic`.
3. In an empty working directory, with only `DATABASE_URL=sqlite:///<a fresh file>`
   set, run the release's `core_registry.db.database.init_db()`. On a database with
   no tables it runs `Base.metadata.create_all` and then stamps the script head.
4. Write the file's `schema_snapshot` as `schema.json` (sorted keys, two-space
   indent), its one `alembic_version.version_num` as `floor_revision.json`, and each
   `sqlite_master` entry's `sql` in `rowid` order as `ddl.sql`.

The release built 7 tables — `publishers`, `publisher_replay_reservations`,
`api_keys`, `identities`, `publisher_identity_rotations`, `listings`, and
`alembic_version` — and recorded `018_listing_resource_column`. These files are
regenerated only to correct them against that release; a later floor is a new
fixture.
