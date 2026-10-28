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

The goal's billing guarantee is stated once — *charges after a deal's effective end
are reversed before they are collected* — and the published payments contract cannot
keep it: a stop takes effect at receipt and releases a rate part's earned periods
toward the payee's withdrawable balance, where nothing in the contract returns them
to the payer. So the guarantee depends on two service capabilities, required and
recorded in `settle-ongoing-compute-through-arkhai-payments`: a payee stop carrying
its own effective time, and a correction entitlement after a stop. **This change is
built and closed out in full, and the composition does not declare per-period
servicing until both land**: the publication gate stays closed, no per-period listing
exists, and a small follow-on turns the product on. Its closeout records the
collection scenarios as unrun behind that explicit external blocker.

In the storefront, built once in the payments mechanism kit with the compute-family
delivery path supplying the lease handle, the delivery predicate, and the teardown
hook:

- A per-deal **continuation state record** from approval — transaction, evidence of
  approval, delivery state, last verified sequence and `observedAt`, trusted horizon,
  financial operation journal — retained under the request log's rule.
- A **continuation** over every approved, non-terminal per-period deal, as a storefront
  lifecycle loop, running **two queues** per deal in order: the physical queue
  executes every due decision in the log and reads the lease with no payments call in
  its path; the financial queue verifies the snapshot before interpreting it, treats a
  stop or an exhausted horizon as a verified end, renews an active deal to
  `fundedThrough`, and runs pending journal operations — skipping, not failing, when
  the snapshot cannot be fetched or verified. Restart recomputes every deal from its
  record, the decision log, and the snapshot.
- One **compute-family delivery path** both domains compose — commit, dispatch,
  disclosure, and activation — deriving the lease window from the accepted Agreement
  and committing against its absolute end in both domains (bare metal's commit from
  `now` retired), refusing delivery when no window remains; calling one kit-owned
  **delivery authorization** before each transition (before `start`: no stop and the
  reserved first batch verified); and driving a persistent **delivery state machine**
  — `authorized`, `start_sent`, `started`, `activated`, `available`, `active` — with a
  recovery obligation per boundary, a payer-issued `start` accepted as the start, and
  a started-but-expired lease stopped and corrected from the start instant.
- **Four access guarantees** in place of one: no disclosure after a locally committed
  end; a remote stop incorporated within one continuation interval while the
  storefront is healthy; the site's deadline bounding physical service otherwise;
  physical termination as the revocation of any credential already disclosed.
- A **financial operation journal** per deal with a cumulative target: each operation
  immutable with its own identity, a delta issued only once earlier operations are
  resolved, lost acknowledgements resolved from the snapshot, the target rising when
  the financial effective end moves earlier; half-open interval arithmetic, the
  started period charged in full and disclosed.
- The buyer's cancel attempting the **payer stop first**, then calling the end-deal
  route whether or not it succeeded; an **operator stop command** over the
  storefront's stored state that works with the process down; the stops at every
  lease's end; identity rotation re-anchoring running deals; the servicing
  declaration with its reason, and the startup rule that a storefront holding accepted
  per-period deals refuses to start without the continuation composed.
- End-to-end, in both lanes against the double built to the published contract: the
  crash matrix across the delivery state machine; a remote stop between `start` and
  disclosure and between disclosure and the next cycle, asserting the bound; buyer
  cancel before provisioning, during it, and after delivery, with and without the
  payments service reachable; restart with a durable cancel while payments is down;
  exhaustion within the funded horizon; a provision overrunning the pool's allowance;
  the seller's bound ending lease and billing; stale, wrong-transaction,
  equal-sequence, and regressed snapshots renewing nothing; a site event after a
  local termination raising the correction target; a lost acknowledgement followed
  by earlier evidence; collection between stop and correction, failing until the
  service delivers; delayed settlement against an absolute bound; the churn scenario
  labelled as accepted; a rotation window.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing` (the continuation, the gate, the stops, the
correction, rotation), `vm-storefront-fulfillment`, `market-composition` (the loop
and the capability), `buyer-orchestration` (payer stop first), `test-compatibility`.
`.openspec.yaml` sets `skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- The site's renewal field, transition, claim rule, provisioning allowance, and lapse
  policy: `renewable-compute-lease-deadlines`.
- Seller preemption: [`publish-and-preempt-spot-compute`](../publish-and-preempt-spot-compute/).
- Pooled funding and a lease pool; a storefront–site liability ledger; push delivery
  of payment events; extending a lease past its agreed end; periodic collection of a
  running deal's earnings by the seller — unowned or accepted, recorded in the goal.

## Dependencies and Related Changes

- Depends on `buyer-initiated-compute-termination` (the request log, the end-deal
  route, the `lease_ended` event), `negotiate-open-ended-compute-terms` (per-period
  deals exist), `settle-ongoing-compute-through-arkhai-payments` (rate parts,
  verified snapshots, `start`/`stop`/partial `reverse`, the double), and
  `renewable-compute-lease-deadlines` (activation and renewal).
- Externally, the two payments-service capabilities named above gate the servicing
  declaration, not this change's design, planning, or implementation; the index
  records the block on the follow-on that declares servicing.
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

- The four access guarantees, and the delivery state machine at the compute family's
  one delivery path — `settlement-servicing` spec; `fulfillment` spec and architecture
  companion.
- The billing guarantee's dependency on two service capabilities, and what turns the
  product on — `settlement-servicing` architecture companion; `ROADMAP.md`, Goal 8.
- A financial operation journal with a cumulative target conserves money under lost
  acknowledgements and later evidence — `settlement-servicing` spec.
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
