## 1. Contract prerequisites

- [x] 1.1 Reconcile `openspec/changes/service-identity-signing/{proposal,design,specs,tasks}.md` with this change: retain mutual authentication, trust pins, replay reservations, and signed responses while replacing its EIP-191-only middleware with the shared scheme-tagged version 2 contract; run strict validation before code.
- [x] 1.2 Verify the immutable sibling `add-hosted-account-identities` release and import only its signed manifest/trust record and exact `hosted-settlement-client` wheel into marketplace release inputs; record required identity/API capabilities and reject editable sibling paths.
- [x] 1.3 Inventory and name every address/private-key assumption in `kit/identity`, `core/{registry-client,registry,buyer,storefront}`, `kit/{settlement-runtime,hosted-settlement}`, domain composition roots, databases, run logs, tests, Helm, Compose, and examples in `design.md`; classify each as marketplace principal, explicit EVM effect, or removable legacy carrier.

## 2. Identity kit and authenticated envelope

- [x] 2.1 Extend `kit/identity/src/market_identity/{models,registry}.py` with strict canonical principal, signer/verifier, authenticated request/response, replay identity, and two-proof rotation contracts; expose no serializable private-key field.
- [x] 2.2 Add `kit/identity/src/market_identity/schemes/ed25519.py`, complete the EIP-191 signer beside its verifier, and update package dependencies/exports; enforce exact identifier/proof lengths, normalization, bounded decoding, and explicit scheme dispatch.
- [x] 2.3 Implement `arkhai.market-request-signature.v2` length-delimited canonicalization over role, principal, method, semantic operation/resource, request ID, timestamp, and canonical body hash; add framework-neutral verifier/replay results without persistence or HTTP imports.
- [x] 2.4 Add conformance fixtures and `kit/identity/tests/unit/` coverage for Ed25519/EIP-191 success, every field/body mutation, cross-scheme collision, malformed encodings, skew, exact replay, changed reuse, signer secret isolation, and old/unknown-version rejection.
- [x] 2.5 Build and install the identity wheel outside the monorepo and run package-boundary tests proving it imports no core role, domain, settlement, provider, Web3, or hosted-client implementation.

## 3. Registry publisher cutover

- [x] 3.1 Replace EIP-191/private-key helpers in `core/registry-client/src/registry_client/{auth,client,models}.py` with injected `market_identity.Signer`; move publish/update/delete auth to version 2 headers and body-bound request IDs with sync/async parity.
- [x] 3.2 Update `core/registry/src/api/{listing_routes,publisher_routes}.py` and persistence models to authenticate complete principals before validation, bind them to stable publishers, authorize owner mutation, and support idempotent two-proof rotation/overlap/retirement.
- [x] 3.3 Add a registry Alembic migration converting publisher identities and listing ownership from valid addresses to canonical `eip191` principals, preserving stable IDs and aborting malformed, duplicate, or referentially incomplete populations transactionally.
- [x] 3.4 Replace EIP-191-specific registry tests with scheme-parameterized unit/integration coverage for lazy Ed25519 publication, body mutation, query/embedded-signature rejection, owner isolation, migration bootstrap/upgrade/rollback, rotation convergence, and exact replay.

## 4. Buyer and storefront protocol cutover

- [x] 4.1 Refactor `core/buyer/src/core_buyer/{buyer_config,negotiation_client,orchestration,orchestrator}.py` to accept an injected marketplace signer and principal; remove `buyer_address`/`buyer_private_key` from generic request and orchestration APIs and resolve wallet/chain values only inside selected EVM adapters.
- [x] 4.2 Replace fallback/address middleware in `core/storefront/src/core_storefront/auth.py` with version 2 principal verification and replay reservation before route dispatch; adapt the reconciled service-identity response/peer flow to the same kit contracts.
- [x] 4.3 Update negotiation, settlement, heartbeat, registry-publication, and service-peer models/services in `core/storefront/src/core_storefront/` so bodies and durable records carry exact buyer/seller/service principals and never infer identity from address claims.
- [x] 4.4 Add idempotent per-authority rotation operations and client coordination for registry, storefront, service-peer, and hosted-account subjects with bounded overlap, status inspection, promote-new/retire-old ordering, and disable-without-transfer incident behavior.
- [x] 4.5 Update core buyer/storefront unit, integration, and API-security tests for Ed25519 and EIP-191, role isolation, cross-scheme collisions, body mutation, lost acknowledgements, signer mismatch during recovery, partial rotation, and legacy-wire rejection.

## 5. Identity-bearing state migration

