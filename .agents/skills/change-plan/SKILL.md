---
name: change-plan
description: Write or amend the implementation plan — tasks.md — for an OpenSpec change whose design has passed its review, sized so each section is implemented in one fresh session and ending with the closeout task. Use when a change is `ready for planning` or `in planning` in openspec/changes/README.md, or when the owner says "plan <change>" or "proceed to planning", typically continuing the design session.
---

# Planning an OpenSpec change

Design settled what the change does. Planning settles how it is delivered: the
sections, their order, the files each decision touches, the evidence each section
owes, where each decision is documented permanently, and the closeout. Planning
makes no design decisions.

This skill usually runs in the session that held the design discussion, because
that context makes a better plan. But the plan is read by implementation sessions
that start fresh and see only the files. Everything the plan relies on must be in
the change's files before a task depends on it.

## 1. Check that planning may start

- The change's status is `ready for planning` or `in planning`.
- The latest design review's triage records its gate as passed.
- No dependency in the row's `Depends on` gates `design` or `planning` and is
  unlanded. A dependency gating implementation does not stop planning; the plan
  notes it.

If any of these fails, stop and tell the owner why.

Set the change's `Status` to `in planning`.

## 2. Load what the plan needs

If this session did not hold the design discussion, read `AGENTS.md` and every
document it requires first. Then read, whether or not you have seen it before —
the files are what the implementer will see:

- the change's `proposal.md`, `design.md`, `specs/`, and current `tasks.md`;
- `openspec/README.md#plan-closeout-requirements`, and `openspec/config.yaml`'s
  rules for tasks;
- `openspec instructions tasks --change <change>` for the tasks template;
- the permanent spec and architecture companion of every capability the change
  touches, and `openspec/specs/README.md`;
- the code each decision changes: enough to name the files, the package
  boundaries, and the existing tests a section extends.

## 3. Record the conversation before planning from it

Read `design.md` as an implementer would. Wherever a task will depend on something
the discussion settled but the file does not say — a rationale, an example, a
rejected alternative, a constraint the owner stated — write it into `design.md`
first, as part of the decision it belongs to. This is recording, not deciding.

If planning exposes a question the design did not answer, it is a design decision:
stop, present it as `change-design` presents a decision, and record the owner's
answer in `design.md` before planning on it. Never settle it inside a task.

## 4. Write the plan

**Preserve history.** A checked task stays exactly as written, notes included. An
unchecked task the reviewed design superseded may be replaced; say at the top of
the replaced section that it was replanned against the reviewed design.

**Sections are slices.** Each section:

- opens with one line on what it delivers and the decisions (`D<n>`) and
  requirements it implements;
- names the files and packages it touches;
- is sized to be implemented in one fresh session without the session compacting:
  a section that crosses several package layers, or needs more tasks than one
  session can hold in mind with the guidance documents, is split;
- ends at a verification point — the focused suites that prove it, at the lowest
  level that can (`docs/development/TESTING.md`), and the packaging check when it
  changes a dependency or lock;
- states when it owes the Helm checks: when it touches `helm/`, an image build
  input, or a service's configuration surface.

**Order by real dependencies.** Lower layers before the layers composing them —
foundation kit before kit before domain before composition root — and focused
behavioral verification before documentation work, per the task rules in
`openspec/config.yaml`.

**Every task is traceable.** Each names the decision or delta requirement it
implements and the evidence that proves it. A task with nothing to trace to is
either missing from the design or not part of this change.

**Name the permanent destinations.** For every entry under the proposal's
`Knowledge to promote`, confirm or correct its destination and name it exactly —
file and heading — including `openspec/specs/README.md` for a new capability or
companion, and `docs/development/ARCHITECTURE.md` where the design says so.
Provisional destinations the design delegated to planning are settled here; tell
the owner which you moved and why.

**End with the closeout task**, its ten parts from
`openspec/README.md#plan-closeout-requirements`, each made specific to this change:
the roadmap goal and gap row it closes, its index row and any dependents the
dependency-landing step must update, the end-to-end scenarios that exercise it,
and the design-promotion record.

## 5. Check the plan

Before presenting it:

- every decision in `design.md` and every delta requirement maps to at least one
  task, and every task maps back;
- no open question has its answer prescribed by a task
  (`openspec/README.md#open-questions-and-prescribed-tasks`);
- every section has a verification point and a size one session can hold;
- `openspec validate <change> --strict` passes, and
  `make check-doc-citations CHANGE=<change>` reports only files the change will
  create.

## 6. Present the plan

Do not paste `tasks.md`. Show:

- each section in one line: what it delivers, the decisions it implements, its
  verification, and anything that makes it large or risky;
- the decision-to-section map, so the owner can see nothing was dropped;
- what you recorded into `design.md` in step 3;
- the permanent destinations you settled or moved;
- dependencies that gate implementation.

The owner accepts the plan or redirects it. When the owner changes or reverses a
recommendation of yours — a split, an order, a destination — append a line to the
change's `interventions.jsonl` with `"review": "plan"`, the affected section as
`finding` (`§3`), lens `scope` or `architecture`, basis `judgement`, and a null
severity, and say that you did.

## 7. Hand off

When the owner accepts the plan, set the change's `Status` to
`ready for implementation`. Planning has no review gate of its own: its sizing and
closeout are examined by the first implementation review.

Implementation starts in a new session, one section per session, with
`change-implement`.
