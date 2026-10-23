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
  Done: `settings.toml`, `config-docker.yml`, `config-mock.yml`,
  `config-local.yml.example`, `config.yml`'s key list, and the `Makefile`'s
  `serve` target; the two integration harnesses' `MagicMock` settings
  (`conftest.py`, `test_test_controller.py`) renamed too. `config-seller.yml`
  states no playbook. Unit (`test_config.py`, real Dynaconf over the service's own
  `settings.toml` and a temporary profile): a profile's relative
  `vm_playbook_path` resolves, and the packaged default resolves to the image's
  VM playbook. `git grep` for `resolved_playbook_path`, `settings.playbook_path`,
  `PROVISIONING_PLAYBOOK_PATH`, and `config.playbook_path` finds only pool-level
  `provider_config.playbook_path` reads (section 2's) and the refusal tests.
  `migrate.py` still passes the resolved path to `run_migrations` as
  `default_playbook_path`; section 7 removes that parameter.
- [x] 1.2 Refuse the retired key (D5). Add a check in `config.py` that names every
  retired setting present — `playbook_path`, replaced by `vm_playbook_path` — and
  a first startup step in `app_runtime.startup_steps()` that raises with that
  message before any other step. Unit: `test_config.py` covers the key set in a
  profile and through the `PROVISIONING_` environment layer, and its absence.
  Application integration: the service's startup sequence, run as the
  integration suite composes it, fails naming `vm_playbook_path` when the retired
  key is set.
  Done: `config.RETIRED_SETTINGS` maps each retired key to its replacement;
  `Settings.stated_retired_settings()` reads presence through Dynaconf's
  `exists`, so any layer counts, and `refuse_retired_settings()` raises
  `RetiredSettingsError` naming each key and its replacement. The startup step
  `refuse-retired-settings` is first, and `compute-provisioning-migrate` calls
  the same refusal before opening the database (beyond the plan: until section 7
  the migration reads the VM playbook to seed `default`, so a stale profile
  would otherwise seed with the key ignored before the API refused). Unit
  (`test_config.py`): the key in a profile and through
  `PROVISIONING_PLAYBOOK_PATH`, both refused naming `vm_playbook_path`; absent,
  no refusal. Unit (`test_worker.py`): the refusal is the first startup step.
  Application integration (`tests/integration/test_retired_settings_startup.py`):
  the in-process app's own lifespan raises `RetiredSettingsError` naming
  `vm_playbook_path`, and the next step's effect (`ANSIBLE_CONFIG` exported) is
  absent; and `migrate.main()` raises the same without creating its SQLite file.
  In both the key is set through the environment layer, reloaded with the
  service's own loader (`config._load_bootstrap`), and swapped into the
  `settings` object the modules read — the service loads it once at import, so
  the test reloads it rather than reproducing import. The integration suite's
  `client_and_queue` harness overrides the container and never runs the
  lifespan, so this test runs the lifespan itself; a refused start has no
  typed-client surface. A subprocess run of `compute-provisioning-api` would
  avoid the swap but starts a server on a port; the lifespan runs the same steps.
- [x] 1.3 Rename the chart's `config.playbook_path` value to `vm_playbook_path`
  in `helm/charts/provisioning/values.yaml` and make `values.schema.json` refuse
  `config.playbook_path`, as it refuses `pool_definitions_path` (D5). Extend
  `helm/charts/provisioning/tests/test_render.py`: the rendered profile carries
  `vm_playbook_path`, and a values file setting `config.playbook_path` fails
  schema validation. Run `make -C helm test-render`.
  Done. Chart render: `make -C helm test-render` passed (Helm v4.3.0), including
  the two new checks — the default render's profile carries
  `"vm_playbook_path"` and no `"playbook_path"`, and `config.playbook_path` fails
  with an error naming it. No umbrella values file or compose file set the
  provisioning playbook setting.
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
  Evidence: `make -C provisioning/compute/service test` — unit 667 passed,
  integration 487 passed (after the review fixes); `make -C
  domains/vms/provisioning/adapter test` — 29 passed; `make -C helm
  test-render` passed; repository `make test` exited 0 (run before the review
  fixes, which touched only the service's migrate entry point, docstrings, and
  tests, all re-run above); `make check-comment-hygiene` and `make check-change`
  passed. The end-to-end scenarios and the owed CI job are confirmed as
  planned: the markers exist in `e2e-tests/pyproject.toml`, and the job is
  `release-deployment` (`release · deployment contracts`) in
  `.github/workflows/tests.yml`, which runs `make -C helm test-render`.
  Handoff: Dynaconf's `exists()` is what makes "set in any layer" hold, and
  `settings.toml` must not state a retired key, or the service could never
  start. The integration suite's harness never runs the app lifespan; a test
  of a startup step runs `app.router.lifespan_context(app)` itself, as
  `test_retired_settings_startup.py` does. The Edit tool strips a trailing
  space from a replacement, which broke `values.yaml` once (`key:"value"`);
  `make -C helm test-render` caught it.

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
  Done. A stated playbook that names nothing (blank, or not a string) is refused
  as `invalid_type` rather than the former `required_field`. Library integration
  (`test_ansible_pool_config_handler.py`, the real handler over in-memory SQLite,
  in the service's `tests/integration`): `{}` and an explicit `null` stored and
  read back as `playbook_path: None`; a stated playbook kept; `""`, blank, an
  integer, and a list refused; `inventory_group` now an unknown field.
- [x] 2.2 Freeze the service's playbook at preparation (D5). `VmFulfillmentPlan`
  takes the configured `vm_playbook_path` from its runtime (`runtime.py`'s
  `fulfillment_plan()`), and `prepare_create` and `prepare_teardown` write the
  pool's `playbook_path` when it states one and that configured path otherwise.
  Unit: `test_vm_fulfillment_plan.py` covers both, for create and teardown, and a
  prepared job's parameters keeping the frozen path after the plan's configured
  path changes.
  Done. `vm_playbook_path` is a required keyword, though it may be `None`, so
  no composition can omit it; with neither the pool's nor the service's
  playbook, preparation is refused (`ProviderConfigInvalidError` naming
  `vm_playbook_path`). The legacy lease conversion's plan passes `None`: a
  historical pool always states its playbook, which its compiler requires. Unit
  (`test_vm_fulfillment_plan.py`, VM adapter): the service's path frozen for a
  pool stating none and the pool's own winning, each for create and teardown; a
  job prepared before reconfiguration carrying the old path and one prepared
  after carrying the new; refusal with neither; and `VmProvisioningRuntime`'s
  `fulfillment_plan()` passing the configured `resolved_vm_playbook_path`. That
  the stored path is what runs is the existing codec and executor tests'
  (`test_vm_codec.py`: a stored `playbook_path` becomes the plan's;
  `test_executor.py`: a plan's playbook replaces the executor's). The plan's
  former "missing playbook" case became a blank-playbook refusal.
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
  Done as `20261023_001_vm_pool_playbook_optional`
  (`_migrate_vm_pool_playbook_optional`). Its rebuild copies `resource_pools`
  and `relays` into the rebuild's metadata, since `CreateTable` must resolve the
  foreign keys it renders; the copies are not created. Correction to the plan's
  premise: `run_migrations` creates every model table before the chain, so on a
  fresh database `ansible_pool_configs` has no `inventory_group` when
  `20260724_001` runs, and `vm_leases` exists (from `20260603_003`), so the
  conversion's `SELECT apc.inventory_group` failed every fresh migration. The
  conversion now reads `inventory_group` only where the column exists, else
  `NULL`. A fresh database holds no lease, so it migrates (the fresh-database
  test below is that case's evidence); a lease met with `NULL` fails the
  compiler's pool configuration check, so a database predating resource pools
  that still holds VM leases is now refused at `20260724_001` with "no usable
  Ansible pool configuration" where it used to convert. Every live database is
  past `20260921_004` (design, Context), and 7.2 refuses such a database
  earlier, at `20260713_002`, with an actionable message. Persistence
  integration (`test_vm_pool_config_migration.py`, file SQLite): a database at
  the committed `schema_through_20260911_001.sql` shape with two populated
  configurations migrated through `apply_schema_migrations` is rebuilt (its
  `sqlite_master` page changes), keeps every other value, relaxes
  `playbook_path`, drops `inventory_group`, keeps the relay index and both
  foreign keys, accepts a NULL playbook, and still refuses an unknown pool; a
  fresh database through `run_migrations` is in shape and the migration leaves
  its table untouched (same page and DDL); a repeated run (the migration
  directly, then the chain) leaves the rebuilt table's page, columns, and rows
  as they were. Legacy suites: the three named add the column after migrating,
  as planned. Beyond the plan, `test_database.py`'s legacy chain (a pre-pools
  database holding an active VM lease) could not add the column itself, since
  `run_migrations` creates the table before the chain; its fixture now holds
  the `default` pool and its configuration, with the inventory group, which is
  what 7.2 prescribes for that test, and pins the new migration ID. That test
  therefore no longer exercises `20260713_002` creating or seeding the pool
  tables on a pre-pools database, and its `pool_document_configured`
  parametrization no longer distinguishes two cases; 7.1 removes the parameter
  and 7.2 the seed. Also updated for the dropped column:
  `test_relay_port_leases.py`, `test_pool_declaration_startup.py` (its
  seeded-`default` test, which section 8 replaces), and
  `test_pool_offering_mode_migration.py`. `_migrate_resource_pools_and_hosts_pool_id`
  keeps an unused `default_inventory_group` parameter, and `migrate.py` still
  passes `default_pool_inventory_group`, until 7.1 and 7.4 retire them;
  `settings.toml` says the setting has no effect.
- [x] 2.4 Application integration through the typed pool client
  (`test_pools_api.py`): a `vm.ansible` pool created with `provider_config: {}`
  is accepted, and its export shows `playbook_path: null`; a fulfillment accepted
  for it carries the service's configured playbook in its job parameters
  (`test_fulfillment_api.py`, extended).
  Done. `test_pools_api.py::TestPlaybookLeftToTheService`: created through the
  typed pool client with `provider_config: {}`, read back and exported with
  `playbook_path: null` and no `inventory_group`. `test_fulfillment_api.py`:
  a fulfillment begun through the typed client for such a pool freezes the
  harness's configured VM playbook (`/fake/playbook.yml`) into the prepared
  operation and into the dispatched job's stored parameters (read from the job
  engine the app composed). The integration harness constructs its own
  `VmFulfillmentPlan` with that configured path rather than through
  `VmProvisioningRuntime`, so this test does not cover the runtime's wiring;
  2.2's unit test does.
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
  Evidence: `make -C domains/vms/provisioning/adapter test` — 37 passed; `make
  -C provisioning/compute/service test` — unit 667 passed, integration 501
  passed (both after the review fixes); repository `make test` exited 0 (before
  the review fixes, which touched only these two projects' tests, a docstring,
  a migration comment, and a `settings.toml` comment, all re-run above); `make
  check-change` (comment hygiene included) passed. Fresh-context review: fixed
  the fallback's comment, the legacy fixture's comments, a vacuous assertion,
  the untested runtime wiring, the no-op proofs, and the stale
  `default_pool_inventory_group` comment; declined moving the handler's pure
  validation cases to a unit module (the file's existing validation tests sit
  there too) and copying the shared schema fixture out of `tests/unit/fixtures`
  (four unit tests read it; one copy is the point). End-to-end scenarios confirmed as planned; the VM lanes'
  pools still come from the migration-seeded `default` until sections 8 and 9,
  so none yet runs a pool stating no playbook. No `Owed by validation:` line:
  the section changes no chart.
  Handoff: a rebuild following `_migrate_capacity_declaration_contract` for a
  table whose foreign keys name tables outside its own metadata must copy those
  tables into the rebuild's `MetaData`, or `CreateTable` cannot render the
  constraint; section 6's `hosts` rebuild references `resource_pools`.
  `run_migrations` creates every model table before the versioned chain, so a
  legacy-chain test cannot add a dropped column after a mid-chain create — it
  pre-creates the table in the fixture. Reflected column types compare by
  identity; compare their string forms.

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
  Done. The plan's `playbook_path` is a required keyword (never `None`), so no
  composition can omit it; the integration harness passes its configured
  `resolved_bare_metal_playbook_path`. Unit (bare-metal adapter): grant and
  reclaim carrying the configured path; a reclaim prepared by a reconfigured
  plan carrying the new path whatever its grant carries; a reclaim of a grant
  stored without a playbook gaining the configured one;
  `build_bare_metal_runtime` (under the mock profile) giving its plan the
  configured path, observed through its provider's prepared operation; the
  codec passing a stored playbook to the plan and rendering no `playbook_path`
  variable; stored parameters without one validating and yielding none. That a
  plan's playbook replaces the executor's is `provisioning/compute/ansible`'s
  `test_executor.py`.
- [x] 3.2 Check every bare-metal mock rule and fixture that matches job
  parameters (`test_bare_metal_mock_output.py`, the service's
  `test_bare_metal_mock_profile.py`, and e2e bare-metal mock rules) and update
  any that matches an exact parameter set to admit the new field (D5). Evidence:
  the suites pass unchanged in intent.
  Checked: a mock rule matches when every key it names equals the job's
  parameter (`executor_mock.py`, `MockRuleSet`), so no rule — the adapter's
  tests, the service's mock-profile tests, or the e2e driver's
  (`{"action", "host_id"}`) — matches an exact parameter set, and none changed.
  The one exact comparison, `test_bare_metal_mock_profile.py`'s reclaim
  parameters equal to the grant's plus action and policy, still holds, since
  both carry the same configured playbook. All pass unchanged.
- [x] 3.3 **Verification checkpoint.** Unit: the two bare-metal suites above.
  Application integration: `test_bare_metal_mock_profile.py` (service) runs a
  grant and reclaim through the composed service and its stored job parameters
  carry the configured playbook. Run `make test` in
  `domains/bare_metal/provisioning/adapter` and `provisioning/compute/service`,
  and `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_mock_deal` and `e2e_bare_metal_deal` run grants
  and reclaims; they prove dispatch, not which playbook was frozen. No scenario
  is owed.
  Evidence: application integration
  (`test_bare_metal_mock_profile.py::test_a_grant_is_delivered_through_convergence_and_reclaimed_from_its_parameters`):
  a grant begun and a reclaim prepared through the typed clients, read back
  through the typed client's job reads, carry the harness's configured
  `/fake/bare-metal-node-access.yml` — through the harness's own plan
  construction, so the runtime's wiring is 3.1's unit test's. `make -C
  domains/bare_metal/provisioning/adapter test` — 46 passed; `make -C
  provisioning/compute/service test` — unit 667 passed, integration 501
  passed (both re-run after the review fixes); repository `make test` exited 0
  (before the review fixes, which renamed tests and reworded docstrings and
  comments only); `make check-change` passed. End-to-end scenarios confirmed as planned: the bare-metal lane runs
  `e2e_bare_metal_mock_deal`; `e2e_bare_metal_deal` needs a real host and no
  lane selects it. No `Owed by validation:` line: the section changes no
  chart. Fresh-context review: no rule breaches; fixed four test names,
  docstrings, or comments that claimed a playbook runs or stays frozen where a
  test shows only that parameters carry it, a vacuous grant assertion, and the
  codec docstring's claim that every stored job names a playbook. Declined:
  replacing the runtime test's `ACTIVE_PROFILES` environment setting with an
  injected seam — `build_bare_metal_runtime` selects its runner from that
  variable, as the VM runtime does, so the environment is its seam.
  Handoff: neither compute runtime's plan wiring is reached by the service's
  integration harness, which builds its own plans; each adapter's unit suite
  covers its runtime's `fulfillment_plan` wiring.

## 4. `default` is an ordinary pool in the kits

Delivers pool documents that need not name `default`, and `kit/site` reading no
declaration without a pool as `default` (D3; deltas "Strict lossless YAML
validation", "Non-destructive pool lifecycle", "Operator-administered capacity
declarations").

Files: `kit/resource-pools/src/market_resource_pools/service.py` and its tests;
`kit/site/src/market_site/ledger.py` and its tests;
`provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py`.

- [ ] 4.1 Remove the `missing_default_pool` check from document validation
  (`service.py:616-623`) (D3). Library integration
  (`kit/resource-pools/tests/integration/test_resource_pool_service.py`):
  `test_missing_default_pool_rejected` becomes a document without `default`
  validating and importing; the disabled-`default` tests stay.
- [ ] 4.2 Remove every `pool_id or DEFAULT_POOL_ID` read from `kit/site`'s ledger
  (`ledger.py:871, 933, 1002, 1222-1229, 1317, 2251, 2307`) and from
  `capacity_inventory.py:59-61`; a stored declaration with no pool is excluded
  from projection, admission, and pool moves, and is logged rather than read as
  any pool (D3). `DEFAULT_POOL_ID` stays exported. Library integration
  (`kit/site/tests/integration/test_ledger.py`) and unit
  (`provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`)
  cover a row stored with a NULL pool: absent from the projection, not admitted,
  and not reported as `default`.
- [ ] 4.3 **Verification checkpoint.** The suites of 4.1 and 4.2. Application
  integration: `test_pools_api.py` imports a document naming no `default`
  through the typed client and disables a pool named `default`. Run `make test`
  in `kit/resource-pools`, `kit/site`, and `provisioning/compute/service`, `make
  check-packaging`, and `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_publication` and `e2e_bare_metal_introduction`
  import the bare-metal development document; none exercises a document without
  `default`. No scenario is owed.

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

- [ ] 5.1 Contracts and client (D1): `HostResponse.pool_id` becomes `str | None`;
  `HostCreate`'s description says an omitted pool leaves the host unplaced;
  `HostUpdate` keeps `pool_id: Optional[str]`, and the route service tells an
  explicit `null` from an omitted field by the fields the request set. The typed
  client's host update sends the fields the caller set, an explicit `null`
  included (`exclude_unset` for `HostUpdate`), while every other body keeps the
  shared `exclude_none` serialization. Unit (`provisioning/compute/tests/unit`):
  the serialized update body carries `"pool_id": null` only when set.
- [ ] 5.2 Host authority (D1): `Host.pool_id` becomes nullable with no default or
  server default; `register_host` stores the named pool or none;
  `_move_to_pool` accepts `None`, runs the pool-change hooks for unplacing as for
  any move, and checks existence only for a named pool; `InventoryHost.pool_id`
  carries three states (a pool, unplace, unstated), and `apply_inventory` moves
  an existing host only when its entry states a pool or unplaces it, creating a
  new host unplaced when its entry is unstated.
- [ ] 5.3 INI parser (D1): `parse_inventory_ini` maps a non-empty `pool_id=` to a
  pool, an empty `pool_id=` to unplace, and an absent key to unstated, and its
  docstring no longer names a default pool. Unit (`test_inventory.py`): all three
  forms.
- [ ] 5.4 Application integration through the typed client (`test_hosts_api.py`,
  `test_host_pool_moves_api.py`): a host created without a pool reads back
  `pool_id: null`; an update omitting the pool keeps it; an explicit `null`
  unplaces it; an import with an empty `pool_id=` unplaces an existing host; an
  import with no `pool_id` keeps an existing host's pool and leaves a new host
  unplaced; a VM relay hook refusing an unplacing rolls back the whole import;
  an unknown pool is still refused.
- [ ] 5.5 **Verification checkpoint.** Unit: contracts/client serialization and
  `test_inventory.py`. Application integration: 5.4. Run `make test` in
  `provisioning/compute/contracts`, `provisioning/compute/client`,
  `provisioning/compute`, `provisioning/compute/ansible`, and
  `provisioning/compute/service`; `make check-packaging`; `make
  check-comment-hygiene`.
  End-to-end: the VM and bare-metal scenarios register hosts into named pools
  (`e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`), so they prove the
  named path still places; none registers an unplaced host. No scenario is owed:
  placement is one authority's transaction, which application integration owns.

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

- [ ] 6.1 Remove the `HostCapacityDerivation` port from the host authority and
  `apply_inventory`'s derivation call and serialization, `services/capacity_derivation.py`,
  its container wiring, and `test_capacity_derivation.py` (D2). The upgrade
  migration `20260921_004` keeps its own SQL and is not touched. Application
  integration: `test_host_capacity_derivation_api.py` becomes the proof that an
  INI import and a startup seed carrying `gpus=` create no capacity declaration,
  so the capacity projection holds no entry for those hosts; the derivation
  cases in `test_capacity_api.py` assert the same.
- [ ] 6.2 Append a migration after section 2's that rebuilds `hosts` from the
  model with `pool_id` nullable and no default, following
  `_migrate_capacity_declaration_contract`, and is a no-op on a table already in
  that shape (D1, design "Migration Plan"). Persistence integration: a new
  `test_host_pool_optional_migration.py` covers existing hosts keeping their
  pools and every other column, a fresh database, a repeated run, and
  `foreign_key_check` passing.
- [ ] 6.3 **Verification checkpoint.** Application integration 6.1; service
  integration 6.2. Run `make test` in `provisioning/compute` and
  `provisioning/compute/service`, `make check-packaging`, and `make
  check-comment-hygiene`.
  End-to-end: every VM and bare-metal scenario declares capacity explicitly, so
  the lanes prove nothing depended on derivation. No scenario is owed.

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

- [ ] 7.1 `run_migrations(engine)` and `apply_schema_migrations(engine)` take only
  the engine; remove their configuration parameters, `seed_default_pool`,
  `_has_existing_pool_or_host_state`, and the special dispatch for
  `20260713_002` and `20261002_002`; `migrate.py` passes only the engine (D6).
  Update every test calling them with keyword inputs.
- [ ] 7.2 `20260713_002` creates its tables and its column only: it writes no
  pool row and no configuration row, and raises an actionable `SchemaDriftError`
  when hosts exist and no `default` pool does (D6). Rewrite its docstring and
  the comments describing the seed. Persistence integration (`test_database.py`):
  a fresh database, with or without a pool document configured, holds no pool
  after migration; a pre-pool database with hosts is refused; tests that relied
  on the seeded `default` create the pool they need. A legacy-chain test whose
  fixture holds hosts from before resource pools inserts the `default` pool and
  configuration rows the retired seed wrote, so it still exercises the later
  migrations it was written for.
- [ ] 7.3 `_migrate_job_envelopes` takes `host_id` from the row's `host_id`, then
  `params.host_id`, then `params.executor_target` only for a bare-metal job; it
  never reads a VM job's `vm_target` or `executor_target`, and logs each job left
  with no host, by ID, at WARNING (D6, design-review 24 F2). Persistence integration
  (`test_job_envelope_migration.py`): fixture `old-1`'s guest target no longer
  becomes its host; a VM job with only a guest target, and one whose guest name
  matches a registered host, both keep `host_id` NULL with a WARNING; `bm-1`
  still takes its machine from `executor_target`.
- [ ] 7.4 Retire `default_pool_inventory_group` and `default_host_id` from
  `settings.toml`, `helm/values.yaml:384`, `helm/charts/provisioning/values.yaml:161`,
  and the test fixtures (D6), and rewrite `settings.toml`'s comments on pool
  definitions and the retired group, which cite sections `ARCHITECTURE.md` lacks.
  Chart render: `make -C helm test-render`.
- [ ] 7.5 Persistence integration (deployment-state delta): migrating copies of one
  database under two configurations that differ in the VM playbook, a host
  default, and the pool and seed documents produces the same schema and rows.
- [ ] 7.6 **Verification checkpoint.** Persistence integration 7.2, 7.3, 7.5;
  `make -C helm test-render`. Run `make test` in `provisioning/compute/service`,
  `make check-packaging`, and `make check-comment-hygiene`.
  End-to-end: every lane migrates a fresh provisioning database through
  `compute-provisioning-migrate`; with section 8, the VM lanes' pools come from
  the seed. No scenario proves configuration independence; service integration
  owns it.
  Owed by validation: `tests.yml`, job `release · deployment contracts` — `make
  -C helm test-render` passes with `default_host_id` gone from both values files.

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

- [ ] 8.1 Add `seed/pools.yaml` with exactly the document in design D4, packaged
  with the service wheel; add `pool_seed_path = "seed/pools.yaml"` to
  `settings.toml` with a comment saying when it applies and that empty disables
  it; `Settings.resolved_pool_seed_path` resolves a relative path against the
  settings file's directory and returns none for an empty value (D4). Unit
  (`test_config.py`): default, absolute, relative, and empty values. Packaging:
  the built wheel contains `seed/pools.yaml`.
- [ ] 8.2 Add the startup step `seed-initial-pools` after
  `import-pool-definitions` and before `verify-pool-declarations` (D4). When no
  `pool_definitions_path` is configured, `pool_seed_path` is not empty, and no
  pool is stored, it applies the seed document through the pool service's
  `import_pools_in_session` in one transaction, recording no digest, and logs each
  created pool at INFO; a missing or invalid seed document fails startup.
- [ ] 8.3 Persistence integration (`test_pool_declaration_startup.py`, real importer,
  file-backed SQLite): a fresh database with no pool document gets `vm-default`
  and `bare-metal-default` with valid declarations and no recorded digest, and
  the declaration check passes; with a pool document, its pools and no seed; with
  stored pools, no seed; with an empty `pool_seed_path`, no pools; with a missing
  or invalid seed document, a failed startup and no pool; the step order. Replace
  the tests built on the migration-seeded or document-created `default` with
  these cases.
- [ ] 8.4 Application integration through the typed clients: on a fresh service
  composed with the default seed, `vm-default` and `bare-metal-default` list
  through the pool client, a host registered with `pool_id: vm-default` and a
  capacity declared into it are admitted, and a host registered without a pool
  sells nothing.
- [ ] 8.5 **Verification checkpoint.** Unit 8.1; service integration 8.3;
  application integration 8.4. Run `make test` in `provisioning/compute/service`,
  `make check-packaging`, and `make check-comment-hygiene`.
  End-to-end: the VM and bare-metal Helm releases and VM compose configure no pool
  document, so `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
  `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `multi_registry`, and
  `e2e_vm_introduction` boot on seeded pools; the bare-metal compose lane mounts
  its document and boots unseeded (`e2e_bare_metal_publication`,
  `e2e_bare_metal_introduction`, `e2e_bare_metal_mock_deal`). No new scenario is
  owed: seeding is one service's startup transaction.

## 9. E2E pools and smoke tests

Delivers e2e pools that read no system pool, the deleted write-path smoke test,
the authentication smoke test under `provisioning_security`, and the bare-metal
development document's comment (D4, D7).

Files: `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`;
`e2e-tests/tests/smoke/test_provisioning_smoke.py`; `e2e-tests/pyproject.toml`;
`helm/charts/provisioning/templates/tests/provisioning-smoke-test.yaml` and its
render test; `dev-env/bare-metal/resource-pools.yaml`.

- [ ] 9.1 `register_e2e_pool` creates `vm.ansible` pools with `provider_config:
  {}`; remove `_default_pool_provider_config` and `SYSTEM_DEFAULT_POOL_ID` (D4,
  D5). Evidence: the e2e unit suite passes and no e2e source names a system pool.
- [ ] 9.2 Delete `test_host_crud_round_trip`. `test_auth_enforcement_when_enabled`
  sends an unsigned `GET` to a protected read route (`/api/v1/hosts/`) and asserts
  401 or 403, under a new marker `provisioning_security`; remove the
  `provisioning_write` marker from `e2e-tests/pyproject.toml` and add
  `provisioning_security` (D7). The Helm smoke hook selects
  `provisioning_readonly or provisioning_security`; extend the chart's render test
  to assert the expression. Run `make -C helm test-render`.
- [ ] 9.3 Rewrite `dev-env/bare-metal/resource-pools.yaml`'s comment: imports no
  longer require a `default` pool, and the document keeps its inert pool so the
  bare-metal lane boots without seed pools (D3, D4).
- [ ] 9.4 **Verification checkpoint.** Run `make test` in `e2e-tests` (its unit
  suite, including `test_domain_stack_configuration.py`) and `make -C helm
  test-render`; `make check-comment-hygiene`.
  End-to-end: the VM scenarios listed in section 8 create their pools through
  `register_e2e_pool`; the provisioning smoke hook runs
  `test_auth_enforcement_when_enabled` on every Helm validation. Both are the
  evidence for this section.
  Owed by validation: `tests.yml`, job `release · deployment contracts` — `make
  -C helm test-render` passes with the smoke hook's marker expression.

## 10. Closeout

Confirm and promote the verified design, then archive last (D1–D8 and every
delta requirement). The eleven parts follow
`openspec/README.md#plan-closeout-requirements` in order. Closeout changes no
code: a part needing a code, lock, or test change returns the change to
implementation.

- [ ] 10.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and
  read every comment and docstring sections 1–9 added or rewrote — the migration
  docstrings of `20260713_002` and `_migrate_job_envelopes`, `settings.toml`'s
  setting comments, the seed document, the handler — for current-system
  rationale with no change, review, or migration narration. A needed correction
  returns to implementation.
- [ ] 10.2 **Import placement — confirm.** Check that every import sections 1–9
  added or touched is at module level unless a verified cycle or a recorded
  lazy-load reason keeps it local. A needed move returns to implementation.
- [ ] 10.3 **Documentation compliance.** Check D1–D8 and design-review 24's two
  corrections against `openspec/README.md`'s placement rules and the promotion
  record below, and against the code: normative behaviour in specs through the
  deltas, rationale in the companions, repository shape in `ARCHITECTURE.md`,
  operator behaviour in `DEPLOYMENT_AND_CONFIG.md` and the quickstarts, test
  ownership in `TESTING.md`. Record a disposition for every decision.
- [ ] 10.4 **Narrative compression.** Compress section notes to final behaviour,
  validation evidence, deferred work (the open question on placement governing
  declarations), and destinations, moving any durable rationale into `design.md`
  first.
- [ ] 10.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1 —
  "Consolidate physical-resource authority in the provisioning service", remove
  the open-gap row this change owns ("Without a pool document, migration seeds the
  VM `default` pool…") and state in the current-state prose that migration reads
  no configuration, hosts are placed explicitly, and fresh sites are seeded from a
  packaged document.
- [ ] 10.6 **Campaign index currency.** Update this change's Goal 1 row in
  `openspec/changes/README.md` (status `in closeout`, notes naming the
  destinations) and its graph lines; leave `bring-host-inventory-under-definition-documents`'s
  and `gpu-optional-compute-shapes`'s `Depends on` for archive cleanup. Run `make
  check-change-index`.
- [ ] 10.7 **Packaging.** Confirm `make check-packaging` and `make
  check-architecture-change CHANGE=seed-default-pool-at-runtime` pass against the
  last implementation commit; the change touches no `.agents/`, `.claude/`, or
  `.codex/` file, so record that `make check-agent-skills` is not owed, or run it
  if one was touched.
- [ ] 10.8 **End-to-end pipeline.** Confirm the latest validation record covers the
  last implementation commit with the three lanes passing, and record its run and
  the scenarios that exercise this change: the VM lane scenarios of sections 1, 2,
  and 8 (renamed setting, seeded pools, empty VM pool configuration), the
  bare-metal scenarios of sections 3 and 8 (frozen grant and reclaim, document
  boot), and the Helm smoke hook's `provisioning_security` test. An unrelated
  blocker names its cause and owner, and leaves what it gates unrun.
- [ ] 10.9 **Promotion.** Write every destination in the promotion record below,
  hand-editing each spec's Evidence section where its named tests moved; the
  archive in 10.11 merges the deltas. `openspec/specs/README.md` needs no change:
  no capability or companion is added. Complete the record's evidence column.
- [ ] 10.10 **Documentation citations.** Run `make check-doc-citations
  CHANGE=seed-default-pool-at-runtime` and resolve every match; then run pinned
  `npx --yes @fission-ai/openspec@1.14.0 validate seed-default-pool-at-runtime
  --strict`.
- [ ] 10.11 **Archival — last.** Run pinned `npx --yes @fission-ai/openspec@1.14.0
  archive seed-default-pool-at-runtime -y` without `--skip-specs`, merging the
  deltas into `resource-pool-management`, `physical-provisioning`,
  `site-capacity`, and `deployment-state` once; point this change's index row at
  the archive with status `in closeout`; run pinned `validate --specs --strict`
  and `make check-change-index`.

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

| Accepted knowledge | Permanent destination |
|---|---|
| D1 optional placement and its null and INI semantics | `openspec/specs/resource-pool-management/spec.md` — "Explicit valid host membership", via archive |
| D1 a host belongs to at most one pool | `docs/development/ARCHITECTURE.md` — "One name per concept", the paragraph beginning "The host is named `host_id`" |
| D1, D2 no host write places a host or declares capacity; a host sells only through an explicit declaration | `docs/development/ARCHITECTURE.md` — "Resource pools", a paragraph after the one on a pool's provider being fixed at creation |
| D2 no derivation from host writes | `openspec/specs/physical-provisioning/spec.md` — "Host writes declare no capacity" (renamed from "Legacy host capacity is derived into declarations"), via archive; `openspec/specs/site-capacity/architecture.md` — the paragraph beginning "The alternatives each left capacity"; `docs/seller-quickstart.md` §6 and `docs/bare-metal-seller-quickstart.md` |
| D3 `default` ordinary | `openspec/specs/resource-pool-management/spec.md` — "Non-destructive pool lifecycle", "Strict lossless YAML validation"; `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations"; both via archive |
| D4 seed document and its trigger | `openspec/specs/resource-pool-management/spec.md` — "A fresh site is seeded from its seed document", via archive; `openspec/specs/resource-pool-management/architecture.md` — "Administrative reconciliation", replacing the paragraph beginning "On a fresh database with a mounted pool document"; `docs/development/ARCHITECTURE.md` — "Resource pools", replacing the sentence beginning "A fresh site with a mounted pool document"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents", replacing the paragraph beginning "On a first boot with a pool document configured" |
| D5 optional VM playbook, playbooks frozen at preparation | `openspec/specs/physical-provisioning/spec.md` — "Ansible fulfillment adapter", "Bare-metal inventory binds an existing provider pool", via archive; `openspec/specs/resource-pool-management/architecture.md` — "Provider configuration" |
| D5 a setting belonging to one domain is named for it; `vm_playbook_path`, the refused retired key | `openspec/specs/physical-provisioning/spec.md` — "A domain's service playbook setting is named for its domain", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Profile-based configuration" |
| D6 migration reads no configuration; job-envelope host evidence | `openspec/specs/deployment-state/spec.md` — "Service-owned migration history", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Migrations at startup" |
| D7 smoke markers | `docs/development/TESTING.md` — "3. Smoke Tests (Deployment Validation)"; its "Pool Offering-Mode Enforcement" bullet on provisioning migration tests, which names the system-owned default pool |
| Goal 1 gap closed | `docs/development/ROADMAP.md` — Goal 1, open-gap table and current state |
| Campaign status | `openspec/changes/README.md` — Goal 1 campaign |
