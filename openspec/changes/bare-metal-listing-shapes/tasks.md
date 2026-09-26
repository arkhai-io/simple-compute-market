# Tasks — bare-metal listing shapes

Unblocked: `bare-metal-publication-reads-pool-declarations` is complete. Planned.

## 1. Design

- [x] 1.1 Decide each open question in `design.md` and record the decision there.
      Decided: the compute-family schema; close and republish once; the nested
      `capabilities` mapping retired; overrides carry clauses and terms only.
- [x] 1.3 Audit the recorded decisions against the code and resolve what it
      invalidated. Recorded in `design.md`:
      - the compute-family schema moves to a new `domains/compute` package;
      - `kit/capability-shape` gains `unflatten_shape`;
      - the shape is derived from declared capacity and attributes, requiring `gpu`
        and exactly one `units`;
      - the derivation identity includes the shape digest, which amends "identity
        stays the Physical Resource" and replaces listings once without special code;
      - the claim carries the shape's attributes beside `units: 1`;
      - region is read from the pool hint, and a pool with none is held;
      - override HTTP handling moves into a framework-free kit route service, with
        status judged against the last accepted generation;
      - a minimal opening guard is added, and moves with
        `bare-metal-and-credits-domain-stacks` 4a;
      - bare metal gains a `pool-override` command: VM's command-line layer copied
        over the kit's typed client, calling the administrator API.
- [x] 1.2 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations. Planning
      recorded "Decisions taken while planning" in `design.md`:
      - the last accepted generation is durable, not in memory;
      - the payload kind is unchanged;
      - the listing model names the schema's flat fields;
      - the source envelope moves to version 2;
      - reconciliation matches resources before keys;
      - `bare-metal list --resource`;
      - no bare-metal override contribution in the combined shell;
      - the storefront's test layout stays flat.
      The closeout placeholder formerly numbered 2.1 is written out in full as
      section 12.

## 2. Compute-family schema and the shape utility

Decisions: "The compute-family capability schema gets one home" and
"`kit/capability-shape` gains a schema-driven inverse of flattening".

- [ ] 2.1 `kit/capability-shape/src/market_capability_shape/__init__.py`: add
      `unflatten_shape(quantities, attributes, schema) -> dict`. It refuses, as
      `CapabilityShapeError` naming every problem:
      - a flat name the schema does not define, or defines as the other kind;
      - every problem `shape_problems` finds on the result.
      Export it. Bump `kit/capability-shape/pyproject.toml` to 0.2.0.
- [ ] 2.2 `kit/capability-shape/tests/unit/test_capability_shape.py`:
      - round trip `flatten_shape(unflatten_shape(...)) ==` input, and the reverse,
        against a test schema;
      - digest equality between a derived and a hand-stated shape;
      - an unknown flat quantity or attribute is refused;
      - a flat name supplied as the wrong kind is refused;
      - a missing required field is refused.
      `test_import_boundary.py` stays green (standard library only).
- [ ] 2.3 Create `domains/compute/` (distribution `arkhai-compute` 0.1.0, import
      `arkhai_compute`) with `pyproject.toml`, `Makefile` (`build`, `reinit`, `test`),
      and `uv.lock`. Its dependencies are `arkhai-kit-capability-shape>=0.2.0` only.
      `src/arkhai_compute/__init__.py` and `capability_schema.py` hold:
      - `COMPUTE_CAPABILITY_SCHEMA`;
      - the flat constants (`GPU_COUNT_DIMENSION`, `VCPU_COUNT_DIMENSION`,
        `RAM_GB_DIMENSION`, `DISK_GB_DIMENSION`, `DIMENSION_KEYS`,
        `GPU_MODEL_ATTRIBUTE`);
      - the rationale comment moved from `arkhai_vms/compute_requirements.py`, stating
        present intent only, with a pointer to
        `openspec/specs/market-composition/spec.md`.
      Add `py.typed`.
