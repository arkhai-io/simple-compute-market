# Storefront Publication Specification

## Purpose

Define seller storefront ownership, listing publication/reconciliation, and domain-runtime composition.

## Requirements

### Requirement: Seller protocol surface
A storefront MUST expose authenticated listing, negotiation, settlement, identity, health, and operator control surfaces while keeping domain-specific behavior behind injected adapters.

#### Scenario: Buyer settles accepted terms
- **WHEN** the buyer submits a settlement request for an accepted negotiation
- **THEN** the storefront verifies the agreed terms and settlement evidence before scheduling fulfillment

### Requirement: Registry publication ownership
A storefront MUST publish, update, close, and reconcile its listings against one or more configured registries using its publisher identity.

#### Scenario: Derived capacity disappears
- **WHEN** authoritative capacity no longer supports a derived listing
- **THEN** reconciliation closes that listing in configured registries without treating stale local state as authority

### Requirement: Schema-opaque publication source
Core storefront publication orchestration MUST accept discovered publication-source plugins and infrastructure callbacks without importing their domain listing types.

#### Scenario: Domain publication plugin is selected
- **WHEN** an operator selects a registered domain source
- **THEN** the core runner invokes it through the publication-source contract and publishes its opaque payloads

### Requirement: Domain runtime codecs
A storefront domain runtime MUST provide the codecs for listing, message, terms, materialization, receipt, and result payloads used by shared storefront services.

#### Scenario: Storefront hosts a domain
- **WHEN** shared services cross a domain payload boundary
- **THEN** they use the selected runtime codec rather than importing a concrete domain helper ad hoc

<!-- Provenance: ARCHITECTURE.md storefront component and package layout; evidence: core_storefront.publication_sources, publication_runner, publication_plugins, domain_runtime and storefront tests -->
