## Why

The marketplace can negotiate and service conditional on-chain settlement, but it has no hosted fiat mechanism for buyers who pay by card and sellers who receive platform transfers. A separately operated financial authority is required so Stripe custody, provider recovery, EAS/arbiter evaluation, and secrets do not leak into marketplace carriers or domain services.

## What Changes

- Consume the separately released `arkhai-hosted-settlement-client` and its signed release manifest through a new thin `arkhai-kit-hosted-settlement` adapter registered as `fiat.stripe.v1`.
- Define one provider-neutral conditional-escrow port at the existing settlement-runtime seam; retain the current `alkahest.v1` adapter and behavior.
- Add optional `SettlementOption` and `SettlementSelection` carriers beside the existing Alkahest fields without changing legacy model dumps, routes, SDK calls, persisted escrow rows, run logs, or economics.
- Publish and negotiate VM fiat options only after account/readiness and condition-capability preflight; derive accepted settlement obligations from exact stored options.
- Add mechanism-neutral settlement start/status/reclaim routes and hosted reference/action persistence on the shared per-obligation lifecycle and work leases. Keep `/settle/{escrow_uid}` unchanged.
- Extend buyer policy ranking to compare constrained legacy escrow and hosted option candidates; add `--settlement-mechanism`, `--settlement-asset`, and `--no-browser` without provider calls before accepted terms.
- Project VM fulfillment into versioned, secret-free condition evidence and preserve fulfillment-before-claim ordering and collect-versus-reclaim exclusion.
- Pin and verify the hosted client wheel, service image, OpenAPI/conformance artifacts, manifest signature, SBOM, and provenance. Marketplace deployment config points to the external service; it does not deploy or build service source.
- **External release dependency:** implementation cannot close until `add-conditional-fiat-escrow-service` publishes an immutable signed contract manifest and matching client wheel/image.

## Capabilities

### New Capabilities

None. The new mechanism composes existing marketplace capabilities rather than creating a second marketplace lifecycle.

### Modified Capabilities

- `settlement-servicing`: provider-neutral conditional-escrow port, hosted adapter behavior, hosted lifecycle projection, and reclaim/fulfillment exclusion.
- `negotiation-protocol`: optional settlement option and accepted selection carriers with exact option matching and legacy serialization parity.
- `buyer-orchestration`: mechanism-neutral constrained ranking and hosted buyer action handling.
- `storefront-publication`: VM fiat option publication, readiness preflight, and graceful Alkahest-only degradation.
- `market-composition`: hosted adapter/client composition through the existing kit-owned runtime without forbidden authority imports.
- `deployment-state`: immutable external release consumption, configuration, packaging, and no hosted-service Deployment in this repository.

## Impact

- New code: `kit/hosted-settlement/`, additive core carriers, VM buyer/storefront integration, hosted reference columns/migrations, packaging and deployment configuration.
- Wire/API: additive optional negotiation fields and new `/api/v1/settlements` routes. Existing Alkahest wire fields and `/settle` stay byte-for-byte compatible.
- Database: additive hosted reference/action/anchor fields and indexes in shared obligation state; existing `escrows` remains untouched with no backfill or dual-read.
- Dependencies: released, hash-pinned `arkhai-hosted-settlement-client`; no Stripe SDK, RPC implementation, editable sibling path, shared database, or copied wire models.
- Deployment: VM storefront receives service URL, request credential, capability/version, and trusted-manifest configuration; external hosted image may be consumed by digest for E2E only.
- Security/authority: Stripe funds remain platform-custodied. EAS and arbiter compatibility evaluate predicates and never provide financial custody, segregated funds, or independent escrow.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specifications and architecture companions
- [x] New marketplace subsystem specification not required; hosted consumer behavior is promoted to existing capability owners
- [x] Deployment, releasing, roadmap, capability-index, and domain-authoring documentation

### Knowledge to promote

- External financial-authority and thin-adapter ownership to market composition and repository architecture.
- Additive settlement carriers and exact legacy compatibility to negotiation protocol.
- Hosted lifecycle, condition evidence, and reclaim exclusion to settlement servicing.
- VM publication, buyer selection/action, and external release pinning to their owning specs and deployment/release references.