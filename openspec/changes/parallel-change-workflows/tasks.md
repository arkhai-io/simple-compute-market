Sections follow the design's implementation cadence: clones and reading (1–4),
Helm isolation (5–7), history and teardown, CI evidence, grants and commit rules
(8, 8A, 8B), the pilot's evidence and the containerization decision (9), then
closeout (10). Sections 8A and 8B, and the amendments to 8.4, 8.5, 9.1, and the
closeout, were planned after the change returned to design from implementation
and its design was settled again (D14–D21, 78 F2). Within each round, scripts come
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
      has not yet (an injected spawn writes none). Evidence: below
      section 4's round 1 triage note.
      Round 2 triage (96 F1): that conclusion claimed too much, and the comment
      above `_SUPERVISOR` and D6's step 5 are corrected, with no change in
      behaviour, on the owner's word. A rerun after an interruption reads the
      bootstrap as started, unless it reads the clone in the moment between the
      spawn and the supervisor's first act; then it reads `absent` and starts a
      second `make init`. No rerun reaches that moment, since `create` runs its
      Git checks on the clone before reading the bootstrap, so no lock guards it.
      Evidence (checks on the fix commit, from 19fb8f584):
      `uv run --no-project --with pytest pytest -q scripts/tests/test_change_clone.py`
      (unit and real-Git integration, TESTING.md), 37 passed; `make test`,
      passed (run before the comment's final wording, a comment-only edit);
      `make check-packaging`, passed; `make check-comment-hygiene`, passed;
      `make check-change`, only the citations of the scripts sections 8 and 8A
      create (`change_history.py`, `ci_evidence.py`, `test_ci_evidence.py`). A
      fresh-context check of the diff found the comment accurate; it corrected
      the comment's grammar, section 6's note on what the rerun deleted, the
      figure's wording in open question 2, and found this same claim in D6,
      corrected with it.

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

- [x] 6.1 `validate_slice.py helm --change <change>` (and `make validate-helm
      CHANGE=`): build with `IMAGE_SUFFIX=-<change>`; deploy into the change's
      namespace only; scale its workloads to zero when a crashed run left any up;
      delete the release's volume claims and `arkhai-buyer-profiles`, waiting until
      they are gone; run `make -C helm topology-secrets` for the namespace; `helm
      upgrade --install` with the local overlay and 5.4's image overlay, falling
      back to uninstall and install when the upgrade is refused, said in the step's
      detail. The retained-volume check runs only for `default`. The preflight
      checks for `cast` (D4).
      Note: one flow for both namespaces — without `--change` the part runs in
      `default` on bare tags, with no image overlay and the retained-volume
      refusal first; with it, in `change_namespace.namespace(change)`. `make
      validate-helm` passes `--change "$(CHANGE)"` whenever `CHANGE` is set, so a
      validation started as `make validate CHANGE=<change>` runs in the change's
      namespace through `MAKEFLAGS` even before the skill names it (section 7).
      Every `make -C helm` call names its namespace — `CHANGE=<change>`, beside
      which `helm/Makefile` refuses an inherited `NAMESPACE`, or `CHANGE=
      NAMESPACE=default` — so neither a step's `CHANGE` nor a `NAMESPACE` in
      `MAKEFLAGS` can redirect it, and the release and its test volumes are read
      from `helm/Makefile` (`RELEASE`, `TEST_VOLUMES`). Every workload, pod,
      resource, and memory read of the namespace is scoped to the release
      (`app.kubernetes.io/instance=<RELEASE>`), so a `default` run leaves an
      owner's other release there, such as the bare-metal seller's, alone; after
      a `default` run the owner's release keeps `scenarios.markers`, so its next
      `helm test` also runs the scenario pod. The preflight no longer runs `check-local-secrets`, since
      `topology-secrets` creates the Secrets (and in `default` replaces them with
      the same development values). The release is replaced as: workloads read
      and any above zero scaled to zero by name (`kubectl scale --replicas=0
      <kind/name>…`, the step's detail naming them), the release's pods deleted
      (its test pods outlive their runs and mount the buyer-profile volume, and a
      claim is deleted only once no pod uses it), the release's labelled claims
      and the test volumes deleted (`--wait=false`), both waited for, then
      `topology-secrets`, then `make -C helm deploy` with `EXTRA_VALUES` naming
      `local-values.yaml`, the change's `images.json`, and `scenarios.json` (both
      written into the attempt's directory; a path with a space would split). An
      upgrade the chart refuses is told from one that failed by its log (`field is
      immutable`): the deploy step becomes a warning naming the line, then
      `undeploy`, the release's own volumes waited for again (the test volume
      `topology-secrets` has just recreated empty stays), and `install`. Since a
      Helm release under server-side apply may not restore a count scaled
      outside it, `make -C helm resume RESUME_RELEASES=<RELEASE>` follows every
      deploy (`resume` gained `RESUME_RELEASES`, limiting it to the releases
      named, so a `default` run never brings an owner's other release up), then
      each workload's `kubectl rollout status` (a scaled-up Deployment's
      `Available` condition can still be true from before). Port-forwards, the
      port probes, and their steps are gone from the part.
- [x] 6.2 Scenarios as a pod in the namespace from the change's `e2e-tests` image,
      with the release's `test-config` ConfigMap's `helm` profile as the
      `e2e-deal-test` pod has it, selecting `HELM_SCENARIOS`; its log and exit
      status collected into the attempt's directory. No port-forward and no
      localhost port is used (D4).
      Note: a Helm test hook in the e2e-tests chart,
      `templates/tests/e2e-scenarios-test.yaml` (`<release>-e2e-tests-e2e-scenarios`),
      rendered only when the new `scenarios.markers` value (schema: a string) is
      set; its environment, mounts, and volumes are the deal test's, copied rather
      than shared so the deal test's render is untouched, and a render test holds
      them equal. Validation sets the markers through `scenarios.json`, runs `helm
      test <release> --filter name=<pod> --timeout 30m`, then keeps `kubectl logs`
      of the pod as `scenarios.log` and its container's exit code as
      `scenarios.exit` and in `summary.json`'s `evidence.scenarios`; the step
      passes only on the pod's own exit status of 0, since `helm test` passes when
      its filter matches no test, so a non-zero or unreadable status fails it even
      when `helm test` passed; a pod with no exit status, as after `helm test`
      timed out, is deleted, since scaling the workloads down would not stop it.
      Every read is bounded (120 s), so no hung read holds the scale-down. Whether
      `contracts` and `e2e_alkahest_escrow_codecs` pass with the `helm` profile in
      the cluster is the cluster run's to show (6.5).
- [x] 6.3 After the scenarios, always: the namespace's peak memory in
      `summary.json`, every pod's log and the namespace's events copied into the
      attempt's directory, the other namespaces' replica counts and the rendered
      requests and limits beside the previous validation's, then the namespace's
      workloads scaled to zero, objects and volumes kept (D4, 26 F2).
      Note: it runs in a `finally` once the namespace's release has been touched,
      whether the deploy or the scenarios passed; while the checkout is no longer
      the commit it keeps no evidence and only scales down, and an unexpected
      error keeping evidence is a warning that still lets it scale down. "Peak"
      is the largest of the release's sampled usage, summed over its containers
      from `metrics.k8s.io` (each read bounded by `--request-timeout=10s`),
      sampled only once the release came up: when it is ready, every 15 s while the
      scenarios run (a thread around the `helm test` step), and after them
      (`summary.json`'s `memory.peak_bytes` and `samples_bytes`), which section 8.4
      writes as the figure. The evidence is `pods/<pod>.log`, a restarted
      container's `pods/<pod>.previous.log`, `pods.json` (each pod's status, where
      a container killed at its own limit shows `OOMKilled`), `events.log`,
      `node-events.log` (the nodes' events from every namespace, where a node out
      of memory is recorded), `evidence.other_namespaces` and
      `other_namespaces_at_start` (each other namespace's workloads of the release
      with their replicas, at the end and at the preflight, bracketing the run
      rather than catching the moment of a failure), and `resources.txt` (each
      workload's containers' rendered `resources`), compared with the latest
      earlier validation's in the same namespace (`evidence.resources.previous`,
      `changed`). A read or an evidence command that fails is a warning, not a
      failure, and its evidence key is then empty.
- [x] 6.4 The capacity preflight (D4, 17 F3): `helm/validation-capacity.toml` holds
      the memory one release needs, when, and from which change it was measured,
      with a reader and writer in `validate_slice.py`; the preflight counts the
      namespaces with workloads above zero replicas, adds its own, and compares that
      many times the figure with the node's allocatable memory, a deployment that
      would not fit failing the part as environmental with its remedy; it warns and
      goes on with no figure, and when `metrics-server` is missing. It reserves
      nothing. The file starts with no figure.
      Note: `read_capacity` and `write_capacity` (a `[release]` table of
      `memory_bytes`, `measured_at`, `change`, under a header saying what the
      figure is and that a merge conflict keeps the later `measured_at`); a figure
      missing a field or not positive is refused when read, and one not positive
      when written, so a figure no preflight could read is never recorded. A
      failed read of the other namespaces with no figure is part of the warning.
      The namespaces counted are those
      other than the run's own with a workload of the validation release
      (`app.kubernetes.io/instance=<RELEASE>`) above zero replicas, so system
      namespaces are not; allocatable memory is summed over nodes, read with
      `memory_bytes`, a Kubernetes quantity parser. The failure's detail begins
      `environmental:`, names the running namespaces, and gives the remedy;
      section 7.1 teaches the skill to read it. `metrics-server` is detected by
      `kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes`. Both checks run
      before anything is built.
