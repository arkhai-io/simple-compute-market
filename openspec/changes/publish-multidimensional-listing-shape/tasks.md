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

## Design amendments after the plan check (2026-09-24)

The Slice B discussion (`design.md`, "Slice B discussion") changed decisions 6 and 7 after
the plan check above was written. Tasks 6–7 are re-planned in the planning phase; until
then, where a task or plan-check note below conflicts with `design.md`, the design governs.
Known conflicts:

- 7.1 and the plan check's "7.1, refresh and fetch": the post-write refresh is the written
  site's resource-pool cache refreshed in place, not `load_site_projections`.
- 7.3 and the plan check's "7.3, signed resource": resources are percent-encoded, not
  length-prefixed.
- 6.4 and the plan check's "6.4, report": override status is computed in system status in
  five states, not as `orphaned_overrides` in the derivation report. The dead legacy
  `gpu_model` fallback is removed.

## 6. Site-scoped storefront override store and resolution tier (decision 6)

- [ ] 6.1 **Migration.** In `domains/vms/storefront/src/market_storefront/utils/migrations.py`,
  add a migration creating `storefront_pool_overrides`:
  - `site_id TEXT NOT NULL`, `pool_id TEXT NOT NULL`, primary key `(site_id, pool_id)`;
  - `sla NUMERIC`, `min_price TEXT`, `token TEXT`, `max_duration_seconds INTEGER`;
  - `settlements TEXT`, `listing_shapes TEXT`;
  - `created_at`, `updated_at`.
  
  Append it to `VM_MIGRATIONS`.
- [ ] 6.2 In `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`, add
  `replace_pool_override` (whole record), `get_pool_override`, `list_pool_overrides`
  (optional site filter), and `delete_pool_override` (idempotent; reports whether a row
  existed).
- [ ] 6.3 **Models.** Add `domains/vms/storefront/src/market_storefront/models/pool_override_models.py`.
  - The record forbids extra fields.
  - `listing_shapes` must be a non-empty list, each shape flattened through
    `VM_CAPABILITY_SCHEMA`.
  - `settlements` are compiled through `publication_terms.compile_publication_clauses`.
  - `sla` must be non-negative and `max_duration_seconds` positive.
  - Response models carry the feasibility report and the live projection's revision and
    digest.
- [ ] 6.4 **Resolution tier.**
  - `domains/vms/listings/listing_shapes.py` resolves the override first, then the hint,
    then the default.
  - `domains/vms/listings/reconciler.py` reads `storefront_pool_overrides` for every site.
    It resolves commercial fields in this order: site-scoped store, legacy home-site row,
    pool hint, config default.
  - The site report gains `legacy_overrides_in_effect` and `orphaned_overrides`.
- [ ] 6.5 **Tests.**
  - `domains/vms/storefront/tests/unit/test_migrations.py`: fresh bootstrap and idempotent
    rerun.
  - A repository unit test: replace clears unset fields, list filter, idempotent delete.
  - A models unit test: every refusal in 6.3.
  - Reconciler unit tests: override replaces the hint whole; legacy precedence and
    reporting; orphaned reporting; a non-home-site override applies.

## 7. Override API (decision 7; `storefront-publication` delta)

- [ ] 7.1 **Service.** Add `domains/vms/storefront/src/market_storefront/services/pool_override_service.py`,
  applying checks in this order:
  1. An unconfigured site or an invalid record is refused with `422`, without any site
     call.
  2. The live projection is fetched through `capacity_runtime.site_client(site_id)`.
     Unreachable or unverifiable gives a retryable `503` naming the site.
  3. A pool absent from the live generation is refused with `404`.
  4. Otherwise the record is stored.
  
  The feasibility report is computed from the live generation with `shape_feasible`, with
  that generation's revision and digest. After the write it triggers a refresh through
  `services/site_projection_cache.py` and calls `wake_publication_loop()`. The live result is
  not written to the cache.
- [ ] 7.2 **Routes.** Add `PUT`, `GET` (one or list), and `DELETE`
  `/api/v1/admin/pool-overrides` to `controllers/admin_controller.py`, with site and pool in
  the body or query.
