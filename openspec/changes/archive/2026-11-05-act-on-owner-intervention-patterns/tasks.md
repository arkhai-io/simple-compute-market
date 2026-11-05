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

Replanned after round 1, once `dev` was merged in (`ed68f99ad`): sections 7–11 were
amended against dev's restructured workflow, which `design.md`'s status note
describes. Paths the task statements below name at their earlier places are now: the
script `run_change_step.py` is the `scripts/change-workflow` command; `round_view.py`,
`change_clone.py`, `change_next_step.py` and the guarded push of `check_push_ready.py`
are `scripts/change_workflow/round_view.py`, `clone.py`, `next_step.py` and `push.py`;
the tests of `test_run_change_step.py` are in
`scripts/tests/test_change_workflow_cli_steps.py`; and `change-workflow`'s companion
is `openspec/specs/change-workflow/README.md`, its "Secret scanning" section in
`openspec/specs/market-change-workflow/README.md`. The notes name them at their
current places. Closeout compressed the notes to behaviour, evidence and
destinations; what implementation settled and declined is in `design.md`,
"Implementation record".

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
  Done: `running.recorded_run` holds `flock(LOCK_EX)` on the record; `live_runs`
  reads a record as a run only when a non-blocking `LOCK_SH` fails; the round view and
  the clone read through `runs_in_progress` unchanged. Evidence (library integration,
  real `flock` and processes, not unit as planned): `test_change_workflow_wrapper.py`
  `test_a_record_is_a_run_only_while_its_lock_is_held` and
  `test_a_killed_runs_record_is_stale_though_its_child_survives`;
  `test_round_view.py` `test_a_held_record_refuses_the_view_and_a_stale_one_does_not`;
  `test_change_clone.py`'s run-in-progress case.
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
  Done: `running.select_run`, `signal_run` and `stop`, and the CLI's `stop`, reading
  the change's clone when it has one. Unit tests in
  `test_change_workflow_cli_steps.py`, `os.kill` injected: a signal reaching the live
  run; "Nothing is running" (`test_stop_with_nothing_running_refuses_and_signals_nothing`);
  "A run record outlives its run" (`test_stop_refuses_a_stale_record_naming_it`); two
  live runs without and with `--step`; "A run ends while it is being stopped"
  (`test_a_run_that_ends_before_the_second_check_is_not_signalled`,
  `test_a_run_killed_between_the_checks_is_not_signalled`); `ProcessLookupError`
  reported as ended. Library integration:
  `test_a_stopped_step_is_logged_stopped_and_its_agent_ended`; `test_change_clone.py`
  `test_stop_from_the_workspace_signals_the_run_in_the_changes_clone`.
