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
  `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`, including the
  local-only helpers `_capacity_pool_member_rows`,
  `_accumulate_capacity_pool_member`, and `_local_table_shapes`. Every
  derivation entry point (`available_compute_slices`,
  `current_available_resource_keys`, `stale_open_listing_ids`,
  `closed_available_listing_ids`, and the storefront wrappers that forward
  them) takes the projection as a required argument; `None` no longer selects
  a source.
- Delete `use_site_projection_for_listings`, its readers
  (`listing_source_projection()` in `capacity_client.py`, which returns `None`
  to select the local path for all seven of its callers, and
  `_projection_enabled()` in `listing_sources.py`), its `settings.toml` entry,
  and the tests that set it. Alice's `storefront.alice.toml` opt-out was
  already removed by the multi-storefront repair.
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
  columns, triggers, and indexes on fresh databases. Upgraded databases retain
  existing schema and rows unchanged as inert rollback data or an operator
  source for seeding provisioning. Current storefront code neither reads nor
  writes them. Retained data is historical and must be reconciled against live
  site state before reuse; no automatic transfer or overwrite is added.
  A schema `DROP` is a
  later change, after a deployment cycle confirms the freeze never needed
  rolling back.

### Retire CSV import and its deployment contract

- Remove CSV import: `domains/vms/listings/src/arkhai_vms_listings/host_csv_importer.py`
  and `resource_csv_importer.py`, `SQLiteClient.upsert_hosts_from_csv` and
  `upsert_resources_from_csv*`, `POST /api/v1/admin/portfolio/resources/import`
  with its administrator route contract and multipart signing descriptor in
  `middleware/admin_identity.py`, both `ImportResourcesResponse` models
  (storefront and `core/storefront-client`), both client variants'
  `admin_import_resources`, and `SQLiteClient.upsert_resource` with
  `_sync_compute_pool_for_resource`.
- Remove the startup seeding stack: `startup.py`'s `_seed_resources_if_empty`
  and its registered `seed_resources` step, `SystemService.seed_resources_if_empty`,
  the `_DEFAULT_CSV_PATH` constant, and the `resources_csv_path` and
  `resources_csv_inline` settings.
- **BREAKING (deployment):** retire CSV inventory as an operator contract —
  `helm/charts/storefront/templates/_helpers.tpl`'s `resources_csv_inline`
  rendering, `secrets.yaml`'s `resourcesCsvInline`, `values.yaml`'s
  `resourcesCsvInline` guidance and `resources_csv_path` config entry,
  `helm/Makefile`'s `RESOURCES_CSV_FILE` `--set-file` wiring,
  `helm/fixtures/eip191-evm-values.yaml`'s `resources_csv_path`,
  `compose/seller.yml`'s volume mount and `SELLER_RESOURCES_CSV`,
  `domains/vms/compose.yml`'s two mounts (Bob's and Alice's),
  `resources_csv_path` in `storefront.alice.toml` and `storefront.bob.toml`,
  `domains/vms/storefront/Makefile`'s `RESOURCES_CSV_FILE` mounts, the bundled
  inventory CSVs under `market_storefront/data/` with
  `test_bundled_inventory.py`, and `docs/seller-quickstart.md`. An operator
  upgrading past this change must have declared inventory at the provisioning
  site first, so migration guidance is part of the change.
- Remove the CLI import surface: `market-storefront portfolio import-csv`, its
  `cli_portfolio.py` module and `add_typer` registration in `cli.py`, and
  `domains/vms/storefront/scripts/import_resources_csv.py`.
- Migrate the six CSV-dependent test files to provisioning-seeded inventory:
  `e2e-tests/tests/e2e/roles/scenarios/vms/test_buy_oneshot_buyer_cli.py`,
  `test_compute_dynamic_listings.py`, `test_full_deal.py`,
  `test_full_deal_buyer_cli.py`, `test_non_erc20_settlement.py`, and
  `e2e-tests/tests/smoke/test_storefront_smoke.py`. The multi-storefront repair
  already moved `test_multi_registry.py` to provisioning seeding.
  `test_compute_dynamic_listings.py` imports rows whose pool identifiers match
  its projected pools, so the legacy tier currently supplies those pools' SLA
  and region; its migration declares them on the pool hint or a site-scoped
  override instead.

### Retire diagnostics and cleanup that depend on local inventory

- Remove the local-row normalization half of `release_reservations` when the
  local listing path retires; retain the authoritative site-ledger release
  operation. Correct its operator description for the resulting behavior.
- **BREAKING (status):** replace top-level `resource_count` with
  `site_projections[site_id][family].resource_count` when CSV inventory retires.
  Count projected resource-pool members and sum the capacity groups' existing
  counts, separately per site and family. Report zero for a held empty
  generation, `null` when none is held, and the retained count with stale state
  after refresh failure. No site projection protocol change is needed.
  Reconcile both health models, the operator acceptance requirement and its
  Evidence entry, smoke and full-deal assertions, the seller quickstart, and
  the validation runbook. Publication diagnostics and catalogue checks prove
  sellable supply separately from inventory presence.
