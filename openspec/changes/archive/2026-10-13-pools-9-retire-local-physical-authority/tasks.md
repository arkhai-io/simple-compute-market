# Tasks

## Status: archived 2026-10-13; implemented, reviewed, and validated end to end

Section numbers keep the original plan's. Section 0 is
`fix-resource-pool-provider-at-creation`'s, and Section 2 and most of Section 3
were delivered by `remove-dead-storefront-physical-surfaces`. Sections 3–6 are
one coordinated retirement of the local inventory contract: they were built
together and deploy together. Design decisions D1–D7, and the two migration
decisions revised after implementation review, are in `design.md`. Each
completed task states its final behaviour, its evidence, and where any durable
decision was promoted.

## 0. Fix a pool's executor at creation

Owned by [`fix-resource-pool-provider-at-creation`](../fix-resource-pool-provider-at-creation/tasks.md).

## 1. Re-ground

- [x] 1.1 The legacy-resources fallback was unreachable, and six CSV-dependent
      test files remained (`design.md`, "Re-grounding").
- [x] ~~1.2–1.5 Override endpoints, clients, and tests.~~ Struck:
      `kit/pool-overrides` is the per-pool override write path.
- [x] 1.6 `repair-multi-storefront-scenario` was archived with its
      two-storefront scenario passing; Alice derives from provisioning-seeded
      projections.
- [x] 1.7 `remove-dead-storefront-physical-surfaces` was archived before
      Sections 3–6 began; this plan was re-grounded against it (`design.md`,
      "Re-grounding against `dev`").

## 2. Retire `compute_allocations`

Delivered by [`remove-dead-storefront-physical-surfaces`](../archive/2026-10-08-remove-dead-storefront-physical-surfaces/tasks.md).

## 3. Remove dead physical surfaces

Tasks 3.1, 3.2, and 3.5–3.12 were delivered by the same change.

- [x] 3.3 `release_reservations` releases only site-ledger reservations and
      touches no storefront table; its summary and `resource_ids` description
      name site reservations. Evidence:
      `domains/vms/storefront/tests/integration/test_admin_api.py`
      (`TestReleaseReservations`).
