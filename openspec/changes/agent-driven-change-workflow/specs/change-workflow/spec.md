## ADDED Requirements

### Requirement: Phases and owner gates

A change MUST move through design, planning, implementation, and closeout, in that
order. The design phase MUST end with a design review, the implementation phase
with a pre-closeout review, and the closeout phase with a closeout review; a phase
ending in a review MUST NOT be treated as finished until that review has been
triaged and the repository owner has recorded, in triage, that its gate is passed.
Planning MUST NOT begin before the design review's gate is passed. A design
decision made after that gate, such as one planning exposes, MUST return the change
to design; the owner MAY waive another design review for it, and a waiver MUST be
recorded in the intervention ledger. Every review —
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
  gate passes or the owner's waiver of that review is recorded

#### Scenario: A design review accepts a blocking finding

- **WHEN** the owner accepts a `blocking` finding in a design review
- **THEN** the change remains in design until the fix lands and the owner passes
  the gate, and planning does not begin

### Requirement: Index transitions are written by the step that makes them

Each change of a change's phase or state MUST be written to its row in the
active-change index by the skill that makes it, in the same step: design
discussion starting, triage passing a phase-closing gate, planning starting and
the owner accepting the plan, the first implementation section starting, closeout
starting, and archival. An implementation review after a section MUST NOT change
the status.

#### Scenario: A pre-closeout gate is passed

- **WHEN** the owner passes the gate of a change's pre-closeout review in triage
- **THEN** the triage step sets the change's index row to `ready for closeout`

### Requirement: Review records

Each review of a change MUST be written as one Markdown file in that change's
`reviews/` directory, numbered in the order reviews are produced, and that file
MUST be the only record of its findings. Each finding MUST state its lens, its
basis, its severity, and the evidence it cites. A later review MUST obtain earlier
findings and their dispositions from these files rather than from session memory;
a review of the same kind as an earlier one MAY continue the reviewer session that
wrote it, so the reviewer keeps the context behind its findings, but MUST still read
the triage and dispositions from the records. The `reviews/` directory MUST NOT be tracked by version control and
MUST NOT be cited by permanent documentation; anything durable in it MUST reach
permanent documentation through the ordinary promotion path before archival.

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
MUST be presented to the owner, none withheld for being minor or uncontested.

#### Scenario: A minor finding the agent agrees with

- **WHEN** a review contains a `minor` finding the implementing agent agrees with
- **THEN** it is still presented to the owner with the agent's reason

### Requirement: Intervention ledger

Each disposition the owner records MUST be appended as one entry to the change's
`interventions.jsonl`, stating the review, the `tasks.md` section the finding
concerns when it concerns one, the finding's lens, basis, and severity,
the implementing agent's position, the owner's disposition, and a one-line summary.
The ledger MUST be tracked by version control, MUST remain in the change directory,
and MUST be archived with the change.

Each time the owner changes or reverses the agent's recommendation during a design
discussion, an entry MUST be appended in the same shape, with `review` set to
`design`, the decision as `finding`, lens `direction`, basis `judgement`, and a null
severity. A recommendation the owner accepts MUST NOT be logged.

#### Scenario: The owner reverses a design recommendation

- **WHEN** the owner chooses a different option than the one the agent recommended
  for a design decision
- **THEN** one ledger entry records the decision, the agent's recommendation, and
  what the owner chose and why

#### Scenario: A reviewed change is archived

- **WHEN** a change whose findings were dispositioned is archived
- **THEN** its `reviews/` directory is gone and its intervention ledger is in the
  archived change directory

### Requirement: One implementation section per fresh session

Each `tasks.md` section MUST be planned to be implementable within one agent session
without compaction, and MUST end at a verification point. A session implementing a
section MUST begin with no prior conversation and read the repository guidance
documents, the change, and that section; by default it implements that one section.
The repository owner MAY direct the session to continue into later sections, each
still checked, handed off, and committed on its own, and decides when the sections
committed since the last implementation review are reviewed together. Anything a
later session needs MUST be recorded in the change's files before each section is
committed. Before
a section is committed, its diff MUST be checked against the repository guidance by
an agent whose context contains no part of the implementing session. When discovered
code invalidates the plan, the session MUST record why and stop without committing
partial work.

#### Scenario: A section is finished

- **WHEN** an implementation session completes a section's tasks
- **THEN** it records any handoff in the section's task notes, a fresh-context
  check of the section's diff passes, and the section is committed; the next
  section starts in a new session

#### Scenario: The plan's premise fails mid-section

- **WHEN** an implementation session finds code that invalidates the section's plan
- **THEN** it records the finding in the change, commits no partial work, and stops

### Requirement: Validation observes a committed slice

Validation before an implementation review MUST describe one commit and MUST NOT
modify the checkout: it MUST fail if the worktree is not clean when it starts or
when it finishes, and MUST NOT regenerate lockfiles or any other tracked file. A
condition validation could repair, such as a stale lock, MUST fail validation and
return the slice to implementation. End-to-end evidence MUST come from a pipeline
run whose head commit is the commit under validation. Validation MUST also build the
service images and include the Helm render checks, with the chart-to-loader check
able to run, and a Helm end-to-end run of the scenarios the pipeline runs. A skipped
chart-to-loader check MUST fail validation. A pipeline scenario the charts cannot
serve MAY be excluded from the Helm run only by an explicit list naming the
missing service, and MUST be reported as not run, never as passed. Validation MUST
NOT fix what it finds.

#### Scenario: A lockfile is stale

- **WHEN** validation runs on a slice whose committed lockfile is not current
- **THEN** validation fails and reports the stale lock, and the lockfile is
  unchanged

#### Scenario: An earlier pipeline run exists on the branch

- **WHEN** validation dispatches the end-to-end pipeline and an earlier, finished
  run exists on the same branch
- **THEN** validation reports the run whose head commit is the validated commit,
  never the earlier one

#### Scenario: A pipeline scenario needs a service the charts do not deploy

- **WHEN** the Helm end-to-end run reaches a pipeline scenario that needs a service
  the charts do not deploy
- **THEN** the scenario is on the exclusion list with that service named, and the
  validation report lists it as not run against Helm

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
session. Each validation failure MUST be presented as a finding, with its diagnosis
checked against the logs. The owner's notes MUST be saved verbatim as a review
record and triaged like any review: the triaging agent MUST state its own position
on each point rather than carry it out as an instruction, and each disposition
MUST be logged to the intervention ledger. Accepted fixes MUST pass the checks a
section passes before they are committed, and the commit MUST be validated again.
A pre-closeout review MUST NOT run, and its gate MUST NOT pass, unless the latest
validation names `HEAD` and passed, except where the owner overrides it.

#### Scenario: The owner's note is contradicted by the files

- **WHEN** a point in the owner's notes rests on a claim the files contradict
- **THEN** triage says so, with the evidence, and nothing changes until the owner
  has recorded a disposition

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
