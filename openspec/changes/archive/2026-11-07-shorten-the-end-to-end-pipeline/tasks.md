# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/09-design.triage.md`. Every implementation task answers to a decision D1–D10, a
delta requirement under `specs/test-compatibility/`, or a repository obligation cited at
the task: `openspec/README.md#plan-closeout-requirements`, the task rules in
`openspec/config.yaml`, `docs/development/TESTING.md`'s level definitions, and
`AGENTS.md`.

Test levels follow `docs/development/TESTING.md`: unit (a function or the e2e harness's
own helper logic in isolation, `e2e-tests/tests/unit`); integration (a script against real
child interpreters it starts, the third flavour `TESTING.md` names beside in-process and
library tests); and system (the `e2e-tests` markers each pipeline lane selects, and the
pipeline's jobs).

Sections 1–2 deliver the gate (D1, D10, D2); sections 3–5 the scenarios (D7 with D6's
holds for the buy modules, then D6's remaining holds and its check, then D4, D5, D8).
Section 3 comes before 4 because the two buy modules cannot take the convergence hold
until their buys step convergence. Each section needs only the sections before it. D9
needs no implementation: the Mailpit wait is unchanged, and its permanent statement is the
new requirement the archive merges. D3 needs no implementation: its roadmap gap is written
at closeout (6.5). No dependency gates implementation. `apicredits-end-to-end-lane` edits
`test_credits_deal_buyer_cli.py` too; whichever lands second merges. Permanent documents —
`TESTING.md`, `ARCHITECTURE.md`, `ROADMAP.md` — are written at closeout; a section writes
only the comments and package documentation its own code needs.

Notes on completed tasks were compressed at closeout (6.4); what implementation settled
beyond the decisions is in `design.md`, "Implementation findings".

## 1. The native Ansible gate job

Delivers the gate as its own E2E job and takes it off the VM lane (D1, D10).

Files: `.github/workflows/e2e.yml`; the root `Makefile`.

- [x] 1.1 Add the root target `build-e2e-native-gate` (D10): `$(MAKE) init-prerequisites`,
  `$(MAKE) dist`, `$(MAKE) build-provisioning`, in that order, beside the
  `build-e2e-<lane>` targets, with a comment saying it builds only the provisioning image
  and the wheels it installs, wheels first because the pipeline runs on a fresh checkout,
  and no dev chain or test image. Add it to `.PHONY`, with a `##` help line.
  Verify: `make -n build-e2e-native-gate` prints the three steps in order and no
  `build-dev-env`, `build-test-image`, or other image build.
  Done. The dry run (`make build-e2e-native-gate -n`) prints `init-prerequisites`,
  `dist`, `build-provisioning` and no other image build.
- [x] 1.2 In `.github/workflows/e2e.yml` (D1, D10): add the job `native-ansible-gate`
  (`runs-on: ubuntu-latest`, `timeout-minutes: 30`) with steps checkout, `setup-uv`
  pinned as the lanes pin it, `make build-e2e-native-gate`, and
  `make test-provisioning-iac-native`; no foundry step and no artifact upload. Remove the
  `VM IaC native Ansible gate` step from `e2e-vm`. Rewrite the header comment: the
  `e2e-vm` entry stops naming the gate, and a new entry says the native Ansible gate runs
  as its own job beside the lanes, in the provisioning image it builds, composing no
  stack, failing rather than skipping when the image lacks its Ansible or callback, its
  output in the job log.
  Verify: the workflow parses as YAML (`python3 -c 'import yaml,sys;
  yaml.safe_load(open(sys.argv[1]))' .github/workflows/e2e.yml`); `e2e-vm` has no step
  running `test-provisioning-iac-native`; the new job's steps call only targets that exist
  (`make -n` of each).
  Done. `e2e-vm` has no gate step; both targets' dry runs resolve. The `python3 -c`
  parse was refused under the unattended step's rules; GitHub parsed the file when
  validation dispatched it (E2E run 42356524201).
- [x] 1.3 Verification point. Locally, where Docker is available:
  `make build-e2e-native-gate` builds `arkhai:compute-provisioning`, then
  `make test-provisioning-iac-native` passes against it. `scripts/change-workflow run
  pre-commit shorten-the-end-to-end-pipeline` passes.
  End-to-end: the pipeline run shows job `native-ansible-gate` passing; `e2e-vm` runs no
  gate step and passes its lane's markers; record each job's duration (the VM lane
  expected about 6.5 minutes, from 12).
  Done. Locally the target built the image and the gate passed against it. Pre-commit
  passed but for the citations check's three files sections 3–4 create, since created.
  Pipeline (E2E run 42356524201, validation 29): `native-ansible-gate` passed in 3m09s;
  `e2e-vm` ran no gate step, passed its markers, and took 4m31s, from 717 s. Outside the
  plan: the image-publication contract test, failing on the branch point, and the VM IaC
  README (`design.md`, "Implementation findings"). No `e2e-tests` marker exercises this
  section.

## 2. The compute gate runs its native tests concurrently

Delivers the compute family gate's one-process-per-test runner (D2).

Files: `provisioning/compute/iac/scripts/native_ansible_gate.sh`; a new
`provisioning/compute/iac/scripts/native_gate_runner.py`; a new
`provisioning/compute/iac/tests/test_native_gate_runner.py`;
`provisioning/compute/iac/README.md`.

- [x] 2.1 Write `provisioning/compute/iac/scripts/native_gate_runner.py`, standard library only (D2). Invoked as
  `native_gate_runner.py <tests dir> <module pattern>...`, it discovers the test ids of the
  named modules with `unittest.defaultTestLoader.discover(<dir>, pattern=<module>,
  top_level_dir=<dir>)`, as the gate does now, and runs each id in its own child
  interpreter (`sys.executable <runner> --child <id>`, cwd the tests dir), at most
  `os.cpu_count()` at a time from a `concurrent.futures.ThreadPoolExecutor`, with no
  worker-count override. The child runs its one test with a verbose `TextTestRunner` and
  ends its output with one JSON line: `{"id", "ran", "skipped", "failures", "errors"}`.
  When a child ends, the parent prints its whole captured output under a header naming
  the test id, its result, and its duration, then, after all, the summary
  `native gate: <n> run, <f> failed, <s> skipped`, and each skip's reason on stderr. Exit
  non-zero on any failure or error, any skip, a child that exits without its JSON line
  (reported as failed, naming the id and the child's exit status), or no test found.
  Its module docstring states the invariant: each test runs in its own interpreter so
  no test's cwd, environment, or umask reaches another, and each test's output is printed
  whole.
  Done as planned. Beyond the plan — an unimportable module and a pattern matching no
  test each fail the gate by name, and the summary ends with the wall time — see
  `design.md`, "Implementation findings" (D2).
- [x] 2.2 Integration tests, `tests/test_native_gate_runner.py`, running the real runner
  against planted `unittest` modules in a temporary directory (D2). Cases: every test
  passing exits 0 and the summary counts them; one failing test exits non-zero and its
  traceback appears inside its own header's block and no other's; a skipped test exits
  non-zero and names the test and reason; no matching test exits non-zero naming it; a
  child killed before its JSON line (a planted test calling `os._exit(3)`) is reported
  failed with its id and status; and the runner runs tests concurrently — two planted
  tests each create a marker file and wait, bounded, for the other's, so the pair passes
  only when both run at once (on a host with at least two CPUs; a single-CPU host skips
  this case with that reason). No case sleeps to pass.
  Verify: `make test-provisioning-iac` passes with the new cases.
  Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — the new
  `test_native_gate_runner.py` cases run and pass.
  Done. `make test-provisioning-iac`: 33 passed, 19 skipped (the native tests, with no
  supported Ansible on the host). The runner's nine cases, the planned six plus an
  unimportable module, a `setUpClass` skip, and output after the JSON line, all ran. The
  concurrency case polls the other's marker against a 60 s bound; with the runner forced
  to one worker it failed at the bound naming the test that never started. CI:
  `test · test-provisioning-iac` passed, 33 passed, 19 skipped (validation 29).
- [x] 2.3 Make `provisioning/compute/iac/scripts/native_ansible_gate.sh` call the runner (D2): keep its version
  prints and both syntax checks, then replace the inline heredoc with one call of the
  runner beside it, through `${PYTHON:-python3}` from the IaC directory the script
  already changes into, naming the `tests` directory and the four modules
  `test_frp_proxy_wait.py`, `test_frp_binary.py`, `test_reclaim_barriers.py`, and
  `test_admission_installer.py`. Leave the VM
  IaC gate (`domains/vms/provisioning/iac/scripts/native_ansible_gate.sh`) and the
  `test-provisioning-iac-native` target's three sequential `docker run`s as they are.
  Update `provisioning/compute/iac/README.md`'s native-gate lines to say the gate runs
  each native test in its own process, concurrently, and fails on a skip.
  Verify: locally, `make build-provisioning` then `make test-provisioning-iac-native`
  passes; the compute gate prints 19 test blocks and `native gate: 19 run, 0 failed, 0
  skipped`; record the compute gate's wall time (expected about 70–90 s on four CPUs,
  from 273 s).
  Done. Locally: 19 blocks, `native gate: 19 run, 0 failed, 0 skipped in 26.8s` on 28
  CPUs, against 131.9 s serially. Pipeline: 89.8 s on the runner's four CPUs.
- [x] 2.4 Verification point: 2.2's integration tests and 2.3's local gate run pass;
  `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` passes.
  End-to-end: the pipeline's `native-ansible-gate` job passes, its log shows the 19
  test blocks and the summary, and it finishes before `e2e-vm`; record its duration.
  Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — as 2.2 states.
  Done. Local evidence as 2.2 and 2.3; pre-commit as 1.3. Pipeline: the job passed, its
  log holding the 19 blocks and the summary, and ended at 08:44:22, before `e2e-vm`
  (08:45:44); 3m09s. The owed CI observation is 2.2's. The VM IaC gate keeps its own
  serial runner: `domains/vms/provisioning/iac/tests/test_ansible_structure.py` reads
  its inline Python. No `e2e-tests` marker exercises this section.

## 3. Buy scenarios step convergence

Delivers the background buy helper and the two buy modules holding their lane's timers
(D7; D6 for these two modules; requirement "Pipeline scenarios advance only by their own
steps", scenario "A buy reaches ready with convergence held").

Files: a new `e2e-tests/tests/e2e/roles/helpers/buy.py`;
`e2e-tests/tests/e2e/roles/scenarios/vms/test_buy_oneshot_buyer_cli.py`;
`e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`; a new
`e2e-tests/tests/unit/test_buy_helper.py`.

- [x] 3.1 Write `buy_to_ready` in `helpers/buy.py` (D7). Given the buyer CLI, the
  `market buy` arguments, the storefront admin client, the buyer-signed storefront client,
  the provisioning client, and the provisioning test client, it:
  1. starts `market buy` with `background=True`;
  2. waits for the run log's `escrow_created` and `settlement_submitted` events, bounded;
  3. waits for the storefront's `provision`/`job_submitted` stage event filtered by the
     buy's negotiation id (from its run log), bounded;
  4. reads the fulfillment id from the buyer-signed settle status for the escrow uid;
  5. drains the provisioning test client's job queue;
  6. advances convergence with `advance_fulfillment_to(..., "active")`;
  7. waits for `run_ended` with status `ready`, bounded, and returns the run and the
     terminal event.
  In a `finally`, a buy that has not ended is terminated and reaped through
  `MarketRun.terminate()`. A failure names the step it stalled at and includes the run
  log's reportable events, as `_run_log_digest` does today. It never pauses or resumes a
  service. Its docstring states why the buy runs in the background (with convergence
  held, a foreground buy would block until a convergence cycle no one steps) and cites
  `docs/development/TESTING.md`'s system-test discipline.
  Done. `buy_to_ready(buyer_cli, buy_args, *, storefront_admin_client,
  storefront_client, provisioning_client, provisioning_test_client)`, `buy_args` without
  `buy`. `run_log_digest` moved into the helper. A step's failure is an
  `AssertionError` naming the step, with the digest and, for an exited buy, its output
  tails. Outside the plan's file list, `MarketRun.terminate` (`roles/buyer_cli.py`) waits,
  bounded, after its kill. The negotiation-id source, the exit check, and the bounds:
  `design.md`, "Implementation findings" (D7).
- [x] 3.2 Unit tests, `tests/unit/test_buy_helper.py`, with a fake run and recording
  clients (D7): the success path calls start, the two run-log waits, the stage-event wait,
  the settle status read, the drain, the convergence advance, and the `run_ended` wait, in
  that order, and returns the terminal event; a missing `settlement_submitted` event, a
  failed advance, and a `run_ended` other than `ready` each raise naming the step and
  terminate the run once; a buy that ended is not terminated again.
  `test_scenario_holds.py` passes over the new helper module.
  Verify: `make test-e2e-unit` passes with the new cases.
  Done. The planned cases, plus one for a dispatch the storefront never logs, run the
  helper's real `advance_fulfillment_to` and `wait_for_stage_event` over fakes. Review 17
  F2 added `test_a_failed_buy_kills_and_reaps_a_process_that_ignores_sigterm`: a real
  child ignoring SIGTERM must end with SIGKILL's `returncode`, set only once reaped; it
  failed with the wait after the kill removed. `make -C e2e-tests test-unit`: 569
  passed. CI: `test · test-e2e-unit` named 6 `test_buy_helper.py` cases passed
  (validation 29).
- [x] 3.3 `test_buy_oneshot_buyer_cli` and `test_listing_shapes` take their lane's holds
  (D6) and buy through the helper (D7). Their `usefixtures` list first
  `storefront_loops_held`, `alice_loops_held`, `fulfillment_convergence_held`,
  `lease_watchdog_held`, then the lane's cleanup, as now. Stage B4 and stages 04a and 09e
  call `buy_to_ready`, keeping their existing assertions on the terminal event. The
  oneshot module's docstring stage map and comments stop describing a buy that completes
  on its own. Where a stage relies on the lease watchdog being held, it asserts it with
  `assert_lease_watchdog_held`, as the deal modules do; provisioning's system status
  reports no convergence hold to read back, and none is added here.
  Verify: `make test-e2e-unit` passes, including `test_scenario_holds.py` and
  `test_scenario_cleanup_order.py`.
  Done. Both modules list the four VM holds first, then their cleanup. B4, 04a and 09e
  call the helper and keep their terminal-event assertions. B4c, whose two dry runs must
  agree, asserts `assert_lease_watchdog_held` first; listing shapes has no such stage.
  The docstrings describe a job drained and convergence stepped. `make test-e2e-unit`
  passed.
- [x] 3.4 Verification point: `make test-e2e-unit` passes;
  `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` passes; where
  Docker is available, `make -C e2e-tests test-e2e-vm` with `E2E_MODULE="e2e_buy or
  e2e_listing_shapes"` passes.
  End-to-end: `e2e_buy` and `e2e_listing_shapes` pass in the VM lane, each buy's step
  log showing a convergence advance before `ready`; record the lane's scenario time.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — the new
  `test_buy_helper.py` cases and the hold checks pass.
  Done. Locally the VM lane over the two markers: 32 passed in 32.1 s, each of the three
  buys `ready` 4–7 s after it started, none waiting out convergence's 30 s timer; with
  convergence held only the helper's advance makes the fulfillment `active`. Pre-commit
  as 1.3. Pipeline: the VM lane passed (153 passed, 2 skipped, scenarios 102.83 s),
  logging the helper's three `[buy] … ready` lines. The owed CI observation is 3.2's.

## 4. Every lane-selected module holds its lane's timers

Delivers D6 across the remaining modules and its setup-plan check (requirement
"Scenarios hold shared services for the whole module", scenarios "A compute-lane module
omits a hold" and "A module no lane selects").

Files: the VM modules `test_full_deal.py`, `test_full_deal_buyer_cli.py`,
`test_vm_payment_deal.py`, `test_multi_registry.py`, `test_compute_dynamic_listings.py`,
`test_vm_introduction.py`, `test_non_erc20_settlement.py`; the bare-metal modules
`test_bare_metal_publication.py`, `test_bare_metal_introduction.py`,
`test_bare_metal_unbacked_introduction.py`; a new
`e2e-tests/tests/unit/test_scenario_lane_holds.py`.

- [x] 4.1 Add the missing holds, listed first in each module's `usefixtures`, before its
  cleanup (D6). VM lane: `test_full_deal`, `test_full_deal_buyer_cli`, and
  `test_vm_payment_deal` gain `alice_loops_held`; `test_multi_registry` gains
  `fulfillment_convergence_held` and `lease_watchdog_held`;
  `test_compute_dynamic_listings` and `test_vm_introduction` gain `alice_loops_held`,
  `fulfillment_convergence_held`, and `lease_watchdog_held`; `test_non_erc20_settlement`
  gains `alice_loops_held` and `lease_watchdog_held`. Bare-metal lane:
  `test_bare_metal_publication`, `test_bare_metal_introduction`, and
  `test_bare_metal_unbacked_introduction` gain `fulfillment_convergence_held` and
  `lease_watchdog_held`. Leave the modules no lane selects as they are
  (`vms/test_real_provisioning_deal.py`, `bare_metal/test_real_provisioning_deal.py`,
  `bare_metal/test_bare_metal_deal.py`, `vms/test_pool_declared_offering_modes.py`). For
  each module gaining convergence or watchdog holds, read its stages and cleanup and
  record in this task's note that none relies on a running convergence or watchdog (the
  design's risk); a module that does is a finding to raise, not a hold to drop.
  Verify: `make test-e2e-unit` passes, including `test_scenario_holds.py` and
  `test_scenario_cleanup_order.py`.
  Done. Holds added as listed (`test_vm_payment_deal` keeps `payments_config` ahead of
  them). None relies on a running convergence or watchdog: `test_non_erc20_settlement`
  steps its own convergence cycle and expires no lease; `test_multi_registry`,
  `test_compute_dynamic_listings` and `test_bare_metal_publication` settle nothing; the
  three introduction modules settle by introduction, which dispatches no fulfillment.
  The lanes' cleanup needs no provisioning timer. The hold fixtures' docstrings (both
  lane conftests, `helpers/compute_deal.py`) say the hold is the module's.
  `make test-e2e-unit` passed.
- [x] 4.2 Write the lane-hold check, `tests/unit/test_scenario_lane_holds.py` (D6). It
  reads `E2E_MODULE` and `E2E_BARE_METAL_MODULE` from `e2e-tests/Makefile`, joining
  backslash continuations, and runs `pytest --setup-plan -q -p no:cacheprovider -m
  <expression>` over each lane's directory (`tests/e2e/roles/scenarios/vms`,
  `.../bare_metal`), parsing the plan with `test_scenario_cleanup_order.module_plans`. It
  fails a module whose setup lacks any of its lane's holds — VM:
  `storefront_loops_held`, `alice_loops_held`, `fulfillment_convergence_held`,
  `lease_watchdog_held`; bare metal: the first, third, and fourth — naming the module and
  each missing hold. It fails when a lane variable cannot be read or a lane selects no
  module. Unit cases over planted inputs: a continued Makefile variable read whole; a
  planted plan missing one hold named by module and hold; a module outside the selection
  not required; an unreadable variable failing by name. The real-lane cases run over the
  actual lanes.
  Verify: `make test-e2e-unit` passes; temporarily removing one hold from one VM module
  makes the check fail naming that module and hold (then restore it).
  Done, amended by review 17 F1 (the owner chose the `scenarios/core/` exemption; D6
  amended): the check collects each lane's expression over pytest's configured test
  paths, as the lane's run does, and drops modules under `scenarios/core/`
  (`CHAIN_ONLY`). The delta gained the scenario "A lane selects a module outside its
  directory"; `scenarios/core/__init__.py` states the directory's chain-only meaning.
  Seven cases: the two real lanes, run as child pytest processes and kept in
  `tests/unit` beside `test_scenario_cleanup_order.py`; and planted inputs, including a
  temporary tree where marked modules in and outside the lane directory are held, a
  planted `core/` module and an unmarked one are not, and an empty selection yields no
  plan. Removing a hold from `test_vm_introduction.py`, then from
  `test_bare_metal_publication.py`, failed the check naming the module and hold;
  pointing `CHAIN_ONLY` elsewhere failed it naming the two `core` modules. The setup
  plan's `-p no:skipping` and the check's limits: `design.md`, "Implementation findings"
  (D6). Pre-commit on the round's fixes passed, citations included.
- [x] 4.3 Verification point: `make test-e2e-unit` passes;
  `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` passes.
  End-to-end: every marker the VM and bare-metal lanes select passes with the new holds:
  `e2e_vm_payment_deal`, `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
  `e2e_compute_dynamic_listings`, `e2e_alkahest_escrow_codecs`,
  `e2e_alkahest_trusted_oracle`, `e2e_listing_shapes`, `e2e_vm_introduction`,
  `e2e_non_erc20_settlement`; `e2e_bare_metal_publication`, `e2e_bare_metal_introduction`,
  `e2e_bare_metal_unbacked_introduction`, `e2e_bare_metal_mock_deal`,
  `e2e_bare_metal_payment_deal`.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — the lane-hold check runs
  over both lanes and passes.
  Done. Pre-commit passed. Locally the full VM lane: 153 passed, 2 skipped (the VM
  payment deal's dispute stages, which skip without a mediation target), 100.65 s; the
  full bare-metal lane: 70 passed, 50.48 s. Pipeline: VM 153 passed, 2 skipped;
  bare metal 69 passed, after 5.1 removed a stage. Correction to the list:
  `e2e_alkahest_escrow_codecs` and `e2e_alkahest_trusted_oracle` are `scenarios/core/`
  modules, exempt from the holds; they pass in the VM lane. CI: `test · test-e2e-unit`
  named 7 `test_scenario_lane_holds.py` cases passed (validation 29).

## 5. The remaining waits

Delivers the removal of the retention-sweep stage (D4), the API-credit lane's uncached
gate (D5), and the bare-metal payment scenario's single read (D8); requirement "Pipeline
scenarios advance only by their own steps", scenario "A behaviour depends on a window
passing".

Files: `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_introduction.py`;
`compose.apicredits-lane.yml`; `domains/apicredits/compose.yml` (comment only);
`e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py`;
`e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_payment_deal.py`.

- [x] 5.1 Remove `TestStage04_RetentionSweep` from `test_bare_metal_introduction.py`
  (D4), with `RETENTION`, `EXPIRY_DEADLINE_SECONDS`, `EXPIRY_POLL_SECONDS`, and any import
  left unused. Rewrite the module docstring's sweep sentence: the scenario ends with the
  operator's deletion, and the held sweep is proven by the storefronts' integration tests
  (`domains/bare_metal/storefront/tests/test_http_introductions.py`).
  Verify: the module defines stages 00–03 only and no loop polls a dry run;
  `make test-e2e-unit` passes.
  Done. Stages 00–03 only, no dry run called, no import left unused. The docstring names
  the integration test file, whose `test_held_retention_sweep_deletes_what_it_previewed`
  back-dates a reveal and steps the held sweep. The two-host scenario stays as it is
  (`design.md`, "Implementation findings", D4). `make test-e2e-unit` passed.
- [x] 5.2 Set `APICREDITS_MIDDLEWARE_VERIFY_TTL_SECONDS=0` on the sample app in
  `compose.apicredits-lane.yml` (D5), with a comment saying every request re-verifies so
  a top-up is visible to the next request, and the cache's own behaviour is proven by the
  middleware conformance trace. Correct the comment in `domains/apicredits/compose.yml`
  so it no longer says the e2e polls through the window. In
  `test_credits_deal_buyer_cli.py`, replace the post-top-up poll with one request
  expecting 200 and the forecast, keeping the final 200 and 402 assertions; drop the
  unused `time` import.
  Verify: `docker compose -f compose.apicredits.yml -f compose.apicredits-local.yml -f
  compose.payments-double.yml -f compose.apicredits-lane.yml config` (the lane's files as
  `E2E_APICREDITS_COMPOSE` in `e2e-tests/Makefile` names them) shows the sample app's TTL
  `0`; `make test-e2e-unit` passes; any lane-compose test
  (`scripts/tests/test_lane_compose.py`) still passes.
  Done. The overlay overrides the included `sample-app` service's environment; the
  scenario makes one request expecting 200 and the forecast, its message naming the
  setting. The plan's `docker compose … config` was refused under the step's rules; in
  its place `test_only_the_api_credit_lane_runs_the_sample_app_with_no_verify_cache`
  (`scripts/tests/test_lane_compose.py`) renders both stacks and pins the lane's `0` and
  the full stack's `3` (`design.md`, "Implementation findings", D5).
  `make test-release-tooling`: 2681 passed, none skipped; `make test-e2e-unit` passed.
- [x] 5.3 In `test_bare_metal_payment_deal.py` (D8), replace the status poll after
  `advance_fulfillment_to(..., "active")` with one `payment_fulfillment.status(...)` read
  asserting `state == "active"`, with a message saying the storefront reads provisioning's
  status live; drop the `time` import if unused.
  Verify: no loop remains between the advance and the delivery assertions;
  `make test-e2e-unit` passes.
  Done. One read after the advance, its message saying the storefront reads
  provisioning's status live; `time` is no longer imported. `make test-e2e-unit` passed.
- [x] 5.4 Verification point: `make test-e2e-unit` passes;
  `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` passes.
  End-to-end: `e2e_bare_metal_introduction` passes stages 00–03;
  `e2e_credits_deal` passes, its post-top-up request answering 200 at once;
  `e2e_bare_metal_payment_deal` passes, its status read answering `active` once.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes.
  Done. Pre-commit passed. Locally: the bare-metal lane 69 passed in 28.51 s, from 70 in
  50.48 s (4.3), with stages 00–03 and the single read; the API-credit lane 4 passed,
  the post-top-up request answering 200. Pipeline: bare metal 69 passed, including
  `test_bare_metal_introduction`'s stages 00–03 and
  `test_payment_deal_delivers_after_a_verified_receipt`; API credits 4 passed, including
  `test_credits_full_deal`. Three texts still describing the removed stage were
  corrected. CI: `test · test-e2e-unit` 569 passed (validation 29).
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — runs
  `scripts/tests` through `make test-release-tooling`; the new
  `test_only_the_api_credit_lane_runs_the_sample_app_with_no_verify_cache` runs, not
  skipped for want of Compose, and passes.
  Observed: 2681 passed with no skips reported (validation 29).
  Fix outside the plan, validation 24 V1 (the owner's option A): the audit test in
  `scripts/tests/test_check_secrets.py` draws `wordless_password()`, and
  `market-change-workflow`'s README, "Secret scanning", states the audit's limit
  (`design.md`, "Implementation findings"). The file's 31 tests passed against the real
  pinned gitleaks; pre-commit passed. The scenario "The audit reports what the gate
  passes" is unchanged.

## 6. Closeout

Confirm and promote the verified design, then archive last (D1–D10 and both delta
requirements). The eleven parts follow `openspec/README.md#plan-closeout-requirements` in
order. Closeout changes no code: a part needing a code, workflow, Compose, or test change
returns the change to implementation.

- [x] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every
  comment and docstring sections 1–5 added: the `e2e.yml` header and job, the
  `build-e2e-native-gate` comment, `native_gate_runner.py` and its tests, the gate
  script, `helpers/buy.py`, the lane-hold check, the scenario docstrings and messages
  touched, and the two Compose comments. Each states current behaviour, with no change,
  review, or migration wording. A needed correction returns to implementation.
  Done. `make check-comment-hygiene` passed: no change-ID, task-number, or change-name
  reference. Every comment and docstring in the diff from the branch point `a725e377a`
  was read; each states current behaviour, and none names a review, migration, or
  change.
- [x] 6.2 **Import placement — confirm.** Every import sections 1–5 added is at module
  level, or local with a recorded reason. One that should move returns to implementation.
  Done. Every Python import the diff adds is at module level. The indented `import`
  lines in `test_native_gate_runner.py` are the text of planted test modules, not
  imports of that file.
- [x] 6.3 **Documentation compliance.** Check D1–D10 and the principle against
  `openspec/README.md`'s placement table: testing methodology in `TESTING.md`, the
  normative hold and stepping rules in `test-compatibility`'s spec, the one-line
  principle in `ARCHITECTURE.md`, the gap in `ROADMAP.md`; nothing durable left only in
  this change.
  Done. Each decision's home follows the table, as the promotion record lists it. Against
  the code: `provisioning/compute/iac/README.md` and `domains/vms/provisioning/iac/README.md`
  already describe the gate as it runs. `test-compatibility/architecture.md`, "Current
  limits", said scenarios retain timing dependencies, no longer true of pipeline
  scenarios; corrected at 6.9. What implementation settled beyond the decisions is now
  in `design.md`, "Implementation findings".
- [x] 6.4 **Narrative compression.** Compress section notes to final behaviour, material
  validation evidence (gate and lane durations, the runs), unresolved or deferred work,
  and permanent destinations, moving any durable rationale into `design.md` first.
  Done. The notes of sections 1–5 now hold behaviour, evidence, and deferrals. Moved
  first to `design.md`, "Implementation findings": the runner's additions and timings
  (D2), the lane-hold check's `-p no:skipping` and limits and its parser coupling (D6),
  the buy helper's negotiation-id source, exit check, and reaping (D7), the TTL
  mechanics and why the render test pins the value (D5), the declined two-host
  simplification (D4), and the defects fixed outside the stated scope. Dropped as
  duplication: local re-run sequences, fresh-context check narratives, and per-run
  pre-commit target lists.
- [x] 6.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, "Goal 1 — Consolidate
  physical-resource authority in the provisioning service", add an open-gap row: no
  workflow runs the bare-metal cleanup native gate (`make test-bare-metal-iac-native`),
  so the bare-metal working-data helper's native account, filesystem, and IPC tests run
  only when someone runs them locally; owned by "Unowned — needs a new change" (D3).
  Record that no goal's current state otherwise changes.
  Done. The row is added, naming the gate's `SYS_ADMIN`, AppArmor-unconfined container
  as what has never run on a hosted runner. No goal's current state otherwise changes.
- [x] 6.6 **Campaign index currency.** In `openspec/changes/README.md`, update this
  change's row in "Lesser goal — End-to-end harness determinism" so its status and notes
  say what is true (status `in closeout`; archive cleanup writes `archived`), and note in
  `apicredits-end-to-end-lane`'s row that its loop holding adopts this change's hold rule
  for its lane (D6). Leave every `Depends on` for archive cleanup. Run
  `scripts/change-workflow check index`.
  Done. The row is `in closeout`, its notes giving the promotion and the pipeline's
  timings; its link moves to the archive at 6.11. `apicredits-end-to-end-lane`'s notes
  say its loop holding adopts the hold rule and that it edits the same scenario module.
  The campaign has no dependency graph, and no `Depends on` changed.
  `scripts/change-workflow check index` passed.
- [x] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=shorten-the-end-to-end-pipeline`. No `.agents/`,
  `.claude/`, or `.codex/` edit is planned; if one was made, run
  `make check-agent-skills`.
  Done. `scripts/change-workflow run pre-archive shorten-the-end-to-end-pipeline` at
  `56bcf7c46` passed: `make check-packaging` (locks, Python selection, layers, scope,
  dependencies, kinds) and `make check-architecture-change` ("owns no architecture
  row"). The change made no `.agents/`, `.claude/`, or `.codex/` edit.
- [x] 6.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, each job's duration, and the evidence for this change:
  the `native-ansible-gate` job passing with 19 compute test blocks; `e2e-vm` running no
  gate step; every VM and bare-metal lane marker passing with its lane's holds (4.3's
  list); `e2e_buy` and `e2e_listing_shapes` stepping convergence; `e2e_credits_deal`,
  `e2e_bare_metal_introduction`, and `e2e_bare_metal_payment_deal` passing without a
  timer or duration wait. A pipeline that cannot run for a reason outside this change is
  recorded as a blocker naming its cause and owner, with its validations unrun.
  Done. E2E run 42356524201 of `c5fd64ea5` (validation 29): success. Jobs, from the
  run's `actions.log`: `e2e-vm` 4m31s (153 passed, 2 skipped, scenarios 102.83 s, no
  gate step); `e2e-bare-metal` 3m20s (69 passed, 35.90 s); `e2e-apicredits` 2m53s (4
  passed, 10.59 s); `native-ansible-gate` 3m09s (19 compute test blocks, `native gate:
  19 run, 0 failed, 0 skipped in 89.8s`). The pipeline takes 4m31s, from about twelve
  minutes in run 42283244737. Every marker each lane selects passed with its holds; the
  VM log shows the helper's three `[buy] … ready` lines (`e2e_buy`, `e2e_listing_shapes`);
  the bare-metal log, `test_bare_metal_introduction`'s stages 00–03 and the payment deal
  passing; the API-credit log, `test_credits_full_deal` passing. CI: `tests.yml` run
  42356527018, all 18 jobs passed, with the owed observations of 2.2, 3.2, 4.3 and 5.4;
  no job failed, so `dev`'s baseline (run 42299053370 at `a725e377a`) was needed for no
  comparison. Both runs name `c5fd64ea5`, the commit the pre-closeout review read; the
  one commit after it, `56bcf7c46`, edits only the index, and closeout changes no code.
- [x] 6.9 **Promotion.** Write, and record in a `## Design promotion record` table in
  `design.md`:
  - `docs/development/TESTING.md`, "Ansible Syntax and Native Checks": the gate runs as
    the `native-ansible-gate` job beside the lanes, building its own provisioning image,
    replacing "The VM end-to-end lane runs this gate once it has built the image" (D1);
    the compute gate runs each native test in its own process, concurrently, each test's
    output whole (D2).
  - `TESTING.md`, "4. System Integration Tests (End-to-End)", the paragraph introducing
    the lanes: one sentence that the native Ansible gate is a pipeline job beside the
    lanes, not a lane (D1); the bare-metal lane's bullet: the introduction scenario ends
    with operator deletion, and the held retention sweep is proven at integration level
    (D4); the API-credit lane's bullet: the sample app runs with no verify cache, whose
    behaviour the conformance trace proves (D5).
  - `TESTING.md`, the hold rule ("A scenario that needs a shared service's timer held…"
    and the paragraph after it): every module a compute pipeline lane selects holds its
    lane's storefront loops, convergence, and watchdog, VM modules also Alice's
    storefront loops, checked by `e2e-tests/tests/unit/test_scenario_lane_holds.py` from
    each lane's marker selection (D6); buy scenarios run `market buy` in the background
    through `helpers/buy.py` and step convergence (D7).
  - `TESTING.md`, "The discipline every scenario follows": an end-to-end test proves a
    deterministic sequence of state changes — a sequence diagram run repeatably — never
    wall-clock time; a timer left running is an unscripted participant; a wait is
    legitimate only on a message the stage's own request caused (the principle; D9's
    rationale).
  - `docs/development/ARCHITECTURE.md`, "Testing strategy": one sentence of the
    principle, linking to `TESTING.md`.
  - `openspec/specs/test-compatibility/spec.md`: written by the archive at 6.11 — the
    MODIFIED "Scenarios hold shared services for the whole module" and the ADDED
    "Pipeline scenarios advance only by their own steps" (D6, D7, D8, D9, the principle).
  - `docs/development/ROADMAP.md`: 6.5's gap row (D3).
  - D10: no permanent destination beyond D1's.
  `openspec/specs/README.md` needs no change: no capability or companion is added.
  Done. Written as listed: `TESTING.md`'s "Ansible Syntax and Native Checks", the lanes'
  introduction and the bare-metal and API-credit bullets, the hold rule with a
  paragraph on stepping after it and the lane-hold check in the paragraph after that,
  and the principle and wait paragraph in "The discipline every scenario follows";
  `ARCHITECTURE.md`'s "Testing strategy"; `ROADMAP.md`'s gap row. Beyond the list:
  `openspec/specs/test-compatibility/architecture.md`, "Current limits", now says
  pipeline scenarios advance only by their own steps and only the real-host scenarios
  still poll hardware (6.3). The spec deltas merge at 6.11. `design.md`'s "Design
  promotion record" names every decision's location.
- [x] 6.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=shorten-the-end-to-end-pipeline` after promotion and
  resolve every match, then `openspec validate shorten-the-end-to-end-pipeline --strict`.
  Done. `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` after
  promotion passed: `make check-repository` (documentation citations among comment
  hygiene, specification index, decision destinations, history wording, local imports,
  and the capability index), and `openspec validate shorten-the-end-to-end-pipeline
  --strict` ("is valid").
- [x] 6.11 **Archival.** `openspec archive shorten-the-end-to-end-pipeline -y`, merging
  the `test-compatibility` delta into `openspec/specs/`; then point the index row at the
  archive directory and run `openspec validate --specs --strict`.
  Done. The permanent spec held neither delta's text, so the archive merged them (no
  `--skip-specs`): `scripts/change-workflow openspec archive
  shorten-the-end-to-end-pipeline -y`. The merged `test-compatibility/spec.md` was read:
  the MODIFIED requirement replaces its earlier text once, with its three new scenarios,
  and the ADDED requirement appears once; nothing else changed. The index row links the
  archive, and `scripts/change-workflow run pre-commit` validated every specification
  strictly.
