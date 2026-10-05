## Why

Every OpenSpec change moves through the same phases: design discussion, planning,
design review, implementation in slices, implementation review, closeout, closeout
review, archival, and a pull request. Today those phases run in browser chat
sessions fed by a zipped snapshot of the repository. The repository owner carries
every review between two agents without editing it, restarts implementation after
each tool-use limit, and keeps a browser window per change for each change worked
in parallel.

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

- Add harness-neutral **leaf skills**, one per phase, each loadable by both Claude
  Code and Codex from one source: `change-design`, `change-plan`, `change-review`,
  `change-triage`, `change-implement`, `change-validate`, `change-closeout`, and
  `change-ship`. Each is proven on a real change, in the order the workflow uses
  them, before the next depends on it.
- Add `make review`, which runs a change review non-interactively in a second
  agent harness and writes it into the change's untracked `reviews/` directory, so
  a review is produced by one agent and read by another without passing through
  the owner's clipboard. A review is one Markdown file whose findings each carry a
  lens, a basis, and a defined severity.
- Record every owner disposition of a finding in the change's tracked intervention
  ledger, which is archived with the change and feeds periodic guidance refinement.
- Automate the validation run before every implementation review, as an
  observation of a committed slice that never alters it: packaging, tests, the
  Helm render checks and Helm end-to-end run when owed, and the end-to-end
  pipeline run for exactly the commit under review. Pushing the change's branch
  is guarded by a check that refuses any state it would have to repair.
- Give every change row in the active-change index a phase-and-state status, a
  `Depends on` column naming which phase each dependency gates, and a `Notes`
  column; when a dependency lands, its dependents' designs are reverified before
  they proceed.
- Remove the browser delivery rules from `AGENTS.md` and `openspec/README.md`.
  They remain, with the rule that no tombstone survives into the tree, in the
  browser session prompts under `docs/prompts/` for as long as that process is
  used; no skill refers to that folder.

## Non-Goals

- **An orchestrating skill.** A process-aware skill that advances a change through
  every phase, and surveys all changes to direct the owner to the next blocking
  item, is the intended end state. It is designed once the leaf skills exist and
  their failure modes are known, as its own change.
- **Campaign priority.** Choosing which campaign to work first has no consumer
  until the orchestrator exists, and belongs to that change.
- **A machine parser for the index.** The index is read by agents; a fixed
  vocabulary is enough for that, and no `make` target acts on it.
- **Removing human gates.** Every review stops for the owner, who reads every
  finding. Triage orders findings and states the implementing agent's own
  position; it does not filter.
- **Per-lens reviewer agents.** A review is one session covering every lens. The
  finding record names its lens so the review can later be split across separate
  reviewer agents without changing what a finding is.
- **Third-party model providers.** Reviews run on the harnesses already in use.
- **Retiring `docs/prompts/`, `make code-snapshot`, or the tombstone tooling.**
  Changes not piloted here continue through browser sessions until the leaf skills
  are proven; that tooling retires with the browser process.

## Capabilities

### New Capabilities

- `change-workflow`: the phases a change moves through and where the owner must
  act; review records, their findings, and their authority; triage and the
  intervention ledger; validation as an observation of a committed slice; the
  guards on pushing a change's branch; and harness-neutral repository skills.

### Modified Capabilities

- `planning-governance`: the active-change index carries a phase-and-state status
  vocabulary and phase-gating dependencies, and a landing change returns its
  dependents to design.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — none; the workflow is contributor
      process, not system architecture.
- [x] Existing subsystem specification — `openspec/specs/planning-governance/spec.md`.
- [x] New subsystem specification — `openspec/specs/change-workflow/spec.md`.
- [x] Contributor guidance — `AGENTS.md`, `openspec/README.md`, and `docs/agents/`.

### Knowledge to promote

- Phases, owner gates, review records, finding lens/basis/severity, triage, the
  intervention ledger, observational validation, push guards, and single-source
  skills — `openspec/specs/change-workflow/spec.md`.
- Why lens and basis are separate axes, why reviews are exchanged as files rather
  than continued sessions, and why validation must not relock —
  `openspec/specs/change-workflow/architecture.md`.
- The index status vocabulary, phase-gating dependencies, and dependency-landing
  reverification — `openspec/specs/planning-governance/spec.md`.
- The dependency-landing rule as a step of campaign index currency —
  `openspec/README.md#plan-closeout-requirements`.
- How to invoke each leaf skill and `make review`, and where review files and the
  ledger live — `docs/agents/change-workflow.md`, linked from `AGENTS.md`.

## Impact

- **Contributor workflow.** `AGENTS.md` no longer describes filesets or
  tombstones; the `openspec/README.md` completion checklist loses its tombstone
  item; closeout part 6 gains the dependency-landing step.
- **Repository layout.** A shared skill source under `.agents/skills/` with
  per-harness links; `.gitignore` gains change `reviews/` directories; each worked
  change gains a tracked `interventions.jsonl`.
- **Index format.** Every change row in `openspec/changes/README.md` is checked
  against its own change and rewritten into `Status`, `Depends on`, and `Notes`.
- **Tooling.** `scripts/fetch-e2e-logs.py` selects the run for a given commit.
- **External effects.** Validation pushes the change's own branch and triggers the
  end-to-end GitHub Actions workflow against it.
- No wire, database, deployment, or packaging change.
