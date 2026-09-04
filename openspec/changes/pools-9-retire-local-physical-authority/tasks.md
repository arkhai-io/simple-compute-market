# Tasks

## Status: planned 2026-08-06

This change's original `tasks.md` was a discuss-phase stub listing four
questions owed before a plan could be written. Three are now resolved; the
fourth remains open by design. Preserved here rather than deleted, per
`AGENTS.md`'s rule to amend rather than replace planning history:

1. **Re-confirm `resources`' commercial columns are dead in the default code
   path** — resolved 2026-08-06. They are read only by
   `_project_legacy_resource_row`, reached only through
   `_pool_rows_from_legacy_resources`, which `_pool_rows_from_local_tables`
   selects only when `compute_capacity_pools` or `compute_pool_members` does
   not exist. Migrations create both unconditionally, so no migrated
   deployment reaches it. Task 1.1 re-runs this check at implementation time.
2. **Re-confirm the CSV-dependent test files** — resolved 2026-08-06. The six
   named scenario files are still accurate, and a seventh was found:
   `e2e-tests/tests/smoke/test_storefront_smoke.py`.
3. **Does the pool-commercial-metadata endpoint need pool creation?** —
   resolved 2026-08-06 (repository owner). Neither creation nor edit-only: an
   upsert of an override row against a pool that already exists in the
   projection. See `design.md`'s "The open scope question from this document
   is now answered."
4. **The trigger for starting this change** — still open, deliberately. What
   is new is a hard technical gate that did not previously exist: this change
   now depends on `capacity-resource-administration`. That gate is necessary,
   not sufficient; the deployment-bake judgment `pools-8` declined to specify
   remains a repository-owner decision.

Sections are ordered so every removal is preceded by its replacement, and
sized to land independently in roughly a day each. Sections 1–3 are additive
or inert and safe to deploy alone. Section 4 is the point of no config-flip
return.

## 1. Re-ground and build the commercial override write path

Nothing may be deleted before this section lands: `_sync_compute_pool_for_resource`
is currently the only writer of pool-level pricing anywhere in the storefront.

- [ ] 1.1 Re-run the confirming searches this change's `design.md` records,
      rather than trusting its 2026-08-06 findings: the legacy-resources
      fallback's reachability, the CSV-dependent test file set, the four
      zero-caller methods, and `compute_allocations`' lack of any production
      `INSERT`. Record drift in `design.md`.
- [ ] 1.2 Add `PUT`/`PATCH` admin routes against `compute_capacity_pools`'
      surviving commercial columns, mirroring `kit/resource-pools`'
      `PoolReplace`/`PoolUpdate` shape. Upsert semantics: the row is created
      or replaced for a pool that already exists in the projection; the
      endpoint never creates a pool.
- [ ] 1.3 Confirm the absent-override-row path needs no new handling —
      `pricing_resolution.resolve_gpu_pricing` already resolves each field
      independently and falls through a missing tier — and cover it with
      tests rather than code.
- [ ] 1.4 Add the corresponding client methods to both the async and sync
      storefront clients in the same change, with the parity contract test
      `TESTING.md` requires.
- [ ] 1.5 Focused tests: create-on-first-write, partial update, override wins
      over projected hint, absent row falls through to hint then to config
      default.

## 2. Retire `compute_allocations`

Independent of the projection cutover — this table is not part of the listing
derivation path at all. Sequenced early because it shrinks the surface later
sections reason about.

- [ ] 2.1 Remove `held_gpu_counts`, `held_gpu_counts_by_resource`, and
      `allocation_table_exists` from `domains/vms/listings/reconciler.py` and
      their exports from that package's `__init__.py`.
- [ ] 2.2 Remove the release-`UPDATE` against `compute_allocations` from
      `SQLiteClient.apply_resource_transition`, including the
      `$.allocation_id`/`$.compute_allocation_id` attribute-path special case
      that feeds it.
