Sections follow the design's implementation cadence: clones and reading (1–4),
Helm isolation (5–7), history and teardown (8), the pilot's evidence and the
containerization decision (9), then closeout (10). Within each round, scripts come
before the skills and documents that call them. Every script is tested in
`scripts/tests/` with an injected command runner, at unit level, except where a
real Git repository is the lowest level that proves the behaviour (repository
level, in a temporary directory, as `test_round_view.py` does today) or a real
cluster is (the two-validation check, 7.3). The workflow tooling is contributor
tooling that no end-to-end scenario in `e2e-tests/` exercises, and none is owed;
the Helm part's own scenarios (`contracts`, `e2e_alkahest_escrow_codecs`) are
evidence for sections 5–7 only in that they now run inside the change's namespace.
The pilot, `seed-default-pool-at-runtime` (D9), is the working evidence.

A task that edits `.claude/change-steps.toml` or another file under `.claude/` is
the orchestrator's, made on the owner's word before its section's session starts,
and that session commits it with its section; the rest of the section is the
implementer's.

## 1. Clones and their bootstrap

Delivers `make change-clone` (D1, D6; requirement "Each change is worked in its own
clone"). Touches a new `scripts/change_clone.py`, the root `Makefile`, and
`scripts/tests/`.

- [x] 1.1 `scripts/change_clone.py create <change> [--branch B] [--from REF]`, run in
      the owner's workspace: clone it locally into `<workspace>.changes/<change>/`;
      set `origin` to the workspace's `origin` URL and add a `workspace` remote
      naming the workspace; check out the branch, the existing one or a new one from
      `--from` (default `dev`); link `.claude/settings.local.json` to the
      workspace's; start `make init` in the background, recording in the clone's
      Git directory its process and log while it runs, then its exit status (D6).
      Default branch `feat/<change>`.
      Note: the clone is made with `git clone --no-checkout --origin workspace`, so
      the `workspace` remote exists from the first step and an unfinished clone has
      no index (its empty worktree is never read as uncommitted deletions). The
      branch, existing or `--from`, is taken at its furthest point between the
      workspace's copy and `origin`'s, and refused when the two have diverged — a
      stale local `dev` would otherwise start a change without its own proposal. It
      is checked out with no upstream in the workspace, tracking `origin`'s branch
      when there is one, and the branch `git clone` made is deleted, so the push
      guard never pushes into the workspace; that settling runs on every pass, so
      a checkout interrupted before it is settled by the rerun (a branch the safe
      delete refuses keeps only its upstream removed). Step 3 fetches the
      workspace first, so a rerun reads its branches as they are now. What is
      already in the clone — its `origin`, its branch, uncommitted changes — is
      refused before anything is written; a diverged branch, a `--from` naming
      nothing, and a settings path that is not the link are found only later,
      after the `origin` remote is added, and leave the clone unfinished for a
      rerun. The furthest-point rule is now in D6. The change and branch are
      recorded, once the branch is checked out, in
      the clone's Git directory (`change-clone.json`), beside the bootstrap's
      `change-bootstrap.json` (pid, log), `.log`, and `.status`; the bootstrap runs
      under `sh -c` in its own session, writing its status through a temporary
      file. The settings link is made even while the workspace has no
      `settings.local.json`, so the clone sees one as soon as the owner writes it.
- [x] 1.2 Idempotence and refusals (D6, 17 F5): in a directory that is already a
      clone of the workspace, resume at the first step not done, never recloning;
      refuse, naming the directory and deleting nothing, a directory that is not a
      clone of the workspace, has another branch checked out, or has uncommitted
      changes. Rerunning restarts a failed bootstrap and leaves a running or
      succeeded one alone.
      Note: also refused, deleting nothing — a clone asked for another `--branch`
      than the one it records, the clone of another change, a clone whose `origin`
      is not the workspace's, a `--from` naming nothing, a settings path that is
      not the link, a workspace with no `origin`, and running `create` in a clone
      (its `workspace` remote names a directory). Settling the upstreams deletes
      the branch `git clone` made inside the clone, and the workspace fetch prunes
      the clone's copies of deleted workspace branches; neither is anyone's work.
- [x] 1.3 `bootstrap_state(clone)` → `running` (recorded process alive),
      `succeeded` (status 0), `failed` (non-zero status, or a dead process with no
      status), or `absent`, with the log's path; and `clone_of(workspace, change)`
      → the clone's directory when it exists and holds the change's branch. Both
      are the computation's inputs (3.1), importable without side effects.
      Note: `workspace_of(checkout)` beside them, the workspace a clone's
      `workspace` remote names, or None for any other checkout; the round view and
      the computation tell a clone from the workspace by it. A recorded pid reused
      by another process would read as `running`; nothing guards against that.
- [x] 1.4 `Makefile`: `make change-clone CHANGE=<change> [BRANCH=…] [FROM=…]`.
- [x] 1.5 Verification. Repository level (temporary workspace with a bare `origin`):
      a fresh clone has both remotes, the branch, the settings link, and a bootstrap
      record (the bootstrap command injected); an interrupted creation, each step
      left undone in turn, is finished without recloning; each refusal deletes
      nothing; a branch created from `--from`. Unit: the bootstrap's four states,
      a dead process with no status read as `failed`. `uv run --no-project --with
      pytest pytest -q scripts/tests/test_change_clone.py`; `make test`. No
      end-to-end scenario covers it.
      Evidence: `scripts/tests/test_change_clone.py`, 36 passed — repository level,
      the plan's term (real Git in a temporary directory, a workspace with a bare
      `origin`, the bootstrap's spawn injected): the fresh clone; its tracking nothing in the workspace, with the
      workspace on `dev` and with the change's branch checked out there; an
      existing branch at its furthest point; a diverged one refused, then taken
      once reconciled in the workspace; `--from` a workspace branch; `dev` from
      `origin` when the workspace's is behind; a named branch recorded; resumption
      after the clone, after the remotes, after a checkout whose upstream was not
      yet settled (approximated by a checkout tracking the workspace), before the
      link, and before the bootstrap alone (a sentinel in the Git directory shows
      nothing was recloned); a failed bootstrap restarted, a running one and a
      complete clone left alone; the refusals of a directory that is not a clone,
      a file in its place, a clone of another repository, the clone of another
      change, another branch checked out, uncommitted changes, another
      `--branch`, an `origin` not the workspace's, a `--from` naming nothing (and
      another `--branch` accepted after it), a settings file that is not the
      link, a workspace without `origin`, and a clone as workspace, each but the
      diverged one asserting what it leaves; the detached-`HEAD` wording and an
      unreadable `origin` are untested; the real
      spawn recording output and status. The bootstrap's states — `failed` for a
      dead process without a status — are read over state files in a real clone
      with the liveness check injected. The command line is exercised only on its
      refusal, since a successful run starts the real `make init`.
      `uv run --no-project --with pytest pytest -q scripts/tests`: 1121 passed.
      `make test`: every suite passed up to `make -C helm test-render`, which
      failed three render assertions (`internalRegistryTrust` got null, in
      `helm/charts/storefront/tests/test_render.py` and
      `helm/tests/test_release_topology.py`); this section touches nothing under
      `helm/`, so the failure is not its own, and is left for validation to
      report. `make check-packaging`: passed. `make check-change`: only the
      citations of the scripts sections 5, 7, and 8 create
      (`change_namespace.py`, `check_parallel_validation.py`,
      `change_history.py`). No end-to-end scenario covers it.
      Handoff: not done, deliberately — the bootstrap record is written just after
      the spawn, so a run killed between the two reads `absent` and a rerun starts
      a second `make init`; `--from` takes a branch name or a commit, not
      `origin/<branch>`; `make change-clone` does not check the change's name with
      `find_change.py`, since the change may exist only on the branch it starts
      from; a checkout killed after writing its index but before moving `HEAD`
      leaves the clone refused as on another branch, for the owner to delete; a
      clone whose custom branch was checked out but not yet recorded is refused on
      a rerun without `--branch`. The furthest-point rule is promoted with D6
      (10.9). Section 3 must read
      a clone `clone_of` returns whose bootstrap is `absent` as incomplete.

