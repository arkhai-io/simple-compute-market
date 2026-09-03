## ADDED Requirements

### Requirement: Public publication is a deliberate promotion, not a merge side effect

Merging MUST NOT publish to a public index. Merging MAY publish to a development
registry, from which artifacts are later promoted.

Promotion MUST copy artifacts already published to the development registry and
MUST NOT rebuild them from source. A distribution's version MUST NOT change
during promotion: a version is fixed by the build that produced it, and
promotion may accept or reject it but cannot alter it.

Promotion MUST be initiated by a person. No schedule, webhook, or trigger may
cause a public publication.

#### Scenario: A change is merged

- **WHEN** a change merges to the default branch
- **THEN** artifacts are published to the development registry, and nothing
  reaches a public index

#### Scenario: Artifacts are promoted

- **WHEN** a person initiates promotion
- **THEN** the bytes already published to the development registry are uploaded
  unchanged, and no artifact is rebuilt

### Requirement: Promotion refuses a version whose published bytes differ

Before uploading any artifact, promotion MUST compare every distribution in the
set against what the public index already holds for that version.

A version absent from the public index is uploaded. A version present with
identical content is skipped, which is not an error. A version present with
differing content MUST fail the entire promotion before any artifact is
uploaded.

Failing the whole set is required rather than skipping the conflicting member.
A partially promoted set would place distributions on a public index whose
versions describe code from different builds, which is the disagreement an
inventory exists to prevent. A public index is write-once, so a version
published in error is permanent and correctable only by a further version.

#### Scenario: A version exists publicly with different content

- **WHEN** promotion finds any distribution whose version is already published
  with different bytes
- **THEN** the promotion fails and no distribution in the set is uploaded

#### Scenario: A version exists publicly with identical content

- **WHEN** promotion finds a distribution whose version is already published
  with identical bytes
- **THEN** that distribution is skipped and the promotion continues

### Requirement: One enumeration of what this repository publishes

The set of distributions this repository publishes MUST have exactly one
declaration, read by every publication path.

A second enumeration must be kept in agreement by hand, and the copy that drifts
is discovered by consumers rather than by the repository.

#### Scenario: A distribution is added or removed

- **WHEN** the set of published distributions changes
- **THEN** one declaration is edited, and every publication path reflects the
  change without a second edit

### Requirement: A product version is distinct from a distribution version

A distribution's version is fixed at build time and is not a product version. A
product version is assigned by a person at a promotion gate and is bound to a
set of independently versioned distributions by an inventory.

Distributions and archives are promoted by copy at the version they were built
with, because their version is recorded inside the artifact and cannot be
changed without rebuilding. Images may be retagged to the product version,
because an image's tag is external to it.

#### Scenario: A product version is assigned

- **WHEN** a person assigns a product version at a promotion gate
- **THEN** images are retagged to it, distributions are promoted at their own
  versions, and the inventory records which distribution versions the product
  version comprises
