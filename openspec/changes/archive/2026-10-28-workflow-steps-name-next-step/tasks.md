Sections follow the design's implementation cadence: the workflow graph as a table
in code and its diagram, reproducing today's routing exactly (1–2); then the new
records and routing on them (3–7); then the steps' side — every skill, the
orchestrate skill, the contributor guide, and the step table (8–9); then closeout
(10). Within each round, scripts come before the skills and documents that call
them. Every script is tested in `scripts/tests/` at unit level, with real files in a
temporary directory where the log's locking and replacement are what is proven, and
a real Git repository in a temporary directory where `HEAD` or the archive is. The
workflow tooling is contributor tooling that no end-to-end scenario in `e2e-tests/`
exercises, and none is owed; no section owes evidence only a push produces.

A task that edits `.claude/change-steps.toml` or another file under `.claude/` is
the orchestrator's, made on the owner's word before its section's session starts,
and that session commits it with its section; the rest of the section is the
implementer's.

The table is drawn in `docs/development/diagrams/change-workflow-graph.drawio` and
its SVG export, which `openspec/specs/change-workflow/architecture.md` shows, and a
test holds the drawing to the table: a section that changes the table redraws the
source from what `make change-graph` reports, and exports the SVG again. The round-3
and round-4 triages (69 O1, 82 O1) replaced the Mermaid block and rendering sections
2–6 wrote; see section 2.

Notes were shortened at closeout (10.4) to final behaviour, evidence, deferrals, and
destinations. The handoffs written between sections were removed once carried out;
the decisions they and the notes held beyond the plan are in `design.md`,
"Decisions taken in implementation", and the full notes are in Git history.

## 1. The workflow graph as a table, interpreted with today's routing

Delivers the graph of D1 as one table in code, which the next-step computation
interprets in place of its per-phase methods, with today's behaviour exactly (D1,
D4's exit guards and remedies; requirement "The workflow graph is declared in
code"). Touches a new `scripts/change_workflow/graph.py`,
`scripts/change_next_step.py`, and `scripts/tests/`.

- [x] 1.1 `scripts/change_workflow/graph.py`: the table — each node a step qualified
      by its review kind where today's routing distinguishes one (D1's table), its
      exits, the join it waits on, and each exit guard with its remedy, a step or
      the owner. State today's routing only: entry guards, the triage's kind as part
      of a target a step writes, and the terminal `done` as a node a step names are
      round 2's (D1, "The table states today's routing").
      Done as D1's rows. The modelling choices D1 left open — `round` one node,
      `round-view` and `validate` nodes with derived exits, the bootstrap's `wait`,
      each exit's `when` label, held guards, a dependency gating closeout held on the
      exit into closeout — are in `design.md`, "Decisions taken in implementation".
- [x] 1.2 Each exit guard as a function of the files and the log, from today's
      `validated()`, `fixed_since()`, `changed_outside_documentation()`, the round's
      join in `_round`, `return_confirmed()`, the clone's bootstrap, and the
      dependency gates, moved rather than rewritten, so each keeps its tests.
      Each checked guard's `check` calls the computation's readings — `validated`,
      `fixed_since`, `changed_outside_documentation`, `return_confirmed`, typed by
      `graph.Readings` — with each call site's reason. The held guards stay in
      `dependencies()`, `bootstrap_held()`, and `bootstrapping()`; the round's join
      is declared as `ROUND_JOIN`.
- [x] 1.3 `scripts/change_next_step.py`: the computation interprets the table in
      place of `_design`, `_implementation`, `_round`, `_pre_closeout`, and
      `_closeout`, and of `_STEP_PHASE`, `_PHASE_STEPS`, and `_REVIEW_PHASE` where
      the table now states what they held; today's token reading, file-time rules,
      and directed decisions are kept as the inputs that choose an exit, since
      round 2 replaces them. The result contract in the module docstring is
      unchanged.
      Each phase's reading takes its exits through `follow`/`unmet`, which evaluate
      the exit's checked guards in the table's order. `_PHASE_STEPS` and
      `_REVIEW_PHASE` are read from the table; `_STEP_PHASE` stays. Correction to the
      plan: the per-phase methods kept their names, since `test_change_next_step.py`
      calls `Computation._design` and could not change; section 6 deleted them.
- [x] 1.4 A new `scripts/tests/test_change_workflow_graph.py`, unit: every exit names
      a node of the table; every guard's remedy is a node or the owner; every node is
      reachable from `design`; every node has an exit, except where the change is
      done.
      Reachability follows exits, guards' remedies, and join suppliers; a remedy may
      be `WAIT`. Added: joins wait on nodes, every logged step is the wrapper's, the
      return and another-round exits, the phases read from the table, and a node's
      result.
- [x] 1.5 Verification: `scripts/tests/test_change_next_step.py` passes unchanged —
      no test edited, added, or removed — which is this section's proof that
      routing is today's (D1, "round 1 reproduces exactly"); the new graph tests,
      unit; every other `scripts/tests/test_change_*` and `test_run_change_step.py`,
      unit; `make test`; `make check-change CHANGE=workflow-steps-name-next-step`.
      End-to-end: none of `e2e-tests/` exercises the workflow tooling, and none is
      owed.
      `test_change_next_step.py`, unchanged: 179 passed; since it asserts reasons by
      substring, the fresh-context check compared every reason and guard order with
      the code before by hand. Graph tests: 44 passed. Workflow suites: 735 passed.
      `make test`, `make check-packaging`: passed. `make check-change`: every check
      but the citation of `convert.py`, section 7's file. End-to-end: none owed.

## 2. The graph drawn, and the drawing held to the table

