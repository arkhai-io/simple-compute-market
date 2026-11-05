## Why

The owner's recorded responses to agents say two things the workflow does not yet act
on.

**Most of triage asks the owner what the owner always answers the same way.** Triage
brings every finding to the owner one message at a time and waits for a disposition on
each. It then asks whether the accepted fixes merit another review round. Triage
records hold 478 findings from the changes triaged between 2026-10-14 and 2026-11-03.
For 313 of them, the orchestrated triage's full presentation survives in the workflow
log.

- **Most findings are accepted as proposed.** That is 79% of all findings.
- **One class is almost never corrected.** In this class the triage agent agrees with
  the finding and proposes one edit or fix. It lays out no alternatives and names
  nothing that would change its recommendation. The finding comes from a review, not
  from a validation record or the owner's own notes. Of the 313 presented findings,
  108 were in this class: 102 accepted as proposed, 5 accepted with added context, and
  1 overridden.
- **Advance recommendations are accepted.** The agent recommended advancing at 56
  gates and the owner agreed at 55. It recommended another round at 20 and the owner
  agreed at 18, so disagreement concentrates there.
- **Interventions come early.** They cluster in the first findings of a round, which
  are the most severe and the ones carrying real choices. They fall away after the
  second finding.

**The owner's corrections show where the guidance is wrong, missing or unenforced.**
The intervention ledgers hold 506 corrections. 232 of them rest on judgement that no
written rule supplied, and 150 concern the change's direction. Of the 63 review
findings that cite a written rule, the owner accepted 52 as proposed. So the
corrections show three things:

- **Guidance that is false.** It sends agents to GitHub Issues for intake, which the
  owner does not use. It points them to a glossary that does not exist.
- **Rules the owner applies repeatedly that nobody wrote down.** For example: no
  guard code for a case nobody can describe; amend a rule or comply, never keep a
  private exception; prefer an existing open-source library.
- **Written rules that nothing enforces.** Reviews keep catching the same breaches.

Some of the owner's working preferences also live only in an agent's private memory
between sessions, where no other agent or person sees them.

`design.md` gives the method, every table, the owner's decisions, and the held-out
check.

## What Changes

### Triage accepts uncontested outcomes by default

- **Triage classifies each finding at triage time.** A finding is either discussed or
  accepted by default. The rule uses only facts known before it is presented:
  - the reviewer's severity;
  - the record it came from;
  - the agent's stance and proposed outcome;
  - whether the agent sees an alternative worth weighing, or a fact that would change
    its recommendation;
  - what the fix affects.

  The rule's width is settled in design from the evidence in `design.md`.
- **Discussed findings are presented as today.** One finding per message, in the same
  order, each disposed of only by the owner's word.
- **Default-accepted findings are reported, not asked.** At the end of the round,
  after the discussed findings are disposed of, triage reports every default-accepted
  finding in one table: its label, severity, the finding in one line, and its outcome.
  Each is recorded in the triage file as accepted by default, so the record tells it
  apart from a disposition the owner stated. The fixes are made with the round's other
  accepted fixes.
- **Advancing is the default exit.** When the agent recommends advancing, triage takes
  the advancing exit without asking and reports it beside the table. A recommendation
  of another round is still argued and asked, as today.
- **A triage can finish without asking anything.** This happens when every finding is
  accepted by default and the agent recommends advancing. Today only a triage with
  nothing to dispose of finishes that way.
- **The owner can revisit afterwards.** The owner may reopen any default-accepted
  finding, or the exit, by telling the orchestrating session. A revision is recorded
  in the intervention ledger as revising that finding. How a revision reaches work
  already committed or a step already started is a design question.
- **The batch is measurable.** Default acceptances and their later revisions are
  recorded, so a later guidance review can measure how often the batch is reopened.

### The guidance says what the owner actually does

- **The issue-tracker guidance is corrected.** `AGENTS.md` "Issue tracker" and
  "Triage labels", `docs/agents/issue-tracker.md`, and `docs/agents/triage-labels.md`
  say GitHub Issues handle intake and triage. The owner does not use them. The
  corrected guidance says where deferred work goes instead: the open change that owns
  that area, a new change, or an unowned gap in the index or roadmap. The
  issue-discovery harness's own issue filing (`docs/development/ISSUE_DISCOVERY.md`)
  is a separate tool and is unchanged.
- **Where a defect found during a change is fixed.** The guidance states the owner's
  practice: a defect found during a change is fixed in that change unless it is large
  enough, or vague enough, to merit a change of its own or an unowned gap. Today the
  guidance leans the other way:
  - `openspec/README.md` treats a growing closeout as a scope-creep signal;
  - `change-design` prefers a change that closes out on its own.

  Design settles the wording, because the owner holds this as a preference and wants
  it stated with nuance.
