# Tasks — repair compute purchase recovery

Planned against the design after its second design review (`reviews/02-design.md`) and
that review's triage. Sections run lowest layer first: the shared Ansible kit before the
adapters that compose it, the fulfillment kit before the compute lifecycle that calls
it, and domain vocabulary before the storefront that publishes it. Test levels are
`docs/development/TESTING.md`'s: unit, library integration, application integration
(the running service through its typed client), and system.

**Packaging.** A section that changes a package bumps its minor version once against
`dev`, updates its dependants' exact pins and floors where they use the change, and
refreshes the locks with `make lock` at the repository's uv minimum; its verification
runs `make check-packaging`, which includes `make check-architecture`. A test-only
section changes no version.

**Fixtures are synthetic (D2).** Every fixture uses development values: a reserved
documentation address, a synthetic tenant account, a zeroed identifier, and a
placeholder key. No output, identifier, address, or key from a real host or purchase
enters a test.

**Test cadence** (`design.md`, "Implementation cadence"). Focused suites and packaging
gate every intermediate commit. A frozen round candidate takes the full suite, one
independent review, and one validation; a passing result is reused while its inputs are
unchanged. The live lanes run only on a validated candidate, and merging to `dev` needs
the owner's approval.

**End-to-end evidence.** Each section names the pipeline scenarios (pytest markers in
`e2e-tests/`) that exercise it, or says that none does.

## 1. Design

- [x] 1.1 **Decision gate.** Resolve the independent design reviews. The first review's
      triage amended the design and asked for another round; the second found nothing
      blocking, and its triage recorded `Advance` and carried its corrections into D1,
      D4, D10, the deltas, and this plan.
- [x] 1.2 **Decision gate.** Confirm D7's ownership split with
      `gpu-optional-compute-shapes`.

      Confirmed when planned. Correction: the owner withdrew D7 on 2026-10-29 before
      any of it was implemented, so the split is undone and that change owns its whole
      scope; it has since landed on `dev` and is archived, naming this change nowhere
      (14.7).

## 2. Read a printed fact in either form, for the job's action

D1's reader in the shared Ansible kit, for "A create succeeds only with readable
delivery evidence".

- [x] 2.1 Add a reader that takes the output, the fact name, and the expected action.

      Done: `read_fact(stdout, fact_name, *, action)` in
      `provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`, exported
      from the package. It returns a JSON `var:` fact as `extract_fact` reads it, the
      codec judging its action; otherwise it reads each whole-line `msg: |` or `msg: |-`
      block alone, dedented, as one JSON document, never past the block's end, and
      returns the last whose `action` matches. It logs at debug level only the counts
      of blocks ignored by reason (`not_json`, `not_object`, `no_action`,
      `other_action`), never their content. `extract_fact` reads the JSON form only.
- [x] 2.2 Unit tests on synthetic output in each form the shipped and the JSON
      configurations print.

      Done (unit): fourteen tests, 21 cases, in `tests/unit/test_runner.py`: both
      forms; several and repeated blocks; the prose summary, alone and followed by a
      later document outside any block, which is not adopted; a malformed block beside
      an unrelated document; no `action`; no fact; non-object documents; 2- and
      4-space keys; the JSON format's escaped `msg:`; blank lines and sibling keys; and
      a block nested past `json.loads`' recursion limit. Red against today's
      `extract_fact`: 10 failed, the shipped YAML form reading `None`. The fixtures'
      shape follows the observed callback output (`design.md`, D1).
- [x] 2.3 Verification.

      `make -C provisioning/compute/ansible test`: 114 passed (unit);
      `make check-packaging`, the change, hygiene, and task checks; the section's full
      `make test` passed. `arkhai-compute-provisioning-ansible` went to 0.5.0, later
      0.6.0 against `dev` (14.7). No caller used the reader yet, so no scenario
      exercised it; Sections 4 and 5 carry it into the mock lanes.

## 3. A tenant-facing port beside the tenant-facing address

D3's connection, inventory, and INI changes, for "The tenant-facing host address falls
back to the connection address" and "Host registry records the connection port".

- [x] 3.1 `SshConnection` gains an optional `public_port`; `InventoryTarget` carries it;
      rendering emits `public_port=` when set; the INI format reads it with
      `ansible_port=`'s rule.

      Done in the Ansible kit's `connection.py`, `runner.py`, and `inventory.py`. An
      absent or null port is stored with no key (`public_fields()`), so a host stating
      no route is stored as before. One `_port` helper validates both INI ports; a
      malformed entry is skipped with a warning naming the variable.
- [x] 3.2 Unit tests: a connection with and without the port, a malformed port refused,
      rendering, and an INI round trip with a malformed entry rejected.

      Done (unit). Red: 10 failed on the missing field; green 125 passed. RFC 5737
      documentation addresses and placeholder key paths.
- [x] 3.3 Application integration: a host registered with `public_host` and
      `public_port` reads back with both and renders them into a job's inventory; one
      without reads unchanged.

      Done (application integration), `TestTenantFacingRoute` in
      `provisioning/compute/service/tests/integration/test_hosts_api.py`, through the
      typed host and VM clients, with the real runner's `write_inventory` and playbook
      execution mocked.
- [x] 3.4 Verification.

      The Ansible kit 125 passed (unit); the service 669 unit and 542 integration (mixed
      levels); the adapters' suites; `make check-packaging`; the full `make test`; change
      and hygiene checks. The service took its floor on the kit (`>=0.5.0`) for the codec,
      INI seeding, and inventory rendering it composes. No scenario registers a
      tenant-facing route; the live bare-metal lane is the system evidence.

**`public_port` belongs to `ssh` version 2 (after merging `dev`).** Adding the field to
version 1 in place is what `RELEASING.md`'s versioning policy forbids, so 3.5–3.8 served
version 1 without it and version 2 with it, with a registry keyed by kind and version.
3.9–3.12 then superseded that: after the Round 1 implementation review's F1, the owner
chose to retire version 1 rather than qualify a downgrade (`design.md`, D3,
"Compatibility: `ssh` is served at version 2 only"; `interventions.jsonl`).

- [x] 3.5 The host authority's `ConnectionCodecs` keys codecs by kind and version.

      Done (unit), then removed by 3.10: the registry is `dev`'s again, keyed by kind.
- [x] 3.6 `SshConnectionCodec` serves one version, given at construction.

      Done (unit), then superseded by 3.10's one codec at version 2.
- [x] 3.7 Fixtures that state a port move to version 2; nothing else changes for callers
      that state none.

      Done (application integration, `TestConnectionVersions`), then superseded by 3.11.
- [x] 3.8 Verification.

      The family kit 253, the Ansible kit 134, both adapters, and the service's suites
      passed on that candidate; superseded with it.
- [x] 3.9 Amend the design, proposal, delta, plan, and ledger for `ssh` at version 2
      only.

      Done: D3's compatibility, the delta's "Host registry records the connection port"
      and "Host connections are typed by their implementation's codec" with scenarios for
      an unversioned or version-1 submission, a stored version-1 host refused before any
      playbook, and a host moved forward by an update keeping its key or by an import.
- [x] 3.10 One `ssh` model and codec at version 2.

      Done. `SshConnection` carries `public_port`; `SSH_CONNECTION_VERSION` is 2;
      `ssh_connection()` and the INI import submit version 2; `parse` refuses any other
      kind or version before reading a field, naming re-registration; a protected key a
      submission does not resubmit is carried forward as opaque ciphertext. The family
      registry is `dev`'s, its `build` refusing another version. Three `e2e-tests`
      helpers, the runbook's host requests, and the issue-discovery tool's local phase
      state version 2, since `ConnectionSubmission` still defaults to 1.
- [x] 3.11 Tests for version 2 only.

      Done. Unit (Ansible kit): every submission at version 2; stored versions 1 and 3
      and other kinds refused; a version-1 row's protected key carried forward; a
      version-1 host never reaching an inventory. Application integration (service,
      typed clients): unversioned, 1, and 3 refused with nothing stored; an update and an
      INI re-import moving a seeded version-1 row forward, the key kept byte for byte and
      the next job succeeding. Version-1 rows are written directly as setup.
- [x] 3.12 Verification.

      After `make dist-clean` and `make dist`: the family kit 243 (back to `dev`'s
      0.21.0 and floors), the Ansible kit 133, the bare-metal adapter 77, the VM adapter
      262, the service 607 unit and twenty affected integration modules (`test_hosts_api`
      52), e2e unit 172; packaging, hygiene, change, and task checks; wheels equal their
      source. The Ansible kit stays at its one bump for this change. The pipeline's hosts
      register at version 2, so the VM and bare-metal lanes exercise it.

## 4. Bare-metal grants yield evidence linked to their job, on the buyer's route

D1's bare-metal linkage, D2's shipped-form mock, and D3's endpoint, in
`domains/bare_metal/provisioning/adapter`.

- [x] 4.1 The codec reads its fact through Section 2's reader, with the job's action,
      and a grant yields evidence only when the fact names the job's action, host,
      tenant account, machine (when the job names one), and status `success`.

      Done in `codec.py`. `fact_mismatch` names every mismatch in one string; a job
      naming no tenant account is itself one. A linked grant's endpoint is the execution
      host's `public_host or ssh_host` and `public_port or ssh_port`, with the confirmed
      account; the fact's own host and port are detail. A reclaim's linked fact is its
      result, and a mismatched one is replaced by `{"mismatch": ...}`, a diagnostic only:
      the reclaim job's status decides its teardown (D1; the delta's "A bare-metal
      reclaim's printed fact is a diagnostic").
- [x] 4.2 The mock prints the shipped configuration's form, rendered for the job.

      Done in `services/mock_output.py`: `shipped_output` prints the YAML `var:` display
      and the `msg: |-` JSON copy. Its one known difference from the role, a grant naming
      no tenant account, is recorded in D2.
- [x] 4.3 Unit tests: a shipped-form grant; each mismatch; another action's document only;
      the endpoint with and without a tenant-facing route; a reclaim in both forms.

      Done (unit). Red: 22 failed, the shipped form reading nothing; green 77 passed.
      `test_bare_metal_fulfillment_plan.py` now expects the tenant-facing endpoint. The
      fixture renderer in `tests/execution.py` is independent of the production one.
- [x] 4.4 Application integration under the mock profile: a shipped-form grant reaches
      `active` on the tenant route; a grant naming another tenant leaves the fulfillment
      `failed` with no evidence.

      Done (application integration), `test_bare_metal_mock_profile.py`, through the
      typed clients. The behavioural red is 4.3's.
