# Tasks — repair compute purchase recovery

Replanned against the reviewed design after its second design review
(`reviews/02-design.md`) and that review's triage. No task had been completed before
the replanning, so none was preserved as done. The design gates in Section 1 record how
the design was settled.

Sections are ordered by real dependencies, lowest layer first: the shared Ansible kit
before the domain adapters that compose it, the fulfillment kit before the compute
lifecycle that calls it, and domain vocabulary before the storefront that publishes
it.

Paths under `provisioning/compute/ansible/` are the shared Ansible kit
(`compute_provisioning_ansible`), and paths under `provisioning/compute/service/` are
the compute provisioning service. Test levels are those of `docs/development/TESTING.md`:
unit, library integration, application integration (the running service through its
typed client), and system.

**Packaging, in every section.** Every section that changes a package does three
things:
- bumps the package's minor version;
- updates the exact pins its dependants hold;
- refreshes the locks with `make lock`, using uv at or above the repository minimum
  (`make check-uv-version`).

Its verification then runs `make check-packaging`, which includes
`make check-architecture`. A section that changes only tests changes no version.

**Fixtures are synthetic (D2).** Every test fixture uses development values:
- a reserved documentation address (`192.0.2.0/24`);
- a synthetic tenant account;
- a zeroed identifier;
- a placeholder key.

No output, identifier, address, or key from a real host or purchase enters a test.

**End-to-end evidence.** Validation runs the Helm checks and the pipeline on every
commit. Each section names the scenarios (pytest markers in `e2e-tests/`) that
exercise it, or says that none does. No section owes evidence from a CI workflow that
only a push produces.

## 1. Design

- [x] 1.1 **Decision gate.** Resolve the independent design reviews of `design.md`,
      the deltas, and this plan. Record each accepted finding in `design.md`, and
      amend these sections before Section 2 starts.
      - The first review's triage (`reviews/01-design.triage.md`) amended the
        design and asked for another round.
      - The second review (`reviews/02-design.md`) found no blocking issue. Its
        triage (`reviews/02-design.triage.md`) recorded `Advance`, and carried its
        corrections into `design.md` (D1, D4, D10), the deltas, and this plan.
- [x] 1.2 **Decision gate.** Confirm D7's ownership split with
      `gpu-optional-compute-shapes`:
      - Its proposal records, under "Dependencies and Related Changes", that this
        change delivers the schema and VM stated-shape slice and gates its planning.
      - Its index row names this change in `Depends on` as
        `` `repair-compute-purchase-recovery` (planning) ``.

      `make check-change-index` holds the column. It checks that each dependency
      the column names is a change the index lists and is not `archived`, with a
      phase from the legend's list. It passed when this plan was written. It reads
      no `Notes` text and no proposal, so the proposal's record was checked by
      reading it.

## 2. Read a printed fact in either form, for the job's action

Delivers D1's reader ("Block boundaries", "What the reader takes and ignores") in the
shared Ansible kit, for the delta requirement "A create succeeds only with readable
delivery evidence". Files:
- `provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`
- its `__init__` exports
- `provisioning/compute/ansible/tests/unit/test_runner.py`

- [ ] 2.1 Add a reader that takes the output, the fact name, and the expected action:
      - It returns the fact printed in JSON `var:` form, when one is printed.
      - Otherwise it reads each `msg: |` or `msg: |-` literal block alone. A block
        is the indented lines after its key, up to the first non-blank line indented
        no deeper than the key. The reader parses the dedented block as one JSON
        document, and never reads past the block's end.
      - It ignores a block that is not JSON, a document that is not an object, a
        document with no `action`, and a document naming another action.
      - It returns the last document whose `action` equals the expected action. With
        none, it returns nothing.
      - It logs at debug level how many blocks it ignored and why, never their
        content.

      `extract_fact` stays for callers that pass no action, and reads the JSON form
      only.
- [ ] 2.2 Unit tests, on synthetic output in each form the shipped configuration and
      the JSON configuration print:
      - YAML `var:` plus `msg: |-` JSON;
      - JSON `var:`;
      - several `msg:` blocks for different actions, the expected one not last;
      - two blocks for the expected action, the last taken;
      - the play's human-readable summary block (`msg: |` with prose lines), alone,
        and followed by another task's JSON document, which is not adopted;
      - a malformed block followed by an unrelated task's JSON document, neither
        taken;
      - a document with no `action`;
      - no fact at all;
      - a debug log that carries no block content.
- [ ] 2.3 Verification:
      - `make -C provisioning/compute/ansible test` (unit);
      - `make check-packaging`.

      End-to-end: none directly. Sections 4 and 5 carry the reader through the mock
      lanes.

## 3. A tenant-facing port beside the tenant-facing address

