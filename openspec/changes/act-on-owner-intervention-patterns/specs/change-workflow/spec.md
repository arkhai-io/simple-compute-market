## ADDED Requirements

### Requirement: CW-k2rv The owner stops a running step through the command

The orchestrating session MUST, on the owner's word, be able to stop a running
unattended step of its change through a command that signals the process the run
recorded as it started, so that the run is logged `stopped` with its session and any
process the run started is ended. When two runs of the change are in progress, the
command MUST name the step it stops; it MUST refuse, stopping nothing, when no run of
the change is in progress. The owner's interrupt MUST be recorded as an owner's
decision that resolves no run.

#### Scenario: The owner interrupts a running validation

- **WHEN** the owner tells the orchestrating session to stop the change's running
  validation
- **THEN** the run is logged `stopped` with its session, the owner's interrupt is
  recorded as their decision, and the run is resumed with the owner's words, rerun, or
  resolved as the owner says

#### Scenario: Two runs are in progress

- **WHEN** a validation and a review of the change run side by side and the owner
  interrupts the review
- **THEN** the stop names the review, the validation runs on, the review is logged
  `stopped`, its reviewer process is ended, and the review publishes nothing and is
  rerun

#### Scenario: Nothing is running

- **WHEN** the stop command is given for a change with no run in progress
- **THEN** it refuses, saying no run is in progress, and stops nothing

### Requirement: CW-h7lq A stop signals only a run that still holds its record

The stop command MUST verify that the recorded run still holds its record, when it
selects the run and again immediately before the signal, and MUST refuse, signalling
nothing, a record whose run no longer holds it at either check.

#### Scenario: A run record outlives its run

- **WHEN** the stop command finds a record whose run is no longer holding it
- **THEN** it refuses, naming the record as stale, and signals nothing

#### Scenario: A run ends while it is being stopped

- **WHEN** the run the stop command selected ends before the check immediately before
  the signal
- **THEN** the command refuses and signals nothing

### Requirement: CW-w4ne A stopped run is recovered as any stop, and a late stop ends nothing

A run the owner stopped MUST be recovered as any stop is: resumed with the owner's
words, rerun, or resolved by the owner's decision. A stop MUST commit nothing, and an
interrupted review MUST publish nothing. A run MUST end with its line however a stop
reaches it: a stop that arrives after the run's agent or reviewer has exited MUST end
nothing, and the run MUST log the outcome it reached.

#### Scenario: A stop arrives as the run writes its line

- **WHEN** the stop command signals a review whose reviewer has exited and whose record
  is published, before its line is written
- **THEN** the run is not killed, its line records the outcome it reached, `finished`
  naming the record, and the owner's interrupt resolves no run

### Requirement: CW-r8vz The owner revisits a default acceptance

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

### Requirement: CW-q3dm Waivers are recommended and the owner's to take

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

### Requirement: CW-g6ua Guidance reviews

A guidance review MUST be run by the owner, interactively, outside any change's steps,
over the records of every change since the previous guidance review. It MUST report
the dispositions, the default acceptances and their revisits against the default rule's
measured baseline, an audit of a sample of default acceptances' recorded
classifications against their findings, the waivers recommended and how many the owner
took, and the terms the owner asked about. It MUST group the owner's corrections into
guidance that is false, rules applied but unwritten, and rules written but unenforced,
and MUST list candidate guidance edits for the owner to pick. On the owner's word it
MUST write the proposal of a change carrying the edits picked, stating the period it
covered. Every guidance review, whether or not it writes a proposal, MUST record its
period, its headline figures, and the proposal it wrote or none, and the next guidance
review MUST start where the last recorded period ended.

#### Scenario: The owner runs a guidance review

- **WHEN** the owner runs a guidance review after several changes have been triaged
- **THEN** it reads their records from the end of the last recorded period, reports
  the figures and the audit, writes a proposal only for the edits the owner picks, and
  records its period

#### Scenario: A guidance review picks nothing

- **WHEN** the owner picks no edit in a guidance review
- **THEN** no proposal is written, the review's period is recorded with no proposal,
  and the next guidance review starts where that period ended

### Requirement: CW-d5ac A review finding the default rule admits is accepted by default

