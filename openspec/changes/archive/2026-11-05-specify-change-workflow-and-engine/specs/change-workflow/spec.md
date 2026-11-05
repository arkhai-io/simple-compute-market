## ADDED Requirements

### Requirement: CW-ab9h A change moves through four phases in order

A change MUST move through design, planning, implementation, and closeout, in that
order, except where the owner directs a step (CW-jtsl). A direction MUST NOT cross
the archive.

#### Scenario: The owner directs a change back to design

- **WHEN** the owner directs a change in implementation back to design
- **THEN** design runs next, and the change moves on from design through planning
  again

### Requirement: CW-nfdb A phase ends only when its review's triage advances it

The design phase MUST end with a design review, the implementation phase with a
pre-closeout review, and the closeout phase with a closeout review. A phase ending
in a review MUST NOT be treated as finished until that review has been triaged and
its triage's outcome names, as its exit, a step of the next phase; for the
implementation phase, the merge that precedes closeout.

#### Scenario: A design review's triage records another round

- **WHEN** a design review's triage names another design review as its exit
- **THEN** the change stays in design, and planning does not begin

### Requirement: CW-hdxi The merge brings in the branch the change lands on

Once the pre-closeout review's triage advances the change, a merge step MUST bring
into the change's branch the branch the change lands on: the branch it was branched
from unless the owner names another, or else the repository's default. It MUST
resolve the merge's conflicts and reconcile the change's own code with what that
branch changed, even where the merge reported no conflict, before closeout starts.

#### Scenario: The branch the change lands on renamed what the change calls

- **WHEN** the branch the change lands on renamed a function the change's code
  calls, and the merge reported no conflict
- **THEN** the merge step updates the change's call before closeout starts

### Requirement: CW-a6ow Closeout waits for a validation of the merged HEAD

Closeout MUST NOT start until a validation of the merged `HEAD` passed, unless the
owner waives it. The merge MUST judge whether its resolutions merit another
pre-closeout review and whether its validation may be waived, and MUST take either
only on the owner's confirmation; without either, it MUST advance to closeout
without waiting for the owner.

#### Scenario: The merge proposes another pre-closeout review

- **WHEN** the merge resolved a conflict in the change's own code by a decision,
  and the owner confirms the review it proposes
- **THEN** the merge names the pre-closeout review, which runs once the merged
  `HEAD` is validated, and that review's triage advances to the merge again

#### Scenario: The owner waives the merge's validation

- **WHEN** the owner, asked by the merge, waives the validation of the merged
  `HEAD`
- **THEN** the merge names closeout and the owner's direction to closeout is
  recorded, which checks no exit guard, so closeout starts unvalidated

### Requirement: CW-9pbk The owner is consulted at fixed touchpoints

The owner MUST be consulted for the design discussion's questions, for their notes
on each implementation round before its triage, for the disposition of every
finding, and for whether the dispositions merit another review round, which triage
MUST ask once every finding is disposed of and before any fix is made. Every other
transition MUST proceed without waiting for the owner, unless a step raises a
question only the owner can answer.

#### Scenario: Another round is decided before the fixes

- **WHEN** the owner has disposed of every finding of an implementation round
- **THEN** triage recommends whether the accepted fixes merit another review round
  and records the owner's answer before making any fix

### Requirement: CW-ksnu Closeout archives the change before its review

Closeout MUST archive the change, merging its specification deltas into the
permanent specifications, before its closeout review, and that review MUST read
the archived change and the permanent documents as archived.

#### Scenario: The closeout review reads the synchronized specifications

- **WHEN** a change's closeout review runs
- **THEN** the change is already archived, its deltas merged into
  `openspec/specs/`, and the review and its triage find the change and its records
  by name under the archive

### Requirement: CW-trdu Archive cleanup waits on the closeout review's triage

The archive MUST be cleaned up, and the change set `archived`, only once the
closeout review's triage records that the change advances and, when `HEAD` differs
from the commit that review read in a path outside `openspec/` and `docs/`, the
latest validation passed for `HEAD` or for an ancestor it differs from only in
records, unless the owner waives that validation, judging the paths named, and the
waiver is recorded in the intervention ledger.

#### Scenario: The owner waives archive cleanup's validation

- **WHEN** the only path outside `openspec/` and `docs/` changed since the closeout
  review's commit is another change's, on a branch the two changes share, and the
  owner judges it harmless
- **THEN** archive cleanup records the waiver as a line of the change's intervention
  ledger and goes on without a validation of `HEAD`

#### Scenario: The owner waives archive cleanup's validation under orchestration

- **WHEN** the next-step computation names validation before archive cleanup and
  the owner tells the orchestrating session they waive it, judging the paths named
- **THEN** the owner's word is recorded in the workflow log as a decision directing
  archive cleanup, the computation names archive cleanup until it has run, and
  archive cleanup's own check finds the direction in the log and records the waiver
  in the ledger, without asking the owner again

#### Scenario: A closeout review finds a code defect

- **WHEN** a closeout review's finding can only be fixed by changing code
- **THEN** the triage makes no code change and stops for the owner, and any
  correction the owner directs in that session is validated before archive cleanup

#### Scenario: A closeout correction awaits validation

- **WHEN** a closeout review's triage named archive cleanup and its correction
  changed a path outside `openspec/` and `docs/` since the reviewed commit
- **THEN** the computation names validation of `HEAD`, with archive cleanup as its
  target

#### Scenario: A documentation correction at closeout

- **WHEN** a closeout review's triage named archive cleanup and its correction
  changed only paths under `openspec/` and `docs/`
- **THEN** the computation names archive cleanup without a validation

### Requirement: CW-pkug Closeout changes documentation only

Closeout MUST change documentation only; a closeout part that would need a code
change MUST return the change to implementation.

#### Scenario: Closeout finds a comment that needs rewriting

- **WHEN** closeout's comment hygiene part finds a comment the change added that
  describes its history
- **THEN** closeout stops without editing it and the change returns to
  implementation for a fix round

### Requirement: CW-1iaz Steps after the archive find a change by name

The steps that follow the archive (the closeout review and its triage, validation,
the round view, the scoped citation check, and archive cleanup) MUST find an
archived change by its name. Design, planning, and implementation MUST refuse a
change that is archived, naming its archived directory.

#### Scenario: An archived change is given to implementation

- **WHEN** the owner asks to implement a change whose directory is under the
  archive
- **THEN** the request is refused, naming the archived directory

### Requirement: CW-z83w A design decision after the design review returns to design

Planning MUST NOT begin before the design review's triage records that the change
advances. A design decision made after that, such as one planning exposes, MUST
return the change to design; the owner MAY waive another design review for it, and
the waiver MUST be recorded in the intervention ledger.

#### Scenario: Planning exposes an unanswered design question

- **WHEN** planning finds a question the reviewed design did not answer
- **THEN** planning stops, the change returns to design, the owner's decision is
  recorded in the design, and planning resumes only after another design review's
  triage records that the change advances, or the owner's waiver of that review is
  recorded

### Requirement: CW-uj2q The step that makes a transition writes it to the index

Each change of a change's phase or state MUST be written to its row in the change
index by the skill that makes it, in the same step: the design discussion starting,
a triage recording that a phase-closing review's change advances, planning starting
and finishing, the first implementation section starting, the merge before closeout
advancing, closeout starting, and archive cleanup. An implementation review after a
section MUST NOT change the status.

#### Scenario: A closeout review's triage advances the change

- **WHEN** a change's closeout review's triage records that the change advances
- **THEN** triage leaves its index row `in closeout` and stops
- **AND** archive cleanup, run next in its own session, releases its dependents and
  sets its index row to `archived`

#### Scenario: A pre-closeout review's triage advances the change

- **WHEN** a change's pre-closeout review's triage records that the change advances
- **THEN** the triage step leaves the change's index row as it is, and the merge
  before closeout runs next
- **AND** the merge sets the row to `ready for closeout` when it advances to
  closeout with the latest validation passed for `HEAD`, and otherwise leaves it,
  closeout accepting the row as it stands once the computation names closeout

### Requirement: CW-jyff Every edit of the change index is checked

Each step that edits the change index MUST check it afterwards: every row has its
table's cell count; its link resolves to its change's directory, or to its archive
when it is `archived` or `in closeout`; its status is one the index defines; each
dependency names a listed change that is not archived; and every active change
directory has exactly one row. An archived change MAY have no row.

#### Scenario: An edit breaks a row

- **WHEN** a step edits the index and leaves a row linking a directory that does not
  exist, or depending on an archived change
- **THEN** the index check reports the row and its line, and the step does not
  proceed until it is fixed

#### Scenario: An archived change's row is pruned

- **WHEN** the index no longer lists a change archived some time ago
- **THEN** the index check passes, since only an active change needs a row

### Requirement: CW-3tvs Design and triage are conversations with the owner

Design MUST NOT run without the owner. Triage MUST bring every finding and every
point of the owner's notes to the owner, and MAY finish without the owner only when
there is none to dispose of. When orchestrated, each MUST run as its own resumable
session, presenting one decision or finding per turn, each of its messages shown to
the owner in the orchestrating session and the owner's reply resuming that session.

#### Scenario: A triage finding is presented

- **WHEN** an orchestrated triage presents a finding
- **THEN** the owner reads it in the orchestrating session, and the owner's
  disposition resumes the triage session

### Requirement: CW-p1us Planning asks the owner nothing

Planning MUST NOT ask the owner to accept the plan; a plan that needs a decision the
design does not make MUST return the change to design.

#### Scenario: A plan needs a decision the design does not make

- **WHEN** planning finds that a section needs a decision the design does not make
- **THEN** it proposes a return to design, and asks the owner neither that question
  nor to accept the plan

### Requirement: CW-dtpz A design blocked on a prerequisite ends blocked

When a design cannot proceed without another change, the design step MUST, with the
owner, define the prerequisite's requirements and initial proposal, and end
blocked. The prerequisite's proposal and index row MUST be written on a branch from
the development branch, never on the blocked change's branch, and MUST reach the
development branch before the prerequisite's workflow starts; the blocked change's
branch MUST receive them only by merging the development branch.

#### Scenario: A design needs another change first

- **WHEN** a design discussion finds it cannot proceed until another change lands
- **THEN** the design step writes, with the owner, the prerequisite's proposal and
  index row on a branch from the development branch, and ends with a blocked outcome
  naming the prerequisite

### Requirement: CW-p7xk A blocked design waits until its prerequisite is released

A blocked change MUST remain `in design`, with the prerequisite in its dependencies
gating design. Once the prerequisite is archived and its result is merged into the
blocked change's branch, the dependency MUST be released, on the owner's word,
before design resumes.

#### Scenario: A prerequisite has not landed

- **WHEN** a change `in design` depends, for its design, on a change that is not
  archived
- **THEN** the next-step computation names no step for it and reports that design
  waits on the prerequisite

#### Scenario: A prerequisite has landed

- **WHEN** a change `in design` depends, for its design, on a change now archived on
  its branch
- **THEN** the next-step computation names the release, and on the owner's word the
  dependency is dropped and the change stays `in design`

### Requirement: CW-jtsl The owner may direct a change to any node

The owner MAY direct a change to any node of the workflow graph, by a decision in
the workflow log naming its target as an outcome names an exit, with a reason
saying what any skipped check was; the decision MAY resolve the run waiting on it.
Only the owner MAY direct a step: the orchestrating session MUST NOT direct one of
its own accord, nor record a step's exit on its behalf.

#### Scenario: The orchestrating session directs a step

- **WHEN** a decision line by the orchestrating session directing a review is
  attempted
- **THEN** the log's writer refuses it, since a direction is the owner's

#### Scenario: Closeout finds a design defect before the archive

- **WHEN** closeout, before archiving the change, finds that a design decision
  contradicts a permanent requirement, and the owner directs the change back to
  design
- **THEN** the computation names design, and the design step sets the status
  `in design` as it starts

### Requirement: CW-zcx8 A directed step is named until it runs

The computation MUST name a directed step until a later run of it is logged,
checking no exit guard, and the step MUST set its own status as it starts.

#### Scenario: The owner directs a repeat review

- **WHEN** the owner asks the orchestrating session for a pre-closeout review
  again outside a triage, recorded as
  `{"seq": 61, "step": "orchestrator", "outcome": "orchestrator", "by": "owner", "next": {"step": "review", "kind": "pre-closeout"}, "decision": "review again", "reason": "the reviewer should see the triage"}`,
  naming no run, since no run waits on it
- **THEN** the next-step computation names the pre-closeout review until it has run

#### Scenario: The owner waives archive cleanup's validation by a direction

- **WHEN** the computation names a validation before archive cleanup, and the owner
  directs archive cleanup, the reason saying the validation is waived
- **THEN** the computation names archive cleanup, and archive cleanup, finding the
  direction in the log, records the waiver in the intervention ledger

### Requirement: CW-uhdy A direction is held to the unwaivable entry guards it meets

