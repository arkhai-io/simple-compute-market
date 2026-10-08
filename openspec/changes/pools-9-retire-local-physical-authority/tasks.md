# Tasks

## Status: planned

Section numbering is kept from the original plan. Section 0 is
`fix-resource-pool-provider-at-creation`'s; Section 2 and most of Section 3 are
`remove-dead-storefront-physical-surfaces`'; former tasks 3.3 and 3.4 now belong
here with the local-inventory cutover. Section 1's endpoint tasks are
struck because `kit/pool-overrides` is the write path. Resolved planning
questions, kept as record. The diagnostic question added by the scope transfer
is resolved in `design.md` as per-site, per-family projection counts:

1. `resources`' commercial columns are dead in the default code path: read only
   by `_project_legacy_resource_row`, reached only when `compute_capacity_pools`
   or `compute_pool_members` is absent, which no migrated deployment is. Task
   1.1 re-runs the check.
2. Seven test files depended on CSV import (six VM scenarios plus
   `e2e-tests/tests/smoke/test_storefront_smoke.py`). Re-grounded 2026-10-08:
   six remain; the multi-storefront repair migrated `test_multi_registry.py`.
3. Per-pool commercial values are an upsert against a pool that exists in the
   projection; the site-scoped store is that upsert.
4. Complete `repair-multi-storefront-scenario` separately before local-inventory
   retirement. Technical gates: `capacity-resource-administration` (met) and
   the multi-storefront repair, including its projection cutover and passing
   scenario evidence (met; archived). Task 1.6 still re-grounds this plan
   against the resulting tree before retirement begins.
5. `remove-dead-storefront-physical-surfaces` lands before this change
   (decided 2026-10-08; `design.md`, "The zero-caller removal lands first").
   Its surfaces read the tables this change stops creating.

Tasks 3.4, 3.8, 4.3, 4.4, 4.5, 6.1, 6.2, and Section 5 are gated on the open
decisions D2–D6 in `design.md`'s Open Questions; they are amended when each
decision is recorded.

Section numbers preserve planning history rather than define independently
deployable slices. After the separate multi-storefront repair is complete,
prepare Sections 3–6 as one coordinated retirement of the local inventory
contract: replacements, consumer migrations, and the schema freeze must all
be present before deployment. Section 7 closes out that complete fileset.
Read-only re-grounding and planning can proceed before the prerequisite lands.

## 0. Fix a pool's executor at creation

Owned by [`fix-resource-pool-provider-at-creation`](../fix-resource-pool-provider-at-creation/tasks.md),
tasks 0.1–0.6 under the same numbers.

## 1. Re-ground

Tasks 1.2–1.5 are struck: `kit/pool-overrides` is the per-pool override write
path, with its own routes, clients, CLI, and precedence contract.

- [x] 1.1 Re-run the confirming searches `design.md`'s Context records: the
      legacy-resources fallback's reachability and the CSV-dependent test file
      set. Record drift in `design.md`. Done 2026-10-08: the fallback is
      unreachable; six CSV-dependent test files remain; further drift and the
      open decisions it raised are in `design.md`, "Re-grounding".
- [x] ~~1.2 Add `PUT`/`PATCH` admin routes against `compute_capacity_pools`'
      surviving commercial columns.~~ Struck: `kit/pool-overrides`' routes.
- [x] ~~1.3 Confirm the absent-override-row path needs no new handling.~~
      Struck: per-field fall-through is normative for the store.
- [x] ~~1.4 Add the corresponding client methods to both storefront clients.~~
      Struck: the store's typed clients.