- [ ] 2.4 `domains/compute/tests/`:
      - schema shape (families, kinds, required fields);
      - flat names against `DIMENSION_KEYS`;
      - an import-boundary test: the package imports only the standard library and
        `market_capability_shape`, and no `arkhai_vms`, `arkhai_bare_metal`, or
        `market_core`.
- [ ] 2.5 `domains/vms/domain/src/arkhai_vms/compute_requirements.py`: re-export from
      `arkhai_compute`, binding `VM_CAPABILITY_SCHEMA = COMPUTE_CAPABILITY_SCHEMA`.
      `arkhai_vms/__init__.py`, `capability_shapes.py`, and `shape_generation.py` keep
      their imports unchanged.
      `domains/vms/domain/pyproject.toml`:
      - add `arkhai-compute>=0.1.0`;
      - bump to 0.5.0;
      - relock.
      `domains/vms/domain/tests/test_compute_requirements.py` gains an identity
      assertion: `VM_CAPABILITY_SCHEMA is COMPUTE_CAPABILITY_SCHEMA`.
- [ ] 2.6 Focused: `make -C kit test-capability-shape`, `make -C domains/compute test`,
      and `make -C domains test-vms-domain`.

## 3. Pool-override kit route service

Decision: "Bare metal joins the override store through a kit route service".

- [ ] 3.1 `kit/pool-overrides/src/market_pool_overrides/routes.py`: add
      `PoolOverrideRouteService(service)` with three methods:
      - `replace(body) -> PoolOverrideWriteResponse`, which validates
        `PoolOverrideRecord`, raising `PoolOverrideRefused(422)` on validation failure;
      - `read(query_items) -> PoolOverrideResponse | PoolOverrideListResponse`, which
        validates the query through `read_query`, raising 400 on
        `PoolOverrideContractError`, dispatches get versus list, and raises 404 for a
        missing single override;
      - `delete(query_items) -> PoolOverrideDeleteResponse`.
      It imports no web framework. Export it from `__init__.py`. Bump
      `kit/pool-overrides/pyproject.toml` to 0.3.0.
- [ ] 3.2 `kit/pool-overrides/tests/unit/test_routes.py`, over a service double:
      - get versus list dispatch;
      - 404 on a missing read;
      - 400 on an unauthenticated alias or an out-of-order narrowing;
      - 422 on a malformed record;
      - responses round-trip through the typed client's parsers.
      Add `kit/pool-overrides/tests/integration/test_routes.py` against the real
      SQLite store: replace, read, list, and delete through the route service.
- [ ] 3.3 `kit/pool-overrides/src/market_pool_overrides/service.py`: split the
      after-write effects so a composition root may inject either as absent.
      `refresh_site` and `wake_publication` become optional, and `None` means the
      storefront has no cache or no loop. Test both absences in
      `tests/integration/test_service.py`. This implements the modified live-projection
      requirement.
- [ ] 3.4 `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`:
      reduce the three override handlers to bindings over `PoolOverrideRouteService`,
      mapping `PoolOverrideRefused` to `HTTPException`. Construct the route service
      beside `resolved_pool_override_service` in `container.py` and `server.py`. Leave
      the middleware's `_pool_override_contract` unchanged.
- [ ] 3.5 Focused: `make -C kit test-pool-overrides`, plus the VM storefront's
      `tests/integration/test_pool_overrides_api.py`,
      `tests/unit/test_identity_dispatch.py`,
      `tests/unit/test_pool_override_client_parity.py`, and
      `tests/unit/cli/test_pool_overrides.py`. All must pass unchanged, which proves
      the wire contract did not move.

## 4. Bare-metal domain: listing, derivation, classification, identity

Decisions:
- "The shape is derived from the declaration";
- "The whole machine is one unit";
- "The nested `capabilities` mapping and the `site` labels are retired";
- "Region comes from the pool hint";
- "Derivation identity: the resource anchors it, the shape completes it";
- planning's "payload kind", "listing model", and "reconciliation matches resources
  before keys".

