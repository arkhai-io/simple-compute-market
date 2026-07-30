## ADDED Requirements

### Requirement: Conditional indexed filter execution

The registry MAY activate database-indexed execution for a filter only after representative PostgreSQL measurements exceed an accepted query-latency threshold and a deployed migration provides that filter's index artifact. Indexed execution MUST remain observably equivalent to the canonical filter semantics.

#### Scenario: Indexed declaration has no deployed artifact

- **WHEN** a filter spec declares `indexed: true` but the current schema does not advertise a compatible index implementation
- **THEN** the registry does not mutate schema at runtime and either uses canonical evaluation or rejects activation actionably

#### Scenario: Indexed and canonical paths are compared

- **WHEN** an indexed implementation is proposed for activation
- **THEN** scalar, array, missing, strict, set, range, existence, legacy-JSON, update, and delete cases produce the same results as canonical evaluation

#### Scenario: Performance trigger is not met

- **WHEN** representative p95 listing-query latency remains within the accepted threshold
- **THEN** no index implementation work or migration is required solely because the declaration exists
