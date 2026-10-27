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

Notes record final behaviour, material evidence, deferrals, and destinations. The
rationale behind each fix round is in `design.md`, under the decision or the
finding (such as "127 O2 / 128 R5") that raised it; what the fresh-context checks
raised and a section declined is under "Declined at the fresh-context compliance
checks", and the gaps left open under "Known gaps".

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
      Note: cloned with `git clone --no-checkout --origin workspace`, so the
      `workspace` remote exists from the first step and an unfinished clone has no
      index to misread as deletions. The branch is taken at its furthest point
      between the workspace's copy and `origin`'s, refused when they diverge (D6),
      checked out tracking `origin`'s branch, never the workspace's; the branch
      `git clone` made is deleted, and that settling reruns on every pass. Each pass
      fetches the workspace first. The clone's Git directory holds
      `change-clone.json` (change and branch, written once the branch is checked
      out) and the bootstrap's `change-bootstrap.json` (pid, log), `.log`, and
      `.status`; the bootstrap runs under `sh -c` in its own session. The settings
      link is made even before the workspace has a `settings.local.json`.
- [x] 1.2 Idempotence and refusals (D6, 17 F5): in a directory that is already a
      clone of the workspace, resume at the first step not done, never recloning;
      refuse, naming the directory and deleting nothing, a directory that is not a
      clone of the workspace, has another branch checked out, or has uncommitted
      changes. Rerunning restarts a failed bootstrap and leaves a running or
      succeeded one alone.
      Note: also refused, deleting nothing: another `--branch` than the clone
      records, the clone of another change, an `origin` not the workspace's, a
      `--from` naming nothing, a settings path that is not the link, a workspace
      with no `origin`, and `create` run in a clone. What is already in the clone is
      refused before anything is written; a diverged branch, a bad `--from`, and a
      settings path that is not the link are found after `origin` is added, leaving
      the clone unfinished for a rerun.
- [x] 1.3 `bootstrap_state(clone)` → `running` (recorded process alive),
      `succeeded` (status 0), `failed` (non-zero status, or a dead process with no
      status), or `absent`, with the log's path; and `clone_of(workspace, change)`
      → the clone's directory when it exists and holds the change's branch. Both
      are the computation's inputs (3.1), importable without side effects.
      Note: `workspace_of(checkout)` beside them names the workspace a clone's
      `workspace` remote points at, or None; the round view and the computation
      tell a clone from the workspace by it. Not guarded: a recorded pid reused by
      another process reads as `running`.
- [x] 1.4 `Makefile`: `make change-clone CHANGE=<change> [BRANCH=…] [FROM=…]`.
- [x] 1.5 Verification. Repository level (temporary workspace with a bare `origin`):
      a fresh clone has both remotes, the branch, the settings link, and a bootstrap
      record (the bootstrap command injected); an interrupted creation, each step
      left undone in turn, is finished without recloning; each refusal deletes
      nothing; a branch created from `--from`. Unit: the bootstrap's four states,
      a dead process with no status read as `failed`. `uv run --no-project --with
      pytest pytest -q scripts/tests/test_change_clone.py`; `make test`. No
      end-to-end scenario covers it.
      Evidence: `scripts/tests/test_change_clone.py`, 37 passed at the round-2
      fix — repository level (real Git, a workspace with a bare `origin`, the spawn
      injected): the fresh clone tracking nothing in the workspace; a branch at its
      furthest point, a diverged one refused then taken once reconciled, `--from`
      a workspace branch, `dev` from `origin` when the workspace's is behind;
      resumption after each step (a sentinel shows nothing was recloned); a failed
      bootstrap restarted, a running one and a complete clone left alone; every
      refusal of 1.2, each asserting what it leaves; the bootstrap's states read
      from state files with liveness injected; the real spawn recording output and
      status. Untested: the detached-`HEAD` wording, an unreadable `origin`, and
      the command line beyond its refusal (a success starts the real `make init`).
      `make check-packaging` and `make check-comment-hygiene`: passed. `make test`:
      passed but for `make -C helm test-render`, failing on a defect owned by
      `repair-helm-render-tests`; nothing under `helm/` changed. End-to-end: none.
      The bootstrap record is written by the `sh` supervisor itself, its own `$$`
      first, through a temporary file, so a rerun after an interruption reads it as
      started (52 F3); only a rerun reading the clone between spawn and that first
      act would start a second `make init`, which no rerun reaches (96 F1, D6).
      Left as limits: `--from` takes a branch or commit, not `origin/<branch>`;
      `make change-clone` does not check the change with `find_change.py`, since
      the change may exist only on the branch it starts from; a checkout killed
      after writing its index but before moving `HEAD` leaves the clone refused as
      on another branch, for the owner to delete; a custom branch checked out but
      not yet recorded is refused on a rerun without `--branch`. The furthest-point
      rule is promoted with D6 (10.9).

## 2. The round view in the owner's workspace

Delivers D2's view and `round-done`'s carry, and D3's removal of the view's push
and dispatch (requirement "Triage of an implementation round"). Touches
`scripts/round_view.py`, `scripts/change_workflow/wrapper.py`, the root `Makefile`,
`scripts/tests/test_round_view.py`, and `scripts/tests/test_change_workflow_wrapper.py`.

- [x] 2.1 The record of a run in progress (D2 step 2): the wrapper writes the run's
      process, step, and change into its checkout's Git directory as a run starts,
      and removes it once the run's line is written, an interrupt included;
      `runs_in_progress(root)` reads the live ones, a dead process counting as none.
      Note: in a new module, `scripts/change_workflow/running.py`, so the round view
      reads it without importing the harness: one file per run under
      `<git-dir>/change-runs/` (pid and a random suffix, so validation and a review
      side by side each have one), written aside and renamed, held by
      `recorded_run` around the whole turn and removed in its `finally`. Nothing is
      recorded outside a Git checkout. The review runner records its runs too.
      Also touched: `review.py`, the package docstring, the test fixtures,
      `test_change_workflow_review.py`, and `test_change_next_step.py`.
- [x] 2.2 `round_view.py start <change>` for a change whose clone holds its branch
      (1.3), run in the workspace: refuse a dirty workspace, naming the files; a run
      in progress there (2.1), naming it; another change's open view, naming the
      change; then fast-forward the workspace's branch from the clone's `workspace`
      remote counterpart (`git fetch <clone> <branch>`), refusing a diverged one;
      record where the workspace was (branch or detached commit); check out the
      branch and mixed-reset it, with `-N`, to the base read from the clone's latest
      `round` line (D2). The state records the clone, so `done` and refresh find it.
      Note: the base falls back, as in place, to the clone's latest triaged
      validation. A workspace branch that is not an ancestor of the clone's is
      refused; a missing one is created at the clone's commit, a checked-out one
      fast-forwarded with `merge --ff-only`. The state is written before the
      checkout moves. `round-done` refuses while a run is in progress; `start`
      refuses in a clone.
- [x] 2.3 Refresh (D2): `start` again for the change whose view is open moves the
      view to the branch's new head over the same base, after the same fetch;
      refuse while the workspace holds uncommitted edits or commits made during the
      view, naming them and `make round-done`.
      Note: with no edits (worktree differences plus untracked files), the move is
      `git reset --hard` to the new head, then the state, then the mixed reset to
      the base, so a failure leaves the state where the branch is. A head not
      descending from the view's, and a `BASE=` on a refresh, are refused; the same
      head leaves the view as it is. An in-place view is not refreshed (D2).
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
      Note: every commit is judged before any is made; replacements are built with
      `read-tree`, `update-index --index-info`, `write-tree`, and `commit-tree` in
      a private index, so the checkout's index, which holds the view, is untouched
      until the final mixed reset. Binary is Git's test (a NUL in a blob's first
      8000 bytes); a submodule is judged with symlinks. A text file the round
      changed must keep the head's mode and is refused when the commit deletes it.
      A commit whose replayed tree equals the previous one's is dropped and named.
      The carry applies to an in-place view too. These rules are in D2.