- [x] 4.5 Verification.

      The adapter 77 passed (unit); the service 669 unit and 544 integration (mixed
      levels); `make check-packaging`; the full `make test`. The adapter went to 0.11.0,
      later 0.12.0 against `dev`, with floors on the Ansible kit `>=0.5.0`; the service's
      floors on the adapter rose with it. End-to-end: `e2e_bare_metal_mock_deal` and
      `e2e_bare_metal_payment_deal` read the shipped-form default through the real read
      path; the live bare-metal lane is a real grant's evidence.

      The first full run exposed a flaky API-credits test: a settlement coordinator task
      left pending by an earlier test was destroyed by garbage collection inside a later
      one, since pytest-asyncio closes a test's loop without cancelling its tasks. Fixed
      test-only in `domains/apicredits/storefront/tests/unit/test_settlement_fulfillment.py`:
      each test that starts background settlement awaits the coordinator's own task. A
      two-test reproduction with forced collection went from one red in about six runs to
      none in 30 (library integration), and the full `make test` then passed.

## 5. VM reads facts through the shared reader, linked to its guest

D1 and D2 for VM, in `domains/vms/provisioning/adapter` and five VM scenario modules.
`resolve-compute-family-findings` landed first: the VM codec tests live in the adapter's
`tests/unit/test_vm_codec.py`, and the scenarios build typed `MockRuleCreate` rules. The
merge also fixed the service's integration fixtures, which re-mounted the test routers
on every setup until the lifespan stack overflowed: they mount through
`mount_unless_served`, held by `tests/integration/test_test_router_mounting.py`.

- [x] 5.1 Replace `extract_vm_fact`'s private `msg:` fallback with Section 2's reader.

      Done in `codec.py`, the expected action from `VM_FACT_ACTIONS`. The forward
      fallback and the whole-output regex readers of a port and an account are removed.
- [x] 5.2 A create's fact yields evidence only when its `action` is `create`, its
      `vm_name` the job's `vm_target`, and its `status` `success`; the account and port
      come from that fact or its relay block.

      Done: `create_fact_mismatch` names a mismatch in the result's detail. The address
      stays the registry's; a guest's port is its forwarded or relay port, never the
      host's `public_port`. A defect found on the way: a disabled relay block's
      `remote_port: 'N/A'` replaced the forwarded port, so a direct-path buyer-key create
      reported no evidence; only an enabled relay's port replaces it now (D1).
- [x] 5.3 `vm_mock_output` renders the shipped form for the job.

      Done in `services/mock_output.py`: a create names the job's guest and tenant
      account, reports `success` on forwarded port `2222`, and prints the provided-key or
      generated-key fact by the job's key; a remove prints `vm_remove_data` for the
      guest; other actions print a minimal success fact under their own name.
- [x] 5.4 Drop `result_stdout` from the create rule in each of the five scenario modules.

      Done; each rule keeps its `rule_id`, `match`, and `pause_before_result`. The fixed
      names were asserted nowhere.
- [x] 5.5 Unit tests for each action's shipped form, adoption across actions, linkage,
      the registry address, and the mock through the codec.

      Done (unit), `tests/unit/test_vm_codec.py` and the new
      `tests/unit/test_vm_mock_output.py`, with a test-local shipped-form renderer. Every
      new case failed on `HEAD`'s code on behaviour: a remove adopting a create document,
      evidence from another guest's or a `running` fact, a port read outside the fact,
      the mock naming another guest, and the disabled relay's `N/A` port.
- [x] 5.6 Verification.

      The VM adapter 262 passed (unit and library integration); the service's VM and
      mock-profile integration modules 316 (mixed levels); e2e unit 172;
      `make check-packaging`. The service's create fixture now renders for the job's
      guest and reports `success`, since a fixed guest yields no evidence under the
      linkage. The adapter went to 0.16.0 against `dev`'s 0.15.0, floors on the Ansible
      kit `>=0.5.0`. End-to-end: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_listing_shapes`,
      `e2e_buy`, and `e2e_non_erc20_settlement` read every create through the per-job
      default; the live VM lane is a real guest's evidence.

## 6. Recover what `buy` recorded, and qualify the payments upgrade

D5 and the payments qualification in "Context".

- [x] 6.1 Test: `buy_bare_metal` writes a real run log under a temporary XDG state
      directory, and `_recovered_deal` reads it back with the same publisher principals,
      publisher, and registry binding.

      Done, `test_a_deal_bought_is_recovered_from_the_run_log_buy_wrote` in
      `domains/bare_metal/buyer/tests/test_run_log_recovery.py`. Only the command
      module's four factories are replaced; the configuration loader, the payments kit's
      `PaymentApproval` over `FakePaymentsClient`, and the command's own HTTP
      collaborators run for real against a loopback seller that verifies each version 2
      proof and signs as the listing's publisher. `access --run-id` then reads through
      the same recovery. CLI component integration with faked registry, payments, and
      seller boundaries. It passed first time, qualifying the producer already on the
      base (D5); a negative control recording the retired list form was refused with
      "malformed publisher_principals". Fixtures are development values.
- [x] 6.2 Qualify the payments upgrade with no code change.

      Done. After `make dist` and the buyer's `reinit`, the installed payments kit and
      core buyer equal their source. `make -C kit/arkhai-payments test`, 92 passed
      (unit), covers signed `livemode`, a receipt from the other mode refused on both
      sides, and generated models forbidding extra fields; no test isolates one unknown
      receipt field. The captured receipt, replayed once locally and not kept, verified
      in test mode and was refused under live mode, a flipped mode, a tampered proof,
      another mandate, and an extra field.
- [x] 6.3 Verification.

      The bare-metal buyer 17 passed, one of them the integration case above; the
      payments kit 92 passed. No package changed. End-to-end: `e2e_bare_metal_payment_deal`
      re-drives settlement from the run log without reaching `_recovered_deal`, and skips
      without a payments target; `e2e_bare_metal_unbacked_introduction` reaches it
      through `settlement contact introduce --run-id`. The real-host scenario's wrong
      options are Section 11's (D14). `test_cli_completion.py` still replaces imported
      names rather than only the module's factories; it was left as it is.

## 7. The fulfillment kit begins a compensating teardown

D4's kit half ("The kit operation", "The compensation marker"), in `kit/fulfillment`,
for the `fulfillment` delta's "Scheduling and assignment".

- [x] 7.1 Add the transition `failed` → `teardown_dispatch_pending`, and the constant
      `CREATE_COMPENSATION = "create_compensation"`.

      Done (unit) in `transitions.py`, exported; `failed` reaches only that state, and
      `torn_down` and `abandoned` reach none.
- [x] 7.2 Add `FulfillmentOrchestrator.begin_compensating_teardown(fulfillment_id,
      *, authorize)`, with `CompensationCandidate` and `CompensationRefusedError`.

      Done (unit and library integration), answering D4's state table in one write
      transaction, as built (`design.md`, D4, "The kit operation"):
      `get_by_fulfillment_id_for_write` takes the writer slot first, and
      `begin_compensating_teardown` writes the prepared operation and the reason only.
      `begin_fulfillment_teardown` still refuses `failed`.
- [x] 7.3 Tests: unit for the transitions, each state-table row, `authorize`'s candidate,
      and a propagated preparation error; library integration for concurrency and the
      diagnostics.

      Done. Unit (`test_fulfillment.py`, `test_fulfillment_persistence.py`): every row;
      `authorize`'s copy is isolated from the record, which a shallow copy fails. Library
      integration (`tests/integration/test_compensating_teardown.py`, file-backed SQLite,
      independent sessions): each refusal writes nothing; a concurrent ordinary teardown
      refuses, then adopts, with one prepared teardown; a second compensation fails at the
      writer slot, and removing the reservation fails that case; the diagnostics count the
      row through `failed`, the teardown states, and `teardown_failed`, and it leaves
      every count at `torn_down`. The design and the delta now say the row leaves every
      count, since the projection has no `torn_down` entry. `test_import_boundaries.py`
      admits `copy` and `types`.
- [x] 7.4 Verification.

      `make -C kit/fulfillment test`: 200 passed. `arkhai-kit-fulfillment` 0.6.0;
      `make check-packaging`. No pipeline scenario fails a create; owed by validation:
      none.

## 8. Release compensates eligible failed creates

D4's compute half ("Eligibility", "The compute-owned seam", "Release paths"), for the
`physical-provisioning` delta's "An undelivered lease is released by what its
fulfillment proves". `resolve-compute-family-findings` landed first and was merged
before Section 5; this section changes neither `TERMINAL_FAILURE_STATES` nor
`_TERMINAL_RESERVATION_STATES`.

- [x] 8.1 Add `compensable(state, failure_reason, provider_metadata)` to
      `compute_provisioning.release`.

      Done (unit): true for `failed`, `provider_reported_failure`, and metadata parsing
      as `JobFulfillmentMetadata` with `operation` `create`. `PROVIDER_REPORTED_FAILURE`
      lives beside it, and convergence writes it from there.
- [x] 8.2 `submit_release` answers `TEARDOWN` for a compensable `failed` aggregate and
      `UNRELEASABLE` (`fulfillment_failed`) for any other.

      Done (library integration, `test_release.py`'s decision table).
- [x] 8.3 `FulfillmentServiceTeardownPort.begin_teardown` compensates a `failed` aggregate
      through `compensable` and begins an ordinary teardown otherwise, translating
      `CompensationRefusedError` into `TeardownRefused` (`compensation_refused`).

      Done (library integration). The service's `DeferredFulfillmentTeardownPort`
      delegates both calls to it, so the rule has one implementation.
- [x] 8.4 `FulfillmentReleaseStatusPort` reads the record and answers by D4's state
      table, `READY_FOR_TEARDOWN` for a compensable `failed` aggregate.

      Done (library integration); it takes `settlement_repository` and
      `session_factory`.
- [x] 8.5 A `TeardownRefused` makes the lease `release_failed` with its reason under the
      release handle; `_mark_release_failed` takes an explicit expected handle.

      Done (unit). The release path passes the decision's `fulfillment_id`; the
      releasing pass passes the handle it read. `_begin_recorded_teardown` returns the
      lease's state, so a refused termination answers `release_failed`.
- [x] 8.6 Convergence's teardown-failure write keeps a `create_compensation` reason.

      Done (library integration) in `_apply_teardown_failure`, reading the reason inside
      the owned write transaction.
- [x] 8.7 Update the tests that pin the old behaviour.

      Done: `test_release.py`'s table; `test_lease_release_api.py`'s failed grant, which
      set `failed` with no reason, replaced by 8.9's ineligible cases; the status port's
      constructor in the lifecycle test and the service fixtures.
      `test_compute_contract_api.py` still answers 409 for an ordinary teardown of
      `failed`.
- [x] 8.8 Unit and library integration tests.

      Done. Unit: `compensable` over eligible and every ineligible row
      (`provisioning/compute/tests/unit/test_compensable.py`); the lifecycle's refusal
      under the decision's handle, refused by the site under a replaced handle (passing
      the read handle fails it). Library integration: the status port for every state;
      the teardown port against the real orchestrator and SQLite, including a state
      changing between its read and the kit's transaction; convergence keeping the
      marker through a failure and requeue, which an unconditional write fails, and a
      delivered teardown never carrying it.
- [x] 8.9 Application integration through the typed clients under the mock profile.

      Done, convergence and the lease watchdog stepped explicitly. Bare metal
      (`test_lease_release_api.py`): an unlinked grant compensated with one reclaim and
      capacity returned once, only at `torn_down`; a create held, then failed,
      compensated by the releasing pass; four ineligible rows `release_failed` with
      capacity held; a missing create job refused (`compensation_refused`) under the
      handle it entered `releasing` with; a failing compensation keeping the marker; a
      delivered teardown never marked. VM (`test_fulfillment_api.py`): a relay-backed
      failed create compensated, its relay port returned with the capacity.
- [x] 8.10 Verification.

      `make -C provisioning/compute test` 280; the service 607 unit and 476 integration;
      `make check-packaging`. `arkhai-compute-provisioning` 0.22.0 at the time, floor on
      the fulfillment kit `>=0.6.0`, later 0.23.0 against `dev` (14.7). No pipeline
      scenario fails a create; the application cases are the lowest level that proves
      the lifecycle.

## 9. A VM storefront reads a compensating fulfillment as a failed delivery

D4's VM storefront reader ("Readers").

- [x] 9.1 The fulfillment resume treats a `create_compensation` reason, in any state, as a
      failed delivery, as it treats `failed`.

      Done (unit) in `fulfillment_resume_runtime.py`'s `_load_active_physical_result`:
      the delivery is recorded `failed` in `physical_failed` and the accepted entry's
      failure policy runs with `provisioning_failed`. The foreground poll is left as it
      is (`design.md`, D4, "Readers").
- [x] 9.2 Unit tests: each teardown state with `create_compensation` is a failed delivery;
      a delivered `torn_down` with another reason is not; the failure actions' release
      stays refused by the guarded site until `torn_down`.

      Done (unit), `test_fulfillment_resume_runtime.py` over a real
      `FulfillmentStatusResponse`, and `test_failure_policy.py` over the fake site.
      Red: the four compensating cases failed against `HEAD`; treating any non-null
      reason as a failure fails the `provider_reported_failure` cases, so the marker
      decides. The failure-policy case passed before and after, pinning D4's "no change
      needed"; it patches two module names, matching the module's existing seam, which
      `TESTING.md` discourages.
- [x] 9.3 Verification.

      `make -C domains/vms/storefront test`: unit 1158 passed and 1 skipped, integration
      476 (both folders mixed levels); `make check-packaging`. `arkhai-vms-storefront`
      0.24.0, later 0.25.0 against `dev`, floor on the fulfillment kit `>=0.6.0`. No
      pipeline scenario fails a create.

## 10. A bare-metal reclaim of an account that was never created succeeds

D4's domain safety for bare metal, for "A bare-metal reclaim tolerates an account its
grant never created".

- [x] 10.1 Before key removal or locking, the reclaim checks whether the tenant account
      exists, and when it does not, skips both, reports `account_present: false`, and
      creates nothing.

      Done in `domains/bare_metal/provisioning/iac/ansible/roles/bare-metal-access/tasks/main.yml`,
      as `design.md` D4 describes: a `getent passwd` lookup gating the four account
      tasks, and `account_present` in the fact beside `account_locked` and
      `account_deleted`. The mock's default reclaim prints it too (booleans since 14.10
      and 14.38).
- [x] 10.2 Tests: role structure, the access playbook's syntax check, and the codec
      accepting the new field.

      Done. Unit `TestReclaimOfAnAbsentAccount` in `test_bare_metal_codec.py`: the lookup
      precedes and gates every account task, takes no `become`, and fails on any exit
      but 0 and 2. Red: five failed against `HEAD`'s role; green 47. The codec reads the
      fact unchanged under each policy. `--syntax-check` of `node-access.yaml` passed on
      ansible-core 2.19.14, outside the repository; a local run for a synthetic absent
      account exited 0 under each policy and created nothing, where `HEAD`'s role failed
      "Failed to lookup user". Corroboration, not a host-lane result.
- [x] 10.3 Verification.

      The adapter 88 passed (unit); the service's two bare-metal mock-profile modules 23;
      `make check-packaging`. No version changed. The mock lanes read the default reclaim;
      a real reclaim of an absent and of a present account is the live bare-metal lane's.

## 11. The real-host bare-metal scenario drives the buyer commands as they ship

**Replanned against the scope revision of 2026-10-29** (`design.md`, "Scope revision").
Sections 11 to 14 replace the plan's earlier Sections 11 to 13, none of which had
started: the CPU-only shape and storefront sections are withdrawn with D7; the earlier
`aarch64` section's recipe is withdrawn, its x86-64 image pin becoming Section 12 (D11)
and its teardown repairs Section 13 (D9). Sections 7 to 14 are one preflight round,
frozen after Section 14; the closeout is Section 15.

D14, the Round 1 review's F3, as test code only, in `e2e-tests`.

- [x] 11.1 The scenario runs `result`, `access`, and `teardown`, each with `--run-id` and
      `buy`'s id, reading JSON with no flag; the run-id resolver reads `--run-id <id>`,
      `--run-id=<id>`, and `--from=<id>`.

      Done: `recovery_command` in `e2e-tests/tests/e2e/roles/helpers/bare_metal_access.py`;
      the run from `buy`'s own run log; `run_id_from_args` in `buyer_cli.py`. The purchase's
      expected events corrected to what `buy` writes (`design.md`, D14).
- [x] 11.2 Teardown repeats `teardown --run-id` and reads its `state` until `released`,
      failing at once on `teardown_failed` and at its bound with the last state.

      Done: `wait_for_release(teardown, *, timeout_seconds, poll_interval_seconds, clock,
      sleep)`; `TERMINAL_TEARDOWN_STATUS` is gone.
- [x] 11.3 Every access attempt is a fresh, pinned SSH process, classified as accepted,
      revoked by a public-key refusal, or an error.

      Done: `ssh_command` and `classify_ssh`, with the options D14 lists; the pinned file
      is the role input `ARKHAI_E2E_BARE_METAL_KNOWN_HOSTS_FILE`, without which the
      scenario skips. The first attempt must be accepted and the one after teardown
      refused.
- [x] 11.4 Unit tests for the argument lists under the installed parser, the resolver, the
      teardown wait, SSH, and the purchase's events.

      Done (unit), `tests/unit/test_bare_metal_deal_commands.py`, 35 cases: each list
      parsed by the installed `bare-metal` entry point's Typer command with
      `make_context`, and the earlier forms refused by it; the resolver and run binding;
      the wait over scripted answers and a fake clock; every SSH option and each error
      class. The buyer's `test_run_log_recovery.py` pins the producer's event sequence.
      Red: `HEAD`'s resolver bound no run for three of the new forms.
- [x] 11.5 Verification.

      e2e unit 208 passed; the bare-metal buyer 17; the scenario collects and was not
      run; `make check-packaging`. No production file changed. The scenario is in no lane;
      a real storefront's states, a real host's refusal, and the run itself are the live
      bare-metal lane's. The roles README's two paragraphs on it were folded into one
      (14.11).

## 12. An x86-64 guest is created from a pinned, verified image

D11, for "A VM guest is created from a pinned, verified image".

- [x] 12.1 The scratch image is one dated release of the Ubuntu Noble x86-64 cloud image,
      pinned with its SHA-256, stored under a name carrying the release, verified before
      it backs any disk on both paths, and the create refuses a non-`x86_64` target before
      any host effect.

      Done, as `design.md` D11's "As built" records: release `20261017`
      (`https://cloud-images.ubuntu.com/noble/20261017/noble-server-cloudimg-amd64.img`,
      SHA-256 `04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94`), its
      signed checksum list verified when the digest was taken; `vars/main.yml` new; the
      image tasks in `vm-create.yml`; the architecture check in `prerequisites.yml`.
      Golden images are unchanged.
