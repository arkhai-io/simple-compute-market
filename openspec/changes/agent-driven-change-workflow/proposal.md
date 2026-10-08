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
- Implement one `tasks.md` section per fresh agent session, with planning sizing
  each section to fit one, a handoff recorded in the section's task notes, and a
  fresh-context compliance check of the section's diff before it is committed, so
  that guidance compliance does not degrade as a session grows or compacts. A
  Claude Code hook re-reads the required documents after compaction as a backstop.
- Record every owner disposition of a finding in the change's tracked intervention
  ledger, which is archived with the change and feeds periodic guidance refinement.
- Automate the validation run beside every implementation review, as an
  observation of a committed slice that never alters it: packaging, tests, the
  Helm render checks and a Helm end-to-end run of the pipeline's scenarios on
  every run, and the end-to-end pipeline run for exactly the commit under review.
  Pushing the change's branch is guarded by a check that refuses any state it
  would have to repair.
- Add `make triage`, which triages an implementation round in a fresh session:
  the review, the validation record, and the owner's own notes together, each
  point evaluated with a position rather than obeyed, and the accepted fixes made
  and checked as a section is.
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
- **A per-section driver.** Running a change's sections in sequence, each in a
  fresh session, belongs to the orchestrator; until then the owner starts each
  section's session.
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
- [x] Contributor guidance — `AGENTS.md`, `openspec/README.md`, `docs/agents/`, and
      `docs/development/TESTING.md` (end-to-end run selection), and
      `docs/development/DEPLOYMENT_AND_CONFIG.md` (PVC retention and the local
      deploy overlay).

### Knowledge to promote

- Phases, owner gates, review records, finding lens/basis/severity, triage, the
  intervention ledger, one section per fresh session, observational validation,
  triage of an implementation round, push guards, and single-source skills —
  `openspec/specs/change-workflow/spec.md`.
- Why validation results go to triage rather than to the reviewer, and why the
  owner's notes are evaluated rather than obeyed —
  `openspec/specs/change-workflow/architecture.md`.
- End-to-end log fetching selects the run for the validated commit —
  `docs/development/TESTING.md`.
- Why compliance degrades with session length and why fresh sessions, not a
  re-injected digest, are the remedy — `openspec/specs/change-workflow/architecture.md`.
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
- **Repository layout.** A committed Claude Code project settings file carrying
  the post-compaction hook; a shared skill source under `.agents/skills/` with
  per-harness links; `.gitignore` gains change `reviews/` directories; each worked
  change gains a tracked `interventions.jsonl`.
- **Index format.** Every change row in `openspec/changes/README.md` is checked
  against its own change and rewritten into `Status`, `Depends on`, and `Notes`.
- **Tooling.** `scripts/fetch-e2e-logs.py` selects the run for a given commit;
  new targets `validate-local`, `validate-helm`, `check-push-ready`,
  `push-branch`, `validate`, and `triage`.
- **Follow-up.** The Helm charts lack services the pipeline's compose stacks run,
  so some pipeline scenarios are excluded from the Helm run; bringing the charts
  to parity is a separate change.
- **External effects.** Validation pushes the change's own branch and triggers the
  end-to-end GitHub Actions workflow against it.
- No wire, database, deployment, or packaging change.
