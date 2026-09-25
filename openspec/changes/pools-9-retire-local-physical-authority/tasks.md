# Tasks

## Status: planned 2026-08-06; re-grounded 2026-09-25

Re-grounded against the current tree on 2026-09-25 (see `design.md`'s
"Re-grounding (2026-09-25)"). Section 0 moved to
`fix-resource-pool-provider-at-creation`; Sections 2 and 3 moved to
`remove-dead-storefront-physical-surfaces`; Section 1's endpoint tasks were
struck because `publish-multidimensional-listing-shape` delivered the write
path; Section 4 gained the legacy-tier retirement and a dependency on
`repair-multi-storefront-scenario`. Section numbers are kept so the
2026-08-06 plan and this one read the same way.

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
   remains a repository-owner decision. (2026-09-25: the gate is met, that
   change archived 2026-09-21. A second gate was found the same day:
   `repair-multi-storefront-scenario`, for Section 4 and task 5.6.)

Sections are ordered so every removal is preceded by its replacement, and
sized to land independently in roughly a day each. Section 1 is a
re-verification pass. Section 4 is the point of no config-flip return.

## 0. Fix a pool's executor at creation

Moved 2026-09-25 to
[`fix-resource-pool-provider-at-creation`](../fix-resource-pool-provider-at-creation/tasks.md),
where tasks 0.1–0.6 continue under the same numbers. A provisioning-side
authority rule with no dependency on this cutover.

## 1. Re-ground

Struck 2026-09-25: tasks 1.2–1.5, which built the `PUT`/`PATCH` override
endpoint, its client methods, and their tests. `publish-multidimensional-listing-shape`
delivered that write path as `kit/pool-overrides` with its own routes, clients,
CLI, and precedence contract; nothing here is owed for it. The section title
and 1.1 keep their numbers.

- [ ] 1.1 Re-run the confirming searches this change's `design.md` records,
      rather than trusting its 2026-08-06 findings: the legacy-resources
      fallback's reachability and the CSV-dependent test file set. (The
      zero-caller methods and `compute_allocations` are
      `remove-dead-storefront-physical-surfaces`' to re-confirm.) Record drift
      in `design.md`.
- [x] ~~1.2 Add `PUT`/`PATCH` admin routes against `compute_capacity_pools`'
      surviving commercial columns.~~ Struck 2026-09-25: delivered as
      `kit/pool-overrides`' site-scoped routes.
- [x] ~~1.3 Confirm the absent-override-row path needs no new handling.~~
      Struck 2026-09-25: normative in "Storefront pool overrides are
      site-scoped and durable"'s per-field fall-through.
- [x] ~~1.4 Add the corresponding client methods to both storefront clients.~~
      Struck 2026-09-25: delivered with the store's typed clients.
- [x] ~~1.5 Focused tests for the endpoint.~~ Struck 2026-09-25: delivered
      with the store.

## 2. Retire `compute_allocations`

Moved 2026-09-25 to
[`remove-dead-storefront-physical-surfaces`](../remove-dead-storefront-physical-surfaces/tasks.md),
where tasks 2.1–2.5 continue under the same numbers. Independent of the
projection cutover.

## 3. Remove dead physical surfaces

Moved 2026-09-25 to the same change, tasks 3.1–3.7 under the same numbers.
Task 3.6's collision warning with `fix-vm-fulfillment-capacity-boundary` is
moot: that change is complete and awaiting archival.

## 4. Retire the local-table listing path

The cutover. Depends on Section 1, on `capacity-resource-administration`
(landed 2026-09-21), and on `repair-multi-storefront-scenario`: the
two-storefront scenario's second storefront derives from local tables because
provisioning does not trust it, and deleting that path before provisioning
can trust two principals leaves her with no listing source.

- [ ] 4.1 Delete `_pool_rows_from_local_tables`, `_pool_rows_from_capacity_pools`,
      `_pool_rows_from_legacy_resources`, `_project_legacy_resource_row`, and
      `_legacy_resource_columns`; make `available_compute_slices` read the
      projection unconditionally.
- [ ] 4.2 Delete `use_site_projection_for_listings` and its reads in
      `capacity_client.py` and `listing_sources.py`, plus its `settings.toml`
      entry, the `storefront.alice.toml` opt-out, and the config-loader tests.
      (Amended 2026-09-25: `cli_publish.py` no longer reads it.)
