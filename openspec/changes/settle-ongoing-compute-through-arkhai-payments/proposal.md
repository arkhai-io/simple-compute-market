## Why

Arkhai payments' first product is compute paid per period from a prepaid balance,
funded by fiat through the payments service: the mandate carries a `rate` part with
`until: stop`, the service reserves funds one quantum ahead per part, and the
transaction stops when a part cannot reserve its next quantum, or when the buyer or the
seller stops it, settling usage to the stop's effective time. The vendored wire
contract (`kit/arkhai-payments/schema/payments.schema.json`, refreshed by
`fix-refresh-payments-contract`) already carries all of it — `RatePart{period,
reserveAhead, hold}`, `HoldUntilStop`, `TransactionSnapshot.fundedThrough`,
`TransactionStop{effectiveAt, cause, sequence, settled}`, event sequence numbers, and
`start`/`stop`/`reverse` lifecycle events — and nothing in this repository uses any of
it: `derive_mandate` builds exactly one `once` part, `PaymentsClient` has no `start` or
`stop` call, only the embedded receipt is verified and a snapshot's own proof is
documented as not evidence (`openspec/specs/settlement-servicing/architecture.md`,
"Snapshot proofs are not evidence"), the kit's `FakePaymentsClient` emits no
`fundedThrough` or stop, and the vendored vectors cover no lifecycle event.

