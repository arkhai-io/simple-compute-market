# Implementation Tasks

## 1. Admissibility capability in kit

- [ ] 1.1 Re-verify `design.md`'s Context findings, particularly that
      `has_matching_inventory_guard` remains categorical-only and that `policy_tags`
      readers still validate only universal-meaning content.
- [ ] 1.2 Define the capability with exactly two operations — whole-shape admissibility,
      and admissible range for one dimension given the remainder. Both take the whole
      proposed shape.
- [ ] 1.3 Do **not** expose a readable per-dimension bounds accessor. `design.md`
      records this as the central decision; an accessor would let callers encode the
      static-box assumption locally.
- [ ] 1.4 Implement static per-dimension minimum/maximum as the only implementation.
- [ ] 1.5 Keep kit free of dimension names: the vocabulary comes from the composition
      root, and validation covers well-formedness only.
- [ ] 1.6 Focused tests: shape inside bounds; shape outside on one dimension; range
      query returns configured bounds and ignores the remainder; unbounded pool admits
      everything; a domain-specific dimension name is validated without kit knowing it.

## 2. Bounds as pool policy

- [ ] 2.1 Add bounds to `kit/resource-pools`' hint vocabulary with a typed reader,
      following the existing tags' validation posture.
- [ ] 2.2 Confirm bounds inherit projection and precedence from the existing hint
      mechanism without a new configuration channel.
- [ ] 2.3 Focused tests: declared bounds project and resolve; malformed bounds are
      rejected at the reader; absent bounds resolve to unbounded.

## 3. Domain wiring

- [ ] 3.1 Supply the VM domain's dimension vocabulary from its composition root.
- [ ] 3.2 Prove by test that kit contains no VM dimension name after wiring — the
      property that makes this capability reusable by a pod, inference-token, or
      model-training domain.

## 4. Validation

- [ ] 4.1 Run `kit/site` and `kit/resource-pools` suites plus the VM composition tests.
      Disclose any suite not run.
- [ ] 4.2 Verify package boundaries per `physical-provisioning`'s dependency isolation:
      kit acquires no domain or service dependency.
- [ ] 4.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`.
- [ ] 5.2 **Import placement.** Review imports this change adds or touches.
- [ ] 5.3 **Documentation compliance.** Confirm the predicate-and-range rule landed in
      `openspec/specs/site-capacity/spec.md` and the coupled-region rationale in
      `openspec/specs/site-capacity/architecture.md`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 5.5 **Roadmap currency.** Update Goal 2's gap mapping in
      `docs/development/ROADMAP.md`.
- [ ] 5.6 **Promotion.** Complete the design-promotion record below. Include an explicit
      check that no caller reads bounds directly from `policy_tags`, bypassing the
      capability — `design.md` names this as the failure mode that would undo the design,
      and `policy_tags` is readable, so it needs verifying rather than assuming.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Admissibility is a whole-shape predicate plus a per-dimension range query, never readable bounds | `openspec/specs/site-capacity/spec.md` — "Capacity shape admissibility" |
| Admissibility is answered from declared pool policy and is independent of current availability | Same requirement |
| An unbounded pool admits every shape | Same requirement |
| Why the interface is shaped for a coupled, occupancy-dependent feasible region despite a static first implementation | `openspec/specs/site-capacity/architecture.md` |
| Bounds reuse the pool hint mechanism rather than a new configuration channel | This change's `design.md` |
