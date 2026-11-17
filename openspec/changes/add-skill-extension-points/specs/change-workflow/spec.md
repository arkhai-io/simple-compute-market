## ADDED Requirements

### Requirement: CW-d1nj A repository injects into the workflow through its configuration and its guides

An adopting repository's configuration MUST hold every value the engine reads — what
it runs, computes, orders, copies, or checks — and its guides MUST hold only what an
agent is told. A value both need MUST live in the configuration, and a skill MUST
learn it from the engine's structured output, never by reading the configuration's
file.

#### Scenario: A skill needs an evidence kind's pattern

- **WHEN** the plan skill needs to know which evidence kinds may be owed
- **THEN** it reads them from `config --json`, and no guide restates them

### Requirement: CW-g2rs A guide restates nothing the configuration holds

An evidence kind's guide MUST NOT restate a value its configuration entry holds, such
as its commands, its evidence pattern, its requirement, or what it follows; review
holds it to this.

#### Scenario: A guide repeats its command

- **WHEN** a guide's prose names the command its kind runs
- **THEN** a review of the change that wrote it raises the duplication

### Requirement: CW-k7gd An evidence kind has a guide the steps read

Each evidence kind the configuration declares MAY name a guide: Markdown, prose
only, saying how to read the kind's evidence, how its failures are told apart, what
its section of the validation record adds, what its cleanup writes, and what a
section's verification names for it. Validation, planning, implementation, the
merge, archive cleanup, and the reviews reading a validation record MUST read the
guides of the kinds they handle.

#### Scenario: The merge meets a file a cleanup writes

- **WHEN** a merge conflicts over a tracked file a kind's cleanup writes
- **THEN** the merge resolves it as that kind's guide says

### Requirement: CW-c5nt A skill names a contradiction it notices and follows its own text

A guide or a hook's message MAY add to or narrow what a skill says. The workflow MUST
NOT be taken to defend its obligations against the adopting repository's own
extensions. A skill that notices a guide or message contradicting its own text MUST
say so in its report and MUST follow its own text.

#### Scenario: A guide is stale

- **WHEN** a guide tells validation to write a record section the skill no longer
  defines
- **THEN** the validation's report names the contradiction and the record follows
  the skill

### Requirement: CW-n8tr The workflow's skills name no repository's targets or paths

A make target or repository path a workflow skill names MUST be the workflow's own —
its guidance, OpenSpec's tree, the change index, the make fragment's targets, or the
engine's command — or one listed as an exemption owned by the change that removes
it. A test MUST fail on any other, naming the skill.

#### Scenario: A skill names a repository's check

- **WHEN** a skill is edited to run `make check-comment-hygiene`
- **THEN** the test fails, naming the target and the skill, and the skill names the
  repository's comment check by its role

### Requirement: CW-t3ev Evidence describes a tree

Evidence MUST describe the Git tree it was gathered against: `git write-tree` of the
worktree as tested, its changes added to a temporary index that honours `.gitignore`.
It MUST be reused for any commit whose tree is that tree. Where the engine computes
the tree — through `{tree}` or its own gathering — the identity is the engine's;
evidence written otherwise names its tree on its writer's word.

#### Scenario: Implementation's checks stand for validation's

- **WHEN** implementation's functional checks leave `local` evidence for the tree it
  then commits
- **THEN** validation of that commit finds `local` present and does not gather it

### Requirement: CW-g1gn What the workflow writes after implementation is ignored by Git

Every file a change's validation, its gathering, or a step hook writes after
implementation MUST be ignored by Git, so that it never changes the tree its evidence
describes. The configuration's check MUST refuse an evidence pattern whose fixed
directory Git does not ignore.

#### Scenario: An evidence pattern under a tracked directory

- **WHEN** a kind declares `evidence = "reports/{tree}/*.json"` and `reports/` is not
  ignored
- **THEN** every reader of the configuration refuses, naming the kind's `evidence`

### Requirement: CW-p4rs Evidence counts by its presence

Evidence MUST count by being present at its kind's pattern for the tree, whoever
wrote it: a step, the engine, or whatever placed it from beyond the checkout. The
workflow MUST NOT fetch evidence from beyond the checkout.

#### Scenario: Evidence from an external topology

- **WHEN** a run of tests needing a topology no checkout holds is placed at the
  pipeline kind's pattern for the tree
- **THEN** `evidence` reports the pipeline kind present, and validation assesses it

### Requirement: CW-r5qk An evidence kind is required always or when owed

