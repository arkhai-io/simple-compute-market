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
      `.next_step`, and `.clone`.
- [x] 1.3 `index.py` exposes the change index's reading — its rows, each row's
      status and dependencies — as public names the computation uses; the
      computation no longer imports `_DEPENDENCY` (D4). `Row.dependencies` yields
      a `Dependency(entry, name, phase)` per `Depends on` entry, `name` None for a
      malformed one; the index check and the computation both read it. The
      computation still treats an empty cell as no dependency, and the check still
      flags one, as before.
- [x] 1.4 `common.py`: `STEPS` and `KINDS` come from `graph`'s declaration, and no
      other module keeps a list of steps or kinds (D5, 1; CW-9fbu). They are
      declared in `graph` itself (`STEPS` the table's `runs`, `KINDS` its review
      nodes' kinds, in table order) and imported from there: `common` cannot import
      `graph`, which imports `common`. `records` used `KINDS` for the triage-outcome
      check and is imported by `graph`, so `triaged_problems` and
      `triage_outcome_problems` moved from `records` to `outcome`, which already
      imports `graph`. `STEPS`' order changed to the table's; only an error
      message's list shows it. The computation's step-to-phase map
      (`next_step._STEP_PHASE`), a second list of the steps, is now derived from the
      table too: the earliest phase of the one node running a step, none for
      review and triage; the map is unchanged, and a test pins it.
- [x] 1.5 `common.py`: the repository root is the working directory's Git top level,
      found once per command, refusing outside a repository and naming the
      directory; every module takes it from there rather than from
      `Path(__file__)` (D5, 2; CW-r3ka). In this checkout and in a change's clone
      it is the same directory as before. `repository_root()` runs `git rev-parse
      --show-toplevel` and raises `NotInRepository` (a `StepError`); each module's
      `main` takes `root=None` and resolves it, refusing with exit 1 and the
      directory named. The step table, the outcome schema, and the diagram source
      are relative paths: `load_steps()`, `load_schema()`, `Wrapper`, `run_review`,
      and `run_codex`'s working directory resolve the repository again from the
      working directory when given no path, which within one command is the same
      answer; a caller passing another `root` still gets this repository's table
      and schema of the working directory's repository, which the tests rely on:
      `scripts/tests` now passes only when pytest runs inside a checkout, as every
      make target runs it. Not "once per command" literally, then: section 2's
      `cli` resolves it once for what it dispatches. Unreachable through the entry
      points, but new: outside a repository `diagram.main` with an explicit
      source, `Wrapper()` without a root, and the post-compaction hook refuse, and
      `run_review` reports the repository before a bad kind.
      Correction: the root is the same as before only where the working directory
      is in the checkout the script sits in. The orchestrate skill runs a clone's
      scripts by path from the workspace (`python3 <clone>/scripts/…`), and the
      post-compaction hook runs from `$CLAUDE_PROJECT_DIR`'s path whatever the
      session's directory, so each old entry point sets the working directory to
      its own checkout before calling `main` (1.7). The command itself acts on the
      working directory's repository, as CW-r3ka says.
- [x] 1.6 `__init__.py` lists every module, `common` and `subagents` among them,
      each with its concern (D5, 4).
- [x] 1.7 Each old script path is an entry point of a few lines that calls its
      moved module's `main`, so every caller keeps working until section 3. Each
      also changes to its own checkout's top level first, so a caller running it
      by path from another directory acts on that checkout, as with `ROOT`. The
      four importers (`check_change.py`, `check_doc_citations.py`,
      `validate_slice.py`, `validate_parallel.py`) import `change_workflow.find`
      and `change_workflow.clone` directly until 3.4 moves them to the command, so
      the entry points re-export nothing. `check_comment_hygiene.py`'s one exempt
      line follows `TASKS_FILE` to `scripts/change_workflow/next_step.py`.
- [x] 1.8 Tests: every `scripts/tests/test_change_*`, `test_find_change.py`,
      `test_round_view.py`, `test_check_change_index.py`, `test_run_change_step.py`,
      and `change_workflow_fixtures.py` import the moved modules; new unit tests
      for the root's resolution (inside a repository's subdirectory, in a clone, and
      outside any repository, refused with the directory named) and that `graph`
      alone declares the steps and kinds. Also `test_check_tasks.py`,
      `test_check_push_ready.py`, `test_check_agent_skills.py`,
      `test_post_compaction_context.py`, and `test_validate_parallel.py`, which
      loaded the old scripts; `test_run_change_step.py` and the fixtures needed no
      change. New: `test_change_workflow_common.py` — the root in a temporary
      repository's subdirectory, in a clone, by default from the working
      directory, in this checkout, and refused outside any repository; every
      module's `main` refusing there and writing nothing; the steps and kinds as
      the table declares them, and no module but `graph` assigning `STEPS` or
      `KINDS` (by name only: a list kept under another name would pass), and the
      computation's step-to-phase map as the table gives it. And
      `test_change_workflow_entry_points.py`, which runs each old script path as a
      process from a directory outside any repository, with arguments that get it
      past finding the repository and stop it before it writes — a change name no
      change may have, or a read-only action — and shows it reaches its module
      without being refused there; section 3 removes it with the scripts. The
      orchestrate skill's pointer to the computation's result contract follows it
      to `scripts/change_workflow/next_step.py`.