- [x] ~~1.5 Focused tests for the endpoint.~~ Struck: delivered with the store.
- [x] 1.6 Confirm `repair-multi-storefront-scenario` is complete before
      starting local-inventory retirement: record its passing two-storefront
      pipeline evidence, verify Alice uses provisioning-seeded projections,
      and re-ground this plan against the resulting tree. Reconcile
      `domains/vms/storefront/storefront.alice.toml` and
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_multi_registry.py` with the
      prerequisite's completed edits rather than repeating them here.
      Done 2026-10-08: archived 2026-10-01 with the 21-stage scenario passing
      and a full local pipeline of 127 VM/API-credit and 11 bare-metal tests
      passing with no skips. Alice's opt-out is absent and
      `test_multi_registry.py` imports no CSV. Alice's `resources_csv_path`
      and compose CSV mount remain and retire in task 5.4.
- [ ] 1.7 Confirm `remove-dead-storefront-physical-surfaces` has landed before
      starting Sections 3–6, then re-check task 4.5's method list and
      migration `20260604_002`'s `compute_allocations` indexes against the
      tree it leaves.

## 2. Retire `compute_allocations`

Owned by [`remove-dead-storefront-physical-surfaces`](../remove-dead-storefront-physical-surfaces/tasks.md),
tasks 2.1–2.5 under the same numbers. That change lands before this one.

## 3. Remove dead physical surfaces

Tasks 3.1, 3.2, and 3.5–3.7 belong to the same change under the same
numbers and land before this change.
Former tasks 3.3 (local-row reservation cleanup) and 3.4 (`resource_count`)
are transferred here and retire with Section 4's local listing path and
Section 5's CSV contract. The site-ledger half of `release_reservations`
remains supported. The accepted diagnostic decision is implemented before
removing the storefront-local count and its consumers.

- [ ] 3.3 Remove only the local-row normalization in
      `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`'s
      `release_reservations`; retain authoritative site-ledger release and
      correct its description. Update its focused cases in
      `domains/vms/storefront/tests/integration/test_admin_api.py`.
- [ ] 3.4 Replace top-level `resource_count` with counts under
      `site_projections[site_id][family]`: derive member counts for
      `resource_pool` and sum group multiplicities for `capacity_bucket` from
      the same cached view used for state and identity in
      `domains/vms/storefront/src/market_storefront/services/site_projection_cache.py`.
      Remove the local inventory read in
      `domains/vms/storefront/src/market_storefront/services/system_service.py`.
      Update `ProjectionFamilyStatus` and `HealthResponse` in
      `core/storefront/src/core_storefront/models/system_models.py` and the
      client model/parser in
      `core/storefront-client/src/storefront_client/models.py`. Preserve
      independent sites and families, zero for held empty generations, null
      when no generation is held, and retained stale counts. Leave the site
      projection protocol and liveness health unchanged.
- [ ] 3.8 Verify counts and state together in
      `domains/vms/storefront/tests/unit/services/test_site_projection_cache.py`
      and the typed-client integration boundary in
      `domains/vms/storefront/tests/integration/test_admin_api.py`; reconcile
      injected summaries in
      `domains/vms/storefront/tests/unit/services/test_system_service.py`.
      Cover multiple sites, independently loaded families, empty and unknown
      generations, stale retained generations, unequal group multiplicities,
      disabled declarations, and exhausted declarations. Assert top-level
      `resource_count` is absent and no local inventory read is needed.
      Run the focused suites before the consumer migrations in task 5.6.

## 4. Retire the local-table listing path

Part of the coordinated cutover with Sections 3, 5, and 6. Depends on Section 1
and completed `repair-multi-storefront-scenario`:
the two-storefront scenario's second storefront derives from local tables
because provisioning does not trust it, and deleting that path before
provisioning can trust two principals leaves it with no listing source.

- [ ] 4.1 Delete `_pool_rows_from_local_tables`, `_pool_rows_from_capacity_pools`,
      `_pool_rows_from_legacy_resources`, `_project_legacy_resource_row`, and
      `_legacy_resource_columns`; make `available_compute_slices` read the
      projection unconditionally.
- [ ] 4.2 Delete `use_site_projection_for_listings` and its reads in
      `capacity_client.py` and `listing_sources.py`, plus its `settings.toml`
      entry, the `storefront.alice.toml` opt-out, and the config-loader tests.
      The prerequisite owns removing Alice's opt-out; verify its absence
      rather than treating that already-completed edit as new work here
      (verified absent 2026-10-08). Also update
      `scripts/tests/test_multi_storefront_compose.py`, which asserts the
      flag's default, and the tests that set the flag
      (`tests/publication_app.py`, `test_negotiate_controller.py`,
      `test_admin_api.py`, `test_pool_overrides_api.py`,
      `test_listing_source_check.py`, `test_remote_capacity_client.py`).
- [ ] 4.2a Make the projection a required argument of every derivation entry
      point in `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
      and of the storefront wrappers in `services/publication_service.py`;
      reduce `listing_source_projection()` in `services/capacity_client.py`
      to the projection read its callers need (the publication loop, the
      listing-source check, `failure_actions.py`, two admin routes,
      capacity-change reconciliation, and the pool-override service's status
      source in `server.py`). Remove the derivation's `home_site` parameter
      where only the legacy tier and the local path used it.
