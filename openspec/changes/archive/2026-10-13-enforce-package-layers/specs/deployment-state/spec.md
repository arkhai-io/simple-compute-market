## MODIFIED Requirements

### Requirement: Packaging conventions are checked mechanically

One repository target MUST build the repository wheelhouse and then run every
packaging check — environment setup, lock currency, Python version, project layout, and
package architecture — failing if any fails. Each check MUST also be runnable alone. The
checks MUST read only the committed tree and the built wheelhouse, and MUST NOT resolve
dependencies, relock, or contact a package index; building the wheelhouse retains
whatever its isolated builds need.

Lock currency MUST fail on a lock that no longer satisfies its project; on a lock that
pins an internal package at a version the tree does not build; and on a lock whose
record of an internal package disagrees with that package's wheel in the wheelhouse —
a requirement added or removed, unconditionally or under an extra in use, or
a locked dependency version the wheel's requirement no longer admits.

#### Scenario: A lock pins a superseded internal version

- **WHEN** an internal distribution's declared version is bumped and a consumer's lock
  still pins the previous one
- **THEN** the packaging check fails and names the consumer and the package

#### Scenario: An empty extra a consumer requests gains a requirement

- **GIVEN** a consumer that requests an extra of an internal wheel while that extra has no
  requirements, and the wheel rebuilt at the same version with a requirement under it
- **WHEN** the packaging check runs
- **THEN** it fails and names the consumer, the package and extra, and the requirement

#### Scenario: A same-version wheel gains a requirement

- **GIVEN** an internal wheel rebuilt at the same version with a new requirement, and a
  consumer lock not refreshed since
- **WHEN** the packaging check runs
- **THEN** it fails and names the consumer, the package, and the requirement

#### Scenario: A package breaks an architecture rule

- **WHEN** a project's source imports an internal distribution its `pyproject.toml` does
  not declare, or depends on a package its layer or scope does not permit, and no
  exception row excuses it
- **THEN** the packaging check fails and names the project, the file and line, and the
  rule

#### Scenario: Every convention holds

- **GIVEN** a tree that follows every convention and a built wheelhouse
- **WHEN** the packaging checks run with no network access
- **THEN** they succeed

#### Scenario: An index the locks resolve from is unreachable

- **WHEN** the packaging target runs where the PyTorch index cannot be reached
- **THEN** its result is the same as where it can