Delivers `make change-graph` and the diagram the `change-workflow` architecture
shows, checked against the table (D1; requirement "The workflow graph is declared in
code", scenarios "The graph is drawn" and "The documented diagram drifts"). Touches
`scripts/change_workflow/graph.py`, the root `Makefile`,
`openspec/specs/change-workflow/architecture.md`, and `scripts/tests/`.

- [x] 2.1 A rendering of the table as a Mermaid diagram — every node, exit, join, and
      guard with its remedy, each target in its display string form
      (`review:pre-closeout`), which is never parsed (D2) — deterministic, so the
      same table always renders the same text.
      `graph.drawing(table)` gives the boxes and edges any diagram of the table draws
      (`Edge.pieces`), in the table's order; the drawing numbers guards `G1`–`G12` in
      a legend. The Mermaid rendering built on it was removed under 82 O1.
- [x] 2.2 `Makefile`: `make change-graph`, printing the rendering, with a help line
      in the style of `make change-next`.
      Runs `python3 -m change_workflow.diagram` (82 O1), on the workflow targets'
      `.PHONY` line; no new script file.
- [x] 2.3 `openspec/specs/change-workflow/architecture.md`, "Routing is code, with
      the model as backstop": the diagram, as the rendering prints it, in one fenced
      `mermaid` block the check can find; the section's prose is promoted at
      closeout (10.9), not here.
      Replaced under 69 O1, the owner choosing a hand-laid draw.io diagram for
      control over its layout: the architecture shows
      `docs/development/diagrams/change-workflow-graph.svg`, exported from
      `change-workflow-graph.drawio` with its source embedded, and names the source;
      the SVG's visible drawing is not compared (83 F2).
- [x] 2.4 The check, in `scripts/tests/test_change_workflow_graph.py`, unit: the
      architecture's diagram equals the rendering, and a failure names the first
      line that differs and the command that redraws it; a test that a table with an
      added exit no longer matches.
      `scripts/change_workflow/diagram.py` (`drawn`, `expected`, `drift`), moved from
      the test under 82 O1: parses the `.drawio`, writes each edge's guard numbers out
      through the legend, and names each box or edge that departs from `drawing()`;
      `make change-graph` prints that the diagram draws the table, or each departure,
      and fails. Tests: the source and the SVG's embedded copy draw the table; the
      architecture shows the export and names its source; a table with an added exit
      departs, and `diagram.main` reports it and returns 1; `drawing()` gives a box
      per node and join and an edge per exit and join member, with their pieces; and
      `make change-graph`, in a subprocess, says the diagram draws the table.
- [x] 2.5 Verification: the graph tests, unit; `make change-graph` run and its output
      compared by eye with D1's table; `make test`; `make check-change
      CHANGE=workflow-steps-name-next-step`. End-to-end: none, and none is owed.
      Graph tests: 52 passed (64 after the round-4 fixes). `make change-graph`, not
      among the implement step's commands, ran through its test, and its output was
      compared by eye with D1's table, departing only as 1.1's choices say. Workflow
      suites: 743 passed. `make test`, `make check-packaging`: passed. `make
      check-change`: every check but `convert.py`'s citation. End-to-end: none owed.

## 3. Targets, the outcome's exit and `triaged`, and the log's format

Delivers the target object and the records that carry it (D2, D3; D7's format
marker; 43 F2's lock check; requirement "Unattended step runs end with a structured
outcome"). Touches `scripts/change_workflow/graph.py`,
`.agents/change-outcome.schema.json`, `scripts/change_workflow/outcome.py`, `log.py`,
`wrapper.py`, `harness.py`, `review.py`, `cli.py`, `cost.py`, and `scripts/tests/`.

- [x] 3.1 `graph.py`: a target's node from its object — `step`, with `kind` for a
      review and for a triage the kind of review it triages, `sections` for an
      implementation, a nested `target` for validation, and `{"step": "done"}` —
      refusing a review or a triage without its kind, or with an empty or unknown
      one, and naming why (D2, 21 F3). The table gains the triage nodes' kinds as
      targets and `done` as archive cleanup's exit (D1); the drawing is redrawn.
      `graph.node_of(target)` returns the node or raises `TargetError` naming why,
      also refusing a kind, sections, or target on a step that takes none, an unknown
      key, a validation for a validation, and `implement` without sessions of
      sections (`graph.section_ids`, moved from `log.py`). `DONE` has no exits and no
      step. Correction to the plan: a triage's result named its kind only from 6.8,
      with the test that compares it.
- [x] 3.2 `.agents/change-outcome.schema.json` and `outcome.py`: `next` an object
      target or, until section 8 switches the skills, a string — a per-property
      `anyOf`, which `harness_schema()` keeps (D3, the cadence's ordering note);
      `returned` requires `next` as an object and no longer `return_to`; `triaged`
      an array of strings. The schema check refuses an object `next` that names no
      node.
      The object holds `step`, `kind`, `sections`, and `target`, and no other key;
      `outcome_problems` adds `node_of`'s refusal. Correction to the plan: until 8.5,
      `returned` required `evidence` and either an object `next` or `return_to`,
      since the skills then wrote `return_to`.
- [x] 3.3 `triaged` (D3): a non-empty list of distinct `NN-<kind>` names, each a
      numbered record in the change's `reviews/` with its triage file beside it, at
      least one a review of any kind, `-external` included. `wrapper.py` records a
      triage outcome that breaks the rule, or names none, as stopped, naming the
      reference; the rule is one function that section 4's `record` calls too.
      `records.triaged_problems`, applied by the wrapper's `triage_outcome` to a
      triage's finished or returned outcome at the run's end, the step's message
      ahead of the reason.
- [x] 3.4 `log.py`: every line `append_entry` writes carries `"format": 2` (D7), so
      the wrapper's, the decision writer's, and the round lines all do;
      `record_outcome` refuses an outcome that sets `format`.
      `format` is reserved beside `seq` and `at`; an appender whose change directory
      has gone raises `StepError`.
- [x] 3.5 `log.py`: `read_log` and `append_entry`, once they hold the log's lock,
      compare the file they locked with the file at the log's name by inode, and
      open and lock the log again when they differ (D7, 43 F2); a missing log is
      still empty to a reader, and created by an appender.
      One helper, `_locked`, compares device and inode and reopens until they match.
- [x] 3.6 `harness.py`: an unattended run's environment carries a marker that the
      run is the wrapper's, for `record` to refuse (D11).
      `run_claude` sets `CHANGE_WORKFLOW_UNATTENDED=1` (`harness.UNATTENDED_RUN`); a
      Codex review is not marked (`design.md`).
- [x] 3.7 `review.py`: a review run's outcome names `{"step": "triage", "kind":
      <its kind>}` as its exit (D3). `cli.py`'s `log` printing, `wrapper.py`'s
      `earlier`, and `cost.py` render an object `next` as its display string, and a
      string as before.
      `review_outcome(path, kind)`. Correction to the plan: nothing renders an object
      `next` as a string (`design.md`).
- [x] 3.8 Verification, each unit: `test_change_workflow_outcome.py` — an object
      `next` accepted, a string accepted, a review or a triage without its kind, an
      empty or unknown kind, and validation without its target refused;
      `test_change_workflow_wrapper.py` — the spec's "A triage names its exit", "A
      triage outcome names no records", "names an unknown record", "names no
      review", "names a record twice"; `test_change_workflow_log.py` — every
      appended line marked, and "An append waits on the conversion": a thread that
      opened the log and waits on its lock while another holds it and renames a new
      file over the log appends to the new file, with real files in a temporary
      directory; `test_change_workflow_review.py` — a review's exit;
      `test_change_workflow_graph.py`, with the redrawn diagram;
      `test_change_next_step.py` unchanged, since routing still reads today's
      inputs; `make test`; `make check-change
      CHANGE=workflow-steps-name-next-step`. End-to-end: none, and none is owed.
      Unit, each through the module it names; the wrapper's with a fake harness over
      real records in a temporary directory. The replacement tests run a second
      thread through `record_outcome` or `read_log` while the test holds the lock,
      observed through `/proc/self/fd` (skipped where it is absent), and fail with
      the inode comparison disabled, which was tried and reverted. One harness test
      crosses a process boundary: a Python process `run_claude` starts sees the
      marker. Those six files and `test_change_next_step.py` (unchanged, 179): 488
      passed; workflow suites: 979. `make test`: passed. `make check-change`: every
      check but `convert.py`'s citation. End-to-end: none owed.

## 4. `record`: an interactive run records its own outcome

Delivers `python3 scripts/run_change_step.py record <change> <step> --outcome
'<json>'` (D11; requirement "Interactive step runs record their outcome"). Touches
`scripts/change_workflow/cli.py`, `log.py`, and `scripts/tests/`.

- [x] 4.1 `record`: checks the outcome against the outcome schema and, for a triage,
      `triaged` by section 3's rule; appends it through `record_outcome` with the
      session from `CLAUDE_CODE_SESSION_ID`, or from `--session`, the commit at
      `HEAD`, and `interactive: true`.
      `log.record_interactive` holds the writer's rules (a session, a commit, the
      triage's `triaged` by `records.triage_outcome_problems`, shared with the
      wrapper); `cli.interactive_outcome` the harness's side (the marker, the
      session, `--session` winning, the JSON, and `HEAD` through the wrapper's
      `head` seam). A `HEAD` that cannot be read is refused.
- [x] 4.2 Refusals, each naming why and writing nothing: no session id, naming the
      variable (scenario "The harness exports no session id"); inside an unattended
      run, by section 3's marker (scenario "An unattended run records its own
      outcome"); a step not in `STEPS`; an outcome the schema or `triaged` refuses.
      Also refused: an `--outcome` that is not JSON. The marker is checked first.
      Each prints `ERROR: …` and exits 1.
- [x] 4.3 Verification, unit, in `test_run_change_step.py` with a real Git
      repository in a temporary directory for `HEAD`: an interactive triage's
      outcome recorded with its session, `HEAD`, `interactive`, and the format
      marker (scenario "An interactive triage finishes", as far as the log); each
      refusal; `make test`; `make check-change CHANGE=workflow-steps-name-next-step`.
      End-to-end: none, and none is owed.
      Through `main` with an injected environment over real records; the interactive
      triage reads `HEAD` from a real Git repository it creates (a process
      boundary), the rest are unit, and each refusal leaves no log. Workflow suites:
      994 passed. `make test` (`scripts/tests`: 1690), `make check-packaging`:
      passed. `make check-change`: every check but `convert.py`'s citation.
      End-to-end: none owed.

## 5. Entry guards, and the owner's directions

Delivers entry guards on nodes and the owner's directions to any node (D1's entry
guards, D5, D6; requirement "The owner directs a change's next step", and
"Unattended step runs end with a structured outcome"'s decision rules). Touches
`scripts/change_workflow/graph.py`, `log.py`, `cli.py`, `review.py`, and
`scripts/tests/`.

- [x] 5.1 `graph.py`: each node's entry guards, unwaivable or waivable, as D1's
      entry-guard table gives them — the archive's absence for design, planning, and
      implementation; the archive for the closeout review, its triage, and archive
      cleanup; a review of its kind awaiting triage for each triage node;
      validation carrying a target that is a node; `done` never directed; and the
      pre-closeout review's validation, waivable. The drawing is redrawn.
      `Declaration.entry`, a tuple of `EntryGuard(condition, waivable, check)`
      reading `Standing(archived, awaiting)`; `entry_refusal(target, standing,
      directed=)` names the first unwaivable guard not met, of the target and, for a
      directed validation, its nested target. The waivable guard is checked by the
      review as it starts (5.4). Each box of the drawing lists its entry guards.
- [x] 5.2 `log.py`, `note_orchestrator` (D6): `next` is the target object; every line
      carrying `next` is `by: owner`; its target is a node of the table; and the
      log's writer refuses it, naming the guard, while an unwaivable entry guard of
      any node it names is not met — the target, and the target nested in a
      direction to validation (D5, 36 F1). No exit guard is checked. The special
      cases for review, plan, archive cleanup, and confirmed returns, and
      `redesigned_after_return`'s gate, are removed: a waiver is a plain direction
      whose `reason` says what it skips. `resolves` and `reads` are unchanged.
      `note_orchestrator` gains `sections` and `target` and loses `status`;
      `standing(path)` reads the archive from the directory's place and the reviews
      awaiting triage from `reviews/` and the log; `unused_direction(entries)` is the
      owner's latest direction while no run of its node follows it.
- [x] 5.3 `cli.py`: `note orchestrator` keeps `--next`, `--kind`, and `--sections`,
      and gains `--target` for a direction to validation, which `--kind` and
      `--sections` then qualify (D6); it builds the object.
      Correction to the plan: `note orchestrator` had no `--sections`; it gained it
      too, in `note round`'s form.
- [x] 5.4 `review.py`: the pre-closeout review's validation check accepts the
      owner's direction to that review, logged and not yet used, as its override, as
      `--unvalidated` is (D5, scenario "The owner directs a pre-closeout review over
      a failed validation").
      `run_review` reads `unused_direction`; a direction to a review of its kind
      sets the override, and its refusal names both overrides.
- [x] 5.5 Verification, unit, with real archive directories in a temporary
      directory: in `test_change_workflow_log.py` and `test_run_change_step.py`, the
      spec's "A directed review names no kind", "A directed triage names no kind",
      "The orchestrating session directs a step", "A return confirmed by anyone but
      the owner", "An archived change is directed to design", "A change not archived
      is directed to archive cleanup", "A validation is directed without a target",
      "A directed validation could never reach its target", "A triage is directed
      with nothing to triage", and a direction to validation with its target
      accepted; in `test_change_workflow_review.py`, the pre-closeout review over a
      failed validation starting on the direction; the graph tests with the redrawn
      diagram; `make test`; `make check-change CHANGE=workflow-steps-name-next-step`.
      End-to-end: none, and none is owed.
      Unit: `note_orchestrator` on logs in real active and archive directories for
      each named scenario, the archive both ways for every node it guards, `done`,
      and `unused_direction`; `main` for the flags; a fake reviewer for the override,
      held to the validation again on the next review; the graph tests for the entry
      guards and their boxes. `test_change_next_step.py` changed in three places (two
      waiver calls lose `status=`, one asserts the object, and a closeout triage's
      return to planning the writer now refuses). Workflow suites: 1028 passed. `make
      test` (1722), `make check-packaging`: passed. `make check-change`: every check
      but `convert.py`'s citation. End-to-end: none owed.

Fix from the round-3 triage, 68 F1: `log.standing()` also counts, as awaiting the
triage of the latest review's kind, an untriaged validation record numbered after
that review, unless it is a design review (`AWAITS_TRIAGE`), so the owner can direct
the triage of a failed fix validation; the triage and orchestrate skills say so.
Unit: `test_change_workflow_log.py::test_a_triage_is_directed_for_a_validation_after_its_kinds_latest_review`
and `test_change_next_step.py::test_the_owner_directs_a_failed_fix_validations_triage`.

## 6. Routing on outcomes and directions

Delivers the computation routing on the exit the last step named and the owner's
latest direction, checked against the table, and the detection of a change not yet
converted (D3, D4, D5, D7's detection, D8; requirements "The next step is computed
from the files", "The workflow graph is declared in code", "Interactive step runs
record their outcome", and the phase requirement's exception for directions).
Touches `scripts/change_next_step.py`, `scripts/change_workflow/graph.py`,
`scripts/tests/test_change_next_step.py`, and `scripts/tests/`.

- [x] 6.1 The route: the last step's exit, or the owner's latest direction until a
      later run of its target is logged; the governing review's latest triage
      outcome is the latest triage line whose `triaged` names it, or the conversion
      line that names it; a triage file no such line names is a triage in progress,
      whatever its first words (D3). A return is confirmed by the owner's decision
      that resolves its run. `next_token()`, `governing()`'s and
      `return_confirmed()`'s file times, and the `## Gate` reading are deleted (D3,
      D7).
      `route_of(log, join)` walks the log into a `Route` (`EXIT`, `DIRECTED`,
      `ROUND_STARTED`, `VALIDATED`, `ELSEWHERE`, `NO_EXIT`); `log.ran` is the one
      reading of a run of a node; `triage_line(record)` a review's governing triage;
      `return_confirmed(run)` an owner's decision resolving the run with a target.
      Deleted with the token readings: `governing`, `_section_text`, `_seconds`,
      `set_aside`, `waived_design_review`, `not_advancing`, `untriaged`, `planned`,
      the per-phase methods, and `log.py`'s `redesigned_after_return` and
      `directed_step`. The reading's decisions beyond the plan are in `design.md`.
