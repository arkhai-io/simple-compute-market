# Tasks — a pool declares what it advertises and whether it can be admitted against

No blocking dependency. Prerequisite for `unbacked-listing-publication`.

This change is observable to operators and to nothing else: no listing behaviour
changes until the storefront reads these tags. Its acceptance boundary is that both
declarations exist, are required and validated on every write path, every existing
pool carries both, and one shared resolver exists for consumers to read them
through. `unbacked-listing-publication` wires that resolver into storefront
projection ingestion (its task 4.1b); no task here touches storefront code.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`; for a kit library it means
the library's public service API against a real embedded database, in the library's
`tests/integration`.

Package abbreviations used below:

- `RP` = `kit/resource-pools/src/market_resource_pools/`
- `PS` = `provisioning/compute/service/src/compute_provisioning_service/`
- `PT` = `provisioning/compute/service/tests/`
- `AC` = `domains/apicredits/service/src/`

## 1. Declarations

- [ ] 1.1 Add `advertisable_modes` to the shared policy-tag vocabulary with the same
      shape rule as `deliverable_modes`: a JSON-compatible list of unique, non-empty
      strings without surrounding whitespace, with set semantics. Factor the existing list-shape check
      in `declared_deliverable_modes` into one private helper both tags use, so the
      rule cannot drift; `deliverable_modes`' behaviour and messages are unchanged.
      Add `pool_advertises_offering_mode` as the membership predicate, mirroring
      `pool_delivers_offering_mode`.
      Files: `RP/hints.py`, `RP/__init__.py` (exports).
- [ ] 1.2 Make an empty advertisable declaration authorize no mode, never widened
      by a default. Files: `RP/hints.py`.
- [ ] 1.3 Add `capacity_backing` with values `backed` and `unbacked`, as module
      constants plus a closed set. Reject any other value, including non-strings.
      Do not resolve a malformed or absent discriminator to a default — that is the
      one behaviour that would let a listing claim an admission authority it does
      not have. Files: `RP/hints.py`, `RP/__init__.py`.
- [ ] 1.3a Fix `capacity_backing` at creation. `replace_pool` and `update_pool`
      compare the supplied value with the stored one inside their transaction, before
      any mutation, and raise `PoolValidationError` naming both values. Document
      import checks each entry for an existing pool while reconciliation is planned
      (`_calculate_reconciliation` or a helper it calls, with the session it already
      holds): `import_pools_in_session` raises, and `validate_pools` returns
      `valid=False` with a `capacity_backing_immutable` problem at
      `pools[i].policy_tags.capacity_backing` and no diff.
      Files: `RP/service.py`.
- [ ] 1.3b Require both tags on every write. Add a `model_validator(mode="after")`
      to `PoolCreate` and `PoolReplace`, and to `PoolUpdate` when `policy_tags` is
      supplied, calling the shared validation of 1.3c and raising one `ValueError`
      listing every problem. Document validation reports each missing tag per entry
      with code `missing_declaration`. Nothing defaults, preserves, or merges: the
      service keeps assigning the supplied map wholesale, exactly as today.
      Files: `RP/pools.py`, `RP/service.py` (`_validate_document`).
- [ ] 1.3c Implement one shared validation returning structured problems
      `(tag, code, message)` for: each tag's presence and shape, the backed subset
      rule, and the unbacked empty-deliverable rule. Codes: `missing_declaration`,
      `invalid_advertisable_modes`, `invalid_capacity_backing`,
      `advertisable_exceeds_deliverable`, `unbacked_pool_delivers`. A malformed
      `deliverable_modes` is reported by the existing validator and suppresses the
      cross-tag checks rather than raising twice. Call it from the models (1.3b),
      from `_validate_document` (mapping each problem to a `PoolValidationProblem`
      at `pools[i].policy_tags.<tag>`), and from
      `_require_valid_policy_tag_hints`, so the service validates what it persists
      even for a model built without validation. Files: `RP/hints.py`, `RP/pools.py`,
      `RP/service.py`.
- [ ] 1.3d Canonical export emits `policy_tags` verbatim, so with 1.3b every
      exported pool carries both tags without export code changing; prove it in 4.3a
      rather than adding export logic. Files: none expected in `RP/service.py`; if
      export needs a change, that is evidence the stored state escaped 1.3b.
- [ ] 1.3e Name each problem's path in the error document import raises: join
      `f"{path}: {message}"` rather than messages alone, in both `import_pools` and
      `import_pools_in_session`, so a service refusing a seeded document names the
      pool. Update any existing test asserting the old message text.
      Files: `RP/service.py`, affected tests under `kit/resource-pools/tests/`.
- [ ] 1.4 Carry both tags through create, replace, patch, bulk import, projection,
      and canonical export on the existing policy-tag channel. Projection copies
      `policy_tags` verbatim (`PS/services/capacity_inventory.py`,
      `kit/site/src/market_site/projections.py`); neither file changes.
- [ ] 1.5 Leave `deliverable_modes` untouched — meaning, derivation, migration, and
      every execution recheck at reservation, scheduling, and provider dispatch. No
      edit to `kit/site/src/market_site/ledger.py`,
      `kit/fulfillment/src/market_fulfillment/scheduler.py`,
      `kit/fulfillment/src/market_fulfillment/fulfillment.py`, or
      `_derive_pool_deliverable_modes` in `PS/db/migrations.py`. A diff touching
      those paths means this change has exceeded its boundary.
- [ ] 1.6 Update the module docstring in `RP/hints.py` to describe both new tags,
      the two cross-tag rules and why each exists, and that absence is reported
      rather than defaulted. State the rationale locally; do not cite this change.

## 2. Cross-tag rules and shared resolution

- [ ] 2.1 Enforce on write that a pool declaring `capacity_backing: backed` has an
      advertisable set that is a subset of its deliverable set, rejecting a write
      that breaks the relation from either side — widening advertisable or narrowing
      deliverable — without rewriting the other declaration. Every write carries the
      complete map (1.3b), so the check needs only the supplied tags.
      Files: `RP/hints.py` (in the 1.3c validation).
- [ ] 2.2 Expose `resolve_pool_declarations(policy_tags) -> PoolDeclarations`, a
      frozen dataclass of `advertisable_modes: frozenset[str]` and
      `capacity_backing: str`, sharing the 1.3c validation. It raises
      `PoolDeclarationError(ValueError)` carrying the structured problems, and the
      subclass `MissingPoolDeclarationError` when the only problems are absent tags,
      so a caller can tell absence from malformation with `except` order alone. Do
      not apply a producer-version rule inside it; that is the consumer's.
      Files: `RP/hints.py`, `RP/__init__.py`.
- [ ] 2.3 Leave an `unbacked` pool's advertisable set independent of its deliverable
      set. Do not require a deliverable proof anywhere in that path — removing that
      requirement is what this change exists to do. Files: `RP/hints.py`.
- [ ] 2.4 Enforce on write, and in the resolver, that a pool declaring
      `capacity_backing: unbacked` has an empty deliverable set. Add no site-side
      pool read: the existing execution rechecks already refuse a pool delivering
      nothing. Files: `RP/hints.py`.

## 3. Migration, seeding, and complete emission

- [ ] 3.1 Add `Migration("20260922_001_pool_advertisement_and_backing", ...)` at the
      end of `MIGRATIONS`. For every `resource_pools` row, read `policy_tags` with
      the existing `_json_mapping`, resolve the deliverable set with
      `declared_deliverable_modes` (a malformed value raises `SchemaDriftError`
      naming the pool rather than being guessed), overwrite `advertisable_modes`
      with that set sorted and `capacity_backing` with `backed`, and log
      `[MIGRATION] Derived advertisement and backing for pool %s: advertisable=%s
      backing=backed` at INFO. Runs in one transaction, like its predecessor.
      Append the new ID to the expected-migrations list.
      Files: `PS/db/migrations.py`, `PT/unit/test_database.py`.
- [ ] 3.1a Do the same for the API-credits service: append a migration to
      `_MIGRATIONS` overwriting both tags on every row of its `resource_pools`, and
      make the `default` pool seed in `run_migrations` write
      `advertisable_modes: [api_credits]` and `capacity_backing: backed` beside its
      existing `deliverable_modes`. Update the applied-ID expectation.
      Files: `AC/db/migrations.py`, `AC/db/database.py`,
      `AC/tests/unit/test_migrations.py`.
- [ ] 3.1b Update every in-repository pool writer to carry both tags:
      - `kit/fulfillment/tests/integration/test_scheduler_host_requirement.py`,
        `kit/fulfillment/tests/unit/test_fulfillment.py`,
        `kit/fulfillment/tests/unit/test_fulfillment_persistence.py`,
        `kit/fulfillment/tests/unit/test_scheduler.py`;
      - `PT/integration/conftest.py` (the directly-seeded `default` pool, which
        declares `[bare_metal, vm]`, gains the same advertisable set and `backed`),
        `PT/integration/test_capacity_api.py`,
        `PT/integration/test_capacity_definitions_api.py`,
        `PT/integration/test_fulfillment_api.py`,
        `PT/integration/test_host_requirement_api.py`,
        `PT/integration/test_scheduling_composition.py`, and the existing cases in
        `PT/integration/test_pools_api.py`;
      - any other `PT/unit/` test inserting `ResourcePool` rows that a startup path
        under test then reads (`services/test_capacity_definitions_startup.py`,
        `services/test_definition_document_restart_safety.py`), confirmed by running
        them;
      - `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`:
        `register_e2e_pool` creates with `advertisable_modes` equal to its
        `deliverable_modes` and `capacity_backing: backed`, and adds both to the
        `wanted` map it reconciles an existing pool against;
      - `docs/bare-metal-seller-quickstart.md`: the pool document example declares
        `advertisable_modes: [bare_metal]` and `capacity_backing: backed`, with one
        sentence that both are required.
      `helm/charts/provisioning/values.yaml` ships `pools: {}` and needs no change;
      its schema types `pools` as an object and does not validate entries.
- [ ] 3.2 Refuse service start on invalid declarations:
      - Provisioning: add `ResourcePoolService.stored_declaration_problems(db)`
        returning `(pool_id, problem)` for every stored pool failing the 1.3c
        validation, and a startup step `verify-pool-declarations` placed immediately
        after `import-pool-definitions`, raising one error that names every failing
        pool. A changed seeded document already fails loudly through
        `import_pools_in_session` (with 1.3e naming the pool); an unchanged one is
        not re-applied and the stored-state check covers it.
        Files: `RP/service.py`, `PS/app_runtime.py`.
      - API credits: after `apply_schema_migrations` in `run_migrations`, resolve
        every stored pool through the shared resolver and raise naming each failing
        pool. Files: `AC/db/database.py`.
- [ ] 3.3 Confirm no existing deployment's advertising surface or admission
      behaviour changes on upgrade. Verify by comparing resolved values before and
      after migration across a fixture covering the system-owned `default` pool, a
      proved single-mode pool, a pool proving nothing, and a pool holding opaque
      values under the new keys. Files: the 4.6 test.

## 4. Validation

- [ ] 4.0 Move `kit/resource-pools/tests/unit/test_resource_pool_service.py`, which
      runs the service against a real embedded database, to
      `kit/resource-pools/tests/integration/test_resource_pool_service.py`, as
      `docs/development/TESTING.md` requires of a touched library test of that
      kind; tombstone the old path. Change the kit's `test` target to run both
      directories (`pytest -q`), matching `kit/site/Makefile`, so the aggregate
      contract keeps covering it. Files: both test paths, `kit/resource-pools/Makefile`.
- [ ] 4.1 **Unit.** Exhaustive declaration and resolver cases for both tags: valid,
      absent, empty, malformed (non-list, non-string, blank, padded, duplicate,
      unknown backing, non-string backing), the backed subset rule broken from each
      side, an unbacked pool with a non-empty deliverable set, missing-versus-
      malformed discrimination in the resolver, and the model validators on all
      three pool models including `PoolUpdate` without `policy_tags`.
      Files: `kit/resource-pools/tests/unit/test_hints.py`, new
      `kit/resource-pools/tests/unit/test_pool_models.py`.
- [ ] 4.1a **Integration (library).** The same rule set asserted identically through
      the service's create, replace, patch, and document validation paths; backing
      immutability on replace, patch, import, and validate-only; import error text
      naming the path; and `stored_declaration_problems` on rows written directly.
      Files: `kit/resource-pools/tests/integration/test_resource_pool_service.py`.
- [ ] 4.2 **Integration.** An operator creates an unbacked pool declaring an
      advertisable mode, an empty deliverable set, and the configuration-free
      `bare_metal.ansible` provider, through the real pool administration API and
      its canonical client. Register `BareMetalPoolConfigHandler` beside the Ansible
      handler in the integration fixture's `ResourcePoolService`, mirroring a
      composition carrying both adapter bundles. The claim is not that a model
      accepts the value — it is that the real administration path does not demand
      fake execution configuration. Files: `PT/integration/conftest.py`,
      `PT/integration/test_pools_api.py`.
- [ ] 4.3 **Integration.** Through the canonical pool client: create, replace, patch,
      and bulk import each round-trip explicit declarations; and each **omitting**
      either tag is refused with a problem naming it and leaves the pool unchanged.
      Construct the omitting request below the typed model where the model would
      refuse to build it, so the assertion is on the service's response, not a
      client-side exception. Files: `PT/integration/test_pools_api.py`.
- [ ] 4.3a **Integration.** A document predating the declarations fails validation
      per entry and imports nothing; canonical export emits both tags for every pool
      and re-imports as unchanged. Files: `PT/integration/test_pools_api.py`.
- [ ] 4.4 **Integration.** A backed pool's widened advertisable declaration, and a
      narrowing of its deliverable set below it, are each rejected on write.
      Files: `PT/integration/test_pools_api.py`.
- [ ] 4.5 **Integration.** A malformed backing value is rejected on write, and an
      unbacked pool with a non-empty deliverable set is rejected on write.
      Files: `PT/integration/test_pools_api.py`.
- [ ] 4.5a **Integration.** A replace, patch, or imported entry changing an existing
      pool's backing is rejected, the pool's backing survives, and validate-only
      reports the problem. Files: `PT/integration/test_pools_api.py`.
- [ ] 4.6 **Migration suite.** Migration derives both values on a database written
      by the previous version, including the API-credits service's, and the
      resolved values are unchanged from before; covers the 3.3 fixture, clobbering
      of opaque prior values, INFO evidence, and a malformed deliverable set
      raising `SchemaDriftError`. Placed with the services' existing migration
      suites, which run migrations against a real database from `unit/`.
      Files: new `PT/unit/test_pool_advertisement_backing_migration.py`,
      `AC/tests/unit/test_migrations.py`.
- [ ] 4.6a **Startup.** The `verify-pool-declarations` step refuses a stored pool
      without declarations and names it; a changed definition document omitting them
      is refused with the pool named and no digest recorded; an unchanged document
      over valid state still starts. The API-credits bootstrap refuses a stored pool
      without declarations. Files: new
      `PT/unit/services/test_pool_declaration_startup.py`, beside the existing
      definition-document startup suites; `AC/tests/unit/test_migrations.py`.
- [ ] 4.7 **Integration.** A projection from the migrated producer carries both tags
      on every pool it projects, and each resolves through the shared resolver — the
      property `unbacked-listing-publication`'s skew rule depends on and cannot
      verify from its own side. Files: `PT/integration/test_capacity_api.py`, which
      already asserts pool metadata on the resource-pool projection.
- [ ] 4.8 Run the resource-pool kit, fulfillment kit, provisioning service, and
      API-credits service suites, plus `docs/development/TESTING.md`'s pool
      offering-mode enforcement coverage, and confirm no execution-path assertion
      changes. Then run `make check-reinit`; `market_resource_pools`' version is not
      bumped, so every consumer's `reinit` must reinstall it from `.dist`, and any
      gap it reports is resolved before the fileset is returned.
- [ ] 4.9 **Executor-default inventory.** `docs/development/TESTING.md` makes this
      part of closeout for changes to the pool offering-mode boundary: search pool
      writers, seeds, and readers for default arguments, `or` fallbacks, and
      `.get(..., default)` reads of either new tag, and record that none resolve an
      absent declaration to a value.

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why advertisement does not require a
      delivery proof and why backing fails closed, not which review found the gaps.
- [ ] 5.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular import
      or documented lazy-load reason exists. Verify against the real test suite.
- [ ] 5.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table, and re-read
      `docs/development/ARCHITECTURE.md`'s Resource Pool term, "Resource pools"
      section, and the authority-boundaries row for pool deliverable-mode
      authorization, to decide whether the second mode declaration belongs in the
      permanent map or is subsystem detail. Record the disposition either way
      rather than leaving the box unchecked. Also promote:
      - `docs/development/TESTING.md` "Pool Offering-Mode Enforcement": which suite
        owns declaration shape, cross-tag rules, the resolver, migration, and the
        load-time check;
      - `docs/development/DEPLOYMENT_AND_CONFIG.md` "Definition documents": a pool
        document must declare both tags on every entry, and the service refuses to
        start on a changed document or stored pool that does not;
      - `openspec/specs/resource-pool-management/spec.md`'s Evidence section: the
        new and moved test files;
      - `openspec/specs/resource-pool-management/architecture.md`: a short section
        on why advertisement and delivery are separate declarations and why an
        unbacked pool delivers nothing.
- [ ] 5.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, the derivation results from 3.1 and 3.1a, the 4.9 inventory result,
      and the revisit trigger for refusing an unbacked pool with a non-empty
      deliverable set. Drop the per-task file lists once the promotion record and
      evidence section carry the durable pointers.
- [ ] 5.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table in
      `docs/development/ROADMAP.md` and absorb the result into that goal's
      current-state prose.
- [ ] 5.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`, including that
      `unbacked-listing-publication` is no longer blocked on this change and now
      owns wiring the shared resolver into storefront ingestion.
