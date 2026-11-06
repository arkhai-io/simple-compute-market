# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/31-design.triage.md`. Every implementation task answers to a decision (D1–D10,
D12, D15–D22), a delta requirement under `specs/`, or a repository obligation cited at the
task: `openspec/README.md#plan-closeout-requirements`, the task rules in
`openspec/config.yaml`, `docs/development/TESTING.md`'s level definitions,
`docs/development/RELEASING.md`'s versioning policy, and `AGENTS.md`.

Test levels follow `docs/development/TESTING.md`: unit (including the e2e harness's
source checks, which read a scenario module without collecting it); library integration;
application integration (an in-process app through its typed client); and system (the
`e2e-tests` markers).

The sections follow D22's cadence. Sections 1–5 are the local and product round:
section 1 keys the shared post-settlement stages on the settlement reference (D15);
section 2 adds the buyer-purchase stage set and restructures the bare-metal payment
purchase onto it (D16, D4, D10); section 3 adds the VM lane's `market buy` purchase
(D17, D3); section 4 adds the real VM listing helper (D2); section 5 adds the host
diagnostics job (D5). Sections 6–7 are the external round: section 6 the target fields
and the admission-log reader (D9, D8), section 7 the three qualification modules (D1,
D3, D5, D6, D8, D9, D10). Section 8 is the closeout. Each section needs only the sections
before it. No dependency gates implementation: `add-mvp-payments-lane-double` is archived
(D20). D18 owes no task: the chart CA option and the kit's transport rule already serve a
deployment.

Return-to-design rules the design states, which a section's implementer applies rather
than working around: a buyer teardown that releases the lease outside `check_leases`
(D15); a reverse after the buyer's teardown refused (D16); a settlement wait that does not
resolve a payments deal by the settlement reference the design names (D15). Each stops the
section and returns the change to design; none is settled in a task.