A direction MUST be refused, naming the guard, while an unwaivable entry guard of a
node it names is not met: its target, and the target nested in a direction to
validation. An archived change MUST NOT be directed to design, planning, or
implementation, nor a change not archived to the closeout review, its triage, or
archive cleanup. A waivable entry guard, and the directed step's own entry check
for it, MUST accept the direction as its override.

#### Scenario: An archived change is directed to design

- **WHEN** a direction of an archived change to design is attempted
- **THEN** the log's writer refuses it, naming the archive

#### Scenario: A change not archived is directed to archive cleanup

- **WHEN** a direction to archive cleanup of a change whose directory is not under
  the archive is attempted
- **THEN** the log's writer refuses it, naming the missing archive

#### Scenario: The owner directs a pre-closeout review over a failed validation

- **WHEN** the latest validation of `HEAD` failed, and the owner directs a
  pre-closeout review
- **THEN** the computation names the pre-closeout review, and the review starts,
  taking the direction as its override of the validation check

#### Scenario: A triage is directed with nothing to triage

- **WHEN** a direction to `{"step": "triage", "kind": "design"}` is attempted and
  every design review has its triage
- **THEN** the log's writer refuses it, naming the entry guard

### Requirement: CW-eups A direction to validation names the validation's target

A direction to validation MUST name, nested in its target, the target the
validation is for, and validation's entry guard MUST refuse one without it. A
directed validation that passed MUST lead to its target, whose entry guards are
checked; one that failed or was inconclusive MUST be brought to the owner.

#### Scenario: The owner directs a validation before closeout

- **WHEN** the owner directs `{"step": "validate", "target": {"step": "closeout"}}`,
  and the validation passes, naming closeout as its exit
- **THEN** the computation names validation with closeout as its target, and then
  closeout; had the validation failed, it would name the owner

#### Scenario: A validation is directed without a target

- **WHEN** a direction to `{"step": "validate"}` naming no target is attempted
- **THEN** the log's writer refuses it, naming validation's entry guard

#### Scenario: A directed validation could never reach its target

- **WHEN** a direction to
  `{"step": "validate", "target": {"step": "archive-cleanup"}}` of a change whose
  directory is not under the archive is attempted
- **THEN** the log's writer refuses it, naming the missing archive, and no
  validation runs

### Requirement: CW-5r7l A section is a verifiable slice

Each `tasks.md` section MUST be a coherent slice that can be verified, sized by
what it changes and what proves it, and MUST end at a verification point. The plan
MUST NOT prescribe in `tasks.md` how sections are distributed across agent sessions
or review rounds.

#### Scenario: Planning writes a section

- **WHEN** planning writes a section of the task list
- **THEN** the section ends with a verification task naming the evidence that
  proves it, and the task list names no session or round

### Requirement: CW-5h8e Evidence only a push produces is owed by validation

A section's verification MUST name only evidence an implementation session can
produce. Evidence only a push produces MUST be named as owed by validation, as the
repository's validation part that produces it identifies it, and MUST NOT gate a
task's completion. A session that finds such evidence in a verification MUST check
the task once its own evidence passes and name that evidence as owed by validation
in the section's notes.

#### Scenario: A section owes CI evidence

- **WHEN** a section's change can be shown only by a run of a CI workflow, which no
  push of the change's branch triggers
- **THEN** the plan names the workflow, the job, and what it must show as owed by
  validation, and the section's verification task is checked on its local evidence
  alone

#### Scenario: An older plan gates a task on a CI run

- **WHEN** an implementation session's verification task asks for a CI run of the
  pushed branch
- **THEN** the session checks the task once its own evidence passes and names the
  CI run as owed by validation in the section's notes, and the next-step computation
  does not name the section again

### Requirement: CW-0ia3 An implementation session starts fresh unless the owner continues one

A session implementing sections MUST begin with no prior conversation and read the
repository's guidance documents, the change, and its sections, unless the owner
directs the work to an implementation session of the change named by its id, one
not waiting on the owner. That session MUST continue on the model it ran on,
reading the change's files again where they may have changed, and the orchestrating
session MUST continue it only on the owner's word.

#### Scenario: The owner sends the next section to a finished session

- **WHEN** the session that implemented section 2 finished, and the owner directs
  section 3 to it
- **THEN** the orchestrating session runs `scripts/change-workflow start implement
  <change> --unattended --sections 3 --session <its session>`, through the
  repository's convenience target where it has one, the wrapper continues that
  session on its model, and the run's log line names the run it continues; a
  session that waits on the owner's answer is refused, its answer going through a
  resume, and so is any session while another implementation run waits

### Requirement: CW-al17 The implementation cadence is settled in design and mapped by the plan

How many sessions implement a change, and how much each round covers before it is
reviewed, MUST be settled in the design discussion as the change's implementation
cadence. The plan's sections MUST be ordered by it, and planning's outcome MUST
carry the mapping of the cadence onto the sections, as the sessions and rounds that
implement them.

#### Scenario: A plan maps a two-round cadence

- **WHEN** a design settles "round 1: the contract changes; round 2: the handlers
  and the migration", and planning writes sections 1 to 4 in that order
- **THEN** the plan's outcome carries `[[[1, 2]], [[3], [4]]]`, and the second
  round's `round` line is recorded only when that round starts, after the first
  round's triage advanced

### Requirement: CW-v6nj Each round is recorded as it starts

Each round MUST be recorded as it starts, from the latest plan's mapping, as its
first round with a section not yet complete; a change with no mapping for its next
incomplete section MUST ask the owner, once per round.

#### Scenario: A round is recorded after the fact

- **WHEN** a round's sections were implemented and its records written before the
  round was recorded
- **THEN** the round is recorded naming the last record before it, and the
  computation reads the records above that number as the round's

### Requirement: CW-tc82 Each section is checked, handed off, and committed alone

Each section MUST be checked, handed off, and committed on its own. Anything a
later session needs MUST be recorded in the change's files before each section is
committed, and before a section is committed its diff MUST be checked against the
repository's guidance by an agent whose context contains no part of the
implementing session.

#### Scenario: A section is finished

- **WHEN** an implementation session completes a section's tasks
- **THEN** it records any handoff in the section's task notes, a fresh-context
  check of the section's diff passes, and the section is committed; the session
  continues into the next section it was given, or stops

### Requirement: CW-1u53 A failed premise returns the change with its work in progress

When discovered code invalidates the plan, the implementation session MUST record
why, commit what it has as work in progress with no task checked for it, push it,
and return the change.

#### Scenario: The plan's premise fails mid-section

- **WHEN** an implementation session finds code that invalidates the section's plan
- **THEN** it records the finding in the change, commits its partial work as work in
  progress with no task checked for it, pushes it, and returns the change

#### Scenario: Implementation finds a design question

- **WHEN** an unattended implementation run finds that a task needs a decision the
  design does not make
- **THEN** it ends with a proposed return naming design, and the change's status is
  unchanged until the owner confirms the return

### Requirement: CW-aoby A round is read as one set of changes

The owner MUST be able to read a round as one set of changes, from the commit the
previous round ended on to the round's commit, without any commit being changed to
show it.

#### Scenario: The owner reads a round committed section by section

- **WHEN** the owner reads a round of a change worked in its own clone
- **THEN** the round is shown in the owner's workspace as uncommitted changes over the
  commit the previous round ended on, on the change's branch by name, and when the
  reading ends with no commit made during it that branch is back at the round's
  commit with the commits unchanged
- **AND** the branch in the change's clone never moves

### Requirement: CW-4svs A clone's round is read in the workspace beside its validation and review

For a change worked in its own clone, the reading MUST take place in the owner's
workspace, on that workspace's copy of the change's branch, and MUST NOT move the
branch in the clone. Validation and the implementation review MUST start when the
round's sections are committed, beside the reading, and triage MUST NOT start until
the owner has answered on the round, with notes or with none, and the answer is
saved as the round's owner record.

#### Scenario: Validation runs while the owner reads

- **WHEN** a round's sections are committed in a change's clone
- **THEN** validation and the implementation review start there while the owner reads
  the round, and triage starts only once the owner has answered on the round and both
  records exist

#### Scenario: The owner has no notes

- **WHEN** the owner answers that a round raises nothing
- **THEN** that answer is saved as the round's owner record, the view is closed, and
  triage starts

### Requirement: CW-9mrq A repeat pass is read as its round was

When a round's triage records another round and commits a fix, the repeat pass MUST
be read in the same way, as one set of changes from the commit that triage's review
read to the fix's commit, and its triage MUST NOT start until the owner has answered
on that pass; an answer saved before that triage finished MUST answer only for the
earlier pass.

#### Scenario: A repeat round's fix is read

- **WHEN** a round's triage recorded another round and committed a fix, and the
  owner's only record on the round was saved before that triage finished, even
  one numbered after the review it triaged
- **THEN** the owner is shown the fix as uncommitted changes over the commit that
  review read, and the repeat pass's triage waits for the owner's answer on it

### Requirement: CW-78ul A round view in the workspace holds every other step

For a change worked in the owner's workspace, while its branch is moved to show the
round, review, validation, triage, and implementation MUST NOT start. A view MUST
NOT move a checkout in which an unattended run is in progress.

#### Scenario: A view would move a checkout with a run in progress

- **WHEN** the owner opens a view in a workspace where an unattended run is in progress
- **THEN** the view is refused, naming the run, and nothing is checked out

#### Scenario: A round's validation and review ran before the owner read it

- **WHEN** a change worked in the owner's checkout has its round's validation and
  implementation review, and no owner record of the round
- **THEN** the computation names the round view, now that no step runs beside it,
  and triage only once the owner record exists

### Requirement: CW-n44s Ending the reading carries the owner's commits onto the round

Ending the reading MUST return the branch to the round's commit when the owner made
no commit while it was moved, and otherwise to the last of those commits carried
onto the round's commit; the round's own commits MUST NOT change. Each commit the
owner made MUST be carried holding exactly the paths it changed, at the content it
gave them, and every edit the owner did not commit MUST stay uncommitted.

#### Scenario: The owner commits an edit while reading

- **WHEN** the owner commits an edit on the branch in their workspace while the view
  shows the round
- **THEN** ending the reading carries the commit onto the round's commit, with the
  paths it changed and nothing else, keeping its author and message, names it
  beside its replacement, and leaves the branch at the replacement, the round's own
  commits unchanged
- **AND** triage pulls it into the clone only as a fast-forward, refusing a branch
  that has diverged, before presenting it like any point; a commit the owner then
  rejects is undone among the round's fixes

#### Scenario: The owner commits a whole file the round changed, then edits on

- **WHEN** a commit made during the view holds a file the round changed with all of
  the round's changes and the owner's edit, and the owner edits the file again
  without committing
- **THEN** ending the reading carries the commit, and the later edit stays
  uncommitted

### Requirement: CW-uq5q An owner's commit is carried only when it keeps the round's changes

Ending the reading MUST carry a path the round also changed only when the commit's
version holds every change the round made to that path, and MUST refuse without
moving the branch when it does not, when any such commit is a merge, or when the
branch has left the line of the round's base.

#### Scenario: The owner commits part of a file the round changed

- **WHEN** a commit made during the view holds a file the round also changed without
  some of the round's changes to it, whether they were left unstaged or removed
- **THEN** ending the reading refuses, naming the file and how to commit it again on
  the round's commit, and the branch is not moved

#### Scenario: The owner merges during the view

- **WHEN** a commit made during the view has two parents
- **THEN** ending the reading refuses, naming the commit, and the branch is not moved

### Requirement: CW-gd24 Added, deleted, and binary paths are carried only as the round left them

A path the round added, deleted, or changed as a binary file, a symlink, or a mode
MUST be carried only when the commit's version is the round's, absent for a path
the round deleted, and an absent path MUST NOT be taken for an empty file.

#### Scenario: The owner edits a file the round added

- **WHEN** a commit made during the view holds a file the round added, with an edit
  of the owner's
- **THEN** ending the reading refuses, naming the file and how to commit it again on
  the round's commit, and the branch is not moved

#### Scenario: The owner commits a deletion the round made

- **WHEN** a commit made during the view deletes a file the round deleted
- **THEN** ending the reading carries the commit, and the file stays absent

#### Scenario: The owner commits a binary file the round changed

- **WHEN** a commit made during the view holds a binary file the round changed
- **THEN** ending the reading carries it only when its contents are the round's,
  and otherwise refuses, naming the file

### Requirement: CW-rgws A view is not moved over the owner's work

A view MUST NOT be moved to a new head while commits the owner made during it, or
edits the owner did not commit, are present.

#### Scenario: The view is refreshed over the owner's commit

- **WHEN** the owner opens the view again while a commit made during it is on the
  branch
- **THEN** the view is refused, naming the commit and the command that ends the
  reading

### Requirement: CW-te38 The owner's commits reach the clone only by a fast-forward

A commit the owner makes on the change's branch while reading MUST reach the clone
only through a fast-forward that triage makes.

