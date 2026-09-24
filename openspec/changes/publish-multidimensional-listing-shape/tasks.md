# Implementation Tasks

Planned 2026-09-24 against `design.md`'s decisions 1–9. The plan first written for this
change had no completed task; its disposition is recorded under "Superseded plan" at the
end rather than deleted.

Every task names the design decision it implements. Test placement follows
`docs/development/TESTING.md`: the lowest level that can prove the behaviour, typed clients
only in integration tests, and rejection-path exceptions commented as such.

## 0. Pre-implementation gates

- [ ] 0.1 **Decision gate — admission parity.**
  - What to check: before building on decision 4, check that
    `compute_capacity_claim_from_order` applied to a shaped `listing_resource`, then
    `market_site.dict_resource_satisfies_claim` applied to a projected member adapted to the
    snapshot-row shape, gives the answer `kit/site` admission gives for the same declaration
    and claim. The `kit/site` library integration suite is the reference.
  - Cases:
    - a member declaring `region` and `gpu_model`;
    - a pool whose region comes only from the pool hint;
    - a projected member whose `resource_type` is absent;
    - a specific-resource claim, which drops `pool_id`.
  - Outcome: record the result in `design.md` decision 4. Where the predicate and
    admission disagree, **pause for design review**: the premise "publish exactly when the
    site would admit" would not hold.
  - Files read: `kit/site/src/market_site/ledger.py`,
    `domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`, and
    `provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py`.
- [ ] 0.2 Re-verify the Context findings in `design.md` that later tasks depend on:
  - `_projected_resource_usage` reads only `gpu_count`;
  - enumeration keys and the version 1 envelope;
  - the claim copies `DIMENSION_KEYS`;
  - the requirement delegate's GiB translation;
  - the buyer sends no `compute_resource`;
  - the home-site-only legacy override read;
  - the fake site serving no resource-pool projection.
  
  Record any that moved.

## 1. Shared capability-shape utility (decision 3; `market-composition` delta)

- [ ] 1.1 Add `core/src/market_core/capability_shape.py`. Provide:
  - the schema types: per family field, its kind (quantity or attribute), whether it is
    required, and its flat name;
  - `shape_structure_problems(shape)`, which needs no schema;
  - `flatten_shape(shape, schema)`, returning quantities and attributes or problems, each
    problem naming its `family.field` path. Quantities are positive integers, `bool`
    refused; attributes are non-empty strings;
  - `canonical_shape(shape)`;
  - `shape_digest(shape)`, domain-tagged `capability-shape.v1:<sha256>` over the canonical
    family-grouped JSON.
  
  The module names no family or field. Export it from `core/src/market_core/__init__.py`
  if the package exports its modules' public names.
- [ ] 1.2 Add `core/tests/unit/test_capability_shape.py`. Cover:
  - structure accepted and refused without a schema;
  - flatten with a test schema;
  - a missing required field;
  - an unknown family or field, naming its path;
  - a wrong value kind, including `True` as a quantity;
  - digest stability under key order;
  - digest unchanged when a schema renames a flat name.
  
  Confirm `test_carrier_purity.py` and `test_domain_boundaries.py` still pass.
- [ ] 1.3 **Version and pins.**
  - Bump `arkhai-core` from 0.2.0 to 0.3.0 (new public API).
  - Update the exact `arkhai-core==0.2.0` pins to `==0.3.0` in:
    - `kit/settlement-runtime/pyproject.toml`
    - `kit/hosted-settlement/pyproject.toml`
    - `kit/contact-exchange/pyproject.toml`
    - `core/registry-client/pyproject.toml`
    - `core/registry/pyproject.toml`
  - Raise the lower bound to `>=0.3.0` where a consumer imports the new module (tasks 2, 3).
  - Relock every project whose lock changes.

## 2. VM family schema (decision 3)

- [ ] 2.1 In `domains/vms/domain/src/arkhai_vms/compute_requirements.py`, add
  `VM_CAPABILITY_SCHEMA`:
  - `gpu.count` → `gpu_count`, a required quantity;
  - `gpu.model` → the `gpu_model` attribute, required;
  - `cpu.count` → `vcpu_count`;
  - `memory.gib` → `ram_gb`;
  - `storage.gib` → `disk_gb`.
  
  Export it from `arkhai_vms/__init__.py`. Carry the flat-name exception as a comment
  stating the rule: these are the published wire names, and they are GiB.
