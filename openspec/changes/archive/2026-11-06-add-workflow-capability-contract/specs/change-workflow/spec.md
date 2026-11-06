## ADDED Requirements

### Requirement: CW-f3qk One configuration file states what the workflow assumes

The workflow MUST read what it assumes about a repository from one file,
`.agents/workflow.toml`: the commands it runs, the documents its skills load, and
the repository's values. Each field MUST configure one operation of a skill or the
engine, and a value Git or the invocation supplies MUST NOT be a field. Adopters
MUST NOT add tables or keys the workflow does not define.

#### Scenario: A repository protects another branch

- **WHEN** a repository's configuration declares `protected-branches = ["trunk"]`
- **THEN** the guarded push refuses `trunk`, and the engine holds no branch name of
  its own

### Requirement: CW-w8ne The configuration is checked whenever it is read

Every subcommand that reads the configuration MUST check all of it as it loads it,
and MUST refuse, naming the field, on an unknown table or key, a value of the wrong
type, or a placeholder unavailable where it is used. With no file, every field MUST
be read as absent. `check config` MUST run the same check alone.

#### Scenario: A key is misspelled

- **WHEN** the configuration declares `pre-comit` under `[hooks]`
- **THEN** every subcommand reading the file refuses, naming `hooks.pre-comit`, and
  runs nothing

### Requirement: CW-t5hz A missing required field refuses only the steps that need it

A required field — `hooks.pre-commit-functional`, at least one validation part,
`repository.protected-branches`, and the models of each step run unattended and of
the orchestrating session — MUST, when absent, make the engine refuse a step that
needs it before launching it, naming the field. An explicit empty value MUST count
as declared. An absent optional field MUST be skipped, the run's record saying so.

#### Scenario: No functional checks are declared

- **WHEN** `start implement` runs and the configuration has no
  `pre-commit-functional`
- **THEN** it refuses before launching a session, naming the field

#### Scenario: A repository declares no functional checks on purpose

- **WHEN** the configuration declares `pre-commit-functional = []`
- **THEN** implementation starts, and a functional commit runs no functional checks

### Requirement: CW-b2xr The workflow's hooks are named by when they run

A repository's commands MUST be declared as hooks named by the moment they run:
`after-functional-change`, after a step's last functional change and before its
pre-commit hooks; `pre-commit`, before every commit; `pre-commit-functional`, before
a commit with a functional change; `pre-archive`, before closeout's archive;
`pre-push`, before the guarded push sends; `post-clone`, as a clone is made.

#### Scenario: A merge resolves a conflicted lock

- **WHEN** the merge takes one side of a conflicted lock file
- **THEN** it runs `after-functional-change` before its pre-commit hooks, which
  rebuilds the lock in a repository that declares relocking there

### Requirement: CW-k9vd A hook runs every command it lists

A hook MAY declare one command or a list. The engine MUST run every command of a
list in order, whatever an earlier one reported, MUST record each, and MUST report
the hook failed when any command failed.

#### Scenario: Two checks fail

- **WHEN** `pre-commit-functional` lists two commands and both fail
- **THEN** both run, both are recorded with their exit statuses, and the hook fails
  naming both

### Requirement: CW-u4pc The engine holds which steps may run each hook

The engine MUST hold, beside the graph, which steps may run each hook through `run`,
which no repository changes. An unattended run's marker MUST name its step, and `run`
MUST refuse a hook its step is not listed for, naming both; a run with no marker
MUST NOT be restricted. `pre-push` and `post-clone` MUST be run only by the engine's
`push` and `clone`.

#### Scenario: Validation asks for a functional hook

- **WHEN** an unattended validation runs `scripts/change-workflow run
  after-functional-change <change>`
- **THEN** `run` refuses, naming the hook and the validate step, and runs nothing

### Requirement: CW-y6mj A pre-commit hook changes nothing

A `pre-commit` hook, its default checks included, MUST report and MUST NOT change the
worktree, so that a review MAY run it.

#### Scenario: A review runs the pre-commit checks

- **WHEN** an unattended review runs `scripts/change-workflow run pre-commit
  <change>`
- **THEN** the checks run and the worktree is unchanged

