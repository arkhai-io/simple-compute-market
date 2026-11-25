## ADDED Requirements

### Requirement: CW-5kl9 The workflow ships as one versioned distribution

The workflow MUST ship as one distribution carrying one version: the engine, as the
`change-workflow` command; its skills; its guidance; its specification with its index,
companion, and diagrams; the owner's handbook; the outcome schema; and the make
fragment. `change-workflow --version` MUST print the distribution's version.

#### Scenario: The installed version is asked for

- **WHEN** a person runs `change-workflow --version` with the distribution at 0.1.0
  installed
- **THEN** it prints `0.1.0` and reads no repository's configuration

### Requirement: CW-lm42 The workflow's own documents are found beside the engine

The engine MUST find the workflow's own documents — its guidance, its specification,
its handbook, the outcome schema, the graph diagram, and the make fragment — in its
installed distribution, with no field of any configuration naming them. `config
--json` MUST name each installed document by its role under `workflow`:
`specification`, `index`, `companion`, `diagrams`, `guidance`, `handbook`, `schema`,
and `fragment`, and MUST NOT name a directory a caller looks inside for another
document. The skills MUST read the workflow's own documents only through those
fields, MUST cite the workflow's guidance by section name and its specification by
requirement id, and the distribution's own test MUST fail on a cited section or id it
does not hold.

#### Scenario: A skill reads the outcome schema

- **WHEN** a skill needs the outcome schema's path in a repository holding no copy of
  it
- **THEN** it reads `workflow.schema` from `config --json`, which names the installed
  distribution's schema

#### Scenario: A skill follows a requirement id

- **WHEN** a skill relies on `CW-r6kd` in a repository holding no copy of the
  workflow's specification
- **THEN** it reads the requirement in the file `workflow.specification` names, and
  infers no path inside the distribution

#### Scenario: A skill cites a section the guidance lost

- **WHEN** a skill cites the workflow's guidance section "One change per branch" and
  that heading is renamed
- **THEN** the distribution's test fails, naming the skill and the section

### Requirement: CW-f8yy A repository declares the workflow versions it accepts

A repository's committed configuration MUST declare, as `[workflow] version`, the
workflow versions it accepts, as comma-separated version specifiers (`>=`, `<=`, `>`,
`<`, `==`, `!=`, `~=`) over release numbers; the field is required. Every subcommand
that reads the configuration MUST read the range before checking the rest of the
file, and MUST refuse, naming the installed version, the range, and the fix, when the
installed version is outside it. `install` and `--version` MUST NOT be refused for
the range.

#### Scenario: The installed version is too old

- **WHEN** the configuration declares `version = ">=0.5, <0.6"`, holds a table only
  0.5 defines, and 0.4.2 is installed
- **THEN** `config load design` refuses, naming 0.4.2, the range, and installing a
  version in range, and does not report the table as unknown

#### Scenario: No range is declared

- **WHEN** the configuration has no `[workflow] version`
- **THEN** every subcommand that reads it refuses, naming the field

### Requirement: CW-1rhd Installed skills carry the engine's version

`change-workflow install` MUST write the distribution's skills into the user skill
directory of each harness the workflow supports, stamp each with the distribution's
version, and record the names it wrote in a manifest beside them; it MUST remove a
skill its manifest names that the installed version no longer ships, and MUST NOT
touch a skill it did not write: it MUST refuse, naming it and writing nothing, when a
skill of a name it ships is present in a user skill directory and its manifest does
not record it. Every subcommand of an installed engine but `install` and `--version`
MUST refuse when an installed skill's stamp differs from the engine's version, naming
both and `change-workflow install`, and when a supported harness's user skill
directory lacks a skill the version ships or the manifest, naming what is missing and
`change-workflow install`.

#### Scenario: The engine is upgraded without its skills

- **WHEN** the engine is upgraded to 0.4.2 and the installed skills are stamped 0.4.1
- **THEN** `next` refuses, naming 0.4.1, 0.4.2, and `change-workflow install`

#### Scenario: A skill is missing

- **WHEN** Codex's user skill directory lacks `change-plan`, which the installed
  version ships
- **THEN** `next` refuses, naming the skill, the directory, and `change-workflow
  install`

#### Scenario: A skill of the workflow's name is not the installer's

- **WHEN** `install` runs and Claude Code's user skill directory holds a
  `change-design` its manifest does not record
