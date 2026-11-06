## 1. Reconcile landed projection foundations

- [x] 1.1 Verify independent site resource-pool and capacity-bucket producers, revisions/digests, pull endpoints, and in-memory storefront caches landed under POOLS-7.
- [x] 1.2 Remove rebuilt producer/polling/cache mechanics from this change and record remaining persistence/consumption scope in `proposal.md` and `design.md`.
- [x] 1.3 Resolve global versus site-scoped Resource Pool identity and record the durable/public key shape before schema work. **Resolved (`design.md`, "Resolved Questions"):** `pool_id` is a site-local operator slug; every durable or public reference this change introduces keys on `(site_id, pool_id[, resource_id])`, never `pool_id` alone.
- [x] 1.4 Inventory every `resources`, capacity-pool, CSV import, validator, publication, claim-building, admin, migration, and e2e reader; classify physical authority versus commercial/operational ownership. **Done (`design.md`, "Local physical-authority inventory"),** corrected twice later: Section 4 found one listing-creation path, not two (the CLI calls `create_listing`); Section 5 found `compute_capacity_pools`/`compute_pool_members` read live by `available_compute_slices`.

### Section 1 closeout

Investigation only, with no code, schema or tests. Its findings are in `design.md` and reach the permanent specifications through later sections: pool-identity scoping in `resource-pool-management/spec.md#requirement-domain-neutral-publication-and-hold-hints`.

## 2. Surface per-site projection load state (revised; no persistence layer)

The planned durable persistence layer was not built: no production code consumed the projection caches yet, so the restart-time gap it targeted had no consumer (`design.md`, "Section 2 revised decision" and "Section 2 design discussion").

- [x] 2.1 Add per-`(site_id, projection_kind)` load-state fields to the storefront's existing operator status surface, following the existing `resource_count`-diagnostic pattern. **Done:** `site_projection_cache.projection_status_summary()` is reported by `SystemService.get_health` under `result["site_projections"]`; both `HealthResponse` models (`core_storefront.models.system_models` and `storefront_client.models`) declare the field; `ProjectionCache`/`ProjectionCacheView` track `fetched_at`.
- [x] 2.2 Confirm the poller already retries indefinitely on a site that has never successfully loaded, and add a regression test. **Done:** every failure path of `ProjectionCache.load()`/`refresh()` is caught internally; covered by `domains/vms/storefront/tests/unit/services/test_site_projection_cache.py`.
- [x] 2.3 Document "ignorance ≠ zero" for Section 4's future projection consumer. **Done:** `openspec/specs/site-capacity/spec.md#requirement-per-site-projection-load-state-visibility`.
- [x] 2.4 Add focused tests for per-site/family status reporting. **Done:** `test_system_service.py` uses constructor injection; HTTP round-trip integration tests in `test_admin_api.py`'s `TestHealthEndpoint`.
- [x] 2.5 Confirm POOLS-7 task 2.3's durability note is already satisfied. **Done:** closed in `pools-7-storefront-fulfillment-cutover/tasks.md`; no code needed here.
- [x] 2.6 **Superseded.** The task named `RemoteCapacityClient`, now `SiteCapacityClient` in `kit/site-client`. `test_capacity_api.py` proves `resource_pool_projection()` and `capacity_bucket_projection()` against a real in-process provisioning app, and `test_site_capacity_projection_version_endpoints_through_the_real_client` proves both `_version()` methods, including that each revision advances when its projection changes.

**Permanent documentation destination:** `openspec/specs/site-capacity/spec.md#requirement-per-site-projection-load-state-visibility`.

<details>
<summary>Original tasks 2.1–2.4 (persistence layer), superseded — kept for history</summary>

- [ ] ~~2.1 Add storefront migrations and repositories for trusted configured-site bindings and independent resource-pool/capacity-bucket generations.~~
- [ ] ~~2.2 Persist revision, digest, accepted value, fetched time, and stale/error state transactionally per `(site_id, projection_kind)`.~~
- [ ] ~~2.3 Load complete stored generations as stale on restart before polling and replace one family without mutating the other.~~
- [ ] ~~2.4 Add migration, restart, partial-refresh, malformed-payload, revision-reset, and stale-retention tests.~~

</details>

### Section 2 closeout

