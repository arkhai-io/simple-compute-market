Sections follow the design's implementation cadence (D14): round 1 consolidates the
engine behind one command without changing what any step does — the package and its
fixes (1), the command and the make fragment (2), then every caller moved to it and
the old scripts removed (3); round 2 adds the conventions and rewrites the
specifications — the record set's format (4), the index check and the companion's
two names (5), the graph diagram's move (6), the assumptions test with the tables it
reads (7), then the `change-workflow` delta and its trace (8), the
`market-change-workflow` delta (9), and the convention's text (10); closeout (11)
writes the two capabilities' `README.md` and `index.md`, the diagrams, and the other
promotions.

Within round 1, the old scripts keep working until section 3 removes them: sections
1 and 2 leave each old script as an entry point that calls the moved module, so the
change's own steps — the wrapper `make implement UNATTENDED=1` starts, the skills'
`find_change.py` and `run_change_step.py record` — run throughout. Section 3 removes
them; no shim survives the change (D4).

Every engine module is tested in `scripts/tests/` at unit level, with real files in
a temporary directory, and a real Git repository in one where `HEAD`, a clone, or the
repository's root is what is proven; the engine's tests stay in `scripts/tests/`,
which `make test-release-tooling` (part of `make test`) already runs, importing
`change_workflow.<module>`. The workflow tooling is contributor tooling that no
end-to-end scenario in `e2e-tests/` exercises, and none is owed; no section owes
evidence only a push produces.

A task that edits `.claude/change-steps.toml` or `.claude/settings.json` is the
orchestrator's, made on the owner's word before its section's session starts, and
that session commits it with its section; the rest of the section is the
implementer's.

## 1. The engine's modules in one package

Delivers the engine as one package with relative imports, its cycle and private
import gone, its vocabulary from the graph, and its repository found from the
working directory (D4; D5 fixes 1, 2, 4; CW-r3ka's repository clause, CW-9fbu's
single source). Touches `scripts/change_workflow/` and `scripts/tests/`; the old
scripts become entry points calling the moved modules.

- [ ] 1.1 Move each engine script into `scripts/change_workflow/` as a module:
      `change_next_step.py` → `next_step.py`, `change_clone.py` → `clone.py`,
      `round_view.py` → `round_view.py`, `change_history.py` → `history.py`,
      `find_change.py` → `find.py`, `change_cost.py` → `cost_report.py` (beside the
      existing `cost.py`, which measures a run), `check_change_index.py` →
      `index.py`, `check_tasks.py` → `tasks.py`, `check_push_ready.py` → `push.py`,
      `check_agent_skills.py` → `skills.py`, `post_compaction_context.py` →
      `hook.py` (D4), with `git mv` so history follows. Imports within the package
      are relative; no module reaches a sibling script through `sys.path`.
- [ ] 1.2 Break the cycle: `convert` imports what it needs of the computation from
      `next_step` inside the package, and the package imports no script (D4;
      design Context).
- [ ] 1.3 `index.py` exposes the change index's reading — its rows, each row's
      status and dependencies — as public names the computation uses; the
      computation no longer imports `_DEPENDENCY` (D4).
- [ ] 1.4 `common.py`: `STEPS` and `KINDS` come from `graph`'s declaration, and no
      other module keeps a list of steps or kinds (D5, 1; CW-9fbu).
- [ ] 1.5 `common.py`: the repository root is the working directory's Git top level,
      found once per command, refusing outside a repository and naming the
      directory; every module takes it from there rather than from
      `Path(__file__)` (D5, 2; CW-r3ka). In this checkout and in a change's clone
      it is the same directory as before.
- [ ] 1.6 `__init__.py` lists every module, `common` and `subagents` among them,
      each with its concern (D5, 4).
- [ ] 1.7 Each old script path is an entry point of a few lines that calls its
      moved module's `main`, so every caller keeps working until section 3.
