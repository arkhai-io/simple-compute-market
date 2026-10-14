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
      Done; its test target uses `uv run --find-links $(DIST_DIR)` as
      `BUILD_AND_PACKAGING.md` prescribes.
- [x] 1.2 Define the public types: opaque `Declaration` and `ResolvedPolicy` (the policy
      keeps the schema it was resolved with); `AdmissibilityProblem` carrying `paths`
      (tuple), `code`, `message`, and `tier`; the opaque `AdmissibleValues`; and a typed
      request error carrying every problem. Nothing exposes a declaration's or policy's
      contents. (D3, D4)
      Done; problems also carry `entries` and `bounds` (design.md, "Implementation
      decisions"). Codes are the `ProblemCode` enum.
- [x] 1.3 `split_listing_shape(raw, *, tier, schema=None)`: base shape (scalars kept,
      constrained fields reduced to `offer`, constraint-only fields omitted) and either a
      `Declaration` or constraint problems. Structure only without a schema; with one,
      constrained paths must be quantities the schema defines. Read the base shape first:
      a constraint-only mapping on a required field is a base-shape problem with no
      declaration. Constraint rules: positive integers, `min` ≤ `max`, `offer` within its
      own range, at least one key, strict keys. (D3, D5)
      Done; edge classifications are in design.md, "Implementation decisions".
- [x] 1.4 `split_listing_shapes(raw_list, *, tier, schema=None)`: per-entry split; entries
      identical in base shape and constraints collapse; a base shape (by the shape kit's
      `shape_digest`) stated with different constraints is reported naming each
      conflicting entry, with or without a schema. (D3, D8's duplicate rule)
      Done; every entry is split on its own, so an unreadable entry is reported at any
      position.
- [x] 1.5 `parse_declaration(raw, *, tier, schema=None)` for the constraint-only form: the
      same field syntax, `offer` refused. (D3, D9)
      Done; an empty declaration or family states no constraint.
- [x] 1.6 `resolve(declarations, schema)`, highest tier first: per-leaf `min`/`max` merge
      (the higher tier stating a leaf wins; an unstated leaf keeps the lower value); an
      empty range is a problem naming each tier and its conflicting value; no policy on
      any problem. (D3, D9)
      Done; it also refuses a declared path that is not a quantity of its schema.
- [x] 1.7 `admissibility_problems(shape)` under completion semantics: an omitted field
      never violates; a malformed shape under the schema is reported as problems; required
      fields are not checked; each problem names the tier that set the violated leaf.
      (D3, D6, D7)
      Done, through the shape kit's `shape_problems` with every field non-required.
- [x] 1.8 `admissible_values(dimension, partial_shape)` and `AdmissibleValues`
      (`is_empty`, `contains`, `at_most`, `at_least`, `minimum`, `maximum`; `maximum` is
      `None` when unbounded; every value accessor answers `None` on an empty set). `{}` is
      valid; a dimension that is not a schema quantity, or a malformed partial shape,
      raises the request error. (D3, D4)
      Done, as methods on `ResolvedPolicy`. Amended after reviews 07 F2 and 12 F1: the
      accessors take any finite real threshold (design.md, "Implementation decisions").
- [x] 1.9 Unit tests in `tests/unit/` against a synthetic schema with no compute
      vocabulary, covering every scenario of both `market-composition` delta
      requirements, plus a property test of the one-dimension-at-a-time guarantee (fixing
      dimensions in every order never empties a later answer and ends admissible).
      `test_import_boundary.py` asserts the kit imports only the shape kit and the
      standard library, at any depth, under `TYPE_CHECKING`, or behind `try`. (D2, D12's
      neutrality proof)
      Done; the property test runs 200 seeded policies over every dimension order, and
      the boundary test walks the whole AST, including `__import__` calls.
- [x] 1.10 Verify: `make -C kit test-capability-admissibility`, `make dist`, and
      `make check-packaging`.
      Done. Kit suite (unit): 109 passed after review 07's fix; review 12's added cases for very large thresholds. `make check-packaging`
      OK.

## 2. Pool-write validation of constrained listing shapes

Delivers the structural split at every pool-write surface. Implements D10's pool-write
bullet and the `resource-pool-management` delta "Listing-shape hint validation". Touches
`kit/resource-pools` (its dependency on the new kit, `hints.py`) and the lock of every
project that locks `kit/resource-pools`. No Helm checks owed: no chart, image input, or
configuration surface changes.

Relocation note (12 F2): the merge of `dev` moved listing-shape hint validation into
`kit/resource-pools-contracts`. The dependency (2.1), the `hints.py` change (2.2), and
2.3's unit cases (`TestListingShapesHint`) now live there; the library integration cases
remain in `kit/resource-pools/tests/integration/test_resource_pool_service.py`.

- [x] 2.1 Add the dependency on `arkhai-kit-capability-admissibility` to
      `kit/resource-pools`, then `make lock` so every dependent lock gains the new wheel.
      A foundation kit below an authority kit is a permitted edge (`ARCHITECTURE.md`, kit
      layers). (D2)
      Done; `make lock` added only the new wheel, to 12 locks (see design.md,
      "Locking against a shared wheelhouse").
- [x] 2.2 `validate_listing_shapes` calls `split_listing_shapes(..., schema=None)` per mode
      in place of `shape_structure_problems`: malformed constraints and conflicting
      duplicates are refused naming each entry; identical entries are accepted; an empty
      list is refused as today. `raw_listing_shapes` keeps passing the value unread. No
      comparison with any storefront's configured default. (D10)
      Done; every pool-write surface already reached it. A problem's location is
      `listing_shapes.<mode>[<entries>].<path>`.
- [x] 2.3 Unit tests in `kit/resource-pools/tests/unit/test_hints.py` for every scenario of
      the delta requirement. Library integration in
      `tests/integration/test_resource_pool_service.py`: the individual create, replace,
      and update surfaces and bulk import refuse alike without changing stored metadata.
      Done: every delta scenario in `TestListingShapesHint`;
      `TestListingShapeConstraintsOnEveryWriteSurface` covers create, replace, patch, and
      bulk for both refusals.
- [x] 2.4 Provisioning integration in
      `provisioning/compute/service/tests/integration/test_pools_api.py`: a conflicting
      duplicate and a malformed constraint are refused through the typed client, asserting
      status and stored state only (`TESTING.md` rejection-path rule).
      Done: a conflicting duplicate on create, a malformed constraint on replace.
- [x] 2.5 Verify: `make -C kit test-resource-pools`, the compute provisioning service's
      integration suite, and `make check-packaging`. Confirm the bare-metal storefront,
      which reads `listing_shapes` only for its presence (`site_reading.py`), is unaffected
      by running its unit suite.
      Done. Resource-pool kit: 301 passed; provisioning service integration: 285 passed;
      bare-metal storefront: 227 passed. `make check-packaging` OK.

## 3. VM domain: stated-shape resolution and the bounded generator

Delivers per-listing resolution of stated shapes and the generator bounded by the
configured default, without yet changing derivation. Implements D3 (every reader splits
through the kit), D5, D9 (tiers, override replacing the hint whole, generated shapes under
the default alone), and D10's generator and identity bullets. Touches `domains/vms/domain`
(`shape_generation.py`, `__init__.py`, its dependency on the kit) and `domains/vms/listings`
(`listing_shapes.py`, `asking_rates.py`, its dependency). No Helm checks owed.

- [x] 3.1 Add the kit dependency to `domains/vms/domain` and `domains/vms/listings`, and
      `make lock`. (D2)
      Done; seven locks gained only the kit and its edges.
- [x] 3.2 Change the `ListingShapeGenerator` protocol to take the default-only
      `ResolvedPolicy` beside the members; `gpu_count_shapes` chooses, per model, the counts
      from one to the largest declared that
      `admissible_values("gpu.count", {"gpu": {"model": m}})` contains. With no
      configured default the output is unchanged. Extend
      `domains/vms/domain/tests/test_shape_generation.py`: bounded, unbounded, minimum
      above every member, two models. (D10)
      Done; `policy` is required (design.md, "The generator"). Also covered: a
      configured minimum, and a constraint on another dimension not bounding the count.
- [x] 3.3 `listing_shapes.py`: stated lists (override, else hint) are split through
      `split_listing_shapes` with the VM schema and the source as the tier label. An
      unreadable base shape anywhere makes the list unreadable (the existing hold). Each
      listing becomes an entry carrying its base `ResolvedShape` and either its
      `ResolvedPolicy` (resolved with the configured default as the lower tier) or the
      problems that make it uncomputable (unreadable constraints, empty range, conflicting
      duplicate). A generated shape's policy is the default alone. The digest stays
      `vm_shape_digest` of the base shape. No code outside the kit reads a constraint.
      (D3, D8, D9, D10)
      Done: `ShapeResolution.listings` holds `ListingShape(shape, policy,
      policy_problems)`; tiers are `storefront_override`, `pool_hint`, and
      `configured_default`. The kit collapses identical stated entries; generated ones
      are still deduplicated locally.
- [x] 3.4 Asking rates match the base shape's digest (`asking_rates.py`); a rate entry's
      shape stays a plain shape, as `vm_shape_problems` already requires. (D10)
      Done with no code change: listing digests were already base-shape digests.
- [x] 3.5 Unit tests in a new `domains/vms/storefront/tests/unit/test_listing_shape_resolution.py`
      (the listings package has no suite of its own; the storefront's unit suite covers
      it): shorthand scalars, a constrained offer, a constraint-only field, an override
      not inheriting the hint's constraints, each uncomputable case, an unreadable base
      shape, and identity unchanged when only constraints change.
      Done, with narrowing, widening, and filling by the configured default, and tier
      labels. The compute schema has no optional attribute, so an attribute constraint
      always leaves the base unreadable; the readable uncomputable cases are an unknown
      key, an undefined field, an empty range, and a conflicting duplicate.
- [x] 3.6 Verify: the VM domain suite, the VM storefront unit suite, and
      `make check-packaging`.
      Done. VM domain: 48 passed; VM storefront unit: 1122 passed, 1 skipped;
      integration: 349 passed; VM buyer: 206 passed. `make check-packaging` OK; mypy
      over the two changed modules: no issues.

## 4. VM derivation and publication

Delivers the publication behavior: per-listing close, inadmissible offers withheld,
reports, and local-table derivation under the configured default. Implements D8, D10
(publication, identity, reports, local tables), and the `storefront-publication` delta
requirements "A VM listing's admissibility resolves per listing", "A VM listing whose
admissibility cannot be computed closes", "VM publication never advertises an inadmissible
offer", and the modified "Every VM listing is a listing shape". Touches
`domains/vms/listings/src/arkhai_vms_listings/reconciler.py` only. No Helm checks owed.

Amended in implementation, with the owner: the key readers and the inventory guard also
take the configured default (design.md, "Key readers take the default"), so section 4
also touches their storefront callers (`publication_loop.py`, `publication_service.py`,
`controllers/admin_controller.py`, `failure_actions.py`, and
`services/listing_source_check.py`).

- [x] 4.1 `PoolHintResolutionSettings` gains the parsed configured default (a
      `Declaration`, or none); derivation passes it to listing-shape resolution and the
      generator. (D9)
      Done: `PoolHintResolutionSettings.admissibility_default`.
- [x] 4.2 `_projected_pool_rows`: a listing whose policy cannot be computed is not
      derived, so reconciliation closes an open listing for it, while the pool's other
      listings publish; a stated listing whose base shape is inadmissible under its policy
      is withheld the same way; an unreadable base shape keeps the existing pool hold.
      Generated shapes are never reported. (D8, D10)
      Done in `_admissible_shapes`, right after the unreadable-list hold; every later step
      reads the admitted shapes only. Amended after review 07 F1: an excluded listing
      closes even when a later rate check holds the pool (design.md, "Excluded listings
      close through a pool hold").
- [x] 4.3 `_SiteDerivationReport` gains `inadmissible_listing_shapes` (tier, shape,
      problems) and `unusable_shape_constraints` (tier, path, problem, each tier's
      conflicting value, or each conflicting entry), logged once per change through
      `_record_site_report` like the existing keys; system status serves them unchanged.
      (D10)
      Done; system status serves the report generically. Round fix (19 F1): every
      unreadable stated-list problem carries its source tier.
- [x] 4.4 `_local_table_shapes` chooses counts from `admissible_values` under the
      default-only policy, as the generator does. (D10, local-table bullet)
      Done, through `gpu_count_shapes` with one synthetic member per row.
- [x] 4.5 `declared_shape_feasibility` judges the override's base shapes. (D10)
      Done with no code change beyond section 3; a test keys a constrained override's
      feasibility by its base shape.
- [x] 4.6 Integration tests in `domains/vms/storefront/tests/integration/test_reconciler_derivation.py`
      (cases in `tests/_reconciler_cases.py`): every scenario of the three added
      requirements and the modified one, including identity kept across a
      constraint-only change, the next reconciliation closing a listing whose offer
      became inadmissible, and local-table derivation under a configured default. Extend
      `test_reconciler_projection.py` so a stored listing's key and the inventory guard's
      re-derivation agree for a constrained shape.
      Done: `TestShapeAdmissibility` (18 cases), one feasibility case, and one projection
      case. These run the reconciler against a real database with no application, so
      "closes" here means reconciliation selects the listing as stale; the application
      evidence is 5.3's (review 08 F1).
- [x] 4.7 Verify: the VM storefront unit and integration suites.
      Done. VM storefront unit and integration: 1491 passed, 1 skipped; after the
      19 F1 fix, unit 1116 passed, 1 skipped, integration 407 passed, and repository
      `make test` exit 0. mypy over the touched modules: six errors, all present before
      the section.

## 5. VM storefront composition: the configured default and the override write check

Delivers `[admissibility.defaults.vm]` and the override contribution's write check.
Implements D9 (the carrier, parsed once, a malformed default stopping startup) and D10's
override-write bullet. Touches `domains/vms/storefront`: `services/publication_terms.py`,
`startup.py`, `settings.toml` (ships none), the configuration template in
`groups/config.py`, `services/vm_pool_override_contribution.py`, and the composition that
constructs the publication loop and the contribution. Owes the Helm check because it
changes the storefront's configuration surface.

- [x] 5.1 Parse `[admissibility.defaults.vm]` once at startup with
      `parse_declaration(tier="configured_default", schema=VM_CAPABILITY_SCHEMA)`; absent and
      empty both mean no default; a malformed table stops startup naming each problem,
      as `_require_readable_family_rates` does. Hand the same `Declaration` to publication,
      the generator's composition, and the contribution. Add a commented example to the
      configuration template; `settings.toml` states none. (D9)
      Amended in section 4: the same `Declaration` also reaches every key reader and the
      inventory guard.
      Done: `publication_terms.parse_configured_admissibility_default()`, called first in
      `server._build_vm_services` (design.md, "Where the default is parsed"); problems
      are named `admissibility.defaults.vm.<path>`. The value rides the container slot
      `resolved_admissibility_default` to every caller; no `admissibility_default=None`
      remains in `src/`. The storefront declares the kit itself; `make lock` added only
      that edge.
- [x] 5.2 `VmPoolOverrideContribution.vocabulary_problems` splits the record's shapes
      through the kit with the VM schema and resolves each against the configured default,
      refusing unreadable base shapes or constraints, conflicting duplicates, an empty
      range, and an inadmissible offer, all before any site call. `judge_shapes` reports
      feasibility for base shapes. (D10)
      Done; refusals name list positions and, for an inadmissible offer, the tier that
      set the bound (design.md, "The override contribution").
- [x] 5.3 Unit tests: a new `tests/unit/test_startup_admissibility_default.py` beside
      `test_startup_family_rates.py`; extend `tests/unit/test_vm_pool_override_contribution.py`.
      Integration: `tests/integration/test_pool_overrides_api.py` covers each of the three
      override-write scenarios through the typed client, asserting the site was not called
      and the stored override is unchanged; `tests/integration/test_publication_loop.py`
      covers a configured default reaching a publication cycle and the new report keys in
      system status.
      Amended after review 08 F1: `test_publication_loop.py` also covers a pool hint's
      constraint closing a listing through a publication cycle.
      Done.
      - Unit: `test_startup_admissibility_default.py` (15 cases, the parser's refusals);
        `test_admissibility_default_composition.py`, at the composition root (an
        unreadable default stops `_build_vm_services` before anything is built, and the
        composed value reaches the container before startup tasks run);
        `test_vm_pool_override_contribution.py` (10 cases).
      - Application integration, `test_pool_overrides_api.py`: four refusals with a
        configured default in force, each asserting 422, no further site call, and the
        stored override unchanged; and, from round 3 (14 F1), a constrained override
        accepted, read back as written, and publishing its base shape.
      - Application integration, `test_publication_loop.py`: a configured default
        bounding a generated pool, withholding a stated offer, and withholding a listing
        whose range it empties, each reported in system status; and a hint constraint
        tightened past a published offer, closed by the next cycle as `reconciliation`.
- [x] 5.4 Helm: run `make helm-values-schema` and confirm the generated schema is
      unchanged (`[admissibility]` is an untyped section, as `[pricing]` is), or run the
      chart render tests if it changed.
      Done: no change to any tracked file, so no render test is owed.
- [x] 5.5 Verify: the VM storefront unit and integration suites, and `make check-packaging`.
      Done. VM storefront unit: 1116 passed, 1 skipped; integration: 407 passed after
      round 3. Repository `make test` exit 0; `make check-packaging` OK. No end-to-end
      scenario configures a default or writes a constrained override, so this section
      has unit and application evidence only.

## 6. End-to-end scenario

Delivers system-level evidence that a constrained stated shape crosses the site,
storefront, and registry boundary as its base shape. Implements D5 and D10 at the system
level. Touches `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`. No Helm
checks owed unless the lane's configuration changes.

- [x] 6.1 Extend the listing-shapes scenario: the pool states a shape with
      `gpu.count {offer: 1, max: 4}` and `memory.gib {max: 512}` through the site's
      operator client; one publication cycle publishes a listing with a GPU count of 1 and
      no `ram_gb`, and the registry listing carries no constraint. Use typed clients only.
      Done: `TestStage08_ShapeConstraints` (marker `e2e_listing_shapes`). 08a patches the
      pool's `listing_shapes` through `SyncResourcePoolClient` and reads the constraints
      back; 08b runs one cycle and asserts one listing with GPU count 1, model L40S, no
      `ram_gb`, `vcpu_count`, or `disk_gb`, and no constraint keys in the storefront's or
      the registry's `listing_resource`. Round fix (16 F1): stage 07c clears any
      override and records `override_cleared`, which 08a requires (design.md,
      "End-to-end staging").
- [x] 6.2 Verify: run the VM lane with `make run-e2e` and
      `make fetch-e2e-logs E2E_RUN_ID=<run>`; the evidence is recorded in 7.9.
      Done by validation: run 38383391257 at `8913fbe0` (stage 08), and run 38460926563
      at `443f9505` (validation 18, stages 00–08 including 07c), both passed.

## 6A. Pilot merge reconciliation

Corrects provisioning transaction boundaries exposed by this pilot's development
merge. This completed corrective work is independent of the remaining
shape-admissibility implementation sequence. The owner-approved boundary and
alternatives are recorded in `design.md`, "Pilot merge reconciliation".

- [x] 6A.1 Fix the provisioning integration fixture's shared-connection race in
      `provisioning/compute/service/tests/integration/conftest.py`: each test uses
      a temporary file-backed database through the production engine factory,
      with independent connections for request and worker sessions. Add
      `tests/integration/test_database_session_isolation.py` to deterministically
      prove that closing a reading session cannot erase another session's replay
      reservation. Run that regression, the bare-metal mock-profile suite, the
      full provisioning-service suite, and required packaging/comment checks.
      The permanent rationale already lives in `ARCHITECTURE.md`'s deterministic
      database-concurrency guidance and `db/database.py`'s file-backed engine rule.
      Done (2026-10-08): the regression failed against the shared connection and
      passes with independent connections; the five bare-metal mock tests and the full
      service suite pass.

- [x] 6A.2 Make preparation join the acceptance transaction: extend
      `kit/fulfillment`'s provider contract and orchestrator, forward its session
      through `provisioning/compute`'s job provider/plan contract and the VM and
      bare-metal plans, and add VM's session-scoped relay allocation with bounded
      savepoint retries. Update the provider import-boundary test for its session
      port, and test allocation rollback/commit and stale-port conflict retries
      in `test_relay_port_allocator.py`. Reuse only released lease rows and begin
      the standalone SQLite writer transaction before scanning mutable leases.
      Refuse relay allocation without the acceptance session.
      Extend the real fulfillment API tests to prove rollback leaves no port or
      acceptance snapshot, and adapt affected unit collaborators. Run fulfillment,
      compute-family, both adapter, and full provisioning-service suites. Promote
      the accepted boundary into the fulfillment spec/architecture, physical
      provisioning spec, and repository architecture named in `design.md`.
      Done. 50 focused replay/relay/fulfillment tests, fulfillment kit 172,
      compute family 222, VM adapter and inventory 29, bare-metal adapter 40, and the
      full service's 677 unit and 462 integration tests pass. Promoted; see the
      design-promotion record.

- [x] 6A.3 Closeout the fixture and allocation fixes: comment hygiene, import placement,
      current-state documentation ownership, concise handoff, unchanged roadmap/campaign status,
      documentation citations, and `make check-packaging`. Record local evidence
      and citation results; keep end-to-end/promotion gates open.
      Done. Comment hygiene, packaging, strict validation, and citations pass; added
      imports are at module level; the four touched permanent documents describe the
      current acceptance boundary. Round fix (20 F1): the conftest fixture header now
      says file-backed, and, at the owner's request, pre-existing history-telling
      comments in `test_fulfillment_persistence.py` and `vm_fulfillment_plan.py` were
      rewritten as invariants. The false `transaction()` docstring is left unowned and
      listed in the index. End-to-end evidence: 7.9.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`. Promotion (7.10) follows the
pre-closeout review, as `AGENTS.md` asks. Worked in that document's order, which runs
packaging (7.8), the pipeline (7.9), and promotion (7.10) before citations (7.7), and
ends with archival (7.11, appended at closeout).

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match;
      read the new kit and every touched module for references to reviews or migrations.
      Confirmed at closeout: `make check-comment-hygiene` OK, and a read of every comment
      the change's commits added found none naming a review, migration, or history. The
      pre-closeout round already rewrote the 6A comments that did (20 F1).
- [x] 7.2 **Import placement.** Review the imports sections 1–5 added or touched. The
      local import of `market_resource_pools` in `listing_shapes.py` stays local for its
      recorded reason (buyers install the listings package without the pool kit).
      Confirmed: the one local import is `market_resource_pools_contracts` in
      `listing_shapes.py`, with its reason in a comment; the only other indented import
      the change added is under `container.py`'s existing `TYPE_CHECKING` block.
- [x] 7.3 **Documentation compliance.** Check every decision's destination against
      `openspec/README.md#documentation-placement`. Verify the design's risk controls
      directly: nothing outside the kit walks a constraint mapping, a `Declaration`, or a
      `ResolvedPolicy`; every `listing_shapes` reader (`grep raw_listing_shapes`,
      `resolve_vm_listing_shapes`, the override contribution) splits through the kit
      before using a shape; no unconditional `admissible_values` answer is cached.
      Done. Normative behaviour goes to the three `spec.md` deltas; rationale to the
      `market-composition` and `storefront-publication` companions; the kit layer, the
      hold-or-close test, and omission to `ARCHITECTURE.md`; configuration and rollback
      to `DEPLOYMENT_AND_CONFIG.md`. Implementation decisions too local for a permanent
      document stay in design.md. Risk controls hold: no `src/` outside the kit reads an
      `offer`/`min`/`max` key or a private attribute of either opaque type; the VM
      readers split through `resolve_stated_shapes` or `split_listing_shapes`, the pool
      write through `split_listing_shapes`, and bare metal only tests the hint's
      presence (D12); the generator's one `admissible_values` call is per model, never
      cached. The permanent `resource-pool-management` Evidence cited
      `kit/resource-pools/tests/unit/test_hints.py`, which the `dev` merge moved to
      `kit/resource-pools-contracts`; both citations corrected.
- [x] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, deferrals, and destinations.
      Done: sections 1–6A compressed and their handoffs removed. Implementation-time
      decisions, review rationale, and lessons that lived only in notes or handoffs moved
      first to design.md, "Implementation decisions"; the rest was duplicated there or is
      resolved by promotion.
- [x] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md` Goal 2, remove the gap row
      "Nothing expresses which shapes a seller will consider…" (now closed), add stated
      constraints and the configured default to the current-state description, and
      correct the sentence saying the seller's feasibility check compares no quantitative
      dimension (the inventory guard checks the published quantity against its source).
      Done, all three; the current state also says negotiation does not yet evaluate the
      policy.
- [x] 7.6 **Campaign index currency.** In `openspec/changes/README.md`: update this
      change's row; remove it from `publish-shape-bounds`'s `Depends on` (its status
      `ready for design` stays); update `negotiation-driven-capacity-resize`'s Notes, whose
      task 2.4 depends on this change (it has begun implementing, so its status stays);
      update the Goal 2 dependency graph. Check each item under design.md's "Findings
      outside this change" against `openspec/changes/` and list the unowned ones in the
      index's unowned-work table for this goal.
      Also settle with the owner (implementation review 08 F3) whether the
      `arkhai_vms_listings` behaviour tests now in `domains/vms/storefront/tests` move to a
      suite of `domains/vms/listings`'s own: open a follow-up change, or record the
      deferral here.
      Done. This row is `in closeout` with its notes rewritten; the Goal 2 graph is
      unchanged, since every edge it draws still holds until archival. The design's
      eleven findings outside this change were checked against `openspec/changes/`: none
      has an owner, and ten, with pre-closeout review 20's `transaction()` docstring and
      the test location below, are listed under "Unowned work found by
      `capacity-shape-envelope`"; the eleventh, the roadmap sentence, is corrected by 7.5.
      Correction: this task's removal of the change from `publish-shape-bounds`'s
      `Depends on`, and any edit to `negotiation-driven-capacity-resize`'s row, are left
      to archive cleanup, which `openspec/README.md#plan-closeout-requirements` part 6
      now assigns them to after the closeout gate.
      08 F3, decided by the owner on 2026-10-14: deferred with no owning change. The
      tests stay in the VM storefront's unit suite, which `make test` runs; a suite of
      the listings package's own is worth its packaging change once a second consumer
      runs its derivation code.
- [x] 7.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=capacity-shape-envelope` and resolve every match.
      Run after promotion: OK, every cited path resolves and none is a tombstone.
      `openspec validate capacity-shape-envelope --strict` (1.14.0): valid.
- [x] 7.8 **Packaging.** Run `make check-packaging` and resolve every failure.
      OK at closeout, every check. `make check-agent-skills` not owed: this change's
      commits touch no `.agents/`, `.claude/`, or `.codex/` file.
- [x] 7.9 **End-to-end pipeline.** Confirm the pipeline passes and record the run, its
      result, and that `test_listing_shapes.py` (6.1) exercises this change. If it cannot
      run for an unrelated reason, record the blocker and its owning change, and treat the
      gated validations as unrun.
      Validation 18: run 38460926563 at `443f9505`, success. e2e-vm 138 passed,
      3 skipped (`test_credits_payment_deal.py`'s readiness guard), 65 deselected;
      e2e-bare-metal 16 passed. All 17 cases of `test_listing_shapes.py` passed: stage
      08 (a constrained stated shape publishes its base shape, no constraint reaching
      the storefront's or registry's listing) and 07c are this change's; stages 00–07b
      are regression evidence. The run names `443f9505`, not the pre-closeout fix commit
      `58fa1004`: the owner waived re-validation at the gate, since that commit changes
      only report text and comments that no scenario reads. No scenario configures
      `[admissibility.defaults.vm]` or writes a constrained override; that behaviour has
      unit and application evidence only (5.3).
- [x] 7.10 **Promotion.** Write the permanent documentation below, then complete the
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
        section 4 derivation tests, and extend the `test_listing_shapes.py` entry with
        its constrained stage (08).
      - `openspec/specs/README.md`: unchanged, since every companion already exists;
        record that disposition.
      - Not promoted here: the negotiation invariant and omitted-dimension policy, which
        `negotiation-driven-capacity-resize` owns.
      Done, each as listed; the three `spec.md` deltas are merged by the archive (7.11),
      none having been synchronized by hand. Beyond the list: `market-composition` and
      `resource-pool-management` Evidence gained the kit's and the hint's tests, and
      `DEPLOYMENT_AND_CONFIG.md` also names the system-status keys. `openspec/specs/README.md`
      unchanged: every companion written already exists. Not done: the kit's module
      docstring still points at `market-composition/spec.md` without a heading anchor,
      as section 1's handoff asked; adding one is a code edit, which closeout does not
      make, and the docstring explains itself without it.
- [x] 7.11 **Archival.** Archive with `openspec archive capacity-shape-envelope -y`
      (1.14.0), merging the deltas; check each merged `spec.md`; point the index row at
      the archived directory; run `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Independent request/worker database transactions | `docs/development/ARCHITECTURE.md#deterministic-database-concurrency-tests` (existing guidance) |
| Local resource claims commit or roll back with acceptance | `openspec/specs/fulfillment/spec.md#requirement-provider-contract`, `openspec/specs/fulfillment/architecture.md#fulfillment-acceptance-and-dispatch-acknowledgement`, and `docs/development/ARCHITECTURE.md#durable-fulfillment-acceptance` |
| Session-scoped relay allocation and safe lease reuse | `openspec/specs/physical-provisioning/spec.md#requirement-relay-port-leases-are-unique-per-relay` |
| D1 Admissibility is the storefront's own policy; a site's constraint is advisory | `openspec/specs/storefront-publication/architecture.md#shape-constraints`; `docs/development/ARCHITECTURE.md#authority-boundaries` (VM listing shapes row) |
| D2 A foundation kit owns admissibility | `openspec/specs/market-composition/spec.md#requirement-capability-shape-admissibility-is-owned-by-one-kit` (archive merge); `openspec/specs/market-composition/architecture.md#capability-shape-admissibility`; `docs/development/ARCHITECTURE.md#kit-layers` |
| D3 Whole shape in, problems out, never unconditional bounds; labelled tiers; the list-level split | `openspec/specs/market-composition/spec.md#requirement-capability-shape-admissibility-is-owned-by-one-kit` (archive merge); `openspec/specs/market-composition/architecture.md#capability-shape-admissibility` |
| D4 Admissible values are an opaque set | `openspec/specs/market-composition/spec.md#requirement-capability-shape-admissibility-is-owned-by-one-kit` (archive merge) |
| D5 Constraints inline and strict | `openspec/specs/market-composition/spec.md#requirement-shape-constraints-are-stated-inline-and-strictly` (archive merge); `openspec/specs/market-composition/architecture.md#capability-shape-admissibility`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides` |
| D6 An omitted dimension is free; D7 an absent constraint commits nothing | `openspec/specs/market-composition/spec.md` (both requirements, archive merge); `openspec/specs/market-composition/architecture.md#capability-shape-admissibility`; `docs/development/ARCHITECTURE.md#omission-states-no-commitment` |
| D8 A listing whose policy cannot be computed closes; the hold-or-close test | `openspec/specs/storefront-publication/spec.md#requirement-a-vm-listing-whose-admissibility-cannot-be-computed-closes` (archive merge); `openspec/specs/storefront-publication/architecture.md#shape-constraints`; `docs/development/ARCHITECTURE.md#holding-or-closing-a-listing-the-storefront-cannot-fully-derive` |
| D9 Per-field merge with the configured default `[admissibility.defaults.vm]`; an override replaces the hint whole | `openspec/specs/storefront-publication/spec.md#requirement-a-vm-listings-admissibility-resolves-per-listing` (archive merge); `openspec/specs/storefront-publication/architecture.md#shape-constraints`; `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides` |
| D10 Publication never advertises an inadmissible offer; the generator, local tables, write checks, identity, reports | `openspec/specs/storefront-publication/spec.md#requirement-vm-publication-never-advertises-an-inadmissible-offer` and `#requirement-every-vm-listing-is-a-listing-shape` (archive merge); `openspec/specs/resource-pool-management/spec.md#requirement-listing-shape-hint-validation` (archive merge); `openspec/specs/storefront-publication/architecture.md#listing-shapes-and-the-storefronts-authority` |
| D11 Destinations confirmed in planning | This record |
| D12 VM only | `openspec/specs/storefront-publication/spec.md#requirement-every-vm-listing-is-a-listing-shape` (archive merge; bare metal unchanged) |
| D13 Buyer disclosure is a separate change | Not promoted: owned by `publish-shape-bounds` |
| Inputs to `negotiation-driven-capacity-resize` | Not promoted: that change's own deltas |
| Rollback procedure (Migration Plan) | `docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides` |
| Implementation decisions | Temporary or local; kept in design.md, "Implementation decisions" |
| Roadmap currency | `docs/development/ROADMAP.md`, Goal 2: gap row removed, current state extended, the feasibility sentence corrected |
| Campaign index currency | `openspec/changes/README.md`: this row's status and notes, "Unowned work found by `capacity-shape-envelope`"; the Goal 2 graph unchanged; dependents' rows left to archive cleanup |
| Capability index | `openspec/specs/README.md` unchanged: every companion already exists |
