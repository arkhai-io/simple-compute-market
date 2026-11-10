## Why

The payments kit derives only once-only parts. `derive_mandate` builds a single
`once` part and refuses `early_termination`
(`kit/arkhai-payments/src/market_arkhai_payments/mandates.py`), and the hosted
adapter refuses rate parts outright
(`kit/arkhai-payments/src/market_arkhai_payments/adapter.py`). So no deal can be
billed per period, whatever its terms say.

The contract the kit speaks already has everything a rate part needs.
`kit/arkhai-payments/schema/SOURCE.md` records that the vendored revision
publishes per-part authorities, notice and partial-period rules, end rules,
extensions and stop-relative holds, with vectors for before- and after-start
snapshots, term ends, partial reversals and lost-response stop retry. The lane's
payments double already serves a rate engine
(`kit/arkhai-payments/src/market_arkhai_payments/fixtures/authority.py`). What is
missing is the kit's half.

This change is one of Goal 8's MVP changes (see `offer-per-period-vm-terms`'s
design for the set). It takes the rate mechanics from
[`spot-deals-through-arkhai-payments`](../spot-deals-through-arkhai-payments/) in
the reduced form the MVP needs: charged treatment only, no setup part, no
mechanical seller-fault remedy, and no identity rotation.

## What Changes

- **Rate parameters.** The payments option parameters gain `period` and
  `reserve_ahead_seconds`, validated together, and a finite term. This change's
  first task fixes them, since `offer-per-period-vm-terms` consumes them.
- **Rate mandate derivation.** `derive_mandate` derives a rate part — amount,
  period, reserve ahead, end, hold and per-part authorities — from an Agreement
  whose option is per-period, reusing `derive_part_terms(kind="rate")`, which
  already emits the payee-only start, the stop entries with their partial-period
  treatment, the end and the `afterStop` hold.
- **The buyer's exact check.** The buyer re-derives the rate mandate and refuses
  any difference before approval.
- **A rate adapter.** Start, entitled stop with notice, and reversal, each as an
  explicit per-part command with an operation-derived stable key; verified rate
  observations (started, pending stop, stop and its cause, funded-through) for
  lifecycle read and watch; refusal classification, including a start refused on
  a stopped transaction and an unknown outcome resolved by reading before another
  monetary call.
- **The authorization hook.** A pure hook answering whether commit, dispatch,
  billing start and disclosure may proceed from verified authority evidence.
- **The materialization gate.** A rate mandate is never materialized unless the
  composition declares per-period servicing.
- **Conformance.** The rate vectors replay through the kit; the adapter is proven
  against the in-process engine and the payments double.

## Capabilities

### Modified Capabilities

- `settlement-servicing`: rate mandate derivation, the rate adapter, verified rate observations, refusal classification and the authorization hook.
- `settlement-configuration`: the rate parameters and the materialization gate.
- `test-compatibility`: rate vector conformance.

### New Capabilities

None.

## Non-Goals

- `returned` or `prorated` treatment, the `chosen` dispute-stop treatment's qualification, and any local end-correction arithmetic.
- Setup parts and their return on non-delivery.
- The delivery_end self-penalty on rate parts and every other mechanical seller-fault remedy (spot task 3.5).
- Hold extension and lifting on rate parts.
- Identity rotation and re-anchoring of running deals (spot tasks 5.2–5.3).
- The buyer's watchdog (spot task 4.5a).
- Seller notice commands, the buyer's rate end and storefront composition (`serve-running-rate-deals-on-vm`).

## Impact

- Wire: rate mandates are new requests to the payments service; once-only mandates are unchanged.
- No database or deployment change. Nothing is composed into a storefront here.

## Dependencies and Related Changes

- Runs in parallel with `offer-per-period-vm-terms` and `drive-the-storefront-clock-in-lanes`; its first task fixes the rate parameters both changes use.
- `serve-running-rate-deals-on-vm` composes its adapter and hook.
- Parts taken from `spot-deals-through-arkhai-payments` (task numbers in its `tasks.md`): 1.4 (vector conformance, without the interim split), 2.1 (rate parameters, without the penalty), 2.2 (rate derivation, without setup), 2.3 (the buyer's exact check, charged by default), 2.6 (the materialization gate), 3.1 (start, stop and reverse), 3.2 (verified observations), 3.3 (descriptors and refusal classification; a matured shortfall is reported, not resolved), 3.4 (charged only), 3.6 (the authorization hook).
- Spot's design rests on an "interim revision" that predates the vendored contract; this change does not inherit that premise, and spot is rewritten against `SOURCE.md` with the rest of Goal 8.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `settlement-servicing`, `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `settlement-servicing`'s spec and architecture companion — rate derivation and the adapter's command and observation surface.
- D2: `settlement-servicing`'s spec — charged treatment as the only supported rate treatment, and refusal of the others.
- D3: `settlement-servicing/architecture.md` — the dispute stop entry as the operator's lever, and the fallback if the hosted service cannot execute `chosen`.
- D4: `deal-lifecycle/architecture.md`'s accepted limitations — earnings held until the stop plus the window — and Goal 8's accepted limitations in `docs/development/ROADMAP.md`.