- [ ] 4.1 `domains/bare_metal/src/arkhai_bare_metal/schema.py`, `BareMetalListing`:
      - remove `capabilities` and `site`;
      - add `gpu_count: int` (≥1), `gpu_model: str`, `vcpu_count`/`ram_gb`/`disk_gb:
        int | None` (≥1), and `region: str`, all non-blank;
      - set `model_config = ConfigDict(extra="forbid")`;
      - keep `kind` at `bare_metal.v2`;
      - add a `shape` property returning the family-grouped shape through
        `unflatten_shape`, and a `shape_digest` property.
- [ ] 4.2 `domains/bare_metal/src/arkhai_bare_metal/projections.py`:
      `TrustedBareMetalResource` gains `declared_capacity: dict[str, Any]` and
      `declared_attributes: dict[str, Any]`, read from the containing projected
      resource. `publication.trusted_bare_metal_projection` populates them. The
      view's `capabilities` stays accepted on input so a site generation carrying it
      is not refused, but it is never read.
- [ ] 4.3 New `domains/bare_metal/src/arkhai_bare_metal/shapes.py`:
      `derive_bare_metal_shape(declared_capacity, declared_attributes)` returns the
      shape or a `BareMetalShapeProblem` list. It covers:
      - `units` present and exactly 1;
      - every other capacity key a compute quantity;
      - positive-integer quantities;
      - GPU count and model required;
      - schema attribute names read from attributes and every other attribute ignored.
      It also reports a present `bare_metal_publication.capabilities` as ignored.
- [ ] 4.4 `domains/bare_metal/src/arkhai_bare_metal/publication.py`:
      `available_bare_metal_listings` builds each listing from the derived shape and a
      supplied `region`, flattening through `COMPUTE_CAPABILITY_SCHEMA`. Remove the
      capacity/capabilities merge.
- [ ] 4.5 `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py`:
      - Classification takes `pool_regions: Mapping[str, str | None]`, and a pool
        without a usable region holds its resources.
      - A resource whose shape is unresolvable is `HELD`, with its problems carried on
        the classified item.
      - `ClassifiedBareMetalResource` gains `shape_digest: str | None`.
      - Candidates carry `shape_digest`.
      - `bare_metal_source_identity` takes `shape_digest`.
      - `IDENTITY_FIELDS` drops `capabilities` and `site` and adds the schema's flat
        names and `region`.
      - Add a `pool_region` helper applying `raw_region` with VM's non-empty-string
        rule.
- [ ] 4.6 `domains/bare_metal/src/arkhai_bare_metal/fixtures/publication_view.py`: the
      default view carries no hardware in `capabilities`. Add
      `build_bare_metal_projected_resource(...)`, which returns a projected resource
      with declared `capacity` (`units: 1` plus hardware), declared `attributes`
      (`gpu_model`, `physical_host_id`, `allocation_mode`), and the view.
      `validate_bare_metal_publication_view` is unchanged.
- [ ] 4.7 `domains/bare_metal/pyproject.toml`:
      - add `arkhai-compute>=0.1.0` and `arkhai-kit-capability-shape>=0.2.0`;
      - bump to 0.6.0;
      - relock.
      `domains/bare_metal/Makefile` reinit adds both packages.
- [ ] 4.8 Tests under `domains/bare_metal/tests/`:
      - `test_shapes.py` (new): every accepted and refused declaration in 4.3, and
        equal shapes for two identical declarations.
      - `test_schema.py`: extra fields are refused; the listing's flat fields equal
        `COMPUTE_CAPABILITY_SCHEMA`'s flat names; a listing's `shape_digest` equals
        `shape_digest` of the hand-stated shape.
      - `test_publication.py` and `test_projections.py`: declared capacity and
        attributes are read from the container, and the view's `capabilities` is
        ignored.
      - `test_storefront_publication.py`: the region hold, a shape hold, digest-bearing
        candidates and source identity, and the new identity fields.
