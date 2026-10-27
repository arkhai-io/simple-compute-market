# Change Workflow Specification

## Purpose

Define how an OpenSpec change is worked with agent skills: the phases it moves
through, where the owner is consulted and where a triage's `## Next` lets the change
advance without them, its review records and their findings, triage and the
intervention ledger, implementation sections and the sessions that implement them,
validation as an observation of a committed slice, the guarded push of a change's
branch, the orchestrating session and the unattended step runs it advances a change
through, the clone each change may be worked in and the validation namespace each
change's Helm validation runs in, so that several changes are worked at once, and
agent skills that every supported harness loads from one source.

## Requirements

### Requirement: Phases and owner touchpoints

A change MUST move through design, planning, implementation, and closeout, in that
order. The design phase MUST end with a design review, the implementation phase
with a pre-closeout review, and the closeout phase with a closeout review; a phase
ending in a review MUST NOT be treated as finished until that review has been
triaged and its triage file records that the change advances. The repository owner
MUST be consulted for the design discussion's questions, for their notes on each
implementation round before its triage, for the disposition of every finding, and
for whether the dispositions merit another review round, which triage MUST ask
once every finding is disposed and before any fix is made; a triage with no
finding and no point of the owner's notes to dispose of MAY record that the change
advances without the owner. Every other transition MUST proceed without waiting for the owner, unless a
step raises a question only the owner can answer.
Closeout MUST archive the change, merging its specification deltas into the
permanent specifications, before its closeout review, and that review MUST read the
archived change and the permanent documents as archived; the archive is cleaned up,
and the change is `archived`, only once that review's triage records that the
change advances and, when `HEAD` differs from the commit that review read in a path
outside `openspec/` and `docs/`, the latest validation passed for `HEAD` or for an
ancestor it differs from only in records, unless the owner waives that validation,
judging the paths named, and the waiver is recorded in the intervention ledger.
Closeout MUST change documentation only; a closeout part that would need a code
change MUST return
the change to implementation. The steps that follow the archive — the closeout
review and its triage, validation, the round view, the scoped citation check, and
archive cleanup — MUST find an archived change by its name; design, planning, and
implementation MUST refuse a change that is archived.
Planning MUST NOT begin before the design review's triage records that the change
advances. A design decision made after that, such as one planning exposes, MUST
return the change to design; the owner MAY waive another design review for it, and a
waiver MUST be recorded in the intervention ledger. Every review —
design, implementation, pre-closeout, and closeout — MUST stop for the owner's
disposition of each finding before any finding is acted on. An agent MUST NOT treat
its own or another agent's agreement with a finding as a disposition.

#### Scenario: A reviewer and the implementing agent agree

- **WHEN** a reviewer raises a finding and the implementing agent agrees with it
- **THEN** nothing is changed until the owner has recorded a disposition for it

#### Scenario: Planning exposes an unanswered design question

- **WHEN** planning finds a question the reviewed design did not answer
- **THEN** planning stops, the change returns to design, the owner's decision is
  recorded in the design, and planning resumes only after another design review's
  triage records that the change advances, or the owner's waiver of that review is
  recorded

#### Scenario: The closeout review reads the synchronized specifications

- **WHEN** a change's closeout review runs
- **THEN** the change is already archived, its deltas merged into
  `openspec/specs/`, and the review and its triage find the change and its records
  by name under the archive

#### Scenario: An archived change is given to implementation

- **WHEN** the owner asks to implement a change whose directory is under the
  archive
- **THEN** the request is refused, naming the archived directory

#### Scenario: A closeout review finds a code defect

- **WHEN** a closeout review's finding can only be fixed by changing code
- **THEN** the triage makes no code change and stops for the owner, and any
  correction the owner directs in that session is validated before archive cleanup

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
  archive cleanup's own check asks the owner and records the waiver in the ledger

#### Scenario: Closeout finds a comment that needs rewriting

- **WHEN** closeout's comment hygiene part finds a comment the change added that
  describes its history
- **THEN** closeout stops without editing it and the change returns to
  implementation for a fix round

#### Scenario: A design review accepts a blocking finding

- **WHEN** the owner accepts a `blocking` finding in a design review
- **THEN** the change remains in design until the fix lands, and planning does not
  begin before the triage records that the change advances

#### Scenario: Another round is decided before the fixes

- **WHEN** the owner has disposed of every finding of an implementation round
- **THEN** triage recommends whether the accepted fixes merit another review round
  and records the owner's answer before making any fix

### Requirement: Index transitions are written by the step that makes them

Each change of a change's phase or state MUST be written to its row in the
active-change index by the skill that makes it, in the same step: design
discussion starting, triage recording that a phase-closing review's change
advances, planning starting and finishing, the first implementation section
starting, closeout starting, and archive cleanup. An implementation review after a
section MUST NOT change the status. Each step that edits the index MUST check it
afterwards: every row has its
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

#### Scenario: A closeout review's triage advances the change

