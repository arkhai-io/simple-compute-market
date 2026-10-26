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
kept in the owner's workspace once it is cleaned up, where later sessions find it;
and, settled on a return from implementation, evidence only a push produces owed by
validation rather than gating a task, a one-run grant for a fresh run as for a
resumed one, and each step committing and pushing its own work.

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
this change; the tooling tells the cases apart by whether a clone of the change
holds its branch (D2, D6), looked for first, and only then by the branch checked
out in the current checkout, since the workspace may have a clone's branch checked
out for reading.

### D2 — The owner reads a round in their workspace, by the branch's name

`make round-view CHANGE=<change>`, run in the owner's workspace:

1. refuses unless the workspace is clean, naming the files (the owner stashes and
   reapplies their own work by hand, rather than the tool holding it);
2. refuses while an unattended run is in progress in the workspace, naming it, and
   while another change's view is open, naming that change; the wrapper, and the
   review runner beside it, record each run in progress in its checkout's Git
   directory — its process, step, and
   change — and removes the record once the run's line is written, and a recorded
   process no longer alive counts as no run;
3. fast-forwards the workspace's `feat/<change>` from the change's clone, refusing
   if it has diverged or holds a commit the clone lacks — one of the owner's that
   triage has not yet pulled;
4. records where the workspace was, checks out `feat/<change>`, and mixed-resets it
   to the round's base, read from the clone's latest `round` line, so the round
   shows as uncommitted changes exactly as before.

Git overwrites an ignored file wherever a checkout, a fast-forward, or a hard reset
puts a tracked one, and the cleanliness checks do not see ignored files; so before
every move of the worktree — opening, refreshing, returning — the view refuses,
naming them and moving nothing, when an ignored file sits at a path the target
tracks and the current commit does not (52 F2). A refused opening leaves the
workspace's branch where it was (52 F4).

Run again while that change's view is open, it moves the view to the branch's new
head over the same base, so the owner follows triage's fixes; it refuses while the
workspace holds uncommitted edits or commits made during the view, naming them and
pointing at `make round-done`, and refuses a new head that does not descend from
the view's and a base given anew, since the view's base is fixed. Closing the view
moves the checkout too, so `round-done` refuses while a run is in progress there. `make round-done` resets `feat/<change>` to the
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

