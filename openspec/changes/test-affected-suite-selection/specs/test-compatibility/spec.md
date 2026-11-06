## ADDED Requirements

### Requirement: A node declares its suite as a command

A directory with a `pyproject.toml`, or with a `test-suite.toml`, is a node; its
`[tool.arkhai.test]` table SHALL give its suite as `command`, a shell command run from
the node's directory, or SHALL give `unrun`, the reason its tests are left out. A
node with a `tests/` directory that declares neither SHALL fail the suite check. No
default command SHALL exist.

#### Scenario: A project with tests declares no suite

- **WHEN** a locked project has a `tests/` directory and its pyproject declares
  neither `command` nor `unrun`
- **THEN** the suite check fails, naming the project

#### Scenario: A directory with no pyproject declares a suite

- **WHEN** `scripts/test-suite.toml` declares `command = "make -C .. test-release-tooling"`
- **THEN** a change selecting `scripts` runs that command from `scripts/`

### Requirement: Dependents are found from the pyprojects, never from a lock

A node's environment SHALL be its own dependencies, all its extras, and its own
dependency groups, then, transitively, the runtime dependencies and extras of each
internal package those name. A change to a package's shipped paths SHALL select
every node whose environment includes it. Selection SHALL NOT read `uv.lock`.

#### Scenario: A test-only dependency changes

- **WHEN** a change edits `domains/vms/provisioning/adapter/src/` and
  `provisioning/compute/service` names that adapter only in a dependency group
- **THEN** `provisioning/compute/service` is selected

### Requirement: What a changed path selects

A path under a node's wheel package or its `pyproject.toml` SHALL select the node and
its dependents. Any other path inside a node SHALL select the node alone. A path a
`read-by` entry names SHALL select each node it names. A path a `global` entry names,
or a path nothing claims outside the workflow's inert paths, SHALL run the full
`make test`. A path under the inert paths SHALL select nothing itself.

#### Scenario: Only a node's tests change

- **WHEN** a change edits only `kit/site/tests/unit/test_routes.py`
- **THEN** `kit/site` alone is selected and no wheel is rebuilt

#### Scenario: A read file changes

- **WHEN** a change edits `dev-env/bare-metal/resource-pools.yaml` and
  `dev-env/test-suite.toml` names `provisioning/compute/service` as its reader
- **THEN** `provisioning/compute/service` is selected

#### Scenario: An unclaimed path changes

- **WHEN** a change edits `.python-version`
- **THEN** the full `make test` runs

#### Scenario: An inert path changes beside code

- **WHEN** a change edits `kit/site/src/` and `docs/development/ROADMAP.md`, and
  `docs/` is an inert path no `read-by` entry names
- **THEN** `kit/site` and its dependents are selected, and the document selects
  nothing

### Requirement: The suite check refuses an undeclared read

The suite check SHALL fail when a test's anchor on its own file
(`Path(__file__)…parents[N]`, directly or through a name derived from one) leaves its
node and the path it reaches lies under no `read-by` entry naming the node; when an
escaping anchor's path cannot be resolved and no `read-by` entry names the node; when
a pytest `pythonpath` entry leaves the node undeclared; and when a declaration names
a path or node that does not exist.

#### Scenario: A test reads another directory's file

- **WHEN** a test in `provisioning/compute/service` reads
  `Path(__file__).resolve().parents[5] / "helm/charts/storefront/values.schema.json"`
  and no `read-by` entry under `helm/` names that node
- **THEN** the suite check fails, naming the file, its line, and the path

#### Scenario: A declaration outlives its file

- **WHEN** `dev-env/test-suite.toml` names `bare-metal/old-pools.yaml`, which does not
  exist
- **THEN** the suite check fails, naming the entry

### Requirement: A selected run never trusts a wheel it did not record

Before running selected suites, every package they install SHALL be rebuilt when it
has no stamp, when its source fingerprint differs from its stamp, or when its wheel's
hash differs from its stamp. A full wheelhouse build SHALL stamp every wheel it
builds.

#### Scenario: Another branch rebuilt a wheel

- **WHEN** another branch's `make dist-core` overwrote the `arkhai-core` wheel after
  it was stamped
- **THEN** the next selected run that installs `arkhai-core` rebuilds it from the
  current tree

#### Scenario: The wheelhouse was just built

- **WHEN** `make dist` has just run and nothing has changed since
- **THEN** a selected run rebuilds no wheel
