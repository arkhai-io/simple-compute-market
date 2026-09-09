# Tasks — separate advertisement authorization from delivery authorization

No blocking dependency. Prerequisite for `unbacked-listing-publication`.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Decision gate

- [ ] 1.1 **Decide whether `advertisable_modes` is projected or resolved
      storefront-side from the pool record**, and record the reasoning in
      `design.md`. Every other policy tag is projected, but a storefront already
      resolves a listing's offering mode from its frozen registration, so the
      projected value may be a check rather than an input. It is an open question
      there; do not implement both to avoid choosing.

## 2. Declaration

- [ ] 2.1 Add `advertisable_modes` to the shared resource-pool capability's
      policy-tag validation and typed resolution, matching how `deliverable_modes`
      is validated: a JSON-compatible set of unique, non-empty strings.
- [ ] 2.2 Make an absent or empty declaration authorize no mode, never widened by
      a default.
- [ ] 2.3 Carry it through create, replace, patch, bulk import, projection, and
      canonical export on the existing policy-tag channel and precedence.
- [ ] 2.4 Leave `deliverable_modes` untouched — meaning, derivation, migration,
      and every execution recheck at reservation, scheduling, and provider
      dispatch. A diff touching those paths means this change has exceeded its
      boundary.

## 3. Subset rule

- [ ] 3.1 Enforce that a capacity-backed pool's advertisable set is a subset of
      its deliverable set, on write.
- [ ] 3.2 Enforce the same on projection ingestion. The two sides upgrade
      independently, so a write-side-only check would accept from a projection
      what it would refuse from an operator.
- [ ] 3.3 Leave an unbacked pool's advertisable set independent of its deliverable
      set. Do not require a deliverable proof anywhere in the unbacked path — that
      requirement is what this change exists to remove.

## 4. Migration

- [ ] 4.1 Derive each existing pool's initial advertisable set from its proved
      deliverable set, and report each derived set at INFO, matching how the
      deliverable sets were themselves derived.
- [ ] 4.2 Confirm no existing deployment's advertising surface changes on upgrade.
      Verify by comparing resolved advertisable sets before and after migration
      across a fixture covering the system-owned `default` pool, a proved
      single-mode pool, and a pool proving nothing.

## 5. Validation

- [ ] 5.1 **Unit.** Exhaustive declaration cases: valid set, absent, empty,
      malformed, duplicate entries, and subset-rule violations in both
      directions.
- [ ] 5.2 **Integration.** An operator creates an unbacked pool declaring an
      advertisable mode with no provider configuration proving it, through the
      real pool administration API and its canonical client. The claim is not that
      a model accepts the value — it is that the real administration path does not
      demand fake execution configuration.
- [ ] 5.3 **Integration.** A backed pool's widened declaration is rejected on
      write, and the same declaration arriving through an ingested projection is
      rejected there too.
- [ ] 5.4 **Integration.** Migration derives the advertisable set and the resolved
      set is unchanged from before.
- [ ] 5.5 Run the pool administration, projection, and offering-mode enforcement
      suites, including `docs/development/TESTING.md`'s pool offering-mode
      enforcement coverage, and confirm no execution-path assertion changes.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why advertisement does not require a
      delivery proof, not which review found the gap.
- [ ] 6.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table, and re-read
      `docs/development/ARCHITECTURE.md`'s Resource Pool term and pool-mode
      paragraph to decide whether the second declaration belongs in the permanent
      map or is subsystem detail. Record the disposition either way rather than
      leaving the box unchecked.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, the 1.1 decision outcome, and the deferred question about an
      unbacked pool with a non-empty deliverable set.
- [ ] 6.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table
      in `docs/development/ROADMAP.md` and absorb the result into that goal's
      current-state prose.
- [ ] 6.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`.
- [ ] 6.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Advertisement authorization and delivery authorization are separate declarations | `openspec/specs/resource-pool-management/spec.md` |
| A capacity-backed pool's advertisable set is a subset of its deliverable set; an unbacked pool's is independent | `openspec/specs/resource-pool-management/spec.md` |
| Neither declaration is widened by a default; an existing pool's advertisable set derives from its proved deliverable set | `openspec/specs/resource-pool-management/spec.md` |
