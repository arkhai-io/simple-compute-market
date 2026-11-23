## Why

The change workflow lives in this repository and has no version of its own. A
change to it ships with whichever commit of this repository carries it. No other
repository can adopt it without copying it, and a copy stops receiving
improvements the day it is made. Its improvements are also entangled with market
changes, in the same history, reviews, and releases.

The changes before this one drew the boundary between the workflow and this
repository while both still live here, and all have landed:

- `specify-change-workflow-and-engine` specified the workflow and its engine and
  defined the public surface.
- `add-workflow-capability-contract` put the repository's assumptions in one
  configuration file.
- `sandbox-unattended-workflow-steps` replaced the step table and its deny rules with
  an engine-owned sandbox, so no permission lives in a harness's settings.
- `add-skill-extension-points` moved this repository's specifics out of the skills
  into evidence kinds, their guides, and hooks around each step.
- `layer-engineering-guidance` separated the workflow's guidance from engineering and
  repository guidance.

What is left on the workflow's side still reaches for paths in the adopting
repository: its guidance, its specification, the engineering guidance, its command,
its schema, and its skills. This change makes the workflow self-contained and
installable, has it moved to a repository of its own, and makes this repository an
adopter.

## What Changes

The change has two halves, with a pause between them (design D1, D2).

**The workflow as a distribution, run here installed (the first half).**

- **One versioned distribution.** A Python wheel, `arkhai-change-workflow`, carries
  the engine as the `change-workflow` command, its eleven skills, its guidance, its
  specification, the owner's handbook, the outcome schema, and the make fragment. The
  engine finds its own documents beside itself (D6, D8, D9).
- **An installer.** `change-workflow install` writes the skills into Claude Code's
  and Codex's user skill directories, stamped with their version, and, run in a
  checkout, writes the checkout's local configuration where none exists. Every engine
  command refuses skills whose stamp differs from its own version, or that are
  missing (D8). The workflow's project skill links go in this half, so each harness
  loads the installed skills (D8, D18).
- **Repositories declare a compatible version range.** A committed `[workflow]
  version` holds PEP 440 specifiers; every engine command that reads the
  configuration refuses an installed version outside it, naming the fix. One version
  is installed per machine, managed like any other tool a repository pins (D7, D11).
- **Records carry the workflow version.** Each log line records the engine's version
  that wrote it; the record format does not move (D12).
- **Committed and local configuration.** Settings developers may give different
  values — the engineering-guidance pointer, the models, added writable paths — move
  to one gitignored file, `.agents/workflow.local.toml`; everything else stays
  committed (D5).
- **Engineering guidance through a pointer.** The workflow ships no engineering
  guidance. A pointer names where a user's is; `config load` reads it, and the skills
  cite it by section name, a provisional interface (D3, D4).
- **Citations by section and id.** The skills cite the workflow's guidance by section
  and its specification by requirement id; the workflow's documents stop linking into
  this repository (D6).
- **Two more default checks.** The specification index and decision destinations
  checks become the engine's (D10).
