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
  Done: the schema holds the shape; `outcome.outcome_problems` checks the full object
  name (design, "Settled in implementation"). Unit: `test_change_workflow_outcome.py`
  passes. Destination: CW-5vkd, README "The log, its format, and the conversion".
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
  Done: `log.landing_problems`, the Git reads injected as `log.Checkout`; the wrapper
  and `record` pass `log.git_checkout`. How a repair is read, and the wrapper logging a
  refused landing `stopped` (outside the plan), are in design.md, "Settled in
  implementation". Unit: `test_change_workflow_log.py` (each scenario named above by
  name) and `test_change_workflow_wrapper.py` pass. Library integration (a real Git
  repository): `test_the_writer_checks_a_merges_landing_in_a_real_repository` passes.
  Destination: CW-5vkd.
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
  Done: `log.landing_source` resolves the source; the containment is recorded on the
  line as `landing_contained`, the field section 2's guard reads. Fix (34 F1, the
  owner chose the writer's check): the writer also refuses a cleanup line whose
  `landing` is not what cleanup fetched from that source — its branch, its remote by
  D10's rule, and the commit the checkout's ref names as the line is written
  (`log._cleanup_landing_problems`, `log.landing_ref`, `records.git_resolve`), with
  the scenario "Archive cleanup records another source than it fetched"; D10 records
  the limit of a skipped fetch while the ref is unmoved. Unit (an injected `Checkout`)
  and library integration (a real Git repository, `origin` and `.`) in
  `test_change_workflow_log.py`: 871 passed across the engine suites with the fix;
  `make check-agent-skills` and `run pre-commit` passed. Declined at the fresh-context
  check: one helper for two modules' `rev-parse` (design.md). End-to-end: none; no
  scenario exercises the workflow tooling. Owed by validation: the pipeline rerun 35
  V1's disposition asked for — run 42788045056 passed at `4f07bf898` (41), with every
  lane. Destination: CW-5vkd, README "The log, its format, and the conversion".
- [x] 1.4 Make `start merge` (`cli.merge_arguments`) bring in the branch it is given,
  else the last finished merge's `landing.branch` read from the change's log, else the
  clone marker's `base` (`find.landing_branch`), and refuse with none, naming `FROM`;
  it takes the branch name alone, never the recorded remote (D10, CW-s3ju). Verify:
  unit tests in `scripts/tests/test_change_workflow_cli_steps.py` mapping the delta
  scenarios "A change worked in place merges with no base given", "The merge before
  closeout is repeated after a review of it", "A merge after the archive of a change
  worked in place", and "An older log records no branch".
  Done: `cli.merge_arguments` reads `log.recorded_landing`. Library integration (a
  real clone marker read through `git`): the four scenarios by name in
  `test_change_workflow_cli_steps.py` pass. Destination: CW-s3ju, CW-5vkd, README
  "The merge before closeout", the guide's "The merge before closeout".
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
  Done: `change-merge` states the record in its outcome, step 3.1, and the repair;
  `change-archive-cleanup` gains step 1's "Landing branch" check, run on reruns too,
  reading the checkout's remotes from its Git configuration, since no step's rules
  allow `git remote`; `change-orchestrate` passes `FROM` only when the owner names
  another branch. `make check-agent-skills` passes.
- [x] 1.6 Orchestrator's, on the owner's word, before this section's session starts:
  add `Bash(git fetch origin *)` and `Bash(git fetch workspace *)` to
  `[steps.archive-cleanup]` in `.claude/change-steps.toml`, under a comment saying
  archive cleanup fetches the branch the last merge brought in (D10). The section's
  session commits it with the section. Verify: `pytest -q
  scripts/tests/test_change_workflow_steps.py` passes; the row loads with both rules.
  Done: committed with the section; `test_change_workflow_steps.py` passes. Fix (34
  F2): the comment's "(D10)", a citation of this change's design, was dropped by the
  orchestrating session on the owner's word in the round's triage.