- [x] Comment hygiene: clean (`make check-comment-hygiene`, repository-wide, in Section 7).
- [x] Documentation compliance and promotion: "Per-site projection load-state visibility" promoted with scenarios and evidence.
- [x] Narrative compression: done in Section 7.

## 3. Project safe pool metadata

Design rationale: `design.md`, "Section 3 design"; defects found while implementing: "Section 3 implementation record".

- [x] 3.1 Define allowlisted pool label/enabled/mechanism/policy-tags/generic `pool_views` in the site resource-pool projection, mirroring the existing `publication_views` precedent. **Done:** `_POOL_METADATA_FIELDS`/`_project_pool_metadata` in `kit/site/src/market_site/projections.py`, threaded through `resource_pool_projection`, `SiteProjectionService` and `make_capacity_router`; the VM storefront client needed no change.
- [x] 3.2 Advance revision/digest on metadata changes; prove credentials/provider secrets are redacted. **Done:** both follow from `canonical_digest` and the allowlist; nested `policy_tags`/`pool_views` are deep-copied so a caller cannot mutate cached state.
- [x] 3.3 Preserve backward compatibility for older producers omitting additive metadata. **Done:** byte-identical output, proven by test.
- [x] 3.4 Add producer/router/client/cache contract tests. **Done:** 24 unit and 8 integration tests; the integration tests go through `SiteCapacityClient` and `ProvisioningClient`.
- [x] 3.5 Project configured VM size defaults (`default_vm_ram`/`vcpus`/`disk_size`) as a versioned `vm.ansible_pool_defaults.v1` entry inside `pool_views`. **Done:** the defaults gained persistence (schema migration, admin handler validation and wiring) and a shaping layer, with 37 tests; the view is gated on the pool's `mechanism` being `"ansible"`, not only on an `AnsiblePoolConfig` row existing.

### Section 3 closeout

- [x] Comment hygiene: clean (`make check-comment-hygiene`, repository-wide, in Section 7), and test docstrings state current behaviour only.
- [x] Documentation compliance and promotion: "Resource-pool projection metadata" promoted to `openspec/specs/site-capacity/spec.md` with its evidence.
- [x] Narrative compression: done in Section 7.

Regression at the time: 420 passed (`provisioning/compute/service` unit), 171 passed (integration), 145 passed (`kit/site`).

## 4. Map projections into commercial inventory

The mapping schema already existed (`derived_compute_listings`/`derived_bare_metal_listings`, with commercial fields on `listings` via `listing_id`); this section extends it. Design rationale and the rejected `use_projection: bool` redesign: `design.md`, "Section 4 design"; defects found while implementing: "Section 4 implementation record".

- [x] 4.1 Site-scoped derivation keys. `listing_resource_key`/`listing_pool_key` require and validate non-empty `site_id`; unmapped-listing fallback is dynamic (a listing's own mapping wins when present, `home_site` only when `configured_site_count == 1`, quarantined otherwise). Bare-metal confirmed already correctly site-scoped. **Done:** `derivation_key` is a length-prefixed encoding, collision-free for operator strings containing colons; `SQLiteClient` delegates the table's schema to `reconciler.py`. 35 new tests; 630 unit and 147 integration passing.
- [x] 4.2 Backfill/quarantine, revised from a migration-based approach to 4.1's own read-time fallback (a migration can't safely depend on live deployment config that changes after it runs). A legacy row not found is idempotent re-derivation, not data loss.
- [x] 4.3 Redirect `available_compute_slices`' structural capacity source to the site-resource-pool projection, opt-in (`site_pool_projection=None` default, byte-identical to prior behavior). **Done:** `gpu_model` carried end to end by the provisioning service; pricing, `region` and `sla` stay local-only (home-site pools only). A never-loaded projection (`None`) is distinct from a loaded zero (`[]`), and the projection's own `available` field wins over member availability; `TestRealOrchestrationCacheToReconciliation` proves the orchestration.
- [x] 4.4 Pinned-site `reserve()`. `AggregateCapacityClient.reserve()` gained `site: str | None = None`, dispatching to `_reserve_at_site`/`_reserve_by_placement`; applies to every listing with a known site mapping regardless of `listing_cardinality_mode`. **Done:** the admin `reserve_capacity` endpoint answers a live refusal 409, an unknown or stale site mapping 500, and a mapped site's transport failure 502. 9 new tests.
- [x] 4.5 Bare-metal parity. **Done:** bare metal has no `.reserve()` (no capacity reservation yet); `bare_metal_listing_key` takes 4.1's collision-free encoding.
- [x] 4.6 Regression proof that projections never participate in live admission/dispatch. **Done:** `aggregation.py` references no projection cache; a call-counting unit test and an end-to-end integration test prove a live refusal wins over a cached projection, and the test fails when the regression is injected.
- [x] 4.7 Move the buyer-facing site-authority HTTP client from `core_storefront.capacity_remote.RemoteCapacityClient` into `kit/site-client` as `SiteCapacityClient`, a package-layer violation 4.6's integration test exposed. **Done:** unreachable `subscribe()`/`emit_local()`/`bus` dropped; `AggregateCapacityClient`'s `sites` takes the narrower `SiteCapacityAuthority` protocol; every import site updated, with no compatibility alias. Final regression: `domains/vms/storefront` unit 738 and integration 152, `core/storefront` 92, `domains/bare_metal` 60, `domains/bare_metal/storefront` 44, `kit/site` 145, `kit/site-client` 9, `provisioning/compute/service` 603, `domains/apicredits/storefront` 51, all passing.
- [x] Outside the plan: `TestFulfillmentEvents` uses the typed storefront client (`notify_usage_started`, `notify_fulfillment_failed` added); `provisioning/compute/service` takes `arkhai-core-storefront` as a development dependency from the wheelhouse. Regression with every touched package installed: 1691 passed; the 6 failures each traced to a cause unrelated to this change.

