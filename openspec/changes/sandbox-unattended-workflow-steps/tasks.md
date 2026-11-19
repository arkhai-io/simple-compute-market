# Tasks

The engine's tests below are named by level as
`docs/guidance/engineering/test-levels.md` defines them: **unit** for a pure function
(a scope's resolution, the configuration's check, a comparison of recorded states,
the sandbox `git`'s decision), and **library integration** for the engine's commands
and launcher driven in process against a real temporary Git repository and, where
the machine runs it, real bubblewrap, the harness doubled by a program the test
writes. A library-integration test needing bubblewrap is skipped, saying so, where
the engine's own probe finds it cannot run; on this machine it runs, and a section's
verification names it as run. No end-to-end scenario exercises the workflow's
tooling: in every section below, validation's pipeline result is not evidence for
the change, and none is owed.

The change rewires the engine it runs on, and each section's commit leaves the engine
runnable and `scripts/change-workflow run pre-commit` passing. Until section 11
removes it, `.claude/change-steps.toml` still holds every session implementing this
change: an edit of `.agents/workflow.toml` or under `.claude/` is the orchestrator's,
made on the owner's word before the section's session starts, and the session
commits it with its section. Nothing launches a step inside the sandbox until
section 7 wires it, so sections 1 to 6 add parts the wrapper does not yet call.

## 1. Each step's definition in the engine, and the index

Delivers each step's skill, `resume_from`, profile, and baseline scope held in the
engine beside the graph, read by nothing yet, and the specification indexes the
change's deltas need on every commit (D11, D5's table; CW-m8wq's baseline, CW-k5mk's
`resume_from` unchanged in behaviour). Files: `scripts/change_workflow/graph.py`,
`openspec/specs/change-workflow/index.md`, `openspec/specs/market-change-workflow/index.md`,
`scripts/tests/test_change_workflow_graph.py`.

