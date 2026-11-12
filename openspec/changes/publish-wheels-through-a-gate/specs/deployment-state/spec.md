## ADDED Requirements

### Requirement: Continuous integration publishes nothing

No workflow MUST upload to a public channel, a package or image registry, or a release
page. Continuous integration builds and tests, including building the wheelhouse and
resolving every declared distribution against it.

#### Scenario: A change is merged

- **WHEN** a change merges to the default branch
- **THEN** nothing is published anywhere

#### Scenario: A release tag is pushed

- **WHEN** a `marketplace-v*` tag is pushed
- **THEN** no workflow builds or publishes an artifact for it

### Requirement: The revision names a candidate and the semver names a release

A candidate MUST be a default-branch commit, loaded into a development registry by the
repository's publish targets, with its images tagged by that commit's revision. A
release version MUST be applied only when a candidate is promoted, by aliasing its
images and binding its components in the release's bill of materials, never by
rebuilding.

A fault found in a candidate MUST be fixed on the default branch and a later commit
loaded as the next candidate.

#### Scenario: A candidate is loaded

- **WHEN** a default-branch commit is loaded into a development registry
- **THEN** its images carry that commit's revision and no artifact carries a release
  version

#### Scenario: A candidate fails validation

- **WHEN** validation finds a fault in a candidate
- **THEN** the fix lands on the default branch and a later commit becomes the
  candidate, and no release branch exists for the failed one

### Requirement: One declaration of what a release comprises

The distributions, service images, chart, binaries and npm package a release comprises
MUST have exactly one declaration, read by every publish target. Each distribution
MUST be declared public or not public. No workflow or publish target MAY carry a
second list of components.

#### Scenario: A component is added

- **WHEN** a service image or distribution joins the release
- **THEN** one declaration is edited, and every publish target loads it without a
  second edit

### Requirement: The chart names no release

The deployment chart's version MUST follow the chart's own semver and change only when
the chart changes. Its default values MUST NOT name a release version or a release's
image revision or digest.

#### Scenario: Two releases share an unchanged chart

- **WHEN** two releases are cut and the chart did not change between them
- **THEN** both releases' bills of materials name the same chart version, and the chart
  each deployment validated is the chart it ships

### Requirement: A release is recorded by a tagged commit on its release branch

A release MUST be recorded only after it is deployed to production: a
`releases/<semver>` branch cut at the candidate's commit, one commit adding the
release's bill of materials, and a `marketplace-v<semver>` tag on that commit.
Public channels MUST be published only after the cut.

The bill of materials MUST record each component's name, version, content digest and
source revision, and for the chart the source tree it was packaged from. It MUST NOT
record a registry host, project or path.

#### Scenario: A release reaches production

- **WHEN** production runs a promoted candidate
- **THEN** its release branch and tag are made, and its bill of materials names every
  declared component by content identity

#### Scenario: A release fails before production

- **WHEN** a promoted candidate fails before production runs it
- **THEN** no release branch, tag or public artifact exists for it

### Requirement: A version changes when its contents change

Before a candidate is loaded, and again at the cut, each built wheel and the chart
MUST be compared with the previous release's bill of materials. A wheel whose version
is unchanged but whose bytes differ, or a chart whose version is unchanged but whose
source tree differs, MUST be refused.

#### Scenario: A wheel changed without a version bump

- **WHEN** a candidate's wheel has the previous release's version and different bytes
- **THEN** the check fails and names the wheel, and the candidate is not loaded

### Requirement: A product version is distinct from a distribution version

A distribution's version is fixed at build time and is not a product version.
Distributions, binaries and charts MUST be promoted at the version they were built
with. Images MAY be aliased to the product version, because an image's tag is
external to it. The bill of materials binds a product version to its components.

#### Scenario: A product version is assigned

- **WHEN** a candidate is promoted under a product version
- **THEN** its images are aliased to it, every other component keeps its own version,
  and the bill of materials records which component versions the product version
  comprises

### Requirement: Public channels receive promoted bytes all or nothing

Bytes published to a public package index MUST be the promoted bytes, unchanged.
Before uploading any distribution, the publisher MUST check every distribution against
the index. A version already present with differing bytes MUST fail the whole
publication before any upload. A version present with identical bytes is skipped.
A published version MUST NOT be replaced or deleted to make room.

#### Scenario: A version exists publicly with different content

- **WHEN** any distribution's version is already published with different bytes
- **THEN** the publication fails and no distribution in the set is uploaded
