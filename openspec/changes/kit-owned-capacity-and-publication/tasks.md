# Implementation Tasks

## 1. Compare before moving

- [x] 1.1 Re-verify the per-domain line counts and that bare metal still has no
      implementation of these concerns.
- [x] 1.2 Compare the existing implementations concern by concern and record where they
      already diverge. Two hand-maintained copies will have drifted; extraction forces a
      choice about which behavior is correct, and making it silently is how a refactor
      becomes a behavior change.
- [x] 1.3 Separate genuine domain specificity from unintended divergence. Differences in
      codecs and configuration go to the domain; differences in control flow are either
      domain-owned or a drift finding.

## 2. Extract onto the seam

- [x] 2.1 Move the mechanism into kit, leaving the domain to supply its contract,
      configuration, and domain-specific semantics.
- [x] 2.2 Confirm the dependency direction: kit depends downward only. The moved code
      currently imports freely from its domain.
- [x] 2.3 Record the chosen behavior wherever the copies disagreed, with the reason.

## 3. Compose every domain

- [x] 3.1 Compose all three domains onto the kit implementation. All three storefronts
      import `market_site_client` and `market_capacity_publication`; bare metal's
      publication runs through `publication_composition.py` over the kit cycle driver.
- [x] 3.2 Remove every domain-local copy **in this change**. Domain packages now
  contain only configuration, codecs, and injected binding/reconciliation hooks.
- [x] 3.3 Give bare metal the concerns it does not have today, and treat gaps its suites
      then expose as findings about bare metal rather than about the extraction. Bare
      metal reserves through the site client and publishes, reconciles, and converges
      through the kit publication runtime on its own end-to-end lane.

## 4. Packaging follow-through

- [x] 4.1 Update build targets and Dockerfile wheel-refresh entries.
- [x] 4.2 Regenerate affected lockfiles and verify they contain no absolute paths.

## 5. Validation

- [ ] 5.1 Run the kit suites, all three domains' storefront suites, and the domain
      conformance suite. Disclose any suite not run.
- [x] 5.2 Confirm no domain retains a local implementation of any extracted concern.
- [ ] 5.3 Confirm behavior preservation per domain against the comparison recorded in
      1.2 — not against a general impression that the suites pass.
- [ ] 5.4 Run `openspec validate --all --strict` against the baseline current at
      implementation time.
- [ ] 5.5 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both. Read the moved modules'
      comments and docstrings once in their final context and remove stale temporary
      commentary.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

Listed in an earlier order; closeout works the parts in `openspec/README.md`'s order.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [x] 6.2 **Permanent documentation.** Promote the kit ownership and exact binding rule
  to `docs/development/ARCHITECTURE.md`.
- [x] 6.3 **Permanent specification.** Promote the implemented requirement to
  `openspec/specs/market-composition/spec.md`.
      Archival uses `--skip-specs`: this task synchronized the specification by hand.
- [x] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations; keep the drift comparisons, which
      the sibling extractions will want.
- [x] 6.5 **Roadmap currency.** Update Goal 4's current-state description and gap mapping
  in `docs/development/ROADMAP.md`.
- [x] 6.6 **Promotion.** Complete the design-promotion record below.
- [ ] 6.7 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 6.8 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=kit-owned-capacity-and-publication` and resolve every match,
      then `openspec validate kit-owned-capacity-and-publication --strict`.
- [ ] 6.9 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 6.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 6.11 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 6.12 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe.
- [ ] 6.13 **Archival.** Last, once every other part is checked: `openspec archive
      kit-owned-capacity-and-publication --skip-specs -y` moves the change under
      `openspec/changes/archive/` without merging its deltas, which 6.3 synchronized by
      hand; point the index row at the archived directory, and run
      `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Kit-owned capacity client and publication runtime | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` |
| Where the existing implementations diverged and which behavior was chosen | `openspec/changes/kit-owned-capacity-and-publication/design.md`; final binding rules promoted to `docs/development/ARCHITECTURE.md` |
