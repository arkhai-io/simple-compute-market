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
- `storefront-publication`: the storefront keeps each registry's last successful
  publication, which a seller prices negotiations from.

## Non-Goals

- Pricing a shape. `capacity-shape-pricing` delivers the rate structure and its
  evaluation; this change consumes them, and owns the seller's check of a
  requested shape ahead of pricing it. Any revised-terms content is limited to what that policy can
  price: an unexamined field that passes content through unchecked risks a
  buyer claiming resources the seller never agreed to give away.
- Calling `resize_reservation`. Neither storefront holds capacity while terms
  are negotiated: a configured soft hold is placed at acceptance, once the terms
  are final, and a VM hold claims the agreed shape. There is no reservation to
  resize during negotiation; `negotiation-time-capacity-hold`, the change that
  first holds capacity before the shape is final, is its first caller.
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
  changes from base units to basis points on shape-priced listings, and the
  storefront's negotiated quantity is renamed `negotiated_scalar` in its database
  and wire. Storefront state crosses the release one way: in-flight negotiations
  must drain before the upgrade.
- Tests: negotiation runtime and VM hook suites, `kit/policy` middleware
  suites, escrow amount construction, and one e2e run with a shape agreed
  below the listing's.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Discovery and negotiation" says what
      a round negotiates.
- [x] Existing subsystem specification — `openspec/specs/negotiation-protocol/spec.md`,
      `openspec/specs/vm-storefront-fulfillment/spec.md`,
      `openspec/specs/storefront-publication/spec.md`.
- [x] `docs/operator-handbook.md` — draining open negotiations before the upgrade.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 — a round may carry a revised capacity shape as a child of `proposal`, in the
  family-grouped form, with durable seller-quoted terms —
  `openspec/specs/negotiation-protocol/spec.md`.
- D2 — the negotiated variable is a multiplier; why, and the rejected models — this
  change's `design.md`; the requirement in `openspec/specs/negotiation-protocol/spec.md`.
- D3 — the multiplier is integer basis points; the quote is the selected option's
  rate scaled by the composed-price ratio, exact, rounded up once, refused on
  overflow — `openspec/specs/negotiation-protocol/spec.md`.
- D4 — the seller's floor is one storefront-wide bound of at most 10,000 —
  `openspec/specs/negotiation-protocol/spec.md`.
- D5 — the buyer's schema-opaque amount codec: monetary outcomes, a separate
  negotiated scalar, bounds against the opening shape, the ceiling check, derived
  prices for the opening shape —
  `docs/development/ARCHITECTURE.md` (buyer negotiation composition) and
  `openspec/specs/negotiation-protocol/spec.md`.
- D6 — legacy flat and hidden-reserve paths keep absolute semantics; the payment,
  not the scalar, enters settlement — `openspec/specs/negotiation-protocol/spec.md`.
- D7 — rates are listing-level sale terms at the registry's `pricing.rate_structure`,
  with the seller's retained publication proof — `openspec/specs/negotiation-protocol/spec.md`;
  registry storage and proof are `store-registry-listings-as-published`'s.
- D8 — the buyer reads rates from the registry, lifted once at its registry
  boundary and verified by the seller's retained proof —
  `openspec/specs/negotiation-protocol/spec.md`.
- D9 — the seller pins and prices from its last successful publication —
  `openspec/specs/negotiation-protocol/spec.md` and
  `openspec/specs/storefront-publication/spec.md`.
- D10 — the evaluation order, distinct refusals, and the advertised-shape cap until
  the feasibility probe is composed — `openspec/specs/negotiation-protocol/spec.md`.
- D11 — the agreed shape is what the claim reserves —
  `openspec/specs/vm-storefront-fulfillment/spec.md`.
- D12 — `resize_reservation` is not wired here — this change's `design.md`.
- D13 — the storefront's negotiated quantity is `negotiated_scalar` —
  `openspec/specs/negotiation-protocol/spec.md`.
- D14 — settlement reads money only from the Agreement and its mandate —
  `openspec/specs/negotiation-protocol/spec.md`.
- D15 — the release is one-way for storefront state; drain before upgrading —
  `docs/operator-handbook.md`.
- D16 — the VM import guard follows the package layers — already stated by
  `docs/development/ARCHITECTURE.md`.
- D17 — content validation lives in the domain codec — this change's `design.md`.

## Dependencies and Related Changes

- Depends on `store-registry-listings-as-published` (archived) for the listing-level
  `pricing.rate_structure` and the retained seller-signed publication proof (D7, D8).
  A changed structure refuses continuation or acceptance, requiring a new opening
  rather than silently repricing the negotiation (D9). The buyer's verifier of that
  proof arrives with `negotiate-open-ended-compute-terms`.

- Depends on `capacity-shape-pricing` for the rate structure, the recorded
  structure that prices a revised shape, its evaluation, and the selected-option
  reference amount the multiplier reinterprets.
- Consumes `capacity-shape-envelope` and `negotiation-capacity-feasibility-probe`
  where a domain composes them; neither blocks this change. Until the probe is
  composed, requested shapes are capped at the advertised quantities (D10): the probe
  is the prerequisite for negotiating a larger shape.
- Builds on `fix-vm-fulfillment-capacity-boundary`: the committed reservation is
  authoritative through scheduling and dispatch, so once the claim is built from
  the agreed shape, fulfillment follows it.
- Hands `resize_reservation`'s first call to `negotiation-time-capacity-hold`.
- Extends `kit/negotiation-runtime`'s `NegotiationDomainHooks`; a domain that
  composes the runtime is affected only where it opts into shape negotiation.
