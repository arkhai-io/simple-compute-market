## Why

Buyer roles currently repeat domain-local `[Identity]` parsing and direct secret resolution, so fresh runs and recovery do not share one durable credential lifecycle. A core-owned buyer profile is needed to select a stable local buyer, retain exact signer history across rotation, and safely associate authority-owned opaque payer bindings without putting secrets in marketplace state.

## What Changes

- Add a versioned XDG metadata store of named buyer profiles with stable local profile IDs, one selected profile, primary and historical canonical public principals, credential references, lifecycle state, and per-authority opaque hosted payer bindings.
- Add approved credential-reference providers for OS keyring, strict owner-readable secret files, and explicit environment references. Provider selection is exact and there is no fallback or implicit precedence between providers.
- Add core `market profile create|import|list|show|select|rotate|retire|delete` commands. Ed25519 generation stores its seed only through the selected credential provider and writes only public metadata to the profile store.
- Add explicit legacy `[Identity]` import. Import derives the principal from the referenced credential and requires an exact match before atomically writing profile metadata; duplicates, conflicts, malformed input, or unavailable secrets leave no partial profile.
- Make fresh buyer runs use the selected profile's primary signer. Make `buy --from` and `settle --from` load the exact principal recorded in the run and resolve that retained signer from profile history.
- Require dual proof for rotation, make the replacement primary for new runs, and retain the predecessor while any recoverable run or authority binding requires it. Retirement and deletion fail while required history remains.
- Cleanly migrate every shipped buyer domain/plugin and generated role configuration to the shared core resolver.
- **BREAKING**: reject direct runtime `[Identity]` and raw secret resolution after the explicit import path. Legacy identity configuration is not retained as a fallback, alias, or second precedence layer.
- Keep marketplace buyer profiles distinct from hosted payer profiles: the marketplace stores only the authority identifier and opaque payer binding required by a later hosted consumer, never Stripe Customer, PaymentMethod, mandate, provider, or action data.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `marketplace-identity`: add local buyer profile, credential-reference provider, lifecycle, rotation-history, secret-separation, and opaque hosted-binding requirements.
- `buyer-orchestration`: select and inject a profile signer for fresh runs and resolve the exact retained principal for every resumed domain command.
- `deployment-state`: add XDG store/config paths, permission requirements, headless/keyring/environment provider inputs, explicit migration, and secret-free generated configuration.
- `test-compatibility`: add deterministic profile create/import/rotate/restart/recovery, permission, failure-atomicity, and multi-domain injection evidence.

## Impact

- Identity foundation: profile and credential-provider primitives under `kit/identity/src/market_identity` plus focused unit and package-boundary tests.
- Buyer core: `core/buyer/src/core_buyer/{buyer_config.py,run_log.py,cli.py,plugins.py}` and shared orchestration/recovery tests.
- Domain buyers: VM and API-credit configuration/bootstrap/fixtures move to the injected resolver; later bare-metal buyers must consume the same contract rather than add another identity path.
- Deployment: XDG mounts, generated role config, Secret references, Compose/Helm fixtures, and headless permission checks change without adding private material to public configuration.
- Existing run logs: their explicit versioned migration remains transactional and preserves the recorded principal and operation identities.

## Non-Goals

- Buyer login or hosted account service, organization accounts, global directory, cross-device synchronization, social recovery, automatic secret export, or cloud key backup.
- Stripe Customer, PaymentMethod, mandate, funding, webhook, or provider modeling in this change.
- Implicit secret-provider fallback or continuing direct `[Identity]` resolution for compatibility.

## Permanent documentation impact

- [x] `openspec/specs/marketplace-identity/{spec,architecture}.md`
- [x] `openspec/specs/buyer-orchestration/spec.md`
- [x] `openspec/specs/deployment-state/spec.md`
- [x] `openspec/specs/test-compatibility/spec.md`
- [x] `docs/development/ARCHITECTURE.md`
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md`
- [x] `docs/development/TESTING.md`
- [x] `docs/buyer-quickstart.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Promote profile ownership, metadata/credential separation, provider contracts, rotation retention, and hosted-binding boundaries to the marketplace identity specification and architecture companion.
- Promote fresh/resumed signer selection and cross-domain injection to buyer orchestration; promote XDG, permissions, migration, and generated-config rules to deployment state.
- Promote deterministic failure-atomicity, secret-canary, and multi-domain recovery evidence to test compatibility and the repository testing guide.
- Update repository architecture and buyer/deployment documentation with the resulting current-state profile flow and clean cutover.