- [ ] 5.7 **Promotion.** Promote `capacity-backed` and `unbacked` to
      `docs/development/ARCHITECTURE.md`'s Terms table now that a pool can declare
      backing and the concept is true, and complete the design-promotion record
      below. The listing-level boundary statements stay with
      `unbacked-listing-publication` until that change makes them true.
- [ ] 5.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=pool-declared-advertisement-and-backing` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 5.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| `capacity-backed` / `unbacked` defined; backing means an admission authority exists, not that hardware does | `docs/development/ARCHITECTURE.md#terms` |
| Advertisement authorization and delivery authorization are separate declarations | `openspec/specs/resource-pool-management/spec.md` |
| A backed pool's advertisable set is a subset of its deliverable set; an unbacked pool's is independent | `openspec/specs/resource-pool-management/spec.md` |
| A malformed backing value fails closed and never resolves to a default | `openspec/specs/resource-pool-management/spec.md` |
| An unbacked pool's deliverable set is empty, keeping it out of every capacity path without a site-side backing read | `openspec/specs/resource-pool-management/spec.md` |
| Both declarations are required on every write; nothing is defaulted, preserved, or merged | `openspec/specs/resource-pool-management/spec.md` |
| Seeded or stored pools lacking valid declarations stop service load | `openspec/specs/resource-pool-management/spec.md` |
| Readers of projected declarations resolve them through one shared resolver | `openspec/specs/resource-pool-management/spec.md` |
| Backing is fixed at pool creation; moving between backed and unbacked supply is a second pool with migrated resources | `openspec/specs/resource-pool-management/spec.md` |
| A producer emitting these tags emits them on every pool it projects | `openspec/specs/resource-pool-management/spec.md` |
| Existing pools are migrated to an advertisable set equal to their proved deliverable set and `backed` backing, overwriting any prior value | `openspec/specs/resource-pool-management/spec.md` |
| Advertisement and delivery are separate declarations; an unbacked pool delivers nothing (rationale) | `openspec/specs/resource-pool-management/architecture.md` |
| Suite ownership for declaration shape, cross-tag rules, resolver, migration, and load-time check | `docs/development/TESTING.md#pool-offering-mode-enforcement` |
| Pool definition documents must declare both tags; the service refuses to start otherwise | `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` |
| Storefront ingestion of the resolver is wired by the consuming change | Temporary — `unbacked-listing-publication` task 4.1b; no permanent destination |
| Declaration validation lives in the pool models; immutability stays a service check | `openspec/specs/resource-pool-management/spec.md` (shared validation requirement) |
