## ADDED Requirements

### Requirement: Per-domain end-to-end deal path

Every market domain intended for deployment MUST have an end-to-end scenario proving a
complete deal — discovery, negotiation, settlement, delivery, and teardown — against
running services. A domain's scenario MUST exercise shared fixtures rather than a copy of
another domain's scenario, so domain-neutral test machinery is generalized rather than
duplicated per domain.

#### Scenario: A domain is deployed

- **WHEN** a market domain is intended for deployment
- **THEN** an end-to-end scenario proves a complete deal for it against running services

#### Scenario: A second domain needs a deal path

- **WHEN** an end-to-end deal path is added for another domain
- **THEN** shared fixtures are generalized to serve both, rather than the existing
  scenario being copied and edited

#### Scenario: A domain composes kit runtime

- **WHEN** a domain's storefront is composed from kit-owned runtime
- **THEN** its end-to-end scenario exercises that composition, not a domain-local
  implementation
