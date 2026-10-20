## Context

The change workflow assumes one change in one checkout. Its state is per checkout,
and most of it is untracked or outside Git: the checked-out branch; `reviews/`, with
the workflow log and transcripts (ignored by `.gitignore`); the round view's state
in the Git directory (`round-view.json`); `.dist` and every project's `.venv`;
`.snapshot/`; `helm/.port-forward.pids`; and Claude Code's session files, which are
keyed by the checkout's path (`scripts/change_workflow/cost.py`,
`conversation_file`), so a waiting run resumes only from the checkout it started
in. Other resources are machine-wide: the Docker daemon's image tags, the kube
release with its namespace and forwarded ports, CPU and memory, and the Claude and
Codex accounts. The end-to-end pipeline is already per branch (`e2e.yml`'s
concurrency group is per ref), and `fetch-e2e-logs` selects a run by its commit.

So nothing in a checkout can commit while validation runs there for its hour
(`scripts/validate_slice.py` fails when `HEAD` moves), and two Helm validations
collide: both deploy `arkhai-node-operator` into `default`, the later one's
`undeploy` removing the earlier one's release mid-scenario.

The design rests on these facts about the current tree, some of which correct the
proposal as first written:

- The orchestrating session exists (`orchestrate-change-workflow`, archived
  2026-10-19) and advances one change in one checkout; orchestrating several
  changes from one session is its named follow-up once this change lands.
- Switching branches in one checkout is not neutral: `reviews/` is ignored, so it
  stays on disk across a switch, `scripts/find_change.py` then finds the leftover
  directory, and `scripts/check_change_index.py` reports it as a change directory
  with no row on any branch whose index lacks the change.