- **WHEN** a change's closeout review's triage records that the change advances
- **THEN** triage leaves its index row `in closeout` and stops
- **AND** archive cleanup, run next in its own session, releases its dependents and
  sets its index row to `archived`

#### Scenario: A pre-closeout review's triage advances the change

- **WHEN** a change's pre-closeout review's triage records that the change advances
- **THEN** the triage step sets the change's index row to `ready for closeout`

### Requirement: Review records

Each review of a change MUST be written as one Markdown file in that change's
`reviews/` directory, numbered in the order reviews are produced, and that file MUST
be the only record of its findings. The order of the records MUST be establishable —
by number, or, where two records of different kinds share a number, by their file
times — and a record MUST NOT be overwritten. Each finding MUST state its lens, its
basis, its severity, and the evidence it cites. A later review MUST obtain earlier
findings and their dispositions from these files rather than from session memory; a
review of the same kind as an earlier one MAY continue the reviewer session that
wrote it, so the reviewer keeps the context behind its findings, but MUST still read
the triage and dispositions from the records. The `reviews/` directory MUST NOT be
tracked by version control and MUST NOT be cited by permanent documentation;
anything durable in it MUST reach permanent documentation through the ordinary
promotion path at closeout.

#### Scenario: A pre-closeout review asks whether feedback was addressed

- **WHEN** a pre-closeout review runs in a session that produced none of the
  change's earlier reviews
- **THEN** it reads the earlier reviews and their triage from `reviews/` and
  answers for every earlier finding

A review's raw session MAY be kept as a transcript under the change's
`reviews/transcripts/`, untracked like the records. A transcript is not a record of
findings: no review or triage step SHALL read one. A reviewer's output SHALL be
published as a review record only after it is checked to have the review format, so
an error message or a truncated answer never becomes review history.

#### Scenario: A later review runs beside a transcript

- **WHEN** a pre-closeout review runs for a change whose earlier review left a
  transcript
- **THEN** it reads the earlier review's Markdown record and triage, and not the
  transcript

#### Scenario: The reviewer returns an error instead of a review

- **WHEN** the reviewing agent's final output is an error message rather than a
  review
- **THEN** no review record is published, and the output is kept beside the
  transcript

#### Scenario: A review finding changes the design

- **WHEN** a review finding leads to an accepted design decision
- **THEN** the decision is recorded in the change's `design.md` and promoted at
  closeout, and nothing permanent cites the review file

### Requirement: Finding lens, basis, and severity

A finding's lens MUST be one of `direction`, `consistency`, `testing`,
`documentation`, `architecture`, `scope`, or `readiness`. Its basis MUST be one of
`specification` or `guidance`, each citing the requirement or rule it rests on;
`evidence`, citing the files that contradict a claim; or `judgement`, resting on no
written rule. Its severity MUST be `blocking`, which must be resolved before the
change enters its next phase; `should`, which is resolved within the change unless
the owner defers it and the deferral is recorded; or `minor`, which the implementing
agent may decline with a reason.

#### Scenario: A finding cites written guidance

- **WHEN** a finding's basis is `guidance`
- **THEN** it names the document and heading of the rule it applies

### Requirement: Triage of every finding

The implementing agent MUST record, for every finding in a review, its own position
— agree, disagree, or partly — with the evidence for it and a proposed action, and a
position of agreement MUST state its reason as a disagreement does. Every finding
MUST be presented to the owner, none withheld for being minor or uncontested. A
finding MUST be treated as disposed of only when the owner states a disposition for
it.

#### Scenario: A minor finding the agent agrees with

- **WHEN** a review contains a `minor` finding the implementing agent agrees with
- **THEN** it is still presented to the owner with the agent's reason

#### Scenario: The owner discusses one finding and not another

- **WHEN** the owner asks about one finding and says nothing of another
- **THEN** the other has no disposition, and is presented again before another
  round is asked about

### Requirement: Intervention ledger

Each disposition by which the owner corrects course — deciding otherwise than the
implementing agent proposed, or adding context or a condition that changes the work —
MUST be appended as one entry to the change's `interventions.jsonl`, stating the
review, the `tasks.md` section the finding concerns when it concerns one, the
finding's lens, basis, and severity, the implementing agent's position, the owner's
disposition, and a one-line summary. A disposition that accepts the agent's proposal
as it stands MUST NOT be logged; the triage record holds every disposition.
The ledger MUST be tracked by version control, MUST remain in the change directory,
and MUST be archived with the change.

Each time the owner changes or reverses the agent's recommendation during a design
discussion, an entry MUST be appended in the same shape, with `review` set to
`design`, the decision as `finding`, lens `direction`, basis `judgement`, and a null
severity. A recommendation the owner accepts MUST NOT be logged.

#### Scenario: The owner accepts a finding as proposed

- **WHEN** the owner disposes of a finding by accepting the agent's proposed
  outcome without adding to it
- **THEN** the triage record holds the disposition and the ledger gains no entry

#### Scenario: The owner reverses a design recommendation

- **WHEN** the owner chooses a different option than the one the agent recommended
  for a design decision
