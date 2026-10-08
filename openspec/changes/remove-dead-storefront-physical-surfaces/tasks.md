# Tasks

Sections 2 and 3 keep the numbering they have in
`pools-9-retire-local-physical-authority`, which points here.

Design review narrowed the scope: former tasks 3.3 and 3.4 belong to
`pools-9-retire-local-physical-authority`. The 2026-10-08 re-grounding amends
the open tasks to the current tree and to three accepted decisions in
`design.md`:

- removal continues to whatever the deletions orphan;
- the two column-only allocation migrations leave the migration list;
- the `kit/site` docstring is corrected here.

Completed task 3.8 is preserved as delivered.

Unit and integration suites run from each project directory after `make dist`
at the root and `make reinit` in the project: `domains/vms/storefront`
(`make test-unit`, `make test-integration`), `core/storefront-client`
(`make test`), `provisioning/compute/service` (`make test-unit`), and
`kit/site` (`make test`). `domains/vms/listings` has no suite of its own; the
storefront suites cover it.

## 1. Re-confirm

- [ ] 1.1 Re-run the confirming searches in `design.md`'s Context before
      deleting anything. Record any drift in `design.md`. The searches cover:
      - no production `INSERT` into `compute_allocations`, and no reader
        outside `reconciler.py`;
      - no production caller of `delete_resource`, `ensure_default_resources`,
        `host_capacity_remaining`, `list_hosts` (storefront), or, once the
        routes go, `get_resource`;
      - no production or executable e2e caller of the two admin routes,
        `get_resource`, or `patch_resource`;
      - no caller of `_authenticated_patch` other than `patch_resource`;
      - no waiter on the `lease_lifecycle`/`resource_released` stage event;
      - no `vm_host` key in any `kit/site` reservation response;
      - `release_reservations` is the only caller left for
        `apply_resource_set_transition`, and it passes only a state.

## 2. Retire `compute_allocations`

- [ ] 2.1 In `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`,
      remove `HELD_ALLOCATION_STATES`, `allocation_table_exists`,
      `held_gpu_counts`, and `held_gpu_counts_by_resource`. Remove their
      imports and `__all__` entries from that package's `__init__.py`.
- [ ] 2.2 In `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`,
      remove both release-`UPDATE`s against `compute_allocations` from
      `apply_resource_transition`, together with the
      `$.allocation_id`/`$.compute_allocation_id` special case. Task 3.10
      completes the narrowing of that method.
- [ ] 2.3 Freeze the table. No `DROP`; existing schema and rows stay intact.
      - `sqlite_client.py`: remove the `compute_allocations` `CREATE TABLE`,
        its comment, and `trg_compute_allocations_updated_at` from
        `_ensure_domain_tables`. Remove its four indexes from
        `_ensure_domain_indexes`.
      - `domains/vms/storefront/src/market_storefront/utils/migrations.py`:
        remove `_migrate_compute_allocation_callback_metadata`,
        `_migrate_allocation_hold_expiry`, and their two `VM_MIGRATIONS`
        entries (`20260604_001_compute_allocation_callback_metadata`,
        `20260611_007_allocation_hold_expiry`). Every other ID stays as it is.
      - In `_migrate_compute_inventory_pools`, remove the two
        `idx_compute_allocations_*` statements. In `_backfill_compute_pools`,
        remove the trailing allocation `UPDATE`.
- [ ] 2.4 In `domains/vms/storefront/tests/unit/test_compute_allocations.py`,
      replace the three allocation schema tests with freeze tests:
      - A fresh database has no `compute_allocations` table, trigger, or
        index, and does not record either removed migration ID.
      - A database with an existing allocation table and rows keeps the
        table's columns and rows exactly as they were through initialization
        and a second initialization, and does not record the removed IDs.
      - On both databases, a resource transition to `available` succeeds and
        writes no allocation row.

      Keep the pre-compute-inventory test's listing and resource assertions.
      Keep the local derivation, member availability, cross-site identity,
      and hold-persistence tests as they are.
- [ ] 2.5 Add `TestReleaseReservations` to
      `domains/vms/storefront/tests/integration/test_admin_api.py`. It covers
      the endpoint's live cleanup through the typed client:
      - On a fresh database, a held local row is released and reported.
      - Existing allocation rows are left untouched.
      - Rows in other states are not changed.

      These are also the focused cases that
      `pools-9-retire-local-physical-authority`'s task 3.3 updates.
- [ ] 2.6 Run the storefront unit and integration suites.

## 3. Remove dead physical surfaces

The surfaces in this change's scope have no production caller. Tasks 3.3 and
3.4 are transferred scope, not deletions this change authorizes.

