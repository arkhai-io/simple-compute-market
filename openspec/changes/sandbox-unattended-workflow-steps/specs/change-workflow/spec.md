## ADDED Requirements

### Requirement: CW-x3pf The engine launches each unattended step inside its sandbox

The engine MUST start every unattended step's harness process inside an OS sandbox
it owns, on Linux bubblewrap, so that the harness's own file tools, its shell, and
every process they start are confined alike. The sandbox MUST leave the network,
the environment but `TMPDIR`, which it sets to its own `/tmp` (CW-m8wq), and every
file the owner can read but those under the host's `/tmp` as they are, and MUST end
the session when the wrapper ends. The workflow's guarantees on what a step writes hold
for the runs the sandbox confines (CW-v5ny).

#### Scenario: A step's file tool writes outside its scope

- **WHEN** an unattended design run's Edit tool writes a file under `src/`
- **THEN** the write fails with a read-only file system error, as a shell write
  there would

#### Scenario: A step uses an ambient credential

- **WHEN** an unattended validation run reads a pipeline's logs with the owner's
  GitHub credential
- **THEN** the sandbox neither withholds the credential nor refuses the network

### Requirement: CW-m8wq Each step writes only its scope

Each step's scope MUST be the paths its sandbox may write: review, in its checkout,
only the engine's record of what a session invoked, `.git/change-invocations/`;
design and planning `openspec/` and `.git/`; implementation, triage, the merge, and
validation the checkout; closeout its inert paths and `.git/`; archive cleanup
`openspec/changes/` and `.git/`. Every step, the review included, MUST also write a
private `/tmp` of its own, owned by the owner and open to no one else, which hides
the host's `/tmp` but for the paths under it its scope names, each mounted at its own
path inside it; and its adapter's state. Every step but the review MUST also write
`~/.cache` and the repository's additions. A file or pattern entry MUST mount each
match's directory.

#### Scenario: Closeout edits a README beside code

- **WHEN** closeout's inert paths include `**/README.md` and a package's README
  sits at the package's root
- **THEN** that package's directory is writable to closeout, and an edit of its code
  stops the run at its checks (CW-q7ub)

#### Scenario: A review tries to write

- **WHEN** an unattended review run writes any file it reviews in the checkout
- **THEN** the write fails, since the review's scope in the checkout is only the
  engine's invocation record

#### Scenario: A review runs the checks before a commit

- **WHEN** an unattended review run on Claude Code runs `scripts/change-workflow run
  pre-commit <change>` for evidence
- **THEN** the engine records what the session invoked under
  `.git/change-invocations/`, and the harness keeps its session state under
  `~/.claude`

#### Scenario: A suite checks its temporary directory's owner

- **WHEN** an unattended implementation run's suite checks that each ancestor of a
  path under `/tmp` is owned by root or the caller and writable by no one else
- **THEN** the check passes, since `/tmp` inside the sandbox is the owner's with no
  group or other access, though the host's `/tmp` shows there as the overflow uid's

#### Scenario: A Codex review writes its final message

- **WHEN** an unattended review run on Codex writes its final message to the drafts
  directory the engine made under the host's temporary directory
- **THEN** the write lands at the same path on the host, since the review's scope
  names that directory, and the engine moves the draft into the transcripts once the
  reviewer has ended

### Requirement: CW-r6kd No step writes the protected paths

The sandbox MUST mount read-only, inside every step's scope, the workflow's
configuration, `.git/config`, the engine's `git` (CW-j4cs), and the paths the
harness's adapter and the repository protect, so no step writes a protected file.
A harness's adapter MUST protect every settings file its harness loads. Each
writable and protected path MUST be mounted where its symlinks lead. A protected
path absent at launch MUST be created first, a settings file in its harness's empty
form, and mounted read-only like any other. A protected path MUST NOT be granted.
The protected path's name is not guarded: renaming a directory holding a protected
mount, or replacing a link to a protected file, inside a writable directory, is a
step working around the sandbox, which its review catches.

#### Scenario: An implementation run edits the configuration

- **WHEN** an unattended implementation run writes `.agents/workflow.toml`
- **THEN** the write fails, and the adapter records the refusal on the run's line

#### Scenario: A step rewires Git's hooks