- **THEN** one ledger entry records the decision, the agent's recommendation, and
  what the owner chose and why

#### Scenario: A reviewed change's archive is cleaned up

- **WHEN** a change whose findings were dispositioned is cleaned up after its
  closeout review's triage advanced it
- **THEN** its intervention ledger is in the archived change directory, and its
  `reviews/` directory stays there, untracked, until an export flow exists

### Requirement: Implementation sections and sessions

Each `tasks.md` section MUST be a coherent slice that can be verified, sized by what
it changes and what proves it, and MUST end at a verification point. A section's
verification MUST name only evidence an implementation session can produce; evidence
only a push produces, such as a CI workflow run a change branch's push does not
trigger, MUST be named as owed by validation — the workflow, the job, and what the
job must show — and MUST NOT gate a task's completion. An implementation session that
finds such evidence in a verification MUST check the task once its own evidence
passes and name that evidence as owed by validation in the section's notes. The plan
MUST NOT prescribe in `tasks.md` how sections are distributed across agent sessions or
review rounds.
A session implementing sections MUST begin with no prior conversation and read the
repository guidance documents, the change, and its sections, unless the owner
directs the work to an implementation session of the change named by its id, one
not waiting on the owner, which then continues with the new sections or
instructions on the model it ran on, reading the change's files again where they
may have changed; how many sessions
implement the work, and how much each round covers before it is reviewed, MUST be
settled in the design discussion as the change's implementation cadence, the
plan's sections ordered by it, and planning's outcome MUST carry the mapping of the
cadence onto the sections, as the sessions and rounds that implement them. Each
round MUST be recorded as it starts, from the latest plan's mapping, as its first
round with a section not yet complete; a change with no mapping for its next
incomplete section MUST ask the owner, once per round. Each section MUST still be checked, handed off, and
committed on its own. Anything a later session needs MUST be recorded in the change's
files before each section is committed. Before a section is committed, its diff MUST
be checked against the repository guidance by an agent whose context contains no
part of the implementing session. When discovered code invalidates the plan, the
session MUST record why, commit what it has as work in progress with no task checked
for it, push it, and return the change.

#### Scenario: A section is finished

- **WHEN** an implementation session completes a section's tasks
- **THEN** it records any handoff in the section's task notes, a fresh-context
  check of the section's diff passes, and the section is committed; the session
  continues into the next section it was given, or stops

#### Scenario: The owner sends the next section to a finished session

- **WHEN** the session that implemented section 2 finished, and the owner directs
  section 3 to it
- **THEN** the orchestrating session runs `make implement CHANGE=<change>
  UNATTENDED=1 SECTIONS=3 SESSION_ID=<its session>`, the wrapper continues that
  session on its model, and the run's log line names the run it continues; a
  session that waits on the owner's answer is refused, its answer going through a
  resume, and so is any session while another implementation run waits

#### Scenario: A plan maps a two-round cadence

- **WHEN** a design settles "round 1: the contract changes; round 2: the handlers
  and the migration", and planning writes sections 1 to 4 in that order
- **THEN** the plan's outcome carries `[[[1, 2]], [[3], [4]]]`, and the second
  round's `round` line is recorded only when that round starts, after the first
  round's triage advanced

#### Scenario: The plan's premise fails mid-section

- **WHEN** an implementation session finds code that invalidates the section's plan
- **THEN** it records the finding in the change, commits its partial work as work in
  progress with no task checked for it, pushes it, and returns the change

#### Scenario: A section owes CI evidence

- **WHEN** a section's change can be shown only by a run of `tests.yml`, which no
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

### Requirement: Validation observes a committed slice

Validation before an implementation review MUST describe one commit and MUST NOT
modify the checkout: it MUST fail if the worktree is not clean when it starts or
after any step, or if `HEAD` is no longer the validated commit after any step, and
MUST then collect no further evidence, though it MAY still stop what it started,
such as port-forwards; it MUST NOT itself regenerate lockfiles or any other
tracked file, `tasks.md` included. It MUST build the internal packages
it tests from the commit under validation, never from wheels another branch left in
the shared wheelhouse. A
condition validation could repair, such as a stale lock, MUST fail validation and
return the slice to implementation. End-to-end evidence MUST come from a pipeline
run whose head commit is the commit under validation. Validation MUST dispatch, on
the change's branch, each workflow a section complete at the validated commit names
as owed by validation, and MUST dispatch only workflows on a fixed list that holds
none that publishes; adding to the list MUST be a tracked change by the owner. It
MUST judge each named job and what that job must show, from a run whose head commit
is the commit under validation; a named job that fails, or an observation that is
absent, MUST be a failure. It MUST compare each failure of every other failing job
of that run — a failing test's ID and its exception type where the job reports
them, otherwise the failing step and its error — with the same job in the latest completed run of the same workflow
on `dev` whose head commit is an ancestor of the commit under validation, and MUST
name that run and its commit: a failure that run shows too MUST be reported as
already failing on `dev` and MUST NOT be a failure, and any other MUST be diagnosed
as any failure is; with no such run, or a job whose failures cannot be compared,
the failure MUST be of unknown cause. Validation MUST also build the
service images and include the Helm render checks, with the chart-to-loader check
able to run, and a Helm end-to-end run of the scenarios the charts serve, named in
an explicit list. A skipped chart-to-loader check MUST fail validation. Every
pipeline scenario not on that list MUST be reported as not run against Helm, never
as passed. Validation MUST
NOT fix what it finds in the commit. Its result MUST be `passed`, `failed` — a
failure caused by the commit or of unknown cause — or `inconclusive`, when no
failure is caused by the commit but a part produced no evidence for an
environmental reason. A failure diagnosed as environmental MUST be put to the
repository owner with its remedy before the record is written, and its part rerun
on the owner's word; every attempt's evidence MUST be kept. The Helm end-to-end run
MUST start from no persistent state left by an earlier deployment. The record MUST
name the end-to-end scenarios that exercise the change, with the basis for each.

