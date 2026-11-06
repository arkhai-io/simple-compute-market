# Tasks

Sections 1–3 are the configuration contract in the engine; sections 4–6 replace the
engine's held values with the configuration or a derivation and give this repository
its configuration and targets; sections 7–9 move the callers — the skills, the
closing checks, the step table, the guide. Section 10 is the closeout; section 11,
placed before it, is the module-list fix closeout's task 10.1 returned the change
for. Every script
suite named below runs under `make test-release-tooling` (`pytest -q scripts/tests`),
which `make test` reaches through `test-deployment-packaging`. Levels are
`docs/development/TESTING.md`'s: a test over fakes is unit; one over a real Git
repository or real processes is library integration.

No end-to-end scenario in `e2e-tests/` exercises the change workflow's tooling, its
skills, or the repository's checks, and none is owed: they run on a developer's
machine and in CI, not in the deployed stack. The pipeline still runs on every
validation. Sections 3, 6, and 7 change how validation itself runs — its parts
through `scripts/change-workflow run`, and the `run-e2e`, `run-ci`, `validate-local`,
and `validate-helm` targets they call — so the round's own validation, run by the
moved skill through the moved targets, is evidence for them; its record says so.

**What the closing checks report until closeout.** `make check-change` fails on two
checks every section expects, and on nothing else: the documentation citations of
files the change creates (`.agents/workflow.toml`, `scripts/change_workflow/config.py`,
`scripts/change_workflow/hooks.py`, and their tests) until they exist, and the
specification index, which wants `index.md` entries for the 21 ids the deltas add,
the three renamed requirements' links moved, and MCW-ca51 and MCW-y37w retired —
entries closeout's promotion writes (task 10.9). Any other failure is the section's
to fix.

**Ordering of the `.claude/` edits.** Every step is denied edits under `.claude/`,
and an unattended session is started by the engine as it stands before the session.
So the step table changes once, before section 7's session starts (task 7.1), when
the engine of sections 4–6 already reads models from the configuration and section
6's session has written `.agents/workflow.toml`. Until then the step table keeps its
`models` and `[orchestrator]` rows, which section 4's loader no longer reads; section
8 makes the loader refuse them once they are gone (task 8.3). The deny rule on the
configuration (D14) lands with the same edit, after the file exists.

Closeout compressed the task notes below to final behaviour, evidence, deferrals,
and destinations; the decisions they recorded are in `design.md`, "Decisions settled
during implementation", and the full notes are in this file's history.

## 1. The configuration and its check (D1, D6, D12, D13, D15, D16)

Delivers the configuration's loader and check, its fields' kinds, and the
subcommands that read it: `config`, `config load`, `config parts`, and `check
config`. Implements CW-f3qk, CW-w8ne, CW-t5hz, CW-l7hn, CW-o6kc, and the plan half of
CW-g4oz. Touches a new module `scripts/change_workflow/config.py`,
`scripts/change_workflow/cli.py`, `scripts/change_workflow/tasks.py` (reading `Owed
by validation:` lines), and new tests in
`scripts/tests/test_change_workflow_config.py`.

- [x] 1.1 Add `scripts/change_workflow/config.py`, which reads `.agents/workflow.toml`
  from the repository the command acts on with `tomllib` and checks all of it as it
  loads (D13, D15, CW-w8ne): the tables and keys the workflow defines — `repository`
  (`protected-branches`, `inert-paths`), `hooks` (`after-functional-change`,
  `pre-commit`, `pre-commit-functional`, `pre-archive`, `pre-push`, `post-clone`),
  `defaults` (`disable`, each entry a check name and a reason), `openspec`
  (`command`), `load` (`common` and a key per step of the graph), `models`
  (`orchestrator` and a key per step), and `validation` (`preflight`, `parts.<name>`
  with `run`, or `start` and `collect`, `owed`, `after`, `evidence`, `cleanup`); a
  hook or part command as a string or a list of strings; refusing, naming the field,
  an unknown table or key, a wrong type, a part with neither or both shapes, an
  `after` naming no declared part, a `defaults.disable` entry naming no default check
  or giving no reason, and a placeholder unknown or unavailable where it is used (the
  per-hook vocabulary of D8: `{change}` and `{base}` everywhere, `{remote}` only in
  `pre-push`, `{owed}` only in an owed part's commands, `{after}` only in a
  `collect`). No file reads as every field absent. Verify: unit tests in
  `scripts/tests/test_change_workflow_config.py`, one per refusal and the scenarios
  "A key is misspelled" (CW-w8ne) and "A placeholder is used where it is
  unavailable" (CW-v2dq).
  - Done: `config.check`; 31 refusal cases, each naming its field, and "A key is
    misspelled" through every reading subcommand and `start design` (unit). What a
    placeholder is, and empty part lists refused: `design.md`, "Decisions settled
    during implementation".
- [x] 1.2 Give each field its kind (D12, CW-t5hz): required —
  `hooks.pre-commit-functional`, at least one validation part,
  `repository.protected-branches`, the models of each step run unattended and of the
  orchestrating session — and an explicit empty value counting as declared; every
  other field optional. Expose a query a caller asks before acting, naming the
  missing field, so `start` refuses a step needing an absent required field before
  launching anything (wired into `start` here, for the fields this section's callers
  read). Verify: unit tests for "No functional checks are declared" and "A repository
  declares no functional checks on purpose" (CW-t5hz) against `start implement`.
  - Done: `config.missing`, `require`, `require_for_step`, and `config.STEP_NEEDS`;
    both scenarios' start halves pass (library integration, a real `git init`).
    `.agents/workflow.toml` was first written here rather than in 6.1, since `start`
    would otherwise have refused the next session in this repository.
- [x] 1.3 Add `scripts/change-workflow config [--json]`, listing every field and how
  it resolved — declared, default, disabled, or absent — with the command it resolves
  to (D16, CW-o6kc), and `scripts/change-workflow check config`, running the check
  alone (D13). Verify: unit tests for the scenario "An optional hook is absent"
  (CW-o6kc) and for `--json`'s structure; a disabled default listed with its reason.
  - Done: `config.resolution`; `--json` is `{"file", "exists", "fields": [{"field",
    "status", "value"?, "reason"?}]}`. The tests pass (unit).
- [x] 1.4 Add `scripts/change-workflow config load <step>`, printing `load.common`
  then `load.<step>` (D6, CW-l7hn). Verify: unit test for "Design loads the roadmap"
  (CW-l7hn).
  - Done: passes (unit); a document listed in both is printed once.
- [x] 1.5 Add `scripts/change-workflow config parts <change> [--json]`, validation's
  plan (D3, CW-g4oz): the preflight, then each run of a part in declaration order with
  its shape, its `after`, and its evidence; an owed part once per `Owed by
  validation:` line of a complete section of the change's `tasks.md`, named by its
  part and that line's workflow, or once as `not owed`. Reading the owed lines is
  `scripts/change_workflow/tasks.py`'s, beside its section parsing. Verify: unit tests
  for "Two sections owe CI workflows" and "No section owes CI evidence" (CW-g4oz),
  and an owed line under an incomplete section ignored.
  - Done: `tasks.owed_lines` and `config.plan`; the tests pass (unit). Two lines owing
    one workflow are one run (`design.md`).
  - Fix, implementation triage 28 F4: the check also refuses an `after` naming a part
    declared later, ruling out every cycle, and a started part's `after` naming a
    `run` part (D3, CW-g4oz). Unit, config suite.
