## ADDED Requirements

### Requirement: The workflow graph is declared in code

The workflow's steps and the transitions between them MUST be declared as one table
in code, which the next-step computation interprets: each node a step, qualified by
its review kind where it has one — a review by its kind, a triage by the kind of
review it triages; the exits it may take; the records a join waits for; the guards
on each exit, each naming the step that satisfies it, or the owner where no step
can; and its entry guards, the conditions without which its step cannot carry out
its work, each unwaivable or waivable. Exit guards MUST apply to the exits steps
take, and MUST NOT be checked against the owner's directions. Entry guards MUST be
checked on every entry to their node: an unwaivable one MUST refuse every entry
while unmet, and a waivable one MUST take the owner's direction as its override.
The change's archive MUST be an unwaivable entry guard of the closeout review, its
triage, and archive cleanup, and its absence one of design, planning, and
implementation. A triage node's entry guard MUST be that a review of its kind
awaits triage. Validation's entry guard MUST be unwaivable: that it carries a
target, a node of the table; the target's own entry guards MUST be checked on
validation's exit, not on its entry. Archive
cleanup's exit MUST be the terminal node `done`, which has no
exits and no step, and which no direction reaches. A change to the table MUST be
made as an OpenSpec change.
The table MUST be renderable as a diagram, and the diagram the `change-workflow`
architecture shows MUST be checked against that rendering.

#### Scenario: The graph is drawn

- **WHEN** the owner runs `make change-graph`
- **THEN** it prints the table as a diagram of every node, exit, join, and guard
  with its remedy

#### Scenario: The documented diagram drifts

- **WHEN** a change adds an exit to a node and does not update the diagram in the
  `change-workflow` architecture
- **THEN** the check comparing that diagram with the rendering fails, naming the
  difference

#### Scenario: The round's triage waits for its join

- **WHEN** an implementation round's validation has finished and its review and the
  owner's reading have not
- **THEN** the computation names the steps the join still waits for, and no triage

#### Scenario: A round's validation starts before its review is published

- **WHEN** an implementation round's validation and review start from the same
  commit, and no implementation review awaits triage yet
- **THEN** the computation names validation with
  `{"step": "triage", "kind": "implementation"}` as its target, and validation's
  entry guard is met

#### Scenario: Archive cleanup finishes

- **WHEN** archive cleanup ends finished, naming `{"step": "done"}`
- **THEN** the computation names `done`, with the reason `archived`, and no step runs

#### Scenario: A step's exit meets an unmet entry guard

- **WHEN** closeout ends finished naming `{"step": "review", "kind": "closeout"}`,
  and the change's directory is not under the archive
- **THEN** the computation names the owner, with the exit and the entry guard, and
  no closeout review

### Requirement: Interactive step runs record their outcome

An interactive run of a step MUST behave as it does without the wrapper, unrestricted
by the step table, except that it MUST end by recording its outcome through the
workflow tooling's record command. The command MUST check the outcome against the
outcome schema, MUST record it with the session's id — read from the harness's
environment, or given explicitly — the commit at `HEAD`, and that the run was
interactive, and MUST refuse to record without a session id, and inside an
unattended run, whose outcome the wrapper records. Every step's permissions MUST
allow it to print the session's id.

#### Scenario: An interactive triage finishes

- **WHEN** the owner triages a review in an interactive session, and the triage
  ends by recording its outcome naming the review it triaged and its exit
- **THEN** the workflow log holds that outcome with the session's id, `HEAD`, and
  `interactive`, and the computation routes on it

#### Scenario: An interactive session ends without recording

- **WHEN** the owner closes an interactive session of any step before it recorded its
  outcome, and the last exit or direction names that step
- **THEN** the computation names the step as in progress, its reason saying that if
  no session of it is open, an interactive session ended without recording, to be
  resumed or recorded by hand

#### Scenario: An interactive plan sets its status and records nothing

- **WHEN** an interactive planning session wrote the task list and set the status
  `ready for implementation`, and was closed before it recorded its outcome
- **THEN** the computation names planning as in progress, and no round, its result
  carrying a `disagreement` naming the missing plan outcome and the record command

#### Scenario: The harness exports no session id

- **WHEN** the record command runs where the harness's session id variable is unset,
  and no session is given
- **THEN** it refuses, naming the variable, and records nothing

#### Scenario: An unattended run records its own outcome

- **WHEN** a step run by the wrapper runs the record command
- **THEN** the command refuses, and the run's outcome is the one the wrapper records

