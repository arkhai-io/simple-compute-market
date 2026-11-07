## Why

The implement skill requires `make test` before every section's commit, "whatever
the section touched" (`.agents/skills/change-implement/SKILL.md`, "Check before
committing"), because a change to a shared package, a dependency, or a lock
reaches projects no focused suite covers. That rule is costly and unreliable:

- **Too wide.** A full `make test` takes about six minutes. A one-package fix runs
  it at least once and often twice, though most sections touch a leaf or domain
  package that a handful of suites depend on.
- **Unreliable.** `make test` never rebuilds the `.dist` wheels that each suite
  installs its internal dependencies from. A dependent suite that passes may have
  run against a stale wheel of the package the section changed, so the run proves
  less than it appears to.

Replaying the last 300 first-parent commits on `dev` through the selection
described below: 165 needed no suite at all (documentation, specifications, and
skills only), 61 needed a median of 8 of the 62 locked projects' suites (11 at the
75th percentile, 15 or fewer in 54 of them), and 74 touched paths that a
package-only mapping could not place. Most of those 74 are Makefiles, `scripts/`,
`helm/`, `dev-env/`, and compose files, which the Makefile walk and declared
reads below place.

## What Changes

- A `make test-affected` target selects the suites a set of changed paths can
  affect, rebuilds the wheels of the changed packages, and runs only the selected
  suites. It explains each selection.
- Selection is mechanical, from three sources:
  - **The pyproject walk.** A suite is affected when a changed path is inside its
    project, or when its project depends on a changed package: through its own
    dependencies, extras, and dependency groups, then transitively through the
    runtime dependencies and extras of the internal packages those name.
  - **The Makefile walk.** From root `test`, through prerequisites and recursive
    `make` calls, to each suite's recipe. A changed Makefile, or a changed
    `scripts/` file a recipe runs, selects every suite whose recipe chain
    reaches it.
  - **Declared reads.** A project declares the repository paths outside itself
    that its tests read. A changed declared path selects that project's suite.
- A new check fails when a test anchors on a path above its project, through
  `Path(__file__).resolve().parents[N]`, while its project declares no reads.
- A changed path that none of the three claims, or a global input such as
  `.python-version`, falls back to the full `make test`.
- The implement skill runs `make test-affected` for each section's evidence in
  place of `make test`. Validation's local part keeps `make dist-clean`, the full
  rebuild, and `make test`, and so does CI's test matrix.

## Capabilities

### Modified Capabilities

- `market-change-workflow`: what the implement step runs for a section's suite
  evidence in this repository, and the check that keeps declared reads honest
  among this repository's checks.
- `test-compatibility`: which suites a change to a path must run, and the
  declaration of cross-directory test reads.

### New Capabilities

None.

## Non-Goals

- Do not change validation's local part, CI's test matrix, or what `make test`
  runs.
- Do not select end-to-end scenarios or Helm tests by changed path.
- Do not read `uv.lock` to select suites: a lock is derived and can be stale;
  the pyprojects cannot.
- Do not run suites in parallel. Whether `make test` can run under `make -j` is a
  separate question.

## Impact

- New tooling under `scripts/` with its tests under `scripts/tests`, and a
  `test-affected` target in the root `Makefile`.
- Recipes that recurse with a literal `make` instead of `$(MAKE)`, if the
  Makefile walk's design needs them uniform.
- `[tool.arkhai.test]` declarations, or whatever name design settles, in the
  `pyproject.toml` of each project whose tests read outside it. Known today:
  `domains/bare_metal/storefront`, `domains/vms/storefront`,
  `provisioning/compute/service`, `domains/apicredits/service`, `e2e-tests`, and
  the `scripts/tests` suite.
- The new check, added to `make check-packaging`.
- `.agents/skills/change-implement/SKILL.md`, `docs/development/TESTING.md`,
  and `docs/agents/change-workflow.md`.

### Workflow engine interfaces

This changes the content of one skill, `change-implement`: what it runs for a
section's suite evidence, and possibly for a merge's resolution. Its argument
form, the step table, the graph, and the record set are unchanged. The step
table already grants `make test*`, which covers `make test-affected`. Compatible.

## Dependencies and Related Changes

- None. Uses the project discovery in `scripts/architecture.py`, which
  `make check-architecture` already walks, and the wheel handling in
  `scripts/uv_project.py`, which every suite's `reinit` already runs.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `market-change-workflow`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations:
`docs/development/TESTING.md` for where `make test-affected` and `make test` each
stand, and the selection rules; `market-change-workflow` for the implement step's
evidence; `docs/development/DEPLOYMENT_AND_CONFIG.md` or `TESTING.md` for the
read declaration's format.
