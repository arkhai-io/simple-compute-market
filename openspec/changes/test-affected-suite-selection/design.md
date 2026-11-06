# Design: select the suites a change can affect

Status: design phase. Not planned. "Settled with the owner" came from the
discussion that opened the change; design confirms it and settles the proposed
decisions and open questions.

## Context

- **How a suite installs its dependencies.** Each project's suite starts with
  `reinit`, which runs `scripts/uv_project.py reinit`: `uv sync --find-links .dist`
  with `--upgrade-package` and `--reinstall-package` for every internal package.
  The project's own source is installed from its tree; every other internal
  package comes from its wheel in `.dist`. So a dependent suite tests the changed
  package's wheel, and a same-version rebuilt wheel is picked up on the next
  `reinit`.
- **Where staleness comes from.** `make test` builds no wheels except the kits'
  (`kit/Makefile`'s `test` depends on `dist`). A change to `core`, a domain
  package, or a provisioning package is tested by its dependents against whatever
  wheel `.dist` held last.
- **The architecture graph is not the test graph.** `scripts/architecture.py`
  reads each project's `dependencies` and `optional-dependencies` only. 17
  projects pull internal packages in through `[dependency-groups]` for their
  tests (for example `provisioning/compute/service` tests against the VM and
  bare-metal provisioning adapters), and `e2e-tests` and
  `tools/payments-lane-double` are outside the model altogether.
- **The pyproject closure covers every lock.** For all 62 locked projects, the
  closure described under D1 includes every internal package the project's
  `uv.lock` resolves from `.dist`. It is wider than the lock in 4 projects,
  because it counts every extra of a dependency.
- **Makefiles are a second pointer system.** Root `test` reaches suites through
  prerequisites and recipes such as `cd core && make test` and
  `$(MAKE) -C domains test-storefront`. A project's own `test` target does not
  always run only its own suite: `core/Makefile`'s runs `core`, `buyer`,
  `storefront`, and `storefront-client`, and `domains/apicredits/Makefile`'s runs
  its subprojects. Some suites need a setup step first, such as `test-registry`'s
  `make reinit`.
- **Recipes run shared tools.** `scripts/uv_project.py` is named in 56 recipes,
  one for every `reinit`. `scripts/tests` runs inside `test-release-tooling`,
  under `test-deployment-packaging`.
- **Tests read files outside their project.** Found today:
  - `domains/bare_metal/storefront/tests/test_values_schema.py` reads
    `helm/charts/storefront/values.schema.json`, and `domains/vms/storefront` has
    its own schema test;
  - `provisioning/compute/service/tests/integration/test_pool_declaration_startup.py`
    reads `dev-env/bare-metal/resource-pools.yaml`;
  - `domains/apicredits/service/tests/integration/test_credits_signed_roundtrip.py`
    reads `dev-env/identities` and checks them against `compose.yml`;
  - `e2e-tests/tests/unit/test_domain_stack_configuration.py` reads
    `domains/apicredits/compose.yml` and `compose.apicredits-local.yml`;
  - `scripts/tests` reads `.github/workflows`, compose files, and
    `manifests/published-distributions.json`.

  Each anchors on the repository root through
  `Path(__file__).resolve().parents[N]`.

## Settled with the owner

- **D1. Suites are selected by a pyproject walk, never from `uv.lock`.** A
  suite's environment is its project's own dependencies, all its extras, and its
  own dependency groups, then, transitively, the runtime dependencies and extras
  of each internal package those name. A dependency's own dependency groups are
  never installed, so the walk stops at runtime dependencies after the first
  step. A lock is derived and can be stale; the pyprojects cannot. A stale lock
  does not change what is tested either way: `reinit` re-resolves and rewrites
  it, and `make check-locks` keeps it from being committed.
- **D2. A Makefile walk selects by Makefile and by recipe-run tool.** From root
  `test`, through prerequisites and recursive `make` calls, to each suite's
  recipe. A changed Makefile selects every suite whose chain passes through it. A
  changed `scripts/` file named in a recipe selects every suite whose chain runs
  that recipe. Running a broader suite after changing `scripts/uv_project.py`
  must not depend on an agent noticing what it reaches.
- **D3. Cross-directory reads are declared, and a path-anchor check keeps the
  declarations honest.** A project lists, in its `pyproject.toml`, the repository
  paths outside it that its tests read. A changed path under a declared one
  selects that project's suite. The check fails on a test file whose
  `parents[N]` anchor reaches above its project while the project declares no
  reads, as `check-architecture-dependencies` fails on an undeclared import.
- **D4. The narrowest target runs.** For an affected project, `test-affected`
  runs the nearest `make test` going up from the project's directory, with any
  setup step the walk passes on the way down, such as the registry's `reinit`.
- **D5. Only the changed packages' wheels are rebuilt.** A dependent suite tests
  its own source and its dependencies' wheels, and a dependent's source has not
  changed. A missing or incomplete `.dist` falls back to `make dist-ci`.
- **D6. An unclaimed path runs the full `make test`.** So does a global input,
  such as `.python-version`, which the root Makefile exports as `UV_PYTHON` to
  every uv command. With D1–D3 this should be rare, and when it happens it points
  at a missing declaration or walk rule.
- **D7. The implement skill runs `make test-affected` per section, with no
  full-run exception,** including for a section that changes a Makefile or a
  lock: D1 and D2 already select what those reach. Validation's local part keeps
  `make dist-clean`, the full rebuild, and `make test`, and CI's test matrix is
  unchanged.

## Proposed decisions

- **P1. Diff base.** The changed paths are the commits since `BASE` plus the
  working tree, untracked files included. `BASE` defaults to `HEAD`; the implement
  skill passes the section's starting commit.
- **P2. Explanation.** `test-affected` prints each selected target with the rule
  and the changed path that selected it, and each changed path no rule claimed.
  A dry-run flag prints the selection and runs nothing. The section's report
  carries the printed selection as its evidence.
- **P3. Imports between scripts.** Scripts import one another (for example
  `scripts/check_locks.py` imports `uv_project`), so a changed script also
  selects whatever the recipes running its importers select, through a small
  import walk inside `scripts/`.
- **P4. Where the check runs.** The path-anchor check is its own script in
  `make check-packaging`, not part of `make check-architecture`: it protects test
  selection, not package layering.
- **P5. Code location.** The tool and its tests live in `scripts/` and
  `scripts/tests`, and reuse `scripts/architecture.py`'s project discovery
  instead of a second pyproject walk.
- **P6. A merge's resolution.** The implement skill's merge path runs
  `make test-affected` with `BASE` set to the merge's first parent instead of
  `make test`. The walk selects every suite that depends on what the merge
  brought in, including the change's own suites whose dependencies `dev` changed.

## Open questions

- **How the Makefile walk reads the Makefiles.** Parsing the files means
  handling variables, `cd X && make`, and `$(MAKE) -C X`. The alternative is
  `make -n test`, which expands everything, but GNU Make runs a line under `-n`
  only when it names `$(MAKE)`, so recipes recursing with a literal `make` would
  be invisible. Recommendation: the `make -n` expansion, with every recursive
  call converted to `$(MAKE)` and a check that keeps them that way.
- **The declaration's name and form.** For example a `reads` list under
  `[tool.arkhai.test]`, whether its entries may be directories or globs, and
  whether a declared path that no longer exists fails the check.
- **What counts as a global input.** `.python-version` at least. Whether the uv
  version pin and any root configuration belong on the list, or are better
  claimed by the walks.
- **Changes inside a project's tests only.** Whether a change confined to a
  project's `tests/` should skip the wheel rebuild and the dependents, since no
  installed code changed. This is cheap to add and narrows many sections, but
  shared test fixtures that another project imports would break it.
