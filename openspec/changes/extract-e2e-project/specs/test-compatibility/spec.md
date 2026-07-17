## MODIFIED Requirements

### Requirement: Deferred e2e project extraction
External operators can run the e2e suite against arbitrary deployments from an independent project. The implementation MUST preserve the ownership and compatibility constraints in the `test-compatibility` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** external operators can run the e2e suite against arbitrary deployments from an independent project.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
