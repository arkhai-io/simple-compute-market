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

## 0. Pre-implementation gates

- [x] 0.1 **Decision gate — feasibility-predicate parity** (decision 4).
  - What to check: `compute_capacity_claim_from_order` applied to a shaped
    `listing_resource`, then `market_site.dict_resource_satisfies_claim` applied to a
    projected member or capacity bucket adapted to the snapshot-row shape. It must give the
    same answer as the resource-requirement step inside `kit/site` admission,
    `resource_satisfies_requirement` over the ledger's feasibility view, for the same
    declaration and claim.
  - Cases:
    - a member declaring `region` and `gpu_model`;
    - a pool whose region comes only from the pool hint;
    - a projected member whose `resource_type` is absent;
    - a specific-resource claim, which drops `pool_id`;
    - a capacity bucket standing in for fungible members.
  - This gate covers the predicate only. The admission checks it deliberately excludes are
    listed in decision 4.
  - Outcome: record the result in `design.md` decision 4. Where the predicate disagrees with
    the ledger's own requirement step, **pause for design review**.
  - **Result (2026-09-24):** recorded in `design.md` decision 4, "Parity gate result".
    - The predicate agrees with the ledger's step on every real projected member and bucket
      once the adapter maps the projection's field names.
    - It disagrees on a member without `resource_type`: the contract builder, the fake site,
      and hand-built test members produce one.
    - A hint-only `region` is refused by both, which silently delists such pools.
    - Both were put to design review, which answered them the same day (`design.md`
      decision 4, "Design review of the gate"): the projection contract requires
      `resource_type` and a member without one is unresolvable (4.12); a default shape
      failing against declared capacity is reported per pool (4.2). Gate cleared.
- [x] 0.2 Re-verify the Context findings in `design.md` that later tasks depend on:
  - `_projected_resource_usage` reads only `gpu_count`;
  - enumeration keys and the version 1 envelope;
  - the claim copies `DIMENSION_KEYS`;
  - the requirement delegate's GiB translation;
  - the provider falls back to pool defaults;
  - `_find_candidate`'s checks beyond the predicate;
  - buckets group on the full `available` map and attributes;
  - the buyer sends no `compute_resource`;
  - the home-site-only legacy override read;
  - the fake site serving no resource-pool projection;
  - seller-close and pause semantics.
  
  Record any that moved.
  - **Result (2026-09-24):** every listed finding holds. Additional facts later tasks depend
    on:
    - The provider's default fallback is in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_fulfillment_provider.py`,
      per dimension; its tests stay where 4.10 names them.
    - The version 1 envelope carries site, pool, resource, and `gpu_count`, but no
      `gpu_model`. The carry-over (4.7) reads the model from the stored listing.
    - Bindings enforce a unique `derivation_key`. The loop finds a seller-closed listing
      under the derived key and skips it, as the carry-over relies on.
    - The fake site's projection omits `resource_type` and advertisement/backing
      declarations, and its matcher tracks availability for `gpu_count` only. Two 4.11
      cases need per-dimension fake-site accounting, which no task yet names: backed memory
      being taken, and a reservation requesting every declared dimension.

## 1. Shared utilities in `market_core` (decisions 3, 7; `market-composition` delta)

- [x] 1.1 Add `core/src/market_core/capability_shape.py`. Provide:
  - the schema types: per family field, its kind (quantity or attribute), whether it is
    required, and its flat name;
  - `shape_structure_problems(shape)`, which needs no schema;
  - `flatten_shape(shape, schema)`, returning quantities and attributes or problems, each
    problem naming its `family.field` path. Quantities are positive integers, `bool`
    refused; attributes are non-empty strings;
  - `canonical_shape(shape)`;
  - `shape_digest(shape)`, domain-tagged `capability-shape.v1:<sha256>` over the canonical
    family-grouped JSON.
  
  The module names no family or field.
  - **Done.** Problems come from `shape_problems`; `flatten_shape` raises
    `CapabilityShapeError` carrying every problem, rather than returning a union of shape
    and problems.
  - **Amended after code review:** moved out of the market core to the foundation kit
    `kit/capability-shape` (`market_capability_shape`, see 1.5), because a capability
    shape is capacity vocabulary, not a concept every market shares.
