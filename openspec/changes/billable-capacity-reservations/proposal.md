## Why

A capacity hold excludes every other buyer from that capacity for its duration and costs
the holder nothing. Acquiring one costs two signed HTTP requests: nothing in the
negotiation path gates hold placement on funds, an escrow, or any chain interaction,
there is no rate limiting anywhere in the storefront, there is no per-buyer concurrency
limit on negotiations, and a fresh buyer address is free to mint. A single actor could
therefore hold a storefront's entire sellable inventory indefinitely at no cost, by
negotiating, accepting, and never settling.

`default-no-pre-settlement-capacity-hold` closed that vector by denying the capability:
both storefronts now ship `hold_ttl_seconds = 0`, so capacity becomes exclusive only at
settlement. That is the correct interim posture and it is not a solution — it reopens
the window the two-phase reserve exists to close, where a buyer whose escrow has settled
finds the capacity taken, and it forecloses every improvement that depends on holding
capacity earlier. This change is what buys the capability back.

The storefront's absence of rate limiting is itself deliberate: nothing touches physical
infrastructure until payment is accepted, so there has been nothing to protect. A hold
changes that. It consumes a scarce, physical, exclusive resource before payment exists,
and shortening its window is not a mitigation — the fraction of capacity an attacker
holds is bounded by their request rate, not by the hold duration.

The right primitive is not identity-based. Capping holds per identity would block a
buyer willing to pay from holding capacity they are paying for, which is backwards in a
market, and minting identities is free anyway. The problem is that **an identity can
block other buyers' consumption of physical resources without compensation**. Charging
for held time makes the cost scale with capacity-time held rather than with identity
count, so Sybil identities buy an attacker nothing and a legitimate buyer can hold as
much as they are willing to fund.

This is also the precondition for holding capacity earlier in a negotiation, which is
where a deal should fail if it is going to fail.

## What Changes

- Give a capacity reservation a burn rate, derived from the shape it holds through the
  same rate structure that prices the shape commercially.
- Require funds committed against that rate before a hold is placed, and derive the
  hold's maximum duration from the committed amount and the burn rate rather than from a
  configured TTL. The pool's advisory hold cap becomes a ceiling on the derived value
  rather than the primary source.
- Charge for held time and return the unconsumed remainder when a hold ends early,
  through the settlement layer's existing per-obligation lifecycle rather than a
  parallel payments path.
- Recompute the burn rate and the remaining affordable duration when a reservation is
  superseded by a shape change, since a different shape burns at a different rate.
- Verify committed funds without requiring a chain write per negotiation: the seller
  either reads the buyer's committed balance or consumes a proof the buyer supplies.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: a reservation carries a burn rate and a funded duration bound, its
  maximum hold duration is derived rather than configured, and a supersede recomputes
  both.
- `settlement-servicing`: held capacity is charged as an obligation with the same
  durable per-obligation lifecycle as other obligations, with the unconsumed remainder
  returned when a hold ends early.

## Non-Goals

- Do not move where holds are placed. This change makes a hold billable wherever it is
  placed today; `negotiation-time-capacity-hold` moves it.
- Do not build a standing buyer account that outlives one negotiation. It is a
  gas-efficiency improvement over per-negotiation commitment, not a correctness
  requirement, and is a deferred follow-on.
- Do not define the rate structure — `capacity-shape-pricing` owns it. This change
  consumes it.
- Do not change what capacity is admitted, how it is matched, or how it is scheduled.
- Do not introduce identity-based rate limiting or per-identity hold caps. The pricing
  mechanism replaces the need for them, and a cap would penalize a paying buyer.
- Do not charge for a non-consuming feasibility check. Verification that reserves
  nothing excludes nobody and must remain free.

## Impact

- Affected code: `kit/site` (reservation rate and funded bound, supersede recomputation,
  expiry semantics), the storefront's hold placement and its interaction with
  `capped_hold_seconds`, `kit/alkahest` and the settlement obligation lifecycle for the
  hold obligation, and the buyer client for committing funds and supplying proof.
- Affected configuration: `hold_ttl_seconds` changes meaning from the hold's duration to
  a ceiling; the pool's `max_reservation_hold_seconds` policy tag likewise.
- Affected tests: ledger suites, settlement servicing, negotiation acceptance paths, and
  an e2e path proving a hold is charged and the remainder returned.
- Buyer-facing: committing funds becomes a precondition for holding capacity, which is a
  new step in the buy flow.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the capacity-reservation section, on what a
      hold costs and what bounds its duration.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md` and
      `openspec/specs/settlement-servicing/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- A reservation carries a burn rate; its maximum duration is derived from committed
  funds and that rate — `openspec/specs/site-capacity/spec.md`.
- Held capacity is charged as an obligation with the unconsumed remainder returned —
  `openspec/specs/settlement-servicing/spec.md`.
- Why exclusivity is priced rather than rate-limited — this change's `design.md`.

## Dependencies and Related Changes

- Depends on `capacity-shape-pricing` for the rate structure a burn rate is derived
  from, and on its requirement that price aggregation be reachable outside the
  negotiation path.
- Depends on `capacity-reservation-lifecycle-hardening`, whose bounded expiry and
  generalized idempotency are what make a larger population of billed holds tractable.
- Prerequisite for `negotiation-time-capacity-hold`. Moving holds earlier without
  billing them is exactly the uncompensated-exclusion problem this change exists to
  prevent.
- Reverses `default-no-pre-settlement-capacity-hold`. Restoring a non-zero
  `hold_ttl_seconds` default is part of this change's own work, once holding capacity
  costs the holder something; that change's spec permits the restoration explicitly.
- Reuses `add-settlement-plan-shapes`' per-obligation lifecycle. That change's interval
  escrows are generated from an accepted total, which does not exist before agreement,
  so the generation rule differs — see `design.md`.
- A standing buyer account outliving one negotiation is a deferred follow-on with no
  change opened; it reduces chain writes and changes nothing about this change's
  contracts.
