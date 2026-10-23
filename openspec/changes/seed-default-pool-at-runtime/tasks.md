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
  Correction (section 7): `compute-provisioning-migrate` no longer calls the
  refusal. Its reason, that the migration read the VM playbook to seed
  `default`, ended when migration stopped reading operational configuration
  (D6), so the command now reads only the database URL and log level; the
  service's own startup step still refuses the key. Its `migrate.main()` test
  was removed, and `test_migration_reads_no_configuration.py` runs the command
  under two configurations instead. Round fix (37 triage, 7.6a): that module
  also runs `migrate.main()` with `PROVISIONING_PLAYBOOK_PATH` set and shows it
  applies every migration, which is the evidence for this correction.
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

- [x] 4.1 Remove the `missing_default_pool` check from document validation
  (`service.py:616-623`) (D3). Library integration
  (`kit/resource-pools/tests/integration/test_resource_pool_service.py`):
  `test_missing_default_pool_rejected` becomes a document without `default`
  validating and importing; the disabled-`default` tests stay.
  Done: the check, its `declared_ids` set, and the module's `DEFAULT_POOL_ID`
  import are gone. Library integration (`kit/resource-pools`, the real service
  over in-memory SQLite): a document naming only `hetzner-eu-central`
  validates with no problems and a created-only diff, writes nothing, then
  imports it alone; the disabled-`default` test stays, its docstring no longer
  naming the removed rule. `make -C kit/resource-pools test` — 124 passed.
- [x] 4.2 Remove every `pool_id or DEFAULT_POOL_ID` read from `kit/site`'s ledger
  (`ledger.py:871, 933, 1002, 1222-1229, 1317, 2251, 2307`) and from
  `capacity_inventory.py:59-61`; a stored declaration with no pool is excluded
  from projection, admission, and pool moves, and is logged rather than read as
  any pool (D3). `DEFAULT_POOL_ID` stays exported. Library integration
  (`kit/site/tests/integration/test_ledger.py`) and unit
  (`provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`)
  cover a row stored with a NULL pool: absent from the projection, not admitted,
  and not reported as `default`.
  Done. Ledger (`kit/site`): admission (`_find_candidate`) skips a pool-less
  row first, before any claim matching, and logs it; a settlement assignment
  to one is refused (`records no pool`); `backing_pool_id_in_session` returns
  `None`; `_stored_declaration` keeps `None`, so re-declaring such a row in a
  pool is "updated", never "unchanged"; and naming any pool for it is a move,
  refused under a live obligation ("from no recorded pool"). Beyond the plan,
  the same defect read a pool-less row as a pool named for its resource id in
  four more `kit/site` places, and each now excludes it:
  `iter_scheduling_candidates_in_session` (scheduling) and both
  `projections.py` functions (`resource_pool_projection`,
  `capacity_bucket_projection`, since the capacity-bucket projection reads the
  ledger directly, not the provisioning inventory) log it;
  `dict_resource_satisfies_claim`, the exact matcher the VM storefront injects
  for ranking over snapshot rows, matches it to no claim, so ranking agrees
  with admission. `resource_feasibility_view` keeps its `pool_id or
  resource_id` fallback, but no caller now reaches it with a pool-less row.
  The administrative listing and the snapshot still carry such a row, with
  `pool_id: null` (the snapshot always did), so an operator can find and
  re-declare it. Provisioning's `load_capacity_resource_inventory` leaves it
  out of the resource-pool projection with a WARNING naming it. Library
  integration (`kit/site/tests/integration/test_ledger.py`, the real ledger
  over in-memory SQLite): a pool-less row is not probed or reserved for an
  unpinned claim, a claim naming `default`, or one naming the resource's id,
  each refusal logged by the missing-pool check itself, and no reservation is
  written; it is in neither projection while a pooled row is, and the listing
  reports it with no pool; it is not a scheduling candidate and an assignment
  to it is refused, leaving the reservation's backing unchanged; naming
  `default` for it is refused while a reservation holds it and accepted once
  released; the declaration that was "unchanged" while the row was in
  `default` is "updated" once its pool is gone, and the reservation it backs
  resolves to no pool. Unit (`kit/site`): `test_projections.py` — both
  projections equal their projection without the pool-less resource, each
  logging it; `test_dict_resource_satisfies_claim.py` — a pool-less row
  matches no claim, `default`- and id-pinned included. The VM storefront's
  test double `domains/vms/storefront/tests/fake_site.py` served snapshot
  rows with no `pool_id`, which no site now produces, so
  `test_most_available_ranks_by_legacy_gpu_count_claim_through_the_real_aggregate_client`
  ranked nothing; its rows now carry the pool-per-resource its own matcher
  already assumed (`make -C domains/vms/storefront test` — unit 1103,
  integration 448 passed). These replace `test_attribute_view_falls_back_to_resource_id_when_pool_id_unset`
  and `test_a_legacy_row_with_no_stored_pool_is_in_the_default_pool`, which
  asserted the fallbacks. `kit/fulfillment`'s
  `test_resource_without_pool_is_not_schedulable` reserved against a pool-less
  row, which admission now refuses; it strips the pool after admission instead,
  and the scheduler still finds no candidate. Unit
  (`test_capacity_inventory.py`): a pool-less declaration between two pooled
  ones is left out and logged, and the projection equals the two pooled
  declarations' own.
  `DEFAULT_POOL_ID` stays exported from `market_resource_pools`.
