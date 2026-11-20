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
  profile, baseline, `resume_from`); the profiles are `READ_ONLY` and `WRITING`, the
  plan's "workspace" renamed since the workflow's "workspace" is the owner's. Two
  baseline entries are named by role, `INERT_PATHS` (closeout's) and `TEMPORARY`; the
  review's invocation path is built from `running.INVOCATIONS`. Unit tests in
  `test_change_workflow_graph.py` pass: one definition per step; skills and
  `resume_from` equal `load_steps()`'s; the review's checkout paths only
  `.git/change-invocations/`; every step writes the temporary directory; each writing
  step's baseline and `~/.cache`.
- [x] 1.3 Verification point: `test_change_workflow_graph.py` (unit) and `make
  check-spec-index CHANGE=sandbox-unattended-workflow-steps`; `scripts/change-workflow
  run pre-commit sandbox-unattended-workflow-steps` passes.
  End-to-end: none — no scenario exercises the workflow's tooling.
  Done:
  - `make test-release-tooling TESTS=scripts/tests/test_change_workflow_graph.py`
    (unit) and `make check-spec-index` pass. `run pre-commit`'s functional hooks pass
    (the relock, packaging, every suite of `make validate-local`, 3383 scripts
    tests); its `pre-commit` fails only `check-doc-citations`, on the eight files
    this plan cites that sections 2 to 5 and 9 create, until the last exists.
  - Outside the plan: `test_change_workflow_assumptions.py`'s `configured` now reads
    `openspec.command`, since the maintenance commit before this branch let every
    step run `scripts/openspec validate`.
  - Not fixed: in two of three runs the relock (`make lock`, the
    `after-functional-change` hook) rewrote `kit/capability-admissibility/uv.lock`
    and `kit/capability-pricing/uv.lock`, each resolving
    `arkhai-kit-capability-shape` 0.3.0 from PyPI rather than `.dist`, against
    `docs/guidance/repository/wheelhouse.md`'s internal-package rule. The third
    run's relock left both as committed, so the section commits neither.
  - Limit: run `run pre-commit` alone. A second one in the same checkout clears
    `.dist` under the first, whose kit tests then fail to resolve.

## 2. `[sandbox]` and a step's resolved scope

Delivers the configuration's `[sandbox]` table and its check, the resolution of a
step's scope from the engine's baseline, an adapter's paths, the repository's
additions, and grants, and its listing in `config` (D12, D8's path rules, D5a, D4's
protected ancestors; CW-h2zt, CW-o6kc, CW-m8wq, CW-r6kd's protected set). Files:
`scripts/change_workflow/config.py`, a new `scripts/change_workflow/scope.py`,
`cli.py`'s `config`, `scripts/tests/test_change_workflow_config.py`, a new
`scripts/tests/test_change_workflow_scope.py`.

- [x] 2.1 In `config.py`, read `[sandbox]`: `writable.common`, `writable.<step>` for a
  step of `graph.STEPS`, and `protected`, each a list of paths; refuse, naming the
  field, an unknown key, a wrong type, `writable.review`, an unknown step, a glob
  character outside a path's pattern form, and a writable entry that is or lies under
  a protected path — the engine's (`.agents/workflow.toml`, `.git/config`, the
  engine's `git`) or the configuration's own — while admitting a directory that
  contains one (D12; CW-h2zt, CW-w8ne). An absent table is every list empty. Verify:
  unit tests for each refusal, each naming the field, and for CW-h2zt's three
  scenarios.
  Done: `Configuration` gains `sandbox_writable`, `sandbox_protected`,
  `repository_writable(step)` (`common` but for the review, then the step's own), and
  `scope(step, root, …)`; `check()` takes a `home` seam. "A glob character outside a
  path's pattern form" is read as two refusals: a pattern in a `~` or absolute entry,
  since patterns match the checkout's files, and any pattern in `protected`, which is
  mounted whole. The protected test is `scope.protected_by`, shared with grants.
  Tests in `test_change_workflow_config.py` pass: unit tests of each refusal naming
  its field; CW-h2zt's scenario 2 through `cli.main` (`check config`, `config`,
  `config --json`, `config load design` each exit 1 naming the field and path);
  scenarios 1 and 3 as library integration on a real Git checkout (the resolved scope
  only). `scripts/change-workflow run test-before … --test
  scripts/tests/test_change_workflow_config.py` at the round's base: the 18 new tests
  fail there and the 122 others pass.
- [x] 2.2 In `scope.py`, resolve a step's scope for one run as absolute paths: the
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
  Done: `scope.resolve(step, root, *, inert_paths, writable, protected,
  adapter_writable, adapter_protected, grants, home, temporary)` returns a `Scope` of
  `ScopedPath`s (path, source, entry, `create`). `PROTECTED`, the engine's set, is
  `.agents/workflow.toml`, `.git/config`, `/usr/bin/git`, and `/usr/lib/git-core/git`.
  `.git/` resolves through `git rev-parse`, `.git/<x>` through `--git-path`; patterns
  match what `git ls-files --cached --others --exclude-standard` lists, through
  `records.inert` beside a public `records.is_pattern`; every absent writable path is
  marked `create`. Outside a Git checkout `.git/` entries read lexically and patterns
  match nothing; Git that cannot run raises `ScopeError`. Tests in
  `test_change_workflow_scope.py`, library integration on a real Git checkout (the
  plan said unit), pass: design with the repository's `docs/`; the review's two
  paths; closeout's README directories and the root from `AGENTS.md`;
  `.agents/workflow.toml` protected inside a writable checkout; the adapter's and
  repository's sources; a linked worktree's Git paths. `absolute` is a unit test.
- [x] 2.3 Grant parsing as `scope.py` takes it (D8; CW-tl5v): each value split on `;`,
  parts trimmed, empties dropped; a value with a glob character refused, naming it; a
  path that is or lies under a protected path refused, naming it; a directory
  containing one admitted, the protected path read-only inside; a file mounting its
  directory; an absent path marked to be created as a directory before launch. The
  command line takes it in section 8. Verify: unit tests for CW-tl5v's pattern
  scenario, a protected path, a protected ancestor, a file, and an absent path.
  Done: `grant_paths` splits values; `granted`, called by `resolve`, refuses a pattern
  or a protected path (the engine's, the adapter's, the repository's), naming the
  value. `grant_paths` is a unit test; the rest are library integration through
  `resolve` on a real Git checkout (the plan said unit), passing: CW-tl5v's pattern
  scenario (refused, naming the value), a protected and an adapter's protected path, a
  protected ancestor with the file inside, a file mounting its directory, an absent
  path marked `create`, and `.git/config` refused in a linked worktree.
- [x] 2.4 `config` and `config --json` list each step's resolved scope — writable and
  protected paths, each with its source — the adapter's paths absent until section 6
  adds them (CW-o6kc). Verify: a library-integration test of `config --json` on a
  fixture repository declaring `writable.plan = ["docs/"]` finding planning's
  `openspec/` and `.git/` from the engine and `docs/` from the repository (CW-o6kc's
  scenario, but for the adapter's paths, which 6.5 adds).
  Done: `config --json` gains `scopes` per step, `writable` and `protected` lists of
  `{path, source, entry}` with `absent` where marked; `config` appends
  `scope.<step>.<writable|protected>` lines; `resolution` lists
  `sandbox.writable.<key>` and `sandbox.protected`; `cli.py`'s help and docstring say
  so. `test_config_lists_each_steps_scope_with_each_paths_source`, library
  integration through `cli.main`, passes.
- [x] 2.5 Verification point: `test_change_workflow_scope.py` and
  `test_change_workflow_config.py` (unit, library integration); `run pre-commit`
  passes. End-to-end: none.
  Done:
  - `make test-release-tooling` on the scope, config, and CLI tests: 328 passed;
    `make check-comment-hygiene` passes.
  - `run pre-commit`: its functional hooks pass; its `pre-commit` fails only
    `check-doc-citations`, on the six files sections 3 to 5 and 9 create. One earlier
    run failed a VM storefront test this section does not reach,
    `test_delivery_recovery_loop.py::test_a_deal_waiting_for_its_start_is_claimed_re_checked_and_driven_at_its_start`;
    it passed in the next run.
  - The fresh-context check's fixes are in the section's commit.

## 3. The bubblewrap launcher, its probe, and the unconfined fallback

Delivers the engine's sandbox: a resolved scope rendered as a `bwrap` command around
any program, protected paths created when absent, the probe, and what the wrapper is
told when the sandbox cannot run (D3, D4, D10, D5b's mount; CW-x3pf, CW-r6kd,
CW-m8wq, CW-v5ny). Files: a new `scripts/change_workflow/sandbox.py`, a new
`scripts/tests/test_change_workflow_sandbox.py`.

- [x] 3.1 `sandbox.py` renders a scope as `bwrap` arguments: the root filesystem
  read-only, `/dev` and `/proc`, the temporary directory, each writable path
  `--bind` over it, each protected path `--ro-bind` after them, any further read-only
  file binds a caller adds (section 4 adds the engine's `git`), the network and
  environment shared, `--die-with-parent`, then the program and its arguments (D4;
  CW-x3pf). A protected path absent at launch is created first — `{}` for a `.json`
  file, an empty file otherwise — and bound like any other; a granted path absent at
  launch is created as a directory (D4, D8; CW-r6kd). Verify: unit tests of the
  rendered arguments' order for a design scope, and of the creation of an absent
  `.claude/settings.local.json` as `{}`.
  Done: `sandbox.arguments(scope, program, …)` renders `bwrap --unshare-pid --ro-bind
  / / --dev /dev --proc /proc`, each writable path `--bind` (shallower first, so none
  hides one inside it), each protected path `--ro-bind`, then `--die-with-parent --`
  and the program. `prepare(scope)` creates absent writable paths as directories and
  absent protected paths as `{}` for `.json`, an empty file otherwise, or a directory
  for an entry ending in `/`. Two departures from the task's wording:
  - Only protected paths inside a writable path are mounted and created
    (`mounted_protected`): one outside every writable path is read-only under the
    root already, so the review creates no placeholder in a checkout it cannot write.
  - `--unshare-pid` is added to D4's flags, so bubblewrap's death ends every process
    the harness started (CW-x3pf).
  Unit tests on hand-built scopes pass: the order for a design scope, the
  configuration mounted after the checkout, each empty form, and no placeholder
  outside the writable paths.
- [x] 3.2 The probe: one trivial program run under `bwrap` before a launch, its
  failure — `bwrap` missing, user namespaces refused — returning the reason, and the
  launch then the program unconfined, with the reason for the wrapper's warning and
  `unconfined: true` (section 7 records it) (D10; CW-v5ny). Verify: unit tests with
  the probe doubled for both failures; a library-integration test that the real probe
  passes on this machine.
  Done: `probe(run)` runs `true` in the base sandbox, its failure returning the
  reason (not installed, bwrap's own message, another `OSError`, an exit with no
  message). `launch(scope, program, …, probing)` returns a `Launch` of the bwrap
  command, its mounts created, or, where the probe fails, the program alone with
  `unconfined` holding the reason, creating nothing. Unit tests with the probe doubled
  pass. A test of the real probe was dropped as unable to fail (it was skipped exactly
  when the probe fails); 3.3's tests running unskipped (`PYTEST_ARGS=-rs`) are the
  evidence the real probe passes here.
- [x] 3.3 Library-integration tests through real bubblewrap, a shell program standing
  in for the harness: a write inside the scope succeeds; a write outside it fails as a
  read-only file system; a write to a protected file fails, and a rename over it fails
  busy (CW-r6kd's `git config core.hooksPath` scenario, on a real repository); an
  absent settings file cannot be created (CW-r6kd's scenario); the Docker socket's
  path, where present, stays connectable (D4); the sandboxed program is killed when
  its parent dies (`--die-with-parent`); and the program reads a file outside its
  scope (P3; CW-x3pf's reads). Verify: these tests pass here, each skipped elsewhere
  with the probe's reason.
  Done: these launch real external processes (bwrap, sh, git), so they are
  external-process integration (`test-levels.md`), not library integration; each runs
  a shell program in a scope resolved on a real Git checkout. All pass here, none
  skipped: a write inside design's scope succeeds and one outside fails "Read-only
  file system"; a write to `.agents/workflow.toml` fails read-only and a rename over
  it "Device or resource busy"; CW-r6kd's `git config core.hooksPath` fails busy,
  `.git/config` unchanged; CW-r6kd's absent `.claude/settings.local.json` cannot be
  written and stays `{}`; a file outside the review's scope is read; the Docker socket
  answers `GET /_ping` with `OK`; once the launcher is killed every process inside
  dies, a background `sleep` included (without `--unshare-pid` the test failed). The
  gate failing these on a skip came in the round's triage (11a, 62 F2).
- [x] 3.4 Verification point: `test_change_workflow_sandbox.py` (unit, library
  integration through real bubblewrap); `run pre-commit` passes. The note records
  whether a native Ubuntu install was at hand to run the probe on; where none was,
  `design.md`'s open question on AppArmor stays open. End-to-end: none.
  Done:
  - `make test-release-tooling` on the sandbox and scope tests: 43 passed, none
    skipped. `run pre-commit`: its functional hooks pass, the bubblewrap tests run;
    its `pre-commit` fails only `check-doc-citations`, on the four files sections 4,
    5, and 9 create.
  - No native Ubuntu install was at hand, only this WSL2 machine, so `design.md`'s
    open question on AppArmor stays open.
  - The fresh-context check's fixes are in the section's commit. The gaps it named
    outside P1 — a renamed directory holding a protected mount, a symlinked protected
    settings file, `protected = ["~"]` — are D19's limits and D20.

## 4. The sandbox's `git`, the guarded push's record, and the upstream after a run

Delivers the engine's `git` bound over the system's two, refusing any push but the
guarded push's under a run and recording each refusal; the guarded push recording
each push's result and setting no upstream under a run; and the engine setting a
missing upstream after the session (D2; CW-j4cs, CW-59c7, CW-w3oa's pushes). Files:
a new executable `scripts/change_workflow/sandbox-git`, `sandbox.py`, `push.py`,
`running.py`, `wrapper.py`, `scripts/tests/test_change_workflow_sandbox.py`, a new
`scripts/tests/test_change_workflow_sandbox_git.py`, `scripts/tests/test_check_push_ready.py`
where it covers `push.py`.

- [x] 4.1 Write `sandbox-git`: while `CHANGE_WORKFLOW_UNATTENDED` is set and the
  guarded push's marker is not, it refuses a `push` subcommand wherever it stands
  among Git's options — `--no-verify`, `-c core.hooksPath=…`, `-C <dir>` among them —
  printing why and exiting non-zero, and records the refusal, with its command line,
  among the session's invocations (`running.keep_invocations`); otherwise it executes
  the real Git at the path the sandbox binds it to (D2; CW-j4cs). Verify: unit tests
  of the decision for each option form, a non-push command, the marker unset, and the
  guarded marker set.
  Done, as a module rather than an executable file, `change_workflow/sandbox_git.py`:
  a program mounted at `/usr/bin/git` cannot find the engine's package by its own
  path, and a new file's mode could not be set in this session. `sandbox.py` mounts a
  generated shell program over Git (4.2) that runs `sandbox_git.main` with the
  engine's Python, `-I`, from the engine's directory, passing `$0`.
  - `subcommand` reads past Git's own options, `_VALUED` naming those taking a
    separate value; a dashed name such as `git-receive-pack` gives its subcommand.
  - `refusal` refuses a push under `UNATTENDED_RUN` without `common.GUARDED_PUSH`
    (`CHANGE_WORKFLOW_GUARDED_PUSH`).
  - `main` keeps a refusal as `{"hook": running.REFUSED_PUSH, "command", "error",
    "started"}`, else `execv`s `REAL_GIT` under the name it was run by, since Git's
    local transport runs `git-receive-pack` through it.
  Unit tests in `test_change_workflow_sandbox_git.py` pass: nine option forms refused,
  five other commands run (`-C push status` among them), dashed names, the marker
  unset and the guarded marker set; the refusal kept, on a real Git checkout.
- [x] 4.2 `sandbox.py` binds the real `/usr/bin/git` at a path only `sandbox-git`
  names, then `sandbox-git` read-only over `/usr/bin/git` and `/usr/lib/git-core/git`
  (Git's exec path), both protected (D2, D4; CW-r6kd). Verify: library-integration
  tests through real bubblewrap on a repository with a bare remote: `git push`, `git
  push --no-verify`, `git -c core.hooksPath=/dev/null push`, and
  `/usr/lib/git-core/git push` are refused and nothing reaches the remote; `git
  status` and `git commit` work (CW-j4cs's scenarios).
  Done: `arguments(scope, program, *, git)` renders, after the protected mounts,
  `--ro-bind /usr/bin/git /dev/change-workflow-git` (`sandbox_git.REAL_GIT`), then
  `--perms 0755 --ro-bind-data <fd>` over each of `scope.GIT_EXECUTABLES`; `/dev`
  because bubblewrap cannot make a mount point on the read-only root, and the
  sandbox's `/dev` is a fresh tmpfs. `launch` writes `git_program()` into one `memfd`
  per mount (`Launch.fds`, closed by `Launch` as a context manager); section 3's
  `binds` parameter was removed. Limit, outside P1: the module the mounted program runs
  is read from the engine's directory at each call, so where the engine runs from the
  change's own checkout a step writing that checkout can change what its `git`
  refuses; no protected path covers the engine's package. External-process
  integration tests on a real repository with a bare `origin` the scope makes
  writable pass, none skipped: CW-j4cs's four pushes each exit 1 naming the refusal,
  `dev` on the remote unchanged, the refusal kept with its command line; `git commit`
  and `git status` work.
- [x] 4.3 `push.py` sets the guarded push's marker in the environment of the `git push`
  it runs, so `sandbox-git` lets it through, and, under a run, records each attempted
  push once Git returns — branch, remote, commit sent, Git's exit status — among the
  session's invocations; under a run it never passes `--set-upstream` (D2; CW-59c7).
  Outside a run nothing changes. Verify: library-integration tests: the guarded push
  through real bubblewrap reaches a bare remote and its record names the commit and
  status 0; a push Git fails after the pre-push hook passed is recorded with its
  failing status (CW-59c7's "An unattended push fails"); outside a run the owner's
  push sets its upstream as today.
  Done: `git push` always runs with `GUARDED_PUSH=1`, which matters only inside the
  sandbox. Under `UNATTENDED_RUN` the target's `set_upstream` is dropped, `check`
  says the engine sets the upstream, and each push is kept as `{"hook":
  running.ATTEMPTED_PUSH, "command", "branch", "remote", "commit", "exit_status",
  "started", "seconds"}`. Tests pass: in `test_change_workflow_sandbox_git.py`,
  external-process, the guarded push inside bwrap reaches the bare remote, kept with
  `HEAD` and status 0; in `test_check_push_ready.py`, library integration through
  `push.main`, an unattended push sets no upstream and is kept, and a non-fast-forward
  push after a passing `pre-push` is kept with Git's status, 1. The outside-a-run
  tests pass unchanged.
- [x] 4.4 After a session ends, before its line is written, the wrapper sets the
  branch's upstream outside the sandbox to the remote of the run's last successful
  guarded push of that branch, as its record names it, and sets none where no push of
  it succeeded (D2; CW-59c7's "An unattended run pushes a branch with no upstream").
  Verify: library-integration tests with the harness doubled pushing a branch with no
  upstream, and failing to.
  Done: `push.set_upstreams(root, invoked)` gives each branch with neither
  `branch.<b>.remote` nor `.merge` its own name on its last successful push's remote;
  `Wrapper._logged_turn` calls it before `record_outcome`, a failure printed and
  stopping no line. Library-integration tests in `test_check_push_ready.py` pass, two
  through the wrapper with a doubled harness running `push --remote origin`: a design
  run's push leaves `origin/feat/change` as upstream; a rejected push leaves none; and
  a branch already tracking keeps its upstream. No test drives `check`'s new message,
  or a failure to set an upstream.
- [x] 4.5 Verification point: `test_change_workflow_sandbox_git.py` (unit, library
  integration through real bubblewrap), the push and wrapper tests above; `run
  pre-commit` passes. End-to-end: none.
  Done:
  - `make test-release-tooling` on the sandbox `git`, sandbox, push, wrapper, and
    scope tests: 196 passed, none skipped (`PYTEST_ARGS=-rs`).
  - `run pre-commit`: its functional hooks pass, the relock leaving the locks as
    committed; its `pre-commit` fails only `check-doc-citations`, on the three files
    sections 5 and 9 create. A first run failed "tree after" because this session
    edited the worktree while the suites ran; the untouched rerun passed.
  - The fresh-context check's fixes are in the section's commit. Declined: its
    reading that the push and wrapper comments describe a sandbox no step yet
    launches in, since the branch lands whole.
  - Not measured: every Git call inside the sandbox now starts a Python process
    first. The routes around the engine's `git` the check named are D2's.

## 5. The seven checks after every run

Delivers the state recorded as a session starts, the seven checks after it, and the
stopped outcome a violation logs, wired into the wrapper and the review so every run
after this section is checked, confined or not (D6, D5c; CW-q7ub, CW-f9le,
CW-4yhk's relock scenario). Files: a new `scripts/change_workflow/invariants.py`,
`wrapper.py`, `review.py`, `log.py`, a new `scripts/tests/test_change_workflow_invariants.py`,
`scripts/tests/test_change_workflow_wrapper.py`, `test_change_workflow_review.py`.

- [x] 5.1 `invariants.py` records at a session's start the commit, the branch, the
  workflow log's and the ledger's lengths and the hash of their contents up to them,
  each review record's hash, `refs/stash`, and the remote's change branch and
  protected branches (D6). Verify: unit tests of the recorded state on a fixture
  repository.
  Done: `invariants.record(root, step, change, *, inert_paths, protected_branches)`
  returns a `Start`: the commit and branch; the worktree as a tree object
  (`worktree_tree`, `git add --all` and `write-tree` through a copy of the index under
  `GIT_INDEX_FILE`, so the checkout's index is untouched) and the tracked paths; the
  log's and the ledger's (`interventions.jsonl`) `Prefix`, a length and a SHA-256;
  each `records.RECORD` file's digest; `refs/stash`; how many entries `HEAD`'s reflog
  holds; each remote's change and protected branches from one `ls-remote`; the delta
  capabilities, inert paths and protected branches. Library-integration tests (the
  plan said unit) on a real checkout with a bare `origin` pass:
  `test_the_state_a_session_starts_from_is_recorded` and
  `test_reading_the_worktree_as_a_tree_leaves_the_checkouts_index_alone`.
- [x] 5.2 The checks against it after the session: (1) `HEAD` on the change's branch
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
  Done: `invariants.check(root, start, invoked)` returns a `Violation(check, found)`
  per failure, the checks named `history`, `unchanged`, `log`, `records`, `stash`,
  `remote`, and `closeout`.
  - Checks 2 and 7 diff the start tree against the end's (`--no-renames`), committed
    or not.
  - Check 6 departs from the task's "after one fetch": it lists every remote with
    `ls-remote` at the start and after, writing nothing, and skips one unreadable at
    either end, so a run's commit another party has since built on is missed (D6). A
    protected branch's new tip is the run's when `HEAD`'s reflog gained it during the
    run.
  - Check 7 admits `records.inert`, `records.is_record`, and `archive_writes`: the
    change's directory, active or archived, `openspec/changes/README.md`, and each
    delta capability's `openspec/specs/<capability>/spec.md`.
  Library-integration tests in `test_change_workflow_invariants.py` pass (22 with
  5.1's two and the outcome's unit test): CW-q7ub's four scenarios; a push from a
  deleted branch; CW-4yhk's relock (`unchanged`, naming `uv.lock`) and a committing
  validation; a stash, a rewritten record, a ledger edited mid-file, a rewritten log;
  a branch switched; the change branch moved without or after a failed push; another
  party's commit fetched; an unreachable remote; closeout's own writes and the
  archive's move passing, another change's documents refused; an ordinary run passing.
- [x] 5.3 The wrapper records the state before every unattended session and runs the
  checks after it, whatever its outcome, before any action or hook after it; a
  violation logs the run `stopped`, its reason and `invariants` naming each, the
  step's message kept ahead, as `triage_outcome` and `landed_outcome` do, and the
  after-hooks do not run; the review runner does the same for its reviewer (D6;
  CW-f9le). `log.py` accepts `invariants`. Verify: library-integration tests with the
  harness doubled for CW-f9le's scenario and a passing run's line carrying no
  `invariants`.
  Done: `invariants.Invariants`, built by `Invariants.of(configuration, root, step,
  change, invocations)` for the wrapper and the review alike, holds a run's `begin()`
  and `violations(sessions)`, reading the guarded push's records through the runner's
  `invocations` seam.
  - `_logged_turn` calls `begin()` after the before-actions and checks after the
    attempts, whatever the outcome, before `_after_finished`, which checks again after
    a session resumed for a failed after-hook.
  - A violation makes `invariants.stopped(outcome, broken)` the outcome, the step's
    message ahead, and puts `invariants`, a list of `{check, found}`, on the line;
    `log.py`'s docstring names the field.
  - `run_review` takes `invariants`: a violation once the reviewer ends publishes
    nothing and raises `ReviewError`; an interrupted reviewer's record carries any.
  - After a violation the wrapper also sets no upstream (4.4), CW-f9le read as
    overriding CW-59c7's "once the session ends" (D2).
  - Outside the plan: `__init__.py`'s module list gains `scope`, `sandbox`,
    `sandbox_git`, and `invariants`.
  Library-integration tests, the harness doubled, pass: in
  `test_change_workflow_wrapper.py` CW-f9le's scenario, a passing run without
  `invariants`, a session resumed after a failed hook rewriting a record, a closeout
  editing `src.py`, a run that exited 3; in `test_check_push_ready.py` a design run
  that pushed then stashed, no upstream set; in `test_change_workflow_review.py` a
  reviewer editing a tracked file and one changing nothing. No test drives an
  interrupted reviewer that also broke an invariant.
- [x] 5.4 Verification point: `test_change_workflow_invariants.py`, the wrapper and
  review tests above (library integration); `run pre-commit` passes. End-to-end:
  none.
  Done:
  - `make test-release-tooling` on the invariants, wrapper, review, around, push,
    sandbox `git`, and CLI tests: 478 passed.
  - `run pre-commit`: its functional hooks pass; its `pre-commit` fails only
    `check-doc-citations`, on `propose.py`. A first run's `check-comment-hygiene`
    failure, on fixtures named `tasks.md` and `01-design.md`, was fixed by renaming.
  - The fresh-context check's fixes are in the section's commit. Declined: a
    detached-`HEAD` start skipping the branch checks (no step starts detached), and
    walking a protected branch's history for a commit built over (it needs the fetch
    the check does without).
  - Every run in a Git checkout lists each remote twice; offline, the remote check is
    skipped and the run goes on. Check 6 knows only this run's sessions' pushes, so a
    validation pushing beside a review would read, to the review, as the change
    branch moving without a push record (rare: validation pushes only an unpushed
    `HEAD`).

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

- [x] 6.1 The Claude Code adapter: its unattended command — `dontAsk` with every tool
  allowed, project settings only, its own sandbox off, the schema, the system prompt,
  a fresh session's id, and, as its optional rule, `git push` denied (D13, D2); its
  writable state `~/.claude` and `~/.claude.json`; its protected paths
  `.claude/settings.json`, `.claude/settings.local.json`, and
  `~/.claude/settings.json`; every step. Rules anchored at the checkout (`anchored`)
  go with the step table. Verify: unit tests of the command for a fresh and a resumed
  run, and of the declared paths.
  Done: the adapters are `claude_code.py` and `codex.py`, each with its `ADAPTER`,
  held by harness in `adapters.py`; `harness.py` keeps what they share (`Model`,
  `Adapter`, `Runner`, `unreachable`, `missing_program`, `UNATTENDED`, `refused`).
  `Adapter` holds the harness, its `steps`, `state` directories, `state_files`,
  `protected` paths, and `rules`. `claude_code.command(prompt, schema, model, *,
  session, system)` gives `--permission-mode dontAsk --setting-sources project`,
  `--settings '{"sandbox": {"enabled": false}}'`, the schema, the system prompt,
  `--session-id` or `--resume`, `--allowedTools`, then `--disallowedTools "Bash(git
  push*)"`. Departures:
  - "Every tool allowed" is `claude_code.TOOLS`, each built-in tool a step works with
    allowed whole; the tools that wait for a later turn (Monitor, ScheduleWakeup, the
    cron tools) stay denied, and Claude Code takes no wildcard rule this session
    could confirm.
  - `~/.claude.json` is mounted alone (`ScopedPath.alone`, `scope.resolve`'s
    `adapter_files`, `sandbox.prepare` creating it `{}`), as D5a and CW-m8wq now say.
  Unit tests in `test_change_workflow_harness.py` of the command fresh and resumed and
  of the declared state, settings, steps, and rule pass.
- [x] 6.2 The Codex adapter: the review's commands as today, `--sandbox read-only` kept
  inside the engine's sandbox; its writable state `~/.codex`; its protected path
  `~/.codex/config.toml`; the review only (D13). Verify: unit tests of the commands
  and paths; a library-integration test launching `codex --version` through real
  bubblewrap in the review's scope, where Codex is installed, else skipped saying so;
  if the two sandboxes cannot nest, the adapter drops `--sandbox read-only`, and the
  task's note records it.
  Done: `codex.command`, `codex.resume_command`, `Progress`, and `run` moved from
  `harness.py` unchanged. The two sandboxes were found to nest here, so `--sandbox
  read-only` stayed; 11a.4 drops it in a confined review (48 F1). Tests pass: unit
  tests of both commands and the paths; in `test_change_workflow_sandbox.py`,
  external-process integration (not library integration as planned), run here, in the
  review's scope with a test home: `codex --version` runs, `codex sandbox -- cat
  src/main.py` reads through Codex's own sandbox inside the engine's, a write under
  `~/.codex` succeeds and one to `~/.codex/config.toml` fails read-only. `codex exec`
  itself, which needs a model, is not run. Codex's sandbox keeps a lock under `/tmp`.
- [x] 6.3 Each adapter reads refusals from its run's events: Claude Code's tool results
  in its stream, Codex's command output, each matching "Read-only file system" or
  "Device or resource busy", recorded with its tool, command or path, and error;
  Claude Code's denials stay read as today (D7; CW-w3oa, CW-k5mk). Verify: unit tests
  on recorded stream fixtures for CW-w3oa's scenario, a busy protected file, a denial,
  and a tool result with neither.
  Done: `harness.refused(text)` finds the first line with either error, or Node.js's
  "resource busy or locked". `Stream.refusals` and `transcript_refusals` read Claude
  Code's failed tool results (`is_error`) once per call, each as `{tool, command |
  path, error}`; `codex.refusals(text)` reads only the output of a command Codex says
  exited non-zero; a search or read quoting the error is no refusal. Unit tests on
  events built by hand in Claude Code's stream shape, not recorded from a run, pass in
  `test_change_workflow_stream.py` and `test_change_workflow_harness.py`.
- [x] 6.4 Move `Model` and `HARNESSES` out of `steps.py` to the adapters, and check the
  configuration's models against each adapter's steps: a model only for a step its
  harness's adapter can run, refused naming the step (CW-zq4h). Verify: unit tests for
  CW-zq4h's two scenarios.
  Done: `Model` is `harness.Model`, `HARNESSES` is `adapters.HARNESSES`;
  `config._models` refuses a model for a step its adapter cannot run, naming the step,
  the harness, and the steps it runs. Outside the task: the configuration's check
  refuses a writable path under any adapter's protected path (`adapters.PROTECTED`).
  Unit tests, moved from `test_change_workflow_steps.py` to
  `test_change_workflow_config.py`, pass: the policy's refusals, CW-zq4h's two
  scenarios, an adapter's settings file refused as a writable path.
- [x] 6.5 A step's resolved scope takes the adapter of its first model's harness, and
  `config`/`config --json` list the adapter's paths with their source (CW-o6kc).
  Verify: the library-integration test of 2.4 extended to CW-o6kc's scenario whole.
  Done: `Configuration.scope(step, root, harness=None, …)` adds the paths of the
  adapter of `harness`, by default the step's first model's; `config --json` marks a
  file mounted alone `"file": true`.
  `test_config_lists_each_steps_scope_with_each_paths_source`, library integration
  through `cli.main`, passes: planning's engine, repository (`docs/`) and adapter
  (`~/.claude`, `~/.claude.json`) paths, the three settings files protected, and only
  Codex's paths in the review's scope. A unit test renders a file mounted alone as its
  own `--bind`, created `{}`; an external-process test writes it in place while the
  home beside it stays read-only.
- [x] 6.6 Verification point: the harness, stream, and config tests (unit, library
  integration); `run pre-commit` passes. End-to-end: none.
  Done:
  - `make test-release-tooling` on the harness, stream, config, sandbox, scope, and
    steps tests: passing, none skipped (`-rs`); the wrapper, review, CLI, hooks,
    assumptions, graph, push, and invariants tests: 707 passed.
  - `run pre-commit`: its functional hooks pass, the locks left as committed. Its
    `pre-commit` also failed `check-history-wording`, on "no longer" in a comment
    moved into `claude_code.py`, fixed; the rerun failed only `check-doc-citations`
    on `propose.py`.
  - The fresh-context check's fixes are in the section's commit. Declined, as in
    section 4: reading the adapters' docstrings as describing a launch not yet wired.
  - Open: a protected placeholder such as `.claude/settings.local.json` is created in
    the checkout; this repository ignores it, but a repository that does not would
    see an untracked file, which dirties the worktree for the guarded push.
    `~/.claude`'s other contents are D13's limit.

## 7. Launching every unattended run in the sandbox

Delivers the wrapper and the review runner launching through the adapters inside
the sandbox, the unconfined fallback recorded, refusals on the line from the adapter
and the sandbox's `git`, routed by the next-step computation, and the harness-neutral
unattended prompt (D3, D7, D10, D15's prompt; CW-x3pf, CW-v5ny, CW-w3oa, CW-k5mk,
CW-jqi7, CW-qu42, CW-m8wq). Files: `wrapper.py`, `review.py`, `harness.py`'s
`UNATTENDED`, `log.py`, `next_step.py`, `test_change_workflow_wrapper.py`,
`test_change_workflow_review.py`, `scripts/tests/test_change_next_step.py`.

- [x] 7.1 The wrapper resolves the run's scope (section 2, with its adapter and
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
  Done. In `sandbox.py`:
  - `Confinement(probe, prepare, launch)` is the sandbox as a seam, `BUBBLEWRAP` the
    real one. `confine(confinement, harnesses, resolve, step)` resolves each harness's
    scope before anything runs, so a grant is refused whether or not the sandbox can
    run, probes once, warns where it fails, and returns `Confined(unconfined,
    scopes)`, whose `prepare` creates the mounts and `launch` gives each attempt's
    command.
  - `missing(said, program)` reads bubblewrap's own whole `bwrap: execvp … No such
    file` line, so a harness not installed is unavailable inside the sandbox too.
  - The memfds are inheritable and the runners keep descriptors open
    (`close_fds=False`). Limit: a harness also inherits any inheritable descriptor the
    engine itself inherited, such as a make jobserver's pipes.
  `Wrapper` gains `confinement`, `home`, and `temporary`, and drops `steps_path`: `run`
  and `resume` confine before `_turn`; `_logged_turn` prepares the mounts after the
  before-actions and before `begin()`; each attempt launches `claude_code.command`, the
  skill and `resume_from` from `STEP_DEFINITIONS`, `unconfined: true` on the line.
  `run_review` and `review_and_log` confine likewise; Codex and its Claude fallback
  (with `REVIEW_UNATTENDED`) launch through `Confined.launch`; Codex's
  `--output-last-message` draft lives in a run-scoped `mkdtemp`, since the review's
  checkout is read-only, moved into `transcripts/` after. `claude_code.table_command`,
  `anchored`, and the wrapper's and review's `load_steps` and `steps_path` are removed.
  Tests pass, none skipped:
  - external-process integration: a design run, the harness doubled through
    `claude_code.run`, writes under `openspec/`, is refused `src.py`, and its line
    names the refusal; a Codex-doubled reviewer's write of a reviewed file fails, its
    write under `.git/change-invocations/` and its draft succeed, the draft is
    published and its directory gone (not CW-m8wq's "A review runs the checks before a
    commit", which needs Claude Code); with the probe doubled to fail, a triage warns,
    records `unconfined: true`, and its stash still stops it;
  - library integration: an unconfined review recording `unconfined: true`; a resumed
    design naming a Codex model refused before any session; a unit test of `missing`.
  Not tested: the Claude fallback reviewer inside real bubblewrap; a harness not
  installed inside it, past `missing`'s unit test. The other wrapper and review tests
  use `NO_SANDBOX`, a fixture `Confinement` that creates nothing.
- [x] 7.2 The line's `refusals` gather the adapter's (6.3) and each push the sandbox's
  `git` refused (4.1), taken from the session's invocations, whatever the harness
  (D7; CW-w3oa, CW-j4cs's refused-push scenario); `denials` stay the harness's.
  Verify: library-integration tests for CW-j4cs's "A refused push reaches the run's
  record" and CW-k5mk's "A step's message omits a refusal".
  Done: `running.refused_pushes(invoked)` turns each `REFUSED_PUSH` entry into `{tool:
  "git", command, error}`. The wrapper's line carries each attempt's
  `Stream.refusals`, then the refused pushes; the review's carries the transcript's
  refusals of either harness (`transcript_refusals_of_either`, Codex's reading reset at
  a Claude Code event, unit-tested), then the refused pushes, only the published path
  tested. A Codex reviewer's refused pushes reached no line until 11a.5's run key.
  External-process tests pass: CW-j4cs's scenario, an implementation run's `git push
  --no-verify origin HEAD:dev` refused, on the line's `refusals` with its command
  line, the bare remote holding nothing; CW-k5mk's scenario, in 7.1's design test, the
  message naming no refusal while the line carries it.
- [x] 7.3 The next-step computation treats a line carrying `refusals` as one carrying
  `denials`: the owner reads it before the change moves on, and a waiting outcome
  waits for that reading (CW-jqi7). Verify: library-integration tests in
  `test_change_next_step.py` for CW-jqi7's two scenarios.
  Done: `next_step._unread(entry)` is denials or refusals, used by `_waiting` and the
  waiting list; the owner's result carries `refusals` beside `denials`, its reason
  counting both and asking for each to be read as a finding or a gap;
  `log.decision_line` lets `--reads` name a run with refusals and no denials.
  Library-integration tests in `test_change_next_step.py` pass: CW-jqi7's "A question
  carries refusals", a finished run with refusals waiting for its reading, and the
  existing denials test; three tests' expected reason text was updated.
- [x] 7.4 Rewrite `UNATTENDED` as one harness-neutral paragraph: the step runs in a
  sandbox scoped to it; a write refused as a read-only file system or busy is outside
  its scope; stop naming the path if it cannot go on, else say what it did instead;
  wait on background commands with `wait`; end every turn with its outcome (D15;
  CW-4yhk, CW-b5cf). Verify: a unit test that the prompt names no rule, chain,
  "don't ask mode", or `-C`.
  Done. `harness.UNATTENDED` is one paragraph. It says a denied call is recorded too,
  without naming a rule. A unit test in `test_change_workflow_harness.py` passes: no
  "rule", "chain", "don't ask mode", "Bash call", or "step table", no `-C` as a word
  (`-c\b` on the lowered text), and each of its points present.
- [x] 7.5 Interactive runs stay outside the sandbox and the checks: the make targets
  without `UNATTENDED=1` open the owner's harness as today, and `run before`, `run
  after`, and `record` record no state and run no check (D9; CW-g5ry). Verify: the
  fragment's interactive command line (`make -n design CHANGE=<change>`) holds no
  `bwrap`, and a library-integration test of `record` on a run that rewrote history
  records its outcome with no `invariants`.
  Done; nothing in the interactive path changed. Tests in
  `test_change_workflow_cli_steps.py` pass: `make -n design CHANGE=X` prints the
  interactive start alone, which opens `["claude", "/change-design …"]`, no `bwrap`;
  `record` of a triage after an amend records it with no `invariants` and no
  `unconfined` (library integration). `run before` and `run after` were not tested:
  neither calls `invariants` or the sandbox.
- [x] 7.6 Verification point: the wrapper, review, and next-step tests (library
  integration through real bubblewrap); `run pre-commit` passes. End-to-end: none.
  Done. The tests through real bubblewrap are external-process integration.
  - `make test-release-tooling` on the review, wrapper, harness, sandbox, CLI, CLI
    steps, hooks, push, cost, stream, next-step, log, invariants, around,
    assumptions, graph, steps, and config tests: 1435 passed, none skipped (`-rs`).
    After the check's fixes, the review, wrapper, harness, next-step, log, CLI, and
    sandbox tests: 855 passed.
  - `run pre-commit`: its functional hooks pass, the locks left as committed. Its
    `pre-commit` also failed `check-doc-citations` on a path in these notes and
    `check-comment-hygiene` on a literal `01-design.md` in a test, both fixed; the
    rerun failed only `check-doc-citations` on `propose.py`, expected.
  - The fresh-context check's fixes are in the section's commit. Declined: dropping
    `prepare` from `sandbox.launch`, which is idempotent and keeps `launch` whole for
    section 3's tests.
  - This round's runs were the first real ones in the sandbox, to watch Claude Code's
    `~/.claude.json` saves (6.1) and the Python each Git call inside starts.

## 8. Grants as writable paths

Delivers `--write` on `start` and `resume` and `WRITE=` on the make targets in place
of `--allow` and `ALLOW=`, recorded as `writes_granted` (D8; CW-tl5v, CW-drf6).
Files: `cli.py`, `wrapper.py`, `log.py`, `scripts/change_workflow/workflow.mk`,
`test_change_workflow_cli.py`, `test_change_workflow_wrapper.py`,
`scripts/tests/test_workflow_command.py` where it covers the fragment.

- [x] 8.1 `start` and `resume` take `--write <path>`, parsed as 2.3, refused before
  anything launches; the wrapper adds each to the run's scope and records
  `writes_granted`; `--allow` is removed and exits 2 (D8; CW-tl5v, CW-drf6). Verify:
  library-integration tests for CW-tl5v's three scenarios and CW-drf6's protected-path
  scenario, and `--allow` refused as a usage error.
  Done: `start` and `resume` take `--write`, appended; an interactive start refuses it
  as a usage error. `Wrapper.run(writes=…)` and `Wrapper.resume(…, writes)` pass the
  values to `_confine` as `grants`, so `scope.granted` refuses a pattern or a
  protected path, naming the value, before the run's inputs are claimed or anything
  runs; the parts, split by `scope.grant_paths`, are recorded as `writes_granted`.
  `granted`, `split_rules`, and `--allow` are gone: argparse refuses `--allow` and
  `main` exits 2. Tests pass:
  - in `test_change_workflow_cli_steps.py`, library integration through `cli.main`,
    the sandbox stood in for by a `Confinement` keeping the scopes it is asked to
    mount: CW-tl5v's fresh run (two values, one holding two paths, in the scope and
    on the line, the next run having neither); its stopped run resumed with `--write
    kit/site/.venv` (from the root, marked to be created); its pattern and CW-drf6's
    protected path (exit 1 naming the value, no scope mounted, no session, no run
    line); a parser test of `--allow` exiting 2 on `start` and `resume`;
  - the wrapper's grant tests now grant paths, and a next-step test's resumed line
    records `writes_granted`.
- [x] 8.2 `workflow.mk`'s step targets take `WRITE=`, several paths separated by `;`,
  each reaching the command as its own `--write`, and drop `ALLOW=` from their
  targets and help (D8). Verify: the fragment's command lines (`make -n`) for one and
  two paths, and its help naming `WRITE`.
  Done: `CHANGE_WORKFLOW_GRANTS` writes `--write '<path>'` per part; the eight step
  targets' help says `[WRITE='<path>;<path>']`, and the header says what an unattended
  target runs in, the unconfined fallback included. Static configuration tests
  (`docs/guidance/repository/static-configuration-tests.md`) pass: `make -n` through
  the fragment and the root Makefile for one and two paths, an interactive design
  ignoring `WRITE`; a real shell keeping a path's quotes and backticks, an empty part
  dropped; every unattended step target's `##` help naming `WRITE`, and no `ALLOW` in
  the fragment.
- [x] 8.3 Verification point: the CLI, wrapper, and fragment tests (library
  integration); `run pre-commit` passes. End-to-end: none.
  Done. The CLI and wrapper tests are library integration, the fragment's dry runs
  static configuration tests.
  - `make test-release-tooling` on the wrapper, CLI, CLI steps, validate-slice,
    scope, review, push, and assumptions tests: 688 passed, none skipped. After the
    check's fixes, the CLI steps, next-step, and CLI tests: 519 passed.
  - `run pre-commit`: its functional hooks pass, the locks left as committed; its
    `pre-commit` fails only `check-doc-citations` on `propose.py`, expected.
  - The fresh-context check's fixes are in the section's commit.
  - Open: the spec delta's CW-tl5v scenario is still titled "The owner grants rules
    before a fresh run", which the section's test quotes; closeout's promotion may
    retitle it "paths". `--write` is unchecked against the review, which takes no
    grant. The handbook, the change-workflow companion, and change-orchestrate's
    `ALLOW=` and `--allow` are 10.4's and 12.9's.

## 9. `propose`, the history copy, and the round view's refusal

Delivers the engine's creation of a prerequisite's worktree and its mount for design,
archive cleanup's history copied by the engine after its session, and the round view
refusing under the unattended marker (D5b, D5's history, D14; CW-k8dn, CW-dtpz,
CW-hak6, CW-p3vz). Files: a new `scripts/change_workflow/propose.py`, `cli.py`,
`scope.py`, `graph.py`'s `STEP_ACTIONS`, `around.py`, `round_view.py`,
`test_change_workflow_cli.py`, `test_change_workflow_scope.py`,
`test_change_workflow_around.py`, `scripts/tests/test_round_view.py`.

- [x] 9.1 Add `propose <change> <prerequisite>`: the worktree
  `../<prerequisite>-proposal` on a new branch `propose-<prerequisite>` from the
  change's landing branch (`find --json`'s `base`) as its remote holds it, `--no-track`,
  refusing one that exists, at the provisional tier (D5b; CW-k8dn). Verify:
  library-integration tests on real Git: the worktree on its branch with no upstream,
  and a second run refused.
  Done: the new `propose.py` holds `propose(root, change, prerequisite, base)` and
  `main`; `cli` dispatches `propose <change> <prerequisite> [--base <branch>]`, its
  help and docstring calling it provisional.
  - The landing branch is `find.landing_branch`, or `--base` where no clone recorded
    one; the remote is the one it tracks, as the workspace records it in a clone,
    else as this checkout does, one tracking none refused: the engine names no remote
    of its own.
  - It fetches into the remote-tracking branch, never `FETCH_HEAD`, which a parallel
    fetch could replace, then runs `git worktree add --no-track -b
    propose-<prerequisite> ../<prerequisite>-proposal refs/remotes/<remote>/<base>`.
  - It refuses an unknown change, a prerequisite that is no change name
    (`find.check_name`), an existing directory or branch, and a failed fetch or
    worktree.
  Library-integration tests in `test_change_workflow_cli.py`, real Git with a bare
  remote, pass: the worktree on `propose-shape-floor` at `origin`'s `dev` with no
  upstream, a second run refused; a landing branch tracking `upstream`; an existing
  branch and a missing landing branch refused; an unknown change, `archive`, and a
  path refused; `propose.main` refused outside any repository. Not tested: a failed
  fetch, and a failed `worktree add`. The command and its tier reach the companion's
  "The command and its tiers" at closeout (12.9).
- [x] 9.2 A design run's scope adds, writable, every worktree registered in its
  checkout's `.git/worktrees/` whose path matches `../*-proposal` (D5b; CW-k8dn).
  Verify: a unit test resolving design's scope with one registered and one unrelated
  worktree; a library-integration test through real bubblewrap that the doubled
  design writes the proposal there.
  Done: design's baseline holds a role entry, `graph.PROPOSALS`;
  `scope._Checkout.proposals` reads `git worktree list --porcelain`, keeping each
  worktree beside the root whose name ends `-proposal` (`graph.PROPOSAL_SUFFIX`),
  never the checkout itself, as an engine path. Tests pass: library integration (the
  plan said unit) in `test_change_workflow_scope.py`, design's scope holding a
  registered proposal worktree and not an unrelated one, one so named elsewhere, or
  planning's; external-process integration in `test_change_workflow_sandbox.py`, a
  design scope's shell writing under the proposal's `openspec/` while a sibling
  worktree stays read-only; the graph's baseline test names `PROPOSALS`.
- [x] 9.3 Add the history copy to `STEP_ACTIONS` after archive cleanup, run once its
  session finishes and before its outcome is logged, writing outside the sandbox
  (D5; CW-hak6). Verify: library-integration tests with the harness doubled for
  CW-hak6's scenario and the copy's line in `invoked`.
  Done: `STEP_ACTIONS[(AFTER, "archive-cleanup")]` is `(graph.HISTORY,)`, an action
  that is no hook-table entry, so no step runs it through `run`. `Around._history`
  runs `history.main(["sync", change])` in the engine's process, outside the sandbox,
  keeping an `Invoked` entry (`history sync <change>`, its exit status) timed by
  `Around`'s new `clock`; a change worked in place copies nothing and passes, saying
  so; a failed copy is a failed action, resuming the session. Library-integration
  tests pass: CW-hak6's scenario through the wrapper on a real clone in
  `test_change_history.py` (the line's `invoked` holds the copy with status 0, and the
  next sync extends the log); the in-place case in `test_change_workflow_around.py`;
  the graph's actions test. That the copy succeeds after a confined session holds by
  structure; no test confines the session.
- [x] 9.4 `round-view` and `round-done` refuse while `CHANGE_WORKFLOW_UNATTENDED` is
  set, naming the step, and move nothing (D14; CW-p3vz). Verify: a library-integration
  test in `test_round_view.py` for CW-p3vz's scenario.
  Done: `round_view.main` takes `environ` from `cli` and refuses `start` and `done`
  before reading anything while `UNATTENDED_RUN` names a step
  (`unattended_refusal`); `check` still runs, since a step's guard reads it.
  Library-integration tests in `test_round_view.py` through `cli.main` pass: CW-p3vz's
  scenario (exit 1 naming the triage, nothing moved, `check` passing under the
  marker), and `round-done` under the marker leaving the owner's view open at the
  base. The module's fixture now removes an inherited marker, which had made three
  existing tests refuse (every scripts test, from 11.6).
- [x] 9.5 Verification point: the tests above (unit, library integration through real
  bubblewrap); `run pre-commit` passes. End-to-end: none.
  Done. The tests through real bubblewrap are external-process integration.
  - `make test-release-tooling` on the sandbox, scope, round view, graph, CLI,
    history, around, common, wrapper, and review tests: 682 passed, none skipped.
  - `run pre-commit`: its functional hooks pass; `check-doc-citations` now passes,
    `propose.py` existing. A first run's `check-comment-hygiene` failure, on a
    fixture path ending `proposal.md`, was fixed by renaming; the rerun passed nine
    of nine, the locks left as committed.
  - The fresh-context check's fixes are in the section's commit. Declined: reusing
    `Hooks`' timing and keeping for the copy's single `Invoked` entry.

## 10. The skills

Delivers every workflow skill free of the step table's rules and the exemptions this
change owns, with design's prerequisite through `propose`, archive cleanup without
`history`, and the orchestrating session reading refusals and relaying unconfined
runs (D15, D5b, D7, D8, D10, D14; CW-n8tr, CW-dtpz, CW-svng, CW-5rmh, CW-vdqj,
CW-v5ny). Files: `.agents/skills/*/SKILL.md`,
`openspec/specs/market-change-workflow/README.md`'s "What the workflow's skills name
of this repository" (the assumptions test reads it),
`scripts/tests/test_change_workflow_assumptions.py`.

- [x] 10.1 Replace each step skill's "Running unattended" denial paragraphs — one
  command per call, the write-steering exception, "don't ask mode", never `git -C` or
  `make -C`, commands in the forms the rules name, a helper carrying those rules —
  with the paragraph `UNATTENDED` gives (7.4), keeping each skill's other unattended
  bullets (D15). `change-implement` names a project's tests and bring-up by role, no
  `make -C <package>` form or `docker compose -p` form remaining. Verify: a search of
  `.agents/skills/` finds no "don't ask mode", "write-steering", "step table", or
  `make -C <package>`; `make check-agent-skills` passes.
  Done: in design, plan, implement, triage, validate, merge, closeout, and archive
  cleanup, "A denied call stops the step only when it cannot go on" and "Git runs in
  this checkout" are one bullet, "The step runs in a sandbox scoped to it", carrying
  `UNATTENDED`'s points (a read-only or busy write is outside the scope; stop naming
  the path, or go on and say what was done instead; a denial is the same, both
  recorded; wait with `wait`). Implement, triage, and merge leave the wait sentence to
  their own "A turn's end is its outcome" bullet; triage keeps "Remove a tracked file
  with `git rm`". Validate, closeout, archive cleanup, merge, and review each say what
  their sandbox means for them; implement's command-form bullets become "A project's
  tests and bring-up, by role", naming no `make -C <package>` or `docker compose -p`
  form; guidance-review's "no row in the step table" is "no definition in the engine".
  A search of `.agents/skills/` finds none of the four phrases, no "one command per",
  "no rule allows", "no rule admits", or "deny rule"; `make check-agent-skills` passes.
- [x] 10.2 `change-plan` and `change-implement` give an edit of the harness's settings
  to the orchestrator because no step writes them (the adapter's protected paths), and
  an edit of the workflow's configuration because no step writes it, never naming
  `.claude/`; `change-triage` likewise (D15). Remove the exemption rows this change
  owns from `market-change-workflow/README.md`'s "What the workflow's skills name of
  this repository" (CW-n8tr). Verify: `test_change_workflow_assumptions.py` passes,
  its exemption test finding no row owned by this change.
  Done: the plan's, implementation's, triage's, and orchestration's hand-offs to the
  orchestrator each name a protected path — the harness's settings, the workflow's
  configuration, or one the repository protects, as `config --json` lists them —
  never `.claude/`. The three exemption rows are gone, the section holds no table, and
  the companion no longer points at "the exemptions below"; the spec's MCW evidence
  line citing "the README's table of exemptions" is left for closeout's promotion
  (12.9). The assumptions test no longer requires an exemption to exist, still failing
  on one no skill names or whose owner is no open change.
  `test_change_workflow_assumptions.py` passes, 18 tests.
- [x] 10.3 `change-design`'s "When the design needs another change first": the design
  ends with a question naming the prerequisite; once the orchestrating session ran
  `propose` on the owner's word, the resumed session writes and checks the proposal
  in the worktree and ends blocked (D5b; CW-dtpz). `change-archive-cleanup` no longer
  runs `history`: the engine copies after its session, and its report names the
  copy's result from the line (CW-hak6). Verify: a reading of both sections against
  CW-dtpz's and CW-hak6's scenarios; `make check-agent-skills` passes.
  Done: design's step 2 ends the turn asking for the prerequisite's worktree;
  `propose` runs on the owner's word, by the orchestrating session or, interactively,
  the session itself; the resumed session writes and checks the directory and index row
  there; steps 3 and 4, ending `blocked`, are unchanged. Archive cleanup's step 10,
  "The history copy, the engine's", never runs `history`: the engine copies once the
  session finishes, and interactively `run after archive-cleanup` copies; its
  description, introduction, end bullet, "Status" repeat, and interactive paragraph
  follow. Its report gives, unattended, that the engine copies once the session ends,
  its status on the line and its report in the run's `after/` directory, which the
  orchestrating session relays — narrowing the task's "its report names the copy's
  result from the line", since an unattended session cannot read its own line. Read
  against CW-dtpz's and CW-hak6's scenarios, steps 2 to 4 and step 10 match.
- [x] 10.4 `change-orchestrate`: refusals and denials read from the line and classified
  as a finding or a gap (CW-svng), a finding's run checked for a workaround
  (CW-5rmh), a gap answered with the narrowest path from `config --json`'s scope as a
  `--write` grant or a `[sandbox]` edit (CW-vdqj), `unconfined: true` relayed to the
  owner (CW-v5ny), `propose` run on the owner's word (CW-k8dn), and a violation's
  `invariants` relayed (CW-f9le); the classification by deny rules, write-steering,
  and the step table's rules removed (D7, D8, D10, D14). Verify: a reading against
  those requirements; a search finds no `change-steps.toml` or `ALLOW=`.
  Done: "Read every refusal and denial before advancing" reads both from the line,
  never the message; classifies each, from the call and the step's job, as a finding
  or a gap, every refused push and adapter-rule denial a finding; checks a finding's
  later calls for a workaround; answers a gap with the narrowest path from `config
  --json`'s scope, as `--write`/`WRITE=` or a `[sandbox]` edit, never a protected path
  or a denied push; records `gap:`, `finding:`, or `workaround:`; recovers by
  `--write`; and relays a line's `invariants`. "Run the computed step" takes `WRITE=`,
  `writes_granted`, and relays `unconfined: true`; the prerequisite paragraph runs
  `propose` on the owner's word; `done` relays the engine's history copy. The denials
  report reads denials alone, so the skill reads a run's transcript after a refusal
  read as a finding; the engine's report could cover refusals in a later change. The
  skill names the configuration and its `[sandbox]`, never the step table; a search
  finds no `change-steps.toml`, `ALLOW=`, `--allow`, "deny rule", or "step table" in
  it.
- [x] 10.5 Verification point: `make check-agent-skills` and
  `test_change_workflow_assumptions.py`; `run pre-commit` passes. End-to-end: none.
  Done:
  - `make check-agent-skills` passes. The tests reading the skills (assumptions,
    steps, agent-skills, next-step, guidance, code-snapshot, CLI): 549 passed; after
    the check's fixes, the assumptions, agent-skills, and steps tests: 64 passed.
  - `run pre-commit` passed every hook and check, nine of nine, before the check's
    fixes and after them; the locks left as committed.
  - The fresh-context check's fixes are in the section's commit.
  - The merge whose landing branch changed a protected path, flagged here, was
    settled in the round's triage (D15; 11a's fixes). The step table's remaining
    mentions were 11.4's, 11.5's, and 12.10's.

## 11. This repository's `[sandbox]`, and the step table removed

Delivers this repository's `[sandbox]` declaration, the step table and its loader
removed, the roles test reading only the make fragment, and every comment naming the
table rewritten (D11, D12, D14; MCW-s4bx, MCW-5tgp, CW-m4ps, CW-z5me). Files:
`.agents/workflow.toml`, `.claude/change-steps.toml`, the engine's `steps.py`,
`__init__.py`, `common.py`, `config.py`, `cli.py`, `workflow.mk`, `scripts/ci_evidence.py`,
its `test_change_workflow_steps.py`, `scripts/tests/test_change_workflow_assumptions.py`,
`test_change_workflow_cli.py`, `test_change_workflow_harness.py`,
`test_change_workflow_review.py`, `test_change_workflow_wrapper.py`,
`openspec/specs/market-change-workflow/README.md`'s "The engine's own assumptions" and
"How this repository provides the workflow's roles" (the assumptions test reads
them).

- [x] 11.1 Declare `.agents/workflow.toml`'s `[sandbox]`: `writable.common =
  ["~/.local/share/uv", "~/.kube/cache", "~/.config/gcloud", "~/.docker"]`,
  `writable.design = ["docs/"]`, `writable.plan = ["docs/"]`, `protected = []`, each
  with its comment naming who uses it (D12; MCW-s4bx). The configuration is denied to
  every step while the step table holds: this task is the orchestrator's, made on the
  owner's word before the section's session starts, and the session commits it.
  Verify: `config --json` lists design's `docs/` from the repository, and
  `test_the_repositorys_own_configuration_passes_its_check` passes, with a unit test
  for MCW-s4bx's two scenarios against the resolved scopes.
  Done: the orchestrator's edit was in the worktree and is committed with the section.
  `config --json` lists design's and planning's `docs/` and the four tool paths, for
  every step but the review, from the repository, and no repository protected path;
  `check config` passes. Tests in `test_change_workflow_config.py`, library
  integration (the plan said unit: each resolves the repository's scopes through real
  Git), pass: MCW-s4bx's "Design edits the roadmap" and "Implementation syncs an
  environment", and the existing
  `test_the_repositorys_own_configuration_passes_its_check`.
- [x] 11.2 Remove `.claude/change-steps.toml` (D11). Every step is denied edits under
  `.claude/`: this task is the orchestrator's, on the owner's word before the
  section's session starts, and the session commits it with the section. Verify:
  the file is gone, and nothing under `scripts/` reads it.
  Done: the orchestrator's removal was in the worktree and is committed with the
  section. A search of `scripts/` finds no `change-steps`; `test_change_workflow_cli.py`
  no longer copies the table into its archived-change fixture.
- [x] 11.3 Remove `steps.py` and `test_change_workflow_steps.py`, moving each test
  still meaningful — every step has a skill, the review writes nothing it reviews, no
  step's scope holds the configuration — onto the engine's definitions and scopes in
  `test_change_workflow_graph.py` and `test_change_workflow_scope.py`; drop
  `steps.STEP_TABLE` and the wrapper's and review's `steps_path` (D11; CW-z5me).
  Verify: the moved tests pass, and a search of `scripts/` finds no `load_steps`,
  `StepRules`, or `STEP_TABLE`.
  Done, with `git rm` (the wrapper's and review's `steps_path` went in section 7).
  Moved, passing:
  - `test_every_step_runs_its_own_skill_and_planning_resumes_the_design` (graph,
    unit), in place of comparing the definitions with the table;
  - `test_no_step_writes_the_configuration_or_the_harnesss_settings`, library
    integration in `test_change_workflow_config.py` beside MCW-s4bx's tests rather
    than in `test_change_workflow_scope.py` as planned;
  - the review writing nothing it reviews, already held by the graph's and the
    scope's review tests and MCW-s4bx's second test;
  - `test_each_step_runs_on_the_models_its_work_needs`, moved to
    `test_change_workflow_config.py` unchanged.
  The table's other tests judged its allow and deny rules, which the sandbox, the
  engine's `git`, and the checks replace (D14). A search of `scripts/` finds no
  `load_steps`, `StepRules`, or `STEP_TABLE`.
- [x] 11.4 The roles test reads the make fragment and the configuration only, no step
  table (CW-m4ps, MCW-5tgp); `market-change-workflow/README.md`'s "The engine's own
  assumptions" drops the step table's row and names `bwrap` among the tools, and "How
  this repository provides the workflow's roles" gives the tests-and-environments
  role through the hooks and `[sandbox]` rather than the step table's grants. Verify:
  `test_change_workflow_assumptions.py` passes.
  Done: `collected` reads the fragment alone. In the market companion the test's
  paragraph names the fragment alone; "The engine's own assumptions" drops the step
  table, names `bwrap` among the tools, without which a step runs unconfined, and says
  the local settings are protected where a clone's link leads; "How this repository
  provides the workflow's roles" gives the tests-and-environments role through the
  hooks and `[sandbox]`'s `writable.common`, in role forms, and the other rows no
  longer say what the table granted or denied. `test_change_workflow_assumptions.py`
  passes, 18 tests.
- [x] 11.5 Rewrite every comment and docstring naming the step table or its rules to
  describe the current system — `__init__.py`, `common.py`, `config.py`, `cli.py`,
  `workflow.mk`, `scripts/ci_evidence.py`, and any section 1 to 10 left (a repository
  obligation, `docs/guidance/engineering/comments.md#comments-describe-the-current-system`).
  Verify: a search of `scripts/` finds no "step table" or `change-steps`; `make
  check-comment-hygiene` passes.
  Done: `__init__.py`, `common.py`, `config.py`, `cli.py`, and `ci_evidence.py`
  describe the current system (`workflow.mk` named none); the prompt test drops "step
  table", its "rule" covering it. Outside `scripts/`,
  `docs/guidance/repository/test-targets.md` now gives its own reason a hand-written
  `uv run … pytest` is not run (12.10 checks the guidance). A search of `scripts/`
  finds neither phrase; `make check-comment-hygiene` passes.
- [x] 11.6 (Moved to section 11a.) Verification point: the whole scripts suite and `make check-agent-skills`;
  `run pre-commit` passes. End-to-end: none.
  Outside the plan, on the owner's direction: bubblewrap cannot mount over a symlink,
  so every clone's first unattended run stopped at launch on its linked
  `.claude/settings.local.json` (`make change-clone` links it); a writable symlink
  failed the same way. `sandbox.py` now mounts each writable and protected path where
  its symlinks lead (`mounted_writable`, `mounted_protected`), `prepare` creating an
  absent target there (D20). Unit and external-process tests in
  `test_change_workflow_sandbox.py` pass: a checkout whose settings file is an
  absolute link outside the scope launches, a write through it fails "Read-only file
  system", the link stays; a file linked inside the checkout is read-only; a linked
  writable `~/.cache` is written where it leads. The orchestrator replaced this
  clone's link with a copy, so this run did not itself launch through a link. The link
  itself is no mount, D19's limit.

  Outside the plan, found running the suites inside this run's own sandbox:
  - a sandbox started inside the engine's cannot mount over the enclosing `git`, so
    `sandbox.launch` keeps the `git` it finds there (`nested`, its `inside` seam) and
    mounts the system's Git from `REAL_GIT`; a unit test renders it, and the
    bubblewrap tests, run nested here, exercise it;
  - the suite inherits the step's marker, so a test's own `git push` was refused;
    `scripts/tests/conftest.py` now removes the marker for every scripts test.
  Evidence, in this run's sandbox: the whole scripts suite, 3523 passed, none skipped
  (`-rs`); `make check-agent-skills`, `check-comment-hygiene`, `check-spec-index`, and
  `check-doc-citations` pass, the last once `design.md`, the proposal, and this
  section's file list named the removed `steps` module without its path. `run
  pre-commit`: `after-functional-change` passes, the locks as committed; `pre-commit`
  passes nine of nine once npm's cache is redirected; `pre-commit-functional` fails
  only `domains/bare_metal/provisioning/iac`'s ledger tests, 82 errors at setup,
  "unsafe ancestor" (`make -k test`), since in the user namespace root-owned `/` and
  `/tmp` show as uid 65534. `npx` failed read-only on `~/.npm`; on the owner's word
  the orchestrator added `~/.npm` to `writable.common`, committed with this section.

  Returned to design, on the owner's word: "We have to do something about the
  bare-metal IaC suite before we can proceed with this change. This change caused
  the failure and has to resolve it." Settled as D17 and D18, with `~/.npm` in
  MCW-s4bx's delta (D21). The section's work was one work-in-progress commit. The
  change-workflow companion, its specification, and the handbook still cited
  `.claude/change-steps.toml` and `steps.STEP_TABLE`, for closeout's promotion (12.9).

  Design review 48's triage added two tasks, placed in 11a: 48 F1 (a confined Codex
  review without Codex's own sandbox) and 48 F3 (the Codex review's run key). Its F2
  and F4 changed the design and the delta only; its F5 was planning's.

  Correction (planning, after the return to design): 11.1 to 11.5 were checked in the
  work-in-progress commit `d05a2b130`, and their notes record each as done; that
  commit's message's "no task is checked" holds for 11.6 alone. 11.6's verification
  point moves to section 11a.

## 11a. The private `/tmp`, Codex's confined review, and section 11's verification point

Replanned against the design settled after the return and its review 48: delivers
every step's private tmpfs `/tmp` with `TMPDIR` pointing at it and the scope's named
host paths bound inside it, its listing and the refusal of `/tmp` as an entry or a
grant (D17, D18; CW-x3pf, CW-m8wq, CW-h2zt, CW-tl5v, CW-o6kc); a confined Codex
review without Codex's own sandbox, and its engine run key (D13; CW-t6mb, CW-w3oa;
48 F1, F3); the delta's statements of what sections 4, 5 and 11 already built (D6's
check 6, D19, D20, D21; CW-q7ub, CW-r6kd, MCW-s4bx), proven as stated; and section
11's verification point. Files: `scripts/change_workflow/graph.py`, `scope.py`,
`sandbox.py`, `config.py`, `review.py`, `codex.py`, `sandbox_git.py`, `hooks.py`,
`.agents/workflow.toml`'s `[models]` comment, `scripts/tests/test_change_workflow_scope.py`,
`test_change_workflow_sandbox.py`, `test_change_workflow_config.py`,
`test_change_workflow_review.py`, `test_change_workflow_harness.py`,
`test_change_workflow_sandbox_git.py`, `test_change_workflow_invariants.py`.

This section's session runs in a sandbox the engine launched before its work, which
binds the host's `/tmp`: its own `run pre-commit` meets the ledger suite's failure
until the commit's engine launches the next step (design, "Implementation
cadence"). Its evidence for D17 is the change's sandbox launched from inside its own.

- [x] 11a.1 The private `/tmp` (D17, D18; CW-m8wq, CW-x3pf). The scope's temporary
  entry renders as `--perms 0700 --tmpfs /tmp`, mounted before every bind; the
  sandbox sets `TMPDIR` to `/tmp` (`--setenv`); each writable path under the host's
  temporary directory the scope names — a grant, the review's drafts directory — is
  bound at its own path inside the tmpfs, created first where absent, as every
  writable path is; inside the engine's sandbox (`nested`) the same holds, from the
  enclosing private `/tmp`. Comments and docstrings of `scope.py`, `sandbox.py` and
  `graph.py` describe the private `/tmp` where they describe the host's. Verify:
  - unit, `test_change_workflow_sandbox.py`: the rendered command holds the tmpfs and
    its mode before any bind, `TMPDIR`, and a named path under the host's
    temporary directory bound at its own path after the tmpfs; the nested command
    the same;
  - library integration through real bubblewrap, `test_change_workflow_sandbox.py`:
    inside a launched scope `/tmp` is the owner's with mode `0700`, the ancestor
    check the bare-metal helper makes passing (CW-m8wq's "A suite checks its
    temporary directory's owner": each ancestor of a path under `/tmp` owned by root
    or the caller and writable by no one else); `TMPDIR` is `/tmp`; a host file under
    `/tmp` outside the scope is not visible; a named path under the host's `/tmp` is
    written at the same host path; the bubblewrap tests of sections 3, 6, 7 and 11
    still pass, each giving the inner sandbox what it reads under `tmp_path` where
    the private `/tmp` now hides it.
  Done: the baseline's temporary entry resolves to `scope.PRIVATE_TEMPORARY`, a
  `ScopedPath` marked `private`, from the engine, never a host path, so
  `scope.resolve`, `Configuration.scope`, the wrapper and `review_confined` lost their
  `temporary` parameter (the review keeps its own, for its drafts directory, 11a.3).
  `sandbox.arguments` renders `--perms 0700 --tmpfs /tmp --setenv TMPDIR /tmp` right
  after the base mounts, before every bind; `prepare` creates nothing for it. Tests
  pass:
  - unit, `test_change_workflow_sandbox.py`: the rendered command, plain and nested,
    a path under the host's `/tmp` bound after the tmpfs with a protected path inside
    it bound read-only after that;
  - library integration, `test_change_workflow_scope.py`: each of the nine steps'
    temporary entry is the private `/tmp` from the engine;
  - external-process integration (the plan said library integration),
    `test_change_workflow_sandbox.py`: CW-m8wq's "A suite checks its temporary
    directory's owner" (`/tmp` the owner's, `700`, the bare-metal helper's ancestor
    check, replicated, passing); `TMPDIR` is `/tmp` though the caller set `/var/tmp`;
    a host file under `/tmp` outside the scope hidden, a granted path under it written
    at the same host path, a file written to the private `/tmp` absent on the host.
  Every bubblewrap launch here took the nested path (`sandbox.nested()`); the
  unnested launch was shown by the unit rendering alone until the round's triage. The
  earlier bubblewrap tests read their directories under pytest's `/tmp` through
  `change_workflow_fixtures.with_test_directory` or `reading(base)`; the sandbox's
  Codex test runs `git rev-parse` in the review's scope instead of Codex's own sandbox
  (11a.4).
- [x] 11a.2 The listing and the refusals (D18, D8, D12; CW-o6kc, CW-h2zt, CW-tl5v).
  `config` and `config --json` list each scope's temporary entry as the private
  `/tmp`, from the engine (in JSON, `path` `/tmp` and `"private": true`); the
  configuration's check refuses `/tmp` itself in any `writable` key, and `granted`
  refuses a `--write` of `/tmp` itself, each naming the value, before anything
  launches; a path under `/tmp` is admitted in both. Verify, unit in
  `test_change_workflow_scope.py` and `test_change_workflow_config.py`: CW-h2zt's "A
  repository opens the host's temporary directory", CW-tl5v's "A grant names the
  host's temporary directory", a grant of `/tmp/x` admitted and bound inside, and
  the listing in both forms.
  Done: `scope.hides_temporary`, asked by `granted` and the configuration's
  `_sandbox`, refuses an entry that is `/tmp` or a directory holding it, lexically or
  where its links lead (D20); refusing `/`, beyond the plan's "`/tmp` itself", since
  bound after the tmpfs it would hide the private `/tmp` as surely. Each refusal names
  the value. `config` lists the entry as `/tmp (private)`, `config --json` with
  `"private": true`. Tests pass:
  - `test_change_workflow_scope.py`, library integration (the plan said unit):
    CW-tl5v's scenario for `/tmp`, `/tmp/`, `/tmp/x/..` and `/`; a link leading to
    `/tmp` refused; a grant under `/tmp` admitted;
  - `test_change_workflow_config.py`: CW-h2zt's scenario through `check config`,
    `config --json`, `config`, and `config load design`, each refusing naming the
    field and `/tmp`; `/tmp/` and `/` among the malformed tables (unit); a path under
    `/tmp` admitted, and the listing in both forms (library integration). The helper
    `_writes` no longer counts the private `/tmp` as writing a host path.
- [x] 11a.3 The review's drafts directory (D18; CW-m8wq's "A Codex review writes its
  final message"). `review.py` keeps making the drafts directory in the host's
  temporary directory and adds it to the review's scope as an engine writable path,
  so it is bound inside the private `/tmp` at its own path. Verify, library
  integration in `test_change_workflow_review.py` through real bubblewrap with the
  Codex harness doubled by a program writing its `-o` file: the draft written
  inside reaches the transcripts after the run, and the drafts directory is gone.
  Done: once the drafts directory exists, `run_review` widens every scope of the run
  by it, from the engine (`Confined.writing`, `Scope.writing`). External-process
  integration through real bubblewrap (the plan said library integration), Codex
  doubled, passing:
  `test_a_codex_reviewers_final_message_written_inside_is_the_review_published` — the
  drafts directory, made under `/tmp` itself, is bound at its own path, the draft
  written inside is the review published, and the directory is gone after. A refused
  draft's move into the transcripts stays the existing unit tests'.
- [x] 11a.4 Codex in a confined review (D13; CW-t6mb; 48 F1). A confined review runs
  Codex without its own sandbox — `--sandbox danger-full-access` on `exec`, and
  `sandbox_mode="danger-full-access"` on `exec resume` — and an unconfined one keeps
  `read-only` in both; `codex.py`'s module docstring says which and why. Verify:
  - unit, `test_change_workflow_harness.py`: both commands, fresh and resumed, for a
    confined and an unconfined launch (CW-t6mb's two scenarios);
  - library integration through real bubblewrap with a Codex double that runs
    `git rev-parse --show-toplevel` and `scripts/change-workflow run pre-commit
    <change>`: both reach the system's Git through the engine's `git`;
  - a real `codex exec` under the engine's review scope, running `git rev-parse` and
    `run pre-commit`, where the owner grants this session `~/.codex` (`WRITE=~/.codex`);
    without the grant the note says so, and the round's review, on Codex, is its
    first real run (design, "Implementation cadence").
  Done: `codex.command` and `codex.resume_command` take `confined`; `_codex_attempt`
  passes whether the run's sandbox confines it. Tests pass:
  - unit: CW-t6mb's two scenarios, fresh and resumed, and the review's wiring
    (`danger-full-access` under `NO_SANDBOX`'s confining probe, `read-only`
    unconfined);
  - external-process integration through real bubblewrap (the plan said library
    integration):
    `test_a_confined_codex_reviewers_git_commands_reach_the_systems_git`, a Codex
    double's `git rev-parse --show-toplevel` and `run pre-commit` each printing the
    checkout's root, the check on the line's `invoked`;
  - a real `codex exec` (codex-cli 0.157.0, `gpt-6-sol`, effort low), launched by a
    script of the session's own, not kept, through `sandbox.launch` with the review's
    resolved scope, `codex.command(..., confined=True)`, and a run key, nested in this
    session's sandbox granted `~/.codex` (`WRITE=~/.codex`): it exited 0, Git printed
    the repository's root, `run pre-commit probe` passed and was kept under the run
    key, and the final message reached the draft on the host; observed in the
    session, not reproducible from the repository. A first attempt under `/tmp` ended
    "Not inside a trusted directory" (D13's limit), so the throwaway repository sat
    under `~/.cache`, removed after.
- [x] 11a.5 The Codex review's run key (D13, D2, D5, D7; CW-w3oa; 48 F3). Each Codex
  review attempt runs with an engine run key in its commands' environment, distinct
  from the starting session's id and from Codex's thread id; the engine's `git`
  keeps a refused push under it and `run` keeps the reviewer's checks under it; the
  review's line reads its invocations and refused pushes by that key, as it reads a
  Claude reviewer's by its session. Verify, library integration in
  `test_change_workflow_review.py` and `test_change_workflow_sandbox_git.py`: a
  Codex double that runs `git push` and `run pre-commit` leaves the refused push in
  the line's `refusals` and the check among its invocations (CW-w3oa's "A Codex
  reviewer pushes"); the starting session's line holds neither.
  Done: each Codex attempt makes a key of its own, `review-codex-<hex>`, passed to
  Codex's runner (`CodexRunner`'s third argument); `run_review` adds each to the
  `run_keys` list `_review_and_log` gives it, and the line takes what was kept under
  the Claude reviewer's session and under each key, then drops them. `codex.run`
  gives the key as `CLAUDE_CODE_SESSION_ID`, as `around.Around.environment` does for
  actions and hooks, so `run`, the guarded push and the engine's `git` keep under it
  unchanged. Tests pass:
  - external-process, `test_change_workflow_harness.py`: Codex's runner withholds the
    starting session and gives the key;
  - library integration, `test_change_workflow_review.py`: a draft and its correction
    under two distinct keys, the line taking what each kept;
  - external-process through real bubblewrap: CW-w3oa's "A Codex reviewer pushes"
    (the refused push on `refusals` as `git`, `run pre-commit` on `invoked`, the
    starting session's record empty, nothing on the remote), and, in
    `test_change_workflow_sandbox_git.py`, a refused push kept under the key.
- [x] 11a.6 The `[models]` comment of `.agents/workflow.toml` says the review runs on
  Codex, which a confined review runs without its own sandbox, falling back to Claude
  (D13). The configuration is protected: this task is the orchestrator's, on the
  owner's word before the section's session starts, and the session commits it with
  the section. Verify: `scripts/change-workflow check config` passes.
  Done. The orchestrator's edit was in the worktree, as the task gives it, and is
  committed with the section; `check config` passes.
- [x] 11a.7 What the delta now states of the built behaviour, each proven by a test
  that names its scenario or, where one exists, checked to name it (D6, D19, D20,
  D21; CW-q7ub, CW-r6kd, MCW-s4bx):
  - check 6 as built (D6; 48 F4): a remote unreadable at either end unchecked, and a
    protected branch's tip compared with the run's commits — the existing
    `test_change_workflow_invariants.py` cases named for CW-q7ub, one added for an
    unreadable remote where none exists;
  - CW-r6kd's "A clone's settings file is a link" (D20): the external-process test
    11.6 added, named for the scenario;
  - MCW-s4bx's "Design validates the change" (D21): the scope test of 11.1 extended
    to `~/.npm` for design.
  D19 changes no code. Verify: those tests pass.
  Done, all passing: `test_change_workflow_invariants.py`'s protected-branch tests
  name CW-q7ub's comparison with the run's commits, the unreachable-remote test the
  end, and `test_a_remote_unreadable_at_the_start_is_not_checked` is added (library
  integration); 11.6's bubblewrap test is named CW-r6kd's "A clone's settings file is
  a link"; MCW-s4bx's "Design validates the change" names the tool-state test holding
  `~/.npm` writable.
- [x] 11a.8 Verification point, completing 11.6: the whole scripts suite (`-rs`, no
  skip on this machine); `make check-agent-skills`; `make check-comment-hygiene`;
  `scripts/change-workflow run pre-commit sandbox-unattended-workflow-steps`, whose
  `make validate-local` in this session's own sandbox may fail only on the
  bare-metal ledger suite's "unsafe ancestor", recorded as such; and `make
  validate-local` run inside the change's sandbox launched from this session's,
  through `sandbox.launch` with implementation's resolved scope, passing, the
  ledger suite among its suites — the command and its result recorded in the note.
  End-to-end: none; no scenario exercises the workflow's tooling, and none is owed.
  Done, on the tree `3d0f3fb2b860`, which differs from what this section commits only
  by this note:
  - `make validate-local` inside the change's sandbox launched from this session's,
    through `sandbox.launch` with `config.load(root).scope("implement", root)`, a
    script of the session's own running `sh -c "stat -c 'tmp %u %a' /tmp; echo
    TMPDIR=$TMPDIR; exec make validate-local"`: unconfined `None`, nested; `/tmp` the
    owner's, `700`, `TMPDIR=/tmp`; local evidence for the tree PASSED (tree before,
    dist-clean, check-packaging, `make test` in 990 s, tree after), the bare-metal IaC
    suite 126 passed and 10 deselected, the scripts suite 3558 passed, none skipped.
    Evidence: `.snapshot/evidence/3d0f3fb2b8607055b540dbbb2f5f4475fb789c20/local/20261120T003746.321024Z`;
  - `scripts/change-workflow run pre-commit sandbox-unattended-workflow-steps` in this
    session's own sandbox, which binds the host's `/tmp`: `after-functional-change`
    passed, the locks unchanged; `pre-commit` passed; `pre-commit-functional` failed
    only as foreseen, the ledger suite 44 passed and 82 errors at setup, "unsafe
    ancestor" (attempt `20261120T005539.406611Z`);
  - the whole scripts suite with `-rs`: 3550 passed, none skipped, before the
    fresh-context fixes; after them, the nested run's 3558;
  - `make check-agent-skills`, `make check-comment-hygiene`, `check tasks`, and `check
    config` pass. `run test-before` was not run: the section's tests were uncommitted.
  A new test launching the real sandbox with its checkout under pytest's `/tmp` reads
  the test's directory through `change_workflow_fixtures.reading` or
  `with_test_directory`, or its scope must write what it reads.

  Fixes of the round's triage (review 62, orchestrator records 58 and 64, and the
  sections' handoffs; the dispositions are in the triage records), outside the
  plan's tasks, each named by the section it concerns:
  - Check 6 (section 5; 64 R1): a moved change branch is a violation only when its
    tip is a commit made in the run and not the guarded push's last
    (`invariants._remote_violations`; D6, CW-q7ub's "The owner opens the round view
    during a review").
  - The protected check (section 2; 62 F1): `_Checkout.protecting` compares an entry
    and each protected entry as written and where their links lead (D8, D12, CW-h2zt,
    CW-tl5v).
  - The review's scope (sections 2 and 11; handoff 11a.8): the review writes
    `~/.cache` from the engine and the repository's `writable.common` entries outside
    its checkout (`graph.STEP_DEFINITIONS`, `config.repository_writable`,
    `scope.outside_checkout`; D5, D12, D21, CW-m8wq, CW-h2zt, MCW-s4bx's "A review
    runs the repository's checks"). A checkout lying under `~/.cache` would be
    writable to its review: not guarded, as no clone is made there.
  - The gate for the sandbox tests (sections 3, 4 and 7; 62 F2): every test launching
    real bubblewrap asks for `conftest.sandbox_runs` through
    `change_workflow_fixtures.needs_bwrap`, skipped where the probe fails and failed
    there under `SANDBOX_REQUIRED=1`, which `tests.yml`'s packaging job sets after
    installing bubblewrap and lifting the runner's AppArmor restriction on
    unprivileged user namespaces.
    Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — `make
    test-deployment-packaging` under `SANDBOX_REQUIRED=1`, its log showing the change
    workflow's sandbox tests passed, none skipped.
  - The skills (section 10; handoff 10.5, 58 R3): `change-merge` stops an unattended
    merge before merging when the landing branch changed a protected path, and
    continues one the orchestrating session started after that stop;
    `change-orchestrate` brings that merge in outside the sandbox on the owner's word,
    and reads a denial by the harness's own guard as a finding by its target or
    neither (D7, D15, CW-svng).
  - Documents only: D2 (two routes around the engine's `git`; no upstream after a
    violation, CW-59c7), D4 (`--unshare-pid`), D5a and CW-m8wq (an adapter's state
    file mounted alone), D13 (`~/.claude`'s other contents, and Codex's trusted
    directories, recorded as limits); the permanent indexes and companion naming the
    review's common paths.
  Tests pass: library integration in `test_change_workflow_invariants.py` (the round
  view's move and the owner's commit pass; a run's commit on another remote's change
  branch found), `test_change_workflow_scope.py` (links into or under protected
  entries refused, a link to a directory holding a protected file admitted; the
  review's `~/.cache`), and `test_change_workflow_config.py` (a linked `[sandbox]`
  entry refused; the review's common paths only those outside its checkout; every step
  writing the tool state and `~/.cache/uv`); the four files launching real bubblewrap
  under `SANDBOX_REQUIRED=1`, none skipped; and the gate, by a probe forced to fail
  through a pytest plugin of the session's own, not kept (each sandbox test erroring
  under `SANDBOX_REQUIRED=1`, skipped without). The nine new or changed tests of the
  first three files all failed against `de2a55c2c` in a throwaway worktree, the last
  only on its violation's new wording. `make check-agent-skills` and `make
  check-comment-hygiene` pass. The fresh-context check's findings were all fixed;
  declined: guarding `~/.cache` against a checkout beneath it.
  `scripts/change-workflow run pre-commit sandbox-unattended-workflow-steps`, in this
  triage's own sandbox, the first step the engine launched with the private `/tmp`
  (`/tmp` the owner's, `700`, `TMPDIR=/tmp`), on the tree `7a4bb1830890`, which differs
  from what the fixes commit only by this paragraph: `after-functional-change` passed,
  the locks unchanged; `pre-commit-functional` passed — local evidence PASSED (tree
  before, dist-clean, check-packaging, `make test` in 1010 s, tree after), the
  bare-metal IaC ledger suite 126 passed and 10 deselected with no "unsafe ancestor",
  the scripts suite 3566 passed (attempt `20261120T093450.074945Z`); `pre-commit`
  passed, strict OpenSpec validation and `make check-repository` among it. So the
  ledger suite passes in a step's own sandbox, unnested. An earlier run failed the
  graph's test still asserting the review wrote no `~/.cache`; it was corrected before
  this run.

## 11b. Closeout's returned fix: a test docstring citing a design decision

Delivers the one fix closeout's comment hygiene (12.1) returned: a docstring the
change added names `D15`, a decision of this change's `design.md`, which leaves with
the archive (repository obligation: `docs/guidance/workflow/change-references.md`;
`docs/guidance/engineering/comments.md#comments-describe-the-current-system`). File:
`scripts/tests/test_change_workflow_harness.py`.

- [x] 11b.1 Drop the `D15: ` prefix from the docstring of
  `test_the_unattended_prompt_is_one_harness_neutral_paragraph`, so it opens "The
  prompt says the step runs in a sandbox scoped to it, …", the rest unchanged, as the
  owner directed the return. Verify: a search of the comments and docstrings the
  change added under `scripts/` since the landing branch finds no decision id (`D`
  and a number, with or without a letter, before a colon or in parentheses).
  - Done: the docstring opens "The prompt says the step runs in a sandbox scoped to
    it, what a refused write means, …", its lines rewrapped, its words otherwise
    unchanged. The search, over the lines `git diff 024f3a039 -- scripts/` adds
    (`024f3a039` the merge base with `origin/dev`), finds no `D` and a number before a
    colon or in parentheses, and none at all as a bare word.
- [x] 11b.2 Verification point: `test_change_workflow_harness.py` (unit) passes; `make
  check-comment-hygiene` passes; `scripts/change-workflow run pre-commit
  sandbox-unattended-workflow-steps` passes. End-to-end: none; no scenario exercises
  the workflow's tooling, and none is owed.
  - `make test-release-tooling TESTS=scripts/tests/test_change_workflow_harness.py`
    (unit): 20 passed. `make check-comment-hygiene` passed; it catches change names,
    not decision ids, so 11b.1's search is what shows none remains.
    `scripts/change-workflow run pre-commit sandbox-unattended-workflow-steps` passed,
    on the tree `156fa2df119a`, which differs from what this commit holds only by this
    note: `after-functional-change` passed with the locks unchanged;
    `pre-commit-functional` passed, local evidence PASSED (dist-clean, check-packaging,
    `make test` in 1014 s; attempt `20261120T115512.852114Z`); `pre-commit` passed,
    strict OpenSpec validation and `make check-repository` among it. No test changed in
    behaviour, so no test-before run applies. End-to-end: confirmed none, and nothing
    is owed by validation. A fresh-context check of the diff found no breach and no
    overstated claim; it noted only that the docstring now cites no requirement id,
    which "State the rule locally" does not ask for. Handoff: 12.1 can be run again from
    the start; nothing else in closeout was touched.

## 12. Closeout

The workflow's closeout parts (`docs/guidance/workflow/closeout.md`), in order, with
this repository's own parts (`openspec/README.md#this-repositorys-closeout-parts`) at
its seventh position. Closed out 2026-11-20 at `e71e69a47`, after 11b's fix.

- [x] 12.1 Comment hygiene — run `make check-comment-hygiene` and read the comments and
  docstrings the change added under `scripts/` for history wording or a change
  reference; anything to rewrite returns the change to implementation.
  - **Confirmed (closeout, 2026-11-20, after 11b), at `e71e69a47`.** `make
    check-comment-hygiene` passed. The engine package's added `#` comments, read
    in full, describe the current system; a search of every line
    `git diff 024f3a039 HEAD` adds under `scripts/`, `.agents/` and `.claude/` finds no
    decision id (`D` and a number), principle id, review finding id or handoff
    number. The one docstring the earlier attempt below found was fixed in 11b.
  - **Returned to implementation (closeout, 2026-11-20).** `make check-comment-hygiene`
    passed (no change id, task number, or change name outside `openspec/`). Reading the
    comments and docstrings the change added under `scripts/` against `dev`
    (`024f3a039..46da89c82`), the engine modules' 135 added comments describe the
    current system, and their requirement ids (CW-…) are permanent ones. One docstring
    names a decision of this change's `design.md`:
    `scripts/tests/test_change_workflow_harness.py:176`,
    `test_the_unattended_prompt_is_one_harness_neutral_paragraph`, opens
    `"""D15: the prompt says …`. `D15` points into a change document that leaves with
    the archive, against `docs/guidance/workflow/change-references.md` and
    `docs/guidance/engineering/comments.md`'s "Comments describe the current system".
    The mechanical check does not catch decision ids. Fix: drop the `D15: ` prefix so
    the docstring opens "The prompt says the step runs in a sandbox scoped to it, …",
    or cite CW-4yhk, the requirement the prompt meets, if a citation is wanted. That is
    a code edit, so closeout stopped here and returns the change to implementation for
    a fix round. No other part was started after 12.2.
- [x] 12.2 Import placement — check the imports the change added in `scope.py`,
  `sandbox.py`, `sandbox_git.py`, `invariants.py`, `propose.py`, `codex.py`,
  `review.py`, and the edited modules;
  one to move returns the change to implementation.
  - `make check-local-imports` passed ("every import the change adds inside a
    function since dev gives its reason"). The diff `024f3a039..46da89c82` under
    `scripts/` adds no import inside a function. Nothing to move. Rerun after 11b and
    the merge of `dev` (`e71e69a47`): passed again.
- [x] 12.3 Documentation compliance — check D1 to D21 and the cadence against
  `docs/guidance/workflow/openspec-documentation.md` and
  `openspec/README.md#documentation-placement`, and each permanent document written
  for the current state, with no wording relative to the change.
  - Each of D1–D21, D5a–D5c and P1–P9 has its home by the placement tables: behaviour
    in the two specifications (through the archive), rationale, boundaries and limits
    in the companions, operation in the handbook; none is cross-system, so
    `ARCHITECTURE.md` owes nothing. The cadence has no permanent home. Every permanent
    document written was read for wording relative to the change; a search of the
    added lines for "now", "no longer", "formerly", "replaced" and the change's name
    finds none but behaviour ("replaced by rename"). Promotion also found three
    untouched requirements naming the step table, added to the delta (12.9, D16).
- [x] 12.4 Narrative compression — shorten sections 1 to 11a's notes to final behaviour,
  evidence, deferrals, and destinations, moving rationale into `design.md` first.
  - Sections 1–11a's notes cut to final behaviour, evidence, deferrals and open
    items (tasks.md 2222 → 1527 lines); task text, intros, 11b and 12 untouched;
    `scripts/change-workflow check tasks` passes. Rationale the notes held that
    `design.md` lacked moved to its "Settled during implementation", with the
    consequences noted and not acted on.
- [x] 12.5 Roadmap currency — record that no goal of `docs/development/ROADMAP.md` is
  affected: the change serves the lesser goal "Make the change workflow a tool any
  repository can adopt" in `openspec/changes/README.md`.
  - No goal of `docs/development/ROADMAP.md` is affected; recorded in the promotion
    record.
- [x] 12.6 Campaign index currency — in `openspec/changes/README.md`: the change's row
  (status and notes); the lesser goal's "Current state", its paragraph on the step
  table's allowlist and its sentence on the exemptions this change owns rewritten for
  the sandbox; the gap "Unattended permissions are allowlists of this repository's
  commands" removed as closed. Leave dependents' `Depends on` for archive cleanup. Run
  `make check-change-index`.
  - Row: `in closeout`, notes rewritten. "Current state": the contract's test reads
    the make fragment alone; the configuration declares the sandbox's additions; the
    allowlist paragraph rewritten for the sandbox; the harnesses' paragraph for the
    adapters and Codex inside the engine's sandbox. The closed gap removed; the
    harness adapters' gap reworded for the internal adapters (its owner and row
    unchanged). Dependents' `Depends on` left for archive cleanup. `scripts/change-workflow
    check index` passes.
- [x] 12.7 Packaging — `scripts/change-workflow run pre-archive
  sandbox-unattended-workflow-steps` (`make check-packaging`, `make
  check-architecture-change`), and `make check-agent-skills`, since the change
  touched `.agents/` and `.claude/`.
  - `scripts/change-workflow run pre-archive sandbox-unattended-workflow-steps`
    passed at `e71e69a47` (`make check-packaging`; `make check-architecture-change`:
    the change owns no architecture row). `make check-agent-skills` passed.
- [x] 12.8 End-to-end pipeline — record the run the latest passing validation names,
  its result, the commit it describes, and that no scenario exercises the workflow's
  tooling.
  - From validation 94, the latest passing, of `e71e69a47` — the pre-closeout `HEAD`
    this closeout commit builds on, changing only inert paths: pipeline run
    44743452762 succeeded (e2e-vm 444 passed, e2e-bare-metal 249, e2e-apicredits 4).
    No scenario exercises the workflow's tooling; the change's evidence is the local
    kind (`make test`, 1018 s, attempt `20261120T130125.711971Z`) and the owed
    `tests.yml` job: §11a owed `test · test-deployment-packaging` under
    `SANDBOX_REQUIRED=1`, which passed in run 44743459934 (3578 passed, 1 skipped;
    under that variable the bubblewrap-gated sandbox tests fail rather than skip, so
    the skip is none of them — it is almost certainly the Codex confinement test,
    `test_codex_runs_in_the_reviews_scope`, which skips where Codex is absent, as on
    the runner, and which passed in the local kind at the same tree, 3579 passed with
    no skip; closeout review 96 F2). Helm passed too. No commit waiver was needed.
- [x] 12.9 Promotion — write, beside the deltas the archive merges into
  `openspec/specs/change-workflow/spec.md` and `market-change-workflow/spec.md`:
  - `openspec/specs/change-workflow/index.md`: the entries 1.1 added, their summary
    lines checked against the requirements as implemented, CW-x3pf's, CW-m8wq's,
    CW-r6kd's, CW-h2zt's, CW-t6mb's and CW-w3oa's against the delta as revised after
    the return and review 48; summary lines revised for
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
    content, the forgeable marker and open reads; the private `/tmp`, `TMPDIR`, and
    the host's `/tmp` hidden from reads (D17, D18); paths mounted where their symlinks
    lead (D20); the three unguarded names of protected paths as boundaries of the
    threat model (D19); "Pushing is guarded, never repaired"
    (D2); "Its parts" (the scope, sandbox, sandbox `git`, invariants, adapters, and
    `propose` modules; D11); "A step run's life" (the probe, the recorded state, the
    seven checks, check 6 read by listing each remote; D6); "Interactive runs record their own outcome" (D9); "Models are
    policy, with no same-vendor fallback" (D13, P6: a confined Codex review without
    Codex's own sandbox, an unconfined one in it, and the Codex review's run key); "A prerequisite is proposed apart
    and halts its dependent" (D5b); "Validation observes a committed slice" (D5c);
    "History lives in the owner's workspace" (the engine's copy); "A repository's
    configuration" (D12); "The command and its tiers" (`propose`, `--write`); "A
    change's records carry one format version" (P9, D16); "The engine's own
    assumptions", under "What an adopting repository provides" (the step table's row
    removed, `bwrap` and the sandbox `git` added, the harnesses' commands named in
    `claude_code` and `codex`, and the overflow uid: inside the sandbox only the
    owner's uid is mapped, root-owned paths showing as 65534; D17);
    "Current limits" — the unchecked configuration and the step table's place removed
    as closed, the forgeable marker and Read reaching any file removed as retired.
  - `openspec/specs/market-change-workflow/README.md`: "Current limits" (the container
    per change's trigger "when unattended steps are to be sandboxed from the owner's
    files" revised to the sandbox as built), checking the sections 10.2 and 11.4
    wrote: "How this repository provides the workflow's roles" naming `~/.npm` (D21),
    and "The engine's own assumptions" a clone's linked settings (D20).
  - `docs/change-workflow-handbook.md`: "Interventions" (grants as `WRITE=` and
    `--write`, refusals, unconfined runs, `propose`), "The engine" and "Customization"
    (the step table gone, `[sandbox]`).
  - The design-promotion record in `design.md`, a row for each of D1 to D21, D5a,
    D5b, and D5c, and the cadence's "no permanent destination" with its reason, as
    the proposal's "Knowledge to promote" gives them.
  Run `make check-spec-index CHANGE=sandbox-unattended-workflow-steps`.
  - Written: both `index.md` (every listed summary line revised against the
    requirements as built; CW-op72, CW-tax4, CW-mzyz's too; "### Permissions" renamed
    "### What a step may do", no citation naming it; retired ids checked; MCW-5tgp and
    MCW-s4bx); `change-workflow/README.md` (the restrictions section rewritten, and the
    sections the task lists, with Current limits: the unchecked configuration, the
    step table and the forgeable marker's bullets removed, Read reaching any file
    retired into the restrictions section, the unconfined, adapter and name limits
    added); `market-change-workflow/README.md`'s Current limits; the handbook's
    Interventions, The engine and Customization; both specifications' Evidence, by
    hand, since no delta carries it. Added to the delta as MODIFIED: CW-op72, CW-tax4,
    CW-mzyz, which still named the step table (D16). Design-promotion record written.
    `make check-spec-index CHANGE=sandbox-unattended-workflow-steps` passes.
- [x] 12.10 Guidance placement — confirm no file under `docs/guidance/` changed, or
  check each that did against the layer test; then `make check-guidance`.
  - The change edited one guidance file, `docs/guidance/repository/test-targets.md`
    (implementation dropped its step-table clause; a repository rule on its test
    targets, in place). Closeout touched no guidance. `make check-guidance` passes.
- [x] 12.11 Documentation citations — `make check-doc-citations
  CHANGE=sandbox-unattended-workflow-steps`, resolving every match; then
  `scripts/change-workflow openspec validate sandbox-unattended-workflow-steps
  --strict`.
  - `make check-doc-citations CHANGE=sandbox-unattended-workflow-steps` passes; every
    heading anchor the edited documents and the promotion record cite was resolved by
    hand too. `scripts/change-workflow openspec validate
    sandbox-unattended-workflow-steps --strict`: valid.
- [x] 12.12 Archival — `scripts/change-workflow openspec archive
  sandbox-unattended-workflow-steps -y`, merging the deltas (no `--skip-specs`: no
  permanent `spec.md` was edited by hand); read each merged requirement once; point
  the row at the archive; `scripts/change-workflow run pre-commit
  sandbox-unattended-workflow-steps`.
  - Archived as `openspec/changes/archive/2026-11-20-sandbox-unattended-workflow-steps/`,
    the deltas merged: `change-workflow` 13 added, 20 modified, 3 removed, 10 renamed;
    `market-change-workflow` 1 added, 1 modified. Each merged requirement equals its
    delta, none is duplicated, and no other requirement changed. The row points at
    the archive; no other active change links its directory.
    `scripts/change-workflow run pre-commit sandbox-unattended-workflow-steps` passed,
    `scripts/openspec validate --specs --strict` among it.
