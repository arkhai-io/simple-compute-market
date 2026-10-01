# Tasks — publish indicative listing rates

**Status.** Sections 1–2 and 5 (registry-engine and specification work) have no
domain dependency and may proceed now. Section 3 (VM declaration, resolution, and
publication) may proceed now — VM publishes shapes from resource-pool projections,
joins the site-scoped override store, and refreshes terms in place today, per
`design.md`'s "Domain scope and dependencies". Section 3b (bare metal joins the
site-scoped override store) may proceed now: its only prerequisite,
`bare-metal-listing-shapes`, is archived. Section 4 (filters and the compute
schema) is blocked on Section 2. Bare metal's share of Section 3 (publishing and
refreshing the rate once a listing carries a shape) is unblocked on the same
ground as 3b. Tasks 7.13 and 7.14's unbacked-supply half additionally wait on
`unbacked-bare-metal-listings` for bare metal and
`compose-contact-exchange-across-compute` for VM; both are named at the tasks that
wait on them rather than gating the whole section.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Settled decisions to confirm against code

No decision gate remains open. The tasks below confirm the code facts
each decision rests on still hold, and stop rather than proceed if one has moved.

- [ ] 1.1 Confirm `market_alkahest.schemas.PER_UNIT_SECONDS` still holds exactly
      `{"hour": 3600}`. The hourly-only rule is a local asking-rate contract
      validated against that table for parity, not a rule inherited from it.
- [ ] 1.2 Confirm `SettlementPublicationClause` still expresses a published rate as
      an opaque `asset` string and positive decimal `rate` text without an exponent,
      with rate and unit required together.
- [ ] 1.3 Confirm the settlement clause grammar still restricts `asset` to equality
      operators.
- [ ] 1.4 Confirm `contact-exchange.v1` options remain rateless; if that mechanism
      gains a rate, revisit the carrier decision before implementing.
- [ ] 1.5 Confirm the site-scoped pool-override store still applies to a pool at any
      configured site and replaces shapes and settlement clauses as whole lists, and
      that `listing_comparison` still refreshes term fields in place. The override
      precedence and the in-place lifecycle rest on both. Files:
      `kit/pool-overrides/src/market_pool_overrides/records.py`,
      `domains/vms/listings/src/arkhai_vms_listings/listing_comparison.py`.
- [ ] 1.6 Confirm the registry still validates its full `listing_shape` only in the
      dry run (`core/registry/src/core_registry/api/validate_routes.py`,
      `core/registry/src/core_registry/api/validate_model.py`). If
      publish-boundary enforcement has been added, the refusal of a partial rate
      may also move there; re-read `design.md` before relying on it.

## 2. Generic registry prerequisite

The engine cannot evaluate this change's field as it stands. Section 4 is blocked on
this section. Nothing in this section may name a rate, an asset, a period, or any
compute field.

- [ ] 2.1 Add `"decimal_text"` to the `ValueType` literal in
      `core/registry/src/core_registry/api/filter_spec.py` (currently
      `Literal["string", "integer", "number", "boolean", "address"]`, line 51).
- [ ] 2.1a In `core/registry/src/core_registry/api/filter_eval.py`, add a
      `decimal_text` branch to `_coerce_scalar` (parses to `decimal.Decimal`,
      rejecting non-decimal text) and widen `_Range.min`/`_Range.max` to
      `float | int | Decimal | None`. Leave the existing `number` branch (parses
      with `float(raw)`) untouched.
- [ ] 2.1b In `_Range.contains` and the `range` branch of `evaluate`
      (`filter_eval.py`, ~line 400), accept `Decimal` alongside `int`/`float` in
      the `isinstance` check that selects which resolved values participate in a
      range comparison.
- [ ] 2.1c Add the buyer-side mapping entry `"decimal_text": QueryValueType.DECIMAL`
      next to the existing `"number": QueryValueType.DECIMAL` entry in
      `core/registry-client/src/registry_client/query.py`'s `_value_type` (~line
      171). No rendering change: `_scalar` (~line 286) already renders `Decimal`
      exactly.
- [ ] 2.1d Confirm `load_filter_spec` (`filter_spec.py`, ~line 149) still raises on
      an unrecognized `value_type` by virtue of `ValueType` being a closed
      `Literal` and `FilterDecl` forbidding extras — no new code needed, but add a
      unit test pinning this for `decimal_text` specifically (see 7.1).