Permanent specifications, `TESTING.md`, `ARCHITECTURE.md`, the runbook and the roadmap are
written at closeout; a section writes only the package and harness documentation its code
needs (the VM IaC README entry, the target example, `e2e-tests/README.md`'s marker list).

## 1. Shared post-settlement stages keyed on the settlement reference

Delivers D15: `09a`, `09b`, `09c`, `10a`, `10b`, `11a` and `11b` read the deal's
settlement reference and the handoff state D15's table names instead of
`real_escrow_uid` and `_evaluate_settle_host_id`, with every existing compute lane
unchanged in behaviour (test-compatibility delta, MODIFIED "The canonical compute deal's
shared stages are defined once", its shared-stage paragraph and input-independence rule).

Files: `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`; the stages' existing
writers and readers in `e2e-tests/tests/e2e/roles/scenarios/vms/{test_full_deal.py,
test_real_provisioning_deal.py, real_compute_deal_driver.py, compute_deal_driver.py}` and
`.../bare_metal/{test_bare_metal_mock_deal.py, test_real_provisioning_deal.py,
real_compute_deal_driver.py, compute_deal_driver.py}`; `e2e-tests/tests/unit/{test_compute_deal_stages.py,
stage_sources.py, test_real_vm_lane.py, test_real_bare_metal_lane.py}`.

- [ ] 1.1 The settlement reference (D15). `ComputeDealState` gains `settlement_ref`, the
  reference the shared stages from fulfillment onwards read: `Stage07_OnChainEscrow`
  writes it beside `real_escrow_uid` (the escrow), and section 2's purchase stages write
  the payments negotiation. `09b` waits on it (`wait_for_settlement`), `09c`, `09c2`,
  `10a` and the logs require and name it, and `11b` names its re-reservation
  `f"{settlement_ref}-reuse"`. The Alkahest-only stages (`07a`–`08b2`) keep reading
  `real_escrow_uid`. Unit, in `test_compute_deal_stages.py`: no stage from `09a` onwards
  requires or reads `real_escrow_uid`.
- [ ] 1.2 The expected host (D15's table). `_evaluate_settle_host_id` becomes
  `expected_host_id` for every writer and reader: `08a` writes it, `08c`, `09c`, the VM
  real module's previewed-host check (`test_real_provisioning_deal.py:443`) and the
  bare-metal real module's (`:273`) read it, and `test_real_vm_lane.py` and
  `test_real_bare_metal_lane.py` construct it. Unit: the renamed cases pass, and a
  source check finds no remaining `_evaluate_settle_host_id`.
- [ ] 1.3 The handoff is checked from source (delta: each shared input written
  independently of the lease under check). `test_compute_deal_stages.py` asserts, per
  lane row, that every state field a shared stage from `09a` onwards requires is written
  by an earlier stage of that lane — the table's `fulfillment_id`,
  `_create_job_completed`, `expected_host_id`, `teardown_fulfillment_id`,
  `_teardown_job_completed` and `settlement_ref` — and by no stage that reads the lease
  it is compared with. Unit: a lane row whose only writer of `expected_host_id` reads the
  lease fails the check (a constructed source in the test).
- [ ] 1.4 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_compute_deal_stages.py`, `test_real_vm_lane.py`, `test_real_bare_metal_lane.py`
  and the other stage-source suites. Run `make test` and `make check-comment-hygiene`.
  End-to-end: `e2e_deal` and `e2e_deal_buyer_cli` (VM lane) and `e2e_bare_metal_mock_deal`
  (bare-metal lane) run every re-keyed shared stage; `e2e_vm_real_provisioning` and
  `e2e_bare_metal_real_provisioning` run them too but are in no lane, so their unit
  suites are this section's evidence for the real lanes.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the re-keyed
  source checks.

## 2. The buyer-purchase stage set and the bare-metal lane purchase

Delivers the shared buyer-purchase stages (D1), with the payment-record and balance checks
(D4) and the bare-metal buyer-teardown ending (D15), and restructures
`test_bare_metal_payment_deal.py` onto them with its re-drive and refund as its own
stages, the buyer's teardown before the refund (D16, D10) (test-compatibility delta:
MODIFIED "A configured bare-metal payment purchase is qualified end to end"; MODIFIED
shared-stage requirement's scenario "A buyer purchase reaches fulfillment"; ADDED "A
compute buyer purchase settled through Arkhai payments runs in each compute lane", its
bare-metal scenarios, "A purchase is checked against its payment records" and "The
buyer's delivery-end filing reaches no authority").

Files: a new `e2e-tests/tests/e2e/roles/helpers/buyer_purchase_stages.py`; a bare-metal
purchase driver in `e2e-tests/tests/e2e/roles/scenarios/bare_metal/` (beside
`compute_deal_driver.py`); `.../bare_metal/test_bare_metal_payment_deal.py`;
`e2e-tests/tests/e2e/roles/helpers/payments.py` if the balance read needs a helper; a new
`e2e-tests/tests/unit/test_buyer_purchase_stages.py`; `e2e-tests/pyproject.toml`'s
`e2e_bare_metal_payment_deal` description.

- [ ] 2.1 The stage set (D1, D15's table). `buyer_purchase_stages.py` defines, like
  `compute_deal_stages.py`, the stages every scenario buying through the shipped buyer
  runs: hold the loops; discover through the purchase profile; buy through the domain's
  command (`market buy` or `market bare-metal buy`), the mock gates around it in a mock
  lane (`07a` armed before, `08b2` after dispatch); correlate the run's events (Agreement,
  settlement data bound to it, transaction, fulfillment); then the shared `09a`, `09b`,
  `09c` from `compute_deal_stages.py`. The purchase stages write `settlement_ref` (the
  negotiation), `fulfillment_id`, `expected_host_id` (the driver's declared host) and
  `seller_listing_id`. A per-domain purchase driver supplies the command, its arguments
  and the buyer's configuration; each stage logs the identifiers it reads (buyer run,
  Agreement, transaction, reservation, jobs). If `09b`'s settlement wait does not resolve
  the bare-metal payments deal by its negotiation, the section stops and the change
  returns to design (D15).
- [ ] 2.2 Payment records (D4). A stage checks each transaction: bound to its Agreement,
  its receipt over that mandate, its snapshot naming the configured payer and payee, its
  parts' gross equal to the Agreement's price for its duration. The balance sum check reads
  the payer's own balance through `PaymentsClient.get_balance` with the buyer's token
  before the first purchase and after the last approval, and asserts the drop in
  `available` equals the sum of the scenario's own transactions' debits, logging the
  dedicated-account precondition beside the result.
- [ ] 2.3 The buyer-teardown ending (D15, D16, D10). A shared stage runs
  `market bare-metal teardown --run-id <run>`, records `teardown_fulfillment_id` from the
  deal's fulfillment as delivery status reports it, and ends where `11b` starts; in a mock
  lane `09c2` arms the teardown gate before it and `11a2` drains after it. The delivery-end
  filing's `Unknown` outcome at the unanswerable authority neither fails the stage nor is
  read as delivery, access-end or refund evidence. If a buyer teardown releases the lease
  outside `check_leases`, the section stops and the change returns to design (D15).
- [ ] 2.4 The bare-metal lane purchase (D16). `test_bare_metal_payment_deal.py` runs, in
  order: the purchase stages and `09a`–`09c`; its re-drive of the run's commit (its own
  stage, as today); the shared buyer-teardown ending; the seller refund of the still-held
  payment (its own stage, the snapshot showing every part reversed); `11b`. Its
  compensating cleanup (`PurchaseCompensation`) and the mock rules' removal are unchanged.
  If the reverse after the teardown is refused, the section stops and the change returns
  to design (D16). The marker's description in `e2e-tests/pyproject.toml` says the buyer's
  CLI teardown precedes the refund.
- [ ] 2.5 The source check (D1; delta "defined once"). `test_buyer_purchase_stages.py`, on
  the pattern of `test_compute_deal_stages.py` and `stage_sources.py`: every scenario
  buying through the shipped buyer declares the purchase stages in order without replacing
  a body, inserts only its own stages between them, and runs the shared ending its lease
  ends by; the bare-metal lane purchase is one row. Unit: a constructed module replacing a
  shared body, or running the buyer-teardown ending and the expiry stages both, fails.
- [ ] 2.6 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_buyer_purchase_stages.py` and `test_compute_deal_stages.py`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_payment_deal` (bare-metal lane) runs the purchase stages,
  the shared post-settlement stages, the buyer-teardown ending and the refund after it.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the purchase
  source check.

## 3. The VM lane purchase through `market buy`

Delivers the VM lane's buyer purchase in `arkhai.payments.v1`, its own resource, host and
pool, ending by back-dating and a stepped watchdog cycle through the shared expiry stages
(D17, D3, D15) (test-compatibility delta ADDED "A compute buyer purchase settled through
Arkhai payments runs in each compute lane", scenario "A VM lane purchase completes").

Files: a VM purchase driver in `e2e-tests/tests/e2e/roles/scenarios/vms/` (beside
`compute_deal_driver.py`); a new `.../vms/test_vm_payment_purchase.py`;
`.../vms/host_registry.py` (its host and pool); `e2e-tests/pyproject.toml` (marker
`e2e_vm_payment_purchase`); `e2e-tests/Makefile` (`E2E_MODULE`);
`e2e-tests/tests/unit/test_buyer_purchase_stages.py` (its row); `e2e-tests/README.md`'s
marker list.

- [ ] 3.1 The VM purchase driver and module (D17). The module declares its own resource id,
  registers its host enabled and its pool in `host_registry.py` (as `E2E_PAYMENT_DEAL_HOST`
  and `E2E_PAYMENT_DEAL_POOL_ID` do), and creates its listing with an
  `arkhai.payments.v1` settlement through the seller client. It runs the purchase stages
  with `market buy`, the buyer CLI polling its settlement while the stages step
  convergence, as `test_full_deal_buyer_cli.py` does, then `09a`–`09c`, the payment-record
  and balance checks, `09c2`, `10a`, `10b`, `11a`, `11a2` and `11b`. It holds the loops for
  the whole module.
- [ ] 3.2 The expiry ending on a payments deal (D17). The back-dated lease, stepped with
  the watchdog held, tears the guest down and releases capacity while the pinned authority
  is unreachable; the module's `11b` asserts it. A stall caused by the unreachable
  authority is product behaviour the change does not alter, and stops the section for the
  owner rather than being worked around.
- [ ] 3.3 Lane membership. `e2e_vm_payment_purchase` is registered in
  `e2e-tests/pyproject.toml` and added to `E2E_MODULE`; `test_buyer_purchase_stages.py`
  gains the VM row; `e2e-tests/README.md` lists the marker.
- [ ] 3.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_payment_purchase` (VM lane) runs the purchase, the shared
  post-settlement stages and the expiry ending against the lane's payments double.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the VM row.

## 4. One listing offers every composed mechanism on a real resource

Delivers D2: one shared helper creates or adopts the real VM resource's listing, stating a
settlement for each mechanism the storefront reports ready, and adoption requires the
adopting module's own mechanism (test-compatibility delta ADDED "A real resource's listing
offers every composed mechanism").

Files: `e2e-tests/tests/e2e/roles/helpers/real_provisioning.py` (or a sibling helper
module); `e2e-tests/tests/e2e/roles/scenarios/vms/test_real_provisioning_deal.py` (its
listing stage, lines ~350–380); `e2e-tests/tests/unit/test_real_vm_lane.py`.

- [ ] 4.1 The helper (D2). Given the storefront's ready mechanisms, the target's resource
  and the module's own mechanism, it adopts the resource's existing listing when it offers
  that mechanism, fails naming the listing and its options when it does not (changing
  nothing), and otherwise creates the listing with one settlement per ready mechanism. The
  VM Alkahest real module's listing stage calls it. Bare metal needs no helper: its
  published options are the composed mechanisms (D2).
- [ ] 4.2 Unit, in `test_real_vm_lane.py`: creation states one settlement per ready
  mechanism; an Alkahest module and a payments module, in either order, adopt the same
  listing and create no second one; a listing lacking the adopting module's mechanism
  fails naming the listing and its options before any deal; a one-mechanism stack yields
  one option.
- [ ] 4.3 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_real_provisioning` runs the helper but is in no lane; no pipeline
  marker covers it, and none is owed, since a real resource exists only on a target.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the helper's
  cases.

## 5. The host diagnostics VM operator job

Delivers D5's host diagnostics: the `host-diagnostics` playbook task, the operator action
and route, the mock profile's default output, and the operator client's `diagnose_host`
submission with the typed `HostDiagnostics.from_job_result` parse (physical-provisioning
delta ADDED "A VM host's diagnostics are read through an operator job").

Files: `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/` (a new
`host-diagnostics.yml`, wired from `tasks/main.yml` and the
`playbooks/single-tenant/vm-operations.yaml` dispatch); `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/{codec.py,
bundle.py, controllers/vms_controller.py, services/host_operations_service.py,
services/mock_output.py}` and its request model; `domains/vms/provisioning/client/src/vm_provisioning_operator/{routes.py,
client.py, models.py, __init__.py}`; tests in
`provisioning/compute/service/tests/{unit/services/test_host_operations_service.py,
integration/test_hosts_api.py, integration/test_provisioning_client_endpoint_coverage.py,
unit/test_provisioning_client_contract.py}` and the adapter's own tests;
`domains/vms/provisioning/iac/scripts/validate_playbooks.sh` coverage if it enumerates
tasks; `domains/vms/provisioning/iac/README.md`; both packages' `pyproject.toml`; every
lock `make lock` rewrites.

- [ ] 5.1 The playbook task (D5). `host-diagnostics.yml` prints one fact for the action
  with boot ID, uptime, kernel, the count of running guests, and for
  `libvirtd.service`, `frpc-buyers.service` and the optional management unit: active
  state, invocation ID, main PID, restart count, active-enter time and result. The
  management unit arrives as a job parameter. The VM IaC README documents the action and
  its fact. Check: `make test-provisioning-iac` (syntax and the native gate's coverage).
- [ ] 5.2 The action (D5). A host-scoped action (`diagnose`), registered in `codec.py`'s
  result-fact and fact-action maps and `bundle.py`'s actions, submitted by
  `host_operations_service.py` beside `check` and routed by the controller. A
  `management_unit` not matching systemd's unit-name syntax is refused at submission, no
  job queued; an unknown host is the route's error. The mock profile's default output
  (`mock_output.py`) renders a fact from the job's parameters. Unit: the unit-name
  validation (valid names, a path, a space, an empty name). Application integration
  (`test_hosts_api.py`, through the typed client): a submitted job succeeds in the mock
  profile with a fact the parse accepts; an invalid unit is refused with no job queued.
- [ ] 5.3 The client (D5's interface). `diagnose_host(host_id, management_unit=None)` on
  `VmOperatorClient` and `SyncVmOperatorClient` returns the `JobSubmitResponse`, and the
  client gains no polling. `HostDiagnostics.from_job_result(result)` in
  `vm_provisioning_operator` returns the typed facts or raises a named error naming the
  missing or malformed field, returning no partial result. Unit: a well-formed result
  parsed; each missing field and a wrong-typed field refused naming it. The endpoint
  coverage and client contract tests include the new route.
- [ ] 5.4 Versions and locks (`docs/development/RELEASING.md`, "Versioning policy";
  `AGENTS.md`, "Package and dependency discipline"). Bump the adapter's and the client's
  versions once each against `dev`, raise any exact pin that moves, run
  `make check-uv-version` and `make lock`, and commit every lock it rewrites.
- [ ] 5.5 **Verification checkpoint.** Unit and application integration:
  `make test-provisioning`, `make test-provisioning-adapter`, `make test-provisioning-iac`.
  Run `make test`, `make check-packaging` (5.4 changes versions and locks) and
  `make check-comment-hygiene`.
  End-to-end: no pipeline marker runs the job; section 7's observation 2 module, in no
  lane, is its first system-level caller. None is owed in the pipeline.
  Owed by validation: `tests.yml`, jobs `test · test-provisioning`,
  `test · test-provisioning-adapter` and `test · test-provisioning-iac` — pass with the
  new action, client and playbook task.

## 6. Target fields and the admission-log reader

Delivers the target's optional `management_unit` on a VM host and `admission_log` on relay
access (D5, D9), the admission-log reader and its comparison with the relay's lease record
(D9), and the per-observation outcome the qualification modules record (D8)
(test-compatibility delta ADDED "The real-provisioning target names diagnostics and
admission inputs"; the qualification requirement's scenarios "Grant admission is read from
the plugin's log" and "A topology input is absent").

Files: `e2e-tests/src/e2e_harness/real_provisioning_target.py`; the target example
(`config-real-provisioning-target.yml.example`, under `e2e-tests/config/`); a new helper under
`e2e-tests/tests/e2e/roles/helpers/` for the admission log and observation outcomes;
`e2e-tests/tests/unit/test_real_provisioning_target.py` and a new unit test module for the
helper.

- [ ] 6.1 Target fields (D5, D9). `VmHost.management_unit: str | None`, checked against
  systemd's unit-name syntax; `RelayAccess.admission_log: str | None`, an absolute
  harness-local path validated as `CleanupOperator.key_path` is. Both join version 2
  without a bump; an older checkout refuses them by name as an unknown field. The target
  example shows both, commented as optional. Unit (`test_real_provisioning_target.py`): a
  valid unit and path accepted; an invalid unit and a relative or `..` path refused before
  any stage, naming the field.
- [ ] 6.2 The admission-log reader (D9). It reads the file's lines as the plugin's
  documented log contract (`tools/frp-grant-admission/README.md#the-log`) and, for one
  delivered lease, finds an `admit` line with `verified` true, `jti` equal to the
  reservation, `remote_port` equal to the lease record's `remote_port`, and `kid` equal to
  its `grant_key_id`, the record read through the relay's leases
  (`GET /api/v1/relays/{relay_id}/leases`). Unit: a matching line found; a line under the
  relay's newer active key but not the lease's recorded key refused; an earlier `admit`
  under a retired key ignored when the latest grant's line is present; a missing, unverified
  or mismatched line failing naming the lease.
- [ ] 6.3 Per-observation outcome (D8). Each qualification stage declares the observations
  that require it; at module end a hook logs each observation's outcome by D8's rule —
  made when every requiring stage passed, failed when one failed, unproven when none failed
  and one skipped, naming the skip's prerequisite — writing no file. Unit: observation 2
  recorded unproven naming `management_unit` when its diagnostics stage skipped and every
  other stage passed; observations 4 and 5 resolved independently in one module; a failure
  outranking a skip.
- [ ] 6.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: none; the fields and the reader are read by section 7's modules, in no
  lane. None is owed in the pipeline.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the target and
  helper cases.

## 7. The qualification modules

Delivers the three external-topology modules making observations 2, 4, 5 and 6 (D1, D3,
D5, D6, D8, D9, D10), each in no lane, blocked without the real-provisioning target and the
payments target (test-compatibility delta ADDED "An external-topology scenario extends a
locally verifiable scenario" and "Real-provisioning qualification scenarios make the owed
observations", every scenario of both).

Files: new modules under `e2e-tests/tests/e2e/roles/scenarios/vms/` (observation 2),
`.../bare_metal/` (observations 4 and 5), and one for observation 6 where both domains'
fixtures are reachable; their conftest fixtures; `e2e-tests/pyproject.toml` (markers
`e2e_vm_qualification`, `e2e_bare_metal_qualification`, `e2e_real_provisioning_reapply`);
`e2e-tests/tests/unit/test_buyer_purchase_stages.py` (their rows) and a unit module for
their wiring; `e2e-tests/README.md`'s marker list.

- [ ] 7.1 Observation 2 (D1, D3, D5, D9). Two CPU-only VM purchases through the shared
  purchase stages on the target's host, the listing through section 4's helper. A
  heartbeat over SSH on the first guest runs across the second guest's create and
  teardown and shows no gap over five seconds; host diagnostics (section 5) are read before,
  during and after, and the pass criterion is D5's (the management unit keeps one
  invocation ID, stays active and adds no restarts; libvirtd adds no restarts, has no
  failed result, and keeps one invocation ID across the reads taken while the first guest
  runs), a changed invocation or a grown restart count failing the module naming the unit;
  both leases end through `10a`/`10b` back-dating and stepped watchdog cycles. Without
  `management_unit` the diagnostics' management reads skip naming it.
- [ ] 7.2 Observations 4 and 5 (D1, D6, D10, D16's ending). The normal cycle through the
  purchase stages and the buyer-teardown ending, then the successor and refusal cycle in
  the same module, using the first cycle's consumed UID: the reclaim meets the planted
  foreign descendant, is queued for retry with its error recorded and a next retry time,
  its log names the descendant, the lease stays `releasing`, and after fixture-only repair
  the same job completes. The cycle reuses the cleanup-qualification fixtures
  (`working_data_qualification.py`, `working_data_probe.py`). No GPU is checked.
- [ ] 7.3 Observation 6 (D5's consumed-UID read). It reapplies both hosts' canonical
  registrations and runs a publication cycle; existing listings are adopted with
  identities, states and pauses intact, no duplicate host, pool, resource, allocator or
  listing appears, unexpired relay quarantine is retained, and the consumed-UID history,
  read through the working-data operator route's `policy` operation before and after, is
  unchanged. It needs both hosts and reports a blocked skip naming the missing one.
- [ ] 7.4 Common to the three (D1, D8, D9, D10). Each module is in no lane, reports a
  blocked skip and writes nothing to the stack without both targets, reads the runner's
  `PAYMENTS` section (D19), holds the loops for the whole module, and never waits out the
  wall clock for a state it can step to. Every relayed lease (observations 2, 4 and 5)
  runs section 6's admission check, skipping naming `admission_log` without it. Each stage
  logs the identifiers it reads and declares the observations requiring it, so the
  module's outcomes are D8's. The delivery-end filing's `Unknown` never fails a stage. No
  module funds the payer: a payer that cannot approve fails the purchase naming the payer
  (D1's topology rule).
- [ ] 7.5 Wiring checks. Unit: each module registered under its marker in no lane
  (absent from every `E2E_*_MODULE`); the observation 2 and observations 4 and 5 modules
  as rows of the purchase source check, extending the purchase stages without replacing a
  body; a module with no target configured reporting a blocked skip before any stage
  (with injected settings). `e2e-tests/README.md` lists the three markers and how an
  operator runs them through `test-module`.
- [ ] 7.6 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_qualification`, `e2e_bare_metal_qualification` and
  `e2e_real_provisioning_reapply` are in no lane; the deployment's operator runs them on
  the post-merge candidate (D7), and their sanitized findings are triaged as the owner's
  notes on that round. In the pipeline they collect and skip, which the unit wiring checks
  prove. The lanes' `e2e_vm_payment_purchase` and `e2e_bare_metal_payment_deal` exercise
  the shared stages these modules extend.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the wiring
  checks.

## 8. Closeout

The closeout task's eleven parts, in order (`openspec/README.md#plan-closeout-requirements`).
Closeout changes documentation only; a part needing a code edit returns the change to
implementation.

- [ ] 8.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read the
  comments sections 1–7 added against `AGENTS.md`'s "Python comments and docstrings". A
  finding returns the change to implementation.
- [ ] 8.2 **Import placement — confirm.** Every import sections 1–7 added is at module
  level, or local for a stated reason. One that should move returns the change to
  implementation.
- [ ] 8.3 **Documentation compliance.** Check D1–D10, D12 and D15–D22 against
  `openspec/README.md`'s placement rules: normative behaviour in the deltas, rationale in
  `openspec/specs/test-compatibility/architecture.md` and `TESTING.md`, nothing durable
  left only in `design.md`. D18, D20 and D22 have no permanent destination, as the proposal
  records.
- [ ] 8.4 **Narrative compression.** Compress section notes to final behaviour, material
  evidence, deferred work and destinations, moving any rationale into `design.md` first.
- [ ] 8.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1 (D12):
  - the row "Real provisioning is not yet qualified" names this change as owner, narrows
    to observations 1 and 3 as owed elsewhere, and closes only if observations 2, 4, 5 and
    6 are each made by D8's per-observation outcome; otherwise its prose states each
    outcome and its owner;
  - new unowned gaps: a paid purchase with checked GPU work for each GPU offer (D6); no
    pushed operator notification for a cleanup refusal or held teardown (D5); a
    payer-scoped debit listing at the payments service, as future work outside this
    repository (D4);
  - the row recording the real modules' first run stays unowned.
  Name the update in the promotion record.
- [ ] 8.6 **Campaign index currency.** In `openspec/changes/README.md`, set this change's
  row to `in closeout` with notes matching the outcome, and update its campaign's
  dependency lines (`qualify-arkhai-real-provisioning` and `add-mvp-payments-lane-double`,
  both archived) to what is true. Run `make check-change-index`. Name the update in the
  promotion record.
- [ ] 8.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=qualify-real-provisioning-by-scenario`; the change
  owns no architecture exception row.
- [ ] 8.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, and the scenarios exercising this change:
  `e2e_bare_metal_payment_deal`, `e2e_bare_metal_mock_deal` (bare-metal lane);
  `e2e_vm_payment_purchase`, `e2e_deal`, `e2e_deal_buyer_cli` (VM lane). Record the
  operator's run of `e2e_vm_qualification`, `e2e_bare_metal_qualification` and
  `e2e_real_provisioning_reapply` on the post-merge candidate (D7): each observation made,
  or failed or unproven with a named cause outside this change, as triaged from the
  owner's notes. An observation failed or unproven by the scenario itself returns the
  change to implementation (D7).
- [ ] 8.9 **Promotion.** Write, and record in the promotion record:
  - `docs/development/TESTING.md`, a new "#### Locally verifiable and external-topology
    scenarios" under "### 4. System Integration Tests (End-to-End)", before "#### The
    real-provisioning lane": the two kinds and their coverage, minimal extension, topology
    ownership, externally supplied and free-form evidence, the per-observation outcome,
    and stepping a lease's end as the application of "Tests wait on events, never on
    durations" (D1, D8, D21; principles 1–5);
  - `docs/development/TESTING.md`, "#### The canonical compute deal": the buyer-purchase
    stage set, the settlement reference and D15's handoff, the two lane purchases (D15,
    D16, D17);
  - `docs/development/TESTING.md`, "#### The real-provisioning lane": the shared listing,
    `management_unit`, `admission_log` and the qualification markers (D2, D5, D9);
  - `docs/development/ARCHITECTURE.md`, "Testing strategy": the repository-wide rule that
    an external-topology scenario minimally extends a locally verifiable one (D1);
  - `openspec/specs/test-compatibility/architecture.md`, "Ordinary Arkhai purchase
    evidence": the lane purchases, the qualification scenarios, the balance sum check and
    its dedicated-account precondition, and the pinned unanswerable authority (D4, D10);
  - `docs/development/VALIDATION_RUNBOOK.md` §25, "Run The Real-Provisioning Scenario":
    running the qualification markers on a candidate, after each storefront chart's
    `helm test` payments check (D7, D19);
  - `docs/development/VALIDATION_RUNBOOK.md` §29, "Observations the qualification owes":
    observation 2's leases end through the watchdog's expiry path (D3); observation 4
    drops its GPU clause (D6); observation 5's notification is the reclaim job's recorded
    error and scheduled retry (D5); the per-observation outcome (D8);
  - `openspec/specs/test-compatibility/spec.md` and
    `openspec/specs/physical-provisioning/spec.md`, written by the archive in 8.11.
  No new capability or companion, so `openspec/specs/README.md` is unchanged.
- [ ] 8.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=qualify-real-provisioning-by-scenario`, resolve every
  match, then `openspec validate qualify-real-provisioning-by-scenario --strict`.
- [ ] 8.11 **Archival.** `openspec archive qualify-real-provisioning-by-scenario -y`,
  merging the test-compatibility and physical-provisioning deltas; the change's row then
  links to its archive directory.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
