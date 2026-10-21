## ADDED Requirements

### Requirement: Each change is worked in its own clone

A change MAY be worked in a clone of the owner's workspace of its own, which holds
its branch, its records, its environments, its evidence, and its step sessions; a
change MAY instead be worked in the owner's workspace itself. When a change's branch
is checked out neither in a clone of its own nor in the checkout the next-step
computation runs in, the computation MUST name the creation of its clone, and the
orchestrating session MUST create it and, when the branch does not exist, the
branch — unless the workspace already holds the change's records, when the
computation MUST NOT name the clone and MUST bring the change to the owner, naming
both routes: working it in the workspace, or moving it into a clone by hand.
Creating a clone MUST be safe to repeat: it MUST finish a clone left
incomplete, and MUST refuse, deleting nothing, a directory that is not a clone of
the workspace, has another branch checked out, or has uncommitted changes. The
clone's `origin` MUST be the workspace's `origin`, and one of its remotes MUST name
the workspace. The clone's bootstrap MAY run while design proceeds; implementation
and validation MUST NOT start before it has succeeded. Its state MUST be recorded
so that running, succeeded, and failed are told apart, and a failed bootstrap MUST
be brought to the owner, naming its log, rather than retried by itself. As its last
act, after every record it writes, archive cleanup MUST copy the change's records,
and the validation evidence they name, into the owner's workspace at the same
paths; the copy MUST be safe to repeat, MUST extend a file there whose contents
are a prefix of the clone's, and MUST NOT otherwise overwrite a file there,
refusing and naming any whose contents differ. A step that reads another change's
or an earlier change's records MUST look for them in its own checkout and then in
the owner's workspace. A clone MUST be removed only on the owner's command; the
removal MUST first repeat the copy, and MUST proceed only once the clone's records
and named evidence are in the workspace with identical contents, its branch is
merged, and it holds no commit and no change its `origin` lacks.

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

#### Scenario: Clone creation was interrupted

- **WHEN** an orchestrating session restarts after creating a change's clone only
  in part
- **THEN** the computation names the clone again, and creating it finishes the
  steps not yet done without recloning or deleting anything

#### Scenario: The bootstrap failed

- **WHEN** a clone's bootstrap ended with a failure, or its process died without
  recording a status
- **THEN** the computation names no implementation or validation, and the failure
  is brought to the owner naming its log; creating the clone again restarts the
  bootstrap

#### Scenario: Two changes are worked at once

- **WHEN** one change's validation runs in its clone and another change's
  implementation runs in its own
- **THEN** neither moves the other's branch, writes the other's records, or
  rebuilds the other's wheelhouse

#### Scenario: A later session needs a cleaned-up change's history

- **WHEN** a design session reads the reviews of a change whose archive was cleaned
  up in its clone
- **THEN** it finds them in the owner's workspace, at the archived change's path

#### Scenario: The owner removes a clone too early

- **WHEN** the owner asks to remove a clone whose branch is not merged, or whose
  records are not all in the workspace
- **THEN** the removal is refused, naming what is missing, and nothing is deleted

#### Scenario: Records grow after archive cleanup copied them

- **WHEN** archive cleanup's outcome is appended to the clone's workflow log after
  its copy, and another round on the pull request writes a record in the clone
- **THEN** the next copy, or clone removal's own, extends the workspace's log and
  adds the record, overwriting nothing

#### Scenario: A copied record conflicts

- **WHEN** a file in the owner's workspace differs from the clone's other than by
  the clone's having grown it
- **THEN** the copy refuses, naming the file, and clone removal deletes nothing

### Requirement: Each Helm validation is isolated in its change's namespace

Validation's Helm part MUST deploy into a namespace of its change's own, derived
from the change's name, and MUST NOT install, upgrade, remove, or scale a release
or volume in any other namespace. The images it deploys MUST carry a tag fixed per
change, so that two changes' builds never write one tag; it MUST NOT tag them by
commit. Before deploying, it MUST remove every volume the change's previous
deployment wrote, including the volumes created for its tests out of band, and
MUST create the namespace's out-of-band Secrets. It SHOULD upgrade the release in
place from zero replicas, and MAY uninstall and install it when the upgrade is
refused, saying so. Its scenarios MUST run inside the namespace and MUST NOT depend
on a local port. After the scenarios it MUST keep every pod's log and the
namespace's events with the attempt's evidence, and MUST scale the namespace's
workloads to zero. A preflight MUST compare the memory a release is recorded to
need, times the releases that would be running, with what the node can allocate,
and MUST treat a deployment that would not fit as an environmental failure; it is
an estimate and reserves nothing. When no figure is recorded, or usage cannot be
measured, it MUST warn and go on. A pod that fails for memory after a passed
preflight MUST be classified as any validation failure is, from the namespace's
events, the other namespaces' workloads at the time, and the rendered requests and
limits: as environmental only when that evidence shows contention for the node's
memory, and otherwise as caused by the commit or of unknown cause.
Archive cleanup MUST remove the change's namespace and images and MUST record the
memory the change's latest validation measured, with when it was measured; where
two branches' recorded figures conflict at a merge, the one measured later MUST be
kept.

