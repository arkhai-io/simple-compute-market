## Context

See `proposal.md` for motivation. `market_identity.Identity` and verifier registration already provide the right value shape, and core storefront authentication already dispatches a verifier by scheme. The implementation is incomplete: only EIP-191 is registered; the registry client derives its publisher from a private key; buyer negotiation and settlement APIs accept `buyer_address` and `buyer_private_key`; several signatures cover only an operation/resource/timestamp rather than the mutable body; persisted state and recovery logs carry address fields; and domain composition roots resolve wallet credentials before they know whether the selected settlement path needs a chain.

The hosted adapter is correctly thin and must consume the released hosted client rather than copy signing logic. The sibling hosted change makes that client accept scheme-tagged principals. This repository also has an active `service-identity-signing` change whose replay and mutual-authentication goals are valid but whose EIP-191-only implementation choice would create a second identity path. Its artifacts must be reconciled before either implementation begins.

### Pre-cutover address and private-key assumption inventory

The cutover classifies every existing carrier by authority rather than by its
field spelling:

| Area | Pre-cutover assumption | Classification and required disposition |
|---|---|---|
| `kit/identity` | EIP-191 is the only implementation and verifier recovery yields an address | **Marketplace principal:** retain EIP-191 as one explicit plugin, add Ed25519, and move all callers to the scheme-tagged signer/verifier and version 2 envelope. Private material remains only inside signer implementations. |
| `core/registry-client` and `core/registry` | Publisher identity is derived from `private_key`/`signer_address`, transported as an address, and stored in address-named ownership columns | **Removable legacy carrier:** inject a signer, transport a complete publisher principal, migrate valid legacy addresses atomically to `eip191`, and preserve publisher/listing IDs. |
| `core/buyer` discovery, negotiation, settlement, and run logs | `buyer_address` names the marketplace actor and `buyer_private_key` is threaded through orchestration before mechanism selection | **Marketplace principal:** replace actor and wire fields with `buyer_principal` plus an injected signer. **Explicit EVM effect:** keep wallet address/key only inside Alkahest balance, escrow, reclaim, and token-transfer inputs selected after the mechanism is known. Versioned run logs migrate address actors and reject all secret fields. |
| `core/storefront` auth, negotiation, claims, stage logs, and SQLite | Buyer/seller/publisher actors are address-shaped and some signed operations do not bind the body | **Marketplace principal:** persist complete principals, authorize exact scheme plus identifier, and use version 2 request/response proofs. **Explicit EVM effect:** `buyer_evm_address`, escrow recipient, token destination, and transaction signer remain inside tagged Alkahest/token-transfer payloads only. |
| `kit/settlement-runtime` | Party fields may be inferred from mechanism wallet parameters | **Marketplace principal:** the runtime receives principals opaquely and never persists wallet/private-key aliases. **Explicit EVM effect:** adapter-owned mechanism params may carry named EVM subjects. |
| `kit/hosted-settlement` | A marketplace raw key/address could be translated into hosted authentication | **Removable legacy carrier:** adapt the injected marketplace signer structurally to the manifest-pinned hosted client. The adapter stores neither private material nor hosted canonical bytes. |
| `domains/vms` composition roots and recovery | Buyer/seller address and private-key flags serve both identity and Alkahest transaction roles; VM state/run logs reuse those names | **Marketplace principal:** configure/inject role signers and migrate principals through negotiation, storefront, fulfillment, settlement, and recovery. **Explicit EVM effect:** retain separately named optional EVM credentials only for Alkahest and chain operations; hosted fiat must run without them. |
| `domains/apicredits` and `domains/bare_metal` | Address-shaped negotiation actors coexist with wallet fields used by their existing Alkahest flows | **Marketplace principal:** migrate shared negotiation/authentication carriers and signer injection. **Explicit EVM effect:** keep their current wallet, escrow-recipient, refund-destination, and transaction-key fields because those domains remain Alkahest-only in this change. |
| Service-peer configuration and clients | `storefront_admin_key`, raw private keys, or address-derived identities authenticate both directions; acknowledgements may be unsigned | **Removable legacy carrier:** replace with public principal trust pins, Secret-injected signers, version 2 body-bound requests, signed responses, durable replay reservations, and dual-proof rotation. |
| Registry/storefront databases and buyer run logs | Address-only columns/events are authoritative actor identities | **Removable legacy carrier:** validate the complete population, convert each valid value to an `eip191` principal in one transactional/versioned boundary, preserve stable subjects and operation IDs, and abort on malformed or conflicting populations. |
| Helm, Compose, settings, and `.env` examples | Wallet address/private key pairs are treated as universal role identity, and public identity may be inferred from secret material | **Marketplace principal:** render explicit scheme plus public identifier and a separate Secret credential reference. **Explicit EVM effect:** wallet/chain values are optional and rendered only for EIP-191 or EVM mechanisms. No private key appears in ConfigMaps, manifests, logs, provenance, or examples. |
| Tests, fixtures, and package/release inputs | Deterministic EVM keys double as actor identity and editable sibling/source paths may satisfy imports | **Removable legacy carrier:** use dual-scheme signer fixtures, assert no-wallet paths, pin immutable wheel versions/capabilities, reject source leakage, and keep EVM keys only in tests that exercise explicit chain effects. |

