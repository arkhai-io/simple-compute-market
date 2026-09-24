# Implementation Tasks

Planned 2026-09-24 against `design.md`'s decisions 1–9, and revised the same day after design
review (see `design.md`, "Design review"). No task had started when either plan was written.
The first plan's disposition is recorded under "Superseded plan".

The work lands as **two reviewable slices** within this one change:

- **Slice A** (sections 0–5): the shared vocabulary, the pool hint, shapes for every listing,
  feasibility, identity and the upgrade carry-over, and discovery. Shapes come from pool
  hints and the default generator.
- **Slice B** (sections 6–7): the override store and its control plane, and the override tier
  in shape and term resolution.

Each slice passes its own validation before the next starts. Sections 8 and 9 cover both.

Every task names the design decision it implements. Test placement follows
`docs/development/TESTING.md`: the lowest level that can prove the behaviour, typed clients
only in integration tests, and rejection-path exceptions commented as such.

# Slice A

Complete. Rationale for every choice below is in
`design.md`; these notes record what exists and the evidence for it.

## 0. Pre-implementation gates

- [x] 0.1 **Decision gate — feasibility-predicate parity** (decision 4). The storefront's
  predicate agreed with the ledger on real projected members and buckets once the adapter
  maps projection field names. Two findings went to design review and were decided there:
  a member without `resource_type` is unresolvable (4.12), and a default shape failing on
  declared capacity is reported per pool (4.2). Result: `design.md` decision 4, "Parity gate
  result"; now held as a regression test (4.9).
- [x] 0.2 Re-verified the Context findings later tasks depended on. All held; the facts that
  shaped tasks are reflected in 4.7 and 4.13.

## 1. Shared utilities (decisions 3, 7; `market-composition` delta)

- [x] 1.1 Capability-shape utility: structure check, schema-driven flattening
  (`shape_problems`; `flatten_shape` raises `CapabilityShapeError` naming every problem),
  canonical form, and a `capability-shape.v1:` digest over the family form.
- [x] 1.2 Length-prefixed identifier encoding in `market_core.identifier_encoding`. VM concept
  packages reach it only through `arkhai_vms/listing_keys.py`, which builds every VM listing
  key; stored key bytes are unchanged (decision 3).
- [x] 1.3 Unit tests for the utility and the encoding, including key-order-independent
  digests and the byte form of stored keys.
- [x] 1.4 `arkhai-core` 0.3.0 with its exact pins updated; every lock carrying a changed
  internal package relocked.
  - **Deferred:** `domains/vms/storefront` and `domains/vms/buyer` resolve `torch` from an
    index the implementation environment could not reach, so their internal entries were
    edited by hand and proved with a frozen sync. Relock them where that index is reachable.
- [x] 1.5 **Capability-shape foundation kit.** The utility lives in `kit/capability-shape`
  (`arkhai-kit-capability-shape` 0.1.0, standard library only, with an import-boundary
  test), not the market core (decision 3). `kit/resource-pools` and `arkhai-vms` depend on
  it; `make check-reinit` required it in ten `reinit` recipes. Kit suite: 32 passed.

## 2. VM family schema and default generator (decisions 2, 3)

- [x] 2.1 `VM_CAPABILITY_SCHEMA` and `GPU_MODEL_ATTRIBUTE` in `arkhai_vms`: `gpu.count` and
  `gpu.model` required; `cpu.count`, `memory.gib`, `storage.gib` optional; flat names are the
  existing wire names.
- [x] 2.2 `arkhai_vms/shape_generation.py`: the `ListingShapeGenerator` seam and the GPU-only,
  per-model default.
- [x] 2.3 `arkhai-vms` 0.4.0.
- [x] 2.4 Schema, generator, VM shape-operation, and listing-key tests. VM domain suite: 37
  passed.

## 3. `listing_shapes` pool hint (decision 8; `resource-pool-management` delta)

- [x] 3.1 `LISTING_SHAPES_POLICY_TAG`, `raw_listing_shapes`, and structural
  `validate_listing_shapes` in `market_resource_pools`.
