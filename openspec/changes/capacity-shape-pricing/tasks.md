# Implementation Tasks

Sections sized to land in roughly a day each. Every section is additive and deployable
alone. Section 4 is `negotiation-driven-capacity-resize`'s; its number is kept.

*Amended 2026-10-01:* `design.md` was revised against the tree. Sections 1–3 are
re-planned against it in the planning round, preserving these entries; until then,
where a task below disagrees with `design.md` — notably 3.2's primary-dimension
reading, which the revision supersedes — `design.md` governs. Section 5 is outside
the Sections 1–3 implementation and opens with decision gate 5.0.

## 1. Rate structure and evaluation

- [ ] 1.1 Re-verify `design.md`'s Context findings before editing, particularly
      `RateValue`'s current reach into escrow obligation data and `PER_UNIT_SECONDS`'
      single entry.
- [ ] 1.2 Define the rate structure as a field of each capability family, not a
      parallel rate-keyed map, over the family-grouped form `kit/capability-shape`
      defines and the family names `VM_CAPABILITY_SCHEMA` fixes (`gpu`, `cpu`,
      `memory`, `storage`). A rate field is not a `ShapeField`: shapes are digested
      over their families and a rate must not change a listing's shape digest.
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
      `gpu` family, using `VM_CAPABILITY_SCHEMA`'s family names.
- [ ] 2.2a Extend `kit/pool-overrides`' VM terms contract with the per-dimension
      rate fields, so the site-scoped override is the top tier for rates as it is for
      `min_price`; a rate an override states for a family the schema does not know is
      refused at write.
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

Owned by [`negotiation-driven-capacity-resize`](../negotiation-driven-capacity-resize/tasks.md)
Section 2b: the multiplier and the revised-terms field are one deployment boundary.

## 5. Seller feasibility guard

- [ ] 5.0 **Decision gate.** Before any other Section 5 task starts, decide whether
      Section 5 and its `negotiation-protocol` "Seller feasibility precedes pricing"
      delta move into their own change depending on `capacity-shape-envelope`, and
      record the decision and its reasoning in `design.md`. Section 5 touches the
      negotiation path rather than pricing and publication, its quantitative check
      overlaps the envelope's admissibility, and it has no live caller until
      `negotiation-driven-capacity-resize` §2.
- [ ] 5.1 Extend `has_matching_inventory_guard` from `region`/`gpu_model` equality to a
      quantitative check across every dimension the seller constrains.
      *Amended 2026-09-23:* `unbacked-listing-publication` makes the guard recheck
      every published source-derived field — categorical and quantitative — against
      the listing's own source. What remains here is checking a *buyer-requested*
      shape, once shapes are negotiable, rather than the listing's advertised one.
      Implement the predicate here, taking a requested shape and the seller's
      constraints, and wire it into the VM `evaluate_round` composition in
      `negotiation_runtime.py` ahead of pricing. Until a round can carry a shape the
      requested shape is the listing's own and the predicate is exercised by unit
      tests only.
- [ ] 5.2 Order the guard before pricing inside the VM `evaluate_round` composition,
      so a shape the seller will not serve is never quoted.
- [ ] 5.3 Focused tests: quantitative constraint exceeded declines without a quote;
      categorical mismatch declines as today.

## 6. Validation

- [ ] 6.1 Run the pricing, negotiation policy, `kit/pool-overrides`, escrow rate
      construction, and VM e2e price-assertion suites. Disclose any suite not run.
- [ ] 6.2 Confirm no consumer reconstructs a total from individual dimension rates —
      the accidental coupling `design.md` names as most likely.
- [ ] 6.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read
      `_validate_vm_opening`'s surroundings and `pricing_resolution.py`'s module
      docstring directly: the latter says one price per GPU model, which this change
      makes false. (The round-0 guard's own retirement is
      `negotiation-driven-capacity-resize`'s.)
- [ ] 7.2 **Import placement.** Review imports this change adds or touches.
- [ ] 7.3 **Documentation compliance.** Confirm the rate-structure and
      feasibility-before-pricing rules landed in the two specs, `ARCHITECTURE.md`'s
      pricing description was updated, and the rejected pricing models stayed in
      `design.md`.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 7.5 **Roadmap currency.** Update Goal 2's current-state description in
      `docs/development/ROADMAP.md` — specifically the statement that pricing resolves
      one price per GPU model — and remove this change's gap row. The statement that
      negotiation has one degree of freedom stays until
      `negotiation-driven-capacity-resize` lands.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.
- [ ] 7.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

- [ ] 7.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=capacity-shape-pricing` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
- [ ] 7.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Per-family rates in one nesting across the three tiers; a listing is shape-priced or flat-priced by its GPU family; unpriceable, mixed, and conflicting inputs refuse the candidate | `openspec/specs/storefront-publication/spec.md` — "Shape-resolvable commercial rates" |
| Price aggregation is replaceable, exact, selected by the domain's composition, and no consumer reconstructs a total | `openspec/specs/storefront-publication/spec.md` — "Price aggregation is replaceable" |
| A shape-priced listing's rates are a storefront term of sale; the registry carries only composed option rates | `openspec/specs/storefront-publication/spec.md` — "A shape-priced listing's rates are a storefront term of sale" |
| A clause rate is stated or composed and converts to base units exactly or is refused | `openspec/specs/storefront-publication/spec.md` — "Publication pricing is explicit per settlement clause" |
| The dead `min_price`/`token` resolution is retired; retired keys are tolerated and reported; the floor is the configured default alone | `openspec/specs/storefront-publication/spec.md` — "Domain-owned publication and hold hints" |
| The seller's reference amount and floor are exact | `openspec/specs/negotiation-protocol/spec.md` — "Uint256-safe negotiation values" |
| Seller feasibility is evaluated quantitatively and precedes pricing (Section 5) | `openspec/specs/negotiation-protocol/spec.md` — "Seller feasibility precedes pricing", subject to gate 5.0 |
| How a listing is priced, and that the override tier is the site-scoped pool override | `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" |
| Why rates live inside families; why the flat rate is never reinterpreted; why `RateValue` was not widened; why the structure is storefront-served | `openspec/specs/storefront-publication/architecture.md` |
| Operator-facing family-rate configuration and override terms | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront listing shapes and pool overrides" |
| The superseded primary-dimension compatibility reading | This change's `design.md` only |
