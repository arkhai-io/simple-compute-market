## Why

`specify-change-workflow-and-engine` listed every assumption the workflow makes about
the repository it runs in, but nothing declares them. The skills name this
repository's make targets and documents directly, and the engine holds this
repository's values as constants: its protected branches, its remote, its pre-push
scripts, the branch a change lands on, its bootstrap command, the models it forbids,
the documents a session re-reads, and the paths a commit may change without a new
validation. Validation's skill builds in this repository's end-to-end pipeline, CI
dispatch, and Helm parts.

So a repository adopting the workflow would have to reproduce this repository's
targets, branches, and paths, or edit the skills and the engine. No single file
states what the workflow assumes about a repository.

## What Changes

- **One configuration file per repository.** `.agents/workflow.toml` is the one place
  the workflow reads what it assumes about a repository. Each field configures one
  operation of a skill or the engine, and a value Git or the invocation can supply is
  never a field.
- **Hooks named by when they run.** A repository's commands hang on the workflow's
  lifecycle: `after-functional-change`, `pre-commit`, `pre-commit-functional`,
  `pre-archive`, `pre-push`, and `post-clone`. A hook holds a command or a list, and
  each command is a shell command, so the contract holds whatever the repository's
  language. Adopters change what a hook runs and add no hook keys.
- **Validation's parts are declared.** The parts validation runs, their order, their
  dispatch and wait, the evidence each keeps, and the cleanup each leaves for archive
  cleanup are the configuration's, not the skill's.
- **Values that are derived, not configured.** The branch a change lands on is the
  branch orchestration started from, recorded with the change's clone; the remote is
  the branch's upstream; an argument overrides either.
- **Models are a preference per step.** Each step's ordered models, and the
  orchestrating session's, move from the step table into the configuration; the
  forbidden-models rule is removed.
- **Defaults run unless disabled by name.** The workflow's default checks for
  `pre-commit` — the change index, the task list, the skills, and the strict OpenSpec
  validation — run before the repository's commands; a repository turns one off only
  by naming it, with a reason.
- **Skills invoke hooks through the engine.** `scripts/change-workflow run` runs a
  hook or a validation part, filling its placeholders; the engine holds which step may
  run which hook and refuses others for an unattended run, whose marker now names its
  step.
- **What ran is recorded.** `scripts/change-workflow config` lists how every field
  resolved, the engine writes each command's closing line, and each run's log line
  records every hook and command it invoked through `run` or the guarded push, with
  its exit status; a clone's bootstrap, which belongs to no step's run, is recorded
  in its own bootstrap state with the command it resolved to.
- **Validation's plan comes from the engine.** `config parts <change>` lists the runs
  of validation's parts in order, an owed part once per owed workflow, each named so
  its kept marker is its own; `run cleanup <change>` runs every part's cleanup.
- **Inert paths.** The paths a change to which proves nothing validation would prove
  are configured, replacing the engine's `openspec/` and `docs/`, and they decide
  which pre-commit hooks a commit runs.
