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
      Round 1 triage (52 F3): the bootstrap record is now written by the `sh`
      supervisor itself, its own `$$` with the command, log, and start time, through
      a temporary file, before the command runs; `start_bootstrap` forgets a failed
      run's record with its status, and writes the record only when the supervisor
      has not yet (an injected spawn writes none). So no interruption of
      `make change-clone` leaves a bootstrap running unrecorded. Evidence: below
      section 4's round 1 triage note.

## 2. The round view in the owner's workspace

Delivers D2's view and `round-done`'s carry, and D3's removal of the view's push
and dispatch (requirement "Triage of an implementation round"). Touches
`scripts/round_view.py`, `scripts/change_workflow/wrapper.py`, the root `Makefile`,
`scripts/tests/test_round_view.py`, and `scripts/tests/test_change_workflow_wrapper.py`.

- [x] 2.1 The record of a run in progress (D2 step 2): the wrapper writes the run's
      process, step, and change into its checkout's Git directory as a run starts,
      and removes it once the run's line is written, an interrupt included;
      `runs_in_progress(root)` reads the live ones, a dead process counting as none.
      Note: a new module, `scripts/change_workflow/running.py`, beside the wrapper
      rather than in it, since the round view reads it and need not import the
      harness: one file per run under `<git-dir>/change-runs/` (the wrapper's pid
      and a random suffix, so validation and a review side by side each have
      theirs), written by `recorded_run` around the whole turn, model fallbacks
      included, and removed in its `finally` after the line is written.
      `live_runs(directory)` reads a directory; `runs_in_progress(root)` the
      checkout's. Outside a Git checkout nothing is recorded. A record is written
      aside and renamed, so a reader never takes a half-written one for no run. The
      review runner, which moves no branch but reads `HEAD` throughout, records its
      runs too, its directory injectable as `runs`. Beyond the files the section
      names, it also touches `scripts/change_workflow/running.py` (new),
      `review.py`, the package docstring, the test fixtures (whose wrapper now
      records nothing), `test_change_workflow_review.py`, and
      `test_change_next_step.py` (the view's dropped `e2e` argument).
- [x] 2.2 `round_view.py start <change>` for a change whose clone holds its branch
      (1.3), run in the workspace: refuse a dirty workspace, naming the files; a run
      in progress there (2.1), naming it; another change's open view, naming the
      change; then fast-forward the workspace's branch from the clone's `workspace`
      remote counterpart (`git fetch <clone> <branch>`), refusing a diverged one;
      record where the workspace was (branch or detached commit); check out the
      branch and mixed-reset it, with `-N`, to the base read from the clone's latest
      `round` line (D2). The state records the clone, so `done` and refresh find it.
      Note: the base falls back, as in place, to the clone's latest triaged
      validation. A workspace branch that is not an ancestor of the clone's — one
      holding a commit of the owner's that triage has not yet pulled, or diverged —
      is refused, naming it; a branch the workspace lacks is created at the
      clone's commit, and one checked out there is fast-forwarded with
      `merge --ff-only`. The state is written before the checkout moves; a failure
      that left the checkout where it was removes it, one after leaves it for
      `make round-done` (the failure paths are untested: a clean workspace leaves
      no way to make the checkout fail). `round-done` refuses while a run is in
      progress, since closing moves the checkout too. The in-place view does not
      check that the checked-out branch is the change's, as before.
      `start` refuses in a clone (its `workspace` remote names a directory), whose
      branch every step runs on.
- [x] 2.3 Refresh (D2): `start` again for the change whose view is open moves the
      view to the branch's new head over the same base, after the same fetch;
      refuse while the workspace holds uncommitted edits or commits made during the
      view, naming them and `make round-done`.
      Note: edits are the worktree's differences from the view's commit plus
      untracked files; once there are none, the move is `git reset --hard` to the
      new head, which overwrites no edit of the owner's (an ignored file where the
      new head adds one would be replaced), then the state is written, then the
      mixed reset to the base, so a failure leaves the state where the branch is. A
      new head that does not descend from the view's is refused, and so is a
      `BASE=` given to a refresh; the same head leaves the view as it is. An
      in-place view is not refreshed (now in D2): its branch is the one its steps
      run on, and nothing moves it while the view is open, so `start` again
      refuses as before.
- [x] 2.4 `done` carries commits made during the view (D2, 17 F1, 26 F3, 37 F2):
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
      Note: every commit is judged before any is made; the replacements are built
      with `read-tree`, `update-index --index-info`, `write-tree`, and
      `commit-tree` in a private index, so the checkout's own index, which holds
      the view, is untouched until the final mixed reset. The kinds: a path the
      round added or deleted, then a mode the round changed, a symlink or
      submodule, or a binary (a NUL in a blob's first 8000 bytes, Git's test) on
      any side, must equal the head's; a text file present at both ends must also
      keep the head's mode, and is refused when the commit deletes it. "Left the
      base's line" is a branch not descending from the base, or whose merge base
      with the round's head is not the base — a reset into the round followed by a
      commit. A branch reset to one of the round's own commits carries nothing. A
      branch already at or past the round's head is closed as it stands, unless a
      commit not descending from the head reaches it — a commit made on the base
      and merged with the head — which is refused. A commit whose replayed tree
      equals the previous one's is dropped and named (`Carried.replacement` is
      None). Every refusal's way back names `make round-done`. The carry applies
      to a view in place as well, replacing the earlier leaving of such commits'
      changes uncommitted. Returning the workspace is skipped while it holds
      uncommitted edits, which a checkout would carry onto the branch it went back
      to: `done` closes the view, leaves the workspace on the change's branch, and
      says to commit or discard them and check out where it was. These, the
      refusal of a text file's mode change, the dropping of empty commits, and how
      the view tells a clone's change from one in place are now recorded in D2.
