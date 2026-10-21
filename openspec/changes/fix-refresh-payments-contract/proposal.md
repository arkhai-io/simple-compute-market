## Why

`kit/arkhai-payments` vendored a payments wire contract that predated rate parts and the signed `livemode` field. Receipts from the current payments service carry `livemode`, and the generated `Receipt` model forbids unknown fields, so no receipt from the current service verified and no Arkhai payment deal could reach delivery.

## What Changes

- Vendor the payments service's current JSON Schema and conformance test vectors, record their hashes in `schema/SOURCE.md`, and regenerate the Pydantic models, including the rate-part definitions.
- `verify_receipt` takes the `livemode` the caller expects and refuses a receipt signed in the other mode, in addition to its existing signature, transaction, and Agreement checks.
- `ArkhaiPaymentsConfig.livemode`, default `false`, supplies that expectation to the buyer and seller settlement stages, and the storefront chart values schemas generated from the configuration carry it.
- Receipt and snapshot fixtures sign `livemode`; the local service example passes the expected mode.
- `arkhai-kit-arkhai-payments` becomes `0.3.0`, since `verify_receipt`'s signature changed, and every dependent's requirement and lock follows.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settlement-configuration`: `[Settlement.arkhai_payments]` carries the expected `livemode`, default `false`.
- `market-composition`: an Arkhai receipt verifies only when its signed `livemode` matches the verifying role's configuration.

## Dependencies and Related Changes

- Builds on the archived `settle-through-arkhai-payments`, which introduced the kit, its receipt verification, and the settlement configuration.
- `spot-deals-through-arkhai-payments` owns settling through `rate` parts. This change vendors the rate-part contract only so the models match the service; the kit still derives only `once` mandates.

## Non-Goals

- Deriving, approving, or tracking `rate` parts or stop events.
- Migrating configuration automatically between test and live modes.
- Qualifying against a live payments service, which stays with the payments service's own end-to-end tests.

## Impact

Touches `kit/arkhai-payments` (schema, vectors, generated models, receipt verification, configuration, fixtures, example, README), the payments dependency pins and locks of every domain and the end-to-end project, the seller quickstart, and the three storefront Helm values schemas.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `settlement-configuration`, `market-composition`
- [ ] New subsystem specification
- [ ] No permanent documentation change
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md`

### Knowledge to promote

- Receipt verification binds the signed `livemode` to the role's configured expectation and fails closed on a mismatch — `openspec/specs/market-composition/spec.md`, through this change's delta.
- `[Settlement.arkhai_payments].livemode` and its `false` default — `openspec/specs/settlement-configuration/spec.md`, through this change's delta.
- Setting `livemode` on upgrade, and switching mode as a cutover that drains or refunds open payment deals first — `docs/development/DEPLOYMENT_AND_CONFIG.md`'s Arkhai payments settings.