## 2. The round view in the owner's workspace

Delivers D2's view and `round-done`'s carry, and D3's removal of the view's push
and dispatch (requirement "Triage of an implementation round"). Touches
`scripts/round_view.py`, `scripts/change_workflow/wrapper.py`, the root `Makefile`,
`scripts/tests/test_round_view.py`, and `scripts/tests/test_change_workflow_wrapper.py`.

- [ ] 2.1 The record of a run in progress (D2 step 2): the wrapper writes the run's
      process, step, and change into its checkout's Git directory as a run starts,
      and removes it once the run's line is written, an interrupt included;
      `runs_in_progress(root)` reads the live ones, a dead process counting as none.
- [ ] 2.2 `round_view.py start <change>` for a change whose clone holds its branch
      (1.3), run in the workspace: refuse a dirty workspace, naming the files; a run
      in progress there (2.1), naming it; another change's open view, naming the
      change; then fast-forward the workspace's branch from the clone's `workspace`
      remote counterpart (`git fetch <clone> <branch>`), refusing a diverged one;
      record where the workspace was (branch or detached commit); check out the
      branch and mixed-reset it, with `-N`, to the base read from the clone's latest
      `round` line (D2). The state records the clone, so `done` and refresh find it.
- [ ] 2.3 Refresh (D2): `start` again for the change whose view is open moves the
      view to the branch's new head over the same base, after the same fetch;
      refuse while the workspace holds uncommitted edits or commits made during the
      view, naming them and `make round-done`.
