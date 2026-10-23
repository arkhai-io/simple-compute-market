## Why

Arkhai payments' first product is spot, interruptible deals paid from prepaid credits, not fixed-interval deals. A spot deal's mandate is a `rate` part with `until: stop`. The service reserves funds one quantum ahead per part, and the deal stops when a part can't reserve its next quantum (credits exhausted), or when an entitled party stops it. A payee stop at time *t* settles usage to *t*; a payer stop settles through *t* plus the seller's declared exposure (`agreed-evidence-and-early-termination` D5). `settle-through-arkhai-payments` settles only `once` parts and gates delivery on approval alone. Nothing in SCM yet watches a transaction after delivery starts, so nothing tears a VM down when its payment stops.

## What Changes

- VM interruptible listings (the existing `interruptible` offering mode) gain an `arkhai.payments.v1` option priced as a rate per period. The option carries the `adjudication` and `early_termination` terms of `agreed-evidence-and-early-termination` in its `params`, including a maximum term. Its derived mandate is one `rate` part with `until: stop`, plus a seller-funded `bond` part when the option has one; the rate part's `stop` authorities are derived from the entitlements, and `start` is the payee's alone.
- The hosted adapter of that change gains the rate part's per-part events, translating deal-level commands into them: payer stop settled through the exposure tail, scheduled notice, exhaustion, and the maximum-term stop. End service already keeps funded-through as a renewable timer and tears down on stop events or an expired timer, and restart replays from the snapshot.
- Seller preemption posts one `notice` with an effective time at least the notice period ahead; the payments service applies the stop at that time. Buyer cancellation is the buyer's own `stop` at the payments service.
- The service stops the rate part at the absolute instant `start_utc + max_term_seconds` from the Agreement, carried in the mandate, with cause terms, so billing ends when the lease does, including on on-demand deals where the seller has no stop authority.
- Spot and on-demand differ only in entitlements. An on-demand option gives the payee no stop entitlement, so the seller is not a `stop` authority; an exceptional end such as failed hardware is a dispute the seller concedes on the buyer's behalf, stopping the rate part now and forfeiting any bond. Reserved deals add a `once` part for the committed term. Presets are combinations of parts and terms; none is special-cased.
- This change's deltas own the rate-part requirements that `agreed-evidence-and-early-termination` names but does not implement: payer stop through the exposure tail, the scheduled notice stop, the exhaustion stop, the maximum-term stop, and `reserve_ahead_seconds ≥ exposure_seconds` in force. Notice withdrawal is decided here.
- This change owns the four-path scenario: buyer stop, seller reclaim with notice, funding exhaustion, and a conceded dispute. It runs as an e2e against the payments service's public test deployment, readiness-gated, with client-side integration tests against the test double at the `kit/arkhai-payments` boundary (`docs/development/TESTING.md`, "Private Service Dependencies").
- Bare metal and API credits keep `once` parts. Reserved and fixed-interval deals stay on `once` until prepaid credits suit them.

## Dependencies

- `agreed-evidence-and-early-termination` (design): the lifecycle terms, the lifecycle kits and their hosted adapter, end service, and the evidence store this change implements against.
- Payments service `rate-parts`: rate parts with per-part periods and reservation ahead, a stop lifecycle, and the snapshot fields below.
- `route-settlement-by-mechanism` (archived 2026-10-09): the continuation lives in the VM payment seller stage.
- Snapshot verification. SCM verifies only the receipt embedded in a transaction snapshot, not the snapshot's own proof (`settle-through-arkhai-payments` design, R9). Funded-through times and stop events are snapshot state, so this change must first verify snapshot proofs and add a snapshot vector and receipt-kit fixture.

## Payments contract this builds on

The payments service's `rate-parts` contract settles the seller-side needs below:
- `fundedThrough` per transaction in the signed snapshot: the earliest current reservation across rate parts. The VM stage's teardown deadline is `min(fundedThrough, stop effective time)`.
- `reserveAhead` is a required per-part Duration term. The VM option params declare it as at least the clause's `exposure_seconds` (polling, watchdog and teardown); the option builder and buyer validation enforce that, and the SDK supplies a default.
- The stop carries an effective time, a cause (payer, payee, authority or terms) and settled amounts. Payee stops may be backdated; the only future-dated stop is a matured `notice`, applied by the service. Any stop ends the whole transaction.
- Per-transaction event sequence numbers give causal order.
- Billing is per started period (period = quantum), and periods count from `start`. The first batch, including any `once` parts, is reserved at approval.
- Platform credits are `USD/6`, so payment options and derived mandates use asset `USD/6`. The examples and kit docs written for `settle-through-arkhai-payments` use `USD/2` and move to `USD/6` here; no production code hardcodes an asset.

## What the seller needs from the payments service

- **A funded-through time per transaction in the signed snapshot.** This is the end of the currently reserved quantum. With it, the seller enforces locally (deliver until funded-through, tear down unless it moves), and polling or webhooks only make teardown prompter; they aren't needed for correctness. Without it, delivery between an exhaustion and the seller noticing is unpaid, and that gap is as long as the polling interval.
- **Reservation lead at least as long as the declared exposure.** The reserved horizon must cover the seller's whole exposure window, not only teardown, so the payer-stop tail is funded. Otherwise every exhaustion leaves an unpaid tail. Per-second periods make this matter. It can be a service policy, or a per-part minimum reservation the seller declares in the option params.
- **A stop event with an authoritative effective time, a cause and the settled amount,** in the signed snapshot. Causes: payer, payee, exhaustion, dispute authority. A stop is idempotent and final.
- **Payee stop at or before now.** Backdating only reduces the payee's own revenue, so it can be allowed.
- **A `notice` event as a scheduled stop.** The notice carries an effective time no earlier than now plus the entitlement's notice period, and the service applies the stop at that time.
- **A maximum-term stop.** The service stops the rate part at the mandate's absolute maximum end with cause terms.
- **Payee-only `start`.** Periods count from the seller's `start`; an unstarted mandate's hold is released when its window expires.
- **A payer stop that settles through the declared exposure.**
- **Dispute file and concede.** A conceded dispute is applied mechanically, through each affected part's events: the rate part stops with cause authority, a `once` part is reversed as the case requests, and a bond is forfeited.
- **Causal event order in snapshots.** The open ordering issue (events with identical `receivedAt` seconds) matters once stop and reservation events interleave.
- **A stop on any part stops the whole transaction,** and the snapshot says so. The seller must not reason per part.

## Non-Goals

- Metered quantities other than time.
- Reserved or fixed-interval deals on rate parts.
- Push delivery of stop events. It can replace polling later through the payments `transaction-webhooks` idea without changing this contract.

## Known mismatch

`Agreement` carries `amount` and `duration_seconds` at the top level, which fit one payment for a fixed term. A deal that runs until stopped has neither in that sense; this change states how they are filled (the rate and the clause's maximum term) until a schema change replaces them.

## Compatibility

There is no backwards-compatibility promise.
