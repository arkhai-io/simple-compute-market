## ADDED Requirements

### Requirement: Each change is worked in its own clone

A change MAY be worked in a clone of the owner's workspace of its own, which holds
its branch, its records, its environments, its evidence, and its step sessions; a
change MAY instead be worked in the owner's workspace itself. When a change's branch
is checked out neither in a clone of its own nor in the checkout the next-step
computation runs in, the computation MUST name the creation of its clone, and the
orchestrating session MUST create it and, when the branch does not exist, the
branch. The clone's `origin` MUST be the workspace's `origin`, and one of its
remotes MUST name the workspace. The clone's bootstrap MAY run while design
proceeds; implementation and validation MUST NOT start before it has finished.
Archive cleanup MUST copy the change's records, and the validation evidence they
name, into the owner's workspace at the same paths, never overwriting a file there.
A step that reads another change's or an earlier change's records MUST look for
them in its own checkout and then in the owner's workspace. A clone MUST be removed
only on the owner's command, and only once its records and named evidence are in
the workspace, its branch is merged, and it holds no commit and no change its
`origin` lacks.

#### Scenario: Feature work begins on a change

- **WHEN** the owner starts the orchestrating session for a change whose branch no
  clone holds
- **THEN** the computation names the clone, the orchestrating session creates it
  with the change's branch, and design runs while the clone's bootstrap continues
  in the background
- **AND** the computation names no implementation or validation until the
  bootstrap has finished

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
need with what the node can allocate and MUST treat a deployment that would not fit
as an environmental failure; when usage cannot be measured, it MUST warn and go on.
Archive cleanup MUST remove the change's namespace and images and MUST record the
memory the change's latest validation measured.

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
validated again. The owner MUST be able to read a round as one set of changes from the
commit the previous round ended on to the round's commit, without any commit being
changed to show it. For a change worked in its own clone, the reading MUST take place
in the owner's workspace, on that workspace's copy of the change's branch, and MUST
NOT move the branch in the clone; validation and the implementation review MUST start
when the round's sections are committed, beside the reading; and triage MUST NOT start
until the owner has answered on the round, with notes or with none, and the answer is
saved as the round's owner record. For a change worked in the owner's workspace, while
its branch is moved to show the round, review, validation, triage, and implementation
MUST NOT start. Ending the reading MUST return the branch to the round's commit. A view
MUST NOT move a checkout in which an unattended run is in progress. A commit the owner
makes on the change's branch while reading MUST reach the clone only through a
fast-forward triage makes. A pre-closeout review MUST NOT run, and its triage MUST NOT
advance the change, unless the latest validation's result is `passed` and it names
`HEAD`, or a commit from which `HEAD` descends and differs only in changes' intervention
ledgers and review records, except where the owner overrides it.

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

#### Scenario: The owner reads a round committed section by section

- **WHEN** the owner reads a round of a change worked in its own clone
- **THEN** the round is shown in the owner's workspace as uncommitted changes over the
  commit the previous round ended on, on the change's branch by name, and when the
  reading ends that branch is back at the round's commit with the commits unchanged
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

- **WHEN** the owner commits a change on the branch in their workspace and names it in
  their answer
- **THEN** triage presents it like any point and, once disposed of, pulls it into the
  clone only as a fast-forward, refusing a branch that has diverged

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
steps, as a numbered record marked as its own, for the next triage. It MUST advance
only the change it was started for.

#### Scenario: The orchestrating session restarts

- **WHEN** an orchestrating session is started for a change partway through its
  workflow
- **THEN** it determines the next step from the change's files and workflow log, and
  continues from there

#### Scenario: The orchestrating session restarts during a round view

- **WHEN** an orchestrating session is started while a round view of the change is
  open
- **THEN** it waits for the owner's answer on the round, saves it as the change's
  next owner record, and closes that view before computing any other step

#### Scenario: A review's triage has nothing for the owner

- **WHEN** a review and the validation beside it raised no finding, and the
  owner's notes raise no point to dispose of
- **THEN** the triage records that the change advances, and the orchestrating
  session runs the next step without asking the owner

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
