# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/55-design-external.triage.md`. Every implementation task answers to a
decision D1–D23, a delta requirement under `specs/`, or a repository obligation
cited at the task: `openspec/README.md#plan-closeout-requirements`, the task
rules in `openspec/config.yaml`, `docs/development/TESTING.md`'s level
definitions, `docs/development/BUILD_AND_PACKAGING.md`, and
`docs/development/RELEASING.md`'s "Versioning policy".

Test levels follow `docs/development/TESTING.md`: unit; library integration (a
kit's service API against a real embedded database); persistence integration (a
service's own migrations against file-backed SQLite, in its `tests/integration`,
without the app); application integration (the in-process app through its typed
clients, raw requests only on the rejection path, asserting statuses and
headers); chart render (`make -C helm test-render`); and system (the
`e2e-tests` markers).

Order: sections 1–26 in number order, then the closeout, 27. Lower layers come
before the layers composing them, except where removing a definition needs its
readers gone first (14 before 15). D1, D2, and D23 are scope, sequencing, and
deltas, and no section implements them; the map at the end says where each
lands.

**Dependency gating implementation.** Sections 10–26 wait for
`unbacked-bare-metal-listings` to land on `dev`, and start from `dev` with it
merged (design D2). Sections 1–9 do not wait. (Amended: by the owner's
decision B in section 9's notes, section 9 waits too, since its test harness
is a file the branch edits.) Each of them names every file it
shares with that change's branch, and why the file merges mechanically. The
partition was derived from the branch at `c6e2108`, compared against its merge
base with `dev`, `73d3760`, and checked against `dev` at `1e5ba29`, after
`pools-7-storefront-fulfillment-cutover`'s closeout landed. Three kinds of
overlap qualify:

- **A version line or a lock.** Both sides bump the package, and the merge keeps
  one bump over its last released version (RELEASING.md's versioning policy).
  Both sides re-derive the lock with `make lock`.
- **A dependency floor raised to a bumped version.** Where both sides raise one
  floor to the same bump, the lines are identical and merge cleanly; otherwise
  the merge keeps the higher floor.
- **A hunk that touches none of the branch's hunks,** with at least one
  unchanged line between them.

A section that finds a shared file this plan does not name, or a hunk that
touches one of the branch's, stops and reports it: whether that work waits for
the branch is D2's rule to apply, not the session's.

**Versions.** A section bumps each package it changes incompatibly by a minor
version and raises a consumer's lower bound only where the consumer needs the
change (RELEASING.md, "Versioning policy"). It bumps a package at most once
across the change. A section that changes a version or a dependency runs
`make lock` and `make check-packaging`.

**Documentation.** Each section corrects the operational text that its own
change makes false, naming the file: a package README, a runbook line, a
quickstart line, a release example. The permanent documents listed in the
design-promotion record are written at closeout (27.9).

## 1. The site ledger's VM target lookup is removed

Delivers the removal of `find_active_lease_by_vm_target` and the unread
`vm_target` reservation-payload key (D21).

Files: `kit/site/src/market_site/ledger.py` (the method at its definition; the
`vm_target` entry of the reservation payload); `kit/site/tests/integration/test_ledger.py`.

Shared with the branch, before it merged: `kit/site/pyproject.toml`'s version
line, and locks.

- [x] 1.1 Remove `CapacityLedgerService.find_active_lease_by_vm_target` and its
  test, `test_find_active_lease_by_vm_target_matches_via_executor_ref`. Remove
  the `vm_target` key from `_reservation_payload`. `executor_target` stays
  (D21).
  Verify:
  - Library integration (`test_ledger.py`): a VM reservation's payload carries
    `executor_target` and no `vm_target`.
  - A repository search finds no caller of the method, and no read of
    `vm_target` from a reservation payload: a site reservation read, a
    `fake_site` reservation, or a ledger answer. `vm_target` is also the name of
    a field of VM's job models, fulfillment requests, operator client, and
    legacy migrations, which this key is not; those matches stay. A reader of
    the reservation key, if one is found, is a design question, since D21
    rests on there being none.

  Done, with `ledger.py`'s now-unread `sqlalchemy.func` import and
  `VM_OFFERING_MODE` constant. Library integration:
  `test_a_vm_reservation_names_its_target_once` passes. The search found no
  caller and no reservation-payload reader of `vm_target`.
- [x] 1.2 Bump `arkhai-kit-site` by a minor version, since a public method is
  removed. Run `make lock`.

  `0.10.1` → `0.11.0`; no floor raised.
- [x] 1.3 **Verification checkpoint.**
  - Library integration: `kit/site`'s `test_ledger.py`.
  - Run `make test` in `kit/site`, `kit/site-client`, and
    `provisioning/compute/service`, which composes the ledger.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: no scenario reads the removed lookup or key, and none is owed.

  `make test`: `kit/site` 289, `kit/site-client` 57, the service 536; full
  `make test` and `make check-packaging` pass. Until closeout, `make
  check-change` failed only on the citation of
  `openspec/specs/introduction-delivery/architecture.md`, which closeout
  creates (27.9); every later checkpoint records the same.

## 2. The mock mechanism's route template, models, and typed client are the family's

Delivers `MockRouteMount`, the mock-rule wire models in the contracts
distribution, the rule route service answering with them, and the family's
`MockRuleClient` and `SyncMockRuleClient` (D14; delta "Compute-owned caller
contract").

Files:
- `provisioning/compute/contracts/src/compute_provisioning_contracts/mock_rules.py`
  (new) and `__init__.py`;
- `provisioning/compute/src/compute_provisioning/jobs/executor_mock.py` (the
  `MockRuleRouteService`);
- `provisioning/compute/client/src/compute_provisioning_client/mock_rules.py`
  (new) and `__init__.py`;
- tests in `provisioning/compute/contracts/tests/unit`,
  `provisioning/compute/client/tests/unit`, and `provisioning/compute/tests/unit`.

Shared with the branch, before it merged: the contracts' `__init__.py` (separate
import blocks), version lines, the client's floor on the contracts, and locks.
The new client has its own module because the branch rewrote `client.py`.

- [x] 2.1 Add `MockRouteMount`, a frozen value of `prefix` and
  `operation_prefix`. Its `route_declarations()` yields the five declarations:
  rule add, rules list, rule delete, rule resume, and job evaluate. Add the
  rule route service's response models beside it (D14).
  Unit (`provisioning/compute/contracts/tests/unit`):
  - `("/test", "provisioning_test")` yields exactly the method, path pattern,
    operation, roles, and `path_resource` of every test entry in today's
    `vm_provisioning_operator/routes.py`.
  - `("/test/bare-metal", "provisioning_test_bare_metal")` yields exactly
    today's `arkhai_bare_metal/provisioning_client.py` entries.

  Equal declarations mean the wire does not change.

  Done in `compute_provisioning_contracts/mock_rules.py`. The mount also
  gives `operation(action)`, `declaration(action)`, and the paths a client
  sends, and refuses a prefix that is not literal path segments. Models:
  `MockRuleCreate`, `MockRuleAdded`, `MockRuleView`, `MockRuleDeleted`,
  `MockRuleResumed`, and `MockJobEvaluation`; the evaluate request stays each
  domain's. Unit (`test_mock_rules.py`, contracts): each mount's declarations
  equal the hand-written entries they replace; both mounts compose into one
  table; every built path resolves to its route; non-literal prefixes are
  refused; the models validate the routes' shapes. Pass.
- [x] 2.2 `MockRuleRouteService` answers with the contracts' models (D14; delta
  `market-composition`, "Compute mock executors share one compute-family
  mechanism"). Unit (`provisioning/compute/tests/unit`, the executor-mock
  suites): every route-service answer validates as its model.

  Unit (`test_executor_mock.py`): add, list, delete, and resume each return
  their model. Plan correction (`design.md`, Implementation record): both
  adapters' rule routes in `controllers/test_controller.py` declare the
  family's models here, and both adapters take their one bump of the change
  here, raising their floor on the contracts to `0.10.0`: the VM adapter
  `0.13.1` → `0.14.0`, the bare-metal adapter `0.9.2` → `0.10.0`.
- [x] 2.3 Add `MockRuleClient` and `SyncMockRuleClient`. Each is constructed over
  the family client's authenticated transport with a `MockRouteMount`. Each
  method signs from the mount's declarations and returns the family's models
  (D14).
  Unit (`provisioning/compute/client/tests/unit`):
  - For both mounts, each method sends its path and signs its operation.
  - Answers parse into the models.
  - The sync and async clients have the same public methods and signatures
    (TESTING.md, "Sync/async client parity").

  Done in `compute_provisioning_client/mock_rules.py`; `evaluate_job` takes
  the job as a mapping. Unit (`test_mock_rules.py`, client): the real async
  and sync family clients, over an `httpx.MockTransport` that resolves and
  verifies each request against the mount's table, send each call's method,
  path, operation, and resource for both mounts, and every answer parses into
  its model; the parity test compares the two classes. Pass. The service's
  parity guardrail gained the pair in 3.3.
- [x] 2.4 Bump `arkhai-compute-provisioning-contracts`,
  `arkhai-compute-provisioning-client`, and `arkhai-compute-provisioning` by a
  minor version each, since the route service's answers change type. Run
  `make lock`.

  Contracts `0.9.1` → `0.10.0`; client `0.7.0` → `0.8.0`; family kit `0.19.1`
  → `0.20.0`; the client's and the family kit's floors on the contracts at
  `0.10.0`.
- [x] 2.5 **Verification checkpoint.**
  - Unit: 2.1–2.3.
  - Run `make test` in `provisioning/compute/contracts`,
    `provisioning/compute/client`, and `provisioning/compute`.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  Application integration is section 3's, where the template is mounted.

  End-to-end: none, since nothing mounts the template yet. No scenario is owed.

  `make test`: contracts 71, client 63, family kit 237, the service 536, the
  VM adapter 37, the bare-metal adapter 46; full `make test` and `make
  check-packaging` pass.

## 3. Each compute domain mounts the family's mock mechanism

Delivers VM's and bare metal's mock routes from the family's template. Bare
metal's declarations are reduced to its two mount values. The service's
integration harness calls the family client (D14). Deltas:
- "Compute-owned caller contract": the scenarios "A test reads a mock rule
  through the family client" and "A compute domain mounts the mock mechanism";
- `market-composition`: the scenario "Two adapters' rule routes answer one
  shape".

Files:
- `domains/vms/provisioning/client/src/vm_provisioning_operator/routes.py`;
- `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/controllers/test_controller.py`
  and `models/system_model.py`, whose VM-owned mock-rule models are removed;
- `domains/bare_metal/src/arkhai_bare_metal/provisioning_client.py`, renamed to
  `provisioning_routes.py`, and `arkhai_bare_metal/__init__.py`, which imports
  and exports `BARE_METAL_PROVISIONING_ROUTES` from it;
- `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/routers.py`
  and `controllers/test_controller.py`;
- in `provisioning/compute/service/tests/integration`: `conftest.py`,
  `test_test_controller.py`, `test_bare_metal_mock_profile.py`,
  `test_system_api.py` (its `TestEvaluateJob` only), and
  `test_provisioning_client_endpoint_coverage.py` (its
  `TestBareMetalTestRouteCoverage` only, which compares the rule answers with
  dictionaries). `test_lease_release_api.py` calls the conftest's bare-metal
  rule methods and discards their answers, so it needs no edit.
- Added by the owner's decision B: `e2e-tests/src/e2e_harness/provisioning_test_client.py`
  and `e2e-tests/pyproject.toml` (`design.md`, Implementation record).

Shared with the branch, before it merged: version lines, floors, and locks;
`arkhai_bare_metal/__init__.py`, `test_system_api.py`, and
`test_provisioning_client_endpoint_coverage.py` in hunks apart from the
branch's; and, by decision B, one adjacent line of `e2e-tests/pyproject.toml`.

- [x] 3.1 VM's `routes.py` replaces its hand-written test entries with
  `MockRouteMount("/test", "provisioning_test").route_declarations()`. VM's test
  controller answers with the family's models. VM's own mock-rule models in
  `models/system_model.py` are removed (D14).
  Unit (`provisioning/compute/service/tests/unit/test_route_binding.py` and
  `test_route_table_composition.py`):
  - every mounted route resolves to exactly one contract;
  - every contract resolves to a mounted route;
  - VM's paths and operations are unchanged.

  The mount is `vm_provisioning_operator.VM_MOCK_ROUTE_MOUNT`; VM's test
  controller takes its prefix from it, reads `MockRuleCreate`, and answers
  `MockJobEvaluation`. `EvaluateJobResponse` is removed; `EvaluateJobRequest`
  stays. Unit: the binding tests pass over the app with the mock profile
  active; new
  `test_each_domain_contributes_its_mock_routes_from_the_family_template` and
  `test_vm_mock_routes_are_served_at_their_signed_paths_and_operations`. Pass.
- [x] 3.2 Rename bare metal's `provisioning_client.py` to `provisioning_routes.py`
  and reduce it to bare metal's two mount values. The bare-metal adapter builds
  the mount from them and contributes its declarations (D14).
  Verify:
  - `make check-architecture` passes with `arkhai-bare-metal` declaring no
    compute dependency.
  - The adapter's route contracts equal the mount's declarations, which 3.1's
    binding tests check.

  The values are `BARE_METAL_MOCK_ROUTE_PREFIX` and
  `BARE_METAL_MOCK_OPERATION_PREFIX`, exported in place of
  `BARE_METAL_PROVISIONING_ROUTES`; the adapter's test controller builds
  `BARE_METAL_MOCK_ROUTE_MOUNT` from them, and its controller reads
  `MockRuleCreate` and answers `MockJobEvaluation`.
  `domains/bare_metal/tests/test_provisioning_routes.py` asserts the values.
  `make check-packaging` passes with `arkhai-bare-metal` declaring no compute
  dependency. By decision B, the e2e harness builds bare metal's signing table
  from a `MockRouteMount` of those values, and `e2e-tests/pyproject.toml`
  raises the contracts (`0.10.0`), client (`0.8.0`), and `arkhai-bare-metal`
  (`>=0.13.0`) floors; collecting the VM and bare-metal scenarios imports
  every module (178 tests).
- [x] 3.3 The service integration harness calls the family client for rules and
  job evaluation. In `conftest.py`, `AsyncProvisioningTestClient`'s rule and
  evaluate-job methods go through `MockRuleClient` with each domain's mount. The
  shared `/test/jobs/*` drain and wait stay where they are (D14; TESTING.md's
  "no raw calls" rule).
  Application integration (`test_test_controller.py`,
  `test_bare_metal_mock_profile.py`, and
  `test_provisioning_client_endpoint_coverage.py`'s
  `TestBareMetalTestRouteCoverage`):
  - Rules are installed, listed, resumed, and deleted, and jobs evaluated,
    through the family client under both mounts. Each answer is the family's
    typed model.
  - A VM rule matches only VM jobs.

  Amended in section 2, which typed the adapters' rule-route answers and
  left this work here:
  - Both adapters' rule-add routes read the family's `MockRuleCreate` in
    place of their own request models (VM's `MockRuleRequest`, bare metal's
    `BareMetalMockRuleRequest`), and both evaluate routes answer the family's
    `MockJobEvaluation`. `MockRuleRouteService.add` then takes only a
    `MockRuleCreate`: its mapping form exists only for the adapters' current
    request models.
  - `provisioning/compute/service/tests/unit/test_provisioning_client_contract.py`
    adds the `MockRuleClient`/`SyncMockRuleClient` pair to its sync/async
    parity guardrail (TESTING.md, "Sync/async client parity").

  Done. `AsyncProvisioningTestClient` holds `vm_rules` and
  `bare_metal_rules` `MockRuleClient`s; only the `/test/jobs/*` reads stay
  its own requests. Application integration, through the family client:
  `TestMockRuleCrud`, new `test_a_vm_rule_holds_a_vm_job_until_resumed`,
  `test_bare_metal_mock_profile.py` with new
  `test_a_rule_installed_through_vms_mount_is_not_bare_metals`,
  `TestBareMetalTestRouteCoverage`, and `TestEvaluateJob`'s new
  `test_the_answer_states_every_field`. Rules installed through one mount are
  in that domain's rule set only; that a VM rule never meets a bare-metal job
  follows from each adapter's mock owning its rule set and is not exercised
  at the job level. The parity guardrail includes the pair. Service: unit
  661, application integration 538.
- [x] 3.4 Bump `arkhai-bare-metal` by a minor version, since the module is
  renamed. Bump the VM and bare-metal adapters and the VM operator client.
  Raise the service's `dev` floor on the client to section 2's bump. Run
  `make lock`.

  Amended in section 2: both adapters took their bump there (VM `0.14.0`,
  bare metal `0.10.0`), so this task does not bump them again.

  `arkhai-bare-metal` `0.12.0` → `0.13.0`; VM operator client `0.9.1` →
  `0.10.0`. Floors raised where a consumer needs this section's change: both
  adapters on `arkhai-compute-provisioning>=0.20.0`, the VM adapter on the
  operator client `>=0.10.0`, the bare-metal adapter on `arkhai-bare-metal>=0.13.0`,
  and the service's `adapters` extra and `dev` floors. No service bump: its
  runtime code is unchanged.