- [ ] 2.2 Add `requires: list[str] = Field(default_factory=list)` to `FilterDecl`
      in `filter_spec.py`.
- [ ] 2.2a In `load_filter_spec`'s validation loop (`filter_spec.py`, ~line
      161–183), after the existing per-declaration checks, validate each
      declaration's `requires`: every named target must be a declared filter
      `name`, must not name itself, and the `requires` graph over all
      declarations must not contain a cycle (a simple DFS over the
      name→requires adjacency built from `spec.filters`).
- [ ] 2.2b In `core/registry/src/core_registry/api/filter_eval.py`, add the
      co-requirement check to `build_criteria` (~line 327): after
      `_extract_strict_overrides` splits real filter params from `strict.*`
      overrides, for each supplied filter name present in `real_params`, check
      that every name in its `FilterDecl.requires` is also present in
      `real_params`; raise `FilterParamError` naming the missing co-requirement
      if not. Follows `_extract_strict_overrides`'s existing shape of a
      cross-cutting check resolved before the per-criterion loop.
- [ ] 2.2c In `core/src/market_core/query_dsl.py`, add `requires: tuple[str, ...]
      = ()` to `FieldDescriptor` (~line 95), naming other descriptor `name`s. Add
      a validation in `compile_query`/`validate_query` (~lines 431–487) checking,
      over the validated comparisons' field names, that every field's `requires`
      entries are also present among the comparisons; raise the same
      `QueryValidationError` family used for other compile-time refusals.
- [ ] 2.2d In `core/registry-client/src/registry_client/query.py`'s
      `_resource_fields` (~line 94), resolve each filter declaration's `requires`
      (filter `name`s) to the corresponding `FieldDescriptor.name`s (the mapped
      `query_name`s) in a second pass after the full `by name` table is built,
      and populate each `FieldDescriptor.requires` accordingly. Encode no
      specific field's dependency in code — this reads only the specification's
      declared `requires`.
- [ ] 2.2e Confirm an undeclared `requires` (the default `[]`) round-trips through
      `compute_etag` and `_spec_body` (`filter_spec.py`) with no new key added to
      the serialized body beyond what `model_dump(exclude_none=False)` already
      produces for the new field — `requires: []` is itself a new key, so this
      task is to recognize that every filter's etag contribution changes the
      moment the field exists on the model, and to pin the new etag with a
      literal-digest test (see 7.2) rather than assume the existing
      `test_etag_unchanged_for_specs_without_schema_identity`
      (`core/registry/tests/unit/test_filter_spec.py`, ~line 302) covers it — it
      builds its expected payload from the model's own dump and will not catch a
      newly defaulted field changing that dump's shape. Re-confirm against
      `design.md`'s "An undeclared co-requirement leaves the specification's etag
      unchanged" before deciding whether a dump-shape change here is acceptable;
      if it is not, exclude `requires` from serialization when empty
      (`model_dump(exclude_defaults=True)` for that one field, or a custom
      serializer) so the normative claim holds exactly.

## 3. Declaration, resolution, and publication

- [ ] 3.1 Add `ASKING_RATES_POLICY_TAG = "asking_rates"` to
      `kit/resource-pools/src/market_resource_pools/hints.py` beside
      `LISTING_SHAPES_POLICY_TAG` (~line 83). Add `raw_asking_rates(policy_tags,
      offering_mode)` mirroring `raw_listing_shapes` (~line 345) and
      `validate_asking_rates(policy_tags)` mirroring `validate_listing_shapes`
      (~line 458): a mapping of offering mode to a list of `{shape, amount,
      asset, period}` entries, each `shape` structurally checked with the
      existing `shape_structure_problems` helper `validate_listing_shapes`
      already uses, `amount`/`asset`/`period` checked for presence and type only
      (decimal-text-shaped string, non-empty string, non-empty string) — the
      value contract from 3.2 validates content. Export both from
      `kit/resource-pools/src/market_resource_pools/__init__.py` beside
      `validate_listing_shapes`.
- [ ] 3.1a Call `validate_asking_rates` from both existing pool-write call sites
      of `validate_listing_shapes` in
      `kit/resource-pools/src/market_resource_pools/service.py`:
      `_require_valid_policy_tag_hints` (~line 135, the shared helper every
      individual-pool write path uses) and the bulk YAML import loop (~line
      518).
