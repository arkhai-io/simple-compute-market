## Purpose

Define canonical marketplace principals, cryptographic proof schemes, signer/verifier composition, authenticated request integrity, and key-lifecycle behavior independently of settlement mechanisms and market domains.

## ADDED Requirements

### Requirement: Canonical scheme-tagged principal

Every authenticated marketplace actor MUST be represented by a strict `{scheme, identifier}` principal. `ed25519` identifiers MUST be unpadded base64url encodings of exactly 32 public-key bytes; `eip191` identifiers MUST be normalized lowercase EVM addresses. Authorization MUST compare the complete canonical principal and MUST reject unknown schemes, malformed identifiers, and address interpretation outside `eip191`.

#### Scenario: Identifier text collides across schemes

- **WHEN** two principals carry the same identifier text under different schemes
- **THEN** they remain distinct and proof by one does not authorize the other

### Requirement: Pluggable signer and verifier contract

The identity capability MUST publish scheme-neutral signer and verifier contracts and MUST ship offline Ed25519 and EIP-191 implementations. A signer MUST expose only its public principal and a signing operation; core roles, domains, and settlement mechanisms MUST NOT receive or branch on raw private-key shape.

#### Scenario: Core role uses Ed25519

- **WHEN** an Ed25519 signer is injected into registry, buyer, or storefront orchestration
- **THEN** the role signs and verifies through the common contract without importing EVM or provider implementation code

#### Scenario: Unknown scheme is configured

- **WHEN** no registered signer/verifier implements the configured principal scheme
- **THEN** startup or request authentication fails before any owned state or external effect changes

### Requirement: Body-bound authenticated request version

Every authenticated state-changing request MUST use a supported explicit signature version that binds domain separation, caller role, complete principal, method, semantic operation, resource identity, request ID, timestamp, and the canonical body hash. The receiving authority MUST reserve replay identity by principal and request ID before dispatch, enforce configured clock skew, and reject changed reuse, missing fields, unsigned behavior-affecting query input, unsupported versions, or invalid proofs.

#### Scenario: Signed body is changed

- **WHEN** a valid proof is replayed with any body, role, principal, operation, resource, request ID, or timestamp change
- **THEN** authentication fails and no handler, database mutation, or external effect runs

#### Scenario: Exact retry follows uncertain acknowledgement

- **WHEN** a client repeats the exact request with the same principal and request ID after losing the response
- **THEN** the authority returns or resumes the recorded operation outcome without executing a conflicting mutation

### Requirement: Two-proof principal rotation

A stable owned subject MAY rotate from one principal to another only through one canonical intent signed by an active current principal and the replacement principal. Authorities MUST apply the intent idempotently, record primary, active-overlap, disabled, and retired history, bound overlap duration, and prevent retirement from erasing audit or ownership history. An operator MAY disable a compromised principal but MUST NOT manufacture replacement ownership without both required proofs.

#### Scenario: Rotation spans several authorities

- **WHEN** some authorities have accepted a valid rotation and another remains unavailable
- **THEN** the old principal remains valid during bounded overlap and retirement cannot complete until required authorities acknowledge the replacement

#### Scenario: Replacement proof is absent

- **WHEN** an owner or administrator submits a replacement identifier without proof of possession
- **THEN** no authority binds or promotes that principal

### Requirement: Marketplace identity is independent of chain credentials

Marketplace identity configuration and private signing material MUST be independent of optional wallet and chain settings. A path whose selected domain and settlement effects are non-EVM MUST NOT require, derive, inspect, or persist an EVM wallet, RPC URL, chain ID, deployed address, gas balance, or EVM private key. A selected EVM effect MAY require explicit separately validated wallet/chain configuration.

#### Scenario: Hosted-fiat participant has no wallet

- **WHEN** an Ed25519 buyer or seller selects only non-EVM marketplace and `fiat.stripe.v1` operations
- **THEN** publication, discovery, negotiation, onboarding, funding, settlement, status, reclaim, and recovery proceed without wallet or chain configuration

#### Scenario: Alkahest is selected

- **WHEN** an accepted obligation requires an Alkahest transaction
- **THEN** the mechanism adapter requires its explicit EVM wallet and chain settings without changing the participant's marketplace-principal contract

### Requirement: Identity secrets never enter durable public carriers

Private signing material MUST be supplied through an approved secret boundary and MUST NOT appear in principals, request bodies, database rows, run logs, listing or negotiation payloads, settlement plans, release artifacts, diagnostics, reprs, ConfigMaps, or public examples. Public principals and trust pins MAY appear in ordinary configuration and signed artifacts.

#### Scenario: Recovery state is persisted

- **WHEN** a buyer or storefront records resumable operation state
- **THEN** the record contains the canonical public principal and operation identity but no private signing material