### Requirement: CW-n7ra The repository's inert paths

The repository's inert paths, `repository.inert-paths`, MUST name the paths a change
to which alters nothing validation or a code check would prove. The engine MUST read
no inert path of its own; with none declared, no path is inert and only changes'
records are exempt where a requirement exempts them.

#### Scenario: A repository marks images inert

- **WHEN** a repository declares `inert-paths = ["docs/", "assets/"]` and a commit
  after a pre-closeout review changes only `assets/logo.svg`
- **THEN** the computation accepts it without a new validation

### Requirement: CW-e1sg A commit's hooks follow from the paths it changes

Before a commit changing any path outside the inert paths, a step MUST run
`after-functional-change`, then `pre-commit-functional`, then `pre-commit`; before
any other commit, `pre-commit` alone. Only implementation, triage, and the merge make
functional commits. A tracked file a validation part's cleanup writes is the
repository's own record, made by its declared command, which answers for it:
archive cleanup MUST commit it on its own, without the hooks (CW-ikmm).

#### Scenario: A triage fix changes only documents

- **WHEN** a triage's accepted fix changes only paths under the inert paths
- **THEN** the triage runs `pre-commit` alone before committing it

#### Scenario: A cleanup records a figure in a tracked file

- **WHEN** archive cleanup's run of the cleanups rewrites a tracked file outside the
  inert paths
- **THEN** archive cleanup commits that file alone, running no hook before it

### Requirement: CW-c8lw A hook's default checks run unless disabled by name

The workflow's default checks for a hook MUST run before its declared commands,
which add to them; `pre-commit`'s are `index`, `tasks`, `skills`, and the strict
`openspec` validation. A repository MUST turn one off only by naming it, with a
reason, under `defaults.disable`. `check change <change>` MUST run them alone.

#### Scenario: A repository declares its own pre-commit

- **WHEN** the configuration declares `pre-commit = "make lint"` and disables nothing
- **THEN** `run pre-commit` runs the four default checks and then `make lint`

#### Scenario: A default check is turned off

- **WHEN** `defaults.disable` names `skills` with a reason
- **THEN** `run pre-commit` skips the skills check, and `config` lists it disabled
  with the reason

### Requirement: CW-v2dq A command receives its values through placeholders

A declared command MUST receive the workflow's values as placeholders the engine
fills in, shell-quoted, before running it with `sh -c` from the repository's root:
`{change}`, `{base}`, `{remote}` in `pre-push` only, `{owed}` in an owed part only,
filled from `run`'s `--owed <workflow>`, and `{after}` in a `collect` only. `run` MUST
refuse `--owed` for a part not owed, and its absence for an owed part. A value of the
owner's machine MUST reach the command through the environment, not the
configuration.

#### Scenario: A placeholder is used where it is unavailable

- **WHEN** `pre-commit` names `{remote}`
- **THEN** the configuration's check refuses, naming the field and the placeholder

### Requirement: CW-g4oz Validation runs the parts the configuration declares

Validation MUST run the parts the configuration declares but those waived: each
`run` once, or `start` then `collect`; an owed part once per `Owed by validation:`
line of a complete section. It MUST start every started part, in declared order,
before it runs any `run` part, then run the `run` parts in declared order, each after
the part its `after` names. It MUST run
`validation.preflight` first, a failure ending it as environmental, and MUST
diagnose each failure from the part's declared evidence. It MUST learn the parts from
`config parts <change>`, never from the configuration's representation: the
preflight, then each run of a part in declaration order with its shape, the part it
follows, and its evidence, an owed part once per owed workflow, named by its part and
that workflow, or once as not owed when no complete section owes it. Which parts are
waived MUST stay validation's judgement, not the plan's. A part's `after` MUST name a
part declared before it, and a part that is started and collected MUST follow only
another such part, since every dispatch starts before any long part runs; the
configuration's check MUST refuse any other `after`.

#### Scenario: Two sections owe CI workflows

- **WHEN** one complete section owes `ci.yml` and another owes `docker.yml`
- **THEN** `config parts` lists the `ci` part twice, as `ci ci.yml` and `ci
  docker.yml`, and validation starts and collects each by that name