- [x] 1.2 Add a small neutral module in `market_core` exporting the length-prefixed
  component encoding now private to `domains/vms/listings/reconciler.py`
  (`_length_prefixed`), byte-identical. Move the reconciler onto it. Every existing
  derivation key must be unchanged; a test asserts known keys.
  - **Done.** The concept packages reach the encoding through `arkhai_vms`
    (`arkhai_vms/capability_shapes.py`, design decision 3), and the reconciler now uses
    it; the known keys are unchanged.
  - **Earlier note:** `core/src/market_core/identifier_encoding.py` exists and is tested.
    Moving the reconciler onto it broke the enforced rule that VM concept modules import no
    core package, so the move was reverted and is held for the open question in `design.md`
    ("How do VM concept modules reach the shared shape utility and encoding?"). The
    known-key test stands.
  - **Amended after implementation review:** the key builders moved to
    `arkhai_vms/listing_keys.py`, which uses the encoding; `arkhai_vms` no longer exports it.
    The reconciler imports the builders, and their byte forms are unchanged.
- [x] 1.3 Tests in `core/tests/unit/`. For `test_capability_shape.py`:
  - structure accepted and refused without a schema;
  - flatten with a test schema;
  - a missing required field;
  - an unknown family or field, naming its path;
  - a wrong value kind, including `True` as a quantity;
  - digest stability under key order;
  - digest unchanged when a schema renames a flat name.
  
  Add encoding tests for delimiter-bearing values, and confirm `test_carrier_purity.py` and
  `test_domain_boundaries.py` still pass.
  - **Done.** `test_capability_shape.py` (now in `kit/capability-shape/tests/unit/`) and
    `test_identifier_encoding.py`; the known-key
    test is in `domains/vms/storefront/tests/unit/test_reconciler.py`. Core suite 132
    passed, purity and domain-boundary tests included.
- [x] 1.4 **Version and pins.**
  - Bump `arkhai-core` from 0.2.0 to 0.3.0 (new public API).
  - Update the exact `arkhai-core==0.2.0` pins to `==0.3.0` in:
    - `kit/settlement-runtime/pyproject.toml`
    - `kit/hosted-settlement/pyproject.toml`
    - `kit/contact-exchange/pyproject.toml`
    - `core/registry-client/pyproject.toml`
    - `core/registry/pyproject.toml`
  - Raise the lower bound to `>=0.3.0` where a consumer imports the new modules.
  - Relock every project whose lock changes.
  - **Done.** `arkhai-core` 0.3.0; the five exact pins updated. Every lock carrying a
    changed internal package was relocked with its relative wheel path. Two locks resolve
    `torch` from an index outside the implementation environment, so their changed internal
    entries were edited by hand and proved with a frozen sync: `domains/vms/storefront`
    and `domains/vms/buyer`. They should be relocked where that index is reachable.

- [x] 1.5 **Capability-shape foundation kit** (code review of 1.1).
  - Add `kit/capability-shape`, distribution `arkhai-kit-capability-shape` 0.1.0,
    importing only the standard library, with build and test targets, a boundary test,
    and entries in `kit/Makefile`'s `dist-ci` and `test` lists.
  - Move the utility and its tests there from `core`. `arkhai-core` stays 0.3.0 for the
    identifier encoding.
  - `kit/resource-pools` and `arkhai-vms` depend on the kit rather than on `arkhai-core` for
    shapes.
  - **Done.** Kit suite 32 passed. Every lock installing the kit was relocked, the two
    torch-bound locks by hand, and `make check-reinit` required the kit in the `reinit` of
    ten projects, now added. The `arkhai-core` `reinit` lines added under 3.3 were
    withdrawn, because those locks no longer install `arkhai-core`.

