## Why

`pools-8-capacity-projection-and-listing-hints`'s Section 6 set out to retire
the VM storefront's local physical-authority tables (`resources`,
`compute_capacity_pools`, `compute_pool_members`, `hosts`,
`resource_transition_events`) and the local-table code path they feed, now
that the site-resource-pool projection can supply the same structural data.
Re-grounding that section against the exact current code found the actual
retirement work could not safely land in the same change as the one thing
it depended on: flipping `use_site_projection_for_listings`'s default to
`true`. Doing both in one change would collapse the staged-rollout safety
margin to zero — once the local-table code is deleted, "roll back" stops
meaning "flip a config value" and starts meaning "revert the deployment."

`pools-8` therefore did only the flip, plus the new region/SLA/pricing hint
mechanism the retirement will eventually depend on having somewhere to fall
back to. The actual deletion work — freezing and then removing the local
tables, CSV import, and the flag itself — was deliberately left out of that
change's own scope, to be picked up as a separate, later change once the
team's real deployment/versioning strategy says it's appropriate. This
product has no fleet-wide deployment signal to gate that decision on:
sellers self-host and self-operate their own storefront deployments, and
individual `openspec/changes/` entries aren't shipped as discrete releases
against any observable rollout metric. This proposal exists so that
decision has a durable, independent place to live — not inside
`pools-8`'s own change documents, which are expected to be archived (and,
eventually, possibly deleted) once that change's own scope is complete,
regardless of whether this follow-on work has started.


**Expanded 2026-08-06.** A full inter-service sweep of the storefront's
remaining physical-resource concerns, done as roadmap Goal 1 analysis, found
this change's original scope covered the listing-derivation half of the
problem and missed several adjacent surfaces -- a dead execution ledger, an
always-`None` physical identity threaded across the storefront/provisioning
boundary, two admin endpoints with no remaining caller, and the fact that CSV
retirement is a deployment-contract break rather than only a code deletion.
Those findings were folded into "What Changes" below; the sweep's evidence is
recorded in `design.md`. The sweep also produced a hard prerequisite this
change did not previously have -- see "Dependencies and Related Changes".
(2026-09-25: the sweep's zero-caller findings now live in
`remove-dead-storefront-physical-surfaces`; the prerequisite has landed.)

## What Changes

**Re-grounded 2026-09-25.** The scope below was re-verified against the current
tree. Two sections have been moved to their own changes because they land
independently of the cutover and the cutover's start trigger is undefined by
design (see "Split out" below); one prerequisite was met by another change
rather than built here; one non-goal describes a defect that no longer exists;
and one previously unrecorded dependency was found. The findings and the
decisions taken are in `design.md`'s "Re-grounding (2026-09-25)".

### Retire the local-table listing path

- Delete the local-table code path (`_pool_rows_from_local_tables` and
  everything downstream of it in `domains/vms/listings/reconciler.py`) and make
  `available_compute_slices` read the projection unconditionally.
- Delete `use_site_projection_for_listings` itself, its reads in
  `capacity_client.py` and `listing_sources.py`, its `settings.toml` entry, and
  the `storefront.alice.toml` opt-out.
- Retire `hosts` (all columns), `compute_pool_members` (all columns),
  `resources`' remaining physical and commercial columns (confirmed dead in
  the current default code path; task 1.1 re-runs the confirming grep), and
  `compute_capacity_pools.total_gpu_count`.
- Retire the **legacy home-site storefront override tier**: the commercial
  columns of `compute_capacity_pools` (`gpu_model`, `region`, `sla`,
  `min_price`, `token`, `accepted_escrows`, `settlements`,
  `max_duration_seconds`), their reader `_local_pool_pricing`, the
  legacy-fallback arm of `_tier()`, the `legacy_overrides_in_effect` derivation
  report, and the system-status field that surfaces it. The site-scoped
  override store `publish-multidimensional-listing-shape` delivered
  (`kit/pool-overrides`, keyed by site, pool, and offering mode) is the only
  storefront-override tier afterwards. **No values are carried over** from
  the legacy rows into the site-scoped store (decision recorded in
  `design.md`); the operator re-enters any value still in effect through
  `market-storefront pool-override set` or the authenticated API before
  upgrading, guided by the system-status report that names each such field.