#### Scenario: A long part is declared before a dispatched one

- **WHEN** the configuration declares `local`, a `run` part, before `pipeline`, a
  `start` and `collect` part, and neither names an `after`
- **THEN** `config parts` lists `local` first, and validation starts `pipeline` before
  it runs `local`

#### Scenario: A repository has no Helm part

- **WHEN** a repository declares only a `local` part
- **THEN** validation runs that part alone, and its record names no other

#### Scenario: No section owes CI evidence

- **WHEN** a part is declared `owed` and no complete section has an `Owed by
  validation:` line
- **THEN** the part is not started, and the record says it is not owed

### Requirement: CW-x9bt The engine keeps a started part's marker and closes each part

A declared command MUST promise only its exit status and, for a `start`, a last
line of standard output naming the marker its `collect` waits past. The engine MUST
keep that marker for the commit, the part, and an owed part's workflow, a later
`start` of the same key replacing it, MUST fill `{after}` from it, and MUST end each
part with a closing line naming the part, its owed workflow, the commit, the result,
the exit status, and the evidence.

#### Scenario: Two owed runs are collected side by side

- **WHEN** validation starts `ci` for `ci.yml`, which prints `401`, then for
  `docker.yml`, which prints `402`, and collects both in the background
- **THEN** the collect of `ci.yml` waits past `401` and the collect of `docker.yml`
  past `402`

#### Scenario: The pipeline is collected

- **WHEN** a part's `start` printed `40733870392` last, and validation then runs its
  `collect`
- **THEN** the engine fills `{after}` with `40733870392`, with no marker passed by
  the skill

### Requirement: CW-q5fy Each run's log line records what it invoked

The log line of a run MUST record, as `invoked`, each hook, part, and command the run
invoked through `run` or the guarded push, with its owed workflow and phase where it
has them, the command it resolved to, its exit status, when it started, and how long
it took. An unattended run's line is the wrapper's, an interactive run's the one
`record` writes; an invocation outside any session MUST NOT be recorded. A clone's
bootstrap, which belongs to no step's run, MUST be recorded in its bootstrap state
(CW-8npg).

#### Scenario: A step's push is refused by the pre-push hook

- **WHEN** an unattended validation's guarded push runs `pre-push` and it exits 1
- **THEN** the run's log line lists `pre-push` with its resolved command and exit
  status 1

#### Scenario: Validation's Helm part fails

- **WHEN** an unattended validation's `helm` part exits 2
- **THEN** the run's log line lists that part with its resolved command and exit
  status 2, whatever the validation record says

### Requirement: CW-s3ju The branch a change lands on is recorded where its orchestration began

When the orchestrating session creates a change's clone, the engine MUST record the
branch the workspace had checked out, or the clone's `--from`, as the branch the
change lands on, and `find --json` MUST print it as `base`. An argument MUST override
it for one run. A step needing it, with none recorded or given, MUST refuse.

#### Scenario: Orchestration is run again from another branch

- **WHEN** a change's clone was created from `dev` and the owner later runs the
  orchestrating session with `main` checked out
- **THEN** `find --json` still prints `dev` as `base`

#### Scenario: A change worked in place merges with no base given

- **WHEN** a change worked in place, with no clone, reaches the merge and no branch
  is given
- **THEN** the merge refuses, naming the argument that gives the branch

### Requirement: CW-l7hn A step's documents to load come from the configuration

The documents a step's skill loads MUST be `load.common` and `load.<step>`, printed
together by `config load <step>`; `config load common` MUST print `load.common`
alone, for a session no step runs; and the post-compaction hook MUST have a session
re-read `load.common`.

#### Scenario: Design loads the roadmap

- **WHEN** the configuration lists the roadmap under `load.design`
- **THEN** `config load design` prints the common documents and the roadmap, and
  `config load plan` prints only the common documents

### Requirement: CW-i2we The OpenSpec CLI runs through the configured command

The engine's OpenSpec validation and closeout's archive MUST run the OpenSpec CLI
through `openspec.command`, or `openspec` on the path when none is declared; `openspec
<arguments>` MUST run that command with the arguments given.

#### Scenario: A repository pins the validator

