# Design: select the suites a change can affect

Status: design settled. Its implementation waits on `add-workflow-capability-contract`
and on the comparison with adopting Pants under "Open Questions".

## Context

- **How a suite installs its dependencies.** Most projects' `test` target depends on
  `reinit`, which runs `scripts/uv_project.py reinit`: `uv sync --find-links .dist`
  with `--upgrade-package` and `--reinstall-package` for every internal package its
  lock names. The project's own source is installed from its tree; every other
  internal package comes from its wheel in `.dist`. `core`'s `test-core` and
  `kit/identity`'s `test` run `uv run` without `reinit`; neither has an internal
  dependency.
- **Where staleness comes from.** `make test` builds no wheel except the kits'
  (`kit/Makefile`'s `test` depends on `dist`). And `.dist` is shared: another
  branch's build, a branch switch, or a merge of `dev` leaves wheels that do not
  match `HEAD` (MCW-v3tf names "wheels another branch left in the shared
  wheelhouse"). A dependent suite tests whatever wheel `.dist` holds.
- **The architecture graph is not the test graph.** `scripts/architecture.py`'s
  `discover()` skips `e2e-tests`, `tools`, `scripts`, and `dev-env`, and every
  `package = false` project, and reads no `[dependency-groups]`: 7 of the 62 locked
  projects are invisible to it, and 17 projects pull internal packages into their
  tests through dependency groups.
- **The pyproject closure covers every lock.** For all 62 locked projects, the
  closure of D2 includes every internal package the project's `uv.lock` resolves from
  `.dist`. It is wider than the lock in 4 projects, because it counts every extra of
  a dependency.
- **Makefiles are not a uniform pointer system.** A project's `make test` is not
  always the suite root `make test` runs for it: `e2e-tests`' runs the deployed
  scenarios (root runs `test-unit`), `helm`'s is `helm test` against a cluster (root
  runs `test-render`), `core`'s runs four suites, `scripts/tests` and
  `tools/issue-discovery` have no Makefile, and about 15 recipes on root `test`'s
  graph recurse with a literal `make`.
- **Tests read files outside their project.** About 14 projects anchor on a path
  above themselves (`Path(__file__).resolve().parents[N]`), some in two steps
  (`ROOT.parents[3]`); `kit/policy` reaches `../alkahest/src` and the repository root
  through pytest's `pythonpath`. `scripts/tests` reads `.agents/skills`,
  `.claude/change-steps.toml`, the workflow specifications' READMEs,
  `docs/development/RELEASING.md`, the root `Makefile`, `.github/workflows`, compose
  files, and `manifests/`.
- **A hand-kept selector already exists.** `scripts/resolve-review-scope.py` maps a
  diff to projects for `make review-wheelhouse`, from a 29-project table and a
  9-entry impact table, both incomplete.
- **The workflow already defines inert paths.** `add-workflow-capability-contract`
  gives the workflow's configuration file, `workflow.toml` under `.agents/`, which
  that change creates, a `[repository] inert-paths` list, the paths a change
  to which alters nothing validation or a code check would prove, and moves the
  skills' per-commit `make test` into its `pre-commit-functional` hook, run before
  each commit that changes a path outside the inert paths.

## Decisions

### D1 — A node is a directory that declares its suite

The inventory comes from structured metadata, never from the text of Make recipes. A
node is a directory with a `pyproject.toml`, or a directory with no pyproject that
has a `test-suite.toml`; both carry the same `[tool.arkhai.test]` table, beside the
`[tool.arkhai.architecture]` table pyprojects already carry. A node claims every
path in its directory, except paths inside a nested node.

A node's suite is its `command`, a shell command run from the node's directory.
Every node with a `tests/` directory declares either `command` or `unrun`, a reason
its tests are left out (`tools/issue-discovery`, whose bootstrap tests probe the
host system and which CI excludes); a node without tests declares neither. No
default command exists, so nothing in the tool assumes Make, and the mechanism
reads the same in a repository that does not use it.

Each node's command is the suite `make test` runs for it — `make test` for most,
`make test-unit` for `e2e-tests`, `make test-core` for `core`, `make test-render` for
`helm`, `make -C .. test-release-tooling` for `scripts`. That equality is kept by
review, with validation's full `make test` as its backstop; no mechanism derives it.

Rejected: a walk of the Makefiles from root `test` (`make -n --trace`, or `make -p`),
which would have derived each suite from the Make graph but needed recipes
rewritten to `$(MAKE)`, a GNU Make version, and recipe text exact enough that a
slightly miswritten recursion changes what is selected; the nearest `make test`
above a project, which picks a cluster run, the deployed scenarios, the full run, or
four suites in the cases above; the root aggregate targets, which run every kit for a
change to one; a `target` key defaulting to `make test`, which builds Make into the
tool; one central file for the directories with no pyproject, which keeps facts
about a directory away from it; and `arkhai.toml` as the file's name.

### D2 — Dependents are found by a pyproject walk, never from `uv.lock`

A node's environment is its own dependencies, all its extras, and its own dependency
groups, then, transitively, the runtime dependencies and extras of each internal
package those name. A dependency's own groups are never installed, so the walk
stops at runtime dependencies after the first step. A changed package selects every
node whose environment includes it. A lock is derived and can be stale; the
pyprojects cannot, and a stale lock changes nothing either way: `reinit` re-resolves
it and `make check-locks` keeps it from being committed.

The walk discovers every `pyproject.toml` and `test-suite.toml` itself.
`architecture.discover` is not reused: it skips seven locked projects and reads no
dependency groups, and widening a layering tool's model to non-packages would
blur what it checks.

### D3 — What a changed path selects

Each changed path is classified once:

1. **A shipped path** — under a node's wheel package (`src/<pkg>/`, the one package
   `make check-project-layout` allows) or its `pyproject.toml` — selects the node and
   every node that depends on it (D2), and makes the node's wheel stale (D6).
