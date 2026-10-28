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
"Snapshot proofs are not evidence"), and the vendored vectors cover no lifecycle event.

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
  an optional `minimum_spend`. An option stating a period is billed per period;
  `derive_mandate` derives one `rate` part for it — `amount` the per-period charge,
  read from the one agreed-price accessor `negotiate-open-ended-compute-terms` defines
  (the quote for one period, rounded upward as `negotiation-driven-capacity-resize`
  requires), never from `Agreement.amount` directly; `period` and `reserveAhead` from
  the params; `hold: {until: stop}` — and keeps deriving one `once` part for an option
  without a period. `minimum_spend` is a true minimum — the buyer pays `max(minimum,
  usage)`, with a committed buyer-visible refund rule — which needs the payments
  service to draw usage down against a prepaid part; it is a required capability in the
  request to the service, and until it lands per-period options state no minimum.
  `reserve_ahead` and `period` are published as clause fields beside `window`.
- On a rate part `start` is authorized for the payee alone and `stop` for both
  parties; `reverse` stays `[payee, dispute authority]`. The kit refuses to issue a
  `start` without the delivery evidence that made it lawful, and the buyer's client
  keeps the delivery instants and the signed site event as its own evidence.
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
  service-identity rotation listed in overlap, instead of being drained; this change
  is rotation's one owner.
- **The billing horizon.** A rate part carries a `vouchedThrough` that only the payee
  advances, never past `fundedThrough`; periods begin only inside it, and when it
  lapses the service stops the transaction itself. The storefront advances it each
  cycle to at most now plus `reserve_ahead` and renews the site's lease to the same
  instant, so billing and the physical lease lapse together whatever happens to the
  storefront, and nothing accrues that the storefront did not vouch for while alive.
  This is the one capability the published contract lacks that the goal's guarantee —
  *charges after a deal's effective end are reversed before they are collected* —
  needs; its residual is stated as a buyer-visible bound: at most `reserve_ahead` past
  an end the storefront did not observe. Until the service vendors it, servicing is
  declared only under the lane profile against the proposed contract, which the
  double implements.
- `start`, `vouch`, `stop`, a partial `reverse{part, amount}`, and a `refund{part,
  amount}` beside the whole-transaction `reverse`, each keyed by the caller's journaled
  operation rather than the transaction, and a read of the transaction's events so a
  caller resolves what it already sent. The ordering rule is *reverse before stop,
  always*, which the horizon makes safe; a correction due after a stop is journaled as
  a `refund` with the outcome `unsupported` until the service provides the command,
  retried and never terminal. The service's refusal codes are classified into
  superseded, partial, permanent, acknowledged, and retry.
- Confirmation against the service's conformance vectors that the period clock runs
  from the `start` event — the mandate has no start time, and approval only reserves
  the first batch — since that is what lets billing begin at delivery.
- The registration declares, per composition, whether it runs the per-period
  continuation and against which contract — `published`, which nothing may declare
  until the horizon is vendored, or `proposed`, accepted only when the payments
  endpoint is the double and refusing every `livemode` snapshot. A per-period option
  publishes and is accepted only where servicing is declared, and settlement
  materialization refuses a rate-part mandate where it is not: three doors, one
  invariant.

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

The requirements this repository states to the service — the horizon the billing
guarantee needs, the minimum spend one feature needs, the vectors the design verifies
against, two questions, and what it would welcome — are listed in `design.md`,
"Requests to the payments service"; the horizon is recorded as the goal's external
dependency in `ROADMAP.md`, Goal 8, and the index names the follow-on that waits on
it.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing` (mandate derivation, snapshot verification, the
lifecycle calls, the horizon), `settlement-configuration` (the option params, clause
fields, and the servicing declaration), `test-compatibility` (the evidence class),
`buyer-orchestration` (what the buyer's client keeps). `.openspec.yaml` sets
`skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Anything a storefront does with a verified snapshot — renewing a lease, terminating
  on a stop, issuing `start` at delivery, issuing the payee stop at a lease's end:
  [`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/).
- The in-lane double: [`add-arkhai-payments-lane-double`](../add-arkhai-payments-lane-double/).
- The listing terms that make a deal per-period or preemptible:
  `negotiate-open-ended-compute-terms`.
- Metered quantities other than time; reserved or fixed-interval deals on rate parts;
  push delivery of stop events (the `transaction-webhooks` idea can replace polling
  later without changing this contract).
- Postpaid monthly invoicing, which is outside the goal.

## Dependencies and Related Changes

- Depends on `add-arkhai-payments-lane-double`, so every operation here is proven
  against the double from the first round. The payments service's `rate-parts`
  contract it once waited on is vendored.
- Reads the agreed-price accessor `negotiate-open-ended-compute-terms` D2 defines,
  which that change's design session freezes before this one derives from it; the
  index records no dependency, since the accessor's unit contract is one line.
- `route-settlement-by-mechanism` (archived 2026-10-09) placed the payment seller
  stage each domain's continuation extends.
- `fix-refresh-payments-contract` (archived 2026-10-21) vendored the contract and left
  rate-part derivation here.

## Compatibility

No backwards-compatibility promise. A per-period option is a new option shape with a
new option ID; existing prepaid options and mandates are unchanged.

## Impact

`kit/arkhai-payments` (mandates, client, receipts, fixtures, vectors, README,
examples), `core/buyer`'s evidence record, and `e2e-tests`' payment settings. No
domain code.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `settlement-servicing`,
  `settlement-configuration`, `test-compatibility`, `buyer-orchestration`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A per-period option derives a `rate` part with `until: stop`; the per-period charge
  is the agreed price for one period, read through the one accessor —
  `settlement-servicing` spec.
- The billing horizon: nothing accrues that the storefront did not vouch for while
  alive; the guarantee and its one bounded residual; reverse before stop —
  `settlement-servicing` spec and architecture companion.
- `start` is the payee's, with evidence; the buyer keeps the delivery instants —
  `settlement-servicing` spec; `buyer-orchestration` spec.
- A service-identity rotation is an overlap under which running deals re-anchor —
  `settlement-servicing` spec; `DEPLOYMENT_AND_CONFIG.md`.
- A snapshot is evidence only once verified, bound, and ordered, replacing the
  companion's "Snapshot proofs are not evidence" paragraph — `settlement-servicing`
  architecture companion.
- The period clock runs from the `start` event, so billing begins when the payee
  declares delivery — `settlement-servicing` spec.
- A servicing declaration names its contract; qualification against a proposed
  contract is not live evidence — `settlement-configuration` and `test-compatibility`
  specs.