- [x] 12.2 Tests: role structure, behaviour through `shell_harness`, and the syntax check.

      Done (unit), `domains/vms/provisioning/iac/tests/test_scratch_image_pin.py`, 17
      cases: the pin's shape, the conditional download, the verification as the task
      before `qemu-img create` on both paths, only read-only tasks before the
      architecture check; the check's real shell with `uname` faked, and the
      verification's with the real `sha256sum` on synthetic bytes. Red: all 17 failed
      against `HEAD`, meaningfully the `current` URL and the missing verification. Two
      mutations each caught by one case. The task files' Ansible parse is in the
      repository since 14.8.
- [x] 12.3 Verification.

      The IaC suite 82 passed; the VM adapter 262; `make check-packaging`. The role ships
      in the provisioning image's copy of the IaC tree, not in a wheel, so no version
      moved. A real download and a guest booted from the pin are the live VM lane's.

## 13. A VM teardown removes only its own guest

D9, for "A VM teardown removes only what its guest created", before any real guest is
created on a lane's host.

- [x] 13.1 Every firewall and NAT rule a create adds carries a comment naming the guest;
      cleanup removes by that exact comment, unmarked rules by the guest's `/32` address,
      never the subnet masquerade.

      Done, as `design.md` D9's "As built" records: the marker in `vars/main.yml`, the
      library `roles/vm-management/files/guest_teardown.sh` used by every teardown path,
      the exact-specification deletion, and the relay proxy block removed by its exact
      lines, fixing a prefix match found on the way.
- [x] 13.2 `vm_remove` with no cleanup script removes what it finds by the guest's name,
      reports the guest absent only when it finds nothing, and fails naming an artifact it
      cannot attribute.

      Done in `vm-remove.yml`: the branch's reads, refusal, removals (domain with storage
      and NVRAM, images, proxy block, reservations, rules, keys, cloud-init directories),
      and its `GUEST_PRESENT` report; `vm_remove_data` gains `cleanup_record` and
      `guest_present`, which the mock prints too (booleans since 14.10).
- [x] 13.3 Tests: behaviour through `shell_harness`, role structure, and the syntax check.

      Done (unit). New `tests/host_fakes.py`, stateful fakes of `iptables -S`/`-D`,
      `virsh`, `ufw`, `curl`, `systemctl`, and `firewall-cmd`, and
      `tests/test_guest_teardown.py`, 21 cases, with two guests sharing a name, address,
      and port prefix: the whole cleanup script removes exactly guest A's effects and fails
      before reporting when a `-D` is refused; the missing-script branch's eight cases,
      including the unattributable rule failing with no `-D`; `vm_undefine`'s port and
      rules; the relay harness's prefix-sharing neighbour; and the role's structure. Red:
      20 new cases against `HEAD`, meaningfully the neighbour's deleted proxy block; and,
      outside the repository, `HEAD`'s cleanup on real iptables 1.8.7 in an unprivileged
      namespace deleted the neighbour's masquerade and FORWARD rules, where the library
      deleted exactly the guest's five. Mutations comparing an address or the marker as
      a prefix fail 5 and 8 cases. `vm-remove.yml` also ran through `include_role` on
      ansible-core 2.17.14 and 2.19.14 against fakes, outside the repository; the
      in-repository parse of these files came with 14.8.
