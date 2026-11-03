## Why

The guidance an agent loads before working here is spread across `AGENTS.md`,
`docs/development/` (`ARCHITECTURE.md`, `TESTING.md`,
`DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`, `VALIDATION_RUNBOOK.md`,
`RELEASING.md`), `openspec/README.md`, `docs/agents/`, and `docs/prompts/`. That
is about 7,000 lines, and each document mixes three kinds of material:

- **Engineering guidance that would hold in any repository.** How to write
  comments and docstrings, the levels of testing and what each may prove, how
  configuration is resolved, how documentation ownership divides between specs,
  architecture documents, and change records.
- **Rules of the change workflow.** The discuss, plan, and implement working
  model; the closeout parts that concern the workflow, such as promotion and
  archival; and how a change moves.
- **This repository's own architecture and examples.** Package layers, the
  architecture exception table, deployment topology, and testing sections such as
  "Pool Offering-Mode Enforcement" and "Payment Receipts in Tests".

The mixing works against every party:

- **A repository adopting the workflow** cannot take the general guidance without
  this repository's specifics coming with it.
- **An agent working here** loads all of it whatever the task.
- **A general rule stated through a market example** reads as a market rule.

The guidance is meant to become shared and tagged: engineering guidance
maintained once and selected per repository, workflow guidance carried with the
workflow, and repository guidance staying here. None of that can happen until
the material is separated. The owner has decided that organizing it comes first,
before deciding where the shared layers live or how a permanent document cites
guidance held elsewhere.

## What Changes

- **Inventory every section of the guidance.** For each section, record its
  layer (engineering, workflow, or repository), its tags, and a one-line reason.
  The inventory is worked through with the owner, section by section, in design.
- **Split mixed sections.** A general rule illustrated with this repository's
  example moves to the engineering layer with a neutral example. This
  repository's example stays as a local illustration in the repository layer.
- **Restructure the documents in place, by layer.** The guidance is reorganized
  within this repository into documents per layer, each section tagged from a
  controlled vocabulary. Every citation of a moved section is updated. The
  repository's documents keep only what is specific to it.
- **State the precedence rule.** Repository guidance may narrow or override
  engineering guidance only in an explicit deviations section, so a reader can see
  where this repository departs from the shared standard.
- **Rewrite `AGENTS.md`.** It says which layers apply and where each lives, then
  carries only this repository's own rules.
- **Classify the checks that enforce guidance.** `make check-comment-hygiene`,
  `make check-doc-citations`, and the architecture checks enforce rules from
  particular layers. Each is classified with the rule it enforces, so it can
  later travel with that rule.

## Capabilities

### New Capabilities

- None expected. Guidance documents are not subsystem behaviour.

### Modified Capabilities

- `planning-governance`, if the closeout parts or documentation ownership rules
  it governs change wording or location.
- `change-workflow`, if workflow guidance moves out of `openspec/README.md` into
  the workflow's own documents.

## Non-Goals

- **Do not move guidance out of this repository.** Extracting the engineering
  layer into its own home is a later change.
- **Do not decide how a permanent document cites guidance held outside its
  repository.** That is decided when the guidance moves.
- **Do not build the loader.** Selecting packs per repository in the workflow's
  configuration, steps declaring the topics they always load, and loading
  guidance by tag are a later change. This change fixes the tag vocabulary and
  applies it, so that work starts from tagged material.
- **Do not change what the guidance says** beyond what a split requires: a
  neutral example, a restated scope. Changing a rule is its own decision.

## Impact

- `AGENTS.md`, every document under `docs/development/` named above,
  `openspec/README.md`, `docs/agents/`, and `docs/prompts/`.
- New layered guidance documents within this repository, at locations decided in
  design.
- Every permanent document and skill that cites a moved section, including the
  `change-*` skills' instructions to load the guidance.
- `scripts/check_comment_hygiene.py`, `scripts/check_doc_citations.py`, and the
  architecture checks, for classification only.

## Dependencies and Related Changes

- **Independent:** nothing must land first. The design session can start now.
- **`specify-change-workflow-and-engine`** owns the workflow's specification and
  architecture. Workflow-layer guidance found here moves toward those documents,
  so the two coordinate on where workflow rules live.
- **`add-skill-extension-points`** moves this repository's closeout parts into
  addenda. This change moves the closeout parts that are engineering concerns
  into the engineering layer. Between them, the eleven parts are distributed by
  layer.
- **Later guidance changes, still to be opened,** build on the inventory and tags:
  the loader, moving the engineering layer out, and the citation scheme.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification, unless the closeout parts or
      documentation ownership rules move (`planning-governance`, `change-workflow`)
- [ ] New subsystem specification
- [ ] No permanent documentation change

`AGENTS.md`, the documents under `docs/development/`, `openspec/README.md`,
`docs/agents/`, and `docs/prompts/` are restructured.

The lesser goal's gap "Guidance is not separated into engineering, workflow, and
repository layers" in `openspec/changes/README.md` is owned by this change for
its layering and tagging. Its loading and citation parts stay open for later
changes.

### Knowledge to promote

To be determined at design completion.