## 2. VM family schema and default generator (decisions 2, 3)

- [x] 2.1 In `domains/vms/domain/src/arkhai_vms/compute_requirements.py`, add
  `VM_CAPABILITY_SCHEMA`:
  - `gpu.count` → `gpu_count`, a required quantity;
  - `gpu.model` → the `gpu_model` attribute, required;
  - `cpu.count` → `vcpu_count`, optional;
  - `memory.gib` → `ram_gb`, optional;
  - `storage.gib` → `disk_gb`, optional.
  
  Export it from `arkhai_vms/__init__.py`. Carry the flat-name exception as a comment
  stating the rule: these are the published wire names, and they are GiB.
  - **Done.** Exported from `arkhai_vms`, with `GPU_MODEL_ATTRIBUTE`.
- [x] 2.2 Add the default shape generator interface and its GPU-only implementation in the
  VM domain. Members go in; shapes come out, one per GPU count from 1 to the largest declared
  count, for each GPU model present among enabled members. The implementation can live in
  `arkhai_vms` or in `domains/vms/listings`; choose the lowest package whose dependencies
  already allow it and record the choice.
  - **Done.** `arkhai_vms/shape_generation.py`, the lowest package whose dependencies
    already allow it: `ListingShapeGenerator`, `gpu_count_shapes`, and
    `DEFAULT_LISTING_SHAPE_GENERATOR`.
- [x] 2.3 In `domains/vms/domain/pyproject.toml`, set `arkhai-core>=0.3.0` and bump
  `arkhai-vms` from 0.3.0 to 0.4.0.
  - **Done.**
- [x] 2.4 In `domains/vms/domain/tests/test_compute_requirements.py`, and a generator unit
  test, cover:
  - the schema's quantity flat names equal `DIMENSION_KEYS`;
  - the required and optional fields;
  - one representative flatten;
  - generator output for single-model and mixed-model pools;
  - members with no GPU count are skipped.
  - **Done.** `test_compute_requirements.py` and `test_shape_generation.py`; suite 28 passed.

## 3. `listing_shapes` pool hint (decision 8; `resource-pool-management` delta)

- [x] 3.1 In `kit/resource-pools/src/market_resource_pools/hints.py`, add:
  - `LISTING_SHAPES_POLICY_TAG`;
  - `raw_listing_shapes(policy_tags, offering_mode)`;
  - `validate_listing_shapes(policy_tags)`, which requires a mapping of offering mode to a
    non-empty list, with each shape passing the capability-shape kit's structure check.
  
  Export them from `market_resource_pools/__init__.py`.
  - **Done.**
- [x] 3.2 In `kit/resource-pools/src/market_resource_pools/service.py`, add
  `validate_listing_shapes` to `_require_valid_policy_tag_hints` and to the bulk-document
  path, with path `...policy_tags.listing_shapes` and code `invalid_listing_shapes`.
  - **Done.**
- [x] 3.3 **Packaging for `kit/resource-pools`.**
  - Add `arkhai-core>=0.3.0` to its `pyproject.toml` and bump it from 0.3.0 to 0.4.0.
  - Add a `reinit` target to `kit/resource-pools/Makefile` that reinstalls `arkhai-core`
    from `.dist`.
  - In the root `Makefile`, declare `dist-ci-kits` and `dist-kits` after `dist-core`.
  - Relock.
  - **Done.** `make check-reinit` then required `arkhai-core` in the `reinit` of
    `kit/fulfillment`, `kit/site`, and `provisioning/compute`, now added.
  - **Amended after code review:** the root `Makefile` ordering was not made. `uv build`
    builds each wheel in isolation with only its build backend and resolves no runtime
    dependency, so a kit wheel builds without the `arkhai-core` wheel present; ordering
    matters only to `uv sync`, which runs after `make dist`. The edge added nothing but a
    core rebuild on a standalone `make dist-kits` and a constraint on parallel builds.