- **THEN** it refuses, naming the skill, and writes nothing

#### Scenario: A later version retires a skill

- **WHEN** `install` runs for a version that no longer ships a skill its manifest
  names, beside a skill the owner wrote themselves
- **THEN** it removes the retired skill and leaves the owner's skill untouched

### Requirement: CW-sv3u The installer writes a checkout's local configuration

`change-workflow install`, run in a checkout, MUST write its local configuration,
`.agents/workflow.local.toml`, where none exists: from the repository's committed
template, `.agents/workflow.local.template.toml`, when one exists, and otherwise as a
skeleton naming each required local field. It MUST NOT overwrite a local
configuration that exists. An empty `.agents/workflow.local.toml`, the form the
sandbox gives an absent protected file, is no local configuration: `install` MUST
write it as it writes an absent one.

#### Scenario: A developer installs in a repository with a template

- **WHEN** a checkout has `.agents/workflow.local.template.toml` and no local
  configuration, and the developer runs `change-workflow install` there
- **THEN** the checkout's `.agents/workflow.local.toml` holds the template's content

#### Scenario: A local configuration exists

- **WHEN** `install` runs in a checkout whose `.agents/workflow.local.toml` exists
  and holds anything
- **THEN** the file is unchanged

#### Scenario: The local configuration is empty

- **WHEN** a step's sandbox left an empty `.agents/workflow.local.toml` in a checkout
  with `.agents/workflow.local.template.toml`, and the developer runs `change-workflow
  install` there
- **THEN** the checkout's `.agents/workflow.local.toml` holds the template's content

### Requirement: CW-4pm4 Settings developers may vary live in the local configuration

A setting developers using the workflow on the same repository may give different
values MUST live in the checkout's gitignored local configuration,
`.agents/workflow.local.toml`: the engineering-guidance pointer, `[models]`, and the
writable sandbox paths a developer adds. Every other field MUST live in the committed
`.agents/workflow.toml`. A field in the wrong file MUST be refused, naming the file it
belongs in; writable sandbox paths alone MAY appear in both, the local ones extending
the committed ones. With no local configuration, `start` MUST refuse, naming the
missing field and `change-workflow install`, and `check config` MUST report the
missing local fields without refusing. `config --json` MUST succeed with no local
configuration, reporting it under `local` with `exists` false and each required
local field it lacks with the status `missing`, and giving every committed field and
what the distribution provides in full. A change's clone MUST link its local
configuration to the workspace's.

#### Scenario: Models are committed

- **WHEN** `.agents/workflow.toml` declares `[models]`
- **THEN** every subcommand that reads it refuses, naming `.agents/workflow.local.toml`
  as the file `[models]` belongs in

#### Scenario: CI checks the configuration

- **WHEN** `check config` runs in a checkout with no local configuration
- **THEN** it checks every committed field, reports the local fields as missing, and
  exits 0

#### Scenario: CI reads the workflow's roles

- **WHEN** a repository's test runs `config --json` in a checkout with no local
  configuration
- **THEN** it exits 0, gives `roles` and the `workflow` paths in full, reports
  `guidance.engineering` and each step's models as `missing`, and gives
  `guidance.engineering` as `null`

#### Scenario: A step starts with no local configuration

- **WHEN** `start design <change>` runs in a checkout with no local configuration
- **THEN** it refuses, naming the missing models and `change-workflow install`, and
  launches nothing

### Requirement: CW-hu0z The engineering guidance is reached through a pointer

The workflow MUST NOT ship engineering guidance. The local configuration's
`[guidance] engineering` MUST name where a user's engineering guidance is, as a table
holding exactly one of `path`, a directory relative to the checkout's root or
beginning with `~`, or `none`, a reason the repository applies none; the field is
required. The check MUST refuse a `path` that is missing or holds no Markdown file,
and an empty reason. `config load` MUST print the Markdown files beneath the pointer
with every step's documents, and `config --json` MUST give the pointer as
`guidance.engineering`: `{"path": <the resolved absolute directory>}`, `{"none":
<the reason>}`, or `null` while the local configuration lacks it. The check MUST
refuse a `load` entry that is or lies beneath the pointer's directory.

#### Scenario: A developer points at the repository's engineering guidance

- **WHEN** the local configuration declares `engineering = { path =
  "docs/guidance/engineering/" }`
