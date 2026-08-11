## Why

The VM and API-credit storefronts still run duplicated settlement-job, claim-servicing,
and failure-policy control flow, while bare metal exposes verification only. Since this
change was proposed, `add-settlement-plan-shapes` landed a stable per-obligation runtime
in `core_storefront`, but only unit tests construct it. Production still uses the older
`escrow_uid`-keyed `ClaimsEngine`, and legacy claim persistence projects into the new
obligation table. Two state machines can therefore describe the same obligation.

The prerequisite must finish as a clean cutover, not create another extraction-era
runtime. Stable obligation identity, operation leasing, uncertain acknowledgements,
collect/reclaim exclusion, retry state, and aggregate status become one kit-owned
commercial-settlement runtime. Domain composition roots supply accepted-plan semantics,
fulfillment, configuration, and failure actions. Mechanism kits supply adapters.

## What Changes

- Add `kit/settlement-runtime` (`arkhai-kit-settlement-runtime`, imported as
  `market_settlement_runtime`) as the single mechanism-neutral obligation lifecycle.
- Move the landed obligation models/runtime out of `core_storefront`; keep the storefront
  SQLite implementation as an injected persistence adapter.
- Add a durable servicing worker over obligation refs and remove the parallel
  `ClaimRecord`/`ClaimsEngine` lifecycle and its dual-write projection.
- Add a generic ordered failure-action dispatcher; VM and API credits inject their real
  capacity, event, webhook, and compensation actions.
- Compose VM and API credits onto the runtime for their existing Alkahest routes without
  changing route payloads, financial effects, fulfillment boundaries, or private result
  delivery.
- Keep bare metal's verified-only behavior explicit until it has a real fulfillment/access
  authority. It must not gain a synthetic fulfillment ref or no-op collector.
- Fold the settlement-specific composition seam into this change because
  `kit-storefront-composition-seam` has not landed in this checkout.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: commercial settlement lifecycle control flow is kit-owned and
  composed by role/domain roots; core carriers remain domain- and mechanism-neutral.
- `settlement-servicing`: one stable obligation and operation journal owns materialize,
  status reconciliation, check, collect, reclaim, retries, and aggregate status.

## Non-Goals

- Do not change the settlement-plan wire carrier, existing Alkahest routes, SDK calls,
  economics, or domain fulfillment semantics.
- Do not make VM connection details, API credentials, or future Checkout URLs part of
  generic obligation state.
- Do not make physical provisioning or credit issuance a settlement-mechanism concern.
- Do not fabricate bare-metal fulfillment or collection behavior before its access
  authority exists.
- Do not add `fiat.stripe.v1` in this prerequisite.

## Impact

- Affected code: new settlement-runtime kit; `core/storefront` lifecycle/persistence
  adapter; Alkahest adapter; VM/API-credit composition, startup, settlement jobs,
  recovery, and failure actions; bare-metal composition declaration.
- Affected tests: kit lifecycle/worker/policy suites; core SQLite adapter suites; VM,
  API-credit, and bare-metal behavior-preservation suites.
- Affected packaging: kit aggregate build, storefront dependencies/reinit targets,
  Dockerfile wheel refresh, review wheelhouse scope, and portable lockfiles.
- Persistence: existing per-obligation/operation tables remain canonical. Legacy
  `settlement_claims` is migrated once into stable obligation state before its code path is
  removed; migration is fail-closed on conflicting immutable snapshots.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — settlement runtime ownership and composition.
- [x] `docs/development/ROADMAP.md` — current-state/gap mapping.
- [x] `openspec/specs/market-composition/spec.md` — kit ownership and composition rule.
- [x] `openspec/specs/settlement-servicing/spec.md` and `architecture.md` — single
      lifecycle, worker, adapter, migration, and bare-metal boundary.

## Dependencies and Related Changes

- Depends on archived `add-settlement-plan-shapes`; its stable identity and operation
  journal are the runtime being moved and completed.
- Absorbs the settlement-specific seam that the still-active
  `kit-storefront-composition-seam` did not implement; no dependency on its unfinished
  code remains.
- Must land before `add-hosted-fiat-settlement`, which adds a second mechanism adapter at
  this seam rather than a second lifecycle.