- [x] 3.4 **`kit/resource-pools` tests.**
  - `tests/unit/test_hints.py`:
    - valid shapes;
    - an empty list;
    - a non-mapping family;
    - a non-scalar field;
    - a field no domain defines, which is accepted.
  - `tests/integration/test_resource_pool_service.py`: identical refusal across create,
    replace, patch, and bulk import, with nothing stored.
  - **Done.** Suite 222 passed.
- [x] 3.5 **Provisioning tests.**
  - `provisioning/compute/service/tests/integration/test_pools_api.py`: refusal through the
    typed provisioning client, asserting status and stored state only (rejection path).
  - `provisioning/compute/service/tests/integration/test_capacity_api.py`: the hint is
    projected verbatim.
  - **Done.** A pool is projected with its members, so the projection test declares one.

## 4. Shapes for every listing, feasibility, identity (decisions 2, 4, 5, 9)

- [x] 4.1 Add `domains/vms/listings/listing_shapes.py`. It resolves a pool's VM shapes:
  - the pool's `listing_shapes` hint for `vm` if stated;
  - otherwise the default generator.
  
  It validates stated shapes through `VM_CAPABILITY_SCHEMA` and returns one outcome: `shapes`
  (with their source) or `unreadable` (with its problems). Slice B adds the override tier
  above the hint.
  - **Done.** `domains/vms/listings/listing_shapes.py`. A present `listing_shapes` value
    that is not a mapping is unreadable too, never the default.
- [x] 4.2 **Reconciler** (`domains/vms/listings/reconciler.py`).
  - Replace per-pool GPU-count enumeration with shape resolution and feasibility for every
    pool:
    - fungible: one row per feasible shape;
    - specific resource: one per member per shape that member is feasible for.
  - Feasibility goes through an injected `shape_feasible` callable:
    - declared capacity for every listing;
    - for backed fungible pools, the site's capacity buckets when loaded, using the existing
      loaded, empty, and unreadable rules; otherwise per-member `available`;
    - for backed specific-resource pools, the member's `available`;
    - a member reporting no availability is judged on declared capacity.
  - A stated shape no member is feasible for yields no row and is reported per shape. A
    default shape no member is feasible for against declared capacity is reported once per
    pool, naming the claim attribute no enabled member declares; failing only against
    availability is not reported. An unreadable hint holds the pool and is reported, with no
    fallback to the default generator.
  - A member with a malformed GPU count, or without a `resource_type`, is unresolvable and
    reported, and holds its pool (fungible) or its own listings (specific resource).
  - Price each row by its shape's `gpu.model`.
  - Candidates carry the canonical shape, its digest, the flattened quantities and
    attributes, and a reconciler key built from site, pool or resource, and the digest.
  - `available_compute_slices`, `current_available_resource_keys`, `stale_open_listing_ids`,
    and `closed_available_listing_ids` take `shape_feasible` as a required keyword.
  - `_bound_vm_listings` reads `source_envelope_json`. `stored_listing_key` reads the key
    from a version 2 envelope. For a version 1 envelope it returns a key that is never
    derived, so such a listing is never reopened and, while open, closes as stale.
  - `slice_identity` carries every published identity field, with dimension names from
    `DIMENSION_KEYS`.
  - `_SiteDerivationReport` adds `infeasible_shapes` and `unreadable_shapes`, and drops
    `mixed_kind_pools`, which per-model generation makes obsolete.
  - **Done.** Shapes × feasibility replace GPU-count enumeration; pool rows keep their
    aggregate fields and gain the resolved and feasible shapes. Keys are
    `…:shape:<digest>`; the separate legacy key is gone. Stored keys come from the binding
    envelope; version 1 keeps its GPU-count key, which nothing derives. Stated infeasible
    shapes are reported per shape, a default shape failing on declared capacity per pool
    with the undeclared attribute; members without `resource_type` are held. The VM
    concept packages reach shape operations and the encoding through `arkhai_vms` (design
    decision 3).
