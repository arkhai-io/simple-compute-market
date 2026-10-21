---
name: change-design
description: Hold the design discussion for an OpenSpec change with the repository owner — load the full context first, surface every open decision with options, trade-offs, and a recommendation, and record the settled design in the change. Use when a change is `ready for design` or `in design` in openspec/changes/README.md, when the owner says "let's design <change>", or when a dependency landing or review sends a change back to design.
---

# Design discussion for an OpenSpec change

The design phase is where the owner's judgement matters most. They usually
agree with an agent's reading of a problem and often disagree with its
solution, so this skill exists to put the whole problem, and every real choice
in it, in front of them — not to arrive with an answer and defend it.

Design is a discussion, not an action. Edit no file until the owner says the
design is settled, except the index transition (section 2), the intervention
ledger, and a prerequisite's proposal and dependency (both in section 4).

## Running unattended

Run interactively, as most runs are, this section does not apply, and nothing else
in the skill changes. When this skill runs through `scripts/run_change_step.py` —
`make design UNATTENDED=1`, or the orchestrating session — nobody can answer in
the session, and every turn ends with an outcome matching
`.agents/change-outcome.schema.json`, whose `message` the owner reads as written:

- **A stop for the owner is a question.** Wherever this skill says to stop and
  ask, tell, or wait for the owner, end the turn with `question`: `message` says
  what you found, the options, and your recommendation; `awaiting` names what you
  need. The owner's answer resumes this session; carry on from it.
- **A denied call stops the step only when it cannot go on.** Run one command per
  Bash call: a chained command runs only when every command in it is allowed, so
  if a chained command is denied, run its commands one call at a time. If a single
  command or any other tool call is denied, finish every part of the work that does
  not depend on it. If the step cannot complete without that call, end with
  `stopped`, `reason` naming that exact call and why the step needed it, and
  `denials` listing the calls as you saw them; the wrapper replaces them with the
  run's own record. Otherwise go on and end as the step ends: the wrapper records
  the denial on the outcome whatever it is, and the orchestrating session reads it
  before the change moves on. One denied call is not a denied tool: never report
  the tool as not allowed. A call a deny rule refused is forbidden: no other tool
  does it. A call denied because no rule allows it — the harness reports it as
  don't ask mode — may be done instead by a tool this step's rules allow for the
  same work, such as the Edit tool for a shell write or Read or Grep for a shell
  read; name the substitute in your message. Never ask about a denial as a
  question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **Git runs in this checkout.** Run Git in the current checkout, never with `-C`:
  the step already runs in the checkout it reads, and no rule allows `git -C`, since
  a wildcard after `-C` would also span a push.
- **Every reply is a turn.** This step is a discussion: each reply to the owner
  ends its turn with an outcome, the reply in full as its `message` — `question`
  while you wait for the owner's answer or disposition. The orchestrating session
  shows the owner every message and resumes this session with each reply.
- **The end is an outcome.** When the settled design is recorded, committed, and
  pushed (section 6), end with `finished`, `next` naming the design review. A
  design that cannot proceed without another change ends `blocked`, `blocked_on` the prerequisite's
  exact change name, at steps 3 and 4 of "When the design needs another change
  first" (section 4); telling the owner there is that outcome's `message`. Under
  orchestration the release of step 5 is proposed to the owner by the
  orchestrating session, which drops the dependency on their word.

## 1. Load everything before saying anything

Answers given from a partial picture are confidently wrong in exactly the
places that matter, so read all of this first, in full:

- `AGENTS.md` and every document it requires: `docs/development/ARCHITECTURE.md`,
  `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`,
  and `openspec/README.md`.
- `docs/development/ROADMAP.md`, the goal this change serves, and this change's
  row and campaign in `openspec/changes/README.md`.
- Every file in `openspec/changes/<change>/`, including `specs/`,
  `interventions.jsonl`, and any `reviews/` (earlier reviews and their triage
  are design input).
- For every capability the change names or touches: `openspec/specs/<capability>/spec.md`
  and its `architecture.md` companion when one exists.
- The code the design cites, and the code it would change. Read enough of it to
  check every factual claim the design makes about the current system.
- Each change listed in the row's `Depends on`, at least its `proposal.md` and
  `design.md`.

If a dependency gates `design` and has not reached `archived`, stop and tell
the owner: designing now risks designing work the
dependency may make unnecessary. If it is archived on this branch — it landed on
dev, and dev was merged in — the dependency is released on the owner's word
(section 4, "When the design needs another change first").

When the change has been through design before, find what has moved since:
`git log` over the code the design cites, and any dependency that has landed.
A stale design is the most common reason a change returns here.

### Triage waiting reviews first

