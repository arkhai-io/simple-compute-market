---
name: change-closeout
description: Close out an OpenSpec change whose pre-closeout gate has passed — work through the eleven parts of its closeout task in order, confirming the code checks and reporting every judgement made, promote its durable knowledge, check its citations, archive it last so its spec deltas merge into openspec/specs, and commit, so the closeout review reads the archived change. Use when a change is `ready for closeout` or `in closeout` in openspec/changes/README.md, or when the owner says "close out <change>".
---

# Closing out an OpenSpec change

Closeout turns a change into the permanent record of what the system now is. It
works through the change's closeout task — the eleven parts in
`openspec/README.md#plan-closeout-requirements`, which the plan made specific to
this change as its last `tasks.md` section — and ends by archiving the change:
`openspec archive` merges the change's spec deltas into `openspec/specs/` and moves
the change under `openspec/changes/archive/`. Archival is the last step, so the
closeout review that follows reads the change, and the specifications, as they will
land. Archive cleanup (`change-archive-cleanup`) — releasing dependents and
drafting the pull request — follows that review's gate and is not
closeout's.

Closeout is one session, and it changes documentation only: the change's own
files, the permanent documents, and the index. The code was last reviewed at
pre-closeout, and the closeout review reads documentation, so closeout never edits
code — a part that would need a code edit stops closeout and returns the change to
implementation. That also means closeout runs no test suites and owes no new
validation.

## Running unattended

Run interactively, as most runs are, this section does not apply, and nothing else
in the skill changes. When this skill runs through `scripts/run_change_step.py` —
`make closeout UNATTENDED=1`, or the orchestrating session — nobody can answer in
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
- **The end is an outcome.** Each point this skill puts to the owner is a
  `question`. A part that would need a code edit ends with `returned`,
  `return_to` `implementation`, and `evidence` naming the closeout task's notes,
  where you recorded what needs the edit; closeout never edits code. The owner
  confirms the return, and implementation then sets the status. When the archive is committed, end with `finished`,
  `next` naming the closeout review.

## 1. Check that closeout may start

- **Branch.** The checked-out branch is the one this change is worked on. If it does
  not carry this change's latest commits, or its name belongs to another change,
  stop and ask the owner.
- **Status.** The change's row in `openspec/changes/README.md` is `ready for
  closeout`, or `in closeout` when an earlier closeout session stopped. The
  pre-closeout gate is recorded as passed in the triage file of the latest
  pre-closeout review in the change's `reviews/`. If either is missing, stop: the
  change is not ready, and passing that gate is the owner's, in triage.
- **Where it stopped.** Find the change with `python3 scripts/find_change.py
  <change>`. When it prints a directory under `openspec/changes/archive/` while the
  row says `in closeout`, an earlier session archived it and stopped: if the
  archive is committed, closeout is finished, so say so and point to the closeout
  review; if not, skip to step 4's steps after the archive (3 onwards), then commit.
  Never archive twice. Read every file of the change from the directory the lookup
  prints, not from `openspec/changes/<change>/`.
- **Tasks.** Every task outside the closeout section is checked, or carries a note
  recording its deferral with the owner's word. An unchecked task with neither is
  unfinished implementation: stop and say which.
- **Worktree.** It is clean, and `make round-view-closed` passes.

If any check fails, stop and say why. Otherwise set the row's status to
`in closeout`, rewriting its `Notes` in the same edit so nothing in it still
describes implementation.

## 2. Load the context

Read in full, even if you believe you know it:

- `AGENTS.md` and every document it requires: `docs/development/ARCHITECTURE.md`,
  `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, and
  `openspec/README.md`; and `docs/development/ROADMAP.md`.
- The change's `proposal.md`, `design.md`, `specs/`, `tasks.md`, and
  `interventions.jsonl`. The proposal's "Knowledge to promote" and the closeout
  section's promotion task name what must reach permanent documentation.
- The pre-closeout review and its triage, and the latest validation record: their
  dispositions may have added to the closeout task.
- For every capability the change touches: `openspec/specs/<capability>/spec.md`
  and its `architecture.md` companion when one exists.
- The change's row, campaign, and every row that lists it in `Depends on`, in
  `openspec/changes/README.md`.

## 3. Work through the closeout task

Take the parts in the order `openspec/README.md#plan-closeout-requirements` gives
them, which is the order the closeout section lists them in; this step covers parts
1 to 8, and step 4 the last three. Mark each `[x]` when its evidence holds, with a
short note: what was run and its result, or what was decided and why. Never delete
or rewrite a completed task; amend it with a correction note. An older plan may
list its parts in another order; work in this order, and note it on the section.

- **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read the
  comments the change added for any that name the review or migration that
  introduced them. Do not edit them: if anything needs rewriting, stop, tell the
  owner what and where, and recommend a fix round in implementation.
- **Import placement — confirm.** Check the imports the change added for any still
  local without a recorded reason. Do not move one: if one should move, stop as for
  comment hygiene.