- **Smaller interfaces callers need.** `config --json` names each of the workflow's
  installed documents by role, the engineering pointer, and the roles, and succeeds
  without the local file; `fragment` prints the installed fragment's path; `check
  spec-index --json` reports the paths a change's deltas create (D5, D6, D10, D14,
  D15).
- **Protection of what is installed.** The sandbox protects the installed skills, the
  installed engine, and the local file (D13).
- **This repository runs the workflow installed from its tree**, and the engine's
  diagrams are redrawn (D20). The `change-workflow` delta is applied to the permanent
  specification, so the release carries its own requirements (D23). This half may be
  merged to `dev` while the change waits.

**The pause.** A coordinator bootstraps the workflow's public repository, `change-workflow`,
from what the first half left, lifting the moved files with their history by path,
and releases it. The change waits in implementation for its evidence: the
repository, the release, its artifacts, and how to install it (D2, D16, D17).

**This repository as an adopter (the second half).** It declares the range it
accepts, installs the release, removes the in-tree engine, skills, schema, workflow
guidance, `change-workflow` capability, and handbook, and re-points its documents to
cite the workflow in prose by name, id, and section. It keeps its committed
configuration, its evidence guides and hooks, its engineering and repository
guidance, and `market-change-workflow` (D6, D14, D18, D19).

## Capabilities

### New Capabilities

- None in this repository. The workflow's capability moves with it.

### Modified Capabilities

- **`change-workflow`** gains the distribution, the installer, the version range, the
  version on log lines, the local configuration, the engineering pointer, the new
  default checks, and the structured outputs above; at the second half it leaves this
  repository for the workflow's.
- **`market-change-workflow`** states how this repository provides the workflow's
  roles across both configuration files, that it runs the installed workflow within
  its declared range, and what its local configuration template names.

## Public interfaces changed

Nothing of the workflow has been released, so these are judged as the first
release's surface (CW-c2tw):

- **The command's name** becomes `change-workflow` on the path: incompatible.
- **The configuration** splits into `.agents/workflow.toml` and
  `.agents/workflow.local.toml`, `[models]` moving to the local file and `[workflow]`
  and `[guidance]` added, both required: incompatible.
- **New subcommands and outputs** — `install`, `fragment`, `--version`, `config
  --json`'s `local`, `workflow` (each installed document by role), `guidance`, and
  `roles`, and its `missing` status, `check spec-index --json`, the log line's
  `workflow` field: compatible additions.
- **New default checks**, `spec-index` and `decisions`: incompatible, since an
  adopter's commits may newly fail.
- **The skills' citations of engineering guidance** become a provisional interface:
  the section names they cite.
- **`check skills`** holds the installed skills' version stamp as well: incompatible.

## Non-Goals

- **Do not move the engineering guidance.** Where it lives, and how it gets a neutral
  home, are a later change; this change builds the pointer that change updates.
- **Do not add harnesses.** The installer serves Claude Code and Codex; adding one is
  `add-workflow-harness-adapters`'.
- **Do not build the model gateway or the hosted runner.**
- **Do not install versions side by side.** One version is installed per machine.
- **Do not open a public distribution channel.** It is deferred to the first public
  adopter.
- **Do not bootstrap the workflow's repository from this branch.** The coordinator
  does, outside this repository's workflow.
- **Do not change what any step does,** beyond the version and skill checks, the
  configuration split, and the checks moved into the engine.

## Impact

- `scripts/change-workflow`, `scripts/change_workflow/` with `workflow.mk`, the
  workflow's tests and fixtures under `scripts/tests/`, `.agents/skills/change-*` and
  `guidance-review`, `.agents/change-outcome.schema.json`, `docs/guidance/workflow/`,
  `openspec/specs/change-workflow/`, and `docs/change-workflow-handbook.md`: packaged
  in the first half, removed in the second.
- `scripts/check_spec_index.py` and `scripts/check_decision_destinations.py`, which
  become engine modules; `scripts/check_doc_citations.py`, which reads delta paths
  from the engine; `scripts/check_guidance.py`, whose link-direction rule changes;
  `scripts/check_change.py` (`make check-repository`).
- `.agents/workflow.toml`, a new `.agents/workflow.local.template.toml`, and
  `.gitignore`.
- `.claude/skills/` and `.codex/skills/`, whose `change-*` and `guidance-review`
  links go in the first half; `.claude/settings.json`'s post-compaction hook.
- `docs/guidance/engineering/`, whose three repeated headings become unique.
- `scripts/check_project_layout.py` and `AGENTS.md`'s exceptions table, which admit the
  wheel's layout until the second half removes the wheel (D24).
- The `Makefile`'s include of the fragment, and its install target.
- About 95 permanent documents citing the workflow's specification or guidance,
  `AGENTS.md` and `openspec/README.md` among them; the citation check fails on any
  reference left behind.
- `scripts/tests/test_change_workflow_assumptions.py`.
- A new public repository, its release, and its own process, which are the
  coordinator's.

## Dependencies and Related Changes

- **`specify-change-workflow-and-engine`, `add-workflow-capability-contract`,
  `sandbox-unattended-workflow-steps`, `add-skill-extension-points`, and
  `layer-engineering-guidance`**: archived; this design rests on what they left.
- **`add-workflow-harness-adapters`**: independent in either order; whichever lands
  second extends `install` to its harnesses' user skill directories.
- **`relay-messages-to-step-sessions`**: once landed, may carry the coordinator's
  report of the gate's evidence; not a dependency.
- **`host-change-workflow-runner`**: builds its image from the extracted workflow at a
  version.
- **The extraction of the engineering guidance, still to be opened**: updates the
  pointer this change builds to its distribution.
- **Open workflow changes in this index** move to the workflow's repository once it
  exists (D19).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`, for how this repository adopts the
      workflow