#### Scenario: The clone's branch has diverged from the owner's

- **WHEN** the owner committed while reading, and the change's branch in its clone
  holds a commit the workspace's branch lacks
- **THEN** triage refuses to pull the owner's commit into the clone, and merges
  nothing

### Requirement: CW-a7dw Validation describes one commit and modifies nothing

Validation before an implementation review MUST describe one commit and MUST NOT
modify the checkout. It MUST fail if the worktree is not clean when it starts or
after any step, or if `HEAD` is no longer the validated commit after any step, and
MUST then collect no further evidence, though it MAY still stop what it started. It
MUST NOT regenerate lockfiles or any other tracked file, `tasks.md` included.

#### Scenario: A part leaves the worktree dirty

- **WHEN** a validation part leaves an uncommitted change in the worktree
- **THEN** validation fails, collects no further evidence, and still stops what it
  started

### Requirement: CW-af15 Validation repairs nothing

Validation MUST NOT fix what it finds in the commit. A condition validation could
repair, such as a stale lock, MUST fail validation and return the slice to
implementation.

#### Scenario: A lockfile is stale

- **WHEN** validation runs on a slice whose committed lockfile is not current
- **THEN** validation fails and reports the stale lock, and the lockfile is
  unchanged

### Requirement: CW-zkhs Validation's parts are the repository's

Validation MUST run the repository's validation parts, and each part's evidence
MUST come from the commit under validation, never from another commit's build, run,
or state.

#### Scenario: A part finds only another commit's evidence

- **WHEN** a validation part finds a finished run of its evidence only for an earlier
  commit of the branch
- **THEN** it does not report that run as evidence of the validated commit

### Requirement: CW-e7lm Validation's result is passed, failed, or inconclusive

A validation's result MUST be `passed`; `failed`, for a failure caused by the commit
or of unknown cause; or `inconclusive`, when no failure is caused by the commit but
a part produced no evidence for an environmental reason.

#### Scenario: A part produces no evidence for an environmental reason

- **WHEN** no failure is caused by the commit, and one part produced no evidence
  because its environment was unavailable
- **THEN** the result is `inconclusive`, neither `passed` nor `failed`

### Requirement: CW-a1nz An environmental failure goes to the owner with its remedy

A failure diagnosed as environmental MUST be put to the repository owner with its
remedy before the record is written, and its part rerun on the owner's word; every
attempt's evidence MUST be kept.

#### Scenario: Validation needs an environmental remedy

- **WHEN** an unattended validation finds an environmental failure
- **THEN** it ends with a question naming the remedy, and once the owner answers, the
  same session resumes with the answer and takes only the action named

### Requirement: CW-av28 A validation record names the scenarios that exercise the change

The validation record MUST name the end-to-end scenarios that exercise the change,
with the basis for each.

#### Scenario: The sections name their scenarios

- **WHEN** the change's complete sections name the end-to-end scenarios that
  exercise them
- **THEN** the record names each scenario with that basis, or says that no scenario
  exercises the change

### Requirement: CW-qtxb A round's review, validation, and owner's notes are triaged together

The implementation review, the validation of the same commit, and the owner's notes
on it MUST be triaged together, in a session that is not the implementing session.
A review the review tooling publishes MUST name the commit it reviewed, so the
commits can be compared mechanically; for a pasted review, triage MUST record the
commit the owner says its reviewer saw.

#### Scenario: A pasted review joins a round

- **WHEN** the owner pastes a review into a round's triage
- **THEN** triage records the commit the owner says its reviewer saw, and compares
  it with the commit the validation names

### Requirement: CW-514y Records of different commits form a round only on the owner's waiver

A review and a validation of different commits MAY be triaged as one round only
when the owner waives the rule, judging the changes between them; the waiver MUST
be recorded in the intervention ledger.

#### Scenario: A review and a validation describe different commits

- **WHEN** a round's review names a different commit from its validation record
- **THEN** triage names both commits and what changed between them, and treats
  them as one round only on the owner's recorded waiver; otherwise the reviewed
  commit is validated or the validated commit reviewed first

### Requirement: CW-xg4v A validation failure is a finding, and missing evidence is not

Each validation failure caused by the commit, or of unknown cause, MUST be presented
as a finding, with its diagnosis checked against the logs; an `inconclusive` part
MUST be read as missing evidence, never as a finding.

#### Scenario: Validation fails beside an implementation review

- **WHEN** an implementation round's validation reports a failing scenario
- **THEN** the failure is triaged as a finding of the round, fixed after the owner's
  disposition, and the fix commit is validated again

### Requirement: CW-rb5n The owner's notes are triaged as a review

The owner's notes MUST be saved verbatim as a review record and triaged like any
review: the triaging agent MUST state its own position on each point rather than
carry it out as an instruction, and each disposition MUST be logged to the
intervention ledger.

#### Scenario: The owner's note is contradicted by the files

- **WHEN** a point in the owner's notes rests on a claim the files contradict
- **THEN** triage says so, with the evidence, and nothing changes until the owner
  has recorded a disposition

### Requirement: CW-j1ab A triage's edits are checked, committed, pushed, and validated

Accepted fixes MUST pass the checks a section passes before they are committed, and
the commit MUST be validated again, unless, after a pre-closeout review, it changes
only paths under `openspec/` and `docs/`. A triage of any kind MUST commit the
tracked edits its dispositions made, with a fix or alone, and push them.

#### Scenario: An implementation triage commits only documents

- **WHEN** an implementation round's triage commits an edit to the change's task
  list after the latest validation passed, with no fix
- **THEN** that commit is validated before the next round or the pre-closeout review

#### Scenario: A pre-closeout triage commits only documents

- **WHEN** a pre-closeout review's triage advances the change with no fix, and
  commits its edits to the change's documents after the latest validation passed,
  and the merge that follows finds the branch the change lands on merged already
- **THEN** closeout starts without the commit being validated again

### Requirement: CW-gqav A pre-closeout review needs a passed validation of HEAD

A pre-closeout review MUST NOT run, and its triage MUST NOT advance the change,
unless the latest validation's result is `passed` and it names `HEAD`, or a commit
from which `HEAD` descends and differs only in changes' intervention ledgers and
review records, except where the owner overrides it. Once its triage has run, a
commit from which `HEAD` differs only in paths under `openspec/` and `docs/` MUST be
accepted in the same way.

#### Scenario: A ledger line is committed after the validation

- **WHEN** the latest validation passed for a commit, and the only commit since adds
  a line to a change's intervention ledger
- **THEN** a pre-closeout review may run without the commit being validated again

### Requirement: CW-p2b2 Each review is one numbered record

Each review of a change MUST be written as one Markdown file in that change's
`reviews/` directory, numbered in the order reviews are produced, and that file MUST
be the only record of its findings. The records' order MUST be establishable, by
number or, where two records of different kinds share a number, by their file
times, and a record MUST NOT be overwritten. Each finding MUST state its lens, its
basis, its severity, and the evidence it cites.

#### Scenario: Two records share a number

- **WHEN** a validation record and a review record of a change are both numbered 12
- **THEN** their order is read from their file times, and neither overwrites the
  other

### Requirement: CW-2nb2 A later review reads earlier findings from the records

A later review MUST obtain earlier findings and their dispositions from the records
rather than from session memory. A review of the same kind as an earlier one MAY
continue the reviewer session that wrote it, keeping the context behind its
findings, but MUST still read the triage and dispositions from the records.

#### Scenario: A pre-closeout review asks whether feedback was addressed

- **WHEN** a pre-closeout review runs in a session that produced none of the
  change's earlier reviews
- **THEN** it reads the earlier reviews and their triage from `reviews/` and
  answers for every earlier finding

### Requirement: CW-ovuj Review records are untracked, and their durable content is promoted

The `reviews/` directory MUST NOT be tracked by version control and MUST NOT be
cited by permanent documentation; anything durable in it MUST reach permanent
documentation through the ordinary promotion path at closeout.

#### Scenario: A review finding changes the design

- **WHEN** a review finding leads to an accepted design decision
- **THEN** the decision is recorded in the change's `design.md` and promoted at
  closeout, and nothing permanent cites the review file

### Requirement: CW-5e24 A review's transcript is kept and never read as a record

A review's raw session MAY be kept as a transcript under the change's
`reviews/transcripts/`, untracked like the records. A transcript is not a record of
findings: no review or triage step SHALL read one.

#### Scenario: A later review runs beside a transcript

- **WHEN** a pre-closeout review runs for a change whose earlier review left a
  transcript
- **THEN** it reads the earlier review's Markdown record and triage, and not the
  transcript

### Requirement: CW-r9d2 A reviewer's output is published only as a review

A reviewer's output SHALL be published as a review record only after it is checked
to have the review format. A review run's outcome MUST name the record that run
published; a review run that published none MUST be recorded as stopped, and an
earlier record MUST NOT count as its result.

#### Scenario: The reviewer returns an error instead of a review

- **WHEN** the reviewing agent's final output is an error message rather than a
  review
- **THEN** no review record is published, and the output is kept beside the
  transcript

### Requirement: CW-5sc1 A finding's lens and basis

A finding's lens MUST be one of `direction`, `consistency`, `testing`,
`documentation`, `architecture`, `scope`, or `readiness`. Its basis MUST be
`specification` or `guidance`, each citing the requirement or rule it rests on;
`evidence`, citing the files that contradict a claim; or `judgement`, resting on no
written rule.

#### Scenario: A finding cites written guidance

- **WHEN** a finding's basis is `guidance`
- **THEN** it names the document and heading of the rule it applies

### Requirement: CW-7d5f A finding's severity

A finding's severity MUST be `blocking`, which MUST be resolved before the change
enters its next phase; `should`, which is resolved within the change unless the
owner defers it and the deferral is recorded; or `minor`, which the implementing
agent MAY decline with a reason.

#### Scenario: A design review accepts a blocking finding

- **WHEN** the owner accepts a `blocking` finding in a design review
- **THEN** the change remains in design until the fix lands, and planning does not
  begin before the triage records that the change advances

### Requirement: CW-j1nv Triage states a position on every finding and presents every one

The implementing agent MUST record, for every finding in a review, its own position
(agree, disagree, or partly) with the evidence for it and a proposed action, and a
position of agreement MUST state its reason as a disagreement does. Every finding
MUST be presented to the owner, none withheld for being minor or uncontested.

#### Scenario: A minor finding the agent agrees with

- **WHEN** a review contains a `minor` finding the implementing agent agrees with
- **THEN** it is still presented to the owner with the agent's reason

### Requirement: CW-neua A finding is disposed of only by the owner

Every review MUST stop for the owner's disposition of each finding before any
finding is acted on, and a finding MUST be treated as disposed of only when the
owner states a disposition for it. An agent MUST NOT treat its own or another
agent's agreement with a finding as a disposition.

#### Scenario: A reviewer and the implementing agent agree

- **WHEN** a reviewer raises a finding and the implementing agent agrees with it
- **THEN** nothing is changed until the owner has recorded a disposition for it

#### Scenario: The owner discusses one finding and not another

- **WHEN** the owner asks about one finding and says nothing of another
- **THEN** the other has no disposition, and is presented again before another
  round is asked about

### Requirement: CW-zidp A course correction is logged to the ledger

Each disposition by which the owner corrects course, deciding otherwise than the
implementing agent proposed or adding context or a condition that changes the work,
MUST be appended as one entry to the change's `interventions.jsonl`, stating the
review, the `tasks.md` section the finding concerns when it concerns one, the
finding's lens, basis, and severity, the agent's position, the owner's disposition,
and a one-line summary.

#### Scenario: The owner adds a condition to a finding

- **WHEN** the owner accepts a finding on the condition that its fix also covers a
  second module
- **THEN** one ledger entry records the finding, the agent's position, the owner's
  disposition with its condition, and a one-line summary

### Requirement: CW-xe8m An accepted proposal is not logged to the ledger

A disposition that accepts the implementing agent's proposal as it stands MUST NOT
be logged to the ledger; the triage record holds every disposition.

#### Scenario: The owner accepts a finding as proposed

- **WHEN** the owner disposes of a finding by accepting the agent's proposed
  outcome without adding to it
- **THEN** the triage record holds the disposition and the ledger gains no entry

### Requirement: CW-w22z A design reversal is logged to the ledger

Each time the owner changes or reverses the agent's recommendation during a design
discussion, an entry MUST be appended to the ledger in the same shape, with `review`
set to `design`, the decision as `finding`, lens `direction`, basis `judgement`, and
a null severity. A recommendation the owner accepts MUST NOT be logged.

#### Scenario: The owner reverses a design recommendation

- **WHEN** the owner chooses a different option than the one the agent recommended
  for a design decision
- **THEN** one ledger entry records the decision, the agent's recommendation, and
  what the owner chose and why

### Requirement: CW-1jxh The ledger is tracked and archived with the change

The intervention ledger MUST be tracked by version control, MUST remain in the
change directory, and MUST be archived with the change.