A path the round did not change is carried as the commit gave it. A path the round
changed is carried only when the commit's version holds every change the round made
to it (26 F3): a three-way merge of the base's, the head's, and the commit's
versions (`git merge-file`) comes out clean and equal to the commit's version. With
the index at the base, a round change missing from the commit means either that the
owner did not stage it (`git add -p`) or that they removed it, and the files cannot
say which; laying such a version over the head would revert the round's change
inside the owner's commit, and merging it in would undo a removal the owner meant.
So `round-done` refuses, moving nothing and saying how to return
(`git reset --mixed <head>`, then commit again on the round's head), when:

- a commit's version of a path the round changed lacks some of the round's changes
  to it, or the merge conflicts; the refusal names the file. A deliberate revert of
  a round change, committed during the view, is refused with them and committed
  again after `round-done`;
- any commit made during the view has two parents (`git rev-list --min-parents=2`),
  since a merge from the base's line still descends from the base;
- the branch has left the base's line — an amend of the base, a reset, or a rebase:
  it does not descend from the base, or its merge base with the round's head is not
  the base, as after a reset into the round followed by a commit.

The merge test needs a text version on every side, so a path the round changed is
judged by its kind (37 F2), comparing the commit's version with the base's and the
head's by presence, blob, and mode, so an absent path is never taken for an empty
file:

- a text file present at the base and the head: the merge test above;
- a file the round added: carried only when the commit's version is the head's;
- a file the round deleted: carried only when the commit deletes it too;
- a binary file, a symlink, or a mode the round changed: carried only when the
  commit's version is the head's;
- anything else is refused, naming the file.

So an edit the owner commits during the view inside a line the round changed —
where the merge conflicts — or anywhere in a file the round added is refused, and
committed again on the round's head after `round-done`, as a deliberate revert is.
A commit that changes the mode of a text file the round changed is refused too, as
anything else is. A commit holding nothing beyond the round's head — "commit all"
with no edit of the owner's — is dropped and named rather than replayed empty,
since triage would otherwise present it as an owner's commit. A branch already at
or past the round's head, back by hand, is closed as it stands, unless a commit
made on the base during the view reaches it through a merge, which is refused like
any merge.

`round-done` returns the workspace to where it was only when it holds no
uncommitted edit, since a checkout would carry such an edit onto the branch it
went back to; otherwise it leaves the workspace on the change's branch, says so,
and the owner commits or discards the edit and checks out by hand. A view of a
change worked without a clone is not refreshed: its branch is the one the
change's steps run on, and nothing moves it while the view is open.

Rejected (26 F3): telling a partly staged file by its version differing both from
the worktree at close and from the round's head (a commit of part of a file, its
remainder then discarded from the worktree, passes and loses the round's other
changes, while a whole file committed and then edited further is refused); carrying
by three-way merge (it silently undoes an owner's removal of a round change).

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
workspace itself, the view resets that branch in place, as before this change. The
view tells the two apart by whether a clone of the change holds its branch, not by
what the workspace has checked out, since the workspace may have the branch of a
change in a clone checked out for reading.

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
  part's `summary.json` when a metrics source measures it, leaving the field empty
  otherwise (83 F2), copies every pod's log and the namespace's events into
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
  skipped and goes on. Two preflights can pass together, so a pod may then fail to
  schedule for memory, be evicted, or be OOM-killed. Such a failure is classified
  as validation classifies any (26 F2), since a commit that raises a request,
  lowers a limit, or leaks fails the same way: environmental when a pod could not
  be scheduled or was evicted while another change's namespace had workloads up
  and the node's allocatable memory was exhausted, its remedy scaling that
  namespace to zero or rerunning once it is down; caused by the commit when a
  container was killed at its own limit or the commit changed the rendered
  requests or limits; otherwise of unknown cause, so `failed` and triaged.
  Validation collects what that needs beside the namespace's events: the other
  namespaces' replica counts when the failure happened, and the rendered requests
  and limits beside the previous validation's. Usage is measured through
  `metrics-server`; when it is missing the preflight warns and goes on. Archive
  cleanup writes the figure from the change's latest validation. When that
  validation measured nothing, cleanup writes nothing, keeps any figure already
  recorded, and says so in its report and the pull-request draft (78 F2).
  `metrics-server` is not a prerequisite of the development cluster, and the one
  the workflow uses has none (section 6's cluster run measured nothing), so the
  preflight first becomes active at the first archive cleanup whose latest
  validation measured — on that cluster, not until one is installed. The pilot's
  evidence records the figure its cleanup wrote, or that it wrote none for want of
  a metrics source. Rejected: requiring a measured figure, with `metrics-server`
  installed on the development cluster before the pilot's cleanup (a cluster-wide
  component for an advisory check). Where a metrics source measured both, the
  pilot's archive cleanup (D9) writes the first figure, on the pilot's branch, and
  this change's archive cleanup writes its own here (83 F2); on the development
  cluster neither wrote one, and the pilot merged into this branch (PR #306) with
  nothing to conflict (152 F1). Had both written one, the file would have conflicted
  at that merge, beside the index rows, and the merge keeps the measurement with the
  later recorded time (37 F3); any later conflict over the file is resolved the same
  way. The figure is advisory and expected to be
  overwritten often: no branch's measurement is of the merged code, branches differ
  little, and the figure creeps up as the code grows. Rejected: keeping the incoming
  branch's figure (merge order, not anything the file records); keeping the larger
  (a rule beyond the latest validation, ratcheting at every merge). Rejected: this change's archive
  cleanup adopting the pilot's figure rather than measuring its own (a special case
  in a rule that is otherwise the change's latest validation). Rejected: no check; sums of
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
3. checks out the branch: the existing one, or a new one from `FROM`, each taken
   at its furthest point between the workspace's copy and `origin`'s and refused
   when the two have diverged, since a stale local `dev` would start a change
   without its own proposal; the branch tracks `origin`'s, never the workspace's,
   so no push goes to the workspace;
4. links `.claude/settings.local.json` to the workspace's, so the owner's local
   permissions have one source;
5. starts `make init` in the background, recording its state in the clone's Git
   directory: its process and log while it runs, then its exit status. The
   bootstrap's own process records itself as its first act, before `make init`
   starts, so a rerun after `make change-clone` is interrupted reads the bootstrap
   as started (52 F3). Only a rerun that read the clone between the spawn and that
   first act would start a second one; a rerun's Git checks on the clone come
   first and take far longer, so no lock guards the moment (96 F1).

`make change-clone` is idempotent (17 F5). It inspects the target and finishes
whatever is missing: it clones into an absent directory, and in a directory that is
already a clone of the workspace it resumes at the first step not yet done. It
refuses, naming the directory and deleting nothing, when the directory is not a
clone of the workspace, has another branch checked out, or has uncommitted changes.
The bootstrap is in one of three states: running, while its recorded process is
alive; succeeded, its exit status 0; failed, a non-zero exit status, or a dead
process that recorded none. The computation routes each: an absent or incomplete
clone names `clone`; while the bootstrap runs, design and planning go on and
implementation and validation wait — with them every later step, triage and
closeout included, since each runs suites or packaging; a failed bootstrap goes to
the owner, in any phase, as an
environmental failure naming its log, and rerunning `make change-clone` restarts
it; a succeeded one lets the change proceed. A failed bootstrap is not retried by
itself: `make init` failing is almost always the environment, and a silent retry
would hide it.

Design proceeds meanwhile; the computation holds implementation, validation, and
every later step until the bootstrap has succeeded, though not a design or plan
step named in a later phase, as after a confirmed return. From then on the session drives every step with
`make -C <clone> <step> UNATTENDED=1`, so the wrapper's root, the log, the
transcripts, and the step sessions are the clone's. Taking a step over is
`cd <clone> && claude --resume <session>`. Rejected: the owner running
`make change-clone` by hand for every change; starting the orchestrating session
inside the clone.

**A change already under way is not cloned (37 F1).** A clone copies what Git
tracks, and a change's `reviews/` — its records, workflow log, and transcripts — is
ignored, so a clone of a change worked in the workspace would start without them,
and the computation, reading records and log from its own checkout, would route it
from the index status alone; a run waiting on an answer could not be resumed there
either, its session being keyed to the workspace's path. So when the workspace
holds the change's `reviews/`, the computation does not name `clone`: it brings the
change to the owner, naming two routes. The default is to check out its branch in
the workspace and go on there without a clone, as before this change. The other is
moving it into a clone by hand, as `docs/agents/change-workflow.md` describes:
settle any run waiting on an answer, in the workspace; merge `dev` into the branch,
so its tooling knows clones; run `make change-clone`; move `reviews/` and the
evidence its records name from the workspace into the clone, and check the copies
are identical. Only changes begun before this change lands have records outside a
clone, and their branches lack the clone-aware tooling until they merge `dev`.
Rejected: migrating the records automatically once no run waits (a waiting-state
check, a reverse synchronization, and a deletion in the owner's workspace, kept for
a transitional case).

`make change-clone-remove CHANGE=<change>`, run by the owner after the merge,
first runs the history synchronization (D11, 26 F1), then refuses unless every file
of the clone's `reviews/` and of the named evidence it holds is in the workspace
with identical contents (17 F4), the branch is merged into `origin/dev`, and the
clone has no commit `origin` lacks and no uncommitted change; a record the
synchronization refused for differing contents is named, and nothing is deleted.
Named evidence the clone does not hold is named in the report and does not refuse
removal (114 F1): deleting the clone cannot lose it, and refusing would keep a clone
forever over evidence held nowhere. Archive cleanup does not remove the clone, since
the pull request may need another round.

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
- A triage of every kind commits and pushes the tracked edits its dispositions made
  — the change's documents, the ledger, the index row — with its fix commit or, with
  none, alone, so the next step starts from a clean worktree (52 F1). Once a
  pre-closeout review's triage has run, a validation clears a `HEAD` that differs
  from the validated commit only under `openspec/` and `docs/`, as one after a
  closeout review already does: closeout runs `make check-change` and
  `make check-packaging` itself, so a triage's commit of documents alone, such as the
  index row set to `ready for closeout`, needs no hour of pipeline. Before then only
  changes' records are exempt, since documentation the packaging checks read, such
  as `docs/development/ARCHITECTURE.toml`, is checked by nothing but the next
  validation. Rejected: exempting only the index row (a pre-closeout triage's task
  list or design edit would still be revalidated, though validation tests neither);
  leaving the index row to closeout (the index would say `in implementation` for a
  change ready for closeout).
- The orchestrating session maintains the workflow as well as advancing the
  change: it creates the clone and the branch (D6), and commits skill changes,
  permission changes, merges of `dev`, and anything else the owner explicitly asks
  for (D20). It commits
  them in the clone, on the feature branch, so they take effect at once and land
  with that feature. It still forms no view of a finding or a design question.
  Rejected: committing workflow maintenance on `dev` in the owner's workspace
  (the clone's step table would not see it until `dev` was merged in).
- The step table: `make push-branch` moves from the committing steps' deny lists
  to their allow lists; `design` and `plan` gain `git add` and `git commit`, since
  both commit their work under the first bullet; `triage` and
  `implement` gain `git pull --ff-only workspace *`; `archive-cleanup` gains
  `make change-history`, the namespace teardown target, and `make
  record-capacity`, which writes the capacity figure through the tested writer —
  on the owner's word during implementation, in place of an edit of
  `helm/validation-capacity.toml` by hand, since finding the latest validation's
  measurement is a lookup a script does reliably. The orchestrating session makes and
  commits these on the owner's word. A `git -C` read stays unallowed (36 R2): an
  allow rule's wildcard after `-C` also spans a push, which no deny rule names in
  that form, and a step already runs in the checkout it reads; the step skills'
  shared unattended-running guidance says instead to run Git in the current
  checkout, without `-C`.
- The owner's waiver of another design review after a return (36 R1), which the
  permanent specification allows, is recorded by the orchestrating session as the
  owner's decision directing planning, naming no run — as the owner's direction to
  archive cleanup waives its validation — once the change is in design and its
  latest design run has finished after the return; the computation's directed
  step then names planning, and the waiver is recorded in the intervention ledger.
  Today the log refuses such a decision, since it reads directing `plan` as a
  confirmed return that must resolve a run, and the computation names a design
  review whenever the latest design run finished.

### D9 — Piloted on `seed-default-pool-at-runtime`, beside this change

The evidence is unit tests under `scripts/tests/` with injected runners; a scripted
check that validates two clones at the same moment on the development cluster and
shows separate namespaces, tags, and scenario pods with neither disturbing the
other; and one real change worked in a clone alongside this one, through archive
cleanup. The check deploys, so it is `scripts/validate_parallel.py` behind `make
validate-parallel`, a validation by name: a `check_*` script or `check-*` target
would fall under the `make check-*` rule six steps hold and closeout's
`python3 scripts/check_*`, and let them deploy two releases.

The pilot is `seed-default-pool-at-runtime`: small, real, and independent; its
chart change makes the Helm part real evidence; and it stays clear of Goal 7's
open work (`unbacked-bare-metal-listings`), meeting it at most in compute
provisioning's startup. Its feature branch is created from this change's branch,
not from `dev`, so its clone inherits the tooling without a merge to `dev`; its
pull request merges after this one. On the owner's word at the pilot's archive
cleanup, it was instead merged into this change's branch as PR #306, so it reaches
`dev` with this change (152 F1).

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
the merge commit with any other conflict in a workflow file, and a conflict in code
goes to the owner (D20). The
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
files on both sides by content, extends a workspace file that is a byte-for-byte
prefix of the clone's to the clone's, and refuses, naming each, when a file differs
otherwise, never overwriting one; nothing rebuildable is copied.

The copy cannot be the last write (26 F1): the wrapper appends the cleanup run's
outcome to `workflow.jsonl` after the skill returns, the run's own transcript is
still being written while the copy runs, and the orchestrating session's decision
lines and another round on the pull request add more. Those files only grow, so the
prefix rule carries them; and clone removal (D6) runs the synchronization as its
first act, so the last copy always follows the last record without the owner
running anything. Archive cleanup's own copy stays, so sessions in other clones find
the history before the clone is removed. Rejected: the wrapper or the orchestrating
session running the copy after recording cleanup's outcome (the generic wrapper
learns one step's special case, and later lines still need the prefix rule and a
rerun); copying the log and transcripts only at removal (between cleanup and
removal the workspace's history would have no rounds, sessions, or costs). Until the merge
reaches the workspace's branch, the copy is an archive directory holding only
`reviews/`, which `find_change.py` and the index check do not misread.

`scripts/find_change.py --records <change>` names a change's records wherever they
are — the checkout's own, then the workspace's through the `workspace` remote — and
every skill that reads another change's or an earlier change's records uses it.
`docs/agents/change-workflow.md` and `AGENTS.md`'s change-workflow section say the
owner's workspace holds the history of every cleaned-up change.

D14–D20 were settled when implementation returned the change to design, after
round 2's sections 5 and 6, to take up two workflow items `dev` had recorded for
it, and the conflict the merge of `dev` exposed. D12 and D13 were labels of the
earlier discussion, recorded in D9 and the implementation cadence.

### D14 — A plan names evidence only a push produces as owed by validation

A section's verification names only evidence an implementation session can
produce. Evidence only a push produces — a CI workflow run such as `tests.yml`,
which a change branch's push does not trigger — is named on its own line of the
verification task, beside `End-to-end:`, giving the workflow, the job, and what the
job must show:

```
- [ ] 5.3 Verification: `make -C helm test-render` prints the version first and passes;
      `make test-release-tooling`. End-to-end: none; the pin changes no deployment.
      Owed by validation: `tests.yml`, job `release · deployment contracts` —
      `azure/setup-helm` installs v4.3.0, and `make -C helm test-render` prints
      `helm v4.3.0` before the first render and passes.
```

Implementation confirms or corrects the line in the section's notes, as it does the
end-to-end scenarios; validation reads it (D17). A workflow not on validation's list
(D15) cannot be owed: owing one is a design question, since only the owner extends
the list. Validation never edits `tasks.md`.

A task gated on evidence no implementation session can produce stays unchecked, and
the next-step computation names `implement` for it indefinitely; the case that
raised this, a CI run showing a pinned Helm, waited until the owner dispatched the
workflow by hand. A round advances only on a `passed` validation, so evidence owed
by validation keeps its gate without a checkbox.

Rejected: a structured block a script parses (a grammar in `tasks.md` the task-list
check would have to police, for an observation an agent reads from a log anyway); a
separate file per change (it parts what is owed from the section that owes it).

### D15 — Validation dispatches only workflows on a fixed list

`make run-ci WORKFLOW=<file>` dispatches a workflow on the current branch and
refuses, naming the list, any workflow its script does not list. The list holds
`tests.yml`; `e2e.yml` stays validation's pipeline part, through `make run-e2e`.
A companion fetch, reusing `scripts/fetch-e2e-logs.py`'s `--workflow` and
`--after-run`, waits for the run of `HEAD` newer than the run recorded before the
dispatch and downloads the named jobs' logs. Adding a workflow to the list is a
tracked change the owner makes. The fetch and the comparison (D16) run as
validation's `ci` part, `make validate-ci`, which the validate step's `make
validate-*` rule already allows, so its table gains `make run-ci` alone.

Three workflows that accept a dispatch publish — `publish-pypi.yml`,
`publish-npm.yml`, `release-cli.yml` — so a plan line naming one would publish from
a feature branch. A list in the script holds interactive runs too, which the step
table does not bind.

Rejected: dispatching any workflow a plan names; the step table as the list (it
binds unattended runs only); the owner's approval at each dispatch (a question in
every validation that owes CI evidence); leaving push-only evidence to the owner's
hand.

### D16 — The owed jobs are judged; other failures are compared with a `dev` run the branch contains

In each dispatched run, validation judges each named job and its observation. A
named job that fails, or an observation that is absent, is caused by the commit or
of unknown cause: a `V<n>`, and the result `failed`. Every other job that fails is
compared failure by failure (78 F1) — each failing test's ID with its exception
type, both read from pytest's short summary (`FAILED <id> - <type>: <message>`),
where the job prints one (83 F1); otherwise the failing step and its error lines —
with the same job in the baseline: the latest completed run of the same workflow on
`dev` whose head commit is an ancestor of the validated commit, usually the merge
base, since `tests.yml` runs on every push to `dev`. A failure the baseline shows
too is reported as already failing on `dev` and is not a finding; any other — a job
passing in the baseline, a test failing only on the branch in a job failing in
both, or a test failing in both with another exception type on the branch — is
diagnosed like any failure, so caused by the commit or unknown, a `V<n>`.
With no baseline run, or a job whose logs cannot be compared, the failure is of
unknown cause and triaged. The record names the baseline run and its commit. A run that
produced no evidence — `gh` not signed in, a runner outage, a run cancelled by a
newer dispatch on the same ref — is environmental: put to the owner with its remedy,
the part rerun on the owner's word, and `inconclusive` when the owner declines.

The record gains a `ci` part and a section:

```markdown
- **Parts:** local passed · helm passed · pipeline passed · ci passed
- **CI:** tests.yml run 39625394342, failure — owed jobs passed; 2 jobs failing not owed, every failure also in dev's run

## CI

| Workflow | Run | Owed by | Job | Owed observation | Result |
|---|---|---|---|---|---|
| tests.yml | 39625394342 | §5, 5.3 | release · deployment contracts | setup-helm installs v4.3.0; `make -C helm test-render` prints `helm v4.3.0` before the first render and passes | passed |

Baseline: dev's tests.yml run `<run>` at `968a4a9cd` (the merge base).

Not owed: `py · vms-storefront` — failed, 3 tests (`TimeoutError`), each failing in the baseline with `TimeoutError`; `py · bare-metal-storefront` — failed, `test_abort_all_is_not_previewed` (`AssertionError`), failing in the baseline with `AssertionError`.
```

With nothing owed, the part reads `ci not owed` and nothing is dispatched. The
`Commit:` and `Result:` lines, which the pre-closeout review and the next-step
computation read, are unchanged.

`tests.yml` fails on `dev` in two jobs unrelated to any change owing evidence from
it, so judging the run's conclusion would fail every such validation. Judging only
the named jobs would let a job the commit broke pass unseen; the comparison with
`dev` is the diagnosis validation gives any failure, and a difference it cannot
place is of unknown cause, so triaged. A job's status alone cannot show a failure
inherited: the branch can break another test in a job already failing, and
`dev`'s latest run may test code the branch does not contain (53 V1's `dev` run was
not an ancestor of the branch). A test ID alone cannot show it either: a test failing
on `dev` with a `TimeoutError` can fail on the branch with a new exception, which the
exception type tells apart. The type is compared mechanically, from a line pytest
already prints, so a timeout whose wording varies from run to run raises nothing.

Rejected: the test ID alone (it calls a new exception in an already failing test
inherited); the test ID with the exception type and its message, volatile detail
disregarded by validation's judgement (a changed assertion in an already failing
test is caught, but every comparison becomes a judgement about which detail is
volatile, for a test that already gives little signal); every failure in a test
already failing on `dev` of unknown cause (the same findings at every validation
until those tests are fixed); the run's conclusion; the named jobs alone; the observation alone (its job
passing was part of what was owed); every job judged against `dev` without named
jobs (a general CI gate no plan asked for); comparing job statuses with `dev`'s
latest run (it hides a new failure in a failing job, and its run may not be of the
branch's base); a tracked file of known failures with their commits (a list to
keep current, describing what was true when last edited rather than the branch's
base); dispatching the workflow on `dev` at each validation (a dispatch runs the
ref's tip, not the merge base, at twice the CI cost).

### D17 — Every validation dispatches what its complete sections owe

Every validation of a change dispatches each listed workflow named on an `Owed by
validation:` line of a section whose tasks are all checked at the validated commit,
and judges each observation (D16). Validation describes one commit, and a fix
commit can break evidence an earlier commit produced, as with the pipeline.
Rejected: only the validation of the round whose sections owe it; once per change.

### D18 — Implementation corrects a verification that demands push-only evidence; closeout records it

An implementation session that finds push-only evidence inside a verification task
— an older plan, or a slip — checks the task once its own evidence passes and
rewrites that evidence as an `Owed by validation:` line in the section's notes, as
it corrects end-to-end scenarios. Closeout's end-to-end part records the owed
observations from the latest passing validation's `## CI`, as it records the
pipeline run. Rejected: returning the change to planning (a round's cycle for a
line); leaving the task unchecked (the loop D14 removes).

### D19 — A grant reaches a fresh run through `ALLOW`

`run_change_step.py run` takes `--allow` as `resume` does; each value is split on
`;`, empty parts dropped, for both commands. Every unattended step target passes
`ALLOW`, which may hold several rules separated by `;`, to `run`:

```
make -C ../simple-compute-market.changes/seed-default-pool-at-runtime validate \
  CHANGE=seed-default-pool-at-runtime UNATTENDED=1 ALLOW='Bash(gh run download *);Bash(make check-packaging)'
```

The run's log line records the rules as `granted`, as a resumed run's does, and the
step's next run is held to its table again. A deny rule is still never granted. A
rule holding `;` could never match, since the harness matches each command of a
chain on its own, so the separator takes nothing from the rule syntax.

The orchestrating session starts every fresh step through its make target, which
checks the change, refuses while a round view is open, and translates `SECTIONS`,
`FRESH`, and `HELM_ALL_SCENARIOS`; a grant on `run` alone would not reach those
runs. A grant the owner decides before a fresh run otherwise costs that run a
refused turn before its resume carries the grant — and, between a round's sections
being committed and its triage, where no table edit may be committed, a fresh run
could not be granted at all.

Rejected: one rule per run (two rules one run needs should not force a table
edit); the orchestrating session calling the script directly (it
skips the targets' guards and keeps two translations of the targets' variables);
moving the targets' guards into the wrapper (a refactor larger than the item); a
grant recorded in the log for the step's next run (a waiting grant is state a run
nobody meant could take).