- [ ] 2.2 In `domains/vms/domain/pyproject.toml`, set `arkhai-core>=0.3.0` and bump
  `arkhai-vms` from 0.3.0 to 0.4.0.
- [ ] 2.3 In `domains/vms/domain/tests/test_compute_requirements.py`, test:
  - the schema's quantity flat names equal `DIMENSION_KEYS`;
  - the required fields;
  - one representative flatten.

## 3. `listing_shapes` pool hint (decision 8; `resource-pool-management` delta)

- [ ] 3.1 In `kit/resource-pools/src/market_resource_pools/hints.py`, add:
  - `LISTING_SHAPES_POLICY_TAG`;
  - `raw_listing_shapes(policy_tags, offering_mode)`;
  - `validate_listing_shapes(policy_tags)`, which requires a mapping of offering mode to a
    non-empty list, with each shape passing `market_core`'s structure check.
  
  Export them from `market_resource_pools/__init__.py`.
- [ ] 3.2 In `kit/resource-pools/src/market_resource_pools/service.py`, add
  `validate_listing_shapes` to `_require_valid_policy_tag_hints` and to the bulk-document
  path, with path `...policy_tags.listing_shapes` and code `invalid_listing_shapes`, so every
  pool-write surface applies the identical check.
- [ ] 3.3 **Packaging for `kit/resource-pools`.**
  - Add `arkhai-core>=0.3.0` to its `pyproject.toml` and bump it from 0.3.0 to 0.4.0.
  - Add a `reinit` target to `kit/resource-pools/Makefile` that reinstalls `arkhai-core`
    from `.dist`.
  - In the root `Makefile`, declare `dist-ci-kits` and `dist-kits` after `dist-core`, so
    the wheel order holds under parallel make.
  - Relock.
- [ ] 3.4 **`kit/resource-pools` tests.**
  - `tests/unit/test_hints.py`:
    - valid shapes;
    - an empty list;
    - a non-mapping family;
    - a non-scalar field;
    - a field no domain defines, which is accepted.
  - `tests/integration/test_resource_pool_service.py`: identical refusal across create,
    replace, patch, and bulk import, with nothing stored.
- [ ] 3.5 **Provisioning tests.**
  - `provisioning/compute/service/tests/integration/test_pools_api.py`: refusal through the
    typed provisioning client, asserting status and stored state only (rejection path).
  - `provisioning/compute/service/tests/integration/test_capacity_api.py`: the hint is
    projected verbatim in `policy_tags`.

## 4. Site-scoped storefront override store (decision 6)

- [ ] 4.1 **Migration.** In `domains/vms/storefront/src/market_storefront/utils/migrations.py`,
  add a migration creating `storefront_pool_overrides`:
  - `site_id TEXT NOT NULL`, `pool_id TEXT NOT NULL`, primary key `(site_id, pool_id)`;
  - `sla NUMERIC`, `min_price TEXT`, `token TEXT`, `max_duration_seconds INTEGER`;
  - `settlements TEXT`, `listing_shapes TEXT`;
  - `created_at`, `updated_at`.
  
  Append it to `VM_MIGRATIONS`.
- [ ] 4.2 In `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`, add
  `replace_pool_override` (whole record), `get_pool_override`, `list_pool_overrides`
  (optional site filter), and `delete_pool_override` (idempotent; reports whether a row
  existed).
- [ ] 4.3 **Models.** Add `domains/vms/storefront/src/market_storefront/models/pool_override_models.py`.
  - The record forbids extra fields.
  - `listing_shapes` must be a non-empty list, each shape flattened through
    `VM_CAPABILITY_SCHEMA`.
  - `settlements` are compiled through `publication_terms.compile_publication_clauses`.
  - `sla` must be non-negative and `max_duration_seconds` positive.
  - Response models carry the fit report and the live projection's revision and digest.
- [ ] 4.4 **Tests.**
  - `domains/vms/storefront/tests/unit/test_migrations.py`: fresh bootstrap and idempotent
    rerun.
  - A repository unit test: replace clears unset fields, list filter, idempotent delete.
  - A models unit test: every refusal in 4.3.

## 5. Shaped derivation, fit, identity (decisions 2, 4, 5, 9)