### Requirement: The owner directs a change's next step

The owner MAY direct a change to any node of the workflow graph, by a decision in the
workflow log naming its target as an outcome names an exit, with a reason, which
says what any skipped check was; the decision MAY resolve the run waiting on it.
Only the owner MAY direct a step: the orchestrating session MUST NOT direct one of
its own accord, nor record a step's exit on its behalf. The computation MUST name
the directed step until a later run of it is logged, checking no exit guard, and the
step sets its own status as it starts. A direction MUST be refused, naming the
guard, while an unwaivable entry guard of any node it names is not met — its
target, and the target nested in a direction to validation: an archived change MUST NOT be
directed to design, planning, or implementation, nor a change not archived to the
closeout review, its triage, or archive cleanup. A waivable entry guard, and the
directed step's own entry check for it, MUST accept the direction as its override.
A direction to validation MUST name, nested in its target, the target the
validation is for, and MUST be refused without one by validation's entry guard; a
directed validation that passed MUST lead to its target, whose entry guards are
checked, and one that failed or was inconclusive MUST be brought to the owner.

#### Scenario: The owner directs past a guard

- **WHEN** the latest validation of `HEAD` failed, and the owner directs the change
  to closeout
- **THEN** the computation names closeout, not the owner or a validation

#### Scenario: Closeout finds a design defect before the archive

- **WHEN** closeout, before archiving the change, finds that a design decision
  contradicts a permanent requirement, and the owner directs the change back to
  design
- **THEN** the computation names design, and the design step sets the status
  `in design` as it starts

#### Scenario: The owner waives archive cleanup's validation by a direction

- **WHEN** the computation names a validation before archive cleanup, and the owner
  directs archive cleanup, the reason saying the validation is waived
- **THEN** the computation names archive cleanup, and archive cleanup, finding the
  direction in the log, records the waiver in the intervention ledger

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

#### Scenario: A triage is directed with nothing to triage

- **WHEN** a direction to `{"step": "triage", "kind": "design"}` is attempted and
  every design review has its triage
- **THEN** the log's writer refuses it, naming the entry guard

## MODIFIED Requirements

### Requirement: Phases and owner touchpoints

A change MUST move through design, planning, implementation, and closeout, in that
order, except where the owner directs a step, as the requirement on the owner's
directions allows; no direction crosses the archive. The design phase MUST end with a design review, the implementation phase
with a pre-closeout review, and the closeout phase with a closeout review; a phase
ending in a review MUST NOT be treated as finished until that review has been
triaged and its triage's outcome names, as its exit, a step of the next phase. The
repository owner MUST be consulted for the design discussion's questions, for their
notes on each implementation round before its triage, for the disposition of every
finding, and for whether the dispositions merit another review round, which triage
MUST ask once every finding is disposed and before any fix is made; a triage with no
finding and no point of the owner's notes to dispose of MAY record that the change
advances without the owner. Every other transition MUST proceed without waiting for
the owner, unless a step raises a question only the owner can answer.
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

### Requirement: Unattended step runs end with a structured outcome

A step MAY be run unattended, through one wrapper, as its leaf skill in a
non-interactive session. Every unattended run MUST end with an outcome that conforms
to the repository's outcome schema and is one of: finished, naming the exit it
takes; a question for the owner; a proposed return, naming the step it returns to;
blocked on a prerequisite; or stopped, with its reason and any tools it was denied.
An exit or a return MUST be named as a target: an object naming a node of the
workflow graph by its step, with its review kind for a review, the kind of review it
triages for a triage, and the sections for an implementation out of the plan's
order; a review or a triage named without its kind, or with an empty or unknown one,
MUST be refused. A validation MUST name as its exit the target the computation gave
it, and archive cleanup the terminal node `done`. A triage's finished or returned outcome
MUST name the review records it triaged, as a non-empty list of distinct record
names in the form `NN-<kind>`, each a numbered record in the change's `reviews/`
with its triage file beside it, at least one of them a review; the wrapper MUST NOT
record a triage's outcome that names none, or breaks that rule, as anything but
stopped, naming the reference, and the record command MUST refuse it. The wrapper
MUST append each outcome, with the run's session and commit, to the change's
workflow log, and MUST record a stopped outcome itself for a run that ends without
one. A run whose session took further turns after an outcome — a background
command finishing, a wake-up — MUST be logged with its last outcome, and MUST keep
each earlier one on its line. The files hold the change's state and MUST prevail
over the log on it; the log holds the exits steps chose and the owner's decisions.
Every outcome's denials MUST be taken from the run's own record of denied tools,
over every turn of the run, each with the harness's reason for it.
A review run's outcome MUST name the review record that run published; a review run
that published none MUST be recorded as stopped, and an earlier record MUST NOT count
as its result.
A question MUST be answered by resuming the same session with the owner's answer.
A proposed return MUST NOT change the change's status until the owner confirms it;
the confirmation MUST be recorded in the workflow log as the owner's decision naming
the run it resolves and the step it directs, and the step so directed sets the
status.
A decision that resolves a run MUST name it, and MUST NOT resolve any other; a
decision that reads a run's denials MUST name that run; a decision that directs a
step MUST name its target as an outcome names an exit, and MUST be the owner's.

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
- **THEN** it ends with a proposed return naming design, and the change's status is
  unchanged until the owner confirms the return