A finding MUST be accepted by default when, and only when, it comes from a review
rather than a validation record, the owner's notes, or the orchestrating session's
observations; its severity is not `blocking`; the agent agrees and proposes one edit or
one fix; neither the reviewer nor the agent lays out an alternative and the agent names
nothing that would change its recommendation; and its fix touches no interface or
representation, migration or compatibility path, the change's scope, or validation
environment. The triage record MUST state, for each default acceptance, how the finding
met each condition, written before any finding is presented, and MUST record it as
accepted by default rather than as a disposition the owner stated.

#### Scenario: A finding is accepted by default

- **WHEN** a `should` review finding meets every condition of the default rule
- **THEN** it is not presented on its own, the triage record states its classification
  and that it was accepted by default, and it appears in the table of default
  acceptances

#### Scenario: A blocking finding with one evident edit

- **WHEN** the agent agrees with a `blocking` finding and proposes one edit
- **THEN** it is presented to the owner and disposed of only by the owner's word

### Requirement: CW-t9bx Default acceptances are reported in one table

A triage's default acceptances MUST be reported to the owner in one table, giving each
finding's label, severity, the finding in one line, and its outcome, with the triage's
last question when it asks one and otherwise with its final report.

#### Scenario: The table rides on the last question

- **WHEN** a triage has findings to discuss and findings accepted by default
- **THEN** the table of default acceptances is shown with its last question, before
  any fix is made

### Requirement: CW-a2lf Each finding states its alternatives

Each finding MUST state its alternatives: each option a reasonable owner might choose,
with its trade-off, or none and why the fix is evident. A reviewer's output with a
finding that states no alternatives MUST NOT be published as a review.

#### Scenario: A finding states no alternatives

- **WHEN** a reviewer's finding has no alternatives field
- **THEN** the review is not published, and the output is kept beside the transcript

#### Scenario: A finding has one evident fix

- **WHEN** a finding's fix has no alternative a reasonable owner might choose
- **THEN** its alternatives state none and why the fix is evident

### Requirement: CW-v1rk A revisited default acceptance is logged and marked

A correction of a finding accepted by default, made before its fix or after, MUST be
logged to the ledger in the shape of any course correction, its disposition beginning
`revisits default acceptance:`.

#### Scenario: The owner revisits a default acceptance

- **WHEN** the owner corrects a finding the triage accepted by default
- **THEN** one ledger entry records it under the finding's review and label, its
  disposition beginning `revisits default acceptance:`

### Requirement: CW-n6wy A recommended waiver is logged with its criterion

A waiver a step recommended MUST be logged to the ledger with the recommendation and
its criterion as the agent's position, and a recommended waiver the owner declines is a
course correction.

#### Scenario: The owner declines a recommended waiver

- **WHEN** a step recommends a waiver and the owner declines it
- **THEN** one ledger entry records the recommendation, its criterion, and the owner's
  reason

## MODIFIED Requirements

### Requirement: CW-9pbk The owner is consulted at fixed touchpoints

The owner MUST be consulted for the design discussion's questions, for their notes
on each implementation round before its triage, for the disposition of every
finding the triage does not accept by default (CW-d5ac), and, when the triage
recommends another review round, for whether the dispositions merit one, which triage
MUST ask once every discussed finding is disposed of and before any fix is made. When
the triage recommends advancing, it MUST take the advancing exit without asking.
Every other transition MUST proceed without waiting for the owner, unless a step
raises a question only the owner can answer.

#### Scenario: Another round is decided before the fixes

- **WHEN** the owner has disposed of every discussed finding of an implementation round
  and the agent recommends another review round
- **THEN** triage asks whether the accepted fixes merit it and records the owner's
  answer before making any fix

#### Scenario: A triage recommends advancing

- **WHEN** every discussed finding of a triage is disposed and the agent recommends
  advancing
- **THEN** the triage takes the advancing exit without asking whether another round is
  merited, and reports it beside the table of default acceptances

### Requirement: CW-3tvs Design and triage are conversations with the owner

Design MUST NOT run without the owner. Triage MUST bring every finding it does not
accept by default, and every point of the owner's notes, to the owner, and MAY finish
without the owner only when there is none and it recommends advancing. When
orchestrated, each MUST run as its own resumable session, presenting one decision or
discussed finding per turn, each of its messages shown to the owner in the
orchestrating session and the owner's reply resuming that session.

#### Scenario: A triage finding is presented

