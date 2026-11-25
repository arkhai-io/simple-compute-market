---
name: change-closeout
description: Close out an OpenSpec change whose pre-closeout review's triage advanced it — work through the parts of its closeout task in order, the workflow's and the repository's own, confirming the code checks and reporting every judgement made, promote its durable knowledge, check its citations, archive it last so its spec deltas merge into openspec/specs, and commit, so the closeout review reads the archived change. Use when a change is `ready for closeout` or `in closeout` in openspec/changes/README.md, or when the owner says "close out <change>".
---

# Closing out an OpenSpec change

Closeout turns a change into the permanent record of what the system now is. It
works through the change's closeout task — the workflow's parts in
the workflow guidance's section "Closeout", with the repository's own parts, in the
section the root guidance names, at the position it gives them, which the plan made
specific to this change as its last `tasks.md` section — and ends by
archiving the change:
OpenSpec's archive merges the change's spec deltas into `openspec/specs/` and moves
the change under `openspec/changes/archive/`. Archival is the last step, so the
closeout review that follows reads the change, and the specifications, as they will
land. Archive cleanup (`change-archive-cleanup`) — releasing dependents and
drafting the pull request — follows once that review's triage advances the change,
and is not closeout's.

Closeout is one session, and it changes only the repository's inert paths, changes'
records, and the archive's own writes — the change's own documents and their move
into the archive, its index row, and its deltas merged into the specifications
(`change-workflow`'s CW-pkug). The code was last reviewed at pre-closeout, and the
closeout review reads documentation, so closeout never edits code or any other path
outside those — a part that would stops closeout and returns the change to
implementation. That also
means closeout runs no test suites and owes no new validation.

## Running unattended

Run interactively, as most runs are, this section does not apply but for the
outcome it describes, which an interactive run records itself ("Running
interactively"); nothing else in the skill changes.
When this skill runs through `change-workflow start --unattended` —
`make closeout UNATTENDED=1`, or the orchestrating session — nobody can answer in
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
  them before the change moves on; never ask about either as a question. Wait on a
  background command with `change-workflow wait`, never by following its
  output. Closeout's sandbox mounts each inert path's directory, a README's code
  beside it included: a path closeout may not change, changed, stops the run at the
  checks after it.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **The end is an outcome.** Each point this skill puts to the owner is a
  `question`. A part that would need a code edit ends with `returned`, `next`
  implementation, `{"step": "round"}`, and `evidence` naming the closeout task's
  notes, where you recorded what needs the edit; closeout never edits code. Every
  section before closeout is checked, so no planned round remains: the owner's
  confirmation directs the implementation that makes the edit. Before ending,
  commit what closeout has written — the status, the notes, any part done — as one
  work-in-progress commit naming the change and why it returns, and push it with
  `change-workflow push`: no session is left to commit it, and a dirty checkout blocks
  every later step's guarded push. The owner confirms the return, and the step
  their confirmation directs then sets the status. A stop commits nothing: its work waits
  uncommitted for the resumed session, and one stopped because a repository guard
  refused or `HEAD` moved leaves the checkout as it was. When the archive
  is committed and pushed, end with `finished`, `next` naming closeout's one exit,
  the closeout review, `{"step": "review", "kind": "closeout"}`.

## Running interactively

Run in an interactive session — `make closeout` without `UNATTENDED=1`, or the
slash command — no wrapper records the run, so its last act records the outcome
it would end with unattended, as "Running unattended" gives it:

```text
change-workflow record <change> closeout --outcome '<the outcome, as JSON>'
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
session closed before it records leaves closeout in progress: the computation
names it again, to be resumed, or its outcome recorded with the command above.

## The run's inputs

Before this session the engine ran the repository's `before-closeout` hook, and kept
what it did in the run's inputs directory, which your prompt names (`Inputs`,
`reviews/runs/<run>/before`). Read it first: `status.md`, the hook's closing lines,
exit status, and log, and every other top-level Markdown file there, each a message
from the repository's hook, in full. Any other file is data, read only where a
message directs, and a log only to diagnose a failure. A failing hook prevented
nothing: say in your report what its failure means for the closeout, and stop and
ask the owner when the closeout cannot be made soundly with it. Interactively, with
no wrapper, run `change-workflow run before closeout <change>` first; its
last line names the directory. Once the work is done, run `change-workflow
run after closeout <change>` before `record`, and, when it fails, fix what it found
if closeout may, and run it again, or tell the owner. Unattended, an after-hook that
fails resumes this session once with its failure; a second failure goes to the owner
as a question.

A guide or a message may add to or narrow what this skill says. When one
contradicts this skill's text, name the file and the contradiction in your report
and follow this skill.

## 1. Check that closeout may start

- **Branch.** The checked-out branch is the one this change is worked on. If it does
  not carry this change's latest commits, or its name belongs to another change,
  stop and ask the owner — unless the change's log holds the owner's decision
  that it runs on this branch: run `git branch --show-current`, then
  `change-workflow log <change> --branch <that branch>`; a line
  it prints is that decision, and the branch is accepted.
- **Route.** `change-workflow next <change>` names `closeout`,
  whatever the status says: the exit of the merge that follows the pre-closeout
  triage, bringing in the branch the change lands on, once a validation cleared the merged `HEAD`, or the owner's
  direction to closeout, which checks no exit guard. A row still `in
  implementation` is so accepted: the merge advanced before its merged `HEAD` was
  validated, so it could not set `ready for closeout`. When the computation names
  anything else — the pre-closeout review's triage, the merge, a validation of
  `HEAD`, the owner — stop: the change is not ready, and the computation's reason
  says what comes first.
- **Where it stopped.** Find the change with `change-workflow find
  <change>`. When it prints a directory under `openspec/changes/archive/` while the
  row says `in closeout`, an earlier session archived it and stopped: if the
  archive is committed, closeout is finished: say so, end with the finished
  outcome the earlier session did not record — interactively, record it — and
  point to the closeout review; if not, skip to step 4's steps after the archive (3 onwards), then commit.
  Never archive twice. Read every file of the change from the directory the lookup
  prints, not from `openspec/changes/<change>/`.
- **Tasks.** `change-workflow check tasks <change>` passes, so the sections are what
  the headings say. Every task outside the closeout section is checked, or carries
  a note recording its deferral with the owner's word. An unchecked task with
  neither is unfinished implementation: stop and say which.
- **Worktree.** It is clean, and `change-workflow check round-view` passes.

If any check fails, stop and say why. Otherwise set the row's status to
`in closeout`, rewriting its `Notes` in the same edit so nothing in it still
describes implementation.

## 2. Load the context

Read in full, even if you believe you know it:

- The documents `change-workflow config load closeout` prints, and, for
  the closeout task's roadmap part, the repository's roadmap, which its root
  guidance names.
- The change's `proposal.md`, `design.md`, `specs/`, `tasks.md`, and
  `interventions.jsonl`. The proposal's "Knowledge to promote" and the closeout
  section's promotion task name what must reach permanent documentation.
- The pre-closeout review and its triage, and the latest validation record, with the
  guide of each evidence kind it names, which `change-workflow config`
  lists: their dispositions may have added to the closeout task.
- For every capability the change touches: `openspec/specs/<capability>/spec.md`
  and its companion when one exists — `README.md` where the capability has an
  `index.md`, which you read too, and `architecture.md` elsewhere — and every
  other Markdown file in its directory but its `index.md`: the capability's own
  guidance.
- The change's row, campaign, and every row that lists it in `Depends on`, in
  `openspec/changes/README.md`.
- Another change's records, where the closeout's evidence or promotion rests on
  them, wherever `change-workflow find --records <change>` says they are:
  this checkout, or, from a change's clone, the owner's workspace, which holds the
  history of every cleaned-up change.

## 3. Work through the closeout task

Take the parts in the order the workflow guidance's section "Closeout" gives them, with
the repository's own parts where it places them, which is the order the closeout
section lists them in; this step covers comment hygiene through the repository's own
parts, and step 4 promotion, guidance placement, documentation citations, and
archival. Mark each `[x]` when its evidence holds, with a
short note: what was run and its result, or what was decided and why. Never delete
or rewrite a completed task; amend it with a correction note. An older plan may
list its parts in another order; work in this order, and note it on the section.

- **Comment hygiene — confirm.** Run the repository's comment check, which the
  section the root guidance names gives among the checks the workflow's parts run,
  and read the
  comments the change added for any that describe history rather than the current
  system (the engineering guidance's section "Comments describe the current
  system") or name the change, the review, or the migration that introduced them
  (the workflow guidance's section "Change references"). Do not edit them: if anything
  needs rewriting, stop, tell the owner what and where, and recommend a fix round
  in implementation.
- **Import placement — confirm.** Check the imports the change added for any still
  local without a recorded reason
  (the engineering guidance's section "Imports go at module level").
  Do not move one: if one should move, stop as for comment hygiene.
- **Documentation compliance.** Check every accepted decision in `design.md`
  against the placement rules —
  the workflow guidance's section "Documentation placement" and
  the repository's placement table, which its root guidance names — and the permanent documents
  against the code they describe, each describing the current state with no wording
  relative to the change
  (the engineering guidance's section "Permanent documents describe the current state").
- **Narrative compression.** Shorten completed-task notes to final behaviour,
  material evidence, deferrals, and destinations. Move what is worth keeping —
  alternatives, debugging narratives, review rationale — into `design.md` first;
  this step removes duplication, not information.
- **Roadmap currency.** Update the affected goal's current state and gap mapping in
  the repository's roadmap, or record that no goal is affected.
- **Campaign index currency.** Update the change's row and its campaign's
  dependency graph. Leave every other row's `Depends on` and status as they are:
  the change lands, and its dependents are released, only at archive cleanup after
  the closeout review's triage advances it
  (the workflow guidance's section "Campaign index currency"). The
  status stays `in closeout`: archive cleanup writes `archived`. Run
  `change-workflow check index` after the edit.
- **The repository's own parts.** Each part the section the root guidance names
  defines, in its order, as that section says: what it confirms, the command it
  runs, and what a failure means for the change. Run the repository's checks before
  the archive, where a part calls for them, through `change-workflow run
  pre-archive <change>`; with no `pre-archive` declared it is skipped, saying so,
  and you record that. A failure that needs a code or lock change stops closeout as
  above; a resolution the part leaves to a decision — an exception the change still
  owns reassigned to another change, say — is the owner's, so put it to them.
  Closeout runs no validation and owes none: a part that records validation's
  evidence — an end-to-end run, say — takes it from the latest passing validation
  record, whatever command the part names as producing it, read with the guide of
  each evidence kind the record names: the evidence, its
  result, and the scenarios that exercise the change, from the record's coverage
  section. Record too, from the record's section of each owed kind, each observation
  the change's sections owed by validation (`Owed by validation:` in `tasks.md`) and
  what showed it. Closeout changes no code, so that evidence still describes the
  code the closeout commit carries; say whether it names the pre-closeout commit or
  an earlier one the owner waived. The skills check runs among `run pre-commit`'s
  defaults (step 4), whatever the change touched.

A part that needs a decision the change does not make — an open question the plan
left to closeout, or a disposition the triage deferred to it — is put to the owner
in prose, with the options and your recommendation, and recorded in `design.md` when
decided. Never settle it yourself.

## 4. Promote, check, then archive

**Promotion.** Write every permanent document the closeout section names:
companions — a capability's `README.md` where it has an `index.md`, its
`architecture.md` elsewhere — the repository's cross-system documents, its
capability index, and any `spec.md` content the deltas do not carry.
Describe the system as it is now, never the change that made it so. Complete the
design-promotion record in `design.md`: every accepted decision and its permanent
location, as a heading anchor where one exists. A `spec.md` the change's deltas
cover is written by the archive, not by hand; the record names it all the same.

In a capability organized by an `index.md`
(the workflow guidance's section "A capability organized by an index"),
promotion also writes the
index before the archive merges the deltas: an entry for each id the change's deltas
add — its link to the requirement's heading in `spec.md` and its summary line, under
the part and group it belongs to — and, for each requirement the deltas remove, its
id moved to the retired ids with where its rule went. The workflow's default
checks run the specification index check with the change's deltas counted, so an id a delta adds
is accepted before the archive puts it in `spec.md`.

**Guidance placement.** Read each guidance section the change added, moved, or
rewrote — promoted text included — against the layer test, adjacency, and exception
placement (the workflow guidance's section "Guidance placement"); move what is
misplaced and re-point its citations within the inert paths — a citation outside them
returns the change to implementation — then run the repository's guidance check where
its closeout parts name one. Report a placement that needs a decision for the
closeout review; never settle it yourself. A change that touched no guidance records
that.

**Checks against the promoted state.** Now that every document the change cites
exists:

- `change-workflow run pre-commit <change>` must report nothing failing:
  its citations check finds every document the change cites
  (the engineering guidance's section "Citations resolve"), so fix the
  documents until it does, and its default OpenSpec check runs `validate <change>
  --strict` through the configured command. A change with no spec deltas cannot
  pass that validation — the validator rejects a change with none — so record on
  the citations task that it has none, and take that one failure as expected.

**Archive** — the last change to the change's files. Check every other closeout
part is checked first.

1. Decide whether the deltas merge. Compare each delta under `specs/` with the
   permanent `spec.md` it targets. When they already say what the delta adds — the
   specs were synchronized by hand before archival became closeout's last step —
   archive with `--skip-specs`, and note that on the promotion task; merging them
   again would duplicate requirements. A change with no deltas archives with
   `--skip-specs` too.
2. Run `change-workflow openspec archive <change> -y`, adding
   `--skip-specs` where step 1 decided it; it runs the OpenSpec command the
   repository's configuration names. It validates the change, merges the deltas, and
   moves the change — its untracked `reviews/` with it — to
   `openspec/changes/archive/<date>-<change>/`.
3. Read the diff of every permanent `spec.md` the archive wrote. Each requirement
   the change added or modified is there once, as the delta stated it, and nothing
   it did not touch changed. A wrong merge is fixed in the permanent spec now,
   before the review reads it.
4. Point the change's row in `openspec/changes/README.md` at the directory
   `change-workflow find <change>` now prints, and update any other link
   to the change's directory in the index.
5. Run `change-workflow run pre-commit <change>`, whose default OpenSpec
   check, for an archived change, validates every specification strictly, and
   which checks the change index among the rest.

If the archive fails, nothing has moved: fix what it reports, or, when the fix is
not closeout's to make, stop and tell the owner.

## 5. Commit

Commit the closeout as one commit: the permanent documents, the archived change
with its `tasks.md` and promotion record, the merged specifications, and the index.
The message names the change and says it is closed out and archived. Then push it
with `change-workflow push`, the guarded push of exactly `HEAD`; if it
refuses, stop and report its reasons. The closeout review reads the commit locally.

## 6. Report

Tell the owner:

- each closeout part, and for each mechanical one the check and its result;
- each judgement made and why: comments and imports confirmed, documents placed,
  notes compressed and what moved to `design.md`, and the roadmap and index edits;
- the permanent documents written, and the specifications the archive merged or
  skipped and why;
- the validation evidence the repository's own parts recorded, and the commit it
  describes;
- any contradiction you noticed between a guide or message and this skill;
- anything that stopped closeout for a code edit, and the fix round recommended;
- what comes next: the closeout review (`make review CHANGE=<change>
  KIND=closeout`), which reads the archived change, then its triage in a fresh
  session (`make triage CHANGE=<change>`); a triage that advances the change is
  followed by archive cleanup in another (`make archive-cleanup CHANGE=<change>`).