- [x] 2.5 The view of a change with no clone, whose branch is the workspace's own,
      keeps today's behaviour: the branch reset in place, the reading first (D2,
      D3). `round_view.py` no longer pushes or dispatches: `--no-e2e`, the
      `e2e-baseline` action, `E2E_BASELINES`, and `make round-e2e-baseline` are
      removed, and `make round-view` loses `NO_E2E` (D3). `check` refuses only in
      the checkout whose branch the view moved.
      Note: the in-place view now also refuses a run in progress and names a dirty
      worktree's files. `check` needed no change: the state lives in the Git
      directory of the checkout the view moved.
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
      Evidence: `scripts/tests/test_round_view.py`, repository level (real Git,
      runs injected): in place, the view and `done`, the base from the round line
      and the triaged validation, every refusal; every carrying case the task
      names, plus "commit all" with and without an edit, two commits oldest first,
      an edit inside a changed line, a symlink and a mode change, and a merge
      bringing in the round's head; from a clone, the view on the branch by name
      with the clone's `HEAD` and status unchanged, `done` returning to `dev`, a
      detached commit, and the branch, an owner's commit carried then pulled
      fast-forward, uncommitted edits keeping the workspace on the branch, and
      every refusal and refresh case of 2.2 and 2.3.
      `test_change_workflow_wrapper.py` (unit, runs directory injected): a record
      present while its run runs and gone after, an interrupted run's likewise, a
      dead process counting as none, none outside Git;
      `test_change_workflow_review.py`: a review's record. `uv run --no-project
      --with pytest pytest -q scripts/tests`: 1162 passed. `make check-packaging`
      and `make check-comment-hygiene`: passed. `make test`: passed but for `make
      -C helm test-render`, failing on a defect owned by
      `repair-helm-render-tests`; nothing under `helm/` changed. End-to-end: none.
      Before each move of the worktree — opening, refresh, return — the view
      refuses, moving nothing, when an ignored file sits at a path the target
      tracks and the current commit does not (52 F2); a return so blocked closes
      the view and leaves the workspace on the change's branch. A failed checkout
      on opening restores the branch ref it moved or deletes one it created (52
      F4), tested by holding `index.lock`. Section 4 rewrote the skills, guide, and
      step table that described the removed push and dispatch.

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
      has checked out (D2). Otherwise "checked out here" is `feat/<change>` or a
      branch the owner's decision in the log names (`branch_decisions`). Results:
      `{"step": "clone", "arguments": {CHANGE, BRANCH, FROM}}` and
      `{"step": "in-clone", "clone": <dir>}`. "Holds the records" is a non-empty
      `reviews/`. A change this checkout lacks stays `unclassified`; an archived
      change is `done` before any routing; in a clone of another change, the
      result is `owner`, naming the workspace.
- [x] 3.2 Bootstrap routing (D6): an incomplete clone names `clone`; while the
      bootstrap is `running`, design and planning steps are named and
      implementation and validation steps wait, the result saying so; `failed` is
      `owner`, an environmental failure naming its log and that `make change-clone`
      restarts it; `succeeded` routes as today. A change with no clone routes as
      today.
      Note: incomplete is a clone whose bootstrap is `absent`, or a directory
      `clone_of` rejects (killed before its checkout), routed `clone` with full
      arguments. While the bootstrap runs, a design or plan step is named in any
      phase (a confirmed return); every other step in implementation and closeout,
      triage, closeout, and archive cleanup included, is held as `{"step": "wait",
      "waits": <step>}` (D6). A failed bootstrap goes to the owner in every phase.
- [x] 3.3 The round of three records (D3): for a change in a clone, once a round's
      sections are committed, the result is `validate-and-review` together with the
      owner's reading — the session opens the view in the workspace and starts both
      in the clone — and triage is named only once the owner record, the review,
      and the validation exist. The view's state is read from the workspace through
      the clone's `workspace` remote, so an open view there holds triage and nothing
      else. A change without a clone keeps the reading first.
      Note: the reading rides on whichever of validation and review is missing, as
      `reading: true` with the `workspace`, while no owner record exists and no view
      is open; with both in and no owner record, the result is `round-view`; with
      the view open where triage would be named, `owner`, to save the answer and
      close the view. An earlier round's view still open while the current round is
      unread goes to the owner to close first. The delta scenario "The
      orchestrating session restarts during a round view" says so.
- [x] 3.4 The waiver after a return (36 R1): `note … orchestrator --next plan`,
      `by: owner`, naming no run, is accepted once the change is `in design` and the
      latest design run finished after a confirmed return; any other `next` other
      than `review` and `archive-cleanup` still names the run it resolves. `_design`
      honours that direction and names planning rather than a design review.
      Note: `note_orchestrator` takes the change's `status` from the index row;
      `redesigned_after_return(entries)` in `change_workflow/log.py` is the shared
      test. Planning is named once after the waiver: a later plan run that waits,
      or finished leaving the change in design, goes to the owner, never rerun.
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
      Evidence: `test_change_next_step.py`, unit with the location seams injected
      (`branch`, `workspace`, `clone`, `bootstrap`, `head`, `view`): every case the
      task names, plus `in-clone` with the workspace on the change's branch, an
      unknown change, a clone's view sending its change to the clone, another
      change's in-place view, a clone of another change, the bootstrap holding
      review and closeout but not a design step after a return, the view cases of
      3.3, and a plan run after the waiver going to the owner. Untested at this
      level: a directory `clone_of` rejects. Repository level in the same file
      (real Git, a clone by `change_clone.create`, a view by `round_view.start`):
      `in-clone` from the workspace, then in the clone the reading beside
      validation and review, `round-view`, and `owner` while the view is open.
      `test_change_workflow_log.py`, unit: the waiver accepted after a finished
      redesign and refused otherwise; the command line reading the status. `uv run
      --no-project --with pytest pytest -q scripts/tests`: 1201 passed. `make
      check-packaging` and `make check-comment-hygiene`: passed. `make test`: passed
      but for `make -C helm test-render`, failing on a defect owned by
      `repair-helm-render-tests`; nothing under `helm/` changed. End-to-end: none.
      Handoff, taken up in section 4: the orchestrating skill's results `clone`,
      `in-clone`, `wait`, `reading`, and `workspace`; `change-plan`'s entry check
      accepting the orchestrator's waiver line with the status `in design`.

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
      Note: a "Where the change is worked" section routes `clone`, `in-clone`,
      `wait`, and the `owner` results; after `in-clone` every command runs in the
      clone, only `make change-clone` and the view in the workspace. For a round
      in a clone the session starts validation and the review before opening the
      view, so a view the workspace refuses holds nothing up. The waiver's ledger
      line (`"review": "plan"`) goes into the clone's ledger for planning to
      commit. The pilot merge is written generally, for any branch whose tooling
      later rounds need, conflicts handled per D20.2. Workflow maintenance is
      committed only in a clone, between steps, and never between a round's
      sections and its triage, where a stopped run is granted its rule for one run
      instead (D19); for a change in the workspace the owner commits it.
- [x] 4.2 The committing skills push: `change-design` commits its recorded design
      once the owner says it is settled; `change-design`, `change-plan`,
      `change-implement`, `change-triage`, `change-closeout`, and
      `change-archive-cleanup` push each commit through `make push-branch` (D8).
      `change-triage` pulls the owner's commits with `git pull --ff-only workspace
      feat/<change>`, refusing anything else, and identifies them as the commits
      between the round's head and what it pulled; it scopes the round from the
      `round` line's base, as the review does (D2, D3). `change-validate` dispatches
      the pipeline itself and no longer reads a baseline the view recorded (D3).
      Note: `change-plan` also commits its plan, and its entry check accepts the
      orchestrator's waiver line with the status still `in design`. A triage of
      every kind commits and pushes what it edited that no fix commit holds (52 F1,
      D8). Triage recognizes a clone by its `.git/config` naming a `workspace`
      remote, since no rule allows `git remote` or `git config`; it pulls the
      owner's commits before presenting them, and undoes a rejected one by edits
      among the fixes, since no rule allows `git revert`. `change-validate` says a
      view in the workspace does not stop a clone's validation. The push guard's
      refusal says "a step pushes".
- [x] 4.3 Every step skill's "Running unattended" section gains: run Git in the
      current checkout, never with `-C` (D8, 36 R2).
      Note: `change-review`, with no bulleted section, takes it in its paragraph.
- [x] 4.4 `.claude/change-steps.toml` (the orchestrator's, as the preamble says): `make
      push-branch` moves from the deny to the allow list of design, plan, triage,
      implement, closeout, and archive cleanup; design and plan gain `git add *`
      and `git commit *`; triage and implement gain `git pull --ff-only workspace *`;
      the round view stays denied to every step (D8).
      Note: the orchestrator's edit, committed with this section, also drops
      validation's `make round-e2e-baseline`. Known limit: `git pull --ff-only
      workspace *` also matches a trailing option such as `--rebase`; the rule is
      unnarrowed.
- [x] 4.5 `docs/agents/change-workflow.md`: a change worked in its own clone —
      where clones live, `make change-clone` and the bootstrap's states, steps run
      with `make -C <clone>`, taking a step over, reading a round in the workspace
      and what `round-done` does with commits made during the view and what it
      refuses; working a change in the workspace without a clone; moving a change
      already under way into a clone by hand: settle any run waiting on an answer in
      the workspace, merge `dev` into its branch, `make change-clone`, move
      `reviews/` and the evidence its records name into the clone and check the
      copies are identical (D6, 37 F1).
      Done: "A change in its own clone", with the skills table, commits, taking a
      step over, the step table's maintenance, and the review section's reading
      updated; the move by hand checks the copies with `diff -r` before removing
      the workspace's. History and clone removal followed in section 8.
- [x] 4.6 Verification: `make check-agent-skills`; `make check-change
      CHANGE=parallel-change-workflows`; `uv run --no-project --with pytest pytest -q
      scripts/tests/test_change_workflow_steps.py`, extended with the table's new
      allows and denies (unit); a fresh-context read of each changed skill against
      D2, D3, D6, D8 and the delta's orchestrating-session and permissions
      requirements, recording what it found; `make test`. Validated in the owner's
      workspace on the existing Helm part. No end-to-end scenario covers it.
      Evidence: `scripts/tests/test_change_workflow_steps.py`, unit over the real
      table, 35 passed: each committing step may `make push-branch` and no other
      push, validation `make push-branch` and `make run-e2e`, the review none;
      `git push`, `FORCE=1`, and `git -C … push` denied; only committing steps may
      `git add`/`git commit`; only triage and implementation may pull
      `--ff-only workspace`; no step may run `git -C`. Two fresh-context reads of
      the skills; their fixes are in 4.1 and 4.2. `make check-agent-skills`,
      `make check-comment-hygiene`, `make check-packaging`: passed. `make test`:
      every suite passed but `make -C helm test-render`, failing on a defect owned
      elsewhere (`repair-helm-render-tests`, 53 V1); nothing under `helm/`
      changed. End-to-end: none.
      Round 1 triage (52 F1–F4): once a pre-closeout review's triage has run, a
      `HEAD` differing from the validated commit only under `openspec/` and
      `docs/` is cleared (D8) — `change_workflow/records.py` (`is_record`,
      `is_documentation`, `validation_problem(exempt=)`), the computation, the
      review runner, `change-closeout`'s entry check, and the delta (a MODIFIED
      "The next step is computed from the files"); an implementation triage's
      document commit is still validated. Evidence, unit or repository level:
      `test_change_next_step.py` (document commits after a pre-closeout triage to
      closeout unvalidated, with code to validation, an implementation triage's
      validated); `test_change_workflow_review.py` (the next pre-closeout review
      admitted over a document commit only after a triaged one);
      `test_round_view.py` (52 F2, F4: openings, refresh, and return refused over
      an ignored file in the way; a failed checkout restoring the branch);
      `test_change_clone.py` (52 F3: the spawn recording itself). `uv run
      --no-project --with pytest pytest -q scripts/tests`: 1221 passed;
      `make check-packaging`, `make check-comment-hygiene`, `make
      check-agent-skills`: passed; `make test` as above. A fresh-context check of
      the diff found no breach of the guidance.
      Handoff: the permanent spec and architecture describe validation's single
      push and the reading first until closeout (10.9).

## 5. Per-change image tags and namespaces in the build and Helm targets

Delivers D4's images, namespace naming, Secrets, and manual access (requirement
"Each Helm validation is isolated in its change's namespace"). Touches the root
`Makefile`'s build targets, `core/registry/Makefile`,
`domains/vms/storefront/Makefile`, `provisioning/compute/service/Makefile`,
`dev-env/Makefile`, `e2e-tests/Makefile`, `helm/Makefile`, a new
`scripts/change_namespace.py`, `helm/tests/`, and `scripts/tests/`.

Round 2's Helm evidence needed `make -C helm test-render` to pass, which validation
53 found failing on `dev`'s values schema (53 V1); `repair-helm-render-tests` fixed
it, merged in from `dev` before round 2 was validated.

- [x] 5.1 `IMAGE_SUFFIX`, empty by default, appended to every image tag the build
      targets write — `build`, `build-dev`, `build-seller`, and each image target the
      root `Makefile` and the subproject Makefiles define — so `make build-dev
      IMAGE_SUFFIX=-<change>` builds `arkhai:storefront-<change>` and its siblings;
      compose, the pipeline lanes, and the owner's own deployments keep bare tags
      (D4).
      Note: the five delegating root targets pass `IMAGE_SUFFIX=$(IMAGE_SUFFIX)` to
      `cd <project> && make build` explicitly. A suffixed build writes no commit
      tag (D4); a bare build still writes `arkhai:<tag>-<sha>`, which
      `push-images` reads. The e2e-tests targets that run the image keep the bare
      tag, as the lanes do.
- [x] 5.2 `scripts/change_namespace.py <change>` prints `validate-<change>`, cut to 63
      characters with a short hash of the full name appended when longer; every
      `helm/Makefile` target that takes `NAMESPACE=` also takes `CHANGE=`, deriving
      the namespace through it (D4).
      Note: the hash is the first 8 hex digits of the full name's SHA-256, after a
      cut to 54 characters with a trailing hyphen dropped; a name that is not a
      change name is refused, exit 2. `helm/Makefile` derives `NAMESPACE` once
      from `CHANGE`, refusing both given and a `CHANGE` the script refuses. A
      step's own `CHANGE=` reaches every `make -C helm` through `MAKEFLAGS`, so
      `validate_slice.py` passes `CHANGE=` (empty for `default`) on every call
      (section 6), and tests of these targets drop `MAKEFLAGS` and `CHANGE`.
- [x] 5.3 `make -C helm forward CHANGE=<change>` forwards that namespace on the usual
      ports, a second forward failing on bind and naming the port; `make -C helm
      resume CHANGE=<change>` scales its workloads back up; `topology-secrets` runs
      for a derived namespace (D4).
      Note: forwarding is `helm/scripts/port-forward.sh` (`start`, `stop`), run
      with `bash`, since the step that added it cannot set a mode bit without the
      worktree differing from the commit. `start` names every port that fails to
      bind, with kubectl's error, and stops the forwards it started; `stop` waits
      up to 15 s and fails over a forward that outlives it, keeping its PID for
      the next `unforward`, and names a stale PID file to remove. `resume` scales
      each Deployment and StatefulSet of every release in the namespace to its
      installed manifest's replicas, rendering nothing from the checkout.
      `topology-secrets.sh` creates its namespace when absent.
- [x] 5.4 The image overlay: a function that writes a values overlay naming every
      image tag `helm/values.yaml` sets with the suffix; a render test in
      `helm/tests/` holds the overlay to every image the chart renders, so an image
      added later cannot stay bare (D4).
      Note: `change_namespace.image_overlay` and `write_image_overlay` (JSON, read
      by Helm as YAML; `--image-overlay <path>`) suffix the `tag` of every mapping
      named `arkhai`, by its path of keys, leaving third-party images' tags,
      skipping block scalars, and refusing a tag inside a list. `helm/values.yaml`
      states the two image settings it had left to subchart defaults
      (`bare-metal-storefront.image`, `validate-contracts.integrationTests`), since
      the overlay names only what that file sets; the render test found the
      second.
- [x] 5.5 Verification. Unit: the namespace name for a short, a 63-character, and a
      longer change, the hash stable; `make -n` of each build target with and
      without `IMAGE_SUFFIX` and of each Helm target with `CHANGE=`. Chart render
      tests (`make -C helm test-render`, `helm/tests/`): the overlay over every
      rendered image. `uv run --no-project --with pytest pytest -q scripts/tests`;
      `make test`; `make test-deployment-packaging`. No end-to-end scenario covers
      it.
      Evidence: `scripts/tests/test_change_namespace.py`, unit, 21 passed (names
      short, exactly 63, and longer, hashed and stable, a shared 60-character
      prefix kept apart, refusals; the overlay's tags by path, a list's refused).
      `scripts/tests/test_change_build_and_helm_targets.py`, 43 passed: through
      `make -n` over the real Makefiles, every image target bare and suffixed, the
      composite targets passing the suffix, `CHANGE=` naming `validate-<change>`
      on thirteen namespaced targets and `topology-secrets` and the two
      refusals; with fake `kubectl`, `helm`, and `cast` on `PATH`, `forward` and
      `unforward`, held ports named, `resume` over two releases and its failures,
      and `topology-secrets` creating the namespace only when absent. Untested: a
      forward that never listens within the wait, and real kubectl's bind error
      text. `helm/tests/test_image_overlay.py`, chart render, 3 passed: the local,
      API-credits, and bare-metal releases render only suffixed `arkhai` images,
      and failed with a tag removed from `helm/values.yaml`. `uv run --no-project
      --with pytest pytest -q scripts/tests`: 1285 passed; `make
      check-packaging`: passed. `make test`, its last suite
      `test-deployment-packaging`: every suite passed but `make -C helm
      test-render`'s thirteen render tests failing on the defect owned by
      `repair-helm-render-tests` (53 V1, 64 V1); nothing under `helm/` but the
      overlay's own test changed, and it passed. Two fresh-context checks; their
      fixes are in the notes above. End-to-end: none; the Helm scenarios first run
      in the change's namespace in section 6.
      Handoff, taken by section 6: `validate_slice.py` passes `CHANGE=` on every
      `make -C helm` call, layers the overlay through `deploy`'s `EXTRA_VALUES`,
      and drops the forward and port steps.

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
      Note: one flow for both namespaces. Without `--change` the part runs in
      `default` on bare tags, with no image overlay and the retained-volume
      refusal first. With it, the part runs in `change_namespace.namespace(change)`.
      `make validate-helm` passes `--change` whenever `CHANGE` is set, so `make
      validate CHANGE=<change>` reaches the namespace through `MAKEFLAGS`. Every
      `make -C helm` call names its namespace (`CHANGE=<change>`, or `CHANGE=
      NAMESPACE=default`), so an inherited `NAMESPACE` cannot redirect it. Every
      workload, pod, resource, and memory read is scoped to the release
      (`app.kubernetes.io/instance=<RELEASE>`), so a `default` run leaves an
      owner's other release there alone. The replacement runs in this order: up
      workloads scaled to zero by name; the release's pods deleted (its test pods
      outlive their runs and mount the buyer-profile volume); its labelled claims
      and the test volumes deleted and waited for; `topology-secrets`; then `make
      -C helm deploy` with `local-values.yaml`, the attempt's `images.json`, and
      `scenarios.json`. The preflight no longer runs `check-local-secrets`. An
      upgrade the chart refuses is told by `field is immutable` in its log: a
      warning naming the line, `undeploy`, the release's own volumes waited for
      again, then `install`. Every deploy is followed by `make -C helm resume
      RESUME_RELEASES=<RELEASE>` and each workload's `rollout status`, since a
      release under server-side apply may not restore a count scaled outside it.
      `RESUME_RELEASES` keeps a `default` run from bringing up an owner's other
      release. Port-forwards are gone from the part.
- [x] 6.2 Scenarios as a pod in the namespace from the change's `e2e-tests` image,
      with the release's `test-config` ConfigMap's `helm` profile as the
      `e2e-deal-test` pod has it, selecting `HELM_SCENARIOS`; its log and exit
      status collected into the attempt's directory. No port-forward and no
      localhost port is used (D4).
      Note: a Helm test hook in the e2e-tests chart,
      `templates/tests/e2e-scenarios-test.yaml` (`<release>-e2e-tests-e2e-scenarios`),
      rendered only when `scenarios.markers` (a string) is set. Its environment,
      mounts, and volumes copy the deal test's, and a render test holds the two
      equal. Validation runs `helm test <release> --filter name=<pod> --timeout
      30m`, keeping `scenarios.log`, `scenarios.exit`, and `summary.json`'s
      `evidence.scenarios`. The step passes only on the pod's own exit status of
      0, since `helm test` passes when its filter matches no test. A pod with no
      exit status, as after a timeout, is deleted. Every read is bounded (120 s),
      so no hung read holds the scale-down. After a `default` run the owner's
      release keeps `scenarios.markers`, so its next `helm test` also runs the
      pod.
- [x] 6.3 After the scenarios, always: the namespace's peak memory in
      `summary.json`, every pod's log and the namespace's events copied into the
      attempt's directory, the other namespaces' replica counts and the rendered
      requests and limits beside the previous validation's, then the namespace's
      workloads scaled to zero, objects and volumes kept (D4, 26 F2).
      Note: runs in a `finally` once the release has been touched. When the
      checkout is no longer the commit, it keeps no evidence and only scales
      down. A failed evidence command or read is a warning, its key left empty.
      "Peak" is the largest sampled usage of the release, summed over its
      containers from `metrics.k8s.io`. It is sampled once the release is ready,
      every 15 s during `helm test`, and after, giving `memory.peak_bytes` and
      `samples_bytes`; section 8.4 records it as the figure. The evidence kept:
      `pods/<pod>.log` and `.previous.log`; `pods.json` (`OOMKilled` shows
      there); `events.log`; `node-events.log`;
      `evidence.other_namespaces_at_start` and `other_namespaces`, which bracket
      the run rather than catching the moment of failure; and `resources.txt`,
      compared with the latest earlier validation in the same namespace
      (`evidence.resources.previous`, `changed`).
- [x] 6.4 The capacity preflight (D4, 17 F3): `helm/validation-capacity.toml` holds
      the memory one release needs, when, and from which change it was measured,
      with a reader and writer in `validate_slice.py`; the preflight counts the
      namespaces with workloads above zero replicas, adds its own, and compares that
      many times the figure with the node's allocatable memory, a deployment that
      would not fit failing the part as environmental with its remedy; it warns and
      goes on with no figure, and when `metrics-server` is missing. It reserves
      nothing. The file starts with no figure.
      Note: `read_capacity` and `write_capacity` handle a `[release]` table of
      `memory_bytes`, `measured_at`, and `change`, with a header saying a merge
      conflict keeps the later `measured_at`. A figure that is incomplete or not
      positive is refused on read, and one not positive on write. The namespaces
      counted are those, other than the run's own, holding a workload of the
      validation release above zero, so system namespaces are not counted.
      Allocatable memory is summed over nodes. The failure's detail begins
      `environmental:`, names the running namespaces, and gives the remedy
      (`deployments,statefulsets --selector
      app.kubernetes.io/instance=<release>`). `metrics-server` is detected by
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
      Evidence: `scripts/tests/test_validate_slice.py` is orchestration against a
      fake at the subprocess boundary (integration in `TESTING.md`'s terms), with
      a fake checkout, daemon, and cluster. It covers:
      - for a change, every command in order, every `kubectl`, `helm`, and
        `make -C helm` call naming the change's namespace (the nodes' events
        apart), and another namespace's workload untouched;
      - in `default`, bare tags, and an owner's other release neither scaled,
        resumed, nor listed;
      - a crashed run scaled down before the volumes are deleted, the waits, and
        the refused upgrade's fallback;
      - the scenario pod's evidence, with a non-zero, missing, or unreadable exit
        status failing the step;
      - evidence kept and the release scaled down after failures and unexpected
        errors, and a commit moved mid-run keeping no evidence yet scaling down;
      - memory sampled during the scenario run and the peak taken;
      - the preflight's refusals, warnings, pass, and environmental failure;
      - the capacity file's reader and writer, and the retained-volume refusal in
        `default` alone.
      Not shown at this level: the `MAKEFLAGS` route, which `helm/Makefile`'s
      tests show (section 5). `helm/tests/test_scenario_pod.py` (chart render
      test, 4 passed) checks the pod and its schema. `uv run --no-project --with
      pytest pytest -q scripts/tests`: 1326 passed. `make check-packaging`:
      passed. `make test`: every suite passed but `make -C helm test-render`,
      which failed on a defect owned by `repair-helm-render-tests`; no render test
      of this section's failed. Three fresh-context checks' fixes are in the
      behaviour above; what they raised and the section declined is in
      `design.md`, "Declined at the fresh-context compliance checks".
      System, on the development cluster (`docker-desktop`): `make validate-helm
      CHANGE=parallel-change-workflows` at 8e6494f51, once the render fix was
      merged from `dev`, run by this step on the owner's word. Attempt 1 passed:
      - namespace `validate-parallel-change-workflows`;
      - pods on `arkhai:{dev-env,registry,storefront,compute-provisioning,e2e-tests}-parallel-change-workflows`;
      - test-render passed with no skip;
      - the pods, the claims, and `arkhai-buyer-profiles` were deleted and gone,
        the Secrets created, and the deploy (a first install, no refusal),
        `resume`, and four rollouts passed;
      - the scenario pod `arkhai-node-operator-e2e-tests-e2e-scenarios`, on the
        `helm` and `e2e-secret` profiles and reaching the chain by its in-cluster
        name, passed 13 tests and exited 0;
      - the evidence was kept and the Deployments scaled to zero, while the
        owner's release in `default` stayed up and untouched.
      The `metrics` and `capacity` warnings fired, since the cluster has no
      metrics source and no figure is recorded. Validation 97 at 19fb8f584 (96
      F2) showed the upgrade over the namespace left at zero: revision 2, every
      pod new on its suffixed image, 13 tests passed, scaled to zero again. The
      refused-upgrade fallback has not occurred on a real cluster, and no memory
      sample has been taken. End to end: `contracts` and
      `e2e_alkahest_escrow_codecs` in the change's namespace.
      Handoff, since done: the skill's rewrite (7.1); the two-validation check
      reading `summary.json` and `images.json` (7.2); the figure written from
      `memory.peak_bytes` (8.4); the architecture's "Validation observes a
      committed slice" rewritten at closeout (10.9). The permanent requirement's
      "port-forwards", an example of what validation may still stop, is modified
      by the delta.

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
      Note: the skill runs `make validate-helm CHANGE=<change>` in the
      background, waiting on its result or `ERROR:` line. It describes section
      6's part as it is, and says validation controls its change's namespace and
      tags and never another change's. Step 3 lists what a Helm attempt keeps.
      Step 4's "The Helm part's memory" reads the three classes from those
      files:
      - a pod unscheduled or evicted for memory while another change's release is
        up is environmental, whatever the resources, with a resource change named
        beside the remedy, as the delta scenario "Two validations pass the
        preflight together" requires;
      - `OOMKilled` counts as the container's own limit only with that limit in
        `resources.txt` and no node memory pressure or system kill;
      - anything else is of unknown cause.
      Node events confirm the classes but are not required. The owner's release
      in `default` is not another change's. Every warning step is listed with
      its meaning, and the capacity step's `environmental:` detail is read as an
      environmental failure. The record's `## Helm` names the namespace, the
      scenario pod, the peak memory, and the warnings.
