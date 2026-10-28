## Why

Once a deal can be per-period
([`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/)), its
mandate a `rate` part the kit can start, stop, correct, and prove
([`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)),
and its lease one the site expires unless renewed
([`renewable-compute-lease-deadlines`](../renewable-compute-lease-deadlines/)),
nothing yet renews it, stops it, or starts it. No storefront watches a transaction
after approval: VM's `VmPaymentsCoordinator` verifies the approval receipt, spawns
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

In the storefront, built once in the payments mechanism kit with each compute domain
contributing only its delivery predicate, lease handle, and teardown hook:

- A per-deal **continuation state record** from approval — transaction, evidence of
  approval, phase, `start` issued, last verified event sequence, trusted horizon, last
  delivery authorization — and a **continuation** over every approved, non-terminal
  per-period deal, as a storefront lifecycle loop on the kit loop controller. Each
  cycle, per deal: verify the current snapshot under the kit's rules before
  interpreting anything; a stop, or an active deal's `fundedThrough` not ahead, is a
  verified end, recorded as a request and terminated at once; otherwise an active
  deal's lease is renewed to `fundedThrough`, capped by the agreed end. A snapshot that
  cannot be fetched or verified renews nothing and terminates nothing; the site's lapse
  policy decides. On restart, every deal is recomputed from its record, its verified
  snapshot, and its decision log, and nothing already in the events is issued twice.
- One **compute-family delivery path** both domains compose — commit, dispatch,
  disclosure, and the activation of every lease after delivery — in place of each
  domain's own, calling one kit-owned **delivery authorization** before each
  transition: before `start`, no stop and the reserved first batch verified; at
  disclosure, the same, then `start`, so every accepted `start` corresponds to a
  recorded authorization and no access is ever granted after an authoritative stop.
  The credential read enforces the recorded decision, never a live snapshot. A deal
  found stopped before delivery takes the undelivered path: refuse access, release the
  hold or terminate, `stop` and `reverse` the reserved batch, the minimum spend under
  its committed refund rule. The rest of the compute fulfillment unification stays
  with `kit-owned-listing-and-fulfillment-lifecycles`.
- The **payee stop at every lease's end**, from the site's `lease_ended` event —
  expiry at the agreed end, lapse, termination, force-release — and the correction of
  a stop learned late inside the contract: stop first, then reverse the periods
  started after the decision's financial effective end, computed from the stopped
  snapshot; re-run when that end later moves earlier on authenticated evidence;
  charges after a deal's effective end are reversed before they are collected.
- The buyer's cancel attempts the **payer stop first**, directly at the payments
  service, then calls the end-deal route whether or not it succeeded; the request is
  recorded and the lease terminated while the payments service is unreachable, and
  the storefront's convergence issues the stop when it can.
- An **operator stop command** over the storefront's stored state — the mandate and
  transaction ID in `negotiation_threads.settlement_data`, the operator's credential —
  that works with the storefront process down, so the seller of record can always end
  billing; stopping without stopping service harms nobody but the seller.
- The request kinds `funding_ended` and `deadline` in the deal's log, with their
  financial convergence; and the `reserve_ahead` floor each domain passes the kit,
  derived from real provisioning and teardown latency plus polling, transport, and
  clock tolerance.
- The composition **declares per-period servicing**, which is what turns per-period
  publication on.
- **Identity rotation** re-anchors running deals: the configuration lists a retiring
  service identity beside the current one, each deal's first snapshot verified under
  the new identity becomes its stored evidence, status reports deals not yet
  re-anchored, and only stragglers are drained.
- End-to-end, in both lanes against the double: on-demand VM and bare-metal deals
  where continued funding does not end a lease merely because a polling interval or
  period passed; buyer cancel before provisioning, during it, and after delivery,
  with and without the payments service reachable; a payer stop between approval and
  delivery refused access; exhaustion ending the lease within the funded horizon; a
  provision that overruns the pool's budget; a storefront restart resuming the
  continuation; the seller's bound ending lease and billing; a stale,
  wrong-transaction, and regressed snapshot each renewing nothing; a site expiry
  while the storefront is down followed by the correction, and a site event arriving
  after a local termination moving the financial end earlier; a crash between `start`
  and credentials, and between stop and reversal; a rotation window with a deal
  running across it.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing` (the continuation, the gate, the stops, the
correction, rotation), `vm-storefront-fulfillment`, `market-composition` (the loop
and the capability), `buyer-orchestration` (payer stop first), `test-compatibility`.
`.openspec.yaml` sets `skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- The site's renewal field, transition, claim rule, provisioning budget, and lapse
  policy: `renewable-compute-lease-deadlines`.
- Seller preemption: [`publish-and-preempt-spot-compute`](../publish-and-preempt-spot-compute/).
- Pooled funding and a lease pool; a storefront–site liability ledger; push delivery
  of payment events; extending a lease past its agreed end — unowned, recorded in the
  goal.

## Dependencies and Related Changes

- Depends on `buyer-initiated-compute-termination` (the request log, the end-deal
  route, the `lease_ended` event), `negotiate-open-ended-compute-terms` (per-period
  deals exist), `settle-ongoing-compute-through-arkhai-payments` (rate parts,
  verified snapshots, `start`/`stop`/partial `reverse`, the double), and
  `renewable-compute-lease-deadlines` (activation and renewal).
- Takes the narrow part of the compute fulfillment unification
  `kit-owned-listing-and-fulfillment-lifecycles` proposes — the three protected
  transitions and the access rule — and leaves it the rest.
- `redesign-storefront-stage-events` decides the event vocabulary the continuation
  emits into; the decision log is authoritative regardless.
- `redesign-authenticated-requests` changes the request envelope the new routes and
  the renewal call sign under; recheck their contracts against its decisions.

## Impact

`kit/arkhai-payments`' seller stage; a compute-family delivery path (its home decided
in design: the family kit, or `kit/fulfillment` if it proves family-neutral) that both
compute storefronts compose in place of their own commit, dispatch, and disclosure
code; both storefronts' payment coordinators, settlement compositions, loop
registrations, and operator CLIs; `core/buyer`'s and both buyers' settle paths; the
compute deal stages and the new per-period scenarios in both lanes.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Release", "Settlement servicing", and
  "Deciding which party is authoritative"
- [x] Existing subsystem specification: `settlement-servicing`,
  `vm-storefront-fulfillment`, `market-composition`, `buyer-orchestration`,
  `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- No access is granted after an authoritative stop, and every `start` corresponds to
  a durable delivery authorization, enforced at the compute family's one delivery path
  — `settlement-servicing` spec; `fulfillment` spec.
- Stopping payment first is always safe for the buyer, reclaiming first is always safe
  for the seller's hardware, and the storefront reconciles whichever came first —
  `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing`
  architecture companion.
- The storefront renews only on verified funding and terminates on a verified end;
  a lapse is only ever the unverifiable case — `settlement-servicing` spec and
  architecture companion.
- The continuation's cadence plus teardown fits inside `reserve_ahead` —
  `settlement-configuration` spec.
- The seller's stop lever works with the storefront process down —
  `settlement-servicing` spec.
