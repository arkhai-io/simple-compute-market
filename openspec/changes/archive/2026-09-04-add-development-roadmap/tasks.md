# Implementation Tasks

## 1. Amend the governance contract

The roadmap cannot be created compliantly until the requirement permitting it
exists, so this section precedes the document itself.

- [x] 1.1 Author the `planning-governance` delta: two ADDED requirements ("Directional
      roadmap document", "Roadmap currency at change closeout") and the MODIFIED
      "Canonical planning homes" requirement defining what makes documentation a
      competing backlog. **Done (2026-08-06).** Amended from "apply" to "author":
      OpenSpec synchronizes requirement deltas into `openspec/specs/` at archive, per
      `openspec/README.md`'s contributor workflow step 7, not during implementation.
      `openspec validate add-development-roadmap --type change --strict` passes.
- [x] 1.2 Edit `openspec/specs/planning-governance/spec.md`'s Evidence section
      directly — OpenSpec's delta synchronizer covers requirements only. Remove the
      three retiring filenames from the "Non-normative legacy redirects" entry and
      add `docs/development/ROADMAP.md` as evidence for the two new requirements.
      Confirm the `migrate-planning-to-openspec` ledger entry stays, since it carries
      the migration-provenance evidence independently of the stubs.
- [x] 1.3 Extend `openspec/README.md#plan-closeout-requirements` from five parts to
      six, adding **Roadmap currency**: update the affected goal's current-state
      description and gap mapping in `docs/development/ROADMAP.md`, name the update in
      the design-promotion record, or record explicitly that no roadmap update is
      owed. Update the section's own "The closeout task has five parts" sentence.
- [x] 1.4 Add a `docs/development/ROADMAP.md` row to `openspec/README.md`'s
      "Documentation placement" table, naming its jurisdiction (goals, value, current
      state per goal, gap-to-change mapping) so it reads against the existing
      `ARCHITECTURE.md` and `openspec/changes/` rows rather than overlapping them.
- [x] 1.5 Verify: `openspec validate planning-governance --type spec --strict` and
      `openspec validate add-development-roadmap --type change --strict` both pass.

## 2. Create the roadmap document

- [x] 2.1 Write `docs/development/ROADMAP.md`'s preamble: purpose, the explicit
      statement that it carries no readiness status or sequencing, and the
      three-document division of labor table (`ARCHITECTURE.md` / `ROADMAP.md` /
      `openspec/changes/README.md`) from `design.md`'s "Three cross-cutting documents,
      three jurisdictions".
- [x] 2.2 Write each goal's section: the goal, the value it delivers, and an
      evidence-based present-tense current-state paragraph. Current state must cite
      real code, configuration, or specification evidence per the "Evidence-based
      baseline specifications" requirement — not restate intent as though implemented.
- [x] 2.3 Write each goal's open-gap table, mapping gaps to the changes that own
      them. Populate only from changes that already exist. A gap identified during
      goal analysis with no owning change is not listed as a standing roadmap item;
      it triggers opening a change, and that change's own work adds the row — see
      "Directional roadmap document"'s first scenario.
- [x] 2.4 Record, in the goals where it applies, any place a goal contradicts a
      recorded non-goal in an active change — including multi-domain storefront
      composition against `market-platform-bare-metal-10-storefront-composition` and
      `market-platform-compute-40-multi-domain-proof` — stating the contradiction as
      unreconciled and naming reconciliation as the goal's own later work.
- [x] 2.5 Self-check the finished document against the new requirement: no
      implementation tasks, no acceptance criteria, no readiness or blocking status,
      no delivery sequencing, and every listed gap carrying a link to its owning
      change.

## 3. Cross-document linkage

- [x] 3.1 Add a roadmap row to `docs/development/ARCHITECTURE.md`'s "Document map"
      table, and a sentence in its header note distinguishing the roadmap's
      jurisdiction from `ARCHITECTURE.md`'s own "not a backlog or changelog" scope.
- [x] 3.2 Confirm the roadmap links back to `ARCHITECTURE.md` and
      `openspec/changes/README.md`, so all three documents name the other two.

## 4. Retire the superseded planning stubs

Sequenced after Sections 1–3 so no window exists where a stub is gone and its
replacement is not yet in place.

- [x] 4.1 Re-run the inbound-reference search before deleting, rather than trusting
      `design.md`'s 2026-08-06 findings unchanged: confirm the only inbound references
      to `docs/development/TODO.md`, `design-remaining-work.md`, and
      `provisioning-migration-plan.md` remain `planning-governance/spec.md`'s Evidence
      list (handled in 1.2) and `provisioning/compute/README.md`. Confirm also that
      each stub's redirect targets are still absent from `openspec/changes/` and
      `openspec/changes/archive/`.
- [x] 4.2 Replace `provisioning/compute/README.md`'s pointer at
      `docs/development/provisioning-migration-plan.md` with the current owning
      contracts — `openspec/specs/physical-provisioning/spec.md` and
      `openspec/specs/site-capacity/spec.md` — matching what the stub itself already
      named as current.
- [x] 4.3 Tombstone `docs/development/TODO.md`,
      `docs/development/design-remaining-work.md`, and
      `docs/development/provisioning-migration-plan.md` per `AGENTS.md`'s generated
      implementation artifacts rule: single-line tombstone at the original path
      stating the reason.
- [x] 4.4 Verify no remaining repository reference resolves to any of the three
      paths, and that `openspec/README.md`, `ARCHITECTURE.md`, and the role guides
      contain no orphaned link.

## 5. Amend in-flight closeout sections

- [x] 5.1 Append the sixth closeout part to
      `pools-8-capacity-projection-and-listing-hints`'s existing per-section closeout
      entries. Amend rather than rewrite, per `AGENTS.md`'s rule on preserving
      implementation history. Its completed sections' roadmap dispositions are
      recorded as findings at the current date, not backdated.
- [x] 5.2 Append the sixth closeout part to
      `fix-vm-fulfillment-capacity-boundary`'s closeout section.
- [x] 5.3 Confirm no other active change carries a written closeout section that
      needs amending; every other change picks up the sixth part when it plans its
      own closeout.

## 6. Validation

- [x] 6.1 Run `openspec validate --all --strict`. Confirm the seven pre-existing
      failures enumerated in `design.md`'s migration plan are unchanged in number and
      identity — all are changes carrying no spec deltas — and that this change adds
      none. Re-derive the baseline at implementation time rather than trusting the
      recorded one, since other changes may have gained or lost deltas since
      2026-08-06.
- [x] 6.2 Run `make check-comment-hygiene`. Expected clean: this change touches no
      `*.py`, `*.yml`, or `*.yaml` file, which is the target's entire scan scope.
- [x] 6.3 Re-read the finished roadmap against `openspec/config.yaml`'s vocabulary
      rules and correct any goal description using non-official terminology for
      Capacity Reservation, Physical Resource, Resource Pool, Settlement Resource, or
      the other named terms.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`, as amended by this change to six
parts — this change is the first to run its own new sixth part.

- [x] 7.1 **Comment hygiene.** Not applicable by scan scope (see 6.2); confirm by
      running the target rather than asserting it. No production code is touched, so
      the fuzzier `AGENTS.md` "comments describe the current system" read has no
      subject.
- [x] 7.2 **Import placement.** Not applicable; this change adds no imports.
- [x] 7.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules — specifically that the
      permitted-roadmap constraints and the closeout-currency rule landed in
      `openspec/specs/planning-governance/spec.md` as normative requirements, and that
      the reasoning for choosing `docs/development/` over `openspec/changes/` is in
      this change's `design.md` and the roadmap's own preamble, not duplicated into
      the spec.
- [x] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations; keep the alternatives
      considered for document placement in `design.md` rather than restating them here.
- [x] 7.5 **Roadmap currency.** This change creates the roadmap rather than altering a
      goal's current state, so no goal's current-state paragraph is owed an update.
      Record that disposition explicitly. Confirm the document as published satisfies
      its own new requirement (2.5's self-check re-run after any late edits).
- [x] 7.6 **Promotion.** Complete the design-promotion record below.
- [x] 7.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. **Done:** the campaign index was reconciled
      on 2026-09-04 and this change's row removed from it on archival. That removal is the
      disposition a completed change owes the index — an archived change leaves the
      active-change index rather than holding a status inside it.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A single permitted directional roadmap, with its no-tasks/no-acceptance-criteria/no-status constraints | `openspec/specs/planning-governance/spec.md` — "Directional roadmap document" |
| Roadmap currency is owed at change completion, not archival, and a null disposition is recorded explicitly | `openspec/specs/planning-governance/spec.md` — "Roadmap currency at change closeout" |
| What distinguishes permitted directional context from a competing normative backlog | `openspec/specs/planning-governance/spec.md` — "Canonical planning homes" |
| The sixth closeout part and its expected null-case form | `openspec/README.md#plan-closeout-requirements` |
| Three-document division of labor across `ARCHITECTURE.md`, `ROADMAP.md`, and `openspec/changes/README.md` | `docs/development/ROADMAP.md` preamble, with document-map rows in `docs/development/ARCHITECTURE.md` and `openspec/README.md`'s placement table |
| Why directional context cannot live in `openspec/changes/` (change directories are designed to be archived and deleted) | This change's `design.md`; summarized in the roadmap preamble. Not promoted to the spec — the requirement states the rule, not its history |


## Implementation notes (2026-08-06)

Recorded at the level `openspec/README.md`'s narrative-compression rule asks for:
final behavior, material evidence, and unresolved work. Fuller reasoning stays in
`design.md`.

**Section 1.** `openspec/README.md`'s closeout section now reads "six parts" with
roadmap currency as part 5 and promotion renumbered to 6; the documentation-placement
table gained a `ROADMAP.md` row. `planning-governance/spec.md`'s Evidence list no
longer names the three retired stubs and now names the three-document separation, the
permitted roadmap, and the closeout part. The `migrate-planning-to-openspec` ledger
entry was confirmed to remain, so the "Complete migration provenance" requirement
keeps its evidence independently of the stubs.

**Section 2.** `docs/development/ROADMAP.md` carries four goals. Goal 1 is at full
depth from the completed sweep; Goals 2–4 carry goal, value, and evidence-based
current state with gap tables populated only from changes that already exist.

Goal 2's known pricing and negotiation-policy gap has no owning change, so per
"Directional roadmap document" it is **not** a gap-table row. It is stated in Goal 2's
current-state prose as a fact about the system, which is where an uncovered gap
belongs — the gap table stays honest about what is owned, and the prose stays honest
about what is true. Goal 4 records the same disposition for the kit reorganization.

**Section 3.** `ARCHITECTURE.md`'s purpose note and document map now name the
roadmap's jurisdiction against its own "not a backlog or changelog" scope, and the
roadmap links back to both `ARCHITECTURE.md` and `openspec/changes/README.md`.

**Section 4.** Inbound-reference and redirect-target searches were re-run rather than
trusted from `design.md`: all three stubs' targets remain absent from
`openspec/changes/` and its archive, and the only inbound reference outside
`planning-governance/spec.md` was `provisioning/compute/README.md`, repointed at the
physical-provisioning and site-capacity specifications. All three stubs tombstoned.
Post-retirement orphan-link scan is clean.

**Section 5.** `fix-vm-fulfillment-capacity-boundary` gained task 6.8 and
`pools-8-capacity-projection-and-listing-hints` gained task 7.6, both appended rather
than folded into existing tasks. `pools-8`'s section-7 preamble was corrected from
"has five parts" to "had five parts when this section was written," naming the
addition. No other active change carries a written closeout section.

**Section 6.** `make check-comment-hygiene` passes. `openspec validate --all --strict`
reports 40 passed / 6 failed; the six are unchanged from the recorded baseline minus
`pools-9-retire-local-physical-authority`, which gained spec deltas independently and
now passes. This change adds no failure. The roadmap self-check found no readiness or
sequencing vocabulary outside the three sentences that exist to disclaim it.

**Unresolved.** The two open questions in `design.md` — stable goal identifiers and a
rendered non-contributor view — remain deliberately deferred; neither affects the
requirements, the approach, or this task breakdown.
