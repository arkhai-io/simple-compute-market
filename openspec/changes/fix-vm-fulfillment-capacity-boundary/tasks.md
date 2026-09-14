## 1. Corrupted GPU-attachment-discovery shell logic

- [x] 1.1 Restore `[ -z "$pci_addr" ] && continue` at `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/vm-create.yml` line 403 (currently `continueThen remove all task that contains installation of GPU driver that is not`). Confirm `roles/vm-management/backup/original-main.yml` remains unreferenced (`grep -rl "original-main"` plus Ansible include/import inspection); if true, delete it and return it as an explicit review tombstone rather than maintaining a duplicate. If a consumer is found, stop and amend the design before changing that file.
- [x] 1.2 Add a shell-logic test harness to `domains/vms/provisioning/iac/tests`: a helper that (a) extracts a named task's literal shell-script content from a task YAML file (this block has no Jinja templating; confirm that remains true or extend the helper to accept pre-rendered variable substitutions if a future case needs it), (b) writes fake `virsh`/`lspci` executables into a temp directory as `#!/bin/sh` scripts returning fixture-controlled output, (c) runs the extracted script via `subprocess.run(["bash", "-c", script], env={**os.environ, "PATH": f"{fake_bin_dir}:{os.environ['PATH']}"})`, (d) exposes the script's result (stdout, or a value it writes to a file/env var for the test to read back) to the caller. Keep this reusable — a second shell-logic bug elsewhere should not need its own harness.
- [x] 1.3 Add a test using the harness that feeds the GPU-attachment-discovery loop a `virsh dumpxml`-shaped fixture containing at least one empty `pci_addr` entry among real ones, asserting the empty entry is skipped and does not appear (garbled or otherwise) in the resulting `ATTACHED_GPUS_LIST`. This is the regression test for the corrupted line — it must fail against the pre-fix text and pass after.
- [x] 1.4 Confirm the existing substring-assertion tests in `test_vm_management_contracts.py` still pass; they are not being replaced, only supplemented — they still catch structural/ordering regressions the harness doesn't (and vice versa).

## 2. Reservation-commit boundary cleanup

- [x] 2.1 Make `CommitRequest.resource_id` optional (`str | None = None`) in `kit/site/src/market_site/http_models.py`. Add a docstring/comment explaining why: `CapacityLedgerService.commit()` already ignores this value whenever `capacity_reservation_id` is supplied (true for every current caller, since the `/commit` endpoint takes `capacity_reservation_id` as a mandatory path parameter, not from the body), so requiring it here over-constrains the wire contract relative to what the method behind it needs.
- [x] 2.2 Document, at `ledger.commit()`'s `resource_id` parameter and at `_find_reservation`'s `resource_id`-only lookup branch (`kit/site/src/market_site/ledger.py`), what caller shape would actually exercise resource_id-only lookup: a caller with a `resource_id` but no `capacity_reservation_id` — not the current resource-pinned-listing case, which still uses `capacity_reservation_id` normally. No current caller does this; this is forward documentation, not a functional change.
- [x] 2.3 Remove `fulfill_vm_obligation`'s `if not reserved_vm_host: raise RuntimeError(...)` guard in `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py`. Keep `vm_host`/`resource_id` flowing into `stage_event(...)` calls as best-effort telemetry (already their only other use here); do not add a replacement guard elsewhere.
- [x] 2.4 Stop `str(reserved.get("resource_id"))` from producing the literal string `"None"`. Either stop persisting `settlement_resource_id` at the `fulfillment_phase="capacity_reserved"` write in `fulfill_vm_obligation` (deferring entirely to the correct post-`schedule_resource()` write `_do_provision` already performs), or persist an actual `None`/omit the field if an early informational write is still wanted. Same fix applies to `_commit_capacity_hold`'s and `_commit_fresh_reservation`'s equivalent `str(...get("resource_id"))` conversions if they have the same pattern — audit both before closing this task.
- [x] 2.5 Remove `_commit_fresh_reservation`'s `if not capacity_reservation_id or not resource_id: raise RuntimeError("Reserved capacity is missing reservation identity")` guard's dependence on `resource_id` specifically (keep the `capacity_reservation_id` check — that one is genuinely required). Confirm nothing else in `_reserve_capacity_for_obligation`'s call chain silently depends on `resource_id` being non-None between this point and `schedule_resource()`.
- [x] 2.6 Add an integration test exercising the real `RemoteCapacityClient` → `kit/site` HTTP router boundary (real ASGI app, not an in-process fake) for a full VM obligation fulfillment — reserve, commit, `schedule_resource()`, `begin_fulfillment()` — asserting it completes without ever requiring `resource_id`/`vm_host` from the reservation response at any step. This is the test that would have caught the original defect; an in-process fake that doesn't enforce the wire contract's field-stripping proves nothing here.
- [x] 2.7 Add a boundary-contract test on `kit/site`'s `/reservations` endpoint response shape directly: assert it never contains `resource_id`, `capacity_bucket_id`, or `backing_resource_id`, independent of any specific caller. Protects every future caller, not just this one.
- [x] 2.8 Add a regression test for 2.4: interrupt fulfillment between the capacity-reserved persist and `schedule_resource()` (e.g. raise from a patched `schedule_resource`), assert the persisted `settlement_resource_id` is never the literal string `"None"`.
- [x] 2.9 Unit test `ledger.commit()` directly: a commit with `resource_id=None`/omitted succeeds identically to one with it supplied, given `capacity_reservation_id` is present.