#### Scenario: A reviewed change's archive is cleaned up

- **WHEN** a change whose findings were dispositioned is cleaned up after its
  closeout review's triage advanced it
- **THEN** its intervention ledger is in the archived change directory, and its
  `reviews/` directory stays there, untracked, until an export flow exists

### Requirement: CW-r3ka The engine is reached through one command

Every operation of the workflow's engine MUST be reachable through one command's
subcommands, `scripts/change-workflow`, and a repository MUST reach the engine
only through that command, never by importing its code. The command MUST act on
the Git repository containing its working directory, and MUST refuse, naming the
directory, when run outside one.

#### Scenario: A repository script needs a change's directory

- **WHEN** a repository's closing check needs the directory of a change and
  whether it is archived
- **THEN** it runs `scripts/change-workflow find --json <change>` and reads the
  `directory` and `archived` fields, and imports nothing of the engine

#### Scenario: A change's checkout holds no records, or the change does not exist

- **WHEN** `find --json` runs for a change whose directory exists and whose
  checkout holds no `reviews/`
- **THEN** it exits 0 with `records` as `null`; for a change that does not exist,
  `find --json` and `clone where` each exit 1, naming the change, and `clone
  where` looks for no clone

#### Scenario: A change's clone exists but is unusable

- **WHEN** `clone where <change>` runs and the clone's directory exists but holds
  another branch, or is not a clone of the workspace, or its bootstrap has not
  succeeded
- **THEN** it exits 1, naming the reason, and never prints nothing as it does for
  a change worked in place, where no clone directory exists

#### Scenario: A step is started interactively without make

- **WHEN** the owner runs `scripts/change-workflow start design <change>` for an
  archived change
- **THEN** the command refuses, naming the archived directory, and starts no
  session

#### Scenario: The command runs in a change's clone

- **WHEN** the command runs in a change's clone
- **THEN** it acts on the clone's repository, not on the owner's workspace

#### Scenario: The command runs outside a repository

- **WHEN** the command runs in a directory no Git repository contains
- **THEN** it refuses, naming the directory, and writes nothing

### Requirement: CW-h8vm Make targets are a convenience outside the surface

The engine MAY ship a make fragment whose targets call its command, for a
repository's `Makefile` to include after setting its own values. The fragment's
targets and variables MUST carry no compatibility promise, and a change to them,
or to a repository's own targets, MUST NOT be counted as a change to the engine's
public interface.

#### Scenario: A repository includes the fragment

- **WHEN** a repository's `Makefile` sets `CHANGE_WORKFLOW_MERGE_FROM := <branch>`
  and includes `scripts/change_workflow/workflow.mk`
- **THEN** the fragment's `merge` target starts the merge from `<branch>` through
  `scripts/change-workflow start merge`

#### Scenario: A fragment target is renamed

- **WHEN** a workflow change renames a target of the make fragment
- **THEN** its proposal records no change to a public interface for it

### Requirement: CW-ms3j One orchestrating session advances one change from its files

The owner MAY advance one change through its steps from one orchestrating session,
which MUST advance only the change it was started for. It MUST hold no state beyond
the change's files and its workflow log, so that a new session resumes the change
from them alone.

#### Scenario: The orchestrating session restarts

- **WHEN** an orchestrating session is started for a change partway through its
  workflow
- **THEN** it determines the next step from the change's files and workflow log, and
  continues from there

#### Scenario: The orchestrating session restarts during a round view

- **WHEN** an orchestrating session is started while a round view of the change is
  open
- **THEN** it waits for the owner's answer on the round, saves it as the change's
  next owner record, and closes that view before triage, and, for a change worked
  in the owner's workspace without a clone, before computing any other step

### Requirement: CW-5jlj The orchestrating session runs what the computation names

The orchestrating session MUST run the next step the next-step computation names,
and MUST advance without the owner wherever the computation names a step.

#### Scenario: A review's triage has nothing for the owner

- **WHEN** a review and the validation beside it raised no finding, and the
  owner's notes raise no point to dispose of
- **THEN** the triage records that the change advances, and the orchestrating
  session runs the next step without asking the owner

### Requirement: CW-yvo1 The orchestrating session relays and takes no position

The orchestrating session MUST bring every question a step raises to the owner,
showing each step's message as written, and MUST show the earlier outcomes a run's
line keeps beside its last. It MUST NOT answer a design question, nor decide or
state a position on a finding.

#### Scenario: A finding is relayed

- **WHEN** an orchestrated triage presents a finding
- **THEN** the orchestrating session shows the triage's message as written, adds no
  position of its own, and resumes the triage with the owner's reply

### Requirement: CW-mkwj The orchestrating session reads only what routing needs

The orchestrating session MUST NOT read code, reviews, or change documents to form
or state a view of a finding or a design question; it MAY read what routing and
recovery need: the computation and the inputs it names, the workflow log, and the
denials report.

#### Scenario: A finding concerns code

- **WHEN** a triage's message presents a finding about a function
- **THEN** the orchestrating session shows the message without reading the function
  to judge the finding

### Requirement: CW-op72 What the orchestrating session may commit

The orchestrating session MAY create the change's clone and branch, and MAY commit
changes to the workflow itself (skills, the step table), what else the owner
explicitly asks for, and merges the owner asks for of the branch the change lands
on, in the change's clone, on its branch, pushing each through the guarded push. It
MUST NOT write the change's feature work of its own accord.

#### Scenario: The owner asks for a permission fix

- **WHEN** a run is denied a command for want of a rule, and the owner asks the
  orchestrating session to add the rule
- **THEN** it edits the step table in the change's clone and commits the edit on the
  change's branch, so the step's next run is held to the new rule

### Requirement: CW-bsmk When the orchestrating session commits and merges nothing

The orchestrating session MUST NOT commit while a step runs, and MUST NOT merge
while a round view of the change is open or between a round's sections being
committed and that round's triage. It MUST NOT commit a closed step's leftover work
unless the owner asks, bringing such work to the owner instead.

#### Scenario: A merge is asked for during a round's window

- **WHEN** the owner asks for a merge of the branch the change lands on after a
  round's sections are committed and before that round's triage
- **THEN** the orchestrating session makes the merge only once the round is triaged,
  so it never moves the commit the round's validation and review describe

#### Scenario: A closed step leaves tracked work uncommitted

- **WHEN** a step's run finished and left a tracked edit uncommitted
- **THEN** the orchestrating session brings it to the owner as a defect of that step,
  and commits it only if the owner asks

### Requirement: CW-tax4 The orchestrating session resolves a merge's conflicts but code's

The orchestrating session MUST resolve a merge's conflicts in the change index,
change documents, the step table, and skills itself, and MUST bring a conflict in
code to the owner; one the owner does not rule on MUST go to an implementation run,
named the conflicted files. While a merge is in progress the next-step computation
MUST name the owner.

#### Scenario: A merge conflicts in a skill and in code

- **WHEN** the owner asks the orchestrating session to merge the branch the change
  lands on between steps, and the merge conflicts in a skill and in a script
- **THEN** it resolves the skill's conflict itself and brings the script's to the
  owner; when the owner does not rule on it, it starts an implementation run naming
  the conflicted script, which resolves it, concludes the merge, and pushes

### Requirement: CW-6scj The orchestrating session may report the tooling's misbehaviour

The orchestrating session MAY report misbehaviour of the workflow's own tooling
that it observed across steps; such a report MUST be a numbered record marked as
its own, for the next triage.

#### Scenario: A step's tooling misbehaves across runs

- **WHEN** the orchestrating session sees the same tooling failure in two steps'
  runs
- **THEN** it writes the change's next numbered record as its own observations,
  citing the log lines, and the next triage triages it with the round's records

### Requirement: CW-6fi2 A waived design review after a return is a direction to planning

When the owner waives another design review for a design decision made after a
return, the orchestrating session MUST record the owner's word as a decision
directing planning, and the next-step computation MUST then name planning.

#### Scenario: The owner waives a design review after a return under orchestration

- **WHEN** planning returned a change to design, the design step settled the
  decision and finished, and the owner tells the orchestrating session they waive
  another design review
- **THEN** the owner's word is recorded in the workflow log as a decision directing
  planning, the waiver is recorded in the intervention ledger, and the computation
  names planning rather than a design review

### Requirement: CW-js86 An unattended run ends with a structured outcome

A step MAY be run unattended, through one wrapper, as its leaf skill in a
non-interactive session. Every unattended run MUST end with an outcome that
conforms to the outcome schema and is one of: finished, naming the exit it takes; a
question for the owner; a proposed return, naming the step it returns to; blocked
on a prerequisite; or stopped, with its reason and any tools it was denied.

#### Scenario: A design ends blocked

- **WHEN** an unattended design run ends because its design needs another change
  first
- **THEN** its outcome is blocked, naming that change, and conforms to the outcome
  schema

### Requirement: CW-5ldi An exit or a return is named as a target

An exit or a return MUST be named as a target: an object naming a node of the
workflow graph by its step, with its review kind for a review, the kind of review
it triages for a triage, and the sections for an implementation out of the plan's
order. A review or a triage named without its kind, or with an empty or unknown
one, MUST be refused. A validation MUST name as its exit the target the computation
gave it, and archive cleanup the terminal node `done`.

#### Scenario: A triage names its exit

- **WHEN** an unattended triage of review 157 ends with
  `{"outcome": "finished", "message": "…", "triaged": ["157-closeout"], "next": {"step": "review", "kind": "closeout"}}`
- **THEN** the wrapper records it, and the computation routes on its exit

### Requirement: CW-4vma A triage outcome names the records it triaged

A triage's finished or returned outcome MUST name the records it triaged, as a
non-empty list of distinct names `NN-<kind>`, each a numbered record in the
change's `reviews/` with its triage file beside it, at least one a review. The
wrapper MUST record an outcome that breaks this rule only as stopped, naming the
reference, and the record command MUST refuse it.

#### Scenario: A triage outcome names no records

- **WHEN** an unattended triage ends finished without naming the records it triaged,
  or naming an empty list
- **THEN** the wrapper records the run as stopped, naming the missing field

#### Scenario: A triage outcome names an unknown record

- **WHEN** an unattended triage of review 13 ends finished with
  `"triaged": ["31-design"]`, and the change has no record 31
- **THEN** the wrapper records the run as stopped, naming `31-design`

#### Scenario: A triage outcome names no review

- **WHEN** a triage outcome's `triaged` names only `12-validation`
- **THEN** it is refused, since it names no review, and the review it triaged stays
  in progress

#### Scenario: A triage outcome names a record twice

- **WHEN** a triage outcome's `triaged` is `["13-design", "13-design"]`
- **THEN** it is refused, naming the duplicate

### Requirement: CW-1a4d The wrapper logs every outcome of a run

The wrapper MUST append each outcome, with the run's session and commit, to the
change's workflow log, and MUST record a stopped outcome itself for a run that ends
without one. A run whose session took further turns after an outcome, such as a
background command finishing or a wake-up, MUST be logged with its last outcome,
keeping each earlier one on its line.

#### Scenario: A run crashes

- **WHEN** an unattended run exits without producing an outcome
- **THEN** the workflow log records a stopped outcome with its exit status

#### Scenario: A wake-up follows a run's report

- **WHEN** an implementation run reports its section finished, and a wake-up it
  scheduled starts another turn that ends with "nothing left to wait for"
- **THEN** the run's line carries that last outcome with the section's report kept
  under `earlier`, and the orchestrating session shows the owner both

### Requirement: CW-4c3e The files prevail over the log on a change's state

A change's files MUST hold its state and MUST prevail over the workflow log on it;
the log holds the exits steps chose and the owner's decisions.

#### Scenario: A status was edited by hand

- **WHEN** a change's status was set back by hand into an earlier phase than its
  workflow log's last step, and no direction of the owner's follows that step
- **THEN** the computation follows the status, naming the node its phase starts at
  — design, planning, or the round — with that node's unwaivable entry guards
  checked, until that node's step starts or the owner directs another

#### Scenario: A status is ahead of the log

- **WHEN** a change's status is past the step its workflow log names
- **THEN** the computation names that step as in progress, its result carrying a
  `disagreement` naming the missing outcome

### Requirement: CW-k5mk A run's denials come from its own record

Every unattended run's outcome MUST carry the denials the run recorded, taken from
the run's own record of denied tools over every turn of the run, each with the
harness's reason for it where the harness gives one.

#### Scenario: A step's message omits a denial

- **WHEN** a run was denied a call in an earlier turn, and its final message names
  no denial
- **THEN** its outcome carries that denial from the run's record, with the
  harness's reason

### Requirement: CW-xgq3 A question resumes its session, and a return waits for the owner

A question MUST be answered by resuming the same session with the owner's answer. A
proposed return MUST NOT change the change's status until the owner confirms it;
the confirmation MUST be recorded in the workflow log as the owner's decision naming
the run it resolves and the step it directs, and the step so directed MUST set the
status.