- [x] 4.3 **Identity fields and packaging for `domains/vms/listings`.**
  - In `domains/vms/listings/listing_comparison.py`, build the dimension part of
    `IDENTITY_FIELDS` from `arkhai_vms.DIMENSION_KEYS`.
  - In `domains/vms/listings/pyproject.toml`, add `arkhai-vms>=0.4.0` and bump
    `arkhai-vms-listings` from 0.1.0 to 0.2.0.
  - Add `reinit` lines, relock, and export new names from
    `domains/vms/listings/__init__.py`.
  - **Done.** `arkhai-vms-listings` 0.2.0 depends on `arkhai-vms>=0.4.0`; new names
    exported.
- [x] 4.4 **Adapter.** In `domains/vms/domain/src/arkhai_vms/storefront_adapter.py`:
  - `vm_listing_resource_for_listing` publishes a candidate's `gpu_model`, `gpu_count`, and
    each quantity its shape declares, and nothing its shape omits;
  - `vm_candidate_skip_keys` handles shape keys.
  - **Done.** Publishes exactly the flattened shape; a candidate without a shape or a
    structural key is refused. The obsolete `vm_listing_resource_key` is removed.
- [x] 4.5 **Feasibility callable.** Add `domains/vms/storefront/src/market_storefront/services/shape_feasibility.py`.
  - It provides the injected callable: it builds the claim with
    `compute_capacity_claim_from_order` and judges it with
    `market_site.dict_resource_satisfies_claim`, configured with the container's unit claim
    keys and mirror dimension.
  - It adapts a projected member or capacity bucket to the snapshot row.
  - Pass it to every reconciler caller:
    - `services/publication_loop.py`
    - `services/publication_service.py`
    - `services/listing_source_check.py`
    - `failure_actions.py`
    - `controllers/admin_controller.py` (fulfillment-event handlers)
  - **Done.** `SiteShapeFeasibility`, with member and bucket adapters that invent nothing,
    wired into all five callers; the publication cycle and the guard take it by injection.
    The guard reads the listing's key from its stored binding.
- [x] 4.6 **Binding.**
  - `domains/vms/storefront/src/market_storefront/publication_binding.py`: every candidate
    writes `compute.listing_source` schema version 2 (site, pool, resource, canonical shape).
  - `models/listing_models.py`: `VmCapacitySource` gains `listing_shape`.
  - `services/listing_service.py`: `derive_listing` checks that the source's flattened shape
    equals the listing's published quantities and attributes.
  - `services/publication_loop.py`: `_create_request` passes the shape.
  - **Done.** `VmCapacitySource.listing_shape` replaces `gpu_count`; `derive_listing`
    refuses a listing whose published quantities or model differ from its shape.
- [x] 4.7 **Seller-state carry-over** (decision 5). Add
  `domains/vms/storefront/src/market_storefront/services/listing_identity_carryover.py`,
  invoked from `startup.py` before any lifecycle loop starts. For each version 1 VM listing:
  - compute the equivalent default shape and its version 2 derivation key from the stored
    listing and binding;
  - if the seller closed it, bind the successor closed by its seller, unpublished;
  - if it is paused and open, bind the successor paused;
  - do nothing when a successor is already bound.
  
  Report the count carried in system status.
  - **Done.** Runs as a fail-fast startup step before the negotiation watchdog. Uses
    `load_listing_binding_by_derivation`: `core_storefront`'s
    `listing_id_for_derivation_key` calls an undefined `_connect()`, a pre-existing defect
    outside this change.
  - **Amended after implementation review:** the listing-source query is a repository
    method, `list_listing_source_envelopes`. A successor already bound under its key is
    brought to the seller's state through the seller's own operations: an open one is
    closed as its seller (`close_order`) or paused (`set_listing_paused`); one reconciliation
    already closed is reported, since no seller operation changes who closed a listing.
- [x] 4.8 **Status.** `services/system_service.py` surfaces the new report fields and the
  carry-over count. If the typed status model in `core/storefront-client` names
  derivation-report fields, extend it there too.
  - **Done.** Status gains `listing_identity_carryover`; the new derivation fields pass
    through the existing opaque `publication_derivation`, so no client change was needed.