- [ ] 3.1 In `sqlite_client.py`, delete `delete_resource`,
      `ensure_default_resources`, `host_capacity_remaining`, and `list_hosts`.
      In `domains/vms/storefront/tests/unit/test_hosts.py`:
      - Delete `TestCapacityRemaining` and `test_list_hosts_filters_disabled`.
      - Rewrite the three `TestCapacityEnforcement` assertions that called
        `host_capacity_remaining` to observe the upsert capacity check itself.
        For example, once two slices fill a host, a further slice raises
        `CapacityExceededError`, and re-importing an existing slice does not
        consume capacity twice.
      - Update the module docstring's coverage list.

      `get_host`, `_HOST_COLUMNS`, and `_host_row_to_dict` stay, because
      `resource_capacity_validator` uses them.
- [ ] 3.2 Remove `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`.
      - `controllers/admin_controller.py`:
        - Delete `get_resource` and `patch_resource`, including the
          `resource_released` stage event, and their model imports.
        - Remove any import (`uuid`, `json`) that is left unused.
        - In `release_reservations`' docstring, describe the endpoint as it
          is (the site-ledger release plus local-row normalization), with no
          watchdog explanation and no `PATCH` recommendation.
      - `models/capacity_admin_models.py`: delete `ResourcePatchRequest` and
        `ResourcePatchResponse`.
      - `middleware/admin_identity.py`: delete the
        `/api/v1/admin/portfolio/resources/` contract block (`admin_get_resource`,
        `admin_patch_resource`). The import route stays.
      - `core/storefront-client/src/storefront_client/client.py`: delete
        `get_resource`, `patch_resource`, and `_authenticated_patch` on both
        `StorefrontClient` and `SyncStorefrontClient`.
      - Tests:
        - Delete `TestPatchResource` from `test_admin_api.py`.
        - Delete the `PATCH` case from
          `tests/unit/test_identity_dispatch.py`.
        - Delete `test_admin_patch_sync_async_contract_is_byte_equivalent`
          and the `PATCH` branch of `_response_context` from
          `core/storefront-client/tests/test_admin_auth.py`. Generic signing
          and parity coverage stays in that file's `authenticated_request`
          and rotation tests.
      - Correct the stage `00h` docstrings and assertion messages in
        `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py` and
        `test_full_deal_buyer_cli.py`:
        - The reverse path is the signed service-peer `capacity_released`
          event to `/api/v1/admin/fulfillment/events/capacity-released`.
        - The `storefront_auth` check is a signed `service`-role
          `GET /api/v1/system/status`.
        - Troubleshooting names the provisioning service's identity and the
          storefront principal it pins
          (`PROVISIONING_STOREFRONT_IDENTITY__*`, the chart's
          `storefrontIdentity`) and the storefront's
          `[Identity.service_peers.provisioning_default]`, not an
          administrator key or `global.adminApiKey`.
      - Correct the `storefront` comment in
        `helm/charts/provisioning/values.yaml`. It describes a watchdog that
        patches the storefront resource; it should describe the callback
        target for the `capacity_released` event.
- [ ] ~~3.3 Remove the legacy local-row normalization loop from
      `release_reservations`.~~ Transferred to
      `pools-9-retire-local-physical-authority`: local inventory cleanup retires
      with the local listing path.
- [ ] ~~3.4 Remove `resource_count` and its resource-count diagnosis
      documentation.~~ Transferred to `pools-9-retire-local-physical-authority`:
      the permanent scenario, e2e assertions, and operator guidance remain
      current until the local-inventory cutover.
- [ ] 3.5 Remove the always-`None` `reserved_vm_host` where it now lives:
      - In `services/vm_fulfillment_service.py`'s `fulfill_vm_obligation`,
        remove the variable, its explanatory comment, and the
        `vm_host=` keyword in the `provision_vm` call.
      - In `services/fulfillment_service.py`'s `_do_provision`, remove the
        `vm_host` parameter and its docstring paragraph.
      - Lease registration at commit and the post-provision paths stay as
        they are.
      - In `tests/unit/test_fulfillment_provisioning.py`, drop `vm_host=` from
        the three `_do_provision` calls. Add an assertion to the provisioning
        call test that `provision_vm` receives no `vm_host` keyword. Correct
        the opaque-reservation test docstring's reference to a double
        supplying `vm_host`.
      - In `tests/unit/test_two_phase_reserve.py`, drop `vm_host` from the
        reservation double `_hold`.
      - In `tests/integration/test_capacity_reservation_boundary.py`, correct
        the comment claiming `vm_host` "is not stripped the same way": the
        site names a host `host_id` and strips it.
      - Leave `vm_host` in local resource attributes and CSV fixtures alone;
        it belongs to local inventory, which `pools-9` retires.
- [ ] 3.6 Confirm by diff that 3.5 leaves `fulfill_vm_obligation`'s
      committed-claim reads and commit-time lease window untouched.