- [ ] 4.9 `provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`
      and `tests/integration/test_capacity_api.py`: still validate the view through
      `validate_bare_metal_publication_view`. Update their declarations to put
      hardware in `capacity` and `attributes`. No provisioning source changes.

## 5. Bare-metal storefront: publication

- [ ] 5.1 `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py`:
      - `bare_metal_derivation_key` takes `shape_digest`;
      - `upsert_bare_metal_listing` writes source envelope schema version 2 with
        `shape_digest`;
      - binding listing returns each binding's `pool_id`, `physical_resource_id`, and
        envelope version, so reconciliation can match by resource.
      Add table access for the accepted-generation record (5.4).
- [ ] 5.2 `.../publication.py`, `BareMetalPublicationCycle`:
      - `_pool_admission` also resolves each pool's region, holds and reports
        (`pool_region_missing`) a pool without one, and reports
        (`listing_shapes_not_applicable`) a pool stating `listing_shapes.bare_metal`;
      - `_classify_site` reports each unresolvable declaration (`declaration_unresolvable`
        with its problems) and each ignored `capabilities`
        (`publication_capabilities_ignored`);
      - `_key` includes the digest;
      - `_close_stale` matches by resource first, in the order recorded under
        "Reconciliation matches bindings by resource before key".
- [ ] 5.3 `.../publication_composition.py`: resolve the override tier per candidate.
      - Read stored `bare_metal` overrides through
        `market_pool_overrides.read_pool_overrides`, over the storefront's connection,
        once per run.
      - An override's settlements replace the configured clauses for its site's pool,
        compiled through the same `SettlementPublicationClause` validation.
      - Its `min_duration_seconds` and `max_duration_seconds` replace the configured
        bounds.
      - An override field that cannot be decoded holds that pool's candidates rather
        than falling through.
- [ ] 5.4 `.../migrations.py`: append two migrations:
      - the kit's `pool_override_migrations()`;
      - a `bare_metal_accepted_generations` table (`site_id` primary key, `revision`,
        `digest`, `pool_ids_json`, `accepted_at`).
      `BareMetalPublicationCycle.run` writes a row for each site whose generation it
      accepted, before registry convergence.
- [ ] 5.5 Tests:
      - `tests/test_publication_cycle.py`:
        - a declared-dimension correction closes and publishes a successor, leaving
          the original binding row unmodified;
        - a version 1 binding closes as `source_gone` with its successor published in
          the same run;
        - a region-less pool is held and reported;
        - an unresolvable declaration holds only its own listing;
        - `listing_shapes.bare_metal` is reported;
        - override clauses and durations reach a refreshed listing;
        - an undecodable override holds its pool;
        - the accepted-generation row is written for accepted sites only.
      - `tests/test_persistence.py`: envelope version 2 and the digest-bearing key.
      - `tests/test_migrations.py`: fresh bootstrap and idempotent rerun of both
        migrations.

## 6. Bare-metal storefront: claims and the opening guard

Decisions: "The whole machine is one unit" and "A minimal seller inventory guard at
opening".

- [ ] 6.1 `.../fulfillment_service.py` and `.../hosted_lifecycle.py`: the reservation
      claim adds the listing's schema attributes (`gpu_model`) as top-level
      exact-match keys. Those are what `kit/site`'s `_split_claim_requirement` treats
      as required attributes. The values come from the trusted listing record
      (`load_bare_metal_listing_payload`). The claim keeps `dimensions: {"units": 1}`,
      `offering_mode`, and its resource or pool. No buyer-supplied value reaches it.
- [ ] 6.2 New `.../inventory_guard.py`: `recheck_listing_source(runtime, listing_id)`
      fetches the bound site's live projection through
      `runtime.capacity_client.site(site_id)`, re-derives shape and region for the
      bound pool and resource, and compares them with the binding's `shape_digest`
      and the published region. The outcomes are:
      - `declared_mismatch` on a difference, a missing resource, or a disabled
        declaration;
      - retryable on an unreachable or unverified site.