- [x] 6.2 Checking the route against the table (D4): an exit its node does not
      declare, a validation's exit other than the target it was given, and an exit
      whose target's entry guard is not met name the owner, with the choice, the
      node's exits or the target, and the guard; an unmet exit guard names its
      remedy with the exit as `target`, or the owner where no step can satisfy it;
      a direction checks no exit guard. Validation is always named with a `target` —
      the round's triage in a round's join — and the target's guards are checked
      again on its exit. `done` names `{"step": "done", "reason": "archived"}` as
      today. A `round` result for sections an `implement` target names out of the
      plan's order, recorded as a round line as it starts (D2).
      `chosen(route)`, `guarded`, and `entered` (`entry_refusal(...,
      directed=False)`); the implementation triage's two exits to the round are told
      apart by sections (`graph.OUT_OF_ORDER`); a validation naming its given target
      leaves the route, so its guards are checked again; `directed()` checks a
      direction's unwaivable entry guards on the change as it stands; an out-of-order
      round carries `by`.
- [x] 6.3 Recovery (D8): the step a last exit or direction names, with no run of it
      logged, is named as in progress, its reason saying that if no session of it is
      open an interactive session ended without recording, to be resumed or recorded
      with `record`; where the files have moved past it — a plan that set
      `ready for implementation` and recorded no outcome — that step is named with a
      `disagreement` naming the missing outcome and `record`, and no step after it.
      `enter` adds `in_progress(node, line)`, the `record` command, when no run
      follows the routing line, and on a step's exit `passed_by_status(node)` as the
      `disagreement` when the status's phase is past every phase of the node.
