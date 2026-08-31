## Why

Marketplace identity is already modeled as a scheme-tagged principal, but every shipped signer and several registry, buyer, negotiation, storefront, heartbeat, and settlement call sites still require an EIP-191 private key or address-shaped claim. A hosted-fiat buyer or seller therefore cannot publish, negotiate, settle, and recover end to end without an EVM wallet even though no blockchain operation is involved.

## What Changes

- Add a durable marketplace-identity capability with canonical principals, Ed25519 and EIP-191 signer/verifier plugins, one body-bound request-signature contract, role authorization, key rotation/revocation semantics, and public/secret configuration separation.
- Make Ed25519 the mandatory non-chain scheme for registry publishers, storefronts, buyers, provisioning/service peers, heartbeat emitters, and hosted-settlement callers while retaining EIP-191 as an explicit scheme.
- **BREAKING** replace address-shaped request claims, EIP-191-only helpers, embedded registry signatures, and operation/resource-only proofs with scheme-tagged principals and versioned method/path/body/request/timestamp-bound authentication; unknown or legacy wire versions fail closed after coordinated migration.
- **BREAKING** migrate registry publisher identities, listing ownership, negotiation parties/messages, settlement parties/evidence, request replay records, service-peer bindings, and run-log recovery records from bare addresses or unversioned keys to canonical principals.
- Let buyer and storefront roles select a local signing identity independently of `[Wallet]` and `[Chains]`. Alkahest/EAS paths may still require a separate EVM wallet for their chain effects; a hosted-fiat path does not.
- Generalize registry-client, core buyer/storefront, settlement runtime, and shipped domain composition APIs to accept injected identity signers instead of private-key strings and to authorize complete principals rather than matching identifier text.
- Pin and consume the independently released `hosted-settlement-client` identity contract from sibling change `add-hosted-account-identities`; map the same marketplace principal into hosted calls without copying its signing or wire implementation.
- Reconcile the active `service-identity-signing` plan before implementation so its replay, response-signing, and authority-boundary guarantees use the shared scheme-tagged identity abstraction rather than introducing a parallel EIP-191-only path.
- Add migration, conformance, package-boundary, and end-to-end evidence proving an Ed25519 seller can publish/onboard and an Ed25519 buyer can discover/negotiate/pay/settle/recover through `fiat.stripe.v1` with no wallet, chain, RPC, or gas configuration.
- Preserve the current Alkahest behavior when `eip191` and explicit chain settings are selected; this change does not make chain effects signable by Ed25519.

## Capabilities

### New Capabilities

- `marketplace-identity`: Canonical participant and service principals, supported proof schemes, signer/verifier injection, versioned authenticated request envelopes, authorization/rotation rules, and fiat-only wallet independence.

### Modified Capabilities

- `registry-discovery`: Publication and owner-scoped mutation use the shared signed-principal contract and preserve publisher identity through migration.
- `negotiation-protocol`: Buyer and seller message identity is scheme-tagged and body-bound; accepted terms preserve exact party principals.
- `buyer-orchestration`: Buyer roles use an injected marketplace identity independently of optional chain credentials and retain it through recovery.
- `storefront-publication`: Storefront publisher, buyer, administrator, and service-peer authentication becomes scheme-neutral and exact-principal authorized.
- `settlement-servicing`: Heartbeat and hosted settlement parties use canonical principals while chain-specific obligations retain explicit EVM requirements.
- `market-composition`: Identity becomes a from-below kit capability composed by roles rather than concrete EIP-191 branches in core/domain packages.
- `deployment-state`: Databases and deployments migrate identity-bearing state and separate public principals from private signing material.

## Impact

Affected packages include `kit/identity`, `core/registry-client`, `core/registry`, `core/buyer`, `core/storefront`, `kit/settlement-runtime`, `kit/hosted-settlement`, and the VM/bare-metal/API-credit composition roots and contract suites. Registry and storefront persistence, request headers/bodies, run logs, CLI/config loading, wheels, images, Helm, Compose, examples, and cross-repository release pins change.

This depends on the signed client/service contract produced by `../hosted-settlement-service/openspec/changes/add-hosted-account-identities` and precedes `unify-settlement-mechanism-configuration`. It intersects active `service-identity-signing`; that plan must be revised or completed against the shared scheme-neutral contract before this change writes code. It does not add marketplace accounts, hosted login/recovery, OIDC/passkeys, Stripe Customer storage, raw provider IDs, new settlement mechanisms, EAS semantics, or domain-specific settlement adoption beyond the already shipped VM path.

Permanent documentation destinations are `openspec/specs/marketplace-identity`, affected capability specs/architectures, `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG,TESTING}.md`, and the capability index.
