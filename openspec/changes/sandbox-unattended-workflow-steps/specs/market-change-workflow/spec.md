## ADDED Requirements

### Requirement: MCW-s4bx This repository's sandbox extensions

This repository's configuration MUST give design and planning `docs/` beside their
baseline scope, and every step but the review the tool state its suites, builds,
and deployments write outside the checkout: uv's Pythons and tools, the Kubernetes
client's cache, the Google Cloud SDK's configuration, which refreshes its tokens,
Docker's client configuration, and npm's cache, which the configured OpenSpec command
writes. It MUST protect nothing beyond the engine's and the adapters' protected
paths.

#### Scenario: Design edits the roadmap

- **WHEN** an unattended design run edits `docs/development/ROADMAP.md`
- **THEN** the write succeeds, since the configuration gives design `docs/`

#### Scenario: Implementation syncs an environment

- **WHEN** an unattended implementation run's `uv sync` installs a Python under
  `~/.local/share/uv`
- **THEN** the write succeeds, since the configuration gives every writing step that
  path

#### Scenario: Design validates the change

- **WHEN** an unattended design run runs `scripts/change-workflow openspec validate
  <change> --strict`, whose `npx` writes npm's cache under `~/.npm`
- **THEN** the write succeeds, since the configuration gives every writing step that
  path

## MODIFIED Requirements

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository's configuration, `.agents/workflow.toml`, MUST declare the fields the
workflow defines, and this repository MUST state how it provides each role the
configuration does not hold: the make target, path, or document that fills it. Every
make target and repository path the workflow's make fragment names MUST appear in
that statement or in the configuration; the workflow's skills name none.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the configuration's `local` evidence kind names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the configuration names `main` and `dev`, which the guarded push refuses