- [x] 13.4 Verification.

      The IaC suite 104 passed; the VM adapter 263; the service's five mock-consumer
      modules 95; `make check-packaging`. No version moved. On the relay path a create
      adds no rule, so the live lane's teardown exercises the proxy block, reservation,
      domain, and storage.

## 14. A GPU guest's boot-GPU detection and opt-in, readiness wait, and autostart

D12 and D13, for "A host's boot GPU is passed through only by an operator's opt-in" and
"A GPU guest's readiness wait and autostart are set by its pool's operator".

- [x] 14.1 Boot-GPU detection reads each candidate's own sysfs `boot_vga` flag, and every
      task that excludes or refuses the boot GPU uses that one test.

      Done, as `design.md` D12's "As built" records, in the new
      `roles/vm-management/files/gpu_eligibility.sh`, used by all seven GPU-choosing
      tasks. That is wider than the single selector planned: the retry alternatives and
      the multi-GPU selection had excluded no boot GPU at all, and the delta names all
      three ways with a retry scenario. The attachment scan's guest-side-address defect
      was fixed on the way.
- [x] 14.2 The opt-in, `vm_passthrough_boot_gpu`, false when absent; with it, the boot GPU
      is eligible only when listed available, bound to `vfio-pci`, and unattached. Nothing
      binds or unbinds a device.

      Done: the default in the new `defaults/main.yml`; each exclusion named on stderr;
      `NO_AVAILABLE_GPU` stopping the create before any domain; unreadable guests failing
      the selection.
- [x] 14.3 The readiness wait reads `vm_setup_wait_attempts` and
      `vm_setup_wait_interval_seconds`, defaulting to 10 and 30, refusing a non-positive
      or non-integer value before any host effect, and failing on exhaustion naming the
      bound.

      Done, with the type checks in `prerequisites.yml` (`design.md`, D13, "As built").
- [x] 14.4 The autostart task runs only when `vm_autostart`, true when absent, is true.

      Done: its condition reads `vm_autostart | bool`.
- [x] 14.5 Tests: detection and selection through `shell_harness`, role structure, the
      settings' source in the VM adapter, and the syntax check.

      Done (unit). `domains/vms/provisioning/iac/tests/test_gpu_eligibility.py`, 22 cases,
      over `host_fakes.FakeGpuHost`, a temporary sysfs tree with `boot_vga` and driver
      links, an `lspci -D -vmm` printing `Slot:` before `Class:`, and a `virsh` with
      separate source and guest-side addresses: the single selector, the three
      alternatives, the retry count, multi-GPU, and the readiness wait with `ssh` and
      `sleep` faked; and the role's structure. The library's one sysfs path is rewritten
      to the temporary tree, so no production variable exists for testing.
      `domains/vms/provisioning/adapter/tests/unit/test_gpu_guest_settings.py`, 7 cases:
      no requirement field or job variable names a setting, a request naming one is
      refused, and a pool's `extra_vars` reach the rendered extra variables with their
      types. Red: 13 cases against `HEAD`, decisively its selector choosing the boot GPU
      with no opt-in, all three alternatives falling back to it, and a guest-side address
      taken as attached. Mutations removing the opt-in, driver, or attachment check fail
      5, 2, and 2 cases. The type checks and the real selector task ran on ansible-core
      2.17.14 and 2.19.14 outside the repository; the in-repository parse came with 14.8,
      and first failed at a comment this section added.
- [x] 14.6 Verification.

      The IaC suite 126 passed and 2 subtests; the VM adapter 270; `make check-packaging`.
      No version moved. Round 2's candidate froze at this commit; the live VM lane owed
      a guest from the pinned image, a boot GPU passed through with the opt-in,
      readiness within the pool's bound, `vm_autostart` false honoured, a teardown
      removing only the guest's artifacts, and the GPU back on its host driver.

**Merge of `dev` after Section 14.** Round 2's frozen candidate had passed its full local
run and pipeline and been reviewed when `dev` advanced, bringing in
`gpu-optional-compute-shapes`. This branch merged `dev` at `1f157a17d` before any live run
(`design.md`, "Coordination with `gpu-optional-compute-shapes`").

- [x] 14.7 Merge `dev` at `1f157a17d`, resolve each conflict so both sides hold, and
      reconcile what merged without one.

      Done. The runbook's and issue-discovery tool's host requests state `ssh` version 2
      and no `gpu_count`; the INI parser reads `public_port=` and ignores `gpus=` and
      `gpu_model=`; the service keeps `dev`'s exact client pin; `dev`'s new
      `test_listing_shapes.py` create rule drops its fixed output, which D1 would yield no
      evidence from. Every requirement the deltas modify was unchanged by `dev`. Four
      packages took the next minor above `dev`'s: the Ansible kit 0.6.0, the compute kit
      0.23.0, the service 0.21.0, and the VM storefront 0.25.0. After `make dist-clean`
      and `make lock`: the Ansible kit 134, the compute kit 281, the fulfillment kit 200,
      the bare-metal adapter 88, the VM adapter 272, the service 607 unit and 480
      integration, e2e unit 208, the VM storefront 1198 unit and 501 integration; packaging
      passed.

**Corrections after the Round 2 implementation review** (`reviews/06-implementation-external.md`).
The supervising session accepted F1–F4 under the owner's delegated judgement, and added
S1. Each is fixed on top of the merge.

- [x] 14.8 F1: a checked-in parse-only playbook statically imports the `vm-management`
      role's task files, and `make validate-playbooks` syntax-checks it.

      Done: `domains/vms/provisioning/iac/ansible/playbooks/single-tenant/vm-management-task-files.yaml`,
      and a structure test. It found three unloadable tasks, reworded (`design.md`,
      beside S3). `validate-playbooks` passed on ansible-core 2.17.14 and 2.19.14 after
      the rewording, exit 2 before it.
- [x] 14.9 F2: D10's sixth condition lists the site's held states without the retired
      `provisioning`, naming `HELD_RESERVATION_STATES`.

      Done in `design.md`.
- [x] 14.10 F3: the diagnostic fields this change added to the mocks print as JSON
      booleans.

      Done for `account_present`, `cleanup_record`, and `guest_present`; the bare-metal
      adapter 88, the VM adapter 272, and the service's mock consumers 103 passed.
      `account_locked` and `account_deleted` followed in 14.38.
- [x] 14.11 F4: `e2e-tests/tests/e2e/roles/README.md` describes `e2e_bare_metal_deal` in
      one paragraph.

      Done.
- [x] 14.12 S1: the provisioning service's `Dockerfile.dockerignore` leaves out what a
      checkout holds locally under the IaC trees it admits whole.

      Done (`design.md`, S1). An emulation of Docker's matching found no tracked file's
      inclusion changed, and every untracked file under the trees excluded. The Terraform
      patterns followed in 14.39.
- [x] 14.13 Verification of 14.8 to 14.12.

      The suites named above; `make check-packaging`; the change checks.
- [x] 14.14 S2: `vm-check.yml`'s "Get total GPU count" loads, and the parse-only playbook
      imports it.

      Done, accepted under the owner's delegated judgement (`design.md`, beside S3).
      Ansible's own splitter over every free-form `shell` and `command` string of both
      IaC trees now finds no failure.
- [x] 14.15 S3: `vm-create.yml`'s "Wait for this VM's proxy to come up" accepts the
      tunnel client's status as the client sends it.

      Done, accepted under the owner's delegated judgement (`design.md`, "The x86-64 GPU
      guest"). `tests/test_frp_proxy_wait.py`, integration: seven tests running the
      shipped task through a real `ansible-playbook` against a loopback HTTP peer, for the
      ready, not-ready, retried, and refused bodies. Red on the old task: the two
      plain-text ready cases and three non-document cases failed on ansible-core 2.17.14
      and 2.19.14; green 7 passed on each.
- [x] 14.16 S4: `tests/test_frp_proxy_wait.py` names the callback it reads, and is skipped,
      saying so, when the Ansible it would run cannot load it.

      Done (`design.md`, beside S3); it now requires `ansible.posix.json`, checks it with
      the same installation's `ansible-doc`, and strips the caller's Ansible settings but
      for the collection paths. Red: a `ValueError` with no collection; green 7 passed
      with it, and skipped by name without it.
- [x] 14.17 S5: the bare-metal storefront sends each registry the bearer token
      `[registry.auth]` names for it, beside its signature, on publication and on its
      status read.

      Done (`design.md`, S5), accepted as necessary preflight under the owner's delegated
      judgement. Unit: the loader and composition, a token by its normalized URL, a token
      for no registry or one registry twice refused naming the URL and never the token.
      Integration of the clients against loopback registries: `Bearer <token>` to the
      gated one, none to the other, both signed. Red: 11 of 16 failed on `31d2e35ec`'s
      source. The values schema refuses the token publicly. `arkhai-bare-metal-storefront`
      0.25.0; the storefront suite 534 passed; the chart's render tests passed.
- [x] 14.18 S5's focused review: its F1 and F2, accepted by the supervising session under
      the owner's delegated judgement, with no further review round.

      Done: the `storefront-publication` delta's scenario "A bare-metal registry pin or
      token names no configured registry", with an application startup test for the pin
      case; status's token lookup through `lookup_registry_auth`, which a key spelled
      `HTTP://Registry-Gated/` proves.

**Integration of `prove-real-vm-provisioning` after 14.18.** Merged twice before any live
run (`design.md`, "Coordination with `prove-real-vm-provisioning`").

- [x] 14.19 Record the merges, what they brought, and what stays each change's.

      Done: `e9200603f` at that change's Section 5, and `c96e3828c` at its round-1 triage
      head. Its Sections 6–9, its GPU-less lane, and its deltas stay its own; this
      change's acceptance is unchanged. The full local validation, pipeline run
      40974364531, and the owned Helm validation passed on `c96e3828c`.
- [x] 14.20 S6: the e2e image carries the system SSH client `e2e_bare_metal_deal` runs.

      Done (`design.md`, S6), accepted under the owner's delegated authority to complete
      the live prerequisites: `e2e-tests/Dockerfile`'s runtime stage installs
      `openssh-client`. On the image built from `afa48148c`, `ssh -V` exits 0 and `ssh`,
      `timeout`, and `market` are on its `PATH`, its copied modules and installed buyers
      equal the source, and pipeline run 41126589665 and the owned Helm validation
      passed. No pipeline lane runs that SSH.

