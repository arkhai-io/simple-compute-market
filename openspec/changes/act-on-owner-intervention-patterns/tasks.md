# Tasks

Sections 1–6 are the code: the workflow tooling (1–3) and the checks (4–6). Sections
7–10 are the guidance and the skills that describe it, the guidance first, since the
skills cite it. Section 11 is the closeout. Every script suite named below runs under
`make test-release-tooling` (`pytest -q scripts/tests`), which `make test` reaches
through `test-deployment-packaging`. No end-to-end scenario in `e2e-tests/` exercises
the change workflow's tooling, its skills, or the repository's checks, and none is
owed: they run on a developer's machine and in CI, not in the deployed stack. The
pipeline still runs on every validation, and for section 4 its result is evidence that
the raised uv builds and runs the stack.

Replanned after round 1, on the owner's direction once `dev` was merged in
(`ed68f99ad`): sections 7–11, none of whose tasks was checked, are amended against
dev's restructured workflow, which `design.md`'s status note describes. The
completed sections' notes keep what they record, with the paths the merge renamed
written at their current places so their citations resolve: the script
`run_change_step.py` is the `scripts/change-workflow` command; the scripts
`round_view.py`, `change_clone.py` and `change_next_step.py`, and the guarded push of
`check_push_ready.py`, are `scripts/change_workflow/round_view.py`, `clone.py`,
`next_step.py` and `push.py`; the cases of the test file `test_run_change_step.py` are
in `scripts/tests/test_change_workflow_cli_steps.py`, its `make -n` case in dev's
Makefile table; and `change-workflow`'s companion, `architecture.md`, is
`openspec/specs/change-workflow/README.md`, its "Secret scanning" section in
`openspec/specs/market-change-workflow/README.md`. Where a completed note names
`test_run_change_step.py` or `run_change_step.py`, it means these. The
delta requirements the sections implement are named by the ids the re-targeted deltas
give them.

## 1. A running step can be stopped (D15)

Delivers the `stop` command, the run's identity as a held lock, and SIGTERM handling
in the review runner. Implements D15 and the delta requirement "The owner interrupts a
running step". Touches `scripts/change_workflow/running.py`, `wrapper.py`,
`review.py`, `harness.py`, `cli.py`, the `scripts/change-workflow` command, and the run
records' readers `scripts/change_workflow/round_view.py` and
`scripts/change_workflow/clone.py`.

- [x] 1.1 Make each run hold an exclusive `fcntl` lock on its record file for as long
  as it runs, opened without inheritance by the run's children, and make a record
  count as a live run only while its lock is held, for every reader
  (`runs_in_progress`, `live_runs`, `round_view.py`, `change_clone.py`) (D15). Verify:
  unit tests in `scripts/tests/test_change_workflow_wrapper.py` and
  `test_round_view.py` show a record whose lock is free read as no run, a held one as
  a run, and a child process of the run holding no lock; `test_change_clone.py`'s
  run-in-progress cases still pass.
  Done: `running.recorded_run` writes the record aside, takes `flock(LOCK_EX)`, then
  renames it, so no reader sees it unlocked; `live_runs` reads a record as a run only
  when a non-blocking `LOCK_SH` fails. `flock`, not `lockf`: a POSIX record lock
  belongs to the process, so an in-process reader would always acquire it and its
  close would drop the run's lock. The `alive` and `pid` parameters are gone; the
  record's process is always the holder. `round_view.py` and `change_clone.py` read
  through `runs_in_progress` and needed no edit. Evidence, differing from the plan's
  "unit tests" since they use real `flock` and real processes, which `TESTING.md`
  makes library integration: `test_change_workflow_wrapper.py`
  `test_a_record_is_a_run_only_while_its_lock_is_held` (held reads as a run; a
  hand-written record with a free lock reads as none though its pid is alive) and
  `test_a_killed_runs_record_is_stale_though_its_child_survives` (a real run process
  SIGKILLed with a grandchild started `close_fds=False` still alive: its record stays
  and reads as no run); `test_round_view.py`
  `test_a_held_record_refuses_the_view_and_a_stale_one_does_not` (a real Git checkout's
  records). `test_change_clone.py`'s run-in-progress case passes, now through the lock.
- [x] 1.2 Add `scripts/change-workflow stop <change> [--step <step>]` (D15):
  it selects the change's live run, or the run of the named step when two are live,
  checks the lock again immediately before sending SIGTERM, and refuses, signalling
  nothing, when no run is live, when two are live and no step is named, when the
  record is stale, or when the run ended before the second check. Verify: unit tests
  in `scripts/tests/test_change_workflow_cli_steps.py` for each refusal and for a signal reaching
  a live run; a library-integration test that starts a real child process holding a
  record, stops it, and finds it ended; the delta scenarios "Nothing is running", "A
  run record outlives its run", and "A run ends while it is being stopped" each map to
  a test.
  Done: `running.select_run`, `signal_run` and `stop`; the CLI's `stop` command, with
  `os.kill` injected as `main(send=…)`. Beyond the plan, `stop` reads the runs of the
  change's clone when it has one (`clone_of`, as `watch` does), since a cloned change's
  steps run and record there; `test_change_clone.py`
  `test_stop_from_the_workspace_signals_the_run_in_the_changes_clone` covers it. Tests
  in `test_run_change_step.py` (unit, with in-process `flock`s and an injected `send`):
  a signal reaching the one live run; "Nothing is running"
  (`test_stop_with_nothing_running_refuses_and_signals_nothing`, beside another change's
  live run); "A run record outlives its run" (`test_stop_refuses_a_stale_record_naming_it`);
  two live runs refused without `--step` and the review signalled with it; "A run ends
  while it is being stopped" (`test_a_run_that_ends_before_the_second_check_is_not_signalled`,
  record removed, and `test_a_run_killed_between_the_checks_is_not_signalled`, record
  left with its lock released); `ProcessLookupError` at the signal reported as ended.
  Library integration: `test_a_stopped_step_is_logged_stopped_and_its_agent_ended`
  starts a real wrapper process running a real agent process through `run_claude`,
  stops it with the real `os.kill`, and finds it logged `stopped` naming SIGTERM, its
  agent gone, and its record removed.
- [x] 1.3 Raise SIGTERM as the wrapper's termination inside `review_and_log`, so a
  stopped review reaches its existing interruption path, is logged `stopped`, publishes
  nothing, and removes its record; and make `run_codex` end the reviewer process it
  started before the run is logged, as `run_claude` does (D15). Verify: unit tests in
  `scripts/tests/test_change_workflow_review.py` and `test_change_workflow_harness.py`
  show a review signalled mid-run logged `stopped` with no record published and its
  reviewer process ended; the delta scenario "Two runs are in progress" maps to a test
  that stops the review and leaves a second live run untouched.
  Done: `Terminated` and `termination_ends_the_run` moved from `wrapper.py` to
  `running.py`, so `review.py` uses them without importing the wrapper; the handler
  spans only `run_review`, as the wrapper's spans only its attempts. `run_codex` kills
  its process in a `finally`. Evidence: `test_change_workflow_review.py`
  `test_a_review_signalled_mid_run_is_logged_stopped_and_publishes_nothing` (unit: a
  fake runner writes a review, then SIGTERMs its own process; logged `stopped`, no
  record, run record removed, handler restored); `test_change_workflow_harness.py`
  `test_a_terminated_codex_run_ends_its_reviewer` and `…_claude_run_ends_its_agent`
  (library integration: a real child signals its parent and is gone afterwards). "Two
  runs are in progress": `test_run_change_step.py`
  `test_stopping_the_review_leaves_the_validation_running` (library integration: a real
  review process through `review_and_log` and `run_codex`, whose reviewer has written a
  finished review, beside a real wrapper's validation; `stop --step review` logs the
  review `stopped`, publishes nothing, keeps the output as `.rejected.md`, ends the
  reviewer, and leaves the validation, its agent, and its live record untouched).
- [x] 1.4 Verification: `pytest -q scripts/tests/test_change_workflow_wrapper.py
  scripts/tests/test_change_workflow_review.py scripts/tests/test_change_workflow_harness.py
  scripts/tests/test_change_workflow_cli_steps.py scripts/tests/test_round_view.py
  scripts/tests/test_change_clone.py` (unit, and library integration where a real
  process or Git repository is used) passes; `make test` passes.
  End-to-end: none; no scenario exercises the workflow tooling.
  Done: the six suites, 375 passed (run as `uv run --no-project --with pytest pytest`);
  `make test-release-tooling` 1903 passed; `make test` passed before the
  fresh-context check's fixes, which touched only `scripts/` and its tests, and
  `make test-release-tooling` passed after them. `make check-change` fails only on the
  citations of files sections 5 and 8 create (`scripts/check_secrets.py`, its test, and
  `.agents/skills/guidance-review/SKILL.md`). End-to-end confirmed: no `e2e-tests/`
  marker exercises the tooling.
  Handoff: on this machine `make test` ran a uv older than the revision-5 writer, and
  its subprojects' `uv run` rewrote 52 `uv.lock` files from revision 5 to 3 — the drift
  section 4 stops. The session put each back by hand (only line 2 differed); until
  section 4 lands, check `git status` after `make test` and restore any lock it
  rewrote.