### Section 4 closeout

- [x] Comment hygiene: clean (`make check-comment-hygiene`, repository-wide, in Section 7).
- [x] Documentation compliance: checked against `openspec/README.md`'s placement rules.
- [x] Narrative compression: done in Section 7.
- [x] Promotion: `openspec/specs/storefront-publication/spec.md` gained "Commercial mapping identity" and "Site-pinned claim routing"; `openspec/specs/site-capacity/spec.md` gained two scenarios and a paragraph. The promotion record's anchors match the generated requirement anchors.
- [x] One orchestration integration test for cache → reconciliation: `TestRealOrchestrationCacheToReconciliation`.

## 5. Implement advisory hints

`listing_cardinality_mode` formalizes the fungible-versus-specific-resource decision `available_compute_slices` made implicitly from local table membership. Design rationale, the Q1–Q4 investigation and the external review round: `design.md`, "Section 5 design", "External review round" and "Section 5 implementation record".

- [x] 5.1 Define `listing_cardinality_mode`/`max_reservation_hold_seconds` key constants, resolvers, and validation in `kit/resource-pools/hints.py`, wired into both write surfaces (bulk YAML and the individual pool admin API). **Done:** a shared `_require_valid_hold_preference` service method; 61 tests in `kit/resource-pools`, including a round trip through the HTTP API.
- [x] 5.2 Add VM and bare-metal listing-mode resolvers, wired into real candidate generation, in four parts:
  - [x] 5.2a Thread `policy_tags` into `resolve_vm_listing_mode` (`domains/vms/listings/`), with an operator-visible explanation for unrecognized values. **Done:** explanations are reported by `listing_mode_explanations()` on the operator status surface; an untagged pool's structural default depends on member count (single-member pools are specific-resource); bare metal has no resolver until its publication has a consumer for one.
  - [x] 5.2b Move fungible-mode candidate generation onto `site_capacity_buckets`. **Done:** a loaded bucket family's absence of a pool is an authoritative zero; only a family never loaded falls back to the resource walk. `SiteCapacityClient.capacity_bucket_projection()` has a wire-contract test.
  - [x] 5.2c Support `specific_resource` on multi-member pools: one row per enabled member instead of the `member_count == 1` special case. **Done:** the publish loop needed no change, proven by test.
  - [x] 5.2d Fix `record_derived_listing`'s `use_pool_key` collision, a prerequisite of 5.2c: specific-resource listings derived their key from `pool_id` alone. **Done:** `use_pool_key` is `pool_id is not None and resource_id is None`.