- [ ] 3.7 Run the storefront unit and integration suites, the
      `core/storefront-client` suite, and the client parity contract test
      `domains/vms/storefront/tests/unit/test_storefront_client_parity.py`.
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
- [ ] 3.9 Remove what the route removal orphans:
      - Delete `SQLiteClient.get_resource`.
      - In `tests/integration/test_settle_controller.py`, drop the local-row
        assertion that reads it and keep the
        `capacity_site._available(...)` assertion, which proves the
        behavior.
      - In `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`,
        drop the `patch_resource` stub and its `assert_not_awaited`.
- [ ] 3.10 Narrow the resource-transition machinery to its one remaining use.
      - Fold `apply_resource_set_transition` into `apply_resource_transition`.
        It accepts `resource_id`, `event_type`, `idempotency_key`, and
        `set_state`, which is what `release_reservations` supplies.
      - Remove the `set_value`, `set_attribute`, `event_id`, and `occurred_at`
        handling. The `resource_transition_events` columns stay, and are
        written as `NULL` and as the generated ID.
      - Point `release_reservations` at the folded method.
- [ ] 3.11 Rewrite the `CapacityReservation` docstring in
      `kit/site/src/market_site/db.py`. Describe the row as it is, with no
      comparison to the storefront's `compute_allocations`, `vm_leases`, or
      a storefront `PATCH`.
- [ ] 3.12 Run the `provisioning/compute/service` unit suite and the
      `kit/site` suite.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the
      touched docstrings and comments directly as well. Stale docstrings are
      what kept these surfaces alive past their callers. These are in scope:
      - `release_reservations`, `_do_provision`, and its
        "legacy job-id hook" phrase;
      - `fulfill_vm_obligation`'s `_record_fulfillment_id`;
      - the `kit/site` `CapacityReservation` docstring;
      - the Helm `storefront` comment;
      - the two stage `00h` docstrings.
- [ ] 4.2 **Import placement.** Check every import this change adds or
      touches. Remove imports the deletions leave unused. Do not relocate
      pre-existing local imports in touched files.
- [ ] 4.3 **Documentation compliance.**
      - Confirm no permanent document describes the removed routes, the
        allocation ledger, or the `vm_host` plumbing.
      - Confirm `docs/development/ARCHITECTURE.md`'s `host_id` paragraph,
        which names local tables still saying `vm_host`, is still accurate.
      - Resource-count diagnosis remains current and belongs to the later
        cutover.
      - Confirm the migration-retirement paragraph from task 4.10 sits in
        `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Migrations at
        startup" section.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final
      behavior, validation evidence, deferrals, and destinations.
- [ ] 4.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, fold the
      retired surfaces into Goal 1's current-state text and remove this
      change's gap row.
- [ ] 4.6 **Campaign index currency.** In `openspec/changes/README.md`'s Goal 1
      campaign, mark this change complete and remove it from the dependency
      graph's independent line.
- [ ] 4.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=remove-dead-storefront-physical-surfaces`
      and resolve every match.
- [ ] 4.8 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.
- [ ] 4.9 **End-to-end pipeline.** Run the E2E workflow (`e2e.yml`) on this
      branch and record the run and its result. Its VM full-deal scenarios
      exercise what this change retains: provisioning, teardown, the
      `capacity_released` callback, and `admin_release_reservations` cleanup
      on a database without `compute_allocations`. If the pipeline cannot run
      for a reason unrelated to this change, record an explicit blocker
      naming the cause and the change that owns it, and treat the
      validations it gates as unrun.
- [ ] 4.10 **Promotion.**
      - Add one paragraph to `docs/development/DEPLOYMENT_AND_CONFIG.md`'s
        "Migrations at startup". A storefront migration whose only effect is
        on a frozen table leaves the chain. Its recorded ID stays inert,
        because the engine ignores recorded IDs it no longer lists, and the ID
        is never reused.
      - Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-allocation ledger and no physical resource administration surface | Reached in part here; the requirement is `pools-9-retire-local-physical-authority`'s "Storefront holds no physical-resource authority" |
| Why each surface was dead | This change's `design.md`; no permanent home once the surfaces are gone |
| Removal continues to whatever the deletions orphan | Scope rule for this change, in `design.md`; no permanent home |
| A migration that only modifies a frozen table leaves the chain; its recorded ID stays inert and is never reused | `docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup` (task 4.10) |
| Authoritative scenario controls replace future local physical-state mutations | Existing authority boundary in `docs/development/ARCHITECTURE.md#authority-boundaries`; no new permanent behavior |
| Resource-count diagnosis and local cleanup retire with the local listing path | Temporary sequencing decision; owned by `pools-9-retire-local-physical-authority/design.md` |
| Existing allocation rows are preserved; unrelated live tests survive the freeze | Migration and validation constraints in this change's `design.md`; no new subsystem requirement |
| Goal 1 current state and gap mapping | `docs/development/ROADMAP.md` (task 4.5) |
| Campaign status | `openspec/changes/README.md` (task 4.6) |
