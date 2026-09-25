# Tasks — bare-metal publication reads pool declarations

Planned. Unblocked. On Goal 7's critical path.

Paths below are relative to the repository root. `DM` is
`domains/bare_metal/src/arkhai_bare_metal/`; `SF` is
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`; `VS` is
`domains/vms/storefront/src/market_storefront/`.

**What the tests prove.** Under `docs/development/TESTING.md`, a controlled double belongs
only at an external boundary — a subprocess, a service this repository does not own, a
blockchain RPC. The site authority and the registry are this repository's own services, so
the publication-cycle tests in Section 6, which replace them with doubles, prove
orchestration and persistence behaviour and nothing about either service's contract. The
contract is covered separately: the resource-pool projection and bare-metal view contract
fixtures are validated against the real producer (6.2, 6.3), and a composition test proves
the command hands the cycle each site's real client (6.9). No end-to-end lane runs
bare-metal publication (8.8).

New storefront tests that use a real database go under
`domains/bare_metal/storefront/tests/integration/`, following the layout rule; the
storefront's flat test directory is not reorganized otherwise.

## 1. Design

- [x] 1.1 **Decision gate.** Decide how listings bound before the common key included
      the pool are reconciled. Decided during design: no deployed bare-metal database
      holds one, so no fallback or carry-over is built; a development database fails
      forward (`design.md`, "No deployed bare-metal database needs an upgrade path").

## 2. Projection rows name their pool `pool_id`

Decision: "The site's projections name the pool `pool_id`" — one step, the site and every
reader together. Lands before Section 3, whose parser reads the renamed field.

- [ ] 2.1 `kit/site/src/market_site/projections.py` — emit `pool_id` in place of
      `resource_pool_id` on every resource-pool entry and every capacity-bucket row.
- [ ] 2.2 Rename every reader of the field to `pool_id`:
      `kit/resource-pools/src/market_resource_pools/site_declarations.py` (`_pool_id`),
      `kit/pool-overrides/src/market_pool_overrides/service.py` (two reads),
      `VS/services/site_projection_cache.py`, `VS/services/listing_sources.py`,
      `VS/negotiation_runtime.py`, `VS/services/shape_feasibility.py` (read and module
      docstring), and `domains/vms/listings/reconciler.py` (its four pool and bucket reads).
- [ ] 2.3 `kit/site-client/src/market_site_client/fixtures/resource_pools.py` — the
      canonical builders emit `pool_id`, and `validate_resource_pool_projection` requires it.
- [ ] 2.4 Versions, per `docs/development/RELEASING.md`'s SemVer policy, each an
      incompatible wire or read change at 0.x:
      - producers: `kit/site/pyproject.toml` `0.5.0`;
        `provisioning/compute/service/pyproject.toml` `0.4.0`, which serves the projection,
        with `provisioning/compute/service/Dockerfile`'s pin following;
      - readers: `kit/resource-pools/pyproject.toml` `0.5.0`,
        `kit/pool-overrides/pyproject.toml` `0.2.0`, `domains/vms/listings/pyproject.toml`
        (`arkhai-vms-listings`, which ships `domains/vms/listings/reconciler.py`) `0.3.0`, and
        `domains/vms/storefront/pyproject.toml` `0.7.0`, with
        `domains/vms/storefront/Dockerfile`'s `arkhai-vms-storefront` pin following;
      - fixtures: `kit/site-client/pyproject.toml` `0.6.0`.
- [ ] 2.5 Raise the floors of every released package that serves or reads the field, or whose
      tests build it through the fixture, so no released combination pairs a renamed side with
      an unrenamed one:
      - `provisioning/compute/service/pyproject.toml`: `arkhai-kit-site>=0.5.0`,
        `arkhai-kit-site-client>=0.6.0`;
      - `domains/vms/listings/pyproject.toml`: `arkhai-kit-resource-pools>=0.5.0`,
        `arkhai-kit-pool-overrides>=0.2.0`;
      - `domains/vms/storefront/pyproject.toml`: `arkhai-kit-resource-pools>=0.5.0`,
        `arkhai-kit-pool-overrides==0.2.0`, `arkhai-kit-site-client>=0.6.0`,
        `arkhai-vms-listings[pools,overrides]>=0.3.0`;
      - `e2e-tests/pyproject.toml`: `arkhai-vms-storefront>=0.7.0`.
      Packages that depend on a bumped package without reading the field —
      `kit/fulfillment`, `provisioning/compute`, `domains/apicredits/service`,
      `domains/apicredits/storefront`, and the VM buyer, settlement, and negotiation packages —
      keep their constraints; only their locks move (5.3).

## 3. Domain package: pure derivation, no database

Decisions: "The domain package loses its database access", "Candidates come from the
resource-pool projection", "Every resource falls into exactly one classification", and
"The containing pool is authoritative for a resource's pool".

- [ ] 3.1 `DM/publication.py` and `DM/projections.py` — `trusted_bare_metal_projection`
      parses one site's resource-pool projection response (`revision`, `digest`,
      `resource_pools`). A resource's pool is its containing entry's `pool_id`; a view naming
      a different pool rejects the generation. The containing resource's `enabled` is kept
      beside each view in the trusted generation. `BareMetalResourceProjection` is unchanged,
      being the producer's model too. Remove the fallbacks to the view's own pool and to a
      pool on the resource, `bare_metal_listing_key`, and `_length_prefixed`.
- [ ] 3.2 `DM/storefront_publication.py` — rewrite as pure functions. Given a trusted
      generation and the caller's per-pool admission (admitted, held, not admitted),
      classify every bare-metal resource as exactly one of candidate, unavailable, held, or
      withdrawn, each candidate carrying `site_id`, `pool_id`, `physical_resource_id`,
      `listing_resource`, and `listing`; and hold the listing comparison — identity fields,
      term fields, the refreshed resource — beside it. Remove every function that reads or
      writes `derived_bare_metal_listings` and the `core_storefront.sqlite_client` imports
      that served them.
- [ ] 3.3 `DM/storefront_adapter.py` — rebuild `bare_metal_publication_adapter` to take its
      source callbacks (`open_keys`, `close_stale`, `available_candidates`,
      `record_published`, `reopen_existing`) from the storefront, as VM's
      `vm_publication_adapter` does, keeping `skip_keys` on the candidate's
      `derivation_key`. `DM/domain_runtime.py`'s `_publication_source` is unchanged except
      for the keyword arguments it forwards.
- [ ] 3.4 `DM/__init__.py` — remove the exports 3.1–3.2 delete and export the new pure
      functions.
- [ ] 3.5 `domains/bare_metal/pyproject.toml` — version `0.5.0`: removing public functions
      is a breaking change under the SemVer policy.

## 4. Storefront package: projection reads, declarations, and the kit runtime

- [ ] 4.1 `SF/publication_service.py` (new) — decision "Bare metal adopts the kit
      publication runtime":
      - `BareMetalPublicationHooks`: `validate_candidate` checks the payload's
        `offering_mode` equals the binding's; `binding_for_listing` builds
        `CapacityBinding(site_id, "bare_metal", physical_resource_id)` from
        `load_listing_binding`, returning `None` for a listing with no binding and refusing
        one not recorded as backed;
      - `build_publication_runtime(sqlite_client, registry_client_factory, *,
        registry_url, storefront_url)`;
      - a registry client factory building the core `MultiRegistryClient` over the one
        configured registry from `BARE_METAL_STOREFRONT_REGISTRY_URL`,
        `BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY`, and
        `BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS`. No configuration surface changes.
- [ ] 4.2 `SF/sqlite_client.py` — extract the listing binding and derivation key that
      `upsert_bare_metal_listing` builds into one method both it and the publication cycle
      call, so a candidate's key and a persisted listing's key cannot differ. Rewrite
      `count_open_bare_metal_resources` over `storefront_listing_bindings` for the
      `bare_metal` offering mode, joined to open, unpaused listings.
- [ ] 4.3 `SF/publication.py` — rewrite as `BareMetalPublicationCycle`, constructed with
      the SQLite client, the domain registry, a mapping of site id to that site's capacity
      client, the runtime's registry client factory, a payload builder, and the storefront
      URL, and returning a report of every publish, refresh, reopen, close (with its
      reason), hold, refusal, and convergence. One run:
      - fetches each site's `resource_pool_projection()` through its own client; a site
        whose fetch fails, or whose generation 3.1 rejects, is unknown and reported
        (decision "A site whose projection cannot be fetched holds its listings");
      - resolves each site's pools with `read_site_declarations`: a pool not advertising
        `bare_metal` or disabled admits nothing, an unresolvable pool is held, and an
        unbacked pool is refused and reported by name;
      - classifies every resource through 3.2 and attaches each candidate's derivation key
        through 4.2;
      - runs the core `run_publication_cycle` over the source 3.3 builds, bridging its
        synchronous callbacks to the event loop as VM's cycle does;
      - new listing: `upsert_bare_metal_listing`, then the runtime's `publish`;
      - existing listing, found by `load_listing_binding_by_derivation`: leave a seller's
        close; close a diverged identity; otherwise write the fresh terms locally and then
        call the runtime's `publish` (open) or `reopen` (closed);
      - builds one `ReconciliationPlan` from the disjoint classes, at sites whose projection
        was fetched and accepted: every open bare-metal listing whose resource is
        withdrawn, or whose key no classified resource carries, closes as `source_gone`;
        every open listing whose resource is unavailable closes as `unavailable`; held
        listings are in neither;
      - ends with the runtime's `converge`.
      Keep `build_bare_metal_publication_selection`, now passing the cycle's callbacks to
      the source, and remove `run_bare_metal_publication`, which the cycle replaces.
- [ ] 4.4 `SF/publication_cli.py` — reduce to wiring: build the runtime from the
      environment, take each site's client from `runtime.capacity_client.site(...)`, build
      the payload builder from the settlement composition and the existing publication
      environment, run one cycle under `asyncio.run`, and print its report. Remove
      `_projections`, `_whole_resource_available`, `_registry`, and
      `_publish_registry_listing`.
- [ ] 4.5 `SF/migrations.py` — add `bare-metal-storefront-0010-drop-derived-publications`,
      dropping `derived_bare_metal_listings` and its two indexes. Leave 0002, 0006, and
      0009 in place (decision "Listings are tracked by the common binding").
- [ ] 4.6 `SF/runtime.py` and `SF/models.py` — decision "The health check reports each
      site's projection, as VM's does": fetch each site's
      `resource_pool_projection_version()` through its own client; add
      `site_projections: dict[str, dict[str, ProjectionFamilyStatus]] | None` to
      `BareMetalHealthResponse`, reusing core's `ProjectionFamilyStatus` under the family
      name `resource_pool`, `loaded` or `unavailable` per site; remove
      `checks["site_projection"]`; and make `checks["fulfillment"]` report only whether a
      fulfillment client is composed. No site's projection state enters a gated check.
- [ ] 4.7 `domains/bare_metal/storefront/pyproject.toml` — version `0.5.0`; depend on
      `arkhai-bare-metal>=0.5.0`, `arkhai-kit-capacity-publication==0.2.0`,
      `arkhai-kit-resource-pools>=0.5.0`, which the storefront now imports directly, and
      `arkhai-kit-site-client>=0.6.0`, whose fixtures its tests build from.
      `domains/bare_metal/storefront/Makefile` — add `arkhai-kit-capacity-publication` to
      `reinit`. `domains/bare_metal/storefront/Dockerfile` — pin
      `arkhai-bare-metal-storefront==0.5.0`.

## 5. Consumers and locks

- [ ] 5.1 `domains/vms/storefront/pyproject.toml` — `arkhai-bare-metal>=0.5.0` and
      `arkhai-bare-metal-storefront==0.5.0`; `domains/vms/storefront/Dockerfile` — the same
      storefront pin. The combined storefront installs the bare-metal contribution but builds
      only its own publication source, so no VM publication code changes for bare metal.
- [ ] 5.2 `domains/vms/storefront/tests/unit/test_compute_allocations.py` — remove
      `test_vm_schema_does_not_create_bare_metal_listing_tables`, which guards a table no
      schema will contain.
- [ ] 5.3 Regenerate, against a freshly built `.dist`, every lock recording a package this
      change bumps: `domains/apicredits/service/uv.lock`,
      `domains/apicredits/storefront/uv.lock`, `domains/bare_metal/uv.lock`,
      `domains/bare_metal/buyer/uv.lock`, `domains/bare_metal/provisioning/adapter/uv.lock`,
      `domains/bare_metal/storefront/uv.lock`, `domains/vms/buyer/uv.lock`,
      `domains/vms/provisioning/adapter/uv.lock`, `domains/vms/provisioning/client/uv.lock`,
      `domains/vms/storefront/uv.lock`, `e2e-tests/uv.lock`,
      `kit/capacity-publication/uv.lock`, `kit/fulfillment/uv.lock`,
      `kit/pool-overrides/uv.lock`, `kit/resource-pools/uv.lock`, `kit/site-client/uv.lock`,
      `kit/site/uv.lock`, `provisioning/compute/service/uv.lock`, and
      `provisioning/compute/uv.lock`. Re-run the search that produced this list after the
      bumps, in case a lock not listed here records a bumped package.

## 6. Tests

Rename (Section 2):

- [ ] 6.1 **Unit** `kit/resource-pools/tests/unit/test_site_declarations.py`,
      `kit/pool-overrides/tests/unit/test_status.py`, and **Integration**
      `kit/pool-overrides/tests/integration/test_service.py` — build projection rows with
      `pool_id`.
- [ ] 6.2 **Unit** `kit/site/tests/unit/test_projections.py` — both projections name the pool
      `pool_id` and no longer carry `resource_pool_id`. **Integration**
      `provisioning/compute/service/tests/integration/test_capacity_api.py` — the real
      projection, over the real typed client, passes the updated
      `validate_resource_pool_projection`.
- [ ] 6.3 Contract fixture for the bare-metal view: `DM/fixtures/__init__.py` and
      `DM/fixtures/publication_view.py` with `build_bare_metal_publication_view` and
      `validate_bare_metal_publication_view`, following `docs/development/TESTING.md`'s
      cross-package rule. The producer's
      `provisioning/compute/service/tests/unit/services/test_capacity_inventory.py` validates
      the view the service produces; bare-metal consumer tests build views from it, placed in
      `build_projected_resource`'s `publication_views`.
- [ ] 6.4 VM tests building projection rows move to `pool_id` — through the contract fixture
      where they construct whole projections: `domains/vms/storefront/tests/fake_site.py`,
      `domains/vms/storefront/tests/integration/test_abandon_truncation.py`,
      `domains/vms/storefront/tests/integration/test_admin_api.py`,
      `domains/vms/storefront/tests/integration/test_listings_api.py`,
      `domains/vms/storefront/tests/integration/test_negotiate_controller.py`,
      `domains/vms/storefront/tests/integration/test_shape_feasibility.py`,
      `domains/vms/storefront/tests/unit/services/test_site_projection_cache.py`,
      `domains/vms/storefront/tests/unit/test_listing_source_check.py`,
      `domains/vms/storefront/tests/unit/test_publications_wiring.py`,
      `domains/vms/storefront/tests/unit/test_reconciler.py`,
      `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`, and
      `domains/vms/storefront/tests/unit/test_sync_negotiation_hold_cap.py`.
- [ ] 6.5 After the rename, no `resource_pool_id` remains in any source, test, or permanent
      document outside `openspec/changes/archive/`; confirm with a repository search.

Bare-metal publication (Sections 3–4):

- [ ] 6.6 **Unit** `domains/bare_metal/tests/test_publication.py` — remove the key tests 3.1
      retires; add a view naming a different pool than its container rejecting the
      generation, and a disabled resource keeping `enabled=False` beside its view.
- [ ] 6.7 **Unit** `domains/bare_metal/tests/test_storefront_publication.py` — rewrite over
      the pure functions: each of the four classes, including a disabled resource whose view
      says unavailable classifying as withdrawn, not unavailable; no resource in two classes;
      identity and term comparison, including a changed pool.
- [ ] 6.8 **Unit** `domains/bare_metal/tests/test_storefront_adapter.py` — rewrite for the
      callback-built source.
- [ ] 6.9 **Unit** `domains/bare_metal/storefront/tests/test_publication_cli.py` (new) — the
      composition-boundary convention: the command hands the cycle each object
      `runtime.capacity_client.site(site_id)` returns, asserted by identity, and closes its
      registry transport.
- [ ] 6.10 **Integration** `domains/bare_metal/storefront/tests/integration/__init__.py` and
      `domains/bare_metal/storefront/tests/integration/test_publication.py` — integration in
      the sense `docs/development/TESTING.md` gives it for code with no application of its
      own: the cycle's public API against a real embedded database, with collaborators it does
      not own injected. The cycle over a real storefront database, per-site client doubles returning projections built from
      the contract fixtures, and a recording registry client. Replaces
      `domains/bare_metal/storefront/tests/test_publication.py`, which is tombstoned; its
      module-attribute patching gives way to constructor injection. Scenarios:
      - a pool advertising `bare_metal` publishes; one that stops, or is disabled, closes its
        listing as `source_gone`;
      - a disabled Physical Resource closes its listing as `source_gone`; a leased one closes
        as `unavailable` and reopens when free; the plan never names a listing twice;
      - an unresolvable pool's listing is neither closed nor refreshed;
      - an unbacked pool yields no listing and is reported;
      - a site whose projection fetch fails, or whose view names a different pool than its
        container, keeps its listings open while another site reconciles;
      - a new listing whose local write fails reaches no registry;
      - a registry that misses a close, and one left closed by a failed reopen, are each
        repaired by the next run alone;
      - a Physical Resource moved to another pool closes its listing and publishes a
        successor under the new pool's binding;
      - a listing bound under the legacy key closes and its successor publishes under the
        common key;
      - a seller's close is left closed; a changed term refreshes in place; a changed
        identity closes and is not reopened.
- [ ] 6.11 **Integration** `domains/bare_metal/storefront/tests/test_migrations.py` — replace
      `test_publication_migration_closes_unscoped_tracking_rows` with a test that the full
      migration sequence leaves no `derived_bare_metal_listings`, including on a database
      0002 populated; keep both retired-kind tests.
- [ ] 6.12 **Integration** `domains/bare_metal/storefront/tests/test_http_system.py` — every
      site answering reports each as `loaded` in `site_projections`; one of two failing reports
      that site as `unavailable` there while no gated check changes, following VM's
      `test_one_site_unavailable_is_reported_outside_the_health_gate`; `checks` carries no
      `site_projection` entry.
- [ ] 6.13 Run the suites of every changed package — `make test-kits`,
      `make test-bare-metal`, `make test-storefront`, the VM storefront suite, the
      `arkhai-vms-listings` suite, and `make test-provisioning` — then `make check-reinit`, resolving every gap.

## 7. Permanent documentation and cross-change text

- [ ] 7.1 `docs/bare-metal-seller-quickstart.md` — publication reads each site's
      resource-pool projection; a pool must advertise `bare_metal`, be enabled, and be
      capacity-backed; a disabled Physical Resource's listing closes; a site that cannot be
      reached keeps its listings; every run repairs a registry that missed an update; the
      health response reports each site. The reset procedure's publish step is unchanged.
- [ ] 7.2 `openspec/specs/storefront-publication/architecture.md` — "Projection families":
      bare metal derives from the resource-pool projection's publication views, why, and
      that the containing pool is authoritative; "Reconciliation": bare metal's four
      classes; "Listing identity": bare-metal listings are tracked by the common binding, so
      a pool move is an identity change; "Registry convergence": remove the sentence
      excluding bare metal.
- [ ] 7.3 `docs/development/ARCHITECTURE.md` — the capacity-publication section names bare
      metal beside VM and API credits as publishing through the kit runtime; "One name per
      concept" notes the site's projections name the pool `pool_id`. Re-confirm
      `docs/development/DEPLOYMENT_AND_CONFIG.md`'s bare-metal publication sentences, which
      this change leaves accurate.
- [ ] 7.4 `openspec/changes/pools-8-capacity-projection-and-listing-hints/design.md` — its
      bucket filter names `resource_pool_id`; name `pool_id`, so that active change is not
      left describing the retired spelling.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match.
      Read the changed files directly for provenance wording the target cannot catch. The
      local rationale to keep: why candidates come from the site's view rather than a
      storefront-built one; why enablement is read from the projected resource and not the
      view; why the containing pool wins; why a listing is persisted before any registry is
      told; and why a bare-metal binding's source is its Physical Resource.
- [ ] 8.2 **Import placement.** Review imports this change added or touched and move
      function-level ones to module level where no genuine circular import or documented
      lazy-load reason exists. Removing the domain package's database access removes its two
      storefront-extra local imports; verify no new one is needed there, since the domain
      package is installed without that extra. Verify against the real suites.
- [ ] 8.3 **Documentation compliance.** Re-check the accepted decisions against
      `openspec/README.md`'s placement table and confirm each landed where Section 7 and the
      promotion record say.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      material validation evidence, deferred work, and permanent-documentation destinations.
- [ ] 8.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table in
      `docs/development/ROADMAP.md` and update the current-state sentence that says
      bare-metal publication reads no pool declaration.
- [ ] 8.6 **Campaign index currency.** Update this change's row and Goal 7's dependency graph
      in `openspec/changes/README.md`, marking `bare-metal-listing-shapes` unblocked.
- [ ] 8.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-publication-reads-pool-declarations` and
      resolve every match.