- **The vocabulary guidance points at a glossary that exists.**
  `docs/agents/domain.md` tells agents to use the terms defined in each context's
  `CONTEXT.md`, and to send gaps to a `/domain-modeling` skill. No `CONTEXT.md` and no
  such skill exist. `AGENTS.md` also cites `docs/adr/`, which does not exist. The
  guidance names where the shared vocabulary lives and tells agents to use it. A term
  new to the reader is defined where it first appears and flagged as new, never
  invented silently. Design settles where the vocabulary lives.
- **Three rules the owner applies are written down.**
  - **No guard code for a case nobody can describe.** No refusal, warning, probe or
    hardening for a case that nobody can describe, or that no integration or
    end-to-end test could deliberately trigger.
  - **Amend a rule or comply.** When work conflicts with a written rule, the rule is
    amended first or the work complies. A private exception is never recorded.
  - **Prefer an existing open-source library.** Use one wherever it meets the
    requirements, and build our own only when none does.
- **The owner's working preferences move from agent memory into the repository.** The
  candidates are listed in `design.md`. For example, a recorded note or a new change's
  proposal on the current branch does not breach one change per branch. The owner
  picks which to promote.

### Not changed, by the owner's decision

- **No narrowest-fix rule.** The owner's scope growth comes from deliberately unifying
  the VM and bare-metal domains, which the architecture already favours. A rule
  steering agents toward the narrowest fix would work against that.
- **The rule for stored-state migrations stays as written.** Whether anything is
  deployed is the team's decision, made outside the repository, and a feature branch
  cannot know where its change will run. So no "never deployed" exception can be
  derived from the repository.
- **Promoting principles stays as it is.** The design agent lists candidate
  principles, and the owner picks and clarifies each promotion.

### Out of scope

- **Folding revisits into the workflow graph.** If revisits of default acceptances
  turn out to be frequent, normalizing them into the workflow graph is a later change.
- **The design discussion's presentation.** It already presents consequence and
  convention decisions together for confirmation.
- **Mechanical checks and agent-recommended waivers.** Checks for the written rules
  reviews keep catching, and agents recommending validation waivers, are open
  questions in `design.md`. They join this change only if design takes them in.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `change-workflow`: the owner's touchpoints in triage, the disposition of every
  finding, the intervention ledger's treatment of revised default acceptances, and the
  one-finding-per-turn rule for orchestrated triage.

## Impact

- **Specification.** `openspec/specs/change-workflow/spec.md` changes these
  requirements:
  - "Phases and owner touchpoints";
  - "Triage of every finding";
  - "Intervention ledger";
  - "Discussion steps stay conversations with the owner".

  `openspec/specs/change-workflow/architecture.md` changes its "Triage" section.
- **Skills.**
  - `.agents/skills/change-triage/SKILL.md` changes its presenting, recording and
    exit steps, and its outcome for a defect outside the change's scope.
  - `.agents/skills/change-orchestrate/SKILL.md` changes how it relays the round's
    table and routes a revisit.
  - `.agents/skills/change-design/SKILL.md` changes its preference on splitting a
    change.
- **Guidance.**
  - `AGENTS.md`: "Issue tracker", "Triage labels", "Domain docs", and a section for
    rules that conflict with work.
  - `docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md`.
  - `docs/agents/domain.md`.
  - `docs/agents/change-workflow.md`.
  - `openspec/README.md`.
  - `docs/development/ARCHITECTURE.md`, for the guard-code and library rules.
- **Tooling.** No change to the next-step computation is expected. The advancing exit
  is recorded as it is today. Design confirms this.
- **Coordination.**
  - `layer-engineering-guidance` restructures the guidance by layer. This change lands
    first, and that change inherits these edits in its design review.
  - `extract-change-workflow-repository` moves the skills, the workflow specification
    and the guidance to a separate repository.
  - `add-skill-extension-points` restructures the skills into slots.

  Neither of those two has started, and whichever lands second carries the other's
  edit.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
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
- Where deferred work goes, and where a defect found during a change is fixed:
  `AGENTS.md` and `openspec/README.md`.
- The vocabulary rule and where the vocabulary lives: `docs/agents/domain.md`, and the
  vocabulary's own home as design settles.
- No speculative guard code, and prefer an existing library:
  `docs/development/ARCHITECTURE.md`.
- Amend a rule or comply: `AGENTS.md`.
- Each promoted working preference: the skill or guidance document design assigns.
