## ADDED Requirements

### Requirement: An unbacked pool yields no bare-metal listing

Every bare-metal listing is capacity-backed. Bare-metal publication MUST derive no
listing from a Physical Resource whose pool declares itself unbacked, and MUST report
each such pool to the operator by name, because a listing derived from it could only
publish a backing its pool contradicts.

#### Scenario: An unbacked pool advertises bare metal

- **WHEN** a pool that declares itself unbacked advertises `bare_metal`
- **THEN** bare-metal publication derives no listing from it
- **AND** the operator is told which pool was refused and why

## MODIFIED Requirements

### Requirement: A listing advertises only a mode its pool authorizes

A listing a storefront derives from a site's resource-pool projection MUST offer only
an offering mode its Resource Pool declares advertisable, whether the listing is
capacity-backed or unbacked. The listing's offering mode continues to resolve from
the frozen contribution registration, and the public offer's mode MUST continue to
equal the recorded offering mode. VM and bare-metal publication both derive their
listings from that projection, and each resolves every pool it derives from through
the shared site declaration reader: a pool that does not declare the listing's mode
advertisable, or that declares itself disabled, yields no listing, and a pool whose
declarations do not resolve holds the listings derived from it — neither published,
closed, nor refreshed.

The pool's delivery authorization MUST continue to be rechecked at reservation,
scheduling, and provider dispatch, and those rechecks apply only to capacity-backed
listings because only they reach those layers.

#### Scenario: A pool authorizes advertisement but not delivery

- **WHEN** an unbacked pool declares a mode advertisable that its provider configuration does not prove deliverable
- **THEN** a listing derived from that pool may offer that mode
- **AND** no reservation, scheduling, or dispatch path is reachable for that listing

#### Scenario: A listing offers a mode its pool does not authorize

- **WHEN** candidate derivation would produce a listing offering a mode its pool does not declare advertisable
- **THEN** the candidate is refused rather than published

#### Scenario: A pool stops advertising bare metal

- **GIVEN** an open bare-metal listing derived from a pool
- **WHEN** that pool no longer declares `bare_metal` advertisable, or declares itself
  disabled, and the operator runs bare-metal publication
- **THEN** the listing closes as a withdrawn source

#### Scenario: A bare-metal pool's declarations do not resolve

- **GIVEN** a bare-metal listing derived from a pool
- **WHEN** a later projection generation leaves that pool unresolvable
- **THEN** the listing is neither closed nor refreshed until the pool resolves

### Requirement: A site whose projection is not held holds its listings

A storefront that derives listings from site projections MUST treat a configured site whose
resource-pool projection holds no value as unknown, not empty: every listing derived from
that site MUST be held, neither closed nor refreshed, until the site's projection holds a
value. Such a storefront MUST NOT derive listings from its local tables because no site's
projection is held.

#### Scenario: The storefront starts while a site is unreachable

- **WHEN** a storefront with open listings from a site restarts while that site cannot be
  reached, and a publication cycle runs
- **THEN** those listings stay open, and none is closed as having lost its source

#### Scenario: No site's projection is held

- **WHEN** no configured site's projection holds a value and a publication cycle runs
- **THEN** no listing is derived from the storefront's local tables and no listing is
  closed

#### Scenario: The site returns

- **WHEN** the unknown site's projection loads
- **THEN** its listings are reconciled against it as usual

#### Scenario: A bare-metal site is unreachable during a publication run

- **GIVEN** open bare-metal listings derived from a site
- **WHEN** the operator runs bare-metal publication while that site's projection cannot be
  fetched
- **THEN** those listings stay open and unchanged, and the run reports the site as unknown
- **AND** every other configured site is reconciled as usual

### Requirement: Registries converge on each listing's local status

This requirement governs VM, API-credit, and bare-metal publication.

For those, a listing's local status is the publication decision and its registries
follow it. A new listing MUST be recorded locally, with its durable binding, before any
registry is told of it, so no registry can hold a listing the storefront has no record
of. A close or reopen MUST change the local listing before any registry is told, and a
local change that fails MUST be reported to its caller with no registry told — a
seller's close is reported as retryable. Each registry's outcome for every publish,
close, and reopen MUST be recorded durably. Every publication pass — each VM
publication cycle, each API-credit capacity reconciliation, and each run of the
bare-metal publication command — MUST then resend, to each configured registry whose
recorded outcome disagrees with its listing's local status, exactly what that status
implies — a close for a closed listing, and for an open one the listing republished and
reopened — and to no other registry. A registry still unreachable stays recorded as
diverged for the next pass.

#### Scenario: A registry misses a close

- **WHEN** a listing closes locally and one of its registries fails the close
- **THEN** the next publication pass sends the close to that registry alone

#### Scenario: A registry misses a reopen

- **WHEN** a listing reopens locally and one registry fails to reopen it
- **THEN** the next publication pass republishes and reopens the listing at that registry alone

#### Scenario: A local close fails

- **WHEN** the local close of a listing fails
- **THEN** no registry is told, and a seller's close is reported as retryable with the listing unchanged

#### Scenario: A new listing's local record fails

- **WHEN** publication derives a new listing and recording it locally fails
- **THEN** no registry is told of the listing

#### Scenario: A bare-metal registry that missed a close is repaired by the next run

- **GIVEN** a bare-metal listing closed locally whose registry close failed
- **WHEN** the operator runs bare-metal publication again
- **THEN** the close is resent to that registry, and to no other