- [x] 1.6 Verification: `pytest -q scripts/tests/test_change_workflow_config.py
  scripts/tests/test_change_workflow_cli.py scripts/tests/test_change_workflow_cli_steps.py`
  (unit) passes; `make test` passes. End-to-end: none; no scenario exercises the
  workflow tooling.
  - Done: the three suites (281), `make test-release-tooling`, and `make test`
    pass. End-to-end: none.

## 2. Hooks run through the engine (D2, D7, D8, D9, D11)

Delivers `scripts/change-workflow run <hook> <change>` for the lifecycle hooks, with
their lists, the default checks and `disable`, the placeholders, the tier a commit's
paths give, the engine's hook table and the marker naming the step, `check change`,
and `openspec`. Implements CW-b2xr, CW-k9vd, CW-u4pc, CW-y6mj, CW-e1sg, CW-c8lw,
CW-v2dq, and CW-i2we. Touches `scripts/change_workflow/config.py`, a new
`scripts/change_workflow/hooks.py`, `scripts/change_workflow/graph.py` (the hook
table beside the graph), `scripts/change_workflow/harness.py` (the marker),
`scripts/change_workflow/wrapper.py`, `scripts/change_workflow/cli.py`, and tests in
`scripts/tests/test_change_workflow_hooks.py`.

- [x] 2.1 Run a hook's commands (D2, D8, CW-k9vd, CW-v2dq): each command's
  placeholders filled, shell-quoted, and run with `sh -c` from the repository's root,
  its output passed through; a list run in order whatever an earlier command
  reported, the hook failing when any failed and naming each. `{change}` is the
  change's name; `{base}` comes from the landing branch (section 5 supplies it; until
  then the caller gives it). Verify: unit tests for "Two checks fail" (CW-k9vd) and a
  value with spaces and quotes reaching the command as one word.
  - Done: `hooks.Hooks`; each command printed before it runs, and the engine's
    closing line ends each hook. "Two checks fail" (unit) and the quoting (library
    integration, a real `sh`) pass.
- [x] 2.2 Hold the hook table beside the graph (D9, CW-u4pc): which steps may run
  `after-functional-change`, `pre-commit-functional`, `pre-commit`, `pre-archive`,
  validation's preflight and parts, and `cleanup`; `pre-push` and `post-clone` run by
  no step. Make the unattended marker (`harness.UNATTENDED_RUN`) carry the run's step
  name where it carried `1`, set by the wrapper for each run and resume, and the
  review's runner for a review; `run` refuses a hook the marker's step is not listed
  for, naming both, and restricts nothing with no marker. Every reader of the marker
  (`cli` refusing `record` inside an unattended run) reads any non-empty value as
  unattended. Verify: unit tests for "Validation asks for a functional hook"
  (CW-u4pc), an interactive `run` unrestricted, and `record` still refused inside a
  run.
  - Done: `graph.HOOK_STEPS`; the marker is `common.UNATTENDED_RUN`. The scenario and
    an interactive `run` (library integration), `record` refused, the wrapper and
    review marking runs (unit), and the harness marking real child processes
    (library integration) pass. The fragment's make variable of the marker's name was
    renamed (`design.md`), with a library-integration test of a real `make`.
- [x] 2.3 Run `pre-commit`'s default checks before its declared commands (D11,
  CW-c8lw): `index`, `tasks`, `skills`, and `openspec` — the strict validation of the
  change, or of every specification for an archived change — each skipped only when
  `defaults.disable` names it; and add `scripts/change-workflow check change
  <change>`, running them alone. Add `scripts/change-workflow openspec <arguments>`,
  running `openspec.command`, or `openspec` on the path, with the arguments (D11,
  D16, CW-i2we); the default validation runs through it. Verify: unit tests for "A
  repository declares its own pre-commit" and "A default check is turned off"
  (CW-c8lw), and "A repository pins the validator" (CW-i2we) with the runner faked.
  - Done: the three scenarios pass (unit), and `openspec` through a real `sh`
    (library integration).
- [x] 2.4 Give `run pre-commit` its tier (D7, CW-e1sg): from the worktree's changes
  against `HEAD` — staged, unstaged, and untracked — when any path lies outside
  `repository.inert-paths`, run `after-functional-change`, then
  `pre-commit-functional`, then `pre-commit`, each held to the hook table; otherwise
  `pre-commit` alone. Refuse when `pre-commit-functional` is absent and the tier needs
  it (CW-t5hz). Verify: library-integration tests over a real Git repository for "A
  triage fix changes only documents" (CW-e1sg), a functional change running all three
  in order, a clean worktree running `pre-commit` alone and changing nothing
  (CW-y6mj), and a design step's functional change refused by the table.
  - Done: `hooks.worktree_changes` and the shared inert-path matcher; the four
    scenarios, staged, untracked, and renamed changes, and CW-t5hz's commit halves
    pass (library integration). How an inert path matches, and records outside the
    inert paths: `design.md`.
- [x] 2.5 Run `pre-archive` through `run pre-archive <change>` for closeout, and
  `after-functional-change` alone through `run after-functional-change <change>`, both
  held to the table (D2, D9). Verify: unit tests that each runs its declared commands
  and that an absent optional hook is skipped, the run saying so (CW-t5hz).
  - Done: both pass (unit); `run pre-commit-functional` is runnable by name too.
- [x] 2.6 Verification: `pytest -q scripts/tests/test_change_workflow_hooks.py
  scripts/tests/test_change_workflow_config.py scripts/tests/test_change_workflow_harness.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_workflow_review.py
  scripts/tests/test_change_workflow_cli.py` (unit, and library integration where a
  real Git repository is used) passes; `make test` passes. End-to-end: none; no
  scenario exercises the workflow tooling.
  - Done: the suites (493), `make test-release-tooling`, and `make test` pass.
    End-to-end: none.

## 3. Validation's parts and the invocation record (D3, D10)

Delivers `run` for validation's preflight, its parts' `run`, `start`, and `collect`,
named owed runs, the kept marker, the engine's closing line, `run cleanup`, and the
`invoked` record of every invocation through `run` or the guarded push on the run's
log line. Implements CW-g4oz (running), CW-x9bt, CW-q5fy, CW-ikmm, and CW-zkhs.
Touches `scripts/change_workflow/hooks.py`, `scripts/change_workflow/running.py` or a
new state file under the change's records for the kept markers and pending
invocations, `scripts/change_workflow/wrapper.py`, `scripts/change_workflow/log.py`
(the optional `invoked` field), `scripts/change_workflow/cli.py` (`record`), and
`scripts/change_workflow/push.py`.

- [x] 3.1 Add `run validation <change> preflight`, `run validation <change> <part>
  run`, and `run validation <change> <part> start|collect [--owed <workflow>]` (D3,
  D8, CW-g4oz, CW-zkhs): `--owed` required by an owed part and refused by any other,
  filling `{owed}`. Each ends with the engine's closing line — the part, its owed
  workflow, the commit, `passed` or `failed`, the exit status, and the evidence
  directory — whatever the command printed (D10). Verify: unit tests for each shape,
  `--owed` required and refused, and the closing line's form.
  - Done: `Hooks.validation`; the closing line `[change-workflow] validation
    <part>[ <owed>] <phase> at <commit>: passed, exit 0; evidence <dir>`, and every
    hook's line carries its exit status. The tests pass (unit), an owed start and
    collect through a real `sh` (library integration).