- [x] 3.2 Validation on create, replace, patch, and bulk import, with code
  `invalid_listing_shapes`.
- [x] 3.3 `kit/resource-pools` 0.4.0 with a `reinit` target. The planned root `Makefile`
  ordering was not made: `uv build` builds each wheel in isolation, so ordering matters only
  to `uv sync`, which runs after `make dist`.
- [x] 3.4 Kit unit and integration tests on every write surface. Suite: 222 passed.
- [x] 3.5 Provisioning tests: refusal through `ProvisioningClient`, and the hint projected
  verbatim.

## 4. Shapes for every listing, feasibility, identity (decisions 2, 4, 5, 9)

- [x] 4.1 `domains/vms/listings/listing_shapes.py`: a pool's shapes come from its hint or the
  default generator; an unreadable hint, including a non-mapping value, is reported and never
  replaced by the default.
- [x] 4.2 Reconciler: every slice is a feasible shape, with capacity buckets as the backed
  fungible availability source; keys are `…:shape:<digest>`; stored keys are read from the
  binding envelope, version 1 keeping a GPU-count key nothing derives; members without
  `resource_type` are held; stated infeasible shapes are reported per shape, and a default
  shape failing on declared capacity per pool with the undeclared attribute. Local-table
  derivation keeps GPU-only default shapes (decision 4).
- [x] 4.3 `IDENTITY_FIELDS` from `DIMENSION_KEYS`; `arkhai-vms-listings` 0.2.0 depends on
  `arkhai-vms`.
- [x] 4.4 The adapter publishes exactly the flattened shape and refuses a candidate without
  a shape or structural key.
- [x] 4.5 `services/shape_feasibility.py` adapts members and buckets to the site predicate's
  row and invents no field; injected into every reconciler caller and the inventory guard,
  which reads a listing's key from its stored binding.
- [x] 4.6 Binding envelope version 2 carries the canonical shape; `VmCapacitySource` carries
  `listing_shape`; `derive_listing` refuses a listing whose published fields differ from it.
- [x] 4.7 Seller-state carry-over runs fail-fast before the first lifecycle loop, reads
  listings through `list_listing_source_envelopes`, and brings an already-bound successor to
  the seller's state through the seller's own operations (close or pause), reporting one
  reconciliation already closed.
  - **Deferred:** `core_storefront`'s `SQLiteClient.listing_id_for_derivation_key` calls an
    undefined `_connect()`; pre-existing and outside this change.
- [x] 4.8 System status reports `listing_identity_carryover`; the new derivation fields pass
  through `publication_derivation` unchanged, so no client change.
  - **Correction (found in Slice B):** the status route's common `HealthResponse` drops
    undeclared keys, so the carry-over report never reached a caller; the tests read it
    from the module. The VM storefront's `VmSystemStatusResponse` now declares it (6.5),
    and the upgrade test asserts it through the typed client.
- [x] 4.9 Tests: 15 reconciler shape cases (`TestListingShapes`); feasibility parity against
  the ledger's public `probe` on held and unheld ledgers (27 cases, both outcomes asserted);
  carry-over including already-bound successors; identity fields. The parity and carry-over
  tests are integration tests. Existing fixtures that claimed an undeclared region or model,
  or bound a listing differently from what it publishes, were corrected.
- [x] 4.10 Provider input: declared quantities size the VM; a GPU-only shape takes every
  other dimension from pool defaults.
- [x] 4.11 Publication-loop integration: hint shapes replace defaults; defaults stay GPU-only;
  editing a shape rebinds without touching the old binding; shrinking a declaration closes
  and reports; taken memory makes a stated shape unpublishable; capacity changes never
  resize; dry run changes nothing; a stated shape negotiates and reserves every declared
  dimension; the upgrade scenario. A changed GPU model closes and republishes, since the
  model is part of the shape.
- [x] 4.12 The projection contract requires a non-empty `resource_type`
  (`arkhai-kit-site-client` 0.5.0), stated as a producer contract in the `site-capacity`
  delta.