#### Scenario: The owner confirms a return

- **WHEN** an implementation run at seq 50 ended with a proposed return to design
  and the owner confirms it, recorded as
  `{"seq": 51, "step": "orchestrator", "outcome": "orchestrator", "by": "owner", "resolves": 50, "next": {"step": "design"}, "decision": "return to design confirmed", "reason": "task 0.4 needs a provider decision the design does not make"}`
- **THEN** the next-step computation names design until it has run, and the
  design step sets the status

### Requirement: CW-ht4h A decision names the run it resolves, and a direction is the owner's

A decision that resolves a run MUST name it, and MUST NOT resolve any other; a
decision that reads a run's denials MUST name that run; a decision that directs a
step MUST name its target as an outcome names an exit, and MUST be the owner's.

#### Scenario: A confirmation names no run

- **WHEN** the returned run at seq 50 waits, and the owner's direction to design is
  recorded naming no run
- **THEN** the run at seq 50 still waits, and the computation names the owner for it
  until a decision resolves it

#### Scenario: A decision about one run leaves another waiting

- **WHEN** a validation run has asked a question and a review run beside it stopped,
  and a decision resolves the review's stop
- **THEN** the validation's question still waits, and is answered by resuming its
  session

#### Scenario: A directed review names no kind

- **WHEN** a decision line directing `{"step": "review"}` with no kind is attempted
- **THEN** the log's writer refuses it, since a review is a node only with its kind

#### Scenario: A directed triage names no kind

- **WHEN** a decision line directing `{"step": "triage"}` with no kind is attempted
- **THEN** the log's writer refuses it, since a triage is a node only with the kind
  of review it triages

#### Scenario: A return confirmed by anyone but the owner

- **WHEN** a decision the log would attribute to the orchestrating session, resolving
  a triage's proposed return and directing planning, is attempted
- **THEN** the log's writer refuses it, and the return still waits for the owner

### Requirement: CW-mzyz An interactive run records its outcome through the command

An interactive run of a step MUST behave as it does without the wrapper,
unrestricted by the step table, except that it MUST end by recording its outcome
through the command's `record`. A review MUST record nothing: an interactive review
publishes no record, and its text is saved as an external review by the triage it
is pasted into.

#### Scenario: An interactive triage finishes

- **WHEN** the owner triages a review in an interactive session, and the triage
  ends by recording its outcome naming the review it triaged and its exit
- **THEN** the workflow log holds that outcome with the session's id, `HEAD`, and
  `interactive`, and the computation routes on it

#### Scenario: An interactive review is pasted into a triage

- **WHEN** the owner asks for a review in an interactive session and pastes it into
  a triage
- **THEN** the review's session records no outcome, the triage saves the review as
  the change's next `NN-<kind>-external.md`, and the triage's outcome names it in
  `triaged`

#### Scenario: An interactive session ends without recording

- **WHEN** the owner closes an interactive session of any step but a review before it
  recorded its outcome, and the last exit or direction names that step
- **THEN** the computation names the step as in progress, its reason saying that if
  no session of it is open, an interactive session ended without recording, to be
  resumed or recorded by hand

#### Scenario: An interactive plan sets its status and records nothing

- **WHEN** an interactive planning session wrote the task list and set the status
  `ready for implementation`, and was closed before it recorded its outcome
- **THEN** the computation names planning as in progress, and no round, its result
  carrying a `disagreement` naming the missing plan outcome and the record command

### Requirement: CW-gnqh The record command checks and attributes an outcome

`record` MUST check the outcome against the outcome schema and record it with the
session's id, read from the harness's environment or given explicitly, the commit
at `HEAD`, and that the run was interactive. It MUST refuse to record without a
session id, and inside an unattended run, whose outcome the wrapper records. Every
step's permissions MUST allow it to print the session's id.

#### Scenario: The harness exports no session id

- **WHEN** the record command runs where the harness's session id variable is unset,
  and no session is given
- **THEN** it refuses, naming the variable, and records nothing

#### Scenario: An unattended run records its own outcome

- **WHEN** a step run by the wrapper runs the record command
- **THEN** the command refuses, and the run's outcome is the one the wrapper records

### Requirement: CW-x7jd A change's record set carries one format version

The workflow log's `format` MUST version a change's record set: its lines, the
records' layout, names, and parsed fields, and, where a log exists, the ledger's
lines. `next` and `find --json` MUST carry it, and the outcome schema's `$id` MUST
state it. A line with no `format` or a lower one MUST be read as older; a higher
one MUST be refused by the reader, naming it. With no log, numbered records MUST be
read as older and a ledger alone in the reader's format.

#### Scenario: A runner reads the next step

- **WHEN** a runner reads the data `scripts/change-workflow next <change>` prints
- **THEN** the output's `format` names the record set's format before any field
  the runner routes on

#### Scenario: An older engine meets a newer log

- **WHEN** an engine reading format 2 finds a log line marked format 3
- **THEN** it refuses the change, naming format 3, and routes on none of its lines

### Requirement: CW-k6qa A step started through the command opens the log

Before any step it starts runs, interactive or unattended, `start` MUST ensure the
change's workflow log exists and append a line carrying the log's format, so that a
change worked through the command has its format marked before any other record.
The next-step computation MUST route on no such line.

#### Scenario: A design discussion writes the ledger before its outcome

- **WHEN** the owner starts a design discussion through `start`, and the session
  appends to the ledger before it records an outcome
- **THEN** the log already holds the opening line with its format, and the ledger
  is read in that format

#### Scenario: A ledger with no log

- **WHEN** a discussion started by slash command leaves a ledger and no log
- **THEN** the ledger, which carries no format, is read in the reader's format, not
  as older records to convert, until a recorded outcome opens the log that then
  governs it

### Requirement: CW-lyr4 Every line appended to the log carries its format

Every line the engine appends to a change's workflow log MUST carry the log's
format, and the log's appender MUST refuse to append to a log holding a line of a
newer format.

#### Scenario: The wrapper appends a run's outcome

- **WHEN** the wrapper appends a finished run's outcome to the change's log
- **THEN** the line carries the format the engine writes

### Requirement: CW-qj77 Records of an older format are brought to the owner with the conversion

A change whose log holds a line of an older format, or which has numbered review
records and no log, MUST be brought to the owner with the command that converts its
records, `convert`, and its log MUST NOT be read as the current format.

#### Scenario: A log not yet converted

- **WHEN** a change's workflow log holds a decision line, without the format marker,
  whose `next` is the string `review` beside a `kind` field
- **THEN** the computation names the owner with the command that converts the
  change's records, and routes on none of its lines

#### Scenario: An older return awaits confirmation

- **WHEN** a change's workflow log ends with a triage's `returned` outcome that
  carries `return_to` and no `next`, without the format marker
- **THEN** the computation names the owner with the conversion command, not the
  waiting return

#### Scenario: A change has records and no log

- **WHEN** a change worked in interactive sessions has `reviews/03-design.md` and
  its triage file, and no workflow log
- **THEN** the computation names the owner with the conversion command, and names
  no triage in progress

#### Scenario: An older wrapper appends after the conversion

- **WHEN** a converted log gains a line without the format marker, as the converting
  run's own outcome appended by the wrapper that started it
- **THEN** the computation names the owner with the conversion command again, and
  the conversion, finding a run after the latest triage, requires the owner's
  `--next`

### Requirement: CW-h12x The conversion refuses a newer log

The conversion MUST refuse a log holding a line of a newer format than the engine
reads, naming that format, before anything else and whether shown or confirmed, and
MUST rewrite nothing; it MUST NOT convert a log backwards.

#### Scenario: An older engine is asked to convert a newer log

- **WHEN** `scripts/change-workflow convert <change>` runs on a log holding a line
  marked format 3, under an engine reading format 2
- **THEN** it refuses, naming format 3, and rewrites nothing

### Requirement: CW-42me The conversion refuses a change with a triage in progress

The conversion MUST refuse, naming the review, a change with a triage file in
progress by the older reading: one with neither `## Next` nor `## Gate`, and no
triage outcome of the current format naming its review.

#### Scenario: A change is converted with a triage in progress

- **WHEN** a change's latest triage file has neither `## Next` nor `## Gate`, and
  no marked triage outcome names its review
- **THEN** the conversion refuses, naming the review and how to finish its triage,
  writes nothing, and the review stays a triage in progress

### Requirement: CW-o1ca The conversion rewrites the log in place and names every triaged review

The conversion MUST rewrite the log's lines in place, each keeping its seq, so every
decision still names the run it named. It MUST append one conversion line naming,
as `triaged`, every review with a triage file, and no exit; it MUST name a review no
current triage outcome names only once the owner, shown the heading line its triage
file was read from, confirms that triage finished.

#### Scenario: A change is converted

- **WHEN** a change's log holds older lines, the last triage file of review 21
  records `Another round`, and the owner confirms the review the conversion proposes
- **THEN** each older line is rewritten in place with its seq and marked, one
  conversion line is appended naming every triaged review and no exit, followed by
  the owner's direction to `{"step": "review", "kind": "design"}`, and the
  computation names that review

#### Scenario: A confirmed return is converted

- **WHEN** the owner's decision at seq 51 resolved the returned triage run at seq 50,
  directing design, and design has not run when the change is converted
- **THEN** seq 50 and 51 keep their seqs, the decision still resolves seq 50, and
  the direction the conversion writes names `{"step": "design"}`

#### Scenario: A conversion's triage is not attested

- **WHEN** a change's latest triage file has `## Next` written as prose and no
  triage outcome names its review, because the triage's interactive session closed
  before `record`, and the owner declines the conversion that lists it
- **THEN** the log is unchanged; once the triage's outcome is recorded with
  `record`, running the conversion again names the review by that outcome

### Requirement: CW-zniv The conversion appends the owner's direction to the node the change stands at

After its conversion line, the conversion MUST append the owner's direction to the
node the change stands at, which the owner confirms or gives; where the owner
neither confirms a proposed node nor gives one, it MUST write nothing.

#### Scenario: A pending return is converted, then confirmed

- **WHEN** a change's last triage, logged at seq 50, proposed a return to planning
  that the owner has not confirmed, and the owner confirms the direction the
  conversion proposes
- **THEN** seq 50 is rewritten in place naming `{"step": "plan"}`, and the
  conversion's direction to planning resolves seq 50; had the owner declined it,
  no direction would be written, and the computation would name the owner for
  seq 50

#### Scenario: A conversion after later runs

- **WHEN** a change's latest triage file is a design review's, recording `Advance`,
  and a planning run is logged after that triage's run
- **THEN** the conversion proposes nothing, names the planning run, and writes
  nothing until the owner gives the node with `--next`

### Requirement: CW-ajcm What the conversion proposes

The conversion MUST propose the node from the latest routing decision after the
latest triage: a later direction whose target has not run, or else the triage's
token, with the remedy of any unmet exit guard on the edge it follows. It MUST NOT
propose one when a step's run follows the latest triage, or when a later
direction's target can no longer be entered.

#### Scenario: A conversion proposes a guard's remedy

- **WHEN** a change's latest triage file is an implementation round's, recording
  `Advance`, no step's run is logged after it, and the fix commit has no passing
  validation
- **THEN** the conversion proposes the direction
  `{"step": "validate", "target": {"step": "round"}}`

#### Scenario: A conversion follows a later direction

- **WHEN** a change's latest triage file is a design review's, recording
  `Another round`, and the owner's later decision directing planning is logged with
  no planning run after it
- **THEN** the conversion proposes `{"step": "plan"}`, not another design review

### Requirement: CW-95xp The conversion replaces the log in one step

The conversion MUST hold the log's lock from its read through replacing the log in
one step, so that an interrupted conversion leaves the older log.

#### Scenario: A conversion is interrupted

- **WHEN** a conversion stops after rewriting the older lines and before replacing
  the log
- **THEN** the log is unchanged, the computation still names the owner with the
  conversion command, and running it again converts the change

### Requirement: CW-v8mq A reader of the log reopens a log replaced under its lock

Every reader and appender of the workflow log MUST, once it holds its lock, open the
log again when the file it locked is no longer the one the log's name holds, so that
a line appended while the log is converted is kept.

#### Scenario: An append waits on the conversion

- **WHEN** a step's run opens the log to append its outcome while the conversion
  holds the log's lock, and takes the lock after the converted log has replaced it
- **THEN** the run finds the file it locked replaced, opens the log again, and its
  line is appended to the converted log

### Requirement: CW-4rqr The next step is computed from the files

The next step of a change MUST be computed by the engine, interpreting the workflow
graph over the change's index row, its reviews, its tasks, its workflow log, and the
state of any open round view, and the same computation MUST be available to the
owner by hand, as the command's `next`.

#### Scenario: Reviews await triage

- **WHEN** a change's latest validation and implementation review have no triage
- **THEN** the computation names triage as the next step

### Requirement: CW-tel3 What the computation cannot classify is resolved or brought to the owner