- [ ] 5.1 Add `domains/vms/listings/listing_shapes.py`. It resolves a pool's VM shape list:
  - first the site-scoped override store;
  - otherwise `raw_listing_shapes(policy_tags, "vm")`;
  - otherwise none.
  
  It validates each shape through `VM_CAPABILITY_SCHEMA` and returns one outcome: `none`,
  `shapes` (with their source), or `unreadable` (with its problems).
- [ ] 5.2 **Reconciler** (`domains/vms/listings/reconciler.py`).
  - Read `storefront_pool_overrides` for every site. Resolve commercial fields in this
    order: site-scoped store, legacy home-site row, pool hint, config default. Record in
    the site report when a legacy value is in effect.
  - In `_projected_pool_rows`, when shapes resolve, build shaped rows:
    - fungible: one per shape;
    - specific resource: one per member per shape the member holds.
  - Evaluate fit with an injected `shape_fits` callable: against declared capacity, and for
    backed pools also against `available`. A member reporting no `available` is judged on
    declared capacity.
  - An unfit shape yields no row and is reported. An unreadable list holds the pool and is
    reported, with no enumeration fallback.
  - The enumeration path is unchanged.
  - Price each shaped row by the shape's `gpu.model`.
  - Shaped candidates carry the canonical shape, its digest, the flattened quantities and
    attributes, and a reconciler key built from site, pool or resource, and the digest.
  - `available_compute_slices`, `current_available_resource_keys`, `stale_open_listing_ids`,
    and `closed_available_listing_ids` take `shape_fits` as a required keyword.
  - `_bound_vm_listings` also reads `source_envelope_json`. `stored_listing_key` reads a
    shaped listing's key from its version 2 envelope.
  - `slice_identity` carries every published identity field, with the dimension names taken
    from `DIMENSION_KEYS`.
  - `_SiteDerivationReport` adds `unfit_shapes`, `unreadable_shapes`,
    `legacy_overrides_in_effect`, and `orphaned_overrides`.
- [ ] 5.3 **Identity fields and packaging for `domains/vms/listings`.**
  - In `domains/vms/listings/listing_comparison.py`, build the dimension part of
    `IDENTITY_FIELDS` from `arkhai_vms.DIMENSION_KEYS`.
  - In `domains/vms/listings/pyproject.toml`, add `arkhai-vms>=0.4.0` and bump
    `arkhai-vms-listings` from 0.1.0 to 0.2.0.
  - Add `reinit` lines, relock, and export new names from
    `domains/vms/listings/__init__.py`.
- [ ] 5.4 **Adapter.** In `domains/vms/domain/src/arkhai_vms/storefront_adapter.py`:
  - `vm_listing_resource_for_listing` publishes a shaped candidate's `gpu_model`,
    `gpu_count`, and each declared quantity from its flattened shape, and publishes nothing
    extra for an enumerated candidate;
  - `vm_candidate_skip_keys` handles shaped keys.
- [ ] 5.5 **Fit callable.** Add `domains/vms/storefront/src/market_storefront/services/shape_fit.py`.
  - It provides the injected fit callable: it builds the claim with
    `compute_capacity_claim_from_order` and judges it with
    `market_site.dict_resource_satisfies_claim`, configured with the container's unit claim
    keys and mirror dimension.
  - It adapts a projected member to the snapshot row, with declared or available quantities
    as asked.
  - Pass it to every reconciler caller:
    - `services/publication_loop.py`
    - `services/publication_service.py`
    - `services/listing_source_check.py`
    - `failure_actions.py`
    - `controllers/admin_controller.py` (fulfillment-event handlers)
- [ ] 5.6 **Binding.**
  - `domains/vms/storefront/src/market_storefront/publication_binding.py`: shaped candidates
    write `compute.listing_source` schema version 2 (site, pool, resource, canonical shape).
    Version 1 is unchanged.
  - `models/listing_models.py`: `VmCapacitySource` gains optional `listing_shape`.
  - `services/listing_service.py`: `derive_listing` checks that a shaped source's flattened
    shape equals the listing's published quantities and attributes.
  - `services/publication_loop.py`: `_create_request` passes the shape.
- [ ] 5.7 **Status.** `services/system_service.py` surfaces the new report fields. If the
  typed status model in `core/storefront-client` names derivation-report fields, extend it
  there too.
