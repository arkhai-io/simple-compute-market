# Implementation Tasks

Sections sized to land in roughly a day each. Every section is additive and deployable
alone. Section 4 is `negotiation-driven-capacity-resize`'s and Section 5 moved; both
numbers are kept.

*Re-planned 2026-10-01, twice.* No task has been completed in this tree. The first
re-plan replaced the 2026-08-06 entries (summarized under "Superseded planning-time
entries" below); this one follows the design revision after review (`design.md`,
"Review dispositions") and the landing of `publish-indicative-listing-rates`. An
implementation of the first re-plan exists against the pre-landing tree; tasks say
where it is carried forward and what changes. Every amount in every task is a Python
`int`, exact decimal text, or a `Fraction`; none passes through `float` or through
`Decimal` arithmetic under a precision context, and none is stored in a fixed-width
column.

## 1. Exact amounts, the pricing kit, and the selected-option reference

Design: "Every amount is exact, and nothing rounds silently"; "Price aggregation is a
replaceable interface in its own foundation kit"; "Which families are priced, and by
what key, is an explicit domain projection"; "The seller's reference amount is the
selected option's rate".

- [x] 1.1 Re-verify `design.md`'s Context against this tree, including the landed
      asking-rate code in `reconciler.py`, `listing_comparison.py`, and the pool-override
      kit, and that `kit/negotiation-runtime` calls `reference_amount` only from its
      continuation path.
      *Done 2026-10-01.* Confirmed.
- [x] 1.2 Exact conversion helper `decimal_rate_to_base_units` beside clause validation
      in `kit/settlement-runtime/src/market_settlement_runtime/publication.py`, exported
      from the package: decimal text and an asset exponent to integer base units by
      integer arithmetic; refuses non-plain text, a non-whole or non-positive result, and
      a result above `2**256 - 1`. Tests in a new
      `kit/settlement-runtime/tests/unit/test_publication_rates.py`. Carried forward.
      *Done 2026-10-01.* Suite passes (109).
- [x] 1.3 Use it in the Alkahest scaler (`kit/alkahest/src/market_alkahest/settlement_config.py`)
      and the hosted scaler `_stripe_rate_minor_units`
      (`kit/hosted-settlement/src/market_hosted_settlement/settlement_config.py`),
      removing their context-limited `Decimal` arithmetic. Tests in each kit's
      `tests/unit/test_settlement_config.py`: a 40-significant-digit whole rate converts
      exactly; one below a base unit is refused; the uint256 bound refuses. Carried forward.
      *Done 2026-10-01.* Both suites pass.
- [x] 1.4 Create `kit/capability-pricing` (`arkhai-kit-capability-pricing`,
      `market_capability_pricing`) on `kit/capability-shape`'s layout: `pyproject.toml`
      depending only on `arkhai-kit-capability-shape`, `Makefile`, `uv.lock`,
      `src/market_capability_pricing/__init__.py`, and `tests/unit`. Register it in
      `kit/Makefile` (`test`, `test-capability-pricing`, `dist`, `dist-ci`,
      `dist-capability-pricing`, and their `.PHONY`).
      *Done 2026-10-01.* Done; `uv.lock` created against the wheelhouse.