Delivers D3's connection, inventory, and INI changes, for the delta requirement "The
tenant-facing host address falls back to the connection address". Files:
- `provisioning/compute/ansible/src/compute_provisioning_ansible/connection.py`
- `runner.py` (`InventoryTarget`, `inventory_target`, and inventory rendering)
- `inventory.py` (INI `public_port=`)
- their unit tests, including `provisioning/compute/ansible/tests/unit/test_inventory.py`
- `provisioning/compute/service/tests/integration/test_hosts_api.py`

- [ ] 3.1 `SshConnection` gains an optional `public_port`, validated as 1–65535 and
      additive to version 1. `InventoryTarget` carries it. Rendering emits
      `public_port=` when set, as it emits `public_host=`. The INI format reads
      `public_port=`, and refuses a malformed port as it refuses a malformed
      `ansible_port`. Each connection field's comment states its fallback.
- [ ] 3.2 Unit tests:
      - a connection with and without `public_port`;
      - a malformed port refused;
      - rendering;
      - an INI round trip, including a malformed entry rejected while the others
        are imported.
- [ ] 3.3 Application integration: register a host through the typed host client
      with `public_host` and `public_port`. Read it back, and see both in the
      rendered execution inventory. A host without them reads unchanged.
- [ ] 3.4 Verification:
      - `make -C provisioning/compute/ansible test` (unit);
      - `make -C provisioning/compute/service test` (application integration);
      - `make check-packaging`.

      End-to-end: no pipeline scenario registers a tenant-facing route. The live
      bare-metal lane is the system evidence.

## 4. Bare-metal grants yield evidence linked to their job, on the buyer's route

Delivers D1's bare-metal linkage, D2's shipped-form mock, and D3's endpoint, for the
delta requirements "A create succeeds only with readable delivery evidence" and "The
tenant-facing host address falls back to the connection address". Files:
- `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/codec.py`
- `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/mock_output.py`
- `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_codec.py`
- `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_mock_output.py`
- `provisioning/compute/service/tests/integration/test_bare_metal_mock_profile.py`

- [ ] 4.1 The codec reads its fact through Section 2's reader, with the job's action.
      A grant yields evidence only when its fact names:
      - the job's action and host;
      - the parameters' tenant account;
      - the parameters' physical machine, when they name one;
      - status `success`.

      Otherwise the result carries no evidence, and a detail naming the mismatch.
      - The evidence endpoint is the execution host's `public_host`, else
        `ssh_host`, and its `public_port`, else `ssh_port`, with the confirmed tenant
        account.
      - The fact's own host and port are detail only.
      - A reclaim's fact is checked the same way.
- [ ] 4.2 The mock output prints the form the shipped configuration prints, a YAML
      `var:` block and the `msg: |-` JSON document, rendered for the job as it is
      today.
- [ ] 4.3 Unit tests:
      - a grant from shipped-form output;
      - each mismatch: action, host, tenant, machine, and status;
      - another action's document only;
      - the endpoint from a host with and without a tenant-facing route;
      - a reclaim in both forms.

      Existing JSON-form cases stay.
- [ ] 4.4 Application integration, through the provisioning service's typed client
      under the mock profile:
      - A grant whose mock output is the shipped form reaches an `active`
        fulfillment, and its result's endpoint is the host's tenant-facing route.
      - A grant whose output names another tenant leaves the fulfillment `failed`,
        with no evidence.
- [ ] 4.5 Verification:
      - `make -C domains/bare_metal/provisioning/adapter test` (unit);
      - `make -C provisioning/compute/service test` (application integration);
      - `make check-packaging`.

      End-to-end:
      - `e2e_bare_metal_mock_deal` and `e2e_bare_metal_payment_deal` (the
        bare-metal lane) arm no rule's stdout, so every grant and reclaim there
        reads the shipped-form default through the real read path.
      - The live bare-metal lane is the system evidence of a real grant.

## 5. VM reads facts through the shared reader, linked to its guest