- [x] 3.2 Keep a `start`'s marker, its last line of standard output, keyed by the
  commit, the part, and the owed workflow, a later `start` of the same key replacing
  it, and fill `{after}` from it in the matching `collect`; a `collect` with no kept
  marker refuses, naming the `start` to run (D10, CW-x9bt). Verify: unit tests for
  "Two owed runs are collected side by side" and "The pipeline is collected"
  (CW-x9bt), and a retried `start` replacing the marker.
  - Done: kept in `<git-dir>/change-validation/<change>.json` under a lock; a failed
    or silent start removes its key's marker. The scenarios and the replacement pass
    (unit), the output capture with a real `sh` (library integration).
  - Fix, implementation triage 31 A1: declared commands run without the calling
    make's variables (`design.md`); a real `make` under `MAKELEVEL=1` keeps its marker
    (library integration).
- [x] 3.3 Add `run cleanup <change>`, running every declared part's `cleanup` in
  declaration order as one list (D3, CW-ikmm). Verify: unit tests for "A change's
  validation left resources" and "A part's cleanup finds nothing" (CW-ikmm) with the
  commands faked.
  - Done: `Hooks.cleanup`; both scenarios pass (unit; one through a real `sh`).
- [x] 3.4 Record every invocation (D10, CW-q5fy): `run` and the guarded push keep, by
  the session's id (`CLAUDE_CODE_SESSION_ID`), each hook, part, and command with its
  owed workflow and phase, the resolved command, its exit status, when it started,
  and how long it took; the wrapper adds them as `invoked` to the run's log line and
  `record` to an interactive run's; nothing is kept outside a session. The field is
  optional, so `common.FORMAT` stays 2. Verify: library-integration tests for "A
  step's push is refused by the pre-push hook" and "Validation's Helm part fails"
  (CW-q5fy), with the push's hook faked; a line without `invoked` read unchanged by
  the next-step computation's tests in `scripts/tests/test_change_next_step.py`.
  - Done: `running.keep_invocations`, `kept_invocations`, `drop_invocations`, in
    `<git-dir>/change-invocations/<session>.jsonl`. Both scenarios pass through the
    wrapper (library integration); `record` taking them (library integration); a line
    with `invoked` routes as one without (unit).
  - Known limit (`design.md`): a review on Claude retried after a network error takes
    only its last attempt's invocations.
- [x] 3.5 Verification: `pytest -q scripts/tests/test_change_workflow_hooks.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_workflow_log.py
  scripts/tests/test_change_workflow_cli_steps.py scripts/tests/test_check_push_ready.py
  scripts/tests/test_change_next_step.py` (unit, and library integration where a real
  Git repository or process is used) passes; `make test` passes. End-to-end: none in
  `e2e-tests/`; the round's validation, run through these commands once section 7
  moves the skill, is their evidence.
  - Done: the suites (677), `make test-release-tooling`, and `make test` pass.
    End-to-end: none in `e2e-tests/`.

## 4. The engine's held values come from the configuration (D5, D6, D7, D10)

Replaces the engine's constants with the configuration's fields: the protected
branches, the pre-push hook, the inert paths, the evidence history copies, the
documents the post-compaction hook re-reads, the models, and the clone's bootstrap.
Implements CW-59c7 (protected branches), CW-p7kq, CW-n7ra, the MODIFIED CW-trdu,
CW-j1ab, CW-gqav, CW-8tdv, and CW-tnp6, CW-ebmo, CW-zq4h, CW-w2ld, and CW-8npg.
Touches `scripts/change_workflow/push.py`, `records.py`, `next_step.py`,
`history.py`, `hook.py`, `steps.py`, `wrapper.py`, `cli.py` (`start orchestrate`),
and `clone.py` (the bootstrap).

- [x] 4.1 The guarded push refuses `repository.protected-branches` where it refused
  `push.PROTECTED`, and runs `hooks.pre-push` through the hook runner with `{remote}`
  and Git's one ref line on its input where it ran `push.PRE_PUSH_CHECKS`, refusing
  with the hook's reasons; with no `pre-push` it pushes once its own check passes
  (D1, CW-59c7, CW-p7kq). The push's invocation is recorded as section 3 records it.
  Verify: tests in `scripts/tests/test_check_push_ready.py` (library integration, a
  real Git repository) for "The worktree is dirty", "The pre-push check refuses", "The
  repository provides no pre-push check", and a configured protected branch refused.
  - Done: `push.pre_push` through `Hooks.engine_hook`, its output on standard error;
    the push requires `repository.protected-branches`. The four scenarios pass
    (library integration). `pre-push` takes `{remote}` alone (`design.md`).
- [x] 4.2 The next-step computation and the records read `repository.inert-paths`
  where they read `records.DOCUMENTATION`, with no inert path when none is declared
  (D7, CW-n7ra, CW-trdu, CW-j1ab, CW-gqav, CW-8tdv, CW-tnp6). Verify: tests in
  `scripts/tests/test_change_next_step.py` and
  `scripts/tests/test_change_workflow_records.py` (unit) for "A repository marks
  images inert" (CW-n7ra), the existing documentation-correction and pre-closeout
  cases with `openspec/` and `docs/` declared, and the same commits read as code with
  no inert path declared.
  - Done: `records.inert` and `records.exempting`; the graph names exemptions by kind
    (`graph.RECORDS`, `graph.INERT`), and the graph diagram's guard texts say "inert
    paths". The tests pass (unit).
- [x] 4.3 History copies each declared part's `evidence` where it copied
  `history.VALIDATION` and `history.E2E_LOGS`, reading the cited runs and commits as
  it does (D3, D10). Verify: `scripts/tests/test_change_history.py` (library
  integration) passes with the evidence declared, and copies nothing for an
  undeclared directory.
  - Done: `Configuration.evidence()`; a commit or run no declared directory holds is
    reported absent under each. The suite passes (library integration).
- [x] 4.4 The post-compaction hook re-reads `load.common` where it read
  `hook.REQUIRED` (D6, CW-l7hn). Verify: a unit test of `hook post-compaction` naming
  the configured documents.
  - Done: passes, as library integration (`hook.context` runs a real `git`).