- **WHEN** an unattended run runs `git config core.hooksPath /tmp/hooks`
- **THEN** Git cannot replace `.git/config`, and the command fails

#### Scenario: A step creates an absent settings file

- **WHEN** a checkout has no `.claude/settings.local.json`, and an unattended
  implementation run on Claude Code writes one
- **THEN** the write fails, since the engine created the file as `{}` before launch
  and mounted it read-only

#### Scenario: A clone's settings file is a link

- **WHEN** a clone's `.claude/settings.local.json` is an absolute link to the owner's
  workspace's file, and an unattended implementation run on Claude Code writes
  through it
- **THEN** the run launches, the write fails with a read-only file system error, and
  the workspace's file and the link are unchanged

#### Scenario: A review on Codex edits Codex's configuration

- **WHEN** an unattended review run on Codex writes `~/.codex/config.toml`
- **THEN** the write fails, though the rest of `~/.codex` is writable as the
  adapter's state

### Requirement: CW-h2zt A repository extends a step's scope in its configuration

A repository MUST add writable paths in `[sandbox]`: `writable.common` for every step
but the review, `writable.<step>` for one step, relative paths from the checkout's
root and `~` the home directory; and protected paths in `protected`, which only add.
The configuration's check MUST refuse a writable path that is or lies under a
protected one, `/tmp` itself, which every step writes as its own (CW-m8wq), a
`writable.review`, and an unknown step. A writable directory
containing a protected path MUST be admitted, the protected path mounted read-only
inside it (CW-r6kd).

#### Scenario: A repository gives design its documents

- **WHEN** the configuration declares `writable.design = ["docs/"]`
- **THEN** design's sandbox writes `docs/`, and planning's does not

#### Scenario: A repository opens a protected path

- **WHEN** the configuration declares `writable.common = [".agents/workflow.toml"]`
- **THEN** every reader of the configuration refuses, naming the field and the
  protected path

#### Scenario: A repository opens a directory holding a protected path

- **WHEN** the configuration declares `writable.design = [".agents/"]`
- **THEN** design's sandbox writes `.agents/`, and `.agents/workflow.toml` stays
  read-only inside it

#### Scenario: A repository opens the host's temporary directory

- **WHEN** the configuration declares `writable.common = ["/tmp"]`
- **THEN** every reader of the configuration refuses, naming the field and `/tmp`

### Requirement: CW-v5ny Where the sandbox cannot run, a step runs unconfined and says so

Before launching an unattended step the engine MUST probe the sandbox. Where it
cannot run, the engine MUST run the step unconfined, warn, and record
`unconfined: true` on the run's line, and the orchestrating session MUST tell the
owner. The checks after the session MUST run either way. An unconfined run is held
by those checks alone: no scope, protected path, or sandbox `git` binds it.

#### Scenario: A machine without bubblewrap

- **WHEN** an unattended triage starts on a machine where `bwrap` is not installed
- **THEN** the triage runs unconfined, its line records `unconfined: true`, the
  orchestrating session tells the owner, and the run's invariants are checked as
  any run's

### Requirement: CW-j4cs No git push but the guarded push's leaves a checkout during an unattended run

The sandbox MUST mount the engine's own `git` read-only over each of the system's Git
executables, the one on `PATH` and the one in Git's exec path. It MUST refuse a
`push` while the unattended-run marker is set and the guarded push's marker is not,
whatever the push's options, MUST record each push it refuses, with its command
line, among the session's invocations, and otherwise MUST run the system's `git`.
The engine MUST leave the checkout's hooks and `core.hooksPath` as they are. An
adapter MAY also refuse `git push` by its harness's command rules. Other routes to
the remote — a real Git called by its own path, the Git host's API, the wire
protocol directly — are a step working around the refusal, outside the threat model
the sandbox serves: the orchestrating session's reading of a finding's run
(CW-5rmh) and the check after the run (CW-q7ub) are what catch them, and the Git
host's authorization what bounds them.

#### Scenario: A step pushes directly

- **WHEN** an unattended implementation run runs `git push origin HEAD:dev`
- **THEN** the sandbox's `git` refuses it, and nothing is pushed

#### Scenario: A step skips the hooks

