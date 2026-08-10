# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `kit/policy`'s `NegotiationContext` carries `our_reference_amount: float`.
  `bisection_middleware` converges by moving one scalar between an opening value and a
  bound. `listed_price_middleware` and the escrow-kind dispatch operate on the same
  quantity. The negotiated variable is one number.
- `kit/alkahest`'s `RateValue` carries `field`, `per`, and `value`, and
  `PER_UNIT_SECONDS` maps only `{"hour": 3600}`. `per` expresses time and nothing else
  today.
- `domains/vms/listings/pricing_resolution.py` resolves one `min_price` per GPU model
  through storefront override → pool hint → config default.
- `domains/vms/negotiation/policies.py`'s `has_matching_inventory_guard` compares
  `region` and `gpu_model` by equality. It does not check `gpu_count`.
- `_place_capacity_hold`'s docstring states the current arrangement is intentional and
  names its precondition: do not thread a negotiated shape through "without first
  building seller policy that can price it."
- `pools-8` already adopted the family-grouped vocabulary for the `gpu` family in
  `[pricing.defaults.gpu.<model>]`, structurally reserving `.cpu`/`.memory`/`.storage`
  without implementing them. `structured-capacity-requirements`' `design.md` records
  this as a one-directional dependency: extending beyond `gpu` needs that change's
  vocabulary settled first.

## Goals / Non-Goals

**Goals:** a seller can put a number on any admissible shape; concessions stay
comparable when shape varies; the aggregator is replaceable without touching
negotiation.

**Non-Goals:** protocol changes, admissibility, authoritative feasibility, hold
billing, or any second aggregator implementation.

## Decisions

### The rate lives inside the capability it prices

Rejected: a parallel rate-keyed map alongside the shape (`{"gpu": 2.20, "cpu": 0.01}`).
It is a second structure keyed by the same families, so every read has to join two
shapes and every write can desynchronize them — a family present in one and absent from
the other is representable and meaningless.

Accepted: the rate is a field of the family, next to what it describes. A GPU family
carries its model, its count, and its per-card-hour rate together. This is one
structure with one traversal, it extends to a new family by adding a family rather than
by editing two places, and it matches the symmetric-nesting direction
`structured-capacity-requirements` already accepted for requirements and inventory —
making rates the third user of one shape rather than a fourth vocabulary.

### `RateValue.per` needs a quantity axis, not just time

`per` currently means time (`hour`), and `PER_UNIT_SECONDS` is the only interpretation.
A per-dimension rate is per *unit* per *hour* — per card-hour, per share-hour — so a
second axis is unavoidable. Two options:

1. Add a quantity dimension to `RateValue` alongside `per`.
2. Keep `RateValue` as-is and let `field` name the dimension, deriving the quantity
   from the shape at evaluation.

Option 2 is preferred: `field` already names the obligation-data slot the rate
populates, `RateValue` is on the wire and in escrow obligation data (so widening it has
the largest blast radius of anything in this change), and the quantity is already
present in the shape being priced — carrying it in the rate too would let the two
disagree. The evaluation function pairs a family's rate with that family's own quantity
by construction.

Recorded explicitly because option 1 will look simpler to anyone who has not traced
`RateValue`'s reach into settlement.

### The negotiated variable becomes a rate multiplier

This is the change's central decision and the one that is easy to get wrong.

With shape fixed, negotiating an absolute total works: each round moves one number
toward or away from a bound, and "who conceded" is well defined. With shape variable,
a total stops being comparable between rounds — a buyer who asks for less RAM and more
disk and quotes a different total has not obviously conceded, and `bisection_middleware`
has no axis to bisect.

Three models were considered:

- **Negotiate the absolute total, re-anchoring bounds whenever shape changes.**
  Rejected: every shape change resets the concession history, so a buyer can escape an
  unfavorable position by perturbing the shape. It also makes convergence
  non-terminating in the general case.
- **Fix the rates and let the buyer choose the shape.** Rejected: price becomes
  derived and there is nothing left to negotiate — this is configure-and-quote, not a
  market, and it discards the existing policy machinery entirely.
- **Accepted: negotiate a multiplier over the listing's minimum rate structure.** The
  listing advertises minimum rates; the quote for a shape is those rates evaluated
  against it; the negotiated scalar is the multiplier applied to that structure. Shape
  and price vary independently, the multiplier remains a single monotone axis, and
  `bisection_middleware` keeps working with its reference quantity reinterpreted rather
  than replaced.

