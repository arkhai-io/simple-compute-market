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
merged (design D2). Sections 1–9 do not wait. Each of them names every file it
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

Shared with the branch: `kit/site/pyproject.toml`'s version line, and locks. The
branch edits `kit/site`'s `auth.py`, `projections.py`,
`tests/integration/test_site_auth_middleware.py`, and
`tests/unit/test_projections.py`, none of which this section touches.

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

  Done. The method's removal left `ledger.py`'s `sqlalchemy.func` import and its
  `VM_OFFERING_MODE` constant unread, so both went too. Library integration:
  `test_a_vm_reservation_names_its_target_once` (`kit/site`'s `test_ledger.py`)
  commits a VM reservation, records its target through
  `record_executor_target_in_session`, and reads it through `get_reservation`:
  `executor_target` is the target and the payload has no `vm_target`; passes.
  Search, outside `.venv`s: no caller of the method remains; every other
  `vm_target` match is a job parameter, a VM fulfillment-request payload, the
  operator client's `CreateVmRequest`, a legacy migration, or a test asserting
  the key's absence from a storefront result. No reservation-payload reader.
- [x] 1.2 Bump `arkhai-kit-site` by a minor version, since a public method is
  removed. Run `make lock`.

  `0.10.1` → `0.11.0`. No consumer called the method, so no floor is raised;
  `make lock` updated the locks that resolve it.
- [x] 1.3 **Verification checkpoint.**
  - Library integration: `kit/site`'s `test_ledger.py`.
  - Run `make test` in `kit/site`, `kit/site-client`, and
    `provisioning/compute/service`, which composes the ledger.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: no scenario reads the removed lookup or key, and none is owed.

  `make test`: `kit/site` 289 passed (unit and library integration);
  `kit/site-client` 57 passed (unit); `provisioning/compute/service` 536 passed
  (unit and application integration), against `arkhai-kit-site` 0.11.0.
  The full `make test` passes. `make check-packaging` passes. `make
  check-change` passes its comment-hygiene, agent-skill, task-list, index, and
  OpenSpec checks, and fails only on the citation of
  `openspec/specs/introduction-delivery/architecture.md`, which closeout
  creates (27.9). The end-to-end statement stands: no scenario reads the lookup
  or the key.

  Handoff: nothing resisted. The fresh-context check found no guidance
  violation; it asked only that the comment-hygiene result be recorded, as it
  now is.

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

Shared with the branch:
- **The contracts' `__init__.py`.** The branch adds `WorkerPauseResponse` inside
  the `.system` import block and after `"VersionResponse"` in `__all__`. This
  section adds its own import block between the `.jobs` and `.system` blocks,
  and its names after `"JobSubmitResponse"`, so there are unchanged lines
  between the two sides' hunks.
- **Version lines and locks.** The contracts' and the client's `pyproject.toml`
  version lines, and the client's floor on the contracts, which the branch also
  raises.
- **The client's `client.py`** is not touched. The branch rewrites it, so the
  new client lives in a module of its own.

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

  Done in `compute_provisioning_contracts/mock_rules.py`. Beside the five
  declarations the mount gives `operation(action)`, `declaration(action)`, and
  the paths a client sends (`rules_path`, `rule_path`, `rule_resume_path`,
  `evaluate_path`), so the client builds no path of its own. It refuses a
  prefix that is not literal path segments, since the prefix enters the
  patterns unescaped. The models: `MockRuleCreate` (the rule request, which
  the client sends and section 3's adapters will read), `MockRuleAdded`,
  `MockRuleView`, `MockRuleDeleted`, `MockRuleResumed`, and `MockJobEvaluation`
  (the dry run's report, identical in both adapters today). The evaluate
  request stays each domain's: its fields are the domain's job parameters.
  Unit (`test_mock_rules.py`, contracts): each mount's declarations equal the
  hand-written entries copied from VM's and bare metal's route modules as they
  stand; both mounts compose into one table; every path the mount builds
  resolves to its route and resource; non-literal prefixes are refused; the
  models validate hand-written examples of the shapes the routes answer.
  Passes. That `MockJobEvaluation` matches both adapters' evaluate responses
  field for field was read, not tested: no route answers with it until
  section 3, whose application integration checks it.
- [x] 2.2 `MockRuleRouteService` answers with the contracts' models (D14; delta
  `market-composition`, "Compute mock executors share one compute-family
  mechanism"). Unit (`provisioning/compute/tests/unit`, the executor-mock
  suites): every route-service answer validates as its model.

  `add` takes a `MockRuleCreate` or a mapping, so the adapters, which still
  pass `body.model_dump()` until section 3, keep working. Unit
  (`test_executor_mock.py`): add, list, delete, and resume each return their
  model, compared by equality with the expected model, and a rule given as a
  mapping is read; passes.

  Plan correction: the plan left the adapters' controllers to section 3, but
  their rule routes declared `-> dict` and `-> list[dict]`, which FastAPI takes
  as the response model and refuses a returned model with
  (`ResponseValidationError`): the service's integration suite failed 10 tests
  on the first full run. The rule routes of both adapters'
  `controllers/test_controller.py` therefore declare the family's models in
  this section (`MockRuleAdded`, `list[MockRuleView]`, `MockRuleDeleted`,
  `MockRuleResumed`), and both adapters raise their floor on the contracts to
  `0.10.0` and take their one bump of the change here: the VM adapter `0.13.1`
  → `0.14.0`, the bare-metal adapter `0.9.2` → `0.10.0`. Neither raises its
  floor on `arkhai-compute-provisioning`, on the reasoning, not tested, that a
  model annotation also validates the dicts an older route service returns.
  The branch also bumps both adapters' version lines, an overlap D2 admits (a
  version line); the contracts floor lines are not the branch's (section 3's
  shared-file notes). The request models, the evaluate route, and VM's
  `system_model.py` stay for section 3, whose tasks are amended to take the
  rest; sections 3.4 and 4.3 bump neither adapter again.
