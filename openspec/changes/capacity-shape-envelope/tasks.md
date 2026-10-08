# Implementation Tasks

Replanned on 2026-10-07 against the design that passed review (`reviews/06-design.triage.md`).
The earlier plan had no completed task; it described a superseded design (a pool-level
bounds tag, a range query ignoring the rest of the shape, negotiation wiring, and promotion
to `site-capacity`) and is replaced whole.

Each section is one implementation session. Sections run in order: each depends on the
packages the one before it builds.

## 1. The admissibility foundation kit

Delivers `kit/capability-admissibility` (`market_capability_admissibility`): splitting,
parsing, labelled resolution, and evaluation. Implements D2, D3, D4, D5, D6, D7, and D9's
merge rule; `market-composition` delta requirements "Capability shape admissibility is
owned by one kit" and "Shape constraints are stated inline and strictly". Touches only the
new package and `kit/Makefile`. No Helm checks owed.

- [x] 1.1 Create the distribution `arkhai-kit-capability-admissibility` beside
      `kit/capability-pricing`, copying its layout: `pyproject.toml` depending only on
      `arkhai-kit-capability-shape`, `Makefile`, `src/market_capability_admissibility/`
      with `py.typed`, `tests/unit/`, and a lock built through `scripts/uv_project.py`.
      Register `test-capability-admissibility` and `dist-capability-admissibility` in
      `kit/Makefile` (including `test`, `dist`, and `dist-ci`). (D2)
      Done. `kit/capability-admissibility` copies `kit/capability-pricing`'s layout,
      adding `py.typed`; its test target uses `uv run --find-links $(DIST_DIR)` as
      `BUILD_AND_PACKAGING.md` prescribes (the pricing and shape kits omit it).
      `scripts/uv_project.py lock` only relocks, so the first lock was created with the
      `uv lock --find-links ../../.dist` it runs, then relocked through the script
      unchanged.
- [x] 1.2 Define the public types: opaque `Declaration` and `ResolvedPolicy` (the policy
      keeps the schema it was resolved with); `AdmissibilityProblem` carrying `paths`
      (tuple), `code`, `message`, and `tier`; the opaque `AdmissibleValues`; and a typed
      request error carrying every problem. Nothing exposes a declaration's or policy's
      contents. (D3, D4)
      Done. `AdmissibilityProblem` also carries `entries` (list positions, for
      conflicting duplicates) and `bounds` (`TierBound`s, each tier's value for an empty
      range), which section 4's reports need. `tier` is `None` on a problem with an
      evaluated shape itself. Codes are the `ProblemCode` enum. Results are
      `ShapeSplit`, `ShapeListSplit`, `DeclarationParse`, and `Resolution`.
- [x] 1.3 `split_listing_shape(raw, *, tier, schema=None)`: base shape (scalars kept,
      constrained fields reduced to `offer`, constraint-only fields omitted) and either a
      `Declaration` or constraint problems. Structure only without a schema; with one,
      constrained paths must be quantities the schema defines. Read the base shape first:
      a constraint-only mapping on a required field is a base-shape problem with no
      declaration. Constraint rules: positive integers, `min` ≤ `max`, `offer` within its
      own range, at least one key, strict keys. (D3, D5)
      Done. A mapping is a constraint only on a well-named field; anything else stays in
      the base shape for the shape kit to report. With a schema an unreadable offer
      (`{offer: 0}`) is a base-shape problem; without one it is a constraint problem. A
      constraint on an undefined field is a constraint problem only when it states no
      offer (with one, the base shape names the undefined field).
