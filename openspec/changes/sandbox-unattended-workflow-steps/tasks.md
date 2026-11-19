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

- [x] 2.1 In `config.py`, read `[sandbox]`: `writable.common`, `writable.<step>` for a
  step of `graph.STEPS`, and `protected`, each a list of paths; refuse, naming the
  field, an unknown key, a wrong type, `writable.review`, an unknown step, a glob
  character outside a path's pattern form, and a writable entry that is or lies under
  a protected path — the engine's (`.agents/workflow.toml`, `.git/config`, the
  engine's `git`) or the configuration's own — while admitting a directory that
  contains one (D12; CW-h2zt, CW-w8ne). An absent table is every list empty. Verify:
  unit tests for each refusal, each naming the field, and for CW-h2zt's three
  scenarios.
  Done: `Configuration` gains `sandbox_writable` (by key), `sandbox_protected`,
  `repository_writable(step)` (`common` but for the review, then the step's own), and
  `scope(step, root, …)`.
  - "A glob character outside a path's pattern form" is read as two refusals: a
    pattern in a `~` or absolute entry, since patterns match the checkout's files,
    and any pattern in `protected`, which is mounted whole.
  - The protected test is `scope.protected_by`, the same one a grant's uses. It
    resolves `.git/` entries through Git and judges a pattern by its fixed part.
  - `check()` takes a `home` seam.
  Tests in `test_change_workflow_config.py`, all passing:
  - unit tests (`config.check` on text), each naming its field: the refusals, an
    absent table, `common` but for the review, and a home-relative protected path;
  - scenario 2 ("opens a protected path"), driven through `cli.main` in process.
    `check config`, `config`, `config --json`, and `config load design` each exit 1,
    naming the field and the protected path;
  - scenarios 1 and 3, library integration on a real Git checkout. They show the
    resolved scope only: `docs/` for design and not for planning, and `.agents/`
    writable with `.agents/workflow.toml` protected. Mounting it is section 3's.
  `scripts/change-workflow run test-before … --test
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
  `ScopedPath`s, each with its path, source, entry, and `create`.
  - `PROTECTED` is the engine's protected set: `.agents/workflow.toml`, `.git/config`,
    `/usr/bin/git`, and `/usr/lib/git-core/git`.
  - `.git/` resolves through `git rev-parse` to the Git directory and the common
    directory; `.git/<x>` through `--git-path`.
  - Patterns match the files `git ls-files --cached --others --exclude-standard`
    lists, through `records.inert`, now beside a public `records.is_pattern`. A
    README inside an ignored `.venv` is no match.
  - Every absent writable path is marked `create`, whatever its source, so the
    review's `.git/change-invocations/` and an absent `~/.cache` can be mounted.
  - Outside a Git checkout, `.git/` entries read lexically and patterns match
    nothing. Git that cannot run at all raises `ScopeError`.
  Tests in `test_change_workflow_scope.py` are library integration on a real Git
  checkout (the plan said unit), all passing:
  - design with the repository's `docs/`;
  - the review: only `.git/change-invocations/` and the temporary directory;
  - closeout: each README's directory, and the root from `AGENTS.md` alone, since
    the fixture has no root README;
  - `.agents/workflow.toml` protected inside a writable checkout;
  - the adapter's and the repository's sources;
  - a linked worktree's Git paths.
  `absolute` is a unit test.
- [x] 2.3 Grant parsing as `scope.py` takes it (D8; CW-tl5v): each value split on `;`,
  parts trimmed, empties dropped; a value with a glob character refused, naming it; a
  path that is or lies under a protected path refused, naming it; a directory
  containing one admitted, the protected path read-only inside; a file mounting its
  directory; an absent path marked to be created as a directory before launch. The
  command line takes it in section 8. Verify: unit tests for CW-tl5v's pattern
  scenario, a protected path, a protected ancestor, a file, and an absent path.
  Done: `grant_paths` splits values, and `granted`, called by `resolve`, refuses a
  pattern or a protected path, naming the value. Its protected set is the engine's,
  the adapter's, and the repository's.
  Tests: `grant_paths` is a unit test. The rest are library integration through
  `resolve` on a real Git checkout (the plan said unit), all passing:
  - CW-tl5v's pattern scenario: the scope is refused, naming the value. That nothing
    launches is section 8's;
  - a protected path, and an adapter's protected path;
  - a protected ancestor granted, with the protected file inside;
  - a file mounting its directory;
  - an absent path marked `create`;
  - `.git/config` refused in a linked worktree.
- [x] 2.4 `config` and `config --json` list each step's resolved scope — writable and
  protected paths, each with its source — the adapter's paths absent until section 6
  adds them (CW-o6kc). Verify: a library-integration test of `config --json` on a
  fixture repository declaring `writable.plan = ["docs/"]` finding planning's
  `openspec/` and `.git/` from the engine and `docs/` from the repository (CW-o6kc's
  scenario, but for the adapter's paths, which 6.5 adds).
  Done: `config --json` gains `scopes`, keyed by step, each with `writable` and
  `protected` lists of `{path, source, entry}` and `absent` where marked. `config`
  appends `scope.<step>.<writable|protected>` lines, shown from the root or `~`.
  `resolution` lists `sandbox.writable.<key>` and `sandbox.protected`. The help and
  the module docstring of `cli.py` say so.
  Test: `test_config_lists_each_steps_scope_with_each_paths_source`, library
  integration on a real Git checkout through `cli.main`, passing.
- [x] 2.5 Verification point: `test_change_workflow_scope.py` and
  `test_change_workflow_config.py` (unit, library integration); `run pre-commit`
  passes. End-to-end: none.
  Done:
  - `make test-release-tooling` on the scope, config, and CLI tests: 328 passed.
  - `make check-comment-hygiene` passes.
  - `run pre-commit`: its functional hooks pass, the relock, packaging, and every
    suite. Its `pre-commit` fails only `check-doc-citations`, on the six files
    sections 3 to 5 and 9 create, as section 1 recorded. One earlier run failed a VM
    storefront integration test this section does not reach,
    `test_delivery_recovery_loop.py::test_a_deal_waiting_for_its_start_is_claimed_re_checked_and_driven_at_its_start`.
    It passed in the next run.
  - Fresh-context check fixes:
    - comments that claimed later sections' mounting;
    - one protected test for the configuration and grants;
    - the `home` seam;
    - a raise where Git cannot run;
    - closeout's test proving `AGENTS.md`;
    - each reader's refusal asserted;
    - honest levels.
  Handoff:
  - Section 6: a file entry mounts its directory, so the adapter's `~/.claude.json`
    state file would make all of `~` writable. Section 6 needs a narrower form for
    it.
  - Section 8: `resolve` accepts grants for the review; nothing yet refuses them.
  - Closeout's scope here lists many nested directories under the root, which
    `AGENTS.md` already makes writable. Section 3 may collapse nested writable binds.

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
  Done: `sandbox.arguments(scope, program, binds)` renders the command in this order:
  - `bwrap --unshare-pid --ro-bind / / --dev /dev --proc /proc`;
  - each writable path `--bind`, shallower first, so none hides one inside it;
  - each protected path `--ro-bind`;
  - the caller's read-only `binds`, as source and destination pairs, which section
    4's `git` uses;
  - `--die-with-parent --`, then the program.

  `prepare(scope)` creates absent writable paths as directories. It creates absent
  protected paths as `{}` for `.json`, an empty file otherwise, or a directory for an
  entry ending in `/`.

  Two departures from the task's wording, for the triage to read:
  - Only protected paths inside a writable path are mounted, and created
    (`mounted_protected`). One outside every writable path is read-only under the
    root already. So design's scope mounts `.git/config` but not
    `.agents/workflow.toml`, and the review's creates no placeholder in a checkout
    it cannot write. Git's executables are left to section 4's binds.
  - `--unshare-pid` is added to D4's flags. With `--die-with-parent` alone, a
    background process the harness started outlives the launcher, against CW-x3pf's
    "end the session when the wrapper ends". With its own process namespace,
    bubblewrap's death ends the whole tree.

  Unit tests, on scopes built by hand, all passing:
  - the order for a design scope;
  - a checkout-wide scope mounting the configuration after the checkout;
  - each empty form, `.claude/settings.local.json` as `{}` among them;
  - no placeholder outside the writable paths.
- [x] 3.2 The probe: one trivial program run under `bwrap` before a launch, its
  failure — `bwrap` missing, user namespaces refused — returning the reason, and the
  launch then the program unconfined, with the reason for the wrapper's warning and
  `unconfined: true` (section 7 records it) (D10; CW-v5ny). Verify: unit tests with
  the probe doubled for both failures; a library-integration test that the real probe
  passes on this machine.
  Done: `probe(run)` runs `true` in the base sandbox. Its failure returns the reason:
  - not installed;
  - bwrap's own message, such as the uid map refusal;
  - another `OSError`;
  - an exit with no message.

  `launch(scope, program, binds, probing)` returns a `Launch` of the bwrap command,
  its mounts created. Where the probe fails, it returns the program alone with
  `unconfined` holding the reason, and creates nothing.

  Unit tests, all passing:
  - the probe's runner doubled for all four failures, and its command;
  - `launch` with the probe doubled both ways.

  A test of the real probe was dropped, since it could not fail: it was skipped
  exactly when the probe fails. The evidence that the real probe passes here is that
  3.3's tests ran and none was skipped (`PYTEST_ARGS=-rs`).
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
  external-process integration (`test-levels.md`), not library integration. Each runs
  a shell program in a scope resolved on a real Git checkout. All pass here, none
  skipped:
  - a write inside design's scope succeeds, and one outside fails "Read-only file
    system";
  - a write to `.agents/workflow.toml` fails read-only, and a rename over it fails
    "Device or resource busy";
  - CW-r6kd's `git config core.hooksPath` exits non-zero, "Device or resource
    busy", with `.git/config` unchanged;
  - CW-r6kd's absent `.claude/settings.local.json` cannot be written, and stays
    `{}`;
  - a file outside the review's scope is read;
  - the Docker socket carries traffic from inside: `GET /_ping` answers `OK`;
  - once the launcher is killed, every process inside dies, a background `sleep`
    included. This is waited on through the end of a pipe they all hold, not a
    pause. Run without `--unshare-pid` as a check, the test failed: the background
    `sleep` survived.

  `test-levels.md` puts such tests in a gate that fails on a skip. None exists, so
  on a machine without bubblewrap they skip silently under `make test`. Flagged for
  the triage: a gate, or a recorded exception.
- [x] 3.4 Verification point: `test_change_workflow_sandbox.py` (unit, library
  integration through real bubblewrap); `run pre-commit` passes. The note records
  whether a native Ubuntu install was at hand to run the probe on; where none was,
  `design.md`'s open question on AppArmor stays open. End-to-end: none.
  Done:
  - `make test-release-tooling` on the sandbox and scope tests: 43 passed, none
    skipped.
  - `run pre-commit`: its functional hooks pass, the relock, packaging, and every
    suite. The scripts suite runs the bubblewrap tests here. Its `pre-commit` fails
    only `check-doc-citations`, on the four files sections 4, 5, and 9 create.
  - No native Ubuntu install was at hand, only this WSL2 machine, so `design.md`'s
    open question on AppArmor stays open.
  - Fresh-context check fixes:
    - the probe described as what it is;
    - `--unshare-pid`;
    - real unit tests over hand-built scopes;
    - the tautological probe test dropped;
    - an event-driven death test;
    - Docker traffic;
    - the busy reason asserted;
    - the untested branches covered.
  Handoff:
  - Section 4 passes the engine's `git` as `binds`, over `scope.GIT_EXECUTABLES`.
  - Gaps the check named, outside P1 or for a later section:
    - Renaming the directory holding a protected mount, then writing a new file
      there, defeats the mount. Nothing after the run checks the configuration.
    - A protected settings file that is a symlink inside a writable directory
      mounts the symlink's target.
    - `[sandbox]` admits a protected directory containing a baseline writable path
      (`protected = ["~"]`), and the inner path stays writable. Section 2's check
      could refuse it.

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
  Done, as a module rather than an executable file: `change_workflow/sandbox_git.py`.
  Why the plan's form could not hold:
  - A program mounted at `/usr/bin/git` cannot find the engine's package by its own
    path.
  - A new file's mode cannot be set in this session: `chmod` has no rule, and Git
    applies a mode only on checkout.

  So `sandbox.py` mounts a short generated shell program over Git (4.2). It runs
  `sandbox_git.main` with the engine's Python, `-I`, from the engine's directory, and
  passes `$0`.
  - `subcommand` reads past Git's own options. `_VALUED` names those that take their
    value as the next argument. A dashed name such as `git-receive-pack` gives its
    subcommand.
  - `refusal` refuses a push under `UNATTENDED_RUN` without `common.GUARDED_PUSH`
    (`CHANGE_WORKFLOW_GUARDED_PUSH`).
  - `main` keeps a refusal as `{"hook": running.REFUSED_PUSH, "command", "error",
    "started"}`, with no change named. Otherwise it `execv`s `REAL_GIT` under the
    name it was run by.
  - Found while testing 4.3: Git's local transport runs `git-receive-pack`, a link to
    Git. Run as `git`, it broke a push to a local path. So the name Git was run by is
    kept.

  Unit tests in `test_change_workflow_sandbox_git.py`, all passing:
  - nine option forms found as a push and refused;
  - five other commands, among them `-C push status`, run;
  - dashed names;
  - the marker unset, and the guarded marker set.

  `test_a_refusal_is_said_and_kept_for_the_sessions_line` uses a real Git checkout
  for the invocations directory.
- [x] 4.2 `sandbox.py` binds the real `/usr/bin/git` at a path only `sandbox-git`
  names, then `sandbox-git` read-only over `/usr/bin/git` and `/usr/lib/git-core/git`
  (Git's exec path), both protected (D2, D4; CW-r6kd). Verify: library-integration
  tests through real bubblewrap on a repository with a bare remote: `git push`, `git
  push --no-verify`, `git -c core.hooksPath=/dev/null push`, and
  `/usr/lib/git-core/git push` are refused and nothing reaches the remote; `git
  status` and `git commit` work (CW-j4cs's scenarios).
  Done. `arguments(scope, program, *, git)` renders three mounts after the protected
  ones:
  - `--ro-bind /usr/bin/git /dev/change-workflow-git`, the real Git at
    `sandbox_git.REAL_GIT`;
  - then `--perms 0755 --ro-bind-data <fd>` over each of `scope.GIT_EXECUTABLES`.

  Why `/dev`: bubblewrap cannot make a mount point on the read-only root ("Can't
  mkdir parents …: Read-only file system", tried here), and the sandbox's own `/dev`
  is a fresh tmpfs. An overlay of `/usr/lib/git-core` also worked, but is heavier.

  `launch` writes `git_program()` into one `memfd` per mount and returns them as
  `Launch.fds`. `Launch` is a context manager that closes them. A caller passes them
  with `pass_fds`, and section 7's runner must too.

  The data mount copies the shell program at launch, so it needs no executable file
  on disk. The module it runs is read from the engine's directory at each call. Where
  the engine runs from the change's own checkout, a step writing that checkout can
  therefore change what its `git` refuses. That is outside P1, and no protected path
  covers the engine's package.

  Section 3's `binds` parameter had no other user, so it was removed. Section 3's
  tests now pass the descriptors.

  External-process integration tests (not library integration: they run bwrap, sh,
  and git), on a real repository with a bare `origin` the scope makes writable, so a
  refusal is not a read-only failure. All pass here, none skipped:
  - CW-j4cs's four pushes each exit 1 naming the refusal, `dev` on the remote
    unchanged, and the refusal kept with its command line;
  - `git commit` and `git status` work through the mounted program.

  As 3.3 flagged, nothing gates these tests on a skip. They join 3.3's in that
  question for the triage.
- [x] 4.3 `push.py` sets the guarded push's marker in the environment of the `git push`
  it runs, so `sandbox-git` lets it through, and, under a run, records each attempted
  push once Git returns — branch, remote, commit sent, Git's exit status — among the
  session's invocations; under a run it never passes `--set-upstream` (D2; CW-59c7).
  Outside a run nothing changes. Verify: library-integration tests: the guarded push
  through real bubblewrap reaches a bare remote and its record names the commit and
  status 0; a push Git fails after the pre-push hook passed is recorded with its
  failing status (CW-59c7's "An unattended push fails"); outside a run the owner's
  push sets its upstream as today.
  Done. `git push` always runs with `GUARDED_PUSH=1`, which matters only inside the
  sandbox. Under `UNATTENDED_RUN`:
  - the target's `set_upstream` is dropped;
  - `check` says the engine sets the upstream;
  - each push is kept as `{"hook": running.ATTEMPTED_PUSH, "command", "branch",
    "remote", "commit", "exit_status", "started", "seconds"}`, with no change named.

  Tests, all passing:
  - in `test_change_workflow_sandbox_git.py`, external-process integration: the
    guarded push, run as `scripts/change-workflow push` inside bwrap, reaches the
    bare remote and is kept with `HEAD` and status 0;
  - in `test_check_push_ready.py`, library integration on real Git through
    `push.main`: an unattended push sets no upstream and is kept; a non-fast-forward
    push after a passing `pre-push` is kept with Git's status, 1, after the
    `pre-push` entry.

  Outside a run, the existing upstream and keeps-nothing tests pass unchanged.
- [x] 4.4 After a session ends, before its line is written, the wrapper sets the
  branch's upstream outside the sandbox to the remote of the run's last successful
  guarded push of that branch, as its record names it, and sets none where no push of
  it succeeded (D2; CW-59c7's "An unattended run pushes a branch with no upstream").
  Verify: library-integration tests with the harness doubled pushing a branch with no
  upstream, and failing to.
  Done. `push.set_upstreams(root, invoked)` gives each branch with neither
  `branch.<b>.remote` nor `.merge` its own name on its last successful push's remote.
  `Wrapper._logged_turn` calls it with what the sessions kept, before
  `record_outcome`. A failure is printed and stops no line.

  Tests in `test_check_push_ready.py`, all passing, library integration on real Git
  and a bare remote. Two drive the wrapper, the harness doubled by a fake whose turn
  runs `cli.main(["push", "--remote", "origin"])`:
  - a design run's push leaves `origin/feat/change` as the upstream;
  - a rejected push leaves none.

  A third calls `push.main` and `set_upstreams` directly: a branch already tracking
  keeps its upstream after an unattended push to another remote. No test drives
  `check`'s new message, or a failure to set an upstream.
- [x] 4.5 Verification point: `test_change_workflow_sandbox_git.py` (unit, library
  integration through real bubblewrap), the push and wrapper tests above; `run
  pre-commit` passes. End-to-end: none.
  Done:
  - `make test-release-tooling` on the sandbox `git`, sandbox, push, wrapper, and
    scope tests: 196 passed, none skipped (`PYTEST_ARGS=-rs`).
  - `run pre-commit`: its functional hooks pass, the relock, packaging, and every
    suite. Its `pre-commit` fails only `check-doc-citations`, on the three files
    sections 5 and 9 create. The relock left the locks as committed.
  - A first run failed its "tree after" check: this session edited the worktree
    while the suites ran. Every suite had passed. The rerun, untouched, passed.
  - Fresh-context check fixes:
    - the false claim that the engine's `git` is fixed at launch;
    - `Launch`'s descriptor wording;
    - two overstated notes;
    - Git's status asserted as 1;
    - the skip gate flagged again.

    Declined: its reading that the push and wrapper comments describe a sandbox that
    no step yet launches in. The branch lands whole, and those comments describe the
    system it lands as.
  Handoff:
  - Section 7's runner starts the `Launch` command with `pass_fds=launched.fds`,
    inside `with launched:`.
  - Section 7.2 reads `REFUSED_PUSH` entries from the sessions' kept invocations.
    A Codex reviewer has no session id (`SESSION_ID` is withheld from it), so the
    sandbox's `git` keeps nothing for it. The review pushes nothing, but 7.2's
    "whatever the harness" needs a run-scoped key, or Codex given one.
  - Gaps for the triage, outside P1:
    - A plain alias naming `push` (`-c alias.p=push p`) passes as its alias's name.
    - An unknown Git option taking a separate value would be read as the
      subcommand.
    - The module the mounted program runs is the engine's, live (4.2).
  - Every Git call inside the sandbox now starts a Python process first (not
    measured). Watch for slowness in Git-heavy hooks once section 7 launches steps
    there.

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
  Done. `invariants.record(root, step, change, *, inert_paths, protected_branches)`
  returns a `Start` holding:
  - the commit and the branch;
  - the worktree as a tree object (`worktree_tree`) and the tracked paths, for
    checks 2 and 7;
  - the log's and the ledger's (`interventions.jsonl`) `Prefix`, a length and a
    SHA-256;
  - each `records.RECORD` file's digest;
  - `refs/stash`;
  - how many entries `HEAD`'s reflog holds, to tell a commit made in the run;
  - each remote's change branch and protected branches, from one `ls-remote`;
  - the change's delta capabilities, and the configuration's inert paths and
    protected branches.

  `worktree_tree` runs `git add --all` and `write-tree` through a copy of the index
  under `GIT_INDEX_FILE`, so the checkout's own index is untouched.

  Tests, library integration (the plan said unit) on a real checkout with a bare
  `origin`, both passing:
  - `test_the_state_a_session_starts_from_is_recorded`;
  - `test_reading_the_worktree_as_a_tree_leaves_the_checkouts_index_alone`: an edit
    and a new file are in the tree, and nothing is staged.
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
  Done. `invariants.check(root, start, invoked)` returns a `Violation(check, found)`
  per failure. The checks are named `history`, `unchanged`, `log`, `records`,
  `stash`, `remote`, and `closeout`.
  - Checks 2 and 7 diff the start tree against the tree at the end (`--no-renames`),
    so what is compared is what the run leaves, committed or not.
  - Check 6 reads every remote of the checkout with `ls-remote`, at the start and
    after. A remote unreadable at either end is skipped. This departs from the
    task's "after one fetch": a listing writes nothing to the checkout. The cost is
    that a protected branch is judged by its tip alone, so a commit of the run that
    another party has since built on is missed.
  - A protected branch's new tip counts as the run's when `HEAD`'s reflog gained it
    during the run. That holds whether the commit sits on a branch since deleted or
    on a detached `HEAD`. A commit someone else pushed, which a step fetched, is not
    the run's. A run that checks out such a commit would make it count, but check 1
    already stops that run.
  - Check 7 admits `records.inert`, `records.is_record`, and `archive_writes`: the
    change's own directory, active or archived; `openspec/changes/README.md`; and
    `openspec/specs/<capability>/spec.md` for each capability the change has a delta
    of.

  Library-integration tests in `test_change_workflow_invariants.py`, on a real
  checkout with a bare `origin`, all passing (22 with 5.1's two and the outcome's
  unit test):
  - CW-q7ub's four scenarios: an amend (`history`), a review's log line during a
    validation (passes), a run's commit pushed to `dev` (`remote`), and closeout's
    code edit beside a README (`closeout`, naming `src/main.py`). That such a
    closeout is logged stopped is a wrapper test, under 5.3;
  - a commit pushed to `dev` from a branch since deleted (`remote`);
  - CW-4yhk's relock (`unchanged`, naming `uv.lock`), and a validation that commits;
  - a stash, a rewritten record, a ledger edited mid-file, and a rewritten log;
  - a branch switched;
  - the change branch moved without a push record, or after a failed one;
  - another party's commit on `dev` fetched in;
  - an unreachable remote;
  - closeout's own writes and the archive's move (passes), and another change's
    documents or specification (`closeout`);
  - an ordinary implementation run passes every check.
- [x] 5.3 The wrapper records the state before every unattended session and runs the
  checks after it, whatever its outcome, before any action or hook after it; a
  violation logs the run `stopped`, its reason and `invariants` naming each, the
  step's message kept ahead, as `triage_outcome` and `landed_outcome` do, and the
  after-hooks do not run; the review runner does the same for its reviewer (D6;
  CW-f9le). `log.py` accepts `invariants`. Verify: library-integration tests with the
  harness doubled for CW-f9le's scenario and a passing run's line carrying no
  `invariants`.
  Done. `invariants.Invariants` holds one run's `begin()` and `violations(sessions)`.
  It reads the guarded push's records from the sessions' kept invocations, through
  the runner's own `invocations` seam. `Invariants.of(configuration, root, step,
  change, invocations)` builds it, for the wrapper and the review alike.
  - `_logged_turn` calls `begin()` after the before-actions, so their writes are not
    the session's. It checks after the attempts, whatever the outcome, before
    `_after_finished`.
  - `_after_finished` checks again after a session resumed for a failed after-hook,
    before the hooks run again.
  - A violation makes `invariants.stopped(outcome, broken)` the outcome, with the
    step's message ahead of the reason. It puts `invariants`, a list of `{check,
    found}`, on the line.
  - `run_review` takes `invariants`: `begin()` after `before-review`, and the check
    once the reviewer ends. A violation publishes nothing and raises `ReviewError`
    with `invariants` in its record. An interrupted reviewer's record carries any
    violation, and `_review_and_log` adds it to the reason.
  - `log.py`'s docstring names the field. The writer already takes any field beside
    the outcome, so no code changed there.
  - After a violation, the wrapper also skips setting the upstream (4.4). CW-f9le
    lets no action run after such a session, and that rule is read here to override
    CW-59c7's "once the session ends". A later push with `--remote` sets it. Flagged
    for the triage.
  - Outside the plan: `__init__.py`'s module list, which CW's "each module listed
    with its role" requires, gains `scope`, `sandbox`, `sandbox_git`, and
    `invariants`. Sections 2 and 3 had left the first two out.

  Library-integration tests on a real Git checkout, the harness doubled, all passing.
  In `test_change_workflow_wrapper.py`:
  - CW-f9le's scenario: a finished validation that edited `src.py` is logged
    stopped, `invariants` naming the file, the message starting with the
    validation's, and `after-validate` not run;
  - a passing run carries no `invariants`, and its hook runs;
  - a session resumed after `after-implement` failed, which rewrites a review record,
    is stopped before the hook runs again;
  - a closeout editing `src.py` is logged stopped, `invariants` naming it;
  - a run that exited 3 is checked too.

  In `test_check_push_ready.py`: a design run that pushed and then stashed is
  stopped, and no upstream is set.

  In `test_change_workflow_review.py`:
  - a reviewer editing a tracked file publishes nothing and is logged stopped with
    `invariants`;
  - one changing nothing is published.

  No test drives an interrupted reviewer that also broke an invariant.
- [x] 5.4 Verification point: `test_change_workflow_invariants.py`, the wrapper and
  review tests above (library integration); `run pre-commit` passes. End-to-end:
  none.
  Done:
  - `make test-release-tooling` on the invariants, wrapper, review, around, push,
    sandbox `git`, and CLI tests: 478 passed.
  - `run pre-commit`: its functional hooks pass, the relock, packaging, and every
    suite. Its `pre-commit` fails only `check-doc-citations`, on `propose.py`, which
    section 9 creates.
  - A first run also failed `check-comment-hygiene`. Test fixtures named
    `tasks.md` and `01-design.md`, which its pattern refuses even as fixture names.
    They were renamed and the run repeated.
  - Fresh-context check fixes:
    - `__init__.py`'s module list;
    - the runner's `invocations` seam passed through;
    - `records.git_contains` and `git_remotes` reused;
    - one `Invariants.of` for both runners, and the unused seams dropped;
    - no upstream set after a violation;
    - commits made in the run read from `HEAD`'s reflog;
    - a real test that the index is untouched;
    - closeout logged stopped through the wrapper;
    - the departure from "one fetch" marked;
    - the test levels named.

    Declined:
    - The detached-`HEAD` start, which skips the branch checks. It matches the
      guarded push's own reading of "the change's branch", and no step starts
      detached.
    - Walking a protected branch's history to find a run's commit built over. That
      needs the fetch this check does without.
  Handoff:
  - Every run in a Git checkout now lists each remote twice (`ls-remote`). Offline,
    the remote check is skipped, and the run goes on.
  - Check 6 knows only this run's sessions' pushes. A validation that pushes beside
    a review would read, to the review, as the change branch moving without a push
    record. Validation pushes only an unpushed `HEAD`, which is rare. If it appears,
    give the review the validation's records or exempt the change branch for it.
  - Section 7 launches the session inside the sandbox between `begin()` and
    `violations()`. Nothing here depends on the launch.
  - The test environment inherits `CHANGE_WORKFLOW_UNATTENDED` when this session runs
    unattended. `push.main` tests that rely on the default `environ` then behave as
    under a run. Those here pass either way.

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
  Done. The adapters are three modules beside `harness.py`:
  - `claude_code.py` and `codex.py`, one per harness, each with its `ADAPTER`;
  - `adapters.py`, holding them by harness;
  - `harness.py` keeps what they share: `Model`, `Adapter`, `Runner`,
    `unreachable`, `missing_program`, `UNATTENDED`, and `refused`.

  `Adapter` holds the harness, its `steps`, its `state` directories, its
  `state_files`, its `protected` paths, and its `rules`.
  `claude_code.command(prompt, schema, model, *, session, system)` gives:
  - `--permission-mode dontAsk --setting-sources project`;
  - `--settings '{"sandbox": {"enabled": false}}'`;
  - the schema, the system prompt, and `--session-id` or `--resume`;
  - `--allowedTools`, then `--disallowedTools "Bash(git push*)"`.

  Departures, for the triage:
  - "Every tool allowed" is `claude_code.TOOLS`, each built-in tool a step works
    with allowed whole. Tools that wait for a later turn stay denied: Monitor,
    ScheduleWakeup, and the cron tools. Claude Code takes no wildcard rule this
    session could confirm.
  - `~/.claude.json` is mounted alone, not as its directory. D5a's directory mount
    would make all of `~` writable, against P3. That is section 2's handoff. A
    `ScopedPath` gains `alone`, `scope.resolve` gains `adapter_files`, and
    `sandbox.prepare` creates an absent one as `{}`. This session could not run
    Claude Code under bubblewrap: the call was denied. Claude Code replaces the
    file by rename, which fails inside the sandbox. The only evidence of what
    follows is the strings of its binary: a failed config save is logged ("Failed
    to save config with lock") and caught. If so, the cost is lost state, not a
    stopped run. The first unattended run after section 7 shows it. This departs
    from CW-m8wq's "A file or pattern entry MUST mount each match's directory" and
    D5a, which the triage should amend or overrule.
  - Nothing calls `command` yet; section 7 moves the wrapper onto it. Until then
    the step table's form is `claude_code.table_command`, with `anchored`.
  Unit tests in `test_change_workflow_harness.py`, all passing:
  - the command for a fresh run;
  - the command for a resumed run;
  - the declared state, settings, steps, and rule.
  `claude_code.run` and `codex.run` keep their earlier library-integration tests.
- [x] 6.2 The Codex adapter: the review's commands as today, `--sandbox read-only` kept
  inside the engine's sandbox; its writable state `~/.codex`; its protected path
  `~/.codex/config.toml`; the review only (D13). Verify: unit tests of the commands
  and paths; a library-integration test launching `codex --version` through real
  bubblewrap in the review's scope, where Codex is installed, else skipped saying so;
  if the two sandboxes cannot nest, the adapter drops `--sandbox read-only`, and the
  task's note records it.
  Done. `codex.command`, `codex.resume_command`, `Progress`, and `run` moved from
  `harness.py` unchanged. The two sandboxes nest, so `--sandbox read-only` stays.
  Tests, all passing:
  - unit tests in `test_change_workflow_harness.py` of both commands, and of the
    state, settings, review-only steps, and no rules;
  - in `test_change_workflow_sandbox.py`, external-process integration, not library
    integration as planned: it runs bwrap and codex. It ran here, not skipped. In
    the review's scope with Codex's adapter paths and a test home:
    - `codex --version` runs;
    - `codex sandbox -- cat src/main.py` starts Codex's own sandbox inside the
      engine's and reads through it. That is the sandbox `codex exec --sandbox
      read-only` starts. `codex exec` itself, which needs a model, is not run;
    - a write under `~/.codex` succeeds, and one to `~/.codex/config.toml` fails as
      a read-only file system.
  - Found here: Codex's sandbox keeps a lock under `/tmp`, so it needs the system's
    temporary directory writable, which the review's baseline gives.
  - As 3.3 and 4.2 flagged, no gate fails on this test's skip where Codex or
    bubblewrap is missing.
- [x] 6.3 Each adapter reads refusals from its run's events: Claude Code's tool results
  in its stream, Codex's command output, each matching "Read-only file system" or
  "Device or resource busy", recorded with its tool, command or path, and error;
  Claude Code's denials stay read as today (D7; CW-w3oa, CW-k5mk). Verify: unit tests
  on recorded stream fixtures for CW-w3oa's scenario, a busy protected file, a denial,
  and a tool result with neither.
  Done. `harness.refused(text)` finds the first line with either error. It also
  matches Node.js's "resource busy or locked", which Claude Code's file tools would
  print for a busy file.
  - `Stream.refusals`, and `transcript_refusals`, read Claude Code's failed tool
    results (`is_error`), once per call. Each gives `{tool, command | path, error}`.
  - `codex.refusals(text)` reads only the output of a command Codex says exited
    non-zero.
  - A search or a read that quotes the error succeeded, and is no refusal.
  Unit tests, all passing, on events built by hand in Claude Code's stream shape,
  not recorded from a run:
  - in `test_change_workflow_stream.py`: CW-w3oa's scenario, a busy protected file
    whose result repeats, read once, a denial that stays a denial, results with
    neither, and a transcript read back;
  - in `test_change_workflow_harness.py`: `refused`, and Codex's refusal from a failed
    command, a succeeded search's output passed over.
- [x] 6.4 Move `Model` and `HARNESSES` out of `steps.py` to the adapters, and check the
  configuration's models against each adapter's steps: a model only for a step its
  harness's adapter can run, refused naming the step (CW-zq4h). Verify: unit tests for
  CW-zq4h's two scenarios.
  Done. `Model` is `harness.Model`, and `HARNESSES` is `adapters.HARNESSES`.
  `config._models` refuses a model for a step its adapter cannot run, naming the step,
  the harness, and the steps it runs.
  - Outside the task: the configuration's check now refuses a writable path under any
    adapter's protected path (`adapters.PROTECTED`), whichever harness runs the step.
  Unit tests, moved from `test_change_workflow_steps.py` to
  `test_change_workflow_config.py`, which section 11 keeps. All passing:
  - the policy's refusals;
  - CW-zq4h's two scenarios;
  - an adapter's settings file refused as a writable path.
- [x] 6.5 A step's resolved scope takes the adapter of its first model's harness, and
  `config`/`config --json` list the adapter's paths with their source (CW-o6kc).
  Verify: the library-integration test of 2.4 extended to CW-o6kc's scenario whole.
  Done. `Configuration.scope(step, root, harness=None, …)` adds the paths of the
  adapter of `harness`. By default that is the step's first model's harness, and none
  where the configuration names no models. `config --json` marks a file mounted alone
  `"file": true`.
  `test_config_lists_each_steps_scope_with_each_paths_source` passes, library
  integration on a real Git checkout through `cli.main`. It finds:
  - planning's `openspec/` and `.git/` from the engine, `docs/` from the repository,
    and `~/.claude` and `~/.claude.json` from the adapter;
  - the adapter's three settings files protected;
  - Codex's `~/.codex` and its protected `config.toml` in the review's scope, and no
    Claude path, writable or protected.
  A unit test in `test_change_workflow_sandbox.py` renders a file mounted alone as
  its own `--bind` and creates it `{}`. An external-process test writes it in place
  through real bubblewrap, while the home directory beside it stays read-only.
- [x] 6.6 Verification point: the harness, stream, and config tests (unit, library
  integration); `run pre-commit` passes. End-to-end: none.
  Done:
  - `make test-release-tooling` on the harness, stream, config, sandbox, scope, and
    steps tests: all passing, none skipped (`-rs`). The wrapper, review, CLI, hooks,
    assumptions, graph, push, and invariants tests: 707 passed.
  - `run pre-commit`: its functional hooks pass, the relock, packaging, and every
    suite. Its `pre-commit` failed two checks. `check-doc-citations` is expected: it
    names `propose.py`, which section 9 creates. `check-history-wording` was real,
    "no longer" in a comment moved into `claude_code.py`, and is fixed. The rerun,
    after the check's fixes, passed every hook and suite, and failed only
    `check-doc-citations` on `propose.py`. The relock left the locks as committed.
  - Fresh-context check fixes:
    - Codex's refusal reading named in `harness`;
    - Node.js's busy text matched;
    - the state file's rename test made real;
    - the Codex test isolated from the owner's home, its configuration asserted;
    - the notes' claims narrowed;
    - `scope.py`'s claim about Claude Code dropped;
    - 12.9 names the companion's harness row.

    Declined: its reading that `claude_code`'s, `codex`'s, and `stream`'s
    docstrings describe the launch section 7 wires. Section 7 lands in this
    session, before the round is reviewed, and section 4 declined the same.
  Handoff:
  - The check observed that `~/.claude`, writable whole, holds what the owner's
    interactive sessions load: `CLAUDE.md`, agents, commands, skills, and hook
    scripts. Only `~/.claude/settings.json` is protected. CW-r6kd asks no more, but
    a step's mistake there reaches the owner's own sessions. For the triage.
  - Section 7: the wrapper and review move from `table_command` to `command`, and
    `table_command` and `anchored` go then. Section 9's `propose.py` citation is the
    one `check-doc-citations` failure to expect until then.
  - A protected placeholder like `.claude/settings.local.json` is created in the
    checkout. This repository ignores it. A repository that does not would see an
    untracked file, which dirties the worktree for the guarded push.

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
    assumptions" (the step table's row removed, `bwrap` and the sandbox `git` added,
    the harnesses' commands named in `claude_code` and `codex`);
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