- [ ] 4.3 Retire the legacy home-site override tier: delete
      `_local_pool_pricing`, the legacy arm of `_tier()` and the `region`
      legacy fallback beside it, the `legacy_overrides_in_effect` derivation
      report, and its system-status field; drop the `inactive` override
      state and its local-table judgment from the pool-override status
      provider. No values are carried into the site-scoped store (decision in
      `design.md`).
- [ ] 4.3a Focused tests: a home-site pool with a legacy row and no
      site-scoped override resolves each commercial field from the pool hint
      then the configured default; system status no longer reports a legacy
      value or an `inactive` override; the two removed scenarios' tests are
      deleted rather than kept green against dead code.
- [ ] 4.4 Freeze `resources`, `hosts`, `compute_pool_members`, and
      `resource_transition_events`, and `compute_capacity_pools` as a whole
      (its commercial columns retire with the tier in 4.3, and
      `total_gpu_count` was always physical): stop creating them, their
      triggers, and their indexes. No `DROP`. Existing
      `resource_transition_events` rows are history and must not be deleted.
      Fresh databases omit the retired schema; upgrades preserve all existing
      schema and rows unchanged. Current storefront code must neither read nor
      write the retained data. Name and verify the affected bootstrap and
      migration functions in
      `domains/vms/storefront/src/market_storefront/utils/migrations.py`.
- [ ] 4.5 Delete `resource_capacity_validator.py` and `SQLiteClient.upsert_resource`
      with `_sync_compute_pool_for_resource`, `upsert_host`, `get_host`,
      `get_resource`, `list_resources`, `apply_resource_transition`, and
      `apply_resource_set_transition` once their callers are gone. The
      transferred local cleanup and resource-count readers are among those
      callers and retire at the same cutover. With
      `remove-dead-storefront-physical-surfaces` landed first, the remaining
      callers are `release_reservations`' local loop, `SystemService`'s count
      and seeding, the validator, and the importers; task 1.7 re-checks this.
- [ ] 4.6 Document, for operators, that rollback past this section is a code
      rollback rather than a configuration change in
      `docs/development/DEPLOYMENT_AND_CONFIG.md`. Retained data is historical;
      reconcile it against current provisioning state before an older version
      resumes trading. Explain operator use for provisioning seeding in
      `docs/seller-quickstart.md` without adding automatic transfer machinery.
- [ ] 4.7 Run the full storefront suite and the VM e2e scenarios after the
      combined Sections 3–6 fileset is ready, not against a partial retirement.

## 5. Retire CSV import and its deployment contract

- [ ] 5.1 Remove `startup.py`'s `_seed_resources_if_empty` and its
      `seed_resources` startup step, `SystemService.seed_resources_if_empty`,
      `_DEFAULT_CSV_PATH`, and the `resources_csv_path`/`resources_csv_inline`
      settings including their `groups/config.py` documentation.
- [ ] 5.2 Remove `host_csv_importer.py`, `resource_csv_importer.py`,
      `SQLiteClient.upsert_hosts_from_csv` and `upsert_resources_from_csv*`,
      the `POST /api/v1/admin/portfolio/resources/import` route, its
      administrator route contract and `_resource_import_descriptor` in
      `middleware/admin_identity.py`, `ImportResourcesResponse` and its row
      model in `models/capacity_admin_models.py` and
      `core/storefront-client/src/storefront_client/models.py`, both client
      variants' `admin_import_resources`, the importer exports in
      `arkhai_vms_listings/__init__.py`, and their tests
      (`test_resource_csv_importer.py`, `test_accepted_escrows_csv_dsl.py`, the
      import cases in `test_hosts.py` and `test_admin_api.py`).
- [ ] 5.3 Remove the CLI surface: `cli_portfolio.py` and its `add_typer`
      registration in `cli.py`, and
      `domains/vms/storefront/scripts/import_resources_csv.py`, with
      `tests/unit/cli/test_portfolio.py`.
