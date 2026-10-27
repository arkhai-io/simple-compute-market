## ADDED Requirements

### Requirement: The workflow graph is declared in code

The workflow's steps and the transitions between them MUST be declared as one table
in code, which the next-step computation interprets: each node a step, qualified by
its review kind where it has one; the exits it may take; the records a join waits
for; and the guards on each edge, each naming the step that satisfies it, or the
owner where no step can. A change to the table MUST be made as an OpenSpec change.
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

- **WHEN** the owner closes an interactive triage session before it recorded its
  outcome
- **THEN** the computation names the triage as in progress, its reason saying that
  an interactive session may have ended without recording, to be resumed or
  recorded by hand

#### Scenario: The harness exports no session id

- **WHEN** the record command runs where the harness's session id variable is unset,
  and no session is given
- **THEN** it refuses, naming the variable, and records nothing

#### Scenario: An unattended run records its own outcome

- **WHEN** a step run by the wrapper runs the record command
- **THEN** the command refuses, and the run's outcome is the one the wrapper records

### Requirement: The owner directs a change's next step

The owner MAY direct a change to any node of the workflow graph, by a decision in the
workflow log naming its target as an outcome names an exit, with a reason, and, where
it skips a guard, the guard it waives; the decision MAY resolve the run waiting on
it. Only the owner MAY direct a step: the orchestrating session MUST NOT direct one
of its own accord, nor record a step's exit on its behalf. The computation MUST name
the directed step until a later run of it is logged, subject to that step's entry
guards and entry check, and the step sets its own status as it starts. A direction
of an archived change to design, planning, or implementation MUST be refused, naming
the archive.

#### Scenario: Closeout finds a design defect before the archive

- **WHEN** closeout, before archiving the change, finds that a design decision
  contradicts a permanent requirement, and the owner directs the change back to
  design
- **THEN** the computation names design, and the design step sets the status
  `in design` as it starts

#### Scenario: The owner waives archive cleanup's validation by a direction

- **WHEN** the computation names a validation before archive cleanup, and the owner
  directs archive cleanup waiving that guard
- **THEN** the computation names archive cleanup, and archive cleanup records the
  waiver in the intervention ledger

#### Scenario: An archived change is directed to design

- **WHEN** a direction of an archived change to design is attempted
- **THEN** the log's writer refuses it, naming the archive

## MODIFIED Requirements

### Requirement: Phases and owner touchpoints

A change MUST move through design, planning, implementation, and closeout, in that
order. The design phase MUST end with a design review, the implementation phase
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
workflow graph by its step, with its review kind for a review, and the sections for
an implementation out of the plan's order. A triage's finished or returned outcome
MUST name the review records it triaged, and the wrapper MUST NOT record a triage's
outcome without them as anything but stopped. The wrapper
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

- **WHEN** an unattended triage ends finished without naming the records it triaged
- **THEN** the wrapper records the run as stopped, naming the missing field

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
while no finished or returned triage outcome names it MUST be treated as a triage in
progress. An exit its node does not declare MUST be brought to the owner. When a
guard on a declared exit is not met, the computation MUST name the step that
satisfies it, carrying the exit as its target, and MUST bring a guard no step can
satisfy to the owner, naming the target and what is missing. Once the owner confirms
a return, the returned review MUST NOT govern what follows, so the work the return
leads to is implemented, validated, and reviewed afresh, as a round of its own even
where it reworks a section the returned round implemented; a return the owner
declined, or one recorded at closeout, MUST be brought to the owner. An
implementation or pre-closeout round MUST advance only on a `passed` validation
naming its final commit, or a commit from which its final commit differs only in
changes' records — or, after a pre-closeout review, only in paths under `openspec/`
and `docs/`; an `inconclusive` validation MUST be brought to the owner. A review that
no triage outcome names MUST be routed by its triage file as written before triage
outcomes named their exits: a `## Next` beginning `Advance`, `Another round`, or
`Returned`, or a `## Gate` beginning `Passed`, read as the target it leads to in its
phase.

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

#### Scenario: A triage file predates triage outcomes

- **WHEN** a review's triage file records `## Next` beginning `Advance`, and no
  triage outcome names the review
- **THEN** the computation reads it as the target `Advance` leads to in its phase

#### Scenario: A triage file predates `## Next`

- **WHEN** a review's triage file ends with a `## Gate` beginning `Passed`, and no
  triage outcome names the review
- **THEN** the computation reads it as `Advance`; any other legacy gate is brought
  to the owner

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