- [ ] 5.8 **Unit tests.**
  - `domains/vms/storefront/tests/unit/test_reconciler.py`:
    - fungible and specific shaped rows;
    - declared and available fit;
    - unknown availability;
    - unfit reported with no fallback;
    - unreadable held with no enumeration fallback;
    - override replaces the hint whole;
    - mixed-model pool: only the matching model's members serve a shape;
    - digest keys differ on edit;
    - the stored key read from the binding;
    - legacy tier precedence and reporting;
    - a pool with no shapes produces candidates identical to a fixture captured before the
      change.
  - `test_listing_comparison.py`: dimension identity fields come from `DIMENSION_KEYS`.
  - `test_listing_source_check.py`: a shaped listing's declared match uses fit, reports
    declared-match versus availability, and makes no site call when unbacked.
  - `domains/vms/domain/tests/test_storefront_adapter.py`: published fields for shaped and
    enumerated candidates.
  - A new `domains/vms/storefront/tests/unit/test_shape_fit.py`: parity cases from 0.1.
- [ ] 5.9 **Integration tests.** In `domains/vms/storefront/tests/integration/test_publication_loop.py`,
  test:
  - a pool hint publishes shaped listings and no enumeration slices;
  - an override replaces the list;
  - a shape edit closes and republishes, leaving the binding row unmodified;
  - a declaration shrink closes;
  - backed memory being taken makes a shape unpublishable;
  - a capacity event does not resize a shaped listing;
  - a pool without shapes is unchanged;
  - a dry run reports without changing anything;
  - a shaped listing negotiates to acceptance, and the fake site records a reservation
    requesting every shape dimension.

## 6. Override API (decision 7; `storefront-publication` delta)

- [ ] 6.1 **Service.** Add `domains/vms/storefront/src/market_storefront/services/pool_override_service.py`,
  applying checks in this order:
  1. An unconfigured site or an invalid record is refused with `422`, without any site
     call.
  2. The live projection is fetched through `capacity_runtime.site_client(site_id)`.
     Unreachable or unverifiable gives a retryable `503` naming the site.
  3. A pool absent from the live generation is refused with `404`.
  4. Otherwise the record is stored.
  
  The fit report is computed from the live generation with `shape_fits`, with that
  generation's revision and digest. After the write it triggers a refresh through
  `services/site_projection_cache.py` and calls `wake_publication_loop()`. The live result
  is not written to the cache.
- [ ] 6.2 **Routes.** Add `PUT`, `GET` (one or list), and `DELETE`
  `/api/v1/admin/pool-overrides` to `controllers/admin_controller.py`, with site and pool in
  the body or query.
- [ ] 6.3 **Identity contract.** In `middleware/admin_identity.py`, add
  `admin_put_pool_override`, `admin_get_pool_override`, `admin_list_pool_overrides`, and
  `admin_delete_pool_override`.
  - Resources are the length-prefixed site and pool.
  - Share the encoder with the reconciler's derivation keys by making `_length_prefixed` a
    public helper in `domains/vms/listings/reconciler.py`.
- [ ] 6.4 **Client.** In `core/storefront-client/src/storefront_client/client.py`, add
  `put_pool_override`, `get_pool_override`, `list_pool_overrides`, and `delete_pool_override`
  to both the async and sync clients, with typed response models.
  - Bump `arkhai-core-storefront-client` from 0.19.1 to 0.20.0.
  - Raise the VM storefront's lower bound.
- [ ] 6.5 **CLI.** Add `domains/vms/storefront/src/market_storefront/groups/pool_overrides.py`
  with `market-storefront pool-override set|get|list|delete`. `set` reads a record document
  (`--file`) and calls the typed client. Register it in `cli.py` and add it to the module
  docstring's subcommand list.
- [ ] 6.6 **Fake site.** `domains/vms/storefront/tests/fake_site.py` serves a signed
  `GET /api/v1/capacity/site-resource-pools` from its projection rows, with a switch to make the site
  unreachable. `resolve_capacity_route` in `kit/site-client` already names that route.
- [ ] 6.7 **Unit tests.**
  - `test_admin_auth.py`: the four semantic operations; resources that stay unambiguous for
    IDs containing delimiters; body and query binding.
  - A client parity test for the new methods, in the style of
    `test_lifecycle_client_parity.py`.
  - `core/storefront-client/tests/test_admin_auth.py`: request construction.