- [x] 3.4 No storefront status, core `HealthResponse`, bare-metal health, or
      typed client carries `resource_count` (`design.md`, "Status reports no
      resource count"); bare metal's `count_open_bare_metal_resources` is gone.
- [x] 3.8 Evidence: `test_admin_api.py::test_system_status_reports_no_resource_count`,
      `domains/bare_metal/storefront/tests/test_http_system.py`, and
      `tests/unit/services/test_system_service.py`, which runs status on a
      database without a `resources` table.

## 4. Retire the local-table listing path

- [x] 4.1 `available_compute_slices` and every derivation entry point read only
      the site projection; the local-table builders and
      `_local_table_shapes` are deleted. Evidence:
      `tests/unit/test_reconciler.py`,
      `tests/integration/test_reconciler_derivation.py`, and
      `test_reconciler_projection.py`; the capacity-hold round trip moved to
      `tests/unit/test_capacity_holds.py`.
- [x] 4.2 `use_site_projection_for_listings` is gone from settings, readers, and
      tests; the compose profile test asserts its absence.
- [x] 4.2a The projection is a required argument everywhere; `home_site` is
      removed; `listing_source_projection()` is replaced by
      `site_pool_projection()`. The fake capacity site's projection refreshes
      from the fake's live availability, so inline reconciliation in tests
      reads what production reads.
- [x] 4.3 The legacy home-site tier is retired: `_tier()` reads only the
      site-scoped override, region comes only from the pool hint, and
      `legacy_overrides_in_effect` is gone. `kit/pool-overrides` has four
      override states and a non-optional projection source. Promoted:
      `storefront-publication` spec, "Storefront pool overrides are the only
      override tier"; companion "Storefront pool overrides".
- [x] 4.3a Evidence: `test_reconciler_derivation.py::test_a_home_site_pool_without_an_override_ignores_a_retained_legacy_row`;
      `kit/pool-overrides/tests/unit/test_status.py`; bare metal's override
      suite unchanged.
- [x] 4.4 The retired inventory tables are frozen: bootstrap creates, alters,
      and re-triggers none of them; `20260604_002`, `20260611_006`,
      `20260716_008`, and `20260813_010` leave `VM_MIGRATIONS`;
      `20260604_003` takes each legacy listing's own `resource_id` and reads no
      retired table; core `_migrate_listing_resource_timestamps` stamps
      `listings` only. Promoted: `storefront-publication` spec, "Storefront
      holds no physical-resource authority"; companion "Seller-owned market
      state"; `DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup".
- [x] 4.5 `SQLiteClient`'s resource, host, and transition methods and the
      capacity validator are deleted, with `test_resource_transitions.py`,
      `test_hosts.py`, and the freeze test's transition case.
- [x] 4.5a The adapters keep only their wire-format half; `Host`,
      `ComputeResourcePortfolio`, the escrow-template configuration in the
      storefront and `kit/config`, and
      `build_storefront_publication_clause_compiler` are deleted (`design.md`,
      "Code describing the retired inventory leaves with it").
- [x] 4.5b No test seeds a local row; every behaviour under test passed with
      the seed removed, so none depended on local inventory.
- [x] 4.6 The upgrade is fail-forward for this change only, and retained
      tables stay for extraction: `DEPLOYMENT_AND_CONFIG.md`, "Migrations at
      startup"; `docs/seller-quickstart.md`, "Upgrading from CSV inventory".
- [x] 4.7 The VM storefront suite passes on the final tree: 1374 passed and 1
      skipped, with the two `test_alkahest.py` cases excluded because they need
      a live chain environment and predate this change. The VM e2e scenarios
      pass (see 7.9).
- [x] 4.8 Publication holds a VM pool that states no region and reports it,
      rather than refusing it on every cycle with a validation message; the
      pool's rows are still derived, so availability reconciliation closes a
      sold-out listing (`publication_loop.py`, `pool_region_missing`;
      `reconciler.py`, `regionless_pools`). The VM test fixtures state a
      region on the pool and its members. Evidence:
      `test_publication_loop.py` (`test_a_pool_stating_no_region_publishes_nothing_and_is_reported`,
      `test_a_pool_losing_its_region_holds_its_listings_open`,
      `test_a_regionless_pools_sold_out_listing_still_closes`),
      `test_reconciler_projection.py::test_a_pool_stating_no_region_is_reported_and_still_derived`,
      and the `test_reconciler.py` row case; every one except the
      held-open case fails without the change, which the old refusal also
      satisfied. Promoted: `storefront-publication` spec, "A VM
      pool that states no region holds its listings"; companion `architecture.md`;
      `DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md`.

## 5. Retire CSV import and its deployment contract

- [x] 5.1 Startup seeding, `SystemService.seed_resources_if_empty`, and the
      `resources_csv_path`/`resources_csv_inline` settings are removed.
- [x] 5.2 Both importers, their `SQLiteClient` wrappers, the import route with
      its administrator contract and multipart descriptor, both response
      models, both client variants' `admin_import_resources`, and their tests
      are removed. `python-multipart` is dropped and the storefront and
      `e2e-tests` locks regenerated.
- [x] 5.3 The `portfolio` CLI command, the storefront's resource-import script, and
      their test are removed.
- [x] 5.4 Helm, compose, both seller TOMLs, both Makefiles, `.dockerignore`, and
      the bundled CSVs no longer supply a CSV. The chart's
      `config-<component>-secret.yml` key renders an empty mapping because the
      chart's smoke-test pod mounts it. The default database path is
      unaffected: its parent directories are created on first start.
- [x] 5.5 `docs/seller-quickstart.md`, "Upgrading from CSV inventory", covers
      moving hosts, capacity, pool terms, and storefront terms to provisioning
      and overrides, the retired settings, and extraction from retained
      tables.
- [x] 5.6 The VM e2e scenarios declare their supply at provisioning:
      `test_full_deal.py` and `test_full_deal_buyer_cli.py` drop stage `00f`;
      `test_buy_oneshot_buyer_cli.py` drops its vestigial import;
      `test_non_erc20_settlement.py`, whose import left its listings without a
      projected source, declares one executor and pool per case;
      `test_compute_dynamic_listings.py` takes region from the pool hint and
      SLA from an override, because the storefront reads a pool's `sla` hint
      only with `accept_pool_declared_sla` on. The smoke check asserts every
      site's projection families are loaded. All modules collect.
- [x] 5.7 Evidence:
      `tests/unit/test_server_app_composition.py::test_the_storefront_mounts_no_physical_resource_route`.
- [x] 5.8 `--inventory` and `migrate_publication_csv` are retired, with
      `_seller_publication_clause_compiler` and its `test_config.py` case,
      which only the CSV path used. Promoted: `storefront-publication` spec,
      "Publication pricing migration is preview-first and atomic" and
      "Settlement input uses the common clause contract"; companion
      "Settlement option reconciliation";
      `settlement-configuration/architecture.md`.
- [x] 5.9 Both values schemas refuse the retired keys in any spelling and
      `secret.resourcesCsvInline`; `config set` refuses them, naming the
      seller quickstart's upgrade section; startup does not. Evidence:
      `helm/charts/storefront/tests/test_render.py` (rendered through a
      containerised `helm`) and `tests/unit/cli/test_config.py`.

## 6. Freeze migration and validation

- [x] 6.1 ~~Freeze-then-redirect migration.~~ No new migration: the freeze is
      task 4.4's bootstrap and chain change.
- [x] 6.2 Evidence: `tests/integration/test_inventory_freeze.py` snapshots
      retained schema, rows, triggers, and recorded migration IDs across
      repeated initialization and a status read, for four histories (all
      migrations recorded; pools only; core timestamp migration pending over
      timestamped rows and their trigger; rows older than resource
      timestamps). Against the previous code every case failed, and the last
      two failed against the previous core migration alone.
      `tests/unit/test_migrations.py` covers a fresh bootstrap and the
      `20260604_003` backfill with and without a retained members table.
- [x] 6.3 Pass on the final tree: storefront unit and integration,
      `core/storefront`, `core/storefront-client`, `kit/pool-overrides`,
      `kit/config`, the VM buyer and domain packages, the bare-metal and
      API-credits storefronts, `scripts/tests/`, and the chart render tests.
      The e2e lanes and the deployed smoke suite pass (see 7.9).
- [x] 6.4 This change and both touched specifications validate strictly; the
      other failures in `validate --all --strict` are in other active changes.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 7.1 **Comment hygiene.** `make check-comment-hygiene` passes; touched
      docstrings, including the ones implementation review found in
      `utils/sqlite_client.py`, `ComputeResource`, and core's subclassing
      notes, describe the current system.
- [x] 7.2 **Import placement.** No function-level import was added in
      production code.
- [x] 7.3 **Documentation compliance.** The legacy tier's retirement is
      `storefront-publication`'s alone; `resource-pool-management` is
      untouched.
- [x] 7.4 **Narrative compression.** Done 2026-10-13: this ledger.
- [x] 7.5 **Roadmap currency.** `docs/development/ROADMAP.md` Goal 1 describes
      storefronts holding no physical state; the gap row is closed and the
      retained-table drop stays a later follow-up.
- [x] 7.6 **Promotion.** Applied after implementation review: see the record
      below. The delta replaced four `storefront-publication` requirements in
      place, modified two, and added one, with Evidence reconciled; the
      companion, `settlement-configuration/architecture.md`, and
      `ARCHITECTURE.md` are corrected; operator documents were updated under
      4.6 and 5.5.
- [x] 7.7 **Campaign index currency.** `openspec/changes/README.md` records the
      change as implemented, reviewed, and promoted, with the e2e and deployed
      smoke evidence 7.9 records; its place in the campaign graph is unchanged.
- [x] 7.8 **Documentation citations.** Every citation in this change's
      documents and in the promoted Evidence resolves. The repository-wide
      check's remaining failures are in files this change does not touch.
- [x] 7.9 **End-to-end pipeline.** Evidence by revision, 2026-10-13:
      - **`c30cb4de`.** Pipeline run 38368952135: the VM lane passed 129
        (`test_full_deal.py`, `test_full_deal_buyer_cli.py`,
        `test_buy_oneshot_buyer_cli.py`, `test_compute_dynamic_listings.py`,
        `test_listing_shapes.py`, `test_multi_registry.py`,
        `test_vm_introduction.py`, and the Alkahest escrow codecs), bare metal
        51, and API credits 1 with 3 skipped. A deployed chart passed
        `helm test`: registry 3, storefront 3 (including
        `test_site_projections_loaded`, reporting site `default` loaded),
        provisioning 3 with 1 skipped (no host registered), and chain
        validation 1. The smoke run needed the shared e2e fixtures to expose
        the seller and provisioning administrator settings the mounted profile
        already held (`e2e-tests/tests/conftest.py`); before that the
        storefront smoke checks skipped.
      - **`40f5805f`.** Since `c30cb4de`: startup migrations that run only on
        a legacy database (`test_inventory_freeze.py`), docstrings, permanent
        documents, the VM lane selecting `test_non_erc20_settlement.py`, that
        scenario's repair, and a defect the scenario surfaced, fixed here: a
        proposal built from a native-token escrow entry named its token as
        `None`, so its escrow never verified, and the verifier's mismatch
        report omitted a key present on one side only
        (`kit/alkahest/tests/unit/test_native_escrow_verification.py`).
        Pipeline run 38376907354 passed all three lanes, the VM lane 131 with
        both settlement cases.
      - **`f48e2f71`.** Since `40f5805f`: publication's hold on a VM pool that
        states no region (4.8). Pipeline run 38379978667 passed all three
        lanes, the VM lane 131; its storefront logs carry `pool_region_missing`
        holds where the earlier runs carried validation refusals. The first
        version of the hold, at `597fac49`, failed seven VM scenarios in run
        38379186498 because it also removed the pool from the round-zero
        inventory guard; see `design.md`.
      - **After `f48e2f71`.** Comments, docstrings, the task ledger, and
        `design.md` only.

      The deployed smoke suite was not re-run after `c30cb4de`: nothing since
      changes chart rendering, configuration, service readiness, or projection
      loading, which are what it checks; the region hold changes publication,
      which it does not exercise.
- [x] 7.10 **Packaging.** `make check-packaging` passes after the relock that
      dropped `python-multipart`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-resource, host, or physical-allocation authority | `openspec/specs/storefront-publication/spec.md` — "Storefront holds no physical-resource authority" |
| Projection-backed derivation is the only listing-candidate path, not the default one | `openspec/specs/storefront-publication/spec.md` — "Projection-backed listing candidate derivation", replacing "Storefronts cache independent site projections"; the unbacked-listing and inline-reconciliation rules widened to every listing; companion `architecture.md` — "Unknown sites and inline reconciliation" |
| A site whose projection is not held yields no listing from any other source | `openspec/specs/storefront-publication/spec.md` — "A site whose projection is not held holds its listings" (modified) |
| Projection is the only listing-candidate origination path; no local-table path or configuration option selects another source | `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary"; its host-naming paragraph no longer names storefront inventory tables as a live exception |
| The site-scoped store is the only storefront-override tier; the legacy home-site record retires with the import that wrote it, and its values are not carried over | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are the only override tier", replacing "Storefront pool overrides are site-scoped and durable" |
| Why no carry-over: the status report already enumerates the population, and two of the eight legacy fields cannot be copied | This change's `design.md`, "The legacy override tier retires with the import, without carry-over" |
| Fresh databases omit retired schema; upgrades retain inert schema, rows, and recorded migration IDs for operator extraction into provisioning, with no current storefront reads or writes, startup migrations included | `openspec/specs/storefront-publication/spec.md` — "Storefront holds no physical-resource authority"; companion `architecture.md` — "Seller-owned market state"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Migrations at startup" frozen-table paragraph names the inventory tables beside `compute_allocations` |
| ~~Rollback requires earlier code~~ — superseded: the upgrade is fail-forward; retained rows are historical extraction input, reconciled against live site state, not current physical truth | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md` |
| Why the retired migrations leave the chain rather than being gated or emptied, why `20260604_003` stays without reading a retired table, and why the core timestamp migration covers `listings` only | This change's `design.md`, "Freeze, do not `DROP`; retained data is extraction input" |
| A VM pool that states no region is held and reported, not refused on every cycle | `openspec/specs/storefront-publication/spec.md` — "A VM pool that states no region holds its listings"; companion `architecture.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/seller-quickstart.md`; rationale in this change's `design.md`, "A VM pool that states no region is held" |
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