#### Scenario: A deploy fails on volumes left by an earlier install

- **WHEN** the Helm part finds a release volume that survived the uninstall, or a
  deploy fails on persistent state another commit wrote
- **THEN** validation tells the owner the evidence and the remedy, reruns the part
  as a new attempt once the owner has acted or named the action, and the failure is
  not a triage finding

#### Scenario: A lockfile is stale

- **WHEN** validation runs on a slice whose committed lockfile is not current
- **THEN** validation fails and reports the stale lock, and the lockfile is
  unchanged

#### Scenario: An earlier pipeline run exists on the branch

- **WHEN** validation dispatches the end-to-end pipeline and an earlier, finished
  run exists on the same branch
- **THEN** validation reports the run whose head commit is the validated commit,
  never the earlier one

#### Scenario: A pipeline scenario the charts do not serve

- **WHEN** the pipeline runs a scenario that is not on the Helm run's list
- **THEN** the validation report lists it as not run against Helm, and its evidence
  comes from the pipeline alone

#### Scenario: Owed CI evidence beside jobs that fail on `dev`

- **WHEN** a complete section owes `tests.yml`'s `release · deployment contracts`
  job passing, and the dispatched run passes that job and fails two others whose
  failing tests also fail, with the same exception types, in `dev`'s latest run of
  `tests.yml` at a commit the branch contains
- **THEN** validation judges the owed job passed, reports the two others as already
  failing on `dev`, naming that run and its commit, and neither is a failure

#### Scenario: A job not owed fails only on the branch

- **WHEN** a job no section owes fails in the dispatched run and passes in `dev`'s
  latest run of the same workflow at a commit the branch contains
- **THEN** validation diagnoses it as any failure, and one caused by the commit or of
  unknown cause fails validation

#### Scenario: A new failure in a job that already fails on `dev`

- **WHEN** a job no section owes fails on `dev` with one test, and the dispatched
  run's same job fails with that test and another
- **THEN** validation reports the first as already failing on `dev` and diagnoses the
  other as any failure

#### Scenario: A test that fails on `dev` fails another way on the branch

- **WHEN** a job no section owes fails on `dev` with a test raising `TimeoutError`,
  and the dispatched run's same job fails that test with an `AssertionError`
- **THEN** validation does not report it as already failing on `dev`, and diagnoses
  it as any failure

#### Scenario: No `dev` run of the branch's code

- **WHEN** a job no section owes fails, and no completed run of the workflow on `dev`
  has a head commit the branch contains
- **THEN** the failure is of unknown cause, so validation fails and it is triaged

#### Scenario: A plan owes a workflow that publishes

- **WHEN** a section names `publish-pypi.yml` as owed by validation
- **THEN** the dispatch is refused, naming the workflows validation may dispatch, and
  nothing is published

#### Scenario: A dispatched run is cancelled

- **WHEN** the run validation dispatched is cancelled by a newer dispatch on the same
  branch
- **THEN** the part produced no evidence for an environmental reason, which goes to
  the owner with its remedy, and the part is rerun on the owner's word

### Requirement: Guarded push of a change branch

An agent MAY push a change's own branch without separate approval, only after a
check confirms that `HEAD` is attached, the worktree is clean, the branch is neither
`main` nor `dev`, and the branch's upstream has the same name. The push MUST send
exactly `HEAD` and MUST NOT be forced. A branch with no upstream MAY be pushed to
the same name, setting that upstream. The check MUST report a refused state and
MUST NOT repair it.

#### Scenario: The worktree is dirty

- **WHEN** validation is about to push and the worktree has uncommitted changes
- **THEN** the push check fails, nothing is pushed, and nothing is committed or
  discarded to make it pass

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
saved as the round's owner record. When a round's triage records another round and
commits a fix, the repeat pass MUST be read in the same way, as one set of changes
from the commit that triage's review read to the fix's commit, and its triage MUST
NOT start until the owner has answered on that pass; an answer saved before that
triage finished answers only for the earlier pass. For a change worked in the owner's workspace, while
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

#### Scenario: A repeat round's fix is read