- [x] 5.3 Add API-credit hint interpretation only if a concrete consumer exists. **Deferred:** `domains/apicredits` has no `ResourcePool`/`policy_tags` concept.
- [x] 5.4 Cap storefront acceptance-hold TTL by a valid projected preference, VM only. Bare metal has no capacity-reservation flow; that belongs to `market-platform-bare-metal-10-storefront-composition`, which names this section's `reserve(site=...)` as a dependency. **Done:** `pool_id_for_listing` and `lookup_pool_policy_tags` read `policy_tags` live from the projection cache, never persisted; a test proves the capped TTL reaches `reserve()`.
- [x] 5.5 Add focused tests for all of the above. **Done:** including the loaded-empty bucket case, the explanation status surface, the hold-cap orchestration, and two provisioning-service integration tests. Final regression: 1830 passing across every touched package, 3 failures unrelated to this change.

### Section 5 closeout

- [x] Comment hygiene: clean (`make check-comment-hygiene`, repository-wide, in Section 7), with production and test files read for provenance language.
- [x] Import placement: the local imports kept `market_resource_pools` out of the buyer's import chain; the closeout fix round moved them to module level once they named `market_resource_pools_contracts` (Section 7).
- [x] Documentation compliance: checked against `openspec/README.md`'s placement rules.
- [x] Narrative compression: done in Section 7.
- [x] Promotion: `openspec/specs/resource-pool-management/spec.md` and `openspec/specs/storefront-publication/spec.md`, with evidence naming files that exist.

## 6. Retire superseded local physical authority

Retirement is column-level, not table-level, for `resources`/`compute_capacity_pools`. `region`/`sla` have no projection equivalent, and flipping the flag's default and deleting the code it gates in one change would leave no staged rollout. Findings, the region/SLA/pricing hint design and the split: `design.md`, "Section 6 design", "Region, SLA, and pricing move to resource-pool hints too", "Splitting Section 6 across two changes" and "Section 6 external review round 2".

**This change's scope: flip the default (6.0) and build the region/SLA/pricing hint mechanism (6.1–6.3).** Deleting the local-table path, CSV import, `hosts`/`compute_pool_members` and the flag moved to a separate change (6.4).

- [x] 6.0 Flip `use_site_projection_for_listings` to default `true`. **Done:** in `settings.toml`; every caller reads it; tests in both directions (`test_config_loader.py`).
- [x] 6.1 Region and SLA move to resource-pool hints: domain-neutral keys in `kit/resource-pools/hints.py` (`raw_region`, `sla_value`, SLA validated as a number); region has no override tier, SLA has the same three tiers as pricing. **Done:** VM resolvers in `domains/vms/listings/pool_descriptors.py`, configured through `PoolHintResolutionSettings`; `validate_sla_preference` on every write path `max_reservation_hold_seconds` uses.
- [x] 6.1a SLA trust gate, separate from the override chain: a storefront may never publish a site's self-reported SLA. **Done:** `[pricing].accept_pool_declared_sla`, default `false`.
- [x] 6.2 Pricing three-tier precedence (storefront override → pool hint → config default), family-grouped like `structured-capacity-requirements` for the `gpu` family; extending beyond `gpu` depends on that change. **Done:** `domains/vms/listings/pricing_resolution.py` resolves each field independently across the tiers, and a malformed hint field falls through like a missing one. The tier-3 admin endpoint was not built: CSV import still writes that tier, and the endpoint belongs to 6.4's change.
- [x] 6.3 Add focused tests for the new hint mechanism. **Done:** about 65 tests across `kit/resource-pools` and `domains/vms/storefront`; resolution covers pools with no local row and non-home-site pools. Regression after review round 2: 1755 passing, none failing because of this change.
- [x] 6.4 Deferred to its own change, with no trigger this document defines (sellers self-host, so there is no fleet-wide deployment signal). **Done:** `openspec/changes/archive/2026-10-13-pools-9-retire-local-physical-authority/`, including the pool-commercial-metadata admin endpoint CSV-import removal needs.

### Section 6 closeout

- [x] Comment hygiene: clean (`make check-comment-hygiene`, repository-wide, in Section 7).
- [x] Import placement: as Section 5.
- [x] Documentation compliance: checked against `openspec/README.md`'s placement rules.
- [x] Narrative compression: done in Section 7.
- [x] Promotion: `openspec/specs/resource-pool-management/spec.md` and `openspec/specs/storefront-publication/spec.md` carry the region/SLA/pricing precedence, the trust gate and per-field resolution, with evidence naming files that exist.

