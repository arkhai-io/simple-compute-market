---
name: change-implement
description: Implement the sections of an OpenSpec change's tasks.md a session is given, in a fresh session or one the owner names to continue — load the guidance, the change, and each section; implement and verify it; check its diff for compliance in a fresh context; record a handoff; and commit each section on its own for review; or, given a merge's conflicted files and no sections, resolve them and conclude the merge. Use when a change is `ready for implementation` or `in implementation`, when the owner says "implement <change>" or "implement section N of <change>", or to continue a change's next section.
---

# Implementing the sections of an OpenSpec change

The section is the unit of work: each is implemented, checked, handed off, and
committed on its own. A session implements the sections it was given, in order:
how many sections a session implements and how many are reviewed together is the
change's implementation cadence, settled in its design and mapped onto the
sections by its plan. Compliance with the repository's guidance degrades as a
session grows and collapses after it compacts, which is the owner's to weigh in
settling the cadence; say so when a session grows large. Either way, everything
the next session needs goes back into the change's files before a section is
committed.

The owner may send further sections, or a fix to edits you made, to a session that
has already finished. Treat that as a new invocation: read the change's files again
where they may have changed — `tasks.md`, the design, the reviews' triage — as the
branch may have moved, and follow every step below for the new work.

## Running unattended

Run interactively, as most runs are, this section does not apply but for the
outcome it describes, which an interactive run records itself ("Running
interactively"); nothing else in the skill changes.
When this skill runs through `change-workflow start --unattended` —
`make implement UNATTENDED=1`, or the orchestrating session — nobody can answer in
the session, and every turn ends with an outcome matching
`.agents/change-outcome.schema.json`, whose `message` the owner reads as written:

- **A stop for the owner is a question.** Wherever this skill says to stop and
  ask, tell, or wait for the owner, end the turn with `question`: `message` says
  what you found, the options, and your recommendation; `awaiting` names what you
  need. The owner's answer resumes this session; carry on from it.
- **The step runs in a sandbox scoped to it.** It writes only the paths this step
  may change: a write that fails as a read-only file system, or as a device or
  resource busy, is outside its scope. If the step cannot go on without that write,
  end with `stopped`, `reason` naming the path and why the step needed it;
  otherwise go on within the scope, and say in your message what you did instead.
  A call the harness denies is the same. The wrapper records every refusal and
  denial on the run's line whatever you say, and the orchestrating session reads
  them before the change moves on; never ask about either as a question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **A project's tests and bring-up, by role.** Run one project's tests as the
  repository's guidance names its test entry point, never a virtual environment's
  runner directly. A section's local bring-up — a service's migrations, its image
  run once, or a stack under a project name of the change's own, so it never
  touches another change's — is taken down before the turn ends. Remove a tracked
  file with `git rm`, which Git can restore. A subagent you start runs in the same
  sandbox, and its prompt says so.
- **A turn's end is its outcome.** Never end a turn with work still running: the
  wrapper logs that turn's report as the run's end, and what the work later finds
  reaches nobody. Run the fresh-context check's subagent in the foreground, never
  with `run_in_background`. Wait for a background command inside one Bash call,
  with `change-workflow wait <output-file> '<pattern>'` matching the line it
  prints when it ends, repeated when the wait gives up; when it says the command
  ended with no line matching, read the output rather than waiting again — never
  with `tail -f`, which hangs when that line is the last, Monitor, a wake-up, or a
  shell loop.
- **The end is an outcome.** When the sections you were given are committed and
  pushed, end with `finished`, `next` naming implementation's exit, the round's
  triage, `{"step": "triage", "kind": "implementation"}`, and what the round needs
  next in `message`: the computation reads the round's join from its records and
  names its next session, the owner's reading, validation and the review, or the
  triage. A merge's conflicts resolved, committed, and pushed end `finished` too
  ("Resolving a merge's conflicts"). When the plan is wrong (step 4), commit and
  push the section's work in progress, no task checked, and end with `returned`,
  `next` the step it returns to, `{"step": "design"}` or `{"step": "plan"}`, and
  `evidence` naming the section's notes, leaving the status as it is: the owner
  confirms the return, and the step started then sets it. An external input the
  change cannot supply, and a section far larger than its plan once its handoff is
  recorded (step 4), are each a `question`. A `stopped` run commits nothing: its
  work waits uncommitted for the resumed session.

## Running interactively

Run in an interactive session — `make implement` without `UNATTENDED=1`, or the
slash command — no wrapper records the run, so its last act records the outcome
it would end with unattended, as "Running unattended" gives it:

```text
change-workflow record <change> implement --outcome '<the outcome, as JSON>'
```

`record` checks the outcome against `.agents/change-outcome.schema.json` and
appends it to the change's workflow log with the session's id, `HEAD`, and
`interactive: true`, and the next-step computation routes on it as on an
unattended run's. It reads the session's id from `CLAUDE_CODE_SESSION_ID`, which
`printenv CLAUDE_CODE_SESSION_ID` shows; where the variable is unset it refuses,
and `--session <id>` gives the id. Record the outcome the session ends with —
`finished` or `returned` — never a question or a stop, which the owner, present,
settles in the session: a recorded stop would wait for a resume only the wrapper
makes. When `record` refuses, correct what it names and run it again. A
session closed before it records loses its report, and any return it would have
proposed: the computation reads a round's progress from the task list and the
records, not from its outcome, and names what they say comes next.

The round's join reads the round from its line in the log, which the orchestrating
session writes as a round starts. Interactively you write it: when
`change-workflow next <change>` names `round`, record that round, as it
names it, before implementing — `change-workflow note <change> round
--sections '<its sessions, as 1,2;3>' --by <its by>` — and implement its
first session. When it names `implement`, the round is recorded already.

## The run's inputs

Before this session the engine ran the repository's `before-implement` hook, and
kept what it did in the run's inputs directory, which your prompt names (`Inputs`,
`reviews/runs/<run>/before`). Read it first: `status.md`, the hook's closing lines,
exit status, and log, and every other top-level Markdown file there, each a message
from the repository's hook, in full. Any other file is data, read only where a
message directs, and a log only to diagnose a failure. A failing hook prevented
nothing, but it may leave the environment broken — an environment refresh that
failed, say — so stop and ask the owner, with what it reported, rather than code in
it. Interactively, with no wrapper, run `change-workflow run before
implement <change>` first; its last line names the directory. Once the sections are
committed and pushed, run `change-workflow run after implement <change>`
before `record`, and, when it fails, fix what it found, commit and push the fix, and
run it again. Unattended, an after-hook that fails resumes this session once with
its failure: fix what it found, commit and push the fix, and end with your outcome
again; a second failure goes to the owner as a question.