- [x] 1.7 Verification: `pytest -q scripts/tests/test_change_workflow_outcome.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_cli_steps.py
  scripts/tests/test_change_workflow_steps.py scripts/tests/test_find_change.py` (unit,
  and library integration where a real Git repository is used) passes; `make
  check-agent-skills` passes; `scripts/change-workflow run pre-commit merge-after-archive`
  passes, which runs `make test`. End-to-end: none; no scenario exercises the workflow
  tooling.
  Done: the named suites (390 passed, with the skills and assumptions suites), the
  wrapper, CLI, and next-step suites pass; `make check-agent-skills` and `make
  check-comment-hygiene` pass; `run pre-commit` passed on the section's work, its
  fresh-context fixes checked again by the skills check and the log suite.
  End-to-end: none, confirmed. Owed by validation: none.

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
  Done: `graph.LATE_MERGE`, `MERGE_REVIEW`, `MERGE_TRIAGE`, the guards
  `LATE_MERGE_VALIDATED` and `LATE_MERGE_REVIEW_VALIDATED`, and the entry guards
  `CLEANED_UP` and `ROW_ARCHIVED`; `start merge` takes an archived change. The merge's
  two phases and the validation node's exits are in design.md, "Settled in
  implementation". Unit: `test_change_workflow_graph.py`,
  `test_change_workflow_cli.py`, and `test_change_workflow_common.py` pass.
  Destination: CW-m4qe, CW-r2hu, CW-xo82, README "Routing is code, with the model as
  backstop", the graph diagram.
- [x] 2.2 Declare the guard on archive cleanup's exit to `done` (D5, CW-5vkd): it holds
  for any archive cleanup run but the first in the log, for a first run whose line
  records no `landing`, and for one whose recorded containment is true; otherwise its
  remedy is `late-merge`. It reads a new `Readings` method over the run's line alone,
  which section 3 supplies. Verify: unit tests in
  `scripts/tests/test_change_workflow_graph.py`, with fake readings, show the guard met
  and unmet in each of those cases, naming `late-merge` and carrying `done`.
  Done: `graph.LANDING_CONTAINED`, reading `Readings.landing_moved(run)`. Correction
  to the plan: the reading, `next_step.Computation.landing_moved`, is supplied here,
  not in section 3, since every routing test reaching archive cleanup's exit needs
  it. Which run is first is in design.md, "Settled in implementation". Unit: the graph
  test (fake readings, met and unmet) and three next-step tests (lines written by the
  real writer) pass. Outside the plan: `_fix_validated`'s reason now says the triage
  recorded a fix since its review read `HEAD`, true of `triage:merge` too.
  Destination: CW-5vkd, CW-9tzd, README "Routing is code, with the model as backstop".
- [x] 2.3 Extend `Standing`, and `log.standing`, with whether an archive cleanup run has
  finished and whether the change's index row says `archived`, so the log's writer
  refuses a direction the new entry guards refuse (D1, 18 F2). Verify: unit tests in
  `scripts/tests/test_change_workflow_log.py` map the delta scenarios "A merge after the
  archive is directed before archive cleanup", "A merge after the archive is directed
  for a change whose row was pruned", "A merge review is directed for a change not
  archived", and "The owner directs implementation of an archived change"; directing
  `done` is still refused.
  Done: `Standing.cleaned_up` and `Standing.row_archived` (`log._row_archived`).
  Unit: `test_change_workflow_log.py`, the four scenarios by name, passes; the
  computation's half of the last is 3.4's. Destination: CW-m4qe, CW-xo82.
- [x] 2.4 Make the review command refuse a review of a kind whose node needs the archive
  — `closeout` and `merge` — for a change not archived, reading the entry guard from the
  table rather than naming the kinds (D2, CW-xo82). Verify: a unit test in
  `scripts/tests/test_change_workflow_review.py` shows `merge` refused for an active
  change and accepted for an archived one; the existing closeout case still passes.
  Done: `review.run_review` refuses a kind whose node carries `graph.ARCHIVED`. Unit
  (the reviewer injected): `test_change_workflow_review.py` passes. Destination:
  CW-xo82, the guide's Skills table.
- [x] 2.5 Draw the new nodes, exits, guards, and entry guards in
  `openspec/specs/change-workflow/diagrams/change-workflow-graph.drawio`, and export
  its `.svg` with the source embedded (CW-66kx). Verify: `scripts/change-workflow check
  graph` succeeds; `test_the_documented_diagram_draws_the_table` and
  `test_the_export_embeds_the_diagram_it_draws` pass.
  Done: three boxes, seven edges, `G14`–`G16` in the legend. The export's visible
  part is hand-written SVG, as the existing export's is, its embedded source carrying
  the same edits; it was not rendered. The comparison ran through the tests that call
  `diagram.drift`, one of them running `scripts/change-workflow check graph` itself,
  which pass.
