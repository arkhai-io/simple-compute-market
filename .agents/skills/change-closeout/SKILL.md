---
name: change-closeout
description: Close out an OpenSpec change whose pre-closeout gate has passed — work through the ten parts of its closeout task, running the mechanical checks and reporting every judgement made, promote its durable knowledge, archive it last so its spec deltas merge into openspec/specs, and commit, so the closeout review reads the archived change. Use when a change is `ready for closeout` or `in closeout` in openspec/changes/README.md, or when the owner says "close out <change>".
---

# Closing out an OpenSpec change

Closeout turns a change into the permanent record of what the system now is. It
works through the change's closeout task — the ten parts in
`openspec/README.md#plan-closeout-requirements`, which the plan made specific to
this change as its last `tasks.md` section — and ends by archiving the change:
`openspec archive` merges the change's spec deltas into `openspec/specs/` and moves
the change under `openspec/changes/archive/`. Archival is the last step, so the
closeout review that follows reads the change, and the specifications, as they will
ship. Shipping — deleting `reviews/` and drafting the pull request — follows that
review's gate and is not closeout's.

Closeout is one session. It edits documentation, the change's own files, and the
index; it changes code only where a closeout part calls for it, such as moving an
import.

## 1. Check that closeout may start

- **Branch.** The checked-out branch is the one this change is worked on. If it does
  not carry this change's latest commits, or its name belongs to another change,
  stop and ask the owner.
- **Status.** The change's row in `openspec/changes/README.md` is `ready for
  closeout`, or `in closeout` when an earlier closeout session stopped. The
  pre-closeout gate is recorded as passed in the triage file of the latest
  pre-closeout review in the change's `reviews/`. If either is missing, stop: the
  change is not ready, and passing that gate is the owner's, in triage.
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

Take the parts in the order the closeout section lists them. Mark each `[x]` when
its evidence holds, with a short note: what was run and its result, or what was
decided and why. Never delete or rewrite a completed task; amend it with a
correction note.

**Mechanical parts** — run them, fix what they report, and run them again:

- **Comment hygiene:** `make check-comment-hygiene`. It does not catch a comment
  naming the review or migration that introduced the code, so also read the
  comments the change added for that.
- **Documentation citations:** `make check-doc-citations CHANGE=<change>`. It must
  report nothing. Run it before archiving: an archived change's citations of its
  own unarchived path no longer resolve.
- **Packaging:** `make check-packaging`.
- **Agent skills:** `make check-agent-skills`.
- **Specifications:** `openspec validate <change> --strict` with the validator
  `openspec/README.md` pins.
- **Tests:** when closeout moved code — an import, a comment beside code — the
  suites covering it, and `make test`.

**Judgement parts** — do the work, and report each judgement in step 6:

- **Import placement.** Check each import the change added or touched for a reason
  to stay local, verified by attempting the move and reading the failure; move the
  rest and run the suites that cover them.
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
  dependency graph; remove the change from every other row's `Depends on`, and
  apply the dependency-landing rule to each dependent as
  `openspec/README.md#plan-closeout-requirements` part 6 states it. The status stays
  `in closeout`: `archived` is written when the change ships.
- **End-to-end pipeline.** Record the run the latest passing validation names, its
  result, and the scenarios that exercise the change, from the validation record's
  coverage section. When closeout changed code, that run no longer describes
  `HEAD`; say so, and tell the owner a validation of the closeout commit is owed
  before shipping.

A part that needs a decision the change does not make — an open question the plan
left to closeout, or a disposition the triage deferred to it — is put to the owner
in prose, with the options and your recommendation, and recorded in `design.md` when
decided. Never settle it yourself.

## 4. Promote, then archive

**Promotion.** Write every permanent document the closeout section names:
architecture companions, `ARCHITECTURE.md`, the other documents under `docs/`,
`openspec/specs/README.md`, and any `spec.md` content the deltas do not carry.
Describe the system as it is now, never the change that made it so. Complete the
design-promotion record in `design.md`: every accepted decision and its permanent
location, as a heading anchor where one exists. A `spec.md` the change's deltas
cover is written by the archive, not by hand; the record names it all the same.

**Archive** — the last change to the change's files. Check every closeout part is
checked first.

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
5. Run `openspec validate --specs --strict` with the pinned validator.

If the archive fails, nothing has moved: fix what it reports, or, when the fix is
not closeout's to make, stop and tell the owner.

## 5. Commit

Commit the closeout as one commit: the permanent documents, the archived change
with its `tasks.md` and promotion record, the merged specifications, and the index.
The message names the change and says it is closed out and archived. Do not push;
the closeout review reads the commit locally, and shipping pushes.

## 6. Report

Tell the owner:

- each closeout part, and for each mechanical one the check and its result;
- each judgement made and why: imports moved or kept, documents placed, notes
  compressed and what moved to `design.md`, the roadmap and index edits, and the
  dependents whose status changed;
- the permanent documents written, and the specifications the archive merged or
  skipped and why;
- the pipeline evidence, and whether a validation of the closeout commit is owed;
- what comes next: the closeout review (`make review CHANGE=<change>
  KIND=closeout`), which reads the archived change, then its triage in a fresh
  session (`make triage CHANGE=<change>`); the gate passing ships the change.
