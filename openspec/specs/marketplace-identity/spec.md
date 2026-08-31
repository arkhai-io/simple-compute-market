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

Every response an authority returns on an authenticated route MUST use the shared version 2 response contract to bind its domain, status, originating request identity, authority principal, timestamp, and canonical response body hash. This MUST hold for refusals as well as acknowledgements, and for a refusal raised while authenticating the request as well as one raised after. A caller MUST verify the proof, body, request identity, and exact expected authority before accepting any of them.

An authority MUST NOT withhold response authentication because trust has not been established: the operation and resource it binds are the ones the route derived from the request, and the request identity is the one the caller sent, neither of which depends on the caller being trusted. An answer MAY be unauthenticated only when it cannot be bound to a caller at all — the request carried no request identity, or the route recognized no authenticated contract — and an authority MUST NOT invent either in order to sign.

A refusal body MUST NOT disclose anything the caller has not already proven it holds. Naming which bound field disagreed is disclosure of the authority's expectation, not of a secret, and is permitted.

#### Scenario: Signed body is changed

- **WHEN** a valid proof is replayed with any body, role, principal, operation, resource, request ID, or timestamp change
- **THEN** authentication fails and no handler, database mutation, or external effect runs

#### Scenario: Exact retry follows uncertain acknowledgement

- **WHEN** a client repeats the exact request with the same principal and request ID after losing the response
- **THEN** the authority returns or resumes the recorded operation outcome without executing a conflicting mutation

#### Scenario: An authority returns a mutation acknowledgement

- **WHEN** an authority returns a mutation response for an authenticated request
- **THEN** the caller accepts it only after the status, originating request identity, exact authority principal, timestamp, body, and response proof verify

#### Scenario: An authenticated route refuses a caller

- **WHEN** an authority refuses a request on an authenticated route, whether the refusal is raised while authenticating it or after
- **THEN** the refusal carries response authentication bound to the route's operation and resource, the caller's request identity, the refusal status, and the refusal body, and the caller reads the refusal after verifying it

#### Scenario: A refusal cannot be bound to a caller

- **WHEN** a request carries no request identity, or names no authenticated route contract
- **THEN** the refusal is returned unauthenticated rather than signed against an invented identity or contract

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

### Requirement: Durable local buyer profiles separate metadata from credentials

A buyer profile store MUST use the versioned XDG JSON schema and stable random profile UUIDs. Each named profile records one primary canonical principal, complete retained principal history, redacted credential references, lifecycle state, selection state, and per-authority opaque payer bindings. Credential values and provider resources MUST NOT enter profile metadata.

Profile mutation MUST validate the complete candidate before fsynced atomic replacement under store serialization. Duplicate names, duplicate active principals, unsupported versions, malformed stores, permission failures, or interrupted writes MUST leave the last valid store unchanged.

#### Scenario: A selected profile is restarted

- **WHEN** a buyer process restarts after profile creation or selection
- **THEN** it resolves the same stable profile UUID and primary public principal while loading the secret only from the exact referenced provider

### Requirement: Buyer credential providers are exact and closed

Durable buyer signing credentials MUST use exactly one approved provider: OS keyring, owner-only regular secret file, or an explicitly named environment variable. No provider fallback, default raw value, symlink traversal, secret copying, or value persistence is permitted. File locators MUST be absolute and pass owner and mode checks at use time.

#### Scenario: The exact provider is unavailable

- **WHEN** the selected credential reference cannot be resolved
- **THEN** buyer work fails with bounded provider/reference context and does not attempt another provider or expose the value

### Requirement: Profile rotation retains recoverable principals

Rotation MUST verify current and replacement signer proofs over the same bounded intent, promote the replacement for new runs, and retain the predecessor while a recoverable run or opaque authority binding needs it. Retirement or deletion MUST reject blockers atomically. A hosted payer binding is opaque local metadata and MUST NOT contain provider identifiers.

#### Scenario: An old run resumes after rotation

- **WHEN** a version-3 run records the predecessor principal and stable profile UUID
- **THEN** recovery resolves that exact retained credential even if another profile or replacement principal is currently selected