#### Scenario: A triage names its exit

- **WHEN** an unattended triage of review 157 ends with
  `{"outcome": "finished", "message": "…", "triaged": ["157-closeout"], "next": {"step": "review", "kind": "closeout"}}`
- **THEN** the wrapper records it, and the computation routes on its exit

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

#### Scenario: The owner confirms a return

- **WHEN** an implementation run at seq 50 ended with a proposed return to design
  and the owner confirms it, recorded as
  `{"seq": 51, "step": "orchestrator", "outcome": "orchestrator", "by": "owner", "resolves": 50, "next": {"step": "design"}, "decision": "return to design confirmed", "reason": "task 0.4 needs a provider decision the design does not make"}`
- **THEN** the next-step computation names design until it has run, and the
  design step sets the status

#### Scenario: A confirmation names no run

- **WHEN** the returned run at seq 50 waits, and the owner's direction to design is
  recorded naming no run
- **THEN** the run at seq 50 still waits, and the computation names the owner for it
  until a decision resolves it

#### Scenario: The owner directs a repeat review

- **WHEN** the owner asks the orchestrating session for a pre-closeout review
  again outside a triage, recorded as
  `{"seq": 61, "step": "orchestrator", "outcome": "orchestrator", "by": "owner", "next": {"step": "review", "kind": "pre-closeout"}, "decision": "review again", "reason": "the reviewer should see the triage"}`,
  naming no run, since no run waits on it
- **THEN** the next-step computation names the pre-closeout review until it has run

#### Scenario: A directed review names no kind

- **WHEN** a decision line directing `{"step": "review"}` with no kind is attempted
- **THEN** the log's writer refuses it, since a review is a node only with its kind

#### Scenario: A directed triage names no kind

- **WHEN** a decision line directing `{"step": "triage"}` with no kind is attempted
- **THEN** the log's writer refuses it, since a triage is a node only with the kind
  of review it triages

#### Scenario: The orchestrating session directs a step

- **WHEN** a decision line by the orchestrating session directing a review is
  attempted
- **THEN** the log's writer refuses it, since a direction is the owner's

#### Scenario: A decision about one run leaves another waiting

- **WHEN** a validation run has asked a question and a review run beside it stopped,
  and a decision resolves the review's stop
- **THEN** the validation's question still waits, and is answered by resuming its
  session

### Requirement: The next step is computed from the files

