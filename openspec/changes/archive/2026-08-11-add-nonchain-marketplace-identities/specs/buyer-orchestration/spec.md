## ADDED Requirements

### Requirement: Identity-first buyer orchestration

The core buyer role MUST receive one injected marketplace signer for discovery-authenticated actions, negotiation, storefront settlement, heartbeat, and recovery. It MUST resolve wallet and chain settings only when the selected domain or settlement adapter declares an EVM effect, and it MUST NOT name or pass private-key strings through schema-opaque orchestration.

#### Scenario: Buyer chooses hosted fiat

- **WHEN** an Ed25519 buyer selects a compatible `fiat.stripe.v1` option
- **THEN** core negotiation and settlement use that signer while wallet, chain, RPC, token-balance, and gas checks are not invoked

#### Scenario: Buyer chooses Alkahest

- **WHEN** the selected obligation requires an Alkahest transaction
- **THEN** the Alkahest adapter separately resolves and validates its EVM wallet and chain inputs before the chain effect

### Requirement: Buyer recovery binds public principal

Buyer run logs MUST persist the canonical public principal, signature-contract version, settlement obligation/operation identities, and domain state needed to resume, but MUST NOT persist private signing material. A recovery command MUST fail closed when the available signer does not match the recorded principal or a completed rotation.

#### Scenario: Another signer resumes a run

- **WHEN** a valid signer whose principal is not authorized for the recorded buyer attempts recovery
- **THEN** the buyer refuses to continue or submit a settlement mutation
