# Design: add the workflow capability contract

Status: design phase. Not planned. The direction under "Starting direction" came
from the owner's discussion that opened the lesser goal, and design confirms or
revises it. Everything under "Open questions" is undecided.

## Context

- **What the skills invoke.** The `change-*` skills name about thirty make
  targets between them, and `.claude/change-steps.toml` allows a similar set.
  Grouped by what they are:
  - **The workflow's own operations:** `push-branch`, `round-view`,
    `round-view-closed`, `round-done`, `check-change`, `check-change-index`,
    `check-tasks`, `check-agent-skills`, `change-clone`, `change-clone-remove`,
    `change-history`, `change-cost`, `change-watch`, and the step targets
    themselves (`design`, `plan`, `implement`, `review`, `triage`, `validate`,
    `merge`, `closeout`, `archive-cleanup`, `orchestrate`).
  - **This repository's operations:** `test`, `typecheck`, `lock`, `init`,
    `reinit`, `check-packaging`, `check-architecture`, `check-uv-version`,
    `dist`, `dist-clean`, `helm-values-schema`, `run-ci`, `validate-ci`,
    `run-e2e`, `fetch-e2e-logs`, `validate-local`, `validate-helm`,
    `validate-parallel`, `record-capacity`, and `code-snapshot`.
  - **Checks with a plausible repository-independent default:**
    `check-doc-citations` and OpenSpec validation (`openspec validate`).
  - **Checks whose rules depend on the language:** `check-comment-hygiene`.

  `specify-change-workflow-and-engine`'s inventory supersedes this list once it
  exists.
- **Parameterized targets.** Several targets take arguments through make
  variables: `CHANGE`, `WORKFLOW` and `CI_AFTER_RUN` for `validate-ci`,
  `HELM_CONTEXT`, and `HELM_ALL_SCENARIOS`.
- **Protected configuration.** Every step is denied editing `.claude/**`, so no
  step can change its own permissions. The repository configuration file is a
  new file of the same kind.

## Starting direction

- **The configuration file is `workflow.toml`, under `.agents/`.**
- **A capability resolves in a fixed order:** the repository's declared command,
  else the workflow's default, else absent. A capability has a default only where
  the operation genuinely does not depend on the repository. Checking OpenSpec
  compliance has one; running the tests does not.
- **Capabilities are shell commands,** so the contract works whatever language
  the repository is written in.
- **Language-specific defaults belong with guidance packs,** not in the workflow.
- **Each step lists the capabilities it may invoke,** and the engine enforces the
  list.
- **Resolution is visible,** both as a listing and on each run's log line.

## Open questions

- **The capability set.** Which capabilities exist, their names, and their
  semantics. The repository's operations above are the starting list, but
  several may merge. For example, `validate-local` is `check-packaging` followed
  by `test`, and the validation step's parts could be one composite capability
  with named parts rather than five separate ones.
- **The validation step's shape.** It is the most repository-specific step:
  local checks, CI workflows, an end-to-end pipeline, Helm, and the capacity
  record. It could be a validation profile in the configuration, listing the
  parts a commit's validation runs, or individual capabilities the skill invokes
  in order.
- **Engine operation or capability.** Some operations sit on the line.
  `record-capacity` and the validation namespace's teardown are specific to this
  repository's Helm validation, so they are probably capabilities that may be
  absent. `round-view` changes the owner's checkout, so it is probably an engine
  operation.
- **Arguments.** How a capability receives the change name, a workflow file, a
  Kubernetes context, or a run to wait for: environment variables, placeholders
  in the declared command, or positional arguments. The choice bears on how the
  engine enforces a step's capability list without parsing the command.
- **The output contract.** What a capability reports beyond its exit status.
  Validation diagnoses failures from logs, so a capability may need to name where
  its logs went. Whether that is a convention or a structured result is open.
- **Defaults.** How the workflow ships a default: as an engine subcommand or as a
  script it runs. Also whether a repository can extend a default rather than
  replace it, for example by running the default OpenSpec check followed by its
  own.
- **What else the configuration names.** Candidates: the OpenSpec root, the
  guidance documents each step loads, where change records are kept and the
  owner's workspace, and the base branch. Each path named here is one assumption
  the skills stop making.
- **Validating the configuration.** Whether the engine checks the file at every
  step start, or a separate check exists. What a missing required capability
  does: refuse every step, or only the steps that need it.
- **Protecting the file.** Whether steps are denied editing the configuration file
  as they are denied editing `.claude/**`. The same reason applies: a step must
  not be able to change what its own capabilities run.
