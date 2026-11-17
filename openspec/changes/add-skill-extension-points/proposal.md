## Why

Each step of the workflow is one skill, a single `SKILL.md` under `.agents/skills/`.
`add-workflow-capability-contract` moved *what runs* into `.agents/workflow.toml`, and
`layer-engineering-guidance` gave closeout's repository parts a role in the root
guidance. What is left in the skills is this repository's tooling written into their
text:

- **`change-validate`** describes this repository's Helm part, end-to-end pipeline,
  CI baseline comparison, evidence files, diagnosis rules, and record sections.
- **`change-archive-cleanup`** and **`change-merge`** describe the capacity figure a
  cleanup writes and how its conflicts resolve.
- **`change-plan`**, **`change-implement`**, and **`change-orchestrate`** name
  `e2e-tests/` markers, `scripts/ci_evidence.py`, and `HELM_ALL_SCENARIOS`.
- **Several skills** cite repository paths and targets where the workflow has a role,
  such as `openspec/README.md#this-repositorys-closeout-parts` and `make
  check-comment-hygiene`.

Once the skills are shared across repositories, an edit for one repository is an edit
for all, and a repository-local copy is a fork. `extract-change-workflow-repository`
needs the base skills to hold no repository material before they are shared.

Validation also runs every part blindly, though implementation has often just run the
same checks on the very tree it commits: the workflow knows parts, not evidence.

## What Changes

- **Evidence, not parts.** The workflow and engine know evidence kinds, not a
  repository's parts. Evidence describes a Git tree and is reused for any commit with
  that tree — or, for a kind whose result depends on the commit's history, such as a
  dispatched run, describes the commit — whoever wrote it; it counts by being present
  at its kind's pattern, an owed kind's for each argument owed.
- **Validation completes and assesses evidence.** `scripts/change-workflow evidence`
  reports which required kinds are present for `HEAD`'s tree; the engine gathers the
  missing ones before validation's session starts; the skill assesses every kind from
  its guide and writes the record, naming each kind's source.
- **Kinds are declared in the configuration, explained in guides.** Each kind's
  engine fields — requirement (`always` or `owed`), evidence pattern with `{tree}` or
  `{commit}`, commands, `after`, `cleanup` — sit in `[validation.evidence.<kind>]`;
  its guide, required, prose under `.agents/evidence/`, tells the agent how to read
  and diagnose it and restates nothing the configuration holds.
- **Hooks around every step.** A repository may declare `before-<step>` and
  `after-<step>` hooks; their messages reach the session through a per-run inputs
  directory. A failing before-hook informs the session; a failing after-hook resumes
  the session once, then goes to the owner; a review's runner holds its hooks, and
  a failing `after-review` goes to the owner directly. The engine's own actions
  around steps —
  gathering before validate, cleanup before archive cleanup — use the same machinery.
- **The base skills name no repository's targets or paths,** held by a test, the step
  table's command forms excepted until `sandbox-unattended-workflow-steps` lands.
- **This repository's specifics move into its four guides** and its configuration,
  with its behaviour unchanged but for reused evidence.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `change-workflow`: evidence kinds, their identity, presence, requirement, gathering,
  and assessment; the two injections and guides; step hooks, their failures, and the
  inputs directory; neutral skills.
- `market-change-workflow`: this repository's evidence kinds and their guides, and its
  statement of roles.

## Public interfaces

The workflow has no release, so none of these is migrated (CW-c2tw):

| Interface | Change | Compatible |
|---|---|---|
| `[validation.parts.<name>]` | becomes `[validation.evidence.<kind>]`; `evidence` a pattern with `{tree}` or `{commit}`, and `{owed}` in an owed kind's; adds `required` and a required `guide` | no |
| Hooks `before-<step>`, `after-<step>` | added, optional, no defaults; a review's run by its runner | yes |
| Placeholders `{tree}`, `{commit}`, `{inputs}`, `{kind}` | added | yes |
| `evidence <change> [--json]`, `gather <change> [--kind] [--lapsed]`, `run before\|after <step> <change>` | added | yes |
| `run validation … preflight\|run\|start\|collect`, `config parts` | fold into `gather` and `evidence` | no |
| `run cleanup` | kept for reruns; also the built-in action before archive cleanup | yes |
| The validation record | adds `Tree:` and each kind's source; `Parts:` becomes `Evidence:`, which the engine does not parse | yes |
| The record set's layout | adds `reviews/runs/<run>/before\|after/` | yes |
| A run's log line | names its inputs directory | yes |
| The owed line | adds an optional `(<kind> <argument>)` | yes |
| Roles (CW-m4ps) | validation's roles restated as evidence kinds; step hooks an optional role; the skills name no target | no, for the restated roles |

## Non-Goals