- **WHEN** an unattended implementation run, its push refused by the repository's
  pre-push hook, runs `git push --no-verify origin HEAD:dev`, or `git -c
  core.hooksPath=/dev/null push origin HEAD:dev`
- **THEN** the sandbox's `git` refuses it, and nothing is pushed

#### Scenario: A refused push reaches the run's record

- **WHEN** an unattended implementation run's `git push --no-verify` is refused by
  the sandbox's `git`, and the run goes on
- **THEN** the run's line carries the refused push among its `refusals`, with its
  command line, whatever harness ran the step

#### Scenario: A step calls Git's exec path

- **WHEN** an unattended implementation run runs `/usr/lib/git-core/git push origin
  HEAD:dev`
- **THEN** the sandbox's `git`, mounted there too, refuses it, and nothing is pushed

#### Scenario: The owner pushes from the workspace

- **WHEN** the owner pushes a branch from the workspace, outside any unattended run
- **THEN** the system's `git` pushes it, running the repository's own hooks, and
  nothing of the engine's is in its way

### Requirement: CW-q7ub The engine checks a run's invariants after its session

After every unattended session, whatever its outcome, the engine MUST check against
the state it recorded at the start: `HEAD` is on the change's branch and descends
from the start commit; for validation and review, `HEAD` and every tracked file are
unchanged; the workflow log and the ledger were only appended to; each review record
is unchanged; `refs/stash` is unchanged; the remote moved only by the guarded push,
the change's branch at the last successful guarded push its record names or
unchanged (CW-59c7); and, for closeout, every path changed since the start, committed or not, is one
closeout may change (CW-pkug).

#### Scenario: A step amends an earlier commit

- **WHEN** an unattended implementation run amends a commit it did not make in this
  run
- **THEN** the check finds that `HEAD` does not descend from the start commit

#### Scenario: A review appends to the log during a validation

- **WHEN** a review's line is appended to the log while a validation of the same
  change runs
- **THEN** the validation's check finds the log only appended to, and passes

#### Scenario: A push reaches a protected branch

- **WHEN** a commit made during an unattended run is on the remote's `dev` after it
- **THEN** the check finds the remote moved other than by the guarded push

#### Scenario: Closeout edits code beside a README

- **WHEN** an unattended closeout run, whose scope mounts a package's directory for
  its README, commits an edit of that package's code
- **THEN** the check finds a path closeout may not change, and the run is logged
  stopped naming it

### Requirement: CW-f9le An invariant violation stops the run

A run whose checks find a violation MUST be logged `stopped`, its reason and an
`invariants` field naming each violation, the step's own message kept ahead. No
action or hook after the session MUST run, and nothing MUST be repaired.

#### Scenario: Validation edits a source file

- **WHEN** an unattended validation run finished passed and left a tracked file
  changed
- **THEN** the run is logged `stopped`, its `invariants` naming the file, its message
  keeping the validation's report, and the after-hooks do not run

### Requirement: CW-w3oa A run's refusals come from its own events

The harness's adapter MUST read the run's events for writes the sandbox refused — a
read-only file system, or a protected file busy — and the wrapper MUST record each,
with its tool, command or path, and error, as `refusals` on the run's line. The
wrapper MUST also record there each push the sandbox's `git` refused, from the
engine's own record of it (CW-j4cs). A step MUST treat such an error as outside its
scope.

#### Scenario: A check writes a cache during design

- **WHEN** an unattended design run's check fails creating a directory under a
  package with a read-only file system error, and the design goes on
- **THEN** the run's line records the refusal with the command and the path, and the
  design's message says what it did without it

### Requirement: CW-k8dn The engine creates a prerequisite's worktree

`propose <change> <prerequisite>` MUST create the worktree `../<prerequisite>-proposal`
on a new branch `propose-<prerequisite>` from the change's landing branch as its
remote holds it, without tracking, refusing one that exists. The sandbox of a
design run of that change MUST make each such worktree registered in its checkout
writable.

#### Scenario: A design needs a prerequisite

- **WHEN** an unattended design ends with a question naming a prerequisite, and the
  orchestrating session runs `propose` on the owner's word
- **THEN** the worktree exists on its new branch, and the resumed design session
  writes the prerequisite's proposal there