- [x] 4.5 Models come from the configuration (D5, CW-ebmo, CW-zq4h, CW-w2ld): the
  wrapper reads each step's ordered models from `models.<step>`, and `start
  orchestrate` from `models.orchestrator`; the engine refuses two models of one
  vendor for a step and a Codex model on any step but the review, naming the step;
  `steps._FORBIDDEN_MODEL` and its check are removed. The step table's loader stops
  reading and requiring `models` and `[orchestrator]`, and accepts their presence
  until the step table loses them before section 7 (task 8.3 then refuses them).
  Verify: tests in `scripts/tests/test_change_workflow_steps.py`,
  `test_change_workflow_wrapper.py`, and `test_change_workflow_cli_steps.py` (unit)
  for "A step's first model is available" (CW-ebmo), "A row names two models of one
  vendor" (CW-zq4h), "The owner starts the orchestrating session" (CW-w2ld), and a
  Fable model in the configuration no longer refused.
  - Done: `config._models`, `Configuration.step_models` and `orchestrator_model`;
    `start` requires an unattended step's models and the orchestrator's. The
    scenarios pass (unit; CW-w2ld in `test_change_workflow_cli.py`, library
    integration).
- [x] 4.6 The clone's bootstrap runs `hooks.post-clone` through the hook runner where
  it ran `clone.BOOTSTRAP_COMMAND`, succeeding at once with none declared, and its
  recorded state holds the resolved command beside its log and exit status (D10,
  CW-8npg). Verify: tests in `scripts/tests/test_change_clone.py` (library
  integration) for "The bootstrap failed", a clone with no `post-clone` usable at
  once, and the state naming the command.
  - Done, spawned in the background (it outlives the call) rather than through
    `Hooks`, each command with `sh -c`. The tests pass (library integration).
- [x] 4.7 Verification: `pytest -q scripts/tests/test_check_push_ready.py
  scripts/tests/test_change_next_step.py scripts/tests/test_change_workflow_records.py
  scripts/tests/test_change_history.py scripts/tests/test_change_workflow_steps.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_workflow_cli_steps.py
  scripts/tests/test_change_clone.py` (unit, and library integration where a real Git
  repository or process is used) passes; `make test` passes. End-to-end: none; no
  scenario exercises the workflow tooling.
  - Done: the suites with their neighbours (1119), `make test-release-tooling`, and
    `make test` pass. End-to-end: none.

## 5. The landing branch and the remote are derived (D4)

Records the branch a change lands on with its clone, exposes it as `find --json`'s
`base`, and has the merge, the review, the hooks' `{base}`, and clone removal read
it; derives the remote from the branch's upstream. Implements CW-s3ju, CW-hdxi,
CW-59c7 (the remote and a new branch's upstream), CW-xx5f, and CW-h8vm. Touches
`scripts/change_workflow/clone.py`, `find.py`, `review.py`, `push.py`, `cli.py`,
`hooks.py`, and `workflow.mk`, and the root `Makefile`'s
`CHANGE_WORKFLOW_MERGE_FROM` and `CHANGE_WORKFLOW_REVIEW_BASE`.

- [x] 5.1 `clone` records the landing branch — the workspace's checked-out branch, or
  `--from` — in the clone's marker, and gives a new change branch an upstream of its
  own name on the landing branch's upstream remote, as `branch.<name>.remote` and
  `branch.<name>.merge`; `clone.DEFAULT_FROM` is removed (D4, CW-s3ju, CW-59c7). Verify:
  tests in `scripts/tests/test_change_clone.py` (library integration) for a clone made
  from `dev` and from `main` recording each, the new branch's upstream configured
  before its first push, and "Orchestration is run again from another branch"
  (CW-s3ju).
  - Done: the marker's `base`, kept on every rerun; the marker is read in `find`. The
    tests pass (library integration).
  - Fix, implementation triage 28 F3: the push remote comes from Git's record in the
    workspace (`clone._push_remote`), no remote named in the engine; CW-8jyb modified
    and D4 records it. A workspace with no `origin`, a stale branch on another remote,
    a fork, and a removed remote are tested (library integration).
  - Left to the owner: the merge step's rules allow `git fetch origin *` and `git
    fetch workspace *` only, and the orchestrating skill pulls `origin dev`; both hold
    in this repository.
- [x] 5.2 `find --json` prints `base`, the recorded landing branch or `null` (D4,
  CW-s3ju); the merge, the review's base, and the hooks' `{base}` read it, an argument
  overriding it for one run (the merge's `FROM`, the review's `--base`), and a step
  needing it with none recorded or given refuses, naming the argument (CW-hdxi).
  `review.DEFAULT_BASE` is removed, and the fragment's `CHANGE_WORKFLOW_MERGE_FROM` and
  `CHANGE_WORKFLOW_REVIEW_BASE` with the root `Makefile`'s settings of them (CW-h8vm).
  Verify: tests in `scripts/tests/test_find_change.py`,
  `test_change_workflow_review.py`, and `test_change_workflow_cli_steps.py` (unit) for
  `base` printed and `null`, "A change worked in place merges with no base given"
  (CW-s3ju), the review reading `base`, and "A repository includes the fragment"
  (CW-h8vm) through `make merge FROM=<branch>`.
  - Done: `cli.merge_arguments`; the fragment passes `--base` and `from` only when
    given. The tests pass, as library integration (`landing_branch` runs `git`).
- [x] 5.3 The guarded push sends to the branch's upstream remote, or a remote given
  as `push --remote <remote>`, and refuses a branch with neither; `push.DEFAULT_REMOTE`
  is removed (D4, CW-59c7). Verify: tests in `scripts/tests/test_check_push_ready.py`
  (library integration) for "A new change branch is pushed first" and "A branch with
  no upstream" (CW-59c7).
  - Done: the `workspace` remote and `.` refused. Both scenarios pass (library
    integration).
- [x] 5.4 `clone-remove` judges the merge against the recorded landing branch on the
  branch's upstream remote, where it judged `origin/dev` and `origin`, and takes
  `--base <branch>` for a clone with none recorded, refusing without it (D4, CW-xx5f).
  Verify: tests in `scripts/tests/test_change_clone.py` (library integration) for
  "The owner removes a clone too early", "A change landed on another branch", and "A
  clone recorded no landing branch" (CW-xx5f).
  - Done: `--base` also overrides a recorded branch for the removal. The scenarios
    pass (library integration).
- [x] 5.5 Verification: `pytest -q scripts/tests/test_change_clone.py
  scripts/tests/test_find_change.py scripts/tests/test_change_workflow_review.py
  scripts/tests/test_change_workflow_cli_steps.py scripts/tests/test_check_push_ready.py
  scripts/tests/test_make_change_completion.py scripts/tests/test_validate_parallel.py`
  (unit, and library integration where a real Git repository is used) passes; `make
  test` passes. End-to-end: none; no scenario exercises the workflow tooling.
  - Done: the suites, `make test-release-tooling` (2574), and `make test` pass.
    End-to-end: none.

## 6. This repository's configuration and targets (D20, MCW-r4tx, MCW-k3vy)

Gives this repository its `.agents/workflow.toml` and the make targets it names.
Implements MCW-r4tx and MCW-k3vy, and D20's repository-side fixes but
`check_change.py`'s (section 8). Touches `.agents/workflow.toml` (new), the root
`Makefile`, `scripts/hooks/pre-push`, `scripts/validate_slice.py`,
`scripts/ci_evidence.py`, and their tests.

- [x] 6.1 Write `.agents/workflow.toml` as `design.md`'s "The configuration, as this
  repository declares it" gives it, with a `models` row for every step of the step
  table and its `[orchestrator]` model and effort as they stand, each field's comment
  saying who uses it (D1, D15, MCW-r4tx). Its `pre-commit` names `make
  check-repository`, which section 8 adds; until section 7 moves the skills, nothing
  runs that hook. Verify: `scripts/change-workflow check config` passes, and `config
  parts <change>` for a fixture change owing `tests.yml` lists the pipeline, `ci
  tests.yml`, local, and Helm after local (MCW-r4tx's scenario), in a test in
  `scripts/tests/test_change_workflow_config.py` that loads the repository's own file.
  - Done (the file from section 1; `pre-commit` and `pre-push` added here): each
    table's comment names who uses it. The config suite's test of the repository's
    own file runs the check and MCW-r4tx's scenario (unit); `check config` itself was
    denied the session, and the test runs the same check.
  - Fix, implementation triage 29 O2: `pre-commit-functional` begins with `make
    dist-clean`, made by the orchestrating session on the owner's word. Unconfirmed
    whether a same-version rebuilt wheel is reinstalled (`design.md`).
- [x] 6.2 Add `make pre-push REMOTE=<remote>`, running both public-content checks
  (`scripts/check_public_content.py --pre-push` and `scripts/check_secrets.py
  --pre-push`) under Git's hook contract, the ref lines read once from standard input
  and given to each, either refusing; `scripts/hooks/pre-push` runs it with its first
  argument (D20, MCW-k3vy, MCW-q8vd). Verify: a library-integration test over a real
  Git repository that the hook and `make pre-push` both refuse a commit adding a
  recognizable private path and pass a clean one, beside
  `scripts/tests/test_check_public_content.py` and `test_check_secrets.py` passing.
  - Done: the hook `exec`s `make -s pre-push REMOTE="$1"`; no newline is added to
    the updates, since an up-to-date push gives no input. The tests pass in
    `test_check_public_content.py` (library integration).
- [x] 6.3 End `make run-e2e`'s and `make run-ci`'s output with the bare marker their
  collect waits past — the newest run of the workflow on the branch before the
  dispatch — and fold `make dist-clean` into `make validate-local` and `make
  validate-helm` (D20). Verify: tests in `scripts/tests/test_ci_evidence.py` and
  `test_validate_slice.py` (unit) for the marker as the last line and the wheelhouse
  cleared before a building part; `scripts/tests/test_change_build_and_helm_targets.py`
  passes.
  - Done: `ci_evidence.py pipeline` dispatches `e2e.yml`; each dispatch ends with the
    run's id alone, `0` with no earlier run, and none after a refused dispatch. The
    `dist-clean` half was already true of `validate_slice.py`. The tests pass (unit;
    `make -n` of the targets, library integration).
- [x] 6.4 Remove `make code-snapshot` and its `.PHONY` entry (D20). Verify: `make -n
  code-snapshot` fails; `grep -rn code-snapshot Makefile` finds nothing.
  - Reverted, implementation triage 29 O1: the target and
    `scripts/tests/test_code_snapshot.py` are restored on the owner's word; it stays
    a target no skill names, and triage's sentence and the role and provision rows
    stay removed (D20). The restored test passes (library integration).
- [x] 6.5 Verification: `pytest -q scripts/tests/test_change_workflow_config.py
  scripts/tests/test_check_public_content.py scripts/tests/test_check_secrets.py
  scripts/tests/test_ci_evidence.py scripts/tests/test_validate_slice.py
  scripts/tests/test_change_build_and_helm_targets.py` (unit, and library integration
  where a real Git repository is used) passes; `make test` passes; `make
  check-packaging` passes. End-to-end: none in `e2e-tests/`; the round's validation
  runs `run-e2e`, `run-ci`, `validate-local`, and `validate-helm` as changed here, and
  its record is their evidence.
  - Done: the suites, `make test-release-tooling` (2591), `make test`, and `make
    check-packaging` pass. End-to-end: none in `e2e-tests/`.

## 7. The skills invoke hooks through the engine (D3, D6, D9, D14, D16, D17, D20)

Moves every skill from this repository's targets and documents to `run`, `config
load`, `config parts`, `run cleanup`, and `openspec`. Implements D17 and the skill
halves of CW-g4oz, CW-ikmm, CW-l7hn, CW-i2we, and CW-e1sg. Touches
`.agents/skills/change-*/SKILL.md`, `.agents/skills/guidance-review/SKILL.md`, and
`.claude/change-steps.toml` (the orchestrator's).

- [x] 7.1 Orchestrator's, on the owner's word, before this section's session
  starts, committed by the session with its section: in `.claude/change-steps.toml`,
  remove every row's `models` and the `[orchestrator]` row (D5); add
  `Edit(.agents/workflow.toml)` and `Write(.agents/workflow.toml)` to `[common]`'s
  deny rules (D14, CW-z5me); give each step that runs a hook
  `Bash(scripts/change-workflow run *)` and each step that runs OpenSpec
  `Bash(scripts/change-workflow openspec *)` in place of the pinned `bunx` and `npx`
  rules, and `Bash(scripts/change-workflow config *)` to `[common]`; remove
  validation's `make validate-*`, `make run-e2e`, `make run-ci *`, `make
  fetch-e2e-logs*`, `make dist-clean`, and `make check-uv-version`, and archive
  cleanup's `make -C helm teardown*` and `make record-capacity*` (D9), keeping every
  grant for engineering work. Verify: `scripts/change-workflow check config` and the
  step table's tests in `scripts/tests/test_change_workflow_steps.py` pass against the
  edited table.
  - Done: committed with section 7; planning also gained `check tasks`. The steps
    suite holds the edited table (unit, 42); `check config` was denied, and `config
    load implement` and the config suite's test ran the same check.
  - Left to the owner: the table still grants validation `gh run list*` and `gh auth
    status`, and closeout the bare `openspec archive *`, which no skill runs.
- [x] 7.2 Every skill that commits runs `scripts/change-workflow run pre-commit
  <change>` where it ran `make check-change`, and stages what the hooks rebuilt
  (D7, D17, CW-e1sg); implementation, triage, and the merge drop their own `make
  lock`, `make check-packaging`, and `make test` steps, which the tier now runs, and
  the merge takes one side of a conflicted derived file before `run pre-commit`
  rebuilds it (D2); closeout runs `run pre-archive` for its packaging part and
  `scripts/change-workflow openspec` for its validation and archive, and design and
  planning `openspec` for theirs (D11, CW-i2we); the review may run `run pre-commit`
  read-only (CW-y6mj). Verify: `grep -n "make check-change\|make lock\|make
  check-packaging\|make test\b\|bunx @fission-ai\|npx --yes @fission-ai"
  .agents/skills/*/SKILL.md` finds no invocation, only references for the owner.
  - Done: the grep finds only validation's prohibition of `make lock`. A merge that
    concluded itself runs `run after-functional-change` and `run
    pre-commit-functional` by name. The skills naming `openspec/` and `docs/` as
    needing no new validation now name the inert paths.
- [x] 7.3 Validation learns its parts from `scripts/change-workflow config parts
  <change>` and runs each through `run validation` — the preflight, every `start`
  dispatched first after the guarded push, then the `run` parts in order keeping each
  `after`, then every `collect` — with no `gh run list`, no `--after`, no
  `HELM_ALL_SCENARIOS` read from its arguments, and its diagnosis read from each
  part's evidence; the repository's own parts, Helm namespace, and pipeline stay
  described where the skill needs them to diagnose, for `add-skill-extension-points`
  to move (D3, D8, D10, CW-g4oz). Archive cleanup runs `scripts/change-workflow run
  cleanup <change>` where it ran `make record-capacity` and `make -C helm teardown`,
  and commits any tracked file it wrote on its own (D3, CW-ikmm). Verify: reading
  `change-validate/SKILL.md` and `change-archive-cleanup/SKILL.md`, every command
  they run is a subcommand of `scripts/change-workflow`, `git`, or `gh auth status`,
  besides the diagnosis's read-only `kubectl`, `docker`, and `helm` calls.
  - Done: each collect starts in the background after its start and is waited on
    after the `run` parts; `HELM_ALL_SCENARIOS` and `HELM_CONTEXT` reach the Helm part
    through the environment, so `make validate` no longer appends an argument
    (`test_validate_slice.py`, library integration). Read: every command is
    `scripts/change-workflow` or `git`, besides the diagnosis.
  - Fix, implementation triage 28 F2: validation no longer runs `gh auth status`.
  - Settled, implementation triage 28 F1: a cleanup's tracked file is committed on its
    own with no hook (CW-e1sg, D3).
- [x] 7.4 Every skill loads its documents from `scripts/change-workflow config load
  <step>` where it named `AGENTS.md`, `ARCHITECTURE.md`, `TESTING.md`,
  `DEPLOYMENT_AND_CONFIG.md`, `openspec/README.md`, and the roadmap as its reading
  list (D6, CW-l7hn); a citation of a guidance section for a rule stays. Triage's
  sentence naming `make code-snapshot` is removed (D20). Verify: `make
  check-agent-skills` passes; the delta scenario "Design loads the roadmap" holds for
  `change-design`.
  - Done: `make check-agent-skills` passes; `config load design` prints the common
    documents and the roadmap. `config load common` serves the orchestrating session
    and guidance reviews (D6, CW-l7hn). Closeout and the review read the roadmap for a
    part's purpose (`design.md`).
- [x] 7.5 Verification: `make check-agent-skills` passes;
  `scripts/tests/test_change_workflow_assumptions.py` is run and its failures are
  only those section 8 resolves (`.agents/workflow.toml` and the new subcommands'
  rules unlisted); `make test` passes but for those. End-to-end: none in
  `e2e-tests/`; the round's validation is run by the moved validation skill, and its
  record is the evidence for 7.3.
  - Correction: 7.2, 7.3, and 7.4 were checked in a later commit, their evidence
    re-run at `HEAD` after sections 8 and 9.
  - Done: `make check-agent-skills` passes; the assumptions suite failed only on
    `.agents/workflow.toml` unlisted, which 8.4 lists. End-to-end: none in
    `e2e-tests/`.

## 8. The closing checks, the step table's loader, and the inventory (D5, D11, D18, D20)

Makes `make check-change` the complete closing check over `run pre-commit`, adds
`make check-repository`, tightens the step table's loader, and brings the inventory's
tables to what the test now collects. Implements D11's closing-check part, D18,
CW-m4ps, MCW-5tgp, and MCW-r4tx's `pre-commit`. Touches `scripts/check_change.py`,
the root `Makefile`, `scripts/change_workflow/steps.py`,
`scripts/tests/test_change_workflow_assumptions.py`, and the role and provision
tables of `openspec/specs/change-workflow/README.md` and
`openspec/specs/market-change-workflow/README.md`.

- [x] 8.1 `scripts/check_change.py` drops the agent skills, task list, change index,
  and OpenSpec validation checks, which the default `pre-commit` runs, reads its base
  from `scripts/change-workflow find --json`'s `base` unless `--base` names one, and
  becomes `make check-repository CHANGE=<change> [CHANGE_BASE=<branch>]`: comment
  hygiene, documentation citations, the spec index, decision destinations, history
  wording, version bumps, local imports, and the capability index (D11, D20,
  MCW-r4tx). Verify: `scripts/tests/test_check_change.py` (unit) lists exactly those
  eight checks, reads `base`, and refuses with neither `base` nor `--base`.
  - Done: the suite passes (17; the list and arguments unit, the base cases library
    integration through a real `find --json`).
- [x] 8.2 `make check-change CHANGE=<change>` runs `scripts/change-workflow run
  pre-commit <change>`, so the four defaults and then `make check-repository` run,
  each once (D11). Verify: `make check-change CHANGE=add-workflow-capability-contract`
  prints the defaults and the repository's checks once each, and its failures are
  those `make check-change` reported before the change, no fewer.
  - Done: `CHANGE_BASE` becomes `--base`. Run with `CHANGE_BASE=dev`, each check ran
    once, the functional tier first; it failed on the specification index (10.9) and,
    on a machine without `bunx`, the OpenSpec default, which the owner's
    `scripts/openspec` later settled (`design.md`).
- [x] 8.3 The step table's loader refuses a row carrying `models` and an
  `[orchestrator]` row, naming it, now that task 7.1 removed them (D5). Verify: unit
  tests in `scripts/tests/test_change_workflow_steps.py`; the repository's table
  loads.
  - Done: each refusal names the configuration's field; the tests pass (unit).
- [x] 8.4 Bring the inventory to what the test collects (D18, CW-m4ps, MCW-5tgp):
  `test_change_workflow_assumptions.py` collects `.agents/workflow.toml`'s commands
  as provisions, and the two `README.md` tables list `.agents/workflow.toml` and the
  new subcommands' rules and no longer list the targets no skill or rule names
  (`make code-snapshot`, validation's moved targets as skill invocations); the full
  description of the configuration is closeout's (task 10.9). Verify: the test passes
  and fails, naming the target and the skill, when a fixture skill names an
  unlisted target (CW-m4ps's scenarios).
  - Done: the test reads the configuration's commands, not its documents, as
    provisions; the provision rows say what the configuration provides. The test
    passes against the repository (library integration) and CW-m4ps's scenarios on
    fixtures (unit).
- [x] 8.5 Verification: `pytest -q scripts/tests/test_check_change.py
  scripts/tests/test_change_workflow_steps.py
  scripts/tests/test_change_workflow_assumptions.py` (unit) passes; `make check-change
  CHANGE=add-workflow-capability-contract` fails only on the citations of files
  closeout writes and the spec index entries closeout's promotion writes; `make
  test` passes; `make check-packaging` passes. End-to-end: none; no scenario
  exercises the workflow tooling.
  - Done: the suites (154 with the CLI-steps suite), `make test`, and `make
    check-packaging` pass. End-to-end: none.

## 9. The workflow's guide (D11, D16, D17)

Brings `docs/agents/change-workflow.md` to the commands the skills now run. Touches
`docs/agents/change-workflow.md` and `scripts/completions/make-change.bash` where it
names removed targets or variables.

- [x] 9.1 In `docs/agents/change-workflow.md`, "Skills": the closing checks as `make
  check-change` over `run pre-commit`, the defaults and `make check-repository`
  listed, the hooks a step runs, validation's parts from `config parts`, archive
  cleanup's `run cleanup`, `code-snapshot` gone; "The engine's command": `run`,
  `config`, `config load`, `config parts`, `check config`, `check change`, `openspec`,
  `push --remote`, `clone-remove --base`, and `find --json`'s `base`; the fragment's
  removed `CHANGE_WORKFLOW_*` values (D11, D16, D17). The shell completion drops what
  no longer exists. Verify: `make check-doc-citations
  CHANGE=add-workflow-capability-contract` reports only files closeout writes;
  `scripts/tests/test_make_change_completion.py` passes.
  - Done: "Skills" gains "The repository's hooks"; "The engine's command" lists the
    new subcommands; the passages sections 4 and 5 left stale were brought current.
    The completion named nothing removed. `make check-doc-citations` reads only the
    change's own documents, so the guide's cited paths were checked by hand by the
    fresh-context check; the completion suite passes (library integration).
- [x] 9.2 Verification: `make check-doc-citations
  CHANGE=add-workflow-capability-contract` and `make test` pass but for files
  closeout writes. End-to-end: none; no scenario exercises the guide.
  - Done: `make check-doc-citations` passes; section 9 changes no code. End-to-end:
    none.
  - Implementation triage of the round (review 28, the owner's notes 29, validation
    31), fixes against `820629f39`: 28 F1 (7.3), 28 F2 (7.3), 28 F3 (5.1), 28 F4
    (1.5), 31 A1 (3.2), 29 O1 (6.4), 29 O2 (6.1). The touched suites pass (530), and
    `run pre-commit --base dev` ran the functional tier, failing only on the
    specification index (10.9) and the then-missing `bunx`.
  - Pre-closeout triage (review 45), documents only: 45 F1 — CW-g4oz states the order
    within each shape, with a scenario, and D3 records it; 45 F2 — D3's example names
    `scripts/openspec`.

## 11. The engine package's module list (D1; CW-r3ka's Evidence)

Appended after closeout's task 10.1 found the package's module list stale, and placed
before the closeout it returns to; numbered 11 so that the closeout's tasks, already
noted, keep their numbers. Brings the docstring of `scripts/change_workflow/__init__.py`,
which `change-workflow`'s `spec.md` Evidence names as where the engine's modules are
listed with their roles, to the package as it stands. Touches that docstring alone:
no code, test, or other document. The owner directed (log seq 82) that once this fix
is done its implementation review and validation are waived and the change returns
to closeout.

- [x] 11.1 In the docstring of `scripts/change_workflow/__init__.py`, list every
  module of `scripts/change_workflow/` once, each with its role as its own module
  docstring states it: add `config` — the repository's workflow configuration,
  `.agents/workflow.toml`, read and checked whole, and the subcommands that read it;
  `hooks` — running the repository's hooks and validation's parts through `run`,
  with the closing line and the kept markers; and `wait` — blocking until a file holds
  a line matching a pattern, which the merge of `dev` brought without a list entry.
  Say that `steps` holds each step's skill and permission rules, not its models,
  which the configuration names; and that `running` also keeps a session's
  invocations through `run` and the guarded push until its log line records them.
  Leave every other entry, the fragment's paragraph, and the `Contract:` line as they
  are, unless one no longer holds. Verify: each of `ls scripts/change_workflow/*.py`
  but `__init__.py` is named in the list exactly once, and no name in the list lacks
  its file; `make check-comment-hygiene` passes; the docstring names no change, task,
  or review.
  - Done: the list gains `config`, `hooks` (with `check change` and `openspec`), and
    `wait`; `steps` and `running` as planned. The 31 modules are each named once
    (checked with Grep against the glob); `make check-comment-hygiene` passes. No test
    reads the docstring.
- [x] 11.2 Verification: `scripts/change-workflow run pre-commit
  add-workflow-capability-contract --base dev` (this change's clone records no
  landing branch, being older than the record), whose functional tier runs, since `scripts/` is
  outside the inert paths, fails on nothing but the specification index entries task
  10.9 writes; `pytest -q scripts/tests/test_change_workflow_cli.py` (unit) passes.
  End-to-end: none; no scenario exercises the workflow tooling, and a docstring
  changes no behaviour.
  - Done at `199a7a3c4`: the functional tier passed (packaging and the whole `make
    test`), and `pre-commit` failed only on `make check-repository`'s specification
    index (10.9). `test_change_workflow_cli.py` passed (153) through `uv run
    --no-project --with pytest`. End-to-end: none. Owed by validation: nothing; the
    owner waived this round's review and validation (log seq 82).

## 10. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only; a part that needs code returns the change to
implementation.

- [x] 10.1 Comment hygiene: run `make check-comment-hygiene`; confirm no comment the
  change added names this change, a task, or the review that introduced it, and that
  `config.py`, `hooks.py`, and the modules sections 4–5 changed describe the current
  system. A finding returns the change to implementation.
  - Closeout at `8aa8f375e`, returned: the package's module list in
    `scripts/change_workflow/__init__.py` omitted `config` and `hooks` and gave
    `steps` models; fixed by section 11.
  - Closeout at `90bcf2910`: `make check-comment-hygiene` passes; section 11's
    docstring diff names no change, task, review, or history, and lists the package
    as it stands. Confirmed.
- [x] 10.2 Import placement: check every import the change added inside a function
  (`make check-local-imports CHANGE_BASE=dev` among the closing checks) for a stated
  reason; one that should move returns the change to implementation.
  - Closeout at `90bcf2910`: `make check-local-imports CHANGE_BASE=origin/dev`
    passes; section 11 added no import. Confirmed.
- [x] 10.3 Documentation compliance: check D1–D21 and P1–P4 against
  `openspec/README.md`'s placement rules: subsystem behaviour in the two `spec.md`,
  rationale in their `README.md`, the guide's procedure in
  `docs/agents/change-workflow.md`, nothing repository-wide for `ARCHITECTURE.md`.
  - Done: each decision's behaviour is in the deltas (the two `spec.md` at archive),
    its rationale in the two `README.md`, the procedure in the guide; D19 and D21 have
    no permanent home, by design. Nothing is repository-wide: `ARCHITECTURE.md` and
    the other `docs/development/` documents describe no value the change moved. The
    record is `design.md`'s "Design promotion record".
- [x] 10.4 Narrative compression: shorten this file's task notes to final behaviour,
  evidence, and destinations, moving any rationale into `design.md` first.
  - Done: the decisions the notes recorded moved first to `design.md`, "Decisions
    settled during implementation"; the notes now hold final behaviour, evidence
    levels, fixes by finding, deferrals left to the owner, and destinations. Handoffs
    between sessions, already acted on, are dropped.
- [x] 10.5 Roadmap currency: no goal of `docs/development/ROADMAP.md` covers the
  change workflow; record that disposition in the design-promotion record.
  - Done: confirmed (no goal names the workflow); recorded in the promotion record.
- [x] 10.6 Campaign index currency: in `openspec/changes/README.md`, this change's row
  (status, notes); the lesser goal "Make the change workflow a tool any repository can
  adopt": its gap row "No single file states what the workflow assumes about a
  repository" removed, and its current state rewritten where it says repository
  assumptions are listed, not declared, and that the allowlist names this
  repository's make targets; dependents (`sandbox-unattended-workflow-steps`,
  `add-skill-extension-points`, `extract-change-workflow-repository`) left as they
  are, released at archive cleanup. Run `make check-change-index`.
  - Done: the row is `in closeout` with closeout's notes; the current state
    describes the configuration, validation's remaining repository material, and the
    allowlist's remaining engineering grants; the gap row is removed; dependents
    unchanged. `scripts/change-workflow check index` passes.
- [x] 10.7 Packaging: `make check-packaging`, then `make check-architecture-change
  CHANGE=add-workflow-capability-contract`; `make check-agent-skills`, since the
  change touched `.agents/` and `.claude/`.
  - Done at `90bcf2910`: `scripts/change-workflow run pre-archive
    add-workflow-capability-contract` passed (`make check-packaging`; `make
    check-architecture-change`: "owns no architecture row"); `make
    check-agent-skills` passes.
- [x] 10.8 End-to-end pipeline: record the latest validation's pipeline run of the
  closeout's code, its result, and that no scenario exercises the workflow tooling,
  the run being evidence that the changed `run-e2e`, `run-ci`, `validate-local`, and
  `validate-helm` targets and the moved validation skill work.
  - Done: validation 46 passed at `8aa8f375e` (the merge of `dev`): pipeline run
    42265570066, success (e2e-vm 153 passed, 2 skipped; e2e-bare-metal 70;
    e2e-apicredits 4), local and Helm passed, `ci` not owed, so no `## CI`
    observation is owed. No scenario exercises the workflow tooling; the run, made by
    the moved skill through `run validation` and the changed targets, is their
    evidence. The closeout commit's code differs from `8aa8f375e` only by section
    11's docstring (`90bcf2910`), whose review and validation the owner waived (log
    seq 82).
- [x] 10.9 Promotion, and the design-promotion record in `design.md`:
  - `openspec/specs/change-workflow/README.md`: a new section "A repository's
    configuration" under "The public surface", holding P1–P4, the fields and their
    kinds (D1, D12, D13, D15), the documents to load (D6), the inert paths (D7), the
    hooks, their lists, defaults, and placeholders (D2, D8, D11), and the operations
    reading it (D16); "What an adopting repository provides" and "The engine's own
    assumptions" rewritten to describe the configuration (D18); "Validation observes
    a committed slice" for declared parts, `config parts`, the closing line, and the
    kept marker (D3, D10); "A step run's life" for `invoked` (D10); "Restrictions
    bind unattended runs only" for the hook table, the marker naming the step, and the
    protected configuration (D9, D14); "Pushing is guarded, never repaired" and "A
    change is worked in its own clone" for the derived remote and landing branch and
    clone removal (D4), with the clone diagrams that still draw `origin` as the
    clone's remote (`diagrams/change-workflow-state.drawio` and
    `change-workflow-engine-parts.drawio`, each with its `.svg`) and the README's
    and `market-change-workflow` README's rows naming `origin` as a held remote
    (28 F3); "Models are policy, with no same-vendor fallback" for models
    per step and no forbidden list (D5); "Interfaces are tiered" for the new
    subcommands (D16); "Current limits" losing the bullet on repository paths held as
    constants and naming what stays fixed in the engine (D1).
  - `openspec/specs/change-workflow/index.md`: entries for CW-f3qk, CW-w8ne, CW-t5hz,
    CW-n7ra, CW-l7hn, CW-i2we, CW-o6kc, and CW-z5me in a new group "A repository's
    configuration" under "5. The public surface"; CW-b2xr, CW-k9vd, CW-u4pc, CW-y6mj,
    CW-e1sg, CW-c8lw, and CW-v2dq in a new group "Hooks" under "4. The engine";
    CW-g4oz and CW-x9bt under "2. … Validation"; CW-q5fy under "Step runs and
    outcomes"; CW-s3ju under "Clones and history"; the links of the renamed CW-zq4h,
    CW-w2ld, and CW-p7kq moved; the summaries of the modified CW-hdxi, CW-trdu,
    CW-j1ab, CW-gqav, CW-8tdv, CW-tnp6, CW-h8vm, CW-zkhs, CW-ebmo, CW-zq4h, CW-w2ld,
    CW-59c7, CW-p7kq, CW-8jyb, CW-8npg, CW-ikmm, CW-xx5f, and CW-m4ps revised where
    they no longer hold.
  - `openspec/specs/market-change-workflow/README.md`: "This repository is the
    workflow's first adopter" losing its sentence that the engine does not yet match;
    "Validation's parts" naming the declared parts (D3); "Branches, models, and the
    clone's bootstrap" without the forbidden models and `dev` as a default (D4, D5);
    "How this repository provides the workflow's roles" and its "The engine's own
    assumptions" rewritten around `.agents/workflow.toml` (D18, D20); "The closing
    checks" naming `make check-change` over `run pre-commit` and `make
    check-repository` (D11).
  - `openspec/specs/market-change-workflow/index.md`: MCW-r4tx and MCW-k3vy under "4.
    This repository's workflow values"; MCW-ca51 and MCW-y37w moved to "Retired ids",
    each naming where its rule went (CW-s3ju and CW-hdxi; CW-ebmo and CW-zq4h);
    MCW-5tgp's summary revised.
  - `docs/agents/change-workflow.md`: confirmed against what section 9 wrote.
  - `openspec/specs/README.md`: no new capability; the two rows' descriptions
    checked and revised only if they no longer hold.
  The `spec.md` files are written by the archive (10.11), and the record names them.
  - Done, every item as listed. Beyond the list, in `change-workflow`'s `README.md`:
    "The merge before closeout" (the recorded landing branch), "Its parts" (`config`,
    `hooks`, `wait`, `steps` without models, `running`'s invocations, the fragment
    setting no repository value), "The command and its tiers", "History lives in the
    owner's workspace" (removal against the recorded branch), and the two sentences
    naming `openspec/` and `docs/` where the inert paths are meant; the role table's
    third column is now what provides each role, and the `origin` role, in both
    `README.md`, is the branch's upstream remote. The step-run diagram
    (`change-workflow-step-run`, `.drawio` and `.svg`) no longer gives the step table
    models; the engine-parts diagram gains `config`, `hooks`, and
    `.agents/workflow.toml`. "Current limits" also names the open questions'
    revisits. The guide matches section 9; `openspec/specs/README.md`'s rows hold,
    unchanged. `make check-spec-index CHANGE=add-workflow-capability-contract`
    passes; the role tables' first cells agree (checked with Grep, the assumptions
    test being no closeout check).
- [x] 10.10 Documentation citations: `make check-doc-citations
  CHANGE=add-workflow-capability-contract`, resolving every match, then
  `scripts/change-workflow openspec validate add-workflow-capability-contract
  --strict`.
  - Done: `make check-doc-citations CHANGE=add-workflow-capability-contract`: every
    cited path resolves, none a tombstone. `scripts/change-workflow run pre-commit
    add-workflow-capability-contract --base dev` over the promoted documents ran
    `pre-commit` alone, passed: the index, tasks, and skills checks, `scripts/openspec
    validate add-workflow-capability-contract --strict` ("is valid"), and `make
    check-repository`'s eight checks, the specification index among them.
- [x] 10.11 Archival: `scripts/change-workflow openspec archive
  add-workflow-capability-contract -y`, merging the `change-workflow` delta (19
  added, 3 renamed, 18 modified) and the `market-change-workflow` delta (2 added, 1
  modified, 2 removed), no `--skip-specs`; the row then links the archived directory,
  and `make check-spec-index` passes unscoped.
  - Done: the permanent specs held none of the deltas' requirements, so the archive
    merged them, no `--skip-specs`: `change-workflow` +19, ~18, →3;
    `market-change-workflow` +2, ~1, −2. Each merged requirement reads once, as its
    delta states it, and nothing else changed. The text the deltas do not carry was
    then brought current by hand: both specs' Evidence and `change-workflow`'s
    Purpose. The row links `archive/2026-11-06-add-workflow-capability-contract/`.
    `scripts/change-workflow run pre-commit add-workflow-capability-contract --base
    dev` passed (`validate --specs --strict`: 26 passed, 0 failed; `make
    check-repository`'s eight checks), and `make check-spec-index` passes unscoped.
  - For the closeout review: the CW-m4ps and MCW-5tgp deltas no longer require the
    engine's own assumptions to be listed; both `README.md` keep their tables, as
    review maintains them.
