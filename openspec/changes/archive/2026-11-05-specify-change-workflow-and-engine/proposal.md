## Why

The change workflow's engine runs every step of an OpenSpec change. It holds
each step's rules, runs the harness, keeps the workflow log, computes the next
step, and manages each change's clone. It is meant to become a separately
versioned tool that other repositories adopt. Nothing describes it as one.

The `change-workflow` specification and its architecture companion describe the
workflow as a process inside this repository: what each step does, when the
owner is asked, and how a change moves. Neither describes the engine itself:

- its parts and the boundaries between them;
- the data that flows from the step table through the wrapper, the harness, the
  event stream, and the log to the next-step computation;
- which of its interfaces another party may rely on.

The process specification has its own problems as a document another repository
would adopt. It grew one requirement at a time. It mixes rules for any adopting
repository with rules for this one. Its only diagram is the graph.

The engine is also split across places nobody has reconciled. Its package,
`scripts/change_workflow/`, documents its own modules. The next-step computation
(`change_next_step.py`), clones (`change_clone.py`), round views
(`round_view.py`), history (`change_history.py`), record lookup
(`find_change.py`), and cost reporting (`change_cost.py`) sit beside it in
`scripts/` as standalone scripts. Validation namespaces
(`scripts/change_namespace.py`) are specific to this repository's Helm
validation, and nothing marks that difference. `scripts/` is outside the
architecture checks (`docs/development/ARCHITECTURE.toml` skips it), so no layer
or scope rule governs these files.

With no defined public surface, a breaking change to the engine cannot be told
apart from an internal one. Every later step toward a reusable workflow depends
on that distinction: the capability contract, extension points, sandboxed
permissions, extraction, and harness adapters. They should parametrize an
engine that has been described in full, not one whose assumptions are still
implicit.

## What Changes

- **Specify the workflow itself.** Write the specification a reader needs to
  understand the workflow without knowing this repository: its phases and steps,
  the owner's touchpoints, the graph, the records, and the engine that runs them.
  `change-workflow`'s specification grew one requirement at a time as this
  repository needed each (24 requirements, about 1,900 lines). It is reviewed and
  restructured into a specification of the workflow as a whole. Requirements
  that hold only for this repository, such as Helm validation in a change's own
  namespace, are separated from those that hold for any adopting repository.
- **Document the workflow's architecture.** Cover both the workflow and its
  engine: the conceptual model, the parts and how they relate, where each piece
  of state lives, the trade-offs behind the design, and its current limits.
- **Draw the diagrams the documents need.** Each is a `.drawio` source beside its
  rendered `.svg`, in `openspec/specs/change-workflow/diagrams/`, embedded in the
  capability's `README.md`:
  - **the engine's parts**, with what each reads and writes;
  - **the life of a step run**, unattended and interactive, from its start
    through waiting and resuming to its recorded outcome;
  - **where a change's state lives**: the checkout, the change's clone, the
    owner's workspace, and the session transcripts;
  - **the existing graph diagram**, kept current.
- **Review the engine's architecture.** Map its parts, the state each holds and
  where, and the flow of a step from start to recorded outcome. Record what the
  review finds. Fix the structural defects that stand in the way of a clean
  surface definition; leave the rest to later changes.
- **Document the engine as a tool.** The documentation is written so that a
  reader who has never seen this repository can understand how the engine works
  and how its parts relate.
- **Define the engine's public surface.** Classify each interface as public,
  provisional, or internal:
  - the commands a repository or a session invokes;
  - the step table's schema;
  - the outcome schema;
  - the workflow log's line format;
  - the layout and naming of a change's records;
  - the graph's node and exit vocabulary;
  - the contract by which a step is started and records its outcome.

  State which changes to a public interface are breaking.
- **Inventory the engine's assumptions about the repository it runs in.** List
  every make target, path, document, and tool the engine and the skills assume,
  so the capability contract starts from a complete list rather than discovering
  assumptions one at a time. The inventory is two-sided: the roles an adopting
  repository provides, in `change-workflow`, and how this repository provides
  each, in `market-change-workflow`. A test holds it complete for the make targets
  and repository paths the skills, the step table, and the make fragment name; the
  engine's own assumptions — its modules' paths, the bootstrap command, remotes,
  environment variables, and the tools it invokes — are listed too, and maintained
  by review.
- **Consolidate the engine behind one command.** The engine's standalone scripts
  move into `scripts/change_workflow/`, reached through one executable,
  `scripts/change-workflow`; the Makefile's entry logic moves into its `start`
  subcommand, and the workflow's make targets into a fragment the root `Makefile`
  includes. This repository's scripts call the command rather than import the
  engine. Behaviour is unchanged.
- **Organize the specification by an index of requirement ids.** Each requirement
  of the two workflow capabilities carries a random, never-reused id at the front
  of its name; an `index.md` organizes them, a check holds the index to the
  specification, and the companion `architecture.md` becomes the capability's
  `README.md`, the human-readable description with its diagrams.

## Capabilities

### New Capabilities

- `market-change-workflow`: how this repository runs the change workflow — its
  validation parts, the isolation of each change's Helm validation, its protected
  branches and other workflow values, and how it provides each role the workflow
  asks of an adopting repository.

### Modified Capabilities

- `change-workflow`: rewritten as a specification of the workflow as a whole,
  organized by its index, with this repository's requirements moved out. It gains
  requirements for the engine's command, the tiers of its interfaces, the record
  set's format version, compatibility, the graph's closed vocabulary, and the roles
  an adopting repository provides.
