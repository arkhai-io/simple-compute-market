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

- [ ] 1.1 Add the optional `landing` object, `{"remote", "branch", "commit"}`, to the
  step outcome schema, and its form to the outcome check: each field a non-empty
  string, the commit a full hexadecimal object name, no other field (D10). Verify:
  unit tests in `scripts/tests/test_change_workflow_outcome.py` accept a well-formed
  `landing` on any outcome, refuse each malformed form naming the field, and accept an
  outcome without it.
- [ ] 1.2 Make the log's writer, in `record_outcome` and `record_interactive`, require
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
- [ ] 1.3 Make the log's writer, for a `finished` archive cleanup line, resolve the
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
- [ ] 1.4 Make `start merge` (`cli.merge_arguments`) bring in the branch it is given,
  else the last finished merge's `landing.branch` read from the change's log, else the
  clone marker's `base` (`find.landing_branch`), and refuse with none, naming `FROM`;
  it takes the branch name alone, never the recorded remote (D10, CW-s3ju). Verify:
  unit tests in `scripts/tests/test_change_workflow_cli_steps.py` mapping the delta
  scenarios "A change worked in place merges with no base given", "The merge before
  closeout is repeated after a review of it", "A merge after the archive of a change
  worked in place", and "An older log records no branch".
- [ ] 1.5 Teach `change-merge` to end every `finished` outcome with `landing` — the
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
- [ ] 1.6 Orchestrator's, on the owner's word, before this section's session starts:
  add `Bash(git fetch origin *)` and `Bash(git fetch workspace *)` to
  `[steps.archive-cleanup]` in `.claude/change-steps.toml`, under a comment saying
  archive cleanup fetches the branch the last merge brought in (D10). The section's
  session commits it with the section. Verify: `pytest -q
  scripts/tests/test_change_workflow_steps.py` passes; the row loads with both rules.
- [ ] 1.7 Verification: `pytest -q scripts/tests/test_change_workflow_outcome.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_cli_steps.py
  scripts/tests/test_change_workflow_steps.py scripts/tests/test_find_change.py` (unit,
  and library integration where a real Git repository is used) passes; `make
  check-agent-skills` passes; `scripts/change-workflow run pre-commit merge-after-archive`
  passes, which runs `make test`. End-to-end: none; no scenario exercises the workflow
  tooling.

## 2. The graph declares the merge after the archive, its review, and cleanup's first-exit guard (D1, D2, D4, D5, D6, D8)

Delivers the table's new nodes, exits, guards, and entry guards, what the entry guards
read, the review command's archive check for the new kind, and the diagram held to the
table. Implements D1's node and entry guards, D2's kind, D4's triage exits, D5's guard
on archive cleanup's exit, D6's validation guards, D8's absent returns, and the delta
requirements CW-m4qe (entry), CW-r2hu (graph), CW-xo82, CW-tnp6, and CW-9tzd. Touches
`scripts/change_workflow/graph.py`, `log.py` (`standing`), `review.py`, and
`openspec/specs/change-workflow/diagrams/change-workflow-graph.drawio` and `.svg`.

- [ ] 2.1 Declare in `graph.py` (D1, D2, D4, D6, D8): `late-merge`, `runs="merge"`,
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
- [ ] 2.2 Declare the guard on archive cleanup's exit to `done` (D5, CW-5vkd): it holds
  for any archive cleanup run but the first in the log, for a first run whose line
  records no `landing`, and for one whose recorded containment is true; otherwise its
  remedy is `late-merge`. It reads a new `Readings` method over the run's line alone,
  which section 3 supplies. Verify: unit tests in
  `scripts/tests/test_change_workflow_graph.py`, with fake readings, show the guard met
  and unmet in each of those cases, naming `late-merge` and carrying `done`.
- [ ] 2.3 Extend `Standing`, and `log.standing`, with whether an archive cleanup run has
  finished and whether the change's index row says `archived`, so the log's writer
  refuses a direction the new entry guards refuse (D1, 18 F2). Verify: unit tests in
  `scripts/tests/test_change_workflow_log.py` map the delta scenarios "A merge after the
  archive is directed before archive cleanup", "A merge after the archive is directed
  for a change whose row was pruned", "A merge review is directed for a change not
  archived", and "The owner directs implementation of an archived change"; directing
  `done` is still refused.
- [ ] 2.4 Make the review command refuse a review of a kind whose node needs the archive
  — `closeout` and `merge` — for a change not archived, reading the entry guard from the
  table rather than naming the kinds (D2, CW-xo82). Verify: a unit test in
  `scripts/tests/test_change_workflow_review.py` shows `merge` refused for an active
  change and accepted for an archived one; the existing closeout case still passes.
- [ ] 2.5 Draw the new nodes, exits, guards, and entry guards in
  `openspec/specs/change-workflow/diagrams/change-workflow-graph.drawio`, and export
  its `.svg` with the source embedded (CW-66kx). Verify: `scripts/change-workflow check
  graph` succeeds; `test_the_documented_diagram_draws_the_table` and
  `test_the_export_embeds_the_diagram_it_draws` pass.
- [ ] 2.6 Verification: `pytest -q scripts/tests/test_change_workflow_graph.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_review.py
  scripts/tests/test_change_workflow_cli.py scripts/tests/test_change_workflow_convert.py`
  (unit) passes; `scripts/change-workflow check graph` succeeds; `scripts/change-workflow
  run pre-commit merge-after-archive` passes. End-to-end: none; no scenario exercises
  the workflow tooling.

## 3. The computation routes an archived change (D1, D5)