- These two removals were transferred from
  `remove-dead-storefront-physical-surfaces` during its design review. The
  replacement operator diagnostic is now resolved in `design.md` as counts
  attached to each site's independently versioned projection families.

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
  plumbing) — `remove-dead-storefront-physical-surfaces`.
- Do not fix a Resource Pool's provider at creation —
  `fix-resource-pool-provider-at-creation`.
- Do not migrate the bare-metal storefront, which has no local tables.
- Do not change projection protocols or the listing-creation paths as part of
  replacing the inventory diagnostic. Preserve independent physical-resource
  counts for pools that do not use capacity buckets, and the per-site,
  per-family structure for any further projection family.

## Impact

- Code: `domains/vms/listings/src/arkhai_vms_listings/` (`reconciler.py`, both
  CSV importers, `pool_descriptors.py`, `pricing_resolution.py`, `resources.py`,
  `__init__.py`);
  `domains/vms/storefront/src/market_storefront/` (`cli_portfolio.py`, `cli.py`,
  `startup.py`, `failure_actions.py`, `server.py`,
  `controllers/admin_controller.py`, `middleware/admin_identity.py`,
  `models/{capacity_admin_models,system_status_models}.py`,
  `services/{capacity_client,listing_sources,listing_source_check,publication_loop,publication_service,system_service,site_projection_cache,resource_capacity_validator,vm_pool_override_contribution}.py`,
  `utils/{sqlite_client,migrations}.py`, `settings.toml`, `groups/config.py`);
  `domains/vms/storefront/storefront.{alice,bob}.toml`;
  `domains/vms/storefront/scripts/import_resources_csv.py`;
  `kit/pool-overrides`, which defines the `inactive` override state and a
  projection source that may be `None`; the status and import surfaces of
  `core/storefront` and `core/storefront-client`; six e2e/smoke test files
  plus the storefront unit and integration tests of the retired surfaces;
  `scripts/tests/test_multi_storefront_compose.py`;
  `docs/development/VALIDATION_RUNBOOK.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Deployment: Helm, compose, both seller TOMLs, the storefront and Helm
  Makefiles, and the seller quickstart lose the CSV contract.
- Not affected: `kit/resource-pools`, the pool-override store, routes, clients,
  and CLI (only the `inactive` state leaves `kit/pool-overrides`), the
  region/SLA/pricing hint mechanism, bare-metal publication. Bare metal shares
  the status models and typed client this change edits, so its status output
  is checked for regressions.
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
- Fresh databases omit retired physical schema; upgraded databases preserve
  inert history for rollback or operator provisioning seeding, without current
  storefront reads or writes — `openspec/specs/storefront-publication/spec.md`
  and its architecture companion. Safe reuse requires checking live site state
  — operator deployment documentation and `docs/seller-quickstart.md`.
- The site-scoped override store is the only storefront override tier; no
  pool-keyed legacy record exists beneath it and no `inactive` override state
  exists — `openspec/specs/storefront-publication/spec.md`, "Storefront pool
  overrides are the only override tier" (replacing "Storefront pool overrides
  are site-scoped and durable").
- Rollback past the retirement is a code rollback, not a configuration flip —
  operator deployment documentation.
- Why legacy values are not carried over, and why the schema is frozen rather
  than dropped — this change's `design.md`.
- Per-site, per-family counts describe the cached projection generation;
  inventory presence, freshness, and publication feasibility are separate
  observations — `openspec/specs/storefront-publication/spec.md` and its
  architecture companion, with operational interpretation in the
  quickstart/runbook.

## Dependencies and Related Changes

- Depends on `repair-multi-storefront-scenario` (archived 2026-10-01). Alice
  has her own provisioning authority and projection-backed listings, her
  local-path opt-out is gone, and `test_multi_registry.py` seeds through
  provisioning. Multiple storefronts per site remain out of scope. The local
  path, CSV contract, startup seeding, schema freeze, and local diagnostic
  retirement land together as one coordinated cutover; none of those removals
  is an independently deployable precursor.
- Depends on `remove-dead-storefront-physical-surfaces`, which lands first. Its
  surfaces read the tables this change stops creating: the resource
  `GET`/`PATCH` routes reach `get_resource` and `apply_resource_transition`,
  `list_hosts` and `host_capacity_remaining` read `hosts`, and migration
  `20260604_002` builds indexes on `compute_allocations`. Landing this change
  first would leave those surfaces failing on fresh databases. With that change
  landed, `compute_allocations` is already frozen and this change's freeze
  covers only the local inventory tables.
- Depends on `capacity-resource-administration` (archived): multi-dimensional
  capacity is declarable at the site, so the CSV path is not the only
  expression of it.
- Depends on `pools-8-capacity-projection-and-listing-hints` and
  `publish-multidimensional-listing-shape` (archived): the projection default,
  the hint mechanism, and the site-scoped override store this change makes
  the only tier.
- Independent of `fix-resource-pool-provider-at-creation`; either order.
- The repository work order is the multi-storefront repair (done), then
  `remove-dead-storefront-physical-surfaces`, then this retirement. Design and
  planning proceed before the zero-caller removal lands. Sellers
  self-host and choose deployment timing after preparing authoritative site
  inventory and commercial overrides; no fleet-wide rollout signal gates it.