- [x] 2.3 Add `MockRuleClient` and `SyncMockRuleClient`. Each is constructed over
  the family client's authenticated transport with a `MockRouteMount`. Each
  method signs from the mount's declarations and returns the family's models
  (D14).
  Unit (`provisioning/compute/client/tests/unit`):
  - For both mounts, each method sends its path and signs its operation.
  - Answers parse into the models.
  - The sync and async clients have the same public methods and signatures
    (TESTING.md, "Sync/async client parity").

  Done in `compute_provisioning_client/mock_rules.py`, in its own module so the
  branch's rewrite of `client.py` does not meet it. `evaluate_job` takes the
  job as a mapping, since its fields are the mounting domain's. Unit
  (`test_mock_rules.py`, client): the real async and sync family clients send
  through an `httpx.MockTransport` that resolves each request against a table
  assembled from the mount's declarations and verifies its signature over that
  route's operation and resource, for the VM and bare-metal mounts; the
  recorded method, path, operation, and resource match each call, and every
  answer parses into its model. The parity test compares the two classes'
  public methods and signatures. Passes. TESTING.md puts the parity guardrail
  in the owning service's unit suite, so section 3 adds the pair to
  `test_provisioning_client_contract.py` (amended into 3.3).
- [x] 2.4 Bump `arkhai-compute-provisioning-contracts`,
  `arkhai-compute-provisioning-client`, and `arkhai-compute-provisioning` by a
  minor version each, since the route service's answers change type. Run
  `make lock`.

  Contracts `0.9.1` → `0.10.0`; client `0.7.0` → `0.8.0`; family kit `0.19.1`
  → `0.20.0`. The client's and the family kit's floors on the contracts rise to
  `0.10.0`, since both import the new models. `make lock` updated every lock
  that resolves them.
- [x] 2.5 **Verification checkpoint.**
  - Unit: 2.1–2.3.
  - Run `make test` in `provisioning/compute/contracts`,
    `provisioning/compute/client`, and `provisioning/compute`.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  Application integration is section 3's, where the template is mounted.

  End-to-end: none, since nothing mounts the template yet. No scenario is owed.

  `make test`: contracts 71 passed, client 63 passed, family kit 237 passed
  (unit and library integration); with the controllers typed (2.2's
  correction), `provisioning/compute/service` 536 passed (unit and application
  integration, its rule routes answering through both adapters), the VM
  adapter 37 and the bare-metal adapter 46. The full `make test` passes. `make
  check-packaging` passes. `make check-change` passes but for the closeout
  citation section 1 notes. The end-to-end statement stands: the routes'
  paths, operations, and answer shapes are unchanged and nothing mounts the
  template yet.

  Handoff: FastAPI takes a route's return annotation as its response model,
  so changing what a route service returns means changing its bindings'
  annotations in the same commit. The fresh-context check found comments
  describing the mount as already in use, a test docstring narrating history,
  and evidence wording that outran the tests; all were corrected, and the
  work this section leaves to section 3 is amended into 3.3 and 3.4.

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

Shared with the branch:
- **Version lines, floors, and locks:**
  - `pyproject.toml` version lines of the VM adapter, `arkhai-bare-metal`, and
    the bare-metal adapter. The VM operator client's `pyproject.toml` is not
    shared;
  - the service's `dev` floor on `arkhai-compute-provisioning-client`, which
    the branch raises to `0.8.0`, the version section 2 bumps the client to;
  - locks.

  The adapters' and the operator client's floors on the contracts, if raised
  for `MockRouteMount`, are not lines the branch edits. In the bare-metal
  adapter, one unchanged line separates that floor from the branch's.
- **`arkhai_bare_metal/__init__.py`.** The branch adds names to the
  `.projections` and `.schema` import blocks and to `__all__`. This section
  edits the `.provisioning_client` import block, which sits above the `.schema`
  block with four unchanged lines between, and the
  `"BARE_METAL_PROVISIONING_ROUTES"` entry of `__all__`, away from the branch's
  entries.
- **`test_system_api.py`.** The branch edits its imports and `TestWorkerControls`.
  This section edits only `TestEvaluateJob`, below `TestMockedExecution`, or
  leaves it on the conftest fixture unchanged.
- **`test_provisioning_client_endpoint_coverage.py`.** The branch edits the two
  assertions of `TestSystemClientEndpointCoverage`. This section edits only
  `TestBareMetalTestRouteCoverage`, two classes below.

The e2e harness keeps its own client until section 21. The paths and signed
operations do not change, so it keeps working.

- [ ] 3.1 VM's `routes.py` replaces its hand-written test entries with
  `MockRouteMount("/test", "provisioning_test").route_declarations()`. VM's test
  controller answers with the family's models. VM's own mock-rule models in
  `models/system_model.py` are removed (D14).
  Unit (`provisioning/compute/service/tests/unit/test_route_binding.py` and
  `test_route_table_composition.py`):
  - every mounted route resolves to exactly one contract;
  - every contract resolves to a mounted route;
  - VM's paths and operations are unchanged.
- [ ] 3.2 Rename bare metal's `provisioning_client.py` to `provisioning_routes.py`
  and reduce it to bare metal's two mount values. The bare-metal adapter builds
  the mount from them and contributes its declarations (D14).
  Verify:
  - `make check-architecture` passes with `arkhai-bare-metal` declaring no
    compute dependency.
  - The adapter's route contracts equal the mount's declarations, which 3.1's
    binding tests check.
- [ ] 3.3 The service integration harness calls the family client for rules and
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
- [ ] 3.4 Bump `arkhai-bare-metal` by a minor version, since the module is
  renamed. Bump the VM and bare-metal adapters and the VM operator client.
  Raise the service's `dev` floor on the client to section 2's bump. Run
  `make lock`.

  Amended in section 2: both adapters took their bump there (VM `0.14.0`,
  bare metal `0.10.0`), so this task does not bump them again.
- [ ] 3.5 **Verification checkpoint.**
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

Shared with the branch: the VM adapter's `pyproject.toml` version line, and
locks. The branch edits only the adapter's `inventory_views.py`.

