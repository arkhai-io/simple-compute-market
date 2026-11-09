## ADDED Requirements

### Requirement: CW-m4qe An archived change's branch merges its landing branch again

The merge after the archive MUST bring the branch the change lands on, or the one the
owner names, into an archived change's branch, resolving and reconciling as the merge
before closeout does (CW-hdxi). It MUST be entered only once archive cleanup has run,
by the owner's direction or archive cleanup's exit guard (CW-5vkd), and MUST declare
no return. A `merge` run logged after an `archive-cleanup` run MUST be read as its run.

#### Scenario: The owner directs a merge after the archive

- **WHEN** an archived change's pull request conflicts with the branch it lands on,
  and the owner tells the orchestrating session to merge that branch again
- **THEN** the owner's direction to `{"step": "late-merge"}` is recorded, the
  computation names the merge, and the merge runs on the archived change

#### Scenario: A merge after the archive is directed before archive cleanup

- **WHEN** the owner directs `{"step": "late-merge"}` while the change's closeout
  review awaits triage
- **THEN** the log's writer refuses the direction, naming the entry guard that
  archive cleanup has run

#### Scenario: The landing branch has gained nothing

- **WHEN** a merge after the archive fetches the branch the change lands on and finds
  no commit `HEAD` lacks
- **THEN** it merges nothing and names archive cleanup, and `HEAD` and its validation
  stand

### Requirement: CW-x9tb The merge after the archive judges its review

The merge after the archive MUST judge whether its resolutions need a merge review,
against written criteria: a conflict resolved outside the mechanical files, a
reconciliation of the change's code or scenarios, a file both sides changed since the
merge base, or a contract the landing branch changed in meaning. It MUST name the
merge review or archive cleanup as its exit, which the orchestrating session MUST
follow without asking the owner. The owner's waiver of the merged `HEAD`'s validation
MUST be a direction to the exit the merge named, so that a merge review it named is
not skipped with the validation; skipping that review too MUST be a direction to
archive cleanup whose reason says it skips both.

#### Scenario: Both changes edited one specification

- **WHEN** the landing branch and the change each changed one `spec.md` since their
  merge base, and Git merged it without a conflict
- **THEN** the merge names `{"step": "review", "kind": "merge"}`, and the
  orchestrating session runs that review once the merged `HEAD` is validated

#### Scenario: Only the change index conflicted

- **WHEN** the merge's only conflict was a row of the change index, and it reconciled
  nothing
- **THEN** it names archive cleanup, and the orchestrating session asks the owner
  nothing

#### Scenario: The owner waives only the validation of a merge that named its review

- **WHEN** the merge after the archive named `{"step": "review", "kind": "merge"}`,
  and the owner waives the validation of the merged `HEAD`
- **THEN** the owner's direction names the merge review, and the computation names
  that review, not archive cleanup

### Requirement: CW-r2hu A merge review reads what a merge after the archive did

A review of kind `merge` MUST read the merge after the archive: each conflict's
resolution against both parents, each permanent specification and index it touched
for both changes' meaning, and the change's code and end-to-end scenarios against
what the landing branch changed. Its triage MUST advance to archive cleanup, once a
fix outside the inert paths is validated, or name another merge review, and MUST
declare no return.

#### Scenario: A merge review's triage commits a code fix

- **WHEN** a merge review's triage commits a fix to the change's code and names
  archive cleanup
- **THEN** the computation names a validation of `HEAD` with archive cleanup as its
  target, and archive cleanup once it passed

#### Scenario: A merge review is directed for a change not archived

- **WHEN** the owner directs `{"step": "review", "kind": "merge"}` for a change in
  implementation
- **THEN** the log's writer refuses it, naming the archive entry guard

### Requirement: CW-5vkd Archive cleanup's first exit waits for the landing branch

