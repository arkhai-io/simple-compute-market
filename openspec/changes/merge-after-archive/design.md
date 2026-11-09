## Context

The merge step brings the branch a change lands on into the change's branch once the
pre-closeout triage advances it (CW-hdxi). Closeout, the closeout review, its triage,
and archive cleanup follow, and the pull request then waits for the owner. The
landing branch keeps moving throughout. When the change's branch then conflicts with
it, or has fallen behind it, nothing in the workflow can bring it in:

- `merge` carries the entry guard `NOT_ARCHIVED` (`scripts/change_workflow/graph.py`),
  and `start` refuses it for an archived change before it begins (`cli._takes`, since
  every node of the step carries that guard);
- the next-step computation answers `done` for an archived row before it reads the
  log, in `Computation.run` and again in `Computation.route`, and `done` has no exits
  and refuses every direction (`NEVER_DIRECTED`);
- the orchestrating session's other way of merging the landing branch, as workflow
  maintenance, sends code conflicts to an implementation run, which an archived
  change refuses too, and validates nothing.

The owner runs several changes on one roadmap goal in parallel, so a merge after the
archive routinely meets conflicts in `openspec/specs/` and the permanent documents
both changes promoted into, and in code — one change moving code into a kit while
another patches the code that moved. The archived change's own deltas are already
merged into `openspec/specs/`, so the resolution edits permanent specifications that
no later step reads.

### Corrections to the proposal

The design discussion found these against the code and the change's own documents:

1. The review of the merge before closeout is not a kind of its own: it is the
   `pre-closeout` review with one added question, asked when the last run before it
   is a `merge` run (`change-review`, pre-closeout question 5).
2. `kind` qualifies only reviews and triages: `node_of` refuses a kind on any other
   step, and every `{"step": "merge"}` already in a change's log would be refused once
   `merge` needed one, unless a kindless merge kept a meaning of its own.
3. Archive cleanup already runs again on a row that says `archived`, skipping the
   release of dependents, the row, its commit, and the drafts, and repeating its
   validation cleanup, the commit of what that wrote, the push, and the history copy.
   A merge after the archive's validation recreates the validation resources that
   cleanup removed, so the history copy alone cannot end the loop.
4. The history copy already repeats at `done` and at clone removal (CW-hak6), and
   anticipates records written after archive cleanup. The copy refuses a file that
   changed other than by growing (CW-rf50), so `reviews/pull-request.md` is appended
   to after the archive, never redrafted.
5. The merge skill sets the row to `ready for closeout` when it advances; that never
   applies after the archive.

## Decisions

### D1 — The merge after the archive is a node of its own that runs the merge step

The graph gains `late-merge`, a node whose run is logged as the `merge` step, as
`round` runs `implement`. It uses the merge step's skill, its row of the step table,
its Make target, its `from <branch>` argument, and its hook rights, unchanged. A
`merge` run logged after an `archive-cleanup` run is a run of `late-merge`: the rule
reads only the log, and holds because nothing returns an archived change to an
earlier phase. Since one node of the `merge` step no longer carries `NOT_ARCHIVED`,
`start` stops refusing `merge` for an archived change by itself; the skill's own
route check refuses a run the computation does not name. The node's entry guards are
the archive and that archive cleanup has run. Its exits are the merge review and
archive cleanup (D3, D4); it declares no return (D8). The owner starts it by telling
the orchestrating session, which records the direction, rather than by leaving the
session to run a separate target.

Rejected:

- **A new step, `late-merge`, with its own row and target.** Simple to route, but it
  copies the merge's permissions into a second row of the step table, adds a Make
  target, hook rights, argument handling, and a model entry, and would have the owner
  leave the orchestrating session to run it.
- **A kinded `merge`.** `kind` may qualify other nodes, but every existing
  `{"step": "merge"}` would need a rule that a kindless merge is the merge before
  closeout — a permanent special case in the vocabulary — or a conversion of every
  change's log, whose tooling is being retired.
- **One `merge` node with both sets of exits, sorted by the targets' entry guards.**
  The graph would declare exits that are wrong in every state the node can be in.
- **Un-archiving the change and returning it to implementation with a new task.** The
  archive's merge of the deltas into `openspec/specs/` cannot be reversed once the
  landing branch's changes are interleaved with it, archive cleanup's release of
  dependents would be undone or left wrong, the plan would gain a section after its
  closeout task, and the common, mostly mechanical merge would go through about ten
  steps whose resolution the merge has already made.
- **Doing nothing.** A conflict after the archive stays off the workflow, with no
  record, validation, or review.

### D2 — A new review kind, `merge`, reads the merge after the archive

