# Build the environment a test-before run needs

## Why

A step that writes a regression test shows it fails without the fix through
`scripts/change-workflow run test-before <change> --test <path> [--at <commit>]`
(`openspec/specs/change-workflow/spec.md`, CW-u4pc). The engine adds a detached
worktree at the earlier commit, copies each named test file into it, runs the
repository's `test-before` hook there, and removes the worktree however the run
ends, so the change's worktree is never touched. The implement and triage skills
send a session to it, and forbid stashing, checking out, or resetting to see the old
code.

The engine's route is sound, but this repository's hook can run only one kind of
test:

```toml
test-before = "uv run --no-project --with pytest --with pyyaml pytest -q {test}"
```

The hook runs pytest with no project environment, which suits the `scripts/` suites
and nothing else. A test in any package or in `e2e-tests` cannot import its own
project's dependencies, nor the internal packages its project installs from the
wheelhouse. So for most of the repository's tests, the sanctioned route fails before
the test runs.

`drive-the-storefront-clock-in-lanes` met this in its pre-closeout triage (its log's
seq 102). The triage wanted to show that a new `e2e-tests` unit test failed without
its uncommitted fix to the lane-time fixture:

- `git stash push -- <the fixture>` was denied, by the deny rule every step carries.
- Calling `e2e-tests/.venv/bin/pytest` directly was denied, since it is not an allowed
  form.
- The session then reverted the fixture with Edit, ran the test, and restored the
  fixture with Edit. The owner accepted the outcome, but the deny rule exists to
  forbid exactly that work, and nothing but the session itself made sure the fix
  came back.

A second gap sits behind the first. Internal packages are consumed as built wheels
from `.dist`, never through a source path (`docs/guidance/repository/wheelhouse.md`).
When the fix is in a package other than the test's project, the old code the test
must run against is that package's wheel built from the earlier commit. The
checkout's `.dist` copy may already hold the fix.

The requirement and the code also disagree about the test file. The requirement says
it runs "as `HEAD` holds it"; the engine copies the file as the change's worktree
holds it. A fix's new test is usually uncommitted when it is shown to fail, so the
code's behaviour is the one the steps need.

## What Changes

- **A `test-before` hook may build what the test needs in the worktree before it
  runs.** The engine passes the hook the change's checkout root and the commit the
  worktree is at, beside the test file, so a repository's hook can reach the
  checkout's wheelhouse and build an environment for the earlier commit.
- **A setup failure is not a test result.** The run's closing line tells a hook
  command that failed while preparing the worktree apart from the test itself
  failing there, so "the environment could not be built" never reads as "the test
  failed without the fix".
- **The test file runs as the worktree holds it.** The requirement is reworded to
  match what the engine does.
- **Merge may run it.** The steps that may run `test-before` become implementation,
  triage, and the merge, whose repair of what the landing branch broke has the same
  need to show a test failing without its fix.
- **This repository's hook builds the test's project environment.** A script finds
  the test's project and seeds the worktree's wheelhouse from the checkout's. It
  rebuilds from the worktree the wheels of internal packages the earlier commit
  holds differently, builds the project's environment with its `reinit` target, and
  runs the test in it. A test with no project, or one in `scripts/`, keeps today's
  run with no environment.
- **The skills name the route and its cost.** The implement, triage, and merge skills
  send a session to `test-before` for a test that should fail without its fix, name
  the allowed test forms, and say that a run builds an environment: a step uses it
  once per test, not as a loop.

### Decided by the owner

- **D1: the sanctioned route is the throwaway worktree, extended.** It is not a stash
  allowance for triage, nor a new set-aside-and-restore command, nor a sanctioned
  Edit revert. Setting the fix aside in the change's own worktree hides it from every
  record while it is aside, and a session that stops or commits in that window loses
  or omits it. The worktree route never touches the change's worktree.
- **D2: implementation, triage, and the merge may run `test-before`.**

### Open for design, not decided here

The design described here is the proposal's starting point, not a settled design. It
goes through design review.

- **The engine's values.** Whether the hook gets the checkout root and the commit as
  new placeholders, as environment variables, or both, and their names. How the
  closing line tells setup from the test, for example by which of the hook's commands
  failed, or by a hook split into a setup part and a run part.
- **Finding the test's project.** The nearest ancestor holding a `pyproject.toml`, or
  something the repository declares. What a test outside every project runs as.
- **Which wheels to rebuild.** Comparing each internal package's directory between
  the earlier commit and the checkout, or between the earlier commit and the
  checkout's `.dist` build. How a package's directory and its wheel's build target are
  found from the lock's package names. Whether the checkout's `.dist` is seeded by
  hard link or used in place as a second `--find-links`.
- **The environment's cost and reuse.** Whether a worktree's environment is built
  fresh each run or kept between runs at the same commit. How long a typical run
  takes, measured on an `e2e-tests` test and a package test whose fix is in a
  dependency.
- **The merge's permissions.** The merge step's rules gain what the hook needs that
  they lack.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `change-workflow`: `test-before`'s values, its setup-failure reading, the file it
  copies, and the merge among the steps that may run it.
- `market-change-workflow`: this repository's `test-before` hook building the test's
  project environment.

### New Capabilities

None.

## Non-Goals

- Allowing `git stash`, or any other command that sets work aside in the change's own
  worktree (D1).
- Running a whole suite against an earlier commit. `test-before` runs named test files.
- Changing how validation or `make test` build environments.

## Impact

- `scripts/change_workflow/hooks.py` (the values and the closing line),
  `scripts/change_workflow/graph.py` (the steps that may run each hook),
  `scripts/change_workflow/cli.py` (any new option), and their tests.
- `.agents/workflow.toml` (the `test-before` hook), a new script under `scripts/` for
  the environment, and its tests.
- `.claude/change-steps.toml` (the merge step's rules), on the owner's word as for any
  change to the step table.
- `.agents/skills/change-implement/`, `.agents/skills/change-triage/`, and
  `.agents/skills/change-merge/`.
- `openspec/specs/change-workflow/` (`spec.md`, `index.md`, `README.md`),
  `openspec/specs/market-change-workflow/`, and `docs/change-workflow-handbook.md`.

### Workflow engine interfaces

- New values a `test-before` hook may use. A compatible addition: a hook that uses
  none of them runs as before.
- The merge step gains the `test-before` hook. A compatible addition.
- The closing line's wording for a setup failure, as design settles, judged against
  `change-workflow`'s compatibility requirement (CW-c2tw).

## Dependencies and Related Changes

- None.
- `extract-change-workflow-repository` moves the engine out of this repository. The
  engine's part of this change stays repository-agnostic, and the environment build
  is this repository's hook.
- `test-affected-suite-selection` also reasons about which packages a change touches.
  Design checks whether the two share a way to find a package's directory and its
  wheel from the lock.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, `market-change-workflow`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: `change-workflow`'s
`spec.md` and `README.md` for the hook's values, its setup-failure reading and the
steps that may run it; `market-change-workflow` for this repository's hook;
`docs/change-workflow-handbook.md` where it describes `test-before`.
