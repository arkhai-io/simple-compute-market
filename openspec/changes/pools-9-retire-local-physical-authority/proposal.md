## Why

The VM storefront still carries a second source of physical truth beside the
provisioning site's resource-pool projection: the local tables `resources`,
`hosts`, `compute_pool_members`, `compute_capacity_pools`, and
`resource_transition_events`, the CSV importer that fills them, and a
listing-derivation path (`_pool_rows_from_local_tables`) that reads them when
`use_site_projection_for_listings` is `false`. Projection-backed derivation is
the default and the only path the permanent contract describes for unbacked
listings, but the local path is still compiled in, still reachable by
configuration, and still the only source one deployed storefront uses.

While that path exists, "roll back" from the projection means flipping a flag,
which is exactly why it was left in place when projection-backed derivation
became the default. The cost is that every physical concept the storefront was
meant to shed — host membership, per-resource capacity, a home-site override
record with physical and commercial columns mixed in one table — stays alive,
and every operator surface that fills it (CSV import, startup seeding, Helm and
compose CSV wiring) stays a supported contract that has no site-side equivalent
and never expressed multi-dimensional capacity.

This change removes the local path and everything that exists only to feed
it. Rollback past it is a code rollback, and the change is sized so that is a
deliberate decision rather than an accident: the schema is frozen, not dropped.

## What Changes

### Retire the local-table listing path

- Delete `_pool_rows_from_local_tables` and everything downstream of it in
  `domains/vms/listings/reconciler.py`; `available_compute_slices` reads the
  projection unconditionally.
- Delete `use_site_projection_for_listings`, its readers in
  `capacity_client.py` and `listing_sources.py`, its `settings.toml` entry, and
  the `storefront.alice.toml` opt-out.
- Retire `hosts` and `compute_pool_members` entirely, `resources`' remaining
  physical and commercial columns, and `compute_capacity_pools.total_gpu_count`.
- Retire the legacy home-site override tier: `compute_capacity_pools`'
  commercial columns (`gpu_model`, `region`, `sla`, `min_price`, `token`,
  `accepted_escrows`, `settlements`, `max_duration_seconds`), their reader
  `_local_pool_pricing`, the legacy arm of `_tier()`, the
  `legacy_overrides_in_effect` derivation report, and its system-status field.
  The site-scoped override store (`kit/pool-overrides`, keyed by site, pool,
  and offering mode) is the only storefront override tier afterwards. No
  values are carried from the legacy rows into the store; an operator
  re-enters any value still in effect through `market-storefront pool-override
  set` before upgrading, guided by the system-status report that names each
  such field.
- Remove `resource_capacity_validator.py` with its only caller,
  `upsert_resource`.
- Freeze, do not drop: the migration stops creating the retired tables,
  columns, triggers, and indexes and stops writing them. A schema `DROP` is a
  later change, after a deployment cycle confirms the freeze never needed
  rolling back.

### Retire CSV import and its deployment contract

- Remove CSV import: `domains/vms/listings/host_csv_importer.py` and
  `resource_csv_importer.py`, `SQLiteClient.upsert_hosts_from_csv` and
  `upsert_resources_from_csv*`, `POST /api/v1/admin/portfolio/resources/import`,
  `storefront_client.admin_import_resources`, and `SQLiteClient.upsert_resource`
  with `_sync_compute_pool_for_resource`.
- Remove the startup seeding stack: `startup.py`'s `_seed_resources_if_empty`
  and its registered `seed_resources` step, `SystemService.seed_resources_if_empty`,
  the `_DEFAULT_CSV_PATH` constant, and the `resources_csv_path` and
  `resources_csv_inline` settings.
- **BREAKING (deployment):** retire CSV inventory as an operator contract —
  `helm/charts/storefront/templates/_helpers.tpl` (two sites), `secrets.yaml`'s
  `resourcesCsvInline`, `values.yaml`'s `--set-file` guidance,
  `compose/seller.yml`'s volume mount and `SELLER_RESOURCES_CSV`,
  `domains/vms/compose.yml`'s two mounts, and `docs/seller-quickstart.md`. An
  operator upgrading past this change must have declared inventory at the
  provisioning site first, so migration guidance is part of the change.
- Remove the CLI import surface: `market-storefront portfolio import-csv`, its
  `cli_portfolio.py` module and `add_typer` registration in `cli.py`, and
  `domains/vms/storefront/scripts/import_resources_csv.py`.
