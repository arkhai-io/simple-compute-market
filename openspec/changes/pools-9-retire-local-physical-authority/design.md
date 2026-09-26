# Design

## Context

Verified against the tree at planning time; re-verify before implementing.

**Two listing sources exist.** `available_compute_slices` in
`domains/vms/listings/reconciler.py` reads the site projection when
`use_site_projection_for_listings` is `true` (the default) and
`_pool_rows_from_local_tables` otherwise. The flag is read in
`services/capacity_client.py` and `services/listing_sources.py`; the
storefront lifecycle loop derives from the same source selection, so retiring
the local path retires it for the loop too.

**The local tables mix physical and commercial columns.**

| Table | Physical columns | Commercial columns |
|---|---|---|
| `resources` | `resource_type`, `resource_subtype`, `unit`, `value`, `state`, `attributes` | `min_price`, `token`, `max_duration_seconds`, `accepted_escrows` — read only by a legacy-resources fallback that is reachable only when `compute_capacity_pools` and `compute_pool_members` are absent, a state no migrated deployment is in |
| `hosts` | all | none; its marketing columns (`cpu_type`, `motherboard`, `host_ram_gb`, `datacenter_grade`, network fields) are unread by publication |
| `compute_pool_members` | all | none |
| `compute_capacity_pools` | `total_gpu_count` | `gpu_model`, `region`, `sla`, `min_price`, `token`, `accepted_escrows`, `settlements`, `max_duration_seconds`, `seller_id`, policy ids |
| `resource_transition_events` | all (audit trail of `resources` mutations) | n/a; existing rows are history and are not deleted |

**The only writer of the local tables is CSV import.**
`SQLiteClient.upsert_resource` → `_sync_compute_pool_for_resource` issues the
one `INSERT … ON CONFLICT` that fills `compute_capacity_pools`, physical and
commercial columns alike. It is reached from
`POST /api/v1/admin/portfolio/resources/import`, the `portfolio import-csv`
command, and startup seeding (`_seed_resources_if_empty` →
`SystemService.seed_resources_if_empty`, sourced from `resources_csv_inline`,
`resources_csv_path`, or `/app/resources.csv`). Helm (`_helpers.tpl`,
`secrets.yaml`, `values.yaml`), compose (`compose/seller.yml`,
`domains/vms/compose.yml`), and the seller quickstart carry that contract.
Seeding silently skips when it finds no source, so an upgraded deployment
with CSV configuration would start with no inventory and no error.

**Two storefront override tiers exist.** The site-scoped store
(`kit/pool-overrides`, keyed by `(site_id, pool_id, offering_mode)`, with
authenticated routes, typed clients, and `market-storefront pool-override
set/show/list/delete`) is the top tier. Beneath it `_tier()` falls back to the
home-site legacy record: `compute_capacity_pools`' commercial columns, read by
`_local_pool_pricing`, keyed by `pool_id` alone. Each field a pool takes from
the legacy record is reported in `legacy_overrides_in_effect` and on system
status. Two legacy fields have no site-scoped equivalent: `region` (the store
forbids it as a physical fact; the pool hint declares it) and
`accepted_escrows` (superseded by `settlements` clauses). The `inactive`
override state exists only for local-table derivation.

**Region, SLA, and pricing have projection equivalents.**
`kit/resource-pools/hints.py` defines the region, SLA, and pricing policy tags,
projected through a pool's `policy_tags` and resolved as a tier by
`_projected_pool_rows`. The legacy record is not filling a projection gap; it
is a second override tier with no write path once the import is gone.

**One deployed storefront depends on the local path.**
`domains/vms/storefront/storefront.alice.toml` sets
`use_site_projection_for_listings = false` because provisioning trusts one
storefront principal; the second storefront in the two-storefront e2e scenario
can load no projection and derives from local tables, where every source is
capacity-backed.

**Multi-dimensional capacity is declarable at the site.** The registration API
and capacity-definition documents accept every dimension a resource names, so
the CSV path is not the only expression of it.

## Goals / Non-Goals

**Goals:** one listing source; no storefront physical authority; one storefront
override tier; no operator contract that fills retired tables; a freeze an
operator can roll back from by reverting code.

**Non-Goals:** a per-pool commercial write path (exists); carrying legacy
values forward; dropping schema; the zero-caller surfaces and the provider
rule (own changes); bare metal.

## Decisions

### Freeze, then redirect; no `DROP`

The migration stops creating and writing the retired tables, columns,
triggers, and indexes and redirects every read to the projection. The schema
stays so a code rollback finds its data. A `DROP` is a later change, after a
deployment cycle shows the freeze never needed reverting. This matches the
additive-only posture of every other schema change in the campaign.

