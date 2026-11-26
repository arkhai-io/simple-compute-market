## ADDED Requirements

### Requirement: Typed configuration metadata generates templates, validation and references

Typed configuration metadata MUST generate role-appropriate init templates, dotted-path
editing validation, environment schema fragments, and reference tables. Generated
outputs MUST be checked for drift in CI and MUST omit secret values and fields not
applicable to the role.

#### Scenario: Mechanism field changes

- **WHEN** a mechanism's typed configuration adds or removes an operator field
- **THEN** drift validation requires the applicable templates, environment schema
  fragments and reference output to change together

## REMOVED Requirements

### Requirement: Generated configuration has one source of truth

**Reason**: Its second half required a chart passing a service's configuration through to carry a values-schema fragment generated from the service's models, so a chart release followed every change to that configuration — the coupling pass-through exists to remove. A service validates its own configuration; a chart's values schema types only the chart's own values. Its first half is kept as "Typed configuration metadata generates templates, validation and references".

**Migration**: The storefront charts' generated definitions remain until a change moves their refusals — a secret in a public file, an unknown key, a doubled spelling — into the storefront's loader and removes them (`openspec/changes/README.md`).
