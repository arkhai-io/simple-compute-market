## ADDED Requirements

### Requirement: The owner interrupts a running step

The orchestrating session MUST, on the owner's word, be able to stop a running
unattended step of its change through a command that signals the process the run
recorded as it started, so that the run is logged `stopped` with its session; when two
runs of the change are in progress, the command MUST name the step it stops, and it
MUST refuse, stopping nothing, when no run of the change is in progress. The owner's
interrupt MUST be recorded as an owner's decision that resolves no run. A stopped run
MUST then be recovered as any stop is: resumed with the owner's words, rerun, or
resolved by the owner's decision. A stop MUST commit nothing, and an interrupted
review MUST publish nothing.

#### Scenario: The owner interrupts a running validation

- **WHEN** the owner tells the orchestrating session to stop the change's running
  validation
- **THEN** the run is logged `stopped` with its session, the owner's interrupt is
  recorded as their decision, and the run is resumed with the owner's words, rerun, or
  resolved as the owner says

#### Scenario: Two runs are in progress

- **WHEN** a validation and a review of the change run side by side and the owner
  interrupts the review
- **THEN** the stop names the review, the validation runs on, and the review publishes
  nothing and is rerun

#### Scenario: Nothing is running

- **WHEN** the stop command is given for a change with no run in progress
- **THEN** it refuses, saying no run is in progress, and stops nothing

### Requirement: The owner revisits a default acceptance

The owner MAY revisit a finding a triage accepted by default, or the advancing exit it
took, after that triage finished. On the owner's direction naming that triage's run,
the run MUST be resumable with the owner's words while it is the latest triage run of
the reviews it triaged; no other finished run MAY be resumed. A step started after that
triage and still running MUST be stopped first, and a stopped step it leaves MUST be
resolved rather than resumed. The resumed triage MUST amend its fixes in a new commit,
log the correction in the intervention ledger, and name its exit again, and its outcome
MUST govern the reviews it names.

#### Scenario: A revisit while the fix commit is validated

- **WHEN** the owner revisits a default-accepted finding while the validation of that
  triage's fix commit runs
- **THEN** the validation is stopped and resolved, the triage session resumes with
  the owner's words, amends the fix in a new commit, logs the revisit, and names its
  exit, and the computation routes on that outcome

#### Scenario: A finished run is resumed without a direction

- **WHEN** a finished triage run is resumed with no owner's direction naming it
- **THEN** the resume is refused, naming the run as not waiting

#### Scenario: A later triage has run

- **WHEN** the owner directs a revisit of a triage whose reviews a later triage run
  already triaged again
- **THEN** the direction is refused, naming the later triage

### Requirement: Waivers are recommended and the owner's to take

A step that meets a guard the owner may waive MAY recommend a waiver only when a
written criterion holds — the commits differ from validated ones only in paths no part
of validation exercises; a failure is a known environmental one diagnosed in an earlier
validation record of the change; a review and a validation name commits that differ
only in records or documentation; or a decision made after a return to design is
confined to one requirement's wording or a choice the design review weighed — and the
recommendation MUST name its criterion and evidence. Only the owner's word MUST waive.

#### Scenario: A round's review and validation name different commits

- **WHEN** a triage finds the review and the validation of a round name commits that
  differ only in documentation
- **THEN** it recommends the owner waive the rule, naming that criterion and the paths,
  and the records are triaged as one round only once the owner waives it

#### Scenario: No criterion holds

- **WHEN** a guard's remedy is pending and no written criterion holds
- **THEN** the step recommends no waiver

### Requirement: Guidance reviews

A guidance review MUST be run by the owner, interactively, outside any change's steps,
over the records of every change since the previous guidance review. It MUST report
the dispositions, the default acceptances and their revisits against the default rule's
measured baseline, an audit of a sample of default acceptances' recorded
classifications against their findings, the waivers recommended and how many the owner
took, and the terms the owner asked about. It MUST group the owner's corrections into
guidance that is false, rules applied but unwritten, and rules written but unenforced,
and MUST list candidate guidance edits for the owner to pick. On the owner's word it
MUST write the proposal of a change carrying the edits picked, stating the period it
covered.

#### Scenario: The owner runs a guidance review

- **WHEN** the owner runs a guidance review after several changes have been triaged
- **THEN** it reads their records from where the newest proposal it wrote says its
  period ended, reports the figures and the audit, and writes a proposal only for the
  edits the owner picks

### Requirement: A change's closing checks enforce written rules