If the change has a numbered review in `reviews/` with no `NN-<kind>.triage.md`
beside it, or the owner brings a review to this session, triage it with
`change-triage` before opening the discussion below. Its findings that need a
decision become this discussion's decisions, under their finding labels; do not
restate them as separate corrections or questions with a second numbering. Open the
discussion of section 3 only for what the reviews did not already raise, and
continue the same numbering scheme rather than starting a parallel one.

## 2. Mark the change as in design

Set the change's `Status` cell in `openspec/changes/README.md` to `in design`
if it is not already.

## 3. Open the discussion

Open in three parts, in this order.

**Summary.** Summarize the change as it stands: its purpose, its scope and
non-goals, and the design it proposes. Then give your own reading of the
problem — what is wrong or missing today, for whom, and what evidence in the
code shows it. The owner checks your understanding here before reading
anything that rests on it.

**Corrections.** List, numbered, every place the change's account of the code,
the guidance, or its own documents is wrong or contradicts itself, each with
the evidence. A correction is a fact, not a question. If the change misreads
the problem itself, lead with that — a well-designed solution to a misread
problem is the costliest outcome.

**Decisions.** List every open decision, numbered, including ones the
documents treat as settled but the code or a correction reopens. For each:

- **Context.** Recap what the design currently says or assumes on this point,
  and the code, guidance, or correction that bears on it, so the owner can
  decide without rereading the change.
- **Alternatives.** Each option actually available, including doing nothing
  and deferring, with its trade-offs: what it costs, what it constrains later,
  which layer or authority boundary it touches (`ARCHITECTURE.md` vocabulary),
  and what it does to wire, persistence, and deployment compatibility.
- **Recommendation.** Which option you recommend and why, and what would change
  your mind.

When some decisions shape the rest, say which to settle first.

Depth is the point of this phase. Do not compress options you think are wrong
into a sentence, and do not drop a question because you are confident of its
answer; the owner decides what is obvious. Use diagrams where structure is the
question.

### Classify each decision

Mark each decision as one of three kinds, because they need different amounts
of the owner's attention:

- **Judgement** — the options trade real values against each other and no
  written principle or precedent picks one. Present these one at a time, in full.
- **Consequence** — the answer follows from a decision already settled, or from
  a principle in `ARCHITECTURE.md`. Name what it follows from.
- **Convention** — the answer follows from how the nearest existing precedent
  does the same thing (a sibling hint, kit, or configuration key). Cite the
  precedent.

Present consequences and conventions together, once the judgements they depend
on are settled, each still with its context, alternatives, and recommendation,
so the owner can confirm the batch or pull one out for discussion.

Never ask the owner where documentation should live. Name a provisional
permanent destination for each decision in `proposal.md`; planning and review
confirm or move it.

### Do not argue from absence of a caller alone

"No planned change uses it" is not on its own a reason to leave a capability
out. Check `docs/development/ROADMAP.md` and the dependent changes for where
the work is heading, and when you recommend against building something for the
future, ask the owner whether that future is anticipated. The owner often knows
direction the documents do not yet record.

### Show examples for representations

Whenever a decision is about a representation — a declaration, configuration,
or wire format, a schema, where a field sits in a document, or how any of these
evolves — show each alternative as a concrete example document with realistic
values, not a description of one. When the question is evolution, show the
document today and after the anticipated change, and say what an older reader
does with the newer document. Write the examples before you recommend: a format
that reads well in prose often fails visibly once written out, and the owner
judges representations by looking at them.

### Walk every caller through a new interface

When a decision creates or changes an interface — a kit's operations, a
declaration format, a report — list every caller it will have, in this change
and in changes that depend on it, and what each must do with it. Then confirm
each caller can do that through the interface alone. A caller that would have
to interpret the interface's internals means the interface is missing an
operation; say which, and add it to the decision.

## 4. Iterate

Follow the owner's direction. When they disagree, engage with their reasoning
rather than restating yours; when they are right, say so plainly. When a
decision raises a new question, add it to the numbered list. Keep a running
record of what has been decided and what is still open, so either of you can
see the state at any point.

Do not treat a reviewer's or another agent's view as settled; only the owner
settles a design.

When a correction or new fact undercuts a premise the owner reasoned from — for
example, a party they assumed enforces something turns out not to — say so and
ask whether the decision still holds, even if the outcome may survive. A
decision recorded on a false premise carries that premise into its permanent
rationale.

When the owner states a principle that settles a decision, apply it to the
remaining open decisions before presenting them, and say where it applied.
Principles the owner states that no document records are candidates for
`ARCHITECTURE.md`; list them for the owner when the design is settled.

When the owner's input changes or reverses your recommendation, append one line
to the change's `interventions.jsonl` with the decision as the finding:

```json
{"review": "design", "finding": "D3", "lens": "direction", "basis": "judgement", "severity": null, "agent_position": "<your recommendation>", "owner_disposition": "<what the owner decided and why>", "summary": "<one line>"}
```

