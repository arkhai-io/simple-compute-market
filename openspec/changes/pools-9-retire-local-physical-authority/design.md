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
| `compute_capacity_pools` | `total_gpu_count` only | `gpu_model` (soft/fallback-only — kept as a resilience fallback for a projection resource missing its own `attributes.gpu_model`; retiring it is optional, not required by this change), `region`/`sla` (**not** retirement candidates — no projection equivalent exists for either; `_projected_pool_rows` reads them from this table as the top-precedence override tier of the hint mechanism `pools-8` built, and will continue to need a source for that tier after this change lands), `seller_id`, `pricing_policy_id`, `escrow_policy_id`, `allocation_policy`, `min_price`, `token`, `accepted_escrows`, `max_duration_seconds` |
| `resource_transition_events` | all (audit trail of `resources`' physical-column mutations) | n/a — existing rows are history, not a live concern; must not be deleted even once new events stop |

`hosts`' marketing-only columns (`cpu_type`, `motherboard`, `host_ram_gb`,
`datacenter_grade`, network fields) were checked against the real publish
pipeline during `pools-8` and found already unread — this data was inert
before this change touches anything, not something this change newly
breaks.

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