#### Scenario: Two changes are validated at once

- **WHEN** two changes' Helm parts run at the same time on one cluster
- **THEN** each builds its own images under its own tags, deploys into its own
  namespace, and runs its scenarios against its own release, and neither removes,
  replaces, or reaches the other's

#### Scenario: A change is validated again

- **WHEN** a change's earlier validation left its namespace scaled to zero with its
  volumes
- **THEN** validation deletes those volumes, recreates the Secrets, and upgrades the
  release, whose pods start new on the images just built against empty volumes

#### Scenario: An earlier run crashed with its workloads up

- **WHEN** validation finds the change's workloads running from a run that ended
  without scaling them down
- **THEN** it scales them to zero before deleting the volumes

#### Scenario: Usage cannot be measured

- **WHEN** the cluster has no metrics source
- **THEN** the preflight warns that no memory figure will be recorded, and the part
  goes on

#### Scenario: No memory figure is recorded yet

- **WHEN** a validation's preflight runs before any archive cleanup has recorded
  the memory a release needs
- **THEN** it warns that the check was skipped, and the part goes on

#### Scenario: Two validations pass the preflight together

- **WHEN** two changes' preflights pass before either deploys, and one's pods then
  cannot be scheduled or are evicted for memory while the other's workloads are up
- **THEN** that validation's failure is diagnosed as environmental, with the remedy
  of scaling another change's namespace to zero or running again once it is down

#### Scenario: A commit's own pod is killed for memory

- **WHEN** a pod is killed at its own memory limit after a passed preflight, and the
  commit changed the rendered requests or limits or the evidence shows no
  contention
- **THEN** the failure is reported as caused by the commit or of unknown cause, so
  validation fails and the failure is triaged

#### Scenario: A change's archive is cleaned up

- **WHEN** archive cleanup runs for a change validated on Helm
- **THEN** the change's namespace and images are removed, and the memory its latest
  validation measured is recorded for the preflight

## MODIFIED Requirements

### Requirement: Triage of an implementation round

The implementation review, the validation of the same commit, and the owner's own
notes on it MUST be triaged together, in a session that is not the implementing
session. A review published by the review tooling MUST name the commit it reviewed,
so the commits can be compared mechanically; for a pasted review, triage MUST record
the commit the owner says its reviewer saw. A review and a validation of different
commits MAY be triaged as one round only when the owner waives the rule, judging the
changes between them; the waiver MUST be recorded in the intervention ledger. Each
validation failure caused by the commit, or of unknown cause, MUST be presented as a
finding, with its diagnosis checked against the logs; an `inconclusive` part MUST be
read as missing evidence, never as a finding. The owner's notes MUST be saved
verbatim as a review record and triaged like any review: the triaging agent MUST
state its own position on each point rather than carry it out as an instruction, and
each disposition MUST be logged to the intervention ledger. Accepted fixes MUST pass
the checks a section passes before they are committed, and the commit MUST be
validated again, unless, after a pre-closeout review, it changes only paths under
`openspec/` and `docs/`. A triage of any kind MUST commit the tracked edits its
dispositions made, with a fix or alone, and push them. The owner MUST be able to read a round as one set of changes from the
commit the previous round ended on to the round's commit, without any commit being
changed to show it. For a change worked in its own clone, the reading MUST take place
in the owner's workspace, on that workspace's copy of the change's branch, and MUST
NOT move the branch in the clone; validation and the implementation review MUST start
when the round's sections are committed, beside the reading; and triage MUST NOT start
until the owner has answered on the round, with notes or with none, and the answer is
saved as the round's owner record. For a change worked in the owner's workspace, while
its branch is moved to show the round, review, validation, triage, and implementation
MUST NOT start. Ending the reading MUST return the branch to the round's commit when
the owner made no commit while it was moved, and otherwise to the last of those
commits carried onto the round's commit; the round's own commits MUST NOT change. A
view MUST NOT move a checkout in which an unattended run is in progress. Ending the
reading MUST carry each commit the owner made while the branch was moved onto the
round's commit, holding exactly the paths that commit changed at the content it gave
them, and MUST leave every edit the owner did not commit uncommitted. It MUST carry a
path the round also changed only when the commit's version holds every change the
round made to that path, and MUST refuse without moving the branch when it does not,
when any such commit is a merge, or when the branch has left the line of the round's
base. A path the round added, deleted, or changed as a binary file, a symlink, or a
mode MUST be carried only when the commit's version is the round's — absent, for a
path the round deleted — and an absent path MUST NOT be taken for an empty file. A
view MUST NOT be
moved to a new head while such commits or uncommitted edits are present. A commit the
owner makes on the change's branch while reading MUST reach the clone only through a
fast-forward triage makes. A pre-closeout review MUST NOT run, and its triage MUST NOT
advance the change, unless the latest validation's result is `passed` and it names
`HEAD`, or a commit from which `HEAD` descends and differs only in changes' intervention
ledgers and review records, except where the owner overrides it. Once a pre-closeout
review's triage has run, a commit from which `HEAD` differs only in paths under
`openspec/` and `docs/` MUST be accepted in the same way, since closeout's own checks
read them again.