A guide or a message may add to or narrow what this skill says. When one
contradicts this skill's text, name the file and the contradiction in your report
and follow this skill.

## The owner's direction

Invoked with sections and an argument after the change, the argument is the owner's
direction to those sections, relayed by the orchestrating session, with any routing
note of its own marked as such. Follow it as the owner's word wherever it bears on
the sections; where it conflicts with the plan or a written rule, stop and ask
rather than choose.

## Resolving a merge's conflicts

Invoked with no sections and an argument naming a merge's conflicted files —
`resolve the merge conflicts in <files>` — you conclude a merge of the branch the
change lands on, or another the owner named, that the
orchestrating session started on the owner's word and that stopped at conflicts in
code the owner did not rule on. Steps 1 to 9 do not apply; this is the whole run,
and it checks no task.

1. **Check.** The branch is the change's, as step 1 checks it. A merge is in
   progress: `git rev-parse --quiet --verify MERGE_HEAD` prints a commit; if it
   prints nothing, stop and say so. The unmerged files, `git diff --name-only
   --diff-filter=U`, are the files you were named; any other difference is the
   owner's to settle, as a question.
2. **Load the context.** Step 2's guidance documents, the change's `proposal.md`,
   `design.md`, and `tasks.md`, and, for each conflicted file, the sections whose
   tasks touch it and their notes, and what each side did to it: `git log --merge
   -p -- <file>`.
3. **Resolve.** Edit each file so both sides hold: the change's behaviour as its
   sections built it, and the merged branch's as its commits made it, with comments describing
   the system that results. Where the two cannot both hold, the resolution is a
   decision: ask the owner, with the options and your recommendation. Then `git
   add` each resolved file.
