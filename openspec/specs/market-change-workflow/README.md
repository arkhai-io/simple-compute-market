# How this repository runs the change workflow

The change workflow ([`change-workflow`](../change-workflow/README.md)) asks each
repository that adopts it to fill a set of roles. This document says how this
repository fills them, and why its own part of the workflow — validation's parts, the
isolation of each change's Helm validation, its workflow values, and its checks — is
shaped as it is. The [specification](spec.md) states this repository's requirements, and its
[index](index.md) organizes them by id.

## This repository is the workflow's first adopter

The workflow is meant to be adopted by other repositories, and what every adopting
repository will need is worked out here first. A general requirement in
`change-workflow` states the rule and where a repository's part plugs in —
validation's parts are the repository's (CW-zkhs); the push refuses the repository's
protected branches (CW-59c7) and runs its pre-push hook where it declares one
(CW-p7kq); each step runs on the models the repository prefers (CW-ebmo); the clone's
bootstrap is the repository's (CW-8npg) — and this capability states what this
repository adds. It is the shape every adopting repository's own capability will
have: the workflow's rules hold no repository's values, so a repository's values
never need to be read out of them. The engine holds none either: this repository's
values are fields of its workflow configuration, `.agents/workflow.toml` (MCW-5tgp),
and the branch a change lands on and the remote it is pushed to are read from Git.

## Validation's parts

Validation describes one commit and fixes nothing (CW-a7dw, CW-af15). What evidence
a commit of this repository needs follows from what it ships — Python packages built
into wheels, services deployed by Helm charts, and end-to-end scenarios across
several market lanes — so `.agents/workflow.toml` declares four parts (MCW-r4tx):
`pipeline`, the end-to-end pipeline, dispatched by `make run-e2e` and collected by
`make fetch-e2e-logs`; `ci`, owed, dispatched once per owed workflow by `make run-ci`
and judged by `make validate-ci`; `local`, `make validate-local`; and `helm`, `make
validate-helm`, declared after `local`, never beside it, since the two share Docker
and the CPU. The two dispatches start first, the pipeline being the slowest. Each
dispatch ends its output with the bare id of the workflow's newest run before it,
the marker its collect waits past. A preflight, `make check-uv-version`, runs before
every part. No local suite stands in for the pipeline, and the pipeline does not
deploy the charts, so each part reports what only it can show. A validation for which
the owner wants every Helm scenario, or another cluster, passes `HELM_ALL_SCENARIOS`
or `HELM_CONTEXT` through the environment, which the Helm part's targets read; they
are values of the owner's machine, not of the configuration.

Each part keeps its evidence under `.snapshot/`: the local and Helm parts under
`.snapshot/validation/<commit>/`, the `ci` part its job logs under
`.snapshot/validation/<short commit>/ci/`, and the pipeline its logs under
`.snapshot/e2e-logs/<run>/`. These are the evidence directories a change's records
name, which `make change-history` copies into the owner's workspace and which move
with a change into its clone.

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

`make validate-parallel CLONES="<clone> <clone>"` checks that isolation on the
development cluster: it runs two clones' Helm parts at the same moment and reports
whether each kept to its own namespace, tags, and scenario pod, and left the other's
release, volumes, and pods untouched, under `.snapshot/parallel-validation/<time>/`.
It deploys two changes' releases, so it is a check of the tooling run by hand, not
part of any change's validation.

The Helm targets carry the namespace and the tags:

- **The namespace's name.** `validate-<change>`, cut to 63 characters with the first
  eight hex digits of the full name's SHA-256 appended when longer
  (`scripts/change_namespace.py`). Every `helm/Makefile` target that takes
  `NAMESPACE=` also takes `CHANGE=`, deriving the namespace the same way; giving both
  is refused. Release names do not change with the namespace, so the in-cluster
  Service names `helm/local-values.yaml` states resolve in every one, and the
  two-release topology fits in it.
- **The tags.** Every build target appends `IMAGE_SUFFIX`, empty by default: `make
  build-dev IMAGE_SUFFIX=-<change>` builds `arkhai:storefront-<change>` and its
  siblings, and the deploy names them through a values overlay naming every `arkhai`
  image `helm/values.yaml` sets (`change_namespace.py <change> --image-overlay
  <path>`); a render test holds the overlay to every image the chart renders, so an
  image added later cannot deploy under its bare tag. Compose, the pipeline lanes, and
  an operator's own deployments keep bare tags. A suffixed build writes no commit tag;
  a bare build still writes `arkhai:<tag>-<sha>`, which `make push-images` reads.
- **The upgrade.** The volumes deleted are the release's volume claims and the deal
  test's `arkhai-buyer-profiles`; `topology-secrets` creates the namespace's Secrets;
  `helm upgrade --install` runs with `local-values.yaml` and the change's image
  overlay, then each workload's replica count is restored and its rollout awaited.
  The chart's refusal that falls back to uninstalling is `field is immutable`.
