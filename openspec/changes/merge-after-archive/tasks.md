# Tasks

Sections 1–3 are the engine, lowest layer first: the outcome's landing record and the
log writer's checks of it (1), the graph's table (2), and the next-step computation
that interprets it (3). Section 4 is the skills that carry the merge after the archive.
Section 5 is the closeout. Section 1 also holds the skill and step-table edits that
record and fetch the landing branch, because the outcome schema, the skills that write
`landing`, and the engine that requires it change in one commit (design D10).

Every script suite named below runs under `make test-release-tooling` (`pytest -q
scripts/tests`), which `make test` reaches through `test-deployment-packaging`. A test
is unit where it injects Git and the filesystem, and library integration where it runs
a real Git repository (`docs/development/TESTING.md`). No end-to-end scenario in
`e2e-tests/` exercises the change workflow's tooling or its skills, and none is owed:
they run on a developer's machine and in CI, not in the deployed stack. The pipeline
still runs on every validation, and is evidence only that the stack still builds and
runs.

## 1. Merges and archive cleanup record the landing branch they fetched (D10, D5's source)

Delivers the outcome's `landing` record, the log writer's checks of it, the
containment the writer records on archive cleanup's line, and `start merge`'s branch;
and the skills and step-table rules that write and fetch it. Implements D10, the parts
of D5 that resolve and record cleanup's source, the delta requirement CW-5vkd (all but
the guard on cleanup's exit, which section 2 declares and section 3 reads), and the
modified CW-s3ju. Touches `.agents/change-outcome.schema.json`,
`scripts/change_workflow/outcome.py`, `log.py`, `cli.py`, `find.py`,
`.agents/skills/change-merge/SKILL.md`, `change-archive-cleanup/SKILL.md`,
`change-orchestrate/SKILL.md`, and `.claude/change-steps.toml`.

- [x] 1.1 Add the optional `landing` object, `{"remote", "branch", "commit"}`, to the
  step outcome schema, and its form to the outcome check: each field a non-empty
  string, the commit a full hexadecimal object name, no other field (D10). Verify:
  unit tests in `scripts/tests/test_change_workflow_outcome.py` accept a well-formed
  `landing` on any outcome, refuse each malformed form naming the field, and accept an
  outcome without it.
  Done: the schema holds the shape (closed, three non-empty strings); the full object
  name (40 or 64 lower-case hex) is checked in `outcome.outcome_problems`, since the
  schema check understands no `pattern`. Unit: `test_change_workflow_outcome.py`
  (`test_a_well_formed_landing_is_accepted_on_any_outcome`, `test_a_malformed_landing_*`,
  `test_an_outcome_without_landing_is_accepted`) passes.
