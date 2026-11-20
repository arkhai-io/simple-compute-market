## Why

How much work one implementation session takes on is decided before any of it is
written. The design discussion settles the change's implementation cadence — how
many rounds, what each covers, and how many sessions implement each — and planning
maps it onto the sections (`change-workflow`'s "The implementation cadence is
settled in design and mapped by the plan"). Both judge the size of work that does
not exist yet, and both have to judge it well: compliance with the guidance degrades
as a session grows and collapses after it compacts, so `change-implement` stops a
section "far larger than its plan" and calls it a planning defect.

That estimate is wrong often enough to cost the owner attention on most changes.
In `spot-deals-through-arkhai-payments`, round 2:

- section 4B's session stopped after 4B.1–4B.3 and asked to split the rest into a
  fresh session;
- sections 4C and 4D, planned for one session, were split in two;
- sections 4E and 4F each ran close to compaction on their own.

Each split stopped the change until the owner agreed to it, and the orchestrator
recorded the new sessions by hand. The owner gave a standing acceptance of
fresh-session splits for the rest of that orchestration, which says the decision
carries no judgement worth asking for each time. What the owner does need to settle
— how much is reviewed together, and in what order the work lands — is the
cadence's rounds, not its sessions.

## What Changes

- **A session's size is measured as it runs, not guessed beforehand.** An
  implementation session ends when the work it holds would take it past a
  threshold, at the end of a committed section or at a verified point inside one,
  and hands the rest to a fresh session. Who measures — the session judging its own
  context, or the wrapper reading the harness's token counts — is settled in design.
- **A split is a logged event, not an owner decision.** The engine records the
  continuation and starts the next session itself, within the same round. The owner
  sees the split in the log and the run's messages; the round, its review, and its
  triage are unchanged.
- **The cadence settles rounds; sessions follow from the work.** Design and
  planning stop sizing sessions. Whether planning's session grouping is dropped or
  kept as a hint the splitting may override is settled in design.
- **A section larger than planned is no longer a stop.** `change-implement`'s
  "sized wrong" stop becomes a split, with a note for the plan's author where the
  section's scope, not its size, was wrong.

## Public interfaces

Each is named here as `docs/guidance/workflow/changes.md` requires; which change and
whether it is compatible is settled in design:

- planning's outcome field `rounds`, whose inner lists are sessions;
- the implementation outcome, which may gain a continuation exit or field;
- the `round` log line and how a round's sessions are recorded;
- `scripts/change-workflow next`'s implementation result and its `sections`;
- the `change-implement` and `change-plan` skills, and `change-design`'s cadence
  question.

## Capabilities

### New Capabilities

- None expected.

### Modified Capabilities

- `change-workflow`: the implementation cadence requirement, round recording, the
  implementation step's outcome, and the engine's handling of a session's
  continuation.

## Non-Goals

- **Do not change what a round is.** How much is reviewed together stays the
  owner's decision in design.
- **Do not split other steps.** Design, triage, and closeout hold conversations
  with the owner, and a review is one reading. Validation and closeout may be
  candidates later; this change is the implementation step's.
- **Do not prevent compaction by any other means.** Guidance loading, context
  budgets per document, and harness settings are out of scope.

## Impact

- `scripts/change_workflow/` — the wrapper's start and resume, the next-step
  computation, the log's round lines, and the outcome schema.
- `.agents/skills/change-implement/`, `change-plan/`, and `change-design/`.
- `change-workflow`'s specification, companion, and diagrams, and
  `docs/change-workflow-handbook.md`.

## Dependencies and Related Changes

- **Independent:** nothing must land first.
- **`add-workflow-harness-adapters`.** If the wrapper measures a session by the
  harness's token counts, each adapter reports them; whichever lands second wires
  the other in.
- **The round base lost on a replan** (an unowned row of
  `openspec/changes/README.md`). A continuation inside a round must keep the round's
  base; design checks whether this change closes that gap too.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
