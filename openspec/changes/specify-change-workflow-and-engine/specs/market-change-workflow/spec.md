## ADDED Requirements

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository MUST state, for each role the change workflow asks of an adopting
repository, how it provides that role: the make target, path, branch, or document
that fills it. Every make target and repository path the workflow's skills, step
table, and make fragment name MUST appear in that statement, and so MUST the
engine's own assumptions about this repository, marked as maintained by review.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the statement names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the statement names `main` and `dev`, which the guarded push refuses