When the computation fails or cannot classify a change's state, the orchestrating
session MUST determine what happened and either resolve it, when it concerns only
routing or recovery, or bring it to the owner, when it would decide a finding,
settle a design question, or change a status; and it MUST record what it decided in
the workflow log.

#### Scenario: The computation cannot classify a change

- **WHEN** `next` reports a change's state as unclassified, and recovering it needs
  only a routing decision
- **THEN** the orchestrating session makes that decision, records it in the
  workflow log, and brings nothing to the owner

### Requirement: CW-m70n The computation routes on exits and directions, never on the phase

The computation MUST route on the exit the last step's outcome names, and on the
owner's latest direction until a later run of its target is logged, and MUST NOT
infer an exit from the phase.

#### Scenario: A triage names sections out of the plan's order

- **WHEN** an implementation round's triage names
  `{"step": "implement", "sections": [["5"]]}` while section 4 is open, and the fix
  commit's validation passed
- **THEN** the computation names a round of section 5, recorded as it starts

### Requirement: CW-l866 A triage's exit is in its outcome, and its file's prose is not routed on

A review's triage MUST name its exit in its outcome, and MUST keep the target and
the owner's words under its triage file's `## Next` as prose, which nothing routes
on. A review whose triage file exists while no finished or returned triage outcome,
and no conversion line, names it MUST be treated as a triage in progress.

#### Scenario: A triage has not finished

- **WHEN** a review's triage file exists and no finished or returned triage outcome
  names the review
- **THEN** the computation names the triage, or the run waiting in it, and no
  review

#### Scenario: A new triage file awaits its outcome

- **WHEN** a review's triage file has `## Next` written as prose beginning with
  "Advance to planning", and no triage outcome names the review
- **THEN** the computation names the triage as in progress, and does not read the
  prose

#### Scenario: A triage file predates `## Next`

- **WHEN** a review's triage file ends with a `## Gate` beginning `Passed`, and no
  triage outcome names the review
- **THEN** the computation names the triage as in progress, since it reads no
  `## Gate`; a change's records are converted when it takes the new code, so that
  its conversion line names each such review

### Requirement: CW-0wna An undeclared exit or an unmet entry guard goes to the owner

An exit its node does not declare, a validation's exit other than the target it was
given, and an exit whose target's entry guard is not met MUST be brought to the
owner.

#### Scenario: A step names an exit its node lacks

- **WHEN** a design run finishes naming `{"step": "plan"}`, an exit the design node
  does not declare
- **THEN** the computation names the owner, with the design's choice and the design
  node's exits

#### Scenario: A validation names another exit

- **WHEN** the computation named validation with closeout as its target, and the
  validation ends finished naming `{"step": "triage", "kind": "implementation"}`
- **THEN** the computation names the owner, with the validation's choice and the
  target it was given

### Requirement: CW-8tdv An unmet exit guard names the step that satisfies it

When a guard on a declared exit is not met, the computation MUST name the step that
satisfies it, carrying the exit as its target, and MUST bring a guard no step can
satisfy to the owner, naming the target and what is missing.

#### Scenario: Triage records another round

- **WHEN** a review's triage named a review of the same kind as its exit, and a
  commit after the commit it reviewed changes more than changes' records — after a
  pre-closeout review, more than paths under `openspec/` and `docs/`
- **THEN** the computation names validation of that commit with the review as its
  target, for an implementation or pre-closeout review, and then the review; with no
  such commit, it names the review again on the same commit

#### Scenario: An implementation round advances

- **WHEN** an implementation round's triage named the plan's next round, and its
  fixes are committed
- **THEN** the computation names validation of the fix commit, with the next round
  as its target, and once it passes, the next round, without the owner; a triage of
  the last round names the pre-closeout review, reached the same way

### Requirement: CW-nkys Validation is always named with a target

The computation MUST name validation with a target always: the round's triage in a
round's join, or the target an owner's direction named after one. It MUST check the
target's guards again on the validation's exit.

#### Scenario: A validation before closeout passes

- **WHEN** the merge after a pre-closeout review's triage named closeout, the
  computation named validation of the merged `HEAD` with closeout as its target,
  and the validation passed, naming closeout as its exit
- **THEN** the computation names closeout

### Requirement: CW-izj1 A confirmed return starts its work afresh

Once the owner confirms a return, the returned review MUST NOT govern what follows,
so the work the return leads to is implemented, validated, and reviewed afresh, as
a round of its own even where it reworks a section the returned round implemented.
A return the owner declined, or one recorded at closeout, MUST be brought to the
owner.

#### Scenario: A triage returns the change

- **WHEN** an implementation round's triage proposed a return naming
  `{"step": "plan"}`, the owner confirmed the return, and the amended plan finished
- **THEN** the computation names the amended plan's next round, not that triage,
  and the round's own validation covers the work-in-progress commit the return left

#### Scenario: A pre-closeout triage returns the change

- **WHEN** a pre-closeout review's triage proposed a return naming
  `{"step": "plan"}`, the owner confirmed the return, and the amended plan added
  nothing to implement
- **THEN** the computation names a validation of `HEAD`, and then a new
  pre-closeout review

#### Scenario: The owner declines a return

- **WHEN** a triage proposed a return and the owner's decision resolved its run
  without directing a step
- **THEN** the computation names the owner, who decides what follows

### Requirement: CW-tnp6 A round and the merge advance only on a passed validation

An implementation round, and the merge before closeout, MUST advance only on a
`passed` validation naming its final commit, or a commit from which it differs only
in changes' records or, for the merge's advance to closeout, only in paths under
`openspec/` and `docs/`. An `inconclusive` validation MUST be brought to the owner,
and a `failed` validation of the merged `HEAD` MUST name the merge again, which
repairs what it found or asks the owner.

#### Scenario: A validation of the merged HEAD fails

- **WHEN** the merge named closeout or a pre-closeout review, and the validation of
  the merged `HEAD` failed
- **THEN** the computation names the merge, carrying the exit it named, so the merge
  repairs what the validation found
- **AND** an `inconclusive` validation of the merged `HEAD` names the owner

#### Scenario: A round's validation is inconclusive

- **WHEN** an implementation round's triage named the plan's next round and the fix
  commit's validation is `inconclusive`
- **THEN** the computation names the owner, with the next round as the target, not
  the next round

### Requirement: CW-ak1z The workflow graph is one table in code

The workflow's steps and transitions MUST be declared as one table in code, which
the computation interprets: each node a step, a review qualified by its kind and a
triage by the kind of review it triages; its exits; the records a join waits for;
the guards on each exit, each naming the step that satisfies it, or the owner where
none can; and its entry guards, each unwaivable or waivable. A change to the table
MUST be made as an OpenSpec change.

#### Scenario: The round's triage waits for its join

- **WHEN** an implementation round's validation has finished and its review and the
  owner's reading have not
- **THEN** the computation names the steps the join still waits for, and no triage

### Requirement: CW-sd34 Exit guards bind steps, and entry guards bind every entry

Exit guards MUST apply to the exits steps take, and MUST NOT be checked against the
owner's directions. Entry guards MUST be checked on every entry to their node: an
unwaivable one MUST refuse every entry while unmet, and a waivable one MUST take the
owner's direction as its override.

#### Scenario: The owner directs past a guard

- **WHEN** the latest validation of `HEAD` failed, and the owner directs the change
  to closeout
- **THEN** the computation names closeout, not the owner or a validation

### Requirement: CW-xo82 The archive guards both sides of closeout

The change's archive MUST be an unwaivable entry guard of the closeout review, its
triage, and archive cleanup, and its absence one of design, planning,
implementation, and the merge before closeout. Closeout MUST be reached by a step's
exit only from the merge.

#### Scenario: A step's exit meets an unmet entry guard

- **WHEN** closeout ends finished naming `{"step": "review", "kind": "closeout"}`,
  and the change's directory is not under the archive
- **THEN** the computation names the owner, with the exit and the entry guard, and
  no closeout review

### Requirement: CW-iaeh A triage needs a record to triage, and a validation a target

A triage node's entry guard MUST be that a review of its kind awaits triage, or a
validation record numbered after the latest review, which is of its kind and not a
design review. Validation's entry guard MUST be unwaivable: that it carries a
target, a node of the table, whose own entry guards MUST be checked on validation's
exit, not on its entry.

#### Scenario: The owner directs the triage of a failed fix validation

- **WHEN** an implementation triage committed a fix and named its exit, the fix
  commit's validation failed, and the owner directs
  `{"step": "triage", "kind": "implementation"}`
- **THEN** the log's writer accepts the direction, since the validation awaits
  triage after the latest review, and that triage, naming the review again beside
  the validation, routes on through its exit's guards

#### Scenario: A round's validation starts before its review is published

- **WHEN** an implementation round's validation and review start from the same
  commit, and no implementation review awaits triage yet
- **THEN** the computation names validation with
  `{"step": "triage", "kind": "implementation"}` as its target, and validation's
  entry guard is met

### Requirement: CW-9tzd Archive cleanup ends at the terminal node

Archive cleanup's exit MUST be the terminal node `done`, which has no exits and no
step, and which no direction reaches.

#### Scenario: Archive cleanup finishes

- **WHEN** archive cleanup ends finished, naming `{"step": "done"}`
- **THEN** the computation names `done`, with the reason `archived`, and no step runs

### Requirement: CW-66kx The graph diagram is held to the table

The source of the graph diagram the capability's documentation shows, and the copy
of it its export embeds, MUST be checked against the table's nodes, exits, joins,
and guards, whatever its layout, by the command's `check graph`; the export's
visible drawing, which draw.io renders from the source it embeds, is not compared.

#### Scenario: The diagram's departures are reported

- **WHEN** the owner runs `scripts/change-workflow check graph` after a change to the
  table
- **THEN** it names each box and edge the diagram's source draws otherwise than the
  table, with the text the table gives it, and fails; and once the source draws the
  table, it says so and succeeds

#### Scenario: The documented diagram drifts

- **WHEN** a change adds an exit to a node and does not update the diagram in the
  capability's documentation
- **THEN** the check comparing that diagram with the table fails, naming the exit
  it does not draw

### Requirement: CW-qu42 An unattended run is limited to its step's table

An unattended run MUST be limited to the tools its step's permission table allows,
and MUST NOT be granted a push other than the guarded push of the change's branch. A
step MUST NOT reset, check out, switch, rebase, stash, or clean.

#### Scenario: A step commits its work

- **WHEN** an unattended implementation run commits a section
- **THEN** it pushes that commit through the guarded push of the change's branch, and
  any other push it attempted would be denied

### Requirement: CW-pehu Writing steps commit and push their work, and validation and review commit nothing

Every step that writes tracked work on the change (design, planning,
implementation, triage, closeout, and archive cleanup) MUST commit it and push it
through the guarded push; validation and review MUST commit nothing.

#### Scenario: A review publishes its record

- **WHEN** an unattended review publishes its record in the change's `reviews/`
- **THEN** the review commits nothing, and its record stays untracked

### Requirement: CW-ajo9 A returning run commits its work in progress, and a stopped run commits nothing

A run that returns the change to an earlier phase MUST commit what it has as work in
progress, check no task for it, and push it; a run that stops MUST leave its partial
work uncommitted, and one stopped by a refusing repository guard or a moved `HEAD`
MUST commit nothing.

#### Scenario: A step stops at its session's limit

- **WHEN** an unattended implementation run stops partway through a section because
  its session reached its limit
- **THEN** its edits stay uncommitted, and the resumed session finishes the section
  and commits it

### Requirement: CW-4yhk A denied run stops, or goes on only by allowed calls

A run that cannot go on without a denied tool MUST end with a stopped outcome naming
the denial, rather than asking a question or working around it; a run that goes on
MUST do so only by calls its step's rules allow.

#### Scenario: Validation attempts to relock

- **WHEN** an unattended validation run attempts to regenerate a lockfile, which
  its table denies
- **THEN** the call is denied, and the run ends stopped, its outcome naming the
  denial

### Requirement: CW-2lvd A deny rule's refusal stands, except a write-steering rule's