- [x] 2.5 The view of a change with no clone, whose branch is the workspace's own,
      keeps today's behaviour: the branch reset in place, the reading first (D2,
      D3). `round_view.py` no longer pushes or dispatches: `--no-e2e`, the
      `e2e-baseline` action, `E2E_BASELINES`, and `make round-e2e-baseline` are
      removed, and `make round-view` loses `NO_E2E` (D3). `check` refuses only in
      the checkout whose branch the view moved.
      Note: the in-place view now also refuses a run in progress and names a dirty
      worktree's files. `check` needed no change: the state lives in the Git
      directory of the checkout the view moved, so a clone's steps never see a
      workspace's view.
- [x] 2.6 Verification. Repository level (a workspace and a clone in a temporary
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
      Evidence: `scripts/tests/test_round_view.py`, 65 passed — repository level
      (real Git in a temporary directory; runs in progress injected). In place:
      the view, `done` with and without edits, the base from the round line and
      from the triaged validation, the guard, the earlier recovery cases, and each
      refusal (dirty worktree naming the file, a run in progress naming it, a base
      not an ancestor, a detached `HEAD`, an empty round, an unknown change).
      Carrying, in place: a commit of an edit, kept with its author, date, and
      message, and `make round-done`'s output naming it beside its replacement; a
      whole file committed then edited on, the edit left uncommitted; "commit all"
      carrying only the owner's edit, and with no edit dropped and named; two
      commits carried oldest first; a committed deletion of a file the round
      deleted (dropped, holding nothing beyond the round) before a carried edit; a
      file lacking a round change, staged by part and with the change removed,
      each refused with the way back and nothing moved; an edit inside a line the
      round changed refused; a text file the round changed refused when the
      commit deletes it or changes its mode; an edited added file refused; a
      binary refused at the owner's contents and carried, beside an owner's edit,
      at the round's; a symlink and a mode the round changed carried as the round
      left them, and a mode the commit undid refused; a merge (a
      two-parent commit made with `commit-tree`) refused, and one bringing in the
      round's head over an owner's commit refused; a reset into the round followed
      by a commit, and an amended base, refused as leaving the base's line. From a
      clone (a workspace with a bare `origin` and a clone made by
      `change_clone.create`): the view on the branch by name, the clone's `HEAD`
      and status unchanged and its `check` passing; `done` returning to `dev`, to
      a detached commit, and to the branch itself; an owner's commit carried and
      then pulled into the clone fast-forward; uncommitted edits keeping the
      workspace on the branch; the workspace branch fast-forwarded by `update-ref`
      and, when checked out, by `merge --ff-only`; the refusals of a workspace
      branch ahead of the clone and one diverged from it, a dirty workspace, a run
      in progress, another change's view, and a view in the clone; `done` refused
      with a run in progress; a refresh onto a triage fix over the same base, one
      with nothing new leaving the view as it is, and its refusals over edits,
      over a commit made during the view, over a branch moved back to the round by
      hand, with a run in progress, onto a head not descending from the view's,
      and of a `BASE=`. `scripts/tests/test_change_workflow_wrapper.py`, unit with
      the runs directory injected: a run's record present while it runs and at
      the clock reading the log takes for the line it then writes, gone after; an
      interrupted run's likewise; a record whose process is gone counting as none;
      and `runs_directory` None outside a Git checkout (the wrapper is not run
      there). `scripts/tests/test_change_workflow_review.py`: a review recorded
      while it runs and forgotten after. `uv run --no-project --with pytest pytest
      -q scripts/tests`: 1162 passed after the last fixes. `make check-packaging`
      and `make check-comment-hygiene`: passed. `make test`, before the last
      fixes, which touched only scripts and their tests: every suite passed, the
      script tests' 1157 among them, up to `make -C helm
      test-render`, which failed on the Helm JSON schema's error wording
      (`internalRegistryTrust` got null, a port's type, retired keys) in the
      storefront and bare-metal chart render tests and
      `helm/tests/test_release_topology.py`, as in section 1; nothing under
      `helm/` changed. No end-to-end scenario covers it.
      Handoff: the change-validate skill (`make round-e2e-baseline`), the
      orchestrating skill and `change-implement`'s report (the view pushing and
      dispatching), `docs/agents/change-workflow.md`, and the step table's
      validation allow of `make round-e2e-baseline` still describe the removed
      push and dispatch; sections 4.1, 4.2, 4.4, and 4.5 rewrite them, so this
      round is not validated before section 4 is committed.
      Round 1 triage (52 F2, 52 F4): before each move of the worktree — the
      opening's checkout or fast-forward, the refresh's hard reset, and
      `round-done`'s return — the view lists the paths the target tracks and the
      current commit does not, and refuses, naming them and moving nothing, when
      anything sits on disk at one, or under a parent that is no directory (Git
      overwrites an ignored file there silently); a return so blocked is skipped,
      the view closed and the workspace left on the change's branch, as for
      uncommitted edits. A failed checkout on opening, the workspace not moved,
      now puts back the branch ref it moved (or deletes one it created) before
      removing the view's state; the earlier note's untested failure path is
      tested by holding `index.lock`, which fails the checkout but not
      `update-ref`. Evidence: below section 4's round 1 triage note.

## 3. The next-step computation for a change in a clone

Delivers the computation's clone routing, the round of three records, and the
owner's design-review waiver after a return (D3, D6, D8's 36 R1; requirements
"Each change is worked in its own clone", "Triage of an implementation round", "An
orchestrating session advances one change"). Touches `scripts/change_next_step.py`,
`scripts/change_workflow/log.py`, and their tests.

- [x] 3.1 Clone routing (D6): for a change whose branch is checked out neither in
      the computing checkout nor in a clone (1.3), the result is `clone`, naming the
      `make change-clone` arguments; unless the workspace holds the change's
      `reviews/` (37 F1), when the result is `owner`, naming both routes — check out
      the branch in the workspace and go on there, or move it into a clone by hand
      per `docs/agents/change-workflow.md` (4.5). For a change whose clone exists,
      run in the workspace, the result names the clone's directory, from which the
      session runs the computation and every step.
      Note: a clone `clone_of` finds is looked for first, whatever the workspace
      has checked out — the owner may have the branch checked out to commit on it
      — as the round view tells the cases apart (D2). Otherwise "checked out in the
      computing checkout" is its own name's branch, `feat/<change>`, or a branch
      the owner's decision in the change's log says it is worked on
      (`branch_decisions`, as each step's branch check reads it); in a clone, it is
      the clone `clone_of` finds for the change. The results are
      `{"step": "clone", "arguments": {CHANGE, BRANCH, FROM}}` and
      `{"step": "in-clone", "clone": <dir>}`, new step names the orchestrating
      skill learns in 4.1. The workspace holding the change's records means a
      non-empty `reviews/`. A change whose directory this checkout lacks stays
      `unclassified`, as `make orchestrate` already refuses it. A workspace showing
      a clone's round has the change's branch checked out only for reading, so
      its view of that change routes to the clone; another change's view in place
      holds a change with no clone as before. An archived change is `done` before
      any routing, so a merged change seen from `dev` is not sent to a clone. In a
      clone of another change, the result is `owner`, naming the workspace.
- [x] 3.2 Bootstrap routing (D6): an incomplete clone names `clone`; while the
      bootstrap is `running`, design and planning steps are named and
      implementation and validation steps wait, the result saying so; `failed` is
      `owner`, an environmental failure naming its log and that `make change-clone`
      restarts it; `succeeded` routes as today. A change with no clone routes as
      today.
      Note: incomplete is a clone `clone_of` finds whose bootstrap is `absent`,
      routed `clone` with the change alone as argument; a clone directory
      `clone_of` rejects (killed before its checkout) also routes `clone`, with
      the full arguments, which `make change-clone` then finishes. In design and
      planning every step is named while the bootstrap runs, and so is a design or
      plan step in a later phase (a confirmed return); any other step in
      implementation and closeout is held as `{"step": "wait", "waits": <the
      step>}` — triage, closeout, and archive cleanup too, since each runs suites
      or packaging (D6 now says so). A failed bootstrap goes to the owner whatever
      the phase (`environmental`, `log`), so design does not run on beside a
      failure nobody has seen.
- [x] 3.3 The round of three records (D3): for a change in a clone, once a round's
      sections are committed, the result is `validate-and-review` together with the
      owner's reading — the session opens the view in the workspace and starts both
      in the clone — and triage is named only once the owner record, the review,
      and the validation exist. The view's state is read from the workspace through
      the clone's `workspace` remote, so an open view there holds triage and nothing
      else. A change without a clone keeps the reading first.
      Note: the reading rides on whichever of validation and review is missing,
      as `reading: true` and the `workspace`, while no owner record exists and no
      view is open; with both in and no owner record, the result is `round-view`
      with the `workspace`; with a view of the change open where triage would be
      named, the result is `owner`, to save the answer in the clone and close the
      view (or, with the answer already saved, only to close it). Past triage an
      open view holds nothing, so the next round or the pre-closeout review is
      named with it open; but a view whose base is not the current round's
      recorded commit is an earlier round's, and while the current round is
      unread the result is `owner`, to close it first. The delta scenario "The
      orchestrating session restarts during a round view" now says the view is
      closed before triage, and before any other step only for a change without a
      clone, as D3 allows validation and the review beside the reading.
- [x] 3.4 The waiver after a return (36 R1): `note … orchestrator --next plan`,
      `by: owner`, naming no run, is accepted once the change is `in design` and the
      latest design run finished after a confirmed return; any other `next` other
      than `review` and `archive-cleanup` still names the run it resolves. `_design`
      honours that direction and names planning rather than a design review.
      Note: `note_orchestrator` takes the change's `status`, which the command
      line reads from the index row; `redesigned_after_return(entries)` in
      `change_workflow/log.py` is the shared test, used by `_design` as well, which
      names planning for an owner's `next: plan` line with no run after the
      finished design run, once: after a plan run that followed the waiver, a
      waiting one (a stop, a question) is brought to the owner with its `seq`, and
      a finished one that left the change in design goes to the owner, so
      planning is never rerun by itself — the plan skill's entry check refuses the
      status `in design` today (section 4's handoff below).
- [x] 3.5 Verification. Unit, over fixture changes and logs, in
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
      Evidence: `scripts/tests/test_change_next_step.py`, unit with the location
      seams injected (`branch`, `workspace`, `clone`, `bootstrap`, beside `head`
      and `view`): a change with no clone and no records (`clone`, with its
      arguments and command), one whose records are in the workspace (`owner`, both
      routes), one whose clone exists (`in-clone`), the same with the workspace on
      the change's branch, an unfinished clone (`clone`), an unknown change
      (`unclassified`), a change worked in the workspace and one on the owner's
      shared branch routing as before, a clone's view in the workspace sending its
      change to the clone, another change's view in place still holding a change
      with no clone, a clone of another change; the bootstrap running in design,
      planning, and implementation (`wait`, naming the step it holds), and holding
      validation with review and closeout, but not a design step after a return;
      failed in design and implementation, absent and succeeded in
      implementation; in a clone, a committed round naming validation and review
      with the reading, an open view not holding them, triage held for the
      reading and then named `round-view`, a view left open after the answer
      naming `make round-done` alone, an earlier round's view to be closed first,
      triage once all three records exist, an open view holding nothing past
      triage; a change in the workspace keeping the reading first; planning named
      after the waiver, by the directive and by `_design` (called directly), and a
      plan run after the waiver, stopped or finished in design, going to the
      owner rather than rerun. A clone directory `clone_of` rejects is not tested
      at this level (its `clone` result is the no-clone one). Repository level, in
      the same file (real Git, a workspace with a bare `origin`, its clone made by
      `change_clone.create`, the view opened by `round_view.start`): from the
      workspace `in-clone` naming the clone, then in the clone the round's
      validation and review with the reading, `round-view` once both records
      exist, and `owner` while the workspace's view is open. The existing tests
      now inject the change as worked here (`HERE`); the round-view test's
      repository uses the change's own branch. `scripts/tests/test_change_workflow_log.py`,
      unit: the waiver accepted after a finished redesign, refused by the
      orchestrator, outside `in design`, with no return, with the design not
      finished, and with the design before the return; the command line reading
      the status from the index. `uv run --no-project --with pytest pytest -q
      scripts/tests`: 1201 passed after the fresh-context check's fixes. `make
      test`, before those fixes, which touched only `scripts/change_next_step.py`
      and its tests: every suite passed, the script tests' 1194 among them, up to
      `make -C helm test-render`, which failed on the same Helm schema error
      wording as in sections 1 and 2; nothing under `helm/` changed. `make
      check-packaging` and `make check-comment-hygiene`: passed. `make
      check-change`: only the citations of the scripts sections 5, 7, and 8
      create. Real computation on this change, in this workspace, before its last
      implement run stopped: `implement`, sections 1–3; since, the owner for
      that stopped run. No end-to-end scenario covers it.
      Handoff: section 4 teaches the orchestrating skill the results `clone`,
      `in-clone`, and `wait`, the `reading` and `workspace` fields, and the owner
      result for a clone's open view; `change-plan`'s entry check reads a waiver
      from the design triage's `## Next` and the ledger, and must also accept the
      orchestrator's waiver line with the status still `in design` (4.1 records
      it; no task of 4.2 names that check, so section 4 should).