- [ ] 2.3 Freeze the table: stop creating it in `_ensure_domain_tables`, stop
      creating its trigger and four indexes, and stop adding its columns in
      `migrations.py`. No `DROP`.
- [ ] 2.4 Remove the test-only `INSERT` in `test_cli_publish_helpers.py` and
      any assertion that depends on it.
- [ ] 2.5 Run the storefront unit and integration suites.

## 3. Remove dead physical surfaces

All zero-caller. Independent of the cutover and of each other.

- [ ] 3.1 Delete `SQLiteClient.delete_resource`, `ensure_default_resources`,
      `host_capacity_remaining`, and `list_hosts`, plus the
      `host_capacity_remaining` tests in `tests/unit/test_hosts.py`.
- [ ] 3.2 Remove `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`,
      their request/response models, and `storefront_client`'s `get_resource`
      and `patch_resource` on both client variants.
- [ ] 3.3 Remove the legacy local-row normalization loop from
      `release_reservations`, keeping `_release_site_ledger_holds` unchanged,
      and rewrite the docstring, which currently describes the storefront as
      clearing bookkeeping "via the provisioning service's LeaseWatchdog."
- [ ] 3.4 Remove `resource_count` from `SystemService.get_health` and from
      both `core_storefront`'s and `storefront_client`'s `HealthResponse`.
      Update `storefront-publication`'s Evidence entry, which cites
      resource-count diagnosis.
- [ ] 3.5 Remove the always-`None` `reserved_vm_host` and its threading
      through `register_lease`, `schedule_shutdown`, `provision_vm`,
      `_do_provision`, and `_register_vm_lease_with_settings`. Leave
      `vm_host` inside the provisioning adapter untouched — it is the real
      execution target there.
- [ ] 3.6 Check for collision with `fix-vm-fulfillment-capacity-boundary`,
      which edits adjacent lines in `fulfill_vm_obligation`, and coordinate
      rather than resolving blind.
- [ ] 3.7 Run the storefront and `core/storefront-client` suites plus the
      client parity contract test.

## 4. Retire the local-table listing path

The cutover. Depends on Section 1, and on `capacity-resource-administration`
having landed so multi-dimensional capacity remains declarable.

- [ ] 4.1 Delete `_pool_rows_from_local_tables`, `_pool_rows_from_capacity_pools`,
      `_pool_rows_from_legacy_resources`, `_project_legacy_resource_row`, and
      `_legacy_resource_columns`; make `available_compute_slices` read the
      projection unconditionally.
- [ ] 4.2 Delete `use_site_projection_for_listings` and its reads in
      `capacity_client.py` and `cli_publish.py`, plus its `settings.toml`
      entry and config-loader tests.
- [ ] 4.3 Keep `_local_pool_pricing` — it reads the surviving commercial
      override tier, not physical state. Confirm by reading it rather than
      by name.
- [ ] 4.4 Freeze `resources`, `hosts`, `compute_pool_members`, and
      `resource_transition_events`: stop creating them, their triggers, and
      their indexes. No `DROP`. Existing `resource_transition_events` rows
      are history and must not be deleted.
- [ ] 4.5 Delete `resource_capacity_validator.py` and `SQLiteClient.upsert_resource`
      with `_sync_compute_pool_for_resource`, `upsert_host`, `get_host`,
      `get_resource`, `list_resources`, `apply_resource_transition`, and
      `apply_resource_set_transition` once their callers are gone.
- [ ] 4.6 Document, for operators, that rollback past this section is a code
      rollback rather than a configuration change.
- [ ] 4.7 Run the full storefront suite and the VM e2e scenarios.

## 5. Retire CSV import and its deployment contract

- [ ] 5.1 Remove `startup.py`'s `_seed_resources_if_empty` and its
      `seed_resources` startup step, `SystemService.seed_resources_if_empty`,
      `_DEFAULT_CSV_PATH`, and the `resources_csv_path`/`resources_csv_inline`
      settings including their `groups/config.py` documentation.
