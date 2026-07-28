## Why

An external review of `dev` at `648682c67a26caf9283492e999923ab6ca1206ee`, done ahead of the first real single-buyer/single-GPU (B1/G1) qualification run, found three current-path defects that block a trustworthy ordinary VM fulfillment: the storefront's obligation-fulfillment path requires physical-placement fields (`resource_id`, `vm_host`) the opaque capacity-reservation boundary deliberately does not return; the accepted VM shape (GPU/CPU/RAM/disk) is reserved correctly but never reaches the provisioning request, so a GPU-reserving listing can silently fulfill without a GPU; and a corrupted line in the GPU-attachment-discovery Ansible task corrupts its own "skip empty entries" logic. All three were confirmed against the code, not just the review's description — see this change's `design.md` for the trace.

A fourth reviewed item (durable teardown lacking a current full-deal e2e proof) is already tracked as POOLS-7 task 10.14 and stays there, deferred to the post–Section 11 POOLS-7 review loop by prior explicit direction; this change does not touch it.

## What Changes

- Make `resource_id` optional on the capacity-commit wire contract, matching what `CapacityLedgerService.commit()` already does internally when `capacity_reservation_id` is supplied (true for every current caller) — no behavior change to `commit()` itself, only removal of an over-constrained request field.
- Remove the storefront's stale `vm_host`-required guard in `fulfill_vm_obligation`, which blocks on a value `_do_provision`/`schedule_resource()` already documents as unused for resource selection.
- Stop persisting the literal string `"None"` as `settlement_resource_id` when a reservation response omits `resource_id`, before `schedule_resource()` has run and established the real value.
- Document, at the code sites this change touches, why `resource_id`-only reservation lookup (no `capacity_reservation_id`) exists with no current caller, and what future caller shape would use it — see Non-Goals and `design.md`.
- Derive `VmFulfillmentRequirements`' shape fields (`vm_gpu_count`, `gpu_provisioned`, `vm_vcpus`, `vm_ram`, `vm_disk_size`) from the reservation's own committed `CapacityReservationDebit.dimensions` at fulfillment-request construction time, instead of the storefront re-transmitting a separately-computed copy that is never authoritative and can only ever redundantly restate what the reservation already carries.
- Share VM compute-requirement field definitions between the storefront and provisioning adapter through `arkhai_vms` (already a dependency of both), rather than each side maintaining an independently-named vocabulary for the same dimensions.
- Fix the corrupted shell line in `vm-management/tasks/vm-create.yml`'s GPU-attachment-discovery task (and its identical, unreferenced copy in `roles/vm-management/backup/original-main.yml`).
- Add a reusable shell-logic test harness (fake-binary `PATH` shimming + real `bash` execution) to `domains/vms/provisioning/iac/tests`, since the existing test file only asserts substrings against YAML text and would not have caught this class of bug.
- Add integration coverage that exercises the real `RemoteCapacityClient` → `kit/site` HTTP boundary end to end for VM obligation fulfillment, rather than only in-process fakes that could mask a wire-contract mismatch the way this one was masked.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: capacity-commit wire contract no longer requires `resource_id`; reservation dimensions become a read path for fulfillment-request construction, not only for admission/matching.
- `physical-provisioning`: VM fulfillment-request construction derives shape requirements from the committed reservation rather than accepting them from the caller.
- `fulfillment` (VM provisioning IaC, not the `kit/fulfillment` package): corrected GPU-attachment-discovery shell logic.

## Dependencies and Related Changes

- Independent of `pools-7-storefront-fulfillment-cutover` Sections 10/11 — this fixes defects on the *current* obligation-fulfillment path (reservation, capacity commit, VM shape propagation), not teardown or schema removal. No ordering dependency either direction.
- The fourth reviewed item stays exactly where it already lives: POOLS-7 task 10.14 (`openspec/changes/pools-7-storefront-fulfillment-cutover/tasks.md`), deferred to the final POOLS-7 review loop.
- Forward-looking design notes for a not-yet-built direct-physical-resource reservation path (no current caller) are recorded in `design.md` for whoever eventually builds that path, and are explicitly out of scope for this change — see Non-Goals.

## Non-Goals

- Do not implement direct-physical-resource capacity reservation (reserving by `resource_id` without a pool-derived claim). No current caller needs it; `design.md` records the two accepted design notes and one open capability gap (preemption/eviction of other reservations off a physical resource to secure it wholly) for whenever that path is actually built.
- Do not implement reservation resizing as a live code path. `resize_reservation` already exists and is correctly shape-agnostic (handles growing or shrinking a claim identically); this change does not add a caller for it. It documents, as an accepted invariant this change's design depends on, that negotiated-requirement changes must resize the reservation before scheduling — enforcement of that invariant is future work, not this change.
- Do not rewrite the VM full-deal e2e teardown suite (POOLS-7 task 10.14, unaffected by this change).
- Do not change capacity-reservation admission, matching, or fairness policy.
- Do not add GPU preemption/eviction capability.

## Permanent documentation impact

- [ ] Existing subsystem specification
- [x] No permanent documentation change (for the `resource_id`/`vm_host` cleanup and shell-logic fix specifically — see below)

### Knowledge to promote

- The `resource_id`/`vm_host` fixes (Decisions 1–3 in `design.md`) restore already-documented intent — `site-capacity/spec.md` already states the opaque-reservation MUST NOT requirement these fixes satisfy — so no new permanent documentation is needed for them beyond the in-code comments this change adds.
- The VM shape derivation fix (Decision 4) *is* new normative current-system behavior once implemented and validated: "VM fulfillment-request shape requirements are derived from the reservation's committed dimensions, not accepted from the caller" belongs in `openspec/specs/site-capacity/spec.md` and/or `openspec/specs/physical-provisioning/spec.md`. Deferred to `tasks.md` §4.2, promoted only after 3.1–3.6 land, not during this planning pass.
- Forward-looking notes for the direct-physical-resource reservation path (`design.md`'s final section) are explicitly *not* promoted anywhere — that capability doesn't exist yet. They stay in this change's `design.md` for whoever plans that path next.
