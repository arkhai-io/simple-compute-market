## ADDED Requirements

### Requirement: Compute capacity bounds are filterable from below

The compute filter specification MUST declare the listing-level `available_until_utc` beside `max_duration_seconds` and MUST expose a lower-bound filter on each, under the specification's ETag precondition. Neither filter MUST depend on a stored class or on a summary of a listing's options.

#### Scenario: A stated maximum duration is too short

- **WHEN** a buyer asks for a maximum duration of at least a number of seconds and a listing states a smaller one
- **THEN** the listing does not match

#### Scenario: A stated availability ends too early

- **WHEN** a buyer asks for availability until at least an instant and a listing states an earlier one
- **THEN** the listing does not match
- **AND** a listing stating a later instant matches