- [x] 6.5 Verification. Unit, with the injected runner and reader: each step's
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
      Evidence so far: `scripts/tests/test_validate_slice.py`, the script's
      orchestration against a fake at the subprocess boundary — the plan's
      "unit", though TESTING.md would call orchestration mocked at its external
      boundary integration — with the runner and reader injected (a fake
      checkout, daemon, and cluster recording every command and read, its workload
      and resource reads and its `resume` honouring the release selector; the
      out-of-band test volume deleted, optionally still listed for a look, and
      recreated by `topology-secrets`), 76 passed: for a change, every command in
      order — the
      suffixed build, the render checks with `CHANGE=`, the release's pods, both
      volume deletions, `topology-secrets`, the deploy naming the three values
      files, `resume`, each rollout, `helm test` of the scenario pod, its log,
      every pod's log, the pod statuses, the namespace's and the nodes' events,
      and the scale to zero by name; the overlay's storefront and e2e-tests tags
      and scenario markers; every `kubectl` and `helm` command run naming the
      change's namespace but the one read of the nodes' events, every `kubectl`
      read naming it too or reading the nodes, the metrics source, or the
      release's workloads across namespaces, every metrics read of pods naming
      it, every `make -C helm` call and setting read naming the change, and
      another namespace's workload untouched; `default` on bare tags with no image
      overlay, every `make -C helm` call naming `CHANGE= NAMESPACE=default`, and
      an owner's other release there, at zero or up, neither scaled, resumed
      (`resume` names the release alone), nor listed in the resources; a crashed
      run's workload scaled down, named, before the
      volumes are deleted, and none when nothing is up; the pods deleted before
      the volumes, the deploy waiting for the release's volumes and for a test
      volume still listed at the first look, and stopping when a volume outlives
      the wait; a refused upgrade (its log naming an immutable selector) becoming
      a warning naming the line, then `undeploy`, the release's volumes alone
      waited for again (the recreated test volume left), `install`, and `resume`;
      a deploy failing otherwise not falling back, yet the evidence kept and the
      workload it left up scaled down; the scenario pod's log (its contents) and
      exit status in `scenarios.log`, `scenarios.exit`, and the written
      `summary.json`; a pod with no exit status deleted; a failing scenario run,
      a pod exiting non-zero, and a passed `helm test` whose pod has no exit
      status each failing the step, the evidence kept and the release scaled to
      zero for the first two; an evidence command that fails, the scenario log
      among them, warned and its key empty; a failed read of the rendered
      resources leaving the other evidence kept; an unexpected error keeping evidence warned and the release still
      scaled down and the summary written; no memory sampled when the deploy
      failed; a passing run's pod logs and statuses, both events
      files, the other namespaces' workloads at the start and the end, the
      resources, and the larger of two different memory samples as the peak in
      `summary.json`; memory sampled while the scenario run blocks until the
      sampler has sampled twice, the peak taken from those samples; a restarted
      container's previous log kept; the resources compared with the latest of two
      earlier validations in the same namespace and not another namespace's, and
      found unchanged when equal; a commit made after `resume` keeping no
      evidence and running no scenarios yet still scaling down, and one made
      during the build touching no cluster; the preflight stopping before any
      command without `cast`, Docker, or a Ready node, warning with no figure (no
      allocatable read) and without a metrics source (no memory recorded),
      passing when two releases fit and failing as environmental, naming the
      running namespaces and the remedy, when three would not; the retained-volume
      refusal in `default` alone; the capacity file written and read back, the
      tracked one holding no figure, three malformed ones refused, two figures
      not positive not written, and seven memory quantities; the command line
      refusing a name that is not a change. Not shown: the `MAKEFLAGS` route is
      shown by `helm/Makefile`'s own tests (section 5) and the runs' arguments,
      not by a real `make`; the sampler's period is a real timer, which the test
      outwaits through a condition rather than a sleep.
      `helm/tests/test_scenario_pod.py`, chart render test, 4 passed in `make -C
      helm test-render`: no scenario pod without markers, the pod a test hook
      running `pytest -m "<markers>"`, its environment, mounts, volumes, and image
      the deal test's, and a non-string or unknown `scenarios` key refused by the
      schema. `uv run --no-project --with pytest pytest -q scripts/tests`: 1321
      passed after the second check's fixes. `make check-packaging`: passed. `make check-change`: only the
      citations of the scripts sections 7 and 8 create. `make test`: every suite
      passed up to `make -C helm test-render`, which failed the same thirteen
      render tests as in section 5 and no other; the new render tests pass there.
      The fresh-context check of the diff found, and this section fixed: the
      refused upgrade's fallback waited for the test volume `topology-secrets`
      had just recreated, so it could never install; the release's test pods,
      which outlive their runs and mount that volume, were not deleted before it;
      a `NAMESPACE` inherited through `MAKEFLAGS` could redirect a `default` run's
      `make -C helm` calls; the evidence lacked pod statuses, previous logs, and
      the nodes' events, which a memory failure is read from; memory was sampled
      only at rest; `cannot patch` matched failures that are not refusals; a
      scenario pod still running was left up; two comments named archive cleanup,
      which writes nothing yet; and six evidence claims went beyond their tests
      (now as above), and the `scenarios` schema had no refusal test. Declined:
      passing `--context` on every `kubectl` and `helm` call, which the part
      never did and which concerns any change in the context mid-run rather than
      this section; and that `resume` would bring up a second release a person
      installed in the change's namespace on its kept volumes, and the
      preflight would count that namespace once — validation installs only the
      one release there. A second check, after those fixes, found and this
      section fixed: a `default` run scaled, resumed, and waited on every workload
      in the namespace, an owner's other release included (now scoped to the
      release); evidence commands that failed were silent; the preflight dropped
      a failed read when no figure was recorded; memory was sampled after a
      release that never came up, which could record a figure of zero, and the
      writer accepted one; an unexpected exception keeping evidence skipped the
      scale-down; metrics reads had no timeout; and three evidence claims went
      beyond their tests (reads not checked for their namespace, the exit-5 run's
      evidence, and failed evidence commands), now tested. Declined: the
      sampler's real period, since production needs a timer and the test waits on
      a condition; the scenario test's place under `helm/tests/`, since it needs
      the umbrella's `test-config` and local values. A third check found, and
      this section fixed: `resume` in a `default` run brought up every release
      there (now `RESUME_RELEASES`, with section 5's target test of it); a
      passed `helm test` with no readable exit status passed the step, though it
      passes when no test pod matched; one failed read lost two pieces of
      evidence; the scenario log failed silently; reads were unbounded, so a hung
      one could hold the scale-down; and the claims that the fake's reads honour
      the selector and that the other release is not resumed went beyond their
      tests, now narrowed or tested. Declined: that a `default` run's
      `topology-secrets` rewrites the bare-metal release's Secrets — they are
      the same development values that target always writes there, and
      DEPLOYMENT_AND_CONFIG's "Release topology" says it creates or replaces
      them. After those fixes: `uv run --no-project --with pytest pytest -q
      scripts/tests`, 1326 passed; `make -C helm test-render`, the same thirteen
      failures; `make test`, every suite passed up to that one, as before;
      `make check-packaging`, passed; `make check-change`, only the citations of
      the scripts sections 7 and 8 create.
      Not run: the `make validate-helm CHANGE=parallel-change-workflows` on the
      development cluster, and so the end-to-end scenarios in the namespace. This
      step may run no `docker`, `kubectl`, `helm`, or `make validate-*`, and the
      Helm part stops at `make -C helm test-render` until the unowned render fix
      named at the head of this section is merged in from `dev`. The task stays
      unchecked until that run is recorded here; the unit tests do not show that
      a real Helm release restores the counts, that the cluster recreates the
      deleted claims, or that the two scenarios pass from the `helm` profile.
      Correction, on the owner's word: once the render fix was merged in from
      `dev` (8e6494f51), this step ran the cluster run itself.
      System, on the development cluster (`docker-desktop`), `make validate-helm
      CHANGE=parallel-change-workflows` at 8e6494f51, attempt 1, passed
      (`.snapshot/validation/8e6494f519ac/helm/1/`): namespace
      `validate-parallel-change-workflows`; images built and deployed as
      `arkhai:{dev-env,registry,storefront,compute-provisioning,e2e-tests}-parallel-change-workflows`,
      each pod's image so in `pods.json`; test-render passed with no skip; the
      release's pods, claims, and `arkhai-buyer-profiles` deleted and gone, the
      namespace's Secrets created, the deploy (`helm upgrade --install`, 25.7 s,
      no refusal), `resume`, and all four rollouts passed, the rollouts at once,
      so the upgrade's `--wait` had already brought the pods up; the scenario pod
      `arkhai-node-operator-e2e-tests-e2e-scenarios` ran with the `helm` and
      `e2e-secret` profiles, reaching the chain at
      `http://arkhai-node-operator-dev-env:8545` by its in-cluster name, and
      passed `contracts`' one test and `e2e_alkahest_escrow_codecs`' twelve (13
      passed, 239 deselected; exit 0); the evidence was kept and the four
      Deployments scaled to zero. The owner's own release in `default` was up
      throughout (`other_namespaces_at_start` and `other_namespaces`, four
      Deployments at one replica each) and untouched. Both preflight warnings
      fired as designed: no metrics source is installed on this cluster, so
      `summary.json`'s `memory` is empty, and no figure is recorded. Not shown
      by this run: an upgrade over a namespace scaled down by an earlier run
      (this was the namespace's first install), the refused-upgrade fallback,
      and a memory sample; section 8.4's figure needs a cluster with
      `metrics-server`. End to end: `contracts` and `e2e_alkahest_escrow_codecs`,
      run in the change's namespace by this validation.
      Handoff: section 7.1's skill still describes the forwarded run (its steps,
      "the port-forwards stopped and their ports free", the retained-volume
      refusal for every run); it should read the capacity step's `environmental:`
      detail, the `metrics` and `capacity` warnings, `pods.json`'s
      `OOMKilled`, `node-events.log`, and `evidence.resources.changed` when it
      classifies a memory failure, and `evidence.scenarios` for the scenario
      run. 7.2's two-validation check can read each clone's `summary.json`
      (`namespace`, `evidence`) and `images.json`. Section 8.4 writes the figure
      from `summary.json`'s `memory.peak_bytes` through `write_capacity`, and
      its `CapacityFigure`. The permanent `change-workflow` spec's "Validation
      observes a committed slice" still gives "port-forwards" as what validation
      may stop, and its architecture's "Validation observes a committed slice"
      describes the forwarded release in `default`; the delta modifies neither,
      so closeout (10.9) must rewrite the architecture section, as it plans, and
      the requirement's example needs a MODIFIED delta or the example left as a
      true one (validation still stops the scenario pod it started).
      Round 2 triage (96 F2): validation 97 at 19fb8f584 showed what this run
      did not, an upgrade over a namespace scaled down by an earlier run: in
      `validate-parallel-change-workflows`, left at zero by this run, this run's
      scenario pod, the release's three claims, and `arkhai-buyer-profiles` were
      deleted and gone, the deploy upgraded the release to revision 2
      (`deploy.log`), every pod was created anew, each main container on its
      `-parallel-change-workflows` image (`pods.json`), the four rollouts and
      the scenario pod's 13 tests passed, and the Deployments were scaled to zero
      again (`.snapshot/validation/19fb8f5848ec/helm/1/`). The refused-upgrade
      fallback is still unexercised: no refusal has occurred on a real cluster.

## 7. Validation's skill and two validations side by side

Delivers D4's classification of a memory failure and D9's scripted check of two
concurrent validations. Touches `.agents/skills/change-validate/`, a new
`scripts/validate_parallel.py` (planned as `check_parallel_validation.py`; renamed
in 7.2), and `scripts/tests/`.

- [x] 7.1 `change-validate`: the Helm part runs for its change (`CHANGE=`); a pod
      that could not be scheduled or was evicted while another change's namespace
      had workloads up and the node's allocatable memory was exhausted is
      environmental, its remedy scaling that namespace to zero or rerunning once it
      is down; a container killed at its own limit, or a commit that changed the
      rendered requests or limits, is the commit's; anything else is of unknown
      cause, so `failed` and triaged; the preflight's warnings are reported as such
      (D4, 26 F2).
      Note: the skill now runs `make validate-helm CHANGE=<change>` and describes
      section 6's part as it is — `cast` and the capacity preflight with its
      `metrics` and `capacity` warnings, the release replaced from zero, the
      scenario pod, the evidence kept and the scale to zero, the retained-volume
      refusal only without `CHANGE` — in place of the forwarded release in
      `default`. Its opening says validation controls its change's namespace and
      tags and never another change's, and drops "one change is validated at a
      time". Step 3 lists what a Helm attempt keeps (`scenarios.log`,
      `scenarios.exit`, `pods/`, `pods.json`, `events.log`, `node-events.log`,
      `evidence.other_namespaces_at_start` and `other_namespaces`, `resources.txt`
      with `evidence.resources.changed`, `memory.peak_bytes`); step 4 gains "The
      Helm part's memory", the three classes read from those files, and the
      capacity step's `environmental:` detail as an environmental failure; step
      5's remedy examples name scaling another change's namespace; the record's
      `## Helm` gains a line for the namespace, the scenario pod, peak memory, and
      the warnings.