- [ ] 6.3 `.../negotiation_service.py`: call the guard in `open` before the round hook,
      and in `_open_exact_selection` before `_validate_physical_selection`. Refuse with
      409 `listing no longer matches its declaration` on a mismatch, and 503 on a
      retryable failure.
- [ ] 6.4 Tests:
      - `tests/test_fulfillment_service.py` and `tests/test_hosted_lifecycle.py`: the
        claim carries `gpu_model` from the listing, and a changed declaration model
        is refused by a site double enforcing equality.
      - `tests/test_http_negotiation.py` and `tests/test_http_settlement.py`: each
        guard outcome on both opening paths.
      - `tests/test_inventory_guard.py` (new): the comparison itself.

## 7. Bare-metal storefront: overrides

Decisions: "Bare metal joins the override store through a kit route service", "Bare
metal gains a `pool-override` command in the same layering", and planning's "last
accepted generation".

- [ ] 7.1 New `.../pool_override_contribution.py`, `BareMetalPoolOverrideContribution`:
      - `offering_mode = "bare_metal"`;
      - `vocabulary_problems` refuses `listing_shapes` and validates terms through a
        new `BareMetalPoolOverrideTerms` model in `.../models.py`
        (`min_duration_seconds`, `max_duration_seconds`, extra forbidden, min ≤ max);
      - `judge_shapes` returns `[]`.
- [ ] 7.2 `.../runtime.py`: compose `PoolOverrideService`. It takes:
      - `SQLitePoolOverrideStore` on the storefront database;
      - site IDs from `site_bindings`;
      - site clients from `capacity_client.site`;
      - `{bare_metal: contribution}`;
      - the settlement composition's clause compiler;
      - `projection_source` reading `bare_metal_accepted_generations`;
      - no `refresh_site` and no `wake_publication`.
      Also compose `PoolOverrideRouteService` over it.
