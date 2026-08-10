## Why

Negotiation today has exactly one degree of freedom. `NegotiationContext` carries
`our_reference_amount: float`; every implemented middleware — bisection, listed-price,
escrow-kind dispatch — moves that one scalar; `RateValue` scales by duration only; and
`resolve_gpu_pricing` resolves a single price per GPU model through a three-tier
override → pool-hint → config-default chain. Nothing in that machinery can answer
"what would this cost with more RAM and fewer GPUs."

Because it cannot, `_reject_unsupported_resource_shape_request` rejects any buyer who
names a shape at all, and `_place_capacity_hold`'s docstring records the reason
explicitly: seller policy prices only the listing's advertised shape, so threading a
negotiated shape through without policy that can price it "would let a buyer claim
capacity the seller never agreed to give away." The seller's own feasibility check,
`has_matching_inventory_guard`, compares only `region` and `gpu_model` by equality — it
does not check GPU count, let alone any other dimension.

Every layer below is ready: the site authority admits and matches multidimensionally,
`PhysicalSettlementScheduler` fit-checks each requested dimension, `resize_reservation`
is implemented and correct, and the Ansible playbooks build variable shapes. The
missing piece is a seller that can put a number on a shape. This change is that piece,
and it is the prerequisite the two negotiation changes are parked on.

## What Changes

- Price each capacity dimension independently at a rate per unit, and derive a shape's
  quote as the sum across dimensions scaled by duration. Independent per-unit rates are
  the deliberate starting point, not an assertion that real pricing is linear.
- Carry the rate with the capability it prices, inside the family-grouped shape
  `structured-capacity-requirements` established, rather than in a parallel
  rate-keyed structure. A family carries what it is and what it costs together:
  a GPU family with its model, count, and per-card-hour rate; a CPU family with its
  shares and per-share-hour rate.
- Make the aggregator injectable at the domain layer from a set of kit-provided
  options, so linear summation is the default rather than the only possibility, and a
  domain can adopt a different one without changes to the negotiation loop.
- **Change what is negotiated.** The listing carries a minimum acceptable rate; the
  quoted price for a shape is that rate structure evaluated against the shape; and the
  negotiated variable becomes a **rate multiplier** over the listing minimum rather
  than an absolute amount. This keeps exactly one monotone axis for the existing
  concession machinery while allowing shape to vary independently.
- Extend the seller's feasibility guard from categorical equality on `region` and
  `gpu_model` to a quantitative check across every dimension of the requested shape.
- Resolve rates through the same three-tier storefront-override → pool-hint →
  config-default precedence `pools-8` established for per-GPU-model pricing, extended
  beyond the `gpu` family.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: commercial resolution produces a per-dimension rate
  structure resolvable to a price for any admissible shape, rather than one price per
  GPU model; rates resolve through the existing three-tier precedence per dimension.
- `negotiation-protocol`: the negotiated quantity is a rate multiplier over the
  listing's minimum rate structure, so a round's concession remains comparable when the
  requested shape changes between rounds.

## Non-Goals

- Do not add the protocol field carrying a shape change between rounds, or call
  `resize_reservation`. `negotiation-driven-capacity-resize` owns both and this change
  unblocks them.
- Do not decide the admissible range for a shape. `capacity-shape-envelope` owns what
  a seller will *consider*; this change owns what it *costs*.
- Do not check whether the site can currently serve a shape.
  `negotiation-capacity-feasibility-probe` owns the authoritative check; the guard
  extended here is the seller's own commercial feasibility, evaluated before it.
- Do not price capacity holds. Billing a reservation for its held duration is the
  parked capacity-economics thread, not this change, though it will consume this
  change's rate structure when it starts.
- Do not implement non-linear or coupled aggregators. Injectability is delivered;
  exactly one implementation ships.
- Do not change escrow mechanics, obligation shapes, or settlement.

## Impact

- Affected code: `domains/vms/listings/pricing_resolution.py`,
  `domains/vms/negotiation/` (`policies.py`'s inventory guard,
  `storefront_round.py`'s chain assembly), `kit/policy` (`negotiation_middleware.py`'s
  context and the scalar middlewares' reference quantity), `kit/alkahest`'s
  `RateValue` handling, the storefront's `[pricing.defaults.*]` settings and the pool
  pricing hint.
- Affected tests: pricing resolution unit tests, negotiation policy and middleware
  suites, escrow rate construction, and e2e price assertions.
- Wire compatibility: the listing's advertised rate structure and the negotiated
  multiplier are both observable. Existing single-rate listings must remain
  interpretable — see `design.md`'s compatibility decision.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the "Discovery and negotiation" section's
      description of what a round negotiates.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`
      and `openspec/specs/negotiation-protocol/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Commercial resolution yields a per-dimension rate structure evaluable for any
  admissible shape — `openspec/specs/storefront-publication/spec.md`.
- The negotiated quantity is a multiplier over a minimum rate structure, not an
  absolute amount — `openspec/specs/negotiation-protocol/spec.md`.
- Why the negotiated variable had to change when shape became variable (concessions
  must stay comparable across rounds) — this change's `design.md`.

## Dependencies and Related Changes

- Depends on `publish-multidimensional-listing-shape`: a rate per dimension is only
  meaningful for dimensions a listing publishes, and both change the same offer
  construction path.
- Depends on `structured-capacity-requirements` for the family-grouped vocabulary the
  rate structure nests inside. That change's `design.md` already records the
  one-directional dependency for extending `[pricing.defaults.gpu.<model>]` beyond the
  `gpu` family; this change is that extension.
- Unblocks `negotiation-driven-capacity-resize` Section 2, which is explicitly parked
  until "seller negotiation policy exists to evaluate" a shape change.
- Consumes `capacity-shape-envelope`'s admissible-range check when present; the two
  are independent and can land in either order.
- The parked capacity-economics thread (billable reservations) will consume this
  change's rate structure to price a hold's burn rate; nothing here anticipates it
  beyond keeping rate evaluation callable outside the negotiation path.
