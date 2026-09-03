## ADDED Requirements

### Requirement: Externally produced dependencies resolve from a declared index

A distribution this repository depends on but does not build MUST be declared as
an ordinary dependency and resolved from a declared package index. It MUST NOT
be obtained by copying a prebuilt artifact into the build output directory, and
no build target may special-case its acquisition.

The build output directory MUST contain only artifacts this repository builds.
An externally produced distribution arriving there is indistinguishable from a
locally built one, which is what allows a build to report success while
producing nothing.

Resolution MUST succeed from a clean checkout with no credential and no access
to the repository that produced the distribution, including from a fork.

#### Scenario: A consuming project is built

- **WHEN** any project depending on an externally produced distribution is
  initialized or tested
- **THEN** the distribution resolves from the declared index, and no target
  stages, copies, or verifies a release to make that possible

#### Scenario: The wheelhouse is built

- **WHEN** the repository builds its distributions
- **THEN** the build output directory contains every distribution built here and
  no distribution produced elsewhere

#### Scenario: A fork builds the repository

- **WHEN** a pull request from a fork builds and tests the repository
- **THEN** it succeeds, because every dependency is publicly resolvable and none
  requires a credential a fork is not given

### Requirement: Release verification is a publication-time activity

Verification of an externally produced signed release MUST NOT be a prerequisite
of building, initializing, or testing. A signed release describes a deployed
service; establishing what a build compiled against is the lockfile's
responsibility, and establishing what a publication contains belongs to
publication.

The verifier itself MUST retain its behaviour. What changes is which targets
invoke it.

#### Scenario: A suite is run without a staged release

- **WHEN** a project's tests are run and no release is staged
- **THEN** the suite runs, because nothing on the path to it verifies a release

#### Scenario: A dependency is modified locally

- **WHEN** a developer builds and tests against a locally modified copy of an
  external dependency
- **THEN** the build and the suite proceed, and no published artifact results
  from them

## MODIFIED Requirements

### Requirement: Deployment documentation states how a dependency is obtained

Deployment and release documentation MUST state, for every distribution this
repository depends on and does not build, which index serves it and how a
developer or a build obtains it.

An undocumented acquisition path survives as folklore and is reconstructed
incorrectly by the next reader, which is how a staging step with no documented
owner came to be a prerequisite of running unit tests.

#### Scenario: A contributor obtains an external dependency

- **WHEN** a contributor needs to know where an externally produced distribution
  comes from
- **THEN** deployment documentation names the index and the resolution path
  without requiring them to read the build system to infer it
