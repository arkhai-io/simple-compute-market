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
Those findings are folded into "What Changes" below; the sweep's evidence is
recorded in `design.md`. The sweep also produced a hard prerequisite this
change did not previously have -- see "Dependencies and Related Changes".

## What Changes

### Original scope (unchanged)

- Freeze writes to the retiring physical-identity columns, then delete the
  local-table code path (`_pool_rows_from_local_tables` and everything
  downstream of it in `domains/vms/listings/reconciler.py`) once
  `use_site_projection_for_listings` no longer needs a fallback to gate.
- Delete `use_site_projection_for_listings` itself, once nothing reads it.
- Remove CSV import (`domains/vms/listings/host_csv_importer.py`,
  `resource_csv_importer.py`, `SQLiteClient.upsert_hosts_from_csv`/
  `upsert_resources_from_csv*`, the
  `POST /api/v1/admin/portfolio/resources/import` route) and
  `SQLiteClient.upsert_resource`/`_sync_compute_pool_for_resource` —
  **only after** a replacement write path for `compute_capacity_pools`'
  surviving commercial columns exists (see below; this is not optional
  scope, CSV import is currently the only way an operator sets or changes
  pool-level pricing at all).
- Build the direct pool-commercial-metadata admin endpoint
  `pools-8`'s own task 6.2 scoped but did not implement (`PUT`/`PATCH`
  routes in `admin_controller.py` against `compute_capacity_pools`'
  surviving columns, mirroring `kit/resource-pools`'s own
  `PoolReplace`/`PoolUpdate` shape) — a prerequisite of the CSV-import
  removal above, not a separate nice-to-have.
- Retire `hosts` (all columns), `compute_pool_members` (all columns),
  `resources`' remaining physical and commercial columns (confirmed dead
  in the current default code path by `pools-8`, pending one final
  repo-wide confirming grep at implementation time), and
  `compute_capacity_pools.total_gpu_count`.
- Remove `resource_capacity_validator.py` once its only caller
  (`upsert_resource`'s removal, above) is gone.
- Migrate the six e2e scenario files that currently seed resources through
  CSV import to projection/provisioning-service-based seeding:
  `e2e-tests/tests/e2e/roles/scenarios/vms/test_buy_oneshot_buyer_cli.py`,
  `test_compute_dynamic_listings.py`, `test_full_deal.py`,
  `test_full_deal_buyer_cli.py`, `test_multi_registry.py`,
  `test_non_erc20_settlement.py`.
- Add the freeze-then-redirect migration (stop writing the retiring
  columns; no `DROP` in this change) and operator-facing documentation
  that a rollback past this change requires a code rollback, not a config
  flip, since it removes the local-table path outright.
- A genuine schema `DROP` of the frozen columns is explicitly **not** this
  change's own scope — it is a further follow-up, after a full deployment
  cycle confirms the freeze itself never needed rolling back, matching
  every other schema change in the POOLS campaign being additive-only
  until that confirmation exists.

### Added 2026-08-06 from the Goal 1 sweep

- **Startup CSV seeding stack.** Remove `startup.py`'s `_seed_resources_if_empty`
  and its registered `seed_resources` startup step,
  `SystemService.seed_resources_if_empty`, the `_DEFAULT_CSV_PATH`
  auto-discovery constant, and the `resources_csv_path`/`resources_csv_inline`
  settings. The original scope named the import *modules* and the import
  *route* but not the startup path that calls them.
- **BREAKING (deployment):** retire CSV inventory as an operator deployment
  contract -- `helm/charts/storefront/templates/_helpers.tpl` (two sites),
  `secrets.yaml`'s `resourcesCsvInline`, `values.yaml`'s `--set-file`
  guidance, `compose/seller.yml`'s volume mount and `SELLER_RESOURCES_CSV`,
  `domains/vms/compose.yml`'s two mounts, and `docs/seller-quickstart.md`. An
  operator upgrading past this change must have migrated inventory to the
  provisioning service first, so this needs migration guidance rather than
  deletion alone.
- **CLI import surface.** Remove the `market-storefront portfolio import-csv`
  command with its `cli_portfolio.py` module and `add_typer` registration,
  `cli_publish.py`'s `_import_csv`, and `scripts/import_resources_csv.py`.
- **A seventh CSV-dependent test file** beyond the six originally named:
  `e2e-tests/tests/smoke/test_storefront_smoke.py`, which points operators at
  the import script in its guidance output.
- **Remove `resource_count` from the health surface** -- `SystemService.get_health`
  and the field on both `core_storefront`'s and `storefront_client`'s
  `HealthResponse`. It counts a table being retired, and an equivalent is
  recomputable from the projection if one is ever wanted.
- **Delete four methods with no production caller**: `SQLiteClient.delete_resource`
  and `ensure_default_resources` (no reference anywhere, including tests),
  `host_capacity_remaining` (referenced only by its own tests), and the
  storefront's `list_hosts`.
- **Retire `compute_allocations`** -- table, update trigger, four indexes, and
  its migration-added columns. `kit/site`'s `CapacityReservation` states in its
  own model docstring that it merges this table's shape and that the watchdog
  now updates the ledger row "instead of PATCHing the storefront's resource
  table." No production code inserts into it; its only writer is a
  release-`UPDATE` inside `apply_resource_transition`, and its readers
  (`held_gpu_counts`, `held_gpu_counts_by_resource`) are exported from
  `domains/vms/listings` with no caller.
- **Remove the always-`None` physical-identity plumbing.** `reserved_vm_host`
  in `vm_fulfillment_service.py` is provably always `None` -- `kit/site` strips
  `vm_host` at the opaque-reservation boundary -- yet is still threaded through
  `register_lease`, `schedule_shutdown`, `provision_vm`, `_do_provision`, and
  `_register_vm_lease_with_settings`. The in-code comment records that it was
  retained only to avoid a signature change.
- **Remove the orphaned physical admin surface**:
  `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`, their
  `storefront_client.get_resource`/`patch_resource` methods, and the legacy
  local-row half of `release_reservations`. None has a production caller, and
  the documented caller of `patch_resource` -- the provisioning service's
  `LeaseWatchdog` -- no longer makes that call.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: the storefront retains no physical-resource, host,
  or physical-allocation authority; projection-backed derivation becomes the
  only listing-candidate path rather than the default one; per-pool commercial
  overrides gain an operator write path with upsert semantics.

## Non-Goals

- Do not `DROP` the frozen columns or tables. Freeze-then-redirect only.
- Do not change capacity admission, matching, scheduling, or fairness policy.
- Do not retire `compute_capacity_pools`' commercial columns (`min_price`,
  `token`, `max_duration_seconds`, `accepted_escrows`, `gpu_model`, `region`,
  `sla`, `seller_id`, the policy IDs). Commercial state is storefront-owned per
  `ARCHITECTURE.md`'s authority boundaries; this change retires physical
  authority, not per-pool rows.
