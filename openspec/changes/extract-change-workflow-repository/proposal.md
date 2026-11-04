## Why

The change workflow lives in this repository and has no version of its own. A
change to it ships with whichever commit of this repository carries it. No other
repository can adopt it without copying it, and a copy stops receiving
improvements the day it is made. Its improvements are also entangled with market
changes, in the same history, reviews, and releases.

The changes before this one draw the boundary between the workflow and this
repository while both still live here:

- `specify-change-workflow-and-engine` specifies the workflow and its engine and
  defines the public surface.
- `add-workflow-capability-contract` puts the repository's assumptions in one
  configuration file and behind named capabilities.
- `sandbox-unattended-workflow-steps` replaces this repository's command
  allowlists with harness-neutral profiles.
- `add-skill-extension-points` moves this repository's specifics out of the base
  skills into addenda.
- `layer-engineering-guidance` separates the workflow's guidance from engineering
  and repository guidance.

Once those land, what is left on the workflow's side of the boundary can move
to a repository of its own, be versioned, and be adopted. This change moves it.
Its details depend on what those designs settle, so this proposal states
direction rather than mechanics.

## What Changes

- **A public repository for the workflow.** It holds:
  - the engine;
  - the `change-*` skills;
  - the workflow's specification and architecture;
  - the outcome schema;
  - the workflow-layer guidance;
  - the capabilities' default implementations;
  - the tests for all of these.

  The history of the moved files is preserved. The repository is public, so an
  adopting public repository may name it.
- **One versioned distribution.** The engine and the skills ship together under one
  version. An installer puts the skills into each supported harness's user skill
  directory, starting with Claude Code's and Codex's. That way one installation
  serves every repository on the machine, with no per-repository copies and no
  namespacing of skill names.
- **Repositories declare a compatible version range.** An adopting repository
  states the range of workflow versions it accepts in its workflow configuration,
  in the style of Python's version specifiers. That lets it follow the latest
  compatible release without committing a pin update for every release. The
  engine checks the range at every step and refuses on a mismatch, naming the
  fix. Until a major release, the workflow bumps minor and patch versions
  leniently.
- **Records carry the workflow version.** Each line of a change's workflow log
  records the version that wrote it. A minor upgrade migrates records forward, as
  record conversion does today. A change started under one major version
  finishes under it.
- **This repository becomes an adopter.** It removes the engine, the skills, and
  the workflow's specification from its tree. It keeps:
  - its workflow configuration;
  - its addenda;
  - its repository-layer guidance;
  - its own workflow requirements;
  - its make targets, as shims over the installed workflow or removed.

## Capabilities

### New Capabilities

- None in this repository. The workflow's capabilities move with it.

### Modified Capabilities

- **`change-workflow`, and the engine capability if one exists,** leave this
  repository for the workflow's repository.
- **This repository's own workflow requirements,** wherever
  `specify-change-workflow-and-engine` placed them, stay here and come to
  reference the workflow by version.

## Non-Goals

- **Do not move the engineering guidance layer.** Where it lives, and how a
  repository loads and cites it, are separate changes.
- **Do not add harnesses.** The installer serves the harnesses the workflow
  supports when it is extracted; adding one is the harness adapter change's.
- **Do not build the model gateway or the hosted runner.**
- **Do not change what any step does.** The extraction moves the workflow; it
  does not redesign it.

## Impact

- `scripts/change_workflow/` and the engine's standalone scripts,
  `.agents/skills/change-*`, `.agents/change-outcome.schema.json`,
  `openspec/specs/change-workflow/`, and the workflow-layer guidance. All leave
  this repository.
- `.claude/skills/` and `.codex/skills/`, whose links to the change skills go,
  and `scripts/check_agent_skills.py`, whose job changes.
- The `Makefile`'s workflow targets.
- Every permanent document that cites a moved path. This repository's citation
  check then fails on any reference left behind.
- The workflow's tests under `scripts/tests/`, which move.
- A new repository, its release process, and its own continuous integration.

## Dependencies and Related Changes

- **`specify-change-workflow-and-engine` (design).** The public surface defines
  what a version promises, and the split of requirements decides what leaves.
- **`add-workflow-capability-contract` (design).** The configuration file is where
  an adopting repository declares its version range, and the capability defaults
  move with the workflow.
- **`sandbox-unattended-workflow-steps` (design).** Permissions must be
  harness-neutral before they leave a repository whose `.claude/` directory holds
  them today.
- **`add-skill-extension-points` (design).** The base skills must hold no
  repository material before they are shared.
- **`layer-engineering-guidance` (design).** It identifies the workflow-layer
  guidance that moves.
- **The harness adapter change, still to be opened,** extends the installer to
  further harnesses.
- **The hosted runner change, still to be opened,** builds its image from the
  extracted workflow at a version.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`, for how this repository adopts the
      workflow
- [x] Existing subsystem specification: `change-workflow` leaves; this
      repository's own workflow requirements are amended
- [ ] New subsystem specification
- [ ] No permanent documentation change

`AGENTS.md`, `docs/agents/change-workflow.md`, `openspec/README.md`, and
`openspec/changes/README.md`'s lesser goal change with it. After extraction, the
lesser goal's remaining gaps belong to the workflow's repository, and this
repository keeps only its adoption.

The lesser goal's gap "The workflow is not a separately versioned distribution"
in `openspec/changes/README.md` is owned by this change and closes with it.

### Knowledge to promote

To be determined at design completion.
