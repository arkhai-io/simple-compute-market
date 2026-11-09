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

- An optional merge after the archive: on the owner's direction, a merge of the
  landing branch into an archived change's branch, with the same mechanics as the
  merge before closeout — fetch, resolve every conflict, reconcile the change's code
  with what the landing branch renamed or removed, run the checks, conclude, push.
- A review and triage loop over that merge's resolutions, so a resolution is read by
  a reviewer before the pull request merges.
- The merged `HEAD` validated before the loop ends, a failed validation sending the
  change back to the merge for repair, as before closeout.
- The loop repeats as often as the landing branch moves: it ends only when a merge
  finds nothing new to bring in, and the owner may start it again whenever the pull
  request conflicts again.
- The next-step computation follows this loop for an archived change instead of
  answering `done` unconditionally, and `done` is reached again when the loop ends.
- The archive stays a boundary nothing crosses backwards: no step after it returns
  the change to design, planning, or implementation, and the change's row stays
  `archived`.

## Open questions for design

Each with the proposer's recommendation.

1. **One node, or a kind of merge.** The graph keys a node by its step and kind.
   The late merge could be a new step, or a second kind of `merge`, the existing
   one becoming the merge before closeout. *Recommendation:* a kinded `merge` node,
   reusing the `change-merge` skill with a section for the archived case. The
   mechanics are the same; the entry guard (archived), the resolution rules for the
   archived change's own documents, and the exits differ.
2. **Is the review always run, or judged.** The merge before closeout judges whether
   its resolutions merit another review, and the owner confirms one. After the
   archive no closeout review follows to catch a mistake. *Recommendation:* the
   merge judges, as before closeout, but a conflict resolved in code, tests,
   configuration, or a permanent document or specification always merits the
   review; only a merge whose conflicts were the index, locks, and version bumps
   may skip it, with the owner's confirmation.
3. **Which review kind.** The closeout review reads the archive and the promoted
   documents; the late merge's review should read what the merge did: each
   resolution against both parents (`git show --remerge-diff`) and each
   reconciliation commit. *Recommendation:* a new review kind for the late merge,
   with its own triage, whose advancing exit returns to the merge, which advances
   only when the landing branch has gained nothing since — the same pattern as the
   review of the merge before closeout.
4. **How the loop ends.** Archive cleanup's last act copies the change's records
   into the owner's workspace; a late merge adds records in the clone after that
   copy, and may make its pull-request drafts stale. *Recommendation:* the loop's
   last step runs the history copy again (it is safe to repeat) and exits to
   `done`; archive cleanup is not re-entered, since its release of dependents and
   its row edit are already done.
5. **Starting it.** The loop is optional. *Recommendation:* the owner's direction
   starts it (`make merge CHANGE=<change>` on an archived change, `FROM` as today),
   and the computation never names it by itself; `done` stays the answer for an
   archived change with no late merge in progress.
6. **Validation waiver.** *Recommendation:* as before closeout: the merged `HEAD`
   is validated, inert paths exempt, unless the owner waives it.

## Capabilities

### Modified Capabilities

- `change-workflow`: the graph (a merge node entered after the archive, its review
  kind and triage), the archive guard (CW-xo82), the terminal node (CW-9tzd), the
  next-step computation's answer for an archived change, the merge's requirements
  (CW-hdxi, CW-a6ow, CW-tnp6), and the history copy (CW-hak6).
- `market-change-workflow`: only if this repository's step table or make fragment
  needs a new entry for the review kind.

### New Capabilities

None.

### Public interfaces

The step graph gains a node and a review kind, and `done` is no longer final for
an archived change. A step outcome naming the new target is new vocabulary; every
existing outcome and log line keeps its meaning, so the change is compatible for
records already written.

## Non-Goals

- Do not merge the pull request, or change how it is merged.
- Do not reopen an archived change's design, plan, or implementation, or move its
  row off `archived`.
- Do not change the merge before closeout, beyond what sharing its skill and
  requirements with the late merge requires.
- Do not make the computation detect a conflicting pull request by itself.

## Impact

- `scripts/change_workflow/graph.py` (node, exits, entry guards),
  `scripts/change_workflow/next_step.py` (the archived-change shortcut),
  `scripts/change_workflow/review.py` and the step table for the new review kind,
  and their tests.
- `.agents/skills/change-merge`, `change-review`, `change-triage`, and
  `change-orchestrate`.
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

To be determined at design completion.