- **Afterwards.** `make -C helm resume CHANGE=<change>` scales the namespace back to
  the replica counts the installed release states, rendering nothing from the
  checkout. `make -C helm forward CHANGE=<change>` forwards its services on the usual
  ports (8545, 8080, 8001, 8081) for running end-to-end targets by hand; the ports are
  the same for every namespace, so a port another checkout already forwards fails to
  bind, and `forward` names it and stops.
- **Teardown.** Archive cleanup records the capacity figure with `make
  record-capacity` ("Memory is shared, and checked by estimate" below), then runs
  `make -C helm teardown CHANGE=<change>`, which deletes the change's namespace in
  `HELM_CONTEXT` (`docker-desktop` by default), with every release, volume, and
  Secret in it, and removes each image the change's validation build tagged. It
  takes `CHANGE=` only, so it never deletes `default`.

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
what a push publishes stays readable after a later commit removes it. Beside it runs
the hook's second check, the pinned gitleaks over the same commits, which refuses
private keys and provider credentials, likewise without printing them. Both are one
make target, `make pre-push REMOTE=<remote>`, which the configuration's `pre-push`
and the Git hook `scripts/hooks/pre-push` both run (MCW-k3vy), so the pair is
defined once.

Changes are branched from `dev` and land on it: an orchestrating session started
with `dev` checked out records `dev` as the change's landing branch, which the merge
before closeout brings in and reviews read the change against, which a prerequisite
change is proposed from, which the orchestrating session merges into a change's
branch on the owner's word, and whose latest completed CI run is the baseline the
`ci` part compares failures with. Nothing here makes `dev` a default: a change whose
clone was made from another branch lands there.

The make fragment's targets complete in bash: source
`scripts/completions/make-change.bash` from `~/.bashrc`, after bash-completion, to
complete `CHANGE=` with the active changes — the archived ones after
`archive-cleanup`, and both after `merge` — and `KIND=` with the review kinds. The
script lives outside the engine's package though it completes the fragment's targets.