- [x] 4.3 **Verification checkpoint.** The suites of 4.1 and 4.2. Application
  integration: `test_pools_api.py` imports a document naming no `default`
  through the typed client and disables a pool named `default`. Run `make test`
  in `kit/resource-pools`, `kit/site`, and `provisioning/compute/service`, `make
  check-packaging`, and `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_publication` and `e2e_bare_metal_introduction`
  import the bare-metal development document; none exercises a document without
  `default`. No scenario is owed.
  Evidence: application integration (`test_pools_api.py`, through the typed
  pool client against the in-process app): a document naming no `default`
  validates with no problems and imports, creating its pool and disabling the
  harness's stored `default` it omits; `test_delete_default_pool_disables_but_keeps_it_resolvable`
  disables `default` (its docstring no longer cites a spec decision that does
  not exist; its host-fallback assertion is section 5's). Persistence
  integration (`test_pool_declaration_startup.py`): the "bad document" case
  used `pools: []`, which is now valid, so it uses an entry missing its
  provider, which no longer distinguishes "nothing substituted" from "not
  applied"; section 8 replaces that test. Repository `make test` passed
  before the review fixes (every suite, chart render included), and after
  them and the test double's fix every suite passed but one:
  `scripts/tests/test_publish_matrix.py` failed on section 5's edit to
  `provisioning/compute/ansible/pyproject.toml`, already in the tree, which
  section 5 owns (`kit/resource-pools` 124, `kit/site` 282 then 289,
  `kit/fulfillment` 171, the service's unit 667 and integration 502); `make check-packaging`, `make
  check-comment-hygiene`, and `make check-change` passed. End-to-end scenarios
  confirmed as planned. No `Owed by validation:` line: the section changes no
  chart. Fresh-context review: fixed the admission order (the missing-pool
  check ran after claim matching, so a `default`-pinned claim was refused by
  the resource-id fallback, unlogged), the injected storefront matcher
  disagreeing with admission, a tombstone assertion on the removed problem
  code, an equality the inventory test claimed but did not check, an
  unreachable guard in `_pool_declares_mode`, and the untested
  `declaration_change_in_session` and `backing_pool_id_in_session` cases, and
  added the projection exclusion at unit level. Declined: rate-limiting the
  WARNING emitted per pool-less row per read — no write path can produce such
  a row (every declaration names a pool, and `20260921_002` backfilled the
  rest), so one appearing is an operator's database edit the log should keep
  naming; and editing the delete-`default` test's host-fallback comment, which
  describes this commit's behaviour and section 5 rewrites.
  Handoff: `.dist` is rebuilt by `make check-packaging` from the working
  tree, so a later section's uncommitted edits reach every wheel-consuming
  suite; a section's checks need the tree to hold that section alone, and
  `git stash` and `git checkout --` are not available to this step.

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
  Done. `HostResponse.pool_id` is `Optional[str]` and required, so a response
  always states it; `HostCreate` and `HostUpdate` describe an omitted pool and
  an explicit `null`. The authority, not the route service, tells the two
  apart (`"pool_id" in data.model_fields_set` in `update_host`): the route
  service passes the model through, and its fields-set travels with it. The
  client's `_update_host` dumps `exclude_unset` itself, so the shared
  `payload()` is unchanged. Unit (`provisioning/compute/client/tests/unit/test_client.py`,
  where the client's tests live rather than `provisioning/compute`'s): through both client
  variants over a mock transport, an update sends `{"pool_id": null}` for an
  explicit `None`, the pool for a named one, `{"enabled": false}` alone, and
  `{}` for an empty update.
- [x] 5.2 Host authority (D1): `Host.pool_id` becomes nullable with no default or
  server default; `register_host` stores the named pool or none;
  `_move_to_pool` accepts `None`, runs the pool-change hooks for unplacing as for
  any move, and checks existence only for a named pool; `InventoryHost.pool_id`
  carries three states (a pool, unplace, unstated), and `apply_inventory` moves
  an existing host only when its entry states a pool or unplaces it, creating a
  new host unplaced when its entry is unstated.
  Done. Unstated is the sentinel `POOL_UNSTATED` (an enum member, exported
  with its type `PoolUnstated`), and `InventoryHost.pool_id` defaults to it;
  `PoolChangeHook` takes optional pools, and VM's relay hook, which already
  compared `None` pools, is annotated so. Library integration
  (`provisioning/compute/tests/integration/test_host_authority.py`, the real
  authority over in-memory SQLite with a recording hook): a created host and
  a new inventory entry naming no pool are each stored, read, and looked up
  with no pool, and no hook runs; an update omitting the pool keeps it, an
  explicit `None` unplaces it through the hooks, unplacing an unplaced host
  is no move, and placing it again is one; an inventory entry stating a pool
  places it, stating none keeps it while reconnecting it, and `None`
  unplaces it; a hook refusing an unplacing leaves the update, and the whole
  import with a new host in it, unapplied. Existing cases that relied on the
  default now state `default`. Beyond the plan, the service's derivation
  (`services/capacity_derivation.py`, `plan_derived_declarations`) skips an
  unplaced host, since a declaration must name a pool; section 6 removes
  derivation. Application integration
  (`test_host_capacity_derivation_api.py::test_an_unplaced_host_with_gpus_derives_nothing`):
  an imported GPU host stating no pool is unplaced and no declaration is
  created.
- [x] 5.3 INI parser (D1): `parse_inventory_ini` maps a non-empty `pool_id=` to a
  pool, an empty `pool_id=` to unplace, and an absent key to unstated, and its
  docstring no longer names a default pool. Unit (`test_inventory.py`): all three
  forms.
  Done. Unit (`provisioning/compute/ansible/tests/unit/test_inventory.py`):
  `pool_id=gpu`, `pool_id=`, and no key parse to `"gpu"`, `None`, and
  `POOL_UNSTATED`. The package no longer imports `market_resource_pools`, so
  `arkhai-kit-resource-pools` leaves its dependencies (`make lock` dropped it
  from four locks) and `docs/development/RELEASING.md`'s row for it, which
  `scripts/tests/test_publish_matrix.py` holds equal to the declaration.
- [x] 5.4 Application integration through the typed client (`test_hosts_api.py`,
  `test_host_pool_moves_api.py`): a host created without a pool reads back
  `pool_id: null`; an update omitting the pool keeps it; an explicit `null`
  unplaces it; an import with an empty `pool_id=` unplaces an existing host; an
  import with no `pool_id` keeps an existing host's pool and leaves a new host
  unplaced; a VM relay hook refusing an unplacing rolls back the whole import;
  an unknown pool is still refused.
  Done. Application integration (the in-process app through the typed family,
  host-import, and pool clients): `test_hosts_api.py::TestHostPlacement` — a
  host created with no pool reads back `null` from create, get, and list; an
  update stating only `gpu_model` keeps `default`; an explicit `null`
  unplaces; an import with `pool_id=` unplaces an imported host; an import
  with no `pool_id` keeps an existing host's pool while changing its address
  and creates a new host unplaced; an unknown pool is a 400 on create,
  update, and import, leaving the host unchanged and creating none.
  `test_host_pool_moves_api.py`: with a VM tunnel bound through a host in a
  relay pool, an import that first names a new host and then unplaces the
  tunnelled one is a 409 naming the held lease; the tunnelled host keeps its
  pool and address and the new host, applied before the refusal, is rolled
  back with it; an update unplacing the host is a 409 too. `test_pools_api.py`: a
  host registered with no pool is in none while `default` is stored and
  enabled (replacing `test_register_host_defaults_to_default_pool`), and the
  delete-`default` test no longer asserts the host fallback; its module
  docstring no longer calls `default` undisableable. Two derivation tests
  (`test_host_capacity_derivation_api.py`, and
  `test_capacity_api.py::test_the_resource_pool_projection_publishes_declarations_not_hosts`)
  import a GPU host expecting a derived declaration, so their INI now states
  `pool_id=default`; section 6 rewrites them.
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
  Evidence: `make -C provisioning/compute/contracts test` — 59 passed;
  `provisioning/compute/client` — 58; `provisioning/compute` — 235 (unit and
  library integration); `provisioning/compute/ansible` — 93;
  `provisioning/compute/service` — unit 667, integration 510, then 511
  after the review fixes (which touched tests, comments, and docstrings, and
  were re-run in `provisioning/compute`, its `ansible`, and the service);
  repository
  `make test` passed before the review fixes (every suite, chart render and
  release tooling included); `make lock`, `make check-packaging`, `make check-comment-hygiene`,
  and `make check-change` passed. End-to-end scenarios: corrected — two
  e2e paths register an unplaced host. The provisioning smoke test's
  `test_host_crud_round_trip` registers `smoke-test-host` with no pool,
  which section 9 deletes; and the VM scenarios' module fixture
  `_ensure_provisioning_host_registered` (`e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`)
  registers `kvm1` with no pool, which is now an unplaced host where it was
  placed in `default`; its readers (the mock job dry run's host lookup)
  read the host record, not its pool, so a scenario reaching it exercises
  an unplaced host's lookup. No `Owed by validation:`
  line: the section changes no chart. Fresh-context review: fixed the import
  rollback test (its new host came after the refused one, so its absence
  proved nothing; it now comes first), an untested derivation branch, the
  unchecked refusal message, the inventory host's lookup, the stale seeding
  comment in `app_runtime.py`, `PoolChangeRefusedError`'s docstring, a
  rationale in `hosts/db.py` tying placement to selling, the operator example
  `domains/vms/provisioning/iac/ansible/inventory/provisioning-hosts.example`
  (outside the plan: it said `pool_id` defaulted to `default` and that a host
  is sold as its pool), the module docstring of `inventory.py`, and these
  notes. Declined: bumping package versions and raising floors for the
  incompatible changes (`HostResponse.pool_id` nullable, `InventoryHost`'s
  default, the hook signature, and `compute_provisioning_ansible` now
  importing `POOL_UNSTATED`, which no released `arkhai-compute-provisioning`
  has). `docs/development/RELEASING.md` bumps a version when a release is
  cut, and no section of this change has bumped one (sections 2 and 3 made
  incompatible changes too); the release that ships the change owes every
  bump and floor together. Recorded for closeout's packaging part.
  Handoff: until section 6's `hosts` rebuild, a database migrated before
  this change keeps `hosts.pool_id` `NOT NULL DEFAULT 'default'`, so on it
  an unplaced write fails at the constraint; the harnesses build `hosts`
  from the model and cannot see it. Sections 5 and 6 ship in one round.
  `.dist` is rebuilt from the working tree by `make check-packaging` and
  `make dist`, so a section's wheel-consuming suites see whatever else is
  uncommitted; and `make push-branch` refuses a dirty tree, so section 4's
  commit is pushed with this section's.

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
  Done. `services/capacity_derivation.py` and `test_capacity_derivation.py`
  are deleted (staged by the owner after the implementing step's `rm` and
  `git rm` were refused), and nothing imports them. `HostCapacityDerivation` and the
  authority's `capacity_derivation` parameter are gone, `apply_inventory`
  neither derives nor takes the ledger's serialization lock (it held it only
  for the derived declarations), and the host authority's docstring states
  that no host write declares capacity; the container's
  `capacity_derivation` provider and import are gone, as are the harnesses'
  (`tests/integration/conftest.py`, `test_test_controller.py`) and the
  library suite's fake; `test_legacy_host_capacity_migration.py` drops its
  parity test against the runtime derivation (the migration's SQL is now the
  only derivation) and its now-unused helper. Comments that described
  derivation are rewritten: `app_runtime.py`'s seeding comment,
  `inventory.py`'s `gpus=` comment, `hosts/db.py`'s module docstring,
  `20260921_004`'s docstring sentence naming the service's derivation (its
  SQL untouched), `kit/site`'s `declarations.py` module docstring (outside
  the plan: it listed the derivation as a user of the model), and the
  operator example `provisioning-hosts.example`'s `gpus=` and `gpu_model=`
  lines, and, beyond the plan, two e2e comments describing a host-derived
  projection (`test_compute_dynamic_listings.py`, and `host_registry.py`'s
  module docstring, which also told the history of a debugging loop).
  Application integration (`test_host_capacity_derivation_api.py`, renamed
  `test_host_writes_declare_no_capacity_api.py` for what it proves): an INI
  import with `gpus=`, placed and unplaced, records both hosts' GPU fields
  and declares nothing, and the resource-pool projection is empty; the
  startup seed step (`app_runtime.seed_inventory_if_empty`, over the
  harness's host authority, its module settings replaced by one stating
  `inventory_ini`) registers both hosts with their GPU counts and declares
  nothing; a host created in a pool through the API, then updated with new
  GPU fields, declares nothing; an operator's declaration naming a host
  survives a re-import changing its GPUs.
  `test_capacity_api.py::test_the_resource_pool_projection_publishes_declarations_not_hosts`
  asserts nothing is declared after the INI import and the host
  registration, then declares `kvm1` and shows only that declaration
  projected, with live availability.
- [x] 6.2 Append a migration after section 2's that rebuilds `hosts` from the
  model with `pool_id` nullable and no default, following
  `_migrate_capacity_declaration_contract`, and is a no-op on a table already in
  that shape (D1, design "Migration Plan"). Persistence integration: a new
  `test_host_pool_optional_migration.py` covers existing hosts keeping their
  pools and every other column, a fresh database, a repeated run, and
  `foreign_key_check` passing.
  Done as `20261023_002_hosts_pool_optional` (`_migrate_hosts_pool_optional`),
  rebuilding from `Host.__table__` with `resource_pools` copied into the
  rebuild's metadata, as section 2's rebuild does. It is a no-op when
  `pool_id` is already nullable with no default. Persistence integration
  (`test_host_pool_optional_migration.py`, file SQLite): a database at the
  committed `schema_through_20260911_001.sql` shape with two hosts in two
  pools, one with a path key and one with an embedded (stand-in) ciphertext,
  migrated through `apply_schema_migrations`, ends with `pool_id` nullable
  and undefaulted, its foreign key to `resource_pools`, both hosts' pools,
  GPU fields, and addresses, the embedded key's ciphertext as protected, and
  accepts an unplaced host; a table restored to the required, defaulted
  shape is rebuilt (its `sqlite_master` page changes) with every column of
  every row equal (`SELECT *`) and `foreign_key_check` empty; the rebuilt table still refuses an unknown pool; a fresh database
  through `run_migrations` is in shape and the migration leaves it untouched
  (same page and DDL); a repeated run leaves page and rows as they were.
  `test_database.py`'s pinned migration set gains the ID; its legacy chain's
  host keeps `default`.
- [x] 6.3 **Verification checkpoint.** Application integration 6.1; service
  integration 6.2. Run `make test` in `provisioning/compute` and
  `provisioning/compute/service`, `make check-packaging`, and `make
  check-comment-hygiene`.
  End-to-end: every VM and bare-metal scenario declares capacity explicitly, so
  the lanes prove nothing depended on derivation. No scenario is owed.
  Evidence, with the deletions in place: `make -C provisioning/compute test`
  — 235 passed; `make -C provisioning/compute/service test` — unit 653,
  integration 515; repository `make test` passed (every suite, chart render
  and release tooling included); `make check-packaging` and `make
  check-change` passed. End-to-end scenarios confirmed as planned; no
  `Owed by validation:` line, since the section changes no chart.
  Fresh-context review: no correctness, layering, or
  packaging finding (the rebuild and dropping the ledger lock from
  `apply_inventory` were judged sound: the only pool-change hook reads relay
  leases, not the ledger). Fixed: a comment naming "this change" in the new
  migration test and another in `test_legacy_host_capacity_migration.py`;
  the rebuild test compared 7 of 11 columns and no protected value (it now
  compares every column, with an embedded key in the fixture); unchecked
  GPU fields and addresses; the unexercised host-update path (now tested);
  `test_capacity_api.py` asserting nothing before its declaration; the
  file's name; the two e2e comments; and these notes. Re-run after the
  fixes: the service suite as above, and `make test-e2e-unit` — 38 passed.
  Not fixed, stated instead: the rebuild copies the current `Host` model, as
  section 2's and `_migrate_capacity_declaration_contract` do, so a later
  model change that adds a `NOT NULL` column without a server default, or
  drops a column, changes what this migration does on an older database.
  Handoff: two permanent documents still describe derivation, now named in
  the promotion record for closeout (10.9): `docs/development/ARCHITECTURE.md`'s
  authority-table row "Sellable capacity" ("or derivation from legacy host
  inventory") and `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Capacity
  definitions" and "What a document does to entries it stops naming".
  Sections 7–9 start in a fresh session; section 7 also owns the stale
  "ARCHITECTURE.md § Schema Migration Execution" citations in `migrate.py`,
  `database.py`, and `migrations.py` (`SchemaDriftError`), and section 8 the
  one in `app_runtime.py`.

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
  Done. Every migration is now dispatched as `migration.apply(engine)`; the
  two entrypoints' docstrings say the result depends on code and stored data
  alone, citing the deployment-state spec, in place of the stale
  "ARCHITECTURE.md § Schema Migration Execution" citation (also replaced in
  `SchemaDriftError`'s docstring, `migrate.py`'s module docstring, and, beyond
  the plan, the provisioning chart's init-container comment in
  `templates/deployment.yaml`). `migrate.main()` reads only `database_url`
  and `log_level` and no longer calls the retired-settings refusal (see 1.2's
  correction). Every caller dropped its keyword inputs (unit:
  `test_pool_offering_mode_migration.py`, `test_vm_host_executor_ref_migration.py`,
  `test_host_connection_migration.py`, `test_legacy_vm_lease_migration.py`,
  `services/test_definition_document_restart_safety.py`,
  `services/test_capacity_definitions_startup.py`; integration: those named
  under 7.2 and 7.3, `test_relay_administration.py`, `test_relay_port_allocator.py`,
  `test_relay_port_leases.py`, `test_reservation_release_mirror_migration.py`,
  `test_pool_advertisement_backing_migration.py`, `test_vm_provider_identity_migration.py`,
  `test_legacy_backfill_teardown.py`, `test_fulfillment_convergence_after_legacy_backfill.py`).
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
  Done. The refusal (`_refuse_hosts_without_default_pool`) runs before this
  migration touches any table or column; `run_migrations`' table creation and
  the earlier migrations have already run, and stay recorded (37 triage,
  7.6d). It counts the hosts, names the migration, and says
  what to create (`default` with provider `ansible` and its
  `ansible_pool_configs` row naming the VM playbook) or that the database can
  first be migrated by a release whose migration still creates the pool. The
  column is still added `NOT NULL DEFAULT 'default'`, as it was, so existing
  hosts land in `default`; `20261023_002` relaxes it. Persistence
  integration (`test_database.py`, in-memory SQLite through `run_migrations`):
  a fresh database holds no pool and no configuration row and passes the
  schema check; a database predating resource pools with an empty host table
  migrates to a nullable, undefaulted `hosts.pool_id` with no pool; one with
  two hosts and no `default` is refused naming the count, the migration, and
  `ansible_pool_configs`, leaving no pool, no `pool_id` column, both hosts,
  and `20260713_002` unrecorded while `20260713_001` is recorded. "With or
  without a pool document configured" no longer has a test of its own, since
  `run_migrations` takes no document; 7.5 shows the migration command's
  result is the same under either. The legacy chain's fixture already held
  `default` and its configuration (section 2); its comment now says why, the
  `pool_document_configured` parametrization is gone, and it asserts the
  fixture's pool is the only one. Tests that relied on the seed now store
  the pool they need: a shared helper `tests/integration/legacy_default_pool.py`
  (`test_legacy_backfill_teardown.py`,
  `test_fulfillment_convergence_after_legacy_backfill.py`,
  `test_vm_provider_identity_migration.py`), inline inserts in
  `test_legacy_vm_lease_migration.py`, `test_pool_offering_mode_migration.py`
  (as the pre-offering-mode `ansible` pool with no tags, so its derivation
  still covers `default`), `test_pool_advertisement_backing_migration.py`
  (its fresh-bootstrap test, which asserted the seeded pool's declarations,
  is removed), `test_lease_target_reconciliation.py`, and a `vm-pool` in
  `test_capacity_definitions_startup.py`. `test_pool_declaration_startup.py`,
  which section 8 rewrites, now stores a serving site's `default` in its
  fixture (`existing_default=True`); its interrupted-migration test interrupts
  at the host count instead of the seed's pool query, and with no document
  configured it now ends with no pool. The integration harness keeps its own
  `default` (it builds tables from the models); its comment no longer says
  migration seeds one, nor does `test_pools_api.py`'s.
- [x] 7.3 `_migrate_job_envelopes` takes `host_id` from the row's `host_id`, then
  `params.host_id`, then `params.executor_target` only for a bare-metal job; it
  never reads a VM job's `vm_target` or `executor_target`, and logs each job left
  with no host, by ID, at WARNING (D6, design-review 24 F2). Persistence integration
  (`test_job_envelope_migration.py`): fixture `old-1`'s guest target no longer
  becomes its host; a VM job with only a guest target, and one whose guest name
  matches a registered host, both keep `host_id` NULL with a WARNING; `bm-1`
  still takes its machine from `executor_target`.
  Done. "Bare-metal job" is the job's resolved offering mode (`bare_metal`),
  the same value the migration records. Persistence integration
  (`test_job_envelope_migration.py`, in-memory SQLite, the migration called
  directly): `old-1` (only `vm_target`), `bare-1` (no evidence), and a new
  `guest-1` whose `vm_target` and `executor_target` both name `kvm2`, a
  host in the fixture's `hosts` table, all keep `host_id` NULL, and exactly
  those three WARNINGs are logged, each naming its job; `vm-1` keeps its
  `host_id` parameter and `bm-1` takes `bm-node-1`. The legacy chain in
  `test_database.py` (job `job-1`, only `vm_target`) passes with its host
  left NULL. Round fix (37 triage, 7.6c):
  `test_a_stored_host_outranks_the_parameter_and_the_parameter_outranks_the_target`
  migrates a job table that already records `host_id`: a VM job's stored host
  outranks its `host_id` parameter, and a bare-metal job's `host_id` parameter
  outranks its `executor_target`. The job engine now fails a queued job naming
  no host with "job names no host, so it cannot be dispatched", rather than
  "host None is not registered" (7.6h; `compute_provisioning/jobs/engine.py`,
  the compute kit's library integration
  `test_a_job_naming_no_host_fails_before_any_executor_runs`), and this
  migration's docstring says so.
- [x] 7.4 Retire `default_pool_inventory_group` and `default_host_id` from
  `settings.toml`, `helm/values.yaml:384`, `helm/charts/provisioning/values.yaml:161`,
  and the test fixtures (D6), and rewrite `settings.toml`'s comments on pool
  definitions and the retired group, which cite sections `ARCHITECTURE.md` lacks.
  Chart render: `make -C helm test-render`.
  Done, and from `config/config.yml`'s key list. Fixtures: both integration
  harnesses' `MagicMock` settings and the unit `mock_settings`. Neither key is
  refused, unlike `playbook_path`: ignoring them changes nothing the service
  does. The pool-definitions comment now cites `DEPLOYMENT_AND_CONFIG.md`,
  "Definition documents", and says migration creates no pool; section 8 adds
  the seed. A repository search finds neither key outside the change's
  documents and 7.5's test. Chart render: `make -C helm test-render` passed.
- [x] 7.5 Persistence integration (deployment-state delta): migrating copies of one
  database under two configurations that differ in the VM playbook, a host
  default, and the pool and seed documents produces the same schema and rows.
  Done as `test_migration_reads_no_configuration.py` (file SQLite, the real
  `compute-provisioning-migrate` entry point, `migrate.main()`, each
  configuration set through the `PROVISIONING_` environment layer and loaded
  by the service's own loader, as 1.2's test does). Reworked in the round fix
  (37 triage, 7.6a/7.6b/7.6f), because the first version's database reached
  none of the configuration reads migration used to make, so its
  two-configuration comparison held under the code before section 7 too; only
  its NULL-host assertion, which 7.3 owns, would have failed. The source database holds no host and no pool, and
  one VM job from before job envelopes whose parameters name no host and no
  target: the old seed would have created `default` from the first
  configuration's playbook, and the old job-envelope migration would have
  given the job each configuration's `default_host_id`. The configurations
  differ in `vm_playbook_path`, `bare_metal_playbook_path`, `default_host_id`,
  `default_pool_inventory_group`, `pool_definitions_path` (empty, against a
  valid document naming another pool), and `pool_seed_path` (the packaged
  seed, against empty). Both copies end with equal DDL for every schema
  object and equal rows in every table, `schema_migrations` compared by ID
  (its `applied_at` is when each copy ran); no pool exists, and the job's
  host is NULL. A second case runs the command with `PROVISIONING_PLAYBOOK_PATH`
  set and shows every migration applied (1.2's correction). The module no
  longer imports `test_database.py`'s private host-table helper.
- [x] 7.6 **Verification checkpoint.** Persistence integration 7.2, 7.3, 7.5;
  `make -C helm test-render`. Run `make test` in `provisioning/compute/service`,
  `make check-packaging`, and `make check-comment-hygiene`.
  End-to-end: every lane migrates a fresh provisioning database through
  `compute-provisioning-migrate`; with section 8, the VM lanes' pools come from
  the seed. No scenario proves configuration independence; service integration
  owns it.
  Owed by validation: `tests.yml`, job `release · deployment contracts` — `make
  -C helm test-render` passes with `default_host_id` gone from both values files.
  Evidence: `make -C provisioning/compute/service test` — unit 653 passed,
  integration 516 passed (re-run after the last edit, a docstring in
  `app_runtime.py`); `make -C helm test-render` passed; repository `make test`
  exited 0; `make check-packaging` and `make check-change` (comment hygiene
  included) passed. End-to-end scenarios confirmed as planned, with one
  consequence: from this commit until sections 8 and 9 land, a fresh e2e
  stack has no pool, and `register_e2e_pool` still reads the system
  `default`'s playbook, so the VM lanes cannot pass on this commit alone;
  sections 7–9 are one round. The owed CI job is confirmed as planned
  (`release-deployment` in `.github/workflows/tests.yml`).
  Handoff: `run_migrations` creates every model table before the chain, so
  `hosts` exists on every database 20260713_002 sees; its refusal counts rows,
  not tables. A test needing a pool after migration stores it itself; the
  integration directory's `legacy_default_pool.py` holds the VM `default` in
  its post-chain shape. `test_pool_declaration_startup.py`'s
  `existing_default` fixture flag is a stand-in until section 8 rewrites that
  module.
  Fresh-context review. The owner deferred every finding below to the
  round's implementation review and triage, and section 7 was committed
  with them open:
  - 7.5's test does not discriminate. Its source database already holds hosts
    and `default`, its VM job has a `vm_target`, and both
    `pool_definitions_path` values are non-empty, so the pre-section code would
    pass its equality check too. Rework it: migrate a host-less database under
    an empty `pool_definitions_path` against a document; include a VM job with
    no target against a set `default_host_id`; drop `pool_seed_path`, which
    does not exist until section 8; vary `bare_metal_playbook_path` as well.
    Also add a case running `migrate.main()` with `PROVISIONING_PLAYBOOK_PATH`
    set, so the 1.2 correction's claim is tested. Then correct the 7.2, 7.5
    and 1.2 notes and `test_retired_settings_startup.py`'s docstring.
  - Fix two comments in that test: the module docstring's "every operational
    setting migration once read" narrates history, and the comment at the
    final job assertion credits a guard the test does not show.
  - 7.3: the fixture's legacy `ansible_jobs` has no `host_id` column, so the
    row's own `host_id` precedence is untested, as is a bare-metal job whose
    `params.host_id` outranks its `executor_target`. Add both, or narrow the
    note.
  - 7.2's note says the refusal runs "before any table or column is touched".
    That is true only within the migration; earlier migrations and
    `run_migrations`' table creation precede it. Reword the note.
  - Wording: `settings.toml`'s pool-definitions comment reads as if migration
    creates no pool only when the path is empty; the chart's init-container
    comment ("which refuses") reads as if the container refuses, and its line
    is overlong.
  - Use `legacy_default_pool.py` instead of the private
    `test_database._create_pre_pool_hosts` import where it fits (low).
  - Declined or deferred: six touched tests in `tests/unit` run real SQLite.
    The misplacement predates this section, and TESTING.md's move-when-touched
    rule is written for library packages, so moving them is not this
    section's. Citations to deployment-state "Service-owned migration history"
    and to `DEPLOYMENT_AND_CONFIG.md` resolve; their text is promoted at
    closeout (10.9, 10.11).
  - Observations, not defects: the job engine's failure message for a NULL
    host says "host None is not registered" (`compute_provisioning/jobs/engine.py`).
    A pre-pools database with capacity rows but no hosts migrates into
    declarations naming a nonexistent `default` (20260921_002), which is
    consistent with D6's wording.
  Round fix (implementation review 37's triage) for the findings above: 7.6a,
  7.6b, and 7.6f in 7.5's note and 1.2's correction; 7.6c and 7.6h in 7.3's
  note; 7.6d in 7.2's note; 7.6e — the chart's init-container comment says the
  service, not the init container, refuses a database behind its last
  migration, and is rewrapped, and `settings.toml`'s `pool_definitions_path`
  comment says an empty value seeds a fresh site from `pool_seed_path`. 7.6g
  and the second observation stand as recorded.

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
  Done. The document's pools are D4's exactly, under a header comment saying
  when it applies. A blank value counts as empty. Unit (`test_config.py`, the
  service's own `settings.toml` and a profile loaded by its loader): the
  packaged default resolves to `seed/pools.yaml` beside `settings.toml` and
  the file exists; an absolute path is kept; a relative one resolves against
  the settings directory, not the working directory (the helper `chdir`s to
  a temporary directory); empty and blank give `None`. Packaging: after `make
  dist`, `unzip -l` of `arkhai_compute_provisioning_service-0.17.2-py3-none-any.whl`
  lists `compute_provisioning_service/seed/pools.yaml` (hatchling ships every
  file under the package, as it ships `settings.toml` and `config/`). The
  standing guard that it stays packaged (37 triage, 9.4b): the service image
  installs only the wheel, and every stack starting without a pool document —
  the VM compose lane and both Helm releases — reads the seed from it, so a
  wheel without it fails each of those starts; no packaging check is added.
- [x] 8.2 Add the startup step `seed-initial-pools` after
  `import-pool-definitions` and before `verify-pool-declarations` (D4). When no
  `pool_definitions_path` is configured, `pool_seed_path` is not empty, and no
  pool is stored, it applies the seed document through the pool service's
  `import_pools_in_session` in one transaction, recording no digest, and logs each
  created pool at INFO; a missing or invalid seed document fails startup.
  Done: `DefinitionDocumentImporter.seed_initial_pools` and the step
  `app_runtime.seed_initial_pools_if_fresh`. A disabled pool counts as
  stored. The seed file is read only once the other conditions hold, so a
  missing seed document fails startup only where it would apply: a site
  holding pools, or one with a pool document, never reads it. The emptiness
  check and the import share one transaction. Each created pool is logged
  ("Pool seed: created pool <id> from <path>"), and each skip is logged with
  its reason. The other stale "ARCHITECTURE.md § Schema Migration Execution"
  citation, in `initialise_container_resources`, now cites the
  deployment-state spec.
- [x] 8.3 Persistence integration (`test_pool_declaration_startup.py`, real importer,
  file-backed SQLite): a fresh database with no pool document gets `vm-default`
  and `bare-metal-default` with valid declarations and no recorded digest, and
  the declaration check passes; with a pool document, its pools and no seed; with
  stored pools, no seed; with an empty `pool_seed_path`, no pools; with a missing
  or invalid seed document, a failed startup and no pool; the step order. Replace
  the tests built on the migration-seeded or document-created `default` with
  these cases.
  Done. Each case runs the real startup steps in the service's order
  (`import_pool_definitions_if_configured`, `seed_initial_pools_if_fresh`,
  `verify_pool_declarations`), with the module's settings and container
  attributes replaced by the deployment's, over `run_migrations`' database and
  the packaged seed resolved by the service's own settings. Cases:
  - fresh, no document: both pools, enabled, with their provider, their mode
    delivered and advertised, backed, and no playbook; an INFO line per
    created pool; no import recorded of any kind; a second start changes
    nothing;
  - fresh with a document (`_DECLARED_DOCUMENT` and the bare-metal lane's
    `dev-env/bare-metal/resource-pools.yaml`): only its pool, and its digest
    recorded;
  - stored pools: no seed, and the export unchanged; a stored pool that is
    disabled: no seed (only the pool IDs are checked);
  - empty `pool_seed_path`: no pools, and startup passes;
  - a missing seed document, and an invalid one whose two valid entries come
    before the bad one: startup fails and no pool is created;
  - a missing or invalid seed document on a site holding pools, or with a
    pool document configured: startup continues, no pool changes, and the step
    logs its skip, which it takes before opening the seed (round fix, 37
    triage, 9.4a);
  - an operator's own valid seed document: exactly its pools are created, with
    no import recorded (round fix, 37 triage, 9.4b);
  - a bad or missing pool document on a fresh site: startup fails, and the
    seed step does not stand in for it;
  - the step order.
  Replaced: the document-created `default` test (now the fresh-with-document
  case), the interrupted first migration (migration creates no pool, which
  7.2 shows), and the existing-`default` state test (now the stored-pools
  case). Kept: the declaration-check tests, the refused predating document,
  the unchanged document, the provider-immutability tests, and the stand-in
  `existing_default` fixture, which now is that case's site. Its declaration
  check over that site is `test_a_site_holding_default_passes_the_startup_check`,
  renamed from `test_migrated_state_passes_the_startup_check`, since migration
  no longer makes the pool it checks (37 triage, 9.4c).
- [x] 8.4 Application integration through the typed clients: on a fresh service
  composed with the default seed, `vm-default` and `bare-metal-default` list
  through the pool client, a host registered with `pool_id: vm-default` and a
  capacity declared into it are admitted, and a host registered without a pool
  sells nothing.
  Done as `test_pool_seed_api.py`, over the in-process app through the
  typed family, pool, and site clients. The module overrides `db_engine` so
  the harness stores no pool (`_initialize_test_database(default_pool=False)`,
  a new keyword), then runs the service's seed step with the packaged path
  over the harness's pool service. Cases: exactly the two seeded pools list,
  enabled, with their providers; a host registered into `vm-default` is
  placed and declares nothing until capacity naming it is registered, after
  which a VM claim is reserved and the projection shows the declaration under
  `vm-default`; a host registered with no pool reads back `null`, no
  declaration exists, and a VM claim is not reserved. Correction (section 9's
  check): that case also asserted every projected pool empty, which could not
  fail, since the projection lists only pools with resources; the assertion
  is removed. Its case does not depend on the seed. The step runs directly rather than through the app's lifespan,
  which the harness never runs (1.2's handoff).
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
  Evidence: `make -C provisioning/compute/service test` — unit 658 passed,
  integration 520 passed; `make dist` and the wheel listing of 8.1; `make
  check-packaging` and `make check-change` (comment hygiene included)
  passed; repository `make test` exited 0. End-to-end scenarios confirmed as
  planned: the only stack mounting a pool document is the bare-metal compose
  file (`domains/bare_metal/compose.yml`, `PROVISIONING_POOL_DEFINITIONS_PATH`),
  and the provisioning chart's `definitions.pools` is empty by default, so
  the VM Helm and compose stacks and the bare-metal Helm release boot on the
  seed. The VM scenarios still need section 9 to create their pools without
  reading `default`. No `Owed by validation:` line: the section changes no
  chart. Fresh-context check: started, and ended early when the API's rate
  limit stopped it, before it reported; one check is run over sections 8 and
  9 together at section 9's checkpoint instead.
  Handoff: a test that needs a fresh site through the in-process app
  overrides `db_engine` with `_initialize_test_database(engine,
  default_pool=False)` and runs the seed step itself, as
  `test_pool_seed_api.py` does. A VM pool stating no playbook reads back with
  `provider_config["playbook_path"]` as `None`, not as an empty mapping.

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
  Done. The helper's docstring now says the pool leaves its playbook to the
  service's `vm_playbook_path`, frozen at preparation, and the constants'
  comment no longer names a system pool. A pool surviving an earlier run is
  reconciled by its tags as before; its stored configuration is left as it
  is. E2e unit (`make -C e2e-tests test-unit`): 38 passed. A search of
  `e2e-tests` for `SYSTEM_DEFAULT_POOL_ID`, `_default_pool_provider_config`,
  `get_pool("default")`, and a `default` pool ID finds nothing. That a VM
  scenario's pool provisions through the service's playbook is shown only
  once the VM lane runs (validation).
- [x] 9.2 Delete `test_host_crud_round_trip`. `test_auth_enforcement_when_enabled`
  sends an unsigned `GET` to a protected read route (`/api/v1/hosts/`) and asserts
  401 or 403, under a new marker `provisioning_security`; remove the
  `provisioning_write` marker from `e2e-tests/pyproject.toml` and add
  `provisioning_security` (D7). The Helm smoke hook selects
  `provisioning_readonly or provisioning_security`; extend the chart's render test
  to assert the expression. Run `make -C helm test-render`.
  Done. The authentication check no longer takes `seller_settings` and needs
  no administrator credential, so it runs wherever the hook runs; `httpx` is
  imported at module level. The module docstring states that every check is
  stateless. The unused contract imports went with the deleted test. Chart
  render (`make -C helm test-render`, Helm v4.3.0): passed, including
  `test_the_smoke_hook_selects_the_read_only_and_security_checks`, which
  finds the hook's rendered document and its `-m` argument. Under
  `--strict-markers`, `pytest --collect-only -m "provisioning_readonly or
  provisioning_security" tests/smoke/test_provisioning_smoke.py` selects the
  module's five checks, the authentication check among them. Against no
  stack the five fail with connection refused, which proves the selection
  and nothing about a deployed service; the Helm validation's hook run is
  that evidence. The check is now `test_an_unsigned_read_is_refused`: nothing
  turns enforcement off, so its old name's "when enabled" described no
  condition it has (37 triage, 9.4c).
- [x] 9.3 Rewrite `dev-env/bare-metal/resource-pools.yaml`'s comment: imports no
  longer require a `default` pool, and the document keeps its inert pool so the
  bare-metal lane boots without seed pools (D3, D4).
  Done, with a correction to the premise: what keeps the lane unseeded is
  that a pool document is configured, whatever it names (an empty `pools`
  list would too), not that it holds a pool. The comment says so, and that a
  document need not name `default` or any pool.
- [x] 9.4 **Verification checkpoint.** Run `make test` in `e2e-tests` (its unit
  suite, including `test_domain_stack_configuration.py`) and `make -C helm
  test-render`; `make check-comment-hygiene`.
  End-to-end: the VM scenarios listed in section 8 create their pools through
  `register_e2e_pool`; the provisioning smoke hook runs
  `test_an_unsigned_read_is_refused` on every Helm validation. Both are the
  evidence for this section.
  Owed by validation: `tests.yml`, job `release · deployment contracts` — `make
  -C helm test-render` passes with the smoke hook's marker expression.
  Evidence: `make -C e2e-tests test-unit` — 38 passed (the unit suite, with
  `test_domain_stack_configuration.py`). Correction to the plan: `make -C
  e2e-tests test` runs the smoke and e2e tiers too, which need a deployed
  stack; run here, with none, it ends 23 failed and 189 errors, all in the
  live smoke and e2e modules (the provisioning smoke module's five fail with
  a refused connection; the others were not inspected one by one), so
  `test-unit` is the suite this checkpoint means. `make -C helm test-render` passed; `make
  check-packaging` and `make check-change` (comment hygiene included)
  passed; repository `make test` exited 0. End-to-end scenarios and the owed CI job confirmed as planned (the
  job is `release-deployment` in `.github/workflows/tests.yml`).
  Fresh-context check over sections 8 and 9: no layering, packaging, or
  documentation-placement breach. Fixed: the bare-metal document's comment
  (see 9.3), the vacuous 8.4 assertion, the importer's module and class
  docstrings (which said every import is digest-gated), an overlong rewrapped
  line in `initialise_container_resources`, and the config unit helper not
  clearing `PROVISIONING_POOL_SEED_PATH`; the 8.3 and 8.4 notes are
  corrected. Re-run after the fixes: the service suite (unit 658,
  integration 520) and `make check-change`. Left for the round's review and
  triage, as the owner directed:
  - The seed step reads the seed document only where it applies, so a
    missing or invalid seed fails startup only on a fresh site with no pool
    document. The delta requirement "A fresh site is seeded from its seed
    document" says a missing or invalid seed "MUST fail startup" without that
    condition. Either the delta says "when it applies", or the step checks
    the seed on every start. The narrower reading is also untested: no case
    pairs a missing or invalid seed with stored pools or a configured
    document.
  - The packaged-seed check is one manual `unzip -l`; the unit test's
    `is_file()` reads the source tree, so nothing catches a regression.
  - `test_auth_enforcement_when_enabled` names a toggle that does not exist
    (D7 kept the name); the seed tests replace `app_runtime.settings` and
    container attributes, as earlier sections' tests do, though the importer
    takes settings directly; `test_pool_seed_api.py` imports the private
    `_initialize_test_database`; `test_migrated_state_passes_the_startup_check`
    now runs over a fixture's pool, not migration's.
  - `host_registry.py`'s module docstring and the GPU-count comment still
    narrate history ("previously let…", "stayed invisible until…"), outside
    this section's lines.
  - Section 8's file list named `tests/unit/services/test_definition_document_restart_safety.py`;
    it needed no change, since it covers contributed documents only.
  - Observation: an API and a worker starting together on one fresh
    database could both find no pool, and one would fail startup; the pool
    document import shares the race, and no deployment runs both against
    one database at first start.
  Closeout (10.9) also replaces the `resource-pool-management` Evidence
  bullet naming the tests section 8 replaced.
  Handoff: sections 7–9 are one round's evidence. A fresh VM e2e stack now
  holds only the seed pools, and its scenarios create their own pools with
  no provider configuration, so the VM lane is the first evidence that a
  pool stating no playbook dispatches. A Helm release with no
  `definitions.pools`, the bare-metal release 2 included, holds the seed
  pools as well; the bare-metal compose lane holds only its document's.
  Round fix (implementation review 37's triage; the open items above are
  dispositioned in `reviews/37-implementation.triage.md`):
  - 37 F2: the provisioning chart's comment on capacity and pools says a pool a
    declaration names must exist when capacity is imported — from `pools`, or
    on a fresh site without one from the service's seed — instead of naming
    `default`; `provisioning-hosts.example` calls its entries hosts the
    service registers, and says to list only execution hosts. The seller
    quickstarts' same wording is 10.9's.
  - 9.4b: the provisioning chart gains `configFiles` (`values.yaml`,
    `values.schema.json`, `templates/configmap.yaml`, `templates/deployment.yaml`):
    each entry renders through `toYaml` into the ConfigMap and mounts
    read-only at `/app/config/<name>`, the mount's path and name quoted. The
    schema takes a single file name of at most 253 characters, and refuses
    `.`, names beginning `..`, the three definition documents' names, and
    `config.yml`, `config-*.yml`, and their `.yaml` forms. Chart render
    (`tests/test_render.py`): an operator seed and `config.pool_seed_path`
    render, mount, and pass through; content with an indented first line and
    no final newline, under a name YAML reads as a boolean, survives exactly
    (Helm parses every rendered manifest, so a broken block scalar fails the
    render); each refused name fails naming it.
  - 9.4c: `test_an_unsigned_read_is_refused` (see 9.2).
  - 9.4d: `host_registry.py`'s module docstring and its GPU-count and
    one-executor comments state the invariants, not how they were found.
  - 39 O1: `docs/development/TESTING.md` cites
    `domains/vms/storefront/tests/fixtures/publication_cycle.py`, which exists,
    as its same-package fixture example.
  Evidence for the round fix, all at the fix commit's tree: `make
  check-packaging` passed (fresh wheelhouse, the compute kit rebuilt);
  `make -C provisioning/compute test` — library integration and unit, 236
  passed, the new engine case among them; `make -C provisioning/compute/service
  test` — unit 658 passed, persistence and application integration 527 passed;
  `make -C helm test-render` — chart render passed, 10 provisioning chart
  checks; `make -C e2e-tests test-unit` — 38 passed; repository `make test`
  exited 0 (run before the compliance fixes below, which changed only the
  chart, its render tests, and two service test modules, each re-run above);
  `make check-change` passed. Fresh-context compliance check of the round's
  diff: no comment-hygiene, import, layering, citation, or public-repository
  finding. Fixed: `configFiles` rendered each file under an unquoted key with
  a literal block, which reshaped content and mis-typed some names (now
  `toYaml`, and quoted mounts); the schema accepted `.`, `..`, and `..data`
  (now refused, with a length limit); the documentation named only the
  `.yml` profile names the schema refuses (now both forms); 7.5's docstring
  claimed every setting varies (now the settings that decide pools and a
  job's host); the not-read case proved only that startup continued (now it
  asserts the skip, taken before the seed is opened); no case showed an
  operator's valid seed replacing the packaged one (added, see 8.3); the
  chart's capacity comment named only the packaged seed's pools; the
  concurrent-start note named a unique-key failure SQLite reports as a lock
  (now the outcome alone); 7.5's note overstated what the old code passed;
  D6 still described the engine's old message. The engine's distinct message
  is a diagnostic and needs no promotion row of its own.

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
  Added by implementation review 37's triage, each a row of the record below:
  the seller quickstarts' "List only hosts to sell" lines
  (`docs/seller-quickstart.md:328`, `docs/bare-metal-seller-quickstart.md:55`)
  describe host registration, not selling (37 F2); both quickstarts document
  overriding the seed — by path and an empty `pool_seed_path` under compose,
  and `configFiles` with `config.pool_seed_path` under Helm — and
  `docs/seller-quickstart.md:200`'s fresh-site `default` is rewritten (9.4b);
  the resource-pool-management companion states that one process initializes
  a database, and what a second process starting with it sees (37 F1 / 9.4f).
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
| D2 no derivation from host writes | `openspec/specs/physical-provisioning/spec.md` — "Host writes declare no capacity" (renamed from "Legacy host capacity is derived into declarations"), via archive; `openspec/specs/site-capacity/architecture.md` — the paragraph beginning "The alternatives each left capacity"; `docs/seller-quickstart.md` §6 and `docs/bare-metal-seller-quickstart.md`; `docs/development/ARCHITECTURE.md` — "Authority boundaries", the "Sellable capacity" row; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Capacity definitions" and "What a document does to entries it stops naming", where they speak of declarations derived from host inventory |
| D3 `default` ordinary | `openspec/specs/resource-pool-management/spec.md` — "Non-destructive pool lifecycle", "Strict lossless YAML validation"; `openspec/specs/site-capacity/spec.md` — "Operator-administered capacity declarations"; both via archive |
| D4 seed document and its trigger | `openspec/specs/resource-pool-management/spec.md` — "A fresh site is seeded from its seed document", via archive; `openspec/specs/resource-pool-management/architecture.md` — "Administrative reconciliation", replacing the paragraph beginning "On a fresh database with a mounted pool document"; `docs/development/ARCHITECTURE.md` — "Resource pools", replacing the sentence beginning "A fresh site with a mounted pool document"; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Definition documents", replacing the paragraph beginning "On a first boot with a pool document configured" |
| D4 amendments: a seed read only where it applies (9.4a); overriding the seed by path (9.4b) | `openspec/specs/resource-pool-management/spec.md` — "A fresh site is seeded from its seed document", via archive; `docs/seller-quickstart.md` and `docs/bare-metal-seller-quickstart.md`, overriding or disabling the seed, with `docs/seller-quickstart.md`'s sentence beginning "A fresh site with a mounted pool document" replaced |
| D4 amendment: the chart's `configFiles` (9.4b) | `openspec/specs/deployment-state/spec.md` — "The provisioning chart mounts operator files it gives no meaning", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Kubernetes: ConfigMap and Secret mounting" |
| One process initializes a database (37 F1 / 9.4f) | `openspec/specs/resource-pool-management/architecture.md` — "Administrative reconciliation", beside the seed paragraph |
| Inventory entries register hosts, not sales (37 F2) | `docs/seller-quickstart.md` §3, `docs/bare-metal-seller-quickstart.md` "Define the selected site" |
| D5 optional VM playbook, playbooks frozen at preparation | `openspec/specs/physical-provisioning/spec.md` — "Ansible fulfillment adapter", "Bare-metal inventory binds an existing provider pool", via archive; `openspec/specs/resource-pool-management/architecture.md` — "Provider configuration" |
| D5 a setting belonging to one domain is named for it; `vm_playbook_path`, the refused retired key | `openspec/specs/physical-provisioning/spec.md` — "A domain's service playbook setting is named for its domain", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Profile-based configuration" |
| D6 migration reads no configuration; job-envelope host evidence | `openspec/specs/deployment-state/spec.md` — "Service-owned migration history", via archive; `docs/development/DEPLOYMENT_AND_CONFIG.md` — "Migrations at startup" |
| D7 smoke markers | `docs/development/TESTING.md` — "3. Smoke Tests (Deployment Validation)"; its "Pool Offering-Mode Enforcement" bullet on provisioning migration tests, which names the system-owned default pool |
| Goal 1 gap closed | `docs/development/ROADMAP.md` — Goal 1, open-gap table and current state |
| Campaign status | `openspec/changes/README.md` — Goal 1 campaign |