- **WHEN** a round's triage recorded another round and committed a fix, and the
  owner's only record on the round was saved before that triage finished, even
  one numbered after the review it triaged
- **THEN** the owner is shown the fix as uncommitted changes over the commit that
  review read, and the repeat pass's triage waits for the owner's answer on it

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

### Requirement: Harness-neutral agent skills

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

### Requirement: An orchestrating session advances one change

The repository owner MAY advance one change through its steps from one orchestrating
session. The orchestrating session MUST hold no state beyond the change's files and
its workflow log, so that a new session resumes the change from them alone. It MUST
run the next step the next-step computation names, and MUST advance without the
owner wherever the computation names a step. It MUST bring every question a step
raises to the owner, showing each step's message as written, and MUST NOT answer a
design question or decide or state a position on a finding, and MUST show the
earlier outcomes a run's line keeps beside its last. It MUST continue a named
implementation session only on the owner's word. It MAY create the
change's clone and branch, and MAY commit changes to the workflow itself — skills,
the step table — what else the owner explicitly asks for, and merges of `dev` the
owner asks for, in the change's clone, on its branch, pushing each through the
guarded push. It MUST NOT commit while a step runs, MUST NOT merge while a round
view of the change is open or between a round's sections being committed and that
round's triage, and MUST NOT write the change's feature work of its own accord; it
MUST NOT commit a closed step's leftover work unless the owner asks, bringing such
work to the owner instead. It MUST resolve a merge's conflicts in the change index,
change documents, the step table, and skills itself, and MUST bring a conflict in
code to the owner; one the owner does not rule on MUST go to an implementation run,
named the conflicted files. While a merge is in progress the next-step computation
MUST name the owner. It MUST NOT read
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

#### Scenario: A merge of `dev` conflicts in a skill and in code

- **WHEN** the owner asks the orchestrating session to merge `dev` between steps, and
  the merge conflicts in a skill and in a script
- **THEN** it resolves the skill's conflict itself and brings the script's to the
  owner; when the owner does not rule on it, it starts an implementation run naming
  the conflicted script, which resolves it, concludes the merge, and pushes

#### Scenario: A merge is asked for during a round's window

- **WHEN** the owner asks for a merge of `dev` after a round's sections are committed
  and before that round's triage
- **THEN** the orchestrating session makes the merge only once the round is triaged,
  so it never moves the commit the round's validation and review describe

#### Scenario: A closed step leaves tracked work uncommitted

- **WHEN** a step's run finished and left a tracked edit uncommitted
- **THEN** the orchestrating session brings it to the owner as a defect of that step,
  and commits it only if the owner asks

### Requirement: Unattended step runs end with a structured outcome

A step MAY be run unattended, through one wrapper, as its leaf skill in a
non-interactive session. Every unattended run MUST end with an outcome that conforms
to the repository's outcome schema and is one of: finished, with the next step;
a question for the owner; a proposed return to an earlier phase; blocked on a
prerequisite; or stopped, with its reason and any tools it was denied. The wrapper
MUST append each outcome, with the run's session and commit, to the change's
workflow log, and MUST record a stopped outcome itself for a run that ends without
one. A run whose session took further turns after an outcome — a background
command finishing, a wake-up — MUST be logged with its last outcome, and MUST keep
each earlier one on its line. Where the workflow log and the change's files
disagree, the files MUST prevail.
Every outcome's denials MUST be taken from the run's own record of denied tools,
over every turn of the run, each with the harness's reason for it.
A review run's outcome MUST name the review record that run published; a review run
that published none MUST be recorded as stopped, and an earlier record MUST NOT count
as its result.
A question MUST be answered by resuming the same session with the owner's answer.
A proposed return MUST NOT change the change's status until the owner confirms it;
the confirmation MUST be recorded in the workflow log as a decision naming the run
it resolves and the step it directs, and the step so directed sets the status.
A decision that resolves a run MUST name it, and MUST NOT resolve any other; a
decision that reads a run's denials MUST name that run; a decision that directs a
review MUST name its kind.
An interactive run of a step MUST behave as it does without the wrapper.

#### Scenario: Validation needs an environmental remedy

- **WHEN** an unattended validation finds an environmental failure
- **THEN** it ends with a question naming the remedy, and once the owner answers, the
  same session resumes with the answer and takes only the action named

#### Scenario: A run crashes

- **WHEN** an unattended run exits without producing an outcome
- **THEN** the workflow log records a stopped outcome with its exit status

#### Scenario: A wake-up follows a run's report

- **WHEN** an implementation run reports its section finished, and a wake-up it
  scheduled starts another turn that ends with "nothing left to wait for"
- **THEN** the run's line carries that last outcome with the section's report kept
  under `earlier`, and the orchestrating session shows the owner both

#### Scenario: Implementation finds a design question

- **WHEN** an unattended implementation run finds that a task needs a decision the
  design does not make
- **THEN** it ends with a proposed return to design, and the change's status is
  unchanged until the owner confirms the return

#### Scenario: The owner confirms a return

