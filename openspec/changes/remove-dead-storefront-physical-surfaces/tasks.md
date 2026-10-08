# Tasks

Sections 2 and 3 keep the numbering they have in
`pools-9-retire-local-physical-authority`, which points here.

Design review narrowed the scope: former tasks 3.3 and 3.4 belong to
`pools-9-retire-local-physical-authority`. The 2026-10-08 re-grounding amended
the plan to the current tree and to three decisions in `design.md`:

- removal continues to whatever the deletions orphan;
- the two column-only allocation migrations leave the migration list;
- the `kit/site` docstring is corrected here.

Task 3.8 was delivered earlier by another change and is preserved as it was
recorded.

## Validation environment

Suites ran on 2026-10-08 after `make dist`. The storefront environment could
not run `make reinit`, because this environment's network policy blocks
`download.pytorch.org`, the index for the storefront's optional `rl` extra.
Instead it was synced from its committed lock with
`uv sync --frozen --find-links ../../../.dist`, reinstalling every
lock-derived internal package. Imports confirmed the fresh wheels, and the
suites ran with `pytest` directly, using the Makefile's environment variables.
The other projects used their own Makefile targets.

| Suite | Result |
|---|---|
| `domains/vms/storefront` unit | 1061 passed, 1 skipped |
| `domains/vms/storefront` integration | 382 passed, 2 failed; see below |
| `core/storefront-client` (`make test`) | 60 passed |
| `kit/site` (`make test`) | 281 passed |
| `provisioning/compute/service` (`make test-unit`) | 677 passed |

The two storefront integration failures are `tests/integration/test_alkahest.py`'s
`test_rust` and `test_python`. They need a host Node.js, Rust, and
Foundry/Anvil toolchain this environment lacks ("could not spawn node"). They
exercise none of this change's code and count as unrun.

`ruff check --select F` over every changed Python file reports seven
findings, and all seven exist unchanged on the base commit.

## 1. Re-confirm

- [x] 1.1 Re-ran the confirming searches in `design.md`'s Context; there was no
      drift. Nothing inserts into `compute_allocations`. The only callers of
      `apply_resource_set_transition` were `release_reservations` and
      `delete_resource`. No `kit/site` reservation response carries `vm_host`.

## 2. Retire `compute_allocations`

- [x] 2.1 Removed `HELD_ALLOCATION_STATES`, `allocation_table_exists`,
      `held_gpu_counts`, and `held_gpu_counts_by_resource` from
      `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`, along with
      their exports.
- [x] 2.2 `apply_resource_transition` no longer touches `compute_allocations`,
      and the `$.allocation_id`/`$.compute_allocation_id` special case is
      gone.
- [x] 2.3 Froze the table. No `DROP`.
      - `sqlite_client.py` no longer creates the table, its trigger, or its
        four indexes.
      - `migrations.py` no longer lists
        `20260604_001_compute_allocation_callback_metadata` or
        `20260611_007_allocation_hold_expiry`, and their functions are gone.
      - Migration `002` no longer creates allocation indexes, and the pool
        backfill no longer updates allocation rows.