- Git refuses to check out one branch in two worktrees, wherever they are; only
  `--ignore-other-worktrees` overrides it, and then a reset or a commit in one
  worktree rewinds or stales the other (Git 2.44's release notes). Separate clones
  have refs of their own, so one branch name can be checked out in both.
- A namespace does not isolate images. Every image the chart deploys has a fixed
  tag pulled `IfNotPresent` from the one daemon the Docker Desktop cluster reads,
  and `make build-dev` re-tags them, so one validation could deploy another's code.
- The forwarded ports are also in configuration: `e2e-tests/config/config-local.yml`
  addresses localhost, and the registry publishes `baseUrl: http://localhost:8080`.
- `make -C helm topology-secrets NAMESPACE=<ns>` creates every out-of-band Secret
  a deploy and the release's tests read, and the deal test's buyer-profile volume,
  from development values, idempotently.
- No workflow step runs the local compose lanes, so `isolate-end-to-end-lane-stacks`
  does not overlap this change.

## Goals / Non-Goals

**Goals.** Several changes worked at once, each on its own branch in its own clone,
with every step of one running while another's run; the owner reading any change's
committed round, by its branch's name, in their own workspace, while that change's
validation and review run; Helm validations side by side, each in its change's
namespace with its own images, release, volumes, and Secrets; a change's history
kept in the owner's workspace once it is cleaned up, where later sessions find it.

**Non-Goals.** Orchestrating several changes from one session. Two changes'
pipelines on one branch. A container per change (open question 1). Making the
chart's out-of-band Secrets optional, which stays `helm-e2e-pipeline-parity`'s.

## Decisions

### D1 — Each change is worked in its own sibling clone

A change's workflow runs in a clone of the owner's workspace, under one sibling
directory, `<workspace>.changes/<change>/`. The clone holds the change's branch,
`reviews/`, workflow log, transcripts, `.dist`, environments, `.snapshot/`, round
state, and Claude sessions. The owner's workspace — their editor project — meets
the workflow only when the owner reads a round, after implementation and sometimes
during triage.

A clone rather than a worktree, because a clone has refs of its own: the change's
branch can be checked out in the clone and, for reading, in the owner's workspace
at the same time, and commits move between them by fetch and pull. A local clone
hard-links its objects, so it costs little disk.

Rejected:

- **Switching branches in one checkout.** It only interleaves changes, since
  validation holds `HEAD` for its hour, and leaves another change's ignored
  `reviews/` behind to confuse `find_change.py` and the index check.
- **A worktree per change.** Git refuses one branch in two worktrees, so the owner
  could read a round only on a detached `HEAD`, and their own edit flow — check
  out the branch, commit, have the agent pull — has no branch to commit on.
- **Worktrees nested under an ignored directory of the workspace.** The scripts'
  tree walkers ignore `.gitignore`: `scripts/uv_project.py` finds every `uv.lock`
  by `rglob`, so `make lock` would relock the nested projects, and
  `check_comment_hygiene.py` and `scripts/architecture.py` would scan them twice.
- **A container per change, with its own Docker daemon and kube cluster.** It
  isolates everything, ports included, and is the direction the owner wants, but
  it is substantially more work: an image, privileged Docker in Docker, a cold
  build cache and a cluster per change, mounted credentials. It is deferred to its
  own change (open question 1). A clone is what such a container would mount.
- **Running steps as Claude Code on the web sessions.** No cluster for the Helm
  part, and the wrapper's guarantees — the step table under `dontAsk`, recorded
  denials, transcripts, the workflow log — would need re-establishing there.

A change may still be worked in the owner's workspace with no clone, as before
this change; the tooling tells the cases apart by whether the change's branch is
checked out in the current checkout.

### D2 — The owner reads a round in their workspace, by the branch's name

`make round-view CHANGE=<change>`, run in the owner's workspace:

1. refuses unless the workspace is clean, naming the files (the owner stashes and
   reapplies their own work by hand, rather than the tool holding it);
2. refuses while an unattended run is in progress in the workspace, naming it, and
   while another change's view is open, naming that change;
3. fast-forwards the workspace's `feat/<change>` from the change's clone, refusing
   if it has diverged;
4. records where the workspace was, checks out `feat/<change>`, and mixed-resets it
   to the round's base, read from the clone's latest `round` line, so the round
   shows as uncommitted changes exactly as before.

Run again while that change's view is open, it moves the view to the branch's new
head over the same base, so the owner follows triage's fixes; it refuses while the
workspace holds uncommitted edits or commits made during the view, naming them and
pointing at `make round-done`. `make round-done` resets `feat/<change>` to the
round's head and returns the workspace to where it was. The view never touches the
clone, so it never moves the branch any step runs on. It leaves the owner's
environments alone: rebuilding and relocking happen in the clone, or by the owner's
hand.

**Commits made during the view (17 F1).** The owner cannot be stopped from
committing while the branch sits at the base — an editor's "commit all" is one
click — so `round-done` repairs such commits rather than relying on a target the
owner might not use. While the view is open the worktree holds the round's head
plus the owner's edits, and the index the base, the round's new files
intent-to-add; so every path a commit made then changed holds what was on disk at
that moment — the round's version of the file with the owner's edits — and every
path it did not change keeps the base's version, which the owner did not mean as a
revert. `round-done` therefore carries each such commit, oldest first, onto the
round's head: each new commit starts from the previous one's tree (the round's head
first), sets every path the original changed against its parent to the original's
version, deleting what it deleted, and keeps the original's author and message; the
branch is then mixed-reset to the last. What the owner committed is on the branch as
descendants of the round's head; anything not committed stays uncommitted in the
worktree, and nothing is swept in. `round-done` prints each original commit beside
its replacement.

It refuses, moving nothing and saying how to return, when:

- a commit partly staged a file the round also changed (`git add -p`): its version
  of the path differs both from the worktree's at close and from the round's head,
  so laying it over the head would revert the round's changes there; the refusal
  names the file, and the owner commits it again by hand;
- the branch has left the base's line — an amend of the base, a reset, a rebase, or
  a merge made during the view, as `done` already refuses today.

A commit the owner makes after `round-done` already sits on the round's head and
needs nothing. Triage pulls the owner's commits into the clone with
`git pull --ff-only workspace feat/<change>`, refusing anything that is not a
fast-forward, and identifies them as the commits between the round's head and what
it pulled, so the owner's answer need not name their hashes.

Rejected: committing only after the view closes (it has no answer to a commit made
during it); a `make round-commit` target used during the view (the owner cannot be
made to use it, and the editor's commit stays a trap); committing everything the
worktree holds beyond the head (it sweeps uncommitted work, and a file a test run
rewrote, into the owner's commit).

Step 2's refusal of a workspace with a run in progress is what keeps reading
safe while this change is itself worked in the owner's workspace (the pilot, D9):
reading the pilot's round there would otherwise move the checkout under this
change's running step.

Rejected: a detached view (no longer needed once clones hold the branch); a named
view branch (a ref every checkout sees); an editor comparison against the branch
(reads as a comparison, and tests run on the workspace's code); rebuilding the
workspace's environments on every view (unwanted; the owner runs `make dist-clean`
or `make lock` when they want them).

For a change worked without a clone, whose branch is checked out in the
workspace itself, the view resets that branch in place, as before this change.

### D3 — Validation and review start when the round is committed

When a round's sections are committed, the next-step computation names validation,
the implementation review, and the owner's reading together. The orchestrating
session opens the view in the owner's workspace and starts validation and the
review in the clone. It then waits for the owner's answer — notes, or that there
are none — saves it as the round's owner record, closes the view, and starts
triage once the review and the validation have also landed. Triage scopes the
round from its `round` line's base, as the review does.

Validation dispatches the pipeline itself; `round-view` no longer pushes or
dispatches, and `make round-e2e-baseline` and the baseline it records are removed.

A change worked without a clone keeps the reading first: its view resets the
branch its own steps run on, as before this change, so the computation names
validation and the review only once that view has closed.

The order of reading first was there only because the shared checkout was moved
to show the round; with the view in another repository, validation's assumption
that its checkout is the commit holds throughout. The owner's reading, which takes
as long as it takes, comes off the round's critical path. Rejected: keeping the
reading first (the round waits on the owner before anything local runs); starting
validation at once but the review after the reading (the review does not read the
owner's notes, which are triaged beside it).

### D4 — Each Helm validation runs in its change's namespace

- **Namespace.** One per change, `validate-<change>`, cut to 63 characters with a
  short hash of the full name appended when longer. Each validation of the change
  replaces its release there, so the number of namespaces is bounded by the active
  changes. Release names are unchanged, so `local-values.yaml`'s in-cluster service
  names resolve in every namespace, and the two-release topology (`topology-up`)
  fits in it when a scenario needs it. Every `helm/` target that takes
  `NAMESPACE=` also takes `CHANGE=`, deriving the name with the same function.
  Rejected: a namespace per validated commit (they accumulate).
- **Images.** Every build target appends `IMAGE_SUFFIX`, empty by default:
  `make build-dev IMAGE_SUFFIX=-<change>` builds `arkhai:storefront-<change>` and
  its siblings, and the deploy names them through a values overlay. Compose, the
  pipeline lanes, and the owner's own deployments keep bare tags. Two changes never
  write one tag, so no build lock is needed. A fixed tag per change, never a commit
  tag: commit-suffixed tags caused repeated image-not-found failures deploying
  Helm, and a rebuilt image under a fixed tag rolls out by restarting pods.
  Rejected: a lock from build to deploy (a restarted pod of one change could pick
  up another's image); a lock across the build plus a re-tag to a commit tag.
- **Replacing the release.** The Helm run still starts from no persistent state.
  Validation scales the change's workloads to zero if a crashed run left any up,
  deletes the release's volume claims and the out-of-band buyer-profile volume
  (`arkhai-buyer-profiles`, which carries no release label), waits until they are
  gone, runs `make -C helm topology-secrets` for the namespace, and runs
  `helm upgrade --install` with the local overlay and the change's tags. The
  upgrade restores the replica counts, so every pod starts new, on the images just
  built, against empty volumes. An upgrade the chart refuses — a changed selector,
  say — falls back to uninstalling and installing, said in the step's detail. The
  retained-volume check stays only for `default`. Rejected: uninstalling every
  time (needless work); cycling pods over kept volumes (the new code would start on
  databases the previous commit migrated).
- **Scenarios.** They run as a pod in the namespace, from the change's
  `e2e-tests` image, with the release's in-cluster configuration (the `helm`
  profile from the release's `test-config` ConfigMap, as the `e2e-deal-test` Helm
  test pod uses), selecting `HELM_SCENARIOS`. Validation collects its log and exit
  status into the attempt's directory. No localhost port is involved, and the
  scenarios reach services by name, as the pipeline's lanes do on their compose
  network. Rejected: forwarding free ports per validation, which needs every
  scenario's URLs and the registry's descriptor overridden.
- **Manual access.** `make -C helm forward CHANGE=<change>` forwards one change's
  namespace on the usual ports for running e2e targets by hand; a second forward
  fails on bind, naming the port. `make -C helm resume CHANGE=<change>` scales a
  namespace back up.
- **Secrets.** `topology-secrets` creates them in each namespace; the preflight
  checks for `cast`. Rejected: copying them from `default` (the generator needs
  nothing from it); waiting for `helm-e2e-pipeline-parity` to make them optional.
- **After the scenarios.** Validation records the namespace's peak memory in the
  part's `summary.json`, copies every pod's log and the namespace's events into
  the attempt's directory, and scales the namespace's workloads to zero, keeping
  objects and volumes. Rejected: leaving releases running (resident memory grows
  with the active changes); uninstalling.
- **Capacity.** `helm/validation-capacity.toml`, tracked, holds the memory one
  release needs, and when and from which change it was measured. The preflight is
  an advisory estimate that reserves nothing (17 F3): it counts the namespaces with
  workloads above zero replicas, adds its own, and compares that many times the
  figure with the node's allocatable memory; a deployment that would not fit is an
  environmental failure put to the owner with its remedy. With no recorded figure —
  before the first archive cleanup writes one — it warns that the check was
  skipped and goes on. Two preflights can pass together; a pod that then fails to
  schedule for memory, is evicted, or is OOM-killed is diagnosed from the
  namespace's collected events as an environmental failure, its remedy scaling
  another change's namespace to zero or rerunning once it is down. Usage is
  measured through `metrics-server`; when it is missing the preflight warns and
  goes on. Archive cleanup writes the figure from the change's latest validation;
  this change's own archive cleanup writes the first. Rejected: no check; sums of
  the rendered requests and limits (declared, not used); `docker stats` on the
  node; a reservation held from preflight to scale-to-zero (it brings back the
  coordination D5 dissolved, and recovery of a lease a crashed validation left, to
  prevent a failure that costs one rerun).
- **Teardown.** Archive cleanup deletes the change's namespace and its
  `-<change>` images.

### D5 — Dissolved

The proposal's serialization of shared resources, with a refusal naming the holder,
has nothing left to serialize: per-change tags remove the build race, and every
other resource is per change or shared safely (D7).

### D6 — The orchestrating session creates the clone and the branch

The owner starts `make orchestrate CHANGE=<change>` in their workspace. When the
change's branch is checked out in no clone and not in the current checkout, the
next-step computation names `clone`, and the session runs
`make change-clone CHANGE=<change> [BRANCH=feat/<change>] [FROM=dev]`, which:

1. clones the owner's workspace locally into `<workspace>.changes/<change>/`;
2. sets `origin` to the workspace's `origin` URL, so the push guard's same-named
   upstream holds, and adds a `workspace` remote pointing back at the workspace —
   how every script in the clone finds the workspace;
3. checks out the branch: the existing one, or a new one from `FROM`;
4. links `.claude/settings.local.json` to the workspace's, so the owner's local
   permissions have one source;
5. starts `make init` in the background, recording its state in the clone's Git
   directory: its process and log while it runs, then its exit status.

`make change-clone` is idempotent (17 F5). It inspects the target and finishes
whatever is missing: it clones into an absent directory, and in a directory that is
already a clone of the workspace it resumes at the first step not yet done. It
refuses, naming the directory and deleting nothing, when the directory is not a
clone of the workspace, has another branch checked out, or has uncommitted changes.
The bootstrap is in one of three states: running, while its recorded process is
alive; succeeded, its exit status 0; failed, a non-zero exit status, or a dead
process that recorded none. The computation routes each: an absent or incomplete
clone names `clone`; while the bootstrap runs, design and planning go on and
implementation and validation wait; a failed bootstrap goes to the owner as an
environmental failure naming its log, and rerunning `make change-clone` restarts
it; a succeeded one lets the change proceed. A failed bootstrap is not retried by
itself: `make init` failing is almost always the environment, and a silent retry
would hide it.

Design proceeds meanwhile; the computation holds implementation and validation
until the bootstrap has succeeded. From then on the session drives every step with
`make -C <clone> <step> UNATTENDED=1`, so the wrapper's root, the log, the
transcripts, and the step sessions are the clone's. Taking a step over is
`cd <clone> && claude --resume <session>`. Rejected: the owner running
`make change-clone` by hand; starting the orchestrating session inside the clone.

`make change-clone-remove CHANGE=<change>`, run by the owner after the merge,
refuses unless every file of the clone's `reviews/` and named evidence is in the
workspace with identical contents (17 F4), the branch is merged into `origin/dev`,
and the clone has no commit `origin` lacks and no uncommitted change; a missing or
differing record is named, with `make change-history` as the remedy. Archive
cleanup does not remove the clone, since the pull request may need another round.

### D7 — Every shared resource is per change, shared safely, or checked

| Resource | Disposition |
|---|---|
| Branch, checkout, `reviews/`, log, transcripts, Claude sessions, `.dist`, environments, `.snapshot/`, port-forward PIDs, `Chart.lock` and chart packages, round state | per change, in the clone |
| Docker image tags | per change (`IMAGE_SUFFIX`); bare tags for compose, the pipeline, and the owner |
| Docker build cache, uv cache, bun cache | shared; each tool locks its cache |
| Kube namespace, releases, volumes, Secrets | per change (D4) |
| Localhost ports | unused by validation; the manual forward serves one namespace at a time |
| Node memory | shared, checked by the capacity preflight |
| CPU, GitHub runners | shared; slower, never wrong |
| `gh`, the Git remote, Claude and Codex accounts and their usage limits | shared; a usage limit stops every change's runs, and the wrapper names the reset time |
| The owner's workspace | one round view at a time |
| The change index | each branch edits its own row; adjacent rows may conflict at merge, resolved there |
| Local compose lanes | not used by any step |

### D8 — Each step commits and pushes its own work; the orchestrating session maintains the workflow

- Every step that commits feature work — design, planning, implementation,
  triage, closeout, archive cleanup — pushes it right after through
  `make push-branch`, the guarded push of exactly `HEAD`, which stays the only
  push any step may make; `git push` stays denied to every step. A pushed feature
  branch starts nothing by itself: `e2e.yml` runs on dispatch and nightly, and
  `tests.yml` on `dev`, `staging`, and pull requests into them.
- The design step commits its recorded design once the owner says it is settled,
  so the design review reads a committed design. Rejected: the owner committing
  design work by hand; the orchestrating session committing it.
- The orchestrating session maintains the workflow as well as advancing the
  change: it creates the clone and the branch (D6), and commits skill changes,
  permission changes, and anything else the owner explicitly asks for. It commits
  them in the clone, on the feature branch, so they take effect at once and land
  with that feature. It still forms no view of a finding or a design question.
  Rejected: committing workflow maintenance on `dev` in the owner's workspace
  (the clone's step table would not see it until `dev` was merged in).
- The step table: `make push-branch` moves from the committing steps' deny lists
  to their allow lists; `design` gains `git add` and `git commit`; `triage` and
  `implement` gain `git pull --ff-only workspace *`; `archive-cleanup` gains
  `make change-history`, the namespace teardown target, and
  `Edit(helm/validation-capacity.toml)`. The orchestrating session makes and
  commits these on the owner's word.

### D9 — Piloted on `seed-default-pool-at-runtime`, beside this change

The evidence is unit tests under `scripts/tests/` with injected runners; a scripted
check that validates two clones at the same moment on the development cluster and
shows separate namespaces, tags, and scenario pods with neither disturbing the
other; and one real change worked in a clone alongside this one, through archive
cleanup.

The pilot is `seed-default-pool-at-runtime`: small, real, and independent; its
chart change makes the Helm part real evidence; and it stays clear of Goal 7's
open work (`unbacked-bare-metal-listings`), meeting it at most in compute
provisioning's startup. Its feature branch is created from this change's branch,
not from `dev`, so its clone inherits the tooling without a merge to `dev`; its
pull request merges after this one.

A branch created once holds only the tooling of its moment, so this change's branch
is merged into the pilot's for the tooling of later rounds (17 F2). On the owner's
word, the pilot's orchestrating session runs, in the pilot's clone,
`git pull --no-rebase workspace feat/parallel-change-workflows` — a merge commit —
and pushes it through `make push-branch`, as workflow maintenance (D8). A merge is
made only between the pilot's steps: never while one of its steps runs or its view
is open, and never between one of its rounds being committed and that round's
triage, so it never falls inside a round's diff; a merge made before a round starts
lies below that round's recorded base. Two merges at least: once this change's
round-2 sections are committed, before the pilot's first implementation round, so
the pilot validates in its own namespace beside round 2's validation; and once
round 3 is triaged, before the pilot's closeout. Others whenever the owner asks,
such as for round 2's triage fixes. No revalidation rule is added: the pilot's next
validation is of the merged `HEAD`, and the pre-closeout and archive-cleanup gates
already require a passed validation naming `HEAD` once a path outside `openspec/`
and `docs/` changed. The index rows are the merge's expected conflicts, resolved in
the merge commit; any other conflict stops the merge and goes to the owner. The
next-step computation is not taught a parent branch: an ordinary change branches
from `dev` and never needs one. Rejected: rebasing the pilot onto this branch (it
rewrites a pushed branch, and every fast-forward-only pull then refuses); holding
the pilot back until rounds are triaged (it leaves a merge, and forgoes the
overlapping validations the pilot is evidence for).

This change itself is worked in the owner's
workspace throughout, which is also the evidence for working a change without a
clone. Rejected as pilots: `resolve-compute-family-findings` and
`kit-owned-storefront-shell` (they reshape the bare-metal storefront Goal 7
edits; the shell also waits on three dependencies); `add-full-stack-ci-job` (its
work barely reaches the Helm deployment).

This change's own design is the verification `agent-driven-change-workflow` left
open: design, design review, and planning from a proposal alone.

### D10 — One change

The Helm isolation and the items it takes from `helm-e2e-pipeline-parity` stay in
this change. That change keeps the charts and values that give the pipeline's
topology, extending the forward target to the services it adds, growing
`HELM_SCENARIOS`, and whether the Secrets become optional; it starts only after
this change merges, and depends on it for design. Its question of how buyer-CLI
scenarios reach the storefront from outside the cluster is answered here: they run
inside it.

### D11 — History moves into the owner's workspace at archive cleanup

As its last act, after its commit and after the pull-request draft is written to
`reviews/pull-request.md` (17 F4), archive cleanup copies into the owner's
workspace, at the same paths, the archived change's whole `reviews/` directory and
the validation evidence its records name (`.snapshot/validation/<commit>/` and
`.snapshot/e2e-logs/<run>/`), through `make change-history CHANGE=<change>`. It is
a synchronization, safe to run again: it copies files not yet there, compares
files on both sides by content, and refuses, naming each, when they differ, never
overwriting one; nothing rebuildable is copied. A record written after cleanup —
another round on the pull request — is carried across by running it again, and
clone removal (D6) refuses until it has been. Until the merge
reaches the workspace's branch, the copy is an archive directory holding only
`reviews/`, which `find_change.py` and the index check do not misread.

`scripts/find_change.py --records <change>` names a change's records wherever they
are — the checkout's own, then the workspace's through the `workspace` remote — and
every skill that reads another change's or an earlier change's records uses it.
`docs/agents/change-workflow.md` and `AGENTS.md`'s change-workflow section say the
owner's workspace holds the history of every cleaned-up change.

### The implementation cadence

Three rounds:

1. **Clones and reading**, in two sessions: the scripts and their tests
   (`change-clone`, `change-clone-remove`, the bootstrap marker, the `workspace`
   remote, the idempotent clone and the bootstrap's three states, the round view in
   its clone form with its refusals, `round-done` carrying commits made during the
   view onto the round's head, the computation's `clone` step, bootstrap routing,
   and round of three records, triage's pull); then the
   skills, the step table, and `docs/agents/change-workflow.md`. Validated in the
   owner's workspace on the existing Helm part. The pilot's design may start in its
   clone once this round is triaged.
2. **Helm isolation**, in two sessions: `IMAGE_SUFFIX` across the build targets,
   namespace naming and `CHANGE=`, `topology-secrets` per namespace, the upgrade
   from zero, the scenario pod, logs and scale-to-zero, the `metrics-server`
   warning and the capacity preflight, `forward` and `resume`; then
   `change-validate` and the scripted two-validation check. Once its sections are
   committed, this change's branch is merged into the pilot's (D9), and this round's
   validation overlaps the pilot's.
3. **History and teardown**, in one session: `make change-history`,
   `find_change.py --records` and the skills that read history, namespace and
   image teardown, and the capacity figure at archive cleanup. Once it is triaged,
   this change's branch is merged into the pilot's again, and the pilot then
   reaches archive cleanup on this tooling.

Before closeout, the owner and the agent discuss opening a change to containerize
the workflow (open question 1); then the pre-closeout review.

## Risks / Trade-offs

- **A clone per change costs a first `make init`** and disk for its environments.
  The bootstrap runs during design, which needs none of them.
- **Two refs named `feat/<change>`** — the clone's and the workspace's reading
  copy — can diverge. Fast-forward-only in both directions refuses rather than
  merges.
- **Two releases at once on one node** may exhaust Docker Desktop's memory. The
  capacity figure is only as current as the last archive cleanup that wrote it,
  and absent until one does; the preflight is an estimate, so two validations
  starting together can both pass it, and the overflow is diagnosed and rerun.
- **The pilot's branch is merged from this change's branch** at least twice. The
  merges are by hand on the owner's word and conflict on the index rows.
- **A usage limit stops every change's runs at once.** Parallel work spends the
  account's limits faster.
- **The index is edited on several branches.** Rows that sit next to each other
  conflict when merged to `dev`.
- **The scenario pod changes where the Helm scenarios run.** A scenario reading a
  file from the checkout rather than the image would need that file in the image;
  planning checks `HELM_SCENARIOS` for it.

## Open Questions

1. **A container per change.** Its own Docker daemon and kube cluster would
   isolate ports, images, releases, and Secrets entirely, and sandbox unattended
   steps from the owner's machine. Discussed before this change's closeout, to open
   it as its own change; revisit sooner if concurrent Helm validations exhaust one
   node. The owner can forward questions to a Claude Code on the web session about
   how its environment provides Docker and with what isolation.

## Pilot

`seed-default-pool-at-runtime`, worked in its own clone from a branch created from
this change's branch, alongside this change from this change's first round through
the pilot's archive cleanup (D9).
