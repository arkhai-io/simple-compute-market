## Context

The payments service publishes its wire contract as a JSON Schema and a set of conformance test vectors. `kit/arkhai-payments` vendors both and generates its Pydantic models from the schema, with `extra='forbid'` on every object. The service's receipts now sign a `livemode` field, true only from a live service, and the contract has gained rate parts. The vendored copy had neither, so the generated `Receipt` model rejected every current receipt before its signature was checked.

This change was implemented before it had a change directory: the work landed as one commit on its branch and the change records it retroactively, so its design review and the rounds after it have a home.

## Goals / Non-Goals

**Goals:** receipts from the current service verify; a receipt proves payment only in the mode the deployment expects; the vendored contract is identified by content.

**Non-Goals:** rate-part settlement, automatic mode migration, live-service qualification.

## Decisions

- **D1 — Vendor the published contract unchanged except its `$id`.** The schema's `$id` becomes the neutral `urn:arkhai:payments:wire-contract`; the vectors are byte-identical. `schema/SOURCE.md` records the published schema's, the vendored schema's, and the vectors' SHA-256, so the vendored files are identified by content rather than by where they were obtained.
- **D2 — Verification compares the signed `livemode` with the caller's expectation.** `verify_receipt` takes a required `livemode` argument and fails when the receipt's signed value differs. A test-mode receipt never proves a live payment, and a live receipt never satisfies a test deployment. The field is covered by the receipt signature, so the comparison is on signed data.
- **D3 — The expectation is configuration, default `false`.** `ArkhaiPaymentsConfig.livemode` supplies it to both the buyer and seller stages. Defaulting to test mode fails closed: a deployment that does not state it is live accepts no live receipt.
- **D4 — Only `once` mandates are derived.** The rate-part definitions arrive with the vendored contract, but deriving and settling rate parts belongs to `spot-deals-through-arkhai-payments`.
- **D5 — A breaking minor version.** `verify_receipt`'s signature changed, so the kit becomes `0.3.0` and every dependent requires it.

## Risks / Trade-offs

- **[A live deployment upgrades without setting `livemode = true`]** → it refuses every receipt, failing closed; the seller quickstart shows the setting.
- **[The vendored contract drifts from the service again]** → the content hashes in `schema/SOURCE.md` make a stale copy detectable; refreshing is replacing both files, restoring the neutral `$id`, recording the hashes, and regenerating.