- [x] 1.9 Verification: the moved suites pass with no assertion changed but
      imports, which proves behaviour unchanged; the new root and vocabulary tests,
      unit; `make test-release-tooling`; `make test`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none of `e2e-tests/` exercises the
      workflow tooling, and none is owed.
      Evidence: `make test-release-tooling` (unit, `scripts/tests`), 1859 passed
      after the fresh-context fixes; `test_change_workflow_common.py` (unit, real
      repositories in a temporary directory where the root is what is proven, as
      the plan's preamble sets the engine's tests), 21 passed;
      `test_change_workflow_entry_points.py` (library integration: each entry point
      run as a process against this checkout), 12 passed; `make test` passed;
      `make check-change` failed only on `check-doc-citations`, every miss a file a
      later section creates (`workflow.mk`, `trace.md`, `check_spec_index.py`, the
      assumptions and index tests, and the two capabilities' new documents).
      What the moved suites prove: they pass an explicit `root`, so they show the
      modules behave as before once given a repository, not the move from the
      script's location to the working directory, which the new tests cover. Not
      every assertion is untouched: `test_check_comment_hygiene.py` expects the
      exempt file at its new path; `test_change_workflow_graph.py`'s
      `{d.runs …} <= set(STEPS)` is now true by construction, since `STEPS` is
      derived from the table, and the vocabulary test pins the set instead;
      `test_change_workflow_steps.py` builds its absolute `STEP_TABLE` from the now
      relative constant.

Notes for the next session. The engine's mains take `root: Path | None = None`
and resolve it with `repository_root()`; section 2's `cli` should resolve it once
and pass it to each subcommand. The old entry points' usage strings
(`find_change.py`, `change_next_step.py`, `check_tasks.py`) and the step prompts
naming the old `run_change_step.py` (`harness.py`, `review.py`, `convert.py`'s
`convert` command, which `next` prints) are left for the command: changing them is
section 2's and 3's. `tasks.main` exits 2 for an unknown change, where D6 calls it
a refusal (1): section 2.2 settles the exit categories.

For section 3: the orchestrate skill runs a clone's engine by path from the
workspace (`python3 <clone>/…/change_next_step.py`, `…/run_change_step.py
note`, `… record`); the command acts on its working directory's repository, so
those calls must run in the clone — `make -C <clone> change-next`, or the command
started with the clone as its working directory — not `<clone>/scripts/change-workflow`
from the workspace, which would act on the workspace. Likewise the hook's new
wiring (3.1) acts on the hook's working directory rather than on
`$CLAUDE_PROJECT_DIR`'s checkout.

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
      the scripts offer today carries over"). `cli` resolves the repository once
      and passes it to each module's `main`; the delegating subcommands build the
      module's own argument list, so their output and status are the module's.
      `clone where <change>` shares the `clone` parser: `clone` with `where` and a
      second word is the lookup, so a change named `where` cannot be cloned by
      name. Not every part takes `cli`'s repository: `start orchestrate` reads the
      table under it, but the wrapper and `review` still read the step table and
      schema from the working directory, as section 1 left them; in production the
      two are one. `cli.delegated` names the module command line and arguments
      each delegating subcommand reaches, a seam the tests read directly.
      `run` is gone from the command: the old `run_change_step.py` maps its
      `run <step> <change> …` onto `start … --unattended` until section 3 removes
      it, so `start`'s refusals now run there too, after the make target's own.
      The file is staged as mode 100755; the worktree copy could not be made
      executable in this session (see the notes below).
- [x] 2.2 Exit statuses: 0 success; 1 a refusal or failed check, its reason on
      standard error; 2 a usage error, for every subcommand (D6; CW-5qne).
      argparse's usage errors return 2 rather than exiting; so do the malformed
      forms argparse cannot judge alone: `clone where` without a change or with
      `--branch`/`--from`, `find --records --json`, `start`'s unattended-only flags
      without `--unattended`, `start orchestrate` with anything but the change,
      sections on a step other than implementation or running backwards, and
      `convert`'s qualifiers without `--next`. Statuses that moved into the
      categories, each test updated: `tasks` exits 1, not 2, for an unknown change;
      `push` exits 1 for any failed `git push` rather than Git's own status; a
      backwards section range and `convert --kind` without `--next` exit 2, not 1.
      A session whose harness cannot be started (`claude` not on the path) is a
      refusal naming it, not a traceback.
- [x] 2.3 `start <step> <change>`: without `--unattended`, opens the interactive
      session the make target opened (`claude "/change-<step> <change>[ arguments]"`);
      with it, runs the wrapper as `run` did, with `--allow`, `--sections`,
      `--session`, `--arguments`, and `--fresh`. Before either, it refuses an
      archived change for design, planning, implementation, and the merge, naming
      the archived directory, and refuses while a round view is open — the make
      targets' `find_change.py --active` and `round-view-closed` (D4; CW-r3ka's
      scenario). `review` and `push` run the same round-view check.
      As the targets did: the steps taking only an active change are read from the
      graph (every node of the step carries the `NOT_ARCHIVED` entry guard), and
      so is archive cleanup's refusal of an active change (`ARCHIVED`, the
      `--archived` the target ran); every other step refuses only an unknown
      change. The round-view check covers the steps whose targets had
      `round-view-closed` — implement, triage, merge, closeout, validate, archive
      cleanup — and not design, planning, or orchestration. The interactive prompt
      is `/change-<step> <change>` with the sections and arguments, read from no
      table, as the target's was. Differences: `--allow`, `--session`, and
      `--fresh` are refused without `--unattended`, where the targets ignored
      them; sections are named by how many they expand to, interactively as
      unattended, so `SECTIONS=2` gives `section 2` and `SECTION=1-3` `sections
      1-3`, where the target followed the variable's name; and interactive
      sections are checked, so `SECTION=3-1` is refused where the target passed it
      through.