- **WHEN** an orchestrated triage presents a finding
- **THEN** the owner reads it in the orchestrating session, and the owner's
  disposition resumes the triage session

#### Scenario: Every finding is accepted by default

- **WHEN** every finding of an orchestrated triage is accepted by default and the
  agent recommends advancing
- **THEN** the triage asks nothing, and its final report, with the table and the exit,
  is shown to the owner in the orchestrating session

### Requirement: CW-j1nv Triage states a position on every finding and presents every one

The implementing agent MUST record, for every finding in a review, its own position
(agree, disagree, or partly) with the evidence for it and a proposed action, and a
position of agreement MUST state its reason as a disagreement does. Every finding not
accepted by default (CW-d5ac) MUST be presented to the owner, none withheld for being
minor or uncontested.

#### Scenario: A minor finding the agent agrees with

- **WHEN** a review contains a `minor` finding the implementing agent agrees with, and
  the reviewer lays out alternatives
- **THEN** it is presented to the owner with the agent's reason

#### Scenario: A validation failure the agent agrees with

- **WHEN** a validation record's failure has one evident fix the agent agrees with
- **THEN** it is presented to the owner, since it does not come from a review

### Requirement: CW-neua A finding is disposed of only by the owner

Every review MUST stop for the owner's disposition of each finding it does not accept
by default before any finding is acted on, and such a finding MUST be treated as
disposed of only when the owner states a disposition for it. An agent MUST NOT treat
its own or another agent's agreement with a finding as a disposition, except as the
default acceptance CW-d5ac defines.

#### Scenario: A reviewer and the implementing agent agree

- **WHEN** a reviewer raises a finding the default rule does not admit and the
  implementing agent agrees with it
- **THEN** nothing is changed until the owner has recorded a disposition for it

#### Scenario: The owner discusses one finding and not another

- **WHEN** the owner asks about one finding and says nothing of another
- **THEN** the other has no disposition, and is presented again before another
  round is asked about

### Requirement: CW-zkhs Validation's parts are the repository's

Validation MUST run the repository's validation parts but those the owner waived
(CW-e7lm), and each part's evidence MUST come from the commit under validation,
never from another commit's build, run, or state.

#### Scenario: A part finds only another commit's evidence

- **WHEN** a validation part finds a finished run of its evidence only for an earlier
  commit of the branch
- **THEN** it does not report that run as evidence of the validated commit

### Requirement: CW-e7lm Validation's result is passed, failed, or inconclusive

A validation's result MUST be `passed`; `failed`, for a failure caused by the commit
or of unknown cause; or `inconclusive`, when no failure is caused by the commit but
a part produced no evidence for an environmental reason. Any part MAY be waived, and
only by the owner. A waived part MUST be recorded as `waived`: an omission of
evidence, neither passed, failed, nor inconclusive, counted in no result, which is
judged on the parts that ran; a requirement that validation run a part, dispatch
its workflows, or judge its evidence applies only to the parts not waived. A
validation with every part waived MUST NOT be recorded: waiving validation entirely
is the owner's direction past the guard it remedies. A waiver for later validations
MUST be the owner's decision in the change's workflow log, naming the parts and the
condition they are waived on; validation MUST read it before running any part, and
MUST run a waived part, saying in the record that the waiver lapsed and why, when
the condition does not hold over the commits since the last validation that ran
that part, or when those commits include a merge.

#### Scenario: A part produces no evidence for an environmental reason

- **WHEN** no failure is caused by the commit, and one part produced no evidence
  because its environment was unavailable
- **THEN** the result is `inconclusive`, neither `passed` nor `failed`

#### Scenario: Parts are waived for the rest of the change

- **WHEN** the change's log holds the owner's decision waiving the Helm and pipeline
  parts on a condition that holds over the commits since those parts last ran
- **THEN** validation runs neither, records both as `waived` naming the decision, and
  judges the result on the local and CI parts

#### Scenario: A standing waiver lapses at a merge

- **WHEN** the commits since the pipeline last ran include a merge
- **THEN** validation runs the pipeline despite the owner's waiver of it, and the
  record says the waiver lapsed at the merge

#### Scenario: The owner waives an environmental failure

- **WHEN** a part fails for an environmental reason and the owner waives it rather
  than remedy it
- **THEN** the part is recorded as `waived`, and the result is judged on the other
  parts rather than being `inconclusive` for it
