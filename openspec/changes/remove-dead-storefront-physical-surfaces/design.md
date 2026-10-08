# Design

## Context

Re-grounded against the tree on 2026-10-08. Task 1.1 re-runs every search
before anything is deleted.

**`compute_allocations` is a dead execution ledger.** `kit/site`'s
`CapacityReservation` is the authoritative allocation record. The storefront's
table has no production `INSERT`. Its readers, `held_gpu_counts` and
`held_gpu_counts_by_resource`, together with `allocation_table_exists` and
the `HELD_ALLOCATION_STATES` set only they read, are exported from
`domains/vms/listings` and called by nothing.

One runtime write remains: the release-`UPDATE` in
`SQLiteClient.apply_resource_transition`, which fires whenever a transition
sets a resource `available`. It is reached through `release_reservations`'
local-row loop, which every end-to-end cleanup calls through
`admin_release_reservations`, and through the `PATCH` route below. A
`$.allocation_id`/`$.compute_allocation_id` attribute-path special case
selects one allocation row instead of all of a resource's rows.

Schema code touches the table in five places:

- `_ensure_domain_tables` creates it and its `updated_at` trigger;
  `_ensure_domain_indexes` creates four indexes on it.
- Migration `20260604_001_compute_allocation_callback_metadata` adds
  correlation columns, and migration `20260611_007_allocation_hold_expiry`
  adds `hold_expires_at`. Both use `_add_column_if_missing`, which already
  does nothing when the table is absent, but both still alter an existing
  table.
- Migration `20260604_002_compute_inventory_pools` creates two indexes on it
  without checking that it exists, so it would fail on a fresh database once
  the table is no longer created.
- `_backfill_compute_pools`, called by that migration, updates its pool and
  member columns when the table exists.

The migration engine skips recorded IDs and ignores recorded IDs it no
longer lists.

No test exercises `release_reservations` or the release-`UPDATE`.

**The physical-identity plumbing carries a key that no longer exists.**
`kit/site` names a host `host_id` and its reservation route strips `host_id`
along with the other placement fields. No reservation carries a `vm_host` key,
so `reserved.get("vm_host")` in `fulfill_vm_obligation` is always `None`.
The value travels through three places: that local variable, the
`provision_vm(vm_host=...)` call, and `_do_provision`'s `vm_host` parameter,
whose docstring describes it as a call-site compatibility parameter.
`register_lease`, `schedule_shutdown`, and `_register_vm_lease_with_settings`
no longer exist. The lease window is recorded when the reservation is
committed, and provisioning records the lease target when the fulfillment
becomes active. `test_fulfillment_provisioning.py` passes `vm_host` to
`_do_provision` directly. A comment in `test_capacity_reservation_boundary.py`
still says `vm_host` "is not stripped the same way".

Provisioning has no live `vm_host` either. The VM provisioning adapter names
it only in `legacy_backfill.py`, which reads the retired `vm_leases` table.
This change touches no provisioning or adapter production code.

**The VM expiry hook is gone.** `bare-metal-mock-provisioned-deal` removed
`_do_shutdown`, the `schedule_shutdown` parameter, `ScheduleShutdownFn`,
`_schedule_shutdown_best_effort`, and the module's background-task set
(task 3.8). The lease watchdog performs expiry.

**Two admin routes have no production or executable e2e caller.**
`GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}` and both
clients' `get_resource`/`patch_resource` have no production caller. `PATCH`'s
docstring describes a provisioning `LeaseWatchdog` call that does not exist.
The only call provisioning makes back into the storefront is the signed
service-peer `capacity_released` event, sent to
`/api/v1/admin/fulfillment/events/capacity-released` through
`notify_capacity_released`.

The routes keep further code alive that nothing else uses:

- `SQLiteClient.get_resource`. Its only production callers are the two
  routes; one assertion in `tests/integration/test_settle_controller.py` reads
  a local row with it, beside the site-ledger assertion that proves the
  behavior.
- `_authenticated_patch` on both client variants. `patch_resource` is its
  only caller, and no other storefront route uses `PATCH`.
- The `lease_lifecycle`/`resource_released` stage event the `PATCH` route
  emits. Nothing waits for it.
- The `set_attribute` path through `apply_resource_transition`. With the
  route and `delete_resource` gone, `apply_resource_set_transition` is its
  only caller, `release_reservations` is that wrapper's only caller, and that
  loop sets only a state.

The routes are still referenced in several other places:

- Storefront tests: integration tests in `test_admin_api.py`, the
  administrator authentication mapping in `middleware/admin_identity.py`,
  and `test_identity_dispatch.py`.
- Client tests: the `PATCH` byte-equivalence test in
  `core/storefront-client/tests/test_admin_auth.py`. That file already
  covers generic administrator signing and synchronous/asynchronous parity
  through the market-neutral `authenticated_request` example route (`PUT`,
  `DELETE`, `GET`) and through identity rotation. Removing the `PATCH` test
  loses no generic coverage.
- Provisioning test: `test_ledger_lease_lifecycle.py` gives its mock
  storefront a `patch_resource` and asserts it is never awaited. A
  `MagicMock` makes that assertion vacuous once the method is gone.
- Prose:
  - `release_reservations`' docstring recommends `PATCH` for single-row
    release.
  - Both VM full-deal scenarios' stage `00h` docstrings describe a watchdog
    `PATCH` callback. Their troubleshooting text names an administrator key
    and a `global.adminApiKey` Helm default; the chart render tests assert
    that no administrator shared secret is rendered.
  - The `CapacityReservation` docstring in `kit/site/src/market_site/db.py`
    describes the row by comparison with the storefront's
    `compute_allocations` and a former `PATCH` of the storefront's resource
    table.

**`release_reservations` has a legacy half.** Beside the authoritative
`_release_site_ledger_holds`, a loop normalizes local `resources` rows that
the projection no longer feeds. Local listing derivation remains selectable,
including for the second storefront, so those local rows have not yet lost
their operational role. E2e cleanup calls this endpoint. Its obsolete
watchdog explanation does not prove the local-row loop is unused.

**Four `SQLiteClient` methods have no production caller.** `delete_resource`
and `ensure_default_resources` have no references at all.
`host_capacity_remaining` is referenced only by `tests/unit/test_hosts.py`,
and in two ways:

- `TestCapacityRemaining` exists only to exercise it.
- Three tests in `TestCapacityEnforcement` use it to check the capacity check
  that runs when a resource is upserted (`resource_capacity_validator`). That
  check is live behavior, and it computes its own totals.

The storefront's `list_hosts` has no production caller and one test. Every
other `list_hosts` in the repository belongs to the provisioning host service
or its client.

**`resource_count` is a live diagnostic contract.** `SystemService.get_health`
exposes it on both `HealthResponse` models. The "Operator-visible acceptance
state" requirement in `openspec/specs/storefront-publication/spec.md` requires
it when local resource rows are absent. The smoke test, both VM full-deal
scenarios, `docs/seller-quickstart.md`, and
`docs/development/VALIDATION_RUNBOOK.md` consume it to diagnose CSV seeding.

**The allocation test file contains surviving coverage.**
`test_compute_allocations.py` contains local listing derivation, member
availability, cross-site identity, and negotiation hold-persistence tests
alongside three allocation schema tests. Removing the ledger does not retire
those behaviors.

## Decisions

### A cleanup change removes what its deletions orphan

This change deletes unused functionality. Removing a surface often leaves the
code beneath it unused too, so the removal continues until nothing it leaves
behind is unused. This covers:

- functions and methods whose last production caller is removed here;
- private transport helpers with no remaining caller;
- stage events nothing waits for;
- parameters and branches of a retained function that only removed callers
  supplied.

A test-only reference does not keep production code alive. The test is
rewritten to observe the behavior through a live interface, or it retires
with the code.

It stops at code that still has a live caller. `apply_resource_transition`
remains because `release_reservations`' local-row loop uses it, and that loop
belongs to `pools-9-retire-local-physical-authority`. What remains is narrowed
to the state transition that loop performs. The pass-through
`apply_resource_set_transition` wrapper is folded into it.

The rule applies to code outside the storefront where the removal makes a
reference stale. `test_ledger_lease_lifecycle.py` drops its `patch_resource`
stub, and the `kit/site` `CapacityReservation` docstring describes the row as
it is rather than by contrast with the removed storefront surfaces. No
provisioning or `kit/site` production behavior changes.

### Freeze `compute_allocations`; do not drop it

The campaign's schema posture is additive-only until a deployment cycle
confirms a freeze never needed rolling back. Absence of a current insertion
path does not establish that an operator's historical table is empty. Existing
table contents and schema therefore remain intact. Fresh databases stop
creating the table, and current runtime and migration code stop modifying it.

The freeze has these parts:

- `_ensure_domain_tables` stops creating the table and its trigger, and
  `_ensure_domain_indexes` stops creating its four indexes.
