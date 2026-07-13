## MODIFIED Requirements

### Requirement: Generic storefront-client negotiation wire
The storefront client sends domain-enveloped provision terms without compute-specific parameters. The implementation MUST preserve the ownership and compatibility constraints in the `negotiation-protocol` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** the storefront client sends domain-enveloped provision terms without compute-specific parameters.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