## 3. Derive VM shape from committed reservation dimensions

- [x] 3.1 Confirm `PhysicalSettlementScheduler.schedule_resource()`'s reservation payload (via `tx.reservation_payload(reservation_row)`) exposes `CapacityReservationDebit.dimensions` in a form usable downstream; if not already exposed on `SettlementResource` or an adjacent type, add it as a domain-neutral field. `kit/fulfillment` treats the dimensions as opaque and must not contain VM- or Ansible-specific interpretation.
- [x] 3.2 Thread the committed dimensions through the scheduled settlement context into `AnsibleFulfillmentProvider.prepare_create()`. Prefer the type already flowing from scheduling over a second ledger read so the selected resource, snapshotted provider configuration, and committed dimensions remain one fulfillment input.
- [x] 3.3 Keep only canonical VM dimension names and domain-level validation in `arkhai_vms`: `gpu_count`, `vcpu_count`, `ram_gb`, and `disk_gb`. Remove Ansible variable names, GiB/MiB conversions, disk-string formatting, and playbook-derived booleans from the VM domain module.
- [x] 3.4 Define a requirement-delegate interface in `domains/vms/provisioning/adapter`. A delegate receives canonical committed dimensions plus the snapshotted pool/provider configuration, validates that the configured playbook can represent them, and returns the exact playbook variables. Its errors must identify the pool, delegate identifier, incompatible dimension, and reason before any Ansible job is created.
- [x] 3.5 Add an explicit adapter-owned registry mapping stable delegate identifiers to interpreting classes. Resource-pool configuration stores the registry identifier alongside the playbook path; it MUST NOT accept an arbitrary Python import path. Register the delegate for the current repository VM-management playbook and reject unknown identifiers during pool provider-config validation.
- [x] 3.6 Move the current playbook-specific translation into that delegate: `gpu_count` to `vm_gpu_count` and `gpu_provisioned`, `vcpu_count` to `vm_vcpus`, canonical RAM to the playbook's `vm_ram` unit, and canonical disk to the playbook's `vm_disk_size` encoding. Verify the playbook's actual unit contract in its tasks/defaults/tests before documenting the conversion.
- [x] 3.7 Enforce one strict precedence rule for every reservation-governed shape field: committed reservation dimensions are authoritative; caller request fields are never fallback inputs. Remove GPU-specific fallback behavior and any equivalent field-by-field exception. Pool defaults may fill only settings explicitly defined outside reservation-governed shape.
- [x] 3.8 Confirm storefront fulfillment payload construction does not transmit VM shape and remove any now-unused request fields or compatibility plumbing that imply callers may override the committed shape.
- [x] 3.9 Add delegate unit tests covering the current playbook contract, missing and malformed canonical dimensions, unsupported values, unknown delegate identifiers, and deterministic conversion of GPU=0 and GPU=1 cases.
- [x] 3.10 Add an end-to-end contract test proving a GPU=1 reservation reaches the provider with the correct playbook variables, sourced only from committed reservation dimensions. Include conflicting caller shape values and assert they have no effect. Include GPU=0/no-GPU coverage so no stale default leaks into the job.
- [x] 3.11 Add a present-tense code comment at `resize_reservation` stating that requirement changes must be committed before scheduling so the scheduled reservation dimensions remain authoritative. Reference the stable permanent specification section added in task 6.2, never this change document.

