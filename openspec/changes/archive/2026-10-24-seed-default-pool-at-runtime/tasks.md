# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/24-design.triage.md`. Every implementation task answers to a decision
D1–D8, a delta requirement under `specs/`, or a repository obligation cited at
the task: `openspec/README.md#plan-closeout-requirements`, the task rules in
`openspec/config.yaml`, `docs/development/TESTING.md`'s level definitions, and
`docs/development/BUILD_AND_PACKAGING.md`.

Test levels follow `docs/development/TESTING.md`: unit; library integration (a
kit's service API against a real database); persistence integration (the
provisioning service's own migrations and startup steps against file-backed
SQLite, in its `tests/integration`, without the app); application integration
(the in-process app through its typed clients); and system (the `e2e-tests`
markers).

Order: 1 → 9, then the closeout, 10. Sections 1–3 deliver the service playbooks
(D5); sections 4–9 deliver hosts, pools, and seeding (D1–D4, D6, D7). Section 8's
seed document needs section 2's optional VM playbook and section 4's removal of
the `default` document rule. No dependency gates implementation. Permanent
documentation is written only at closeout.

Closeout compressed the section notes to final behaviour, evidence, deferrals,
and destinations; plan corrections, declined review items, and limitations moved
to `design.md`'s "Implementation findings". Review rounds 37, 60, and 67 and
their triage records hold the round-by-round detail.

## 1. Domain-named playbook settings

Delivers `vm_playbook_path` beside `bare_metal_playbook_path`, with no alias and
the retired `playbook_path` refused at startup and in the chart (D5; delta
"A domain's service playbook setting is named for its domain").

Files: `provisioning/compute/service/src/compute_provisioning_service/{config.py,
settings.toml,app_runtime.py,db/migrate.py}`; its `config/{config.yml,
config-docker.yml,config-mock.yml,config-local.yml.example}`;
`provisioning/compute/service/Makefile`;
`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/runtime.py`;
`helm/charts/provisioning/{values.yaml,values.schema.json,tests/test_render.py}`;
tests and fixtures naming `playbook_path` or `resolved_playbook_path`. The
quickstarts' mentions of the setting are promotion work (10.9).

- [x] 1.1 Rename the setting `playbook_path` to `vm_playbook_path` in
  `settings.toml`, every `config/*.yml` profile, and the service `Makefile`
  (`PROVISIONING_PLAYBOOK_PATH` becomes `PROVISIONING_VM_PLAYBOOK_PATH`); rename
  `Settings.resolved_playbook_path` to `resolved_vm_playbook_path` and update its
  readers, the VM runtime's executor construction (`runtime.py:77`) and
  `db/migrate.py` (D5). Verify with the service's unit `test_config.py` that
  `resolved_vm_playbook_path` resolves the configured value, and that no source,
  test, or fixture still reads `playbook_path` as a setting (a repository search
  for `resolved_playbook_path` and `settings.playbook_path` finds nothing).
  Done in every profile, the `Makefile`'s `serve` target, and both integration
  harnesses' settings. Unit (`test_config.py`): a relative value and the
  packaged default resolve. The search finds only pool-level
  `provider_config.playbook_path` reads and the refusal tests.