- [x] 1.1 In `openspec/specs/change-workflow/index.md`, add entries for the ids the
  change's deltas add — under "### Permissions": CW-x3pf, CW-m8wq, CW-r6kd, CW-v5ny,
  CW-w3oa, CW-t6mb; under "### Step runs and outcomes": CW-q7ub, CW-f9le; under "###
  The guarded push": CW-j4cs; under "### Interactive runs": CW-g5ry; under "### A
  repository's configuration": CW-h2zt; beside CW-dtpz: CW-k8dn; beside the round
  view's entries: CW-p3vz — each linked to its requirement's heading; move the links
  of the ten renamed requirements (CW-qu42, CW-4yhk, CW-k5mk, CW-svng, CW-5rmh,
  CW-vdqj, CW-jqi7, CW-drf6, CW-b5cf, CW-hak6) to their new headings; and move
  CW-2lvd, CW-2h9t, and CW-56zq to "## Retired ids" with where each rule went (their
  delta's Migration). In `openspec/specs/market-change-workflow/index.md`, add
  MCW-s4bx under "## 4. This repository's workflow values". The index check resolves
  entries against the deltas, so the repository's closing checks pass on every commit
  before the archive (a repository obligation, `openspec/README.md#the-index-check`);
  closeout's promotion revises the summary lines (12.9). Verify: `make
  check-spec-index CHANGE=sandbox-unattended-workflow-steps` passes.
  Done: `make check-spec-index CHANGE=sandbox-unattended-workflow-steps` and the
  unscoped `make check-spec-index` pass. The new entries carry provisional summary
  lines; the renamed entries keep their old summaries until 12.9 revises them.
- [x] 1.2 In `graph.py`, beside `HOOK_STEPS` and `STEP_ACTIONS`, hold each step's
  definition: its skill and `resume_from` as `.claude/change-steps.toml` gives them
  today, its profile (read-only for the review, workspace for the rest), and its
  baseline scope in the workflow's own terms only (CW-n8tr) — the review: in the
  checkout only `.git/change-invocations/`; design and plan: `openspec/`, `.git/`;
  implement, triage, merge, validate: the checkout; closeout: the repository's inert
  paths and `.git/`; archive cleanup: `openspec/changes/`, `.git/`; every step a
  temporary directory, and every step but the review `~/.cache` (D5, D11). Verify:
  unit tests that every step of `graph.STEPS` with a run has one definition, that the
  skills and `resume_from` equal the step table's today, and that the review's
  baseline holds no other checkout path.
  Done: `graph.STEP_DEFINITIONS` maps each step to a `StepDefinition` (skill,
  profile, baseline, `resume_from`). The profiles are `READ_ONLY` and `WRITING`.
  The plan's "workspace" was renamed, since the workflow's "workspace" is the
  owner's. Two baseline entries are named by role: `INERT_PATHS` (closeout's) and
  `TEMPORARY`. Every other entry is a checkout path, a `.git/` path, or a `~`
  path. The review's invocation path is built from `running.INVOCATIONS`. Unit tests
  in `test_change_workflow_graph.py`, all passing:
  - one definition per step;
  - the skills and `resume_from` equal `load_steps()`'s;
  - the review's checkout paths are only `.git/change-invocations/`;
  - every step writes the temporary directory;
  - each writing step's baseline and `~/.cache`.
- [x] 1.3 Verification point: `test_change_workflow_graph.py` (unit) and `make
  check-spec-index CHANGE=sandbox-unattended-workflow-steps`; `scripts/change-workflow
  run pre-commit sandbox-unattended-workflow-steps` passes.
  End-to-end: none — no scenario exercises the workflow's tooling.
  Done:
  - `make test-release-tooling TESTS=scripts/tests/test_change_workflow_graph.py`
    (unit) passes, and so does `make check-spec-index`.
  - `run pre-commit`'s functional hooks pass: the relock, packaging, and every suite
    in `make validate-local`, including 3383 scripts tests.
  - Its `pre-commit` fails one check of nine, `check-doc-citations`. This plan's
    `tasks.md` cites eight files that sections 2 to 5 and 9 create: `scope.py`,
    `sandbox.py`, `invariants.py`, `propose.py`, and their tests. The check fails
    until the last of them exists. No permanent document is involved.
  - Outside the plan, a fix: `test_change_workflow_assumptions.py`'s `configured`
    now reads `openspec.command`. The maintenance commit before this branch let
    every step run `scripts/openspec validate`. The roles test then failed on
    `scripts/openspec`, which the configuration names only as its OpenSpec command.
  - Not fixed: in two of three runs the relock (`make lock`, the
    `after-functional-change` hook) rewrote two locks,
    `kit/capability-admissibility/uv.lock` and `kit/capability-pricing/uv.lock`. Each
    then resolved `arkhai-kit-capability-shape` 0.3.0 from PyPI rather than `.dist`,
    against `docs/guidance/repository/wheelhouse.md`'s internal-package rule. The
    third run's relock left both as committed, so the section commits neither.
  Handoff:
  - Nothing reads `STEP_DEFINITIONS` yet: section 7 moves the wrapper onto it.
  - Section 2 should resolve `.git/` entries through Git
    (`git rev-parse --git-path`) rather than as checkout paths, so a linked
    worktree's Git directory resolves too.
  - Run `run pre-commit` alone. A second `run pre-commit` in the same checkout, such
    as a helper's, clears `.dist` under the first, and the first's kit tests then
    fail to resolve.

## 2. `[sandbox]` and a step's resolved scope

Delivers the configuration's `[sandbox]` table and its check, the resolution of a
step's scope from the engine's baseline, an adapter's paths, the repository's
additions, and grants, and its listing in `config` (D12, D8's path rules, D5a, D4's
protected ancestors; CW-h2zt, CW-o6kc, CW-m8wq, CW-r6kd's protected set). Files:
`scripts/change_workflow/config.py`, a new `scripts/change_workflow/scope.py`,
`cli.py`'s `config`, `scripts/tests/test_change_workflow_config.py`, a new
`scripts/tests/test_change_workflow_scope.py`.

- [ ] 2.1 In `config.py`, read `[sandbox]`: `writable.common`, `writable.<step>` for a
  step of `graph.STEPS`, and `protected`, each a list of paths; refuse, naming the
  field, an unknown key, a wrong type, `writable.review`, an unknown step, a glob
  character outside a path's pattern form, and a writable entry that is or lies under
  a protected path — the engine's (`.agents/workflow.toml`, `.git/config`, the
  engine's `git`) or the configuration's own — while admitting a directory that
  contains one (D12; CW-h2zt, CW-w8ne). An absent table is every list empty. Verify:
  unit tests for each refusal, each naming the field, and for CW-h2zt's three
  scenarios.
- [ ] 2.2 In `scope.py`, resolve a step's scope for one run as absolute paths: the
  baseline (1.2), the adapter's state and protected paths passed in by the caller
  (section 6 supplies them), the repository's additions, and the run's grants;
  relative entries from the checkout's root and `~` the home directory; a file or
  pattern entry mounting each match's directory (D5a; closeout's inert paths), a
  pattern matched against the checkout as the run starts; the protected set — the
  engine's, the adapter's, the repository's — each kept read-only inside any writable
  directory that contains it (D4, D12). Each path carries its source: engine,
  adapter, repository, or grant. Verify: unit tests resolving design's, the review's,
  and closeout's scopes on a fixture checkout, closeout's `**/README.md` yielding each
  README's directory and `AGENTS.md` the root, and `.agents/workflow.toml` protected
  inside a writable checkout.
- [ ] 2.3 Grant parsing as `scope.py` takes it (D8; CW-tl5v): each value split on `;`,
  parts trimmed, empties dropped; a value with a glob character refused, naming it; a
  path that is or lies under a protected path refused, naming it; a directory
  containing one admitted, the protected path read-only inside; a file mounting its
  directory; an absent path marked to be created as a directory before launch. The
  command line takes it in section 8. Verify: unit tests for CW-tl5v's pattern
  scenario, a protected path, a protected ancestor, a file, and an absent path.
- [ ] 2.4 `config` and `config --json` list each step's resolved scope — writable and
  protected paths, each with its source — the adapter's paths absent until section 6
  adds them (CW-o6kc). Verify: a library-integration test of `config --json` on a
  fixture repository declaring `writable.plan = ["docs/"]` finding planning's
  `openspec/` and `.git/` from the engine and `docs/` from the repository (CW-o6kc's
  scenario, but for the adapter's paths, which 6.5 adds).
- [ ] 2.5 Verification point: `test_change_workflow_scope.py` and
  `test_change_workflow_config.py` (unit, library integration); `run pre-commit`
  passes. End-to-end: none.

## 3. The bubblewrap launcher, its probe, and the unconfined fallback

Delivers the engine's sandbox: a resolved scope rendered as a `bwrap` command around
any program, protected paths created when absent, the probe, and what the wrapper is
told when the sandbox cannot run (D3, D4, D10, D5b's mount; CW-x3pf, CW-r6kd,
CW-m8wq, CW-v5ny). Files: a new `scripts/change_workflow/sandbox.py`, a new
`scripts/tests/test_change_workflow_sandbox.py`.

- [ ] 3.1 `sandbox.py` renders a scope as `bwrap` arguments: the root filesystem
  read-only, `/dev` and `/proc`, the temporary directory, each writable path
  `--bind` over it, each protected path `--ro-bind` after them, any further read-only
  file binds a caller adds (section 4 adds the engine's `git`), the network and
  environment shared, `--die-with-parent`, then the program and its arguments (D4;
  CW-x3pf). A protected path absent at launch is created first — `{}` for a `.json`
  file, an empty file otherwise — and bound like any other; a granted path absent at
  launch is created as a directory (D4, D8; CW-r6kd). Verify: unit tests of the
  rendered arguments' order for a design scope, and of the creation of an absent
  `.claude/settings.local.json` as `{}`.
- [ ] 3.2 The probe: one trivial program run under `bwrap` before a launch, its
  failure — `bwrap` missing, user namespaces refused — returning the reason, and the
  launch then the program unconfined, with the reason for the wrapper's warning and
  `unconfined: true` (section 7 records it) (D10; CW-v5ny). Verify: unit tests with
  the probe doubled for both failures; a library-integration test that the real probe
  passes on this machine.
- [ ] 3.3 Library-integration tests through real bubblewrap, a shell program standing
  in for the harness: a write inside the scope succeeds; a write outside it fails as a
  read-only file system; a write to a protected file fails, and a rename over it fails
  busy (CW-r6kd's `git config core.hooksPath` scenario, on a real repository); an
  absent settings file cannot be created (CW-r6kd's scenario); the Docker socket's
  path, where present, stays connectable (D4); the sandboxed program is killed when
  its parent dies (`--die-with-parent`); and the program reads a file outside its
  scope (P3; CW-x3pf's reads). Verify: these tests pass here, each skipped elsewhere
  with the probe's reason.
- [ ] 3.4 Verification point: `test_change_workflow_sandbox.py` (unit, library
  integration through real bubblewrap); `run pre-commit` passes. The note records
  whether a native Ubuntu install was at hand to run the probe on; where none was,
  `design.md`'s open question on AppArmor stays open. End-to-end: none.

## 4. The sandbox's `git`, the guarded push's record, and the upstream after a run

Delivers the engine's `git` bound over the system's two, refusing any push but the
guarded push's under a run and recording each refusal; the guarded push recording
each push's result and setting no upstream under a run; and the engine setting a
missing upstream after the session (D2; CW-j4cs, CW-59c7, CW-w3oa's pushes). Files:
a new executable `scripts/change_workflow/sandbox-git`, `sandbox.py`, `push.py`,
`running.py`, `wrapper.py`, `scripts/tests/test_change_workflow_sandbox.py`, a new
`scripts/tests/test_change_workflow_sandbox_git.py`, `scripts/tests/test_check_push_ready.py`
where it covers `push.py`.

- [ ] 4.1 Write `sandbox-git`: while `CHANGE_WORKFLOW_UNATTENDED` is set and the
  guarded push's marker is not, it refuses a `push` subcommand wherever it stands
  among Git's options — `--no-verify`, `-c core.hooksPath=…`, `-C <dir>` among them —
  printing why and exiting non-zero, and records the refusal, with its command line,
  among the session's invocations (`running.keep_invocations`); otherwise it executes
  the real Git at the path the sandbox binds it to (D2; CW-j4cs). Verify: unit tests
  of the decision for each option form, a non-push command, the marker unset, and the
  guarded marker set.
- [ ] 4.2 `sandbox.py` binds the real `/usr/bin/git` at a path only `sandbox-git`
  names, then `sandbox-git` read-only over `/usr/bin/git` and `/usr/lib/git-core/git`
  (Git's exec path), both protected (D2, D4; CW-r6kd). Verify: library-integration
  tests through real bubblewrap on a repository with a bare remote: `git push`, `git
  push --no-verify`, `git -c core.hooksPath=/dev/null push`, and
  `/usr/lib/git-core/git push` are refused and nothing reaches the remote; `git
  status` and `git commit` work (CW-j4cs's scenarios).
- [ ] 4.3 `push.py` sets the guarded push's marker in the environment of the `git push`
  it runs, so `sandbox-git` lets it through, and, under a run, records each attempted
  push once Git returns — branch, remote, commit sent, Git's exit status — among the
  session's invocations; under a run it never passes `--set-upstream` (D2; CW-59c7).
  Outside a run nothing changes. Verify: library-integration tests: the guarded push
  through real bubblewrap reaches a bare remote and its record names the commit and
  status 0; a push Git fails after the pre-push hook passed is recorded with its
  failing status (CW-59c7's "An unattended push fails"); outside a run the owner's
  push sets its upstream as today.
- [ ] 4.4 After a session ends, before its line is written, the wrapper sets the
  branch's upstream outside the sandbox to the remote of the run's last successful
  guarded push of that branch, as its record names it, and sets none where no push of
  it succeeded (D2; CW-59c7's "An unattended run pushes a branch with no upstream").
  Verify: library-integration tests with the harness doubled pushing a branch with no
  upstream, and failing to.
- [ ] 4.5 Verification point: `test_change_workflow_sandbox_git.py` (unit, library
  integration through real bubblewrap), the push and wrapper tests above; `run
  pre-commit` passes. End-to-end: none.

## 5. The seven checks after every run

Delivers the state recorded as a session starts, the seven checks after it, and the
stopped outcome a violation logs, wired into the wrapper and the review so every run
after this section is checked, confined or not (D6, D5c; CW-q7ub, CW-f9le,
CW-4yhk's relock scenario). Files: a new `scripts/change_workflow/invariants.py`,
`wrapper.py`, `review.py`, `log.py`, a new `scripts/tests/test_change_workflow_invariants.py`,
`scripts/tests/test_change_workflow_wrapper.py`, `test_change_workflow_review.py`.

- [ ] 5.1 `invariants.py` records at a session's start the commit, the branch, the
  workflow log's and the ledger's lengths and the hash of their contents up to them,
  each review record's hash, `refs/stash`, and the remote's change branch and
  protected branches (D6). Verify: unit tests of the recorded state on a fixture
  repository.
- [ ] 5.2 The checks against it after the session: (1) `HEAD` on the change's branch
  and descending from the start commit; (2) for validation and review, `HEAD` and
  every tracked file unchanged; (3) the log only appended to; (4) each review record
  unchanged and the ledger only grown at its end; (5) `refs/stash` unchanged; (6)
  after one fetch, the remote's change branch at the last successful guarded push its
  record names (4.3) or unchanged, and no protected branch holding a commit made in
  the run; (7) for closeout, every path changed since the start, committed or not, one
  of the repository's inert paths, a change's records, or the archive's own writes
  (CW-pkug) (D6; CW-q7ub). Verify: library-integration tests on real Git for CW-q7ub's
  four scenarios, CW-4yhk's relock scenario, a stash, a rewritten review record, a
  ledger edited mid-file, and each check passing on an ordinary run.
- [ ] 5.3 The wrapper records the state before every unattended session and runs the
  checks after it, whatever its outcome, before any action or hook after it; a
  violation logs the run `stopped`, its reason and `invariants` naming each, the
  step's message kept ahead, as `triage_outcome` and `landed_outcome` do, and the
  after-hooks do not run; the review runner does the same for its reviewer (D6;
  CW-f9le). `log.py` accepts `invariants`. Verify: library-integration tests with the
  harness doubled for CW-f9le's scenario and a passing run's line carrying no
  `invariants`.
- [ ] 5.4 Verification point: `test_change_workflow_invariants.py`, the wrapper and
  review tests above (library integration); `run pre-commit` passes. End-to-end:
  none.

## 6. The Claude Code and Codex adapters

Delivers an internal adapter per harness — its launch with its own prompts off, its
state and protected paths, its reading of refusals and denials, the steps it can
run, its optional command rules — with the models' policy checked against it, and
its paths in a step's resolved scope (D13, D7, D2's optional rule; CW-t6mb, CW-zq4h,
CW-w3oa, CW-r6kd's settings inventory). Files: `scripts/change_workflow/harness.py`
reorganized into the adapters, `stream.py`, `steps.py`'s `Model` and `HARNESSES`
moved to the adapters, `config.py`'s models check, `scope.py`,
`scripts/tests/test_change_workflow_harness.py`, `test_change_workflow_stream.py`,
`test_change_workflow_config.py`.

- [ ] 6.1 The Claude Code adapter: its unattended command — `dontAsk` with every tool
  allowed, project settings only, its own sandbox off, the schema, the system prompt,
  a fresh session's id, and, as its optional rule, `git push` denied (D13, D2); its
  writable state `~/.claude` and `~/.claude.json`; its protected paths
  `.claude/settings.json`, `.claude/settings.local.json`, and
  `~/.claude/settings.json`; every step. Rules anchored at the checkout (`anchored`)
  go with the step table. Verify: unit tests of the command for a fresh and a resumed
  run, and of the declared paths.
- [ ] 6.2 The Codex adapter: the review's commands as today, `--sandbox read-only` kept
  inside the engine's sandbox; its writable state `~/.codex`; its protected path
  `~/.codex/config.toml`; the review only (D13). Verify: unit tests of the commands
  and paths; a library-integration test launching `codex --version` through real
  bubblewrap in the review's scope, where Codex is installed, else skipped saying so;
  if the two sandboxes cannot nest, the adapter drops `--sandbox read-only`, and the
  task's note records it.
- [ ] 6.3 Each adapter reads refusals from its run's events: Claude Code's tool results
  in its stream, Codex's command output, each matching "Read-only file system" or
  "Device or resource busy", recorded with its tool, command or path, and error;
  Claude Code's denials stay read as today (D7; CW-w3oa, CW-k5mk). Verify: unit tests
  on recorded stream fixtures for CW-w3oa's scenario, a busy protected file, a denial,
  and a tool result with neither.
- [ ] 6.4 Move `Model` and `HARNESSES` out of `steps.py` to the adapters, and check the
  configuration's models against each adapter's steps: a model only for a step its
  harness's adapter can run, refused naming the step (CW-zq4h). Verify: unit tests for
  CW-zq4h's two scenarios.
- [ ] 6.5 A step's resolved scope takes the adapter of its first model's harness, and
  `config`/`config --json` list the adapter's paths with their source (CW-o6kc).
  Verify: the library-integration test of 2.4 extended to CW-o6kc's scenario whole.
- [ ] 6.6 Verification point: the harness, stream, and config tests (unit, library
  integration); `run pre-commit` passes. End-to-end: none.

## 7. Launching every unattended run in the sandbox

Delivers the wrapper and the review runner launching through the adapters inside
the sandbox, the unconfined fallback recorded, refusals on the line from the adapter
and the sandbox's `git`, routed by the next-step computation, and the harness-neutral
unattended prompt (D3, D7, D10, D15's prompt; CW-x3pf, CW-v5ny, CW-w3oa, CW-k5mk,
CW-jqi7, CW-qu42, CW-m8wq). Files: `wrapper.py`, `review.py`, `harness.py`'s
`UNATTENDED`, `log.py`, `next_step.py`, `test_change_workflow_wrapper.py`,
`test_change_workflow_review.py`, `scripts/tests/test_change_next_step.py`.

- [ ] 7.1 The wrapper resolves the run's scope (section 2, with its adapter and
  grants), probes, and launches the adapter's command inside the sandbox; when the
  probe fails it launches unconfined, prints the warning, and records `unconfined:
  true` on the line; it reads each step's skill and `resume_from` from the engine's
  definitions (1.2), no longer the step table (D3, D10; CW-x3pf, CW-v5ny). The review
  runner does the same for Codex and its Claude fallback in the review's scope.
  Verify: library-integration tests through real bubblewrap with the harness doubled
  by a program that writes inside and outside its scope: the outside write fails and
  the line names the refusal; a review's doubled reviewer cannot write the files it
  reviews but records its invocations (CW-m8wq's review scenarios); with the probe
  doubled to fail, the run is unconfined and its line says so (CW-v5ny's scenario).
- [ ] 7.2 The line's `refusals` gather the adapter's (6.3) and each push the sandbox's
  `git` refused (4.1), taken from the session's invocations, whatever the harness
  (D7; CW-w3oa, CW-j4cs's refused-push scenario); `denials` stay the harness's.
  Verify: library-integration tests for CW-j4cs's "A refused push reaches the run's
  record" and CW-k5mk's "A step's message omits a refusal".
- [ ] 7.3 The next-step computation treats a line carrying `refusals` as one carrying
  `denials`: the owner reads it before the change moves on, and a waiting outcome
  waits for that reading (CW-jqi7). Verify: library-integration tests in
  `test_change_next_step.py` for CW-jqi7's two scenarios.
- [ ] 7.4 Rewrite `UNATTENDED` as one harness-neutral paragraph: the step runs in a
  sandbox scoped to it; a write refused as a read-only file system or busy is outside
  its scope; stop naming the path if it cannot go on, else say what it did instead;
  wait on background commands with `wait`; end every turn with its outcome (D15;
  CW-4yhk, CW-b5cf). Verify: a unit test that the prompt names no rule, chain,
  "don't ask mode", or `-C`.
- [ ] 7.5 Interactive runs stay outside the sandbox and the checks: the make targets
  without `UNATTENDED=1` open the owner's harness as today, and `run before`, `run
  after`, and `record` record no state and run no check (D9; CW-g5ry). Verify: the
  fragment's interactive command line (`make -n design CHANGE=<change>`) holds no
  `bwrap`, and a library-integration test of `record` on a run that rewrote history
  records its outcome with no `invariants`.
- [ ] 7.6 Verification point: the wrapper, review, and next-step tests (library
  integration through real bubblewrap); `run pre-commit` passes. End-to-end: none.

## 8. Grants as writable paths

Delivers `--write` on `start` and `resume` and `WRITE=` on the make targets in place
of `--allow` and `ALLOW=`, recorded as `writes_granted` (D8; CW-tl5v, CW-drf6).
Files: `cli.py`, `wrapper.py`, `log.py`, `scripts/change_workflow/workflow.mk`,
`test_change_workflow_cli.py`, `test_change_workflow_wrapper.py`,
`scripts/tests/test_workflow_command.py` where it covers the fragment.

- [ ] 8.1 `start` and `resume` take `--write <path>`, parsed as 2.3, refused before
  anything launches; the wrapper adds each to the run's scope and records
  `writes_granted`; `--allow` is removed and exits 2 (D8; CW-tl5v, CW-drf6). Verify:
  library-integration tests for CW-tl5v's three scenarios and CW-drf6's protected-path
  scenario, and `--allow` refused as a usage error.
- [ ] 8.2 `workflow.mk`'s step targets take `WRITE=`, several paths separated by `;`,
  each reaching the command as its own `--write`, and drop `ALLOW=` from their
  targets and help (D8). Verify: the fragment's command lines (`make -n`) for one and
  two paths, and its help naming `WRITE`.
- [ ] 8.3 Verification point: the CLI, wrapper, and fragment tests (library
  integration); `run pre-commit` passes. End-to-end: none.

## 9. `propose`, the history copy, and the round view's refusal

Delivers the engine's creation of a prerequisite's worktree and its mount for design,
archive cleanup's history copied by the engine after its session, and the round view
refusing under the unattended marker (D5b, D5's history, D14; CW-k8dn, CW-dtpz,
CW-hak6, CW-p3vz). Files: a new `scripts/change_workflow/propose.py`, `cli.py`,
`scope.py`, `graph.py`'s `STEP_ACTIONS`, `around.py`, `round_view.py`,
`test_change_workflow_cli.py`, `test_change_workflow_scope.py`,
`test_change_workflow_around.py`, `scripts/tests/test_round_view.py`.

- [ ] 9.1 Add `propose <change> <prerequisite>`: the worktree
  `../<prerequisite>-proposal` on a new branch `propose-<prerequisite>` from the
  change's landing branch (`find --json`'s `base`) as its remote holds it, `--no-track`,
  refusing one that exists, at the provisional tier (D5b; CW-k8dn). Verify:
  library-integration tests on real Git: the worktree on its branch with no upstream,
  and a second run refused.
- [ ] 9.2 A design run's scope adds, writable, every worktree registered in its
  checkout's `.git/worktrees/` whose path matches `../*-proposal` (D5b; CW-k8dn).
  Verify: a unit test resolving design's scope with one registered and one unrelated
  worktree; a library-integration test through real bubblewrap that the doubled
  design writes the proposal there.
- [ ] 9.3 Add the history copy to `STEP_ACTIONS` after archive cleanup, run once its
  session finishes and before its outcome is logged, writing outside the sandbox
  (D5; CW-hak6). Verify: library-integration tests with the harness doubled for
  CW-hak6's scenario and the copy's line in `invoked`.
- [ ] 9.4 `round-view` and `round-done` refuse while `CHANGE_WORKFLOW_UNATTENDED` is
  set, naming the step, and move nothing (D14; CW-p3vz). Verify: a library-integration
  test in `test_round_view.py` for CW-p3vz's scenario.
- [ ] 9.5 Verification point: the tests above (unit, library integration through real
  bubblewrap); `run pre-commit` passes. End-to-end: none.

## 10. The skills

Delivers every workflow skill free of the step table's rules and the exemptions this
change owns, with design's prerequisite through `propose`, archive cleanup without
`history`, and the orchestrating session reading refusals and relaying unconfined
runs (D15, D5b, D7, D8, D10, D14; CW-n8tr, CW-dtpz, CW-svng, CW-5rmh, CW-vdqj,
CW-v5ny). Files: `.agents/skills/*/SKILL.md`,
`openspec/specs/market-change-workflow/README.md`'s "What the workflow's skills name
of this repository" (the assumptions test reads it),
`scripts/tests/test_change_workflow_assumptions.py`.

- [ ] 10.1 Replace each step skill's "Running unattended" denial paragraphs — one
  command per call, the write-steering exception, "don't ask mode", never `git -C` or
  `make -C`, commands in the forms the rules name, a helper carrying those rules —
  with the paragraph `UNATTENDED` gives (7.4), keeping each skill's other unattended
  bullets (D15). `change-implement` names a project's tests and bring-up by role, no
  `make -C <package>` form or `docker compose -p` form remaining. Verify: a search of
  `.agents/skills/` finds no "don't ask mode", "write-steering", "step table", or
  `make -C <package>`; `make check-agent-skills` passes.
- [ ] 10.2 `change-plan` and `change-implement` give an edit of the harness's settings
  to the orchestrator because no step writes them (the adapter's protected paths), and
  an edit of the workflow's configuration because no step writes it, never naming
  `.claude/`; `change-triage` likewise (D15). Remove the exemption rows this change
  owns from `market-change-workflow/README.md`'s "What the workflow's skills name of
  this repository" (CW-n8tr). Verify: `test_change_workflow_assumptions.py` passes,
  its exemption test finding no row owned by this change.
- [ ] 10.3 `change-design`'s "When the design needs another change first": the design
  ends with a question naming the prerequisite; once the orchestrating session ran
  `propose` on the owner's word, the resumed session writes and checks the proposal
  in the worktree and ends blocked (D5b; CW-dtpz). `change-archive-cleanup` no longer
  runs `history`: the engine copies after its session, and its report names the
  copy's result from the line (CW-hak6). Verify: a reading of both sections against
  CW-dtpz's and CW-hak6's scenarios; `make check-agent-skills` passes.
- [ ] 10.4 `change-orchestrate`: refusals and denials read from the line and classified
  as a finding or a gap (CW-svng), a finding's run checked for a workaround
  (CW-5rmh), a gap answered with the narrowest path from `config --json`'s scope as a
  `--write` grant or a `[sandbox]` edit (CW-vdqj), `unconfined: true` relayed to the
  owner (CW-v5ny), `propose` run on the owner's word (CW-k8dn), and a violation's
  `invariants` relayed (CW-f9le); the classification by deny rules, write-steering,
  and the step table's rules removed (D7, D8, D10, D14). Verify: a reading against
  those requirements; a search finds no `change-steps.toml` or `ALLOW=`.
- [ ] 10.5 Verification point: `make check-agent-skills` and
  `test_change_workflow_assumptions.py`; `run pre-commit` passes. End-to-end: none.

## 11. This repository's `[sandbox]`, and the step table removed

Delivers this repository's `[sandbox]` declaration, the step table and its loader
removed, the roles test reading only the make fragment, and every comment naming the
table rewritten (D11, D12, D14; MCW-s4bx, MCW-5tgp, CW-m4ps, CW-z5me). Files:
`.agents/workflow.toml`, `.claude/change-steps.toml`, `scripts/change_workflow/steps.py`,
`__init__.py`, `common.py`, `config.py`, `cli.py`, `workflow.mk`, `scripts/ci_evidence.py`,
`scripts/tests/test_change_workflow_steps.py`, `test_change_workflow_assumptions.py`,
`test_change_workflow_cli.py`, `test_change_workflow_harness.py`,
`test_change_workflow_review.py`, `test_change_workflow_wrapper.py`,
`openspec/specs/market-change-workflow/README.md`'s "The engine's own assumptions" and
"How this repository provides the workflow's roles" (the assumptions test reads
them).

- [ ] 11.1 Declare `.agents/workflow.toml`'s `[sandbox]`: `writable.common =
  ["~/.local/share/uv", "~/.kube/cache", "~/.config/gcloud", "~/.docker"]`,
  `writable.design = ["docs/"]`, `writable.plan = ["docs/"]`, `protected = []`, each
  with its comment naming who uses it (D12; MCW-s4bx). The configuration is denied to
  every step while the step table holds: this task is the orchestrator's, made on the
  owner's word before the section's session starts, and the session commits it.
  Verify: `config --json` lists design's `docs/` from the repository, and
  `test_the_repositorys_own_configuration_passes_its_check` passes, with a unit test
  for MCW-s4bx's two scenarios against the resolved scopes.
- [ ] 11.2 Remove `.claude/change-steps.toml` (D11). Every step is denied edits under
  `.claude/`: this task is the orchestrator's, on the owner's word before the
  section's session starts, and the session commits it with the section. Verify:
  the file is gone, and nothing under `scripts/` reads it.
- [ ] 11.3 Remove `steps.py` and `test_change_workflow_steps.py`, moving each test
  still meaningful — every step has a skill, the review writes nothing it reviews, no
  step's scope holds the configuration — onto the engine's definitions and scopes in
  `test_change_workflow_graph.py` and `test_change_workflow_scope.py`; drop
  `steps.STEP_TABLE` and the wrapper's and review's `steps_path` (D11; CW-z5me).
  Verify: the moved tests pass, and a search of `scripts/` finds no `load_steps`,
  `StepRules`, or `STEP_TABLE`.
- [ ] 11.4 The roles test reads the make fragment and the configuration only, no step
  table (CW-m4ps, MCW-5tgp); `market-change-workflow/README.md`'s "The engine's own
  assumptions" drops the step table's row and names `bwrap` among the tools, and "How
  this repository provides the workflow's roles" gives the tests-and-environments
  role through the hooks and `[sandbox]` rather than the step table's grants. Verify:
  `test_change_workflow_assumptions.py` passes.
- [ ] 11.5 Rewrite every comment and docstring naming the step table or its rules to
  describe the current system — `__init__.py`, `common.py`, `config.py`, `cli.py`,
  `workflow.mk`, `scripts/ci_evidence.py`, and any section 1 to 10 left (a repository
  obligation, `docs/guidance/engineering/comments.md#comments-describe-the-current-system`).
  Verify: a search of `scripts/` finds no "step table" or `change-steps`; `make
  check-comment-hygiene` passes.
- [ ] 11.6 Verification point: the whole scripts suite and `make check-agent-skills`;
  `run pre-commit` passes. End-to-end: none.

## 12. Closeout

The workflow's closeout parts (`docs/guidance/workflow/closeout.md`), in order, with
this repository's own parts (`openspec/README.md#this-repositorys-closeout-parts`) at
its seventh position.

- [ ] 12.1 Comment hygiene — run `make check-comment-hygiene` and read the comments and
  docstrings the change added under `scripts/` for history wording or a change
  reference; anything to rewrite returns the change to implementation.
- [ ] 12.2 Import placement — check the imports the change added in `scope.py`,
  `sandbox.py`, `sandbox-git`, `invariants.py`, `propose.py`, and the edited modules;
  one to move returns the change to implementation.
- [ ] 12.3 Documentation compliance — check D1 to D16 and the cadence against
  `docs/guidance/workflow/openspec-documentation.md` and
  `openspec/README.md#documentation-placement`, and each permanent document written
  for the current state, with no wording relative to the change.
- [ ] 12.4 Narrative compression — shorten sections 1 to 11's notes to final behaviour,
  evidence, deferrals, and destinations, moving rationale into `design.md` first.
- [ ] 12.5 Roadmap currency — record that no goal of `docs/development/ROADMAP.md` is
  affected: the change serves the lesser goal "Make the change workflow a tool any
  repository can adopt" in `openspec/changes/README.md`.
- [ ] 12.6 Campaign index currency — in `openspec/changes/README.md`: the change's row
  (status and notes); the lesser goal's "Current state", its paragraph on the step
  table's allowlist and its sentence on the exemptions this change owns rewritten for
  the sandbox; the gap "Unattended permissions are allowlists of this repository's
  commands" removed as closed. Leave dependents' `Depends on` for archive cleanup. Run
  `make check-change-index`.
- [ ] 12.7 Packaging — `scripts/change-workflow run pre-archive
  sandbox-unattended-workflow-steps` (`make check-packaging`, `make
  check-architecture-change`), and `make check-agent-skills`, since the change
  touched `.agents/` and `.claude/`.
- [ ] 12.8 End-to-end pipeline — record the run the latest passing validation names,
  its result, the commit it describes, and that no scenario exercises the workflow's
  tooling.
- [ ] 12.9 Promotion — write, beside the deltas the archive merges into
  `openspec/specs/change-workflow/spec.md` and `market-change-workflow/spec.md`:
  - `openspec/specs/change-workflow/index.md`: the entries 1.1 added, their summary
    lines checked against the requirements as implemented; summary lines revised for
    CW-qu42, CW-4yhk, CW-k5mk, CW-svng, CW-5rmh, CW-vdqj, CW-jqi7, CW-drf6, CW-tl5v,
    CW-b5cf, CW-z5me, CW-zq4h, CW-hak6, CW-dtpz, CW-o6kc, CW-59c7, CW-m4ps; the
    retired ids' notes checked; "### Permissions" renamed only if no citation names
    it.
  - `openspec/specs/market-change-workflow/index.md`: MCW-s4bx's entry checked, and
    MCW-5tgp's summary revised.
  - `openspec/specs/change-workflow/README.md`: "Restrictions bind unattended runs
    only" rewritten — P1, P2, P3, P5, P7, P8 as its threat model and boundaries, the
    sandbox (D3, D4), each step's scope and the protected paths (D5, D5a, D5c),
    refusals (D7), grants (D8), the unconfined fallback (D10), adapters (D13), what
    survives of the deny rules and the hook table (D14), and the two retired limits'
    content, the forgeable marker and open reads; "Pushing is guarded, never repaired"
    (D2); "Its parts" (the scope, sandbox, sandbox `git`, invariants, adapters, and
    `propose` modules; D11); "A step run's life" (the probe, the recorded state, the
    seven checks; D6); "Interactive runs record their own outcome" (D9); "Models are
    policy, with no same-vendor fallback" (D13, P6); "A prerequisite is proposed apart
    and halts its dependent" (D5b); "Validation observes a committed slice" (D5c);
    "History lives in the owner's workspace" (the engine's copy); "A repository's
    configuration" (D12); "The command and its tiers" (`propose`, `--write`); "A
    change's records carry one format version" (P9, D16); "The engine's own
    assumptions" (the step table's row removed, `bwrap` and the sandbox `git` added);
    "Current limits" — the unchecked configuration and the step table's place removed
    as closed, the forgeable marker and Read reaching any file removed as retired.
  - `openspec/specs/market-change-workflow/README.md`: "Current limits" (the container
    per change's trigger "when unattended steps are to be sandboxed from the owner's
    files" revised to the sandbox as built), checking the sections 10.2 and 11.4
    wrote.
  - `docs/change-workflow-handbook.md`: "Interventions" (grants as `WRITE=` and
    `--write`, refusals, unconfined runs, `propose`), "The engine" and "Customization"
    (the step table gone, `[sandbox]`).
  - The design-promotion record in `design.md`, a row for each of D1 to D16, D5a,
    D5b, and D5c, and the cadence's "no permanent destination" with its reason, as
    the proposal's "Knowledge to promote" gives them.
  Run `make check-spec-index CHANGE=sandbox-unattended-workflow-steps`.
- [ ] 12.10 Guidance placement — confirm no file under `docs/guidance/` changed, or
  check each that did against the layer test; then `make check-guidance`.
- [ ] 12.11 Documentation citations — `make check-doc-citations
  CHANGE=sandbox-unattended-workflow-steps`, resolving every match; then
  `scripts/change-workflow openspec validate sandbox-unattended-workflow-steps
  --strict`.
- [ ] 12.12 Archival — `scripts/change-workflow openspec archive
  sandbox-unattended-workflow-steps -y`, merging the deltas (no `--skip-specs`: no
  permanent `spec.md` was edited by hand); read each merged requirement once; point
  the row at the archive; `scripts/change-workflow run pre-commit
  sandbox-unattended-workflow-steps`.