- [ ] 6.8 **Integration tests.** Add `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`,
  through the typed client.
  - Acceptance returns the fit report and generation.
  - An unknown pool is refused while the storefront's cache still lists it.
  - An unreachable site is refused as retryable, with the reason distinct from an unknown
    pool.
  - An unfit shape is accepted, and the next cycle publishes nothing for it.
  - A vocabulary error is refused with zero site requests recorded.
  - An unconfigured site is refused.
  - Delete is idempotent.
  - An orphaned override is retained and reported, and applies again when the pool returns.
  - Deleting an override over a legacy home-site value restores the legacy value and
    status reports it.
  - An override at a non-home site applies.
  - An exact retry returns the recorded outcome.
  
  Rejection-path cases assert status and stored state only.

## 7. Discovery and end to end (proposal Impact)

- [ ] 7.1 **Registry filters.** In `core/registry/tests/integration/test_listings_filtering.py`:
  - a listing publishing `ram_gb` matches `ram_gb` lower bounds at or below its value and
    is excluded above;
  - a listing without `ram_gb` is still excluded by any `ram_gb` filter;
  - a shaped listing's published `listing_resource` validates against
    `core/registry/filter-spec.yaml`.
- [ ] 7.2 **End-to-end helpers.** In `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`,
  `declare_e2e_capacity` accepts a full capacity map and `register_e2e_pool` accepts
  `listing_shapes`. Existing callers are unchanged.
- [ ] 7.3 **Scenario.** Add a new `test_listing_shapes.py` scenario under
  `e2e-tests/tests/e2e/roles/scenarios/vms/`, with marker `e2e_listing_shapes` registered in
  `e2e-tests/pyproject.toml`.
  - A 2-GPU, 16 vCPU, 64 GiB, 200 GiB declaration in a pool that lists a
    1-GPU/8/32/100 shape.
  - The buyer discovers it with `--resource 'ram_gb>=32'` and gets nothing with
    `ram_gb>=33`.
  - It negotiates, settles, and provisions.
  - The committed reservation dimensions equal the shape.
  - A storefront override through the typed client replaces the shape, and a publication
    cycle closes and republishes.
  - The VM scenarios with no shapes pass unchanged.

## 8. Validation

- [ ] 8.1 Run the default `make test` of every affected project:
  - `core`, `core/registry`, `core/storefront-client`;
  - `kit/resource-pools`, `kit/site`, `kit/site-client`;
  - `provisioning/compute/service`;
  - `domains/vms/domain` and `domains/vms/storefront`, including the listings, negotiation,
    and settlement suites it runs;
  - `domains/vms/buyer`;
  - `domains/apicredits/storefront` and `domains/apicredits/service`;
  - `domains/bare_metal` and `domains/bare_metal/storefront`;
  - `e2e-tests/tests/unit`.
  
  Disclose any suite not run.
- [ ] 8.2 **Packaging.**
  - Run `make dist-ci`.
  - Check wheel contents for `market_core/capability_shape.py`.
  - Bump `arkhai-vms-storefront` from 0.5.0 to 0.6.0 and its pin in
    `domains/vms/storefront/Dockerfile`, so the image-version guard holds.
  - Run type checks where the affected projects configure them.
- [ ] 8.3 **No-default inventory.** Search publication, listing derivation, the claim, and the
  fulfillment translation for defaults, `or` fallbacks, or inferred values that could
  publish or reserve a dimension no shape declares. Record the result.
- [ ] 8.4 Run `make check-reinit` and resolve every gap it reports.
- [ ] 8.5 Run `openspec validate --all --strict` and compare the result with the baseline
  current at implementation time.

## 9. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 9.1 **Comment hygiene.** Run `make check-comment-hygiene`. Then read directly:
  - the docstrings in `domains/vms/listings/reconciler.py` that describe a GPU-only shape;
  - `IDENTITY_FIELDS`' "once publication carries them" comment;
  - `vm_listing_resource_for_listing`;
  - `compute_capacity_claim_from_order`'s "fixed, seller-declared shape" docstring.