- [ ] 4.3 Retire the legacy home-site override tier: delete
      `_local_pool_pricing`, the legacy arm of `_tier()` and the `region`
      legacy fallback beside it, the `legacy_overrides_in_effect` derivation
      report, and its system-status field; drop the `inactive` override
      state and its local-table judgment from the pool-override status
      provider. No values are carried into the site-scoped store (decision in
      `design.md`). (Rewritten 2026-09-25; it previously said to keep
      `_local_pool_pricing` as the surviving override tier, which
      `kit/pool-overrides` has replaced.)
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
      registration in `cli.py`, and
      `domains/vms/storefront/scripts/import_resources_csv.py`.
      (Amended 2026-09-25: `cli_publish.py`'s `_import_csv` was removed by
      `unbacked-listing-publication`.)
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
      Include the legacy override tier: which fields the system-status report
      names as still coming from the legacy record, that each must be
      re-entered with `pool-override set` before upgrading or it falls
      through to the hint and the configured default, that `region` must
      instead be declared on the pool hint, and that `accepted_escrows` has
      no equivalent other than a `settlements` clause list.
- [ ] 5.6 Migrate the seven CSV-dependent test files to
      projection/provisioning-service seeding: the six VM scenario files
      named in `proposal.md` plus `e2e-tests/tests/smoke/test_storefront_smoke.py`.
      `test_multi_registry.py`'s Alice stages (02b, 06b, 06c) wait on
      `repair-multi-storefront-scenario`; once provisioning trusts her
      principal, her inventory is seeded through provisioning like Bob's and
      `storefront.alice.toml`'s opt-out goes with the flag in 4.2.

## 6. Freeze migration and validation

- [ ] 6.1 Add the freeze-then-redirect migration covering every table and
      column frozen in Section 4 (and, if it has not landed first, the
      `compute_allocations` freeze `remove-dead-storefront-physical-surfaces`
      owns). Stop writing; redirect reads; no `DROP`.
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
      touched docstrings directly as well: several — `_local_pool_pricing`,
      `_place_capacity_hold`, `_project_host`'s callers — describe an
      arrangement that no longer exists, and stale docstrings are what kept
      these surfaces alive past their callers. (`patch_resource` and
      `release_reservations` are `remove-dead-storefront-physical-surfaces`'.)
- [ ] 7.2 **Import placement.** Review imports this change adds or touches;
      relocate function-level imports where no genuine circular import or
      documented lazy-load reason applies, verified against the real suite.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement rules. Confirm the legacy tier's
      retirement landed as the replacement of `storefront-publication`'s
      site-scoped override requirement and nowhere in
      `resource-pool-management` — see this change's `design.md` correction.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final
      behavior, validation evidence, and promotion destinations; keep the
      sweep findings in `design.md`.
- [ ] 7.5 **Roadmap currency.** Update Goal 1's current-state description and
      gap mapping in `docs/development/ROADMAP.md`. (Amended 2026-09-25:
      `add-development-roadmap` landed 2026-09-04; the condition it carried
      is gone.)
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
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The storefront holds no physical-resource, host, or physical-allocation authority | `openspec/specs/storefront-publication/spec.md` — "Storefront holds no physical-resource authority" |
| Projection-backed derivation is the only listing-candidate path, not the default one | `openspec/specs/storefront-publication/spec.md` — "Storefronts cache independent site projections" (modified) |
| Projection is the listing-candidate origination path; a local-table path is a rollback opt-in, not a second supported category | `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary" |
| The site-scoped store is the only storefront-override tier; the legacy home-site record retires with the import that wrote it, and its values are not carried over | `openspec/specs/storefront-publication/spec.md` — "Storefront pool overrides are the only override tier", replacing "Storefront pool overrides are site-scoped and durable" |
| Why no carry-over: the status report already enumerates the population, and two of the eight legacy fields cannot be copied | This change's `design.md`, "Decision: retire the legacy override tier without carrying values over" |
| Freeze-then-redirect, and that rollback past the cutover is a code rollback | `openspec/specs/storefront-publication/spec.md`, as a scenario on the modified projection requirement |
| Why `region`/`sla` were kept in 2026-08 (commercial override tier, not a missing projection field), and why the tier now retires (its write path is gone and the site-scoped store replaced it) | This change's `design.md` |