- **Documentation compliance.** Check every accepted decision in `design.md`
  against `openspec/README.md#documentation-placement`, and the permanent documents
  against the code they describe.
- **Narrative compression.** Shorten completed-task notes to final behaviour,
  material evidence, deferrals, and destinations. Move what is worth keeping —
  alternatives, debugging narratives, review rationale — into `design.md` first;
  this step removes duplication, not information.
- **Roadmap currency.** Update the affected goal's current state and gap mapping in
  `ROADMAP.md`, or record that no goal is affected.
- **Campaign index currency.** Update the change's row and its campaign's
  dependency graph. Leave every other row's `Depends on` and status as they are:
  the change lands, and its dependents are released, only at archive cleanup after
  the closeout gate (`openspec/README.md#plan-closeout-requirements` part 6). The
  status stays `in closeout`: archive cleanup writes `archived`. Run
  `make check-change-index` after the edit.
- **Packaging.** Run `make check-packaging`, then `make check-architecture-change
  CHANGE=<change>`, and `make check-agent-skills` when the change touched
  `.agents/`, `.claude/`, or `.codex/`. A failure that needs a code or lock change
  stops closeout as above. An architecture exception or override row the change
  still owns is deleted with its edge, which is code, or reassigned in
  `docs/development/ARCHITECTURE.toml` to the open change that now owns the
  divergence; reassigning is the owner's decision, so put it to them.
- **End-to-end pipeline.** Record the run the latest passing validation names, its
  result, and the scenarios that exercise the change, from the validation record's
  coverage section. Closeout changes no code, so that run still describes the code
  the closeout commit carries; say whether it names the pre-closeout commit or an
  earlier one the owner waived.

A part that needs a decision the change does not make — an open question the plan
left to closeout, or a disposition the triage deferred to it — is put to the owner
in prose, with the options and your recommendation, and recorded in `design.md` when
decided. Never settle it yourself.

## 4. Promote, check, then archive

**Promotion.** Write every permanent document the closeout section names:
architecture companions, `ARCHITECTURE.md`, the other documents under `docs/`,
`openspec/specs/README.md`, and any `spec.md` content the deltas do not carry.
Describe the system as it is now, never the change that made it so. Complete the
design-promotion record in `design.md`: every accepted decision and its permanent
location, as a heading anchor where one exists. A `spec.md` the change's deltas
cover is written by the archive, not by hand; the record names it all the same.

**Checks against the promoted state.** Now that every document the change cites
exists:

- `make check-doc-citations CHANGE=<change>` must report nothing; fix the
  documents until it does.
- `openspec validate <change> --strict`, with the validator `openspec/README.md`
  pins. A change with no spec deltas cannot pass it — the validator rejects a change
  with none — so record on the citations task that it has none, and skip it.

**Archive** — the last change to the change's files. Check every other closeout
part is checked first.

1. Decide whether the deltas merge. Compare each delta under `specs/` with the
   permanent `spec.md` it targets. When they already say what the delta adds — the
   specs were synchronized by hand before archival became closeout's last step —
   archive with `--skip-specs`, and note that on the promotion task; merging them
   again would duplicate requirements. A change with no deltas archives with
   `--skip-specs` too.
2. Run `openspec archive <change> -y`, adding `--skip-specs` where step 1 decided
   it, with the pinned validator. It validates the change, merges the deltas, and
   moves the change — its untracked `reviews/` with it — to
   `openspec/changes/archive/<date>-<change>/`.
3. Read the diff of every permanent `spec.md` the archive wrote. Each requirement
   the change added or modified is there once, as the delta stated it, and nothing
   it did not touch changed. A wrong merge is fixed in the permanent spec now,
   before the review reads it.
4. Point the change's row in `openspec/changes/README.md` at the directory
   `python3 scripts/find_change.py <change>` now prints, and update any other link
   to the change's directory in the index.
5. Run `openspec validate --specs --strict` with the pinned validator, and
   `make check-change-index`.

If the archive fails, nothing has moved: fix what it reports, or, when the fix is
not closeout's to make, stop and tell the owner.

## 5. Commit

Commit the closeout as one commit: the permanent documents, the archived change
with its `tasks.md` and promotion record, the merged specifications, and the index.
The message names the change and says it is closed out and archived. Do not push;
the closeout review reads the commit locally.

## 6. Report

Tell the owner:

- each closeout part, and for each mechanical one the check and its result;
- each judgement made and why: comments and imports confirmed, documents placed,
  notes compressed and what moved to `design.md`, and the roadmap and index edits;
- the permanent documents written, and the specifications the archive merged or
  skipped and why;
- the pipeline evidence and the commit it describes;
- anything that stopped closeout for a code edit, and the fix round recommended;
- what comes next: the closeout review (`make review CHANGE=<change>
  KIND=closeout`), which reads the archived change, then its triage in a fresh
  session (`make triage CHANGE=<change>`); the gate passing is followed by archive
  cleanup in another (`make archive-cleanup CHANGE=<change>`).