Do not log decisions the owner accepted as recommended. This is the one file
edit allowed before the design is settled, besides the index transition and a
prerequisite's proposal, below.

### When the design needs another change first

When the discussion shows the design cannot proceed until another change lands,
that change is a prerequisite, and its workflow is the owner's to start. One change
is worked per branch, so the prerequisite's proposal reaches this branch only
through dev, never written here:

1. With the owner, shape the prerequisite: its requirements and an initial
   `proposal.md` only. Its design is its own workflow's, started by the owner.
2. Write it in a worktree on a new branch from dev, never on this branch:
   `git worktree add ../<prerequisite>-proposal -b propose-<prerequisite> dev`,
   then, in that worktree, its directory under `openspec/changes/` and its
   `ready for design` row in that worktree's `openspec/changes/README.md`. Run
   `make -C ../<prerequisite>-proposal check-change-index`.
3. Tell the owner the proposal is ready: they commit it in that worktree and open
   its pull request. Leave this change `in design`; do not record the dependency
   yet, since the index check refuses a `Depends on` entry naming a change this
   branch does not list. The design halts here.
4. Once the proposal has merged to dev and dev has been merged into this branch,
   record the dependency: add the prerequisite to this change's `Depends on`
   gating `design` (`` `<prerequisite>` (design) ``), name it in `Notes`, keep the
   status `in design`, and run `make check-change-index`. `blocked in design` is
   for reasons that are not another change; the dependency itself holds design,
   through section 1's entry check, and the design halts again until it lands.
5. Once the prerequisite is archived and dev is merged in again, the index check
   refuses this change's dependency on an archived change. On the owner's word,
   drop only that dependency, leaving the status `in design`, run
   `make check-change-index`, and resume the discussion.

## 5. Check the whole before recording

When every decision is settled, and before writing anything:

- **Re-read every decision's rationale against the final set of decisions and
  principles.** A rationale written early can rest on something a later
  decision removed. Restate any that no longer holds, and tell the owner when
  the outcome itself is in doubt.
- **Walk every caller through each new interface once more**, against the
  settled design as a whole, as in section 3.
- **Compare the scope with the original proposal.** List what was added, which
  decisions added it, and whether any of it gives the change a new prerequisite
  or a second domain, subsystem, or acceptance boundary. Ask the owner
  explicitly whether any of it should be split into its own change. A change
  that can close out on its own is preferred to one waiting on another.
- **List the principles the owner stated** that no permanent document records,
  for promotion to `ARCHITECTURE.md`.
- **Settle the implementation cadence** with the owner, as a decision like any
  other: how many rounds implement the work, what each round covers before its
  review, and how many sessions implement each — in terms of the work, since the
  plan's sections do not exist yet ("one round, one session"; "round 1: the
  contract changes; round 2: the handlers and the migration"). The order of the
  work can bear on the design, and nothing about it is asked once the owner has
  moved on: planning orders its sections by it and maps it onto them. Recommend a
  cadence from the work's natural slices and its risk; a small change is usually
  one round of everything before closeout.

Present these results and resolve what they raise before recording.

## 6. Record the settled design

Only when the owner says the design is settled:

- Record each decision in `design.md` under `## Decisions`, with its rationale
  and the alternatives rejected and why. Describe the design as it will be,
  not the conversation that produced it. Record the implementation cadence there
  too, in terms of the work, as the change's implementation cadence.
- Keep under `## Open Questions` only what is genuinely deferred, each with what
  would trigger revisiting it. A question may not stay open while a task
  prescribes its answer (`openspec/README.md#open-questions-and-prescribed-tasks`).
- Amend `proposal.md` when scope, non-goals, capabilities, or impact moved, and
  keep its `## Permanent documentation impact` and `### Knowledge to promote`
  naming the permanent destination of every material decision.
- Amend the delta specs in `specs/` so every accepted behavior is a requirement
  with at least one WHEN/THEN scenario.
- Run `make check-change CHANGE=<change>`, which runs the strict OpenSpec
  validation and the change's citations check among the repository's closing
  checks, and report the result. A citation of a file the change itself will
  create is expected; any other is a defect.
- Commit the recorded design as one commit — the change's documents, the index
  row, and the ledger lines this step wrote — whose message names the change and
  says its design is settled, so the design review reads a committed design. Then
  push it with `make push-branch`, the guarded push of exactly `HEAD`; if it
  refuses, stop and report its reasons.

Do not write or amend `tasks.md`: planning is a separate phase and starts only
once the design review's triage records that the change advances.

## 7. Hand off to design review

The design phase ends with a design review, not with this skill. Tell the owner
the design is ready for review and leave the status `in design`. Its triage records
under `## Next` whether the change advances or another design review runs; when it
advances, the triage sets `ready for planning`, and planning follows without
another question to the owner.