### D20 — Each step commits and pushes its own work; the orchestrating session commits maintenance, instructions, and merges

The steps were once denied their own commits and pushes by inheritance, not by a
decided reason: the owner read and committed design-phase work, and only validation
pushed, since only the pipeline needed a pushed branch. `dev`'s step table still
denies design and planning `git commit`, and every step but validation `make
push-branch`; under it the orchestrating session was given a closed step's leftover
work to commit and push, so a remote owner's work would not sit in the checkout.
D8's table removes the cause, and the rules are now:

1. **Each step that writes tracked work commits and pushes it itself** — design,
   planning, implementation, triage, closeout, archive cleanup (D8).
2. **Partial work is committed only on a return.** An implementation or triage run
   that returns records why, commits what it has as work in progress, checks no
   task for it, pushes it, and stops. A stopped run leaves its work uncommitted:
   stops are mostly a session's token limit, resumed as they stand or after a merge
   of `dev`, and the owner can have the orchestrating session commit the work to a
   separate work-in-progress branch. A run stopped because a repository guard
   refused, or `HEAD` moved, commits nothing.
3. **Validation and review commit nothing**; validation edits only its own record.
   Each describes one commit, and a commit of its own would move `HEAD` from under
   its evidence.
4. **Every push is the guarded push** — exactly `HEAD`, never forced, never `main`
   or `dev`, to an upstream of the same name; `git push` stays denied. `dev` is the
   line that matters, so the guard keeps every step off it; never forcing keeps
   the fast-forward-only pulls between the clone and the workspace valid.