2. **Any other path inside a node** — its `tests/`, `Makefile`, examples — selects
   the node alone. Cross-package test fixtures live in the producer's installed
   source (`TESTING.md`, "Contract Fixtures"), so no dependent imports another
   node's tests, and an unshipped file a dependent does read is a `read-by` entry
   the anchor check holds (D5). A virtual project ships nothing and has no
   dependents.
3. **A path named in a `read-by` entry** selects each node the entry names, whatever
   else claims it.
4. **A path named in a `global` entry** runs the full `make test`.
5. **A path under the workflow's `[repository] inert-paths`** (`workflow.toml`,
   read with `tomllib`; its format is the engine's public interface and the file
   stays in this repository) selects nothing itself; a `read-by` entry still selects
   its readers.
6. **Any other path** runs the full `make test`: `.python-version`, root files no
   entry names, `kit/Makefile`, `domains/Makefile`, and any new top-level directory
   until it declares itself.

The root `Makefile` is read by `scripts/tests`, so an edit to it selects that suite;
its effect on `make test` itself is proven by validation's full run, which every
round has. Documentation-only commits never reach `test-affected`, since the engine
runs no `pre-commit-functional` hook for them; rule 5 serves mixed commits and
manual runs.

Rejected: every path selecting its node and all dependents, which sends each
tests-only section through its dependents and a wheel rebuild; only `tests/` being
special, which sends a Makefile edit to every dependent; per-directory `suite =
false` declarations, a second definition of inertness beside the workflow's that
would drift from it; an unclaimed path selecting nothing, which lets a missing
declaration skip a suite silently.

### D4 — The declaration format

```toml
# dev-env/test-suite.toml
[tool.arkhai.test]
# Paths in this directory that other suites' tests read, each with the suites that
# read it; a change under one selects those suites.
read-by = { "bare-metal/resource-pools.yaml" = ["provisioning/compute/service"],
            "identities/" = ["domains/apicredits/service"] }
```
```toml
# scripts/test-suite.toml
[tool.arkhai.test]
# The suite, run from this directory.
command = "make -C .. test-release-tooling"
# Paths in this directory every suite depends on; a change to one runs the full
# test run.
global = ["uv_project.py", "check_uv_version.py"]
```
```toml
# kit/site/pyproject.toml
[tool.arkhai.test]
# The suite, run from this directory.
command = "make test"
```

- `command`: the node's suite, a shell command run from its directory.
- `read-by`: paths in this directory that other nodes' tests read, each with the
  nodes that read it. The metadata beside a path says what a change to it affects,
  so a reader of a directory sees what its changes run without reading anything
  else.
