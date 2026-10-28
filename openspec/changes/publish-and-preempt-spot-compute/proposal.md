## Why

Spot compute — the cheapest price, on the understanding the seller may take the
resource back — needs a seller who can act on the interruption policy it published. The
only seller-side interruption today is the VM storefront's
`POST /api/v1/admin/deals/{escrow_uid}/interrupt`: administrator-authenticated, keyed
by an Alkahest escrow UID, admitted only for a deal whose settlement plan carries the
splitter term, and it truncates the lease (teardown waits for the watchdog) and never
submits the settlement split it announces. It looks the reservation up by `escrow_uid`
while VM deals commit with `deal_ref={negotiation_id}`, so it very likely finds nothing
for a negotiated deal. Bare metal has no seller-side end at all, and no mechanism-neutral
end-deal operation exists in the storefront kit.

This is the last change of the roadmap goal that sells compute by the period until
either party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)):
the terms exist, the deal can be settled per period and kept alive while funded, and
this change lets the seller end it under the policy the buyer accepted.

## What Changes

- A seller-authenticated **preemption route** in both compute storefronts, keyed by the
  negotiation ID and declared in the shared route contracts beside the buyer's end-deal
  route: it reads the accepted option's `interruption` from its Agreement — never
  the current listing — refuses a deal whose policy does not permit the seller to
  interrupt, fixes the effective time as now plus `notice_seconds`, appends a request
  with cause `seller_preemption` to the deal's decision log, durably schedules the end
  at that instant — the contract carries no future-effective stop, so when due the
  started period is reversed and the payee stop issued, and a storefront that is down
  then is covered by the horizon lapsing — and terminates the lease at the site then. A buyer's earlier cancel supersedes it and the scheduled stop never
  executes. A pending end is observable through the deal's status within the notice
  window; the buyer is not promised to be told. The canonical client gains the method
  and the storefront operator CLI a verb.
- The administrative override is `buyer-initiated-compute-termination`'s request kind;
  this change adds only the contractual route over it.
- Spot publication end to end: a pool offering a per-period option with
  `seller_may_interrupt: true` publishes its spot option beside its on-demand one at
  its own rate; the deal settles, runs, and is preempted with notice in both lanes
  against the in-lane double under the lane profile's `proposed` declaration, with
  the started period reversed, billing ending at the effective time, and capacity
  returned. Finding it by `--class spot` is
  [`discover-open-ended-compute-listings`](../discover-open-ended-compute-listings/)'.
- The Alkahest-only interrupt route is left as it is, with its `escrow_uid` lookup
  defect and its unsubmitted splitter declaration recorded as Alkahest's, under
  `automate-seller-spot`'s lesser goal.

## Capabilities

### Modified Capabilities

Expected: `storefront-publication` or `market-composition` (the route and the override),
`settlement-servicing` (the payee stop at a scheduled effective time),
`buyer-orchestration` (what a buyer observes of a notice), `test-compatibility`.
`.openspec.yaml` sets `skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Automated preemption strategies, active-deal views, and splitter execution:
  `automate-seller-spot`.
- Delivering notice of a pending preemption: the status read makes it observable by
  polling; a push notice is `replace-polling-with-authenticated-push`'s shape.
- A permitted-cause list for preemption, or a site-declared bound on it (rejected in
  `negotiate-open-ended-compute-terms`).
- Alkahest deals, whose interruption is the splitter model's.

## Dependencies and Related Changes

- Depends on `negotiate-open-ended-compute-terms` (the policy in the Agreement, spot
  options) and `converge-ongoing-compute-leases` (the decision log's financial
  convergence, the seller-caused end's rule, the double-backed scenarios).
- `activate-per-period-compute-servicing` depends on this change; its live evidence
  includes the preemption scenario.
- Builds on `buyer-initiated-compute-termination`'s route shape, which lands with
  `converge-ongoing-compute-leases`' dependency on it.

## Impact

Both compute storefronts' route tables and fulfillment services, the storefront client
and route contracts, both storefront operator CLIs, the kit continuation's scheduled
stop, and the spot scenarios in both lanes.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Release", the seller's end beside the
  buyer's and the site's
- [x] Existing subsystem specification: the storefront capability owning the route,
  `settlement-servicing`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A preemption is judged against the accepted deal's policy and scheduled locally
  from its notice; on-demand means no discretionary preemption, not immunity from
  infrastructure — `ARCHITECTURE.md`, "Release"; the owning storefront spec;
  `storefront-publication` architecture companion.
- Spot and on-demand share every mechanism and differ only in the policy and the
  rate — `storefront-publication` architecture companion.
