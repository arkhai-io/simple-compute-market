# Design

## Context

Verified against the tree at planning time; re-verify before implementing.

- Negotiation is a kit lifecycle. `kit/negotiation-runtime` owns the round state
  machine; the VM storefront injects `NegotiationDomainHooks` from
  `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`:
  `validate_opening`, `validate_continuation`, `evaluate_round`,
  `reference_amount`, `amount_from_proposal`, `proposal_from_amount`,
  `agreement_terms`, `build_artifacts`, `place_hold`.
- Continue and advance requests carry a typed `proposal`. The kit stores the
  negotiated amount as an exact integer parsed through `Decimal(str(value))`,
  never a float and never a 64-bit column.
- Round 0 carries shape data in `provision_terms.compute_resource` (the flat
  `ComputeResource`). `_validate_vm_opening` refuses an opening whose shape
  differs from the listing's on any dimension the listing declares
  (`OfferUnfulfillableError`, `resource_shape_not_negotiable`); an opening that
  omits `compute_resource` proceeds. No later round can carry a shape.
- Both storefronts ship `capacity.hold_ttl_seconds = 0`: `_place_capacity_hold`
  returns immediately, and the reservation is created at settlement from the
  settlement order, which `build_vm_accepted_artifacts` derives from the
  listing record at acceptance. The committed reservation's dimensions and
  `claim_attributes` are authoritative through scheduling and dispatch.
- `kit/site`'s `resize_reservation` supersedes a reservation with a new shape
  under the same negotiation. It has no caller.
- `kit/capability-shape` and `VM_CAPABILITY_SCHEMA` define the family-grouped
  capability shape and the VM vocabulary. `capacity-shape-pricing` advertises a
  per-dimension minimum rate structure on each listing and evaluates it for a
  shape; `capacity-shape-envelope` supplies an admissibility predicate and
  `negotiation-capacity-feasibility-probe` a non-consuming authoritative probe,
  where a domain composes them.
- `NegotiateContinueRequest` and `AdvanceRequest` in `core_storefront` carry
  no `extra="forbid"`; an undeclared top-level field is dropped. A core-level
  guard against that was tried and reverted: the risk is not a stray key but an
  unexamined nested field, and the check belongs in the domain that understands
  the content.

## Goals / Non-Goals

**Goals:** a round after the first can carry a revised capacity shape; the seller
evaluates and prices it; concessions stay comparable across a shape change; the
agreed shape is what gets reserved and built.

**Non-Goals:** pricing a shape (`capacity-shape-pricing`); deciding which shapes a
seller will consider (`capacity-shape-envelope`) or whether the site can serve
one now (`negotiation-capacity-feasibility-probe`); calling `resize_reservation`
(`negotiation-time-capacity-hold`, the change that first holds capacity before
the shape is final); round 0 adopting the family form
(`settle-capacity-claim-vocabulary`).

## Decisions

### The revised shape is a child of `proposal`, typed as the `ProvisionTerms` envelope, in the family-grouped form

A revised-terms field is a child of `proposal`, not a sibling: it is part of
what a round proposes. It reuses the existing opaque `ProvisionTerms` envelope
rather than introducing a core-level concept, so core stays schema-opaque and
the VM codec decodes the payload as a family-grouped capability shape validated
by `VM_CAPABILITY_SCHEMA`. Round 0 keeps `compute_resource`; whether it adopts
the family form is another change's question.

The payload is limited to what seller policy can price. A nested field that
passes through unexamined is an unpriced giveaway surface: a buyer could claim
disk or RAM the seller never agreed to give away because nothing checked it.

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


### The multiplier is an integer in basis points, and every amount stays exact

A multiplier is a ratio; the kit's negotiated amount is an integer. The
multiplier is carried as basis points over the advertised minimum rate
structure: 10,000 means 1.0×. The kit's `reference_amount`,
`amount_from_proposal`, and `proposal_from_amount` hooks keep their integer
contract, `bisection_middleware` converges on it unchanged, and the seller's
floor is one integer bound.

Amount arithmetic follows the rule the kit already applies: exact integers
(Python `int`) or `Decimal`, never `float`, and never a database `INTEGER`
column — an asset's base units exceed 64 bits routinely, and a wei amount that
has been through a float is a different number. The quote for a shape is
`ceil(evaluate(rates, shape, duration) × multiplier_bps / 10_000)` computed in
integers; rounding is upward so a quote is never below what the multiplier
promises the seller. A quote that would not fit the asset's amount type is
refused, not truncated.