4. **Test.** Run the suites the verification tasks of the sections owning the
   conflicted files name, then `change-workflow run pre-commit <change>`
   (step 5): a resolution outside the inert paths is a functional change, so it
   runs every hook of a functional commit. A conflicted derived file, such as a
   lock, is resolved by taking one side before it runs, and the hook that rebuilds
   it settles the rest. Fix what the merge broke, adding each fix, and what the
   hooks rebuilt, to the merge.
5. **Conclude.** `git commit -m "<Git's merge subject>" -m "<resolutions>"`
   concludes the merge without opening an editor: the subject is the one Git
   wrote for it (`Merge branch '<merged>' into <branch>`), and the paragraph names each
   conflicted file and how it was resolved. Push it with `change-workflow
   push`; if it refuses, stop and report its reasons. Report each file's resolution, and end `finished`. A merge is the
   owner's intervention, so where the change goes after it is theirs, not this
   run's: `next` is `{"step": "round"}`, an exit implementation does not declare,
   which the computation brings to the owner rather than taking, and `message`
   says where the change stood — what `change-workflow next <change>`
   names once the merge is concluded — for the owner to direct it.

## 1. Check that this section may start

- **Branch.** The checked-out branch is the one this change is worked on. Several
  changes are often in flight in one checkout; if the branch does not carry this
  change's latest planning commits, or its name belongs to another change, stop and
  ask the owner — unless the change's log holds the owner's decision that it runs
  on this branch: run `git branch --show-current`, then
  `change-workflow log <change> --branch <that branch>`; a line
  it prints is that decision, and the branch is accepted.
- **Status.** The change's row in `openspec/changes/README.md` is
  `ready for implementation` or `in implementation`, and no dependency in its
  `Depends on` gates implementation while unlanded. A change `in closeout` whose
  return to implementation the owner has confirmed is set `in implementation`.
- **Worktree.** It is clean, or holds only changes the owner confirms are this
  section's, or the edit that a task of this section gives the orchestrator
  (section 3). `change-workflow check round-view` passes:
  while the owner reads a round
  (`make round-view`), the branch points at the round's base and its changes are
  uncommitted, so committing a section then would squash the round into it.
- **Task list.** `make check-tasks CHANGE=<change>` passes. A task numbered for
  one section under another section's heading means a heading was lost in an
  edit, and the sections cannot be read until it is restored.
- **Section.** The owner names it, or it is the first section with unchecked tasks.
  An earlier section with unchecked tasks is unfinished: that is the section, unless
  the owner says otherwise. When the owner names a range ("sections 1-3"), work them
  in order, one at a time, through every step below.

If any check fails, stop and say why.

## 2. Load the context

Read in full, even if you believe you know it:

- the documents `change-workflow config load implement` prints: the
  repository's guidance, which its configuration names;
- the change's `proposal.md`, `design.md`, `specs/`, and all of `tasks.md` —
  especially earlier sections' notes, which carry the previous session's handoff;
- the triage of the latest implementation review in `reviews/`, if any: accepted
  findings may have become tasks in this section;
- the permanent spec and architecture companion of every capability the section
  touches, and every other Markdown file in its directory but its `index.md`: the
  capability's own guidance;
- the code the section changes, and the tests it extends.

If the session compacts while working, read these again before continuing.

When this is the change's first section, set its status to `in implementation`.

## 3. Implement the section

Work through the section's tasks in order. For each:

- Make the change the task and its cited decision call for, and no more. Work that
  belongs to a later section stays there. A defect you find on the way is fixed
  here when its fix is understood and small beside the change, even outside the
  change's stated scope, and recorded in the section's notes as outside the plan,
  so the round's review and the owner's reading see it; one that is large, or not
  understood well enough to fix without a design of its own, is recorded where
  deferred work goes (the workflow guidance's sections "Deferred work" and "Defects
  found during a change").
- A task the plan gives the orchestrator — an edit of a protected path, which no
  step writes: the harness's settings, the workflow's configuration, or one the
  repository protects, as `change-workflow config --json` lists them — is
  never attempted: check that its edit is in the worktree and commit it with the
  section. When it is missing, stop and name the edit.
- Prove it at the lowest test level that can (the engineering guidance's sections
  "Where a test goes" and "Test levels"), through the seams and injected
  dependencies the code already offers rather than brute-force patching (the
  engineering guidance's section "Test seams").
- Respect the dependency layers the repository's guidance draws, and take internal
  dependencies as it says; `TYPE_CHECKING` imports count
  (the engineering guidance's section "Every import form counts").
- Comments describe the current system: an invariant, a constraint, a reason a
  simpler implementation is wrong. Never a change name, a task number, a review, or
  what the code used to be (the engineering guidance's section "Comments describe
  the current system"; the workflow guidance's section "Change references").
- Imports the section adds go at module level, unless one has a reason to stay
  local that you verified by attempting the move — a circular import that fails, or
  a deliberate lazy load — and recorded beside it
  (the engineering guidance's section "Imports go at module level"; the workflow
  guidance's section "Import placement"). Closeout only confirms
  comments and imports; it never edits code, so this is where they are done.
- Mark the task `[x]` when its evidence passes, with a short note: each suite, its
  level as the engineering guidance's section "Test levels" defines them — unit, library
  integration (a real component against real storage, no application),
  application integration (the running
  application through its typed client), or system — and its result, and anything
  that differed from the plan. Name a suite by what it actually exercises: a test
  that calls the reconciler directly is not application integration, and a test that
  shows a listing becomes a candidate to close does not show it closes.
- Before the section's last task is checked, confirm or correct the end-to-end
  scenarios its plan says cover it, in the section's notes: the scenarios that
  exercise its behaviour once deployed, named as the guide of the evidence kind that
  runs them says — `change-workflow config` names each kind's guide —
  including any the section added, or that none does. Validation reads this to say
  whether the end-to-end result is evidence for the section.
- Confirm or correct, the same way, the section's `Owed by validation:` lines:
  evidence only a push produces, such as a CI workflow run a change branch's push
  does not trigger, named by the owed kind that produces it and its argument, then
  what must be shown, as the kind's guide gives it. Every validation of the change
  gathers each one once the section is complete and judges it, so a line naming the
  wrong argument or observation misdirects them all.
  A verification task that demands such evidence itself — an older plan, or a slip
  — is checked on the section's own evidence once that passes, and the push-only
  evidence is written as an `Owed by validation:` line in the section's notes; it
  never holds the task open, since no implementation session can produce it. Only
  what the owed kind's guide says may be owed can be: owing anything else is a
  design question (step 4).

Never delete or rewrite a completed task; amend it with a correction note when
something it established changes.

## 4. Stop cleanly when the plan is wrong

If the code shows the section's premise is wrong, or a task needs a design decision
the design does not make, do not guess and do not work around it:

1. Record in the section's notes what you found, with the evidence, and what you
   had and had not done.
2. For a return to design or planning, commit what the section has — its code,
   tests, and notes — as one work-in-progress commit, checking no task for it: the
   message names the change and the section, says the work is in progress, and why
   the change returns. No check need pass first: the change's branch is not
   protected — only the configuration's protected branches are — and a commit known not to work harms
   nothing on it, while no session is left to commit the work, and a dirty
   checkout blocks every later step's guarded push. Push it with `change-workflow push`; if it refuses, stop
   and report its reasons, leaving the commit as it is.
3. Tell the owner, and recommend the way back: a design question returns the change
   to design (`change-design`); a plan defect goes to planning (`change-plan`); an
   external input the change cannot supply makes it `blocked in implementation`,
   and that commits nothing, since this session resumes once it is supplied.

Only a return commits partial work. A stop — the session's limit, a denied call it
cannot go on without — leaves the work uncommitted for the resumed session to
finish and commit, and a stop because a repository guard refused or `HEAD` moved
commits nothing further.

If the section turns out far larger than its plan — many more files or layers than
it names — stop at a coherent, verified point instead, record the handoff, and tell
the owner the section was sized wrong. A section far larger than its plan is a
planning defect, not a reason to let the session compact.

## 5. Check before committing

Run each of these, and fix what it reports:

- the focused suites the section's verification point names, and every suite that
  covers code the section changed;
- where a test you wrote should fail without the change, show it:
  `change-workflow run test-before <change> --test <path> [--at <commit>]`
  runs the test file as `HEAD` holds it against the round's base, or the commit
  given, in a throwaway worktree, and its closing line says whether it failed
  there. It runs in the environment of the project owning the test, against the
  checkout's wheels; where the code under test is an internal dependency's, name
  the root `make` targets that rebuild its wheels from that commit in
  `TEST_BEFORE_DIST` (`TEST_BEFORE_DIST=dist-compute-provisioning`), and `dist`
  only when no narrower set will do. A test that imports what only the change adds
  fails as it is collected, which shows less; read the error and say which it was.
  Never stash, check out, or reset to see the
  old code: the change's worktree is not touched to answer it;
- `change-workflow run pre-commit <change>`, the repository's checks
  before a commit. The paths the worktree changes decide what it runs: when any
  lies outside the repository's inert paths, it runs `after-functional-change`,
  such as a relock, then `pre-commit-functional`, such as the packaging check
  and every suite, then `pre-commit`; otherwise `pre-commit` alone. `pre-commit`
  runs the workflow's default checks — the change index, the task list, the
  skills, and the strict OpenSpec validation of the change — then the
  repository's own closing checks. Each hook ends with the engine's closing line,
  naming every command that failed with its exit status. Stage what the hooks
  rebuilt, such as a lock, with the section's edits. Before closeout the
  citations check may report only the permanent documents the change's tasks
  create at closeout — the promotion destinations its plan names; list those in
  the report and fix anything else. A change with no spec deltas fails the
  validation every time, since the validator rejects a change with none; say so
  in the report and take that one failure as expected. A change whose clone
  recorded no landing branch, or that has no clone, needs `--base <branch>` where
  the configuration names `{base}`, and the run refuses without it, naming it:
  give the branch the change's log or its plan says it lands on.

Then have the section's diff checked in a fresh context. Start a subagent that has
seen none of this session, and give it only: the change name, the section, the
command to see the diff (`git diff` against the section's starting commit, plus any
untracked files), and this instruction — read the documents
`change-workflow config load implement` prints and every document they
require, plus the specs and architecture companions of the capabilities the diff
touches and every other Markdown file in their directories but their `index.md`;
then report every place the diff breaks that guidance — layering,
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
says what it delivers. Then push it with `change-workflow push`, the
guarded push of exactly `HEAD`; if it refuses, stop and report its reasons. A pushed branch starts
nothing: validation's gathering dispatches what it needs itself.

## 8. Continue or stop

When sections you were given remain, go on to the next one, from step 1, without
waiting — unless this section stopped for a plan or design problem, or its checks
could not be made to pass, which ends the sections. Before starting the next
section, re-read the section and its earlier sections' notes; and if the session
has compacted, re-read every document in step 2.

When the sections you were given are committed and pushed, stop and report. Say
how large the session has grown if you can tell; when it is large, recommend that
the next sections start in a fresh session.

## 9. Report

When the session stops, tell the owner, for each section implemented:

- what the section delivered, and the tasks checked;
- the evidence: each check and suite with its result;
- what the fresh-context check found, what was fixed, and what was declined;
- the handoff recorded;
- what comes next. While the round's recorded sessions leave sections you were
  not given, that is the round's next session, named by its sections, and nothing
  else: validation and the review read the whole round. Once yours was the round's
  last session, it is validation (`make validate CHANGE=<change>`) and one
  implementation review (`make review CHANGE=<change> KIND=implementation`), run
  side by side, and the owner's reading of the commits since the last round as
  uncommitted changes (`make round-view CHANGE=<change>`, closed with `make
  round-done`). For a change worked in its own clone, the owner reads in their
  workspace while validation and the review run in the clone. For a change worked
  in the owner's workspace, the view moves the branch this checkout works on, so
  the reading comes first and validation and the review start once it is closed.
  Then the round is triaged in a fresh session (`make triage CHANGE=<change>`),
  which fixes what the owner accepts and records whether the change advances;
  then, once the fix commit is validated, the next round.
