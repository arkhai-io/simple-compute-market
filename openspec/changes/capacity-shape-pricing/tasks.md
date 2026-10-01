# Implementation Tasks

Sections sized to land in roughly a day each. Every section is additive and deployable
alone. Section 4 is `negotiation-driven-capacity-resize`'s; its number is kept.

*Re-planned 2026-10-01* against the revised `design.md`. No task had been started,
so Sections 1–3 are rewritten rather than amended; the planning-time entries they
replace are summarized under "Superseded planning-time entries" at the end of this
section list. Section 5 is outside this implementation round and opens with decision
gate 5.0. Every amount in every task is a Python `int`, exact decimal text, or a
`Fraction`; none passes through `float` or through `Decimal` arithmetic under a
precision context, and none is stored in a fixed-width column.

## 1. Exact amounts and the aggregator

Design: "Every amount is exact, and nothing rounds silently"; "Price aggregation is
a replaceable interface in `kit/capability-shape`"; "`RateValue.per` stays a time
unit".

- [ ] 1.1 Re-verify `design.md`'s Context against the tree: the mechanism scalers'
      context-limited multiplication, `_seller_reference_amount`'s `Decimal` path,
      `extract_initial_price_from_order`'s `float()`, and that `RateValue` and
      `PER_UNIT_SECONDS` are unchanged.
- [ ] 1.2 Add the exact conversion helper beside clause validation in
      `kit/settlement-runtime/src/market_settlement_runtime/publication.py`,
      exported from the package `__init__.py`: decimal rate text and an asset
      exponent to integer base units, by integer arithmetic on the digits; refuses a
      non-whole result, a non-positive result, and a result above `2**256 - 1`, each
      with a distinct message. Tests in
      `kit/settlement-runtime/tests/unit/test_clauses.py`.
- [ ] 1.3 Use the helper in the Alkahest scaler,
      `kit/alkahest/src/market_alkahest/settlement_config.py` (the clause-rate block
      building `rates`), keeping its existing messages' meaning. Tests in
      `kit/alkahest/tests/unit/test_settlement_config.py`: an 18-decimal rate with
      more than 28 significant digits that is not whole is refused; one that is whole
      converts exactly; the uint256 bound refuses.
- [ ] 1.4 Use the helper in the hosted scaler `_stripe_rate_minor_units`,
      `kit/hosted-settlement/src/market_hosted_settlement/settlement_config.py`, with
      the same cases in `kit/hosted-settlement/tests/unit/test_settlement_config.py`.
- [ ] 1.5 Make the seller's reference amount exact.
      `domains/vms/listings/src/arkhai_vms_listings/pricing.py`'s
      `extract_initial_price_from_order` returns the advertised base-unit rate as an
      `int`, or the `default_min_price` floor parsed exactly from its decimal text as
      a `Fraction` (positive, no exponent, never `float`).
      `domains/vms/negotiation/src/arkhai_vms_negotiation/storefront_round.py`'s
      `_seller_reference_amount` computes `floor(rate × seconds / 3600)` exactly and
      returns an `int`. Confirm `negotiation_runtime.seller_reference_amount` needs
      no change. Tests: `domains/vms/storefront/tests/unit/test_extract_initial_price.py`
      (floor text with many digits; float-typed configuration refused) and a
      reference-amount case for a 21-significant-digit rate over one year, in the
      same file.
- [ ] 1.6 Add `kit/capability-shape/src/market_capability_shape/pricing.py`, exported
      from the package: a family-rate value (decimal text and a time unit), an exact
      price result (decimal text and unit), an unpriceable result naming every family
      without a rate, the aggregator protocol (shape, one asset's family rates,
      schema → price or unpriceable), and the linear implementation. The linear
      implementation prices each family the shape names by its single quantity
      field and ignores families the shape omits; it refuses a priced family whose
      schema gives it no quantity field or several, a zero or malformed rate, a
      binary float anywhere, and rates naming different units. Standard library
      only.
- [ ] 1.7 Tests in `kit/capability-shape/tests/unit/test_pricing.py`: the design's
      worked example yields `174.4`; the same rates price a different shape; a missing
      family is unpriceable and every missing family is named; an omitted family is
      not priced; a 40-significant-digit result is exact; zero, negative, float, and
      exponent rates are refused; mixed units are refused. Confirm
      `kit/capability-shape/tests/unit/test_import_boundary.py` still holds.