- **THEN** `config load plan` prints that directory's Markdown files, and `config
  --json` gives `guidance.engineering` as `{"path": ...}` holding its absolute path

#### Scenario: A repository applies no engineering guidance

- **WHEN** the local configuration declares `engineering = { none = "the workflow's
  own repository applies only its guidance" }`
- **THEN** `config load plan` prints no engineering file, and `config --json` gives
  `guidance.engineering` as `{"none": ...}` holding the reason

#### Scenario: A load entry repeats the pointer

- **WHEN** the pointer names `docs/guidance/engineering/` and `load.common` names
  `docs/guidance/`
- **THEN** the configuration's check refuses, naming the entry and the pointer

### Requirement: CW-7x0z Skills cite engineering guidance by section name

A skill MUST cite engineering guidance by the name of a Markdown section beneath the
pointer's directory, never by a file's name or path. The section names the shipped
skills cite are a provisional interface, succeeded by naming engineering guidance by
role. A cited name that heads more than one section beneath the pointer does not
resolve. `check config` MUST report each cited section no file beneath the pointer
heads, and each that more than one section heads, naming the files, and MUST NOT
refuse for either.

#### Scenario: A user's guidance lacks a cited section

- **WHEN** a user's pointer names guidance with no section "Imports go at module
  level", which a skill cites
- **THEN** `check config` reports the section as missing beneath the pointer and exits
  0

#### Scenario: A cited section name repeats

- **WHEN** a skill cites the section "Integration tests" and two files beneath the
  pointer each head a section of that name
- **THEN** `check config` reports the citation as ambiguous, naming both files, and
  exits 0

### Requirement: CW-d867 Each log line records the workflow version

Every line the log's writer appends MUST carry `workflow`, the version of the engine
that wrote it. No reader MUST route on it, and adding it MUST NOT move the record
set's format.

#### Scenario: A change crosses an upgrade

- **WHEN** a change's design is recorded under 0.4.1 and its plan under 0.4.2
- **THEN** the design's line carries `"workflow": "0.4.1"`, the plan's `"workflow":
  "0.4.2"`, and both carry `"format": 2`

### Requirement: CW-dvz5 The command prints the installed fragment's path

`change-workflow fragment` MUST print the path of the installed make fragment, for a
repository's `Makefile` to include. The fragment's targets and variables stay outside
the compatibility promise; `fragment` is public.

#### Scenario: A Makefile includes the fragment

- **WHEN** a repository's `Makefile` holds `include $(shell change-workflow fragment)`
- **THEN** make reads the installed version's fragment, and its targets call
  `change-workflow`

### Requirement: CW-ora1 The workflow's roles are structured output

`config --json` MUST list, as `roles`, each role the workflow leaves to an adopting
repository, by name, with the configuration fields that provide it. The
distribution's own test MUST fail when the companion's table of roles and `roles`
differ.

#### Scenario: A repository holds its statement of provisions complete

- **WHEN** a repository's test compares its statement of provisions with the
  workflow's roles
- **THEN** it reads the roles from `config --json`, and parses no document of the
  workflow's

### Requirement: CW-368t The specification index check reports what a change's deltas create

`check spec-index <change> --json` MUST report, beside the check's result, the
specification paths the change's delta specifications create, so a repository's own
checks learn them without reading the deltas themselves.

#### Scenario: A citation check meets a specification the change creates

- **WHEN** a change's delta specifications create a new capability's specification,
  and a document cites it
- **THEN** `check spec-index <change> --json` lists the specification's path, and a
  citation check reading it accepts the citation

## MODIFIED Requirements

### Requirement: CW-r3ka The engine is reached through one command

Every operation of the workflow's engine MUST be reachable through one command's
subcommands, `change-workflow`, installed on the path, and a repository MUST reach the
engine only through that command, never by importing its code. The command MUST act
on the Git repository containing its working directory, and MUST refuse, naming the
directory, when run outside one.

#### Scenario: A repository script needs a change's directory

- **WHEN** a repository's closing check needs the directory of a change and
  whether it is archived
- **THEN** it runs `change-workflow find --json <change>` and reads the `directory`
  and `archived` fields, and imports nothing of the engine

#### Scenario: A change's checkout holds no records, or the change does not exist

- **WHEN** `find --json` runs for a change whose directory exists and whose
  checkout holds no `reviews/`
- **THEN** it exits 0 with `records` as `null`; for a change that does not exist,
  `find --json` and `clone where` each exit 1, naming the change, and `clone
  where` looks for no clone

#### Scenario: A change's clone exists but is unusable

- **WHEN** `clone where <change>` runs and the clone's directory exists but holds
  another branch, or is not a clone of the workspace, or its bootstrap has not
  succeeded
- **THEN** it exits 1, naming the reason, and never prints nothing as it does for
  a change worked in place, where no clone directory exists

#### Scenario: A step is started interactively without make

- **WHEN** the owner runs `change-workflow start design <change>` for an archived
  change
- **THEN** the command refuses, naming the archived directory, and starts no
  session

#### Scenario: The command runs in a change's clone

- **WHEN** the command runs in a change's clone
- **THEN** it acts on the clone's repository, not on the owner's workspace

#### Scenario: The command runs outside a repository

- **WHEN** the command runs in a directory no Git repository contains
- **THEN** it refuses, naming the directory, and writes nothing

### Requirement: CW-d8de Each skill has one source for every harness

The workflow's skills MUST be the installed distribution's, stamped with its version
(CW-1rhd), loaded from each supported harness's user skill directory, with no project
skill entry of the same name; an unattended Claude Code run of an installed engine,
whose opening event lists the skills its harness loaded, MUST be stopped before its
first turn when one of them is missing, naming each. Each agent skill a repository
commits itself MUST have exactly one source, under `.agents/skills/`, and MUST be
loadable by every supported agent harness from that source. A skill MUST NOT be
maintained as separate copies for different harnesses, and every harness entry for a
skill MUST resolve. `check skills` MUST hold both, the installed skills where the
engine is installed.

#### Scenario: A skill is edited

- **WHEN** a contributor edits a skill the repository commits
- **THEN** every harness loads the edited skill, with no second copy to update

#### Scenario: A harness entry does not resolve

- **WHEN** a harness skill entry points at a source that does not exist
- **THEN** the skills check fails

#### Scenario: An installed skill is stale

- **WHEN** an installed workflow skill is stamped with a version other than the
  engine's
- **THEN** the skills check fails, naming the skill and both versions

#### Scenario: A step's harness does not load an installed skill

- **WHEN** an unattended step's harness starts and its opening event lists no
  `change-design` among the skills it loaded
- **THEN** the run is stopped before its first turn, its model passed over as
  unavailable, naming `change-design`

### Requirement: CW-f3qk One configuration file states what the workflow assumes

The workflow MUST read what it assumes about a repository from its committed
configuration, `.agents/workflow.toml`, and the settings developers may vary from the
checkout's local configuration, `.agents/workflow.local.toml` (CW-4pm4): the commands
it runs, the documents its skills load, and the repository's values. Each field MUST
configure one operation of a skill or the engine, and a value Git or the invocation
supplies MUST NOT be a field. Adopters MUST NOT add tables or keys the workflow does
not define.

#### Scenario: A repository protects another branch

- **WHEN** a repository's configuration declares `protected-branches = ["trunk"]`
- **THEN** the guarded push refuses `trunk`, and the engine holds no branch name of
  its own

### Requirement: CW-c8lw A hook's default checks run unless disabled by name

The workflow's default checks for a hook MUST run before its declared commands,
which add to them; `pre-commit`'s are `index`, `tasks`, `skills`, `spec-index`,
`decisions`, and the strict `openspec` validation. A repository MUST turn one off only
by naming it, with a reason, under `defaults.disable`. `check change <change>` MUST run
them alone.

#### Scenario: A repository declares its own pre-commit

- **WHEN** the configuration declares `pre-commit = "make lint"` and disables nothing
- **THEN** `run pre-commit` runs the six default checks and then `make lint`

#### Scenario: A default check is turned off

- **WHEN** `defaults.disable` names `skills` with a reason
- **THEN** `run pre-commit` skips the skills check, and `config` lists it disabled
  with the reason

#### Scenario: A decision names no destination

- **WHEN** a change's design records `### D7` and its proposal's knowledge to promote
  has no bullet starting `D7`
- **THEN** the `decisions` default check fails, naming D7

### Requirement: CW-l7hn A step's documents to load come from the configuration

The documents a step's skill loads MUST be, in order, the Markdown files beneath the
engineering-guidance pointer (CW-hu0z), the installed workflow's guidance (CW-lm42),
and the configuration's `load.common` and `load.<step>`, printed together by `config
load <step>`; `config load common` MUST print the same without `load.<step>`, for a
session no step runs; and the post-compaction hook MUST have a session re-read what
`config load common` prints. An entry ending in `/` names a directory and MUST resolve
to the Markdown files beneath it, in sorted path order, each printed once; `config
load` MUST refuse, naming the entry, a directory entry that is missing, unreadable, or
holds no Markdown file.

#### Scenario: Design loads the roadmap

- **WHEN** the configuration lists the roadmap under `load.design`
- **THEN** `config load design` prints the engineering guidance, the workflow's
  guidance, the common documents, and the roadmap, and `config load plan` prints all
  but the roadmap

#### Scenario: A directory entry

- **WHEN** `load.common` names `docs/guidance/repository/`, which holds
  `locks.md` and `wheelhouse.md`
- **THEN** `config load common` prints both files' paths in sorted order in place of
  the directory, after the engineering and workflow guidance, and the post-compaction
  hook names them

#### Scenario: A directory entry names nothing

- **WHEN** `load.common` names `docs/guidens/`, which does not exist
- **THEN** `config load common` fails, naming the entry, and the post-compaction hook
  tells the session the documents to re-read are unknown

### Requirement: CW-d2rw Guidance never links to a higher layer

A guidance file MUST NOT link to a guidance file tagged with a higher layer:
engineering guidance links only to engineering guidance, and repository guidance to
any. Workflow guidance MUST name the engineering guidance it relies on by section
name, through the engineering-guidance pointer (CW-7x0z), and MUST NOT link to it by
path.

#### Scenario: Workflow guidance links to a repository document

- **WHEN** a file tagged `workflow` links to a file tagged `repository`
- **THEN** it does not satisfy the requirement, and the link is replaced by what the
  workflow guidance can state without the repository

#### Scenario: Workflow guidance relies on an engineering rule

- **WHEN** the workflow's closeout guidance relies on the rule that a cited path
  resolves
- **THEN** it names the engineering guidance's section "Citations resolve", with no
  link to a file

### Requirement: CW-n8tr The workflow's skills name no repository's targets or paths

A make target or repository path a workflow skill names MUST be the workflow's own —
OpenSpec's tree, the change index, the make fragment's targets, or the engine's
command — or one listed as an exemption owned by the change that removes it. A skill
MUST cite the workflow's guidance by section name and its specification by
requirement id (CW-lm42), and engineering guidance by section name (CW-7x0z). A test
MUST fail on any other target or path, naming the skill.

#### Scenario: A skill names a repository's check

- **WHEN** a skill is edited to run `make check-comment-hygiene`
- **THEN** the test fails, naming the target and the skill, and the skill names the
  repository's comment check by its role

#### Scenario: A skill names an engineering guidance file

- **WHEN** a skill is edited to cite `docs/guidance/engineering/test-levels.md`
- **THEN** the test fails, naming the path and the skill, and the skill cites the
  section it relies on by name

### Requirement: CW-r6kd No step writes the protected paths

The sandbox MUST mount read-only, inside every step's scope, the workflow's committed
and local configuration, `.git/config`, the engine's `git` (CW-j4cs), the installed
distribution, and the paths the harness's adapter and the repository protect, so no
step writes a protected file. A harness's adapter MUST protect every settings file
its harness loads, its user skill directory, and the installer's manifest there. Each
writable and protected path MUST be mounted where its symlinks lead. A protected path
absent at launch MUST be created first, a settings file in its harness's empty form,
and mounted read-only like any other. A protected path MUST NOT be granted. The
protected path's name is not guarded: renaming a directory holding a protected mount,
or replacing a link to a protected file, inside a writable directory, is a step
working around the sandbox or, by a shell rewrite of a settings link, a step already
writing what no step writes, which its review catches.

#### Scenario: An implementation run edits the configuration

- **WHEN** an unattended implementation run writes `.agents/workflow.toml` or
  `.agents/workflow.local.toml`
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

#### Scenario: A step edits an installed skill

- **WHEN** an unattended implementation run on Claude Code writes a workflow skill in
  Claude Code's user skill directory
- **THEN** the write fails, though the rest of `~/.claude` is writable as the
  adapter's state

#### Scenario: A step edits the installed engine

- **WHEN** an unattended run writes a module of the installed distribution beneath a
  writable path the repository grants
- **THEN** the write fails, the distribution mounted read-only inside the writable path