**The payments mandate in the service's current wire (S7).** A test-mode preflight
approval was refused with `400 invalid_request`: the service's current `ApprovalRequest`
requires each part's own `authorities` and `maxHoldExtension` and refuses the
mandate-level `authorities` the kit sent (`design.md`, "S7: the payments mandate in the
service's current wire contract"). No transaction was created and no rental started.
Every change is in `kit/arkhai-payments` and the pins and locks of the projects that
install it.

- [x] 14.21 Regression first, at the mandate seam.

      Done (unit), `tests/test_wire_contract.py` and `tests/test_mandates.py`: the previous
      wire refused; the derived mandate equal to a literal current-wire `ApprovalRequest`
      written by hand from the published schema; one transaction ID on both sides; the
      buyer's check refusing an extend right, a hold extension, a notice, another
      partial period, and a `start`; stored previous-wire data refused, not upgraded.
      Red 12 of 13 on the previous contract; green 13.
- [x] 14.22 The contract and its provenance.

      Done: `schema/payments.schema.json` is the supplied extraction byte for byte
      (`5cf22707c0e5c1c1c3ffd398d0a1710e136e719eee841c39323eba837e0ea848`, 93
      definitions); `models.py` regenerated by `kit/arkhai-payments/scripts/generate_models.py`, with its two
      code consequences (`design.md`, S7); `schema/SOURCE.md` records the extraction, the
      `HttpUrl` defect, the vectors as the previous publication kept for framing, and the
      synthetic current-wire fixture; `kit/arkhai-payments/scripts/check_vectors.py` checks the vectors'
      framing over raw JSON and their refusal by the current models.
- [x] 14.23 Derivation and consumption, in the kit alone.

      Done: `mandates.py` derives the one `once` part with its own stop, reverse, and empty
      extend authorities and `maxHoldExtension` `P0D`; `require_bound_to` reads the
      reverse authorities from that part and refuses a stored mandate without exactly
      one; the fake client serves part `extensions`; the receipt fixture's tests reproduce
      the previous framing from raw bytes and sign and verify a current-wire receipt. The
      kit 106 passed (unit).
- [x] 14.24 Packaging.

      Done: `arkhai-kit-arkhai-payments` 0.4.0; dependants whose requirement changed took
      their own minor bump against `dev` (bare-metal buyer 0.7.0, API-credit buyer 0.8.0,
      storefront 0.18.0, domain 0.9.0, VM buyer 0.10.0). `make lock` under uv 0.12.19
      rewrote ten locks' internal entries only, and a second run changed nothing.
- [x] 14.25 Verification.

      Each from its refreshed lock: the kit's type check, vectors, generated models, and
      106 unit tests; the VM buyer 213, bare-metal buyer 17, API-credit buyer 35, domain
      41, service 79, storefront 248, bare-metal storefront 536, VM storefront 1198 unit
      and 501 integration; e2e unit 279; packaging, change, index, and hygiene checks. No
      pipeline lane configures a payments target, so none exercises the wire.

**The required nullable maximum hold extension (S7, continued).** Both part kinds'
`maxHoldExtension` is required and accepts `null`, which the generated models refused and
the kit's `exclude_none` dumps would have dropped (`design.md`, "S7, continued"). The kit
stays at 0.4.0, unreleased in this change.

- [x] 14.26 Regression first, then the fix, in `kit/arkhai-payments` alone.

      Done: `tests/test_required_nullable.py` (unit, synthetic mandates); generation from a
      normalized copy in which exactly `OncePart.maxHoldExtension` and
      `RatePart.maxHoldExtension` are `Duration` or null, after asserting each is required
      and published as expected, the vendored schema unchanged;
      `market_arkhai_payments.canonical.wire_json` replaces every `exclude_none` wire dump
      in the kit; `SOURCE.md` and the README record it and why
      `ConnectStatus.connectedAccount` is generated as published. Red: 7 of 17 failed with
      the previous models, 6 with an `exclude_none` serializer; green 17.
- [x] 14.27 Verification of 14.26.

      The kit 123 passed with its other gates; packaging; each consumer re-synced (VM
      buyer 213, bare-metal buyer 17, API-credit buyer 35, domain 41, service 79, e2e unit
      279) and each storefront's payment-path modules (VM 53, bare metal 97, API credits
      23). The storefronts' whole suites stand from 14.25 on the unchanged non-null path.

**The S7 review's corrections** (`reviews/12-implementation-external.md`), in documentation
and one unit test.

- [x] 14.28 Corrections in `design.md` (S7), `kit/arkhai-payments/schema/SOURCE.md`, the
      kit's README, and `tests/test_required_nullable.py`.

      Done: the history claim narrowed, since an earlier previous-wire test purchase was
      found fully reversed and refunded by the supervising session's read-back, and every
      retained previous-wire payment is read back by its transaction ID before the first
      live qualification; the vector-update procedure also revises `check_vectors.py`'s
      refusals and the README; `wire_json` scoped to the kit, the storefronts'
      receipt-evidence dumps keeping `exclude_none` while no receipt property is
      required-nullable; an optional explicit `null` normalized away and refused when
      paired with the raw JSON's hash, pinned by one unit case. The kit 124 passed with
      its gates; packaging, change, and hygiene checks.

**The merge of `prove-real-vm-provisioning` through its Section 7C (S8).** The owner
directed that change's branch merged; this branch merged it at `cb05d625f` before either
live run (`design.md`, "S8: merging `prove-real-vm-provisioning` through its Section 7C").

- [x] 14.29 Resolve the merge so both changes hold, and record what came in.

      Done: the VM codec reads the relay block from the action's own fact and takes its
      port only from an enabled relay and only as a TCP port; both sides' relay tests
      kept, that change's executor tests naming their guest as `vm_target`; that
      change's driver split kept with the mock create gate stating no output; the host
      registry placeholder at `ssh` version 2; the real target's connection stated at
      version 2 and checked, with a unit test. No version, dependency, or lock moved.
- [x] 14.30 Verification of 14.29.

      The VM adapter 288; the IaC suite 155 and 15 subtests, with `validate-playbooks`
      and `validate-inventory`; the service 607 unit and 480 integration; e2e unit 340;
      `make check-packaging`. That change's GPU-less scenario is no evidence of this
      change's GPU lanes.

**A bare-metal purchase pays its option's exact total (S9).** A synthetic reproduction
showed `buy` scaling the lease's quantity twice, and the seller's exact-selection path
accepting the result (`design.md`, "S9"). Both packages are already above `dev`.

- [x] 14.31 Correct both ends, at their existing seams.

      Done: the buyer's `purchase_quote` quotes the option's one time-scaled `amount` rate
      over the duration, truncated once, refusing zero; `require_quoted_agreement` refuses
      another amount or duration; `buy` negotiates the quote as one unit, refusing zero
      before any request and checking the Agreement inside the negotiation and before
      approval; the seller accepts an exact selection of such an option, for a mechanism
      that settles from the Agreement alone, only at its total, refusing a different
      amount, a zero total, or more than one `amount` rate before keeping anything. Tests
      at both seams with 1800, 3600, 7200, and 1801 seconds. Red: the old buyer failed 7
      cases (3600 seconds, the masked case, passed); the old seller failed the under- and
      overcharge and zero-total cases. Deltas: `negotiation-protocol` and
      `buyer-orchestration`.
- [x] 14.32 Verification of 14.31.

      The bare-metal buyer 26; the bare-metal storefront 543; e2e unit 340; the VM
      storefront's nine bare-metal-wiring modules 289; packaging, change, index, and
      hygiene checks. No lane exercises a duration other than an hour, and none settles
      through payments in the pipeline.
- [x] 14.33 The S9 review's findings, under the owner's standing instruction to make the
      necessary repairs.

      Done: F1, the plan and deltas, resolved by 14.31–14.32; F2, an option with a rate on
      any field other than `amount` refused before negotiation; F3, a command-owned
      `AgreementOffQuote` ending the run once as `exited` with its reason and negotiation
      ID, exit 1, nothing approved. Red: the 6 run-end and 2 other-field cases. The buyer
      30, the storefront's selection tests 14, e2e unit 340; checks passed.

**A healthy pending poll is not spaced by failure backoff (S10).** A normal lease expiry
recorded `teardown_timeout` for a teardown that had succeeded in seconds, because the
convergence worker's poll spacing grew with every claim a row ever had (`design.md`,
"S10"). Both packages are already above `dev`.

- [x] 14.34 Regression first, then the fix, at the owning boundary.

      Done: `kit/fulfillment/src/market_fulfillment/settlement_repository.py`'s
      ownership-guarded `record_progress`; the convergence worker records progress on an
      applied outcome and on a pending read, which keeps its claim for the initial
      interval (`_poll_again`); exceptions keep the grown lease. Tests, synthetic, moving
      recorded instants rather than sleeping: integration in
      `test_fulfillment_convergence.py` (healthy pending polls, a still-pending operation,
      failed reads backing off then clearing, a taken claim untouched, a fresh phase);
      `provisioning/compute/service/tests/integration/test_ledger_lease_lifecycle.py`
      (under `tests/unit/services/` when these cases were added; 14.36 moved it) over one
      SQLite database with the real ledger, repository, lifecycle, and worker, a fast
      teardown after a long create released within the 300-second grace and a timed-out
      lease freed by `retry_release` with no new job; unit `record_progress` cases. Red:
      five convergence cases and the end-to-end case on `7b626c989`'s source. The
      `fulfillment` delta's convergence and recovery-lease paragraphs gain two scenarios.
- [x] 14.35 Verification of 14.34.

      The fulfillment kit 203; the service 609 unit and 486 integration; every project
      locking the kit (compute 281, Ansible 134, VM adapter 288, bare-metal adapter 88,
      e2e unit 340); packaging, change, index, and hygiene checks. The VM storefront,
      which calls none of the claim API, was not rerun.
- [x] 14.36 The S10 review's two findings, under the owner's standing instruction to make
      the necessary repairs.

      Done: F1, the real-database module moved byte for byte to `tests/integration/`, its
      own `session_factory` taking precedence, and the permanent evidence list
      re-citing it; F2, the delta and design saying the diagnostics' maximum attempt count
      is the longest current run of consecutive unproductive claims. The moved module 14
      passed; the service still collects 609 across both folders; checks passed; the
      sources, locks, and wheels unchanged. Correction (14.37): the plan's other citations
      of the module name its current path.

**The pre-closeout review's record findings** (`reviews/17-pre-closeout-external.md`). The
supervising session directed all three fixed before closeout.

- [x] 14.37 Reconcile the change's records with its review history.

      Done: F1, the Round 2 implementation review and its later amendments (`06`–`16`) and
      the pre-closeout review saved verbatim in the untracked `reviews/`, each triaged from
      the dispositions these notes record as a current reconciliation, with no owner reply
      or exit added; five minor findings then had no recorded disposition. F2, S1's design
      entry, proposal line, promotion row, and 15.9 item. F3, the moved lease test cited at
      its current path. The intervention ledger gained no entry. Packaging, hygiene,
      change, and index checks passed with every source, lock, and wheel unchanged.
      Correction (14.41): the five open findings are fixed by 14.38 to 14.40, and their
      triages record it.