- [x] 4.13 The fake site projects `resource_type` and full capacity maps and accounts for
  every requested dimension.

## 5. Discovery, end to end, and slice A validation

- [x] 5.1 Registry filters through the canonical `RegistryClient`: `ram_gb` lower bounds at
  and above a shape's value, GPU-only listings excluded, and a shaped listing validating for
  publication.
- [x] 5.2 End-to-end helpers accept a full capacity map and the pool's `listing_shapes`,
  `pricing`, and `region` hints; `capacity_source_for` and the hosted scenario send
  `listing_shape`.
- [x] 5.3 `e2e_listing_shapes` scenario, registered in `E2E_MODULE`: a pool states a
  four-family shape and its own terms and region; one cycle publishes exactly that shape;
  discovery finds it at `ram_gb>=32` and not at `ram_gb>=33`; `market buy` reaches ready; the
  reservation holds exactly the shape's quantities; the create job is sized from them (1 GPU,
  8 vCPUs, 32 768 MiB, `100G`).
- [x] 5.4 **Slice A validation.**
  - End-to-end pipeline: 123 passed, 3 skipped, all nine `e2e_listing_shapes` stages
    passing; the skips (bare-metal deal, two Alice multi-registry stages) predate this
    change.
  - Implementation-environment suites: every affected project's `make test` passes, and the
    VM storefront (1041 unit, 220 integration) and buyer (196) pass against frozen
    environments. The storefront's two Alkahest integration tests need a `node` runtime, and
    `domains/apicredits`' middleware toolchain check needs `cargo`.
  - `make dist-ci`, `make dist-kits`, `make check-reinit`, and strict OpenSpec validation
    (baseline 73 passed, 19 failed, this change passing) succeed.
  - The maintainer's full `make test` passed (reported at the start of the Slice B
    session, 2026-09-24).
- [x] 5.5 **Slice A closeout** (the plan closeout requirements of `openspec/README.md`,
  applied at section scope).
  - Comment hygiene: `make check-comment-hygiene` passes. A direct read of every production
    comment Slice A added found no review, task, or change history; references to version 1
    envelopes describe data that exists in deployed databases. Three docstrings cite
    requirements added by this change's `storefront-publication` delta ("Every listing is a
    listing shape"; "A listing shape is published only where a source member is feasible
    for it"; "A listing's derivation identity includes its shape"). They resolve when the
    delta is synced; 9.9 syncs it and verifies them then.
  - Import placement: of the two function-level imports Slice A added, the one in
    `listing_shapes.py` stays (buyers install the listings package without the pool kit);
    the system-status provider's moved to module level, verified by importing the
    application and by both storefront suites.
  - Documentation compliance: the proposal's Impact now names the VM domain's generator
    and key builders, `kit/site-client`, the delisting of pools no reservation could admit,
    and the producer-side projection contract.
  - Narrative compression: sections 0–5 reduced to final behaviour, evidence, deferred
    work, and destinations; every rationale they carried is in `design.md`.
  - Roadmap and campaign index: owed at change completion, which Slice B precedes; no
    disposition changes now (9.5, 9.6).
  - Documentation citations: `make check-doc-citations` passes.
  - End-to-end pipeline: recorded in 5.4.
  - Promotion: the design-promotion record lists every Slice A decision's permanent
    destination; promotion itself happens once, at change completion (9.9).

# Slice B

## Plan check before Slice B (2026-09-24)

Tasks 6–7 were checked against the code as Slice A left it. Every named module, function,
and test file exists; the details below amend the tasks they name.

- **6.4, shapes.** `resolve_vm_listing_shapes` takes the override tier as a keyword and
  resolves it with the existing `resolve_stated_shapes` under a `storefront_override`
  source. Keys depend only on the shape digest, so an override stating the pool's hint
  shape keeps its listing.
