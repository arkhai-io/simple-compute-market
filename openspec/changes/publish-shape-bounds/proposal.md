## Why

`capacity-shape-envelope` gives a seller's storefront a resolved policy for which
capacity shapes it will sell, and publishes only listings inside it. A buyer cannot see
that policy. It learns the bounds only when a shape it proposes is refused, so it cannot
discover a seller who would sell 8 GPUs from a listing that advertises 2, and cannot
build an informed counter-proposal once dimensions are negotiable.

Hardware bounds are not commercially sensitive. Rates are what a seller optimises
against a buyer; bounds are a statement of what can be sold, and disclosing them helps
both sides find a deal.

## What Changes

- A VM listing discloses the storefront's resolved shape bounds for its pool and mode,
  in a form a buyer evaluates through `kit/capability-admissibility`.
- The registry carries and serves it, and its filter specification may let buyers filter
  on it.
- The representation is the open design question: a listing has a base offering, a range
  around each base value, and, once constraint sections exist, ratios between two
  dimensions, and these should read concisely and close to the base value.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

Provisional; settled in design.

- `storefront-publication`: a VM listing discloses its resolved shape bounds.
- `registry-discovery`: the registry stores and serves the disclosed bounds.

## Non-Goals

- Changing what is admissible, how bounds resolve, or how publication enforces them
  (`capacity-shape-envelope`).
- Disclosing rates or rate structures (`negotiation-driven-capacity-resize`'s decision
  gate 2.1a).
- Disclosing bounds for bare metal, which negotiates no shape, or API credits, which has
  no shapes.

## Impact

- VM storefront publication: the listing payload.
- `core/registry` and its compute filter specification: storing, serving, and possibly
  filtering on the disclosed bounds, under the carrier policy
  `store-registry-listings-as-published` settles.
- Buyer: reading the disclosed bounds and evaluating them through the admissibility kit.
- Wire: a new listing term, observable to registries and buyers.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — to be decided in design.
- [x] Existing subsystem specification — provisional: `storefront-publication`,
      `registry-discovery`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- A VM listing discloses its resolved shape bounds, evaluated through the admissibility
  kit — `openspec/specs/storefront-publication/spec.md`.
- How a listing represents its base offering and admissible region, and why —
  destination decided in design.

## Dependencies and Related Changes

- Depends on `capacity-shape-envelope` for the resolved bounds and the kit.
- Depends on `store-registry-listings-as-published` for whether the registry keeps a
  listing-level term outside `listing_resource`.
- Informs `negotiation-driven-capacity-resize`: once bounds are disclosed, a buyer can
  build counter-proposals from them rather than from refusals alone.
