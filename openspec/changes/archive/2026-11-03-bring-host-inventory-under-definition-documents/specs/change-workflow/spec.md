## MODIFIED Requirements

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
call a deny rule refused MUST NOT be done by another tool, except where the rule
exists only to keep file writes on the Edit and Write tools — the step table marks
such rules, as sed's in-place forms, find's deleting, running, and writing
actions, and the diff family's output-to-file forms — whose refused shell write
MAY be made with the Edit or Write tool the step's rules allow. A call denied for
want of an allow rule MAY be done by a tool the step's rules allow for the same
work. Either way the run MUST name that substitute in its message. The orchestrating session
MUST read each recorded denial from the run's record, never from the step's
message; classify it by the harness's reason as a gap in the table or a
forbidden action, matching a command refused by its parts, or one with no
reason, against the step's deny rules; check the run's later calls, after a deny-rule
denial, for a workaround; read a write-steering rule's denial whose write was made
with the Edit or Write tool as a gap, which needs no ruling from the owner; propose,
for a gap, the narrowest rule that matches the
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
again. A file-tool rule's relative path, in the table or in a grant, MUST name a
path from the root of the checkout the run starts in, whatever directory the run
has since moved to. Interactive runs MUST NOT be restricted by the table.

#### Scenario: A step changes directory before writing a file its table allows

- **WHEN** an unattended run changes its working directory into a subdirectory
  and then writes a file its step's relative file rule names from the checkout's
  root
- **THEN** the write is allowed, as it would be from the checkout's root

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

#### Scenario: A step's in-place sed is refused and the step uses the Edit tool

- **WHEN** an unattended run's `sed -i` is refused by the deny rule that keeps file
  writes on the Edit tool, and the run makes the same edit with the Edit tool its
  step's rules allow
- **THEN** the run names the substitute in its message, and the orchestrating
  session reads the denial as a gap, not a workaround, with no ruling asked of the
  owner

#### Scenario: A question carries denials

- **WHEN** an unattended validation was denied a command it could do without, went
  on, and ended with a question
- **THEN** the next-step computation names the owner for the reading of the denial
  first, carrying it; once a decision reads that run, the question waits for its
  answer, and the same session resumes with it

#### Scenario: A step is denied by a deny rule

- **WHEN** an unattended run is denied a call that a deny rule forbidding the work
  itself names, such as `git stash`
- **THEN** the denial stands, no other tool does the work, and the run's attempt
  is reported to the owner as a finding

#### Scenario: A step commits its work

- **WHEN** an unattended implementation run commits a section
- **THEN** it pushes that commit through the guarded push of the change's branch, and
  any other push it attempted would be denied

#### Scenario: A step stops at its session's limit

- **WHEN** an unattended implementation run stops partway through a section because
  its session reached its limit
- **THEN** its edits stay uncommitted, and the resumed session finishes the section
  and commits it