- **6.4, commercial fields.** The new store merges over the legacy home-site row field by
  field, through the existing per-field fall-through (`GpuPricingFields`, and
  `resolve_sla`'s override argument), before the pool hint and configuration.
- **6.4, report.** `_SiteDerivationReport` gains `legacy_overrides_in_effect` and
  `orphaned_overrides` beside Slice A's fields; system status already passes the report
  through without a client change.
- **7.1, refresh and fetch.** The post-write refresh is `load_site_projections`, the
  function the admin refresh route calls. The live read is
  `capacity_runtime.site_client(site_id).resource_pool_projection()`, whose response
  carries `revision`, `digest`, and `resource_pools`. Feasibility is reported with
  `vm_shape_feasibility()` against declared capacity.
- **7.3, signed resource.** Encoded with `market_core.identifier_encoding`: the storefront
  is a composition root, and the rule that VM concept packages import no core package
  does not bind it.
- **7.4, versions.** Slice A changed nothing in `core/storefront-client`, so 0.19.1 →
  0.20.0 stands; the VM storefront's lower bound is currently `>=0.19.1`.
- **7.6, fake site.** The route answers `revision`, `digest`, and `resource_pools`, signed
  through the fake site's existing response path; its members already carry
  `resource_type` and full capacity maps (4.12, 4.13).
- **8.2.** `arkhai-vms-storefront` is still 0.5.0, pinned at line 147 of
  `domains/vms/storefront/Dockerfile`; its code changed in Slice A, so the bump is owed.
- **Start condition.** Slice B starts once the end-to-end pipeline has run against Slice A
  (5.3, 5.4).

## Plan (2026-09-24)

Re-planned after the Slice B discussion (`design.md`, "Slice B discussion"); that
discussion superseded the plan check's "6.4, report", "7.1, refresh and fetch", and
"7.3, signed resource" notes. **Versions:** a package whose wheel changes is bumped
once per change. `arkhai-core` and `arkhai-vms-listings` were bumped in Slice A; Slice
B bumps the client (0.20.0), the VM storefront (0.6.0), and the provisioning service
(0.3.1).

## 6. Override store, resolution tier, and status (decision 6)

- [x] 6.1 Migration `20260924_011_storefront_pool_overrides` creates
  `storefront_pool_overrides`, keyed by `(site_id, pool_id)`.
- [x] 6.2 Repository: whole-record replace keeping `created_at`, get, list with a site
  filter, and an idempotent delete that reports existence.
- [x] 6.3 `models/pool_override_models.py`: the record forbids extra fields and refuses
  empty shape and clause lists, shapes outside the vocabulary, a negative SLA, and a
  non-positive duration. Clauses compile in the service (7.1).
- [x] 6.4 Resolution tier.
  - `listing_shapes.py` resolves `storefront_override` shapes before the hint.
  - The reconciler reads the store inside `available_compute_slices`, so every
    structural-key reader sees it. Stored shapes the vocabulary cannot read are held and
    reported.
  - Commercial fields merge field by field over the legacy row, and
    `legacy_overrides_in_effect` names each field a legacy row supplies, `region` and
    `accepted_escrows` included.
  - The dead legacy `gpu_model` fallback and the per-row model and terms are removed;
    projection-path terms come only from `pricing_by_model`.
  - **Deviation:** instead of extracting half of `_judge_members`, the write report's
    `declared_shape_feasibility` runs `_projected_pool_rows` itself, declared-only and
    without recording a site report, over the site's whole live projection. The report
    and derivation therefore cannot disagree.
- [x] 6.5 Override status: `override_state` and `PoolOverrideService.statuses` report one of
  five states through `listing_source_projection()`. System status carries them as
  `pool_overrides`, declared on the VM storefront's `VmSystemStatusResponse` (see the 4.8
  correction).
- [x] 6.6 Tests.
  - Unit: `TestStorefrontOverrideTier` (8) in `test_reconciler.py`, whose per-row term
    assertions moved to per-shape pricing; `test_pool_override_models.py`; and
    `unit/services/test_pool_override_service.py`, which holds the status tests beside the
    service's.
  - Integration: `test_pool_override_store.py` (10), including the structural-key
    invariant and the feasibility judge.

