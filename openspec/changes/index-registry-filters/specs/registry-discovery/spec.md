## MODIFIED Requirements

### Requirement: Conditional registry filter indexes
Measured listing-query latency can activate scalar generated indexes and array side indexes declared by indexed:true. The implementation MUST preserve the ownership and compatibility constraints in the `registry-discovery` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** measured listing-query latency can activate scalar generated indexes and array side indexes declared by indexed:true.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
