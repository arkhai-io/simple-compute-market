# The VM storefront's upgraded v0.3.0 database

A database the marketplace v0.2.29 release's VM storefront built on a fresh SQLite
file, which the marketplace v0.3.0 release's storefront then ran on: the database a
deployment that reached the floor by upgrading holds, before any store opened. Its
ledger records every ID of the v0.3.0 floor (`../floor_ids.json`) and the seven
migrations every v0.2.x release applied that v0.3.0 retired, which the storefront's
chain sets aside at adoption.

- `schema.json` — the database's `market_schema_migrations.schema_snapshot`, the
  ledger left out.
- `recorded_ids.json` — the migration IDs its `schema_migrations` records, in the
  order they were recorded.
- `ddl.sql` — every object's DDL as SQLite stored it, the ledger's included: what an
  upgraded database is built from to prove adoption.

v0.2.29's chains carry every VM storefront migration ID any v0.2.x release recorded
that v0.3.0 does not, so this one database covers the retired set.

## How it was built

Each release ran in an isolated environment, with no configuration file and no
`STOREFRONT_` environment, constructing the release's
`market_storefront.utils.sqlite_client.SQLiteClient` on the file with its
one-registration VM registry,
`build_vm_storefront_registry(build_vm_storefront_domain())`, and opening no store.

1. **marketplace v0.2.29** (`arkhai-vms-storefront` 0.3.5), built from the
   `marketplace-v0.2.29` tree. The release built only the VM storefront's image, from
   that tree, and the 0.3.5 wheel on PyPI cannot be installed, since it pins
   `arkhai-kit-capacity-publication==0.1.0` and `arkhai-kit-storefront==0.1.0`, which
   PyPI never held. The storefront and every other internal distribution the
   storefront's lock at that tag takes from the repository's wheels were built from
   the tree at the version the lock names, and installed with every third-party
   distribution constrained to that lock. The one internal distribution the tree does
   not build, `arkhai-hosted-settlement-client`, was installed from PyPI at 0.4.2, the
   version the tree's projects pin, where the lock names 0.4.0.
2. **marketplace v0.3.0** (`arkhai-vms-storefront` 0.27.0, service code dev
   `9fffe41e9`), installed from PyPI with every distribution constrained to the version
   `domains/vms/storefront/uv.lock` names at `9fffe41e9`, and run over the same file.

The files were then written with `kit/schema-migrations` from this repository, as
`../README.md` gives them: the snapshot as `schema.json` (sorted keys, two-space
indent), the ledger's IDs in `rowid` order as `recorded_ids.json`, and each
`sqlite_master` entry's `sql` in `rowid` order as `ddl.sql`.

v0.2.29 recorded 21 IDs; after v0.3.0 the database holds 33 tables and records 36 IDs.

## What it holds that a fresh v0.3.0 database does not

- The inventory tables earlier releases kept — `compute_allocations`,
  `compute_capacity_pools`, `compute_pool_members`, `hosts`,
  `resource_transition_events` and `resources` — and the triggers on them, which a
  migration after the baseline drops.
- `derived_compute_listings`, the listing-to-site mapping `storefront_listing_bindings`
  replaced, which a migration after the baseline drops.
- `negotiation_threads` with `agreement_bytes` and `settlement_data` as its last
  columns, which v0.3.0 appended with `ALTER TABLE` to the table v0.2.29 created; a
  fresh database holds them mid-table. Every read and write of the table addresses its
  columns by name, so the order is harmless, and the chain test compares that table's
  columns by name.

These files are regenerated only to correct them against those releases; a later floor
is a new fixture.
