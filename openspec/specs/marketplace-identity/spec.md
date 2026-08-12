# Marketplace Identity Specification

## Purpose

Define canonical marketplace principals, cryptographic proof schemes, signer/verifier composition, authenticated request integrity, and key-lifecycle behavior independently of settlement mechanisms and market domains.

## Requirements

### Requirement: Canonical scheme-tagged principal

Every authenticated marketplace actor MUST be represented by a strict `{scheme, identifier}` principal. `ed25519` identifiers MUST be unpadded base64url encodings of exactly 32 public-key bytes; `eip191` identifiers MUST be normalized lowercase EVM addresses. Authorization MUST compare the complete canonical principal and MUST reject unknown schemes, malformed identifiers, and address interpretation outside `eip191`.

#### Scenario: Identifier text collides across schemes

- **WHEN** two principals carry the same identifier text under different schemes
- **THEN** they remain distinct and proof by one does not authorize the other

### Requirement: Role authorization binds complete principals to stable subjects

Authorization MUST resolve the complete canonical principal to a stable subject and an explicit caller role at the receiving authority. Possession of a valid credential MUST NOT grant an unassigned role, and changing a subject's active credential MUST NOT change the subject, its ownership history, or its durable operation identities. Provider account IDs, hosted `account_ref` values, URLs, and other resource identifiers MUST remain resources and MUST NOT authorize as marketplace credentials. A buyer MAY use its principal directly as its subject when no separate account exists.

#### Scenario: Valid principal claims an unassigned role

- **WHEN** a principal produces a cryptographically valid proof for a role it is not authorized to perform
- **THEN** authorization fails before the handler, owned state, or external effects are reached

#### Scenario: Provider resource is presented as a credential

- **WHEN** a caller presents a hosted account reference or provider account identifier as proof of marketplace identity
- **THEN** the authority rejects it rather than resolving it to an owner or role

### Requirement: Pluggable signer and verifier contract

The identity capability MUST publish scheme-neutral signer and verifier contracts, verifier and signer-factory registries, and offline Ed25519 and EIP-191 implementations. A signer MUST expose only its public principal and a signing operation; core roles, domains, and settlement mechanisms MUST NOT receive or branch on raw private-key shape. Proofs MUST use bounded scheme-specific encodings. Ed25519 MUST sign canonical protocol bytes directly, EIP-191 MUST personal-sign those same bytes, and verification MUST dispatch from the principal scheme without changing their semantic coverage.

#### Scenario: Core role uses Ed25519

- **WHEN** an Ed25519 signer is injected into registry, buyer, or storefront orchestration
- **THEN** the role signs and verifies through the common contract without importing EVM or provider implementation code

#### Scenario: Unknown scheme is configured

- **WHEN** no registered signer/verifier implements the configured principal scheme
- **THEN** startup or request authentication fails before any owned state or external effect changes

### Requirement: Body-bound authenticated request and response version

Every authenticated state-changing request MUST use `arkhai.market-request-signature.v2`. Its proof MUST cover one domain-separated, length-delimited canonical sequence containing the protocol version, caller role, complete principal, HTTP method, semantic operation, resource identity, request ID, timestamp, and SHA-256 of canonical JSON or the empty body. Authentication headers MUST carry the version, principal scheme and identifier, role, request ID, timestamp, and proof. Behavior-affecting query values MUST be represented in the signed semantic body, and the route boundary MUST supply the expected semantic operation and resource independently of proxy path spelling.

The receiving authority MUST reserve `(principal, request_id)` before dispatch, enforce configured clock skew on first use, and reject changed reuse, missing fields, unsupported versions, or invalid proofs. An exact reuse of the same canonical request MUST resolve to the recorded operation outcome rather than execute a conflicting mutation.

Every authenticated mutation response MUST use the shared version 2 response contract to bind its domain, status, originating request identity, authority principal, timestamp, and canonical response body hash. A caller MUST verify the proof, body, request identity, and exact expected authority before accepting the acknowledgement.

