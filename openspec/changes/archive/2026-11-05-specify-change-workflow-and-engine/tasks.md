Sections follow the order of the design's implementation cadence (D14): first the
engine is consolidated behind one command without changing what any step does — the
package and its fixes (1), the command and the make fragment (2), then every caller
moved to it and the old scripts removed (3); then the conventions are added and the
specifications rewritten — the record set's format (4), the index check and the
companion's two names (5), the graph diagram's move (6), the assumptions test with
the tables it reads (7), then the `change-workflow` delta and its trace (8), the
`market-change-workflow` delta (9), and the convention's text (10); closeout (11)
writes the two capabilities' `README.md` and `index.md`, the diagrams, and the other
promotions.

The old scripts keep working until section 3 removes them: sections
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

- [x] 1.1 Move each engine script into `scripts/change_workflow/` as a module:
      `change_next_step.py` → `next_step.py`, `change_clone.py` → `clone.py`,
      `round_view.py` → `round_view.py`, `change_history.py` → `history.py`,
      `find_change.py` → `find.py`, `change_cost.py` → `cost_report.py` (beside the
      existing `cost.py`, which measures a run), `check_change_index.py` →
      `index.py`, `check_tasks.py` → `tasks.py`, `check_push_ready.py` → `push.py`,
      `check_agent_skills.py` → `skills.py`, `post_compaction_context.py` →
      `hook.py` (D4), with `git mv` so history follows. Imports within the package
      are relative; no module reaches a sibling script through `sys.path`.
      Done; every package module, the existing ones included, now imports its
      siblings relatively, and the moved modules lost their shebangs.
- [x] 1.2 Break the cycle: `convert` imports what it needs of the computation from
      `next_step` inside the package, and the package imports no script (D4;
      design Context). Done: `convert`, `log`, `review`, and `cli` import `.find`,
      `.next_step`, and `.clone`; `push` runs the repository's pre-push check as a
      command rather than importing it (71 F1; D4, CW-p7kq), and a test loads
      `change_workflow.cli` with only the package on the path.
- [x] 1.3 `index.py` exposes the change index's reading — its rows, each row's
      status and dependencies — as public names the computation uses; the
      computation no longer imports `_DEPENDENCY` (D4). Done: `Row.dependencies`
      yields a `Dependency(entry, name, phase)` per entry, read by the check and the
      computation alike.
- [x] 1.4 `common.py`: `STEPS` and `KINDS` come from `graph`'s declaration, and no
      other module keeps a list of steps or kinds (D5, 1; CW-9fbu). Done: declared
      in `graph` itself, in table order, with the computation's step-to-phase map
      derived from the table too (D5, "Settled in implementation").
- [x] 1.5 `common.py`: the repository root is the working directory's Git top level,
      found once per command, refusing outside a repository and naming the
      directory; every module takes it from there rather than from
      `Path(__file__)` (D5, 2; CW-r3ka). In this checkout and in a change's clone
      it is the same directory as before. Done: `repository_root()` raises
      `NotInRepository`, each `main` refusing with exit 1 and the directory named;
      the step table, schema, and diagram source are relative to it, so
      `scripts/tests` passes only inside a checkout (D5, "Settled in
      implementation"). Correction: the root matches the old one only from inside
      the checkout; the callers that ran a clone's scripts from elsewhere run the
      command in the clone (D4, "Settled in implementation").
- [x] 1.6 `__init__.py` lists every module, `common` and `subagents` among them,
      each with its concern (D5, 4).
- [x] 1.7 Each old script path is an entry point of a few lines that calls its
      moved module's `main`, so every caller keeps working until section 3.
      Done, each changing to its own checkout first; removed in 3.7.
      `check_comment_hygiene.py`'s exempt line follows `TASKS_FILE` to
      `scripts/change_workflow/next_step.py`.
- [x] 1.8 Tests: every `scripts/tests/test_change_*`, `test_find_change.py`,
      `test_round_view.py`, `test_check_change_index.py`, `test_run_change_step.py`,
      and `change_workflow_fixtures.py` import the moved modules; new unit tests
      for the root's resolution (inside a repository's subdirectory, in a clone, and
      outside any repository, refused with the directory named) and that `graph`
      alone declares the steps and kinds. Done, the old scripts' other tests
      included. New: `test_change_workflow_common.py` — the root in a subdirectory,
      a clone, and this checkout, refused outside any repository with every `main`
      writing nothing; the vocabulary as the table declares it, no module but
      `graph` assigning `STEPS` or `KINDS` (by name only), and the step-to-phase
      map. The entry points' process test was removed with them in section 3.
- [x] 1.9 Verification: the moved suites pass with no assertion changed but
      imports, which proves behaviour unchanged; the new root and vocabulary tests,
      unit; `make test-release-tooling`; `make test`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none of `e2e-tests/` exercises the
      workflow tooling, and none is owed.
      Evidence: the scripts suite, 1859 passed; `test_change_workflow_common.py`
      (unit, real repositories), 21 passed; the entry points' process test, 12
      passed; `make test` passed; `make check-change` failed only on citations of
      files later sections create. The moved suites pass an explicit `root`, so
      they prove the modules unchanged given a repository; the new tests prove the
      root. Assertions changed beyond imports: the hygiene test's exempt path, the
      graph test's step-set check (now true by construction, pinned by the
      vocabulary test), and the step test's table path.

## 2. The command and the make fragment

Delivers `scripts/change-workflow`, every subcommand of D4's mapping with D6's exit
categories, structured outputs, and refusals, `start` holding the Makefile's entry
logic, the step table's `[orchestrator]` row read, and the make fragment (D4; D5, 3;
D6; CW-r3ka, CW-h8vm, CW-5qne, CW-w2ld). Touches a new `scripts/change-workflow`,
`scripts/change_workflow/cli.py`, `steps.py`, a new
`scripts/change_workflow/workflow.mk`, and `scripts/tests/`.