### Requirement: CW-t6mb A harness's adapter states what the engine needs of it

Each harness MUST have an adapter stating its unattended launch inside the sandbox
with its own prompts off, the state paths it writes, the paths it protects, how it
reads refusals and denials from its events, the steps it can run, and any command
rules it adds. The engine MUST reach a harness only through its adapter.

#### Scenario: Codex runs a review

- **WHEN** a review runs on Codex
- **THEN** the engine launches it through Codex's adapter inside the review's scope,
  with `~/.codex` writable but its `config.toml`, the checkout read-only but the
  engine's invocation record, and Codex's own read-only sandbox inside it

### Requirement: CW-g5ry Interactive runs are not confined

An interactive run MUST NOT be launched inside a step's sandbox, and its invariants
MUST NOT be checked: the owner's own settings and prompts apply.

#### Scenario: The owner runs a design interactively

- **WHEN** the owner opens a design session through the make target without
  `UNATTENDED=1`
- **THEN** the session runs under the owner's own settings, unconfined

### Requirement: CW-p3vz No unattended step opens or ends a round view

`round-view` and `round-done` MUST refuse while an unattended run's marker is set,
naming the run's step, and move nothing: the round view is the owner's.

#### Scenario: A step opens a round view

- **WHEN** an unattended triage runs `scripts/change-workflow round-view <change>`
- **THEN** the command refuses, naming the triage step, and moves nothing

## RENAMED Requirements

- FROM: `### Requirement: CW-qu42 An unattended run is limited to its step's table`
- TO: `### Requirement: CW-qu42 An unattended run is limited to its step's scope`
- FROM: `### Requirement: CW-4yhk A denied run stops, or goes on only by allowed calls`
- TO: `### Requirement: CW-4yhk A refused run stops, or goes on within its scope`
- FROM: `### Requirement: CW-k5mk A run's denials come from its own record`
- TO: `### Requirement: CW-k5mk A run's denials and refusals come from its own record`
- FROM: `### Requirement: CW-svng The orchestrating session reads and classifies each denial`
- TO: `### Requirement: CW-svng The orchestrating session reads and classifies each refusal`
- FROM: `### Requirement: CW-5rmh The orchestrating session checks a deny rule's denial for a workaround`
- TO: `### Requirement: CW-5rmh The orchestrating session checks a finding's run for a workaround`
- FROM: `### Requirement: CW-vdqj The orchestrating session proposes a rule for each gap and records its reading`
- TO: `### Requirement: CW-vdqj The orchestrating session proposes a path for each gap and records its reading`
- FROM: `### Requirement: CW-jqi7 A waiting outcome is settled after its denials are read`
- TO: `### Requirement: CW-jqi7 A waiting outcome is settled after its refusals and denials are read`
- FROM: `### Requirement: CW-drf6 A step's permissions change only on the owner's word`
- TO: `### Requirement: CW-drf6 A step's scope changes only on the owner's word`
- FROM: `### Requirement: CW-b5cf An unattended step's calls take the forms its rules match`
- TO: `### Requirement: CW-b5cf An unattended step waits on a background command through wait`
- FROM: `### Requirement: CW-hak6 Archive cleanup copies a change's history into the workspace`
- TO: `### Requirement: CW-hak6 Archive cleanup's history is copied into the workspace`

## MODIFIED Requirements

### Requirement: CW-qu42 An unattended run is limited to its step's scope

An unattended run MUST be limited to its step's scope (CW-m8wq) and MUST NOT push
other than through the guarded push of the change's branch. A step MUST NOT reset,
check out, switch, rebase, stash, or clean.

#### Scenario: A step commits its work

- **WHEN** an unattended implementation run commits a section
- **THEN** it pushes that commit through the guarded push of the change's branch, and
  any other `git push` it attempted would be refused (CW-j4cs)

### Requirement: CW-4yhk A refused run stops, or goes on within its scope

A run that cannot go on without a refused write or a denied call MUST end with a
stopped outcome naming it, rather than asking a question or working around it; a run
that goes on MUST do so within its scope.

#### Scenario: Validation attempts to relock

- **WHEN** an unattended validation run regenerates a lockfile
- **THEN** the run's invariants find a tracked file changed, and the run is logged
  stopped naming it