- [x] 1.3 Raise SIGTERM as the wrapper's termination inside `review_and_log`, so a
  stopped review reaches its existing interruption path, is logged `stopped`, publishes
  nothing, and removes its record; and make `run_codex` end the reviewer process it
  started before the run is logged, as `run_claude` does (D15). Verify: unit tests in
  `scripts/tests/test_change_workflow_review.py` and `test_change_workflow_harness.py`
  show a review signalled mid-run logged `stopped` with no record published and its
  reviewer process ended; the delta scenario "Two runs are in progress" maps to a test
  that stops the review and leaves a second live run untouched.
  Done: `Terminated` and `termination_ends_the_run` live in `running.py`, shared by
  the wrapper and the review; `run_codex` kills its process in a `finally`. Evidence:
  `test_change_workflow_review.py`
  `test_a_review_signalled_mid_run_is_logged_stopped_and_publishes_nothing` (unit);
  `test_change_workflow_harness.py` `test_a_terminated_codex_run_ends_its_reviewer`
  and `…_claude_run_ends_its_agent` (library integration); "Two runs are in progress":
  `test_stopping_the_review_leaves_the_validation_running` (library integration, a
  real review and a real wrapper's validation side by side).
- [x] 1.4 Verification: `pytest -q scripts/tests/test_change_workflow_wrapper.py
  scripts/tests/test_change_workflow_review.py scripts/tests/test_change_workflow_harness.py
  scripts/tests/test_change_workflow_cli_steps.py scripts/tests/test_round_view.py
  scripts/tests/test_change_clone.py` (unit, and library integration where a real
  process or Git repository is used) passes; `make test` passes.
  End-to-end: none; no scenario exercises the workflow tooling.
  Done: the six suites, 375 passed; `make test-release-tooling` 1903 passed; `make
  test` passed. End-to-end: none.
- Round 1 triage fixes (64 F1, 64 F2): a stop held while a run finishes ends nothing,
  and the run logs the outcome it reached (`termination_deferred()`; the interrupt
  requirement's last sentence and the scenario "A stop arrives as the run writes its
  line"); an interrupted review's `stopped` line carries the reviewer's session and
  cost. Tests (unit, real signals): a wrapper stop after the agent exits logged
  `finished`; stops before the agent or reviewer starts end the run without running
  it; a review stop after publication logged `finished` with its record; Codex and
  Claude interrupts record their sessions. Evidence: the workflow suites 551 passed;
  `make test` passed, its scripts suite 2076; `make check-packaging` passed.

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
  line records `resumes` and no `next`; three further refusals in `design.md`,
  "Implementation record". Unit tests, `test_change_workflow_log.py`: the accepted
  direction; "A later triage has run"
  (`test_a_revisit_of_a_triage_a_later_triage_superseded_is_refused`); a question,
  stop, return, validation, or missing seq refused; the orchestrator's refused; a
  waiting resumed run; no review named; `--next`. `test_change_workflow_cli_steps.py`:
  the command line's accepted direction and refusals.
- [x] 2.2 Let `Wrapper.resume` resume a `finished` triage run only when an unused owner
  direction `--resumes` names it, and keep refusing every other finished run as not
  waiting (D16). Verify: unit tests in `scripts/tests/test_change_workflow_wrapper.py`
  for a resume under the direction, a resume without one refused ("A finished run is
  resumed without a direction"), and a direction used once only.
  Done: the resumed line records `resumes: <seq>`, which spends the direction.
  Unit tests, `test_change_workflow_wrapper.py`: a resume under the direction; "A
  finished run is resumed without a direction"; a direction used once; a direction
  given before a later triage refused at the resume; a direction naming another
  triage resuming nothing.
- [x] 2.3 Make the next-step computation route on the resumed triage's later outcome
  for the reviews it names, and read the stopped step it superseded as resolved only
  through the owner's decision line (D16). Verify: unit tests in
  `scripts/tests/test_change_next_step.py` for "A revisit while the fix commit is
  validated": a triage finished, its fix commit's validation stopped and resolved, the
  triage resumed and finished again, and the computation naming what that later
  outcome's exit requires; `scripts/tests/test_change_workflow_graph.py` passes
  unchanged, showing the graph has no new node or edge.
  Done: no code change was needed (`route_of`'s docstring gained a sentence). The unit
  test `test_a_revisit_while_the_fix_commit_is_validated_routes_on_the_resumed_triage`
  proves the existing behaviour holds for a revisit; `graph.py` and its test are
  unchanged.
- [x] 2.4 Verification: `pytest -q scripts/tests/test_change_workflow_log.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_next_step.py
  scripts/tests/test_change_workflow_graph.py scripts/tests/test_change_workflow_cli_steps.py`
  (unit) passes; `make test` passes. End-to-end: none; no scenario exercises the
  workflow tooling.
  Done: the five suites, 541 passed; `make test-release-tooling` 1923 passed; `make
  test` ran after section 3, as this section touched only `scripts/` and its tests.
  End-to-end: none. The revisit's order (stop, direction, resume, resolve) was handed
  to section 10's `change-orchestrate`.

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
  Done: `FIELDS["Alternatives"] = None`; the field parser's defect, found by the new
  tests, fixed (`design.md`, "Implementation record"). Unit tests through
  `run_review`: "A finding states no alternatives"
  (`test_a_review_missing_alternatives_is_kept_beside_its_transcript`); an empty field
  and a nested list refused; an empty Evidence refused; "A finding has one evident
  fix" (`test_a_finding_stating_its_one_evident_fix_is_published`).
- [x] 3.2 Add `- **Alternatives:**` to `change-review`'s finding format in section 6,
  with the rule that it holds `none — <why the fix is evident>` or each option a
  reasonable owner might choose with its trade-off, and that the direction finding's
  prose alternatives are listed there too (D17). Verify: `make check-agent-skills`
  passes, and the format block in the skill carries every field `review.py` requires.
  Done: the field in the format block, its rule beside basis and severity, the value
  on the field's own line; `docs/agents/change-workflow.md`'s "Reviews" names it. The
  block carries all five of `FIELDS`. `make check-agent-skills` passes.
- [x] 3.3 Verification: `pytest -q scripts/tests/test_change_workflow_review.py` (unit)
  passes; `make check-agent-skills` passes; `make test` passes. End-to-end: none; no
  scenario exercises the review tooling.
  Done: the review suite, 76 passed; `make check-agent-skills` passes; `make test`
  passed; `make test-release-tooling` 1928 passed after the fresh-context fixes.
  End-to-end: none. Round 1's own review was the first in this format.

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
  release before it, writes revision 3. Found by locking a fresh one-file project
  with each release through `uvx --from uv==<release> uv lock`: 0.12.19–0.12.21 write
  3; 0.12.22–0.12.24 (the last 0.12) and 0.13.0 write 5. A fresh project matters: a
  release relocking an unchanged lock leaves its revision.
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
  Done: `MINIMUM = (0, 12, 22)`; the seven `setup-uv` pins at 0.12.22;
  `uv_project.main` runs the check before `lock` and `reinit`, `image` and
  `install-wheel` unchecked. Other uv installs confirmed and one defect fixed in
  place (`design.md`, "Implementation record"). Tests: `test_check_uv_version.py`
  (unit), the minimum and releases either side; `test_uv_project.py` (unit), `lock`
  and `reinit` refused naming both versions with nothing run; integration, a real
  `make -n`: `test_every_make_target_that_relocks_goes_through_the_guarded_command`.
- [x] 4.3 Add the lock-revision check to `scripts/check_locks.py`: every committed
  `uv.lock` carries revision 5, and one carrying another fails, naming the lock and
  both revisions (D24 item 7). Verify: unit tests in `scripts/tests/test_check_locks.py`
  for a lock at the expected revision, one at 3, and one at a revision above 5.
  Done: `LOCK_REVISION = 5` in `check_locks.lock_problems`. Tests,
  `test_check_locks.py`: revision 5 passes; 3, 6 and none fail naming the lock and
  both revisions; the real tree has no revision problem. `test_check_locks_uv.py`
  skips below the minimum, since an older uv writes revision 3 by design.
- [x] 4.4 Relock the eight locks at revision 3 with the new minimum uv, changing
  nothing but what the relock writes, and update
  `docs/development/BUILD_AND_PACKAGING.md`'s uv minimum, the lock-revision check, and
  drift in both directions (D24 item 7). Verify: `git grep -l "^revision = 3" --
  '*uv.lock'` prints nothing; `make check-locks` passes.
  Done: each relocked with `uvx --from uv==0.12.22 uv lock --upgrade-package <its own
  distribution>`, moving no dependency; seven change only the revision, and
  `kit/identity/uv.lock` drops a redundant marker as the revision-5 locks write it.
  `BUILD_AND_PACKAGING.md`, "Locks", and its checks table. The `git grep` prints
  nothing; `make check-packaging` passes.
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
  Done: the five suites, 61 passed, 4 skipped below the minimum; `make
  check-packaging` passes; once the machine had uv 0.12.22, `make
  test-release-tooling` 2035 passed with none skipped, and `make test` passed. The
  pipeline's run is evidence only that 0.12.22 builds and runs the stack.
  Owed by validation, beside the line above: in the same job, the four cases of
  `scripts/tests/test_check_locks_uv.py` run and pass rather than skip.
  Every machine running the workflow's steps needs uv 0.12.22 or newer.

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

Prepared before the section, on the owner's direction of 2026-11-05, so installing
gitleaks is one step and a missing gitleaks names it:

- `scripts/gitleaks-pins.toml` pins **gitleaks 8.30.1** with each common platform's
  archive URL and sha256; the linux_x64 archive was downloaded and matched, and the
  other three hashes are copied from the release's checksums file, as the pins file
  says.
- `scripts/install_gitleaks.py`, `make install-gitleaks [GITLEAKS_INSTALL_DIR=<dir>]`:
  downloads the platform's archive, refuses it unless its sha256 is pinned, installs
  into `~/.local/bin`, and fails when what it installed is not the `gitleaks` on PATH;
  its `problem()` names the release required and `make install-gitleaks`.
- `tests.yml`'s `test-deployment-packaging` job and `public-content.yml` install it
  that way.
- Tests, `scripts/tests/test_install_gitleaks.py` (unit, injected download and
  lookups; one integration case, a real `make -n`), 17 passed.

The first gate run (gitleaks 8.30.1) held the key rule on every case and returned the
change to design: gitleaks' other default rules reported 114 findings on the tree, the
repository's own fixtures. Design settled it as D25–D30 (`design.md`, "The secret
scan's rules"), and tasks 5.1–5.6 replaced the section's earlier tasks, none of which
was checked; the work that run committed was built on.

- [x] 5.1 The README's credential (D25): in `domains/vms/provisioning/iac/README.md`,
  "Configure Build Variables (Optional)", replace the `root_password` and
  `root_filename` values the heredoc writes with `<the existing key's password>` and
  `<its filename>`, as the section's first commit. Record in the notes that the fix is
  outside the change's stated scope, a found defect fixed in place (D6), and that no
  customer image was built with the value, so nothing is rotated. Verify: the two
  lines hold placeholders, and 5.6's audit reports no finding in that file.
  Done, as the section's first commit (`da72f3841`): both lines hold the
  placeholders. Outside the change's stated scope, a found defect fixed in place (D6);
  no customer image was built with the value, so nothing is rotated, and it stays in
  public history. `make audit-secrets` at `9e5c10cfc` reported no finding in the file.
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
  Done: release 8.30.1, linux_x64 sha256 `551f6fc8…70eb`. **The nested extension
  loads**, gitleaks run from the repository root
  (`test_every_scan_runs_from_the_repository_root_where_the_gate_finds_the_audit`);
  the fallback was not needed. Evidence under the gate, real gitleaks: every key case
  refuses as `private-key-block`; `test_a_provider_token_is_staged` refuses a GitHub
  token; `test_a_development_fixture_is_added` passes lines the audit reports as
  `generic-api-key`; `test_the_repositorys_own_tree_passes_the_gate` asserts `found ==
  []`. Counts: none under the gate; under the audit, `make audit-secrets` at
  `9e5c10cfc`, 116 findings — `generic-api-key` 76, `jwt` 38, `curl-auth-header` 2 —
  D26's 113 less the README's, plus three lines this change's own documents gained
  citing `private_key: Ed25519PrivateKey`.
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
  Done: `--audit`, `audit()`, and the shared `tree_commit()`; findings as
  `<file>:<line>: <rule>` then a count; exit 0 whatever it found, 1 when gitleaks
  could not run or another release is installed. `test_check_secrets.py`, 28 passed,
  none skipped: injected-gitleaks cases over real repositories for the audit's
  configuration, source, exit and errors; real-gitleaks cases (external process,
  required under `GITLEAKS_REQUIRED=1`) for "A provider token is staged", "A
  development fixture is added", "The audit reports what the gate passes"
  (`test_the_audit_reports_what_the_gate_passes`), and the ten key cases — "A key
  fixture carries no key material", "Two key fixtures share a file", "A real key is
  staged" (wrapped at 64 and 16), "A key is embedded as one escaped string", "A key
  is added in a merge resolution".
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
  Done: both hooks, the guarded push (a gate that cannot run refusing the push), both
  make targets, `public-content.yml`, and `GITLEAKS_REQUIRED=1` on the
  `test-deployment-packaging` job's `make` step. Tests, `test_check_push_ready.py`, 15
  passed: `test_an_outgoing_commit_adding_a_key_refuses_publication` and
  `test_an_outgoing_commit_adding_a_key_fixture_is_pushed` (integration, the real
  gitleaks through the guard's real push, the level that proves a refusal, not unit as
  planned). The hooks have no test. `python3 scripts/check_secrets.py --base
  origin/dev` passed over the branch to `9e5c10cfc`.
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
  Done, as round 1's triage (65 O3) placed it: `ARCHITECTURE.md`, "Public repository
  content checks", has one paragraph — the pinned release and its install, the gate,
  the audit — linking to `openspec/specs/market-change-workflow/README.md`, "Secret
  scanning", which holds the rest; `RELEASING.md`, "Cutting a release", begins with
  `make audit-secrets`. The citations resolved but for section 8's skill, then
  unwritten.
- [x] 5.6 Verification: `pytest -q scripts/tests/test_check_secrets.py
  scripts/tests/test_check_public_content.py scripts/tests/test_check_push_ready.py`
  (unit and library integration) passes with `GITLEAKS_REQUIRED=1`; `make
  check-public-content` and `make check-secrets` pass; `make audit-secrets` exits 0
  listing the audit's findings, none in `domains/vms/provisioning/iac/README.md`; `make
  test` passes. End-to-end: none; no scenario exercises the public-content checks.
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — it
  installs the pinned gitleaks with its checksum checked, and the real-scanner cases in
  `scripts/tests/test_check_secrets.py` run and pass rather than being skipped.
  Done: the three suites, 62 passed, none skipped; `make check-public-content` and
  `make check-secrets` pass; `make audit-secrets` exited 0, 116 findings, none in the
  README; `make test` passed, `test-release-tooling` 2070 with none skipped; `make
  check-packaging` passes. End-to-end: none. The owed observation covers the gitleaks
  cases of `test_check_push_ready.py` too.

The section's session stopped once, before committing, for want of the audit and
branch-scan commands in its step's rules; the owner added them to every step's rules
(`9e5c10cfc`), and the section resumed and was committed and pushed.

- Round 1 triage fixes (65 O1, 65 O3, 65 O4): 65 O3, the secret-scanning text moved
  from `ARCHITECTURE.md` to `market-change-workflow`'s README, "Secret scanning", as
  5.5 records, with `.gitleaks.toml`, `scripts/gitleaks-audit.toml` and
  `scripts/check_secrets.py` pointing there; 65 O1, the root `Makefile`'s scattered
  `.PHONY` lines moved to the top block; 65 O4, "Cutting a release" step 1 shortened,
  its explanation after the list.

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
  Done: `scripts/check_decision_destinations.py`, `make check-decision-destinations`.
  Tests, `test_check_decision_destinations.py`: headings read only under a level-2
  `## Decisions` outside fences (unit); through `main()` over a temporary change
  (library integration), every decision named passes, a missing bullet named, `per
  D2` and `D20` not naming D2, no headings not checked. This change: 24 decisions,
  passing (a run, since code may not name a change). Over every active change, 12
  designs carry `### D<n>` headings: two pass (`activate-compute-leases-at-the-site`,
  and this one), and ten fail, for their own next step to fix —
  `spot-deals-through-arkhai-payments` (D1–D8), `lapse-billing-with-the-site-lease`
  (D1–D4), `publish-wheels-through-a-gate` (D1–D6), `renewable-compute-lease-deadlines`
  (D2, D4), `unify-compute-delivery-path` (D1–D7), `negotiate-open-ended-compute-terms`
  (D1–D8), `add-arkhai-payments-lane-double` (D1–D7),
  `activate-per-period-compute-servicing` (D1–D4),
  `discover-open-ended-compute-listings` (D1–D4), and
  `converge-ongoing-compute-leases` (D1–D7).
- [x] 6.2 History wording (D24 item 2): a comment or docstring line the change's diff
  from its merge-base adds in a `.py`, `.toml`, `.yml` or `.yaml` file fails on
  "previously", "formerly", "used to", "no longer", "moved from", "was renamed" or
  "originally", naming the file and line, with no exception marker. Verify: unit tests
  for each word, for "now" and "legacy" passing, for a matching word in code rather
  than a comment passing, and library integration tests over a temporary Git
  repository showing only added lines are read.
  Done: `scripts/check_history_wording.py`, `make check-history-wording`, over the
  shared `scripts/change_diff.py` (the lines the diff from the merge-base adds,
  uncommitted and untracked included). Python comments from `tokenize`, docstrings from
  `ast`; a TOML or YAML comment is a `#` after whitespace outside a quoted value.
  Tests, `test_check_history_wording.py` (unit and library integration) and
  `test_change_diff.py` (library integration, real Git): each phrase, "now" and
  "legacy", code and strings, docstrings, only added lines, an unparsable file, an
  unknown base; dev's merged commits not the change's, the branch found on a remote,
  the newer copy of a lagging branch, odd hunk lines and paths, the user's diff
  prefixes. It found three comments on this branch, reworded.
- [x] 6.3 One version bump (D24 item 3): each `pyproject.toml` version that differs
  from the merge-base is exactly one SemVer step from it, lower parts reset; a missing
  bump is not checked. Verify: unit tests for 0.4.0 → 0.4.1, 0.5.0 and 1.0.0 passing,
  0.4.0 → 0.4.2 and 0.6.0 failing with the package and both versions, and a package
  bumped 0.4.0 → 0.4.1 → 0.5.0 on the branch passing.
  Done: `scripts/check_version_bumps.py`, `make check-version-bumps`; a package absent
  at the merge-base or without a version not checked, a version not
  `MAJOR.MINOR.PATCH` named. Tests, `test_check_version_bumps.py`: the planned steps
  and more (unit); 0.4.0 → 0.4.1 → 0.5.0 in two commits passing and 0.4.2 failing
  through the command (library integration, real Git).
- [x] 6.4 Local imports (D24 item 5): an import inside a function that the diff adds to
  a `.py` file has a comment on its own line or the line above, else the check names
  the file and line. Verify: unit tests for an added local import with and without a
  reason comment, a module-level import passing, and an unchanged local import not
  read.
  Done: `scripts/check_local_imports.py`, `make check-local-imports`, nested, async
  and method imports included; tool directives alone give no reason. Tests,
  `test_check_local_imports.py`: the planned cases and directives (unit); an
  unchanged import not read, and the command failing then passing (library
  integration, real Git).
- [x] 6.5 The capability index (D24 item 6): every `openspec/specs/<capability>/` with a
  `spec.md` has a row in `openspec/specs/README.md` linking it, and every row links one
  that exists; add the `contact-exchange-settlement` row. Verify: unit tests for a
  missing row and a row linking nothing; the check passes on the repository.
  Done: `scripts/check_capability_index.py`, `make check-capability-index`; the
  `Contact-exchange settlement` row added, with no companion. Tests,
  `test_check_capability_index.py` (library integration): a full index; a missing
  row; a dead link; a row linking no capability; the repository's index passes.
- [x] 6.6 Run the five checks from `scripts/check_change.py` after its existing ones,
  each named in its failure line, the diff-scoped ones against the merge-base with the
  branch the change lands on, `dev` by default. Verify: `scripts/tests/test_check_change.py`
  lists the new checks in order and reports each failure by name; `make check-change
  CHANGE=act-on-owner-intervention-patterns` runs all of them, failing only on the
  citation of the skill section 8 creates.
  Done: each check a `make` target `check_change.py` runs; `make check-change
  CHANGE=<change> [CHANGE_BASE=<branch>]` passes the branch to the three diff checks.
  Tests: `test_check_change.py` (unit), the commands in order, each failure by name,
  `CHANGE_BASE`; a `make -n` case. `make check-change` failed only on the citations of
  files sections 5 and 8 then had to create. Outside the plan, comment hygiene's
  exemption became a table (`design.md`, "Implementation record"), covered by
  `test_check_comment_hygiene.py`.
- [x] 6.7 Verification: the new checks' suites and `pytest -q
  scripts/tests/test_check_change.py` (unit, and library integration where a temporary
  Git repository is used) pass; `make test` passes. End-to-end: none; no scenario
  exercises the closing checks.
  Done: the eight suites, 124 passed; `make test-release-tooling` 2009 passed; `make
  check-comment-hygiene` passes. `make test` was not run for this section, the
  machine's uv then rewriting locks; it ran with section 4. End-to-end: none.
- Round 1 triage fix (64 F3, the owner chose C): the history-wording check reads a `#`
  line inside a YAML block scalar or a TOML multi-line string as a comment, its
  docstring saying so;
  `test_a_hash_line_in_a_block_scalar_or_multi_line_string_is_read_as_a_comment`
  pins it. `design.md` D24 item 2 records it.
- Round 2 triage fix (83 F1): the six closing checks' docstrings cite
  `openspec/specs/market-change-workflow/spec.md, MCW-c4ek`.

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
  Done: "Deferred work"; "Amend a rule or comply" after "Asking the owner"; "Domain
  docs" without its ADR sentence or the directory-drawn contexts D11 removes, naming
  the three homes. Both documents removed; the change's own documents name them so the
  citation check does not read a path. The `git grep` prints nothing.
- [x] 7.2 Rewrite `docs/agents/domain.md` to name the vocabulary's homes and state the
  rule for terms, without `CONTEXT.md`, `CONTEXT-MAP.md`, `/domain-modeling` or ADRs
  (D11, D23). Verify: the document holds D11's table and rule and none of the removed
  references.
  Done: D11's table, each home linked, and the rule; `git grep` finds none of the
  removed references outside `openspec/changes/`.
- [x] 7.3 `openspec/README.md`: add a "Defects found during a change" section after
  "Plan closeout requirements" in D6's wording, so skills cite a stable heading, and
  replace the scope-creep sentence with D6's (D6). Verify: the section's anchor,
  `openspec/README.md#defects-found-during-a-change`, resolves for the skills of
  sections 9 and 10 to cite.
  Done: the section, D6's paragraph verbatim, and the scope-creep sentence linking it;
  the anchor resolves.
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
  Done: "Reviews" (the `Alternatives:` field, `### Default acceptance` with the rule,
  the `Classification:` line, the table, and the advancing default); "Orchestrating a
  change" (**Interrupting a running step**, **Revisiting a default acceptance**);
  `## Waivers`; "The ledger" (the revisit entry, the recommended-waiver line);
  "Skills" (the five checks, `CHANGE_BASE`, D12's paragraphs); `stop` in "The engine's
  command". Commands checked against `scripts/change_workflow/cli.py`'s parsers.
- [x] 7.5 `docs/development/ARCHITECTURE.md`: add an "Implementation rules" section
  before "Testing strategy", with "No speculative guard code" (D8) and "Prefer an
  existing library" (D10), and its row in the document map. Verify: the document map
  links the new section's anchor.
  Done: `## Implementation rules`, a paragraph per rule; the map links
  `#implementation-rules`.
- [x] 7.6 Verification: `make check-doc-citations
  CHANGE=act-on-owner-intervention-patterns` reports only the citation of the skill
  section 8 creates; `make check-change CHANGE=act-on-owner-intervention-patterns`
  fails on nothing else. End-to-end: none; no scenario exercises the guidance.
  Done: `make check-change` failed only on section 8's skill citation; the new anchors
  checked by hand; `make test` passed, its scripts suite 2366. End-to-end: none. The
  fresh-context check's fixes brought `ARCHITECTURE.md`'s rules back to D8's and D10's
  terms and the "Waivers" and ledger text in line with CW-n6wy.

## 8. Guidance reviews have a skill (D20, D21)

Delivers `guidance-review` and its period ledger. Implements D20, D21, and the delta
requirement `CW-g6ua`. Touches a new `.agents/skills/guidance-review/SKILL.md`, its
links under `.claude/skills/` and `.codex/skills/`, `.gitignore`, and, for the roles
test, `openspec/specs/market-change-workflow/README.md`, "How this repository provides
the workflow's roles".

- [x] 8.1 Write `.agents/skills/guidance-review/SKILL.md`: run interactively by the
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
  Done: steps 1–6 are D20's six, and step 7 reports; `design.md`'s "Evidence" method
  in steps 2–4; only aggregates and principles reach the repository; a proposal is
  written in a worktree from `origin/dev`. The ledger line's fields: `start`, `end`,
  `changes`, `findings`, `default_acceptances`, `revisits_before_fix`,
  `revisits_after_fix`, `advancing_revisits`, `audit_sample`, `audit_disagreements`,
  `waivers` by criterion (`paths`, `environmental`, `commits`, `design`, `merge`), and
  `proposal`. What the skill settled beyond D20 is in `design.md`, "Implementation
  record".
- [x] 8.2 Link the skill from `.claude/skills/guidance-review` and
  `.codex/skills/guidance-review`, and add `openspec/changes/archive/guidance-reviews.jsonl`
  to `.gitignore` (D20). Every step is denied edits under `.claude/`, so the
  `.claude/skills/guidance-review` link is the orchestrator's, made on the owner's word
  before this section's session starts; the session makes the `.codex/` link, checks
  both resolve, and commits them with the section. Verify: `make check-agent-skills` passes; `git check-ignore`
  reports the ledger path ignored.
  Done: the `.gitignore` entry (`git check-ignore -v`: `.gitignore:252`); both links,
  each `-> ../../.agents/skills/guidance-review`, made by the orchestrator on the
  owner's word, since the step could make neither; `make check-agent-skills` passes.
- [x] 8.3 Keep the roles statement whole (`MCW-5tgp`): every make target and repository
  path the new skill names in code spans or fenced blocks — the period ledger's path
  among them — is listed in `openspec/specs/market-change-workflow/README.md`'s tables,
  the period ledger beside the changes' archive in "The engine's own assumptions"; no
  new role is added, since the ledger lives in the archive the engine already assumes.
  Verify: `pytest -q scripts/tests/test_change_workflow_assumptions.py` (unit) passes.
  Done: the archive's row names the period ledger; no role added. Found and fixed in
  place (D6): the roles test now reads every workflow skill
  (`test_the_guidance_review_is_read_and_openspecs_own_skills_are_not`). The roles
  suite, 11 passed.
- [x] 8.4 Verification: `make check-agent-skills` passes;
  `pytest -q scripts/tests/test_change_workflow_assumptions.py` passes; `make
  check-change CHANGE=act-on-owner-intervention-patterns` passes every check, the
  citation of the new skill now resolving. End-to-end: none; no scenario exercises the
  skills.
  Done: `make check-agent-skills` passes; the roles and command suites, 25 passed;
  `make check-change` passes all twelve checks; `make test` passed, its scripts suite
  2367. End-to-end: none.

The section's session stopped once, before committing, since it could make neither
skill link; the owner had both made, and the section was committed and pushed with
them.

## 9. Triage accepts uncontested findings by default (D1–D3, D6, D16, D18, D19, D22)

Delivers the triage skill's default acceptance. Implements D1, D2, D3, D16, D18, D19,
D6's triage outcomes, D22 at a review and validation of different commits, and the
delta requirements `CW-d5ac`, `CW-t9bx`, `CW-j1nv`, `CW-neua`, `CW-9pbk`, `CW-3tvs`,
`CW-v1rk`, `CW-n6wy`, `CW-r8vz` and `CW-q3dm`. Touches
`.agents/skills/change-triage/SKILL.md`, and, for the roles test,
`openspec/specs/market-change-workflow/README.md`.

- [x] 9.1 Write Rule E into step 2 as the classification each finding receives with its
  position, reading the reviewer's `Alternatives:` field, and the `Classification:`
  line and "accepted by default" disposition in step 4's record form (D3, D17, D18).
  Verify: the skill states every condition of D3 and the record form carries the D18
  example's fields.
  Done: step 2's **Alternatives** (read the reviewer's field, assign it for a pasted
  review) and **Default acceptance** (D3's five conditions, citing CW-d5ac; a finding
  of which not every condition can be said to hold, or a challenge to the owner's
  decision, is discussed); step 4's `Classification:` line and disposition, with
  D18's example.
- [x] 9.2 Rewrite step 3 so only discussed findings are presented one per message, the
  agenda lists them, and the "Accepted by default" table rides on the last question or
  goes in the final report; rewrite step 6 so an advancing recommendation is taken
  without asking and reported beside the table, another round is still asked, and a
  triage with nothing to discuss and an advancing recommendation asks nothing (D1,
  D2). Update "Running unattended" to match. Verify: the skill no longer requires a
  question for a default-accepted finding or for an advancing exit, and still forbids
  inferring a discussed finding's disposition from silence.
  Done: step 3 presents every discussed finding, the silence rule governing them; the
  table rides on the last question asked or the final report; step 6 takes an
  advancing recommendation without asking and asks another round; the opening, the
  description, `## Next`'s wording, and "Running unattended" follow.
- [x] 9.3 Add the resumed-triage path: resumed with the owner's revisit, the triage
  amends the fix in a new commit, appends the `revisits default acceptance:` ledger
  line, and names its exit again; a correction of a table item before the fixes is
  logged the same way (D16, D19). Verify: the skill's ledger section shows the D19
  example and names both moments.
  Done: step 4's ledger paragraph names both moments with D19's example; a new step 7
  handles the resume — branch and worktree checked, a `Revisit:` line and the ledger
  line, the amendment in a new commit, a contradiction with later commits a return,
  the exit named again and the status put back where the earlier advance set it.
  Outside the plan: a revisit of the advancing exit is a `revisits default
  acceptance:` entry with `"finding": "next"`, in the skill, the guide's "The ledger",
  and D19, and `guidance-review` counts it under the exit.
- [x] 9.4 Align the outcomes with `openspec/README.md#defects-found-during-a-change`:
  `fix` and `edit` cover a small, understood out-of-scope defect, recorded in the notes
  or triage record, and a large or vague one is `none`, recorded where `AGENTS.md`'s
  "Deferred work" says; and recommend a waiver at a review and validation of different
  commits when a criterion of `docs/agents/change-workflow.md`'s "Waivers" holds (D6,
  D22). Verify: `make check-agent-skills` passes.
  Done: step 2's outcomes cite the section; step 5's `fix` records an out-of-scope
  fix and a `none` records a large defect where "Deferred work" says; step 1
  recommends a waiver when a criterion holds, its ledger line naming the
  recommendation and criterion, a declined one named in the stop's `reason` and
  logged by the round's triage. `make check-agent-skills` passes.
- [x] 9.5 Verification: `make check-agent-skills` passes;
  `pytest -q scripts/tests/test_change_workflow_assumptions.py` (unit) passes, any make
  target or repository path the skill newly names listed in
  `openspec/specs/market-change-workflow/README.md`'s tables (`MCW-5tgp`); `make
  check-change CHANGE=act-on-owner-intervention-patterns` passes; a read of the skill
  against the scenarios of `CW-d5ac`, `CW-t9bx`, `CW-j1nv`, `CW-neua`, `CW-9pbk` and
  `CW-3tvs` finds each one stated. End-to-end: none; no scenario exercises the skills.
  Done: `make check-agent-skills` passes; the roles test, 11 passed, no new target or
  path; `make check-change` passes all twelve; `make test` passed, its scripts suite
  2367. The scenarios: CW-d5ac's in steps 2 and 4; CW-t9bx's in step 3; CW-j1nv's
  minor finding with alternatives and validation failure discussed; CW-neua's in step
  3's silence rule; CW-9pbk's in step 6; CW-3tvs's in steps 3 and 6 and "Running
  unattended". End-to-end: none.

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

- [x] 10.1 `change-orchestrate`: relay the table and an advancing exit as any message;
  on the owner's word, interrupt a running step with `scripts/change-workflow stop
  <change> [--step <step>]` and record the interrupt as an owner's decision resolving
  nothing (`scripts/change-workflow note <change> orchestrator --by owner …`), then
  recover the stop as the owner says; route a revisit in the order section 2's handoff
  gives — stop the step running after the triage, record `scripts/change-workflow note
  <change> orchestrator --by owner --resumes <seq> …`, resume the triage with the
  owner's words, then resolve the stopped step (D15, D16). Verify: the skill names each
  command as sections 1 and 2 implemented it and the merge placed it under
  `scripts/change-workflow`.
  Done: the table and advancing exit relayed with no prompt to confirm them; a new
  "Interrupting and revisiting", citing the guide, with `stop`, the interrupt's
  decision, recovery as any stop, and the revisit in order — each running step
  stopped, `note --by owner --resumes`, `resume --seq --answer`, then each stopped
  step resolved. Beyond the task (D22, CW-n6wy): the design-review waiver's ledger
  line names the design step's recommendation, a declined one a line left for the
  design review's triage to commit. Commands checked against
  `scripts/change_workflow/cli.py`.
- [x] 10.2 `change-review`: the design and pre-closeout scope lenses ask whether new
  scope is a small understood fix, kept, or large or vague work, split, and the
  implementation consistency lens admits a found defect the notes record, each citing
  `openspec/README.md#defects-found-during-a-change` (D6). `change-implement`: a
  small, understood defect found while implementing is fixed and recorded in the
  section's notes as outside the plan (D6). Verify: `make check-agent-skills` passes.
  Done: the three lenses as the task gives them, each citing the section, an
  unrecorded out-of-scope defect being a finding; `change-implement` step 3 fixes and
  records a small defect and records a large one where "Deferred work" says. `make
  check-agent-skills` passes.
- [x] 10.3 `change-design`: record decisions under `### D<n> — <title>` headings and
  name each in "Knowledge to promote" (D24 item 1); state documentation destinations,
  test levels and evidence rather than asking them (D12); ask the splitting question
  as `openspec/README.md#defects-found-during-a-change` frames it (D6); and, finishing
  after a return, recommend waiving another design review when a criterion holds
  (D22). `change-validate` recommends a waiver on a known environmental failure, and
  `change-archive-cleanup` before its validation, when a criterion holds (D22).
  Verify: `make check-agent-skills` passes.
  Done: `change-design` steps 5–7 and "Classify each decision" as the task gives
  them; `change-validate` step 5 recommends, beside the remedy, waiving a part on a
  known environmental failure, the record keeping the recommendation and answer;
  `change-archive-cleanup` recommends waiving its validation, and writes the line of
  each waiver a validation no triage read recommended. Outside the plan's file list:
  `change-plan` recommends waiving another design review after a return made in
  planning; `change-triage` step 1 logs a validation's waiver; the guide's "Waivers"
  and D22 name which step writes each line. `make check-agent-skills` passes.
- [x] 10.4 Verification: `make check-agent-skills` passes;
  `pytest -q scripts/tests/test_change_workflow_assumptions.py` (unit) passes, any make
  target or repository path the skills newly name listed in
  `openspec/specs/market-change-workflow/README.md`'s tables (`MCW-5tgp`); `make
  check-change CHANGE=act-on-owner-intervention-patterns` passes. End-to-end: none; no
  scenario exercises the skills.
  Done: `make check-agent-skills` passes; the roles test, 11 passed; `make
  check-change` passes all twelve; `make test` passed, its scripts suite 2367.
  End-to-end: none.
- Round 2 triage fix (84 O1, the owner chose A and formalized the waivable parts): any
  part of validation may be waived, by the owner alone; a waived part is `waived`, an
  omission of evidence counted in no result; a waiver for later validations is the
  owner's decision in the workflow log, which validation reads at its step 1 and which
  lapses at a merge or when its condition breaks; every part waived is the owner's
  direction past the guard. Delta spec: `CW-zkhs` and `CW-e7lm` modified, with three
  scenarios, and their `index.md` lines revised. `change-validate`,
  `change-orchestrate`, `change-triage`, the guide's "Waivers" ("Waiving parts of
  validation"), D22, and the proposal follow. Evidence: `make check-agent-skills`
  passed; the roles and history-wording suites, 35 passed; `make check-packaging`
  passed; `make test` passed, its scripts suite 2367; `make check-change` passes all
  twelve.

## 11. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [x] 11.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the change's
  own history-wording check (section 6) passes on its diff; a comment that needs
  rewriting returns the change to implementation.
  Done: `make check-comment-hygiene` passes; `make check-history-wording` passes on
  the diff since `dev`. A read of the comments the change added since `origin/dev`
  found none naming the review, decision, or migration that introduced it.
- [x] 11.2 Import placement: confirm every import sections 1–6 added inside a function
  carries its reason, which the local-import check (section 6) reports; one that should
  move returns the change to implementation.
  Done: `make check-local-imports` passes. The one added local import,
  `uv_project.py`'s version check, stays local for the reason beside it: the image
  builds copy that script alone.
- [x] 11.3 Documentation compliance: re-check D1–D30 against `openspec/README.md`'s
  placement rules and the destinations named in 11.9 (D30, 55 F2), each rule in the
  capability that owns it — the engine's in `change-workflow`, this repository's in
  `market-change-workflow`; and confirm the proposal's "Public interfaces of the
  workflow's engine" still names every public interface the change altered, and
  whether each is compatible (`CW-c2tw`).
  Done: each decision's destination is its placement rule's home — normative rules in
  the two specifications by their deltas (the engine's D1–D3 and D15–D22 in
  `change-workflow`, this repository's D24, D27 and D29 in `market-change-workflow`),
  rationale in their `README.md` companions, contributors' procedure in
  `docs/agents/change-workflow.md`, repository-wide rules in `AGENTS.md`,
  `openspec/README.md` and `ARCHITECTURE.md`, packaging in `BUILD_AND_PACKAGING.md`;
  the record is in `design.md`. Against the code: `change-workflow`'s README did not
  list `stop` among the public subcommands nor `guidance-review` among the skill
  names, and said the wrapper resumed no finished run; corrected in 11.9. The
  proposal's interfaces omitted the validation record's `waived` part and the ledger
  line's two new values, both compatible; added.
- [x] 11.4 Narrative compression: shorten completed task notes to final behaviour,
  material evidence (the uv release of 4.1, the gitleaks release, the nested
  extension, and the tree counts of 5.2, the active changes 6.1 listed), and
  destinations; section 5's gate-run notes compress to what design decided from them.
  Done: the notes keep each task's behaviour, tests and counts, the material evidence
  named, and destinations; handoffs since carried out, stop-and-resume narratives,
  and fresh-context fix lists were cut. What implementation settled or declined, and
  the defects it fixed in place, moved first to `design.md`, "Implementation record";
  section 5's gate run is one paragraph pointing to "The secret scan's rules".
- [x] 11.5 Roadmap currency: record in the promotion record that the change has no
  roadmap impact — it serves no goal of `docs/development/ROADMAP.md` and closes no gap
  row there.
  Done: `ROADMAP.md` names neither the change nor its area; the promotion record says
  so.
- [x] 11.6 Campaign index currency: set the change's row in `openspec/changes/README.md`
  to `in closeout` with notes matching what is now true, and run
  `make check-change-index`; the change has no campaign graph entry, and its
  dependents are released at archive cleanup.
  Done: the row, under "Independent active changes", is `in closeout`, its notes
  rewritten for closeout; no graph or other row edited. `scripts/change-workflow
  check index` passes.
- [x] 11.7 Packaging: run `make check-packaging` and `make check-architecture-change
  CHANGE=act-on-owner-intervention-patterns`, and `make check-agent-skills`, since the
  change touched `.agents/` and the skill links.
  Done: all three pass; the change owns no architecture row; no tracked file was
  rewritten.
- [x] 11.8 End-to-end pipeline: record the latest passing pipeline run, its commit, and
  that no scenario exercises the change's behaviour, the run being evidence only that
  section 4's uv builds and runs the stack.
  Done: the latest validation, 90 at `9b3943005` (the pre-closeout commit, which
  closeout's documentation-only commits follow), passed with the pipeline waived under
  the owner's standing waiver (workflow log seq 125) and the waiver's lapse test
  checked; the last pipeline run, `e2e.yml` run 42056791513 in validation 85 at
  `41d7cb435`, after the merge of `dev`, passed all three lanes, with the Helm part. No scenario exercises the change's behaviour; that run
  is evidence only that uv 0.12.22 builds and runs the stack. Owed by validation, from
  90's `## CI`: `tests.yml` run 42068322600, job `test · test-deployment-packaging`,
  success — `setup-uv` installed uv 0.12.22, the four `test_check_locks_uv.py` cases
  ran among 2367 passed with none skipped (4.5), and "Install the pinned gitleaks"
  installed 8.30.1 with its checksum checked and the real-scanner cases ran (5.6);
  baseline `dev` run 42029903285 at `a449117b3`, no other job failing.
- [x] 11.9 Promotion: write the permanent documents and the design-promotion record:
  - `openspec/specs/change-workflow/spec.md`, a `## Terms` section by hand, with round,
    round view, pass, exit, direction, guard, join, record, waiver, default acceptance,
    revisit, and interrupt (D11); its requirements arrive by the archive in 11.11.
  - `openspec/specs/change-workflow/README.md`: its opening (the owner reads every
    finding, discussed or in the table); "The owner is interrupted only for judgement"
    (D2, the advancing default); "The orchestrator relays and routes" (D14's principle
    that the owner can always reach a running step, and D15); "Reviews are files"
    (D17); "Triage" (D3's rationale and Rule E's baseline, D4, D16, D20, D21); "The
    intervention ledger" where its account of what is logged no longer holds (D19,
    D22); and its account of validation's parts and result, which must say a part the
    owner waived is `waived`, counted in no result, and how a standing waiver lapses
    (D22, `CW-zkhs`, `CW-e7lm`; 84 O1). Its sections follow `index.md`'s parts, so a new group of the index —
    "Guidance reviews", under "Reviews and triage" — has its paragraphs under that
    part.
  - `openspec/specs/market-change-workflow/README.md`: a section for its index's part
    "This repository's checks", holding "Secret scanning" as the merge placed it (D24
    item 4, D26, D28, D29; 65 O3) beside the closing checks and the lock revision in
    brief, each pointing to the document that details it.
  - Both capabilities' `index.md`: the entries for the ids the deltas add were written
    with the re-targeted deltas, before implementation, since the index check fails a
    change whose delta adds an id its index omits; and the summary lines of `CW-9pbk`,
    `CW-3tvs`, `CW-j1nv` and `CW-neua` were revised then, and of `CW-zkhs` and
    `CW-e7lm` by round 2's triage (84 O1). Confirm each entry's group
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
  Done: `change-workflow/spec.md` gains `## Terms` with the twelve terms, between
  "Purpose" and "Requirements". `change-workflow/README.md`: the opening; "The owner
  is interrupted only for judgement" (the advancing default and its evidence, and
  why steps recommend waivers); the validation account (owed CI unless waived, and
  waived parts, standing waivers and their lapse); "Reviews are files" (alternatives);
  "Triage" (the default rule, its evidence and Rule E's baseline, the classification,
  and the revisit, outside the graph); a new "Guidance reviews" under "Reviews and
  triage" (D20, D21); "The intervention ledger" (revisits and recommended waivers);
  "The orchestrator relays and routes" (the owner can always reach a running step,
  the interrupt, the held lock and its accepted window); and, found by 11.3, `stop`
  in the public subcommands, `guidance-review` among the skill names and in "Leaf
  skills", and the resume of a finished triage under a revisit.
  `market-change-workflow/README.md`: "This repository's checks" — the closing checks
  and one lock revision, each pointing to its detail, and "Secret scanning" beneath
  them, its anchor unchanged. Both `index.md`: every entry's group and summary hold as
  implemented; none revised. The record, with the roadmap's no-impact disposition and
  the index row, is `design.md`'s "Design promotion record". After the archive, every
  added id is in its `spec.md` once, `MCW-s8gk` and `MCW-u2dt` with their scenarios,
  and `make check-spec-index` passes unscoped.
- [x] 11.10 Documentation citations: run `make check-doc-citations
  CHANGE=act-on-owner-intervention-patterns` and resolve every match, then
  `openspec validate act-on-owner-intervention-patterns --strict`.
  Done: after promotion, `make check-change` passed every check, its documentation
  citations, specification index with the deltas counted, and the pinned strict
  `openspec validate` among them.
- [x] 11.11 Archival: `openspec archive act-on-owner-intervention-patterns -y`, merging
  the `change-workflow` delta into `openspec/specs/change-workflow/spec.md` and the
  `market-change-workflow` delta into `openspec/specs/market-change-workflow/spec.md`
  (no `--skip-specs`); the row then links the archived directory.
  Done: the pinned 1.14.0 (through `npx`, `bunx` being absent) archived the change as
  `2026-11-05-act-on-owner-intervention-patterns`: `change-workflow` +11 ~6,
  `market-change-workflow` +4, no `--skip-specs`, since neither spec held the deltas.
  The merged diff holds each added requirement once inside "Requirements", the six
  modified ones as the delta states them, and nothing else changed. The row links the
  archive; `make check-change` passes on the archived change.
  Closeout review 95's triage, after the archive: the citation this change's design
  added to `openspec/changes/layer-engineering-guidance/design.md` now points to
  `openspec/specs/change-workflow/README.md`, since the merge brought in that
  companion's rename from `architecture.md` (95 F1). The headings of `CW-3tvs`,
  `CW-j1nv` and `CW-neua` in `openspec/specs/change-workflow/spec.md` now state the
  default-acceptance exception their bodies define, their ids unchanged, and
  `index.md`'s links follow them, with `CW-3tvs`'s summary revised (95 F2). The
  archived delta keeps the headings it merged.