A change's closing checks MUST fail when a decision headed `D<n>` under its design's
`## Decisions` has no bullet starting `D<n>` in its proposal's knowledge to promote;
when a comment or docstring line its diff adds uses history wording on the check's
list; when a package version differs from its version at the merge-base with the
branch the change lands on by more than one SemVer step; when an import its diff adds
inside a function has no comment giving its reason; or when a capability with a
specification has no row in the capability index, or a row links no capability. The
public-content check MUST refuse a private-key block whose body holds a line of 40 or
more base64 characters, reporting its location without its content.

#### Scenario: A decision names no destination

- **WHEN** a design records `### D7` and the proposal's knowledge to promote has no
  bullet starting `D7`
- **THEN** the closing checks fail, naming D7

#### Scenario: A comment describes history

- **WHEN** a change's diff adds the comment "# previously read from the pool table"
- **THEN** the closing checks fail, naming the file and line

#### Scenario: A package is bumped twice

- **WHEN** a package at 0.4.0 on the merge-base is at 0.4.2 on the change's branch
- **THEN** the closing checks fail, naming the package and both versions

#### Scenario: A larger bump replaces a smaller one

- **WHEN** a package at 0.4.0 on the merge-base, bumped to 0.4.1 for a fix, is bumped
  to 0.5.0 for an incompatible edit
- **THEN** the version check passes

#### Scenario: A local import has no reason

- **WHEN** a change's diff adds an import inside a function with no comment beside or
  above it
- **THEN** the closing checks fail, naming the file and line

#### Scenario: A capability has no index row

- **WHEN** `openspec/specs/<capability>/spec.md` exists and the capability index has
  no row linking it
- **THEN** the closing checks fail, naming the capability

#### Scenario: A key fixture carries no key material

- **WHEN** a test fixture holds a private-key block whose body is the word `fixture`
- **THEN** the public-content check passes it

#### Scenario: A real key is staged

- **WHEN** a staged file holds a private-key block with base64 key lines
- **THEN** the public-content check refuses it, naming the file and line without
  echoing the key

## MODIFIED Requirements

### Requirement: Phases and owner touchpoints

A change MUST move through design, planning, implementation, and closeout, in that
order, except where the owner directs a step, as the requirement on the owner's
directions allows; no direction crosses the archive. The design phase MUST end with a design review, the implementation phase
with a pre-closeout review, and the closeout phase with a closeout review; a phase
ending in a review MUST NOT be treated as finished until that review has been
triaged and its triage's outcome names, as its exit, a step of the next phase — for
the implementation phase, the merge that precedes closeout. Once the pre-closeout
review's triage advances the change, a merge step MUST bring the branch the change
lands on — the branch it was branched from, `dev` unless the owner names another —
into the change's branch, resolve its conflicts, and reconcile the change's own code
with what that branch changed even where the merge reported no conflict, before closeout
starts; closeout MUST NOT start until a validation of the merged `HEAD` passed,
unless the owner waives it. The merge MUST judge whether its resolutions merit
another pre-closeout review and whether its validation may be waived, and MUST
take either only on the owner's confirmation; without either, it MUST advance to
closeout without waiting for the owner. The
repository owner MUST be consulted for the design discussion's questions, for their
notes on each implementation round before its triage, for the disposition of every
finding the triage does not accept by default, and, when the triage recommends another
review round, for whether the dispositions merit one, which triage MUST ask once every
discussed finding is disposed and before any fix is made; when the triage recommends
advancing, it MUST take the advancing exit without asking, and a triage with no finding
to discuss and no point of the owner's notes to dispose of MAY finish without the
owner. Every other transition MUST proceed without waiting for
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
disposition of each discussed finding before any finding is acted on. An agent MUST
NOT treat its own or another agent's agreement with a finding as a disposition, except
as the default acceptance the requirement on triage of every finding defines.

#### Scenario: A reviewer and the implementing agent agree

- **WHEN** a reviewer raises a finding the default-acceptance rule does not admit and
  the implementing agent agrees with it
- **THEN** nothing is changed until the owner has recorded a disposition for it

#### Scenario: A triage recommends advancing

- **WHEN** every discussed finding of a triage is disposed and the agent recommends
  advancing
- **THEN** the triage takes the advancing exit without asking whether another round is
  merited, and reports it beside the table of default acceptances

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
  archive cleanup's own check finds the direction in the log and records the waiver
  in the ledger, without asking the owner again

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

- **WHEN** the owner has disposed of every discussed finding of an implementation round
  and the agent recommends another review round
- **THEN** triage asks whether the accepted fixes merit it and records the owner's
  answer before making any fix

### Requirement: Review records