- Round 1 triage fixes (64 F1, 64 F2):
  - 64 F1 (the owner chose B): a stop that reached a run while it finished, after its
    agent or reviewer had exited, killed it with no line. `running.py`'s new
    `termination_deferred()` holds SIGTERM for as long as a run holds its record;
    `termination_ends_the_run()` covers each runner call only — the wrapper's in
    `_attempt_models`, the review's in `_codex_attempt` and `_claude_attempt` — raises
    at entry a signal held before it, and sets its handler inside its `try`. A signal
    after the process exits ends nothing, and the run logs the outcome it reached.
    Delta spec: the interrupt requirement's last sentence and the scenario "A stop
    arrives as the run writes its line"; `design.md` D15 records it.
  - 64 F2: an interrupted review's `stopped` line now carries the reviewer's session,
    read from the interrupted attempt's own output in the transcript, and its cost.
    `run_review` hands the record to an `interrupted` callback before passing the
    interruption on; `_unpublished_record` builds it, and the rejected-review path
    shares it, so a rejected review's line carries its session too, and a runner
    failure its models passed over, session and cost.
  - Tests (unit, with real signals): a wrapper stop after the agent exits is logged
    `finished`; a wrapper and a review stop before the agent or reviewer starts end
    the run without running it; a review stop after publication is logged `finished`
    with its record; a Codex interrupt records `codex:s-1` and its tokens, a Claude
    interrupt `claude:c-1`.
  - Evidence: the workflow suites (`test_change_workflow_wrapper.py`,
    `test_change_workflow_review.py`, `test_change_workflow_harness.py`,
    `test_run_change_step.py`, `test_change_next_step.py`, `test_change_clone.py`,
    `test_check_history_wording.py`; unit, and library integration where a real
    process or repository is used) 551 passed; `make test` passed, its scripts suite
    2076 passed, no lock rewritten; `make check-packaging` passed; `make check-change`
    fails only on the citation of section 8's skill. End-to-end: none; the owner
    waived the Helm and end-to-end parts of validation for the rest of the change
    (66 V1).
  - Fresh-context check: fixed — the review's handler covered the whole model loop,
    so a signal after a reviewer exited discarded its draft (moved into each
    attempt); a pending signal could arrive before a handler's `try` and leave it
    unrestored (handlers now set inside the `try`); a failure building the
    interrupted record could swallow the interrupt (guarded); the session could be
    read from an earlier attempt (read from the attempt's offset); two comments still
    pointed at the shrunken `ARCHITECTURE.md` paragraph (65 O3); the audit was
    described as running "every rule"; a missing before-start review test and
    restoration asserts in the Claude test. Declined: a wrapper test for a signal
    between network retries, since the before-start test covers the same entry check.

## 2. A finished triage can be resumed for a revisit (D16)

Delivers the owner's `--resumes` direction and the wrapper's resume of a finished
triage under it. Implements D16, D4, and the delta requirement "The owner revisits a
default acceptance". Touches `scripts/change_workflow/cli.py`, `log.py`, `wrapper.py`,
and `scripts/change_workflow/next_step.py`; no node or exit of `scripts/change_workflow/graph.py`
changes (D4).

- [x] 2.1 Add `--resumes <seq>` to `run_change_step.py note`, accepted only with
  `--by owner`, naming a `finished` triage run; the log's writer refuses it when that
  run is not the latest triage run of the reviews it triaged, naming the later
  triage, or when the run is not a finished triage (D16). Verify: unit tests in
  `scripts/tests/test_change_workflow_log.py` and `test_run_change_step.py` for the
  accepted direction and each refusal; the delta scenario "A later triage has run"
  maps to a test.
  Done: `log.revisit_refusal` and `revisit_direction`, checked in `decision_line`; the
  line records `resumes` and no `next`. Beyond the task's two refusals, three found
  by the fresh-context check: a run that resumed the triage supersedes it too, even
  while it waits with a question or a stop (else a second revisit would resume the
  finished session under a waiting one); a finished triage naming no review is not
  revisited; and `--resumes` with `--next` is refused, since the resumed triage names
  the exit. Unit tests, `test_change_workflow_log.py`: the accepted direction beside a
  later triage of other reviews; "A later triage has run"
  (`test_a_revisit_of_a_triage_a_later_triage_superseded_is_refused`); a question,
  stop, or return, a validation, and a missing seq refused as not a finished triage;
  the orchestrator's refused; a waiting resumed run; no review named; `--next`.
  `test_run_change_step.py`: the command line's accepted direction resuming the
  triage, the orchestrator's refused, and the later-triage and not-finished refusals.
- [x] 2.2 Let `Wrapper.resume` resume a `finished` triage run only when an unused owner
  direction `--resumes` names it, and keep refusing every other finished run as not
  waiting (D16). Verify: unit tests in `scripts/tests/test_change_workflow_wrapper.py`
  for a resume under the direction, a resume without one refused ("A finished run is
  resumed without a direction"), and a direction used once only.
  Done: under an unused direction the step's-latest-run rule gives way to
  `revisit_refusal`, checked again at the resume; the resumed line records
  `resumes: <seq>`, which spends the direction. A finished triage without a direction
  is refused as before, its message now naming the `--resumes` direction. Unit tests,
  `test_change_workflow_wrapper.py`: a resume under the direction after the stopped
  validation was resolved; "A finished run is resumed without a direction"; a direction
  used once; a direction given before a later triage of the same review, refused at the
  resume; a direction naming another triage resuming nothing.
- [x] 2.3 Make the next-step computation route on the resumed triage's later outcome
  for the reviews it names, and read the stopped step it superseded as resolved only
  through the owner's decision line (D16). Verify: unit tests in
  `scripts/tests/test_change_next_step.py` for "A revisit while the fix commit is
  validated": a triage finished, its fix commit's validation stopped and resolved, the
  triage resumed and finished again, and the computation naming what that later
  outcome's exit requires; `scripts/tests/test_change_workflow_graph.py` passes
  unchanged, showing the graph has no new node or edge.
  Done: no code change was needed. `route_of` already takes the last exit logged, and
  `pending` already holds a stopped run until a line resolves it; only `route_of`'s
  docstring gained a sentence saying a revisit's direction routes nothing. The test
  `test_a_revisit_while_the_fix_commit_is_validated_routes_on_the_resumed_triage`
  (unit) therefore proves that existing behaviour holds for a revisit, not new routing:
  the stopped validation waits through the interrupt line and the `--resumes` line,
  and once resolved, the resumed triage's exit (pre-closeout) governs in place of the
  first's (the next round). `graph.py` and its test are unchanged.
- [x] 2.4 Verification: `pytest -q scripts/tests/test_change_workflow_log.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_next_step.py
  scripts/tests/test_change_workflow_graph.py scripts/tests/test_change_workflow_cli_steps.py`
  (unit) passes; `make test` passes. End-to-end: none; no scenario exercises the
  workflow tooling.
  Done: the five suites, 541 passed; `make test-release-tooling` 1923 passed. `make
  test` was not rerun for this section: it rewrites this machine's locks (section 1's
  handoff), and the section touched only `scripts/` and its tests, which
  `make test-release-tooling` covers; it runs again after section 3. `make
  check-change` fails only on the citations sections 5 and 8 create. End-to-end
  confirmed: none.
  Handoff for section 10 (`change-orchestrate`): nothing in code stops a resume of the
  stopped step a revisit leaves; the spec's "resolved rather than resumed" rests on the
  skill. Order the procedure stop, `note --by owner --resumes`, resume the triage, then
  resolve the stopped step: resolved before the resume, the computation names the old
  triage's exit again until the resumed triage ends. At closeout,
  `openspec/specs/change-workflow/README.md` still says the wrapper refuses any
  run not waiting; D16's promotion there covers the revisit.

## 3. Reviewers state alternatives on every finding (D17)

Delivers the required `Alternatives:` field in the review publishing check and in
`change-review`'s finding format together, so the next review is written in the format
its publisher checks. Implements D17 and the delta requirement "Review records".
Touches `scripts/change_workflow/review.py` and `.agents/skills/change-review/SKILL.md`.

- [x] 3.1 Add `Alternatives` to `review.py`'s required finding fields, accepting any
  non-empty value, so a finding missing it is refused and its output kept beside the
  transcript (D17). Verify: unit tests in `scripts/tests/test_change_workflow_review.py`
  for a review missing the field rejected ("A finding states no alternatives") and one
  stating `none — <reason>` published ("A finding has one evident fix").
  Done: `FIELDS["Alternatives"] = None`. Outside the plan, a defect the new tests
  found, fixed here as small and understood: `_FIELD`'s `\s*` ran past the line's
  end, so an empty field took the next line as its value — an empty
  `- **Alternatives:**` passed on the prose below it, and an empty Evidence swallowed
  the Alternatives line. The value is now the rest of the field's own line. Unit tests
  through `run_review` with a fake runner: "A finding states no alternatives"
  (`test_a_review_missing_alternatives_is_kept_beside_its_transcript`: refused, nothing
  published, the output kept as `01-design.rejected.md`); an empty field and a nested
  list each refused as no Alternatives; an empty Evidence refused as no Evidence; "A
  finding has one evident fix" (`test_a_finding_stating_its_one_evident_fix_is_published`:
  the publisher admits `none — <reason>`; that a reason is given is the reviewer's, the
  check asking only for a value). The shared `FINDING` fixture gained the field.
- [x] 3.2 Add `- **Alternatives:**` to `change-review`'s finding format in section 6,
  with the rule that it holds `none — <why the fix is evident>` or each option a
  reasonable owner might choose with its trade-off, and that the direction finding's
  prose alternatives are listed there too (D17). Verify: `make check-agent-skills`
  passes, and the format block in the skill carries every field `review.py` requires.
  Done: the field in section 6's format block, and its rule as an **Alternatives**
  paragraph in section 4 beside basis and severity: options with trade-offs or `none —
  <why>`, "none" a statement, a direction finding's alternatives listed there too, and
  the value on the field's own line, several separated by `; or`, since the check reads
  a nested list as empty. The skill's description names the field too. The skill says
  nothing of triage reading the field: that is section 9's. Outside the plan,
  `docs/agents/change-workflow.md`'s "Reviews" sentence listing what the publishing
  check requires now names alternatives, so it stays true before section 7. The format
  block carries all five of `FIELDS`: Lens, Basis, Severity, Evidence, Alternatives.
  `make check-agent-skills` passes.
- [x] 3.3 Verification: `pytest -q scripts/tests/test_change_workflow_review.py` (unit)
  passes; `make check-agent-skills` passes; `make test` passes. End-to-end: none; no
  scenario exercises the review tooling.
  Done: the review suite, 76 passed; `make check-agent-skills` passes; `make test`
  passed, run before the fresh-context check's fixes, which touched only the skill's
  wording, one sentence of `docs/agents/change-workflow.md`, and the review tests;
  `make test-release-tooling` 1928 passed after them. `make test` rewrote the same 52
  locks to revision 3 again, and they were put back. `make check-change` fails only on
  the citations sections 5 and 8 create. End-to-end confirmed: none.
  Handoff: the round's own review is the first written in this format. Section 9's
  Rule E reads the field; section 7's "Reviews" text describes it more fully than the
  one sentence corrected here.

## 4. One lock revision, and a uv minimum every lock writer checks (D24 item 7)

Delivers the lock-revision check, the raised uv minimum, the guard in every lock
writer, and the relock. Implements D24 item 7 and the delta scenarios "A lock is
written by another uv release" and "A lock is rewritten with an older uv". It comes
before the other checks because the drift is happening now. Touches
`scripts/check_locks.py`, `scripts/check_uv_version.py`, `scripts/uv_project.py`,
`.github/workflows/tests.yml`, `.github/workflows/e2e.yml`,
`docs/development/BUILD_AND_PACKAGING.md`, and the `uv.lock` files at revision 3
(`core/`, `domains/bare_metal/provisioning/iac/`, `domains/vms/provisioning/iac/`,
`kit/capability-shape/`, `kit/identity/`, `provisioning/compute/iac/`,
`tools/frp-grant-admission/`, `tools/issue-discovery/`).

- [x] 4.1 Establish, by running uv, the first release that writes lock revision 5, and
  record it and how it was found in this section's notes (D24 item 7). Verify: the
  notes name the release, the release before it, and the revision each writes.
  Done: **uv 0.12.22** is the first release that writes revision 5; **0.12.21**, the
  release before it, writes revision 3. Found by locking a fresh one-file project (no
  dependencies, `requires-python = ">=3.10"`, no prior lock) with each release through
  `uvx --from uv==<release> uv lock`, under the owner's grant for this run: 0.12.19,
  0.12.20 and 0.12.21 write revision 3; 0.12.22, 0.12.23, 0.12.24 (the last 0.12
  release; 0.12.25 does not exist) and 0.13.0 write revision 5. A fresh project
  matters: a release relocking an existing lock in which nothing changes leaves it at
  the revision it had (0.12.22 kept a revision-3 lock at 3).
