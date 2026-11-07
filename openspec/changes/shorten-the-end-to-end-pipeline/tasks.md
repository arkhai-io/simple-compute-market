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
  Done. The dry run, as `make build-e2e-native-gate -n` (the unattended step allows
  `make build-*`, not `make -n …`), prints `make init-prerequisites`, `make dist`,
  `make build-provisioning` at the top level and no other image build; the only
  `docker build` is the provisioning service's.
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
  Done. `e2e-vm` has no step running the gate; the dry runs of `build-e2e-native-gate`
  (1.1) and `test-provisioning-iac-native` resolve. Not run: the `python3 -c` YAML
  parse, which the unattended step's rules refuse; the file was checked by reading,
  and the round's validation, which dispatches `e2e.yml`, is the first parse by
  GitHub. The header keeps `PROVISIONING_MODE` at workflow level; the gate job ignores
  it.
- [x] 1.3 Verification point. Locally, where Docker is available:
  `make build-e2e-native-gate` builds `arkhai:compute-provisioning`, then
  `make test-provisioning-iac-native` passes against it. `scripts/change-workflow run
  pre-commit shorten-the-end-to-end-pipeline` passes.
  End-to-end: the pipeline run shows job `native-ansible-gate` passing; `e2e-vm` runs no
  gate step and passes its lane's markers; record each job's duration (the VM lane
  expected about 6.5 minutes, from 12).
  Done on the section's local evidence. `make build-e2e-native-gate` built
  `arkhai:compute-provisioning`; `make test-provisioning-iac-native` passed against it
  (the native Ansible integration tests, real `ansible-playbook` in the image: VM IaC 3
  in 5.8 s, compute family 19 in 131.9 s serially on this host; image syntax gate
  passed). Pre-commit: `after-functional-change` and `pre-commit-functional` (every
  suite, packaging) passed; `pre-commit` failed only on the citations check's three
  files sections 3 and 4 create (`e2e-tests/tests/e2e/roles/helpers/buy.py`,
  `e2e-tests/tests/unit/test_buy_helper.py`,
  `e2e-tests/tests/unit/test_scenario_lane_holds.py`), expected until those sections
  land. Unrun: the end-to-end evidence, which the round's validation produces when it
  dispatches the pipeline.
  Outside the plan: `scripts/tests/test_image_publication_contract.py` failed on the
  base (`cf4db5b7f` moved `push-images` onto `scripts/publish_artifacts.py`, and the
  test still expected a `docker tag` line in the Makefile's dry run). It now reads the
  `image` arguments from `push-images`' dry-run command line and gives them to
  `push_image` with a recording runner, so the build's tag and the tag pushed from must
  agree; a static check of the Makefile's dry runs with a unit check of `push_image`,
  passing. It does not run `publish_artifacts.py`'s argument parser. Also outside the
  plan's file list: `domains/vms/provisioning/iac/README.md` said the VM lane runs the
  root gate target; it now names the `native-ansible-gate` job.
  End-to-end scenarios: no `e2e-tests` marker exercises this section. Its pipeline
  evidence is the job list: `native-ansible-gate` passing, `e2e-vm` running no gate
  step, and each job's duration.

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
  Done. Beyond the plan: a module that fails to import fails the run, naming it (from
  the loader's `errors`); a pattern naming no test is checked per pattern, not only as
  an empty run; and the summary ends `in <seconds>s`, the gate's wall time, so the job
  log records it. The child puts the tests directory (its cwd) on `sys.path`, since
  the native modules import one another by name, and runs unbuffered (`-u`) so its
  stderr and stdout keep their order in the one pipe; its output is decoded with
  replacement, so a stray byte cannot lose the report. The JSON line's `skipped` is a
  list of `[test id, reason]`; `failures` also counts unexpected successes (no case
  covers that). The child exits non-zero on a failure or error, or when it ran no
  test and skipped none; a skip, including one raised in a class fixture (tested) or a
  module fixture (by `unittest`'s handling, untested), is the parent's to judge from
  the JSON line. The parent finds the JSON line by
  searching back from the end, so output written at interpreter exit does not hide
  it, and counts a child failed when its status is non-zero, its JSON line is missing,
  or it reports a failure or error. Only the parent's result loop prints, so blocks
  never interleave. A pattern named twice runs its tests twice; the gate names each
  module once.
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
  supported Ansible on this host). The nine runner cases are integration tests running
  the real runner over planted modules in real child interpreters; they are not
  native, so they run in the default suite and never skip but for the single-CPU
  concurrency case. All ran, the concurrency case included (28 CPUs here). Beyond the
  plan: cases for a module that cannot be imported (named, with its missing import), a
  skip raised in `setUpClass` (counted a skip), and output written at interpreter exit
  after the JSON line (the test still passes, the output inside its block). The
  concurrency case's wait polls the other test's marker every 10 ms against a 60 s
  bound: a poll on that event, not a duration it waits out, though it is a polling
  loop. With the runner forced to one worker, the case failed at its bound naming the
  test that never started, then passed again once restored.
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
  Done. After `make build-provisioning`, `make test-provisioning-iac-native` passed: the
  VM IaC gate's 3 tests as before, then the compute gate's 19 blocks, each `passed`,
  and `native gate: 19 run, 0 failed, 0 skipped in 26.8s`; image syntax gate passed.
  This host has 28 CPUs, so all 19 ran at once: 26.8 s against 131.9 s serially on the
  same host (1.3). The four-CPU figure is the pipeline's to record (2.4).
- [x] 2.4 Verification point: 2.2's integration tests and 2.3's local gate run pass;
  `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` passes.
  End-to-end: the pipeline's `native-ansible-gate` job passes, its log shows the 19
  test blocks and the summary, and it finishes before `e2e-vm`; record its duration.
  Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — as 2.2 states.
  Done on the section's local evidence: 2.2's cases and 2.3's gate run pass. Pre-commit:
  `after-functional-change` and `pre-commit-functional` (`make check-packaging`, every
  suite, `test-provisioning-iac` 33 passed, 19 skipped) passed; `pre-commit` failed
  only on the citations check's three files sections 3 and 4 create, as in 1.3. A
  comment in `native_ansible_gate.sh` was reworded after that run;
  `make check-comment-hygiene` and `make check-history-wording` passed over it.
  Confirmed: the `Owed by validation` line names the job that runs
  `make test-provisioning-iac`, which collects `test_native_gate_runner.py`.
  Handoff: sections 3–5 touch none of this. The VM IaC gate keeps its own serial
  runner (D2); `domains/vms/provisioning/iac/tests/test_ansible_structure.py` reads that
  gate's inline Python, so it must not be moved onto this runner without changing the
  structure test. The pipeline's four-CPU timing of the compute gate is unmeasured
  until validation; if the admission tests contend there (design's risk), the worker
  count is the lever.
  End-to-end scenarios: no `e2e-tests` marker exercises this section; its pipeline
  evidence is the `native-ansible-gate` job's log (19 blocks, the summary) and its
  duration against `e2e-vm`'s. Unrun until the round's validation dispatches the
  pipeline.

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
  Done. Signature `buy_to_ready(buyer_cli, buy_args, *, storefront_admin_client,
  storefront_client, provisioning_client, provisioning_test_client)`; `buy_args` omits
  `buy`, which the helper adds. The negotiation id is the run log's last
  `negotiation_completed` event with status `agreed` (the event `market buy` writes
  with the id; `escrow_created` carries none). Beyond the plan: after `run_ended` it
  waits for the process to exit and requires 0, as the stages' foreground buys did;
  each wait has its own module-level bound (escrow 120 s, submit 60 s, stage event
  30 s, drain 30 s, ready 60 s, exit 20 s). `_run_log_digest` moved from the oneshot
  module into the helper as `run_log_digest`. A step's failure, including the
  `pytest.fail` that `wait_for_stage_event` and `advance_fulfillment_to` raise, is
  re-raised as an `AssertionError` naming the step, with the digest and, for a buy
  that has exited, its stdout and stderr tails, which the stages' foreground buys
  reported (a running buy's streams are not read, since reading them waits for its
  exit). Outside the plan's file list:
  `MarketRun.terminate` (`roles/buyer_cli.py`) killed a process that outlived SIGTERM
  without waiting for it; it now waits, bounded, after the kill, so the helper's
  `finally` reaps what it starts.
- [x] 3.2 Unit tests, `tests/unit/test_buy_helper.py`, with a fake run and recording
  clients (D7): the success path calls start, the two run-log waits, the stage-event wait,
  the settle status read, the drain, the convergence advance, and the `run_ended` wait, in
  that order, and returns the terminal event; a missing `settlement_submitted` event, a
  failed advance, and a `run_ended` other than `ready` each raise naming the step and
  terminate the run once; a buy that ended is not terminated again.
  `test_scenario_holds.py` passes over the new helper module.
  Verify: `make test-e2e-unit` passes with the new cases.
  Done. `make test-e2e-unit`: 561 passed, the six new unit cases among them, and
  `test_scenario_holds.py` over `helpers/buy.py`. The fakes stand in for the run
  (whose waits fail, as the real ones do, for an event it never writes), the buyer
  CLI, the storefront's stage-event wait (which can time out, as the typed client's
  does) and the buyer's settle status, the job queue's drain, and convergence (one
  advance reaches `active`, or none does); the helper's real `advance_fulfillment_to`
  and `wait_for_stage_event` run over them. The order the success case asserts also
  includes the exit wait after `run_ended`. Beyond the plan: a case for a dispatch the
  storefront never logs (the `pytest.fail` of `wait_for_stage_event`, named as its
  step). The missing-event case also checks the failure carries the run log's digest,
  the run-ended case the status it ended with, and the ended-buy case its stdout tail.
  The success case asserts the call order, which `TESTING.md`'s unit level calls
  orchestration; it is kept, as the plan's level for the harness's own helper logic,
  whose integration is the lane run (3.4).
  Round fix, review 17 F2: `test_a_failed_buy_kills_and_reaps_a_process_that_ignores_sigterm`
  runs the helper's failure cleanup over a real `MarketRun` around a real child
  interpreter (`TESTING.md`'s subprocess boundary, kept in `tests/unit` beside the other
  real-child checks). The child ignores SIGTERM, writes the run log's agreed
  negotiation, `escrow_created`, and `settlement_submitted`, and sleeps; the storefront
  fake logs no dispatch, so the helper fails naming its stage-event step, and the test
  requires the child's `returncode` to be SIGKILL's, which is set only once it is
  reaped. It takes about 5 s, `terminate`'s SIGTERM bound. With the wait after the kill
  removed from `MarketRun.terminate`, the case failed (`returncode` None); restored, it
  passed. `make -C e2e-tests test-unit`: 569 passed.
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
  Done. `make test-e2e-unit` passed (561): the cleanup-order check finds no cleanup in
  either module released after a hold, and the holds check passes. Neither check
  requires the four holds to be present; section 4's lane-hold check does. The one
  stage relying on the watchdog is the oneshot module's B4c, whose two dry runs must
  agree; it asserts `assert_lease_watchdog_held` first. `test_listing_shapes` has no
  such stage. The oneshot docstring's stage map now names B4's stepping and B4c, which
  it omitted; B3's docstring and the rule-id comment, and listing shapes' 03a docstring
  and module step 4, describe a job drained and convergence stepped. Each stage keeps
  its assertions on the terminal event, including `status == "ready"`, which the
  helper also requires; the stages' returncode checks are the helper's. The oneshot
  docstring's "untested at the live-subprocess level until now" was history wording,
  rewritten.
- [x] 3.4 Verification point: `make test-e2e-unit` passes;
  `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` passes; where
  Docker is available, `make -C e2e-tests test-e2e-vm` with `E2E_MODULE="e2e_buy or
  e2e_listing_shapes"` passes.
  End-to-end: `e2e_buy` and `e2e_listing_shapes` pass in the VM lane, each buy's step
  log showing a convergence advance before `ready`; record the lane's scenario time.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — the new
  `test_buy_helper.py` cases and the hold checks pass.
  Done on the section's local evidence. `make test-e2e-unit`: 561 passed. The VM lane
  locally (`make -C e2e-tests test-e2e-vm E2E_MODULE="e2e_buy or e2e_listing_shapes"`,
  system level, the lane's stack with mock provisioning): 32 passed in 32.1 s, on the
  final code; a run before the fresh-context fixes passed the same 32 in 24.1 s. With
  the four holds logged taken, each of the three buys logged `[buy] … ready` 4–7 s
  after it started, so none waited out convergence's 30 s timer; `advance_fulfillment_to`
  returns only once the fulfillment reads `active`, and with convergence held only its
  advance can make that transition. The log has no per-advance line; the provisioning
  service's own log of the advance was not read (the step's rules refuse the lane's
  log target). Pre-commit: `after-functional-change` and `pre-commit-functional`
  passed; `pre-commit` failed only on the citations check's
  `e2e-tests/tests/unit/test_scenario_lane_holds.py`, which section 4 creates.
  End-to-end scenarios: `e2e_buy` and `e2e_listing_shapes`, both in the VM lane
  (`E2E_MODULE`), exercise this section once deployed; the pipeline's run of them is
  validation's to produce. Owed by validation: confirmed as stated — `tests.yml`, job
  `test · test-e2e-unit`, runs `make test-e2e-unit`, which collects
  `test_buy_helper.py` and the hold checks.
  Handoff: the helper is VM-lane only today; a bare-metal buy would need its own
  stage-event and settle-status clients but the same sequence. `buy_to_ready` reads the
  negotiation id from `negotiation_completed`, so a buyer CLI that stops writing it
  there breaks the helper at its named step. Section 4 must not add holds to these
  two modules again: they already list all four VM holds.

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
  Done. Holds added as listed; `test_vm_payment_deal` keeps `payments_config` ahead of
  its holds, as before. `make test-e2e-unit` passed (568), the holds and cleanup-order
  checks among them. Read for reliance on a running convergence or watchdog: none.
  `test_non_erc20_settlement` (gaining the watchdog) settles with its own
  `advance_fulfillment_convergence_cycle` and reads settlement readiness from the
  storefront; it never expires a lease. `test_multi_registry` and
  `test_compute_dynamic_listings` settle nothing. `test_vm_introduction` and the two
  bare-metal introduction modules settle by introduction, which dispatches no
  fulfillment and records no lease; `test_bare_metal_publication` settles nothing. The
  introduction module's stage 04 waits on the storefront's own retention window, not
  on convergence or the watchdog (section 5 removes it). The full VM lane run locally
  with the new holds passed (4.3). The VM modules' cleanup is
  the storefront's fleet-wide release, `ensure_storefront_resumed`, and
  `reap_buyer_settle_subprocess`, none of which needs a provisioning timer; the
  bare-metal modules list no cleanup. Beyond the plan: the hold fixtures' docstrings in
  both lane conftests, and `fulfillment_convergence_held`'s and
  `lease_watchdog_held`'s in `helpers/compute_deal.py`, said a module took the hold to
  advance it itself; they now say the hold is the module's and a module that needs a
  transition steps it.
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
  Done. `make test-e2e-unit`: 568 passed, the check's seven cases among them. The two
  real-lane cases read each variable from `e2e-tests/Makefile` and collect its lane
  directory's setup plan in a child pytest with the lane's expression: real child
  processes, `TESTING.md`'s third integration flavour, kept in `tests/unit` beside
  `test_scenario_cleanup_order.py`, which does the same and which `TESTING.md` places
  there. They pass, which also shows the out-of-lane modules excluded:
  `vms/test_real_provisioning_deal.py` lacks `alice_loops_held` and
  `bare_metal/test_bare_metal_deal.py` holds none, and neither fails it. Cases over
  planted inputs: a continued variable read whole, a variable assigned no value
  failing by name (an absent one takes the same path), a lane with no plan failing by
  name (through `check_lane`), and a planted plan missing one hold named by module and
  hold. The "module outside the selection" case runs the real setup plan over a
  planted lane in a temporary directory (a conftest defining the holds; a marked module
  lacking the watchdog hold; a marked module skipped by a `skipif` mark; an unmarked
  module holding nothing): both marked modules are checked, each missing hold named,
  the unmarked one is not, and an expression selecting nothing yields no plan
  (pytest's exit 5). Beyond the plan: the setup plan runs with `-p no:skipping`, so a
  module skipped where the check runs is still held to its lane's holds; without it a
  skip mark would hide the module from the plan and the check would pass it. A module
  skipped at collection (`pytest.skip` at module level, `importorskip`) still escapes,
  as it does collection itself. With `lease_watchdog_held` removed from
  `test_vm_introduction.py`, the `E2E_MODULE` case failed with
  `tests/e2e/roles/scenarios/vms/test_vm_introduction.py: lease_watchdog_held`; with
  `fulfillment_convergence_held` removed from `test_bare_metal_publication.py` (on the
  final code), the `E2E_BARE_METAL_MODULE` case failed naming it; each restored, both
  passed. The variable is read by pattern, its first non-empty assignment: a later
  `+=` or a conditional assignment would be missed and read the lane short. The lanes'
  variables have one `?=` each, which the pipeline's lane targets use as they are.
  Outside the plan, for the round's review: the VM lane's expression also selects
  `e2e_alkahest_escrow_codecs` and `e2e_alkahest_trusted_oracle`, modules in
  `scenarios/core/` that talk only to the dev chain. D6's check reads each lane's own
  directory, so they are outside it, as the design intends; the delta requirement's
  "every module a compute pipeline lane selects" reads wider than that and would cover
  them. Holding Bob's and Alice's timers for chain-only modules would be harmless but
  pointless; the requirement's wording, or the check's directories, is the design's to
  settle.
  Round fix, review 17 F1 (the owner chose the exemption, D6 amended): the check now
  collects each lane's expression with no path, over pytest's configured test paths as
  the lane's own run does, and `held_plans` drops modules under `scenarios/core/`
  (`CHAIN_ONLY`); every other selected module, from any directory, is held to the lane's
  holds. The delta requirement states the exemption and gains the scenario "A lane
  selects a module outside its directory"; `proposal.md`'s line says the same. The
  planted case is now `test_the_selection_is_the_expression_not_the_directory`: over a
  temporary tree, a marked module in the lane directory, one skipped there, and one in
  another directory are each held to the holds, a marked one under the planted `core/`
  is not, an unmarked one is not, and an expression selecting nothing yields no plan.
  With `CHAIN_ONLY` pointed at a missing directory, the `E2E_MODULE` case failed naming
  exactly the two `core` modules' four holds each; restored, it passed.
  `make -C e2e-tests test-unit` (unit level, with this check's real child pytest, as
  above): 569 passed.
  The round's fresh-context check (both fixes, against `6216a4504`) found nothing
  blocking; fixed from it: `scenarios/core/__init__.py` gained a docstring stating the
  directory's chain-only meaning the exemption rests on (D6 cites it); the delta's
  source-check clause and the "omits a hold" scenario now carry the exemption; the
  check's failure message says a module outside its lane's directory moves into it,
  where the hold fixtures are defined; `lane_plans`' docstring says pytest reports
  paths relative to its rootdir. Also corrected, outside the findings: 5.4's handoff
  cited the roles README without its `tests/e2e/` segment, which the citations check
  refused; it now cites `e2e-tests/tests/e2e/roles/README.md`.
  Pre-commit on the round's fixes (both findings), final content:
  `after-functional-change … passed, exit 0`; `pre-commit-functional … passed, exit 0`
  (`make test`, the e2e unit suite 569 passed, `scripts/tests` 2681 passed, packaging);
  `pre-commit … passed, exit 0` (citations included).
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
  Done on the section's local evidence. Pre-commit: `after-functional-change`,
  `pre-commit-functional` (every suite, packaging), and `pre-commit` (citations
  included, now that the check's file exists) passed.
  `make test-e2e-unit` 568 passed. The full VM lane locally
  (`make -C e2e-tests test-e2e-vm`, system level, with sections 3–4's holds): 153
  passed, 2 skipped, in 100.65 s of scenarios. The two skips are
  `test_vm_payment_deal`'s operator-end and refund stages, which skip by design where
  no dispute authority is configured, as in the lane. The design's baseline counts 153
  VM scenarios; this host's time is not comparable with the pipeline runner's. The
  full bare-metal lane locally (`make -C e2e-tests test-e2e-bare-metal`): 70 passed in
  50.48 s, its retention-sweep stage still present (section 5 removes it). A first
  bare-metal run failed to start because the VM stack left up held the `anvil`
  container name (`TESTING.md`: the lanes run one at a time); `make -C e2e-tests
  e2e-vm-down` cleared it.
  Correction to the list above: `e2e_alkahest_escrow_codecs` and
  `e2e_alkahest_trusted_oracle` are `scenarios/core/` modules, which take no hold and
  are outside the check (4.2's note); they pass in the VM lane without holds.
  End-to-end scenarios: every marker listed above, in the VM and bare-metal lanes
  (`E2E_MODULE`, `E2E_BARE_METAL_MODULE`); the pipeline's run of them is validation's.
  Owed by validation: confirmed as stated — `tests.yml`, job `test · test-e2e-unit`,
  collects `test_scenario_lane_holds.py`.
  Handoff: the check imports `module_plans` from `test_scenario_cleanup_order.py`, as
  that module imports `HOLD_FIXTURE_NAMES` from `test_scenario_holds.py`; moving either
  parser moves both checks. Section 5 edits `test_bare_metal_introduction.py` and
  `test_bare_metal_payment_deal.py`, whose holds are now complete; it must keep them
  first in `usefixtures`. The `core` modules' place under the rule is open for the
  round's review (4.2's note). Settled by review 17 F1: they are exempt by directory,
  and the check collects what the lane collects (4.2's round fix).

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
  Done. The module defines stages 00–03 and calls no dry run; no import became unused
  (`time` serves stage 02's expiration, `IntroductionPayloadsDeleted` stage 03). The
  docstring names the integration test's file, whose
  `test_held_retention_sweep_deletes_what_it_previewed` back-dates a reveal and steps
  the held sweep. The scenario still reveals two introductions and deletes the first;
  `IntroductionState.operator_deleted` is now set and read by no later stage, kept as
  the stage's record. `make test-e2e-unit` passed (568). The bare-metal lane locally
  ran stages 00–03, passing (5.4).
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
  Done. The overlay overrides the included `sample-app` service's environment, as
  `compose.apicredits-local.yml` already overrides its volumes. With a TTL of 0 the
  gate's cached verify expires at once (`gate.py` keeps it only while
  `verify_expires > now`), so every request re-verifies, and a valid verify clears the
  key's cached exhaustion; the first drain still answers 402 through the consume path.
  The scenario's poll is one request expecting 200 and the forecast; its failure
  message names the overlay setting. `time` is no longer imported. The plan's
  `docker compose … config` was refused under this step's rules (don't-ask mode);
  in its place, beyond the plan, `scripts/tests/test_lane_compose.py` gained
  `test_only_the_api_credit_lane_runs_the_sample_app_with_no_verify_cache`, which
  renders both stacks with `docker compose config` and requires the lane's TTL `0` and
  the full stack's `3`. `make test-release-tooling` (which runs `scripts/tests`): 2681
  passed, none skipped, so Compose was present and the new case ran.
  `make test-e2e-unit` passed (568). The API-credit lane locally passed (5.4); that
  run cannot be relied on to separate TTL 0 from 3, since the top-up's own negotiation
  and settlement between the drained request and the next likely outlast a 3 s
  cache, so the render test is the evidence for the value.
- [x] 5.3 In `test_bare_metal_payment_deal.py` (D8), replace the status poll after
  `advance_fulfillment_to(..., "active")` with one `payment_fulfillment.status(...)` read
  asserting `state == "active"`, with a message saying the storefront reads provisioning's
  status live; drop the `time` import if unused.
  Verify: no loop remains between the advance and the delivery assertions;
  `make test-e2e-unit` passes.
  Done. One read after the advance, its message saying the storefront reads
  provisioning's status live; no loop remains before `assert_delivery`. `time` was
  used nowhere else and is no longer imported. `make test-e2e-unit` passed (568); the
  bare-metal lane locally passed `test_payment_deal_delivers_after_a_verified_receipt`
  with the single read (5.4).
- [x] 5.4 Verification point: `make test-e2e-unit` passes;
  `scripts/change-workflow run pre-commit shorten-the-end-to-end-pipeline` passes.
  End-to-end: `e2e_bare_metal_introduction` passes stages 00–03;
  `e2e_credits_deal` passes, its post-top-up request answering 200 at once;
  `e2e_bare_metal_payment_deal` passes, its status read answering `active` once.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes.
  Done on the section's local evidence. `make test-e2e-unit` 568 passed;
  `make test-release-tooling` 2681 passed. Pre-commit, on the final content:
  `after-functional-change`, `pre-commit-functional` (every suite, packaging), and
  `pre-commit` passed.
  Local evidence (system level, each lane's stack with mock provisioning, on the
  section's code before the fresh-context fixes, which changed only comments, a marker
  description, and a test docstring): `make -C e2e-tests test-e2e-bare-metal` 69
  passed in 28.51 s, against 70 in 50.48 s before the stage's removal (4.3); the run
  lists `test_bare_metal_introduction`'s stages 00–03 and no 04, and
  `test_payment_deal_delivers_after_a_verified_receipt` passed with the single read.
  `make -C e2e-tests test-e2e-apicredits`: 4 passed in 11.72 s, `e2e_credits_deal`'s
  post-top-up request answering 200 (5.2 says why that run alone does not pin the
  TTL). Each stack was taken down after its run (`make -C e2e-tests
  e2e-<lane>-down`), since the lanes share the `anvil` container name.
  Outside the plan's file list, from the fresh-context check: three texts still
  described the removed stage — the `e2e_bare_metal_introduction` marker in
  `e2e-tests/pyproject.toml`, and the retention-window comments in
  `domains/bare_metal/storefront/storefront.dev.toml` and
  `e2e-tests/config/config-docker.yml` — now say the window is read back from the
  disclosure. The 5-second window itself is unchanged: stage 00 compares the disclosure
  with it, and any value would serve.
  Declined, for the round's review: the introduction scenario still declares two
  hosts and reveals two introductions, though only the first now feeds a later stage
  (the second fed the removed sweep). D4 keeps stages 00–03 as they are; dropping to
  one host is a scenario edit the design did not ask for.
  End-to-end scenarios: `e2e_bare_metal_introduction` and `e2e_bare_metal_payment_deal`
  (bare-metal lane), `e2e_credits_deal` (API-credit lane); the pipeline's run of them
  is validation's.
  Owed by validation: confirmed as stated — `tests.yml`, job `test · test-e2e-unit`.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — runs
  `scripts/tests` through `make test-release-tooling`; the new
  `test_only_the_api_credit_lane_runs_the_sample_app_with_no_verify_cache` runs, not
  skipped for want of Compose, and passes.
  Handoff: `TESTING.md`'s bare-metal lane bullet and the `e2e-tests/tests/e2e/roles/README.md`
  text describing scenarios were not edited here; closeout's promotion (6.9) owns the
  former, and the latter was not found to describe the removed stage. Every section of
  the round is now implemented; the pipeline run is validation's.

## 6. Closeout

Confirm and promote the verified design, then archive last (D1–D10 and both delta
requirements). The eleven parts follow `openspec/README.md#plan-closeout-requirements` in
order. Closeout changes no code: a part needing a code, workflow, Compose, or test change
returns the change to implementation.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every
  comment and docstring sections 1–5 added: the `e2e.yml` header and job, the
  `build-e2e-native-gate` comment, `native_gate_runner.py` and its tests, the gate
  script, `helpers/buy.py`, the lane-hold check, the scenario docstrings and messages
  touched, and the two Compose comments. Each states current behaviour, with no change,
  review, or migration wording. A needed correction returns to implementation.
- [ ] 6.2 **Import placement — confirm.** Every import sections 1–5 added is at module
  level, or local with a recorded reason. One that should move returns to implementation.
- [ ] 6.3 **Documentation compliance.** Check D1–D10 and the principle against
  `openspec/README.md`'s placement table: testing methodology in `TESTING.md`, the
  normative hold and stepping rules in `test-compatibility`'s spec, the one-line
  principle in `ARCHITECTURE.md`, the gap in `ROADMAP.md`; nothing durable left only in
  this change.
- [ ] 6.4 **Narrative compression.** Compress section notes to final behaviour, material
  validation evidence (gate and lane durations, the runs), unresolved or deferred work,
  and permanent destinations, moving any durable rationale into `design.md` first.
- [ ] 6.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, "Goal 1 — Consolidate
  physical-resource authority in the provisioning service", add an open-gap row: no
  workflow runs the bare-metal cleanup native gate (`make test-bare-metal-iac-native`),
  so the bare-metal working-data helper's native account, filesystem, and IPC tests run
  only when someone runs them locally; owned by "Unowned — needs a new change" (D3).
  Record that no goal's current state otherwise changes.
- [ ] 6.6 **Campaign index currency.** In `openspec/changes/README.md`, update this
  change's row in "Lesser goal — End-to-end harness determinism" so its status and notes
  say what is true (status `in closeout`; archive cleanup writes `archived`), and note in
  `apicredits-end-to-end-lane`'s row that its loop holding adopts this change's hold rule
  for its lane (D6). Leave every `Depends on` for archive cleanup. Run
  `scripts/change-workflow check index`.
- [ ] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=shorten-the-end-to-end-pipeline`. No `.agents/`,
  `.claude/`, or `.codex/` edit is planned; if one was made, run
  `make check-agent-skills`.
- [ ] 6.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, each job's duration, and the evidence for this change:
  the `native-ansible-gate` job passing with 19 compute test blocks; `e2e-vm` running no
  gate step; every VM and bare-metal lane marker passing with its lane's holds (4.3's
  list); `e2e_buy` and `e2e_listing_shapes` stepping convergence; `e2e_credits_deal`,
  `e2e_bare_metal_introduction`, and `e2e_bare_metal_payment_deal` passing without a
  timer or duration wait. A pipeline that cannot run for a reason outside this change is
  recorded as a blocker naming its cause and owner, with its validations unrun.
- [ ] 6.9 **Promotion.** Write, and record in a `## Design promotion record` table in
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
- [ ] 6.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=shorten-the-end-to-end-pipeline` after promotion and
  resolve every match, then `openspec validate shorten-the-end-to-end-pipeline --strict`.
- [ ] 6.11 **Archival.** `openspec archive shorten-the-end-to-end-pipeline -y`, merging
  the `test-compatibility` delta into `openspec/specs/`; then point the index row at the
  archive directory and run `openspec validate --specs --strict`.
