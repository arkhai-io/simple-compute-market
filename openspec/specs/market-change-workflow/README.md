# How this repository runs the change workflow

The change workflow ([`change-workflow`](../change-workflow/README.md)) asks each
repository that adopts it to fill a set of roles. This document says how this
repository fills them, and why its own part of the workflow — validation's parts, the
isolation of each change's Helm validation, and its workflow values — is shaped as it
is. The [specification](spec.md) states this repository's requirements, and its
[index](index.md) organizes them by id.

## This repository is the workflow's first adopter

The workflow is meant to be adopted by other repositories, and what every adopting
repository will need is worked out here first. A general requirement in
`change-workflow` states the rule and where a repository's part plugs in —
validation's parts are the repository's (CW-zkhs); the push refuses the repository's
protected branches (CW-59c7) and runs its pre-push check where it provides one
(CW-p7kq); a repository may forbid models (CW-zq4h); the clone's bootstrap is the
repository's (CW-8npg) — and this capability states what this repository adds. It is
the shape every adopting repository's own capability will have: the workflow ships
no repository's values, and a repository's values never need to be read out of the
workflow's rules.

## Validation's parts

Validation describes one commit and fixes nothing (CW-a7dw, CW-af15). What evidence
a commit of this repository needs follows from what it ships — Python packages built
into wheels, services deployed by Helm charts, and end-to-end scenarios across
several market lanes — so validation here has four parts: a local part, a Helm part,
the end-to-end pipeline, which starts first because it is the slowest, and a `ci`
part for evidence owed by validation. No local suite stands in for the pipeline, and
the pipeline does not deploy the charts, so each part reports what only it can show.

Validation never relocks: `make lock` would silently repair the stale lock `make
check-packaging` exists to report, so relocking belongs to implementation, and a
stale lock sends the slice back.

The wheelhouse in `.dist` is shared by every branch built in the checkout, and
environments sync internal packages with an upgrade, so a higher version another
branch left behind is installed in place of the one the commit builds. Each part
that builds therefore starts from `make dist-clean`; the `ci` part builds nothing
(MCW-v3tf). End-to-end evidence comes from a pipeline run whose head is the commit,
never an earlier run (MCW-zk52).

The Helm part builds the service images, runs the chart's render checks, a skipped
one failing (MCW-qeja), and runs the pipeline scenarios the default charts can serve,
reporting every other one as not run against Helm rather than as passed (MCW-8h0r).
It never starts from state another commit wrote, and never reaches another change's
deployment.

### The change's namespace

Each change's Helm part deploys into a namespace of its own, `validate-<change>`, so
two changes' validations never uninstall each other's release (MCW-fnuh). A namespace
alone does not isolate images: every image the chart deploys is pulled
`IfNotPresent` from the one Docker daemon the development cluster reads, so the part
builds every image under a tag fixed per change, the bare tag with `-<change>`
appended, and deploys those tags. A tag per change, never per commit: a rebuilt image
under a fixed tag rolls out by restarting pods, and two changes never write one tag,
so no build lock is needed. A namespace per validated commit was rejected because
they accumulate; one per change is bounded by the active changes.

The release is replaced by upgrading it from zero rather than uninstalling it
(MCW-a0hu): the part scales the release's workloads to zero if a crashed run left any
up, deletes its volume claims and the out-of-band test volume, waits until they are
gone, creates the namespace's Secrets from development values, and upgrades the
release, which restores the replica counts, so every pod starts new on the images
just built against empty volumes. Uninstalling every time is needless work, and
cycling pods over kept volumes would start the new code on databases the previous
commit migrated. An upgrade the chart refuses falls back to uninstalling and
installing, said in the step's detail.

The scenarios run as a pod inside the namespace, from the change's own test image
and the release's in-cluster configuration, reaching services by name as the
pipeline's lanes do on their compose network (MCW-notv); no local port is involved,
since forwarding free ports per validation would need every scenario's addresses and
the registry's published address overridden. Afterwards the part keeps every pod's
log, the namespace's events, the other namespaces' replica counts, and the rendered
requests and limits beside the previous validation's, then scales the namespace to
zero, keeping objects and volumes: leaving releases running would grow resident
memory with the active changes. Without a change named, the part deploys into
`default` on bare tags, refusing a release volume an earlier install kept.

### Memory is shared, and checked by estimate

The node's memory is the one resource the namespaces still share. A preflight
compares the releases that would then be running, times the memory one release was
last measured to need, with the node's allocatable memory, and fails a deployment
that would not fit as environmental (MCW-7bia). It is an estimate that reserves
nothing: two preflights can pass together. A reservation held from preflight to
scale-to-zero would bring back the cross-change coordination per-change namespaces
and tags removed, and recovery of a lease a crashed validation left, to prevent a
failure that costs one rerun.

A pod that then fails for memory is classified from the evidence the part kept, as
any failure is, since a commit that raises a request, lowers a limit, or leaks fails
the same way (MCW-epkd): unscheduled or evicted while another change's release was
up is contention, environmental whatever the resources, with any resource change
named beside the remedy; killed at its own limit, with the limit in the rendered
resources and no node pressure, is the commit's; anything else is of unknown cause.