Each merge's outcome, before closeout and after the archive, MUST record as
`landing` the branch it fetched and the commit it fetched, and the log's writer MUST
refuse a merge's line whose `landing` is absent, malformed, or names a commit the
run's `HEAD` does not contain. Archive cleanup MUST fetch the branch the last merge's
`landing` names, else the branch the change's clone recorded (CW-s3ju), and MUST
record what it fetched as its outcome's `landing`, the log's writer recording whether
the run's commit contains it. Archive cleanup's first exit to `done` MUST be guarded
by that recorded result, the guard's remedy the merge after the archive; a later exit
MUST NOT be. The guard MUST read only the log, so that no fetch after the line was
written changes it and the computation reads nothing over the network. An archive
cleanup line with no `landing` MUST be read as checked.

#### Scenario: The landing branch moved during closeout

- **WHEN** archive cleanup first ends finished naming `{"step": "done"}`, and the
  commit its `landing` records is not contained in the run's commit
- **THEN** the computation names the merge, carrying `done` as its target, and the
  orchestrating session runs it without asking the owner

#### Scenario: The landing branch moves after the pull request opened

- **WHEN** archive cleanup's first run recorded a `landing` commit its commit
  contains, and a later fetch moves the landing branch's ref while the pull request
  is open
- **THEN** the computation still names `done`, and the owner directs a merge when
  they want one

#### Scenario: The landing branch moved after a merge after the archive

- **WHEN** archive cleanup ends finished after a merge after the archive, and the
  branch the change lands on has gained a commit since that merge
- **THEN** the computation names `done`, and the owner directs another merge when
  they want one

#### Scenario: A change archived before the record existed

- **WHEN** an archived change's log ends at an archive cleanup line with no `landing`,
  and its landing branch has moved on since
- **THEN** the computation names `done`

#### Scenario: The merge before closeout was given another branch

- **WHEN** a change's clone recorded `dev`, the merge before closeout was given
  `FROM=main`, and archive cleanup runs
- **THEN** archive cleanup fetches `main`, the branch the merge's `landing` names

#### Scenario: A merge's outcome records no landing branch

- **WHEN** a merge's outcome has no `landing`, or one whose commit `HEAD` does not
  contain
- **THEN** the log's writer refuses the line, naming the field

### Requirement: CW-p8fy Archive cleanup run again cleans up and copies only

Archive cleanup run on a change whose index row already says `archived` MUST NOT
release dependents, edit the row, or draft the pull request again. It MUST run the
cleanup of every validation part, commit any tracked file that cleanup wrote, push,
and copy the history, and MUST record what the cleanup reported by appending to the
pull request's drafts.

#### Scenario: Archive cleanup follows a merge after the archive

- **WHEN** a merge after the archive's validation recreated the change's validation
  resources, and archive cleanup runs again
- **THEN** the resources are removed, any capacity figure the cleanup recorded is
  committed on its own, the history is copied, and the row and dependents are
  untouched

### Requirement: CW-j7wp The computation answers done from the route

For an archived change, the next-step computation MUST read the workflow log's route,
and answer `done` only while that route ends at archive cleanup's exit to `done`, or
the change has no log or no index row; a direction or exit logged after it MUST be
followed. A change worked in its own clone MUST be named to its clone before `done` is
answered. `done` MUST be answered before any check of which branch this checkout has
checked out, and only a route with a step to run MUST go on to those checks.

#### Scenario: The owner's direction follows done

- **WHEN** archive cleanup's run named `done`, and a later line records the owner's
  direction to `{"step": "late-merge"}`
- **THEN** the computation names the merge, not `done`

#### Scenario: An archived change in its clone is computed in the workspace

- **WHEN** the computation runs in the owner's workspace for an archived change whose
  clone still exists
- **THEN** it names the clone, where the change's log is current, rather than `done`

#### Scenario: An archived change without a clone, another branch checked out

- **WHEN** the computation runs in the owner's workspace, with another branch checked
  out, for an archived change with no clone whose records the workspace holds and
  whose route ends at archive cleanup's exit to `done`