- [x] 2.4 Added `tests/integration/test_compute_allocations_freeze.py`.
      - A fresh database has no allocation schema and no retired ID.
      - For each of the three recorded histories (both IDs, `001` only, and
        neither, each seeded in its era's table shape), two initializations
        leave the table, index, and trigger definitions, the rows, and the
        retired IDs' history byte-identical.
      - A release transition writes no allocation row.

      Against the pre-change schema code, 5 of its 6 cases fail. The fresh
      transition case passes either way, because a fresh table has no rows.
      The unit file lost its two allocation schema tests and the allocation
      assertions in its pre-compute-inventory test.
- [x] 2.5 Added `TestReleaseReservations` to `tests/integration/test_admin_api.py`.
      It uses the canonical `StorefrontClient` over `httpx.ASGITransport` and
      calls `admin_release_reservations()`. It checks three things:
      - held rows are released on a database without the ledger, and rows in
        other states are left alone;
      - a second call releases nothing;
      - an existing allocation ledger is left untouched.
- [x] 2.6 Ran the storefront suites; see the validation environment above.

## 3. Remove dead physical surfaces

Tasks 3.3 and 3.4 are transferred scope, not deletions this change authorizes.

- [x] 3.1 Deleted `delete_resource`, `ensure_default_resources`,
      `host_capacity_remaining`, and `list_hosts`. In `tests/unit/test_hosts.py`:
      - `TestCapacityRemaining` and the `list_hosts` test are gone.
      - The three capacity-check tests that used `host_capacity_remaining`
        now assert the `CapacityExceededError` violations, including
        `used_excluding_this`.
      - `get_host`, `_HOST_COLUMNS`, and `_host_row_to_dict` remain for
        `resource_capacity_validator`.
- [x] 3.2 Removed the routes and everything only they used:
      - both routes, their models and administrator contracts, and the
        `resource_released` stage event;
      - both clients' `get_resource`, `patch_resource`, and
        `_authenticated_patch`;
      - their tests in `test_admin_api.py`, `test_identity_dispatch.py`, and
        `core/storefront-client/tests/test_admin_auth.py`.

      Corrected the prose that described them:
      - `release_reservations`' docstring;
      - both full-deal stage `00h` docstrings and assertion messages, which
        now describe the `capacity_released` path and service-peer identity
        troubleshooting;
      - the provisioning chart's `storefront` values comment.
- [ ] ~~3.3 Remove the legacy local-row normalization loop from
      `release_reservations`.~~ Transferred to
      `pools-9-retire-local-physical-authority`: local inventory cleanup retires
      with the local listing path.
- [ ] ~~3.4 Remove `resource_count` and its resource-count diagnosis
      documentation.~~ Transferred to `pools-9-retire-local-physical-authority`:
      the permanent scenario, e2e assertions, and operator guidance remain
      current until the local-inventory cutover.
- [x] 3.5 Removed `reserved_vm_host`, the `provision_vm` keyword, and
      `_do_provision`'s `vm_host` parameter.
      - The provisioning-call test asserts that no `vm_host` keyword reaches
        `provision_vm`.
      - `test_two_phase_reserve.py`'s reservation double no longer carries
        `vm_host`.
      - `test_capacity_reservation_boundary.py` asserts that `host_id` is
        stripped along with the other placement fields, and its comments say
        so.
- [x] 3.6 The diff of `fulfill_vm_obligation` only removes lines. Its
      committed-claim reads and commit-time lease window are unchanged.
- [x] 3.7 The storefront and `core/storefront-client` suites and
      `tests/unit/test_storefront_client_parity.py` pass.
- [x] 3.8 Remove the dead VM expiry hook. Delivered by
      `bare-metal-mock-provisioned-deal` task 5B.8.C.6 on 2026-10-05, on the
      maintainer's ruling at that change's slice C design review. The hook
      ran `_do_shutdown`, which always raised because provisioning has no
      expiry-scheduling endpoint, so every VM deal logged "Failed to schedule
      VM expiry". The lease watchdog performs expiry from the registered
      lease's window.
      - Removed: `_do_shutdown`, the `schedule_shutdown` parameter,
        `ScheduleShutdownFn`, `_schedule_shutdown_best_effort`, and the
        module's background-task set.
      - Updated: `test_fulfillment_provisioning.py`,
        `test_fulfillment_service.py`, and
        `test_fulfill_vm_obligation_error_handling.py` no longer pass the
        hook.

      Task 3.5 still owns `reserved_vm_host`.
- [x] 3.9 Deleted `SQLiteClient.get_resource`.
      - `test_settle_controller.py` keeps its site-capacity assertion.
      - The provisioning lease-lifecycle test no longer stubs
        `patch_resource`.
- [x] 3.10 `apply_resource_transition` takes `resource_id`, `event_type`,
      `idempotency_key`, and `set_state`, and absorbed
      `apply_resource_set_transition`. It keeps one transaction, reports a
      duplicate key as a no-op, rolls back on a missing resource, and
      generates the event ID with the current time.
      `tests/integration/test_resource_transitions.py` covers it.
- [x] 3.11 Rewrote the `CapacityReservation` docstring in
      `kit/site/src/market_site/db.py` to describe the row as it is.
- [x] 3.12 The provisioning service unit suite and the `kit/site` suite pass.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 4.1 **Comment hygiene.** `make check-comment-hygiene` passes. Reading
      the touched docstrings found `_record_fulfillment_id` narrating its own
      history and claiming nothing resumes from the identities it stores.
      `fulfillment_resume_runtime` does resume from them, so the docstring
      now says that.
- [x] 4.2 **Import placement.** The change adds no local imports. It removed
      the import its deletions left unused (`uuid` in `admin_controller.py`).
      The pre-existing ruff findings were left alone.
- [x] 4.3 **Documentation compliance.**
      - No permanent document describes the removed routes, the ledger's
        readers, or the `vm_host` plumbing.
      - `ARCHITECTURE.md`'s `host_id` paragraph stays accurate: local tables
        and the upsert capacity check still say `vm_host`.
      - Resource-count diagnosis stays current.
- [x] 4.4 **Narrative compression.** Done in this file.
- [x] 4.5 **Roadmap currency.** Goal 1's current state in
      `docs/development/ROADMAP.md` now records that the surfaces are gone,
      and the change's gap row is removed.
- [x] 4.6 **Campaign index currency.** This change's row in
      `openspec/changes/README.md` reads "implemented 2026-10-08; local suites
      pass; end-to-end evidence pending". It moves to complete, leaving the
      dependency graph, once task 4.9 records evidence.
- [x] 4.7 **Documentation citations.**
      `make check-doc-citations CHANGE=remove-dead-storefront-physical-surfaces`
      passes.
- [x] 4.8 **Packaging.** `make check-packaging` passes on 2026-10-08. The lock,
      install-derivation, Python-version, and project-layout checks are all
      OK.
- [ ] 4.9 **End-to-end pipeline.** Run the E2E workflow (`e2e.yml`) on this
      branch and record the run and its result. Its VM full-deal scenarios
      exercise what this change retains: provisioning, teardown, the
      `capacity_released` callback, and `admin_release_reservations` cleanup
      on a database without `compute_allocations`. If the pipeline cannot run
      for a reason unrelated to this change, record an explicit blocker
      naming the cause and the change that owns it, and treat the
      validations it gates as unrun.
- [x] 4.10 **Promotion.** `docs/development/DEPLOYMENT_AND_CONFIG.md`'s
      "Migrations at startup" now states the frozen-table and
      migration-retirement rule. The record below is complete.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-allocation ledger and no physical resource administration surface | Reached in part here; the requirement is `pools-9-retire-local-physical-authority`'s "Storefront holds no physical-resource authority" |
| Why each surface was dead | This change's `design.md`; no permanent home once the surfaces are gone |
| Removal continues to whatever the deletions orphan | Scope rule for this change, in `design.md`; no permanent home |
| A frozen table is never dropped; a migration that only modifies it leaves the chain, and its recorded ID stays inert and is never reused | `docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup` |
| Authoritative scenario controls replace future local physical-state mutations | Existing authority boundary in `docs/development/ARCHITECTURE.md#authority-boundaries`; no new permanent behavior |
| Resource-count diagnosis and local cleanup retire with the local listing path | Temporary sequencing decision; owned by `pools-9-retire-local-physical-authority/design.md` |
| Existing allocation rows are preserved; unrelated live tests survive the freeze | Migration and validation constraints in this change's `design.md`; no new subsystem requirement |
| Goal 1 current state and gap mapping | `docs/development/ROADMAP.md` |
| Campaign status | `openspec/changes/README.md` |
