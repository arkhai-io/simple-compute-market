## Why

Each step of the workflow is one skill, a single `SKILL.md` under
`.agents/skills/`. The skills are written for this repository, and some of them
build this repository in:

- **`change-validate`** runs this repository's end-to-end pipeline, its CI
  workflows, and Helm validation in a change's own namespace and image tags.
- **`change-archive-cleanup`** records the validation capacity figure and tears
  down the validation namespace and images.
- **The closeout task's eleven parts**, which `change-closeout` works through,
  mix parts any repository would want with parts specific to this one. Comment
  hygiene and citation resolution are general; packaging and end-to-end pipeline
  evidence are local.

A skill can vary per repository today only by being edited. Once the skills are
shared across repositories, an edit for one repository is an edit for all, and a
repository-local copy is a fork that stops receiving improvements. Neither is
acceptable. Repositories need a way to add what is theirs while keeping the
common baseline every repository shares.

The capability contract covers *what runs*: each repository supplies the
commands. It does not cover *what the agent is told*: what to check, what
evidence to record, how to diagnose a failure peculiar to a repository's
pipeline. That is the gap this change fills.

## What Changes

- **Named extension points.** Each skill declares named slots where a
  repository's material belongs. Examples: closeout's repository-specific parts,
  validation's parts and their diagnosis notes, archive cleanup's teardown. A
  slot states what an addendum to it may contain.
- **Repository addenda, named in the workflow's configuration.** A repository
  fills a slot with an addendum, and the workflow's configuration file names it.
  The skill reads the addendum for each of its slots when it runs, so the base
  skill stays the one source every repository shares.
- **Addenda add or narrow, never silently remove.** An addendum may add
  obligations, or narrow one the baseline leaves open. Removing a baseline
  obligation needs an explicit, visible deviation entry, so a reviewer can see
  where a repository departs from the baseline.
- **A check holds addenda to slots.** The repository's skill check grows to fail
  in three cases: an addendum names a slot that does not exist, a configured
  addendum is missing, or a skill reads a slot it does not declare. A renamed
  slot then fails loudly instead of silently dropping a repository's material.
- **This repository's specifics move into its own addenda.** The Helm, pipeline,
  capacity, and packaging material leaves the base skills for this repository's
  addenda. The base skills then describe the workflow for any repository, and
  this repository's behaviour is unchanged.

## Capabilities

### New Capabilities

- None expected.

### Modified Capabilities

- `change-workflow`, or the engine capability if `specify-change-workflow-and-engine`
  creates one: extension points, addenda, deviations, and the check.
  "Harness-neutral agent skills" gains the rule that a skill varies per
  repository only through its slots.
- This repository's own workflow requirements, wherever
  `specify-change-workflow-and-engine` places them. They are the first set of
  addenda.

## Non-Goals

- **Do not allow a repository to replace a skill.** A full override loses the
  baseline. A free-form addendum loaded beside the skill could contradict it with
  nothing to say so. Only named slots are supported.
- **Do not defend the guidance against hostile addenda.** An addendum is
  instruction text in the agent's context, and one could ask the agent to reveal
  or write out the guidance it has loaded. That matters once untrusted parties
  supply addenda. It is designed with the hosted runner's access model, not here.
- **Do not change what runs.** Commands are the capability contract's. An addendum
  tells the agent what to do with a capability's result; it does not supply the
  command.
- **Do not change the OpenSpec skills** (`openspec-*`). They are maintained with
  the OpenSpec tool.

## Impact

- `.agents/skills/change-*/SKILL.md`, which declare their slots and read their
  addenda. `change-validate`, `change-archive-cleanup`, and `change-closeout`
  lose this repository's specifics.
- A set of addenda for this repository, and their entries in the workflow's
  configuration file.
- `openspec/README.md`'s "Plan closeout requirements", whose repository-specific
  parts become this repository's closeout addendum.
- `scripts/check_agent_skills.py`, for the slot check.
- The workflow's specification, architecture companion, and
  `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- **`specify-change-workflow-and-engine` (design).** That change separates the
  workflow's general requirements from this repository's, and that split decides
  which material becomes an addendum. Its inventory of repository assumptions
  lists the candidates.
- **`add-workflow-capability-contract`.** Addenda are named in the configuration
  file that change creates. The boundary between a capability (what runs) and an
  addendum (what the agent is told about it) is drawn with it. Gates
  implementation only.
- **The guidance layering change, still to be opened,** moves the closeout parts
  that are company engineering concerns into the guidance layer. This change
  moves only this repository's parts out of the baseline.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, or the engine
      capability `specify-change-workflow-and-engine` creates, specification and
      architecture companion
- [ ] New subsystem specification
- [ ] No permanent documentation change

`openspec/README.md` and `docs/agents/change-workflow.md` change with it.

The lesser goal's gap "A skill can vary per repository only by being edited" in
`openspec/changes/README.md` is owned by this change and closes with it.

### Knowledge to promote

To be determined at design completion.