- Remove `resource_capacity_validator.py` once its only caller
  (`upsert_resource`'s removal, below) is gone.
- Add the freeze-then-redirect migration (stop writing the retiring columns;
  no `DROP` in this change) and operator-facing documentation that a rollback
  past this change requires a code rollback, not a config flip.
- A genuine schema `DROP` of the frozen columns is explicitly **not** this
  change's own scope — it is a further follow-up, after a full deployment
  cycle confirms the freeze itself never needed rolling back.

### Retire CSV import and its deployment contract

- Remove CSV import (`domains/vms/listings/host_csv_importer.py`,
  `resource_csv_importer.py`, `SQLiteClient.upsert_hosts_from_csv`/
  `upsert_resources_from_csv*`, the
  `POST /api/v1/admin/portfolio/resources/import` route, and
  `storefront_client.admin_import_resources`) and
  `SQLiteClient.upsert_resource`/`_sync_compute_pool_for_resource`. The
  replacement write path for per-pool commercial values that this bullet
  used to wait on is the site-scoped override store; that prerequisite is
  met.
- **Startup CSV seeding stack.** Remove `startup.py`'s `_seed_resources_if_empty`
  and its registered `seed_resources` startup step,
  `SystemService.seed_resources_if_empty`, the `_DEFAULT_CSV_PATH`
  auto-discovery constant, and the `resources_csv_path`/`resources_csv_inline`
  settings.
- **BREAKING (deployment):** retire CSV inventory as an operator deployment
  contract -- `helm/charts/storefront/templates/_helpers.tpl` (two sites),
  `secrets.yaml`'s `resourcesCsvInline`, `values.yaml`'s `--set-file`
  guidance, `compose/seller.yml`'s volume mount and `SELLER_RESOURCES_CSV`,
  `domains/vms/compose.yml`'s two mounts, and `docs/seller-quickstart.md`. An
  operator upgrading past this change must have migrated inventory to the
  provisioning service first, so this needs migration guidance rather than
  deletion alone.
- **CLI import surface.** Remove the `market-storefront portfolio import-csv`
  command with its `cli_portfolio.py` module and `add_typer` registration, and
  `domains/vms/storefront/scripts/import_resources_csv.py`.
  (`cli_publish.py`'s `_import_csv` and `publish --inventory` were already
  removed by `unbacked-listing-publication`.)
- Migrate the seven CSV-dependent test files to projection/provisioning-service
  seeding: `e2e-tests/tests/e2e/roles/scenarios/vms/test_buy_oneshot_buyer_cli.py`,
  `test_compute_dynamic_listings.py`, `test_full_deal.py`,
  `test_full_deal_buyer_cli.py`, `test_multi_registry.py`,
  `test_non_erc20_settlement.py`, and `e2e-tests/tests/smoke/test_storefront_smoke.py`.
  `test_multi_registry.py` seeds a second storefront (Alice) that provisioning
  does not trust; migrating it requires `repair-multi-storefront-scenario`
  (see Dependencies).
### Split out (2026-09-25)

Two bodies of work that this change accumulated during the 2026-08-06 sweep
and the 2026-09-09 Goal 7 review land independently of the cutover and now
have their own changes:

- **[`fix-resource-pool-provider-at-creation`](../fix-resource-pool-provider-at-creation/)**
  — rejecting an in-place provider swap on `ResourcePoolService.replace_pool`
  and `update_pool`. A provisioning-side authority rule with no storefront
  surface in it.
- **[`remove-dead-storefront-physical-surfaces`](../remove-dead-storefront-physical-surfaces/)**
  — retiring `compute_allocations`, the always-`None` `reserved_vm_host`
  plumbing, the orphaned `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`
  surface with its client methods, the legacy local-row half of
  `release_reservations`, the four zero-caller `SQLiteClient` methods, and
  `resource_count` on the health surface. Every item is zero-caller today and
  independent of the projection cutover.

This change keeps the cutover, the CSV and deployment-contract retirement,
the legacy override tier's retirement, and the freeze migration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: the storefront retains no physical-resource, host,
  or physical-allocation authority; projection-backed derivation becomes the
  only listing-candidate path rather than the default one; the site-scoped
  override store is the only storefront-override tier, so the legacy home-site
  override record, the `inactive` override state, and the local-table
  scenarios leave the contract.

## Non-Goals

- Do not `DROP` the frozen columns or tables. Freeze-then-redirect only.
- Do not change capacity admission, matching, scheduling, or fairness policy.
- Do not build a per-pool commercial override write path. `kit/pool-overrides`
  is that path; this change retires the legacy tier beneath it and nothing
  else about storefront-owned commercial state. (Until 2026-09-25 this
  non-goal read the other way -- the commercial columns were to survive as the
  override tier. The site-scoped store has replaced them; see `design.md`.)
- Do not carry legacy override values into the site-scoped store, and do not
  build a migration command for them. Decided 2026-09-25; `design.md` records
  the alternatives and the revisit trigger.
- Do not build the operator path for declaring multi-dimensional capacity --
  `capacity-resource-administration` delivered it (archived 2026-09-21).
- Do not fix a pool's provider at creation or retire the storefront's dead
  physical surfaces here; both are split out (see "Split out").
- Do not migrate the bare-metal storefront, which has no local tables at all.

## Impact

**Expanded 2026-08-06** by the Goal 1 sweep; the original entry named the
listing-derivation surfaces only.

- Affected code (re-inventoried 2026-09-25): `domains/vms/listings/`
  (`reconciler.py`, both CSV importers, `pool_descriptors.py`, `resources.py`),
  `domains/vms/storefront/src/market_storefront/` (`cli_portfolio.py`,
  `cli.py`'s `portfolio` registration, `startup.py`,
  `controllers/admin_controller.py`,
  `services/{capacity_client,listing_sources,system_service,resource_capacity_validator}.py`,
  `utils/{sqlite_client,migrations}.py`, `settings.toml`, `groups/config.py`),
  `domains/vms/storefront/storefront.alice.toml`,
  `domains/vms/storefront/scripts/import_resources_csv.py`, `core/storefront`
  and `core/storefront-client` health and import surfaces, and seven test
  files. `vm_fulfillment_service.py` and the admin resource routes moved to
  `remove-dead-storefront-physical-surfaces`.
- Affected deployment: Helm chart helpers, secrets, and values; both compose
  files; `docs/seller-quickstart.md`. This is the operator-visible half of the
  change; it needs migration guidance, not deletion alone.
- Not affected: `kit/resource-pools` (its provider rule is
  `fix-resource-pool-provider-at-creation`'s), `kit/pool-overrides` (this
  change removes the tier beneath it, not the store), the region/SLA/pricing
  hint mechanism `pools-8` built, and bare metal (already fully
  projection-native, never had this local-table concept to begin with).

## Dependencies and Related Changes

- **Depended on `capacity-resource-administration`** (added 2026-08-06;
  archived 2026-09-21, so the gate is met). Retiring CSV import removes the
  only operator-facing path that had ever expressed multi-dimensional
  capacity; the site authority now declares capacity across every dimension a
  resource names, through the registration API or a capacity-definitions
  document.
- **Depends on `repair-multi-storefront-scenario`** (found 2026-09-25). The
  two-storefront e2e scenario's second storefront, Alice, sets
  `use_site_projection_for_listings = false` on purpose: provisioning trusts
  one storefront principal, so she never loads a projection and derives from
  her local tables. Retiring that path leaves her with no listing source, and
  task 5.6 cannot migrate `test_multi_registry.py` to projection seeding
  until provisioning trusts her. The dependency is on the cutover (Section 4)
  and the test migration (5.6), not on the freeze or the CSV code removal.
- Depends on `pools-8-capacity-projection-and-listing-hints` having landed
  (`use_site_projection_for_listings` defaulting `true`, the region/SLA/pricing
  hint mechanism existing).
- Superseded in part by `publish-multidimensional-listing-shape` (archived
  2026-09-25): its site-scoped override store is the replacement write path
  this change previously scoped an endpoint for.
- `unbacked-listing-publication` (archived 2026-09-24) moved VM publication
  into the storefront lifecycle loop; the loop derives from the same source
  selection, so retiring the local-table path retires it for the loop too.
- Split out 2026-09-25: `fix-resource-pool-provider-at-creation` and
  `remove-dead-storefront-physical-surfaces`. The latter edits adjacent lines
  in `vm_fulfillment_service.py` to `fix-vm-fulfillment-capacity-boundary`,
  which is complete and awaiting archival, so the collision this change
  used to warn about no longer arises.
- `structured-capacity-requirements` remains the owner of requirement/claim
  vocabulary; this change introduces none.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the "Storefront capacity boundary"
      subsection. `pools-8` confirmed the existing "storefront is not the source
      of truth for physical resources" principle already covers this change's
      direction, but nothing in the permanent map says that projection is the
      listing-candidate origination path. That becomes true when this change
      retires the retained local-table path, so it promotes here rather than in
      a downstream change that would inherit an unstated premise. Goal 7's
      unbacked-listing work depends on the statement existing and does not own
      it.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`'s
      "Storefronts cache independent site projections" requirement, which
      already carries the "projection-backed derivation defaults on once
      at parity with a retained local-table path" scenario `pools-8`
      promoted; this change is what actually retires that retained path.
- [ ] No permanent documentation change beyond the above.

### Knowledge to promote

- The freeze-then-redirect migration shape (stop writing, redirect reads,
  no `DROP`) and its rollback-requires-a-code-rollback consequence, once
  implemented — likely the same `storefront-publication` requirement
  named above, as a further scenario.
- The site-scoped override store is the only storefront-override tier, with
  no legacy record beneath it and no `inactive` state, and legacy values are
  not carried over — `openspec/specs/storefront-publication/spec.md`'s
  "Storefront pool overrides are the only override tier", replacing "Storefront
  pool overrides are site-scoped and durable". (The
  endpoint this item used to name was delivered by
  `publish-multidimensional-listing-shape`; the 2026-08-06 correction that
  it belongs in `storefront-publication` rather than
  `resource-pool-management` still holds and is where that change promoted
  it.)
- The storefront retains no physical-resource, host, or physical-allocation
  authority, and the local-table derivation path is removed outright rather
  than demoted to a non-default option —
  `openspec/specs/storefront-publication/spec.md`.