- [x] 7.2 `scripts/validate_parallel.py <clone> <clone>` (`make
      validate-parallel`; planned as `check_parallel_validation.py` and `make
      check-parallel-validation`): runs both clones' Helm parts at the same moment on
      the development cluster and reports, from their summaries and the cluster,
      separate namespaces, tags, and scenario pods, and that neither's release,
      volumes, or pods were touched by the other (D9).
      Note: renamed because it deploys. Design, planning, triage, implementation,
      closeout, and archive cleanup are each allowed `make check-*`, and closeout
      `python3 scripts/check_*`, so the planned names would have let any of them
      deploy two releases; `make validate-*` is already implementation's,
      triage's, and validation's, and no step's rule names `python3
      scripts/validate_*`. Recorded in D9. The target is `make validate-parallel
      CLONES="<clone> <clone>" [HELM_CONTEXT=…]`. A clone is one `make
      change-clone` made — its `workspace` remote names the workspace,
      `change_clone.clone_of` returns it for its directory's name, and its
      bootstrap has `succeeded` — and the two must be of different changes. Both
      `make -C <clone> validate-helm CHANGE=<change>` runs start before either is
      waited for, with `MAKEFLAGS`, `CHANGE`, and the other variables `make` hands
      down removed from their environment; each run's end is taken by its own
      thread. Then six checks, each failing alone on a read it cannot make:
      `together` (the runs overlapped, and whether the scenario pods' run times
      did, from their terminated state); `results` (each part passed, else its
      failed steps or its log's end); `namespaces` (each summary's is the one its
      change derives, and they differ); `tags` (the attempts' `images.json`
      overlays share no tag, and every `arkhai` image in each attempt's
      `pods.json` is one of its own overlay's tags); `scenario pods` (each, read
      from the cluster, is in its own namespace, on its own image, exit 0);
      `untouched` (in each namespace after both ended: exactly one Helm revision
      since the check started, every volume and pod created within its own run's
      window, no pod on another overlay's image, every claim its kept pods
      mounted still present, and its workloads at zero; a namespace whose own
      Helm part did not pass is not judged, and fails the check). Every cluster
      read names `HELM_CONTEXT` (`kubectl --context`, `helm --kube-context`). It
      reads the cluster only after both runs, and the runs overlap almost
      entirely, so the creation times separate nothing between them: a
      disturbance shows only by what it left — a second revision, a pod on the
      other's images, a missing claim, a workload up again — and one that left
      nothing, such as an uninstall and install by the other run or a pod its
      ReplicaSet recreated, is not shown; that each run's own commands name only
      its namespace is `test_validate_slice.py`'s. A run that cannot be launched
      is reported beside the other, which is still waited for.
      Output: `<change>.log` for each run and `report.json` under
      `.snapshot/parallel-validation/<UTC time>/` in the invoking checkout; exit 0
      when every check passed, 1 otherwise, 2 on a refusal.
- [x] 7.3 Verification. Unit: 7.2's report over fake summaries and cluster reads,
      including a run that touched the other's namespace. System: one run of `make
      validate-parallel` (planned as `check-parallel-validation`, renamed in 7.2)
      over two clones on the development cluster,
      recorded here. A fresh-context read of `change-validate` against D4 and the
      delta's Helm requirement. `make check-agent-skills`; `make test`. End to end:
      the Helm scenarios of 6.5, in both namespaces at once.
      Evidence so far: `scripts/tests/test_validate_parallel.py`, 45 passed.
      Integration as `TESTING.md` defines it for orchestration — the check's run
      with the launcher and the cluster reader injected at the process boundary,
      and the clock and the clone lookup injected as controls (a fake leaving each run's log,
      `summary.json`, `images.json`, and `pods.json` in its clone, and answering
      the cluster's reads per namespace, refusing a `kubectl` read without
      `--context docker-desktop` or a `helm` one without `--kube-context`): two
      isolated runs passing all six checks, with the `together`, `results`,
      `namespaces`, `tags`, and `scenario pods` details asserted whole and
      `untouched` naming one revision in each; every cluster read naming the
      context; both runs launched before either is waited for, each with its
      command and directory; each run's end taken as it ends (the first run's
      wait returns only once the second's end was taken, and the second's end
      is the earlier); a run that cannot be launched reported beside the other,
      which was waited for and judged, its own namespace not judged; the report
      and both logs kept together; scenario pods that ran apart said to; a
      namespace holding of its release what its own run did not leave, six ways,
      each failing `untouched` alone, naming that namespace, while the other
      namespace reports one revision — four the other run's touch (the release
      upgraded a second time, a pod on the other's images, a mounted volume
      deleted, a workload up again) and two leftovers (a pod made after its run, a
      volume made before the check); another release's pod, volume, and running
      workload in the namespace, made before the check, not judged; one
      namespace's history unreadable, not a list, or its release unreadable, each
      failing `untouched` alone, naming it, while the other namespace reports;
      kept pod statuses that are not JSON or hold an item that is not a pod
      failing `tags` and `untouched` alone, and a container with no image name
      failing `tags` alone; a summary that is not a mapping read as none; overlays
      sharing a tag, a pod on a tag outside its overlay, and no kept pod
      statuses each failing `tags`; a run in another namespace; a failed part
      named with its failed steps, and one that wrote no summary with its log's
      end; a scenario pod exiting 1, one that cannot be read, one with no status,
      and one on the other's image. Unit: the constructor's three refusals (one
      clone, one change twice, a name that is not a change's) and the command
      line's exit 2, for one clone and for clones that do not exist; three
      timestamp forms and a refusal. Integration against
      the real boundary: a run's environment carrying no `MAKEFLAGS` or `CHANGE`
      (a real subprocess), and the target's command (`make -n`). Library
      integration over real Git (a workspace with a bare `origin`, clones made by
      `change_clone.create` with the bootstrap's spawn injected), the level
      sections 1–3 call repository level: a clone whose bootstrap succeeded is of
      its change; one whose bootstrap failed, one with another branch checked
      out, and the workspace itself are refused.
      `scripts/tests/test_validate_slice.py` (the capacity remedy's new wording,
      below). `uv run --no-project --with
      pytest pytest -q scripts/tests`: 1376 passed after both diff checks' fixes.
      `make check-agent-skills` and `make check-comment-hygiene`: passed. `make
      test`, after `make dist-clean` and `make dist`, and before the capacity
      remedy's wording in `validate_slice.py` and both diff checks' fixes, which
      touched only scripts and their tests (covered by the script suite above),
      the Makefile target, the skill, and documents: every suite passed, `make -C helm test-render` included
      (Helm v4.3.0, no skip). Its first run had failed the VM storefront's two
      values-schema drift tests and rewritten `domains/vms/storefront/uv.lock` to
      `arkhai-kit-arkhai-payments` 0.3.0, a wheel another branch had left in
      `.dist` (this branch builds 0.2.0): environmental, the lock put back as
      committed by hand and the wheelhouse rebuilt from this commit. `make
      check-packaging`: passed, before and after the diff check's fixes. `make
      check-change`: only the citations of the scripts sections 8 and 8A create
      (`change_history.py`, `ci_evidence.py`, `test_ci_evidence.py`).
      The fresh-context read of `change-validate` against D4, D7, and the delta's
      Helm requirement found no instruction that touches another change's
      namespace without the owner's word, and found, all fixed: the namespace
      said to be printed first (it is in the summary, and a long name is cut and
      hashed); the evidence said to be kept always (only once the release has
      been touched); the skill's remedy (`deployment,statefulset --all`) and the
      script's (`deployment --all`) disagreeing — the script's would leave a
      StatefulSet up and, in `default`, scale an owner's other releases, so
      `validate_slice.py`'s capacity remedy now names the release's selector,
      `deployments,statefulsets --selector app.kubernetes.io/instance=<release>`,
      as the skill's does; only the preflight's warnings covered (now every
      warning step, `deploy`, `memory`, `evidence`, and `scenario pod` included,
      each with its meaning) and a `capacity` failure without `environmental:`
      unaddressed; in the classification, node exhaustion read from
      `node-events.log` where `FailedScheduling` is a pod event, `OOMKilled` taken
      as proof of a container's own limit (now also its limit in `resources.txt`
      and no node memory pressure or system kill, else unknown), no order where
      contention and changed resources meet, and the owner's release in
      `default` counting as another change's; and two stale lines — the Helm
      part run in the foreground (it can outlast one call, so it now runs in the
      background and is waited for on its result line or `ERROR:` line) and the
      retained volume in `default` as a remedy example the skill no longer
      reaches. Correction: the order was first written as changed resources
      before contention; the diff's fresh-context check found that contradicts
      the delta scenario "Two validations pass the preflight together", so a pod
      unscheduled or evicted for memory while another change's release is up is
      environmental whatever the resources, a resource change is named beside
      the remedy, and the rerun with nothing else running tells contention from
      the commit's own demand. That orders contention before a resource change,
      the order the delta scenario requires; D4 states none.
      The fresh-context check of the diff found, and this section fixed: the
      script's planned `check_*` name, which closeout's `python3 scripts/check_*`
      allows, kept open the deployment the target's rename closed (now
      `validate_parallel.py`, recorded in D9); the Makefile comment's reason (the
      `check-*` steps "only read") false; the window comment claiming Helm
      records whole seconds; three reads failing silently (the release, the
      overlay, and the kept pod statuses, the last leaving the missing-claim test
      vacuous), now each failing the check that needs it, naming the read; a
      launch that raised, a wait that raised, a summary that is not a mapping, a
      step with no name, and a pod with no status, each of which would have
      ended the report with a traceback; a namespace whose own part did not pass
      reported as disturbed (now not judged); the check's own cluster reads not
      naming `HELM_CONTEXT`, nor dropping the inherited `MAKEFLAGS`; the help
      text claiming more than the check shows; a second container in the
      fixture's scenario pod, which the chart's has not; and evidence claims —
      orchestration with fakes at the process boundary called unit (now
      integration, as section 6 named it), "each check's detail" and "the other
      checks passing" beyond their assertions (now asserted), an "unreadable
      namespace" test that made both unreadable (now one, the other shown
      reporting), "refusals before anything is launched" where no launch could
      happen (now the constructor's refusals), and "each run's end taken by its
      own thread" untested (now tested). Declined: a `round-view-closed`
      prerequisite on `make validate-parallel` — each clone's own `make
      validate-helm` refuses an open view in its clone, and the check moves
      nothing in the checkout it runs from; tolerance for clock skew between the
      host and the API server — objects are made minutes into a run, and a skew
      that large would show as a failure to read, not a pass.
      A second check of the diff, after those fixes, found and this section
      fixed: malformed kept pod statuses (an item that is not a pod, an image
      that is not a name, evidence that is not a mapping) still able to end the
      report from `tags`; a clone path that does not exist ending the command
      line with a traceback rather than exit 2; `untouched` judging every pod,
      volume, and workload in the namespace where the Helm part replaces only
      the release's labelled ones and the test volume — another release there
      would have failed a correct run, so it now judges the release's labelled
      objects and the claims its pods mounted; the docstring not naming an
      uninstall and install by the other run as unseen; the eviction class
      requiring node events that may have expired (now confirming, not
      required) and not saying the other namespaces' replicas are read at the
      preflight and the end rather than at the failure; and evidence wording —
      the clone lookup said to be injected at the process boundary, two of the
      six disturbance cases leftovers rather than the other run's touch, the
      order "with no new order", and when `make test` ran. Left for the owner,
      below: that `make validate-*`, which implementation and triage hold, now
      also reaches `make validate-parallel`, which scales and deletes in two
      changes' namespaces, neither of them necessarily the step's own.
      The bootstrap in a fresh clone (on the owner's word, after this section's
      commit): the owner chose the pilot and `resolve-compute-family-findings`
      for the system run, and the orchestrating session made both clones from
      this branch. Both bootstraps failed at `init-buyer`: uv found no
      `arkhai-core` 0.4.1 for `arkhai-kit-contact-exchange`, because the clone's
      `.dist` held only what `init-buyer`'s prerequisite, `dist-domains`, builds
      (`uv build` resolves nothing, so the kit wheels built without
      `arkhai-core`), while the workspace's `.dist` held every wheel earlier
      builds had left; `init-arkhai-core-registry` lacked `arkhai-core` and
      `arkhai-kit-identity` the same way. Changed in the root `Makefile`:
      `init-buyer`, `init-storefront`, and `init-arkhai-core-registry` each build
      the whole repository wheelhouse (`dist-ci`) first, in place of a hand-kept
      subset. `scripts/tests/test_init_targets.py`, integration through `make
      -n` over the real Makefiles (the tracked projects only, `.dist` a
      temporary directory): each of the three prints a wheel build for every
      package its project's lock installs from `.dist`, 3 passed; with
      `init-buyer` put back on `dist-domains` it failed naming `arkhai-core`,
      `arkhai-core-buyer`, `arkhai-core-registry-client`, `arkhai-kit-alkahest`,
      `arkhai-kit-config`, `arkhai-kit-identity`, and `arkhai-kit-policy`, and
      with `init-arkhai-core-registry` on `dist-registry-client`, naming
      `arkhai-core` and `arkhai-kit-identity`. That shows the wheels are built,
      not that a fresh clone's `make init` now succeeds: the clones' bootstraps
      are rerun only once they hold this fix (below). `uv run --no-project
      --with pytest pytest -q scripts/tests`: 1379 passed. `make
      check-packaging`: passed. A fresh-context check of the fix found it
      complete for the three locks and no caller broken; fixed from it: the
      test now lists tracked projects, reads the lock as TOML, and runs make in
      the C locale without `GNUMAKEFLAGS`; the Makefile's `init` comment no
      longer says wheels are built separately; and this note's wording.
      On the owner's word the orchestrating session fast-forwarded both clones
      to 297c64fa1 and reran their bootstraps, which succeeded (exit 0).
      System, attempt 1 of `make validate-parallel` over the two clones
      (`.snapshot/parallel-validation/20261022T070836Z/`): both Helm parts
      started together, in `validate-seed-default-pool-at-runtime` and
      `validate-resolve-compute-family-findings`, and both failed at
      `test-render` before touching any release, on the render check's `skip:
      BARE_METAL_STOREFRONT_PYTHON unset; the storefront loader check did not
      run`, which validation fails by design. The check reported it as it
      should: `together` and `namespaces` passed, `results` failed naming
      `test-render` in each, `tags` and `scenario pods` failed on the missing
      overlays, and `untouched` judged neither namespace. Cause: `make init`
      never created the bare-metal storefront's environment, which the
      bare-metal chart's and the release topology's loader checks run in, and
      validation neither checked for it nor reinstalled it; the workspace had
      one from earlier `make test` runs. Fixed: `make init` gains
      `init-bare-metal-storefront` (the wheelhouse, then that project's `make
      init`); `validate_slice.py`'s preflight checks both loader environments,
      each naming the `make` target that creates it, and reinstalls both from
      the commit's wheels before the render checks; `change-validate` says so.
      `scripts/tests/test_init_targets.py`, 5 passed: the new target builds
      every wheel its lock installs, and `make -n init` reaches both
      storefronts' `make init` (failing with the target taken out of `init`);
      `scripts/tests/test_validate_slice.py`, 77 passed: the second reinstall in
      the Helm part's command order, and each missing environment refused
      before any command, naming its target. `uv run --no-project --with pytest
      pytest -q scripts/tests`: 1382 passed. `make check-packaging`: passed. A
      fresh-context check of this fix found the environment's `make
      init`/`reinit` the right way to create and refresh it and no other
      environment the render checks need; fixed from it: two Makefile comments,
      `init`'s own dependency on the target untested, an unused constant, and
      this note. `helm/scripts/test-render.sh`'s and `TESTING.md`'s pointers to
      `make -C domains/bare_metal/storefront init`, which in a fresh checkout
      needs the wheelhouse first, are left: the first is a comment of a script
      this section does not otherwise touch, and the second is closeout's
      promotion (10.9).
      On the owner's word the orchestrating session fast-forwarded both clones
      to b1c1e044d and ran `make init-bare-metal-storefront` in each (exit 0).
      System, on the development cluster (`docker-desktop`), attempt 2 of `make
      validate-parallel` over the two clones, both at b1c1e044d, passed every
      check (`.snapshot/parallel-validation/20261022T072048Z/`, exit 0):
      `together` — both runs 07:20:48 to 07:22:58 and 07:22:59 UTC, their
      scenario pods running together; `results` — each Helm part passed,
      attempt 1 under `.snapshot/validation/b1c1e044d142/helm/1/` in its clone;
      `namespaces` — `validate-seed-default-pool-at-runtime` and
      `validate-resolve-compute-family-findings`; `tags` — each run's pods on
      its own five images, `arkhai:{compute-provisioning,dev-env,e2e-tests,
      registry,storefront}-<change>`, the overlays sharing none; `scenario
      pods` — `arkhai-node-operator-e2e-tests-e2e-scenarios` in each namespace,
      on its own `e2e-tests` image, exit 0, each passing `contracts`' and
      `e2e_alkahest_escrow_codecs`' 13 tests (239 deselected); `untouched` —
      in each namespace one revision of `arkhai-node-operator` since the check
      started, its volumes and pods made during its own run on its own images,
      its workloads at zero. Each namespace's deploy was a first install (attempt
      1 never reached one), so the upgrade over a namespace left at zero and the
      refused-upgrade fallback were again not exercised; the only warnings were
      `metrics` (no metrics source on this cluster, so no memory recorded) and
      `capacity` (no figure recorded). The check takes two clones, so this
      change, worked in the owner's workspace, is not one of them.
      End to end: `contracts` and `e2e_alkahest_escrow_codecs`, run in both
      namespaces at once by this run.
      End-to-end scenarios: `contracts` and `e2e_alkahest_escrow_codecs`, the Helm
      run's served list, in both namespaces at once — by the system run alone; no
      pipeline scenario exercises the check or the skill.
      Handoff: the `MAKEFLAGS` route means a validation started as `make validate
      CHANGE=<change>` reaches its namespace even if a skill omitted `CHANGE`,
      but the skill now names it. The check reads its clones' summaries and the
      cluster after both runs, so a disturbance during the runs that leaves no
      trace — a read of the other's Service, say — is not shown; that each run's
      commands name only its own namespace is section 6's evidence. 10.9's
      "Evidence" now names `scripts/validate_parallel.py`, and its guide entry
      `make validate-parallel` beside the clone targets. Its `helm history`
      handling was checked only against hand-written fixtures, not a real Helm
      4.3 history, which the system run will exercise. Open for the owner: the
      clones the system run needs, and whether implementation and triage should
      keep reaching `make validate-parallel` through `make validate-*` (a deny
      rule for it in their rows is the orchestrator's edit, under `.claude/`).

## 8. History in the owner's workspace, clone removal, and teardown

Delivers D11, D6's removal, and D4's teardown and capacity figure (requirements
"Each change is worked in its own clone", "Each Helm validation is isolated in its
change's namespace"). Touches a new `scripts/change_history.py`,
`scripts/find_change.py`, `scripts/change_clone.py`, `helm/Makefile`,
`scripts/validate_slice.py`, the root `Makefile`, `.agents/skills/`
(`change-archive-cleanup`, `change-design`, `change-plan`, `change-review`,
`change-triage`, `change-closeout`, `change-orchestrate`), `.claude/change-steps.toml`,
`docs/agents/change-workflow.md`, `AGENTS.md`, and `scripts/tests/`.

- [x] 8.1 `scripts/change_history.py sync <change>` (`make change-history
      CHANGE=`), run in a clone: copy into the workspace, at the same paths, the
      archived change's whole `reviews/` and the evidence its records name
      (`.snapshot/validation/<commit>/`, `.snapshot/e2e-logs/<run>/`); copy what is
      missing, compare what is on both sides by content, extend a workspace file
      that is a byte-for-byte prefix of the clone's, and refuse, naming each, any
      other difference, never overwriting; copy nothing rebuildable (D11, 17 F4,
      26 F1).
      Note: the evidence the records name is read from every file directly in
      `reviews/` — a cited `.snapshot/validation/<dir>` or `.snapshot/e2e-logs/<run>`
      path, a validation record's `**Commit:**` (its evidence under the first twelve
      characters, as `validate_slice.py` keeps it), and its `**Pipeline:** run <id>`
      — since a validation record names its commit and run rather than the paths;
      transcripts are not read for it, as they cite whatever a session read, another
      clone's evidence included. Named evidence the clone lacks is reported, not
      refused. Only regular files are copied — a link, to a file or a directory, is
      refused and named — each aside and renamed so a session reading the
      workspace never finds a half-copy (a crash can leave the aside file); a
      refused file does not stop the others, and the command exits 1 naming each. A change not yet archived is refused:
      its history moves at archive cleanup.
- [x] 8.2 `find_change.py --records <change>`: the change's records in the checkout,
      then in the workspace through the `workspace` remote; every skill that reads
      another change's or an earlier change's records uses it (D11).
      Note: the records are the directory holding `reviews/`, so the workspace's
      archive copy is found beside the change's active directory from its branch;
      the workspace's is printed as an absolute path. `workspace_of` moved from
      `change_clone.py` into `find_change.py`, which both it and the new
      `change_history.py` import, since `change_clone.py`'s removal imports the
      history script and the two would otherwise import each other; importers of
      `change_clone.workspace_of` are unchanged. The skills reading another change's
      records — design, planning, the review, triage, closeout — say to find them
      with it; the orchestrating skill says where a done change's history went and
      that clone removal is the owner's.
- [x] 8.3 `scripts/change_clone.py remove <change>` (`make change-clone-remove
      CHANGE=`), run by the owner in the workspace: run 8.1 first; refuse, deleting
      nothing and naming what is missing, unless every file of the clone's
      `reviews/` and named evidence is in the workspace with identical contents, the
      branch is merged into `origin/dev`, and the clone has no commit `origin` lacks
      and no uncommitted change (D6).
      Note: also refused, before anything is copied, a run in progress in the clone
      and a bootstrap still running, since deleting the clone would kill the one and
      break the other; and, after the copy, a stash, which is a commit `origin`
      lacks that no branch holds. `origin` is fetched (with prune) before the merge
      and unpushed checks, which read `--branches --not --remotes=origin`. A refusal
      after the copy carries the copy's report, which the command prints beside the
      problems.
- [x] 8.4 Teardown and the figure: `make -C helm teardown CHANGE=<change>` deletes the
      change's namespace and its `-<change>` images; archive cleanup writes the
      figure from the change's latest validation's `summary.json` into
      `helm/validation-capacity.toml` with when and from which change, through the
      writer of 6.4, when that validation measured memory; when its `memory` is
      empty, it writes nothing, leaves any recorded figure as it is, and reports
      that it recorded none (D4, 37 F3, 78 F2; replanned against the reviewed
      design: the figure is conditional on a measurement).
      Note: `make -C helm teardown CHANGE=` deletes the namespace
      (`--ignore-not-found --wait`) and removes, of the images `change_namespace.py
      <change> --images` lists, each that is present, failing after trying the rest
      when one cannot be removed; it refuses without `CHANGE`, so it never deletes
      `default`. The list is the bare tags `make build-dev` writes with the suffix
      (`BUILT_IMAGES`, held to the build by a test), not every tag ending in the
      suffix, which would also take the images of a change whose name ends in this
      one's. The figure: archive cleanup's planned rules (8.6) let it edit
      `helm/validation-capacity.toml` but run no script, so "through the writer of
      6.4" could not run unattended. Put to the owner, who chose a target: `make
      record-capacity CHANGE=` (`validate_slice.py capacity --change`) reads the
      change's latest `NN-validation.md`, its `**Commit:**`, and the summary of that
      commit's last Helm attempt, and writes `memory.peak_bytes` through
      `write_capacity` with `measured_at` and the change, or writes nothing and says
      why (no Helm part; no measurement, for want of a metrics source). The Helm
      part now records `memory.measured_at`, the time of its last sample; a summary
      without it is dated by the file. The orchestrator's table edit (8.6) allows
      `make record-capacity*` in place of the `Edit` rule; D8 records the choice.
- [x] 8.5 `change-archive-cleanup`: after its commit and the pull-request draft,
      write the capacity figure when the latest validation measured one and commit
      it, tear the namespace and images down, push, then run `make change-history`
      as its last act; with no measurement, its report and the draft say that no
      figure was recorded, for want of a metrics source; the draft's notes say
      that a conflict over `helm/validation-capacity.toml` keeps the later recorded
      time (D4, D11, 37 F3, 78 F2; replanned likewise). `docs/agents/change-workflow.md` and `AGENTS.md`'s
      "Change workflow" say the owner's workspace holds the history of every
      cleaned-up change, and the guide gains clone removal.
      Note: the skill's steps are now the index commit and its push (5), the draft
      (6), `make record-capacity` and its commit (7), with its outcome — the figure,
      or no figure and the reason the target gave — and, for a recorded figure, the
      later-`measured_at` merge rule added to the draft's notes, `make -C helm
      teardown` (8, a failure reported with its rerun rather than retried), the
      figure commit's push (9), and `make change-history` last (10), only for a
      change whose `.git/config` names a `workspace` remote — a change worked in the
      workspace has its history there. The push stays at step 5 so that a run that
      dies after the index commit leaves nothing unpushed; a rerun on a row already
      `archived` skips the Advance and Validated checks and goes on from step 7,
      appending to the draft rather than rewriting it, since a rewritten file could
      no longer be extended in the workspace. A refused file is reported and the
      step still finishes, since clone removal refuses until it is reconciled. The guide's "A change in its own clone"
      gains "History and removal", its table row and review-directory paragraph
      say where history goes, and `AGENTS.md`'s "Change workflow" says the
      workspace holds every cleaned-up change's history and how to find records.
- [x] 8.6 `.claude/change-steps.toml` (the orchestrator's, as the preamble says): archive
      cleanup gains `make change-history*`, `make -C helm teardown*`, and
      `Edit(helm/validation-capacity.toml)`; every step gains `python3
      scripts/find_change.py --records *` (D8).
      Correction, on the owner's word (8.4): archive cleanup gains `make
      record-capacity*` in place of `Edit(helm/validation-capacity.toml)`. The
      orchestrator's edit was in the worktree, and is committed with this section.
      Left for the orchestrator: the preamble's "a step's permissions change here,
      by the owner" and the archive-cleanup row's comment, which does not yet name
      the figure, the teardown, or the history copy.
- [x] 8.7 Verification. Repository level (a workspace and a clone): a first copy; a
      second after the log and a transcript grew, extending them; a conflicting file
      refused and named, nothing overwritten; removal refused for each missing
      condition and run after the synchronization; `--records` finding the
      checkout's, then the workspace's. Unit: teardown's commands; the figure
      written with its time and change; with an empty measurement, nothing written
      and a recorded figure left as it was (78 F2). `uv run --no-project --with pytest pytest -q
      scripts/tests`; `make check-agent-skills`; a fresh-context read of the changed
      skills against D11 and the delta's clone requirement; `make test`. No
      end-to-end scenario covers it.
      Evidence. `scripts/tests/test_change_history.py`, 16 passed, repository level
      (real Git: a workspace with a bare `origin` and a clone made by
      `change_clone.create`, its spawn injected): a first copy of the records,
      transcripts included, and of the evidence they name — the validated commit's,
      a cited one, and the pipeline run's — to the same paths, an unnamed evidence
      directory and the run's zip left; named evidence the clone lacks reported; a
      second copy extending the log and a transcript that grew, adding a new
      record, and leaving six files; two conflicting files refused and named, left
      as they were, the rest copied, and both listed by `differences`; a directory
      where the clone has a file, and a link to a file and to a directory, each
      refused; a change not archived, and an archive without records, refused; the
      command copying and reporting, failing over a refusal, and refusing outside a
      clone; `--records` finding the clone's records, then the workspace's, and a
      cleaned-up change's from another clone, and refusing records found nowhere;
      which evidence records name, read from text (unit). `test_find_change.py`, 22
      passed, unit: the records directory of an active change, the archive copy
      beside an active directory without records, none, an archive copy twice
      refused, the checkout before the workspace (the workspace lookup injected),
      and `--records` not combined with another restriction.
      `test_change_clone.py`, 55 passed, repository level: removal after the copy,
      with what grew since extended; the settings link deleted and the workspace's
      settings kept; a merge `origin` holds that the clone had not fetched letting
      the clone go (the fetch shown); refused, the clone kept, for a differing
      record (the rest copied all the same), a branch not merged, a commit `origin`
      lacks, uncommitted changes, a stash, a marker branch the clone lacks, and an
      `origin` that cannot be fetched (the copy's report kept); refused before any
      copy for a run in progress, a running bootstrap, another change's clone, a
      change not archived, no clone, a directory not a clone, and a clone as
      workspace; the command line reporting a refusal and a removal. The aside
      copy's partial-file protection is shown only by no aside file left behind,
      and `rmtree` failing is untested. `test_change_build_and_helm_targets.py`,
      integration through the real `helm/Makefile` against fake `kubectl` and
      `docker` on `PATH` (the process boundary): teardown deleting the namespace in
      `docker-desktop`, and in a `HELM_CONTEXT` given, removing the images present
      and naming the absent, failing over an image it could not remove after
      trying the rest, and refused without `CHANGE`, nothing run; and, through
      `make -n`, the image list equal to every tag `make build-dev` writes with a
      suffix. `test_change_namespace.py`, 23 passed, unit: a change's images and
      `--images`. `test_validate_slice.py`, unit with the runner and reader
      injected: the figure from the latest record's commit's last Helm attempt,
      with its time and change, over an older record; with no measurement, no Helm
      part, and no validation record, nothing written, the recorded figure left as
      it was, and the reason said; a summary without a timestamp dated by the file;
      memory that is not a measurement recording nothing; `measured_at` the last
      sample's time; the command. `uv run --no-project --with pytest pytest -q
      scripts/tests`: 1442 passed after both fresh-context checks' fixes. `make
      test`: passed, every suite, `make -C helm test-render` included, run before
      those fixes, which touched only scripts and their tests, `helm/Makefile`'s
      teardown, skills, and documents; after them `make -C helm test-render`
      passed again. `make check-packaging`, `make check-agent-skills`, and `make
      check-comment-hygiene`: passed. `make check-change`: only the citations of
      the scripts section 8A creates (`scripts/ci_evidence.py`,
      `scripts/tests/test_ci_evidence.py`). End to end: none — no scenario in
      `e2e-tests/` exercises the history copy, removal, the figure, or teardown;
      the pilot's archive cleanup is their working evidence (9.1).
      The first fresh-context check found, and this section fixed: teardown ran in
      whatever kube context was current (now `HELM_CONTEXT`, `docker-desktop`);
      archive cleanup's push moved after the figure left a window a rerun could
      not close (the push is back at step 5, and a rerun goes on from step 7);
      `record-capacity` failed with no validation record and the skill gave "for
      want of a metrics source" as every reason (now the target's reason);
      malformed memory and a `measured_at` that is no timestamp; a failed fetch
      losing the copy's report; `rmtree` unguarded; a symlinked directory silently
      skipped; the guide's order of removal's refusals; the settings-link test
      checking nothing; and the untested refusals and the last-sample time, now
      tested. Declined: calling the history tests "repository level", the term
      sections 1–3 use; the `Contract:` lines naming the delta's requirement, which
      the archive promotes. The second check found, and this section fixed: a rerun
      stopped at step 1's Validated check by its own figure commit; a rerun's
      rewrite of the draft, which the copy would then refuse; the aside copy's
      stated reason; an unused constant; the guide's table row lacking "for a
      change worked in its own clone"; and the 8.5 note's account of the push.
      Declined: a crashed attempt's summary being skipped for an earlier attempt of
      the same commit, which is still that commit's measurement; the small
      duplication of the record-commit pattern and of `workspace_of`'s Git calls,
      each module keeping its own reads.
      Handoff: unverified — that an unattended Claude step or the Codex review can
      read the absolute workspace path `--records` prints for another change's
      records; the pilot's sessions will show it, and a denial would name the call.
      Left for the orchestrator (`.claude/`): `Bash(python3 scripts/find_change.py
      --records *)` in `common` is already covered by `Bash(python3
      scripts/find_change.py*)`; `Bash(make -C helm teardown*)` also admits a
      `HELM_CONTEXT=` naming another context, so a narrower rule may be wanted; the
      archive-cleanup row's comment and the preamble's permissions sentence (8.6).
      Section 9 records the pilot's history copy and figure from its archive
      cleanup on this tooling.

## 8A. Evidence only a push produces, owed by validation

Delivers D14–D18 (requirements "Implementation sections and sessions" and
"Validation observes a committed slice"): a plan names push-only evidence as owed
by validation; validation dispatches each owed workflow from a fixed list, judges
the owed jobs, and compares every other failure with a `dev` run the branch
contains. Touches a new `scripts/ci_evidence.py`, `scripts/fetch-e2e-logs.py`,
`scripts/validate_slice.py`, the root `Makefile`, `.claude/change-steps.toml`,
`.agents/skills/` (`change-plan`, `change-implement`, `change-validate`,
`change-closeout`), `docs/agents/change-workflow.md`, and `scripts/tests/`.

- [x] 8A.1 `scripts/ci_evidence.py`: the dispatchable list (`tests.yml`) and
      `dispatch <workflow>`, which refuses a workflow not on the list, naming the
      list, records the newest run of the workflow on the branch and prints its ID,
      and runs `gh workflow run <workflow> --ref <branch>`; `make run-ci
      WORKFLOW=<file>` runs it (D15).
      Note: `DISPATCHABLE`; the ID is printed as `CI_AFTER_RUN=<id>`, 0 when the
      branch has no run of the workflow; a refusal runs nothing and exits 2, a
      detached `HEAD` is refused before any dispatch. `make run-ci` has `make
      round-view-closed` as its prerequisite, as `make run-e2e` does.
- [x] 8A.2 The fetch: `scripts/fetch-e2e-logs.py --workflow <file>` downloads the
      run's whole log (`gh run view --log`) and, for a workflow other than
      `e2e.yml`, asks for none of the end-to-end lanes' artifacts, so a missing one
      is not warned about (D15).
      Note: the whole log was already downloaded for any workflow; the lane
      artifacts are now asked for only of `e2e.yml`'s runs, and the script's
      messages name the workflow, or no workflow, rather than "E2E". It also
      gains `--event`, taking only runs triggered so; the `ci` part passes
      `workflow_dispatch`, and the pipeline's fetch is unchanged.
- [x] 8A.3 The comparison in `scripts/ci_evidence.py`, over the fetched logs: each
      job's failures — every pytest short-summary line, `FAILED <id> - <type>:
      <message>`, as the test ID and the exception type; for a job printing none,
      the failing step and its error lines; the baseline — the latest completed run
      of the same workflow on `dev` whose head commit is an ancestor of the
      validated commit (`git merge-base --is-ancestor`), its log fetched the same
      way; and each failure classed `inherited` when the baseline's same job shows
      the same test ID with the same exception type, `new` when it does not, and
      `uncomparable` when there is no baseline or the job printed no short summary
      on either side (D16, 78 F1, 83 F1).
      Note: `read_jobs` takes each job's conclusion and failing steps from `gh run
      view --json jobs` and its lines from the whole log, whose lines `gh` prefixes
      with the job's and the step's names and a timestamp (read past a byte-order
      mark and colour codes). Only lines inside a `short test summary info` block
      are read, so a line starting `FAILED` elsewhere is not a failure; `ERROR`
      lines (an error outside the test body) count as failures beside `FAILED`; a
      test ID's bracketed parameters may hold spaces. On CI (`CI` set) pytest
      prints each entry's whole crash message, which may run over several lines;
      only lines matching `FAILED`/`ERROR` are read as entries, and the block ends
      only at pytest's closing count, matched as `-q` prints it (counts of named
      outcomes, then `in <n>s`, with or without its rule), at a runner line
      (`##[…`), or where its step ends, so a message line cannot end it early.
      The type is the message's leading `<name>:`, or a message that is only an
      exception's name (`TimeoutError`, `asyncio.CancelledError`, raised with no
      message), and a plain failed `assert`, which pytest prints as the assertion
      itself, is `AssertionError`. A line naming no type — pytest trims lines off
      CI, dropping a long ID's message — makes that failure `uncomparable`, since
      D16 rejects comparing by the ID alone. A test is compared by ID, type, and
      outcome, so one erroring where `dev` fails it is `new`.
      Correction to the task's wording, from the fresh-context checks: D16 and the
      delta compare a job printing no failing test by its failing step and error
      lines, so such a job — a TypeScript or Rust job, a setup step — is not always
      `uncomparable`: it is `inherited` when the baseline's same job failed at the
      same step with the same `##[error]` lines, and `new` when that job passed,
      or failed only at other steps, or there with other error lines. Failing
      tests are likewise `new` beside a baseline job that failed only at other
      steps. Every failure is `uncomparable` when there is no baseline (or it
      could not be chosen, fetched, or read, the reason saying which), when the
      baseline has no job of that name or skipped it, when either run's log holds
      no line of the job (as if `gh`'s log named jobs otherwise than `--json
      jobs`), when either job failed at no named step, when a step's error lines
      say only that it failed (the runner's `Process completed with exit code
      <n>.`, all a TypeScript or Rust job's new failing test may leave), or when
      one side names failing tests and the other only the same step failing; a
      baseline job that passed makes every failure `new`. A job
      with failing tests is compared by them alone, not also by its failing steps:
      a `tests.yml` job stops at its first failing step.
      Choosing the baseline (`baseline_run`) skips a cancelled `dev` run, which
      completed without its jobs finishing, and a pull request's, which tests a
      merge rather than its head commit; ancestry (`is_ancestor`) is `git
      merge-base --is-ancestor` after `git rev-parse --verify --quiet`, so a commit
      the checkout lacks is no ancestor, and any other Git exit is an error, not an
      answer.
- [x] 8A.4 Validation's `ci` part: `validate_slice.py ci --workflow <file>
      --after-run <id>` (`make validate-ci WORKFLOW=<file> CI_AFTER_RUN=<id>`,
      which the validate step's `make validate-*` rule already allows) writes an
      attempt under `.snapshot/validation/<short commit>/ci/<attempt>/` like the
      other parts: the run and its conclusion, the baseline run and its commit,
      each job's result and log, and 8A.3's classes, in `summary.json`; a run that
      is cancelled, never listed, or not fetched is reported as producing no
      evidence. Judging the owed observations is the validating agent's, from the
      job logs (D15, D16).
      Note: the part fetches both runs with `fetch-e2e-logs.py` — the dispatched
      one with its new `--event workflow_dispatch`, so a pull request's run of the
      same head commit, which tests a merge, is never taken — into the attempt's
      `runs/<run>/` — `actions.log`, `run.json`, and `jobs/<job>.log` — so the
      history copy, which copies the validated commit's
      `.snapshot/validation/<commit>/`, carries them with no rule of its own.
      `summary.json`'s `evidence` holds `workflow`, `run`, `baseline`, `jobs`
      (each with its conclusion, failing steps, error lines, classed failures, a
      reason when they share one, and its log), `classes`, and `no_evidence`. The
      part passes when the run produced evidence and every failure is
      `inherited`; a `new` or `uncomparable` one fails its `failures` step, naming
      each, and an owed job is the agent's to judge whatever the part says. Also
      refused: a workflow off the list (nothing run), a run of another commit,
      and `ci` without `--workflow` or `--after-run`, since without the run before
      the dispatch an earlier run of the same commit could be read. A run not yet
      `completed`, a fetch that kept no run, and a run that cannot be read are no
      evidence too. No baseline is a `baseline` warning; a baseline that cannot be
      chosen (a listing that fails or is not a list, a failing ancestry check),
      fetched, or read fails its step, and the part still compares with
      none, keeping the run's own evidence, every failure `uncomparable` with that
      reason — the one place a part goes on past a failed step; when no job of the
      run failed, such a baseline step is a warning, nothing needing comparison.
      `HEAD` moving after the fetch fails a `checkout` step and stops the part. The
      helper closing a part is now `_after_part`, shared by the Helm and `ci`
      parts.
- [x] 8A.5 `.claude/change-steps.toml` (the orchestrator's, as the preamble says):
      validate gains `Bash(make run-ci *)` (D15).
      Note: the orchestrator's edit was in the worktree as the session started and
      is committed with this section. `test_change_workflow_steps.py` gains a test
      that validation alone may run `make run-ci`.
- [x] 8A.6 `change-validate`: read every `Owed by validation:` line of a section
      whose tasks are all checked at `HEAD`; with none, the part is `ci not owed`;
      otherwise, per workflow, `make run-ci` once the push is done, then `make
      validate-ci`, beside the pipeline; judge each named job and its observation,
      a failed job or absent observation a `V<n>`; take `inherited` failures as
      already failing on `dev`, diagnose `new` ones like any failure and
      `uncomparable` ones as of unknown cause; a run with no evidence is
      environmental, put to the owner with its remedy; the record's `Parts` line
      gains `ci <result>`, its header a `**CI:**` line, and its body `## CI`, as
      D16's example shows; `tasks.md` is never edited (D14, D16, D17).
      Note: the owed lines are read in step 1, the dispatch and `make validate-ci`
      started in step 2 beside the pipeline, what the part keeps described in step
      3, the judging in step 4's "The CI part", and the record's `Parts`, `**CI:**`,
      `## CI`, and the `ci` result in step 7. A line owing a workflow off the list
      is refused by `make run-ci`, its observation absent, a `V<n>` of unknown
      cause for triage to take to design.
- [x] 8A.7 `change-plan`: a section's verification names only evidence an
      implementation session can produce, and evidence only a push produces on an
      `Owed by validation:` line — workflow, job, what the job must show — beside
      `End-to-end:`; a workflow not on `scripts/ci_evidence.py`'s list cannot be
      owed and is a design question. `change-implement`: before a section's last
      task is checked, confirm or correct its `Owed by validation:` lines, and a
      verification that demands push-only evidence is checked on the section's own
      evidence, that evidence named as owed by validation in the notes.
      `change-closeout`: the end-to-end part records the owed observations from the
      latest passing validation's `## CI`, as it records the pipeline run (D14,
      D18).
      Note: `change-plan`'s "Sections are slices" gains the bullet with D14's
      example line; `change-implement`'s step 3 the confirmation beside the
      end-to-end one; `change-closeout`'s end-to-end part the owed observations
      with their runs and baseline.
