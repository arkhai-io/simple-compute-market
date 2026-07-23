## MODIFIED Requirements

### Requirement: Host capacity filtering
The capacity check accepts optional vCPU, RAM, and GPU requirements and returns eligible ranked hosts. The implementation MUST preserve the ownership and compatibility constraints in the `physical-provisioning` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** the capacity check accepts optional vCPU, RAM, and GPU requirements and returns eligible ranked hosts.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