**The inherited minor findings (S11).** The supervising session accepted the five open
findings, under the owner's standing instruction to do the necessary work, to be fixed
rather than deferred (`design.md`, "S11"). No individual owner answer is recorded.

- [x] 14.38 `07` F2: the bare-metal mock's default reclaim prints `account_locked` and
      `account_deleted` as `False`.

      Done in `mock_output.py`, the default `remove_lease_key` policy neither locking nor
      deleting. Two unit tests read the default reclaim through `read_fact` and through
      the real executor and codec and assert booleans. Red: both failed on the text
      values; green: the adapter 90 passed. No version or lock moved.
- [x] 14.39 `07` F3: `provisioning/compute/service/Dockerfile.dockerignore` leaves out the
      VM IaC tree's Terraform patterns, and its comment claims only what it excludes.

      Done. A synthetic probe under Docker 29.9.2's BuildKit, in a scratch directory
      outside the checkout with placeholder operator files, exported a `COPY . /ctx` of
      the context: the HEAD file admitted all seven Terraform placeholders, the new one
      none, and both admitted every one of the 100 IaC files. No tracked Terraform file
      exists, so no image content changed and no leak is implied.
- [x] 14.40 `07` F1 / `08` F1 and `10` F2: a native Ansible gate, and `vm-setup`'s included
      task files parsed.

      Done:
      - `domains/vms/provisioning/iac/ansible/playbooks/host-kit/vm-setup-task-files.yaml`,
        parse-only and refusing first, imports all 13 task files the role reaches;
      - `domains/vms/provisioning/iac/scripts/validate_playbooks.sh` syntax-checks every playbook from one list, run by
        `make validate-playbooks`;
      - `domains/vms/provisioning/iac/scripts/native_ansible_gate.sh` runs it, then `tests/test_frp_proxy_wait.py`
        with `unittest`, failing on any skip or no test;
      - the root `make test-provisioning-iac-native` runs the gate in the built
        provisioning image, the IaC tree mounted read-only with no network;
      - `.github/workflows/e2e.yml`'s VM lane runs it as its own step;
      - structure tests hold the wrapper's imports and the one list.

      Red: an apostrophe injected into a scratch copy's `kvm-setup.yml` passed
      `vm-setup.yaml`'s syntax check and failed the wrapper's (exit 4); the gate failed
      with no collections (exit 4), without `ansible.posix` (exit 4), and without Ansible
      (exit 127), and its runner exited 1 where `unittest` reported `OK (skipped=7)`; the
      structure tests failed for a missing wrapper, a dropped import, and a missing list
      entry. No role file needed a change.
- [x] 14.41 Verification and records of 14.38 to 14.40.

      The bare-metal adapter 90; after `make dist`, only the adapter's wheel changed, its
      `mock_output.py` equal to the source; the service's six bare-metal-mock integration
      modules 96; the IaC suite 150 and 7 skipped, by design; the gate in an image built
      from `afa48148c`, ansible-core 2.19.14 and `ansible.posix` 1.5.4, 7 playbooks and 7
      tests, none skipped; packaging, hygiene, change, index, and architecture checks.
      Every role file, the service's playbooks, `ansible.cfg`, every Dockerfile, lock,
      `pyproject.toml`, and e2e file, and every `src/` file but the mock were
      byte-identical to `48b3e4129`. No fresh-context check ran, for want of a subagent.
      Correction (14.44): S11 is committed as `e957c418b`.

**The merge of `prove-real-vm-provisioning` as archived (S12).** Under the owner's standing
authorization for needed upstream integration, the supervising session merged that
change's final head, `72a49b6d45da89b26a0fe8c4e8975289f289398c`, at which it is archived
(`design.md`, "S12"). No individual owner answer is recorded. `dev`'s squash of the same
work has the identical tree; its ancestry is recorded by 14.44.

- [x] 14.42 Resolve the merge so both changes hold, and record what came in.

      Done. The one conflict, `docs/development/VALIDATION_RUNBOOK.md`, keeps that change's
      sections 21–26 whole and this change's version 2 on the local mock host request, and
      section 24 states the scenario's version 2 registration with `ssh_key_path` as
      `key_path`, as `real_compute_deal_driver.py` does. The inherited GCP sections now
      read the operator's own values from required variables, and their dev-chain wallet
      key is labelled a development key. What came in is e2e harness, unit tests,
      documentation, and specifications: no `src/` module, role, lock, or image input; the
      bare-metal real-host scenario imports none of the changed modules; the cursor's
      calls are within the storefront client and route. Against the six deltas, the
      merged permanent specifications hold no added title and every modified one, and the
      merge changed no requirement they modify. Change documents record S12. The root
      `Makefile`'s default `AR_PROJECT` was outside the merge's files.
- [x] 14.43 Verification of 14.42.

      e2e unit 352 passed; 263 scenario tests collected; packaging, hygiene, change, index,
      scoped citation, and architecture checks. Unscoped, `make check-doc-citations` reports
      the repository's existing debt, the merged tree's 10 exactly the archived head's;
      the one beyond this branch's earlier 9 is that change's runbook command copying the
      committed `config-real-vm-target.yml.example` profile to its git-ignored rendered
      name, kept as written.

**`dev`'s squashed ancestry.**

- [x] 14.44 Record what `2d9b23624` did.

      Done, from the repository: its parents are `ca35f2264`, the S12 merge, and
      `c7dd275c5`, `dev`'s squash; its tree equals `ca35f2264`'s (`5d81b488…`);
      `c7dd275c5`'s tree equals `72a49b6d4`'s (`b319840d…`), and its parent `182818a79`
      was already in this branch's history. So it brought no content and dropped none of
      `dev`'s. The design, the index row, and the triages of `07`, `08`, `10`, and `17` say
      so.

**The parse-only refusal under tag selection, and the gate's native list (S13).** Review
18 raised three findings; the supervising session accepted them under the owner's
standing instruction (`design.md`, "S13"). No individual owner answer is recorded.

- [x] 14.45 Review 18 F1: each parse-only playbook's refusal holds under any `--tags`
      selection.

      Done: both `Refuse to run` tasks tagged `always`, their comments naming
      `--skip-tags always` and `--start-at-task` as the bypasses that remain; the
      structure tests require an `always`-tagged first `fail`. Red: `--list-tasks`, which
      executes nothing, under `--tags kvm_config` and `--tags vm_create` listed imported
      `always` tasks and no refusal; the two wrapper tests failed. Green: a tag-selected
      run of each in the provisioning image, read-only and offline, executed only `Refuse
      to run`, failed with its message, exit 2, 0 ok, 0 changed.
- [x] 14.46 Review 18 F3: the native gate's list is held.

      Done: a structure test parses `NATIVE` from the gate's inline Python and holds it
      equal to every test module defining the `_ansible` guard. Each mutation in a scratch
      copy: an emptied list, an unlisted guarded module, and a listed unguarded one fail;
      added and listed passes.
- [x] 14.47 Verification of 14.44 to 14.46.

      The IaC suite 151 and 7 skipped, by design; the gate in an image built from
      `2d9b23624`, 7 playbooks and 7 tests, none skipped; packaging, hygiene, change,
      index, scoped citation, and architecture checks. Only the two parse-only playbooks,
      the structure test, and the records changed; every source, role, lock, image input,
      and wheel is byte-identical. No fresh-context check ran. Validation of `77ed7141b`
      followed: `reviews/05-validation.md`.

## 15. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only. A part that would need a code edit returns the
change to implementation.

- [x] 15.1 **Comment hygiene.** Run `make check-comment-hygiene`. Any finding, or a
      comment Sections 2–14 added that still describes history, returns the change
      to implementation.

      Done. `make check-comment-hygiene` passed. Every added line of the change's code,
      read against `dev`'s squash `c7dd275c5`, was searched for a change, task, review,
      round, or history phrasing. The four hits describe the present: two generator error
      messages for a publication that moves on, the vectors pinning a previous wire, and
      an ownership invariant. Nothing needs rewriting.

- [x] 15.2 **Import placement.** Confirm that every import Sections 2–14 added is at
      module level, or carries a verified reason to stay local.

      Done. The change adds no function-local import in production code. One test-module
      local import remains, `from tests.fake_site import FakeSite, capacity_runtime_over`
      in `domains/vms/storefront/tests/unit/test_failure_policy.py`'s compensation case.
      It mirrors the identical local import of the same names `dev` already has in that
      module's other release case, so the module keeps one convention, and reviews 06 and
      17 read it so. Moving both would be cleanup of pre-existing code, which this part
      excludes. Nothing returns to implementation.

- [x] 15.3 **Documentation compliance.** Re-check D1–D14 against `openspec/README.md`'s
      placement rules and `design.md`'s promotion record.

      Done. Each accepted decision has a home under `openspec/README.md`'s placement
      rules:
      - normative behaviour in the six deltas, which the archive writes;
      - rationale in the `physical-provisioning` and `fulfillment` companions;
      - the release table and convergence spacing in `ARCHITECTURE.md`;
      - testing conventions in `TESTING.md`, and packaging in `BUILD_AND_PACKAGING.md`;
      - operator configuration in `DEPLOYMENT_AND_CONFIG.md`, both quickstarts, the VM IaC
        README, and the runbook.

      D5, D8, S6, S8, and S12 need none, as the record says. The promoted text was checked
      against the code it names:
      - `compensable`, `TeardownRefused` and `compensation_refused`, and
        `PROVIDER_REPORTED_FAILURE`;
      - `record_progress`, `_poll_again`'s initial interval, and `HELD_RESERVATION_STATES`;
      - `pause_listing`, and the opening refusal in `_plan_opening`;
      - the scenario's role inputs, the gate's targets, and `validate-playbooks`'s script;
      - that no VM scenario arms its own create output.

- [x] 15.4 **Narrative compression.** Compress these task notes to final behaviour,
      material evidence, deferred work, and destinations.

      Done. Durable rationale moved into `design.md` first: D1's observed callback forms
      and VM limits, D2's mock limit, D3's migrated hosts, D4's as-built kit operation,
      foreground poll, and reclaim lookup, D9, D11, D12, D13, and D14's as-built details,
      S7's code consequences, and the parse-only playbook, S2, and S4 beside S3. Every
      completed note was then shortened to final behaviour, material evidence, deferrals,
      and destinations: `tasks.md` went from 4729 lines to about 1250, with every task ID
      and check state unchanged.