- **THEN** it names `done`, not the owner

#### Scenario: A merge after the archive directed without the branch

- **WHEN** the owner directs `{"step": "late-merge"}` for an archived change with no
  clone, and the workspace has another branch checked out
- **THEN** the computation names the owner, until the change's branch is checked out
### Requirement: CW-g3zn A merge after the archive keeps the change archived

The merge after the archive MUST keep the change's index row `archived` and its
archived directory as its branch has them, MUST release any row the landing branch
brought that depends on the change, as archive cleanup does, and MUST record what it
merged and how it was validated by appending to the pull request's drafts, never
rewriting them.

#### Scenario: The landing branch brought a dependent

- **WHEN** the landing branch brought a change's row whose `Depends on` names the
  archived change
- **THEN** the merge removes the change from that row's `Depends on`, and sets a
  status of `ready for planning`, `in planning`, or `ready for implementation` to
  `ready for design`

## MODIFIED Requirements

### Requirement: CW-tnp6 A round and the merge advance only on a passed validation

An implementation round, the merge before closeout, and the merge after the archive
MUST advance only on a `passed` validation naming its final commit, or a commit from
which it differs only in changes' records or, for a merge's advance to closeout or to
archive cleanup, only in inert paths. An `inconclusive` validation MUST be brought to
the owner, and a `failed` validation of a merged `HEAD` MUST name the merge that made
it again, which repairs what it found or asks the owner.

#### Scenario: A validation of the merged HEAD fails

- **WHEN** the merge named closeout or a pre-closeout review, and the validation of
  the merged `HEAD` failed
- **THEN** the computation names the merge, carrying the exit it named, so the merge
  repairs what the validation found
- **AND** an `inconclusive` validation of the merged `HEAD` names the owner

#### Scenario: A validation of HEAD merged after the archive fails

- **WHEN** the merge after the archive named archive cleanup or a merge review, and
  the validation of the merged `HEAD` failed
- **THEN** the computation names the merge after the archive, carrying the exit it
  named, so it repairs what the validation found

#### Scenario: A round's validation is inconclusive

- **WHEN** an implementation round's triage named the plan's next round and the fix
  commit's validation is `inconclusive`
- **THEN** the computation names the owner, with the next round as the target, not
  the next round

### Requirement: CW-xo82 The archive guards both sides of closeout

The change's archive MUST be an unwaivable entry guard of the closeout review, its
triage, archive cleanup, the merge after the archive, the merge review, and its
triage, and its absence one of design, planning, implementation, and the merge before
closeout. Closeout MUST be reached by a step's exit only from the merge before
closeout.

#### Scenario: A step's exit meets an unmet entry guard

- **WHEN** closeout ends finished naming `{"step": "review", "kind": "closeout"}`,
  and the change's directory is not under the archive
- **THEN** the computation names the owner, with the exit and the entry guard, and
  no closeout review

#### Scenario: The owner directs implementation of an archived change

- **WHEN** a merge after the archive found a conflict it cannot resolve so that both
  sides hold, and the owner directs `{"step": "round"}`
- **THEN** the log's writer refuses the direction, naming the entry guard, and the
  merge's question stays with the owner

### Requirement: CW-9tzd Archive cleanup ends at the terminal node

Archive cleanup's exit MUST be the terminal node `done`, which has no exits and no
step, and which no direction reaches. An archived change MUST stay at `done` until the
owner directs the merge after the archive, or archive cleanup's first exit is guarded
to it (CW-5vkd).

#### Scenario: Archive cleanup finishes

- **WHEN** archive cleanup ends finished, naming `{"step": "done"}`, and the run's
  commit contains the landing commit its outcome recorded
- **THEN** the computation names `done`, with the reason `archived`, and no step runs

#### Scenario: The owner directs done

- **WHEN** the owner directs `{"step": "done"}`
- **THEN** the log's writer refuses the direction, since only archive cleanup's exit
  reaches `done`