- [ ] 7.3 **Identity contract.** In `middleware/admin_identity.py`, add
  `admin_put_pool_override`, `admin_get_pool_override`, `admin_list_pool_overrides`, and
  `admin_delete_pool_override`. Resources are the site and pool encoded with the
  `market_core` length-prefixed encoding from 1.2.
- [ ] 7.4 **Client.** In `core/storefront-client/src/storefront_client/client.py`, add
  `put_pool_override`, `get_pool_override`, `list_pool_overrides`, and `delete_pool_override`
  to both the async and sync clients, with typed response models.
  - Bump `arkhai-core-storefront-client` from 0.19.1 to 0.20.0.
  - Raise the VM storefront's lower bound.
- [ ] 7.5 **CLI.** Add `domains/vms/storefront/src/market_storefront/groups/pool_overrides.py`
  with `market-storefront pool-override set|get|list|delete`. `set` reads a record document
  (`--file`) and calls the typed client. Register it in `cli.py` and add it to the module
  docstring's subcommand list.
- [ ] 7.6 **Fake site.** `domains/vms/storefront/tests/fake_site.py` serves a signed
  `GET /api/v1/capacity/site-resource-pools` from its projection rows, with a switch to make
  the site unreachable. `resolve_capacity_route` in `kit/site-client` already names the
  route.
- [ ] 7.7 **Unit tests.**
  - `test_admin_auth.py`: the four semantic operations; resources that stay unambiguous for
    IDs containing delimiters; body and query binding.
  - A client parity test for the new methods, in the style of
    `test_lifecycle_client_parity.py`.
  - `core/storefront-client/tests/test_admin_auth.py`: request construction.
- [ ] 7.8 **Integration tests.** Add `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`,
  through the typed client.
  - Acceptance returns the feasibility report and generation.
  - An unknown pool is refused while the storefront's cache still lists it.
  - An unreachable site is refused as retryable, with the reason distinct from an unknown
    pool.
  - An infeasible shape is accepted, and the next cycle publishes nothing for it.
  - A vocabulary error is refused with zero site requests recorded.
  - An unconfigured site is refused.
  - Delete is idempotent.
  - An orphaned override is retained and reported, and applies again when the pool returns.
  - Deleting an override over a legacy home-site value restores the legacy value and
    status reports it.
  - An override at a non-home site applies.
  - An exact retry returns the recorded outcome.
  - An override replacing a pool's hint shapes closes and republishes through the next
    cycle.
  
  Rejection-path cases assert status and stored state only.
- [ ] 7.9 **End to end.** Extend the listing-shapes scenario from 5.3: a storefront override
  through the typed client replaces the pool's shape, and a publication cycle closes and
  republishes.

# Both slices

## 8. Validation

- [ ] 8.1 Run the default `make test` of every affected project: slice A's set plus
  `core/storefront-client`. Disclose any suite not run.
- [ ] 8.2 **Packaging.**
  - Run `make dist-ci`.
  - Check wheel contents: `market_core.identifier_encoding` in `arkhai-core`, and no
    capability-shape module there; `market_capability_shape` in its kit.
  - Bump `arkhai-vms-storefront` from 0.5.0 to 0.6.0 and its pin in
    `domains/vms/storefront/Dockerfile`, so the image-version guard holds.
  - Run type checks where the affected projects configure them.
- [ ] 8.3 **No-default inventory.** Search publication, listing derivation, and the claim for
  defaults, `or` fallbacks, or inferred values that could publish or reserve a dimension no
  shape declares. Confirm that provisioning's use of pool defaults applies only to dimensions
  the reservation omits, as decision 3 accepts and 4.10 proves. Record the result.
- [ ] 8.4 Run `make check-reinit` and resolve every gap it reports.
- [ ] 8.5 Run `openspec validate --all --strict` and compare the result with the baseline
  current at implementation time.

## 9. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 9.1 **Comment hygiene.** Run `make check-comment-hygiene`. Then read directly:
  - the docstrings in `domains/vms/listings/reconciler.py` that describe GPU-count
    enumeration;
  - `IDENTITY_FIELDS`' "once publication carries them" comment;
  - `vm_listing_resource_for_listing`;
  - `compute_capacity_claim_from_order`'s "fixed, seller-declared shape" docstring;
  - the carry-over module, which must describe the invariant it keeps, not the upgrade that
    introduced it.
