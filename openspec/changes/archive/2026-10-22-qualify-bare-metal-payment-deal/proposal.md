## Why

The bare-metal payment buyer and seller had no connected-system scenario proving a complete fixed-term deal settled through Arkhai payments. Running one against a payments target found that `market bare-metal buy` and `market bare-metal request-introduction` both failed at the end of every agreed negotiation: each serialized the accepted provision terms as a model, and the bare-metal buyer receives them as a plain dictionary.

## What Changes

- A bare-metal lane scenario, `e2e_bare_metal_payment_deal`, of three ordered calls against a configured payments target: purchase and receipt-gated mock delivery; re-drive of the original run's settlement through `settle_agreement`; seller refund, then separate physical teardown. The canonical Alkahest mock deal is unchanged. Without a configured, ready target the scenario is a named blocked skip, which is what the pipeline runs.
- The scenario cleans up after a failure as it does after success: it refunds and tears down any deal still outstanding, and every cleanup step runs whatever an earlier one did, with the held loops resumed last.
- Both bare-metal buyer commands serialize accepted provision terms through the negotiation outcome's own serializer, with unit-level regression tests.
- The bare-metal buyer CLI keeps the validated seller principals it read and asserts the delivery sink boundary it relies on.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: a configured bare-metal payment purchase is qualified end to end, leaves nothing behind on failure, and is blocked without a target.

## Dependencies and Related Changes

- Implemented as PR #275, stacked on PR #272 (`fix-credits-payment-opening-amount`, archived), whose shared payments helper the scenario uses.
- `unbacked-bare-metal-listings` replaces bare metal's direct loop pauses with shared module-scoped holds and a source check refusing direct pause calls; this scenario's supply fixture pauses directly, so that change converts it with the other bare-metal modules.

## Non-Goals

- Real SSH access and revocation, which belong to the protected real-host lane.
- Live payment qualification, which stays with the payments service's own end-to-end tests.
- A bare-metal settle command, or any change to settlement design.

## Impact

Touches the bare-metal lane's scenarios and its Makefile selection, `e2e-tests/pyproject.toml`'s markers, the bare-metal buyer CLI and its tests, `e2e-tests/README.md`, and `docs/development/TESTING.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `test-compatibility`
- [ ] New subsystem specification
- [x] `docs/development/TESTING.md` and `e2e-tests/README.md` — the bare-metal payment scenario

### Knowledge to promote

- The configured bare-metal payment purchase, its cleanup contract, and its blocked skip (D1–D7) — `openspec/specs/test-compatibility/spec.md`, through this change's delta.
- The scenario's place in the bare-metal lane and how to run it — `docs/development/TESTING.md` and `e2e-tests/README.md`.