- [x] 7.2 `scripts/validate_parallel.py <clone> <clone>` (`make
      validate-parallel`; planned as `check_parallel_validation.py` and `make
      check-parallel-validation`): runs both clones' Helm parts at the same moment on
      the development cluster and reports, from their summaries and the cluster,
      separate namespaces, tags, and scenario pods, and that neither's release,
      volumes, or pods were touched by the other (D9).
      Note: renamed because it deploys (D9). Run as `make validate-parallel
      CLONES="<clone> <clone>" [HELM_CONTEXT=…]`. The two must be clones of
      different changes, each with a succeeded bootstrap. Both `make -C <clone>
      validate-helm CHANGE=<change>` runs start before either is waited for, with
      `MAKEFLAGS` and `CHANGE` removed from their environment. Six checks follow,
      each failing alone on a read it cannot make:
      - `together`: the runs overlapped, and whether their scenario pods did;
      - `results`: each part passed, else its failed steps or its log's end;
      - `namespaces`: each is the one its change derives, and the two differ;
      - `tags`: the overlays share no tag, and each run's `arkhai` pods are on its
        own;
      - `scenario pods`: each in its own namespace, on its own image, exit 0;
      - `untouched`: in each namespace, one Helm revision since the check started,
        the release's labelled volumes and pods made within its own run, none on
        the other's images, every mounted claim present, and workloads at zero. A
        namespace whose own part failed is not judged, and fails the check.
      Every cluster read names `HELM_CONTEXT`. The cluster is read only after both
      runs, so a disturbance that left nothing behind is not shown, such as an
      uninstall and install by the other run. That each run's commands name only
      its namespace is `test_validate_slice.py`'s evidence. Output goes to
      `<change>.log` and `report.json` under
      `.snapshot/parallel-validation/<UTC time>/`: exit 0 when every check
      passes, 1 otherwise, 2 on a refusal. Triage's row in the step table denies
      `make validate-parallel*`, which would otherwise reach two changes'
      namespaces through `make validate-*`.
