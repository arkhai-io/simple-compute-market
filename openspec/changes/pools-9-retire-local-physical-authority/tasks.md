# Tasks

## Status: planned (implementation plan amended 2026-10-11 after design review)

Section numbering is kept from the original plan. Section 0 is
`fix-resource-pool-provider-at-creation`'s; Section 2 and most of Section 3 are
`remove-dead-storefront-physical-surfaces`'; former tasks 3.3 and 3.4 now belong
here with the local-inventory cutover. Section 1's endpoint tasks are
struck because `kit/pool-overrides` is the write path. Resolved planning
questions, kept as record. The diagnostic question added by the scope transfer
was first resolved as per-site, per-family projection counts and is now
resolved in `design.md` as "Status reports no resource count":

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

The re-grounding decisions are folded in: D2 into task 4.3, D3 into task 5.8,
D4 into tasks 3.4 and 3.8, D5 into tasks 4.4, 4.6, 6.1, and 6.2, D6 into
task 4.5a, and D7 into task 5.9.

Section numbers preserve planning history rather than define independently
deployable slices. Both prerequisites are archived. Sections 3–6 are one
coordinated retirement of the local inventory contract: replacements, consumer
migrations, and the schema freeze must all be present before deployment.
Section 7 closes out that complete fileset.

### Implementation order

One fileset, built in an order that keeps each step's focused suites runnable.
Each phase ends by running the suites it names; Section 6 runs everything.

1. **Derivation** (4.1, 4.2, 4.2a, 4.3, 4.3a): projection-only derivation, the
   flag, the legacy tier, and `kit/pool-overrides`' `inactive` state. Its
   tests stop seeding local rows for derivation.
2. **Status and cleanup** (3.3, 3.4, 3.8): `release_reservations`' local loop
   and every `resource_count`, VM and bare metal.
3. **Import and its contract** (5.1–5.4, 5.7–5.9): seeding, import, CLI,
   deployment wiring, the CSV pricing migration, retired-key refusal, and the
   route-absence guard.
4. **Local storage** (4.5, 4.5a, 4.5b): the `SQLiteClient` local-row methods,
   the validator, the code describing the retired inventory, and the test
   fixtures that still seed local rows.
5. **Freeze** (4.4, 6.1, 6.2): bootstrap and migration chain, with the freeze
   tests.
6. **Consumers and guidance** (5.5, 5.6, 4.6): e2e and smoke migrations, then
   operator documentation.
7. **Validation** (4.7, 6.3, 6.4), then Section 7.

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
- [x] 1.7 Confirm `remove-dead-storefront-physical-surfaces` has landed before
      starting Sections 3–6, then re-check task 4.5's method list and
      migration `20260604_002`'s `compute_allocations` indexes against the
      tree it leaves. Done 2026-10-11 after merging `dev`: archived
      2026-10-08; `20260604_002` no longer creates allocation indexes; task
      4.5's list is amended below (`design.md`, "Re-grounding against `dev`").

## 2. Retire `compute_allocations`

Delivered by [`remove-dead-storefront-physical-surfaces`](../archive/2026-10-08-remove-dead-storefront-physical-surfaces/tasks.md)
(archived 2026-10-08), tasks 2.1–2.6 under the same numbers.

## 3. Remove dead physical surfaces

Tasks 3.1, 3.2, and 3.5–3.12 were delivered by the same change under the same
numbers.
Former tasks 3.3 (local-row reservation cleanup) and 3.4 (`resource_count`)
are transferred here and retire with Section 4's local listing path and
Section 5's CSV contract. The site-ledger half of `release_reservations`
remains supported. Status reports no resource count afterwards (`design.md`,
"Status reports no resource count").