- [x] 2.4 `steps.py` reads an `[orchestrator]` row naming a model and effort and no
      permission rules, refusing one with rules; `start orchestrate <change>` opens
      the orchestrating session on it (D5, 3; CW-w2ld). The row itself is added to
      the table in 3.1. `load_orchestrator()` returns a Claude `Model`; the row
      takes `model` and an optional `effort`, and is refused with `allow` or
      `deny`, any other key, or a forbidden model, by `load_steps` too. `start
      orchestrate` takes the change alone (no `--unattended`, sections, or
      arguments) and refuses while the table has no row.
- [x] 2.5 `find --json <change>`: prints `name`, `directory`, `archived`, and
      `records` (the records directory, or `null` when this checkout holds none),
      and refuses an unknown change with exit 1, naming it; `format` joins it in
      section 4 (D6; CW-r3ka). `find.found` builds the object; `--json` combines
      with `--active` or `--archived`, and refuses `--records` (exit 2), whose
      workspace fallback the field does not follow.
- [x] 2.6 `clone where <change>`: D6's four cases in order — an unknown change exits
      1 naming it, before any clone lookup; a usable clone exits 0 printing its
      path; no clone directory exits 0 printing nothing; an unusable clone directory
      (not a clone of the workspace, its branch not checked out, its bootstrap not
      succeeded) exits 1 with the reason (D6; CW-r3ka). `clone.where` holds the
      three clone cases; run in a change's clone it looks beside the workspace that
      clone's `workspace` remote names.
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
      Done as the `Makefile`'s targets read, except: the step targets and `review`
      lose their `round-view-closed` prerequisites and `find_change.py` lines,
      whose checks `start` and `review` now run (2.3), and so does `push-branch`,
      since `push` runs the round-view check itself; `check-push-ready` keeps its
      prerequisite. `validate` passes `ARGUMENTS` in both modes in place of
      `HELM_ALL_SCENARIOS`, this repository's own variable: section 3's
      `Makefile` maps it, for instance by a target-specific `validate: ARGUMENTS =
      …`. `change-graph` runs `python3 -m change_workflow.diagram` with
      `PYTHONPATH` the command's directory, not the command: D4 and D6 name no
      subcommand for the diagram's comparison. That departs from CW-r3ka's "every
      operation … reachable through one command" and "never by importing its
      code", so it is an open choice for the owner, not settled here: a `check
      graph` subcommand (classified, as D6 would need, public or internal), or the
      comparison kept out of the surface as the diagram's own maintenance with
      CW-r3ka's wording narrowed to match. The recommendation is `check graph`,
      internal, beside the other checks.
- [x] 2.8 Tests, unit: each subcommand reaches its module with today's arguments;
      the exit categories, including a usage error; `start`'s refusals of an
      archived change and of an open round view, and the session command it builds
      interactively and unattended; `start orchestrate` on the row's model and
      effort, and a row with rules refused; `find --json`'s fields, `records` as
      `null`, and an unknown change; `clone where`'s four cases, against real
      clones in a temporary directory; the fragment's targets, with `make -n` from a
      temporary `Makefile` that sets `CHANGE_WORKFLOW_MERGE_FROM` and includes it,
      printing the command each target runs.
      In `scripts/tests/test_change_workflow_cli.py`: each delegating subcommand
      hands its module every argument (`cli.delegated`, read directly, flags
      included), and its output and status equal the module's own command line's on
      the same temporary repository — where most refuse at their first check, so
      that half shows the wiring, not the flags; sixteen usage errors exit 2, and
      `start`'s malformed sections too; `start`'s refusals and the interactive
      prompts through an injected launcher, a harness that cannot be started, the
      unattended run through the wrapper fixture; the orchestrator row's six
      refusals and its model; `clone where` against clones made with `git clone`
      beside a temporary workspace, plus a lookup run from inside the clone; every
      fragment target by `make -n`, and `CHANGE_WORKFLOW` and
      `CHANGE_WORKFLOW_REVIEW_BASE` set by `:=` before the include standing. The entry-point test
      gains the command run as a process inside and outside a repository, its mode
      in Git (100755), and the old step runner's mapping of `run`.
      `test_run_change_step.py`'s `run` calls became `start … --unattended`, on a
      Git checkout where the step reads `HEAD`, and its review test runs in one.
- [x] 2.9 Verification: the new command and fragment tests, unit; the suites of
      section 1; `make test-release-tooling`; `make test`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates; by hand, `scripts/change-workflow next
      specify-change-workflow-and-engine` prints what the old
      `change_next_step.py specify-change-workflow-and-engine` printed.
      End-to-end: none, and none is owed.
      Evidence so far: `test_change_workflow_cli.py` (unit, real repositories in a
      temporary directory, `make -n` of the fragment), 138 passed;
      `test_change_workflow_entry_points.py` (library integration), 17 passed;
      the scripts suite, 2002 passed; `make test` passed on the final code; `make check-change` failed only on `check-doc-citations`,
      every miss a file a later section creates (with `workflow.mk` now resolved);
      `make check-packaging` passed. Not run: the by-hand comparison — no rule lets
      this session run `scripts/change-workflow` or `python3
      scripts/change-workflow` until 3.1 adds the command's rules; the old script
      printed `{"step": "implement", "sections": [1, 2], …}`, and the subcommand
      test shows `next` prints what `next_step.main` prints on the same
      repository. Checked on that evidence once the owner made the command
      executable; the by-hand comparison was tried again then and is still denied
      (no rule names the command), so it is owed to 3.9's by-hand checks, which run
      the command once 3.1's rules exist.

Notes for the next session. No step's rules could make a file executable
(`chmod`, `git update-index --chmod`, and `git restore` have no rule; `git
checkout` and `git stash` are denied): the command was staged with `git add
--chmod=+x` and the owner made the worktree copy executable. A later executable
file needs the same.
Owed to section 3 from this section: the root `Makefile` maps `HELM_ALL_SCENARIOS`
onto the fragment's `validate` `ARGUMENTS`; and `change-graph` (2.7). Asked to
choose between a `check graph` subcommand (recommended, internal) and narrowing
CW-r3ka, the owner answered "a.", read as the first option, `check graph`; its
tier and its wording in the `change-workflow` delta are still to be written down,
in design or in section 3's plan, before 3.2 drops the `Makefile`'s own target.
Correction: the owner set its tier, internal, before section 3, and D4's mapping
and D6's table record it; its wording in the delta is section 8's.

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
      Done by the orchestrator once the owner approved it, after this section's
      first run stopped on its absence; committed with the section. The rules the
      edit added: `find*`, `next*`, `cost*`, `log*`, `record*`, `check round-view`,
      and `check index` for every step; `push` wherever `make push-branch` was
      allowed; `check push` for validation, `check *` for closeout, `history*` for
      archive cleanup; `round-view*` and `round-done*` denied to every step.
      `test_change_workflow_steps.py` pins them (unit, the real table read): each
      common rule and the deny rules for every step, `push` for every step but the
      review, `check push` for validation and closeout only, `check tasks` for
      closeout only, and `history` for archive cleanup only.
- [x] 3.2 The root `Makefile`: sets `CHANGE_WORKFLOW_MERGE_FROM := dev` and
      `CHANGE_WORKFLOW_REVIEW_BASE := dev`, includes
      `scripts/change_workflow/workflow.mk`, and drops the targets the fragment now
      holds; its own targets that ran `round-view-closed` keep it, now the
      fragment's (D4; CW-h8vm). `make help` lists the fragment's targets.
      Done; `HELM_ALL_SCENARIOS` reaches validation as the fragment's `ARGUMENTS`
      through a target-specific `validate: ARGUMENTS += …`, interactive and
      unattended, so a validation session's invocation reads as before.
      `change-graph` now runs `scripts/change-workflow check graph`: the owner chose
      the subcommand and its tier, internal (recorded in D4's mapping and D6's
      table), and `diagram.main` refuses a missing diagram with exit 1, naming it,
      where it raised. The repository has no `make help` target; the targets' `##`
      descriptions live in the fragment, and Bash completion lists its targets
      (3.5).
