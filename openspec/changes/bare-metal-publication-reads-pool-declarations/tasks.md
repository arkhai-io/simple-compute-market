# Tasks — bare-metal publication reads pool declarations

Planned. Unblocked. On Goal 7's critical path.

Paths below are relative to the repository root. `DM` is
`domains/bare_metal/src/arkhai_bare_metal/`; `SF` is
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`.

Validation levels are named deliberately. Per `docs/development/TESTING.md`,
integration means real persistence and the component's real wiring, with a controlled
double only where this codebase wraps an external process boundary: here, each site
authority's client and the registry client. New storefront tests that use a real
database go under `domains/bare_metal/storefront/tests/integration/`, following the
layout rule; the storefront's flat test directory is not reorganized otherwise.

## 1. Design

- [x] 1.1 **Decision gate.** Decide how listings bound before the common key included
      the pool are reconciled. Decided during design: no deployed bare-metal database
      holds one, so no fallback or carry-over is built; a development database fails
      forward (`design.md`, "No deployed bare-metal database needs an upgrade path").

## 2. Domain package: pure derivation, no database

Decision: "The domain package loses its database access" and "Candidates come from the
resource-pool projection".

- [ ] 2.1 `DM/publication.py` — keep `trusted_bare_metal_projection` as the parser of a
      site's resource-pool projection response (`revision`, `digest`,
      `resource_pools`), retaining unavailable resources so availability closes can be
      told apart from source withdrawal. Remove `bare_metal_listing_key` and
      `_length_prefixed`, the domain-table key.
- [ ] 2.2 `DM/storefront_publication.py` — rewrite as pure functions: derive candidates
      from a `TrustedBareMetalProjection` given the caller's set of admitted pool ids,
      returning the available candidates (each with `site_id`, `pool_id`,
      `physical_resource_id`, `listing_resource`, and `listing`) and the Physical
      Resources present but unavailable; and hold the listing comparison — identity
      fields, term fields, and the refreshed resource — beside it. Remove every
      function that reads or writes `derived_bare_metal_listings` and the
      `core_storefront.sqlite_client` imports that served them.
- [ ] 2.3 `DM/storefront_adapter.py` — rebuild `bare_metal_publication_adapter` to take
      its source callbacks (`open_keys`, `close_stale`, `available_candidates`,
      `record_published`, `reopen_existing`) from the storefront, as VM's
      `vm_publication_adapter` does, keeping `skip_keys` on the candidate's
      `derivation_key`. `DM/domain_runtime.py`'s `_publication_source` is unchanged
      except for the keyword arguments it forwards.
- [ ] 2.4 `DM/__init__.py` — remove the exports 2.1–2.2 delete and export the new pure
      functions.
- [ ] 2.5 `domains/bare_metal/pyproject.toml` — version `0.5.0`: removing public
      functions is a breaking change under `docs/development/RELEASING.md`'s SemVer policy.

## 3. Storefront package: projection reads, declarations, and the kit runtime

- [ ] 3.1 `SF/publication_service.py` (new) — decision "Bare metal adopts the kit
      publication runtime":
      - `BareMetalPublicationHooks`: `validate_candidate` checks the payload's
        `offering_mode` equals the binding's; `binding_for_listing` builds
        `CapacityBinding(site_id, "bare_metal", physical_resource_id)` from
        `load_listing_binding`, returning `None` for a listing with no binding and
        refusing one not recorded as backed;
      - `build_publication_runtime(sqlite_client, registry_client_factory, *,
        registry_url, storefront_url)`;
      - a registry client factory building the core `MultiRegistryClient` over the one
        configured registry from `BARE_METAL_STOREFRONT_REGISTRY_URL`,
        `BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY`, and
        `BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS`. No configuration surface changes.
- [ ] 3.2 `SF/sqlite_client.py` — extract the listing binding and derivation key that
      `upsert_bare_metal_listing` builds into one method both it and the publication
      cycle call, so a candidate's key and a persisted listing's key cannot differ.
      Rewrite `count_open_bare_metal_resources` over `storefront_listing_bindings` for
      the `bare_metal` offering mode, joined to open, unpaused listings.
- [ ] 3.3 `SF/publication.py` — rewrite as `BareMetalPublicationCycle`, constructed with
      the SQLite client, the domain registry, a mapping of site id to that site's
      capacity client, the runtime's registry client factory, a payload builder, and
      the storefront URL, and returning a report of every publish, refresh, reopen,
      close (with its reason), hold, refusal, and convergence. One run:
      - fetches each site's `resource_pool_projection()` through its own client; a site
        whose fetch fails is unknown and reported (decision "A site whose projection
        cannot be fetched holds its listings");
      - resolves each site's pools with `read_site_declarations`: a pool not
        advertising `bare_metal` or disabled admits nothing, an unresolvable pool is
        held, and an unbacked pool is refused and reported by name;
      - derives candidates through 2.2 and attaches each derivation key through 3.2;
      - runs the core `run_publication_cycle` over the source 2.3 builds, bridging its
        synchronous callbacks to the event loop as VM's cycle does;
      - new listing: `upsert_bare_metal_listing`, then the runtime's `publish`;
      - existing listing, found by `load_listing_binding_by_derivation`: leave a
        seller's close; close a diverged identity; otherwise write the fresh terms
        locally and then call the runtime's `publish` (open) or `reopen` (closed);
      - closes, through the runtime's `reconcile`, every open bare-metal listing at a
        site whose projection was fetched and in a pool not held, whose key no
        candidate carries — reason `source_gone` — and every one whose Physical
        Resource is unavailable — reason `unavailable` (decision "Availability closes
        stay distinguishable from source withdrawal");
      - ends with the runtime's `converge`.
      Keep `build_bare_metal_publication_selection`, now passing the cycle's callbacks
      to the source, and remove `run_bare_metal_publication`, which the cycle replaces.
- [ ] 3.4 `SF/publication_cli.py` — reduce to wiring: build the runtime from the
      environment, take each site's client from `runtime.capacity_client.site(...)`,
      build the payload builder from the settlement composition and the existing
      publication environment, run one cycle under `asyncio.run`, and print its report.
      Remove `_projections`, `_whole_resource_available`, `_registry`, and
      `_publish_registry_listing`.
- [ ] 3.5 `SF/migrations.py` — add `bare-metal-storefront-0010-drop-derived-publications`,
      dropping `derived_bare_metal_listings` and its two indexes. Leave 0002, 0006, and
      0009 in place (decision "Listings are tracked by the common binding").
- [ ] 3.6 `SF/runtime.py` — the health check fetches each site's
      `resource_pool_projection_version()` through that site's client and reports each
      site's result under `site_projection` (decision "The health check reads each
      site's projection").
- [ ] 3.7 `domains/bare_metal/storefront/pyproject.toml` — version `0.5.0`; depend on
      `arkhai-bare-metal>=0.5.0`, `arkhai-kit-capacity-publication==0.2.0`, and
      `arkhai-kit-resource-pools>=0.4.0`, the current release exporting `read_site_declarations`,
      which the storefront now imports directly.
      `domains/bare_metal/storefront/Makefile` — add
      `arkhai-kit-capacity-publication` to `reinit`.
      `domains/bare_metal/storefront/Dockerfile` — pin `arkhai-bare-metal-storefront==0.5.0`.

## 4. Consumers and locks

- [ ] 4.1 `domains/vms/storefront/pyproject.toml` — `arkhai-bare-metal>=0.5.0` and
      `arkhai-bare-metal-storefront==0.5.0`; `domains/vms/storefront/Dockerfile` — the same
      storefront pin. The combined storefront installs the bare-metal contribution but
      builds only its own publication source, so no VM code changes.
- [ ] 4.2 `domains/vms/storefront/tests/unit/test_compute_allocations.py` — remove
      `test_vm_schema_does_not_create_bare_metal_listing_tables`, which guards a table no
      schema will contain.
- [ ] 4.3 Regenerate, against a freshly built `.dist`, every lock recording a bare-metal
      package: `domains/bare_metal/uv.lock`, `domains/bare_metal/storefront/uv.lock`,
      `domains/bare_metal/buyer/uv.lock`,
      `domains/bare_metal/provisioning/adapter/uv.lock`, `domains/vms/storefront/uv.lock`,
      `domains/vms/provisioning/adapter/uv.lock`, `provisioning/compute/service/uv.lock`,
      and `e2e-tests/uv.lock`.

## 5. Tests

- [ ] 5.1 **Unit** `domains/bare_metal/tests/test_publication.py` — remove the key tests
      2.1 retires; keep the projection-parser tests and add one retaining an unavailable
      resource.
- [ ] 5.2 **Unit** `domains/bare_metal/tests/test_storefront_publication.py` — rewrite
      over the pure functions: an admitted pool's available resources become candidates;
      an unadmitted pool's resources do not; an unavailable resource is reported, not a
      candidate; identity and term comparison, including a changed pool.
- [ ] 5.3 **Unit** `domains/bare_metal/tests/test_storefront_adapter.py` — rewrite for the
      callback-built source.
- [ ] 5.4 **Integration** `domains/bare_metal/storefront/tests/integration/__init__.py` and
      `domains/bare_metal/storefront/tests/integration/test_publication.py` — the cycle
      over a real storefront database, per-site client doubles returning projection
      documents, and a recording registry client. Replaces
      `domains/bare_metal/storefront/tests/test_publication.py`, which is tombstoned; its
      module-attribute patching gives way to constructor injection. Scenarios:
      - a pool advertising `bare_metal` publishes; one that stops, or is disabled, closes
        its listing as `source_gone`;
      - an unresolvable pool's listing is neither closed nor refreshed;
      - an unbacked pool yields no listing and is reported;
      - a site whose projection fetch fails keeps its listings open while another site
        reconciles;
      - a new listing whose local write fails reaches no registry;
      - a registry that misses a close, and one left closed by a failed reopen, are each
        repaired by the next run alone;
      - a Physical Resource moved to another pool closes its listing and publishes a
        successor under the new pool's binding;
      - a listing bound under the legacy key closes and its successor publishes under the
        common key;
      - a leased resource's listing closes as `unavailable` and reopens when free; a
        seller's close is left closed; a changed term refreshes in place; a changed
        identity closes and is not reopened.
- [ ] 5.5 **Integration** `domains/bare_metal/storefront/tests/test_migrations.py` — replace
      `test_publication_migration_closes_unscoped_tracking_rows` with a test that the full
      migration sequence leaves no `derived_bare_metal_listings`, including on a database
      0002 populated; keep both retired-kind tests.
- [ ] 5.6 **Integration** `domains/bare_metal/storefront/tests/test_http_system.py` — the
      health check reports each site's projection and a failing site as an error.
- [ ] 5.7 Run `make test-bare-metal`, `make test-storefront`, and the VM storefront suite
      the combined deployment depends on, then `make check-reinit`, resolving every gap.

## 6. Permanent documentation

- [ ] 6.1 `docs/bare-metal-seller-quickstart.md` — publication reads each site's
      resource-pool projection; a pool must advertise `bare_metal`, be enabled, and be
      capacity-backed; a site that cannot be reached keeps its listings; every run
      repairs a registry that missed an update. The reset procedure's publish step is
      unchanged.
- [ ] 6.2 `openspec/specs/storefront-publication/architecture.md` — "Projection families":
      bare metal derives from the resource-pool projection's publication views, and why;
      "Listing identity": bare-metal listings are tracked by the common binding, so a pool
      move is an identity change; "Registry convergence": remove the sentence excluding
      bare metal.
- [ ] 6.3 `docs/development/ARCHITECTURE.md` — the capacity-publication section names bare
      metal beside VM and API credits as a contribution publishing through the kit runtime.
      Re-confirm `docs/development/DEPLOYMENT_AND_CONFIG.md`'s bare-metal publication
      sentences, which this change leaves accurate.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match.
      Read the changed files directly for provenance wording the target cannot catch. The
      local rationale to keep: why candidates come from the site's view rather than a
      storefront-built one; why an unreachable site holds its listings; why a listing is
      persisted before any registry is told; why a bare-metal binding's source is its
      Physical Resource.
- [ ] 7.2 **Import placement.** Review imports this change added or touched and move
      function-level ones to module level where no genuine circular import or documented
      lazy-load reason exists. Removing the domain package's database access removes its
      two storefront-extra local imports; verify no new one is needed there, since the
      domain package is installed without that extra. Verify against the real suites.
- [ ] 7.3 **Documentation compliance.** Re-check the accepted decisions against
      `openspec/README.md`'s placement table and confirm each landed where Section 6 and
      the promotion record say.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
      material validation evidence, deferred work, and permanent-documentation
      destinations.
- [ ] 7.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table in
      `docs/development/ROADMAP.md` and update the current-state sentence that says
      bare-metal publication reads no pool declaration.
- [ ] 7.6 **Campaign index currency.** Update this change's row and Goal 7's dependency
      graph in `openspec/changes/README.md`, marking `bare-metal-listing-shapes` unblocked.
- [ ] 7.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=bare-metal-publication-reads-pool-declarations` and
      resolve every match.