- **WHEN** `openspec.command` is `bunx @fission-ai/openspec@1.14.0`
- **THEN** the default strict validation and `scripts/change-workflow openspec
  archive <change> -y` both run that pinned version

### Requirement: CW-o6kc The configuration's resolution is listed

`config` MUST list every field and how it resolved — declared, default, disabled, or
absent — with the command it resolves to, and `config --json` MUST give the same as
structured output. `config parts <change>`, and its `--json`, MUST list validation's
plan for the change (CW-g4oz).

#### Scenario: An optional hook is absent

- **WHEN** a repository declares no `pre-archive`
- **THEN** `config` lists `pre-archive` as absent, and closeout skips it, saying so

### Requirement: CW-z5me No step edits the configuration

No unattended step MAY edit `.agents/workflow.toml`; it MUST change only as a tracked
edit by the owner, or by the orchestrating session on the owner's word, so that no
step changes what its own hooks run.

#### Scenario: An implementation run edits the configuration

- **WHEN** an unattended implementation run tries to write `.agents/workflow.toml`
- **THEN** the write is denied and recorded on the run's line

## RENAMED Requirements

- FROM: `### Requirement: CW-zq4h The step table's model policy`
- TO: `### Requirement: CW-zq4h The step models' policy`

- FROM: `### Requirement: CW-w2ld The orchestrating session's model is the step table's`
- TO: `### Requirement: CW-w2ld The orchestrating session's model is the configuration's`

- FROM: `### Requirement: CW-p7kq The guarded push runs the repository's pre-push check`
- TO: `### Requirement: CW-p7kq The guarded push runs the repository's pre-push hook`

## MODIFIED Requirements

### Requirement: CW-hdxi The merge brings in the branch the change lands on

Once the pre-closeout review's triage advances the change, a merge step MUST bring
into the change's branch the branch the change lands on (CW-s3ju), or the branch
the owner names instead. It MUST resolve the merge's conflicts and reconcile the
change's own code with what that branch changed, even where the merge reported no
conflict, before closeout starts.

#### Scenario: The branch the change lands on renamed what the change calls

- **WHEN** the branch the change lands on renamed a function the change's code
  calls, and the merge reported no conflict
- **THEN** the merge step updates the change's call before closeout starts

### Requirement: CW-trdu Archive cleanup waits on the closeout review's triage

The archive MUST be cleaned up, and the change set `archived`, only once the
closeout review's triage records that the change advances and, when `HEAD` differs
from the commit that review read outside the inert paths, the latest validation
passed for `HEAD` or for an ancestor it differs from only in records, unless the
owner waives that validation, judging the paths named, and the waiver is recorded in
the intervention ledger.

#### Scenario: The owner waives archive cleanup's validation

- **WHEN** the only path outside the inert paths changed since the closeout review's
  commit is another change's, on a branch the two changes share, and the owner
  judges it harmless
- **THEN** archive cleanup records the waiver as a line of the change's intervention
  ledger and goes on without a validation of `HEAD`

#### Scenario: The owner waives archive cleanup's validation under orchestration

- **WHEN** the next-step computation names validation before archive cleanup and
  the owner tells the orchestrating session they waive it, judging the paths named
- **THEN** the owner's word is recorded in the workflow log as a decision directing
  archive cleanup, the computation names archive cleanup until it has run, and
  archive cleanup's own check finds the direction in the log and records the waiver
  in the ledger, without asking the owner again

#### Scenario: A closeout review finds a code defect

- **WHEN** a closeout review's finding can only be fixed by changing code
- **THEN** the triage makes no code change and stops for the owner, and any
  correction the owner directs in that session is validated before archive cleanup

#### Scenario: A closeout correction awaits validation

- **WHEN** a closeout review's triage named archive cleanup and its correction
  changed a path outside the inert paths since the reviewed commit
- **THEN** the computation names validation of `HEAD`, with archive cleanup as its
  target

#### Scenario: A documentation correction at closeout

- **WHEN** a closeout review's triage named archive cleanup and its correction
  changed only inert paths
- **THEN** the computation names archive cleanup without a validation

### Requirement: CW-j1ab A triage's edits are checked, committed, pushed, and validated

