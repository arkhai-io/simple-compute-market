## ADDED Requirements

### Requirement: CW-r3ka The engine is reached through one command

Every operation of the workflow's engine MUST be reachable through one command's
subcommands, `scripts/change-workflow`, and a repository MUST reach the engine
only through that command, never by importing its code. The command MUST act on
the Git repository containing its working directory, and MUST refuse, naming the
directory, when run outside one.

#### Scenario: A repository script needs a change's directory

- **WHEN** a repository's closing check needs the directory of a change and
  whether it is archived
- **THEN** it runs `scripts/change-workflow find --json <change>` and reads the
  `directory` and `archived` fields, and imports nothing of the engine

#### Scenario: A step is started interactively without make

- **WHEN** the owner runs `scripts/change-workflow start design <change>` for an
  archived change
- **THEN** the command refuses, naming the archived directory, as the make target
  did

#### Scenario: The command runs in a change's clone

- **WHEN** the command runs in a change's clone
- **THEN** it acts on the clone's repository, not on the owner's workspace

#### Scenario: The command runs outside a repository

- **WHEN** the command runs in a directory no Git repository contains
- **THEN** it refuses, naming the directory, and writes nothing

### Requirement: CW-h8vm Make targets are a convenience outside the surface

The engine MAY ship a make fragment whose targets call its command, for a
repository's `Makefile` to include after setting its own values. The fragment's
targets and variables MUST carry no compatibility promise, and a change to them,
or to a repository's own targets, MUST NOT be counted as a change to the engine's
public interface.

#### Scenario: A repository includes the fragment

- **WHEN** this repository's `Makefile` sets `CHANGE_WORKFLOW_MERGE_FROM := dev`
  and includes `scripts/change_workflow/workflow.mk`
- **THEN** `make merge CHANGE=<change>` starts the merge from `dev` through
  `scripts/change-workflow start merge`

#### Scenario: A fragment target is renamed

- **WHEN** a workflow change renames a target of the make fragment
- **THEN** its proposal records no change to a public interface for it

### Requirement: CW-5qne The engine's interfaces are tiered

Each interface of the engine MUST be classified as public, which an adopting
repository, a person, or a runner may rely on; provisional, public with a named
successor expected; or internal, used only by the engine and its shipped skills.
The command's subcommands, flags, exit statuses, and outputs, and the skills'
names and argument forms, MUST be public unless classified otherwise by name.

#### Scenario: A provisional subcommand is replaced

- **WHEN** the change named as `convert`'s successor removes it
- **THEN** the removal is not an incompatible change, since `convert` is
  provisional

#### Scenario: An internal marker changes

- **WHEN** the engine renames the variable that marks an unattended run in a
  step's environment
- **THEN** no public interface changes, since only the engine reads it

### Requirement: CW-x7jd A change's record set carries one format version

The workflow log's `format` MUST version a change's whole record set: the log's
lines and the outcomes and decisions they embed, the records' layout and names,
the fields the engine parses from records, and the ledger's lines. The `next` and
`find --json` outputs MUST carry the same `format`, and the outcome schema MUST
state it in its `$id`. An engine MUST refuse a record set of a format it does not
read, naming the format.

#### Scenario: A runner reads the next step

- **WHEN** a runner reads the data `scripts/change-workflow next <change>` prints
- **THEN** the output's `format` names the record set's format before any field
  the runner routes on

#### Scenario: An older engine meets a newer log

- **WHEN** an engine reading format 2 finds a log line marked format 3
- **THEN** it refuses the change, naming format 3, and routes on none of its lines

### Requirement: CW-c2tw Compatibility is judged by semantic versioning

An incompatible change to a public interface MUST be counted as a major change, a
compatible one as minor, and one limited to internals as a patch; while the major
version is 0, an incompatible change MUST be counted as minor. A proposal that
changes the workflow MUST name each public interface it changes and whether the
change is compatible.

#### Scenario: A public flag is removed

- **WHEN** a workflow change removes a flag of `start`
- **THEN** its proposal names the flag and the change as incompatible

#### Scenario: An output gains a field

- **WHEN** a workflow change adds an optional field to `next`'s output
- **THEN** its proposal names the output and the change as compatible

### Requirement: CW-9fbu The graph's vocabulary is closed

The graph's node names, review kinds, and target shape MUST be public, and an
adopting repository MUST NOT add to them. A reader of an outcome, a direction, or
a log line that names a node or kind it does not know MUST report it by name and
MUST NOT route on it. The step names and review kinds the engine uses MUST come
from the graph's declaration alone.

#### Scenario: A log names an unknown node

- **WHEN** the next-step computation reads a line whose exit names
  `{"step": "deploy"}`, which its graph does not declare
- **THEN** it names the owner with the unknown node, and routes on no later line

#### Scenario: A review kind is added to the graph

- **WHEN** the graph's declaration gains a review kind
- **THEN** the outcome check and the log's writer accept that kind with no other
  list to update

### Requirement: CW-m4ps An adopting repository provides the workflow's roles

The workflow MUST state each role an adopting repository provides — such as a
command that validates a commit locally, the change index at a known path, the
guidance documents every step reads, and protected branches — with the skills that
use it. An adopting repository MUST state how it provides each role, and a test
MUST fail on a make target or repository path the skills, the step table, or the
make fragment name that the repository's statement does not list.

#### Scenario: A skill names a new target

- **WHEN** a skill is edited to run `make check-something` and this repository's
  statement of its roles does not list that target
- **THEN** the test fails, naming the target and the skill

#### Scenario: A role has no provision

- **WHEN** the workflow states a role this repository's statement does not provide
- **THEN** the test fails, naming the role

### Requirement: CW-w2ld The orchestrating session's model is the step table's

The step table MUST name the orchestrating session's model and effort in a row of
its own, which carries no permission rules, and the orchestrating session MUST be
started on that model and effort.

#### Scenario: The owner starts the orchestrating session

- **WHEN** the owner runs `make orchestrate CHANGE=<change>`
- **THEN** the session starts on the model and effort the step table's
  `[orchestrator]` row names