- **WHEN** an implementation run at seq 50 ended with a proposed return to design
  and the owner confirms it, recorded as
  `{"seq": 51, "step": "orchestrator", "outcome": "orchestrator", "by": "owner", "resolves": 50, "next": "design", "decision": "return to design confirmed", "reason": "task 0.4 needs a provider decision the design does not make"}`
- **THEN** the next-step computation names design until it has run, and the
  design step sets the status

#### Scenario: A confirmation names no run

- **WHEN** a confirmation line with `next: design` and no `resolves` is attempted
- **THEN** the log's writer refuses it, since the returned run at seq 50 would
  otherwise keep waiting and the computation would name the owner, never design

#### Scenario: The owner directs a repeat review

- **WHEN** the owner asks the orchestrating session for a pre-closeout review
  again outside a triage, recorded as
  `{"seq": 61, "step": "orchestrator", "outcome": "orchestrator", "by": "owner", "next": "review", "kind": "pre-closeout", "decision": "review again", "reason": "the reviewer should see the triage"}`,
  naming no run, since no run waits on it
- **THEN** the next-step computation names the pre-closeout review until it has run

#### Scenario: A directed review names no kind

- **WHEN** a decision line with `next: review` and no `kind` is attempted
- **THEN** the log's writer refuses it, since the computation could name no review
  from it

#### Scenario: A decision about one run leaves another waiting

- **WHEN** a validation run has asked a question and a review run beside it stopped,
  and a decision resolves the review's stop
- **THEN** the validation's question still waits, and is answered by resuming its
  session

### Requirement: The next step is computed from the files

The next step of a change MUST be computed by a script from the change's index row,
its reviews and their triage, its tasks, its workflow log, and the state of any open
round view, and the same
computation MUST be available to the owner by hand. When the computation fails or
cannot classify the change's state, the orchestrating session MUST determine what
happened and either resolve it, when it concerns only routing or recovery, or bring
it to the owner, when it would decide a finding, settle a design question, or
change a status; and MUST record what it decided in the workflow log. A review's triage
MUST record, in its triage file's `## Next`, whether the change advances, another
review round runs, or the triage returns the change to an earlier phase, beginning
with the token `Advance`, `Another round`, or `Returned`; the computation MUST route
on that token alone, and MUST treat a triage file without it as a triage in
progress. Once the owner confirms a return, the returned review MUST NOT govern
what follows, so the work the return leads to is implemented, validated, and
reviewed afresh, as a round of its own even where it reworks a section the
returned round implemented; a return the owner declined, or one recorded at
closeout, MUST be brought to the owner. An implementation or pre-closeout round MUST advance only
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

#### Scenario: A triage returns the change

- **WHEN** an implementation round's triage recorded `Returned to planning` under
  `## Next`, the owner confirmed the return, and the amended plan finished
- **THEN** the computation names the amended plan's next round, not that triage,
  and the round's own validation covers the work-in-progress commit the return left

#### Scenario: A pre-closeout triage returns the change

- **WHEN** a pre-closeout review's triage recorded `Returned to planning`, the
  owner confirmed the return, and the amended plan added nothing to implement
- **THEN** the computation names a validation of `HEAD`, and then a new
  pre-closeout review

#### Scenario: The owner declines a return

- **WHEN** a triage recorded `Returned` and the owner's decision resolved its run
  without directing design or planning
- **THEN** the computation names the owner, who decides what the triage records

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

### Requirement: Discussion steps stay conversations with the owner

Design MUST NOT run without the owner. Triage MUST bring every finding and every
point of the owner's notes to the owner, and MAY finish without the owner only when
there is none to dispose of. When orchestrated, each MUST run as its own resumable
session, presenting one decision or finding per turn, and each
of its messages MUST be shown to the owner in the orchestrating session, with the
owner's reply resuming that session. Planning MUST NOT ask the owner to accept the
plan; a plan that needs a decision the design does not make MUST return the change
to design.

#### Scenario: A triage finding is presented

- **WHEN** an orchestrated triage presents a finding
- **THEN** the owner reads it in the orchestrating session, and the owner's
  disposition resumes the triage session

### Requirement: Unattended runs are held to their step's permissions