#### Scenario: Signed body is changed

- **WHEN** a valid proof is replayed with any body, role, principal, operation, resource, request ID, or timestamp change
- **THEN** authentication fails and no handler, database mutation, or external effect runs

#### Scenario: Exact retry follows uncertain acknowledgement

- **WHEN** a client repeats the exact request with the same principal and request ID after losing the response
- **THEN** the authority returns or resumes the recorded operation outcome without executing a conflicting mutation

#### Scenario: An authority returns a mutation acknowledgement

- **WHEN** an authority returns a mutation response for an authenticated request
- **THEN** the caller accepts it only after the status, originating request identity, exact authority principal, timestamp, body, and response proof verify

#### Scenario: A valid but unexpected authority signs a response

- **WHEN** another valid principal signs the same response body
- **THEN** verification fails because route and configuration context select a different expected authority

#### Scenario: A supported proof scheme is verified

- **WHEN** the verifier checks an Ed25519 or EIP-191 request or response proof
- **THEN** verification completes locally without a chain node, RPC endpoint, or external identity service

### Requirement: Two-proof principal rotation

A stable owned subject MAY rotate from one principal to another only through one canonical intent containing the current principal, replacement principal, stable subject, authority, nonce, requested overlap, and expiry, signed by both the active current principal and the replacement principal. Authorities MUST apply the intent idempotently, record primary, active-overlap, disabled, and retired history, and keep both credentials active only for the bounded overlap. The replacement MUST be promoted and the old principal MUST be retired only after every required authority acknowledges the replacement. Retirement or disablement MUST NOT erase audit, subject, ownership, or operation history. An operator MAY disable a compromised principal but MUST NOT manufacture replacement ownership without both required proofs.

#### Scenario: Rotation spans several authorities

- **WHEN** some authorities have accepted a valid rotation and another remains unavailable
- **THEN** the old principal remains valid during bounded overlap and retirement cannot complete until required authorities acknowledge the replacement

#### Scenario: Replacement proof is absent

- **WHEN** an owner or administrator submits a replacement identifier without proof of possession
- **THEN** no authority binds or promotes that principal

#### Scenario: Compromised principal is disabled

- **WHEN** an operator disables an active principal after suspected compromise
- **THEN** new authorization by that principal stops while its stable-subject binding, operation history, and rotation audit remain recorded

### Requirement: Marketplace identity is independent of chain credentials

Marketplace identity configuration and private signing material MUST be independent of optional wallet and chain settings. A path whose selected domain and settlement effects are non-EVM MUST NOT require, derive, inspect, or persist an EVM wallet, RPC URL, chain ID, deployed address, gas balance, or EVM private key. A selected EVM effect MAY require explicit separately validated wallet/chain configuration. An `eip191` marketplace signer MAY share underlying key material with a chain wallet only when configuration explicitly selects that reuse; neither implicit derivation nor cross-role key reuse is required.

#### Scenario: Hosted-fiat participant has no wallet

- **WHEN** an Ed25519 buyer or seller selects only non-EVM marketplace and `fiat.stripe.v1` operations
- **THEN** publication, discovery, negotiation, onboarding, funding, settlement, status, reclaim, and recovery proceed without wallet or chain configuration

#### Scenario: Alkahest is selected

- **WHEN** an accepted obligation requires an Alkahest transaction
- **THEN** the mechanism adapter requires its explicit EVM wallet and chain settings without changing the participant's marketplace-principal contract

### Requirement: Identity secrets never enter durable public carriers

Private signing material MUST be supplied through an approved secret boundary, consumed only to construct the selected signer, and MUST NOT appear in principals, request bodies, database rows, run logs, listing or negotiation payloads, settlement plans, release artifacts, diagnostics, reprs, ConfigMaps, or public examples. Public principals and trust pins MAY appear in ordinary configuration and signed artifacts.

#### Scenario: Recovery state is persisted

- **WHEN** a buyer or storefront records resumable operation state
- **THEN** the record contains the canonical public principal and operation identity but no private signing material
