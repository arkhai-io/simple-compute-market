# Sections 1–3 consumer checkpoint

Base: `origin/open-ended-terms` at `7f1a72cf9` (PR #351), stacked on PR #350 and PR #349. D-a–D-e and monetary D2a/signed-acceptance D2b remain unchanged.

## Installed producer contracts

`kit/arkhai-payments/schema/SOURCE.md` pins the published returned-capable per-part contract. Vendored schema SHA-256: `b7be9fb05b306de5469903ed70c6a821e5129ce757c4d20c9b6cef4e77b32e3a`; vectors SHA-256: `61cfb19e1fb85e12c58484a09f47e89878069e58e44071fb2f8c868bd5c67adf`. Its installed contract API supplies these bytes without another checkout. Snapshot/start, mixed parts, fixed/chosen partial-period stops, term ends and before/after-stop reversal fixtures are available. Producer-reported integration evidence is not hosted qualification. No interim-contract fallback or generated-model edits are authorized.

The archived foundation marks 7.5, 9.1, 10.4, 10.5, 12.1, 12.3 and 13.3 complete. It supplies snapshot verification, per-part permissions, the versioned DeliveryEvidence envelope, OperationKeys and journal seams, delivery_end intent/mapping, both concurrence signature vectors, seller filing and lifecycle reads. The adapter consumes these; it owns neither persistence nor the exceptional-end remedy.

## Terms boundary

The terms change's dependency-contracts.md is the frozen helper/declaration/timing seam. The accepted unit-bearing accessor uses monetary Agreement.amount, not a scalar or current listing; signed acceptance binds pricing. A rate mandate consumes per_period, period and reserve_ahead_seconds with optional positive setup_amount. Materialization checks the same RateServicing selection as publication/acceptance; absence/withdrawal refuses new materialization, not accepted-deal recovery. Installed compositions keep declarations empty.

## Conservative integration details

- Existing once options retain `window`. Rate presets publish `approval_window`; the parser accepts the legacy window default and refuses conflicting explicit windows. Neither is an adjudication hold.
- The actual published schema requires PartEnd.partialPeriod on *both* once and rate ends (OncePart.end references the same PartEnd). Despite the draft's statement that once ends omit it, retain the foundation's inert `returned` encoding on once/setup ends. Removing it would violate the published schema; no generated model is modified. Rate stop and end treatments remain explicit and binding.
- DeliveryEvidence is an internal trusted-composition envelope, not a site proof verifier. Validate all its identities and required activation/ready fields before rate start; the caller verifies site evidence and journals this exact envelope under the sole billing-start key. Export descriptor digests for caller write-before-call and replay comparison.

Permanent destinations remain the change's design-promotion record. Sections 4–6, hosted qualification, continuation and archival are not part of this implementation slice.
