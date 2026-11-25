## ADDED Requirements

### Requirement: MCW-9k0c This repository runs the installed workflow within its declared range

This repository MUST run the change workflow as the installed `change-workflow`
command and its installed skills, holding no copy of the workflow's engine, skills,
outcome schema, guidance, specification, or handbook in its tree, and its committed
configuration MUST declare the workflow versions it accepts. Its documents MUST cite
the workflow in prose, by requirement id and section, naming it as the distribution
`arkhai-change-workflow`, with no link to or address of the workflow's repository.

#### Scenario: A developer runs a step with a version outside the range

- **WHEN** this repository's configuration accepts `>=0.1, <0.2` and the developer
  has 0.2.0 installed
- **THEN** `make design CHANGE=<change>` refuses, naming the installed version, the
  range, and installing a version in range

#### Scenario: A document cites a workflow requirement

- **WHEN** a document of this repository relies on the workflow's guarded push
- **THEN** it names `change-workflow`'s requirement by id, with no relative path to a
  file of the workflow's

#### Scenario: A document names the workflow

- **WHEN** a document of this repository says where the change workflow comes from
- **THEN** it names the distribution `arkhai-change-workflow`, and no address of the
  workflow's repository

### Requirement: MCW-iqh1 This repository's local configuration template points at its engineering guidance

This repository MUST commit `.agents/workflow.local.template.toml`, from which the
workflow's installer writes a developer's local configuration, naming
`docs/guidance/engineering/` as the engineering-guidance pointer and the models this
repository's steps are expected to run on; the local configuration itself MUST be
ignored by Git.

#### Scenario: A developer installs the workflow in a fresh clone

- **WHEN** a developer sets up the installed workflow in a checkout of this repository
  with no local configuration
- **THEN** its `.agents/workflow.local.toml` points the engineering guidance at
  `docs/guidance/engineering/`, and Git reports the file as ignored

### Requirement: MCW-w7nb This repository builds, tests, and releases without the workflow

This repository MUST build, test, and release on a machine where the change workflow
is not installed: its CI MUST NOT install the workflow, no suite `make test` runs and
no release target MAY call `change-workflow`, its `Makefile` MUST include the
workflow's fragment only when the command is installed, and its own targets that
refuse while a round view is open MUST read the open view from Git's metadata rather
than through the workflow's command.

#### Scenario: CI runs the suites without the workflow

- **WHEN** CI runs `make test`'s targets on a runner where `change-workflow` is not
  installed
- **THEN** every suite runs, and none fails or skips for the workflow's absence

#### Scenario: A repository target refuses an open round view

- **WHEN** a round view is open in the checkout and the developer runs `make
  validate-local`
- **THEN** it refuses before running anything, whether or not `change-workflow` is
  installed

#### Scenario: A code snapshot of a worktree in use

- **WHEN** the worktree holds uncommitted changes and the developer runs `make
  code-snapshot`
- **THEN** the snapshot is made

## MODIFIED Requirements

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository's committed configuration, `.agents/workflow.toml`, MUST declare the
committed fields the workflow defines, and this repository MUST state how it provides
each role the configuration does not hold: the make target, path, or document that
fills it. Whether the statement is complete for the installed version is the
workflow's repository's to verify, and a review's when a change edits the declared
range; this repository keeps no test of it.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the configuration's `local` evidence kind names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the configuration names `main` and `dev`, which the guarded push refuses