- [x] 2.1 `scripts/change-workflow`: an executable with no `.py`, which puts
      `scripts/` on the path and runs `change_workflow.cli.main`; `cli.py` parses
      every subcommand of D4's mapping table, including `resume`, `log`, `watch`,
      `denials`, `note`, `convert`, and `check round-view` (D4, "Every operation
      the scripts offer today carries over"). Done: `cli` resolves the repository
      once; delegating subcommands hand the module its own argument list
      (`cli.delegated`, a seam the tests read), so output and status are the
      module's. `clone where` shares `clone`'s parser (D4, "Settled in
      implementation"). The command is mode 100755 in Git.
- [x] 2.2 Exit statuses: 0 success; 1 a refusal or failed check, its reason on
      standard error; 2 a usage error, for every subcommand (D6; CW-5qne).
      Done, argparse's errors and the malformed forms it cannot judge alone both
      returning 2; the statuses that moved are D6's "Settled in implementation".
- [x] 2.3 `start <step> <change>`: without `--unattended`, opens the interactive
      session the make target opened (`claude "/change-<step> <change>[ arguments]"`);
      with it, runs the wrapper as `run` did, with `--allow`, `--sections`,
      `--session`, `--arguments`, and `--fresh`. Before either, it refuses an
      archived change for design, planning, implementation, and the merge, naming
      the archived directory, and refuses while a round view is open — the make
      targets' `find_change.py --active` and `round-view-closed` (D4; CW-r3ka's
      scenario). `review` and `push` run the same round-view check.
      Done; which steps refuse what is read from the graph's entry guards, and the
      differences from the targets are recorded in D4's "Settled in
      implementation".
- [x] 2.4 `steps.py` reads an `[orchestrator]` row naming a model and effort and no
      permission rules, refusing one with rules; `start orchestrate <change>` opens
      the orchestrating session on it (D5, 3; CW-w2ld). The row itself is added to
      the table in 3.1. Done: the row takes `model` and optional `effort`, refused
      with rules, any other key, or a forbidden model; `start orchestrate` takes
      the change alone and refuses while the table has no row.
- [x] 2.5 `find --json <change>`: prints `name`, `directory`, `archived`, and
      `records` (the records directory, or `null` when this checkout holds none),
      and refuses an unknown change with exit 1, naming it; `format` joins it in
      section 4 (D6; CW-r3ka). Done; `--json` refuses `--records` (exit 2), whose
      workspace fallback the field does not follow.
- [x] 2.6 `clone where <change>`: D6's four cases in order — an unknown change exits
      1 naming it, before any clone lookup; a usable clone exits 0 printing its
      path; no clone directory exits 0 printing nothing; an unusable clone directory
      (not a clone of the workspace, its branch not checked out, its bootstrap not
      succeeded) exits 1 with the reason (D6; CW-r3ka). Done; run in a clone it
      looks beside the workspace its `workspace` remote names.
- [x] 2.7 `scripts/change_workflow/workflow.mk`: the workflow's convenience targets
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
      Done as the `Makefile`'s targets read, except: the step targets, `review`,
      and `push-branch` drop the checks `start`, `review`, and `push` now run;
      `validate` passes `ARGUMENTS` in place of this repository's
      `HELM_ALL_SCENARIOS`, mapped by the root `Makefile` (3.2). `change-graph`
      runs `check graph`, the owner's choice of tier internal (D4's mapping, D6's
      table).
- [x] 2.8 Tests, unit: each subcommand reaches its module with today's arguments;
      the exit categories, including a usage error; `start`'s refusals of an
      archived change and of an open round view, and the session command it builds
      interactively and unattended; `start orchestrate` on the row's model and
      effort, and a row with rules refused; `find --json`'s fields, `records` as
      `null`, and an unknown change; `clone where`'s four cases, against real
      clones in a temporary directory; the fragment's targets, with `make -n` from a
      temporary `Makefile` that sets `CHANGE_WORKFLOW_MERGE_FROM` and includes it,
      printing the command each target runs.
      Done in `scripts/tests/test_change_workflow_cli.py`, as listed, with
      `start`'s interactive prompts through an injected launcher and `clone where`
      against real `git clone`s; the step runner's tests moved to `start …
      --unattended`.
- [x] 2.9 Verification: the new command and fragment tests, unit; the suites of
      section 1; `make test-release-tooling`; `make test`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates; by hand, `scripts/change-workflow next
      specify-change-workflow-and-engine` prints what the old
      `change_next_step.py specify-change-workflow-and-engine` printed.
      End-to-end: none, and none is owed.
      Evidence: `test_change_workflow_cli.py` (unit, real repositories, `make -n`
      of the fragment), 138 passed; the scripts suite, 2002 passed; `make test`
      and `make check-packaging` passed; `make check-change` failed only on
      citations of files later sections create. The by-hand comparison, denied
      before 3.1's rules existed, is carried by 3.9.

Notes. No step's rules can make a file executable: the command was staged with
`git add --chmod=+x` and the owner made the worktree copy executable; a later
executable file needs the same.

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

- [x] 3.1 The orchestrator's, before the session starts, on the owner's word:
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
      Done by the orchestrator on the owner's word; committed with the section.
      `test_change_workflow_steps.py` (unit, the real table) pins the rules each
      step holds and the `round-view*`/`round-done*` deny rules.
- [x] 3.2 The root `Makefile`: sets `CHANGE_WORKFLOW_MERGE_FROM := dev` and
      `CHANGE_WORKFLOW_REVIEW_BASE := dev`, includes
      `scripts/change_workflow/workflow.mk`, and drops the targets the fragment now
      holds; its own targets that ran `round-view-closed` keep it, now the
      fragment's (D4; CW-h8vm). `make help` lists the fragment's targets.
      Done; `HELM_ALL_SCENARIOS` reaches validation by `validate: ARGUMENTS += …`;
      `diagram.main` refuses a missing diagram with exit 1. The repository has no
      `make help`; the targets' `##` descriptions live in the fragment, and Bash
      completion lists them (3.5).
- [x] 3.3 Every skill under `.agents/skills/change-*` names the command where it
      named an old script or `run_change_step.py`: `scripts/change-workflow find
      --records`, `next`, `log`, `record`, `note`, `push` (for `make push-branch`),
      `check round-view` (for `make round-view-closed`), `check index`, and the
      rest; the orchestrate skill starts steps through the make targets as before
      (D4).
      Done, with `history` in archive cleanup and each unattended preamble naming
      `start --unattended`. Kept as make targets: `make check-tasks`, `make
      check-agent-skills`, `make check-change`, the owner's own targets, and
      design's proposal-checkout index check. The orchestrate skill runs a clone's
      command as `cd <clone> && scripts/change-workflow …`.
