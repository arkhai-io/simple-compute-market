## ADDED Requirements

### Requirement: Identity configuration separates public and secret material

Every deployed role MUST resolve a supported public principal and trust pins from ordinary profile configuration and its private signer credential from an approved Secret boundary. Wallet and chain configuration MUST remain optional and separate. ConfigMaps, rendered command arguments, image layers, release artifacts, logs, probes, and examples MUST NOT contain private signing material.

#### Scenario: Fiat-only storefront is rendered

- **WHEN** a profile enables only Ed25519 marketplace identity and hosted non-EVM settlement
- **THEN** Helm/Compose rendering requires the identity Secret reference but no wallet, chain, RPC, deployed-address, or gas configuration

#### Scenario: Identity secret is missing

- **WHEN** a role has a public principal but cannot load matching private credential material
- **THEN** startup fails before serving authenticated routes, publishing, negotiating, or submitting settlement operations

### Requirement: Identity migrations are coordinated and fail closed

Each owning service MUST migrate its identity-bearing rows through its own ordered migration chain while preserving cross-service opaque IDs and provider-operation identity. Versioned buyer run logs MUST have an explicit migration path. Authorities MUST reject old schema, old signature versions, drift, ambiguous principals, or partially migrated state; production cutover MUST quiesce authenticated mutations until all required authorities and clients report the new identity capability.

#### Scenario: One authority remains on the old signature contract

- **WHEN** deployment readiness detects a registry, storefront, service peer, or hosted authority that lacks the pinned identity version
- **THEN** the affected workflow remains unavailable rather than downgrading or submitting a legacy proof

#### Scenario: Migration encounters conflicting owners

- **WHEN** two address-only rows would create an invalid active-principal ownership relation
- **THEN** that service migration rolls back completely and readiness remains false

### Requirement: Hosted identity release is pinned as one contract

Marketplace packaging and deployment MUST consume the exact hosted client wheel and identity capabilities bound by one verified hosted release manifest. The marketplace MUST reject editable sibling sources, copied hosted signing modules, compatible-major substitution, or a service/client identity-version mismatch.

#### Scenario: Marketplace wheel carries the wrong hosted client

- **WHEN** the installed hosted client hash differs from the verified manifest used by the service deployment
- **THEN** packaging verification or startup preflight fails before a fiat option is published
