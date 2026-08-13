## ADDED Requirements

### Requirement: Pre-settlement reservation idempotency

A site authority MUST accept a durable pre-settlement identity, in addition to a
settlement identity, as an idempotency key for reserving capacity. A repeat reserve
carrying the same pre-settlement identity while a prior reservation for it remains in a
held state MUST return that reservation rather than admitting a second one. The key MUST
distinguish separate logical placements: two counterparties negotiating over the same
listing MUST each receive their own reservation.

#### Scenario: Hold placement is retried before any settlement identity exists

- **WHEN** a hold is placed again with the same pre-settlement identity while the first
  reservation is still held
- **THEN** the existing reservation is returned and no additional capacity is admitted

#### Scenario: Two counterparties negotiate over one listing

- **WHEN** two counterparties each place a hold against the same listing
- **THEN** each receives a distinct reservation, and neither is deduplicated into the
  other

#### Scenario: Placement is retried after the prior hold expired

- **WHEN** a hold is placed again with a pre-settlement identity whose only prior
  reservation has expired or been released
- **THEN** a new reservation is admitted, exactly as if no prior attempt had occurred

### Requirement: Bounded hold expiry evaluation

Evaluating which holds have expired MUST cost in proportion to the holds that are due,
not to the holds that are outstanding. The expiry instant MUST be stored in a form the
datastore can range-compare and MUST be indexed for that comparison. Bulk expiry MUST
run on a schedule rather than in the path of every ledger operation; an operation whose
own correctness depends on current availability MUST still evaluate due holds before
deciding.

#### Scenario: Many holds are outstanding and none are due

- **WHEN** a ledger operation runs while many holds are outstanding and none have expired
- **THEN** no outstanding hold is loaded or evaluated individually

#### Scenario: A hold expires between scheduled sweeps

- **WHEN** an admission is attempted after a hold expired but before the next scheduled
  sweep
- **THEN** the expired hold does not block the admission

#### Scenario: A site receives no requests

- **WHEN** no ledger operation occurs for an extended period
- **THEN** expired holds are still released by the scheduled sweep

### Requirement: Terminal reservation retention

Reservations in a terminal state MUST be retained for a bounded window rather than
indefinitely, so stored reservations track live capacity plus that window rather than
total historical volume. A terminal reservation MUST NOT be removed while a settlement
record or in-flight reconciliation still references it, regardless of its age.

#### Scenario: Terminal reservation ages past the retention window

- **WHEN** a released reservation is older than the retention window and nothing
  references it
- **THEN** it is removed, and live capacity accounting is unaffected

#### Scenario: Aged reservation is still referenced

- **WHEN** a terminal reservation is older than the retention window and a settlement
  record still references it
- **THEN** it is retained

#### Scenario: Retention runs during a period of heavy traffic

- **WHEN** reservation volume rises sharply
- **THEN** retention removes rows on the same age-and-reference basis, and no row is
  removed earlier because of unrelated volume