## 7. Override API, client, and CLI (decision 7; `storefront-publication` delta)

- [x] 7.1 `PoolOverrideService` applies the ordered checks, with distinct `503` reasons for
  an unreachable site, an unverified answer, an HTTP error, and an unusable projection. It
  refreshes the written site's resource-pool cache in place
  (`refresh_site_resource_pools`) and wakes publication. The shape judge is injected.
- [x] 7.2 Routes `PUT`/`GET`/`DELETE /api/v1/admin/pool-overrides`; composed by
  `server.build_pool_override_service` into `resolved_pool_override_service`.
- [x] 7.3 Identity contract: percent-encoded resources and a strict query. The
  `identifier_encoding` docstring no longer names administrator resources.
- [x] 7.4 Client 0.20.0: `_authenticated_put` and `_authenticated_delete`, the four `admin_*`
  methods, response models, and `HealthResponse.pool_overrides`.
  - Pins moved: the VM storefront and `e2e-tests` (`>=0.20.0`), and the provisioning
    service (`==0.20.0`, bumped to 0.3.1 with its Dockerfile pin).
  - Relocked: the client, the provisioning service, both adapters, and `e2e-tests`. The VM
    storefront's lock was edited by hand. Every lock diff is version-only.
- [x] 7.5 `market-storefront pool-override set|get|list|delete`, over
  `cli_common.admin_client`. **Deviation:** the URL option is the existing
  `--storefront-url`/`-a`, not `--url`.
- [x] 7.6 `FakeSite` serves the live projection with `reachable` and `verifiable` switches
  and a request log. The harness cache re-reads the harness pools and counts refreshes.
  The harness also resets the process-wide capacity-event cursor, which had let an
  earlier app's cycle skip a later app's events.
- [x] 7.7 Unit: override-route contract tests in `test_identity_dispatch.py` (the module
  that tests `_contract`, not `test_admin_auth.py`); `test_pool_override_client_parity.py`;
  the client's byte-equality and resource tests; `unit/cli/test_pool_overrides.py`.
- [x] 7.8 `integration/test_pool_overrides_api.py` (14) covers every case planned except the
  non-home-site override. The harness configures one site, so that case is covered in the
  unit suite (`TestStorefrontOverrideTier`).
- [x] 7.9 `e2e_listing_shapes` stage 06: an override through the typed client, reported
  feasible; one cycle replaces the hint's listing; status `applied`; delete restores the
  hint's shape. It collects here; it runs only in the pipeline (9.8).

# Both slices

## 8. Validation

- [x] 8.1 Suites, in the implementation environment:
  - VM storefront: 1119 unit (1 skipped); 244 integration, with the two Alkahest tests
    deselected for lack of `node`.
  - VM buyer: 196.
  - `core/storefront-client`: 33.
  - Provisioning service: 665 unit and 271 integration.
  - VM and bare-metal provisioning adapters: 39 and 2.
  - `core`: 101.
  - `e2e-tests` unit: 237, plus the known pre-existing failure
    `test_buyer_deployment_mounts_separate_profile_state_and_credential`.
  - **Open:** the maintainer's full `make test`.
- [x] 8.2 Wheels rebuilt, and their contents checked: the encoding is in `arkhai-core`, which
  holds no capability-shape module; `market_capability_shape` is in its kit; the new
  storefront modules are in `arkhai-vms-storefront` 0.6.0 (Dockerfile and `e2e-tests`
  pins moved). `make typecheck-core` passes.
- [x] 8.3 No-default inventory: nothing publishes or reserves a dimension a shape omits.
  - The adapter publishes exactly the flattened shape.
  - The claim copies only quantities the listing carries (`is not None`).
  - The listing model's dimension fields default to `None`.
  - Only provisioning fills an omitted dimension, from pool defaults (4.10).
- [x] 8.4 `make check-reinit` passes.
- [x] 8.5 `openspec validate --all --strict`: 73 passed, 19 failed, identical to the
  baseline; this change passes.

