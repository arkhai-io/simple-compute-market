# Tasks

Sections 2 and 3 keep the numbering they have in
`pools-9-retire-local-physical-authority`, which points here.

Design review narrowed the scope: former tasks 3.3 and 3.4 belong to
`pools-9-retire-local-physical-authority`. The existing checklist is reconciled
below with that decision; this is not a new implementation plan. The accepted
freeze and test-ownership constraints are in `design.md`.

## 1. Re-confirm

- [ ] 1.1 Re-run the confirming searches `design.md`'s Context records:
      `compute_allocations`' lack of any production `INSERT`, the four
      methods with no production caller, the two admin routes' lack of any
      production or executable e2e caller,
      and that `reserved.get("vm_host")` is always `None` at the
      opaque-reservation boundary. Record drift in `design.md`.

## 2. Retire `compute_allocations`

- [ ] 2.1 Remove `held_gpu_counts`, `held_gpu_counts_by_resource`, and
      `allocation_table_exists` from
      `domains/vms/listings/src/arkhai_vms_listings/reconciler.py` and
      their exports from that package's `__init__.py`.
- [ ] 2.2 Remove the release-`UPDATE` against `compute_allocations` from
      `SQLiteClient.apply_resource_transition`, including the
      `$.allocation_id`/`$.compute_allocation_id` attribute-path special case
      that feeds it.
- [ ] 2.3 Freeze the table: stop creating it in `_ensure_domain_tables`, stop
      creating its trigger and four indexes, and stop adding its columns in
      `migrations.py`, including allocation backfill writes. Existing schema
      and rows remain intact; historical migration IDs remain stable. No `DROP`.
- [ ] 2.4 Revise the allocation schema assertions for the freeze while
      preserving the local derivation, member availability, cross-site identity,
      and negotiation hold-persistence coverage in `test_compute_allocations.py`.
      The previously named CLI publish test file is absent. Validation must
      cover fresh initialization, an existing allocation table, and rerun.
- [ ] 2.5 Run the storefront unit and integration suites.

## 3. Remove dead physical surfaces

The surfaces retained in this change's scope have no production caller.
Tasks 3.3 and 3.4 are transferred scope, not deletions authorized by this change.

- [ ] 3.1 Delete `SQLiteClient.delete_resource`, `ensure_default_resources`,
      `host_capacity_remaining`, and `list_hosts`, plus the
      `host_capacity_remaining` and `list_hosts` tests in `tests/unit/test_hosts.py`.
- [ ] 3.2 Remove `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`,
      their request/response models, and `storefront_client`'s `get_resource`
      and `patch_resource` on both client variants. This includes the route
      contracts in `middleware/admin_identity.py` and their route-specific
      assertions in `test_admin_api.py` and `test_identity_dispatch.py`.
      Preserve generic signing/parity coverage in
      `core/storefront-client/tests/test_admin_auth.py` through a supported
      operation. Correct the obsolete PATCH callback descriptions in both VM
      full-deal scenarios and the release endpoint's docstring.
- [ ] ~~3.3 Remove the legacy local-row normalization loop from
      `release_reservations`.~~ Transferred to
      `pools-9-retire-local-physical-authority`: local inventory cleanup retires
      with the local listing path.
- [ ] ~~3.4 Remove `resource_count` and its resource-count diagnosis
      documentation.~~ Transferred to `pools-9-retire-local-physical-authority`:
      the permanent scenario, e2e assertions, and operator guidance remain
      current until the local-inventory cutover.
- [ ] 3.5 Remove the always-`None` `reserved_vm_host` and its threading
      through `register_lease`, `schedule_shutdown`, `provision_vm`,
      `_do_provision`, and `_register_vm_lease_with_settings`. Leave
      `vm_host` inside the provisioning adapter untouched — it is the real
      execution target there.
      **Rebase note (2026-10-05).** `bare-metal-mock-provisioned-deal`
      (5B.8.B.1, B.7, B.8, B.9) rewrote the code this task edits. In
      `vm_fulfillment_service.py`, the post-provision path now registers the lease
      with the window the reservation's commit returned (`committed_lease_window`).
      A missing window, a failed registration, or a failed evidence publication now
      returns a `deferred` result rather than an error. `_register_vm_lease_with_settings`
      no longer sends an offering mode. Remove `reserved_vm_host` from that code as it
      stands, keeping those paths intact.
