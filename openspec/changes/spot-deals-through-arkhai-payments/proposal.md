## Why

Arkhai payments' first product is spot, interruptible deals paid from prepaid credits, not fixed-interval deals. A spot deal's mandate is a `rate` part with `until: stop`. The service reserves funds one quantum ahead per part, and the deal stops when a part can't reserve its next quantum (credits exhausted), or when an entitled party stops it. A payee stop at time *t* settles usage to *t*; a payer stop settles through *t* plus the seller's declared exposure (`agreed-evidence-and-early-termination` D5). `settle-through-arkhai-payments` settles only `once` parts and gates delivery on approval alone. Nothing in SCM yet watches a transaction after delivery starts, so nothing tears a VM down when its payment stops.

## What Changes

- VM interruptible listings (the existing `interruptible` offering mode) gain an `arkhai.payments.v1` option priced as a rate per period. The option carries the early-termination clause of `agreed-evidence-and-early-termination` in its `params`, including a maximum term. Its derived mandate is one `rate` part with `until: stop`; `stop` authorities are derived from the clause's entitlements, and `start` is the payee's alone.
- The VM seller's payment stage is the hosted adapter of that change's lifecycle kit. It calls `start` when service begins, and end service runs while the VM lives. It tears down by the transaction's funded-through time unless the funding extends, and immediately on a stop event. Restart recomputes the deadline from the signed snapshot.
- Seller preemption posts a `notice` event and stops once the notice period has passed; buyer cancellation is the buyer's own `stop` at the payments service.
- Spot and on-demand differ only in entitlements. An on-demand option gives the payee no stop entitlement, so the seller is not a `stop` authority; an exceptional end such as failed hardware is a dispute the seller concedes on the buyer's behalf. Reserved deals add a `once` part for the committed term.
- Bare metal and API credits keep `once` parts. Reserved and fixed-interval deals stay on `once` until prepaid credits suit them.

## Dependencies

- `agreed-evidence-and-early-termination` (design): the clause, the lifecycle kit and its hosted adapter, end service, and the evidence store this change implements against.
- Payments service `rate-parts`: rate parts with per-part periods and reservation ahead, a stop lifecycle, and the snapshot fields below.
- `route-settlement-by-mechanism` (archived 2026-10-09): the continuation lives in the VM payment seller stage.
- Snapshot verification. SCM verifies only the receipt embedded in a transaction snapshot, not the snapshot's own proof (`settle-through-arkhai-payments` design, R9). Funded-through times and stop events are snapshot state, so this change must first verify snapshot proofs and add a snapshot vector and receipt-kit fixture.

## Payments contract this builds on

The payments service's `rate-parts` contract settles the seller-side needs below:
- `fundedThrough` per transaction in the signed snapshot: the earliest current reservation across rate parts. The VM stage's teardown deadline is `min(fundedThrough, stop effective time)`.
- `reserveAhead` is a required per-part Duration term. The VM option params declare it as at least the domain's teardown time, and the SDK supplies a default.
- The stop carries an effective time, a cause (payer, payee, authority or terms) and settled amounts. Payee stops may be backdated, never future-dated, and any stop ends the whole transaction.
- Per-transaction event sequence numbers give causal order.
- Billing is per started period (period = quantum), and periods count from `start`. The first batch, including any `once` parts, is reserved at approval.
- Platform credits are `USD/6`, so payment options and derived mandates use asset `USD/6`. The examples and kit docs written for `settle-through-arkhai-payments` use `USD/2` and move to `USD/6` here; no production code hardcodes an asset.

## What the seller needs from the payments service

- **A funded-through time per transaction in the signed snapshot.** This is the end of the currently reserved quantum. With it, the seller enforces locally (deliver until funded-through, tear down unless it moves), and polling or webhooks only make teardown prompter; they aren't needed for correctness. Without it, delivery between an exhaustion and the seller noticing is unpaid, and that gap is as long as the polling interval.
- **Reservation lead at least as long as teardown.** The reserved horizon must cover the seller's teardown time. Otherwise every exhaustion leaves an unpaid tail. Per-second periods make this matter. It can be a service policy, or a per-part minimum reservation the seller declares in the option params.
- **A stop event with an authoritative effective time, a cause and the settled amount,** in the signed snapshot. Causes: payer, payee, exhaustion, dispute authority. A stop is idempotent and final.
- **Payee stop at or before now.** No future-dated stops. Backdating only reduces the payee's own revenue, so it can be allowed.
- **A `notice` event.** Notice before a seller stop is posted at the service, and the service rejects an entitled payee stop before notice plus period.
- **Payee-only `start`.** Periods count from the seller's `start`; an unstarted mandate's hold is released when its window expires.
- **A payer stop that settles through the declared exposure.**
- **Dispute file and concede.** A conceded dispute is applied mechanically, as a stop with cause dispute authority and an optional `reverse`.
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