The next step of a change MUST be computed by a script that interprets the workflow
graph over the change's index row, its reviews, its tasks, its workflow log, and the
state of any open round view, and the same computation MUST be available to the
owner by hand. When the computation fails or cannot classify the change's state, the
orchestrating session MUST determine what happened and either resolve it, when it
concerns only routing or recovery, or bring it to the owner, when it would decide a
finding, settle a design question, or change a status; and MUST record what it
decided in the workflow log. The computation MUST route on the exit the last step's
outcome names, and on the owner's latest direction until a later run of its target
is logged, and MUST NOT infer an exit from the phase. A review's triage MUST name its
exit in its outcome, and MUST keep the target and the owner's words under its triage
file's `## Next` as prose, which nothing routes on; a review whose triage file exists
while no finished or returned triage outcome, and no conversion line, names it MUST
be treated as a triage in progress. An exit its node does not declare, a validation's exit other than the
target it was given, and an exit whose target's entry guard is not met MUST be
brought to the owner. When a guard on a declared exit is not met, the computation
MUST name the step that satisfies it, carrying the exit as its target, and MUST
bring a guard no step can satisfy to the owner, naming the target and what is
missing. The computation MUST name validation with a target always — the round's
triage in a round's join, the target an owner's direction named after one — and
MUST check the target's guards again on the validation's exit. Every line the
workflow tooling appends to a workflow log MUST carry the log's format marker. A
change whose log holds a line without the marker, or which has numbered review
records and no log, MUST be brought to the owner with the command that converts the
change's records, and its log MUST NOT be read as the new format. The conversion
MUST refuse a change with a triage file in progress by the older reading — with
neither `## Next` nor `## Gate`, and no marked triage outcome naming its review —
naming the review. It MUST rewrite the log's lines in place, each keeping its seq,
so every decision still names the run it named; MUST append one conversion line
naming, as `triaged`, every review with a triage file, and no exit, naming a review
no marked triage outcome names only once the owner, shown the heading line its
triage file was read from, confirms that triage finished; MUST append after it the
owner's direction to the node the change stands at, which the owner confirms or
gives, and which the command proposes from the latest routing decision after the
latest triage — a later direction whose target has not run, or else the triage's
token — with the remedy of any unmet exit guard on the edge it follows, and does
not propose when a step's run follows the latest triage or a later direction's
target can no longer be entered; MUST hold the log's lock from its read through
replacing the log in one step, so that an interrupted conversion leaves the older
log; and every reader and appender of the log MUST, once it holds its lock, open
the log again when the file it locked is no longer the one the log's name holds,
so a line appended while the log is converted is kept. Once the owner confirms
a return, the returned review MUST NOT govern what follows, so the work the return
leads to is implemented, validated, and reviewed afresh, as a round of its own even
where it reworks a section the returned round implemented; a return the owner
declined, or one recorded at closeout, MUST be brought to the owner. An
implementation or pre-closeout round MUST advance only on a `passed` validation
naming its final commit, or a commit from which its final commit differs only in
changes' records — or, after a pre-closeout review, only in paths under `openspec/`
and `docs/`; an `inconclusive` validation MUST be brought to the owner. Nothing
routes on a triage file's `## Next`.

#### Scenario: Reviews await triage

- **WHEN** a change's latest validation and implementation review have no triage
- **THEN** the computation names triage as the next step

#### Scenario: A status was edited by hand

- **WHEN** a change's status disagrees with its workflow log
- **THEN** the orchestrating session follows the files and records that it did

#### Scenario: Triage records another round

- **WHEN** a review's triage named a review of the same kind as its exit, and a
  commit after the commit it reviewed changes more than changes' records — after a
  pre-closeout review, more than paths under `openspec/` and `docs/`
- **THEN** the computation names validation of that commit with the review as its
  target, for an implementation or pre-closeout review, and then the review; with no
  such commit, it names the review again on the same commit

#### Scenario: A triage has not finished

- **WHEN** a review's triage file exists and no finished or returned triage outcome
  names the review
- **THEN** the computation names the triage, or the run waiting in it, and no
  review

#### Scenario: A step names an exit its node lacks

- **WHEN** a design run finishes naming `{"step": "plan"}`, an exit the design node
  does not declare
- **THEN** the computation names the owner, with the design's choice and the design
  node's exits

#### Scenario: A triage names sections out of the plan's order

- **WHEN** an implementation round's triage names
  `{"step": "implement", "sections": [["5"]]}` while section 4 is open, and the fix
  commit's validation passed
- **THEN** the computation names a round of section 5, recorded as it starts

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

#### Scenario: A return confirmed by anyone but the owner

- **WHEN** a decision the log would attribute to the orchestrating session, resolving
  a triage's proposed return and directing planning, is attempted
- **THEN** the log's writer refuses it, and the return still waits for the owner

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

#### Scenario: A change is converted

- **WHEN** a change's log holds older lines, the last triage file of review 21
  records `Another round`, and the owner confirms the review the conversion proposes
- **THEN** each older line is rewritten in place with its seq and marked, one
  conversion line is appended naming every triaged review and no exit, followed by
  the owner's direction to `{"step": "review", "kind": "design"}`, and the
  computation names that review

#### Scenario: A pending return is converted, then confirmed

- **WHEN** a change's last triage, logged at seq 50, proposed a return to planning
  that the owner has not confirmed, and the owner confirms the direction the
  conversion proposes
