# How this repository runs the change workflow

The change workflow ([`change-workflow`](../change-workflow/README.md)) asks each
repository that adopts it to fill a set of roles. This document says how this
repository fills them.

## How this repository provides the workflow's roles

Each role is the workflow's, as
[`change-workflow`](../change-workflow/README.md#what-an-adopting-repository-provides)
states it; the provision is what fills it here. A test
(`scripts/tests/test_change_workflow_assumptions.py`) fails when a make target or
repository path the workflow's skills, its step table, or its make fragment name, the
fragment's own targets among them, is missing from these two tables, or when the two
documents' roles differ.

| Role | Provided by |
|---|---|
| Local validation of a commit: the repository's own checks and suites against the commit, built from it | `make validate-local`, the family `make validate-*` the step table grants, among them `make validate-ci`; `make check-uv-version` and `make dist-clean` around them; `scripts/validate_slice.py`, which runs the parts against the commit and writes their evidence under `.snapshot/validation/` |
| Validation in a deployed environment: the change's services built and run as the repository deploys them | `make validate-helm`, `make validate-parallel*`, and the chart's render checks `make -C helm test-render`, in the change's own namespace, within the capacity `helm/validation-capacity.toml` records |
| The end-to-end pipeline: a run whose head is the commit, its logs fetched | `make run-e2e` (`make run-e2e*`), the scenarios under `e2e-tests/`, and `make fetch-e2e-logs` (`make fetch-e2e-logs*`), into `.snapshot/e2e-logs/` |
| CI evidence only a push produces: the workflows validation may dispatch, from a fixed list | `make run-ci`, dispatching only the workflows `scripts/ci_evidence.py` lists |
| Removing a change's validation resources, and recording what they used, at archive cleanup | `make -C helm teardown` (`make -C helm teardown*`), and `make record-capacity` (`make record-capacity*`) into `helm/validation-capacity.toml` |
| The repository's tests and environments: the suites, locks, builds, and environment refreshes a change's work runs | `make test` and `make test*`, `make -C * test*` in a project; `make lock`, `make lock*`; `make dist*`, `make -C * dist*`; `make init*`, `make -C * init*`; `make reinit*` and `make typecheck*`, the targets of a project's own `Makefile`; `make helm-values-schema`; internal dependencies from wheels and locks through `scripts/uv_project.py` |
| The packaging check before closeout | `make check-packaging`, which runs `make check-architecture` over `docs/development/ARCHITECTURE.toml`, and `make check-architecture-change` |
| The closing checks a step ends with | `make check-change` (`scripts/check_change.py`), and the checks it runs and the step table grants as `make check-*` and `scripts/check_*`: `make check-comment-hygiene`, `make check-doc-citations` (`make check-doc-citations*`), `make check-spec-index` |
| A snapshot of the code for the owner's reading | `make code-snapshot` |
| The change index at a known path | `openspec/changes/README.md`, checked in a prerequisite's proposal checkout beside this one by `make -C ../<prerequisite>-proposal check-change-index` (`make -C ../*-proposal check-change-index`) |
| The guidance documents every step reads | `AGENTS.md`, `docs/development/ARCHITECTURE.md`, `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, `openspec/README.md`, `docs/development/ROADMAP.md`, `openspec/config.yaml`, and the workflow's guide `docs/agents/change-workflow.md` |
| Where specifications and documentation live | `openspec/` (`openspec/**`): the capabilities under `openspec/specs/`, indexed by `openspec/specs/README.md`, each `openspec/specs/<capability>/spec.md`; and `docs/` (`docs/**`), its development documents under `docs/development/` |
| Protected branches the guarded push refuses | `main` and `dev` |
| The `origin` remote the guarded push and the pipeline use | `origin`, this repository on GitHub |
| The branch a change lands on, merged before closeout and reviewed against | `dev`, set before the fragment's include by `Makefile` as `CHANGE_WORKFLOW_MERGE_FROM` and `CHANGE_WORKFLOW_REVIEW_BASE` |
| The clone's bootstrap: one command that readies a fresh clone | `make init` |
| The make fragment's targets, included by the repository's `Makefile` | `Makefile` includes `scripts/change_workflow/workflow.mk`, giving `make design`, `make plan`, `make implement`, `make review`, `make triage`, `make validate`, `make merge`, `make closeout`, `make archive-cleanup`, `make orchestrate`, `make change-next`, `make change-clone`, `make change-clone-remove`, `make round-view`, `make round-done` (`make round-done*`), `make round-view-closed`, `make change-watch`, `make change-cost`, `make change-history`, `make check-change-index`, `make check-tasks` (`make check-tasks*`), `make check-agent-skills`, `make check-push-ready`, `make push-branch`, and `make change-graph`; run in a change's clone as `make -C <clone> implement`, `make -C <clone> push-branch`, and `make -C <clone> change-history` |

### The engine's own assumptions

How this repository meets what the engine itself holds. The test reads these as
provisions too; whether the table names everything the engine holds is kept by
review.

| Assumption | Here |
|---|---|
| The protected branches the guarded push refuses, and the remote it pushes to | `main` and `dev`; `origin` |
| The branch a review reads the change against | `dev` |
| The change index's path | `openspec/changes/README.md` |
| The guidance documents a session re-reads after its context is compacted | `docs/development/ARCHITECTURE.md`, `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, `openspec/README.md` |
| The documentation a commit may change after a pre-closeout review without a validation | `openspec/` and `docs/` |
| Where validation's and the pipeline's evidence is, which history copies | `.snapshot/validation/` and `.snapshot/e2e-logs/`, untracked |
| Its command and package, beside each other under `scripts/` | `scripts/change-workflow` and `scripts/change_workflow/`, whose computation and graph the orchestrating skill cites, `scripts/change_workflow/next_step.py` and `scripts/change_workflow/graph.py` |
| The step table, at a fixed path, in Claude Code's permission-rule syntax | `.claude/change-steps.toml`, its rules guarding `.claude/**` |
| The outcome schema, at a fixed path | `.agents/change-outcome.schema.json` |
| The skills' one source, linked into each harness's directory | `.agents/skills`, under `.agents/`, linked from `.claude/` and `.codex/` |
| The harness's local settings, which a clone links to the workspace's | `.claude/settings.local.json` |
| The changes' directory, its archive, and each change's records under `reviews/` | `openspec/changes/`, each change at `openspec/changes/<change>/`, archived under `openspec/changes/archive/` as `openspec/changes/archive/<date>-<change>/`; the step table names `openspec/changes/**/reviews/*-validation.md`, `openspec/changes/archive/*/interventions.jsonl`, and `openspec/changes/archive/*/reviews/pull-request.md` |
| The graph diagram's place in this capability | `openspec/specs/change-workflow/diagrams/`, the workflow's own specification being `openspec/specs/change-workflow/spec.md` |
| The branch a new change's clone starts from, and the merge's default | `dev` |
| The clone's bootstrap command, run as the clone is made | `make init` |
| The `workspace` remote a clone names the owner's workspace by | `workspace`, set by `scripts/change-workflow clone` |
| The harness's session id in the environment, `CLAUDE_CODE_SESSION_ID` | Claude Code's |
| The tools it invokes, `git`, `claude`, `codex`, and `make`, and `gh`, which its skills invoke | each on the owner's path |
