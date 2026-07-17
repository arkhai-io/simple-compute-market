## MODIFIED Requirements

### Requirement: Golden-image configuration compatibility
Golden-image automation emits Dynaconf key names consumed directly by provisioning and documents secret transfer. The implementation MUST preserve the ownership and compatibility constraints in the `physical-provisioning` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** golden-image automation emits Dynaconf key names consumed directly by provisioning and documents secret transfer.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