- [ ] 5.2 Remove `host_csv_importer.py`, `resource_csv_importer.py`,
      `SQLiteClient.upsert_hosts_from_csv` and `upsert_resources_from_csv*`,
      the `POST /api/v1/admin/portfolio/resources/import` route, and
      `storefront_client.admin_import_resources`.
- [ ] 5.3 Remove the CLI surface: `cli_portfolio.py` and its `add_typer`
      registration, `cli_publish.py`'s `_import_csv`, and
      `scripts/import_resources_csv.py`.
- [ ] 5.4 Remove the deployment wiring: Helm `_helpers.tpl` (both sites),
      `secrets.yaml`'s `resourcesCsvInline`, `values.yaml`'s `--set-file`
      guidance, `compose/seller.yml`'s mount and `SELLER_RESOURCES_CSV`, and
      `domains/vms/compose.yml`'s two mounts.
- [ ] 5.5 Write operator migration guidance in `docs/seller-quickstart.md`
      covering how to move CSV inventory to the provisioning service's host
      inventory, pool definitions, and capacity declarations. This is
      required, not optional: seeding silently skips when it finds no source,
      so an unmigrated operator gets an empty storefront and no error.
      Check `docs/bare-metal-seller-quickstart.md` for the same references.
- [ ] 5.6 Migrate the seven CSV-dependent test files to
      projection/provisioning-service seeding: the six VM scenario files
      named in `proposal.md` plus `e2e-tests/tests/smoke/test_storefront_smoke.py`.

## 6. Freeze migration and validation

- [ ] 6.1 Add the freeze-then-redirect migration covering every table and
      column frozen in Sections 2 and 4. Stop writing; redirect reads; no
      `DROP`.
- [ ] 6.2 Validate migration behavior as `TESTING.md` requires: fresh
      bootstrap, idempotent rerun, drift detection.
- [ ] 6.3 Run every affected suite — storefront unit and integration,
      `core/storefront-client`, `domains/vms/listings`, and the VM e2e
      scenarios. Disclose any suite not run.
- [ ] 6.4 Run `openspec validate --all --strict` against the baseline current
      at implementation time.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the
      touched docstrings directly as well: several — `patch_resource`,
      `release_reservations`, `_place_capacity_hold`, `_project_host`'s
      callers — describe an arrangement that no longer exists, and stale
      docstrings are what kept these surfaces alive past their callers.
- [ ] 7.2 **Import placement.** Review imports this change adds or touches;
      relocate function-level imports where no genuine circular import or
      documented lazy-load reason applies, verified against the real suite.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement rules. Confirm the override endpoint's
      shape landed in `storefront-publication`, not `resource-pool-management`
      — see this change's `design.md` correction.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final
      behavior, validation evidence, and promotion destinations; keep the
      sweep findings in `design.md`.
- [ ] 7.5 **Roadmap currency.** Update Goal 1's current-state description and
      gap mapping in `docs/development/ROADMAP.md`. If `add-development-roadmap`
      has not landed when this change completes, record that disposition
      explicitly rather than skipping the step.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.
- [ ] 7.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-resource, host, or physical-allocation authority | `openspec/specs/storefront-publication/spec.md` — "Storefront holds no physical-resource authority" |
| Projection-backed derivation is the only listing-candidate path, not the default one | `openspec/specs/storefront-publication/spec.md` — "Storefronts cache independent site projections" (modified) |
| Commercial pool overrides are upserted against projected pools; an absent row falls through | `openspec/specs/storefront-publication/spec.md` — "Commercial pool override administration" |
| Freeze-then-redirect, and that rollback past the cutover is a code rollback | `openspec/specs/storefront-publication/spec.md`, as a scenario on the modified projection requirement |
| Why `region`/`sla` survive (commercial override tier, not a missing projection field) | This change's `design.md`; the surviving behavior itself is the override requirement above |