- [x] 3.3 Every skill under `.agents/skills/change-*` names the command where it
      named an old script or `run_change_step.py`: `scripts/change-workflow find
      --records`, `next`, `log`, `record`, `note`, `push` (for `make push-branch`),
      `check round-view` (for `make round-view-closed`), `check index`, and the
      rest; the orchestrate skill starts steps through the make targets as before
      (D4).
      Done, and also `check index` for `make check-change-index`, `history` for
      `make change-history` in archive cleanup, and each skill's unattended
      preamble names `scripts/change-workflow start --unattended`. Kept as make
      targets, since no rule names the command for them: `make check-tasks`,
      `make check-agent-skills`, `make check-change`, the owner's own targets
      (`make round-view`, `make round-done`, `make change-watch`), and design's
      `make -C ../<prerequisite>-proposal check-change-index`. The orchestrate
      skill runs the command for a change worked in its clone as `cd <clone> &&
      scripts/change-workflow …` and says why: the command acts on its working
      directory's repository; it keeps `make -C <clone> push-branch` and
      `change-history`.
- [x] 3.4 The four importers call the command and import nothing of the engine:
      `check_change.py`, `check_doc_citations.py`, and `validate_slice.py` read
      `find --json`'s `directory`, `archived`, and `records`; `validate_parallel.py`
      reads `clone where`, telling its four cases apart by exit status and output
      (D6; CW-r3ka's first scenario).
      Done through a new `scripts/workflow_command.py`, which the plan did not name:
      it runs the command beside it as a process in the checkout asked about and
      returns `found_change`'s object or `clone_where`'s path, raising
      `WorkflowRefused` with the command's reason (or, with none, the command and
      its status; or output that is no JSON object), so the three readers of `find
      --json` share one call; `test_workflow_command.py` tests it directly, against
      the real command on a temporary repository and a stand-in executable for the
      answers the command never gives. It is this repository's, not the engine's:
      closeout's promotion names it in `market-change-workflow`'s Evidence. `validate_slice.py` reads `records` (the change's
      `reviews/` in this checkout), where it read `<directory>/reviews`.
      `validate_parallel.py` asks `clone where` from inside the clone: a refusal
      (unknown change, unusable clone) and an empty answer (no clone of that change
      there) are both refused, and a path other than the clone is too, each case
      tested. Its tests now make their clones with `scripts/change-workflow clone`,
      whose bootstrap is the fixture's own `make init`, waiting for it through
      `clone where` (bounded at 30 s), rather than through the engine's module with
      an injected spawn, which the import rule now forbids a repository script's
      test. The wait polls until `clone where` stops reporting the bootstrap as
      running, which is the engine's report text, outside its promise: should it
      be reworded, the wait ends early and the failed-bootstrap test may race its
      bootstrap. The tests of all four now run on real Git repositories,
      since the command refuses outside one.