Delivers the run rule that tells the merge after the archive from the merge before
closeout, the route read for an archived change, the order in which `done` is
answered, the reading cleanup's guard needs, and the result naming the step to run.
Implements D1's run rule, D5, and the delta requirements CW-j7wp, CW-m4qe (the run
rule), CW-5vkd (the guard's reading), and CW-9tzd. Touches
`scripts/change_workflow/next_step.py` and `log.py` (`ran`, `unused_direction`).

- [ ] 3.1 Read a `merge` run logged after an `archive-cleanup` run as a run of
  `late-merge`, in `next_step._run_node` and in `log.ran`, so routing, a direction's
  use, and `merge_waiting` see the right node (D1, CW-m4qe). Verify: unit tests in
  `scripts/tests/test_change_next_step.py` and `test_change_workflow_log.py` show a
  merge run before archive cleanup routed on `merge`'s exits and one after it on
  `late-merge`'s, and a `late-merge` direction spent by the merge run after it.
- [ ] 3.2 Answer `done` for an archived change from the route, in this order (D5,
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
- [ ] 3.3 Supply the reading cleanup's exit guard declares (2.2), over the run's line
  alone, and name `late-merge` in a result as the step to run, `{"step": "merge", …}`,
  the node in its reason (D5, CW-5vkd). Verify: unit tests in
  `scripts/tests/test_change_next_step.py` mapping "The landing branch moved during
  closeout", "The landing branch moves after the pull request opened", "The landing
  branch moved after a merge after the archive", "A change archived before the record
  existed", and CW-9tzd's "Archive cleanup finishes".
- [ ] 3.4 Route the loop end to end (D3, D4, D6; CW-x9tb, CW-r2hu, CW-tnp6): a merge
  after the archive naming `review:merge` or archive cleanup, each through its
  validation guard; a failed validation naming `late-merge` carrying the exit, an
  inconclusive one the owner; `triage:merge` advancing to archive cleanup through a
  validation of its fix; and the owner's waiver as a direction to the exit the merge
  named. Verify: unit tests in `scripts/tests/test_change_next_step.py` mapping "The
  landing branch has gained nothing", "Both changes edited one specification", "Only
  the change index conflicted", "The owner waives only the validation of a merge that
  named its review", "A merge review's triage commits a code fix", and "A validation of
  HEAD merged after the archive fails".
- [ ] 3.5 Verification: `pytest -q scripts/tests/test_change_next_step.py
  scripts/tests/test_change_workflow_log.py scripts/tests/test_change_workflow_graph.py
  scripts/tests/test_change_clone.py scripts/tests/test_change_workflow_cli_steps.py`
  (unit, and library integration where a real clone is used) passes;
  `scripts/change-workflow run pre-commit merge-after-archive` passes. End-to-end:
  none; no scenario exercises the workflow tooling.

## 4. The skills carry the merge after the archive (D3, D4, D6, D7, D8)

Delivers the skill text each step of the loop follows. Implements D3's judgement and
its criteria, D4's rerun, D6's waiver, D7's resolution rules, D8's questions in place
of a return, and the skill side of the delta requirements CW-x9tb, CW-r2hu, CW-p8fy,
and CW-g3zn. Touches `.agents/skills/change-merge/SKILL.md`, `change-review/SKILL.md`,
`change-triage/SKILL.md`, `change-archive-cleanup/SKILL.md`, and
`change-orchestrate/SKILL.md`.

- [ ] 4.1 Give `change-merge` a section for an archived change (D3, D6, D7, D8;
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
- [ ] 4.2 Give `change-review` the `merge` kind (D2, CW-r2hu): its description and kind
  list name it, and a section asks what a merge after the archive did — each
  resolution against both parents (`git show --remerge-diff`) and every commit since
  the merge's first parent, each permanent specification and index it touched for both
  changes' meaning with ids unique, and the change's code and end-to-end scenarios
  against what the landing branch renamed, removed, moved, or changed in meaning.
  Verify: `make check-agent-skills` passes; `pytest -q
  scripts/tests/test_change_workflow_review.py` passes.
- [ ] 4.3 Give `change-triage` the `merge` kind (D4, D8, CW-r2hu): its exits are archive
  cleanup on advancing and another merge review, with no return; a finding needing a
  code fix is fixed in the triage and validated by its exit's guard. Verify: `make
  check-agent-skills` passes; the section names both exits and no return.
- [ ] 4.4 Make `change-archive-cleanup` accept `late-merge` and `triage:merge` as its
  routes in, and, on a row already `archived`, append what its cleanup reported to
  `reviews/pull-request.md` rather than redraft it (D4, CW-p8fy). Verify: `make
  check-agent-skills` passes; the skill's status check names both routes.
- [ ] 4.5 Make `change-orchestrate` record the owner's direction to `{"step":
  "late-merge"}` on their word, run the merge the computation names after the archive
  as any merge, record a waiver of the merged `HEAD`'s validation as a direction to the
  exit the merge named, and say that at `done` an advanced landing branch is the owner's
  to direct a merge for (D1, D5, D6). Verify: `make check-agent-skills` passes.
- [ ] 4.6 Verification: `make check-agent-skills` passes; `pytest -q
  scripts/tests/test_check_agent_skills.py scripts/tests/test_change_workflow_assumptions.py`
  (unit) passes; `scripts/change-workflow run pre-commit merge-after-archive` passes.
  End-to-end: none; no scenario exercises the skills.

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
    CW-g3zn, CW-r2hu, CW-5vkd, CW-p8fy, and CW-j7wp, and its summaries of CW-s3ju,
    CW-tnp6, CW-xo82, and CW-9tzd, written with the design: check each against the
    requirement as implemented and revise it where it no longer holds; no id is
    retired.
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