Rollback past this change is a code operation, not a configuration flip;
operator documentation says so explicitly.

### The legacy override tier retires with the import, without carry-over

The legacy record is written only by CSV import and read only by
`_local_pool_pricing`. Retiring the import leaves it write-only-in-the-past,
so it retires with the import. On upgrade a home-site pool that took a field
from it resolves that field from the pool hint, then the configured default.
The operator re-enters any value they want to keep through `pool-override set`
before upgrading; the system-status report already enumerates the pools and
fields.

Alternatives:

- *A gate in the freeze migration*, refusing to run while a legacy row carries
  a non-null commercial column with no site-scoped override for the same pool
  unless acknowledged. Rejected: machinery for a population the status report
  already enumerates; the operator guidance carries the instruction.
- *A preview-first `pool-override import-legacy --site <id>` command* on the
  publication-pricing migration pattern. Rejected: one-shot code, dead after
  it runs, copying a price the operator typed into a CSV once; and two of the
  eight fields cannot be copied — `region` (the store forbids it) and
  `accepted_escrows` (its only conversion is the clause interpretation the
  pricing migration already refuses when ambiguous).
- *Keeping the tier read-only beneath the store.* Rejected: with the write
  path gone the rows can only decay, the physical/commercial mixed table
  survives the change whose purpose is removing it, and `_tier()` keeps two
  levels forever.

Revisit trigger: a seller with many home-site pools reporting that re-entry
through the CLI is impractical. That reopens the import command, not the gate.

Consequences the guidance must state: `region`'s legacy fallback disappears,
so a home-site pool whose region came from the CSV needs `region` declared on
its pool hint before upgrading; `accepted_escrows` has no equivalent other
than a `settlements` clause list.

### The cutover requires provisioning to trust a second storefront principal

Deleting the local path leaves the second e2e storefront with no listing
source, and its scenario cannot be migrated to provisioning-seeded inventory
until provisioning trusts its principal. `repair-multi-storefront-scenario`
owns that. Narrowing the scenario to drop that storefront's inventory, or
giving it a second provisioning service in compose, were both rejected as
working around a scenario the repository intends to repair; storefront
substitutability is the property this consolidation exists to deliver.

The dependency is on the cutover and that one test migration only. The
freeze and the CSV code removal can land first.

### Commercial rows are storefront-owned; the site-scoped store is where they live

`ARCHITECTURE.md`'s authority boundaries assign listing, negotiation, deal,
and seller-policy state to the storefront and pool metadata and provider
configuration to the resource-pool service. Per-pool commercial values are
therefore correctly storefront-owned, and the site-scoped store is the
architecturally right home. This bounds the change: the terminal state is no
*physical* authority in the storefront, not no per-pool rows.

### The contract modification is a replacement, not an amendment

The "Storefront pool overrides are site-scoped and durable" requirement loses
its legacy-record paragraph, its `inactive` state, and two scenarios ("An
override is deleted over a legacy value", "Listings derive from local
tables"). A modified requirement cannot drop scenarios, so the delta removes
it and adds "Storefront pool overrides are the only override tier", carrying
every other paragraph and scenario forward and adding one for a home-site
pool with no override.

### Independent work is not held behind the cutover

The cutover's start trigger is a repository-owner judgment with no fleet-wide
signal to gate on. Work that lands alone — fixing a pool's provider at
creation, and removing the storefront's zero-caller physical surfaces — is
not held behind it; each is its own change.

## Risks / Trade-offs

- **An operator upgrades with legacy values still in effect** → a silent
  commercial change to the hint or configured default. Mitigated by the
  status report and the guidance; accepted rather than gated (see above).
- **An operator upgrades with CSV configuration** → no inventory, no error.
  Mitigated by migration guidance that names the provisioning-side
  declaration path and by the seeding stack's removal making the
  configuration keys unknown.
- **The two-storefront scenario is repaired later than expected** → the
  cutover waits; the freeze and code removal do not.

## Migration Plan

1. Re-verify the confirming searches (legacy-resources fallback
   reachability, the CSV-dependent test set).
2. Retire the local-table path, the flag, the legacy override tier, and the
   `inactive` state; freeze the retired tables and columns.
3. Retire CSV import, the startup seeding stack, the deployment contract,
   and the CLI surface; migrate the seven test files; write operator
   guidance.
4. Freeze-then-redirect migration; run the storefront suites and one e2e run.

Rollback at any step is a code revert; no `DROP` has happened.

## Open Questions

None. The start trigger is a decision outside this document, not an open
design question.