- [ ] 3.2 Add the asking-rate value contract shared by VM and bare metal — a
      pydantic model (new file,
      `kit/resource-pools/src/market_resource_pools/asking_rate.py`, or beside
      `hints.py` if a separate module is unwarranted once written) validating
      decimal-text amount (positive, no exponent, matching the grammar
      `SettlementPublicationClause`'s `rate` field already uses in
      `kit/settlement-runtime`), opaque trimmed non-empty asset, and a period
      checked against `PER_UNIT_SECONDS` parity (`hour` only this version,
      confirmed in 1.1).
- [ ] 3.3 Add asking rates to the site-scoped pool-override store beside listing
      shapes: `asking_rates: list[dict[str, Any]] | None = None` on
      `PoolOverrideRecord` in
      `kit/pool-overrides/src/market_pool_overrides/records.py` (~line 54,
      beside `listing_shapes`), replacing the pool's list as a whole and
      accepting an empty list (distinct from `None`) as withholding every rate —
      `listing_shapes`' `_non_empty` validator (~line 60) must not be reused
      verbatim here, since it rejects empty lists and this field must not.
- [ ] 3.4 Resolve each listing's rate by canonical shape digest through the
      override, then the pool declaration, then none, in
      `domains/vms/listings/src/arkhai_vms_listings/pricing_resolution.py`
      (new function beside the existing resolution logic there) and wire it into
      candidate construction in
      `domains/vms/listings/src/arkhai_vms_listings/reconciler.py` where
      `shape_fields` are merged per shape digest into each candidate row (~lines
      1080–1118). Supply no rate from storefront configuration. Report entries
      naming an unpublished shape through the same reporting channel
      `infeasible_shapes`/`undeclared_attributes` already use (~lines 1120–1140).
- [ ] 3.5 Hold a pool whose declaration or override is unreadable — unknown shape
      vocabulary, a duplicate shape, or an invalid amount, asset, or period — and
      report it through the reconciler's existing hold-and-report path (the same
      one `_VALID_HINT_FIELD`'s sibling checks use in
      `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`). Do not fall
      through; `design.md` records why this diverges from `_VALID_HINT_FIELD`
      and the divergence must not be "fixed" later.
- [ ] 3.6 Publish `listing_resource.asking_rate` for VM listings in the candidate
      construction path identified in 3.4, excluded from every shape digest and
      derivation identity (confirm it is not read by whatever function computes
      `shape.digest` — `domains/vms/domain/src/arkhai_vms/shape_generation.py` —
      nor by the derivation-identity builder referenced in `design.md`).
- [ ] 3.7 Add `"asking_rate"` to `TERM_RESOURCE_FIELDS` in
      `domains/vms/listings/src/arkhai_vms_listings/listing_comparison.py`
      (~line 48), so a change or removal refreshes the listing in place through
      `compare_listing`/`refreshed_listing_resource` (~lines 81, 118) unchanged.