## 4. Distribution and dependency ownership

- [x] 4.1 Replace root-level per-domain wheel forwarding with one aggregate delegation to `domains/Makefile` (`$(MAKE) -C domains dist ...` or the repository-equivalent `cd domains && $(MAKE) dist`). The root Makefile remains a repository-composition layer and does not enumerate individual domain wheels.
- [x] 4.2 Make `domains/Makefile` own the complete domain distribution set and dependency order. Audit every domain wheel produced there and add a corresponding test entry point or an explicit, documented packaging-only exemption; do not leave silently untested distribution targets.
- [x] 4.3 Audit the entire `[tool.uv.sources]` block in `domains/vms/provisioning/adapter/pyproject.toml` and remove all relative editable internal dependencies, not only the newly added VM-domain dependency.
- [x] 4.4 Follow the repository's existing `reinit` pattern to recreate the adapter virtual environment and install internal dependencies from wheels in `.dist`. If a required wheel is absent, add its producer to the aggregate `make dist` chain and dependency ordering rather than restoring a relative source.
- [x] 4.5 Add or amend Makefile tests that prove a clean `make dist` followed by the adapter's `reinit`/test path works without sibling source imports.

## 5. Boundary and regression validation

- [x] 5.1 Retain any existing commit-only HTTP boundary test as focused coverage, but name it according to the behavior it actually proves.
- [x] 5.2 Add the required full integration path using the real `RemoteCapacityClient` and site ASGI router: `reserve → commit → schedule_resource() → begin_fulfillment()`. Assert no step requires `resource_id` or `vm_host` from the opaque reservation response.
- [x] 5.3 Add a direct `/reservations` response-shape contract test asserting that `resource_id`, `capacity_bucket_id`, and `backing_resource_id` are absent.
- [x] 5.4 Interrupt fulfillment before scheduling and assert no literal `"None"` settlement resource is persisted.
- [x] 5.5 Run the full existing suite for every touched package together: `kit/site`, `kit/fulfillment`, `domains/vms/domain`, `domains/vms/storefront`, `domains/vms/provisioning/adapter`, `domains/vms/provisioning/iac`, and any provisioning service package changed by the integration path.

## 6. Permanent documentation and closeout