- [x] 8A.8 `docs/agents/change-workflow.md`: in "Skills", `make run-ci` and `make
      validate-ci` beside the pipeline targets; in "Reviews", the `Owed by
      validation:` line and the record's `## CI` (D14, D16).
      Note: the Validation row names the pipeline's and the CI targets, and a
      paragraph after the push paragraph says what each does and that only the
      owner extends the list.
- [x] 8A.9 Verification. Unit, with an injected runner, in
      `scripts/tests/test_ci_evidence.py`: a listed workflow dispatched on the
      branch and a publishing one refused, naming the list, nothing run; parsing
      short-summary lines; a baseline chosen as the newest `dev` run whose commit
      the branch contains, skipping a newer one it does not; each of the delta's
      scenarios — "Owed CI evidence beside jobs that fail on `dev`", "A job not owed
      fails only on the branch", "A new failure in a job that already fails on
      `dev`", "A test that fails on `dev` fails another way on the branch", "No
      `dev` run of the branch's code" — as classes over fixture logs. Unit, in
      `scripts/tests/test_fetch_e2e_logs.py`: a `tests.yml` fetch asks for no lane
      artifact. Unit, in `scripts/tests/test_validate_slice.py`: the `ci` part's
      summary, and a cancelled run reported as no evidence. `uv run --no-project
      --with pytest pytest -q scripts/tests`; `make check-agent-skills`; a
      fresh-context read of the changed skills against D14–D18 and the delta's two
      modified requirements; `make test`. End-to-end: none of `e2e-tests/`; the
      part is exercised by this round's validation, which this line owes.
      Owed by validation: `tests.yml`, job `release · deployment contracts` — the
      job passes, and the record's `## CI` names the baseline `dev` run and its
      commit, and classes every failure of the jobs not owed.
      Evidence. `scripts/tests/test_ci_evidence.py`, 47 passed, unit (Git and `gh`
      injected as a fake runner): a listed workflow dispatched on the branch after
      its newest run there is recorded and printed as `CI_AFTER_RUN`, and 0 for a
      branch with none; `publish-pypi.yml`, `e2e.yml`, and no workflow refused,
      naming the list, nothing run, and the command line's exit 2 for the first
      two; a detached
      `HEAD` refused before any dispatch; the list holding `tests.yml` alone; the
      baseline the newest `dev` run the branch contains, skipping a newer one it
      does not, skipping a cancelled run and a pull request's, and none; ancestry
      true and false, a commit the checkout lacks never asked of `merge-base`, and
      a failing `merge-base` and a failing `rev-parse` each an error;
      short-summary lines read as test ID and type — a type, a bracketed
      parameter holding ` - `, an `ERROR` line, a dotted type, a long ID with no
      message, pytest's `Failed:`, a `SKIPPED` line not a failure, a plain `assert`
      as `AssertionError`, an exception's bare name (dotted too) as its type and a
      bare word not; entries whose messages run over several lines — among them
      lines reading like a count (`3 attempts in 5.0s`, `5 failed in 2.0s, then
      …`) and a rule — hiding no later entry; pytest's closing count, bare and
      ruled, ending the summary; a summary with no closing count ending with its
      step and at a runner line; only the summary block read, past the timestamp, the
      byte-order mark, and colour, another job's lines apart; a job printing no
      summary keeping its failing step and error lines; and the delta's five
      scenarios — "Owed CI evidence beside jobs that fail on `dev`", "A job not owed
      fails only on the branch", "A new failure in a job that already fails on
      `dev`", "A test that fails on `dev` fails another way on the branch", "No `dev`
      run of the branch's code" — as classes over fixture logs; a job printing no
      failing test compared by its step: `inherited` at the same step with the
      same error lines, `new` beside a passing baseline job, other error lines, a
      baseline failing only another step, and a baseline naming failing tests at
      another step; failing tests `new` beside a baseline failing only a later
      step; failing tests beside a baseline job that timed out at the same step
      printing none, and a failing step beside a baseline naming failing tests at
      it, each `uncomparable`; a job failing at no named step and a job the
      baseline skipped `uncomparable`; a job of which the run's or the
      baseline's log holds no line, and a step whose error lines on both sides
      say only that it failed, `uncomparable`; the caller's reason for no
      baseline kept; a job the baseline lacks; a failure naming no type
      `uncomparable` beside an `inherited` one; a bare `KeyError` where `dev`
      raises a bare `TimeoutError`, and a test erroring where `dev` fails it,
      each `new`; and passing and skipped jobs.
      `scripts/tests/test_fetch_e2e_logs.py`, 20 passed, unit (`gh` faked at the
      process boundary): a `tests.yml` fetch keeps the whole log, lists
      `tests.yml`'s runs, asks for no lane artifact, and warns of none; `--event
      workflow_dispatch` passing over a newer pull request's run of the same
      commit, and refused beside `--run-id`; a `tests.yml` run whose log cannot
      be fetched fails. `scripts/tests/
      test_validate_slice.py`, the `ci` part's orchestration with the runner and
      reader injected — a fake fetch leaving each run's `actions.log`, a fake `gh`
      answering the run, its jobs, and the `dev` listing — integration as
      `TESTING.md` defines it for orchestration, as section 6 named it: the
      summary's run, baseline, classed jobs, and classes, the job's log file, the
      run's `run.json`, the written `summary.json`, every step's result, the fetch
      after the recorded run, of the dispatch only, then the baseline's by ID, the
      `dev` listing read with its events, and the rendered lines; a failure the
      baseline lacks failing the part, naming it alone; no baseline a warning,
      every failure `uncomparable`, nothing more fetched; a baseline whose fetch
      fails, one fetched but unreadable, a listing that is not a list, and a
      failing ancestry check each failing its step and leaving every failure
      `uncomparable`, the reason saying which; a baseline that cannot be fetched
      only a warning when no job failed, the part passing; `HEAD` moving while
      the baseline is fetched failing a `checkout` step, no job compared; no
      evidence from a
      cancelled run, a run not yet completed, a fetch that exits non-zero (one
      case standing for a run never listed and one not fetched, which the part
      tells apart only by the fetch's log), a fetch that keeps no run, and a run
      that cannot be read, the first and the fetch failures read no further; a
      run of another commit refused; a workflow off
      the list refused, nothing run; the command line refusing `ci` without either
      argument; and, through `make -n` over the real Makefile, `make validate-ci`
      and `make run-ci` running their scripts. `scripts/tests/
      test_change_workflow_steps.py`, unit over the real step table: validation
      alone may run `make run-ci`. Not shown: a real `gh run view --log` of
      `tests.yml` and a real `--json jobs`; the fixtures follow the format of an
      `e2e.yml` log fetched earlier (`<job>\t<step>\t<timestamp> <line>`), and the
      validation this line owes exercises the real ones. `uv run --no-project
      --with pytest pytest -q scripts/tests`: 1512 passed after the three
      fresh-context checks' fixes. `make test`: passed, every suite, `make -C helm
      test-render` included, before the fixes and again after the last. `make
      check-packaging`, `make check-agent-skills`, and `make check-change`:
      passed, citations included, now that the scripts this section creates exist.
      The fresh-context read of the diff — the changed skills among it — against
      D14–D18 and the delta's two modified requirements found no breach of
      layering, imports, comments, or packaging, and found, all fixed: a job
      printing no failing test was always `uncomparable`, where D16 and the
      delta compare it by its failing step and error lines (the plan's 8A.3 had
      narrowed it; corrected there); a baseline that could not be listed, fetched,
      or read was reported as no `dev` run of the branch's code; the module
      docstring's "both parts" and "each part stops at its first failure", which
      the `ci` part made untrue; a fetch message still saying "E2E"; and evidence
      claims beyond their tests — the not-completed run, a fetch keeping no run, an
      unreadable run, exit 2 for `e2e.yml`, and one fetch failure claimed as two
      cases — now tested or narrowed. Declined: classing a job's failing steps
      beside its failing tests, since a `tests.yml` job stops at its first
      failing step. A second check, after those fixes, found and this section
      fixed: the summary parser ended a block at an entry's second line, while
      pytest on CI prints each entry's whole, often multi-line, message, so a
      failure listed after one could be missed and the part pass over it; the
      notes' "80 columns" premise, false on CI, where nothing is trimmed and
      `tests.yml` sets `COLUMNS: '200'` besides; failing tests beside a baseline
      failing only a later step called `uncomparable` rather than `new`; a
      skipped baseline job read as passing; a job failing at no named step
      always `new`; a `dev` listing that is not a list reported as no baseline;
      `git cat-file`'s exit 128 for a missing commit indistinguishable from any
      other failure (now `rev-parse --verify --quiet`, exit 1); a pull request's
      run of the same head commit, which tests a merge, able to be taken as the
      run or the baseline (now `--event workflow_dispatch` on the fetch, and pull
      requests' runs skipped as baselines); the skill's no-evidence list and its
      treating every no-evidence case as environmental; the guide's
      `<commit>` path; and evidence claims beyond their tests, now tested. A third
      check, after those, found and this section fixed: two steps failing the
      same way with nothing said but the runner's exit line — or with no line of
      the job in either log, as a job-name mismatch would leave — were
      `inherited`, so a new TypeScript or Rust test failure could pass (now
      `uncomparable`); the summary's end rule matched a message line such as `3
      attempts in 5.0s`, hiding the entries after it (now pytest's count alone);
      an exception raised with no message had no type, and two typeless failures
      were compared by ID alone, which D16 rejects (now the bare name is the type,
      and a typeless failure `uncomparable`); the outcome was not compared; a
      `HEAD` move after the fetch stopped the part without failing it; a
      baseline that could not be had failed a run in which nothing failed (now a
      warning); a docstring sentence with no verb and one that would go stale;
      the fetch's docstring not naming `--event`; and the notes' claims about
      them. End to end: none of `e2e-tests/`; the
      owed line is confirmed — `release · deployment contracts` is that job's
      `name:` in `.github/workflows/tests.yml` — and this round's validation is
      the part's first real run.
      Handoff: unverified until that run — `gh run view --log`'s prefix for
      `tests.yml`'s job names (`py · <name>`, matched exactly against `--json
      jobs`'s `name`), and the `--json` fields read (`jobs[].name`,
      `conclusion`, `status`, `steps[].name`, `steps[].conclusion`); this step
      could run no `gh` to check them, and a mismatch would show as every failed
      job `uncomparable`, its reason saying the log holds no line of it, and the
      part failing. The multi-line summary entries follow pytest's own
      source (`_get_line_with_reprcrash_message`, untrimmed when `CI` is set),
      not a real `tests.yml` log. A baseline older than GitHub's log
      retention cannot be fetched, which fails `baseline fetch` and leaves every
      failure `uncomparable`. For closeout (10.9): the companion
      `architecture.md`'s "Each part therefore starts from `make dist-clean`" is
      no longer true of the `ci` part, which builds nothing. Implementation and
      triage reach `make
      validate-ci` through their `make validate-*` rule; it only reads GitHub
      and writes under `.snapshot/`, so it was left. Section 8B's fresh run
      grant is how a validation granted a missing `gh` rule would get it.

## 8B. Grants for a fresh run, and the commit and merge rules

Delivers D19 and D20 (requirements "Unattended runs are held to their step's
permissions", "Implementation sections and sessions", "An orchestrating session
advances one change"): a one-run grant reaches a fresh run through `ALLOW`; a
returning step commits its partial work; the orchestrating session commits
maintenance, instructions, and merges of `dev`, and hands code conflicts to the
owner, then to an implementation run. Touches `scripts/change_workflow/cli.py`,
`scripts/change_workflow/wrapper.py`, `scripts/change_next_step.py`, the root
`Makefile`, `.claude/change-steps.toml`, `.agents/skills/` (`change-orchestrate`,
`change-implement`, `change-triage`, `change-plan`, `change-closeout`),
`docs/agents/change-workflow.md`, and `scripts/tests/`.

- [x] 8B.1 `run_change_step.py run` takes `--allow`, repeatable; for `run` and
      `resume`, each value is split on `;` and empty parts dropped; `Wrapper.run`
      takes `granted`, passes it on the command line, and records it as `granted`
      on the run's line, as `resume` does (D19).
      Note: `split_rules` in `change_workflow/cli.py` also trims each part, so
      `a; b` grants `b`, not ` b`.
- [x] 8B.2 The root `Makefile`: every unattended step target — `design`, `plan`,
      `implement`, `triage`, `validate`, `closeout`, `archive-cleanup` — passes
      `ALLOW` to `run` as `--allow`; `implement` passes `ARGUMENTS` as `--arguments`
      (D19, D20.3).
      Note: `STEP_GRANTS` makes each `;`-separated rule its own `--allow`, each
      single-quoted with `'` escaped, so spaces, `*`, quotes, and backticks reach
      the script as written; `ARGUMENTS` is quoted the same way. A `$` in either is
      make's own and is written `$$`, as the comment beside `ALLOW` says. Both are
      unattended only: an interactive session is not held to the table, and
      `ARGUMENTS` was planned for the unattended merge hand-off alone. The help
      lines name both.