- **THEN** seq 50 is rewritten in place naming `{"step": "plan"}`, and the
  conversion's direction to planning resolves seq 50; had the owner declined it,
  no direction would be written, and the computation would name the owner for
  seq 50

#### Scenario: A confirmed return is converted

- **WHEN** the owner's decision at seq 51 resolved the returned triage run at seq 50,
  directing design, and design has not run when the change is converted
- **THEN** seq 50 and 51 keep their seqs, the decision still resolves seq 50, and
  the direction the conversion writes names `{"step": "design"}`

#### Scenario: A conversion proposes a guard's remedy

- **WHEN** a change's latest triage file is an implementation round's, recording
  `Advance`, no step's run is logged after it, and the fix commit has no passing
  validation
- **THEN** the conversion proposes the direction
  `{"step": "validate", "target": {"step": "round"}}`

#### Scenario: A conversion after later runs

- **WHEN** a change's latest triage file is a design review's, recording `Advance`,
  and a planning run is logged after that triage's run
- **THEN** the conversion proposes nothing, names the planning run, and writes
  nothing until the owner gives the node with `--next`

#### Scenario: A conversion follows a later direction

- **WHEN** a change's latest triage file is a design review's, recording
  `Another round`, and the owner's later decision directing planning is logged with
  no planning run after it
- **THEN** the conversion proposes `{"step": "plan"}`, not another design review

#### Scenario: A conversion's triage is not attested

- **WHEN** a change's latest triage file has `## Next` written as prose and no
  triage outcome names its review, because the triage's interactive session closed
  before `record`, and the owner declines the conversion that lists it
- **THEN** the log is unchanged; once the triage's outcome is recorded with
  `record`, running the conversion again names the review by that outcome

#### Scenario: An append waits on the conversion

- **WHEN** a step's run opens the log to append its outcome while the conversion
  holds the log's lock, and takes the lock after the converted log has replaced it
- **THEN** the run finds the file it locked replaced, opens the log again, and its
  line is appended to the converted log

#### Scenario: A conversion is interrupted

- **WHEN** a conversion stops after rewriting the older lines and before replacing
  the log
- **THEN** the log is unchanged, the computation still names the owner with the
  conversion command, and running it again converts the change

#### Scenario: A change is converted with a triage in progress

- **WHEN** a change's latest triage file has neither `## Next` nor `## Gate`, and
  no marked triage outcome names its review
- **THEN** the conversion refuses, naming the review and how to finish its triage,
  writes nothing, and the review stays a triage in progress

#### Scenario: An older wrapper appends after the conversion

- **WHEN** a converted log gains a line without the format marker, as the converting
  run's own outcome appended by the wrapper that started it
- **THEN** the computation names the owner with the conversion command again, and
  the conversion, finding a run after the latest triage, requires the owner's
  `--next`

#### Scenario: A validation before closeout passes

- **WHEN** a pre-closeout review's triage named closeout, the computation named
  validation of `HEAD` with closeout as its target, and the validation passed,
  naming closeout as its exit
- **THEN** the computation names closeout

#### Scenario: A validation names another exit

- **WHEN** the computation named validation with closeout as its target, and the
  validation ends finished naming `{"step": "triage", "kind": "implementation"}`
- **THEN** the computation names the owner, with the validation's choice and the
  target it was given

#### Scenario: A closeout correction awaits validation

- **WHEN** a closeout review's triage named archive cleanup and its correction
  changed a path outside `openspec/` and `docs/` since the reviewed commit
- **THEN** the computation names validation of `HEAD`, with archive cleanup as its
  target

#### Scenario: A documentation correction at closeout

- **WHEN** a closeout review's triage named archive cleanup and its correction
  changed only paths under `openspec/` and `docs/`
- **THEN** the computation names archive cleanup without a validation

#### Scenario: A round's validation is inconclusive

- **WHEN** an implementation round's triage named the plan's next round and the fix
  commit's validation is `inconclusive`
- **THEN** the computation names the owner, with the next round as the target, not
  the next round

#### Scenario: An implementation round advances

- **WHEN** an implementation round's triage named the plan's next round, and its
  fixes are committed
- **THEN** the computation names validation of the fix commit, with the next round
  as its target, and once it passes, the next round, without the owner; a triage of
  the last round names the pre-closeout review, reached the same way

#### Scenario: A round is recorded after the fact

- **WHEN** a round's sections were implemented and its records written before the
  round was recorded
- **THEN** the round is recorded naming the last record before it, and the
  computation reads the records above that number as the round's