## 2. Family-rate resolution and the retired keys

Design: "The rate lives inside the capability it prices"; "Family rates resolve
through the existing tiers, one whole list per family"; "The dead `min_price` and
`token` resolution is removed"; "Scope edges found during planning".

- [ ] 2.1 Rewrite `domains/vms/listings/src/arkhai_vms_listings/pricing_resolution.py`:
      remove `min_price` and `token` from `GpuPricingFields`, `_FIELD_NAMES`, and
      `_VALID_HINT_FIELD`, and correct the module docstring. Add family-rate
      resolution: parse a family's `rates` list (each entry `asset`, positive decimal
      text `rate`, time-unit `per`; one entry per asset), resolve each family
      independently with a tier's list replacing lower tiers' whole, the GPU family
      by model. A malformed hint list is treated as absent and returned as a problem.
      Report a hint's retired `min_price`/`token` keys.
- [ ] 2.2 Read the configured defaults in
      `domains/vms/storefront/src/market_storefront/services/publication_terms.py`'s
      `pool_hint_resolution_settings`: drop `default_min_price` and
      `default_token_address` from the flat default and `min_price`/`token` from the
      per-model defaults; add `[pricing.defaults.<family>].rates`, the GPU family per
      model. Extend `PoolHintResolutionSettings` in
      `domains/vms/listings/src/arkhai_vms_listings/reconciler.py` to carry them.
- [ ] 2.3 Override terms. In
      `domains/vms/storefront/src/market_storefront/models/pool_override_models.py`,
      remove `min_price` and `token` from `VmPoolOverrideTerms` and add a typed
      `pricing` term in the hint's nesting, refusing at write a family
      `COMPUTE_CAPABILITY_SCHEMA` does not define, a non-GPU family keyed by model, and
      a malformed rate. In `reconciler.py`, `VM_OVERRIDE_TERMS` loses `min_price` and
      `token` and gains `pricing`, and `vm_override_view` also returns the retired keys
      a stored override still carries.
- [ ] 2.4 Derivation in `reconciler.py`. `_projected_pool_rows`: the storefront
      tier's `_tier` no longer reads `min_price`/`token` from the override or the
      legacy row; resolve family rates per GPU model beside `pricing_by_model`; carry
      them on each candidate as `family_rates`. `_SiteDerivationReport` gains
      `retired_pricing_keys` and `malformed_family_rates`, per pool, in `as_dict`.
      Local-table path (`_pool_rows_from_local_tables` and the row dictionaries it
      builds): stop selecting and carrying `min_price` and `token`, and never
      resolve family rates. `available_compute_slices` drops the `min_price` and
      `token` candidate keys.
- [ ] 2.5 Narrow `_per_model_legacy_conflicts` in
      `domains/vms/storefront/src/market_storefront/publication_migration.py` to model
      tables stating `min_price` or `token`.
- [ ] 2.6 Configuration surfaces.
      `domains/vms/storefront/src/market_storefront/settings.toml`: remove
      `default_token_address` and the per-model `min_price`/`token` example; document
      `default_min_price` as the hidden-reserve floor in base units per hour; add a
      commented family-rates example. Remove `default_token_address` from
      `domains/vms/storefront/storefront.alice.toml`, `storefront.bob.toml`,
      `config.stripe-fiat-ed25519.toml`, `e2e-tests/config/hosted-storefront.toml`, and
      `helm/fixtures/fiat-ed25519-values.yaml`. In `helm/values.schema.json` and
      `helm/charts/storefront/values.schema.json`, keep accepting
      `default_token_address` with a description marking it retired and unread.
      Update the `pricing.default_min_price` help text and example comment in
      `domains/vms/storefront/src/market_storefront/groups/config.py`.
- [ ] 2.7 Report retired configuration keys once at startup from
      `domains/vms/storefront/src/market_storefront/server.py`'s
      `_run_startup_tasks`.
