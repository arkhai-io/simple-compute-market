## MODIFIED Requirements

### Requirement: Conditional callback client extraction
Provisioning may replace its storefront-client dependency with a narrow local HTTP client if dependency direction becomes costly. The implementation MUST preserve the ownership and compatibility constraints in the `physical-provisioning` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** provisioning may replace its storefront-client dependency with a narrow local HTTP client if dependency direction becomes costly.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
