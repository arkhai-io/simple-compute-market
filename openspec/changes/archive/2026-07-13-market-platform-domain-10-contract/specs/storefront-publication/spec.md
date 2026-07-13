## MODIFIED Requirements

### Requirement: Domain runtime composition

The shared storefront role MUST consume the selected market-domain contract for listing, message, agreed-terms, materialization, receipt, and result codecs plus publication, negotiation-policy, settlement-verification, plan-construction, and fulfillment hooks. VM, bare-metal, and API-credit composition roots MUST supply their implementations explicitly, and generic storefront services MUST NOT import or branch on those concrete domains.

#### Scenario: Storefront composition selects a domain

- **WHEN** a VM, bare-metal, or API-credit storefront is assembled
- **THEN** its composition root supplies a validated domain contract used by every shared storefront service that interprets domain behavior

#### Scenario: Domain validation fails

- **WHEN** a domain codec or hook rejects a payload
- **THEN** the storefront surfaces the domain validation failure without coercing it through a different domain or a generic fallback

### Requirement: Domain publication capability

A domain that supports seller publication MUST provide its publication source and listing interpretation through the domain contract while registry fan-out remains schema-opaque core orchestration.

#### Scenario: Domain capacity changes

- **WHEN** a domain publication source observes a change in its authoritative inventory or quota
- **THEN** it produces domain listings through its contract and the shared runner publishes or reconciles their opaque payloads