- [ ] 4.1 VM's operator `create_vm` checks the guest name with
  `check_guest_name` in the adapter's service, before anything is prepared or
  submitted, and answers 422 naming the rule (D17).
  - Unit:
    - a name that is not a hostname label is refused;
    - a login that, stripped to letters and digits, exceeds 32 characters or
      starts with a digit is refused;
    - provisioning's own generated names pass.
  - Application integration, through the typed VM operator client: an over-long
    login is refused with 422, and no job is submitted.
- [ ] 4.2 Correct the IaC README: an operator's guest name is checked against
  the same rules (D17).
- [ ] 4.3 Bump the VM adapter, unless section 3 already did, and run
  `make lock`. **Verification checkpoint:**
  - unit and application integration, 4.1;
  - `make test` in `domains/vms/provisioning/adapter` and
    `provisioning/compute/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: no scenario creates an operator-named VM. No scenario is owed: the
  check is one authority's validation, which application integration owns.

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

Shared with the branch: the VM adapter's `pyproject.toml`. The branch edits its
version line and the `arkhai-compute-provisioning` floor. This section edits
the `dev` group, many lines below. Also locks.

- [ ] 5.1 Declare the partial unique index `uq_relay_port_leases_active_owner` on
  VM's `relay_port_leases` model, so that a schema built from the models has it.
  Service migration `20260901_001` still creates it where it is absent (D20).
  - Library integration (adapter): over the VM schema fixture, two retries
    taking a port for one owner hold one relay port.
  - Persistence integration (service): a database migrated from before
    `20260901_001` gains the index. A fresh database, created from the models,
    migrates without error.
- [ ] 5.2 Move the suites listed above into the VM adapter, over a VM schema
  fixture built from VM's models. `TestTheDigestGate` stays in the service,
  since it tests the service's importer (D20).
  Verify:
  - the moved suites pass under `make test` in
    `domains/vms/provisioning/adapter`, whose target runs both `unit/` and
    `integration/`;
  - the service suite no longer contains them.
- [ ] 5.3 Confirm that `database.py` imports VM's metadata at module level and
  that no comment in it or in `db/migrations.py` still says the module imports
  without the adapters, or that the VM adapter is optional to it (D6). No code
  change is expected; if such a comment is found, rewrite it to say that the
  service's database holds VM's tables, so its metadata and migration history
  name them. The rationale is promoted at closeout (27.9).
- [ ] 5.4 **Verification checkpoint.**
  - Library and persistence integration: 5.1.
  - Run `make test` in `domains/vms/provisioning/adapter` and
    `provisioning/compute/service`.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: the VM lane's deals take relay ports through the composed service
  on a freshly migrated database (`e2e_deal`, `e2e_deal_buyer_cli`). No scenario
  is owed.

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

Shared with the branch:
- **Version lines and locks.** `kit/policy/pyproject.toml`'s version line: the
  branch edits only that line in this file, raising it to `0.6.0`, the minor
  bump this section makes. The description this section edits is the next
  line, so Git reports the two lines as one conflict; it is resolved by keeping
  `0.6.0` and this section's description. Also locks.
- **`RELEASING.md`.** The branch edits two rows of the "Published packages"
  table and the "Versioning policy" section. This section edits only the
  console-script sentence in its opening paragraphs.

- [ ] 6.1 Remove from `kit/policy` everything design D7 lists. `typer` stays, for
  `buyer_policy.py`. The removed material is already carried verbatim in
  `repair-rl-training-tooling`'s `removed-tooling.md`. Compare it with what is
  removed, and record any difference there (D7).
  Verify:
  - `kit/policy`'s built wheel has no `market-policy` entry point and no `cli`
    module.
  - Its lock no longer resolves pufferlib or the CPU torch index.
  - A repository search for `market-policy` finds only
    `repair-rl-training-tooling`'s records.
- [ ] 6.2 Cut `domains/vms/training/README.md` down to what exists (D7). Verify
  that every path and target it names exists.
- [ ] 6.3 Drop `market-policy` from `RELEASING.md`'s console-script examples
  (D7).
- [ ] 6.4 The empty-chain refusal names `[negotiation].policies`. The
  unknown-name refusal says that built-ins are always registered and that
  extensions come from the `market_policy.negotiation_middlewares` entry-point
  group (D18). Unit (`kit/policy/tests/unit`): each refusal's message.
- [ ] 6.5 Bump `arkhai-kit-policy` by a minor version, since the console script
  is removed. Run `make lock`.
- [ ] 6.6 **Verification checkpoint.**
  - Unit: 6.4.
  - Run `make test` in `kit/policy` and in the VM and bare-metal storefronts,
    which compose its chain.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: every storefront composes the chain at startup, and no scenario
  meets a refusal. No scenario is owed.

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

Shared with the branch: `kit/contact-exchange/pyproject.toml`'s version line. The
branch also raises two pins there, on `arkhai-core` and
`arkhai-kit-settlement-runtime`, which this section leaves alone. Also locks.
The branch edits the kit's `settlement_config.py` and bare metal's
`test_http_introductions.py`, which this section does not touch.

- [ ] 7.1 Add the seller-delivery claim table, keyed by the introduction's
  obligation reference, with an insert that succeeds for exactly one caller. Add
  a migration that creates the table empty (D9).
  `contact_introductions_redaction_only` is untouched.
  - Library integration (`test_composition.py`): two independent sessions claim
    one introduction, and exactly one succeeds. The redaction trigger still
    refuses every update but the redaction.
  - `test_migrations.py`: a fresh database and a rerun are covered.
- [ ] 7.2 `IntroductionRouteService.start` claims once completion succeeds, and
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
- [ ] 7.3 Application integration (`test_introduction_delivery_claim.py`, through
  the VM storefront's typed introduction clients, with completion failing once
  at an injected collaborator):
  - the first start answers 503 and names starting again;
  - the buyer's next start completes the reveal, and the seller's recording
    sink receives exactly one dispatch;
  - further starts dispatch nothing;
  - the operator's explicit re-delivery still sends.
- [ ] 7.4 Bump `arkhai-kit-contact-exchange` by a minor version, since its schema
  and the start's answer change. Run `make lock`.
- [ ] 7.5 **Verification checkpoint.**
  - Unit, library integration, and application integration: 7.1–7.3.
  - Run `make test` in `kit/contact-exchange`, `kit/delivery`, and the VM and
    bare-metal storefronts.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: `e2e_vm_introduction` and `e2e_bare_metal_introduction` reveal an
  introduction and deliver it once on the seller's side, so they prove the claim
  does not stop an ordinary first delivery. Neither fails a completion. No
  scenario is owed: the interrupted reveal is one storefront's transaction,
  which library and application integration own.

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

Shared with the branch:
- **`admin_controller.py`.** The branch edits the interrupt route's docstring and
  `_deal_is_interruptible`. This section edits the request-model imports near
  the top, `_apply_fulfillment_event`, and the callback routes that follow
  `_reopen_available_compute_listings`.
- **`storefront_client/client.py`.** The branch edits the module docstring, the
  escrow opening, and the escrow-verify methods. This section removes two
  methods from each client class, which sit away from those hunks.
- **`test_compute_dynamic_listings.py`.** See `design.md`, "Implementation
  cadence": the branch edits the imports, `pytestmark`, the head of
  `DynamicListingState`, and `test_00`/`test_00a`. This section edits the
  module docstring's step 4, the `usage_started` field, `test_03`, and
  `test_04`'s `require_state`. Four unchanged fields separate the
  `usage_started` field from the branch's new first field.
- **`docs/configuration.md`.** The branch edits the `escrow_shape_guard` and
  `bisection` rows of the bundled-policies table. This section edits the
  failure-policy section's opening paragraph, below that table.
- **Version lines and locks:** `pyproject.toml` version lines of the VM
  storefront, `arkhai-core-storefront`, and `arkhai-core-storefront-client`, and
  locks.

- [ ] 8.1 Remove the four routes, their request models, their operation-map
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
- [ ] 8.2 Remove `notify_usage_started` and `notify_fulfillment_failed` from
  both storefront client classes (D4). Verify:
  - the storefront client's sync/async parity test passes;
  - a repository search finds no caller.
- [ ] 8.3 Remove the e2e stage that tests `usage-started` itself:
  - `test_03_usage_started_keeps_oversized_listings_closed`;
  - the `usage_started` field, and `test_04`'s requirement on it;
  - the module docstring's "Mark usage started" step.

  `test_04` now follows the reserve stage (D4). Verify: `make -C e2e-tests
  test-unit` passes, including the stage-set check.
- [ ] 8.4 `docs/configuration.md` describes the failure policy as the pull
  path's, run when the storefront reads a failed fulfillment (D4).
- [ ] 8.5 Confirm the sender's side of "Deal-scoped lifecycle events". In
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
- [ ] 8.6 Bump the VM storefront, `arkhai-core-storefront`, and
  `arkhai-core-storefront-client` by a minor version each, since routes and
  public methods are removed. Run `make lock`.
- [ ] 8.7 **Verification checkpoint.**
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

## 9. VM binds pool overrides at `POOL_OVERRIDES_PATH`

Delivers VM's pool-override routes on an unprefixed router bound at the kit's
`POOL_OVERRIDES_PATH`, as the bare-metal storefront binds them (D16).

Files: `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`
(the three pool-override routes) and `server.py` (the controller imports and the
`StorefrontRouteHooks` routers tuple).

Shared with the branch:
- **`admin_controller.py`.** The branch's hunks are the ones listed in section 8.
  The pool-override routes are separate from them.
- **`server.py`.** The branch edits the module's imports up to the settlement
  registry import, the Alkahest composition, `VmStorefrontServices`,
  `VmCompositionSeams`, `_build_vm_services`, and `_start_vm_services`. This
  section edits only the late controller import block and the routers tuple,
  below all of those.
- **`test_pool_overrides_api.py`.** The branch edits two assertions in it. This
  section does not change that file.
- **Version line:** the VM storefront's, already bumped by section 8.

- [ ] 9.1 Move the pool-override routes to a router with no prefix, declared at
  `POOL_OVERRIDES_PATH`, and mount it in the routers tuple (D16).
  Verify:
  - Application integration: `test_pool_overrides_api.py`, through the typed
    `SyncPoolOverrideClient`, passes unchanged.
  - Unit: the mounted path equals `POOL_OVERRIDES_PATH`, and the
    administrator-identity middleware's contract for it is unchanged.
- [ ] 9.2 **Verification checkpoint.**
  - Application integration: 9.1.
  - Run `make test` in `domains/vms/storefront` and `make check-comment-hygiene`.

  End-to-end: `e2e_compute_dynamic_listings` and `e2e_listing_shapes` write pool
  overrides through the typed client. A passing lane is the evidence that the
  path is unchanged.

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

- [ ] 10.1 Route resolution reports which case failed through a typed error. The
  middleware answers each case unsigned (D3):
  - 404 when no contract names the path;
  - 405 with `Allow` naming the contracts' methods;
  - 400 naming the field when the body resource cannot be bound.

  Resolution stays first-match over the one ordered table it is given.
  Library integration (`test_site_auth_middleware.py`): each case answers its
  status, carries no response signature, and names no credential.
- [ ] 10.2 The site client reports an answer with no response authentication as
  unauthenticated, with its status. The report contains no part of the body, no
  header value, and no credential. A malformed or wrong signature is reported
  as today (D3). Unit (`test_client.py`).
- [ ] 10.3 Application integration, rejection path, asserting the status and
  `Allow` only:
  - the provisioning service's site routes answer 405 to a known site path under
    another method;
  - the API-credits service, whose table extends the site's, answers the same
    (`test_signed_authority.py`).
- [ ] 10.4 Bump `arkhai-kit-site` and `arkhai-kit-site-client`, and run
  `make lock`. **Verification checkpoint:**
  - 10.1–10.3;
  - `make test` in `kit/site`, `kit/site-client`, `provisioning/compute/service`,
    and `domains/apicredits/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: the provisioning smoke hook's `provisioning_security` check still
  sends an unsigned read to a protected route that matches, and expects 401 or
  403. No scenario sends an unroutable request, and none is owed.

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
`tests/integration/test_servicing.py`.