Accepted fixes MUST pass the hooks their commit runs (CW-e1sg) before they are
committed, and the commit MUST be validated again, unless, after a pre-closeout
review, it changes only inert paths. A triage of any kind MUST commit the tracked
edits its dispositions made, with a fix or alone, and push them.

#### Scenario: An implementation triage commits only documents

- **WHEN** an implementation round's triage commits an edit to the change's task
  list after the latest validation passed, with no fix
- **THEN** that commit is validated before the next round or the pre-closeout review

#### Scenario: A pre-closeout triage commits only documents

- **WHEN** a pre-closeout review's triage advances the change with no fix, and
  commits its edits to the change's documents after the latest validation passed,
  and the merge that follows finds the branch the change lands on merged already
- **THEN** closeout starts without the commit being validated again

### Requirement: CW-gqav A pre-closeout review needs a passed validation of HEAD

A pre-closeout review MUST NOT run, and its triage MUST NOT advance the change,
unless the latest validation's result is `passed` and it names `HEAD`, or a commit
from which `HEAD` descends and differs only in changes' intervention ledgers and
review records, except where the owner overrides it. Once its triage has run, a
commit from which `HEAD` differs only in inert paths MUST be accepted in the same
way.

#### Scenario: A ledger line is committed after the validation

- **WHEN** the latest validation passed for a commit, and the only commit since adds
  a line to a change's intervention ledger
- **THEN** a pre-closeout review may run without the commit being validated again

### Requirement: CW-8tdv An unmet exit guard names the step that satisfies it

When a guard on a declared exit is not met, the computation MUST name the step that
satisfies it, carrying the exit as its target, and MUST bring a guard no step can
satisfy to the owner, naming the target and what is missing.

#### Scenario: Triage records another round

- **WHEN** a review's triage named a review of the same kind as its exit, and a
  commit after the commit it reviewed changes more than changes' records — after a
  pre-closeout review, more than inert paths
- **THEN** the computation names validation of that commit with the review as its
  target, for an implementation or pre-closeout review, and then the review; with no
  such commit, it names the review again on the same commit

#### Scenario: An implementation round advances

- **WHEN** an implementation round's triage named the plan's next round, and its
  fixes are committed
- **THEN** the computation names validation of the fix commit, with the next round
  as its target, and once it passes, the next round, without the owner; a triage of
  the last round names the pre-closeout review, reached the same way

### Requirement: CW-tnp6 A round and the merge advance only on a passed validation

An implementation round, and the merge before closeout, MUST advance only on a
`passed` validation naming its final commit, or a commit from which it differs only
in changes' records or, for the merge's advance to closeout, only in inert paths. An
`inconclusive` validation MUST be brought to the owner, and a `failed` validation of
the merged `HEAD` MUST name the merge again, which repairs what it found or asks the
owner.

#### Scenario: A validation of the merged HEAD fails

- **WHEN** the merge named closeout or a pre-closeout review, and the validation of
  the merged `HEAD` failed
- **THEN** the computation names the merge, carrying the exit it named, so the merge
  repairs what the validation found
- **AND** an `inconclusive` validation of the merged `HEAD` names the owner

#### Scenario: A round's validation is inconclusive

- **WHEN** an implementation round's triage named the plan's next round and the fix
  commit's validation is `inconclusive`
- **THEN** the computation names the owner, with the next round as the target, not
  the next round

### Requirement: CW-h8vm Make targets are a convenience outside the surface

The engine MAY ship a make fragment whose targets call its command, for a
repository's `Makefile` to include. The fragment's targets and variables MUST carry
no compatibility promise, and a change to them, or to a repository's own targets,
MUST NOT be counted as a change to the engine's public interface.

#### Scenario: A repository includes the fragment

- **WHEN** a repository's `Makefile` includes `scripts/change_workflow/workflow.mk`
  and the owner runs `make merge CHANGE=<change> FROM=<branch>`
- **THEN** the fragment starts the merge from `<branch>` through
  `scripts/change-workflow start merge`

#### Scenario: A fragment target is renamed

- **WHEN** a workflow change renames a target of the make fragment
- **THEN** its proposal records no change to a public interface for it

