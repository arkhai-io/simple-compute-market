## ADDED Requirements

### Requirement: An orchestrating session advances one change

The repository owner MAY advance one change through its steps from one orchestrating
session. The orchestrating session MUST hold no state beyond the change's files and
its workflow log, so that a new session resumes the change from them alone. It MUST
run the next step the next-step computation names, and MUST advance without the
owner wherever the computation names a step. It MUST bring every question a step
raises to the owner, showing each step's message as written, and MUST NOT answer a
design question, decide or state a position on a finding, or commit. It MUST NOT
read code, reviews, or change documents to form or state a view of a finding or a
design question; it MAY read what routing and recovery need: the computation and
the inputs it names, the workflow log, and the denials report.
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
- **THEN** it waits for the owner's notes on the round, saves them as the change's
  next owner-notes record, and closes that view before computing any other step

#### Scenario: A review's triage has nothing for the owner

- **WHEN** a review and the validation beside it raised no finding
- **THEN** the triage records that the change advances, and the orchestrating
  session runs the next step without asking the owner

#### Scenario: A finding is relayed

- **WHEN** an orchestrated triage presents a finding
- **THEN** the orchestrating session shows the triage's message as written, adds no
  position of its own, and resumes the triage with the owner's reply

### Requirement: Unattended step runs end with a structured outcome

A step MAY be run unattended, through one wrapper, as its leaf skill in a
non-interactive session. Every unattended run MUST end with an outcome that conforms
to the repository's outcome schema and is one of: finished, with the next step;
a question for the owner; a proposed return to an earlier phase; blocked on a
prerequisite; or stopped, with its reason and any tools it was denied. The wrapper
MUST append each outcome, with the run's session and commit, to the change's
workflow log, and MUST record a stopped outcome itself for a run that ends without
one. Where the workflow log and the change's files disagree, the files MUST prevail.
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
MUST record, in its triage file's `## Next`, whether the change advances or another
review round runs, beginning with the token `Advance` or `Another round`; the
computation MUST route on that token alone, and MUST treat a triage file without it
as a triage in progress.

#### Scenario: Reviews await triage

- **WHEN** a change's latest validation and implementation review have no triage
- **THEN** the computation names triage as the next step

#### Scenario: A status was edited by hand

- **WHEN** a change's status disagrees with its workflow log
- **THEN** the orchestrating session follows the files and records that it did

#### Scenario: Triage records another round

- **WHEN** a review's triage recorded another round, and a commit after the commit
  it reviewed changes more than changes' records
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
  more than records since the reviewed commit
- **THEN** the computation names validation of `HEAD` before archive cleanup

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
and MUST NOT be granted a push other than validation's guarded push. Every denial a
run records MUST be recorded on the run's outcome, from the run's own record and
with the harness's reason. A run that cannot go on without a denied tool MUST end
with a stopped outcome naming the denial, rather than asking a question or working
around it; a run that goes on MUST do so only by calls its step's rules allow. The
orchestrating session MUST read each recorded denial from the run's record, never
from the step's message; classify it by the harness's reason as a gap in the table
or a forbidden action; check the run's later calls for a workaround; propose, for
a gap, the narrowest rule that matches the call and say whether it is a one-run
grant or a tracked change; and record its reading in the workflow log as a
decision reading that run, before the next step runs. A run whose outcome still
waits — a question, a proposed return — MUST be answered or decided after its
denials are read, and the reading MUST NOT settle that outcome. A denial by a
deny rule MUST NOT be granted for one run. A
change to a step's permissions MUST be made by the owner, as a tracked change, or
granted by the owner for one resumed run. Interactive runs MUST NOT be restricted by
the table.

#### Scenario: Validation attempts to relock

- **WHEN** an unattended validation run attempts `make lock`
- **THEN** the call is denied, and the run ends stopped, its outcome naming the
  denial

#### Scenario: A step is denied a command no rule names

- **WHEN** an unattended run is denied a command because no allow rule names it
- **THEN** the orchestrating session proposes the narrowest allow rule matching the
  call, and the owner grants it for the resumed run or commits it to the table

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
session only on the same harness.

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
run MUST also record the time since its session's previous run and whether its
first turn read the prompt cache. The cost of a change's runs MUST be reportable by
step and by round, with the cache misses and their gaps listed.

#### Scenario: A discussion turn is resumed after a long gap

- **WHEN** a triage session is resumed two hours after its previous run, and its
  first turn rewrites its context to the prompt cache
- **THEN** the run's line records the gap, a cache miss, and the run's own cost,
  not the session's running total, and the cost report lists the miss with its gap