- [x] 1.2 Make the log's writer, in `record_outcome` and `record_interactive`, require
  and check `landing` on a merge's `finished` line (D10, CW-5vkd): refuse it absent —
  but for a repair when no finished merge in the log recorded one — or naming a remote
  that is neither one of the checkout's remotes nor `.`, or a commit the line's commit
  does not contain; never require it on a merge's `question`, `stopped`, or `returned`
  line. The Git reads (the checkout's remotes, ancestry) are injected. Verify: unit
  tests in `scripts/tests/test_change_workflow_log.py` for each refusal and for each
  outcome recorded without `landing`, mapping the delta scenarios "A merge's outcome
  records no landing branch", "A merge stops at a conflict it asks about", "A repair of
  the merged HEAD finishes", and "A repair of a merge logged before the record
  existed"; a library-integration test with a real repository whose merge commit
  contains the recorded commit and one whose `HEAD` does not.
  Done: `log.landing_problems`, called by `record_outcome` for a finished merge or
  archive cleanup, with the Git reads injected as `log.Checkout` (`remotes`,
  `contains(commit, ancestor)`, `base`); `log.git_checkout` reads them through
  `records.git_remotes` and `records.git_contains`. `record_outcome` refuses a
  finished merge or cleanup when no checkout is given; the wrapper and `record` pass
  `git_checkout(root, change)`. "A repair" is read as: an earlier finished merge
  exists, none recorded `landing`, and the change's latest validation record failed
  (`_repairs_unrecorded`). The writer does not compare a repair's `landing` with the
  repaired merge's: it requires one, and the skill says which. Unit:
  `test_change_workflow_log.py` (`test_a_merges_outcome_records_no_landing_branch`
  ×3, `test_a_merge_stops_at_a_conflict_it_asks_about` ×3 — no checkout read for them,
  `test_a_repair_of_the_merged_head_carries_the_landing_it_repairs` — a repair
  without `landing` refused once a merge recorded one,
  `test_a_repair_of_a_merge_logged_before_the_record_existed` — the writer's half;
  the cleanup line read as checked is section 3's guard,
  `test_a_first_merge_finished_without_landing_is_no_repair`,
  `test_an_interactive_merge_is_checked_as_an_unattended_one`) passes. Library
  integration (a real Git repository, no application):
  `test_the_writer_checks_a_merges_landing_in_a_real_repository` passes.
  Outside the plan: the wrapper logs a finished merge or cleanup whose landing the
  writer refuses as `stopped`, the step's message kept (`wrapper.landed_outcome`), as
  it does a triage naming no records, since a refusal raised inside `record_outcome`
  would leave the run without a line; unit tests in `test_change_workflow_wrapper.py`
  (`test_a_merge_whose_landing_the_writer_refuses_is_logged_stopped`,
  `test_a_merge_recording_its_landing_is_logged_as_it_ended`) pass. The shared fixtures
  gain `LANDED` and `ACCEPTING`, `make_wrapper` passes `ACCEPTING`, and
  `test_change_next_step._log` gives a finished merge or cleanup `LANDED`, so the
  routing tests record merges as the writer now requires.
- [x] 1.3 Make the log's writer, for a `finished` archive cleanup line, resolve the
  source as cleanup does — the last finished merge's `landing.remote` and
  `landing.branch`, else the clone marker's `base` — refuse the line without a
  well-formed `landing` whenever a source resolves, on every run, reruns included, and
  record on the line whether the line's commit contains the recorded commit (D10, D5;
  26 F1). Verify: unit tests in `scripts/tests/test_change_workflow_log.py` show a
  cleanup line refused without `landing` when the last merge recorded one and when only
  the clone marker resolves, recorded without it when neither resolves, and the
  recorded containment true and false, mapping "The merge before closeout was given
  another branch" (the source resolved from the merge's `landing`, not the clone's) and
  the writer's half of "Archive cleanup's fetch fails"; a library-integration test
  computes the containment against a real repository.
  Done: `log.landing_source` resolves the source (the latest finished merge line
  recording `landing`, else `Checkout.base`, the clone marker's `base`); the
  containment is recorded on the line as `landing_contained` (`log.CONTAINED`), the
  field section 3's guard reads. A cleanup line's remote is not checked against the
  checkout's remotes, nor its branch against the source: the delta asks only that it
  be well-formed there, and which branch cleanup fetches is the skill's text. Unit:
  `test_a_cleanup_line_without_landing_is_refused_when_a_source_resolves` (merge,
  clone; and again for a rerun after a finished cleanup line),
  `test_a_cleanup_line_without_a_source_records_no_landing`,
  `test_a_cleanup_line_records_whether_its_commit_contains_the_landing` (true, false),
  `test_cleanup_fetches_the_branch_the_merge_was_given` — the source resolved from the
  merge's `landing`, not the clone's, and named in the refusal — pass. Library
  integration:
  `test_the_writer_records_a_cleanups_containment_in_a_real_repository` passes.
  Fix (34 F1, the owner chose the writer's check): the writer now refuses a finished
  cleanup line whose `landing` is not what cleanup fetched from the source it resolves
  — the source's branch; the source's remote where that is `.` or one of the
  checkout's, else any of the checkout's or `.`; the commit the checkout's ref for that
  remote and branch names as the line is written, compared for equality — so the
  sentence above that left the remote and branch to the skill no longer holds (D10,
  CW-5vkd, with the scenario "Archive cleanup records another source than it
  fetched"). A cleanup that skips its fetch while the ref is unmoved since the merge's
  still passes; D10 records that limit. `log._cleanup_landing_problems`,
  `log.landing_ref`, `Checkout.resolve`, and `records.git_resolve`;
  `change-archive-cleanup` says what the writer refuses and asks the owner for a
  remote, not a branch, when the recorded remote is absent; `index.md`'s CW-5vkd
  summary updated. Unit (an injected `Checkout`):
  `test_cleanup_fetches_the_branch_the_merge_was_given` gains the reviewer's
  regression (the merge names `main`, cleanup records `dev`, refused before
  containment is read), `test_a_cleanup_lines_remote_is_the_source_it_fetched_from`
  ×9, `test_a_cleanup_lines_commit_is_the_one_its_fetch_left` ×6 (fetched, stale, no
  ref; `origin` and `.`). Library integration (a real Git repository):
  `test_the_writer_refuses_a_cleanups_stale_commit_in_a_real_repository` (`origin/dev`,
  and `.` read from `refs/heads/dev`); the existing cleanup test now fetches the ref
  it checks. `test_change_workflow_log.py`, `test_change_next_step.py`,
  `test_change_workflow_wrapper.py`, `test_change_workflow_cli.py`,
  `test_change_workflow_cli_steps.py`, `test_change_workflow_outcome.py`,
  `test_check_agent_skills.py`, `test_change_workflow_steps.py`: 871 passed; `make
  check-agent-skills` passes. `scripts/change-workflow run pre-commit
  merge-after-archive` on the fixes: "after-functional-change … passed, exit 0",
  "pre-commit-functional … passed, exit 0" (`make test` and the packaging check),
  "pre-commit … passed, exit 0"; no hook rebuilt a file. Fresh-context check against `c5fd1e31d`: no blocking
  defect; fixed — the skill let the owner name another branch the writer would refuse,
  its sentence understated the remote rule, the delta left the no-source case
  implicit, and the tests did not show the refusal precedes containment, cite the new
  scenario, or take `.` through Git; declined — `records.git_resolve` repeats
  `clone._ref`'s `rev-parse`, a merge of two modules' helpers outside the fix.
  End-to-end: none; no scenario exercises the workflow tooling. Owed by validation:
  the pipeline rerun 35 V1's disposition asks for.
- [x] 1.4 Make `start merge` (`cli.merge_arguments`) bring in the branch it is given,
  else the last finished merge's `landing.branch` read from the change's log, else the
  clone marker's `base` (`find.landing_branch`), and refuse with none, naming `FROM`;
  it takes the branch name alone, never the recorded remote (D10, CW-s3ju). Verify:
  unit tests in `scripts/tests/test_change_workflow_cli_steps.py` mapping the delta
  scenarios "A change worked in place merges with no base given", "The merge before
  closeout is repeated after a review of it", "A merge after the archive of a change
  worked in place", and "An older log records no branch".
  Done: `cli.merge_arguments` reads `log.recorded_landing` from the change's log;
  `find.py` needed no edit. Library integration — each runs `git` in a temporary
  directory, since `find.landing_branch` reads the clone marker through `git
  rev-parse`, and the clone case holds a real marker: `test_change_workflow_cli_steps.py`
  (`test_a_change_worked_in_place_with_no_recorded_merge_needs_its_branch`,
  `test_the_merge_repeated_after_its_review_brings_in_the_branch_it_was_given`,
  `test_a_merge_after_the_archive_of_a_change_worked_in_place`,
  `test_an_older_log_records_no_branch`) passes; the existing start tests in
  `test_change_workflow_cli.py` still pass.
- [x] 1.5 Teach `change-merge` to end every `finished` outcome with `landing` — the
  remote it fetched from as its checkout names it, `.` for a branch the checkout holds,
  the branch, and the commit fetched, whether or not anything merged — and a repair to
  carry the `landing` of the merge it repairs, read from the log, omitting it only when
  no finished merge recorded one (D10). Teach `change-archive-cleanup` to fetch the
  source the last finished merge's `landing` names, else the clone's recorded branch;
  to ask the owner when the recorded remote is not one of its checkout's; for `.`, to
  fetch nothing and record that branch's commit; to end `stopped`, naming the fetch,
  when the fetch fails; and to end every `finished` outcome with `landing` (D10, D5).
  Teach `change-orchestrate` to pass `FROM` to `make merge` only when the owner names
  another branch (D10, 26 F2). Verify: `make check-agent-skills` passes; each skill
  states the fields its outcome carries, as the schema of 1.1 defines them; the
  archive cleanup skill's text answers the delta scenarios "A merge in a clone fetched
  from the workspace", "The recorded remote is absent from cleanup's checkout", and
  "Archive cleanup's fetch fails".
  Done: `change-merge` states the record in its opening, its outcome, step 3.1 (`git
  rev-parse <remote>/<base>`), and the repair; `change-archive-cleanup` gains step 1's
  "Landing branch" check, run on reruns too, reading the whole log (`grep` of
  `workflow.jsonl`, since `log --last` reads a window) and `find --json`; it reads the checkout's remotes from its Git configuration (`git
  rev-parse --git-path config`), since no step's rules allow `git remote`.
  `change-orchestrate`'s merge paragraph passes `FROM` only when the owner names
  another branch. `make check-agent-skills` passes.
- [x] 1.6 Orchestrator's, on the owner's word, before this section's session starts:
  add `Bash(git fetch origin *)` and `Bash(git fetch workspace *)` to
  `[steps.archive-cleanup]` in `.claude/change-steps.toml`, under a comment saying
  archive cleanup fetches the branch the last merge brought in (D10). The section's
  session commits it with the section. Verify: `pytest -q
  scripts/tests/test_change_workflow_steps.py` passes; the row loads with both rules.
  Done: the edit was in the worktree and is committed with the section;
  `test_change_workflow_steps.py` passes. Owed: its comment ends "(D10)", a citation
  of this change's design that AGENTS.md's comment rule forbids (the hygiene check
  does not catch it); no step may edit `.claude/`, so the orchestrator removes it,
  on the owner's word, in a commit of its own before the round's review.
  Fix (34 F2): the orchestrating session dropped "(D10)" on the owner's word during
  the round's triage, and the triage's fix commit carries it.
- [x] 1.7 Verification: `pytest -q scripts/tests/test_change_workflow_outcome.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_cli_steps.py
  scripts/tests/test_change_workflow_steps.py scripts/tests/test_find_change.py` (unit,
  and library integration where a real Git repository is used) passes; `make
  check-agent-skills` passes; `scripts/change-workflow run pre-commit merge-after-archive`
  passes, which runs `make test`. End-to-end: none; no scenario exercises the workflow
  tooling.
  Done: the named suites (390 passed, with `test_check_agent_skills.py` and
  `test_change_workflow_assumptions.py`), `test_change_workflow_wrapper.py`,
  `test_change_workflow_cli.py`, and `test_change_next_step.py` pass; `make
  check-agent-skills` and `make check-comment-hygiene` pass. `scripts/change-workflow
  run pre-commit merge-after-archive` passed (`after-functional-change`,
  `pre-commit-functional` with `make test` and the packaging check, and `pre-commit`
  with the repository's checks) on the section's work before the fresh-context
  check; its fixes — the skills' log reading, the rerun case in the cleanup test, and
  these notes — were checked again by `make check-agent-skills` and the log suite. A
  second pre-commit run overlapped section 2's edits in the worktree and is not
  evidence for this section. End-to-end: none, confirmed; no scenario in
  `e2e-tests/` exercises the workflow tooling. Owed by validation: none.

## 2. The graph declares the merge after the archive, its review, and cleanup's first-exit guard (D1, D2, D4, D5, D6, D8)

Delivers the table's new nodes, exits, guards, and entry guards, what the entry guards
read, the review command's archive check for the new kind, and the diagram held to the
table. Implements D1's node and entry guards, D2's kind, D4's triage exits, D5's guard
on archive cleanup's exit, D6's validation guards, D8's absent returns, and the delta
requirements CW-m4qe (entry), CW-r2hu (graph), CW-xo82, CW-tnp6, and CW-9tzd. Touches
`scripts/change_workflow/graph.py`, `log.py` (`standing`), `review.py`, and
`openspec/specs/change-workflow/diagrams/change-workflow-graph.drawio` and `.svg`.

- [x] 2.1 Declare in `graph.py` (D1, D2, D4, D6, D8): `late-merge`, `runs="merge"`,
  phase closeout, entry guards the archive, that archive cleanup has run, and that the
  change's index row says `archived`, its exits archive cleanup — guarded by the merged
  `HEAD` validated, inert paths exempt — and `review:merge` — guarded by the merged
  `HEAD` validated, records exempt — each failed validation naming `late-merge`;
  `review:merge`, entry guard the archive, its exit `triage:merge`; `triage:merge`,
  entry guards the archive and a review of its kind awaiting triage, exits advance to
  archive cleanup and another round to `review:merge`, each guarded by a fix outside the
  inert paths validated (`_fix_validated(INERT)`); no return on any of them. Keep
  `merge`'s exits and its `NOT_ARCHIVED` guard. Verify: unit tests in
  `scripts/tests/test_change_workflow_graph.py` show each node's exits, guards, and
  entry guards; `KINDS` holds `merge`; `STEPS` gains no step; `cli.ACTIVE_ONLY` no
  longer holds `merge`; `node_of({"step": "late-merge"})` is the node.
  Done: `graph.LATE_MERGE`, `MERGE_REVIEW`, `MERGE_TRIAGE`; guards
  `LATE_MERGE_VALIDATED` (inert exempt) and `LATE_MERGE_REVIEW_VALIDATED` (records
  exempt), each `failed=LATE_MERGE`; the triage reuses `DOCUMENTED_FIX_VALIDATED`; the
  entry guards `CLEANED_UP` and `ROW_ARCHIVED` read the two new `Standing` fields
  (2.3). The review exit is labelled "a review". Unit: `test_change_workflow_graph.py`
  (`test_the_merge_after_the_archive_runs_the_merge_step_once_cleanup_has_run`,
  `test_the_merge_review_and_its_triage_follow_the_archive_and_return_nowhere`,
  `test_the_merge_after_the_archive_adds_no_step`,
  `test_the_merge_after_the_archive_is_entered_once_cleaned_up_with_its_row` ×4)
  passes. `start merge` now takes an archived change
  (`test_change_workflow_cli.py::test_start_takes_an_archived_change_for_the_merge_after_the_archive`;
  the merge dropped from the archived-refusal parameters). Consequences the table
  carries by itself: `phase_steps("closeout")` gains `merge`, `review_phase("merge")`
  is closeout, and `next_step._STEP_PHASE["merge"]` is None, since the merge now runs
  in two phases, so a status set back by hand is never compared with a merge line —
  as with a review or a triage (`test_change_workflow_common.py` updated, the comment
  in `next_step` says so). The validation node's exits to archive cleanup keep the
  closeout triage's guard only: `_remedying` keeps the first exit per target and
  label, as for every target several nodes exit to.
- [x] 2.2 Declare the guard on archive cleanup's exit to `done` (D5, CW-5vkd): it holds
  for any archive cleanup run but the first in the log, for a first run whose line
  records no `landing`, and for one whose recorded containment is true; otherwise its
  remedy is `late-merge`. It reads a new `Readings` method over the run's line alone,
  which section 3 supplies. Verify: unit tests in
  `scripts/tests/test_change_workflow_graph.py`, with fake readings, show the guard met
  and unmet in each of those cases, naming `late-merge` and carrying `done`.
  Done: `graph.LANDING_CONTAINED` on archive cleanup's exit, its check reading
  `Readings.landing_moved(run)`. Correction to the plan: the reading,
  `next_step.Computation.landing_moved`, is supplied in this section, not section 3,
  since without it every routing test whose route reaches archive cleanup's exit fails
  at this commit. It holds the cases on the line alone: the first archive cleanup run
  to *finish* (a stopped run, as on a failed fetch, took no exit, so the rerun that
  finishes is the first), its line carrying `landing` and `landing_contained` false.
  Unit: `test_change_workflow_graph.py::test_archive_cleanups_exit_to_done_waits_for_the_landing_branch`
  (fake readings, met and unmet; the guard's remedy is `late-merge`; carrying `done` is
  the computation's `guarded`, tested in 3.3), and
  `test_change_next_step.py::test_the_landing_moved_only_on_the_first_cleanups_recorded_result`
  (moved, contained, no landing, a later run; lines written by the real writer with an
  injected checkout), `test_a_cleanup_finishing_after_a_stopped_fetch_is_the_first_to_take_its_exit`,
  and `test_a_cleanup_line_without_its_recorded_containment_reads_as_checked` pass. The
  guard's result names the node, `{"step": "late-merge"}`; naming the merge step for
  it is 3.3's. Outside the plan: `_fix_validated`'s reason said the triage "records
  another round", wrong once the guard sits on `triage:merge`'s advance too; it now
  says the triage records a fix committed since its review read `HEAD`.
- [x] 2.3 Extend `Standing`, and `log.standing`, with whether an archive cleanup run has
  finished and whether the change's index row says `archived`, so the log's writer
  refuses a direction the new entry guards refuse (D1, 18 F2). Verify: unit tests in
  `scripts/tests/test_change_workflow_log.py` map the delta scenarios "A merge after the
  archive is directed before archive cleanup", "A merge after the archive is directed
  for a change whose row was pruned", "A merge review is directed for a change not
  archived", and "The owner directs implementation of an archived change"; directing
  `done` is still refused.
  Done: `Standing.cleaned_up` (a finished archive cleanup line in the log) and
  `Standing.row_archived` (`log._row_archived`, reading the index of the repository
  holding the change's directory, the change's name from `find.change_name`), both
  defaulting to False. Unit: `test_change_workflow_log.py`
  (`test_the_standing_reads_cleanup_and_the_archived_row`,
  `test_a_merge_after_the_archive_is_directed_once_cleanup_has_run`, and the four
  scenarios by name, the last with `round` and `done`) passes. Of "The owner directs
  implementation of an archived change" only the writer's refusal is shown here, by
  `round`'s existing archive guard; that the merge's question then still waits on the
  owner is the computation's, read in section 3.
- [x] 2.4 Make the review command refuse a review of a kind whose node needs the archive
  — `closeout` and `merge` — for a change not archived, reading the entry guard from the
  table rather than naming the kinds (D2, CW-xo82). Verify: a unit test in
  `scripts/tests/test_change_workflow_review.py` shows `merge` refused for an active
  change and accepted for an archived one; the existing closeout case still passes.
  Done: `review.run_review` refuses a kind whose `review:<kind>` node carries
  `graph.ARCHIVED`. Unit (the reviewer injected):
  `test_a_merge_review_of_an_active_change_is_refused`,
  `test_a_merge_review_of_an_archived_change_is_recorded_in_the_archive`, and the
  closeout case pass.
- [x] 2.5 Draw the new nodes, exits, guards, and entry guards in
  `openspec/specs/change-workflow/diagrams/change-workflow-graph.drawio`, and export
  its `.svg` with the source embedded (CW-66kx). Verify: `scripts/change-workflow check
  graph` succeeds; `test_the_documented_diagram_draws_the_table` and
  `test_the_export_embeds_the_diagram_it_draws` pass.
  Done: three boxes beside the closeout column (`review_merge`, `triage_merge`,
  `late_merge`), seven edges, `G14`–`G16` in the legend, and `G14` on archive
  cleanup's exit to `done`. The export's visible part is hand-written SVG, as the
  existing export is, and its embedded source carries the same edits, geometry and
  label offsets included (the tests compare only boxes, edges, and labels; the
  geometry was compared by reading).
  `scripts/change-workflow check graph` is not allowed in an implementation step's
  rules, so the comparison ran through its tests, which call the same `diagram.drift`:
  `test_the_documented_diagram_draws_the_table`,
  `test_the_export_embeds_the_diagram_it_draws`,
  `test_make_change_graph_reports_that_the_diagram_draws_the_table`, and
  `test_change_workflow_command.py::test_the_command_compares_this_checkouts_graph_diagram`
  (which runs `scripts/change-workflow check graph` itself) pass. The visible SVG was
  not rendered in this session; its coordinates follow the existing export's.
- [x] 2.6 Verification: `pytest -q scripts/tests/test_change_workflow_graph.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_review.py
  scripts/tests/test_change_workflow_cli.py scripts/tests/test_change_workflow_convert.py`
  (unit) passes; `scripts/change-workflow check graph` succeeds; `scripts/change-workflow
  run pre-commit merge-after-archive` passes. End-to-end: none; no scenario exercises
  the workflow tooling.
  Done: the named suites with `test_change_workflow_common.py`,
  `test_change_workflow_command.py`, `test_change_next_step.py`, `test_find_change.py`,
  and `test_change_workflow_cli_steps.py` (882 passed) pass; `make check-history-wording`
  and `make check-local-imports` pass. `scripts/change-workflow run pre-commit
  merge-after-archive` passed on the section's work (`after-functional-change`,
  `pre-commit-functional` with `make test` and the packaging check, `pre-commit` with
  the repository's checks); the fresh-context check's fixes after it — comments, the
  fix guard's reason, four label offsets, two reading tests, these notes — were
  checked again by the graph, next-step, command, and CLI suites (486 passed).
  End-to-end: none, confirmed. Owed by validation: none.
  Handoff: section 1's commit was made on its own, but its guarded push refused the
  worktree holding this section's edits, so both commits are pushed together with this
  one.

## 3. The computation routes an archived change (D1, D5)

Delivers the run rule that tells the merge after the archive from the merge before
closeout, the route read for an archived change, the order in which `done` is
answered, the reading cleanup's guard needs, and the result naming the step to run.
Implements D1's run rule, D5, and the delta requirements CW-j7wp, CW-m4qe (the run
rule), CW-5vkd (the guard's reading), and CW-9tzd. Touches
`scripts/change_workflow/next_step.py` and `log.py` (`ran`, `unused_direction`).

- [x] 3.1 Read a `merge` run logged after an `archive-cleanup` run as a run of
  `late-merge`, in `next_step._run_node` and in `log.ran`, so routing, a direction's
  use, and `merge_waiting` see the right node (D1, CW-m4qe). Verify: unit tests in
  `scripts/tests/test_change_next_step.py` and `test_change_workflow_log.py` show a
  merge run before archive cleanup routed on `merge`'s exits and one after it on
  `late-merge`'s, and a `late-merge` direction spent by the merge run after it.
  Done: `log.after_cleanup(entry, entries)` (any archive cleanup line logged before
  the run); `log.ran` gains the log's lines as a third argument, passed by every
  caller (`route_of`, `unused_direction`, `in_progress`, and `convert`'s proposal), and
  `next_step._run_node` the log, both required, so no caller reads every merge as the
  merge before closeout by leaving it out. `merge_waiting` compares the step name,
  which both nodes share, so it needed no edit. Unit:
  `test_change_workflow_log.py::test_a_merge_run_is_the_merge_after_the_archive_once_archive_cleanup_ran`,
  and in `test_change_next_step.py`
  `test_a_merge_run_before_archive_cleanup_and_one_after_are_different_nodes` (the
  route's source node; the exits each is routed on are the 3.4 tests') and
  `test_a_direction_to_the_merge_after_the_archive_is_spent_by_the_merge_after_it`
  (a question does not spend it) pass. `ran`'s use through `in_progress` and
  `convert`'s proposal is exercised only by their existing tests, with no merge
  after the archive in them.
  Fix (42 F1, the owner chose (A)): a merge run by hand on an archived change before
  `late-merge` existed — finished after archive cleanup, no `landing`, no finished
  merge before it recording one, as the owner's workspace holds — was read as an
  undeclared `late-merge` exit to `done`, so its change named the owner.
  `log.unrouted_merge` reads such a line as a run of neither merge node: `route_of`
  skips it, so the route stays at archive cleanup's exit, and `ran` matches it to
  neither node. `log._repairs_unrecorded` no longer exempts a merge once archive
  cleanup ran, so only an older line has that shape. D1, CW-m4qe's run rule, CW-j7wp
  (with the scenario "A merge was run by hand after archive cleanup before the merge
  after the archive was a node"), and CW-5vkd's "MAY omit" say so. Unit:
  `test_change_next_step.py::test_a_merge_run_by_hand_after_archive_cleanup_before_the_record_existed`
  (`done`) and
  `::test_a_merge_recording_no_landing_after_one_that_did_is_the_merge_after_the_archive`;
  `test_change_workflow_log.py::test_a_finished_merge_after_cleanup_without_landing_is_neither_merge_unless_one_landed`
  ×2 and `::test_a_merge_after_archive_cleanup_is_never_a_repair_without_landing`.
  `test_change_workflow_log.py`, `test_change_next_step.py`,
  `test_change_workflow_wrapper.py`, `test_change_workflow_cli.py`,
  `test_change_workflow_cli_steps.py`, `test_change_workflow_outcome.py`,
  `test_change_workflow_convert.py`, `test_change_workflow_graph.py`: 948 passed.
  `scripts/change-workflow run pre-commit merge-after-archive`: "after-functional-change
  … passed, exit 0", "pre-commit-functional … passed, exit 0" (`make test` and the
  packaging check), "pre-commit … passed, exit 0"; no hook rebuilt a file.
  Fresh-context check against `4f07bf898`: fixed — CW-m4qe's run rule contradicted the
  new CW-j7wp sentence; the writer's repair exemption could still admit a landing-less
  merge after archive cleanup; three over-long lines in `design.md` and `tasks.md`.
  Nothing declined. End-to-end: none; no scenario exercises the workflow tooling.
  Owed by validation: the fix commit's, before the merge.
- [x] 3.2 Answer `done` for an archived change from the route, in this order (D5,
  CW-j7wp; 11 F3, 18 F2): a newer log and an undeclared line refused first; then a
  change with a live clone named to its clone, or, in that clone, computed there;
  otherwise `done` when the route ends at archive cleanup's exit to `done`, or the
  change has no log, with or without an index row, before any check of the branch
  checked out; only a route with a step to run goes on to `locate`'s branch checks and
  to the row, naming the owner when the index has no row. Remove the archived-row
  shortcuts in `Computation.run` and `Computation.route`. Verify: unit tests in
  `scripts/tests/test_change_next_step.py` mapping the delta scenarios "The owner's
  direction follows done", "An archived change in its clone is computed in the
  workspace", "An archived change without a clone, another branch checked out", "A
  merge after the archive directed without the branch", and "An archived change whose
  row was pruned".
  Done: `Computation.run` refuses a newer log and an undeclared line, then, for an
  archived change, `locate_clone` (the clone half of `locate`, split from its branch
  half, `locate_branch`) and `archived_done`, before `locate_branch`; the row is read
  only after, an archived change with no row and a step to run naming the owner. The
  shortcuts in `run` and `route` are gone; `route` reads an `archived` row as the
  closeout phase, so a merge's question after the archive waits in `pending`.
  `archived_done` answers `done` when the route is archive cleanup's exit to `done`
  with its guard met, or when the change has no log at all; an archived change whose
  log is of an older format goes on to the conversion's owner result, as any change
  does. An archived change whose clone was left unfinished is still named to `make
  change-clone`, as `locate` names any change's. Unit: the five scenarios by name,
  `test_an_archived_change_with_no_log_is_done`,
  `test_an_archived_changes_undeclared_line_is_refused_before_done` (the first step
  of the order), `test_a_merge_after_the_archive_directed_in_the_clone_is_computed_there`,
  and the existing next-step suite pass.
- [x] 3.3 Supply the reading cleanup's exit guard declares (2.2), over the run's line
  alone, and name `late-merge` in a result as the step to run, `{"step": "merge", …}`,
  the node in its reason (D5, CW-5vkd). Verify: unit tests in
  `scripts/tests/test_change_next_step.py` mapping "The landing branch moved during
  closeout", "The landing branch moves after the pull request opened", "The landing
  branch moved after a merge after the archive", "A change archived before the record
  existed", and CW-9tzd's "Archive cleanup finishes".
  Done: the reading was supplied in section 2 (see 2.2). `graph.Node.result` names the
  merge step for `late-merge` (`_RUN_BY`), its reason prefixed `late-merge: `, so a
  guard's remedy, a failed validation's, and a direction all name it so. Unit: the
  five scenarios by name in `test_change_next_step.py`, and the graph test's moved
  case, now asserting `{"step": "merge"}`, pass. "Moves after the pull request
  opened" is shown by the computation reading no ref at all: nothing but the line
  is an input, so no fetch can be simulated against it.
- [x] 3.4 Route the loop end to end (D3, D4, D6; CW-x9tb, CW-r2hu, CW-tnp6): a merge
  after the archive naming `review:merge` or archive cleanup, each through its
  validation guard; a failed validation naming `late-merge` carrying the exit, an
  inconclusive one the owner; `triage:merge` advancing to archive cleanup through a
  validation of its fix; and the owner's waiver as a direction to the exit the merge
  named. Verify: unit tests in `scripts/tests/test_change_next_step.py` mapping "The
  landing branch has gained nothing", "Both changes edited one specification", "Only
  the change index conflicted", "The owner waives only the validation of a merge that
  named its review", "A merge review's triage commits a code fix", and "A validation of
  HEAD merged after the archive fails".
  Done: no code beyond 3.1–3.3; the table routes it. Unit, in
  `test_change_next_step.py`: the six scenarios by name (the last for both exits, with
  its inconclusive case), `test_a_merge_reviews_triage_names_another_merge_review`, and
  `test_the_owner_directs_implementation_of_an_archived_change_while_the_merge_asks`,
  which shows the computation's half of CW-xo82's scenario section 2 left open, pass.
  "Only the change index conflicted" shows the computation naming archive cleanup;
  that the orchestrating session asks nothing is the skills' (section 4).
- [x] 3.5 Verification: `pytest -q scripts/tests/test_change_next_step.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_graph.py
  scripts/tests/test_change_clone.py scripts/tests/test_change_workflow_cli_steps.py`
  (unit, and library integration where a real clone is used) passes;
  `scripts/change-workflow run pre-commit merge-after-archive` passes. End-to-end:
  none; no scenario exercises the workflow tooling.
  Done: the named suites with `test_change_workflow_convert.py`,
  `test_change_workflow_cli.py`, and `test_change_workflow_common.py` pass (868 with
  the routing tests and the fresh-context check's fixes); `make check-history-wording`,
  `make check-local-imports`, and `make check-comment-hygiene` pass.
  `scripts/change-workflow run pre-commit merge-after-archive` passed on the finished
  section (`after-functional-change`, `pre-commit-functional` with `make test` and the
  packaging check, `pre-commit` with the repository's checks); an earlier run that
  overlapped the fresh-context check's fixes is not counted. End-to-end: none,
  confirmed. Owed by validation: none. Handoff: `graph._RUN_BY` names the step that
  runs `late-merge` beside the table's `runs="merge"`, kept by hand — a node named for
  no step of its own is rare enough that deriving it was not worth a rule telling it
  from the round, whose result names `round`, not `implement`.

## 4. The skills carry the merge after the archive (D3, D4, D6, D7, D8)

Delivers the skill text each step of the loop follows. Implements D3's judgement and
its criteria, D4's rerun, D6's waiver, D7's resolution rules, D8's questions in place
of a return, and the skill side of the delta requirements CW-x9tb, CW-r2hu, CW-p8fy,
and CW-g3zn. Touches `.agents/skills/change-merge/SKILL.md`, `change-review/SKILL.md`,
`change-triage/SKILL.md`, `change-archive-cleanup/SKILL.md`, and
`change-orchestrate/SKILL.md`.

- [x] 4.1 Give `change-merge` a section for an archived change (D3, D6, D7, D8;
  CW-x9tb, CW-g3zn): its route check accepts the computation naming the merge for
  `late-merge`; it resolves as before closeout and also keeps this change's row
  `archived` and its archived directory, keeps both sides in `openspec/specs/`, each
  `index.md`, and the permanent documents, releases a dependent row the landing branch
  brought as archive cleanup's step 3 does, keeps the capacity figure measured later,
  and never sets `ready for closeout`; it appends a note on what it merged and how it
  was validated to `reviews/pull-request.md`; it judges the merge review on D3's written
  criteria and names that exit or archive cleanup's, without asking; it recommends a
  waiver of the validation only on the guide's criteria, the waiver being the owner's
  direction to the exit it named; it asks the owner, the merge left in progress, where
  both sides cannot hold or the design no longer does, and declares no return. Verify:
  `make check-agent-skills` passes; the section states each D7 rule and each D3
  criterion.
  Done: `change-merge` gains "After the archive" — the D7 rules (index row kept
  `archived`, a dependent released as archive cleanup's step 3 does, the archived
  directory, both sides in `openspec/specs/`, `index.md`, and permanent documents,
  the later capacity figure, never `ready for closeout`, a note appended to
  `reviews/pull-request.md` saying what it merged and how `HEAD` is to be validated,
  archive cleanup run again appending the result), the four D3 criteria, the D6
  waiver as the owner's direction to the exit named with its interactive command,
  and D8's question in place of a return — and its route check, step 2, step 3.1,
  step 7, outcome bullet, and description point to it. `make check-agent-skills`
  passes. The D3 criterion "a file both sides changed since the merge base" is
  written outside the mechanical files, since a conflicted index row is changed by
  both sides and the delta's scenario "Only the change index conflicted" names
  archive cleanup. The pre-closeout triage gave CW-x9tb and D3 the same exception
  (42 F2); closeout's promotion (5.9) confirms the index summary and README match.
- [x] 4.2 Give `change-review` the `merge` kind (D2, CW-r2hu): its description and kind
  list name it, and a section asks what a merge after the archive did — each
  resolution against both parents (`git show --remerge-diff`) and every commit since
  the merge's first parent, each permanent specification and index it touched for both
  changes' meaning with ids unique, and the change's code and end-to-end scenarios
  against what the landing branch renamed, removed, moved, or changed in meaning.
  Verify: `make check-agent-skills` passes; `pytest -q
  scripts/tests/test_change_workflow_review.py` passes.
  Done: description, kind list, the change directory and diff for the kind, and a
  "Merge review" section of four questions (resolutions against both parents and
  every commit since the first parent; specifications, indexes, permanent documents,
  and the change index for both changes' meaning; the code and scenarios against
  what the landing branch changed; readiness for archive cleanup). `make
  check-agent-skills` and `test_change_workflow_review.py` pass.
- [x] 4.3 Give `change-triage` the `merge` kind (D4, D8, CW-r2hu): its exits are archive
  cleanup on advancing and another merge review, with no return; a finding needing a
  code fix is fixed in the triage and validated by its exit's guard. Verify: `make
  check-agent-skills` passes; the section names both exits and no return.
  Done: the exit table's row (archive cleanup; another merge review; no return), the
  status table's row (`archived`, unchanged), a "fix, at a merge review's triage"
  outcome, and step 1's and step 5's archived-change wording. `make
  check-agent-skills` passes.
- [x] 4.4 Make `change-archive-cleanup` accept `late-merge` and `triage:merge` as its
  routes in, and, on a row already `archived`, append what its cleanup reported to
  `reviews/pull-request.md` rather than redraft it (D4, CW-p8fy). Verify: `make
  check-agent-skills` passes; the skill's status check names both routes.
  Done: the Route check names both routes in on an `archived` row, which now runs
  the Route and Landing branch checks before steps 7 to 10, never releasing,
  editing the row, or redrafting; step 8 already appended on a rerun. The
  "Running interactively" paragraph said the computation names `done` for an
  archived row whatever the log holds, false since section 3; it now says `done`
  comes only from a finished cleanup line. `make check-agent-skills` passes.
- [x] 4.5 Make `change-orchestrate` record the owner's direction to `{"step":
  "late-merge"}` on their word, run the merge the computation names after the archive
  as any merge, record a waiver of the merged `HEAD`'s validation as a direction to the
  exit the merge named, and say that at `done` an advanced landing branch is the owner's
  to direct a merge for (D1, D5, D6). Verify: `make check-agent-skills` passes.
  Done: a paragraph after the merge before closeout — archive cleanup's first exit
  run without asking, the owner's direction recorded on their word with its command,
  the writer's refusals relayed, the merge's exit followed, a waiver recorded as a
  direction to the exit named with its command, no return, and `done` leaving a
  moved landing branch to the owner — the refusals list, and the pull request at
  `done` after a merge after the archive (no second one; the appended notes
  relayed). `make check-agent-skills` passes.
- [x] 4.6 Verification: `make check-agent-skills` passes; `pytest -q
  scripts/tests/test_check_agent_skills.py scripts/tests/test_change_workflow_assumptions.py`
  (unit) passes; `scripts/change-workflow run pre-commit merge-after-archive` passes.
  End-to-end: none; no scenario exercises the skills.
  Done: `make check-agent-skills` passes; the two suites with
  `test_change_workflow_review.py` pass (104). The fresh-context check found, and
  this section fixed: archive cleanup's rerun skipping a validation its route still
  owed (it now stops on one, runs the Worktree check, writes a waiver's ledger
  line, and appends the validation's result); the orchestrator assuming a pull
  request exists at `done` after a merge after the archive; no interactive waiver
  command after the archive; stale wording in archive cleanup's description and
  introduction, the triage's fix procedure, the merge's step 2 and 3.1, the
  orchestrator's refusals (a `merge` direction for an archived change), and the
  review's merge base and inert-path exemption; the dependent release restated in
  full. Declined: a closeout direction for an archived change is accepted by the
  log's writer, since closeout carries no entry guard (it is the step that
  archives); the closeout skill refuses it itself, and guarding the table is outside
  this change. `scripts/change-workflow run pre-commit merge-after-archive` passed on
  the finished section, after those fixes (`after-functional-change`,
  `pre-commit-functional` with `make test` and the packaging check, `pre-commit`).
  End-to-end: none, confirmed. Owed by validation: none. Handoff: the round's
  sections are all committed; the `(D10)` in the step table's comment (1.6) is still
  owed by the orchestrator.

## 5. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [ ] 5.1 Comment hygiene: run `make check-comment-hygiene` and `make
  check-history-wording`, and read the comments sections 1–3 added for any naming the
  review or change that introduced them; one that needs rewriting returns the change to
  implementation.
- [ ] 5.2 Import placement: run `make check-local-imports`, and confirm every import
  sections 1–3 added inside a function carries its reason; one that should move returns
  the change to implementation.
- [ ] 5.3 Documentation compliance: re-check D1–D10 against `openspec/README.md`'s
  placement rules and the destinations named in 5.9, and confirm the proposal's
  "Public interfaces" still names every public interface the change altered — the
  graph's vocabulary, `next`'s output for an archived change, `start merge`'s
  acceptance and default branch, cleanup's guard, and the outcome's `landing` — and
  whether each is compatible (CW-c2tw).
- [ ] 5.4 Narrative compression: shorten completed task notes to final behaviour,
  material evidence, and destinations; move anything implementation settled or declined
  into `design.md` first.
- [ ] 5.5 Roadmap currency: record in the promotion record that the change has no
  roadmap impact — `docs/development/ROADMAP.md` names neither the change nor the
  change workflow's area, and it closes no gap row there.
- [ ] 5.6 Campaign index currency: set the change's row, under "Independent active
  changes" in `openspec/changes/README.md`, to `in closeout`, its notes rewritten for
  closeout; the change has no campaign graph entry and no dependents. Run
  `scripts/change-workflow check index`.
- [ ] 5.7 Packaging: run `make check-packaging`, `make check-architecture-change
  CHANGE=merge-after-archive`, and `make check-agent-skills`, since the change touched
  `.agents/` and `.claude/`.
- [ ] 5.8 End-to-end pipeline: record the latest passing pipeline run, its commit, and
  that no scenario exercises the change's behaviour, the run being evidence only that
  the stack still builds and runs.
- [ ] 5.9 Promotion: write the permanent documents and the design-promotion record:
  - `openspec/specs/change-workflow/index.md`: its entries for CW-m4qe, CW-x9tb,
    CW-g3zn, CW-r2hu, CW-5vkd, CW-p8fy, and CW-j7wp, and its summaries of CW-1iaz
    (42 F3), CW-s3ju, CW-tnp6, CW-xo82, and CW-9tzd, written with the design: check
    each against the requirement as implemented and revise it where it no longer
    holds, CW-m4qe's and CW-j7wp's with the older hand-run merge that routes nothing
    (42 F1); no id is retired.
  - `openspec/specs/change-workflow/README.md`: "The owner is interrupted only for
    judgement" — the archive boundary paragraph (D8) and the principle that a step's
    judgement of its exit is followed unless the exit needs a waiver (D3); "The merge
    before closeout" — the merge after the archive, its review, its validation, its
    resolution rules, and the principle that detection runs by itself only where
    nothing it moves is under the owner's review (D1, D2, D4–D7), and which branch a
    merge brings in (D10); "Reviews are files" — the `merge` kind (D2); "The log, its
    format, and the conversion" — the outcome's `landing` and the containment recorded
    on cleanup's line (D10); "Routing is code, with the model as backstop" — the run
    rule, `done` from the route, the guard reading only the log, and the principle that
    the graph declares no exit wrong in a state its node can be in (D1, D5); "The
    orchestrator relays and routes" — the principle that the owner instructs the
    orchestrating session (D1); "History lives in the owner's workspace" — archive
    cleanup's rerun and the drafts appended to (D4, D7).
  - `docs/agents/change-workflow.md`: the Skills table's merge, review, and archive
    cleanup rows (D1, D2, D4, D10); "Directing a change" — the direction to
    `late-merge` (D1, D5); "The merge before closeout" — `make merge`'s branch and the
    outcome's `landing` (D10), followed by a paragraph on the merge after the archive
    (D1, D3–D7); "History and removal" — the rerun (D4); "Waivers" — the waiver of a
    merged `HEAD`'s validation after the archive (D6).
  - The graph diagram was drawn with the table in 2.5; confirm `scripts/change-workflow
    check graph` still succeeds.
  - `design.md`'s design-promotion record: a row for each of D1–D8 and D10 naming its
    destinations above, D9 recorded as having none.
- [ ] 5.10 Documentation citations: run `make check-doc-citations
  CHANGE=merge-after-archive` and resolve every match; then `scripts/change-workflow
  openspec validate merge-after-archive --strict`.
- [ ] 5.11 Archival: `openspec archive merge-after-archive -y`, merging the deltas into
  `openspec/specs/change-workflow/spec.md`; confirm the archived change is found by name
  (`scripts/change-workflow find merge-after-archive`).