The configuration names each step's models (`[models]`): Opus at high effort for the
steps that judge, Sonnet at medium for validation and archive cleanup, and Codex
first for the review, falling back to Claude. It sends a review's refused draft back
to its reviewer once (`[review]`'s `format-retries`), the workflow's default, stated
so a reader of the file finds it.

A clone's bootstrap is `make init` (MCW-uqlq), the configuration's `post-clone`, run
in the clone as it is made. Its
failing is almost always the environment, which is why the workflow brings a failed
bootstrap to the owner rather than retrying it.

## This repository's checks

Some written rules of this repository were breached often enough that reviews kept
finding them, a written rule nothing checks being a finding waiting to be raised. A
check moves each from a review's finding to the change's own work, where the agent
that breaks it finds it before anyone reads the change.

### What each check enforces

Each check that enforces guidance, the rule it enforces and that rule's layer, and
where the check runs. The first four are the workflow's default checks, which its
engine runs; every other is this repository's script, even where its rule is the
workflow's or the engineering guidance's.

| Check | Rule it enforces | Rule's layer | Where it runs |
|---|---|---|---|
| Change index (`scripts/change-workflow check index`; `make check-change-index`) | each row's cells, link, status, and dependencies; one row per active change ([`changes.md`, "The change index"](../../../docs/guidance/workflow/changes.md#the-change-index); [`closeout.md`, "Campaign index currency"](../../../docs/guidance/workflow/closeout.md#campaign-index-currency)) | workflow | the workflow's default checks, in every committing step's `run pre-commit` and in `make check-change` |
| Task list (`scripts/change-workflow check tasks`; `make check-tasks`) | every numbered task sits under its own section's heading ([`change-workflow`'s companion, "The command and its tiers"](../change-workflow/README.md#the-command-and-its-tiers)) | workflow | the default checks; implementation's entry check |
| Agent skills (`scripts/change-workflow check skills`; `make check-agent-skills`) | each skill has one source for every harness ([`change-workflow`'s CW-d8de](../change-workflow/spec.md#requirement-cw-d8de-each-skill-has-one-source-for-every-harness)) | workflow | the default checks; the packaging closeout part ([`openspec/README.md`, "Packaging"](../../README.md#packaging)) |
| Strict OpenSpec validation (`scripts/change-workflow openspec validate <change> --strict`) | a change's delta requirements are well formed and carry scenarios ([`openspec-documentation.md`, "Capability documentation pattern"](../../../docs/guidance/workflow/openspec-documentation.md#capability-documentation-pattern)) | workflow | the default checks; closeout's "Documentation citations", last before the archive |
| Comment hygiene (`make check-comment-hygiene`) | no change id, section or task number, change document's name, or change directory's name in code ([`change-references.md`](../../../docs/guidance/workflow/change-references.md)), over the file types, exclusions, and exemption [The closing checks](#the-closing-checks) names | workflow; its file types and exemptions the repository's | `make check-repository`; closeout's "Comment hygiene" |
| Documentation citations (`make check-doc-citations`) | a cited path resolves and is no tombstone ([`documentation.md`, "Citations resolve"](../../../docs/guidance/engineering/documentation.md#citations-resolve)), over the directories and documents [The closing checks](#the-closing-checks) names | engineering; its directories the repository's | `make check-repository`, scoped to the change; closeout's "Documentation citations" |
| Specification index (`make check-spec-index`) | an indexed capability's `spec.md` and `index.md` agree on its ids, the change's deltas counted ([`openspec-documentation.md`, "A capability organized by an index"](../../../docs/guidance/workflow/openspec-documentation.md#a-capability-organized-by-an-index); [`openspec/README.md`, "The index check"](../../README.md#the-index-check)) | workflow | `make check-repository`; closeout's "Promotion" |
| Decision destinations (`make check-decision-destinations`) | each decision has a "Knowledge to promote" bullet ([`changes.md`, "Change documentation requirements"](../../../docs/guidance/workflow/changes.md#change-documentation-requirements)) | workflow | `make check-repository` |
| History wording (`make check-history-wording`) | a comment or docstring the change adds describes no history ([`comments.md`, "Comments describe the current system"](../../../docs/guidance/engineering/comments.md#comments-describe-the-current-system)) | engineering | `make check-repository`, against the merge-base with the landing branch |
| Version bumps (`make check-version-bumps`) | a package's version moves at most one step from the landing branch's ([`versioning.md`, "One bump per unit of work"](../../../docs/guidance/engineering/versioning.md#one-bump-per-unit-of-work)) | engineering | `make check-repository`, against the merge-base |
| Local imports (`make check-local-imports`) | an import added inside a function gives its reason ([`dependencies-python.md`, "Imports go at module level"](../../../docs/guidance/engineering/dependencies-python.md#imports-go-at-module-level)) | engineering | `make check-repository`, against the merge-base; closeout's "Import placement" |
| Capability index (`make check-capability-index`) | every capability with a `spec.md` has a row in the capability index, and no row links nothing ([`openspec/README.md`, "Current capability documentation"](../../README.md#current-capability-documentation); the index's role, [`openspec-documentation.md`, "The capability index and the roadmap"](../../../docs/guidance/workflow/openspec-documentation.md#the-capability-index-and-the-roadmap)) | repository | `make check-repository` |
| `dist`, the prerequisite of `make check-packaging` | none: it builds the wheelhouse the checks read | — | `make check-packaging` |
| `make check-uv-setup` | internal packages are derived from the lock, never listed ([`packaging.md`, "Nothing is maintained by hand"](../../../docs/guidance/engineering/packaging.md#nothing-is-maintained-by-hand); [`packaging-uv.md`, "Refreshing a same-version wheel"](../../../docs/guidance/engineering/packaging-uv.md#refreshing-a-same-version-wheel)), through `scripts/uv_project.py` ([`BUILD_AND_PACKAGING.md`, "The wheelhouse"](../../../docs/development/BUILD_AND_PACKAGING.md#the-wheelhouse)) | engineering; the script the repository's | `make check-packaging`: the functional pre-commit hook, the pre-archive hook, and validation's local part |
| `make check-locks` | every lock is current and resolves internal packages from the wheelhouse ([`packaging-uv.md`, "Relock against fresh artifacts"](../../../docs/guidance/engineering/packaging-uv.md#relock-against-fresh-artifacts)), at the one lock revision ([`packaging-uv.md`, "Locks are written by a stated minimum uv"](../../../docs/guidance/engineering/packaging-uv.md#locks-are-written-by-a-stated-minimum-uv); [`BUILD_AND_PACKAGING.md`, "Locks"](../../../docs/development/BUILD_AND_PACKAGING.md#locks)) | engineering; the revision and `.dist` the repository's | `make check-packaging`, wherever it runs |
| `make check-python-version` | every consumer reads the one runtime declaration ([`packaging.md`, "One declaration of the runtime version"](../../../docs/guidance/engineering/packaging.md#one-declaration-of-the-runtime-version)) | engineering | `make check-packaging`, wherever it runs |
| `make check-project-layout` | one import package, built with nothing remapped and installed editable ([`packaging-python.md`](../../../docs/guidance/engineering/packaging-python.md); [`packaging-hatchling.md`](../../../docs/guidance/engineering/packaging-hatchling.md); [`packaging-uv.md`, "Every project installs itself editable"](../../../docs/guidance/engineering/packaging-uv.md#every-project-installs-itself-editable) and "No source path to a sibling") | engineering | `make check-packaging`, wherever it runs |
| `make check-architecture` (its parts `layers`, `scope`, `dependencies`, `kinds`) | the package layer, scope, and kind rules ([`ARCHITECTURE.md`, "Package and dependency layers"](../../../docs/development/ARCHITECTURE.md#package-and-dependency-layers)); its `dependencies` part also a package's declaring what it imports ([`dependencies.md`, "Declare what you import"](../../../docs/guidance/engineering/dependencies.md#declare-what-you-import)) | repository; its `dependencies` part engineering too | `make check-packaging`, wherever it runs; CI's `tests.yml`, on pushes and pull requests to `dev` and `staging` |
| `make check-architecture-change` | a change owns no architecture exception or override row when archived ([`ARCHITECTURE.md`, "Where the current tree diverges"](../../../docs/development/ARCHITECTURE.md#where-the-current-tree-diverges)) | repository | the pre-archive hook; the packaging closeout part |
| `make check-uv-version` | the installed uv meets the minimum that writes the locks ([`packaging-uv.md`, "Locks are written by a stated minimum uv"](../../../docs/guidance/engineering/packaging-uv.md#locks-are-written-by-a-stated-minimum-uv)), the minimum itself in [`BUILD_AND_PACKAGING.md`, "Locks"](../../../docs/development/BUILD_AND_PACKAGING.md#locks) | engineering; the minimum the repository's | `make lock`; validation's preflight |
| Public content (`scripts/check_public_content.py`; `make check-public-content`, with the secret scan) | no recognizable private content in what is published ([`repository-content.md`, "In a public repository"](../../../docs/guidance/engineering/repository-content.md#in-a-public-repository), selected in [`AGENTS.md`, "Exceptions to shared guidance"](../../../AGENTS.md#exceptions-to-shared-guidance)), by the patterns of [Public repository content checks](#public-repository-content-checks) | engineering; the patterns the repository's | the Git pre-commit hook, over staged additions; `make pre-push`; CI's `public-content.yml` |
| Secret scan (`scripts/check_secrets.py`, gitleaks; `make check-secrets`) | no private key or provider credential ([`repository-content.md`, "No credentials"](../../../docs/guidance/engineering/repository-content.md#no-credentials)) | engineering | the Git pre-commit hook; `make pre-push`; CI's `public-content.yml` |
| `make pre-push` | the two rows above, over what a push would send | as the two rows above | the Git pre-push hook (`scripts/hooks/pre-push`) and the guarded push (`[hooks].pre-push`) |
| `make audit-secrets` | reports every gitleaks finding in the tracked tree and refuses nothing ([`repository-content.md`, "No credentials"](../../../docs/guidance/engineering/repository-content.md#no-credentials)) | engineering | by hand before a release ([`RELEASING.md`, "Cutting a release"](../../../docs/development/RELEASING.md#cutting-a-release)); listed so the table is complete |
| Guidance check (`make check-guidance`) | every guidance file's tags against the vocabularies, the exception tables, the link direction, and the anchors of guidance citations (`change-workflow`'s CW-g7lt, CW-d2rw, and CW-x4ex; [MCW-c4ek](spec.md#requirement-mcw-c4ek-a-changes-closing-checks-enforce-written-rules)) | workflow, enforced from this repository's script | `make check-repository`; closeout's "Guidance placement" |

### The closing checks

Every step that commits runs `scripts/change-workflow run pre-commit <change>`: the
workflow's default checks — the change index, the task list, the skills, and the
strict OpenSpec validation through `scripts/openspec`, which runs the pinned
validator through `bunx`, else `npx --yes` — then this repository's `pre-commit`,
`make check-repository` (`scripts/check_change.py`), and, before a commit changing a
path outside the inert paths `.agents/workflow.toml` declares (`openspec/`, `docs/`,
every `README.md`, and `AGENTS.md`), the relock and then the wheelhouse cleared, the packaging
check, and every suite first (MCW-r4tx). The owner's complete closing
check stays `make check-change CHANGE=<change> [CHANGE_BASE=<branch>]`, which runs
the same `run pre-commit`, unrestricted as any interactive session's hooks are, so
no check runs twice and the familiar target is never partial.

`make check-repository CHANGE=<change> CHANGE_BASE=<branch>`
(`scripts/check_change.py`) prints only failures and one pass line. It runs comment
hygiene, the change's documentation citations, and each indexed capability's
`spec.md` against its `index.md` with the change's deltas counted (`make
check-spec-index`), and holds five of the rules beside them (MCW-c4ek):

- each `### D<n>` decision under `design.md`'s `## Decisions` has a bullet starting
  `D<n>` in `proposal.md`'s "Knowledge to promote", `D<n>: no permanent destination
  — <reason>` where it has nothing to promote (`make check-decision-destinations`);
- no comment or docstring line the change's diff adds in a `.py`, `.toml`, `.yml`,
  or `.yaml` file says "previously", "formerly", "used to", "no longer", "moved
  from", "was renamed", or "originally" (`make check-history-wording`);
- each `pyproject.toml` version the diff changes is at most one SemVer step from its
  version at the merge-base, which admits a larger bump replacing a smaller one
  (`make check-version-bumps`);
- each import the diff adds inside a function has a comment giving its reason
  (`make check-local-imports`);
- every capability with a `spec.md` has a row in `openspec/specs/README.md`, and
  every row links one (`make check-capability-index`).

Three of them read the change's diff from its merge-base with the branch it lands
on — the clone's recorded branch, `find --json`'s `base`, unless `CHANGE_BASE` names
another, refusing, naming how to give it, with neither, as for a change worked in the
owner's workspace with no clone — since against the wrong branch a prerequisite's
commits read as the change's own. None keeps an exception marker: a false positive
is reworded, or the rule amended. Whether an import's reason is sound, and whether a
test sits at the level that can prove its behaviour, stay with review, which a
pattern cannot judge.

Comment hygiene, `make check-comment-hygiene`, holds
[`change-references.md`](../../../docs/guidance/workflow/change-references.md)
outside `openspec/`: it fails on a change id, a section or task number, or a change
document's name in a `.py`, `.yml`, or `.yaml` file, and on a change directory's name
in those and `.toml` files outside `docs/`, which holds the roadmap, and `.claude/`.
Its one exemption is each file name's definition in the script that reads it
(`next_step.py`'s `TASKS_FILE`, `check_decision_destinations.py`'s `DESIGN_FILE` and
`PROPOSAL_FILE`). A comment's stable heading is in `openspec/specs` or
`ARCHITECTURE.md`, as in:

```python
# Fulfillment may depend on site and resource-pool authorities; those lower
# layers must not import fulfillment, including under TYPE_CHECKING.
# See openspec/specs/fulfillment/spec.md#dependency-boundary.
```

The citation check, `make check-doc-citations`, checks every `openspec/`, `docs/`,
`tools/`, `scripts/`, `e2e-tests/`, and `.agents/` path cited in the Markdown under
`openspec/specs/` and `docs/`, the change index, and every unarchived change's
documents but its `reviews/`. It treats a citation whose target does
not resolve as a blocking defect, and additionally rejects a citation pointing at a
*tombstone*: a tombstoned file still exists on disk while its content is gone, so a
plain existence test could never fail on a rename-to-tombstone — the likeliest
broken citation in a renaming change. Closeout runs it scoped to the change; run
unscoped, it shows the repository-wide picture.

### One lock revision

Every committed `uv.lock` carries the lock revision the repository's minimum uv
writes, and `make check-packaging` fails on one that carries another (MCW-l5rv).
Agents running different uv releases rewrote each other's locks back and forth, and
nothing caught it: the minimum admitted both releases, an environment refresh checked
no version, and the lock check asked only whether a lock satisfied its project. The
minimum is therefore the first release that writes the repository's revision, and the
repository's relock and environment refresh commands refuse an older uv before
running it; a plain `uv run` that relocks a changed project is not guarded, and the
revision check fails on what it writes before it lands. Making every `uv run` pass
`--locked` was rejected: it would touch most Makefiles and need a check of its own,
and still leave a hand-typed `uv run` unguarded. The check is a minimum, not an exact
pin, so a newer uv still runs; the revision check stops its rewrite landing unseen.
The minimum, and how to bring a lock to the running uv's revision, are in
[`BUILD_AND_PACKAGING.md`, "Locks"](../../../docs/development/BUILD_AND_PACKAGING.md#locks).

### Public repository content checks

This repository selects the public case of the engineering guidance on what enters a
repository ([`AGENTS.md`, "Exceptions to shared guidance"](../../../AGENTS.md#exceptions-to-shared-guidance)),
and two checks read content about to be published: `scripts/check_public_content.py`,
the repository's own rules below, and `scripts/check_secrets.py`, which runs the
gitleaks secret scanner for private keys and provider credentials. They run
together. `make check-public-content` runs both over the staged index, and `make
check-secrets` the second alone. The guarded branch push checks every outgoing
commit, including intermediate additions and commit messages. The Public content
CI workflow checks commits against the event base, using `origin/dev` for a
new branch without a previous tip. This retains inspection of every commit outside
the product branch, including intermediate changes, without treating existing
product history as newly published work. It runs after publication and therefore
provides detection rather than preventing the first upload.

The scanner rejects literal personal home paths and private assistant
planning/session paths. `example-user` is the synthetic fixture username;
`appuser` and `ubuntu` are documented runtime-image accounts, and `you` is an
example placeholder. These names do not authorize publishing actual operator
paths. Machine-specific names, addresses and other operational identifiers require
a private local literal denylist; arbitrary identifiers, and secrets in no format
the secret scan recognizes, are not automatically recognizable. Binary additions
are refused because this text scanner cannot inspect them. Review remains required.
Diagnostics report location and rule without echoing matched content.

Enable the repository-owned hooks in each checkout with
`git config --local core.hooksPath scripts/hooks` after inspecting any existing
hooks configuration; preserve or chain existing hooks instead of overwriting them.
The pre-commit hook checks staged additions. The pre-push hook checks the actual
refs being sent, including ref names and annotated tag content. Each hook runs both
checks and refuses when either does. Hooks and the guarded push require Python 3.11
or newer and the pinned gitleaks; hooks may be bypassed by direct
Git options; they are local safeguards, not server enforcement. Use the guarded
`make push-branch` path for agent pushes.

Configure deployment-specific literals with
`git config --local scm.publicContentDenyFile /absolute/path/to/private-denylist.txt`.
Keep that file outside the repository, one literal per line; blank lines and
lines starting with `#` are ignored. Matching is case-insensitive. Never commit
the denylist or use real identifiers in guard tests. A configured file that cannot
be read fails the check. A CI runner without that private file runs the generic
rules only. Fetch the target remote before checking outgoing commits. Use
`python3 scripts/check_public_content.py --base <commit>` to inspect a known
committed range; this is not a complete historical secret audit.

Private keys and provider credentials are recognized by
[gitleaks](https://github.com/gitleaks/gitleaks) at the release
`scripts/gitleaks-pins.toml` pins; `make install-gitleaks` installs it, refusing an
archive whose sha256 is not the pinned one, and a check that finds no gitleaks, or
another release, refuses and names that command. The gate, `.gitleaks.toml`, runs
wherever `check_public_content.py` runs and reports locations, never content.
`make audit-secrets` runs the gate's rules and the three default rules it turns off
over the tracked tree, gates nothing, and is run before a release ships. The gate's
rules, the audit, and what both leave to review are "Secret scanning", below.

### Secret scanning

The public-content checks — the hooks, the guarded push, and the Public content
workflow ([Public repository content checks](#public-repository-content-checks))
— refuse private keys and provider credentials (MCW-s8gk) through gitleaks rather than rules
of the repository's own: a maintained scanner knows far more credential formats
than the repository could keep current. Every check runs one release, pinned with
each platform's sha256 in `scripts/gitleaks-pins.toml`, so a finding means the same
on every machine and in CI. Findings are redacted to rule, file, line and commit.
`gitleaks:allow` comments are ignored, since the repository keeps no exception
markers. Commit ranges are read with merges compared with each parent
(`--diff-merges=separate`): gitleaks reads commits through `git log -p`, which
otherwise prints no patch for a merge, so a key written only in a merge resolution
would go unseen.

The gate, `.gitleaks.toml`, is gitleaks' default rules but four. Gitleaks'
`private-key` rule accepts any 64 or more characters between a `BEGIN … PRIVATE
KEY-----` header and the next `KEY-----`, so a short test fixture's own END marker
comes too soon to end a match, which runs on into the next block and reads two
fixtures in one file as one key. The repository replaces it with
`private-key-block`, which keeps the 64-character minimum body but admits no run of
five dashes in it, so a match ends at its own block's END marker: a real key's body,
wrapped at any length or written as one string of `\n` escapes, is refused, and a
fixture whose body is a word passes however many share a file. The three other
rules turned off — `generic-api-key`, `jwt`, `curl-auth-header` — match the
repository's own fixtures and code as readily as secrets; `.gitleaks.toml` gives
the reason for each beside the list. The provider-specific rules stay, because
they match fixed formats that almost never misfire. A later fixture that trips one
is another entry in the gate's list, never a marker beside the fixture.

`scripts/tests/test_check_secrets.py` scans the whole tracked tree under the gate
and asserts it finds nothing, under any rule. A gitleaks release whose new rule the
tree trips therefore fails that test when the pin moves, rather than at someone's
commit, and a release is changed only with it passing.

The audit, `make audit-secrets`, runs the configuration the gate extends (MCW-u2dt),
`scripts/gitleaks-audit.toml`: every default rule but `private-key`, and the
repository's key rule. It scans `HEAD`'s tracked tree, read as one parentless
commit of `HEAD^{tree}` in a temporary clone, so nothing untracked or ignored is
read. It refuses nothing and keeps no baseline: most of what it lists is the
development fixtures the gate passes, and a baseline would have to be kept in step
with them. It is run by hand before an official build ships
([`RELEASING.md`, "Cutting a release"](../../../docs/development/RELEASING.md#cutting-a-release)).

The gate cannot see two things, and review remains the safeguard for both. A key
body edited beneath an unchanged header is invisible to a scanner reading the
change's patch, which holds no header. A random credential in no provider's format
— a generated password, say — has the character class of the identifiers
`generic-api-key` matched, so the gate does not look for it; the audit reports that
class across the whole tree, except a credential holding one of the rule's stop
words — common words such as `menu` or `boot` — since `generic-api-key` passes any
value holding one.

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
states it; the provision is what fills it here: a field of this repository's
workflow configuration, `.agents/workflow.toml`, or what the configuration does not
hold. A test (`scripts/tests/test_change_workflow_assumptions.py`) fails when a make
target or repository path the workflow's skills, its step table, or its make fragment
name, the fragment's own targets among them, is missing from these two tables and
from the configuration's commands, or when the two documents' roles differ.

| Role | Provided by |
|---|---|
| Local validation of a commit: the repository's own checks and suites against the commit, built from it | the configuration's validation preflight, then its `local` part; `scripts/validate_slice.py`, which runs the local and Helm parts against the commit, clearing the wheelhouse first, and writes their evidence under `.snapshot/validation/`; the family `make validate-*` the step table grants the steps that fix code |
| Validation in a deployed environment: the change's services built and run as the repository deploys them | the configuration's `helm` part, after `local`; `make validate-parallel*`, and the chart's render checks `make -C helm test-render`, in the change's own namespace, within the capacity `helm/validation-capacity.toml` records |
| The end-to-end pipeline: a run whose head is the commit, its logs fetched | the configuration's `pipeline` part, dispatching the run and collecting its logs into `.snapshot/e2e-logs/`; the scenarios under `e2e-tests/`; the step table denies `make run-e2e*` to the steps that fix code |
| CI evidence only a push produces: the workflows validation may dispatch, from a fixed list | the configuration's owed `ci` part, dispatching only the workflows `scripts/ci_evidence.py` lists |
| Removing a change's validation resources, and recording what they used, at archive cleanup | the `helm` part's `cleanup`, recording the capacity measured into `helm/validation-capacity.toml`, then removing the change's namespace and images |
| The repository's tests and environments: the suites, locks, builds, and environment refreshes a change's work runs | the configuration's `after-functional-change`, `make lock`, and `pre-commit-functional`, `make dist-clean`, `make check-packaging`, and `make test`; the step table's grants for engineering work: `make test` and `make test*`, `make -C * test*` in a project (`make -C <package> test`), and one project's tests run directly as `uv run --directory * pytest *`, `uv run --project * pytest *`, or `uv run --find-links * pytest *`; `make lock`, `make lock*`; `make dist*`, `make -C * dist*`; `make init*`, `make -C * init*`; `make reinit*`, `make -C * reinit*`, and `make typecheck*`, the targets of a project's own `Makefile`; `uv lock --directory *`, a new project's first lock; a section's local bring-up, `make -C * migrate*` (`make -C <package> migrate`), `docker run --rm *`, and `docker compose -p *` up, down, ps, and logs under a project name of the session's own; `make build-*`, the images a lane runs, `make -C * e2e-*-down`, a lane's teardown, and `make -C e2e-tests e2e-*-logs`, its containers' logs; `make helm-values-schema`; internal dependencies from wheels and locks through `scripts/uv_project.py` |
| The packaging check before closeout | the configuration's `pre-commit-functional` and `pre-archive`: `make check-packaging`, which runs `make check-architecture` over `docs/development/ARCHITECTURE.toml`, and `make check-architecture-change` |
| The closing checks a step ends with | the configuration's `pre-commit`, `make check-repository` (`scripts/check_change.py`), after the workflow's default checks; `make check-change`, the owner's complete closing check, which runs `scripts/change-workflow run pre-commit`; the checks they run and the step table grants as `make check-*` and `scripts/check_*`: `make check-comment-hygiene`, `make check-doc-citations` (`make check-doc-citations*`), `make check-spec-index` |
| The change index at a known path | `openspec/changes/README.md`, checked in a prerequisite's proposal checkout beside this one by `make -C ../<prerequisite>-proposal check-change-index` (`make -C ../*-proposal check-change-index`) |
| The guidance documents every step reads | `AGENTS.md`, `docs/development/ARCHITECTURE.md`, `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, `openspec/README.md`, its closeout parts `openspec/README.md#this-repositorys-closeout-parts`, and the shared guidance under `docs/guidance/`, every Markdown file beneath it: the workflow's under `docs/guidance/workflow/` and the engineering guidance under `docs/guidance/engineering/`; the roadmap `docs/development/ROADMAP.md`, which design loads too; and `openspec/config.yaml`. The owner's handbook, `docs/change-workflow-handbook.md`, is no guidance and no step reads it |
| Where specifications and documentation live | `openspec/` (`openspec/**`): the capabilities under `openspec/specs/`, indexed by `openspec/specs/README.md`, each `openspec/specs/<capability>/spec.md`; and `docs/` (`docs/**`), its development documents under `docs/development/` and its shared guidance under `docs/guidance/`, the workflow's under `docs/guidance/workflow/` and the engineering guidance under `docs/guidance/engineering/` |
| Protected branches the guarded push refuses | `main` and `dev`, the configuration's `repository.protected-branches` |
| A pre-push check the guarded push runs over what it would send, where the repository provides one | the configuration's `pre-push`, `make pre-push`, which runs `scripts/check_public_content.py --pre-push`, the public-content scan of the branch's name and every outgoing commit (MCW-q8vd), its local denylist named by Git's `scm.publicContentDenyFile`; then `scripts/check_secrets.py --pre-push`, the pinned gitleaks over the same commits; the same target `scripts/hooks/pre-push` runs. A step runs the gate over its staged additions with `make check-secrets`, and the audit of every rule with `make audit-secrets` |
| The remote a change's branch is pushed to, its upstream's, from which the pipeline runs | `origin`, this repository on GitHub, which every branch of the workspace tracks, so a change's clone gives its branch an upstream there |
| The branch a change lands on, merged before closeout and reviewed against | the clone's `--from`, or else the branch the workspace had checked out when the change's clone was made, `dev` for most changes, which the clone records |
| The clone's bootstrap: one command that readies a fresh clone | the configuration's `post-clone`, `make init` |
| The make fragment's targets, included by the repository's `Makefile` | `Makefile` includes `scripts/change_workflow/workflow.mk`, giving `make design`, `make plan`, `make implement`, `make review`, `make triage`, `make validate`, `make merge`, `make closeout`, `make archive-cleanup`, `make orchestrate`, `make change-next`, `make change-clone`, `make change-clone-remove`, `make round-view`, `make round-done` (`make round-done*`), `make round-view-closed`, `make change-watch`, `make change-cost`, `make change-history`, `make check-change-index`, `make check-tasks` (`make check-tasks*`), `make check-agent-skills`, `make check-review` (`make check-review*`), `make check-push-ready`, `make push-branch`, and `make change-graph`; run in a change's clone as `make -C <clone> implement`, `make -C <clone> push-branch`, and `make -C <clone> change-history` |

### The engine's own assumptions

How this repository meets what the engine itself holds. The test reads these as
provisions too; whether the table names everything the engine holds is kept by
review.

| Assumption | Here |
|---|---|
| The change index's path | `openspec/changes/README.md` |
| Its command and package, beside each other under `scripts/` | `scripts/change-workflow` and `scripts/change_workflow/`, whose computation and graph the orchestrating skill cites, `scripts/change_workflow/next_step.py` and `scripts/change_workflow/graph.py` |
| The repository's workflow configuration, at a fixed path, checked whenever it is read | `.agents/workflow.toml`, which the step table denies every step to edit |
| The step table, at a fixed path, in Claude Code's permission-rule syntax | `.claude/change-steps.toml`, its rules guarding `.claude/**` and `.agents/workflow.toml`, and granting the engine's `scripts/change-workflow run` for the hooks, `scripts/change-workflow openspec` for the configured OpenSpec command, and `scripts/change-workflow config` |
| The outcome schema, at a fixed path | `.agents/change-outcome.schema.json` |
| The skills' one source, linked into each harness's directory | `.agents/skills`, under `.agents/`, linked from `.claude/` and `.codex/` |
| The harness's local settings, which a clone links to the workspace's | `.claude/settings.local.json` |
| The changes' directory, its archive, and each change's records under `reviews/` | `openspec/changes/`, each change at `openspec/changes/<change>/`, archived under `openspec/changes/archive/` as `openspec/changes/archive/<date>-<change>/`, beside the guidance reviews' untracked period ledger `openspec/changes/archive/guidance-reviews.jsonl`, which no reader of the archive takes for a change; the step table names `openspec/changes/**/reviews/*-validation.md`, `openspec/changes/archive/*/interventions.jsonl`, and `openspec/changes/archive/*/reviews/pull-request.md` |
| The graph diagram's place in this capability | `openspec/specs/change-workflow/diagrams/`, the workflow's own specification being `openspec/specs/change-workflow/spec.md` |
| The `workspace` remote a clone names the owner's workspace by | `workspace`, set by `scripts/change-workflow clone` |
| The harness's session id in the environment, `CLAUDE_CODE_SESSION_ID` | Claude Code's |
| The tools it invokes, `git`, `claude`, `codex`, and `sh`, which runs every command the configuration declares | each on the owner's path; the configuration's commands run `make`, and its `ci` and `pipeline` parts `gh` |

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
