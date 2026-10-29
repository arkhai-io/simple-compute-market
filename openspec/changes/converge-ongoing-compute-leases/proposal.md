## Why

Once a deal can be per-period
([`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/)), its
mandate a `rate` part the kit can start, vouch for, stop, correct, and prove
([`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)),
its lease one the site expires unless renewed
([`renewable-compute-lease-deadlines`](../renewable-compute-lease-deadlines/)), and
its delivery one path with a hook a mechanism may refuse
([`unify-compute-delivery-path`](../unify-compute-delivery-path/)), nothing yet
vouches, renews, stops, or starts it. No storefront watches a transaction after
approval: VM's `VmPaymentsCoordinator` verifies the approval receipt, spawns
provisioning, and does nothing after; bare metal's and credits' reconciliation passes
skip delivered deals. A buyer who stops at the payments service before delivery is
still delivered, on a historical receipt; a buyer whose funds run out after delivery
keeps the resource until the lease ends; a lease that expires at the seller's bound
stops no billing.

This is the integration point of the roadmap goal that sells compute by the period
until either party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)):
the storefront-side continuation, in both compute domains, that keeps the three
authorities — the payments service for charges, the site for the lease, the
storefront for the deal — converged on one effective end.

## What Changes

The goal's billing guarantee is stated once — *charges after a deal's effective end
are reversed before they are collected* — with its one bounded residual: a buyer may
be charged for at most the option's `reserve_ahead` past an end the storefront did
not observe. What keeps it is the **billing horizon**: the storefront vouches for
billing only as far ahead as it has verified the lease is alive and wanted, and
renews the site's lease to the same instant in the same cycle, so a dead
storefront's billing and lease lapse together. The published contract lacks the
horizon. **This change is built and closed out in full against the double's proposed
contract**, under a servicing declaration only the lane profile may make; no
production composition declares servicing, so no per-period option is published,
accepted, or materialized; every per-period scenario is recorded as qualification
against a proposed contract; and
[`activate-per-period-compute-servicing`](../activate-per-period-compute-servicing/)
turns the product on once the service ships the horizon.

In the storefront, built once in the payments mechanism kit with the delivery path
supplying the lease handle, the delivery predicate, and the teardown hook:

- A per-deal **continuation state record** from approval — transaction, evidence of
  approval, delivery state, last verified sequence and `observedAt`, trusted horizon,
  the instants last vouched and last renewed to, financial operation journal — and
  **two completion facts**, physical and financial, written by the transitions that
  earn them; a deal leaves the continuation only when both are set, and the gap
  between them is a measured, reported exposure: teardown failing after billing
  stopped (the seller's), or a correction still owed (the buyer's).
- A **continuation** over every approved, unconverged per-period deal, as a
  storefront lifecycle loop, running **two queues** per deal in order: the physical
  queue executes every due decision in the log and reads the lease with no payments
  call in its path; the financial queue verifies the snapshot before interpreting it,
  treats a stop or an exhausted horizon as a verified end, vouches and renews an
  active deal to the earliest of now plus `reserve_ahead`, `fundedThrough`, and the
  agreed end, and runs pending journal operations — skipping, not failing, when the
  snapshot cannot be fetched or verified. Restart recomputes every deal from its
  record, the decision log, and the snapshot.
- The **per-period implementation of the delivery hook**: before `start`, no stop and
  the reserved first batch verified; at `start`, the payee's `start` journaled with
  the delivery evidence and issued, one issuer; a refusal taking the undelivered path
  with the reserved batch returned; a started-but-expired lease stopped and corrected
  from the start instant.
- **Four access guarantees** in place of one: no disclosure after a locally committed
  end; a remote stop incorporated within one continuation interval while the
  storefront is healthy; the site's deadline and the horizon bounding service and
  billing to one instant otherwise; physical termination as the revocation of any
  credential already disclosed.
- A **financial operation journal** per deal with a cumulative target: kinds `start`,
  `stop`, `reverse`, `refund`; each operation immutable with its own identity, a delta
  issued only once earlier operations are resolved, the amount returned read as the
  snapshot's `reversed + refunded`, lost acknowledgements resolved from the snapshot,
  the target rising when the financial effective end moves earlier; **reverse before
  stop, always**, a post-stop correction journaled as a `refund` marked `unsupported`
  until the service provides it; half-open interval arithmetic, the started period
  charged in full for a buyer-caused end and reversed for a seller-caused one.