## Goals / Non-Goals

**Goals:**

- Make a canonical marketplace principal and signer/verifier contract usable by every role and domain.
- Let an Ed25519 seller publish and onboard, and an Ed25519 buyer discover, negotiate, fund, settle, inspect, and reclaim hosted fiat without wallet, chain, RPC, or gas configuration.
- Bind mutable request bodies, operation/resource, principal, role, request identity, and time into one versioned proof.
- Preserve durable ownership and recovery across key rotation and address-to-principal migrations.
- Keep EIP-191 and chain wallets available only where explicitly selected identity or settlement effects require them.
- Keep hosted-provider wire/signature logic inside the independently released hosted client.

**Non-Goals:**

- Add marketplace login, hosted accounts, sessions, passwords, OIDC, passkeys, email identity, or social/admin account recovery.
- Treat a Stripe account/customer/payment identifier, hosted account reference, URL, or API key as a marketplace identity.
- Make Ed25519 authorize EVM transactions, EIP-712 attestations, or Alkahest contracts.
- Change negotiation policy, settlement economics, condition semantics, VM fulfillment, or provider financial authority.
- Adopt hosted fiat in API credits or bare metal; those require separate domain changes.
- Keep legacy address-only APIs or unversioned signatures as compatibility aliases.

## Decisions

### The identity kit owns principals and cryptographic dispatch

`kit/identity` will own:

- `Identity(scheme, identifier)` with strict per-scheme normalization;
- a `Signer` protocol exposing its public identity and `sign(bytes) -> bytes` without exposing private material;
- verifier and signer-factory registries;
- mandatory `ed25519` and `eip191` implementations;
- canonical authenticated request/response and rotation-intent models;
- encoding, verification, timestamp, and replay primitives that are independent of HTTP framework, roles, domains, registries, settlement mechanisms, and hosted providers.

Ed25519 identifiers are unpadded base64url encodings of exactly 32 public-key bytes. EIP-191 identifiers are normalized lowercase addresses. Proofs are bounded scheme-specific encodings. Core and domain packages receive injected signers and never branch on scheme or private-key shape.

A single universal credential class containing a `private_key: str` was rejected because it would leak scheme details and encourage secret persistence in models, logs, and state.

### Marketplace request signatures use one version 2 semantic envelope

`arkhai.market-request-signature.v2` signs a length-delimited canonical sequence containing protocol version, caller role, complete principal, HTTP method, semantic operation, resource identity, request ID, timestamp, and SHA-256 of canonical JSON or the empty body. Query inputs that affect behavior are represented in the canonical operation body instead of unsigned query parameters. Servers reserve `(principal, request_id)` before dispatch, reject more than configured skew, and reject changed reuse.