- Migrate the seven CSV-dependent test files to provisioning-seeded inventory:
  `e2e-tests/tests/e2e/roles/scenarios/vms/test_buy_oneshot_buyer_cli.py`,
  `test_compute_dynamic_listings.py`, `test_full_deal.py`,
  `test_full_deal_buyer_cli.py`, `test_multi_registry.py`,
  `test_non_erc20_settlement.py`, and `e2e-tests/tests/smoke/test_storefront_smoke.py`.
  `test_multi_registry.py`'s second storefront needs provisioning to trust its
  principal first (see Dependencies).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: the storefront retains no physical-resource, host,
  or physical-allocation authority; projection-backed derivation is the only
  listing-candidate path; the site-scoped override store is the only
  storefront override tier, so the home-site legacy record, the `inactive`
  override state, and the local-table scenarios leave the contract.

## Non-Goals

- Do not build a per-pool commercial override write path; `kit/pool-overrides`
  is that path. This change retires the tier beneath it and nothing else
  about storefront-owned commercial state.
- Do not carry legacy override values into the site-scoped store or build a
  migration command for them (`design.md` records the alternatives).
- Do not retire the storefront's zero-caller physical surfaces
  (`compute_allocations`, the resource admin routes, the always-`None` host
  plumbing, `resource_count`) — `remove-dead-storefront-physical-surfaces`.
- Do not fix a Resource Pool's provider at creation —
  `fix-resource-pool-provider-at-creation`.
- Do not migrate the bare-metal storefront, which has no local tables.

## Impact

- Code: `domains/vms/listings/` (`reconciler.py`, both CSV importers,
  `pool_descriptors.py`, `resources.py`);
  `domains/vms/storefront/src/market_storefront/` (`cli_portfolio.py`, `cli.py`,
  `startup.py`, `controllers/admin_controller.py`,
  `services/{capacity_client,listing_sources,system_service,resource_capacity_validator}.py`,
  `utils/{sqlite_client,migrations}.py`, `settings.toml`, `groups/config.py`);
  `domains/vms/storefront/storefront.alice.toml`;
  `domains/vms/storefront/scripts/import_resources_csv.py`; the import surfaces
  of `core/storefront` and `core/storefront-client`; seven test files.
- Deployment: Helm, compose, and the seller quickstart lose the CSV contract.
- Not affected: `kit/resource-pools`, `kit/pool-overrides` (the store stays;
  the tier beneath it goes), the region/SLA/pricing hint mechanism, bare metal.
- Behaviour after upgrade: a home-site pool that took a commercial field from
  the legacy record resolves it from the pool hint, then the configured
  default; `region` has no legacy fallback and must be declared on the pool
  hint; `accepted_escrows` has no equivalent other than a `settlements` clause
  list.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary"
      describes projection-backed derivation as the only path.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`
      and its architecture companion.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The storefront holds no physical-resource, host, or physical-allocation
  authority, and derives every listing candidate from the site projection —
  `openspec/specs/storefront-publication/spec.md`.
- The site-scoped override store is the only storefront override tier; no
  pool-keyed legacy record exists beneath it and no `inactive` override state
  exists — `openspec/specs/storefront-publication/spec.md`, "Storefront pool
  overrides are the only override tier" (replacing "Storefront pool overrides
  are site-scoped and durable").
- Rollback past the retirement is a code rollback, not a configuration flip —
  operator deployment documentation.
- Why legacy values are not carried over, and why the schema is frozen rather
  than dropped — this change's `design.md`.

## Dependencies and Related Changes

- Depends on `repair-multi-storefront-scenario`. The two-storefront e2e
  scenario's second storefront derives from local tables because provisioning
  trusts one storefront principal and it can load no projection; the cutover
  and the migration of `test_multi_registry.py` wait on provisioning trusting
  a second principal. The freeze and the CSV code removal do not.
- Depends on `capacity-resource-administration` (archived): multi-dimensional
  capacity is declarable at the site, so the CSV path is not the only
  expression of it.
- Depends on `pools-8-capacity-projection-and-listing-hints` and
  `publish-multidimensional-listing-shape` (archived): the projection default,
  the hint mechanism, and the site-scoped override store this change makes
  the only tier.
- Independent of `remove-dead-storefront-physical-surfaces` and
  `fix-resource-pool-provider-at-creation`; either order. This change's
  freeze migration covers `compute_allocations` if the former has not landed
  first.
- The start trigger for the cutover is a repository-owner decision. Sellers
  self-host, so no fleet-wide rollout signal exists to gate it on.