- [ ] 11.1 `defer_fulfillment` writes in one transaction (D8.2):
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
- [ ] 11.2 The worker reads the operation after a ready hook returns without a
  fulfillment reference (D8.2):
  - if it is awaiting delivery, it keeps its due time and takes no backoff;
  - if it is still pending without the mark, it takes the error backoff;
  - if the hook raised, it stays on the error path.

  Unit (`test_servicing.py`) and library integration: across several
  consecutive deferrals, the obligation is due on each next cycle, and its
  attempts are not counted. A hook that returns without deferring backs off. A
  worker that ignores the flag backs the operation off as today (the delta's
  rollback scenario).
- [ ] 11.3 The worker logs every retry it schedules at warning, naming the
  obligation, the operation, and the error, whether or not an `on_event` is
  composed (D8.1). Unit: a failing step under a worker with no callback logs
  the retry.
- [ ] 11.4 `SettlementAdminRouteService.wait` treats a failed status read as a
  non-terminal poll and keeps polling until its deadline. At the deadline it
  returns `ready: false` with the last error (D8.3).
  Unit (`test_admin_routes.py`):
  - one failed read, then a terminal one: the wait reports ready;
  - every read fails: the wait reports `ready: false` with the last error.
- [ ] 11.5 Bump `arkhai-kit-settlement-runtime` by a minor version, since its
  schema and worker behaviour change. Run `make lock`.
