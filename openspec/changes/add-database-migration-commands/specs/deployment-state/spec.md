## MODIFIED Requirements

### Requirement: Standalone migration commands and startup schema guards
Services can run migrations separately from application startup and reject schema drift. The implementation MUST preserve the ownership and compatibility constraints in the `deployment-state` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** services can run migrations separately from application startup and reject schema drift.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
