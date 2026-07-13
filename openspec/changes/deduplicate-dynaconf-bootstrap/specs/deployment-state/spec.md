## MODIFIED Requirements

### Requirement: Shared Dynaconf bootstrap
Provisioning and e2e settings use one kit/config loader with unchanged layering. The implementation MUST preserve the ownership and compatibility constraints in the `deployment-state` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** provisioning and e2e settings use one kit/config loader with unchanged layering.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