- [ ] 9.2 **Import placement.** Review each import this change adds or touches. The existing
  local import of `market_resource_pools` in the reconciler stays local, because buyers
  install the listings package without the `pools` extra. Verify any new local import the
  same way.
- [ ] 9.3 **Documentation compliance.** Re-check decisions 1–9 against the placement table
  in `openspec/README.md`.
- [ ] 9.4 **Narrative compression.** Compress completed task notes.
- [ ] 9.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, update Goal 2's current
  state (every listing is a shape; stated shapes publish every declared dimension; dimension
  filters match them) and this change's gap row. Record the update in the promotion record.
- [ ] 9.6 **Campaign index currency.** In `openspec/changes/README.md`, update:
  - this change's row: status, and removal of the stale "offering mode" and
    `offer_resource` text;
  - the Goal 2 dependency graph;
  - `pools-9`'s row: its override endpoint is now this change's;
  - `structured-capacity-requirements`' row: the parts implemented here.
- [ ] 9.7 **Documentation citations.** Run
  `make check-doc-citations CHANGE=publish-multidimensional-listing-shape` and resolve every
  match.
- [ ] 9.8 **End-to-end pipeline.** Run it and record the run, its result, and the scenarios
  exercising this change: `e2e_listing_shapes` plus the existing VM scenarios, which now
  publish default shapes. If it cannot run for an unrelated reason, record the blocker and
  treat the validations it gates as unrun.
- [ ] 9.9 **Promotion** (after code review). Promote to:
  - `openspec/specs/storefront-publication/spec.md`, `openspec/specs/resource-pool-management/spec.md`,
    `openspec/specs/market-composition/spec.md`, and `openspec/specs/site-capacity/spec.md`:
    the synced deltas, with evidence entries; then confirm the requirement names production
    docstrings cite exist (5.5);
  - `openspec/specs/storefront-publication/architecture.md`: a section on listing shapes and
    the storefront's authority, covering:
    - the commitment argument;
    - stated, generated, and never-inferred shapes;
    - the generator seam;
    - feasibility versus admission;
    - omitted dimensions as the site's;
    - overrides;
    - the live write check;
  - `docs/development/ARCHITECTURE.md`:
    - storefront capacity boundary;
    - an authority-table row for listing shapes;
    - package layers (the `kit/capability-shape` foundation kit and its dependants;
      the identifier encoding in `market_core`);
    - one name per concept (listing shape, `listing_shapes`);
    - the identifiers table's `pool_id` row, corrected to a site-local slug;
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`:
    - `listing_shapes` in pool definition entries;
    - state a pool's `region` on the pool, which listings advertise, and `region` and
      `gpu_model` on its capacity declarations, which reservations match; a region stated
      only on the pool publishes nothing;
    - storefront pool overrides administered through the API;
    - the legacy home-site tier;
    - sizing pool VM defaults for omitted dimensions;
    - fail-forward upgrade with the one-time republish and seller-state carry-over;
  - `docs/development/TESTING.md`: a listing-shape coverage split, in the style of
    "Pool Offering-Mode Enforcement".

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
| `listing_shapes` hint and structural validation | `openspec/specs/resource-pool-management/spec.md` |
| Family-grouped shapes flattened by one shared utility in a foundation kit; the neutral identifier encoding in the market core | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` kit layers (the capability-shape foundation kit) and package layers (the encoding in `market_core`) |
| Every projected resource-pool member states its resource kind | `openspec/specs/site-capacity/spec.md` — "Resource-pool projection metadata" |
| Fail-forward deployment; one-time republish at upgrade | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Omission beats inference; flat-name exception; review outcomes | This change's `design.md`; flat-name exception also in `structured-capacity-requirements`' `design.md` |
| Roadmap currency | `docs/development/ROADMAP.md` Goal 2 (task 9.5) |
| Campaign index currency | `openspec/changes/README.md` (task 9.6) |