- [x] 8B.3 The next-step computation: while the checkout's Git directory holds
      `MERGE_HEAD`, it names `owner`, "a merge is in progress", before any other
      routing (D20.3).
      Note: `_merging` (`git rev-parse --quiet --verify MERGE_HEAD`) is an injected
      seam, `merging`, checked first in `Computation.run`, before the view, the
      clone lookup, or the change's files are read; the result carries
      `merging: true`.
- [x] 8B.4 `.claude/change-steps.toml` (the orchestrator's, as the preamble says):
      the preamble's "a rule the owner grants for one resumed run" becomes "for one
      run, fresh or resumed" (D19).
      Note: the orchestrator's edit was in the worktree as the session started and
      is committed with this section.
- [x] 8B.5 Partial work on a return (D20 rule 2): `change-implement` §4 commits
      what the section has as work in progress, checks no task for it, records the
      handoff, pushes, and returns; a stop leaves its work uncommitted, and a guard's
      refusal or a moved `HEAD` commits nothing. `change-triage`, `change-plan`,
      and `change-closeout` say the same of their returns.
      Note: `change-implement`'s step 4 and its unattended "The end is an outcome";
      a block for an external input commits nothing, since its session resumes; a
      work-in-progress commit whose push the guard refuses is left as it is.
      `change-plan` and `change-closeout` in their unattended return bullets;
      `change-triage`, which had no return, gains "A return commits its partial
      work; a stop does not", for a fix that shows the plan or design wrong.
- [x] 8B.6 The merge mode of `change-implement` (D20.3): invoked with no sections
      and an argument naming a merge's conflicted files, it resolves them, runs the
      suites of the sections owning those files, concludes the merge with `git
      commit`, pushes, and finishes, checking no task.
      Note: a section of its own, "Resolving a merge's conflicts", before step 1:
      it checks `MERGE_HEAD` and that the unmerged files are those named, reads
      each side with `git log --merge -p`, asks the owner where both sides cannot
      hold, runs the owning sections' suites and `make test` (and `make lock`/`make
      check-packaging` when a lock or `pyproject.toml` conflicted), and concludes
      with `git commit -m <Git's merge subject> -m <resolutions>`, which opens no
      editor. The skill's description names the mode.
- [x] 8B.7 `change-orchestrate` (D19, D20): a grant is passed to a fresh run as
      `ALLOW='<rule>;<rule>'` on its step's target and to a resumed run as
      `--allow`, so a stop met inside a round's window is recovered either way;
      the closed-step leftover commit is replaced by bringing leftover work to the
      owner, committing it only on their word; it commits workflow maintenance, what
      the owner instructs, and merges of `dev` on the owner's word, never while a
      step runs, a round view is open, or between a round's sections being
      committed and its triage; it resolves conflicts in the index, change
      documents, the step table, and skills itself, and brings a code conflict to
      the owner, starting, when the owner does not rule on it, `make implement
      CHANGE=<change> UNATTENDED=1 ARGUMENTS='resolve the merge conflicts in
      <files>'` after recording the owner's decision; "Never commit the change's own
      feature work" becomes "never write the change's feature work of your own
      accord".
      Note: the opening paragraph, "Run the computed step", "Read every denial",
      the `owner` relay paragraph (a `merging` result), and "Maintain the
      workflow". `dev` is merged from the clone's `origin` (another branch still
      from `workspace`); a merge stopped at conflicts is never aborted; the session
      resolves the index rows, change documents under `openspec/changes/` (any
      change's), the step table, and skills, and brings any other conflict — code
      above all — to the owner, concluding with `git commit --no-edit`. A stopped
      run's work may, on the owner's word, be committed to a separate
      work-in-progress branch (D20 rule 2), as a fresh rerun of implementation,
      which wants a clean worktree, needs. A merge run's question or stop is
      resumed by the `seq` its target printed, since the computation names no
      waiting run while `MERGE_HEAD` exists.
- [x] 8B.8 `docs/agents/change-workflow.md`: in "Orchestrating a change", grants
      for a fresh or resumed run with `ALLOW`, the commit rules (each step commits
      and pushes its own work; partial work only on a return), and merges of `dev`
      with the conflict hand-off (D19, D20).
      Note: "Granting a rule for one run", "Commits", and "Merging `dev`", after
      "Maintaining the step table", whose "granted for one resumed run" became "for
      one run"; the opening paragraph loses the leftover commit.
- [x] 8B.9 Verification. Unit, in `scripts/tests/test_run_change_step.py` and
      `scripts/tests/test_change_workflow_wrapper.py`: `run --allow` passes the
      rules and records `granted`; `ALLOW`-style `a;b` splits into two rules for
      `run` and `resume`; the step's next run has no grant — the delta's scenario
      "The owner grants rules before a fresh run". Unit, in
      `scripts/tests/test_change_next_step.py`: `MERGE_HEAD` present names the
      owner whatever the change's state. Unit, in a Makefile dry-run test beside
      `scripts/tests/test_run_change_step.py`'s: `ALLOW` and `ARGUMENTS` reach the
      command line, each rule its own `--allow`. `uv run --no-project --with pytest
      pytest -q scripts/tests`; `make check-agent-skills`; a fresh-context read of
      the changed skills against D19, D20, and the delta's orchestrator and
      permissions requirements, with its scenarios "A merge of `dev` conflicts in
      a skill and in code", "A merge is asked for during a round's window", "A
      closed step leaves tracked work uncommitted", "A step stops at its session's
      limit", and "The plan's premise fails mid-section"; `make test`. No
      end-to-end scenario covers it.
      Evidence. Unit, the CLI and wrapper with a fake Claude: in
      `test_run_change_step.py`, `run --allow 'a;b' --allow c` passes three rules
      after the table's and records them `granted`; `resume --allow 'a;; b ;'`
      passes two; `split_rules` over empty, single, `;`-separated, padded, and
      blank values. In `test_change_workflow_wrapper.py`, a fresh run granted two
      rules passes them after the table's and records both, and the step's next
      run is held to its table, `granted` absent — the delta's "The owner grants
      rules before a fresh run", covered in pieces with the Makefile tests below,
      since no test runs make, the script, and the wrapper end to end. In
      `test_change_next_step.py`, through the `merging` seam: a merge in progress
      names the owner, `merging`, in five states (ready for design, a design
      question, an untriaged review, a committed round, in closeout), and before
      the view, the workspace, and the clone are read (each fails the test if
      read). Through `make -n` over the real `Makefile` (unit, as earlier
      sections named it): `ALLOW` on all seven targets becomes one `--allow` per
      rule, and interactively none; `ARGUMENTS` on `implement` beside a grant.
      Integration, as `TESTING.md` defines it for a real process boundary: the
      `make -n` command run by `sh`, a quoted rule, a backticked rule and
      argument, and an empty part arriving as written, the empty part then dropped
      by `split_rules`; and, in a real Git repository, a conflicted merge seen by
      `_merging` until `git commit` concludes it, the computation naming design
      before and after. `uv run --no-project --with pytest pytest -q
      scripts/tests`: 1537 passed. `make check-agent-skills`, `make
      check-packaging`, and `make check-change CHANGE=parallel-change-workflows`:
      passed. `make test`: passed,
      every suite, `make -C helm test-render` included. The skill fixes after the
      fresh-context check changed no code or test. End to end: none of
      `e2e-tests/`, and no `Owed by validation:` line: nothing here needs a push
      to show.
      The fresh-context read of the diff and of the changed skills against D19,
      D20, and the delta found no breach of layering, comments, documentation
      placement, or packaging, and found, all fixed: the real-Git and real-shell
      tests called unit here (now integration, above); an unwrapped line in the
      guide; a merge run's question or stop with no route back while the
      computation names only `merging` (now resumed by the `seq` its target
      printed); the `disagreement` an `implement` line reports for a change in
      design or planning (now named in the skill as expected); "the change's
      documents" narrowing D20.2's "change documents", and permanent documents in
      neither tier (now any change's documents, and any other conflict the
      owner's); D20 rule 2's work-in-progress branch for a stopped run missing
      from the skill and the guide; `change-implement` saying a refused guard
      commits nothing after its work-in-progress commit (now "nothing further",
      the commit left); two `git commit`s that would open an editor (now `-m … -m
      …` and `--no-edit`); and the guide's `make change-next` not saying it runs in
      the clone. Declined, for review: see the handoff. Not run again after these
      fixes, which were wording in the skills and the guide.
      Handoff, for the implementation review and triage:
      - A triage that returns the change writes no `## Next`, so its file reads as
        a triage in progress, and the computation may name triage again once the
        change is back in design or planning. The skill does not say what `## Next`
        records on a return, since neither token fits and D20 does not decide it;
        a design question, not settled here.
      - The merge check runs in whatever checkout computes, before the clone
        lookup, as 8B.3 says ("before any other routing"): an unrelated merge in
        progress in the owner's workspace makes the workspace's computation name
        the owner rather than `in-clone`. D20.3 means the change's own merge, so
        whether the check should follow the clone lookup is for review.
      - No test runs a merge-mode `implement` run's prompt or the routing after
        it; 8B.9 asks for neither.

## 9. The pilot's evidence and the containerization decision

Delivers D9's evidence and open question 1's decision point, once the pilot's
archive cleanup has run on this branch's tooling. Touches this change's documents
only.

- [ ] 9.1 Record from the pilot's log and records, citing their seq numbers: its
      clone's creation and bootstrap; its validation in its own namespace beside
      this change's round-2 validation, with both namespaces, tags, and scenario
      pods; a round of it read in the owner's workspace, with any commit made during
      the view and what `round-done` did with it; its archive cleanup's history copy
      and the capacity figure that cleanup wrote, or that it wrote none for want of
      a metrics source (78 F2; replanned against the reviewed design); each merge of
      this branch into the
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
- [ ] 10.3 Documentation compliance: re-check D1–D11 and D14–D21 against
      `openspec/README.md`'s placement rules.
- [ ] 10.4 Narrative compression of the notes of sections 1–9, 8A and 8B included,
      moving any rationale not yet in `design.md` there first.
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
      owner, and, from the latest passing validation's `## CI`, the owed
      `tests.yml` observation of 8A.9 with its run and baseline (D18). No pipeline
      scenario exercises the workflow tooling; the pilot (section 9), the
      two-validation check (7.3), and round 3's `ci` part are its working evidence.
- [ ] 10.9 Promotion, completing the design-promotion record:
      - `openspec/specs/change-workflow/spec.md` — written by the archive (10.11):
        "Each change is worked in its own clone" and "Each Helm validation is
        isolated in its change's namespace" added; "Implementation sections and
        sessions", "Validation observes a committed slice", "Triage of an
        implementation round", "An orchestrating session advances one change", and
        "Unattended runs are held to their step's permissions" modified. By hand:
        the Purpose paragraph gains clones, and "Evidence" gains
        `scripts/change_clone.py` (`make change-clone`, `make change-clone-remove`),
        `scripts/change_history.py` (`make change-history`),
        `scripts/change_namespace.py`, `scripts/validate_parallel.py` (`make
        validate-parallel`),
        `scripts/ci_evidence.py` (`make run-ci`, `make validate-ci`), and
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
        upgrade from zero, the advisory capacity figure, written only when measured,
        78 F2) and for the `ci` part (D15–D17: no publishing workflow dispatchable,
        the owed jobs judged, every other failure compared by test ID and exception
        type with a `dev` run the branch contains, and why); "Sections are slices,
        sessions are the owner's" for evidence owed by validation (D14, D18);
        "Pushing is guarded, never repaired" for each step committing and pushing
        its own work, why the steps once did not, and the branch as the guard
        against unfinished work, only `dev` protected (D8, D20 rules 1–5);
        "Restrictions bind unattended runs only" for a grant for one run, fresh or
        resumed, through `ALLOW` (D19); "The orchestrator relays and routes" for its
        workflow maintenance, the owner's instructions, merges of `dev`, and the
        conflict tiers (D8, D20 rule 6, D20.1–D20.3); a new "History lives in the
        owner's workspace" (D11); "Current limits" rewritten (one orchestrating
        session per change; the container per change, as 9.3 decided; side work
        chosen to stay clear of the critical-path goal's files, D9).
      - `docs/agents/change-workflow.md` — already written in sections 4, 8, 8A,
        and 8B;
        "Skills" gains `make change-clone`, `make change-clone-remove`, `make
        change-history`, and `make validate-parallel` (added by section 7); "The
        review directory" says where a cleaned-up change's
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
