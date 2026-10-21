## MODIFIED Requirements

### Requirement: Packaging check at change closeout

Every change's closeout task MUST run the repository packaging check and resolve every
failure it reports before implementation is considered complete. Passing test suites do
not satisfy it: a suite can pass against an environment a hand-maintained or missing
refresh left stale, and the next environment to rebuild then fails instead. A change
MUST own no architecture exception row when it is archived.

#### Scenario: A change adds an internal dependency

- **WHEN** a change makes a project depend on another repository distribution and its
  closeout runs the packaging check
- **THEN** the check passes only if the project's lock resolves that distribution from
  the wheelhouse at the version the tree builds

#### Scenario: A closeout task omits the packaging check

- **WHEN** a change's plan ends with a closeout task that does not run the packaging
  check
- **THEN** the plan does not satisfy the plan-closeout requirements

#### Scenario: A change owns an architecture exception at closeout

- **WHEN** a change that owns an architecture exception row runs its closeout
- **THEN** the change-scoped architecture check fails until the row is gone, either
  because the change removed its edge and deleted the row, or because the row was
  reassigned to another open change that now owns the divergence