A consequence worth stating: a seller's floor is expressed once, as the multiplier's
lower bound, and applies to every shape automatically. Under absolute-total
negotiation, a floor has to be recomputed per shape, which is where a shape-perturbation
attack would have entered.

### Independent per-dimension rates are a starting point, and the seam is the aggregator

Real capacity is not linearly priced — the last GPU on a host is worth more than the
first, and the roadmap's own note about reservable capacity per dimension being a
function of current occupancy applies to price as much as to availability.

Linear summation ships as the only implementation. What makes that safe is that
evaluation is reached through an injectable aggregator selected by domain
configuration, so a later non-linear or coupled aggregator is a new implementation
behind an unchanged interface rather than a rewrite of the negotiation loop. The
interface takes a shape and a resolved rate structure and returns a price; it does not
assume the price is a sum, and nothing downstream may assume it either.

Specifically: no caller may reconstruct a total by multiplying one dimension's rate by
its quantity. That shortcut would be correct today and wrong the moment a second
aggregator exists, and it is the most likely accidental coupling.

### Rate resolution reuses the three-tier precedence per dimension

`pools-8` established storefront override → pool hint → config default, resolved
independently per field. Extending that per dimension rather than inventing a second
precedence keeps one mental model, and the existing resolver already falls through
missing tiers per field — the behavior a partially-specified rate structure needs.

### Compatibility with existing single-rate listings

A listing today advertises one rate. After this change it advertises a rate structure.
An existing listing must remain interpretable, and the natural reading is a structure
whose only priced dimension is the primary one — which reproduces today's price for
today's shapes exactly.

This is stated as a decision rather than left implicit because the alternative — a
migration that rewrites published listings — would republish every listing in the
market for a semantically identical result.

## Risks / Trade-offs

- **[Linear pricing is wrong for real hardware]** → Acknowledged and accepted as a
  starting point. Mitigated by the aggregator seam and by the prohibition on
  reconstructing totals outside it.
- **[The multiplier is unintuitive to sellers who think in dollars]** → A presentation
  concern: a quoted price for a concrete shape is still what a seller and buyer see.
  The multiplier is the internal negotiated quantity, not the operator-facing knob.
- **[`bisection_middleware`'s reference quantity changes meaning]** → Contained: the
  middleware bisects a scalar between bounds regardless of that scalar's units. The
  risk is in every place that assumed the scalar was an amount in an asset's base
  units, which needs an explicit audit rather than a rename.
- **[Rate structures resolve partially and produce a price from an incomplete
  structure]** → A dimension with no resolved rate at any tier must make the shape
  unpriceable rather than free. Priced-at-zero is the dangerous default and must be
  impossible by construction.
- **[Two aggregator implementations disagree on the same shape]** → Only one ships; the
  injection point is configuration at the domain layer, so a deployment has exactly
  one.

## Migration Plan

1. Rate structure and evaluation, with the aggregator interface and its linear
   implementation, callable outside the negotiation path.
2. Rate resolution extended per dimension through the existing three tiers.
3. Listing advertisement of the minimum rate structure, with single-rate listings
   interpreted as a primary-dimension-only structure.
4. Negotiation reinterpreted: reference quantity becomes the multiplier; audit every
   consumer that assumed base units.
5. Seller feasibility guard extended to quantitative per-dimension checks.

Rollback before step 4 is a code revert with no published-state change. After step 4,
in-flight negotiations carry a multiplier and would need to drain; treat step 4 as the
deployment boundary.

## Open Questions

- **Should the multiplier be bounded below at 1.0, or may a seller policy quote under
  its own advertised minimum?** A below-minimum quote is meaningful for a seller
  clearing idle capacity, but "minimum" then stops meaning minimum. Deferrable: it is a
  policy bound, not a structural one, and changes no requirement or task here.
- **Does the quoted price need to be carried on the wire per round, or is the
  multiplier plus the shape sufficient for both sides to derive it?** Deferrable until
  `negotiation-driven-capacity-resize` defines the round payload; deriving is
  sufficient if both sides resolve identical rates, which holds only while the listing's
  advertised structure is authoritative for both.
