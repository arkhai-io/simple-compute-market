---
name: change-archive-cleanup
description: Clean up an archived OpenSpec change once the owner has passed its closeout review's gate — release the changes that depend on it, set its index row to `archived`, keep its reviews, commit, and draft the merge commit message and pull request description. Use when a closeout gate has passed and the change's row still says `in closeout`, when the owner says "clean up the archive of <change>", or when `make archive-cleanup` invokes you.
---

# Cleaning up an archived change

Closeout archived the change and committed it; the closeout review read the archive,
and the owner passed its gate in triage. The change has not landed yet: a change
lands when its index row says `archived`, and this skill writes that. It does what
closeout deliberately left until the review agreed — releasing the changes that
wait on this one — and prepares the change to merge.

Archive cleanup changes the campaign index only. The archived change, its specs, and
the permanent documents are as the closeout review read them; a defect found now
in any of them is not this skill's to fix — stop and tell the owner.

## 1. Check that cleanup may start

- **Branch.** The checked-out branch is the one this change is worked on. If it does
  not carry this change's latest commits, or its name belongs to another change,
  stop and ask the owner.
- **Archived.** `python3 scripts/find_change.py --archived <change>` prints a
  directory under `openspec/changes/archive/`. Read every file of the change from
  there.
- **Status.** The change's row in `openspec/changes/README.md` is `in closeout`. A
  row already `archived` means cleanup ran: say so and stop.
- **Gate.** Every numbered closeout review in the change's `reviews/` —
  `NN-closeout.md`, `NN-closeout-external.md` — has a triage file beside it, and
  the latest one's `## Gate` records the owner passing it. Otherwise stop: passing
  that gate is the owner's, in triage.
- **Worktree.** It is clean, and `make round-view-closed` passes.

If any check fails, stop and say why.

## 2. Load the context

Read in full: `openspec/README.md#plan-closeout-requirements` (part 6 states the
dependent rules), and `openspec/changes/README.md` — its legend, the change's row
and campaign, and every row and dependency graph that names the change. From the
archived change read `proposal.md`, `design.md`'s design-promotion record,
`tasks.md`'s closeout section with its end-to-end evidence, and the latest passing
validation record in `reviews/`.

## 3. Release the dependents

For every row whose `Depends on` lists this change:

- Remove the change from its `Depends on`, leaving `—` when nothing remains.
- When its status is `ready for planning`, `in planning`, or `ready for
  implementation`, set it to `ready for design`, and say in its `Notes` that its
  design is reverified against the codebase this change left. Its design rests on
  code this change has just altered.
- When its status is `blocked in` a phase, keep it, and record in its `Notes` that
  design reverification is owed once the blocker clears.
- Any other status — `ready for design`, `in design`, or `in implementation`, whose
  implementation has begun — is kept as it is. Do not read its `tasks.md` to decide.

A row that does not list the change in `Depends on` but describes it in its `Notes`
as still to land is rewritten to say it has; its status is not touched.

## 4. Mark the change archived

In the same edit, set the change's row to `archived`, and rewrite its `Notes` in the
form the index's other archived rows use: `Archived <date>`, from the archive
directory's name, and where it was promoted, from the design-promotion record,
followed by anything still owned elsewhere that the old notes named. Mark the change
`(archived)` in every campaign dependency graph that shows it.

Leave the change's `reviews/` where it is, transcripts included: it is untracked, so
it costs the repository nothing, and it is the only copy of the review history
until an export flow exists.

Run `make check-change-index` and `make check-doc-citations CHANGE=<change>`; both
must report nothing. The citation check reads only the change's own documents, so
the index check is the one that sees this edit.

## 5. Commit

Commit the index edit as one commit whose message names the change and says its
archive is cleaned up and which dependents it released. Do not push.

## 6. Draft the merge

Draft, for the owner to use when the branch is merged:

- **A merge commit message** — a subject naming what the change makes true, and a
  body of a few lines: the behavior it adds or changes, and the permanent documents
  that now describe it.
- **A pull request description** — what the change does and why, from the proposal;
  where its decisions now live, from the promotion record; how it was validated —
  the pipeline run, its result, the commit it ran at, and the scenarios that
  exercised the change — from the closeout section and the validation record; and
  what it deliberately leaves to other changes, by their names.

Both are as public as the code, so `AGENTS.md#public-repository-discipline`
applies to every word. When the branch carries another change that is not archived,
say so: the pull request would merge that change too, so the owner decides when to
open it, and the drafts cover this change only.

Write both to `reviews/pull-request.md` in the archived change, beside the review
history, and show them in the report.

## 7. Report

Tell the owner:

- each dependent released, its status before and after, and why;
- any row whose notes were rewritten;
- the commit, and the index and citation checks' results;
- the two drafts, and anything on the branch that the pull request would also carry.