- [ ] 2.8 Tests.
      `domains/vms/storefront/tests/unit/test_pricing_resolution.py`: replace the
      `min_price` cases with family-rate tiers — whole-list replacement, per-family
      independence, GPU per model, malformed hint absent and reported, retired keys
      ignored and reported.
      `domains/vms/storefront/tests/unit/test_reconciler.py`: candidates carry
      `family_rates` on the projection path and none on the local-table path; no
      candidate carries `min_price` or `token`; retired and malformed keys reach the
      derivation report.
      `domains/vms/storefront/tests/unit/test_vm_pool_override_contribution.py` and
      `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`: a
      `pricing` term is accepted and validated; a write stating `min_price` is
      refused; a stored override carrying `min_price` still applies its other terms
      and is reported.
      `domains/vms/storefront/tests/unit/test_publication_migration.py`: a model table
      with only `rates` or `settlements` is not a conflict; one stating `min_price`
      is.

## 3. Shape-priced publication

Design: "A listing is either flat-priced or shape-priced, decided by its GPU family";
"Compatibility: the flat rate is never reinterpreted"; "The rate structure is a
storefront-served term of sale, not a registry field".

- [ ] 3.1 Add clause-rate composition to `publication_terms.py`: from a candidate's
      raw clauses, listing shape, and `family_rates`, decide the mode and either
      return the clauses unchanged (flat) or supply each scalar-negotiating clause's
      `rate` and `per` through the aggregator in that clause's asset, passing
      non-scalar clauses through rateless. Scalar participation is read from the
      mechanism registration (`negotiates_scalar_amount`) through
      `build_storefront_settlement_registry`. Refuse, naming family and asset: a
      shape-priced clause stating its own rate; an unpriceable family; non-GPU family
      rates without GPU rates. Return the listing's rate structure (each family the
      shape names to its resolved rates) or `None`.
- [ ] 3.2 Call it from `VmPublicationCycle._create_request` in
      `domains/vms/storefront/src/market_storefront/services/publication_loop.py`
      before `compile_publication_clauses`, so a refusal takes the existing
      `_build_payload` refuse path and is recorded in the cycle report; put the rate
      structure on the request.
- [ ] 3.3 Persist the rate structure on the generic listing record: a nullable
      `rate_structure TEXT` column in `core/storefront/src/core_storefront/sqlite_client.py`
      (`CREATE TABLE listings`, the column-adding init step, `_execute_listing_upsert`,
      `upsert_listing`, `upsert_listing_with_binding`, `update_listing`, and the
      listing load and list readers), added for existing databases by a migration in
      `core/storefront/src/core_storefront/sqlite_migrations.py` that follows the
      conventions `add-database-migration-commands` names if it has landed by then.
      `rate_structure: dict | None` on `core/storefront/src/core_storefront/models/listing_models.py`'s
      `CreateListingRequest` and `ListingResponse`.
- [ ] 3.4 Carry it through the VM listing: `rate_structure` on
      `domains/vms/listings/src/arkhai_vms_listings/models.py`'s `Listing`; the derived
      listing and `persist_derived_listing` in
      `domains/vms/storefront/src/market_storefront/services/listing_service.py`;
      `TERM_LISTING_FIELDS` in
      `domains/vms/listings/src/arkhai_vms_listings/listing_comparison.py`, so a change
      refreshes in place; and `update_listing` in `publication_loop.py`'s
      `_reconcile_existing`. Confirm `core/storefront/src/core_storefront/registry_publication.py`
      builds the registry request without it.
- [ ] 3.5 Tests. A new
      `domains/vms/storefront/tests/unit/test_publication_terms_composition.py`:
      a configuration stating no family rates yields clauses, settlement options, and
      `option_id`s byte-identical to today's; the worked example composes `174.4` and
      the Alkahest option carries `174400000000000000000`; each refusal; a
      contact-exchange clause passes through rateless; an omitted family is not
      priced. `domains/vms/storefront/tests/unit/test_listing_comparison.py`: a
      changed rate structure is `terms_differ`, never identity.
      `core/storefront/tests/unit/test_publication_runner.py` or a new
      `core/storefront/tests/unit/test_rate_structure_column.py`: the column is added to
      an existing database, round-trips JSON, and stays null for other domains.
      `domains/vms/storefront/tests/integration/test_reconciler_projection.py`: an
      override stating family rates publishes composed rates and records the
      structure. `domains/vms/storefront/tests/integration/test_listings_api.py`: the
      listing read returns the structure; the registry request carries none.
