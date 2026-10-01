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
ground as 3b. The system evidence that unbacked supply carries a comparable rate
(7.13) is transferred to the changes that make unbacked supply publishable; see
7.13.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Settled decisions to confirm against code

No decision gate remains open. The tasks below confirm the code facts
each decision rests on still hold, and stop rather than proceed if one has moved.

- [x] 1.1 Confirmed: `market_alkahest.schemas.PER_UNIT_SECONDS` holds exactly
      `{"hour": 3600}`.
- [x] 1.2 Confirmed: `SettlementPublicationClause` (`kit/settlement-runtime/src/market_settlement_runtime/publication.py`)
      expresses `asset: str` (trimmed, non-empty) and `rate: str | None` validated
      against `_DECIMAL_RATE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")` —
      positive decimal text without an exponent. Reused for the asking-rate
      amount contract in 3.2.
- [x] 1.3 Confirmed: every settlement-carrier asset filter in
      `core/registry/filter-spec.yaml` (`token`, `token_exclude`, `mechanism`) is
      declared `op: in` / `op: not_in` — equality-family ops only, nothing
      range-like.
- [x] 1.4 Confirmed: `kit/contact-exchange/src/market_contact_exchange/settlement_config.py`'s
      `contact_option_builder` raises `ValueError("contact exchange declines
      scalar rates")` when its clause carries a rate, and always publishes
      `rates: []`.
- [x] 1.5 Confirmed: `kit/pool-overrides/src/market_pool_overrides/records.py`'s
      `PoolOverrideRecord` carries `listing_shapes` as a whole-list replacement,
      and `domains/vms/listings/src/arkhai_vms_listings/listing_comparison.py`'s
      `TERM_RESOURCE_FIELDS`/`compare_listing`/`refreshed_listing_resource`
      refresh named term fields in place.
- [x] 1.6 Confirmed: `core/registry/src/core_registry/api/validate_routes.py`'s
      `/api/v1/listings/validate-publish` is the only route that validates the
      full `listing_shape`; its own comment states "A shape opinion that only
      the dry run holds is advisory," i.e. the publish boundary does not
      re-enforce it. No publish-boundary enforcement has been added since
      `design.md` was written.

## 2. Generic registry prerequisite

Nothing in this section names a rate, an asset, a period, or any compute field.

- [x] 2.1 `decimal_text` joins `ValueType` in
      `core/registry/src/core_registry/api/filter_spec.py`.
- [x] 2.1a `core/registry/src/core_registry/api/filter_eval.py`: `_coerce_scalar`
      parses `decimal_text` bounds to `Decimal`; `_Range` bounds admit `Decimal`;
      `number` is unchanged.
- [x] 2.1b `Criterion` carries the declaration's `value_type`; for `decimal_text`,
      `evaluate` coerces each resolved listing value from decimal text and drops
      one of the wrong shape (a JSON number included), so `on_missing` decides it.
      Range evaluation admits `Decimal`.
- [x] 2.1c `core/registry-client/src/registry_client/query.py` maps `decimal_text`
      to `QueryValueType.DECIMAL`; rendering already exact.
- [x] 2.1d A registry still refuses a spec naming a value type it does not
      implement (closed `Literal`, `extra="forbid"`); no code needed.
- [x] 2.2 `FilterDecl.requires: list[str]`, default empty.
- [x] 2.2a `load_filter_spec` refuses a `requires` target that is undeclared or
      the declaration itself, and any cycle (`_check_requires_acyclic`).
- [x] 2.2b `build_criteria` refuses a supplied filter whose co-requirements are
      not all supplied, before building any criterion, as `strict.<n>` is
      resolved before the criterion loop. One-directional.
- [x] 2.2c `core/src/market_core/query_dsl.py`: `FieldDescriptor.requires` (query
      names); a descriptor requiring itself is refused at construction, an
      undeclared target in `_descriptor_maps`, and `validate_query` refuses a
      missing co-requirement as `missing_co_requirement` positioned at the
      comparison that needs it. `field_reference_json` and
      `render_field_reference` name co-requirements only when declared, so
      existing help output is unchanged.
