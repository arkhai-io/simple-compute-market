# Design

This document is written to stand on its own — `pools-8-capacity-projection-and-listing-hints`,
where this scope was originally investigated, is expected to be archived
(and its documents possibly eventually removed) once its own scope is
complete, independent of when this change is picked up. Findings below
were verified directly against the code during `pools-8`'s own Section 6
work; re-verify anything load-bearing again before implementing, since the
codebase will have moved on by the time this change actually starts.

## Retirement is column-level, not table-level, for two tables

`resources` and `compute_capacity_pools` each mix physical-identity
columns (retirement candidates) with commercial columns that must survive
(pricing, seller policy, accepted escrows) — this change cannot simply
drop either table.

| Table | Physical columns (retirement candidate) | Commercial columns (must survive) |
|---|---|---|
| `resources` | `resource_type`, `resource_subtype`, `unit`, `value`, `state`, `attributes` | `min_price`, `token`, `max_duration_seconds`, `accepted_escrows` — confirmed **dead** in the current default code path as of `pools-8` (read only by the also-dead legacy-resources fallback, itself only reachable when `compute_capacity_pools`/`compute_pool_members` don't both exist — a state no migrated deployment can be in). Reclassified from "must survive" to "retirement candidate" alongside the physical columns; the confirming repo-wide grep for any other reader is this change's own task, not assumed complete from `pools-8`'s planning pass alone. |
| `hosts` | all (pure physical validator input) | none |
| `compute_pool_members` | all (pure physical membership) | none |
| `compute_capacity_pools` | `total_gpu_count` only | `gpu_model` (soft/fallback-only — kept as a resilience fallback for a projection resource missing its own `attributes.gpu_model`; retiring it is optional, not required by this change), `region`/`sla` (**not** retirement candidates — see the correction below), `seller_id`, `pricing_policy_id`, `escrow_policy_id`, `allocation_policy`, `min_price`, `token`, `accepted_escrows`, `max_duration_seconds` |
| `resource_transition_events` | all (audit trail of `resources`' physical-column mutations) | n/a — existing rows are history, not a live concern; must not be deleted even once new events stop |

`hosts`' marketing-only columns (`cpu_type`, `motherboard`, `host_ram_gb`,
`datacenter_grade`, network fields) were checked against the real publish
pipeline during `pools-8` and found already unread — this data was inert
before this change touches anything, not something this change newly
breaks.

### Correction (2026-08-06): why `region`/`sla` survive

The table above previously justified retaining `region`/`sla` on the grounds
that "no projection equivalent exists for either." That is inaccurate as of
`pools-8`. `kit/resource-pools/hints.py` defines `REGION_POLICY_TAG` and
`SLA_POLICY_TAG` with `raw_region`/`sla_value` readers, projected through a
pool's `policy_tags`, and `_projected_pool_rows` already resolves them as a
tier.

The accurate reason these columns survive is different and narrower: they are
the **top-precedence storefront override tier** over a pool's own projected
hint. A projection equivalent exists; the local row is what lets a seller
disagree with it. Retaining them is a commercial-authority decision, not a
gap in the projection.

This matters for implementation because the two justifications imply
different work. "No projection equivalent" would suggest this change owes a
new projection field. It does not — the field exists, and what this change
owes is only the override write path already scoped below.

## Why CSV-import removal needs a replacement write path first

`SQLiteClient.upsert_resource`'s `_sync_compute_pool_for_resource` side
effect is not just a physical-membership sync — the same
`INSERT ... ON CONFLICT` statement it issues against
`compute_capacity_pools` is the *only* place that currently writes
`min_price`/`token`/`max_duration_seconds`/`accepted_escrows` (and
`gpu_model`/`region`/`sla`) at the pool level, sourced from whatever a
resource-level CSV row or admin `upsert_resource` call supplied.
`admin_controller.py` has no other write path to this table. Removing CSV
import without first building a direct replacement silently removes every
operator's only way to set or change pool-level pricing at all — not a
theoretical risk, a certain regression.

The natural shape for that replacement (not yet built, scoped by
`pools-8`'s own task 6.2 but explicitly not implemented there): `PUT`/
`PATCH` admin routes against `compute_capacity_pools`'s surviving columns,
mirroring `kit/resource-pools`'s own `PoolReplace`/`PoolUpdate` shape (the
individual-pool admin API `pools-8` built out in its own Section 5). One
open scope question to resolve before implementing, not assumed either
way: does an operator need to *create* a new `compute_capacity_pools` row
through this endpoint, or only edit one that already exists structurally?
Depends on whether anything still triggers row creation once
`_sync_compute_pool_for_resource` (this endpoint's predecessor) is gone —
check the projection's own pool-discovery behavior directly before
assuming either answer.

## Freeze-then-redirect, not a `DROP`, in this change

A rollback path requires the previous reader's data to still exist. This
change's own migration work should stop at freezing writes to the
retiring physical columns/tables and redirecting reads to the projection,
without dropping the underlying schema in the same migration — matching
every other schema change in the POOLS campaign being additive-only. A
genuine `DROP`/column removal belongs in a further follow-up after a full
deployment cycle confirms the freeze itself was never rolled back.

Concretely: a rollback past this change means restoring the removed code
paths from version control, not flipping a config value — this change's
own local-table code deletion (not just the flag flip `pools-8` already
did) is what makes rollback a code operation rather than a config one.
Document this explicitly for operators (in whatever this repository's
deployment documentation lives, or a new scenario on the
`storefront-publication` requirement this change's own retirement
promotes into) rather than leaving it implicit.

## Goal 1 sweep findings (2026-08-06)

A full inter-service sweep of the storefront's remaining physical-resource
concerns was run as roadmap Goal 1 analysis. Findings below are recorded with
their evidence because most are not obvious from reading any one file, and
several contradict what the surrounding docstrings claim. Re-verify before
implementing; the codebase will have moved on.

### The open scope question from this document is now answered

This design previously left open: does the pool-commercial-metadata admin
endpoint need pool *creation*, or only editing an existing row? Resolved
(repository owner, 2026-08-06) as neither exactly.

The *table* is created at service initialization, as it already is. *Rows* are
not created by anything once `_sync_compute_pool_for_resource` is gone, and
many storefronts are expected to have none at all — a seller who accepts every
site's projected hints never needs an override row. So the endpoint is an
**upsert against a projected pool**: it creates or replaces an override row for
a pool that already exists structurally in the projection. It never creates a
pool.

That resolution removes work rather than adding it. The three-tier resolver in
`domains/vms/listings/pricing_resolution.py` already treats an absent override
row as "this tier has no opinion" and falls through per field, so the
absent-row case needs no new handling — only tests proving it.

### `compute_allocations` is a dead execution ledger

`kit/site`'s `CapacityReservation` model docstring states that it "merges the
storefront's `compute_allocations` shape with the lease fields previously
duplicated into `vm_leases`" and that on release the watchdog "updates *this*
row locally and emits events, instead of PATCHing the storefront's resource
table." The replacement is therefore already in production and self-documented.

The storefront side was never removed:

- No production code inserts into `compute_allocations`. The only `INSERT` in
  the repository is in `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py`.
- The only production writer is a release-`UPDATE` inside
  `SQLiteClient.apply_resource_transition`, reached when a resource transitions
  to `available`.
- Its readers, `held_gpu_counts` and `held_gpu_counts_by_resource` in
  `domains/vms/listings/reconciler.py`, are exported from that package's
  `__init__.py` and have no caller. `held_gpu_counts_by_resource` calls
  `held_gpu_counts`, which nothing calls.

So the table accumulates no rows, and the code that would read them cannot run.
It retires as a unit with its trigger, its four indexes, and the columns
`migrations.py` adds to it.

### Physical identity threaded across the service boundary is provably `None`

`vm_fulfillment_service.py` reads `reserved_vm_host = reserved.get("vm_host")`
immediately after a comment stating that `vm_host` "is unconditionally stripped
from the reservation response (`kit/site`'s opaque-reservation boundary)" and
that the value "is therefore always None." The comment then records why it was
kept: removing it "from every call site is a larger signature change than
stripping it from the API response requires."

That larger signature change is this change's work. The parameter is threaded
through `register_lease`, `schedule_shutdown`, `provision_vm`, `_do_provision`,
and `_register_vm_lease_with_settings`, each of which documents it as an
accepted-but-unused compatibility parameter.

Note the boundary carefully: `vm_host` inside the provisioning adapter is
legitimate and stays. It is the real execution target, read by
`ansible_service.py` for SSH port and tenant-user extraction. What retires is
the storefront's threading of a value it can never have.

### Two admin endpoints have outlived their only caller

`GET` and `PATCH /api/v1/admin/portfolio/resources/{resource_id}` have no
production caller anywhere; every reference outside the controller itself is a
test. `PATCH`'s docstring names its primary use case as "the provisioning
service's `LeaseWatchdog` calls this with `{"state": "available", ...}` when a
VM has been cleaned up."

That call no longer exists. The provisioning service's only reverse call to the
storefront is `StorefrontLifecycleEventSink.deliver`, which handles exactly one
event kind, `capacity_released`, and raises on anything else. The
`CapacityReservation` docstring quoted above states the same fact from the
other side.

`release_reservations`' docstring repeats the same stale claim and points
operators at `PATCH` as the "surgical" alternative. Its authoritative half
(`_release_site_ledger_holds`) is already correct; only the local-row
normalization loop after it retires.

### CSV retirement is a deployment-contract break

The original scope treated CSV import as code. It is also an operator contract
with a startup path and deployment wiring the original scope did not name:

- `startup.py`'s `_seed_resources_if_empty`, registered as the `seed_resources`
  startup step, calling `SystemService.seed_resources_if_empty`.
- Config keys `resources_csv_inline` and `resources_csv_path`, plus a
  `_DEFAULT_CSV_PATH = "/app/resources.csv"` auto-discovery constant, documented
  in `groups/config.py`.
- Helm: `_helpers.tpl` renders both keys, `secrets.yaml` carries
  `resourcesCsvInline`, `values.yaml` documents `--set-file`.
- Compose: `compose/seller.yml` mounts `${SELLER_RESOURCES_CSV:-../resources.csv}`
  at `/app/resources.csv`; `domains/vms/compose.yml` mounts a fixture there twice.
- `docs/seller-quickstart.md` and `docs/bare-metal-seller-quickstart.md`
  reference the CSV workflow.

An operator who upgrades past this change with a CSV-configured deployment gets
a storefront with no inventory and no error, because seeding silently skips when
it finds no source. That makes migration guidance part of the change, not a
follow-up.

### Dead methods confirmed by exhaustive search

`SQLiteClient.delete_resource` and `ensure_default_resources` have **zero**
references in the repository, including tests. `host_capacity_remaining` is
referenced only by `tests/unit/test_hosts.py`. The storefront's `list_hosts`
has no production caller; every `list_hosts` hit outside it belongs to the
provisioning adapter's own host service or its client.

`host_capacity_remaining` is worth one note: it computes remaining host capacity
across `gpu_count`, `vcpu_count`, `ram_gb`, and `disk_gb` by summing
`resources` rows. It is the clearest surviving evidence that the storefront's
retiring CSV path was the system's only multi-dimensional capacity expression —
which is what makes `capacity-resource-administration` a prerequisite rather
than a parallel improvement.

### Scope boundary confirmed: commercial rows are not residue

`ARCHITECTURE.md`'s authority-boundaries table assigns listing, negotiation,
deal, and seller policy state to the storefront, and resource-pool metadata and
provider configuration to the resource-pool service. `compute_capacity_pools`'
commercial columns are therefore correctly storefront-owned, and a storefront
write path for per-pool commercial values is the architecturally right answer
rather than a workaround for a missing projection field.

This bounds the change: Goal 1's terminal state for the storefront is no
*physical* authority, not no per-pool rows. (2026-09-25: the write path is
`kit/pool-overrides`, keyed by site; the per-pool rows that survive are the
site-scoped store's, and the legacy `compute_capacity_pools` columns retire
with the import that wrote them. See "Re-grounding" below.)

### Out of scope, recorded so it is not double-claimed

`deal_event_sink.py`'s `offering_mode=str(reservation.get("offering_mode") or "vm")`
was the implicit VM executor fallback `market-platform-compute-40-multi-domain-proof`
required removing. **No longer applicable (2026-09-25):** the sink now refuses
to publish a capacity release without `offering_mode` rather than defaulting
it. Nothing here or in that change owes it.

## Publication command changes made by `unbacked-listing-publication` (recorded 2026-09-23)

`unbacked-listing-publication` moves VM publication into a storefront lifecycle loop and
reduces `market-storefront publish` to a typed-client front end. Three consequences
reach this change:

- `publish --inventory` is removed. CSV import remains reachable only through
  `POST /api/v1/admin/portfolio/resources/import`, which this change still retires.
- `--settlement` and `--max-duration-seconds` are removed, because reconciliation cannot
  re-derive a term supplied by one process's arguments. The storefront per-pool override
  row (`compute_capacity_pools`' commercial columns) is now the only storefront-side way
  to set settlement clauses for one pool without editing configuration, which makes the
  override upsert endpoint this document scopes the operator's runtime path for that. Its
  write path remains this change's.
- The publication loop derives from the same source selection as before, including the
  local-table path while `use_site_projection_for_listings` is false. Retiring that path
  retires it for the loop too; no separate work is needed there.

## Cross-references this change should re-establish, since they currently only exist in `pools-8`'s own documents

- The pricing-config family-grouped shape (`[pricing.defaults.gpu.<model>]`)
  `pools-8` built mirrors `structured-capacity-requirements`'s own
  family-grouped requirement shape. If this change's new admin endpoint
  needs to extend pricing beyond the `gpu` family, that still depends on
  `structured-capacity-requirements`'s own vocabulary having landed and
  stabilized first — re-confirm this dependency is still recorded in that
  change's own documents (not only here) before relying on it.
- The six e2e scenario files' CSV dependency was confirmed by direct
  search during `pools-8`'s own Section 6 design pass (2026-08-05); their
  contents may have changed by the time this change starts — re-confirm
  the same search rather than trusting this list unchanged.

## Storefront override endpoint superseded by `publish-multidimensional-listing-shape` (recorded 2026-09-24)

`publish-multidimensional-listing-shape` builds the storefront's per-pool override
write path as a new site-scoped store, keyed by `(site_id, pool_id)`, with
authenticated administrator routes, typed clients, and a CLI. The `PUT`/`PATCH`
endpoint over `compute_capacity_pools`' commercial columns that "Why CSV-import
removal needs a replacement write path first" scopes is therefore no longer this
change's to build, and the prerequisite that section names is met by that change.

What remains here:

- `compute_capacity_pools`' commercial columns stay the lower storefront-override tier,
  consulted for home-site pools only, beneath the site-scoped store.
- They remain so for as long as the resource import writes them. This change retires
  the import and that tier together.
- It still owes a decision on whether any legacy commercial values are carried into
  the site-scoped store when the tier is retired.
  - A migration cannot attribute a legacy row to a site without reading live
    configuration.
  - An explicit, preview-first command that names the site is the pattern this
    repository uses for such cutovers.

## Re-grounding (2026-09-25)

Every finding above was re-checked against the tree on 2026-09-25. The
retirement targets are all still present: the flag and both of its readers,
`_pool_rows_from_local_tables` and its three feeders, both CSV importers, the
import route and CLI, the startup seeding step and its settings, the Helm and
compose wiring, and the seven CSV-dependent test files. What has moved is
around them.

### The override write path was built elsewhere

`publish-multidimensional-listing-shape` (archived 2026-09-25) delivered the
per-pool override write path as `kit/pool-overrides`: a durable store keyed by
`(site_id, pool_id, offering_mode)`, authenticated administrator routes, typed
clients, and `market-storefront pool-override set/show/list/delete`. Its
precedence is already normative in `storefront-publication`'s "Storefront pool
overrides are site-scoped and durable": the site-scoped value wins field by
field over the home-site legacy record, and system status names each field a
pool still takes from the legacy record (`legacy_overrides_in_effect`).

So "Why CSV-import removal needs a replacement write path first" is satisfied,
and the `PUT`/`PATCH` endpoint scoped there and in the former Section 1 is not
this change's to build. What remains is the tier beneath the store.

### Decision: retire the legacy override tier without carrying values over

The legacy tier is `compute_capacity_pools`' commercial columns, written only
by `_sync_compute_pool_for_resource` from CSV import and read only by
`_local_pool_pricing` for home-site pools. Retiring the import leaves it
write-only-in-the-past, so it retires with the import. The question the
2026-09-24 addendum left open was whether its values are carried into the
site-scoped store first.

**Decided: no carry-over.** On upgrade a home-site pool that still took a
field from a legacy row resolves that field from the pool's own hint, then the
configured default. The operator re-enters any value they want to keep
through `pool-override set` before upgrading, and the system-status report
already tells them exactly which pools and fields those are.

Alternatives considered:

- *A gate in the freeze migration* refusing to run while a legacy row carries
  a non-null commercial column with no site-scoped override for the same
  pool, unless explicitly acknowledged. Rejected as machinery for a
  population the status report already enumerates; the operator guidance in
  task 5.5 carries the instruction instead.
- *A preview-first `pool-override import-legacy --site <id>` command*,
  following the publication-pricing migration precedent. Rejected: it is
  one-shot code dead the day after it runs, copying a price the operator
  typed into a CSV once; and two of the eight fields cannot be copied at all
  (`region`, which the store forbids because it is a physical fact, and
  `accepted_escrows`, whose only conversion is the clause interpretation the
  pricing migration already refuses when ambiguous).
- *Keeping the tier read-only beneath the store* (what task 4.3 said until
  today). Rejected: the write path is gone so the rows can only decay, the
  physical/commercial mixed table survives the change whose purpose is
  removing it, and `_tier()`'s two-level precedence stays forever.

**Revisit trigger:** a seller with many home-site pools reporting that
re-entry through the CLI is impractical. That would reopen the import-legacy
command, not the gate.

**Consequence to state in guidance:** `region`'s legacy fallback disappears.
A home-site pool whose region came from the CSV and whose pool hint declares
none publishes with no region after the upgrade; such a pool needs `region`
declared on its hint first. Likewise `accepted_escrows` has no site-scoped
equivalent other than a `settlements` clause list.

Contract consequences: the "Storefront pool overrides are site-scoped and
durable" requirement loses its legacy-record paragraph, its `inactive`
state (which only local-table derivation produced), and its two scenarios
"An override is deleted over a legacy value" and "Listings derive from local
tables". OpenSpec refuses a modification that drops scenarios, so the delta in
`specs/storefront-publication/spec.md` removes the requirement and adds
"Storefront pool overrides are the only override tier" in its place, with
every other paragraph and scenario carried forward unchanged.

### A prerequisite this change did not know it had

`domains/vms/storefront/storefront.alice.toml` sets
`use_site_projection_for_listings = false` with the reason in its comment:
provisioning trusts one storefront principal, Bob, so Alice never loads a
projection and would derive no listing at all from one; she derives from local
tables, where every source is capacity-backed. Section 4 deletes exactly that
path, and task 5.6's migration of `test_multi_registry.py` to
projection seeding needs Alice's storefront to be a trusted caller of
provisioning.

`repair-multi-storefront-scenario` owns letting provisioning serve more than
one storefront. It is now a blocking dependency of Section 4 and of 5.6 for
that file. Narrowing the scenario to drop Alice's inventory, or giving her a
second provisioning service in compose, were both considered and rejected as
working around a test the repository already intends to repair; the
substitutability that scenario demonstrates is the property Goal 1 names as
the value of this consolidation.

### The implicit VM executor fallback is gone

`deal_event_sink.py` now raises `capacity release cannot be published without
offering_mode`. The non-goal that disclaimed removing it, and the
"Out of scope" paragraph above, are struck. `market-platform-compute-40-multi-domain-proof`
still lists the fallback as its own work and is corrected separately.

### `capacity-resource-administration` has landed

Archived 2026-09-21. It delivered digest-gated capacity-definition import and
a composition-supplied mirror dimension, so multi-dimensional capacity is
declarable at the site authority and the CSV path is no longer the only
expression of it. The gate is met; the start trigger for the cutover remains
a repository-owner judgment, as before.

### Two sections split out

Section 0 (a pool's provider is fixed at creation) is a provisioning-side
authority rule with no storefront in it, and Sections 2–3 (the
`compute_allocations` ledger, the always-`None` `reserved_vm_host` threading,
the orphaned resource admin routes, the legacy half of `release_reservations`,
and four zero-caller methods) are all independent of the projection cutover.
Neither had a reason to wait on a start trigger that is undefined by design.
They are now `fix-resource-pool-provider-at-creation` and
`remove-dead-storefront-physical-surfaces`; their evidence sections above
("`compute_allocations` is a dead execution ledger", "Physical identity
threaded across the service boundary is provably `None`", "Two admin
endpoints have outlived their only caller", "Dead methods confirmed by
exhaustive search") remain here as the record of where they were found, and
are cited by those changes rather than duplicated.

Section 0's provider rule can follow the pattern `_require_backing_unchanged`
now establishes in `ResourcePoolService` for the immutable backing
declaration: the same refusal shape, applied to `provider`.

### Smaller drift

- `cli_publish.py` no longer reads the flag or carries `_import_csv`;
  `listing_sources.py` is the second reader. `unbacked-listing-publication`
  removed `publish --inventory`, `--settlement`, and `--max-duration-seconds`.
- The import script is at `domains/vms/storefront/scripts/import_resources_csv.py`.
- `add-development-roadmap` (archived 2026-09-04) established roadmap
  currency; task 7.5 no longer needs to condition on it.
- The delta spec's replacement requirement previously copied the
  pre-`project-capacity-resources-without-hosts` wording ("host-granular");
  it now carries the current text ("resource-granular … each pool provider's
  host requirement") so archival does not regress it.
