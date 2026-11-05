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

## 1. A running step can be stopped (D15)

Delivers the `stop` command, the run's identity as a held lock, and SIGTERM handling
in the review runner. Implements D15 and the delta requirement "The owner interrupts a
running step". Touches `scripts/change_workflow/running.py`, `wrapper.py`,
`review.py`, `harness.py`, `cli.py`, `scripts/run_change_step.py`, and the run
records' readers `scripts/round_view.py` and `scripts/change_clone.py`.

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
- [x] 1.2 Add `python3 scripts/run_change_step.py stop <change> [--step <step>]` (D15):
  it selects the change's live run, or the run of the named step when two are live,
  checks the lock again immediately before sending SIGTERM, and refuses, signalling
  nothing, when no run is live, when two are live and no step is named, when the
  record is stale, or when the run ended before the second check. Verify: unit tests
  in `scripts/tests/test_run_change_step.py` for each refusal and for a signal reaching
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
  scripts/tests/test_run_change_step.py scripts/tests/test_round_view.py
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

## 2. A finished triage can be resumed for a revisit (D16)

Delivers the owner's `--resumes` direction and the wrapper's resume of a finished
triage under it. Implements D16, D4, and the delta requirement "The owner revisits a
default acceptance". Touches `scripts/change_workflow/cli.py`, `log.py`, `wrapper.py`,
and `scripts/change_next_step.py`; no node or exit of `scripts/change_workflow/graph.py`
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
  scripts/tests/test_change_workflow_graph.py scripts/tests/test_run_change_step.py`
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
  `openspec/specs/change-workflow/architecture.md` still says the wrapper refuses any
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
  Handoff: every machine running the workflow's steps now needs uv 0.12.22 or newer
  before `make lock`, `make init` or `make test`. `make lock` still passes no
  `--upgrade-package` for a lock naming no internal package, so a future rise of the
  minimum leaves such locks at the old revision; the revision check then names them,
  and `BUILD_AND_PACKAGING.md` says how to relock one.

## 5. Private keys are refused through gitleaks (D24 item 4)

Delivers a pinned gitleaks with a repository rule beside `check_public_content.py`
wherever that runs. Implements D24 item 4 and the delta requirement's private-key
clauses with its scenarios "A key fixture carries no key material", "Two key fixtures
share a file", "A key is added in a merge resolution", "A real key is staged", and "A
key is embedded as one escaped string". Touches a new `.gitleaks.toml`, a new
`scripts/check_secrets.py`, `scripts/hooks/pre-commit`, `scripts/hooks/pre-push`,
`scripts/check_push_ready.py`, the `Makefile`'s `check-public-content`,
`.github/workflows/public-content.yml`, `.github/workflows/tests.yml`, and
`docs/development/ARCHITECTURE.md`, "Public repository content checks".

- [ ] 5.1 Decision gate (D24 item 4): choose the gitleaks release to pin, write
  `.gitleaks.toml` extending the default configuration, turning its `private-key` rule
  off, and adding the block rule whose body holds no run of five dashes, then run the
  pinned release with it against the repository's tree, two fixtures in one file, a key
  wrapped at short lines, a key embedded as one escaped string, a key added in an
  intermediate outgoing commit a later commit deletes, and a key introduced only in a
  merge resolution scanned with `--log-opts=--diff-merges=separate`. Record the release,
  its checksum, and each case's result in this section's notes. If the release cannot
  turn off or replace its default rule from an extending configuration, a fixture is
  refused, or a key passes, stop: the change returns to design (`change-implement`,
  "Stop cleanly when the plan is wrong"), with no workaround.
- [ ] 5.2 Add `scripts/check_secrets.py`: it runs the pinned gitleaks with
  `.gitleaks.toml` and redaction, on staged additions or on a commit range with
  `--log-opts=--diff-merges=separate`, refuses an installed release other than the pin,
  naming both, and reports each finding by file and line without its content (D24 item
  4). Verify: unit tests in a new `scripts/tests/test_check_secrets.py` with an
  injected runner for the arguments of each mode and the version refusal; library
  integration tests there running the real pinned release over temporary Git
  repositories for every case of 5.1, each delta scenario above mapping to one.
- [ ] 5.3 Run it wherever `check_public_content.py` runs: the pre-commit hook on staged
  additions, the pre-push hook and `scripts/check_push_ready.py` on every outgoing
  commit, `make check-public-content`, and `.github/workflows/public-content.yml` on
  every commit since its base, that workflow and `tests.yml`'s
  `test-deployment-packaging` job installing the pinned release and checking its
  checksum (D24 item 4). Verify: unit tests in `scripts/tests/test_check_push_ready.py`
  and `test_check_public_content.py` show the guarded push refusing an outgoing commit
  that adds a key and passing the fixtures; running the workflow's own command locally
  over this branch's commits passes.
- [ ] 5.4 Record in `docs/development/ARCHITECTURE.md`, "Public repository content
  checks", gitleaks and its pinned release, how to install it, why the repository
  replaces the default key rule, and the edit beneath an unchanged key header it
  cannot see, review remaining the safeguard there (D24 item 4). Verify:
  `make check-doc-citations CHANGE=act-on-owner-intervention-patterns` reports no path
  this section added that fails to resolve.
- [ ] 5.5 Verification: `pytest -q scripts/tests/test_check_secrets.py
  scripts/tests/test_check_public_content.py scripts/tests/test_check_push_ready.py`
  (unit and library integration) passes; `make check-public-content` passes; `make
  test` passes. End-to-end: none; no scenario exercises the public-content checks.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — it
  installs the pinned gitleaks with its checksum checked, and the real-scanner cases in
  `scripts/tests/test_check_secrets.py` run and pass rather than being skipped.

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

## 7. The guidance says what the owner does (D5, D6, D8–D12, D22, D23, D24)

Delivers the guidance edits the skills in sections 9 and 10 cite. Implements D5, D6,
D8, D9, D10, D11, D12, D22's criteria, D23, and D24's description for contributors.
Touches `AGENTS.md`, `docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md`
(deleted), `docs/agents/domain.md`, `openspec/README.md`,
`docs/agents/change-workflow.md`, and `docs/development/ARCHITECTURE.md`.

- [ ] 7.1 `AGENTS.md`: replace "Issue tracker" and "Triage labels" with "Deferred
  work" in D5's wording; remove the ADR sentence from "Domain docs" (D23); add "Amend a
  rule or comply" under "Working model" (D9). Delete `docs/agents/issue-tracker.md`
  and `docs/agents/triage-labels.md` with `git rm` (D5). Verify: `git grep -n
  "issue-tracker.md\|triage-labels.md\|docs/adr"` finds no citation outside
  `openspec/changes/`.
- [ ] 7.2 Rewrite `docs/agents/domain.md` to name the vocabulary's homes and state the
  rule for terms, without `CONTEXT.md`, `CONTEXT-MAP.md`, `/domain-modeling` or ADRs
  (D11, D23). Verify: the document holds D11's table and rule and none of the removed
  references.
- [ ] 7.3 `openspec/README.md`: add a "Defects found during a change" section after
  "Plan closeout requirements" in D6's wording, so skills cite a stable heading, and
  replace the scope-creep sentence with D6's (D6). Verify: the section's anchor,
  `openspec/README.md#defects-found-during-a-change`, resolves for the skills of
  sections 9 and 10 to cite.
