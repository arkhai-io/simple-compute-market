# Design: specify the change workflow and its engine

Status: design phase. Not planned. The direction under "Starting direction" came
from the owner's discussion that opened the lesser goal, and design confirms or
revises it. Everything under "Open questions" is undecided.

## Context

- **Engine package.** `scripts/change_workflow/` holds one concern per module,
  on the standard library alone. Its `__init__.py` lists them: graph, diagram,
  outcome, log, records, steps, stream, harness, cost, running, wrapper, review,
  watch, convert, and cli. `scripts/run_change_step.py` runs its command line.
- **Engine scripts outside the package.**
  - `scripts/change_next_step.py` (about 1,500 lines) is the next-step
    computation. It interprets `graph`, and the orchestrator and `make
    change-next` call it.
  - `scripts/change_clone.py`, `scripts/round_view.py`,
    `scripts/change_history.py`, `scripts/find_change.py`, and
    `scripts/change_cost.py` manage clones, round views, history, record
    lookup, and cost reports.
  - `scripts/change_namespace.py` derives a change's Helm validation namespace
    and image tags. It serves this repository's validation, not the engine in
    general.
- **Step table.** `scripts/change_workflow/steps.py` reads
  `.claude/change-steps.toml`. That file holds each step's skill, permission
  rules in Claude Code's syntax, and models.
- **Outcome and log.** An outcome conforms to `.agents/change-outcome.schema.json`
  and names a target in the graph. `log` is the workflow log's only writer.
  `convert` brings older records into the log's format on the owner's
  confirmation. That is a precedent for migrating a record format.
- **Harnesses.** `harness` runs a step as headless Claude Code (`claude -p`) and
  a review in Codex's read-only sandbox (`codex exec`) first.
- **Entry points.** The make targets in the `Makefile` (`design`, `plan`,
  `implement`, `review`, `triage`, `validate`, `merge`, `closeout`,
  `archive-cleanup`, `orchestrate`, `change-next`, `change-clone`,
  `round-view`, and others) call the scripts above.
- **Contract and companion.** `openspec/specs/change-workflow/spec.md` states the
  workflow's requirements. `openspec/specs/change-workflow/architecture.md`
  explains its design: skills from one source, headless runs, routing as code,
  restrictions on unattended runs, clones, history, and so on. It explains the
  workflow's behaviour, not the engine's internal structure.
- **The specification as it stands.** `change-workflow`'s specification has 22
  requirements in about 1,900 lines, added as this repository needed each. Some
  hold for any repository, such as "The next step is computed from the files" and
  "Guarded push of a change branch". Others name this repository's own setup,
  such as "Each Helm validation is isolated in its change's namespace".
- **Diagrams.** The repository keeps each diagram as a `.drawio` source with a
  rendered `.svg` in `docs/development/diagrams/`. The workflow has one,
  `change-workflow-graph`, which the architecture companion embeds. `make
  change-graph` (`scripts/change_workflow/diagram.py`) reports where it departs
  from the graph table, so the diagram is held to the code.
- **Architecture checks.** `docs/development/ARCHITECTURE.toml` skips `scripts/`,
  so no layer, scope, or kind rule applies to the engine.

## Starting direction

- **Review before parametrizing.** The boundary between the engine and the
  repository is drawn inside this repository before anything is extracted, and
  this review is the first step of drawing it.
- **The public surface** comprises:
  - the repository configuration schema;
  - capabilities;
  - extension points;
  - the record and outcome formats.

  The configuration, capabilities, and extension points do not exist yet. This
  change defines the surface as it stands today, and the later changes extend it.
- **Lenient versioning until a major release.** Until a major release, changes
  bump minor and patch versions, as this repository's own releases do. Defining
  what would be breaking still matters now, so that a major release has a
  meaning when it comes.
- **Repositories call the engine only as a command.** A repository never imports
  the engine. That lets the engine stay in Python while adopting repositories
  use any language.
- **Skills are invoked by name.** The engine starts a step by naming its skill in
  the harness, as it does today. It does not compose the step's prompt itself.

## Open questions

- **How the specification is restructured.** The options are reorganizing the
  existing requirements under a new outline, or rewriting the specification
  against that outline. Either way, every existing requirement has to be accounted
  for: kept, merged, moved, or deliberately dropped. A trace from old requirement
  to new is the obvious control. Whether the trace lives in this change's design
  or in the delta itself is undecided.
- **Where this repository's own workflow requirements go.** The Helm validation
  namespace, the end-to-end pipeline, the capacity record, and similar
  requirements hold only here.
  - **Option 1:** they stay in `change-workflow`, marked as specific to this
    repository.
  - **Option 2:** they move to a capability of this repository's own that
    extends the workflow.

  Option 2 previews what every adopting repository will need once the workflow
  is extracted.
- **Which diagrams, and which are held to code.** Beyond the four the proposal
  names, design may find others are needed, such as the orchestrator's relay
  loop or a round's review, validation, and triage join. The graph diagram is
  checked against the graph table. Whether other diagrams get a similar check, or
  are maintained by review alone, depends on whether each has a single source in
  the code to check against.
- **Where the engine's documentation lives.**
  - **Option 1:** `change-workflow`'s architecture companion grows a section on
    the engine.
  - **Option 2:** the engine becomes its own capability with its own
    specification and companion. `change-workflow` then states what the steps
    do, and the engine capability states how they are run and recorded.

  Option 2 matches the two audiences: a repository adopting the workflow reads
  the process, and someone changing the engine reads the tool. It also gives
  the extracted repository two clear documents.
- **Which standalone scripts belong to the engine.** The candidates for the
  engine are the next-step computation, clones, round views, history, record
  lookup, and cost. `change_namespace` belongs with this repository's Helm
  validation. Whether the engine's parts are consolidated under one package and
  one command line in this change, or only classified here and moved at
  extraction, is undecided.
- **Which commands are public.** Candidates:
  - `run_change_step.py`'s subcommands: `record`, which an interactive step
    calls, and `log`;
  - the next-step computation;
  - the make targets.

  If the make targets are only this repository's shims over the engine, they
  are not part of its surface.
- **Whether the graph is public.** The node and exit vocabulary appears in every
  outcome, so it is at least readable surface. Whether a repository may ever
  extend the graph, or only the steps inside it through extension points, bears
  on how far the graph is public.
- **Whether records carry a format version now.** A change spans engine upgrades,
  and `convert` already migrates older records. Recording a format version in
  the log may belong here, as part of defining the formats, or at extraction,
  with the engine's own version.
- **How far the review fixes what it finds.** Fixes that block a clean surface
  definition land here. Whether other structural findings land here or are
  recorded for later changes depends on what the review finds and on the
  owner's judgement of each.
- **Where the assumptions inventory is kept.** It is input to the capability
  contract change. It could live in this change's `design.md` and travel by
  reference, or become part of the engine's permanent documentation, as the
  list of what an adopting repository must provide until capabilities replace
  it.