A call a deny rule refused MUST NOT be done by another tool, except where the rule
exists only to keep file writes on the Edit and Write tools, as the step table marks
it (sed's in-place forms, find's deleting, running, and writing actions, the diff
family's output-to-file forms), whose refused shell write MAY be made with the Edit
or Write tool the step's rules allow. The run MUST name that substitute in its
message.

#### Scenario: A step is denied by a deny rule

- **WHEN** an unattended run is denied a call that a deny rule forbidding the work
  itself names, such as `git stash`
- **THEN** the denial stands, no other tool does the work, and the run's attempt
  is reported to the owner as a finding

#### Scenario: A step's in-place sed is refused and the step uses the Edit tool

- **WHEN** an unattended run's `sed -i` is refused by the deny rule that keeps file
  writes on the Edit tool, and the run makes the same edit with the Edit tool its
  step's rules allow
- **THEN** the run names the substitute in its message, and the orchestrating
  session reads the denial as a gap, not a workaround, with no ruling asked of the
  owner

### Requirement: CW-2h9t A call no rule allows may be done by an allowed tool

A call denied for want of an allow rule MAY be done by a tool the step's rules allow
for the same work, and the run MUST name that substitute in its message.

#### Scenario: A step does the work of a call no rule names with a tool its rules allow

- **WHEN** an unattended run's shell write is denied because no allow rule names
  it, and the run makes the same edit with the Edit tool its step's rules allow
- **THEN** the run names the substitute in its message, and the orchestrating
  session reads the denial as a gap, not a workaround

### Requirement: CW-svng The orchestrating session reads and classifies each denial

The orchestrating session MUST read each recorded denial from the run's record,
never from the step's message, and classify it by the harness's reason as a gap in
the table or a forbidden action, matching a command refused by its parts, or one
with no reason, against the step's deny rules.

#### Scenario: A denial carries no reason

- **WHEN** a run's record holds a denial for which the harness gave no reason
- **THEN** the orchestrating session matches the call against the step's deny rules
  to classify it as a gap or a forbidden action

### Requirement: CW-5rmh The orchestrating session checks a deny rule's denial for a workaround

After a deny rule's denial, the orchestrating session MUST check the run's later
calls for a workaround, and MUST read a write-steering rule's denial whose write was
made with the Edit or Write tool as a gap, which needs no ruling from the owner.

#### Scenario: A run does a forbidden action another way

- **WHEN** a run denied `git stash` by a deny rule later sets its edits aside with
  another tool
- **THEN** the orchestrating session finds the workaround in the run's later calls
  and reports it to the owner

### Requirement: CW-vdqj The orchestrating session proposes a rule for each gap and records its reading

For a gap, the orchestrating session MUST propose the narrowest rule that matches
the call and say whether it is a one-run grant or a tracked change, and MUST record
its reading in the workflow log as a decision reading that run, before the next
step runs.

#### Scenario: A step is denied a command no rule names

- **WHEN** an unattended run is denied a command because no allow rule names it
- **THEN** the orchestrating session proposes the narrowest allow rule matching the
  call, and the owner grants it for the resumed run or has it committed to the table

### Requirement: CW-jqi7 A waiting outcome is settled after its denials are read

A run whose outcome still waits, such as a question or a proposed return, MUST be
answered or decided after its denials are read, and the reading MUST NOT settle
that outcome.

#### Scenario: A question carries denials

- **WHEN** an unattended validation was denied a command it could do without, went
  on, and ended with a question
- **THEN** the next-step computation names the owner for the reading of the denial
  first, carrying it; once a decision reads that run, the question waits for its
  answer, and the same session resumes with it

### Requirement: CW-drf6 A step's permissions change only on the owner's word

A change to a step's permissions MUST be made by the owner, or on the owner's word
by the orchestrating session, as a tracked change, or granted by the owner for one
run, fresh or resumed. A denial by a deny rule MUST NOT be granted for one run.

#### Scenario: A deny rule's denial is asked to be granted

- **WHEN** the owner asks to grant, for one run, a call a deny rule refused
- **THEN** no grant is made; only a tracked change to the step table can allow it

### Requirement: CW-tl5v A grant holds for one run

A grant MUST be passed on that run's command line, for a fresh run through `start`,
recorded as `granted` on the run's log line, and never added to the table, so the
step's next run is held to its table again.

#### Scenario: The owner grants rules before a fresh run

- **WHEN** the owner grants two rules for a step's next run, which has not started
- **THEN** the orchestrating session starts the run as `scripts/change-workflow
  start <step> <change> --unattended --allow <rule> --allow <rule>`, the run's log
  line records both as `granted`, and the step's run after it is held to its table
  alone

### Requirement: CW-56zq A file rule names a path from the checkout's root

A file-tool rule's relative path, in the table or in a grant, MUST name a path from
the root of the checkout the run starts in, whatever directory the run has since
moved to.

#### Scenario: A step changes directory before writing a file its table allows

- **WHEN** an unattended run changes its working directory into a subdirectory
  and then writes a file its step's relative file rule names from the checkout's
  root
- **THEN** the write is allowed, as it would be from the checkout's root

### Requirement: CW-59c7 The guarded push of a change branch

An agent MAY push a change's own branch without separate approval, only after a
check confirms that `HEAD` is attached, the worktree is clean, the branch is none of
the repository's protected branches, and its upstream has the same name. The push
MUST send exactly `HEAD` and MUST NOT be forced; a branch with no upstream MAY be
pushed to the same name, setting that upstream. The check MUST report a refused
state and MUST NOT repair it.

#### Scenario: The worktree is dirty

- **WHEN** validation is about to push and the worktree has uncommitted changes
- **THEN** the push check fails, nothing is pushed, and nothing is committed or
  discarded to make it pass

### Requirement: CW-p7kq The guarded push runs the repository's pre-push check

Where the repository provides a pre-push check, the guarded push MUST run it before
it pushes and before its check reports success, as Git runs a pre-push hook: the
remote as its argument and one line naming the branch and `HEAD`, as for a new
branch, on its input. A
failing check MUST refuse the push with the check's reasons. The engine MUST reach
the check as a command, never by importing it.

#### Scenario: The pre-push check refuses

- **WHEN** the guarded push runs and the repository's pre-push check fails
- **THEN** nothing is pushed, and the check's reasons are on standard error

#### Scenario: The repository provides no pre-push check

- **WHEN** the guarded push runs in a repository with no pre-push check
- **THEN** it pushes once its own check passes

### Requirement: CW-ebmo Each step runs on its ordered models

Each step's row in the step table MUST name the models its unattended runs use, in
priority order, each with its harness and effort. The wrapper MUST run the first
available model, MUST fall to the next only when one is unavailable (a usage limit,
a missing sign-in, or a missing harness), and MUST record on the run's log line the
model and effort that ran.

#### Scenario: A step's first model is available

- **WHEN** a step's row names a Claude model at high effort and then a Codex model,
  and Claude is available
- **THEN** the run uses the Claude model, and its log line names that model and high
  effort

### Requirement: CW-zq4h The step table's model policy

A repository MAY forbid models, and the step table MUST name none it forbids. A row
MUST NOT list two models of one vendor, and a model of another harness MUST appear
only on a row whose limits that harness can enforce. The wrapper MUST refuse to load
a table that breaks these rules, naming the row.

#### Scenario: A row names two models of one vendor

- **WHEN** the step table names two Claude models on one row
- **THEN** the wrapper refuses to load the table, naming the row

### Requirement: CW-1dld A run with no available model stops, and a waiting run resumes on its own

A run whose models are all unavailable MUST end stopped, naming the reason; a
network error MUST be retried and MUST NOT cause a fallback. A waiting run MUST be
resumed only on the model it ran on.

#### Scenario: A step's only model is at its usage limit

- **WHEN** an unattended triage is started and Claude reports a usage limit
- **THEN** the run ends stopped with the reason and the time the limit resets, and
  nothing runs the step on another harness

### Requirement: CW-clhl A review names a reviewer other than its row's first

A review run on a model other than its row's first MUST name its reviewer's harness
and model in its record, and a review MUST continue a previous reviewer's session
only on the same harness.

#### Scenario: Codex is unavailable for a review

- **WHEN** an implementation review is started and Codex is not signed in
- **THEN** the review runs on the row's next model, Claude, its record and log line
  name the reviewer's harness and model, and triage follows as usual

### Requirement: CW-d1sm The owner may override one review's model

The owner MAY name, for one review run by hand, any model, outside the table's
policy, or an effort for its models; a model named MUST then be the run's only one,
with no fallback, and the record and its log line MUST mark the run as an override.
The orchestrating session MUST NOT name one.

#### Scenario: The owner reviews on a model the table forbids

- **WHEN** the owner runs a review by hand naming a model the repository forbids
- **THEN** the review runs on that model alone, and its record and log line mark it
  as the owner's override

### Requirement: CW-w2ld The orchestrating session's model is the step table's

The step table MUST name the orchestrating session's model and effort in a row of
its own, which carries no permission rules, and the orchestrating session MUST be
started on that model and effort.

#### Scenario: The owner starts the orchestrating session

- **WHEN** the owner runs `scripts/change-workflow start orchestrate <change>`
- **THEN** the session starts on the model and effort the step table's
  `[orchestrator]` row names

### Requirement: CW-yzer Each unattended run records its own cost

Each unattended run's log line MUST record its cost: for a Claude run, the dollars,
turns, duration, and input, output, cache-read, and cache-write tokens of that run
alone, over all its turns; for a Codex review, the tokens it reports. Where a run's
own dollars cannot be told from its session's earlier turns, after a crashed run or
turns the wrapper did not run, the line MUST mark its dollars as partial.

#### Scenario: A run follows a crashed run in its session

- **WHEN** a resumed run's session holds the turns of a crashed run whose cost the
  wrapper never recorded
- **THEN** the run's line marks its dollars as partial

### Requirement: CW-u7da A resumed run records its gap, and cost is reported by step and round

A resumed run MUST also record the time since its session's last turn of any kind
and whether its first turn read the prompt cache. The cost of a change's runs MUST
be reportable by step and by round, with the cache misses and their gaps listed.

#### Scenario: A discussion turn is resumed after a long gap

- **WHEN** a triage session is resumed two hours after its previous run, and its
  first turn rewrites its context to the prompt cache
- **THEN** the run's line records the gap, a cache miss, and the run's own cost,
  not the session's running total, and the cost report lists the miss with its gap

### Requirement: CW-yib2 A change may be worked in a clone of its own

A change MAY be worked in a clone of the owner's workspace of its own, which holds
its branch, its records, its environments, its evidence, and its step sessions, or
MAY instead be worked in the owner's workspace itself. Two changes' clones MUST NOT
move each other's branches, write each other's records, or rebuild each other's
environments.

#### Scenario: Two changes are worked at once

- **WHEN** one change's validation runs in its clone and another change's
  implementation runs in its own
- **THEN** neither moves the other's branch, writes the other's records, or
  rebuilds the other's environments

### Requirement: CW-4x66 The computation names a change's clone, or brings workspace records to the owner

When a change's branch is checked out neither in a clone of its own nor in the
checkout the computation runs in, the computation MUST name the creation of its
clone, and the orchestrating session MUST create it, and the branch when it does not
exist; but when the workspace already holds the change's records, the computation
MUST NOT name the clone and MUST bring the change to the owner, naming both routes:
working it in the workspace, or moving it into a clone by hand.

#### Scenario: Feature work begins on a change

- **WHEN** the owner starts the orchestrating session for a change whose branch no
  clone holds
- **THEN** the computation names the clone, the orchestrating session creates it
  with the change's branch, and design runs while the clone's bootstrap continues
  in the background
- **AND** the computation names no implementation or validation until the
  bootstrap has succeeded

#### Scenario: A change already under way in the workspace

- **WHEN** the owner starts the orchestrating session for a change whose branch no
  clone holds and whose records are in the owner's workspace
- **THEN** the computation names no clone and brings the change to the owner,
  naming both routes: checking out its branch in the workspace and working it there,
  or moving it into a clone by hand

### Requirement: CW-8jyb Creating a clone is safe to repeat

Creating a clone MUST be safe to repeat: it MUST finish a clone left incomplete, and
MUST refuse, deleting nothing, a directory that is not a clone of the workspace, has
another branch checked out, or has uncommitted changes. The clone's `origin` MUST be
the workspace's `origin`, and one of its remotes MUST name the workspace.

#### Scenario: Clone creation was interrupted

- **WHEN** an orchestrating session restarts after creating a change's clone only
  in part
- **THEN** the computation names the clone again, and creating it finishes the
  steps not yet done without recloning or deleting anything

### Requirement: CW-8npg A clone's bootstrap gates implementation and validation

A clone's bootstrap, the repository's own, MAY run while design proceeds;
implementation and validation MUST NOT start before it has succeeded. Its state MUST
be recorded so that running, succeeded, and failed are told apart, and a failed
bootstrap MUST be brought to the owner, naming its log, rather than retried by
itself.

#### Scenario: The bootstrap failed

- **WHEN** a clone's bootstrap ended with a failure, or its process died without
  recording a status
- **THEN** the computation names no implementation or validation, and the failure
  is brought to the owner naming its log; creating the clone again restarts the
  bootstrap

### Requirement: CW-hak6 Archive cleanup copies a change's history into the workspace

As its last act, after every record it writes, archive cleanup MUST copy the
change's records, and the validation evidence they name, into the owner's workspace
at the same paths; once archive cleanup's own outcome is logged, the orchestrating
session MUST repeat the copy, so the workspace holds that outcome too.

#### Scenario: Records grow after archive cleanup copied them

- **WHEN** archive cleanup's outcome is appended to the clone's workflow log after
  its copy, and another round on the pull request writes a record in the clone
- **THEN** the next copy, or clone removal's own, extends the workspace's log and
  adds the record, overwriting nothing

### Requirement: CW-rf50 Copying a change's history overwrites nothing

The copy of a change's history MUST be safe to repeat, MUST extend a file in the
workspace whose contents are a prefix of the clone's, and MUST NOT otherwise
overwrite a file there, refusing and naming any whose contents differ.

#### Scenario: A copied record conflicts

- **WHEN** a file in the owner's workspace differs from the clone's other than by
  the clone's having grown it
- **THEN** the copy refuses, naming the file, and clone removal deletes nothing

### Requirement: CW-c3he A step looks for records in its checkout, then in the workspace

A step that reads another change's or an earlier change's records MUST look for
them in its own checkout and then in the owner's workspace.

#### Scenario: A later session needs a cleaned-up change's history

- **WHEN** a design session reads the reviews of a change whose archive was cleaned
  up in its clone
- **THEN** it finds them in the owner's workspace, at the archived change's path,
  even where the workspace's branch also carries the change's active directory
  without them, and a report of the change's cost or log reads them there

### Requirement: CW-xx5f A clone is removed only once its work is safe

A clone MUST be removed only on the owner's command. The removal MUST first repeat
the copy, and MUST proceed only once the clone's records, and the named evidence it
holds, are in the workspace with identical contents, its branch is merged, and it
holds no commit and no change its `origin` lacks; named evidence the clone does not
hold MUST be named in the removal's report.

#### Scenario: The owner removes a clone too early

- **WHEN** the owner asks to remove a clone whose branch is not merged, or whose
  records are not all in the workspace
- **THEN** the removal is refused, naming what is missing, and nothing is deleted

### Requirement: CW-ikmm Archive cleanup removes a change's validation resources

Archive cleanup MUST run the repository's removal of a change's validation
resources, where the repository's validation leaves any.

#### Scenario: A change's validation left resources

- **WHEN** archive cleanup runs for a change whose validation left resources the
  repository removes after a change lands
- **THEN** archive cleanup runs that removal and reports what it removed

### Requirement: CW-d8de Each skill has one source for every harness

Each agent skill committed to the repository MUST have exactly one source, and MUST
be loadable by every supported agent harness from that source. A skill MUST NOT be
maintained as separate copies for different harnesses, and every harness entry for
a skill MUST resolve.

#### Scenario: A skill is edited

- **WHEN** a contributor edits a committed skill
- **THEN** every harness loads the edited skill, with no second copy to update

#### Scenario: A harness entry does not resolve

- **WHEN** a harness skill entry points at a source that does not exist
- **THEN** the repository's skill check fails

### Requirement: CW-5qne The engine's interfaces are tiered

Each interface of the engine MUST be classified as public, which an adopting
repository, a person, or a runner may rely on; provisional, public with a named
successor expected; or internal, used only by the engine and its shipped skills.
The command's subcommands, flags, exit-status categories, and structured outputs,
and the skills' names and argument forms, MUST be public unless classified
otherwise by name; report text written for a person MUST carry no promise.

#### Scenario: A provisional subcommand is replaced

- **WHEN** the change named as `convert`'s successor removes it
- **THEN** the removal is not an incompatible change, since `convert` is
  provisional

#### Scenario: An internal marker changes

- **WHEN** the engine renames the variable that marks an unattended run in a
  step's environment
- **THEN** no public interface changes, since only the engine reads it

#### Scenario: A report is reworded

- **WHEN** a workflow change rewords `history`'s report or a check's message, and
  changes no exit status and no structured output
- **THEN** its proposal records no change to a public interface for it

### Requirement: CW-m7fk The command's exit statuses fall in three categories

Every subcommand of the command MUST exit 0 for success; 1 for a refusal or a failed
check, writing its reason to standard error; and 2 for a usage error, such as a
malformed or missing argument.

#### Scenario: A subcommand is given a malformed argument

- **WHEN** `scripts/change-workflow start implement <change> --sections 3-1` is run
- **THEN** it exits 2, as a usage error, and starts nothing

#### Scenario: A check fails

- **WHEN** `scripts/change-workflow check tasks <change>` finds a task numbered for
  one section under another section's heading
- **THEN** it exits 1, its reason on standard error

### Requirement: CW-c2tw Compatibility is judged by semantic versioning

An incompatible change to a public interface MUST be counted as a major change, a
compatible one as minor, and one limited to internals as a patch; while the major
version is 0, an incompatible change MUST be counted as minor. A proposal that
changes the workflow MUST name each public interface it changes and whether the
change is compatible.

#### Scenario: A public flag is removed

- **WHEN** a workflow change removes a flag of `start`
- **THEN** its proposal names the flag and the change as incompatible

#### Scenario: An output gains a field

- **WHEN** a workflow change adds an optional field to `next`'s output
- **THEN** its proposal names the output and the change as compatible

### Requirement: CW-9fbu The graph's vocabulary is closed

The graph's node names, review kinds, and target shape MUST be public, and an
adopting repository MUST NOT add to them. A reader of an outcome, a direction, or
a log line that names a node or kind it does not know MUST report it by name and
MUST NOT route on it. The step names and review kinds the engine uses MUST come
from the graph's declaration alone.

#### Scenario: A log names an unknown node

- **WHEN** the next-step computation reads a line whose exit names
  `{"step": "deploy"}`, which its graph does not declare
- **THEN** it names the owner with the unknown node, and routes on no later line

#### Scenario: A review kind is added to the graph

- **WHEN** the graph's declaration gains a review kind
- **THEN** the outcome check and the log's writer accept that kind with no other
  list to update

### Requirement: CW-m4ps An adopting repository provides the workflow's roles

The workflow MUST state each role an adopting repository provides, such as a local
validation command, the change index, and protected branches, with the skills that
use it. A repository MUST state how it provides each. A test MUST fail on a make
target or repository path the skills, step table, or make fragment name that the
statement omits. The engine's own assumptions — its paths, commands, remotes,
environment variables, and tools — MUST be listed too, marked as maintained by
review.

#### Scenario: A skill names a new target

- **WHEN** a skill is edited to run `make check-something` and this repository's
  statement of its roles does not list that target
- **THEN** the test fails, naming the target and the skill

#### Scenario: A role has no provision

- **WHEN** the workflow states a role this repository's statement does not provide
- **THEN** the test fails, naming the role

## REMOVED Requirements

### Requirement: Phases and owner touchpoints

**Reason**: Rewritten against the capability's outline as requirements of one
behaviour each, under 500 characters, with ids; the merge's default branch is this
repository's value.
**Migration**: CW-ab9h, CW-nfdb, CW-hdxi, CW-a6ow, CW-9pbk, CW-ksnu, CW-trdu,
CW-pkug, CW-1iaz, CW-z83w, CW-neua, CW-3tvs, CW-7d5f; the default branch the merge
brings in, `dev`, moves to `market-change-workflow` as MCW-ca51.

### Requirement: Index transitions are written by the step that makes them

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-uj2q, CW-jyff.

### Requirement: Review records

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-p2b2, CW-2nb2, CW-ovuj, CW-5e24, CW-r9d2.

### Requirement: Finding lens, basis, and severity

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-5sc1, CW-7d5f.

### Requirement: Triage of every finding

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-j1nv, CW-neua.

### Requirement: Intervention ledger

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-zidp, CW-xe8m, CW-w22z, CW-1jxh.

### Requirement: Implementation sections and sessions

**Reason**: Rewritten as requirements of one behaviour each, with ids; the evidence a
section may owe validation is named by the repository's validation part.
**Migration**: CW-5r7l, CW-5h8e, CW-0ia3, CW-al17, CW-v6nj, CW-tc82, CW-1u53; the
form of owed CI evidence, its workflow, job, and what the job must show, moves to
`market-change-workflow` as MCW-gvqb.

### Requirement: Validation observes a committed slice

**Reason**: Its general rules are rewritten as requirements of one behaviour each,
with ids, and validation's parts become the repository's; this repository's parts
are its own requirements.
**Migration**: CW-a7dw, CW-af15, CW-zkhs, CW-e7lm, CW-a1nz, CW-av28; this
repository's parts move to `market-change-workflow`: the packages built from the
commit, MCW-v3tf; the pipeline's evidence, MCW-zk52; the owed CI workflows and their
dispatch list, MCW-3i99; the owed jobs judged and the comparison with `dev`,
MCW-7hr1, MCW-2lzw, MCW-3yqn; the images and render checks, MCW-qeja; the Helm
end-to-end run, MCW-8h0r.

### Requirement: Guarded push of a change branch

**Reason**: Rewritten with an id; the protected branches and the refusal of private
content are the repository's.
**Migration**: CW-59c7; the repository's pre-push check it runs, CW-p7kq; `main`
and `dev` as the protected branches move to `market-change-workflow` as MCW-farr,
and the refusal of recognizable private content, this repository's pre-push check,
as MCW-q8vd.

### Requirement: Triage of an implementation round

**Reason**: Rewritten as requirements of one behaviour each, with ids; the round
view's mechanics are requirements of their own.
**Migration**: CW-qtxb, CW-514y, CW-xg4v, CW-rb5n, CW-j1ab, CW-gqav for the triage;
CW-aoby, CW-4svs, CW-9mrq, CW-78ul, CW-n44s, CW-uq5q, CW-gd24, CW-rgws, CW-te38 for
the round's reading.

### Requirement: Harness-neutral agent skills

**Reason**: Rewritten with an id.
**Migration**: CW-d8de.

### Requirement: An orchestrating session advances one change

**Reason**: Rewritten as requirements of one behaviour each, with ids; the merges it
makes are of the branch the change lands on.
**Migration**: CW-ms3j, CW-5jlj, CW-yvo1, CW-mkwj, CW-0ia3, CW-op72, CW-bsmk,
CW-tax4, CW-6scj, CW-6fi2.

### Requirement: Unattended step runs end with a structured outcome

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-js86, CW-5ldi, CW-4vma, CW-1a4d, CW-4c3e, CW-k5mk, CW-r9d2,
CW-xgq3, CW-ht4h, and, for its scenarios, CW-a1nz, CW-1u53, CW-zcx8, CW-jtsl.

### Requirement: The next step is computed from the files

**Reason**: Rewritten as requirements of one behaviour each, with ids; the
conversion's rules are requirements of their own.
**Migration**: CW-4rqr, CW-tel3, CW-m70n, CW-l866, CW-0wna, CW-8tdv, CW-nkys,
CW-izj1, CW-tnp6, CW-lyr4 for the computation, and, for its scenarios, CW-4c3e,
CW-ht4h, CW-a6ow, CW-trdu, CW-v6nj; CW-qj77, CW-h12x, CW-42me, CW-o1ca, CW-zniv,
CW-ajcm, CW-95xp, CW-v8mq for the conversion.

### Requirement: Discussion steps stay conversations with the owner

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-3tvs, CW-p1us.

### Requirement: Unattended runs are held to their step's permissions

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-qu42, CW-pehu, CW-ajo9, CW-k5mk, CW-4yhk, CW-2lvd, CW-2h9t,
CW-svng, CW-5rmh, CW-vdqj, CW-jqi7, CW-drf6, CW-tl5v, CW-56zq, CW-mzyz.

### Requirement: A design blocked on a prerequisite halts

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-dtpz, CW-p7xk.

### Requirement: Unattended steps run on their step's ordered models

**Reason**: Rewritten as requirements of one behaviour each, with ids; the models a
repository forbids are its own.
**Migration**: CW-ebmo, CW-zq4h, CW-1dld, CW-clhl, CW-d1sm; the forbidden Fable and
Astra models move to `market-change-workflow` as MCW-y37w.

### Requirement: Unattended runs record their cost

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-yzer, CW-u7da.

### Requirement: Each change is worked in its own clone

**Reason**: Rewritten as requirements of one behaviour each, with ids; the clone's
bootstrap is the repository's.
**Migration**: CW-yib2, CW-4x66, CW-8jyb, CW-8npg, CW-hak6, CW-rf50, CW-c3he,
CW-xx5f; the bootstrap command, `make init`, is stated in `market-change-workflow`
as MCW-uqlq.

### Requirement: Each Helm validation is isolated in its change's namespace

**Reason**: It holds only for this repository's Helm validation.
**Migration**: The requirement moves whole to `market-change-workflow`, as
MCW-fnuh, MCW-a0hu, MCW-notv, MCW-7bia, MCW-epkd, and MCW-7ts3; archive
cleanup's running of the repository's removal of a change's validation resources is
CW-ikmm.

### Requirement: The workflow graph is declared in code

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-ak1z, CW-sd34, CW-xo82, CW-iaeh, CW-9tzd, CW-66kx, and, for a
scenario, CW-78ul.

### Requirement: Interactive step runs record their outcome

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-mzyz, CW-gnqh.

### Requirement: The owner directs a change's next step

**Reason**: Rewritten as requirements of one behaviour each, with ids.
**Migration**: CW-jtsl, CW-zcx8, CW-uhdy, CW-eups, and, for a scenario, CW-sd34.