- [x] 4.2 Raise `MINIMUM` in `scripts/check_uv_version.py` to that release, its
  docstring covering drift in both directions; move `tests.yml`'s and `e2e.yml`'s
  `setup-uv` pins to it; and make `scripts/uv_project.py` run the uv-version check
  before its `lock` and `reinit` commands run uv, keeping `make lock`'s
  `check-uv-version` prerequisite (D24 item 7, 31 F2). Confirm no other uv the
  repository installs rewrites a lock (`install.sh` pins its own uv); one that does is
  a found defect, recorded and fixed under `openspec/README.md`'s rule on defects found
  during a change (D6). Verify: unit tests in `scripts/tests/test_check_uv_version.py`
  and `test_uv_project.py` show `lock` and `reinit` refusing an older uv before
  running it, naming both versions; `make lock` and `make review-locks` both reach the
  check.
  Done: `MINIMUM = (0, 12, 22)`, its docstring covering both directions and naming
  every lock writer; the seven `setup-uv` pins in `tests.yml` and `e2e.yml` at
  0.12.22. `uv_project.main` takes the check as `uv_problem` and runs it before `lock`
  and `reinit` build any command; `image` and `install-wheel` install a committed lock
  and skip it. The check is imported inside `_installed_uv_problem`, with its reason
  beside it: the image Dockerfiles copy `scripts/uv_project.py` alone to run `image`
  and `install-wheel`, so a module-level import of `check_uv_version` would break every
  image build. Tests: `test_check_uv_version.py` (unit) — the minimum is 0.12.22;
  0.12.22, 0.12.24, 0.13.0 and 1.0.0 pass; 0.12.21, 0.12.19 and 0.11.17 refused
  naming both versions. `test_uv_project.py` (unit, injected runner and check) — `lock`
  and `reinit` refused naming both versions, nothing run; `image` and `install-wheel`
  unchecked; the default check is `check_uv_version.problem`, looked up when called;
  the existing cases inject a passing check. Integration, a real `make -n` over the
  real Makefile: `make -n lock` and `make -n review-locks` both run
  `scripts/uv_project.py lock`, and `make lock` runs `check_uv_version.py` before it
  (`test_every_make_target_that_relocks_goes_through_the_guarded_command`). The guard
  covers the repository's relock and environment refresh, not every lock writer: a
  package's plain `uv run`, which relocks a changed project, is unguarded, and the
  revision check (4.3) catches what it writes; the docstrings and
  `BUILD_AND_PACKAGING.md` say so. Other uv installs: `install.sh` pins uv 0.8.13 and
  runs `uv sync` only in its own install copy, never a checkout; uv 0.8.13 reads a
  revision-5 lock under `--locked` and leaves it unchanged on a plain `sync` (both run
  here); the release workflows and `validate-model-release.yml` (0.8.13) build, run,
  or `uv pip install` without relocking; `scripts/bootstrap-clean-host-ubuntu.sh`
  installs the latest uv. Found defect, fixed here (D6), from the fresh-context check:
  the root `Makefile`'s `init-prerequisites` and `core/registry/Makefile`'s `init-uv`
  install uv 0.8.13 where none is installed, and the `reinit` that `init` runs next
  would refuse it; both now install 0.12.22.