#### Scenario: The owner's note is contradicted by the files

- **WHEN** a point in the owner's notes rests on a claim the files contradict
- **THEN** triage says so, with the evidence, and nothing changes until the owner
  has recorded a disposition

#### Scenario: A review and a validation describe different commits

- **WHEN** a round's review names a different commit from its validation record
- **THEN** triage names both commits and what changed between them, and treats
  them as one round only on the owner's recorded waiver; otherwise the reviewed
  commit is validated or the validated commit reviewed first

#### Scenario: A ledger line is committed after the validation

- **WHEN** the latest validation passed for a commit, and the only commit since adds
  a line to a change's intervention ledger
- **THEN** a pre-closeout review may run without the commit being validated again

#### Scenario: A pre-closeout triage commits only documents

- **WHEN** a pre-closeout review's triage advances the change with no fix, and
  commits its edits to the change's documents and the index row after the latest
  validation passed
- **THEN** closeout starts without the commit being validated again

#### Scenario: An implementation triage commits only documents

- **WHEN** an implementation round's triage commits an edit to the change's task
  list after the latest validation passed, with no fix
- **THEN** that commit is validated before the next round or the pre-closeout review

#### Scenario: The owner reads a round committed section by section

- **WHEN** the owner reads a round of a change worked in its own clone
- **THEN** the round is shown in the owner's workspace as uncommitted changes over the
  commit the previous round ended on, on the change's branch by name, and when the
  reading ends with no commit made during it that branch is back at the round's
  commit with the commits unchanged
- **AND** the branch in the change's clone never moves

#### Scenario: Validation runs while the owner reads

- **WHEN** a round's sections are committed in a change's clone
- **THEN** validation and the implementation review start there while the owner reads
  the round, and triage starts only once the owner has answered on the round and both
  records exist

#### Scenario: The owner has no notes

- **WHEN** the owner answers that a round raises nothing
- **THEN** that answer is saved as the round's owner record, the view is closed, and
  triage starts

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

#### Scenario: The owner commits part of a file the round changed

- **WHEN** a commit made during the view holds a file the round also changed without
  some of the round's changes to it, whether they were left unstaged or removed
- **THEN** ending the reading refuses, naming the file and how to commit it again on
  the round's commit, and the branch is not moved

#### Scenario: The owner commits a whole file the round changed, then edits on

- **WHEN** a commit made during the view holds a file the round changed with all of
  the round's changes and the owner's edit, and the owner edits the file again
  without committing
- **THEN** ending the reading carries the commit, and the later edit stays
  uncommitted

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

#### Scenario: The owner merges during the view

- **WHEN** a commit made during the view has two parents
- **THEN** ending the reading refuses, naming the commit, and the branch is not moved

#### Scenario: The view is refreshed over the owner's commit

- **WHEN** the owner opens the view again while a commit made during it is on the
  branch
- **THEN** the view is refused, naming the commit and the command that ends the
  reading