- [ ] 7.3 `.../api.py`: add `PUT`, `GET`, and `DELETE` routes at
      `/api/v1/admin/pool-overrides`, each authenticating through `_admin` with the
      operation and resource from `pool_override_contract`. They delegate to the route
      service and map `PoolOverrideRefused` to `HTTPException`. `system_status` adds
      `pool_overrides` (the service's `statuses()`) to
      `BareMetalHealthResponse`, which gains that optional field in `models.py`.
      Public `/health` does not include it.
- [ ] 7.4 New `.../pool_override_cli.py`, copied from
      `domains/vms/storefront/src/market_storefront/groups/pool_overrides.py`, with
      only the session helper replaced. `_client()` resolves the URL (`--storefront-url`,
      else `BARE_METAL_STOREFRONT_PUBLIC_URL`, else `http://localhost:8000`) and the
      signer (`BARE_METAL_STOREFRONT_IDENTITY_*` and `ARKHAI_IDENTITY_CREDENTIAL`
      through `resolve_storefront_signer`). It opens a `SyncStorefrontClient` as
      `admin`, pinning that signer as expected publisher. `.../cli.py` mounts it as
      `pool-override`.
- [ ] 7.5 `domains/bare_metal/storefront/pyproject.toml`:
      - add `arkhai-kit-pool-overrides==0.3.0` and `arkhai-compute>=0.1.0`;
      - raise `arkhai-bare-metal>=0.6.0` and `arkhai-kit-capability-shape`;
      - bump to 0.6.0;
      - relock.
      `Makefile` reinit adds `arkhai-kit-pool-overrides` and `arkhai-compute`.
      `Dockerfile` pins `arkhai-bare-metal-storefront==0.6.0`.
- [ ] 7.6 `tests/test_import_boundaries.py`: assert the storefront imports
      `arkhai_compute` and no VM implementation. The existing VM list is unchanged.
- [ ] 7.7 Tests:
      - `tests/test_pool_overrides_api.py` (new; typed-client integration against the
        in-process app with site doubles, following the "no raw calls" rule):
        - replace, read, list, and delete;
        - 422 for shapes, unknown terms, and an unconfigured site;
        - 503 unreachable, 404 unknown pool;
        - status `unknown` before any accepted generation, `applied` after a run
          recorded through the publication command, `orphaned` after the pool
          leaves, and `site_unconfigured`;
        - an administrator-only route refuses a buyer signer.
      - `tests/test_pool_override_cli.py` (new): each command drives
        `SyncPoolOverrideClient` against the in-process app, and `--mode` is
        required.
      - `tests/test_pool_override_contribution.py` (new): the vocabulary.

## 8. Bare-metal buyer

Decision: planning's "`bare-metal list --resource`".

- [ ] 8.1 `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`: `list` gains
      `--resource`. It fetches the registry's filter specification, compiles through
      `registry_client.query.compile_resource_query`, and passes the compiled filters
      and ETag with `offering_mode=bare_metal`. `pyproject.toml`:
      - raise `arkhai-bare-metal>=0.6.0`;
      - bump to 0.3.0;
      - relock.
      `Makefile` reinit adds `arkhai-compute` and `arkhai-kit-capability-shape` if its
      lock installs them.
- [ ] 8.2 `domains/bare_metal/buyer/tests/test_buyer_composition.py`: a query compiles
      against a filter-spec fixture, an unknown field is refused before any request,
      and the ETag is sent.

## 9. Combined shell and remaining consumers

Decision: planning's "combined shell registers no bare-metal override contribution".

- [ ] 9.1 `domains/vms/storefront/pyproject.toml`:
      - `arkhai-bare-metal-storefront==0.6.0`;
      - `arkhai-bare-metal>=0.6.0`;
      - `arkhai-kit-pool-overrides==0.3.0`;
      - `arkhai-vms>=0.5.0`.
      Relock. `domains/vms/storefront/Dockerfile` line pinning
      `arkhai-bare-metal-storefront==0.5.0` becomes `0.6.0`. Its Makefile reinit adds
      `arkhai-compute`.
- [ ] 9.2 Relock, and add `arkhai-compute` to reinit, for every other lock that now
      installs it: `domains/vms/buyer`, `domains/vms/provisioning/adapter`,
      `domains/bare_metal/provisioning/adapter`, `provisioning/compute/service`, and
      `e2e-tests`. Also add the two changed kits where they are installed.
      `domains/vms/listings/pyproject.toml` raises its pool-overrides floor only if it
      uses the route service; it does not.
- [ ] 9.3 A test in the VM storefront's `tests/unit/` asserts a combined registration
      that selects `bare_metal` still refuses a `bare_metal` override write as a mode
      no market serves.

## 10. Build, packaging, and reinit

- [ ] 10.1 `domains/Makefile`:
      - add `dist-compute` (`cd compute && uv build`, with the platform-wheel guard)
        and `test-compute`;
      - add `dist-compute` to `dist`;
      - make `dist-vms` and `dist-bare-metal` depend on it.
      Root `Makefile`:
      - add `test-compute` beside `test-vms-domain`, and to `test`;
      - add both new targets to `.PHONY`.
- [ ] 10.2 `make dist-ci` builds cleanly, and `unzip -l` shows each changed wheel's
      contents: `arkhai_compute`, `market_capability_shape`, `market_pool_overrides`
      with `routes.py`, `arkhai_bare_metal`, and `arkhai_bare_metal_storefront`, with
      no test or fixture leakage beyond the published `fixtures` package.
- [ ] 10.3 Typing: `py.typed` present in `arkhai_compute`. Run the repository's
      configured type checks for the touched packages, or disclose any not configured.
- [ ] 10.4 `make check-reinit` passes.

## 11. End-to-end and operator documentation

- [ ] 11.1 `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py`:
      - `_whole_host` declares `capacity: {units: 1, gpu_count: 8, ram_gb: 2048}` and
        `attributes: {gpu_model: H200, physical_host_id, allocation_mode,
        bare_metal_publication: {enabled, access_methods}}`, registered through
        `register_resource(capacity=...)`;
      - the advertised pool's `policy_tags` gain `region`;
      - Stage 03 also finds the listing through `bare_metal_registry.list_listings`
        with `gpu_model` and `gpu_count` filters, and asserts the published fields;
      - a new stage writes a `bare_metal` override (`max_duration_seconds`) through
        `SyncPoolOverrideClient` over `bare_metal_storefront_admin`, steps
        publication, and observes the refreshed value at the registry;
      - a new stage adds a dark pool without a region and asserts the `hold` report.
- [ ] 11.2 `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py`:
      it is selected by neither lane. Update any declaration it documents or builds to
      the new rules, so it is not stale when a lane selects it.
- [ ] 11.3 `docs/bare-metal-seller-quickstart.md`:
      - the registration body carries hardware in `capacity` and `attributes`;
      - `bare_metal_publication` keeps `enabled` and `access_methods` only;
      - the pool document gains `region`;
      - the round's bullet list names the region hold and the unresolvable-declaration
        hold;
      - add a "Per-pool overrides" subsection for `bare-metal-storefront pool-override`,
        naming the administrator requirement.
- [ ] 11.4 If `bare-metal-mock-provisioned-deal` is still unplanned when this change
      completes, append a context line to its `design.md` stating that bare-metal
      declarations carry hardware in `capacity` and `attributes` with `units: 1`.

## 12. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 12.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Then read directly for fuzzier provenance:
      - the moved schema comment in `arkhai_compute`;
      - the source-envelope version reader;
      - the upgrade-closing path in `_close_stale`;
      - the copied CLI module's docstring.
      None may say where something came from or which review asked for it.
- [ ] 12.2 **Import placement.** For imports this change adds or touches only:
      - `cli.py`'s function-local imports for `pool_override_cli` stay local, for the
        existing lazy-load reason shared by its sibling commands;
      - every new module-level import in `shapes.py`, `inventory_guard.py`,
        `pool_override_contribution.py`, `routes.py`, and `arkhai_compute` is verified
        against the real suites;
      - any local import added under 4–7 is moved unless a circular import is shown
        by attempting the move.
- [ ] 12.3 **Documentation compliance.** Re-check each accepted decision against
      `openspec/README.md`'s placement table. Normative behaviour goes in `spec.md`,
      rationale in `architecture.md`, and cross-system facts in `ARCHITECTURE.md`.
      Nothing may remain only in this change.
- [ ] 12.4 **Narrative compression.** Shorten completed task notes to final behaviour,
      evidence, deferrals, and destinations. Detailed alternatives stay in `design.md`.
- [ ] 12.5 **Roadmap currency.** In `docs/development/ROADMAP.md` Goal 7:
      - remove the "Bare-metal listings form no capability shape" gap row;
      - rewrite the current-state paragraph so bare-metal listings carry a derived
        shape discoverable by the compute filters.
      In the Goal 1–2 vocabulary text, note that the compute-family schema has one
      owner. Record the update in the promotion record.
- [ ] 12.6 **Campaign index currency.** In `openspec/changes/README.md`:
      - this change's row becomes complete;
      - Goal 7's graph marks it done and unblocks `unbacked-bare-metal-listings`
        and `publish-indicative-listing-rates` Sections 3–4 on this dependency;
      - `settle-capacity-claim-vocabulary`'s row notes that its gate edits
        `arkhai_compute`.
      Record the update in the promotion record.
- [ ] 12.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-listing-shapes` and resolve every
      match, then run it unscoped to confirm no permanent document this change touched
      cites a missing path.
- [ ] 12.8 **End-to-end pipeline.** Run both lanes (`make run-e2e`, then
      `make fetch-e2e-logs`). Record:
      - the run ID and result;
      - that the bare-metal lane's publication scenario exercised discovery by
        `gpu_model` and `gpu_count`, the override stage, and the region hold;
      - that the VM lane's `test_listing_shapes.py` and pool-override stages passed
        on the re-exported schema and the rebound routes.
      A pipeline blocked for an unrelated reason is recorded as a blocker naming its
      cause and owning change, and its validations are unrun.
- [ ] 12.9 **Promotion.** Complete the design-promotion record below and promote:
      - `openspec/specs/storefront-publication/spec.md`: the ADDED requirements and
        both MODIFIED requirements, plus the Evidence list entries for 3–7.
      - `openspec/specs/storefront-publication/architecture.md`: in "Listing shapes and
        the storefront's authority", replace "Bare-metal and API-credit publication do
        not use listing shapes" with the derived-shape model, the one-unit
        commitment, and why the digest completes identity; in "Storefront pool
        overrides", add the route service, bare metal's vocabulary, and the durable
        accepted-generation status source.
      - `openspec/specs/market-composition/spec.md`: the ADDED and MODIFIED
        requirements, plus Evidence for `domains/compute` and `unflatten_shape`.
      - `openspec/specs/market-composition/architecture.md`: why the compute-family
        schema lives in a domain package rather than the foundation kit or the core,
        and that the flat-spelling gate edits it.
      - `docs/development/ARCHITECTURE.md`:
        - "Package and dependency layers": add the compute-family domain package
          between kit and the compute domains;
        - "Storefront capacity boundary": replace "Bare-metal and API-credit listings
          are not listing shapes" and state the one-unit commitment;
        - "One name per concept": the listing-shape sentence covers derived shapes.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`:
        - "Storefront listing shapes and pool overrides": bare metal's vocabulary,
          command, and status source, and that bare-metal writes apply at the next
          publication run;
        - "Capacity definitions": a bare-metal declaration carries its hardware in
          `capacity` and `attributes` with `units: 1`.
      - `docs/development/TESTING.md`: "Multi-Domain Storefront Composition" names
        the override route service's split between kit and storefront tests.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The compute-family schema has one owner, `domains/compute`, not the foundation kit or the core | `openspec/specs/market-composition/spec.md` (ADDED requirement); rationale in `openspec/specs/market-composition/architecture.md`; layer in `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| `unflatten_shape` is the exact inverse of `flatten_shape` | `openspec/specs/market-composition/spec.md#requirement-family-grouped-capability-shapes-share-one-flattening-contract` |
| A bare-metal listing's shape is derived from its declaration; `units` exactly 1 and `gpu` required; publication-only data is not a source | `openspec/specs/storefront-publication/spec.md`; rationale in its `architecture.md` |
| Shape fields published top-level under compute flat names; region from the pool hint, held when absent | `openspec/specs/storefront-publication/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` capacity definitions |
| Derivation identity includes the shape digest; old keys close as `source_gone` | `openspec/specs/storefront-publication/spec.md`; rationale in its `architecture.md` |
| One whole unit held exclusively; the claim carries shape attributes | `openspec/specs/storefront-publication/spec.md`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| Minimal opening recheck of shape and region | `openspec/specs/storefront-publication/spec.md` |
| Override route service in the kit, FastAPI binding per storefront; after-write effects conditional | `openspec/specs/storefront-publication/spec.md` (MODIFIED live-projection requirement); `openspec/specs/storefront-publication/architecture.md#storefront-pool-overrides` |
| Bare-metal override vocabulary, command, and durable accepted-generation status | `openspec/specs/storefront-publication/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Payload kind unchanged; listing model names the schema's flat fields | Temporary: change history only (no permanent rule beyond the spec's published fields) |
| Combined shell registers no bare-metal override contribution | Temporary: holds until the shell publishes bare metal; recorded in `design.md` |
| Roadmap and campaign index | Filled in at 12.5 and 12.6 |
