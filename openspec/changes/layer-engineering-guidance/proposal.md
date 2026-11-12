## Why

The guidance an agent loads before working here is spread across `AGENTS.md`,
`docs/development/` (`ARCHITECTURE.md`, `TESTING.md`,
`DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`, `VALIDATION_RUNBOOK.md`,
`RELEASING.md`), `openspec/README.md`, and `docs/agents/`. That is about 8,700
lines, and each document mixes three kinds of material:

- **Engineering guidance that would hold in any repository.** How to write
  comments and docstrings, the levels of testing and what each may prove, how
  configuration is resolved, that permanent documents describe the current system.
- **Rules of the change workflow.** The discuss, plan, and implement working
  model; OpenSpec's division between specifications, companions, and changes; the
  closeout parts; how a change moves.
- **This repository's own architecture and examples.** Package layers, the
  architecture exception table, deployment topology, and testing sections such as
  "Pool Offering-Mode Enforcement" and "Payment Receipts in Tests".

The mixing works against every party:

- **A repository adopting the workflow** cannot take the general guidance without
  this repository's specifics coming with it, and
  `extract-change-workflow-repository` cannot tell which guidance is the workflow's.
- **An agent working here** reads 5,669 lines at every step through `load.common`,
  most of `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md` being market material the
  step never uses. Steps already declare what they load, but only by whole
  document.
- **A general rule stated through a market example** reads as a market rule.

The guidance is meant to become shared and tagged: engineering guidance
maintained once and selected per repository, workflow guidance carried with the
workflow, and repository guidance staying here, beside the systems it describes.
None of that can happen until the material is separated. Organizing it comes
first, before deciding where the shared layers live or how a permanent document
cites guidance held elsewhere.

## What Changes

- **Three layers, assigned by a test.** Engineering guidance holds without the
  workflow or OpenSpec; workflow guidance holds in any adopting repository and
  names nothing of one; repository guidance names this repository. A lower layer
  never links to a higher one.
- **An inventory, made in implementation.** Every section gets a layer, tags, a
  destination, and a reason, with ambiguous rows flagged; the owner corrects it
  before any text moves.
- **Shared guidance in `docs/guidance/`.** Engineering and workflow guidance move
  into files under `docs/guidance/engineering/` and `docs/guidance/workflow/`,
  general rules given neutral examples. The directories are organization for
  people; a file's frontmatter tags carry its layer, topics, and tools, drawn from
  each layer's vocabulary table.
- **Repository guidance beside its system.** A section that pertains to one
  capability moves beside it, into `openspec/specs/<capability>/`; guidance spanning
  several systems stays in the repository's cross-system documents. A step reads a
  capability's guidance wherever it reads its specification.
- **Exceptions declared beside what they apply to.** A repository's selection of a
  case shared guidance leaves open, or override of one of its rules, is a row in an
  exceptions table beside the component it applies to, or in `AGENTS.md` when it
  spans several systems.
- **Engineering guidance for private and public repositories.** What may enter a
  repository is described for both; this repository applies the public case.
- **The closeout parts by layer.** The workflow's parts move to
  `docs/guidance/workflow/closeout.md`, cited by name; this repository's parts —
  roadmap currency, packaging, pipeline evidence — stay in its own guide. A new
  workflow part, guidance placement, checks and fixes where promoted guidance sits.
- **`AGENTS.md` rewritten** as the entry: the layers and where each lives, this
  repository's own rules, its tags, and its multi-system exceptions.
- **`make check-guidance`.** It holds the tags, the vocabulary, the exception
  tables, the link direction, and the anchors of links into guidance, and lists the
  guidance set; `make check-repository` calls it.
- **`[load]` may name a directory**, so `load.common` names `docs/guidance/` once.
- **The checks are classified.** Every check enforcing guidance is recorded with
  the rule it enforces and that rule's layer.

## Capabilities

### New Capabilities

- None. Guidance documents are not subsystem behaviour.

### Modified Capabilities

- `change-workflow`: the layer tag, the link direction, placement beside the
  system, exceptions, directories carrying no meaning, capability guidance read
  with its capability (added); a `[load]` entry naming a directory (CW-l7hn,
  modified).
- `market-change-workflow`: the closing checks include the guidance check
  (MCW-c4ek, modified).

## Workflow interfaces changed

As `openspec/README.md`'s change documentation requirements ask:

- **`[load]`** — an entry may name a directory, expanded to its Markdown files in
  sorted order. Compatible: every existing configuration resolves as before.
- **`config load <step>`** — prints the expanded list. Compatible: its output is
  still one path per line.
- **The skills `change-design`, `change-plan`, `change-implement`,
  `change-review`, and `change-closeout`** — read the guidance files in a
  capability's directory beside its specification and companion, and closeout gains
  the guidance placement part. Compatible: no argument form or outcome changes.

## Non-Goals

- **Do not move guidance out of this repository.** Extracting a layer is a later
  change.
- **Do not decide how a permanent document cites guidance held outside its
  repository.** That is decided when the guidance moves.
- **Do not build the loader.** Selecting guidance by tag, per-step topics, and
  per-task selection are a later change. Letting `[load]` name a directory resolves
  paths and selects nothing.
- **Do not remove the skills' restatements of guidance.** The inventory lists them
  for the loader change.
- **Do not change what the guidance says** beyond what a split requires: a neutral
  example, a restated scope. The one exception is engineering guidance's
  description of what a private repository may hold.