- [x] 3.5 **Verification checkpoint.**
  - Unit: 3.1 and 3.2.
  - Application integration: 3.3.
  - Run `make test` in `domains/vms/provisioning/client`,
    `domains/vms/provisioning/adapter`, `domains/bare_metal`,
    `domains/bare_metal/provisioning/adapter`, and
    `provisioning/compute/service`.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: these scenarios install mock rules through the e2e harness, which
  signs the unchanged paths and operations:
  - `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_listing_shapes`, and
    `e2e_non_erc20_settlement`;
  - `e2e_bare_metal_mock_deal`.

  Passing lanes are the evidence that the wire did not change. No scenario is
  owed.

  `make test`: the VM adapter 37, `domains/bare_metal` 133, the bare-metal
  adapter 46, the service 661 and 538, the family kit 237;
  `domains/vms/provisioning/client` has no suite, its declarations tested
  through the service. Full `make test` and `make check-packaging` pass. The
  bare-metal lane is also the evidence that the harness's table, built from
  bare metal's mount, signs as the service authenticates.

## 4. An operator-named VM guest satisfies provisioning's naming rules

Delivers the check of an operator's guest name, and a 422 answer when it fails
(D17; delta "An operator-named VM guest satisfies provisioning's naming
rules").

Files:
- `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/controllers/vms_controller.py`
  and the adapter service behind it;
- `guest_names.py` (`check_guest_name`);
- `domains/vms/provisioning/iac/README.md` (the sentence saying a direct VM
  operation's name "is not checked");
- tests.

Shared with the branch, before it merged: the VM adapter's version line, and
locks.

- [x] 4.1 VM's operator `create_vm` checks the guest name with
  `check_guest_name` in the adapter's service, before anything is prepared or
  submitted, and answers 422 naming the rule (D17).
  - Unit:
    - a name that is not a hostname label is refused;
    - a login that, stripped to letters and digits, exceeds 32 characters or
      starts with a digit is refused;
    - provisioning's own generated names pass.
  - Application integration, through the typed VM operator client: an over-long
    login is refused with 422, and no job is submitted.

  `VmOperationsService.create_vm` runs `check_guest_name` first and raises
  `ProvisioningRouteError(422, …)`; the VMs controller answers it through
  `route_binding.routed_async`. Only create is checked.
  - Unit (VM adapter `tests/unit/test_guest_names.py`, new): each rule's
    refusals, the 32-character login and 63-character label limits, and
    provisioning's generated names.
  - Unit (service `test_vm_operations_service.py`, which stays in the service):
    a 33-character login is refused with 422 and nothing is submitted.
  - Application integration (`test_vms_api.py`, `TestCreateVmViaClient`, on a
    registered host):
    `test_a_guest_name_the_playbooks_refuse_is_refused_before_any_job`.

  All pass.
- [x] 4.2 Correct the IaC README: an operator's guest name is checked against
  the same rules (D17).

  `domains/vms/provisioning/iac/README.md`, "Guest names", and
  `guest_names.py`'s docstring say so.
- [x] 4.3 Bump the VM adapter, unless section 3 already did, and run
  `make lock`. **Verification checkpoint:**
  - unit and application integration, 4.1;
  - `make test` in `domains/vms/provisioning/adapter` and
    `provisioning/compute/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: no scenario creates an operator-named VM. No scenario is owed: the
  check is one authority's validation, which application integration owns.

  No bump (section 2). `make test`: VM adapter 55, the service 662 and 539;
  full `make test` and `make check-packaging` pass.

## 5. VM's tables: suites in the VM adapter, the relay index on its model

Delivers:
- the VM-owned suites, moved into the VM adapter with a VM schema fixture;
- `uq_relay_port_leases_active_owner`, declared on VM's model;
- confirmation that `database.py` no longer claims to import without the
  adapters (D20, D6).

Task 5.3 was replanned against `dev` at `1e5ba29`: the closeout of
`pools-7-storefront-fulfillment-cutover` moved `database.py`'s metadata imports,
VM's included, to module level and removed the comment D6 corrects, so no code
change remains for it.

Files:
- **Moved from `provisioning/compute/service/tests/`:**
  - from `integration/`: `test_relay_administration.py` (all but
    `TestTheDigestGate`, which stays), `test_relay_port_allocator.py`,
    `test_relay_port_leases.py`, and `test_ansible_pool_config_handler.py`;
  - from `unit/services/`: `test_vm_codec.py`.
- **Their destination:** `domains/vms/provisioning/adapter/tests/{integration,unit}/`.
- **The index:** VM's `relay_port_leases` model in the VM adapter.
- **Configuration:** the VM adapter's `pyproject.toml` (`pyyaml` in its `dev`
  group).
- **Read, not changed:**
  `provisioning/compute/service/src/compute_provisioning_service/db/database.py`.

Shared with the branch, before it merged: the VM adapter's `pyproject.toml`, in
lines apart from the branch's, and locks.

- [x] 5.1 Declare the partial unique index `uq_relay_port_leases_active_owner` on
  VM's `relay_port_leases` model, so that a schema built from the models has it.
  Service migration `20260901_001` still creates it where it is absent (D20).
  - Library integration (adapter): over the VM schema fixture, two retries
    taking a port for one owner hold one relay port.
  - Persistence integration (service): a database migrated from before
    `20260901_001` gains the index. A fresh database, created from the models,
    migrates without error.

  `RelayPortLease.__table_args__` declares the index (unique, partial on
  `released_at IS NULL`). Tests, all passing:
  - Library integration, VM adapter, `test_relay_port_leases.py`
    `TestOneActiveLeasePerOwner`: two uncommitted leases for one owner on
    different ports, the second commit refused; a released lease does not
    hold its owner. Rows are written directly, so this shows the database's
    refusal, not the allocator's.
  - Persistence integration, service, new `test_relay_migrations.py`
    `TestTheActiveOwnerIndex`: `test_a_lease_table_lacking_the_index_gains_it`
    (a constructed state, since no recorded history holds the table without
    the index) and `test_a_fresh_database_created_from_the_models_migrates`.
- [x] 5.2 Move the suites listed above into the VM adapter, over a VM schema
  fixture built from VM's models. `TestTheDigestGate` stays in the service,
  since it tests the service's importer (D20).
  Verify:
  - the moved suites pass under `make test` in
    `domains/vms/provisioning/adapter`, whose target runs both `unit/` and
    `integration/`;
  - the service suite no longer contains them.

  Moved with `git mv`; the adapter's new `tests/integration/conftest.py`
  builds the resource-pool tables and VM's metadata on file-backed SQLite.
  Plan corrections (`design.md`, Implementation record): `pyyaml` is a
  runtime dependency of the adapter; `TestMigrations` stays in the service
  with `TestTheDigestGate`, as `test_relay_migrations.py` and
  `test_definition_document_digest.py`. `make test` in the adapter: 256
  passed; the service: unit 570, application integration 434. Other suites
  testing VM-adapter code from the service's tree stay, as D20 names them
  not. `physical-provisioning`'s Evidence section is rewritten at closeout
  (27.9).
- [x] 5.3 Confirm that `database.py` imports VM's metadata at module level and
  that no comment in it or in `db/migrations.py` still says the module imports
  without the adapters, or that the VM adapter is optional to it (D6). No code
  change is expected; if such a comment is found, rewrite it to say that the
  service's database holds VM's tables, so its metadata and migration history
  name them. The rationale is promoted at closeout (27.9).

  Confirmed; no change.
- [x] 5.4 **Verification checkpoint.**
  - Library and persistence integration: 5.1.
  - Run `make test` in `domains/vms/provisioning/adapter` and
    `provisioning/compute/service`.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: the VM lane's deals take relay ports through the composed service
  on a freshly migrated database (`e2e_deal`, `e2e_deal_buyer_cli`). No scenario
  is owed.

  `make test`: VM adapter 256, the service 570 and 434; full `make test` and
  `make check-packaging` pass. No bump: the index is one the service's
  migration already creates, and the adapter was bumped in section 2. A
  latent relay-allocator defect found here is recorded in `design.md`'s
  Implementation record for whichever change next touches relay allocation.

## 6. `kit/policy` carries no training tooling, and its refusals name the right things

Delivers:
- the removal of the `market-policy` console script and its training
  dependency settings (D7);
- the policy chain's refusal messages (D18).

Files:
- `kit/policy/pyproject.toml`: the console script, the description's CLI
  clause, the `training` dependency group, and the `[tool.uv]` pufferlib build
  settings and CPU torch index;
- `kit/policy/src/market_policy/cli.py` (removed) and any test of it;
- `kit/policy/src/market_policy/negotiation_middleware.py` (the empty-chain and
  unknown-name refusals);
- `domains/vms/training/README.md`;
- `docs/development/RELEASING.md` (the console-script examples sentence).

Shared with the branch, before it merged: `kit/policy`'s version line beside
the description this section edits, `RELEASING.md` in separate paragraphs, and
locks. Sections 6–8 bump no version, by the owner's decision A (`design.md`,
Implementation record).

- [x] 6.1 Remove from `kit/policy` everything design D7 lists. `typer` stays, for
  `buyer_policy.py`. The removed material is already carried verbatim in
  `repair-rl-training-tooling`'s `removed-tooling.md`. Compare it with what is
  removed, and record any difference there (D7).
  Verify:
  - `kit/policy`'s built wheel has no `market-policy` entry point and no `cli`
    module.
  - Its lock no longer resolves pufferlib or the CPU torch index.
  - A repository search for `market-policy` finds only
    `repair-rl-training-tooling`'s records.

  Done; `removed-tooling.md` matched what was removed, so nothing was
  recorded there. The rebuilt wheel has no `cli.py` and no
  `entry_points.txt`; `kit/policy/uv.lock` names neither pufferlib nor torch.
  The search finds only `repair-rl-training-tooling`'s records and this
  change's.
- [x] 6.2 Cut `domains/vms/training/README.md` down to what exists (D7). Verify
  that every path and target it names exists.

  Rewritten: the directory is scripts and configurations, not a project; it
  lists the training scripts and configurations and the inference path (the
  committed checkpoints, `ArkhaiInferencePolicy`, `torch_arkhai_strategy.py`,
  the path-override and slot-layout variables under their real names and
  defaults, the `rl` extras, and `validate-model-release.yml`). Every path it
  names exists; it names no Make target. Also corrected: `eval_arkhai.py`'s
  docstring and `docs/development/BUILD_AND_PACKAGING.md`'s list of projects
  declaring the PyTorch CPU index.
- [x] 6.3 Drop `market-policy` from `RELEASING.md`'s console-script examples
  (D7).

  The sentence now names `market` and `market-storefront`.
- [x] 6.4 The empty-chain refusal names `[negotiation].policies`. The
  unknown-name refusal says that built-ins are always registered and that
  extensions come from the `market_policy.negotiation_middlewares` entry-point
  group (D18). Unit (`kit/policy/tests/unit`): each refusal's message.

  Done in `load_negotiation_chain`. "Always registered" rests on composition:
  every caller imports `market_policy.scalar_policies`, directly or through a
  domain module, at module level. Unit (`test_negotiation_strategy.py`): the
  unknown-name refusal's two sentences, and new
  `test_an_empty_chain_is_refused_naming_the_policies_setting`. Pass.
- [x] 6.5 Bump `arkhai-kit-policy` by a minor version, since the console script
  is removed. Run `make lock`.

  Amended by the owner's decision A (above): no bump here. The branch bumps
  `arkhai-kit-policy` to `0.6.0` with `kit/negotiation-runtime`'s pin, and
  section 10 confirms the bump once the branch has merged. `make lock` ran for
  the removed settings and changed `kit/policy/uv.lock` alone.
- [x] 6.6 **Verification checkpoint.**
  - Unit: 6.4.
  - Run `make test` in `kit/policy` and in the VM and bare-metal storefronts,
    which compose its chain.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: every storefront composes the chain at startup, and no scenario
  meets a refusal. No scenario is owed.

  `make test`: `kit/policy` 82, the VM storefront 1103 and 449, the
  bare-metal storefront 444, the API-credit storefront 184, the core buyer
  141, `kit/negotiation-runtime` 61; `make check-packaging` passes. Stale
  texts outside this section's files are listed in `design.md`'s
  Implementation record.

## 7. An introduction's seller-side delivery is claimed once

Delivers the seller-dispatch claim and the claim-taking start (D9; delta
"Delivery fires once per reveal and re-delivery is explicit"). The claim is a
row in its own table, which a migration creates empty. Only the start that
completes the reveal and wins the claim dispatches. A failed start's 503 says
to start again.

Files:
- `kit/contact-exchange/src/market_contact_exchange/store.py`, `migrations.py`,
  `introduction_routes.py`, and `composition.py`;
- `kit/contact-exchange/tests/unit/test_introduction_routes.py`;
- `kit/contact-exchange/tests/integration/test_composition.py` and
  `test_migrations.py`;
- `domains/vms/storefront/tests/integration/test_introduction_delivery_claim.py`
  (new).

Shared with the branch, before it merged: `kit/contact-exchange/pyproject.toml`'s
version line, and locks.

- [x] 7.1 Add the seller-delivery claim table, keyed by the introduction's
  obligation reference, with an insert that succeeds for exactly one caller. Add
  a migration that creates the table empty (D9).
  `contact_introductions_redaction_only` is untouched.
  - Library integration (`test_composition.py`): two independent sessions claim
    one introduction, and exactly one succeeds. The redaction trigger still
    refuses every update but the redaction.
  - `test_migrations.py`: a fresh database and a rerun are covered.

  Migration `20261027_008_contact_introduction_seller_dispatch_claims`
  creates `contact_introduction_seller_dispatches` (`obligation_ref` primary
  key, `claimed_at`), empty; `claim_seller_dispatch` is an `INSERT OR IGNORE`
  answering whether it inserted, exported with the migration ID. Both
  storefronts' chains include it through `CONTACT_EXCHANGE_MIGRATIONS`.
  Library integration (`test_composition.py`): an uncommitted claim locks a
  second connection out, a committed one wins, a rolled-back one leaves the
  introduction claimable; four concurrent claims have one winner; after a
  reveal the claim row exists and the redaction trigger and retention still
  hold. `test_migrations.py`: a fresh database, a rerun, and a database from
  the earlier migrations. All pass.
- [x] 7.2 `IntroductionRouteService.start` claims once completion succeeds, and
  only the start that wins schedules the seller's delivery. A failed claim write
  answers 503. A failed start's 503 detail says that starting the introduction
  again completes it (D9).
  Unit (`test_introduction_routes.py`), one case for each of the delta's
  scenarios:
  - an exact replay;
  - a first completion that failed, then a new start;
  - a failed start replayed exactly, which answers its recorded 503;
  - two concurrent completing starts;
  - repeated starts after a completed reveal;
  - deletion committing while a start completes, where the start still
    dispatches its one claimed delivery;
  - re-delivery of a deleted introduction, which is refused.

  `IntroductionRouteCallbacks` gains a required `claim_seller_dispatch`;
  after persist and completion `start` claims, and only a won claim delivers.
  A failed completion or claim write answers 503 with
  `INTRODUCTION_COMPLETION_UNAVAILABLE`, ending "starting the introduction
  again completes it". Unit: each listed case, and a claim write failing once.
  Re-delivery is the composition's (`load_revealed`/`seller_view`); its
  refusal of a deleted introduction is the existing
  `test_redelivery_reads_the_durable_reveal_and_stops_after_deletion`. All
  pass.
- [x] 7.3 Application integration (`test_introduction_delivery_claim.py`, through
  the VM storefront's typed introduction clients, with completion failing once
  at an injected collaborator):
  - the first start answers 503 and names starting again;
  - the buyer's next start completes the reveal, and the seller's recording
    sink receives exactly one dispatch;
  - further starts dispatch nothing;
  - the operator's explicit re-delivery still sends.

  `test_an_interrupted_reveal_is_delivered_to_the_seller_once`, on the VM
  full-app harness over loopback through the buyer's `IntroductionTransport`,
  the settlement runtime wrapped so its first `collect` fails: each listed
  case holds. Passes.
- [x] 7.4 Bump `arkhai-kit-contact-exchange` by a minor version, since its schema
  and the start's answer change. Run `make lock`.

  Amended by the owner's decision A (section 6's notes): no bump here. The
  branch bumps `arkhai-kit-contact-exchange` to `0.4.0` with the four exact
  pins on it, and section 10 confirms the bump once the branch has merged. No
  dependency changed, so no lock did; `make check-packaging` confirms every
  lock current.
- [x] 7.5 **Verification checkpoint.**
  - Unit, library integration, and application integration: 7.1–7.3.
  - Run `make test` in `kit/contact-exchange`, `kit/delivery`, and the VM and
    bare-metal storefronts.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: `e2e_vm_introduction` and `e2e_bare_metal_introduction` reveal an
  introduction and deliver it once on the seller's side, so they prove the claim
  does not stop an ordinary first delivery. Neither fails a completion. No
  scenario is owed: the interrupted reveal is one storefront's transaction,
  which library and application integration own.

  Corrected: only `e2e_vm_introduction` observes seller-side delivery (its
  `test_05` finds one Mailpit message), so it is the evidence that a first
  start still claims and delivers; `e2e_bare_metal_introduction` reveals
  through the claim-taking start but observes no sink.

  `make test`: `kit/contact-exchange` 141, `kit/delivery` 66, the VM
  storefront 1103 and 450, the bare-metal storefront 444, the VM buyer 202,
  the bare-metal buyer 15; `make check-packaging` passes. Round 1's
  validation (66 V1) failed `e2e_vm_introduction`'s `test_04` on an inherited
  command collision (`design.md`, Implementation record); validation 94 passed
  the VM lane with `dev` merged. Left for closeout's documentation compliance
  (27.3): `contact-exchange-settlement`'s scenario "A deletion overlaps a
  start that has already revealed" says the start "delivers it if it is the
  first reveal", while the deliverer is the start that claims.

## 8. The VM storefront's senderless fulfillment callbacks are removed

Delivers the removal of `started`, `usage-started`, `release-started`, and
`failed`, with their models, client methods, operation-map and OpenAPI entries,
tests, and e2e stage. The failure policy and `capacity-released` stay (D4;
delta "Deal-scoped lifecycle events").

Files:
- in `domains/vms/storefront/src/market_storefront/`:
  `controllers/admin_controller.py` (the four routes and their imports),
  `models/capacity_admin_models.py` (the four request models), and
  `middleware/service_peer_auth.py` (`_CALLBACK_OPERATIONS`);
- `core/storefront/src/core_storefront/openapi.py` (the callback set);
- `core/storefront-client/src/storefront_client/client.py` (`notify_usage_started`
  and `notify_fulfillment_failed`, async and sync);
- in `domains/vms/storefront/tests/`: `integration/test_admin_api.py` (the
  callback cases), `unit/test_service_peer_identity.py`, and
  `unit/test_capacity_admin_models.py`;
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_compute_dynamic_listings.py`;
- `docs/configuration.md` (the failure policy described as the pull path's).

Shared with the branch, before it merged: `admin_controller.py`,
`storefront_client/client.py`, `test_compute_dynamic_listings.py`, and
`docs/configuration.md`, each in hunks apart from the branch's (see `design.md`,
"Implementation cadence"); version lines and locks.

- [x] 8.1 Remove the four routes, their request models, their operation-map
  entries, and their OpenAPI callback entries. Keep `capacity-released`,
  `_apply_fulfillment_event`, and `apply_fulfillment_failure_policy`, with its
  unit and pull-path tests (D4). Remove code that only the removed routes
  reached. One example: `_apply_fulfillment_event`'s `close_oversized` path,
  which only they set. `_close_oversized_compute_listings` stays, because
  `reserve_capacity` calls it.
  - Unit:
    - `test_service_peer_identity.py`: the operation map names only
      `capacity-released`;
    - the OpenAPI callback set lists only it;
    - `test_capacity_admin_models.py` covers the remaining models.
  - Application integration (`test_admin_api.py`, typed `StorefrontClient`):
    `capacity-released` still records the release and reopens the listings it
    closed.

  Removed: the four routes, their request models, their operation-map and
  OpenAPI entries, and `_apply_fulfillment_event`'s flags only they set; it
  now releases, reopens, and records the `capacity_released` stage event.
  The failure policy and its pull-path callers are untouched;
  `core/storefront-client/README.md` names the one callback.
  - Unit: `test_service_peer_identity.py` (the map is exactly
    `capacity-released`), `test_capacity_admin_models.py`, and new
    `test_openapi_callback_roles.py` (in the VM storefront, since
    `core/storefront` does not install FastAPI for its tests), which mounts the
    real admin router and finds `capacity-released` the only fulfillment-event
    path.
  - Application integration: `test_capacity_released_releases_and_reopens`
    reserves through the typed admin reserve, releases through the typed
    service client, and sees the listings reopen and the units returned.

  All pass.
- [x] 8.2 Remove `notify_usage_started` and `notify_fulfillment_failed` from
  both storefront client classes (D4). Verify:
  - the storefront client's sync/async parity test passes;
  - a repository search finds no caller.

  Removed; the parity test passes and the search finds neither name.
- [x] 8.3 Remove the e2e stage that tests `usage-started` itself:
  - `test_03_usage_started_keeps_oversized_listings_closed`;
  - the `usage_started` field, and `test_04`'s requirement on it;
  - the module docstring's "Mark usage started" step.

  `test_04` now follows the reserve stage (D4). Verify: `make -C e2e-tests
  test-unit` passes, including the stage-set check.

  Done. The e2e unit suite passes (80); collecting the module finds its nine
  stages without `test_03`.
- [x] 8.4 `docs/configuration.md` describes the failure policy as the pull
  path's, run when the storefront reads a failed fulfillment (D4).

  The failure-policy section says the VM storefront runs the policy when
  settlement's provisioning step fails to start a fulfillment and when the
  resume loop reads a failed one, and that capacity-released is the
  provisioning service's only callback.
- [x] 8.5 Confirm the sender's side of "Deal-scoped lifecycle events". In
  `services/deal_event_sink.py`, the provisioner derives the notification's
  request identity from the release's event identity and retries it from its
  outbox until acknowledged. Confirm that
  `provisioning/compute/service/tests/unit/services/test_deal_event_sink.py` and
  `test_capacity_release_outbox.py` cover the delta's three scenarios:
  - one notification for a released reservation;
  - a resend under the same request identity after a lost acknowledgement;
  - no notification for a usage-ready transition.

  Add any missing case. No production change is expected. If one is needed, it
  is a design question, not a task (D4).

  Confirmed, no production change: one notification
  (`test_release_event_uses_service_signer_site_and_storefront_pin`); the
  resend (`test_uncertain_ack_retry_reuses_the_same_client_and_request_identity`
  and `test_capacity_release_outbox.py`); and, added,
  `test_the_sink_sends_nothing_for_an_event_other_than_capacity_release`. That
  no other transition reaches the sink is read from the code. The delta's
  clause on the full storefront client was dropped by round 1's triage
  (65 F1; `design.md`, Implementation record).
- [x] 8.6 Bump the VM storefront, `arkhai-core-storefront`, and
  `arkhai-core-storefront-client` by a minor version each, since routes and
  public methods are removed. Run `make lock`.

  Amended by the owner's decision A (section 6's notes): no bump here. The
  branch bumps `arkhai-vms-storefront` to `0.22.0`,
  `arkhai-core-storefront` to `0.16.0`, and `arkhai-core-storefront-client`
  to `0.27.0`, with the exact pins on them, and section 10 confirms the bumps
  once the branch has merged. No dependency changed, so no lock did; `make
  check-packaging` confirms every lock current.
- [x] 8.7 **Verification checkpoint.**
  - Unit and application integration: 8.1–8.2.
  - Run `make test` in `domains/vms/storefront`, `core/storefront`,
    `core/storefront-client`, and `provisioning/compute/service`.
  - Run `make -C e2e-tests test-unit`, `make check-packaging`, and
    `make check-comment-hygiene`.

  End-to-end:
  - `e2e_compute_dynamic_listings` reserves capacity, then releases it through
    `capacity-released` and sees the closed listings reopen.
  - `e2e_deal` and `e2e_deal_buyer_cli` release through the provisioner's own
    capacity-released callback.

  Together they are the evidence that the surviving callback works and that
  nothing calls the removed ones.

  `make test`: the VM storefront 1108 and 446, `core/storefront` 217,
  `core/storefront-client` 62, the service 572 and 434, the e2e unit suite
  80; `make check-packaging` and `make check-comment-hygiene` pass. Left for
  closeout's promotion (27.9): `ARCHITECTURE.md`, "Site authority", which
  says deal-scoped fulfillment events are pushed with their deal context,
  while one notification, capacity-released, is pushed. Other follow-ups are
  in `design.md`'s Implementation record.

## 9. VM binds pool overrides at `POOL_OVERRIDES_PATH`

Delivers VM's pool-override routes on an unprefixed router bound at the kit's
`POOL_OVERRIDES_PATH`, as the bare-metal storefront binds them (D16).

Files: `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`
(the three pool-override routes) and `server.py` (the controller imports and the
`StorefrontRouteHooks` routers tuple); added by the owner's decision B,
`domains/vms/storefront/tests/publication_app.py` (its router list) and
`domains/vms/storefront/tests/unit/test_pool_override_routes.py`.

By the owner's decision B (`design.md`, Implementation record), this section
waited for `unbacked-bare-metal-listings` and was implemented in round 2 from
`dev` with the branch merged, so nothing was shared with it.

- [x] 9.1 Move the pool-override routes to a router with no prefix, declared at
  `POOL_OVERRIDES_PATH`, and mount it in the routers tuple (D16).
  Verify:
  - Application integration: `test_pool_overrides_api.py`, through the typed
    `SyncPoolOverrideClient`, passes unchanged.
  - Unit: the mounted path equals `POOL_OVERRIDES_PATH`, and the
    administrator-identity middleware's contract for it is unchanged.

  `admin_controller.py` declares `pool_overrides_router`, unprefixed, and a
  `PoolOverrideController` whose three routes, moved unchanged, are declared
  at `POOL_OVERRIDES_PATH`; `server.py` and `tests/publication_app.py` list
  it after `admin_router`.
  - Application integration: `test_pool_overrides_api.py`, unchanged, passes
    (it uses the async `PoolOverrideClient`, not the sync one).
  - Unit (new `test_pool_override_routes.py`): `server.app` mounts PUT, GET,
    and DELETE once each at `POOL_OVERRIDES_PATH` and no other
    `/pool-overrides` route; it fails with the router dropped.
  - Unit: `test_identity_dispatch.py`'s three pool-override tests, unchanged,
    pin the middleware's contract and pass.
- [x] 9.2 **Verification checkpoint.**
  - Application integration: 9.1.
  - Run `make test` in `domains/vms/storefront` and `make check-comment-hygiene`.

  End-to-end: `e2e_compute_dynamic_listings` and `e2e_listing_shapes` write pool
  overrides through the typed client. A passing lane is the evidence that the
  path is unchanged.

  `make test` in the VM storefront: 1138 and 475; full `make test`, `make
  check-comment-hygiene`, and `make check-packaging` pass. `e2e_vm_introduction`
  also writes an override through `SyncPoolOverrideClient`.

## 10. A site authority answers an unroutable request by what failed to match

Waits for `unbacked-bare-metal-listings` (D2). Delivers `kit/site`'s answers by
cause, and the site client's report of an unauthenticated answer (D3; delta
`site-capacity`, "A site authority answers an unroutable request by what failed
to match").

Files:
- `kit/site/src/market_site/auth.py` (`resolve_site_route` and the middleware's
  resolution failure);
- `kit/site-client/src/market_site_client/client.py` (its response
  verification);
- `kit/site/tests/integration/test_site_auth_middleware.py`;
- `kit/site-client/tests/unit/test_client.py`;
- `domains/apicredits/service/tests/integration/test_signed_authority.py`.

Amended by the owner's decision A (section 6's notes): sections 6–8 bumped no
version, leaving each bump to the branch's. Before 10.1, with the branch
merged, confirm that `arkhai-kit-policy`, `arkhai-kit-contact-exchange`,
`arkhai-core-storefront`, `arkhai-core-storefront-client`, and
`arkhai-vms-storefront` each stand at least one minor version above their last
release, and record the versions in 10.4's note. A package that does not is
bumped in 10.4 by a minor version, with `make lock`.