- [ ] 3.8 Publish and refresh the asking rate for bare-metal listings through the
      same resolution (3.4's function, reused rather than re-implemented) once
      bare-metal publication reads pool declarations and publishes a capability
      shape per listing — both true as of `bare-metal-listing-shapes` (archived).
      Files: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`
      and `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_composition.py`,
      where clause and duration precedence are currently resolved (see 3b.3) and
      where the shape-keyed rate lookup joins it.
- [ ] 3.9 Do not populate the asking rate from a mechanism rate, and do not write
      it into a settlement carrier. Confirm by reading
      `domains/vms/storefront/src/market_storefront/settlement_composition.py`
      and `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_composition.py`
      for any path that reads a listing's published fields when constructing a
      settlement option or escrow term, and confirm neither reads
      `asking_rate`.

## 3b. Bare metal joins the site-scoped override store

Baseline from `bare-metal-listing-shapes`' design review, which moved this work
here; see "Bare metal joins the site-scoped override store" in `design.md`.

- [ ] 3b.1 `kit/pool-overrides`:
      - add the framework-free `PoolOverrideRouteService` (`replace`, `read`,
        `delete`) as a new module,
        `kit/pool-overrides/src/market_pool_overrides/route_service.py`,
        following `kit/contact-exchange`'s `IntroductionRouteService` shape;
      - make `refresh_site` and `wake_publication` accept `None` in
        `kit/pool-overrides/src/market_pool_overrides/service.py`
        (`PoolOverrideService`);
      - bump the kit's version (`kit/pool-overrides/pyproject.toml`);
      - add unit tests over a service double in
        `kit/pool-overrides/tests/unit/test_route_service.py`, and integration
        tests against the real store in
        `kit/pool-overrides/tests/integration/test_route_service.py`, including
        a storefront with no cache and no loop (exercising the now-optional
        `refresh_site`/`wake_publication`).
- [ ] 3b.2 VM storefront: reduce the three override handlers in
      `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`
      (`put_pool_override`, `get_pool_overrides`, the delete handler — ~lines
      618–675) to bindings over `PoolOverrideRouteService`. VM's existing
      override integration
      (`domains/vms/storefront/tests/integration/test_pool_overrides_api.py`),
      identity-dispatch, client-parity
      (`domains/vms/storefront/tests/unit/test_pool_override_client_parity.py`),
      and CLI tests
      (`domains/vms/storefront/tests/unit/cli/test_pool_overrides.py`) must pass
      unchanged.
- [ ] 3b.3 Bare-metal storefront:
      - a new `BareMetalPoolOverrideTerms` model (new file,
        `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/pool_override_terms.py`,
        mirroring
        `domains/vms/storefront/src/market_storefront/models/pool_override_models.py`),
        carrying `min_duration_seconds` and `max_duration_seconds` and no
        shapes;
      - a new `BareMetalPoolOverrideContribution` implementing
        `market_pool_overrides.contribution.PoolOverrideContribution` for
        `bare_metal` (new file,
        `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/pool_override_contribution.py`,
        mirroring
        `domains/vms/storefront/src/market_storefront/services/vm_pool_override_contribution.py`),
        whose `vocabulary_problems` refuses a record stating `listing_shapes`
        and whose `judge_shapes` returns nothing;
      - a new migration for the kit's override tables plus a bare-metal
        storefront table recording, per site, the site, revision, digest,
        projected pool IDs, and acceptance time of every publication run that
        accepted that site's generation — in
        `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/migrations.py`;
      - every publication run records its accepted generation — in
        `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`
        and/or `publication_service.py`;
      - override status reads that table (`unknown` for a site with no row) —
        exposed through
        `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py`'s
        system-status route;
      - three admin routes (`PUT`/`GET`/`DELETE` `/pool-overrides`) bound in
        `api.py` through the existing `_admin` dependency (~line 131), delegating
        to the kit's `PoolOverrideRouteService` from 3b.1;
      - clause and duration precedence in
        `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_composition.py`,
        holding a pool whose override is unreadable (replacing
        `BARE_METAL_STOREFRONT_PUBLICATION_CLAUSES` configuration precedence
        where an override states clauses);
      - wiring in
        `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`
        (`build_runtime_from_environment`, `BareMetalStorefrontRuntime`) to
        construct and hold the `PoolOverrideService` the way
        `domains/vms/storefront/src/market_storefront/server.py` and
        `container.py` do for VM.
- [ ] 3b.4 Bare-metal `pool-override` command (`set --file`, `get`, `list`,
      `delete`, `--mode` never defaulted) over the kit's `SyncPoolOverrideClient`
      in `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py`,
      written for bare metal rather than copied from VM's
      `domains/vms/storefront/src/market_storefront/cli.py` — no
      infeasible-shape warning, since an override here states no shapes.
- [ ] 3b.5 Integration through the typed clients, in a new
      `domains/bare_metal/storefront/tests/test_pool_overrides_api.py` (mirroring
      VM's `test_pool_overrides_api.py`) and
      `domains/bare_metal/storefront/tests/test_publication_cli.py` (extended):
      - replace, read, list, and delete;
      - refusals of shapes, unknown terms, an unconfigured site, an unreachable
        site, and an unknown pool;
      - status `unknown` before any run, `applied` after a run from the command,
        `orphaned`, and `site_unconfigured`;
      - an override's clauses and durations reaching a refreshed listing.
      A VM storefront test
      (`domains/vms/storefront/tests/integration/test_admin_api.py` or
      `test_pool_overrides_api.py`) shows the combined shell still refuses a
      `bare_metal` write.
- [ ] 3b.6 End-to-end: the bare-metal publication scenario in
      `e2e-tests/tests/e2e/` writes an override through the kit client, steps
      publication, and observes the refreshed term at the registry.

## 4. Filters and the compute schema

Blocked on Section 2.

- [ ] 4.0 Confirm the decided query names against `design.md` ("A bound filter's
      bare query name follows the field's preferred direction, not bound
      position"): `asking_rate` for the upper bound, `asking_rate_min` for the
      lower. Stop and revisit rather than proceed if the reasoning no longer
      holds against the current filter-spec conventions
      (`core/registry/filter-spec.yaml`'s existing `*_min` declarations, ~lines
      224–234).
- [ ] 4.1 Declare `asking_rate_max`, `asking_rate_min`, `asking_rate_asset`, and
      `asking_rate_period` in `core/registry/filter-spec.yaml`, beside the
      existing lower-bound block (~line 220–234), with the paths, ops, types,
      and alias kinds `design.md`'s table fixes, naming `asking_rate_max`'s
      `query_name` as `asking_rate` and `asking_rate_min`'s as
      `asking_rate_min` per 4.0.
- [ ] 4.1a Make all four `on_missing: fail`.
- [ ] 4.1b Declare `requires: [asking_rate_asset, asking_rate_period]` on both
      bound filters.
- [ ] 4.1c Match only listings quoting the named period and asset; convert
      across neither (no code change beyond 2.2b's co-requirement check and the
      `in`-op equality filters declared in 4.1 — `asking_rate_asset` and
      `asking_rate_period` as `op: in, value_type: string`).
- [ ] 4.2 Declare the `asking_rate` object in the compute `listing_shape` inside
      `core/registry/filter-spec.yaml` (the `listing_resource.properties` block,
      ~lines 54–119), all three fields (`amount`, `asset`, `period`) required
      when the object is present, so the dry run
      (`core/registry/src/core_registry/api/validate_model.py`) and the served
      self-description (`filter_spec.py`'s `/filter-spec` route) describe it.
- [ ] 4.3 Record the etag consequence in `design.md`'s Migration Plan (already
      stated) and confirm by running the filter-spec test suite
      (`core/registry/tests/unit/test_filter_spec.py`,
      `core/registry/tests/integration/test_filter_spec.py`) after the YAML
      change: the compute specification's etag changes and buyers re-fetch,
      without a version bump; no other deployed specification's etag changes
      (none other declares `decimal_text` or `requires`).

## 5. Specification

- [ ] 5.1 State the two engine capabilities (the `decimal_text` value type and
      declarative `requires` co-requirements) in
      `openspec/specs/registry-discovery/spec.md`, near the existing "Resource
      query compilation preserves filter-spec authority" requirement (~line
      110), including that an undeclared co-requirement leaves a
      specification's serialization and etag unchanged (or, if 2.2e concludes
      otherwise, the corrected statement of that rule).
- [ ] 5.1a State the general naming convention from `design.md` ("A bound
      filter's bare query name follows the field's preferred direction, not
      bound position") in `openspec/specs/registry-discovery/spec.md`, as
      guidance for filter authors rather than an engine-enforced requirement —
      see `design.md`'s note that this binds only a human choosing a
      `query_name`.
- [ ] 5.2 State the compute schema's asking-rate field and its four filters in
      `openspec/specs/registry-discovery/spec.md` near "The published listing
      shape is named for the seller's listing" (~line 182) or "Compute listings
      publish their capacity backing" (~line 211), and that the registry
      validates the field only in the dry run.
- [ ] 5.3 State in `openspec/specs/storefront-publication/spec.md` the per-shape
      declaration and precedence (override, then pool declaration, then none,
      no configuration default), the fail-closed rule, the listing-attribute and
      independent-carrier rules, and the in-place refresh.
- [ ] 5.4 State the `asking_rates` policy tag and its structural validation in
      `openspec/specs/resource-pool-management/spec.md`.
- [ ] 5.5 Record in `openspec/specs/storefront-publication/architecture.md` why
      the rate is keyed by shape beside the shape, why the storefront has final
      authority with no configuration default, and why a site-declared range is
      deferred.
- [ ] 5.6 Record in `openspec/specs/storefront-publication/architecture.md`
      (new "Storefront pool overrides" subsection content, or extending the
      existing one the design cites) and
      `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Storefront listing shapes
      and pool overrides") bare metal's override vocabulary, its status source,
      and the override route service both storefronts bind.

## 6. Cross-change reconciliation

- [x] 6.1 Amend `capacity-shape-pricing` so its single-rate compatibility
      reading names the negotiation-side rate and cannot be read as
      reinterpreting a published asking rate. Already present in that change's
      design.
- [x] 6.2 Correct `docs/development/ROADMAP.md`'s Goal 7 claim that no compute
      listing publishes a price. Current-state text and the gap row now say the
      price exists only inside settlement carriers and no filter reads it.
- [x] 6.3 Correct this change's row in `openspec/changes/README.md` and record
      it as blocked on the bare-metal changes. Superseded by the index's current
      state: both `bare-metal-publication-reads-pool-declarations` and
      `bare-metal-listing-shapes` are now archived, so this change is unblocked
      on bare-metal shapes specifically (Section 4) and on Section 3b's
      override-store join; only the unbacked-supply system evidence (7.13,
      7.14) remains blocked, on `unbacked-bare-metal-listings` and
      `compose-contact-exchange-across-compute`. Re-confirmed current as of this
      planning pass.

## 7. Validation

- [ ] 7.1 **Unit.** `core/registry/tests/unit/test_filter_eval.py` and
      `core/registry/tests/unit/test_filter_spec.py`: exact-decimal comparator
      behaviour — bounds at, above, and below a value; inclusive against
      exclusive at equality; a value with more significant digits than a double
      holds; a resolved listing value of the wrong shape; a spec declaring
      `decimal_text` loads, one declaring an unrecognized type is refused.
- [ ] 7.2 **Unit.** `core/registry/tests/unit/test_filter_spec.py`: co-requirement
      declaration validation — unknown target, self-reference, cycle,
      one-directional supply (naming an asset/period without a bound still
      validates), serialization change when `requires` is declared versus not,
      and a literal-digest pin for the new etag value per 2.2e.
      `core/registry/tests/unit/test_filter_eval.py`: criterion construction
      refusing a bound supplied without its co-requirement.
      `core/tests/unit/test_query_dsl.py`: the buyer-side `requires` check on
      `FieldDescriptor`.
- [ ] 7.3 **Unit.**
      `kit/resource-pools/tests/unit/test_hints.py`: `validate_asking_rates` and
      `raw_asking_rates` — missing field, boundary amounts, an unsupported
      period, a duplicate shape. New test module (e.g.
      `domains/vms/storefront/tests/unit/test_pricing_resolution.py`, extended):
      shape matching by digest, override replacement and the empty override
      list, and — with a synthetic second period — a cross-period query
      excluding rather than converting.
- [ ] 7.4 **Integration.** `core/registry/tests/integration/test_filter_spec.py`
      or a new `test_asking_rate_filter.py`: exact decimal round-trip through
      the canonical `RegistryClient` against the real registry app, matching or
      excluding on the true value.
- [ ] 7.5 **Integration.** Same file as 7.4: a valid three-part rate query
      through the canonical `RegistryClient`; and a narrow raw-ASGI
      rejection-path request supplying an amount bound without its asset,
      proving the registry itself refuses.
- [ ] 7.6 **Integration.** `kit/resource-pools/tests/` (new or extended
      integration test): pool write surfaces refuse a structurally malformed
      `asking_rates` identically on create, replace, patch, and bulk import, and
      project a valid one verbatim.
- [ ] 7.7 **Integration.**
      `domains/vms/storefront/tests/integration/test_reconciler_projection.py`
      (extended): seller authoring through the real pool administration client
      and projection — a rate declared for each of two shapes reaches each
      shape's publication candidate and then the registry.
- [ ] 7.8 **Integration.**
      `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`
      (extended): override authority — an override for a pool at a non-first
      site replaces the declared rate; an empty override list withholds every
      rate; a storefront with pricing defaults and no declaration publishes no
      rate.
- [ ] 7.9 **Integration.** Same file as 7.7: rate lifecycle — change amount,
      asset, and period and confirm each listing refreshes in place under its
      identity; remove the entry and confirm the listing stays discoverable but
      absent from rate-bounded queries.
- [ ] 7.10 **Integration.** Same file as 7.7: an unreadable declaration or
      override holds its pool rather than publishing a fallback or a rateless
      listing.
- [ ] 7.11 **Integration.**
      `domains/vms/storefront/tests/integration/` (new or extended settlement
      composition test) and the bare-metal equivalent in
      `domains/bare_metal/storefront/tests/test_settlement.py`: no settlement
      option, escrow term, or accepted obligation carries a value derived from
      the published rate, and a published rate is not populated from a
      mechanism rate. Exercise through the real storefront composition.
- [ ] 7.12 **Integration.** Same files as 7.11, or the registry integration
      suite: a listing advertising a rateless option (`contact-exchange.v1`)
      publishes an asking rate and is returned by a rate-bounded query while its
      option remains rateless.
- [ ] 7.13 **System.** `e2e-tests/tests/e2e/`: a buyer query bounded by rate
      returns backed and unbacked listings together, bare metal and VM, and
      excludes listings publishing no rate. Blocked on
      `unbacked-bare-metal-listings` and
      `compose-contact-exchange-across-compute`; until both land, record this as
      an explicit blocker and treat it as unrun rather than passed.
- [ ] 7.14 **System.** `e2e-tests/tests/e2e/`: multi-seller provenance — one
      storefront publishing for two seller sites, each site's declared rates
      reaching only its own listings, and an override for one site leaving the
      other's rates unchanged.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve
      every match. The local rationale to keep is why nothing is constructed
      from the rate, why the asking rate is not derived from a mechanism rate,
      why the rate is excluded from shape identity, and why a malformed
      declaration fails closed against the resolver's fall-through convention.
- [ ] 8.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real
      test suite.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. Confirm the engine capabilities
      landed in `registry-discovery`, the publication rules in
      `storefront-publication`, and the policy tag in
      `resource-pool-management`.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, material validation evidence, deferred work, and
      permanent-documentation destinations.
- [ ] 8.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table
      in `docs/development/ROADMAP.md`. If this closes Goal 7's last gap, remove
      the goal and absorb its result into permanent documentation — check the
      remaining rows (`unbacked-bare-metal-listings` and
      `compose-contact-exchange-across-compute`) first; as of this planning
      pass both remain open, so Goal 7 will not yet be fully closed by this
      change alone.
- [ ] 8.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`.
- [ ] 8.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=publish-indicative-listing-rates` and
      resolve every match.
- [ ] 8.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that exercise
      this change's behaviour. If the pipeline cannot run for a reason unrelated
      to this change, record that as an explicit blocker naming the cause and
      the change that owns it, and treat the validations it gates as unrun
      rather than passed.
- [ ] 8.9 **Promotion.** Complete the design-promotion record below.
- [ ] 8.10 **Packaging.** Run `make check-packaging` and resolve every failure
      it reports: environment and image installs derive their internal
      packages from their locks, every lock is current, and every Python
      version selection reads the root declaration.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| An exact-decimal declared value type whose comparison never passes through binary floating point | `openspec/specs/registry-discovery/spec.md` |
| Declarative filter co-requirements, resolved from the specification by registry and buyer alike | `openspec/specs/registry-discovery/spec.md` |
| An undeclared co-requirement leaves a specification's serialization and etag unchanged | `openspec/specs/registry-discovery/spec.md` |
| The compute schema's asking-rate field, validated by the registry only in the dry run | `openspec/specs/registry-discovery/spec.md` |
| Rate filters match the period and the asset rather than normalizing across them; a listing publishing no rate is excluded | `openspec/specs/registry-discovery/spec.md` |
| A bound filter's bare query name follows the field's preferred search direction (lower bound for capacity-shaped dimensions, upper bound for cost-shaped ones), not bound position | `openspec/specs/registry-discovery/spec.md` |
| The asking rate is declared per shape; override, then pool declaration, then none; no configuration default | `openspec/specs/storefront-publication/spec.md` |
| A malformed asking-rate declaration holds its pool | `openspec/specs/storefront-publication/spec.md` |
| The asking rate is a listing attribute and independent of any mechanism rate | `openspec/specs/storefront-publication/spec.md` |
| An asking-rate change refreshes the listing in place | `openspec/specs/storefront-publication/spec.md` |
| The `asking_rates` policy tag and its structural validation | `openspec/specs/resource-pool-management/spec.md` |
| Why the rate is keyed by shape, why the storefront has final authority, why a site range is deferred | `openspec/specs/storefront-publication/architecture.md` |
| Bare metal's override vocabulary, status source, and shared route service | `openspec/specs/storefront-publication/architecture.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Goal 7 current state and gap ownership | `docs/development/ROADMAP.md` |
