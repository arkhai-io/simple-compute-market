## ADDED Requirements

### Requirement: Phases and owner gates

A change MUST move through design, planning, implementation, and closeout, in that
order. The design phase MUST end with a design review, the implementation phase
with a pre-closeout review, and the closeout phase with a closeout review; a phase
ending in a review MUST NOT be treated as finished until that review has been
triaged and the repository owner has recorded, in triage, that its gate is passed.
Planning MUST NOT begin before the design review's gate is passed. Every review —
design, implementation, pre-closeout, and closeout — MUST stop for the owner's
disposition of each finding before any finding is acted on. An agent MUST NOT treat
its own or another agent's agreement with a finding as a disposition.

#### Scenario: A reviewer and the implementing agent agree

- **WHEN** a reviewer raises a finding and the implementing agent agrees with it
- **THEN** nothing is changed until the owner has recorded a disposition for it

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
findings and their dispositions from these files rather than from a reviewer's
session memory. The `reviews/` directory MUST NOT be tracked by version control and
MUST NOT be cited by permanent documentation; anything durable in it MUST reach
permanent documentation through the ordinary promotion path before archival.

#### Scenario: A pre-closeout review asks whether feedback was addressed

- **WHEN** a pre-closeout review runs in a session that produced none of the
  change's earlier reviews
- **THEN** it reads the earlier reviews and their triage from `reviews/` and
  answers for every earlier finding

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

#### Scenario: A reviewed change is archived

- **WHEN** a change whose findings were dispositioned is archived
- **THEN** its `reviews/` directory is gone and its intervention ledger is in the
  archived change directory

### Requirement: One implementation section per fresh session

Each `tasks.md` section MUST be planned to be implementable within one agent session
without compaction, and MUST end at a verification point. Each section MUST be
implemented in a session that begins with no prior conversation, by reading the
repository guidance documents, the change, and that section. Anything a later
session needs MUST be recorded in the change's files before the session ends. Before
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
run whose head commit is the commit under validation. When a slice touches the Helm
charts, an image build input, or a service's configuration surface, validation MUST
include the Helm render checks, with the chart-to-loader check able to run, and a
Helm end-to-end run.

#### Scenario: A lockfile is stale

- **WHEN** validation runs on a slice whose committed lockfile is not current
- **THEN** validation fails and reports the stale lock, and the lockfile is
  unchanged

#### Scenario: An earlier pipeline run exists on the branch

- **WHEN** validation dispatches the end-to-end pipeline and an earlier, finished
  run exists on the same branch
- **THEN** validation reports the run whose head commit is the validated commit,
  never the earlier one

### Requirement: Guarded push of a change branch

An agent MAY push a change's own branch without separate approval, only after a
check confirms that `HEAD` is attached, the worktree is clean, the branch is neither
`main` nor `dev`, and the branch's upstream has the same name. The push MUST send
exactly `HEAD` and MUST NOT be forced. The check MUST report a refused state and
MUST NOT repair it.

#### Scenario: The worktree is dirty

- **WHEN** validation is about to push and the worktree has uncommitted changes
- **THEN** the push check fails, nothing is pushed, and nothing is committed or
  discarded to make it pass

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
