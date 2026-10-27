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

The table is drawn into `openspec/specs/change-workflow/architecture.md` from
section 2 on, and a test holds the drawing to the table: a section that changes the
table updates the drawing in the same commit with `make change-graph`.

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

- [ ] 5.1 `graph.py`: each node's entry guards, unwaivable or waivable, as D1's
      entry-guard table gives them — the archive's absence for design, planning, and
      implementation; the archive for the closeout review, its triage, and archive
      cleanup; a review of its kind awaiting triage for each triage node;
      validation carrying a target that is a node; `done` never directed; and the
      pre-closeout review's validation, waivable. The drawing is redrawn.
- [ ] 5.2 `log.py`, `note_orchestrator` (D6): `next` is the target object; every line
      carrying `next` is `by: owner`; its target is a node of the table; and the
      log's writer refuses it, naming the guard, while an unwaivable entry guard of
      any node it names is not met — the target, and the target nested in a
      direction to validation (D5, 36 F1). No exit guard is checked. The special
      cases for review, plan, archive cleanup, and confirmed returns, and
      `redesigned_after_return`'s gate, are removed: a waiver is a plain direction
      whose `reason` says what it skips. `resolves` and `reads` are unchanged.
- [ ] 5.3 `cli.py`: `note orchestrator` keeps `--next`, `--kind`, and `--sections`,
      and gains `--target` for a direction to validation, which `--kind` and
      `--sections` then qualify (D6); it builds the object.
- [ ] 5.4 `review.py`: the pre-closeout review's validation check accepts the
      owner's direction to that review, logged and not yet used, as its override, as
      `--unvalidated` is (D5, scenario "The owner directs a pre-closeout review over
      a failed validation").
- [ ] 5.5 Verification, unit, with real archive directories in a temporary
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

## 6. Routing on outcomes and directions

Delivers the computation routing on the exit the last step named and the owner's
latest direction, checked against the table, and the detection of a change not yet
converted (D3, D4, D5, D7's detection, D8; requirements "The next step is computed
from the files", "The workflow graph is declared in code", "Interactive step runs
record their outcome", and the phase requirement's exception for directions).
Touches `scripts/change_next_step.py`, `scripts/change_workflow/graph.py`,
`scripts/tests/test_change_next_step.py`, and `scripts/tests/`.

- [ ] 6.1 The route: the last step's exit, or the owner's latest direction until a
      later run of its target is logged; the governing review's latest triage
      outcome is the latest triage line whose `triaged` names it, or the conversion
      line that names it; a triage file no such line names is a triage in progress,
      whatever its first words (D3). A return is confirmed by the owner's decision
      that resolves its run. `next_token()`, `governing()`'s and
      `return_confirmed()`'s file times, and the `## Gate` reading are deleted (D3,
      D7).
- [ ] 6.2 Checking the route against the table (D4): an exit its node does not
      declare, a validation's exit other than the target it was given, and an exit
      whose target's entry guard is not met name the owner, with the choice, the
      node's exits or the target, and the guard; an unmet exit guard names its
      remedy with the exit as `target`, or the owner where no step can satisfy it;
      a direction checks no exit guard. Validation is always named with a `target` —
      the round's triage in a round's join — and the target's guards are checked
      again on its exit. `done` names `{"step": "done", "reason": "archived"}` as
      today. A `round` result for sections an `implement` target names out of the
      plan's order, recorded as a round line as it starts (D2).
- [ ] 6.3 Recovery (D8): the step a last exit or direction names, with no run of it
      logged, is named as in progress, its reason saying that if no session of it is
      open an interactive session ended without recording, to be resumed or recorded
      with `record`; where the files have moved past it — a plan that set
      `ready for implementation` and recorded no outcome — that step is named with a
      `disagreement` naming the missing outcome and `record`, and no step after it.
- [ ] 6.4 Detection (D7): a log holding a line without the format marker, or numbered
      records under `reviews/` and no log, names the owner with
      `python3 scripts/run_change_step.py convert <change>`, and the log is read as
      nothing else. The module docstring's result contract gains `target`.
- [ ] 6.5 `scripts/tests/test_change_next_step.py` rewritten to the new records: its
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
- [ ] 6.6 Verification, unit: `test_change_next_step.py` as rewritten; the graph
      tests with any redrawn diagram; every other `scripts/tests/test_change_*`,
      `test_round_view.py`, and `test_run_change_step.py`; `make test`; `make
      check-change CHANGE=workflow-steps-name-next-step`. End-to-end: none, and none
      is owed.
- [ ] 6.7 The round's join read from `graph.ROUND_JOIN`: the records its members
      supply decide what the join still waits for and which member's step the
      computation names, the clone's and the repeat pass's reading rules kept; unit,
      in `test_change_next_step.py`, a table whose join lacks a member no longer
      waits for that member's record (52 F1: the table declared the join while
      `in_round` read it from record kinds of its own, so a changed join redrew the
      diagram and left routing as it was).
- [ ] 6.8 `graph.py`: a triage's result names the kind of review it triages
      (`Node.result`, D2), with `test_change_next_step.py`'s rewrite (6.5) and the
      graph test `test_a_node_names_its_step_and_a_reviews_kind`: section 3 left
      it, since that test file is unchanged until 6.5 and compares a triage's
      result exactly.

## 7. `convert`: a change's records converted when it takes the new code

