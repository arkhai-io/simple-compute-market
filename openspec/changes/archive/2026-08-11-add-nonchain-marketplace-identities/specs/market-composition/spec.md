## ADDED Requirements

### Requirement: From-below identity capability

Canonical principal, signer/verifier dispatch, authenticated-envelope, replay, and rotation contracts MUST live in a foundation kit. Core roles MAY consume that kit, and domain and settlement implementations MAY receive its opaque interfaces, but identity code MUST NOT depend on role composition, a concrete domain, a settlement mechanism, a hosted provider, or chain runtime.

#### Scenario: A new market domain is installed

- **WHEN** the domain composes buyer and storefront roles without blockchain functionality
- **THEN** it can use the shared Ed25519 identity capability without importing an EVM or hosted-provider package

### Requirement: Composition roots inject signers

Role and domain composition roots MUST construct signers from separately resolved identity credentials and inject them into registry, negotiation, service-peer, and settlement clients. Core/domain APIs MUST NOT select behavior by raw private-key fields or duplicate signer implementations.

#### Scenario: VM composition selects hosted fiat

- **WHEN** the VM root receives an Ed25519 signer and a manifest-compatible hosted adapter
- **THEN** the same scheme-neutral core lifecycle runs without an Alkahest client, wallet derivation, or chain preflight
