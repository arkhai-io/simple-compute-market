## MODIFIED Requirements

### Requirement: Gradual typing for core packages
Core public APIs are marked typed and checked through a shared pragmatic type-check target. The implementation MUST preserve the ownership and compatibility constraints in the `market-composition` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** core public APIs are marked typed and checked through a shared pragmatic type-check target.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
