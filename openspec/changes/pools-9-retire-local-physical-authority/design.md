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
commercial columns are therefore correctly storefront-owned, and the admin
endpoint this change builds is the architecturally right answer rather than a
workaround for a missing projection field.

This bounds the change: Goal 1's terminal state for the storefront is no
*physical* authority, not no per-pool rows.

### Out of scope, recorded so it is not double-claimed

`deal_event_sink.py`'s `executor_kind=str(reservation.get("executor_kind") or "vm")`
is the implicit VM executor fallback `market-platform-compute-40-multi-domain-proof`
requires removing. It sits near this change's surfaces; it belongs to that
change.

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
