# Design

## Context

Verified against the tree at planning time; re-verify before implementing.

- Negotiation is a kit lifecycle. `kit/negotiation-runtime` owns the round state
  machine; the VM storefront injects `NegotiationDomainHooks` (`validate_opening`,
  `evaluate_round`, `reference_amount`, `amount_from_proposal`,
  `proposal_from_amount`, `place_hold`, …) from
  `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`. The
  round-0 shape guard is `_validate_vm_opening`.
- `kit/policy`'s `NegotiationContext` carries `our_reference_amount` as one
  integer. `bisection_middleware` converges by moving one scalar between an
  opening value and a bound; `listed_price_middleware` and the escrow-kind
  dispatch operate on the same quantity. The negotiated variable is one number.
- `kit/alkahest`'s `RateValue` carries `field`, `per`, and `value`, and
  `PER_UNIT_SECONDS` maps only `{"hour": 3600}`. `per` expresses time and nothing
  else.
- `domains/vms/listings/pricing_resolution.py` resolves one `min_price` per GPU
  model through the site-scoped storefront override (`kit/pool-overrides`, keyed
  by site, pool, and offering mode; its VM terms `min_price`, `token`,
  `max_duration_seconds`, and `sla` are validated by the VM market's contract),
  then the pool hint, then the configured default. `[pricing.defaults.gpu.<model>]`
  is the only family the defaults implement.
- `has_matching_inventory_guard` in `domains/vms/negotiation/policies.py`
  rechecks every published source-derived field of a listing against the
  listing's own source, categorical and quantitative alike. It has no notion of
  a buyer-requested shape because no round can carry one.
- `kit/capability-shape` defines the family-grouped capability shape and its
  schema-driven flattening; `VM_CAPABILITY_SCHEMA` fixes the VM families `gpu`,
  `cpu`, `memory`, `storage`. Listing shapes are digested over their families.

## Goals / Non-Goals

**Goals:** a seller can put a number on any admissible shape; the aggregator is
replaceable without touching negotiation; every existing negotiation prices as
before.

**Non-Goals:** protocol changes and the multiplier reinterpretation
(`negotiation-driven-capacity-resize`), admissibility, authoritative feasibility,
hold billing, or any second aggregator implementation.

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

### The negotiated variable is unchanged here

This change advertises and evaluates a rate structure; it does not change what a
round negotiates. Making the negotiated quantity a multiplier over the advertised
minimum is one deployment boundary with the field that lets a round carry a shape,
so both belong to `negotiation-driven-capacity-resize`. The structures here are
designed so the multiplier can be applied to them, and nothing here depends on it
having been: after this change every existing negotiation prices exactly as before.

### The feasibility guard checks a requested shape, ordered before pricing

`has_matching_inventory_guard` answers "is this listing still what it says". The
predicate this change adds answers "will the seller serve this shape", taking a
requested shape and the seller's constraints, and runs inside the VM
`evaluate_round` composition ahead of pricing so a shape the seller will not serve
is never quoted. Until a round can carry a shape the requested shape is the
listing's own, so the predicate is exercised by unit tests here and first by a
counter-offer in `negotiation-driven-capacity-resize`.

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
published-state change.

## Open Questions

None. Whether the multiplier is bounded below at 1.0 and whether the quoted price
travels on the wire are `negotiation-driven-capacity-resize`'s questions.