## 4. The skills, the step table, and the contributor guide for clones

Delivers D6, D8, and the skill side of D2 and D3 (requirements "An orchestrating
session advances one change", "Unattended runs are held to their step's
permissions", "Triage of an implementation round"). Touches `.agents/skills/`
(`change-orchestrate`, `change-design`, `change-plan`, `change-implement`,
`change-triage`, `change-validate`, `change-closeout`, `change-archive-cleanup`),
`.claude/change-steps.toml`, and `docs/agents/change-workflow.md`.

- [x] 4.1 `change-orchestrate`: run the computation in the workspace and, once a
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
      Note: a new "Where the change is worked" section routes `clone`, `in-clone`,
      `wait`, and the `owner` results carrying `environmental`, `routes`, or the
      workspace; after `in-clone` every command runs in the clone
      (`python3 <clone>/scripts/…`, `make -C <clone> …`), only `make change-clone`
      and the view in the workspace. For a round in a clone the session starts
      validation and the review first and then opens the view, so a view the
      workspace refuses holds nothing up; `reading` is read on whichever of them
      carries it. The waiver's ledger line (`"review": "plan"`, lens `readiness`)
      goes into the clone's `interventions.jsonl` uncommitted, for planning to
      commit. The pilot merge is written generally, as merging any branch whose
      tooling the change's later rounds need: `git -C <clone> pull --no-rebase
      workspace <branch>`, index-row conflicts resolved each row as its own branch
      has it, any other conflict aborted and taken to the owner. Workflow
      maintenance is committed only in a clone and only between steps; for a
      change in the workspace the session makes the edit and the owner commits it.
- [x] 4.2 The committing skills push: `change-design` commits its recorded design
      once the owner says it is settled; `change-design`, `change-plan`,
      `change-implement`, `change-triage`, `change-closeout`, and
      `change-archive-cleanup` push each commit through `make push-branch` (D8).
      `change-triage` pulls the owner's commits with `git pull --ff-only workspace
      feat/<change>`, refusing anything else, and identifies them as the commits
      between the round's head and what it pulled; it scopes the round from the
      `round` line's base, as the review does (D2, D3). `change-validate` dispatches
      the pipeline itself and no longer reads a baseline the view recorded (D3).
      Note: `change-plan` also commits its plan (it gained `git add`/`git commit`
      in 4.4), and its entry check accepts the orchestrator's waiver line with the
      status still `in design` (section 3's handoff), reading it from the log and
      `change_next_step.py`. Beyond the task, found by the fresh-context check: a
      design review's triage now commits and pushes its edits, whichever `## Next`
      records, since nothing else commits them now that the owner no longer
      commits design-phase work and the guarded push refuses an unclean worktree.
      The triage skill decides a clone by its `.git/config` naming a `[remote
      "workspace"]` (no rule allows `git remote` or `git config`), pulls the
      owner's commits at the start of an implementation round, before they are
      presented, and reverts one the owner rejects among the fixes — D2's order,
      since the commits are identified by the pull; the delta scenario "The owner
      commits an edit while reading" says triage pulls "once disposed of", which
      review should reconcile. D3's "scopes the round from the `round` line's
      base, as the review does" is written without the comparison: the review
      reads the change against `REVIEW_BASE` (`dev`), not the round. `change-validate`
      clarifies that a view in the owner's workspace for a change in a clone does
      not stop validation. `scripts/check_push_ready.py`'s refusal of a protected
      branch now says "a step pushes", not "validation pushes".
- [x] 4.3 Every step skill's "Running unattended" section gains: run Git in the
      current checkout, never with `-C` (D8, 36 R2).
      Note: `change-review` has no bulleted unattended section; the sentence joins
      its paragraph.
- [x] 4.4 `.claude/change-steps.toml` (the orchestrator's, as the preamble says): `make
      push-branch` moves from the deny to the allow list of design, plan, triage,
      implement, closeout, and archive cleanup; design and plan gain `git add *`
      and `git commit *`; triage and implement gain `git pull --ff-only workspace *`;
      the round view stays denied to every step (D8).
      Note: the orchestrator's edit was in the worktree as the session started and
      is committed with this section; it also drops validation's allow of `make
      round-e2e-baseline` (section 2 removed the target), rewrites the preamble's
      push sentence, and the design row's comment. Left for the orchestrator, which
      alone may edit `.claude/`: the preamble still says a step's permissions
      change "by the owner", where D8 lets the orchestrating session commit them
      on the owner's word; the design comment sits above `[steps.review]`; and
      `git pull --ff-only workspace *` also matches trailing options such as
      `--rebase`, so a narrower rule may be wanted.
- [x] 4.5 `docs/agents/change-workflow.md`: a change worked in its own clone —
      where clones live, `make change-clone` and the bootstrap's states, steps run
      with `make -C <clone>`, taking a step over, reading a round in the workspace
      and what `round-done` does with commits made during the view and what it
      refuses; working a change in the workspace without a clone; moving a change
      already under way into a clone by hand: settle any run waiting on an answer in
      the workspace, merge `dev` into its branch, `make change-clone`, move
      `reviews/` and the evidence its records name into the clone and check the
      copies are identical (D6, 37 F1).
      Note: a new section, "A change in its own clone"; the skills table, the
      orchestrating session's commits, taking a step over from its checkout, the
      step table's maintenance, and the review section's reading paragraph are
      updated to match. The move by hand copies, checks with `diff -r`, then
      removes the workspace's copies. History and clone removal are not written
      here: their targets come in section 8.
- [x] 4.6 Verification: `make check-agent-skills`; `make check-change
      CHANGE=parallel-change-workflows`; `uv run --no-project --with pytest pytest -q
      scripts/tests/test_change_workflow_steps.py`, extended with the table's new
      allows and denies (unit); a fresh-context read of each changed skill against
      D2, D3, D6, D8 and the delta's orchestrating-session and permissions
      requirements, recording what it found; `make test`. Validated in the owner's
      workspace on the existing Helm part. No end-to-end scenario covers it.
      Evidence: `scripts/tests/test_change_workflow_steps.py`, unit over the real
      step table, 35 passed: every committing step (design, plan, implement,
      triage, closeout, archive cleanup) may run `make push-branch` and no other
      push, validation `make push-branch` and `make run-e2e`, the review none, and
      `git push`, `make push-branch FORCE=1`, and `git -C … push` none; exactly the
      committing steps may `git add` and `git commit`; triage and implementation
      alone may `git pull --ff-only workspace <branch>`, and no step a pull
      without `--ff-only` or from `origin`; no step may run `git -C`. The test
      shows the rule's prefix, not that every form it matches is a fast-forward
      (above). `uv run --no-project --with pytest pytest -q scripts/tests`: 1204
      passed. `make check-agent-skills` and `make check-comment-hygiene`: passed.
      `make check-packaging`: passed. `make check-change`: only the citations of
      the scripts sections 5, 7, and 8 create. `make test`: every suite passed,
      the script tests' 1204 among them, up to `make -C helm test-render`, which
      failed on the same Helm schema error wording as in sections 1–3; nothing
      under `helm/` changed. The fresh-context read of the skills found, and this
      section fixed: nothing committed a design review's triage edits; the view
      opened before validation could hold a clone's validation up behind the
      workspace; `reading` was tied to `validate-and-review` alone; the waiver's
      ledger line named no checkout; workflow commits were allowed in the
      workspace, which D8 does not give; triage's refusal named only divergence
      when an open view is the likelier cause; the push guard's message. Declined
      or left: the step table's comments and the pull rule's breadth (the
      orchestrator's file); implementation's pull allowance, which D8 grants and
      no skill uses; the pull-before-disposition order (D2, above); D1's last
      paragraph telling the cases apart by the checked-out branch where D2 and
      the computation look for a clone first, a design wording for review. A
      second fresh-context read, after those fixes, found no breach of the
      guidance and every named target, field, and option present; this section
      fixed what it found within its reach: an owner's rejected commit is undone
      by edits (no rule allows `git revert`); a workflow commit between a round's
      sections and its triage would move the `HEAD` its validation and review
      describe, so the orchestrating session grants a stopped run's permission for
      its resumed run then and commits the table edit after the triage; its
      commits wait for a clean worktree (the waiver's pending ledger line); the
      owner may name another `BRANCH` or `FROM` for `make change-clone` (the
      pilot's branch starts from this change's); the guide's table rows for
      triage and orchestration, and its step-table sentence. `make test` was run
      again after the push guard's message changed: the same result. Left for
      review, each needing a decision this section does not have: whether a
      triage of every kind commits what it changed — an implementation,
      pre-closeout, or closeout triage that writes only ledger lines, tasks, or
      design edits, with no fix, leaves them uncommitted for the next step's
      clean-worktree checks, and committing a pre-closeout triage's index row
      would make closeout ask for a new validation, since the computation's
      validation check allows only records and ledgers to differ; and that a
      triage started by hand for a change in a clone cannot see the owner's view
      still open in the workspace (a step may not run Git there), so only the
      computation holds it. No end-to-end scenario covers it.
      Handoff: this section's skills take effect for this change's own next steps:
      triage and validation of round 1 run on them, and validation dispatches the
      pipeline itself (no baseline). This section's commit was not pushed: the
      session ran on the skill as loaded before 4.2, which said not to; the next
      committing step or validation pushes it. The permanent `change-workflow`
      spec and architecture still describe validation's single push and the
      reading first, until closeout (10.9).
      Round 1 triage (52 F1, decided B; the owner's wording edits): a triage of
      every kind commits and pushes what it changed that no fix commit holds
      (`change-triage`, `docs/agents/change-workflow.md`'s table). Once a
      pre-closeout review's triage has run, a validation clears a `HEAD` differing
      from the validated commit only under `openspec/` and `docs/` (D8):
      `change_workflow/records.py` gains `is_record`, `is_documentation`, and
      `validation_problem(exempt=)`; `change_next_step.py` passes
      `is_documentation` after a pre-closeout review, advancing or another round,
      and its `validated` now reads ancestry through the injected `changed_since`,
      so two older tests' expected wording names the changed path rather than
      "not HEAD"; `change_workflow/review.py` exempts documentation for a
      pre-closeout review once a triaged one exists; `change-closeout`'s entry
      check and the triage table's pre-closeout row say the same. An
      implementation triage's commit of documents alone is still validated. The
      delta gains the triage-commit and closeout-gate sentences, two scenarios,
      and a MODIFIED "The next step is computed from the files" (its another-round
      scenario). Wording: D1's last paragraph now says a clone is looked for
      first; the delta scenario "The owner commits an edit while reading" pulls
      before presenting.
      Evidence for the round's fixes (52 F1–F4), all unit or repository level per
      `TESTING.md`: `test_change_next_step.py` (unit), a pre-closeout triage's
      document commit going to closeout unvalidated and one with code to
      validation, another pre-closeout round over documents reviewed again, an
      implementation triage's document commit validated;
      `test_change_workflow_review.py` (unit), the next pre-closeout review
      admitted over a document commit after a triaged one, and refused before any;
      `test_round_view.py` (repository level), opening by checkout and by
      fast-forward refused over an ignored file the round tracks, a refresh
      refused over one the fix tracks, the return skipped over one where `dev`
      tracks a file, an ignored file elsewhere moving freely, and a failed
      checkout putting the branch back (absent, and at the base) with no view
      open, and, over `_in_the_way` directly, a file the target replaces with a
      directory let through, an ignored file where the target puts a directory
      refused, and a directory of tracked files the target replaces with a file
      let through unless it holds an ignored one; `test_change_clone.py`
      (repository level), the real spawn recording itself while its command runs,
      nothing else writing, and a rerun leaving it alone. `make test`, before the
      fresh-context check's fixes: every suite passed, the script tests' 1217
      among them, up to `make -C helm test-render`, which failed the fifteen
      render tests 53 V1 names and no other. After those fixes, which touched only
      scripts, their tests, and documents: `uv run --no-project --with pytest
      pytest -q scripts/tests`, 1221 passed; `make check-packaging`, `make
      check-comment-hygiene`, and `make check-agent-skills`, passed; `make
      check-change`, only the citations of the scripts sections 5, 7, and 8
      create. The fresh-context check of the diff found no breach of the
      guidance (no function-local import, no history in comments, nothing
      private) and the code doing what each disposition says; fixed from it: a
      directory of tracked files the target replaces with a file was refused;
      a failed ref restore would have left the view's state behind (the state is
      now removed first); the computation's documentation comment had lost its
      constant (moved to `records.py`); the review runner's docstring,
      `change-review`, `change-triage`'s fix and routing paragraphs, and the
      delta's "the commit MUST be validated again" still stated the records-only
      rule; and the parent-path cases were untested. Declined: that the section 5
      note was missing — the check read the tree before the note was written.

## 5. Per-change image tags and namespaces in the build and Helm targets

Delivers D4's images, namespace naming, Secrets, and manual access (requirement
"Each Helm validation is isolated in its change's namespace"). Touches the root
`Makefile`'s build targets, `core/registry/Makefile`,
`domains/vms/storefront/Makefile`, `provisioning/compute/service/Makefile`,
`dev-env/Makefile`, `e2e-tests/Makefile`, `helm/Makefile`, a new
`scripts/change_namespace.py`, `helm/tests/`, and `scripts/tests/`.

Round 2's Helm evidence (6.5, 7.3, and the pilot's validation beside it) needs
`make -C helm test-render` to pass: validation 53 found fifteen render tests failing
on `dev`'s values schema (`got null, want object`), which stops the Helm part before
it deploys (53 V1). No change owns the failure; the index records it as unowned
work under the local end-to-end stack campaign. Its fix lands and is merged in from
`dev` before round 2 is validated.

- [x] 5.1 `IMAGE_SUFFIX`, empty by default, appended to every image tag the build
      targets write — `build`, `build-dev`, `build-seller`, and each image target the
      root `Makefile` and the subproject Makefiles define — so `make build-dev
      IMAGE_SUFFIX=-<change>` builds `arkhai:storefront-<change>` and its siblings;
      compose, the pipeline lanes, and the owner's own deployments keep bare tags
      (D4).
      Note: the root image targets append it to their `-t`; the five that delegate
      (`build-registry`, `build-storefront`, `build-provisioning`, `build-dev-env`,
      `build-test-image`) still run `cd <project> && make build`, so no jobserver
      reaches them and nothing about their order changes, now passing
      `IMAGE_SUFFIX=$(IMAGE_SUFFIX)` explicitly, which `make -n` shows. Each
      subproject's `IMAGE_SUFFIX ?=` ends the image's tag, `arkhai:<tag><suffix>`
      (the VM storefront's `build-no-cache` too); a suffixed build writes no
      commit tag, since D4 tags a change's images per change alone and a commit
      tag would keep one image per validated commit, while a bare build still
      writes `arkhai:<tag>-<sha>`, which `push-images` reads. The e2e-tests
      targets that run the image (`test-buyer-machine`, `test-container-module`)
      keep the bare tag, as the lanes do.
- [x] 5.2 `scripts/change_namespace.py <change>` prints `validate-<change>`, cut to 63
      characters with a short hash of the full name appended when longer; every
      `helm/Makefile` target that takes `NAMESPACE=` also takes `CHANGE=`, deriving
      the namespace through it (D4).
      Note: the hash is the first 8 hex digits of the full name's SHA-256, after a
      cut of 54 characters with any trailing hyphen dropped. A name that is not a
      change name (lowercase letters and digits in hyphen-separated words) is
      refused, exit 2. `helm/Makefile` derives `NAMESPACE` once, at the top, from
      `CHANGE`, so every target reading it takes `CHANGE=`; `CHANGE=` beside a
      command-line `NAMESPACE=` is refused, and so is a `CHANGE` the script
      refuses. A `make` step's own `CHANGE=` reaches `make -C helm` through
      `MAKEFLAGS`, inherited by everything the step runs: an unattended
      validation started as `make validate CHANGE=<change>` derives the change's
      namespace in every `make -C helm` call unless that call passes `CHANGE=`
      itself, which section 6's `validate_slice.py` must do on every call
      (`CHANGE=` empty for `default`), and tests reading these targets drop
      `MAKEFLAGS` and `CHANGE`.
- [x] 5.3 `make -C helm forward CHANGE=<change>` forwards that namespace on the usual
      ports, a second forward failing on bind and naming the port; `make -C helm
      resume CHANGE=<change>` scales its workloads back up; `topology-secrets` runs
      for a derived namespace (D4).
      Note: forwarding moved into a new `helm/scripts/port-forward.sh` (`start`,
      `stop`), run with `bash` since the file carries no executable bit. `start`
      waits for each forward to print kubectl's "Forwarding from" or exit; a
      forward that exits is named with its port and kubectl's error, every
      forward is waited for so all failing ports are named, and on any failure
      every forward it started is stopped and `forward` fails. `stop`
      (`unforward`) now waits up to 15 s (`WAIT_SECONDS`) for its forwards to
      exit, so the `unforward` `forward` runs first cannot leave its own ports
      bound, and fails over one that outlives the wait, keeping it in the PID
      file for the next `unforward`.
      `resume` reads every installed release's manifest in the namespace (`helm
      list`, `helm get manifest`) and scales each Deployment and StatefulSet to
      the replicas it states, so it renders nothing from the checkout and changes
      no release; it fails when no release states any. A stale PID file whose
      processes ignore the signal makes `unforward`, and so `forward`, fail
      naming the file to remove. `topology-secrets.sh` creates its namespace when
      `kubectl get namespace` finds none, before any Secret.
- [x] 5.4 The image overlay: a function that writes a values overlay naming every
      image tag `helm/values.yaml` sets with the suffix; a render test in
      `helm/tests/` holds the overlay to every image the chart renders, so an image
      added later cannot stay bare (D4).
      Note: `change_namespace.image_overlay(change, values)` and
      `write_image_overlay` (JSON, which Helm reads as YAML; also
      `change_namespace.py <change> --image-overlay <path>`) name the `tag` of every
      mapping with `name: arkhai` — an image built here; a third-party image's tag
      is left alone — by its path of keys, in the block mappings `helm/values.yaml`
      is written in, skipping block scalars and refusing a tag inside a list rather
      than skipping it. `helm/values.yaml` gains the
      two image settings it left to subchart defaults — `bare-metal-storefront.image`
      and `validate-contracts.integrationTests` — since the overlay can name only
      what that file sets; the render test found the second missing. The test is
      `helm/tests/test_image_overlay.py`; "built here" is an image named `arkhai`
      with no repository, and third-party images (busybox, redis, mailpit) keep
      their tags.
- [x] 5.5 Verification. Unit: the namespace name for a short, a 63-character, and a
      longer change, the hash stable; `make -n` of each build target with and
      without `IMAGE_SUFFIX` and of each Helm target with `CHANGE=`. Chart render
      tests (`make -C helm test-render`, `helm/tests/`): the overlay over every
      rendered image. `uv run --no-project --with pytest pytest -q scripts/tests`;
      `make test`; `make test-deployment-packaging`. No end-to-end scenario covers
      it.
      Evidence: `scripts/tests/test_change_namespace.py`, unit, 21 passed: a short
      name, one of exactly 63 characters kept whole, a longer one cut to 63 and
      ending in the full name's hash, stable, two sharing a 60-character prefix
      apart, a cut ending in a hyphen not doubled, seven names refused; the tags of
      a sample values file's `arkhai` images by path — comments and quotes
      dropped, a third-party image's tag and a block scalar's lines left out — a
      tag in a list refused (as a field and opening an item), the overlay holding
      the suffixed tags alone, the overlay written as JSON, and the command
      printing, writing, and refusing. Which of the umbrella's images the overlay
      names is the render test's, below.
      `scripts/tests/test_change_build_and_helm_targets.py`, 43 passed: through
      `make -n` (unit, over the real Makefiles), each root image target's tag bare
      and suffixed, each subproject image target's bare build writing the image
      and commit tags and its suffixed build the suffixed tag alone (and the VM
      storefront's `build-no-cache` suffixed), each delegating root target passing
      the suffix, and `build`, `build-dev`, and `build-seller` each writing their
      own images' tags bare without and suffixed with it and passing it, empty or
      set, to each subproject they build (the subprojects' recipes are printed,
      not run, under `make -n`, so their tags are the tests before; `build-e2e-*`
      are not read, and keep bare tags as the lanes do); `print-NAMESPACE` with and without `CHANGE=`, the two
      refusals, and thirteen namespaced targets plus `topology-secrets` naming
      `validate-<change>` and no `--namespace default` or `NAMESPACE=default`.
      Against fake `kubectl`, `helm`, and `cast` on `PATH` (the scripts run for
      real; the fakes stand at the process boundary they wrap): four forwards in
      the change's namespace on the usual ports, then `unforward` leaving none
      alive and no PID file, each fake taking a second to exit once signalled so
      a `stop` that did not wait would leave them alive; two held ports each named
      with kubectl's error and the two that listened stopped; `unforward` failing
      over a process that ignores the signal, keeping it in the PID file;
      `resume` scaling two releases' Deployment and StatefulSet to their
      manifests' 1 and 2 and skipping a Service, and failing over a namespace with
      no release and over one stating no workload; `topology-secrets` creating the
      namespace first only when absent, each Secret rendered and applied in it,
      and the buyer-profile volume looked for and applied there. Not tested: a
      forward that never listens within the wait, and
      a real kubectl's bind error text. `helm/tests/test_image_overlay.py`, chart
      render test, 3 passed (`uv run --no-project --with pytest pytest`, and in
      `make -C helm test-render`): the local release, with the API-credits
      registry enabled, and the bare-metal release each render only suffixed
      `arkhai` images, one per bare tag, and every other image as without the
      overlay; removing `validate-contracts.integrationTests.tag` from
      `helm/values.yaml` failed the first two, then restored. `uv run --no-project
      --with pytest pytest -q scripts/tests`: 1285 passed. `make check-packaging`:
      passed. `make check-change`: only the citations of the scripts sections 7
      and 8 create (`check_parallel_validation.py`, `change_history.py`). `make
      test`, which runs `make test-deployment-packaging` as its last suite: every
      suite passed up to `make -C helm test-render`, which failed the thirteen
      render tests 53 V1 and 64 V1 name (four bare-metal storefront, seven
      storefront, two release topology) and no other; the new overlay tests pass
      there; run again after the fresh-context check's fixes, the same. End to
      end: none — no scenario in `e2e-tests/` exercises the build or Helm
      targets; the Helm scenarios first run in the change's namespace in
      section 6.
      The fresh-context check of the diff found, and this section fixed: a
      suffixed build still wrote a commit tag (D4: never a commit tag); the
      overlay suffixed every `tag` key, a third-party image's included, and would
      have read a block scalar's lines; `unforward` gave up silently over a
      forward that outlived its wait; a unit test sat in `helm/tests/`; and four
      evidence claims went beyond their tests (`unforward`'s wait, several failing
      ports, `default` never named, third-party images unchanged), each now
      tested. Declined: that `MAKEFLAGS` carries a step's `CHANGE` into `make -C
      helm` — the 5.2 note hands it to section 6, and nothing validates this
      round before section 7; and that three comments (the root Makefile's
      `IMAGE_SUFFIX`, `resume`'s, `helm/values.yaml`'s two restated images)
      describe validation's use before section 6 builds it — section 6 lands in
      the same round, which is read and reviewed whole. A second check, after
      those fixes, found and this section fixed: `resume` restored one release
      where D4 resumes a namespace; a stale PID file's error did not say to remove
      it; `helm/Makefile`'s pointer to the script read as `helm/scripts/`; a unit
      test repeated the render test's job; and the composite targets, the
      uncached storefront build, and `topology-secrets`' applies and volume were
      claimed beyond their tests, now tested, as is `resume` over two releases;
      and 10.9 now names the manual access, `CHANGE=`, `IMAGE_SUFFIX`, and the
      namespace `topology-secrets` creates for promotion. Declined: the new
      script's executable bit — this step cannot change a file's mode, and
      setting it in the index alone would leave the worktree differing from the
      commit, which validation refuses; `helm/Makefile` runs it with `bash`.
      After the second fixes, which touched only `helm/Makefile`'s `resume`,
      the forward script's message, and tests: `uv run --no-project --with
      pytest pytest -q scripts/tests` and `make -C helm test-render` again,
      the latter the same thirteen failures.
      Handoff: section 6's `validate_slice.py` passes `CHANGE=<change>` (or
      `CHANGE=` for `default`) on every `make -C helm` call, since a step's own
      `CHANGE` reaches it through `MAKEFLAGS`; it writes the image overlay into the
      attempt's directory with `change_namespace.write_image_overlay` and can
      layer it as `EXTRA_VALUES` the way `deploy-local` layers `local-values.yaml`
      (`helm/Makefile`'s `deploy` takes `$(EXTRA_VALUES)`); and it drops the
      forward and port steps, since its scenarios run in the cluster. The
      validation skill (section 7) still runs `make validate-helm` with no
      `CHANGE`.

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
        merge rule, and teardown at archive cleanup; with them `CHANGE=` on every
        `helm/` target, `IMAGE_SUFFIX` on the build targets, manual access through
        `make -C helm forward` and `resume` (one forwarded namespace per host, a
        held port named), and, in "Release topology"'s `make
        helm-topology-secrets` bullet, that it creates its namespace when absent.
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