- [x] 7.3 Verification. Unit: 7.2's report over fake summaries and cluster reads,
      including a run that touched the other's namespace. System: one run of `make
      validate-parallel` (planned as `check-parallel-validation`, renamed in 7.2)
      over two clones on the development cluster,
      recorded here. A fresh-context read of `change-validate` against D4 and the
      delta's Helm requirement. `make check-agent-skills`; `make test`. End to end:
      the Helm scenarios of 6.5, in both namespaces at once.
      Evidence: `scripts/tests/test_validate_parallel.py` is integration, with
      the launcher and cluster reader injected at the process boundary and the
      clock and clone lookup as controls. It covers:
      - two isolated runs passing all six checks, every read naming the context,
        and both runs launched before either is waited for;
      - an unlaunchable run reported beside the other;
      - six disturbances, each failing `untouched` alone for its namespace: four
        touches by the other run and two leftovers;
      - another release's objects in the namespace not judged;
      - unreadable or malformed history, release, and pod statuses failing only
        the check that needs them;
      - shared or foreign tags, a failed part, and failing scenario pods;
      - the command line's refusals (exit 2) and a run's environment free of
        `MAKEFLAGS` and `CHANGE`;
      - over real Git, which clones are accepted.
      `uv run --no-project --with pytest pytest -q scripts/tests`: 1382 passed.
      `make check-agent-skills`, `make check-comment-hygiene`, and `make
      check-packaging`: passed. `make test` passed every suite, `make -C helm
      test-render` included (Helm v4.3.0, no skip), after a first run met a
      `.dist` wheel another branch left. That cause was environmental: the lock
      was put back as committed and the wheelhouse rebuilt.
      The fresh-context read of `change-validate` found no instruction that
      touches another change's namespace. Its findings are fixed in 7.1's note:
      the classification order and its evidence, every warning listed, the run
      in the background, and the capacity remedy scoped to the release's selector
      in both the skill and `validate_slice.py`. The diff checks' fixes are in
      7.2's note. What they declined is in `design.md`.
      The bootstrap in a fresh clone: on the owner's word, the orchestrating
      session cloned the pilot and `resolve-compute-family-findings` from this
      branch. Both bootstraps failed at `init-buyer`, because a fresh `.dist` held
      only `dist-domains`' wheels, where the workspace had relied on wheels
      earlier builds left. Fixed: `init-buyer`, `init-storefront`, and
      `init-arkhai-core-registry` build `dist-ci` first.
      `scripts/tests/test_init_targets.py` (integration through `make -n`) shows
      each builds every wheel its lock installs from `.dist`. Both bootstraps,
      rerun at 297c64fa1, exited 0.
      System, attempt 1 (`.snapshot/parallel-validation/20261022T070836Z/`): both
      parts failed at `test-render` on the skipped bare-metal loader check, before
      touching a release. The check reported it correctly. Cause: `make init`
      never created the bare-metal storefront's environment. Fixed: `make init`
      gains `init-bare-metal-storefront`, and `validate_slice.py`'s preflight
      checks both loader environments, naming the target that creates each, and
      reinstalls them from the commit's wheels before rendering.
      `test_init_targets.py` (5 passed) and `test_validate_slice.py` (77 passed)
      cover it.
      System, attempt 2 on `docker-desktop`, both clones at b1c1e044d after `make
      init-bare-metal-storefront`: passed every check
      (`.snapshot/parallel-validation/20261022T072048Z/`, exit 0):
      - `together`: the runs went 07:20:48 to 07:22:58 and to 07:22:59 UTC, with
        the scenario pods running together;
      - `results`: each part's attempt 1 passed;
      - `namespaces`: `validate-seed-default-pool-at-runtime` and
        `validate-resolve-compute-family-findings`;
      - `tags`: each run on its own `arkhai:{compute-provisioning,dev-env,e2e-tests,registry,storefront}-<change>`,
        the overlays sharing none;
      - `scenario pods`: `arkhai-node-operator-e2e-tests-e2e-scenarios` in each
        namespace on its own image, exit 0, 13 tests passed;
      - `untouched`: one revision of `arkhai-node-operator` in each, read from
        real Helm 4.3 history.
      Both deploys were first installs, and the only warnings were `metrics` and
      `capacity`. This change, worked in the workspace, could not be one of the
      two clones. End to end: `contracts` and `e2e_alkahest_escrow_codecs` in both
      namespaces at once, by this run; no pipeline scenario exercises the check or
      the skill. Left to closeout: `TESTING.md`'s pointer to the bare-metal
      storefront's environment, which in a fresh checkout needs the wheelhouse
      first (10.9); `helm/scripts/test-render.sh`'s comment naming `make -C
      domains/bare_metal/storefront init` is code, and stays.

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
      Note: the named evidence is read from the files directly in `reviews/` — a
      cited `.snapshot/validation/<dir>` or `.snapshot/e2e-logs/<run>` path, a
      validation record's `**Commit:**` (its first twelve characters) and
      `**Pipeline:** run <id>` — never from transcripts, which cite whatever a
      session read. Named evidence the clone lacks is reported, not refused. Only
      regular files are copied, a link refused and named; each is written aside and
      renamed, so no reader finds a half-copy. A refused file does not stop the
      others; the command exits 1 naming each. A change not yet archived is refused.
- [x] 8.2 `find_change.py --records <change>`: the change's records in the checkout,
      then in the workspace through the `workspace` remote; every skill that reads
      another change's or an earlier change's records uses it (D11).
      Note: the records are the directory holding `reviews/`, so the workspace's
      archive copy is found beside the change's active directory; the workspace's
      is printed as an absolute path. `workspace_of` lives in `find_change.py`,
      imported by `change_clone.py` and `change_history.py`, since clone removal
      imports the history script and the two would otherwise import each other.
      Design, planning, the review, triage, and closeout find other changes'
      records with it; the orchestrating skill says where a done change's history
      went and that clone removal is the owner's.
- [x] 8.3 `scripts/change_clone.py remove <change>` (`make change-clone-remove
      CHANGE=`), run by the owner in the workspace: run 8.1 first; refuse, deleting
      nothing and naming what is missing, unless every file of the clone's
      `reviews/` and named evidence is in the workspace with identical contents, the
      branch is merged into `origin/dev`, and the clone has no commit `origin` lacks
      and no uncommitted change (D6).
      Note: also refused, before any copy, a run in progress in the clone and a
      running bootstrap; after it, a stash (a commit `origin` lacks that no branch
      holds). `origin` is fetched with prune before the merge and unpushed checks. A
      refusal prints the copy's report beside the problems. Named evidence the clone
      does not hold is named and does not refuse removal (114 F1, D6).
- [x] 8.4 Teardown and the figure: `make -C helm teardown CHANGE=<change>` deletes the
      change's namespace and its `-<change>` images; archive cleanup writes the
      figure from the change's latest validation's `summary.json` into
      `helm/validation-capacity.toml` with when and from which change, through the
      writer of 6.4, when that validation measured memory; when its `memory` is
      empty, it writes nothing, leaves any recorded figure as it is, and reports
      that it recorded none (D4, 37 F3, 78 F2; replanned against the reviewed
      design: the figure is conditional on a measurement).
      Note: teardown deletes the namespace in `HELM_CONTEXT` (`docker-desktop` by
      default), whatever context is current, and removes each image
      `change_namespace.py <change> --images` lists, failing after trying the rest
      when one cannot be removed; it refuses without `CHANGE`, so never deletes
      `default`. The list is exactly the tags `make build-dev` writes with the
      suffix (`BUILT_IMAGES`, held to the build by a test), not every tag ending in
      it, which would take the images of a change whose name ends in this one's.
      The figure is written by `make record-capacity CHANGE=` (`validate_slice.py
      capacity --change`), on the owner's word in place of an `Edit` rule, since
      archive cleanup's rules run no script (D8): it reads the latest
      `NN-validation.md`'s commit and that commit's last Helm attempt and writes
      `memory.peak_bytes` with `measured_at` and the change, or writes nothing and
      says why (no record, no Helm part, no measurement). The Helm part records
      `memory.measured_at`, its last sample's time; a summary without it is dated
      by the file.
- [x] 8.5 `change-archive-cleanup`: after its commit and the pull-request draft,
      write the capacity figure when the latest validation measured one and commit
      it, tear the namespace and images down, push, then run `make change-history`
      as its last act; with no measurement, its report and the draft say that no
      figure was recorded, for want of a metrics source; the draft's notes say
      that a conflict over `helm/validation-capacity.toml` keeps the later recorded
      time (D4, D11, 37 F3, 78 F2; replanned likewise). `docs/agents/change-workflow.md` and `AGENTS.md`'s
      "Change workflow" say the owner's workspace holds the history of every
      cleaned-up change, and the guide gains clone removal.
      Note: the skill's order is the index commit and its push (5), the draft (6),
      `make record-capacity` and its commit, the report giving the target's reason
      (7), teardown, a failure reported with its rerun (8), the figure commit's push
      (9), and `make change-history` last (10), only for a change whose clone has a
      `workspace` remote. The push stays at step 5 so a run dying after the index
      commit leaves nothing unpushed; a rerun on a row already `archived` goes on
      from step 7, appending to the draft rather than rewriting it, which the copy
      could not then extend. A refused file is reported and the step still
      finishes. Written: the guide's "History and removal" under "A change in its
      own clone", its table row and review-directory paragraph, and `AGENTS.md`'s
      "Change workflow".
- [x] 8.6 `.claude/change-steps.toml` (the orchestrator's, as the preamble says): archive
      cleanup gains `make change-history*`, `make -C helm teardown*`, and
      `Edit(helm/validation-capacity.toml)`; every step gains `python3
      scripts/find_change.py --records *` (D8).
      Correction, on the owner's word (8.4): archive cleanup gains `make
      record-capacity*` in place of `Edit(helm/validation-capacity.toml)`, committed
      with this section. Left for the orchestrator: the preamble's permissions
      sentence and the archive-cleanup row's comment; the `--records` rule is
      already covered by `Bash(python3 scripts/find_change.py*)`; `make -C helm
      teardown*` also admits a `HELM_CONTEXT=` naming another context.
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
      Evidence: `scripts/tests/test_change_history.py`, 16 passed, repository level
      (real Git, a workspace with a bare `origin`, a clone from
      `change_clone.create`): the first copy of records and named evidence; a
      second extending what grew and adding a record; conflicting files refused,
      the rest copied; a directory-for-file and links refused; an unarchived change
      refused; `--records` finding the clone's, then the workspace's, and a
      cleaned-up change's from another clone. `test_find_change.py`, 22 passed,
      unit. `test_change_clone.py`, 55 passed, repository level: removal after the
      copy; each refusal of 8.3, the clone kept; and (114 F1) removal going on over
      evidence held nowhere, the report naming it. `test_change_build_and_helm_targets.py`,
      integration through the real `helm/Makefile` with fake `kubectl` and
      `docker`: teardown's namespace and images, its context, its failure, its
      refusal without `CHANGE`, and the image list equal to `make build-dev`'s
      suffixed tags. `test_change_namespace.py`, 23 passed, unit. `test_validate_slice.py`,
      unit: the figure from the latest record, nothing written for each reason,
      `measured_at`. Untested: the aside copy's partial-file protection beyond no
      aside file left, and `rmtree` failing. `uv run --no-project --with pytest
      pytest -q scripts/tests`: 1442 passed; `make test`: passed, `make -C helm
      test-render` included; `make check-packaging`, `make check-agent-skills`,
      `make check-comment-hygiene`: passed. Two fresh-context checks' findings were
      fixed in the section. End to end: none — no scenario exercises the history
      copy, removal, the figure, or teardown; the pilot's archive cleanup is their
      working evidence (9.1), and clone removal, which follows the pilot's merge,
      rests on these tests.
      Handoff: whether an unattended step can read the absolute workspace path
      `--records` prints was unverified here; the pilot showed Read, Glob, and Grep
      can and Bash cannot (9.1, Risks).

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
      Note: `DISPATCHABLE`; the ID printed as `CI_AFTER_RUN=<id>`, 0 when the
      branch has none; a refusal runs nothing and exits 2; a detached `HEAD` is
      refused. `make run-ci` requires `make round-view-closed`, as `make run-e2e`
      does.
- [x] 8A.2 The fetch: `scripts/fetch-e2e-logs.py --workflow <file>` downloads the
      run's whole log (`gh run view --log`) and, for a workflow other than
      `e2e.yml`, asks for none of the end-to-end lanes' artifacts, so a missing one
      is not warned about (D15).
      Note: the lane artifacts are asked only of `e2e.yml`'s runs, and messages
      name the workflow. It also gains `--event`, taking only runs triggered so;
      the `ci` part passes `workflow_dispatch`, so a pull request's run of the same
      head commit, which tests a merge, is never taken.
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
      Note: job conclusions and failing steps come from `gh run view --json jobs`,
      lines from the whole log (its job/step/timestamp prefix, byte-order mark, and
      colour read past). Only lines inside the `short test summary info` block are
      read, `FAILED` and `ERROR` entries both; the block ends only at pytest's
      closing count, a runner line (`##[…`), or its step's end, since on CI pytest
      prints each entry's whole, often multi-line, message. The type is the
      message's leading `<name>:`, or a message that is only an exception's name;
      a plain failed `assert` is `AssertionError`; a failure naming no type is
      `uncomparable`, as D16 rejects the ID alone. Outcome is compared too, so a
      test erroring where `dev` fails it is `new`.
      Correction to the task's wording, per D16 and the delta: a job printing no
      failing test is compared by its failing step and `##[error]` lines —
      `inherited` at the same step with the same lines, `new` beside a passing
      job or another step or other lines — and failing tests beside a baseline
      failing only another step are `new`. Every failure is `uncomparable` with no
      baseline (or one not chosen, fetched, or read, the reason saying which), a
      job the baseline lacks or skipped, a job with no line in either log, a job
      failing at no named step, error lines saying only that a step failed (the
      runner's exit line), or failing tests on one side and only the step on the
      other. A job with failing tests is compared by them alone, since a
      `tests.yml` job stops at its first failing step. The baseline skips
      cancelled runs and pull requests' runs; ancestry runs `git rev-parse --verify
      --quiet` first, so a commit the checkout lacks is no ancestor and any other
      Git failure is an error.
- [x] 8A.4 Validation's `ci` part: `validate_slice.py ci --workflow <file>
      --after-run <id>` (`make validate-ci WORKFLOW=<file> CI_AFTER_RUN=<id>`,
      which the validate step's `make validate-*` rule already allows) writes an
      attempt under `.snapshot/validation/<short commit>/ci/<attempt>/` like the
      other parts: the run and its conclusion, the baseline run and its commit,
      each job's result and log, and 8A.3's classes, in `summary.json`; a run that
      is cancelled, never listed, or not fetched is reported as producing no
      evidence. Judging the owed observations is the validating agent's, from the
      job logs (D15, D16).
      Note: both runs are fetched into the attempt's `runs/<run>/` (`actions.log`,
      `run.json`, `jobs/<job>.log`), so the history copy carries them with the
      validated commit's directory. The part passes when the run produced evidence
      and every failure is `inherited`; a `new` or `uncomparable` one fails its
      `failures` step; an owed job is the agent's to judge whatever the part says.
      Also no evidence: a run not yet `completed`, a fetch keeping no run, an
      unreadable run, and a run concluded other than success with no failed job
      (114 F2). Refused: a workflow off the list, a run of another commit, and `ci`
      without `--workflow` or `--after-run`. No baseline is a warning; one that
      cannot be chosen, fetched, or read fails its step while the part compares
      with none — the one place a part goes on past a failed step — and is only a
      warning when no job failed. `HEAD` moving after the fetch fails a `checkout`
      step and stops the part. The part builds nothing, so it does not start from
      `make dist-clean` (promoted at 10.9).
- [x] 8A.5 `.claude/change-steps.toml` (the orchestrator's, as the preamble says):
      validate gains `Bash(make run-ci *)` (D15).
      Note: committed with this section; `test_change_workflow_steps.py` holds that
      validation alone may run `make run-ci`. Implementation and triage reach the
      read-only `make validate-ci` through their `make validate-*` rule, left as is.
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
      Done, in the skill's steps 1–4 and 7. A line owing a workflow off the list is
      refused by `make run-ci`, its observation absent: a `V<n>` of unknown cause
      for triage to take to design.
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
      Done: `change-plan`'s "Sections are slices" with D14's example line,
      `change-implement`'s step 3, `change-closeout`'s end-to-end part.
- [x] 8A.8 `docs/agents/change-workflow.md`: in "Skills", `make run-ci` and `make
      validate-ci` beside the pipeline targets; in "Reviews", the `Owed by
      validation:` line and the record's `## CI` (D14, D16).
      Done: the Validation row and a paragraph after the push paragraph, which says
      only the owner extends the list.
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
      Evidence: `scripts/tests/test_ci_evidence.py`, 47 passed, unit (Git and `gh`
      faked): dispatch and `CI_AFTER_RUN`; `publish-pypi.yml`, `e2e.yml`, and no
      workflow refused, nothing run; the list holding `tests.yml` alone; baseline
      choice, skipping a run the branch lacks, a cancelled run, and a pull
      request's; ancestry and its errors; short-summary parsing across 8A.3's
      cases, multi-line entries and count-like message lines included; the
      delta's five scenarios as classes over fixture logs; step-based comparison
      and each `uncomparable` case. `scripts/tests/test_fetch_e2e_logs.py`, 20
      passed, unit: a `tests.yml` fetch keeping the whole log with no lane
      artifact, and `--event workflow_dispatch` passing over a pull request's run.
      `scripts/tests/test_validate_slice.py`, the `ci` part's orchestration with
      runner and reader injected (integration, as `TESTING.md` defines it for
      orchestration): the summary, files, and steps; each no-evidence case; each
      baseline failure; `HEAD` moving; a failed run with no failed job (114 F2);
      and `make validate-ci` and `make run-ci` through `make -n`.
      `test_change_workflow_steps.py`: validation alone may run `make run-ci`.
      `uv run --no-project --with pytest pytest -q scripts/tests`: 1512 passed;
      `make test`: passed, `make -C helm test-render` included; `make
      check-packaging`, `make check-agent-skills`, `make check-change`: passed.
      Three fresh-context checks' findings were fixed in the section. End to end:
      none of `e2e-tests/`; the owed line is confirmed (`release · deployment
      contracts` is that job's `name:` in `.github/workflows/tests.yml`).
      Validation 115 was the part's first real run: the owed job passed and the
      four failures of jobs not owed were classed `inherited` against `dev`'s run
      at the merge base, confirming `gh`'s job-name log prefix and the `--json`
      fields the fixtures assumed. Known limit: a baseline older than GitHub's log
      retention cannot be fetched, which fails `baseline fetch` and leaves every
      failure `uncomparable`.

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
      Note: `split_rules` (`change_workflow/cli.py`) also trims each part.
- [x] 8B.2 The root `Makefile`: every unattended step target — `design`, `plan`,
      `implement`, `triage`, `validate`, `closeout`, `archive-cleanup` — passes
      `ALLOW` to `run` as `--allow`; `implement` passes `ARGUMENTS` as `--arguments`
      (D19, D20.3).
      Note: `STEP_GRANTS` makes each `;`-separated rule its own single-quoted
      `--allow`, so spaces, `*`, quotes, and backticks arrive as written;
      `ARGUMENTS` is quoted the same way, and a `$` in either is written `$$`.
      Both apply to unattended runs only, since an interactive session is not held
      to the table.
- [x] 8B.3 The next-step computation: while the checkout's Git directory holds
      `MERGE_HEAD`, it names `owner`, "a merge is in progress", before any other
      routing (D20.3).
      Note: the `merging` seam (`git rev-parse --quiet --verify MERGE_HEAD`) is
      checked first in `Computation.run`, before the view, the clone lookup, or
      the change's files; the result carries `merging: true`.
- [x] 8B.4 `.claude/change-steps.toml` (the orchestrator's, as the preamble says):
      the preamble's "a rule the owner grants for one resumed run" becomes "for one
      run, fresh or resumed" (D19).
      Note: committed with this section.
- [x] 8B.5 Partial work on a return (D20 rule 2): `change-implement` §4 commits
      what the section has as work in progress, checks no task for it, records the
      handoff, pushes, and returns; a stop leaves its work uncommitted, and a guard's
      refusal or a moved `HEAD` commits nothing. `change-triage`, `change-plan`,
      and `change-closeout` say the same of their returns.
      Note: a block for an external input commits nothing, since its session
      resumes; a work-in-progress commit whose push the guard refuses is left as
      it is. `change-triage` gains "A return commits its partial work; a stop
      does not".
- [x] 8B.6 The merge mode of `change-implement` (D20.3): invoked with no sections
      and an argument naming a merge's conflicted files, it resolves them, runs the
      suites of the sections owning those files, concludes the merge with `git
      commit`, pushes, and finishes, checking no task.
      Note: the skill's section "Resolving a merge's conflicts" checks
      `MERGE_HEAD` and that the unmerged files are the ones named, reads each side
      with `git log --merge -p`, and asks the owner where both sides cannot hold.
      It runs `make test` beside the owning suites, plus `make lock` and `make
      check-packaging` when a lock or `pyproject.toml` conflicted, and concludes
      with `git commit -m <Git's merge subject> -m <resolutions>`, which opens no
      editor.
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
      Note: `dev` is merged from the clone's `origin`. A merge stopped at
      conflicts is never aborted. The session resolves conflicts in the index
      rows, in any change's documents under `openspec/changes/`, in the step
      table, and in skills, and concludes with `git commit --no-edit`. Any other
      conflict, code above all, goes to the owner. On the owner's word, a stopped
      run's work may be committed to a separate work-in-progress branch (D20 rule
      2). While `MERGE_HEAD` exists the computation names no waiting run, so a
      merge run's question or stop is resumed by the `seq` its target printed.
- [x] 8B.8 `docs/agents/change-workflow.md`: in "Orchestrating a change", grants
      for a fresh or resumed run with `ALLOW`, the commit rules (each step commits
      and pushes its own work; partial work only on a return), and merges of `dev`
      with the conflict hand-off (D19, D20).
      Note: "Granting a rule for one run", "Commits", and "Merging `dev`".
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
      Evidence. Unit, with a fake Claude: `test_run_change_step.py` (`run --allow
      'a;b' --allow c` passes three rules after the table's, recorded `granted`;
      `resume` dropping empty parts; `split_rules`); `test_change_workflow_wrapper.py`
      (a fresh run's two grants recorded, its next run held to the table); the
      delta's "The owner grants rules before a fresh run" is covered in pieces,
      since no test runs make, the script, and the wrapper end to end.
      `test_change_next_step.py`, through the `merging` seam: a merge in progress
      names the owner in five states, before the view, the workspace, and the
      clone are read. `make -n` over the real `Makefile`: `ALLOW` on all seven
      targets, one `--allow` per rule, none interactively; `ARGUMENTS` on
      `implement`. Integration (a real process boundary, as `TESTING.md` defines
      it): the `make -n` command run by `sh` with quoted, backticked, and empty
      parts; in real Git, a conflicted merge seen by `_merging` until `git commit`
      concludes it. `make check-agent-skills`, `make check-packaging`, `make
      check-change`, and `make test` (`make -C helm test-render` included):
      passed. A fresh-context read of the skills against D19, D20, and the delta
      found wording and coverage gaps in the skills and the guide, all fixed. End
      to end: none of `e2e-tests/`, and no `Owed by validation:` line, since
      nothing here needs a push to show.
      Handoff, raised by no review and decided by none; recorded at closeout under
      `design.md`'s "Known gaps" and in "Current limits" (10.9):
      - A triage that returns the change writes no `## Next`, so its file reads as
        a triage in progress, and once the change is back in design or planning
        the computation may name triage again; D20 does not say what `## Next`
        records on a return.
      - The merge check runs in whatever checkout computes, before the clone
        lookup, so an unrelated merge in progress in the owner's workspace makes
        the workspace's computation name the owner rather than `in-clone`.
      - No test runs a merge-mode `implement` prompt or the routing after it.
      Round 3 triage (112 O1; 109 R1 / 111 R1; rationale in the design's blocks
      of those labels):
      - 112 O1: `make implement … UNATTENDED=1 SESSION_ID=<id>` (`run implement
        --session <id>`) continues the named implementation session on its model,
        recording `continues`, with the refusals the design block names; the
        orchestrate skill continues a session only on the owner's word; the guide
        gains "Continuing an implementation session"; the delta's scenario "The
        owner sends the next section to a finished session". An interactive
        `make implement` ignores `SESSION_ID` rather than refusing it, since there
        the owner resumes with `claude --resume`.
      - 109 R1 / 111 R1: the wrapper keeps every earlier turn's outcome, across
        attempts, under `earlier`; the unattended prompt (`harness.py`) says never
        to end the turn or schedule a wake-up to wait for a background command;
        the orchestrate skill and the guide relay `earlier`; the delta's scenario
        "A wake-up follows a run's report".
      Evidence: unit with a fake Claude in `test_change_workflow_wrapper.py` (a
      wake-up's turn after a report, a crash after a report, a named session
      continued past a later one, the refusals) and `test_run_change_step.py`
      (`run --session`; `SESSION_ID` through `make -n`). With 114 F1 (8.7) and
      114 F2 (8A.9): `scripts/tests` 1552 passed; `make test`, `make
      check-packaging`, `make check-agent-skills`, `make check-comment-hygiene`,
      `make check-change`: passed. A fresh-context check of the diff fixed, among
      wording, continuing one session stranding another's open question and a
      retried attempt's report lost from `earlier`. End to end: none; the next
      continued session and the next wake-up are its working evidence.
      Pilot triage (127, 128, with validation 126), decided with the owner:
      - 127 O2 / 128 R5 (design block of that label): a repeat pass over a fix is
        read like a first pass. `_round` names `round-view` with `base`, before
        the fix's validation and review in the workspace and beside them in a
        clone, and the pass's triage waits for an owner record saved after that
        triage finished; the triage and orchestrate skills, the guide,
        `round_view.py`'s docstring, and the delta's "A repeat round's fix is read".
      - 128 R2: `history_log_path` (`find_records`, then `log_path`) is what `make
        change-cost` and `run_change_step.py log` read; writes keep `log_path`.
      - 128 R1: at `done` the orchestrating session runs `make -C <clone>
        change-history`, so the workspace holds archive cleanup's own line (D11).
      - 128 R3: every step skill says Make runs without `-C <a checkout>`; validate
        reads snapshot JSON with Read or Grep; triage gains implementation's wait
        rule.
      - 127 O1 (design block of that label), as the owner directed:
        `scripts/check_uv_version.py` (`make check-uv-version`, uv ≥ 0.12) runs
        before `make lock` builds or relocks anything and first in validation;
        validate's table gains its rule; `tests.yml` and `e2e.yml` install uv
        0.12.19; `BUILD_AND_PACKAGING.md` documents it. No `uv.toml` pin and no
        relock: the fix commit's CI run showed whether the locks needed one.
      Evidence: unit in `test_change_next_step.py` (repeat passes in the
      workspace and in a clone, a first pass's record numbered after its review
      not answering for the fix, no fix, an abbreviated base, a third pass, a
      failed fix validation triaged first), `test_change_cost.py` and
      `test_run_change_step.py` (an archived change's records beside a
      records-less active directory), `test_check_uv_version.py`. `scripts/tests`
      1572 passed; `make test` passed after `make dist-clean` (a stale wheel this
      diff does not touch had failed a first run); `make check-packaging`, `make
      check-agent-skills`, `make check-comment-hygiene`, `make check-change`:
      passed. A fresh-context check's findings, chiefly a clone's first-pass
      record taken for the repeat pass's reading (now judged by when it was
      saved), were fixed. End to end: none; the next repeat round and the next
      archive cleanup in a clone are its working evidence.

## 9. The pilot's evidence and the containerization decision

Delivers D9's evidence and open question 1's decision point, once the pilot's
archive cleanup has run on this branch's tooling. Touches this change's documents
only.

- [x] 9.1 Record from the pilot's log and records, citing their seq numbers: its
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
      Evidence, from the pilot's log in its clone (97 lines; "P-seq"), this
      change's log ("seq"), the pilot's records and validation evidence, its
      orchestrating session's transcript, and Git. The pilot ran from 2026-10-23
      06:33Z (P-seq 1, design) to 2026-10-24 06:51Z (P-seq 97, archive cleanup):
      a design and its review, a plan of one round in two sessions (P-seq 33,
      `[[1, 2, 3], [4–9]]`), that round's two passes, a pre-closeout review,
      closeout, its review, and archive cleanup, all unattended in its clone,
      driven by an orchestrating session started in the clone (seq 169).
      - Clone and bootstrap. On the owner's word (seq 114) this change's
        orchestrating session ran `make change-clone` from this branch for the
        pilot and for `resolve-compute-family-findings`, for 7.3's run. Both
        bootstraps failed at `init-buyer` (seq 115): `make init` relied on wheels
        and an environment the workspace had left behind (fixed in 7.3). Then
        fast-forwarded to 297c64fa1 and rerun (seq 118): `change-bootstrap.json`
        and `.status` record `make init` started 07:07:49Z, exit 0, and
        `change-clone.json` the change and `feat/seed-default-pool-at-runtime`.
        Fast-forwarded again to b1c1e044d with `make init-bare-metal-storefront`
        (seq 121, 122), and after round 3's triage to 15b4b6ded with `make init`
        rerun (seq 170). The bootstrap finished a day before the pilot's design,
        so nothing waited on it; the computation's `clone` and `wait` results were
        not met, the clone being made on the owner's word.
      - Validation in its own namespace. Not beside round 2's validation as
        planned: the owner held the pilot until round 3 was triaged (seq 169), so
        its validations (P-seq 51, 73, 81, 89; records 38, 59, 66, 73) ran on
        2026-10-23 and 24 with no other change validating, each finding every
        other release at zero (`other_namespaces_at_start`). Its one Helm part
        beside another change's was 7.3's second `make validate-parallel` attempt
        (07:20:48–07:22:59Z on 2026-10-22, before round 2's validation, seq 125):
        `validate-seed-default-pool-at-runtime` beside
        `validate-resolve-compute-family-findings`, each on its own
        `arkhai:{compute-provisioning,dev-env,e2e-tests,registry,storefront}-<change>`
        images, each scenario pod `arkhai-node-operator-e2e-tests-e2e-scenarios`
        in its own namespace, exit 0, every check passed. Across its five Helm
        parts the release went from a first install (b1c1e044d, revision 1) to
        four upgrades over a namespace left at zero (cb954190f, 0152385ad,
        f78ea4e8b, 29f9fecd9; revisions 2–5 in each `deploy.log`), the 0152385ad
        upgrade over the pilot's own chart change (the provisioning chart's
        `configFiles`); each overlay named the change's tags (`images.json`), each
        scenario pod exited 0, no upgrade was refused, so the fallback stays
        unexercised. Every part warned `metrics` and `capacity` and recorded no
        memory. Validation and the implementation review ran side by side in the
        clone for each pass (P-seq 50 and 51, 73 and 75, 81 and 83).
      - A round read in the owner's workspace. The pilot's orchestrating session
        started validation and the review in the clone, then at 16:38:52Z on
        2026-10-23 ran `make round-view` in the workspace ("Round of
        seed-default-pool-at-runtime: 56bafe8a39bd..cb954190f415 is now uncommitted
        changes on feat/seed-default-pool-at-runtime in this checkout"). The review
        (P-seq 50) and validation (P-seq 51) finished while it was open. The owner
        answered (`39-implementation-owner.md`) and made no commit during the
        view; `make round-done` at 18:29Z returned the branch to the round's
        commit and the workspace, clean, to `feat/parallel-change-workflows`;
        triage's `git pull --ff-only workspace feat/seed-default-pool-at-runtime`
        brought nothing (`37-implementation.triage.md`). Carrying commits made
        during the view, its refusals, and a refresh were not met. The view held
        118 files, 11 of them brought by the three merges below (four skills, the
        step table, the delta, the companion architecture, three
        `scripts/change_workflow/` files, and one of their tests): open question
        2's case. The repeat pass over the fix 0152385ad opened no view, and its
        triage asked for notes on code no one had shown the owner (P-seq 76;
        127 O2, 128 R5), fixed in 8B.9's pilot triage.
      - Archive cleanup (P-seq 97, at fcd80e5c9). It released
        `bring-host-inventory-under-definition-documents` and
        `gpu-optional-compute-shapes`, set the row `archived`, wrote the pull
        request draft, and recorded no capacity figure — the Helm part measured
        no memory, as no metrics source answers — leaving
        `helm/validation-capacity.toml` unchanged with no figure commit. It
        deleted `validate-seed-default-pool-at-runtime` and the change's nine
        images, and copied 628 files into the workspace with none refused,
        including the named evidence of its four validated commits and pipeline
        run 40069878714. The copy ran before the wrapper wrote P-seq 97, so the
        workspace's log ends at P-seq 96 (128 O1); the orchestrating session now
        copies again at `done` (128 R1), and the pilot's copy gains the line at
        clone removal. `make change-cost` read nothing for the archived change
        until 128 R2. On the owner's word the pilot was merged into this branch as
        PR #306 (da75bcebe, seq 177), not after this change as D9 planned, so
        this change's pull request carries it.
      - Merges of this branch into the pilot's. The two planned merges were
        fast-forwards, since the pilot had no commit of its own yet (seq 118,
        170). Three merges followed during its implementation, each between its
        steps, on the owner's word, by this change's orchestrating session:
        59041f6cb (770acfd27: `git rm` for implementation and triage, design's
        one decision per message; P-seq 38), 9419d691b (4976cb930: denials
        classified by every reason; P-seq 39), and 461cd7b6b (66ce8f1f6:
        foreground subagents, `unzip -l`; P-seq 47, once the resume of P-seq 43
        had ended, seq 173). None conflicted, the index rows included: `git show
        --remerge-diff` shows no resolution in any, nor in da75bcebe. All three
        fell inside the pilot's one round, between its sessions, which D9's timing
        rule allows and which put them in the round's view.
      - Denials and `orchestrator` lines. Eighteen of the pilot's runs logged
        denials, each read on its own `orchestrator` line (P-seq 2, 12, 28, 35,
        37, 42, 44, 46, 49, 52, 54, 72, 74, 80, 82, 88, 90, 92); archive cleanup
        logged none. All but three were `mode` gaps redone by an allowed route,
        or not needed: Bash reads of the workspace's records outside the clone
        (P-seq 1, redone with Glob — the `--records` path is readable by Read,
        Glob, and Grep, not by Bash), inline `python3 -c` reads of JSON (P-seq 27,
        41, 51, 73), chained or piped reads, output redirected to `/tmp`,
        `Monitor` and wait loops (P-seq 34, 36, 43, 79), `make -C <its own
        checkout>` (P-seq 71, 87), `git config --get-regexp remote` (P-seq 53), a
        `git diff` against a substituted merge base (P-seq 89, not redone,
        disclosed in record 73), and a heredoc rewrite (P-seq 91, redone with
        Edit). Three stopped a step or went to the owner: design's `git fetch
        origin dev` and `git worktree add` for the `gpu-optional-compute-shapes`
        proposal (P-seq 11, granted for one run, P-seq 12); implementation's `rm`
        and `git rm` of two files task 6.1 deletes (P-seq 36; the owner ran `git
        rm` and allowed it, P-seq 38–40), whose `git stash push` and `git
        checkout --` were refused by deny rules (`subcommandResults`) and undone
        by hand with Edit; and the wheel listing (P-seq 43, `unzip -l` granted,
        then allowed to every step, seq 174). P-seq 45 stopped on the account's
        session limit, not a denial, and resumed after its reset (P-seq 46, 48),
        while no run of this change was in progress. This change's orchestrating
        session's lines on the clones: seq 114, 115, 117, 118, 120–122, 169–174,
        176, 177. Section 7's implementation run was denied reads of a clone's
        bootstrap log and Git after `cd` into it (seq 117), redone with Read,
        Grep, or Glob, and Git in a clone after `cd` (seq 120), not done, since
        the orchestrating session moves the clones. The gaps several steps
        tripped became 128 R3's skill text.
      Clone removal was not run: the pilot's branch is merged into this one, not
      `origin/dev`, so `make change-clone-remove` refuses it until this change
      merges (8.7 is its evidence). End to end: none; this is the pilot's working
      evidence, and validation 139 at caa4cbc4c the latest of this change's own.
- [x] 9.2 Update `design.md`'s Risks with what the pilot confirmed or disproved.
      Note: each risk gains what the pilot showed — the clone's first `make init`
      as the first build from the commit alone (confirmed, fixed in 7.3); the two
      `feat/<change>` refs (not met); two releases on one node (the inactive
      preflight confirmed, exhaustion untested); the merges (no conflict, the
      index rows included; a merge between a round's sessions inside its view,
      open question 2; the pilot merged into this branch); the usage limit (met
      once); the index at a merge to `dev` (not yet tested); the scenario pod
      (five parts from the images, four upgrades from zero, the fallback
      unexercised). A new risk: an unattended step's Read, Glob, and Grep reach
      any file the owner can read, while its Bash reads stay in its checkout.
- [x] 9.3 Decision gate (open question 1): the owner decides, with the agent, whether
      to open a change to containerize the workflow, and the reasoning is recorded in
      `design.md`, the open question then closed or kept with its trigger. A change
      it decides to open is proposed afterwards on its own branch from `dev`, not
      here (D13 disposition).
      Note: put to the owner with three options — open a proposal-only change now,
      keep the question with triggers, or close it — and the agent's
      recommendation, keeping it; the owner chose to keep it. Open question 1
      records the decision, its reasoning, the three triggers that reopen it, and
      the rejected options. No change is opened. 10.9's "Current limits" names the
      triggers and the read-scope risk.
- [x] 9.4 Verification: `make check-change CHANGE=parallel-change-workflows`.
      Evidence: `make check-change CHANGE=parallel-change-workflows`, passed
      (comment hygiene, agent skills, citations, task list, change index, strict
      validation); `make test`, passed, every suite, `make -C helm test-render`
      included, though the section changes no code. End to end: none; no
      `Owed by validation:` line, since the section changes only this change's
      documents. A fresh-context check of the diff found no breach of the
      guidance and corrected one mislabel and three design sentences that said
      more than the evidence; it did not check the round view's times, which come
      from the pilot's orchestrating session's transcript.
      Handoff, each settled:
      - Open question 2 (the round view mixing merges into a round): deferred in
        round 4's triage (145 F1) to `workflow-round-review-without-merges`, proposed from
        `dev` after this change merges; recorded in open question 2 and 10.9's
        "Current limits".
      - The pilot merged into this branch (PR #306, seq 177), not after it as D9
        planned: corrected in pre-closeout triage 152 F1 in D9, D4, the
        proposal's Dependencies and Impact, the pilot's index row, and 10.6.
      - The workspace's copy of the pilot's log lacks P-seq 97 until the pilot's
        clone is removed, which runs the copy first; removal waits for this
        change's merge into `dev`.
      - Open question 1's triggers and the read-scope risk have their
        destination in 10.9's "Current limits".

## 10. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [x] 10.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments this change added to `scripts/`, the Makefiles, `helm/`, and the step
      table; anything to rewrite returns the change to implementation.
      Confirmed: `make check-comment-hygiene` passed. The comments and docstrings
      added under `scripts/`, the Makefiles, `helm/`, `.claude/`, `.agents/`, and
      `e2e-tests/` since `dev` (968a4a9cd) were read for provenance — review,
      triage, round, or finding labels, "pilot", "migrated", "no longer" — and
      none names the review or migration that introduced it; "review" and
      "triage" appear only as the workflow's own steps. Nothing returns.
- [x] 10.2 Import placement — confirm: no function-local import added in the files
      this change added or touched under `scripts/`; one that should move returns
      the change to implementation.
      Confirmed: every import line added to a Python file since `dev` is at module
      level (167 under `scripts/`); none is indented.
- [x] 10.3 Documentation compliance: re-check D1–D11 and D14–D21 against
      `openspec/README.md`'s placement rules.
      Done: behaviour went to the `change-workflow` spec (by the archive) and its
      rationale to the companion architecture; contributor procedure to
      `docs/agents/change-workflow.md` and `AGENTS.md`; Kubernetes deployment
      conventions (D4's namespace, tags, and capacity) to
      `DEPLOYMENT_AND_CONFIG.md`; where the Helm scenarios run to `TESTING.md`;
      the uv minimum (127 O1, packaging) to `BUILD_AND_PACKAGING.md`, in round 4.
      D5, D9's pilot, D10, D21, and the cadence are this change's history and
      stay here. The permanent documents were checked against the code they
      describe (`helm/Makefile`, `scripts/change_namespace.py`,
      `scripts/validate_slice.py`, the e2e-tests chart's scenario hook and
      Dockerfile, the root `Makefile`, `.github/workflows/`); the design-promotion
      record names each destination.
- [x] 10.4 Narrative compression of the notes of sections 1–9, 8A and 8B included,
      moving any rationale not yet in `design.md` there first.
      Done: 2,678 lines to about 1,600. Notes keep final behaviour, evidence (test
      files, levels, final counts, commands and results, cluster runs), deferrals,
      and destinations; intermediate counts, debugging chronology, and per-round
      fix narratives were dropped, each fix cited by the finding whose rationale
      `design.md` holds. Moved to `design.md` first: what the fresh-context checks
      raised and sections declined ("Declined at the fresh-context compliance
      checks"); 8B.9's open handoffs ("Known gaps"); the uv minimum's decision
      ("127 O1"); an interactive `SESSION_ID` ignored (under 112 O1). Section 9,
      the pilot's evidence, is compressed least. Every task's own text is
      unchanged.
- [x] 10.5 Roadmap currency: no goal in `docs/development/ROADMAP.md` covers
      contributor workflow; record that, or update it.
      Recorded: no goal covers it, so no edit; the pilot's own roadmap effect was
      its closeout's.
- [x] 10.6 Campaign index currency: this change's row `in closeout`, under
      independent active changes; `helm-e2e-pipeline-parity`'s `Depends on` is left
      as it is (archive cleanup releases dependents), and the pilot's row already
      says it merged into this branch (152 F1). `make check-change-index`.
      Done: the row is `in closeout`, its notes rewritten for closeout and, after
      the archive, linking it (10.11); no campaign graph names this change, and no
      other row changed. `make check-change-index`: passed.
- [x] 10.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=parallel-change-workflows`, and `make check-agent-skills`.
      Passed, all three: every environment and image install from its lock, every
      lock current, one Python version, the project layout, and the layers, scope,
      dependencies, and kinds rules; the change owns no architecture row; every
      skill loads from its one source.
- [x] 10.8 End-to-end pipeline: record a passing run on the closeout commit and the
      Helm part's namespace evidence, or an explicit blocker naming its cause and
      owner, and, from the latest passing validation's `## CI`, the owed
      `tests.yml` observation of 8A.9 with its run and baseline (D18). No pipeline
      scenario exercises the workflow tooling; the pilot (section 9), the
      two-validation check (7.3), and round 3's `ci` part are its working evidence.
      Recorded from validation 151, `passed`, at 53c9465e7, the commit pre-closeout
      review 152 read. Closeout changes no code, and every commit since changes
      only `openspec/` and `docs/`, so these runs describe the code the closeout
      commit carries; no run is made on the closeout commit itself, which is the
      skill's rule rather than this task's first wording.
      - Pipeline: `e2e.yml` run 40292542009, success — e2e-bare-metal, e2e-vm, and
        e2e-apicredits passed. No scenario exercises the workflow tooling (8A.9:
        "none of `e2e-tests/`"); the scenarios this change's diff touches,
        `e2e_compute_dynamic_listings` and its VM host-registry helper, passed in
        e2e-vm.
      - Helm: namespace `validate-parallel-change-workflows`, scenario pod
        `arkhai-node-operator-e2e-tests-e2e-scenarios`, exit 0; `metrics` and
        `capacity` warned, no memory measured; every pipeline scenario the default
        charts do not serve reported as not run against Helm.
      - CI owed by 8A.9: `tests.yml` run 40292552695, job `release · deployment
        contracts` passed (1572 tests, the provisioning chart render checks, and
        the structural identity assertions), and `## CI` names the baseline,
        `dev`'s run 39646750044 at 968a4a9cd709, and classes every failure of the
        jobs not owed: `py · vms-storefront`'s three `TimeoutError`s and `py ·
        bare-metal-storefront`'s one `AssertionError`, each `inherited`.
      Working evidence beyond the pipeline: the pilot (9.1), the two-validation
      check (7.3), and validation 115's first real `ci` part (8A.9).
- [x] 10.9 Promotion, completing the design-promotion record:
      - `openspec/specs/change-workflow/spec.md` — written by the archive (10.11):
        "Each change is worked in its own clone" and "Each Helm validation is
        isolated in its change's namespace" added; "Implementation sections and
        sessions", "Validation observes a committed slice", "Triage of an
        implementation round", "An orchestrating session advances one change",
        "Unattended step runs end with a structured outcome", and "Unattended runs
        are held to their step's permissions" modified. By hand:
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
        uncommitted work) and for a repeat pass's reading of its fix, over the
        commit the earlier pass's review read (127 O2 / 128 R5); "Validation observes a committed slice" rewritten for the
        change's namespace (D4: fixed per-change rather than commit tags, the
        upgrade from zero, the advisory capacity figure, written only when measured,
        78 F2) and for the `ci` part (D15–D17: no publishing workflow dispatchable,
        the owed jobs judged, every other failure compared by test ID and exception
        type with a `dev` run the branch contains, and why); "Sections are slices,
        sessions are the owner's" for evidence owed by validation (D14, D18), and
        its "Each session still starts with no prior conversation" amended for an
        implementation session the owner names to continue, and why it is named
        rather than inferred (112 O1); "Steps run headless and resume with the
        owner's answers" for a run's earlier outcomes kept beside its last and the
        unattended prompt's rule against waiting on a wake-up (109 R1 / 111 R1);
        "Pushing is guarded, never repaired" for each step committing and pushing
        its own work, why the steps once did not, and the branch as the guard
        against unfinished work, only `dev` protected (D8, D20 rules 1–5);
        "Restrictions bind unattended runs only" for a grant for one run, fresh or
        resumed, through `ALLOW` (D19); "The orchestrator relays and routes" for its
        workflow maintenance, the owner's instructions, merges of `dev`, and the
        conflict tiers (D8, D20 rule 6, D20.1–D20.3); a new "History lives in the
        owner's workspace" (D11; the copy repeated at `done` for archive
        cleanup's own line, and reports read through `find_records`, 128 R1,
        128 R2); "Current limits" rewritten (one orchestrating
        session per change; the container per change, as 9.3 decided, with the
        triggers that reopen it, open question 1; an unattended step's reads
        reaching any file the owner can read, Risks; the round view showing a
        merge made inside a round among the round's own changes, until a
        synthetic base lands in its own change, open question 2, 145 F1; side
        work chosen to stay clear of the critical-path goal's files, D9).
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
      Done, the record completed in `design.md`'s "Design promotion record". The
      spec's requirements are the archive's (10.11); by hand, its Purpose and
      "Evidence" (with `scripts/change_workflow/running.py` and `make
      record-capacity` beside the files named). The companion architecture gains
      "A change is worked in its own clone" and "History lives in the owner's
      workspace", and rewrites or extends every section named, "Reviews are
      files" and archive cleanup's sentence in "Phases, triage, and archival"
      too; "Current limits" also takes the two system gaps of `design.md`'s
      "Known gaps" and the node-memory risk. `docs/agents/change-workflow.md`
      already held the clone, history, and removal targets under "A change in its
      own clone"; "Skills" gains `make validate-parallel`. `DEPLOYMENT_AND_CONFIG.md`
      gains "Validation namespaces" after "Release topology", whose
      `helm-topology-secrets` bullet gains the namespace, and its paragraph on the
      retained-volume refusal is scoped to `default`. `TESTING.md` gains the Helm
      scenario pod under its section 4, and its chart render section names `make
      init-bare-metal-storefront` (7.3's handoff).
- [x] 10.10 Documentation citations: `make check-change
      CHANGE=parallel-change-workflows`, which runs `make check-doc-citations
      CHANGE=parallel-change-workflows` and `openspec validate
      parallel-change-workflows --strict`.
      Passed: comment hygiene, agent skills, documentation citations, task list,
      change index, and the pinned strict validation.
- [x] 10.11 Archival: `openspec archive parallel-change-workflows -y`, merging the
      delta into `openspec/specs/change-workflow/spec.md`; the index row then links
      the archive; `make check-change CHANGE=parallel-change-workflows`.
      Done with the pinned validator (`npx --yes @fission-ai/openspec@1.14.0`, as
      `scripts/check_change.py` runs it where `bunx` is absent), without
      `--skip-specs`, since the permanent spec held none of the delta: 2 added, 7
      modified, nothing removed. The diff of `spec.md` touches only the Purpose,
      those nine requirements, each present once, and "Evidence". Archived as
      `openspec/changes/archive/2026-10-26-parallel-change-workflows/`, `reviews/`
      with it; the index row links it. `make check-change`: passed.

Closeout triage 157 corrections, on the owner's direction (the closeout review's
two findings):

- 157 F1, a code correction: a triage that returns the change records `Returned
  to design` or `Returned to planning` under `## Next`, and once the owner confirms
  the return its review no longer governs (`design.md`, "Known gaps").
  `scripts/change_next_step.py` gains the `RETURNED` token, `return_confirmed`
  (a decision resolving a returned triage run and directing design or planning,
  recorded after the review's triage file was last written), and `set_aside`,
  which `_implementation` reads before anything else about the current round, so
  the amended plan's next round runs as a round of its own, or the pre-closeout
  review when every section is checked; `_pre_closeout` goes to a validation of
  `HEAD` and a new pre-closeout review; an unconfirmed or declined return, and any
  at closeout, names the owner. The triage skill writes the token on a return,
  and the plan and orchestrate skills name it; the spec's requirement and three
  scenarios, the companion architecture, and `docs/agents/change-workflow.md`
  describe it, and the limit is removed.
  Evidence: `scripts/tests/test_change_next_step.py`, unit level (`TESTING.md`),
  178 passed, seven new: a round's confirmed return to the amended plan's next
  round; a rework of the round's own section as a new round; a plan that drops
  the round's section; a confirmation from before a return not confirming it; an
  unconfirmed and a declined return; a pre-closeout return to validation then
  review; a closeout return to the owner. `make test-release-tooling` 1578 passed;
  `make test` passed; `make check-packaging`, `make check-comment-hygiene`, and
  `make check-change CHANGE=parallel-change-workflows` passed. Two fresh-context
  compliance checks of the diff against 860ce6db7: fixed — a rework of the
  returned round's own section, which under the old round reached the next round
  unread and unreviewed; a confirmation matched to the latest returned run rather
  than to the review; a plan that renumbered the round's sections reaching
  `unclassified` before the set-aside; two-token wording left in the module
  docstring and the orchestrate, plan, and triage skills; the pre-closeout and
  declined routes missing from the spec; one more history phrase of F2's kind
  ("It no longer commits a step's leftover work"). Declined — a triage that
  crashes after writing `Returned` and before logging its outcome: its stopped run
  is resumed and then ends `returned`, and the owner's message says so. Raised and
  left to the owner, since it predates this correction: with a round line in the
  log, a pre-closeout `Another round` over documents alone reaches `_round`'s
  validation of the round's fixes before `_pre_closeout`'s documentation
  exemption, so it asks for a validation the exemption would waive.
- 157 F2, documentation: the architecture's "Pushing is guarded, never repaired"
  states the present reason a step commits its own work without the former
  rule, "The change's namespace" gives fixed per-change tags their present
  reasons only, and "The orchestrator relays and routes" says the session commits
  no step's leftover work, without "no longer".

Closeout triage 165 corrections, on the owner's direction (the closeout review's
two findings):

- 165 F1, a code correction: only the owner's decision confirms a return.
  `note_orchestrator` refuses a decision directing any step but a review unless it
  is the owner's; `directed`, `return_confirmed`, and `redesigned_after_return`
  count such a line only when the log attributes it to the owner, so one already in
  a log still resolves its run but directs nothing, and a triage's return then names
  the owner as unconfirmed. The spec's requirement "Unattended step runs end with a
  structured outcome" states it, with a scenario under "The next step is computed
  from the files"; the architecture's "The owner is interrupted only for judgement"
  explains it. Evidence: `scripts/tests/test_change_workflow_log.py` and
  `scripts/tests/test_change_next_step.py`, unit level (`TESTING.md`), four new
  cases — the writer refusing an orchestrator-attributed return to design and to
  planning; routing past such a line naming the owner; a design-review waiver
  refused after such a line. `uv run --no-project --with pytest pytest -q
  scripts/tests`: 1583 passed; `make test`: passed, `make -C helm test-render`
  included; `make check-packaging` and `make check-comment-hygiene` passed. A
  fresh-context compliance check of the diff against `27a038db4` found no broken
  path; fixed — an error message naming a waiver it could never apply to, the
  `directed` docstring overstating what follows for a non-triage returned run, a
  test comment describing the writer's past behaviour, an unwrapped architecture
  line, and no test of the owner filter in `redesigned_after_return`; declined — a
  spec scenario for the writer's refusal, since the spec's MUST is on the
  confirmation and the writer is one enforcement of it.
- 165 F2, documentation: the design's promotion record splits the "Known gaps" row,
  the returning triage's token and its owner-only confirmation pointing to the spec,
  the architecture's routing discussion, and the contributor guide, and only the
  merge check to "Current limits".
