## 1. Prerequisite acceptance and interface lock

- [x] 1.1 Verify `storefront-domain-parameterization` is implemented, accepted, and promoted: `build_vm_storefront_app` passes one exact validated `compute.v1` contract through `domains/vms/storefront/src/market_storefront/{server.py,startup.py,container.py,utils/sqlite_client.py,services/listing_service.py,controllers/negotiate_controller.py,utils/sync_negotiation.py,settlement_composition.py}` with no lower-layer default/getter/module lookup. Record the exact permanent `market-composition`/`storefront-publication` headings and focused evidence in `design.md`; stop before implementation if the seam is absent.
- [x] 1.2 Verify `pool-declared-offering-modes` is implemented, accepted, and promoted with the canonical pool declaration reader, explicit requested mode, shared reservation/scheduling/provisioning predicate, withdrawn-mode behavior, legacy reservation migration, and removal of every implicit VM executor fallback. Record the exact `resource-pool-management`, `site-capacity`, `fulfillment`, and physical-provisioning interfaces/evidence in `design.md`; stop before implementation if enforcement is incomplete.
- [ ] 1.3 Parent integration gate: merge and accept the production bare-metal contribution reported in `18083392` (entry-point group `market.storefront_contributions`, contribution `bare_metal`) plus its selected-site publication, negotiation, settlement, scheduling, begin/status/result, restart, teardown, and capacity-restoration lifecycle; render its dedicated chart from `3b46f6f8`. The isolated shell does not substitute a no-op, VM adapter, route-internal fake, or success flag.
- [x] 1.4 Reconciled `publish-multidimensional-listing-shape` against the live canonical `offer_resource.virtualization_type`: common bindings and publication enforce equality while the existing registry builder/fixture remains the sole public-schema owner; no alternate discriminator was added.
- [x] 1.5 Inventoried listing/mapping/thread/settlement/fulfillment/result/teardown carriers and singleton/default/fan-out branches; recorded the common binding/artifact, frozen-registry, exact-site, domain-neutral lifecycle, and migration destinations in `design.md`.

## 2. Frozen registry and shared application composition

- [x] 2.1 Add immutable `DomainContractKey`, `StorefrontDomainRegistration`, `StorefrontDomainBinding`, and `StorefrontDomainRegistry` in `core/storefront/src/core_storefront/domain_registry.py`; validate through `market_core.validate_domain_contracts`, require the full storefront capability set, reject duplicate modes/contributions/identities and unsupported versions, and resolve only to the exact pre-registered object.
- [x] 2.2 Add storefront contribution discovery in `core/storefront/src/core_storefront/domain_plugins.py` and package exports/entry-point fixtures. Keep it distinct from concept-level `market.storefront_domains`, verify configured mode/identity/version assertions against each returned complete contract, and load all contributions only during startup.
- [x] 2.3 Change `core/storefront/src/core_storefront/app_composition.py` to build the shared shell from the frozen registry and an injected runtime resolver; replace `app.state.market_domain` with a safe immutable registration projection and do not expose a request-time application-global selection API.
- [x] 2.4 Replaced one-contract VM parameterization with registry/binding injection through `server.py`, startup/container, `domain_runtime.py`, SQLite/listing/negotiation services, synchronization, settlement, fulfillment, and recovery while preserving exact-object resolution.
- [x] 2.5 Added core focused registry/application/plugin tests for one/two registrations, duplicate/unknown/incomplete/unsupported input, frozen lookup, absent contribution, and exact pre-registered object resolution.
- [x] 2.6 Extended architecture-import coverage so core/kit remain free of domain composition imports, VM does not import bare-metal composition, and contract construction occurs only in the VM contribution.

## 3. Immutable persistence and transactional legacy migration