- [x] 4.9 **Unit tests.**
  - `domains/vms/storefront/tests/unit/test_reconciler.py`:
    - hint shapes, fungible and specific;
    - default shapes reproduce today's published fields for a single-model pool (golden
      fixture captured before the change);
    - mixed-model pools publish per model;
    - declared and available feasibility, including bucket-sourced availability for every
      dimension;
    - unknown availability;
    - an infeasible stated shape reported with no fallback;
    - an unreadable hint held with no fallback to the default generator;
    - a pool whose `region` is only a pool hint publishes nothing and is reported once,
      naming `region`; a default shape unavailable only on load is not reported;
    - a member without `resource_type` holds its fungible pool, or only itself in a
      specific-resource pool, and is reported;
    - digest keys differ on edit;
    - a declared shape identical to a default shape keeps its key;
    - the stored key read from the binding;
    - version 1 listings never reopen and close while open.
  - `test_listing_comparison.py`: dimension identity fields come from `DIMENSION_KEYS`.
  - `test_listing_source_check.py`: the declared match uses feasibility, reports
    declared-match versus availability, and makes no site call when unbacked.
  - `domains/vms/domain/tests/test_storefront_adapter.py`: published fields for stated and
    default shapes.
  - A new `domains/vms/storefront/tests/unit/test_shape_feasibility.py`: parity cases from
    0.1.
  - A new `domains/vms/storefront/tests/unit/test_listing_identity_carryover.py`:
    - seller-closed and paused successors;
    - reconciliation-closed and open listings untouched;
    - idempotent rerun.
  - **Done.** All planned cases, plus the hint-only-region report and the missing-type
    hold (`TestListingShapes`, 15 cases). `test_shape_feasibility.py` holds gate 0.1's
    parity against a real ledger (24 cases). Existing fixtures that claimed a region or
    model their members did not declare, or bound a listing differently from what it
    publishes, were corrected: both were hidden while keys were rebuilt from published
    fields.
  - **Amended after implementation review:** `test_shape_feasibility.py` moved to
    `tests/integration/` and compares against the ledger's public admission dry run,
    `CapacityLedgerService.probe`: declared feasibility on a ledger holding nothing,
    availability on one holding part of a member. No private site-kit helper is imported,
    and a check confirms both outcomes occur. `test_listing_identity_carryover.py` moved to
    `tests/integration/` too: both use a real database. `test_reconciler.py` stays where it is
    for now.
- [x] 4.10 **Provider-input test.** In
  `provisioning/compute/service/tests/unit/services/test_ansible_fulfillment_provider.py`,
  the existing provider suite:
  - a reservation carrying every declared dimension sizes the VM from them, not from pool
    defaults;
  - a reservation omitting a dimension uses the pool default, the accepted behaviour
    decision 3 records.
  - **Done.** The existing suite already proved declared dimensions win and defaults fill
    an empty reservation; added the GPU-only-shape case.
- [x] 4.11 **Integration tests.** In
  `domains/vms/storefront/tests/integration/test_publication_loop.py`, test:
  - a pool hint publishes its shapes and no default shapes;
  - a pool without a hint publishes default shapes whose fields match today's;
  - a shape edit closes and republishes, leaving the binding row unmodified;
  - a declaration shrink closes;
  - backed memory being taken makes a stated shape unpublishable;
  - a capacity event does not resize a listing;
  - a dry run reports without changing anything;
  - a stated shape negotiates to acceptance, and the fake site records a reservation
    requesting every declared dimension;
  - **upgrade:** a database with version 1 listings (open, seller-closed, paused,
    reconciliation-closed) starts, carries over, and runs one cycle. Afterwards:
    - each open listing is closed and succeeded once;
    - seller-closed and paused state is on the successors;
    - no version 1 listing reopens on a later capacity event;
    - no duplicate is open for any shape.

  - **Done.** All planned scenarios in `test_publication_loop.py`. A changed GPU model now
    closes and republishes, since the model is part of the shape; that test was rewritten
    for it.