- [ ] 7.8 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record the
      run, its result, and the scenarios exercising this change. No end-to-end scenario
      runs `bare-metal-storefront publish` today, and `e2e_bare_metal_deal` skips unless its
      bare-metal environment is configured; record which ran and which skipped. If the
      bare-metal lane cannot run, record that as an explicit blocker naming the cause and
      its owner, and treat the validations it gates as unrun rather than passed.
- [ ] 7.9 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A listing advertises only a mode its pool authorizes, bare metal included | `openspec/specs/storefront-publication/spec.md` |
| An unbacked pool yields no bare-metal listing | `openspec/specs/storefront-publication/spec.md` |
| A held site holds bare-metal listings | `openspec/specs/storefront-publication/spec.md` |
| Registry convergence covers bare metal; a new listing is recorded locally before any registry is told | `openspec/specs/storefront-publication/spec.md` |
| Bare metal derives from the resource-pool projection, not the capacity projection | `openspec/specs/storefront-publication/architecture.md#projection-families` |
| Bare-metal listings are tracked by the common binding; a pool move is an identity change | `openspec/specs/storefront-publication/architecture.md#listing-identity` |
| Bare metal publishes through the kit runtime | `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition` |
| "Publication candidate" has one name | `docs/development/ARCHITECTURE.md` (added during design) |
| No data migration or compatibility path for undeployed bare-metal state | Temporary, not promoted: the repository-wide additive-schema rule in `docs/development/ARCHITECTURE.md` governs from bare metal's first deployment |