#### Scenario: Design cannot write what it needs

- **WHEN** an unattended design run needs a write its scope refuses
- **THEN** it ends stopped, naming the path refused

### Requirement: CW-k5mk A run's denials and refusals come from its own record

Every unattended run's outcome MUST carry the denials the run recorded, taken from
the run's own record of denied tools over every turn, each with the harness's reason
where it gives one, and its line MUST carry the refusals its adapter read from its
events (CW-w3oa).

#### Scenario: A step's message omits a denial

- **WHEN** a run was denied a call in an earlier turn, and its final message names
  no denial
- **THEN** its outcome carries that denial from the run's record, with the
  harness's reason

#### Scenario: A step's message omits a refusal

- **WHEN** a run's write was refused in an earlier turn, and its final message names
  no refusal
- **THEN** its line carries that refusal from the run's events

### Requirement: CW-svng The orchestrating session reads and classifies each refusal

The orchestrating session MUST read each recorded refusal and denial from the run's
record, never from the step's message, and classify each as the step reaching beyond
its job, a finding for the owner, or its scope too narrow for the work, a gap.

#### Scenario: A denial carries no reason

- **WHEN** a run's record holds a denial for which the harness gave no reason
- **THEN** the orchestrating session classifies it from the call and the step's job,
  as a finding or a gap

#### Scenario: A refusal of a cache

- **WHEN** a run's line records a refusal of a build cache inside the checkout
  during planning
- **THEN** the orchestrating session reads it as a gap in planning's scope

### Requirement: CW-5rmh The orchestrating session checks a finding's run for a workaround

After a refusal or a denial read as the step reaching beyond its job, the
orchestrating session MUST check the run's later calls for the same work done
another way, and report it to the owner.

#### Scenario: A run does a forbidden action another way

- **WHEN** a run refused a write of a protected file later writes the same content
  through a copy it renames
- **THEN** the orchestrating session finds the workaround in the run's later calls
  and reports it to the owner

### Requirement: CW-vdqj The orchestrating session proposes a path for each gap and records its reading

For a gap, the orchestrating session MUST propose the narrowest writable path that
covers the refused write, read from the step's resolved scope, and say whether it
is a one-run grant or a tracked edit of the configuration, and MUST record its
reading in the workflow log as a decision reading that run, before the next step
runs.

#### Scenario: A step is denied a command no rule names

- **WHEN** an unattended run's command is refused a write under `kit/site/.venv`,
  which no path of its scope names
- **THEN** the orchestrating session proposes that path, and the owner grants it for
  the resumed run or has it added to the configuration's `[sandbox]`

### Requirement: CW-jqi7 A waiting outcome is settled after its refusals and denials are read

A run whose outcome still waits, such as a question or a proposed return, MUST be
answered or decided after its refusals and denials are read, and the reading MUST
NOT settle that outcome. The next-step computation MUST treat a line carrying either
alike.

#### Scenario: A question carries denials

- **WHEN** an unattended validation was denied a command it could do without, went
  on, and ended with a question
- **THEN** the next-step computation names the owner for the reading of the denial
  first, carrying it; once a decision reads that run, the question waits for its
  answer, and the same session resumes with it

#### Scenario: A question carries refusals

- **WHEN** an unattended validation was refused a write it could do without, went
  on, and ended with a question
- **THEN** the next-step computation names the owner for the reading of the refusal
  first; once a decision reads that run, the question waits for its answer, and the
  same session resumes with it

### Requirement: CW-drf6 A step's scope changes only on the owner's word

A change to a step's scope MUST be made by the owner, or on the owner's word by the
orchestrating session, as a tracked edit of the configuration, or granted by the
owner for one run, fresh or resumed. A protected path, and a call an adapter's
command rule denies, MUST NOT be granted.

#### Scenario: A deny rule's denial is asked to be granted

- **WHEN** the owner asks to grant, for one run, a `git push` the harness's adapter
  denies by its command rule
- **THEN** no grant is made; the guarded push is the only push a step makes

#### Scenario: A protected path is asked to be granted

- **WHEN** the owner asks to grant, for one run, a write of `.agents/workflow.toml`
- **THEN** the engine refuses the grant, naming the protected path