- [ ] 2.4 `done` carries commits made during the view (D2, 17 F1, 26 F3, 37 F2):
      oldest first onto the round's head, each new commit from the previous one's
      tree, with every path the original changed against its parent set to the
      original's version (deletions deleted), keeping author and message; then
      mixed-reset the branch to the last and return the workspace to where it was,
      printing each original beside its replacement. A path the round did not
      change is carried as given. A path the round changed is judged by kind, from
      presence, blob, and mode at the base, the head, and the commit: a text file
      present at base and head by `git merge-file` of base, head, and commit coming
      out clean and equal to the commit's version; a file the round added, a
      binary, a symlink, or a changed mode only when equal to the head's; a file the
      round deleted only when deleted too; anything else refused. Refuse, moving
      nothing and naming the file or commit with `git reset --mixed <head>` as the
      way back, on any such failure, on a commit with two parents, and when the
      branch has left the base's line. No commit: back at the head, as today.
- [ ] 2.5 The view of a change with no clone, whose branch is the workspace's own,
      keeps today's behaviour: the branch reset in place, the reading first (D2,
      D3). `round_view.py` no longer pushes or dispatches: `--no-e2e`, the
      `e2e-baseline` action, `E2E_BASELINES`, and `make round-e2e-baseline` are
      removed, and `make round-view` loses `NO_E2E` (D3). `check` refuses only in
      the checkout whose branch the view moved.
- [ ] 2.6 Verification. Repository level (a workspace and a clone in a temporary
      directory, real Git): each refusal of 2.2 and 2.3; a view and its refresh onto
      a triage fix; `done` with no commit; each delta scenario of "Triage of an
      implementation round" on carrying — a commit of an edit, a partly staged file
      whose round changes were unstaged and one where they were removed, a whole
      file committed then edited on, an edited added file, a committed deletion, a
      binary file, a merge, an amended base; the clone's branch never moving; a
      change without a clone viewed in place. Unit: the run record written,
      removed, and read with a dead process. `uv run --no-project --with pytest
      pytest -q scripts/tests/test_round_view.py
      scripts/tests/test_change_workflow_wrapper.py`; `make test`. No end-to-end
      scenario covers it.

## 3. The next-step computation for a change in a clone

Delivers the computation's clone routing, the round of three records, and the
owner's design-review waiver after a return (D3, D6, D8's 36 R1; requirements
"Each change is worked in its own clone", "Triage of an implementation round", "An
orchestrating session advances one change"). Touches `scripts/change_next_step.py`,
`scripts/change_workflow/log.py`, and their tests.

- [ ] 3.1 Clone routing (D6): for a change whose branch is checked out neither in
      the computing checkout nor in a clone (1.3), the result is `clone`, naming the
      `make change-clone` arguments; unless the workspace holds the change's
      `reviews/` (37 F1), when the result is `owner`, naming both routes — check out
      the branch in the workspace and go on there, or move it into a clone by hand
      per `docs/agents/change-workflow.md` (4.5). For a change whose clone exists,
      run in the workspace, the result names the clone's directory, from which the
      session runs the computation and every step.
