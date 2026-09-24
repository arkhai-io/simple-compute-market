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

## MODIFIED Requirements

### Requirement: Registries converge on each listing's local status

This requirement governs VM, API-credit, and bare-metal publication.

For those, a listing's local status is the publication decision and its registries
follow it. A close or reopen MUST change the local listing before any registry is
told, and a local change that fails MUST be reported to its caller with no registry
told — a seller's close is reported as retryable. Each registry's outcome for every
publish, close, and reopen MUST be recorded durably. Every publication pass — each
VM publication cycle, each API-credit capacity reconciliation, and each run of the
bare-metal publication command — MUST then resend, to each configured registry whose
recorded outcome disagrees with its listing's local status, exactly what that status
implies — a close for a closed listing, and for an open one the listing republished
and reopened — and to no other registry. A registry still unreachable stays recorded
as diverged for the next pass.

#### Scenario: A registry misses a close

- **WHEN** a listing closes locally and one of its registries fails the close
- **THEN** the next publication pass sends the close to that registry alone

#### Scenario: A registry misses a reopen

- **WHEN** a listing reopens locally and one registry fails to reopen it
- **THEN** the next publication pass republishes and reopens the listing at that registry alone

#### Scenario: A local close fails

- **WHEN** the local close of a listing fails
- **THEN** no registry is told, and a seller's close is reported as retryable with the listing unchanged

#### Scenario: A bare-metal registry that missed a close is repaired by the next run

- **GIVEN** a bare-metal listing closed locally whose registry close failed
- **WHEN** the operator runs bare-metal publication again
- **THEN** the close is resent to that registry, and to no other