### Requirement: CW-tl5v A grant holds for one run

A grant MUST be a writable path passed on that run's command line, `--write <path>`,
for a fresh run through `start` or a resumed one through `resume`, recorded as
`writes_granted` on the run's log line, and never kept, so the step's next run is
held to its scope again. Each value MUST be split on `;`, each part trimmed and empty
parts dropped, and each path resolved as a `[sandbox]` entry is (CW-h2zt). A grant
MUST name a path: the engine MUST refuse a value with a glob character, a path that
is or lies under a protected path, and `/tmp` itself, naming the value, before it
launches anything. A directory containing a protected path MUST be granted, the protected
path staying read-only inside it. A file MUST mount its directory, and a path absent
at launch MUST be created as a directory before it is mounted.

#### Scenario: The owner grants rules before a fresh run

- **WHEN** the owner grants two paths for a step's next run, which has not started
- **THEN** the orchestrating session starts the run as `scripts/change-workflow start
  <step> <change> --unattended --write <path> --write <path>`, its line records both
  as `writes_granted`, and the step's run after it is held to its scope alone

#### Scenario: The owner grants a path to a stopped run

- **WHEN** a run stopped naming a refused write under `kit/site/.venv`, and the owner
  grants that path for its resumption
- **THEN** the orchestrating session resumes it as `scripts/change-workflow resume
  <change> --seq <its line> --answer <the owner's words> --write kit/site/.venv`, the
  path resolved from the checkout's
  root and created if absent, and the resumed run's line records it as
  `writes_granted`

#### Scenario: A grant names a pattern

- **WHEN** a run is started with `--write 'kit/*/.venv'`
- **THEN** the engine refuses it, naming the value, and launches nothing

#### Scenario: A grant names the host's temporary directory

- **WHEN** a run is started with `--write /tmp`
- **THEN** the engine refuses it, naming the value, and launches nothing, since the
  step writes a private `/tmp` already

### Requirement: CW-b5cf An unattended step waits on a background command through wait

An unattended step MUST wait on a background command through the command's `wait`,
never by following the command's output.

#### Scenario: A step waits on a background suite

- **WHEN** an unattended implementation runs the suites in the background
- **THEN** it waits with `wait` on the output file for the line the suites print when
  they end, never with a following read of the file

### Requirement: CW-z5me No step edits the configuration

No unattended step MAY edit `.agents/workflow.toml`, which its sandbox mounts
read-only (CW-r6kd); it MUST change only as a tracked edit by the owner, or by the
orchestrating session on the owner's word, so that no step changes what its own
hooks run.

#### Scenario: An implementation run edits the configuration

- **WHEN** an unattended implementation run tries to write `.agents/workflow.toml`
- **THEN** the write fails and its refusal is recorded on the run's line

### Requirement: CW-zq4h The step models' policy

A step's models MUST NOT list two models of one vendor, and a model MUST appear only
for a step its harness's adapter can run. The engine MUST refuse configured models
that break these rules, naming the step.

#### Scenario: A row names two models of one vendor

- **WHEN** the configuration names two Claude models for one step
- **THEN** the engine refuses the configuration, naming the step

#### Scenario: A harness whose adapter runs only reviews

- **WHEN** the configuration names a Codex model for implementation, and Codex's
  adapter runs only the review
- **THEN** the engine refuses the configuration, naming implementation

### Requirement: CW-hak6 Archive cleanup's history is copied into the workspace

Once archive cleanup's session finishes, before its outcome is logged, the engine
MUST copy the change's records, and the validation evidence they name, into the
owner's workspace at the same paths; once that outcome is logged, the orchestrating
session MUST repeat the copy, so the workspace holds it too.

#### Scenario: Records grow after archive cleanup copied them

- **WHEN** archive cleanup's outcome is appended to the clone's workflow log after
  the engine's copy, and another round on the pull request writes a record in the
  clone
- **THEN** the next copy, or clone removal's own, extends the workspace's log and
  adds the record, overwriting nothing

### Requirement: CW-dtpz A design blocked on a prerequisite ends blocked

