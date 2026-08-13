## ADDED Requirements

### Requirement: Deterministic multi-authority topology proof

The integration suite MUST provide a deterministic topology containing one multi-domain
compute storefront and two provisioning authorities, each composing both executor
adapters. It MUST exercise every domain-to-authority edge through reservation,
scheduling, fulfillment, result observation, teardown, and capacity restoration, without
timing sleeps. It MUST reuse the shared end-to-end fixtures rather than a parallel
harness.

#### Scenario: Every domain-to-authority edge completes

- **WHEN** the multi-authority topology suite executes
- **THEN** each domain completes a lifecycle at each authority, reaching its expected
  terminal state with isolated correlation and ownership

#### Scenario: Storefront restarts mid-lifecycle

- **WHEN** the storefront restarts after reservation and before lifecycle completion
- **THEN** it resumes from durable selected-authority and fulfillment state, without
  duplicate infrastructure work and without reaching another authority

#### Scenario: The selected authority becomes unavailable

- **WHEN** the authority owning a lifecycle is made unavailable
- **THEN** the lifecycle reports or retries against that authority, and no
  state-changing operation is submitted to another

#### Scenario: Cross-mode conflict within an authority

- **WHEN** a shareable claim and an exclusive claim target one Physical Resource, in
  either order
- **THEN** the conflicting claim is rejected before any executor job is created

#### Scenario: Executor identity is absent, unknown, or conflicting

- **WHEN** a lifecycle carries no recorded executor identity, an unknown one, or one
  conflicting with its reservation
- **THEN** it fails before adapter or infrastructure work, and no default executor is
  substituted

#### Scenario: Authority-local identities collide across authorities

- **WHEN** two authorities issue textually equal pool, resource, or access identifiers
- **THEN** neither is treated as globally unique, and routing uses the configured
  authority binding together with the authority-issued identifier

#### Scenario: Domains share authorities without sharing market state

- **WHEN** two market domains hosted by one storefront use the same authorities
- **THEN** each retains its own market semantics, agreement state, receipts, and results