- [ ] 7.4 `docs/agents/change-workflow.md`: under "Reviews", default acceptance, the
  table and the classification (D1–D3, D17, D18); under "Orchestrating a change",
  interrupting a step and revisiting a default acceptance (D15, D16); a new "Waivers"
  section with D22's criteria; under "The ledger", the revisit marker and recommended
  waivers (D19, D22); under "Skills", notes and proposals across changes, a skill
  restating guidance only to cite it, and the checks `make check-change` now runs (D12,
  D24). Verify: every command the document names exists as sections 1, 2 and 6 built
  it.
- [ ] 7.5 `docs/development/ARCHITECTURE.md`: add an "Implementation rules" section
  before "Testing strategy", with "No speculative guard code" (D8) and "Prefer an
  existing library" (D10), and its row in the document map. Verify: the document map
  links the new section's anchor.
- [ ] 7.6 Verification: `make check-doc-citations
  CHANGE=act-on-owner-intervention-patterns` reports only the citation of the skill
  section 8 creates; `make check-change CHANGE=act-on-owner-intervention-patterns`
  fails on nothing else. End-to-end: none; no scenario exercises the guidance.

## 8. Guidance reviews have a skill (D20, D21)

Delivers `guidance-review` and its period ledger. Implements D20, D21, and the delta
requirement "Guidance reviews". Touches a new `.agents/skills/guidance-review/SKILL.md`,
its links under `.claude/skills/` and `.codex/skills/`, and `.gitignore`.

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
  sections, under `AGENTS.md`'s public-repository rules (D20, D21). Verify: the skill
  states each of D20's six steps and the period ledger's path and line fields.
- [ ] 8.2 Link the skill from `.claude/skills/guidance-review` and
  `.codex/skills/guidance-review`, and add `openspec/changes/archive/guidance-reviews.jsonl`
  to `.gitignore` (D20). Every step is denied edits under `.claude/`, so the
  `.claude/skills/guidance-review` link is the orchestrator's, made on the owner's word
  before this section's session starts; the session makes the `.codex/` link, checks
  both resolve, and commits them with the section. Verify: `make check-agent-skills` passes; `git check-ignore`
  reports the ledger path ignored.