- [ ] 1.8 Tests: every `scripts/tests/test_change_*`, `test_find_change.py`,
      `test_round_view.py`, `test_check_change_index.py`, `test_run_change_step.py`,
      and `change_workflow_fixtures.py` import the moved modules; new unit tests
      for the root's resolution (inside a repository's subdirectory, in a clone, and
      outside any repository, refused with the directory named) and that `graph`
      alone declares the steps and kinds.
- [ ] 1.9 Verification: the moved suites pass with no assertion changed but
      imports, which proves behaviour unchanged; the new root and vocabulary tests,
      unit; `make test-release-tooling`; `make test`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none of `e2e-tests/` exercises the
      workflow tooling, and none is owed.

## 2. The command and the make fragment

Delivers `scripts/change-workflow`, every subcommand of D4's mapping with D6's exit
categories, structured outputs, and refusals, `start` holding the Makefile's entry
logic, the step table's `[orchestrator]` row read, and the make fragment (D4; D5, 3;
D6; CW-r3ka, CW-h8vm, CW-5qne, CW-w2ld). Touches a new `scripts/change-workflow`,
`scripts/change_workflow/cli.py`, `steps.py`, a new
`scripts/change_workflow/workflow.mk`, and `scripts/tests/`.

- [ ] 2.1 `scripts/change-workflow`: an executable with no `.py`, which puts
      `scripts/` on the path and runs `change_workflow.cli.main`; `cli.py` parses
      every subcommand of D4's mapping table, including `resume`, `log`, `watch`,
      `denials`, `note`, `convert`, and `check round-view` (D4, "Every operation
      the scripts offer today carries over").
- [ ] 2.2 Exit statuses: 0 success; 1 a refusal or failed check, its reason on
      standard error; 2 a usage error, for every subcommand (D6; CW-5qne).
- [ ] 2.3 `start <step> <change>`: without `--unattended`, opens the interactive
      session the make target opened (`claude "/change-<step> <change>[ arguments]"`);
      with it, runs the wrapper as `run` did, with `--allow`, `--sections`,
      `--session`, `--arguments`, and `--fresh`. Before either, it refuses an
      archived change for design, planning, implementation, and the merge, naming
      the archived directory, and refuses while a round view is open — the make
      targets' `find_change.py --active` and `round-view-closed` (D4; CW-r3ka's
      scenario). `review` and `push` run the same round-view check.
- [ ] 2.4 `steps.py` reads an `[orchestrator]` row naming a model and effort and no
      permission rules, refusing one with rules; `start orchestrate <change>` opens
      the orchestrating session on it (D5, 3; CW-w2ld). The row itself is added to
      the table in 3.1.
- [ ] 2.5 `find --json <change>`: prints `name`, `directory`, `archived`, and
      `records` (the records directory, or `null` when this checkout holds none),
      and refuses an unknown change with exit 1, naming it; `format` joins it in
      section 4 (D6; CW-r3ka).
- [ ] 2.6 `clone where <change>`: D6's four cases in order — an unknown change exits
      1 naming it, before any clone lookup; a usable clone exits 0 printing its
      path; no clone directory exits 0 printing nothing; an unusable clone directory
      (not a clone of the workspace, its branch not checked out, its bootstrap not
      succeeded) exits 1 with the reason (D6; CW-r3ka).
- [ ] 2.7 `scripts/change_workflow/workflow.mk`: the workflow's convenience targets
      — `design`, `plan`, `implement`, `review`, `triage`, `validate`, `merge`,
      `closeout`, `archive-cleanup`, `orchestrate`, `change-next`, `change-clone`,
      `change-clone-remove`, `round-view`, `round-done`, `round-view-closed`,
      `change-watch`, `change-cost`, `change-history`, `check-change-index`,
      `check-tasks`, `check-agent-skills`, `check-push-ready`, `push-branch`, and
      `change-graph` — each calling the command with today's variables (`CHANGE`,
      `UNATTENDED`, `ALLOW`, `KIND`, `SECTION`, `SECTIONS`, `SESSION_ID`,
      `ARGUMENTS`, `FRESH`, `FROM`, `REVIEW_BASE`, `REVIEW_MODEL`, `REVIEW_EFFORT`,
      `UNVALIDATED`, `BASE`, `BRANCH`); defaults by `?=`, among them
      `CHANGE_WORKFLOW ?= scripts/change-workflow`, `CHANGE_WORKFLOW_MERGE_FROM ?=
      dev`, and `CHANGE_WORKFLOW_REVIEW_BASE ?= dev`. A comment at its head says
      its targets and variables carry no compatibility promise (D4; D6; CW-h8vm).
      The root `Makefile` includes it in section 3.