- [x] 3.1 Add ordered schema migrations in `core/storefront/src/core_storefront/sqlite_migrations.py` for `storefront_listing_bindings`, `storefront_domain_artifacts`, negotiation binding/site columns, indexes, foreign-key/equivalence checks, and database triggers that reject changes to offering mode, domain identity/version, or site after first persistence.
- [x] 3.2 Implement typed common binding/mapping repository methods in `core/storefront/src/core_storefront/sqlite_client.py`: atomic listing+binding upsert, exact load, collision-safe derivation lookup, thread binding copy/load, binding-set inventory, and fulfillment-context equivalence. Identical retries are idempotent; any changed binding fails without partial state.
- [x] 3.3 Implement common domain-artifact persistence in `core/storefront/src/core_storefront/sqlite_client.py`, keyed by negotiation/artifact slot and validated against the thread binding before invoking the selected `message`, `terms`, `materialization`, `receipt`, or `result` codec. Do not duplicate settlement plans or provider-owned fulfillment results.
- [x] 3.4 Replace the module-global legacy `set_accepted_escrows_synthesizer` path in `core/storefront/src/core_storefront/sqlite_migrations.py` with explicit migration inputs selected from the frozen legacy contribution; prove two databases/processes cannot contaminate each other's migration codec.
- [x] 3.5 Added `market_storefront.domain_migration` and wired `market-storefront migrate-storefront-domains --contribution --offering-mode --domain-identity --contract-version --check|--write --backup`; it uses restrictive same-directory backup, fsync, atomic replacement, redacted reports, and explicit adapter selection.
- [x] 3.6 Migrated provable `derived_compute_listings` rows to common bindings with exact site/pool/resource source envelopes and collision-safe keys; whole-population equivalence is required before the legacy table stops being authoritative.
- [ ] 3.7 External bare-metal producer gate: its contribution must supply the shared `legacy_migration` adapter for provable `derived_bare_metal_listings`/agreement artifacts and reject the incomplete VM-owned bare-metal table rather than inventing Physical Resource/machine/host provenance.
- [x] 3.8 VM backfill uses only the explicitly selected contribution, preserves durable public/operation/provider identities, and aborts on missing provenance, mixed/orphaned rows, collisions, unsupported versions, or binding disagreement.
- [x] 3.9 Added focused fresh/legacy VM/accepted-state/missing-site/mismatch/backup/idempotency migration tests; bare-metal source-population cases remain attached to the external adapter gate in 3.7.
- [x] 3.10 Added repository tests for immutable/conflicting writes, delimiter-safe derivation keys, thread/artifact/fulfillment equivalence, large identifiers, transactional rollback, and redacted public bindings/reports.

## 4. Multi-domain publication and trusted listing mapping

- [x] 4.1 VM and bare-metal domain runtimes expose publication through the same immutable registration-owned capability, without runtime singleton lookup.
- [x] 4.2 Frozen publication composition iterates configured registrations and persists candidates through the common listing-binding repository; shared runner control flow contains no VM/bare-metal branch.
- [x] 4.3 Publication requires each source's exact declared pool mode; absent/withdrawn mode suppresses only that mode while accepted/sibling records retain their bindings.
- [x] 4.4 VM and bare-metal publication project canonical `offer_resource.virtualization_type`; common persistence rejects public/binding disagreement and collision-safe derivation keeps same-pool modes distinct.
- [x] 4.5 Shared binding lookup replaces domain mapping authority for selected site/pool/resource provenance; public bindings and source envelopes exclude URLs, credentials, provider configuration, SSH material, and buyer assertions.
- [x] 4.6 Added common runner/plugin/composition plus VM/bare-metal publication tests for frozen source selection, both modes, zero-source behavior, exact binding/public mode, collision isolation, and close/reopen behavior.
- [x] 4.7 Confirmed the existing registry fixture already owns canonical `virtualization_type`; observable generic carrier shapes were unchanged, so no alternate field or fixture fork was introduced.

## 5. Record-bound negotiation and acceptance

- [x] 5.1 New negotiations load listing/binding, resolve the exact contract, validate the provision envelope, and persist thread binding/domain artifact before policy; conflicting copies fail atomically.
- [x] 5.2 VM start resolves from listing and continuation from thread through schema-opaque binding selection; request kind, installed order, current config, and one-entry registries are never routing authority.
- [ ] 5.3 External bare-metal producer gate: adapt its concrete policy/SSH/access validation to the shared negotiation hooks and exact listing/thread binding supplied by this shell.
- [x] 5.4 Canonical Terms, acceptance, and settlement-plan construction resolve from the recorded thread contract and reject binding/artifact mismatch before terminal/agreed mutation.
- [ ] 5.5 External bare-metal cutover gate: remove its parallel new/continue persistence/routes after 5.3 consumes the common shell; no compatibility endpoint may select by URL, payload kind, app instance, or module getter.
- [x] 5.6 Added focused exact-contract/binding/cross-swap/unknown/mismatch/failure-atomic/restart assertions with untouched unselected hooks and repositories.
- [x] 5.7 Generic storefront responses and versioned provision envelopes did not change, so canonical client fixtures required no alternate discriminator or safe-binding projection.

