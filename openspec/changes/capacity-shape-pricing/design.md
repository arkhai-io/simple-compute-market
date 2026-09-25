# Design

## Context

Verified by inspection 2026-08-06; re-verified 2026-09-25 (see "Re-grounding" at the
end); re-verify before implementing.

- `kit/policy`'s `NegotiationContext` carries `our_reference_amount: float`.
  `bisection_middleware` converges by moving one scalar between an opening value and a
  bound. `listed_price_middleware` and the escrow-kind dispatch operate on the same
  quantity. The negotiated variable is one number.
- `kit/alkahest`'s `RateValue` carries `field`, `per`, and `value`, and
  `PER_UNIT_SECONDS` maps only `{"hour": 3600}`. `per` expresses time and nothing else
  today.
- `domains/vms/listings/pricing_resolution.py` resolves one `min_price` per GPU model
  through storefront override → pool hint → config default.
- *Superseded by `unbacked-listing-publication` (2026-09-23), which rechecks every
  published source-derived field against the listing's own source; see that change's
  design. As originally recorded:* `domains/vms/negotiation/policies.py`'s
  `has_matching_inventory_guard` compares
  `region` and `gpu_model` by equality. It does not check `gpu_count`.
- `_place_capacity_hold`'s docstring states the current arrangement is intentional and
  names its precondition: do not thread a negotiated shape through "without first
  building seller policy that can price it."
- `pools-8` already adopted the family-grouped vocabulary for the `gpu` family in
  `[pricing.defaults.gpu.<model>]`, structurally reserving `.cpu`/`.memory`/`.storage`
  without implementing them. *Superseded 2026-09-25:* the vocabulary is settled by
  `VM_CAPABILITY_SCHEMA` (`gpu`, `cpu`, `memory`, `storage`), so the dependency on
  `structured-capacity-requirements` this bullet recorded is met.

## Goals / Non-Goals

**Goals:** a seller can put a number on any admissible shape; the aggregator is
replaceable without touching negotiation; every existing negotiation prices as
before.

**Non-Goals:** protocol changes, the multiplier reinterpretation (moved to
`negotiation-driven-capacity-resize` 2026-09-25), admissibility, authoritative
feasibility, hold billing, or any second aggregator implementation.

## Decisions

### The rate lives inside the capability it prices

Rejected: a parallel rate-keyed map alongside the shape (`{"gpu": 2.20, "cpu": 0.01}`).
It is a second structure keyed by the same families, so every read has to join two
shapes and every write can desynchronize them — a family present in one and absent from
the other is representable and meaningless.

Accepted: the rate is a field of the family, next to what it describes. A GPU family
carries its model, its count, and its per-card-hour rate together. This is one
structure with one traversal, it extends to a new family by adding a family rather than
by editing two places, and it matches the family-grouped capability shape
`kit/capability-shape` defines for listing shapes and pool overrides — making rates
a second user of one shape rather than a second vocabulary.

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

### The negotiated variable becomes a rate multiplier — moved

Moved 2026-09-25 to `negotiation-driven-capacity-resize`'s `design.md` ("The
negotiated variable becomes a rate multiplier"), together with the three models it
weighed and the consequence for the seller's floor. It is that change's central
decision because it is one deployment boundary with the revised-terms field. This
change's structures are designed so that the multiplier can be applied to them, and
nothing here depends on it having been.

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

### Compatibility with existing single-rate negotiation pricing

Commercial resolution today produces one negotiation-side rate per listing. After
this change it produces a rate structure. An existing listing must remain
interpretable, and the natural reading is a structure whose only priced dimension is
the primary one — which reproduces today's price for today's shapes exactly.

This is stated as a decision rather than left implicit because the alternative — a
migration that rewrites published listings — would republish every listing in the
market for a semantically identical result.

**This reading applies to the negotiation-side rate only, and not to a published
asking rate.** `publish-indicative-listing-rates` adds a second kind of single
advertised rate: a listing-wide catalogue price on the published listing resource,
from which nothing is constructed. The two are distinct quantities. The rate
structure this change introduces is per-dimension negotiation pricing, so a seller
can price a shape a buyer proposes; the asking rate prices the one shape a listing
advertises, and is what a buyer compares on before contacting anyone.

A storefront **may** derive an asking rate by evaluating a seller's rate structure
at the listing's advertised shape, where the seller's declared policy says so. It is
not required to, and this change's structure does not replace, subsume, or
reinterpret a published asking rate as a primary-dimension rate. Reading it that way
would silently redefine a catalogue price as a negotiation rate.

## Risks / Trade-offs

- **[Linear pricing is wrong for real hardware]** → Acknowledged and accepted as a
  starting point. Mitigated by the aggregator seam and by the prohibition on
  reconstructing totals outside it.
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
4. Seller feasibility guard extended to quantitative per-dimension checks of a
   requested shape, ordered before pricing.

Every step is additive; rollback at any point is a code revert with no
published-state change. The deployment boundary (in-flight negotiations carrying a
multiplier) moved to `negotiation-driven-capacity-resize` with the reinterpretation.

## Open Questions

Both questions this section held — whether the multiplier is bounded below at 1.0,
and whether the quoted price travels on the wire per round — moved with the
multiplier to `negotiation-driven-capacity-resize` on 2026-09-25. Nothing here is
open.

## Re-grounding (2026-09-25)

- **Negotiation is a kit lifecycle.** `kit/negotiation-runtime` owns the round state
  machine and the VM storefront injects `NegotiationDomainHooks`
  (`validate_opening`, `evaluate_round`, `reference_amount`,
  `amount_from_proposal`, `proposal_from_amount`, `place_hold`, …) from
  `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`.
  `sync_negotiation.py` and `_reject_unsupported_resource_shape_request` no longer
  exist; the round-0 shape guard is `_validate_vm_opening`. The feasibility guard
  this change extends is ordered inside the VM `evaluate_round` composition, ahead
  of pricing, not in `storefront_round.py`.
- **The override tier is site-scoped.** `publish-multidimensional-listing-shape`
  replaced the pool-keyed `compute_capacity_pools` row with `kit/pool-overrides`,
  keyed by site, pool, and offering mode, whose VM terms (`min_price`, `token`,
  `max_duration_seconds`, `sla`) are validated by the VM market's contract. A
  per-dimension rate in the override tier is a widening of that contract
  (`pools-9-retire-local-physical-authority` retires the legacy row beneath it).
- **The inventory guard already rechecks every dimension of the listing.**
  `has_matching_inventory_guard` vetoes a listing whose own source no longer supports
  it, categorical and quantitative fields alike. What this change adds is a check of
  a *buyer-requested* shape against the seller's constraints, which has no meaning
  until `negotiation-driven-capacity-resize` lets a round carry one — so Section 5
  lands its predicate here and is first exercised there.
- **The vocabulary landed.** `kit/capability-shape` and `VM_CAPABILITY_SCHEMA` settle
  the family names; `settle-capacity-claim-vocabulary` (the re-scoped remainder of
  `structured-capacity-requirements`) owns only wire-name cleanup and is not a
  dependency.
- **The multiplier moved.** The decision, its alternatives, and its two open
  questions now live in `negotiation-driven-capacity-resize`, which shares the
  deployment boundary with the revised-terms field. This change is additive
  throughout.