- [ ] 2.8 Tests, unit: each subcommand reaches its module with today's arguments;
      the exit categories, including a usage error; `start`'s refusals of an
      archived change and of an open round view, and the session command it builds
      interactively and unattended; `start orchestrate` on the row's model and
      effort, and a row with rules refused; `find --json`'s fields, `records` as
      `null`, and an unknown change; `clone where`'s four cases, against real
      clones in a temporary directory; the fragment's targets, with `make -n` from a
      temporary `Makefile` that sets `CHANGE_WORKFLOW_MERGE_FROM` and includes it,
      printing the command each target runs.
- [ ] 2.9 Verification: the new command and fragment tests, unit; the suites of
      section 1; `make test-release-tooling`; `make test`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates; by hand, `scripts/change-workflow next
      specify-change-workflow-and-engine` prints what `python3
      scripts/change_next_step.py specify-change-workflow-and-engine` prints.
      End-to-end: none, and none is owed.

## 3. Every caller moved to the command, and the old scripts removed

Delivers the engine reached only through the command: the step table, the hook, the
root `Makefile`, the skills, the four importers, the guide, and the completion call
it, and the old scripts are gone (D4; D6, "A repository calls the engine only as the
command"; CW-r3ka, CW-w2ld). Touches `.claude/change-steps.toml`,
`.claude/settings.json` (both the orchestrator's), the root `Makefile`,
`.agents/skills/change-*/SKILL.md`, `scripts/check_change.py`,
`scripts/check_doc_citations.py`, `scripts/validate_slice.py`,
`scripts/validate_parallel.py`, `scripts/completions/make-change.bash`,
`docs/agents/change-workflow.md`, `AGENTS.md`'s "Agent skills", `openspec/README.md`'s
citations of the scripts, and `scripts/tests/`.

- [ ] 3.1 The orchestrator's, before the session starts, on the owner's word:
      `.claude/change-steps.toml` gains, beside each rule naming an old script or a
      moved make target, the rule naming the command (`Bash(scripts/change-workflow
      find*)`, `Bash(scripts/change-workflow next*)`, `Bash(scripts/change-workflow
      log*)`, `Bash(scripts/change-workflow record*)`, `Bash(scripts/change-workflow
      check round-view)`, `Bash(scripts/change-workflow push)`, and the rest each
      step's rules name), keeping the old rules for this section's own run; and an
      `[orchestrator]` row with `claude-opus-5-5` at `medium` effort and no rules
      (D5, 3; CW-w2ld). `.claude/settings.json`'s post-compaction hook runs
      `"$CLAUDE_PROJECT_DIR/scripts/change-workflow" hook post-compaction`. The
      session commits both with the section.
- [ ] 3.2 The root `Makefile`: sets `CHANGE_WORKFLOW_MERGE_FROM := dev` and
      `CHANGE_WORKFLOW_REVIEW_BASE := dev`, includes
      `scripts/change_workflow/workflow.mk`, and drops the targets the fragment now
      holds; its own targets that ran `round-view-closed` keep it, now the
      fragment's (D4; CW-h8vm). `make help` lists the fragment's targets.
- [ ] 3.3 Every skill under `.agents/skills/change-*` names the command where it
      named an old script or `run_change_step.py`: `scripts/change-workflow find
      --records`, `next`, `log`, `record`, `note`, `push` (for `make push-branch`),
      `check round-view` (for `make round-view-closed`), `check index`, and the
      rest; the orchestrate skill starts steps through the make targets as before
      (D4).
- [ ] 3.4 The four importers call the command and import nothing of the engine:
      `check_change.py`, `check_doc_citations.py`, and `validate_slice.py` read
      `find --json`'s `directory`, `archived`, and `records`; `validate_parallel.py`
      reads `clone where`, telling its four cases apart by exit status and output
      (D6; CW-r3ka's first scenario).
- [ ] 3.5 `scripts/completions/make-change.bash` completes change names on the
      fragment's targets as it did on the `Makefile`'s.
- [ ] 3.6 `docs/agents/change-workflow.md`, `AGENTS.md`'s "Agent skills", and
      `openspec/README.md`'s closeout part 11 name the command where they named
      the old scripts.
- [ ] 3.7 Remove the old scripts: `scripts/run_change_step.py`,
      `change_next_step.py`, `change_clone.py`, `round_view.py`,
      `change_history.py`, `find_change.py`, `change_cost.py`,
      `check_change_index.py`, `check_tasks.py`, `check_push_ready.py`,
      `check_agent_skills.py`, and `post_compaction_context.py` (D4).
- [ ] 3.8 Tests: `test_make_change_completion.py`,
      `test_change_build_and_helm_targets.py`, `test_run_change_step.py`,
      `test_validate_parallel.py`, `test_check_change.py`, and any test naming an
      old script or a moved target, follow the command and the fragment; a new unit
      test fails when a file under `scripts/` other than the engine's own modules
      and tests imports `change_workflow` (D6, "A repository calls the engine only
      as the command").
- [ ] 3.9 Verification: the section's tests, unit; `make test-release-tooling`;
      `make test`; `make check-agent-skills`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates; by hand, `make change-next
      CHANGE=specify-change-workflow-and-engine`, `scripts/change-workflow find
      --json specify-change-workflow-and-engine`, `make check-change-index`, `make
      -n design CHANGE=specify-change-workflow-and-engine UNATTENDED=1`, and `make
      -n orchestrate CHANGE=specify-change-workflow-and-engine`, each printing the
      command it runs; `grep -rn` over `.agents`, `.claude`, `docs`, `Makefile`,
      `AGENTS.md`, and `openspec/README.md` finds no old script's name. The
      round's validation runs the rewritten step table. End-to-end: none, and none
      is owed.

## 4. The record set's format, read and marked

Delivers one format version for a change's record set, carried on the outputs and
the schema, read as older, current, or newer, and marked by `start` before any step
runs; and an unknown node reported by name (D8; D7; CW-x7jd, CW-k6qa, CW-9fbu).
Touches `.claude/change-steps.toml` (the orchestrator's),
`scripts/change_workflow/log.py`, `next_step.py`, `find.py`, `convert.py`, `cli.py`,
`outcome.py`, `.agents/change-outcome.schema.json`, and `scripts/tests/`.

- [ ] 4.1 The orchestrator's, before the session starts, on the owner's word:
      `.claude/change-steps.toml` drops the rules naming the removed scripts and
      make targets section 3 moved, keeping the command's.
- [ ] 4.2 `next`'s data output and `find --json` carry `format`; the outcome
      schema's `$id` states the format it belongs to (D8; CW-x7jd).
- [ ] 4.3 Reading a log: a line with no `format`, or a lower one, is older, named
      to the owner with `convert` as today; a higher one is refused, naming it, by
      the computation and by `convert`, which rewrites nothing. With no log, or an
      empty one, numbered records are older and a ledger alone, or nothing, is read
      in the reader's format (D8; CW-x7jd's scenarios; CW-k6qa's second).
- [ ] 4.4 `start` ensures the change's log exists and appends a line carrying the
      format before any step it starts runs, interactive or unattended; the
      computation routes on no such line (D8; CW-k6qa).
- [ ] 4.5 The computation, the outcome check, and the log's writer report a node or
      kind the graph does not declare by name and route on no line after it (D7;
      CW-9fbu's first scenario).
- [ ] 4.6 Tests, unit: the format on `next` and `find --json` and in the schema's
      `$id`; an older, a current, and a newer log, read and converted; a log with
      only a ledger beside it, and none; `start`'s opening line, interactive and
      unattended, and the computation ignoring it; an unknown node in an exit and a
      kind added to `graph` accepted with no other list edited.
- [ ] 4.7 Verification: the section's tests, unit; `make test-release-tooling`;
      `make test`; `make check-change CHANGE=specify-change-workflow-and-engine`,
      failing only on the citations of files a later section creates. End-to-end:
      none, and none is owed.

## 5. The index check, and the companion's two names

Delivers the check that holds an indexed capability's `spec.md` to its `index.md`,
and the skills and configuration that know a capability's companion is `README.md`
where `index.md` exists (D15; planning-governance's "Indexed capability
documentation" and modified "Permanent capability architecture companions").
Touches a new `scripts/check_spec_index.py`, `scripts/check_change.py`,
`openspec/config.yaml`, `.agents/skills/change-closeout/SKILL.md`,
`change-design/SKILL.md`, `change-review/SKILL.md`, and `scripts/tests/`.

- [ ] 5.1 `scripts/check_spec_index.py`: for each capability under
      `openspec/specs/` with an `index.md`, fails on a requirement whose name begins
      with no id (the capability's prefix and four characters from `[a-z0-9]`), two
      requirements sharing an id, an id `index.md` omits or lists twice, a listed id
      in neither `spec.md` nor the named change's own deltas, a retired id in use,
      and a link in `index.md` that does not resolve; it names each. A capability
      with no `index.md` is not checked (D15).
- [ ] 5.2 `scripts/check_change.py` runs it among a change's closing checks, with
      the change named so its deltas count (D15, "The deltas clause").
- [ ] 5.3 `openspec/config.yaml`'s rules, and the closeout, design, and review
      skills, name the companion as `README.md` where `index.md` exists and
      `architecture.md` elsewhere; the closeout skill's promotion part writes the
      `index.md` entries, with links and summary lines, for the ids a change adds,
      and moves a removed requirement's id to the retired ids with where its rule
      went (D15).
- [ ] 5.4 Tests, unit, `scripts/tests/test_check_spec_index.py`: each failure case
      named; an id listed in `index.md` and present only in a change's ADDED delta
      accepted; a capability without `index.md` ignored.
- [ ] 5.5 Verification: the section's tests, unit; `make test-release-tooling`;
      `make check-agent-skills`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.

## 6. The graph diagram moved into its capability

Delivers the graph diagram in `openspec/specs/change-workflow/diagrams/`, still held
to the graph table (D12). Touches
`docs/development/diagrams/change-workflow-graph.drawio` and `.svg`,
`scripts/change_workflow/diagram.py`, `graph.py`,
`openspec/specs/change-workflow/architecture.md`, and
`scripts/tests/test_change_workflow_graph.py`.

- [ ] 6.1 `git mv` the diagram's `.drawio` and `.svg` to
      `openspec/specs/change-workflow/diagrams/`; `diagram.py`, `graph.py`'s
      docstring, the graph test, and the companion's embed and source link name the
      new path (D12).
- [ ] 6.2 Verification: `make change-graph` says the diagram draws the table; the
      graph tests, unit; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.

## 7. The assumptions test, and the two tables it reads

Delivers the inventory written two-sided — the roles in `change-workflow`'s
`README.md`, this repository's provision of each in `market-change-workflow`'s — and
the test that holds the targets and paths the skills, the step table, and the
fragment name to it (D13; D15's rename; CW-m4ps, MCW-5tgp). Touches
`openspec/specs/change-workflow/architecture.md` → `README.md`, a new
`openspec/specs/market-change-workflow/README.md`, every citation of the companion's
old path, and a new `scripts/tests/test_change_workflow_assumptions.py`.

- [ ] 7.1 `git mv openspec/specs/change-workflow/architecture.md
      openspec/specs/change-workflow/README.md` (D15), and move every citation of
      the old path: `openspec/specs/README.md`, `docs/agents/change-workflow.md`,
      `openspec/changes/README.md`, the spec's own Evidence, `diagram.py`,
      `graph.py`, the graph test, and any other `make check-doc-citations` finds.
      The content is rewritten at closeout (11.9); this section adds only the
      section of 7.2.
- [ ] 7.2 `change-workflow`'s `README.md` gains "What an adopting repository
      provides": a table of each role (a command validating a commit locally, the
      packaging check before closeout, the change index at its path, the guidance
      documents every step reads, the protected branches, the `origin` remote, the
      clone's bootstrap, and every other role the targets and paths of 7.4 fill),
      the skills that use it, and the change expected to replace it; then the
      engine's own assumptions — the paths its modules hold, the default merge
      branch, the `workspace` remote, `CLAUDE_CODE_SESSION_ID`, and the tools it
      invokes (`git`, `claude`, `codex`, `gh`) — marked as maintained by review
      (D13; CW-m4ps).
- [ ] 7.3 A new `openspec/specs/market-change-workflow/README.md` with "How this
      repository provides the workflow's roles": each role of 7.2 and the target,
      path, branch, or document that fills it here (`make validate-local`, `make
      check-packaging`, `openspec/changes/README.md`, `dev` and `main`, `make init`,
      …), the engine's own assumptions marked as maintained by review; the rest of
      the document is written at closeout (D13; MCW-5tgp).
- [ ] 7.4 `scripts/tests/test_change_workflow_assumptions.py`, unit: collects every
      `make <target>` and repository path the skills under `.agents/skills/change-*`,
      `.claude/change-steps.toml`, and `scripts/change_workflow/workflow.mk` name,
      and fails, naming each and where it is named, on one the provision table does
      not list; and fails on a role either table lacks. It reads the two tables'
      Markdown and claims nothing of the engine's own assumptions (D13; CW-m4ps's
      scenarios).
- [ ] 7.5 Verification: the assumptions test, unit, passing, and failing on a
      temporary skill naming an unlisted target; `make test-release-tooling`; `make
      test`; `make check-doc-citations CHANGE=specify-change-workflow-and-engine`
      reporting no citation of the old companion path; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.

## 8. The `change-workflow` specification rewritten, with its trace

Delivers the `change-workflow` delta that rewrites the specification against its
outline: every existing requirement REMOVED with its migration, every new one ADDED
with its id, each under 500 characters, and the trace that maps every old MUST
clause and scenario (D10; D11's isolation; D3's seam; the deltas of D4–D9 and D13
already in it). Touches
`openspec/changes/specify-change-workflow-and-engine/specs/change-workflow/spec.md`
and a new `openspec/changes/specify-change-workflow-and-engine/trace.md`.

- [ ] 8.1 ADDED requirements written from D10's outline, each `### Requirement:
      CW-xxxx <name>` with a new random id, one behaviour in under 500 characters,
      its cases as scenarios; the general rules of every "general" and "split" row
      of D10's destination table, with the seam each split row keeps; and the
      commands the requirements name are the command's, not the old scripts'
      (D10; D3; D4).
- [ ] 8.2 The conversion's rules are requirements of their own, and so are the
      round view's mechanics, so that `remove-workflow-log-conversion` and
      `workflow-round-review-without-merges` each meet known ids (D11).
- [ ] 8.3 Every one of the 24 existing requirements REMOVED, its `**Reason**` and
      its `**Migration**` naming the ids that hold its rules, in `change-workflow` or
      `market-change-workflow` (D10).
- [ ] 8.4 `trace.md`: one row per MUST clause and per scenario of the existing
      specification, naming the id that holds it, or "dropped" with the reason;
      every placement agreeing with D10's destination table. A clause the trace
      cannot place as the table does stops the section and returns the change to
      design (D10).
- [ ] 8.5 Verification: `openspec validate specify-change-workflow-and-engine
      --strict` under the pinned 1.14.0, and every ADDED requirement's text under
      500 characters, read from the delta; `trace.md` names every requirement and
      scenario heading of `openspec/specs/change-workflow/spec.md`, checked by
      listing those headings with `grep` against the trace's rows; `make
      check-change CHANGE=specify-change-workflow-and-engine`, failing only on the
      citations of files the change creates. End-to-end: none, and none is owed.

## 9. The `market-change-workflow` specification

Delivers this repository's own workflow requirements as their own capability: the
clause groups D10's table moves, the Helm namespace requirement whole, and this
repository's values, beside MCW-5tgp (D3; D10's destination table). Touches
`openspec/changes/specify-change-workflow-and-engine/specs/market-change-workflow/spec.md`
and `trace.md`.

- [ ] 9.1 ADDED requirements, each `### Requirement: MCW-xxxx <name>` with a new
      random id and under 500 characters: this repository's validation parts (the
      clause groups of D10's "Validation observes a committed slice" row), each Helm
      validation isolated in its change's namespace (whole), the protected branches,
      the merge's default branch, the forbidden models, and the clone's bootstrap
      (D3; D10).
- [ ] 9.2 `trace.md`'s rows for the clauses that move here name these ids (D10).
- [ ] 9.3 Verification: `openspec validate specify-change-workflow-and-engine
      --strict`; every requirement under 500 characters; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files the change creates. End-to-end: none, and none is owed.

## 10. The indexed organization's text

Delivers the convention as written guidance: how an indexed capability's documents
are organized, and what closeout writes into `index.md` (D15; D14's round 2). Touches
`openspec/README.md` and `openspec/specs/README.md`.

- [ ] 10.1 `openspec/README.md#capability-documentation-pattern`: a capability may
      be organized by an index — `README.md`, `index.md`, `spec.md`, `diagrams/` as
      D15 lays them out — with the id rule, retired ids, citing by id, and the
      check (D15).
- [ ] 10.2 `openspec/README.md#plan-closeout-requirements`, part 9: promotion writes
      the `index.md` entries for the ids a change adds and retires the ids it
      removes (D15).
- [ ] 10.3 `openspec/specs/README.md`'s description of a capability's files: the
      companion is `README.md` where `index.md` exists (D15).
- [ ] 10.4 Verification: `make check-doc-citations
      CHANGE=specify-change-workflow-and-engine`, failing only on files the change
      creates; `make check-change CHANGE=specify-change-workflow-and-engine`.
      End-to-end: none, and none is owed.

## 11. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [ ] 11.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments and docstrings this change added under `scripts/`, in
      `scripts/change_workflow/workflow.mk`, the root `Makefile`, `.agents/`, and
      `.claude/` for provenance — review, triage, finding, round, or section labels,
      "moved from", "formerly", the old scripts named as history; anything to
      rewrite returns the change to implementation.
- [ ] 11.2 Import placement — confirm: no function-local import added in the files
      this change added or touched under `scripts/`, the engine's moves included;
      one that should move returns the change to implementation.
- [ ] 11.3 Documentation compliance: re-check D1–D15 against
      `openspec/README.md#documentation-placement` — behaviour in the two
      capabilities' and planning-governance's specs, rationale and limits in the two
      `README.md`, organization in the two `index.md`, contributor procedure in
      `docs/agents/change-workflow.md`, documentation conventions in `AGENTS.md`
      and `openspec/README.md`; the cadence, the trace, and the destination table
      are change history and stay here.
- [ ] 11.4 Narrative compression of sections 1–10's notes, moving any rationale not
      yet in `design.md` there first.
- [ ] 11.5 Roadmap currency: no goal in `docs/development/ROADMAP.md` covers the
      change workflow — the lesser goal it serves is in `openspec/changes/README.md`
      (11.6); record that disposition in the promotion record, with no roadmap edit.
- [ ] 11.6 Campaign index currency: this change's row `in closeout`, its notes
      rewritten; the lesser goal "Make the change workflow a tool any repository can
      adopt"'s current state names the command, the package, the make fragment, and
      the two capabilities in place of the old scripts and the architecture
      companion, and its gap row "The engine is documented as this repository's
      contract, not as a tool in its own right" is removed, the gap closed; no
      other row's `Depends on` or status changes; `make check-change-index`.
- [ ] 11.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=specify-change-workflow-and-engine`, and `make check-agent-skills`.
- [ ] 11.8 End-to-end pipeline: record the latest passing validation's pipeline run
      and Helm evidence for the commit closeout reads, or an explicit blocker naming
      its cause and owner. No scenario exercises the workflow tooling, so `make
      test` is its evidence; the change's own steps run through the command from
      round 2 on, cited by their log lines, are its working evidence.
- [ ] 11.9 Promotion, completing the design-promotion record in `design.md`:
      - `openspec/specs/change-workflow/spec.md` — written by the archive (11.11):
        the rewritten requirements. By hand, before the archive: "Purpose" drops
        the Helm validation namespace and describes the workflow and its engine;
        "Evidence" names the command, the package's modules, the fragment, and the
        tests, its validation, namespace, capacity, and parallel-Helm entries moving
        to `market-change-workflow`'s.
      - `openspec/specs/change-workflow/README.md` — rewritten from the companion in
        `index.md`'s parts, in order: the process; implementation and validation;
        reviews and triage; the engine (its parts, a step run's life, where a
        change's state lives, the command and its tiers); the public surface (the
        formats and their version, compatibility, what an adopting repository
        provides, from 7.2); and "Current limits", which gains a ledger with no log
        (D8), `scripts/` outside the architecture checks (D5, 5), hardcoded
        repository paths (D5, 6), the step table's harness syntax (D5, 7), the graph
        closed to adopters (D7), and the graph diagram compared rather than
        generated (D12). It embeds the four diagrams.
      - `openspec/specs/change-workflow/diagrams/` — the engine's parts, a step
        run's life with the relay as a lane, and where a change's state lives, each
        a `.drawio` source and its `.svg` export, beside the graph moved in
        section 6 (D12).
      - `openspec/specs/change-workflow/index.md` — the outline's parts and groups,
        every CW id with its link and summary line, and the retired ids: none yet.
      - `openspec/specs/market-change-workflow/README.md` — completed around 7.3's
        table: why validation has its parts, the namespace and capacity rationale
        from the companion's "Validation observes a committed slice", and "This
        repository is the workflow's first adopter" (the owner's principle).
      - `openspec/specs/market-change-workflow/index.md` — every MCW id.
      - `openspec/specs/market-change-workflow/spec.md` and
        `openspec/specs/planning-governance/spec.md` — written by the archive.
      - `openspec/specs/README.md` — rows for `market-change-workflow` (spec,
        `README.md`, `index.md`) and `change-workflow`'s `README.md` and `index.md`.
      - `openspec/README.md#capability-documentation-pattern` — the principles that
        documentation follows the specification and that a component's `README.md`
        is its most human-readable document; `#change-documentation-requirements` —
        a workflow change's proposal names each public interface it changes and
        whether the change is compatible (D9).
      - `AGENTS.md` — "Documentation ownership": the companion is `README.md` where
        `index.md` exists; a new "Diagrams" section after "Python comments and
        docstrings": a diagram is held to code only when generated deterministically
        from a well-structured source, and is otherwise maintained like any other
        documentation.
      - `docs/agents/change-workflow.md` — the command, the fragment, and the
        tiers, where it describes the engine's commands.
- [ ] 11.10 Documentation citations: `make check-doc-citations
      CHANGE=specify-change-workflow-and-engine` after promotion, resolving every
      match; then `openspec validate specify-change-workflow-and-engine --strict`.
- [ ] 11.11 Archival: `openspec archive specify-change-workflow-and-engine -y`,
      merging the deltas into `change-workflow`, the new `market-change-workflow`,
      and `planning-governance`; where the archive writes a placeholder Purpose for
      `market-change-workflow`, replace it with its Purpose in the closeout commit;
      `make check-change CHANGE=specify-change-workflow-and-engine`, the index check
      among it, passes against the archived specifications; the row links the
      archive.