- [x] Existing subsystem specification: `change-workflow` is amended, then leaves;
      `market-change-workflow` is amended
- [ ] New subsystem specification
- [ ] No permanent documentation change

`AGENTS.md`, `docs/change-workflow-handbook.md`, `openspec/README.md`, and the lesser
goal's section of `openspec/changes/README.md` change with it.

The lesser goal's gap "The workflow is not a separately versioned distribution" is
owned by this change and closes with it. So is the gap on `change-workflow`'s diagrams
of the engine's parts and of a step run's life, which draw neither the evidence
modules nor the actions and hooks around a step; this change redraws both (D20),
given the redraw by `add-skill-extension-points`' closeout triage (55 F4).

### Knowledge to promote

- D1: `change-workflow`'s companion, "The public surface", for how the workflow
  became a distribution; the staging itself is change history.
- D2: no permanent destination — the gate governs this change's own pause, recorded
  in its plan and task notes.
- D3: `change-workflow`'s companion, "The repository's guidance is layered", and
  CW-hu0z.
- D4: `change-workflow`'s companion, "A repository's configuration" and "Interfaces
  are tiered"; CW-hu0z, CW-7x0z, and the modified CW-d2rw and CW-n8tr.
- D5: `change-workflow`'s companion, "A repository's configuration", and CW-4pm4 and
  the modified CW-f3qk; the test it rests on, to the workflow repository's own
  repository guidance, carried there by the handbook's procedure for the move.
- D6: `change-workflow`'s companion, "Leaf skills from one source" and "A
  repository's configuration"; CW-lm42 and the modified CW-l7hn and CW-n8tr;
  `market-change-workflow`'s companion and `AGENTS.md` for this repository's
  citations.
- D7: `change-workflow`'s companion, "The public surface", and the handbook, the
  workflow's user guide; CW-f8yy.
- D8: `change-workflow`'s companion, "The command and its tiers" and "Its parts";
  CW-5kl9, CW-1rhd, CW-sv3u, and the modified CW-r3ka; the handbook, for installing.
- D9: `change-workflow`'s companion, "The command and its tiers", for the names; the
  licence is the workflow repository's `LICENSE`.
- D10: `change-workflow`'s companion, "A repository's configuration"; CW-368t and the
  modified CW-c8lw; `market-change-workflow`'s companion, "What each check enforces".
- D11: `change-workflow`'s companion, "A repository's configuration"; CW-f8yy.
- D12: `change-workflow`'s companion, "A change's records carry one format version";
  CW-d867.
- D13: `change-workflow`'s companion, "Restrictions bind unattended runs only" and
  "Current limits"; the modified CW-r6kd.
- D14: `change-workflow`'s companion, "What an adopting repository provides"; CW-ora1;
  `market-change-workflow`'s companion, "How this repository provides the workflow's
  roles", and the modified MCW-5tgp.
- D15: `change-workflow`'s companion, "The command and its tiers"; CW-dvz5.
- D16: the handbook's procedure for the move.
- D17: no permanent destination here — the workflow repository's own process is its
  bootstrap's, outside this repository.
- D18: the handbook, for when an open change crosses to the installed workflow.
- D19: `openspec/changes/README.md`, the lesser goal's section.
- D20: `change-workflow`'s companion diagrams, `change-workflow-engine-parts` and the
  step run's.
- D21: the modified CW-d8de and `change-workflow`'s companion, "Leaf skills from one
  source".
- D22: no permanent destination — the cadence is this change's plan.
- D24: no permanent destination — the `overrides` row in `AGENTS.md`, "Exceptions
  to shared guidance", and `make check-project-layout`'s admission of the wheel stand
  only through the pause; (iii) removes both with the wheel.
- D23: no permanent destination — how this change's own delta reaches the permanent
  specification and how it archives are recorded in its plan and closeout task.
- `market-change-workflow`: MCW-9k0c and MCW-iqh1, and its companion's "This
  repository is the workflow's first adopter"; `docs/development/ARCHITECTURE.md` for
  how this repository adopts the workflow.
