## ADDED Requirements

### Requirement: Bare-metal publication reads its pools' declarations

Bare-metal publication MUST resolve the Resource Pool of every candidate Physical
Resource through the site's projected pool declarations, under the same joint
per-generation rule as every other reader of those declarations. A candidate whose
pool does not declare `bare_metal` advertisable, or whose pool is disabled, MUST
yield no listing. A candidate whose pool is unresolvable MUST be held: no new listing
is published for it, and a listing already derived from it is neither closed nor
refreshed. A candidate whose pool declares itself unbacked MUST yield no listing,
because every bare-metal listing is capacity-backed.

#### Scenario: A pool that does not advertise bare metal yields no listing

- **GIVEN** an available Physical Resource enabled for bare-metal publication
- **WHEN** its pool does not declare `bare_metal` advertisable
- **THEN** bare-metal publication derives no listing from it

#### Scenario: An unresolvable pool holds its listings

- **GIVEN** a bare-metal listing derived from a pool
- **WHEN** a later projection generation leaves that pool unresolvable
- **THEN** the listing is neither closed nor refreshed until the pool resolves

#### Scenario: An unbacked pool yields no bare-metal listing

- **WHEN** a candidate's pool declares itself unbacked
- **THEN** no bare-metal listing is published and the operator is told which pool

### Requirement: Bare-metal publication converges its registry

Bare-metal publication MUST record each registry outcome in the storefront's
per-registry publication records, and each run MUST resend to any registry whose
record disagrees with its listing's local status exactly what that status implies: a
close for a closed listing, and for an open one the stored listing republished and
reopened.

#### Scenario: A registry that missed a close is repaired by the next run

- **GIVEN** a bare-metal listing closed locally whose registry close failed
- **WHEN** the operator runs bare-metal publication again
- **THEN** the close is resent to that registry, and to no other