- The buyer's cancel attempting the **payer stop first**, then calling the end-deal
  route whether or not it succeeded; an **operator stop command** over the
  storefront's stored state that works with the process down and can close a deal's
  physical side by hand; the stops at every lease's end; rotation composed from the
  kit; the startup rule that a storefront holding accepted per-period deals refuses
  to start without the continuation composed.
- **Nine scenario diagrams** — a baseline and eight edge cases, draw.io sources with
  SVG exports — each demonstrating one guarantee, cited from the decisions and
  promoted at the follow-on's closeout.
- End-to-end, in both lanes against the double under the lane profile's `proposed`
  declaration: the nine scenarios; a remote stop between `start` and disclosure and
  between disclosure and the next cycle, asserting the bound; buyer cancel before
  provisioning, during it, and after delivery, with and without the payments service
  reachable; restart with a durable cancel while payments is down; stale,
  wrong-transaction, equal-sequence, and regressed snapshots vouching nothing; a site
  event after a local termination raising the correction target; a lost
  acknowledgement followed by earlier evidence; the churn scenario labelled as
  accepted; a rotation window.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing` (the continuation, the queues, the facts, the
journal, the stops), `market-composition` (the loop and the capability),
`buyer-orchestration` (payer stop first; the buyer's evidence), `fulfillment` (the
hook's per-period implementation), `test-compatibility`. `.openspec.yaml` sets
`skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- The site's renewal field, transition, claim rule, provisioning allowance, and lapse
  policy: `renewable-compute-lease-deadlines`.
- The delivery path, its state machine, the window, and the undelivered path:
  `unify-compute-delivery-path`.
- Seller preemption: [`publish-and-preempt-spot-compute`](../publish-and-preempt-spot-compute/).
- Pooled funding and a lease pool; a storefront–site liability ledger; push delivery
  of payment events; extending a lease past its agreed end; periodic collection of a
  running deal's earnings by the seller — unowned or accepted, recorded in the goal.

## Dependencies and Related Changes

- Depends on `buyer-initiated-compute-termination` (the request log, the end-deal
  route, the `lease_ended` event, the retention rule), `negotiate-open-ended-compute-terms`
  (per-period deals exist; the three doors), `settle-ongoing-compute-through-arkhai-payments`
  (rate parts, verified snapshots, the horizon and the operations, the servicing
  declaration), `renewable-compute-lease-deadlines` (activation and renewal), and
  `unify-compute-delivery-path` (the hook interface, the state machine, the
  undelivered path).
- Externally, the horizon gates the production servicing declaration, not this
  change's design, planning, or implementation; the index records the block on
  `activate-per-period-compute-servicing`.
- `redesign-storefront-stage-events` decides the event vocabulary the continuation
  emits into; the decision log is authoritative regardless.
- `redesign-authenticated-requests` changes the request envelope the new routes and
  the renewal call sign under; recheck their contracts against its decisions.

## Impact

`kit/arkhai-payments`' seller stage; both storefronts' payment coordinators,
settlement compositions, loop registrations, and operator CLIs; `core/buyer`'s and
both buyers' settle paths and evidence record; the compute deal stages and the new
per-period scenarios in both lanes; the scenario diagrams under this change's
`diagrams/`.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Release", "Settlement servicing", and
  "Deciding which party is authoritative"
- [x] Existing subsystem specification: `settlement-servicing`,
  `market-composition`, `buyer-orchestration`, `fulfillment`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The four access guarantees — `settlement-servicing` spec.
- The billing guarantee, its residual, and the horizon that keeps it; what turns the
  product on — `settlement-servicing` architecture companion; `ROADMAP.md`, Goal 8.
- Two completion facts per deal, the selection predicate, and the two measured gaps
  — `settlement-servicing` spec.
- A financial operation journal with a cumulative target conserves money under lost
  acknowledgements and later evidence; reverse before stop; the started period's rule
  by cause — `settlement-servicing` spec.
- Stopping payment first is always safe for the buyer, reclaiming first is always safe
  for the seller's hardware, and the storefront reconciles whichever came first —
  `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing`
  architecture companion.
- The storefront vouches and renews only on verified funding and terminates on a
  verified end; a lapse is only ever the unverifiable case — `settlement-servicing`
  spec and architecture companion.
- The continuation's cadence plus teardown fits inside `reserve_ahead` —
  `settlement-configuration` spec.
- The seller's stop lever works with the storefront process down —
  `settlement-servicing` spec.
- The scenario diagrams — `docs/development/diagrams/`, at the follow-on's closeout.
