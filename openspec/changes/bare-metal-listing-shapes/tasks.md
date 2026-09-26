# Tasks — bare-metal listing shapes

Unblocked: `bare-metal-publication-reads-pool-declarations` is complete. Sections 2, 4–8, 10.1–10.2,
10.4, and 11.1–11.3 are implemented. Open: 9.1–9.2 (VM storefront and VM buyer
relocks), 10.3 (typing, unrun), 11.4 (closeout-conditional), the review
follow-ups below, and section 12. Design review moved the pool-override work to
`publish-indicative-listing-rates` (its section 3b). Sections 3 and 7 below are kept
only as markers of that move.

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
- [x] 1.4 Resolve design review. Recorded in `design.md` ("Design review corrections",
      "The opening guard is a domain function the storefront calls", and "Joining the
      override store moved to `publish-indicative-listing-rates`"):
      - the VM commitment and VM-default paragraphs of the modified "Every VM listing
        is a listing shape" requirement say "VM listing" and "VM pool", resolving the
        contradiction with bare metal's whole-unit claim;
      - the opening guard's substance is a domain function, sequenced before §4a;
      - the override store work, the thin command, and the durable status record move
        to `publish-indicative-listing-rates` (its `design.md`, `proposal.md`, section
        3b of `tasks.md`, and its `storefront-publication` delta), with this change's
        working-tree override code reverted;
      - `bare-metal-and-credits-domain-stacks`' design carries a context note about the
        guard it inherits.

## 2. Compute-family schema and the shape utility

Decisions: "The compute-family capability schema gets one home" and
"`kit/capability-shape` gains a schema-driven inverse of flattening".

- [x] 2.1 `kit/capability-shape/src/market_capability_shape/__init__.py`: add
      `unflatten_shape(quantities, attributes, schema) -> dict`. It refuses, as
      `CapabilityShapeError` naming every problem:
      - a flat name the schema does not define, or defines as the other kind;
      - every problem `shape_problems` finds on the result.
      Export it. Bump `kit/capability-shape/pyproject.toml` to 0.2.0.
- [x] 2.2 `kit/capability-shape/tests/unit/test_capability_shape.py`:
      - round trip `flatten_shape(unflatten_shape(...)) ==` input, and the reverse,
        against a test schema;
      - digest equality between a derived and a hand-stated shape;
      - an unknown flat quantity or attribute is refused;
      - a flat name supplied as the wrong kind is refused;
      - a missing required field is refused.
      `test_import_boundary.py` stays green (standard library only).
- [x] 2.3 Create `domains/compute/` (distribution `arkhai-compute` 0.1.0, import
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
- [x] 2.4 `domains/compute/tests/`:
      - schema shape (families, kinds, required fields);
      - flat names against `DIMENSION_KEYS`;
      - an import-boundary test: the package imports only the standard library and
        `market_capability_shape`, and no `arkhai_vms`, `arkhai_bare_metal`, or
        `market_core`.
- [x] 2.5 `domains/vms/domain/src/arkhai_vms/compute_requirements.py`: re-export from
      `arkhai_compute`, binding `VM_CAPABILITY_SCHEMA = COMPUTE_CAPABILITY_SCHEMA`.
      `arkhai_vms/__init__.py`, `capability_shapes.py`, and `shape_generation.py` keep
      their imports unchanged.
      `domains/vms/domain/pyproject.toml`:
      - add `arkhai-compute>=0.1.0`;
      - bump to 0.5.0;
      - relock.
      `domains/vms/domain/tests/test_compute_requirements.py` gains an identity
      assertion: `VM_CAPABILITY_SCHEMA is COMPUTE_CAPABILITY_SCHEMA`.
- [x] 2.6 Focused: `make -C kit test-capability-shape`, `make -C domains/compute test`,
      and `make -C domains test-vms-domain`. All passed: 38, 6, and 38.

## 3. Pool-override kit route service — moved

Moved to `publish-indicative-listing-rates` section 3b. This change does not touch
`kit/pool-overrides` or VM's admin controller.

## 4. Bare-metal domain: listing, derivation, classification, identity

Decisions:
- "The shape is derived from the declaration";
- "The whole machine is one unit";
- "The nested `capabilities` mapping and the `site` labels are retired";
- "Region comes from the pool hint";
- "Derivation identity: the resource anchors it, the shape completes it";
- planning's "payload kind", "listing model", and "reconciliation matches resources
  before keys".

- [x] 4.1 `domains/bare_metal/src/arkhai_bare_metal/schema.py`, `BareMetalListing`:
      - remove `capabilities` and `site`;
      - add `gpu_count: int` (≥1), `gpu_model: str`, `vcpu_count`/`ram_gb`/`disk_gb:
        int | None` (≥1), and `region: str`, all non-blank;
      - set `model_config = ConfigDict(extra="forbid")`;
      - keep `kind` at `bare_metal.v2`;
      - add a `shape` property returning the family-grouped shape through
        `unflatten_shape`, and a `shape_digest` property.
- [x] 4.2 `domains/bare_metal/src/arkhai_bare_metal/projections.py`:
      `TrustedBareMetalResource` gains `declared_capacity: dict[str, Any]` and
      `declared_attributes: dict[str, Any]`, read from the containing projected
      resource. `publication.trusted_bare_metal_projection` populates them. The
      view's `capabilities` stays accepted on input so a site generation carrying it
      is not refused, but it is never read.
- [x] 4.3 New `domains/bare_metal/src/arkhai_bare_metal/shapes.py`:
      `derive_bare_metal_shape(declared_capacity, declared_attributes)` returns the
      shape or a `BareMetalShapeProblem` list. It covers:
      - `units` present and exactly 1;
      - every other capacity key a compute quantity;
      - positive-integer quantities;
      - GPU count and model required;
      - schema attribute names read from attributes and every other attribute ignored.
      It also reports a present `bare_metal_publication.capabilities` as ignored.
- [x] 4.4 `domains/bare_metal/src/arkhai_bare_metal/publication.py`:
      `available_bare_metal_listings` builds each listing from the derived shape and a
      supplied `region`, flattening through `COMPUTE_CAPABILITY_SCHEMA`. Remove the
      capacity/capabilities merge.
- [x] 4.5 `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py`:
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
- [x] 4.6 `domains/bare_metal/src/arkhai_bare_metal/fixtures/publication_view.py`: the
      default view carries no hardware in `capabilities`. Add
      `build_bare_metal_projected_resource(...)`, which returns a projected resource
      with declared `capacity` (`units: 1` plus hardware), declared `attributes`
      (`gpu_model`, `physical_host_id`, `allocation_mode`), and the view.
      `validate_bare_metal_publication_view` is unchanged.
- [x] 4.7 `domains/bare_metal/pyproject.toml`:
      - add `arkhai-compute>=0.1.0` and `arkhai-kit-capability-shape>=0.2.0`;
      - bump to 0.6.0;
      - relock.
      `domains/bare_metal/Makefile` reinit adds both packages.
- [x] 4.8 Tests under `domains/bare_metal/tests/`:
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
- [x] 4.9 `provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`
      and `tests/integration/test_capacity_api.py` pass against the new
      `arkhai-bare-metal` wheel. No edit is needed: they test that the site copies
      `bare_metal_publication.capabilities` into the view, which the site still does.
      Consumers now ignore that field, and the site's behaviour is unchanged.
- [x] 4.10 Evidence for 4.1–4.8: `make -C domains/bare_metal test` passes with 120
      tests, including the new `test_shapes.py` and new cases in `test_schema.py`,
      `test_publication.py`, `test_projections.py`, and
      `test_storefront_publication.py`. Two amendments: `pool_region` lives in the
      storefront, so the domain package takes no dependency on `kit/resource-pools`;
      and a listing contract fixture (`arkhai_bare_metal/fixtures/listing.py`) was
      added for consumers that need a valid listing.

## 5. Bare-metal storefront: publication

- [x] 5.1 `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py`:
      - `bare_metal_derivation_key` takes `shape_digest`;
      - `upsert_bare_metal_listing` writes source envelope schema version 2 with
        `shape_digest`, taken from the listing's own shape, so a listing can only be
        bound under the key its published fields imply.
      Bindings already carry `pool_id` and `physical_resource_id`, so no read-path
      change is needed. Evidence comes with 5.5.
- [x] 5.2 `.../publication.py`, `BareMetalPublicationCycle`:
      - `_pool_admission` also resolves each pool's region through a storefront
        `pool_region` helper (`raw_region` under VM's non-empty-string rule), holds
        and reports (`pool_region_missing`) a pool without one, and reports
        (`listing_shapes_not_applicable`) a pool stating `listing_shapes.bare_metal`;
      - `_classify_site` reports each unresolvable declaration (`declaration_unresolvable`
        with its problems) and each ignored `capabilities`
        (`publication_capabilities_ignored`);
      - `_key` includes the digest;
      - `_close_stale` matches by resource first, in the order recorded under
        "Reconciliation matches bindings by resource before key".
- 5.3 and 5.4 (override precedence, override migration, and the accepted-generation
  record) moved to `publish-indicative-listing-rates` section 3b.
- [x] 5.5 Tests:
      - `tests/test_publication_cycle.py`:
        - a declared-dimension correction closes and publishes a successor, leaving
          the original binding row unmodified;
        - a version 1 binding closes as `source_gone` with its successor published in
          the same run;
        - a region-less pool is held and reported;
        - an unresolvable declaration holds only its own listing;
        - `listing_shapes.bare_metal` is reported;
        - ignored `bare_metal_publication.capabilities` is reported.
      - `tests/test_persistence.py`: envelope version 2 and the digest-bearing key.
      - Every storefront test fixture that builds a listing gains region and GPU
        fields through `arkhai_bare_metal.fixtures.listing`.

## 6. Bare-metal storefront: claims and the opening guard

Decisions: "The whole machine is one unit" and "The opening guard is a domain
function the storefront calls".

- [x] 6.1 `.../fulfillment_service.py` and `.../hosted_lifecycle.py`: the reservation
      claim adds the listing's schema attributes (`gpu_model`) as top-level
      exact-match keys. Those are what `kit/site`'s `_split_claim_requirement` treats
      as required attributes. The values come from the trusted listing record
      (`load_bare_metal_listing_payload`). The claim keeps `dimensions: {"units": 1}`,
      `offering_mode`, and its resource or pool. No buyer-supplied value reaches it.
- [x] 6.2 New `domains/bare_metal/src/arkhai_bare_metal/inventory_guard.py`:
      `recheck_bare_metal_listing_source(generation, *, pool_admission, pool_regions,
      pool_id, physical_resource_id, shape_digest, region)`. It classifies the
      generation with `classify_bare_metal_resources` and returns `match`,
      `declared_mismatch` (differing digest or region, or a resource held for an
      unreadable declaration), or `absent` (missing, withdrawn, or its pool no longer
      admitting bare metal). It is pure: no I/O, no storefront types. Export it.
- [x] 6.3 Bare-metal storefront, as a thin wrapper in `.../publication.py`'s helpers
      or a small `.../opening_guard.py`: fetch the bound site's live projection
      through `runtime.capacity_client.site(site_id)`, build the trusted generation,
      resolve pool admission and regions with the same helpers publication uses,
      and call 6.2. `.../negotiation_service.py` calls it in `open` before the round
      hook and in `_open_exact_selection` before `_validate_physical_selection`.
      A mismatch or absence is refused with 409 `listing no longer matches its
      declaration`; an unreachable or unverified site with 503.
- [x] 6.4 Tests:
      - `tests/test_fulfillment_service.py`: the claim carries `gpu_model` from the
        trusted listing, and a context naming none reserves nothing. Its capacity
        double records and accepts every claim, so it proves construction only.
      - `tests/test_claims.py`: the claim run through `kit/site`'s exported matcher
        `dict_resource_satisfies_claim`. The site admits the published machine, and
        refuses once the declared model changes or the unit is taken. Hardware
        quantities are not requested. This ties the claim's spelling to the site's
        admission semantics.
      - `tests/test_http_negotiation.py` and `tests/test_http_settlement.py`: each
        guard outcome on both opening paths.
      - `domains/bare_metal/tests/test_inventory_guard.py` (new): every outcome of the
        pure function.

## 7. Bare-metal storefront: overrides — moved

Moved to `publish-indicative-listing-rates` section 3b.

The version bumps and the import-boundary task formerly here remain in this change:

- [x] 7.5 `domains/bare_metal/storefront/pyproject.toml`:
      - add `arkhai-compute>=0.1.0`;
      - raise `arkhai-bare-metal>=0.6.0` and `arkhai-kit-capability-shape>=0.2.0`;
      - bump to 0.6.0;
      - relock.
      `Makefile` reinit adds `arkhai-compute`. `Dockerfile` pins
      `arkhai-bare-metal-storefront==0.6.0`.
- [x] 7.6 Amended: asserting that the storefront imports `arkhai_compute` proves
      nothing. Instead, `domains/bare_metal/tests/test_import_boundary.py` asserts
      the domain package imports no VM package. The storefront's existing
      VM-import test is unchanged and passes.

## 8. Bare-metal buyer

Decision: planning's "`bare-metal list --resource`".

- [x] 8.1 `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`: `list` gains
      `--resource`. It fetches the registry's filter specification, compiles through
      `registry_client.query.compile_resource_query`, and passes the compiled filters
      and ETag with `offering_mode=bare_metal`. `pyproject.toml`:
      - raise `arkhai-bare-metal>=0.6.0`;
      - bump to 0.3.0;
      - relock.
      `Makefile` reinit adds `arkhai-compute` and `arkhai-kit-capability-shape` if its
      lock installs them.
- [x] 8.2 `domains/bare_metal/buyer/tests/test_buyer_composition.py`: a query compiles
      against a filter-spec fixture, an unknown field is refused before any request,
      and the ETag is sent.

## 9. Combined shell and remaining consumers

- [ ] 9.1 `domains/vms/storefront/pyproject.toml`:
      - `arkhai-bare-metal-storefront==0.6.0`;
      - `arkhai-bare-metal>=0.6.0`;
      - `arkhai-vms>=0.5.0`.
      Relock. `domains/vms/storefront/Dockerfile` line pinning
      `arkhai-bare-metal-storefront==0.5.0` becomes `0.6.0`. Its Makefile reinit adds
      `arkhai-compute`.
- [ ] 9.2 Relock, and add `arkhai-compute` to reinit, for every other lock that now
      installs it: `domains/vms/buyer`, `domains/vms/provisioning/adapter`,
      `domains/bare_metal/provisioning/adapter`, `provisioning/compute/service`, and
      `e2e-tests`. Also add `arkhai-kit-capability-shape` where it is newly
      installed.

## 10. Build, packaging, and reinit

- [x] 10.1 `domains/Makefile`:
      - add `dist-compute` (`cd compute && uv build`, with the platform-wheel guard)
        and `test-compute`;
      - add `dist-compute` to `dist`;
      - make `dist-vms` and `dist-bare-metal` depend on it.
      Root `Makefile`:
      - add `test-compute` beside `test-vms-domain`, and to `test`;
      - add both new targets to `.PHONY`.
- [x] 10.2 `make dist-ci` builds cleanly, and `unzip -l` shows each changed wheel's
      contents: `arkhai_compute`, `market_capability_shape`, `arkhai_bare_metal`, and
      `arkhai_bare_metal_storefront`, with
      no test or fixture leakage beyond the published `fixtures` package.
- [ ] 10.3 Typing: `py.typed` present in `arkhai_compute`. Run the repository's
      configured type checks for the touched packages, or disclose any not configured.
- [x] 10.4 `make check-reinit` passes.

## 11. End-to-end and operator documentation

- [x] 11.1 `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py`:
      - `_whole_host` declares `capacity: {units: 1, gpu_count: 8, ram_gb: 2048}` and
        `attributes: {gpu_model: H200, physical_host_id, allocation_mode,
        bare_metal_publication: {enabled, access_methods}}`, registered through
        `register_resource(capacity=...)`;
      - the advertised pool's `policy_tags` gain `region`;
      - Stage 03 also finds the listing through `bare_metal_registry.list_listings`
        with `gpu_model` and `gpu_count` filters, and asserts the published fields;
      - a new stage adds a dark pool without a region and asserts the `hold` report.
- [x] 11.2 `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py`:
      it is selected by neither lane. Update any declaration it documents or builds to
      the new rules, so it is not stale when a lane selects it.
- [x] 11.3 `docs/bare-metal-seller-quickstart.md`:
      - the registration body carries hardware in `capacity` and `attributes`;
      - `bare_metal_publication` keeps `enabled` and `access_methods` only;
      - the pool document gains `region`;
      - the round's bullet list names the region hold and the unresolvable-declaration
        hold.
- [ ] 11.4 If `bare-metal-mock-provisioned-deal` is still unplanned when this change
      completes, append a context line to its `design.md` stating that bare-metal
      declarations carry hardware in `capacity` and `attributes` with `units: 1`.

## Implementation evidence and deviations (sections 4–11)

- **Suites, all passing from a fresh reinit:**
  - `kit/capability-shape`: 38;
  - `domains/compute`: 6;
  - `domains/vms/domain`: 38;
  - `domains/bare_metal`: 131;
  - `domains/bare_metal/storefront`: 169;
  - `domains/bare_metal/buyer`: 14;
  - `domains/vms/provisioning/adapter`: 39;
  - `domains/bare_metal/provisioning/adapter`: 2;
  - `provisioning/compute/service`: 666 unit and 272 integration, with no edit
    (task 4.9).
  `make check-reinit` passes. `make check-comment-hygiene` passes.
- **e2e unit suite:** 237 pass. One failure,
  `test_hosted_public_boundary.py::test_buyer_deployment_mounts_separate_profile_state_and_credential`,
  renders `docker-compose.yml`, which this change does not touch. It is outside
  this change.
- **Unrun:**
  - The VM storefront and VM buyer suites (9.1–9.2). Their locks cannot be
    re-resolved in the implementation environment because `download.pytorch.org`
    is not reachable, and their `rl` extra resolves torch from it. Their pins and
    reinit lines are updated. Relock both with `uv lock` in a networked checkout
    and run `make -C domains test-storefront test-vms-buyer` before closeout.
  - Typing: only `core/` configures a type check, so none ran for the touched
    packages.
  - The end-to-end lanes (12.8).
- **Deviations from the plan:**
  - **One guard call.** `open()` runs the guard once, before the Alkahest and
    hosted paths branch, rather than at two call sites.
  - **`site_reading.py`** (shared by publication and the guard) and **`claims.py`**
    (the whole-machine claim, shared by both reservation paths) are new storefront
    modules the plan did not name.
  - **Claimed attributes** reach the claim through the fulfillment context's
    `claimed_attributes`, taken from a new `BareMetalListing.claimed_attributes`
    property.
  - **Hold reasons** take precedence in this order: `pool_region_missing`, then
    `declaration_unresolvable`, then `pool_unresolvable`.
  - **The VM storefront wheel stays at 0.7.0.** Only its pins changed, and every
    consumer's reinit reinstalls it.
  - **Missing site authority.** An opening with no configured site authority is
    refused with 503. A bare-metal storefront therefore refuses a negotiation it
    could never admit, consistent with the VM storefront; accepted in review of
    the implementation.
- **Test harness:** `tests/source_sites.py` is a site-authority double built from
  the site-client and bare-metal contract fixtures, answering the projection a
  seeded listing came from.
- **Lock hygiene:** relocks that recorded absolute wheel paths were restored to
  each project's committed relative path, and `uv lock --check` passes for each.

## Review follow-ups (post-implementation review)

- [x] R.1 Correct 6.4's evidence note, which overstated what the capacity doubles
      prove, and add the site-matcher contract tests in `tests/test_claims.py`.
- [x] R.2 Correct this file's status line.
- [x] R.3 Stale internal pins. Bumping `arkhai-kit-capability-shape` and
      `arkhai-vms` left eight consumer locks pinning wheels a clean `.dist` no
      longer holds; this failed both e2e lanes at setup. `uv lock` keeps a pin that
      still satisfies its constraint, so each consumer must be relocked with
      `--upgrade-package`.
      - Relocked here: `domains/apicredits/service`,
        `domains/vms/provisioning/client`, `kit/fulfillment`, `kit/resource-pools`,
        `kit/site`, and `provisioning/compute`. Their suites pass: 34, 255, 222,
        176, and 131; the client has no tests.
      - Added `make check-internal-locks` (`scripts/check_internal_locks.py`),
        which fails on any lock pinning an internal wheel version the tree does not
        build.
- [ ] R.4 Relock `domains/vms/buyer` and `domains/vms/storefront` with
      `--upgrade-package` for `arkhai-vms`, `arkhai-kit-capability-shape`,
      `arkhai-bare-metal`, `arkhai-bare-metal-storefront`, and (for the storefront)
      `arkhai-core-storefront-client`, where the PyTorch
      index is reachable. `make check-internal-locks` must pass.
- [ ] R.5 Move the raw-HTTP tests this change touched onto typed clients over the
      in-process app, keeping raw calls only for rejection paths.
      - `test_http_negotiation.py`: done. Every opening, refusal, and thread read
        goes through `negotiate_new`, `list_negotiations`, or `get_negotiation`,
        including the hosted opening (R.7). The unsigned request and the ambiguous
        nested-and-direct selection stay raw as rejection paths.
      - `test_http_system.py`: done. The listing reads go through `get_listing` and
        `list_listings`. The unsigned pause and run-cycle requests stay raw as
        rejection paths.
      - The conversion surfaced and fixed two production defects:
        - The negotiate-new, negotiate-continue, and settle routes verified
          signatures against a re-serialized model, so the canonical client's
          explicit `null`s failed. They now verify the body the caller sent.
        - The negotiation read routes were unauthenticated and unsigned. They now
          require the administrator's signed contract (`admin_list_negotiations`
          with the query bound into the resource, and `admin_get_negotiation`),
          matching the canonical client and VM.
      - Open, blocked on a placement decision:
        - `test_http_settlement.py`: the settle routes have canonical methods; the
          fulfillment routes' typed client is `BareMetalFulfillmentTransport`, in
          `arkhai-bare-metal-buyer`.
        - `test_http_introductions.py` and `test_introduction_delivery.py`: the
          introduction routes' typed calls live in `core_buyer`.
        Neither is a dependency of the storefront's tests.
- [x] R.7 The canonical client's `negotiate_new` gains `selection_only`. It is set
      explicitly, never inferred, so existing callers send what they sent before.
      It opens with a `settlement_selection` and a proposal carrying only `fields`,
      as a hosted or introduction buyer does, and refuses any escrow parameter
      stated beside it.
      - Both clients build the proposal through one shared helper, so they cannot
        drift.
      - `arkhai-core-storefront-client` is 0.21.0, and the provisioning service's
        exact pin moves with it.
      - Evidence: `core/storefront-client` 43 passed, including byte-identical async
        and sync selection-only requests, each refused escrow parameter, and the
        unchanged escrow form. The bare-metal hosted opening passes through the
        canonical client.
      - Consumers relocked: `domains/bare_metal/provisioning/adapter` (2 passed),
        `domains/vms/provisioning/adapter` (39), `provisioning/compute/service`
        (666 + 272), and `e2e-tests` (unit 237 passed, plus the unrelated compose
        failure). `domains/vms/storefront` also needs
        `--upgrade-package arkhai-core-storefront-client` in R.4.
- Evidence: `domains/bare_metal/storefront`, 174 passed. `make check-reinit`
  passes. `make check-internal-locks` flags only the R.4 VM locks.
- Reviewer prerequisite: running a package's `make test` from a fresh checkout
  needs `make dist-ci`, and for the bare-metal storefront also
  `make -C kit dist-hosted-settlement`, which `dist-ci` excludes.

## 12. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 12.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Then read directly for fuzzier provenance:
      - the moved schema comment in `arkhai_compute`;
      - the source-envelope version reader;
      - the upgrade-closing path in `_close_stale`;
      - the guard function's docstring and the storefront wrapper.
      None may say where something came from or which review asked for it.
- [ ] 12.2 **Import placement.** For imports this change adds or touches only:
      - the bare-metal buyer's new query-compilation imports sit at module level in
        `cli.py` unless a circular import is shown;
      - every new module-level import in `shapes.py`, `inventory_guard.py`, the
        storefront guard wrapper, and `arkhai_compute` is verified against the real
        suites;
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
        `arkhai_compute`;
      - `publish-indicative-listing-rates`' row names the bare-metal override adoption
        it now owns;
      - Goal 4's graph gains the edge that §4a follows this change.
      Record the update in the promotion record.
- [ ] 12.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-listing-shapes` and resolve every
      match, then run it unscoped to confirm no permanent document this change touched
      cites a missing path.
- [ ] 12.8 **End-to-end pipeline.** Run both lanes (`make run-e2e`, then
      `make fetch-e2e-logs`). Record:
      - the run ID and result;
      - that the bare-metal lane's publication scenario exercised discovery by
        `gpu_model` and `gpu_count`, and the region hold;
      - that the VM lane's `test_listing_shapes.py` passed on the re-exported schema.
      A pipeline blocked for an unrelated reason is recorded as a blocker naming its
      cause and owning change, and its validations are unrun.
- [ ] 12.9 **Promotion.** Complete the design-promotion record below and promote:
      - `openspec/specs/storefront-publication/spec.md`: the ADDED requirements and the
        MODIFIED requirement, plus the Evidence list entries for 4–6 and 8.
      - `openspec/specs/storefront-publication/architecture.md`: in "Listing shapes and
        the storefront's authority", replace "Bare-metal and API-credit publication do
        not use listing shapes" with the derived-shape model, the one-unit
        commitment, why the digest completes identity, and why the guard reuses
        classification.
      - `openspec/specs/market-composition/spec.md`: the ADDED and MODIFIED
        requirements, plus Evidence for `domains/compute` and `unflatten_shape`.
      - `openspec/specs/market-composition/architecture.md`: why the compute-family
        schema lives in a domain package rather than the foundation kit or the core,
        and that the flat-spelling gate edits it.
      - `docs/development/ARCHITECTURE.md`:
        - "Package and dependency layers": add the compute-family domain package
          between kit and the compute domains;
        - "Storefront capacity boundary": replace "Bare-metal and API-credit listings
          are not listing shapes", scope "the claim a listing produces reserves every
          quantity it publishes" to VM, and state bare metal's one-unit commitment;
        - "One name per concept": the listing-shape sentence covers derived shapes.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md` "Capacity definitions": a
        bare-metal declaration carries its hardware in `capacity` and `attributes`
        with `units: 1`.

## 13. E2E debugging

- [x] 13.1 Rebuild internal wheels and update
      `domains/bare_metal/storefront/uv.lock` and
      `domains/vms/storefront/uv.lock` to the current storefront-client wheel.
      Validate with `make check-internal-locks` and frozen dependency installation.
      Both pass. Bare-metal storefront: 174 passed. VM storefront: 1333 passed,
      one skipped; two Alkahest integration tests cannot start the local chain
      runtime. Baseline E2E run 36251858600 failed in both lanes on the missing
      storefront-client 0.20.0 wheel.
- [ ] 13.2 Run both lanes using `make run-e2e`, retrieve diagnostics with
      `make fetch-e2e-logs`, and fix observed failures with focused validation.
      Record the successful run and scenario evidence here.
- [ ] 13.3 Close out the debugging fileset: comment hygiene, touched import
      placement, documentation compliance and narrative compression, roadmap and
      campaign-index disposition, documentation citations, passing E2E evidence,
      and design promotion per section 12; run `make check-reinit`. Packaging-only
      corrections restore the existing architecture contract and need no new
      promotion or change-completion claim.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The compute-family schema has one owner, `domains/compute`, not the foundation kit or the core | `openspec/specs/market-composition/spec.md` (ADDED requirement); rationale in `openspec/specs/market-composition/architecture.md`; layer in `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| `unflatten_shape` is the exact inverse of `flatten_shape` | `openspec/specs/market-composition/spec.md#requirement-family-grouped-capability-shapes-share-one-flattening-contract` |
| A bare-metal listing's shape is derived from its declaration; `units` exactly 1 and `gpu` required; publication-only data is not a source | `openspec/specs/storefront-publication/spec.md`; rationale in its `architecture.md` |
| Shape fields published top-level under compute flat names; region from the pool hint, held when absent | `openspec/specs/storefront-publication/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` capacity definitions |
| Derivation identity includes the shape digest; old keys close as `source_gone` | `openspec/specs/storefront-publication/spec.md`; rationale in its `architecture.md` |
| One whole unit held exclusively; the claim carries shape attributes | `openspec/specs/storefront-publication/spec.md`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| Opening recheck of shape and region, as a domain function over classification | `openspec/specs/storefront-publication/spec.md`; rationale in its `architecture.md` |
| The VM commitment rule is scoped to VM listings | `openspec/specs/storefront-publication/spec.md` (MODIFIED "Every VM listing is a listing shape"); `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| Bare-metal negotiation reads require the administrator's signed contract; negotiation routes verify the body the caller sent | `openspec/specs/storefront-publication/spec.md` ("Scheme-neutral storefront authorization") |
| Pool-override work moved to `publish-indicative-listing-rates` | Superseded here; owned by that change's design and tasks |
| Payload kind unchanged; listing model names the schema's flat fields | Temporary: change history only (no permanent rule beyond the spec's published fields) |
| Roadmap and campaign index | Filled in at 12.5 and 12.6 |