- [x] 15.5 **Roadmap currency**, in `docs/development/ROADMAP.md`:
      - Under "Goal 1 — Consolidate physical-resource authority in the provisioning
        service", the gap row "The real runner reports no structured
        terminal-failure evidence…" notes that successful results are read in
        either callback form. It stays open for failure classification.
      - Under "Payment qualification boundaries", record the gaps this change leaves
        open:
        - D6's exhausted teardown job;
        - where two lanes share a machine, D10's operational precondition, that a
          refresh or reopen under the same identity keeps a listing's pause;
        - D10's limits: successor listings are created unpaused, no permanent
          requirement states per-listing pause semantics, no test closes a paused
          listing by reconciliation and reopens it, and bare metal has no test of a
          paused listing refusing an opening;
        - the live lanes' state at closeout, as evidence or as named blockers;
        - S7's payments contract: current-wire producer vectors were not supplied
          with this schema snapshot; the kit retains the previous publication for
          canonical framing and uses an explicit SCM synthetic current-wire fixture.
      - "Goal 2 — Negotiate full compute capability, not GPU count alone" is
        unchanged by this change: D7 is withdrawn, and `gpu-optional-compute-shapes`,
        archived, delivered that scope.
      - Name the update in `design.md`'s promotion record.

      Done in `docs/development/ROADMAP.md`. Goal 1's real-runner row now says a
      successful result is read in either callback form and linked to its job, and stays
      open for failure classification. "Payment qualification boundaries" records:
      - the two qualified purchases, in public generic terms;
      - D6's exhausted teardown job;
      - D10's precondition and test gaps where two lanes share a machine;
      - S7's missing current-wire producer vectors.

      Goal 2 is unchanged.

- [x] 15.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md` to `in closeout`, with notes stating what is true
      at closeout. Confirm that no dependency line or `Depends on` entry names this
      change, since D7's were removed with its withdrawal. Run
      `make check-change-index`, and name the update in the promotion record.

      Done. This change's row is `in closeout`, with notes rewritten to the state at
      closeout; this drops the Round 2 sentence review 19 F1 named. No dependency line or
      `Depends on` entry names this change, and no other row changed.
      `make check-change-index` passed.

      Closeout triage, review 20 F2 (accepted by the supervising session under the
      owner's standing instruction): the preface sentence that still named this change
      as the owner of the tenant-address item now says this change delivered it, links
      the archive, and says a buyer's SSH endpoint is built from the registered host's
      tenant-facing address and port, each falling back to the connection's. The row
      stays `in closeout`; no other row, status, or dependency changed.
      `make check-change-index` passed.

- [x] 15.7 **Packaging.** Run `make check-packaging` and
      `make check-architecture-change CHANGE=repair-compute-purchase-recovery`. Run
      `make check-agent-skills` only if the change touched `.agents/`, `.claude/`, or
      `.codex/`; it is not planned to.

      Done. `make check-packaging` passed, the architecture rules included, and
      `make check-architecture-change CHANGE=repair-compute-purchase-recovery` reported no
      row owned. The change touched nothing under `.agents/`, `.claude/`, or `.codex/`, so
      `make check-agent-skills` is not owed.

- [x] 15.8 **End-to-end pipeline.** Record the pipeline run and its result:
      - the bare-metal lane's `e2e_bare_metal_mock_deal` and
        `e2e_bare_metal_payment_deal`;
      - the VM lane's `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_listing_shapes`,
        `e2e_buy`, and `e2e_non_erc20_settlement`, which read the shipped-form
        default.

      Record the live lanes' qualification separately, as live evidence or as named
      blockers, never as pipeline evidence (`design.md`, "Live qualification"):
      - the bare-metal lane, a whole GPU machine bought through the buyer commands,
        `e2e_bare_metal_deal` or its commands, a bounded GPU computation by the
        tenant, teardown to `released`, a fresh SSH refusal, and restored capacity;
      - the VM lane, a GPU guest on an x86-64 host from the pinned image, a bounded
        GPU computation inside the guest, the normal release, a fresh SSH refusal,
        the GPU back at the host's driver baseline, and restored capacity.

      The two run on separate hosts, in parallel; D10's conditions apply only to a
      lane sharing a machine.

      **Pipeline**, at the frozen implementation head `77ed7141b`, which closeout's
      documentation does not change (`reviews/05-validation.md`): run 41142248005 passed in
      all three jobs.

      | Lane | Result |
      |---|---|
      | VM | 145 passed, 485 deselected |
      | Bare metal | 65 passed, 3 skipped, 562 deselected |
      | API credits | 1 passed, 3 skipped, 626 deselected |

      The VM lane's native Ansible gate step syntax-checked 7 playbooks and ran 7 real
      Ansible tests, none skipped; that discharges 14.41's owed observation.
      `e2e_bare_metal_mock_deal` and the VM lane's `e2e_deal`, `e2e_deal_buyer_cli`,
      `e2e_listing_shapes`, `e2e_buy`, and `e2e_non_erc20_settlement` read the shipped-form
      defaults. `e2e_bare_metal_payment_deal` and the optional payment cases skipped
      because `PAYMENTS.SERVICE_URL` is not configured, and are no payment evidence.

      **Owned Helm validation, a composite of two attempts.**
      - **Attempt 1** passed its 14 served cases, but its image loader ran out of temporary
        disk exporting a finished image, and serving checks found older role images. Its
        serving result is not counted.
      - **Attempt 2.** The finished images were imported, and the unchanged passing build,
        environment, and render results were reused. A fresh deployment, readiness, the
        14 cases, and cleanup then passed, with all five served role image IDs matching
        the current builds.
      - No new full build in attempt 2 and no pass of the original transport wrapper are
        claimed.

      **Local validation.** It is aggregate, under the owner-approved exact-input reuse,
      not a new literal root `make test`. The built images' sources, installed buyers and
      payments kit, and copied playbooks matched the committed source.

      **Live qualification, separately and never as pipeline evidence.** Both lanes
      passed on runtime source `e2f0790f1`, built at `afa48148c`, as the supervising
      session observed them; they are not this session's runs. Each was one attributable
      rental, on its own host, in test mode, through the buyer commands as they ship:
      - **The whole bare-metal GPU machine:**
        - bought, recovered from its run log, and reached over pinned-key SSH;
        - checked by a bounded GPU computation with no CPU fallback;
        - torn down to `released`, then refused for the same key;
        - its full capacity restored and its test payment reconciled at the quoted
          amount;
        - under the `remove_lease_key` policy, which keeps the account.
      - **The GPU guest on an x86-64 host, from the pinned image:**
        - bought, recovered, reached over pinned-key SSH, and checked the same way;
        - released at its natural lease expiry with no operator retry, force, or
          backdating;
        - its owned artifacts, reservation, relay proxy, and firewall entries removed;
        - refused afterwards, and its full capacity restored;
        - followed by one controlled cold reboot that returned the host's GPU and display
          baseline.

      Funds a contract holds are recorded as held, not refunded. Earlier failed rentals
      stay historical. Since then only mock output, validation-only parse playbooks,
      build exclusions, harness, and documentation changed; every real buyer, runtime,
      role, and dependency input is byte-identical, so no new rental is owed. Raw
      operational evidence stays outside the repository.

- [x] 15.9 **Promotion**, per `design.md`'s promotion record:
      - `docs/development/ARCHITECTURE.md` "Release": the table's `failed` row splits
        into compensable and not.
      - `docs/development/ARCHITECTURE.md`, the paragraph on
        `FulfillmentConvergenceWatchdog`: backoff and jitter apply between consecutive
        failed attempts, and a healthy pending poll is spaced by the initial interval
        (S10).
      - `openspec/specs/physical-provisioning/architecture.md`:
        - "Durable jobs, transient workers": fact reading and linkage, and a
          bare-metal reclaim's diagnostic result, whose teardown the reclaim
          job's status decides;
        - "The host registry owns the connection": the tenant-facing port, and
          `ssh` served at version 2 alone, a stored version-1 host refused until it
          is submitted again;
        - "Proof-driven release": compensation, and the corrected `teardown_failed`
          requeue sentence, which says the requeue re-observes the same failed job
          and does not re-run it (D6).
      - `openspec/specs/fulfillment/architecture.md` "Durable persistence and
        recovery": the compensating teardown and its marker.
      - `docs/development/TESTING.md` "4. System Integration Tests (End-to-End)":
        mock output prints the shipped form for the job, and the VM scenarios use
        the default.
      - `docs/development/TESTING.md`, beside "Chart Render Tests", and
        `domains/vms/provisioning/iac/README.md` "Validation", whose list of syntax
        checks it extends: `make validate-playbooks` parses the `vm-management`
        role's task files, a capacity check's included, through the parse-only
        `vm-management-task-files.yaml`, since a syntax check does not follow
        `include_tasks`; it renders no Jinja and runs nothing (14.8, 14.14);
        and `tests/test_frp_proxy_wait.py`, an integration test, runs the relay
        proxy wait through a real `ansible-playbook` when ansible-core 2.17 to
        2.19 and the `ansible.posix` collection's `json` callback are installed,
        and is skipped otherwise, saying which is missing (14.15, 14.16).
      - `docs/development/DEPLOYMENT_AND_CONFIG.md` "Bare-metal role
        configuration": `[registry.auth]` in the Secret overlay, one token per
        configured registry URL, sent beside the signature on publication and
        status alike; and "Storefront startup and site trust", whose list of
        refusals gains a bare-metal registry pin or token naming no configured
        registry (14.17, 14.18). The `storefront-publication` requirement "A
        storefront that cannot publish refuses to start" is written by the
        archive.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md` "Definition documents", the
        host-inventory paragraph: `public_port=`; every `ssh` host connection,
        through the API or an inventory, at version 2; and a host stored at version
        1 moved forward by an update or an import.
      - `docs/bare-metal-seller-quickstart.md`:
        - "Define the selected site": the inventory example with `public_port=`, and
          the sentence on `public_host` rewritten to the buyer's endpoint the host
          record states, each field falling back to the connection's;
        - "Release-qualified deal evidence": the scenario's inputs, the pinned
          known-hosts file among them, `--run-id`, teardown to `released`, and
          revocation proven only by an authentication refusal.
      - `docs/seller-quickstart.md` "4. Prepare your KVM hosts": in step 2, that a
        VM guest's port is its forwarded or relay port, never the host's
        `public_port`; in step 3, the x86-64 host prerequisites.
      - `domains/vms/provisioning/iac/README.md`:
        - "Prerequisites": the x86-64 host prerequisites, how an operator moves the
          image pin, and the `vm-setup.yaml` warning;
        - "VM Management Operations (vm-management role)": the relay proxy wait,
          ready only for the exact proxy reported `running`, reading the client's
          status body whatever its label (14.15);
        - "VM Management Operations (vm-management role)": `vm_passthrough_boot_gpu`,
          `vm_setup_wait_attempts`, `vm_setup_wait_interval_seconds`, and
          `vm_autostart`, beside the passthrough variables.
      - `docs/development/VALIDATION_RUNBOOK.md`, a new generic section on running
        live lanes (D10):
        - lanes on separate machines run in parallel, with source, build, and
          environment changes serialized;
        - lanes sharing a machine run in sequence, under the freeze and the
          per-listing pause;
        - read-backs in the site's held states, `reserved`, `leased`, `releasing`,
          `release_failed`, and `unmanaged` (`HELD_RESERVATION_STATES`), naming
          neither retired state;
        - each member's full `available` mapping compared with its `capacity`
          mapping;
        - every accepted deal drained, with no refund taken as proof;
        - the precondition that a refresh or reopen under the same identity keeps
          the pause.
      - `docs/development/TESTING.md` "Payment Receipts in Tests": the published
        vectors pin the previous wire's framing; current-wire producer vectors were not
        supplied with this schema snapshot, so the kit uses an explicit SCM synthetic
        current-wire fixture (S7). The
        section's example reproduces the vector signature from the raw body, since the
        current models refuse that body; "Private Service Dependencies"' current
        example says the same of the kit's conformance.
      - `docs/development/BUILD_AND_PACKAGING.md` "Images", beside its rule that a
        Dockerfile with a deny-all ignore file admits `scripts/uv_project.py`
        explicitly: an ignore file beside a Dockerfile replaces the root's, so one
        that admits a tree whole states that tree's exclusions itself, an operator's
        credentials, keys, inventories, and variable files, and a checkout's logs,
        retry files, caches, and environments, and the VM IaC tree's Terraform
        variables and state (S1, 14.12; S11, 14.39).
      - `docs/development/TESTING.md`, beside "Chart Render Tests", and
        `domains/vms/provisioning/iac/README.md` "Validation": the parse-only
        `vm-setup-task-files.yaml`, each parse-only playbook refusing to run first
        under any `--tags` selection though not an explicit `--skip-tags always` or
        `--start-at-task`, and `make test-provisioning-iac-native`, which runs every
        playbook's syntax check and every test module that runs a shipped task
        through `ansible-playbook` with the built provisioning image's Ansible, fails
        on any skip, and runs in the VM end-to-end lane (S11, 14.40; S13, 14.45,
        14.46).
      - `openspec/specs/README.md`: no new capability or companion, so no edit.
        Confirm it.
      - Complete the promotion record.

      Done; each document describes the current system:
      - **`ARCHITECTURE.md`.** "Release": the `failed` row split into compensable and not,
        with the predicate, the refusal, and the marker. "Recovery workers": attempts
        spaced by consecutive unproductive claims, and a healthy pending poll held for
        the initial interval.
      - **`physical-provisioning/architecture.md`.** "Durable jobs, transient workers":
        fact reading and linkage, and the reclaim's diagnostic fact. "Proof-driven
        release": the requeue corrected per D6, and compensation with each domain's
        safe teardown. "The host registry owns the connection": the tenant-facing route
        and `ssh` at version 2 alone, with key preservation.
      - **`fulfillment/architecture.md`.** "Durable persistence and recovery": the
        claim's spacing, and the compensating edge and its marker.
      - **`TESTING.md`.** Mock output in the shipped form beside the mock-profile
        paragraph; a new "Ansible Syntax and Native Checks" section before "Chart Render
        Tests"; "Payment Receipts in Tests" and "Private Service Dependencies" corrected
        for the previous-wire vectors and the synthetic current-wire fixture.
      - **`DEPLOYMENT_AND_CONFIG.md`.** "Storefront startup and site trust"'s refusals;
        "Definition documents"' `public_port=` and `ssh` version 2; "Bare-metal role
        configuration"'s `[registry.auth]`.
      - **`docs/bare-metal-seller-quickstart.md`.** "Define the selected site" and
        "Release-qualified deal evidence".
      - **`docs/seller-quickstart.md`.** "4. Prepare your KVM hosts", steps 2 and 3.
      - **`domains/vms/provisioning/iac/README.md`.** "Prerequisites"; "Validation"; and a
        "GPU guests, readiness, and autostart" subsection, under "VM Management Operations
        (vm-management role)", holding the four settings and the relay wait.
      - **`VALIDATION_RUNBOOK.md`.** "27. Running Live Lanes".
      - **`BUILD_AND_PACKAGING.md`.** "Images": the Dockerfile-adjacent ignore rule.

      `openspec/specs/README.md` needs no edit: all six capabilities and their companions
      are indexed. The six `spec.md` files are written by the archive (15.11), since no
      delta was promoted by hand. The promotion record is complete. No destination
      overlapped `prove-real-vm-provisioning`'s own promotion.

