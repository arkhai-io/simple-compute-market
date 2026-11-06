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
  under the same negotiation. It has no caller. *Since 2026-10-05
  (`bare-metal-mock-provisioned-deal` 5B.8.B.3), the supersede passes the site's
  release guard, as every capacity release does. The guard frees the superseded
  reservation only when its fulfillment proves nothing was dispatched (no aggregate,
  or one still `assigned`, which it abandons), so a resize of a reservation whose
  fulfillment has begun is refused and changes nothing. A negotiation-time resize
  precedes fulfillment and passes; design for the refusal anyway.*
- `kit/capability-shape` and `VM_CAPABILITY_SCHEMA` define the family-grouped
  capability shape and the VM vocabulary. `capacity-shape-pricing` lets a seller
  state per-family rates; a shape-priced listing records its resolved rates on the
  storefront's listing record, served by the storefront's unsigned listing read,
  and publishes to the registry only each option's composed rate for the listing's
  own shape. Its aggregator evaluates the rates for any shape exactly. A
  flat-priced listing — one whose GPU family states no rates — has a clause rate
  for its own shape and no family rates, so it cannot price a revised shape and is
  shape-fixed by construction. `capacity-shape-envelope` supplies an
  admissibility predicate and `negotiation-capacity-feasibility-probe` a
  non-consuming authoritative probe, where a domain composes them.
- Reverified 2026-11-06: `NegotiateContinueRequest` and `AdvanceRequest` now
  carry `extra="forbid"`; their `proposal` remains a dictionary, not a typed
  revised-terms carrier. The Section 1 revert remains historical; this section
  does not undo subsequent request-model strictness. Nested content still needs
  the domain codec that understands it.

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

The wire child is `proposal.provision_terms`; its envelope payload is the whole
family-grouped shape, not a patch. The VM decoder preserves the opening's duration,
start and delivery credentials and replaces only `compute_resource` in the effective
terms used by the existing VM codecs. Those full effective terms are recorded beside
each scalar message. Continuation resumes the latest seller-quoted terms, not the
immutable opening's shape or an unquoted buyer proposal. The round adapter may
supply its agreed terms separately from the proposed revision. Domains that do not
compose a revision decoder refuse a revised envelope. Revisit this boundary if
non-shape delivery terms become negotiable; they need explicit domain validation,
not arbitrary replacement of the opening's payload.

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
which is authoritative for both. It is not carried per round. At opening the
seller pins the rate-structure digest; a changed structure refuses a later round
or acceptance distinctly, requiring the buyer to reopen (D-e below). Revisit
condition: sellers needing to reprice live negotiations.

### Registry carrier and authority: D-a through D-d

Each decision below is **decided by webapp owner 2026-11-06, pending maintainer review**.

- **D-a — keep what the schema admits.** `store-registry-listings-as-published`
  stores and serves each accepted listing as published. Listing-level terms need
  not accumulate inside `listing_resource`; the schema describes the whole
  accepted listing. Revisit if the registry's admitted schema becomes deliberately
  narrower. Registry storage and verification are owned by that change, not here.
- **D-b — listing-level rates.** Read `rate_structure` from the registry listing's
  top level. Rates describe sale terms for multiple shapes, not the advertised
  resource's shape. `asking_rate` stays in `listing_resource`; moving it is not
  required by quote derivation. Revisit if the published pricing vocabulary changes.
- **D-c — seller authority.** The registry retains the publisher's signed request
  bytes and signature beside its own signed response. A buyer verifies the seller's
  commitment, rather than treating the registry's copy as seller authority.
  Revisit if the signed-listing proof contract changes.
- **D-d — buyer rate access.** A buyer derives quotes from D-b's registry carrier,
  verified with D-c's retained seller signature under D-a. This avoids an unsigned
  storefront read or an additional negotiation commitment carrier. The registry
  change is an implementation/deployment dependency. Revisit if discovery no
  longer supplies the seller-authenticated rate structure.

### D-e — a rate structure is pinned for the negotiation

**Decided by webapp owner 2026-11-06, pending maintainer review.**

At opening, persist the digest of the seller-signed rate structure. On a later
round or acceptance, refuse distinctly as `rate_structure_changed_reopen` if the
current structure differs, even if the advertised shape's composed total and
settlement option identity are unchanged. A missing pin on a shape-priced thread
also fails closed: in-flight absolute-amount negotiations must drain at upgrade.

Publication updates terms in place and continuation resolves the current listing.
The existing pinned-option guard already refuses withdrawn options; this rule
extends that boundary to changes that only affect other shapes. Honoring the old
snapshot would bind the seller to withdrawn rates, a new pricing commitment;
explicit repricing would change the wire. Neither is implicit in a multiplier.
Revisit condition: sellers needing to reprice live negotiations.

### Carrier alternatives considered before D-a through D-d

The quote for a revised shape is derived from the listing's rate structure, so a
buyer must be able to read that structure with the authority the quote needs. Three
carriers are possible:

- the storefront's listing read, which exists today but is unsigned, with the
  structure — or its digest — bound into a signed negotiation response so both
  parties derive the quote from the same committed rates;
- `listing_resource`, following `asking_rate`'s precedent, which the registry
  already stores and can filter;
- a listing-level field at the registry, which the registry currently discards.

The third depends on `store-registry-listings-as-published`, and that change's
accepted carrier policy bears on the second as well: its review decides whether
listing-level terms keep accumulating in `listing_resource`. This is therefore an
decision gate resolved by D-a through D-d above: the listing-level registry
carrier is selected, including availability at discovery, and depends on the
registry change's implementation.

### Evaluation order inside the seller's round

For a round carrying a shape, the VM `evaluate_round` composition runs, in
order: admissibility (if composed), authoritative feasibility (if composed), the
seller's commercial feasibility guard, then pricing.

The commercial feasibility guard is this change's: a predicate taking a requested
shape and the listing's categorical commitments — GPU model and region compared by
equality — so a requested shape the seller does not sell is declined before it is
quoted. Its quantitative counterpart is `capacity-shape-envelope`'s admissibility
predicate, composed first; the guard does not re-check ranges. It moved here from
`capacity-shape-pricing`, whose planning-time Section 5 held both halves, because
this composition is where a requested shape first exists and where the order is
decided. The "Seller feasibility precedes pricing" requirement moved with it. Each is a distinct refusal
reason on the wire, because each leads to a different counter: change the ask,
retry later, or accept the seller's counter. A domain that composes neither of
the first two negotiates shapes on price alone and says so in its composition
rather than silently.

### Slice A composition and reference-price scale

The VM composition resolves the requested shape's quantitative predicate from the
listing's durable site/pool binding and the held pool projection, then reads the
stored VM override and parsed configured default through the existing listing-shape
resolver. The override replaces the hint's shape list whole; only the advertised
base shape's constraints apply. Missing/unreadable policy refuses as
`shape_policy_unavailable`, never as an unconstrained fallback. Admissibility
refuses as `shape_inadmissible`; the categorical guard refuses as
`shape_commercially_infeasible`. Requested-shape authoritative feasibility is
**not checked**. Existing listing-source confirmation concerns the advertised
shape alone and is not evidence that the requested shape fits.

The VM-specific seller hook receives the effective grouped requested shape.
For a shape-priced scalar option it evaluates both the advertised and requested
shapes through `price_vm_shape` in that selected asset. Their exact rational
ratio rescales the already-materialized option rate, reusing its base-unit scale
without a token metadata RPC or an inferred decimal precision. Both composed
prices must be positive. A selected asset with no matching family rates refuses
as `shape_price_unavailable`, never falling back to another asset's rates.
This preserves the current absolute scalar and truncation semantics until 2b;
it is not the multiplier or payment-consumer conversion. Flat-priced listings
remain shape-fixed, as the existing design's open question anticipates.

Round-zero flat compute requests remain partial: omitted dimensions inherit the
listing once, and the complete effective shape is recorded with the seller quote.
A later grouped revision remains a whole shape and never inherits omitted
families. Continuation validates policy before its fallback reference can price
anything; exit performs no reference pricing, so withdrawn or unpriceable terms
cannot prevent the buyer leaving. Revisit the scale bridge at the 2b conversion:
quote derivation and upward rounding then have one shared amount contract.

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
  shape is fixed by construction, and so is a flat-priced listing; a seller policy
  that refuses every revised shape achieves the rest. Leaning towards no declaration until a seller asks
  for one.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A buyer-requested round-0 VM shape differing from the listing is rejected outright until a round can carry a shape | Temporary; lifted by Section 2. Never promoted |
| Revised terms are a child of `proposal`; core reuses `ProvisionTerms` rather than adding vocabulary; durable seller-quoted terms survive continuation and acceptance | `openspec/specs/negotiation-protocol/spec.md` — "A round may revise the capacity shape" |
| The negotiated quantity is a multiplier in basis points; amounts stay exact | `openspec/specs/negotiation-protocol/spec.md` — "Rate-multiplier negotiation" |
| A requested shape's feasibility, quantitative and categorical, is evaluated before pricing | `openspec/specs/negotiation-protocol/spec.md` — "Seller feasibility precedes pricing" |
| The agreed shape is what the claim reserves | `openspec/specs/vm-storefront-fulfillment/spec.md` — "The agreed shape is reserved" |
| No core-level extra-field guard; content validation lives in the domain codec | This change's `design.md` |
| D-a through D-d: registry listing-level rate carrier and retained seller proof | `openspec/specs/negotiation-protocol/spec.md` — "Rate-multiplier negotiation"; registry storage/proof promotion belongs to `store-registry-listings-as-published` |
| D-e: rate-structure pin and distinct refusal on repricing | `openspec/specs/negotiation-protocol/spec.md` — "Rate-multiplier negotiation" |