- [x] 6.4 Detection (D7): a log holding a line without the format marker, or numbered
      records under `reviews/` and no log, names the owner with
      `python3 scripts/run_change_step.py convert <change>`, and the log is read as
      nothing else. The module docstring's result contract gains `target`.
      `unconverted()` runs after the change is located and before the bootstrap and
      every routing reading, naming the first unmarked line's seq; a cleaned-up
      change is `done` before it.
- [x] 6.5 `scripts/tests/test_change_next_step.py` rewritten to the new records: its
      fixtures write marked outcomes with object exits and `triaged`, and marked
      decisions, in place of `## Next` tokens and file times; every test that held a
      behaviour this change keeps is kept under its behaviour, and each
      next-step scenario of the delta has a test: "Reviews await triage", "Triage
      records another round", "A triage has not finished", "A step names an exit its
      node lacks", "A triage names sections out of the plan's order", "A triage
      returns the change", "A pre-closeout triage returns the change", "The owner
      declines a return", "A new triage file awaits its outcome", "A triage file
      predates `## Next`", "A log not yet converted", "An older return awaits
      confirmation", "A change has records and no log", "A validation before
      closeout passes", "A validation names another exit", "A closeout correction
      awaits validation", "A documentation correction at closeout", "A round's
      validation is inconclusive", "An implementation round advances", "A round is
      recorded after the fact"; the graph requirement's "The round's triage waits
      for its join", "A round's validation starts before its review is published",
      "Archive cleanup finishes", "A step's exit meets an unmet entry guard"; the
      directions' "The owner directs past a guard", "Closeout finds a design defect
      before the archive", "The owner waives archive cleanup's validation by a
      direction" (as far as the computation), "The owner directs a validation before
      closeout", "The owner confirms a return", "A confirmation names no run", "The
      owner directs a repeat review"; and the interactive requirement's "An
      interactive session ends without recording" and "An interactive plan sets its
      status and records nothing".
      Fixtures log marked lines through `record_outcome`, `note_round`, and
      `note_orchestrator`, unmarked ones raw. Each named scenario has a test, three
      sharing one. Deleted with what they held: the token and gate readings, the
      file-time confirmation, two reviews triaged together read by files' times, and
      a status with no route naming its phase's step past design.
