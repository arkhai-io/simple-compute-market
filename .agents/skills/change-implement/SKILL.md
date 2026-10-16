---
name: change-implement
description: Implement the sections of an OpenSpec change's tasks.md a session is given, in a fresh session — load the guidance, the change, and each section; implement and verify it; check its diff for compliance in a fresh context; record a handoff; and commit each section on its own for review. Use when a change is `ready for implementation` or `in implementation`, when the owner says "implement <change>" or "implement section N of <change>", or to continue a change's next section.
---

# Implementing the sections of an OpenSpec change

The section is the unit of work: each is implemented, checked, handed off, and
committed on its own. A session implements the sections it was given, in order:
the owner decides, before implementation starts, how many sections a session
implements and how many are reviewed together. Compliance with the repository's
guidance degrades as a session grows and collapses after it compacts, which is the
owner's to weigh in giving a session several sections; say so when a session grows
large. Either way, everything the next session needs goes back into the change's
files before a section is committed.

## Running unattended

Run interactively, as most runs are, this section does not apply, and nothing else
in the skill changes. When this skill runs through `scripts/run_change_step.py` —
`make implement UNATTENDED=1`, or the orchestrating session — nobody can answer in
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
  the tool as not allowed. Never do by another tool what a denied call would have
  done, and never ask about a denial as a question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **The end is an outcome.** When the sections you were given are committed,
  end with `finished`, `next` naming what the round needs next. When the plan is
  wrong (step 4), commit nothing from the section and end with `returned`,
  `return_to` `design` or `planning`, and `evidence` naming the section's notes,
  leaving the status as it is: the owner confirms the return, and the step started
  then sets it. An external input the change cannot supply, and a section far
  larger than its plan once its handoff is recorded (step 4), are each a
  `question`.

## 1. Check that this section may start

- **Branch.** The checked-out branch is the one this change is worked on. Several
  changes are often in flight in one checkout; if the branch does not carry this
  change's latest planning commits, or its name belongs to another change, stop and
  ask the owner.
- **Status.** The change's row in `openspec/changes/README.md` is
  `ready for implementation` or `in implementation`, and no dependency in its
  `Depends on` gates implementation while unlanded. A change `in closeout` whose
  return to implementation the owner has confirmed is set `in implementation`.
- **Worktree.** It is clean, or holds only changes the owner confirms are this
  section's. `make round-view-closed` passes: while the owner reads a round
  (`make round-view`), the branch points at the round's base and its changes are
  uncommitted, so committing a section then would squash the round into it.
- **Section.** The owner names it, or it is the first section with unchecked tasks.
  An earlier section with unchecked tasks is unfinished: that is the section, unless
  the owner says otherwise. When the owner names a range ("sections 1-3"), work them
  in order, one at a time, through every step below.

If any check fails, stop and say why.

## 2. Load the context

Read in full, even if you believe you know it:

- `AGENTS.md` and every document it requires: `docs/development/ARCHITECTURE.md`,
  `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, and
  `openspec/README.md`;
- the change's `proposal.md`, `design.md`, `specs/`, and all of `tasks.md` —
  especially earlier sections' notes, which carry the previous session's handoff;
- the triage of the latest implementation review in `reviews/`, if any: accepted
  findings may have become tasks in this section;
- the permanent spec and architecture companion of every capability the section
  touches;
- the code the section changes, and the tests it extends.

If the session compacts while working, read these again before continuing.

When this is the change's first section, set its status to `in implementation`.

## 3. Implement the section

Work through the section's tasks in order. For each:

- Make the change the task and its cited decision call for, and no more. Work that
  belongs to a later section stays there.
- Prove it at the lowest test level that can (`TESTING.md`), through the seams and
  injected dependencies the code already offers rather than brute-force patching.
- Respect the dependency layers in `ARCHITECTURE.md`; `TYPE_CHECKING` imports count.
  Internal dependencies come from wheels and locks through `scripts/uv_project.py`,
  never editable sibling paths.
- Comments describe the current system: an invariant, a constraint, a reason a
  simpler implementation is wrong. Never a change name, a task number, a review, or
  what the code used to be (`AGENTS.md`, "Python comments and docstrings").
- Imports the section adds go at module level, unless one has a reason to stay
  local that you verified by attempting the move — a circular import that fails, or
  a deliberate lazy load — and recorded beside it
  (`openspec/README.md#plan-closeout-requirements`, part 2). Closeout only confirms
  comments and imports; it never edits code, so this is where they are done.
