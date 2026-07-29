## Context

An external review of `dev` at `648682c67a26caf9283492e999923ab6ca1206ee` was done ahead of the first real single-buyer/single-GPU (B1/G1) qualification run — real KVM/Ansible provisioning, real GPU passthrough, the ordinary public buyer/seller path. The review deliberately excluded harness, private-driver, agent-orchestration, and branch-governance issues, and flagged four current-path defects. Three are addressed by this change; the fourth (durable teardown e2e proof) is already POOLS-7 task 10.14 and is untouched here.

Every finding below was independently traced against the actual code before being accepted, not taken on the review's word — see the corresponding conversation turns for the full trace. This document records the resulting decisions.

## Goals / Non-Goals

**Goals:**
- Make the storefront's ordinary VM obligation-fulfillment path work through the real `RemoteCapacityClient` → `kit/site` wire boundary, with no dependence on fields that boundary deliberately does not return.
- Make a GPU-reserving listing's fulfillment request actually carry GPU intent to the provider, sourced from something that cannot drift from what capacity accounting actually committed.
- Fix the corrupted GPU-attachment-discovery shell logic and add a test category capable of catching this class of bug.
- Leave a clear, documented trail for the not-yet-built direct-physical-resource reservation path so it does not have to rediscover these boundary decisions.

**Non-Goals:**
- Do not build the direct-resource reservation path itself.
- Do not wire a live caller for `resize_reservation`.
- Do not touch POOLS-7 task 10.14 or its scope.

## Decisions

### Capacity-commit no longer requires `resource_id`

`CapacityLedgerService.commit()` already declares `resource_id: str | None = None` and, when `capacity_reservation_id` is also supplied, ignores the parameter entirely — `_find_reservation` looks the reservation up purely by `capacity_reservation_id`, and the `CapacityEvent` it records resolves the backing resource internally via `_backing_resource_id(db, capacity_reservation_id)`. Every current caller supplies `capacity_reservation_id`. `CommitRequest.resource_id: str` at the HTTP wire layer (`kit/site/src/market_site/http_models.py`) is therefore a mandatory field guarding a value the method behind it never reads for these callers.

Traced with the direct-resource-reservation use case specifically in mind (see "Forward-looking notes" below) before accepting this: the `/reservations/{capacity_reservation_id}/commit` endpoint takes `capacity_reservation_id` as a mandatory **path** parameter, not from the request body. That means `_find_reservation`'s `resource_id`-only lookup branch (used when `capacity_reservation_id` is absent) is structurally unreachable through this endpoint regardless of what the request body's `resource_id` says. A resource-pinned claim (a listing carrying `resource_id`, per `site-capacity/spec.md`) still mints and uses a `capacity_reservation_id` through `reserve()`, so it does not exercise this branch either. Making `CommitRequest.resource_id` optional cannot regress any current caller, including the resource-pinned listing case, because none of them depend on the request body's `resource_id` reaching `_find_reservation` at all.

**Rejected alternative:** redesigning the wire contract's shape (e.g., dropping `resource_id` from `CommitRequest` entirely, or adding a new no-`resource_id` commit endpoint) — unnecessary. The field already tolerates absence at every layer that matters; only its pydantic-enforced mandatoriness needs to change.

### `vm_host`-required guard removed as stale, not redesigned

`fulfill_vm_obligation` raises `RuntimeError("Reserved resource missing vm_host")` before calling `provision_vm`/`_do_provision`. `_do_provision`'s own docstring already states `vm_host` is accepted only "for call-site compatibility" and is not used for resource selection — `schedule_resource()` re-confirms or fairness-reassigns the settlement resource independent of which host the reservation bound at reserve time. The guard predates that update to `_do_provision` and was never removed. `vm_host`/`resource_id` remain useful, non-blocking values for `stage_event(...)` telemetry (already their only other use in this function) — populate when available, never gate control flow on them.

### Stop persisting the string `"None"` as `settlement_resource_id`

`reserved_resource_id = str(reserved.get("resource_id"))` converts an absent value into the literal three-character string `"None"`, persisted via `persist_escrow_fields_with_retry(..., settlement_resource_id=reserved_resource_id, fulfillment_phase="capacity_reserved")` before `schedule_resource()` runs. On the happy path this is silently overwritten once `_do_provision` calls `schedule_resource()` and persists the real `settlement_resource_id`. If fulfillment fails or the process dies in that window, a stuck order is left with the string `"None"` as its persisted settlement resource — a forensics trap. This call either stops persisting `settlement_resource_id` at this early phase (deferring the field entirely to the post-`schedule_resource()` write that already exists) or persists an actual `None`/omits the field rather than a string.