When a design cannot proceed without another change, the design step MUST, with the
owner, define the prerequisite's requirements and initial proposal, have its
worktree made by `propose` (CW-k8dn), write them there, and end blocked. The
proposal MUST reach the development branch before the prerequisite's workflow
starts; the blocked change's branch MUST receive it only by merging that branch.

#### Scenario: A design needs another change first

- **WHEN** a design discussion finds it cannot proceed until another change lands
- **THEN** the design asks for the prerequisite's worktree, writes the
  prerequisite's proposal and index row there once `propose` made it, and ends with a
  blocked outcome naming the prerequisite

### Requirement: CW-o6kc The configuration's resolution is listed

`config` MUST list every field and how it resolved — declared, default, disabled, or
absent — with the command it resolves to, each evidence kind's guide among them, and
each step's resolved scope: its writable and protected paths, each named by its
source, the engine, the adapter, or the repository. `config --json` MUST give the
same as structured output.

#### Scenario: An optional hook is absent

- **WHEN** a repository declares no `pre-archive`
- **THEN** `config` lists `pre-archive` as absent, and closeout skips it, saying so

#### Scenario: The orchestrating session reads a step's scope

- **WHEN** the orchestrating session reads planning's scope from `config --json`
- **THEN** it finds `openspec/` and `.git/` from the engine, the adapter's state
  paths, and `docs/` from the repository

### Requirement: CW-59c7 The guarded push of a change branch

An agent MAY push a change's own branch without separate approval, only after a
check confirms that `HEAD` is attached, the worktree is clean, the branch is none of
the configured protected branches, and its upstream has the same name. The push MUST
send exactly `HEAD` to the upstream's remote, or a remote given as an argument, and
MUST NOT be forced. The check MUST report a refused state and MUST NOT repair it.
Under an unattended run, each push the guarded push attempts MUST be recorded among
the session's invocations once Git returns: its branch, its remote, the commit sent,
and Git's exit status. A push to a given remote of a branch with no upstream MUST
NOT set one, since `.git/config` is protected (CW-r6kd); once the session ends, the
engine MUST set the branch's upstream, outside the sandbox, to the remote of the
run's last successful guarded push of that branch, and MUST set none where no push
of it succeeded.

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

#### Scenario: An unattended run pushes a branch with no upstream

- **WHEN** an unattended design run pushes, through the guarded push with a remote
  given, a branch with no upstream
- **THEN** the push sends `HEAD` without setting an upstream, and once the session
  ends the engine sets the branch's upstream to that remote's branch of its name

#### Scenario: An unattended push fails

- **WHEN** an unattended design run's guarded push of a branch with no upstream
  passes its pre-push hook, and Git then fails to push
- **THEN** the push's record carries Git's failing status, and once the session ends
  the engine sets no upstream

### Requirement: CW-m4ps An adopting repository provides the workflow's roles

The workflow MUST describe each field of the configuration, who uses it, and how,
and each role an adopting repository provides outside it. A repository MUST state how
it provides what the configuration does not hold. A test MUST fail on a make target
or repository path the make fragment names that both the statement and the
configuration's commands omit.

#### Scenario: A skill names a new target

- **WHEN** a skill is edited to run `make check-something`
- **THEN** the test fails, naming the target and the skill, since a skill names no
  repository's target (CW-n8tr), whatever this repository's statement lists

#### Scenario: A role has no provision

- **WHEN** the workflow states a role this repository's statement does not provide
- **THEN** the test fails, naming the role

## REMOVED Requirements

### Requirement: CW-2lvd A deny rule's refusal stands, except a write-steering rule's

**Reason**: No write-steering rule remains: a shell write within a step's scope is no longer refused, and every refusal outside it means the same thing (CW-svng).

**Migration**: CW-svng and CW-5rmh read every refusal as a finding or a gap; the skills drop the substitution paragraph.

### Requirement: CW-2h9t A call no rule allows may be done by an allowed tool

**Reason**: No allow rules remain: within its scope a step may run any command, so no call is refused for want of a rule.

**Migration**: None; a refused write is outside the step's scope, and CW-4yhk governs it.

### Requirement: CW-56zq A file rule names a path from the checkout's root

**Reason**: No file rules remain; the sandbox mounts absolute paths resolved from the checkout as the run starts.

**Migration**: CW-h2zt states how a repository's relative paths resolve.
