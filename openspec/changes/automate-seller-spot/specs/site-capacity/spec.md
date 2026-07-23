## ADDED Requirements

### Requirement: Interruption state remains authority-specific

A seller interruption workflow MUST treat lease truncation, fulfillment teardown, Physical Resource release, and settlement completion as independently authoritative transitions. Storefront decision evidence MAY reference those states but MUST NOT substitute for them.

#### Scenario: Lease is truncated but teardown is pending

- **WHEN** the site accepts an earlier lease end while physical teardown has not succeeded
- **THEN** capacity remains governed by teardown/release policy and the storefront reports the distinct pending state