- [ ] 3.2 Bootstrap routing (D6): an incomplete clone names `clone`; while the
      bootstrap is `running`, design and planning steps are named and
      implementation and validation steps wait, the result saying so; `failed` is
      `owner`, an environmental failure naming its log and that `make change-clone`
      restarts it; `succeeded` routes as today. A change with no clone routes as
      today.
- [ ] 3.3 The round of three records (D3): for a change in a clone, once a round's
      sections are committed, the result is `validate-and-review` together with the
      owner's reading — the session opens the view in the workspace and starts both
      in the clone — and triage is named only once the owner record, the review,
      and the validation exist. The view's state is read from the workspace through
      the clone's `workspace` remote, so an open view there holds triage and nothing
      else. A change without a clone keeps the reading first.
- [ ] 3.4 The waiver after a return (36 R1): `note … orchestrator --next plan`,
      `by: owner`, naming no run, is accepted once the change is `in design` and the
      latest design run finished after a confirmed return; any other `next` other
      than `review` and `archive-cleanup` still names the run it resolves. `_design`
      honours that direction and names planning rather than a design review.
- [ ] 3.5 Verification. Unit, over fixture changes and logs, in
      `scripts/tests/test_change_next_step.py` and
      `scripts/tests/test_change_workflow_log.py`: a change with no clone and no
      records (`clone`); one with records in the workspace (`owner`, both routes);
      an interrupted clone; each bootstrap state against each phase; a round in a
      clone naming validation and review with the reading, and triage only once all
      three records exist; a workspace change keeping the reading first; the waiver
      accepted after a return and refused otherwise, and planning named after it.
      Repository level: the clone found by `clone_of` and the workspace's view read
      through the remote. `uv run --no-project --with pytest pytest -q
      scripts/tests`; `make test`. No end-to-end scenario covers it.

## 4. The skills, the step table, and the contributor guide for clones