- [x] 10.1 Route resolution reports which case failed through a typed error. The
  middleware answers each case unsigned (D3):
  - 404 when no contract names the path;
  - 405 with `Allow` naming the contracts' methods;
  - 400 naming the field when the body resource cannot be bound.

  Resolution stays first-match over the one ordered table it is given.
  Library integration (`test_site_auth_middleware.py`): each case answers its
  status, carries no response signature, and names no credential.

  `market_site.auth` gains `SiteRouteResolutionError` (a `ValueError`) and
  its cases `SiteRouteNotFound` (404), `SiteRouteMethodNotAllowed` (405,
  `Allow`), and `SiteRouteResourceUnbound` (400, `field`), which the
  middleware answers unsigned. A request whose body cannot be read is
  answered by its route first (`design.md`, Implementation record).
  - Unit (new `tests/unit/test_route_resolution.py`): each case, and first
    match between a literal and a capture route.
  - Library integration (`test_site_auth_middleware.py`): 404, 405 with
    `Allow: GET, POST`, and 400 naming the field, each carrying no
    authentication header and neither the request's signature nor its
    principal; an unreadable body at each kind of path. Pass (`kit/site`,
    302).
- [x] 10.2 The site client reports an answer with no response authentication as
  unauthenticated, with its status. The report contains no part of the body, no
  header value, and no credential. A malformed or wrong signature is reported
  as today (D3). Unit (`test_client.py`).

  `SiteCapacityUnauthenticatedResponseError`, a subclass of
  `SiteCapacityAuthenticationError`, exported, reports "site authority
  answered HTTP <status> without response authentication" with
  `status_code`. Unit (`test_client.py`): unsigned 200 and 405 answers
  carrying canaries are refused with it, naming neither canary nor the
  signature; an unknown protocol is still "missing or malformed". The fake
  site's unused `omit_response_authentication` control went. Pass
  (`kit/site-client`, 63).
- [x] 10.3 Application integration, rejection path, asserting the status and
  `Allow` only:
  - the provisioning service's site routes answer 405 to a known site path under
    another method;
  - the API-credits service, whose table extends the site's, answers the same
    (`test_signed_authority.py`).

  Plan correction (`design.md`, Implementation record): the provisioning
  service's 405 for a site path is section 13's (13.1 amended). Application
  integration (`test_signed_authority.py`, the real `main.app`): `DELETE
  /api/v1/capacity/snapshot` answers 405 `Allow: GET`, and `DELETE
  /api/v1/keys/key-1/revoke` 405 `Allow: POST`. Pass (75).