The graph gains `review:merge` and `triage:merge`, each with the archive as its entry
guard, the triage also needing a review of its kind awaiting it. The reviewer reads
each conflict's resolution against both parents (`git show --remerge-diff`) and each
commit since the merge's first parent; whether each permanent `spec.md` and its
`index.md` say what both changes' deltas meant, with no requirement id duplicated or
dropped; whether the change's code still uses what the landing branch renamed,
removed, moved into a kit, or changed in meaning, its new callers moved where the
landing branch moved the others; and whether its end-to-end scenarios still match the
landing branch's harness. The kind comes from the table, so the review command, the
outcome check, and the log's writer accept it with no other list updated (CW-9fbu).

Rejected:

- **The closeout review with added questions,** following the pre-closeout precedent.
  It would give the closeout review, built to read documentation because closeout
  edits no code, a duty to read code; its own questions mostly do not apply to a
  merge; and its records would mean two things. With D4's advance going straight to
  archive cleanup, it would add no wrong exit, which narrowed the margin.
- **The pre-closeout review.** Its triage's exits lead to the merge before closeout,
  planning, and design, all wrong after the archive.
- **No review.** Conflicts in specifications and code are routine and substantive,
  and no later review reads them.

### D3 — The merge judges whether a review is needed, and the orchestrating session follows it

The merge after the archive judges whether its resolutions need the merge review and
names that exit or archive cleanup's; the orchestrating session follows it without
asking the owner, as it follows any exit. The skill writes the criteria the judgement
weighs: a conflict resolved outside the mechanical files — the change index, other
changes' documents, files the repository's hooks rebuild, version-only bumps, and a
file a validation part's cleanup writes; a reconciliation of the change's own code or
scenarios; a file both sides changed since the merge base, even where Git merged it
cleanly, since two changes' edits to one specification can merge into contradiction;
and a contract the landing branch changed in meaning.

Rejected:

- **Always review.** Spends a review and a triage on a merge whose only conflict is
  an index row.
- **The merge recommends and the owner confirms, as before closeout.** Given how
  often the review is warranted, the confirmation would be a stop with a foregone
  answer.
- **A fixed rule taken without judgement.** The written criteria guide the merge's
  judgement instead.

The merge before closeout keeps CW-a6ow's confirmation; the owner will try the
workflow before deciding whether it changes too.

### D4 — The merge review's triage advances to archive cleanup's rerun, which ends at `done`

`triage:merge` advances to archive cleanup, guarded by a fix outside the inert paths
being validated, or names another merge review, under the same guard. It does not
return to the merge: the owner reviews the branch before merging the pull request,
sees whether the landing branch has moved, and directs another merge after the
archive when it has. Archive cleanup, run on a row already `archived`, runs the
cleanup of every validation part, commits what that cleanup wrote, pushes, and copies
the history, then exits to `done` — so `done` is still reached only by archive
cleanup's exit. Its route check accepts `late-merge` and `triage:merge` as the ways
in.

Rejected:

- **The advance returns to the merge, which ends the loop only when the landing
  branch has gained nothing,** as the merge before closeout does. With the landing
  branch moving often, it goes round until the branch pauses; the owner watches the
  pull request instead.
- **The merge cleans up and copies the history itself, exiting to `done`.** It would
  give the merge the cleanup hook, duplicate archive cleanup's steps, and make `done`
  reachable by two steps.
- **No cleanup.** The validation namespace and images would stay up, the capacity
  figure stale, and the workspace's history waiting for clone removal.

### D5 — Archive cleanup's first exit detects an advanced landing branch; otherwise the owner directs

Archive cleanup fetches the branch the change's last merge brought in — the branch
the merge was given, or else the one the change's clone recorded (CW-s3ju). Its first
exit to `done`, the one before the pull request opens, is guarded by that branch
having gained nothing `HEAD` lacks (`git merge-base --is-ancestor`), the guard's
remedy `late-merge`; the computation then names the merge, carrying `done` as its
target, and the orchestrating session runs it without asking. A later exit is not
guarded. The guard reads the fetched ref, so the computation stays off the network.
After the pull request opens, the merge after the archive starts only by the owner's
direction to `{"step": "late-merge"}`, recorded by the orchestrating session on their
word.

For an archived change, the computation reads the route and answers `done` only while
it ends at archive cleanup's exit to `done`, following a direction or exit logged
after it. The check moves after the computation locates the change, so a change with
a clone is computed in the clone, where the owner's direction is written, rather than
answered `done` from the workspace's copy of its log. For `late-merge` the result
names the step to run, `{"step": "merge", …}`, the node in its reason, so the
orchestrating session's `make <step>` and the merge skill's route check work
unchanged.