- [ ] 11.6 **Verification checkpoint.**
  - Unit and library integration: 11.1–11.4.
  - Run `make test` in `kit/settlement-runtime` and in the VM, bare-metal, and
    API-credit storefronts, which compose it.
  - Run `make check-packaging` and `make check-comment-hygiene`.

  Application integration and end-to-end are section 18's, where the storefronts
  compose the reporting.

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

- [ ] 12.1 Building a contract accepts only these constructs (D3):
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
- [ ] 12.2 Composing the table compares the contracts of different contributions
  segment by segment, a pattern ending in `/?` in both its forms. It refuses two
  that can match one method and path before the service accepts traffic. Within
  one contribution, the owner's order decides, first match (D3).
  Unit (`test_route_table.py`):
  - two overlapping contributions are refused;
  - a literal route before a capture route in one contribution composes, and
    the literal path resolves to the literal route.
- [ ] 12.3 VM's two relay declarations drop their terminal `$`, which full
  matching makes redundant (D3). Unit: VM's relay paths resolve as before.
- [ ] 12.4 Resolution reports an unknown path, a known path under another method
  (with the allowed methods), and an unbindable body resource through a typed
  error that names its case, in place of `ValueError` (D3). Unit: each case.
- [ ] 12.5 Unit (`test_route_table_composition.py`): the composition root builds
  the complete table under the grammar and the overlap check:
  - the family's routes, and every contribution the service ships: VM, bare
    metal, resource pools, Ansible host import, and capacity definitions;
  - the slashed and unslashed forms of `jobs/?`, `hosts/?`, `vms/?`,
    `relays/?`, and `pools/?` resolve to the same route.
- [ ] 12.6 Bump the contracts and the VM operator client, and run `make lock`.
  **Verification checkpoint:**
  - unit, 12.1–12.5;
  - `make test` in `provisioning/compute/contracts`,
    `domains/vms/provisioning/client`, and `provisioning/compute/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: every lane's provisioning requests resolve through the composed
  table, so a passing pipeline shows that no served route was refused at
  composition. No scenario is owed.

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

- [ ] 13.1 The middleware maps section 12's typed error to an unsigned answer:
  404, 405 with `Allow`, or 400 naming the field (D3).
  - Unit (`test_auth.py`): each case, unsigned.
  - Application integration, rejection path, asserting status and `Allow` only:
    - an unknown path answers 404;
    - a known path under another method answers 405, its `Allow` naming the
      contract's methods;
    - a route whose body resource is missing answers 400.
- [ ] 13.2 The family client reports an answer with no response authentication
  as unauthenticated, with its status, and still refuses it. A malformed or
  other-principal signature is reported as today. The report contains no body,
  header value, or credential (D3).
  Unit (`test_client.py`): an unsigned 405 is refused and reported as an
  unauthenticated 405 (the scenario "The client and service route tables
  differ").
- [ ] 13.3 Bump the service and the client, and run `make lock`. **Verification
  checkpoint:**
  - 13.1–13.2;
  - `make test` in `provisioning/compute/service` and
    `provisioning/compute/client`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: the provisioning smoke hook's `provisioning_security` check is
  unchanged. No scenario sends an unroutable request, and none is owed.

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

- [ ] 14.1 Add a provisioning migration that converts stored reservations (D5):
  - `provisioning` becomes `unmanaged`;
  - `provisioning_failed` becomes `force_released`.

  Each gets a failure reason naming the state it held. Persistence integration
  (file-backed SQLite), the delta's three scenarios:
  - a `provisioning` row is `unmanaged`, its capacity still held;
  - a `provisioning_failed` row is `force_released`, its capacity free;
  - a database with neither is unchanged.

  A rerun changes nothing.
- [ ] 14.2 Add the same conversion to the API-credits service's chain (D5).
  Persistence integration in its `tests/integration`: the same three cases, and
  the rerun.
- [ ] 14.3 The readers listed above stop naming the two states (D5). Verify:
  - a repository search finds them only in `kit/site`'s definitions (until
    section 15), historical migrations, and the conversion and its tests;
  - unit `test_lease_lifecycle.py` passes on the remaining states.
- [ ] 14.4 Bump the service, the family kit, the VM storefront, and the
  API-credits service, and run `make lock`. **Verification checkpoint:**
  - 14.1–14.3;
  - `make test` in `provisioning/compute`, `provisioning/compute/service`,
    `domains/vms/storefront`, and `domains/apicredits/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: every compute lane and the API-credit lane migrate fresh
  databases, which hold no such row. No scenario is owed: the conversion is one
  service's migration, which persistence integration owns.

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

