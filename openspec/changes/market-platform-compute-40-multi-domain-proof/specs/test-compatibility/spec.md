## ADDED Requirements

### Requirement: Deterministic compute storefront-to-site matrix

The integration suite MUST provide a deterministic topology containing separately composed VM and bare-metal storefronts and two provisioning authorities with both executor adapters. It MUST exercise every storefront-to-authority relationship through reservation, fulfillment, result observation, teardown, and capacity restoration without timing sleeps.

#### Scenario: Complete matrix runs

- **WHEN** the focused multi-domain topology suite executes
- **THEN** VM-to-site-A, VM-to-site-B, bare-metal-to-site-A, and bare-metal-to-site-B lifecycles all reach their expected terminal states with isolated correlation and ownership

#### Scenario: Storefront process restarts

- **WHEN** either storefront restarts after reservation but before lifecycle completion
- **THEN** the scenario resumes through durable selected-site and fulfillment state without duplicate infrastructure work or cross-site fallback

#### Scenario: Authority or adapter rejects work

- **WHEN** a controlled authority outage, executor mismatch, or cross-mode capacity conflict is introduced
- **THEN** the scenario observes the defined failure without routing to another authority, another storefront, or a default executor