- Do not build the operator path for declaring multi-dimensional capacity --
  `capacity-resource-administration` owns it and this change depends on it.
- Do not remove the implicit `"vm"` executor fallback in `deal_event_sink.py`.
  It sits adjacent to this change's surfaces but belongs to
  `market-platform-compute-40-multi-domain-proof`'s executor-identity work.
- Do not migrate the bare-metal storefront, which has no local tables at all.

## Impact

**Expanded 2026-08-06** by the Goal 1 sweep; the original entry named the
listing-derivation surfaces only.

- Affected code: `domains/vms/listings/` (`reconciler.py`, both CSV importers,
  `pool_descriptors.py`, `resources.py`),
  `domains/vms/storefront/src/market_storefront/` (`cli_publish.py`,
  `cli_portfolio.py`, `startup.py`, `controllers/admin_controller.py`,
  `services/{capacity_client,system_service,resource_capacity_validator,vm_fulfillment_service}.py`,
  `utils/{sqlite_client,migrations}.py`, `settings.toml`, `groups/config.py`,
  `scripts/import_resources_csv.py`), `core/storefront` and
  `core/storefront-client` health and admin surfaces, and seven test files.
- Affected deployment: Helm chart helpers, secrets, and values; both compose
  files; `docs/seller-quickstart.md`. This is the operator-visible half of the
  change; it needs migration guidance, not deletion alone.
- Not affected: `kit/resource-pools`, the region/SLA/pricing hint
  mechanism `pools-8` built (this change consumes it, notably for the new
  admin endpoint's SLA/pricing override tier, but does not change it),
  bare-metal (already fully projection-native, never had this local-table
  concept to begin with).

## Dependencies and Related Changes

- **Depends on `capacity-resource-administration`** (added 2026-08-06).
  Retiring CSV import removes the only operator-facing path that has ever
  expressed multi-dimensional capacity, and the provisioning service has no
  equivalent until that change lands: host inventory carries GPU columns
  only, and `capacity_inventory._project_host`'s fallback can express nothing
  else. Starting this change first would silently narrow every seller to
  GPU-count-only capacity.
- Depends on `pools-8-capacity-projection-and-listing-hints` having
  landed (`use_site_projection_for_listings` defaulting `true`, the
  region/SLA/pricing hint mechanism existing as the fallback the new admin
  endpoint's absence currently leans on).
- Coordinate with `fix-vm-fulfillment-capacity-boundary`, which removes the
  stale `vm_host`-required guard in `fulfill_vm_obligation` while this change
  removes the parameter threading around it. No ordering dependency either
  direction, but the two touch adjacent lines in the same file.
- `structured-capacity-requirements` remains the owner of requirement/claim
  vocabulary; this change introduces none.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — likely no change; `pools-8`
      already confirmed the current text's "storefront is not the source
      of truth for physical resources" principle covers this change's own
      direction. Re-confirm at implementation time rather than assuming.
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
- Whatever the direct pool-commercial-metadata admin endpoint's final
  shape turns out to be, once built — `openspec/specs/storefront-publication/spec.md`.
  **Corrected 2026-08-06:** this previously named
  `openspec/specs/resource-pool-management/spec.md`. That capability's own
  Purpose scopes it to operator-managed *provisioning* resource pools,
  provider configuration, and host membership; a storefront-side commercial
  override table is not part of it, and promoting there would place
  storefront-owned commercial state inside a provisioning capability.
- The storefront retains no physical-resource, host, or physical-allocation
  authority, and the local-table derivation path is removed outright rather
  than demoted to a non-default option —
  `openspec/specs/storefront-publication/spec.md`.