## 6. Settlement, capacity, fulfillment, result, recovery, and teardown

- [x] 6.1 Replaced VM-global settlement/fulfillment access with accepted-thread resolution and defined the shared domain-neutral plan/fulfillment carrier and hook contract consumed by concrete domain contributions.
- [x] 6.2 Persist and compare the safe binding/site projection in settlement fulfillment context before dispatch; recovery reloads negotiation, exact binding, site, reservation, fulfillment, and operation identities.
- [x] 6.3 Pass the recorded offering mode through the selected domain payload and explicit capacity/fulfillment boundary; request-side payload shape is never mode authority.
- [x] 6.4 Extended `AggregateCapacityClient` and `AggregateFulfillmentClient` with exact `site_id` routing for commit/release/truncate/schedule/begin/status/result/begin-teardown; targeted calls never route-order fallback.
- [x] 6.5 Domain fulfillment hooks receive the selected contract's validated versioned envelope and recorded site/mode; provisioning remains the authority that preserves/rejects pool executor identity.
- [x] 6.6 Active `domain_result` is decoded only by the accepted contract's result codec; unknown/cross-swapped results fail before protected result persistence.
- [x] 6.7 Teardown and capacity release route by recorded site plus fulfillment/reservation identities; the provisioning authority dispatches its durable executor kind.
- [x] 6.8 Timer/restart paths resolve the recorded contract/site, block unavailable trust, preserve exact retry, and do not fallback-decode terminal history.
- [x] 6.9 Removed storefront singleton/default and cold-cache accepted-record fan-out from the shared path; architecture tests guard domain-free core and contribution-owned construction.
- [x] 6.10 Added deterministic core/VM coverage for exact resolution, selected-site isolation, cold restart, domain-result mismatch, retry, failure, and teardown carriers; the real dual-domain lifecycle remains the explicit parent-run gate.

## 7. Domain contributions and clean route cutover

- [x] 7.1 Declared the full VM `market.storefront_contributions` entry point and exact staged runtime dependencies while preserving concept-level domain exports.
- [ ] 7.2 External bare-metal producer gate: merge/accept `18083392`, whose `bare_metal` contribution must satisfy the shared publication, policy, settlement, fulfillment, receipt/result, and teardown hooks using selected POOLS-7 clients and no VM-shaped carrier.
- [ ] 7.3 External bare-metal cutover gate: reduce its former server/runtime/API/repository/service copies to contribution adapters or a one-registration invocation of the shared app after 7.2 proves the observable routes.
- [x] 7.4 VM listing, negotiation, settlement, fulfillment, operator, and recovery paths now enter through the common registry/binding route set while VM-only fields remain inside VM codecs/hooks.
- [x] 7.5 Added one shared conformance matrix for exact contract capabilities and schema-opaque settlement/fulfillment/result lifecycles under two distinct domain contracts.

## 8. Configuration, packages, image, Compose, and Helm

- [x] 8.1 Added strict versioned `storefront_domains` parsing, safe status projection, settings/examples, Helm schema validation, and tests; registrations are explicit/non-empty and reject duplicates, unknown fields, secrets, and entry-point assertion mismatch.
- [x] 8.2 Updated core/VM/root/domain build surfaces to stage the core shell plus enabled contribution wheels from `.dist`; the bare-metal wheel is a first-class `dist-bare-metal-storefront` dependency with no editable sibling source.
- [x] 8.3 Updated the VM storefront Docker build to install the shared shell and staged VM/bare-metal contribution wheels and start one common command without a duplicate app or private config.
- [x] 8.4 Updated mounted VM storefront configs used by Compose to run one process/database with explicit VM and bare-metal registrations; package/config selection is explicit and never defaults to the remaining domain.
- [x] 8.5 Updated shared and subchart Helm values/schemas/helpers/fixtures to render explicit public registrations while retaining one RWO/Recreate SQLite workload, trusted sites, and Secret-only credentials.
- [x] 8.6 Added configuration/schema/render fixtures for one/two domains and fail-closed missing/duplicate/unsupported inputs; public config contains no signer, provider, SSH, or private-result value.
- [x] 8.7 Implemented and permanently documented staged artifact, quiesce, explicit migration check/write/backup, frozen-binding readiness, single-process activation, and forward-recovery sequencing; no live database merge is supported.
- [x] 8.8 Remove the packaged VM registration from `settings.toml` so Dynaconf list merging cannot append it to an operator's explicit one- or two-domain selection. Configuration loading now proves the effective list equals the complete overlay, and `deployment-state` permanently records the no-packaged-default rule.

