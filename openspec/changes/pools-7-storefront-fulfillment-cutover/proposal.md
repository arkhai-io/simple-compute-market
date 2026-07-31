## Why

`pools-2-physical-settlement-scheduler` and `pools-3-fulfillment-provider`
build a generic-scheduling-then-provider-execution path
(`PhysicalSettlementScheduler.select_resource` → `FulfillmentProvider.create`)
inside the extracted compute provisioning service, but **nothing calls it**. The
storefront's actual fulfillment path today (verified against current code,
not assumed) is entirely separate:

- `vm_fulfillment_service.py` reserves capacity with
  `required_attributes=("vm_host",)` — the storefront picks the concrete
  physical host **at reservation time**, via `AggregateCapacityClient`
  placement policies (`fill_first`, `most_available` in
  `core_storefront/aggregation.py`).
- It then dispatches straight to the VM executor —
  `provisioning_orchestration_service.create_vm_and_wait_with_credentials`
  submits an `ExecutorActionEnvelope(action_kind="create")` directly via
  `ComputeProvisioningClient` and polls the job itself. This never touches
  `PhysicalSettlementScheduler` or any `FulfillmentProvider`.

So there are two parallel, non-interacting systems today: the one the
storefront actually uses, and the one `pools-2`/`pools-3` are building.
POOLS-7 reconciles these paths by cutting the storefront over to durable
physical-resource scheduling and fulfillment managed by the provisioning
service.

**Status note (2026-07-25, Section 9 design review):** the paragraph above
is this proposal's original motivating rationale and is kept as written for
that history, but two of its factual claims no longer describe current
code and should not be read as current: `vm_fulfillment_service.py`
reserves with a pool/resource/dimension-shaped claim today (POOLS-4
landed), not `required_attributes=("vm_host",)` — the reservation
response's `vm_host` is still read and dispatched to directly, which is the
actual remaining gap; and `PhysicalSettlementScheduler.select_resource`/
`FulfillmentProvider.create` were renamed to `schedule_resource`/
`FulfillmentOrchestrator.begin_fulfillment` by Sections 3-8. See `design.md`'s
"Section 9 design review" for the current, verified state.

## Current Rebaseline

The shared fulfillment package, multidimensional capacity model, shared feasibility predicate, two provisioning projection families, pull projection endpoints, and storefront in-memory projection loading/polling are now implemented. The production cutover is not: scheduling and fulfillment state remain process-local, provider dispatch is not durably recoverable, the storefront still calls the VM executor path directly, credentials remain persisted, teardown bypasses the provider lifecycle, and pull fulfillment status/results do not exist.

Implementation therefore resumes at the durable lifecycle/persistence work in tasks 3–12. Completed tasks remain recorded in `tasks.md`. Projection production and cache mechanics are no longer POOLS-8 scope; POOLS-8 owns residual durable projection consumption, commercial mapping, and listing hints.

## What This Change Covers

- Change the storefront's ordinary reservation path from host-shaped
  (`vm_host` required attribute) to pool-shaped, consuming
  `pools-4-storefront-capacity-boundary`'s reservation claim shape.