### Requirement: CW-zkhs Validation's parts are the repository's

Validation MUST run the parts the repository's configuration declares (CW-g4oz) but
those the owner waived (CW-e7lm), and each part's evidence MUST come from the commit
under validation, never from another commit's build, run, or state.

#### Scenario: A part finds only another commit's evidence

- **WHEN** a validation part finds a finished run of its evidence only for an earlier
  commit of the branch
- **THEN** it does not report that run as evidence of the validated commit

### Requirement: CW-ebmo Each step runs on its ordered models

The configuration MUST name, for each step, the models its unattended runs use, in
order of preference, each with its harness and effort. The wrapper MUST run the first
available model, MUST fall to the next only when one is unavailable (a usage limit,
a missing sign-in, or a missing harness), and MUST record on the run's log line the
model and effort that ran.

#### Scenario: A step's first model is available

- **WHEN** a step's models name a Claude model at high effort and then a Codex model,
  and Claude is available
- **THEN** the run uses the Claude model, and its log line names that model and high
  effort

### Requirement: CW-zq4h The step models' policy

A step's models MUST NOT list two models of one vendor, and a model of another
harness MUST appear only for a step whose limits that harness can enforce. The engine
MUST refuse configured models that break these rules, naming the step.

#### Scenario: A row names two models of one vendor

- **WHEN** the configuration names two Claude models for one step
- **THEN** the engine refuses the configuration, naming the step

### Requirement: CW-w2ld The orchestrating session's model is the configuration's

The configuration MUST name the orchestrating session's model and effort, and the
orchestrating session MUST be started on that model and effort.

#### Scenario: The owner starts the orchestrating session

- **WHEN** the owner runs `scripts/change-workflow start orchestrate <change>`
- **THEN** the session starts on the model and effort the configuration's
  `models.orchestrator` names

### Requirement: CW-59c7 The guarded push of a change branch

An agent MAY push a change's own branch without separate approval, only after a
check confirms that `HEAD` is attached, the worktree is clean, the branch is none of
the configured protected branches, and its upstream has the same name. The push MUST
send exactly `HEAD` to the upstream's remote, or a remote given as an argument, and
MUST NOT be forced. The check MUST report a refused state and MUST NOT repair it.

#### Scenario: The worktree is dirty

- **WHEN** validation is about to push and the worktree has uncommitted changes
- **THEN** the push check fails, nothing is pushed, and nothing is committed or
  discarded to make it pass

#### Scenario: A new change branch is pushed first

- **WHEN** a change's clone was made for a new branch from a landing branch tracking
  `origin`
- **THEN** the clone gave the new branch an upstream of its own name on `origin`, and
  its first push goes there

#### Scenario: A branch with no upstream

- **WHEN** the guarded push runs on a branch with no upstream and no remote is given
- **THEN** it refuses, naming the argument that gives the remote, and pushes nothing

### Requirement: CW-p7kq The guarded push runs the repository's pre-push hook

Where the configuration declares `pre-push`, the guarded push MUST run it before it
pushes and before its check reports success, as Git runs a pre-push hook: one line
naming the branch and `HEAD`, as for a new branch, on its input, and the remote as
`{remote}`. A failing command MUST refuse the push with its reasons.

#### Scenario: The pre-push check refuses

- **WHEN** the guarded push runs and the repository's `pre-push` fails
- **THEN** nothing is pushed, and the hook's reasons are on standard error

#### Scenario: The repository provides no pre-push check

- **WHEN** the guarded push runs in a repository with no `pre-push`
- **THEN** it pushes once its own check passes

### Requirement: CW-8jyb Creating a clone is safe to repeat

Creating a clone MUST be safe to repeat: it MUST finish a clone left incomplete, and
MUST refuse, deleting nothing, a directory that is not a clone of the workspace, has
another branch checked out, or has uncommitted changes. One of the clone's remotes
MUST name the workspace. The clone MUST take its push remote from Git's record in
the workspace — the upstream remote of the workspace's branch of the change, else of
the branch the change lands on — and the landing branch's upstream remote, each
under its workspace name and URL, and its branch MUST track its branch of the same
name on the push remote; the engine MUST name no remote of its own.

