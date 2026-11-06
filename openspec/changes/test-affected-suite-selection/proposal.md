## Why

Every commit an implementation, triage, or merge session makes runs the full `make
test` first, "whatever the section touched", because a change to a shared package,
a dependency, or a lock reaches projects no focused suite covers. That rule is
costly and unreliable:

- **Too wide.** A full `make test` takes about six minutes. A one-package fix runs
  it at least once and often twice, though most sections touch a leaf or domain
  package that a handful of suites depend on.
- **Unreliable.** `make test` never rebuilds the `.dist` wheels that each suite
  installs its internal dependencies from, and `.dist` is shared with other
  branches' builds. A dependent suite that passes may have run against a stale
  wheel, so the run proves less than it appears to.

Replaying the last 300 first-parent commits on `dev` through an earlier form of
this selection — a Makefile walk, and no reads declared for `scripts/tests` — 165
needed no suite at all, 61 needed a median of 8 of the 62 locked projects' suites
(11 at the 75th percentile), and 74 touched paths a package-only mapping could not
place. The settled rules select more for skills and workflow edits, which
`scripts/tests` reads; planning re-measures the figures under them.

## What Changes

- **`make test-affected`** selects the suites a set of changed paths can affect,
  rebuilds the wheels that are stale, runs only the selected suites, explains each
  selection, and writes a record of what ran. A dry run prints the selection, as
  text or as data.
- **Nodes declare their suites.** Every `pyproject.toml`, and a `test-suite.toml` in a
  directory with no pyproject, may carry a `[tool.arkhai.test]` table: `command`, the
  node's suite as a shell command; `read-by`, the nodes whose tests read a path in
  this directory; `global`, paths every suite depends on; and `unrun`, the reason a
  node with tests has no suite.
- **Selection is mechanical.** A change to what a node ships selects it and its
  dependents, found by a walk of the pyprojects, never `uv.lock`; any other change
  inside a node selects it alone; a `read-by` entry selects its readers; a `global`
  entry runs the full `make test`; a path under the workflow's inert paths selects
  nothing itself; and any other path runs the full `make test`.
- **Wheels are rebuilt from a stamp** recording the source and the wheel hash each
  was built from, which `make dist` and `make dist-ci` also write, so a wheel another
  build left is never trusted.
- **A check** in `make check-packaging` fails on a test reading a path outside its
  node that no `read-by` entry names, a stale entry, a node with tests that declares
  neither `command` nor `unrun`, and a `global` script importing one that is not.
- **The workflow runs it before each functional commit**, through this repository's
  `pre-commit-functional` hook. Validation's local part keeps `make dist-clean`, the
  full rebuild, and `make test`, and so does CI's test matrix.
- **The review wheelhouse** takes a diff's projects from the selection, and
  `scripts/resolve-review-scope.py`'s hand-kept tables are retired.

## Capabilities

### Modified Capabilities

- `test-compatibility`: which suites a change to a path selects, the declaration of
  suites and of cross-directory reads, the check that keeps them honest, and how
  wheels are kept current for a selected run.
- `market-change-workflow`: what this repository runs for a commit's suite evidence.
- `review-artifacts`: where a diff-derived review scope comes from.

### New Capabilities

None.

## Non-Goals

- Do not change validation's local part, CI's test matrix, or what `make test`
  runs.
- Do not select end-to-end scenarios or Helm tests by changed path.
- Do not read `uv.lock` to select suites: a lock is derived and can be stale;
  the pyprojects cannot.
- Do not read the Makefiles' recipes to find suites or their dependencies.
- Do not run suites in parallel. Whether `make test` can run under `make -j` is a
  separate question.
- Do not decide here between this tool and adopting Pants; a separate comparison
  does that before implementation.

## Impact

- New tooling under `scripts/` — the selection module, `scripts/test_affected.py`,
  and `scripts/check_test_suites.py` — with its tests under `scripts/tests`; root
  `Makefile` targets `test-affected`, `test-affected-report`, and
  `check-test-suites`, the last listed in `check-packaging`; and a stamping step at
  the end of `dist` and `dist-ci`.
- A `[tool.arkhai.test]` table in each of about 58 pyprojects, and `test-suite.toml`
  files in `scripts/`, `helm/`, `dev-env/`, the root, `.github/`, `.agents/`,
  `docs/`, and `openspec/`. An entry under `.claude/` is the owner's to write.
- The `pre-commit-functional` line of the workflow's configuration, `workflow.toml`
  under `.agents/`.
- `make review-wheelhouse` and `review-wheelhouse-scope`, and
  `scripts/resolve-review-scope.py` and its tests.
- `docs/development/TESTING.md`, `docs/development/BUILD_AND_PACKAGING.md`, and the
  three capabilities above.

### Workflow engine interfaces

This changes no interface of the workflow's engine: no subcommand, flag, output
field, skill or argument form, graph node, review kind, or record format. It changes
this repository's own `pre-commit-functional` hook command in `workflow.toml`,
an interface `add-workflow-capability-contract` defines. Compatible.

## Dependencies and Related Changes

- **`add-workflow-capability-contract` (implementation).** Its `workflow.toml` under `.agents/`
  defines the repository's inert paths, which selection reads, and the
  `pre-commit-functional` hook through which implement, triage, and merge run their
  per-commit suites. Until it lands, the skills name `make test` directly.
- **A comparison with adopting Pants**, by a separate session, before implementation.
- **`align-package-paths-with-layers`** lists `scripts/resolve-review-scope.py` among
  the files a path move edits; once its tables are retired here, there is nothing
  there to move.
- Uses the shipped-package discovery of `scripts/check_project_layout.py` and the
  name normalisation of `scripts/uv_project.py`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `test-compatibility`, `market-change-workflow`, `review-artifacts`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/test-compatibility/spec.md` (nodes and their declared suites)
  and a new "Selecting the suites a change affects" section of
  `docs/development/TESTING.md`, with why the inventory reads metadata rather than
  Make recipes in `openspec/specs/test-compatibility/architecture.md`.
- D2: `openspec/specs/test-compatibility/spec.md` and the `TESTING.md` section above.
- D3: `openspec/specs/test-compatibility/spec.md` and the `TESTING.md` section above.
- D4: the `TESTING.md` section above, for the `[tool.arkhai.test]` format and its
  comments.
- D5: `openspec/specs/test-compatibility/spec.md` and
  `docs/development/BUILD_AND_PACKAGING.md`, which says what each `check-packaging`
  check enforces.
- D6: `openspec/specs/test-compatibility/spec.md` and `BUILD_AND_PACKAGING.md`'s "The
  wheelhouse".
- D7: the `TESTING.md` section above.
- D8: the `TESTING.md` section above.
- D9: `openspec/specs/market-change-workflow/spec.md`, its `index.md`, and its
  `README.md` roles statement; `TESTING.md`'s "Boundary-Change Validation" for where
  `make test` and `make test-affected` each stand.
- D10: `openspec/specs/review-artifacts/spec.md` and `TESTING.md`'s "Offline Review
  Validation".
- The owner's principle that a mechanism detected as drifting from another is kept
  in sync by closeout: provisionally
  `openspec/README.md#plan-closeout-requirements`.
