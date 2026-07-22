## MODIFIED Requirements

### Requirement: Storefront database pruning
Storefront persistence contains only production-read state; write-only dormant audit/config tables are removed after reader verification. The implementation MUST preserve the ownership and compatibility constraints in the `storefront-publication` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** storefront persistence contains only production-read state; write-only dormant audit/config tables are removed after reader verification.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