## 9. Behavioral, integration, packaging, and strict validation

- [ ] 9.1 Run the core registry/persistence/migration focused suite with `make -C core/storefront test`; report any unrun test rather than narrowing silently.
- [ ] 9.2 Build current internal wheels, then run `make -C domains/vms/storefront test-unit`, `make -C domains/vms/storefront test-integration`, and `make -C domains/bare_metal/storefront test` so both one-registration regressions and shared two-registration routes use installed artifacts.
- [ ] 9.3 Run provisioning/site/resource-pool/fulfillment focused suites that own explicit mode enforcement, selected-site scheduling, result, teardown, and capacity restoration; include migration restart and no-default executor cases from the accepted prerequisites.
- [ ] 9.4 Add and run `e2e-tests/tests/e2e/roles/scenarios/compute_family/{conftest.py,test_multi_domain_storefront.py}` plus the exact `DealState` producer/consumer fields: one process publishes, negotiates, settles, reserves, fulfills, observes real VM and bare-metal domain results, restarts, tears both down, and observes capacity restoration; include payload/result/listing/settlement/teardown cross-swaps and independent failure. Reuse canonical typed clients and explicit synchronization, not sleeps or raw route calls.
- [ ] 9.5 Keep Compute-40's later two-authority topology out of this scenario, but run its prerequisite/contract fixture if available to prove this change exports the exact multi-domain storefront it expects; disclose the separate topology suite as not owned here.
- [ ] 9.6 Run `make dist-arkhai-core-storefront dist-domains`, clean wheelhouse installation/startup, wheel-content and dependency review, storefront image startup/health, `make test-deployment-packaging`, Helm one/two-domain renders, Compose config rendering, and affected configured typing checks. Verify no editable path, source mount, duplicate server, or disabled-domain wait remains.
- [ ] 9.7 Run the complete VM and bare-metal contract/canonical-client integration suites and the repository smoke path from staged artifacts. Attribute every failure to this change, a prerequisite, environment, or an unrelated baseline failure with the exact unrun/failed command.
- [ ] 9.8 Cross-check `proposal.md`'s six modified capabilities against the six delta-spec directories and every requirement heading/scenario; then run `openspec validate multi-domain-storefront-composition --strict` and `openspec validate --all --strict`, reporting unrelated pre-existing active-change failures separately.

## 10. Closeout

Per `openspec/README.md#plan-closeout-requirements`, complete this section only after Section 9 proves the behavior.

- [ ] 10.1 **Comment hygiene.** Run `make check-comment-hygiene`; directly read every changed comment/docstring around registry selection, migration, site routing, and recovery; remove change/task/history wording, temporary commentary, obsolete singleton/fallback explanations, and any review tombstones before completion.
- [ ] 10.2 **Import placement.** Review every import added or touched across core and both contributions, move function-local imports to module scope where safe, verify any retained local import through an actual circular-import or deliberate lazy-load test, rerun the affected suites, and confirm core/kit/domain dependency direction including `TYPE_CHECKING`.
- [x] 10.3 **Documentation compliance and promotion.** Synchronized the six verified deltas into their owning permanent specs, promoted rationale into each companion architecture, and updated `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG,TESTING}.md` with current compute-family behavior and proof boundaries.
- [x] 10.4 **Narrative compression.** Recorded durable alternatives and dispositions in `design.md`; compressed completed Sections 1–8 to final behavior/evidence and retained only exact external producer and parent-validation blockers.
- [x] 10.5 **Roadmap currency.** Updated Goal 3 with the implemented shared storefront boundary and retained the `bare-metal-buyer-domain`, bare-metal producer, and Compute-40 live-proof gaps; exact permanent destinations are recorded in the Design Promotion Record.
- [ ] 10.6 **Promotion record and final closeout.** Replace `design.md`'s planned Design Promotion Record rows with exact accepted headings, mark every material decision permanent/temporary/superseded/rejected, confirm no production code references `openspec/changes`, rerun affected focused/integration/package/type/render/E2E checks plus strict change/all validation after promotion, disclose anything unrun, and leave the change ready for review/sync/archive with no temporary compatibility alias, singleton, domain branch copy, fake fulfillment, or default fallback.