#### Scenario: A view would move a checkout with a run in progress

- **WHEN** the owner opens a view in a workspace where an unattended run is in progress
- **THEN** the view is refused, naming the run, and nothing is checked out

#### Scenario: Validation fails beside an implementation review

- **WHEN** an implementation round's validation reports a failing scenario
- **THEN** the failure is triaged as a finding of the round, fixed after the owner's
  disposition, and the fix commit is validated again

### Requirement: An orchestrating session advances one change

The repository owner MAY advance one change through its steps from one orchestrating
session. The orchestrating session MUST hold no state beyond the change's files and
its workflow log, so that a new session resumes the change from them alone. It MUST
run the next step the next-step computation names, and MUST advance without the
owner wherever the computation names a step. It MUST bring every question a step
raises to the owner, showing each step's message as written, and MUST NOT answer a
design question or decide or state a position on a finding. It MAY create the
change's clone and branch, and MAY commit changes to the workflow itself — skills,
the step table, and what else the owner explicitly asks for — in the change's clone,
on its branch; it MUST NOT commit the change's own feature work. It MUST NOT read
code, reviews, or change documents to form or state a view of a finding or a design
question; it MAY read what routing and recovery need: the computation and the inputs
it names, the workflow log, and the denials report.
It MAY report misbehaviour of the workflow's own tooling that it observed across
steps, as a numbered record marked as its own, for the next triage. When the owner
waives another design review for a design decision made after a return, it MUST
record the owner's word as a decision directing planning, and the next-step
computation MUST then name planning. It MUST advance only the change it was started
for.

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

#### Scenario: A review's triage has nothing for the owner

- **WHEN** a review and the validation beside it raised no finding, and the
  owner's notes raise no point to dispose of
- **THEN** the triage records that the change advances, and the orchestrating
  session runs the next step without asking the owner

#### Scenario: The owner waives a design review after a return under orchestration

- **WHEN** planning returned a change to design, the design step settled the
  decision and finished, and the owner tells the orchestrating session they waive
  another design review
- **THEN** the owner's word is recorded in the workflow log as a decision directing
  planning, the waiver is recorded in the intervention ledger, and the computation
  names planning rather than a design review

#### Scenario: A finding is relayed

- **WHEN** an orchestrated triage presents a finding
- **THEN** the orchestrating session shows the triage's message as written, adds no
  position of its own, and resumes the triage with the owner's reply

#### Scenario: The owner asks for a permission fix

- **WHEN** a run is denied a command for want of a rule, and the owner asks the
  orchestrating session to add the rule
- **THEN** it edits the step table in the change's clone and commits the edit on the
  change's branch, so the step's next run is held to the new rule

### Requirement: Unattended runs are held to their step's permissions

An unattended run MUST be limited to the tools its step's permission table allows,
and MUST NOT be granted a push other than the guarded push of the change's branch.
Every step that commits work on the change MUST push it through that guarded push
after committing. Every denial a
run records MUST be recorded on the run's outcome, from the run's own record and
with the harness's reason when it gives one; the harness gives none for a call a
deny rule refused. A run that cannot go on without a denied tool MUST end
with a stopped outcome naming the denial, rather than asking a question or working
around it; a run that goes on MUST do so only by calls its step's rules allow. A
call a deny rule refused MUST NOT be done by another tool; a call denied for want
of an allow rule MAY be done by a tool the step's rules allow for the same work,
and the run MUST name that substitute in its message. The orchestrating session
MUST read each recorded denial from the run's record, never from the step's
message; classify it by the harness's reason, or its absence, as a gap in the
table or a forbidden action; check the run's later calls, after a deny-rule
denial, for a workaround; propose, for a gap, the narrowest rule that matches the
call and say whether it is a one-run grant or a tracked change; and record its
reading in the workflow log as a
decision reading that run, before the next step runs. A run whose outcome still
waits — a question, a proposed return — MUST be answered or decided after its
denials are read, and the reading MUST NOT settle that outcome. A denial by a
deny rule MUST NOT be granted for one run. A
change to a step's permissions MUST be made by the owner or, on the owner's word, by
the orchestrating session, as a tracked change, or granted by the owner for one
resumed run. Interactive runs MUST NOT be restricted by the table.

#### Scenario: Validation attempts to relock

- **WHEN** an unattended validation run attempts `make lock`
- **THEN** the call is denied, and the run ends stopped, its outcome naming the
  denial