- [ ] 3.6 End-to-end scenario in
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`: a site-scoped
      override stating GPU and CPU rates publishes options whose rates are the
      composed values at the registry, while the scenario's flat-priced pools keep
      their configured rate.

### Superseded planning-time entries

The 2026-08-06 plan's 1.1–1.6, 2.1–2.4 (with 2.2a), and 3.1–3.3 are replaced by the
tasks above. Two were changed in substance, not only in wording: 3.2, "interpret an
existing single-rate listing as a primary-dimension-only structure", is superseded
by the flat-rate reading (see `design.md`, "Compatibility: the flat rate is never
reinterpreted"); and 2.2a's override tier is the `pricing` term of 2.3.

## 4. Negotiation reinterpretation

Owned by [`negotiation-driven-capacity-resize`](../negotiation-driven-capacity-resize/tasks.md)
Section 2b: the multiplier and the revised-terms field are one deployment boundary.

## 5. Seller feasibility guard

- [ ] 5.0 **Decision gate.** Before any other Section 5 task starts, decide whether
      Section 5 and its `negotiation-protocol` "Seller feasibility precedes pricing"
      delta move into their own change depending on `capacity-shape-envelope`, and
      record the decision and its reasoning in `design.md`. Section 5 touches the
      negotiation path rather than pricing and publication, its quantitative check
      overlaps the envelope's admissibility, and it has no live caller until
      `negotiation-driven-capacity-resize` §2.
- [ ] 5.1 Extend `has_matching_inventory_guard` from `region`/`gpu_model` equality to a
      quantitative check across every dimension the seller constrains.
      *Amended 2026-09-23:* `unbacked-listing-publication` makes the guard recheck
      every published source-derived field — categorical and quantitative — against
      the listing's own source. What remains here is checking a *buyer-requested*
      shape, once shapes are negotiable, rather than the listing's advertised one.
      Implement the predicate here, taking a requested shape and the seller's
      constraints, and wire it into the VM `evaluate_round` composition in
      `negotiation_runtime.py` ahead of pricing. Until a round can carry a shape the
      requested shape is the listing's own and the predicate is exercised by unit
      tests only.
- [ ] 5.2 Order the guard before pricing inside the VM `evaluate_round` composition,
      so a shape the seller will not serve is never quoted.
- [ ] 5.3 Focused tests: quantitative constraint exceeded declines without a quote;
      categorical mismatch declines as today.

## 6. Validation

- [ ] 6.1 Focused suites, each through its project's Make target:
      `make -C kit/capability-shape test`, `make -C kit/settlement-runtime test`,
      `make -C kit/alkahest test`, `make -C kit/hosted-settlement test`,
      `make -C core/storefront test`, and `make -C domains/vms/storefront test`
      (unit and integration). `make -C domains/bare_metal/storefront test` and
      `make -C domains/apicredits test`, because the generic listing table gains a
      column. `make -C core typecheck`. Disclose any
      suite not run.
- [ ] 6.2 Confirm no consumer reconstructs a total from individual family rates: a
      search for rate-times-quantity arithmetic outside the aggregator finds none.
- [ ] 6.3 Confirm no amount on the pricing path passes through `float` or
      context-limited `Decimal` arithmetic: a search of the files this change touches
      for `float(`, `Decimal(` arithmetic, and `INTEGER` amount columns.
- [ ] 6.4 Run `openspec validate --all --strict` against the baseline current at
      implementation time; report only new failures as this change's.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`. Promotion happens after code
review.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Direct-read `pricing_resolution.py`'s module docstring, the
      `PoolHintResolutionSettings` docstring, `settings.toml`'s pricing comments, and
      `_validate_vm_opening`'s surroundings: each described one price per GPU model
      or the retired keys. (The round-0 guard's retirement is
      `negotiation-driven-capacity-resize`'s.)
- [ ] 7.2 **Import placement.** Review every import this change adds or touches and
      move it to module level where safe, attempting the move and running the suite
      before keeping any local import. `pricing_resolution.py`'s existing local import
      of `market_resource_pools.hints` and `reconciler.py`'s of
      `market_pool_overrides` are deliberate and stay unless the section changes
      their reason.
- [ ] 7.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules: normative behavior in the two
      spec deltas, rationale in `storefront-publication/architecture.md`, the
      cross-system pricing account in `ARCHITECTURE.md`, operator configuration in
      `DEPLOYMENT_AND_CONFIG.md`, and the superseded compatibility reading only in
      `design.md`.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work (Section 5, and the
      findings `design.md` records as not changed), and promotion destinations.
- [ ] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md`'s Goal 2, rewrite
      the current-state statement that commercial resolution produces a single price
      per GPU model and that rates scale by duration only, and remove this change's
      gap row if Section 5 has moved out (gate 5.0); otherwise narrow the row to
      Section 5. The statement that negotiation has one degree of freedom stays until
      `negotiation-driven-capacity-resize` lands. Name the update in the promotion
      record.
- [ ] 7.6 **Campaign index currency.** Update this change's row and Goal 2's
      dependency graph in `openspec/changes/README.md` to its state at completion,
      including any change gate 5.0 creates, and remove the unowned-work entries this
      change resolved. Name the update in the promotion record.
- [ ] 7.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=capacity-shape-pricing` and resolve every match.
      An unresolvable citation, or one whose target is a tombstone, is a blocking
      defect under `AGENTS.md`'s cross-reference rule.
- [ ] 7.8 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports. `kit/settlement-runtime` and `kit/capability-shape` gain exports their
      dependents' locks must still resolve.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record
      the run, its result, and the scenarios exercising this change: 3.6's
      shape-priced scenario and the existing VM full-deal scenarios, which prove
      flat-priced listings settle unchanged. If the pipeline cannot run for a reason
      unrelated to this change, record that as an explicit blocker naming the cause and
      its owning change, and treat the validations it gates as unrun.
- [ ] 7.10 **Promotion.** Complete the design-promotion record below, mapping every
      accepted decision to its exact permanent heading, and synchronize the two spec
      deltas into `openspec/specs/storefront-publication/spec.md` and
      `openspec/specs/negotiation-protocol/spec.md`. Write the rationale into
      `openspec/specs/storefront-publication/architecture.md`, the pricing account into
      `docs/development/ARCHITECTURE.md`'s "Discovery and negotiation", and the
      operator configuration into `docs/development/DEPLOYMENT_AND_CONFIG.md`'s
      "Storefront listing shapes and pool overrides" and the terms-of-sale paragraph
      under "Combined compute-family storefront".

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Per-family rates in one nesting across the three tiers; a listing is shape-priced or flat-priced by its GPU family; unpriceable, mixed, and conflicting inputs refuse the candidate | `openspec/specs/storefront-publication/spec.md` — "Shape-resolvable commercial rates" |
| Price aggregation is replaceable, exact, selected by the domain's composition, and no consumer reconstructs a total | `openspec/specs/storefront-publication/spec.md` — "Price aggregation is replaceable" |
| A shape-priced listing's rates are a storefront term of sale; the registry carries only composed option rates | `openspec/specs/storefront-publication/spec.md` — "A shape-priced listing's rates are a storefront term of sale" |
| A clause rate is stated or composed and converts to base units exactly or is refused | `openspec/specs/storefront-publication/spec.md` — "Publication pricing is explicit per settlement clause" |
| The dead `min_price`/`token` resolution is retired; retired keys are tolerated and reported; the floor is the configured default alone | `openspec/specs/storefront-publication/spec.md` — "Domain-owned publication and hold hints" |
| The seller's reference amount and floor are exact | `openspec/specs/negotiation-protocol/spec.md` — "Uint256-safe negotiation values" |
| Seller feasibility is evaluated quantitatively and precedes pricing (Section 5) | `openspec/specs/negotiation-protocol/spec.md` — "Seller feasibility precedes pricing", subject to gate 5.0 |
| How a listing is priced, and that the override tier is the site-scoped pool override | `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" |
| Why rates live inside families; why the flat rate is never reinterpreted; why `RateValue` was not widened; why the structure is storefront-served | `openspec/specs/storefront-publication/architecture.md` |
| Operator-facing family-rate configuration and override terms | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront listing shapes and pool overrides" |
| Goal 2's current state: per-family pricing exists; negotiation still has one degree of freedom | `docs/development/ROADMAP.md`, Goal 2 (task 7.5) |
| This change's status and Goal 2's dependency graph | `openspec/changes/README.md`, Goal 2 (task 7.6) |
| The superseded primary-dimension compatibility reading | This change's `design.md` only |