- [ ] 9.2 **Import placement.** Review each import this change adds or touches. The existing
  local import of `market_resource_pools` in the reconciler stays local, because buyers
  install the listings package without the `pools` extra. Verify any new local import the
  same way.
- [ ] 9.3 **Documentation compliance.** Re-check decisions 1–9 against the placement table
  in `openspec/README.md`.
- [ ] 9.4 **Narrative compression.** Compress completed task notes.
- [ ] 9.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, update Goal 2's current
  state (listings no longer GPU-only where shapes are declared; dimension filters match
  shaped listings) and this change's gap row. Record the update in the promotion record.
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
  exercising this change: `e2e_listing_shapes` plus the unchanged VM scenarios. If it
  cannot run for an unrelated reason, record the blocker and treat the validations it gates
  as unrun.
- [ ] 9.9 **Promotion** (after code review). Promote to:
  - `openspec/specs/storefront-publication/spec.md`, `openspec/specs/resource-pool-management/spec.md`,
    and `openspec/specs/market-composition/spec.md`: the synced deltas, with evidence entries;
  - `openspec/specs/storefront-publication/architecture.md`: a section on listing shapes and
    the storefront's authority, covering the commitment argument, chosen versus inferred
    shapes, the three layers, overrides, and the live write check;
  - `docs/development/ARCHITECTURE.md`:
    - storefront capacity boundary;
    - an authority-table row for listing shapes;
    - package layers (`market_core` capability shape; `kit/resource-pools` → `arkhai-core`);
    - one name per concept (listing shape, `listing_shapes`);
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`: `listing_shapes` in pool definition
    entries; storefront pool overrides administered through the API; the legacy home-site
    tier;
  - `docs/development/TESTING.md`: a listing-shape coverage split, in the style of
    "Pool Offering-Mode Enforcement".

## Superseded plan

The original tasks predate the design revision of 2026-09-24. None was started.

| Original task | Disposition |
|---|---|
| 1.1 Re-verify context | Replaced by 0.2 |
| 1.2 Carry the projection's capacity map through the slice builder | Superseded by decision 1: dimensions are published only from chosen shapes (5.2) |
| 1.3 Emit each declared dimension from `DIMENSION_KEYS` | Superseded by decision 1; the vocabulary is `VM_CAPABILITY_SCHEMA` (2.1, 5.4) |
| 1.4 No provisioning default reaches a candidate | Kept as 8.3 |
| 1.5 Focused tests | Replaced by 5.8 |
| 2.1–2.2 Registry filter coverage | Kept as 7.1 |
| 2.3 End-to-end `--ram-gb-min` path | Replaced by 7.3; the flag is now a `--resource` query |
| 3.1–3.2 Validation | Replaced by section 8 |
| 4.1–4.9 Closeout | Replaced by section 9 |

## Design promotion record

Filled in during implementation. Destinations planned:

| Accepted decision | Permanent location |
|---|---|
| A published dimension is a commitment; dimensions are published only from chosen shapes | `openspec/specs/storefront-publication/spec.md` — "A pool's listing shapes are chosen by its site and its storefront"; rationale in `openspec/specs/storefront-publication/architecture.md` |
| Shapes are chosen by pool hint, replaced per pool by the storefront; how many fit is derived | Same requirement; `docs/development/ARCHITECTURE.md` storefront capacity boundary and authority table |
| A shape is publishable only where the site's own predicate admits it | `openspec/specs/storefront-publication/spec.md` — "A listing shape is published only where its source can hold it" |
| A shaped listing's identity includes its shape digest | `openspec/specs/storefront-publication/spec.md` — "A shaped listing's derivation identity includes its shape" |
| Site-scoped, durable storefront pool overrides and the legacy tier | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are site-scoped and durable"; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Override writes are checked against the site's live projection | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are written against the site's live projection" |
| `listing_shapes` hint and structural validation | `openspec/specs/resource-pool-management/spec.md` |
| Family-grouped shapes flattened by one shared utility in `market_core` | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` package layers |
| Omission beats inference for pools without shapes | This change's `design.md` |
| Flat-name exception to the family-prefixed convention | This change's `design.md`; `structured-capacity-requirements`' `design.md` |
| Roadmap currency | `docs/development/ROADMAP.md` Goal 2 (task 9.5) |
| Campaign index currency | `openspec/changes/README.md` (task 9.6) |
