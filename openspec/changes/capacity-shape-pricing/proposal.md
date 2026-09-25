## Why

Negotiation today has exactly one degree of freedom. `NegotiationContext` carries
`our_reference_amount: float`; every implemented middleware — bisection, listed-price,
escrow-kind dispatch — moves that one scalar; `RateValue` scales by duration only; and
`resolve_gpu_pricing` resolves a single price per GPU model through a three-tier
override → pool-hint → config-default chain. Nothing in that machinery can answer
"what would this cost with more RAM and fewer GPUs."

Because it cannot, the VM opening validator (`_validate_vm_opening`, injected into
`kit/negotiation-runtime` as the domain's `validate_opening` hook) rejects any buyer
who names a shape differing from the listing's, and the round-0 guard's origin records
the reason: seller policy prices only the listing's advertised shape, so threading a
negotiated shape through without policy that can price it would let a buyer claim
capacity the seller never agreed to give away. The seller's own feasibility check,
`has_matching_inventory_guard`, rechecks every published source-derived field against
the listing's own source; it has no notion of a *buyer-requested* shape because no
round can carry one.

Every layer below is ready: the site authority admits and matches multidimensionally,
`PhysicalSettlementScheduler` fit-checks each requested dimension, `resize_reservation`
is implemented and correct, and the Ansible playbooks build variable shapes. The
missing piece is a seller that can put a number on a shape. This change is that piece,
and it is the prerequisite the two negotiation changes are parked on.

## What Changes

- Price each capacity dimension independently at a rate per unit, and derive a shape's
  quote as the sum across dimensions scaled by duration. Independent per-unit rates are
  the deliberate starting point, not an assertion that real pricing is linear.
- Carry the rate with the capability it prices, inside the family-grouped
  capability shape `kit/capability-shape` defines and `VM_CAPABILITY_SCHEMA`
  instantiates, rather than in a parallel rate-keyed structure. A family carries
  what it is and what it costs together: a GPU family with its model, count, and
  per-card-hour rate; a CPU family with its shares and per-share-hour rate.
- Make the aggregator injectable at the domain layer from a set of kit-provided
  options, so linear summation is the default rather than the only possibility, and a
  domain can adopt a different one without changes to the negotiation loop.
- Advertise the listing's minimum rate structure, and keep evaluation callable
  outside the negotiation path so a quote for any admissible shape can be produced
  by anyone holding the structure and the shape.
- Extend the seller's feasibility guard to a quantitative check across every
  dimension of a *buyer-requested* shape, ordered before pricing, so a shape the
  seller will not serve is never quoted. (Until 2026-09-25 this bullet described the
  guard as categorical-only; `unbacked-listing-publication` already made it recheck
  every source-derived field of the listing's own shape.)
- Resolve rates through the same three-tier precedence `pools-8` established for
  per-GPU-model pricing — the site-scoped storefront pool override, the pool hint,
  the configured default — extended beyond the `gpu` family. The override tier is
  `kit/pool-overrides`' VM terms contract, which gains the per-dimension rate
  fields.

**Moved 2026-09-25 to `negotiation-driven-capacity-resize`:** changing what is
negotiated. The negotiated variable becoming a rate multiplier over the listing
minimum, the reinterpretation of the kit's amount hooks, and the audit of every
consumer that assumed an absolute amount are one deployment boundary with the
revised-terms field that carries a shape change between rounds, so they belong to
the change that defines that round payload. This change stays additive: after it
lands, every listing advertises a rate structure and every existing negotiation
prices exactly as before.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: commercial resolution produces a per-dimension rate
  structure resolvable to a price for any admissible shape, rather than one price per
  GPU model; rates resolve through the existing three-tier precedence per dimension.
- `negotiation-protocol`: a seller policy evaluates a requested shape's feasibility
  before pricing it. (The rate-multiplier requirement this change carried until
  2026-09-25 moved to `negotiation-driven-capacity-resize`.)

## Non-Goals

- Do not add the protocol field carrying a shape change between rounds, reinterpret
  the negotiated amount as a multiplier, or call `resize_reservation`.
  `negotiation-driven-capacity-resize` owns all three and this change unblocks them.
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

- Affected code (re-inventoried 2026-09-25): `domains/vms/listings/pricing_resolution.py`
  and `listing_shapes.py`, `domains/vms/negotiation/policies.py` (the inventory
  guard), `kit/alkahest`'s `RateValue` handling, `kit/pool-overrides`' VM terms
  contract (the override tier), the storefront's `[pricing.defaults.*]` settings
  and the pool pricing hint, and the VM storefront's `negotiation_runtime.py` where
  the guard is ordered ahead of `evaluate_round`. `kit/policy`'s middlewares are
  untouched here; their reference quantity changes meaning in
  `negotiation-driven-capacity-resize`.
- Affected tests: pricing resolution unit tests, negotiation policy suites, pool
  override validation, escrow rate construction, and e2e price assertions.
- Wire compatibility: the listing's advertised rate structure is observable.
  Existing single-rate listings must remain interpretable — see `design.md`'s
  compatibility decision. Nothing about a negotiation round changes.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the "Discovery and negotiation" section's
      description of what a round negotiates.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`
      and `openspec/specs/negotiation-protocol/spec.md` (feasibility-before-pricing only).
- [ ] New subsystem specification — none.

### Knowledge to promote

- Commercial resolution yields a per-dimension rate structure evaluable for any
  admissible shape — `openspec/specs/storefront-publication/spec.md`.
- A seller policy evaluates feasibility before pricing —
  `openspec/specs/negotiation-protocol/spec.md`.
- Why the rate lives inside the family it prices, and why evaluation goes through a
  replaceable aggregator — this change's `design.md`. (The multiplier rationale moved
  with the decision to `negotiation-driven-capacity-resize`.)

## Dependencies and Related Changes

- Depends on `publish-multidimensional-listing-shape` (archived 2026-09-25): a rate
  per dimension is only meaningful for dimensions a listing publishes, and that change
  delivered the listing shape, `kit/capability-shape`, and the site-scoped pool
  override store this change's override tier is.
- No longer depends on `structured-capacity-requirements` (2026-09-25). The
  family-grouped vocabulary the rate structure nests inside is `VM_CAPABILITY_SCHEMA`;
  the remainder of that change is now `settle-capacity-claim-vocabulary`, a wire-name
  cleanup this change does not wait on. `[pricing.defaults.<family>]` follows the
  schema's family names (`gpu`, `cpu`, `memory`, `storage`).
- Unblocks `negotiation-driven-capacity-resize`, which owns the multiplier
  reinterpretation, the revised-terms field, and the resize wiring, and consumes this
  change's rate structure and evaluation.
- Consumes `capacity-shape-envelope`'s admissible-range check when present; the two
  are independent and can land in either order.
- `billable-capacity-reservations` will consume this change's rate structure to price a
  hold's burn rate; nothing here anticipates it beyond keeping rate evaluation callable
  outside the negotiation path.
- `publish-indicative-listing-rates` publishes a distinct catalogue asking rate; see
  `design.md`'s compatibility decision for why the two are not the same quantity.