- [x] 3.4 The four importers call the command and import nothing of the engine:
      `check_change.py`, `check_doc_citations.py`, and `validate_slice.py` read
      `find --json`'s `directory`, `archived`, and `records`; `validate_parallel.py`
      reads `clone where`, telling its four cases apart by exit status and output
      (D6; CW-r3ka's first scenario).
      Done through a new repository helper, `scripts/workflow_command.py`, which
      runs the command as a process and raises `WorkflowRefused` with its reason
      (tested against the real command); closeout's promotion names it in
      `market-change-workflow`'s Evidence. `validate_parallel.py` refuses a
      refusal, an empty answer, and a path other than the clone; its tests make
      clones with `scripts/change-workflow clone` and wait on report text (D4,
      "Settled in implementation"). The four importers' tests run on real Git
      repositories.
- [x] 3.5 `scripts/completions/make-change.bash` completes change names on the
      fragment's targets as it did on the `Makefile`'s.
      Needed no edit: bash-completion's `make -npq` follows the include; two tests
      against a Makefile including the real fragment.
- [x] 3.6 `docs/agents/change-workflow.md`, `AGENTS.md`'s "Agent skills", and
      `openspec/README.md`'s closeout part 11 name the command where they named
      the old scripts.
      Done; also `change-workflow`'s `spec.md` Evidence and companion, whose
      citations of the removed scripts would not resolve, the outcome schema's
      description, and the engine's own strings.
- [x] 3.7 Remove the old scripts from `scripts/`: `run_change_step.py`,
      `change_next_step.py`, `change_clone.py`, `round_view.py`,
      `change_history.py`, `find_change.py`, `change_cost.py`,
      `check_change_index.py`, `check_tasks.py`, `check_push_ready.py`,
      `check_agent_skills.py`, and `post_compaction_context.py` (D4).
      Done, with `git rm`.
- [x] 3.8 Tests: `test_make_change_completion.py`,
      `test_change_build_and_helm_targets.py`, `test_run_change_step.py`,
      `test_validate_parallel.py`, `test_check_change.py`, and any test naming an
      old script or a moved target, follow the command and the fragment; a new unit
      test fails when a file under `scripts/` other than the engine's own modules
      and tests imports `change_workflow` (D6, "A repository calls the engine only
      as the command").
      Done. `test_run_change_step.py` became `test_change_workflow_cli_steps.py`,
      reading the root Makefile's commands by `make -n`;
      `test_change_workflow_command.py` runs the command as a process and holds the
      import rule — an AST scan of every `.py` under `scripts/` but the package and
      its tests, finding an import at module level, in a function, under
      `TYPE_CHECKING`, or in a `try`. It does not see `importlib.import_module`,
      which no script uses. `test_change_build_and_helm_targets.py` needed no
      edit.
- [x] 3.9 Verification: the section's tests, unit; `make test-release-tooling`;
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
      Evidence: the scripts suite (unit, with real repositories and clones, and the
      subprocess boundaries — `make -n` of the Makefiles, the command as an
      executable, the clones' background bootstrap — run for real), 1999 passed;
      `make test` and `make check-packaging` passed; `make check-change` failed
      only on citations of files later sections create. By hand: `find --json`,
      `next --plain`, `check index`, `make check-change-index`, and `check
      round-view`. Denied as Bash calls, and shown instead by the root-Makefile
      tests and `test_change_workflow_command.py`: `make change-next`, the two
      `make -n` runs, and `check graph`. The side-by-side comparison with the
      removed `change_next_step.py` stands as the in-process equality of
      `cli.main` and `next_step.main`. The `cd <clone> && …` form is shown only by
      section 1's root tests. The grep finds no old script's name outside `.claude`,
      whose old rules 4.1 removed.

Deferred. Other changes' documents citing the removed scripts are left to each
change's own redesign once this change lands (an unscoped `make
check-doc-citations` lists them). Five engine tests keep the old scripts' names
(`test_find_change.py`, `test_check_tasks.py`, `test_check_push_ready.py`,
`test_post_compaction_context.py`, `test_round_view.py`); no rule asks a rename.

Round 1's triage (review 38) fixed 38 F1, the post-compaction hook now run in
`$CLAUDE_PROJECT_DIR` (D4, "Settled in implementation"), and 38 F2, `next` writing
`ERROR: <reason>` to standard error on an `unclassified` result. Tests in
`test_change_workflow_command.py` run the hook from outside any repository and from
another one, and `next` on an unknown change in both forms. Evidence: focused
suites 367 passed; the scripts suite 2001 passed; `make test` and `make
check-packaging` passed; `make check-change` as before.

## 4. The record set's format, read and marked

Delivers one format version for a change's record set, carried on the outputs and
the schema, read as older, current, or newer, and marked by `start` before any step
runs; and an unknown node reported by name (D8; D7; CW-x7jd, CW-k6qa, CW-9fbu).
Touches `.claude/change-steps.toml` (the orchestrator's),
`scripts/change_workflow/log.py`, `next_step.py`, `find.py`, `convert.py`, `cli.py`,
`outcome.py`, `.agents/change-outcome.schema.json`, and `scripts/tests/`.

- [x] 4.1 The orchestrator's, before the session starts, on the owner's word:
      `.claude/change-steps.toml` drops the rules naming the removed scripts and
      make targets section 3 moved, keeping the command's.
      Done by the orchestrator, with the header comment naming the command;
      committed with the section. `test_change_workflow_steps.py` shows no step
      allows the moved targets.
- [x] 4.2 `next`'s data output and `find --json` carry `format`; the outcome
      schema's `$id` states the format it belongs to (D8; CW-x7jd).
      Done; `next`'s JSON begins with `format`, the plain form unchanged; the
      `$id` and its check are D8's "Also settled in section 4".
- [x] 4.3 Reading a log: a line with no `format`, or a lower one, is older, named
      to the owner with `convert` as today; a higher one is refused, naming it, by
      the computation and by `convert`, which rewrites nothing. With no log, or an
      empty one, numbered records are older and a ledger alone, or nothing, is read
      in the reader's format (D8; CW-x7jd's scenarios; CW-k6qa's second).
      Done as D8's section-4 paragraph states, the appender's refusal
      (`NewerFormat`) beyond the plan; the engine reads no ledger, and a test pins
      a ledger alone read in the reader's format.
- [x] 4.4 `start` ensures the change's log exists and appends a line carrying the
      format before any step it starts runs, interactive or unattended; the
      computation routes on no such line (D8; CW-k6qa).
      Done: `log.open_log` writes `{"step": "start", "outcome": "opened",
      "starts": <step>, "interactive": …}` after `start`'s refusals; its refusals
      of older and newer records, `start orchestrate`'s opening none, and the line
      a wrapper refusal leaves are recorded in D8.
- [x] 4.5 The computation, the outcome check, and the log's writer report a node or
      kind the graph does not declare by name and route on no line after it (D7;
      CW-9fbu's first scenario).
      Done as D7's section-4 paragraph states, through `log.undeclared`; `next`'s
      output gains no field, and the log's writer and the triage check read the
      kinds from the graph's `NODES` at call time.
- [x] 4.6 Tests, unit: the format on `next` and `find --json` and in the schema's
      `$id`; an older, a current, and a newer log, read and converted; a log with
      only a ledger beside it, and none; `start`'s opening line, interactive and
      unattended, and the computation ignoring it; an unknown node in an exit and a
      kind added to `graph` accepted with no other list edited.
      Done across `test_change_workflow_log.py`, `test_change_next_step.py`,
      `test_change_workflow_convert.py`, `test_change_workflow_cli.py`, and
      `test_change_workflow_outcome.py`. A kind added to the graph is shown by
      patching `graph.NODES`, which reaches the writer, the outcome check, and the
      triage check; `review --kind` reads `graph.KINDS`, derived at import, so it
      follows an edit of the table but not the patch. The table has no seam, and
      reloading the package around a rebuilt one would test the import machinery
      more than the readers.
- [x] 4.7 Verification: the section's tests, unit; `make test-release-tooling`;
      `make test`; `make check-change CHANGE=specify-change-workflow-and-engine`,
      failing only on the citations of files a later section creates. End-to-end:
      none, and none is owed.
      Evidence: the section's suites (unit; real files, temporary Git
      repositories, the real step table), 682 passed; the scripts suite, 2049
      passed; `make test` and `make check-packaging` passed; `make check-change`
      failed only on citations of files later sections create. No typing check
      covers `scripts/`.

## 5. The index check, and the companion's two names

Delivers the check that holds an indexed capability's `spec.md` to its `index.md`,
and the skills and configuration that know a capability's companion is `README.md`
where `index.md` exists (D15; planning-governance's "Indexed capability
documentation" and modified "Permanent capability architecture companions").
Touches a new `scripts/check_spec_index.py`, `scripts/check_change.py`,
`openspec/config.yaml`, `.agents/skills/change-closeout/SKILL.md`,
`change-design/SKILL.md`, `change-review/SKILL.md`, and `scripts/tests/`.

- [x] 5.1 `scripts/check_spec_index.py`: for each capability under
      `openspec/specs/` with an `index.md`, fails on a requirement whose name begins
      with no id (the capability's prefix and four characters from `[a-z0-9]`), two
      requirements sharing an id, an id `index.md` omits or lists twice, a listed id
      in neither `spec.md` nor the named change's own deltas, a retired id in use,
      and a link in `index.md` that does not resolve; it names each. A capability
      with no `index.md` is not checked (D15).
      Done; the index's shape and the deltas' counting are D15's "Settled in
      implementation", stated in `openspec/README.md#capability-documentation-pattern`
      and the check's docstring. Links resolve to headings as GitHub writes
      anchors, fenced code skipped; an archived change has no deltas. `make
      check-spec-index [CHANGE=…]` runs it.
- [x] 5.2 `scripts/check_change.py` runs it among a change's closing checks, with
      the change named so its deltas count (D15, "The deltas clause").
      Done as `specification index`, the seventh check, before the validator; the
      guide, the implement skill, and the target's description list it.
- [x] 5.3 `openspec/config.yaml`'s rules, and the closeout, design, and review
      skills, name the companion as `README.md` where `index.md` exists and
      `architecture.md` elsewhere; the closeout skill's promotion part writes the
      `index.md` entries, with links and summary lines, for the ids a change adds,
      and moves a removed requirement's id to the retired ids with where its rule
      went (D15).
      Done; `config.yaml` also asks a new id for each requirement of an indexed
      capability and names the index among promotion destinations.
- [x] 5.4 Tests, unit, `scripts/tests/test_check_spec_index.py`: each failure case
      named; an id listed in `index.md` and present only in a change's ADDED delta
      accepted; a capability without `index.md` ignored.
      Done, with the prefix line, removals, renames, code fences, and the
      command's statuses; `test_check_change.py` expects the seventh check.
- [x] 5.5 Verification: the section's tests, unit; `make test-release-tooling`;
      `make check-agent-skills`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.
      Evidence: `test_check_spec_index.py` and `test_check_change.py` (unit, real
      files), 38 passed; the scripts suite, 2075 passed; `make check-agent-skills`,
      `make check-comment-hygiene`, `make test`, and `make check-packaging` passed;
      `make check-spec-index` passed with no `index.md` yet, showing only the
      wiring; `make check-change` failed only on citations of files later sections
      create.

Review 49's triage (49 F3) added the failure on an entry whose link is not to its
own id's heading (D15); an id two requirements share is held to neither. Tests:
swapped links, another file's heading, a `./spec.md` path, a shared id, a rename's
new heading. Evidence under section 10.

## 6. The graph diagram moved into its capability

Delivers the graph diagram in `openspec/specs/change-workflow/diagrams/`, still held
to the graph table (D12). Touches
`docs/development/diagrams/change-workflow-graph.drawio` and `.svg`,
`scripts/change_workflow/diagram.py`, `graph.py`, the capability's companion (then
`architecture.md`, now `README.md`), and
`scripts/tests/test_change_workflow_graph.py`.

- [x] 6.1 `git mv` the diagram's `.drawio` and `.svg` to
      `openspec/specs/change-workflow/diagrams/`; `diagram.py`, `graph.py`'s
      docstring, the graph test, and the companion's embed and source link name the
      new path (D12).
      Done; Git records both as renames, the test reads `diagram.DIAGRAMS`, and
      the guide's and the spec's Evidence citations moved too.
- [x] 6.2 Verification: `make change-graph` says the diagram draws the table; the
      graph tests, unit; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.
      Evidence: the graph, CLI, and command tests, 229 passed, among them the
      graph test running `make change-graph` as a process and finding it print
      that the diagram draws the table (the target being denied to the step as a
      Bash call); `make test` and `make check-packaging` passed; `make
      check-change` failed only on citations of files later sections create.

## 7. The assumptions test, and the two tables it reads

Delivers the inventory written two-sided — the roles in `change-workflow`'s
`README.md`, this repository's provision of each in `market-change-workflow`'s — and
the test that holds the targets and paths the skills, the step table, and the
fragment name to it (D13; D15's rename; CW-m4ps, MCW-5tgp). Touches
`change-workflow`'s companion, `architecture.md` → `README.md`, a new
`openspec/specs/market-change-workflow/README.md`, every citation of the companion's
old path, and a new `scripts/tests/test_change_workflow_assumptions.py`.

- [x] 7.1 `git mv` the companion, `architecture.md` in
      `openspec/specs/change-workflow/`, to `README.md` beside it (D15), and move
      every citation of the old path: `openspec/specs/README.md`, `docs/agents/change-workflow.md`,
      `openspec/changes/README.md`, the spec's own Evidence, `diagram.py`,
      `graph.py`, the graph test, and any other `make check-doc-citations` finds.
      The content is rewritten at closeout (11.9); this section adds only the
      section of 7.2.
      Done, with each listed citation. Correction: this task and sections 6 and
      7's "Touches" now name the old file without forming a path the citation
      check reads. Deferred: four other active changes cite the old path
      (`add-workflow-harness-adapters`, `remove-workflow-log-conversion`,
      `sandbox-unattended-workflow-steps`, `workflow-round-review-without-merges`),
      left to each one's reverification once this change lands.
- [x] 7.2 `change-workflow`'s `README.md` gains "What an adopting repository
      provides": a table of each role (a command validating a commit locally, the
      packaging check before closeout, the change index at its path, the guidance
      documents every step reads, the protected branches, the `origin` remote, the
      clone's bootstrap, and every other role the targets and paths of 7.4 fill),
      the skills that use it, and the change expected to replace it; then the
      engine's own assumptions — the paths its modules hold, the default merge
      branch, the `workspace` remote, `CLAUDE_CODE_SESSION_ID`, and the tools it
      invokes (`git`, `claude`, `codex`, `gh`) — marked as maintained by review
      (D13; CW-m4ps).
      Done: seventeen roles (D13, "Settled in implementation"), then the engine's
      own assumptions with the module attribute holding each. Corrected against
      the code: the engine invokes `make` for the bootstrap and no `gh`, which only
      the validation skill names.
- [x] 7.3 A new `openspec/specs/market-change-workflow/README.md` with "How this
      repository provides the workflow's roles": each role of 7.2 and the target,
      path, branch, or document that fills it here (`make validate-local`, `make
      check-packaging`, `openspec/changes/README.md`, `dev` and `main`, `make init`,
      …), the engine's own assumptions marked as maintained by review; the rest of
      the document is written at closeout (D13; MCW-5tgp).
      Done, every collected target and path in code, with the engine's own
      assumptions as met here in a second table.
- [x] 7.4 `scripts/tests/test_change_workflow_assumptions.py`, unit: collects every
      `make <target>` and repository path the skills under `.agents/skills/change-*`,
      `.claude/change-steps.toml`, and `scripts/change_workflow/workflow.mk` name,
      and fails, naming each and where it is named, on one the provision table does
      not list; and fails on a role either table lacks. It reads the two tables'
      Markdown and claims nothing of the engine's own assumptions (D13; CW-m4ps's
      scenarios).
      Done; what it collects and what it leaves is D13's "Settled in
      implementation". Roles are each document's first table's first column,
      compared both ways; only the two tests of the real documents read Git's
      tracked root.
- [x] 7.5 Verification: the assumptions test, unit, passing, and failing on a
      temporary skill naming an unlisted target; `make test-release-tooling`; `make
      test`; `make check-doc-citations CHANGE=specify-change-workflow-and-engine`
      reporting no citation of the old companion path; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.
      Evidence: `test_change_workflow_assumptions.py` (unit), 10 passed, among them
      a temporary skill naming an unlisted `make check-something` reported with
      where it is named, and a role missing either side named through the real
      test's function; the graph tests at the new path pass; the scripts suite,
      2085 passed; `make test` and `make check-packaging` passed; the scoped
      citation check reports no citation of the old companion path; `make
      check-change` failed only on citations of files closeout creates.

Review 49's triage (49 F4) corrected the implement skill, the guide, and the
companion, which said only `dev` is protected: `main` and `dev` are. Until closeout
writes `change-workflow`'s `index.md`, the companion rule points at an
`architecture.md` that is gone; closeout closes that window.

## 8. The `change-workflow` specification rewritten, with its trace

Delivers the `change-workflow` delta that rewrites the specification against its
outline: every existing requirement REMOVED with its migration, every new one ADDED
with its id, each under 500 characters, and the trace that maps every old MUST
clause and scenario (D10; D11's isolation; D3's seam; the deltas of D4–D9 and D13
already in it). Touches
`openspec/changes/specify-change-workflow-and-engine/specs/change-workflow/spec.md`
and a new `openspec/changes/specify-change-workflow-and-engine/trace.md`.

- [x] 8.1 ADDED requirements written from D10's outline, each `### Requirement:
      CW-xxxx <name>` with a new random id, one behaviour in under 500 characters,
      its cases as scenarios; the general rules of every "general" and "split" row
      of D10's destination table, with the seam each split row keeps; and the
      commands the requirements name are the command's, not the old scripts'
      (D10; D3; D4).
      Done in the outline's order, which closeout's `index.md` groups (D10,
      "Settled in implementation"). The seams: CW-hdxi, CW-zkhs, CW-59c7 (with
      CW-p7kq, 71 F1), CW-zq4h, CW-8npg, CW-ikmm. Scenarios name the command where
      the old ones named make targets.
- [x] 8.2 The conversion's rules are requirements of their own, and so are the
      round view's mechanics, so that `remove-workflow-log-conversion` and
      `workflow-round-review-without-merges` each meet known ids (D11).
      Done; the ids are listed under D11's "Settled in implementation".
- [x] 8.3 Every one of the 24 existing requirements REMOVED, its `**Reason**` and
      its `**Migration**` naming the ids that hold its rules, in `change-workflow` or
      `market-change-workflow` (D10).
      Done; each Migration names every id holding its rules or scenarios, the
      MCW ids included (9.2).
- [x] 8.4 `trace.md`: one row per MUST clause and per scenario of the existing
      specification, naming the id that holds it, or "dropped" with the reason;
      every placement agreeing with D10's destination table. A clause the trace
      cannot place as the table does stops the section and returns the change to
      design (D10).
      Done; nothing dropped, every placement agreeing with the table (D10,
      "Settled in implementation").
- [x] 8.5 Verification: `openspec validate specify-change-workflow-and-engine
      --strict` under the pinned 1.14.0, and every ADDED requirement's text under
      500 characters, read from the delta; `trace.md` names every requirement and
      scenario heading of `openspec/specs/change-workflow/spec.md`, checked by
      listing those headings with `grep` against the trace's rows; `make
      check-change CHANGE=specify-change-workflow-and-engine`, failing only on the
      citations of files the change creates. End-to-end: none, and none is owed.
      Evidence: the pinned strict validation passed, run by `make check-change`;
      each ADDED body, counted with `awk`, is under 500 bytes (the longest,
      CW-m4ps, 492) with MUST or SHALL and a scenario; the trace's headings and
      `Scenario:` rows match all 24 requirements and 185 scenarios exactly; `make
      check-change` failed only on citations of files closeout creates; `make test`
      passed.

Review 49's triage (49 F2) moved every `Contract:` citation in
`scripts/change_workflow/` and the four `scripts/` modules to the ids holding its
rules, each checked against the two deltas; the step table's header comment was
edited by the orchestrator on the owner's word after the triage. Owed to closeout
(11.9): the permanent documents citing the removed names
(`docs/agents/change-workflow.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, the
capability's `README.md`).

## 9. The `market-change-workflow` specification

Delivers this repository's own workflow requirements as their own capability: the
clause groups D10's table moves, the Helm namespace requirement whole, and this
repository's values, beside MCW-5tgp (D3; D10's destination table). Touches
`openspec/changes/specify-change-workflow-and-engine/specs/market-change-workflow/spec.md`
and `trace.md`.

- [x] 9.1 ADDED requirements, each `### Requirement: MCW-xxxx <name>` with a new
      random id and under 500 characters: this repository's validation parts (the
      clause groups of D10's "Validation observes a committed slice" row), each Helm
      validation isolated in its change's namespace (whole), the protected branches,
      the merge's default branch, the forbidden models, and the clone's bootstrap
      (D3; D10).
      Done, beside MCW-5tgp: the validation parts MCW-v3tf, MCW-zk52, MCW-gvqb,
      MCW-3i99, MCW-7hr1, MCW-2lzw, MCW-3yqn, MCW-qeja, MCW-8h0r; the Helm
      namespace MCW-fnuh, MCW-a0hu, MCW-notv, MCW-7bia, MCW-epkd, MCW-7ts3; and
      MCW-farr, MCW-ca51, MCW-y37w, MCW-uqlq, with MCW-q8vd added at 71 F1. Moved
      scenarios keep their text but MCW-7hr1's job name (D10, "Settled in
      implementation").
- [x] 9.2 `trace.md`'s rows for the clauses that move here name these ids (D10).
      Done, and the REMOVED entries' Migration lines name them too; no row is left
      unnamed.
- [x] 9.3 Verification: `openspec validate specify-change-workflow-and-engine
      --strict`; every requirement under 500 characters; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files the change creates. End-to-end: none, and none is owed.
      Evidence: the pinned strict validation passed; each of the 20 bodies is
      under 500 bytes by `awk` (the longest, MCW-2lzw, 478); every trace row naming
      an MCW id names the requirement carrying its scenario, 20 rows; `make
      check-change` failed only on citations of files closeout creates; `make test`
      passed. The `README.md` provisions and these requirements agree on the
      values; closeout completes the `README.md` (11.9).

## 10. The indexed organization's text

Delivers the convention as written guidance: how an indexed capability's documents
are organized, and what closeout writes into `index.md` (D15). Touches
`openspec/README.md` and `openspec/specs/README.md`.

- [x] 10.1 `openspec/README.md#capability-documentation-pattern`: a capability may
      be organized by an index — `README.md`, `index.md`, `spec.md`, `diagrams/` as
      D15 lays them out — with the id rule, retired ids, citing by id, and the
      check (D15).
      Done as a subsection, "A capability organized by an index", keeping the
      section's cited anchor, with the index's shape and the check's failures (D15,
      "Settled in implementation"); the opening list, placement table, and
      companion paragraphs name `README.md` where `index.md` exists.