#### Scenario: Clone creation was interrupted

- **WHEN** an orchestrating session restarts after creating a change's clone only
  in part
- **THEN** the computation names the clone again, and creating it finishes the
  steps not yet done without recloning or deleting anything

#### Scenario: A workspace with no origin

- **WHEN** the workspace's landing branch tracks `upstream` and the workspace has no
  `origin`
- **THEN** the clone is made, with an `upstream` remote and no `origin`, and its
  branch tracks its own name on `upstream`

#### Scenario: A stale branch of the change's name on another remote

- **WHEN** the workspace's landing branch tracks `upstream`, the workspace has no
  branch of the change, and `origin` holds an old branch of the change's name
- **THEN** the clone's branch starts from the landing branch and tracks `upstream`

### Requirement: CW-8npg A clone's bootstrap gates implementation and validation

A clone's bootstrap, the configuration's `post-clone`, MAY run while design proceeds;
implementation and validation MUST NOT start before it has succeeded, and with no
`post-clone` it succeeds at once. Its state MUST be recorded so that running,
succeeded, and failed are told apart, and a failed bootstrap MUST be brought to the
owner, naming its log, rather than retried by itself. The state MUST record the
command the bootstrap resolved to, beside its log and exit status.

#### Scenario: The bootstrap failed

- **WHEN** a clone's bootstrap ended with a failure, or its process died without
  recording a status
- **THEN** the computation names no implementation or validation, and the failure
  is brought to the owner naming its log; creating the clone again restarts the
  bootstrap

### Requirement: CW-ikmm Archive cleanup removes a change's validation resources

Archive cleanup MUST run the `cleanup` of every validation part that declares one,
through `run cleanup <change>`, which runs them in declaration order as one list
(CW-k9vd), and each cleanup MUST succeed when it finds nothing to clean. A tracked
file a cleanup writes MUST be committed on its own.

#### Scenario: A change's validation left resources

- **WHEN** archive cleanup runs for a change whose Helm part left a namespace
- **THEN** it runs that part's cleanup and reports what it removed

#### Scenario: A part's cleanup finds nothing

- **WHEN** archive cleanup runs a part's cleanup for a change that part never
  validated
- **THEN** the cleanup succeeds, removing nothing

### Requirement: CW-xx5f A clone is removed only once its work is safe

A clone MUST be removed only on the owner's command. The removal MUST first repeat
the copy, and MUST proceed only once the clone's records, and the named evidence it
holds, are in the workspace with identical contents, its branch is merged into the
branch the change lands on (CW-s3ju) on its upstream's remote, and it holds no commit
and no change that remote lacks; named evidence the clone does not hold MUST be named
in the removal's report. A clone with no landing branch recorded MUST be removed only
with the branch given as an argument.

#### Scenario: The owner removes a clone too early

- **WHEN** the owner asks to remove a clone whose branch is not merged, or whose
  records are not all in the workspace
- **THEN** the removal is refused, naming what is missing, and nothing is deleted

#### Scenario: A change landed on another branch

- **WHEN** a change's clone was created from `main`, and its branch is merged into
  `main` on its upstream's remote but not into `dev`
- **THEN** the removal proceeds, its branch counted as merged

#### Scenario: A clone recorded no landing branch

- **WHEN** the owner removes a clone made before the engine recorded a landing
  branch, giving no branch
- **THEN** the removal refuses, naming the argument that gives the branch, and
  nothing is deleted

### Requirement: CW-m4ps An adopting repository provides the workflow's roles

The workflow MUST describe each field of the configuration, who uses it, and how,
and each role an adopting repository provides outside it, with the skills that use
it. A repository MUST state how it provides what the configuration does not hold. A
test MUST fail on a make target or repository path the skills or step table name that
both the statement and the configuration's commands omit.

#### Scenario: A skill names a new target

- **WHEN** a skill is edited to run `make check-something` and this repository's
  statement of its roles does not list that target
- **THEN** the test fails, naming the target and the skill

#### Scenario: A role has no provision

- **WHEN** the workflow states a role this repository's statement does not provide
- **THEN** the test fails, naming the role
