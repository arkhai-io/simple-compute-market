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

- [ ] 3.1 Compose all three domains onto the kit implementation.
- [x] 3.2 Remove every domain-local copy **in this change**. Domain packages now
  contain only configuration, codecs, and injected binding/reconciliation hooks.
- [ ] 3.3 Give bare metal the concerns it does not have today, and treat gaps its suites
      then expose as findings about bare metal rather than about the extraction.

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

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`; read moved modules'
  comments/docstrings once in final context and remove stale temporary commentary.
- [x] 6.2 **Permanent documentation.** Promote the kit ownership and exact binding rule
  to `docs/development/ARCHITECTURE.md`.
- [x] 6.3 **Permanent specification.** Promote the implemented requirement to
  `openspec/specs/market-composition/spec.md`.
- [x] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations; keep the drift comparisons, which
      the sibling extractions will want.
- [x] 6.5 **Roadmap currency.** Update Goal 4's current-state description and gap mapping
  in `docs/development/ROADMAP.md`.
- [x] 6.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Kit-owned capacity client and publication runtime | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` |
| Where the existing implementations diverged and which behavior was chosen | `openspec/changes/kit-owned-capacity-and-publication/design.md`; final binding rules promoted to `docs/development/ARCHITECTURE.md` |