## 9. Closeout

- [x] 9.1 `make check-comment-hygiene` passes. Direct reads rewrote three things:
  - `compute_capacity_claim_from_order`'s docstring, which now says the claim carries the
    shape's declared quantities;
  - the key readers' cost comment, which now states why keys need the full derivation;
  - `cli_common`'s history-narrating module docstring.
  
  The carry-over module states its invariant. Two new docstrings cite delta-only
  requirements, joining Slice A's three for 9.9: "Storefront pool overrides are
  site-scoped and durable" and "Storefront pool overrides are written against the site's
  live projection".
- [x] 9.2 Import placement.
  - `build_pool_override_service`'s imports moved to module level in `server.py`. Both
    suites pass, and the standalone import behaviour is unchanged.
  - `cli_common.admin_client` keeps its local settings import, a deliberate lazy load
    carried from `cli_publish` and commented.
  - The listings package's local `market_resource_pools` imports stay local, because
    buyers install it without the `pools` extra.
- [x] 9.3 Documentation compliance: decisions 1–9 re-checked against the placement table.
  Their destinations are in the promotion record, and `VmSystemStatusResponse`'s rule is
  local to its module.
- [x] 9.4 Narrative compression: sections 6–9 reduced to final behaviour, evidence,
  deviations, and open work.
- [x] 9.5 Roadmap currency: in `docs/development/ROADMAP.md`, Goal 2's current state now
  says every listing is a shape, stated shapes publish and reserve their declared
  dimensions, and dimension filters match them. This change's gap row is removed.
- [x] 9.6 Campaign index currency: this change's row states its status and boundary,
  without the stale offering-mode and `offer_resource` text. `structured-capacity-requirements`
  names the parts implemented here, and `pools-9` records that its override endpoint is
  superseded and that it retires the legacy tier. The Goal 2 dependency graph is unchanged:
  this change still precedes `capacity-shape-pricing`.
- [x] 9.7 `make check-doc-citations CHANGE=publish-multidimensional-listing-shape` passes.
- [ ] 9.8 **End-to-end pipeline** (maintainer). Record the run, its result, and the
  scenarios: `e2e_listing_shapes` including stage 06, and the existing VM scenarios. If it
  cannot run for an unrelated reason, record the blocker and treat the validations it gates
  as unrun.
