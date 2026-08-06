# Design

## Context

See `proposal.md`'s "Why" for motivation. The constraints that shape the approach:

- `openspec/specs/planning-governance/spec.md`'s "Canonical planning homes"
  requirement prohibits a competing normative backlog in ordinary documentation, but
  states the prohibition as a judgment call. Three documents have already been
  written, judged non-compliant, and reduced to redirect stubs under it.
- `docs/development/ARCHITECTURE.md` states in its own header that it "is not a
  backlog or changelog," so directional content cannot simply be appended there.
- `openspec/changes/README.md` already performs a related function — grouping active
  changes into campaigns — and describes itself as "a planning map, not a normative
  specification or an umbrella change." Any new document must not duplicate it.
- Verified 2026-08-06: `design-remaining-work.md` links to
  `genericize-storefront-client-wire` and `prove-multi-domain-capacity`, and
  `provisioning-migration-plan.md` links to `migrate-compute-provisioning`. None of
  the three exists in `openspec/changes/` or `openspec/changes/archive/`.
  `TODO.md`'s links all resolve but point only at directories `openspec/README.md`
  already indexes. Two inbound references name these files:
  `planning-governance/spec.md`'s Evidence list and `provisioning/compute/README.md:31`.
- Verified 2026-08-06: only `pools-8-capacity-projection-and-listing-hints` and
  `fix-vm-fulfillment-capacity-boundary` carry written closeout sections today, so
  extending the closeout contract has a small, enumerable in-flight cost.

## Goals / Non-Goals

**Goals:**

- Give goal-level context a home whose lifecycle matches its lifespan.
- Make the boundary between directional context and a normative backlog checkable at
  review rather than arguable.
- Attach currency to the moment truth changes, and to the contributor who changed it.
- Leave `openspec/changes/README.md`'s jurisdiction intact.

**Non-Goals:**

- A general relaxation of the backlog prohibition.
- Any mechanism (tooling, CI check, link checker) enforcing roadmap currency. The
  closeout contract is a review-enforced discipline, consistent with how comment
  hygiene's fuzzier half and documentation compliance already work.
- Deciding the roadmap's initial goal content. That is written in this change's
  tasks, but the goals themselves come from the repository owner, not from this
  design.

## Decisions

### Directional context lives in `docs/development/`, not `openspec/changes/`

The decisive argument is lifecycle, not topical similarity. `openspec/changes/` is a
directory whose organizing principle is disposal: entries are archived on
completion and archived entries may eventually be removed. `pools-9-retire-local-physical-authority`'s
`design.md` is written defensively around exactly this, duplicating `pools-8`'s
findings because that change's documents are expected to disappear. A document
intended to outlive several campaigns cannot live in the directory designed to
delete its neighbors. `docs/development/` is where documents are corrected in place
indefinitely, which is the lifecycle the roadmap needs.

Alternatives considered:

- **`openspec/changes/ROADMAP.md`.** Rejected on the lifecycle argument above, and
  because proximity to `changes/README.md` invites the two to merge in practice —
  they answer different questions at different cadences.
- **Extend `openspec/changes/README.md` with a goals preamble.** Rejected for the
  same merge risk in its most acute form: one file cannot credibly carry both
  volatile per-change readiness and stable goal rationale without the stable half
  being churned by the volatile half's edit rate.
- **`docs/ROADMAP.md`, beside the role guides.** Defensible if the primary audience
  is non-contributor, and `docs/` root does hold audience-facing material
  (`roles.md`, the quickstarts). Rejected because the roadmap is most useful read
  against `ARCHITECTURE.md` — one says what the system is, the other where it is
  going — and folder proximity serves that reading better than it serves
  discoverability, which a direct link solves either way.

### Three cross-cutting documents, three jurisdictions

The roadmap is defined by what it does *not* carry, so the boundary is stated
positively for all three:

| Document | Owns | Cadence |
|---|---|---|
| `docs/development/ARCHITECTURE.md` | what the system is and why its boundaries exist | corrected when the system changes |
| `docs/development/ROADMAP.md` | which goals are being pursued, the value each delivers, current state per goal, and which change owns each gap | corrected when a goal's truth changes |
| `openspec/changes/README.md` | delivery sequence, readiness, blocking, acceptance boundaries | corrected as changes start, block, and finish |

The single rule that keeps the roadmap from becoming a backlog: **it carries no
status.** No readiness, no blocking, no ordering, no acceptance criteria, no tasks. A
change appears as a link plus one line naming the gap it closes; a reader asking
whether that change can start goes to `changes/README.md`. This is expressed as a
normative requirement rather than a convention precisely because the previous
convention-shaped prohibition produced three abandoned documents.

### Current-state prose plus an active-gap table, not a static change list

A fixed table of change links rots as changes are renamed, archived, or absorbed.
Each goal therefore carries two parts:

1. A present-tense **current state** paragraph, evidence-based and corrected in
   place, following `ARCHITECTURE.md`'s own discipline.
2. A table of **open gaps only**, each mapped to the change that owns it.

When a change completes, its row leaves the table and whatever became true is
absorbed into the current-state paragraph. This gives progress visibility — the
current-state paragraph legibly grows as gaps close — without the roadmap becoming a
changelog, which `ARCHITECTURE.md` explicitly forbids for itself and which the
"describe current state, not history" rule forbids repository-wide.

It also fixes the decay mode observed in the retired stubs. Those broke because they
linked to changes and outlived them. Here, a link exists only while its change is in
flight; the moment a change completes, the link is replaced by prose describing its
result. Links cannot outlive their targets because nothing links to a completed
change.

### Currency attaches to change closeout, not to periodic review