- [x] 10.4 Bump `arkhai-kit-site` and `arkhai-kit-site-client`, and run
  `make lock`. **Verification checkpoint:**
  - 10.1–10.3;
  - `make test` in `kit/site`, `kit/site-client`, `provisioning/compute/service`,
    and `domains/apicredits/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: the provisioning smoke hook's `provisioning_security` check still
  sends an unsigned read to a protected route that matches, and expects 401 or
  403. No scenario sends an unroutable request, and none is owed.

  Decision A's check, against `main`'s versions: `arkhai-kit-policy` 0.6.0
  (0.1.1), `arkhai-kit-contact-exchange` 0.4.0 (0.1.2),
  `arkhai-core-storefront` 0.16.0 (0.3.0), `arkhai-core-storefront-client`
  0.27.0 (0.17.0), `arkhai-vms-storefront` 0.22.0 (0.3.5); none bumped.
  Bumps over `dev`: `arkhai-kit-site` `0.11.0` → `0.12.0`,
  `arkhai-kit-site-client` `0.12.0` → `0.13.0`, and
  `arkhai-apicredits-service` `0.6.1` → `0.7.0`, with its floor on
  `arkhai-kit-site` at `0.12.0`. `make test`: `kit/site` 302,
  `kit/site-client` 63, the API-credits service 75, the provisioning service
  583 and 438; `make check-packaging` passes.

## 11. Settlement servicing records awaiting delivery, reports every retry, and waits through a failed read

Waits for `unbacked-bare-metal-listings` (D2). Delivers D8 parts 1–3 in
`kit/settlement-runtime`, with these deltas from `settlement-servicing`:
- "A fulfillment attempt may be deferred to its domain's convergence";
- "A ready step awaiting delivery is rechecked every cycle";
- "Every failing servicing step is reported";
- "The settle wait polls through a failed status read".

Files in `kit/settlement-runtime/src/market_settlement_runtime/`:
- `runtime.py` (`defer_fulfillment`);
- `sqlite_repository.py`: a migration adding `awaiting_delivery` to
  `settlement_operations`, the defer write, and lease writes clearing the flag;
- `ports.py`;
- `servicing.py`: the post-hook read and the retry log;
- `admin_routes.py` (`SettlementAdminRouteService.wait`).

Tests: `kit/settlement-runtime/tests/unit/` (`test_runtime.py`, `test_servicing.py`,
`test_sqlite_repository.py`, `test_admin_routes.py`) and
`tests/integration/test_servicing.py`. (Corrected in implementation:
`test_runtime.py`, `test_sqlite_repository.py`, and
`test_non_financial_obligation.py` read a real database and moved to
`tests/integration`; the kit's `Makefile` now runs both directories.)

- [x] 11.1 `defer_fulfillment` writes in one transaction (D8.2):
  - releases the fulfillment lease;
  - returns the attempt that `reserve_fulfillment` counted;
  - sets `awaiting_delivery`, leaving the state `pending`;
  - makes the operation due at once.

  The runtime's own migration adds the column. Any later write that leases the
  operation clears it.
  Library integration (`tests/integration/test_servicing.py`, over SQLite):
  - after the write, the operation is pending, due, unleased, and its attempt is
    not counted. This also covers "The process stops just after the mark is
    written", with a fresh repository and worker.
  - a lease clears the flag.
  - the due query, `schedule_settlement_retry`, and `wake_settlement_obligation`
    select the operation as an ordinary pending one, which is what a release
    without the mark reads.
  - the migration's rerun changes nothing.

  `defer_fulfillment` calls the repository's new
  `mark_fulfillment_awaiting_delivery`: one `UPDATE` to `pending`, the
  attempt returned, `awaiting_delivery = 1`, error and lease cleared, due
  now. Migration `20261028_005_settlement_operation_awaiting_delivery`
  (`SETTLEMENT_AWAITING_DELIVERY_MIGRATION_ID`) adds the column;
  `reserve_settlement_operation` and `schedule_settlement_retry` clear it.
  Bare metal's ready hook already called `defer_fulfillment`. Library
  integration (`test_servicing.py`, `test_sqlite_repository.py`,
  `test_runtime.py`): each listed case, including three consecutive deferring
  cycles and a fresh worker after a stop. Pass.
- [x] 11.2 The worker reads the operation after a ready hook returns without a
  fulfillment reference (D8.2):
  - if it is awaiting delivery, it keeps its due time and takes no backoff;
  - if it is still pending without the mark, it takes the error backoff;
  - if the hook raised, it stays on the error path.

  Unit (`test_servicing.py`) and library integration: across several
  consecutive deferrals, the obligation is due on each next cycle, and its
  attempts are not counted. A hook that returns without deferring backs off. A
  worker that ignores the flag backs the operation off as today (the delta's
  rollback scenario).

  `SettlementServicingWorker._after_ready_step` reschedules a marked
  operation at its own due time, consuming the mark; any other is logged and
  backed off. Unit: each case. Library integration: consecutive deferrals, an
  unmarked return backing off 30 s, and a repository that drops the mark (a
  release predating it) backing the operation off 30 s. Pass.
- [x] 11.3 The worker logs every retry it schedules at warning, naming the
  obligation, the operation, and the error, whether or not an `on_event` is
  composed (D8.1). Unit: a failing step under a worker with no callback logs
  the retry.

  Logged on every failing step and on a ready step that neither started
  fulfillment nor awaits delivery. Unit (`test_servicing.py`): both, under a
  worker with no `on_event`. Pass.
- [x] 11.4 `SettlementAdminRouteService.wait` treats a failed status read as a
  non-terminal poll and keeps polling until its deadline. At the deadline it
  returns `ready: false` with the last error (D8.3).
  Unit (`test_admin_routes.py`):
  - one failed read, then a terminal one: the wait reports ready;
  - every read fails: the wait reports `ready: false` with the last error.

  A failed read is recorded as `last_error` and polled through; a successful
  read clears it; a refusal (`LookupError` or `SettlementAdminRouteError`)
  ends the wait. Unit: each case. `last_error` reaches the wire in 18.2.
- [x] 11.5 Bump `arkhai-kit-settlement-runtime` by a minor version, since its
  schema and worker behaviour change. Run `make lock`.

  `0.5.0` → `0.6.0`; the six exact pins on it move, their packages unbumped
  for the pin alone (`design.md`, Implementation record). Bare metal's floor
  rises in section 18.
- [x] 11.6 **Verification checkpoint.**
  - Unit and library integration: 11.1–11.4.
  - Run `make test` in `kit/settlement-runtime` and in the VM, bare-metal, and
    API-credit storefronts, which compose it.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  Application integration and end-to-end are section 18's, where the storefronts
  compose the reporting.

  `make test`: the kit 175, the VM storefront 1138 and 475, bare metal's
  domain 182, storefront 502, buyer 16, and adapter 57, the API-credit
  storefront 241; `make check-packaging` passes.

## 12. Route contracts follow a decidable grammar and compose without overlap

Waits for `unbacked-bare-metal-listings` (D2). Delivers:
- the restricted route-pattern grammar;
- the typed resolution error;
- the refusal of overlapping contributions when the table is composed;
- the composition root's complete-table test.

This is D3, and the pattern-grammar part of the delta "The provisioning service
answers an unroutable request by what failed to match", with its scenarios:
"Two contributions claim one route", "A contract's pattern is outside the
grammar", "The service's own route table composes", and "One contribution
orders overlapping routes".

Files:
- `provisioning/compute/contracts/src/compute_provisioning_contracts/routes.py`:
  `route_contract_from_declaration`, `ProvisioningRouteContract.match`,
  `resolve_provisioning_route`, `ProvisioningRouteTable`, and
  `assemble_provisioning_route_table`;
- `domains/vms/provisioning/client/src/vm_provisioning_operator/routes.py` (the
  two relay declarations' terminal `$`);
- `provisioning/compute/contracts/tests/unit/test_route_table.py`;
- `provisioning/compute/service/tests/unit/test_route_table_composition.py`.

- [x] 12.1 Building a contract accepts only these constructs (D3):
  - literal segments;
  - `[^/]+` named captures;
  - finite alternations of literal segments;
  - a terminal `/?`.

  It refuses any other pattern, naming the route. Unit: each accepted construct;
  a tail capture, `.*`, a typed segment, a terminal `$`, and a mid-pattern
  optional are each refused by name.
  **Gate:** a route in the tree that this grammar cannot express is not handled
  by extending the grammar. Per D3, the contracts would adopt an established
  path-template grammar and its matcher, which returns the change to design.

  `route_contract_from_declaration` parses each pattern into segments
  (literals of `[A-Za-z0-9_~-]`, `(?P<name>[^/]+)` captures, alternations of
  two or more literals, an optional terminal `/?`) and refuses anything else,
  and a pattern compiled with flags, as "outside the route grammar". The gate
  held: every route the service composes fits once VM's relays drop `$`.
  Unit (`test_route_table.py`): each accepted construct and each refusal.
  Pass.
- [x] 12.2 Composing the table compares the contracts of different contributions
  segment by segment, a pattern ending in `/?` in both its forms. It refuses two
  that can match one method and path before the service accepts traffic. Within
  one contribution, the owner's order decides, first match (D3).
  Unit (`test_route_table.py`):
  - two overlapping contributions are refused;
  - a literal route before a capture route in one contribution composes, and
    the literal path resolves to the literal route.

  `ProvisioningRouteTable` refuses an overlap naming both operations and
  patterns; resolution is plain first match over one tuple, and the
  per-request "claimed by more than one route" refusal went. Unit: the
  overlapping and disjoint pairs, and
  `test_order_decides_within_one_contribution`. Pass.
- [x] 12.3 VM's two relay declarations drop their terminal `$`, which full
  matching makes redundant (D3). Unit: VM's relay paths resolve as before.

  Done. Unit: `test_every_assembled_route_resolves_to_itself`, and 12.5's
  slash test for `/api/v1/relays`. Pass.
- [x] 12.4 Resolution reports an unknown path, a known path under another method
  (with the allowed methods), and an unbindable body resource through a typed
  error that names its case, in place of `ValueError` (D3). Unit: each case.

  `ProvisioningRouteResolutionError` (a `ValueError`) and its cases
  `ProvisioningRouteNotFound`, `ProvisioningRouteMethodNotAllowed`, and
  `ProvisioningRouteResourceUnbound`, exported from the contracts, mirroring
  `kit/site`'s, since a contracts package may not import the site kit. Unit:
  each case. Pass.
- [x] 12.5 Unit (`test_route_table_composition.py`): the composition root builds
  the complete table under the grammar and the overlap check:
  - the family's routes, and every contribution the service ships: VM, bare
    metal, resource pools, Ansible host import, and capacity definitions;
  - the slashed and unslashed forms of `jobs/?`, `hosts/?`, `vms/?`,
    `relays/?`, and `pools/?` resolve to the same route.

  Over `main.provisioning_route_table`: every contribution's operations are
  in it, and each slashed path resolves with and without its slash to one
  contract. Pass (the service, 593 unit).
- [x] 12.6 Bump the contracts and the VM operator client, and run `make lock`.
  **Verification checkpoint:**
  - unit, 12.1–12.5;
  - `make test` in `provisioning/compute/contracts`,
    `domains/vms/provisioning/client`, and `provisioning/compute/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: every lane's provisioning requests resolve through the composed
  table, so a passing pipeline shows that no served route was refused at
  composition. No scenario is owed.

  `arkhai-compute-provisioning-contracts` `0.10.0` → `0.11.0`; the VM operator
  client stays `0.10.0` (section 3). `e2e-tests/pyproject.toml` raises its
  floor on the operator client to `0.10.0`, since `dev`'s `0.9.1` ends its
  relays in `$`. `make test`: contracts 100, the service 593 and 438, the e2e
  unit suite 169, the VM adapter 256; `make check-packaging` passes. The
  contracts package has no type-check target.

## 13. The provisioning service answers an unroutable request by cause, and the family client names an unauthenticated answer

Waits for `unbacked-bare-metal-listings` (D2). Delivers the middleware's
answers, and the client's report (D3). Deltas: the answer part of "The
provisioning service answers an unroutable request by what failed to match",
with its first three scenarios, and "The family client names an unauthenticated
answer".

Files:
- `provisioning/compute/service/src/compute_provisioning_service/middleware/auth.py`
  (route resolution before authentication, and `_rejection`);
- `provisioning/compute/client/src/compute_provisioning_client/base.py`
  (`_verify`);
- `provisioning/compute/service/tests/unit/middleware/test_auth.py`;
- a rejection-path module in `provisioning/compute/service/tests/integration`;
- `provisioning/compute/client/tests/unit/test_client.py`.

- [x] 13.1 The middleware maps section 12's typed error to an unsigned answer:
  404, 405 with `Allow`, or 400 naming the field (D3).
  - Unit (`test_auth.py`): each case, unsigned.
  - Application integration, rejection path, asserting status and `Allow` only:
    - an unknown path answers 404;
    - a known path under another method answers 405, its `Allow` naming the
      contract's methods;
    - a route whose body resource is missing answers 400.

  Amended by section 10's plan correction (10.3): the 405 cases include a
  known site path under another method, since the service authenticates the
  site's routes through this middleware.

  `ProvisioningAuthMiddleware.dispatch` answers a
  `ProvisioningRouteResolutionError` unsigned, before authentication; an
  unreadable body is answered by its route first, as in `kit/site`.
  - Unit (`test_auth.py`, both signature schemes): 404; 405 `Allow: POST` on
    the schedule route and `Allow: GET` on a site route; 400 naming
    `capacity_reservation_id`; each answer unauthenticated and leaking no
    signature or principal; unparseable JSON at each kind of path.
  - Application integration (new `test_unroutable_requests.py`, the composed
    `main.app`): 404, three 405 cases with their `Allow`, and 400.
- [x] 13.2 The family client reports an answer with no response authentication
  as unauthenticated, with its status, and still refuses it. A malformed or
  other-principal signature is reported as today. The report contains no body,
  header value, or credential (D3).
  Unit (`test_client.py`): an unsigned 405 is refused and reported as an
  unauthenticated 405 (the scenario "The client and service route tables
  differ").

  `ComputeProvisioningUnauthenticatedResponseError`, a subclass of
  `ComputeProvisioningAuthenticationError`, exported, reports "provisioning
  service answered HTTP <status> without response authentication" with
  `status_code`. Unit, both variants: an unsigned 405 with canaries is
  refused with it, naming neither canary nor the signature; a proof over
  another resource is "authentication failed"; another principal's answer
  reports `wrong_principal`. Pass (67).
- [x] 13.3 Bump the service and the client, and run `make lock`. **Verification
  checkpoint:**
  - 13.1–13.2;
  - `make test` in `provisioning/compute/service` and
    `provisioning/compute/client`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: the provisioning smoke hook's `provisioning_security` check is
  unchanged. No scenario sends an unroutable request, and none is owed.

  `arkhai-compute-provisioning-service` `0.18.0` → `0.19.0` and
  `arkhai-compute-provisioning-client` `0.8.0` → `0.9.0`; the service's floor
  on the contracts rises to `0.11.0`. `make test`: the service 605 and 443,
  the client 67; `make check-packaging` passes. No type checker runs on
  either project.

## 14. Retired reservation states are converted at upgrade, and no reader names them

Waits for `unbacked-bare-metal-listings` (D2). Delivers D5's upgrade conversion
in both services' migration chains, and every reader outside `kit/site` that
stops deciding about `provisioning` and `provisioning_failed` (D5; delta "A
stored reservation in a retired state is converted at upgrade"). This section
comes before section 15, which removes the definitions these readers name.

Files:
- **Migration chains:**
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
  and `domains/apicredits/service/src/apicredits_service/db/migrations.py` (a new
  migration in each).
- **Readers in production code:**
  - `provisioning/compute/src/compute_provisioning/lease_lifecycle.py`
    (`TERMINAL_FAILURE_STATES`);
  - `provisioning/compute/service/src/compute_provisioning_service/services/fulfillment_convergence.py`
    (its terminal-state set);
  - `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`
    (`_INTERRUPTIBLE_HELD_STATES`, and the release-state loop);
  - `domains/apicredits/service/src/apicredits_service/services/keys_service.py`
    (its held-state set).
- **Test fakes:** `domains/vms/storefront/tests/fake_site.py`,
  `kit/site-client/tests/unit/fake_site.py`, and
  `provisioning/compute/tests/unit/test_lease_lifecycle.py`.
- **Not changed:** historical migrations that name the states as data of their
  time.

- [x] 14.1 Add a provisioning migration that converts stored reservations (D5):
  - `provisioning` becomes `unmanaged`;
  - `provisioning_failed` becomes `force_released`.

  Each gets a failure reason naming the state it held. Persistence integration
  (file-backed SQLite), the delta's three scenarios:
  - a `provisioning` row is `unmanaged`, its capacity still held;
  - a `provisioning_failed` row is `force_released`, its capacity free;
  - a database with neither is unchanged.

  A rerun changes nothing.

  `20261028_001_retired_reservation_states`: one `UPDATE` per state, setting
  `failure_reason` `retired_state_<state>` and a message keeping any earlier
  reason, and `released_at` on a row becoming `force_released`; no capacity
  event is written. A converted windowed row is held wider than D5's
  "exactly" (`design.md`, Implementation record). Persistence integration
  (new `tests/integration/test_retired_reservation_states_migration.py`):
  each scenario, the rerun, and `run_migrations` applying it; held and free
  are read as membership of the ledger's held set. Pass.
- [x] 14.2 Add the same conversion to the API-credits service's chain (D5).
  Persistence integration in its `tests/integration`: the same three cases, and
  the rerun.

  `20261028_006_retired_reservation_states`, since each service owns its
  migration history. Persistence integration: the same cases and the chain
  applying it. Pass (79).
- [x] 14.3 The readers listed above stop naming the two states (D5). Verify:
  - a repository search finds them only in `kit/site`'s definitions (until
    section 15), historical migrations, and the conversion and its tests;
  - unit `test_lease_lifecycle.py` passes on the remaining states.

  Removed from every listed reader and fake. The search finds the states only
  where the task allows and in the contract's `LeaseState` mapping (section
  16); the string elsewhere is a fulfillment failure reason, not a state.
  `test_lease_lifecycle.py` passes (243).
- [x] 14.4 Bump the service, the family kit, the VM storefront, and the
  API-credits service, and run `make lock`. **Verification checkpoint:**
  - 14.1–14.3;
  - `make test` in `provisioning/compute`, `provisioning/compute/service`,
    `domains/vms/storefront`, and `domains/apicredits/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: every compute lane and the API-credit lane migrate fresh
  databases, which hold no such row. No scenario is owed: the conversion is one
  service's migration, which persistence integration owns.

  `arkhai-compute-provisioning` `0.20.0` → `0.21.0` and
  `arkhai-vms-storefront` `0.22.0` → `0.23.0`; the two services were bumped
  in sections 13 and 10. `make test`: the family kit 243, the service 605 and
  447, the VM storefront 1138 and 475, the API-credits service 79; `make
  check-packaging` passes.

## 15. The site ledger defines only the states its lifecycle writes

Waits for `unbacked-bare-metal-listings` (D2). Delivers the removal of
`ReservationState.provisioning` and `provisioning_failed`, and of
`update_reservation_state` (D5). Deltas in `site-capacity`:
- "Reservation lifecycle";
- "A reservation's lease tail is written once";
- "The lease lifecycle's writes are conditional transitions", including "A
  caller asks to set a state directly";
- "Lease truncation neither resurrects nor extends a lease".

Files:
- in `kit/site/src/market_site/`:
  - `db.py`: the two members, and `HELD_RESERVATION_STATES`;
  - `ledger.py`: the lease transitions' source-state sets, the terminal sets,
    and `update_reservation_state`;
  - `authority.py`: the protocol entry for `update_reservation_state`;
- `kit/site/tests/integration/test_ledger.py`;
- `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`.

- [x] 15.1 Remove the two members, and every set, transition, and terminal
  check that names them (D5). Library integration (`test_ledger.py`): the
  conditional transitions and truncation refusals hold for the remaining
  states.

  Removed with every set and transition naming them. Library integration
  (`test_ledger.py`): the transition and truncation tests pass. Unit (new
  `tests/unit/test_reservation_states.py`): the enum is exactly `reserved`,
  `leased`, `releasing`, `released`, `release_failed`, `unmanaged`, and
  `force_released`, and the held set the five that hold.
- [x] 15.2 Remove `CapacityLedgerService.update_reservation_state` and its
  authority-protocol entry. Tests reach a state through the real transitions,
  or seed the row where no API expresses it (TESTING.md, "Service-internal
  state setup") (D5).
  Verify:
  - a repository search finds no caller;
  - unit: the authority protocol exposes no generic state writer.

  Removed; its four test callers use `begin_releasing`,
  `record_release_failed`, and `record_unmanaged`. `release` takes `forced:
  bool` in place of a caller-named state (`design.md`, Implementation
  record); `SiteAuthorityLedger` also declares `record_release_failed` and
  `record_unmanaged`. Unit (`test_reservation_states.py`): no public
  operation of the ledger or the protocol takes a `state`-named parameter or
  `**kwargs`, but the list filter. Pass (`kit/site`, 304).
- [x] 15.3 Bump `arkhai-kit-site`, unless section 10 already did, and run
  `make lock`. **Verification checkpoint:**
  - library integration, 15.1–15.2;
  - `make test` in `kit/site`, `kit/site-client`, `provisioning/compute`,
    `provisioning/compute/service`, `domains/vms/storefront`, and
    `domains/apicredits/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: `e2e_deal`, `e2e_deal_buyer_cli`, and `e2e_bare_metal_mock_deal`
  lease and release through the remaining transitions. No scenario is owed.

  No bump (section 10). `test_compute_contract_api.py`'s expectation drops
  the two states; the contract's mapping loses them in 16.1. `make test`:
  `kit/site` 304, `kit/site-client` 63, `provisioning/compute` 243, the
  service 605 and 447, the VM storefront 1138 and 475; `make
  check-packaging` passes.

## 16. The compute provisioning contract is major 3

Waits for `unbacked-bare-metal-listings` (D2). Delivers contract major 3,
accepted alone. Its schedule response carries the scheduled resource's
`host_id`, and its lease state has no `provisioning_failed` (D13, and the
contract part of D5). Deltas:
- "Explicit contract incompatibility";
- "A schedule response names the scheduled resource's host and machine".