- [ ] 9.9 **Promotion** (after code review). Promote to:
  - `openspec/specs/storefront-publication/spec.md`, `openspec/specs/resource-pool-management/spec.md`,
    `openspec/specs/market-composition/spec.md`, and `openspec/specs/site-capacity/spec.md`:
    the synced deltas, with evidence entries. Then confirm the five delta-only
    requirement names production docstrings cite (5.5, 9.1).
  - `openspec/specs/storefront-publication/architecture.md`: a section on listing shapes and
    the storefront's authority, covering:
    - the commitment argument;
    - stated, generated, and never-inferred shapes;
    - the generator seam;
    - feasibility versus admission;
    - omitted dimensions as the site's;
    - overrides, their five status states, and why an unloaded site is unknown;
    - the live write check and the targeted post-write refresh.
  - `docs/development/ARCHITECTURE.md`:
    - storefront capacity boundary;
    - an authority-table row for listing shapes;
    - package layers (the `kit/capability-shape` foundation kit and its dependants;
      the identifier encoding in `market_core`);
    - one name per concept (listing shape, `listing_shapes`);
    - the identifiers table's `pool_id` row, corrected to a site-local slug.
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`:
    - `listing_shapes` in pool definition entries;
    - state a pool's `region` on the pool, which listings advertise, and `region` and
      `gpu_model` on its capacity declarations, which reservations match; a region stated
      only on the pool publishes nothing;
    - storefront pool overrides administered through the API, and inactive while listings
      derive from local tables;
    - the legacy home-site tier and its per-field report;
    - sizing pool VM defaults for omitted dimensions;
    - fail-forward upgrade with the one-time republish and seller-state carry-over.
  - `docs/development/TESTING.md`: a listing-shape and storefront-override coverage split,
    in the style of "Pool Offering-Mode Enforcement".

## Superseded plan

The first plan predates the design revision of 2026-09-24. None of it was started.

| Original task | Disposition |
|---|---|
| 1.1 Re-verify context | Replaced by 0.2 |
| 1.2 Carry the projection's capacity map through the slice builder | Superseded by decision 1: dimensions are published only from shapes (4.2) |
| 1.3 Emit each declared dimension from `DIMENSION_KEYS` | Superseded by decision 1; the vocabulary is `VM_CAPABILITY_SCHEMA` (2.1, 4.4) |
| 1.4 No provisioning default reaches a candidate | Kept as 8.3 |
| 1.5 Focused tests | Replaced by 4.9 |
| 2.1–2.2 Registry filter coverage | Kept as 5.1 |
| 2.3 End-to-end `--ram-gb-min` path | Replaced by 5.3; the flag is now a `--resource` query |
| 3.1–3.2 Validation | Replaced by 5.4 and section 8 |
| 4.1–4.9 Closeout | Replaced by section 9 |

The Slice B tasks 6.1–7.9 planned before the Slice B discussion were never started; the plan
above replaces them. 6.1–6.3, 6.5–6.6, 7.2, and 7.4–7.9 carry over with amended detail. 6.4
gains the legacy-report scope and the dead-fallback removal. 7.1 changes its refresh, 7.3 its
encoding, and override status moves from the derivation report into system status (6.5).

## Design promotion record

Filled in during implementation. Destinations planned:

| Accepted decision | Permanent location |
|---|---|
| A published dimension is a commitment; every listing is a listing shape from override, hint, or default generator | `openspec/specs/storefront-publication/spec.md` — "Every listing is a listing shape"; rationale in `openspec/specs/storefront-publication/architecture.md` |
| The VM default generator is GPU-only and per model; generators are a seam | Same requirement; `openspec/specs/storefront-publication/architecture.md` |
| Omitted dimensions are the site's; the administrator sizes the defaults | `openspec/specs/storefront-publication/architecture.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| A shape is published only where a member is resource-feasible; reservation remains the admission boundary | `openspec/specs/storefront-publication/spec.md` — "A listing shape is published only where a source member is feasible for it" |
| Every listing's identity includes its shape digest; seller state carries across the upgrade | `openspec/specs/storefront-publication/spec.md` — "A listing's derivation identity includes its shape" |
| Site-scoped, durable storefront pool overrides and the legacy tier | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are site-scoped and durable"; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Override writes are checked against the site's live projection | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are written against the site's live projection" |
| Every stored override reports one of five states; an unloaded site is unknown, not absent | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are site-scoped and durable"; rationale in `openspec/specs/storefront-publication/architecture.md` |
| Overrides have no effect under local-table derivation | Same requirement; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| The post-write refresh targets the written site's cache | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are written against the site's live projection"; `openspec/specs/storefront-publication/architecture.md` |
| Signed override resources are unambiguous; percent-encoded as the administrator contract's other resources are | The rule: `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are written against the site's live projection". The encoding follows an existing convention and needs no separate promotion; the rejected alternative stays in `design.md` |
| `listing_shapes` hint and structural validation | `openspec/specs/resource-pool-management/spec.md` |
| Family-grouped shapes flattened by one shared utility in a foundation kit; the neutral identifier encoding in the market core | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` kit layers (the capability-shape foundation kit) and package layers (the encoding in `market_core`) |
| Every projected resource-pool member states its resource kind | `openspec/specs/site-capacity/spec.md` — "Resource-pool projection metadata" |
| Fail-forward deployment; one-time republish at upgrade | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Omission beats inference; flat-name exception; review outcomes | This change's `design.md`; flat-name exception also in `structured-capacity-requirements`' `design.md` |
| Roadmap currency | `docs/development/ROADMAP.md` Goal 2 (task 9.5) |
| Campaign index currency | `openspec/changes/README.md` (task 9.6) |