## RENAMED Requirements

- FROM: `### Requirement: Phases and owner gates`
- TO: `### Requirement: Phases and owner touchpoints`

- FROM: `### Requirement: One implementation section per fresh session`
- TO: `### Requirement: Implementation sections and sessions`

## MODIFIED Requirements

### Requirement: Phases and owner touchpoints

A change MUST move through design, planning, implementation, and closeout, in that
order. The design phase MUST end with a design review, the implementation phase
with a pre-closeout review, and the closeout phase with a closeout review; a phase
ending in a review MUST NOT be treated as finished until that review has been
triaged and its triage file records that the change advances. The repository owner
MUST be consulted for the design discussion's questions, for their notes on each
implementation round before its triage, for the disposition of every finding, and
for whether the dispositions merit another review round, which triage MUST ask
once every finding is disposed and before any fix is made; a triage whose review
and validation raised no finding MAY record that the change advances without the
owner. Every other transition MUST proceed without waiting for the owner, unless a
step raises a question only the owner can answer.
Closeout MUST archive the change, merging its specification deltas into the
permanent specifications, before its closeout review, and that review MUST read the
archived change and the permanent documents as archived; the archive is cleaned up,
and the change is `archived`, only once that review's triage records that the
change advances. Closeout MUST
change documentation only; a closeout part that would need a code change MUST return
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

#### Scenario: A closeout gate is passed

- **WHEN** a change's closeout review's triage records that the change advances
- **THEN** triage leaves its index row `in closeout` and stops
- **AND** archive cleanup, run next in its own session, releases its dependents and
  sets its index row to `archived`

#### Scenario: A pre-closeout gate is passed

- **WHEN** a change's pre-closeout review's triage records that the change advances
- **THEN** the triage step sets the change's index row to `ready for closeout`

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
changed to show it; while the branch is moved to show it, review, validation,
triage, and implementation MUST NOT start, and ending the reading MUST return the branch
to the round's commit. A pre-closeout review MUST NOT run, and its triage MUST NOT advance the
change, unless the latest validation's result is `passed` and it names `HEAD`, or a commit
from which `HEAD` descends and differs only in changes' intervention ledgers and review
records, except
where the owner overrides it.

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

- **WHEN** the owner reads a round whose sections were each committed
- **THEN** the round is shown as uncommitted changes over the commit the previous
  round ended on, in the owner's own checkout, and when the reading ends the
  branch is back at the round's commit with the commits unchanged
- **AND** no review, validation, triage, or implementation starts while the
  branch does not point at the round's commit

#### Scenario: Validation fails beside an implementation review

- **WHEN** an implementation round's validation reports a failing scenario
- **THEN** the failure is triaged as a finding of the round, fixed after the owner's
  disposition, and the fix commit is validated again

### Requirement: Implementation sections and sessions

Each `tasks.md` section MUST be a coherent slice that can be verified, sized by what
it changes and what proves it, and MUST end at a verification point. The plan MUST
NOT prescribe how sections are distributed across agent sessions or review rounds.
A session implementing sections MUST begin with no prior conversation and read the
repository guidance documents, the change, and its sections; how many sessions
implement the work, and how much each round covers before it is reviewed, MUST be
settled in the design discussion as the change's implementation cadence, the
plan's sections ordered by it, and the plan MUST map the cadence onto its sections
as the sessions and rounds that implement them. Each round MUST be recorded as it
starts, from that mapping. Each section MUST still be checked, handed off, and
committed on its own. Anything a later session needs MUST be recorded in the change's
files before each section is committed. Before a section is committed, its diff MUST
be checked against the repository guidance by an agent whose context contains no
part of the implementing session. When discovered code invalidates the plan, the
session MUST record why and stop without committing partial work.

#### Scenario: A section is finished

- **WHEN** an implementation session completes a section's tasks
- **THEN** it records any handoff in the section's task notes, a fresh-context
  check of the section's diff passes, and the section is committed; the session
  continues into the next section it was given, or stops

#### Scenario: A plan maps a two-round cadence

- **WHEN** a design settles "round 1: the contract changes; round 2: the handlers
  and the migration", and planning writes sections 1 to 4 in that order
- **THEN** the plan's outcome carries `[[[1, 2]], [[3], [4]]]`, and the second
  round's `round` line is recorded only when that round starts, after the first
  round's triage advanced

#### Scenario: The plan's premise fails mid-section

- **WHEN** an implementation session finds code that invalidates the section's plan
- **THEN** it records the finding in the change, commits no partial work, and stops
