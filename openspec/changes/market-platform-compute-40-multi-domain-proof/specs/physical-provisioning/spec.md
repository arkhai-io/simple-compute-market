## ADDED Requirements

### Requirement: Explicit executor identity proof

Provisioning action, result, teardown, and release dispatch MUST use executor identity durably recorded with the allocation or fulfillment. Missing, unknown, or conflicting executor identity MUST fail without infrastructure work and MUST NOT fall back to VM or another default adapter. Fulfillment-provider identity MUST remain orthogonal and MUST NOT infer or replace executor identity.

#### Scenario: Durable executor identity is absent

- **WHEN** a lifecycle operation reaches dispatch without a recorded executor identity
- **THEN** the provisioner rejects or quarantines the operation without invoking a VM or bare-metal adapter

#### Scenario: Request attempts executor substitution

- **WHEN** a caller supplies an executor kind different from the durable allocation or fulfillment record
- **THEN** the provisioner rejects the request before infrastructure work and preserves the recorded identity

#### Scenario: Provider identity is available

- **WHEN** a FulfillmentProvider is registered for the selected Settlement Resource
- **THEN** action and release dispatch still select the executor adapter only from recorded executor identity

### Requirement: Multi-owner multi-domain provisioner proof

Each provisioning authority in the proof MUST load VM and bare-metal adapter bundles concurrently and MUST serve lifecycle operations originating from both storefront compositions without process-global storefront or executor selection.

#### Scenario: One authority serves both storefronts

- **WHEN** VM and bare-metal storefronts schedule agreements at the same provisioning authority
- **THEN** their jobs, results, teardown, and releases remain correlated to their own reservations and recorded executor identities

#### Scenario: Both authorities serve both domains

- **WHEN** the complete two-site proof runs
- **THEN** each authority executes at least one VM lifecycle and one bare-metal lifecycle through the common compute contract

### Requirement: Generic provisioning dependency proof

Generic site and compute-provisioning modules MUST remain importable and testable without concrete VM or bare-metal implementation imports.

#### Scenario: Architecture boundary tests run

- **WHEN** dependencies of generic site and compute packages are inspected
- **THEN** concrete domain models, actions, playbooks, and result types appear only behind registered adapter packages
