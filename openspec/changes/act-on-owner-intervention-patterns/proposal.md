## Why

Triage brings every finding to the owner one message at a time and waits for a
disposition on each. It then asks whether the accepted fixes merit another review
round. That protects the owner's attention for findings that need judgement, but most
findings do not need it. The owner reads each one in full and answers "Agreed".

The owner's recorded dispositions show where the turns go. Triage records hold 478
findings from the changes triaged between 2026-10-14 and 2026-11-03. For 313 of
them, the orchestrated triage's full presentation survives in the workflow log.

- **Most findings are accepted as proposed.** That is 79% of all findings.
- **One class is almost never corrected.** In this class the triage agent agrees
  with the finding and proposes one edit or fix. It lays out no alternatives and
  names nothing that would change its recommendation. The finding comes from a
  review, not from a validation record or the owner's own notes. Of the 313
  presented findings, 108 were in this class: 102 accepted as proposed, 5 accepted
  with added context, and 1 overridden.
- **Advance recommendations are accepted.** The agent recommended advancing at 56
  gates and the owner agreed at 55. It recommended another round at 20 and the
  owner agreed at 18, so disagreement concentrates there.
- **Interventions come early.** They cluster in the first findings of a round,
  which are the most severe and the ones carrying real choices. They fall away
  after the second finding.

`design.md` gives the method, every table, and the held-out check.

Each finding in that class costs the owner a full read and a turn. A round of
twelve findings can hold six of them, presented after the decisions that needed
the owner's attention.

## What Changes

- **Triage classifies each finding at triage time.** A finding is either
  discussed or accepted by default. The rule uses only facts known before it is
  presented:
  - the reviewer's severity;
  - the record it came from;
  - the agent's stance and proposed outcome;
  - whether the agent sees an alternative worth weighing, or a fact that would
    change its recommendation;
  - what the fix affects.

  The rule's width is settled in design from the evidence in `design.md`.
- **Discussed findings are presented as today.** One finding per message, in the
  same order, each disposed of only by the owner's word.
- **Default-accepted findings are reported, not asked.** At the end of the round,
  after the discussed findings are disposed of, triage reports every
  default-accepted finding in one table: its label, severity, the finding in one
  line, and its outcome. Each is recorded in the triage file as accepted by
  default, so the record tells it apart from a disposition the owner stated. The
  fixes are made with the round's other accepted fixes.
- **Advancing is the default exit.** When the agent recommends advancing, triage
  takes the advancing exit without asking and reports it beside the table. A
  recommendation of another round is still argued and asked, as today.
- **A triage can finish without asking anything.** This happens when every finding
  is accepted by default and the agent recommends advancing. Today only a triage
  with nothing to dispose of finishes that way.
- **The owner can revisit afterwards.** The owner may reopen any default-accepted
  finding, or the exit, by telling the orchestrating session. A revision is
  recorded in the intervention ledger as revising that finding. How a revision
  reaches work already committed or a step already started is a design question.
- **The batch is measurable.** Default acceptances and their later revisions are
  recorded, so a later guidance review can measure how often the batch is
  reopened.

### Out of scope

- **Folding revisits into the workflow graph.** If revisits of default
  acceptances turn out to be frequent, normalizing them into the workflow graph is
  a later change.
- **The design discussion.** It already presents consequence and convention
  decisions together for confirmation.
- **Waivers recommended by agents.** Agents recommending a waiver of validation
  for commits that change only specifications, comments or tests is an open
  question in `design.md`, not part of this change's scope unless design takes it
  in.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `change-workflow`: the owner's touchpoints in triage, the disposition of every
  finding, the intervention ledger's treatment of revised default acceptances, and
  the one-finding-per-turn rule for orchestrated triage.

## Impact

- **Specification.** `openspec/specs/change-workflow/spec.md` changes these
  requirements:
  - "Phases and owner touchpoints": the owner is consulted for every finding and
    for whether another round is merited.
  - "Triage of every finding".
  - "Intervention ledger".
  - "Discussion steps stay conversations with the owner".

  `openspec/specs/change-workflow/architecture.md` changes its "Triage" section.
- **Skills.** `.agents/skills/change-triage/SKILL.md` changes its presenting,
  recording and exit steps. `.agents/skills/change-orchestrate/SKILL.md` changes
  how it relays the round's table and routes a revisit.
- **Guidance.** `docs/agents/change-workflow.md` changes its triage and ledger
  sections.
- **Tooling.** No change to the next-step computation is expected. The
  advancing exit is recorded as it is today. Design confirms this.
- **Coordination.**
  - `extract-change-workflow-repository` moves these skills, the workflow
    specification and the guidance to a separate repository.
  - `add-skill-extension-points` restructures the skills into slots.

  Neither has started. This change does not depend on them. Whichever lands
  second carries the other's edit.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The default-acceptance rule and the advancing default:
  `openspec/specs/change-workflow/spec.md`.
- Why a class of findings is accepted by default, what keeps the owner's later
  revision possible, and the evidence the rule rests on in summary:
  `openspec/specs/change-workflow/architecture.md`, "Triage".
- The table, the record of a default acceptance, and how to revisit one:
  `docs/agents/change-workflow.md`.
