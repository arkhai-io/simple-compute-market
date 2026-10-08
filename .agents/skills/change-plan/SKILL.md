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

Planning has three outcomes: the owner accepts the plan, the owner redirects it, or
planning returns the change to design.

## 1. Check that planning may start

Read the evidence from the files, even if this session held the design discussion:
the session's memory of a gate can be out of date, and reviews and triage may have
happened elsewhere. Read the change's row in `openspec/changes/README.md` — status,
`Depends on`, notes — and the change's latest design review and its triage in
`reviews/`. Then confirm:

- The change's status is `ready for planning` or `in planning`.
- The latest design review's triage records its gate as passed, or the owner's
  waiver of that review is recorded (section 3).
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

If planning exposes a question the design did not answer, it is a design decision,
and no review has seen it. Planning stops: never settle it inside a task, and never
plan on an answer the design review did not cover.

1. Tell the owner what planning found and why it stopped, and set the change's
   status back to `in design`.
2. Settle the question as `change-design` settles a decision, and record it in
   `design.md`.
3. Ask the owner whether the change needs another design review for it, or whether
   they waive the review. A waiver is the owner's call. Record it in the latest
   design triage's gate and as a ledger entry with `"review": "plan"`, the decision
   as `finding`, lens `readiness`, basis `judgement`, and a null severity, stating
   what was waived and why.
4. With the review passed or waived, set the status to `ready for planning` and
   resume planning.

## 4. Write the plan

**Preserve history.** Never delete a checked task, rewrite what it says was done,
or change its completion state. When the reviewed design changes what follows from
a completed task, amend it with a correction note, or append a task that carries
the correction. An unchecked task the reviewed design superseded may be replaced;
say at the top of the replaced section that it was replanned against the reviewed
design.

**Sections are slices.** Each section:

- opens with one line on what it delivers and the decisions (`D<n>`) and
  requirements it implements;
- names the files and packages it touches;
- is sized to be implemented in one fresh session without the session compacting:
  a section that crosses several package layers, or needs more tasks than one
  session can hold in mind with the guidance documents, is split;
- ends at a verification point — the focused suites that prove it, each named with
  its level as `docs/development/TESTING.md` defines them (unit, library
  integration, application integration through the typed client, system), at the
  lowest level that can prove the behavior; `make test`; and the packaging check
  when it changes a dependency or lock. A section whose title promises a behavior
  of the running application — publication, a write refused — includes at least one
  application-integration case for it, not only lower-level evidence of its parts;
- states when it owes the Helm checks: when it touches `helm/`, an image build
  input, or a service's configuration surface.

**Order by real dependencies.** Lower layers before the layers composing them —
foundation kit before kit before domain before composition root — and focused
behavioral verification before documentation work, per the task rules in
`openspec/config.yaml`.

**Every task is traceable.** Each names what it answers to — a design decision, a
delta requirement, or a repository obligation such as the verification, packaging,
promotion, and closeout work `openspec/README.md` and `openspec/config.yaml` require,
cited — and the evidence that proves it. A feature task with nothing to trace to is
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
  task, and every task maps back to a decision, a requirement, or a cited
  repository obligation;
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