- [x] 5.1 Add ordered migrations in `core/storefront/src/core_storefront/sqlite_migrations.py` and owned schemas for negotiation parties/messages, listings, settlement plans/obligations, heartbeats, service peers, replay reservations, claims, and audits; preserve all domain, fulfillment, lease, and operation identities.
- [x] 5.2 Version and migrate buyer/storefront run logs and recovery carriers in `core/buyer` and `core/storefront`: addresses become `eip191` principals, public principal/version is retained, private keys remain absent, and unsafe/unknown versions fail closed.
- [x] 5.3 Add fresh-bootstrap, idempotent-rerun, legacy-nonterminal, funded-hosted-obligation, malformed-population, duplicate-owner, checksum-drift, and transactional-rollback tests at each database/log owner.

## 6. Settlement and domain composition

- [x] 6.1 Update `kit/settlement-runtime` carriers and heartbeat/operation authorization to use opaque canonical principals while keeping tagged EVM addresses only inside mechanisms that perform chain effects.
- [x] 6.2 Update `kit/hosted-settlement/src/market_hosted_settlement/adapter.py` to wrap the injected marketplace signer through the exact hosted-client interface; require the manifest identity capability and delete any duplicate canonicalization, signing, response verification, or provider model.
- [x] 6.3 Migrate VM, API-credit, and bare-metal buyer/storefront composition roots, CLI handlers, settings adapters, and shared domain contract fixtures to signer injection; preserve each domain's existing settlement support and do not add hosted fiat outside VM.
- [x] 6.4 Prove an Ed25519 VM seller can publish and use its owner-bound hosted account and an Ed25519 buyer can discover, negotiate, fund, fulfill, collect/status, reclaim, and resume with `[Wallet]`, `[Chains]`, RPC, address books, token balance, and gas settings absent.
- [x] 6.5 Re-run existing Alkahest, EAS, VM, API-credit, and bare-metal paths with explicit EIP-191/chain configuration to prove mechanism behavior and package layering remain unchanged.

## 7. Deployment and release integration

- [x] 7.1 Add public `IdentityConfig` plus separately injected credential-secret resolution in the owning config packages, with fail-closed signer/principal matching and no private-key repr/log/model serialization; leave settlement namespace/CLI restructuring to `unify-settlement-mechanism-configuration`.
- [x] 7.2 Update role Helm/Compose schemas, Secret/ConfigMap boundaries, images, wheel dependencies, environment examples, and readiness capability checks for the version 2 identity contract and optional chain configuration.
- [x] 7.3 Update root review-wheelhouse scope, package locks, distribution manifests, image/release provenance, and cross-repository smoke inputs to pin the identity kit and exact hosted client release without sibling-source leakage.
- [x] 7.4 Add render/package tests proving fiat-only deployments contain public principals and Secret references but no EVM/provider credentials, and that missing signer secrets, contract drift, or old authority versions block readiness.

## 8. Verification

- [x] 8.1 Run focused identity, registry client/server, core buyer/storefront, database migration, run-log recovery, settlement runtime, hosted adapter, domain conformance, and API-security suites plus affected Ruff and mypy checks.
- [x] 8.2 Run relevant integration suites for registry publication/rotation, synchronous negotiation, service-peer authentication, heartbeat, hosted lifecycle, Alkahest regression, and restart/uncertain-acknowledgement recovery.
- [x] 8.3 Build the review wheelhouse and all affected wheels/images; install from staged wheels only; run exact manifest/provenance verification, image readiness smoke, Helm schema/render checks, and `make check`.
- [x] 8.4 Run the cross-repository no-wallet fake-provider E2E and available real Stripe test-mode onboarding/collection/refund flow with Ed25519 participants; disclose unavailable reachable-webhook, EAS-testnet, Kubernetes, or protected-publisher evidence without substitution.
- [x] 8.5 Run targeted strict validation for this and reconciled dependent changes, then repository-wide strict OpenSpec validation and report unrelated active-change failures separately.

## 9. Closeout

Per `openspec/README.md` plan-closeout requirements.

- [x] 9.1 Run `make check-comment-hygiene`; review every touched comment/docstring for current invariants and remove change IDs, task references, migration narrative, tombstones, private-key terminology in generic APIs, compatibility aliases, address fallbacks, and obsolete EIP-191-only paths.
- [x] 9.2 Review touched imports and built artifacts: identity points upward to no role/domain/mechanism, core remains schema-opaque, hosted wire stays in the released client, and chain/provider packages appear only behind owning adapters.
- [x] 9.3 Promote the new normative contract and rationale to `openspec/specs/marketplace-identity/{spec,architecture}.md` and add it to `openspec/specs/README.md`.
- [x] 9.4 Promote registry, negotiation, buyer, storefront, settlement, composition, and deployment deltas to each owning `openspec/specs/<capability>/{spec,architecture}.md`; update `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG,TESTING}.md` with current boundaries and operations.
- [x] 9.5 Record roadmap disposition in `ROADMAP.md` only if this changes an existing delivery claim, compress completed task notes to final behavior/evidence, and complete the design-promotion record in `design.md` before archive.