- [x] 1.5 In the new kit: `FamilyRate` (positive decimal text and a unit token),
      `ShapePrice` (exact decimal text and unit), `PricingProjection` (per priced family,
      its one quantity field and optional pricing-key attribute) with
      `pricing_projection_problems(projection, schema)`, the `PriceAggregator` protocol
      (shape, one asset's family rates, projection → `ShapePrice`), and `linear_price`.
      `linear_price` prices each family the shape names that has a rate, ignores the
      rest, returns a zero amount when none applies, and refuses a family the projection
      does not price, a binary float, and rates naming different units. Imports only the
      standard library and `market_capability_shape`. Ported from the earlier
      `market_capability_shape.pricing`, with unrated families now contributing nothing
      rather than making the shape unpriceable.
      *Done 2026-10-01.* `ShapePrice` reports `is_zero`; a zero price carries no unit. `linear_price` does not validate the shape against a schema — the domain binding does, before pricing.
- [x] 1.6 Tests in `kit/capability-pricing/tests/unit/test_pricing.py`: the worked example
      is `174.4`; an unrated named family contributes nothing; no applicable rate is
      zero; an omitted family is not priced; a 40-significant-digit result is exact; zero,
      negative, float, and exponent rates are refused; mixed units are refused; a
      projection disagreeing with its schema is reported. An import-boundary test in
      `tests/unit/test_import_boundary.py` asserts nothing beyond the standard library and
      the shape kit is imported.
      *Done 2026-10-01.* Suite passes (22).
- [x] 1.7 VM binding in `domains/vms/domain/src/arkhai_vms/capability_shapes.py`, exported
      from `arkhai_vms/__init__.py`: `VM_PRICING_PROJECTION` (`gpu` by `count` per `model`;
      `cpu` by `count`; `memory` and `storage` by `gib`), `VM_PRICE_AGGREGATOR`,
      `price_vm_shape`, and `vm_family_rate` (time units only, via `PER_UNIT_SECONDS`).
      Add `arkhai-kit-capability-pricing` to `domains/vms/domain/pyproject.toml`. Tests in
      `domains/vms/domain/tests/test_capability_shapes.py`, including that the projection
      agrees with `VM_CAPABILITY_SCHEMA`.
      *Done 2026-10-01.* `price_vm_shape` validates the shape with `canonical_vm_shape` first. Suite passes (42).
- [x] 1.8 Widen `ReferenceAmountHook` in
      `kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py` to receive the
      buyer's pinned proposal, passed at its continuation call site. Update the hook test
      double in `kit/negotiation-runtime/tests/unit/test_runtime.py` and assert the pinned
      proposal reaches the hook.
      *Done 2026-10-01.* Suite passes; the test double asserts the pinned proposal arrives.
- [x] 1.9 VM selected-option reference. `extract_initial_price_from_order` in
      `domains/vms/listings/src/arkhai_vms_listings/pricing.py` takes the buyer's proposal
      and returns the amount rate of the option it selects — the settlement option matched
      by `option_id` for a settlement selection, the matched accepted escrow for an escrow
      proposal — as an `int`, or the `default_min_price` floor parsed exactly as a
      `Fraction` when that option has no rate; a float floor is refused. Matching reuses
      `market_policy.scalar_policies`' selection and escrow matchers. `_seller_reference_amount`
      in `domains/vms/negotiation/src/arkhai_vms_negotiation/storefront_round.py` takes the
      proposal, computes `floor(rate × seconds / 3600)` exactly, and is called with the
      round's latest buyer proposal; `seller_reference_amount` and the `reference_amount`
      hook in `domains/vms/storefront/src/market_storefront/negotiation_runtime.py` pass the
      pinned proposal.
      *Done 2026-10-01.* `_selected_option` in `storefront_round.py` reads the selected option; a proposal selecting nothing the listing offers (an escrow proposal without an escrow address, an unmatched selection) falls back to the first accepted escrow, so the round's guards refuse it for its own reason rather than for want of a floor.
- [x] 1.10 API-credit selected-option reference. `_reference_amount` in
      `domains/apicredits/storefront/src/apicredits_storefront/negotiation_runtime.py` takes
      the pinned proposal and prices the artifact it selects — a matched accepted escrow,
      which need not be the first, or a selected settlement option, falling to the floor
      when that artifact has no rate — through a shared `selected_settlement_artifact` in
      `kit/policy/src/market_policy/scalar_policies.py` that the VM reference uses too; the last step of
      `_seller_reference_amount` in
      `domains/apicredits/src/arkhai_apicredits/negotiation/storefront_round.py` and the
      floor parsing in `domains/apicredits/src/arkhai_apicredits/listings/pricing.py` become
      exact.
      *Done 2026-10-01; amended after implementation review.* The first pass passed only
      the settlement selection, so an escrow proposal priced against the first accepted
      escrow and a rateless selected option raised instead of using the floor. Both
      domains now read the selected artifact through `selected_settlement_artifact`
      (tests in `kit/policy/tests/unit/test_selection_scalar.py`); API-credit cases for a
      non-first escrow, a selected option, a rateless option, and the hook reading the
      whole pinned proposal are in `test_concept_modules.py`.
- [x] 1.11 Reference tests. `domains/vms/storefront/tests/unit/test_extract_initial_price.py`:
      a hosted option selected on a two-mechanism listing references the hosted rate; a
      hosted-only listing never uses the floor; a rateless selected option uses the floor;
      a 21-significant-digit rate over one year is exact; a float floor is refused. A
      hosted-selection negotiation in `domains/vms/storefront/tests/integration/test_listings_api.py`
      reports the hosted option's reference amount. `domains/apicredits/storefront/tests/unit/test_concept_modules.py`:
      the pinned selection reaches the reference, and a long amount is exact.
      *Done 2026-10-01; amended after implementation review.* The first pass replaced the
      integration case with unit cases, which `TESTING.md` does not allow for orchestration.
      `test_a_hosted_selection_negotiates_from_the_hosted_rate` in `test_listings_api.py`
      now drives `StorefrontClient.evaluate_negotiate` against a listing offering Alkahest
      at 9000 and a hosted option at 1500, and asserts a reference of 1500.

## 2. Family-rate resolution, validation, and diagnosis

Design: "The rate lives inside the capability it prices"; "Family rates resolve through
the existing tiers, one whole list per family"; "An unreadable rate holds the pool, and
the reason is visible"; "The dead `min_price` and `token` resolution is removed";
"Scope edges".

- [x] 2.1 Provisioning-side check: `validate_pricing_rates(policy_tags)` in
      `kit/resource-pools/src/market_resource_pools/hints.py`, exported from the package,
      checking every `rates` list under a family or a family key of `pricing` per the
      `resource-pool-management` delta, knowing no family name. Wire it beside
      `validate_asking_rates` in both validation sites of
      `kit/resource-pools/src/market_resource_pools/service.py` (the pool model check and
      the bulk import). Tests in `kit/resource-pools/tests/unit/test_hints.py` and a
      refused write through each surface in
      `kit/resource-pools/tests/integration/test_resource_pool_service.py`.
      *Done 2026-10-01.* Validator in `hints.py`, with unit tests in a new `kit/resource-pools/tests/unit/test_pricing_rates.py`. Suite passes (280); the provisioning service suite passes (670 and 281).
      *Amended after implementation review:* the provisioning service's API boundary is proven through `ProvisioningClient` in `provisioning/compute/service/tests/integration/test_pools_api.py` (`TestPricingRatesValidationThroughAdminApi`: a malformed rate refused with nothing stored, a valid rate list round-tripped).
- [x] 2.2 Rewrite `domains/vms/listings/src/arkhai_vms_listings/pricing_resolution.py`:
      `min_price` and `token` leave `GpuPricingFields`, `_FIELD_NAMES`, and
      `_VALID_HINT_FIELD`, and the module docstring is corrected. Family-rate resolution
      over `VM_PRICING_PROJECTION`: each family independently, a tier's list replacing
      lower tiers' whole, an empty list stopping fall-through, the GPU family per model.
      A tier value that cannot be read — malformed, an unpriced family, a non-time unit —
      makes the resolution unreadable, naming tier, family, and problem, and never falls
      through. Report retired `min_price`/`token` hint keys. Carried forward, with
      unreadable now holding rather than falling through.
      *Done 2026-10-01.* Rates under an unpriced family, and GPU rates not stated per model, are unreadable too.
- [x] 2.3 Configured defaults in
      `domains/vms/storefront/src/market_storefront/services/publication_terms.py`'s
      `pool_hint_resolution_settings`, with a case-preserving reader (GPU models are keys):
      drop `default_min_price`, `default_token_address`, and per-model `min_price`/`token`
      from resolution; read `[pricing.defaults.<family>].rates`. Extend
      `PoolHintResolutionSettings` in `reconciler.py`. Add `configured_family_rate_problems()`
      and a fail-fast startup step in `domains/vms/storefront/src/market_storefront/startup.py`
      that refuses to start on any, beside a non-fatal step reporting retired
      configuration keys. Carried forward, plus the fail-fast step.
      *Done 2026-10-01.* The fail-fast step is `configured_family_rates` in `startup.py`'s `_startup_tasks`; startup tests in a new `domains/vms/storefront/tests/unit/test_startup_family_rates.py`.
- [x] 2.4 Override terms. `VmPoolOverrideTerms` in
      `domains/vms/storefront/src/market_storefront/models/pool_override_models.py` loses
      `min_price` and `token` and gains a `pricing` term validated against
      `VM_PRICING_PROJECTION` at write. In `reconciler.py`, `VM_OVERRIDE_TERMS` loses them and
      gains `pricing`, and `vm_override_view` — which now also carries `asking_rates` —
      returns the retired keys a stored override still carries. Carried forward.
      *Done 2026-10-01.* Done.
- [x] 2.5 Derivation in `reconciler.py`'s `_projected_pool_rows`, beside the landed
      asking-rate resolution: `_tier` stops reading `min_price`/`token`; family rates
      resolve per GPU model; an unreadable resolution holds the pool and records
      `unreadable_family_rates`, as `unreadable_asking_rates` does; each candidate carries
      `family_rates` (projection path only). The derivation report gains
      `unreadable_family_rates`, `retired_pricing_keys`, and `families_without_rates`
      (per pool, shape digest, and clause asset: families the shape names with no rate in
      that asset), each in `as_dict` and logged once per change. The local-table path
      stops selecting and carrying `min_price` and `token` and resolves no family rates.
      *Done 2026-10-01.* Done; unreadable rates hold the pool before any listing is derived from it.
- [x] 2.6 Narrow `_per_model_legacy_conflicts` in
      `domains/vms/storefront/src/market_storefront/publication_migration.py` to model
      tables stating `min_price` or `token`. Carried forward.
      *Done 2026-10-01.* Done.
- [x] 2.7 Configuration surfaces: `domains/vms/storefront/src/market_storefront/settings.toml`
      (floor documented in base units per hour as decimal text; a family-rates example;
      `default_token_address` removed); `default_token_address` removed from
      `domains/vms/storefront/storefront.alice.toml`, `storefront.bob.toml`,
      `config.stripe-fiat-ed25519.toml`, `e2e-tests/config/hosted-storefront.toml`, and
      `helm/fixtures/fiat-ed25519-values.yaml`; `helm/values.schema.json` and
      `helm/charts/storefront/values.schema.json` describe `default_token_address` as
      retired and `default_min_price` as decimal text; the generated template in
      `domains/vms/storefront/src/market_storefront/groups/config.py`. Carried forward.
      *Done 2026-10-01.* Done; `settings.toml` states the not-charged and free-listing rules.
- [x] 2.8 Tests. `domains/vms/storefront/tests/unit/test_pricing_resolution.py` (tiers,
      whole lists, per-family independence, GPU per model, unreadable values in each tier
      including an unpriced family and a non-time unit, retired keys);
      `domains/vms/storefront/tests/unit/test_reconciler.py` (`family_rates` on candidates,
      an unreadable hint holding the pool rather than falling to a configured default,
      `families_without_rates` and retired keys in the report, the local-table path);
      `domains/vms/storefront/tests/unit/test_vm_pool_override_contribution.py` and
      `domains/vms/storefront/tests/integration/test_pool_overrides_api.py` (a `pricing` term
      validated; `min_price` refused at write; a stored override with retired terms still
      applies and is reported); `domains/vms/storefront/tests/unit/test_publication_migration.py`;
      a startup test that a malformed configured family rate stops startup. Carried forward
      where the rule is unchanged; the `min_price` cases in `test_reconciler.py` exercise the
      same tiers through `max_duration_seconds` and `settlements`.
      *Done 2026-10-01.* Done. `test_reconciler_projection.py`'s landed asking-rate test, which configured `min_price`, now configures settlements and family rates and asserts neither becomes an asking rate.

## 3. Shape-priced publication

Design: "A listing is either flat-priced or shape-priced, and is never free"; "The
recorded rate structure is everything that could price a revised shape"; "Settlement-option
identity follows the composed rate"; "The rate structure is a storefront-served term of
sale, not a registry field".

- [x] 3.1 `compose_clause_rates` in `publication_terms.py`, taking compiled clauses, the
      listing shape, its `family_rates`, and an injectable settlement registry (defaulting
      to the storefront's): flat when no family resolves rates; otherwise each
      scalar-negotiating clause's rate composed through `price_vm_shape` in its asset,
      non-scalar clauses passed through rateless. Refuse, naming the asset, a composed rate
      of zero; refuse a shape-priced clause stating its own rate. Return the clauses and the
      rate structure: every resolved family's rates for the listing's model, including
      families the shape omits.
      *Done 2026-10-01.* Done.
- [x] 3.2 Call it from `VmPublicationCycle._create_request` in
      `domains/vms/storefront/src/market_storefront/services/publication_loop.py` before
      compilation completes the request, so a refusal takes the existing refuse path; carry
      the structure on `DerivedVmListing.rate_structure`
      (`domains/vms/storefront/src/market_storefront/services/listing_service.py`) into
      `persist_derived_listing` and `_reconcile_existing`'s comparison and `update_listing`.
      Carried forward.
      *Done 2026-10-01.* Done.
- [x] 3.3 Persist it on the generic listing: migration `20261001_001_listing_rate_structure`
      in `core/storefront/src/core_storefront/sqlite_migrations.py`, an additive entry in the
      versioned chain; the column through `write_listing_update` (written whenever passed, so
      `None` clears it), `_execute_listing_upsert`, `upsert_listing`,
      `upsert_listing_with_binding`, `update_listing`, `load_listing`, and `list_listings` in
      `core/storefront/src/core_storefront/sqlite_client.py`; `rate_structure` on
      `ListingResponse` in `core/storefront/src/core_storefront/models/listing_models.py`.
      Carried forward.
      *Done 2026-10-01.* Done; core storefront suite passes (182).
- [x] 3.4 `rate_structure` in `TERM_LISTING_FIELDS` in
      `domains/vms/listings/src/arkhai_vms_listings/listing_comparison.py`, beside the landed
      `asking_rate` in `TERM_RESOURCE_FIELDS`. Confirm
      `core/storefront/src/core_storefront/registry_publication.py` builds the registry request
      without it.
      *Done 2026-10-01.* Done; `registry_publication.py` builds the request field by field, unchanged.
- [x] 3.5 Tests. `domains/vms/storefront/tests/unit/test_publication_terms_composition.py`:
      unchanged flat clauses; the worked example's `174.4`, and its base units; an unrated
      family not charged; a would-be-free asset refused; a non-scalar clause passed through;
      a shape-priced clause with its own rate refused; the structure recording an omitted
      family. `test_listing_comparison.py`: a structure change is a term change, including
      one for an omitted family. `core/storefront/tests/unit/test_rate_structure_column.py`.
      `domains/vms/storefront/tests/integration/test_publication_loop.py`: composed rates
      published with the structure recorded and absent from registry requests; an in-place
      refresh on a rate change, with new option identities and the same listing; a
      would-be-free listing refused and never posted.
      *Done 2026-10-01.* Done. VM storefront: 1149 unit and 270 integration tests pass.
      *Amended after implementation review:* `test_rate_structure_column.py` is in `core/storefront/tests/integration/`, since it uses real SQLite. The reconciler's database-backed cases moved from `domains/vms/storefront/tests/unit/test_reconciler.py` to `tests/integration/test_reconciler_derivation.py`, as the campaign index recorded they would when the file next changed; shared helpers and the schema fixture are in `tests/_reconciler_cases.py`, which `test_reconciler_projection.py` also imports.
- [x] 3.6 End-to-end Stage 07 in
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`: an override stating
      family rates and rateless clauses refreshes the listing in place at the composed rate,
      seen at the registry, with the structure served only by the storefront; deleting the
      override restores the flat rate. Carried forward; its rates name every family the
      shape names, so the expected 11 tokens an hour is unchanged.
      *Done 2026-10-01.* Unchanged from the earlier implementation; run evidence is 7.9's.

### Superseded planning-time entries

The 2026-08-06 plan's 1.1–1.6, 2.1–2.4 (with 2.2a), and 3.1–3.3 are replaced by the
tasks above. Two were changed in substance, not only in wording: 3.2, "interpret an
existing single-rate listing as a primary-dimension-only structure", is superseded by
the flat-rate reading (see `design.md`, "Compatibility: the flat rate is never
reinterpreted"); and 2.2a's override tier is the `pricing` term of 2.4.

## 4. Negotiation reinterpretation

Owned by [`negotiation-driven-capacity-resize`](../negotiation-driven-capacity-resize/tasks.md)
Section 2b: the multiplier and the revised-terms field are one deployment boundary.

## 5. Seller feasibility guard

Moved (design review, 2026-10-01): the quantitative check of a requested shape is
`capacity-shape-envelope`'s admissibility predicate, and the categorical check, the
ordering ahead of pricing, and the "Seller feasibility precedes pricing" requirement
are `negotiation-driven-capacity-resize` task 2.4's. The number is kept.

## 6. Validation

- [x] 6.1 Focused suites, each through its project's Make target:
      `make -C kit/capability-pricing test`, `make -C kit/settlement-runtime test`,
      `make -C kit/alkahest test`, `make -C kit/hosted-settlement test`,
      `make -C kit/negotiation-runtime test`, `make -C kit/resource-pools test`,
      `make -C provisioning/compute/service test` (pool writes refusing malformed rate
      lists), `make -C core/storefront test`, `make -C domains/vms/domain test`, and
      `make -C domains/vms/storefront test` (unit and integration);
      `make -C domains/bare_metal/storefront test` and `make -C domains/apicredits test`,
      because the generic listing table gains a column and the API-credit reference
      changes. `make -C core typecheck`. Disclose any suite not run.
      *Done 2026-10-01, with unrun suites disclosed:* passed — `kit/capability-pricing` (22), `kit/settlement-runtime` (109), `kit/alkahest` (182), `kit/hosted-settlement` (189), `kit/negotiation-runtime` (8), `kit/resource-pools` (280), `provisioning/compute/service` (670, 281), `domains/vms/domain` (42), `core/storefront` (182), `domains/vms/storefront` unit (1149) and integration (270), `domains/bare_metal/storefront` (215), and the API-credit Python suites (87 and the rest). Not run here, for environment reasons: the VM storefront's two `test_alkahest.py` cases (no local chain runtime binary) and the API-credit Rust middleware suite (no `cargo`). The VM storefront's environment was built from its existing lock plus the new kit's wheel, because relocking it needs `torch` metadata this environment cannot fetch; see 7.8. `make -C core typecheck` reports one error, in `core/src/market_core/query_dsl.py`, a file this change does not touch.
- [x] 6.2 Confirm no consumer reconstructs a total from individual family rates: a
      search for rate-times-quantity arithmetic outside the aggregator finds none.
      *Done 2026-10-01.* Done: no rate-times-quantity arithmetic outside `market_capability_pricing`.
- [x] 6.3 Confirm no amount on the pricing path passes through `float` or
      context-limited `Decimal` arithmetic: a search of the files this change touches
      for `float(`, `Decimal(` arithmetic, and `INTEGER` amount columns.
      *Done 2026-10-01.* Done: no `float(` or context-limited `Decimal(` arithmetic in any touched production file.
- [x] 6.4 Run `openspec validate --all --strict` against the baseline current at
      implementation time; report only new failures as this change's.
      *Done 2026-10-01:* the same twelve pre-existing change failures as the unmodified tree.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`. Promotion happens after code
review.

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Direct-read `pricing_resolution.py`'s module docstring, the
      `PoolHintResolutionSettings` docstring, `settings.toml`'s pricing comments, and
      `_validate_vm_opening`'s surroundings: each described one price per GPU model
      or the retired keys. (The round-0 guard's retirement is
      `negotiation-driven-capacity-resize`'s.)
      *Done 2026-10-01.* Done: `make check-comment-hygiene` passes; added comments read directly.
- [x] 7.2 **Import placement.** Review every import this change adds or touches and
      move it to module level where safe, attempting the move and running the suite
      before keeping any local import. `pricing_resolution.py`'s existing local import
      of `market_resource_pools.hints` and `reconciler.py`'s of
      `market_pool_overrides` are deliberate and stay unless the section changes
      their reason.
      *Done 2026-10-01.* Done: added imports are module level, including the moved test imports.
- [x] 7.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules: normative behavior in the three
      spec deltas, rationale in `storefront-publication/architecture.md`, the
      cross-system pricing account in `ARCHITECTURE.md`, operator configuration in
      `DEPLOYMENT_AND_CONFIG.md`, and the superseded compatibility reading only in
      `design.md`.
      *Done 2026-10-01:* each accepted decision maps to a destination in the promotion record; the superseded readings and review dispositions stay in `design.md`.
- [x] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work (the findings
      `design.md` records as not changed), and promotion destinations.
      *Done 2026-10-01:* completed-task notes give final behavior, deviations, and evidence; alternatives stay in `design.md`.
- [x] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md`'s Goal 2, rewrite
      the current-state statement that commercial resolution produces a single price
      per GPU model and that rates scale by duration only, and remove this change's
      gap row. The statement that negotiation has one degree of freedom stays until
      `negotiation-driven-capacity-resize` lands. Name the update in the promotion
      record.
      *Done 2026-10-01.* Done: Goal 2's current state describes per-family pricing, the not-charged and free-listing rules, holding on unreadable rates, the recorded structure, and the selected-option reference; this change's gap row is removed, its remaining seller check being resize's; Goal 7's cross-reference no longer calls the work in design.
- [x] 7.6 **Campaign index currency.** Update this change's row and Goal 2's
      dependency graph in `openspec/changes/README.md` to its state at completion, and remove the unowned-work entries this
      change resolved. Name the update in the promotion record.
      *Done 2026-10-01.* Done: this change's row records Sections 1–3 implemented and pending review, end-to-end evidence, and promotion.
- [x] 7.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=capacity-shape-pricing` and resolve every match.
      An unresolvable citation, or one whose target is a tombstone, is a blocking
      defect under `AGENTS.md`'s cross-reference rule.
      *Done 2026-10-01.* Done: passes.
- [x] 7.8 **Packaging.** Run `make lock` for the new distribution and its dependents,
      then `make check-packaging`, and resolve every failure it reports:
      `arkhai-kit-capability-pricing` is a new distribution and `arkhai-vms` depends on
      it, so every lock downstream of `arkhai-vms` changes; `kit/settlement-runtime` gains
      an export.
      *Done 2026-10-01 by the maintainer:* `make lock` regenerated seven locks and
      `make check-packaging` passes every check. (The first note here described the
      implementer's local tree, whose relocked files were not in the fileset; this
      environment cannot relock the VM storefront, buyer, or `kit/policy`, because their
      `rl` extra resolves `torch` from an index that refuses it.)
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record
      the run, its result, and the scenarios exercising this change: 3.6's
      shape-priced scenario and the existing VM full-deal scenarios, which prove
      flat-priced listings settle unchanged. If the pipeline cannot run for a reason
      unrelated to this change, record that as an explicit blocker naming the cause and
      its owning change, and treat the validations it gates as unrun.
      *Run 2026-10-01 by the maintainer, before the implementation-review fixes:* VM e2e 128 passed, 2 skipped; bare-metal 11
      passed. Stage 07 (`test_07a`, `test_07b`) passed, and the full-deal scenarios settle
      flat-priced listings unchanged. The two skips are `test_multi_registry.py`'s
      negotiate-with-alice stages, statically skipped and unrelated. The run predates the
      implementation-review fixes; the task closes when a run after them passes.
- [ ] 7.10 **Promotion.** Complete the design-promotion record below, mapping every
      accepted decision to its exact permanent heading, and synchronize the three spec
      deltas into `openspec/specs/storefront-publication/spec.md`,
      `openspec/specs/negotiation-protocol/spec.md`, and
      `openspec/specs/resource-pool-management/spec.md`. Write the rationale into
      `openspec/specs/storefront-publication/architecture.md`, the pricing account into
      `docs/development/ARCHITECTURE.md`'s "Discovery and negotiation", and the
      operator configuration into `docs/development/DEPLOYMENT_AND_CONFIG.md`'s
      "Storefront listing shapes and pool overrides" and the terms-of-sale paragraph
      under "Combined compute-family storefront".
      *Pending code review.*

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Per-family rates in one nesting across the three tiers; an explicit pricing projection; shape-priced when any family resolves rates; unrated families not charged; a free listing refused | `openspec/specs/storefront-publication/spec.md` — "Shape-resolvable commercial rates" |
| An unreadable family rate holds its pool and is reported; a malformed configured default stops startup | `openspec/specs/storefront-publication/spec.md` — "An unreadable family rate holds its pool" |
| Price aggregation is replaceable, exact, domain-selected, and no consumer reconstructs a total | `openspec/specs/storefront-publication/spec.md` — "Price aggregation is replaceable" |
| The recorded structure holds every resolved family; option identity follows the composed rate | `openspec/specs/storefront-publication/spec.md` — "A shape-priced listing records the rates that could price a revised shape" |
| A clause rate is stated or composed and converts to base units exactly or is refused | `openspec/specs/storefront-publication/spec.md` — "Publication pricing is explicit per settlement clause" |
| The dead `min_price`/`token` resolution is retired; retired keys are reported; the floor is the configured default alone | `openspec/specs/storefront-publication/spec.md` — "Domain-owned publication and hold hints" |
| The seller's reference amount is the selected option's rate | `openspec/specs/negotiation-protocol/spec.md` — "The seller's reference amount is the selected option's rate" |
| Reference amounts and the floor are exact | `openspec/specs/negotiation-protocol/spec.md` — "Uint256-safe negotiation values" |
| Pool writes check pricing rate-list structure | `openspec/specs/resource-pool-management/spec.md` — "Pricing rate-list hint validation" |
| `kit/capability-pricing` is a foundation kit over the shape vocabulary | `docs/development/ARCHITECTURE.md`, "Kit layers" |
| How a listing is priced and what a seller negotiates from | `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" |
| Why rates live inside families; why the flat rate is never reinterpreted; why `RateValue` was not widened; why pricing is its own kit; why the structure is storefront-served | `openspec/specs/storefront-publication/architecture.md` |
| Operator-facing family-rate configuration, override terms, and the refused fractional floor | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront listing shapes and pool overrides" and "Combined compute-family storefront" |
| Goal 2's current state | `docs/development/ROADMAP.md`, Goal 2 |
| This change's status and Goal 2's dependency graph | `openspec/changes/README.md`, Goal 2 |
| The superseded primary-dimension compatibility reading; the review dispositions | This change's `design.md` only |
