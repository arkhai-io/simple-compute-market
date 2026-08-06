# Implementation Tasks

## 1. Amend the governance contract

The roadmap cannot be created compliantly until the requirement permitting it
exists, so this section precedes the document itself.

- [ ] 1.1 Apply the `planning-governance` delta from `specs/planning-governance/spec.md`:
      two ADDED requirements ("Directional roadmap document", "Roadmap currency at
      change closeout") and the MODIFIED "Canonical planning homes" requirement that
      defines what makes documentation a competing backlog.
- [ ] 1.2 Edit `openspec/specs/planning-governance/spec.md`'s Evidence section
      directly — OpenSpec's delta synchronizer covers requirements only. Remove the
      three retiring filenames from the "Non-normative legacy redirects" entry and
      add `docs/development/ROADMAP.md` as evidence for the two new requirements.
      Confirm the `migrate-planning-to-openspec` ledger entry stays, since it carries
      the migration-provenance evidence independently of the stubs.
- [ ] 1.3 Extend `openspec/README.md#plan-closeout-requirements` from five parts to
      six, adding **Roadmap currency**: update the affected goal's current-state
      description and gap mapping in `docs/development/ROADMAP.md`, name the update in
      the design-promotion record, or record explicitly that no roadmap update is
      owed. Update the section's own "The closeout task has five parts" sentence.
- [ ] 1.4 Add a `docs/development/ROADMAP.md` row to `openspec/README.md`'s
      "Documentation placement" table, naming its jurisdiction (goals, value, current
      state per goal, gap-to-change mapping) so it reads against the existing
      `ARCHITECTURE.md` and `openspec/changes/` rows rather than overlapping them.
- [ ] 1.5 Verify: `openspec validate planning-governance --type spec --strict` and
      `openspec validate add-development-roadmap --type change --strict` both pass.

## 2. Create the roadmap document

- [ ] 2.1 Write `docs/development/ROADMAP.md`'s preamble: purpose, the explicit
      statement that it carries no readiness status or sequencing, and the
      three-document division of labor table (`ARCHITECTURE.md` / `ROADMAP.md` /
      `openspec/changes/README.md`) from `design.md`'s "Three cross-cutting documents,
      three jurisdictions".
- [ ] 2.2 Write each goal's section: the goal, the value it delivers, and an
      evidence-based present-tense current-state paragraph. Current state must cite
      real code, configuration, or specification evidence per the "Evidence-based
      baseline specifications" requirement — not restate intent as though implemented.
- [ ] 2.3 Write each goal's open-gap table, mapping gaps to the changes that own
      them. Populate only from changes that already exist. A gap identified during
      goal analysis with no owning change is not listed as a standing roadmap item;
      it triggers opening a change, and that change's own work adds the row — see
      "Directional roadmap document"'s first scenario.
- [ ] 2.4 Record, in the goals where it applies, any place a goal contradicts a
      recorded non-goal in an active change — including multi-domain storefront
      composition against `market-platform-bare-metal-10-storefront-composition` and
      `market-platform-compute-40-multi-domain-proof` — stating the contradiction as
      unreconciled and naming reconciliation as the goal's own later work.
- [ ] 2.5 Self-check the finished document against the new requirement: no
      implementation tasks, no acceptance criteria, no readiness or blocking status,
      no delivery sequencing, and every listed gap carrying a link to its owning
      change.

## 3. Cross-document linkage

- [ ] 3.1 Add a roadmap row to `docs/development/ARCHITECTURE.md`'s "Document map"
      table, and a sentence in its header note distinguishing the roadmap's
      jurisdiction from `ARCHITECTURE.md`'s own "not a backlog or changelog" scope.
- [ ] 3.2 Confirm the roadmap links back to `ARCHITECTURE.md` and
      `openspec/changes/README.md`, so all three documents name the other two.

## 4. Retire the superseded planning stubs

Sequenced after Sections 1–3 so no window exists where a stub is gone and its
replacement is not yet in place.

- [ ] 4.1 Re-run the inbound-reference search before deleting, rather than trusting
      `design.md`'s 2026-08-06 findings unchanged: confirm the only inbound references
      to `docs/development/TODO.md`, `design-remaining-work.md`, and
      `provisioning-migration-plan.md` remain `planning-governance/spec.md`'s Evidence
      list (handled in 1.2) and `provisioning/compute/README.md`. Confirm also that
      each stub's redirect targets are still absent from `openspec/changes/` and
      `openspec/changes/archive/`.
- [ ] 4.2 Replace `provisioning/compute/README.md`'s pointer at
      `docs/development/provisioning-migration-plan.md` with the current owning
      contracts — `openspec/specs/physical-provisioning/spec.md` and
      `openspec/specs/site-capacity/spec.md` — matching what the stub itself already
      named as current.
- [ ] 4.3 Tombstone `docs/development/TODO.md`,
      `docs/development/design-remaining-work.md`, and
      `docs/development/provisioning-migration-plan.md` per `AGENTS.md`'s generated
      implementation artifacts rule: single-line tombstone at the original path
      stating the reason.
- [ ] 4.4 Verify no remaining repository reference resolves to any of the three
      paths, and that `openspec/README.md`, `ARCHITECTURE.md`, and the role guides
      contain no orphaned link.

## 5. Amend in-flight closeout sections

- [ ] 5.1 Append the sixth closeout part to
      `pools-8-capacity-projection-and-listing-hints`'s existing per-section closeout
      entries. Amend rather than rewrite, per `AGENTS.md`'s rule on preserving
      implementation history. Its completed sections' roadmap dispositions are
      recorded as findings at the current date, not backdated.
- [ ] 5.2 Append the sixth closeout part to
      `fix-vm-fulfillment-capacity-boundary`'s closeout section.
- [ ] 5.3 Confirm no other active change carries a written closeout section that
      needs amending; every other change picks up the sixth part when it plans its
      own closeout.

## 6. Validation

- [ ] 6.1 Run `openspec validate --all --strict`. Confirm the seven pre-existing
      failures enumerated in `design.md`'s migration plan are unchanged in number and
      identity — all are changes carrying no spec deltas — and that this change adds
      none. Re-derive the baseline at implementation time rather than trusting the
      recorded one, since other changes may have gained or lost deltas since
      2026-08-06.
- [ ] 6.2 Run `make check-comment-hygiene`. Expected clean: this change touches no
      `*.py`, `*.yml`, or `*.yaml` file, which is the target's entire scan scope.
- [ ] 6.3 Re-read the finished roadmap against `openspec/config.yaml`'s vocabulary
      rules and correct any goal description using non-official terminology for
      Capacity Reservation, Physical Resource, Resource Pool, Settlement Resource, or
      the other named terms.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`, as amended by this change to six
parts — this change is the first to run its own new sixth part.

- [ ] 7.1 **Comment hygiene.** Not applicable by scan scope (see 6.2); confirm by
      running the target rather than asserting it. No production code is touched, so
      the fuzzier `AGENTS.md` "comments describe the current system" read has no
      subject.
- [ ] 7.2 **Import placement.** Not applicable; this change adds no imports.
- [ ] 7.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules — specifically that the
      permitted-roadmap constraints and the closeout-currency rule landed in
      `openspec/specs/planning-governance/spec.md` as normative requirements, and that
      the reasoning for choosing `docs/development/` over `openspec/changes/` is in
      this change's `design.md` and the roadmap's own preamble, not duplicated into
      the spec.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations; keep the alternatives
      considered for document placement in `design.md` rather than restating them here.
- [ ] 7.5 **Roadmap currency.** This change creates the roadmap rather than altering a
      goal's current state, so no goal's current-state paragraph is owed an update.
      Record that disposition explicitly. Confirm the document as published satisfies
      its own new requirement (2.5's self-check re-run after any late edits).
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A single permitted directional roadmap, with its no-tasks/no-acceptance-criteria/no-status constraints | `openspec/specs/planning-governance/spec.md` — "Directional roadmap document" |
| Roadmap currency is owed at change completion, not archival, and a null disposition is recorded explicitly | `openspec/specs/planning-governance/spec.md` — "Roadmap currency at change closeout" |
| What distinguishes permitted directional context from a competing normative backlog | `openspec/specs/planning-governance/spec.md` — "Canonical planning homes" |
| The sixth closeout part and its expected null-case form | `openspec/README.md#plan-closeout-requirements` |
| Three-document division of labor across `ARCHITECTURE.md`, `ROADMAP.md`, and `openspec/changes/README.md` | `docs/development/ROADMAP.md` preamble, with document-map rows in `docs/development/ARCHITECTURE.md` and `openspec/README.md`'s placement table |
| Why directional context cannot live in `openspec/changes/` (change directories are designed to be archived and deleted) | This change's `design.md`; summarized in the roadmap preamble. Not promoted to the spec — the requirement states the rule, not its history |
