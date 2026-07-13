## MODIFIED Requirements

### Requirement: Compute provisioning category migration
Cross-domain compute provisioning runs from provisioning/compute while VM and bare-metal semantics remain domain-owned. The implementation MUST preserve the ownership and compatibility constraints in the `physical-provisioning` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** cross-domain compute provisioning runs from provisioning/compute while VM and bare-metal semantics remain domain-owned.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