- [x] 10.2 `openspec/README.md#plan-closeout-requirements`, part 9: promotion writes
      the `index.md` entries for the ids a change adds and retires the ids it
      removes (D15).
      Done, with renames and modifications (D15, "Settled in implementation").
- [x] 10.3 `openspec/specs/README.md`'s description of a capability's files: the
      companion is `README.md` where `index.md` exists (D15).
      Done, with the reading order's companion and the promotion sentence naming
      `index.md`.
- [x] 10.4 Verification: `make check-doc-citations
      CHANGE=specify-change-workflow-and-engine`, failing only on files the change
      creates; `make check-change CHANGE=specify-change-workflow-and-engine`.
      End-to-end: none, and none is owed.
      Evidence: the scoped `make check-doc-citations` failed only on files closeout
      creates (the two `index.md`, `market-change-workflow`'s `spec.md`); an
      unscoped run reports nothing in `openspec/README.md` or
      `openspec/specs/README.md`; `make test` passed. The new text's anchors were
      checked by reading; no tool checks a fragment.

Review 49's triage fixed four findings against `ff9fbd029` (validation 52 passed,
Helm waived): 49 F1, the preamble orders sections without assigning them to rounds;
49 F2 under section 8; 49 F3 under section 5; 49 F4 under section 7. Evidence:
`test_check_spec_index.py` and `test_check_change.py`, 43 passed; the scripts
suite, 2090 passed; `make test`, `make check-packaging`, `make check-agent-skills`,
and `make check-comment-hygiene` passed; `make check-change` failed only on
citations of files closeout creates.

