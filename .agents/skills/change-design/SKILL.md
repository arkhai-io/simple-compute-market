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
design is settled, except the one index transition below.

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

If a dependency gates `design` and has not reached `ready for archival` or
`archived`, stop and tell the owner: designing now risks designing work the
dependency may make unnecessary.

When the change has been through design before, find what has moved since:
`git log` over the code the design cites, and any dependency that has landed.
A stale design is the most common reason a change returns here.

## 2. Mark the change as in design

Set the change's `Status` cell in `openspec/changes/README.md` to `in design`
if it is not already. This is the only edit before the design is settled.

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

## 4. Iterate

Follow the owner's direction. When they disagree, engage with their reasoning
rather than restating yours; when they are right, say so plainly. When a
decision raises a new question, add it to the numbered list. Keep a running
record of what has been decided and what is still open, so either of you can
see the state at any point.

Do not treat a reviewer's or another agent's view as settled; only the owner
settles a design.

## 5. Record the settled design

Only when the owner says the design is settled:

- Record each decision in `design.md` under `## Decisions`, with its rationale
  and the alternatives rejected and why. Describe the design as it will be,
  not the conversation that produced it.
- Keep under `## Open Questions` only what is genuinely deferred, each with what
  would trigger revisiting it. A question may not stay open while a task
  prescribes its answer (`openspec/README.md#open-questions-and-prescribed-tasks`).
- Amend `proposal.md` when scope, non-goals, capabilities, or impact moved, and
  keep its `## Permanent documentation impact` and `### Knowledge to promote`
  naming the permanent destination of every material decision.
- Amend the delta specs in `specs/` so every accepted behavior is a requirement
  with at least one WHEN/THEN scenario.
- Run `openspec validate <change> --strict` and
  `make check-doc-citations CHANGE=<change>`, and report the results. A
  citation of a file the change itself will create is expected; any other is a
  defect.

Do not write or amend `tasks.md`: planning is a separate phase and starts only
after the design review's gate is passed.

## 6. Hand off to design review

The design phase ends with a design review, not with this skill. Tell the owner
the design is ready for review and leave the status `in design`; triage of that
review moves the change to `ready for planning` once the owner passes its gate.