## 7. Plan closeout (per `openspec/README.md#plan-closeout-requirements`)

Listed in an earlier order; closeout works the parts in `openspec/README.md`'s order.

### Closeout return and fix round (2026-11-06)

A closeout run stopped at part 2 and returned the change to implementation; the owner
waived validation, review and triage of the fix round, and closeout resumed at `4e9cd63c7`.

- **What the fix round changed** (`4e9cd63c7`, comments and imports only, no behaviour). In
  `domains/vms/listings/src/arkhai_vms_listings/`: the four
  `market_resource_pools_contracts.hints` imports in `listing_cardinality_mode.py`,
  `pool_descriptors.py` and `pricing_resolution.py` moved to module level, since the
  contracts distribution is a required dependency and holds no pool authority
  (`domains/vms/buyer/tests/test_no_resource_pools_dependency.py` still guards the buyer);
  `resolve_vm_listing_cardinality_mode`'s docstring states the member-count default as an
  invariant rather than history; three module docstrings name the hints module where it
  lives; one spec citation takes its `#requirement-` anchor.
- **Its evidence**, on wheels rebuilt by `make dist-domains` (the suites install internal
  wheels from `.dist`, which `make test` does not rebuild): `make test-storefront` 1215 unit
  passed, 1 skipped, 527 integration passed; `make test-vms-buyer` 215 passed; full
  `make test`, `make check-packaging` and `make check-change` passed.
- **The documentation compliance fixes that run made** are in `design.md`: every
  promotion-record anchor resolves, superseded rows say so, and the two findings handed to
  this change are recorded as resolved elsewhere, each with its evidence.

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match; separately, direct-read every touched file for `AGENTS.md`'s fuzzier provenance-narration rule the tool can't catch mechanically. **Done (closeout, 2026-11-06, at `4e9cd63c7`):** `make check-comment-hygiene` passes repository-wide, and the comments the fix round rewrote state current behaviour. `pricing_resolution.py:110`'s "this domain, not `kit/resource-pools`, owns validating the shape it accepts" is accurate: the pool authority's write path validates only `pricing`'s rate lists (`validate_pricing_rates`).
- [x] 7.2 **Import placement.** Migrate local imports to module level wherever safe; verify each candidate move against the real test suite. **Done (closeout, 2026-11-06, at `4e9cd63c7`):** no import this change added is local without a reason. The buyer regression test's local `import domains.vms.listings`, after a `sys.modules` clear, is its subject and stays local, with a comment. `listing_shapes.py:219`'s local import came from `dev` (`9f095518c`), outside this part's scope.
- [x] 7.3 **Documentation compliance.** Re-check every accepted decision against `openspec/README.md`'s placement rules directly. **Done:** every promotion-record row resolves to its current heading, and no permanent-spec evidence line depends on a change document. The fix round changed only comments and import placement, so no permanent document's description changed.
- [x] 7.4 **Narrative compression.** Shorten completed-task notes to final behavior, material evidence, deferred work, and permanent destinations; move debugging narratives into `design.md` first. **Done (closeout triage, 2026-11-06):** every section's notes keep final behaviour, evidence, deferred work and destinations; the debugging and review history found only here moved to `design.md` ("Section 3 implementation record", "Section 4 implementation record", "Section 5 implementation record", "Section 6 external review round 2"); the rest was already there.
- [x] 7.5 **Promotion.** Complete the design-promotion record. **Done:**
  Archival uses `--skip-specs`: the specifications were synchronized by hand. Every delta's rule is in the permanent specs under the names they use now (`site-capacity`'s "Per-site projection load-state visibility" and "Resource-pool projection metadata"; `storefront-publication`'s "Commercial mapping identity", "Site-pinned claim routing" and "Domain-owned publication and hold hints"; `resource-pool-management`'s "Domain-neutral publication and hold hints" and "Reservation hold and SLA preference validation"), so merging the deltas would duplicate or collide with them. None of the three capabilities has an `index.md`. The design-promotion record gained the roadmap, campaign-index and `--skip-specs` rows; no companion or `ARCHITECTURE.md` edit is owed.
  - [x] 7.5.1 Projection load-state visibility and resource-pool projection metadata: promoted through Sections 2–4; no `architecture.md` change owed (7.5.4).
  - [x] 7.5.2 Commercial mapping, claim routing, and the projection-becomes-default decision, to `openspec/specs/storefront-publication/spec.md`. **Done:** the projection path becomes the storefront's default once it has parity with the local-table path it retains (`#requirement-projection-backed-listing-candidate-derivation`); the retirement boundary is `pools-9-retire-local-physical-authority`'s, not this change's.
  - [x] 7.5.3 Domain-neutral hint keys, domain-owned values, and pool-identity site-scoping, to `openspec/specs/resource-pool-management/spec.md`: promoted through Sections 1, 5, and 6.
  - [x] 7.5.4 `docs/development/ARCHITECTURE.md`: no change owed; its "storefront is not the source of truth for physical resources" already states the principle at the right level.
  - [x] 7.5.5 Strict `openspec` validation: `change/pools-8-capacity-projection-and-listing-hints`, `spec/resource-pool-management`, `spec/storefront-publication`, and `spec/site-capacity` each validate.

