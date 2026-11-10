## Why

The merge step brings the branch a change lands on into the change's branch once the
pre-closeout triage advances it, so closeout and its validation see the change as it
will land (`openspec/specs/change-workflow/spec.md`, CW-hdxi). Five steps follow that
merge before the change's pull request can merge: closeout, the closeout review, its
triage, any further closeout review rounds, and archive cleanup. The landing branch
keeps moving while they run, and, once archive cleanup has pushed, while the pull
request waits. When the pull request then conflicts with its base, the workflow has
no step to resolve it:

- the merge is refused for an archived change: its entry guard is the archive's
  absence (CW-xo82);
- archive cleanup exits to `done`, which has no exits and which no direction
  reaches (CW-9tzd), and the next-step computation answers `done` for any archived
  change whose row says `archived` before it reads the log;
- merging the landing branch "at other times" through the orchestrating session
  sends code conflicts to an implementation run, which an archived change refuses
  too, and has no review of what the resolution did.

So a conflict found after archival is resolved off the workflow, with no record in
the change's log, no validation of the merged `HEAD`, and no review of the
resolution. A late merge's resolution can be the most complicated work on the
branch: the landing branch has meanwhile landed other changes that promoted into the
same specifications and permanent documents this change promoted into, and its own
archived deltas are already merged into `openspec/specs`.

## What Changes

- A merge after the archive (`late-merge`): a node of the graph whose run is the
  `merge` step, with the same skill, mechanics, permissions, and Make target as the
  merge before closeout — fetch, resolve every conflict, reconcile the change's code
  with what the landing branch changed, run the checks, conclude, push. It is entered
  once archive cleanup has run, by the owner's direction through the orchestrating
  session, or by archive cleanup's first exit (below) (design D1).
- A new review kind, `merge`, with its own triage, reading each resolution against
  both parents, the specifications and indexes both changes promoted into, and the
  change's code and scenarios against what the landing branch changed (D2).
- The merge judges, on written criteria, whether its resolutions need that review,
  and the orchestrating session follows its exit without asking the owner (D3).
- The merged `HEAD` validated before the review or archive cleanup, a failed
  validation sending the change back to the merge for repair, as before closeout
  (D6).
- The merge review's triage advances to archive cleanup, which, run on an archived
  row, cleans up what validation left, commits what that wrote, pushes, copies the
  history, and exits to `done`. The owner directs another merge after the archive
  when the landing branch moves again (D4).
- Each finished merge, and archive cleanup, records in its outcome the remote, landing
  branch, and commit it fetched, which the engine checks (D10). A merge started without
  a branch brings in the one the last merge recorded. Archive cleanup fetches the
  source the last finished merge recorded, and its first exit to `done`, before the pull request opens, is
  guarded in the engine by whether the run's commit contains the fetched commit, as
  the log's writer recorded it, its remedy the merge after the archive (D5).
- The next-step computation reads the route for an archived change, answering `done`
  only while the route ends there, computes a change with a clone in its clone first,
  and answers `done` before any check of the branch checked out (D5).
- The archive stays a boundary nothing crosses backwards: no step after it returns
  the change to design, planning, or implementation, and the change's row stays
  `archived`; a dependent row the landing branch brings is released, and the pull
  request's drafts are appended to, never redrafted (D7, D8).

## Capabilities

### Modified Capabilities