- [x] 1.4 `split_listing_shapes(raw_list, *, tier, schema=None)`: per-entry split; entries
      identical in base shape and constraints collapse; a base shape (by the shape kit's
      `shape_digest`) stated with different constraints is reported naming each
      conflicting entry, with or without a schema. (D3, D8's duplicate rule)
      Done. Every entry is split on its own, so an unreadable `offer`-only mapping is
      reported whatever its position (found by the fresh-context check; regression test
      added). Constraints compare by a schema-free signature in which an `offer`-only
      mapping equals its scalar and an empty mapping differs from stating nothing.
- [x] 1.5 `parse_declaration(raw, *, tier, schema=None)` for the constraint-only form: the
      same field syntax, `offer` refused. (D3, D9)
      Done. An empty declaration or empty family states no constraint; a scalar is
      refused as an offer.
- [x] 1.6 `resolve(declarations, schema)`, highest tier first: per-leaf `min`/`max` merge
      (the higher tier stating a leaf wins; an unstated leaf keeps the lower value); an
      empty range is a problem naming each tier and its conflicting value; no policy on
      any problem. (D3, D9)
      Done. An empty-range problem's `tier` is the higher tier involved; `bounds` names
      both. `resolve` also refuses a declared path that is not a quantity of its schema
      (a declaration split without one).
- [x] 1.7 `admissibility_problems(shape)` under completion semantics: an omitted field
      never violates; a malformed shape under the schema is reported as problems; required
      fields are not checked; each problem names the tier that set the violated leaf.
      (D3, D6, D7)
      Done. Uses the shape kit's `shape_problems` with every field made non-required, so
      no shape validation is duplicated.
- [x] 1.8 `admissible_values(dimension, partial_shape)` and `AdmissibleValues`
      (`is_empty`, `contains`, `at_most`, `at_least`, `minimum`, `maximum`; `maximum` is
      `None` when unbounded; every value accessor answers `None` on an empty set). `{}` is
      valid; a dimension that is not a schema quantity, or a malformed partial shape,
      raises the request error. (D3, D4)
      Done. Both evaluations are methods on `ResolvedPolicy`.
- [x] 1.9 Unit tests in `tests/unit/` against a synthetic schema with no compute
      vocabulary, covering every scenario of both `market-composition` delta
      requirements, plus a property test of the one-dimension-at-a-time guarantee (fixing
      dimensions in every order never empties a later answer and ends admissible).
      `test_import_boundary.py` asserts the kit imports only the shape kit and the
      standard library, at any depth, under `TYPE_CHECKING`, or behind `try`. (D2, D12's
      neutrality proof)
      Done. 90 unit tests; the property test runs 200 seeded random policies over every
      dimension order. The import-boundary test walks the whole AST, including
      `__import__` calls.
- [x] 1.10 Verify: `make -C kit test-capability-admissibility`, `make dist`, and
      `make check-packaging`.
      Done. `make -C kit test-capability-admissibility`: 90 passed.
      `make check-packaging` (which runs `make dist`): all four checks OK.
      `make check-comment-hygiene` and
      `make check-doc-citations CHANGE=capacity-shape-envelope`: OK.

Handoff from section 1:

- The kit's module docstring ends with a bare pointer to `market-composition/spec.md`, which
  states no admissibility requirement until 7.10 promotes them; add the heading anchor
  then.
- `Declaration` is a frozen dataclass and `ResolvedPolicy` has a public constructor, so
  their opacity holds by the underscore convention, not enforcement. Kept: `Declaration`
  equality is what makes a scalar and its `offer` mapping compare equal in tests.
- For sections 2–3: refuse or hold on `ShapeListSplit.base_problems`; per listing, use each
  `ShapeSplit`'s `declaration` or `constraint_problems`; format positions from
  `problem.entries`.

## 2. Pool-write validation of constrained listing shapes

Delivers the structural split at every pool-write surface. Implements D10's pool-write
bullet and the `resource-pool-management` delta "Listing-shape hint validation". Touches
`kit/resource-pools` (its dependency on the new kit, `hints.py`) and the lock of every
project that locks `kit/resource-pools`. No Helm checks owed: no chart, image input, or
configuration surface changes.

- [x] 2.1 Add the dependency on `arkhai-kit-capability-admissibility` to
      `kit/resource-pools`, then `make lock` so every dependent lock gains the new wheel.
      A foundation kit below an authority kit is a permitted edge (`ARCHITECTURE.md`, kit
      layers). (D2)
      Done. `make lock` added only the new wheel, to 12 locks. The first attempt resolved
      against a `.dist` holding higher-versioned wheels built on other branches
      (resource-pools 0.6.0, site 0.10.0, …) and rewrote locks to them; reverted, `.dist`
      rebuilt from empty, relocked. The shape-kit dependency stays: `asking_rates.py`
      still calls `shape_structure_problems`.
- [x] 2.2 `validate_listing_shapes` calls `split_listing_shapes(..., schema=None)` per mode
      in place of `shape_structure_problems`: malformed constraints and conflicting
      duplicates are refused naming each entry; identical entries are accepted; an empty
      list is refused as today. `raw_listing_shapes` keeps passing the value unread. No
      comparison with any storefront's configured default. (D10)
      Done. Every pool-write surface already reached it through `service.py`, so nothing
      else changed. The tier label is `listing_shapes`; a problem's location is
      `listing_shapes.<mode>[<entries>].<path>`, e.g. `vm[0, 2].gpu.count` for a conflict.
- [x] 2.3 Unit tests in `kit/resource-pools/tests/unit/test_hints.py` for every scenario of
      the delta requirement. Library integration in
      `tests/integration/test_resource_pool_service.py`: the individual create, replace,
      and update surfaces and bulk import refuse alike without changing stored metadata.
      Done. `TestListingShapesHint` gains every delta scenario (constrained list accepted,
      six malformed constraints, an attribute constraint accepted, a conflicting duplicate
      named once with both entries, identical repeats and scalar/`{offer}` equivalence
      accepted, modes judged apart). `TestListingShapeConstraintsOnEveryWriteSurface`
      covers create, replace, patch, and bulk validation for both refusals.
- [x] 2.4 Provisioning integration in
      `provisioning/compute/service/tests/integration/test_pools_api.py`: a conflicting
      duplicate and a malformed constraint are refused through the typed client, asserting
      status and stored state only (`TESTING.md` rejection-path rule).
      Done: a conflicting duplicate on create, a malformed constraint on replace.
- [x] 2.5 Verify: `make -C kit test-resource-pools`, the compute provisioning service's
      integration suite, and `make check-packaging`. Confirm the bare-metal storefront,
      which reads `listing_shapes` only for its presence (`site_reading.py`), is unaffected
      by running its unit suite.
      Done. `make -C kit/resource-pools test`: 301 passed. Provisioning service
      `make test-integration`: 285 passed. Bare-metal storefront `make test` (one suite, no
      `unit/` split): 227 passed. `make check-packaging`, `make check-comment-hygiene`, and
      `make check-doc-citations CHANGE=capacity-shape-envelope`: OK.

Handoff from section 2:

- `make lock` resolves against whatever `.dist` holds, and that wheelhouse may carry
  higher-versioned wheels built on other branches; check its added/updated lines name only
  this section's wheels, and if not, rebuild `.dist` from empty and relock.
- The fresh-context check found one stale `pyproject.toml` comment (fixed); nothing else.
- `domains/vms/listings` has no lock of its own; the VM storefront's lock covers it.

## 3. VM domain: stated-shape resolution and the bounded generator

Delivers per-listing resolution of stated shapes and the generator bounded by the
configured default, without yet changing derivation. Implements D3 (every reader splits
through the kit), D5, D9 (tiers, override replacing the hint whole, generated shapes under
the default alone), and D10's generator and identity bullets. Touches `domains/vms/domain`
(`shape_generation.py`, `__init__.py`, its dependency on the kit) and `domains/vms/listings`
(`listing_shapes.py`, `asking_rates.py`, its dependency). No Helm checks owed.

- [x] 3.1 Add the kit dependency to `domains/vms/domain` and `domains/vms/listings`, and
      `make lock`. (D2)
      Done. `make lock` added only the kit and its edges (seven locks).
- [x] 3.2 Change the `ListingShapeGenerator` protocol to take the default-only
      `ResolvedPolicy` beside the members; `gpu_count_shapes` chooses, per model, the counts
      from one to the largest declared that
      `admissible_values("gpu.count", {"gpu": {"model": m}})` contains. With no
      configured default the output is unchanged. Extend
      `domains/vms/domain/tests/test_shape_generation.py`: bounded, unbounded, minimum
      above every member, two models. (D10)
      Done. `policy` is a required argument: with no configured default the caller passes
      the policy resolved from no tiers. The generator steps through the answer with
      `at_least`, so it assumes no interval. Added cases: a configured minimum, and a
      constraint on another dimension not bounding the count. Nothing injects a custom
      generator anywhere in the tree.
- [x] 3.3 `listing_shapes.py`: stated lists (override, else hint) are split through
      `split_listing_shapes` with the VM schema and the source as the tier label. An
      unreadable base shape anywhere makes the list unreadable (the existing hold). Each
      listing becomes an entry carrying its base `ResolvedShape` and either its
      `ResolvedPolicy` (resolved with the configured default as the lower tier) or the
      problems that make it uncomputable (unreadable constraints, empty range, conflicting
      duplicate). A generated shape's policy is the default alone. The digest stays
      `vm_shape_digest` of the base shape. No code outside the kit reads a constraint.
      (D3, D8, D9, D10)
      Done. `ShapeResolution.listings` holds `ListingShape(shape, policy, policy_problems)`;
      `shapes` remains as every listing's base shape, so derivation is unchanged until
      section 4. `default_only_policy(configured_default)` is exported for 4.4. Tiers are
      `storefront_override`/`pool_hint` and `configured_default`
      (`CONFIGURED_DEFAULT_TIER`). The kit collapses identical entries, so stated lists
      no longer go through `_deduplicated`; generated ones still do. Unreadable problems
      read `[<entries>] <path>: <message>`, as before.
      `resolve_vm_listing_shapes` takes `configured_default` as a required keyword; both
      reconciler call sites pass `None` until 4.1 supplies the parsed default.
- [x] 3.4 Asking rates match the base shape's digest (`asking_rates.py`); a rate entry's
      shape stays a plain shape, as `vm_shape_problems` already requires. (D10)
      Done with no code change: listing digests are already base-shape digests. The
      module docstring now says so; a 3.5 test prices a constrained listing from a
      plain-shape rate.
- [x] 3.5 Unit tests in a new `domains/vms/storefront/tests/unit/test_listing_shape_resolution.py`
      (the listings package has no suite of its own; the storefront's unit suite covers
      it): shorthand scalars, a constrained offer, a constraint-only field, an override
      not inheriting the hint's constraints, each uncomputable case, an unreadable base
      shape, and identity unchanged when only constraints change.
      Done, 20 tests, plus narrowing, widening, and filling by the configured default, and
      tier labels on problems. The compute schema has no optional attribute, so an
      attribute constraint always leaves the base unreadable (`gpu.model` is required);
      the readable uncomputable cases are an unknown key, an undefined field, an empty
      range, and a conflicting duplicate.
- [x] 3.6 Verify: the VM domain suite, the VM storefront unit suite, and
      `make check-packaging`.
      Done. VM domain `make test`: 48 passed. VM storefront `tests/unit`: 1122 passed,
      1 skipped; `tests/integration`: 349 passed. VM buyer `make test`: 206 passed.
      `make check-packaging`, `make check-comment-hygiene`, and
      `make check-doc-citations CHANGE=capacity-shape-envelope`: OK.
      mypy (storefront config, run ad hoc with `uv run --with mypy`; no target runs it)
      over `listing_shapes.py` and `shape_generation.py`: no issues.

Handoff from section 3:

- Derivation still publishes every listing's base shape, including those whose policy is
  `None`: `_projected_pool_rows` reads `resolution.shapes`. Section 4 filters on
  `resolution.listings`; both `resolve_vm_listing_shapes` call sites in `reconciler.py`
  pass `configured_default=None` until 4.1.
- `declared_shape_feasibility` already sees base shapes, because resolution yields them,
  so 4.5 may need only a test.
- 4.4 can call `gpu_count_shapes` with one synthetic member carrying the row's model and
  range, so local tables choose counts exactly as the generator does.
- The fresh-context check's two plan gaps (the architecture generator sentence, and the
  spec's Evidence list) were appended to 7.10.


## 4. VM derivation and publication

Delivers the publication behavior: per-listing close, inadmissible offers withheld,
reports, and local-table derivation under the configured default. Implements D8, D10
(publication, identity, reports, local tables), and the `storefront-publication` delta
requirements "A VM listing's admissibility resolves per listing", "A VM listing whose
admissibility cannot be computed closes", "VM publication never advertises an inadmissible
offer", and the modified "Every VM listing is a listing shape". Touches
`domains/vms/listings/src/arkhai_vms_listings/reconciler.py` only. No Helm checks owed.

Amended in implementation, with the owner: the key readers that reconciliation closes and
reopens by (`current_available_resource_keys`, `stale_open_listing_ids`,
`closed_available_listing_ids`) derived without `hint_resolution`, so a listing the
configured default excludes would never close. They take `admissibility_default` as a
required keyword, and section 4 also touches their storefront callers
(`publication_loop.py`, `publication_service.py`, `controllers/admin_controller.py`,
`failure_actions.py`) and the inventory guard (`services/listing_source_check.py`), each
passing `None` until 5.1 supplies the parsed default.

- [x] 4.1 `PoolHintResolutionSettings` gains the parsed configured default (a
      `Declaration`, or none); derivation passes it to listing-shape resolution and the
      generator. (D9)
      Done. `PoolHintResolutionSettings.admissibility_default` (`None` when unconfigured);
      derivation passes it to listing-shape resolution, and through it to the generator.
- [x] 4.2 `_projected_pool_rows`: a listing whose policy cannot be computed is not
      derived, so reconciliation closes an open listing for it, while the pool's other
      listings publish; a stated listing whose base shape is inadmissible under its policy
      is withheld the same way; an unreadable base shape keeps the existing pool hold.
      Generated shapes are never reported. (D8, D10)
      Done in `_admissible_shapes`, which runs right after the unreadable-list hold; every
      later step (rates, terms, feasibility, `listing_shapes`, infeasibility reports) reads
      the admitted shapes only. See the amendment above for the key readers.
- [x] 4.3 `_SiteDerivationReport` gains `inadmissible_listing_shapes` (tier, shape,
      problems) and `unusable_shape_constraints` (tier, path, problem, each tier's
      conflicting value, or each conflicting entry), logged once per change through
      `_record_site_report` like the existing keys; system status serves them unchanged.
      (D10)
      Done. `unusable_shape_constraints` entries carry `tier`, `shape_digest`, `shape`,
      `paths`, `code`, `problem`, `bounds` (tier, bound, value), and `entries`;
      `inadmissible_listing_shapes` entries carry the source `tier`, the shape, and each
      problem's `tier`, `paths`, `code`, and `message`. System status serves the report
      generically, so nothing else changed.
- [x] 4.4 `_local_table_shapes` chooses counts from `admissible_values` under the
      default-only policy, as the generator does. (D10, local-table bullet)
      Done by calling `gpu_count_shapes` with one synthetic member carrying the row's model
      and range, under `default_only_policy`.
- [x] 4.5 `declared_shape_feasibility` judges the override's base shapes. (D10)
      Done with no code change beyond section 3: resolution yields base shapes. A test
      keys a constrained override's feasibility by its base shape. The judgement still
      uses no configured default; the override write check (5.2) refuses an inadmissible
      shape first.
- [x] 4.6 Integration tests in `domains/vms/storefront/tests/integration/test_reconciler_derivation.py`
      (cases in `tests/_reconciler_cases.py`): every scenario of the three added
      requirements and the modified one, including identity kept across a
      constraint-only change, the next reconciliation closing a listing whose offer
      became inadmissible, and local-table derivation under a configured default. Extend
      `test_reconciler_projection.py` so a stored listing's key and the inventory guard's
      re-derivation agree for a constrained shape.
      Done: `TestShapeAdmissibility` (18 cases), one feasibility case, and one
      projection case binding a constrained candidate through
      `prepare_vm_listing_binding`. The test helpers' `_keyed` wrapper supplies
      `admissibility_default=None` unless a case states one.
- [x] 4.7 Verify: the VM storefront unit and integration suites.
      Done. VM storefront `tests/unit` + `tests/integration`: 1491 passed, 1 skipped.
      `make check-packaging`, `make check-comment-hygiene`, and
      `make check-doc-citations CHANGE=capacity-shape-envelope`: OK. mypy over
      `reconciler.py` and `listing_source_check.py`: six errors, all present at HEAD
      before the section; none added.
      End-to-end, sections 2–4 together: GitHub Actions run 37736356195 at d725cb55
      (`make run-e2e`, logs fetched with `make fetch-e2e-logs`) passed both lanes. VM lane
      135 passed, 280 deselected; bare-metal lane 16 passed, 399 deselected; nothing
      skipped or failed. All 14 cases of `test_listing_shapes.py` passed, which shows
      unconstrained stated shapes still publish, discover, reserve, and size as before.
      That is regression evidence only: the scenario states no constraint until 6.1, so
      it does not satisfy 6.2 or 7.9. ebf12fc2, an API-credits test-fixture change, was not
      in the run.

Handoff from section 4:

- No configured default reaches a running storefront yet: every caller passes
  `admissibility_default=None` and `pool_hint_resolution_settings()` sets none. 5.1's
  amendment lists each site; `grep -rn "admissibility_default=None" domains/vms/storefront/src`
  finds them, and closeout should find none left.
- `reconciler.py` cites
  `storefront-publication/spec.md#requirement-a-vm-listing-whose-admissibility-cannot-be-computed-closes`,
  which resolves only once 7.10 promotes that requirement.
- An asking rate stated for an excluded or uncomputable shape is also reported under
  `unpublished_asking_rates`, beside the admissibility report keys. Kept: the rate does
  reach no buyer.
- mypy reports six errors in `reconciler.py` and `listing_source_check.py`, all present
  before section 4; untouched.
- The fresh-context check found a bare spec pointer (now a heading anchor) and
  integration cases re-asserting unit-level problem codes (trimmed to one representative
  detail per report field).

## 5. VM storefront composition: the configured default and the override write check

Delivers `[admissibility.defaults.vm]` and the override contribution's write check.
Implements D9 (the carrier, parsed once, a malformed default stopping startup) and D10's
override-write bullet. Touches `domains/vms/storefront`: `services/publication_terms.py`,
`startup.py`, `settings.toml` (ships none), the configuration template in
`groups/config.py`, `services/vm_pool_override_contribution.py`, and the composition that
constructs the publication loop and the contribution. Owes the Helm check because it
changes the storefront's configuration surface.

- [ ] 5.1 Parse `[admissibility.defaults.vm]` once at startup with
      `parse_declaration(tier="configured_default", schema=VM_CAPABILITY_SCHEMA)`; absent and
      empty both mean no default; a malformed table stops startup naming each problem,
      as `_require_readable_family_rates` does. Hand the same `Declaration` to publication,
      the generator's composition, and the contribution. Add a commented example to the
      configuration template; `settings.toml` states none. (D9)
      Amended in section 4: the same `Declaration` also replaces every explicit
      `admissibility_default=None` section 4 left: `PoolHintResolutionSettings` built by
      `pool_hint_resolution_settings()`, the key-reader calls in `publication_loop.py`,
      `publication_service.py`, `controllers/admin_controller.py`, and
      `failure_actions.py`, and the inventory guard's settings in
      `services/listing_source_check.py`. Integration evidence that a configured default
      closes a listing through the publication loop belongs to 5.3.
- [ ] 5.2 `VmPoolOverrideContribution.vocabulary_problems` splits the record's shapes
      through the kit with the VM schema and resolves each against the configured default,
      refusing unreadable base shapes or constraints, conflicting duplicates, an empty
      range, and an inadmissible offer, all before any site call. `judge_shapes` reports
      feasibility for base shapes. (D10)
- [ ] 5.3 Unit tests: a new `tests/unit/test_startup_admissibility_default.py` beside
      `test_startup_family_rates.py`; extend `tests/unit/test_vm_pool_override_contribution.py`.
      Integration: `tests/integration/test_pool_overrides_api.py` covers each of the three
      override-write scenarios through the typed client, asserting the site was not called
      and the stored override is unchanged; `tests/integration/test_publication_loop.py`
      covers a configured default reaching a publication cycle and the new report keys in
      system status.
- [ ] 5.4 Helm: run `make helm-values-schema` and confirm the generated schema is
      unchanged (`[admissibility]` is an untyped section, as `[pricing]` is), or run the
      chart render tests if it changed.
- [ ] 5.5 Verify: the VM storefront unit and integration suites, and `make check-packaging`.

## 6. End-to-end scenario

Delivers system-level evidence that a constrained stated shape crosses the site,
storefront, and registry boundary as its base shape. Implements D5 and D10 at the system
level. Touches `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`. No Helm
checks owed unless the lane's configuration changes.

- [ ] 6.1 Extend the listing-shapes scenario: the pool states a shape with
      `gpu.count {offer: 1, max: 4}` and `memory.gib {max: 512}` through the site's
      operator client; one publication cycle publishes a listing with a GPU count of 1 and
      no `ram_gb`, and the registry listing carries no constraint. Use typed clients only.
- [ ] 6.2 Verify: run the VM lane with `make run-e2e` and
      `make fetch-e2e-logs E2E_RUN_ID=<run>`; the evidence is recorded in 7.9.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`. Promotion (7.10) follows the
pre-closeout review, as `AGENTS.md` asks.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match;
      read the new kit and every touched module for references to reviews or migrations.
- [ ] 7.2 **Import placement.** Review the imports sections 1–5 added or touched. The
      local import of `market_resource_pools` in `listing_shapes.py` stays local for its
      recorded reason (buyers install the listings package without the pool kit).
- [ ] 7.3 **Documentation compliance.** Check every decision's destination against
      `openspec/README.md#documentation-placement`. Verify the design's risk controls
      directly: nothing outside the kit walks a constraint mapping, a `Declaration`, or a
      `ResolvedPolicy`; every `listing_shapes` reader (`grep raw_listing_shapes`,
      `resolve_vm_listing_shapes`, the override contribution) splits through the kit
      before using a shape; no unconditional `admissible_values` answer is cached.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, deferrals, and destinations.
- [ ] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md` Goal 2, remove the gap row
      "Nothing expresses which shapes a seller will consider…" (now closed), add stated
      constraints and the configured default to the current-state description, and
      correct the sentence saying the seller's feasibility check compares no quantitative
      dimension (the inventory guard checks the published quantity against its source).
- [ ] 7.6 **Campaign index currency.** In `openspec/changes/README.md`: update this
      change's row; remove it from `publish-shape-bounds`'s `Depends on` (its status
      `ready for design` stays); update `negotiation-driven-capacity-resize`'s Notes, whose
      task 2.4 depends on this change (it has begun implementing, so its status stays);
      update the Goal 2 dependency graph. Check each item under design.md's "Findings
      outside this change" against `openspec/changes/` and list the unowned ones in the
      index's unowned-work table for this goal.
- [ ] 7.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=capacity-shape-envelope` and resolve every match.
- [ ] 7.8 **Packaging.** Run `make check-packaging` and resolve every failure.
- [ ] 7.9 **End-to-end pipeline.** Confirm the pipeline passes and record the run, its
      result, and that `test_listing_shapes.py` (6.1) exercises this change. If it cannot
      run for an unrelated reason, record the blocker and its owning change, and treat the
      gated validations as unrun.
- [ ] 7.10 **Promotion.** Write the permanent documentation below, then complete the
      design-promotion record:
      - `openspec/specs/market-composition/spec.md`: the two added requirements, synced
        from the delta.
      - `openspec/specs/market-composition/architecture.md`: a new section
        "Capability shape admissibility", after "The compute family vocabulary": why the
        interface takes whole shapes and returns no unconditional bounds (coupled
        constraints, counter-proposals), why occupancy is excluded, why constraints sit
        inline on the listing, and why a requirement that a dimension be stated is not a
        constraint.
      - `openspec/specs/resource-pool-management/spec.md`: the modified "Listing-shape hint
        validation".
      - `openspec/specs/storefront-publication/spec.md`: the modified "Every VM listing is
        a listing shape" and the three added requirements.
      - `openspec/specs/storefront-publication/architecture.md`: a new subsection
        "Shape constraints" under "Listing shapes and the storefront's authority":
        admissibility is the storefront's policy and a site's constraint an advisory
        input; why an uncomputable policy closes one listing where pricing and an
        unreadable shape list hold.
      - `docs/development/ARCHITECTURE.md`: the kit-layers foundation list gains
        `kit/capability-admissibility`; "Omission states no commitment" gains that an offer
        without a range commits nothing about negotiability; a new subsection under
        "Authority boundaries", "Holding or closing a listing the storefront cannot fully
        derive", states the test as a framework with brief examples (pricing and an
        unreadable shape list hold, uncomputable admissibility closes); the "VM listing
        shapes a storefront publishes" authority row adds the constraints and the
        configured default.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront listing shapes and pool
        overrides": the inline `{offer, min, max}` form, `[admissibility.defaults.vm]`,
        what pool and override writes refuse, local-table derivation, and the rollback
        procedure from design.md's Migration Plan.
      - `openspec/specs/storefront-publication/architecture.md`, "Listing shapes and the
        storefront's authority": the generator sentence says it yields only the counts
        the configured default admits.
      - `openspec/specs/storefront-publication/spec.md`, `## Evidence`: cite
        `domains/vms/storefront/tests/unit/test_listing_shape_resolution.py` and the
        section 4 derivation tests.
      - `openspec/specs/README.md`: unchanged, since every companion already exists;
        record that disposition.
      - Not promoted here: the negotiation invariant and omitted-dimension policy, which
        `negotiation-driven-capacity-resize` owns.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
