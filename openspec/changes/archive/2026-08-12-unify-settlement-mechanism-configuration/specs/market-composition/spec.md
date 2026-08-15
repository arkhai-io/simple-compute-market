## ADDED Requirements

### Requirement: Explicit settlement configuration registration

Composition roots MUST register installed settlement mechanisms with canonical ID, typed config schema, preflight, client factory, option builder, buyer compatibility, and optional operator commands. Core role packages MUST consume only the shared registration/status contract and MUST NOT branch on mechanism IDs or import concrete mechanism configuration.

#### Scenario: Composition omits hosted client

- **WHEN** a domain composition installs only Alkahest
- **THEN** common settlement status, publication, and buyer selection expose only that registration without hosted placeholders or no-op hooks

### Requirement: Shared resources are injected on demand

Identity, wallet, and chain resources MUST be composed independently of settlement mechanism configuration and injected only into registrations that declare them. Installing a non-EVM mechanism MUST NOT require placeholder wallet or chain resources.

#### Scenario: Fiat-only VM storefront starts

- **WHEN** VM composition installs hosted non-EVM settlement with Ed25519 identity and no Alkahest registration
- **THEN** startup, readiness, publication, and servicing succeed without constructing a wallet or chain client