Pre-closeout review 62's triage fixed two findings against `ce2c0f3ee` (validation
61 passed the scripts suite, the rest waived): 62 F1, CW-m7fk's reason on standard
error on every path (D6, "Settled in implementation"); 62 F2, `cli.py`'s `_takes`
and `delegated` docstrings describe what they do. Evidence: command-level tests in
`test_change_workflow_cli.py` and the reasons asserted in `test_check_tasks.py`,
`test_change_workflow_graph.py`, and `test_change_history.py`; the scripts suite,
2092 passed; `make test`, `make check-packaging`, `make check-agent-skills`, and
`make check-comment-hygiene` passed; `make check-change` as above.

Pre-closeout review 71's triage fixed two findings against the merged `7bb70aff4`
(validation 70 passed the scripts suite, the rest waived): 71 F1, `push` runs the
repository's pre-push check, `push.PRE_PUSH_CHECK`, as a command as Git runs a
pre-push hook rather than importing it (D4; CW-p7kq; MCW-q8vd), both `README.md`
gaining the role and the engine assumption; 71 F2, D10's guarded-push row and the
trace name the seam. Evidence: `test_check_push_ready.py` (real repositories with a
bare remote) covers the hook protocol, a refusal stopping `check` and `push`, a
silent failure named by its status, and the real check passing a clean push;
`test_change_workflow_cli.py` loads `change_workflow.cli` from the package alone
under `python -I`; the scripts suite, 2162 passed (validation 78 at `c882c6b6f`);
`make test`, `make check-packaging`, and `make check-comment-hygiene` passed; `make
check-change` as above.