- [x] 6.1 Update `openspec/specs/site-capacity/spec.md` to state that committed reservation dimensions are the authoritative admitted shape exposed to scheduling and that callers cannot replace that shape during fulfillment.
- [x] 6.2 Update `openspec/specs/physical-provisioning/spec.md` to define the requirement-delegate boundary: a resource pool selects a registered delegate and playbook; the delegate validates compatibility and translates canonical dimensions into provider-specific inputs; arbitrary class import paths are forbidden; committed dimensions have strict precedence over caller fields.
- [x] 6.3 Update the appropriate permanent resource-pool/provider-configuration specification to document the new delegate identifier field, registry validation, snapshot behavior, and failure semantics. If no existing subsystem specification owns provider configuration, identify and amend that ownership explicitly before implementation closeout rather than placing the rule only in `ARCHITECTURE.md`.
- [x] 6.4 Amend `docs/development/ARCHITECTURE.md` only if implementation reveals a repository-wide rule not already covered there. The expected package-specific delegate mechanics belong in subsystem specifications, not the repository-wide architecture document. **No amendment required:** existing wheel-consumption and package-boundary guidance already covers the repository-wide concerns; delegate mechanics are documented in subsystem specifications.
- [x] 6.5 Remove temporary, migration-oriented, speculative, and change-history comments from production code. Production comments describe current invariants and may reference only stable permanent documentation. **Verified:** the new delegate implementation uses present-tense contract documentation and contains no active-change references or speculative unit commentary.
- [x] 6.6 Complete the design-promotion record below with exact headings after promotion and verify production code contains no `openspec/changes` references. **Verified:** repository production sources contain no reference to `openspec/changes/fix-vm-fulfillment-capacity-boundary`.
- [x] 6.7 Update all task checkboxes to reflect actual implementation and validation status; preserve already-completed work and amend tasks whose delivered behavior changed during review.
## 7. Post-provision opaque-boundary correction

- [x] 7.1 Fix `fulfill_vm_obligation`'s post-provision `capacity.commit(...)` gate: key on `reserved_capacity_reservation_id` instead of `reserved_resource_id`, which is legitimately absent on the real opaque reservation response and was silently skipping the lease-window refresh.
- [x] 7.2 Fix `fulfill_vm_obligation`'s post-provision `register_lease(...)` gate the same way: key on `reserved_capacity_reservation_id`/`vm_target`/`escrow_uid`, not `reserved_resource_id`/`reserved_vm_host` -- the latter was silently skipping lease registration, which the watchdog's auto-release depends on.
- [x] 7.3 Make `_register_vm_lease_with_settings`'s `resource_id`/`vm_host` parameters optional (`| None = None`), matching that its `LeaseRegistration` call never reads them.
- [x] 7.4 Add a regression test using the real opaque-reservation shape (no `resource_id`/`vm_host` in the `reserve()` result) asserting both post-provision calls still fire. Confirm it fails against the pre-fix gates and passes after.
- [x] 7.5 Re-run the full touched-file test suite; confirm no regressions.
- [x] 7.6 Record the correction and its promotion status in `design.md`'s "Post-implementation correction" section.

### Section 7 design-promotion record

See `design.md`'s "Design-promotion record" table.

## 8. Correct scheduled-vs-committed dimensions authority

- [x] 8.1 Discuss phase: confirm via test whether `SettlementResource.dimensions` reflects the reservation's full committed dimensions or the (possibly narrower) scheduled request. Confirmed: the latter, and this is correct -- see `design.md`'s "Discuss phase" and "Resolution" sections for the negotiation-conversation context that settles this.
- [x] 8.2 No scheduler code change required -- `_resource_from_record` already reports the scheduled (reservation-bounded) dimensions, which is the correct behavior once negotiation-driven narrowing is understood as intended.
- [x] 8.3 Correct `openspec/specs/site-capacity/spec.md`'s "Committed dimensions remain authoritative through scheduling" requirement to state the scheduled shape, bounded by but not necessarily equal to the reservation, is authoritative.
- [x] 8.4 Correct `openspec/specs/physical-provisioning/spec.md`'s "Provisioning shape comes from committed capacity" requirement to match.
- [x] 8.5 Add the repository-wide negotiation/capacity premise to `docs/development/ARCHITECTURE.md`: pooled-capacity negotiation, not physical-resource pinning; `resize_reservation` as the mechanism for a persisted shape change; explicit note that `resize_reservation` has no negotiation-side caller yet.
- [x] 8.6 Update `kit/fulfillment/tests/unit/test_scheduler.py::test_scheduled_dimensions_reflect_narrowed_request_not_full_reservation`'s docstring to describe pinned intended behavior rather than an open gap.
- [x] 8.7 Re-run `kit/fulfillment` test suite; confirm no regressions.

