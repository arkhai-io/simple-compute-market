## MODIFIED Requirements

### Requirement: Generic site-resource lifecycle boundary
Generic site resource/allocation/event persistence is independent of lease watchdog and executor teardown policy. The implementation MUST preserve the ownership and compatibility constraints in the `site-capacity` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** generic site resource/allocation/event persistence is independent of lease watchdog and executor teardown policy.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