Files:
- `provisioning/compute/contracts/src/compute_provisioning_contracts/contracts.py`:
  - `COMPUTE_PROVISIONING_CONTRACT_VERSION` and
    `SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS`;
  - `FulfillmentScheduleResponse.host_id`;
  - `LeaseState`, and `lease_state_for_reservation_state`'s mapping;
- `provisioning/compute/service/src/compute_provisioning_service/controllers/fulfillment_controller.py`
  (the schedule response);
- tests that assert the old version or state:
  - `provisioning/compute/client/tests/unit/test_fulfillment_client_opacity.py`;
  - `provisioning/compute/service/tests/integration/test_compute_contract_api.py`,
    `test_fulfillment_api.py`, and `test_scheduling_composition.py`;
  - `domains/vms/storefront/tests/unit/services/test_aggregate_fulfillment_client.py`.

- [x] 16.1 The contract is major 3, and every party accepts only major 3.
  `FulfillmentScheduleResponse` gains an optional `host_id`.
  `LeaseState.PROVISIONING_FAILED` and its mapping entry are removed
  (D13, D5).
  Unit (contracts):
  - a 2.x model is refused, naming the supported major;
  - a schedule response validates with and without `host_id`;
  - `LeaseState` has no `provisioning_failed`.

  Amended by section 15: `lease_state_for_reservation_state`'s mapping
  loses both retired keys, `provisioning` (to `PENDING`) as well as
  `provisioning_failed`, since neither is a reservation state any longer
  (D5's "the mapping entries").

  `COMPUTE_PROVISIONING_CONTRACT_VERSION` is `"3.0"` and the supported
  majors `{3}`. `host_id: str | None` is omitted from serialization when
  absent (`Field(exclude_if=…)`), with the contracts' pydantic floor at
  `2.12` (corrected from `2.11` at section 19; `design.md`, Implementation
  record). Unit (`test_contracts.py`): `1.0`, `2.0`, `2.1`, and `4.0` refused
  naming "supported majors: 3", `3.0` and `3.1` accepted; the schedule
  response with and without `host_id`, the schema still listing it;
  `LeaseState` without `provisioning_failed`. Pass.
- [x] 16.2 The schedule route sets `host_id` from the scheduled resource's
  declaration, and omits it when the declaration names none. The resource's
  `physical_host_id` stays in its top-level attributes (D13).
  Application integration, through the typed family client:
  - "A whole host is scheduled": `host_id` and the top-level `physical_host_id`
    are present.
  - "A resource with no host is scheduled": a hostless declaration in a pool
    whose provider needs no host is scheduled with `host_id` omitted.
  - An idempotent repeat returns the same assignment.
  - "Old client calls new service": a major-2 request is refused with the
    supported version range, and nothing is done.

  Application integration (`test_fulfillment_api.py`, `TestScheduleEndpoint`):
  bare metal's whole host schedules with `host_id` and `physical_host_id`; a
  VM repeat carries its `host_id`; a `2.0` request is refused 422 with no
  settlement record. Plan correction: no provider the service composes needs
  no host, so the hostless case is library integration in `kit/fulfillment`
  (`test_a_provider_needing_no_host_places_and_returns_a_hostless_assignment`);
  the route's omission of an absent host is read from its serialization, not
  tested.
- [x] 16.3 "A storefront calls a service that has not been upgraded". Unit, in
  the family client or VM's aggregate fulfillment client: a major-2 schedule
  answer is refused, naming the supported major, and nothing is begun.

  Unit (`test_fulfillment_client_opacity.py`): a `2.0` schedule answer raises
  naming "supported majors: 3". "Nothing is begun" is the caller's and is not
  tested. Pass (client 68).
- [x] 16.4 Bump the contracts, the client, the family kit, and the service,
  and raise every consumer's floor on the contracts to major 3's release. Run
  `make lock`. **Verification checkpoint:**
  - 16.1–16.3;
  - `make test` in `provisioning/compute/contracts`,
    `provisioning/compute/client`, `provisioning/compute`,
    `provisioning/compute/service`, `domains/vms/storefront`, and
    `domains/bare_metal/storefront`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: every compute lane schedules and reads leases across the contract
  between upgraded parties: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
  `e2e_listing_shapes`, `e2e_non_erc20_settlement`, and
  `e2e_bare_metal_mock_deal`. A passing pipeline is the evidence that both sides
  speak major 3.

  Major 3 ships in the versions sections 12–14 bumped. Every consumer's floor
  on the contracts rises to `0.11.0`. The provisioning adapters take their
  one bump over `dev`: `arkhai-vms-provisioning-adapter` `0.14.0` → `0.15.0`,
  `arkhai-bare-metal-provisioning-adapter` `0.10.0` → `0.11.0`. `make test`:
  contracts 107, the client 68, `kit/fulfillment` 172, the family kit 243,
  the service 605 and 449; `make check-packaging` passes. The lockstep
  upgrade across major 3 is promoted to `DEPLOYMENT_AND_CONFIG.md` (27.9).

## 17. Worker controls are typed, and convergence counts reach the log text

Waits for `unbacked-bare-metal-listings` (D2). Delivers:
- typed answers for `check-leases`, `run-cycle`, `advance-cycle`, and identity
  rotation, beside the branch's `WorkerPauseResponse` (D15; delta
  "Compute-owned caller contract", the scenario "An operator runs a worker
  control");
- the recovery-diagnostics counts in the log message (D19).

Files:
- `provisioning/compute/contracts/src/compute_provisioning_contracts/system.py`;
- `provisioning/compute/client/src/compute_provisioning_client/client.py`
  (`check_leases`, `run_fulfillment_convergence_cycle`,
  `advance_fulfillment_convergence_cycle`, and `rotate_trusted_principal`, async
  and sync);
- in `provisioning/compute/service/src/compute_provisioning_service/`:
  `controllers/system_controller.py`, and `services/fulfillment_convergence.py`
  (its recovery-diagnostics line);
- e2e callers that index these answers:
  - `e2e-tests/tests/e2e/roles/helpers/compute_deal.py` and
    `compute_deal_stages.py`;
  - `scenarios/vms/test_full_deal_buyer_cli.py` and
    `test_non_erc20_settlement.py`;
  - `scenarios/bare_metal/test_bare_metal_mock_deal.py` and
    `test_bare_metal_payment_deal.py`;
- tests: the client's unit tests; the service's `test_system_api.py`,
  `test_leases_api.py`, `test_lease_release_api.py`, and
  `test_bare_metal_mock_profile.py`.

- [x] 17.1 Each control answers a model from `system.py`. The client returns it,
  in both variants, and the service's failures are answered as every
  provisioning route's are (D15).
  - Application integration (`test_system_api.py`, through the typed client):
    each control's typed answer.
  - Unit: sync/async parity.

  `system.py` gains `LeaseCheckResponse`, `ConvergenceStateCounts`,
  `ConvergenceDiagnostics`, `ConvergenceCycleResponse`, and
  `PrincipalRotationResponse`, exported; the routes and both client variants
  answer them, their failures unchanged. The service's `dev` floor on the
  client rises to `0.9.0`. Application integration (`test_system_api.py`):
  each control, and a new `TestIdentityRotation`. Unit: each control through
  both clients; the parity guardrail passes.
- [x] 17.2 The e2e callers read the models' attributes (D15). Verify: `make -C
  e2e-tests test-unit` passes, including the stage-set check.

  `compute_deal_stages.py` and `test_full_deal_buyer_cli.py` read the
  models' attributes; the harness's unused untyped copies of two controls
  went; `e2e-tests`' floor on the family client is `0.9.0`. `make -C
  e2e-tests test-unit` passes (169); the reads run only in the lanes.
- [x] 17.3 The recovery-diagnostics line carries its counts in its message, and
  keeps `extra` for the test that reads it (D19). Unit: the formatted message
  names each count.

  `_diagnostics_text` writes the counts into the message, the three
  unrecordable lease-target categories as their sum, and `extra` is kept.
  Unit (new `test_convergence_diagnostics_text.py`): the text names every
  count and the record keeps its `extra`. Pass.
- [x] 17.4 Bump the contracts, the client, and the service, unless sections 12,
  13, or 16 already did, and run `make lock`. **Verification checkpoint:**
  - 17.1–17.3;
  - `make test` in `provisioning/compute/contracts`,
    `provisioning/compute/client`, and `provisioning/compute/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: these scenarios advance convergence and check leases through the
  typed controls, which is the evidence that both sides agree:
  - the shared compute stages;
  - `e2e_deal_buyer_cli` and `e2e_non_erc20_settlement`;
  - `e2e_bare_metal_mock_deal`.

  No bump (sections 12 and 13). `make test`: contracts 107, the client 74,
  the service 607 and 450, the e2e unit suite 169; `make check-packaging`
  passes.

## 18. Every storefront that services obligations reports its servicing events

Waits for `unbacked-bare-metal-listings` (D2). Delivers:
- bare metal's and API credits' `on_event`, writing the `claims` stage events
  that VM's composition writes (D8.1, recorded in `design.md`; delta "Every
  failing servicing step is reported");
- the storefront-level proof of section 11's awaiting-delivery cadence and
  settle wait.

Files:
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`
  (the worker's construction);
- `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py`
  (the worker's construction);
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/alkahest_lifecycle.py`
  (the ready hook's deferral, through `defer_fulfillment`);
- tests in `domains/bare_metal/storefront/tests/`: `test_alkahest_lifecycle.py`
  and `test_obligation_servicing.py`;
- `domains/apicredits/storefront/tests/unit/test_settlement_fulfillment.py`.

- [x] 18.1 Both storefronts compose `on_event`, as VM's
  `settlement_composition.py` does (D8.1). Unit: each composition hands the
  worker its callback. Assert the object identity at the constructor, per
  TESTING.md, "Composition-boundary convention".

  Each storefront's `record_servicing_event` writes a `claims` stage event and
  is handed to its worker. Shown by behaviour, not identity (`design.md`,
  Implementation record): API credits' unit `test_settlement_events.py` and
  integration `test_settlement_events.py` (the composition's worker writes
  one `claims` `settlement_retry` event for a failed step); bare metal's
  `test_obligation_servicing.py` (the runtime's worker writes one naming the
  obligation, `fulfill`, and the error).
- [x] 18.2 Application integration (bare metal, through its typed clients and the
  lifecycle `run-cycle` route):
  - a deal whose lease is not yet active is due again on the next
    servicing cycle, with no backoff, and publishes its evidence once the lease
    is active;
  - a failing step writes a stage event;
  - the administrator's settle wait, with one failed status read at the site,
    reports ready (D8.2, D8.3).

  Amended by section 11 (11.4): the kit's wait returns `last_error` beside
  `ready: false`, and no storefront's answer carries it, since
  `core_storefront`'s `SettleWaitResponse` and the core client's model
  name only `ready`, `status`, `provisioning_job_id`, and `elapsed_ms`. This
  section adds an optional `last_error` to both, the three storefronts' wait
  routes pass it through, and application integration shows a wait whose
  every read fails answering `ready: false` with it. `arkhai-core-storefront`
  and `arkhai-core-storefront-client` take their one bump over `dev` here.

  Done as amended; bare metal's `BareMetalSettleWaitResponse` gains
  `last_error` too. Application integration (`test_alkahest_lifecycle.py`,
  typed buyer and administrator clients): a deal settled while its lease is
  `provisioning` is processed by two consecutive `run-cycle` steps, the
  second publishing its evidence; a rejected publication writes a `claims`
  `settlement_retry` event; one failed read then ready reports ready with no
  `last_error`; every read failing reports `ready: false` with it. The waits
  poll at the route service's one-second interval. The VM and API-credit
  routes' pass-through is read, not tested.
- [x] 18.3 Bump the bare-metal and API-credit storefronts, and run `make lock`.

  Amended by section 11 (11.5): bare metal's floor on
  `arkhai-kit-settlement-runtime` rises to `0.6.0`, since its deals depend
  on the awaiting-delivery cadence.
  **Verification checkpoint:**
  - 18.1–18.2;
  - `make test` in `domains/bare_metal/storefront` and
    `domains/apicredits/storefront`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end:
  - `e2e_bare_metal_mock_deal` settles through the servicing worker and the
    settle wait.
  - `e2e_credits_deal` settles through API credits' worker.

  Whether a deal meets a deferral depends on timing the scenarios do not
  control. They are therefore evidence for the composition, not for the
  awaiting-delivery cadence, which library and application integration own.
  No scenario is owed.

  `arkhai-bare-metal-storefront` `0.22.0` → `0.23.0`,
  `arkhai-apicredits-storefront` `0.16.0` → `0.17.0`,
  `arkhai-core-storefront` `0.16.0` → `0.17.0`, and
  `arkhai-core-storefront-client` `0.27.0` → `0.28.0`; exact pins on them
  moved, their packages unbumped. Floors: bare metal's on the settlement
  runtime (`0.6.0`) and the core client (`0.28.0`); the VM and API-credit
  storefronts' on core-storefront (`0.17.0`) and the settlement runtime
  (`0.6.0`). `make test`: the bare-metal storefront 507, the API-credit
  storefront 243; `make check-packaging` passes.

## 19. Bare-metal begin reads the scheduled identity, and a delivery conflict answers 409

Waits for `unbacked-bare-metal-listings` (D2), and comes after section 16.
Delivers:
- begin comparing the schedule response's `host_id` and top-level
  `physical_host_id` with the terms (D13);
- the typed 409 `delivery_conflict` (D12).

Deltas in `storefront-publication`: "Bare-metal begin reads the scheduled
resource's own identity", and "A bare-metal delivery that conflicts with its
recorded result is refused".

Files:
- in `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`:
  - `fulfillment_service.py` (begin's scheduled-resource check, and the status
    read);
  - `sqlite_client.py` (the write-once result);
  - `api.py` (the status, result, and access routes);
- `e2e-tests/tests/e2e/roles/scenarios/bare_metal/compute_deal_driver.py` (the
  nested `bare_metal_publication` copies);
- tests in `domains/bare_metal/storefront/tests/`: `test_fulfillment_service.py`
  and `test_http_settlement.py`.

- [x] 19.1 Begin compares the schedule response's `host_id` and the scheduled
  resource's top-level `physical_host_id` with the accepted terms. It refuses an
  absent or different `host_id`, or a different `physical_host_id`, as a
  conflict with its terms. It no longer reads `bare_metal_publication` (D13).
  - Unit (`test_fulfillment_service.py`): each case.
  - Application integration (`test_http_settlement.py`, typed clients), one case
    each:
    - "A declaration names its machine once": fulfillment begins.
    - "The scheduled resource is another machine": the deal reports the
      conflict.
    - "The scheduled resource names no host": the deal reports the conflict.

  Unit: `test_begin_refuses_a_scheduled_resource_the_terms_did_not_sell`
  (no host, another host, another machine; one schedule and no begin).
  Application integration: the existing deal tests begin from a schedule
  naming `host_id` and a top-level `physical_host_id`; new
  `test_a_scheduled_resource_the_terms_did_not_sell_is_reported_as_a_conflict`,
  where no begin reaches the fake and the conflict is reported in the
  worker's `settlement_retry` stage event only. `test_payment_settlement_client.py`'s
  schedule fake now answers as the contract does. The contracts' pydantic
  floor was corrected here (16.1). Pass.
- [x] 19.2 A site-reported delivery that differs from the recorded result makes
  the status, result, and access reads answer 409 `delivery_conflict`, and the
  recorded result stands (D12). Application integration, through
  `StorefrontClient`: "The site reports a different delivery".

  When the store refuses the write-once result and the recorded result
  differs, the status read raises
  `BareMetalFulfillmentError(error="delivery_conflict")`; any other refusal
  propagates. The status, result, access, and teardown routes answer a coded
  refusal as `{"error": …, "reason": …}`. Unit:
  `test_a_delivery_conflict_is_named_only_when_the_recorded_result_differs`.
  Application integration:
  `test_a_delivery_other_than_the_recorded_result_is_a_conflict`, through the
  bare-metal buyer's `BareMetalFulfillmentTransport` (plan correction:
  `StorefrontClient` has no fulfillment reads), status, result, and access
  each 409 and the stored result unchanged. `sqlite_client.py` is unchanged.
  Pass.
- [x] 19.3 The bare-metal e2e driver stops declaring the nested copies of the
  host and machine (D13). Verify: `make -C e2e-tests test-unit`.

  `compute_deal_driver.py` declares `enabled` and `access_methods` only. The
  e2e unit suite passes (169) without importing the driver; collecting the
  bare-metal scenarios imports it (64). No other e2e declaration nested the
  copies.
- [x] 19.4 Bump the bare-metal storefront, unless section 18 already did, and run
  `make lock`. **Verification checkpoint:**
  - 19.1–19.3;
  - `make test` in `domains/bare_metal/storefront`;
  - `make check-packaging` and `make check-comment-hygiene`.

  No bump (section 18). `make test` in the bare-metal storefront: 514; full
  `make test`, `make check-packaging`, and `make check-comment-hygiene` pass.
  Teardown and the admin settle-status read under a conflict are follow-ups
  in `design.md`'s Implementation record.

  End-to-end: `e2e_bare_metal_mock_deal` begins fulfillment from a declaration
  that no longer repeats its identity in its publication settings, which is the
  evidence for 19.1. No scenario produces a conflicting delivery. The 409 is
  owned by application integration, and no scenario is owed for it.

## 20. The VM storefront's `[provisioning] mode` is removed

Waits for `unbacked-bare-metal-listings` (D2). Delivers the removal of the
unread `mode` key. A configuration that still states it starts unchanged
(D22).

Files:
- in `domains/vms/storefront/src/market_storefront/`: `settings.toml` and
  `groups/config.py` (the `config init` template);
- `helm/values.yaml` (the storefront agent's `provisioning.mode`), and
  `helm/charts/storefront/tests/test_render.py`;
- `docs/development/VALIDATION_RUNBOOK.md`;
- `docs/seller-quickstart.md`: each line stating `mode`, or saying that it
  selects mock or live.

- [x] 20.1 Remove `mode` from the settings, the template, and the umbrella
  values, and the render test's expectation of it (D22).
  - Unit (`domains/vms/storefront/tests/unit/cli/test_config.py`): the generated
    template has no `mode`, and a settings file that states it still loads.
  - Chart render: `make -C helm test-render`.

  Removed from `settings.toml`, the `config init` template, and the
  umbrella's agent config, whose `provisioning:` block went whole; the
  render test expects `service_url` alone. `retired_settings.py` says a key
  the storefront never read is ignored, not refused. Unit:
  `test_config_init_user_states_no_provisioning_mode`,
  `test_a_stated_provisioning_mode_loads_beside_the_section_it_sits_in`, and
  `test_a_provisioning_mode_the_storefront_never_read_is_ignored` (they show
  loading and the startup checks, not the app starting). Chart render:
  `test_a_stated_provisioning_mode_renders_beside_the_derived_service_url`.
  Pass.
- [x] 20.2 Remove `mode` from the runbook and the seller quickstart, which say
  it selects mock or live provisioning (D22).

  `VALIDATION_RUNBOOK.md`'s cutover drops the storefront's `--set …
  provisioning.mode=real` (the provisioning chart's `mockMode=false` stays).
  `seller-quickstart.md` drops the example's `mode` line, says the storefront
  has no provisioning mode, and drops live provisioning's first step.
- [x] 20.3 Bump the VM storefront, unless already bumped since the merge.
  **Verification checkpoint:**
  - 20.1;
  - `make test` in `domains/vms/storefront`;
  - `make -C helm test-render`;
  - `make check-comment-hygiene`.

  No bump: `arkhai-vms-storefront` is already `0.23.0` over `dev`'s
  `0.22.0`. The VM storefront's suite: 1141 passed and 1 skipped, 475
  integration; `make -C helm test-render`, `make check-comment-hygiene`, and
  `make check-packaging` pass.

  Owed by validation: `tests.yml`, job `release · deployment contracts`, where
  `make -C helm test-render` passes with `mode` gone from the umbrella's values
  and its render test.

  End-to-end: the VM lane's storefronts boot without the key. No scenario is
  owed.

  Correction: that sentence is not new evidence, since the lanes'
  configurations never stated the key; the render covers the one deployment
  that did, and validation's Helm release boots it. The quickstart's "mock
  mode" sections are a follow-up in `design.md`'s Implementation record.

## 21. The e2e harness calls the family's mock-rule client

Waits for `unbacked-bare-metal-listings` (D2). Delivers the e2e callers' move
onto section 2's client (D14; the e2e side of the delta scenario "A test reads
a mock rule through the family client").

Files:
- `e2e-tests/src/e2e_harness/provisioning_test_client.py`: rule and
  evaluate-job methods over `SyncMockRuleClient`, one per mount. The shared
  `/test/jobs/*` drain and wait stay.
- `e2e-tests/pyproject.toml`: the family client, if not yet declared. Also its
  lock.
- callers:
  - `e2e-tests/tests/e2e/roles/helpers/compute_deal.py` and
    `compute_deal_stages.py`;
  - `scenarios/vms/{conftest.py,compute_deal_driver.py,test_full_deal_buyer_cli.py,test_buy_oneshot_buyer_cli.py,test_listing_shapes.py,test_non_erc20_settlement.py}`;
  - `scenarios/bare_metal/{conftest.py,compute_deal_driver.py,test_bare_metal_payment_deal.py}`.

- [x] 21.1 The harness builds the family client with VM's mount and bare
  metal's mount, the latter from `arkhai_bare_metal.provisioning_routes`'
  values. The callers read the typed models' attributes (D14).
  Verify:
  - `make -C e2e-tests test-unit` passes, including the stage-set check;
  - no e2e source builds a mock-rule path or operation by hand.

  `ProvisioningTestClient` builds a `SyncComputeProvisioningClient` signing
  as `admin` and two `SyncMockRuleClient`s, `vm_rules` and
  `bare_metal_rules`; its hand-written rule methods are gone, and it signs
  the family's `/test/jobs/*` routes itself for their long-poll timeouts. It
  takes an optional `transport` as its test seam. The callers add
  `MockRuleCreate` models and read `MockJobEvaluation`'s attributes; VM's
  evaluate body is `vm_job_evaluation` in VM's driver. The VM conftest's
  `storefront_service_client` docstring names the one callback it drives.
  Unit (new `tests/unit/test_provisioning_test_client.py`): each mount's
  five operations reach their method, path, and `admin` role, and each
  mount's operation prefix is pinned; 3 cases pass. `make -C e2e-tests
  test-unit`: 172. Collecting `tests/e2e` imports every module (210). A
  search finds no hand-built mock-rule path or operation.
- [x] 21.2 **Verification checkpoint.**
  - Run `make -C e2e-tests test-unit`, `make lock`, `make check-packaging`, and
    `make check-comment-hygiene`.

  `make lock` changed nothing; `make check-packaging` and `make
  check-comment-hygiene` pass. No bump: `arkhai-e2e-tests` is not published.

  End-to-end: every scenario that installs mock rules is the evidence for this
  section:
  - `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_listing_shapes`, and
    `e2e_non_erc20_settlement`;
  - `e2e_bare_metal_mock_deal`, and `e2e_bare_metal_payment_deal` when a
    payments target is configured.

## 22. A seller's wallet address and key name one account

Waits for `unbacked-bare-metal-listings` (D2), whose rewrite of
`kit/alkahest/settlement_config.py`'s readiness blockers this builds on.
Delivers D10 in `kit/alkahest`:
- the `alkahest.wallet_address_mismatch` blocker;
- a missing seller address derived from the key;
- the oracle check against the signing account.

Delta: "A seller's wallet address and key name one account".

Files:
- `kit/alkahest/src/market_alkahest/settlement_config.py`: the wallet blockers,
  and the oracle-is-not-the-seller check;
- `kit/alkahest/tests/unit/test_settlement_config.py`.

- [x] 22.1 A configured seller address that differs from the address its key
  derives (through `kit/config`'s `derive_wallet_address`) makes Alkahest
  unready with `alkahest.wallet_address_mismatch`. An absent address is the
  key's. The oracle check compares the oracle with the signing account as well
  as the address. Buyers keep their tolerance (D10).
  Unit: one case each:
  - "The address names another account";
  - "The address is omitted";
  - "The oracle is the signing key".

  A buyer configuration with a mismatch is not refused.

  A seller whose address and key's account differ (case-insensitively) has
  `alkahest.wallet_address_mismatch`; `alkahest.wallet_address_missing` is
  only for a wallet with neither an address nor a readable key; the oracle is
  compared with both accounts. The kit exports `wallet_account_address`. Moved
  forward from 24.2 (`design.md`, Implementation record): each storefront
  names its seller through it in one accessor (VM's
  `get_evm_wallet_address`, bare metal's `runtime.py`, API credits' new
  `seller_wallet_address`), and the `settlement-configuration` delta modifies
  "An Alkahest section that cannot settle makes Alkahest unready" and
  "Readiness blockers state their kind".
  - Unit (`kit/alkahest`): `test_the_address_names_another_account`,
    `test_the_address_is_omitted`, `test_the_oracle_is_the_signing_key`,
    `test_a_buyer_whose_address_is_not_its_keys_is_not_refused`, and an
    uppercase address.
  - Unit, bare metal's composition root:
    `test_an_omitted_address_is_the_account_its_key_signs_as`; VM:
    `test_an_omitted_wallet_address_is_the_account_its_key_signs_as`.
  - Application integration (API credits):
    `test_a_seller_stating_only_a_key_publishes_the_keys_account_as_recipient`.

  The storefront suites' seller wallets now use Anvil's first published
  development account, whose address matches its key.
- [x] 22.2 Bump `arkhai-kit-alkahest`, and run `make lock`. **Verification
  checkpoint:**
  - 22.1;
  - `make test` in `kit/alkahest`;
  - `make check-packaging` and `make check-comment-hygiene`.

  Application integration and end-to-end are section 24's.

  `arkhai-kit-alkahest` 0.10.0 → 0.11.0; the three storefronts' floors at
  `>=0.11.0`. `make test`: `kit/alkahest` 424, the VM, bare-metal, and
  API-credit storefronts 1142 + 475, 513, and 244; `make check-packaging`
  passes. End-to-end: the pipeline's storefronts state addresses their keys
  sign as, so no scenario meets the blocker.

## 23. Alkahest address books are named per chain in the Alkahest section

Waits for `unbacked-bare-metal-listings` (D2). Delivers:
- `[Settlement.alkahest.address_books]`;
- readiness refusing a key that names no configured chain;
- the one `kit/alkahest` operation that resolves a chain's book.

This is D11 in `kit/alkahest`, beside the keys it later retires. Delta "Alkahest
address books are named per chain in the Alkahest section", its first
sentences.

Files:
- `kit/alkahest/src/market_alkahest/settlement_config.py` (the map, and
  readiness);
- the resolver operation, exported from `market_alkahest`;
- `kit/alkahest/tests/unit/test_settlement_config.py`, and a resolver unit
  suite.

- [x] 23.1 Add the map from configured chain name to book. A key naming no
  configured chain makes Alkahest unready (D11).
  Unit:
  - the map parses;
  - an unknown chain key is a blocker naming the key.

  `AlkahestSettlementConfig.address_books: dict[str, str]`, empty by default,
  each key a trimmed chain name and each value a trimmed path. Readiness
  reports one `alkahest.address_book_chain_unknown` blocker naming every key
  that is not a configured settlement chain, when the composition passes a
  chains mapping; an unloadable book is `alkahest.address_config_invalid`.
  Unit (`test_settlement_config.py`): parsing, malformed entries, the unknown
  key for a seller (enabled and disabled) and a buyer, no chains mapping, and
  an unloadable book. The three values schemas carry the field, written by
  hand (`design.md`, Implementation record); the drift tests pass.
- [x] 23.2 Add the resolver operation. It answers a chain's book, and nothing
  for a chain using the SDK's built-in addresses. No caller reads the map
  itself (D11).
  Unit: "A seller trades on two chains" at the resolver: `anvil` is named, and
  `base_sepolia` resolves to nothing.

  `market_alkahest.alkahest_address_book(section, chain_name)`. Unit (new
  `test_address_books.py`):
  `test_a_seller_trading_on_two_chains_resolves_only_the_named_chains_book`,
  an unparsed section, and no section. The kit's own readers moved to it in
  section 24.
- [x] 23.3 Bump `arkhai-kit-alkahest`, unless section 22 already did.
  **Verification checkpoint:**
  - 23.1–23.2;
  - `make test` in `kit/alkahest`;
  - `make check-packaging` and `make check-comment-hygiene`.

  No bump (section 22). `make test`: `kit/alkahest` 440, the VM and
  bare-metal storefronts with their drift tests 1142 + 475 and 513; `make
  check-packaging` and `make check-comment-hygiene` pass. End-to-end: none,
  since no deployed configuration states the table until 24.3.

## 24. Storefronts resolve address books and the seller account through Alkahest

Waits for `unbacked-bare-metal-listings` (D2). Delivers every storefront reading
its books through section 23's operation, and passing the resolved
chain-to-book mapping as data to the negotiation, policy, and codec packages,
whose `chain_config_paths` parameters stay as they are. It also delivers:
- API credits passing its wallet to readiness;
- `resolve_evm_wallet` removed;
- the seller's address optional;
- the repository's storefront configurations and charts moved to the map.

These are D10's and D11's storefront parts, with the delta scenarios "A seller
trades on two chains" and "The address names another account", at the
application level.

Files:
- `kit/storefront/src/market_storefront_kit/alkahest_clients.py`;
- the VM storefront's readers of a chain's book, in
  `domains/vms/storefront/src/market_storefront/`:
  - `server.py`, `settlement_composition.py`, `settlement_stages.py`, and
    `negotiation_runtime.py`;
  - `services/listing_service.py` and `services/admin_settle_service.py`;
  - `failure_actions.py`, `groups/escrow.py`, `groups/config.py`, and
    `utils/config.py`;
- the bare-metal storefront's, in
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`:
  - `runtime.py`, `settlement_stages.py`, and `deal_controls.py`;
  - `config.py` (`[Wallet].address` optional for a seller);
- the API-credit storefront's, in
  `domains/apicredits/storefront/src/apicredits_storefront/`:
  - `server.py`, `startup.py`, `settlement_stages.py`, `negotiation_runtime.py`,
    and `cli.py`;
  - `utils/config.py` (`resolve_evm_wallet` removed);
- the storefront configurations:
  - `domains/vms/storefront/storefront.{bob,alice}.toml`;
  - `domains/bare_metal/storefront/storefront.dev.toml`;
  - `domains/apicredits/storefront/storefront.credits.toml`;
  - each storefront's `settings.toml`;
- charts:
  - `helm/charts/storefront/{values.yaml,templates/_helpers.tpl,values.schema.json,tests/test_render.py}`;
  - `helm/charts/bare-metal-storefront/{values.yaml,values.schema.json,tests/test_render.py}`;
  - `helm/{values.schema.json,local-values.yaml,bare-metal-release-values.yaml,fixtures/eip191-evm-values.yaml,tests/test_release_topology.py}`;
- `scripts/tests/test_settlement_deployment_surfaces.py`;
- the storefronts' tests that state the old keys.
- Amended at section 23: `kit/alkahest`'s own readers of a chain's book, which
  move to `alkahest_address_book` with the storefronts that call them:
  - `settlement_config.py`'s client factory, which applies
    `address_config_path` to every chain, and its option builder;
  - `release_conditions.py`;
  - `chain_probe.py`'s `ProbedChain.from_config`.

- [x] 24.1 Each storefront resolves a chain's book through the `kit/alkahest`
  operation, and passes the mapping to the packages it composes. It adds no
  dependency on `kit/alkahest` to `arkhai-kit-policy`,
  `arkhai-vms-negotiation`, or `arkhai-kit-storefront` while
  `move-escrow-into-alkahest`'s scope exceptions stand (D11).
  - Application integration (VM storefront, its Alkahest client constructor
    injected through `VmCompositionSeams`): with `anvil` named in the map and
    `base_sepolia` not, these use the `anvil` book and the built-in addresses
    for `base_sepolia`:
    - client construction;
    - publication's release conditions;
    - escrow verification;
    - claim servicing.
  - Unit: the bare-metal and API-credit compositions hand the mapping on.

  The kit's readers resolve through `alkahest_address_book`: the client
  factory gives each chain its own book, the option builder and
  `release_conditions` read the section's, and `ProbedChain.from_config`
  takes a required `address_book`. Each storefront resolves the mapping in
  one place (VM's and API credits' `utils/config.py`
  `chain_address_books()`, bare metal's `runtime.py`) and hands it on. Three
  domain packages take it as data (`design.md`, Implementation record),
  each bumped: `arkhai-vms-negotiation` 0.5.0 → 0.6.0,
  `arkhai-apicredits-domain` 0.7.0 → 0.8.0, `arkhai-vms-settlement` 0.3.0 →
  0.4.0. No dependency was added to the three packages named;
  `kit/storefront` already took each chain's book as data. The CLI's touched
  local imports stay local, their reason beside them.
  - Application integration (VM, new `test_alkahest_address_books.py`, the
    real app with injected seams): the client policy gives `anvil` its book
    and `base_sepolia` none, and Alkahest is ready.
  - Unit (kit): `test_a_chain_the_table_names_no_book_for_uses_the_sdks_addresses`
    (release conditions on both chains) and
    `test_claims_on_each_chain_are_serviced_against_that_chains_book` (the
    conditional-escrow client's per-chain books, read from a private
    attribute).
  - Escrow verification has no two-chain test; the VM settle tests verify
    against the section's `anvil` book.
  - Unit: bare metal's
    `test_a_configured_alkahest_section_composes_its_client_and_worker` and
    API credits' `test_api_credit_chain_values_are_contributed_to_shared_factory`
    hand the mapping on; new `test_compute_lease_token.py` reads a native
    escrow on `anvil` through its book.
- [x] 24.2 The seller's wallet (D10):
  - API credits passes its wallet to readiness;
  - `resolve_evm_wallet` is removed;
  - a seller configuration may omit `[Wallet].address`.

  Application integration, through `StorefrontClient`'s settlement status:
  - a mismatched address leaves Alkahest unready with
    `alkahest.wallet_address_mismatch`, the storefront's other mechanisms ready,
    and no Alkahest option published;
  - an omitted address is derived from the key.

  Correction, recorded at section 22: the first bullet already held, since
  API credits' settlement composition passes its wallet to readiness. The
  storefronts' naming of the seller through `wallet_account_address`, which
  is what makes `[Wallet].address` optional, moved to section 22 (22.1's
  notes), with API credits' application test of the derived recipient.
  Bare metal's `WalletSettings.address` already defaults to empty. What
  remains here is `resolve_evm_wallet`'s removal and the application tests
  above.

  `resolve_evm_wallet` is removed. Application integration (API credits,
  `test_alkahest_release_conditions.py`):
  `test_an_address_naming_another_account_leaves_alkahest_unready` (Alkahest
  unready with the mismatch, a create supplying escrows refused 400) and
  section 22's omitted-address test. Bare metal's
  `test_an_address_naming_another_account_leaves_only_alkahest_unready` shows
  contact exchange ready beside the mismatch.
- [x] 24.3 Move the repository's storefront configurations and charts to
  `[Settlement.alkahest.address_books]`, and regenerate the values schemas with
  `make helm-values-schema`. The drift tests pass (D11).
  Chart render:
  - `make -C helm test-render`;
  - the storefront render tests' loader checks, run locally with
    `STOREFRONT_PYTHON` and `BARE_METAL_STOREFRONT_PYTHON` set (TESTING.md,
    "Chart Render Tests").

  Moved to the table: the four storefront configurations, `helm/local-values.yaml`,
  `helm/bare-metal-release-values.yaml`, and
  `helm/fixtures/eip191-evm-values.yaml`; the settings comments, VM's
  `config init` template, and both charts' `alkahestAddressBook` comments
  name it; `_address_paths` reads only it; `test_release_topology.py` and
  `test_settlement_deployment_surfaces.py` hold the configurations to it.
  The e2e `test_alkahest_trusted_oracle.py` states its book in the section
  (`e2e-tests`' floor on the kit `>=0.11.0`). No values schema needed
  regenerating beyond section 23's hand edit. `make -C helm test-render`
  passes with its loader checks run; `scripts/tests` 1585.
- [x] 24.4 Bump the three storefronts and `arkhai-kit-storefront`, and run
  `make lock`. **Verification checkpoint:**
  - 24.1–24.3;
  - `make test` in `kit/storefront`, `domains/vms/storefront`,
    `domains/bare_metal/storefront`, and `domains/apicredits/storefront`;
  - `make -C helm test-render`;
  - `make check-packaging` and `make check-comment-hygiene`.

  Owed by validation: `tests.yml`, job `release · deployment contracts`, where
  `make -C helm test-render` passes with the charts' address books under
  `[Settlement.alkahest.address_books]`.

  End-to-end: the seller storefronts publish, verify escrows, and service
  claims with the `anvil` book from the map:
  - `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, and `e2e_non_erc20_settlement`;
  - `e2e_bare_metal_mock_deal`;
  - `e2e_credits_deal`.

  This is the evidence for 24.1 and 24.3.

  `e2e_non_erc20_settlement`'s native-token case is the only evidence that
  the VM settle path hands `token_resource_from_accepted_escrow` the books;
  the escrow-kind dispatch's mapping in both negotiation packages is
  exercised by no test. No further bump: the storefronts were already bumped
  and `arkhai-kit-storefront` was unchanged here. `make test`: `kit/alkahest`
  441, the VM storefront 1144 + 476, bare metal 514, API credits 245; full
  `make test`, `make -C helm test-render`, and `make check-packaging` pass.

## 25. Buyers resolve address books through Alkahest

Waits for `unbacked-bare-metal-listings` (D2). Delivers the buyer CLIs reading
their books through section 23's operation, and their configurations moved to
the map (D11, "buyers included").

Files:
- the VM buyer's readers of a chain's book, in
  `domains/vms/buyer/src/arkhai_vms_buyer/`:
  - `settle_cli.py`, `escrow_cli.py`, `chain_cli.py`, and `config_cli.py`;
  - `deal_helpers.py`, `buyer_client.py`, `settlement_composition.py`, and
    `settlement_stages.py`;
- the API-credit buyer's, in
  `domains/apicredits/buyer/src/arkhai_apicredits_buyer/`: `settle_cli.py`,
  `buyer_client.py`, and `buy_cli.py`;
- the bare-metal buyer's chain configuration, if it states a book;
- the buyer configurations the e2e harness writes:
  - `e2e-tests/tests/e2e/roles/buyer_cli.py`;
  - `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`;
  - `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal_buyer_cli.py`;
  - `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py`;
- the buyers' tests that state the old keys.

- [x] 25.1 Each buyer CLI resolves a chain's book through the operation, and
  passes the mapping to the codec and negotiation packages it calls. Buyers keep
  their tolerance of a wallet mismatch (D11, D10).
  Unit, in each buyer's suite:
  - a buyer configuration with the map resolves `anvil`'s book;
  - a chain the map does not name uses the built-in addresses.

  Each buyer's `common.py` gains `chain_address_book` and
  `chain_address_books`, resolving through `alkahest_address_book`; every
  reader of a book calls them, and `resolve_alkahest_address_config_path` is
  removed. `settle_cli`, `escrow_cli`, and `buy_cli` hold a module-level
  `chain_address_book` seam. The bare-metal buyer states no book and is
  unchanged. Unit (new `tests/test_address_books.py` in each buyer):
  `test_a_buyer_configuration_with_the_table_resolves_anvils_book` and
  `test_a_chain_the_table_does_not_name_uses_the_built_in_addresses`. Readers
  are covered only through existing command tests with the seam replaced;
  `load_buyer_chain`'s default, `chain check`, `escrow show`, and `buy_cli`'s
  resolution have no test. VM buyer 210, API-credit buyer 33.
- [x] 25.2 The e2e harness writes buyer configurations with the map (D11).
  Verify: `make -C e2e-tests test-unit`.

  The harness's VM and API-credit buyers name `anvil`'s book in the table;
  `e2e-tests`' floors are `arkhai-vms-buyer>=0.9.0` and
  `arkhai-apicredits-buyer>=0.7.0`. `make -C e2e-tests test-unit`: 172; the
  lanes are the configurations' evidence. A search of `e2e-tests` finds
  neither retired key.
- [x] 25.3 Bump the VM, API-credit, and bare-metal buyers as changed, and run
  `make lock`. **Verification checkpoint:**
  - 25.1–25.2;
  - `make test` in `domains/vms/buyer`, `domains/apicredits/buyer`, and
    `domains/bare_metal/buyer`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: `e2e_deal_buyer_cli`, `e2e_buy`, and `e2e_credits_deal` fund
  escrows with the buyer's `anvil` book from the map, which is the evidence for
  this section.

  `arkhai-vms-buyer` 0.8.0 → 0.9.0 and `arkhai-apicredits-buyer` 0.6.0 →
  0.7.0, each with `arkhai-kit-alkahest>=0.11.0`; the bare-metal buyer
  unbumped. Full `make test` and `make check-packaging` pass. Sections 25
  and 26 shipped together, since buyers ignore the retired keys until 26
  refuses them.

## 26. The retired address-book keys are refused and migrated

Waits for `unbacked-bare-metal-listings` (D2). Delivers the refusal of the two
retired keys, each with a diagnostic naming the map, and the
configuration-migration tool moving either key into the map (D11). Delta: the
scenarios "A retired key is stated" and "A configuration is migrated".

Files:
- `kit/config/src/market_config/config_loader.py`: `ChainSettings` loses
  `alkahest_address_config_path`, and the loaders refuse it;
- `kit/config/src/market_config/settlement_migration.py`;
- `kit/alkahest/src/market_alkahest/settlement_config.py` (the section key
  refused);
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/config.py`
  and `domains/vms/buyer/src/arkhai_vms_buyer/deal_helpers.py` (their own
  `ChainSettings`);
- `kit/config/tests/unit/test_config_loader.py` and
  `test_settlement_migration.py`;
- the storefront and buyer `config migrate` tests
  (`domains/vms/storefront/tests/unit/cli/test_settlement.py`, and the VM
  buyer's).

- [x] 26.1 `[Chains.<name>].alkahest_address_config_path` and
  `[Settlement.alkahest].address_config_path` are each refused with a
  diagnostic naming `[Settlement.alkahest.address_books]`, in every
  storefront's and buyer's loader (D11). Unit: "A retired key is stated", for
  each key and each loader.

  `kit/alkahest`'s `retired_address_book_keys` finds either key in any
  spelling, and `retired_address_book_refusal` names the key and the table,
  never the value. Each role checks before resolving its section (`design.md`,
  Implementation record): the VM and API-credit storefronts through
  `retired_setting_problems` and, for VM, `refuse_retired_address_book_keys`
  before the release model; bare metal in its settings model; the VM and
  API-credit buyers in `common.refuse_retired_address_book_keys`.
  `AlkahestSettlementConfig` drops `address_config_path` and refuses it;
  `kit/config`'s `ChainConfig` and bare metal's `ChainSettings` drop the chain
  key. The values schemas drop the section key (and bare metal's the chain
  key), edited by hand; `alkahest.py`'s `anvil` diagnostics name the table.
  Unit, for both keys: `kit/alkahest`'s `test_address_books.py`, the VM
  storefront's `test_startup_refusal.py`, the API-credit storefront's
  `test_server_composition.py`, bare metal's `test_config_loader.py`, and the
  two buyers' `test_address_books.py`. The bare-metal buyer reads no book and
  has no refusal.
- [x] 26.2 The migration tool moves each retired key into the map (D11):
  - a per-chain key moves to its own chain;
  - the section key moves to the one configured chain, or to the chains whose
    per-chain keys name the same book;
  - where the tool cannot tell which chains a section key served, it refuses,
    naming both keys;
  - it refuses two different books for one chain.

  Unit (`test_settlement_migration.py`): each case, and an idempotent rerun.
  Application integration: the storefront's `config migrate --scope settlement
  --check` and `--write --backup`, and the buyer's `market config migrate`, move
  the keys ("A configuration is migrated").

  `migrate_address_books` moves each key as listed, removing an empty one and
  naming no value in a refusal; a book alone adds no mechanism to
  `priority`; the migrated candidate admits `probe_interval_seconds` and
  `rpc_timeout_seconds` and refuses either retired key remaining;
  `is_legacy_settlement_path` treats the section key as legacy. Migration
  matches the keys in their exact spelling. Unit
  (`kit/config/tests/unit/test_settlement_migration.py`): each listed case,
  trimming, and the rerun; "naming both keys" is read as the section key and
  the table. Untested: `Chains` against `chains`, the section key with no
  chain, an empty key's removal, and the candidate check. The command-level
  tests are unit tests of the command modules (no app drives a CLI):
  `test_settlement_migration_moves_the_retired_address_book_keys` (VM
  storefront) and `test_buyer_migration_moves_the_retired_address_book_keys`
  (VM buyer). `kit/config` 264, VM buyer 213, VM storefront unit 1147.
- [x] 26.3 A repository search finds the retired keys only in the migration
  code, the refusal diagnostics, and their tests (D11).

  Three readers' own names were renamed `address_book`:
  `verify_escrow_against_plan`'s keyword, `ProbedChain.address_config_path`,
  and `kit/storefront`'s `AlkahestChain.address_config_path`. The search then
  finds the keys in the migration, the refusal, their tests, and the tests
  asserting their absence. The operator documents naming them are closeout
  destinations (27.9).
- [x] 26.4 Bump `arkhai-kit-config` and every package whose loader changed. Run
  `make lock`, and `make helm-values-schema` if a model changed.
  **Verification checkpoint:**
  - 26.1–26.3;
  - `make test` in `kit/config`, `kit/alkahest`, the three storefronts, and the
    three buyers;
  - `make -C helm test-render`;
  - `make check-packaging` and `make check-comment-hygiene`.

  Owed by validation: `tests.yml`, job `release · deployment contracts`, where
  `make -C helm test-render` passes, and no chart value or fixture states a
  retired key.

  End-to-end: every Alkahest scenario boots on the map with the retired keys
  refused, which is the evidence that no deployment the pipeline runs still
  states one:
  - `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, and `e2e_non_erc20_settlement`;
  - `e2e_bare_metal_mock_deal`;
  - `e2e_credits_deal`.

  `arkhai-kit-config` 0.4.1 → 0.5.0; `arkhai-kit-storefront` 0.9.0 → 0.10.0,
  the storefronts' exact pins moving with it; floors on
  `arkhai-kit-config>=0.5.0` in the VM and API-credit storefronts and buyers.
  Full `make test` (with `make -C helm test-render` and its loader checks)
  and `make check-packaging` pass.

  Round 2's triage fixes (review 86):
  - F1 (recorded in D11): a seller's migration names, as `note:` lines from
    `SettlementMigrationResult.notices`, each configured chain the section key
    does not move to and the book its claims will use; a buyer's names none.
    The delta adds the scenario "The section key does not reach every chain".
  - F2: the VM and API-credit storefronts refuse the retired keys inside
    `chain_address_books()` too, sharing
    `utils.config.retired_address_book_problems` with the startup refusal;
    VM `escrow show` and API-credit `publish --chain` report it and exit 2.

  Tests: `test_settlement_migration.py`'s notice cases (a seller's notices
  and `note:` lines with no value printed, a chain the table names, a buyer
  naming none, a key carried to every chain); the command-module tests
  `test_escrow_show_refuses_a_retired_address_book_key` and
  `test_publishing_an_alkahest_rate_refuses_a_retired_address_book_key`.
  `kit/config` 267, the VM storefront 1148 (1 skipped) and 476, the
  API-credit storefront 248; full `make test` and `make check-packaging`
  pass.

## 27. Closeout

Confirm and promote the verified design, then archive last. This covers D1–D23
and every delta requirement. The eleven parts follow
`openspec/README.md#plan-closeout-requirements`, in order. Closeout changes no
code: a part that needs a code, lock, or test change returns the change to
implementation.

- [x] 27.1 **Comment hygiene — confirm.**
  - Run `make check-comment-hygiene`.
  - Read every comment and docstring that sections 1–26 added or rewrote, for
    current-system rationale with no change, review, or migration narration:
    - `database.py`'s, if 5.3 rewrote one;
    - the migrations' docstrings (the reservation-state conversion, the claim
      table, `awaiting_delivery`);
    - the route grammar's refusal text;
    - the mock-route template;
    - the address-book refusals.

  A needed correction returns the change to implementation.

  `make check-comment-hygiene` passes. Read in the diff from the merge base
  `c82de9861`: 5.3 rewrote no `database.py` comment; both
  retired-reservation-state migrations, the seller-dispatch claim migration and
  `claim_seller_dispatch`, the route grammar's comment and refusals, the
  mount's prefix comment, and the address-book refusals all state current
  invariants and reasons. Their "retired key" wording names what the code
  refuses, not a history. No correction needed.
- [x] 27.2 **Import placement — confirm.** Check that every import sections 1–26
  added or touched is at module level, unless a verified cycle or a recorded
  lazy-load reason keeps it local. A needed move returns the change to
  implementation.

  The production diff adds two function-local imports, both with a recorded
  reason: the settings must resolve after the root `--config` option
  (`apicredits_storefront/cli.py`'s `publish_cmd`; `market_storefront/groups/escrow.py`'s
  `show_cmd`). Every other added import is at module level. No move needed.
- [x] 27.3 **Documentation compliance.** Check D1–D23 and the owner's pre-1.0
  principle against `openspec/README.md`'s placement rules, against the
  promotion record below, and against the code:
  - normative behaviour in specs, through the deltas;
  - rationale in the companions;
  - repository rules in `ARCHITECTURE.md`;
  - operator behaviour in `DEPLOYMENT_AND_CONFIG.md` and the quickstarts;
  - versioning in `RELEASING.md`.

  Record a disposition for every decision.

  Dispositions:
  - Normative, through the deltas: D3, D4, D5, D8, D9, D10, D11, D12, D13,
    D14, D15, D17. Each lands in the spec its delta targets (27.11).
  - Rationale, in companions: D3, D6, D14 (`physical-provisioning`); D5
    (`site-capacity`); D8 (`settlement-servicing`); D9 (new
    `introduction-delivery` companion); D10 and D11 (`settlement-configuration`).
  - Repository-wide, in `ARCHITECTURE.md`: D3's composition-time overlap
    refusal and grammar; D14 as a worked five-piece instance; D4's one push
    under "Site authority", whose old sentence section 8 found false; the
    pre-1.0 pointer under "Operators".
  - Operator behaviour, in `DEPLOYMENT_AND_CONFIG.md` and the quickstarts:
    D10, D11, D13's coordinated upgrade, and the pre-1.0 sentence. Also
    `docs/configuration.md` for D4: its `release_capacity` row still called the
    action an explicit admin repair, which no longer holds now the policy runs
    only on the pull path, so it was corrected.
  - Versioning, in `RELEASING.md`: the pre-1.0 principle.
  - Scope and sequencing, not promoted: D1, D2, D23. D1's hand-offs are in the
    other changes' proposals and the index.
  - Operational text only, written in their sections: D7 (the training README
    and `RELEASING.md`'s examples), D16, D18, D19, D21, D22. Nothing permanent
    describes them, as the decision map says.
  - D20: `physical-provisioning`'s Evidence section names the moved suites.
  - Hand edit to a spec with no delta: `contact-exchange-settlement`'s
    scenario "A deletion overlaps a start that has already revealed" now says
    the start that claims the seller-side delivery delivers it, which agrees
    with D9 (7.5).

  Checked against the code: the promoted statements were verified against
  this branch as they were written.
- [x] 27.4 **Narrative compression.** Compress the section notes to final
  behaviour, validation evidence, deferred work, and destinations. Move durable
  rationale, plan corrections, and declined review items into `design.md`
  first. The open question on per-adapter migration chains stays in
  `design.md`.

  Sections 1–26 were compressed from about 4,225 lines to about 2,270. Every
  task statement and its prescribed verification stays as written, and so do
  the plan's own amendments. The branch-sharing preambles are reduced to a
  line, since the branch has merged. The fresh-context-check and handoff
  narration was removed. What it carried that was worth keeping moved first
  to `design.md`, "Implementation record":
  - the owner's decisions A and B, and the version-bump rules;
  - twenty plan corrections;
  - defects found outside scope, which no change yet owns.

  The open question stays in `design.md`.
- [x] 27.5 **Roadmap currency.** In `docs/development/ROADMAP.md`:
  - Goal 1: remove the open-gap row this change owns, which begins "Small
    defects and dead surfaces in the compute family". State in the current-state
    prose what is now true:
    - unmatched routes answered by cause;
    - the typed mock and worker surfaces;
    - the compute provisioning contract at major 3.
  - Goal 6: confirm that the unowned payout-account gap row, added at design, is
    still accurate.

  Goal 1: the row is removed. A current-state paragraph now covers:
  - unmatched routes answered by cause, and the composition-time overlap
    refusal;
  - the family-owned typed mock mechanism and the typed worker controls;
  - the compute provisioning contract at major 3, with its coordinated
    upgrade.

  Goal 6: the payout row is accurate against D10 as built, and unchanged.
- [x] 27.6 **Campaign index currency.** Update this change's row in
  `openspec/changes/README.md`: status `in closeout`, and notes naming the
  validation and destinations. Update the architecture campaign's paragraph,
  which names this change as the owner of two judgement items: say that both
  are settled, and where (D6, in `physical-provisioning`'s companion; D7,
  carried to `repair-rl-training-tooling`). Leave other rows' `Depends on` for
  archive cleanup. Run `make check-change-index`.

  Done. The row is `in closeout`, and its notes name validation 94 and the
  destinations. The architecture campaign's paragraph says both judgement
  items are settled: D6 in `physical-provisioning`'s companion, "Compute
  composition"; D7 by removal, with the tooling owned by
  `repair-rl-training-tooling`. No other row changed, and the campaign has no
  dependency graph naming this change. `make check-change-index` passes.
- [x] 27.7 **Packaging.** Confirm that these pass against the last
  implementation commit:
  - `make check-packaging`;
  - `make check-architecture-change CHANGE=resolve-compute-family-findings`, since
    the change owns no `ARCHITECTURE.toml` row.

  Record whether any `.agents/`, `.claude/`, or `.codex/` file was touched, and
  run `make check-agent-skills` if one was.

  Run at `837e82ab4`, whose code is `36084dcf9`'s:
  - `make check-packaging` passes: locks, Python selection, layout, and the
    layer, scope, dependency, and kind rules;
  - `make check-architecture-change` passes: the change owns no row;
  - `.claude/change-steps.toml` was touched (it allows the implement step
    `make helm-values-schema`), so `make check-agent-skills` ran and passes.

  The byte-for-byte schema check that `design.md`'s Implementation record
  lists as owed was not run here: `make helm-values-schema` is denied to the
  closeout step, and closeout edits no generated file. The drift tests, which
  compare parsed JSON, pass, as does validation 94's `test-render`.
- [x] 27.8 **End-to-end pipeline.** Confirm that the latest validation covers the
  last implementation commit with the three lanes passing. Record its run and
  the scenarios that exercise this change:
  - `e2e_compute_dynamic_listings` (section 8);
  - `e2e_vm_introduction` and `e2e_bare_metal_introduction` (section 7);
  - `e2e_bare_metal_mock_deal` (sections 16–19 and 21);
  - the VM deal scenarios (sections 3, 16, 17, 21, and 24–26);
  - `e2e_credits_deal` (sections 18 and 24–26).

  Also record the `tests.yml` `release · deployment contracts` job that
  sections 20, 24, and 26 owe. An unrelated blocker names its cause and its
  owner, and leaves what it gates unrun.

  Validation 94 covers `36084dcf9`, the last implementation commit. Since then
  `HEAD` has changed only `openspec/`, and closeout changes no code, so the
  evidence describes the code this closeout carries. Its parts passed: local,
  Helm, pipeline, and CI.
  - Pipeline run 40733870392 passed all three lanes: `e2e-vm` 134 passed,
    `e2e-bare-metal` 60, `e2e-apicredits` 1. Those lanes hold the scenarios
    listed above: `e2e_compute_dynamic_listings`, `e2e_vm_introduction`, and
    the VM deal scenarios in `e2e-vm`; `e2e_bare_metal_introduction` and
    `e2e_bare_metal_mock_deal` in `e2e-bare-metal`; `e2e_credits_deal` in
    `e2e-apicredits`. The record passes each lane as a whole and does not map
    scenarios by name.
  - `tests.yml` run 40733888468: the owed job `release · deployment
    contracts` passed, and its `make -C helm test-render` completed. It is
    owed by 20.3 (`mode` gone), 24.4 (address books under
    `[Settlement.alkahest.address_books]`), and 26.4 (no retired key in any
    value or fixture). The run's other failures are in jobs nothing owes:
    `py · vms-storefront` (three loop-gate and retention timeouts) and
    `py · bare-metal-storefront` (`test_abort_all_is_not_previewed`). Both
    fail the same way in `dev`'s baseline, run 40563728160 at `c82de9861bfe`.

  No blocker.
- [x] 27.9 **Promotion.** Write every destination in the promotion record below,
  and complete its third column. Hand-edit each spec's Evidence section where
  the tests it names moved. That includes `physical-provisioning`'s, for the
  suites section 5 moved. The archive in 27.11 merges the deltas. Add the new
  `introduction-delivery` companion to `openspec/specs/README.md`.

  Every destination is written, and the record's third column is complete.
  `physical-provisioning`'s Evidence section names the VM adapter's suites;
  no other spec cited the moved files. The introduction-delivery companion is
  new, with its row in `openspec/specs/README.md`.

  Two destinations that sections 7 and 8 found are written too:
  - `contact-exchange-settlement`'s scenario;
  - `ARCHITECTURE.md`'s "Site authority".

  The smoke-test profile's `seller.wallet_address` sentence in
  `DEPLOYMENT_AND_CONFIG.md` now says the value is absent when the agent
  derives its address.
- [x] 27.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=resolve-compute-family-findings` and resolve
  every match. Then run the pinned
  `bunx @fission-ai/openspec@1.14.0 validate resolve-compute-family-findings --strict`
  (or `make check-change`, which runs it).

  `make check-change CHANGE=resolve-compute-family-findings` passes every check:
  - comment hygiene;
  - agent skills;
  - documentation citations, including the new introduction-delivery
    companion;
  - the task list and the change index;
  - `openspec validate --strict`.
- [x] 27.11 **Archival — last.** Run the pinned
  `bunx @fission-ai/openspec@1.14.0 archive resolve-compute-family-findings -y`
  without `--skip-specs`. It merges the deltas once into these specs:
  `site-capacity`, `physical-provisioning`, `compute-provisioning-contract`,
  `market-composition`, `storefront-publication`, `settlement-servicing`,
  `introduction-delivery`, and `settlement-configuration`.
  Then:
  - read each merged requirement in its spec's diff;
  - point this change's index row at the archive, with status `in closeout`;
  - run the pinned `validate --specs --strict` and `make check-change-index`.

  Archived as `openspec/changes/archive/2026-10-28-resolve-compute-family-findings/`,
  with the deltas merged and no `--skip-specs`: implementation had written no
  permanent `spec.md`, so nothing was merged twice. The pinned validator ran
  through `npx`, as `scripts/check_change.py` does where `bunx` is absent. It
  reported 13 requirements added and 12 modified across the eight specs, and
  each of the 25 appears exactly once under its spec's `## Requirements`.
  Every line the merge removed belongs to a requirement a delta modifies, and
  nothing else in those specs changed. The index row links the archive, with
  status `in closeout`. `make check-change` passes, which runs
  `validate --specs --strict` and the change-index check.

**Closeout verification:** the eleven recorded outcomes, valid synchronized specs,
resolvable citations, and a current index.

## Decision-to-section map

| Decision / requirement | Implementation | Promotion |
|---|---|---|
| D1 scope: items kept, dropped, and handed over | none: no code; recorded in `design.md` and the other changes' proposals | 27.6 |
| D2 sequencing against `unbacked-bare-metal-listings` | the gating note above; each of sections 1–9 names its shared files, derived from the branch at `c6e2108` | 27.6 |
| D3 unmatched routes, grammar, and overlap; "A site authority answers an unroutable request…"; "The provisioning service answers an unroutable request…"; "The family client names an unauthenticated answer" | 10, 12, 13 | 27.9 |
| D4 senderless callbacks removed; "Deal-scoped lifecycle events" | 8 | 27.9 |
| D5 retired reservation states; "A stored reservation in a retired state is converted at upgrade"; "Reservation lifecycle"; the lease-transition and truncation requirements; "Explicit contract incompatibility" (the lease state) | 14, 15, 16 | 27.9 |
| D6 migration modules name VM's tables | 5.3 (a confirmation: the false comment left `dev` with the pools-7 closeout) | 27.9 |
| D7 RL training CLI leaves `kit/policy` | 6.1–6.3, 6.5 | 27.6 |
| D8 servicing: reporting, awaiting delivery, settle wait; the four `settlement-servicing` deltas | 11, 18 | 27.9 |
| D9 claim-once seller delivery; "Delivery fires once per reveal…" | 7 | 27.9 |
| D10 wallet address and key; "A seller's wallet address and key name one account" | 22, 24.2, 25.1 | 27.9 |
| D11 address books per chain; "Alkahest address books are named per chain…" | 23, 24, 25, 26 | 27.9 |
| D12 delivery conflict 409; "A bare-metal delivery that conflicts…" | 19.2 | 27.9 |
| D13 schedule host and begin; "A schedule response names…"; "Bare-metal begin reads…"; "Explicit contract incompatibility" | 16, 19.1, 19.3 | 27.9 |
| D14 mock mechanism the family's; "Compute-owned caller contract"; "Compute mock executors share one compute-family mechanism" | 2, 3, 21 | 27.9 |
| D15 typed worker controls; "Compute-owned caller contract" | 17.1–17.2 | 27.9 |
| D16 pool overrides at `POOL_OVERRIDES_PATH` | 9 | none: no permanent document describes the binding |
| D17 operator guest names; "An operator-named VM guest satisfies…" | 4 | 27.9 |
| D18 policy refusal messages | 6.4 | none: the messages are the documentation |
| D19 convergence counts in the log text | 17.3 | none |
| D20 VM suites and the relay index | 5.1–5.2 | 27.9 (spec Evidence) |
| D21 VM target lookup removed | 1 | none: nothing permanent names it |
| D22 `[provisioning] mode` removed | 20 | 20.2 (operational text) |
| D23 deltas | `specs/` | 27.11 |
| Pre-1.0 incompatible changes (owner) | none: guidance | 27.9 |
| Open question: per-adapter migration chains | none: deferred | 27.4 keeps it in `design.md` |

## Design promotion record

Planning settled each destination below; closeout (27.9) completed the third
column.

| Accepted knowledge | Permanent destination | Written |
|---|---|---|
| D3: the unmatched-route answers, the pattern grammar and overlap refusal, and the clients' report of an unauthenticated answer | `openspec/specs/physical-provisioning/spec.md`, "The provisioning service answers an unroutable request by what failed to match" and "The family client names an unauthenticated answer"; `openspec/specs/site-capacity/spec.md`, "A site authority answers an unroutable request by what failed to match"; all through the archive | Merged by the archive (27.11) |
| D3: why an unroutable answer is unsigned; why the grammar is restricted; that a route needing more adopts an established path-template grammar | `openspec/specs/physical-provisioning/architecture.md`, "Canonical requests, durable replay, and signed responses" | Yes: `physical-provisioning/architecture.md#canonical-requests-durable-replay-and-signed-responses`, two paragraphs |
| D3: the service refuses overlapping contributions when it composes its table | `docs/development/ARCHITECTURE.md`, "Route contracts and their HTTP binding", the paragraph beginning "A domain that contributes routes" | Yes: `ARCHITECTURE.md#route-contracts-and-their-http-binding`, with the grammar and the unsigned answers |
| D4: the one lifecycle event provisioning pushes | `openspec/specs/compute-provisioning-contract/spec.md`, "Deal-scoped lifecycle events", through the archive | Merged by the archive; also `ARCHITECTURE.md#site-authority`, whose deal-scoped events sentence now names the one push (a destination section 8 found) |
| D13 and D5: the schedule response's host and machine; contract major 3 | `openspec/specs/compute-provisioning-contract/spec.md`, "A schedule response names the scheduled resource's host and machine" and "Explicit contract incompatibility", through the archive | Merged by the archive |
| D13: a provisioning service and the storefronts and clients that call it upgrade, and roll back, together across major 3 | `docs/development/DEPLOYMENT_AND_CONFIG.md`, beside its statement that sites and storefronts are upgraded together (added by section 16's review) | Yes: `DEPLOYMENT_AND_CONFIG.md#storefront-listing-shapes-and-pool-overrides`, after "Sites and storefronts are upgraded together" |
| D14 and D15: the family's mock-route template, models, and client; the typed worker controls | `openspec/specs/physical-provisioning/spec.md`, "Compute-owned caller contract"; `openspec/specs/market-composition/spec.md`, "Compute mock executors share one compute-family mechanism"; both through the archive | Merged by the archive |
| D14: the mock mechanism as a worked instance of the five-piece route pattern | `openspec/specs/physical-provisioning/architecture.md`, "Compute composition"; `docs/development/ARCHITECTURE.md`, "Family kits", the paragraph beginning "Executor selection is one table", whose list names the rule route service | Yes: `physical-provisioning/architecture.md#compute-composition`; `ARCHITECTURE.md#family-kits`, a paragraph after the mechanism's list |
| D5: the remaining reservation states and the upgrade conversion | `openspec/specs/site-capacity/spec.md`, "Reservation lifecycle", "The lease lifecycle's writes are conditional transitions", "Lease truncation neither resurrects nor extends a lease", "A reservation's lease tail is written once", and "A stored reservation in a retired state is converted at upgrade", through the archive | Merged by the archive |
| D5: why a conversion keeps each row's capacity effect, rather than refusing the upgrade | `openspec/specs/site-capacity/architecture.md`, "Reservation lifecycle" | Yes: `site-capacity/architecture.md#reservation-lifecycle`, with why no operation writes a named state |
| D6: the service's migration history names the tables its database holds | `openspec/specs/physical-provisioning/architecture.md`, "Compute composition" | Yes: `physical-provisioning/architecture.md#compute-composition`, with the per-adapter-chain limit |
| D8: the awaiting-delivery cadence and its journal mark; retry reporting; the settle wait | `openspec/specs/settlement-servicing/spec.md`, its four requirements, through the archive | Merged by the archive |
| D8: why the mark is a flag, not a state (rollback); how it differs from the deferred outcome | `openspec/specs/settlement-servicing/architecture.md`, "Servicing lifecycle" | Yes: `settlement-servicing/architecture.md#servicing-lifecycle`, four paragraphs |
| D9: one dispatch claimed by the completing start; no counterparty-triggered re-send | `openspec/specs/introduction-delivery/spec.md`, "Delivery fires once per reveal and re-delivery is explicit", through the archive | Merged by the archive; `contact-exchange-settlement/spec.md`'s scenario "A deletion overlaps a start that has already revealed" corrected by hand to the claiming start (7.5) |
| D9: the buyer-retry limit; why a new start, not a replay, completes a reveal; why the claim is its own table | `openspec/specs/introduction-delivery/architecture.md` (new), and its row in `openspec/specs/README.md` | Yes: `introduction-delivery/architecture.md` (new), and its row in `openspec/specs/README.md` |
| D10 and D11: one seller account; address books per chain | `openspec/specs/settlement-configuration/spec.md`, through the archive; `openspec/specs/settlement-configuration/architecture.md`, where it lists an empty wallet address among the blockers (added at section 22); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover", "Bare-metal role configuration", and "Storefront agents: pass-through configuration", whose `alkahestAddressBook` paragraph names the retired keys (added at section 23); `docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md`, `docs/buyer-quickstart.md`, and `docs/cookbooks/vllm-apicredits-seller.md`, wherever each names a book or the seller's address | Merged by the archive; yes: `settlement-configuration/architecture.md#readiness-publication-and-selection`, `#one-seller-account`, `#alkahest-address-books`; `DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover`, `#bare-metal-role-configuration`, `#storefront-agents-pass-through-configuration`, and the smoke-test profile's `seller.wallet_address`; the four quickstarts and cookbook |
| D12 and D13: the bare-metal delivery conflict, and begin | `openspec/specs/storefront-publication/spec.md`, through the archive | Merged by the archive |
| D17: operator guest names | `openspec/specs/physical-provisioning/spec.md`, through the archive | Merged by the archive |
| D20: the moved suites | `openspec/specs/physical-provisioning/spec.md`, its Evidence section | Yes, by hand: the relay and pool-configuration evidence names the VM adapter's suites |
| D4: the failure policy is the pull path's | `docs/configuration.md` (written at section 8) | Yes; the `release_capacity` row corrected at closeout |
| Pre-1.0 incompatible changes; versioned contracts are versioned, not changed in place; neither applies at or above 1.0.0 | `docs/development/RELEASING.md`, "Versioning policy"; a pointer in `docs/development/ARCHITECTURE.md`, "Operators"; the owner's one sentence in `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Profile-based configuration" | Yes: `RELEASING.md#versioning-policy`; `ARCHITECTURE.md#operators`; `DEPLOYMENT_AND_CONFIG.md#profile-based-configuration` |
| Goal 1 gap closed; Goal 6 payout gap | `docs/development/ROADMAP.md`, Goal 1 and Goal 6 | Yes: Goal 1's row removed and its current state extended; Goal 6's row confirmed accurate, unchanged |
| Campaign status | `openspec/changes/README.md`: this change's row and the architecture campaign's paragraph | Yes (27.6, 27.11) |
| Implementation record: plan corrections, owner decisions, and defects found outside scope | `design.md`, "Implementation record" (change history, not permanent) | Yes (27.4) |