- [x] 6.6 Verification, unit: `test_change_next_step.py` as rewritten; the graph
      tests with any redrawn diagram; every other `scripts/tests/test_change_*`,
      `test_round_view.py`, and `test_run_change_step.py`; `make test`; `make
      check-change CHANGE=workflow-steps-name-next-step`. End-to-end: none, and none
      is owed.
      `test_change_next_step.py`: 192 passed, unit but for three that start `git`
      (the round view, the conflicted merge, the clone). Graph tests: 64 passed; no
      diagram redrawn. Workflow suites: 1041 passed. `make test` (1736; 1742 after
      the fresh-context fixes), `make check-packaging`: passed. `make check-change`:
      every check but `convert.py`'s citation. End-to-end: none owed.
- [x] 6.7 The round's join read from `graph.ROUND_JOIN`: the records its members
      supply decide what the join still waits for and which member's step the
      computation names, the clone's and the repeat pass's reading rules kept; unit,
      in `test_change_next_step.py`, a table whose join lacks a member no longer
      waits for that member's record (52 F1: the table declared the join while
      `in_round` read it from record kinds of its own, so a changed join redrew the
      diagram and left routing as it was).
      `round_join` reads `Computation`'s `join` seam, `ROUND_JOIN` by default, each
      member only while it is one (`_SUPPLIES`); the repeat pass's state is
      `round_pass(current, again)` (`Pass`). Tests: a join without `round-view`, and
      one without validation.
- [x] 6.8 `graph.py`: a triage's result names the kind of review it triages
      (`Node.result`, D2), with `test_change_next_step.py`'s rewrite (6.5) and the
      graph test `test_a_node_names_its_step_and_a_reviews_kind`: section 3 left
      it, since that test file is unchanged until 6.5 and compares a triage's
      result exactly.
      The graph test is now `test_a_node_names_its_step_and_its_kind`.

Fixes from the round-3 triage:

- 68 F2: `round_pass` holds a first pass unread until its owner record exists,
  wherever the change is worked (`design.md`). Unit:
  `test_the_round_is_read_before_triage_though_its_validation_and_review_ran_first`.
- 69 O2: `Computation.set_back` follows a status set back into an earlier phase than
  the log's last step, with no owner direction after it, to the node its phase
  starts at (`_PHASE_START`), its unwaivable entry guards checked, until an owner's
  direction or a round line follows (D8); `disagreement()` is gone and
  `passed_by_status` stays. Unit: `test_a_status_set_back_by_hand_is_followed` and
  four tests beside it.

## 7. `convert`: a change's records converted when it takes the new code