#### Scenario: A step is denied a command no rule names

- **WHEN** an unattended run is denied a command because no allow rule names it
- **THEN** the orchestrating session proposes the narrowest allow rule matching the
  call, and the owner grants it for the resumed run or has it committed to the table

#### Scenario: A step does the work of a call no rule names with a tool its rules allow

- **WHEN** an unattended run's shell write is denied because no allow rule names
  it, and the run makes the same edit with the Edit tool its step's rules allow
- **THEN** the run names the substitute in its message, and the orchestrating
  session reads the denial as a gap, not a workaround

#### Scenario: A question carries denials

- **WHEN** an unattended validation was denied a command it could do without, went
  on, and ended with a question
- **THEN** the next-step computation names the owner for the reading of the denial
  first, carrying it; once a decision reads that run, the question waits for its
  answer, and the same session resumes with it

#### Scenario: A step is denied by a deny rule

- **WHEN** an unattended run is denied a call that a deny rule names
- **THEN** the denial stands, and the run's attempt is reported to the owner as a
  finding

#### Scenario: A step commits its work

- **WHEN** an unattended implementation run commits a section
- **THEN** it pushes that commit through the guarded push of the change's branch, and
  any other push it attempted would be denied

### Requirement: The next step is computed from the files

The next step of a change MUST be computed by a script from the change's index row,
its reviews and their triage, its tasks, its workflow log, and the state of any open
round view, and the same
computation MUST be available to the owner by hand. When the computation fails or
cannot classify the change's state, the orchestrating session MUST determine what
happened and either resolve it, when it concerns only routing or recovery, or bring
it to the owner, when it would decide a finding, settle a design question, or
change a status; and MUST record what it decided in the workflow log. A review's triage
MUST record, in its triage file's `## Next`, whether the change advances or another
review round runs, beginning with the token `Advance` or `Another round`; the
computation MUST route on that token alone, and MUST treat a triage file without it
as a triage in progress. An implementation or pre-closeout round MUST advance only
on a `passed` validation naming its final commit, or a commit from which its final
commit differs only in changes' records — or, after a pre-closeout review, only in
paths under `openspec/` and `docs/`; an `inconclusive` validation MUST be brought to
the owner.

#### Scenario: Reviews await triage

- **WHEN** a change's latest validation and implementation review have no triage
- **THEN** the computation names triage as the next step

#### Scenario: A status was edited by hand

- **WHEN** a change's status disagrees with its workflow log
- **THEN** the orchestrating session follows the files and records that it did

#### Scenario: Triage records another round

- **WHEN** a review's triage recorded another round, and a commit after the commit
  it reviewed changes more than changes' records — after a pre-closeout review,
  more than paths under `openspec/` and `docs/`
- **THEN** the computation names the review of the same kind again, an
  implementation or pre-closeout one once that commit has a passing validation;
  with no such commit, it names the review again on the same commit

#### Scenario: A triage has not finished

- **WHEN** a review's triage file exists without a `## Next` section
- **THEN** the computation names the triage, or the run waiting in it, and no
  review

#### Scenario: A triage file predates `## Next`

- **WHEN** a review's triage file ends with a `## Gate` beginning `Passed`
- **THEN** the computation reads it as `Advance`; any other legacy gate is brought
  to the owner

#### Scenario: A closeout correction awaits validation

- **WHEN** a closeout review's triage records `Advance` and its correction changed
  a path outside `openspec/` and `docs/` since the reviewed commit
- **THEN** the computation names validation of `HEAD` before archive cleanup

#### Scenario: A documentation correction at closeout

- **WHEN** a closeout review's triage records `Advance` and its correction changed
  only paths under `openspec/` and `docs/`
- **THEN** the computation names archive cleanup without a validation

#### Scenario: A round's validation is inconclusive

- **WHEN** an implementation round's triage records `Advance` and the fix commit's
  validation is `inconclusive`
- **THEN** the computation names the owner, not the next round

#### Scenario: An implementation round advances

- **WHEN** an implementation round's triage recorded that the change advances, and
  its fixes are committed
- **THEN** the computation names validation of the fix commit, and once it passes,
  the next round or, after the last, the pre-closeout review, without the owner

#### Scenario: A round is recorded after the fact

- **WHEN** a round's sections were implemented and its records written before the
  round was recorded
- **THEN** the round is recorded naming the last record before it, and the
  computation reads the records above that number as the round's