- [x] 2.6 Verification: `pytest -q scripts/tests/test_change_workflow_graph.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_review.py
  scripts/tests/test_change_workflow_cli.py scripts/tests/test_change_workflow_convert.py`
  (unit) passes; `scripts/change-workflow check graph` succeeds; `scripts/change-workflow
  run pre-commit merge-after-archive` passes. End-to-end: none; no scenario exercises
  the workflow tooling.
  Done: the named suites with five more (882 passed); `make check-history-wording`
  and `make check-local-imports` pass; `run pre-commit` passed on the section's work,
  its fresh-context fixes checked again by four suites (486 passed). End-to-end:
  none, confirmed. Owed by validation: none.

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
  Done: `log.after_cleanup`; `log.ran` and `next_step._run_node` take the log,
  required of every caller. Unit: one log test and two next-step tests pass. Fix (42
  F1, the owner chose (A)): a merge run by hand after archive cleanup before the node
  existed, recording no `landing` with none recorded before it, routes nothing
  (`log.unrouted_merge`), and the writer's repair exemption ends at archive cleanup
  (D1, CW-m4qe, CW-j7wp and its new scenario, CW-5vkd). Unit: two next-step and three
  log tests; the engine suites, 948 passed; `run pre-commit` passed. End-to-end:
  none. Owed by validation: the fix commit's — validation 41 passed at `4f07bf898`.
  Destination: CW-m4qe, CW-j7wp, README "Routing is code, with the model as
  backstop".
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
  Done: `Computation.run` in D5's order, through `locate_clone`, `archived_done`, and
  `locate_branch`, `locate` split in two; the shortcuts are gone, and `route` reads an
  `archived` row as the closeout phase. An older log and an unfinished clone are in
  design.md, "Settled in implementation". Unit: the five scenarios by name and three
  more pass. Destination: CW-j7wp, README "Routing is code, with the model as
  backstop".
- [x] 3.3 Supply the reading cleanup's exit guard declares (2.2), over the run's line
  alone, and name `late-merge` in a result as the step to run, `{"step": "merge", …}`,
  the node in its reason (D5, CW-5vkd). Verify: unit tests in
  `scripts/tests/test_change_next_step.py` mapping "The landing branch moved during
  closeout", "The landing branch moves after the pull request opened", "The landing
  branch moved after a merge after the archive", "A change archived before the record
  existed", and CW-9tzd's "Archive cleanup finishes".
  Done: the reading was supplied in 2.2. `graph.Node.result` names the merge step for
  `late-merge` (`_RUN_BY`), its reason prefixed `late-merge: `. Unit: the five
  scenarios by name pass; "moves after the pull request opened" holds since the
  computation reads no ref. Destination: CW-5vkd, the guide's "Directing a change".
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
  Done: no code beyond 3.1–3.3; the table routes it. Unit: the six scenarios by name
  and two more in `test_change_next_step.py` pass; that the orchestrating session asks
  nothing is section 4's. Destination: CW-x9tb, CW-r2hu, CW-tnp6.
- [x] 3.5 Verification: `pytest -q scripts/tests/test_change_next_step.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_graph.py
  scripts/tests/test_change_clone.py scripts/tests/test_change_workflow_cli_steps.py`
  (unit, and library integration where a real clone is used) passes;
  `scripts/change-workflow run pre-commit merge-after-archive` passes. End-to-end:
  none; no scenario exercises the workflow tooling.
  Done: the named suites with three more (868 passed); the history-wording,
  local-imports, and comment-hygiene checks pass; `run pre-commit` passed on the
  finished section. End-to-end: none, confirmed. Owed by validation: none. Why
  `_RUN_BY` is kept by hand is in design.md, "Settled in implementation".

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
  Done: `change-merge` gains "After the archive", with the D7 rules, the four D3
  criteria, the D6 waiver and its interactive command, and D8's question in place of
  a return. The criterion of a file both sides changed excepts the mechanical files,
  as CW-x9tb and D3 do since 42 F2. `make check-agent-skills` passes. Destination:
  CW-x9tb, CW-g3zn, the guide's "The merge before closeout".
- [x] 4.2 Give `change-review` the `merge` kind (D2, CW-r2hu): its description and kind
  list name it, and a section asks what a merge after the archive did — each
  resolution against both parents (`git show --remerge-diff`) and every commit since
  the merge's first parent, each permanent specification and index it touched for both
  changes' meaning with ids unique, and the change's code and end-to-end scenarios
  against what the landing branch renamed, removed, moved, or changed in meaning.
  Verify: `make check-agent-skills` passes; `pytest -q
  scripts/tests/test_change_workflow_review.py` passes.
  Done: the kind named, and a "Merge review" section of four questions. `make
  check-agent-skills` and `test_change_workflow_review.py` pass. Destination:
  CW-r2hu, README "Reviews are files".