An unattended run MUST be limited to the tools its step's permission table allows,
and MUST NOT be granted a push other than the guarded push of the change's branch.
Every step that writes tracked work on the change — design, planning,
implementation, triage, closeout, archive cleanup — MUST commit it and push it
through that guarded push; validation and review MUST commit nothing. A run that
returns the change to an earlier phase MUST commit what it has as work in progress,
check no task for it, and push it; a run that stops MUST leave its partial work
uncommitted, and one stopped by a refusing repository guard or a moved `HEAD` MUST
commit nothing. A step MUST NOT reset, check out, switch, rebase, stash, or clean. Every denial a
run records MUST be recorded on the run's outcome, from the run's own record and
with the harness's reason when it gives one. A run that cannot go on without a denied tool MUST end
with a stopped outcome naming the denial, rather than asking a question or working
around it; a run that goes on MUST do so only by calls its step's rules allow. A
call a deny rule refused MUST NOT be done by another tool; a call denied for want
of an allow rule MAY be done by a tool the step's rules allow for the same work,
and the run MUST name that substitute in its message. The orchestrating session
MUST read each recorded denial from the run's record, never from the step's
message; classify it by the harness's reason as a gap in the table or a
forbidden action, matching a command refused by its parts, or one with no
reason, against the step's deny rules; check the run's later calls, after a deny-rule
denial, for a workaround; propose, for a gap, the narrowest rule that matches the
call and say whether it is a one-run grant or a tracked change; and record its
reading in the workflow log as a
decision reading that run, before the next step runs. A run whose outcome still
waits — a question, a proposed return — MUST be answered or decided after its
denials are read, and the reading MUST NOT settle that outcome. A denial by a
deny rule MUST NOT be granted for one run. A
change to a step's permissions MUST be made by the owner or, on the owner's word, by
the orchestrating session, as a tracked change, or granted by the owner for one
run, fresh or resumed. A grant MUST be passed on that run's command line — for a
fresh run through its step's make target — recorded as `granted` on the run's log
line, and never added to the table, so the step's next run is held to its table
again. Interactive runs MUST NOT be restricted by the table.

#### Scenario: Validation attempts to relock

- **WHEN** an unattended validation run attempts `make lock`
- **THEN** the call is denied, and the run ends stopped, its outcome naming the
  denial

#### Scenario: A step is denied a command no rule names

- **WHEN** an unattended run is denied a command because no allow rule names it
- **THEN** the orchestrating session proposes the narrowest allow rule matching the
  call, and the owner grants it for the resumed run or has it committed to the table

#### Scenario: The owner grants rules before a fresh run

- **WHEN** the owner grants two rules for a step's next run, which has not started
- **THEN** the orchestrating session starts the run through its make target with
  both rules in `ALLOW`, separated by `;`, the run's log line records both as
  `granted`, and the step's run after it is held to its table alone

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

#### Scenario: A step stops at its session's limit

- **WHEN** an unattended implementation run stops partway through a section because
  its session reached its limit
- **THEN** its edits stay uncommitted, and the resumed session finishes the section
  and commits it

### Requirement: A design blocked on a prerequisite halts

When a design cannot proceed without another change, the design step MUST, with the
owner, define the prerequisite's requirements and initial proposal and end with a
blocked outcome. The prerequisite's proposal and index row MUST be written on a
branch from the development branch, never on the blocked change's branch, and MUST
reach the development branch before the prerequisite's own workflow starts; the
blocked change's branch MUST receive them only by merging the development branch.
The blocked change MUST then remain `in design`, with the prerequisite in its
dependencies gating design. Once the prerequisite is archived and its result is
merged into the blocked change's branch, the blocked change's dependency MUST be
released, on the owner's word, before design resumes.

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

### Requirement: Unattended steps run on their step's ordered models

Each step's row in the step table MUST name the models its unattended runs use, in
priority order, each with its harness and effort. The wrapper MUST run the first
available model, MUST fall to the next only when one is unavailable — a usage
limit, a missing sign-in, or a missing harness — and MUST record on the run's log
line the model and effort that ran. The table MUST NOT name a Fable or Astra model,
and a row MUST NOT list two models of one vendor. A model of another harness MUST
appear only on a row whose limits that harness can enforce. A run whose models are
all unavailable MUST end stopped, naming the reason; a network error MUST be retried
and MUST NOT cause a fallback. A waiting run MUST be resumed only on the model it ran
on. A review run on a model other than its row's first MUST name its reviewer's
harness and model in its record, and a review MUST continue a previous reviewer's
session only on the same harness. The owner MAY name, for one review run by hand,
any model, outside the table's policy, or an effort for its models; a model named
MUST then be the run's only one, with no fallback, and the record and its log line
MUST mark the run as an override.
The orchestrating session MUST NOT name one.

#### Scenario: The owner reviews on a model the table forbids

- **WHEN** the owner runs a review by hand naming a Fable model
- **THEN** the review runs on that model alone, and its record and log line mark it
  as the owner's override

#### Scenario: Codex is unavailable for a review

- **WHEN** an implementation review is started and Codex is not signed in
- **THEN** the review runs on the row's next model, Claude, its record and log line
  name the reviewer's harness and model, and triage follows as usual

#### Scenario: A row names a forbidden model

- **WHEN** the step table names a Fable model, or two Claude models on one row
- **THEN** the wrapper refuses to load the table, naming the row

#### Scenario: A step's only model is at its usage limit

- **WHEN** an unattended triage is started and Claude reports a usage limit
- **THEN** the run ends stopped with the reason and the time the limit resets, and
  nothing runs the step on another harness

### Requirement: Unattended runs record their cost