This is the kit half of the roadmap goal that sells compute by the period until either
party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)).
Renamed from `spot-deals-through-arkhai-payments` on 2026-10-28: that proposal was
VM-only and spot-only and called `interruptible` an offering mode, which it is not — it
is an Alkahest release model and a listing flag. The payments mechanics are the same for
on-demand and spot, in both compute domains, and this change owns them; what differs
between the classes is settled in
[`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/).

## What Changes

In `kit/arkhai-payments`, and nowhere domain-specific:

- `PaymentsOptionParams` gains `period` and `reserve_ahead`, both ISO durations, and
  an optional `minimum_charge`. An option stating a period is billed per period;
  `derive_mandate` derives one `rate` part for it — `amount` the per-period charge,
  `floor(hourly amount × period / 3600)` in minor units, both sides re-deriving it from
  the Agreement's unchanged hourly `amount`; `period` and `reserveAhead` from the
  params; `hold: {until: stop}` — plus one `once` part for the minimum charge where
  stated, the enforceable minimum cost of a lease that a buyer's stop cannot recover;
  and keeps deriving one `once` part for an option without a period. `reserve_ahead`
  and `period` are published as clause fields beside `window`.
- The mandate's stop authorities stay `[payer, payee]` for both classes: the payee's
  stop is the honest way to end billing when the seller must, and a routine on-demand
  preemption is a breach remedied through `reverse` and dispute, not by removing the
  authority. `reverse` stays `[payee, dispute authority]`.
- Platform credits are `USD/6`; the kit's examples, README, and fixtures move from
  `USD/2`. No production code names an asset.
- Snapshot verification: a snapshot is evidence only once its proof verifies against
  the pinned service identity, it is bound to the expected transaction, mandate, and
  deal, its parts match the mandate's, its `observedAt` is within tolerance, and its
  event sequence has not regressed against a persisted high-water mark — with a
  snapshot vector, a fixture, and hostile tests (stale, wrong-transaction, regressed,
  post-stop), as the archived design of `settle-through-arkhai-payments` required of
  the first reader of snapshot state. A receipt embedded in a verified snapshot is
  trusted by that proof, which is what lets a running deal re-anchor across a
  service-identity rotation listed in overlap, instead of being drained.
- `start`, `stop`, and a partial `reverse{part, amount}` beside the whole-transaction
  `reverse`, each keyed by the caller's durable decision rather than the transaction,
  and a read of the transaction's events so a caller checks what was already sent.
  The stop command carries no effective time, so a stop learned late is corrected
  inside the contract: the periods earned after the effective end are reversed on the
  rate part, whose charges stay held until its stop, and then the stop is issued —
  charges after a deal's effective end are reversed before they are collected. A
  future-effective stop is scheduled durably by the caller and issued immediately
  when due.
- Confirmation against the service's conformance vectors that the period clock runs
  from the `start` event — the mandate has no start time, and approval only reserves
  the first batch — since that is what lets billing begin at delivery.
- The kit's fake grows into an in-lane HTTP double of the payments service: it serves
  approve, snapshots with verifiable proofs carrying `fundedThrough`, `stop`, and the
  event sequence, `start`, `stop`, partial and whole `reverse`, and test controls that
  exhaust a payer's funds, serve stale or wrong-transaction snapshots, regress a
  sequence, and rotate the signing identity, so every payment scenario runs in the
  pipeline instead of skipping and the hostile cases can be asserted. It is a test
  asset of the mechanism, never a stand-in for live qualification.
- The registration declares, per composition, whether it runs the per-period
  continuation; a per-period option publishes only where it does.

## Payments contract this builds on

Now vendored: `fundedThrough` per transaction in the signed snapshot, the earliest
current reservation across rate parts; `reserveAhead` a required per-part term the
option declares; a stop with the service's effective time, a cause (`payer`, `payee`,
`authority`, `terms`), and settled amounts, any stop ending the whole transaction;
per-transaction event sequence numbers; a rate part's charges held until its stop;
`reverse` taking a part and an amount; billing per started period, counted from
`start`; the first batch, including any `once` parts, reserved at approval. The
earlier proposal's note that payee stops may be backdated is not in the vendored
schema, and the design does not rely on it.

Confirmations owed to the service's published vectors before planning, each a blocker
if unpublished: the snapshot proof's frame; a partial reverse of a running rate part
before its stop, and whether after it; the period clock from `start`; a mandate
mixing `once` and `rate` parts; whether `latestEventSequence` is strictly monotonic. A
payee stop carrying its own effective time is recorded as unowned work outside this
repository in `ROADMAP.md`, Goal 8.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing` (mandate derivation, snapshot verification, the
lifecycle calls), `settlement-configuration` (the option params and clause fields),
`test-compatibility` (the in-lane double). `.openspec.yaml` sets `skip_specs` until
design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Anything a storefront does with a verified snapshot — renewing a lease, terminating
  on a stop, issuing `start` at delivery, issuing the payee stop at a lease's end:
  [`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/).
- The listing terms that make a deal per-period or preemptible:
  `negotiate-open-ended-compute-terms`.
- Metered quantities other than time; reserved or fixed-interval deals on rate parts;
  push delivery of stop events (the `transaction-webhooks` idea can replace polling
  later without changing this contract).
- Postpaid monthly invoicing, which is outside the goal.

## Dependencies and Related Changes

- Depends on nothing in this repository. The payments service's `rate-parts` contract
  it once waited on is vendored.
- `route-settlement-by-mechanism` (archived 2026-10-09) placed the payment seller
  stage each domain's continuation extends.
- `fix-refresh-payments-contract` (archived 2026-10-21) vendored the contract and left
  rate-part derivation here.

## Compatibility

No backwards-compatibility promise. A per-period option is a new option shape with a
new option ID; existing prepaid options and mandates are unchanged.

## Impact

`kit/arkhai-payments` (mandates, client, receipts, fixtures, vectors, README,
examples), the e2e lane stacks that gain the double, and `e2e-tests`' payment
settings. No domain code.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `settlement-servicing`,
  `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A per-period option derives a `rate` part with `until: stop`, and a `once` part for
  its minimum charge; the per-period charge is derived from the Agreement's hourly
  `amount` by floored exact arithmetic — `settlement-servicing` spec.
- Charges after a deal's effective end are reversed before they are collected; a
  stop's effective time is corrected by partial reversal — `settlement-servicing` spec
  and architecture companion.
- A service-identity rotation is an overlap under which running deals re-anchor —
  `settlement-servicing` spec; `DEPLOYMENT_AND_CONFIG.md`.
- A snapshot is evidence only once verified, bound, and ordered, replacing the
  companion's "Snapshot proofs are not evidence" paragraph — `settlement-servicing`
  architecture companion.
- The period clock runs from the `start` event, so billing begins when the payee
  declares delivery — `settlement-servicing` spec.
- The in-lane payments double, what it proves and what it does not —
  `test-compatibility` spec and `docs/development/TESTING.md`, "Payment Receipts in
  Tests".