**Floor.** The seller's floor defaults to 10,000 (1.0×, the advertised minimum)
and is a policy bound a seller may lower explicitly to clear idle capacity.
When lowered, "minimum rate structure" reads as the advertised reference
structure; the floor is still expressed once and applies to every shape.

**Wire.** The round carries the multiplier and, when it changes, the shape; the
quote is derived by both sides from the listing's advertised rate structure,
which is authoritative for both. It is not carried per round. Revisit trigger:
the advertised structure ceasing to be authoritative for both parties (a seller
repricing mid-negotiation), at which point the quote would have to travel.

### Evaluation order inside the seller's round

For a round carrying a shape, the VM `evaluate_round` composition runs, in
order: admissibility (if composed), authoritative feasibility (if composed), the
seller's commercial feasibility guard, then pricing. Each is a distinct refusal
reason on the wire, because each leads to a different counter: change the ask,
retry later, or accept the seller's counter. A domain that composes neither of
the first two negotiates shapes on price alone and says so in its composition
rather than silently.

### The agreed shape reaches the claim through the accepted artifacts

`build_vm_accepted_artifacts` writes the settlement order from the listing
record. It writes the agreed shape into the order's `listing_resource`
quantities instead, so `compute_capacity_claim_from_order` — unchanged — builds
the claim from what was agreed, and fulfillment follows the committed
reservation with no further work. `_place_capacity_hold` takes its claim from
the same agreed order, so a deployment with a non-zero `hold_ttl_seconds` holds
the agreed shape.

### `resize_reservation` is not wired here

With no pre-settlement hold there is no reservation to resize during
negotiation: the claim built at settlement from the agreed shape is reserved
fresh. A resize is needed only when a hold was placed *before* the shape was
final, and the change that introduces such a hold is
`negotiation-time-capacity-hold` (one superseded reservation per negotiation,
resized per differing-terms proposal). That change is the first caller. This
change's title names the mechanism the model described; its scope is that the
capacity shape is negotiated.

### The round-0 shape guard is retired

`_validate_vm_opening` refuses a differing round-0 shape because nothing could
price it. Once a differing shape is a proposal the seller evaluates, round 0 is
evaluated by the same composition as any later round, and the guard and its
regression tests go. The restriction was never promoted to a permanent
requirement because it was temporary by design.

### No core-level extra-field guard

`extra="forbid"` on the shared continue/advance models was implemented and
reverted. Generic top-level key hygiene in core does not protect against the
real risk, an unexamined nested field, and it belongs in the domain that
understands the content. The VM codec's schema validation of the revised shape
is that check.

## Risks / Trade-offs

- **The multiplier is unintuitive to sellers who think in currency** → a
  presentation concern; the quoted price for a concrete shape is what both
  parties see. The multiplier is the internal negotiated quantity.
- **`bisection_middleware`'s reference quantity changes meaning** → contained
  in the middleware, which bisects a scalar regardless of units. The risk is
  every consumer that assumed the scalar was an amount in base units, which
  needs an explicit audit rather than a rename.
- **In-flight negotiations at deployment** carry an absolute amount → treat
  Section 2b as the deployment boundary and drain before it.

## Migration Plan

1. Revised-terms field, kit hook widening, evaluation order, guard retirement.
2. Multiplier reinterpretation and the consumer audit. Deployment boundary.
3. Agreed shape into the accepted artifacts and the hold's claim.

Rollback before step 2 is a code revert; after it, in-flight negotiations must
drain.

## Open Questions

- **Should a seller be able to declare a listing shape-fixed** (no revised shape
  accepted), independently of the envelope? A pool with exactly one feasible
  shape is fixed by construction; a seller policy that refuses every revised
  shape achieves the rest. Leaning towards no declaration until a seller asks
  for one.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A buyer-requested round-0 VM shape differing from the listing is rejected outright until a round can carry a shape | Temporary; lifted by Section 2. Never promoted |
| Revised terms are a child of `proposal`; core reuses `ProvisionTerms` rather than adding vocabulary | `openspec/specs/negotiation-protocol/spec.md` — "A round may revise the capacity shape" |
| The negotiated quantity is a multiplier in basis points; amounts stay exact | `openspec/specs/negotiation-protocol/spec.md` — "Rate-multiplier negotiation" |
| The agreed shape is what the claim reserves | `openspec/specs/vm-storefront-fulfillment/spec.md` — "The agreed shape is reserved" |
| No core-level extra-field guard; content validation lives in the domain codec | This change's `design.md` |
