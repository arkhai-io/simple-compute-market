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
test holds the drawing to the table: a section that changes the table redraws both
in the same commit, from what `make change-graph` prints. (Until the round-3 triage,
69 O1, the drawing was a Mermaid block in the architecture; see the note under
section 9.)

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
      Done as D1's rows, with five modelling choices D1 left open: `round` is one
      node (D1's "`round` / `implement`"), its in-progress result `implement`;
      `round-view` and `validate` are nodes too, since they are guards' remedies
      and the round's join suppliers, and their exits are derived from the table —
      the join's exit and each exit whose guard they remedy (`_remedying`); the
      bootstrap guard's remedy is `WAIT`, D1's `wait`, which no step runs; exits
      carry a `when` label (`advance`, `another round`, `a return`, …) that a
      triage's token chooses among; and the dependency gates and the bootstrap are
      *held* guards (no `check`), which the computation holds a stretch of the
      workflow on rather than checking as the exit is taken, as today —
      `dependencies()` before the change is read, `bootstrap_held()` and
      `bootstrapping()` around whatever is named. Beyond D1's rows, a dependency
      gating closeout is a held guard on the exit into closeout, since
      `dependencies()` holds it today; one gating design holds the change before
      its first node and has no exit to sit on. `archive-cleanup` has no exit; a
      triage's result names no kind (`Node.result`).
- [x] 1.2 Each exit guard as a function of the files and the log, from today's
      `validated()`, `fixed_since()`, `changed_outside_documentation()`, the round's
      join in `_round`, `return_confirmed()`, the clone's bootstrap, and the
      dependency gates, moved rather than rewritten, so each keeps its tests.
      Each checked guard's `check` in `graph.py` calls the computation's readings —
      `validated`, `fixed_since`, `changed_outside_documentation`,
      `return_confirmed`, kept as methods and typed by `graph.Readings`, which no
      type checker holds, since none covers `scripts/` — with the reason text each
      call site had, but for one that cannot show: on the round's triage into the
      pre-closeout review the second, identical validation check now carries the
      round's reason, and it holds wherever the first did; `another_round()`'s body became
      `REPEAT_FIX_VALIDATED`/`DOCUMENTED_FIX_VALIDATED`, the repeat pass's
      reading-first rule `REPEAT_FIX_READ`, closeout's correction check
      `CORRECTION_VALIDATED`. The held guards stay in `dependencies()`,
      `bootstrap_held()`, and `bootstrapping()`, whose docstrings name the table's
      guard. The round's join is declared in the table (`ROUND_JOIN`) and still read
      by `in_round` from the records, as before.
- [x] 1.3 `scripts/change_next_step.py`: the computation interprets the table in
      place of `_design`, `_implementation`, `_round`, `_pre_closeout`, and
      `_closeout`, and of `_STEP_PHASE`, `_PHASE_STEPS`, and `_REVIEW_PHASE` where
      the table now states what they held; today's token reading, file-time rules,
      and directed decisions are kept as the inputs that choose an exit, since
      round 2 replaces them. The result contract in the module docstring is
      unchanged.
      Each phase's reading takes the exits it reads through `follow`/`unmet`, which
      evaluate the exit's checked guards in the table's order, and names an
      in-progress node with `Node.result`. Still built in place: the owner's waiver
      of another design review, a direction rather than an exit; the round's join —
      its next `implement` session, `round-view`, `validate-and-review` — read from
      the records as before, `ROUND_JOIN` declaring it without being read; and
      `REPEAT_FIX_READ`'s `round-view` result. Correction to the plan: `_design`, `_planning`, `_implementation`, and
      `_closeout` keep their names, since `test_change_next_step.py` calls
      `Computation._design` directly and may not change; `_round` became
      `in_round`, `_pre_closeout` became `pre_closeout(source)`, the exit it is
      reached by, and `another_round` is gone. `_PHASE_STEPS` and `_REVIEW_PHASE`
      are read from the table (`graph.phase_steps`, `graph.review_phase`, from each
      node's phases); `_STEP_PHASE` stays: the disagreement leaves review and triage
      out of its comparison on purpose, and reading their nodes' phases from the
      table would change which logged line it compares. One difference from today, in a state no test reaches: an unconfirmed return
      recorded by a closeout triage names the owner with the archived-change reason
      rather than the unconfirmed-return one, since the table gives a closeout
      triage no return exit; both name the owner.
- [x] 1.4 A new `scripts/tests/test_change_workflow_graph.py`, unit: every exit names
      a node of the table; every guard's remedy is a node or the owner; every node is
      reachable from `design`; every node has an exit, except where the change is
      done.
      Reachability follows exits, guards' remedies, and join suppliers, the ways the
      computation names a node; a remedy may also be `WAIT` (the bootstrap). Added:
      every join waits on nodes, every logged step is one the wrapper runs, the
      return and another-round exits, the phases read from the table, and a node's
      result.
- [x] 1.5 Verification: `scripts/tests/test_change_next_step.py` passes unchanged —
      no test edited, added, or removed — which is this section's proof that
      routing is today's (D1, "round 1 reproduces exactly"); the new graph tests,
      unit; every other `scripts/tests/test_change_*` and `test_run_change_step.py`,
      unit; `make test`; `make check-change CHANGE=workflow-steps-name-next-step`.
      End-to-end: none of `e2e-tests/` exercises the workflow tooling, and none is
      owed.
      `test_change_next_step.py`, unit, unchanged from the section's base: 179
      passed. It asserts mostly steps and kinds, and reasons by substring, so a
      reason changed in a state it does not reach would pass; the fresh-context
      check compared every reason and guard order with the code before by hand,
      and found only the differences these notes give. The graph tests, unit: 44
      passed. `test_change_*.py`, `test_run_change_step.py`, and
      `test_check_tasks.py`, unit: 735 passed. `make test`: passed, every suite, run
      before the fresh-context check's fixes, which touched only comments, a held
      guard's declaration, and a graph test under `scripts/`, rerun above.
      `make check-packaging`: passed. `make check-change`: every check passes but
      the documentation citations, which report `scripts/change_workflow/convert.py`,
      the file section 7 creates. End-to-end: none, confirmed; no `Owed by
      validation:` line.

Handoff from section 1: `follow(source, target, reason, **context)` names the
target once the exit's checked guards hold; `unmet` returns the first unmet guard's
result and raises `StepError` for an exit the table lacks, which compute() reports
as unclassified — round 2's D4 rule (an undeclared exit names the owner) replaces
that. The context a guard reads is passed by keyword: `review`, `first` (the first
closeout review), and for the repeat pass `unread`, `in_clone`, `base`. Section 3
changes `Node.result` so a triage names its kind, and adds `done` as archive
cleanup's exit; `test_every_node_has_an_exit_but_the_one_that_finishes_the_change`
and `test_a_node_names_its_step_and_a_reviews_kind` then change with it.

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
      `graph.mermaid(table=TABLE)`: a box per node labelled `Node.label`, an edge per
      exit labelled with what it is taken on and each guard as `condition ⇒
      remedy`, its `otherwise` and `(held)` after it, and a `join` hexagon the
      join's members enter, each edge labelled with the record its node supplies.
      Node ids are the labels with `:` and `-` as `_`. Order is the table's, so it
      is deterministic; `validate`'s nine derived exits carry the guards of the
      exits they remedy, which makes the diagram busy around it.
- [x] 2.2 `Makefile`: `make change-graph`, printing the rendering, with a help line
      in the style of `make change-next`.
      Runs `PYTHONPATH=scripts python3 -m change_workflow.graph`, `graph.py`'s
      `main`; no new script file. Added to the workflow targets' `.PHONY` line.
- [x] 2.3 `openspec/specs/change-workflow/architecture.md`, "Routing is code, with
      the model as backstop": the diagram, as the rendering prints it, in one fenced
      `mermaid` block the check can find; the section's prose is promoted at
      closeout (10.9), not here.
      After the section's first paragraph, under a one-line caption naming
      `make change-graph` and `graph.py`. Not rendered by a Mermaid renderer here,
      none being installed; read by eye for Mermaid's syntax, its ids clear of
      Mermaid's keywords by inspection, which no test holds.
- [x] 2.4 The check, in `scripts/tests/test_change_workflow_graph.py`, unit: the
      architecture's diagram equals the rendering, and a failure names the first
      line that differs and the command that redraws it; a test that a table with an
      added exit no longer matches.
      `drift()` finds the document's one `mermaid` block and names its first
      differing line, both versions, and `make change-graph`; tests hold each of
      those, a shorter block, and a document with no block or two. The added-exit
      test gives the closeout triage a return. Also: the rendering draws an edge
      for each exit from its node to its target or join carrying its `when`, the
      record it supplies, and each guard's condition, remedy, `otherwise`, and
      `(held)` mark; its ids are distinct and no label needs escaping; and `make
      change-graph`, run with `python3` in a subprocess — the one test of this
      file that crosses a process boundary — prints exactly the rendering.
- [x] 2.5 Verification: the graph tests, unit; `make change-graph` run and its output
      compared by eye with D1's table; `make test`; `make check-change
      CHANGE=workflow-steps-name-next-step`. End-to-end: none, and none is owed.
      The graph tests, unit but for the `make` one: 52 passed. `make change-graph`
      is not among this step's allowed commands, so it was run by
      `test_make_change_graph_prints_the_rendering` instead, whose output equals
      the rendering, which equals the documented block; that block was compared by
      eye with D1's table: every row's exits and guards are drawn, and where the
      drawing departs from D1's rows it follows the section 1 notes — `implement`,
      as an exit and as the join's supplier, drawn as `round`; `round-view` a node
      with derived exits; `validate`'s exits spelled out; the dependency and
      bootstrap guards marked held, with one more on the exit into closeout; the
      repeat fix's validation naming the owner when it fails — and there is no
      `done`, which is section 3's. Workflow suites (`test_change_*.py`,
      `test_run_change_step.py`, `test_check_tasks.py`), unit: 743 passed. `make
      test`: passed, every suite, before the fresh-context check's fixes, which
      touched the graph tests, a caption, and two docstrings, rerun above. `make
      check-packaging`: passed. `make check-change`: every check passes but the
      documentation citations, which report `scripts/change_workflow/convert.py`,
      the file section 7 creates. End-to-end: none, confirmed; no `Owed by
      validation:` line.

Handoff from section 2: a section that changes the table pastes `make change-graph`'s
output over the `mermaid` block in the architecture companion in the same commit;
the block is written to the line, and `drift` names the first line that differs.
`make change-graph` is not in the implement step's allowed commands, so an
unattended implementation session writes the block from `graph.mermaid()`'s
algorithm and lets `drift` confirm it line by line, as this one did. The renderer escapes nothing, so a label with `"` or `|`
fails `test_the_diagrams_ids_are_distinct_and_its_labels_need_no_escaping` rather
than drawing invalid Mermaid. The target runs `python3 -m change_workflow.graph`
where its neighbours run a script file, since the plan adds no script.

Fix from the round-3 triage, 69 O1 (the owner chose a hand-laid draw.io diagram over
a generated one, for control over its layout): the Mermaid block is gone from the
architecture companion, which shows `docs/development/diagrams/change-workflow-graph.svg`
and names its source, `change-workflow-graph.drawio`, beside it, as the repository's
other diagrams do. `graph.drawing(table)` gives the boxes and edges any diagram of
the table draws (`Edge.pieces`: what a join's member supplies, what the exit is taken
on, and each guard's `guard_text`), and `mermaid()` renders from it, unchanged; the
drawing writes guards as numbers, `G1`–`G12`, in a legend box (`guards`).
`test_change_workflow_graph.py`'s `drift` parses the `.drawio`, writes each edge's
numbers out through the legend, and names every box or edge that differs from
`drawing()`, with a test that the SVG's embedded `content` draws the same, and one
that the architecture shows the export and names the source. The first layout was
written by this triage's session as draw.io XML and its SVG by hand, with no draw.io
here to render it: the owner adjusts it in draw.io, re-exporting the SVG with its
source embedded, and the test checks structure only. A table change now redraws
both files, from what `make change-graph` prints.

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
      `graph.node_of(target)` returns the node or raises `TargetError` naming why:
      also refused are a kind, sections, or target on a step that takes none, an
      unknown key, a validation for another validation, and `implement` without
      sessions of sections (`graph.section_ids`, moved here from `log.py`, which
      imports it); `implement` with sections is the `round` node. `DONE` is a node
      with no exits and no step (`runs` None). Correction to the plan: a triage's
      *result* still names no kind — `Node.result` is unchanged, since
      `test_change_next_step.py`, unchanged in this section, compares a triage
      result exactly (`{"step": "triage", "reason": …}`); section 6 changes it with
      that test. The drawing gains `done` and `archive_cleanup --> done`.
- [x] 3.2 `.agents/change-outcome.schema.json` and `outcome.py`: `next` an object
      target or, until section 8 switches the skills, a string — a per-property
      `anyOf`, which `harness_schema()` keeps (D3, the cadence's ordering note);
      `returned` requires `next` as an object and no longer `return_to`; `triaged`
      an array of strings. The schema check refuses an object `next` that names no
      node.
      The object form: `step`, `kind`, `sections` (shaped as `rounds`' sessions),
      and `target` (an object, its node checked by `node_of`), no other key;
      `outcome_problems` adds `node_of`'s refusal as `outcome.next names no node:
      …`, and an `anyOf` failure now lists each form's problems. Correction to the
      plan: `returned` requires `evidence` and *either* an object `next` or
      `return_to`, not an object `next` alone, until section 8 — the cadence's
      ordering note applies to returns too, since today's skills write `return_to`,
      and `test_change_next_step.py` logs such returns through `record_outcome`;
      8.5 drops `return_to`'s alternative. A returned `next`, when given, is an
      object, `return_to` or not.
- [x] 3.3 `triaged` (D3): a non-empty list of distinct `NN-<kind>` names, each a
      numbered record in the change's `reviews/` with its triage file beside it, at
      least one a review of any kind, `-external` included. `wrapper.py` records a
      triage outcome that breaks the rule, or names none, as stopped, naming the
      reference; the rule is one function that section 4's `record` calls too.
      `records.triaged_problems(triaged, reviews)`, a list of problems; the
      wrapper's `triage_outcome` applies it to a triage's `finished` or `returned`
      outcome, in the log's directory at the run's end, keeping the step's message
      ahead of the reason. A question, block, or stop names nothing.
- [x] 3.4 `log.py`: every line `append_entry` writes carries `"format": 2` (D7), so
      the wrapper's, the decision writer's, and the round lines all do;
      `record_outcome` refuses an outcome that sets `format`.
      `format` is reserved in `append_entry` beside `seq` and `at`, so no writer
      sets it; an outcome setting it is refused by the schema first. An appender
      whose change directory has gone since it was found raises `StepError`.
- [x] 3.5 `log.py`: `read_log` and `append_entry`, once they hold the log's lock,
      compare the file they locked with the file at the log's name by inode, and
      open and lock the log again when they differ (D7, 43 F2); a missing log is
      still empty to a reader, and created by an appender.
      One helper, `_locked`, compares device and inode and reopens until they match.
- [x] 3.6 `harness.py`: an unattended run's environment carries a marker that the
      run is the wrapper's, for `record` to refuse (D11).
      `run_claude` sets `CHANGE_WORKFLOW_UNATTENDED=1` (`harness.UNATTENDED_RUN`) in
      the run's environment, so a review run on Claude carries it too; a Codex
      review cannot run `record` in its read-only sandbox and is not marked.
- [x] 3.7 `review.py`: a review run's outcome names `{"step": "triage", "kind":
      <its kind>}` as its exit (D3). `cli.py`'s `log` printing, `wrapper.py`'s
      `earlier`, and `cost.py` render an object `next` as its display string, and a
      string as before.
      `review_outcome(path, kind)`. Correction to the plan: nothing renders `next`.
      `cli.py`'s `log` prints each line as JSON, where an object `next` reads as
      it is; `earlier` keeps the outcome's fields as the step gave them, an object
      among them; and `cost.py` reads no `next`. A display string in either would
      replace the target with words a reader could not route on.
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
      Unit, each by calling the module it names: the outcome tests check targets
      through `outcome_problems`, a returned outcome naming its step, and
      `triaged`'s shape; the wrapper tests run a triage through the wrapper with a
      fake harness over real records in a temporary directory, for each scenario
      named and an external review, a record without its triage file, and a
      malformed name; the log tests check the marker on lines from every writer,
      `format` refused from an outcome and from `append_entry`, and a call waiting
      on a replacement — a second thread runs `record_outcome`, or `read_log`,
      which opens the log while the test holds its lock; the test renames a new
      file over it and releases the lock, and the line lands in the new file, the
      replaced one unchanged, or the read returns the new file's lines. Both fail
      with the inode comparison disabled, which was tried and reverted. The
      thread's opening is observed through `/proc/self/fd`, a bounded wait, and
      the tests skip where `/proc` is absent. The review test checks the logged
      line's exit; the graph tests `done`, `node_of`, and the redrawn block. One
      harness test crosses a process boundary, so is not unit by `TESTING.md`'s
      definition: a Python process `run_claude` starts, standing in for Claude
      Code, sees the marker; that Claude Code passes it on to its own commands is
      the harness's behaviour and not tested here. Those six files and
      `test_change_next_step.py`: 488 passed, the latter unchanged from the
      section's base (179).
      Workflow suites (`-k "change or run_change_step or check_tasks or
      round_view"` over `scripts/tests/`): 979 passed. `make test`: passed, before
      the fresh-context check's fixes, which touched only the schema's return
      branch, `append_entry`'s missing-directory error, and tests under
      `scripts/`, rerun above. `make check-change`: every check passes but the
      documentation citations, which
      report `scripts/change_workflow/convert.py`, section 7's file. End-to-end:
      none, confirmed; no `Owed by validation:` line.

Handoff from section 3: from this commit the change's own log mixes unmarked lines
with marked ones, which section 6's detection names for `convert`, as D7 intends.
Today's routing still reads string `next` and `return_to`, which every line still
carries or omits as before; an object `next` (a review's, from now on) is read by
nothing yet, since `change_next_step.py` reads a review's line only for its
outcome. Left for section 6: a triage's result naming its kind (`Node.result`),
and the routing on `triaged`. Left for section 8: dropping the string `next` and
`returned`'s `return_to` alternative. `section_ids` lives in `graph.py`, and
`note_round` calls it from there. The replacement tests' helper, `_while_replaced`
in `test_change_workflow_log.py`, is what section 7's "an append waiting on the
conversion" can reuse with the real `convert`. It polls `/proc/self/fd` rather than
a hook in `_locked`, since production code exposes no test-only hook
(`ARCHITECTURE.md`, "Deterministic database-concurrency tests").

## 4. `record`: an interactive run records its own outcome

Delivers `python3 scripts/run_change_step.py record <change> <step> --outcome
'<json>'` (D11; requirement "Interactive step runs record their outcome"). Touches
`scripts/change_workflow/cli.py`, `log.py`, and `scripts/tests/`.

- [x] 4.1 `record`: checks the outcome against the outcome schema and, for a triage,
      `triaged` by section 3's rule; appends it through `record_outcome` with the
      session from `CLAUDE_CODE_SESSION_ID`, or from `--session`, the commit at
      `HEAD`, and `interactive: true`.
      `log.record_interactive` holds the writer's rules — a session and a commit,
      the triage's `triaged` by `records.triage_outcome_problems`, which the
      wrapper's `triage_outcome` now shares, then `record_outcome` with
      `interactive: true` — and `cli.interactive_outcome` the harness's side: the
      marker, the session (the `--session` given wins over the variable), the
      JSON, and `HEAD` through the wrapper's `head` seam, `git_head` by default.
      `main` takes the environment as `environ`, `os.environ` by default, the seam
      its tests use. A `HEAD` that cannot be read is refused, rather than recorded
      as no commit.
- [x] 4.2 Refusals, each naming why and writing nothing: no session id, naming the
      variable (scenario "The harness exports no session id"); inside an unattended
      run, by section 3's marker (scenario "An unattended run records its own
      outcome"); a step not in `STEPS`; an outcome the schema or `triaged` refuses.
      Also refused: an `--outcome` that is not JSON. The marker is checked first,
      so a wrapper's run is refused whatever session it names. Each prints
      `ERROR: …` and exits 1, as every command of the CLI does.
- [x] 4.3 Verification, unit, in `test_run_change_step.py` with a real Git
      repository in a temporary directory for `HEAD`: an interactive triage's
      outcome recorded with its session, `HEAD`, `interactive`, and the format
      marker (scenario "An interactive triage finishes", as far as the log); each
      refusal; `make test`; `make check-change CHANGE=workflow-steps-name-next-step`.
      End-to-end: none, and none is owed.
      Through `main` with an injected environment over real records in a
      temporary directory. One test, the interactive triage, reads `HEAD` from a
      real Git repository it creates, starting `git` — a process boundary, so not
      unit by `TESTING.md`, as the round test beside it; the rest are unit, `HEAD`
      given through the wrapper's seam: `--session` recorded whether or not the
      variable is set; each refusal leaving no log — no session, the marker, the
      marker with `--session`, an unknown step, a schema refusal, an object `next`
      naming no node, an unknown record, an empty `triaged`, an outcome that is not
      JSON, and no `HEAD`. In `test_change_workflow_log.py`, unit,
      `record_interactive`'s own refusals of a missing session and commit. The
      workflow suites (`-k "change or run_change_step or check_tasks or
      round_view"` over `scripts/tests/`): 994 passed. `make test`: passed, every
      suite (`scripts/tests`: 1690 passed), before the fresh-context check's fixes,
      which touched only `scripts/`, rerun above. `make check-packaging`: passed.
      `make check-change`: every check passes but the documentation citations,
      which report `scripts/change_workflow/convert.py`, section 7's file.
      End-to-end: none, confirmed; no `Owed by validation:` line.

Handoff from section 4: `record` exists for section 8's skills and section 9's
guide; `python3 scripts/run_change_step.py record --help` prints its usage. The
computation does not route on an `interactive` line differently from a wrapper's:
section 6 reads both alike. The change-workflow architecture's "The log is the
wrapper's alone" is now untrue; 10.9 rewrites it ("written by the wrapper, `record`,
the decision writer, and `convert`").

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
      `Declaration.entry`, a tuple of `EntryGuard(condition, waivable, check)`; a
      check reads `Standing(archived, awaiting)` — the kinds of review awaiting
      triage — the target, and whether the entry is a direction. `entry_refusal(
      target, standing, directed=)` names the first unwaivable guard not met, of the
      target and, for a directed validation only, its nested target: on a step's
      exit the nested target is checked on the validation's own exit (D1). The
      waivable guard has no check here: the review checks it as it starts (5.4).
      A validation whose target names no node is refused by validation's own
      guard, which the refusal names; any other target naming no node raises
      `TargetError`.
      Each box of the drawing lists its entry guards (`entry: …`, `(waivable)`);
      the block was written by hand from `mermaid()`'s algorithm and `drift`
      confirms it.
- [x] 5.2 `log.py`, `note_orchestrator` (D6): `next` is the target object; every line
      carrying `next` is `by: owner`; its target is a node of the table; and the
      log's writer refuses it, naming the guard, while an unwaivable entry guard of
      any node it names is not met — the target, and the target nested in a
      direction to validation (D5, 36 F1). No exit guard is checked. The special
      cases for review, plan, archive cleanup, and confirmed returns, and
      `redesigned_after_return`'s gate, are removed: a waiver is a plain direction
      whose `reason` says what it skips. `resolves` and `reads` are unchanged.
      `note_orchestrator` keeps `next_step` and `kind` and gains `sections` and
      `target`, building the object with `direction()`; its `status` parameter is
      gone. `standing(path)` reads the archive from the change directory's place
      and the awaiting reviews from `reviews/` and the log: a numbered record of a
      review kind, `-external` included, that no finished or returned triage line,
      and no conversion line, names in `triaged`. `unused_direction(entries)` is
      the owner's latest direction while no run of its node follows it (a review
      of its kind; a triage naming a review of its kind). `redesigned_after_return`
      stays, the computation's reading until section 6, and reads a decision's
      step through `directed_step`, which takes the object or an unmarked line's
      string. The computation's three readers of a decision's `next` (`directed`,
      `waived_design_review`, `return_confirmed`) read it the same way, so today's
      routing holds on directions written as objects.
- [x] 5.3 `cli.py`: `note orchestrator` keeps `--next`, `--kind`, and `--sections`,
      and gains `--target` for a direction to validation, which `--kind` and
      `--sections` then qualify (D6); it builds the object.
      Correction to the plan: `note orchestrator` had no `--sections`; it gains
      both, `--sections` in `note round`'s form. The writer builds the object from
      the flags, so a caller of `note_orchestrator` passes the same names. The
      index lookup for the waiver's status is gone.
- [x] 5.4 `review.py`: the pre-closeout review's validation check accepts the
      owner's direction to that review, logged and not yet used, as its override, as
      `--unvalidated` is (D5, scenario "The owner directs a pre-closeout review over
      a failed validation").
      `run_review` reads `unused_direction` from the change's log; a direction to a
      review of the kind it runs sets the override. Its refusal names both
      overrides.
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
      Unit. `test_change_workflow_log.py`, calling `note_orchestrator` on logs in
      real active and archive directories in a temporary directory: each named
      scenario, a validation without its target refused naming validation's guard,
      `done` never directed, the archive both ways for design, planning, the round
      and an implementation, the closeout review, its triage, and archive cleanup,
      and for a validation nesting one, a triage directed once an external review
      awaits it, the owner's directions past the pre-closeout review's validation
      and closeout's, the waiver as a plain direction, and `unused_direction` for a
      review, a triage (used only by a triage naming a review of its kind), and any
      other step (used by its run however it ended).
      `test_run_change_step.py`, through `main`: the flags building each object,
      and a validation without its target refused naming the guard.
      `test_change_workflow_review.py`, with a fake reviewer: a pre-closeout review
      over a failed validation starts on the owner's direction, through
      `review_and_log`; the next one, through `run_review`, is held to the
      validation again; and a direction to another node overrides nothing. The
      graph tests: the entry
      guards as D1 tabulates them, `entry_refusal` for a direction and for a step's
      exit, and the boxes drawn with their guards. `test_change_next_step.py`
      changed in three places — two waiver calls lose `status=`, one asserts the
      object, and the closeout triage's return to planning is now refused by the
      writer, the owner declining it instead; its routing assertions are
      otherwise as they were, and section 6 rewrites it. Workflow suites
      (`-k "change or run_change_step or check_tasks or round_view"`): 1028
      passed. `make test`: passed (`scripts/tests`: 1722), before the
      fresh-context check's fixes, which touched `graph.py`'s `entry_refusal`,
      the review's refusal message, and tests, all under `scripts/`, rerun above.
      `make check-packaging`: passed. `make check-change`: every check passes but
      the documentation citations, which report `scripts/change_workflow/convert.py`,
      section 7's file. End-to-end: none, confirmed; no `Owed by validation:` line.

Fix from the round-3 triage, 68 F1: a failed or inconclusive validation of a fix
commit a triage made names the owner, and the triage skill said the owner "may run
this triage by hand", since the triage's entry guard refused the owner's direction
to it once its review was triaged. `log.standing()` now also counts, as awaiting the
triage of the latest review's kind, an untriaged validation record numbered after
that review, unless it is a design review, whose triage makes no commit a validation
reads (narrowed after the fresh-context check, which found the first round's
validation opening a design triage); `AWAITS_TRIAGE` reads "a review of its kind, or
a validation after it, awaits triage". The triage skill says the owner directs it, and the orchestrate
skill's list of refusals names the validation. Tests: unit,
`test_change_workflow_log.py::test_a_triage_is_directed_for_a_validation_after_its_kinds_latest_review`
(a validation before the latest review does not count; one after it does, until a
triage names it), and `test_change_next_step.py::test_the_owner_directs_a_failed_fix_validations_triage`
(the full path: the failed validation names the owner, the direction names the
triage, and that triage's outcome, naming the review and the validation, routes
through its exit's guard once a passing validation is in).

Handoff from section 5: until section 9 rewrites `change-orchestrate`, the
orchestrating session's own repeat-review decision (`--by orchestrator --next
review`) is refused by the writer, as D5 intends; the owner's word is recorded `--by
owner`. The computation still accepts an unmarked decision's string `next` through
`directed_step`, the older reading section 6 deletes with the detection. A
direction's nested target is checked by the writer; section 6 checks a validation's
exit against the target it carries with `entry_refusal(..., directed=False)`, and a
step's exit with the same call. `standing(path)` is what section 6 builds its
`Standing` from. Left open for section 6, which routes on directions: a direction
to `round-view` is never used up by `unused_direction`, since no run of it is
logged (the round view's own state says when the owner read); a triage run that
ends without `triaged` — a question or a stop — does not use up a direction to a
triage, since nothing records which kind it ran for, while the computation's
`directed()` counts any triage run; and `standing()` reads an unconverted log's
triages as naming nothing, so every review awaits triage there — the detection
should hold routing before any direction is checked on such a log, and section 7's
`convert` checks its direction against the converted lines. Section 9's
`change-orchestrate` rewrite also drops its account of the design-review waiver's
old gate (the change `in design`, a finished redesign).

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
      `route_of(log, join)` walks the log into a `Route`: a step's exit (`EXIT`),
      the owner's direction (`DIRECTED`), a round line (`ROUND_STARTED`), a
      directed validation that ran (`VALIDATED`), a validation naming another
      target (`ELSEWHERE`), a finished run naming none (`NO_EXIT`). A direction
      stands until a run of its node takes an exit (`log.ran`: a review of its kind,
      a triage naming a review of its kind, a round line or `implement` for the
      round); a run of another node in between leaves it. A run taking no exit — a
      question, block, or stop — leaves the route where it was, so its step is named
      again once answered or resolved; `log.unused_direction`, the pre-closeout
      review's override, now reads a direction the same way, through the same
      `ran`, where section 5 had any run use it up. No run of `round-view` is
      logged, so a direction to it reads the round's join, whose records say whether
      the reading is due: a validation in it names the round's triage as given, and
      a review's exit replaces it. `unused_direction` never sees such a direction
      used, which matters to no override, since only a review's direction is one. A triage line's node is the kind of the
      latest review its `triaged` names; `triage_line(record)` is a review's
      outcome. `return_confirmed(run)`: an owner's decision resolving the run with a
      target; graph's `RETURN_CONFIRMED` now reads the returned run
      (`Readings.return_confirmed(run)`), and once confirmed the direction is the
      route, so the guard is met only by a direction. Deleted with the token
      readings: `governing`, `_section_text`, `_seconds`, `set_aside`,
      `waived_design_review`, `not_advancing`, the per-kind reading of decisions
      that `directed()` held (it now reads one direction), `untriaged`, `planned`,
      `pre_closeout`, `in_round`, `_design`, `_planning`, `_implementation`,
      `_closeout`, and, unused once the log is read only in its format, log.py's
      `redesigned_after_return` and `directed_step`. Decisions this task's reading
      made, beyond the plan's words: the route names its step whatever the status
      says (D8's "an exit or direction that contradicts the status is reported");
      `disagreement()` still reports a log whose last step is past the status, now
      saying the result follows the log's route, and not once an owner's direction
      follows that step, whose step sets its own status. With no exit or direction logged, a
      design status names design, and any later status the owner, rather than a
      step inferred from the phase. A finished run naming no exit (a prose `next`,
      which the schema admits until 8.5) inside the round's join leaves the round as
      its records say — section 8's own implementation session ends that way — and
      anywhere else names the owner. `pending` waits in the status's phase and in
      the phases of the node the route names, so a directed step that stopped before
      setting its status waits rather than reruns. A marked `returned` outcome that
      gives only `return_to` — the schema's transitional form, not an older line's —
      returns to that phase's step (`implementation`: the round), so a declined one
      still names the owner; `_RETURN_STEP` goes with the field (see the handoff).
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
      `chosen(route)`: an undeclared exit names the owner with `choice` and the
      node's `exits`; `guarded` gives the first unmet checked guard's result with
      the exit as `target` (the owner's too); `entered` checks the target's
      unwaivable entry guards with `entry_refusal(..., directed=False)`; an exit
      with a join reads the round's join. The implementation triage's two exits to
      the round are told apart by the target's sections (`graph.OUT_OF_ORDER`, now
      a constant). A validation naming the target it was given — the round's
      triage in the join, the direction's nested target, otherwise the exit whose
      guard it remedies (`_given`) — leaves the route where it was, so the guards
      are checked again from the files; a directed one leads, once
      `validated()` passes, to its target through its entry guards. The join's
      `validate-and-review` and `validate` carry `target`. `directed()` checks the
      direction's unwaivable entry guards again on the change as it stands. An
      out-of-order round carries `by`: `triage` or `owner`, each tested.
- [x] 6.3 Recovery (D8): the step a last exit or direction names, with no run of it
      logged, is named as in progress, its reason saying that if no session of it is
      open an interactive session ended without recording, to be resumed or recorded
      with `record`; where the files have moved past it — a plan that set
      `ready for implementation` and recorded no outcome — that step is named with a
      `disagreement` naming the missing outcome and `record`, and no step after it.
      `enter` adds `in_progress(node, line)` to the reason — the `record` command for
      the node's step — when no run of the node follows the routing line (not for
      the round, whose run is its line, nor `round-view` or `done`), and, on a
      step's exit only, `passed_by_status(node)` as the `disagreement` when the
      status's phase is past every phase of the node: an owner's direction back to
      an earlier step is no missing outcome.
- [x] 6.4 Detection (D7): a log holding a line without the format marker, or numbered
      records under `reviews/` and no log, names the owner with
      `python3 scripts/run_change_step.py convert <change>`, and the log is read as
      nothing else. The module docstring's result contract gains `target`.
      `unconverted()`, after the change is located and its records read, before the
      bootstrap and every routing reading: the result carries the command as
      `convert` and names the first unmarked line's seq. A cleaned-up change is
      `done` before it, as history. This change's own log now names the owner with
      the command, which section 7 creates.
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
      Fixtures log marked outcomes through `record_outcome`, `note_round`, and
      `note_orchestrator`: object exits (`_done`, `_returned`), review runs naming
      their triage (`_review`), triage runs naming `triaged` beside their files
      (`_triage`), owner directions (`_direct`), and unmarked lines written raw
      (`_unmarked`); triage files hold prose only. Each named scenario has a test,
      most named for it; three share or carry another's name: "Triage records
      another round" is the three another-round tests (pre-closeout over a fix, the
      same commit with no fix, closeout); "A triage has not finished" and "A new
      triage file awaits its outcome" are one parametrized test; "A validation
      before closeout passes" is the pre-closeout triage advancing once `HEAD` is
      validated. Kept under the behaviour they hold: waiting runs and denials,
      dependencies, the plan's mapping, the clone, the bootstrap, the round view,
      merges, the repeat pass and its readings. Deleted with what they held: the
      `## Next` token and `## Gate` readings, the file-time confirmation, two reviews
      triaged together read by their files' times, an earlier round's token, and a
      status with no route naming its phase's step past design (now the owner,
      tested for planning, implementation, and closeout). Changed: a failed fix
      validation before the repeat review, triaged alone, now names the owner,
      since a triage names a review among what it triaged; "a plan that finished
      leaving the status in planning", which went to the owner, is now "a status
      set back by hand is reported" — the route, with its `disagreement`. Added
      beyond the scenarios: a direction to sections out of order, to the round
      view, a directed review that stopped and was resolved, and a direction back
      reporting no disagreement.
- [x] 6.6 Verification, unit: `test_change_next_step.py` as rewritten; the graph
      tests with any redrawn diagram; every other `scripts/tests/test_change_*`,
      `test_round_view.py`, and `test_run_change_step.py`; `make test`; `make
      check-change CHANGE=workflow-steps-name-next-step`. End-to-end: none, and none
      is owed.
      `test_change_next_step.py`: 192 passed; unit, each calling `compute`, or `main`
      for the command's output, with injected seams over real files in a temporary
      directory, but for three that
      start `git` in a real repository (the round view, the conflicted merge, the
      clone), a process boundary, as before. The graph tests, unit: 64 passed; no
      diagram redrawn, since no guard, exit, or entry guard changed.
      `test_change_workflow_log.py`, unit, with `unused_direction`'s test of a
      question that leaves a direction standing. Workflow suites (`-k "change or
      run_change_step or check_tasks or round_view"` over `scripts/tests/`): 1041
      passed. `make test`: passed, every suite (`scripts/tests`: 1736), before the
      two fresh-context checks' fixes, which touched only `scripts/`; `scripts/tests`
      rerun after them: 1742 passed. `make check-packaging`: passed. `make
      check-change`: every check passes but the documentation citations, which
      report `scripts/change_workflow/convert.py`, section 7's file. End-to-end:
      none, confirmed; no `Owed by validation:` line.
- [x] 6.7 The round's join read from `graph.ROUND_JOIN`: the records its members
      supply decide what the join still waits for and which member's step the
      computation names, the clone's and the repeat pass's reading rules kept; unit,
      in `test_change_next_step.py`, a table whose join lacks a member no longer
      waits for that member's record (52 F1: the table declared the join while
      `in_round` read it from record kinds of its own, so a changed join redrew the
      diagram and left routing as it was).
      `round_join` reads `Computation`'s `join` seam, `ROUND_JOIN` by default: the
      round's sessions only while the round is a member, the owner's reading only
      while `round-view` is, and validation and the review only while each is
      (`_SUPPLIES`, the record kind each member supplies). The repeat pass's state is
      `round_pass(current, again)` (`Pass`), shared with the implementation
      triage's exit to another review. Tests: a join without `round-view` goes from
      a committed round straight to `validate-and-review`; one without validation
      triages a round with no validation record.
- [x] 6.8 `graph.py`: a triage's result names the kind of review it triages
      (`Node.result`, D2), with `test_change_next_step.py`'s rewrite (6.5) and the
      graph test `test_a_node_names_its_step_and_a_reviews_kind`: section 3 left
      it, since that test file is unchanged until 6.5 and compares a triage's
      result exactly.
      The graph test is now `test_a_node_names_its_step_and_its_kind`.

Fixes from the round-3 triage:

- 68 F2 (the triage's fix over the reviewer's, on the owner's word): in a change
  worked in the owner's checkout, a validation or review record stood in for the
  owner's reading, so the round went to triage with no owner record. `round_pass`
  now holds a first pass unread until its owner record exists, wherever the change
  is worked; `round_join` still names a missing validation or review first, adding
  `reading` beside them only in a clone, since in this checkout the view would move
  the branch under them, and names `round-view` once both are in. Tests: unit,
  `test_the_round_is_read_before_triage_though_its_validation_and_review_ran_first`;
  `test_reviews_and_validation_await_triage` and
  `test_an_external_implementation_review_counts_for_the_round` gain the owner
  record they assumed.
- 69 O2 (the owner's reading of D8, seq 78): a status set back by hand was reported
  as a `disagreement` beside the log's route. `Computation.set_back` now follows it:
  with the status's phase earlier than the log's last step's and no owner direction
  after that step, the computation names the node the phase starts at
  (`_PHASE_START`: `design`, `plan`, the round; no step runs after closeout), its
  unwaivable entry guards checked as for a direction, the reason saying the status
  is followed and not that a session may have closed unrecorded (`enter(...,
  fresh=True)`). An owner's direction or a round line after that step ends it: the
  fresh-context check found the round named again and again once its line was
  recorded, since a round line is the orchestrating session's and has no phase.
  `disagreement()` is gone; `passed_by_status`, a status ahead of the log, stays.
  Tests: unit, `test_a_status_set_back_by_hand_is_followed` (was "…is reported"),
  `test_a_status_set_back_is_followed_to_where_its_phase_starts` (planning, the
  round), `test_a_status_set_back_to_implementation_routes_on_once_its_round_is_recorded`,
  `test_a_status_set_back_and_then_directed_follows_the_direction`, and
  `test_a_status_set_back_past_the_archive_goes_to_the_owner`.

Handoff from section 6: from this commit the computation names the owner with the
`convert` command for this change itself, whose log holds unmarked lines, and the
command is section 7's; section 7 is started directly, not from the computation.
For `convert` (section 7): the conversion line (`step` `convert`) is skipped by
`route_of` and `pending`, which read only `STEPS`, and counted by `triage_line` and
`log.standing` as naming its `triaged`; the direction after it is an ordinary owner
direction, routed by `directed()`. Detection is any line whose `format` is not 2,
so every rewritten line needs the marker. The proposal's "a later decision whose
target has not run" is `route_of`'s `DIRECTED` route, and `log.ran` the one
reading of a run of a node; the remedy of an unmet exit guard on the edge is what
`Computation.guarded` gives for the edge with `context`, which the proposal can
reuse rather than evaluate the guards again. For 8.5: once `returned` requires an
object `next`, delete `_RETURN_STEP` and its reading in `_exit_of`; once `next` is
an object only, `route_of`'s tolerance for a finished run naming no exit inside the
round's join can go too (section 8's own implementation session is the run it
exists for). Declined from the fresh-context check: removing the repeat pass's
file-time reading (an owner record saved after the pass's triage file), which 6.7
keeps. For review: the route names its step whatever the status says, and a status
with no exit or direction logged names the owner past design — this section's
reading of D8 and of "MUST NOT infer an exit from the phase", noted in 6.1.

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
      `convert.conversion` refuses both with `StepError`, before anything is built.
      "Already converted" is the computation's detection inverted — no unmarked
      line, and a log or no numbered records — through `log.unmarked`, which
      `Computation.unconverted` now calls too. A conversion line counts as naming a
      triage as a marked triage outcome does, so a rerun's earlier conversion
      attests what the owner attested before.
- [x] 7.2 The log's lines rewritten in place, each keeping its seq: a decision's
      string `next` and `kind` become the target object; a `returned` outcome's
      `return_to` gains its target in `next`; an outcome's prose `next` moves into
      its `message`; every line gains the format marker. One conversion line
      appended, `step` `convert`, `outcome` `converted`, naming as `triaged` every
      review with a triage file, and no exit.
      `convert.rewritten(entry)`: only unmarked lines change, the marker placed after
      `at` as `append_entry` writes it; prose joins the message as `\n\nNext: …`;
      `return_to` is kept beside the new `next` (`design`→`design`,
      `planning`→`plan`, `implementation`→`round`, the computation's transitional
      `_RETURN_STEP` copied, since 8.5 deletes that one). A review line's older
      `next: "triage"` is prose like any other. `triaged` names review records only
      (`-external` included), not the validation and owner records triaged beside
      them, as D7 says; it may be empty.
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
      `convert._propose`, in this order: the latest decision carrying `next` after
      the latest triage's run whose node no run has taken since (`log.ran`), by the
      owner or, as older repeat-review decisions were, the orchestrating session;
      nothing while a review numbered after the latest triaged one awaits its
      triage; nothing while any step's run follows the latest triage's; else its
      exit. The latest triage is the highest-numbered review with a triage file;
      its run (`_anchor`) is the latest marked triage outcome naming it, else the
      latest triage line after the review run that published it (`record`), else
      that run, else, for a review no run published, the latest triage line. The
      exit is the one that marked outcome names where there is one, else the token
      (`read_triage`, the deleted `next_token` reading with its `## Next: …` form):
      `Advance` the table's `advance` exit — for an implementation triage the
      pre-closeout review once every section before closeout is checked — `Another
      round` the table's `another round` exit, other words nothing, `Returned` the
      returned run's rewritten `next`, resolving it, or nothing once a decision
      resolved it without directing. The guards are the computation's own:
      `Computation.context` and `Computation.guarded` on the edge, the triage's run
      read as naming the review; a validation remedy becomes `{"step": "validate",
      "target": <the exit>}`, and a remedy no direction can name — the owner, or a
      repeat pass's `round-view` — proposes nothing, saying why. Every proposal is
      checked by `entry_refusal(..., directed=True)` on the converted log. Beyond
      the plan's words: the marked outcome's exit taking precedence over the token,
      since under the current skill `## Next` is prose whose first word may be
      "Advance"; the awaiting-review rule; and declining a remedy that is not a
      validation.
- [x] 7.4 The owner's confirmation: the command shows the proposal, or why there is
      none, and every review the conversion line will name, each with the first line
      of the `## Next` or `## Gate` it read, flagging those no marked triage outcome
      names; it writes only when the owner confirms, which attests the flagged
      triages finished, or gives `--next` in the proposal's place (43 F1). The
      direction is written through `note_orchestrator`'s checks (section 5), `by:
      owner`; declining writes nothing.
      `run_change_step.py convert <change>` shows, writing nothing; `--confirm`
      writes; `--next`, qualified by `--kind`, `--sections`, `--target` as `note
      orchestrator` takes them, gives the direction in the proposal's place, shown or
      written; `--reason` replaces the direction's reason. Correction to the plan:
      `--decline`, with `--confirm`, writes the conversion with no direction, only
      where the proposal confirms a pending return — the spec's "had the owner
      declined it, no direction would be written, and the computation would name the
      owner for seq 50" needs the conversion written while the return is declined.
      `note_orchestrator`'s checks are `log.decision_line`, split out of it, which
      checks a direction against the converted lines held in memory, since the log
      cannot be read by name while its replacement holds the lock.
- [x] 7.5 The replacement (D7, 36 F3, 43 F2): the log's exclusive lock taken before
      the log is read and held until the converted log — the rewritten lines, the
      conversion line, and the direction — is written to a temporary file beside the
      log and renamed over it; a change with records and no log gains its log the
      same way.
      `log.replace_log(path, rewrite, replace=os.replace)`, in `log.py` so it stays
      the log's only writer: locked through `_locked` (the inode check), the file
      `.workflow.jsonl.<random>.tmp` beside it, fsynced, given the old log's
      permissions, renamed, and removed if the rename did not happen. A change with no
      log gains one by the same open, `a+` creating it; a refused or failed
      replacement removes a log that open created while the name still holds it,
      empty, and keeps the new log once the rename has happened. An appender that
      opened the created log meanwhile reopens it by `_locked`'s check, which finds
      the name gone — read from the code, not tested. A process killed before the
      rename may leave an empty log, still detected, and its temporary dotfile, which
      nothing reads; a refusal may leave `reviews/` created. `append_entry`
      and `replace_log` share `log.numbered`, the line with its seq, time, and
      marker. The computation's files are read before the lock is taken
      (`Computation.read`, split out of `run`), since a read of the log by name under
      the lock would wait on it. `--confirm` computes the conversion again under the
      lock and prints what it wrote, so a line appended between the preview and the
      confirmation is in what is written though the owner was not shown it; the
      command is run between steps, when no step appends (D7), and nothing further
      guards that interval.
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
      A new `scripts/tests/test_change_workflow_convert.py`, 36 passed: each test
      calls `convert_change`, `rewritten`, or `read_triage`, or `main` for the
      command, with the computation's seams over a real index, task list, records,
      and logs in a temporary directory, and `change_next_step.compute` for where a
      converted log routes. By `TESTING.md` these are unit only loosely: a test
      drives the conversion, the log's replacement, and the computation together over
      real files, as section 3's and 6's tests do; the append test adds a thread.
      Each named scenario has a test of its name or close to it; "A conversion's
      triage is not attested" also records an outcome whose exit differs from its
      file's token, and the proposal follows the outcome. Also: a change with records
      and no log; a refused and an interrupted conversion of one, which leave no log;
      the already-converted refusal; a triage a recorded outcome names; a later
      direction naming no node, and one that can no longer be entered; a review
      awaiting its triage; the last round's advance, proposing the pre-closeout
      review's validation; a failed validation of `HEAD`, which no direction
      remedies; other words; `Returned` with no returned run; a return a decision
      declined; a declined proposal; `--decline` with no return; the rerun's
      attestation of the first conversion's reviews; the command's show and write,
      and `--target` and `--sections` building the direction; the token reading; and
      the rewrite of each line shape, its keys' order included. The routing tests
      whose conversion is written assert the step `compute` then names; the
      refusal, append, and command tests assert the lines written instead, and the
      preview-only tests the proposal shown. The interruption test's `replace` raises
      before the rename: the log is byte-for-byte unchanged, no temporary file is
      left, the computation still names `convert`, and a second run converts. The
      append test reuses section 3's method — a thread runs `record_outcome` once the
      conversion holds the lock, observed through `/proc/self/fd`, then the rename —
      and the line lands after the direction; with `_locked`'s inode comparison
      disabled it fails, the line lost to the replaced file, which was tried and
      reverted. `test_change_workflow_log.py`, unit: `replace_log` — the new lines
      with the old log's permissions and no file left beside it; a refusal and a
      replacement interrupted before its rename, of lines it would have changed,
      each leaving the log's bytes as they were, or no log where there was none; a
      failure after the rename keeping the new log of a change that had none,
      which an earlier cleanup deleted; a missing log created — and `unmarked`;
      `descriptors_of` moved from it to `change_workflow_fixtures.py`.
      `test_change_next_step.py` and `test_run_change_step.py`: unchanged, passing.
      `scripts/tests`: 1784 passed. `make test`: passed, every suite
      (`scripts/tests`: 1770), before the two fresh-context checks' fixes, which
      touched only `scripts/`, rerun above. `make
      check-packaging`: passed. `make check-change`: every check passes, the
      documentation citations included now that `convert.py` exists. No table change,
      so no diagram redrawn. End-to-end: none, confirmed; no `Owed by validation:`
      line.

Handoff from section 7: before section 8, the orchestrating session runs `python3
scripts/run_change_step.py convert workflow-steps-name-next-step` on the owner's
word, which shows first and writes only with `--confirm`. On this change's log as it
stood at this section's start, nothing should be proposed: the latest triaged review
is 52-implementation, and runs follow its triage (validate at seq 70, implement at
72, 74, 75, and this section's), so the owner gives `--next`. Read from the code, untested on this log: `--next
round-view` reads the current round's join, whose round line (seq 71) names the
sessions `[3, 4, 5, 6, 7]` and `[8, 9]`, and so should name `implement` of 8 and 9;
`--next round` would have the plan's next round recorded again as a new round line.
Not run here:
the implement step may not run the command, and the conversion is the owner's. The
conversion reads the computation's files without locating the change (`locate`
is not run), so in a clone a repeat pass's reading is judged as a workspace change's
would be: the proposal may name the `round-view` remedy as nothing proposed where the
computation, in the clone, would run the reading beside the validation. `convert`
imports `change_next_step` for `Computation`, `Route`, `Record`, and
`target_label` (renamed from `_label` to be shared): the package's first module to
import the computation, which imports none of `cli` or `convert`, so there is no
cycle; since `cli` imports `convert` at module level, every command of
`run_change_step.py` now loads the computation and its standard-library imports,
which the fresh-context check raised and was left, a function-local import being no
lighter an edge. `test_change_workflow_convert.py` imports `change_next_step` by name, where
`test_change_next_step.py` loads a second copy of it; neither compares the other's
classes. For section 8's skills and section 9's guide: the conversion's preview is
text for the owner to read, and its write prints the conversion line and the
direction as JSON lines.

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
      `{"step": "plan"}`; closeout, whose code-needing part returns the change to
      implementation (the spec's phase requirement), names `{"step": "round"}`, the
      owner's confirmation directing the implementation that makes the edit, since
      every section before closeout is checked. Validation records its target in its
      step 1, from whatever result carries one: `validate`, `validate-and-review`,
      or the owner after a failed or inconclusive validation of it, so a rerun names
      the exit whose guard it remedies; with none (a validation started outside the
      route) it names the round's triage, the join's target. Beyond the plan's
      words: a merge-resolving implementation run names `{"step": "round"}`, an exit
      implementation does not declare, so the computation brings it to the owner
      (D4), its message saying where the change stood. The design does not consider
      merge runs; naming implementation's one exit instead sends a merge between
      rounds into a triaged round's join, which the computation reports as
      unclassified, and copying the computation's result is not always a target (a
      round result carries `by`, an implementation result flat sections). Flagged
      for the implementation review: D3's "a step with one exit names it" read
      against the run being the owner's intervention.
- [x] 8.2 `change-triage`: the triage chooses its exit among its node's exits, on the
      owner's disposition, as a target with `triaged`; `## Next` is prose — the
      target and the owner's words — which nothing routes on; the "Advance, or
      another round" step and its routing paragraph rewritten to the exits; the
      validation, owner, and orchestrator triage files keep their evidence line.
      Step 6 is "Choose the exit", with a table of each triage node's advancing,
      another-round, and return exits, read against `graph._STEPS`, and an
      implementation triage's out-of-order `implement` sections. Step 4 defines
      `triaged` (every record the triage wrote a triage file beside, at least one a
      review). A validation record triaged alone names the earlier round's review
      again in `triaged`, as D3 allows, since a triage names a review; the
      computation brings a failed one to the owner and a direction to its triage is
      refused (no review awaits), so it is run by hand.
- [x] 8.3 Each leaf skill gains a "Running interactively" ending: its last act runs
      `python3 scripts/run_change_step.py record <change> <step> --outcome '<the
      outcome>'`, with `printenv CLAUDE_CODE_SESSION_ID` named as the way to read the
      session's id when the skill needs to show it (D11).
      Design, planning, implementation, triage, validation, closeout, and archive
      cleanup, each after "Running unattended", whose opening now says its outcome
      is the one an interactive run records. Each records `finished`, `returned`, or
      (design) `blocked` — never a question, answered in the session, nor a stop,
      which would wait for a resume only the wrapper makes — and says what the
      computation does with a session closed before recording, read from the code:
      named again for design, planning, triage, closeout, and a directed
      validation; for implementation, and a validation in a round's join or as a
      guard's remedy, the computation reads the task list and records, so only the
      report is lost; for archive cleanup, `done` once the row is `archived`.
      Implementation interactively records the round line as the computation names
      it, since the round's join reads it. Correction to the plan: `change-review`
      records nothing interactively — it changes no file and publishes no record,
      and a review run's outcome names the record it published — so its "Running
      interactively" says the owner pastes the review into a triage, saved as an
      external review. Planning that needs another design review interactively ends
      as a return (`returned`, `{"step": "design"}`) with the owner's confirmation
      directing the design review, `--resolves` the seq `record` printed; a
      waiver is a ledger line, the session planning on. Design's embedded triage of
      a waiting review records `finished` naming `{"step": "design"}`, superseded
      by the design's own outcome; unattended, it asks the owner to run the triage
      first, since only the wrapper records there.
- [x] 8.4 Entry checks (D3, D5): `change-plan`, `change-closeout`, and
      `change-archive-cleanup` ask `python3 scripts/change_next_step.py <change>`
      and proceed when it names their step, in place of reading `## Next` or
      `## Gate`; planning's check of the owner's waiver becomes that question too.
      `change-archive-cleanup` still writes the waiver's ledger line when the owner's
      direction to it is in the log.
      Each check says the computation names the step "whatever the status says",
      the step setting its own status (D5). Archive cleanup's Route check passes a
      validation of `HEAD`, or the owner, carrying archive cleanup as `target` on to
      its Validated check, which takes a direction named in the computation's reason
      (`the owner directed archive-cleanup at seq <n>`) as the waiver, or, asked
      interactively, records the owner's waiver as their direction with `note`.
      Closeout's "Where it stopped" records the outcome an earlier session left
      unrecorded once the archive is committed.
- [x] 8.5 `.agents/change-outcome.schema.json` and `outcome.py`: `next` an object
      only, now that every skill writes one (D3, the cadence's ordering note); tests
      updated.
      The schema's `next` is the object alone; `returned` requires `next` and
      `evidence`; `return_to` is gone from the schema. `outcome.py` needed no
      change. Section 6's handoff: `change_next_step.py`'s `_RETURN_STEP` and its
      reading in `_exit_of` deleted, and `route_of`'s tolerance for a finished run
      naming no exit inside the round's join with it — such a run now names the
      owner wherever it is. `convert.py`'s `_RETURN_STEP` stays: it reads older
      lines. The shared fixtures' outcomes name targets.
- [x] 8.6 Verification: `make check-agent-skills`; `test_change_workflow_outcome.py`,
      unit, a string `next` refused; every `scripts/tests/test_change_*`, unit;
      `make test`; `make check-change CHANGE=workflow-steps-name-next-step`; each
      skill's ending read against the delta's requirements. The skills are
      instructions to an agent: that a session follows them is shown by this
      change's own runs after this section, its validation and review's outcomes
      among them. End-to-end: none, and none is owed.
      `make check-agent-skills`: passed. `test_change_workflow_outcome.py`, unit,
      calling `outcome_problems`: a string `next` refused, on a finished and on a
      returned outcome; a return without `next` refused; `return_to` refused as a
      field the schema does not define; a phase as a step naming no node. In
      `test_change_next_step.py`, unit, calling `compute` over marked lines written
      past the writer: a finished implementation run naming no exit inside the
      round's join names the owner, and a return giving only `return_to` waits for
      the owner with no target, each failing on the code before 8.5; and an
      implementation naming `{"step": "round"}` names the owner with its choice and
      exits, the merge ending's claim. `scripts/tests`: 1788 passed. `make test`:
      passed, before the two fresh-context checks' fixes, which touched the skills,
      the schema's descriptions, and tests under `scripts/`, rerun above. `make
      check-packaging`: passed. `make check-change`: every check passes. Each
      skill's ending was read against the
      delta's requirements by the two fresh-context checks, whose findings the
      notes above answer. End-to-end: none, confirmed; no `Owed by validation:`
      line.

Settled at the round-3 triage, documents only: 68 F3 — the merge run's undeclared
exit (8.1) is kept, the owner having accepted it, and its rationale is now in
`design.md` D4, with the declared alternatives and why they were not taken; 69 O5 —
`change-review`'s interactive exception (8.3) is recorded in D11, and the delta's
MODIFIED scenario "The owner waives archive cleanup's validation under
orchestration" now has archive cleanup find the owner's direction and record the
waiver without asking again, as the ADDED scenario and both skills do (the owner:
"Certainly would prefer it to find my direction and record the waiver").

Handoff from section 8: from this commit the wrapper refuses a string `next`, so
every run's outcome names a target; this session's own outcome names
`{"step": "triage", "kind": "implementation"}`. Open for the implementation review
and closeout: the merge run's undeclared exit (8.1); `change-review`'s interactive
exception (8.3); and the delta's MODIFIED scenario "The owner waives archive
cleanup's validation under orchestration", which still says archive cleanup's own
check "asks the owner", where the ADDED "by a direction" scenario and 8.4 have it
find the direction and record the waiver — the skill follows the latter; the delta
is the design's to reconcile before the archive merges it. Section 9's
`change-orchestrate` rewrite relays a merge run's choice to the owner for their
direction, and drops "its free-text `next` is not a routing command". The 9.3 rule,
`printenv CLAUDE_CODE_SESSION_ID` for every step, was committed on the owner's word
before this section (0d4535448), so this section's commit carries no `.claude/`
edit.

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
      refusals by entry guard (the archive both ways, a triage with nothing
      awaiting it, a validation with no target, `done`), returns confirmed and
      declined, repeat reviews, and the waivers; the design-review waiver's old gate
      (`in design`, a finished redesign) is gone, and archive cleanup finds the
      waiver's direction in the log. "A change not yet converted" relays `convert`'s
      preview and writes with `--confirm`, `--next`, or `--confirm --decline` on the
      owner's word. A round is recorded with the computation's `by` (`plan`,
      `triage`, `owner`); a merge run's undeclared exit is relayed to the owner for
      their direction; the log's writers are listed as the wrapper, `record`,
      `note`, and `convert`. Correction to the plan: the orchestrating session
      does not run `record` for a step the owner closed unrecorded — the delta's
      "MUST NOT … record a step's exit on its behalf" has no exception, and a line
      it wrote would read as the step's own — so it gives the owner the command,
      naming the closed session with `--session`, and starts nothing for the step;
      it acts when the owner says they ran a step interactively, not on the
      computation's reason, which carries the in-progress wording whenever a step is
      named before its first run.
- [x] 9.2 `docs/agents/change-workflow.md`: the triage row of the steps table, the
      paragraph on the order of steps (`## Next` tokens), "Orchestrating a change"
      and "Answering and taking over" for exits, directions, `record`, `convert`, and
      `make change-graph`.
      Also: the orchestration row (directions, conversion); a paragraph on exits as
      targets and `record` after the unattended-run paragraph; the graph's table,
      `make change-graph`, and the drift test beside the order of steps, routing
      cited to the spec's "The next step is computed from the files"; the entry
      checks that ask the computation; "Directing a change" and "Converting a
      change's records" under "Orchestrating a change"; the pre-closeout review's
      override by a direction; the log's writers and format marker; the repeat
      pass's wording; the ledger's waiver by direction.
- [x] 9.3 `.claude/change-steps.toml` — the orchestrator's, on the owner's word,
      before section 8's session starts, committed by that session with section 8:
      every step may run `printenv CLAUDE_CODE_SESSION_ID`, and no broader reading
      of the environment (D11).
      Correction to the plan: committed by the orchestrating session on the owner's
      word as its own commit, 0d4535448, before section 8 started, in `[common]`;
      sections 8 and 9 carry no `.claude/` edit. `test_change_workflow_steps.py`
      loads the table (9.4).
- [x] 9.4 Verification: `make check-agent-skills`; the step table loads
      (`test_change_workflow_steps.py`, unit); `make test`; `make check-change
      CHANGE=workflow-steps-name-next-step`; the guide's commands run as written
      (`make change-graph`, `run_change_step.py record --help`, `convert --help`).
      End-to-end: none, and none is owed.
      `make check-agent-skills`: passed. `test_change_workflow_steps.py`, unit:
      36 passed. `scripts/tests`: 1788 passed. `make test`: passed, before the
      fresh-context check's fixes, which touched only the two Markdown files. `make
      check-change`: every check passes. `make change-graph`: ran, printing the
      table's Mermaid rendering. `run_change_step.py record --help` and `convert
      --help` were denied in this run (no rule allows them); in their place every
      command and flag the guide and the skill give was read against `cli.py`'s
      parser, and each exists as written. The fresh-context check ran once on this
      section; its fixes were not checked again. End-to-end: none, confirmed; no
      `Owed by validation:` line.

Handoff from section 9: the orchestrate skill and the guide describe exits,
directions, `record`, and `convert`; the change's skills now all write targets.
Left for closeout (10.3, 10.9): the guide's account of the graph and of the log is
contributor procedure, and its routing sentence cites the spec; the delta's
MODIFIED scenario "The owner waives archive cleanup's validation under
orchestration" still says archive cleanup "asks the owner", against the ADDED "by
a direction" scenario and both skills (section 8's handoff); and the permanent
`change-workflow` spec and architecture still describe the tokens until the archive
and 10.9 rewrite them.

The round-3 triage (reviews 67-validation, 68-implementation, 69-implementation-owner;
the round `f9c2b1c50`..`b902d8866`) resolved the MODIFIED scenario above (69 O5,
section 8's note). Its fixes are noted in the sections they concern: 68 F1 under
section 5; 68 F2 and 69 O2 under section 6; 69 O1 under section 2. One concerns no
section:

- 69 O3 (the owner: fix it here): a resume that found no conversation reported a
  fresh session's total, 0, and `cost.run_cost` logged the run at minus the
  session's earlier spending, its `session_usd` reset to 0, so `make change-cost`
  understated the change and the session's next run was measured from zero. A
  running total only grows, so a last total below the one logged now records no
  `usd` and no `session_usd`, and `measured_cost` keeps the total it found.
  Unit, `test_change_workflow_cost.py::test_a_resume_that_found_no_conversation_records_no_dollars`,
  through the wrapper with a fake harness: both its assertions fail on the code
  before (−97.0, and 98.5 for the next run).

Evidence for the round-3 fixes: `scripts/tests`, unit (and the process-boundary
tests among them, as before): 1797 passed. `make test`: passed, before the
fresh-context check's follow-ups and again after them, over the committed fixes.
`make check-packaging`:
passed. `make check-change CHANGE=workflow-steps-name-next-step`: every check
passes, comment hygiene and documentation citations included. The fresh-context
check of the diff against `b902d8866` found one defect, fixed (a status set back to
implementation named its round again after the round was recorded, under 69 O2's
note), and optional points, of which these were taken: the triage guard narrowed to
exclude design (under 68 F1's note); no "closed without recording" wording in a
followed status's reason; closeout dropped from `_PHASE_START`, being unreachable;
the guide and the architecture no longer claim the SVG's drawing is checked, only
the source it embeds; the graph tests' module docstring; a long line; and the
orchestrate skill's refusal naming the review's kind. Not taken: narrowing the guard
to failed validations only — a passed one already routes on its own, and the
direction is the owner's. End-to-end: none, and none is owed; no `Owed by
validation:` line.

## 10. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [ ] 10.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments and docstrings this change added under `scripts/`, the `Makefile`,
      `.agents/`, and `.claude/` for provenance — review, triage, finding, or round
      labels, "no longer", "migrated", the conversion described as a migration
      rather than as the command's current job; anything to rewrite returns the
      change to implementation.
- [ ] 10.2 Import placement — confirm: no function-local import added in the files
      this change added or touched under `scripts/`; one that should move returns
      the change to implementation.
- [ ] 10.3 Documentation compliance: re-check D1–D8 and D11 against
      `openspec/README.md`'s placement rules — behaviour in the `change-workflow`
      spec, rationale in its architecture companion, contributor procedure in
      `docs/agents/change-workflow.md`; the cadence and the conversion of this
      change's own records are history and stay here.
- [ ] 10.4 Narrative compression of sections 1–9's notes, moving any rationale not
      yet in `design.md` there first.
- [ ] 10.5 Roadmap currency: no goal in `docs/development/ROADMAP.md` covers
      contributor workflow; record that, or update it.
- [ ] 10.6 Campaign index currency: this change's row `in closeout`, under
      independent active changes, its notes rewritten for closeout; the row of the
      change 10.9 opens added `ready for design`; `make check-change-index`.
- [ ] 10.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=workflow-steps-name-next-step`, and `make check-agent-skills`.
- [ ] 10.8 End-to-end pipeline: record the latest passing validation's pipeline run
      and Helm evidence for the commit closeout reads, or an explicit blocker naming
      its cause and owner. No scenario exercises the workflow tooling; this change's
      own runs from section 8 on, recorded and routed in the new format, are its
      working evidence, cited by their log lines.
- [ ] 10.9 Promotion, completing the design-promotion record in `design.md`:
      - `openspec/specs/change-workflow/spec.md` — written by the archive (10.11):
        "The workflow graph is declared in code", "Interactive step runs record
        their outcome", and "The owner directs a change's next step" added; "Phases
        and owner touchpoints", "Unattended step runs end with a structured
        outcome", and "The next step is computed from the files" modified. By hand:
        "Evidence" gains `scripts/change_workflow/graph.py` (`make change-graph`),
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
- [ ] 10.10 Documentation citations: `make check-doc-citations
      CHANGE=workflow-steps-name-next-step`, resolving every match; then `openspec
      validate workflow-steps-name-next-step --strict`.
- [ ] 10.11 Archival: `openspec archive workflow-steps-name-next-step -y`, merging
      the deltas into `openspec/specs/change-workflow/spec.md`; the row links the
      archive.