Rejected:

- **The owner alone starts it, as the proposal's non-goal said.** A long closeout is
  when the landing branch gains the other changes on the owner's goal; a check before
  the pull request opens costs one fetch and moves nothing under the owner's review.
- **The same check on every exit to `done`.** It brings back the loop D4 declined,
  and stopping it would need a waiver of a node no direction reaches.
- **Detecting while the pull request is open,** by a poller or a trigger on pushes to
  the landing branch. Nothing runs after `done`; it needs infrastructure the workflow
  lacks and is tied to the hosting; and a merge started by itself would move the
  branch the owner is reviewing (Open Questions).
- **The result names `late-merge`,** leaving every caller to map it to `make merge`.

### D6 — The merged HEAD is validated, as before closeout

The merge after the archive's exit to archive cleanup is guarded by the merged `HEAD`
validated with the inert paths exempt, and its exit to the merge review by the merged
`HEAD` validated with records exempt. A failed validation names `late-merge`, which
repairs what it found; an inconclusive one names the owner. When the landing branch
gained nothing, nothing is merged, and `HEAD` and its validation stand. Only the
owner waives the validation: the merge may recommend a waiver on the guide's
"Waivers" criteria, never after reconciling the change's own code, and the waiver is
the owner's direction past the guard to archive cleanup.

Rejected: **no validation after the archive** — the end-to-end pipeline is the only
check that finds a stale call in a scenario.

### D7 — The archived change's own files are resolved so it stays archived

The merge after the archive resolves as the merge before closeout does, and also:

- the change index: this change's row from its branch, still `archived`, every other
  row from the landing branch; a row the landing branch brought whose `Depends on`
  names this change is released as archive cleanup releases a dependent, since
  archive cleanup's rerun does not;
- the archived change's directory as its branch has it;
- `openspec/specs/`, each `index.md`, and the permanent documents: both sides, every
  requirement saying what each change meant, ids unique, each change's index entries
  kept;
- `reviews/pull-request.md`, which is untracked and never conflicts: a note appended
  on what was merged and how it was validated, never a redraft;
- the validation capacity figure: the one measured later;
- the row's status is never set to `ready for closeout`.

Rejected: **a separate skill** — the merge skill gains a section for the archived
case (D1).

### D8 — No return crosses the archive

`late-merge` and `triage:merge` declare no return, and design, planning, and
implementation still refuse an archived change. Where a conflict cannot be resolved so
that both sides hold, or the landing branch has invalidated the change's design, the
merge asks the owner and leaves the merge in progress; the owner resolves it as they
direct, lands the change and follows up in a new change, or takes it off the
workflow. A merge review's finding that needs a code fix is fixed by its triage, as a
closeout triage's code correction is, and validated by D4's guard.

Rejected: **an owner-directed un-archiving return** — the archive's merge of the
deltas cannot be reversed (D1), and the case is rare.

### D9 — Implementation cadence

The change is implemented in one round of one session: the graph's node, review kind,
and guards; the computation's run rule, its reading of the route for an archived
change, and the order of locating; archive cleanup's fetch and exit guard; their
tests; the graph diagram; and the skills — `change-merge`'s section for the archived
case, `change-review`'s and `change-triage`'s for the merge kind,
`change-archive-cleanup`'s fetch and route check, and `change-orchestrate`. The
specification, its index, the companion README, and the workflow guide are promoted
at closeout.

Rejected: **two rounds,** the engine before the skills, which would have reviewed the
table before the skills name its vocabulary, at the cost of a second round.

## Implementation cadence

One round, one session, covering everything D9 lists, then closeout.

The `change-workflow` index's entries for the requirements this change adds, and its
revised summaries of those it modifies, were written with the design on the owner's
word: with a change named, the specification index check counts its deltas as
archived, so every step's pre-commit would otherwise fail until closeout. Closeout's
promotion checks and revises them rather than writing them.

## Principles stated in this design

Stated by the owner and recorded in no permanent document, for promotion to the
`change-workflow` companion README:

- A step's judgement of the exit it takes is followed without the owner's
  confirmation unless the exit needs a waiver.
- The owner instructs the orchestrating session, rather than leaving it to run a
  separate target.
- The graph declares no exit that is wrong in a state its node can be in.
- Detection runs by itself only where nothing it moves is under the owner's review.

## Open Questions

- **Noticing an advanced landing branch while the pull request is open.** Deferred:
  nothing runs after `done`, and a poller or a trigger on pushes to the landing branch
  is infrastructure a hosted runner would supply (`host-change-workflow-runner`).
  Revisit when that runner is designed, or if pull requests routinely wait long enough
  for the landing branch to move several times.
