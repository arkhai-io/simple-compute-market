## ADDED Requirements

### Requirement: Unbacked storefront provenance

Shared listing provenance SHALL be either site-backed or unbacked. The unbacked
alternative SHALL have no site, pool, or physical-resource authority; SQL NULL
encodes that absence. Site-backed provenance SHALL retain its existing valid
forms. Core SHALL leave eligibility for unbacked offers to domain admission.

Negotiation bindings SHALL inherit the exact listing domain and nullable site.
Listing and negotiation provenance SHALL remain immutable. SQL guards SHALL use
NULL-safe owner comparisons. A versioned transactional migration SHALL preserve
existing bindings, negotiation rows, and their immutable constraints.

#### Scenario: Introduction without a site

- **WHEN** a domain admits an unbacked listing and opens its negotiation
- **THEN** the listing and thread retain absent site authority across restart
  without a placeholder principal, site, pool, or resource

#### Scenario: Partial physical authority

- **WHEN** a caller supplies a pool or physical resource with no site
- **THEN** both model validation and SQL admission reject the invalid provenance

#### Scenario: Migration fails before recording completion

- **WHEN** a migration error occurs after rebuilding the binding table
- **THEN** the transaction restores the previous schema, constraints and rows,
  and a later successful retry applies the migration exactly once