Headers carry the version, scheme, identifier, role, request ID, timestamp, and proof. The server supplies the expected semantic operation/resource at the route boundary so reverse-proxy path rewriting cannot change the signed value. EIP-191 personal-sign and Ed25519 sign exactly the same canonical bytes through their scheme wrapper.

Version 1 and legacy embedded/query signatures are removed after a coordinated migration rather than guessed from missing fields. Body-bound v2 is breaking but fixes an existing integrity gap and avoids maintaining two replay stores.

### Authorization binds complete principals to stable subjects

A principal is a credential identity; stable records such as registry publisher, storefront, negotiation, listing, settlement plan, or account binding remain durable subjects. Authorization resolves the complete principal to a subject and role. Matching identifier text under another scheme never authorizes.

Buyers may be represented directly by their principal where no separate account exists. Sellers use one chosen marketplace principal across storefront publication, hosted account ownership, negotiation, and settlement calls. Provider account IDs and hosted `account_ref` values remain opaque resources, never credentials.

### Rotation is a two-proof, multi-authority operation

The kit defines a canonical rotation intent with old principal, replacement principal, subject, authority, nonce, requested overlap, and expiry. Both old and replacement sign the same intent. Each owning service applies it idempotently, records primary/active/retired history, and keeps both credentials active only for the bounded overlap. A client-side coordinator queries every authority, applies the rotation, verifies convergence, promotes the new principal, and retires the old only after all required authorities acknowledge it.

There is no cross-service database transaction. Partial rotation is safe because the old credential remains active until convergence. Operator disablement can stop a compromised principal but cannot manufacture a replacement proof. Lost-key/social recovery is deferred.

### Wallet and marketplace identity are orthogonal

A role receives an `IdentityConfig` plus separately injected credential material. Optional `Wallet` and `Chains` settings remain chain-effect configuration. Core buyer discovery and negotiation resolve marketplace identity first; a domain/settlement adapter requests a wallet only after choosing an Alkahest/EVM path. A hosted-fiat path maps the same marketplace signer into the released hosted client's signer interface and never imports `eth-account`, Web3, chain config, or raw key fields into core orchestration.

If a role explicitly chooses `eip191`, it may use the same underlying key for marketplace proof and a chain wallet only when configuration says so. No implicit derivation or role-key reuse is required.

### Wire carriers and persistence use principals, not address aliases

Negotiation request/response and message history, listing publishers, accepted terms, heartbeat evidence, settlement parties, hosted start/status/reclaim, service-peer bindings, and run logs carry `{scheme, identifier}`. Address fields used by chain mechanism payloads remain explicitly named EVM fields inside those mechanism envelopes and are not interpreted as marketplace principals.

Registry Alembic and storefront SQLite migrations validate every address-shaped identity, convert it to `eip191`, preserve stable publisher/listing/negotiation/obligation/operation IDs, and retire old columns in one schema boundary. Versioned run-log migration performs the same conversion before recovery. Any malformed or conflicting population aborts the migration transaction.

### Service response authentication composes the same identity capability

The active service-to-service authentication change should retain its trust pins, replay reservations, lease ownership, and signed responses, but consume the kit principal/signer and version 2 canonical primitives. Service authorities may use Ed25519 unless an independent chain effect requires EIP-191. This change will amend that active design before code so no EIP-191-only middleware or duplicate envelope is introduced.

### Hosted identity stays in the hosted client

`kit/hosted-settlement` adapts the marketplace `Signer` to the public interface of the exact manifest-pinned `hosted-settlement-client`. It does not reimplement hosted headers, canonicalization, principal models, Ed25519, EIP-191, response verification, Account Link behavior, or provider concepts. Startup checks the hosted manifest advertises the required identity contract before publishing a fiat option.

The two protocols may share cryptographic schemes but have different domain separation and release ownership. Byte-for-byte reuse across protocols is intentionally not assumed.

## Risks / Trade-offs