### Section 8 design-promotion record

See `design.md`'s "Design-promotion record" table.

## 9. Verification pass on prior fixes

- [x] 9.1 Re-verify prior fixes in this change against current code, not against task checkmarks alone.
- [x] 9.2 `vm_host` stripping from `/reservations`: confirmed still not done; decision needed (recorded in `design.md`, not yet made).
- [x] 9.3 Adapter lockfile: root-caused the actual regeneration bug (`test-domain-dist-reinit` propagating an absolute `DIST_DIR`), fixed the root `Makefile`, regenerated `domains/vms/provisioning/adapter/uv.lock` cleanly (verified no absolute paths), confirmed the adapter's own test target still passes (25/25).
- [x] 9.4 CI workflow: reviewed `.github/workflows/tests.yml`; confirmed gaps broader than initially reported (missing several packages from the matrix entirely, not just the staging-only trigger). Left unresolved pending a decision on priority.
- [x] 9.5 Cross-service test strengthening: confirmed the specific test originally flagged is unchanged, but found its substance already satisfied by `test_ansible_fulfillment_provider.py::test_request_supplied_sizing_is_ignored_even_when_present` (this change's own task 3.10). Recommend treating as resolved.

### Section 9 design-promotion record

See `design.md`'s "Design-promotion record" table.

## 10. Amendment: the claim's categorical half (see the design document)

- [x] 10.1 Persist the categorical half of the admitted claim on the
      reservation: a ledger-owned `claim_attributes` JSON column on
      `CapacityReservation`, written in `reserve()` from the same
      `_split_claim_requirement` call `_find_candidate` matches on. Additive
      and not backfilled -- the information is unrecoverable for existing
      rows, which is the gap being closed, so `NULL` means "admitted before
      this was recorded" rather than "no constraint".

- [x] 10.2 `resize_reservation` carries the superseded reservation's
      `claim_attributes` onto its replacement rather than re-splitting the
      resize call's claim. A resize changes how much was committed; what kind
      of resource was sold was settled at admission.

- [x] 10.3 `PhysicalSettlementScheduler._requirement` takes categorical
      constraints from the reservation, on the same precedence rule as the
      dimensions beside it: the reservation governs, a request may narrow by
      adding a key the reservation does not govern, and a request
      contradicting a governed key raises `SettlementRequestMismatchError`.
      Only a `NULL` column falls back to the request.

- [x] 10.4 Four scheduler tests, each verified to fail against the unpatched
      scheduler: a categorical claim excluding an otherwise-eligible
      resource; a resource-pinned claim surviving a cursor pointing
      elsewhere; an unsatisfiable claim refused rather than reassigned; and
      narrowing permitted where contradiction is refused.

      The first two needed a deliberate adversarial setup, and did not have
      one at first. A fresh round-robin cursor selects the first pool in
      sorted order, which was also the correct answer, so both passed against
      the unpatched scheduler until a warm-up placement was added to walk the
      cursor onto the *wrong* pool first. Each now asserts that warm-up's
      outcome too, so the test states the cursor position it is beating
      rather than depending on it silently.

- [x] 10.5 **Not in this change:** retire `capacity_reservations.vm_remove_job_id`.
      It holds a VM-conditional mirror of `release_job_id`, written only when
      `offering_mode` is the VM mode and always to the value `release_job_id`
      already has, and it is the one domain-prefixed field on a reservation
      table bare-metal pools share. Attempted here and withdrawn: the name is
      also a field on three packages' public wire models
      (`vm_provisioning_operator.models`, the storefront's
      `capacity_admin_models`, the VM and bare-metal lease controllers) and
      appears in a legacy-backfill path, so it is a wire-contract change
      across 22 files rather than a column drop. Its own change, with the
      `vm_host`/`vm_target` column drops on this table as precedent for the
      rebuild migration.

      `_reservation_payload`'s derived `vm_host`/`vm_target` keys are
      deliberately left alone -- those are domain-shaped projections beside
      the generic `executor_ref`/`executor_target`, not duplicated storage.

      **Closed as deferred (2026-09-14):** tracked by
      `openspec/changes/retire-vm-remove-job-id/`, which this task named as
      its home. Scoping it there corrected this note in one material way:
      the "22 files" figure conflates two different columns. A grep for the
      identifier also finds `vm_leases.vm_remove_job_id`, the legacy table
      the backfill reads from -- `db/migrations.py` `SELECT`s
      `vl.vm_remove_job_id` and joins to `capacity_reservations`, so it
      reads the legacy source and never writes the mirror -- plus the
      storefront's own column in `market_storefront/utils/sqlite_client.py`.
      Neither is in scope for retiring the mirror, which makes the real
      change roughly ten production files rather than twenty-two.

      The wire-compatibility argument for keeping the mirror also went away
      with the groundwork recorded above: `release_job_id` is now published
      on the VM adapter's lease contract, so no caller has to read
      `vm_remove_job_id` to get the handle.

      **Partial groundwork since (2026-09-14).** `LeaseResponse`
      (`vm_provisioning_operator.models`) now also publishes
      `release_job_id`, and the VM adapter's lease view fills both from the
      one ledger field. Additive and wire-compatible -- no consumer had to
      change -- and it removes the reason a caller would reach for
      `vm_remove_job_id`: the canonical name is now readable from the VM
      lease endpoint, which it previously was not.

      That gap was the defect behind e2e stage `10b`. The ledger held
      `release_job_id` correctly and the *compute contract* endpoint
      (`/api/v1/contract/leases/{id}`) published it, but the VM adapter's
      `/api/v1/leases/{id}` -- which is the endpoint
      `SyncProvisioningClient.get_lease` calls, and therefore the one the
      e2e's `DealLease` view reads -- published only `vm_remove_job_id`. A
      caller asking for the documented name got `None` from a lease that
      was demonstrably releasing. Two lease contracts for one reservation,
      disagreeing about which names they expose, is the cost of the mirror
      this task exists to retire.

      The existing coverage asserted the handle on the *ledger*, which is
      why this survived: asserting the ledger is not asserting the
      contract. `test_leases_api.py` now asserts it on the API response.

- [x] 10.6 **`create_job_id` is populated by the service that dispatches the
      job.** The field was plumbed end to end with a `None` default at every
      hop and no VM supplier, so the VM path left it null while bare metal
      filled it -- invisible to tests of either side.

      The id is the Ansible job id, not the durable fulfillment id: the
      fulfillment id is already reachable from settle status and the buyer's
      run-log, whereas a provider's own job handle is visible nowhere outside
      the service that dispatched it and is the only one of the two a site
      admin can act on. The lease should carry the reference that otherwise
      dead-ends.

      That places the write in the provisioning service, not the storefront,
      which registers the lease but never sees the value. Implemented as four
      layers, each owning only what it knows:

      - `FulfillmentProvider.resolve_executor_job_id(provider_metadata)`,
        concrete and returning `None` rather than abstract -- a provider with
        no addressable job handle is legitimate, and forcing every existing
        provider to declare that would be churn. Shared orchestration never
        learns which metadata key holds it.
      - The Ansible provider overrides it, reading defensively rather than
        through `AnsibleFulfillmentMetadata`: a teardown-phase row has the
        same shape with a different `operation`, and a partially-written row
        from a failed dispatch should yield no id rather than raise inside a
        transaction that is only surfacing a diagnostic handle.
      - `SqlAlchemyFulfillmentTransaction` gains the capacity ledger the
        scheduling unit of work already held, and `attach_executor_job`.
        Best-effort by construction: the fulfillment is already acknowledged
        and failing it here would trade a working VM for a missing
        cross-reference.
      - The orchestrator attaches inside the acknowledgement transaction, so a
        reservation never references a create the settlement row does not also
        record, and skips a falsy answer -- an empty job reference is worse
        than none, because it reads as a handle an operator can look up.

      Two tests. The attaching one was verified to fail against the unpatched
      orchestrator; the `None` one passes either way and is a guard against a
      future falsy placeholder rather than a discriminating test.

      Found while wiring it: the shared fake provider is a bare `MagicMock`,
      so `resolve_executor_job_id` returned a truthy `Mock` and the
      orchestrator tried to attach that object as a job id, breaking two
      existing tests. The fake now returns `None` explicitly, which is also
      the honest default for a provider fake.

- [x] 10.7 **The first implementation called a method that does not exist.**
      `CapacityLedgerService.update_reservation_fields` -- the real name is
      `update_lease_fields`. It shipped, and the e2e run showed
      `create_job_id` still null with an `AttributeError` logged from inside
      `attach_executor_job`.

      Three things had to line up for that to reach a run. The signature was
      read from partway into the method and the *name* inferred rather than
      checked. `capacity_ledger` is typed as `Any | None`, which is what let a
      compile and lint pass say nothing. And the orchestrator-level tests used
      a fake transaction, so they asserted the call was *made* and never that
      it lands -- the one assertion that would have failed.

      The best-effort `except` is the fourth: it is deliberate, because a
      missing diagnostic handle must not fail a working fulfillment, but it
      also means the only signal was a warning line in a container log.

      Now exercised against a real `CapacityLedgerService` over a real SQLite
      ledger, reading the value back off the reservation rather than trusting
      the call. Two of the three new tests fail against the shipped version.
      A test of a duck-typed collaborator that only checks the call happened
      is not a test of the collaborator.

- [x] 10.8 **The corrected method name then deadlocked against its own
      caller.** `update_lease_fields` is the right name, but it is the
      session-owning form: it opens a session of its own and commits.
      `attach_executor_job` is called from inside the acknowledgement
      transaction — by design, per 10.6 — and that session has already
      written, so it holds SQLite's single writer slot. The ledger's second
      session cannot take that slot while its own caller holds it, so it
      waited out the provisioning service's 30s busy timeout and raised
      `database is locked`.

      The best-effort `except` absorbed it for the second run running, so
      `create_job_id` was still null. The new symptom was the latency: the
      30s stall sat inside `POST /fulfillment/begin`, which pushed the
      `provision`/`job_submitted` stage event 30s past settlement submission
      and timed out the e2e's 15s wait at stage `08b` in both VM scenarios —
      failing *earlier* than 10.7 did, which turned nine passing downstream
      stages into skips via `require_state`.

      Fixed by splitting `update_lease_fields` the way
      `assign_settlement_resource` was already split: a session-owning
      wrapper that commits, delegating to `update_lease_fields_in_session`,
      which neither commits nor takes the ledger lock.
      `attach_executor_job` passes `self.db`, which is what makes 10.6's
      same-transaction guarantee true rather than merely intended. The
      sibling `SqlAlchemySchedulingTransaction` was already doing this
      correctly for five ledger calls, including a write
      (`assign_settlement_resource_in_session`) — the convention existed and
      was one module away.

      `db/database.py`'s busy timeout is documented as keeping contending
      sessions waiting instead of erroring. That reasoning holds only for
      *independent* writers; when the contender is inside the lock holder's
      own call stack, waiting cannot succeed, so the timeout converts an
      immediate error into a guaranteed 30s stall followed by the same error.
      A busy timeout is not a defence against self-contention.

      Neither existing test could see it, for two independent reasons: the
      transaction was constructed with a `MagicMock()` session, which holds
      no writer slot, and the ledger fixture used a `StaticPool` in-memory
      engine, which shares one connection across every session so no two
      connections ever contend. The regression test makes both halves real —
      a file-backed engine and a genuinely held `BEGIN IMMEDIATE` — with a
      1s busy timeout so a recurrence fails in a second rather than thirty.
      It reproduces `database is locked` on the unpatched tree.

      One of the two tests first written for this passed unpatched and had to
      be rewritten: asserting that a caller's rollback discards the handle
      held for the wrong reason, because unpatched the write never lands at
      all. It now also asserts the value is visible inside the caller's
      session before the rollback, which fails both unpatched and against a
      ledger that committed independently. Same lesson as 10.4 and 10.7,
      third occurrence: a new test that has not been run against the
      unpatched tree is not yet evidence.

- [x] 6.8 **Roadmap currency** (added 2026-08-06 by `add-development-roadmap`, which extended `openspec/README.md#plan-closeout-requirements` from five parts to six). Update this change's rows in `docs/development/ROADMAP.md` — it currently appears as an open gap under both Goal 1 (stale physical-placement fields on the current fulfillment path) and Goal 2 (accepted VM shape not reaching the provisioning request) — and record the update in the design-promotion record. Appended rather than folded into 6.6, per `AGENTS.md`'s rule to amend rather than replace implementation history.
      **Done (2026-09-14).** Both rows removed from `docs/development/ROADMAP.md`:
      the goal-1 row under physical-resource authority and the goal-2 row under
      negotiating full compute capability. A closed gap is not marked closed in
      place -- the convention is that each goal carries a present-tense current
      state and a table of *open* gaps only -- so the delivered behaviour was
      folded into both current-state texts instead: that the committed claim now
      governs the fulfillment request, and that what is agreed reaches the
      provisioning request even though publication still loses the shape. The
      goal-1 text also names the one outstanding cleanup and its owner, so the
      `vm_remove_job_id` mirror is not silently dropped from the roadmap along
      with the gap that carried it.
- [x] 6.9 **Campaign index currency** (part seven, added when `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven). Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend rather than replace implementation history. Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
      **Done (2026-09-14).** Row updated to `complete; awaiting archival` with
      the green e2e run named as its proof, and the campaign's dependency graph
      changed from `fix-vm-fulfillment-capacity-boundary (independent)` to point
      at its successor. Two change directories were created in this step, so
      their rows and links were reconciled in the same edit per part six's rule
      that a link to a directory that does not exist is a blocking defect:
      `retire-vm-remove-job-id` in this goal's table, and
      `sign-multi-language-credits-middleware` under the local end-to-end stack
      campaign that opened it. Every `](<dir>/)` link in the index was checked
      to resolve to a real directory.

### Design-promotion record

| Material decision | Permanent documentation destination |
|---|---|
| Committed reservation dimensions are authoritative for fulfillment shape | `openspec/specs/site-capacity/spec.md` — “Committed dimensions remain authoritative through scheduling” |
| Physical providers translate canonical dimensions through a pool-selected registered requirement delegate | `openspec/specs/physical-provisioning/spec.md` — “Provisioning shape comes from committed capacity” and “Ansible fulfillment adapter” |
| Delegate identifier, registry validation, and provider-config snapshot semantics | `openspec/specs/resource-pool-management/spec.md` — “Registered requirement delegates” |
| A lease's release handle is `release_job_id` on both lease contracts; `vm_remove_job_id` is a retired mirror | `openspec/specs/site-capacity/spec.md` — carried into [`retire-vm-remove-job-id`](../retire-vm-remove-job-id/), which owns the removal |
| An explicit convergence cycle must be able to reach rows the worker itself claimed, or "run one cycle" is not a step | `docs/development/TESTING.md` — “Pause the loop, then advance it explicitly” |
| A best-effort write inside a caller's transaction uses the caller's session, never a second one | Code docstring: `market_site.ledger.update_lease_fields_in_session` |
| Internal packages are consumed from `.dist` wheels rather than relative editable sibling paths | Existing `docs/development/ARCHITECTURE.md` packaging/dependency section; amend only if the current text is insufficient |
| Root build composition delegates domain artifact ownership to `domains/Makefile` | Existing repository build guidance in `AGENTS.md`/`ARCHITECTURE.md`; no new permanent rule unless implementation finds a gap |