- `global`: paths in this directory every suite depends on.
- `unrun`: the reason a node with tests declares no suite.
- Every declaration carries the comments above for `read-by` and `global`.
- Paths in this directory (`read-by` keys, `global`) are relative to the declaring
  directory; node references (`read-by` values) are repository-relative node
  directories. A trailing `/` names a directory and everything under it; `*`
  matches within one path segment.
- An entry naming a path that does not exist, or a node that does not exist, fails
  the check (D5): a dangling declaration is certainly stale, as an unresolvable
  citation is.

`read-by` entries for what `scripts/tests` reads sit in a root `test-suite.toml`
(the root `Makefile`, compose files) and in `.github/`, `.agents/`, `docs/`, and
`openspec/`. Every step is denied edits under `.claude/`; an entry there is the
owner's to write, and until it exists a change to `.claude/change-steps.toml` runs
the full `make test`.

Rejected: `reads`, declared beside the reading test, which is easier to write but
puts what a change affects in every other node's metadata; `reads` with a generated
inverted form, two forms of one fact; `reads` with the inversion only shown by a
command.

### D5 — A check keeps the declarations honest

`scripts/check_test_suites.py` (`make check-test-suites`) runs in `make
check-packaging`, not in `make check-architecture`: it guards test selection, not
package layering. It reads only the tree, with the standard library. It fails on:

- **An undeclared read.** It walks the AST of every file under a node's `tests/`
  and its `conftest.py`, recording each name bound at module level to a
  `Path(__file__)…parents[N]` chain (an anchor) and each name derived from one by a
  further `.parents[M]`. An anchor that leaves its node, followed by a literal path,
  must resolve under a `read-by` entry naming the node. An anchor that leaves its
  node and whose use cannot be resolved requires some `read-by` entry to name the
  node. A pytest `pythonpath` entry in the node's pyproject that leaves the node
  must lie under a `read-by` entry naming it. Paths built at run time are not seen;
  validation's full run is the backstop.
- **A stale entry** (D4).
- **A node with tests and neither `command` nor `unrun`** (D1).
- **A `global` script importing a module in its directory that is not also
  `global`**: `uv_project.py` imports `check_uv_version.py`, and both are listed.
  Every other script's importers are in its own node's suite already.

Before each functional commit the engine runs `make check-packaging`, so a missing
entry fails in the session that added the read.

Rejected: failing only when a node with no reads at all anchors above itself, which
passes forever once any read is declared and misses two-step anchors and
`pythonpath`; no check, leaving a missing read to validation a round later.

### D6 — Wheels are rebuilt from what built them, recorded in a stamp

`.dist/.built-from.json` records, for each wheel `test-affected` builds, the
package's source fingerprint — the Git tree hashes of its shipped paths (D3) and its
`pyproject.toml` at `HEAD`, plus a hash of their uncommitted and untracked files —
and the SHA-256 of the wheel written. Before a run, every package the selected
suites install is rebuilt, by `uv build --wheel --out-dir <.dist>` in its directory,
when it has no stamp, its fingerprint differs, or its wheel's hash differs from the
stamp. The wheel hash means a build by anything else — another branch's `make dist`,
a `make dist-core` — fails the comparison, so the stamp never vouches for a wheel it
did not record.

The root `dist` and `dist-ci` targets end by stamping every wheel, since each has
just built every wheel from the current tree. The engine's `pre-commit-functional`
hook runs `make check-packaging`, whose `dist` then leaves `test-affected` nothing to
rebuild. `make dist-clean` removes the stamp with the wheels, so it never outlives
its wheelhouse. Images copy `.dist/` and carry the one small file; uv's
`--find-links` ignores a file that is not a distribution, which implementation
confirms, and `DIST_FINGERPRINT` counts only `*.whl`.

`BASE` decides only which suites are selected, never which wheels are current.

Rejected: rebuilding only the packages changed since `BASE`, which passes against
another branch's wheel of an untouched package; rebuilding the selected suites' whole
closure every run; `make dist-ci` before every run; leaving the evidence as
unreliable as it is and relying on validation's clean rebuild.

### D7 — Running `test-affected`

`scripts/test_affected.py`, run as `make test-affected [BASE=…] [DRY_RUN=1]`:

- **The changed paths** are the commits in `BASE..HEAD` plus the working tree,
  untracked files included. `BASE` defaults to `HEAD`: run before each commit, as the
  hook runs it, the diff is exactly what the commit will hold; during a merge it is
  what the merge brought in, `HEAD` being the first parent, so the change's own suites
  whose dependencies `dev` changed are selected and D6 rebuilds what `dev` changed.
- **Explanation.** Each selected node prints with the rule that selected it (`ships`,
  `depends on <node>`, `read-by`, `global`) and the path; each path that runs the full
  `make test` prints with that consequence. `DRY_RUN=1` prints the selection and runs
  nothing; `--format lines|json` gives it as data.
- **Running.** It rebuilds stale wheels (D6), then runs each selected node's
  `command` from its directory, serially, and exits non-zero when any fails. A
  fallback runs `make test` from the root.

Standard library only, run with a plain `python3`, like `check-architecture`; it
reuses `check_project_layout.wheel_package` for a node's shipped package and
`uv_project.normalise`. A shared selection module serves the tool, the check, and
the review wheelhouse. Its tests are unit tests over fixture trees and library
integration tests against a real Git repository in a temporary directory, under
`scripts/tests`.

### D8 — Each run writes a record; a round's inventory is formed from them

Each run writes a JSON record under `.snapshot/test-affected/` (untracked, like
validation's evidence under `.snapshot/validation/`): `BASE`; the tree it ran on, the
`HEAD` tree hash and the worktree's fingerprint, so a reader can tell whether a
record describes the commit before it; each selected node with its rule and path;
the wheels rebuilt; and each command with its exit status.

`make test-affected-report SINCE=<round base>` merges the records of the commits in
`<base>..HEAD` into the round's inventory, marking a commit with no record or with a
record of a different tree. The implementation review and its triage read that
report to check evidence claims, rather than the records' JSON. The selection itself
is deterministic and recomputable; the record keeps what is not — what ran, against
which wheels, with what result.

Rejected: holding the records in the change's records through the engine, which
would survive archive cleanup but extends the engine's hook contract, which
`add-workflow-capability-contract` owns; recomputing on demand only, which leaves
results claimed only in task notes.

### D9 — The workflow runs it before each functional commit

This repository's `workflow.toml` line becomes `pre-commit-functional =
["make check-packaging", "make test-affected"]`. The engine's hook table sends
implement, triage, and merge through it, so all three switch together and no skill
changes. Validation's local part keeps `make dist-clean`, the full build, and
`make test`, and CI's test matrix is unchanged: only the per-commit evidence
narrows. If steps are denied edits to `workflow.toml`, the edit is the
orchestrator's or the owner's, as `.claude/` edits are.

This depends on `add-workflow-capability-contract` having landed: before it, the
skills name `make test` directly.

### D10 — The review wheelhouse takes its scope from the selection

`make review-wheelhouse`'s diff mode takes its projects from `test-affected`'s
machine-readable dry run, keeping only locked projects; a fallback to the full run
selects every locked project. Explicit `REVIEW_PROJECTS` and `REVIEW_SCOPE_FILE`
stay. `scripts/resolve-review-scope.py`'s project and impact tables, its settlement
rule, and the JSON fields only its tests read are retired. One mechanical answer
replaces a hand-kept one that had already drifted.

## Implementation cadence

One round of two sessions, then closeout:

- **Session 1:** the selection module and discovery (D1–D3), every declaration
  across the tree (D4), and `check_test_suites.py` in `make check-packaging` (D5).
- **Session 2:** the runner — stamps, including `dist` and `dist-ci` (D6), the
  explanation and dry run (D7), records and the report (D8) — the review
  wheelhouse's migration (D10), and the hook line in `workflow.toml` (D9).

## Open Questions

- **Adopting Pants instead.** A separate session weighs this design against adopting
  Pants (dependency inference from imports, `--changed-since` with transitive
  dependents, `files` targets for non-code reads) before implementation begins.
  Bazel and Nx/Turborepo were considered and are heavier or bring a second
  toolchain. Revisit trigger: that comparison. If it adopts Pants, this change is
  dropped or rescoped, and whatever replaces it must also take over
  `resolve-review-scope.py`'s selection or keep it in sync at closeout. Planning
  makes this an explicit decision gate before the first implementation task.
