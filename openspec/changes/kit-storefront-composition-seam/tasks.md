# Implementation Tasks

## 1. Define the seam

- [x] 1.1 Re-verify `design.md`'s Context measurements before designing against them:
      the eight concerns, their per-domain line counts, and that bare metal still has
      none of them.
- [x] 1.2 Define where kit-owned storefront runtime sits, what a domain supplies to it,
      and its composition point, extending the injected-contract shape
      `storefront-domain-parameterization` establishes.
- [x] 1.3 Confirm the dependency direction: kit depends downward only, per
      "From-below kit dependencies". The concerns being moved currently import freely
      from their domains, so check rather than assume.

## 2. Extract `alkahest_service`

- [x] 2.1 Compare the VM and API-credits implementations line by line and record where
      they already differ. `design.md` names silent drift resolution as the way a
      refactor becomes a behavior change.
- [x] 2.2 Move the mechanism into kit; leave chain configuration domain-supplied.
- [x] 2.3 Compose all three domains, including bare metal, which has no implementation
      today. Remove both existing copies in this change.
- [x] 2.4 Focused tests: kit unit coverage; each domain's chain client construction
      behaves identically to before; bare metal gains the concern.

## 3. Extract `negotiation_watchdog`

- [x] 3.1 Compare the two implementations and record differences, as in 2.1.
- [x] 3.2 Move the sweep mechanism into kit; leave the timeout value and terminal-state
      vocabulary domain-supplied.
- [x] 3.3 Compose all three domains and remove both copies.
- [x] 3.4 Focused tests: stale threads are marked abandoned on the same schedule as
      before, per domain; bare metal gains the sweep.

## 4. Packaging follow-through

- [x] 4.1 Update build targets and Dockerfile wheel-refresh entries for the kit package
      gaining modules and the domain wheels losing them.
- [x] 4.2 Regenerate affected lockfiles and verify they contain no absolute paths — this
      repository has been bitten by stale and machine-specific lock entries before.

## 5. Validation

- [ ] 5.1 Run the kit suites, all three domains' storefront suites, and the domain
      conformance suite. Disclose any suite not run.
- [x] 5.2 Confirm no domain retains a local implementation of either extracted concern —
      the property that makes the extraction complete rather than additive.
- [ ] 5.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.
- [ ] 5.4 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both. Read the moved modules'
      docstrings; they describe a domain-local concern.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

Listed in an earlier order; closeout works the parts in `openspec/README.md`'s order.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them, including the moved modules' docstrings (5.4). Do not edit code
      here: anything to rewrite returns the change to implementation.
- [x] 6.2 **Import placement.** Central rather than incidental here: extraction changes
      import direction, and a function-level import retained to dodge a cycle would hide
      a layering violation.
- [x] 6.3 **Documentation compliance.** Confirm the kit-ownership and no-copy-survives
      rules landed in `market-composition`, the seam's shape in
      `market-composition/architecture.md`, and that `ARCHITECTURE.md` describes what
      the storefront role composes rather than implements.
- [x] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations; keep the per-concern drift
      comparisons, which later extractions will want.
- [x] 6.5 **Roadmap currency.** Update Goal 4's current-state description and gap
      mapping in `docs/development/ROADMAP.md`.
- [x] 6.6 **Promotion.** Complete the design-promotion record below.
      Archival uses `--skip-specs`: this task synchronized the specification by hand.
- [ ] 6.7 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 6.8 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=kit-storefront-composition-seam` and resolve every
      match, then `openspec validate kit-storefront-composition-seam --strict`.
- [ ] 6.9 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 6.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 6.11 **Archival.** Last, once every other part is checked: `openspec archive
      kit-storefront-composition-seam -y --skip-specs` moves the change under
      `openspec/changes/archive/` without merging the deltas, which 6.6 synchronized by
      hand; point the index row at the archived directory, and run
      `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Cross-cutting storefront runtime is kit-owned and composed; kit depends downward only | `openspec/specs/market-composition/spec.md` — "Cross-cutting storefront runtime is kit-owned" |
| An extracted concern leaves no domain-local implementation, and a domain lacking it gains it | `openspec/specs/market-composition/spec.md` — "An extracted concern leaves no domain-local implementation" |
| The seam's shape: kit owns mechanism, the domain supplies codecs and configuration | `openspec/specs/market-composition/architecture.md` |
| What the storefront role composes rather than implements | `docs/development/ARCHITECTURE.md` |
| Why the smallest concerns go first, and how drift between copies is resolved | This change's `design.md` |
