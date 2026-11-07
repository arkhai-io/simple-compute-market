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

## Evidence boundaries

What each level of evidence proves, settled across the design review (01 F2) and the implementation round (02 F2, 02 F3), and why no higher level was built:

- **The mode check is proven at the kit's stages, not in a running application.** Unit tests with an injected `FakePaymentsClient` show each stage passes its configured `livemode` to verification: each fails if its stage uses a fixed mode. The buyer's polled receipt is verified apart from its approval receipt. A domain blocking delivery on an invalid receipt was already proven by each domain's integration tests, and a wrong-mode receipt is an invalid receipt, so no domain-level mode case was added.
- **Configuration loading is proven once per role, in bare metal only.** Every path from configuration to a stage passes the whole `arkhai_payments` section through Pydantic validation and copies no field, so the risk is narrow. Bare metal is where the whole path is cheapest to exercise: the storefront's settings loader over real files into the composition the runtime builds, and the buyer's TOML loader into its configuration. The `buy` command's own composition of its approval is not separately proven.
- **Live-service qualification is not this repository's.** No payments target is reachable from its tests or pipeline lanes, so no end-to-end scenario settles through Arkhai payments or exercises the mode; the pipeline is regression evidence that the stacks deploy and run. The payments-contract evidence is the kit's tests against the published conformance vectors, which pin the signed field's framing, and `examples/local_e2e.py` against a development-mode service. Live qualification stays with the payments service, as `docs/development/ROADMAP.md#payment-qualification-boundaries` records.

## Risks / Trade-offs

- **[A live deployment upgrades without setting `livemode = true`]** → it refuses every receipt, failing closed; the seller quickstart shows the setting.
- **[An operator switches mode while payment deals are open]** → every receipt check, including the stored-receipt revalidation at restart, compares with the current `livemode`, and switching mode in practice also switches the service origin and receipt identity. A deal accepted under the old mode then stays pending against a service that never saw its transaction, or its stored receipt revalidates as invalid, so it never reaches delivery. That fails closed, but it is a cutover: operators drain or refund open payment deals before changing mode, origin, or identity. The operator reference states this (01 F3).
- **[The vendored contract drifts from the service again]** → the content hashes in `schema/SOURCE.md` make a stale copy detectable; refreshing is replacing both files, restoring the neutral `$id`, recording the hashes, and regenerating.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 — the vendored contract is identified by content hashes, its `$id` neutral | `kit/arkhai-payments/schema/SOURCE.md`; `kit/arkhai-payments/README.md` (opening paragraphs) |
| D2 — a receipt verifies only when its signed `livemode` equals the role's expectation | `openspec/specs/market-composition/spec.md#requirement-arkhai-payment-request-and-receipt-authentication`, written by the archive from this change's delta |
| D3 — the expectation is configuration, default `false` | `openspec/specs/settlement-configuration/spec.md#requirement-payments-configuration-separates-accounts-and-credentials`, written by the archive from this change's delta |
| D3 — set `livemode` for a live service; switching mode, origin, or identity is a cutover that drains or refunds open payment deals (01 F3) | `docs/development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover` |
| D4 — only `once` mandates are derived; rate parts arrive in the models only | `openspec/specs/settlement-servicing/spec.md#requirement-the-payments-mandate-is-derived-exactly-from-the-agreement` (unchanged: it already requires one `once` part); `kit/arkhai-payments/README.md` (mandate paragraph) |
| D5 — `verify_receipt`'s signature change makes the kit `0.3.0` | Git history and the pull request: provenance, not current-state documentation |
| Receipt fixtures and `FakePaymentsClient` take the `livemode` they sign | `docs/development/TESTING.md#payment-receipts-in-tests`; `kit/arkhai-payments/README.md` ("Testing with the kit") |
| Evidence boundaries — what the kit-stage, file-level, and pipeline evidence prove | This design (change history); the live-qualification boundary it relies on is `docs/development/ROADMAP.md#payment-qualification-boundaries` |