- [ ] 8.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record the
      run, its result, and the scenarios exercising this change. No end-to-end scenario runs
      `bare-metal-storefront publish` today, and `e2e_bare_metal_deal` skips unless its
      bare-metal environment is configured; record which ran and which skipped. If closeout
      is blocked on the missing bare-metal publication lane, the next step is implementing a
      valid end-to-end test, which may land in this change; it is deliberately not planned
      here. Until then, treat the validations it gates as unrun rather than passed.
- [ ] 8.9 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A listing advertises only a mode its pool authorizes, bare metal included | `openspec/specs/storefront-publication/spec.md` |
| An unbacked pool yields no bare-metal listing | `openspec/specs/storefront-publication/spec.md` |
| A held site holds bare-metal listings | `openspec/specs/storefront-publication/spec.md` |
| Registry convergence covers bare metal; a new listing is recorded locally before any registry is told | `openspec/specs/storefront-publication/spec.md` |
| Projection rows name their pool `pool_id`; the containing pool is authoritative | `openspec/specs/site-capacity/spec.md` |
| Bare metal derives from the resource-pool projection, not the capacity projection | `openspec/specs/storefront-publication/architecture.md#projection-families` |
| Every bare-metal resource falls into exactly one class; enablement comes from the projected resource | `openspec/specs/storefront-publication/architecture.md#reconciliation` |
| Bare-metal listings are tracked by the common binding; a pool move is an identity change | `openspec/specs/storefront-publication/architecture.md#listing-identity` |
| Bare metal publishes through the kit runtime | `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition` |
| The site's projections name the pool `pool_id` | `docs/development/ARCHITECTURE.md#one-name-per-concept` |
| "Publication candidate" has one name | `docs/development/ARCHITECTURE.md` (added during design) |
| No data migration or compatibility path for undeployed bare-metal state | Temporary, not promoted: the repository-wide additive-schema rule in `docs/development/ARCHITECTURE.md` governs from bare metal's first deployment |
| The rename needs no transition while one operator deploys a storefront with its sites | Temporary, not promoted: its revisit trigger stays in `design.md` |
