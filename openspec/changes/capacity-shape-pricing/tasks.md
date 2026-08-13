# Implementation Tasks

Sections sized to land in roughly a day each. Sections 1–3 are additive and deployable
alone; Section 4 is the deployment boundary described in `design.md`'s migration plan.

## 1. Rate structure and evaluation

- [ ] 1.1 Re-verify `design.md`'s Context findings before editing, particularly
      `RateValue`'s current reach into escrow obligation data and `PER_UNIT_SECONDS`'
      single entry.
- [ ] 1.2 Define the rate structure as a field of each capability family, not a
      parallel rate-keyed map. Align the family shape with
      `structured-capacity-requirements`' accepted vocabulary rather than inventing a
      third spelling.
- [ ] 1.3 Implement the aggregation interface — shape plus resolved rate structure to
      price — with linear summation as its only implementation, selected by domain
      configuration.
- [ ] 1.4 Make evaluation callable outside the negotiation path, so the parked
      capacity-economics thread can price a hold's burn rate without a refactor.
- [ ] 1.5 Keep `RateValue` unwidened: pair a family's rate with that family's own
      quantity at evaluation, per `design.md`'s rejection of adding a quantity axis.
- [ ] 1.6 Focused tests: multi-dimension shape prices correctly; the same rates price a
      different shape; a shape with an unpriced dimension is unpriceable rather than
      discounted.

## 2. Rate resolution per dimension

- [ ] 2.1 Extend `pricing_resolution.py` from one price per GPU model to per-dimension
      rates, resolved through the existing storefront-override → pool-hint →
      config-default precedence independently per dimension.
- [ ] 2.2 Extend `[pricing.defaults.*]` settings and the pool pricing hint beyond the
      `gpu` family, using the vocabulary `structured-capacity-requirements` settles.
      If that change has not landed, stop and coordinate rather than choosing a
      `cpu`/`memory`/`storage` shape independently — its `design.md` records this as a
      one-directional dependency.
- [ ] 2.3 Make an unresolvable dimension rate produce unpriceable, never zero. Assert
      it directly; priced-at-zero is the dangerous default.
- [ ] 2.4 Focused tests: mixed-tier resolution across dimensions; absent tier falls
      through per field; no rate at any tier yields unpriceable.

## 3. Listing advertisement

- [ ] 3.1 Advertise the minimum rate structure on published listings, extending the
      offer construction `publish-multidimensional-listing-shape` touches.
- [ ] 3.2 Interpret an existing single-rate listing as a primary-dimension-only
      structure, producing an unchanged price for its own shape. No republication
      migration.
- [ ] 3.3 Focused tests: byte-comparable price for a pre-existing listing and shape;
      new structure advertised for a listing with several priced dimensions.

## 4. Negotiation reinterpretation

The deployment boundary. In-flight negotiations carry a multiplier after this section.

- [ ] 4.1 Reinterpret the negotiated reference quantity as a multiplier over the
      advertised minimum rate structure.
- [ ] 4.2 Audit every consumer that assumed the negotiated scalar was an amount in an
      asset's base units. This is an audit, not a rename — `design.md` names it as the
      contained risk, and the escrow construction path is where a missed consumer would
      surface as a wrong on-chain amount.
- [ ] 4.3 Express the seller's floor once as a multiplier bound and confirm it applies
      to a shape never explicitly priced.
- [ ] 4.4 Confirm `bisection_middleware` converges unchanged on the reinterpreted
      quantity, and that a shape change between rounds does not re-anchor bounds.
- [ ] 4.5 Focused tests: concession comparability across a shape change; floor applied
      to an unanticipated shape; agreed terms yield one derivable price.

## 5. Seller feasibility guard

- [ ] 5.1 Extend `has_matching_inventory_guard` from `region`/`gpu_model` equality to a
      quantitative check across every dimension the seller constrains.
- [ ] 5.2 Order the guard before pricing, so a shape the seller will not serve is never
      quoted.
- [ ] 5.3 Focused tests: quantitative constraint exceeded declines without a quote;
      categorical mismatch declines as today.

## 6. Validation

- [ ] 6.1 Run the pricing, negotiation policy, `kit/policy` middleware, escrow rate
      construction, and VM e2e price-assertion suites. Disclose any suite not run.
- [ ] 6.2 Confirm no consumer reconstructs a total from individual dimension rates —
      the accidental coupling `design.md` names as most likely.
- [ ] 6.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read
      `_place_capacity_hold`'s and `_reject_unsupported_resource_shape_request`'s
      docstrings directly: both state that seller policy cannot price a shape, which
      this change makes false. Leaving them is how the next reader concludes the guard
      is still load-bearing.
- [ ] 7.2 **Import placement.** Review imports this change adds or touches.
- [ ] 7.3 **Documentation compliance.** Confirm the rate-structure and multiplier rules
      landed in the two specs, `ARCHITECTURE.md`'s negotiation description was updated,
      and the rejected pricing models stayed in `design.md`.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 7.5 **Roadmap currency.** Update Goal 2's current-state description in
      `docs/development/ROADMAP.md` — specifically the statement that pricing resolves
      one price per GPU model and that no policy can evaluate a shape counter-offer —
      and remove this change's gap row.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Commercial resolution yields a rate structure evaluable for any admissible shape, per-dimension, unpriceable rather than free when a rate is missing | `openspec/specs/storefront-publication/spec.md` — "Shape-resolvable commercial rates" |
| Price aggregation is replaceable and no consumer may reconstruct a total | `openspec/specs/storefront-publication/spec.md` — "Price aggregation is replaceable" |
| The negotiated quantity is a multiplier over a minimum rate structure; a seller floor is expressed once | `openspec/specs/negotiation-protocol/spec.md` — "Rate-multiplier negotiation" |
| Seller feasibility is evaluated quantitatively and precedes pricing | `openspec/specs/negotiation-protocol/spec.md` — "Seller feasibility precedes pricing" |
| What a negotiation round negotiates | `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" |
| Why the negotiated variable had to change, and the two rejected alternatives | This change's `design.md` |
| Why `RateValue` was not widened with a quantity axis | This change's `design.md` |