Periodic roadmap review has no trigger and no owner, and would re-derive from the
codebase what the implementing contributor already knew. The closeout task is
already the point where a contributor is required to re-check documentation
placement and complete a promotion record, so adding roadmap currency there attaches
the update to the moment the truth changed, done by the person who changed it.

Currency is tied to change **completion**, not archival, because a completed change
may sit unarchived for a long time —
`pools-8-capacity-projection-and-listing-hints` is exactly this case today. Waiting
for archival would make the roadmap systematically lag the codebase by the length of
the archive backlog.

The sixth closeout part is expected to be a single line in most changes, frequently
"no roadmap impact." That disposition must be recorded rather than omitted, so the
absence of a roadmap edit is a deliberate finding instead of an unanswered question
at review.

### A goal leaves the roadmap when it is achieved

The terminal state is deliberate rather than left implicit. When a goal's gaps are
all closed, its durable result is already in `ARCHITECTURE.md` or the owning
capability's `spec.md`/`architecture.md` through the ordinary promotion path, so the
goal is removed from the roadmap rather than retained as a completed entry. Retaining
finished goals would turn the roadmap into the changelog this design has otherwise
kept it from becoming, and the record of what was done already exists in Git history
and the archived changes.

### Stub retirement belongs in this change

Retiring `TODO.md`, `design-remaining-work.md`, and `provisioning-migration-plan.md`
is technically independently archivable, which `openspec/config.yaml`'s task rules
would normally push into a separate change. It is kept here because the three stubs
are the *previous* answer to the question this change re-answers — where directional
and planning-facing content lives under `docs/` — and because two of the edits
overlap physically: `planning-governance/spec.md`'s Evidence list, which this change
is already editing, names all three by filename. Splitting would leave a spec whose
Evidence cites files a sibling change is deleting.

Per `AGENTS.md`, all three are delivered as tombstones at their original paths.

### The governance amendment is a narrow carve-out

"Canonical planning homes" keeps its prohibition and gains a definition: a document
maintains a competing backlog when it carries implementation tasks, acceptance
criteria, or readiness status for work a change owns or should own. Stating a goal,
its value, current behavior, and a link to the owning change does not. The permitted
roadmap is singular and named at a specific path, with an explicit scenario rejecting
a second one. This is intended to survive review as a bounded exception rather than
an opening for planning content to return to `docs/` generally.

## Risks / Trade-offs

- **[The roadmap drifts into a backlog anyway]** → The constraints are normative
  requirements with scenarios, so drift is a spec violation catchable at review, not
  a matter of taste. The "no status" rule is the single checkable proxy: any
  readiness word in the roadmap is a defect.
- **[Closeout burden creep]** → The sixth part is one line in the common case, and
  the roadmap's own constraints cap the size of any update. If the sixth part is
  routinely large, that indicates the roadmap has acquired detail it should not have.
- **[A roadmap goal contradicts a recorded non-goal in an active change]** → This is
  already true for multi-domain storefront composition, which contradicts explicit
  non-goals in `market-platform-bare-metal-10-storefront-composition` and
  `market-platform-compute-40-multi-domain-proof`. The roadmap states such
  contradictions explicitly as unreconciled rather than silently superseding a
  recorded position; reconciliation is the work of the goal's own later change.
- **[Goal-level content becomes stale between closeouts]** → Accepted. The roadmap is
  as current as the last completed change, which is the same guarantee
  `ARCHITECTURE.md` offers, and better than the status quo of no guarantee at all.
- **[Two in-flight changes' closeouts are amended mid-flight]** → Both amendments are
  additive task entries, consistent with `AGENTS.md`'s rule to amend or append rather
  than replace implementation history.

## Migration Plan

1. Amend `openspec/specs/planning-governance/spec.md` (requirements via the delta,
   Evidence list directly) and `openspec/README.md`'s closeout section and
   documentation-placement table.
2. Create `docs/development/ROADMAP.md` with its preamble stating the three-document
   division of labor, then its goal content.
3. Link it from `ARCHITECTURE.md`'s document map.
4. Tombstone the three stubs and repoint `provisioning/compute/README.md`.
5. Append the sixth closeout part to the two in-flight changes' closeout sections.
6. Run `openspec validate --all --strict` and confirm no regression against the
   baseline recorded 2026-08-06: 37 passed, 7 failed, every failure a change carrying
   no spec deltas — `add-buyer-vm-connectivity-terms`,
   `add-storefront-principal-authentication`, `fix-vm-fulfillment-capacity-boundary`,
   `negotiation-driven-capacity-resize`, `pools-9-retire-local-physical-authority`,
   `refactor-e2e-fulfillment-lifecycle`, and `structured-capacity-requirements`. With
   this change's own artifacts in place the suite reports 38 passed and the same 7
   failures, confirming it adds a pass and no regression.

Rollback is a documentation revert: delete the roadmap, restore the spec
requirements and closeout section, restore the three stubs from version control.
Nothing at runtime depends on any of it.

## Open Questions

- **Do roadmap goals need stable identifiers?** The required link direction is
  roadmap → change. The reverse (a change's proposal declaring which goal it serves)
  would be useful for orientation but creates a second link to maintain and, if goals
  are numbered, a renumbering hazard. Deferrable: adding stable goal slugs later
  changes no requirement, no approach, and no task in this change, and is best
  decided once there is evidence contributors actually want the reverse link.
- **Does a non-contributor audience eventually need a rendered view?** The stated
  motivation includes readers outside the contributor loop. A plain Markdown document
  in a contributor directory may prove sufficient, or may not. Deferrable because any
  export is derived from this document rather than replacing it.