- Mark the task `[x]` when its evidence passes, with a short note: each suite, its
  level as `TESTING.md` defines them — unit, library integration (a real component
  against real storage, no application), application integration (the running
  application through its typed client), or system — and its result, and anything
  that differed from the plan. Name a suite by what it actually exercises: a test
  that calls the reconciler directly is not application integration, and a test that
  shows a listing becomes a candidate to close does not show it closes.
- Before the section's last task is checked, confirm or correct the end-to-end
  scenarios its plan says cover it, in the section's notes: the pytest markers in
  `e2e-tests/` that exercise its behaviour once deployed, including any the section
  added, or that none does. Validation reads this to say whether the pipeline's
  result is evidence for the section.

Never delete or rewrite a completed task; amend it with a correction note when
something it established changes.

## 4. Stop cleanly when the plan is wrong

If the code shows the section's premise is wrong, or a task needs a design decision
the design does not make, do not guess and do not work around it:

1. Commit nothing from the section.
2. Record in the section's notes what you found, with the evidence, and what you
   had and had not done.
3. Tell the owner, and recommend the way back: a design question returns the change
   to design (`change-design`); a plan defect goes to planning (`change-plan`); an
   external input the change cannot supply makes it `blocked in implementation`.

If the section turns out far larger than its plan — many more files or layers than
it names — stop at a coherent, verified point instead, record the handoff, and tell
the owner the section was sized wrong. A section far larger than its plan is a
planning defect, not a reason to let the session compact.

## 5. Check before committing

Run each of these, and fix what it reports:

- `make lock` when the section changed a dependency, then `make check-packaging`;
- the focused suites the section's verification point names, and every suite that
  covers code the section changed;
- `make test`, whatever the section touched: a change to a shared package, a
  dependency, or a lock reaches projects no focused suite covers, and the full
  suite is cheap beside a review round spent finding that;
- `make check-comment-hygiene`;
- `make check-doc-citations CHANGE=<change>`. Before closeout it may report only
  the permanent documents the change's tasks create at closeout — the promotion
  destinations its plan names; list those in the report and fix anything else.
  At closeout the check passes with nothing reported;
- `make check-agent-skills` if the section touched `.agents/`, `.claude/`, or
  `.codex/`.

Then have the section's diff checked in a fresh context. Start a subagent that has
seen none of this session, and give it only: the change name, the section, the
command to see the diff (`git diff` against the section's starting commit, plus any
untracked files), and this instruction — read `AGENTS.md` and every document it
requires, plus the specs and architecture companions of the capabilities the diff
touches; then report every place the diff breaks that guidance — layering,
comments, test level, documentation placement, packaging — with file and line, and
every evidence claim in the section's task notes that overstates what its tests
exercise, and say plainly when it finds none. Fix what it finds that is right, and say what you
declined and why. Run it again after substantial fixes.

## 6. Record the handoff

In the section's notes in `tasks.md`, record whatever the next session would
otherwise have to rediscover: a seam that resisted, an approach that failed and
why, a surprise in the code, a follow-up the section deliberately left. Closeout's
narrative compression trims these later; until then they are how sessions talk to
each other.

## 7. Commit the section

Commit the section's work, `tasks.md` included, as one commit, unreviewed: review
findings land as later commits. The message names the change and the section and
says what it delivers. Do not push; pushing belongs to validation.

## 8. Continue or stop

When sections you were given remain, go on to the next one, from step 1, without
waiting — unless this section stopped for a plan or design problem, or its checks
could not be made to pass, which ends the sections. Before starting the next
section, re-read the section and its earlier sections' notes; and if the session
has compacted, re-read every document in step 2.

When the sections you were given are committed, stop and report. Say how large the
session has grown if you can tell; when it is large, recommend that the next
sections start in a fresh session.

## 9. Report

When the session stops, tell the owner, for each section implemented:

- what the section delivered, and the tasks checked;
- the evidence: each check and suite with its result;
- what the fresh-context check found, what was fixed, and what was declined;
- the handoff recorded;
- what comes next — the owner reads the commits since the last round as
  uncommitted changes (`make round-view CHANGE=<change>`, which first pushes them
  and starts the end-to-end pipeline) and closes the view (`make round-done`);
  then validation (`make validate CHANGE=<change>`) and one implementation review
  (`make review CHANGE=<change> KIND=implementation`), run side by side; then the
  round triaged in a fresh session
  (`make triage CHANGE=<change>`), which fixes what the owner accepts; then the
  next section.