- `change-workflow`: the graph (the `late-merge` node, the `merge` review kind and its
  triage, the guard on archive cleanup's first exit), the archive guard (CW-xo82), the
  terminal node (CW-9tzd), the merges' validation (CW-tnp6), and new requirements for
  the merge after the archive, its review, archive cleanup's rerun, and the
  computation's answer for an archived change.

### New Capabilities

None.

### Public interfaces

- The graph's vocabulary gains the node `late-merge`, the review kind `merge`, and the
  triage of that kind: compatible, since a reader that does not know them names them
  and routes on nothing (CW-9fbu).
- `next`'s output for an archived change may name a step — the merge, the merge
  review or its triage, a validation, archive cleanup — or the change's clone, where it
  always named `done`: incompatible for a caller that treated an archived change as
  done, counted minor while the major version is 0 (CW-c2tw). The orchestrating session
  is the caller, and changes with it.
- `start merge`, and so `make merge`, accepts an archived change: compatible, a
  refusal lifted. Given no `FROM`, it brings in the branch the last finished merge
  recorded before the one the change's clone recorded, and refuses only with neither
  (D10, CW-s3ju modified): compatible for a change with no recorded merge; for a merge
  repeated after one given another branch, which now brings in that branch rather than
  the clone's, incompatible, counted minor while the major version is 0 (CW-c2tw). The
  orchestrating session is the caller, and changes with it, passing `FROM` only when
  the owner names another branch.
- Archive cleanup's exit to `done` gains a guard on its first run: a behaviour of the
  graph's table, reading only the log line, so a line written before this engine reads
  as checked.
- The step outcome (`.agents/change-outcome.schema.json`) gains an optional `landing`
  object, `{"remote", "branch", "commit"}`, its form checked by the outcome check; the
  log's writer requires it on a merge's `finished` outcome — but a repair of a merge
  logged before the field — and on a finished archive cleanup line whenever a source
  resolves, checks it against the checkout's remotes and `HEAD`, and records on
  cleanup's line the containment (D10). Reading it is compatible: every existing line keeps its meaning without the
  field. Writing it is incompatible, counted minor while the major version is 0
  (CW-c2tw): a merge skill that does not record `landing` can no longer record a
  finished merge, and an engine that predates the field refuses an outcome carrying
  it. In this repository the schema, the skills, and the engine change in one commit.
- Every existing outcome and log line keeps its meaning.

## Non-Goals

- Do not merge the pull request, or change how it is merged.
- Do not reopen an archived change's design, plan, or implementation, or move its
  row off `archived`.
- Do not change the merge before closeout, beyond what sharing its skill and
  requirements with the merge after the archive requires, and the landing record its
  outcome gains so archive cleanup can tell which branch it brought in (D10).
- Do not detect, after the pull request opens, that the landing branch has moved:
  nothing runs after `done`, and the owner directs the merge then.

## Impact

- `scripts/change_workflow/graph.py` (the node, the review kind and its triage, their
  exits, guards, and entry guards, and the guard on archive cleanup's exit),
  `scripts/change_workflow/next_step.py` (the run rule, the route for an archived
  change, the order of locating), `scripts/change_workflow/review.py` (the merge kind's
  archive check), `.agents/change-outcome.schema.json`,
  `scripts/change_workflow/outcome.py` and `log.py` (the `landing` record, its check,
  and the containment recorded on cleanup's line), `scripts/change_workflow/cli.py`
  (`start merge`'s branch), and their tests.
- `.agents/skills/change-merge`, `change-review`, `change-triage`,
  `change-archive-cleanup`, and `change-orchestrate`.
- The `change-workflow` specification, its `index.md`, `README.md`, and graph
  diagram, and `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- None blocking. `workflow-round-review-without-merges` also concerns merges of the
  landing branch, inside a round rather than after the archive; the two do not
  overlap.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` (spec, index, README,
      graph diagram)
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 — the merge after the archive as a node running the merge step: `change-workflow`
  `spec.md` (CW-m4qe) and `index.md`; the companion `README.md` ("The merge before
  closeout" and the archive boundary) and its graph diagram;
  `docs/agents/change-workflow.md` (the skills table and directing a change).
- D2 — the `merge` review kind and its triage: `spec.md` (CW-r2hu, CW-xo82),
  `index.md`, `README.md`, the graph diagram, and `docs/agents/change-workflow.md`.
- D3 — the merge judges its review, followed without the owner's confirmation:
  `spec.md` (CW-x9tb) and `README.md`, with the principle that a step's judgement of
  its exit is followed unless the exit needs a waiver.
- D4 — the triage advances to archive cleanup's rerun, which ends at `done`:
  `spec.md` (CW-r2hu, CW-p8fy, CW-9tzd), `README.md` ("History lives in the owner's
  workspace"), and `docs/agents/change-workflow.md`.
- D5 — archive cleanup's first exit detects an advanced landing branch, the owner
  directs otherwise, and the computation answers `done` from the route: `spec.md`
  (CW-5vkd, CW-j7wp, CW-9tzd) and `README.md`, with the principle that detection runs
  by itself only where nothing it moves is under the owner's review.
- D6 — the merged `HEAD` validated: `spec.md` (CW-tnp6) and `README.md`.
- D7 — the archived change's files resolved so it stays archived: `spec.md`
  (CW-g3zn) and `docs/agents/change-workflow.md`.
- D8 — no return crosses the archive: `spec.md` (CW-xo82) and `README.md` ("The
  archive is the boundary no direction crosses").
- D10 — the merges and archive cleanup record the landing branch they fetched:
  `spec.md` (CW-5vkd, CW-s3ju) and `index.md`, `README.md` (the outcome and the log,
  and "The merge before closeout"'s paragraph on which branch a change lands on), and
  `docs/agents/change-workflow.md` (the merge's outcome and `make merge`'s branch).
- D9: no permanent destination — the implementation cadence is this change's
  history.