- **Do not let a repository replace a skill,** or load a free-form addendum beside it.
- **Do not defend the workflow's obligations against the repository's own guides or
  hooks.** Injected text can always steer a model, and whoever controls the repository
  controls the files that would enforce them; a skill only names a contradiction it
  notices. Defending guidance against untrusted parties is designed with the hosted
  runner's access model.
- **Do not fetch evidence from beyond the checkout.** Whatever holds it places it.
- **Do not add hooks for every node,** each review kind and `late-merge` apart; they
  are a later change.
- **Do not change the OpenSpec skills** (`openspec-*`).

## Impact

- `scripts/change_workflow/`: `config.py` (kinds, hooks, placeholders, the check),
  `hooks.py`, `cli.py` (`evidence`, `gather`, `run before|after`), `wrapper.py` (the
  actions around steps, the inputs directory, resumption after an after-hook),
  `review.py` (a review's hooks),
  `graph.py` (the actions table), `history.py`, `records.py`; their tests.
- `.agents/workflow.toml`, the new `.agents/evidence/` guides, and this repository's
  validation scripts (`scripts/validate_slice.py`, `scripts/ci_evidence.py`,
  `scripts/fetch-e2e-logs.py`), writing under `.snapshot/evidence/{tree}/`.
- Every `change-*` skill, for neutrality, the inputs directory, and the contradiction
  notice; `change-validate`, `change-archive-cleanup`, `change-merge`, `change-plan`,
  `change-implement`, `change-orchestrate`, `change-closeout`, `change-review`,
  `change-design`, and `change-triage` lose this repository's material.
- `scripts/tests/test_change_workflow_assumptions.py`, inverted for skills.
- The step table, `.claude/change-steps.toml`, for the new commands.
- The workflow's specification, index, and companion; `market-change-workflow`'s.

## Dependencies and Related Changes

- **`specify-change-workflow-and-engine`, `add-workflow-capability-contract`, and
  `layer-engineering-guidance`,** archived: this design rests on the surface, the
  configuration, and the closeout role they left.
- **`sandbox-unattended-workflow-steps`** owns the exemption for the step table's
  command forms in the skills, and moves the guarded push into the engine as the
  gathering already uses it.
- **`test-affected-suite-selection`** builds the mapping from paths to suites that
  identity and requirement by declared inputs would build on (Open Questions).
- **`extract-change-workflow-repository`** depends on this change for its design.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` and `market-change-workflow`,
      specifications, indexes, and companions
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/change-workflow-handbook.md` changes with it for the hooks and the inputs
directory. The lesser goal's gap "A skill can vary per repository only by being
edited" in `openspec/changes/README.md` is owned by this change and closes with it;
hooks for every node become an unowned gap there.

### Knowledge to promote

- D1: `change-workflow`'s companion, "Validation observes a committed slice" and
  "What an adopting repository provides"; CW-zkhs, CW-k7gd.
- D2: CW-t3ev and CW-g1gn; `change-workflow`'s companion, "Validation observes a
  committed slice", with the risk of a digest changed by an unignored file.
- D3: CW-p4rs; `change-workflow`'s companion, "Validation observes a committed slice".
- D4: CW-e2vd and CW-a8ss; `change-workflow`'s companion, "Validation observes a
  committed slice".
- D5: CW-r5qk and CW-5h8e; `change-workflow`'s companion; the plan skill.
- D6: CW-d1nj, CW-g2rs, and CW-g4oz; `change-workflow`'s companion, "A repository's
  configuration".
- D7: CW-g6th, CW-ikmm, CW-h3ks, CW-b7fl, CW-a4fl, CW-i9np, CW-b2xr, CW-v2dq, and
  CW-q5fy; `change-workflow`'s companion, "A step run's life", "The hooks", and
  beside "Routing is code, with the model as backstop" for deterministic work in the
  engine; the owner's handbook.
- D8: CW-h3ks; `change-workflow`'s companion, "The hooks".
- D9: CW-n8tr and CW-m4ps; `change-workflow`'s companion, "Leaf skills from one
  source"; `market-change-workflow`'s MCW-5tgp.
- D10: CW-c5nt; `change-workflow`'s companion, "A repository's configuration".
- D11: CW-w8ne's scenarios as the check's; `change-workflow`'s companion, "A
  repository's configuration".
- D12: CW-k7gd; the review skill.
- D13: the orchestrating skill; `change-workflow`'s companion, "The orchestrator relays
  and routes".
- D14: no permanent destination beyond the pipeline and CI guides — CW-av28 is
  unchanged.
- D15: no permanent destination — the interfaces it lists are recorded in the
  requirements above and in the companion's "Interfaces are tiered".
- D16: MCW-r4tx and MCW-5tgp; `market-change-workflow`'s companion, "Validation's
  parts" and "How this repository provides the workflow's roles".
- D17: no permanent destination — the cadence is the change's own.
