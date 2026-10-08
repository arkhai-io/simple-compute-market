## MODIFIED Requirements

### Requirement: Marketplace identity is independent of chain credentials

Marketplace identity configuration and private signing material MUST be independent of optional wallet and chain settings. A path whose selected domain and settlement effects are non-EVM MUST NOT require, derive, inspect, or persist an EVM wallet, RPC URL, chain ID, deployed address, gas balance, or EVM private key. A selected EVM effect MAY require explicit separately validated wallet/chain configuration. An `eip191` marketplace signer MAY share underlying key material with a chain wallet only when configuration explicitly selects that reuse; neither implicit derivation nor cross-role key reuse is required.

#### Scenario: Payment participant has no wallet

- **WHEN** an Ed25519 buyer or seller selects only non-EVM marketplace and `arkhai.payments.v1` operations
- **THEN** publication, discovery, negotiation, payment approval, settlement, status, refund, and recovery proceed without wallet or chain configuration

#### Scenario: Alkahest is selected

- **WHEN** an accepted obligation requires an Alkahest transaction
- **THEN** the mechanism adapter requires its explicit EVM wallet and chain settings without changing the participant's marketplace-principal contract

### Requirement: Profile rotation retains recoverable principals

Rotation MUST verify current and replacement signer proofs over the same bounded intent, promote the replacement for new runs, and retain the predecessor while a recoverable run or opaque authority binding needs it. Retirement or deletion MUST reject blockers atomically. An opaque authority binding is local metadata and MUST NOT contain provider identifiers or authorize marketplace actions. Arkhai `payer_account` is explicit domain payment input and MUST NOT be inferred from the profile principal or such a binding.

#### Scenario: An old run resumes after rotation

- **WHEN** a version-3 run records the predecessor principal and stable profile UUID
- **THEN** recovery resolves that exact retained credential even if another profile or replacement principal is currently selected

### Requirement: Role authorization binds complete principals to stable subjects

Authorization MUST resolve the complete canonical principal to a stable subject and an explicit caller role at the receiving authority. Possession of a valid credential MUST NOT grant an unassigned role, and changing a subject's active credential MUST NOT change the subject, its ownership history, or its durable operation identities. Provider account IDs, payment account references, URLs, and other resource identifiers MUST remain resources and MUST NOT authorize as marketplace credentials. A buyer MAY use its principal directly as its subject when no separate account exists.

#### Scenario: Valid principal claims an unassigned role

- **WHEN** a principal produces a cryptographically valid proof for a role it is not authorized to perform
- **THEN** authorization fails before the handler, owned state, or external effects are reached

#### Scenario: Provider resource is presented as a credential

- **WHEN** a caller presents a payment account reference or provider account identifier as proof of marketplace identity
- **THEN** the authority rejects it rather than resolving it to an owner or role