The figure, in `helm/validation-capacity.toml`, is written by archive cleanup from
the change's latest validation, and only when that validation measured memory, so
a cluster with no metrics source leaves it absent and the preflight warns that it
skipped its check; installing a metrics source cluster-wide for an advisory check
was rejected. Archive cleanup also removes the change's namespace and images
(MCW-7ts3). The figure is advisory and expected to be overwritten often — no
branch's measurement is of the merged code, branches differ little, and it creeps
up as the code grows — so a merge conflict over it keeps the later measurement.

### Evidence only a push produces

The `ci` part dispatches, on the change's branch, each workflow a complete section
owes, and judges the owed job and its observation from the run of the validated
commit (MCW-gvqb, MCW-7hr1). It dispatches only workflows on a fixed list in its
script, `scripts/ci_evidence.py`, which holds `tests.yml` (MCW-3i99): three workflows
that accept a dispatch publish, so a plan line naming one would publish from a
feature branch, and a list in the script binds interactive runs too, which the step
table does not. Only the owner extends the list.

`tests.yml` fails on `dev` in jobs unrelated to any change, so judging the run's
conclusion would fail every such validation, and judging the owed jobs alone would
let a job the commit broke pass unseen. Every other failing job is therefore
compared, failure by failure, with the same job in the latest completed run of the
workflow on `dev` whose commit the branch contains (MCW-2lzw): by each failing test's
ID and exception type, read from the line pytest already prints, or by the failing
step and its error lines where no test is printed. A job status cannot show a failure
inherited, since the branch can break another test in a job already failing; a test
ID alone cannot either, since a test failing on `dev` with a timeout can fail on the
branch another way; the exception type is compared mechanically, so a timeout whose
wording varies raises nothing. A failure the baseline shows too is reported as
already failing on `dev`; any other is diagnosed like any failure, and one with no
baseline to compare is of unknown cause (MCW-3yqn).

## Branches, models, and the clone's bootstrap

Only `main` and `dev` are protected (MCW-farr), so a commit known not to work harms
nothing while it stays on a change branch. A pushed change branch starts nothing by
itself: the pipeline runs on dispatch and nightly, and `tests.yml` on `dev`,
`staging`, and pull requests into them. The pre-push check the guarded push runs is
the same public-content scan this repository's Git hook runs, refusing recognizable
private content in the branch's name and in every outgoing commit, intermediate ones
included, without printing what it matched (MCW-q8vd): this repository is public, and
what a push publishes stays readable after a later commit removes it.

Changes are branched from `dev` and land on it, so the merge before closeout brings
in `dev` unless the owner names another branch (MCW-ca51), and reviews read a change
against `dev`.

The step table names no Fable or Astra model (MCW-y37w): the workflow here never
chooses them.

A clone's bootstrap is `make init` (MCW-uqlq), run in the clone as it is made. Its
failing is almost always the environment, which is why the workflow brings a failed
bootstrap to the owner rather than retrying it.

## Every resource is per change, shared, or checked

The branch, checkout, records, sessions, wheelhouse, environments, evidence,
port-forward state, and chart packages are the clone's; image tags, the namespace,
its releases, volumes, and Secrets are the change's ([The change's
namespace](#the-changes-namespace)). The Docker build cache and the uv and bun caches
are shared, each tool locking its own. Validation forwards no port; a manual forward
serves one namespace at a time. Node memory is shared and checked by the capacity
preflight. CPU and CI runners are shared, so slower, never wrong. The Git remote,
`gh`, and the Claude and Codex accounts are shared, and a usage limit stops every
change's runs at once. No step runs the local compose lanes.

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
| A pre-push check the guarded push runs over what it would send, where the repository provides one | `scripts/check_public_content.py --pre-push`, the public-content scan of the branch's name and every outgoing commit (MCW-q8vd), its local denylist named by Git's `scm.publicContentDenyFile`; the same check `scripts/hooks/pre-push` runs |
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
| The pre-push check's path, a Python script run as a command with the engine's interpreter, never imported | `scripts/check_public_content.py` |
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

## Current limits

- A container per change, with its own Docker daemon and cluster, is not built:
  clones and per-change namespaces have kept every step and validation apart, at a
  fraction of its cost. It would be reopened when a validation fails because two
  changes' releases contend for one node, or two changes need cluster-scoped
  resources a namespace cannot separate; when side-by-side validations become
  routine, with several changes orchestrated from one session; or when unattended
  steps are to be sandboxed from the owner's files.
- Two releases at once may exhaust the node's memory: the capacity preflight is an
  estimate, and stays inactive on a cluster with no metrics source, which has no
  recorded figure.
- The Helm run serves only the scenarios the default charts can: the charts lack the
  pipeline's full topology, which
  [`helm-e2e-pipeline-parity`](../../changes/helm-e2e-pipeline-parity/proposal.md)
  owns.
