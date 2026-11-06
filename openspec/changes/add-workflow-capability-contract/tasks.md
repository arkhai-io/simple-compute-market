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
  - Done: `config.check` (unit, 31 refusal cases, each naming its field); "A key is
    misspelled" runs `config`, `config --json`, `check config`, `config load`, and
    `config parts` through `cli.main`, each refusing with nothing on standard output,
    and `start design` refusing before launching or logging (unit). A placeholder is
    a name in braces not preceded by `$`, so `${HOME}` passes; `awk '{print}'` would
    be refused as an unknown placeholder. `defaults.disable` entries are inline
    tables `{ check = "…", reason = "…" }`. `openspec.command` is one string and
    takes no placeholder. Outside the plan: a part's `run`, `start`, or `collect`
    may not be an empty list (a hook's may), since a part running nothing passes
    without evidence.
- [x] 1.2 Give each field its kind (D12, CW-t5hz): required —
  `hooks.pre-commit-functional`, at least one validation part,
  `repository.protected-branches`, the models of each step run unattended and of the
  orchestrating session — and an explicit empty value counting as declared; every
  other field optional. Expose a query a caller asks before acting, naming the
  missing field, so `start` refuses a step needing an absent required field before
  launching anything (wired into `start` here, for the fields this section's callers
  read). Verify: unit tests for "No functional checks are declared" and "A repository
  declares no functional checks on purpose" (CW-t5hz) against `start implement`.
  - Done: `config.missing`, `require`, and `require_for_step`; `start` checks the
    configuration whole for every step but `orchestrate`, and requires
    `hooks.pre-commit-functional` of implement, triage, and merge and a part of
    validate (`config.STEP_NEEDS`), interactive or unattended. "No functional checks
    are declared" (no session launched, no log line) and the start half of "A
    repository declares no functional checks on purpose" pass, library integration
    (a real `git init`, which `start` needs for the round-view check); "a functional
    commit runs no functional checks" is section 2's. An empty `[validation.parts]`
    is refused: CW-t5hz asks for at least one part.
  - Outside the plan: **`.agents/workflow.toml` is written here, not in 6.1.** With
    `start` refusing implement, triage, merge, and validate without these fields,
    the next session (sections 4–6), started by the engine as this section leaves
    it, and this round's validation would be refused in this repository. The file
    holds the design's listing but `pre-commit` and `pre-push`, whose targets
    (`make check-repository`, section 8; `make pre-push`, 6.2) do not exist yet:
    with `pre-push` declared, section 4's push would run a missing target. Its
    `models` rows copy the step table's. It is unprotected until 7.1's deny rule.
    `test_the_repositorys_own_configuration_passes_its_check` loads it.
  - Handoff to section 4: `start` does not yet require
    `repository.protected-branches` or the step and orchestrator `models`; 4.1 and
    4.5, which make the push and the wrapper read them, add them to
    `config.STEP_NEEDS` (and `start orchestrate` to `models.orchestrator`), so
    CW-t5hz holds whole. `config` imports `graph` (for `STEPS`), and `graph`
    imports `records`: for 4.2, `records` importing `config` would make a cycle, so
    pass the inert paths in rather than have `records` load the file.
- [x] 1.3 Add `scripts/change-workflow config [--json]`, listing every field and how
  it resolved — declared, default, disabled, or absent — with the command it resolves
  to (D16, CW-o6kc), and `scripts/change-workflow check config`, running the check
  alone (D13). Verify: unit tests for the scenario "An optional hook is absent"
  (CW-o6kc) and for `--json`'s structure; a disabled default listed with its reason.
  - Done: `config.resolution`; `--json` is `{"file", "exists", "fields": [{"field",
    "status", "value"?, "reason"?}]}`, every field the workflow defines, one per
    step for `load` and `models`, each declared part's keys. Unit tests pass for the
    `config` half of "An optional hook is absent" (closeout skipping it is 2.5's),
    the JSON structure, and a disabled default with its reason.
- [x] 1.4 Add `scripts/change-workflow config load <step>`, printing `load.common`
  then `load.<step>` (D6, CW-l7hn). Verify: unit test for "Design loads the roadmap"
  (CW-l7hn).
  - Done: unit test passes; a document listed in both is printed once, and a name
    that is not a step is a usage error.
- [x] 1.5 Add `scripts/change-workflow config parts <change> [--json]`, validation's
  plan (D3, CW-g4oz): the preflight, then each run of a part in declaration order with
  its shape, its `after`, and its evidence; an owed part once per `Owed by
  validation:` line of a complete section of the change's `tasks.md`, named by its
  part and that line's workflow, or once as `not owed`. Reading the owed lines is
  `scripts/change_workflow/tasks.py`'s, beside its section parsing. Verify: unit tests
  for "Two sections owe CI workflows" and "No section owes CI evidence" (CW-g4oz),
  and an owed line under an incomplete section ignored.
  - Done: `tasks.owed_lines` (the first backticked name after `Owed by
    validation:`, in a task's text or the section's notes), using
    `next_step.section_heading`, added beside `read_sections`; the plan is
    `config.plan`, printed by `cli` so `config` imports neither `tasks` nor `find`.
    Unit tests pass for the plan halves of both scenarios (starting and recording
    the runs is section 3's and the skill's) and the incomplete section. Decision
    the design left open: two lines owing one workflow are one run, owed by both
    sections, since a run is named, and its marker kept, by part and workflow
    (D10); CW-g4oz's "once per line" and "once per owed workflow" agree only so.
  - Fix, implementation triage 28 F4: the check refused only an `after` naming no
    other part, so it accepted an order validation cannot follow. It now also
    refuses an `after` naming a part declared later, which rules out every cycle,
    and a `start` part's `after` naming a `run` part, since every dispatch starts
    before any long part runs; CW-g4oz's delta says so and D3 records why
    (topological ordering rejected). Evidence (unit, config suite): the forward
    reference, the two-part cycle, and the dispatch after a long part refused,
    naming the field; dispatch-after-dispatch and long-after-either accepted; this
    repository's file still loads. Checks: see 9.2's triage note.
- [x] 1.6 Verification: `pytest -q scripts/tests/test_change_workflow_config.py
  scripts/tests/test_change_workflow_cli.py scripts/tests/test_change_workflow_cli_steps.py`
  (unit) passes; `make test` passes. End-to-end: none; no scenario exercises the
  workflow tooling.
  - Done: the three suites pass, 281 tests (unit, and library integration where a
    test runs `git init`); `make test-release-tooling` (every script suite, 2421)
    and `make test` pass. The CLI suites' checkouts (`_repository`, `_checkout`)
    now write a configuration (`change_workflow_fixtures.configured`), since the
    steps they start need its fields. End-to-end: confirmed none.
  - `make check-change` fails, as the preface expects, on the citations of
    `hooks.py` and its tests (section 2) and the specification index (10.9).

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
  - Done: `scripts/change_workflow/hooks.py` (`Hooks`, `fill`). "Two checks fail"
    passes (unit, the shell faked); the quoting test runs a real `sh` (library
    integration). `{base}` is `run --base <branch>` until section 5; a command
    naming a value the run lacks is refused before any command runs. Each hook
    prints `+ <command>` before each command and ends with the engine's closing
    line, `[change-workflow] <hook> at <commit>: passed`, or `failed:` and each
    failed command with its exit status, or `skipped, not declared`; section 3's
    parts' closing line should keep this form, adding the part, owed workflow,
    and evidence. Each command, default check, and skip is an `Invoked` (hook,
    part, owed, phase, check, command, exit status, started, seconds), which
    section 3 keeps for the run's line; `part`, `owed`, and `phase` are for its
    parts.
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
  - Done: `graph.HOOK_STEPS` (keys `validation` and `cleanup` for section 3); the
    marker moved to `common.UNATTENDED_RUN` (harness re-uses it), since `hooks`
    needs it without the harness adapter. The harness's `Runner` takes the step
    (`run_claude(command, cwd, feed, step)`); the wrapper passes each run's and
    resume's step, the review its Claude fallback `review`, and `run_codex` sets
    `review` itself. A marker naming no step runs no hook. `pre-push` and
    `post-clone` are no choice of `run` (a usage error). Evidence: "Validation asks
    for a functional hook" and an interactive `run` unrestricted go through
    `cli.main` with a real `sh` (library integration); `record` refused under
    `implement`, the wrapper marking a run and its resume, a Claude review marked,
    and every table entry a step (unit); the harness marking a real child process
    `validate` and a Codex one `review` (library integration).
  - Outside the plan, found by the fresh-context check: `workflow.mk` assigned a
    make variable `CHANGE_WORKFLOW_UNATTENDED`, which overrides the environment
    variable of that name in every recipe, so any `make` target an unattended run
    started saw the marker erased, and would have run unrestricted. Renamed
    `CHANGE_WORKFLOW_HEADLESS`; a library-integration test runs a real `make`
    including the fragment and reads the marker in a recipe.
- [x] 2.3 Run `pre-commit`'s default checks before its declared commands (D11,
  CW-c8lw): `index`, `tasks`, `skills`, and `openspec` — the strict validation of the
  change, or of every specification for an archived change — each skipped only when
  `defaults.disable` names it; and add `scripts/change-workflow check change
  <change>`, running them alone. Add `scripts/change-workflow openspec <arguments>`,
  running `openspec.command`, or `openspec` on the path, with the arguments (D11,
  D16, CW-i2we); the default validation runs through it. Verify: unit tests for "A
  repository declares its own pre-commit" and "A default check is turned off"
  (CW-c8lw), and "A repository pins the validator" (CW-i2we) with the runner faked.
  - Done: `index`, `tasks`, and `skills` run in process (`index.main`,
    `tasks.main`, `skills.main`); `openspec` runs `<command> validate <change>
    --strict`, or `validate --specs --strict` for an archived change, through the
    shell. The three scenarios pass (unit, the shell and in-process checks faked),
    with a failing default not stopping the declared commands, an archived change,
    `check change` alone, and an absent `pre-commit` recording its skip. `openspec`
    is handled before argparse, so every argument, flags included, is OpenSpec's;
    one test runs it through a real `sh` (library integration). It maps a non-zero
    status to 1, as every subcommand does.
- [x] 2.4 Give `run pre-commit` its tier (D7, CW-e1sg): from the worktree's changes
  against `HEAD` — staged, unstaged, and untracked — when any path lies outside
  `repository.inert-paths`, run `after-functional-change`, then
  `pre-commit-functional`, then `pre-commit`, each held to the hook table; otherwise
  `pre-commit` alone. Refuse when `pre-commit-functional` is absent and the tier needs
  it (CW-t5hz). Verify: library-integration tests over a real Git repository for "A
  triage fix changes only documents" (CW-e1sg), a functional change running all three
  in order, a clean worktree running `pre-commit` alone and changing nothing
  (CW-y6mj), and a design step's functional change refused by the table.
  - Done: `hooks.worktree_changes` (`git status --porcelain=v1 -z
    --untracked-files=all`, both sides of a rename) and `config.inert`, which
    matches an entry whole (an entry `docs/` covers a file under it, not one under
    a sibling `docsite/` directory); 4.2
    should use `config.inert` for the next-step computation too, so the two never
    disagree. The four scenarios pass, plus staged, untracked, and renamed changes,
    a functional commit with no `pre-commit-functional` refused, one with it
    declared empty running none (the commit half of CW-t5hz's "on purpose"), and
    no inert path making every change functional (library integration, a real Git
    repository, the shell and default checks faked). The clean-worktree test
    shows the tier and an unchanged tree with the default checks faked; that the
    real defaults change nothing rests on their reading only. Every hook of the
    tier is checked against the table and for missing values before any runs; all
    run, whatever an earlier one reported. The line naming the first functional
    path is printed before the table's check, so a refusal is explained.
  - A change's records outside the inert paths, such as a tracked ledger in a
    repository declaring none, make a commit functional, as CW-e1sg reads; D7's
    exemption of records is the next-step computation's, not the tier's.
- [x] 2.5 Run `pre-archive` through `run pre-archive <change>` for closeout, and
  `after-functional-change` alone through `run after-functional-change <change>`, both
  held to the table (D2, D9). Verify: unit tests that each runs its declared commands
  and that an absent optional hook is skipped, the run saying so (CW-t5hz).
  - Done: both pass (unit). Outside the plan: `run pre-commit-functional` is also
    runnable by name, held to the table like the rest.
- [x] 2.6 Verification: `pytest -q scripts/tests/test_change_workflow_hooks.py
  scripts/tests/test_change_workflow_config.py scripts/tests/test_change_workflow_harness.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_workflow_review.py
  scripts/tests/test_change_workflow_cli.py` (unit, and library integration where a
  real Git repository is used) passes; `make test` passes. End-to-end: none; no
  scenario exercises the workflow tooling.
  - Done: the six suites and `test_change_workflow_cli_steps.py` pass, 493 tests;
    `make test-release-tooling` (2465) and `make test` pass. One full run failed
    `test_check_secrets.py::test_the_audit_reports_what_the_gate_passes`, which
    passed alone and on every run since; not this section's code. Every runner
    stand-in in the wrapper, review, and CLI tests now takes the step.
    End-to-end: confirmed none. `make check-change` fails only on the
    specification index (10.9).

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
  - Done: `Hooks.validation`. The closing line is section 2's, with the part's
    evidence: `[change-workflow] validation <part>[ <owed>] <phase> at <commit>:
    passed, exit 0; evidence <dir>`, or `failed, exit <n>: <command> (exit <n>);
    …`. Outside the plan: every hook's line now carries the exit status too
    (`passed, exit 0`, `failed, exit <n>:`), which D10 asks of every closing
    line; section 2's tests were updated. Unit tests pass for each shape, the
    preflight absent (skipped, saying so), `--owed` required and refused, a part
    run in another shape or not declared, the table refusing another step, the
    closing lines, and each malformed `run` form a usage error; an owed start and
    collect through `cli.main` with a real `sh` (library integration). A part may
    not be named `preflight`, which names the preflight (`config`).
- [x] 3.2 Keep a `start`'s marker, its last line of standard output, keyed by the
  commit, the part, and the owed workflow, a later `start` of the same key replacing
  it, and fill `{after}` from it in the matching `collect`; a `collect` with no kept
  marker refuses, naming the `start` to run (D10, CW-x9bt). Verify: unit tests for
  "Two owed runs are collected side by side" and "The pipeline is collected"
  (CW-x9bt), and a retried `start` replacing the marker.
  - Done: kept in `<git-dir>/change-validation/<change>.json`, locked from read to
    write, since owed runs start side by side; a start that failed or printed
    nothing removes its key's marker, so its collect refuses rather than wait past
    an older dispatch; a collect at another commit finds none. `hooks.capture`
    passes the start's output through as it arrives and keeps its last non-empty
    line (library integration, a real `sh`). The scenarios and the replacement
    pass (unit, the commands and the marker's directory faked). Markers are never
    pruned; one entry per commit and part is small. A `start` that leaves a
    background process holding its output keeps `capture` reading until it exits:
    a dispatch must return at once, as D10's contract says.
  - Fix, implementation triage 31 A1 (validation 31's pipeline collect failed): a
    session launched by a make target (`make validate`, `make orchestrate`)
    inherits `MAKELEVEL`, so the declared `make run-e2e` ran as a sub-make and
    printed "make[2]: Leaving directory …" after its marker, which the engine
    kept as `{after}`. `hooks.shell`, `hooks.capture`, and the guarded push's
    `pre-push` runner now run their command in `hooks.command_environment()`,
    the caller's environment without `MAKELEVEL`, `MAKEFLAGS`, `MFLAGS`, and
    `MAKEOVERRIDES`; a variable given on the outer make's command line still
    reaches the command as an environment variable, which this repository's `?=`
    assignments read. The `post-clone` bootstrap and the configured OpenSpec
    command keep the caller's environment. Evidence: a `start` running a real
    `make` with `MAKELEVEL=1` and `MAKEFLAGS=w` set keeps its marker and prints no
    directory line (hooks suite, library integration: a real `sh` and `make`;
    without the fix make prints the line last); the environment's filtering
    (unit). The fix commit's validation runs the pipeline part through it.
    Checks: see 9.2's triage note.
- [x] 3.3 Add `run cleanup <change>`, running every declared part's `cleanup` in
  declaration order as one list (D3, CW-ikmm). Verify: unit tests for "A change's
  validation left resources" and "A part's cleanup finds nothing" (CW-ikmm) with the
  commands faked.
  - Done: `Hooks.cleanup`, held to the table (archive cleanup only); with no part
    declaring one it is skipped, saying so. Both scenarios pass (unit); one
    through `cli.main` with a real `sh` (library integration).
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
    `<git-dir>/change-invocations/<session>.jsonl`; `SESSION_ID` moved to
    `common`. Each entry `run` keeps names its change, and a line takes its own
    change's and the push's (which name none); entries are forgotten only once the
    line is written, by exact match, the file emptied, never removed. Taking or
    forgetting never stops a line; failing to keep warns and changes no hook's or
    push's result. The push records each of its current pre-push scripts as
    `pre-push` (4.1 moves it onto the hook runner). Beyond the task: the wrapper
    takes every attempt's session (a retried or passed-over attempt has its own);
    a review on Claude records its session's invocations on its own line; Codex is
    given no `CLAUDE_CODE_SESSION_ID`, so a review started from a Claude session
    never lands on that session's line. Evidence: both scenarios pass through the
    wrapper (library integration, a real Git repository; the push's check a
    script exiting 1; the Helm part a real `sh` exiting 2); `record` taking a
    session's invocations, a refused record keeping them, nothing kept outside a
    session (library integration); a resumed turn taking only what came since, a
    retried attempt's taken, a review's taken and forgotten, an unreadable file
    never stopping a line, and the store itself (unit). A line with `invoked`
    routes as one without (`test_change_next_step.py`, unit); every existing
    next-step test reads lines without it.
  - Known limit: a review on Claude retried after a network error takes only its
    last attempt's session; an earlier attempt's invocations stay kept. Reviews
    run on Codex first, and the review rarely runs a hook.
- [x] 3.5 Verification: `pytest -q scripts/tests/test_change_workflow_hooks.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_workflow_log.py
  scripts/tests/test_change_workflow_cli_steps.py scripts/tests/test_check_push_ready.py
  scripts/tests/test_change_next_step.py` (unit, and library integration where a real
  Git repository or process is used) passes; `make test` passes. End-to-end: none in
  `e2e-tests/`; the round's validation, run through these commands once section 7
  moves the skill, is their evidence.
  - Done: the six suites and the review suite pass, 677 tests; `make
    test-release-tooling` (2510) and `make test` pass. End-to-end: confirmed none
    in `e2e-tests/`. `make check-change` fails only on the specification index
    (10.9).
  - Handoff: section 6's `.agents/workflow.toml` comment for `ci` and task 3.1 use
    `run validation <change> ci start --owed <workflow>`; `design.md`'s listing
    still shows `run ci start <change> --owed <workflow>`, the form before 3.1.
    Closeout's promotion (10.9) should also bring the change-workflow README's
    "Its parts" to the `config` and `hooks` modules and `running`'s session
    invocations.

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
  - Done: `push.pre_push` runs the hook with `Hooks.engine_hook` (held to no step's
    listing, skipped saying so when undeclared), each command fed the ref line and
    its output, both streams in order, sent to standard error, so the check's
    "Ready to push" stays alone on standard output. The push requires
    `repository.protected-branches`, refusing naming it, and `config.STEP_NEEDS`
    now requires it of every step but the review (1.2's handoff). The four
    scenarios pass, plus a push with no protected branches declared refused naming
    the field, a silent failure named by its exit status, and the run's line
    listing the hook (library integration: real Git, a bare remote, and a real
    `sh` running each test's check script).
  - Decision the design left open, found by the fresh-context check: `pre-push`
    takes `{remote}` alone, and the configuration's check refuses `{change}` and
    `{base}` there (config suite, unit). D8 gives those two "everywhere", but the
    guarded push pushes a branch, not a change, so it has neither to give, and D13
    refuses a placeholder unavailable where it is used when the file is checked,
    not at the push.
  - Outside the plan: until 6.2's `make pre-push` exists, this repository's
    `pre-push` runs its two public-content scripts as a list, so the guarded push
    keeps checking what it sends; 6.2 replaces it. The two tests that ran this
    repository's own public-content script through the push moved to
    `test_check_public_content.py`, reaching the engine as the command, since
    `test_change_workflow_command.py` holds that a test naming one of this
    repository's scripts is the repository's, not the engine's.
- [x] 4.2 The next-step computation and the records read `repository.inert-paths`
  where they read `records.DOCUMENTATION`, with no inert path when none is declared
  (D7, CW-n7ra, CW-trdu, CW-j1ab, CW-gqav, CW-8tdv, CW-tnp6). Verify: tests in
  `scripts/tests/test_change_next_step.py` and
  `scripts/tests/test_change_workflow_records.py` (unit) for "A repository marks
  images inert" (CW-n7ra), the existing documentation-correction and pre-closeout
  cases with `openspec/` and `docs/` declared, and the same commits read as code with
  no inert path declared.
  - Done: `records.inert` (moved from `config`, which re-exports it) and
    `records.exempting(inert_paths)`, a record or an inert path. The graph names an
    exemption by kind, `graph.RECORDS` or `graph.INERT`, which the computation
    resolves from the configuration read once as it starts (`inert_paths` seam);
    `changed_outside_documentation` is `changed_outside_inert`. The review's
    pre-closeout check reads the same. The guards' and the review entry guard's
    texts say "inert paths", so the graph diagram's source and export were edited
    to match (`check graph` holds them to the table). Evidence (unit): "A
    repository marks images inert" from a real configuration file; the existing
    cases with `openspec/` and `docs/` declared (the tests' default seam); the merge,
    pre-closeout, and closeout-correction cases read as code with none declared,
    and, in the merge and pre-closeout cases, records still exempt; a malformed
    configuration leaving the change
    unclassified; `exempting` and `validation_problem` in the records suite; the
    review admitting a document commit after a pre-closeout triage only with inert
    paths declared.
- [x] 4.3 History copies each declared part's `evidence` where it copied
  `history.VALIDATION` and `history.E2E_LOGS`, reading the cited runs and commits as
  it does (D3, D10). Verify: `scripts/tests/test_change_history.py` (library
  integration) passes with the evidence declared, and copies nothing for an
  undeclared directory.
  - Done: `Configuration.evidence()` lists each declared directory once; history
    reads the clone's checkout's configuration. A record citing `<directory>/<name>`
    names it under that directory; a validated commit (first twelve characters)
    and a pipeline run name no directory, so they are copied from whichever
    declared directories hold them, and reported absent under each when none does.
    The suite passes with the workspace declaring this repository's evidence
    directories, and a clone declaring only `.snapshot/validation/` copies nothing
    under `.snapshot/e2e-logs/` (library integration, real clones). Clone removal's
    tests declare their evidence directory the same way.
- [x] 4.4 The post-compaction hook re-reads `load.common` where it read
  `hook.REQUIRED` (D6, CW-l7hn). Verify: a unit test of `hook post-compaction` naming
  the configured documents.
  - Done: tests for the configured documents (a step's additions not named), none
    configured, and a malformed configuration named while the session is still told
    to re-read its skill's guidance; one reads this repository's own file. Library
    integration, not unit: `hook.context` reads the branch with a real `git`.
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
  - Done: the policy is `config._models`, checked as the file loads;
    `Configuration.step_models` and `orchestrator_model` refuse naming the field when
    absent. `start` requires `models.<step>` of an unattended run and
    `models.orchestrator` of `start orchestrate` (`require_for_step(…, unattended=)`,
    1.2's handoff); an interactive step needs no models. The review reads
    `models.review` (`review_models` takes the models, not the step's rules).
    `StepRules` has no `models`; `load_orchestrator` is gone. Evidence (unit):
    CW-ebmo through the wrapper, the configured first model running and named on
    the line — one Claude model, since CW-zq4h admits no Codex model and no second
    Claude model on a wrapper step, so the fall to the next model stays proven with
    the models given directly, and the review's Codex-then-Claude in the review
    suite — and a step with no models refused before launching; CW-zq4h and each
    policy refusal naming the step (steps suite); a
    Fable model accepted (config suite); this repository's models per step. CW-w2ld
    is `test_the_owner_starts_the_orchestrating_session` in
    `test_change_workflow_cli.py`, beside the other `start orchestrate` tests,
    not in `test_change_workflow_cli_steps.py` (library integration: a real
    `git init`, the launch faked).
  - The shared fixtures' least configuration (`CONFIGURED`) now holds the
    protected branches and every step's models (`MODELS`), and `make_wrapper` and
    `repository()` write it where a root has none.
- [x] 4.6 The clone's bootstrap runs `hooks.post-clone` through the hook runner where
  it ran `clone.BOOTSTRAP_COMMAND`, succeeding at once with none declared, and its
  recorded state holds the resolved command beside its log and exit status (D10,
  CW-8npg). Verify: tests in `scripts/tests/test_change_clone.py` (library
  integration) for "The bootstrap failed", a clone with no `post-clone` usable at
  once, and the state naming the command.
  - Done, not through `Hooks`: the bootstrap outlives the call, so it is spawned in
    the background as before, each command with `sh -c` in one process that runs
    them all and exits with the first failure's status (`bootstrap_command`); the
    `post-clone` is read from the clone's checkout once its branch is checked out,
    filled with `{change}` and, until 5.1 records the landing branch, `{base}` as
    `--from`. The record's `command` is the resolved commands; with none declared,
    or `[]`, the state is written succeeded with an empty `command` and nothing
    spawned. The spawn seam takes the hook's commands. Evidence (library
    integration): the recorded state of "The bootstrap failed" with the real spawn
    (both commands ran, status the first failure's, log and record named); its
    THEN, the computation bringing it to the owner and a rerun restarting it, rests
    on the next-step suite and `test_rerunning_restarts_a_failed_bootstrap`; a clone
    with no `post-clone` or an empty one usable at once; and the state naming the
    filled command. The engine's messages on a failed or running bootstrap name
    its `post-clone`, not `make init`.
  - Outside the plan: `fill` moved from `hooks` to `config` (`hooks` imports it),
    since `clone` importing `hooks` would close a cycle through `tasks` and
    `next_step`. `cli.ORCHESTRATE` is `config.ORCHESTRATOR_STEP`.
  - Fresh-context check, declined: reporting a validated commit or pipeline run no
    evidence directory holds under every declared directory (4.3) names paths no
    part writes; kept, since which directory a commit's or run's evidence goes to
    is no field, and naming every candidate is true where naming one would guess.
- [x] 4.7 Verification: `pytest -q scripts/tests/test_check_push_ready.py
  scripts/tests/test_change_next_step.py scripts/tests/test_change_workflow_records.py
  scripts/tests/test_change_history.py scripts/tests/test_change_workflow_steps.py
  scripts/tests/test_change_workflow_wrapper.py scripts/tests/test_change_workflow_cli_steps.py
  scripts/tests/test_change_clone.py` (unit, and library integration where a real Git
  repository or process is used) passes; `make test` passes. End-to-end: none; no
  scenario exercises the workflow tooling.
  - Done: the eight suites with the review, config, hooks, CLI, graph, harness,
    post-compaction, public-content, secrets, command, and parallel-validation
    suites pass, 1119 tests; `make test-release-tooling` (`test_check_secrets.py`
    and `test_validate_parallel.py` updated to declare their `pre-push` and
    `post-clone`) and `make test` pass. End-to-end: confirmed none. `make
    check-change` fails only on the specification index (10.9).
  - Handoff to section 5: `{base}` reaches the bootstrap as `--from`; 5.1 replaces
    it with the recorded landing branch. `next_step` still imports
    `clone.DEFAULT_FROM` for the merge's default (5.2).

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
  - Done: the marker gains `base`, kept on every rerun (a recorded base stands
    whatever the workspace has checked out); a workspace with no branch checked out
    and no `--from` is refused before anything is cloned. The upstream is
    `origin`'s branch of the name when it exists, else the name on the landing
    branch's upstream remote (`git config`, since `--set-upstream-to` needs the
    remote-tracking ref), else none; a landing upstream remote other than `origin`
    is added to the clone with the workspace's URL. The bootstrap's `{base}` is the
    landing branch. The marker's reading moved to `find` (`clone_marker`,
    `landing_branch`, and `clone_directory`, which `clone` imports), since `find`
    cannot import `clone`. Evidence (library integration, real workspaces and
    clones): clones from `dev` and from `main` recording each, `--from` naming
    another, the upstream configured before any push, "Orchestration is run again
    from another branch" through `find --json`, a detached workspace refused, a
    `--from` contradicting the recorded branch refused, a landing branch tracking
    another remote giving the clone that remote and the branch its upstream there,
    one tracking nothing giving no upstream, and the bootstrap's `{base}` the
    landing branch. The suites' workspaces now push `dev` with `-u`, as a real
    workspace's `dev` tracks `origin`. A rerun that adds the landing branch's remote
    settles the upstream again after adding it.
  - Fix, implementation triage 28 F3: clone creation required `origin` and made
    the change branch track `origin`'s branch of its name whenever one existed,
    against D4. It now takes its push remote from Git's record in the workspace:
    the upstream remote of the workspace's branch of the change, when that remote
    still exists there, else the landing branch's (`clone._push_remote`). It adds
    that remote and the landing branch's upstream remote, each under its workspace
    name and URL, compares the branch's copies in the workspace and on the push
    remote, and tracks the push remote's branch; no remote is named in the engine.
    A push remote not yet added leaves an existing clone's upstream as it is until
    the pass after it is added. CW-8jyb is modified in the delta (its "The clone's
    `origin` MUST be the workspace's `origin`" was the requirement in the way),
    D4 records the derivation, and the guide's clone paragraph and the merge
    skill's fetch line name the remote the branch tracks rather than `origin`.
    Evidence (library integration, real workspaces and bare remotes): a workspace
    with no `origin` whose dev tracks `upstream` clones, the branch tracking
    `upstream`; a stale branch of the change's name on `origin` is neither the
    start nor the upstream when dev tracks `upstream`; a fork's change branch
    tracking `origin` keeps it, with `upstream` added; a change branch tracking a
    removed remote falls to dev's. The first two fail on the old code. The CLI
    suite's delegation test, which relied on a workspace without `origin` making
    `clone` refuse, now refuses through a file at the clone's path. Left: the
    merge step's rules allow `git fetch origin *` and `git fetch workspace *`
    only, and the orchestrating skill's `pull --no-rebase origin dev`; both hold
    in this repository, the step table being the owner's to widen. Closeout's
    10.9 now names the clone diagrams and README rows still drawing `origin`.
    Checks: see 9.2's triage note.
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
  - Done: `start merge` with no `from <branch>` in its arguments adds the recorded
    branch, or refuses naming `FROM=<branch>` and `--arguments 'from <branch>'`
    (`cli.merge_arguments`); a review other than the design's takes `--base` or the
    recorded branch, or refuses naming `--base` (the design review names no base, so
    needs none); `run` fills `{base}` from `--base` or the recorded branch. The
    fragment passes `--base` and `from` only when `REVIEW_BASE` or `FROM` is set;
    `make change-clone-remove` takes `BASE`. The next-step computation's clone
    suggestion names no `FROM`, and its messages on an unlanded prerequisite say to
    merge the branch the change lands on, not `dev`. Only a leading `from <branch>`
    in the merge's arguments names its branch. Evidence, all library integration
    (`landing_branch` runs `git`, inside or outside a repository): `base` null for
    a change with no clone and recorded, read in the clone and from the workspace
    (`test_find_change.py`; `find --json` both ways in
    `test_change_workflow_cli.py`); "A change worked in place merges with no base
    given" and the merge bringing in the recorded branch, a leading `from`
    overriding and other words left to the skill, in `test_change_workflow_cli.py`
    beside the other `start` tests (real `git init` and clone, the launch faked),
    not `test_change_workflow_cli_steps.py`; the review reading the recorded branch
    and refusing with none (review suite); `{base}`
    recorded and overridden through `run` with a real `sh` (hooks suite); CW-h8vm
    through the root Makefile's `make -n merge` with and without `FROM`, and the
    review with and without `REVIEW_BASE` (`test_change_workflow_cli_steps.py`,
    library integration: a real `make -n`). The review suite's runs of other kinds
    give `base="dev"`, the change being worked in place.
- [x] 5.3 The guarded push sends to the branch's upstream remote, or a remote given
  as `push --remote <remote>`, and refuses a branch with neither; `push.DEFAULT_REMOTE`
  is removed (D4, CW-59c7). Verify: tests in `scripts/tests/test_check_push_ready.py`
  (library integration) for "A new change branch is pushed first" and "A branch with
  no upstream" (CW-59c7).
  - Done: a remote given overrides the upstream's for that push, leaving the
    upstream as it was; with no upstream it is pushed with `--set-upstream`; the
    `workspace` remote and `.` are refused, so no push goes into the owner's
    workspace (tested both ways). Both
    scenarios pass, "A new change branch is pushed first" through a real clone
    made by `clones.create`, plus the remote given for a branch with no upstream
    and the override (library integration, real Git). The push suites'
    repositories (`test_check_push_ready.py`, `test_check_public_content.py`,
    `test_check_secrets.py`) give their change branch its own-name upstream, as a
    clone does.
- [x] 5.4 `clone-remove` judges the merge against the recorded landing branch on the
  branch's upstream remote, where it judged `origin/dev` and `origin`, and takes
  `--base <branch>` for a clone with none recorded, refusing without it (D4, CW-xx5f).
  Verify: tests in `scripts/tests/test_change_clone.py` (library integration) for
  "The owner removes a clone too early", "A change landed on another branch", and "A
  clone recorded no landing branch" (CW-xx5f).
  - Done: `--base` overrides the recorded branch for the removal, as CW-s3ju has
    an argument override it for one run, so a change the merge brought onto
    another branch is removable once landed there (found by the fresh-context
    check: the first version kept the recorded branch over the argument). A clone
    whose marker records none and given none is refused before its history is
    copied; a branch tracking no remote is a problem named in the refusal. The
    three scenarios pass ("too early" is the existing unmerged and records-missing
    refusals), plus a branch merged only into another branch than its recorded
    one, the override, a branch tracking no remote, and `clone-remove --base`
    through the command (library integration, real clones and a bare `origin`).
- [x] 5.5 Verification: `pytest -q scripts/tests/test_change_clone.py
  scripts/tests/test_find_change.py scripts/tests/test_change_workflow_review.py
  scripts/tests/test_change_workflow_cli_steps.py scripts/tests/test_check_push_ready.py
  scripts/tests/test_make_change_completion.py scripts/tests/test_validate_parallel.py`
  (unit, and library integration where a real Git repository is used) passes; `make
  test` passes. End-to-end: none; no scenario exercises the workflow tooling.
  - Done: the seven suites with the CLI, hooks, next-step, history, public-content,
    secrets, and workflow-command suites pass; `make test-release-tooling` (2574)
    and `make test` pass. End-to-end: confirmed none. `make check-change` fails
    only on the specification index (10.9).
  - Handoff: the permanent documents still name `CHANGE_WORKFLOW_MERGE_FROM`,
    `CHANGE_WORKFLOW_REVIEW_BASE`, and `dev` as the default
    (`docs/agents/change-workflow.md`, section 9; both capabilities' `README.md`
    and `market-change-workflow`'s `spec.md`, closeout's 10.9 and the archive).
    The validation skill's guarded push needs no `--remote`: this branch tracks
    `origin`.
  - Fresh-context check, declined: a run interrupted after the clone's checkout and
    before its marker records the workspace's branch at the rerun, which may not be
    the one the branch started from; the window is one Git call wide, and a rerun
    with `--from` records the intended one.

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
  - Amended in section 1: the file exists from section 1 (see 1.2's note), all of
    the design's listing but `pre-commit` and `pre-push`; this task adds those two,
    once their targets exist, and checks every field's comment names who uses it.
  - Done: `pre-push` is `make pre-push REMOTE={remote}`, replacing section 4's
    interim list of the two scripts; `pre-commit` names `make check-repository`,
    which section 8 adds, so `run pre-commit` fails in this repository until then
    (no skill runs it before section 7). Each table's comment names the engine
    operation using its fields and the steps it serves, as the engine holds them
    now (the hook table, `config load`, `openspec`); each part's comment says what
    it is, under one naming who runs the parts. Comments name a table's users, not
    each key's: the design's listing comments by table too. Section 8 adds that
    `make check-change` runs `run pre-commit` once it does. Evidence (unit, config
    suite): the file passes its check through `cli.main(["check", "config"])` with
    every required field, the models of every step and the orchestrator included;
    MCW-r4tx's hooks as declared; those comments, by table; and
    MCW-r4tx's scenario, `config parts` for a change whose complete section owes
    `tests.yml` listing the pipeline, `ci tests.yml`, local, and Helm after local
    from this repository's own file. `scripts/change-workflow check config` itself
    was denied this session (no rule allows it until 7.1); the test runs the same
    check.
  - Handoff: this checkout is a clone made before clones recorded their landing
    branch, so its marker has no `base`: `run pre-commit` here (section 7's skills,
    section 8's `make check-change`) needs `--base dev` until the marker records one,
    or `{base}` is refused naming `--base`.
  - Fix, implementation triage 29 O2 (the owner's note: a stage passed `make test`
    against stale wheels): `pre-commit-functional` begins with `make dist-clean`,
    so the packaging check builds every wheel from the commit, as validation's
    local part already does; the orchestrating session made the edit of the
    protected file on the owner's word. MCW-r4tx's delta, the design's listing,
    the guide, and the config suite's test of this repository's hooks say so.
    Unconfirmed: whether each suite's `uv run --find-links` reinstalls a rebuilt
    wheel whose name and version are unchanged; if not, this guard is partial.
    Checks: see 9.2's triage note.
- [x] 6.2 Add `make pre-push REMOTE=<remote>`, running both public-content checks
  (`scripts/check_public_content.py --pre-push` and `scripts/check_secrets.py
  --pre-push`) under Git's hook contract, the ref lines read once from standard input
  and given to each, either refusing; `scripts/hooks/pre-push` runs it with its first
  argument (D20, MCW-k3vy, MCW-q8vd). Verify: a library-integration test over a real
  Git repository that the hook and `make pre-push` both refuse a commit adding a
  recognizable private path and pass a clean one, beside
  `scripts/tests/test_check_public_content.py` and `test_check_secrets.py` passing.
  - Done: the target refuses without `REMOTE`; the hook `exec`s `make -s pre-push
    REMOTE="$1"` from the top level. The updates go on with no newline added, as
    the hook gave them before: Git runs the hook with no input when every ref is
    up to date, and a blank line is a malformed update to both checks (found by
    the fresh-context check). Evidence, library integration in
    `test_check_public_content.py` (a real Git repository and bare remote, a real
    `make` running the target's recipe as the root Makefile defines it, the real
    public-content check): an owner's `git push` running the hook passes a clean
    commit, the secret scan given the remote and the ref line, and refuses a
    private path, the secret scan still running; an up-to-date push passes, the
    scan given no input; `make pre-push` refuses a private path and passes a clean
    commit, refuses when the secret scan refuses, and needs `REMOTE`. The secret
    scan is a stand-in there, recording what it read, since it needs the pinned
    gitleaks; `test_check_secrets.py` runs the real one through the guarded push.
    `make -n` of the target shows both scripts given the remote
    (`test_change_workflow_cli_steps.py`).
- [x] 6.3 End `make run-e2e`'s and `make run-ci`'s output with the bare marker their
  collect waits past — the newest run of the workflow on the branch before the
  dispatch — and fold `make dist-clean` into `make validate-local` and `make
  validate-helm` (D20). Verify: tests in `scripts/tests/test_ci_evidence.py` and
  `test_validate_slice.py` (unit) for the marker as the last line and the wheelhouse
  cleared before a building part; `scripts/tests/test_change_build_and_helm_targets.py`
  passes.
  - Done: `ci_evidence.py pipeline` dispatches `e2e.yml` (`PIPELINE`, not on
    `DISPATCHABLE`, which `dispatch` still refuses it) and `make run-e2e` runs it;
    each dispatch names the run as its fetch takes it (`CI_AFTER_RUN=<id>`, the
    pipeline's `E2E_AFTER_RUN=<id>`) and ends with the ID alone, `0` with no
    earlier run, after the dispatch; a dispatch refused before or by `gh` ends with
    no bare ID. The `dist-clean` half was already true: `validate_slice.py` starts its
    local and Helm parts with `make dist-clean`, which `test_validate_slice.py`
    asserts as each part's first command; what is left over is the validation
    skill's own `make dist-clean`, section 7's. Evidence: the marker last for a
    listed workflow, for none, and for the pipeline, and none after a failed
    dispatch, through `dispatch`, `dispatch_pipeline`, and `main` (unit, `git` and
    `gh` faked); `make -n run-e2e` and `make -n run-ci` running those scripts after
    the round-view check (`test_change_workflow_cli_steps.py`, library
    integration); `test_validate_slice.py` and `test_change_build_and_helm_targets.py`
    pass.
- [x] 6.4 Remove `make code-snapshot` and its `.PHONY` entry (D20). Verify: `make -n
  code-snapshot` fails; `grep -rn code-snapshot Makefile` finds nothing.
  - Done, with the scripts suite's code-snapshot test, which tested only that
    target's zip flags (`git rm`); the round-view test's `code-snapshot` case is
    `run-e2e`'s. `make -n code-snapshot` was denied this session (no rule allows
    `make -n`), so a test runs it and asserts make's "No rule to make target"
    (`test_change_workflow_cli_steps.py`, library integration); Grep finds no
    `code-snapshot` in the Makefile. The triage skill's sentence (7.4) and the
    provision row (8.4) still name it.
  - Reverted, implementation triage 29 O1 (the owner's note: the target is still
    useful): `make code-snapshot`, its `.PHONY` entry, and
    `scripts/tests/test_code_snapshot.py` are restored as they stood before this
    task, and the test asserting the target's absence is removed. It stays a
    target of the repository's own that no skill names, so triage's sentence and
    the role and provision rows stay removed; D20 and the proposal say so. The
    restored test passes (library integration, a real `zip` and `unzip`). Checks:
    see 9.2's triage note.
- [x] 6.5 Verification: `pytest -q scripts/tests/test_change_workflow_config.py
  scripts/tests/test_check_public_content.py scripts/tests/test_check_secrets.py
  scripts/tests/test_ci_evidence.py scripts/tests/test_validate_slice.py
  scripts/tests/test_change_build_and_helm_targets.py` (unit, and library integration
  where a real Git repository is used) passes; `make test` passes; `make
  check-packaging` passes. End-to-end: none in `e2e-tests/`; the round's validation
  runs `run-e2e`, `run-ci`, `validate-local`, and `validate-helm` as changed here, and
  its record is their evidence.
  - Done: the six suites with the CLI-steps, assumptions, and push suites pass;
    `make test-release-tooling` (2591), `make test`, and `make check-packaging`
    pass. End-to-end: confirmed none in `e2e-tests/`; the
    round's validation, once section 7 moves the skill, runs these targets and is
    their evidence. `make check-change` fails only on the specification index
    (10.9).
  - Handoff to sections 7–9: the engine now reads everything sections 4–6 moved
    into `.agents/workflow.toml` (models, protected branches, `pre-push`,
    `post-clone`, inert paths, `load`, evidence), so 7.1's step-table edit can drop
    `models` and `[orchestrator]`; the loader already ignores them. 7.1 should also
    allow `Bash(scripts/change-workflow push --remote *)` only if a skill needs
    it: none does, since clones give their branch an upstream. The merge skill
    still expects `from <branch>` in its invocation, which `start merge` now
    supplies from the recorded branch; `make merge` passes it only with `FROM`.
    The validation skill's `gh run list` and its own `make dist-clean` are what
    7.3 removes: `run-e2e` and `run-ci` now end with their marker, and both local
    and Helm parts clear the wheelhouse themselves. This clone's marker records no
    landing branch (6.1's note).

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
  - Done: the orchestrator's edit was in the worktree and is committed here. Beyond
    the task's text it also gives planning `Bash(scripts/change-workflow check tasks
    *)`, which `change-plan` now names. `scripts/change-workflow check config` was
    denied this session (implementation's rules allow `config *`, not `check
    config`); substitutes: `scripts/change-workflow config load implement`, which
    loads and checks the whole file, and the config suite's
    `test_the_repositorys_own_configuration_passes_its_check`. The steps suite
    (unit, 42 pass) now holds the edited table: validation pushes only through the
    guarded push and dispatches through `run`, which `graph.HOOK_STEPS` holds to
    the validate step; every step reaches its hooks through `run`, validation's and
    archive cleanup's hook targets are refused, and implementation's, triage's, and
    the merge's engineering grants stay; design, planning, triage, and closeout run
    OpenSpec through the command and no step a pinned version; every step reads
    `config load`, `config parts`, and `config --json`; and no step may edit
    `.agents/workflow.toml` while implementation may still edit a skill (CW-z5me;
    its "recorded on the run's line" is the wrapper's existing denial record).
    Validation keeps `gh run list*`, which its skill no longer runs: the table's to
    trim, by the owner.
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
  - Done: implementation (step 5, the merge-resolution run's test step),
    triage, the merge, design, planning, and closeout run `scripts/change-workflow
    run pre-commit <change>` and stage what the hooks rebuilt; implementation's
    step 5 says which hooks the worktree's paths run, and that a change with no
    recorded landing branch gives `--base`. The merge takes one side of a
    conflicted lock and lets `after-functional-change` rebuild it; a merge that
    concluded itself leaves nothing in the worktree for the tier to see, so the
    skill runs `run after-functional-change` and `run pre-commit-functional` by
    name first. Closeout runs `run pre-archive` for packaging, saying so when it
    is skipped, and `scripts/change-workflow openspec archive`; design and
    planning run OpenSpec through `scripts/change-workflow openspec`. The review
    may run `run pre-commit` on its clean checkout. The grep (Grep tool) finds only
    validation's "never … `make lock`", a prohibition.
  - Outside the plan: the skills' sentences naming `openspec/` and `docs/` as the
    paths that need no new validation (triage, the merge, the review, archive
    cleanup, the orchestrating session) now name the repository's inert paths,
    which the engine reads since section 4; the merge skill says the engine
    supplies the recorded landing branch, which section 5 made true; and the
    orchestrating session's clone paragraph describes section 5's clone — `FROM`,
    else the workspace's branch, recorded as the landing branch — and the
    `post-clone` bootstrap.
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
  - Done: validation runs `run validation <change> preflight` first, records
    `config parts <change>`, starts every `start, collect` run after the push and
    collects each in the background, then runs the `run` parts in order keeping
    each `after`, and waits on the engine's closing line; its record's `Parts:`
    line names the plan's runs. Each collect starts in the background right after
    its start, as the pipeline's fetch did, and is waited for after the `run`
    parts: the task's "then every collect". A refused `run` prints `ERROR:` and no
    closing line, so the wait matches either. `HELM_ALL_SCENARIOS` and
    `HELM_CONTEXT` reach the Helm part through the environment, so the root
    `Makefile` no longer appends `with HELM_ALL_SCENARIOS=1` to `make validate`'s
    arguments (outside the plan's files, D8); `test_validate_slice.py` shows `make
    -n validate HELM_ALL_SCENARIOS=1` passes no argument and `validate-helm` takes
    `--all-scenarios` from its environment (library integration, a real `make
    -n`). That make exports a command-line variable to the session it starts is
    GNU make's documented behaviour, which no test here shows, and `HELM_CONTEXT`
    is not exercised. Archive cleanup runs `run cleanup <change>`, commits any tracked file it
    wrote on its own, and checks its index edit with `run pre-commit` (D9 lists
    it) where it ran `check index` and `make check-doc-citations`. Read: every
    command the two skills run is `scripts/change-workflow` (`push`, `config
    parts`, `run`, `next`, `log`, `note`, `find`, `record`, `history`, `check
    round-view`), `git`, or `gh auth status`, besides validation's diagnosis and
    the owner-named `kubectl scale` remedy.
  - Fix, implementation triage 28 F2: validation no longer runs `gh auth status`
    before its push, a GitHub prerequisite outside the plan that a local-only plan
    (CW-g4oz's "A repository has no Helm part") would still have needed; a
    dispatch failing for want of a sign-in fails in its own `start`, diagnosed
    from its output. The step table still grants it, the owner's to trim.
  - Settled, implementation triage 28 F1 (the conflict the note under 7.5 left for
    review): CW-e1sg's delta now says a tracked file a validation part's cleanup
    writes is the repository's own record, which archive cleanup commits on its
    own with no hook before it, with a scenario; D3 records why (running the
    functional hooks after the archive rejected), and archive cleanup's step 8
    says so. No code changes. Checks: see 9.2's triage note.
- [x] 7.4 Every skill loads its documents from `scripts/change-workflow config load
  <step>` where it named `AGENTS.md`, `ARCHITECTURE.md`, `TESTING.md`,
  `DEPLOYMENT_AND_CONFIG.md`, `openspec/README.md`, and the roadmap as its reading
  list (D6, CW-l7hn); a citation of a guidance section for a rule stays. Triage's
  sentence naming `make code-snapshot` is removed (D20). Verify: `make
  check-agent-skills` passes; the delta scenario "Design loads the roadmap" holds for
  `change-design`.
  - Done: design, planning, implementation (and its fresh-context check), triage,
    the merge, closeout, and the review read `config load <their step>`. Closeout
    and the review keep the roadmap as a read for a purpose — closeout's roadmap
    part, the goal the change serves — since `load` names it only for design, and
    a `load.closeout` row would be the owner's edit of the protected file. `make
    check-agent-skills` passes; `config load design` prints the common documents
    and the roadmap in this repository, and the config suite's existing CW-l7hn
    test shows `plan` without it (unit).
  - Outside the plan: the orchestrating session and a guidance review run no step
    of the graph, and `config load` refused anything else, so `config load common`
    prints `load.common` alone (`config.COMMON_DOCUMENTS`, which the
    post-compaction hook reads too); a config-suite unit test covers it. Both
    skills read it. Recorded in D6 and CW-l7hn's delta, so closeout's promotion
    names it; the `cli` help and usage say it.
  - Closeout and the review name the roadmap as the one `openspec/README.md`'s
    documentation placement names, which `load.common` holds, so a reviewer can
    find it. The fresh-context check judged these reads a private exception to
    CW-l7hn; declined, since each is a read for a part's work, not the guidance a
    session loads as it starts. The owner may instead give `load.review` and
    `load.closeout` the roadmap, an edit of the protected configuration.
- [x] 7.5 Verification: `make check-agent-skills` passes;
  `scripts/tests/test_change_workflow_assumptions.py` is run and its failures are
  only those section 8 resolves (`.agents/workflow.toml` and the new subcommands'
  rules unlisted); `make test` passes but for those. End-to-end: none in
  `e2e-tests/`; the round's validation is run by the moved validation skill, and its
  record is the evidence for 7.3.
  - Correction: 7.2, 7.3, and 7.4 carried their notes but were left unchecked
    in the section's commit; they are checked in a later commit, their evidence
    re-run at `HEAD` after sections 8 and 9 (the 7.2 grep, `make
    check-agent-skills`, `config load design`, and reading archive cleanup's
    commands), which touched no skill.
  - Done: `make check-agent-skills` passes; the assumptions suite fails only on
    `.agents/workflow.toml` unlisted (named in the step table), which 8.4 lists.
    `make test` ran every suite to `test-release-tooling`, which failed on that
    one test alone (2595 passed); make stopped there, so `helm test-render` and
    `test-frp-grant-admission`, which the section does not touch, did not run
    (section 8's `make test` runs them). The steps, config, CLI, validate-slice,
    and assumptions suites pass but for that test. `make check-change` fails only
    on the specification index (10.9). End-to-end: confirmed none in
    `e2e-tests/`.
  - Until section 8 adds `make check-repository`, every `run pre-commit` the skills
    now run fails at the `pre-commit` hook in this repository; sections 7 and 8
    are committed one after the other in one session, so no step runs between
    them.
  - For the review and triage, found by the fresh-context check and not the
    implementer's to settle: archive cleanup commits what a cleanup wrote, such as
    `helm/validation-capacity.toml`, a path outside the inert paths, with no
    functional hooks, as D3 and CW-ikmm say; CW-e1sg says such a commit runs the
    functional tier and that only implementation, triage, and the merge make
    functional commits, and the hook table refuses archive cleanup that tier. One
    of the two needs the owner's wording. The step table, the owner's to trim,
    still allows validation `gh run list*` and closeout the bare `openspec
    archive *`, which no skill runs now.

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
  - Done: the script keeps its name and reads `base` from `find --json` through
    `workflow_command.found_change`, as it already read `archived`; with neither
    it refuses before any check, naming `--base` and `CHANGE_BASE`. Its pinned
    validator (`OPENSPEC`, `openspec_command`) is gone with the validation. The
    suite (17 pass) lists exactly the eight checks and their commands, a failing
    one shown alone, `--base` overriding, an unknown change refused, and the
    refusal naming `--base` and `CHANGE_BASE`. The cases through `run_checks` are
    library integration, not the task's unit: each runs the real command's `find
    --json` in a real `git init`, the base cases reading a clone marker written
    under `.git/` as a clone records it; the list of checks and the argument
    parsing are unit. `make -n check-repository` with and without `CHANGE_BASE` is
    in `test_change_workflow_cli_steps.py` (library integration, a real `make -n`).
    The sibling checks' docstrings name `make check-repository` as their caller.
- [x] 8.2 `make check-change CHANGE=<change>` runs `scripts/change-workflow run
  pre-commit <change>`, so the four defaults and then `make check-repository` run,
  each once (D11). Verify: `make check-change CHANGE=add-workflow-capability-contract`
  prints the defaults and the repository's checks once each, and its failures are
  those `make check-change` reported before the change, no fewer.
  - Done: `CHANGE_BASE` becomes `--base`, which this clone needs (6.1's note).
    `make check-change CHANGE=add-workflow-capability-contract CHANGE_BASE=dev`
    ran each check once: with section 8's code in the worktree it ran the
    functional tier first — `make lock` (no lock changed), `make check-packaging`,
    and the whole `make test`, all passing — then the four defaults and `make
    check-repository`. It fails on the specification index, as `make check-change`
    did before (10.9), and on one more: the default OpenSpec check, since this
    machine has no `bunx` (`sh: 1: bunx: not found`, exit 127) and the
    configuration's `openspec.command` is `bunx @fission-ai/openspec@1.14.0`,
    where the old script fell back to `npx --yes` without `bunx`. The validation
    itself passed here through that fallback after section 7's last delta edit,
    and section 8 changed no delta. The configuration is the owner's to edit
    (CW-z5me); see the handoff below. `make -n check-change` with and without
    `CHANGE_BASE` is in `test_change_workflow_cli_steps.py`, whose `make -n`
    helper now drops an inherited `CHANGE_BASE`, which the outer `make
    check-change CHANGE_BASE=dev` exported into the suite's environment.
- [x] 8.3 The step table's loader refuses a row carrying `models` and an
  `[orchestrator]` row, naming it, now that task 7.1 removed them (D5). Verify: unit
  tests in `scripts/tests/test_change_workflow_steps.py`; the repository's table
  loads.
  - Done: each refusal names the configuration's field that holds the value
    (`models.<step>`, `models.orchestrator`). The steps suite (unit) refuses both
    and loads the repository's table; its malformed-table cases no longer carry
    `models`. The CLI suite's test that the loader accepted them is removed.
- [x] 8.4 Bring the inventory to what the test collects (D18, CW-m4ps, MCW-5tgp):
  `test_change_workflow_assumptions.py` collects `.agents/workflow.toml`'s commands
  as provisions, and the two `README.md` tables list `.agents/workflow.toml` and the
  new subcommands' rules and no longer list the targets no skill or rule names
  (`make code-snapshot`, validation's moved targets as skill invocations); the full
  description of the configuration is closeout's (task 10.9). Verify: the test passes
  and fails, naming the target and the skill, when a fixture skill names an
  unlisted target (CW-m4ps's scenarios).
  - Done: `configured` reads the configuration's hooks', preflight's, and parts'
    commands (not `load`'s documents) as provisions beside the tables. The roles
    lose "A snapshot of the code"; the provisions name the configuration's parts
    and hooks where they named validation's and archive cleanup's targets, and
    `make check-repository` with `make check-change` over `run pre-commit`; the
    engine's assumptions gain the configuration at its fixed path
    (`config.CONFIGURATION`; `.agents/workflow.toml`), and this repository's step
    table row its new deny and grants. Outside the task's list, the provisions'
    landing branch (no longer `CHANGE_WORKFLOW_MERGE_FROM`), remote, protected
    branches, and bootstrap rows say what the configuration and the clone now
    provide; the fragment's `orchestrate` description names `models.orchestrator`.
    CW-m4ps's delta now says the test fails on what both the statement and the
    configuration's commands omit, as MCW-5tgp already did. Evidence (12 pass):
    the test passes against the repository, reading its tracked tree through `git
    ls-files` and its real documents and configuration (library integration);
    CW-m4ps's scenarios on fixtures — a skill naming an unlisted target fails naming
    both, against the statement and the configuration together, a target only the
    configuration provides passing; a role with no provision fails naming it — and
    the configuration's commands collected, its documents not (unit). The rest of
    both `README.md` — the engine's assumptions still naming the removed
    constants, this repository's "The closing checks" — and `change-workflow`'s
    `spec.md` pairing the closing checks with `scripts/check_change.py` as
    evidence, are 10.9's.
- [x] 8.5 Verification: `pytest -q scripts/tests/test_check_change.py
  scripts/tests/test_change_workflow_steps.py
  scripts/tests/test_change_workflow_assumptions.py` (unit) passes; `make check-change
  CHANGE=add-workflow-capability-contract` fails only on the citations of files
  closeout writes and the spec index entries closeout's promotion writes; `make
  test` passes; `make check-packaging` passes. End-to-end: none; no scenario
  exercises the workflow tooling.
  - Done: the three suites pass (154 with the CLI-steps suite); the check-change
    and assumptions suites are partly library integration (8.1's and 8.4's
    notes), the steps suite unit. `make test` and `make check-packaging` pass, run as
    `pre-commit-functional` inside `make check-change` (8.2), every suite through
    `test-frp-grant-admission` included. `make check-change` fails only on the
    specification index and, on this machine, the default OpenSpec check for want
    of `bunx` (8.2). End-to-end: confirmed none.
  - Handoff: this repository's `openspec.command` names `bunx` alone, so on a
    machine without it — this clone's — every `run pre-commit`, and so every
    committing skill's check and `make check-change`, fails its OpenSpec default.
    The old closing check ran `bunx` where installed, else `npx --yes`. Fixing it
    is an edit of `.agents/workflow.toml`, the owner's or the orchestrating
    session's on the owner's word: for example `command = "npx --yes
    @fission-ai/openspec@1.14.0"`, which needs only Node, or a repository script
    choosing between them; or the owner accepts that the configured command needs
    `bunx` on every machine. It is put to the owner, not settled here.
    `make check-change`'s target comment, this repository's "The
    closing checks" in `market-change-workflow`'s `README.md`, and the guide
    (section 9) are where the closing checks are described.

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
  - Done: "Skills" gains "The repository's hooks" — `.agents/workflow.toml`, `run`
    and its closing line, `run pre-commit`'s tiers, `run pre-archive`, `config
    parts` and `run validation`, `run cleanup`, `config load`, `openspec`, the
    configuration protected from steps — and the validation, merge, and archive
    cleanup rows and the CI paragraph say what runs through them; the closing
    checks are `make check-change` over `run pre-commit`, the four defaults and
    `defaults.disable`, `make check-repository`'s eight checks, `check change`, and
    the diff checks' base from the clone's record. "The engine's command" lists
    `run`, `config`, `config load` (with `common`), `config parts`, `check
    config`, `check change`, `openspec`, `push --remote`, and `clone-remove
    --base`, says what `start` requires, `find --json`'s `base`, `start
    orchestrate` on `models.orchestrator`, and that the fragment sets no value of
    the repository's. The guide never named `code-snapshot`. Outside the task's
    list, the passages sections 4 and 5 left stale say what is now true: the step
    table without models and the model policy, the protected branches, the merge's
    and the review's base from the clone's record, the clone recording its
    landing branch and its upstream, the `post-clone` bootstrap, clone removal
    against the recorded branch with `BASE`, and the ledger's inert paths. The
    shell completion names no removed target or variable, so nothing is dropped.
    `make check-doc-citations` passes, but it reads only the change's own
    documents, not the guide — run without `CHANGE` it named this change all the
    same — so the guide's cited paths (`.agents/workflow.toml`,
    `scripts/check_change.py`, `scripts/ci_evidence.py`, the fragment, the step
    table) were checked by hand, by the fresh-context check; the plan's verify
    has the same gap. The completion suite passes (library integration, a real
    `bash`). The fresh-context check's corrections are in: the hook table binds
    unattended runs only, the review's models are the configuration's, the
    validation preflight is named, and clone removal's `BASE` is described as the
    code checks it.
- [x] 9.2 Verification: `make check-doc-citations
  CHANGE=add-workflow-capability-contract` and `make test` pass but for files
  closeout writes. End-to-end: none; no scenario exercises the guide.
  - Done: `make check-doc-citations` passes. Section 9 changes no code: `make
    test` passed in full in section 8 (8.2), and `make test-release-tooling`
    (2597) after section 8's last fixes, which changed tests, docstrings, and
    target descriptions only. `scripts/change-workflow run pre-commit ... --base
    dev` over this documents-only worktree ran `pre-commit` alone, its tier, and
    failed only on the specification index (10.9) and this machine's missing
    `bunx` (8.5's handoff). End-to-end: confirmed none.
  - Implementation triage of the round (review 28, the owner's notes 29,
    validation 31), fixes made against `820629f39`: 28 F1 (7.3), 28 F2 (7.3),
    28 F3 (5.1), 28 F4 (1.5), 31 A1 (3.2), 29 O1 (6.4), 29 O2 (6.1); each is noted
    under its task. Evidence: the config, hooks, clone, push, CLI-steps,
    code-snapshot, assumptions, CLI, and find suites pass, 530 together (unit and
    library integration, as each note says), the clone suite 80 after the last
    docstring edit. `scripts/change-workflow run pre-commit
    add-workflow-capability-contract --base dev` ran the functional tier:
    "[change-workflow] after-functional-change at 820629f39…: passed, exit 0"
    (no lock changed), "[change-workflow] pre-commit-functional at 820629f39…:
    passed, exit 0" (`make dist-clean`, `make check-packaging`, the whole `make
    test`), then `pre-commit`: the index, tasks, and skills checks passed; it
    closed "failed, exit 127" on the OpenSpec default (`bunx` absent here, 8.5's
    handoff) and `make check-repository`, which failed on the specification
    index (10.9) and on history wording in two of this fix's docstrings ("no
    longer"). Those two were reworded, after which `make check-repository
    CHANGE=add-workflow-capability-contract CHANGE_BASE=dev` fails on the
    specification index alone. Not run: the strict OpenSpec validation of the
    delta edits (CW-e1sg, CW-g4oz, CW-8jyb, MCW-r4tx), since `bunx` is absent and
    no rule of the triage step allows `npx`; the fix commit's validation, and
    closeout's 10.10, run it where it can. A fresh-context check of the diff found
    no blocking defect; taken from it: `_push_remote` passes over an upstream
    naming a remote the workspace lacks (with a test), an existing clone's
    upstream is left alone until its push remote is added, D4 records the
    derivation, the test docstrings cite CW-8jyb rather than D4, the
    `command_environment` docstring states what a command-line variable keeps,
    10.9 names the clone diagrams, and two wrapping fixes. Declined: removing the
    step table's `gh auth status` grant to validation and its steps-suite chain,
    and the orchestrating skill's `pull --no-rebase origin dev`, which hold in
    this repository; the step table is the owner's to trim.
  - Pre-closeout triage (review 45), documents only: 45 F1 — CW-g4oz states the
    order within each shape (started parts in declared order, then `run` parts in
    declared order), with a scenario for a `run` part declared before a started
    one, and D3 records it; the loader and the skill already behave so. 45 F2 —
    D3's example configuration names `scripts/openspec`, the command
    `.agents/workflow.toml` holds since the owner chose a runner script over
    8.5's handoff options.

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
  - Done: the list gains `config` (with the subcommands dispatched to it: `config`,
    `config load`, `config parts`, and `check config`), `hooks` (`run`'s hooks and
    parts, the closing line, the marker kept from a dispatch for its collect, and,
    beyond the plan's wording, `check change` and `openspec`, which `cli.py`
    dispatches to it), and `wait`; `steps` holds each step's skill, its permission
    rules, and what a model is, its models being the configuration's; `running`
    also keeps a session's invocations through `run` and the guarded push until
    its log line records them. Every other entry, the fragment's paragraph, and the
    `Contract:` line still hold and are unchanged. The 31 modules beside
    `__init__.py` are each named once and no name lacks its file (checked with
    Grep against the glob, the planned inline script being denied); `make
    check-comment-hygiene` passes; the docstring names no change, task, review,
    or history. No test reads the docstring: the list's correctness rests on this
    comparison, repeated by the fresh-context check, which found no violation and
    whose two wording gaps (`steps` defines what a model is; `hooks` serves `check
    change` and `openspec`) were taken.
- [x] 11.2 Verification: `scripts/change-workflow run pre-commit
  add-workflow-capability-contract --base dev` (this change's clone records no
  landing branch, being older than the record), whose functional tier runs, since `scripts/` is
  outside the inert paths, fails on nothing but the specification index entries task
  10.9 writes; `pytest -q scripts/tests/test_change_workflow_cli.py` (unit) passes.
  End-to-end: none; no scenario exercises the workflow tooling, and a docstring
  changes no behaviour.
  - Done: `scripts/change-workflow run pre-commit add-workflow-capability-contract
    --base dev` ran the functional tier: "after-functional-change at 199a7a3c4…:
    passed, exit 0", "pre-commit-functional at 199a7a3c4…: passed, exit 0" (the
    packaging check and the whole `make test`), then `pre-commit`: the index,
    tasks, and skills checks and `scripts/openspec validate … --strict` passed,
    and it closed "failed, exit 2" on `make check-repository`, whose one failing
    check of eight is the specification index (10.9's entries). The last wording
    fix to the docstring came after that run; `make check-repository` rerun after
    it fails on the specification index alone. `uv run --no-project --with pytest
    pytest -q scripts/tests/test_change_workflow_cli.py` (unit; the bare `pytest`
    the plan names is not allowed this step): 153 passed, before and after that
    fix; it imports the package, so the docstring parses, and shows nothing of the
    list's content. End-to-end: confirmed none. Owed by validation: nothing; the
    owner waived this round's review and validation (log seq 82).
  - Handoff: closeout resumes at 10.1, whose finding this section fixed; 10.2 and
    10.7 are owed again over this commit. The engine-parts section of
    `openspec/specs/change-workflow/README.md` still lacks `config`, `hooks`, and
    `wait` and says `steps` reads models, which 10.9's promotion covers.

## 10. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only; a part that needs code returns the change to
implementation.

- [ ] 10.1 Comment hygiene: run `make check-comment-hygiene`; confirm no comment the
  change added names this change, a task, or the review that introduced it, and that
  `config.py`, `hooks.py`, and the modules sections 4–5 changed describe the current
  system. A finding returns the change to implementation.
  - Closeout at `8aa8f375e`, returned: `make check-comment-hygiene` passes, and no
    comment the change added names a review, triage, or migration (the added
    comment lines read for "review", "triage", "migration", "no longer", "previous",
    "interim", "handoff"; each "review" names the review step). `config.py`,
    `hooks.py`, `running.py`, `cli.py`, `steps.py`, `review.py`, and `wrapper.py`
    describe the current system. One docstring does not: the package's module
    list in `scripts/change_workflow/__init__.py`, which `change-workflow`'s
    `spec.md` Evidence names as where the modules are listed with their roles,
    omits the two modules the change added, `config` (the repository's workflow
    configuration, read and checked whole) and `hooks` (running the repository's
    hooks, validation's parts, and the kept markers), still says `steps` holds each
    step's "permissions, and models", and does not say `running` keeps a session's
    invocations through `run` and the guarded push. Fixing it is a code edit, so
    the change returns to implementation for a fix round of that docstring alone;
    closeout resumes after it.
- [ ] 10.2 Import placement: check every import the change added inside a function
  (`make check-local-imports CHANGE_BASE=dev` among the closing checks) for a stated
  reason; one that should move returns the change to implementation.
  - Closeout at `8aa8f375e`: `make check-local-imports CHANGE_BASE=origin/dev`
    passes; the change adds no import inside a function (no indented `import` among
    its added `.py` lines). To be confirmed again after the fix round.
  - Run out of order before the return, and owed again once the fix round's commit
    exists: 10.7's `scripts/change-workflow run pre-archive
    add-workflow-capability-contract` passed at `8aa8f375e` (`make check-packaging`;
    `make check-architecture-change`: "owns no architecture row").
- [ ] 10.3 Documentation compliance: check D1–D21 and P1–P4 against
  `openspec/README.md`'s placement rules: subsystem behaviour in the two `spec.md`,
  rationale in their `README.md`, the guide's procedure in
  `docs/agents/change-workflow.md`, nothing repository-wide for `ARCHITECTURE.md`.
- [ ] 10.4 Narrative compression: shorten this file's task notes to final behaviour,
  evidence, and destinations, moving any rationale into `design.md` first.
- [ ] 10.5 Roadmap currency: no goal of `docs/development/ROADMAP.md` covers the
  change workflow; record that disposition in the design-promotion record.
- [ ] 10.6 Campaign index currency: in `openspec/changes/README.md`, this change's row
  (status, notes); the lesser goal "Make the change workflow a tool any repository can
  adopt": its gap row "No single file states what the workflow assumes about a
  repository" removed, and its current state rewritten where it says repository
  assumptions are listed, not declared, and that the allowlist names this
  repository's make targets; dependents (`sandbox-unattended-workflow-steps`,
  `add-skill-extension-points`, `extract-change-workflow-repository`) left as they
  are, released at archive cleanup. Run `make check-change-index`.
- [ ] 10.7 Packaging: `make check-packaging`, then `make check-architecture-change
  CHANGE=add-workflow-capability-contract`; `make check-agent-skills`, since the
  change touched `.agents/` and `.claude/`.
- [ ] 10.8 End-to-end pipeline: record the latest validation's pipeline run of the
  closeout's code, its result, and that no scenario exercises the workflow tooling,
  the run being evidence that the changed `run-e2e`, `run-ci`, `validate-local`, and
  `validate-helm` targets and the moved validation skill work.
- [ ] 10.9 Promotion, and the design-promotion record in `design.md`:
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
- [ ] 10.10 Documentation citations: `make check-doc-citations
  CHANGE=add-workflow-capability-contract`, resolving every match, then
  `scripts/change-workflow openspec validate add-workflow-capability-contract
  --strict`.
- [ ] 10.11 Archival: `scripts/change-workflow openspec archive
  add-workflow-capability-contract -y`, merging the `change-workflow` delta (19
  added, 3 renamed, 18 modified) and the `market-change-workflow` delta (2 added, 1
  modified, 2 removed), no `--skip-specs`; the row then links the archived directory,
  and `make check-spec-index` passes unscoped.
