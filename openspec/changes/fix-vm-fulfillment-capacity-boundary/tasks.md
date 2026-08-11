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
- [ ] 6.8 **Roadmap currency** (added 2026-08-06 by `add-development-roadmap`, which extended `openspec/README.md#plan-closeout-requirements` from five parts to six). Update this change's rows in `docs/development/ROADMAP.md` — it currently appears as an open gap under both Goal 1 (stale physical-placement fields on the current fulfillment path) and Goal 2 (accepted VM shape not reaching the provisioning request) — and record the update in the design-promotion record. Appended rather than folded into 6.6, per `AGENTS.md`'s rule to amend rather than replace implementation history.

### Design-promotion record

| Material decision | Permanent documentation destination |
|---|---|
| Committed reservation dimensions are authoritative for fulfillment shape | `openspec/specs/site-capacity/spec.md` — “Committed dimensions remain authoritative through scheduling” |
| Physical providers translate canonical dimensions through a pool-selected registered requirement delegate | `openspec/specs/physical-provisioning/spec.md` — “Provisioning shape comes from committed capacity” and “Ansible fulfillment adapter” |
| Delegate identifier, registry validation, and provider-config snapshot semantics | `openspec/specs/resource-pool-management/spec.md` — “Registered requirement delegates” |
| Internal packages are consumed from `.dist` wheels rather than relative editable sibling paths | Existing `docs/development/ARCHITECTURE.md` packaging/dependency section; amend only if the current text is insufficient |
| Root build composition delegates domain artifact ownership to `domains/Makefile` | Existing repository build guidance in `AGENTS.md`/`ARCHITECTURE.md`; no new permanent rule unless implementation finds a gap |

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



## 10. Placement identity on the admin reservation path

Added 2026-08-11. Section 2 removed the storefront's dependence on placement fields along
the obligation-fulfillment path and added a boundary test asserting `/reservations` never
returns `resource_id`, `capacity_bucket_id`, or `backing_resource_id` (task 2.7). It missed
the admin reservation path, which still dereferences the stripped field and returns 500 —
observed in the nightly e2e as
`POST /api/v1/admin/portfolio/reservations` → `KeyError: 'resource_id'`. The same audit
found the response carries no usable pool identity either, and that the comment explaining
why asserts an authority the site does hold. See `design.md`'s "Placement identity is
echoed from the claim, never reported by the site".

- [ ] 10.1 Confirm 9.2's open item is closed by inspection: `vm_host` is in
      `/reservations`' strip set today. Record the finding rather than the checkmark alone —
      9.2 recorded it as not done and needing a decision.
- [ ] 10.2 Add `pool_id` and `member_id` to the strip set in
      `kit/site/src/market_site/router.py`'s reserve route. Stripping rather than returning
      a present-and-`None` field is the point: the `None` is what produced
      `admin_controller`'s `reserved.get("pool_id") or (reserved.get("attributes") or {}).get("pool_id")`
      fallback chain, which only reads the attribute because the first term is always empty.
- [ ] 10.3 Replace `_match_payload`'s "pool/member are storefront (aggregator) concepts the
      site does not know" comment in `kit/site/src/market_site/ledger.py`. The site owns
      pool membership; the reason the field is absent is that a reservation commits to a
      site and a shape and to nothing narrower, so reporting the pool the site happened to
      match would advertise a placement scheduling is free to change. `member_id` is
      aggregator bookkeeping with no site-side meaning. State both reasons separately.
- [ ] 10.4 Source `ReserveCapacityResponse`'s `resource_id` and `pool_id` from the request's
      own claim in `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`,
      not from the reservation payload. A claim that pins either already carries it; a claim
      that pins neither must report neither.
- [ ] 10.5 Make `resource_id` optional on both response models —
      `market_storefront/models/capacity_admin_models.py` (currently a required `str`) and
      `core/storefront-client/src/storefront_client/models.py` (currently defaults to `""`,
      which reads as a present empty identity rather than an absent one). Keep the two in
      step and cover them with the sync/async parity contract test `TESTING.md` requires.
- [ ] 10.6 Audit the remaining reservation-payload readers for the same pattern:
      `fulfillment_resume_runtime`'s `settlement_resource_id` write (guarded, so it now
      persists `None` on every recovery — confirm that is correct rather than assumed, since
      the fulfillment scheduler owns that selection) and `vm_job_spec_service`'s
      `selected["resource_id"]`/`selected["vm_host"]` off `probe()`, which the probe route
      does not strip. Record the probe asymmetry as a finding for
      `negotiation-capacity-feasibility-probe`, which owns that payload's shape; do not
      change it here.
- [ ] 10.7 Extend task 2.7's boundary-contract test to cover `pool_id` and `member_id`, so
      the assertion protects every future caller rather than the fields known in July.
- [ ] 10.8 Integration test the admin reservation path through the real router for both
      claim shapes: a resource-pinned claim reports its resource and no pool, a pool-scoped
      claim reports its pool and no resource, and neither raises. The unit level cannot
      catch this — `_match_payload` includes `resource_id` in-process and only the HTTP
      boundary strips it, which is why the defect survived a green suite.

### Section 10 closeout

Per `openspec/README.md#plan-closeout-requirements`, scoped to this section.

- [ ] 10.9 **Comment hygiene.** Run `make check-comment-hygiene`. Read 10.3's and 10.4's
      comments directly: both replace text that stated the wrong reason, and a comment
      asserting an authority the code does not hold is a defect in this change rather than a
      wording preference.
- [ ] 10.10 **Import placement.** Nothing in this section is expected to add an import;
      confirm rather than assume, and record the disposition.
- [ ] 10.11 **Documentation compliance.** The opaque-reservation requirement in
      `openspec/specs/site-capacity/spec.md` already covers physical-resource identity.
      Confirm whether it also covers pool identity as written; if it does not, the delta is
      a spec amendment, not an in-code comment.
- [ ] 10.12 **Narrative compression.** Keep these notes at final behaviour and evidence
      once implemented; the trace belongs in `design.md`.
- [ ] 10.13 **Roadmap currency.** Goal 1's gap row for this change names stale
      physical-placement fields on the fulfillment path, which this section extends to the
      admin path without changing the gap's shape. Confirm at closeout and record the
      disposition explicitly rather than omitting the step.
- [ ] 10.14 **Promotion.** Add this section's rows to the design-promotion record.

### Section 10 design-promotion record

See `design.md`'s "Design-promotion record" table.
