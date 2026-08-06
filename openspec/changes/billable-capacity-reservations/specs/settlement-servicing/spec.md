## ADDED Requirements

### Requirement: Held capacity is charged as a serviced obligation

Charging for held capacity MUST be carried as an obligation with the same durable
per-obligation lifecycle as every other obligation — its own identity, materialization,
collection, and reclaim state — rather than through a separate payments path. The
obligation MUST be generated from the reservation's burn rate and funded maximum
duration rather than from an accepted deal total, which does not exist before agreement.
The collectable amount MUST be determined by the time the capacity was actually held,
and the unconsumed remainder MUST be returned when a hold ends before its funded
maximum. Collection MUST be gated on the capacity having actually been held
exclusively, not on elapsed clock time alone.

#### Scenario: Hold runs to its funded maximum

- **WHEN** a hold is held for its full funded duration
- **THEN** the full committed amount is collectable and nothing is returned

#### Scenario: Hold is released early

- **WHEN** a hold ends before its funded maximum, whether by commitment, release, or
  abandonment
- **THEN** the amount for the time actually held is collectable and the remainder is
  returned

#### Scenario: Seller does not honor the hold

- **WHEN** capacity was not in fact held exclusively for the elapsed period
- **THEN** collection is not gated open by elapsed time alone, and the buyer is not
  charged for exclusivity it did not receive

#### Scenario: Servicing restarts mid-lifecycle

- **WHEN** the servicing process restarts while a hold obligation is part-way through
  its lifecycle
- **THEN** it resumes from durable state without double-collecting or double-returning

### Requirement: Committed funds are verifiable without a chain write

A seller MUST be able to establish that a buyer has committed funds sufficient for a
requested hold without requiring an on-chain write per verification. The verification
MAY be satisfied by reading committed balance or by consuming a proof the buyer supplies;
either MUST establish the amount committed and MUST NOT be satisfiable by a stale or
replayed assertion.

#### Scenario: Buyer requests a hold

- **WHEN** a buyer requests a hold requiring committed funds
- **THEN** the seller establishes the committed amount without an on-chain write for the
  verification itself

#### Scenario: Stale evidence of commitment is presented

- **WHEN** evidence of committed funds is stale or has already been used
- **THEN** it does not satisfy the verification