- [x] 3.3 Remove only the local-row normalization in
      `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`'s
      `release_reservations`; retain authoritative site-ledger release and
      correct its description. Update its focused cases in
      `domains/vms/storefront/tests/integration/test_admin_api.py`.
      Amended 2026-10-11: the loop now calls the narrowed
      `apply_resource_transition`; delete `_HELD_STATES` if nothing else reads
      it, and correct the route summary ("Release every held compute
      resource") and the response's `resource_ids` description to name the
      released site reservations. The e2e teardown that calls the route
      (`e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`) needs no change.
- [x] 3.4 ~~Replace top-level `resource_count` with counts under
      `site_projections[site_id][family]`.~~ Superseded 2026-10-09 by
      `design.md`, "Status reports no resource count": remove `resource_count`
      from every storefront's status with no replacement count. Remove the
      local inventory read in
      `domains/vms/storefront/src/market_storefront/services/system_service.py`;
      the field from `HealthResponse` in
      `core/storefront/src/core_storefront/models/system_models.py`; the typed
      field and its parsing in
      `core/storefront-client/src/storefront_client/models.py`; and, in
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`,
      `BareMetalHealthResponse.resource_count` in `models.py`, the count in
      `runtime.py`'s `health()` (its database check stays), and
      `count_open_bare_metal_resources` in `sqlite_client.py`. Leave
      `ProjectionFamilyStatus`, the site projection protocol, liveness health,
      and global pause unchanged.
- [x] 3.8 ~~Verify counts and state together.~~ Superseded 2026-10-09 with
      task 3.4: assert `resource_count` is absent from VM and bare-metal
      status through the typed client
      (`domains/vms/storefront/tests/integration/test_admin_api.py` and
      `domains/bare_metal/storefront/tests/test_http_system.py`), that VM
      status performs no local inventory read
      (`domains/vms/storefront/tests/unit/services/test_system_service.py`),
      and that per-site projection state is unchanged
      (`tests/unit/services/test_site_projection_cache.py`). Run the
      `core/storefront-client` suite and the focused storefront suites before
      the consumer migrations in task 5.6.

## 4. Retire the local-table listing path

Part of the coordinated cutover with Sections 3, 5, and 6. Depends on Section 1
and completed `repair-multi-storefront-scenario`:
the two-storefront scenario's second storefront derives from local tables
because provisioning does not trust it, and deleting that path before
provisioning can trust two principals leaves it with no listing source.

- [x] 4.1 Delete `_pool_rows_from_local_tables`, `_pool_rows_from_capacity_pools`,
      `_pool_rows_from_legacy_resources`, `_project_legacy_resource_row`, and
      `_legacy_resource_columns`; make `available_compute_slices` read the
      projection unconditionally.
      Amended 2026-10-11: also delete `_capacity_pool_member_rows`,
      `_accumulate_capacity_pool_member`, `_local_table_shapes`, and the
      local-tables branch's `capacity_backing = "backed"` default in
      `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`; keep
      `_member_available_units`, which the projection path uses. Rewrite the
      docstrings of `available_compute_slices`, `_pool_rows_from_projection`,
      and `_projected_pool_rows` for one source. Tests: delete the local-table
      and legacy-row cases in `domains/vms/storefront/tests/unit/test_reconciler.py`
      (including `TestProjectLegacyResourceRow`) and their builders in
      `tests/_reconciler_cases.py`; delete the local-source cases in
      `tests/unit/test_remote_capacity_client.py` and
      `tests/integration/test_reconciler_projection.py`; in
      `tests/unit/test_compute_allocations.py`, delete the local-table
      derivation cases (fungible pool across members, member availability,
      member at another site) and the pre-compute-inventory migration case,
      keep the capacity-hold round trip, and rename the file for what remains.
- [x] 4.2 Delete `use_site_projection_for_listings` and its reads in
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
- [x] 4.2a Make the projection a required argument of every derivation entry
      point in `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
      and of the storefront wrappers in `services/publication_service.py`;
      reduce `listing_source_projection()` in `services/capacity_client.py`
      to the projection read its callers need (the publication loop, the
      listing-source check, `failure_actions.py`, two admin routes,
      capacity-change reconciliation, and the pool-override service's status
      source in `server.py`). Remove the derivation's `home_site` parameter
      where only the legacy tier and the local path used it.
      Amended 2026-10-11: `home_site` threads through `reconciler.py`,
      `services/{capacity_client,listing_source_check,publication_loop,publication_service,vm_pool_override_contribution}.py`,
      `controllers/admin_controller.py`, `failure_actions.py`, and
      `server.py`; remove it wherever the legacy tier and the local path were
      its only readers, and keep a projected row's own `site_id` as the only
      site attribution. In `services/listing_sources.py`, delete
      `_projection_enabled()` and the "backed when disabled" branches of
      `resolve_source_backing` and `current_source_backing`; in
      `services/listing_source_check.py`, drop the local-path distinction.
- [x] 4.3 Retire the legacy home-site override tier: delete
      `_local_pool_pricing`, the legacy arm of `_tier()` and the `region`
      legacy fallback beside it, the `legacy_overrides_in_effect` derivation
      report, and its system-status field; drop the `inactive` override
      state and its local-table judgment from the pool-override status
      provider. No values are carried into the site-scoped store (decision in
      `design.md`).
      In `kit/pool-overrides` (`design.md`, "The pool-override kit loses
      `inactive`"): delete `OVERRIDE_INACTIVE` from
      `src/market_pool_overrides/service.py` and `__init__.py`, make
      `ProjectionSource` and `override_state()`'s `projection` non-optional,
      remove the `None` branch, and replace the two `None` cases in
      `tests/unit/test_status.py` with a `{}` case reporting `unknown`. Pass a
      non-optional projection read from `server.py`, and correct the state list
      in `models/system_status_models.py`'s `pool_overrides` comment.
      Amended 2026-10-11: in `reconciler.py`, `_tier()` reads only the
      site-scoped override, `region` comes from the pool hint alone, and the
      override tier no longer supplies `accepted_escrows` (configured per-model
      terms still may). Drop `resolve_region`'s `fallback` parameter and the
      legacy-row wording in `arkhai_vms_listings/pool_descriptors.py` and
      `pricing_resolution.py`. Remove `legacy_overrides_in_effect` from
      `_SiteDerivationReport`, its `as_dict()`, and its log line.
- [x] 4.3a Focused tests: a home-site pool with a legacy row and no
      site-scoped override resolves each commercial field from the pool hint
      then the configured default; system status no longer reports a legacy
      value or an `inactive` override; the two removed scenarios' tests are
      deleted rather than kept green against dead code. Run
      `kit/pool-overrides`' unit and integration suites and bare metal's
      `test_pool_overrides_api.py` to confirm its override status is
      unchanged.
      Amended 2026-10-11, files: `domains/vms/storefront/tests/unit/test_reconciler.py`
      (`TestStorefrontOverrideTier`'s legacy cases and the home-site local-row
      cases become hint-then-default cases);
      `tests/integration/test_reconciler_derivation.py`;
      `tests/integration/test_pool_overrides_api.py` (delete
      `test_under_local_table_derivation_an_override_is_stored_but_inactive`
      and `test_deleting_an_override_over_a_legacy_value_restores_and_reports_it`,
      and the local-row setup they use); `kit/pool-overrides/tests/unit/test_status.py`.
      Add the delta scenario "A home-site pool has no override" as a
      derivation test against a database that still holds a legacy
      `compute_capacity_pools` row.
- [x] 4.4 Freeze `resources`, `hosts`, `compute_pool_members`, and
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
      Per `design.md`, "Freeze, do not `DROP`; retained data is extraction
      input": remove the retired tables, triggers (including the per-startup
      drop and recreation of `trg_resources_updated_at`), `ALTER`s, and
      indexes from `_ensure_domain_tables` and `_ensure_domain_indexes` in
      `utils/sqlite_client.py`; remove `20260604_002`, `20260611_006`,
      `20260716_008`, and `20260813_010` from `VM_MIGRATIONS` with their
      functions, `_backfill_compute_pools`, and `_resource_attrs`; keep
      `20260604_003` and make its `pool_id` backfill fall back to
      `resource_id` when `compute_pool_members` is absent; leave core
      `_migrate_listing_resource_timestamps` unchanged.
- [x] 4.5 Delete `resource_capacity_validator.py` and `SQLiteClient.upsert_resource`
      with `_sync_compute_pool_for_resource`, `upsert_host`, `get_host` with
      `_host_row_to_dict`, `list_resources`, and `apply_resource_transition`
      once their callers are gone (`get_resource` and
      `apply_resource_set_transition` were already removed by
      `remove-dead-storefront-physical-surfaces`). Retire
      `tests/integration/test_resource_transitions.py` and the
      release-transition case of
      `tests/integration/test_compute_allocations_freeze.py`, keeping its
      freeze cases. The
      transferred local cleanup and resource-count readers are among those
      callers and retire at the same cutover. With
      `remove-dead-storefront-physical-surfaces` landed first, the remaining
      callers are `release_reservations`' local loop, `SystemService`'s count
      and seeding, the validator, and the importers; task 1.7 re-checks this.
      Also delete `tests/unit/test_hosts.py`'s host CRUD and capacity-validator
      cases with the methods they test.
- [x] 4.5a Delete the code describing the retired inventory (`design.md`,
      "Code describing the retired inventory leaves with it"): in
      `domains/vms/listings/src/arkhai_vms_listings/`, the adapters' storage
      half in `resources.py`, `get_supported_resource_types()`, `Host` and
      `ComputeResourcePortfolio` in `models.py`, and their exports in
      `__init__.py`; in `domains/vms/storefront/src/market_storefront/`,
      `ESCROW_TEMPLATES`, `_build_escrow_templates`, and
      `_coerce_templates_table` in `utils/config.py`, and
      `build_storefront_publication_clause_compiler()` in
      `settlement_composition.py`; in `kit/config/src/market_config/config_loader.py`,
      `EscrowTemplate`, `RateSlot`, and `escrow_templates_from_config` with
      their cases in `kit/config/tests/unit/test_config_loader.py`. Retire the
      storage round-trip cases in `tests/unit/test_resources.py` and the
      adapter-join cases in `tests/unit/test_hosts.py`, keeping the wire-format
      cases. Run `kit/config`'s suite and confirm no other package imported
      the removed names.
- [x] 4.5b Move the test fixtures that still seed local rows through
      `SQLiteClient.upsert_resource` onto the projection and site fakes the
      behaviour under test reads, or drop the seed where nothing reads it:
      `domains/vms/storefront/tests/integration/test_negotiate_controller.py`
      (its comment says the inventory guard needs the row; the guard reads the
      projection), `tests/integration/test_settle_controller.py`,
      `tests/integration/test_admin_api.py`,
      `tests/unit/test_fulfillment_service.py`,
      `tests/unit/services/test_system_service.py`, and the remaining case in
      the renamed `tests/unit/test_compute_allocations.py`. A test that only
      passes with the row present is reporting a real dependency on local
      inventory: stop and record it in `design.md` before changing behaviour.
- [ ] 4.6 ~~Document that rollback past this section is a code rollback.~~
      Amended 2026-10-11 (`design.md`, "Upgrades are fail-forward"): document
      in `docs/development/DEPLOYMENT_AND_CONFIG.md` that the upgrade is
      fail-forward with no supported downgrade, and that retained tables stay
      for operator extraction until a later change drops them; name the frozen
      inventory tables beside `compute_allocations` in the frozen-table
      paragraph of "Migrations at startup". Explain
      extraction into provisioning in `docs/seller-quickstart.md`: retained
      data is historical and is reconciled against current provisioning state
      first; no automatic transfer machinery is added.
- [ ] 4.7 Run the full storefront suite and the VM e2e scenarios after the
      combined Sections 3–6 fileset is ready, not against a partial retirement.

## 5. Retire CSV import and its deployment contract

- [x] 5.1 Remove `startup.py`'s `_seed_resources_if_empty` and its
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
      Amended 2026-10-11: the import route is the storefront's only multipart
      consumer, so remove `python-multipart` from
      `domains/vms/storefront/pyproject.toml` and the `File`/`UploadFile`
      imports in `admin_controller.py`, then regenerate the affected locks
      with `make lock` (`docs/development/BUILD_AND_PACKAGING.md`).
      Amended 2026-10-11 (implementation): everything above is done except
      dropping `python-multipart`. `make lock` cannot resolve while
      `download.pytorch.org` is unreachable from the implementation
      environment, and a hand-edited lock is not acceptable, so the dependency
      stays declared until the locks can be regenerated, before closeout.
- [x] 5.3 Remove the CLI surface: `cli_portfolio.py` and its `add_typer`
      registration in `cli.py`, and
      `domains/vms/storefront/scripts/import_resources_csv.py`, with
      `tests/unit/cli/test_portfolio.py`.
- [x] 5.4 Remove the deployment wiring: Helm `_helpers.tpl`'s
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
      Amended 2026-10-11: keep `market_storefront/data/`, which still holds
      the default database path; remove only the CSVs. Also update
      `compose/seller.yml`'s header comment that names
      `resources.sample.csv`, and the compose comment in
      `domains/vms/compose.yml` that says Alice's startup still requires a CSV
      path.
      Amended 2026-10-11 (implementation): with the CSVs gone the directory
      holds no tracked file. The default database path is unaffected: the
      storefront creates its parent directories on first start. The chart's
      `config-<component>-secret.yml` key stays, rendering an empty mapping,
      because the chart's smoke-test pod mounts it.
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
      In `test_full_deal.py` and `test_full_deal_buyer_cli.py`, shared stage
      `00f1` already seeds supply through provisioning
      (`e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`), so VM's
      stage `00f` import and its `resource_count` assertion are deleted, not
      migrated (re-grounded 2026-10-11).
      `test_compute_dynamic_listings.py`'s imported rows share pool
      identifiers with its projected pools, so its listings take SLA and
      region from the legacy tier today; declare them on the pool hint or a
      site-scoped override and keep its published-term assertions. Confirm
      the other files' imports are vestigial before deleting them.
      Replace the resource-count assertions and their import diagnostics: the
      smoke test checks that each configured site's projection families are
      loaded (as `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`
      already does) and that its seeded declarations are present at
      provisioning; stage 00f of both full-deal scenarios seeds through
      provisioning and asserts the projection loaded. Preserve catalogue and
      deal assertions as the evidence of sellable supply.
      `repair-multi-storefront-scenario` must already have migrated
      `test_multi_registry.py`'s Alice seeding and removed her local-path opt-out.
      Preserve that completed work and migrate the remaining CSV consumers
      identified by re-grounding, including Bob's local import where it remains.
      Amended 2026-10-11, per file:
      `e2e-tests/tests/smoke/test_storefront_smoke.py` replaces its
      `resource_count` check and importer instructions with projection-state
      and provisioning checks; `test_full_deal.py` and
      `test_full_deal_buyer_cli.py` delete stage `00f` and their
      `E2E_RESOURCE_CSV`; `test_buy_oneshot_buyer_cli.py` and
      `test_non_erc20_settlement.py` drop their imports once confirmed
      vestigial; `test_compute_dynamic_listings.py` moves its pool SLA and
      region onto the pool hint. Also correct the comments in
      `test_buy_oneshot_buyer_cli.py`, `test_full_deal.py`, and
      `test_full_deal_buyer_cli.py` that cite
      `use_site_projection_for_listings`.
- [x] 5.7 Once 5.2 removes the import route, add an in-process application test
      that the storefront mounts no route under `/api/v1/admin/portfolio/resources`.
      It is the route-level evidence for "Storefront holds no physical-resource
      authority". `remove-dead-storefront-physical-surfaces` deferred this guard
      here: while the import route remains, only a test of the specific paths it
      removed was possible, and that would record history rather than a contract.

- [x] 5.8 Retire the CSV pricing migration (`design.md`, "The CSV pricing
      migration retires with CSV import"): remove `--inventory` and its
      `--scope` checks from `groups/config.py`, `migrate_publication_csv` and
      any helper only it uses from `publication_migration.py`, and the CSV
      cases in `tests/unit/test_publication_migration.py`. Keep
      `migrate_publication_config` and its tests, including
      `tests/unit/cli/test_config.py`'s publication case, passing unchanged.
      Amended 2026-10-11 (implementation): that publication case,
      `test_publication_migration_compiles_a_payment_clause`, exercised
      `_seller_publication_clause_compiler`, which only the CSV migration
      called. Under "any helper only it uses" both are removed; the TOML
      migration's own tests are unchanged.

- [x] 5.9 Refuse the retired settings where retired settlement settings are
      refused (`design.md`, "Retired configuration keys follow the settlement
      retirement convention"): add `resources_csv_path`,
      `resources_csv_inline`, `escrow_templates`, and
      `capacity.use_site_projection_for_listings` to the any-spelling retired
      config keys in `helm/charts/storefront/values.schema.json` and
      `helm/values.schema.json`, and refuse `resourcesCsvInline` under an
      agent's `secret` in both; cover each in
      `helm/charts/storefront/tests/test_render.py`'s retired-key tests. Make
      `market-storefront config set` in `groups/config.py` refuse the same
      keys in any spelling with a removal message naming the seller
      quickstart's upgrade section, with cases in
      `tests/unit/cli/test_config.py`. Add no startup refusal.

## 6. Freeze migration and validation

- [x] 6.1 ~~Add the freeze-then-redirect migration.~~ Amended 2026-10-11: no
      new migration is added; the freeze is task 4.4's bootstrap and chain
      removal. `compute_allocations` is already frozen by
      `remove-dead-storefront-physical-surfaces` (archived 2026-10-08). No
      `DROP`.
- [x] 6.2 Validate migration behavior as `TESTING.md` requires: fresh
      bootstrap, idempotent rerun, drift detection.
      Follow `tests/integration/test_compute_allocations_freeze.py`'s pattern
      (a byte-level snapshot of retained schema, rows, triggers, and recorded
      migration IDs across initialization) in a sibling integration test for
      the inventory tables. Extend `domains/vms/storefront/tests/unit/test_migrations.py` to prove
      that fresh bootstrap omits retired schema and records none of the removed
      migration IDs, and that a populated upgrade and rerun preserve existing
      schema, row contents (including transition history), triggers, and
      recorded migration IDs. Cover `20260604_003` on a legacy database with
      and without `compute_pool_members`. Retire the tests of the removed
      migrations (`test_rename_migration_preserves_data_and_pool_members_fk`
      and any backfill cases). Verify normal startup and status do not recreate or mutate it
      through the storefront integration suite.
      Amended 2026-10-11: the sibling test also asserts that repeated
      initialization leaves `trg_resources_updated_at` and `trg_hosts_updated_at`
      exactly as retained (no drop and recreate), and that a fresh database
      records none of `20260604_002`, `20260611_006`, `20260716_008`, or
      `20260813_010`.
- [ ] 6.3 Run every affected suite — storefront unit and integration,
      `core/storefront-client`, `domains/vms/listings`, and the VM e2e
      scenarios. Disclose any suite not run.
      Amended 2026-10-11: the affected suites are also `core/storefront`,
      `kit/pool-overrides`, `kit/config`, the bare-metal storefront,
      `helm/charts/storefront/tests/`, `scripts/tests/`, and the smoke suite.
- [ ] 6.4 Run `openspec validate --all --strict` against the baseline current
      at implementation time.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the
      touched docstrings directly as well: several — `_local_pool_pricing`,
      `_place_capacity_hold` (`negotiation_runtime.py`), and the reconciler
      entry points' "local-table path" paragraphs — describe an
      arrangement that no longer exists, and stale docstrings are what kept
      these surfaces alive past their callers. `release_reservations`' local
      cleanup and its operator description are part of this cutover;
      `patch_resource` is already gone, removed by
      `remove-dead-storefront-physical-surfaces`.
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
      (Section 4) makes them true of every listing. Amended 2026-10-11: also
      drop "nothing is derived from local tables in its place" from the same
      section's bare-metal paragraph, and the local-tables clause from the
      architecture companion's "Unknown sites and inline reconciliation";
      state fail-forward only for this change, not as a repository rule. Also strike the
      `storefront-publication` architecture companion's description of the
      legacy override record and the `inactive` state ("Storefront pool
      overrides"), and `docs/development/DEPLOYMENT_AND_CONFIG.md`'s state
      list and legacy-terms bullet in "Storefront listing shapes and pool
      overrides".
      Replace the "Operator-visible acceptance state" requirement with the
      delta's "Operator-visible acceptance and projection state" and reconcile
      its Evidence entry. Update `docs/seller-quickstart.md` and
      `docs/development/VALIDATION_RUNBOOK.md` to diagnose inventory
      readiness by per-site projection state, import failures at
      provisioning, and sellable listings through publication diagnostics and
      catalogue checks; remove every `resource_count` check.
      Correct the CSV-input descriptions the retired pricing migration
      leaves: `openspec/specs/storefront-publication/architecture.md`'s
      "Settlement option reconciliation",
      `openspec/specs/settlement-configuration/architecture.md`'s migration
      paragraph, `docs/development/DEPLOYMENT_AND_CONFIG.md`'s publication
      migration paragraph and `--inventory` commands, and
      `docs/seller-quickstart.md`'s `--inventory` commands. Reconcile the
      spec Evidence entry naming `test_resource_csv_importer.py`.
      Promote the fresh-versus-upgraded persistence boundary to
      `openspec/specs/storefront-publication/spec.md`'s "Storefront holds no
      physical-resource authority" and explain inert history in its
      `architecture.md` companion's "Seller-owned market state". Keep the
      fail-forward policy and extraction procedure in the operator documents
      named in task 4.6, and list the retired settings to remove, noting that
      the chart and `config set` refuse them while the runtime ignores them.
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
| Why no carry-over: the status report already enumerates the population, and two of the eight legacy fields cannot be copied | This change's `design.md`, "The legacy override tier retires with the import, without carry-over" |
| Fresh databases omit retired schema; upgrades retain inert schema, rows, and recorded migration IDs for operator extraction into provisioning, with no current storefront reads or writes | `openspec/specs/storefront-publication/spec.md` — "Storefront holds no physical-resource authority"; companion `architecture.md` — "Seller-owned market state"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Migrations at startup" frozen-table paragraph names the inventory tables beside `compute_allocations` |
| ~~Rollback requires earlier code~~ — superseded: the upgrade is fail-forward; retained rows are historical extraction input, reconciled against live site state, not current physical truth | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md` |
| Why the retired migrations leave the chain rather than being gated or emptied, and why `20260604_003` and the core timestamp migration stay | This change's `design.md`, "Freeze, do not `DROP`; retained data is extraction input" |
| Retired settings are refused at chart render and by `config set`, as retired settlement settings are, and ignored at runtime | `openspec/specs/deployment-state/spec.md` (existing retired-values rule, no text change); `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md` |
| Why retired settings are not refused at startup | This change's `design.md`, "Retired configuration keys follow the settlement retirement convention" |
| Code describing the retired inventory, including the `Host` model and `[escrow_templates]` configuration, is deleted rather than left without a caller | This change's `design.md`, "Code describing the retired inventory leaves with it"; nothing permanent to promote once the code is gone |
| Why the legacy tier retires with the import (its only writer) rather than surviving as a lower override tier | This change's `design.md` |
| `kit/pool-overrides` defines exactly the contract's four override states; its projection source is never `None` | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are the only override tier"; companion `architecture.md` — "Storefront pool overrides"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Storefront listing shapes and pool overrides" |
| Why the kit drops `inactive` rather than tolerating `None` | This change's `design.md`, "The pool-override kit loses `inactive`" |
| Publication pricing migration takes TOML configuration only; settlement clauses for a pool come from configuration, hints, or a pool override, never an imported resource record | `openspec/specs/storefront-publication/spec.md` — "Publication pricing migration is preview-first and atomic" (modified) and "Settlement input uses the common clause contract" (replacing "Per-resource settlement input uses the common clause contract"); companion `architecture.md` — "Settlement option reconciliation"; `openspec/specs/settlement-configuration/architecture.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Why the CSV pricing migration retires with import rather than surviving as a converter | This change's `design.md`, "The CSV pricing migration retires with CSV import" |
| Local resource-count diagnosis and local reservation normalization retire with their inventory source | Temporary sequencing decision in this change's `design.md` |
| Complete the separate multi-storefront repair first; retire the local inventory contract, its writers and consumers, and fresh-schema creation together | Temporary sequencing decision in this change's `design.md`; dependency/status in `openspec/changes/README.md` |
| `remove-dead-storefront-physical-surfaces` lands before this change, so this freeze covers only the local inventory tables | Temporary sequencing decision in this change's `design.md`, "The zero-caller removal lands first"; dependency/status in `openspec/changes/README.md` |
| ~~Inventory counts remain separate per site and projection family~~ — superseded: status reports no resource count; inventory readiness is per-site projection state, sellable supply is listings and publication diagnostics, import outcomes are provisioning's | `openspec/specs/storefront-publication/spec.md` — "Operator-visible acceptance and projection state"; `docs/seller-quickstart.md`; `docs/development/VALIDATION_RUNBOOK.md` |
| Why no count replaces `resource_count`, and its provenance | This change's `design.md`, "Status reports no resource count" |
