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
(`scripts/change_next_step.py`), clones (`scripts/change_clone.py`), round views
(`scripts/round_view.py`), history (`scripts/change_history.py`), record lookup
(`scripts/find_change.py`), and cost reporting (`scripts/change_cost.py`) sit
beside it as standalone scripts. Validation namespaces
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
  repository needed each (22 requirements, about 1,900 lines). It is reviewed and
  restructured into a specification of the workflow as a whole. Requirements
  that hold only for this repository, such as Helm validation in a change's own
  namespace, are separated from those that hold for any adopting repository.
- **Document the workflow's architecture.** Cover both the workflow and its
  engine: the conceptual model, the parts and how they relate, where each piece
  of state lives, the trade-offs behind the design, and its current limits.
- **Draw the diagrams the documents need.** Follow the repository's convention: a
  `.drawio` source beside its rendered `.svg` in `docs/development/diagrams/`. At
  least the following:
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
- **Define the engine's public surface.** Classify each interface as public or
  internal:
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
  assumptions one at a time.

## Capabilities

### New Capabilities

- Possibly a capability for the engine as a tool, separate from `change-workflow`'s
  process. Possibly also a capability holding the requirements that are specific
  to this repository. Both are decided in design.

### Modified Capabilities

- `change-workflow`: restructured into a specification of the workflow as a
  whole. It gains requirements naming the engine's public surface and what counts
  as a breaking change to it.

## Non-Goals

- Do not introduce the capability contract, the repository configuration file,
  extension points, sandbox profiles, or new harnesses. Each is its own change;
  this one gives them a described engine to start from.
- Do not extract the engine from this repository or assign it a version.
- Do not change what any step does, or the order of steps, except where a fix the
  review justifies requires it, and only with the owner's agreement in design.
- Do not decide the guidance layering; this change touches guidance only where it
  documents the engine.

## Impact

- `scripts/change_workflow/` and the standalone workflow scripts beside it, for
  any restructuring the review justifies.
- `openspec/specs/change-workflow/spec.md` and `architecture.md`, and possibly a
  new capability's specification.
- `docs/development/diagrams/`, for the new diagrams and the graph diagram.
- `docs/agents/change-workflow.md`, where it describes the engine's commands.
- `.agents/change-outcome.schema.json` and `.claude/change-steps.toml`, as
  surfaces being classified, not changed.
- The workflow's tests under `scripts/tests/`.

## Dependencies and Related Changes

- Independent: nothing must land first.
- First change of the lesser goal "Make the change workflow a tool any repository
  can adopt" in `openspec/changes/README.md`. The changes for that goal's other
  gaps design against the surface and the assumptions inventory this change
  produces.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, specification and
      architecture companion
- [ ] New subsystem specification, if design separates the engine, or this
      repository's own workflow requirements, into a capability of its own
- [ ] No permanent documentation change

New diagrams go in `docs/development/diagrams/`, and the documents above embed
them.

The lesser goal's gap "The engine is documented as this repository's contract,
not as a tool in its own right" in `openspec/changes/README.md` is owned by this
change and closes with it.

### Knowledge to promote

To be determined at design completion.