- [ ] 5.4 Remove the deployment wiring: Helm `_helpers.tpl`'s
      `resources_csv_inline` rendering (one site in the current tree),
      `secrets.yaml`'s `resourcesCsvInline`, `values.yaml`'s
      `resourcesCsvInline` guidance and `resources_csv_path` config entry,
      `helm/Makefile`'s `RESOURCES_CSV_FILE` `--set-file` wiring,
      `helm/fixtures/eip191-evm-values.yaml`'s `resources_csv_path`,
      `compose/seller.yml`'s mount and `SELLER_RESOURCES_CSV`,
      `domains/vms/compose.yml`'s two mounts (Bob's and Alice's),
      `resources_csv_path` in `storefront.alice.toml` and
      `storefront.bob.toml`, `domains/vms/storefront/Makefile`'s
      `RESOURCES_CSV_FILE` mounts, and the bundled inventory CSVs under
      `market_storefront/data/` (`kvm1-machine.csv`, `kvm1-host.csv`,
      `resources.sample.csv`, `hosts.sample.csv`) with
      `tests/unit/test_bundled_inventory.py`. Run the chart render tests in
      `helm/charts/storefront/tests/`.
- [ ] 5.5 Write operator migration guidance in `docs/seller-quickstart.md`
      covering how to move CSV inventory to the provisioning service's host
      inventory, pool definitions, and capacity declarations. This is
      required, not optional: seeding silently skips when it finds no source,
      so an unmigrated operator gets an empty storefront and no error.
      Check `docs/bare-metal-seller-quickstart.md` for the same references.
      Include the legacy override tier: which fields the system-status report
      names as still coming from the legacy record, that each must be
      re-entered with `pool-override set` before upgrading or it falls
      through to the hint and the configured default, that `region` must
      instead be declared on the pool hint, and that `accepted_escrows` has
      no equivalent other than a `settlements` clause list.
      Include retained legacy tables as an operator source for those physical
      declarations, after reconciling their historical contents against live
      site state. Use supported provisioning administration surfaces and do not
      prescribe automatic overwrite of live declarations or storefront reads.
- [ ] 5.6 Migrate the six CSV-dependent test files to
      projection/provisioning-service seeding: the five VM scenario files
      named in `proposal.md` plus `e2e-tests/tests/smoke/test_storefront_smoke.py`
      (re-grounded 2026-10-08; `test_multi_registry.py` is already migrated).
      `test_compute_dynamic_listings.py`'s imported rows share pool
      identifiers with its projected pools, so its listings take SLA and
      region from the legacy tier today; declare them on the pool hint or a
      site-scoped override and keep its published-term assertions. Confirm
      the other files' imports are vestigial before deleting them.
      The resource-count assertions and their import diagnostics must be
      replaced by per-site projection state and counts from Section 3;
      known-empty is distinct from unknown, and inventory presence is distinct
      from publishable supply. Preserve catalogue/deal assertions for the latter.
      `repair-multi-storefront-scenario` must already have migrated
      `test_multi_registry.py`'s Alice seeding and removed her local-path opt-out.
      Preserve that completed work and migrate the remaining CSV consumers
      identified by re-grounding, including Bob's local import where it remains.

## 6. Freeze migration and validation

- [ ] 6.1 Add the freeze-then-redirect migration covering every table and
      column frozen in Section 4. `compute_allocations` is already frozen by
      `remove-dead-storefront-physical-surfaces`, which lands first. Stop
      writing; redirect reads; no `DROP`.
- [ ] 6.2 Validate migration behavior as `TESTING.md` requires: fresh
      bootstrap, idempotent rerun, drift detection.
      Extend `domains/vms/storefront/tests/unit/test_migrations.py` to prove
      that fresh bootstrap omits retired schema and a populated upgrade and
      rerun preserve existing schema and row contents, including transition
      history. Verify normal startup and status do not recreate or mutate it
      through the storefront integration suite.
- [ ] 6.3 Run every affected suite — storefront unit and integration,
      `core/storefront-client`, `domains/vms/listings`, and the VM e2e
      scenarios. Disclose any suite not run.
- [ ] 6.4 Run `openspec validate --all --strict` against the baseline current
      at implementation time.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the
      touched docstrings directly as well: several — `_local_pool_pricing`,
      `_place_capacity_hold`, `_project_host`'s callers — describe an
      arrangement that no longer exists, and stale docstrings are what kept
      these surfaces alive past their callers. `release_reservations`' local
      cleanup and its operator description are part of this cutover;
      `patch_resource` belongs to `remove-dead-storefront-physical-surfaces`.
- [ ] 7.2 **Import placement.** Review imports this change adds or touches;
      relocate function-level imports where no genuine circular import or
      documented lazy-load reason applies, verified against the real suite.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement rules. Confirm the legacy tier's
      retirement landed as the replacement of `storefront-publication`'s
      site-scoped override requirement and nowhere in
      `resource-pool-management` — see `design.md`, "Commercial rows are
      storefront-owned".
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final
      behavior, validation evidence, and promotion destinations.