- [ ] 15.1 Remove the two members, and every set, transition, and terminal
  check that names them (D5). Library integration (`test_ledger.py`): the
  conditional transitions and truncation refusals hold for the remaining
  states.
- [ ] 15.2 Remove `CapacityLedgerService.update_reservation_state` and its
  authority-protocol entry. Tests reach a state through the real transitions,
  or seed the row where no API expresses it (TESTING.md, "Service-internal
  state setup") (D5).
  Verify:
  - a repository search finds no caller;
  - unit: the authority protocol exposes no generic state writer.
- [ ] 15.3 Bump `arkhai-kit-site`, unless section 10 already did, and run
  `make lock`. **Verification checkpoint:**
  - library integration, 15.1–15.2;
  - `make test` in `kit/site`, `kit/site-client`, `provisioning/compute`,
    `provisioning/compute/service`, `domains/vms/storefront`, and
    `domains/apicredits/service`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: `e2e_deal`, `e2e_deal_buyer_cli`, and `e2e_bare_metal_mock_deal`
  lease and release through the remaining transitions. No scenario is owed.

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

- [ ] 16.1 The contract is major 3, and every party accepts only major 3.
  `FulfillmentScheduleResponse` gains an optional `host_id`.
  `LeaseState.PROVISIONING_FAILED` and its mapping entry are removed
  (D13, D5).
  Unit (contracts):
  - a 2.x model is refused, naming the supported major;
  - a schedule response validates with and without `host_id`;
  - `LeaseState` has no `provisioning_failed`.
- [ ] 16.2 The schedule route sets `host_id` from the scheduled resource's
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
- [ ] 16.3 "A storefront calls a service that has not been upgraded". Unit, in
  the family client or VM's aggregate fulfillment client: a major-2 schedule
  answer is refused, naming the supported major, and nothing is begun.
- [ ] 16.4 Bump the contracts, the client, the family kit, and the service,
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

- [ ] 17.1 Each control answers a model from `system.py`. The client returns it,
  in both variants, and the service's failures are answered as every
  provisioning route's are (D15).
  - Application integration (`test_system_api.py`, through the typed client):
    each control's typed answer.
  - Unit: sync/async parity.
- [ ] 17.2 The e2e callers read the models' attributes (D15). Verify: `make -C
  e2e-tests test-unit` passes, including the stage-set check.
- [ ] 17.3 The recovery-diagnostics line carries its counts in its message, and
  keeps `extra` for the test that reads it (D19). Unit: the formatted message
  names each count.
- [ ] 17.4 Bump the contracts, the client, and the service, unless sections 12,
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

- [ ] 18.1 Both storefronts compose `on_event`, as VM's
  `settlement_composition.py` does (D8.1). Unit: each composition hands the
  worker its callback. Assert the object identity at the constructor, per
  TESTING.md, "Composition-boundary convention".
- [ ] 18.2 Application integration (bare metal, through its typed clients and the
  lifecycle `run-cycle` route):
  - a deal whose lease is not yet active is due again on the next
    servicing cycle, with no backoff, and publishes its evidence once the lease
    is active;
  - a failing step writes a stage event;
  - the administrator's settle wait, with one failed status read at the site,
    reports ready (D8.2, D8.3).
- [ ] 18.3 Bump the bare-metal and API-credit storefronts, and run `make lock`.
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

- [ ] 19.1 Begin compares the schedule response's `host_id` and the scheduled
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
- [ ] 19.2 A site-reported delivery that differs from the recorded result makes
  the status, result, and access reads answer 409 `delivery_conflict`, and the
  recorded result stands (D12). Application integration, through
  `StorefrontClient`: "The site reports a different delivery".
- [ ] 19.3 The bare-metal e2e driver stops declaring the nested copies of the
  host and machine (D13). Verify: `make -C e2e-tests test-unit`.
- [ ] 19.4 Bump the bare-metal storefront, unless section 18 already did, and run
  `make lock`. **Verification checkpoint:**
  - 19.1–19.3;
  - `make test` in `domains/bare_metal/storefront`;
  - `make check-packaging` and `make check-comment-hygiene`.

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

- [ ] 20.1 Remove `mode` from the settings, the template, and the umbrella
  values, and the render test's expectation of it (D22).
  - Unit (`domains/vms/storefront/tests/unit/cli/test_config.py`): the generated
    template has no `mode`, and a settings file that states it still loads.
  - Chart render: `make -C helm test-render`.
- [ ] 20.2 Remove `mode` from the runbook and the seller quickstart, which say
  it selects mock or live provisioning (D22).
- [ ] 20.3 Bump the VM storefront, unless already bumped since the merge.
  **Verification checkpoint:**
  - 20.1;
  - `make test` in `domains/vms/storefront`;
  - `make -C helm test-render`;
  - `make check-comment-hygiene`.

  Owed by validation: `tests.yml`, job `release · deployment contracts`, where
  `make -C helm test-render` passes with `mode` gone from the umbrella's values
  and its render test.

  End-to-end: the VM lane's storefronts boot without the key. No scenario is
  owed.

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

- [ ] 21.1 The harness builds the family client with VM's mount and bare
  metal's mount, the latter from `arkhai_bare_metal.provisioning_routes`'
  values. The callers read the typed models' attributes (D14).
  Verify:
  - `make -C e2e-tests test-unit` passes, including the stage-set check;
  - no e2e source builds a mock-rule path or operation by hand.
- [ ] 21.2 **Verification checkpoint.**
  - Run `make -C e2e-tests test-unit`, `make lock`, `make check-packaging`, and
    `make check-comment-hygiene`.

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

- [ ] 22.1 A configured seller address that differs from the address its key
  derives (through `kit/config`'s `derive_wallet_address`) makes Alkahest
  unready with `alkahest.wallet_address_mismatch`. An absent address is the
  key's. The oracle check compares the oracle with the signing account as well
  as the address. Buyers keep their tolerance (D10).
  Unit: one case each:
  - "The address names another account";
  - "The address is omitted";
  - "The oracle is the signing key".

  A buyer configuration with a mismatch is not refused.
- [ ] 22.2 Bump `arkhai-kit-alkahest`, and run `make lock`. **Verification
  checkpoint:**
  - 22.1;
  - `make test` in `kit/alkahest`;
  - `make check-packaging` and `make check-comment-hygiene`.

  Application integration and end-to-end are section 24's.

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

- [ ] 23.1 Add the map from configured chain name to book. A key naming no
  configured chain makes Alkahest unready (D11).
  Unit:
  - the map parses;
  - an unknown chain key is a blocker naming the key.
- [ ] 23.2 Add the resolver operation. It answers a chain's book, and nothing
  for a chain using the SDK's built-in addresses. No caller reads the map
  itself (D11).
  Unit: "A seller trades on two chains" at the resolver: `anvil` is named, and
  `base_sepolia` resolves to nothing.
- [ ] 23.3 Bump `arkhai-kit-alkahest`, unless section 22 already did.
  **Verification checkpoint:**
  - 23.1–23.2;
  - `make test` in `kit/alkahest`;
  - `make check-packaging` and `make check-comment-hygiene`.

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

- [ ] 24.1 Each storefront resolves a chain's book through the `kit/alkahest`
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
- [ ] 24.2 The seller's wallet (D10):
  - API credits passes its wallet to readiness;
  - `resolve_evm_wallet` is removed;
  - a seller configuration may omit `[Wallet].address`.

  Application integration, through `StorefrontClient`'s settlement status:
  - a mismatched address leaves Alkahest unready with
    `alkahest.wallet_address_mismatch`, the storefront's other mechanisms ready,
    and no Alkahest option published;
  - an omitted address is derived from the key.
- [ ] 24.3 Move the repository's storefront configurations and charts to
  `[Settlement.alkahest.address_books]`, and regenerate the values schemas with
  `make helm-values-schema`. The drift tests pass (D11).
  Chart render:
  - `make -C helm test-render`;
  - the storefront render tests' loader checks, run locally with
    `STOREFRONT_PYTHON` and `BARE_METAL_STOREFRONT_PYTHON` set (TESTING.md,
    "Chart Render Tests").
- [ ] 24.4 Bump the three storefronts and `arkhai-kit-storefront`, and run
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

- [ ] 25.1 Each buyer CLI resolves a chain's book through the operation, and
  passes the mapping to the codec and negotiation packages it calls. Buyers keep
  their tolerance of a wallet mismatch (D11, D10).
  Unit, in each buyer's suite:
  - a buyer configuration with the map resolves `anvil`'s book;
  - a chain the map does not name uses the built-in addresses.
- [ ] 25.2 The e2e harness writes buyer configurations with the map (D11).
  Verify: `make -C e2e-tests test-unit`.
- [ ] 25.3 Bump the VM, API-credit, and bare-metal buyers as changed, and run
  `make lock`. **Verification checkpoint:**
  - 25.1–25.2;
  - `make test` in `domains/vms/buyer`, `domains/apicredits/buyer`, and
    `domains/bare_metal/buyer`;
  - `make check-packaging` and `make check-comment-hygiene`.

  End-to-end: `e2e_deal_buyer_cli`, `e2e_buy`, and `e2e_credits_deal` fund
  escrows with the buyer's `anvil` book from the map, which is the evidence for
  this section.

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

- [ ] 26.1 `[Chains.<name>].alkahest_address_config_path` and
  `[Settlement.alkahest].address_config_path` are each refused with a
  diagnostic naming `[Settlement.alkahest.address_books]`, in every
  storefront's and buyer's loader (D11). Unit: "A retired key is stated", for
  each key and each loader.
- [ ] 26.2 The migration tool moves each retired key into the map (D11):
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
- [ ] 26.3 A repository search finds the retired keys only in the migration
  code, the refusal diagnostics, and their tests (D11).
- [ ] 26.4 Bump `arkhai-kit-config` and every package whose loader changed. Run
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

## 27. Closeout

Confirm and promote the verified design, then archive last. This covers D1–D23
and every delta requirement. The eleven parts follow
`openspec/README.md#plan-closeout-requirements`, in order. Closeout changes no
code: a part that needs a code, lock, or test change returns the change to
implementation.

- [ ] 27.1 **Comment hygiene — confirm.**
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
- [ ] 27.2 **Import placement — confirm.** Check that every import sections 1–26
  added or touched is at module level, unless a verified cycle or a recorded
  lazy-load reason keeps it local. A needed move returns the change to
  implementation.
- [ ] 27.3 **Documentation compliance.** Check D1–D23 and the owner's pre-1.0
  principle against `openspec/README.md`'s placement rules, against the
  promotion record below, and against the code:
  - normative behaviour in specs, through the deltas;
  - rationale in the companions;
  - repository rules in `ARCHITECTURE.md`;
  - operator behaviour in `DEPLOYMENT_AND_CONFIG.md` and the quickstarts;
  - versioning in `RELEASING.md`.

  Record a disposition for every decision.
- [ ] 27.4 **Narrative compression.** Compress the section notes to final
  behaviour, validation evidence, deferred work, and destinations. Move durable
  rationale, plan corrections, and declined review items into `design.md`
  first. The open question on per-adapter migration chains stays in
  `design.md`.
- [ ] 27.5 **Roadmap currency.** In `docs/development/ROADMAP.md`:
  - Goal 1: remove the open-gap row this change owns, which begins "Small
    defects and dead surfaces in the compute family". State in the current-state
    prose what is now true:
    - unmatched routes answered by cause;
    - the typed mock and worker surfaces;
    - the compute provisioning contract at major 3.
  - Goal 6: confirm that the unowned payout-account gap row, added at design, is
    still accurate.
- [ ] 27.6 **Campaign index currency.** Update this change's row in
  `openspec/changes/README.md`: status `in closeout`, and notes naming the
  validation and destinations. Update the architecture campaign's paragraph,
  which names this change as the owner of two judgement items: say that both
  are settled, and where (D6, in `physical-provisioning`'s companion; D7,
  carried to `repair-rl-training-tooling`). Leave other rows' `Depends on` for
  archive cleanup. Run `make check-change-index`.
- [ ] 27.7 **Packaging.** Confirm that these pass against the last
  implementation commit:
  - `make check-packaging`;
  - `make check-architecture-change CHANGE=resolve-compute-family-findings`, since
    the change owns no `ARCHITECTURE.toml` row.

  Record whether any `.agents/`, `.claude/`, or `.codex/` file was touched, and
  run `make check-agent-skills` if one was.
- [ ] 27.8 **End-to-end pipeline.** Confirm that the latest validation covers the
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
- [ ] 27.9 **Promotion.** Write every destination in the promotion record below,
  and complete its third column. Hand-edit each spec's Evidence section where
  the tests it names moved. That includes `physical-provisioning`'s, for the
  suites section 5 moved. The archive in 27.11 merges the deltas. Add the new
  `introduction-delivery` companion to `openspec/specs/README.md`.
- [ ] 27.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=resolve-compute-family-findings` and resolve
  every match. Then run the pinned
  `bunx @fission-ai/openspec@1.14.0 validate resolve-compute-family-findings --strict`
  (or `make check-change`, which runs it).
- [ ] 27.11 **Archival — last.** Run the pinned
  `bunx @fission-ai/openspec@1.14.0 archive resolve-compute-family-findings -y`
  without `--skip-specs`. It merges the deltas once into these specs:
  `site-capacity`, `physical-provisioning`, `compute-provisioning-contract`,
  `market-composition`, `storefront-publication`, `settlement-servicing`,
  `introduction-delivery`, and `settlement-configuration`.
  Then:
  - read each merged requirement in its spec's diff;
  - point this change's index row at the archive, with status `in closeout`;
  - run the pinned `validate --specs --strict` and `make check-change-index`.

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

Planning settled each destination below. Implementation completes the third
column at closeout (27.9).

| Accepted knowledge | Permanent destination | Written |
|---|---|---|
| D3: the unmatched-route answers, the pattern grammar and overlap refusal, and the clients' report of an unauthenticated answer | `openspec/specs/physical-provisioning/spec.md`, "The provisioning service answers an unroutable request by what failed to match" and "The family client names an unauthenticated answer"; `openspec/specs/site-capacity/spec.md`, "A site authority answers an unroutable request by what failed to match"; all through the archive | |
| D3: why an unroutable answer is unsigned; why the grammar is restricted; that a route needing more adopts an established path-template grammar | `openspec/specs/physical-provisioning/architecture.md`, "Canonical requests, durable replay, and signed responses" | |
| D3: the service refuses overlapping contributions when it composes its table | `docs/development/ARCHITECTURE.md`, "Route contracts and their HTTP binding", the paragraph beginning "A domain that contributes routes" | |
| D4: the one lifecycle event provisioning pushes | `openspec/specs/compute-provisioning-contract/spec.md`, "Deal-scoped lifecycle events", through the archive | |
| D13 and D5: the schedule response's host and machine; contract major 3 | `openspec/specs/compute-provisioning-contract/spec.md`, "A schedule response names the scheduled resource's host and machine" and "Explicit contract incompatibility", through the archive | |
| D14 and D15: the family's mock-route template, models, and client; the typed worker controls | `openspec/specs/physical-provisioning/spec.md`, "Compute-owned caller contract"; `openspec/specs/market-composition/spec.md`, "Compute mock executors share one compute-family mechanism"; both through the archive | |
| D14: the mock mechanism as a worked instance of the five-piece route pattern | `openspec/specs/physical-provisioning/architecture.md`, "Compute composition"; `docs/development/ARCHITECTURE.md`, "Family kits", the paragraph beginning "Executor selection is one table", whose list names the rule route service | |
| D5: the remaining reservation states and the upgrade conversion | `openspec/specs/site-capacity/spec.md`, "Reservation lifecycle", "The lease lifecycle's writes are conditional transitions", "Lease truncation neither resurrects nor extends a lease", "A reservation's lease tail is written once", and "A stored reservation in a retired state is converted at upgrade", through the archive | |
| D5: why a conversion keeps each row's capacity effect, rather than refusing the upgrade | `openspec/specs/site-capacity/architecture.md`, "Reservation lifecycle" | |
| D6: the service's migration history names the tables its database holds | `openspec/specs/physical-provisioning/architecture.md`, "Compute composition" | |
| D8: the awaiting-delivery cadence and its journal mark; retry reporting; the settle wait | `openspec/specs/settlement-servicing/spec.md`, its four requirements, through the archive | |
| D8: why the mark is a flag, not a state (rollback); how it differs from the deferred outcome | `openspec/specs/settlement-servicing/architecture.md`, "Servicing lifecycle" | |
| D9: one dispatch claimed by the completing start; no counterparty-triggered re-send | `openspec/specs/introduction-delivery/spec.md`, "Delivery fires once per reveal and re-delivery is explicit", through the archive | |
| D9: the buyer-retry limit; why a new start, not a replay, completes a reveal; why the claim is its own table | `openspec/specs/introduction-delivery/architecture.md` (new), and its row in `openspec/specs/README.md` | |
| D10 and D11: one seller account; address books per chain | `openspec/specs/settlement-configuration/spec.md`, through the archive; `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Settlement consumer configuration and cutover" and "Bare-metal role configuration"; `docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md`, `docs/buyer-quickstart.md`, and `docs/cookbooks/vllm-apicredits-seller.md`, wherever each names a book or the seller's address | |
| D12 and D13: the bare-metal delivery conflict, and begin | `openspec/specs/storefront-publication/spec.md`, through the archive | |
| D17: operator guest names | `openspec/specs/physical-provisioning/spec.md`, through the archive | |
| Pre-1.0 incompatible changes; versioned contracts are versioned, not changed in place; neither applies at or above 1.0.0 | `docs/development/RELEASING.md`, "Versioning policy"; a pointer in `docs/development/ARCHITECTURE.md`, "Operators"; the owner's one sentence in `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Profile-based configuration" | |
| Goal 1 gap closed; Goal 6 payout gap | `docs/development/ROADMAP.md`, Goal 1 and Goal 6 | |
| Campaign status | `openspec/changes/README.md`: this change's row and the architecture campaign's paragraph | |