- [ ] 8.3 Verification: `make check-agent-skills` passes; `make check-change
  CHANGE=act-on-owner-intervention-patterns` passes every check, the citation of the
  new skill now resolving. End-to-end: none; no scenario exercises the skills.

## 9. Triage accepts uncontested findings by default (D1–D3, D6, D16, D18, D19, D22)

Delivers the triage skill's default acceptance. Implements D1, D2, D3, D16, D18, D19,
D6's triage outcomes, D22 at a review and validation of different commits, and the
delta requirements "Triage of every finding", "Phases and owner touchpoints",
"Intervention ledger", "Discussion steps stay conversations with the owner", "The
owner revisits a default acceptance", and "Waivers are recommended and the owner's to
take". Touches `.agents/skills/change-triage/SKILL.md`.

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
- [ ] 9.5 Verification: `make check-agent-skills` passes; `make check-change
  CHANGE=act-on-owner-intervention-patterns` passes; a read of the skill against the
  delta's scenarios for "Triage of every finding" and "Discussion steps stay
  conversations with the owner" finds each one stated. End-to-end: none; no scenario
  exercises the skills.

## 10. The other skills interrupt, route revisits, recommend waivers, and fix found defects (D6, D12, D15, D16, D22, D24 item 1)

Delivers the orchestrator's interrupt and revisit procedures and the other skills'
alignments. Implements D15 and D16 in `change-orchestrate`, D6 in `change-review`,
`change-implement` and `change-design`, D12's bookkeeping rule and D24 item 1's
decision headings in `change-design`, and D22 in `change-design`, `change-validate`
and `change-archive-cleanup`. Touches `.agents/skills/change-orchestrate/SKILL.md`,
`change-review/SKILL.md`, `change-implement/SKILL.md`, `change-design/SKILL.md`,
`change-validate/SKILL.md`, and `change-archive-cleanup/SKILL.md`.

- [ ] 10.1 `change-orchestrate`: relay the table and an advancing exit as any message;
  on the owner's word, interrupt a running step with `run_change_step.py stop` and
  record the interrupt as an owner's decision resolving nothing, then recover the stop
  as the owner says; route a revisit by stopping the step running after the triage,
  recording `note --by owner --resumes <seq>`, resuming the triage with the owner's
  words, and resolving the stopped step (D15, D16). Verify: the skill names each
  command as sections 1 and 2 implemented it.
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
- [ ] 10.4 Verification: `make check-agent-skills` passes; `make check-change
  CHANGE=act-on-owner-intervention-patterns` passes. End-to-end: none; no scenario
  exercises the skills.

## 11. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [ ] 11.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the change's
  own history-wording check (section 6) passes on its diff; a comment that needs
  rewriting returns the change to implementation.
- [ ] 11.2 Import placement: confirm every import sections 1–6 added inside a function
  carries its reason, which the local-import check (section 6) reports; one that should
  move returns the change to implementation.
- [ ] 11.3 Documentation compliance: re-check D1–D24 against `openspec/README.md`'s
  placement rules and the destinations named in 11.9.
- [ ] 11.4 Narrative compression: shorten completed task notes to final behaviour,
  material evidence (the uv release of 4.1, the gitleaks release and cases of 5.1, the
  active changes 6.1 listed), and destinations.
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
  - `openspec/specs/change-workflow/architecture.md`: "What the workflow is for" (the
    owner reads every finding, discussed or in the table); "The owner is interrupted
    only for judgement" (D2, the advancing default); "The orchestrator relays and
    routes" (D14's principle that the owner can always reach a running step, and D15);
    "Reviews are files" (D17); "Triage" (D3's rationale and Rule E's baseline, D4, D16,
    D20, D21).
  - The record names, besides those, the documents sections 4, 5, 7, 8 and 10 wrote:
    `AGENTS.md` (D5, D9), `openspec/README.md` (D6), `docs/agents/domain.md` (D11),
    `docs/agents/change-workflow.md` (D1, D12, D15, D16, D19, D22, D24),
    `docs/development/ARCHITECTURE.md` (D8, D10, and D24 item 4 under "Public repository
    content checks"), `docs/development/BUILD_AND_PACKAGING.md` (D24 item 7),
    `.agents/skills/change-design/SKILL.md` (D12), `.agents/skills/guidance-review/SKILL.md`
    (D20), and D7, D13 and D23 as having no permanent destination.
- [ ] 11.10 Documentation citations: run `make check-doc-citations
  CHANGE=act-on-owner-intervention-patterns` and resolve every match, then
  `openspec validate act-on-owner-intervention-patterns --strict`.
- [ ] 11.11 Archival: `openspec archive act-on-owner-intervention-patterns -y`, merging
  the `change-workflow` delta into `openspec/specs/change-workflow/spec.md` (no
  `--skip-specs`); the row then links the archived directory.
