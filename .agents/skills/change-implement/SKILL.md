---
name: change-implement
description: Implement one section of an OpenSpec change's tasks.md in a fresh session — load the guidance, the change, and that section; implement and verify it; check its diff for compliance in a fresh context; record a handoff; and commit the section for review. Use when a change is `ready for implementation` or `in implementation`, when the owner says "implement <change>" or "implement section N of <change>", or to continue a change's next section.
---

# Implementing one section of an OpenSpec change

One session implements one `tasks.md` section, then stops. Compliance with the
repository's guidance degrades as a session grows and collapses after it compacts,
so the fresh session is the unit of work: everything this session needs is in the
change's files, and everything the next session needs goes back into them before
this one ends.

## 1. Check that this section may start

- **Branch.** The checked-out branch is the one this change is worked on. Several
  changes are often in flight in one checkout; if the branch does not carry this
  change's latest planning commits, or its name belongs to another change, stop and
  ask the owner.
- **Status.** The change's row in `openspec/changes/README.md` is
  `ready for implementation` or `in implementation`, and no dependency in its
  `Depends on` gates implementation while unlanded.
- **Worktree.** It is clean, or holds only changes the owner confirms are this
  section's.
- **Section.** The owner names it, or it is the first section with unchecked tasks.
  An earlier section with unchecked tasks is unfinished: that is the section, unless
  the owner says otherwise.

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
- Mark the task `[x]` when its evidence passes, with a short note: the suite and its
  result, and anything that differed from the plan.

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
the owner the section was sized wrong. A section that cannot finish in one session
is a planning defect, not a reason to let the session compact.

## 5. Check before committing

Run each of these, and fix what it reports:

- `make lock` when the section changed a dependency, then `make check-packaging`;
- the focused suites the section's verification point names, and every suite that
  covers code the section changed;
- `make check-comment-hygiene`;
- `make check-doc-citations CHANGE=<change>`;
- `make check-agent-skills` if the section touched `.agents/`, `.claude/`, or
  `.codex/`.

Then have the section's diff checked in a fresh context. Start a subagent that has
seen none of this session, and give it only: the change name, the section, the
command to see the diff (`git diff` against the section's starting commit, plus any
untracked files), and this instruction — read `AGENTS.md` and every document it
requires, plus the specs and architecture companions of the capabilities the diff
touches; then report every place the diff breaks that guidance — layering,
comments, test level, documentation placement, packaging — with file and line, and
say plainly when it finds none. Fix what it finds that is right, and say what you
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

## 8. Report

Tell the owner:

- what the section delivered, and the tasks checked;
- the evidence: each check and suite with its result;
- what the fresh-context check found, what was fixed, and what was declined;
- the handoff recorded;
- what comes next — the pre-review validation of this commit, then an
  implementation review, and the next section in a new session.
