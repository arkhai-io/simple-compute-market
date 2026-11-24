## ADDED Requirements

### Requirement: MCW-9k0c This repository runs the installed workflow within its declared range

This repository MUST run the change workflow as the installed `change-workflow`
command and its installed skills, holding no copy of the workflow's engine, skills,
outcome schema, guidance, specification, or handbook in its tree, and its committed
configuration MUST declare the workflow versions it accepts. Its documents MUST cite
the workflow in prose, by name, requirement id, and section, with a link only to the
workflow's repository.

#### Scenario: A developer runs a step with a version outside the range

- **WHEN** this repository's configuration accepts `>=0.1, <0.2` and the developer
  has 0.2.0 installed
- **THEN** `make design CHANGE=<change>` refuses, naming the installed version, the
  range, and installing a version in range

#### Scenario: A document cites a workflow requirement

- **WHEN** a document of this repository relies on the workflow's guarded push
- **THEN** it names `change-workflow`'s requirement by id, with no relative path to a
  file of the workflow's

### Requirement: MCW-iqh1 This repository's local configuration template points at its engineering guidance

This repository MUST commit `.agents/workflow.local.template.toml`, from which the
workflow's installer writes a developer's local configuration, naming
`docs/guidance/engineering/` as the engineering-guidance pointer and the models this
repository's steps are expected to run on; the local configuration itself MUST be
ignored by Git.

#### Scenario: A developer installs the workflow in a fresh clone

- **WHEN** a developer runs `change-workflow install` in a checkout of this repository
  with no local configuration
- **THEN** its `.agents/workflow.local.toml` points the engineering guidance at
  `docs/guidance/engineering/`, and Git reports the file as ignored

## MODIFIED Requirements

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository's committed configuration, `.agents/workflow.toml`, MUST declare the
committed fields the workflow defines, and this repository MUST state how it provides
each role the configuration does not hold: the make target, path, or document that
fills it. Its test MUST read the workflow's roles from `config --json` and the make
fragment from the path `change-workflow fragment` prints; every make target and
repository path the fragment names MUST appear in that statement or in the
configuration, and the workflow's skills name none.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the configuration's `local` evidence kind names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the configuration names `main` and `dev`, which the guarded push refuses

#### Scenario: The workflow adds a role

- **WHEN** an installed workflow version lists a role in `config --json` that this
  repository's statement does not name
- **THEN** this repository's test fails, naming the role