- [x] 3.5 `scripts/completions/make-change.bash` completes change names on the
      fragment's targets as it did on the `Makefile`'s.
      Needed no edit: target names come from bash-completion's own `make -npq`
      reading, which follows the include. Two tests added against a Makefile that
      includes the real fragment.
- [x] 3.6 `docs/agents/change-workflow.md`, `AGENTS.md`'s "Agent skills", and
      `openspec/README.md`'s closeout part 11 name the command where they named
      the old scripts.
      Done; and the permanent `change-workflow` documents, which the plan left to
      section 8 and closeout: `spec.md`'s Evidence and five passages of
      `architecture.md` cited the removed scripts by path, which `AGENTS.md`'s
      cross-reference rule makes a blocking defect once they are gone, so they now
      name the command and the modules. The outcome schema's description and the
      engine's own strings (the unattended prompts, `next`'s `convert` and
      `record` commands, usage lines, docstrings) name the command too.
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
      Done. `test_run_change_step.py` became `test_change_workflow_cli_steps.py`;
      its root-Makefile tests now read the fragment's commands from `make -n` of
      the root Makefile (this repository's branches, a repository target's
      round-view prerequisite, a grant's quoting through a real shell), the
      fragment's own forms staying in `test_change_workflow_cli.py`.
      `test_change_workflow_entry_points.py` became `test_change_workflow_command.py`:
      the command's process runs (`check skills` inside and outside a repository,
      `find --json` from a subdirectory, `check graph` on this checkout) and its
      mode, and the import rule — an AST scan of every `.py` under `scripts/` but
      the package and the engine's own tests, a test that imports one of this
      repository's scripts or names its file (as a load by path does) counting as
      the repository's, finding an import at module level, in a function, under
      `TYPE_CHECKING`, or in a `try`, itself tested on sources of each shape. It
      does not see `importlib.import_module`, which no script uses, and a test that
      checks this repository's files (the step table, the root Makefile) while
      importing the engine, as `test_change_workflow_steps.py` and the root-Makefile
      tests do, counts as the engine's. `test_check_change_index.py`'s and
      `test_check_push_ready.py`'s Makefile assertions moved into the root-Makefile
      tests. `test_change_build_and_helm_targets.py` names no old script or moved
      target, so it needed no edit. Also updated: `test_change_next_step.py` and
      `test_change_workflow_convert.py` (the `convert`/`record` commands),
      `test_change_workflow_steps.py` (the command's rules),
      `test_validate_slice.py` (Git repositories; `HELM_ALL_SCENARIOS` by `make
      -n`), `test_check_doc_citations.py`, and `test_change_workflow_cli.py`
      (`check graph`, the real table's orchestrator row).
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
      Evidence: the scripts suite (`scripts/tests`: unit as the plan's preamble
      sets the engine's tests, with real files, Git repositories, and clones in a
      temporary directory, and beyond it the subprocess boundaries proven against
      the real thing — `make -n` of the root Makefile and the fragment, the command
      run as an executable in `test_change_workflow_command.py`,
      `test_workflow_command.py`, and the importers' tests, and the clones'
      background bootstrap in `test_validate_parallel.py`), 1999 passed after both
      fresh-context checks' fixes; `make test` passed on the final code;
      `make check-packaging` passed;
      `make check-change` failed only on `check-doc-citations`, every miss a file a
      later section creates (`trace.md`, `check_spec_index.py`, the assumptions and
      index tests, the two capabilities' new documents), with comment hygiene and
      the agent skills check passing. By hand: `scripts/change-workflow find --json
      specify-change-workflow-and-engine` printed the four fields;
      `scripts/change-workflow next … --plain` printed the computation's plain form
      (the stopped run of this section, waiting on the owner); `make
      check-change-index` and `scripts/change-workflow check index` passed;
      `scripts/change-workflow check round-view` passed. Denied in this session, as
      no rule names them: `make change-next`, `make -n design … UNATTENDED=1`,
      `make -n orchestrate …`, and `scripts/change-workflow check graph`. In their
      place the root-Makefile tests (unit, `make -n` of the real Makefile) show
      what `change-next`, `design … UNATTENDED=1`, and `orchestrate` would run,
      without running them, and `test_change_workflow_command.py` runs `check
      graph` as the executable on this checkout. Section 2's owed side-by-side
      comparison cannot be made now that `change_next_step.py` is gone; what
      stands for it is `test_change_workflow_cli.py` calling `cli.main` and
      `next_step.main` in-process on one temporary repository, and the `next`
      run above on this change. Running a clone's command from the workspace
      with `cd <clone> && …`, as the orchestrate skill now says, is shown only by
      section 1's root tests (the root resolved in a clone); no test runs that
      form. The grep finds no old script's name in `.agents`, `docs`, `Makefile`,
      `AGENTS.md`, or `openspec/README.md`; in `.claude` it finds the old rules 3.1
      kept for this run and the step table's header comment, both 4.1's.

Notes for the next session. Owed to 4.1, the orchestrator's: beside the old rules,
the step table's header comment still says unattended steps run through the
removed `run_change_step.py`, and its comment on the push names only `make
push-branch`. Other changes' documents still cite the removed scripts by path
(`add-skill-extension-points`, `add-workflow-harness-adapters`,
`add-workflow-model-gateway`, `extract-change-workflow-repository`,
`host-change-workflow-runner`, `remove-workflow-log-conversion`,
`workflow-round-review-without-merges`), as does this change's campaign row in
`openspec/changes/README.md`: an unscoped `make check-doc-citations` lists them.
They are left to each change's own redesign once this change lands, and the
campaign row to closeout's 11.6. The engine's report text still names fragment
targets (`make round-done`, `make change-clone` in `next`'s commands and the round
view's refusals): report text is outside the promise (D6), but an adopter not
including the fragment would read targets it lacks, which section 7's inventory
should list. A fragment variable a repository sets for one target only goes in a
target-specific assignment after the include, as `validate: ARGUMENTS += …` does;
`make -n` of a root target is how the tests read what it runs, and is denied to the
implementation step as a Bash call, so the by-hand checks of a later section that
need it run through those tests. Five engine tests keep the old scripts' names
(`test_find_change.py`, `test_check_tasks.py`, `test_check_push_ready.py`,
`test_post_compaction_context.py`, `test_round_view.py`); renaming them was left,
as they name what they test well enough and no rule asks it.

Round 1's triage (review 38) fixed two of sections 1–3's defects. 38 F1: the
post-compaction hook ran the command by `$CLAUDE_PROJECT_DIR`'s path but in the
hook's working directory, so from outside a repository it printed nothing and from
another checkout it described that checkout. `.claude/settings.json`'s hook now runs
`cd "$CLAUDE_PROJECT_DIR" && scripts/change-workflow hook post-compaction`, an edit
the orchestrating session made on the owner's word, so the command's
working-directory rule (CW-r3ka) holds without an exception. 38 F2: `next` exited 1
on an `unclassified` result with its reason only in the result on standard output;
it now also writes `ERROR: <reason>` to standard error, as D6's exit 1 promises,
with standard output unchanged. Tests, in `test_change_workflow_command.py`: the
hook command read from the settings and run by `sh` from a directory outside any
repository and from another repository, describing this checkout's branch; and
`scripts/change-workflow next` on an unknown change, in its JSON and plain forms,
exiting 1 with the reason on standard error and the JSON result on standard output.
Evidence: the focused suites (`test_change_workflow_command.py`,
`test_change_next_step.py`, `test_post_compaction_context.py`,
`test_change_workflow_cli.py`; the two new tests library integration, the command
run as a process), 367 passed; the scripts suite (`make test-release-tooling`),
2001 passed; `make test` passed, on the fixed code before the fresh-context
check's two test-only edits; `make check-packaging` passed; `make check-change`
failed only on `check-doc-citations`, every miss a file a later section creates, as
before. The fresh-context check found nothing blocking. Following its notes, the plain form's test no
longer parses text outside the promise, and a redundant assertion went. Declined:
moving the `next` test in-process, since the owner accepted a process test of the
command's two streams, and the in-process equality of `cli.main` and
`next_step.main` stays where it is.

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
      Done by the orchestrator, in the worktree as the session started, with the
      table's header comment naming the command and its guarded push; committed
      with the section. `test_change_workflow_steps.py` (unit, the real table read)
      follows: the push test names `scripts/change-workflow push`, and a new test
      shows no step's rules allow `make change-cost`, `make round-view-closed`,
      `make push-branch`, or `make change-history`. `make check-change-index` and
      `make check-push-ready` stay reachable through `make check-*`, which design,
      planning, and closeout hold for checks of their own.
- [x] 4.2 `next`'s data output and `find --json` carry `format`; the outcome
      schema's `$id` states the format it belongs to (D8; CW-x7jd).
      `FORMAT` moved to `common`, since `find` cannot import `log`. `next`'s JSON
      begins with `format` (added by `next_step.main`, so `compute`'s results and
      the plain form are unchanged); `find.found` adds it last. The schema's `$id`
      is `urn:change-workflow:change-outcome:format:2`; `outcome.load_schema`
      refuses a schema whose `$id` states another format or none, and
      `harness_schema` leaves the `$id` out of what Claude Code is given, as it
      constrains nothing a step writes.
- [x] 4.3 Reading a log: a line with no `format`, or a lower one, is older, named
      to the owner with `convert` as today; a higher one is refused, naming it, by
      the computation and by `convert`, which rewrites nothing. With no log, or an
      empty one, numbered records are older and a ledger alone, or nothing, is read
      in the reader's format (D8; CW-x7jd's scenarios; CW-k6qa's second).
      `log.older` replaces `unmarked`, and `log.newer` finds a higher format or a
      mark that is no whole number (a string, a boolean), which is refused rather
      than converted backwards. The computation refuses a newer log right after
      reading it, before a branch decision is read, as `unclassified` (exit 1, the
      reason on standard error), as it refuses an unknown change, and so during a
      merge in progress, ahead of the merge's waiting run. `convert` refuses one before anything else,
      shown or confirmed. Beyond the plan, the log's appender refuses a newer log
      too (`NewerFormat`), so no line of this format follows one. The engine reads
      no ledger, so a ledger alone was already read in the reader's format; a test
      pins it.
- [x] 4.4 `start` ensures the change's log exists and appends a line carrying the
      format before any step it starts runs, interactive or unattended; the
      computation routes on no such line (D8; CW-k6qa).
      `log.open_log`, called by `cli.start` after its refusals and the round-view
      check, before the session or the wrapper: `{"step": "start", "outcome":
      "opened", "starts": <step>, "interactive": …}`. `start orchestrate` opens no
      log, since the orchestrating session is no step. Decided within D8: `start`
      refuses, writing nothing, records of an older format (a log with an older
      line, or numbered records and no line), naming `convert`, since the opening
      line would mark them current; and a newer log. An unattended start the
      wrapper refuses after the opening (an unknown `--session`, say) leaves its
      opening line: the line marks the format, not a run.
- [x] 4.5 The computation, the outcome check, and the log's writer report a node or
      kind the graph does not declare by name and route on no line after it (D7;
      CW-9fbu's first scenario).
      `log.undeclared` names a line's step no node runs, a review's kind no node is
      (none included), or an exit or owner's direction naming no node; the
      conversion and opening lines are known. The computation checks every line of
      the current format (an older one is the conversion's) right after the
      newer-format refusal, before `locate` reads a branch decision, and at the
      first undeclared one names the owner, the line's seq and what it names in the
      reason, and routes on nothing, earlier lines included; a merge's waiting run
      is not named past one either. The result adds no field, so `next`'s output
      gains none. `record_outcome` refuses an undeclared line, so a review of an
      unknown kind is refused; the outcome check and directions already named an
      unknown node. The kinds are read from the graph's `NODES` at call time
      (`graph.review_phase`) in `log.standing` and `outcome.triaged_problems`,
      which used the `KINDS` tuple.
- [x] 4.6 Tests, unit: the format on `next` and `find --json` and in the schema's
      `$id`; an older, a current, and a newer log, read and converted; a log with
      only a ledger beside it, and none; `start`'s opening line, interactive and
      unattended, and the computation ignoring it; an unknown node in an exit and a
      kind added to `graph` accepted with no other list edited.
      In `test_change_workflow_log.py`: older and newer lines, the appender's
      refusal, `undeclared`'s cases, a review of an unknown kind refused, the
      opening line, a ledger alone opened, older and newer records not opened; and
      a review kind added to the graph by putting a node in `graph.NODES`, the index
      of the table's declarations (through `monkeypatch.setitem`), then accepted by
      the writer, the outcome check, and the triage check. That shows those readers
      take the kinds from the graph at call time; it does not reach `review --kind`
      and `review.run_review`, which check `graph.KINDS`, a tuple derived from the
      table at import, so they follow an edit of the table but not this patch. In
      `test_change_next_step.py`: an empty log beside records is older, a ledger
      with no log is not, a newer log refused in the result, on the command line,
      and during a merge, `format` first in the output, an exit to an undeclared
      node routing no later line, an undeclared line named before a branch decision
      the checkout would match, and an unknown step, kind, and direction. In
      `test_change_workflow_convert.py`: a newer log refused, shown or confirmed,
      the log unchanged. In `test_change_workflow_cli.py`: the opening line before
      an interactive session (read by the injected launcher) and before an
      unattended run, the computation reading a log of the opening line alone as no
      log and routing past a later one, `start` refusing older and
      newer records and launching nothing, and `find --json`'s `format`. In
      `test_change_workflow_outcome.py`: the `$id`'s format, and schemas stating
      another or none refused. Three tests of `start --unattended` in
      `test_change_workflow_cli_steps.py` read the run's line, not the opening one.
- [x] 4.7 Verification: the section's tests, unit; `make test-release-tooling`;
      `make test`; `make check-change CHANGE=specify-change-workflow-and-engine`,
      failing only on the citations of files a later section creates. End-to-end:
      none, and none is owed.
      Evidence: the section's suites — `test_change_workflow_log.py`,
      `test_change_next_step.py`, `test_change_workflow_convert.py`,
      `test_change_workflow_cli.py`, `test_change_workflow_outcome.py`,
      `test_change_workflow_cli_steps.py`, `test_change_workflow_steps.py`, and
      `test_workflow_command.py` (unit; real files in a temporary directory, the
      command's `start` and `find` against temporary Git repositories, the real
      step table read) — 682 passed after the fresh-context check's fixes; the
      scripts suite (`scripts/tests`, as `make test-release-tooling` runs it), 2049
      passed; `make test` passed before those fixes and again after them;
      `make check-packaging` passed; `make check-change` failed only on
      `check-doc-citations`, every miss a file a later section creates, with
      comment hygiene passing. No typing check covers `scripts/`.

Notes for the next session. The fresh-context check's findings were fixed but two:
declined, the opening line written before the wrapper's own refusals, since moving
it into `Wrapper.run` would add a line to every wrapper test's log for a run that
never started either way, and the line creates no record the computation reads as
one (a workspace's `reviews/` holding only a log already exists wherever a step was
recorded there); and kept, with its reach stated in 4.6, the `graph.NODES` patch
standing for a kind added to the table, since the table is a module constant with no
seam and reloading the package around a rebuilt table would test the import machinery
more than the readers. `records.RECORD` is now the one numbered-record pattern;
`next_step` imports it as `_RECORD_FILE`, as its own `RECORD` is the `record`
command's text. The section owes no evidence only a push produces, and no end-to-end
scenario exercises it.

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
      The index's shape, which D15 left to the check and section 10 and closeout
      write down: a line `Prefix: `CW`` declares the capability's prefix (the
      check fails without one); a listed id is a list item or table row whose first
      cell is the link `[CW-a8tf](spec.md#…)`; the retired ids are the items under
      `## Retired ids`, each beginning with the id, bare, in backticks, or as the
      link its entry carried. An id is followed by a space or the name's end. A
      link resolves when its file exists and its fragment is a heading of that file
      as GitHub writes anchors; fenced code is skipped throughout, the prefix line
      and requirement headings included, and a URL is not followed. With a change
      named, its delta for the capability counts as the archive will leave it:
      ADDED and MODIFIED names, and a rename's new name, are in the specification
      and their headings resolve in `spec.md` (a requirement both renamed and
      modified counted once); a REMOVED requirement, and a rename's old name, are
      held to nothing, and their headings no longer resolve — which
      this change's own closeout needs, since `change-workflow`'s 24 requirements
      carry no id until the archive removes them. A change not found active (an
      archived one, whose deltas are merged) has no deltas. A new
      `make check-spec-index [CHANGE=…]` runs it.
- [x] 5.2 `scripts/check_change.py` runs it among a change's closing checks, with
      the change named so its deltas count (D15, "The deltas clause").
      As `specification index`, before the validator: seven checks now. The
      permanent lists of those checks follow: `docs/agents/change-workflow.md`, the
      implement skill's check list, and `make check-change`'s description.
- [x] 5.3 `openspec/config.yaml`'s rules, and the closeout, design, and review
      skills, name the companion as `README.md` where `index.md` exists and
      `architecture.md` elsewhere; the closeout skill's promotion part writes the
      `index.md` entries, with links and summary lines, for the ids a change adds,
      and moves a removed requirement's id to the retired ids with where its rule
      went (D15).
      Each skill's context list reads the companion by the two names, and the
      index where it exists; `config.yaml`'s specs rule also asks a new id for each
      requirement of an indexed capability, and its tasks rule names the index's
      entries and retired ids among promotion destinations.
- [x] 5.4 Tests, unit, `scripts/tests/test_check_spec_index.py`: each failure case
      named; an id listed in `index.md` and present only in a change's ADDED delta
      accepted; a capability without `index.md` ignored.
      Also: a missing prefix line; an id accepted from the delta is refused without
      the change named, as listed though no specification holds it and as an
      unresolved heading; a requirement a REMOVED delta names held to nothing; a
      rename, read from a string by `read_deltas` and checked by
      `capability_problems`; a rename with a MODIFIED block under the new name, from
      a delta file through `problems(root, change)`, counted once; a link to a
      heading a rename drops refused; a retired id written as a link; headings in a
      code fence neither anchors nor requirements; an id running past its four
      characters; GitHub's anchor form; the command's statuses.
      `test_check_change.py` expects the seventh check, with the change named.
- [x] 5.5 Verification: the section's tests, unit; `make test-release-tooling`;
      `make check-agent-skills`; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.
      Evidence: `test_check_spec_index.py` and `test_check_change.py` (unit, real
      files in a temporary directory), 38 passed after the fresh-context check's
      fixes; the scripts suite (`scripts/tests`, as `make test-release-tooling`
      runs it), 2075 passed; `make check-agent-skills` and `make
      check-comment-hygiene` passed; `make check-spec-index
      CHANGE=specify-change-workflow-and-engine` passed on this repository, which
      has no `index.md` yet, so it shows the wiring and not a real index; `make
      check-change` failed only on `check-doc-citations`, every miss a file a later
      section creates (its new `specification index` check passing); `make test`
      passed before the fixes and after them; `make check-packaging` passed.

Notes for the next session. The index's shape the check reads (the prefix line, the
entry and retired forms) is the format section 10's text and closeout's `index.md`
must use; the check's docstring states it. The fresh-context check's findings were
all fixed but one gap D15 does not ask for: an entry whose link points at another
requirement's heading than its id's passes. `openspec/README.md#capability-documentation-pattern`,
which the check, the `Makefile`, and the closeout skill cite, describes the index
only once section 10 writes it.

## 6. The graph diagram moved into its capability

Delivers the graph diagram in `openspec/specs/change-workflow/diagrams/`, still held
to the graph table (D12). Touches
`docs/development/diagrams/change-workflow-graph.drawio` and `.svg`,
`scripts/change_workflow/diagram.py`, `graph.py`,
`openspec/specs/change-workflow/architecture.md`, and
`scripts/tests/test_change_workflow_graph.py`.

- [x] 6.1 `git mv` the diagram's `.drawio` and `.svg` to
      `openspec/specs/change-workflow/diagrams/`; `diagram.py`, `graph.py`'s
      docstring, the graph test, and the companion's embed and source link name the
      new path (D12).
      Done; Git records both as renames. The companion's embed and source link are
      now `diagrams/…`, beside it, and the graph test reads that relative path from
      `diagram.DIAGRAMS`. Also moved: the two other permanent citations of the old
      path, `docs/agents/change-workflow.md` and the spec's Evidence. No rule lets
      the step make a directory, so the Write tool created the destination with a
      placeholder at the source's new path, which `git mv -f` then replaced with
      the moved file.
- [x] 6.2 Verification: `make change-graph` says the diagram draws the table; the
      graph tests, unit; `make check-change
      CHANGE=specify-change-workflow-and-engine`, failing only on the citations of
      files a later section creates. End-to-end: none, and none is owed.
      Evidence: `test_change_workflow_graph.py`, `test_change_workflow_cli.py`, and
      `test_change_workflow_command.py`, 229 passed — among them the graph test
      that runs `make change-graph` as a process on this checkout and finds it
      printing `openspec/specs/change-workflow/diagrams/change-workflow-graph.drawio
      draws the table.`, and the command run as `check graph`; `make change-graph`
      itself is denied to this step as a Bash call, so that test stands for the
      by-hand run. `make check-change` failed only on `check-doc-citations`, every
      miss a file a later section creates; `make test` passed; `make
      check-packaging` passed.

Notes for the next session. Section 7 renames the companion that embeds the diagram;
its links are relative (`diagrams/…`), so they hold through the rename, and the
graph test's `ARCHITECTURE` constant moves with it.

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
