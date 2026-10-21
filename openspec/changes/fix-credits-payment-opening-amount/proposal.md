## Why

An API-credit purchase settled through Arkhai payments could not complete end to end. Qualifying it against a payments service exposed a chain of defects, each hidden behind the one before:

- the payment scenario invoked `market credits buy` with an option the command no longer has, and its buyer configuration left out the registry trust pins and the receipt mode;
- the credits storefront stored a listing's payment options as Pydantic models rather than JSON values, so discovery returned the listing with no payment options;
- a buyer that selected a payment option reached negotiation without that option's advertised rate, so the scalar opening proposal carried no amount;
- the buy command then priced the opening and ceiling from the first legacy escrow advertised beside the payment option, in the wrong asset;
- the credits settlement payload supplied a `buyer_principal` that the shared settlement transport already binds and authenticates;
- recovering a run compared the registry's integer publisher ID with the same ID retained as text, and refused its own deal.

## What Changes

- Payment end-to-end scenarios read one explicit payments policy — service, identity, fee, dispute authority, authentication, and receipt mode — through a shared, readiness-gated helper, and the credits buyer pins both registries and emits `livemode` explicitly (PR #270).
- The credits payment scenario uses the typed resource query, and the credits storefront serializes payment options to JSON before storing a listing (PR #271).
- Shared buyer orchestration resolves a domain hook's `SettlementSelection` to the listing's advertised `SettlementOption`, so negotiation receives the selected option's rate and acceptance contract for every buyer entry point (PR #272).
- `market credits buy` selects each match's settlement proposal before pricing, and prices the opening and ceiling from the selected artifact (PR #272).
- The credits settlement payload no longer carries `buyer_principal`; the shared transport binds it (PR #272).
- Recovery compares publisher subject IDs in their retained text form (PR #272).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None recorded. The permanent `negotiation-protocol` and `settlement-servicing` specifications already require the seller's reference amount to come from the selected option's rate and an accepted Agreement to keep its exact mechanism, option, and parameters; this change repairs the buyer so it meets them.

## Dependencies and Related Changes

- Builds on the archived `fix-refresh-payments-contract`, now on `dev`, whose payments kit and `livemode` setting the scenarios configure.
- `e2e-bare-metal-payment-deal` (PR #275) is stacked on this branch and lands after it.
- PRs #270 and #271 are included in PR #272's branch; when #272 merges they are closed as included rather than merged separately.

## Non-Goals

- A new settlement mechanism policy, wire field, or schema migration.
- Republishing listings already stored with malformed payment options; an operator republishes, or local state is recreated.
- Live payment qualification, which stays with the payments service's own end-to-end tests.

## Impact

Touches `core/buyer` orchestration, the API-credit buyer's buy command and payment adapter, the API-credit storefront's listing service, the end-to-end payment scenario and its shared helper and settings, `e2e-tests/README.md`, and `docs/development/TESTING.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification — pending the design review's triage
- [ ] New subsystem specification
- [x] `docs/development/TESTING.md` — payment-scenario configuration (written by PR #270)

### Knowledge to promote

- Payment scenarios share one explicit, readiness-gated payments policy — `docs/development/TESTING.md` (written; its accuracy is under the design review's triage).
- Buyer orchestration resolves a selection to its advertised option before negotiating — destination decided in triage, if any beyond the existing specifications.