5. **No step rewrites or discards**: `reset`, `checkout`, `switch`, `rebase`,
   `stash`, and `clean` stay denied.
6. **The orchestrating session commits workflow maintenance, what the owner
   instructs, and merges of `dev`**, never while a step runs, and never writes the
   change's feature work of its own accord. Nothing restricts its commits
   mechanically: it runs on the owner's interactive permissions, and "when the
   owner instructs" is not a rule a table can hold. It no longer commits a closed
   step's leftovers: under the rules above there are none, and tracked work left
   after a step ends is a defect of that step, brought to the owner.

The branch is the guard against unfinished work: only `dev` is protected, and
`dev` is not deployed at every commit, so a commit known not to work harms nothing
while it stays on a change branch.

**Merges of `dev` (D20.1).** The orchestrating session merges `dev` into the
change's branch on the owner's word, between steps, never while a round view is
open, and never between a round's sections being committed and that round's triage,
so a merge never moves the `HEAD` a round's validation and review describe or falls
inside a round's diff. Rejected: merging on its own initiative; dropping the timing
rules.

**Conflicts (D20.2).** It resolves conflicts in the change index, change documents,
the step table, and skills itself: it understands the workflow's files, and there is
rarely a real decision in them. A conflict in code goes to the owner as it stands;
one the owner cannot rule on from the report goes to an implementation run, with no
planning, since understanding the code base and deciding such a conflict is
implementation's work. Rejected: resolving every conflict, naming code resolutions
(a code decision at relaying effort); resolving index rows only (as before).