- [x] 15.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=repair-compute-purchase-recovery`, then
      `openspec validate repair-compute-purchase-recovery --strict`.

      Done.
      - `make check-doc-citations CHANGE=repair-compute-purchase-recovery`: passed, after
        four short `scripts/` paths in these notes and one in `TESTING.md` were written
        in full.
      - `make check-change CHANGE=repair-compute-purchase-recovery`, which runs the
        pinned `openspec validate --strict`: passed.
      - Unscoped, the check reports the repository's existing 10, the same as on the
        merged head before closeout. The promoted documents add none.

      Closeout triage, review 20 F1 (accepted by the supervising session under the
      owner's standing instruction), in `docs/development/VALIDATION_RUNBOOK.md`:
      - "Running The Local Pass" replaces "Optional Local Automation", which pointed
        at a helper this repository does not ship. No inbound link named its anchor.
      - Every call to the operations repository's component validators keeps its
        arguments, working directory, and section. It names the script through
        `OPS_VALIDATORS`, which section 17 requires and checks once, rather than
        through a path that read as this repository's `scripts/`.
      - Sections 24 and 26 derive the rendered target's name,
        `config-real-vm-target.yml`, from the committed example, in a subshell in the
        e2e config directory. The name and loading are unchanged.
      - Section 17's unset-variable messages carry no apostrophes. With one, the
        block failed `bash -n`, before this correction as after.

      Unscoped, the check now reports 3, each in another active change's `tasks.md`
      (`add-harness-scenario-contract`, `restore-issue-discovery-thin-runner`). The
      scoped check, `make check-change-index`, and `make check-change` passed.

      A further review 20 F1 correction to section 17's required directories, found by
      the supervising session's shell probe:
      - **The failure:** `export OPS_REPO="$(cd "${OPS_REPO:?…}" && pwd)"`, and the
        same form for `OPS_VALIDATORS`, did not stop. The check failed inside the
        command substitution, `export` returned 0, and the variable was exported empty.
      - **The fix:** a braced group now checks both variables in the calling shell,
        resolves each with `cd` and `pwd`, and exports it only through a second `:?`
        check. A missing or empty variable, or one that names no directory, stops the
        group with a message naming it.
      - **The proof:** isolated `env -i` runs of only that prefix exited nonzero in each
        failing case, without reaching the next command. Valid absolute, relative, and
        symlinked paths were exported resolved as before. `bash -n` passed on the block.

      Closeout triage, review 21 F1 (accepted by the supervising session under the
      owner's standing instruction): sections 24 and 26 now run
      `cd e2e-tests/config || exit 1` in their subshells. Run from the wrong directory,
      each subshell now exits 1 before its `cp` or `rm`, leaving a same-named file
      there untouched. From the repository root, the copy is still the shipped
      template under `config-real-vm-target.yml`, and the removal deletes only that
      file. Proven in temporary directories only.

- [x] 15.11 **Archival.** Run `openspec archive repair-compute-purchase-recovery -y`,
      which merges the `physical-provisioning`, `fulfillment`,
      `storefront-publication`, `settlement-servicing`, `negotiation-protocol`, and
      `buyer-orchestration` deltas into `openspec/specs/`. The deltas were not promoted by hand, so `--skip-specs` is
      not used.

      Done. Every delta was compared with the permanent spec it targets: none had been
      promoted by hand, no added title existed there, and every modified title did, so
      the archive merged without `--skip-specs`. `openspec archive
      repair-compute-purchase-recovery -y`, with the pinned validator (1.14.0), applied
      8 added and 10 modified requirements across the six capabilities. It moved the
      change, with its untracked `reviews/` and workflow log intact, to
      `openspec/changes/archive/2026-10-30-repair-compute-purchase-recovery/`. Each
      permanent spec's diff was read against its delta: the requirements that changed are
      exactly each delta's set, every merged body equals the delta's text, no title
      repeats, and nothing outside the requirements changed. The index row links the
      archive and stays `in closeout`. `make check-change` passed on the archived change.

      After the archive, S14 (`design.md`), accepted by the supervising session under
      the owner's standing instruction from an automatic pull-request review:
      - **The fix.** A VM teardown whose relay-client reload fails now fails and is
        retried until a reload succeeds, including after the proxy's block is gone. Made
        in `roles/vm-management/files/guest_teardown.sh` (`remove_guest_proxy` and its
        pending record), its two callers (the cleanup script in `vm-create.yml` and
        the missing-script branch in `vm-remove.yml`), and the permanent
        `physical-provisioning` requirement "A VM teardown removes only what its guest
        created".
      - **The tests,** in `domains/vms/provisioning/iac/tests`.
        - `test_guest_teardown.py` runs both teardown paths as their real shell against
          `host_fakes`, whose `curl` now takes queued exit statuses. A refused reload,
          and an unreachable client followed by a refused one, each fail, keep
          `guest-12`'s block, and succeed only on a reloading retry. Hosts with no VM
          tunnel client still need no reload.
        - `test_cleanup_script_relay_teardown.py` expects a failed reload to fail the
          cleanup.
      - **Red:** six of those failed before the fix, each because a failed reload
        exited 0.
      - **Green:**
        - the IaC suite: 158 passed, 7 native cases skipped there;
        - the native gate in the provisioning image: 7 playbooks syntax-checked and 7
          tests, none skipped;
        - the VM adapter's unit suite: 173 passed.
      - **Checks:** `make check-packaging`, `make check-architecture`,
        `make check-comment-hygiene`, and `make check-change` passed.

      Then S15 (`design.md`), accepted the same way, after the supervising session
      reproduced a refused `virsh undefine` the cleanup script reported as success:
      - **The fix.** The cleanup script in `vm-create.yml` now fails, keeping itself, on
        a refused destroy, undefine, DHCP removal, or key or image removal, and on a
        network or domain list it cannot read. An absent domain is skipped, and a
        retry removes storage and reservations left under the guest's name.
        `vm_undefine` removes the proxy through `remove_guest_proxy`, in one task
        without `ignore_errors`.
      - **The tests,** in `domains/vms/provisioning/iac/tests`. `host_fakes` gained
        one-shot refusals (`FakeHost.refuse`, and a refusing `rm`).
        `test_guest_teardown.py` covers each refused removal failing and its retry
        completing, an unreadable network, a refused domain listing, storage left
        without a domain, the missing-script branch's refused undefine, and
        `vm_undefine`'s failed reload followed by a reloading `vm_remove`.
      - **Red:** ten of them failed before the fix.
        - Seven cleanup-script cases exited 0 where the removal had not happened.
        - Three `vm_undefine` cases failed for want of the task.
        - The missing-script branch's refused-undefine case passed, since that
          branch already fails under `set -e`.
      - **Green:**
        - the IaC suite: 168 passed, 7 native cases skipped there;
        - the native gate: 7 playbooks syntax-checked and 7 tests, none skipped;
        - the VM adapter's unit suite: 173 passed.