## 11. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [x] 11.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments and docstrings this change added under `scripts/`, in
      `scripts/change_workflow/workflow.mk`, the root `Makefile`, `.agents/`, and
      `.claude/` for provenance — review, triage, finding, round, or section labels,
      "moved from", "formerly", the old scripts named as history; anything to
      rewrite returns the change to implementation.
      Confirmed: `make check-comment-hygiene` passed; the comments and docstrings
      added since the merge base with `dev` (`343d56733`) name no review, finding,
      round, section, earlier location, or removed script — "triage" and "review"
      appear only as the workflow's own vocabulary. Nothing to rewrite.
- [x] 11.2 Import placement — confirm: no function-local import added in the files
      this change added or touched under `scripts/`, the engine's moves included;
      one that should move returns the change to implementation.
      Confirmed: the change's diff adds no indented import, and no module of
      `scripts/change_workflow/`, `scripts/workflow_command.py`,
      `scripts/check_spec_index.py`, or the four callers holds one.
- [x] 11.3 Documentation compliance: re-check D1–D15 against
      `openspec/README.md#documentation-placement` — behaviour in the two
      capabilities' and planning-governance's specs, rationale and limits in the two
      `README.md`, organization in the two `index.md`, contributor procedure in
      `docs/agents/change-workflow.md`, documentation conventions in `AGENTS.md`
      and `openspec/README.md`; the cadence, the trace, and the destination table
      are change history and stay here.
      Done: each decision's destination is in the design-promotion record, every one
      in the home the placement table gives it; D1, D11, and D14 are change history.
      Against the code: the guide's subcommand list matches `cli.py`'s parsers, and
      the README's parts match `scripts/change_workflow/__init__.py`. A stale
      citation of a removed requirement name in `DEPLOYMENT_AND_CONFIG.md` ("Each
      Helm validation is isolated…") now cites MCW-fnuh, and the guide's cites
      CW-4rqr.
- [x] 11.4 Narrative compression of sections 1–10's notes, moving any rationale not
      yet in `design.md` there first.
      Done: sections 1–10 shortened from 1384 lines of `tasks.md` to 804, each note
      keeping final behaviour, evidence, deferrals, and destinations; the rationale
      not yet in `design.md` moved there first as "Settled in implementation"
      paragraphs under D4, D5, D6, D8, D10, D11, D13, and D15.
- [x] 11.5 Roadmap currency: no goal in `docs/development/ROADMAP.md` covers the
      change workflow — the lesser goal it serves is in `openspec/changes/README.md`
      (11.6); record that disposition in the promotion record, with no roadmap edit.
      Confirmed: no goal of `ROADMAP.md` names the workflow; no edit, recorded.
- [x] 11.6 Campaign index currency: this change's row `in closeout`, its notes
      rewritten; the lesser goal "Make the change workflow a tool any repository can
      adopt"'s current state names the command, the package, the make fragment, and
      the two capabilities in place of the old scripts and the architecture
      companion, and its gap row "The engine is documented as this repository's
      contract, not as a tool in its own right" is removed, the gap closed; no
      other row's `Depends on` or status changes; `make check-change-index`.
      Done: the row is `in closeout` with its notes rewritten; the goal's current
      state names the command, the package, the fragment, and the two capabilities,
      and its bullet on repository assumptions says they are listed but not
      declared; the gap row is removed. The goal has no dependency graph. No other
      row changed; `scripts/change-workflow check index` passed.
- [x] 11.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=specify-change-workflow-and-engine`, and `make check-agent-skills`.
      All three passed: every lock, layer, scope, dependency, and kind rule held;
      the change owns no architecture row; every skill loads from its one source.
- [x] 11.8 End-to-end pipeline: record the latest passing validation's pipeline run
      and Helm evidence for the commit closeout reads, or an explicit blocker naming
      its cause and owner. No scenario exercises the workflow tooling, so `make
      test` is its evidence; the change's own steps run through the command from
      round 2 on, cited by their log lines, are its working evidence.
      Recorded: the latest passing validation, 78, is of `c882c6b6f`, the
      pre-closeout fix commit, which the closeout commit carries unchanged: the
      scripts suite passed (2162 tests); `make check-packaging` and `make test`,
      Helm, the pipeline, and CI were waived by the owner ("workflow unit tests that
      validate the changed scripts"), as for 61 and 70. The last pipeline run is
      41902877727, success, at `ff9fbd029` (validation 52, round 2, Helm waived);
      the last full validation, local, Helm, and pipeline run 41862314250, is 40, at
      `0ff2623c9` (round 1). No CI is owed (no `Owed by validation:` line). No
      end-to-end scenario exercises the workflow tooling. Working evidence: from
      round 2 on every step was started through the command, its opening `start`
      lines at seq 62, 66, 68, 79, 84, 90, 94, 97, 103, 105, and 107 of the
      change's log, and its runs, implementation through the merge, logged at seq
      63–106.
- [x] 11.9 Promotion, completing the design-promotion record in `design.md`:
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
      Done, every location in the design-promotion record. `change-workflow`'s
      `README.md` follows the index's five parts, with a new opening to the engine
      (its parts, a step run's life, where a change's state lives, the command and
      its tiers), a public-surface part, and six new current limits; its
      Helm-specific prose (the namespace, memory and capacity, the CI list and the
      `dev` comparison, the wheelhouse) moved to `market-change-workflow`'s
      `README.md`, which gained the first-adopter principle, validation's parts,
      its workflow values, and its own limits. The three new diagrams are drawn by
      hand as `.drawio` and `.svg`, the SVG not embedding its source, and no XML
      parser was available to closeout, so they were checked for escaping by search
      only. Drawing them found the README saying a clone holds the round view's
      state; the code keeps it in the workspace, and the README now says so. The
      two `index.md` list 146 and 21 ids, as many as the deltas add, under the
      outline's parts and groups. Beyond the list: the guide's introduction names
      the index and `market-change-workflow`, and `DEPLOYMENT_AND_CONFIG.md`'s
      citation of the removed Helm requirement names MCW-fnuh. The deltas were not
      synchronized by hand, so the archive merges them.
- [x] 11.10 Documentation citations: `make check-doc-citations
      CHANGE=specify-change-workflow-and-engine` after promotion, resolving every
      match; then `openspec validate specify-change-workflow-and-engine --strict`.
      Before the archive, the citation check's only misses were
      `openspec/specs/market-change-workflow/spec.md`, cited by the proposal and
      this list and created by the archive. The index check, run by `make
      check-change`, also failed only on that capability's links to the same
      missing file, because it looks for the linked file before it reads a
      change's deltas, so it cannot accept a capability whose `spec.md` the
      change itself creates. The archived run (11.11) passed both. `npx --yes
      @fission-ai/openspec@1.14.0 validate specify-change-workflow-and-engine
      --strict`: valid.
      Closeout review 80 F2 found that part 10 was ticked on those failures and that
      the next new indexed capability would meet them; both checks were corrected
      after the archive, on the owner's direction. `scripts/check_spec_index.py`
      resolves a new capability's links to `spec.md` against the change's deltas
      when `spec.md` does not yet exist, and `scripts/check_doc_citations.py`,
      scoped to an active change, resolves a citation of
      `openspec/specs/<capability>/spec.md` the change's own delta creates. Unit
      tests in `scripts/tests/test_check_spec_index.py` and
      `scripts/tests/test_check_doc_citations.py` cover both, and the archived
      change's own run is unchanged. Evidence: the scripts suite (unit, `make
      test-release-tooling`) 2166 passed; `make test` passed; `make
      check-packaging` passed; `make check-change` passed. The fresh-context check
      found no defect; the two tests it asked for were added: a remove-only delta
      still leaves a missing `spec.md` missing, and a change's delta exempts only
      the `spec.md` it creates. Declined: the unscoped citation check still
      reports such a citation, since that view holds permanent documents to what
      exists; and the rules' `origin` (CW-8jyb, CW-xx5f) names the workspace's own
      remote by Git's convention, not one of this repository's values.
      Implementation review 88 F1 found both exceptions looser than a `spec.md`
      the delta creates: the citation check accepted any delta file, even an empty
      or remove-only one, and the index check a modify-only one. On the owner's
      direction both now require the delta to add a requirement, the only operation
      that can write a missing `spec.md`: `read_deltas` records the added names
      apart (`Deltas.added`), the index check's missing-file exemption reads them,
      and the citation check reads each delta with the same parser. Unit tests
      show an empty, empty-ADDED, remove-only, modify-only, and rename-only delta
      each leaves the citation and the index links unresolved, a delta adding a
      requirement beside a removal still resolves, and `added` holds only ADDED
      names. Evidence: the scripts suite (unit, `make test-release-tooling`) 2176
      passed; `make test` passed; `make check-packaging` passed; `make
      check-change` passed. The fresh-context check found no defect; its requested
      tests (a direct `added` test, a mixed delta that resolves, a rename-only
      citation case) were added, a delta is read tolerating invalid UTF-8 as
      documents are, and a reflowed docstring line was mended. Declined: the
      citation check's module docstring sentence "The existence test this
      replaces" predates this correction and is outside it.
- [x] 11.11 Archival: `openspec archive specify-change-workflow-and-engine -y`,
      merging the deltas into `change-workflow`, the new `market-change-workflow`,
      and `planning-governance`; where the archive writes a placeholder Purpose for
      `market-change-workflow`, replace it with its Purpose in the closeout commit;
      `make check-change CHANGE=specify-change-workflow-and-engine`, the index check
      among it, passes against the archived specifications; the row links the
      archive.
      Done with the pinned validator, `npx --yes @fission-ai/openspec@1.14.0
      archive specify-change-workflow-and-engine -y`, without `--skip-specs`, since
      no delta was synchronized by hand: `change-workflow` +146 −24,
      `market-change-workflow` created with 21, `planning-governance` +1 ~1, now
      `openspec/changes/archive/2026-11-05-specify-change-workflow-and-engine/`.
      The merged specifications hold each requirement once, as its delta stated
      it; `change-workflow` keeps its hand-written Purpose and Evidence and has no
      requirement without an id. `market-change-workflow`'s placeholder Purpose
      was replaced, and its Evidence written, taking the entries `change-workflow`
      gave up. The row links the archive.