- Replace `create_vm_and_wait_with_credentials`'s direct
  `ExecutorActionEnvelope` dispatch with two provisioning-side calls the
  storefront invokes as separate operations — schedule
  (`PhysicalSettlementScheduler.select_resource`) and begin fulfillment
  (`FulfillmentService.create`) — plus an optional convenience operation
  that composes both for callers that don't need the pricing-preview
  behavior. **`FulfillmentService` does not call the scheduler and never
  will** (`pools-3`'s explicit, unchanged boundary decision); the
  storefront calls them in sequence because `select_resource`'s result
  can be commercially material before a deal is finalized (see
  `design.md`, "Storefront orchestrates scheduling and fulfillment as
  separate calls").
- **Result and credential retrieval is pull-based for this change**:
  `get_fulfillment_status`/`get_fulfillment_result`, read directly from
  durable state, over the existing storefront→provisioning auth
  direction. A push-based delivery transport was designed but requires a
  new provisioning→storefront authenticated channel that doesn't exist
  in this codebase yet — designing that channel is split out to a
  separate change, `provisioning-result-push-delivery`, rather than
  built inside this one. See `design.md`, "`SettlementResult` delivery:
  pull for v1, push deferred to a separate change."
- Resolve `pools-3`'s deferred release-path wiring: give
  `VmReleaseExecutor` (or its replacement) a way to resolve
  `SettlementRecord` → `ProviderRegistry.require(provider).teardown(...)`
  for allocations that went through the settlement path, now that a real
  caller exists to design the call shape against.
- Resolve `pools-2`'s deferred "persist Capacity Settlement Assignments...
  transactionally" follow-on item, now that `select_resource` will have a
  production caller and restart-safety actually matters. Decide then
  whether `PhysicalSettlementScheduler` should write through
  `SettlementRecord` directly or maintain separate assignment storage —
  this was explicitly punted by `pools-3` to avoid scope creep into the
  scheduler while there was no caller to design against
  (`pools-3`'s `design.md`, Risks).
- Add durable database-backed fulfillment idempotency keyed by
  `capacity_reservation_id`. Equivalent retries return the existing fulfillment;
  conflicting reuse fails before dispatch. Database uniqueness and
  transactions, not process-local locks, are the correctness mechanism.
  Explicitly handle recovery across the commit/queue-dispatch failure window.
- Snapshot resource-pool provider configuration into executor inputs when the
  fulfillment operation is accepted, and retain enough selected-resource and
  provider metadata for asynchronous teardown after restart.
- Decide the `AggregateCapacityClient` placement-policy fate:
  `fill_first`/`most_available` are storefront-side physical-placement
  logic that duplicates what `PhysicalSettlementScheduler`'s round-robin
  policy is meant to own. Likely removed or reduced to pool-level
  preference once the storefront stops picking concrete resources itself.

## Status

This change is active and design-complete. The design review completed on
2026-07-20, and `tasks.md` is the implementation plan for the cutover.

**Resolved scope, superseding the original activation gate below:**
this change retrofits the VM domain storefront and the extracted compute
provisioning service onto the POOLS 1-4 machinery. Compute-30 landed first and
moved service composition to `provisioning/compute/service`, VM/Ansible behavior
to `domains/vms/provisioning/adapter`, and bare-metal behavior to
`domains/bare_metal/provisioning/adapter`; POOLS-7 consumes that layout rather
than performing another service extraction. The shared fulfillment and
physical-settlement lifecycle, persistence, scheduler, provider contracts, and
recovery destination is the new `kit/fulfillment` package decided by this
change's design review. It sits above `kit/site` and `kit/resource-pools` in an
explicit one-way kit dependency hierarchy; authority kits may not import
`market_fulfillment`, deployed services, or domain adapters, including for type
checking. `kit/site` and `kit/resource-pools` may be modified where genuinely
cross-domain, and the `apicredits` domain is explicitly in scope for the same
capacity-reservation-against-a-pooled-view reshape, not just VM.

**Dependencies, current as of this review:**

- `pools-2-physical-settlement-scheduler` — implemented prerequisite.
- `pools-3-fulfillment-provider` — implemented prerequisite.
- `pools-4-storefront-capacity-boundary` — implemented prerequisite.
- `pools-6-multidimensional-fair-scheduling` — implemented prerequisite;
  multidimensional reservation and scheduler fit accounting landed before
  this change begins implementation.
- `pools-8-capacity-projection-and-listing-hints` — related and not blocking. POOLS-7 has already landed projection production, pull endpoints, and in-memory storefront caches; POOLS-8 now owns durable projection generations, explicit mapping into commercial publication/claim data, and listing/TTL hints.
- `market-platform-compute-30-extract-service` — implemented related change;
  it was not a behavioral prerequisite, but was selected to land first, so
  this plan now targets the extracted service and adapter paths.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

Each implemented section carries its own itemized design-promotion record in `design.md`, mapping every accepted decision to its exact permanent destination heading; this list is a proposal-level summary, not a substitute for those records.

- Kit dependency layers, package ownership, wheel/reinit conventions: `docs/development/ARCHITECTURE.md#package-and-dependency-layers`; `openspec/specs/fulfillment/spec.md` (new subsystem specification, added in this change).
- Capacity-reservation/resource-pool schema cutover, projection naming, and storefront projection caching: `openspec/specs/site-capacity/spec.md`, `openspec/specs/resource-pool-management/spec.md`, `openspec/specs/storefront-publication/spec.md` — see design.md's "Design promotion record" (Section 2).
- Durable settlement/fulfillment aggregate persistence, identity, and equivalence rules: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` — see design.md's "Section 3 correction design-promotion record".
- Atomic scheduling transaction and concurrency contract: `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment`; `docs/development/ARCHITECTURE.md#deterministic-database-concurrency-tests` — see design.md's Section 4 entries (4.8.3, 4.14.4).
- Fulfillment acceptance, provider preparation, and envelope/transaction shape: `openspec/specs/fulfillment/spec.md`, `openspec/specs/fulfillment/architecture.md`, `openspec/specs/resource-pool-management/spec.md` — see design.md's "Section 5 design-promotion record".
- Recovery/convergence claim semantics, provider-call transaction boundary, and convergence worker contract: `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` — see design.md's "Section 6 implementation promotion record".
- Legacy-lease-to-fulfillment cutover: lease-state mapping, atomicity, provider-owned teardown preparation, and the compiler/migration split: `openspec/specs/fulfillment/spec.md#existing-lease-continuity-during-fulfillment-cutover`, `openspec/specs/fulfillment/architecture.md#atomic-legacy-lease-cutover`, `openspec/specs/physical-provisioning/spec.md#vm-lease-migration-uses-current-provider-contracts`, `openspec/specs/physical-provisioning/architecture.md#preserving-provider-operations-across-schema-cutover`, `docs/development/ARCHITECTURE.md#atomic-workload-lifecycle-cutovers` — see design.md's "Section 7 implementation promotion record".
- Section 8 (pull-based status/result queries and live credentials) is implemented at the source level; its design-promotion record is `design.md`'s "Section 8 completed design-promotion record," promoted into `openspec/specs/fulfillment/spec.md` and `openspec/specs/physical-provisioning/spec.md#requirement-vm-fulfillment-result-payload`. The repository-standard wheel-based validation and `openspec validate --all --strict` this section's own text said would gate Section 9's start (tracked as task 8.15) were never actually confirmed closed before Section 9 work began — recorded here plainly rather than silently dropped, since the plan's own stated gate was not honored procedurally, whatever the practical risk turned out to be.
- Section 9 (storefront orchestration cutover and restart convergence) is complete after the 9.19–9.24 correction pass. Tasks 9.0–9.24 implement durable recovery context, a startup convergence worker, full post-physical settlement convergence, aggregate routing, and duplicate-safe ambiguous on-chain handling. Its permanent behavior is documented in `openspec/specs/vm-storefront-fulfillment/spec.md`, with supporting fulfillment and architecture updates recorded in `design.md`'s completed promotion records. Root `make test` passed. Strict OpenSpec validation was unavailable in both validation environments and was explicitly waived for this section. Section 10 (teardown and physical-resource reclamation) is complete after a review correction pass (tasks 10.9–10.16). Tasks 10.1–10.8 implemented `begin_fulfillment_teardown` and cut `VmReleaseExecutor` over to it through a kind-routed release-completion seam that leaves `LeaseLifecycleService` and bare-metal's release path unchanged. A code review then replaced the module-global lazy-accessor bridge with a narrow composition-root-bound port, and found five follow-up tasks that were marked complete without meeting their own stated acceptance criteria; verification against a working test environment confirmed three of those five (failure-taxonomy test coverage, client-contract test coverage, and a controller-level lease-state-projection duplication) and completed them properly, plus added a migration-produced-backfill integration test the review had also called for. Its permanent behavior is documented in `openspec/specs/fulfillment/spec.md`, `openspec/specs/physical-provisioning/spec.md`, and `openspec/specs/vm-storefront-fulfillment/spec.md`, with the rebuilt completed promotion record in `design.md`. One item is explicitly deferred by repository-owner direction rather than completed or dropped: rewriting the VM full-deal e2e teardown phases (task 10.14) moves to the final POOLS-7 review loop after Section 11, since Section 10 is completing without executing the full e2e suite. Section 11 (obsolete-schema removal) entered code review after its initial implementation pass; it is not yet complete. Its discuss and plan phases (2026-07-28 through 2026-07-30) found two of the original 11.1's three components already satisfied by Sections 2–10 (`allocation_id`/`SiteAllocation`, direct-host storefront placement, process-local settlement maps), found `deal_ref` removal should be dropped from this change's scope entirely (the precondition was never repository-wide, only VM-local), found `register_resource` is a live, load-bearing `apicredits` call path and is not safe to remove, redesigned the `most_available` claim-blindness fix against the claim/row vocabulary that actually shipped (the original 2026-07-17 sketch predates it), and resolved task 11.6 (`vm_host`, added 2026-07-29 by `fix-vm-fulfillment-capacity-boundary`'s audit) into a concrete migration plan. Implementation (2026-07-30) then: fixed `most_available` (11.2) with new claim-awareness tests; found and fixed a real credential-leak gap in the Ansible execution layer beyond what the discuss phase's own investigation had caught (11.4) — six password-bearing tasks in `vm-create.yml` needed `no_log`, not the two originally found, plus a real-time debug-log redaction gap and a second, subtler escaped-JSON rendering gap in the same scrubber, all fixed with new tests; migrated `CapacityReservation.vm_host` into the generic `executor_ref` field end to end — ledger write sites, the authority adapter, a `json_extract`-based query rewrite, the payload shape, the SQLAlchemy model, and a backfill-then-drop migration (11.6), closing a real pre-existing test-coverage gap (`find_active_lease_by_vm_target` had none) along the way; and re-confirmed 11.1 and 11.3 needed no code changes. 11.5's suite run covered eighteen packages (2,300+ tests) with a working multi-package test environment assembled during this session; the small number of failures found were each individually traced and confirmed unrelated to this change (an environment FastAPI-version artifact, one pre-existing negotiation-policy test failure, and chain-fixture-dependent Alkahest integration tests), and typing checks were run against the three packages that have them configured (all pre-existing findings, in files this change never touched). `core/registry`'s own pytest suite and `e2e-tests` were not run (a deep unrelated dependency chain, and a two-service live stack, respectively — both disclosed, not silently skipped). `openspec validate --all --strict` remains unavailable, unchanged from every validation pass since Section 8. `tasks.md`'s Section 11 entries record the full implementation detail and design-promotion notes per task; `design.md`'s "Section 11 design review" remains the discuss-phase record. Code review then reopened Section 11 with two blocking corrections (VM legacy-quantity matcher composition and foreign-key-safe reservation-table rebuilding) and accepted a bounded API-credit modernization expansion covering wheel-based packaging, ordered service migrations/deployment init, a typed capacity-administration client, and a domain-owned API-credit service client. Tasks 11.7–11.12 are now implemented and verified: the matcher composition fix (new `market_site.dict_resource_satisfies_claim` public export, a VM-owned `unit_claim_keys` constant, and behavioral aggregate-client tests that caught a real `FakeSite` fidelity gap along the way); the foreign-key-safe table rebuild (SQLite's documented offline-schema-change sequence, with a regression fixture that itself caught a real index-recreation ordering bug in the first implementation attempt); API-credit packaging modernization (removed editable-path overrides, fixed reinit target completeness, found and fixed a pre-existing gap where the domain-level test directory was never wired into `make test-apicredits` at all); service-owned ordered migrations (scoped to in-process startup migration rather than a CLI, since this service has no Kubernetes deployment topology today — explicitly flagged for revisit once it gains a Helm chart); the new `kit/site-client` package's typed capacity-administration client; and the new `CreditsServiceClient` centralizing what were five independent ad hoc HTTP call sites, with its actual callers (`fulfillment.py`, `keys_lookup.py`) refactored to construct and call it directly rather than through the original implementation's free-function facade — a real caller-composition gap the first pass left in place and review correctly caught, corrected the same day by deleting `issuance.py` entirely once every real caller was confirmed migrated. Task 11.13's documentation/closure work is complete except 11.13.5 (permanent-documentation promotion), deliberately deferred until this round of review accepts the implementation, consistent with promotion belonging to implementation closure rather than an in-progress review cycle. Cross-domain requirement vocabulary and API-credit durability redesign remain deferred to new discuss phases, as originally decided.

## Section 7 cutover boundary

Section 7 is a pre-release, all-or-nothing migration of legacy VM leases into
the durable fulfillment lifecycle. Existing hosts and site capacity are already
covered by Section 2 migrations. The migration joins legacy leases to supporting
capacity-reservation and resource-pool data, preserves every known active create
or teardown Ansible operation, and aborts rather than speculatively replaying a
create operation whose prior job identity cannot be established. POOLS-only
reservation states were never shipped and do not require compatibility handling.

## Non-Goals

- Anything `pools-4` already covers (claim-shape change itself).
- Kubernetes/cloud/other non-Ansible providers — inherits `pools-3`'s
  Ansible-only scope unless a second domain has forced that open by then.
- Removing `SettlementRecord`/`settlement_claims` independence —
  `pools-3` resolved that boundary; this change should not reopen it
  without new evidence of an actual need to correlate them.
- Durable consumption of Capacity Projections for commercial publication and claim construction, plus operator-declared listing-mode and reservation-TTL hints, remains in `pools-8-capacity-projection-and-listing-hints`. Projection producer endpoints and in-memory cache mechanics already landed here are retained as completed prerequisite work.
- Multi-principal storefront authentication and per-fulfillment-record
  ownership (distinct storefront/tenant principals authenticated separately,
  each scoped to only its own settlement rows). This change's provisioning
  service continues to authenticate its single VM storefront caller as it
  does today. A candidate design surfaced and was rejected as out of scope
  during Section 6's design review (see `dev-branch-migration-notes.md`,
  "Flagged as new, unscoped, cross-cutting work"); it would need its own
  proposal, since it touches every fulfillment API surface and the
  settlement schema, not just one section's caller.
- The bare-metal domain's own fulfillment cutover (bare-metal
  `FulfillmentProvider`, site capacity/config/routing). This change is
  scoped to the VM storefront only, per "Impact" above. A candidate
  implementation surfaced during Section 6's design review is noted in
  `dev-branch-migration-notes.md` for whoever owns that domain's roadmap,
  and is explicitly not part of this change.

## Capabilities

### Modified Capabilities

- `site-capacity`: storefront capacity reservation and fulfillment call
  shape changes to consume the scheduler/provider path.
- `physical-provisioning`: `PhysicalSettlementScheduler` and
  `FulfillmentProvider`/`ProviderRegistry` gain a production caller;
  `pools-2`'s and `pools-3`'s deferred durability/wiring items get
  resolved against a real call shape.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler` (implemented) and
  `pools-3-fulfillment-provider` (implemented).
- Requires `pools-4-storefront-capacity-boundary` (implemented).
- Requires `pools-6-multidimensional-fair-scheduling` (implemented).
- Related, not blocking: `pools-8-capacity-projection-and-listing-hints`
  — required for this change's `pool_id`-correctness fix to be complete
  end-to-end on the storefront side; see "Status" above.
- Follows the implemented `market-platform-compute-30-extract-service`
  package layout. Compute-30 did not create `kit/fulfillment` or
  implement this change's durable lifecycle.
- Related, nonblocking follow-on: `provisioning-result-push-delivery` hardens the existing provisioning→storefront callback transport and adds durable result delivery on top of this change's pull-correct durable state.
- `market-platform-bare-metal-10-storefront-composition` consumes the selected-site lifecycle after it lands; it does not block VM cutover.
- `market-platform-compute-40-multi-domain-proof` is the post-cutover regression/topology gate for two storefronts and two provisioning authorities.

## Impact

Touches `kit/site` (`site_resource_pools`/`CapacityReservation` reshape),
`kit/resource-pools` (removal of fulfillment-provider responsibilities),
`kit/fulfillment` (scheduler/policy and provider-contract consolidation,
settlement persistence, recovery, and pull-based result/status query contracts —
push delivery is `provisioning-result-push-delivery`'s scope, not this
change's),
the extracted compute provisioning service (models, migrations, generic
services, API and workers), the VM provisioning adapter (Ansible provider and
release behavior), and the VM storefront's reservation/orchestration path.
POOLS-6 has landed; the result is not fully complete end-to-end without
POOLS-8. The dependency-ordered implementation work is defined in `tasks.md`.
