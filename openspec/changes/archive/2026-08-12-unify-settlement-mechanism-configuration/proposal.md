## Why

The marketplace already runs Alkahest and hosted Stripe through the same settlement lifecycle, but operator configuration still presents Alkahest as the implicit default and hosted settlement as a separate feature block and seller executable. This makes equivalent mechanism choices look architecturally different, spreads startup policy across domain code, and forces sellers to know which command owns onboarding, readiness, publication, and recovery.

## What Changes

- Add a settlement-configuration capability with one `[Settlement]` namespace, ordered mechanism priority, and peer `[Settlement.alkahest]` and `[Settlement.stripe]` sections keyed to `alkahest.v1` and `fiat.stripe.v1`.
- Keep `[Identity]`, `[Wallet]`, and `[Chains]` outside mechanism sections: identity is role authentication, while wallet/chain resources are shared infrastructure requested only by enabled mechanisms that perform EVM effects.
- **BREAKING** move Alkahest-only policy/address-book fields and the legacy `[HostedSettlement]` block into the mechanism sections, rename environment/Helm overlays consistently, and reject old paths after an explicit idempotent config-migration command.
- Add a common mechanism status/preflight model reporting configured, enabled, ready, blocking reason, capabilities, and safe public detail without exposing credentials, provider IDs, raw URLs, chain private keys, or administrator state.
- Put seller-facing settlement administration under `market-storefront settlement`: common `status`, plus mechanism groups such as `stripe onboard|status` and `alkahest check`. Remove the separate `hosted-settlement-seller` entry point after equivalent storefront commands ship.
- Make `market-storefront publish` derive every advertised settlement option from all enabled and ready mechanisms in declared priority order; one unready mechanism is suppressed with an operator-visible reason rather than hiding ready peers.
- Make buyer `market ... buy/negotiate` selection consume the same ordered mechanism vocabulary and request wallet/chain configuration only if an EVM mechanism is selected.
- Generate `config init-user` templates and role documentation from the same typed configuration model so names, defaults, secret placement, and mechanism status cannot drift.
- Update VM settings/composition, Helm, Compose, environment overlays, examples, packaging, tests, and recovery paths. Preserve existing Alkahest and hosted financial behavior; this is a configuration/UX cutover, not a second settlement runtime.
- Depend on `add-nonchain-marketplace-identities` for `[Identity]` and signer injection and on the manifest-pinned hosted identity release it consumes. Implement only after those contracts are final.

## Capabilities

### New Capabilities

- `settlement-configuration`: Shared mechanism configuration hierarchy, precedence, validation, status/preflight, seller CLI ownership, publication derivation, buyer selection, migration, and secret/public boundaries.

### Modified Capabilities

- `settlement-servicing`: Mechanism registration and selection are driven by the common typed configuration while all mechanisms continue through one lifecycle.
- `storefront-publication`: Publication derives deterministic options from every enabled/ready mechanism and exposes unified operator status and administration.
- `buyer-orchestration`: Buyer preference and late mechanism-specific prerequisite resolution use the common mechanism vocabulary.
- `deployment-state`: TOML/environment/Helm/Compose keys migrate to one hierarchy with explicit secret placement and fail-closed readiness.
- `market-composition`: Composition roots build mechanism adapters from one registry/config contract rather than feature-specific branches or executables.

## Impact

Affected code includes `kit/config`, `kit/settlement-runtime`, `kit/{alkahest,hosted-settlement}`, `core/{buyer,storefront}`, VM buyer/storefront composition, config templates/loaders, CLI groups, Helm/Compose overlays, Makefiles/wheels/images, docs, examples, and configuration/recovery tests. The runtime settlement wire, provider authority, persisted financial operation identity, Alkahest contracts, Stripe API behavior, and non-VM domain support do not change.

The config key and command cutover is intentionally breaking. Operators run a previewable migration that preserves comments where possible, refuses conflicting old/new values, validates the result, and writes atomically with backup; services reject legacy keys afterward rather than applying hidden precedence. Permanent documentation destinations are `openspec/specs/settlement-configuration`, affected capability specs/architectures, `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG}.md`, role documentation, and the capability index.