- [x] 4.12 **Projection contract requires `resource_type`** (decision 4, gate review).
  - `kit/site-client/src/market_site_client/fixtures/resource_pools.py`:
    `build_projected_resource` sends `resource_type="compute.gpu"` by default, and
    `validate_resource_pool_projection` requires a non-empty string `resource_type` on every
    member.
  - `kit/site-client/tests/unit/test_resource_pool_fixture.py`: the validator refuses a
    member without it.
  - Bump `arkhai-kit-site-client` from 0.4.0 to 0.5.0. Resolve the consumers
    `make check-reinit` lists.
  - The provisioning producer test that already calls the validator keeps proving real sites
    comply.
  - **Done.** Done as specified.
  - **Amended after implementation review:** the requirement is a producer contract, so it is
    stated in a `site-capacity` delta modifying "Resource-pool projection metadata".
- [x] 4.13 **Fake site projects the contract and accounts per dimension.** In
  `domains/vms/storefront/tests/fake_site.py`:
  - projected members carry `resource_type`, and hand-built members in the storefront's own
    tests do too;
  - resources declare a full capacity map, and the matcher admits and holds every requested
    dimension, so 4.11's memory-taken and every-dimension reservation cases can be observed.
  - **Done.** Resources may declare a full capacity map; matching, holds, snapshots, and
    projections work per dimension, and reservations record every requested dimension.

## 5. Discovery, end to end, and slice A validation

- [x] 5.1 **Registry filters.** In `core/registry/tests/integration/test_listings_filtering.py`:
  - a listing publishing `ram_gb` matches `ram_gb` lower bounds at or below its value and
    is excluded above;
  - a listing without `ram_gb` is still excluded by any `ram_gb` filter;
  - a listing with a stated shape validates against `core/registry/filter-spec.yaml`.
  - **Done.** Added the at-value and above-value bounds, the GPU-only exclusion, and a
    shaped listing validating against the filter spec's listing schema.
  - **Amended after implementation review:** both new tests use the canonical
    `RegistryClient` against the in-process app: `list_listings(ram_gb_min=...)` for the
    filter bounds, and `validate_publish_listing` for the shaped listing.
- [x] 5.2 **End-to-end helpers.** In `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`,
  `declare_e2e_capacity` accepts a full capacity map and `register_e2e_pool` accepts
  `listing_shapes`. Existing callers are unchanged.
  - **Done.** `provision_e2e_executor` passes both through. `capacity_source_for` and the
    hosted scenario's capacity source now send `listing_shape`.
- [ ] 5.3 **Scenario.** Add a new `test_listing_shapes.py` scenario under
  `e2e-tests/tests/e2e/roles/scenarios/vms/`, with marker `e2e_listing_shapes` registered in
  `e2e-tests/pyproject.toml`.
  - A 2-GPU, 16 vCPU, 64 GiB, 200 GiB declaration in a pool whose hint lists a
    1-GPU/8/32/100 shape.
  - The buyer discovers it with `--resource 'ram_gb>=32'` and gets nothing with
    `ram_gb>=33`.
  - It negotiates, settles, and provisions.
  - The committed reservation dimensions equal the shape, and the provisioning job's VM
    parameters come from them.
  - The existing VM scenarios, now publishing default shapes, pass unchanged.
  - **Written; not yet run.** The scenario's nine stages cover the pool hint and
    multidimensional declaration, publication of exactly the stated shape, `--resource`
    discovery at 32 and 33 GiB, a one-shot `market buy` to ready through the same memory
    query, the site reservation holding exactly the shape's quantities, and the create
    job's VM parameters (1 GPU, 8 vCPUs, 32 768 MiB, `100G`).
  - Statically confirmed seams: the listing's terms come from the pool's own `pricing`
    hint, which outranks storefront configuration and has no legacy row above it; the
    Alkahest composition scales a clause rate of `10` to 10¹⁹ base units, the rate the
    one-shot buy scenario's listing advertises, so its buyer prices carry over; the
    typed `SyncProvisioningClient` exposes `list_capacity_reservations` (whose payload
    carries `dimensions`) and `list_jobs` (whose jobs carry `params`). The pool helpers
    gained a `pricing` argument.