- Migrations `20260604_001_compute_allocation_callback_metadata` and
  `20260611_007_allocation_hold_expiry` exist only to add columns to the
  table. Both are removed from the migration list along with their
  functions.
  - A database that recorded them keeps the record, and the engine ignores
    it. A database that had not applied them never alters the frozen table.
  - Every other migration ID is unchanged, and a removed ID is never reused.
  - Keeping the entries as functions that do nothing was rejected: it adds
    code that records a decision without performing one.
- `20260604_002_compute_inventory_pools` stops creating its two allocation
  indexes, and `_backfill_compute_pools` stops updating allocation rows.
- The release-`UPDATE` and its attribute-path special case leave
  `apply_resource_transition`, so no runtime path writes the table.

A fresh database, a database with an existing allocation table and rows, and
repeated initialization must all satisfy the freeze. `release_reservations`
must succeed on a fresh database and leave existing allocation rows untouched.
The local derivation, member availability, cross-site identity, and
hold-persistence coverage in `test_compute_allocations.py` survives. Its
allocation schema tests are replaced by these freeze assertions.

### Remove the routes rather than deprecate them

Both routes are pre-1.0 and have no production or executable e2e caller.
The accepted decision is to remove them with their models, client methods,
route authentication contracts, and the code beneath them that nothing else
uses. Route-specific tests retire with the routes. Generic administrator
signing and synchronous/asynchronous client parity coverage already runs
through `authenticated_request` and identity rotation, so nothing replaces
the `PATCH` test.

Prose describing the routes is corrected rather than deleted. The two
full-deal stage `00h` docstrings describe the real reverse path: a signed
service-peer `capacity_released` event. Their troubleshooting text names
service-peer identity configuration rather than an administrator key.

Alternatives considered:

- Keep the routes for future e2e state setup. Rejected: modifying a storefront
  resource row does not modify the authoritative site's reservation or
  fulfillment state. Existing site reservation APIs, provisioning lifecycle
  controls, and mock execution gates provide the appropriate scenario seams.
- Deprecate until the local-inventory cutover. Rejected: no running scenario
  relies on either route, and the stale PATCH references are explanatory text
  to correct rather than a compatibility dependency.

Revisit only if a concrete scenario identifies state it must establish that
the authoritative seams cannot express. Before retaining a local
physical-state mutation, review that missing seam and decide who owns it.

### Remove the `vm_host` plumbing where it now lives

The removal follows the code as it stands: the local variable, the
`provision_vm` keyword, and `_do_provision`'s parameter and its
compatibility explanation. Tests stop passing the keyword, and the boundary
test's comment states that no reservation carries a host. Lease registration
at commit and the post-provision deferral paths stay as they are.
`fulfill_vm_obligation`'s committed-claim reads stay as well.

### Retire local cleanup and resource-count diagnosis with local inventory

The user accepted deferring the local-row half of `release_reservations` and
`resource_count` to `pools-9-retire-local-physical-authority`. That change owns
the local listing path, CSV import, scenario seeding, and operator migration.
Their supporting diagnostics and cleanup retire at the same boundary.

Removing both here would require revising the normative resource-count
scenario, smoke and deal assertions, and operator guidance while their local
inventory source still exists. Replacing the diagnostic with projection state
alone would also stop checking whether the CSV importer and storefront use
the same database. Keeping the field but removing cleanup alone would leave
the selectable local path without its existing normalization during cleanup.

The replacement operator diagnostic is a cutover design question for
`pools-9`; this change does not select its response shape or acceptance rule.

### No delta specification

The requirement this work serves is `pools-9-retire-local-physical-authority`'s
and describes the terminal state, which this change reaches only in part. Two
changes adding overlapping requirements to one specification would leave
archival to reconcile them; one owns the requirement and the other removes dead
code toward it. The resource-count requirement and its Evidence entry remain
current until `pools-9` resolves and promotes their replacement.

## Design review disposition

Re-grounded on 2026-10-08. The review accepted three things:

- removal continues to whatever the deletions orphan;
- the two column-only allocation migrations leave the migration list rather
  than becoming functions that do nothing;
- the `kit/site` docstring is corrected here.

`tasks.md` still reflects the earlier tree: its task 3.5 function list, its
rebase note, and its test-ownership notes. Planning amends it to match this
document.

This change's task 3.8 and `pools-9-retire-local-physical-authority`'s task
3.8 are different tasks that share a number. `pools-9` claims only tasks 3.1,
3.2, and 3.5–3.7 from this change, so the shared number causes no ownership
ambiguity.