- [ ] 7.5 **Roadmap currency.** Update Goal 1's current-state description and
      gap mapping in `docs/development/ROADMAP.md`.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below. Widen
      `openspec/specs/storefront-publication/spec.md`'s rule that an unbacked
      listing is derived only from the site projection to every listing, and correct
      `docs/development/ARCHITECTURE.md`'s "Storefront capacity boundary", which
      says a storefront disabling projection-backed derivation still derives backed
      listings from local tables. Both became true only for unbacked listings when
      `unbacked-listing-publication` promoted them; retiring the local-table path
      (Section 4) makes them true of every listing. Also strike the
      `storefront-publication` architecture companion's description of the
      legacy override record and the `inactive` state, if it carries one.
      Replace the "Operator-visible acceptance state" requirement with the
      delta's "Operator-visible acceptance and projection state", reconcile
      its Evidence entry, and promote the count interpretation to
      `openspec/specs/storefront-publication/architecture.md`'s "Projection
      families". Update `docs/seller-quickstart.md` and
      `docs/development/VALIDATION_RUNBOOK.md` to diagnose inventory by site,
      family, state, and count; diagnose import failures at provisioning and
      sellable listings through publication diagnostics and catalogue checks.
      Promote the fresh-versus-upgraded persistence boundary to
      `openspec/specs/storefront-publication/spec.md`'s "Storefront holds no
      physical-resource authority" and explain inert history in its
      `architecture.md` companion's "Seller-owned market state". Keep rollback
      and seeding procedures in the operator documents named in task 4.6.
- [ ] 7.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

- [ ] 7.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=pools-9-retire-local-physical-authority` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
- [ ] 7.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-resource, host, or physical-allocation authority | `openspec/specs/storefront-publication/spec.md` — "Storefront holds no physical-resource authority" |
| Projection-backed derivation is the only listing-candidate path, not the default one | `openspec/specs/storefront-publication/spec.md` — "Storefronts cache independent site projections" (modified) |
| A site whose projection is not held yields no listing from any other source | `openspec/specs/storefront-publication/spec.md` — "A site whose projection is not held holds its listings" (modified) |
| Projection is the only listing-candidate origination path; no local-table path or configuration option selects another source | `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary" |
| The site-scoped store is the only storefront-override tier; the legacy home-site record retires with the import that wrote it, and its values are not carried over | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are the only override tier", replacing "Storefront pool overrides are site-scoped and durable" |
| Why no carry-over: the status report already enumerates the population, and two of the eight legacy fields cannot be copied | This change's `design.md`, "Decision: retire the legacy override tier without carrying values over" |
| Fresh databases omit retired schema; upgrades retain inert schema and rows for rollback or operator provisioning seeding, with no current storefront reads or writes | `openspec/specs/storefront-publication/spec.md` — "Storefront holds no physical-resource authority"; companion `architecture.md` — "Seller-owned market state" |
| Rollback requires earlier code and reconciliation against live site state; retained rows are historical seeding input, not current physical truth | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md` |
| Why the legacy tier retires with the import (its only writer) rather than surviving as a lower override tier | This change's `design.md` |
| Local resource-count diagnosis and local reservation normalization retire with their inventory source | Temporary sequencing decision in this change's `design.md` |
| Complete the separate multi-storefront repair first; retire the local inventory contract, its writers and consumers, and fresh-schema creation together | Temporary sequencing decision in this change's `design.md`; dependency/status in `openspec/changes/README.md` |
| `remove-dead-storefront-physical-surfaces` lands before this change, so this freeze covers only the local inventory tables | Temporary sequencing decision in this change's `design.md`, "The zero-caller removal lands first"; dependency/status in `openspec/changes/README.md` |
| Inventory counts remain separate per site and projection family, describing the same cached generation as the reported state and identity | `openspec/specs/storefront-publication/spec.md` — "Operator-visible acceptance and projection state"; companion `architecture.md` — "Projection families" |
| Zero means known-empty, null means unknown, and a stale count describes retained inventory rather than current sellable supply | `openspec/specs/storefront-publication/spec.md`; `docs/seller-quickstart.md`; `docs/development/VALIDATION_RUNBOOK.md` |