**Handing a code conflict to implementation (D20.3).** While a merge is in progress
(`MERGE_HEAD` exists), the next-step computation names the owner, "a merge is in
progress", so a restarted orchestrating session does not route on the change's
state alone. On the owner's word the session records a decision naming the
conflicted files and runs `make implement CHANGE=<change> UNATTENDED=1
ARGUMENTS='resolve the merge conflicts in <files>'`: the `implement` target gains
`ARGUMENTS`, passed as `--arguments`. The wrapper starts each implementation run in
a fresh session unless the run names one to continue (112 O1, below); a resume
reaches only a waiting run. `change-implement` gains a merge mode with no sections:
resolve the conflicts, run the suites of the sections owning the conflicted files,
conclude the merge with `git commit`, and push.
Rejected: calling the script directly (skips the target's guards, as D19 rejects);
aborting the merge for implementation to redo it (implementation would make a merge
the owner asked the orchestrating session to make, and needs `git merge`).

Rejected for D20 as a whole: keeping `dev`'s rule that the orchestrating session
commits a closed step's leftover work (it compensated for a table this branch has
replaced); committing a stopped run's partial work too (a stop is usually resumed,
and its own session finishes the section); keeping partial work uncommitted on a
return (no session is left to commit it, and a dirty clone blocks every later
step's guarded push and validation).

### 112 O1 — An implementation session is continued by its id, on the owner's word

Round 3's owner asked for section 8B to go to 8A's finished session, whose context
was small enough, and nothing could: a run started fresh, and a resume reached only
a waiting run. `make implement CHANGE=<change> UNATTENDED=1 SECTIONS=<ids>
SESSION_ID=<id>` (`run implement --session <id>`) continues the named session with
the step's prompt for those sections, or with `ARGUMENTS`, on the model its run used,
since a session cannot move between harnesses; the line records `continues`, the seq
of the run it continues. The session is named, never inferred, so it may be any of
the change's implementation runs: the next section's, or the session that made the
edits a later finding concerns, which holds their context. The wrapper refuses an id
with no implementation run in the change's log; any session while implementation's
latest run waits on the owner, since its answer goes through `resume`, which reaches
only that latest run; a step other than implementation; and `--fresh` beside it. The orchestrating session continues a session only on the
owner's word: the cadence is the owner's, and a growing session is the degradation
"Sections are slices, sessions are the owner's" weighs. Rejected: a bare
`CONTINUE=1` taking the latest run, guarded on `HEAD` being its commit (it cannot
reach an earlier session, nor one whose branch moved since); recording the round
with both sections in one session (decided before the first session runs, so it
cannot extend a session after its size is seen); continuing by default within a
round (sessions grow with no one choosing it).

### 109 R1 / 111 R1 — A run's earlier outcomes are kept beside its last

Two of round 3's sessions reported, then ended on a wake-up they had scheduled as a
fallback for `make test`, and that turn's "nothing left to wait for" became the
logged outcome; their reports reached no log line. The wrapper logs a run from its
last turn, as before, so routing is unchanged, and keeps each earlier turn's outcome
— its `outcome`, `message`, `next`, `reason`, `awaiting` — under `earlier` on the
line; a run that exited non-zero keeps even its last turn's there, since its line is
the wrapper's own `stopped`. The orchestrating session shows the owner the earlier
messages before the last. The unattended prompt the wrapper gives every run says a
background command wakes the session when it ends, so a step never schedules a
wake-up to wait for one. Rejected: the wrapper choosing a "substantive" outcome (a
guess that hides the later turn); denying `ScheduleWakeup` in the step table (covers
wake-ups only, and adds a denial to read on every run that tries one).

### 127 O2 / 128 R5 — A repeat round's fix is read by the owner

The pilot's second implementation round went from a triage recording Another round
over a fix — a new chart interface — straight to that fix's validation and review,
and its triage then asked the owner for notes on code no view had shown them. The
computation counted an owner record anywhere in the round as its reading, and the
view's refresh "follows triage's fixes" only while a view stays open through
triage, which a clone's reading may not. A repeat pass is now read like a first
one: once a triage records another round over a committed fix, the computation
names a round view of the fix, over the commit that triage's review read (`base`),
beside the fix's validation and review in a clone and before them in the workspace;
the pass's triage waits for an owner record saved after that triage finished — not
merely numbered after its review, since in a clone the first pass's answer can land
after the review it is read beside. A repeat pass with no fix has nothing to read. Rejected: asking no notes on a repeat pass
(cheaper, but the commits a repeat round exists for are the ones the owner would
not see); counting the first pass's notes for both (the owner read none of the fix).

### The implementation cadence

Four rounds:

1. **Clones and reading**, in two sessions: the scripts and their tests
   (`change-clone`, the bootstrap marker, the `workspace`
   remote, the idempotent clone and the bootstrap's three states, the round view in
   its clone form with its refusals, `round-done` carrying commits made during the
   view onto the round's head with its rule by path kind, the computation's `clone`
   step and its refusal of a change already under way, bootstrap routing, and round
   of three records, triage's pull, the owner's design-review waiver after a
   return); then the skills, with the unattended guidance's Git-without-`-C`
   sentence, the step table, and `docs/agents/change-workflow.md` with the manual
   move of a change into a clone. Validated in the
   owner's workspace on the existing Helm part. The pilot's design may start in its
   clone once this round is triaged.
2. **Helm isolation**, in two sessions: `IMAGE_SUFFIX` across the build targets,
   namespace naming and `CHANGE=`, `topology-secrets` per namespace, the upgrade
   from zero, the scenario pod, logs and scale-to-zero, the `metrics-server`
   warning and the capacity preflight, `forward` and `resume`; then
   `change-validate` and the scripted two-validation check. Once its sections are
   committed, this change's branch is merged into the pilot's (D9), and this round's
   validation overlaps the pilot's.
3. **History and teardown, CI evidence, grants and commit rules**, in three
   sessions (D21):
   1. `make change-history`, `find_change.py --records` and the skills that read
      history, `change-clone-remove`, which runs that synchronization as its first
      act (D6), namespace and image teardown, and the capacity figure at archive
      cleanup;
   2. validation's CI part (D14–D18): `make run-ci` with its list and the fetch,
      the `ci` part and its comparison with `dev`, and the plan, implement,
      validate, and closeout skills. Its section owes one observation of its own —
      `tests.yml`'s `release · deployment contracts` job passing — so the round's
      validation dispatches `tests.yml` on this branch and exercises the list, the
      fetch, the judging of a named job, and the comparison of the jobs failing on
      `dev`;
   3. grants for a fresh run (D19) and the commit rules (D20): `run --allow` and
      `ALLOW`, the merge-in-progress routing and `ARGUMENTS` on `implement`, the
      implement, triage, and orchestrate skills, and the guide.

   Once it is triaged, this change's branch is merged into the pilot's again, and
   the pilot then reaches archive cleanup on this tooling.
4. **The pilot's evidence and the containerization decision**, in one session,
   once the pilot's archive cleanup has run: it records the pilot's clone and
   bootstrap, its validation beside round 2's, a round of it read in the owner's
   workspace, its archive cleanup's history copy, and the capacity figure that
   cleanup wrote, or that it wrote none; and the owner's decision, discussed with the agent, on opening a
   change to containerize the workflow (open question 1). The round records the
   decision only; a change it decides to open is proposed afterwards on its own
   branch from `dev`. Then the pre-closeout review.

**D21.** The work of D14–D20 joins round 3 as sessions of their own rather than a
round of its own: it adds no round's cycle, each session's context holds one slice,
and the pilot has the new rules before its closeout. Round 2 had already been
recorded with sections 5–7 when they were settled, so section 7 stays next.
Rejected: two sessions, D14–D20 in one (a larger context for the second); a round of
their own between rounds 2 and 3 (one more cycle, and the pilot's history tooling
later); adding them to round 2 (the recorded round would have to be redistributed
by hand, for nothing gained).

Clone removal sits with the synchronization it runs first, rather than the
synchronization moving to round 1: removal is first needed after the pilot merges,
which follows this change's. So the pilot cannot exercise it, and round 3's unit
tests are its evidence. The pilot's evidence has a round of its own, rather than
the closeout task's end-to-end part and the pre-closeout triage, so that it and the
containerization decision are recorded before closeout rather than in a
conversation the plan cannot see. The cost is a round's whole cycle on a commit that
changes only change documents — the owner's reading, a validation, and an
implementation review — where round 3's validation would otherwise have served the
pre-closeout review.

## Risks / Trade-offs

- **A clone per change costs a first `make init`** and disk for its environments.
  The bootstrap runs during design, which needs none of them. The pilot confirmed
  a further cost: a fresh clone's first `make init` is the first build from
  nothing but the commit, and it failed on targets that had relied on wheels and
  an environment the workspace's earlier builds left behind (7.3); fixed in
  `make init`, and a bootstrap failure is put to the owner rather than retried,
  as D6 decides.
- **Two refs named `feat/<change>`** — the clone's and the workspace's reading
  copy — can diverge. Fast-forward-only in both directions refuses rather than
  merges. Not met in the pilot: its one view opened and closed without a
  refusal, the owner committed nothing during it, and triage's pull brought
  nothing.
- **Two releases at once on one node** may exhaust Docker Desktop's memory. The
  capacity figure is only as current as the last archive cleanup that wrote it,
  and absent until one does — on a cluster without `metrics-server`, which the
  development cluster is today, indefinitely, so the preflight stays inactive
  there; the preflight is an estimate, so two validations
  starting together can both pass it; an overflow the evidence shows to be
  contention is rerun. The pilot confirmed the inactive preflight: its archive
  cleanup recorded no figure, since none of its validations measured memory.
  Two releases ran at once only in 7.3's scripted check, and fitted; no
  validation of one change has yet overlapped another's, so exhaustion is
  untested rather than disproved.
- **The pilot's branch is merged from this change's branch** at least twice. The
  merges are by hand on the owner's word and conflict on the index rows. The
  pilot disproved the conflicts: its three merges, made between its steps, and
  its pull request into this branch were all clean, the index rows included;
  the two planned merges were fast-forwards, as the pilot had no commit yet. It
  showed instead that a merge between a round's sessions lies inside that
  round's diff: eleven of the 118 files the pilot's round view showed were
  workflow files those merges brought (open question 2). The pilot merged into this branch rather than after it
  (this change's seq 177), so this change's pull request carries the pilot's
  work.
- **A usage limit stops every change's runs at once.** Parallel work spends the
  account's limits faster. Met once: the pilot's implementation stopped on the
  account's session limit and resumed after its reset (pilot seq 45–48), while no
  run of this change was in progress.
- **The index is edited on several branches.** Rows that sit next to each other
  conflict when merged to `dev`. Not yet tested at a merge to `dev`: the pilot
  merged into this branch, cleanly.
- **The scenario pod changes where the Helm scenarios run.** A scenario reading a
  file from the checkout rather than the image would need that file in the image.
  Neither `HELM_SCENARIOS` module
  (`e2e-tests/tests/e2e/roles/layers/test_external.py`,
  `e2e-tests/tests/e2e/roles/scenarios/core/test_alkahest_escrow_codecs.py`) does:
  the image copies `e2e-tests/src`, `tests`, `config`, `conftest.py`, and
  `settings.toml`, which is all they read. A scenario added to the list later must
  hold to the same. The pilot's five Helm parts ran the scenario pod from their
  own images, each exiting 0, the four after the first upgrading the release over
  a namespace left at zero, one of them over the pilot's own chart change; the
  refused-upgrade fallback is still unexercised.
- **An unattended step reads outside its checkout.** Its Read, Glob, and Grep
  reach any file the owner can read — the workspace's records, which history
  needs, and equally another clone's or the owner's own files — while Bash reads
  outside the checkout are denied (pilot seq 1). The step table bounds commands,
  not the files a step may read.

## Open Questions

1. **A container per change.** Its own Docker daemon and kube cluster would
   isolate ports, images, releases, and Secrets entirely, and sandbox unattended
   steps from the owner's machine. The owner can forward questions to a Claude Code on the web session about
   how its environment provides Docker and with what isolation.

   **Decided in round 4: no change is opened now; the question stays open with
   its triggers.** Nothing in the pilot called for one: clones and per-change
   namespaces kept every step and validation apart — each validation deployed
   only its own tags into its own namespace, the scripted check found neither
   release, volume, nor pod touched by the other (7.3), validation forwards no
   port, and the node was never exhausted — while a
   container costs an image, privileged Docker in Docker, a cold build cache and
   a cluster per change, and mounted credentials (D1). What only a container
   answers is the cluster-wide isolation and the new risk of an unattended
   step's reads reaching any file the owner can read; neither has yet cost
   anything. A change opened with no trigger met would wait in the index. The
   question is reopened, as a change proposed on its own branch from `dev`, when:
   - a validation fails because two changes' releases contend for one node, or
     two changes need different cluster-scoped resources, which a namespace
     cannot separate;
   - orchestrating several changes from one session lands, and side-by-side
     validations become routine rather than occasional;
   - the owner wants unattended steps sandboxed from their own files.

   Rejected: opening a proposal-only change now (a row with no trigger met, idle
   in the index); closing the question (the read-scope and cluster-wide gaps
   remain, and the owner wants the direction kept).
2. **The round view mixes the branch's own changes with merges from `dev` (94
   O1).** The view resets the branch to the round's base (D2), so a merge from
   `dev` inside the round shows `dev`'s changes as uncommitted beside the round's
   own, with nothing to tell them apart. Round 2's view held 98 files, 69 of them
   touched by one merge of `dev` (`8e6494f51`, which brought in a Helm render fix), and
   the owner could not read the round for it. Candidates: a synthetic base — the
   view resets to a commit merging the round's base with each `dev` commit the
   round merged, so only the branch's own changes and its conflict resolutions
   show; merging `dev` only between rounds, so the next round's base holds it; or
   listing beside the view the paths a merge brought. The owner leans to the
   synthetic base: a merge from `dev` often carries an urgent fix, as that render
   fix was, which a round must build on rather than ignore and then rediscover or
   duplicate, so holding merges to round boundaries would delay it.

   **Decided in round 4's triage (145 F1): deferred to its own change,
   `round-view-without-merges`, proposed on its own branch from `dev` once this
   change merges, not here.** The pilot met the case again — eleven of the 118
   files in its round view came from merges inside the round — so the view stays
   as D2 builds it, and "Current limits" says it mixes in merges until that change
   lands. The owner's leaning to the synthetic base carries into that change's
   proposal. Its design is more than a fix: `scripts/round_view.py` holds the
   view's base to be an ancestor of the round's head where `done` carries the
   owner's commits onto the head, where it refuses a branch that has left the
   base's line, and where a refresh resets over new commits, and a synthetic base
   is off that line; and it must say what the view shows when the round's base
   and the merged `dev` commits do not merge cleanly without the round's own
   resolution. Rejected: building the synthetic base here (a return to design and
   planning, and a further round, for a change ready for its pre-closeout review);
   merging `dev` only between rounds (delays the urgent fixes the owner merges
   for); listing a merge's paths beside the view as a stopgap (labels the files
   without separating them, and adds a code round before closeout).

## Pilot

`seed-default-pool-at-runtime`, worked in its own clone from a branch created from
this change's branch, alongside this change from this change's first round through
the pilot's archive cleanup (D9).