- `planning-governance`: a capability may organize its documentation by an index
  of requirement ids, and its companion is then its `README.md`.

## Non-Goals

- Do not introduce the capability contract, the repository configuration file,
  extension points, sandbox profiles, or new harnesses. Each is its own change;
  this one gives them a described engine to start from.
- Do not extract the engine from this repository or assign it a version.
- Do not change what any step does, or the order of steps, except where a fix the
  review justifies requires it, and only with the owner's agreement in design.
- Do not decide the guidance layering; this change touches guidance only where it
  documents the engine or states a documentation convention the owner set.
- Do not convert the other capabilities to the indexed organization, or move
  their material out of `ARCHITECTURE.md`; that is `index-capability-documentation`'s.
- Do not make the graph extensible by an adopting repository.

## Impact

- `scripts/change_workflow/` gains the engine's standalone scripts as modules,
  the command `scripts/change-workflow`, and the make fragment `workflow.mk`;
  `change_next_step.py`, `change_clone.py`, `round_view.py`, `change_history.py`,
  `find_change.py`, `change_cost.py`, `check_change_index.py`, `check_tasks.py`,
  `check_push_ready.py`, `check_agent_skills.py`, `post_compaction_context.py`,
  and `run_change_step.py` are removed.
- The root `Makefile`, which includes the fragment; `.claude/change-steps.toml`,
  whose rules name the command and which gains an `[orchestrator]` row;
  `.claude/settings.json`'s hook; `scripts/completions/make-change.bash`.
- `scripts/check_change.py`, `check_doc_citations.py`, `validate_slice.py`, and
  `validate_parallel.py`, which call the command instead of importing the engine.
- Every skill under `.agents/skills/change-*` that names an engine script, and
  the closeout, design, and review skills for the companion's name and the index.
- `.agents/change-outcome.schema.json`, whose `$id` states its format.
- `openspec/specs/change-workflow/` (rewritten, with `README.md`, `index.md`, and
  `diagrams/`), `openspec/specs/market-change-workflow/` (new),
  `openspec/specs/planning-governance/spec.md`, and `openspec/specs/README.md`.
- `AGENTS.md`, `openspec/README.md`, and `openspec/config.yaml`, for the
  companion's name, the indexed organization, and the diagram rule.
- `docs/agents/change-workflow.md`, for the engine's commands.
- The rows of `remove-workflow-log-conversion`, `workflow-round-review-without-merges`,
  and `shorten-long-requirements` in `openspec/changes/README.md`, whose `Notes`
  say this change rewrites `change-workflow`.
- The workflow's tests under `scripts/tests/`, which move with the package.

## Dependencies and Related Changes

- Independent: nothing must land first.
- First change of the lesser goal "Make the change workflow a tool any repository
  can adopt" in `openspec/changes/README.md`. The changes for that goal's other
  gaps design against the surface and the assumptions inventory this change
  produces.
- `remove-workflow-log-conversion`, `workflow-round-review-without-merges`, and
  `shorten-long-requirements` also edit `change-workflow`; none waits on this
  change or it on them (design D11).
- `index-capability-documentation`, not yet proposed, converts the other
  capabilities to this change's organization and merges alongside this branch.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` (specification,
      `README.md` replacing `architecture.md`, `index.md`, diagrams) and
      `planning-governance`
- [x] New subsystem specification: `market-change-workflow`
- [ ] No permanent documentation change

The lesser goal's gap "The engine is documented as this repository's contract,
not as a tool in its own right" in `openspec/changes/README.md` is owned by this
change and closes with it.

### Knowledge to promote

Provisional destinations; planning and review confirm or move them.

- The workflow as a whole, the engine's command, its interface tiers, the record
  set's format, compatibility, the graph's closed vocabulary, and the roles an
  adopting repository provides (D3–D10, D13) → `openspec/specs/change-workflow/spec.md`,
  through the deltas, and its `README.md` for the rationale and "Current limits".
- This repository's validation parts, Helm validation namespace, workflow values,
  and provision of each role (D3, D13) → `openspec/specs/market-change-workflow/spec.md`
  and its `README.md`; the principle that this repository is the workflow's first
  adopter → that `README.md`.
- The engine's parts, a step run's life, and where a change's state lives (D12) →
  diagrams in `openspec/specs/change-workflow/diagrams/`, embedded in its
  `README.md`; the graph diagram moves there from `docs/development/diagrams/`.
- The indexed organization of a capability's documentation, the id rule, and the
  index check (D15) → `openspec/specs/planning-governance/spec.md` through its
  delta, and `openspec/README.md#capability-documentation-pattern`, with
  `openspec/specs/README.md`; the companion's name → `AGENTS.md`'s documentation
  ownership and `openspec/README.md`.
- Documentation follows the specification, and a component's `README.md` is its
  most human-readable document → `openspec/README.md#capability-documentation-pattern`.
- A diagram is held to code only when generated deterministically from a
  well-structured source → `AGENTS.md`, beside the other documentation
  conventions.
- The engine's promise is its command; conveniences ship without a compatibility
  promise (D6, D9) → `change-workflow`'s surface requirements.
- Each workflow change's proposal names the public interfaces it changes and
  whether each change is compatible (D9) → `change-workflow`'s compatibility
  requirement, and the proposal guidance in `openspec/README.md#change-documentation-requirements`.