### VM shape requirements are derived from the committed reservation, not re-transmitted

Traced whether the storefront's separately-computed `required_attributes` (via `compute_capacity_claim_from_order`) could ever legitimately diverge from the reservation's own committed dimensions before deciding this. It cannot, today: `_place_capacity_hold` places the TTL soft hold "at terms acceptance" (its own docstring), computing the claim via `compute_capacity_claim_from_order(order_dict)` on the terminal, post-negotiation order — the same function and the same data the later fulfillment path uses to compute `required_attributes`. `resize_reservation` — the only mechanism that could change a reservation's dimensions after creation — has zero callers anywhere in the codebase. So the reservation's `CapacityReservationDebit.dimensions` and the fulfillment path's `required_attributes` are, by construction, always identical; passing the latter into the fulfillment request is not "authoritative vs. secondary," it is recomputing something already durably recorded on the reservation.

`PhysicalSettlementScheduler.schedule_resource()` already resolves the full reservation payload, dimensions included, when it runs — no new site-ledger access is needed to obtain the data. The gap is threading it from there to wherever `VmFulfillmentRequirements` is actually constructed, today inside `AnsibleFulfillmentProvider` in `domains/vms/provisioning/adapter`, a separate package from `kit/fulfillment`. This is real, contained plumbing work, not a design fork: either the generic type already flowing from scheduling into the provider's `prepare_create` carries the dimensions forward, or the provider (which already has ledger access) reads them directly at that point. Task-level planning decides which; both are consistent with this decision.

The reservation carries canonical VM-domain dimensions (`gpu_count`, `vcpu_count`, `ram_gb`, and `disk_gb`) with stable domain meanings. It does not carry Ansible variable names, playbook-specific encodings, or unit conversions.

Each Ansible-backed VM resource pool configures both:

- the playbook that implements fulfillment; and
- a **requirement delegate** identifier naming the registered adapter class that validates the selected playbook contract and translates canonical reservation dimensions into that playbook's variables.

The provider resolves the configured identifier through an explicit registry of allowed delegate classes. Resource-pool configuration MUST NOT name an arbitrary Python import path. This keeps configuration declarative and reviewable while allowing two valid VM playbooks to use different variable names, units, ranges, or derived values. The delegate is snapshotted and validated as part of provider configuration so fulfillment uses the same interpretation that was accepted for the pool.

The delegate boundary separates two forms of validation:

- VM-domain validation defines the canonical meaning and numeric shape of reservation dimensions without knowing any playbook contract.
- Delegate validation determines whether the configured playbook can represent the committed dimensions and performs playbook-specific conversion, such as GiB-to-MiB conversion or derived GPU booleans.

The initial registry contains the delegate for the repository's current VM-management playbook. A new playbook contract requires a new registered delegate and tests; this change does not introduce a general mapping or expression language in resource-pool metadata.

**Rejected terminology:** `profile` was rejected because the repository's configuration system already uses that term and a resource-pool configuration field with the same name would be ambiguous.

**Rejected alternative:** placing Ansible-facing mappings and conversions in `arkhai_vms`. The VM domain owns canonical dimension vocabulary, but playbook variable names and units are adapter-specific and may differ between otherwise valid providers in the same domain.

**Accepted invariant this decision depends on, not yet enforced in code:** if a negotiated requirement ever changes after a hold is placed, the reservation must be resized (via `resize_reservation`, once it has a caller) *before* `schedule_resource()` runs, not worked around by re-deriving shape from the order at fulfillment time. This is deliberately not enforced by this change, since nothing currently changes requirements post-acceptance — but it is the reason re-transmission was rejected as a "just in case" safety net rather than accepted as harmless redundancy. Whoever eventually gives `resize_reservation` a caller must resize before scheduling, not after, or this decision's premise breaks silently.

**Rejected alternative:** independently deriving shape on both sides and failing closed on disagreement. Rejected once the above trace showed there is currently nothing for the two derivations to disagree about — they are the same computation performed twice. Revisit if `resize_reservation` ever gets a caller that does not resize strictly before scheduling.

### Forward-looking notes for the direct-physical-resource reservation path (not built by this change)

Recorded here because tracing this change surfaced them; not part of this change's scope. Two accepted outcomes, and one open capability gap:

1. **The direct-resource path still goes through a capacity reservation.** It must not bypass `capacity_reservation_id` — it uses `reserve()`'s existing resource-pinned claim shape (`claim` carrying `resource_id`), which already mints a `capacity_reservation_id` the normal commit/schedule/fulfillment flow can use unchanged.
2. **A negotiated-requirement change must resize the reservation before scheduling**, per the invariant above — not be re-applied at fulfillment time.
3. **Open gap:** the review's stated goal — securing an entire physical resource for one reservation — needs the ability to preempt/evict other reservations currently holding capacity on that resource, which does not exist today. `reserve()`'s resource-pinned claim only succeeds against *available* capacity on the named resource; it has no mechanism to reclaim capacity already held by other reservations to make room. This is a genuinely new capability (eviction/preemption semantics: what happens to a preempted reservation's in-flight deal, what authorizes preemption, whether it is soft-hold-only or can interrupt an active lease) and needs its own design pass whenever the direct-resource path is actually planned. Not scoped or designed here.

### Code-review planning decisions

The following corrections were accepted during code review and are part of this change's implementation plan:

- The repository root delegates domain distribution as one aggregate operation to `domains/Makefile`; it does not mirror each domain wheel as a root target. `domains/Makefile` owns the complete domain wheel set, dependency order, and aggregate test entry points or explicit packaging-only exemptions.
- The VM provisioning adapter's entire `[tool.uv.sources]` block is brought into compliance while this file is being changed. Internal dependencies are installed from wheels already produced under `.dist` through the repository's `reinit` pattern. Missing wheels are added to the aggregate `make dist` chain rather than replaced with relative editable paths.
- Fulfillment shape uses one strict, field-independent precedence rule: committed reservation dimensions are authoritative. Caller-supplied shape fields are never fallback inputs. Defaults may apply only to provider settings explicitly outside the reservation-governed shape.
- The boundary regression test must cover the complete `reserve → commit → schedule_resource() → begin_fulfillment()` path through the real HTTP boundary. A commit-only test is useful but does not satisfy this requirement.
- `roles/vm-management/backup/original-main.yml` is deleted if implementation confirms it remains unreferenced.



### Design promotion record

| Material decision | Permanent documentation |
|---|---|
| Committed reservation dimensions are authoritative for fulfillment shape | `openspec/specs/site-capacity/spec.md`, "Committed dimensions remain authoritative through scheduling" |
| Providers derive shape from scheduled reservation dimensions rather than caller retransmission | `openspec/specs/physical-provisioning/spec.md`, "Provisioning shape comes from committed capacity" |
| Ansible pools select an allowlisted requirement delegate alongside the playbook | `openspec/specs/resource-pool-management/spec.md`, "Registered requirement delegates"; `openspec/specs/physical-provisioning/spec.md`, "Provisioning shape comes from committed capacity" |
| Delegate validation and accepted-operation snapshot semantics | `openspec/specs/resource-pool-management/spec.md`, "Registered requirement delegates" |

## Post-implementation corrections

Defects found after the initial implementation, each resolved to a current
decision. Historical review provenance (who found what, when, in which
pass) is not repeated here — see git history / PR review for that.

### Post-provision fulfillment calls were still gated on opaque fields

`fulfill_vm_obligation`'s post-provision `capacity.commit(...)` and
`register_lease(...)` calls were gated on `resource_id`/`vm_host`, which
are legitimately absent on an ordinary pool-scoped reservation. Both
silently no-op'd — the lease-window refresh and the watchdog registration
this change's design depends on for auto-release never ran on the exact
path this change exists to make trustworthy.

**Decision:** both gates key on `capacity_reservation_id` (always present)
instead. `resource_id`/`vm_host` remain optional, unused arguments to both
calls — neither ever read them (`commit()` ignores `resource_id` whenever
`capacity_reservation_id` is supplied; `register_lease`'s `LeaseRegistration`
never read either field, since `executor_ref` self-heals from the
independently-written `reservation.vm_host`).

Regression test: `test_post_provision_commit_and_lease_registration_do_not_require_resource_id`
(`test_fulfillment_provisioning.py`), using the real opaque-reservation
shape.

### `vm_host` was not stripped from the reservation response

`vm_host` is real physical-placement data, populated at `reserve()` time,
that was never added to the response-stripping list alongside
`resource_id`/`capacity_bucket_id`/`backing_resource_id`.

**Decision:** stripped. `resource_id`/`vm_host` are an optional
pinning/telemetry pathway (resource pools exist so buyers negotiate on
pooled capacity, not a pinned physical node); no code should depend on
either being present for ordinary fulfillment. All references to `vm_host`
in stage-event/log telemetry removed accordingly (functional passthrough
to `provision_vm`/`register_lease`/`schedule_shutdown` left as-is — already
accepted-but-unused compatibility parameters).

### Scheduled dimensions vs. reservation dimensions

`SettlementResource.dimensions` reports the *scheduled* shape (bounded by,
but not necessarily equal to, the reservation), confirmed by
`test_scheduled_dimensions_reflect_narrowed_request_not_full_reservation`.
This is correct behavior, not a bug: negotiation resizes the reservation
via `resize_reservation` (supersede, never mutate) when a shape genuinely
changes; a scheduling request may separately narrow for a placement/pricing
check without committing to that resize yet.

**Rejected alternative:** always reporting the reservation's full committed
dimensions regardless of what was scheduled. Would silently deliver the
pre-negotiation shape after a buyer negotiated down — a correctness/billing
defect in the opposite direction from this change's original purpose.

**Decision:** no scheduler code change (it already behaved correctly).
`site-capacity/spec.md` and `physical-provisioning/spec.md` corrected —
both overclaimed that the reservation's own dimensions are unconditionally
authoritative; the scheduled, reservation-bounded dimensions are.
`docs/development/ARCHITECTURE.md` gained the repository-wide statement of
the premise this depends on (pooled-capacity negotiation, not physical-node
pinning; a negotiated shape change resizes the reservation).

**Open, not resolved by this change:** `resize_reservation` has no
negotiation-side caller yet. The corrected specs describe intended design;
wiring negotiation to it is separate, larger work.

### Adapter lockfile was not portable

`domains/vms/provisioning/adapter/uv.lock` still recorded stale
editable-source resolutions after `pyproject.toml`'s `[tool.uv.sources]`
block was cleaned. Root cause: the root `Makefile`'s `test-domain-dist-reinit`
target passed its own absolute `DIST_DIR` into `uv sync --find-links`,
which bakes that literal machine-specific path into `uv.lock`'s
`source = { registry = ... }` entries on every regeneration.

**Decision:** stopped propagating the absolute override; the adapter's own
already-correct relative default (`DIST_DIR ?= ../../../../.dist`) applies
instead. Regenerated lock verified free of absolute paths; target's own
test scope (25 tests) still passes.

### Cross-service test coverage

Two gaps identified against the merged head: the boundary test only
asserted up to `dispatching` (not a terminal state), and it ran in no CI
job (`.github/workflows/tests.yml` triggers on `staging` only and its
matrix omits several touched packages entirely).

**Decision:** the "inspect prepared values under conflicting caller
fields" gap is satisfied by
`test_ansible_fulfillment_provider.py::test_request_supplied_sizing_is_ignored_even_when_present`,
a more appropriate layer for that proof than the heavier cross-service
test. The cross-service test tier itself was later retired in favor of a
mock-transport client test plus existing e2e coverage — see
`openspec/changes/refactor-e2e-fulfillment-lifecycle`.

**Unresolved:** the CI-matrix gaps (missing packages, staging-only trigger)
remain open pending a repository-owner decision on priority, since GitHub
Actions isn't part of the current local workflow.

## Design-promotion record

| Material decision | Permanent location |
|---|---|
| Post-provision lease refresh/registration key on `capacity_reservation_id`, never `resource_id`/`vm_host` | `openspec/specs/site-capacity/spec.md`'s opaque-reservation-boundary requirement |
| `resource_id`/`vm_host` are an optional pinning/telemetry pathway, not the primary negotiation unit; covers any domain-specific physical field, not just generic accounting identifiers | `openspec/specs/site-capacity/spec.md`, "Capacity accounting is private to the site authority" |
| Scheduled (reservation-bounded) dimensions, not the reservation's own dimensions unconditionally, are authoritative for what a provider builds | `openspec/specs/site-capacity/spec.md`, "Committed dimensions remain authoritative through scheduling" |
| Providers derive shape from the scheduled settlement resource | `openspec/specs/physical-provisioning/spec.md`, "Provisioning shape comes from committed capacity" |
| Capacity reservations negotiate pooled capacity, not a pinned physical resource; a negotiated shape change resizes the reservation; `resize_reservation` has no caller yet | `docs/development/ARCHITECTURE.md`, "Capacity reservation" |
| `test-domain-dist-reinit` must not propagate an absolute `DIST_DIR` into the adapter's lock regeneration | In-code comment on the `Makefile` target; build tooling, not subsystem behavior, so no `openspec/specs` entry |