- [x] 7.6 **Roadmap currency.** Update the affected goal's current state and gap mapping in `docs/development/ROADMAP.md`, or record that no goal is affected. **Done (closeout, 2026-11-06): no edit owed.** Goal 1's current state already says storefronts consume physical facts through both projections and derive every listing from them. Since `pools-9-retire-local-physical-authority`, that is the only path rather than the default. No gap row names this change.
- [x] 7.7 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md`, or record that both are unchanged. Other rows' `Depends on` are left alone: archive cleanup releases dependents after the closeout gate. **Done (closeout, 2026-11-06):** the row is `in closeout`, its notes rewritten to say it closes out after the waived fix round and archives with `--skip-specs`, and after archival it links the archive directory. The campaign's graph (`POOLS-7 ──► POOLS-8 projection consumption`) still holds and is unchanged. No row lists this change in `Depends on`. `scripts/change-workflow check index` passes.
- [x] 7.8 **Documentation citations.** After promotion, run `make check-doc-citations CHANGE=pools-8-capacity-projection-and-listing-hints` and resolve every match, then `openspec validate pools-8-capacity-projection-and-listing-hints --strict`. **Done (closeout, 2026-11-06):** `make check-change CHANGE=pools-8-capacity-projection-and-listing-hints` passed every check, documentation citations and the pinned `openspec validate --strict` among them.
- [x] 7.9 **End-to-end pipeline.** Record the passing run the latest validation names, its result, and the scenarios that exercise this change, or an explicit blocker naming its cause and the change that owns it, with the validations it gates treated as unrun. **Done (closeout, 2026-11-06):** the latest validation, `reviews/03-validation.md`, passed at `f39af1197`: pipeline run 42226002048 of `e2e.yml` succeeded (e2e-vm 153 passed, 2 skipped; e2e-bare-metal 70 passed; e2e-apicredits 4 passed), and its local and Helm parts passed. The scenarios exercising this change's surfaces are `test_compute_dynamic_listings` and `test_listing_shapes` (vms lane) and `test_bare_metal_publication` (bare-metal lane), named by the files' content; the change's behaviour is proven chiefly by its unit and integration tests. No CI was owed: no section carries an `Owed by validation:` line. The run names `f39af1197`, not the commit closeout carries: the owner waived validation of the fix round at `4e9cd63c7` (workflow log seq 15), whose edits are comments and import placement only.
- [x] 7.10 **Packaging.** Run `make check-packaging` and resolve every failure it reports (a failure needing a code or lock change returns the change to implementation). **Done (closeout, 2026-11-06, at `4e9cd63c7`):** `make check-packaging` passed (locks, Python version, layout, and the layers, scope, dependencies and kinds rules). `make check-architecture-change` reports the change owns no architecture row. The change touched nothing under `.agents/`, `.claude/` or `.codex/`, so `make check-agent-skills` is not owed.
- [x] 7.11 **Archival.** Last, once every other part is checked: `openspec archive pools-8-capacity-projection-and-listing-hints --skip-specs -y` moves the change under `openspec/changes/archive/` without merging its deltas, which 7.5 synchronized by hand; point the index row at the archived directory, and run `openspec validate --specs --strict`.