- [ ] 3.6 Confirm `fulfill_vm_obligation`'s committed-claim reads are untouched
      by 3.5.
- [ ] 3.7 Run the storefront and `core/storefront-client` suites plus the
      client parity contract test.
- [x] 3.8 Remove the dead VM expiry hook (routed here on 2026-10-05 from
      `bare-metal-mock-provisioned-deal`'s closeout findings). Delivered by
      `bare-metal-mock-provisioned-deal` task 5B.8.C.6 (2026-10-05), on the maintainer's
      ruling at that change's slice C design review: `_do_shutdown`, the
      `schedule_shutdown` parameter, `ScheduleShutdownFn`,
      `_schedule_shutdown_best_effort`, and the module's background-task set are gone, and
      the three test files below no longer pass the hook. 3.5 still owns
      `reserved_vm_host`.
      - What is dead: `fulfillment_service.py` wires `schedule_shutdown=_do_shutdown`,
        and `_do_shutdown` always raises, because the provisioning service has no
        expiry-scheduling endpoint. `vm_fulfillment_service.py`'s
        `_schedule_shutdown_best_effort` runs it as a background task after every
        deal, so every VM deal logs "Failed to schedule VM expiry". The lease
        watchdog performs expiry from the registered lease's window.
      - Remove `_do_shutdown`, the `schedule_shutdown` parameter and its
        `ScheduleShutdownFn` type, `_schedule_shutdown_best_effort`, and the
        module's `_background_tasks` set if nothing else uses it.
      - Update the tests that pass the hook: `test_fulfillment_provisioning.py`,
        `test_fulfillment_service.py`, and
        `test_fulfill_vm_obligation_error_handling.py`.
      - Coordinate with 3.5, which removes `reserved_vm_host` from the same call.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the
      touched docstrings directly as well: `patch_resource`,
      `release_reservations`, and `_register_vm_lease_with_settings` describe
      an arrangement that no longer exists, and stale docstrings are what kept
      these surfaces alive past their callers.
- [ ] 4.2 **Import placement.**
- [ ] 4.3 **Documentation compliance.** Confirm no permanent document
      describes the removed routes. Resource-count diagnosis remains current
      and belongs to the later cutover.
- [ ] 4.4 **Narrative compression.**
- [ ] 4.5 **Roadmap currency.** Fold the retired surfaces into Goal 1's
      current-state text in `docs/development/ROADMAP.md` and remove this
      change's gap row.
- [ ] 4.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md`'s Goal 1 campaign.
- [ ] 4.7 **Promotion.** Complete the design-promotion record below.
- [ ] 4.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=remove-dead-storefront-physical-surfaces`
      and resolve every match.
- [ ] 4.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence; the VM full-deal provisioning and teardown stages
      exercise the retained reservation/fulfillment behavior beside the removed
      host threading. If the pipeline cannot run for a reason unrelated
      to this change, record that as an explicit blocker naming the cause and
      the change that owns it, and treat the validations it gates as unrun.
- [ ] 4.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-allocation ledger and no physical resource administration surface | Reached in part here; the requirement is `pools-9-retire-local-physical-authority`'s "Storefront holds no physical-resource authority" |
| Why each surface was dead | This change's `design.md`; no permanent home once the surfaces are gone |
| Authoritative scenario controls replace future local physical-state mutations | Existing authority boundary in `docs/development/ARCHITECTURE.md#authority-boundaries`; no new permanent behavior |
| Resource-count diagnosis and local cleanup retire with the local listing path | Temporary sequencing decision; owned by `pools-9-retire-local-physical-authority/design.md` |
| Existing allocation rows are preserved; unrelated live tests survive the freeze | Migration and validation constraints in this change's `design.md`; no new subsystem requirement |