- **This repository adopts the contract.** Its `workflow.toml` declares its existing
  targets, so its behaviour is unchanged but for the decisions' own effects: a
  documentation-only commit skips the code checks, and a step with no recorded or
  given landing branch refuses instead of assuming `dev`. Its pre-push checks become
  one make target its Git hook also runs, `make check-change` stays the complete
  closing check by running the engine's `pre-commit`, whose hook is the new `make
  check-repository`, and `make code-snapshot` stays a target of the repository's own
  that no skill names.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `change-workflow`: the configuration file, its check, and its fields' kinds; the
  hooks, their defaults, placeholders, and the engine's hook table; declared
  validation parts and their cleanup; the derived landing branch and remote; models
  per step; inert paths in place of `openspec/` and `docs/`; the invocation record;
  and what an adopting repository provides.
- `market-change-workflow`: this repository's configuration; the merge's default
  branch and the forbidden models removed.

## Non-Goals

- **Do not rework permissions beyond hook invocation.** Sandbox profiles,
  engine-held credentials, and post-step invariant checks are
  `sandbox-unattended-workflow-steps`'. This change moves only what is now a hook
  behind the engine.
- **Do not add skill extension points.** What the agent is told about one
  repository's validation failures or closeout parts is `add-skill-extension-points`'.
- **Do not ship language-specific defaults.** Comment hygiene and similar checks stay
  the repository's.
- **Do not bootstrap a repository's configuration.** Writing an adopting repository's
  first `workflow.toml` is a separate task.
- **Do not move the make fragment's targets.** The skills keep naming them for the
  owner; `extract-change-workflow-repository` owns the fragment.
- **Do not extract the engine, or change what any step is for.**

## Impact

- `scripts/change_workflow/`: a configuration module and its check; the `run`,
  `config`, `config load`, `config parts`, `check config`, `check change`, and
  `openspec` subcommands;
  `push`, `clone`, `review`, `find`, `next_step`, `records`, `history`, `hook`,
  `steps`, `harness`, `wrapper`, `log`, and `cli`, where constants become fields or
  derivations.
- `.agents/workflow.toml`, new, and this repository's `Makefile`: `pre-push`, the
  markers of `run-e2e` and `run-ci`, `dist-clean` folded into the parts,
  `check-repository` added and `check-change` running the engine's `pre-commit`;
  `scripts/hooks/pre-push`.
- `.agents/skills/change-*/SKILL.md`, which invoke hooks, `openspec`, and `config
  load` instead of this repository's targets and documents.
- `.claude/change-steps.toml`: models moved out, `run` and `openspec` rules added,
  validation's and archive cleanup's hook commands removed, the configuration denied.
- `scripts/check_change.py`, and the workflow's tests under `scripts/tests/`.
- `docs/agents/change-workflow.md`, and both capabilities' specifications, `README.md`,
  and `index.md`.

## Public interfaces changed

As `openspec/README.md`, "Change documentation requirements", and CW-c2tw require:

| Interface | Change | Compatible |
|---|---|---|
| `run` (with `run cleanup` and `--owed`), `config`, `config load`, `config parts`, `check config`, `check change`, `openspec` | new subcommands | yes |
| `.agents/workflow.toml` | a new public input, versioned by the engine's release | yes, as new |
| `hooks.pre-commit-functional`, `validation.parts`, `repository.protected-branches`, `models` | roles an adopter must now provide | no: minor while the major version is 0 |
| `clone-remove` | judges the merge against the recorded landing branch; `--base` for a clone with none recorded | no (minor) for a clone made before it |
| `find --json`'s `base`; the log line's `invoked` | optional fields added | yes |
| The step table's `models` and `[orchestrator]` | removed from a provisional schema | allowed |
| A repository forbidding models (CW-zq4h) | removed | no (minor) |
| The merge's fallback to the repository's default branch (CW-hdxi) | a step with no landing branch refuses | no (minor) |
| `CHANGE_WORKFLOW_MERGE_FROM`, `CHANGE_WORKFLOW_REVIEW_BASE` | removed from the fragment | outside the surface |

## Dependencies and Related Changes

- **`specify-change-workflow-and-engine`**, archived: this change designs against its
  inventory of repository assumptions and its tiered surface.
- **`sandbox-unattended-workflow-steps`** builds on the configuration file and the
  engine's hook table; it makes the configuration's protection an invariant check and
  replaces the step table's remaining grants.
- **`add-skill-extension-points`** names its addenda in the same file; what runs is
  this change's, what the agent is told about it is that change's.
- **`extract-change-workflow-repository`** decides whether decision destinations and
  the spec index move into the engine's defaults, and ships the fragment.
- **`layer-engineering-guidance`** may replace `[load]`'s paths with tags.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` (`spec.md`, `index.md`,
      `README.md`) and `market-change-workflow` (`spec.md`, `index.md`, `README.md`)
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/agents/change-workflow.md` changes with it. The lesser goal's gap "No single
file states what the workflow assumes about a repository" in
`openspec/changes/README.md` is owned by this change and closes with it.

### Knowledge to promote

- P1–P4, the owner's principles: `openspec/specs/change-workflow/README.md`, in a
  section describing the configuration.
- D1: CW-f3qk; `openspec/specs/change-workflow/README.md`, the configuration's section
  and "What an adopting repository provides", what stays fixed in the engine among its
  current limits.
- D2: CW-b2xr, CW-k9vd; `openspec/specs/change-workflow/README.md`, the hooks.
- D3: CW-g4oz, CW-zkhs, CW-ikmm, CW-o6kc; `openspec/specs/change-workflow/README.md`,
  "Validation observes a committed slice"; `market-change-workflow/README.md`,
  "Validation's parts".
- D4: CW-s3ju, CW-hdxi, CW-59c7, CW-xx5f; `openspec/specs/change-workflow/README.md`, "A change
  is worked in its own clone" and "Pushing is guarded, never repaired".
- D5: CW-ebmo, CW-zq4h, CW-w2ld; `openspec/specs/change-workflow/README.md`, "Models
  are policy, with no same-vendor fallback"; MCW-y37w removed.
- D6: CW-l7hn; `openspec/specs/change-workflow/README.md`, the configuration's section.
- D7: CW-n7ra, CW-e1sg, CW-trdu, CW-j1ab, CW-gqav, CW-8tdv, CW-tnp6;
  `openspec/specs/change-workflow/README.md`, the configuration's section.
- D8: CW-v2dq; `openspec/specs/change-workflow/README.md`, the hooks.
- D9: CW-u4pc, CW-y6mj; `openspec/specs/change-workflow/README.md`, "Restrictions bind
  unattended runs only".
- D10: CW-x9bt, CW-q5fy, CW-8npg; `openspec/specs/change-workflow/README.md`, "Validation
  observes a committed slice" and "A step run's life".
- D11: CW-c8lw, CW-i2we, MCW-r4tx; `openspec/specs/change-workflow/README.md`, the
  hooks; `docs/agents/change-workflow.md`, "Skills" and its description of `make
  check-change`.
- D12: CW-t5hz; `openspec/specs/change-workflow/README.md`, the configuration's
  section.
- D13: CW-w8ne; `openspec/specs/change-workflow/README.md`, the configuration's
  section.
- D14: CW-z5me; `openspec/specs/change-workflow/README.md`, "Restrictions bind
  unattended runs only".
- D15: `openspec/specs/change-workflow/README.md`, the configuration's section.
- D16: CW-o6kc, CW-l7hn, CW-i2we; `openspec/specs/change-workflow/README.md`,
  "Interfaces are tiered"; `docs/agents/change-workflow.md`, "The engine's command".
- D17: CW-h8vm; `docs/agents/change-workflow.md`, "Skills".
- D18: CW-m4ps, MCW-5tgp; both capabilities' `README.md`, their role and provision
  tables; `scripts/tests/test_change_workflow_assumptions.py`.
- D19: no permanent destination — the compatibility statement is this proposal's,
  as CW-c2tw requires until the engine is versioned.
- D20: MCW-r4tx, MCW-k3vy; `openspec/specs/market-change-workflow/README.md`, "How this
  repository provides the workflow's roles" and "Branches, models, and the clone's
  bootstrap"; MCW-ca51 removed.
- D21: no permanent destination — the implementation cadence is change history.
