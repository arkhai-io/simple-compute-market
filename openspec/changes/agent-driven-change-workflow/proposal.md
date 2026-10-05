## Why

Every OpenSpec change moves through the same phases: design discussion, design
review, implementation in slices, implementation review, closeout, closeout review,
archival, and a pull request. Today those phases run in browser chat sessions fed
by a zipped snapshot of the repository. The repository owner carries every review
between two agents without editing it, restarts implementation after each tool-use
limit, and keeps a browser window per change for each change worked in parallel.

The judgement the owner adds is concentrated in two places: design direction, and
refining the development guidance and closeout procedure so later reviews find
less. The rest is transport: copying text between agents, rebuilding snapshots,
running the same validation sequence before every review. Agents working directly
in the repository can do the transport themselves, provided the process each
phase follows is written down where any agent harness can load it, and reviews
are exchanged as files rather than pasted text.

The browser-oriented delivery rules — zipped filesets, and tombstone files standing
in for deletions — exist only because a browser session cannot touch the
repository. They are in `AGENTS.md`, which every agent reads, so an agent working
directly in the repository is told to write tombstones instead of deleting files.

## What Changes

- Add harness-neutral **leaf skills**, one per mechanical phase, each loadable by
  both Claude Code and Codex from one source: design discussion, change review,
  review triage, pre-review validation, closeout, and archival with pull-request
  drafting. Each is proven on a real change before the next depends on it.
- Add a `make` entry point that runs a change review non-interactively in a
  second agent harness and writes its findings into the change's `reviews/`
  directory, so a review is produced by one agent and read by another without
  passing through the owner's clipboard.
- Give every review finding a structured record — the review lens that produced
  it, the basis it rests on, and a severity — so findings can be read in order of
  the attention they need, and so the owner's interventions accumulate into a
  local ledger for periodic guidance refinement.
- Automate the validation sequence run before every implementation review — lock,
  packaging check, tests, the end-to-end pipeline and its logs — and record the
  result where the reviewer reads it.
- Make the active-change index machine-readable: a fixed status vocabulary in one
  column with explanatory prose moved to its own column, and one priority order
  over campaigns.
- Remove the browser delivery rules from `AGENTS.md` and `openspec/README.md`.
  They remain in the browser session prompts under `docs/prompts/` for as long as
  that process is used; no skill refers to that folder.

## Non-Goals

- **An orchestrating skill.** A process-aware skill that advances a change through
  every phase, and surveys all changes in priority order to direct the owner to the
  next blocking item, is the intended end state. It is deliberately not built here:
  it is designed once the leaf skills exist and their failure modes are known, as
  its own change.
- **Removing human gates.** Every design review and every implementation review
  stops for the owner, who reads every finding. Triage orders findings and states
  the implementing agent's own position; it does not filter.
- **Per-lens reviewer agents.** A review is one session covering every lens. The
  finding record names the lens so the review can later be split across separate
  reviewer agents without changing what a finding is.
- **Third-party model providers.** Reviews run on the harnesses already in use.
- **Retiring `docs/prompts/` or `make code-snapshot`.** Changes not piloted here
  continue through browser sessions until the leaf skills are proven.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `planning-governance`: the active-change index carries a fixed status
  vocabulary and a campaign priority order; review records produced while a change
  is worked are transient and untracked; repository agent skills have one source
  shared by every supported harness.

## Impact

- **Contributor workflow.** `AGENTS.md` no longer describes filesets or
  tombstones; the `openspec/README.md` completion checklist loses its tombstone
  item. `make check-comment-hygiene` keeps rejecting tombstones in tracked files.
- **Repository layout.** A shared skill source directory with per-harness links;
  `.gitignore` gains change `reviews/` directories and the local intervention
  ledger.
- **Index format.** Every status cell in `openspec/changes/README.md` is rewritten
  into the fixed vocabulary, with its prose moved to a new column.
- **External effects.** The validation sequence triggers the end-to-end GitHub
  Actions workflow, which runs against the pushed branch.
- No wire, database, deployment, or packaging change.