- **Do not touch `docs/prompts/`.** The prompts are deprecated and stay outside the
  guidance set.

## Impact

- `AGENTS.md`, `openspec/README.md`, every document under `docs/development/`
  named above, and `docs/agents/`.
- New guidance files under `docs/guidance/` and under `openspec/specs/<capability>/`.
- Every permanent document and skill that cites a moved section, including about 74
  citations of the closeout parts.
- `.agents/workflow.toml` (`load.common`), `scripts/change_workflow/config.py` and
  its tests (directory entries).
- `scripts/check_guidance.py` and its tests, and the `Makefile`'s `check-guidance`
  and `check-repository`.
- `.agents/skills/change-{design,plan,implement,review,closeout}/SKILL.md`.
- `openspec/specs/market-change-workflow/README.md`, for the classification of the
  checks.

## Dependencies and Related Changes

- **Independent:** nothing must land first.
- **`specify-change-workflow-and-engine`** (archived) created `change-workflow` and
  `market-change-workflow`; workflow guidance's normative rules join the former,
  this repository's the latter.
- **`add-workflow-capability-contract`** (archived) created `[load]` and left
  loading by tag to this change's vocabulary.
- **`add-skill-extension-points`** depends on this change for its design: it builds
  its closeout slot on the closeout list this change settles.
- **`extract-change-workflow-repository`** depends on this change for its design:
  it moves the files tagged `workflow`.
- **Later guidance changes, still to be opened,** build on the inventory and tags:
  the loader, moving the engineering layer out, and the citation scheme.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`, which loses its engineering rules
- [x] Existing subsystem specification: `change-workflow` and
      `market-change-workflow`, with their `README.md` and `index.md`;
      `planning-governance`'s Evidence section
- [ ] New subsystem specification
- [ ] No permanent documentation change

`AGENTS.md`, the documents under `docs/development/`, `openspec/README.md`, and
`docs/agents/` are restructured, and `docs/guidance/` is created.

The lesser goal's gap "Guidance is not separated into engineering, workflow, and
repository layers" in `openspec/changes/README.md` is owned by this change for
its layering and tagging. Its loading and citation parts stay open for later
changes.

### Knowledge to promote

- D1, the layers, their test, and the link direction: `openspec/specs/change-workflow/spec.md` (CW-g7lt, CW-d2rw); `openspec/specs/change-workflow/README.md`; `docs/guidance/engineering/README.md`
- D2: no permanent destination — the inventory is change history, and the placement and tags it produces are their own record
- D3, shared guidance under `docs/guidance/` and repository guidance beside its system: `openspec/specs/change-workflow/spec.md` (CW-p9sa); `openspec/specs/change-workflow/README.md`; `openspec/README.md`'s placement table; `AGENTS.md`
- D4, frontmatter tags: `openspec/specs/change-workflow/spec.md` (CW-g7lt); `openspec/specs/change-workflow/README.md`
- D5, `[load]` directory entries: `openspec/specs/change-workflow/spec.md` (CW-l7hn); `.agents/workflow.toml`
- D6, private and public repositories: `docs/guidance/engineering/` (what may enter a repository); `AGENTS.md`'s exceptions; `openspec/specs/change-workflow/README.md`, that the workflow runs in private repositories too
- D7, tool tags: `docs/guidance/engineering/README.md`
- D8, the closeout parts by layer: `docs/guidance/workflow/closeout.md`; `openspec/README.md`'s "This repository's closeout parts"; `AGENTS.md`'s layer table; `planning-governance`'s Evidence; `.agents/skills/change-closeout/SKILL.md`
- D9, exceptions: `openspec/specs/change-workflow/spec.md` (CW-x4ex); `openspec/specs/change-workflow/README.md`; `AGENTS.md`
- D10: no permanent destination — how this change treats each document; the result is the documents themselves
- D11: no permanent destination — the restatements stay, and their inventory rows are change history for the loader change
- D12: no permanent destination — `docs/prompts/` is left as it is
- D13, the checks' classification: `openspec/specs/market-change-workflow/README.md`, "This repository's checks"
- D14, the capability deltas: `openspec/specs/change-workflow/spec.md` and `index.md`; `openspec/specs/market-change-workflow/spec.md` and `index.md`
- D15, the anchor check: `openspec/specs/market-change-workflow/spec.md` (MCW-c4ek); `openspec/specs/market-change-workflow/README.md`
- D16, the guidance placement part: `docs/guidance/workflow/closeout.md`; `.agents/skills/change-closeout/SKILL.md`; `openspec/specs/market-change-workflow/spec.md` (MCW-c4ek) for its mechanical rule
- D17, the frontmatter: `openspec/specs/change-workflow/spec.md` (CW-g7lt); `docs/guidance/engineering/README.md`
- D18, the vocabulary tables: `docs/guidance/engineering/README.md`; `docs/guidance/workflow/README.md`; `AGENTS.md`
- D19, flat files: `openspec/specs/change-workflow/README.md`, with directories carrying no meaning (CW-n6dm)
- D20: no permanent destination — superseded by D3
- D21, `make check-guidance`: `openspec/specs/market-change-workflow/spec.md` (MCW-c4ek); `openspec/specs/market-change-workflow/README.md`
- D22, capability guidance read with its capability: `openspec/specs/change-workflow/spec.md` (CW-r8cg); the five skills
- D23: no permanent destination — `openspec/config.yaml` is unchanged in kind