Each unattended run's log line MUST record its cost: for a Claude run, the dollars,
turns, duration, and input, output, cache-read, and cache-write tokens of that run
alone, over all its turns; for a Codex review, the tokens it reports. Where a run's
own dollars cannot be told from its session's earlier turns — a crashed run before
it, or turns the wrapper did not run — the line MUST mark its dollars as partial. A resumed
run MUST also record the time since its session's last turn of any kind and whether
its first turn read the prompt cache. The cost of a change's runs MUST be reportable by
step and by round, with the cache misses and their gaps listed.

#### Scenario: A discussion turn is resumed after a long gap

- **WHEN** a triage session is resumed two hours after its previous run, and its
  first turn rewrites its context to the prompt cache
- **THEN** the run's line records the gap, a cache miss, and the run's own cost,
  not the session's running total, and the cost report lists the miss with its gap

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
refusing and naming any whose contents differ; once archive cleanup's own outcome is
logged, the orchestrating session MUST repeat the copy, so the workspace holds that
outcome too. A step that reads another change's
or an earlier change's records MUST look for them in its own checkout and then in
the owner's workspace. A clone MUST be removed only on the owner's command; the
removal MUST first repeat the copy, and MUST proceed only once the clone's records,
and the named evidence it holds, are in the workspace with identical contents, its
branch is merged, and it holds no commit and no change its `origin` lacks; named
evidence the clone does not hold MUST be named in the removal's report.

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
- **THEN** it finds them in the owner's workspace, at the archived change's path,
  even where the workspace's branch also carries the change's active directory
  without them, and a report of the change's cost or log reads them there

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
Archive cleanup MUST remove the change's namespace and images and, when the
change's latest validation measured memory, MUST record it, with when it was
measured; when that validation measured none, it MUST keep the figure already
recorded and say that it recorded none. Where two branches' recorded figures
conflict at a merge, the one measured later MUST be kept.

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

#### Scenario: Archive cleanup after a validation that measured nothing

- **WHEN** archive cleanup runs and the change's latest validation recorded no
  memory
- **THEN** it leaves the recorded figure as it is, or absent, and says in its report
  and the pull-request draft that it recorded none

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
  validation measured, if it measured any, is recorded for the preflight

## Evidence

- Contributor guide to each step, the review directory, and the ledger:
  `docs/agents/change-workflow.md`; rationale: `architecture.md`.
- Leaf skills: `.agents/skills/change-design/`, `change-plan/`, `change-review/`,
  `change-triage/`, `change-implement/`, `change-validate/`, `change-closeout/`, and
  `change-archive-cleanup/`, and the orchestrating skill,
  `.agents/skills/change-orchestrate/`, linked for each harness and held by
  `make check-agent-skills` (`scripts/check_agent_skills.py`).
- Unattended runs, the workflow log, and reviews: `scripts/run_change_step.py`, the
  entry point of the `scripts/change_workflow/` package, reached through each step's
  `make` target with `UNATTENDED=1` and through `make review`; the outcome schema:
  `.agents/change-outcome.schema.json`; each step's permissions and models:
  `.claude/change-steps.toml`; finding a change by name, active or archived:
  `scripts/find_change.py`.
- The next-step computation: `scripts/change_next_step.py` (`make change-next`);
  the orchestrating session: `make orchestrate`; following a run:
  `make change-watch`; the cost report: `make change-cost`
  (`scripts/change_cost.py`); completion of change names on the workflow targets:
  `scripts/completions/make-change.bash`.
- A change's closing checks: `make check-change` (`scripts/check_change.py`); its
  task list's sections: `make check-tasks` (`scripts/check_tasks.py`).
- Validation: `make validate-local`, `make validate-helm`, and `make validate-ci`
  (`scripts/validate_slice.py`); run selection for the validated commit:
  `scripts/fetch-e2e-logs.py`; the workflows validation may dispatch and the
  comparison of a CI run's failures with `dev`'s: `make run-ci`
  (`scripts/ci_evidence.py`); the push guard: `make check-push-ready` and
  `make push-branch` (`scripts/check_push_ready.py`).
- A change's validation namespace and image tags: `scripts/change_namespace.py`,
  with `CHANGE=` on every `helm/Makefile` target and `IMAGE_SUFFIX` on the build
  targets; manual access: `make -C helm forward` and `make -C helm resume`;
  teardown: `make -C helm teardown`; the memory one release needs:
  `helm/validation-capacity.toml`, written by `make record-capacity`; two clones'
  Helm parts at once: `make validate-parallel` (`scripts/validate_parallel.py`).
- A change's clone: `make change-clone` and `make change-clone-remove`
  (`scripts/change_clone.py`); its history in the owner's workspace: `make
  change-history` (`scripts/change_history.py`) and `python3
  scripts/find_change.py --records`; a run in progress in a checkout:
  `scripts/change_workflow/running.py`.
- Reading a round: `make round-view` and `make round-done` (`scripts/round_view.py`).
- Index edits checked: `make check-change-index` (`scripts/check_change_index.py`).
- The post-compaction hook: `.claude/settings.json` and
  `scripts/post_compaction_context.py`.
- Tests for each script under `scripts/tests/`.

The skills are instructions to an agent; that a session follows them is shown by the
sessions that ran them, not by a test.