Each review of a change MUST be written as one Markdown file in that change's
`reviews/` directory, numbered in the order reviews are produced, and that file MUST
be the only record of its findings. The order of the records MUST be establishable —
by number, or, where two records of different kinds share a number, by their file
times — and a record MUST NOT be overwritten. Each finding MUST state its lens, its
basis, its severity, its alternatives — each option a reasonable owner might choose,
with its trade-off, or none and why the fix is evident — and the evidence it cites. A
later review MUST obtain earlier
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

#### Scenario: A finding states no alternatives

- **WHEN** a reviewer's finding has no alternatives field
- **THEN** the review is not published, and the output is kept beside the transcript

#### Scenario: A finding has one evident fix

- **WHEN** a finding's fix has no alternative a reasonable owner might choose
- **THEN** its alternatives state none and why the fix is evident

### Requirement: Triage of every finding

The implementing agent MUST record, for every finding in a review, its own position
— agree, disagree, or partly — with the evidence for it and a proposed action, and a
position of agreement MUST state its reason as a disagreement does. A finding MUST be
accepted by default when, and only when, it comes from a review rather than a
validation record, the owner's notes, or the orchestrating session's observations; its
severity is not `blocking`; the agent agrees and proposes one edit or one fix; neither
the reviewer nor the agent lays out an alternative and the agent names nothing that
would change its recommendation; and its fix touches no interface or representation,
migration or compatibility path, the change's scope, or validation environment. The
triage record MUST state, for each default acceptance, how the finding met each
condition, written before any finding is presented, and MUST record it as accepted by
default rather than as a disposition the owner stated. Every other finding MUST be
presented to the owner, none withheld for being minor or uncontested, and MUST be
treated as disposed of only when the owner states a disposition for it. Default
acceptances MUST be reported to the owner in one table, giving each finding's label,
severity, the finding in one line, and its outcome, with the triage's last question
when it asks one and otherwise with its final report.

#### Scenario: A minor finding the agent agrees with

- **WHEN** a review contains a `minor` finding the implementing agent agrees with, and
  the reviewer lays out alternatives
- **THEN** it is presented to the owner with the agent's reason

#### Scenario: A finding is accepted by default

- **WHEN** a `should` review finding meets every condition of the default rule
- **THEN** it is not presented on its own, the triage record states its classification
  and that it was accepted by default, and it appears in the table of default
  acceptances

#### Scenario: A blocking finding with one evident edit

- **WHEN** the agent agrees with a `blocking` finding and proposes one edit
- **THEN** it is presented to the owner and disposed of only by the owner's word

#### Scenario: The table rides on the last question

- **WHEN** a triage has findings to discuss and findings accepted by default
- **THEN** the table of default acceptances is shown with its last question, before
  any fix is made

#### Scenario: A validation failure the agent agrees with

- **WHEN** a validation record's failure has one evident fix the agent agrees with
- **THEN** it is presented to the owner, since it does not come from a review

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
as it stands MUST NOT be logged; the triage record holds every disposition. A
correction of a finding accepted by default, made before its fix or after, MUST be
logged in the same shape, its disposition beginning `revisits default acceptance:`. A
waiver a step recommended MUST be logged with the recommendation and its criterion as
the agent's position, and a recommended waiver the owner declines is a correction.
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

#### Scenario: The owner revisits a default acceptance

- **WHEN** the owner corrects a finding the triage accepted by default
- **THEN** one ledger entry records it under the finding's review and label, its
  disposition beginning `revisits default acceptance:`

#### Scenario: The owner declines a recommended waiver

- **WHEN** a step recommends a waiver and the owner declines it
- **THEN** one ledger entry records the recommendation, its criterion, and the owner's
  reason

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

### Requirement: Discussion steps stay conversations with the owner

Design MUST NOT run without the owner. Triage MUST bring every finding it does not
accept by default, and every point of the owner's notes, to the owner, and MAY finish
without the owner only when there is none and it recommends advancing. When
orchestrated, each MUST run as its own resumable session, presenting one decision or
discussed finding per turn, and each
of its messages MUST be shown to the owner in the orchestrating session, with the
owner's reply resuming that session. Planning MUST NOT ask the owner to accept the
plan; a plan that needs a decision the design does not make MUST return the change
to design.

#### Scenario: A triage finding is presented

- **WHEN** an orchestrated triage presents a finding
- **THEN** the owner reads it in the orchestrating session, and the owner's
  disposition resumes the triage session

#### Scenario: Every finding is accepted by default

- **WHEN** every finding of an orchestrated triage is accepted by default and the
  agent recommends advancing
- **THEN** the triage asks nothing, and its final report, with the table and the exit,
  is shown to the owner in the orchestrating session
