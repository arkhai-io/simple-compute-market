## MODIFIED Requirements

### Requirement: Portable internal wheel resolution
Customer-facing and service package locks no longer encode parent-directory uv sources. The implementation MUST preserve the ownership and compatibility constraints in the `deployment-state` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** customer-facing and service package locks no longer encode parent-directory uv sources.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