Delivers `python3 scripts/run_change_step.py convert <change>` (D7; requirement "The
next step is computed from the files", its conversion clauses). Touches
`scripts/change_workflow/cli.py`, `log.py`, a new `scripts/change_workflow/convert.py`,
and `scripts/tests/`. The command and the older reading it alone holds are
temporary, removed by the change closeout opens (10.9).

- [x] 7.1 Refusals, writing nothing: a change already converted; a triage in
      progress by the older reading — a triage file with neither `## Next` nor
      `## Gate` that no marked triage outcome names — naming the review and the two
      ways to finish it (36 F4).
      `convert.conversion` refuses both with `StepError` before anything is built;
      "already converted" is the detection inverted, through `log.unmarked`. A
      conversion line counts as naming its triages, so a rerun attests what the
      first did.
- [x] 7.2 The log's lines rewritten in place, each keeping its seq: a decision's
      string `next` and `kind` become the target object; a `returned` outcome's
      `return_to` gains its target in `next`; an outcome's prose `next` moves into
      its `message`; every line gains the format marker. One conversion line
      appended, `step` `convert`, `outcome` `converted`, naming as `triaged` every
      review with a triage file, and no exit.
      `convert.rewritten(entry)`: only unmarked lines change, the marker after `at`;
      prose joins the message as `\n\nNext: …`; `return_to` is kept beside the new
      `next`. `triaged` names review records only, `-external` included.
- [x] 7.3 The proposal of the owner's direction to where the change stands, from the
      latest routing decision after the latest triage (43 F3): a later decision
      carrying `next` whose target has not run, converted — a confirmed return among
      them — unless an unwaivable entry guard of a node it names is no longer met,
      when nothing is proposed; otherwise the latest triage file's token as it leads
      in its phase today, `Advance` and a `## Gate` beginning `Passed` the phase's
      advancing exit, `Another round` the review of the same kind, with the remedy of
      any unmet exit guard on the edge, evaluated by the table's own guards, as the
      target; nothing where a step's run follows the latest triage's, naming those
      runs; for a return not yet confirmed, the direction to its target resolving
      that run's seq. The older reading of tokens lives only here.
      `convert._propose`, in that order, the latest triage's run found by `_anchor`;
      its exit is a marked outcome's, else the token (`read_triage`). The guards are
      the computation's (`Computation.context`, `Computation.guarded`), a validation
      remedy becoming `{"step": "validate", "target": <the exit>}`; every proposal is
      checked by `entry_refusal(..., directed=True)` on the converted log. Beyond the
      plan: see `design.md`.
- [x] 7.4 The owner's confirmation: the command shows the proposal, or why there is
      none, and every review the conversion line will name, each with the first line
      of the `## Next` or `## Gate` it read, flagging those no marked triage outcome
      names; it writes only when the owner confirms, which attests the flagged
      triages finished, or gives `--next` in the proposal's place (43 F1). The
      direction is written through `note_orchestrator`'s checks (section 5), `by:
      owner`; declining writes nothing.
      Shows by default; `--confirm` writes; `--next`, with `--kind`, `--sections`,
      and `--target`, replaces the proposal, and `--reason` its reason. Correction to
      the plan: `--confirm --decline` writes the conversion with no direction where
      the proposal confirms a pending return. The checks are `log.decision_line`,
      against the converted lines in memory.
- [x] 7.5 The replacement (D7, 36 F3, 43 F2): the log's exclusive lock taken before
      the log is read and held until the converted log — the rewritten lines, the
      conversion line, and the direction — is written to a temporary file beside the
      log and renamed over it; a change with records and no log gains its log the
      same way.
      `log.replace_log(path, rewrite, replace=os.replace)`: locked through `_locked`,
      written to `.workflow.jsonl.<random>.tmp` beside it, fsynced, given the old
      log's permissions, renamed, and removed if the rename did not happen; a refused
      or failed replacement removes a log its own open created. A process killed
      before the rename may leave an empty log, still detected, and its dotfile.
      `Computation.read` reads the computation's files before the lock is taken.
- [x] 7.6 Verification, unit, with real files in a temporary directory: the spec's
      "A change is converted", "A pending return is converted, then confirmed", "A
      confirmed return is converted", "A conversion proposes a guard's remedy", "A
      conversion after later runs", "A conversion follows a later direction", "A
      conversion's triage is not attested", "A conversion is interrupted" (the
      replacement stopped before the rename leaves the log unchanged), "A change is
      converted with a triage in progress", "An older wrapper appends after the
      conversion", and, with section 3's thread test, an append waiting on the
      conversion landing in the converted log; a converted log routed by the
      computation to the direction it ends with; `make test`; `make check-change
      CHANGE=workflow-steps-name-next-step`. End-to-end: none, and none is owed.
      `test_change_workflow_convert.py`, 36 passed, through `convert_change`,
      `rewritten`, `read_triage`, or `main`, with the computation's seams over real
      files in a temporary directory and `change_next_step.compute` for where a
      converted log routes — unit only loosely, each driving the conversion, the
      replacement, and the computation together. Each named scenario has a test; the
      interrupted conversion leaves the log byte for byte and no temporary file; the
      append test reuses section 3's thread method and fails with the inode
      comparison disabled. `test_change_workflow_log.py`: `replace_log` and
      `unmarked`. `scripts/tests`: 1784 passed. `make test`, `make check-packaging`:
      passed. `make check-change`: every check passes. End-to-end: none owed.

## 8. Every skill names its exit, and records it when interactive

Delivers the steps' side of the new records (D2, D3, D5's entry checks, D11;
requirements "Unattended step runs end with a structured outcome" and "Interactive
step runs record their outcome"). Before this section's session starts, the
orchestrating session runs `python3 scripts/run_change_step.py convert
workflow-steps-name-next-step` on the owner's word, which the computation names once
sections 3–7 are committed (D7, "Round 2 runs the command on this change"), and adds
the step table's rule in 9.3. Touches every skill under `.agents/skills/change-*/`,
`.agents/change-outcome.schema.json`, `scripts/change_workflow/outcome.py`, and
`scripts/tests/`.

- [x] 8.1 Each leaf skill's unattended ending names its exit as a target in `next`,
      its prose moving into `message`: design names the design review; planning
      `{"step": "round"}` beside `rounds`, or the pre-closeout review when the plan
      adds nothing to implement; implementation the round's triage of kind
      `implementation`; validation the target the computation gave it, read by
      running the computation, under orchestration and interactively alike (D1);
      closeout the closeout review; archive cleanup `{"step": "done"}`. A return
      names its target as a step. The review skill describes the exit its run
      records (section 3's `review.py`).
      Returns: implementation, planning, and triage name `{"step": "design"}` or
      `{"step": "plan"}`; closeout's code-needing part names `{"step": "round"}`. A
      merge-resolving implementation run names `{"step": "round"}`, undeclared on
      purpose (D4, 68 F3). Validation's target: `design.md`.
- [x] 8.2 `change-triage`: the triage chooses its exit among its node's exits, on the
      owner's disposition, as a target with `triaged`; `## Next` is prose — the
      target and the owner's words — which nothing routes on; the "Advance, or
      another round" step and its routing paragraph rewritten to the exits; the
      validation, owner, and orchestrator triage files keep their evidence line.
      Step 6 is "Choose the exit", with each triage node's exits, read against
      `graph._STEPS`; step 4 defines `triaged`. A validation triaged alone names the
      earlier round's review again in `triaged`.
- [x] 8.3 Each leaf skill gains a "Running interactively" ending: its last act runs
      `python3 scripts/run_change_step.py record <change> <step> --outcome '<the
      outcome>'`, with `printenv CLAUDE_CODE_SESSION_ID` named as the way to read the
      session's id when the skill needs to show it (D11).
      Design, planning, implementation, triage, validation, closeout, and archive
      cleanup; implementation interactively records the round line too. What each
      records, and design's and planning's interactive cases: `design.md`. Correction
      to the plan: `change-review` records nothing interactively (D11, 69 O5).
- [x] 8.4 Entry checks (D3, D5): `change-plan`, `change-closeout`, and
      `change-archive-cleanup` ask `python3 scripts/change_next_step.py <change>`
      and proceed when it names their step, in place of reading `## Next` or
      `## Gate`; planning's check of the owner's waiver becomes that question too.
      `change-archive-cleanup` still writes the waiver's ledger line when the owner's
      direction to it is in the log.
      Each check names the step whatever the status says. Archive cleanup's route
      check passes a validation of `HEAD`, or the owner, carrying archive cleanup as
      `target` on to its validated check, which takes the owner's direction as the
      waiver. Closeout's "Where it stopped" records an outcome an earlier session
      left unrecorded.
- [x] 8.5 `.agents/change-outcome.schema.json` and `outcome.py`: `next` an object
      only, now that every skill writes one (D3, the cadence's ordering note); tests
      updated.
      `returned` requires `next` and `evidence`; `return_to` is gone from the schema.
      `change_next_step.py`'s `_RETURN_STEP`, and `route_of`'s tolerance for a
      finished run naming no exit in the join, were deleted; `convert.py`'s
      `_RETURN_STEP` stays, reading older lines.
- [x] 8.6 Verification: `make check-agent-skills`; `test_change_workflow_outcome.py`,
      unit, a string `next` refused; every `scripts/tests/test_change_*`, unit;
      `make test`; `make check-change CHANGE=workflow-steps-name-next-step`; each
      skill's ending read against the delta's requirements. The skills are
      instructions to an agent: that a session follows them is shown by this
      change's own runs after this section, its validation and review's outcomes
      among them. End-to-end: none, and none is owed.
      Before this section the owner converted this change's records (seq 82, the
      conversion line; seq 83, the direction). `make check-agent-skills`: passed.
      Outcome tests, unit: a string `next`, a return without `next`, and `return_to`
      refused. `test_change_next_step.py`, unit: a finished run naming no exit names
      the owner, a return giving only `return_to` waits, and an implementation naming
      `{"step": "round"}` names the owner. `scripts/tests`: 1788 passed. `make test`,
      `make check-packaging`: passed. `make check-change`: passes. Each skill's
      ending was read against the delta by two fresh-context checks. The runs that
      followed are under 10.8. End-to-end: none owed.

Settled at triage, documents only: 68 F3 — the merge run's undeclared exit kept, its
rationale in D4; 69 O5 — the review's interactive exception in D11, and the MODIFIED
scenario "The owner waives archive cleanup's validation under orchestration" has
archive cleanup find the owner's direction and record the waiver without asking
again; 83 F1 — the requirement "Interactive step runs record their outcome" names the
review as its exception, with the scenario "An interactive review is pasted into a
triage".

## 9. The orchestrate skill, the contributor guide, and the step table

Delivers the orchestrating session's part and the contributor's account (D5, D6, D7,
D11; requirement "The owner directs a change's next step"). Touches
`.agents/skills/change-orchestrate/SKILL.md`, `docs/agents/change-workflow.md`, and
`.claude/change-steps.toml`.

- [x] 9.1 `change-orchestrate`: every direction is the owner's — a confirmed return, a
      repeat review, a waiver, an intervention to any node — written with `--next`,
      `--kind`, `--sections`, and `--target`; the orchestrating session directs
      nothing on its own and never records a step's exit; a result's `target` shown
      in its relay; the `convert` command run on the owner's word when the
      computation names it, between steps, relaying its proposal and the reviews it
      flags for the owner's confirmation; `record` for a step the owner ran
      interactively and closed before recording; "its free-text `next` is not a
      routing command" replaced by the exit the outcome names.
      A new "The owner's directions" subsection holds the flags, the writer's
      refusals by entry guard, returns, repeat reviews, and waivers; "A change not
      yet converted" relays `convert`'s preview; a merge run's undeclared exit is
      relayed for the owner's direction. Correction to the plan: the orchestrating
      session does not run `record` for a closed step (`design.md`).
- [x] 9.2 `docs/agents/change-workflow.md`: the triage row of the steps table, the
      paragraph on the order of steps (`## Next` tokens), "Orchestrating a change"
      and "Answering and taking over" for exits, directions, `record`, `convert`, and
      `make change-graph`.
      Also the orchestration row, exits as targets beside `record`, the graph and
      `make change-graph`, routing cited to the spec, the entry checks, "Directing a
      change" and "Converting a change's records", the pre-closeout review's
      override, the log's writers and marker, and the ledger's waiver by direction.
- [x] 9.3 `.claude/change-steps.toml` — the orchestrator's, on the owner's word,
      before section 8's session starts, committed by that session with section 8:
      every step may run `printenv CLAUDE_CODE_SESSION_ID`, and no broader reading
      of the environment (D11).
      Correction to the plan: committed by the orchestrating session on the owner's
      word as its own commit, 0d4535448, before section 8, in `[common]`.
- [x] 9.4 Verification: `make check-agent-skills`; the step table loads
      (`test_change_workflow_steps.py`, unit); `make test`; `make check-change
      CHANGE=workflow-steps-name-next-step`; the guide's commands run as written
      (`make change-graph`, `run_change_step.py record --help`, `convert --help`).
      End-to-end: none, and none is owed.
      `make check-agent-skills`: passed. `test_change_workflow_steps.py`: 36 passed.
      `scripts/tests`: 1788 passed. `make test`: passed. `make check-change`: passes.
      `make change-graph` ran. `record --help` and `convert --help` were denied in
      that run; every command and flag the guide and the skill give was read against
      `cli.py`'s parser instead, and each exists. End-to-end: none owed.

The round-3 triage (67-validation, 68-implementation, 69-implementation-owner; the
round `f9c2b1c50`..`b902d8866`) and the round-4 triage (81-validation,
82-implementation-owner, 83-implementation; the repeat pass `b902d8866`..`860cfa125`)
made the fixes noted under sections 2, 5, 6, and 8, and one concerning no section:

- 69 O3: a resume that found no conversation records no `usd` and no `session_usd`
  (`design.md`). Unit,
  `test_change_workflow_cost.py::test_a_resume_that_found_no_conversation_records_no_dollars`,
  through the wrapper with a fake harness, failing on the code before.

Evidence for the round-3 fixes: `scripts/tests`, unit: 1797 passed. `make test`,
`make check-packaging`, `make check-change`: passed. The fresh-context check's one
defect, a status set back to implementation naming its round again once recorded,
was fixed. Evidence for the round-4 fixes: graph tests 64 and `scripts/tests` 1797
passed; `make test`, `make check-packaging`, `make check-change`: passed; `make
change-graph` printed that the diagram draws the table. End-to-end: none owed; no
`Owed by validation:` line.

## 10. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [x] 10.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments and docstrings this change added under `scripts/`, the `Makefile`,
      `.agents/`, and `.claude/` for provenance — review, triage, finding, or round
      labels, "no longer", "migrated", the conversion described as a migration
      rather than as the command's current job; anything to rewrite returns the
      change to implementation.
      `make check-comment-hygiene`: passed. The comments and docstrings added since
      `c82de9861` were read for provenance: none names a review, triage, finding, or
      round, and `convert.py`'s describe the command's current job, its "older" lines
      being what it reads. Confirmed; nothing to rewrite.
- [x] 10.2 Import placement — confirm: no function-local import added in the files
      this change added or touched under `scripts/`; one that should move returns
      the change to implementation.
      None in `git diff c82de9861 HEAD -- scripts`. Confirmed.
- [x] 10.3 Documentation compliance: re-check D1–D8 and D11 against
      `openspec/README.md`'s placement rules — behaviour in the `change-workflow`
      spec, rationale in its architecture companion, contributor procedure in
      `docs/agents/change-workflow.md`; the cadence and the conversion of this
      change's own records are history and stay here.
      Each decision, and those taken in implementation, placed by
      `openspec/README.md#documentation-placement`, as the promotion record gives
      them. Permanent passages the deltas do not carry still described the tokens —
      the spec's Purpose, the architecture's log and triage paragraphs — and were
      rewritten (10.9). The guide was read against the code: its clone removal now
      says a squash merge counts, as `change_clone._merged` does.
- [x] 10.4 Narrative compression of sections 1–9's notes, moving any rationale not
      yet in `design.md` there first.
      The notes now give final behaviour, evidence, deferrals, and destinations; the
      handoffs between sections, carried out, were removed. The modelling, routing,
      conversion, interactive, and cost decisions they held were moved first to
      `design.md`, "Decisions taken in implementation".
- [x] 10.5 Roadmap currency: no goal in `docs/development/ROADMAP.md` covers
      contributor workflow; record that, or update it.
      No goal covers it (no mention of the workflow, triage, or orchestration); no
      edit, recorded in the promotion record.
- [x] 10.6 Campaign index currency: this change's row `in closeout`, under
      independent active changes, its notes rewritten for closeout; the row of the
      change 10.9 opens added `ready for design`; `make check-change-index`.
      Both rows under "Independent active changes", which has no dependency graph;
      no other row's `Depends on` or status changed. `make check-change-index`:
      passed.
- [x] 10.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=workflow-steps-name-next-step`, and `make check-agent-skills`.
      `make check-packaging`: passed. `make check-architecture-change`: the change
      owns no architecture row. `make check-agent-skills`: passed.
- [x] 10.8 End-to-end pipeline: record the latest passing validation's pipeline run
      and Helm evidence for the commit closeout reads, or an explicit blocker naming
      its cause and owner. No scenario exercises the workflow tooling; this change's
      own runs from section 8 on, recorded and routed in the new format, are its
      working evidence, cited by their log lines.
      Validation 91 passed at `4e7912531`, the pre-closeout commit, which `HEAD`
      before closeout (`6e732fd29`) differs from only in the index: local (`make
      check-packaging`, `make test`); Helm (namespace
      `validate-workflow-steps-name-next-step`, the scenario pod exiting 0 on the
      scenarios the default charts serve); and e2e.yml run 40689900549, success, its
      lanes e2e-vm, e2e-bare-metal, and e2e-apicredits. No scenario exercises the
      workflow tooling, as the record's coverage section says, so `make test` is
      its evidence. CI: not owed. Working evidence, each line in the format: after
      the conversion (seq 82) and the owner's direction (seq 83), the implementation
      at seq 84 named `{"step": "triage", "kind": "implementation"}`, validations at
      86, 100, and 110 named their targets, reviews at 87, 101, and 111 their
      triages, and triages at 98, 108, and 112 their exits with `triaged`; the
      computation routed on each, naming closeout from seq 112.
- [x] 10.9 Promotion, completing the design-promotion record in `design.md`:
      - `openspec/specs/change-workflow/spec.md` — written by the archive (10.11):
        "The workflow graph is declared in code", "Interactive step runs record
        their outcome", and "The owner directs a change's next step" added; "Phases
        and owner touchpoints", "Unattended step runs end with a structured
        outcome", and "The next step is computed from the files" modified. By hand:
        "Evidence" gains `scripts/change_workflow/graph.py`,
        `scripts/change_workflow/diagram.py` (`make change-graph`),
        `run_change_step.py record`, and `run_change_step.py convert`
        (`scripts/change_workflow/convert.py`).
      - `openspec/specs/change-workflow/architecture.md` — "Routing is code, with the
        model as backstop": the graph as a table in code beside its diagram (placed
        in section 2), entry and exit guards and why a direction checks only entry
        guards (D1, D4, D5), and that a durable change to the workflow is an
        OpenSpec change (D1); "Steps run headless and resume with the owner's
        answers": an interactive run records its own outcome (D11), and the log
        holds the transitions chosen on the files' state, written by the wrapper,
        `record`, the decision writer, and `convert` through one module (D3), in a
        marked format whose older records `convert` brings over (D7); "The owner is
        interrupted only for judgement": a triage's exit replacing the tokens, and
        an intervention as a per-change, irregular transition, deliberate and the
        owner's alone, the archive the boundary no direction crosses (D5); "Current
        limits": an archived change is not returned to an earlier phase (D5), and
        `convert` stays until every change not yet cleaned up has taken the new code
        (D7).
      - `docs/agents/change-workflow.md` — written in section 9; confirm it against
        the archived spec.
      - Open the change that removes `convert` and the detection once every change
        not yet cleaned up is converted (D7): its `proposal.md` under
        `openspec/changes/remove-workflow-log-conversion/` and its index row
        (10.6), the format marker staying.
      Written as listed. By hand in the spec, beside "Evidence": the Purpose, which
      named a triage's `## Next`, now names its exit and the graph. In the
      architecture, beyond the list: held guards, validation's target, and the
      merge run's exit under routing; the files and the log each prevailing in its
      domain; "Phases, triage, and archival" finishing a phase on an exit or a
      direction; and two more limits, a direction's reach and
      `CLAUDE_CODE_SESSION_ID`. The guide matches the archived spec; its one edit is
      10.3's. `remove-workflow-log-conversion` opened with its proposal, its open
      questions those its design owns. The promotion record is complete.
- [x] 10.10 Documentation citations: `make check-doc-citations
      CHANGE=workflow-steps-name-next-step`, resolving every match; then `openspec
      validate workflow-steps-name-next-step --strict`.
      `make check-doc-citations`: every cited path resolves, none a tombstone; so
      for `remove-workflow-log-conversion`. `make check-change`: every check passes,
      `openspec validate --strict` with the pinned validator among them.
- [x] 10.11 Archival: `openspec archive workflow-steps-name-next-step -y`, merging
      the deltas into `openspec/specs/change-workflow/spec.md`; the row links the
      archive.
      The permanent spec did not already hold the deltas, so they merged, with the
      pinned validator: three requirements added and three modified; its diff
      touches only those, the Purpose, and "Evidence", each requirement once. The
      change is at `openspec/changes/archive/2026-10-28-workflow-steps-name-next-step/`,
      and its row links it.
