## ADDED Requirements

### Requirement: MCW-r4tx This repository's hooks and validation parts

This repository's configuration MUST relock after a functional change; run its own
closing checks, `make check-repository`, before every commit, while `make
check-change` runs the workflow's whole `pre-commit` for the owner; before a
functional commit, clear the wheelhouse, so that the packaging check builds every
wheel from the commit and no suite tests a wheel another commit built, then check
packaging and run every suite; check packaging and the
change's architecture exceptions before the archive; and declare validation's
pipeline, owed CI, local, and Helm parts, the Helm part after the local one, with a
cleanup that records the capacity measured and removes the change's namespace and
images.

#### Scenario: Validation runs this repository's parts

- **WHEN** validation runs in this repository with no part waived and a complete
  section owing `tests.yml`
- **THEN** it starts the pipeline and the owed CI run, then runs the local part,
  then the Helm part

### Requirement: MCW-k3vy The pre-push checks are one make target

The pre-push checks MUST be one make target, `make pre-push`, which runs both
public-content checks under Git's hook contract, and which both the configuration's
`pre-push` and the Git hook `scripts/hooks/pre-push` run.

#### Scenario: The Git hook runs the checks

- **WHEN** an owner's `git push` runs the repository's pre-push hook
- **THEN** the hook runs `make pre-push` with the remote, which runs both
  public-content checks the guarded push runs

## MODIFIED Requirements

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository's configuration, `.agents/workflow.toml`, MUST declare the fields the
workflow defines, and this repository MUST state how it provides each role the
configuration does not hold: the make target, path, or document that fills it. Every
make target and repository path the workflow's skills and step table name MUST appear
in that statement or in the configuration.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the configuration's `local` validation part names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the configuration names `main` and `dev`, which the guarded push refuses

## REMOVED Requirements

### Requirement: MCW-ca51 The merge brings in `dev` unless the owner names another branch

**Reason**: The branch a change lands on is no repository value: it is recorded where
the change's orchestration began, or given as an argument.

**Migration**: CW-s3ju and CW-hdxi.

### Requirement: MCW-y37w The step table names no Fable or Astra model

**Reason**: A repository states the models it prefers for each step; it keeps no
list of models it forbids.

**Migration**: CW-ebmo and CW-zq4h; this repository's configuration names its
models.