- [x] 4.3 Add the lock-revision check to `scripts/check_locks.py`: every committed
  `uv.lock` carries revision 5, and one carrying another fails, naming the lock and
  both revisions (D24 item 7). Verify: unit tests in `scripts/tests/test_check_locks.py`
  for a lock at the expected revision, one at 3, and one at a revision above 5.
  Done: a fourth axis in `check_locks.lock_problems`: `LOCK_REVISION = 5`, and a lock
  carrying another, or none, fails as `<project>/uv.lock: lock revision <found>, but
  the repository's locks carry revision 5 …` (`no lock revision` when it has none).
  Tests, `test_check_locks.py` (temporary trees, injected lock check): the fixture's
  locks now carry revision 5, so every existing case is a lock at the expected
  revision passing; revisions 3, 6 and none each fail naming the lock and both
  revisions; and, over the real repository tree, no committed lock reports a revision
  problem (a lock that cannot be read at all is `check-locks`' to report, not this
  test's). `test_check_locks_uv.py` (integration: the real uv), whose locks the real uv
  writes, now skips unless the installed uv meets the minimum, since an older uv writes
  revision 3 by design; on this machine (uv 0.12.19) its four cases skip, and CI's
  0.12.22 runs them.
- [x] 4.4 Relock the eight locks at revision 3 with the new minimum uv, changing
  nothing but what the relock writes, and update
  `docs/development/BUILD_AND_PACKAGING.md`'s uv minimum, the lock-revision check, and
  drift in both directions (D24 item 7). Verify: `git grep -l "^revision = 3" --
  '*uv.lock'` prints nothing; `make check-locks` passes.
  Done: none of the eight locks resolves anything from the wheelhouse, so `make lock`
  passes uv no `--upgrade-package` for them, and uv, finding nothing changed, leaves a
  lock at its revision: that is why exactly these eight stayed at 3. Each was relocked
  with `uvx --from uv==0.12.22 uv lock --directory <project> --upgrade-package <its own
  distribution>`, which forces the rewrite and moves no dependency. Seven change only
  `revision = 3` → `5`; `kit/identity/uv.lock` also drops a redundant
  `python_full_version < '3.13'` marker on exceptiongroup's typing-extensions
  dependency, as the 53 revision-5 locks already write it (`kit/policy/uv.lock`).
  `BUILD_AND_PACKAGING.md`, "Locks": the 0.12.22 minimum and revision 5, drift in both
  directions, the guard in every lock writer, the revision check, CI's pin, a minimum
  rather than a pin, and how to bring one lock to the running uv's revision; the
  `check-locks` row of its checks table gains the revision. `git grep -l "^revision =
  3" -- '*uv.lock'` prints nothing; `make check-packaging` passes, `check-locks` among
  it.
- [x] 4.5 Verification: `pytest -q scripts/tests/test_check_locks.py
  scripts/tests/test_check_locks_uv.py scripts/tests/test_check_uv_version.py
  scripts/tests/test_uv_project.py scripts/tests/test_tests_workflow.py` (unit)
  passes; `make check-packaging` passes; `make test` passes.
  End-to-end: the pipeline's run of the commit shows `e2e.yml` installing the new uv
  and the stack building and passing its scenarios; no scenario exercises the checks
  themselves.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
  `astral-sh/setup-uv` installs the new minimum release, and `make
  test-deployment-packaging` passes with the lock-revision tests in it.
  Done: the five suites (unit, with `test_check_locks_uv.py` and the `make -n` case
  integration), 61 passed and 4 skipped (`test_check_locks_uv.py`, below the minimum
  here); `make check-packaging` passes; `make test-release-tooling` 2018 passed, 4
  skipped. `make check-change` fails only on the citations sections 5 and 8 create. `make test` was not run: its subprojects' `make reinit` now
  refuses this machine's uv 0.12.19, which is the guard working; it runs once the
  machine has uv 0.12.22 or newer. End-to-end confirmed as planned: the pipeline's run
  is evidence that 0.12.22 builds and runs the stack; no scenario exercises the checks.
  Owed by validation, beside the line above: in the same job, the four cases of
  `scripts/tests/test_check_locks_uv.py` run and pass rather than skip.
  Correction, after the commit: the owner installed uv 0.12.22 on this machine, and
  `make test-release-tooling` then ran those four cases and passed them, 2035 passed
  and none skipped; `make test` ran too (see the section 5 note).
  Handoff: every machine running the workflow's steps now needs uv 0.12.22 or newer
  before `make lock`, `make init` or `make test`. `make lock` still passes no
  `--upgrade-package` for a lock naming no internal package, so a future rise of the
  minimum leaves such locks at the old revision; the revision check then names them,
  and `BUILD_AND_PACKAGING.md` says how to relock one.

## 5. Private keys and provider credentials are refused through gitleaks, and an audit reports every rule (D24 item 4, D25–D30)

Delivers a pinned gitleaks beside `check_public_content.py` wherever that runs, its
gate the default rules minus four with the repository's key rule, and a hand-run audit
of every rule over the tracked tree; and replaces the credential the gate run found.
Implements D24 item 4, D25, D26, D27, D28, D29 and D30, and the delta requirement's
public-content and audit clauses with its scenarios "A key fixture carries no key
material", "Two key fixtures share a file", "A key is added in a merge resolution", "A
real key is staged", "A key is embedded as one escaped string", "A provider token is
staged", "A development fixture is added", and "The audit reports what the gate
passes". Touches `domains/vms/provisioning/iac/README.md`, `.gitleaks.toml`, a new
`scripts/gitleaks-audit.toml`, `scripts/check_secrets.py` and
`scripts/tests/test_check_secrets.py`, `scripts/hooks/pre-commit`,
`scripts/hooks/pre-push`, the guarded push (`scripts/change_workflow/push.py`) and its tests, the `Makefile`'s
`check-public-content` and new `check-secrets` and `audit-secrets` targets,
`.github/workflows/public-content.yml`, `.github/workflows/tests.yml`,
`docs/development/ARCHITECTURE.md`, "Public repository content checks", and
`docs/development/RELEASING.md`, "Cutting a release".

Prepared before the section, on the owner's direction of 2026-11-05: installing
gitleaks is one runnable step, a missing gitleaks names that step rather than leaving
its user guessing, and CI installs it the same way. Done in the session that
implemented sections 6 and 4, before this section's session starts:

- `scripts/gitleaks-pins.toml` pins **gitleaks 8.30.1** with each common platform's
  archive URL and sha256 (linux x64 and arm64, darwin x64 and arm64), in the shape
  of `tools/frp-grant-admission/frp-pins.toml`. The owner installed 8.30.1 on this
  machine (`/usr/local/bin/gitleaks`); its linux_x64 archive matched the release's
  published sha256. The other three hashes are copied from that checksums file, and
  nobody has downloaded and hashed those archives; the pins file says so. The
  release is the candidate 5.1's gate tries; if the gate fails on it, the change
  returns to design as 5.1 says, and a different release changes the pins file.
- `scripts/install_gitleaks.py`, run as `make install-gitleaks
  [GITLEAKS_INSTALL_DIR=<dir>]`: downloads the running platform's archive, refuses it
  unless its sha256 is the pinned one, and installs the binary into `~/.local/bin`
  by default, needing no root; it does nothing when the pinned release is already on
  PATH, and fails, naming the cause, when what it installed is not the `gitleaks` on
  PATH (the directory is missing from PATH, or another gitleaks comes first), so a
  rerun is not left looping. Its `problem()` returns `None`
  when the pinned gitleaks is on PATH, else a message naming the release required,
  what was found, and `make install-gitleaks`. 5.2's `check_secrets.py` refuses a
  missing or other release with that message, and imports nothing else for it.
- `tests.yml`'s `test-deployment-packaging` job and `public-content.yml` put
  `$HOME/.local/bin` first on PATH, run `make install-gitleaks
  GITLEAKS_INSTALL_DIR="$HOME/.local/bin"`, and add that directory to `$GITHUB_PATH`
  for the steps after; 5.3 adds the scan that uses it, and the checksum check 5.3
  asks for is the installer's. Until then `public-content.yml` downloads gitleaks on
  every push without using it, and fails if github.com is unreachable.
- Tests, `scripts/tests/test_install_gitleaks.py` (unit, injected download, version
  and PATH lookup, temporary directories; plus one integration case, a real `make
  -n` over the Makefile): the repository's pins file; platform names; a matching
  archive installs an executable binary and nothing else; another checksum refused
  with nothing installed; an archive without the binary refused; an unpinned platform
  refused before any download; a missing or other release reported naming `make
  install-gitleaks`; the pinned release on PATH not reinstalled; an install
  confirmed as the `gitleaks` on PATH, and one shadowed by another gitleaks or off
  PATH failing; a refused archive failing the command; and the target passing
  `GITLEAKS_INSTALL_DIR` as `--dir`. No real download is exercised here, since the
  implement step may not run `make install-gitleaks`. `public-content.yml` runs the
  real install on every push of the branch; `tests.yml` runs it only when dispatched
  or on pushes and pull requests to `dev` and `staging`, hence the line owed below.
  Checks: `test_install_gitleaks.py` 17 passed; `make test-release-tooling` 2035
  passed; `make check-change` fails only on the citations sections 5 and 8 create; and
  `make test`, its first full run in this session now that the machine has uv
  0.12.22, passed and rewrote no lock.
- For the section's session: run gitleaks only through make targets, as the owner
  directs: `make check-secrets` (5.2, beside `check-public-content`) and `make
  install-gitleaks`. `docs/development/ARCHITECTURE.md`'s install instructions (5.4)
  name `make install-gitleaks`. Owed by validation once 5.3 lands, as 5.5 says:
  `tests.yml`, job `test · test-deployment-packaging`, shows "Install the pinned
  gitleaks" passing. `public-content.yml` runs on every push, and no dispatch is owed
  for it.

Replanned against the reviewed design (D25–D30, design review 55), 2026-11-05: tasks
5.1–5.6 below replace the earlier unchecked 5.1–5.5, none of which was checked. The
prepared notes before them and the gate-run notes after them name the earlier numbers: the earlier 5.1 is now 5.2, 5.2 is
5.3, 5.3 is 5.4, 5.4 is 5.5, and 5.5 is 5.6; `make check-secrets`, which the prepared notes above give
to 5.2, is 5.4's. The work those notes record as committed stands and is built on, not
redone.

- [x] 5.1 The README's credential (D25): in `domains/vms/provisioning/iac/README.md`,
  "Configure Build Variables (Optional)", replace the `root_password` and
  `root_filename` values the heredoc writes with `<the existing key's password>` and
  `<its filename>`, as the section's first commit. Record in the notes that the fix is
  outside the change's stated scope, a found defect fixed in place (D6), and that no
  customer image was built with the value, so nothing is rotated. Verify: the two
  lines hold placeholders, and 5.6's audit reports no finding in that file.
  Done, as the section's first commit (`da72f3841`, not yet pushed): the two lines
  read `root_password: <the existing key's password>` and `root_filename: <its
  filename>`. The fix lies outside the change's stated scope: a small, understood
  defect the secret scan's first run found, fixed in place (D6). No customer image
  was built with the value, so nothing is rotated; the value stays in public history.
  On the resume, `make audit-secrets` at `9e5c10cfc` reported no finding in the file.
- [x] 5.2 The gate and audit configurations, confirmed (D24 item 4, D26, D28, D29):
  move the current `.gitleaks.toml`'s content — `useDefault = true`, `disabledRules =
  ["private-key"]`, and the `private-key-block` rule as committed — into a new
  `scripts/gitleaks-audit.toml`, and make `.gitleaks.toml` the gate, extending it by
  `path = "scripts/gitleaks-audit.toml"` with `disabledRules = ["generic-api-key",
  "jwt", "curl-auth-header"]`; each file's comments say what it is for, and the gate's
  say why each of its rules is off, as D26 gives the reasons. Confirm with the pinned
  8.30.1, run from the repository root as `check_secrets.py` runs it, that the gate
  loads the nested extension: the gate's scans report keys as `private-key-block` and
  nothing from the four rules it turns off, and the audit's scan of the tree reports
  `generic-api-key`, `jwt` and `curl-auth-header` findings. If the nested extension does
  not load, make the two files self-contained, the key rule written in both, with a
  unit test asserting the two rules are identical (D29's settled fallback, not a return
  to design). Restore the tree test's assertion to `found == []` under the gate
  configuration, any rule counted (D28). Record in the notes the release, its
  checksum, whether the nested extension loaded, and the tree scan's counts under each
  configuration: none under the gate; under the audit, the 113 findings D26 describes
  once 5.1 has removed the README's. The key cases the gate-run notes record are
  rerun by 5.3's suite under the gate configuration. If a key case fails or the gate
  finds anything in the tree, stop: the change returns to design (`change-implement`,
  "Stop cleanly when the plan is wrong").
  Done: `scripts/gitleaks-audit.toml` holds the committed key rule over the defaults
  minus `private-key`; `.gitleaks.toml` extends it by path and turns off the three,
  its comments giving D26's reasons. Release 8.30.1, linux_x64 sha256
  `551f6fc8…70eb` (`scripts/gitleaks-pins.toml`). **The nested extension loads**, from
  the repository root: `check_secrets.py` now runs gitleaks with the repository root as
  its working directory whatever repository it scans, the scanned repository passed as
  gitleaks' source argument, since gitleaks resolves `[extend] path` from its working
  directory (`test_every_scan_runs_from_the_repository_root_where_the_gate_finds_the_audit`:
  staged, range, pre-push and audit scans, injected runner). Evidence, each a
  real-gitleaks case of 5.3's suite under the gate: every key case refuses as
  `private-key-block`, which reaches the gate only through the extension;
  `test_a_provider_token_is_staged` refuses a GitHub token, a default rule reaching the
  gate through both levels; `test_a_development_fixture_is_added` passes lines of which
  the audit reports at least one as `generic-api-key`, so that rule is off at the gate
  and on in the audit; and `test_the_repositorys_own_tree_passes_the_gate`, now
  asserting `found == []` under any rule (D28), passes over `HEAD`'s tree. That run's
  `HEAD` was `da72f3841`, so the tree it scanned held none of this section's other
  files; those passed the gate as staged additions (`make check-secrets`), and the
  test reads them once they are committed. The fallback was not needed. Counts: none
  under the gate. Under the audit, `make audit-secrets` at `9e5c10cfc` (before this
  section's other files were committed): 116 findings, `generic-api-key` 76, `jwt` 38,
  `curl-auth-header` 2. That is D26's 113 once the README's is gone, plus three lines
  this change's own `design.md`, delta `spec.md` and `tasks.md` gained after the gate
  run, each citing `private_key: Ed25519PrivateKey`.
- [x] 5.3 The gate's provider-format cases and the audit in `scripts/check_secrets.py`
  (D26, D27, D28, D29): add `--audit`, which runs the pinned gitleaks with
  `scripts/gitleaks-audit.toml` and redaction over `HEAD`'s tracked tree, read as the
  tree test reads it — one parentless commit of `HEAD^{tree}` in a temporary shared
  clone, with a fixed author and committer in that clone's environment, the helper
  shared by the test and the audit — so untracked and ignored files are never scanned;
  it prints each finding as `<file>:<line>: <rule>` without its content, exits 0 when
  the scan ran whatever it found, and exits non-zero only when gitleaks could not run
  or another release is installed. It keeps no baseline (D9). Verify, in
  `scripts/tests/test_check_secrets.py`: unit cases with the injected runner showing
  `--audit` passes the audit configuration and the tree source and exits 0 with
  findings, and an unfinished audit is an error; library integration cases against the
  real release for "A provider token is staged" (a GitHub personal access token built
  at runtime, as the key cases assemble their headers, refused naming file and line
  without echoing it), "A development fixture is added" (one of Anvil's published
  keys, a contract address, and `private_key: Ed25519PrivateKey`, added and passed),
  and "The audit reports what the gate passes" (a random 40-character password built
  at runtime, reported by the audit, which exits 0, and passed by the gate); the
  existing ten cases run under the gate configuration, each key scenario mapping to
  one.
  Done: `--audit`, `audit()`, and the shared helper `tree_commit()` (a `--shared
  --no-checkout` clone, `commit-tree --no-gpg-sign` of `HEAD^{tree}` under a fixed
  identity), used by the tree test too; findings print as `<file>:<line>: <rule>`,
  then a count line; exit 0 whatever it found, 1 with `ERROR:` when gitleaks could not
  run or another release is installed. `scan_source` takes the configuration, the gate
  by default. Tests, `test_check_secrets.py`, 28 passed, none skipped. With gitleaks
  injected (a recording runner and version check) over real temporary Git
  repositories, as the file's earlier cases are: `--audit` passes
  `scripts/gitleaks-audit.toml`, scans the temporary clone rather than the repository,
  with `--log-opts` ending `--root --diff-merges=separate`, and exits 0 printing
  `settings.yaml:1: generic-api-key`; the tree commit is parentless, holds `HEAD`'s
  tree, and not an untracked file; an audit gitleaks could not finish (exit 2 or 126)
  is an error; another release is an error and runs nothing; every scan runs from the
  repository root. Integration against the real 8.30.1, a real external process
  (`TESTING.md`'s third flavour, skipped without the binary and failing under
  `GITLEAKS_REQUIRED=1`; the plan's "library integration" names these): "A provider
  token is staged" (`test_a_provider_token_is_staged`: `ghp_` and 36 random characters,
  refused at `deploy.env:2`, not echoed); "A development fixture is added"
  (`test_a_development_fixture_is_added`: Anvil's first key, its first contract
  address, and `private_key: Ed25519PrivateKey`, passed by the gate, while the audit of
  the same lines reports at least one as `generic-api-key`; `check_public_content.py`
  is not run on them, the scenario's gitleaks half being this section's); "The audit
  reports what the gate passes"
  (`test_the_audit_reports_what_the_gate_passes`: a random 40-character
  `root_password`, reported by `main(["--audit"])`, which exits 0, without echoing it,
  and passed by the gate's range scan). The existing ten real-scanner cases run under
  the gate, and map to the key scenarios: "A key fixture carries no key material",
  "Two key fixtures share a file", "A real key is staged" (wrapped at 64 and 16), "A
  key is embedded as one escaped string", "A key is added in a merge resolution".
- [x] 5.4 Run the gate wherever `check_public_content.py` runs (D24 item 4):
  `scripts/hooks/pre-commit` on staged additions and `scripts/hooks/pre-push` on each
  pushed ref's commits, each running both checks and failing when either does;
  the guarded push (`scripts/change_workflow/push.py`) on every outgoing commit; `make check-public-content`,
  running both; a new `make check-secrets` running the gate over staged additions, and
  a new `make audit-secrets` running `--audit`; `.github/workflows/public-content.yml`
  on every commit since its base; and `tests.yml`'s `test-deployment-packaging` job
  setting `GITLEAKS_REQUIRED=1` where it runs the script suites, so a skipped
  real-scanner case fails. Verify: unit tests in `scripts/tests/test_check_push_ready.py`
  show the guarded push refusing an outgoing commit that adds a key and passing one
  that adds a fixture; `python3 scripts/check_secrets.py --base origin/dev`, the
  workflow's own command, passes over this branch's commits.
  Done: both hooks run both checks and exit non-zero when either fails, each check
  reporting even after the other refused; the pre-push hook reads Git's ref updates
  once and gives them to each. `check_push_ready.main` scans the outgoing commits with
  the gate after `check_public_content`, a gate that cannot run refusing the push; the
  gate is injected (`secrets=`) so the push tests about other states pass a scan that
  finds nothing. `make check-public-content` runs both; `make check-secrets` and `make
  audit-secrets` are new. `public-content.yml` runs both over the same base;
  `tests.yml` sets `GITLEAKS_REQUIRED=1` on the `make` step of the
  `test-deployment-packaging` job only, the one that installs gitleaks and runs the
  script suites. Tests, `test_check_push_ready.py` (real Git repositories and a bare
  remote; 15 passed): `test_an_outgoing_commit_adding_a_key_refuses_publication` and
  `test_an_outgoing_commit_adding_a_key_fixture_is_pushed` (integration, the real
  gitleaks as an external process, through the guard's real push; the plan asked for
  unit tests, and the real scanner is the level that proves a refusal); a gate that
  cannot run refusing the push (injected). `test_tests_workflow.py` passes. The hooks have no test, as before;
  `make check-public-content` and `make check-secrets` passed over this section's
  staged files. On the resume, `python3 scripts/check_secrets.py --base origin/dev`
  passed over the branch's commits to `9e5c10cfc`; the section's own commit is scanned
  by `make push-branch`'s outgoing check.
- [x] 5.5 Documentation (D24 item 4, D26, D28, D29): `docs/development/ARCHITECTURE.md`,
  "Public repository content checks", records gitleaks and its pinned release, how to
  install it (`make install-gitleaks`), why the repository replaces the default key
  rule, the three default rules the gate turns off and why, the tree test as the guard
  on a gitleaks upgrade, the audit and how to run it, and the two things the gate
  cannot see — an edit beneath an unchanged key header, and a random credential in no
  provider's format — review remaining the safeguard for both.
  `docs/development/RELEASING.md`, "Cutting a release", gains the step: run `make
  audit-secrets` and read what it reports before an official build ships. Verify:
  `make check-doc-citations CHANGE=act-on-owner-intervention-patterns` reports no path
  this section added that fails to resolve.
  Done: `ARCHITECTURE.md`, "Public repository content checks", says the two checks run
  together and where, the hooks now needing Python 3.11 (`install_gitleaks` reads
  `tomllib`) and the pinned gitleaks; a new "Secret scanning through gitleaks" covers
  the scanner and its pin, `make install-gitleaks`, redaction and ignored
  `gitleaks:allow`, merge patches, the gate's four rules off and why, the tree test as
  the guard on an upgrade, the audit, and the two things the gate cannot see.
  `RELEASING.md`, "Cutting a release", gains its first step, `make audit-secrets`.
  `make check-doc-citations` (through `make check-change`) reports only section 8's
  skill, cited by `proposal.md` and `tasks.md`.
- [x] 5.6 Verification: `pytest -q scripts/tests/test_check_secrets.py
  scripts/tests/test_check_public_content.py scripts/tests/test_check_push_ready.py`
  (unit and library integration) passes with `GITLEAKS_REQUIRED=1`; `make
  check-public-content` and `make check-secrets` pass; `make audit-secrets` exits 0
  listing the audit's findings, none in `domains/vms/provisioning/iac/README.md`; `make
  test` passes. End-to-end: none; no scenario exercises the public-content checks.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — it
  installs the pinned gitleaks with its checksum checked, and the real-scanner cases in
  `scripts/tests/test_check_secrets.py` run and pass rather than being skipped.
  So far: the three suites, 62 passed with none skipped (`pytest -rs`; with the pinned
  release on PATH `GITLEAKS_REQUIRED=1` changes nothing, and the session could not set
  it on the command line); `make check-public-content` and `make check-secrets` pass
  over the section's staged files; `make test` passes, its `test-release-tooling`
  2070 passed and none skipped, rewriting no lock; `make check-packaging` passes;
  `make check-change` fails only on section 8's skill citation. End-to-end confirmed:
  none. Owed by validation confirmed as written above, the gitleaks cases of
  `test_check_push_ready.py` among the real-scanner cases that must run there.
  On the resume, `make audit-secrets` exited 0 listing 116 findings, none in
  `domains/vms/provisioning/iac/README.md` (5.2 gives the counts).

Stopped, 2026-11-05, before committing: the session may not run `make audit-secrets`,
`python3 scripts/check_secrets.py --audit`, or `python3 scripts/check_secrets.py
--base origin/dev` (no rule of the implement step allows them), and four checks need
them: 5.1's "no finding in the README", 5.2's audit count and its `jwt` and
`curl-auth-header` findings over the tree, 5.4's scan of the branch since `dev`, and
5.6's audit. Everything else is done and staged, uncommitted, but for 5.1's commit,
`da72f3841`, made first as 5.1 asks and not yet pushed. For the resumed session: run
the three commands; record the audit's count and the rules it names, and check that
none is in `domains/vms/provisioning/iac/README.md` (the placeholders hold no value;
if the audit still reports the file, read the line it names before checking 5.1);
check 5.1, 5.2, 5.4 and 5.6 if they pass; then commit the rest as the
section's second commit and push both with `make push-branch`, which now runs the gate
over the outgoing commits too. The audit reads `HEAD`, so run it after that commit
for the counts to include this section's files, or before it for the tree D26
measured; the notes should say which. If `--base origin/dev` refuses an earlier
commit of the branch, that is a found defect in a committed file, fixed in this
section (D6), since the Public content workflow scans a pull request's commits from
its base and would refuse the branch's.
Resumed, the same day: the owner added `make audit-secrets` and `python3
scripts/check_secrets.py *` to every step's rules (`9e5c10cfc`, committed by the
orchestrator), and confirmed that running the real-scanner cases through pytest is
acceptable. The audit ran before the section's commit, so its counts are D26's tree;
both commands passed as 5.1–5.6 record, and the section was committed and pushed.

Gate run, 2026-11-05: the key rule holds, and the change returns to design over
gitleaks' other default rules. No task above is checked.

- Done, committed as work in progress: `.gitleaks.toml` (extends the default
  configuration, `disabledRules = ["private-key"]`, adds `private-key-block`, the
  design's regex made case-insensitive and admitting PGP's `PRIVATE KEY BLOCK`);
  `scripts/check_secrets.py` (`--staged`, `--base`, `--outgoing REMOTE`, `--pre-push
  REMOTE`; ranges with `--diff-merges=separate`; `--redact`; `--ignore-gitleaks-allow`,
  since D24 rejects per-fixture `gitleaks:allow` markers and D9 exception markers; a
  missing or other release refused through `install_gitleaks.problem()`; findings as
  `[<commit>:]<file>:<line>: <rule>`, gitleaks' failure an error rather than a pass);
  `scripts/tests/test_check_secrets.py`, 19 passed: 9 unit cases (injected runner and
  version check: the staged and range arguments, the outgoing range's exclusions, the
  pre-push ref updates and a deletion skipped, the version refusal naming both releases
  and running nothing, a finding reported without its content, an unfinished scan an
  error, three ways) and 10 library integration cases against the real gitleaks over
  temporary repositories and the repository's own tree (skipped without the pinned release unless `GITLEAKS_REQUIRED=1`, which
  fails them instead and which 5.3 is to set in `tests.yml`). Nothing is wired in: the
  hooks, the guarded push, `make check-public-content`, the workflow, and the
  `make check-secrets` target are 5.3's, and `ARCHITECTURE.md` is 5.4's.
- Gate results, gitleaks 8.30.1 (`scripts/gitleaks-pins.toml`, linux_x64 sha256
  `551f6fc8…70eb`), each a test in that suite: the extending configuration turns the
  default `private-key` rule off and runs the repository's rule (keys are reported as
  `private-key-block`, and no `private-key` finding appears anywhere, though the tree's
  two fixtures in `test_hosts_api.py` are what the default rule joins); the
  repository's tree, scanned as one parentless commit of `HEAD`'s tree, has no key-rule
  finding; two fixtures in one file pass, staged and committed; a key wrapped at 64 and
  at 16 characters is refused naming its file and the header's line, its body not
  echoed; a key as one escaped string is refused; a fixture before a real key does not
  hide it; a key marked `gitleaks:allow` is refused; a key an intermediate commit adds
  and a later one deletes is refused naming the adding commit; a key written only in a
  merge resolution is refused naming the merge, and the same range scanned without
  `--diff-merges=separate` does not find it. Every condition 5.1 names for the key
  rule is met.
- Why the change returns: D24 item 4 keeps every other default rule ("the scan modes,
  the redaction, and every other rule stay gitleaks'"), and the same tree scan under
  them reports 114 findings in 47 tracked files: `generic-api-key` 74, `jwt` 38,
  `curl-auth-header` 2. They are the repository's own development fixtures: the
  `dev-env/identities/` and `dev-env/bare-metal/` identity files, the Anvil address
  files under `helm/charts/dev-env/files/`, `e2e-tests/config/`, the storefronts'
  `.env.*.docker` files, test fixtures under `domains/`, `kit/` and `provisioning/`,
  the JWTs of `tools/frp-grant-admission/vector/frp-grant-1.json`, and examples in
  `docs/`. Wired in as designed, the hook, the guarded push and CI would refuse any
  added line of those shapes: a new or moved fixture, and a merge of `dev` whose
  patch against its first parent carries one, since merges are compared with each
  parent. That is 5.1's "a fixture is refused", for fixtures the design did not
  consider, and the design decides nothing about them.
- Options for design. (A) Run the repository's key rule alone, `useDefault = false`:
  exactly what the delta requirement asks, no exceptions, and none of gitleaks'
  provider-token rules, which the repository has never had. (B) Keep the default
  rules but also disable the three that fire on the tree: measured here (the
  configuration edited and the tree scanned with every finding counted, then put
  back), the tree has no finding at all and every key case still passes; gitleaks'
  provider-specific rules stay, with no exception markers, and a later fixture that
  trips one is a rule-list edit. (C) Keep every rule and allowlist the fixtures by path
  or value: an exception list, which D9 and 38 F1's reasoning reject. (D) Keep every
  rule and rewrite the 47 files' fixtures to assemble at runtime: the churn 20 F4
  rejected. Recommendation: B, which keeps the scanner's value beyond keys at no cost
  on the current tree; A if the owner wants the check to claim no more than the
  requirement states.
- For the next session: once design settles this, edit `disabledRules` (or
  `useDefault`), restore the tree test's assertion to `found == []` if the tree is
  then clean, and continue with 5.1's record and 5.2–5.5 from the work above.
  Correction: design settled this as D25–D30 (B, with the audit); the replanned tasks
  5.1–5.6 above stand in for this paragraph.
- Round 1 triage fixes (65 O1, 65 O3, 65 O4):
  - 65 O3: `docs/development/ARCHITECTURE.md`'s "Secret scanning through gitleaks"
    subsection is now one paragraph under "Public repository content checks" — the
    pinned release and its install, the gate, the audit — linking to a new "Secret
    scanning" section of `change-workflow`'s companion, which the merge of dev moved to
    `openspec/specs/market-change-workflow/README.md`, and which holds
    the key rule, why the provider rules stay, the tree test, the audit and the gate's
    blind spots, and points to `.gitleaks.toml` for the disabled rules' reasons.
    `.gitleaks.toml`, `scripts/gitleaks-audit.toml` and `scripts/check_secrets.py`
    point there; the proposal's destinations for D24 item 4, D26, D28 and D29, its
    impact list, and 11.9 follow.
  - 65 O1: the root `Makefile`'s three scattered `.PHONY` lines
    (`check-public-content check-secrets audit-secrets`, `test-bare-metal-iac`,
    `test-bare-metal-iac-native`) are in the top block.
  - 65 O4: "Cutting a release" step 1 in `docs/development/RELEASING.md` is a
    three-line instruction; its explanation and link follow the list.
  - Evidence: as section 1's round 1 note records; the documentation links resolve.

## 6. A change's closing checks enforce five more written rules (D24 items 1, 2, 3, 5, 6)

Delivers the destination, history-wording, version-bump, local-import, and
capability-index checks in `make check-change`, and the missing index row. Implements
D24 items 1, 2, 3, 5, and 6 and the delta requirement "A change's closing checks
enforce written rules" with its scenarios "A decision names no destination", "A
comment describes history", "A package is bumped twice", "A larger bump replaces a
smaller one", "A local import has no reason", and "A capability has no index row".
Touches `scripts/check_change.py`, new check scripts under `scripts/` with their tests
under `scripts/tests/`, and `openspec/specs/README.md`.

- [x] 6.1 Destinations (D24 item 1): each `### D<n>` heading under `design.md`'s
  `## Decisions`, outside fenced code blocks, has a bullet starting `D<n>` in
  `proposal.md`'s "Knowledge to promote"; a design with no such heading passes,
  reported as not checked. Run it over every active change and record in this
  section's notes the changes it fails, for their own next step to fix. Verify: unit
  tests for a missing bullet named, a `D<n>: no permanent destination — <reason>`
  bullet passing, a heading inside a fenced block ignored, and this change's own
  design and proposal passing.
  Done: `scripts/check_decision_destinations.py`, `make check-decision-destinations
  CHANGE=<change>`. Only a level-2 `## Decisions` is read, and, as in CommonMark, a
  fence closes only on a bare run of its own character at its opening's length or
  longer. Tests, `test_check_decision_destinations.py`: decisions read only from
  `## Decisions` outside fences (a `### Decisions` elsewhere, a fence, a line opening
  another fence inside one, and a longer fence holding a shorter one ignored) (unit);
  through `main()` over a change directory in a temporary tree (library integration):
  every decision named passes, the `no permanent destination` form among them; a
  missing bullet named; a bullet must start with the decision (`per D2` and `D20` do
  not name D2); a design with no headings not checked. This change's
  own pair is a run, not a test, since code may not name a change
  (`check-comment-hygiene`): `make check-decision-destinations
  CHANGE=act-on-owner-intervention-patterns` passes, 24 decisions. Over every active
  change, 12 designs carry `### D<n>` headings; two pass
  (`activate-compute-leases-at-the-site`, and this one), and ten fail, for their own
  next step to fix: `spot-deals-through-arkhai-payments` (D1–D8),
  `lapse-billing-with-the-site-lease` (D1–D4), `publish-wheels-through-a-gate`
  (D1–D6), `renewable-compute-lease-deadlines` (D2, D4: its `D1–D2` range bullet names
  only D1), `unify-compute-delivery-path` (D1–D7), `negotiate-open-ended-compute-terms`
  (D1–D8), `add-arkhai-payments-lane-double` (D1–D7),
  `activate-per-period-compute-servicing` (D1–D4),
  `discover-open-ended-compute-listings` (D1–D4), and
  `converge-ongoing-compute-leases` (D1–D7). The rest write decisions as bullets and
  are not checked.
- [x] 6.2 History wording (D24 item 2): a comment or docstring line the change's diff
  from its merge-base adds in a `.py`, `.toml`, `.yml` or `.yaml` file fails on
  "previously", "formerly", "used to", "no longer", "moved from", "was renamed" or
  "originally", naming the file and line, with no exception marker. Verify: unit tests
  for each word, for "now" and "legacy" passing, for a matching word in code rather
  than a comment passing, and library integration tests over a temporary Git
  repository showing only added lines are read.
  Done: `scripts/check_history_wording.py`, `make check-history-wording`, over the
  shared `scripts/change_diff.py`, which reads the lines the diff from the merge-base
  adds in the working tree, uncommitted edits and untracked files included, since a
  step runs its checks before committing. Python comments come from `tokenize`,
  docstrings (module, class, function) from `ast`; a `.toml`/`.yml`/`.yaml` comment is
  a `#` after whitespace outside a quoted value. A Python file that does not parse is
  named, not a traceback. Tests, `test_check_history_wording.py`: each listed phrase in
  an added comment fails and "now" and "legacy" pass, through `problems()` over a real
  repository (library integration); a phrase in code or a string value is not a
  comment, every line of a docstring is read, and the TOML/YAML comment rule's cases,
  escaped quotes among them (unit); only added lines are read, across `.py`, `.yml` and
  `pyproject.toml`, `.md` ignored (library integration); the command fails naming file
  and line, then passes once reworded; an unparsable file; an unknown base.
  `test_change_diff.py` (library integration, real Git): only added lines, uncommitted
  and untracked included; dev's commits merged into the branch are not the change's;
  the branch found on a remote; of two copies of the branch, the newer read when the
  local one lags; an added line starting `++ `, printed `+++ ` before a file's second
  hunk, and a path holding a space parsed; the user's `diff.noprefix` and
  `diff.mnemonicPrefix` hiding nothing, the prefixes being fixed; a branch found
  nowhere refused. Outside the plan: run on this branch, the check found
  three comments sections 1 and 3 added saying "no longer" in
  `scripts/change_workflow/harness.py` and `running.py`, reworded here.
- [x] 6.3 One version bump (D24 item 3): each `pyproject.toml` version that differs
  from the merge-base is exactly one SemVer step from it, lower parts reset; a missing
  bump is not checked. Verify: unit tests for 0.4.0 → 0.4.1, 0.5.0 and 1.0.0 passing,
  0.4.0 → 0.4.2 and 0.6.0 failing with the package and both versions, and a package
  bumped 0.4.0 → 0.4.1 → 0.5.0 on the branch passing.
  Done: `scripts/check_version_bumps.py`, `make check-version-bumps`, comparing every
  tracked or untracked `pyproject.toml` with its copy at the merge-base; one absent
  there, or with no `[project].version`, is not checked; a version not
  `MAJOR.MINOR.PATCH` is named. Tests, `test_check_version_bumps.py`: 0.4.0 → 0.4.0,
  0.4.1, 0.5.0, 1.0.0 pass and 0.4.2, 0.6.0, 0.5.1, 2.0.0, 0.3.9 fail naming the
  package and both versions (unit); a pre-release version named (unit); 0.4.0 → 0.4.1
  → 0.5.0 in two commits passes, and a package bumped 0.4.0 → 0.4.2 fails through the
  command, named by distribution and path, beside a new package not checked (library
  integration, real Git).
- [x] 6.4 Local imports (D24 item 5): an import inside a function that the diff adds to
  a `.py` file has a comment on its own line or the line above, else the check names
  the file and line. Verify: unit tests for an added local import with and without a
  reason comment, a module-level import passing, and an unchanged local import not
  read.
  Done: `scripts/check_local_imports.py`, `make check-local-imports`: an import inside
  a function, nested and async functions and methods included, any line of which the
  diff adds, needs a comment ending one of its lines or alone on the line above. Beyond
  the plan, from the fresh-context check: an empty comment, or one made only of tool
  directives (`noqa`, `type: ignore`, `pyright: ignore`, `pylint: disable=`, `pragma:
  no cover`/`no branch`, `fmt:`/`isort:` skip, off or on, one or several), is no
  reason, since the repository has local imports carrying only `# noqa: F401`; a
  directive followed by a reason counts. Tests, `test_check_local_imports.py`: an
  import without a reason named; trailing, above, and multi-line forms pass;
  directives alone refused and a directive with a reason passing; module-level imports
  pass; nested, async and method imports read (unit); an unchanged local import not
  read beside an added one named, and the command failing then passing once a reason
  is given (library integration, real Git).
- [x] 6.5 The capability index (D24 item 6): every `openspec/specs/<capability>/` with a
  `spec.md` has a row in `openspec/specs/README.md` linking it, and every row links one
  that exists; add the `contact-exchange-settlement` row. Verify: unit tests for a
  missing row and a row linking nothing; the check passes on the repository.
  Done: `scripts/check_capability_index.py`, `make check-capability-index`, reading the
  body rows of the `## Capabilities` table (its first two lines are header and
  delimiter): every row links a capability's `spec.md` and no missing file, and every
  capability with a `spec.md` is linked. The `Contact-exchange settlement` row is added
  to `openspec/specs/README.md`, with no architecture companion, which the capability
  has none of. An external link is not resolved. Tests,
  `test_check_capability_index.py` (library integration, over temporary trees and the
  repository's own index): a full index passes; a capability with no row named; a dead
  link named; a row with no link, or linking only a non-spec file, named as linking no
  capability; the repository's index passes.
- [x] 6.6 Run the five checks from `scripts/check_change.py` after its existing ones,
  each named in its failure line, the diff-scoped ones against the merge-base with the
  branch the change lands on, `dev` by default. Verify: `scripts/tests/test_check_change.py`
  lists the new checks in order and reports each failure by name; `make check-change
  CHANGE=act-on-owner-intervention-patterns` runs all of them, failing only on the
  citation of the skill section 8 creates.
  Done: each check is a `make` target `check_change.py` runs, named in its failure
  line; `make check-change CHANGE=<change> [CHANGE_BASE=<branch>]` passes the branch to
  the three diff checks (`--base`, `dev` by default). Tests: `test_check_change.py`
  (unit, injected runner) lists the eleven commands in order, reports each failure by
  name, passes `CHANGE_BASE` through, and takes `--base`; `test_run_change_step.py`'s
  `make -n` case shows the target passing `CHANGE_BASE`. `make check-change` ran all
  eleven, failing only on documentation citations, of the skill section 8 creates and
  of `scripts/check_secrets.py` and its test, which section 5, not yet implemented,
  creates. Outside the plan: `check-comment-hygiene` refuses the file names of a
  change's design and proposal in code, so its exemption, until now only `TASKS_FILE` in
  `change_next_step.py`, became a table that also exempts `DESIGN_FILE` and
  `PROPOSAL_FILE` in `check_decision_destinations.py`; `test_check_comment_hygiene.py`
  covers them, exempt there and caught elsewhere.
- [x] 6.7 Verification: the new checks' suites and `pytest -q
  scripts/tests/test_check_change.py` (unit, and library integration where a temporary
  Git repository is used) pass; `make test` passes. End-to-end: none; no scenario
  exercises the closing checks.
  Done: the eight suites (`test_change_diff`, the five checks', `test_check_change`,
  `test_check_comment_hygiene`), 124 passed; `make test-release-tooling` 2009 passed.
  `make test` was not run: on this machine it runs uv 0.12.19, which rewrites the 53
  revision-5 locks to revision 3 (section 1's handoff), and this session can restore
  them only one Edit at a time; the section touched only `scripts/`, its tests, the
  `Makefile`'s new check targets and `openspec/specs/README.md`, which `make
  test-release-tooling` covers. `make check-comment-hygiene` passes. End-to-end
  confirmed: none.
  Handoff: sections 4 and 5 were given to this session before section 6 and are not
  started: section 4 needs a uv that writes lock revision 5, and the means to run
  other uv releases to find the first one, and section 5 a gitleaks binary; this
  machine has uv 0.12.19 only and no gitleaks, and the step may not download either.
  Section 6 is independent of both. Correction: on the owner's answer the same session
  then implemented section 4, running uv releases through a grant for the run; its
  notes stand in for this paragraph. Section 5 still waits for gitleaks. For section 7: `docs/agents/change-workflow.md`
  should name the five checks and `CHANGE_BASE`, and that the diff checks compare with
  `dev` unless told otherwise, so a change landing on another branch passes
  `CHANGE_BASE`, which no skill does yet; without it, a prerequisite's commits read as
  the change's own.
- Round 1 triage fix (64 F3, the owner chose C): the history-wording check keeps
  reading a `#` line inside a YAML block scalar or a TOML multi-line string as a
  comment, since such blocks here hold embedded shell or configuration whose comments
  the rule covers; its docstring now says so, and
  `test_a_hash_line_in_a_block_scalar_or_multi_line_string_is_read_as_a_comment` (unit,
  over a real Git repository) pins a `run: |` block and a TOML multi-line string.
  `design.md` D24 item 2 records it. Evidence: as section 1's round 1 note records.

## 7. The guidance says what the owner does (D5, D6, D8–D12, D22, D23, D24)

Delivers the guidance edits the skills in sections 9 and 10 cite. Implements D5, D6,
D8, D9, D10, D11, D12, D22's criteria, D23, and D24's description for contributors.
Touches `AGENTS.md`, `issue-tracker.md` and `triage-labels.md` under `docs/agents/`
(deleted), `docs/agents/domain.md`, `openspec/README.md`,
`docs/agents/change-workflow.md`, and `docs/development/ARCHITECTURE.md`.

- [x] 7.1 `AGENTS.md`: replace "Issue tracker" and "Triage labels" with "Deferred
  work" in D5's wording; remove the ADR sentence from "Domain docs" (D23); add "Amend a
  rule or comply" under "Working model" (D9). Delete `issue-tracker.md` and
  `triage-labels.md` under `docs/agents/` with `git rm` (D5). Verify: `git grep -n
  "issue-tracker.md\|triage-labels.md\|docs/adr"` finds no citation outside
  `openspec/changes/`.
  Done: "Deferred work" in D5's wording; "Amend a rule or comply" a `###` of its own
  after "Asking the owner", in D9's wording, the testing levels its example. "Domain
  docs" lost its ADR sentence and, beyond the task's letter, its "Multi-context: one
  platform context over `core/`…" sentence, which described the directory-drawn
  contexts D11 removes from `domain.md`; it now names the three homes and points to
  `domain.md`. Both documents removed with `git rm`. The `git grep` prints nothing.
  Outside the plan: the change's own `design.md`, `proposal.md` and this file cited
  the two deleted paths, which `check-doc-citations` then reported as missing (7.6
  expected only section 8's skill); each now names them as `issue-tracker.md` and
  `triage-labels.md` under `docs/agents/`, a form the check does not read as a path,
  so closeout's scoped check (11.10) passes on them too. No decision's wording
  changed.
- [x] 7.2 Rewrite `docs/agents/domain.md` to name the vocabulary's homes and state the
  rule for terms, without `CONTEXT.md`, `CONTEXT-MAP.md`, `/domain-modeling` or ADRs
  (D11, D23). Verify: the document holds D11's table and rule and none of the removed
  references.
  Done: D11's table, each home linked, "A subsystem's definition wins inside that
  subsystem", and the rule as three bullets, the synonym clause citing
  `ARCHITECTURE.md`'s "One name per concept". `git grep` finds no `CONTEXT.md`,
  `CONTEXT-MAP`, `domain-modeling` or `docs/adr` outside `openspec/changes/`.
- [x] 7.3 `openspec/README.md`: add a "Defects found during a change" section after
  "Plan closeout requirements" in D6's wording, so skills cite a stable heading, and
  replace the scope-creep sentence with D6's (D6). Verify: the section's anchor,
  `openspec/README.md#defects-found-during-a-change`, resolves for the skills of
  sections 9 and 10 to cite.
  Done: `## Defects found during a change` after the promotion record, before
  "Implementation completion checklist", D6's paragraph verbatim with its
  `ARCHITECTURE.md` reference linked; the scope-creep sentence is D6's and links the
  new section. The heading's anchor is `#defects-found-during-a-change`.
- [x] 7.4 `docs/agents/change-workflow.md`: under "Reviews", default acceptance, the
  table and the classification (D1–D3, D17, D18); under "Orchestrating a change",
  interrupting a step and revisiting a default acceptance (D15, D16); a new "Waivers"
  section with D22's criteria; under "The ledger", the revisit marker and recommended
  waivers (D19, D22); under "Skills", notes and proposals across changes, a skill
  restating guidance only to cite it, and the checks `make check-change` now runs, with
  `CHANGE_BASE` and the diff checks' default of `dev` (D12, D24). The guide names the
  engine's operations as dev does, `scripts/change-workflow stop` and
  `scripts/change-workflow note … --resumes <seq>`. Verify: every command the document
  names exists as sections 1, 2 and 6 built it and the merge placed it.
  Done: "Reviews" gains the `Alternatives:` field's two forms and triage assigning it
  for a pasted review (D17), and a `### Default acceptance` with Rule E's five
  conditions citing CW-d5ac, discussed findings disposed of only by the owner's word,
  the `Classification:` line and the table with D18's and D1's examples, the table
  riding on the last question, and the advancing default (D1–D3, D18); the "Skills"
  paragraph on the order of steps now says a triage recommending advancing takes it
  without asking. "Orchestrating a change" gains **Interrupting a running step** and
  **Revisiting a default acceptance**, the revisit's four steps in section 2's
  handoff order (stop, `note --resumes`, `resume --seq --answer`, then
  `--resolves`), with the direction's refusals. A new `## Waivers` before "The
  ledger", D22's criteria verbatim; the merge before closeout keeps its own
  judgement, as its skill gives it. "The ledger" gains the `revisits default
  acceptance:` entry with D19's example and the recommended-waiver line. "Skills"
  lists the five new closing checks with their targets, no exception marker,
  `CHANGE_BASE` and the `dev` default, then D12's two paragraphs. `stop` joins "The
  engine's command" list. Commands checked against the code by reading it (the
  `--help` calls were denied to this step, so `scripts/change_workflow/cli.py`'s
  parsers were read instead): `stop <change> [--step]`, `note <change> orchestrator
  --by owner --resumes --decision --reason`, `resume <change> --seq --answer`, and
  `check_change.py`'s twelve checks in order with `CHANGE_BASE`.
- [x] 7.5 `docs/development/ARCHITECTURE.md`: add an "Implementation rules" section
  before "Testing strategy", with "No speculative guard code" (D8) and "Prefer an
  existing library" (D10), and its row in the document map. Verify: the document map
  links the new section's anchor.
  Done: `## Implementation rules` with the two `###` rules in D8's and D10's terms,
  kept to a paragraph each (65 O3 found the document's detail too heavy), the
  library rule's examples the frp grant-admission plugin and gitleaks; the document
  map's row links `#implementation-rules`.
- [x] 7.6 Verification: `make check-doc-citations
  CHANGE=act-on-owner-intervention-patterns` reports only the citation of the skill
  section 8 creates; `make check-change CHANGE=act-on-owner-intervention-patterns`
  fails on nothing else. End-to-end: none; no scenario exercises the guidance.
  Done: `make check-change` fails only on documentation citations, and those only on
  `.agents/skills/guidance-review/SKILL.md`, cited by `proposal.md` and this file,
  which section 8 creates. The check reads paths, not headings or anchors, so the new
  anchors were checked by hand against their headings (`#defects-found-during-a-change`,
  `#composition-from-above-and-below`, `#shared-vocabulary-and-identities`,
  `#implementation-rules`, and `frp-grant-admission/spec.md`). `make test` passed, its
  scripts suite 2366 passed, rewriting no lock. End-to-end confirmed: none. No CI
  evidence is owed.
  Fresh-context check: fixed — `ARCHITECTURE.md`'s guard rule had loosened D8 to
  "a test" and the library rule added "maintained" to D10; the "Waivers" section said
  no step recommends without a criterion, which the merge's own judgement contradicts,
  and that every waiver is a ledger line, which holds only for a recommended one
  (CW-n6wy); "The ledger" said an accepting disposition never reaches it, against the
  recommended-waiver line; the proposal's "Knowledge to promote" now names the guide
  for D2, D3, D17 and D18, its impact list what the guide gained, and 11.9's list
  follows. Declined, as the plan's accepted order: the guide describes triage and
  orchestrator behaviour sections 9 and 10 give the skills, and modifies what
  CW-9pbk, CW-3tvs, CW-j1nv and CW-neua say until the archive; it cites CW-d5ac,
  whose `spec.md` anchor exists only once archived; and `AGENTS.md` and `domain.md`
  name `change-workflow`'s "Terms", which 11.9 writes. Declined: "Implementation
  rules" belonging elsewhere, since D8 and D10 name `ARCHITECTURE.md`.
  Handoff: for section 9, the guide says triage assigns a pasted external review's
  `Alternatives:` (D17); no task names it, so 9.1 should state it with Rule E. For
  sections 9 and 10, cite the guide's `### Default acceptance`, `## Waivers`,
  **Interrupting a running step** and **Revisiting a default acceptance** rather than
  restating them in full ("Skills", a skill restating guidance). The heading and
  "Implements" line above omit D1–D3 and D15–D19, which 7.4 writes into the guide.

## 8. Guidance reviews have a skill (D20, D21)

Delivers `guidance-review` and its period ledger. Implements D20, D21, and the delta
requirement `CW-g6ua`. Touches a new `.agents/skills/guidance-review/SKILL.md`, its
links under `.claude/skills/` and `.codex/skills/`, `.gitignore`, and, for the roles
test, `openspec/specs/market-change-workflow/README.md`, "How this repository provides
the workflow's roles".

- [ ] 8.1 Write `.agents/skills/guidance-review/SKILL.md`: run interactively by the
  owner in their workspace, outside any change's steps; read every ledger, triage
  record and workflow log since the end of the last period in
  `openspec/changes/archive/guidance-reviews.jsonl`, or from a date the owner gives
  before the first review; report the disposition figures, default acceptances and
  revisits before and after the fix against Rule E's baseline, a sample audit of
  `Classification:` lines, waiver recommendations and acceptances by criterion, and the
  terms the owner asked about; cluster corrections into false, unwritten and
  unenforced guidance; list candidate edits, including keeping, narrowing or widening
  Rule E and whether a waiver criterion has earned acceptance by default; on the
  owner's word write a change's proposal stating its period; and append one line to
  the period ledger whatever the owner picks. The method is `design.md`'s "Evidence"
  sections, under `AGENTS.md`'s public-repository rules (D20, D21). It finds each
  change's records through `scripts/change-workflow find --records <change>`, as every
  skill does since the merge. Verify: the skill states each of D20's six steps and the
  period ledger's path and line fields.
- [ ] 8.2 Link the skill from `.claude/skills/guidance-review` and
  `.codex/skills/guidance-review`, and add `openspec/changes/archive/guidance-reviews.jsonl`
  to `.gitignore` (D20). Every step is denied edits under `.claude/`, so the
  `.claude/skills/guidance-review` link is the orchestrator's, made on the owner's word
  before this section's session starts; the session makes the `.codex/` link, checks
  both resolve, and commits them with the section. Verify: `make check-agent-skills` passes; `git check-ignore`
  reports the ledger path ignored.
- [ ] 8.3 Keep the roles statement whole (`MCW-5tgp`): every make target and repository
  path the new skill names in code spans or fenced blocks — the period ledger's path
  among them — is listed in `openspec/specs/market-change-workflow/README.md`'s tables,
  the period ledger beside the changes' archive in "The engine's own assumptions"; no
  new role is added, since the ledger lives in the archive the engine already assumes.
  Verify: `pytest -q scripts/tests/test_change_workflow_assumptions.py` (unit) passes.
- [ ] 8.4 Verification: `make check-agent-skills` passes;
  `pytest -q scripts/tests/test_change_workflow_assumptions.py` passes; `make
  check-change CHANGE=act-on-owner-intervention-patterns` passes every check, the
  citation of the new skill now resolving. End-to-end: none; no scenario exercises the
  skills.

## 9. Triage accepts uncontested findings by default (D1–D3, D6, D16, D18, D19, D22)

Delivers the triage skill's default acceptance. Implements D1, D2, D3, D16, D18, D19,
D6's triage outcomes, D22 at a review and validation of different commits, and the
delta requirements `CW-d5ac`, `CW-t9bx`, `CW-j1nv`, `CW-neua`, `CW-9pbk`, `CW-3tvs`,
`CW-v1rk`, `CW-n6wy`, `CW-r8vz` and `CW-q3dm`. Touches
`.agents/skills/change-triage/SKILL.md`, and, for the roles test,
`openspec/specs/market-change-workflow/README.md`.

- [ ] 9.1 Write Rule E into step 2 as the classification each finding receives with its
  position, reading the reviewer's `Alternatives:` field, and the `Classification:`
  line and "accepted by default" disposition in step 4's record form (D3, D17, D18).
  Verify: the skill states every condition of D3 and the record form carries the D18
  example's fields.
- [ ] 9.2 Rewrite step 3 so only discussed findings are presented one per message, the
  agenda lists them, and the "Accepted by default" table rides on the last question or
  goes in the final report; rewrite step 6 so an advancing recommendation is taken
  without asking and reported beside the table, another round is still asked, and a
  triage with nothing to discuss and an advancing recommendation asks nothing (D1,
  D2). Update "Running unattended" to match. Verify: the skill no longer requires a
  question for a default-accepted finding or for an advancing exit, and still forbids
  inferring a discussed finding's disposition from silence.
- [ ] 9.3 Add the resumed-triage path: resumed with the owner's revisit, the triage
  amends the fix in a new commit, appends the `revisits default acceptance:` ledger
  line, and names its exit again; a correction of a table item before the fixes is
  logged the same way (D16, D19). Verify: the skill's ledger section shows the D19
  example and names both moments.
- [ ] 9.4 Align the outcomes with `openspec/README.md#defects-found-during-a-change`:
  `fix` and `edit` cover a small, understood out-of-scope defect, recorded in the notes
  or triage record, and a large or vague one is `none`, recorded where `AGENTS.md`'s
  "Deferred work" says; and recommend a waiver at a review and validation of different
  commits when a criterion of `docs/agents/change-workflow.md`'s "Waivers" holds (D6,
  D22). Verify: `make check-agent-skills` passes.
- [ ] 9.5 Verification: `make check-agent-skills` passes;
  `pytest -q scripts/tests/test_change_workflow_assumptions.py` (unit) passes, any make
  target or repository path the skill newly names listed in
  `openspec/specs/market-change-workflow/README.md`'s tables (`MCW-5tgp`); `make
  check-change CHANGE=act-on-owner-intervention-patterns` passes; a read of the skill
  against the scenarios of `CW-d5ac`, `CW-t9bx`, `CW-j1nv`, `CW-neua`, `CW-9pbk` and
  `CW-3tvs` finds each one stated. End-to-end: none; no scenario exercises the skills.

## 10. The other skills interrupt, route revisits, recommend waivers, and fix found defects (D6, D12, D15, D16, D22, D24 item 1)

Delivers the orchestrator's interrupt and revisit procedures and the other skills'
alignments. Implements D15 and D16 in `change-orchestrate`, D6 in `change-review`,
`change-implement` and `change-design`, D12's bookkeeping rule and D24 item 1's
decision headings in `change-design`, and D22 in `change-design`, `change-validate`
and `change-archive-cleanup`. Touches `.agents/skills/change-orchestrate/SKILL.md`,
`change-review/SKILL.md`, `change-implement/SKILL.md`, `change-design/SKILL.md`,
`change-validate/SKILL.md`, and `change-archive-cleanup/SKILL.md`, and, for the roles
test, `openspec/specs/market-change-workflow/README.md`. Implements the delta
requirements `CW-k2rv`, `CW-h7lq`, `CW-w4ne`, `CW-r8vz`, `CW-q3dm` and `CW-n6wy` in the
skills.

- [ ] 10.1 `change-orchestrate`: relay the table and an advancing exit as any message;
  on the owner's word, interrupt a running step with `scripts/change-workflow stop
  <change> [--step <step>]` and record the interrupt as an owner's decision resolving
  nothing (`scripts/change-workflow note <change> orchestrator --by owner …`), then
  recover the stop as the owner says; route a revisit in the order section 2's handoff
  gives — stop the step running after the triage, record `scripts/change-workflow note
  <change> orchestrator --by owner --resumes <seq> …`, resume the triage with the
  owner's words, then resolve the stopped step (D15, D16). Verify: the skill names each
  command as sections 1 and 2 implemented it and the merge placed it under
  `scripts/change-workflow`.
- [ ] 10.2 `change-review`: the design and pre-closeout scope lenses ask whether new
  scope is a small understood fix, kept, or large or vague work, split, and the
  implementation consistency lens admits a found defect the notes record, each citing
  `openspec/README.md#defects-found-during-a-change` (D6). `change-implement`: a
  small, understood defect found while implementing is fixed and recorded in the
  section's notes as outside the plan (D6). Verify: `make check-agent-skills` passes.
- [ ] 10.3 `change-design`: record decisions under `### D<n> — <title>` headings and
  name each in "Knowledge to promote" (D24 item 1); state documentation destinations,
  test levels and evidence rather than asking them (D12); ask the splitting question
  as `openspec/README.md#defects-found-during-a-change` frames it (D6); and, finishing
  after a return, recommend waiving another design review when a criterion holds
  (D22). `change-validate` recommends a waiver on a known environmental failure, and
  `change-archive-cleanup` before its validation, when a criterion holds (D22).
  Verify: `make check-agent-skills` passes.
- [ ] 10.4 Verification: `make check-agent-skills` passes;
  `pytest -q scripts/tests/test_change_workflow_assumptions.py` (unit) passes, any make
  target or repository path the skills newly name listed in
  `openspec/specs/market-change-workflow/README.md`'s tables (`MCW-5tgp`); `make
  check-change CHANGE=act-on-owner-intervention-patterns` passes. End-to-end: none; no
  scenario exercises the skills.

## 11. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [ ] 11.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the change's
  own history-wording check (section 6) passes on its diff; a comment that needs
  rewriting returns the change to implementation.
- [ ] 11.2 Import placement: confirm every import sections 1–6 added inside a function
  carries its reason, which the local-import check (section 6) reports; one that should
  move returns the change to implementation.
- [ ] 11.3 Documentation compliance: re-check D1–D30 against `openspec/README.md`'s
  placement rules and the destinations named in 11.9 (D30, 55 F2), each rule in the
  capability that owns it — the engine's in `change-workflow`, this repository's in
  `market-change-workflow`; and confirm the proposal's "Public interfaces of the
  workflow's engine" still names every public interface the change altered, and
  whether each is compatible (`CW-c2tw`).
- [ ] 11.4 Narrative compression: shorten completed task notes to final behaviour,
  material evidence (the uv release of 4.1, the gitleaks release, the nested
  extension, and the tree counts of 5.2, the active changes 6.1 listed), and
  destinations; section 5's gate-run notes compress to what design decided from them.
- [ ] 11.5 Roadmap currency: record in the promotion record that the change has no
  roadmap impact — it serves no goal of `docs/development/ROADMAP.md` and closes no gap
  row there.
- [ ] 11.6 Campaign index currency: set the change's row in `openspec/changes/README.md`
  to `in closeout` with notes matching what is now true, and run
  `make check-change-index`; the change has no campaign graph entry, and its
  dependents are released at archive cleanup.
- [ ] 11.7 Packaging: run `make check-packaging` and `make check-architecture-change
  CHANGE=act-on-owner-intervention-patterns`, and `make check-agent-skills`, since the
  change touched `.agents/` and the skill links.
- [ ] 11.8 End-to-end pipeline: record the latest passing pipeline run, its commit, and
  that no scenario exercises the change's behaviour, the run being evidence only that
  section 4's uv builds and runs the stack.
- [ ] 11.9 Promotion: write the permanent documents and the design-promotion record:
  - `openspec/specs/change-workflow/spec.md`, a `## Terms` section by hand, with round,
    round view, pass, exit, direction, guard, join, record, waiver, default acceptance,
    revisit, and interrupt (D11); its requirements arrive by the archive in 11.11.
  - `openspec/specs/change-workflow/README.md`: its opening (the owner reads every
    finding, discussed or in the table); "The owner is interrupted only for judgement"
    (D2, the advancing default); "The orchestrator relays and routes" (D14's principle
    that the owner can always reach a running step, and D15); "Reviews are files"
    (D17); "Triage" (D3's rationale and Rule E's baseline, D4, D16, D20, D21); and "The
    intervention ledger" where its account of what is logged no longer holds (D19,
    D22). Its sections follow `index.md`'s parts, so a new group of the index —
    "Guidance reviews", under "Reviews and triage" — has its paragraphs under that
    part.
  - `openspec/specs/market-change-workflow/README.md`: a section for its index's part
    "This repository's checks", holding "Secret scanning" as the merge placed it (D24
    item 4, D26, D28, D29; 65 O3) beside the closing checks and the lock revision in
    brief, each pointing to the document that details it.
  - Both capabilities' `index.md`: the entries for the ids the deltas add were written
    with the re-targeted deltas, before implementation, since the index check fails a
    change whose delta adds an id its index omits; and the summary lines of `CW-9pbk`,
    `CW-3tvs`, `CW-j1nv` and `CW-neua` were revised then. Confirm each entry's group
    and summary still hold for the requirement as implemented, and revise any that
    does not (`openspec/README.md#plan-closeout-requirements`, part 9).
  - The record names, besides those, the documents sections 4, 5, 7, 8 and 10 wrote:
    `AGENTS.md` (D5, D9), `openspec/README.md` (D6), `docs/agents/domain.md` (D11),
    `docs/agents/change-workflow.md` (D1–D3, D12, D15–D19, D22, D24),
    `docs/development/ARCHITECTURE.md` (D8, D10, and D24 item 4 and D29 in brief under
    "Public repository content checks"), `docs/development/BUILD_AND_PACKAGING.md` (D24
    item 7), `docs/development/RELEASING.md`, "Cutting a release" (D29), the comments of
    `.gitleaks.toml` (D26), `.agents/skills/change-design/SKILL.md` (D12),
    `.agents/skills/guidance-review/SKILL.md` (D20), and D7, D13, D23, D25 and D30 as
    having no permanent destination.
  - The engine's requirements (D1–D3, D15–D20, D22) arrive in
    `openspec/specs/change-workflow/spec.md`, and this repository's (D24, D27, D29) in
    `openspec/specs/market-change-workflow/spec.md`, by the archive in 11.11; confirm
    afterwards that every id the deltas add is there, `MCW-s8gk` and `MCW-u2dt` with
    their scenarios among them, and that `make check-spec-index` passes unscoped.
- [ ] 11.10 Documentation citations: run `make check-doc-citations
  CHANGE=act-on-owner-intervention-patterns` and resolve every match, then
  `openspec validate act-on-owner-intervention-patterns --strict`.
- [ ] 11.11 Archival: `openspec archive act-on-owner-intervention-patterns -y`, merging
  the `change-workflow` delta into `openspec/specs/change-workflow/spec.md` and the
  `market-change-workflow` delta into `openspec/specs/market-change-workflow/spec.md`
  (no `--skip-specs`); the row then links the archived directory.
