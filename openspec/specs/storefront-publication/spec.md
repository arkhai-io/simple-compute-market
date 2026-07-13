# Storefront Publication Specification

## Purpose

Define seller storefront ownership, listing publication/reconciliation, and domain-runtime composition.

## Requirements

### Requirement: Seller protocol surface
A storefront MUST expose authenticated listing, negotiation, settlement, identity, health, and operator control surfaces while keeping domain-specific behavior behind injected adapters.

#### Scenario: Buyer settles accepted terms
- **WHEN** the buyer submits a settlement request for an accepted negotiation
- **THEN** the storefront verifies the agreed terms and settlement evidence before scheduling fulfillment

### Requirement: Operator-visible acceptance state
The storefront MUST expose enough operator state to distinguish global negotiation pause from listing state and an empty resource projection from an inventory import failure.

#### Scenario: Storefront is globally paused
- **WHEN** a buyer starts a negotiation while global pause is active
- **THEN** the storefront rejects it with HTTP 503 and a global-pause reason until an authenticated operator resumes the process

#### Scenario: Storefront has no imported resources
- **WHEN** the active storefront database contains no resource rows
- **THEN** system status reports `resource_count` as zero and new negotiations cannot match inventory

### Requirement: Registry publication ownership
A storefront MUST publish, update, close, and reconcile its listings against one or more configured registries using its publisher identity.

#### Scenario: Derived capacity disappears
- **WHEN** authoritative capacity no longer supports a derived listing
- **THEN** reconciliation closes that listing in configured registries without treating stale local state as authority

### Requirement: Domain publication capability
A domain that supports seller publication MUST provide its publication source and listing interpretation through the domain contract while registry fan-out remains schema-opaque core orchestration.

#### Scenario: Domain publication plugin is selected
- **WHEN** an operator selects a registered domain source
- **THEN** the core runner invokes it through the publication-source contract and publishes its opaque payloads

#### Scenario: Domain capacity changes
- **WHEN** a domain publication source observes a change in its authoritative inventory or quota
- **THEN** it produces domain listings through its contract and the shared runner publishes or reconciles their opaque payloads

### Requirement: Domain runtime composition
The shared storefront role MUST consume the selected market-domain contract for listing, message, agreed-terms, materialization, receipt, and result codecs plus publication, negotiation-policy, settlement-verification, plan-construction, and fulfillment hooks. VM, bare-metal, and API-credit composition roots MUST supply their implementations explicitly, and generic storefront services MUST NOT import or branch on those concrete domains.

#### Scenario: Storefront composition selects a domain
- **WHEN** a VM, bare-metal, or API-credit storefront is assembled
- **THEN** its composition root supplies a validated domain contract used by every shared storefront service that interprets domain behavior

#### Scenario: Domain validation fails
- **WHEN** a domain codec or hook rejects a payload
- **THEN** the storefront surfaces the domain validation failure without coercing it through a different domain or a generic fallback

## Evidence

- Generic publication source, runner, and plugin discovery: `core/storefront/tests/unit/test_publication_sources.py`, `test_publication_runner.py`, and `test_publication_plugins.py`.
- Registry fan-out and publication persistence: `core/storefront/tests/unit/test_registry_publication.py` and `domains/vms/storefront/tests/unit/test_publications_wiring.py`.
- Domain-runtime bundle and VM wiring: `core/storefront/tests/unit/test_domain_runtime.py` and `domains/vms/storefront/tests/unit/test_domain_runtime_wiring.py`.
- Global pause state: `domains/vms/storefront/tests/unit/test_order_pause_state.py` and `tests/integration/test_admin_api.py`.
- Resource-count diagnosis: `domains/vms/storefront/src/market_storefront/services/system_service.py` and `e2e-tests/tests/smoke/test_storefront_smoke.py`.

Replacing the domain-owned storefront executables remains proposed work rather than baseline behavior.
