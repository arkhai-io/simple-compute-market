## MODIFIED Requirements

### Requirement: MCW-r4tx This repository's hooks and validation parts

This repository's configuration MUST relock after a functional change; run `make
check-repository` before every commit, while `make check-change` runs the workflow's
whole `pre-commit` for the owner; before a functional commit, clear the wheelhouse,
check packaging, and run every suite, leaving `local` evidence for the tree it
tested; check packaging and the change's architecture exceptions before the archive;
and declare the evidence kinds `local`, `helm` after it with a cleanup recording the
capacity measured and removing the change's namespace and images, `pipeline`, and
owed `ci`, each with its guide under `.agents/evidence/`; `local` and `helm` keep
their evidence under `.snapshot/evidence/{tree}/`, and `pipeline` and `ci`, whose
runs MCW-zk52 and MCW-7hr1 tie to the commit under validation and whose baseline
MCW-2lzw chooses by its ancestry, under `.snapshot/evidence/{commit}/`, `ci`'s per
owed workflow; each attempt is a directory named by its UTC start time.

#### Scenario: Validation runs this repository's parts

- **WHEN** validation of a commit runs in this repository with no kind waived, a
  complete section owing `(ci tests.yml)`, and no evidence present for its tree
- **THEN** the gathering starts the pipeline and the owed CI run, then runs the
  local kind, then the Helm kind

#### Scenario: Implementation's checks stand for the local kind

- **WHEN** an implementation's functional checks pass for the tree it then commits
- **THEN** validation of that commit finds the `local` kind present and gathers only
  the others

#### Scenario: A pipeline run for another commit with the same tree

- **WHEN** a pipeline run's evidence exists for a commit whose message was since
  amended, and the amended commit is validated
- **THEN** the pipeline kind is missing for it and its own run is dispatched

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository's configuration, `.agents/workflow.toml`, MUST declare the fields the
workflow defines, and this repository MUST state how it provides each role the
configuration does not hold: the make target, path, or document that fills it. Every
make target and repository path the workflow's step table and make fragment name MUST
appear in that statement or in the configuration; the workflow's skills name none.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the configuration's `local` evidence kind names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the configuration names `main` and `dev`, which the guarded push refuses