Delivers D6, D8, and the skill side of D2 and D3 (requirements "An orchestrating
session advances one change", "Unattended runs are held to their step's
permissions", "Triage of an implementation round"). Touches `.agents/skills/`
(`change-orchestrate`, `change-design`, `change-plan`, `change-implement`,
`change-triage`, `change-validate`, `change-closeout`, `change-archive-cleanup`),
`.claude/change-steps.toml`, and `docs/agents/change-workflow.md`.

- [ ] 4.1 `change-orchestrate`: run the computation in the workspace and, once a
      clone exists, in the clone; on `clone`, run `make change-clone`; on the
      `owner` result for a change under way, relay both routes; drive every step
      with `make -C <clone> <step> UNATTENDED=1`; once a round is committed, open
      the view in the workspace and start validation and the review in the clone
      side by side, wait for the owner's answer, save it as the round's owner record
      in the clone, close the view, and start triage once all three records exist;
      record the owner's waiver after a return as 3.4's decision, with its ledger
      line; commit workflow maintenance the owner asks for — skills, the step
      table, anything else named — in the clone on the feature branch, and push it
      through `make push-branch`; take a step over with `cd <clone> && claude
      --resume <session>`; for the pilot, merge this change's branch into the
      pilot's on the owner's word only between the pilot's steps and never inside
      one of its rounds (D9) (D2, D3, D6, D8).
- [ ] 4.2 The committing skills push: `change-design` commits its recorded design
      once the owner says it is settled; `change-design`, `change-plan`,
      `change-implement`, `change-triage`, `change-closeout`, and
      `change-archive-cleanup` push each commit through `make push-branch` (D8).
      `change-triage` pulls the owner's commits with `git pull --ff-only workspace
      feat/<change>`, refusing anything else, and identifies them as the commits
      between the round's head and what it pulled; it scopes the round from the
      `round` line's base, as the review does (D2, D3). `change-validate` dispatches
      the pipeline itself and no longer reads a baseline the view recorded (D3).
- [ ] 4.3 Every step skill's "Running unattended" section gains: run Git in the
      current checkout, never with `-C` (D8, 36 R2).
- [ ] 4.4 `.claude/change-steps.toml` (the orchestrator's, as the preamble says): `make
      push-branch` moves from the deny to the allow list of design, plan, triage,
      implement, closeout, and archive cleanup; design and plan gain `git add *`
      and `git commit *`; triage and implement gain `git pull --ff-only workspace *`;
      the round view stays denied to every step (D8).
- [ ] 4.5 `docs/agents/change-workflow.md`: a change worked in its own clone —
      where clones live, `make change-clone` and the bootstrap's states, steps run
      with `make -C <clone>`, taking a step over, reading a round in the workspace
      and what `round-done` does with commits made during the view and what it
      refuses; working a change in the workspace without a clone; moving a change
      already under way into a clone by hand: settle any run waiting on an answer in
      the workspace, merge `dev` into its branch, `make change-clone`, move
      `reviews/` and the evidence its records name into the clone and check the
      copies are identical (D6, 37 F1).
- [ ] 4.6 Verification: `make check-agent-skills`; `make check-change
      CHANGE=parallel-change-workflows`; `uv run --no-project --with pytest pytest -q
      scripts/tests/test_change_workflow_steps.py`, extended with the table's new
      allows and denies (unit); a fresh-context read of each changed skill against
      D2, D3, D6, D8 and the delta's orchestrating-session and permissions
      requirements, recording what it found; `make test`. Validated in the owner's
      workspace on the existing Helm part. No end-to-end scenario covers it.

## 5. Per-change image tags and namespaces in the build and Helm targets

Delivers D4's images, namespace naming, Secrets, and manual access (requirement
"Each Helm validation is isolated in its change's namespace"). Touches the root
`Makefile`'s build targets, `core/registry/Makefile`,
`domains/vms/storefront/Makefile`, `provisioning/compute/service/Makefile`,
`dev-env/Makefile`, `e2e-tests/Makefile`, `helm/Makefile`, a new
`scripts/change_namespace.py`, `helm/tests/`, and `scripts/tests/`.

- [ ] 5.1 `IMAGE_SUFFIX`, empty by default, appended to every image tag the build
      targets write — `build`, `build-dev`, `build-seller`, and each image target the
      root `Makefile` and the subproject Makefiles define — so `make build-dev
      IMAGE_SUFFIX=-<change>` builds `arkhai:storefront-<change>` and its siblings;
      compose, the pipeline lanes, and the owner's own deployments keep bare tags
      (D4).
- [ ] 5.2 `scripts/change_namespace.py <change>` prints `validate-<change>`, cut to 63
      characters with a short hash of the full name appended when longer; every
      `helm/Makefile` target that takes `NAMESPACE=` also takes `CHANGE=`, deriving
      the namespace through it (D4).
- [ ] 5.3 `make -C helm forward CHANGE=<change>` forwards that namespace on the usual
      ports, a second forward failing on bind and naming the port; `make -C helm
      resume CHANGE=<change>` scales its workloads back up; `topology-secrets` runs
      for a derived namespace (D4).
- [ ] 5.4 The image overlay: a function that writes a values overlay naming every
      image tag `helm/values.yaml` sets with the suffix; a render test in
      `helm/tests/` holds the overlay to every image the chart renders, so an image
      added later cannot stay bare (D4).
- [ ] 5.5 Verification. Unit: the namespace name for a short, a 63-character, and a
      longer change, the hash stable; `make -n` of each build target with and
      without `IMAGE_SUFFIX` and of each Helm target with `CHANGE=`. Chart render
      tests (`make -C helm test-render`, `helm/tests/`): the overlay over every
      rendered image. `uv run --no-project --with pytest pytest -q scripts/tests`;
      `make test`; `make test-deployment-packaging`. No end-to-end scenario covers
      it.

## 6. The Helm part of validation in the change's namespace

Delivers D4's release replacement, scenario pod, evidence, scale-to-zero, and
capacity preflight (requirement "Each Helm validation is isolated in its change's
namespace"). Touches `scripts/validate_slice.py`, the root `Makefile`'s
`validate-helm`, a new tracked `helm/validation-capacity.toml`, the e2e-tests
chart under `helm/charts/`, and `scripts/tests/test_validate_slice.py`.

- [ ] 6.1 `validate_slice.py helm --change <change>` (and `make validate-helm
      CHANGE=`): build with `IMAGE_SUFFIX=-<change>`; deploy into the change's
      namespace only; scale its workloads to zero when a crashed run left any up;
      delete the release's volume claims and `arkhai-buyer-profiles`, waiting until
      they are gone; run `make -C helm topology-secrets` for the namespace; `helm
      upgrade --install` with the local overlay and 5.4's image overlay, falling
      back to uninstall and install when the upgrade is refused, said in the step's
      detail. The retained-volume check runs only for `default`. The preflight
      checks for `cast` (D4).
- [ ] 6.2 Scenarios as a pod in the namespace from the change's `e2e-tests` image,
      with the release's `test-config` ConfigMap's `helm` profile as the
      `e2e-deal-test` pod has it, selecting `HELM_SCENARIOS`; its log and exit
      status collected into the attempt's directory. No port-forward and no
      localhost port is used (D4).
- [ ] 6.3 After the scenarios, always: the namespace's peak memory in
      `summary.json`, every pod's log and the namespace's events copied into the
      attempt's directory, the other namespaces' replica counts and the rendered
      requests and limits beside the previous validation's, then the namespace's
      workloads scaled to zero, objects and volumes kept (D4, 26 F2).
- [ ] 6.4 The capacity preflight (D4, 17 F3): `helm/validation-capacity.toml` holds
      the memory one release needs, when, and from which change it was measured,
      with a reader and writer in `validate_slice.py`; the preflight counts the
      namespaces with workloads above zero replicas, adds its own, and compares that
      many times the figure with the node's allocatable memory, a deployment that
      would not fit failing the part as environmental with its remedy; it warns and
      goes on with no figure, and when `metrics-server` is missing. It reserves
      nothing. The file starts with no figure.
- [ ] 6.5 Verification. Unit, with the injected runner and reader: each step's
      commands for a change; a crashed run scaled down before its volumes are
      deleted; the upgrade's fallback; the scenario pod's log and status collected;
      the evidence and scale-to-zero after a passing and a failing scenario run; the
      preflight with no figure, without `metrics-server`, fitting, and not fitting;
      `default` alone checked for retained volumes. `uv run --no-project --with
      pytest pytest -q scripts/tests/test_validate_slice.py`; `make test`; one
      `make validate-helm CHANGE=parallel-change-workflows` on the development
      cluster, recorded here with its namespace, tags, and scenario pod. End to
      end: the Helm scenarios `contracts` and `e2e_alkahest_escrow_codecs`, run by
      that validation in the namespace.

## 7. Validation's skill and two validations side by side

Delivers D4's classification of a memory failure and D9's scripted check of two
concurrent validations. Touches `.agents/skills/change-validate/`, a new
`scripts/check_parallel_validation.py`, and `scripts/tests/`.

- [ ] 7.1 `change-validate`: the Helm part runs for its change (`CHANGE=`); a pod
      that could not be scheduled or was evicted while another change's namespace
      had workloads up and the node's allocatable memory was exhausted is
      environmental, its remedy scaling that namespace to zero or rerunning once it
      is down; a container killed at its own limit, or a commit that changed the
      rendered requests or limits, is the commit's; anything else is of unknown
      cause, so `failed` and triaged; the preflight's warnings are reported as such
      (D4, 26 F2).
- [ ] 7.2 `scripts/check_parallel_validation.py <clone> <clone>` (`make
      check-parallel-validation`): runs both clones' Helm parts at the same moment on
      the development cluster and reports, from their summaries and the cluster,
      separate namespaces, tags, and scenario pods, and that neither's release,
      volumes, or pods were touched by the other (D9).
- [ ] 7.3 Verification. Unit: 7.2's report over fake summaries and cluster reads,
      including a run that touched the other's namespace. System: one run of `make
      check-parallel-validation` over two clones on the development cluster,
      recorded here. A fresh-context read of `change-validate` against D4 and the
      delta's Helm requirement. `make check-agent-skills`; `make test`. End to end:
      the Helm scenarios of 6.5, in both namespaces at once.

## 8. History in the owner's workspace, clone removal, and teardown

Delivers D11, D6's removal, and D4's teardown and capacity figure (requirements
"Each change is worked in its own clone", "Each Helm validation is isolated in its
change's namespace"). Touches a new `scripts/change_history.py`,
`scripts/find_change.py`, `scripts/change_clone.py`, `helm/Makefile`,
`scripts/validate_slice.py`, the root `Makefile`, `.agents/skills/`
(`change-archive-cleanup`, `change-design`, `change-plan`, `change-review`,
`change-triage`, `change-closeout`, `change-orchestrate`), `.claude/change-steps.toml`,
`docs/agents/change-workflow.md`, `AGENTS.md`, and `scripts/tests/`.

- [ ] 8.1 `scripts/change_history.py sync <change>` (`make change-history
      CHANGE=`), run in a clone: copy into the workspace, at the same paths, the
      archived change's whole `reviews/` and the evidence its records name
      (`.snapshot/validation/<commit>/`, `.snapshot/e2e-logs/<run>/`); copy what is
      missing, compare what is on both sides by content, extend a workspace file
      that is a byte-for-byte prefix of the clone's, and refuse, naming each, any
      other difference, never overwriting; copy nothing rebuildable (D11, 17 F4,
      26 F1).
- [ ] 8.2 `find_change.py --records <change>`: the change's records in the checkout,
      then in the workspace through the `workspace` remote; every skill that reads
      another change's or an earlier change's records uses it (D11).
- [ ] 8.3 `scripts/change_clone.py remove <change>` (`make change-clone-remove
      CHANGE=`), run by the owner in the workspace: run 8.1 first; refuse, deleting
      nothing and naming what is missing, unless every file of the clone's
      `reviews/` and named evidence is in the workspace with identical contents, the
      branch is merged into `origin/dev`, and the clone has no commit `origin` lacks
      and no uncommitted change (D6).
- [ ] 8.4 Teardown and the figure: `make -C helm teardown CHANGE=<change>` deletes the
      change's namespace and its `-<change>` images; archive cleanup writes the
      figure from the change's latest validation's `summary.json` into
      `helm/validation-capacity.toml` with when and from which change, through the
      writer of 6.4 (D4, 37 F3).
- [ ] 8.5 `change-archive-cleanup`: after its commit and the pull-request draft,
      write the capacity figure and commit it, tear the namespace and images down,
      push, then run `make change-history` as its last act; the draft's notes say
      that a conflict over `helm/validation-capacity.toml` keeps the later recorded
      time (D4, D11, 37 F3). `docs/agents/change-workflow.md` and `AGENTS.md`'s
      "Change workflow" say the owner's workspace holds the history of every
      cleaned-up change, and the guide gains clone removal.
- [ ] 8.6 `.claude/change-steps.toml` (the orchestrator's, as the preamble says): archive
      cleanup gains `make change-history*`, `make -C helm teardown*`, and
      `Edit(helm/validation-capacity.toml)`; every step gains `python3
      scripts/find_change.py --records *` (D8).
- [ ] 8.7 Verification. Repository level (a workspace and a clone): a first copy; a
      second after the log and a transcript grew, extending them; a conflicting file
      refused and named, nothing overwritten; removal refused for each missing
      condition and run after the synchronization; `--records` finding the
      checkout's, then the workspace's. Unit: teardown's commands; the figure
      written with its time and change. `uv run --no-project --with pytest pytest -q
      scripts/tests`; `make check-agent-skills`; a fresh-context read of the changed
      skills against D11 and the delta's clone requirement; `make test`. No
      end-to-end scenario covers it.

## 9. The pilot's evidence and the containerization decision

Delivers D9's evidence and open question 1's decision point, once the pilot's
archive cleanup has run on this branch's tooling. Touches this change's documents
only.

- [ ] 9.1 Record from the pilot's log and records, citing their seq numbers: its
      clone's creation and bootstrap; its validation in its own namespace beside
      this change's round-2 validation, with both namespaces, tags, and scenario
      pods; a round of it read in the owner's workspace, with any commit made during
      the view and what `round-done` did with it; its archive cleanup's history copy
      and the capacity figure that cleanup wrote; each merge of this branch into the
      pilot's and its conflicts; every denial and `orchestrator` line the clones
      produced. Clone removal is not among them: it runs after the pilot merges,
      which follows this change, so 8.7 is its evidence.
- [ ] 9.2 Update `design.md`'s Risks with what the pilot confirmed or disproved.
- [ ] 9.3 Decision gate (open question 1): the owner decides, with the agent, whether
      to open a change to containerize the workflow, and the reasoning is recorded in
      `design.md`, the open question then closed or kept with its trigger. A change
      it decides to open is proposed afterwards on its own branch from `dev`, not
      here (D13 disposition).
- [ ] 9.4 Verification: `make check-change CHANGE=parallel-change-workflows`.

## 10. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [ ] 10.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments this change added to `scripts/`, the Makefiles, `helm/`, and the step
      table; anything to rewrite returns the change to implementation.
- [ ] 10.2 Import placement — confirm: no function-local import added in the files
      this change added or touched under `scripts/`; one that should move returns
      the change to implementation.
- [ ] 10.3 Documentation compliance: re-check D1–D11 against
      `openspec/README.md`'s placement rules.
- [ ] 10.4 Narrative compression of sections 1–9's notes, moving any rationale not
      yet in `design.md` there first.
- [ ] 10.5 Roadmap currency: no goal in `docs/development/ROADMAP.md` covers
      contributor workflow; record that, or update it.
- [ ] 10.6 Campaign index currency: this change's row `in closeout`, under
      independent active changes; `helm-e2e-pipeline-parity`'s `Depends on` and the
      pilot's row are left as they are (archive cleanup releases dependents). `make
      check-change-index`.
- [ ] 10.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=parallel-change-workflows`, and `make check-agent-skills`.
- [ ] 10.8 End-to-end pipeline: record a passing run on the closeout commit and the
      Helm part's namespace evidence, or an explicit blocker naming its cause and
      owner. No pipeline scenario exercises the workflow tooling; the pilot
      (section 9) and the two-validation check (7.3) are its working evidence.
- [ ] 10.9 Promotion, completing the design-promotion record:
      - `openspec/specs/change-workflow/spec.md` — written by the archive (10.11):
        "Each change is worked in its own clone" and "Each Helm validation is
        isolated in its change's namespace" added; "Triage of an implementation
        round", "An orchestrating session advances one change", and "Unattended
        runs are held to their step's permissions" modified. By hand: the Purpose
        paragraph gains clones, and "Evidence" gains `scripts/change_clone.py`
        (`make change-clone`, `make change-clone-remove`),
        `scripts/change_history.py` (`make change-history`),
        `scripts/change_namespace.py`, `scripts/check_parallel_validation.py`, and
        `helm/validation-capacity.toml`.
      - `openspec/specs/change-workflow/architecture.md` — a new "A change is worked
        in its own clone" (D1: why clones rather than branch switching, worktrees,
        or containers; the shared-resource inventory of D7; the owner's workspace
        meets the workflow only for reading; D6's branch taken at its furthest
        point and tracking `origin`, never the workspace); "An implementation round is triaged
        together, in a fresh session" rewritten for the reading in the workspace
        beside validation (D2, D3: why the reading no longer gates validation;
        tooling refuses rather than taking silent risks with the owner's
        uncommitted work); "Validation observes a committed slice" rewritten for the
        change's namespace (D4: fixed per-change rather than commit tags, the
        upgrade from zero, the advisory capacity figure); "Pushing is guarded, never
        repaired" for each step pushing its own work (D8); "The orchestrator relays
        and routes" for its workflow maintenance (D8); a new "History lives in the
        owner's workspace" (D11); "Current limits" rewritten (one orchestrating
        session per change; the container per change, as 9.3 decided; side work
        chosen to stay clear of the critical-path goal's files, D9).
      - `docs/agents/change-workflow.md` — already written in sections 4 and 8;
        "Skills" gains `make change-clone`, `make change-clone-remove`, and `make
        change-history`; "The review directory" says where a cleaned-up change's
        history lives.
      - `AGENTS.md` "Change workflow" — already written in 8.5.
      - `docs/development/DEPLOYMENT_AND_CONFIG.md` "Stateful service persistence"
        — a new "### Validation namespaces" subsection: the namespace per change,
        per-change fixed image tags and why not commit tags, the release upgraded
        from zero over deleted volumes, scale-to-zero, the capacity figure and its
        merge rule, and teardown at archive cleanup.
      - `docs/development/TESTING.md` "### 4. System Integration Tests
        (End-to-End)" — the Helm scenarios run as a pod in the change's namespace,
        reaching services by name.
      - `openspec/specs/README.md` and `docs/development/ARCHITECTURE.md` — no
        change: no new capability or companion, and the workflow is contributor
        process.
- [ ] 10.10 Documentation citations: `make check-change
      CHANGE=parallel-change-workflows`, which runs `make check-doc-citations
      CHANGE=parallel-change-workflows` and `openspec validate
      parallel-change-workflows --strict`.
- [ ] 10.11 Archival: `openspec archive parallel-change-workflows -y`, merging the
      delta into `openspec/specs/change-workflow/spec.md`; the index row then links
      the archive; `make check-change CHANGE=parallel-change-workflows`.