Each evidence kind MUST be declared required `always` or when `owed`. An owed kind is
required once for each argument a complete section's `Owed by validation (<kind>
<argument>):` line names. A line naming no kind MUST be read as the one owed kind,
and refused when there is more than one. A waiver MUST name kinds.

#### Scenario: A section owes the pipeline

- **WHEN** a repository declares `pipeline` as owed and a complete section has
  `Owed by validation (pipeline): scenario test_spot_deal_settles passes`
- **THEN** `evidence` lists the pipeline kind as required for that section

### Requirement: CW-e2vd The engine reports which required evidence is present

`evidence <change>`, and its `--json`, MUST list for `HEAD`'s tree each required
kind, its pattern, and the evidence matching it, as present, missing, waived with
the decision's `seq`, or not required.

#### Scenario: Only local evidence exists

- **WHEN** `local` evidence exists for `HEAD`'s tree and no other kind's does
- **THEN** `evidence` lists `local` present with its path and every other required
  kind missing

### Requirement: CW-a8ss Validation gathers what is missing and assesses all of it

Validation MUST gather each missing required kind and assess every required kind's
evidence from its guide. Present failing evidence MUST be diagnosed, never gathered
again for a pass; unreadable evidence MAY be gathered again, saying why. The record
MUST name the tree and each kind's result and source, `present` or `gathered`.

#### Scenario: Present evidence failed

- **WHEN** `local` evidence present for the tree records a failing suite
- **THEN** validation diagnoses the failure from it and does not run `local` again

### Requirement: CW-g6th The engine gathers missing evidence before validation's session

Before validation's session starts, the engine MUST run the preflight, push `HEAD`
through the guarded push, start every missing `start` kind, run the missing `run`
kinds in order, keeping each `after`, then collect each started kind. A gathering's
failure MUST NOT prevent the session. A waived kind MUST be skipped unless a merge
since it last ran lapses the waiver.

#### Scenario: The local suite fails during gathering

- **WHEN** the gathering's `local` kind fails
- **THEN** the session starts with that failure in its inputs and diagnoses it

### Requirement: CW-h3ks Each step has a hook before and after it

A repository MAY declare `before-<step>` and `after-<step>` for each step a run is
logged as; review and triage hooks receive `{kind}`. An absent or empty hook MUST run
nothing, with no default, and the orchestrating session MUST say in one sentence that
it ran the step without it. Interactively, the skill MUST run them through `run
before|after <step> <change>`.

#### Scenario: No hook is declared before a review

- **WHEN** a review starts and the configuration declares no `before-review`
- **THEN** the review runs, and the orchestrating session says no `before-review`
  hook was declared

### Requirement: CW-b7fl A failing hook before a step informs its session

A `before-<step>` hook that fails MUST NOT prevent the step's session: its closing
line and log MUST be in the session's inputs, and the step's skill MUST say what the
failure means for its work. A hook the configuration's check refuses MUST refuse the
step.

#### Scenario: An environment refresh fails before implementation

- **WHEN** `before-implement` fails
- **THEN** the implementation session starts, reads the failure from its inputs, and
  stops to ask the owner rather than code in a broken environment

### Requirement: CW-a4fl A failing hook after a step resumes its session once

An `after-<step>` hook MUST run only after a `finished` outcome, before that outcome
is logged as final. When it fails, the wrapper MUST resume the same session once
with the failure; when it fails again, the run MUST end as a question to the owner
naming the hook.

#### Scenario: A hook after implementation finds a lint failure

- **WHEN** `after-implement` fails after an implementation finishes
- **THEN** the implementation session resumes with the failure, fixes and commits it,
  ends finished again, and the hook passes

### Requirement: CW-i9np A run's inputs reach its session through a directory

Each run MUST have an inputs directory under its change's records, given to its hooks
as `{inputs}` and named on its log line. The engine MUST write `status.md` and keep
each hook's output as a log there. Every top-level Markdown file a hook writes MUST
be read in full as the session loads; any other file is data, read where a message
directs.

#### Scenario: A hook passes a large artifact

- **WHEN** `before-review` writes `message.md` and a multi-megabyte
  `diff-summary.json` into `{inputs}`
- **THEN** the review reads `message.md` in full and reads the JSON only where the
  message directs

## MODIFIED Requirements

### Requirement: CW-zkhs Validation's parts are the repository's

Validation MUST assess the evidence kinds the repository's configuration declares
but those the owner waived (CW-e7lm), and each kind's evidence MUST describe the tree
under validation (CW-t3ev), never another tree's build, run, or state, whoever wrote
it (CW-p4rs).

#### Scenario: A part finds only another commit's evidence

- **WHEN** evidence of a kind exists only for an earlier commit's tree
- **THEN** it is not evidence of the validated commit, and the kind is missing

### Requirement: CW-e7lm Validation's result is passed, failed, or inconclusive

A validation's result MUST be `passed`; `failed`, for a failure caused by the commit
or of unknown cause; or `inconclusive`, when no failure is caused by the commit but
a kind has no evidence for an environmental reason. Any kind MAY be waived, and
only by the owner. A waived kind MUST be recorded as `waived`: an omission of
evidence, neither passed, failed, nor inconclusive, counted in no result, which is
judged on the kinds assessed; a requirement that validation gather a kind, dispatch
its workflows, or judge its evidence applies only to the kinds not waived. A
validation with every kind waived MUST NOT be recorded: waiving validation entirely
is the owner's direction past the guard it remedies. A waiver for later validations
MUST be the owner's decision in the change's workflow log, naming the kinds and the
condition they are waived on; validation MUST read it before assessing any kind, and
MUST gather a waived kind, saying in the record that the waiver lapsed and why, when
the condition does not hold over the commits since the last validation that assessed
that kind, or when those commits include a merge.

#### Scenario: A part produces no evidence for an environmental reason

- **WHEN** no failure is caused by the commit, and one kind has no evidence because
  its environment was unavailable
- **THEN** the result is `inconclusive`, neither `passed` nor `failed`

#### Scenario: Parts are waived for the rest of the change

- **WHEN** the change's log holds the owner's decision waiving the Helm and pipeline
  kinds on a condition that holds over the commits since those kinds were last
  assessed
- **THEN** validation gathers neither, records both as `waived` naming the decision,
  and judges the result on the local and CI kinds

#### Scenario: A standing waiver lapses at a merge

- **WHEN** the commits since the pipeline kind was last assessed include a merge
- **THEN** the pipeline kind is gathered despite the owner's waiver of it, and the
  record says the waiver lapsed at the merge

#### Scenario: The owner waives an environmental failure

- **WHEN** a kind fails for an environmental reason and the owner waives it rather
  than remedy it
- **THEN** the kind is recorded as `waived`, and the result is judged on the other
  kinds rather than being `inconclusive` for it

### Requirement: CW-g4oz Validation runs the parts the configuration declares

The configuration MUST declare each evidence kind under `[validation.evidence.<kind>]`
with its requirement, its pattern holding `{tree}`, and `run` or `start` then
`collect`, and MAY declare `after`, `cleanup`, and `guide`. The engine MUST gather
started kinds before `run` kinds, each after the kind its `after` names, and refuse an
`after` naming no declared kind or forming a cycle.

#### Scenario: Two sections owe CI workflows

- **WHEN** one complete section owes `(ci ci.yml)` and another `(ci docker.yml)`
- **THEN** `evidence` lists the `ci` kind twice, as `ci ci.yml` and `ci docker.yml`,
  and the gathering starts and collects each by that name

#### Scenario: A long part is declared before a dispatched one

- **WHEN** the configuration declares `local`, a `run` kind, before `pipeline`, a
  `start` and `collect` kind, and neither names an `after`
- **THEN** the gathering starts `pipeline` before it runs `local`

#### Scenario: A repository has no Helm part

- **WHEN** a repository declares only a `local` kind
- **THEN** validation assesses that kind alone, and its record names no other

#### Scenario: No section owes CI evidence

- **WHEN** a kind is declared `owed` and no complete section owes it
- **THEN** it is not gathered, and the record says it is not owed

### Requirement: CW-x9bt The engine keeps a started part's marker and closes each part

A declared command MUST promise only its exit status and, for a `start`, a last
line of standard output naming the marker its `collect` waits past. The engine MUST
keep that marker for the tree, the kind, and an owed kind's argument, a later `start`
of the same key replacing it, MUST fill `{after}` from it, and MUST end each kind's
gathering with a closing line naming the kind, its argument, the tree, the result,
the exit status, and the evidence.

#### Scenario: Two owed runs are collected side by side

- **WHEN** the gathering starts `ci` for `ci.yml`, which prints `401`, then for
  `docker.yml`, which prints `402`, and collects both
- **THEN** the collect of `ci.yml` waits past `401` and the collect of `docker.yml`
  past `402`

#### Scenario: The pipeline is collected

- **WHEN** a kind's `start` printed `40733870392` last, and the gathering then runs
  its `collect`
- **THEN** the engine fills `{after}` with `40733870392`, with no marker passed by
  a skill

### Requirement: CW-ikmm Archive cleanup removes a change's validation resources

Before archive cleanup's session starts, the engine MUST run the `cleanup` of every
evidence kind that declares one, in declaration order as one list (CW-k9vd), and each
cleanup MUST succeed when it finds nothing to clean. `run cleanup <change>` MUST run
the same list again. A tracked file a cleanup writes MUST be committed on its own.

#### Scenario: A change's validation left resources

- **WHEN** archive cleanup starts for a change whose Helm kind left a namespace
- **THEN** the engine runs that kind's cleanup first, and the session reports what it
  removed

#### Scenario: A part's cleanup finds nothing

- **WHEN** the engine runs a kind's cleanup for a change that kind never validated
- **THEN** the cleanup succeeds, removing nothing

### Requirement: CW-b2xr The workflow's hooks are named by when they run

A repository's commands MUST be declared as hooks named by the moment they run:
`after-functional-change`, after a step's last functional change and before its
pre-commit hooks; `pre-commit`, before every commit; `pre-commit-functional`, before
a commit with a functional change; `pre-archive`, before closeout's archive;
`pre-push`, before the guarded push sends; `post-clone`, as a clone is made; and
`before-<step>` and `after-<step>`, around each step's session (CW-h3ks).

#### Scenario: A merge resolves a conflicted lock

- **WHEN** the merge takes one side of a conflicted lock file
- **THEN** it runs `after-functional-change` before its pre-commit hooks, which
  rebuilds the lock in a repository that declares relocking there

### Requirement: CW-v2dq A command receives its values through placeholders

A declared command MUST receive the workflow's values as shell-quoted placeholders,
run with `sh -c` from the repository's root: `{change}`, `{base}`; `{remote}` in
`pre-push`; `{owed}` in an owed kind; `{after}` in a `collect`; `{tree}` in a kind's
commands and pattern and the functional hooks; `{kind}` in review and triage hooks;
`{inputs}` in step hooks. A value of the owner's machine MUST reach it through the
environment.

#### Scenario: A placeholder is used where it is unavailable

- **WHEN** `pre-commit` names `{remote}`
- **THEN** the configuration's check refuses, naming the field and the placeholder

### Requirement: CW-q5fy Each run's log line records what it invoked

The log line of a run MUST record, as `invoked`, each hook, kind, and command the run
or its gathering invoked through the engine, with its argument and phase where it has
them, the command it resolved to, its exit status, when it started, and how long it
took, and MUST name the run's inputs directory. An invocation outside any session
MUST NOT be recorded; a clone's bootstrap MUST be recorded in its bootstrap state
(CW-8npg).

#### Scenario: A step's push is refused by the pre-push hook

- **WHEN** a validation's gathering pushes and `pre-push` exits 1
- **THEN** the run's log line lists `pre-push` with its resolved command and exit
  status 1

#### Scenario: Validation's Helm part fails

- **WHEN** the gathering's `helm` kind exits 2
- **THEN** the run's log line lists that kind with its resolved command and exit
  status 2, whatever the validation record says

### Requirement: CW-o6kc The configuration's resolution is listed

`config` MUST list every field and how it resolved — declared, default, disabled, or
absent — with the command it resolves to, each evidence kind's guide among them, and
`config --json` MUST give the same as structured output.

#### Scenario: An optional hook is absent

- **WHEN** a repository declares no `pre-archive`
- **THEN** `config` lists `pre-archive` as absent, and closeout skips it, saying so

### Requirement: CW-5h8e Evidence only a push produces is owed by validation

A section's verification MUST name only evidence an implementation session can
produce. Evidence only a push produces MUST be named as owed by validation, by the
evidence kind that produces it (CW-r5qk), and MUST NOT gate a task's completion. A
session that finds such evidence in a verification MUST check the task once its own
evidence passes and name that evidence as owed by validation in the section's notes.

#### Scenario: A section owes CI evidence

- **WHEN** a section's change can be shown only by a run of a CI workflow, which no
  push of the change's branch triggers
- **THEN** the plan names the kind, the workflow, the job, and what it must show as
  owed by validation, and the section's verification task is checked on its local
  evidence alone

#### Scenario: An older plan gates a task on a CI run

- **WHEN** an implementation session's verification task asks for a CI run of the
  pushed branch
- **THEN** the session checks the task once its own evidence passes and names the
  CI run as owed by validation in the section's notes, and the next-step computation
  does not name the section again

### Requirement: CW-m4ps An adopting repository provides the workflow's roles

The workflow MUST describe each field of the configuration, who uses it, and how,
and each role an adopting repository provides outside it. A repository MUST state how
it provides what the configuration does not hold. A test MUST fail on a make target
or repository path the step table or the make fragment names that both the statement
and the configuration's commands omit.

#### Scenario: A skill names a new target

- **WHEN** a skill is edited to run `make check-something`
- **THEN** the test fails, naming the target and the skill, since a skill names no
  repository's target (CW-n8tr), whatever this repository's statement lists

#### Scenario: A role has no provision

- **WHEN** the workflow states a role this repository's statement does not provide
- **THEN** the test fails, naming the role
