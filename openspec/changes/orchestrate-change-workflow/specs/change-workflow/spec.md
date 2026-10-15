## ADDED Requirements

### Requirement: An orchestrating session advances one change

The repository owner MAY advance one change through its steps from one orchestrating
session. The orchestrating session MUST hold no state beyond the change's files and
its workflow log, so that a new session resumes the change from them alone. It MUST
run the next step the next-step computation names, MUST bring every gate and every
question a step raises to the owner, and MUST NOT pass a gate, answer a design
question, or commit. It MUST advance only the change it was started for.

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

#### Scenario: A step reaches a gate

- **WHEN** a step's outcome is a review ready for its gate
- **THEN** the orchestrating session brings the gate to the owner and does not pass it

### Requirement: Unattended step runs end with a structured outcome

A step MAY be run unattended, through one wrapper, as its leaf skill in a
non-interactive session. Every unattended run MUST end with an outcome that conforms
to the repository's outcome schema and is one of: finished, with the next step;
a question for the owner; a proposed return to an earlier phase; blocked on a
prerequisite; or stopped, with its reason and any tools it was denied. The wrapper
MUST append each outcome, with the run's session and commit, to the change's
workflow log, and MUST record a stopped outcome itself for a run that ends without
one. Where the workflow log and the change's files disagree, the files MUST prevail.
A stopped outcome's denials MUST be taken from the run's own record of denied tools.
A review run's outcome MUST name the review record that run published; a review run
that published none MUST be recorded as stopped, and an earlier record MUST NOT count
as its result.
A question MUST be answered by resuming the same session with the owner's answer.
A proposed return MUST NOT change the change's status until the owner confirms it.
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

### Requirement: The next step is computed from the files

The next step of a change MUST be computed by a script from the change's index row,
its reviews and their triage, its tasks, its workflow log, and the state of any open
round view, and the same
computation MUST be available to the owner by hand. When the computation fails or
cannot classify the change's state, the orchestrating session MUST determine what
happened and either resolve it, when it concerns only routing or recovery, or bring
it to the owner, when it would pass a gate, settle a design question, or change a
status; and MUST record what it decided in the workflow log.

#### Scenario: Reviews await triage

- **WHEN** a change's latest validation and implementation review have no triage
- **THEN** the computation names triage as the next step

#### Scenario: A status was edited by hand

- **WHEN** a change's status disagrees with its workflow log
- **THEN** the orchestrating session follows the files and records that it did

### Requirement: Discussion steps stay conversations with the owner

Design, planning, and triage MUST NOT run without the owner. When orchestrated, each
MUST run as its own resumable session, and each of its messages MUST be shown to the
owner in the orchestrating session, with the owner's reply resuming that session.

#### Scenario: A triage finding is presented

- **WHEN** an orchestrated triage presents a finding
- **THEN** the owner reads it in the orchestrating session, and the owner's
  disposition resumes the triage session

### Requirement: Unattended runs are held to their step's permissions

An unattended run MUST be limited to the tools its step's permission table allows,
and MUST NOT be granted a push other than validation's guarded push. A run denied a
tool MUST end with a stopped outcome naming the denial, rather than asking a question
or working around it. A
change to a step's permissions MUST be made by the owner, as a tracked change, or
granted by the owner for one resumed run. Interactive runs MUST NOT be restricted by
the table.

#### Scenario: Validation attempts to relock

- **WHEN** an unattended validation run attempts `make lock`
- **THEN** the call is denied, and the run ends stopped, its outcome naming the
  denial

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

## RENAMED Requirements

- FROM: `### Requirement: One implementation section per fresh session`
- TO: `### Requirement: Implementation sections and sessions`

## MODIFIED Requirements

### Requirement: Implementation sections and sessions

Each `tasks.md` section MUST be a coherent slice that can be verified, sized by what
it changes and what proves it, and MUST end at a verification point. The plan MUST
NOT prescribe how sections are distributed across agent sessions or review rounds.
A session implementing sections MUST begin with no prior conversation and read the
repository guidance documents, the change, and its sections; the repository owner
decides how many sections a session implements and how many are reviewed together,
before implementation starts. Each section MUST still be checked, handed off, and
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

#### Scenario: The plan's premise fails mid-section

- **WHEN** an implementation session finds code that invalidates the section's plan
- **THEN** it records the finding in the change, commits no partial work, and stops