- [x] 1.2 Refuse the retired key (D5). Add a check in `config.py` that names every
  retired setting present — `playbook_path`, replaced by `vm_playbook_path` — and
  a first startup step in `app_runtime.startup_steps()` that raises with that
  message before any other step. Unit: `test_config.py` covers the key set in a
  profile and through the `PROVISIONING_` environment layer, and its absence.
  Application integration: the service's startup sequence, run as the
  integration suite composes it, fails naming `vm_playbook_path` when the retired
  key is set.
  Done: `config.RETIRED_SETTINGS`, `Settings.stated_retired_settings()` (any
  layer, through Dynaconf's `exists`), and `RetiredSettingsError`; the step
  `refuse-retired-settings` runs first. Unit (`test_config.py`,
  `test_worker.py`); application integration
  (`test_retired_settings_startup.py`, running the app's own lifespan, since the
  harness never does). Correction (section 7): `compute-provisioning-migrate`
  no longer refuses the key, since it reads no configuration (D6);
  `test_migration_reads_no_configuration.py` shows it migrates with the key set.
- [x] 1.3 Rename the chart's `config.playbook_path` value to `vm_playbook_path`
  in `helm/charts/provisioning/values.yaml` and make `values.schema.json` refuse
  `config.playbook_path`, as it refuses `pool_definitions_path` (D5). Extend
  `helm/charts/provisioning/tests/test_render.py`: the rendered profile carries
  `vm_playbook_path`, and a values file setting `config.playbook_path` fails
  schema validation. Run `make -C helm test-render`.
  Done; `make -C helm test-render` passed with both checks.
- [x] 1.4 **Verification checkpoint.** Unit: service `test_config.py` and the
  startup-step test. Application integration: the startup refusal of 1.2. Chart
  render: `make -C helm test-render`. Run `make test` in
  `provisioning/compute/service` and `domains/vms/provisioning/adapter`, and
  `make check-comment-hygiene`.
  End-to-end: every VM lane scenario (`e2e_deal`, `e2e_deal_buyer_cli`,
  `e2e_buy`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
  `multi_registry`, `e2e_vm_introduction`) boots provisioning on the renamed
  setting; none proves the refusal, which unit and application integration own.
  No scenario is owed.
  Owed by validation: `tests.yml`, job `release · deployment contracts` — `make
  -C helm test-render` passes with the renamed value and the refused key.
  Evidence: the service (unit 667, integration 487), the VM adapter (29), chart
  render, repository `make test`, `make check-comment-hygiene`, and `make
  check-change` passed.

## 2. Optional VM pool playbook, frozen at preparation

Delivers a VM pool whose `playbook_path` may be omitted, the service's
`vm_playbook_path` frozen into a VM job's parameters when the pool states none,
and the `ansible_pool_configs` rebuild (D5, D6's `inventory_group` drop; delta
"Ansible fulfillment adapter").

Files: `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/{db.py,
runtime.py,services/ansible_pool_config_handler.py,
services/vm_fulfillment_plan.py,models/fulfillment_model.py}`;
`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`;
tests in `domains/vms/provisioning/adapter/tests/unit/test_vm_fulfillment_plan.py`
and `provisioning/compute/service/tests/integration/{test_ansible_pool_config_handler.py,
test_pools_api.py}`, and a new migration test module beside them.

- [x] 2.1 Make `AnsiblePoolConfig.playbook_path` nullable and remove
  `inventory_group` from the model; the handler accepts an omitted or null
  `playbook_path`, stores NULL for it, returns it from `read_config`, and stops
  writing the `__unused__` placeholder and its comment (D5, D6). Make the VM
  fulfillment model's `playbook_path` optional (`models/fulfillment_model.py:67`).
  Library integration: `test_ansible_pool_config_handler.py` covers an omitted
  playbook stored and read as null, a stated one unchanged, and a blank string
  still refused.
  Done. A stated playbook that names nothing is refused as `invalid_type`;
  `inventory_group` is an unknown field. Library integration as planned.
- [x] 2.2 Freeze the service's playbook at preparation (D5). `VmFulfillmentPlan`
  takes the configured `vm_playbook_path` from its runtime (`runtime.py`'s
  `fulfillment_plan()`), and `prepare_create` and `prepare_teardown` write the
  pool's `playbook_path` when it states one and that configured path otherwise.
  Unit: `test_vm_fulfillment_plan.py` covers both, for create and teardown, and a
  prepared job's parameters keeping the frozen path after the plan's configured
  path changes.
  Done. `vm_playbook_path` is a required keyword that may be `None`; with
  neither playbook, preparation is refused naming `vm_playbook_path`. The legacy
  lease conversion's plan passes `None`, since a historical pool always states
  its playbook. Unit as planned, plus refusal and the runtime's wiring.
- [x] 2.3 Append a migration after `20261019_001_vm_provider_identity` that
  rebuilds `ansible_pool_configs` from the model with `playbook_path` nullable
  and `inventory_group` dropped, following `_migrate_capacity_declaration_contract`
  (foreign keys off, temporary table from the model, copy shared columns, drop,
  rename, `foreign_key_check`, one transaction), and is a no-op on a table already
  in that shape (D6, design "Migration Plan"). Remove `inventory_group` from the
  config row `20260713_002` writes, so a fresh database migrates; that seed is
  removed entirely in section 7. Persistence integration: a new
  `test_vm_pool_config_migration.py` over file-backed SQLite covers existing rows
  keeping every value, the relaxed column, the dropped column, a fresh database,
  and a repeated run. The legacy lease conversion `20260724_001` still selects
  `inventory_group`, which only a legacy schema holds at that point in the chain;
  a legacy-migration test that builds `ansible_pool_configs` from the current
  model adds the column its legacy schema had, and the legacy migration suites
  (`test_legacy_vm_lease_migration.py`, `test_legacy_backfill_teardown.py`,
  `test_fulfillment_convergence_after_legacy_backfill.py`) pass.
  Done as `20261023_001_vm_pool_playbook_optional`. Correction to the premise:
  `20260724_001` reads `inventory_group` only where the column exists (see
  `design.md`, "Implementation findings"). Persistence integration
  (`test_vm_pool_config_migration.py`): a database at
  `schema_through_20260911_001.sql` is rebuilt keeping every value, index, and
  foreign key; a fresh database and a repeated run are untouched. The legacy
  suites and `test_database.py`'s legacy chain pre-create the configuration they
  need.
- [x] 2.4 Application integration through the typed pool client
  (`test_pools_api.py`): a `vm.ansible` pool created with `provider_config: {}`
  is accepted, and its export shows `playbook_path: null`; a fulfillment accepted
  for it carries the service's configured playbook in its job parameters
  (`test_fulfillment_api.py`, extended).
  Done (`TestPlaybookLeftToTheService`; `test_fulfillment_api.py` reads the
  dispatched job's stored parameters). The harness builds its own plan, so the
  runtime's wiring is 2.2's unit test's.
- [x] 2.5 **Verification checkpoint.** Unit `test_vm_fulfillment_plan.py`;
  library integration `test_ansible_pool_config_handler.py`; service integration
  `test_vm_pool_config_migration.py`; application integration 2.4. Run `make
  test` in `domains/vms/provisioning/adapter` and `provisioning/compute/service`,
  and `make check-comment-hygiene`.
  End-to-end: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, and
  `e2e_compute_dynamic_listings` dispatch VM jobs under the mock profile, where
  the playbook path is not run, so they prove dispatch still succeeds but not
  which playbook was frozen; unit and application integration own that. No
  scenario is owed.
  Evidence: the VM adapter (37), the service (unit 667, integration 501),
  repository `make test`, and `make check-change` passed. No chart change, so no
  `Owed by validation:` line.

## 3. Bare-metal playbook frozen at preparation

Delivers the bare-metal grant and reclaim carrying `bare_metal_playbook_path` as
configured when each is prepared (D5; delta "Bare-metal inventory binds an
existing provider pool").

Files: `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/{codec.py,
runtime.py,services/bare_metal_fulfillment_plan.py}`; tests
`domains/bare_metal/provisioning/adapter/tests/{test_bare_metal_fulfillment_plan.py,
test_bare_metal_codec.py,test_bare_metal_mock_output.py}`.

- [x] 3.1 `BareMetalJobParams` gains `playbook_path: str | None = None`;
  `BareMetalFulfillmentPlan` takes `playbook_path` beside `reclaim_policy`, writes
  it into every grant in `prepare_create` and into every reclaim through
  `prepare_teardown`'s `model_copy` update; the runtime passes
  `config.resolved_bare_metal_playbook_path` to the plan as well as the executor;
  `BareMetalAnsibleCodec.prepare` passes the parameters' playbook to
  `AnsibleJobPlan` (D5). Unit: `test_bare_metal_fulfillment_plan.py` covers grant
  and reclaim parameters carrying the configured path and a reclaim of a grant
  stored without it gaining the current one; `test_bare_metal_codec.py` covers a
  plan carrying the stored path and parameters without one validating and
  yielding none, so the executor's configured playbook runs.
  Done. The plan's `playbook_path` is a required keyword. Unit as planned, plus
  a reconfigured plan's reclaim and the runtime's wiring under the mock profile.
- [x] 3.2 Check every bare-metal mock rule and fixture that matches job
  parameters (`test_bare_metal_mock_output.py`, the service's
  `test_bare_metal_mock_profile.py`, and e2e bare-metal mock rules) and update
  any that matches an exact parameter set to admit the new field (D5). Evidence:
  the suites pass unchanged in intent.
  Checked: a mock rule matches on the keys it names, so none matches an exact
  parameter set and none changed; all pass.
- [x] 3.3 **Verification checkpoint.** Unit: the two bare-metal suites above.
  Application integration: `test_bare_metal_mock_profile.py` (service) runs a
  grant and reclaim through the composed service and its stored job parameters
  carry the configured playbook. Run `make test` in
  `domains/bare_metal/provisioning/adapter` and `provisioning/compute/service`,
  and `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_mock_deal` and `e2e_bare_metal_deal` run grants
  and reclaims; they prove dispatch, not which playbook was frozen. No scenario
  is owed.
  Evidence: the application-integration case above; the bare-metal adapter
  (46), the service (unit 667, integration 501), repository `make test`, and
  `make check-change` passed. `e2e_bare_metal_deal` needs a real host and no
  lane selects it. No chart change.

## 4. `default` is an ordinary pool in the kits

Delivers pool documents that need not name `default`, and `kit/site` reading no
declaration without a pool as `default` (D3; deltas "Strict lossless YAML
validation", "Non-destructive pool lifecycle", "Operator-administered capacity
declarations").

Files: `kit/resource-pools/src/market_resource_pools/service.py` and its tests;
`kit/site/src/market_site/ledger.py` and its tests;
`provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py`.

- [x] 4.1 Remove the `missing_default_pool` check from document validation
  (`service.py:616-623`) (D3). Library integration
  (`kit/resource-pools/tests/integration/test_resource_pool_service.py`):
  `test_missing_default_pool_rejected` becomes a document without `default`
  validating and importing; the disabled-`default` tests stay.
  Done; `make -C kit/resource-pools test` — 124 passed.
- [x] 4.2 Remove every `pool_id or DEFAULT_POOL_ID` read from `kit/site`'s ledger
  (`ledger.py:871, 933, 1002, 1222-1229, 1317, 2251, 2307`) and from
  `capacity_inventory.py:59-61`; a stored declaration with no pool is excluded
  from projection, admission, and pool moves, and is logged rather than read as
  any pool (D3). `DEFAULT_POOL_ID` stays exported. Library integration
  (`kit/site/tests/integration/test_ledger.py`) and unit
  (`provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`)
  cover a row stored with a NULL pool: absent from the projection, not admitted,
  and not reported as `default`.
  Done, and beyond the plan in scheduling candidates, both projections, and the
  injected exact matcher (see `design.md`, "Implementation findings"). Admission
  skips a pool-less row before claim matching; assignment to one is refused;
  naming a pool for it is a move. Library integration (`test_ledger.py`) and
  unit (`test_projections.py`, `test_dict_resource_satisfies_claim.py`,
  `test_capacity_inventory.py`) as planned. The VM storefront's `fake_site.py`
  and `kit/fulfillment`'s `test_resource_without_pool_is_not_schedulable` were
  updated for rows a site no longer produces.
- [x] 4.3 **Verification checkpoint.** The suites of 4.1 and 4.2. Application
  integration: `test_pools_api.py` imports a document naming no `default`
  through the typed client and disables a pool named `default`. Run `make test`
  in `kit/resource-pools`, `kit/site`, and `provisioning/compute/service`, `make
  check-packaging`, and `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_publication` and `e2e_bare_metal_introduction`
  import the bare-metal development document; none exercises a document without
  `default`. No scenario is owed.
  Evidence: application integration as planned; `kit/resource-pools` 124,
  `kit/site` 289, `kit/fulfillment` 171, the VM storefront (unit 1103,
  integration 448), the service (unit 667, integration 502), `make
  check-packaging`, `make check-comment-hygiene`, and `make check-change`
  passed. No chart change.

## 5. A host's pool is optional

Delivers unplaced hosts on every host write path, explicit-`null` and empty-INI
unplacing through the pool-change hooks, and absent INI keys leaving a host's
pool unchanged (D1; delta "Explicit valid host membership").

Files: `provisioning/compute/contracts/src/compute_provisioning_contracts/hosts.py`;
`provisioning/compute/client/src/compute_provisioning_client/{client.py,base.py}`;
`provisioning/compute/src/compute_provisioning/hosts/{db.py,service.py,route_service.py}`;
`provisioning/compute/ansible/src/compute_provisioning_ansible/{inventory.py,host_import.py}`;
`provisioning/compute/service/src/compute_provisioning_service/app_runtime.py`
(inventory seeding); tests in `provisioning/compute/tests/unit`,
`provisioning/compute/ansible/tests/unit/test_inventory.py`, and the service's
`test_hosts_api.py` and `test_host_pool_moves_api.py`.

- [x] 5.1 Contracts and client (D1): `HostResponse.pool_id` becomes `str | None`;
  `HostCreate`'s description says an omitted pool leaves the host unplaced;
  `HostUpdate` keeps `pool_id: Optional[str]`, and the route service tells an
  explicit `null` from an omitted field by the fields the request set. The typed
  client's host update sends the fields the caller set, an explicit `null`
  included (`exclude_unset` for `HostUpdate`), while every other body keeps the
  shared `exclude_none` serialization. Unit (`provisioning/compute/tests/unit`):
  the serialized update body carries `"pool_id": null` only when set.
  Done; the authority, not the route service, reads the model's fields-set.
  Unit in `provisioning/compute/client/tests/unit/test_client.py`, where the
  client's tests live.
- [x] 5.2 Host authority (D1): `Host.pool_id` becomes nullable with no default or
  server default; `register_host` stores the named pool or none;
  `_move_to_pool` accepts `None`, runs the pool-change hooks for unplacing as for
  any move, and checks existence only for a named pool; `InventoryHost.pool_id`
  carries three states (a pool, unplace, unstated), and `apply_inventory` moves
  an existing host only when its entry states a pool or unplaces it, creating a
  new host unplaced when its entry is unstated.
  Done; unstated is the exported sentinel `POOL_UNSTATED`, and `PoolChangeHook`
  takes optional pools. Library integration (`test_host_authority.py`): every
  state, hook-run unplacing, and a refusal leaving the whole import unapplied.
- [x] 5.3 INI parser (D1): `parse_inventory_ini` maps a non-empty `pool_id=` to a
  pool, an empty `pool_id=` to unplace, and an absent key to unstated, and its
  docstring no longer names a default pool. Unit (`test_inventory.py`): all three
  forms.
  Done. The package no longer imports `market_resource_pools`, so
  `arkhai-kit-resource-pools` left its dependencies, four locks, and
  `docs/development/RELEASING.md`'s row.
- [x] 5.4 Application integration through the typed client (`test_hosts_api.py`,
  `test_host_pool_moves_api.py`): a host created without a pool reads back
  `pool_id: null`; an update omitting the pool keeps it; an explicit `null`
  unplaces it; an import with an empty `pool_id=` unplaces an existing host; an
  import with no `pool_id` keeps an existing host's pool and leaves a new host
  unplaced; a VM relay hook refusing an unplacing rolls back the whole import;
  an unknown pool is still refused.
  Done (`TestHostPlacement`; the relay-hook refusal is a 409 rolling back a new
  host applied before it). `test_pools_api.py` shows a host registered with no
  pool in none.
- [x] 5.5 **Verification checkpoint.** Unit: contracts/client serialization and
  `test_inventory.py`. Application integration: 5.4. Run `make test` in
  `provisioning/compute/contracts`, `provisioning/compute/client`,
  `provisioning/compute`, `provisioning/compute/ansible`, and
  `provisioning/compute/service`; `make check-packaging`; `make
  check-comment-hygiene`.
  End-to-end: the VM and bare-metal scenarios register hosts into named pools
  (`e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`), so they prove the
  named path still places; none registers an unplaced host. No scenario is owed:
  placement is one authority's transaction, which application integration owns.
  Evidence: contracts 59, client 58, `provisioning/compute` 235, `ansible` 93,
  the service (unit 667, integration 511), repository `make test`, `make lock`,
  `make check-packaging`, and `make check-change` passed. Correction: the VM
  scenarios' fixture registers `kvm1` with no pool, so they do exercise an
  unplaced host's lookup. Version bumps for the incompatible interface changes
  are deferred to the release (see `design.md`, "Implementation findings"). No
  chart change.

## 6. Host writes declare no capacity, and the hosts rebuild

Delivers the removal of capacity derivation from every host write and the
`hosts` table rebuild for existing databases (D1, D2; delta "Host writes declare
no capacity").

Files: `provisioning/compute/service/src/compute_provisioning_service/services/capacity_derivation.py`
(removed), `container.py`, `db/migrations.py`;
`provisioning/compute/src/compute_provisioning/hosts/service.py` (the derivation
port); tests `provisioning/compute/service/tests/integration/{test_host_capacity_derivation_api.py,
test_capacity_api.py}`, `tests/unit/services/test_capacity_derivation.py`
(removed), and a new hosts migration test.

- [x] 6.1 Remove the `HostCapacityDerivation` port from the host authority and
  `apply_inventory`'s derivation call and serialization, `services/capacity_derivation.py`,
  its container wiring, and `test_capacity_derivation.py` (D2). The upgrade
  migration `20260921_004` keeps its own SQL and is not touched. Application
  integration: `test_host_capacity_derivation_api.py` becomes the proof that an
  INI import and a startup seed carrying `gpus=` create no capacity declaration,
  so the capacity projection holds no entry for those hosts; the derivation
  cases in `test_capacity_api.py` assert the same.
  Done; `apply_inventory` no longer takes the ledger's serialization lock, which
  it held only for derivation. Application integration, renamed
  `test_host_writes_declare_no_capacity_api.py`: an INI import, placed and
  unplaced, the startup seed, and host API create and update declare nothing,
  and an operator's declaration survives a re-import;
  `test_capacity_api.py` projects only an explicit declaration.
- [x] 6.2 Append a migration after section 2's that rebuilds `hosts` from the
  model with `pool_id` nullable and no default, following
  `_migrate_capacity_declaration_contract`, and is a no-op on a table already in
  that shape (D1, design "Migration Plan"). Persistence integration: a new
  `test_host_pool_optional_migration.py` covers existing hosts keeping their
  pools and every other column, a fresh database, a repeated run, and
  `foreign_key_check` passing.
  Done as `20261023_002_hosts_pool_optional`. Persistence integration as
  planned, comparing every column of every row, a protected key's ciphertext
  included.
- [x] 6.3 **Verification checkpoint.** Application integration 6.1; service
  integration 6.2. Run `make test` in `provisioning/compute` and
  `provisioning/compute/service`, `make check-packaging`, and `make
  check-comment-hygiene`.
  End-to-end: every VM and bare-metal scenario declares capacity explicitly, so
  the lanes prove nothing depended on derivation. No scenario is owed.
  Evidence: `provisioning/compute` 235, the service (unit 653, integration 515),
  `make test-e2e-unit` 38, repository `make test`, `make check-packaging`, and
  `make check-change` passed. The rebuild's dependence on the current model is
  recorded in `design.md`, "Implementation findings". No chart change.

## 7. Migration reads no operational configuration

Delivers migration entrypoints that take only the engine, `20260713_002` seeding
nothing, the job-envelope migration reading only physical-host evidence, and the
retired settings (D6; delta "Service-owned migration history", and "Explicit
valid host membership"'s scenario "Existing schema is migrated").

Files: `provisioning/compute/service/src/compute_provisioning_service/db/{database.py,
migrate.py,migrations.py}`, `settings.toml`; `helm/values.yaml`,
`helm/charts/provisioning/values.yaml`; fixtures
`provisioning/compute/service/tests/{unit,integration}/conftest.py` and
`tests/integration/test_test_controller.py`; tests
`test_database.py`, `test_pool_declaration_startup.py`,
`test_job_envelope_migration.py`, and every test calling `run_migrations` or
`apply_schema_migrations` with keyword inputs.

- [x] 7.1 `run_migrations(engine)` and `apply_schema_migrations(engine)` take only
  the engine; remove their configuration parameters, `seed_default_pool`,
  `_has_existing_pool_or_host_state`, and the special dispatch for
  `20260713_002` and `20261002_002`; `migrate.py` passes only the engine (D6).
  Update every test calling them with keyword inputs.
  Done; every migration is dispatched as `migration.apply(engine)`, and
  `migrate.main()` reads only `database_url` and `log_level`.
- [x] 7.2 `20260713_002` creates its tables and its column only: it writes no
  pool row and no configuration row, and raises an actionable `SchemaDriftError`
  when hosts exist and no `default` pool does (D6). Rewrite its docstring and
  the comments describing the seed. Persistence integration (`test_database.py`):
  a fresh database, with or without a pool document configured, holds no pool
  after migration; a pre-pool database with hosts is refused; tests that relied
  on the seeded `default` create the pool they need. A legacy-chain test whose
  fixture holds hosts from before resource pools inserts the `default` pool and
  configuration rows the retired seed wrote, so it still exercises the later
  migrations it was written for.
  Done. The refusal runs before this migration touches a table, after earlier
  migrations and `run_migrations`' table creation, which stay recorded.
  Persistence integration (`test_database.py`) as planned; "with or without a
  pool document" is 7.5's, since `run_migrations` takes none. Tests needing a
  pool store it, through `tests/integration/legacy_default_pool.py` or inline.
- [x] 7.3 `_migrate_job_envelopes` takes `host_id` from the row's `host_id`, then
  `params.host_id`, then `params.executor_target` only for a bare-metal job; it
  never reads a VM job's `vm_target` or `executor_target`, and logs each job left
  with no host, by ID, at WARNING (D6, design-review 24 F2). Persistence integration
  (`test_job_envelope_migration.py`): fixture `old-1`'s guest target no longer
  becomes its host; a VM job with only a guest target, and one whose guest name
  matches a registered host, both keep `host_id` NULL with a WARNING; `bm-1`
  still takes its machine from `executor_target`.
  Done; a bare-metal job is one whose resolved offering mode is `bare_metal`.
  Persistence integration as planned, plus the precedence of a stored host over
  the parameter and of the parameter over `executor_target`. The job engine
  fails a queued job naming no host with its own message
  (`provisioning/compute/tests/integration/test_job_authority.py`).
- [x] 7.4 Retire `default_pool_inventory_group` and `default_host_id` from
  `settings.toml`, `helm/values.yaml:384`, `helm/charts/provisioning/values.yaml:161`,
  and the test fixtures (D6), and rewrite `settings.toml`'s comments on pool
  definitions and the retired group, which cite sections `ARCHITECTURE.md` lacks.
  Chart render: `make -C helm test-render`.
  Done, and from `config/config.yml`'s key list. Neither key is refused: ignoring
  them changes nothing. Chart render passed.
- [x] 7.5 Persistence integration (deployment-state delta): migrating copies of one
  database under two configurations that differ in the VM playbook, a host
  default, and the pool and seed documents produces the same schema and rows.
  Done as `test_migration_reads_no_configuration.py`, through the real
  `compute-provisioning-migrate` entry point: a database holding no host or pool
  and a VM job naming no host, migrated under two configurations differing in
  both playbooks, `default_host_id`, `default_pool_inventory_group`,
  `pool_definitions_path`, and `pool_seed_path`, ends with equal DDL and rows, no
  pool, and the job's host NULL; a second case migrates with
  `PROVISIONING_PLAYBOOK_PATH` set.
- [x] 7.6 **Verification checkpoint.** Persistence integration 7.2, 7.3, 7.5;
  `make -C helm test-render`. Run `make test` in `provisioning/compute/service`,
  `make check-packaging`, and `make check-comment-hygiene`.
  End-to-end: every lane migrates a fresh provisioning database through
  `compute-provisioning-migrate`; with section 8, the VM lanes' pools come from
  the seed. No scenario proves configuration independence; service integration
  owns it.
  Owed by validation: `tests.yml`, job `release · deployment contracts` — `make
  -C helm test-render` passes with `default_host_id` gone from both values files.
  Evidence: the service (unit 653, integration 516), chart render, repository
  `make test`, `make check-packaging`, and `make check-change` passed. Sections
  7–9 were one round: a fresh VM stack has no pool until section 8 seeds one. The
  section's fresh-context findings were fixed in implementation review 37's
  triage (7.6a–h, in `reviews/37-implementation.triage.md`).

## 8. A fresh site is seeded from its seed document

Delivers `pool_seed_path`, the packaged `seed/pools.yaml`, and the
`seed-initial-pools` startup step (D4; delta "A fresh site is seeded from its seed
document", and the removed "The default pool is created with its intended
provider").

Files: `provisioning/compute/service/src/compute_provisioning_service/{seed/pools.yaml
(new),settings.toml,config.py,app_runtime.py,services/definition_documents.py}`;
tests `test_pool_declaration_startup.py`,
`tests/unit/services/test_definition_document_restart_safety.py`, and the
integration `conftest.py`.

- [x] 8.1 Add `seed/pools.yaml` with exactly the document in design D4, packaged
  with the service wheel; add `pool_seed_path = "seed/pools.yaml"` to
  `settings.toml` with a comment saying when it applies and that empty disables
  it; `Settings.resolved_pool_seed_path` resolves a relative path against the
  settings file's directory and returns none for an empty value (D4). Unit
  (`test_config.py`): default, absolute, relative, and empty values. Packaging:
  the built wheel contains `seed/pools.yaml`.
  Done; a blank value counts as empty. Unit as planned. `unzip -l` of the built
  service wheel lists `compute_provisioning_service/seed/pools.yaml`; the
  standing guard is every seeded stack (see `design.md`, "Implementation
  findings").
- [x] 8.2 Add the startup step `seed-initial-pools` after
  `import-pool-definitions` and before `verify-pool-declarations` (D4). When no
  `pool_definitions_path` is configured, `pool_seed_path` is not empty, and no
  pool is stored, it applies the seed document through the pool service's
  `import_pools_in_session` in one transaction, recording no digest, and logs each
  created pool at INFO; a missing or invalid seed document fails startup.
  Done (`DefinitionDocumentImporter.seed_initial_pools`,
  `app_runtime.seed_initial_pools_if_fresh`). A disabled pool counts as stored;
  the seed is read only once the other conditions hold (D4, 9.4a), and each skip
  is logged with its reason.
- [x] 8.3 Persistence integration (`test_pool_declaration_startup.py`, real importer,
  file-backed SQLite): a fresh database with no pool document gets `vm-default`
  and `bare-metal-default` with valid declarations and no recorded digest, and
  the declaration check passes; with a pool document, its pools and no seed; with
  stored pools, no seed; with an empty `pool_seed_path`, no pools; with a missing
  or invalid seed document, a failed startup and no pool; the step order. Replace
  the tests built on the migration-seeded or document-created `default` with
  these cases.
  Done, each case running the real startup steps in order over
  `run_migrations`' database: every planned case, plus a seed that does not
  apply left unread, an operator's own seed, a missing or invalid pool document
  not replaced by the seed, and a second start changing nothing. The
  migration-seeded and document-created `default` tests are replaced.
- [x] 8.4 Application integration through the typed clients: on a fresh service
  composed with the default seed, `vm-default` and `bare-metal-default` list
  through the pool client, a host registered with `pool_id: vm-default` and a
  capacity declared into it are admitted, and a host registered without a pool
  sells nothing.
  Done as `test_pool_seed_api.py`: the harness stores no pool
  (`_initialize_test_database(default_pool=False)`), runs the seed step, and
  shows the two pools, a placed host selling only once capacity naming it is
  declared, and an unplaced host declaring nothing.
- [x] 8.5 **Verification checkpoint.** Unit 8.1; service integration 8.3;
  application integration 8.4. Run `make test` in `provisioning/compute/service`,
  `make check-packaging`, and `make check-comment-hygiene`.
  End-to-end: the VM and bare-metal Helm releases and VM compose configure no pool
  document, so `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
  `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `multi_registry`, and
  `e2e_vm_introduction` boot on seeded pools; the bare-metal compose lane mounts
  its document and boots unseeded (`e2e_bare_metal_publication`,
  `e2e_bare_metal_introduction`, `e2e_bare_metal_mock_deal`). No new scenario is
  owed: seeding is one service's startup transaction.
  Evidence: the service (unit 658, integration 520), `make dist` and the wheel
  listing, `make check-packaging`, repository `make test`, and `make
  check-change` passed. The only stack mounting a pool document is the
  bare-metal compose file. No chart change.

## 9. E2E pools and smoke tests

Delivers e2e pools that read no system pool, the deleted write-path smoke test,
the authentication smoke test under `provisioning_security`, and the bare-metal
development document's comment (D4, D7).

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`;
`e2e-tests/tests/smoke/test_provisioning_smoke.py`; `e2e-tests/pyproject.toml`;
`helm/charts/provisioning/templates/tests/provisioning-smoke-test.yaml` and its
render test; `dev-env/bare-metal/resource-pools.yaml`.

- [x] 9.1 `register_e2e_pool` creates `vm.ansible` pools with `provider_config:
  {}`; remove `_default_pool_provider_config` and `SYSTEM_DEFAULT_POOL_ID` (D4,
  D5). Evidence: the e2e unit suite passes and no e2e source names a system pool.
  Done; e2e unit 38 passed, and a search of `e2e-tests` finds no system pool.
- [x] 9.2 Delete `test_host_crud_round_trip`. `test_auth_enforcement_when_enabled`
  sends an unsigned `GET` to a protected read route (`/api/v1/hosts/`) and asserts
  401 or 403, under a new marker `provisioning_security`; remove the
  `provisioning_write` marker from `e2e-tests/pyproject.toml` and add
  `provisioning_security` (D7). The Helm smoke hook selects
  `provisioning_readonly or provisioning_security`; extend the chart's render test
  to assert the expression. Run `make -C helm test-render`.
  Done; the check is named `test_an_unsigned_read_is_refused` (37 triage, 9.4c)
  and needs no administrator credential. Chart render passed, including
  `test_the_smoke_hook_selects_the_read_only_and_security_checks`.
- [x] 9.3 Rewrite `dev-env/bare-metal/resource-pools.yaml`'s comment: imports no
  longer require a `default` pool, and the document keeps its inert pool so the
  bare-metal lane boots without seed pools (D3, D4).
  Done, with a correction: any configured pool document keeps the lane
  unseeded, whatever it names, and the comment says so.
- [x] 9.4 **Verification checkpoint.** Run `make test` in `e2e-tests` (its unit
  suite, including `test_domain_stack_configuration.py`) and `make -C helm
  test-render`; `make check-comment-hygiene`.
  End-to-end: the VM scenarios listed in section 8 create their pools through
  `register_e2e_pool`; the provisioning smoke hook runs
  `test_an_unsigned_read_is_refused` on every Helm validation. Both are the
  evidence for this section.
  Owed by validation: `tests.yml`, job `release · deployment contracts` — `make
  -C helm test-render` passes with the smoke hook's marker expression.
  Evidence: `make -C e2e-tests test-unit` 38 (correction: `make -C e2e-tests
  test` also runs the live tiers, which need a deployed stack), chart render,
  `make check-packaging`, repository `make test`, and `make check-change`
  passed. The section-8–9 fresh-context findings were dispositioned in
  implementation review 37's triage.
  Round fixes, each recorded in its triage file:
  - Implementation review 37: the provisioning chart's capacity comment and
    `provisioning-hosts.example` describe host registration, not selling
    (37 F2); the chart's `configFiles` map, its schema, and render tests (9.4b);
    the renamed security check (9.4c); `host_registry.py`'s comments stating
    invariants (9.4d); `TESTING.md`'s fixture citation (39 O1); and the
    findings of 7.6. Evidence: `make check-packaging`, `provisioning/compute`
    236, the service (unit 658, integration 527), chart render (10 provisioning
    checks), e2e unit 38, repository `make test`, and `make check-change`
    passed.
  - Implementation review 60: no deployed `configFiles` check (60 F1, see
    `design.md`); the INI parser's and `test_pool_seed_api.py`'s docstrings say
    registering a host declares none of its capacity (60 F2). Evidence: `make
    check-packaging`, `ansible` 93, the service (unit 658, integration 527),
    repository `make test`, and `make check-change` passed.
  - Pre-closeout review 67: `test_ledger.py`'s imports at module level (67 F1);
    the backfill's and capacity migration's comments state chain-position
    invariants (67 F2). Evidence: `make check-comment-hygiene`, `make
    check-packaging`, `kit/site` 289, the service (unit 658, integration 527),
    repository `make test`, and `make check-change` passed.

## 10. Closeout

Confirm and promote the verified design, then archive last (D1–D8 and every
delta requirement). The eleven parts follow
`openspec/README.md#plan-closeout-requirements` in order. Closeout changes no
code: a part needing a code, lock, or test change returns the change to
implementation.

- [x] 10.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and
  read every comment and docstring sections 1–9 added or rewrote — the migration
  docstrings of `20260713_002` and `_migrate_job_envelopes`, `settings.toml`'s
  setting comments, the seed document, the handler — for current-system
  rationale with no change, review, or migration narration. A needed correction
  returns to implementation.
  Confirmed: `make check-comment-hygiene` passed. A scan of every comment and
  docstring line the change's commits added for history wording found none in
  production code; the test comments that name a past schema
  (`test_host_pool_optional_migration.py`'s schema-through-`20260911_001`
  fixture, the legacy suites' `inventory_group` column) describe the database
  shape a fixture reproduces, which is their invariant.
- [x] 10.2 **Import placement — confirm.** Check that every import sections 1–9
  added or touched is at module level unless a verified cycle or a recorded
  lazy-load reason keeps it local. A needed move returns to implementation.
  Confirmed: across the change's own commits, the only indented imports added
  were `test_ledger.py`'s, moved to module level in pre-closeout review 67's
  round; none remains in that module.
- [x] 10.3 **Documentation compliance.** Check D1–D8 and design-review 24's two
  corrections against `openspec/README.md`'s placement rules and the promotion
  record below, and against the code: normative behaviour in specs through the
  deltas, rationale in the companions, repository shape in `ARCHITECTURE.md`,
  operator behaviour in `DEPLOYMENT_AND_CONFIG.md` and the quickstarts, test
  ownership in `TESTING.md`. Record a disposition for every decision.
  Dispositions: D1 normative in `resource-pool-management` (delta), its
  repository rule in `ARCHITECTURE.md`; D2 normative in `physical-provisioning`
  (delta), rationale in the `site-capacity` companion, repository rule in
  `ARCHITECTURE.md`, operator behaviour in the quickstarts and
  `DEPLOYMENT_AND_CONFIG.md`; D3 normative in `resource-pool-management` and
  `site-capacity` (deltas), rationale in both companions; D4 and its amendments
  normative in `resource-pool-management` and `deployment-state` (deltas),
  rationale in the `resource-pool-management` companion, operator behaviour in
  `DEPLOYMENT_AND_CONFIG.md` and both quickstarts; D5 normative in
  `physical-provisioning` (delta), rationale in the `resource-pool-management`
  companion, the naming convention in `DEPLOYMENT_AND_CONFIG.md`; D6 and
  review 24 F2 normative in `deployment-state` (delta), operator behaviour in
  `DEPLOYMENT_AND_CONFIG.md`; D7 in `TESTING.md`; D8 is scope, recorded in the
  index. Review 24 F1 (the narrowed sale guarantee) is the `ARCHITECTURE.md`
  "Resource pools" paragraph; F2 is D6's. Every promoted statement was checked
  against the code: the startup step order (`app_runtime.startup_steps()`), the
  seed and setting comments (`settings.toml`), the chart's `configFiles`
  (`values.yaml`, its schema and render tests), and the smoke markers
  (`test_provisioning_smoke.py`). Superseded: the "Without a document,
  migration supplies the configured VM default" and "the document creates
  `default`" statements in the permanent documents, replaced.
- [x] 10.4 **Narrative compression.** Compress section notes to final behaviour,
  validation evidence, deferred work (the open question on placement governing
  declarations), and destinations, moving any durable rationale into `design.md`
  first.
  Done: plan corrections, the rebuilds' dependence on the current model, the
  pool-less-row exclusions, the packaging guard and `configFiles` rationale,
  and the declined review items moved to `design.md`'s "Implementation
  findings"; handoff notes, debugging narratives, and round-by-round fix lists
  were removed, their substance kept in the review triage files. The open
  question stays in `design.md`.
- [x] 10.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1 —
  "Consolidate physical-resource authority in the provisioning service", remove
  the open-gap row this change owns ("Without a pool document, migration seeds the
  VM `default` pool…") and state in the current-state prose that migration reads
  no configuration, hosts are placed explicitly, and fresh sites are seeded from a
  packaged document.
  Done: the row is removed; the provider paragraph states migration reads no
  configuration and creates no pool, the seed, and playbooks fixed at
  preparation; the capacity paragraphs state that no host write declares
  capacity or places a host, and that hosts are placed explicitly.
- [x] 10.6 **Campaign index currency.** Update this change's Goal 1 row in
  `openspec/changes/README.md` (status `in closeout`, notes naming the
  destinations) and its graph lines; leave `bring-host-inventory-under-definition-documents`'s
  and `gpu-optional-compute-shapes`'s `Depends on` for archive cleanup. Run `make
  check-change-index`.
  Done: status `in closeout`, notes naming the validation and destinations.
  The graph lines are unchanged: they show this change's two dependents, which
  stay until archive cleanup. `make check-change-index` passed.
- [x] 10.7 **Packaging.** Confirm `make check-packaging` and `make
  check-architecture-change CHANGE=seed-default-pool-at-runtime` pass against the
  last implementation commit; the change touches no `.agents/`, `.claude/`, or
  `.codex/` file, so record that `make check-agent-skills` is not owed, or run it
  if one was touched.
  Confirmed at `29f9fecd9`: `make check-packaging` passed (locks, layers,
  scope, dependencies, kinds); `make check-architecture-change` — the change owns
  no architecture row. The change's own commits touch no `.agents/`,
  `.claude/`, or `.codex/` file (the branch's changes there are
  `parallel-change-workflows`' merges), so `make check-agent-skills` is not
  owed; it was run and passed. Deferred to the release that ships the change:
  version bumps and floors for its incompatible interface changes (see
  `design.md`, "Implementation findings").
- [x] 10.8 **End-to-end pipeline.** Confirm the latest validation record covers the
  last implementation commit with the three lanes passing, and record its run and
  the scenarios that exercise this change: the VM lane scenarios of sections 1, 2,
  and 8 (renamed setting, seeded pools, empty VM pool configuration), the
  bare-metal scenarios of sections 3 and 8 (frozen grant and reclaim, document
  boot), and the Helm smoke hook's `provisioning_security` test. An unrelated
  blocker names its cause and owner, and leaves what it gates unrun.
  Confirmed: validation 73 (`reviews/73-validation.md`) passed at `29f9fecd9`,
  the pre-closeout fix commit and the last code commit, so it describes the
  code this closeout carries. Pipeline run 40069878714, success: e2e-vm 134
  passed (`e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
  `e2e_compute_dynamic_listings`, `e2e_listing_shapes`, `multi_registry`,
  `e2e_vm_introduction` — the renamed setting, seeded pools, and e2e pools
  with empty configuration); e2e-bare-metal 51 passed
  (`e2e_bare_metal_publication`, `e2e_bare_metal_introduction`,
  `e2e_bare_metal_mock_deal` — grants and reclaims, and the document boot);
  e2e-apicredits 1 passed, 3 skipped. Helm validation in its own namespace:
  the `e2e_scenarios` pod exited 0, and the provisioning smoke hook ran
  `test_an_unsigned_read_is_refused`. CI, owed by sections 1, 7, and 9:
  `tests.yml` run 40069882924, job `release · deployment contracts` passed,
  its log showing `make -C helm test-render` passing (the renamed value and
  refused key, `default_host_id` gone, the hook's marker expression). The
  run's other failures, `py · vms-storefront` (three
  `test_loop_gate_wiring.py` timeouts) and `py · bare-metal-storefront`
  (`test_abort_all_is_not_previewed`), fail the same way in `dev`'s baseline
  run 39646750044 at `968a4a9cd709`. No blocker.
- [x] 10.9 **Promotion.** Write every destination in the promotion record below,
  hand-editing each spec's Evidence section where its named tests moved; the
  archive in 10.11 merges the deltas. `openspec/specs/README.md` needs no change:
  no capability or companion is added. Complete the record's evidence column.
  Added by implementation review 37's triage, each a row of the record below:
  the seller quickstarts' "List only hosts to sell" lines
  (`docs/seller-quickstart.md:328`, `docs/bare-metal-seller-quickstart.md:55`)
  describe host registration, not selling (37 F2); both quickstarts document
  overriding the seed — by path and an empty `pool_seed_path` under compose,
  and `configFiles` with `config.pool_seed_path` under Helm — and
  `docs/seller-quickstart.md:200`'s fresh-site `default` is rewritten (9.4b);
  the resource-pool-management companion states that one process initializes
  a database, and what a second process starting with it sees (37 F1 / 9.4f).
  Done: every row of the record below is written, its location in the third
  column. Evidence sections hand-edited: `resource-pool-management` (the
  replaced startup tests, seeding, placement, and migration bullets),
  `physical-provisioning` (no host-write derivation, frozen playbooks, the
  retired setting), `site-capacity` (the pool-less declaration), and
  `deployment-state` (configuration-free migration, `configFiles`).
  `openspec/specs/README.md` is unchanged.
- [x] 10.10 **Documentation citations.** Run `make check-doc-citations
  CHANGE=seed-default-pool-at-runtime` and resolve every match; then run pinned
  `npx --yes @fission-ai/openspec@1.14.0 validate seed-default-pool-at-runtime
  --strict`.
  Done: `make check-doc-citations` — every cited path in the change's seven
  documents resolves and none is a tombstone; `make check-change`, which runs
  the pinned strict validation with comment hygiene, agent skills, the task
  list, and the change index, passed. The promotion record cites repository
  paths rather than relative links, so it stays valid from the archive.
- [x] 10.11 **Archival — last.** Run pinned `npx --yes @fission-ai/openspec@1.14.0
  archive seed-default-pool-at-runtime -y` without `--skip-specs`, merging the
  deltas into `resource-pool-management`, `physical-provisioning`,
  `site-capacity`, and `deployment-state` once; point this change's index row at
  the archive with status `in closeout`; run pinned `validate --specs --strict`
  and `make check-change-index`.
  Done without `--skip-specs`: no permanent spec carried a delta's requirement
  beforehand. The merged requirements were read in each spec's diff. One wrong
  merge was fixed: the deployment-state delta restated "Service-owned migration
  history" from an older wording, so the merge dropped "rather than rejecting
  drift from its normal startup path" from the scenario "A service has no
  separate deployment step for migrations", which this change did not mean to
  touch; the phrase is restored. The row
  links the archive, `in closeout`; `make check-change` on the archived change
  (pinned `validate --specs --strict` and the change index among its checks)
  passed.

**Closeout verification:** the eleven recorded outcomes, valid synchronized specs,
resolvable citations, and a current index.

## Decision-to-section map

| Decision / requirement | Implementation | Promotion |
|---|---|---|
| D1 optional host placement; "Explicit valid host membership" | 5, 6.2 | 10.9 |
| D2 no capacity from host writes; "Host writes declare no capacity" | 6.1 | 10.9 |
| D3 `default` ordinary; "Non-destructive pool lifecycle", "Strict lossless YAML validation", "Operator-administered capacity declarations" | 4, 9.3 | 10.9 |
| D4 seed document; "A fresh site is seeded from its seed document"; removed "The default pool is created with its intended provider" | 8, 9.1 | 10.9 |
| D5 domain-named settings; "A domain's service playbook setting is named for its domain" | 1 | 10.9 |
| D5 optional VM playbook, frozen at preparation; "Ansible fulfillment adapter" | 2, 9.1 | 10.9 |
| D5 bare-metal playbook frozen; "Bare-metal inventory binds an existing provider pool" | 3 | 10.9 |
| D6 migration reads no configuration; "Service-owned migration history"; "Existing schema is migrated" scenario | 2.3, 7 | 10.9 |
| D6 job-envelope host evidence (review 24 F2) | 7.3 | 10.9 |
| D7 smoke tests | 9.2 | 10.9 |
| D8 scope | none: no code; index already records the dependents | 10.6 |
| Open question: placement governing declarations | none: deferred | 10.4 keeps it in `design.md` |

## Design promotion record

| Accepted knowledge | Permanent destination | Written |
|---|---|---|
| D1 optional placement and its null and INI semantics | `openspec/specs/resource-pool-management/spec.md` — "Explicit valid host membership", via archive | `openspec/specs/resource-pool-management/spec.md#requirement-explicit-valid-host-membership`, merged by the archive; its Evidence bullet on optional placement by hand |
| D1 a host belongs to at most one pool | `docs/development/ARCHITECTURE.md` — "One name per concept", the paragraph beginning "The host is named `host_id`" | `docs/development/ARCHITECTURE.md#one-name-per-concept`: "A host belongs to at most one Resource Pool" |
| D1, D2 no host write places a host or declares capacity; a host sells only through an explicit declaration | `docs/development/ARCHITECTURE.md` — "Resource pools", a paragraph after the one on a pool's provider being fixed at creation | `docs/development/ARCHITECTURE.md#resource-pools`: the paragraph beginning "No host write places a host" |
| D2 no derivation from host writes | `openspec/specs/physical-provisioning/spec.md` — "Host writes declare no capacity" (renamed from "Legacy host capacity is derived into declarations"), via archive; `openspec/specs/site-capacity/architecture.md` — the paragraph beginning "The alternatives each left capacity"; `docs/seller-quickstart.md` §6 and `docs/bare-metal-seller-quickstart.md`; `docs/development/ARCHITECTURE.md` — "Authority boundaries", the "Sellable capacity" row; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Capacity definitions" and "What a document does to entries it stops naming", where they speak of declarations derived from host inventory | `openspec/specs/physical-provisioning/spec.md#requirement-host-writes-declare-no-capacity`, by the archive; `openspec/specs/site-capacity/architecture.md#declared-capacity-and-connection-identity`, the paragraphs beginning "The alternatives each left capacity" and "One declaration type"; `docs/seller-quickstart.md#declaring-capacity` and §6 step 3; `docs/bare-metal-seller-quickstart.md#define-the-selected-site`; `docs/development/ARCHITECTURE.md#authority-boundaries`; `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` (host inventory), `#what-a-document-does-to-entries-it-stops-naming`, and `#capacity-definitions` |
| D3 `default` ordinary | `openspec/specs/resource-pool-management/spec.md` — "Non-destructive pool lifecycle", "Strict lossless YAML validation"; `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations"; both via archive | `openspec/specs/resource-pool-management/spec.md#requirement-non-destructive-pool-lifecycle`, `#requirement-strict-lossless-yaml-validation`, and `openspec/specs/site-capacity/spec.md#requirement-operator-administered-capacity-declarations`, by the archive; the rationale in `openspec/specs/site-capacity/architecture.md#declared-capacity-and-connection-identity` and `openspec/specs/resource-pool-management/architecture.md#administrative-reconciliation` |
| D4 seed document and its trigger | `openspec/specs/resource-pool-management/spec.md` — "A fresh site is seeded from its seed document", via archive; `openspec/specs/resource-pool-management/architecture.md` — "Administrative reconciliation", replacing the paragraph beginning "On a fresh database with a mounted pool document"; `docs/development/ARCHITECTURE.md` — "Resource pools", replacing the sentence beginning "A fresh site with a mounted pool document"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents", replacing the paragraph beginning "On a first boot with a pool document configured" | `openspec/specs/resource-pool-management/spec.md#requirement-a-fresh-site-is-seeded-from-its-seed-document`, by the archive; `openspec/specs/resource-pool-management/architecture.md#administrative-reconciliation`; `docs/development/ARCHITECTURE.md#resource-pools`; `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` |
| D4 amendments: a seed read only where it applies (9.4a); overriding the seed by path (9.4b) | `openspec/specs/resource-pool-management/spec.md` — "A fresh site is seeded from its seed document", via archive; `docs/seller-quickstart.md` and `docs/bare-metal-seller-quickstart.md`, overriding or disabling the seed, with `docs/seller-quickstart.md`'s sentence beginning "A fresh site with a mounted pool document" replaced | The same requirement, by the archive; `docs/seller-quickstart.md#declaring-capacity`, the paragraph beginning "A fresh site starts with pools"; `docs/bare-metal-seller-quickstart.md#define-the-selected-site`, the paragraph beginning "The document is authoritative" |
| D4 amendment: the chart's `configFiles` (9.4b) | `openspec/specs/deployment-state/spec.md` — "The provisioning chart mounts operator files it gives no meaning", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Kubernetes: ConfigMap and Secret mounting" | `openspec/specs/deployment-state/spec.md#requirement-the-provisioning-chart-mounts-operator-files-it-gives-no-meaning`, by the archive; `docs/development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting` |
| One process initializes a database (37 F1 / 9.4f) | `openspec/specs/resource-pool-management/architecture.md` — "Administrative reconciliation", beside the seed paragraph | `openspec/specs/resource-pool-management/architecture.md#administrative-reconciliation`, the paragraph beginning "One process initializes a database"; also `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` |
| Inventory entries register hosts, not sales (37 F2) | `docs/seller-quickstart.md` §3, `docs/bare-metal-seller-quickstart.md` "Define the selected site" | `docs/seller-quickstart.md#6-live-kvm-provisioning` step 3, "List the execution hosts the service registers" (the plan's "§3" is that step); `docs/bare-metal-seller-quickstart.md#define-the-selected-site` |
| D5 optional VM playbook, playbooks frozen at preparation | `openspec/specs/physical-provisioning/spec.md` — "Ansible fulfillment adapter", "Bare-metal inventory binds an existing provider pool", via archive; `openspec/specs/resource-pool-management/architecture.md` — "Provider configuration" | `openspec/specs/physical-provisioning/spec.md#requirement-ansible-fulfillment-adapter` and `#requirement-bare-metal-inventory-binds-an-existing-provider-pool`, by the archive; `openspec/specs/resource-pool-management/architecture.md#provider-configuration`; operator notes in `docs/seller-quickstart.md#declaring-capacity` and `docs/bare-metal-seller-quickstart.md#define-the-selected-site` |
| D5 a setting belonging to one domain is named for it; `vm_playbook_path`, the refused retired key | `openspec/specs/physical-provisioning/spec.md` — "A domain's service playbook setting is named for its domain", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Profile-based configuration" | `openspec/specs/physical-provisioning/spec.md#requirement-a-domains-service-playbook-setting-is-named-for-its-domain`, by the archive; `docs/development/DEPLOYMENT_AND_CONFIG.md#profile-based-configuration`, the paragraph beginning "A setting that belongs to one domain" |
| D6 migration reads no configuration; job-envelope host evidence | `openspec/specs/deployment-state/spec.md` — "Service-owned migration history", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Migrations at startup" | `openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history`, by the archive; `docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup` |
| D7 smoke markers | `docs/development/TESTING.md` — "3. Smoke Tests (Deployment Validation)"; its "Pool Offering-Mode Enforcement" bullet on provisioning migration tests, which names the system-owned default pool | `docs/development/TESTING.md#3-smoke-tests-deployment-validation` and `#pool-offering-mode-enforcement` |
| Goal 1 gap closed | `docs/development/ROADMAP.md` — Goal 1, open-gap table and current state | `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service`: row removed, current state rewritten |
| Campaign status | `openspec/changes/README.md` — Goal 1 campaign | The change's row, `in closeout`, linking the archive |