Delivers D1 and D2 for VM ("The VM pipeline scenarios use that default"), for the
delta requirement "A create succeeds only with readable delivery evidence". Files:
- `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`
- `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/mock_output.py`
- a new `domains/vms/provisioning/adapter/tests/unit/test_vm_mock_output.py`
- the VM codec tests
- `e2e-tests/tests/e2e/roles/scenarios/vms/compute_deal_driver.py`, used by
  `test_full_deal.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal_buyer_cli.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_buy_oneshot_buyer_cli.py`
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_non_erc20_settlement.py`

The VM codec tests are in
`provisioning/compute/service/tests/unit/services/test_vm_codec.py`. They stay there
until `resolve-compute-family-findings` moves them to
`domains/vms/provisioning/adapter/tests/unit/`. Add the cases wherever the file is when
this section starts, and record in this section's notes where they went.

- [ ] 5.1 Replace `extract_vm_fact`'s private `msg:` fallback with Section 2's
      reader. The codec supplies the expected action from its own mapping, beside
      `VM_RESULT_FACTS`: the job's `vm_action`, which is `create` for a create and
      `vm_remove` for a remove, as each VM role prints it. The shared reader holds no
      VM knowledge. Behaviour on JSON-form output is unchanged.
- [ ] 5.2 A create's fact yields evidence only when:
      - its `action` is `create`;
      - its `vm_name` is the job's `vm_target`;
      - its `status` is `success`.

      The tenant account and forwarded port are read from that fact
      (`tenant_user`, `external_ssh_port`) or its `frp` block, no longer by
      searching the whole output. The fact's `host` is not compared. Otherwise the
      result carries no evidence, and a detail naming the mismatch.
- [ ] 5.3 `vm_mock_output` renders the shipped form for the job, from the job's
      stored parameters, as bare metal's does:
      - **A create.** The provided-key create fact, with:
        - `vm_name` set to the job's `vm_target`;
        - `tenant_user` derived from that name as the role derives it, by removing
          every non-alphanumeric character and lower-casing;
        - `status` `success` and a `timestamp` of the run;
        - a forwarded `external_ssh_port`, and no relay.
      - **A remove.** `vm_remove_data` naming the job's guest.

      The fixed `mock-vm` create, whose status is `running`, is removed.
- [ ] 5.4 Drop `result_stdout` from the create rule in each of the five scenario
      modules. Each rule keeps its `rule_id`, `match`, and `pause_before_result`, so
      every create there gets the per-job default:
      - remove `compute_deal_driver.py`'s `_CREATE_RESULT_STDOUT`, and correct the
        comments that describe the fixed fact;
      - before changing any assertion, re-run
        `rg -n "vmuser|e2e-test-vm|e2e-shapes-vm|e2e-buy-vm" e2e-tests/` and adjust
        any assertion that pins a fixed tenant user or guest name. When this plan
        was written, nothing asserted on them.

      None of the five rules is a deliberate invalid-output case. A test that needs
      invalid create output stays at the codec's or the provider's level (5.5,
      Section 4.4).
- [ ] 5.5 Unit tests:
      - each VM action from shipped-form output;
      - another action's `msg:` document no longer taken, including a `vm_remove`
        run whose output also carries a create document;
      - a create fact naming another guest yields no evidence, and so does one
        reporting another status;
      - a create fact whose `host` differs from the registry's address still yields
        evidence at the registry's address;
      - the mock's create output for a job yields evidence through the codec, with
        `tenant_user` derived from the job's `vm_target`, and its remove output
        names the job's guest;
      - existing cases kept.
- [ ] 5.6 Verification:
      - `make -C domains/vms/provisioning/adapter test` (unit);
      - `make -C provisioning/compute/service test` (unit and application
        integration, including the VM codec tests and the service's mock-profile
        cases that use `vm_mock_output`);
      - `make -C e2e-tests test-unit` (the scenario helpers still import and pass);
      - `make check-packaging`.

      End-to-end: once this section lands, five VM-lane scenarios read every create
      through the shipped-form default and the `msg:` path:
      - `e2e_deal`, through `compute_deal_driver.py`;
      - `e2e_deal_buyer_cli`;
      - `e2e_listing_shapes`;
      - `e2e_buy`;
      - `e2e_non_erc20_settlement`.

      `e2e_deal` and `e2e_deal_buyer_cli` also arm a `vm_remove` rule with no
      stdout, which already reads the default and now prints `vm_remove_data`. No
      VM-lane scenario still supplies a rule's stdout. None is relay-backed. The
      live VM lane is the system evidence of a real guest.

## 6. Recover what `buy` recorded, and qualify the payments upgrade

Delivers D5 and the payments qualification in "Context". Files:
`domains/bare_metal/buyer/tests/test_cli_completion.py`, or a new test module beside
it.

- [ ] 6.1 Test: `buy_bare_metal` writes a real run log under one temporary XDG state
      directory, with its module factories replaced:
      - `fresh_identity`, `registry_client`, and `payment_approval` for the write;
      - `recovery_identity` for the read.

      `_recovered_deal`, the path `access`, `result`, and `teardown` share, reads the
      log back under the same directory. It recovers the same publisher principals,
      publisher, and registry binding. The test fails if the producer's form changes
      without the consumer's.
- [ ] 6.2 Qualify the payments upgrade with no code change:
      - run `make -C kit/arkhai-payments test`;
      - rebuild the bare-metal buyer environment through `make dist` and its
        `reinit`;
      - record in this section's notes that the kit verifies `livemode`, refuses a
        mismatched mode, and refuses unknown receipt fields.
- [ ] 6.3 Verification:
      - `make -C domains/bare_metal/buyer test` (unit);
      - `make -C kit/arkhai-payments test` (unit).

      No package changes, so there is no packaging step. End-to-end:
      `e2e_bare_metal_payment_deal` re-drives a recorded run.

## 7. The fulfillment kit begins a compensating teardown

Delivers D4's kit half ("The kit operation", "The compensation marker"), for the
`fulfillment` delta requirement "Scheduling and assignment". Files:
- `kit/fulfillment/src/market_fulfillment/transitions.py`
- `kit/fulfillment/src/market_fulfillment/fulfillment.py`
- `kit/fulfillment/src/market_fulfillment/fulfillment_persistence.py`
- `kit/fulfillment/src/market_fulfillment/provider.py` (the refusal error)
- the package exports
- `kit/fulfillment/tests/unit/test_transitions.py`, `test_fulfillment.py`, and
  `test_settlement_repository.py`
- a library integration case under `kit/fulfillment/tests/integration/`

- [ ] 7.1 Add the transition `failed` → `teardown_dispatch_pending`, and the constant
      `CREATE_COMPENSATION = "create_compensation"`.
- [ ] 7.2 Add `FulfillmentOrchestrator.begin_compensating_teardown(fulfillment_id,
      *, authorize)`, with two new types:
      - `CompensationCandidate`: the state, the failure reason, and the provider
        metadata, which stays opaque;
      - `CompensationRefusedError`, a `FulfillmentConflictError`.

      In one write transaction it answers by state, as D4's table states:
      - unknown: not found;
      - a teardown already begun or finished: the current view, writing nothing;
      - `failed`, and either refused by `authorize` or the provider's
        `prepare_teardown` raises `ProviderConfigInvalidError`:
        `CompensationRefusedError`, writing nothing;
      - `failed`, and any other preparation error: that error propagates, writing
        nothing;
      - `failed`, authorized, and prepared: the prepared teardown is recorded, and
        the row moves to `teardown_dispatch_pending` with `failure_reason`
        `create_compensation` and its message kept;
      - any other state: `FulfillmentConflictError`, writing nothing.

      `begin_fulfillment_teardown` still refuses `failed`.
- [ ] 7.3 Tests:
      - **Unit:**
        - the transition table;
        - each row of the state table;
        - `authorize` receives one `CompensationCandidate` carrying the record's
          fields, and nothing is written when it refuses;
        - another preparation error propagates, writing nothing.
      - **Library integration (real SQLite):**
        - the operation and a concurrent ordinary teardown request on one
          aggregate settle on one prepared teardown;
        - `recovery_diagnostics` before, during, and after a compensation counts the
          row as `failed`, then in its teardown state, then under `teardown_failed`
          after a failure, and finally under `torn_down`. It never counts a
          compensated `torn_down` as failed.
- [ ] 7.4 Verification:
      - `make -C kit/fulfillment test` (unit and library integration);
      - `make check-packaging`.

      End-to-end: none. No pipeline scenario fails a create deliberately.

## 8. Release compensates eligible failed creates

Delivers D4's compute half ("Eligibility", "The compute-owned seam", "Release paths"),
for the `physical-provisioning` delta requirement "An undelivered lease is released by
what its fulfillment proves". Files:
- `provisioning/compute/src/compute_provisioning/release.py`: `compensable`,
  `TeardownRefused`, the executor, the status port, and the teardown port
- `provisioning/compute/src/compute_provisioning/lease_lifecycle.py`: refusal handling
  in `_begin_recorded_teardown` and the releasing pass, and
  `_mark_release_failed`'s expected handle
- `provisioning/compute/service/src/compute_provisioning_service/services/fulfillment_convergence.py`:
  the teardown-failure write keeps `create_compensation`
- `provisioning/compute/service/src/compute_provisioning_service/container.py`: the
  status port is given the repository and the session factory
- `provisioning/compute/tests/integration/test_release.py`
- `provisioning/compute/service/tests/integration/test_lease_release_api.py`,
  `test_fulfillment_convergence.py`, and `test_compute_contract_api.py`
- `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`

`resolve-compute-family-findings` plans edits to `lease_lifecycle.py` and
`fulfillment_convergence.py`. This section edits other functions in them, and changes
neither `TERMINAL_FAILURE_STATES` nor `_TERMINAL_RESERVATION_STATES` (`design.md`,
"Coordination with `resolve-compute-family-findings`"). Record in this section's notes
whether either change landed first.

- [ ] 8.1 Add `compensable(state, failure_reason, provider_metadata)` to
      `compute_provisioning.release`. It is true when the state is `failed`, the
      reason is `provider_reported_failure`, and the metadata parses as
      `JobFulfillmentMetadata` with `operation` `create`.
- [ ] 8.2 `submit_release` calls `compensable` with the record's fields. It answers
      `TEARDOWN` for a compensable `failed` aggregate, and `UNRELEASABLE`
      (`fulfillment_failed`) for any other `failed` one.
- [ ] 8.3 `FulfillmentServiceTeardownPort.begin_teardown` reads the current state:
      - for `failed`, it calls `begin_compensating_teardown` with
        `authorize=lambda candidate: compensable(candidate.state,
        candidate.failure_reason, candidate.provider_metadata)`;
      - for any other state, it calls `begin_fulfillment_teardown`.

      It translates `CompensationRefusedError` into `TeardownRefused`
      (`compensation_refused`), and passes every other error through.
- [ ] 8.4 `FulfillmentReleaseStatusPort` reads the record through the repository and
      calls `compensable` with its fields. It answers by D4's state table, with
      `READY_FOR_TEARDOWN` for a compensable `failed` aggregate. The composition
      gives it the repository and the session factory the executor holds.
- [ ] 8.5 When `begin_teardown` raises `TeardownRefused`, the lease lifecycle records
      `release_failed` with the refusal's reason and message, under the release
      handle, through the site's conditional write. `_mark_release_failed` gains an
      explicit expected-handle argument:
      - On the release path, `_begin_recorded_teardown` passes the decision's
        `fulfillment_id`, which `begin_release` has just recorded. Its reservation
        was read before that write, so it is not used without the handle.
      - In the releasing pass, the reservation read in that cycle supplies its
        recorded `release_job_id`, as today.

      Every other error stays transient, as today.
- [ ] 8.6 Convergence's teardown-failure write keeps a `create_compensation` reason
      and replaces only `failure_message`. For every other aggregate it writes
      `provider_reported_failure`, as today.
- [ ] 8.7 Update the tests that pin the old behaviour. The design found the set
      below; re-list it at section start:
      - `provisioning/compute/tests/integration/test_release.py`
      - `provisioning/compute/service/tests/unit/services/test_ledger_lease_lifecycle.py`
      - `provisioning/compute/service/tests/integration/test_lease_release_api.py`
      - `provisioning/compute/service/tests/integration/test_compute_contract_api.py`
- [ ] 8.8 Unit and library integration tests:
      - `compensable` for each eligible and ineligible row: quarantined,
        `invalid_provisioned_resource_metadata`, no metadata, unreadable metadata,
        and another provider's metadata;
      - the status port's answer for every state in D4's table;
      - the teardown port: `active`, already begun, compensable `failed`, refused,
        and a state that changed between its read and the kit's transaction;
      - the release path records a refusal under the decision's `fulfillment_id`,
        and a refusal under a handle another release has since replaced is refused
        by the site and left as it is;
      - convergence:
        - a compensating teardown that fails keeps `create_compensation`, and its
          message becomes the teardown's detail;
        - an `active` fulfillment's teardown that fails and later succeeds never
          carries `create_compensation`.
- [ ] 8.9 Application integration, through the typed clients under the mock profile:
      - **Bare metal.** A grant runs but yields no evidence, and the lease is
        terminated:
        - the lease becomes `releasing`;
        - one reclaim job is dispatched;
        - the aggregate reaches `torn_down` carrying `create_compensation`;
        - capacity returns once, and never before `torn_down`;
        - a repeated termination starts no second teardown.
      - **Create in flight, then failed.** The lease is terminated while the create
        is `dispatching`, and the create then fails compensably. The releasing pass
        begins the compensation, and capacity returns at `torn_down`.
      - **Ineligible rows.** For each, the lease is `release_failed` and capacity is
        held.
      - **Refused compensation.** For a compensable row whose create job is missing:
        - the lease is `release_failed` with `compensation_refused`, under the
          handle it entered `releasing` with;
        - the aggregate stays `failed`;
        - capacity is held.
      - **A failing compensation** leaves the lease `release_failed`, with capacity
        held and the aggregate carrying `create_compensation`.
      - **Delivered teardown.** An `active` fulfillment whose teardown fails once and
        then succeeds is not reported compensated.
      - **VM.** A create that fails after dispatch on a relay-backed pool tears
        down, and its relay port returns with the capacity, not before. Its create
        output comes from a rule armed in the test, since the default mock reports
        no relay.
- [ ] 8.10 Verification:
      - `make -C provisioning/compute test` (unit and library integration);
      - `make -C provisioning/compute/service test` (application integration);
      - `make check-packaging`.

      End-to-end: no pipeline scenario fails a create deliberately, and none is
      added. The application integration cases are the lowest level that proves the
      lifecycle. The live bare-metal lane's supported teardown is the system
      evidence.

## 9. A VM storefront reads a compensating fulfillment as a failed delivery

Delivers D4's VM storefront reader ("Readers"), for the `physical-provisioning` delta
requirement "An undelivered lease is released by what its fulfillment proves". Files:
- `domains/vms/storefront/src/market_storefront/services/fulfillment_resume_runtime.py`
- `domains/vms/storefront/tests/unit/test_fulfillment_resume_runtime.py`
- `domains/vms/storefront/tests/unit/test_failure_policy.py`, for the failure actions
  in `domains/vms/storefront/src/market_storefront/failure_actions.py`

- [ ] 9.1 The fulfillment resume treats a `create_compensation` reason, in any state,
      as a failed delivery, as it treats `failed`.
- [ ] 9.2 Unit tests:
      - an aggregate in `teardown_dispatch_pending`, `tearing_down`,
        `teardown_failed`, or `torn_down` carrying `create_compensation` is a failed
        delivery;
      - a delivered aggregate's `torn_down`, carrying another reason, is not;
      - the failure actions' capacity release is still refused by the guarded site
        release until the aggregate is `torn_down`.
- [ ] 9.3 Verification:
      - `make -C domains/vms/storefront test` (unit and application integration);
      - `make check-packaging`.

      End-to-end: none. No pipeline scenario fails a create deliberately.

## 10. A bare-metal reclaim of an account that was never created succeeds

Delivers D4's domain safety for bare metal, for the delta requirement "A bare-metal
reclaim tolerates an account its grant never created". Files:
- `domains/bare_metal/provisioning/iac/ansible/roles/bare-metal-access/tasks/main.yml`
- `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_codec.py` (the
  role-variable test class)

- [ ] 10.1 Before key removal or locking, the reclaim checks whether the tenant
      account exists. When it does not:
      - it skips key removal and locking;
      - it reports `account_present: false` in its fact;
      - it creates nothing.

      An existing account is handled as today, under each policy.
- [ ] 10.2 Tests:
      - role-structure unit tests that the existence check precedes every task
        reading the account, and that the reclaim fact carries `account_present`;
      - `ansible-playbook --syntax-check` on the access playbook;
      - the codec's reclaim interpretation accepts the new field.

      Owed outside this section: running the role against a host that lacks the
      account is the live lane's evidence. No repository suite runs a playbook
      against a host.
- [ ] 10.3 Verification:
      - `make -C domains/bare_metal/provisioning/adapter test` (unit);
      - `make check-packaging`.

      End-to-end: the bare-metal mock lane runs no playbook. The live bare-metal
      lane is the system evidence.

## 11. A compute shape need not state a GPU

Delivers D7's schema and VM vocabulary, for the delta requirement "The compute family
shares one capability schema". Files:
- `domains/compute/src/arkhai_compute/capability_schema.py`
- `domains/compute/tests/test_capability_schema.py`
- `domains/vms/domain/src/arkhai_vms/schema.py`, `capability_shapes.py`, and their
  tests
- `domains/vms/listings/src/arkhai_vms_listings/`: models, resources, pricing, and
  `listing_shapes.py`

- [ ] 11.1 Make `gpu.count` and `gpu.model` not required. The VM shape rule refuses a
      `gpu` family that names only one of them. Bare metal's own rules are
      unchanged, and its tests prove it still refuses a shape without `gpu`.
- [ ] 11.2 Make the listing models and accessors tolerate a missing GPU:
      - `ComputeResource`'s GPU fields become optional;
      - compute and token resources are told apart by the token resource's fields,
        and `resource_is_compute` uses the same test;
      - `VmListing` requires both GPU fields or neither;
      - `ResolvedShape`'s GPU accessors tolerate absence.
- [ ] 11.3 Unit tests:
      - flattening, unflattening, and the digest of a shape without `gpu`;
      - a half-stated `gpu` refused;
      - a CPU listing parsed as compute;
      - a token listing still parsed as tokens;
      - the bare-metal refusal kept.
- [ ] 11.4 Verification:
      - `make -C domains/compute test` (unit);
      - `make -C domains/vms/domain test` (unit);
      - `make -C domains/vms/storefront test-unit`, where the listings package's
        tests run;
      - `make check-packaging`.

      End-to-end: `e2e_listing_shapes` re-runs its GPU shapes over the changed
      schema.

## 12. The VM storefront publishes, prices, and claims a stated CPU-only shape

Delivers D7's storefront half ("CPU-only VM shapes"), for the delta requirements
"Every VM listing is a listing shape" and "A listing's published shape comes from its
source declaration". Files:
- `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
- `domains/vms/settlement/src/arkhai_vms_settlement/compute_lease.py`
- `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py` (the
  reservation response's `gpu_count`)
- `domains/vms/storefront/src/market_storefront/models/capacity_admin_models.py`
- `core/storefront-client/src/storefront_client/models.py`
  (`ReserveCapacityResponse.gpu_count`)
- `domains/vms/storefront/tests/integration/test_reconciler_derivation.py` and
  `test_admin_api.py`
- `kit/site/tests/integration/test_ledger.py` (test only)

The administrator controller is also in `resolve-compute-family-findings`'s plan
(`_INTERRUPTIBLE_HELD_STATES`). This section edits only the reservation response.

- [ ] 12.1 Reconciler member usage keeps each member that has a resource type and
      declared capacity, for stated shapes:
      - GPU totals are optional, and are reported only for default generation, which
        is unchanged;
      - listing reopening and GPU-model ordering tolerate a shape without a model;
      - the compute lease encoding omits absent GPU fields.
- [ ] 12.2 The VM administrator reservation response's `gpu_count` becomes optional,
      in the server model and the storefront client's model:
      - it is read from the reservation's `dimensions` when they are present, and is
        absent when they name no `gpu_count`;
      - it is read from `allocated_gpu_count` only when the reservation has no
        `dimensions`;
      - nothing coerces it to one.
- [ ] 12.3 Update `test_reconciler_derivation.py`'s case for a member without GPUs:
      it yields nothing under default generation, and serves a stated CPU shape.
- [ ] 12.4 Library integration in `kit/site`: a claim whose `dimensions` name vCPU,
      memory, and disk and no `gpu_count` is admitted holding exactly those, with
      `units` 0 and its `dimensions` authoritative. Its release returns exactly
      those. Add the case only if `test_ledger.py` does not already prove it, and
      record which in this section's notes.
- [ ] 12.5 Application integration, through the storefront's typed client against a
      site projection:
      - a pool hint stating `{cpu: {count: 2}, memory: {gib: 2}, storage: {gib: 20}}`,
        over a member declaring vCPU, RAM, and disk, publishes one listing with no
        GPU fields;
      - negotiating it builds a capacity claim requesting exactly those quantities;
      - per-family rates price it from the flat tiers, and a storefront configuring
        per-GPU-model terms and rates applies none of them to it;
      - reserving the CPU-only listing as administrator, through the storefront
        client's `admin_reserve_capacity`, returns a response with no `gpu_count`.
- [ ] 12.6 Verification:
      - `make -C domains/vms/storefront test` (unit and application integration);
      - `make -C core/storefront-client test` (unit);
      - `make -C kit/site test` (library integration);
      - `make check-packaging`.

      End-to-end:
      - `e2e_listing_shapes` re-runs for its GPU shapes.
      - No pipeline lane provisions a CPU-only VM. The live VM lane is the system
        evidence (`design.md`, "CPU-only VM shapes").

## 13. An aarch64 guest, and a teardown that removes only its own guest

Delivers D7's guest recipe and D9, for the delta requirements "A VM guest matches its
host's architecture" and "A VM teardown removes only what its guest created". Files:
- `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/`: `vm-create.yml`,
  `vm-remove.yml` with the cleanup script it generates, and `vm-undefine.yml`
- new role-structure tests in `domains/vms/provisioning/adapter/tests/unit/`
- `domains/vms/provisioning/iac/README.md`

- [ ] 13.1 Select the cloud image, machine, and firmware from the target host's
      architecture:
      - each architecture's image is pinned to a dated release with its published
        checksum, and verified before use;
      - `aarch64` uses `--arch aarch64 --machine virt --boot uefi`;
      - an architecture with no pinned image fails before any host effect.

      The `x86_64` path keeps its behaviour, except that its image is now pinned and
      verified.
- [ ] 13.2 Every firewall and NAT rule a create adds for a guest carries a comment
      naming the guest:
      - the cleanup script removes rules by that exact comment;
      - unmarked rules are removed by the guest's `/32` address, never a prefix;
      - the subnet-wide masquerade rule is left alone.
- [ ] 13.3 `vm_remove` with no cleanup script:
      - removes what it finds by the guest's name: the domain with its storage and
        firmware variables, the images, the relay proxy block, the DHCP
        reservation, and the marked rules;
      - reports the guest absent only when it finds none of them;
      - fails, naming the artifact, when it finds one it cannot attribute.
- [ ] 13.4 The VM IaC README lists the host prerequisites (`design.md`, "CPU-only VM
      shapes"). It warns that `playbooks/host-kit/vm-setup.yaml` must not run on a
      host whose management access must be preserved.
- [ ] 13.5 Tests:
      - **Role-structure unit tests:**
        - architecture selection;
        - checksum verification before definition;
        - the comment on every added rule;
        - no prefix match in cleanup;
        - the attribution checks of the missing-script branch.
      - `ansible-playbook --syntax-check` on the VM operations playbook.

      Owed outside this section: a real guest boot and teardown on `aarch64` are the
      live VM lane's evidence.
- [ ] 13.6 Verification:
      - `make -C domains/vms/provisioning/adapter test` (unit);
      - `make -C provisioning/compute/service test`;
      - `make check-packaging`.

      End-to-end: the VM mock lanes run no playbook, so recipe changes do not reach
      them. The live VM lane is the system evidence.

## 14. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only. A part that would need a code edit returns the
change to implementation.

- [ ] 14.1 **Comment hygiene.** Run `make check-comment-hygiene`. Any finding, or a
      comment Sections 2–13 added that still describes history, returns the change
      to implementation.
- [ ] 14.2 **Import placement.** Confirm that every import Sections 2–13 added is at
      module level, or carries a verified reason to stay local.
- [ ] 14.3 **Documentation compliance.** Re-check D1–D10 against `openspec/README.md`'s
      placement rules and `design.md`'s promotion record.
- [ ] 14.4 **Narrative compression.** Compress these task notes to final behaviour,
      material evidence, deferred work, and destinations.
- [ ] 14.5 **Roadmap currency**, in `docs/development/ROADMAP.md`:
      - Under "Goal 1 — Consolidate physical-resource authority in the provisioning
        service", the gap row "The real runner reports no structured
        terminal-failure evidence…" notes that successful results are read in
        either callback form. It stays open for failure classification.
      - Under "Goal 2 — Negotiate full compute capability, not GPU count alone", the
        current state notes that VM shapes stated without GPUs are sold.
      - Under "Payment qualification boundaries", record the gaps this change leaves
        open:
        - D6's exhausted teardown job;
        - D10's operational precondition, that a refresh or reopen under the same
          identity keeps a listing's pause;
        - D10's limits: successor listings are created unpaused, no permanent
          requirement states per-listing pause semantics, no test closes a paused
          listing by reconciliation and reopens it, and bare metal has no test of a
          paused listing refusing an opening;
        - `gpu-optional-compute-shapes`'s remaining scope.
      - Name the update in `design.md`'s promotion record.
- [ ] 14.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md` to `in closeout`, with notes stating what is true
      at closeout, and keep the dependency graph line to
      `gpu-optional-compute-shapes`. That row's `Depends on` stays until archive
      cleanup. Run `make check-change-index`, and name the update in the promotion
      record.
- [ ] 14.7 **Packaging.** Run `make check-packaging` and
      `make check-architecture-change CHANGE=repair-compute-purchase-recovery`. Run
      `make check-agent-skills` only if the change touched `.agents/`, `.claude/`, or
      `.codex/`; it is not planned to.
- [ ] 14.8 **End-to-end pipeline.** Record the pipeline run and its result:
      - the bare-metal lane's `e2e_bare_metal_mock_deal` and
        `e2e_bare_metal_payment_deal`;
      - the VM lane's `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_listing_shapes`,
        `e2e_buy`, and `e2e_non_erc20_settlement`, which read the shipped-form
        default.

      Record the live lanes' qualification separately, as live evidence or as named
      blockers, never as pipeline evidence. The live lanes are the real bare-metal
      and CPU-only ARM64 VM test purchases, each run under D10's operational
      conditions.
- [ ] 14.9 **Promotion**, per `design.md`'s promotion record:
      - `docs/development/ARCHITECTURE.md` "Release": the table's `failed` row splits
        into compensable and not.
      - `openspec/specs/physical-provisioning/architecture.md`:
        - "Durable jobs, transient workers": fact reading and linkage;
        - "The host registry owns the connection": the tenant-facing port;
        - "Proof-driven release": compensation, and the corrected `teardown_failed`
          requeue sentence, which says the requeue re-observes the same failed job
          and does not re-run it (D6).
      - `openspec/specs/fulfillment/architecture.md` "Durable persistence and
        recovery": the compensating teardown and its marker.
      - `openspec/specs/storefront-publication/architecture.md` "Listing shapes and
        the storefront's authority" and "Shape pricing": stated shapes without GPUs,
        and flat-tier pricing.
      - `docs/development/TESTING.md` "4. System Integration Tests (End-to-End)":
        mock output prints the shipped form for the job, and the VM scenarios use
        the default.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`:
        - "Definition documents", the host-inventory paragraph: `public_port=`;
        - "Storefront listing shapes and pool overrides": the shape-constraints
          bullet, corrected for VM shapes stated without the `gpu` family.
      - `domains/vms/provisioning/iac/README.md` "Prerequisites": the aarch64 host
        prerequisites and the `vm-setup.yaml` warning.
      - `docs/seller-quickstart.md` "6. Live KVM provisioning": the tenant-facing
        route and aarch64 hosts.
      - `docs/development/VALIDATION_RUNBOOK.md`, a new generic section on running two
        lanes against one machine in sequence (D10):
        - the freeze and the per-listing pause;
        - read-backs in the site's states, `reserved`, `provisioning`, `leased`,
          `releasing`, `release_failed`, and `unmanaged`, with `provisioning_failed`
          read as terminal;
        - each member's full `available` mapping compared with its `capacity`
          mapping;
        - every accepted deal drained, with no refund taken as proof;
        - the precondition that a refresh or reopen under the same identity keeps
          the pause.
      - `openspec/specs/README.md`: no new capability or companion, so no edit.
        Confirm it.
      - Complete the promotion record.
- [ ] 14.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=repair-compute-purchase-recovery`, then
      `openspec validate repair-compute-purchase-recovery --strict`.
- [ ] 14.11 **Archival.** Run `openspec archive repair-compute-purchase-recovery -y`,
      which merges the deltas into `openspec/specs/`. The deltas were not promoted by
      hand, so `--skip-specs` is not used.
