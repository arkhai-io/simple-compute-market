## Why

`docs/development/ARCHITECTURE.md`'s "Capacity reservation" section states the
negotiation model: buyer and seller negotiate pooled capacity, not a pinned
physical resource, and a durable shape change is expressed for the negotiation
rather than by mutating a reservation in place. Nothing in the protocol can
express that change. Round 0 carries a shape in `provision_terms.compute_resource`,
but the VM opening validator refuses any shape that differs from the listing's,
because nothing could price it; no later round can carry a shape at all. The
one negotiable quantity is an absolute amount for the listing's fixed shape,
which stops being comparable across rounds the moment shape can vary. And the
settlement order, the claim, and the committed reservation are all derived from
the listing record, so even an agreed shape would not reach what gets built.

`capacity-shape-pricing` gives every listing a per-dimension minimum rate
structure and a way to price any admissible shape. This change makes the shape
negotiable on top of it.

## What Changes

- A round after the first may carry a revised capacity shape, as a child of
  `proposal` typed as the existing `ProvisionTerms` envelope and expressed in
  the family-grouped capability shape `VM_CAPABILITY_SCHEMA` validates.
  `kit/negotiation-runtime`'s continuation hooks see the decoded shape.
- The negotiated quantity becomes a rate multiplier over the listing's
  advertised minimum rate structure, carried as integer basis points; the
  seller's floor is one bound on it; every derived amount stays an exact
  integer, rounds upward, and is refused rather than truncated when it exceeds
  the asset's amount type.
- The VM seller's round evaluates a revised shape in a fixed order —
  admissibility, authoritative feasibility, commercial feasibility, pricing —
  with a distinct refusal reason for each, and the round-0 shape guard is
  retired since a differing shape is a proposal rather than a defect.
- The agreed shape, not the listing's, reaches the accepted artifacts, the
  settlement order, and therefore the capacity claim and committed reservation;
  a hold placed at acceptance holds the agreed shape.
- Shipped already: the round-0 guard that refuses a differing shape outright
  rather than silently ignoring it, so a buyer cannot believe they negotiated a
  smaller deal than what gets built. This change retires it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: a round may revise the capacity shape; the negotiated
  quantity is a rate multiplier over the advertised minimum rate structure.
- `vm-storefront-fulfillment`: the agreed shape is what the claim reserves.

## Non-Goals

- Pricing a shape. `capacity-shape-pricing` delivers the rate structure, its
  evaluation, and the seller's commercial feasibility guard; this change
  consumes them. Any revised-terms content is limited to what that policy can
  price: an unexamined field that passes content through unchecked risks a
  buyer claiming resources the seller never agreed to give away.
- Calling `resize_reservation`. Both storefronts place no hold before
  settlement, so there is no reservation to resize during negotiation;
  `negotiation-time-capacity-hold`, the change that first holds capacity
  before the shape is final, is its first caller.
- Deciding which shapes a seller will consider (`capacity-shape-envelope`) or
  whether the site can currently serve one
  (`negotiation-capacity-feasibility-probe`). This change calls both where they
  exist and states "not checked" where a domain composes neither.
- Round 0 adopting the family-grouped form (`settle-capacity-claim-vocabulary`).

## Impact

- Code: `core_storefront`'s continue/advance request models (the revised-terms
  child), `kit/negotiation-runtime`'s `NegotiationDomainHooks`, `RoundRequest`,
  and `RoundEvaluation`, the VM storefront's `negotiation_runtime.py`
  (`_validate_vm_opening`, the `evaluate_round` composition, the amount hooks,
  `build_vm_accepted_artifacts`, `_place_capacity_hold`), `kit/policy`'s
  middlewares' reference quantity, and every consumer of the negotiated amount
  on the escrow and hosted obligation paths.
- Wire: a new optional child of `proposal`; the negotiated amount's meaning
  changes from base units to basis points. In-flight negotiations must drain
  across the deployment boundary.
- Tests: negotiation runtime and VM hook suites, `kit/policy` middleware
  suites, escrow amount construction, and one e2e run with a shape agreed
  below the listing's.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Discovery and negotiation" says what
      a round negotiates.
- [x] Existing subsystem specification — `openspec/specs/negotiation-protocol/spec.md`,
      `openspec/specs/vm-storefront-fulfillment/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The negotiated quantity is a multiplier over the listing's minimum rate
  structure, in basis points; a seller floor is expressed once; derived amounts
  stay exact — `openspec/specs/negotiation-protocol/spec.md`.
- A round after the first may carry a revised capacity shape as a child of
  `proposal`, in the family-grouped form, evaluated in a fixed order with
  distinct refusals — `openspec/specs/negotiation-protocol/spec.md`.
- The agreed shape is what the claim reserves —
  `openspec/specs/vm-storefront-fulfillment/spec.md`.
- Why the negotiated variable had to change, the rejected models, and why the
  multiplier is basis points — this change's `design.md`.

## Dependencies and Related Changes

- Depends on `capacity-shape-pricing` for the rate structure, its evaluation,
  and the seller's commercial feasibility guard.
- Consumes `capacity-shape-envelope` and `negotiation-capacity-feasibility-probe`
  where a domain composes them; neither blocks this change.
- Builds on `fix-vm-fulfillment-capacity-boundary`: the committed reservation is
  authoritative through scheduling and dispatch, so once the claim is built from
  the agreed shape, fulfillment follows it.
- Hands `resize_reservation`'s first call to `negotiation-time-capacity-hold`.
- Extends `kit/negotiation-runtime`'s `NegotiationDomainHooks`; a domain that
  composes the runtime is affected only where it opts into shape negotiation.