- [x] 2.2d The registry client reads `requires` per declaration and resolves the
      filter names to query names once every declaration is read
      (`_resolve_requires`); an undeclared target is a `FilterVocabularyError`.
- [x] 2.2e **Decided in implementation:** an empty `requires` is omitted from both
      the etag input and the served body (`_dump_filter`), so the normative claim
      holds exactly: no specification declaring no co-requirement changes
      serialization or etag. The existing precedent test built its expected
      payload from the model's own dump and would have silently absorbed the new
      key; it now drops that key explicitly and also pins the literal digest.
      No version bump or relock: same-version internal wheels are reinstalled by
      `reinit` and no package requirement changed
      (`docs/development/BUILD_AND_PACKAGING.md`).

## 3. Declaration, resolution, and publication

Three planning premises moved during implementation; each is recorded at the
task it changed.

- [x] 3.1 `kit/resource-pools/src/market_resource_pools/asking_rates.py` (new):
      `ASKING_RATES_POLICY_TAG`, `validate_asking_rates` (structure only:
      mapping of mode to list; each entry exactly `shape`, `amount`, `asset`,
      `period`; shape well-formed; amount positive decimal text in the
      settlement clause's grammar; asset and period trimmed non-empty tokens),
      and `raw_asking_rates`. An empty mode list is valid and prices nothing.
      Exported from the package.
- [x] 3.1a Both pool-write surfaces in `service.py` call it: the shared
      `_require_valid_policy_tag_hints` and the bulk-import loop
      (`invalid_asking_rates` at `.policy_tags.asking_rates`).
- [x] 3.2 **Amended.** The value contract is `AskingRate` in the same module.
      The accepted periods are a local constant, `ACCEPTED_ASKING_RATE_PERIODS`,
      held equal to `PER_UNIT_SECONDS` by a parity test in the VM storefront
      suite (`tests/unit/test_asking_rate_period_parity.py`), which installs
      both packages. Importing `market_core` into `kit/resource-pools` would
      have changed its requirements and forced relocks across every consumer;
      the design already makes the rule local with parity checked, not
      inherited.
- [x] 3.3 **Amended.** `kit/pool-overrides`: `asking_rates` on
      `PoolOverrideRecord` (an empty list accepted, unlike shapes and clauses;
      an override stating only rates states something), in `_JSON_COLUMNS`, on
      `StoredPoolOverride`, and added by a second, additive, idempotent
      migration (`20261001_001_pool_override_asking_rates`) that VM's chain
      composes unchanged. The record does not check entry structure: that would
      add a `resource-pools` dependency to a kit whose dependency set
      `ARCHITECTURE.md` fixes. Each market's contribution judges rates instead,
      through the shared resolver, which also catches vocabulary, period, and
      duplicate problems at the write.
- [x] 3.4 **Amended.** Resolution is `resolve_asking_rates` in
      `kit/resource-pools`, not VM's `pricing_resolution.py`: bare metal reuses
      it and cannot import VM. It is generic over each domain's shape digest and
      vocabulary: override, else pool declaration, else none; an unreadable tier
      never falls through; `unpublished()` names priced shapes no listing has.
      VM binds it in `arkhai_vms_listings/asking_rates.py`
      (`resolve_vm_asking_rates`, keyed by `vm_shape_digest`, listing
      identity's digest); `reconciler.py` resolves it right after shapes and
      carries `asking_rates_by_digest` on each row, from which
      `available_compute_slices` gives each candidate its own shape's rate.
      `_site_pool_overrides` and `vm_override_view` carry the override's rates.
      Unpublished priced shapes go to the derivation report
      (`unpublished_asking_rates`) and are logged. No configuration default.
- [x] 3.5 An unreadable declaration or override holds the pool and is reported
      (`unreadable_asking_rates`), as unreadable shapes are.
- [x] 3.6 `arkhai_vms/storefront_adapter.py` publishes
      `listing_resource.asking_rate` from the candidate; it reaches no shape
      digest or derivation key. **Found in implementation:** VM's
      `ComputeResource` (`arkhai_vms_listings/models.py`) ignores undeclared
      fields, so the stored and published listing silently lost the rate; only
      the app-level tests could see it. It now declares `asking_rate`
      (`PublishedAskingRate`) and omits it from serialization when unset, so an
      unpriced listing publishes no field (the compute schema types it as an
      object) and a withdrawn rate refreshes to a listing without one.
- [x] 3.7 `asking_rate` joins `TERM_RESOURCE_FIELDS` in
      `arkhai_vms_listings/listing_comparison.py`; a change or removal refreshes
      in place.
- [x] 3.8 Bare metal, through the same resolver:
      - `arkhai_bare_metal/shapes.py` owns `bare_metal_shape_digest` and
        `bare_metal_shape_problems` (compute-family vocabulary), so the
        storefront adds no direct dependency on `arkhai_compute` or the
        capability-shape kit;
      - `arkhai_bare_metal_storefront/site_reading.py` resolves each pool's
        rates (`resolve_bare_metal_asking_rates`), takes an optional
        per-pool override rate list for 3b, and marks an admitted pool whose
        rates cannot be read as held in the admission map classification
        already obeys;
      - `classify_bare_metal_resources` attaches each candidate's own shape's
        rate; `BareMetalListing` declares `asking_rate`
        (`BareMetalAskingRate`), persisted with `exclude_none`;
      - `asking_rate` joins bare metal's `TERM_RESOURCE_FIELDS`;
      - `publication.py` holds with reason `asking_rates_unreadable` and
        reports `asking_rate_shape_unpublished`.
- [x] 3.9 Confirmed by reading: neither VM's nor bare metal's
      `settlement_composition.py` reads a published listing field, and nothing
      in VM settlement or negotiation, or the bare-metal domain, references the
      rate. 7.11 asserts it at the app level.

## 3b. Bare metal joins the site-scoped override store

Baseline from `bare-metal-listing-shapes`' design review, which moved this work
here; see "Bare metal joins the site-scoped override store" in `design.md`.

- [x] 3b.1 `kit/pool-overrides`:
      - `route_service.py` (new): `PoolOverrideRouteService` with `replace`
        (accepts a validated record or a raw mapping, refusing an invalid body
        with 422), `read` (a whole address reads one, 404 when absent; otherwise
        a list), and `delete` (refuses a partial address with 400); a malformed
        address component is 400; no service composed is 503. Every refusal is a
        `PoolOverrideRouteError` carrying its status, as
        `kit/contact-exchange`'s route service does;
      - `PoolOverrideService` accepts `None` for `refresh_site` and
        `wake_publication`;
      - unit tests over a service double:
        `kit/pool-overrides/tests/unit/test_route_service.py`;
      - the delete path also guards its wake, which the optional effect needs;
      - **Decided in implementation: no version bump.** The kit's additions are
        backward compatible and its requirements are unchanged, so a same-version
        wheel is what `docs/development/BUILD_AND_PACKAGING.md` reinstalls and
        `make check-locks` accepts. A bump would also force relocking VM's
        storefront, whose resolution this environment cannot reproduce (its RL
        extra's index host is unreachable here), to no behavioural end. The
        bare-metal storefront pins `arkhai-kit-pool-overrides==0.2.0` as VM does.
      - the no-cache, no-loop composition is exercised end to end by bare
        metal's own integration tests (3b.5), which is the storefront that
        needs it.
- [x] 3b.2 `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`:
      the three handlers bind the route service and translate its error to an
      `HTTPException`. VM keeps FastAPI's typed record body, so its 422 shape is
      unchanged. VM's override integration, client-parity, CLI, and admin tests
      pass unchanged (100).
- [x] 3b.3 Bare-metal storefront:
      - `pool_overrides.py` (new): `BareMetalPoolOverrideTerms`
        (`min_duration_seconds`, `max_duration_seconds`, ordered);
        `BareMetalPoolOverrideContribution` refusing shapes and judging terms
        and rates through the same function publication reads a stored
        override with, `judge_shapes` empty; `read_bare_metal_pool_overrides`
        (an undecodable or unreadable stored override carries its problems);
        `record_accepted_generation` and `accepted_site_projection`;
      - `migrations.py`: `bare-metal-storefront-0011-accepted-site-generations`;
        `sqlite_client.py` composes the kit's migrations before it;
      - `publication.py`: each run reads overrides once, records every site
        generation it accepts, passes override rates and problems to
        `read_site_pools`, holds with `pool_override_unreadable`, and carries a
        pool's override to its candidates as plain values;
      - `publication_composition.py`: a candidate's override clauses replace the
        configured clauses, and its bound the configured bound;
      - `runtime.py`: `pool_override_service()` composes the kit service with no
        after-write effects and the accepted-generation projection as status
        source; `None` without sites;
      - `api.py`: `PUT`/`GET`/`DELETE` on the kit's path, authenticated through
        `_admin` with the kit's `pool_override_contract`, delegating to the route
        service; administrator system status reports `pool_overrides`
        (`models.py`);
      - `pyproject.toml` requires the kit; `uv.lock` relocked (adds only the
        kit; no environment path recorded).
- [x] 3b.4 `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/pool_override_cli.py`
      (new), registered in `cli.py` as `pool-override`: `set --file`, `get`,
      `list`, and `delete` over the kit's `SyncPoolOverrideClient`, `--mode`
      never defaulted, `--pool` requiring `--site`, a refusal exiting 1 with its
      message. It connects to `--storefront-url`, else
      `BARE_METAL_STOREFRONT_PUBLIC_URL`, else `http://localhost:8000`. It signs
      with `runtime.storefront_signer_from_environment`, extracted from
      `build_runtime_from_environment` so the server and the command resolve one
      identity from the same inputs. **Defect found by the end-to-end run:** the
      extraction left six later reads of the removed local `identity_config` in
      `build_runtime_from_environment`, so the server could not start. The unit
      suites construct the runtime directly and never call that function. Fixed
      by binding the principal from the resolved signer, which resolves only when
      it owns the configured principal; `tests/test_runtime_environment.py` now
      builds the runtime from its environment and refuses a credential that does
      not own the identity. Heavy imports stay inside the command, as
      its sibling commands keep theirs. No infeasible-shape warning: an override
      here states no shapes. Tests: `tests/test_pool_override_cli.py`.
- [x] 3b.5 `domains/bare_metal/storefront/tests/test_pool_overrides_api.py`
      through the kit's typed client against the running app: replace, read,
      list, delete; refusal (422) of shapes, an unknown term, bounds out of
      order, an unreadable rate, and an unconfigured site, each storing
      nothing; 404 for a pool the live site lacks; status `unknown`, `applied`,
      `orphaned`, and `site_unconfigured`; a signed non-administrator refused.
      `tests/test_publication_cycle.py`: a run records its accepted generation;
      an override's rate and minimum duration refresh the listing in place; an
      undecodable stored override holds its pool. Not covered: an unreachable
      site (the kit's own suite covers its 503), and an override's clauses
      reaching a listing, which needs the settlement composition the cycle
      harness replaces; that belongs with 3b.6.
- [x] 3b.6 Written; runs in CI.
      `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py`
      gains stages 05b–05d on the reinstated listing: a pool-declared rate
      refreshes it in place and a rate query compiled from the registry's own
      specification finds it, at and only at its bound, by both bound names; a
      storefront override through the kit's typed client replaces the rate and
      the maximum duration and reports `applied`; deleting it restores the
      pool's rate. The machine's rate key is the domain's own
      `derive_bare_metal_shape`. The module collects in the e2e environment (11
      stages). An override's clauses reaching a listing are not asserted: the
      lane's configured clauses are not visible to the scenario, so a clause
      override it wrote could not be told apart from configuration.

## 4. Filters and the compute schema

- [x] 4.0 Confirmed against `core/registry/filter-spec.yaml`'s lower-bound block:
      every existing bare-named bound is a capacity field searched from below.
      `asking_rate` names the upper bound; the lower bound keeps
      `asking_rate_min`.
- [x] 4.1 `core/registry/filter-spec.yaml` declares `asking_rate_max` (query name
      `asking_rate`), `asking_rate_min`, `asking_rate_asset`, and
      `asking_rate_period`, after the lower-bound block, with a comment stating
      the direction-of-search naming rule.
- [x] 4.1a All four `on_missing: fail`.
- [x] 4.1b Both bounds `requires: [asking_rate_asset, asking_rate_period]`.
- [x] 4.1c Asset and period are `op: in` string filters, so a listing in another
      asset or period is excluded, never converted.
- [x] 4.2 `listing_resource.asking_rate` declared in the compute `listing_shape`:
      `additionalProperties: false`, all three parts required, `amount` matching
      the settlement publication clause's decimal-text grammar, `period` limited
      to `hour`.
- [x] 4.3 The compute specification's etag changes (it now declares `requires`);
      nothing in the tree snapshots it. No other specification declares
      `decimal_text` or `requires`, and the literal-digest test pins that an
      undeclaring spec's etag is unchanged.

## 5. Specification

Normative statements are carried in this change's deltas and reach the permanent
specs when the change is archived. Companion `architecture.md` and
`DEPLOYMENT_AND_CONFIG.md` are not synchronized by OpenSpec, so 5.5 and 5.6 are
written at promotion (8.9), after code review.

- [x] 5.1 `specs/registry-discovery/spec.md`: exact decimal comparison, declared
      co-requirements (registry refusal authoritative; specification defects
      refused; an undeclaring specification's serialization and etag unchanged).
- [x] 5.1a Same delta: "A bound filter's bare query name is the bound a buyer
      searches by", stated as a rule for filter authors, not engine behaviour.
- [x] 5.2 Same delta: the compute schema's `asking_rate` object, validated only
      in the dry run, and its filters, now naming `asking_rate` as the upper
      bound and `asking_rate_min` as the lower.
- [x] 5.3 `specs/storefront-publication/spec.md`: per-shape declaration and
      precedence, no configuration default, the fail-closed hold, the listing
      attribute independent of any mechanism rate, the in-place refresh, and
      bare metal's override vocabulary, durable status source, command, and
      unreadable-override hold. The modified write requirement now refuses rates
      the domain cannot read, judged as publication reads them.
- [x] 5.4 `specs/resource-pool-management/spec.md`: the `asking_rates` tag and its
      structural check. **Found in reconciliation:** the delta requires `period`
      to be a canonical lowercase unit token; the implementation checked only a
      trimmed string. It now applies the settlement clause's unit grammar
      (`kit/resource-pools/.../asking_rates.py`, `_UNIT`), with a test.
- [ ] 5.5 At promotion: `openspec/specs/storefront-publication/architecture.md`,
      why the rate is keyed by shape beside the shape, why the storefront has
      final authority with no configuration default, and why a site range is
      deferred.
- [ ] 5.6 At promotion: the same companion's "Storefront pool overrides" section
      and `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Storefront listing
      shapes and pool overrides"): bare metal's vocabulary, its status source,
      the shared route service, and the bare-metal command's identity and URL
      inputs.

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
      override-store join. The unbacked-supply system evidence was later
      transferred out (7.13), and multi-seller provenance proven at integration
      (7.14), so no task remains blocked on another change.

## 7. Validation

- [x] 7.1 **Unit.** `core/registry/tests/unit/test_filter_eval.py` and
      `core/registry/tests/unit/test_filter_spec.py`: exact-decimal comparator
      behaviour — bounds at, above, and below a value; inclusive against
      exclusive at equality; a value with more significant digits than a double
      holds; a resolved listing value of the wrong shape; a spec declaring
      `decimal_text` loads, one declaring an unrecognized type is refused.
- [x] 7.2 **Unit.** `core/registry/tests/unit/test_filter_spec.py`: co-requirement
      declaration validation — unknown target, self-reference, cycle,
      one-directional supply (naming an asset/period without a bound still
      validates), serialization change when `requires` is declared versus not,
      and a literal-digest pin for the new etag value per 2.2e.
      `core/registry/tests/unit/test_filter_eval.py`: criterion construction
      refusing a bound supplied without its co-requirement.
      `core/tests/unit/test_query_dsl.py`: the buyer-side `requires` check on
      `FieldDescriptor`.
- [x] 7.3 **Unit.** `kit/resource-pools/tests/unit/test_asking_rates.py`:
      structure (absent, empty mode list, refused amounts including zero, sign,
      exponent, leading zero, and a JSON number; boundary amounts; a missing or
      unknown part; an untrimmed asset; an unknown period structurally valid)
      and resolution (no tier; per-shape pricing by digest; another mode's
      declaration; override replacing the pool's list as a whole; an empty
      override; unknown vocabulary, an unaccepted period, and a duplicate shape
      holding; an unreadable override not falling through; unpublished shapes
      reported). The period parity guard is
      `domains/vms/storefront/tests/unit/test_asking_rate_period_parity.py`.
- [x] 7.6 **Integration.** `kit/resource-pools/tests/integration/test_resource_pool_service.py`
      (`TestAskingRatesValidationOnEveryWriteSurface`): create, replace, patch,
      and bulk import refuse identically and store nothing; a valid
      declaration is kept verbatim.
Test levels for 7.7–7.10 were corrected after review against
`docs/development/TESTING.md` §2: integration means the real app, a real database,
wired DI, and the canonical typed client, and the library exception covers kits
only. Derivation and cycle tests over a real database are component evidence here,
whatever a module's header says; `test_reconciler_projection.py` calls itself an
integration test, a description that predates this change and is left to the next
change that touches the module.

- [x] 7.7 **Integration.** VM: `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`
      carries a pool-declared rate and an override rate through the real app's
      publication into the stored listing, over the typed client. Bare metal:
      `domains/bare_metal/storefront/tests/test_http_publication_rates.py` (added
      after review) drives the administrator's publication step through the
      typed client and reads back the listing a buyer fetches, with a declared
      rate, an override rate, and an empty override. **Component:**
      `test_reconciler_projection.py` prices two shapes on real SQLite and omits
      the field for an unpriced one.
- [x] 7.8 **Integration.** `test_pool_overrides_api.py`: an empty override
      withholds a declared rate and the same listing refreshes without it; the
      write refuses a rate keyed by a shape outside the vocabulary, an unaccepted
      period, and two rates for one shape. **Component:**
      `test_reconciler_projection.py` covers an override at a non-first site
      replacing that site's rates as a whole while the other keeps the pool's,
      and pricing defaults with no declaration publishing no rate.
- [x] 7.9 **Integration.** Both domains' app tests above show a rate change and
      an empty override refreshing the same listing in place. **Component:**
      `test_reconciler_projection.py` classifies amount, asset, and removal as
      `terms_differ` on `asking_rate` alone under an unchanged key;
      `domains/bare_metal/storefront/tests/test_publication_cycle.py` (which
      describes itself as not integration evidence) shows the bare-metal refresh
      and removal.
- [x] 7.10 **Component.** Both domains' derivation and cycle tests: an
      unreadable declaration or override holds the pool (VM
      `unreadable_asking_rates`; bare metal `asking_rates_unreadable`, its listing
      kept open and nothing sent), and a priced shape no listing has is
      reported. Hold behaviour is orchestration, which the cycle and derivation
      tests are the right level for; no app test is added for it.
- [x] 7.11 **Integration.** `test_pool_overrides_api.py`: an override's rate and
      its settlement clause's rate each publish as stated, and no settlement
      option carries the asking amount.
- [x] 7.12 **Integration.** `core/registry/tests/integration/test_asking_rate_filter.py`:
      a listing whose only settlement option is a rateless introduction, built
      with contact exchange's own option-identity derivation, is found by a
      rate-bounded query and keeps its option's empty rate list. The registry
      depends on no mechanism, so the mechanism's name and asset are stated
      literally.
- [x] 7.13 **Transferred.** A buyer query bounded by rate returning backed and
      unbacked listings together. The asking-rate path is independent of backing,
      and this change proves it through running services on backed supply (8.8)
      and, at the registry, for a listing whose only option is a rateless
      introduction (7.12). What is missing is the unbacked listing itself, which
      two other changes create, so each owns its half where its own system
      scenario already queries backed and unbacked supply together:
      `compose-contact-exchange-across-compute` 6.4 (VM) bounds that query by
      asking rate, and `unbacked-bare-metal-listings` carries the bare-metal half
      in its proposal and closeout. Holding this change open for them would have
      left already-true behaviour unpromoted behind a Goal 6 prerequisite
      (`contact-payload-retention`) with no tasks begun.
- [x] 7.14 **Integration** (re-levelled from System). Multi-seller provenance:
      `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`
      (`test_each_seller_sites_rate_reaches_only_its_own_listing`) runs one
      storefront app for two seller sites whose pools share a name. Each site's
      declared rate reaches only its own listing, and an override at one site
      changes only that site's. System level adds nothing here: provenance is the
      storefront keying rates by site and pool, and both service crossings the
      rate makes, site to storefront and storefront to registry, are proven by
      the bare-metal end-to-end run (8.8). The dependency on
      `repair-multi-storefront-scenario` is dropped.

## 7b. Review findings

From the implementation review. Each was reproduced before it was changed.

- [x] 7b.1 **Finite decimals.** `core/registry/src/core_registry/api/filter_eval.py`:
      `_finite_decimal` admits only finite values. A non-finite query bound is a
      `FilterParamError` (400), not the `decimal.InvalidOperation` a `NaN` bound
      raised as a server error; a non-finite listing value reads as no value.
      Tests: `NaN`, `sNaN`, both infinities, and `inf`, on both sides
      (`core/registry/tests/unit/test_filter_eval.py`). Delta: `registry-discovery`
      now says finite, with two scenarios.
- [x] 7b.2 **A stated null holds.** `kit/resource-pools/.../asking_rates.py`:
      `raw_asking_rates` returns `NOT_STATED` for a missing key, and anything
      stated, `None` included, as-is, so a stated `null` tag or mode holds the
      pool instead of reading as no rate. The bare-metal override reader
      validates `terms` stated as anything but a mapping (`[]` included) as
      unreadable instead of defaulting it. **Not changed:** the override kit's
      store maps both SQL `NULL` and stored JSON `"null"` to `None`. The store
      writes `NULL` for every unset field, so `"null"` text can arise only from
      corruption, and telling them apart is a kit change that also governs VM's
      existing fields; it is outside this change.
- [x] 7b.3 **Effective duration bounds.** Each bare-metal override bound replaces
      its configured counterpart, as configuration overlays do, and the effective
      pair must be ordered (`pool_overrides.py`, `effective_duration_problems`).
      The write is refused against the configured maximum
      (`BareMetalPoolOverrideContribution` reads it when judging); publication
      rechecks against current configuration and holds the pool as
      `pool_override_terms_conflict`. One parser,
      `configured_max_duration_seconds`, now serves the payload builder, the
      contribution, and the cycle. Tests: `tests/test_pool_override_terms.py`
      (unit), `tests/test_pool_overrides_api.py` (write refusal and acceptance
      through the typed client), `tests/test_publication_cycle.py` (a conflict
      after the write, and stored `terms` of `[]`).
- [x] 7b.4 **Test levels.** 7.7–7.10 relabelled; one bare-metal app integration
      test added (see 7.7).
- [x] 7b.5 **Stale comment.** The registry evaluator test no longer says the
      deployed specification lacks asking-rate filters.
- [x] 7b.6 **Placement of precedence.** Kept beside the declaration parser, with
      the reasoning and a revisit trigger in `design.md`.
- [x] 7b.7 **Scope.** The review diff included edits to
      `pools-9-retire-local-physical-authority` and
      `remove-dead-storefront-physical-surfaces`. No fileset of this change
      touches them; they are concurrent work outside this change.

## 8. Closeout

- [x] 8.1 **Comment hygiene.** `make check-comment-hygiene` passes. Its one
      finding during implementation was a test docstring of this change citing
      `design.md`, restated as the invariant. Still owed at closeout: a direct
      read of the touched production files for fuzzier provenance.
- [x] 8.2 **Import placement.** Every function-level import this change added
      was checked. Kept local, with their reasons verified: VM's
      `resolve_vm_asking_rates` imports the resource-pool kit locally because
      `arkhai-vms-listings` installs it only as an optional extra (confirmed in
      its `pyproject.toml`); the bare-metal `pool-override` command imports its
      client stack inside each command, as its sibling commands do, so help and
      unrelated commands load none of it. Moved to module level: the tests'
      mid-module and function-local imports in
      `core/registry/tests/unit/test_filter_eval.py`,
      `core/registry/tests/integration/test_asking_rate_filter.py`,
      `domains/vms/storefront/tests/integration/test_reconciler_projection.py`, and
      `domains/bare_metal/storefront/tests/test_publication_cycle.py`; all three
      suites pass after the move.
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
- [x] 8.7 **Documentation citations.**
      `make check-doc-citations CHANGE=publish-indicative-listing-rates` passes;
      rerun after promotion.
- [x] 8.8 **End-to-end pipeline.**
      - Run 36837675676: VM lane 126 passed with its 2 existing skips; the
        bare-metal lane failed before any scenario, its storefront unable to
        start (the 3b.4 defect).
      - Run 36839524415, with that fix: both lanes passed. VM: 126 passed and
        2 existing skips. Bare metal: all 11 stages of
        `test_bare_metal_publication.py` passed, including 05b (a declared rate
        refreshes the listing in place and rate queries find it at, and only at,
        its bound by both bound names), 05c (a storefront override replaces the
        rate and maximum duration and reports `applied`), and 05d (deleting it
        restores the pool's rate). No tracebacks in either lane's container
        logs.
      - Run 36841346733, including the 7b review fixes: both lanes passed. VM:
        126 passed and 2 existing skips. Bare metal: all 11 publication stages
        passed, 05b–05d included. No tracebacks in either lane's container logs.
      - `make test` passed in the reviewer's environment on the same tree,
        covering the suites the implementation environment could not run (the
        VM storefront's chain-dependent Alkahest tests and its `rl` extra).
      - 7.13 transferred and 7.14 proven at integration; neither is owed here.
      - Note: `e2e-tests/tests/unit/test_hosted_public_boundary.py::
        test_buyer_deployment_mounts_separate_profile_state_and_credential`
        fails before this change too; it reads compose files this change does
        not touch.
- [ ] 8.9 **Promotion.** Complete the design-promotion record below.
- [x] 8.10 **Packaging.** `make check-packaging` passes after `make lock` in the
      reviewer's environment, which relocked two projects (including
      `domains/vms/storefront/uv.lock`, which the implementation environment's
      network could not resolve). Those locks are the reviewer's; nothing here
      supersedes them.

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
| One asking-rate resolver in `kit/resource-pools`, generic over each domain's shape digest and vocabulary, because bare metal cannot import VM | `openspec/specs/storefront-publication/architecture.md` |
| A market's override contribution judges override rates, so the override kit gains no resource-pool dependency | `openspec/specs/storefront-publication/architecture.md` ("Storefront pool overrides") |
| Accepted periods are a local contract held equal to `PER_UNIT_SECONDS` by a parity test, not imported | `openspec/specs/storefront-publication/architecture.md` |
| An unpriced listing publishes no `asking_rate` field rather than null, so a withdrawn rate refreshes in place | `openspec/specs/storefront-publication/spec.md` (delta: "A shape is priced nowhere") |
| The bare-metal command signs as the storefront's own identity from the server's inputs | `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Storefront listing shapes and pool overrides") |
| `kit/pool-overrides` keeps its version: backward-compatible additions, unchanged requirements | Temporary: change history only |
| The decimal value type is finite: a non-finite bound is refused, a non-finite listing value is no value | `openspec/specs/registry-discovery/spec.md` |
| A stated `null` asking-rate declaration is malformed and holds the pool | `openspec/specs/storefront-publication/spec.md` |
| Bare-metal duration bounds replace their configured counterparts independently; the effective pair is checked at write and at publication | `openspec/specs/storefront-publication/spec.md`, and the operator rule in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Storefront precedence stays beside the pool declaration's parser, with its revisit trigger | `openspec/specs/storefront-publication/architecture.md` |
