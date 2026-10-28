## Why

The per-period compute products are built in full and switched off. Their billing
guarantee — *charges after a deal's effective end are reversed before they are
collected* — rests on a billing horizon the payee advances
([`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)
D5), which the published `arkhai.payments.v1` contract lacks; until the service ships
it, no production composition declares per-period servicing, so no per-period option
is published, accepted, or materialized anywhere, and every per-period scenario in the
lanes runs against the double's proposed contract and is recorded as qualification
against a proposed contract, never as live evidence.

This is the change that turns the product on, the last of the roadmap goal that sells
compute by the period until either party stops
([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)).
It is tracked now so the goal's external blocker has a row, and it cannot begin until
the payments service publishes the horizon.

## What Changes

- Vendor the service's contract revision carrying the horizon — schema and vectors
  together, through `kit/arkhai-payments/schema/SOURCE.md` as every revision is — and
  re-verify the in-lane double against the published vectors before anything else:
  the double's proposed extension was an approximation, and the first task is to find
  where it was wrong.
- Adjust the kit's `vouch`, the lapse semantics, and the refusal table to the
  contract as published; adjust the `refund` kind to whatever post-stop correction the
  revision carries, or leave it `unsupported` if none.
- Declare per-period servicing against the `published` contract in both compute
  compositions' production profiles, retiring the lane-only `proposed` declaration
  if the revision makes it redundant.
- Run every per-period scenario in both lanes as live evidence, and the payment
  scenarios against the service's own test deployment where one is configured; the
  closeout records them as live evidence, the evidence class the goal's completion
  criterion names.
- Update the roadmap's Goal 8 and the index: the goal is complete when this change
  closes out.

## Capabilities

### Modified Capabilities

Expected: `settlement-servicing`, `settlement-configuration`, `test-compatibility`.
`.openspec.yaml` sets `skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Any product change: the terms, the continuation, the delivery path, and preemption
  are their own changes', built and closed out before this one begins.
- Capabilities the goal records as welcome rather than required — the effective-time
  stop, the post-stop refund, the prorated final period, periodic collection — which
  are taken up where the revision provides them and otherwise stay requests.

## Dependencies and Related Changes

- Depends on `discover-open-ended-compute-listings` (a product anyone can find),
  `converge-ongoing-compute-leases` (the continuation), and
  `publish-and-preempt-spot-compute` (preemption).
- Blocked in design on the payments service publishing the billing horizon; the index
  row says so, and `settle-ongoing-compute-through-arkhai-payments`' design states the
  requirement.

## Impact

`kit/arkhai-payments`' vendored schema and vectors, the double, both compute
compositions' production profiles, the lane reports, `ROADMAP.md`, and the index.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Settlement servicing", the product on
- [x] Existing subsystem specification: `settlement-servicing`,
  `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Per-period servicing is declared against the published contract; what the horizon
  guarantees — `settlement-servicing` spec and architecture companion.
- The scenario diagrams `converge-ongoing-compute-leases` drew — promoted to
  `docs/development/diagrams/`.