- [x] 4.3 Give `change-triage` the `merge` kind (D4, D8, CW-r2hu): its exits are archive
  cleanup on advancing and another merge review, with no return; a finding needing a
  code fix is fixed in the triage and validated by its exit's guard. Verify: `make
  check-agent-skills` passes; the section names both exits and no return.
  Done: the exit and status tables' rows, a fix at a merge review's triage, and the
  archived-change wording. `make check-agent-skills` passes.
- [x] 4.4 Make `change-archive-cleanup` accept `late-merge` and `triage:merge` as its
  routes in, and, on a row already `archived`, append what its cleanup reported to
  `reviews/pull-request.md` rather than redraft it (D4, CW-p8fy). Verify: `make
  check-agent-skills` passes; the skill's status check names both routes.
  Done: the Route check names both routes in on an `archived` row, which runs the
  Route and Landing branch checks before steps 7 to 10; "Running interactively" says
  `done` comes only from a finished cleanup line. `make check-agent-skills` passes.
  Destination: CW-p8fy, README "History lives in the owner's workspace", the guide's
  "History and removal".
- [x] 4.5 Make `change-orchestrate` record the owner's direction to `{"step":
  "late-merge"}` on their word, run the merge the computation names after the archive
  as any merge, record a waiver of the merged `HEAD`'s validation as a direction to the
  exit the merge named, and say that at `done` an advanced landing branch is the owner's
  to direct a merge for (D1, D5, D6). Verify: `make check-agent-skills` passes.
  Done: a paragraph after the merge before closeout, the refusals list, and the pull
  request at `done` after a merge after the archive. `make check-agent-skills`
  passes. Destination: the guide's "Directing a change" and "Waivers".
- [x] 4.6 Verification: `make check-agent-skills` passes; `pytest -q
  scripts/tests/test_check_agent_skills.py scripts/tests/test_change_workflow_assumptions.py`
  (unit) passes; `scripts/change-workflow run pre-commit merge-after-archive` passes.
  End-to-end: none; no scenario exercises the skills.
  Done: `make check-agent-skills` passes; the two suites with the review suite pass
  (104). The fresh-context check's fixes — archive cleanup's rerun honouring a
  validation its route still owes, the pull request at `done`, the interactive
  waiver command, and stale wording in four skills — are in the section's commit;
  its declined finding, a closeout direction for an archived change, is in
  design.md. `run pre-commit` passed after those fixes. End-to-end: none, confirmed.
  Owed by validation: none.

## 5. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.

- [x] 5.1 Comment hygiene: run `make check-comment-hygiene` and `make
  check-history-wording`, and read the comments sections 1–3 added for any naming the
  review or change that introduced them; one that needs rewriting returns the change to
  implementation.
  Done: both checks pass. The comments and docstrings the change adds under
  `scripts/change_workflow/` and in `.claude/change-steps.toml` were read: none names
  a review, change, or migration; those on lines written before the record existed
  state why such a line reads as it does, an invariant of the log.
- [x] 5.2 Import placement: run `make check-local-imports`, and confirm every import
  sections 1–3 added inside a function carries its reason; one that should move returns
  the change to implementation.
  Done: `make check-local-imports` passes, every function-level import the change adds
  giving its reason; none should move.
- [x] 5.3 Documentation compliance: re-check D1–D10 against `openspec/README.md`'s
  placement rules and the destinations named in 5.9, and confirm the proposal's
  "Public interfaces" still names every public interface the change altered — the
  graph's vocabulary, `next`'s output for an archived change, `start merge`'s
  acceptance and default branch, cleanup's guard, and the outcome's `landing` — and
  whether each is compatible (CW-c2tw).
  Done: each decision's normative part is in the deltas, its rationale in the
  companion `README.md`, how to run it in the workflow guide, and nothing in
  `ARCHITECTURE.md`, which does not describe the workflow; the record in `design.md`
  names each. The proposal's "Public interfaces" names all five, with their
  compatibility; the `merge` review kind's acceptance by `make review` is the graph's
  vocabulary (CW-9fbu), and the containment on cleanup's line is named under
  `landing`. The documents agree with the code and skills as read for promotion.
  Closeout triage (52 F1, owner-directed, outside the plan): the `make` help strings
  for `review`, `merge`, and `archive-cleanup` and the shell completion had not taken
  the `merge` review kind or the runs after the archive; `workflow.mk` and
  `scripts/completions/make-change.bash` now name them, the completion offering
  archived and active changes for `make merge`, and the guide's sentence on
  completion with them. Library integration (real Bash and bash-completion):
  `test_make_change_completion.py`, with a `make merge` case, 14 passed. `run
  pre-commit`: "after-functional-change … passed, exit 0", "pre-commit-functional …
  passed, exit 0", "pre-commit … passed, exit 0". The fresh-context check found the help strings matching CW-m4qe and CW-p8fy and no
  other stale copy of the kinds; declined, as outside the owner's direction, its
  note that `make review KIND=merge CHANGE=` completes active names only, as `KIND=closeout`,
  `triage`, and `validate` already did for an archived change. 52 F2: the
  graph's SVG is re-rendered from its `.drawio` source, not hand-edited, by
  `render-diagrams-from-source`, which owns the repository's rendering support; a
  render in a pinned `drawio-desktop-headless` container drew the labels as PNG
  images (59 KB to 1.9 MB) and was not committed, so the hand-kept export stands
  until then.
- [x] 5.4 Narrative compression: shorten completed task notes to final behaviour,
  material evidence, and destinations; move anything implementation settled or declined
  into `design.md` first.
  Done: what implementation settled or declined moved to `design.md`, "Settled in
  implementation"; the notes of sections 1–4 now keep the behaviour, the evidence, the
  fixes from triage, and each destination.
- [x] 5.5 Roadmap currency: record in the promotion record that the change has no
  roadmap impact — `docs/development/ROADMAP.md` names neither the change nor the
  change workflow's area, and it closes no gap row there.
  Done: recorded in `design.md`'s promotion record; a search of `ROADMAP.md` for the
  change and the workflow finds nothing.
- [x] 5.6 Campaign index currency: set the change's row, under "Independent active
  changes" in `openspec/changes/README.md`, to `in closeout`, its notes rewritten for
  closeout; the change has no campaign graph entry and no dependents. Run
  `scripts/change-workflow check index`.
  Done: the row is `in closeout`, its notes rewritten; no other row lists the change.
  `scripts/change-workflow check index` passes; the row's link moves to the archive
  with 5.11.
- [x] 5.7 Packaging: run `make check-packaging`, `make check-architecture-change
  CHANGE=merge-after-archive`, and `make check-agent-skills`, since the change touched
  `.agents/` and `.claude/`.
  Done: `scripts/change-workflow run pre-archive merge-after-archive` — `make
  check-packaging` and `make check-architecture-change` — "passed, exit 0" at
  `04535fa20`; the change owns no architecture row. `make check-agent-skills` passes.
- [x] 5.8 End-to-end pipeline: record the latest passing pipeline run, its commit, and
  that no scenario exercises the change's behaviour, the run being evidence only that
  the stack still builds and runs.
  Done: validation 49 passed at `04535fa20`, the merge of `dev` after the
  pre-closeout triage, which this closeout commit follows changing documentation
  only: pipeline run 42796448887 (`e2e.yml`) succeeded in every lane (e2e-vm,
  native-ansible-gate, e2e-apicredits, e2e-bare-metal), and the local and Helm parts
  passed. No end-to-end scenario exercises the change; the local part's `make test`
  and the packaging check are its evidence. No section owed a CI observation; the
  pipeline rerun 35 V1 asked for passed in validation 41.
- [x] 5.9 Promotion: write the permanent documents and the design-promotion record:
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
  Done: `index.md` — the entries checked against the deltas as implemented; CW-m4qe's
  and CW-j7wp's summaries name the older hand-run merge that routes nothing, CW-1iaz's
  the merge after the archive and the merge review; no id retired. `README.md` — every
  section named above, the merge after the archive under "The merge before closeout"
  as "The merge after the archive", and "Current limits" amended (no return; nothing
  notices a moved landing branch while the pull request is open, the design's open
  question). `docs/agents/change-workflow.md` — every section named above, the
  merge after the archive as a paragraph of its own after "The merge before
  closeout". `scripts/change-workflow check graph` succeeds. The promotion record is
  in `design.md`. Specs synchronized by hand: none, so the archive merges the deltas.
- [x] 5.10 Documentation citations: run `make check-doc-citations
  CHANGE=merge-after-archive` and resolve every match; then `scripts/change-workflow
  openspec validate merge-after-archive --strict`.
  Done: the citation check passes ("every cited path resolves and none is a
  tombstone", 4 documents). `scripts/change-workflow run pre-commit
  merge-after-archive` on the promoted state passed, its strict validation printing
  "Change 'merge-after-archive' is valid" and the repository's checks — the
  specification index with the deltas counted among them — passing.
- [x] 5.11 Archival: `openspec archive merge-after-archive -y`, merging the deltas into
  `openspec/specs/change-workflow/spec.md`; confirm the archived change is found by name
  (`scripts/change-workflow find merge-after-archive`).
  Done: archived with `scripts/change-workflow openspec archive merge-after-archive
  -y`, the deltas merged (none was in `spec.md` before); the merged requirements read
  against the deltas, and `find` names the archived directory, which the index row
  links.
