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

## What Changes

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

## Impact

- Affected code: `domains/vms/listings/reconciler.py`,
  `domains/vms/storefront/src/market_storefront/{cli_publish.py,
  services/capacity_client.py, utils/sqlite_client.py,
  utils/migrations.py, controllers/admin_controller.py,
  services/resource_capacity_validator.py, settings.toml}`, six e2e
  scenario files.
- Not affected: `kit/resource-pools`, the region/SLA/pricing hint
  mechanism `pools-8` built (this change consumes it, notably for the new
  admin endpoint's SLA/pricing override tier, but does not change it),
  bare-metal (already fully projection-native, never had this local-table
  concept to begin with).
- Depends on `pools-8-capacity-projection-and-listing-hints` having
  landed (`use_site_projection_for_listings` defaulting `true`, the
  region/SLA/pricing hint mechanism existing as the fallback the new admin
  endpoint's absence currently leans on).

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
  shape turns out to be, once built — `openspec/specs/resource-pool-management/spec.md`,
  alongside the individual-pool admin API's other write paths.