Delivers `python3 scripts/run_change_step.py convert <change>` (D7; requirement "The
next step is computed from the files", its conversion clauses). Touches
`scripts/change_workflow/cli.py`, `log.py`, a new `scripts/change_workflow/convert.py`,
and `scripts/tests/`. The command and the older reading it alone holds are
temporary, removed by the change closeout opens (10.9).

- [ ] 7.1 Refusals, writing nothing: a change already converted; a triage in
      progress by the older reading — a triage file with neither `## Next` nor
      `## Gate` that no marked triage outcome names — naming the review and the two
      ways to finish it (36 F4).
- [ ] 7.2 The log's lines rewritten in place, each keeping its seq: a decision's
      string `next` and `kind` become the target object; a `returned` outcome's
      `return_to` gains its target in `next`; an outcome's prose `next` moves into
      its `message`; every line gains the format marker. One conversion line
      appended, `step` `convert`, `outcome` `converted`, naming as `triaged` every
      review with a triage file, and no exit.
- [ ] 7.3 The proposal of the owner's direction to where the change stands, from the
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
- [ ] 7.4 The owner's confirmation: the command shows the proposal, or why there is
      none, and every review the conversion line will name, each with the first line
      of the `## Next` or `## Gate` it read, flagging those no marked triage outcome
      names; it writes only when the owner confirms, which attests the flagged
      triages finished, or gives `--next` in the proposal's place (43 F1). The
      direction is written through `note_orchestrator`'s checks (section 5), `by:
      owner`; declining writes nothing.
- [ ] 7.5 The replacement (D7, 36 F3, 43 F2): the log's exclusive lock taken before
      the log is read and held until the converted log — the rewritten lines, the
      conversion line, and the direction — is written to a temporary file beside the
      log and renamed over it; a change with records and no log gains its log the
      same way.
- [ ] 7.6 Verification, unit, with real files in a temporary directory: the spec's
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

- [ ] 8.1 Each leaf skill's unattended ending names its exit as a target in `next`,
      its prose moving into `message`: design names the design review; planning
      `{"step": "round"}` beside `rounds`, or the pre-closeout review when the plan
      adds nothing to implement; implementation the round's triage of kind
      `implementation`; validation the target the computation gave it, read by
      running the computation, under orchestration and interactively alike (D1);
      closeout the closeout review; archive cleanup `{"step": "done"}`. A return
      names its target as a step. The review skill describes the exit its run
      records (section 3's `review.py`).
- [ ] 8.2 `change-triage`: the triage chooses its exit among its node's exits, on the
      owner's disposition, as a target with `triaged`; `## Next` is prose — the
      target and the owner's words — which nothing routes on; the "Advance, or
      another round" step and its routing paragraph rewritten to the exits; the
      validation, owner, and orchestrator triage files keep their evidence line.
- [ ] 8.3 Each leaf skill gains a "Running interactively" ending: its last act runs
      `python3 scripts/run_change_step.py record <change> <step> --outcome '<the
      outcome>'`, with `printenv CLAUDE_CODE_SESSION_ID` named as the way to read the
      session's id when the skill needs to show it (D11).
- [ ] 8.4 Entry checks (D3, D5): `change-plan`, `change-closeout`, and
      `change-archive-cleanup` ask `python3 scripts/change_next_step.py <change>`
      and proceed when it names their step, in place of reading `## Next` or
      `## Gate`; planning's check of the owner's waiver becomes that question too.
      `change-archive-cleanup` still writes the waiver's ledger line when the owner's
      direction to it is in the log.
- [ ] 8.5 `.agents/change-outcome.schema.json` and `outcome.py`: `next` an object
      only, now that every skill writes one (D3, the cadence's ordering note); tests
      updated.
- [ ] 8.6 Verification: `make check-agent-skills`; `test_change_workflow_outcome.py`,
      unit, a string `next` refused; every `scripts/tests/test_change_*`, unit;
      `make test`; `make check-change CHANGE=workflow-steps-name-next-step`; each
      skill's ending read against the delta's requirements. The skills are
      instructions to an agent: that a session follows them is shown by this
      change's own runs after this section, its validation and review's outcomes
      among them. End-to-end: none, and none is owed.

## 9. The orchestrate skill, the contributor guide, and the step table

Delivers the orchestrating session's part and the contributor's account (D5, D6, D7,
D11; requirement "The owner directs a change's next step"). Touches
`.agents/skills/change-orchestrate/SKILL.md`, `docs/agents/change-workflow.md`, and
`.claude/change-steps.toml`.

- [ ] 9.1 `change-orchestrate`: every direction is the owner's — a confirmed return, a
      repeat review, a waiver, an intervention to any node — written with `--next`,
      `--kind`, `--sections`, and `--target`; the orchestrating session directs
      nothing on its own and never records a step's exit; a result's `target` shown
      in its relay; the `convert` command run on the owner's word when the
      computation names it, between steps, relaying its proposal and the reviews it
      flags for the owner's confirmation; `record` for a step the owner ran
      interactively and closed before recording; "its free-text `next` is not a
      routing command" replaced by the exit the outcome names.
- [ ] 9.2 `docs/agents/change-workflow.md`: the triage row of the steps table, the
      paragraph on the order of steps (`## Next` tokens), "Orchestrating a change"
      and "Answering and taking over" for exits, directions, `record`, `convert`, and
      `make change-graph`.
- [ ] 9.3 `.claude/change-steps.toml` — the orchestrator's, on the owner's word,
      before section 8's session starts, committed by that session with section 8:
      every step may run `printenv CLAUDE_CODE_SESSION_ID`, and no broader reading
      of the environment (D11).
- [ ] 9.4 Verification: `make check-agent-skills`; the step table loads
      (`test_change_workflow_steps.py`, unit); `make test`; `make check-change
      CHANGE=workflow-steps-name-next-step`; the guide's commands run as written
      (`make change-graph`, `run_change_step.py record --help`, `convert --help`).
      End-to-end: none, and none is owed.

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
