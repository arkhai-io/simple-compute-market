## Why

The workflow's skills and step table name this repository's make targets
directly. Between them they reach about thirty targets. Those targets are three
different kinds of thing, and nothing tells them apart:

- **The workflow's own operations that happen to live in this Makefile:** the
  guarded push, round views, clones, history, cost, and the change-index and
  task checks.
- **This repository's own operations:** `make test`, `make typecheck`, `make
  lock`, `make check-packaging`, the CI dispatch and read, the end-to-end
  pipeline and its logs, Helm validation, and the capacity record.
- **Checks any repository would want, which could have a default:** OpenSpec
  validation and citation resolution.

So a repository adopting the workflow would have to reproduce this repository's
target names exactly, or edit the skills. No single file states what the
workflow assumes about the repository it runs in; the assumptions are spread
through the skills, the step table, and the `Makefile`.

## What Changes

- **One configuration file per repository.** A `workflow.toml` under `.agents/` is the one
  place the workflow reads its assumptions about a repository: where things
  live, such as the OpenSpec root and the guidance documents the skills load, and
  the commands that implement its capabilities.
- **A capability contract.** The workflow names a small set of capabilities, each
  with stated semantics: what it must do, what its exit status means, and where
  its output goes. A capability resolves to the command the repository declares,
  else the workflow's default, else absent. Each capability is one of three
  kinds:

  | Kind | If the repository declares nothing |
  |---|---|
  | Required, with no default | the workflow refuses to run a step that needs it |
  | Optional, with a default | the workflow's default runs |
  | Optional, and may be absent | a step that would use it skips that part and says so in its record |

- **Commands are shell commands.** A capability is implemented by any command,
  in any language. Make is one possible implementation, not a requirement.
- **Skills invoke capabilities by name, through the engine.** They no longer name
  make targets. Each step names the capabilities it may invoke, and the engine
  refuses any other. So moving the skills to capability invocation widens no
  step's permissions.
- **Resolution is visible.** A command lists every capability with how it
  resolved. Each run's log line records which implementation satisfied each
  capability the run invoked, so a reviewer can see what actually ran.
- **The workflow's own operations become engine commands.** The guarded push,
  round views, clones, history, cost, and the workflow's own checks are not
  capabilities a repository supplies.
- **This repository adopts the contract.** Its `workflow.toml` declares
  its capabilities as its existing make targets, so its behaviour does not
  change.

## Capabilities

### New Capabilities

- None expected. The contract is part of the workflow's specification, or of the
  engine capability if `specify-change-workflow-and-engine` creates one.

### Modified Capabilities

- `change-workflow`, or the engine capability: the repository configuration
  file, the capability contract and its resolution, per-step capability lists,
  and resolution recorded on each run.

## Non-Goals

- **Do not rework permissions beyond capability invocation.** Sandbox profiles,
  engine-held credentials for privileged actions, and post-step invariant checks
  are their own change. This change only keeps capability invocation from
  widening any step's permissions.
- **Do not add skill extension points.** That is its own change.
- **Do not ship language-specific defaults.** Comment hygiene is an example: its
  rules are guidance, and it belongs with the guidance packs. Until those exist,
  a repository declares its own command.
- **Do not extract the engine, or change what any step does.**

## Impact

- `.agents/skills/change-*/SKILL.md`, which move from make targets to
  capabilities.
- `scripts/change_workflow/`, for configuration loading, capability resolution,
  the per-step capability lists, and the resolution recorded on run lines.
- `.claude/change-steps.toml`, whose allow rules move to the capability
  invocation form.
- A new `workflow.toml` under `.agents/` for this repository, and the `Makefile` targets it
  names, which are unchanged.
- `docs/agents/change-workflow.md` and the workflow's specification and
  architecture companion.
- The workflow's tests under `scripts/tests/`.

## Dependencies and Related Changes

- **`specify-change-workflow-and-engine` (design).** This change designs against
  that change's inventory of repository assumptions and its classification of
  the engine's public surface. The configuration schema and the capability
  contract extend that surface.
- **The permissions change, still to be opened,** builds on the per-step
  capability lists.
- **The skill extension points change, still to be opened,** names its addenda
  in the same configuration file.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, or the engine
      capability `specify-change-workflow-and-engine` creates
- [ ] New subsystem specification
- [ ] No permanent documentation change

The lesser goal's gap "No single file states what the workflow assumes about a
repository" in `openspec/changes/README.md` is owned by this change and closes
with it.

### Knowledge to promote

To be determined at design completion.
