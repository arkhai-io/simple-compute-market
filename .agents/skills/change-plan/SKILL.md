---
name: change-plan
description: Write or amend the implementation plan — tasks.md — for an OpenSpec change whose design has passed its review, its sections coherent, verifiable slices, and ending with the closeout task. Use when a change is `ready for planning` or `in planning` in openspec/changes/README.md, or when the owner says "plan <change>" or "proceed to planning", typically continuing the design session.
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

## Running unattended

Run interactively, as most runs are, this section does not apply, and nothing else
in the skill changes. When this skill runs through `scripts/run_change_step.py` —
`make plan UNATTENDED=1`, or the orchestrating session — nobody can answer in
the session, and every turn ends with an outcome matching
`.agents/change-outcome.schema.json`, whose `message` the owner reads as written:

- **A stop for the owner is a question.** Wherever this skill says to stop and
  ask, tell, or wait for the owner, end the turn with `question`: `message` says
  what you found, the options, and your recommendation; `awaiting` names what you
  need. The owner's answer resumes this session; carry on from it.
- **A denied tool stops the step.** Run one command per Bash call: a chained
  command runs only when every command in it is allowed, so if a chained command
  is denied, run its commands one call at a time. If a single command or any other
  tool call is denied, finish every part of the work that does not depend on it,
  then end with `stopped`, `reason` naming that exact call and why the step needed
  it, and `denials` listing the calls as you saw them; the wrapper replaces them
  with the run's own record. One denied call is not a denied tool: never report
  the tool as not allowed. Never do by another tool what a denied call would have
  done, and never ask about a denial as a question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **Every reply is a turn.** This step is a discussion: each reply to the owner
  ends its turn with an outcome, the reply in full as its `message` — `question`
  while you wait for the owner's answer or disposition. The orchestrating session
  shows the owner every message and resumes this session with each reply.
- **The end is an outcome.** Presenting the plan (section 6) is a `question`
  awaiting the owner's acceptance. Once the owner accepts and the status is set
  (section 7), end with `finished`, `next` naming the agreement of the first
  implementation round.
- **A return to design is proposed, not made.** When planning exposes a design
  question (section 3), end with `returned`, `return_to` `design`, and `evidence`
  naming where you recorded what planning found; leave the status as it is. The
  owner confirms the return, and the design step then sets the status.

## 1. Check that planning may start

Read the evidence from the files, even if this session held the design discussion:
the session's memory of a gate can be out of date, and reviews and triage may have
happened elsewhere. Read the change's row in `openspec/changes/README.md` — status,
`Depends on`, notes — and the change's latest design review and its triage in
`reviews/`. Then confirm:

- The change's status is `ready for planning` or `in planning`, or the owner has
  confirmed implementation's return of the change to planning, in which case set
  it to `in planning`.
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

1. Tell the owner what planning found and why it stopped. Interactively, set the
   change's status back to `in design` and go on with steps 2–4 in this session.
   Unattended, end the turn `returned` instead, as "Running unattended" says, and
   leave the status: the owner confirms the return, and the design step sets it.
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
- is a coherent slice that can be verified, sized by what it changes and what
  proves it: a section that crosses several package layers, or whose tasks one
  verification point cannot prove together, is split. The plan says nothing of
  sessions or rounds: how many sections a session implements, and how many are
  reviewed together, the owner decides before implementation starts, whether or
  not a coding harness implements them;
- ends at a verification point — the focused suites that prove it, each named with
  its level as `docs/development/TESTING.md` defines them (unit, library
  integration, application integration through the typed client, system), at the
  lowest level that can prove the behavior; `make test`; and the packaging check
  when it changes a dependency or lock. A section whose title promises a behavior
  of the running application — publication, a write refused — includes at least one
  application-integration case for it, not only lower-level evidence of its parts;
- names the end-to-end scenarios (pytest markers in `e2e-tests/`) that exercise
  the section's behaviour once deployed, or says that none does and whether one is
  owed. Validation runs the Helm checks and the pipeline on every commit; it reads
  this list to report whether the pipeline's result is evidence for the section.

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

**End with the closeout task**, its eleven parts from
`openspec/README.md#plan-closeout-requirements` in that order, each made specific
to this change:
the roadmap goal and gap row it closes, its index row, the end-to-end scenarios
that exercise it, the permanent documents it promotes, and the archive's merge or
`--skip-specs`. Dependents are released at archive cleanup, not by a closeout
task.

## 5. Check the plan

Before presenting it:

- every decision in `design.md` and every delta requirement maps to at least one
  task, and every task maps back to a decision, a requirement, or a cited
  repository obligation;
- no open question has its answer prescribed by a task
  (`openspec/README.md#open-questions-and-prescribed-tasks`);
- every section has a verification point, its covering end-to-end scenarios or a
  statement that none covers it, and a size its verification point can prove;
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

Implementation starts in a new session with `change-implement`, in rounds of
sections the owner agrees before it starts.