- **[Breaking every authenticated route creates coordination risk]** → Release clients and migrations first, quiesce mutations, migrate registry/storefront state, deploy all authorities and role clients against version 2, verify trust/readiness, then reopen. No downgrade fallback.
- **[Cross-service rotation can partially complete]** → Bounded overlap, idempotent intents, per-authority status, and retire-last sequencing preserve access until convergence.
- **[A generic signer leaks private material through config or serialization]** → Signers expose only identity/sign operations; secrets are injected separately and excluded from Pydantic carriers, run logs, database rows, diagnostics, and reprs.
- **[EIP-191 chain fields are confused with marketplace identity]** → Address validators live only in the EIP-191 identity plugin or tagged EVM mechanism models; generic code handles principals opaquely.
- **[Hosted and marketplace canonicalization drift]** → Each owning package supplies its own conformance fixtures; the thin adapter uses the hosted client API rather than translating wire bytes.
- **[Existing active change duplicates middleware]** → Reconcile `service-identity-signing` artifacts as an explicit implementation prerequisite and run dependency-boundary tests before editing runtime code.
- **[One identity across roles increases blast radius]** → Sharing is a user choice for marketplace continuity, not a requirement. Role authorization remains explicit and separate credentials remain supported.

## Migration Plan

1. Reconcile `service-identity-signing` planning artifacts with the shared scheme-neutral v2 contract without changing its authority and replay guarantees.
2. Publish a new `market-identity` wheel with strict models, Ed25519/EIP-191 signer/verifier plugins, request/response/rotation fixtures, and conformance tests.
3. Migrate registry client/server to injected signers and v2 body-bound routes; apply the transactional publisher/listing identity migration.
4. Migrate core buyer/storefront, negotiation, heartbeat, settlement, and service-peer carriers and stores; migrate versioned recovery logs.
5. Migrate VM, API-credit, and bare-metal composition roots and shared domain contract fixtures without enabling new settlement mechanisms.
6. Pin the sibling hosted identity release and update the thin adapter/startup capability check.
7. Implement credential/identity configuration consumed by the following `unify-settlement-mechanism-configuration` change; do not keep wallet aliases in the new APIs.
8. Run package, migration, role, domain conformance, cross-repository, and exact-artifact tests, including one no-wallet hosted-fiat E2E.
9. Coordinate production cutover: quiesce authenticated mutations, back up owned databases/run logs, migrate, deploy authorities and clients, verify replay/trust/identity readiness, then resume.
10. Roll back only before the identity schema cutover. After provider or settlement operations resume on v2, recover by roll-forward against the migrated identities rather than restoring stale operation state.

## Design Promotion Record

| Accepted decision | Permanent location |
|---|---|
| Canonical principals and scheme-neutral signer/verifier contracts live in the identity kit | `openspec/specs/marketplace-identity/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md` |
| Version 2 signatures bind role, principal, operation/resource, request identity, time, and body | `openspec/specs/marketplace-identity/{spec,architecture}.md`; affected protocol specs |
| Rotation uses old/new proofs, bounded overlap, idempotent per-authority convergence, and retire-last ordering | `openspec/specs/marketplace-identity/{spec,architecture}.md` |
| Marketplace identity is independent of optional chain wallet/configuration | `openspec/specs/{marketplace-identity,buyer-orchestration,settlement-servicing}/`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Address-bearing durable state migrates atomically to explicit `eip191` principals | `openspec/specs/{registry-discovery,negotiation-protocol,storefront-publication,deployment-state}/` |
| Hosted identity/signature wire remains owned by the manifest-pinned hosted client | `openspec/specs/{settlement-servicing,market-composition,deployment-state}/`; `docs/development/ARCHITECTURE.md` |
| Service-peer authentication consumes the same identity kit while preserving separate role/trust bindings | `openspec/specs/{marketplace-identity,storefront-publication}/`; `docs/development/ROADMAP.md#goal-3--one-storefront-serving-several-compute-family-domains` |
| Deployment separates public identities from signer secrets and optional chain credentials | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/{DEPLOYMENT_AND_CONFIG,TESTING}.md` |