- [ ] 5.4 **Slice A validation.**
  - Run the default `make test` of every project slice A touches:
    - `core`, `core/registry`;
    - `kit/resource-pools`, `kit/site`, `kit/site-client`;
    - `provisioning/compute/service`;
    - `domains/vms/domain`, `domains/vms/storefront`, `domains/vms/buyer`;
    - `domains/apicredits/storefront` and `domains/apicredits/service`;
    - `domains/bare_metal` and `domains/bare_metal/storefront`;
    - `e2e-tests/tests/unit`.
  - Run `make dist-ci`, then `make check-reinit`, resolving every gap.
  - Run `openspec validate --all --strict` against the baseline.
  - Disclose anything not run.
  - **Status (2026-09-24):** every listed project's default `make test` passes, plus
    `kit/capability-shape`, `kit/capacity-publication`, `kit/fulfillment`, and
    `core/registry-client`. The VM storefront and buyer ran against frozen environments,
    because their `reinit` resolves `torch` from an index the implementation environment
    cannot reach; the storefront's two Alkahest integration tests need a `node` runtime it
    lacks. One `e2e-tests` unit test fails identically on the unchanged tree.
    `make check-reinit` passes. **Not run:** the end-to-end pipeline, which this task and
    5.3 still need.
  - **First pipeline run (2026-09-24):** 114 passed, 3 skipped, and every existing VM
    scenario passed against Slice A, including those creating listings through the
    shape-bearing capacity source. The new scenario did **not** run: CI selects scenarios
    through `E2E_MODULE` in `e2e-tests/Makefile`, and 5.3 registered the marker only in
    `pyproject.toml`. The marker is now in `E2E_MODULE`; 5.3 needs a second run.
  - **`make test`:** `domains/apicredits` failed one install test, whose wheel set in
    `domains/apicredits/tests/conftest_wheels.py` lacked `kit/capability-shape`, now a
    dependency of the pool kit. Added; the suite passes (42). The earlier sweep had run the
    `service` and `storefront` projects but not the `domains/apicredits` root project.
  - **Lockfiles:** the maintainer's `uv` regenerated five locks without the platform and
    Python markers the implementation environment's `uv` wrote; two returned exactly to
    their original form. Those are canonical and adopted. Internal wheels listed twice in
    eleven locks are pre-existing: a lock records one entry per `find-links` source, and
    each `reinit` passes `--find-links` for the directory its `pyproject.toml` already names.
    Out of scope here; worth its own issue.
  - Recorded evidence: `make dist-ci` and `make dist-kits` succeed; `make check-reinit`
    passes; strict OpenSpec validation completes at the repository baseline (73 passed,
    19 failed, all pre-existing), with this change passing.
  - **Second pipeline run (2026-09-24):** 116 passed, 1 failed, 9 skipped. The new
    scenario ran and failed at 01a: the cycle refused its candidate because the listing's
    `region` was null. A listing advertises its pool's `region` hint (or the legacy local
    row), never a member attribute, and the scenario's pool stated none. The pool helpers
    gained a `region` argument and the scenario states the region on the pool as well as on
    the declaration, which reservations match. Stage 01a now reports the cycle's actions
    for its pool when it fails. The same cycle refused the `buy`, `deal-cli`, and `deal`
    scenarios' pools for the same reason; that predates this change, since region
    resolution is unchanged, and those scenarios publish through the API. 5.3 needs a third
    run.

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
    and `openspec/specs/market-composition/spec.md`: the synced deltas, with evidence entries;
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
    - declare `region` and `gpu_model` on capacity declarations, since claims match them
      against the declaration and a pool-hint region alone publishes nothing;
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
