# Tasks: extract the change workflow repository

The change has two halves (design D1). Sections 1–8 are the first half: the workflow
becomes a versioned wheel this repository runs installed from its own tree, and its
last section's triage makes it the candidate for the preliminary pull request to
`dev`. Sections 9–10 are the second half, started only once the coordinator's
evidence of the workflow's repository is recorded (D2). Suites run as `make
test-release-tooling TESTS=<files>`; the engine's tests are unit tests of a module's
functions, or library integration tests running the command as a subprocess over a
temporary Git repository, as `scripts/tests/test_change_workflow_*.py` already do
(`docs/guidance/engineering/test-levels.md`). No end-to-end scenario exercises the
workflow's tooling; none is owed by any section.

## 1. The wheel, its version, and the workflow's documents beside the engine

Delivers the `arkhai-change-workflow` wheel, built under the temporary packaging
exception, with `--version`, the log's `workflow` field, and every document of the
workflow's found in the installed distribution (D6, D8, D9, D12, D24; CW-5kl9,
CW-lm42, CW-d867). Touches `scripts/change-workflow-wheel/` (new),
`scripts/change_workflow/` (`cli.py`, `config.py`, `outcome.py`, `diagram.py`,
`log.py`, a new `documents.py`), `scripts/check_project_layout.py`, `AGENTS.md`, and
their tests.

- [x] 1.1 Write the wheel's project, `change-workflow-wheel/pyproject.toml`:
  distribution `arkhai-change-workflow`, version `0.1.0`, MIT, Hatchling, the
  `change-workflow` console entry point on `change_workflow.cli:main`, the package
  `scripts/change_workflow/`, and, as package data under it, the eleven workflow skills
  (`.agents/skills/change-*`, `.agents/skills/guidance-review`), `docs/guidance/workflow/`,
  `openspec/specs/change-workflow/` (`spec.md`, `index.md`, `README.md`, `diagrams/`),
  the handbook and the outcome schema (`change-workflow-handbook.md` under `docs/`,
  `change-outcome.schema.json` under `.agents/`), and
  `workflow.mk` (D8, D9). First prove that Hatchling builds it with these sources
  outside the project's directory (`uv build --wheel scripts/change-workflow-wheel`)
  and that the wheel lists every file; if it cannot, stop the section and report it,
  since the layout is D24's. Verify: the wheel's file list in the section's handoff.
  Done: Hatchling builds it with `bypass-selection = true` and a `force-include` table
  of paths relative to the project directory, each document under
  `change_workflow/data/`; `only-include` and `sources` refuse a path outside the
  project. The capability's `diagrams.md`, its own guidance, does not ship.
- [x] 1.2 Add `change_workflow/documents.py`: each document by its role
  (`specification`, `index`, `companion`, `diagrams`, `guidance`, `handbook`, `schema`,
  `fragment`, and the skills), found through `importlib.resources` when installed and
  at its tree path when the package runs from `scripts/` (D6, CW-lm42). Route
  `outcome.SCHEMA` and `diagram.DIAGRAMS` through it. Verify: unit tests for both
  modes, `test_change_workflow_documents.py` (new).
  Done: `documents.Distribution` gives each role's path, the skills, the version, and
  `described()` for `config --json`; `outcome.SCHEMA` and `diagram.DIAGRAMS` are
  absolute paths in the distribution, so `check graph` checks the distribution's
  diagram in any repository. Unit, `test_change_workflow_documents.py` (both modes):
  passed, with the graph, CLI, and outcome suites.
- [x] 1.3 `config --json` gains `workflow`: `version` and each document by role, no
  directory to look inside (D6, CW-lm42); `change-workflow --version` prints the
  version and reads no configuration (CW-5kl9). The version comes from the installed
  distribution's metadata, or the project file's when run from the tree. Verify:
  library integration cases in `test_change_workflow_config.py` and
  `test_change_workflow_cli.py`.
  Done: `--version` prints before any repository is looked for. Library integration:
  `config --json` names the eight documents; `--version` outside any repository and
  in one whose configuration `config` refuses prints the version: passed.
- [x] 1.4 Every line `log.py` appends carries `workflow`, the engine's version; no
  reader routes on it and `format` stays 2 (D12, CW-d867). Verify: unit cases in
  `test_change_workflow_log.py` (a line written under each of two versions), and the
  next-step suite unchanged (`test_change_next_step.py`).
  Done: `log.numbered` adds `workflow` beside `format` and refuses a writer setting
  it; a conversion's appended line carries it, the lines it rewrites do not. Unit,
  `test_change_workflow_log.py`: passed; `test_change_next_step.py` unchanged: passed.
- [x] 1.5 Declare the exception (D24): an `overrides` row in `AGENTS.md`, "Exceptions
  to shared guidance", against `packaging-python.md`'s "One import package per
  distribution", "Nothing remaps the package", and "Data files live inside the
  package", and `packaging-hatchling.md`'s "The wheel target names the one package",
  for `scripts/change-workflow-wheel/`, lasting until the second half removes it; and
  `scripts/check_project_layout.py` admitting that one project, naming the row. Verify:
  `test_check_project_layout.py` (the wheel admitted, any other remap still refused)
  and `make check-guidance`.
  Done: the admitted project skips only the wheel target's rule. Unit,
  `test_check_project_layout.py`: passed; `make check-guidance`, `make
  check-project-layout`, and the other packaging checks: passed. Both went in 9.6.
- [x] 1.6 Verify the section: build the wheel, install it into a temporary tool
  directory with `uv tool install`, and run the installed `change-workflow --version`
  and `config --json` in a temporary repository, each named document existing — a
  library integration test, `test_change_workflow_wheel.py` (new),
  skipped with its reason where `uv` is absent; plus the section's suites and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: `test_change_workflow_wheel.py` (external process) builds and installs the
  wheel into a temporary tool directory, holds its packaged files equal byte for byte
  to the tree's, and runs the installed `--version` and `config --json` in a
  repository holding no copy of the workflow: passed. `scripts/change-workflow run
  pre-commit`: `make validate-local`, the default checks, and strict OpenSpec
  validation passed; `make check-repository` failed only on the index check, on the
  fourteen ids the deltas add, which 8.2 and 10.2 index (D1).

Section 1 notes (handoff):

- The wheel packages `change_workflow/` with `workflow.mk`, and under
  `change_workflow/data/` the schema, the handbook, the workflow guidance, the
  specification set, each at its tree path so its relative links resolve installed
  (30 F2), and the eleven skills. A document added to the set needs a `force-include`
  line and a role in `documents`; the wheel test fails until both agree with the tree.
- Implementation review 30's triage, F2: the documents are packaged at their tree
  paths under `data/`, and the wheel test holds every relative link of the unpacked
  wheel's documents to the set.
- Outside the plan: a comment in `test_change_next_step.py` that
  `make check-comment-hygiene` refused, reworded.

## 2. The configuration's new shape, read

Delivers the committed range, the local configuration, and the engineering pointer as
the engine reads them, each checked when declared; their enforcement as required, and
the one-home rule, wait for section 4, after the orchestrator moves this repository's
fields (D4, D5, D6, D11, D13; CW-f8yy, CW-4pm4, CW-hu0z, CW-l7hn, CW-r6kd for the
local file, MCW-iqh1). Touches `scripts/change_workflow/` (`config.py`, `hook.py`,
`clone.py`, `scope.py`), `.gitignore`, `.agents/workflow.local.template.toml` (new),
and their tests.

- [x] 2.1 `config.py` reads `[workflow] version` before the rest of the file: a
  comma-separated subset of PEP 440 specifiers (`>=`, `<=`, `>`, `<`, `==`, `!=`, `~=`)
  over release numbers, parsed on the standard library; an installed version outside
  it refuses every subcommand that reads the configuration but `install` and
  `--version`, naming the version, the range, and the fix, and a newer table is then
  reported as the mismatch, not as unknown (D11, CW-f8yy). Verify: unit tests of the
  parser and the check, and library integration cases in
  `test_change_workflow_config.py` ("The installed version is too old").
  Done: `config.version_range` and `config.admits` parse and compare on the standard
  library, pre-releases and development releases sorting before their release as
  PEP 440 orders them; `config.check` reads the range right after parsing the TOML.
  Unit (parsing, admission across the operators, the check): passed. Library
  integration, "The installed version is too old" and a range admitting the engine:
  passed.
- [x] 2.2 The engine reads `.agents/workflow.local.toml` beside the committed file:
  `[guidance]`, `[models]`, and `[sandbox] writable.*`, the local writable paths
  extending the committed ones; `config --json` reports `local` (`file`, `exists`),
  each required local field it lacks as `missing`, distinct from `absent`, and
  succeeds with no local file, giving the committed fields and the distribution's in
  full (D5, CW-4pm4's CI scenarios). Verify: library integration cases in
  `test_change_workflow_config.py`.
  Done: `config.load` reads both files; a local key the committed file holds is
  refused naming `.agents/workflow.toml`; local writable paths extend the committed
  ones and are checked against the committed protected paths. Library integration:
  no local file (exit 0, every required local field `missing`), a local file read,
  seven malformed local files refused, a local writable path under a protected one
  refused: passed.
- [x] 2.3 The pointer (D4, CW-hu0z): `engineering = { path }` or `{ none = <reason> }`,
  one key; a missing or Markdown-less directory and an empty reason refused; a `load`
  entry that is or lies beneath the pointer refused; `config --json`'s
  `guidance.engineering` as `{"path"}`, `{"none"}`, or `null`. Verify: library
  integration cases in `test_change_workflow_config.py`, the scenarios of CW-hu0z.
  Done: an absolute `path` is refused, as CW-hu0z admits only the root's or `~`'s; an
  entry that is, lies beneath, or holds the pointer's directory is refused. Library
  integration: CW-hu0z's three scenarios, malformed pointers, and overlapping
  entries: passed.
- [x] 2.4 `config load <step>` and `config load common` print, in order, the
  pointer's Markdown files, the installed workflow guidance, then `load.common` and
  `load.<step>`, each once; the post-compaction hook re-reads what `config load
  common` prints (D6, CW-l7hn). Verify: library integration cases in
  `test_change_workflow_config.py` and `test_change_workflow_command.py`.
  Done: `Configuration.documents` gives that order, each once, and the hook reads the
  same list. Library integration, including the hook (`test_post_compaction_context.py`)
  and `config load common` run as a process in this checkout: passed.
- [x] 2.5 A change's clone links `.agents/workflow.local.toml` to the workspace's, as
  it links `.claude/settings.local.json` (CW-4pm4); the sandbox protects the local
  file beside `.agents/workflow.toml` (D13, CW-r6kd). Verify: `test_change_clone.py`
  and `test_change_workflow_scope.py`, `test_change_workflow_sandbox.py` (the write
  refused, under `needs_bwrap`).
  Done: `clone.LINKED` links both files, replacing an empty local file — the
  sandbox's empty form of an absent protected file — and refusing any other;
  `scope.PROTECTED` holds the local file. `test_change_clone.py`,
  `test_change_workflow_scope.py`, and `test_change_workflow_sandbox.py` under
  `needs_bwrap`, run, not skipped: passed.
- [x] 2.6 Add `.agents/workflow.local.toml` to `.gitignore`, and commit
  `.agents/workflow.local.template.toml`: the pointer at `docs/guidance/engineering/`
  and the models `.agents/workflow.toml` declares today, each with its comment (D5,
  MCW-iqh1). Verify: `git check-ignore .agents/workflow.local.toml` and the template
  read by 2.2's parser in a test.
  Done: the local file is ignored and the template not, both held by a test; the
  template is read whole beside the committed configuration: passed.
- [x] 2.7 Verify the section: its suites, and `scripts/change-workflow run
  pre-commit extract-change-workflow-repository` with this repository's configuration
  unchanged, which still passes.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites: passed. `scripts/change-workflow run pre-commit`, the
  configuration unchanged: `make validate-local`, the default checks, and strict
  OpenSpec validation passed; `make check-repository` failed only on the index check's
  ids 8.2 and 10.2 index (D1).

Section 2 notes (handoff):

- Outside the plan: `scripts/check_doc_citations.py` admits one absent path,
  `.agents/workflow.local.toml` (`LOCAL_ONLY`), which no branch holds, under an
  `overrides` row of `AGENTS.md`'s exceptions against `documentation.md`'s "Citations
  resolve"; `market-change-workflow`'s companion's row for the check says so.
- An absent protected path is created empty before a step launches, the local file
  among them, so `clone` and `install` treat an empty local file as absent.
- Test fixtures making a workspace ignore `.agents/workflow.local.toml` beside
  `.claude/settings.local.json`, as this repository's `.gitignore` does.

## 3. The installer, the version stamp, and what is installed protected

Delivers `change-workflow install` and the checks of installed skills, and the
sandbox's protection of them and of the installed engine (D8, D13, D21; CW-1rhd,
CW-sv3u, CW-d8de, CW-r6kd). Touches `scripts/change_workflow/` (a new `install.py`,
`skills.py`, `harness.py`, `claude_code.py`, `codex.py`, `scope.py`, `cli.py`) and
their tests.

- [x] 3.1 Each adapter names its harness's user skill directory (Claude Code's under
  `~/.claude`, Codex's under `~/.codex`) and protects it and the installer's manifest
  there; the engine protects its own installed distribution, found from its own
  location (D13, CW-r6kd). Verify: `test_change_workflow_scope.py`, and
  `test_change_workflow_sandbox.py` under `needs_bwrap` (a write to an installed skill
  and to the installed engine beneath a writable path both refused).
  Done: `Adapter.skills` names `~/.claude/skills/` and `~/.codex/skills/`, each among
  its adapter's protected paths; an installed engine's package and its `dist-info`
  are protected as the engine's, the tree's engine having none. Unit,
  `test_change_workflow_documents.py`, `test_change_workflow_scope.py`,
  `test_change_workflow_harness.py`: passed. External process,
  `test_change_workflow_sandbox.py` under `needs_bwrap`, run, not skipped: writes to an
  installed skill and to an installed package beneath a writable path fail: passed.
- [x] 3.2 `install.py`: write the version's skills into each user skill directory,
  stamp each with the version, and keep a manifest of the names it wrote; remove a
  retired skill the manifest names; refuse, writing nothing, a skill of a shipped name
  the manifest does not record; and, in a checkout, write `.agents/workflow.local.toml`
  where none exists, from `.agents/workflow.local.template.toml` when present and
  otherwise as a skeleton naming each required local field, never overwriting one
  (D8, CW-1rhd, CW-sv3u). Verify: library integration tests under a temporary `HOME`,
  `test_change_workflow_install.py` (new), every scenario of CW-1rhd and
  CW-sv3u.
  Done: the stamp is `.change-workflow-version` in each installed skill's directory
  and the manifest `.change-workflow-manifest.json` in each user skill directory; an
  empty local file is written as an absent one; `install` reads no configuration.
  Library integration, `test_change_workflow_install.py`: every scenario of CW-1rhd
  and CW-sv3u, an empty local file, the skeleton, nothing written outside a checkout:
  passed.
- [x] 3.3 Every subcommand but `install` and `--version` refuses when an installed
  skill's stamp differs from the engine's version, or a supported harness's user skill
  directory lacks a shipped skill or the manifest, naming what and `change-workflow
  install` (CW-1rhd). Verify: library integration cases in
  `test_change_workflow_install.py`.
  Done: `cli.main` refuses through `install.require_installed` before finding the
  repository; the check applies to an installed engine alone, since the engine run
  from its source tree has no installed skills to check. Library integration,
  `test_change_workflow_install.py` (CW-1rhd's scenarios, a missing manifest, `check
  skills` and `openspec` refusing over stale skills, the tree's engine checking
  nothing), and external process, `test_change_workflow_wheel.py`: passed.
- [x] 3.4 `check skills` holds both halves: the installed skills as 3.3 checks them,
  and, for skills the repository commits, one source under `.agents/skills/` linked
  from each harness's project skill directory, asking no project link of the
  workflow's own sources (D21, CW-d8de). Verify: `test_check_agent_skills.py`.
  Done: `skills.problems` asks no project link of the distribution's own skill
  names; the installed half is the check every subcommand makes first (3.3). Unit,
  `test_check_agent_skills.py`: passed; `make check-agent-skills`: passed.
- [x] 3.5 Verify the section: its suites, with the repository's existing
  `make check-agent-skills` still passing against the tracked links, which section 4
  removes; and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites and `make check-agent-skills`: passed.
  `scripts/change-workflow run pre-commit`: `make validate-local`, the default
  checks, and strict OpenSpec validation passed; `make check-repository` failed only
  on the index check's ids 8.2 and 10.2 index (D1).

Section 3 notes (handoff):

- Two judgments departing from a requirement's letter, settled by implementation
  review 30's triage (F3), which amended the delta and `spec.md` together: CW-1rhd's
  refusal and CW-d8de's installed half are of an installed engine, and CW-sv3u writes
  an empty local file as an absent one, with a scenario; no code changed.
- Deferred to section 8.3, the companion's "Current limits": a step whose writable
  paths hold the tool's environment can still add a `.pth` file or replace the entry
  script beside the protected package and `dist-info`.

## 4. The switch: this repository runs the installed workflow

Delivers this repository's configuration in its new shape, the shape enforced, the
command on the path, and the workflow's project skill links gone, so every session
runs the workflow installed from the tree (D4, D5, D7, D8, D11, D15, D18; CW-r3ka,
CW-f8yy, CW-4pm4, CW-hu0z, CW-dvz5, CW-d8de). Touches `.agents/workflow.toml`,
`.claude/settings.json`, `.claude/skills/`, `.codex/skills/`, the eleven workflow
skills, `scripts/change_workflow/` (`config.py`, `cli.py`, `workflow.mk`), the
`Makefile`, `.github/workflows/tests.yml`, `change-workflow-handbook.md`, and
their tests.

- [x] 4.1 The orchestrator's, on the owner's word, before the section's session: edit
  the protected `.agents/workflow.toml` — add `[workflow] version = ">=0.1, <0.2"`,
  remove `[models]`, and make `load.common` name `docs/guidance/repository/` in place
  of `docs/guidance/` — and `.claude/settings.json`'s post-compaction hook to run
  `change-workflow hook post-compaction`; then install the tree's wheel and run
  `change-workflow install` in the workspace, writing the user skill directories and
  `.agents/workflow.local.toml` from the template (D5, D8, D11). The session commits
  both protected files with its section.
  Done by the orchestrator on the owner's word, the edits committed with the section;
  by the owner's direction the install ran in this change's clone only, its local
  file its own, written from the template.
- [x] 4.2 Enforce the shape: `[workflow] version` and `[guidance] engineering`
  required; a field in the wrong file refused, naming the file it belongs in; with no
  local file, `start` refuses, naming the missing field and `change-workflow install`,
  while `check config` and `config --json` report and exit 0 (D4, D5, D11; CW-f8yy,
  CW-4pm4, CW-hu0z). Verify: library integration cases in
  `test_change_workflow_config.py` and `test_change_workflow_cli_steps.py` ("Models are
  committed", "A step starts with no local configuration", "No range is declared").
  Done: a committed file declaring no `workflow.version` is refused; `[models]` and
  `[guidance]` in the committed file are refused naming the local file; a missing
  field is named with its file, a local one with `change-workflow install`; the
  pointer is required by every step, the orchestrating session, the review, `config
  load`, and the post-compaction hook; `check config` prints a `MISSING:` line and
  exits 0. Library integration, `test_change_workflow_config.py` and
  `test_change_workflow_cli_steps.py` (the three named scenarios, CI with no local
  file), with `test_change_workflow_cli.py`, `test_change_workflow_review.py`, and
  `test_post_compaction_context.py`: passed. The tests of this repository's own
  configuration read it as its template's install leaves it (`as_installed`).
- [x] 4.3 `change-workflow fragment` prints the installed `workflow.mk`'s path, and the
  fragment's default becomes `CHANGE_WORKFLOW ?= change-workflow`; this repository's
  `Makefile` keeps including the in-tree fragment and gains `make install-workflow`,
  installing the tree's wheel with `uv tool install --force` and running
  `change-workflow install` (D8, D15, CW-dvz5). Verify: `test_change_workflow_cli.py`,
  `test_make_change_completion.py`, and `make install-workflow` in the section's
  handoff.
  Done: `fragment` prints the distribution's fragment and reads no configuration;
  `make install-workflow` ran `uv tool install --force --reinstall` (an edit keeps the
  version, which uv would otherwise keep) then `change-workflow install`. Library
  integration and external process, `test_change_workflow_cli.py` and
  `test_change_workflow_wheel.py` (CW-dvz5's scenario on the installed command), and
  `test_make_change_completion.py`: passed. `make install-workflow` under a temporary
  `HOME` and tool directory installed 0.1.0 and wrote the eleven stamped skills into
  each user skill directory. Both went in 9.4.
- [x] 4.4 The eleven workflow skills, the handbook, and the fragment invoke
  `change-workflow …` in place of `scripts/change-workflow …`, which stays in the tree
  through this half (D8, CW-r3ka); remove the `change-*` and `guidance-review` links
  from `.claude/skills/` and `.codex/skills/`, the skills' sources staying under
  `.agents/skills/` for the wheel (D8, D18, CW-d8de). Verify:
  `test_change_workflow_assumptions.py` (the skills' targets and paths), `make
  check-agent-skills`, and `change-workflow check skills` after the orchestrator's
  reinstall.
  Done: the skills, the handbook, and the engine's own messages name
  `change-workflow`; the 22 links went, OpenSpec's six stay; `check skills` refuses a
  project skill entry of a workflow skill's name, link or copy (CW-d8de). Unit and
  integration, `test_change_workflow_assumptions.py`, `test_check_agent_skills.py`:
  passed; `make check-agent-skills`: passed.
- [x] 4.5 `tests.yml`'s test job installs the tree's wheel and runs `change-workflow
  install` before `make`, so the scripts' suites and every engine command CI runs meet
  installed skills (D8). Verify: the job's definition in the handoff.
  Done: the `test-deployment-packaging` entry installed the wheel from the tree and
  ran `change-workflow install` outside the checkout, writing no local file. Unit,
  `test_tests_workflow.py`: passed. Section 9.4 removed the step (D26).
- [x] 4.6 Verify the section: its suites; `scripts/change-workflow run pre-commit
  extract-change-workflow-repository` and `change-workflow config load implement`
  against the edited configuration; and the handoff naming that the orchestrator
  reinstalls (`make install-workflow`) before the next session, since the skills
  changed.
  End-to-end: none exercises the workflow's tooling; none owed.
  Shown by validation (ci tests.yml) until section 9 removed the job's install, by
  validations 49 (`58b902685`) and 51 (`3b663fc5d`): the
  `test · test-deployment-packaging` job, run under `SANDBOX_REQUIRED=1` with
  `PYTEST_ADDOPTS=-rfEs`, its log showing the wheel installed from the tree,
  `change-workflow install` run, and the change workflow's
  suites passed with no sandbox test skipped on the bubblewrap probe and one test
  skipped in all: the Codex sandbox test, its skip-summary line naming
  `test_change_workflow_sandbox.py` and the reason `Codex is not
  installed here`, since the runner has no Codex — the local kind runs it (44 F1).
  Section 9's owed line (9.8) is the job's current observation (69 F1).
  Done: the section's suites: passed. `scripts/change-workflow run pre-commit`
  against the edited configuration: `make validate-local`, the default checks, and
  strict OpenSpec validation passed; `make check-repository` failed only on the index
  check's ids 8.2 and 10.2 index (D1). `config load implement`, installed and from
  the tree, printed the pointer's guidance, then the workflow's, then `load.common`,
  each once.

Section 4 notes (handoff):

- Implementation review 44's triage, 44 F1: the owed line above is narrowed to the
  bubblewrap probe's tests, admitting the Codex test's skip on a runner with no
  Codex, and the packaging job set `PYTEST_ADDOPTS=-rfEs` so its summary names each
  skip while still listing the failures `scripts/ci_evidence.py` reads. Unit,
  `test_tests_workflow.py`, failing at the earlier commit and passing here.
- Implementation review 30's triage, 33 R1 (D25, outside the plan): with the project
  links gone, unattended Claude Code steps ran without the workflow's skills; the
  adapter adds `--add-dir` of the home directory, and a run whose harness did not
  load a shipped skill is stopped before its first turn. CW-d8de gains the stop and
  its scenario. Evidence under section 8's triage note.
- Judgments reading a requirement's letter: an interactive `start design` names the
  pointer alone, not models it does not use (CW-4pm4); the pointer is required by
  `config load` and the post-compaction hook too, since interactive sessions never
  pass through `start` (CW-hu0z); "No range is declared" is read for a committed file
  (CW-f8yy); `fragment` refuses over stale skills like every subcommand (CW-1rhd).
- Outside the plan: `check skills` refuses a project entry of a workflow skill's
  name; documents the switch made false corrected (`AGENTS.md`, `openspec/README.md`,
  `market-change-workflow`'s companion, the workflow guidance, the handbook); the
  graph target's test runs the tree's command; the repository's own suites write the
  range as a literal rather than importing the workflow's fixtures.
- Left for later sections and done there: the `[openspec]` comment (9.1),
  `market-change-workflow`'s scenarios naming the tree's command (10.2), the
  specification set (section 8), the orchestrating skill's module citations
  (section 5), the handbook's installing procedure (7.3).

## 5. Citations by section and requirement id; unique engineering headings

Delivers the skills and the workflow's guidance citing engineering guidance by
section name, the workflow's guidance by section, and its specification by id, with
`check config`'s reports and the engineering guidance's repeated headings made unique
(D4, D6; CW-7x0z, CW-n8tr, CW-d2rw). Touches the eleven workflow skills,
`docs/guidance/workflow/*.md`, `docs/guidance/engineering/` (`integration-tests.md`,
`system-tests.md`, `contract-fixtures.md`, `test-levels.md`, `testing-python.md`)
and every citation of the renamed headings, `change_workflow/config.py`,
`scripts/check_guidance.py`, and their tests.

- [x] 5.1 Make the three repeated headings unique — "Integration tests", "System
  tests", "Contract fixtures", each a file's title and a section of another — and
  re-point every citation of a renamed anchor (D4, 15 F5). Verify: `make
  check-guidance` (the anchor check) and no heading repeated beneath
  `docs/guidance/engineering/`, held by a unit test of 5.3's resolver over this
  repository's guidance.
  Done: `test-levels.md`'s level sections keep their names; the files' titles became
  "Application integration tests" (`integration-tests.md`) and "System test
  scenarios" (`system-tests.md`), and `testing-python.md`'s section "Contract fixture
  modules", its one citation, in `docs/guidance/repository/test-placement.md`,
  re-pointed. Content check, `test_check_guidance.py`: no heading beneath
  `docs/guidance/engineering/` heads two sections; library integration, the same
  file: the workflow's `check config` over this repository's engineering guidance
  reports no cited section unresolved or ambiguous; `make check-guidance`: passed.
- [x] 5.2 The skills cite engineering guidance by section name, never a path or file
  name, the workflow's guidance by section, and the workflow's specification by
  requirement id; the workflow's guidance names engineering guidance in prose by
  section, with no link (D4, D6; CW-7x0z, CW-n8tr, CW-d2rw). Verify:
  `test_change_workflow_assumptions.py`, extended to fail on any path into
  `docs/guidance/` in a skill ("A skill names an engineering guidance file").
  Done: every path into `docs/guidance/` in the eleven skills became a citation by
  section name in the one form the engine parses (`the engineering guidance's section
  "<name>"`), eleven engineering sections and fourteen of the workflow's; the
  orchestrating skill cites the graph as CW-ak1z and CW-66kx; the workflow
  guidance's seven links to engineering guidance became section names in prose.
  `test_change_workflow_assumptions.py` ("A skill names an engineering guidance
  file", and no bare guidance file name in a skill's code span): passed.
- [x] 5.3 `check config` reports each engineering section a shipped skill cites that
  no file beneath the pointer heads, and each that several sections head, naming the
  files, exiting 0 for both (CW-7x0z). Verify: library integration cases in
  `test_change_workflow_config.py` ("A user's guidance lacks a cited section", "A cited
  section name repeats").
  Done: a new `sections.py` reads cited section names and a directory's headings;
  `check config` prints `UNRESOLVED:` and `AMBIGUOUS:` lines, naming files and the
  citing skills, exiting 0, and nothing while the pointer applies none. Unit,
  `test_change_workflow_sections.py`; library integration,
  `test_change_workflow_config.py` (both scenarios, and a pointer applying none):
  passed.
- [x] 5.4 The guidance check refuses a link from workflow guidance to engineering
  guidance (CW-d2rw, MCW-c4ek's link rule). Verify: `test_check_guidance.py` and `make
  check-guidance`.
  Done: `check_guidance.py` refuses such a link, naming both files; its lines and
  `market-change-workflow`'s companion say so. Unit, `test_check_guidance.py`; `make
  check-guidance`: passed.
- [x] 5.5 The distribution's test fails on a skill citing a section of the workflow's
  guidance that the installed guidance does not head (CW-lm42). Verify:
  `test_change_workflow_citations.py` (new, under `scripts/tests/`); its requirement-id half is
  section 8's.
  Done: `test_change_workflow_citations.py` holds every cited workflow-guidance
  section to exactly one heading of the shipped guidance, and CW-lm42's "A skill
  cites a section the guidance lost" fails naming both. Unit: passed.
- [x] 5.6 Verify the section: its suites, `make check-guidance`, and `scripts/change-workflow
  run pre-commit extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites, `make check-guidance`, `make check-doc-citations
  CHANGE=extract-change-workflow-repository`, and `make check-comment-hygiene`:
  passed. `scripts/change-workflow run pre-commit`: `make validate-local` passed
  (every suite); the default checks and strict OpenSpec validation passed; `make
  check-repository` failed only on `check-spec-index`, the fourteen ids 8.2 and 10.2
  index.

Section 5 notes (handoff):

- The citation form `the engineering guidance's section "<name>"` (or `sections
  "<a>" and "<b>"`, and the same with `workflow guidance's`) is the interface
  `sections.py` parses; a citation written otherwise is neither reported nor held.
- Beyond CW-7x0z's letter, `check config` also reads the engineering sections the
  workflow's own guidance cites, which ships with the skills and cites them the same
  way.
- Outside the plan: the orchestrating skill cites its own routing sections rather
  than `change_workflow/next_step.py` for the computation's result, which no
  requirement words; the workflow guidance's README restates the layer rule as
  CW-d2rw has it.

## 6. Two default checks moved into the engine, and the roles as structured output

Delivers `spec-index` and `decisions` as default checks, the delta paths in `check
spec-index --json`, and `roles` in `config --json`, read by this repository's
assumptions test (D10, D14; CW-c8lw, CW-368t, CW-ora1, MCW-5tgp). Touches
`scripts/change_workflow/` (new `spec_index.py` and `decisions.py`, `config.py`,
`hooks.py`, `cli.py`), `check_spec_index.py` and `check_decision_destinations.py`
under `scripts/`, which leave it, `scripts/check_doc_citations.py`,
`scripts/check_change.py`, the `Makefile`, `test_change_workflow_assumptions.py`,
and their tests.

- [x] 6.1 The orchestrator's, on the owner's word, before the section's session:
  `make install-workflow`, so the session runs the skills section 5 rewrote.
  Done by the orchestrator on the owner's word, in this change's clone.
- [x] 6.2 Move the specification index check and the decision destinations check into
  the engine as `spec-index` and `decisions`, run by `pre-commit` and `check change`
  before the declared commands and turned off only by name; `make check-repository`
  stops running them, and `make check-spec-index` and `make
  check-decision-destinations` call the engine; the two scripts go (D10, CW-c8lw).
  Verify: `test_check_spec_index.py` and `test_check_decision_destinations.py` moved to
  the engine's command, `test_change_workflow_hooks.py` (six default checks, "A
  decision names no destination"), `test_check_change.py`.
  Done: the scripts moved with `git mv` to the engine's `spec_index.py` and
  `decisions.py`, behind `check spec-index [<change>] [--json]` and `check decisions
  <change>`; the default checks are `index`, `tasks`, `skills`, `spec-index`,
  `decisions`, `openspec`; an archived change's deltas count for nothing and its
  design is read from the archive. `check_change.py` runs neither; the two make
  targets call `$(CHANGE_WORKFLOW) check …`. Unit and library integration,
  `test_change_workflow_spec_index.py`, `test_change_workflow_decisions.py`,
  `test_change_workflow_hooks.py` (the six in order, one disabled by name skipped,
  CW-c8lw's scenario naming D7), `test_check_change.py`,
  `test_check_comment_hygiene.py`: passed.
- [x] 6.3 `check spec-index <change> --json` reports the specification paths the
  change's deltas create, and `scripts/check_doc_citations.py` reads them in place of
  importing a delta reader (D10, CW-368t). Verify: `test_check_doc_citations.py`
  ("A citation check meets a specification the change creates").
  Done: `--json` prints `change`, `result`, `problems`, and `created`, exiting as the
  check does; `workflow_command.created_specifications` reads `created`, and
  `check_doc_citations.py` imports no delta reader. Library integration,
  `test_check_doc_citations.py` (CW-368t's scenario), `test_workflow_command.py`,
  `test_change_workflow_spec_index.py`: passed.
- [x] 6.4 `config --json` lists `roles`, each role by name with the configuration
  fields that provide it; the distribution's test holds the companion's roles table to
  it; `test_change_workflow_assumptions.py` reads the roles from `config --json` and the
  fragment from `change-workflow fragment`, with no local configuration (D14; CW-ora1,
  MCW-5tgp). Verify: `test_change_workflow_config.py` and
  `test_change_workflow_assumptions.py` ("The workflow adds a role").
  Done: `config.ROLES`, seventeen roles in the companion's order, each `{"role",
  "fields"}`; three of the companion's provisions reworded to name their fields.
  Content check and unit, `test_change_workflow_config.py` (the companion's table
  held to `roles`; every field a configuration key); library integration, `roles` in
  full with no local file; `test_change_workflow_assumptions.py` reading roles and
  fragment through the command in a checkout with no configuration, and "The
  workflow adds a role" (MCW-5tgp): passed.
- [x] 6.5 Verify the section: its suites, and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`, the two checks now run by the engine.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites: passed. `scripts/change-workflow run pre-commit`: `make
  validate-local` passed (every suite); of the six default checks all passed but
  `spec-index`, on the fourteen ids 8.2 and 10.2 index; `make check-repository`
  passed.

Section 6 notes (handoff):

- `check spec-index --json` is structured output a repository script relies on
  (`workflow_command.created_specifications`); 8.3 listed it in "Interfaces are
  tiered".
- Outside the plan: documents this section made false were corrected —
  `openspec/README.md`'s "The index check", the workflow guidance's closeout
  "Promotion" paragraph, change-implement's and change-closeout's lists of what
  `pre-commit` runs, and the comment-hygiene exemption's path.
  `pass-checks-at-every-commit`'s proposal, citing the removed script, was left to
  that change's design.
- Deferred: the engine reads fenced blocks three ways (`decisions` as CommonMark,
  `spec_index` and `sections` toggling on any fence), recorded as unowned work and
  carried to the workflow's repository (9.2).

## 7. The workflow's documents self-contained, and the move's procedure

Delivers documents the coordinator can lift whole, the handbook's procedures for
installing, crossing, and the move, and the workflow's tests runnable without this
repository's other files (D6, D7, D8, D16, D17, D18). Touches
the capability's companion (`README.md` under `openspec/specs/change-workflow/`),
`docs/guidance/workflow/*.md`,
`change-workflow-handbook.md`, and the workflow's tests and fixtures under
`scripts/tests/`.

- [x] 7.1 The workflow's documents link only within their own set: the companion's
  four links to `market-change-workflow` become neutral text about an adopting
  repository's own capability, and no workflow document links to this repository's
  documents (D6). Verify: a unit test over the wheel's document set,
  `test_change_workflow_citations.py`, failing on a relative link leaving it.
  Done: the companion's four links say an adopting repository states its own
  provisions, kinds, and resources; "Current limits" link no change of this
  repository; the handbook names the change index as a path. Unit,
  `test_change_workflow_citations.py`: every relative link of a shipped document
  resolves within the set, a link leaving it named with its line: passed; it fails
  at the section's base.
- [x] 7.2 The workflow's tests and fixtures name the files they need from the
  workflow's own set, and run with only the paths section 7.3 lists present (D16, D17).
  Verify: the workflow's suites run from a temporary checkout holding only those paths,
  recorded in the handoff.
  Done: the workflow's tests of this repository's own provisions (its configuration
  and template, Makefile targets, settings' hook) moved to a repository test,
  `test_market_change_workflow.py`, reaching the engine only through the command
  (CW-r3ka); the workflow's suites keep only their fixtures. The lifted checkout —
  exactly the handbook's paths copied into a fresh repository, run with `uv run
  --no-project --with pytest pytest scripts/tests`: 2,209 passed, none skipped (48
  failed before the move, each reading this repository's files).
  `test_market_change_workflow.py` and the edited workflow suites: passed.
- [x] 7.3 The handbook gains: installing the workflow and the local configuration;
  that one version is installed per machine, managed like any tool a repository pins,
  each repository declaring its range (D7, D8, the owner's principle); when an open
  change crosses to the installed workflow (D18); and the procedure for the move —
  the exact path list the coordinator lifts with `git filter-repo`, keeping paths, the
  wheel's project file to rename to the new repository's root, and the test for which
  settings are local, for the workflow repository's own repository guidance (D5, D16,
  D17). Verify: the path list matches what the wheel packages plus its tests, held by
  `test_change_workflow_wheel.py`.
  Done: the handbook opens with "Installing the workflow" and "When an open change
  crosses to the installed workflow", and closes with "Moving the workflow to its own
  repository", its 67 paths in one fenced block; the capability's `diagrams.md`,
  repository guidance, is not lifted. Unit, `test_change_workflow_wheel.py` (the list
  is the `force-include` sources, the project, the command, and every test importing
  the engine or its fixtures, none importing a repository script): passed; it fails
  at the section's base.
- [x] 7.4 Verify the section: its suites and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites: passed. `scripts/change-workflow run pre-commit`: `make
  validate-local` passed (every suite); the default checks passed but `spec-index`,
  on the fourteen ids 8.2 and 10.2 index; `make check-repository` passed.

Section 7 notes (handoff):

- The lifted checkout is built outside `/tmp`, whose sandbox-private copy hides it
  from the sandbox tests; the lifted suites need pytest alone.
- Outside the plan: "Current limits" no longer names the open change owning a limit,
  the change index holding owners, and `change-workflow convert` replaces the tree's
  command there.

## 8. The specification, its companion, and its diagrams current for the release

Delivers the `change-workflow` delta applied to the permanent specification with its
index entries, the companion's promotions and its diagrams redrawn, and the
distribution's test of cited requirement ids, so the release carries its own
documents (D20, D23; every requirement of the `change-workflow` delta; CW-lm42).
Touches `openspec/specs/change-workflow/` (`spec.md`, `index.md`, `README.md`,
`diagrams/`), and `test_change_workflow_citations.py`.

- [x] 8.1 Apply the `change-workflow` delta to its `spec.md` under
  `openspec/specs/change-workflow/` by hand: the twelve added requirements (CW-5kl9, CW-lm42, CW-f8yy, CW-1rhd, CW-sv3u,
  CW-4pm4, CW-hu0z, CW-7x0z, CW-d867, CW-dvz5, CW-ora1, CW-368t) and the eight modified
  (CW-r3ka, CW-d8de, CW-f3qk, CW-c8lw, CW-l7hn, CW-d2rw, CW-n8tr, CW-r6kd), each as the
  delta words it (D23). Verify: `make check-spec-index` and a diff of each requirement
  against its delta in the handoff.
  Done: all twenty applied to `spec.md`, each identical to its delta block for block;
  `openspec validate --specs --strict`: 28 passed; `change-workflow` agrees with its
  index once 8.2's entries are written. Requirements the delta does not touch still
  name `scripts/change-workflow` in their scenarios, carried to the workflow's
  repository (9.2).
- [x] 8.2 Write `index.md`'s entries as promotion would: under 4, "The command"
  CW-dvz5, "Hooks" CW-368t, "The log and its format" CW-d867, "Skills from one source"
  CW-1rhd; under 5, "The engine's interfaces" CW-5kl9 and CW-lm42, "Compatibility"
  CW-f8yy, "A repository's configuration" CW-sv3u and CW-4pm4, "The repository's
  guidance" CW-hu0z and CW-7x0z, "What an adopting repository provides" CW-ora1; each
  modified requirement's summary revised where it no longer holds; no id retired (D23).
  Verify: `make check-spec-index CHANGE=extract-change-workflow-repository`.
  Done: the twelve entries written under those groups, all eight modified summaries
  revised, no id retired; `change-workflow`'s entries pass the index check.
- [x] 8.3 Promote to the companion, `README.md` under
  `openspec/specs/change-workflow/`, each destination the proposal's knowledge to promote names there, before the release is
  cut (D23): "The public surface" (D1, D7), "The repository's guidance is layered"
  (D3, D4, and the principles that the workflow relies on sections and that users
  bring their own engineering guidance), "A repository's configuration" (D4, D5, D6,
  D10, D11), "Interfaces are tiered" (D4's provisional section names, `install`,
  `fragment`, `--version`, `config --json`'s fields), "Leaf skills from one source"
  (D6, D21), "The command and its tiers" (D8, D9, D15), "Its parts" (the new modules),
  "A change's records carry one format version" (D12), "Restrictions bind unattended
  runs only" and "Current limits" (D13), "What an adopting repository provides" (D14),
  and the sentence of "The log, its format, and the conversion" on each branch running
  its own tooling withdrawn (D7). Verify: `make check-doc-citations
  CHANGE=extract-change-workflow-repository` and `make check-guidance`.
  Done: each named section of the companion written as listed — the distribution and
  one installed version per machine (D1, D7), the tier table's new commands and
  fields with the section names provisional (D4), the pointer and the two principles
  (D3, D4), the committed and local split, the shipped documents, `[workflow]` and
  `[guidance]` (D4, D5, D6, D11), the six default checks (D10), citations by section
  and id and both halves of `check skills` (D6, D21), the wheel, names, licence,
  `install`, and `fragment` (D8, D9, D15), the new modules, `workflow` on every log
  line (D12), what is installed protected and the narrowed limits (D13), the
  engine's assumptions table (D14), and the withdrawn sentence (D7); `spec.md`'s
  Purpose and Evidence name no document of this repository's. `make
  check-doc-citations CHANGE=extract-change-workflow-repository` and `make
  check-guidance`: passed.
- [x] 8.4 Redraw `change-workflow-engine-parts.drawio` and the step run's diagram, and
  export both SVGs: the evidence modules, the actions and hooks around a step, the
  configuration's validation entries as entries, not parts, and the parts this change
  adds (D20). Verify: `change-workflow check graph` and the SVGs open in the
  companion.
  Done: both drawn anew, each `.drawio` source and its SVG emitted from one layout by
  a script kept outside the repository; the source's edges carry fixed points, and
  the companion says the SVG is drawn from the same layout. The engine's parts draw
  every module with what each reads and writes, validation's evidence kinds as
  configuration entries; the step run draws `start`'s range and skills checks, the
  before- and after-hooks, the sandboxed session, the checks after it, and the log
  line. `change-workflow check graph`: passed; both SVGs embedded.
- [x] 8.5 The distribution's test fails on a `CW-` id a skill or the workflow's
  guidance cites that `workflow.specification` does not hold (CW-lm42). Verify:
  `test_change_workflow_citations.py`.
  Done: the test fails, naming text and id, on a cited `CW-` id no requirement
  carries; it found the guidance's example id `CW-a8tf`, now of a capability
  prefixed `EX`. Unit: passed.
- [x] 8.6 Verify the first half whole: `make test-release-tooling`, `make
  check-change CHANGE=extract-change-workflow-repository`, the wheel rebuilt and
  installed from the tree with `make install-workflow` and `change-workflow config
  --json` naming every document, and the handoff stating that the first half is
  complete on its own for the preliminary pull request (D1).
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: `scripts/change-workflow run pre-commit`: `make validate-local` passed (every
  suite); the default checks passed but `spec-index`, on MCW-9k0c and MCW-iqh1 alone;
  `make check-repository` passed. `make install-workflow` under a temporary `HOME`
  and tool directory installed 0.1.0 from the tree and wrote its 11 skills; its
  `config --json` named all eight documents inside the tool directory. The first
  half was complete on its own for the preliminary pull request, the named index
  check failing only on the two `market-change-workflow` ids section 10 indexes.

Section 8 notes (handoff):

- Implementation review 30's triage (30 F1–F3, 32 O1–O2, 33 R1): the fixes are
  recorded under sections 1, 3, and 4 and in D1, D24, and D25. R1's cause was
  checked on Claude Code 2.1.331: no workflow skill loaded with `--setting-sources
  project`, all eleven with `--add-dir` of the home directory. Evidence:
  `test_change_workflow_stream.py`, `test_change_workflow_harness.py`,
  `test_change_workflow_review.py`, `test_change_workflow_wheel.py`, and the
  citations, documents, and wrapper suites: passed, the new tests failing at the
  prior commit; D25 gained its "Knowledge to promote" bullet.
- The judgments of sections 3 and 4 — CW-1rhd and CW-d8de of an installed engine,
  CW-4pm4's step naming its models only when unattended, CW-sv3u's empty local file
  — are in the permanent specification as the delta words them.
- Outside the delta: the Terms the new requirements rely on were written into
  `spec.md`'s "Terms" by hand.

## 9. The gate, and the switch to the released workflow

Replanned against the design as amended by the owner's return to design of
2026-11-25 and design review 58's triage: the gate checks the installed wheel's
digest, CI installs no workflow, and the switch removes the six moved workflow changes
and this repository's tests of its workflow wiring.

Delivers this repository on the coordinator's release, `arkhai-change-workflow` 0.1.0,
with no copy of the workflow in its tree, building, testing, and releasing without the
workflow installed (D2, D7, D11, D14, D15, D19, D24, D26; MCW-9k0c, MCW-w7nb). Touches
the `Makefile`, `.github/workflows/tests.yml`, `scripts/tests/test_tests_workflow.py`,
`scripts/tests/conftest.py`, `scripts/workflow_command.py`,
`scripts/check_guidance.py` and its test, `scripts/check_comment_hygiene.py`,
`scripts/check_project_layout.py` and its test, `AGENTS.md`'s layer table and
exceptions table, `openspec/specs/README.md`, and `openspec/changes/README.md`; and
removes every path the handbook's procedure for the move lists (`scripts/change-workflow`,
`scripts/change_workflow/`, `scripts/change-workflow-wheel/`, the workflow's tests and
fixtures under `scripts/tests/`, `.agents/skills/change-*`,
`.agents/skills/guidance-review`, the outcome schema under `.agents/`,
`docs/guidance/workflow/`, `openspec/specs/change-workflow/`, and the handbook under
`docs/`), `test_change_workflow_assumptions.py` and
`test_market_change_workflow.py` under `scripts/tests/`, and the six moved changes' directories
under `openspec/changes/`. The workflow is reached throughout as the installed
`change-workflow`; nothing here names the workflow's repository or links to it (D2, D6).

- [x] 9.1 The orchestrator's, on the owner's word, before the section's session (D2,
  D14):
  - download the release's wheel, `arkhai_change_workflow-0.1.0-py3-none-any.whl`,
    from the release page of the workflow's repository to a path outside the tree;
    check its SHA-256 is
    `3434aceddbb56ac9763ac32a17c9fd25ce37e8e588beeaee242e5d328eb2d71f`; install it
    from that file with `uv tool install --force <file>`; and run `change-workflow
    install`. The range stays `>=0.1, <0.2` (D11), so no committed file changes;
  - ask the coordinator to confirm that the two unowned rows this change found about
    the workflow's own engine and specification — the engine reading Markdown's fenced
    blocks three ways, and the specification naming `scripts/change-workflow` in
    scenarios its delta did not modify — were carried to the workflow's repository,
    and deliver to the coordinator D14's requests: a test of its own that the skills
    name no adopting repository's make target or path, rewritten as they move to
    calling its command, and the rewording of its companion's "What an adopting
    repository provides" sentence on an adopter's test of its provisions, as a check
    an adopter may keep;
  - correct the protected `.agents/workflow.toml`'s comment on `[openspec]`, which
    names `scripts/change-workflow openspec`, to `change-workflow openspec`; the
    session commits it with its section;
  - record each with `change-workflow note extract-change-workflow-repository
    orchestrator --by owner`, naming nothing of the workflow's repository but the
    release page by role.

  Done by the orchestrator on the owner's word (log seq 89–92, and 96 for the
  reinstall from a file the step can read); the `[openspec]` comment's edit was in
  the worktree and is committed with this section.
- [x] 9.2 Decision gate (D2): record in this task's note the coordinator's evidence —
  the distribution and its version, `arkhai-change-workflow` 0.1.0; the tag,
  `v0.1.0`; the artifact, `arkhai_change_workflow-0.1.0-py3-none-any.whl` with
  SHA-256 `3434aceddbb56ac9763ac32a17c9fd25ce37e8e588beeaee242e5d328eb2d71f`, on the
  release page of the workflow's repository and in the dev artifact repository; and,
  from 9.1's log lines, the coordinator's confirmation that the two rows were carried
  and that D14's requests were delivered. Before writing anything else, check: the
  log holds 9.1's lines; `change-workflow --version` prints `0.1.0`, within the
  committed range; uv's receipt for the tool (`uv-receipt.toml` under `uv tool dir`'s
  `arkhai-change-workflow`) names a wheel file, not `scripts/change-workflow-wheel`,
  of the recorded file name, whose SHA-256 is the recorded digest — reading that
  file's path and writing it nowhere; and `change-workflow check skills` passes. End
  the session `stopped`, naming what is missing, when any of it is absent or any check
  fails. No URL, repository name, commit, registry location, or install guide enters
  the note.
  Done: the coordinator's evidence — `arkhai-change-workflow` 0.1.0, tag `v0.1.0`;
  the artifact `arkhai_change_workflow-0.1.0-py3-none-any.whl`, SHA-256
  `3434aceddbb56ac9763ac32a17c9fd25ce37e8e588beeaee242e5d328eb2d71f`, on the
  release page of the workflow's repository and in the dev artifact repository. The
  log's 9.1 lines (seq 89–92): the release's wheel downloaded from the release page,
  its digest checked, installed from the file with `uv tool install --force`, and
  `change-workflow install` run, on the owner's word; the coordinator's confirmation
  (seq 92) that both unowned rows — the engine reading fenced blocks three ways, and
  the unmodified scenarios naming `scripts/change-workflow` — are carried to the
  workflow's repository, and its acceptance of D14's two requests; the
  `[openspec]` comment corrected, committed with this section. Checked by the
  session: `change-workflow --version` prints `0.1.0`, within `>=0.1, <0.2`; uv's
  receipt names a wheel file of the recorded name, not the tree's wheel project,
  whose SHA-256 is the recorded digest; `change-workflow check skills` passes. A
  first check stopped (seq 95) on a receipt naming a file the step's private `/tmp`
  could not read; the owner reinstalled from a directory under the home directory
  (seq 96), and the checks then passed.
- [x] 9.3 Remove the workflow's copy from the tree: every path the handbook's procedure
  for the move lists (read it before removing it, or in the installed release's
  handbook, `change-workflow config --json`'s `workflow.handbook`), with the
  fixtures and the sandbox fixture of `scripts/tests/conftest.py` only the removed
  tests use, and `scripts/check_comment_hygiene.py`'s exemptions for files of
  `scripts/change_workflow/`. `scripts/workflow_command.py`'s `COMMAND` becomes the
  installed `change-workflow` on the path, its docstring following, and
  `scripts/tests/test_workflow_command.py` keeps its stand-in command. Delete
  `test_change_workflow_assumptions.py` and
  `test_market_change_workflow.py` (D14). Drop `change-workflow`'s row
  from `openspec/specs/README.md` (MCW-9k0c). Verify: `make check-capability-index`,
  `make check-comment-hygiene`, and `test_workflow_command.py` (unit).
  Done: the procedure's 66 paths removed, and with them the whole of
  `openspec/specs/change-workflow/`, its `diagrams.md` guidance among them;
  `conftest.py` keeps only the path insertion and the fixture that drops the step's
  marker, `CHANGE_WORKFLOW_UNATTENDED`, named literally. Comment hygiene exempts
  nothing. `workflow_command.COMMAND` is `change-workflow`, found on the path.
  `make check-capability-index`, `make check-comment-hygiene`: passed. Unit:
  `test_check_comment_hygiene.py`; integration with a stand-in executable at the
  process boundary: `test_workflow_command.py`; passed. Outside the plan, every other
  suite that ran the tree's command or the engine was moved off it (Section 9 notes).
- [x] 9.4 The `Makefile` and CI without the workflow (D15, D26; MCW-w7nb):
  - the `Makefile` includes `$(shell change-workflow fragment)` only when
    `change-workflow` is on the path, printing nothing when it is not, and drops
    `install-workflow`; its comment over the include says the workflow's targets exist
    only where it is installed, as the installed workflow's handbook sets it up;
  - `validate-local`, `validate-ci`, `validate-helm`, `run-ci`, `run-e2e`,
    `review-diff`, `last-diff`, and `code-snapshot` lose the `round-view-closed`
    prerequisite; each but `code-snapshot` says in its help text not to run it while a
    round view is open, when the branch points at the round's base rather than its
    commit;
  - `tests.yml` drops the step installing the workflow from the tree, the bubblewrap
    step, and `SANDBOX_REQUIRED`, which only the workflow's sandbox tests needed, its
    comments following; `scripts/tests/test_tests_workflow.py` drops their
    assertions and asserts that no step installs `change-workflow`.

  Verify: `test_tests_workflow.py` (unit); with `change-workflow` off the path, `make
  help` succeeds and shows the help text above, `make -n code-snapshot` and `make -n
  validate-local` print no `change-workflow`, and `make design CHANGE=x` fails with
  make's "no rule"; with it on the path, `make -n check-change CHANGE=x` prints the
  fragment's `change-workflow run pre-commit`.
  Done: the include is `$(shell command -v change-workflow … && change-workflow
  fragment)`, empty and silent without the command; `check-change`,
  `check-spec-index`, `check-decision-destinations`, and `design-review` sit inside
  the same conditional, declared phony only there, so without the workflow each is
  make's "no rule". `install-workflow` is gone; the eight targets lost
  `round-view-closed`, seven carrying the caution. Outside the plan: a `help` target,
  which none existed for, lists every target's `##` text, skipping the conditional's
  targets where the workflow is absent. `tests.yml` lost the install, bubblewrap, and
  `SANDBOX_REQUIRED`. Unit: `test_tests_workflow.py`, passed. Static configuration
  tests of the root `Makefile` with no `change-workflow` on the path,
  `test_workflow_targets.py` (`help`, the "no rule" targets, `make -n` naming no
  `change-workflow` or round view, the seven cautions): passed. With the installed
  release, by hand (its wiring, which no test holds, D14): `make -n check-change
  CHANGE=x` printed `change-workflow run pre-commit "x"`.
- [x] 9.5 The guidance check reads the workflow layer from the installed workflow
  (D6, D10, D26): `AGENTS.md`'s layer table names the workflow layer as the installed
  `arkhai-change-workflow`'s guidance in place of `docs/guidance/workflow/`, and
  `scripts/check_guidance.py` takes that layer's directory, and its tag vocabulary,
  from `change-workflow config --json`'s `workflow.guidance`, run through
  `workflow_command`, so `openspec/README.md`'s `openspec` tag still resolves; with
  the command missing it fails saying the workflow is needed, being run by
  `check-repository`, the workflow's `pre-commit`. Its tests give the layer's
  directory without the command. Verify: `scripts/tests/test_check_guidance.py`
  (unit, a case for the layer read from structured output and one for the missing
  command) and `make check-guidance`.
  Done: the layer table's workflow row names the installed guidance in prose, and the
  check skips that row. `check(root, files, installed)` reads the installed layer's
  vocabulary and its files' tags, none of its files joining the set; `main` takes the
  directory from `workflow_command.installed_guidance` and fails without the command,
  naming `arkhai-change-workflow`. Unit: `test_check_guidance.py`, and
  `test_workflow_command.py`'s `installed_guidance` cases with a stand-in at the
  process boundary: passed. `make check-guidance`: 97 files, passed; with no
  `change-workflow` on the path it fails saying the workflow is needed.
- [x] 9.6 Remove the `overrides` row from `AGENTS.md` and `scripts/check_project_layout.py`'s
  admission of `scripts/change-workflow-wheel` (D24). Verify:
  `scripts/tests/test_check_project_layout.py` (unit), `make check-project-layout`,
  and `make check-guidance`.
  Done: the row is gone, and `check_project_layout.py` is as it was before section 1
  admitted the wheel's project; its two admission tests went. Unit:
  `test_check_project_layout.py`, passed; `make check-project-layout`, `make
  check-guidance` (4 exception rows): passed.
- [x] 9.7 Remove the six workflow changes that moved to the workflow's repository
  (D19): the directories `openspec/changes/add-workflow-harness-adapters/`,
  `add-workflow-model-gateway/`, `host-change-workflow-runner/`,
  `split-implementation-sessions-automatically/`, `relay-messages-to-step-sessions/`,
  and `pass-checks-at-every-commit/`; their rows in the lesser goal "Make the change
  workflow a tool any repository can adopt", with `host-change-workflow-runner`'s
  dependency on this change; the six gap rows of that goal's gap table they own (the
  public adapter interface, the model gateway, measuring and splitting sessions,
  relaying to a reviewer's session, a step committing while checks fail, the hosted
  runner); and the two rows under "Unowned work found by
  `extract-change-workflow-repository`", the heading going with them, once 9.2 has
  recorded that the coordinator carried them. The goal's own retirement is
  closeout's (11.6). Verify: `make check-change-index`, and no document outside the
  archive and this change's records naming a removed change's directory
  (`make check-doc-citations` unscoped, for those paths).
  Done: the six directories, their six change rows, the six gap rows, and the
  "Unowned work found by" heading with its two rows removed, the coordinator having
  carried both (9.2). `make check-change-index`: passed. The one permanent citation
  of a removed directory, in `market-change-workflow`'s companion, was rewritten by
  10.3; an archived row's notes name two of them in prose.
- [x] 9.8 Verify the section: `make test-release-tooling`; with `change-workflow` off
  the path (a `PATH` without `uv tool dir --bin`), `make test-release-tooling`, `make
  dist-release`, `make check-release-components`, and `make pre-push REMOTE=origin`
  with an empty ref list on standard input, none calling `change-workflow`;
  `change-workflow --version` within the range; `make check-change
  CHANGE=extract-change-workflow-repository` passing but for the citations of removed
  documents section 10 rewrites and the `market-change-workflow` delta's added ids
  10.2 indexes; and `git ls-files` listing no path of those 9.3 and 9.7 remove.
  Done: with no `change-workflow` on the path: `make test-release-tooling`, 1485
  passed; `make dist-release`, built; `make check-release-components` and `make
  pre-push REMOTE=origin`, passed, none calling `change-workflow`. `change-workflow
  --version`: `0.1.0`, within `>=0.1, <0.2`. `git ls-files`: no path 9.3 or 9.7
  removes. The new tests fail at the section's base (`change-workflow run
  test-before`): `test_tests_workflow.py` 2 of 3, `test_workflow_targets.py` all 7.
  `change-workflow run pre-commit`: `make validate-local` passed packaging and every
  suite but the Ansible project's, whose local temporary directory under `~/.ansible`
  the step's sandbox did not grant (environmental); with `ANSIBLE_LOCAL_TEMP`
  elsewhere every suite passed, the Ansible project's 214 among them. The default
  checks passed but `spec-index` (the three ids 10.2 indexes); `check-repository`
  passed but the scoped citations, on paths this change's own documents cited, which
  round 2's triage rewrote.
  End-to-end: none exercises the workflow's tooling; none owed.
  Owed by validation (ci tests.yml): the `test · test-deployment-packaging` job, its
  log showing no step installing the change workflow and the scripts' suites passed.

Section 9 notes (handoff):

- Outside the plan, every suite that ran the tree's command or the engine, which D26
  says no suite may need, was moved off it; what each dropped is the workflow's to
  test (D14): `test_check_public_content.py` and `test_check_secrets.py` push through
  a Git pre-push hook running the gate; `test_validate_parallel.py`'s clone cases
  became `change_of` cases against a stand-in answering `clone where`;
  `test_check_change.py`'s `run_checks` takes an injected finder;
  `test_check_doc_citations.py` and `test_validate_slice.py` share a stand-in,
  `scripts/tests/workflow_stand_in.py`, answering `find --json` and `check spec-index
  --json`; `test_check_guidance.py` keeps the test that no engineering heading
  repeats; `test_make_change_completion.py` completes a stand-in fragment's targets.
  The whole scripts suite runs without the workflow.
- `scripts/tests/conftest.py` names the step's marker, `CHANGE_WORKFLOW_UNATTENDED`,
  literally: no interface promises it, and a release renaming it fails loudly.
- The step's sandbox did not let Ansible write `~/.ansible`, so the Ansible project's
  suite failed in sandboxed steps running `make test`; this section touched nothing
  of that suite.

## 10. This repository's documents cite the workflow, and `market-change-workflow` amended

Replanned with section 9: documents name the workflow only by its distribution, and
`market-change-workflow` records that no test holds its provisions.

Delivers every document of this repository citing the workflow in prose by its
distribution, requirement id, and section, and its own capability amended by hand (D6,
D14, D23, D26; MCW-5tgp, MCW-9k0c, MCW-iqh1, MCW-w7nb). Touches the documents outside
the archive that cite `openspec/specs/change-workflow/`, `docs/guidance/workflow/`,
the handbook under `docs/`, `.agents/skills/change-*`, or
`scripts/change-workflow` (`AGENTS.md`, `openspec/README.md`,
`docs/development/ARCHITECTURE.md`, `docs/development/TESTING.md`, the capabilities'
documents, the repository guidance, `.agents/evidence/`, and the docstrings and
comments of this repository's scripts), and `openspec/specs/market-change-workflow/`
(`spec.md`, `index.md`, `README.md`).

- [x] 10.1 Rewrite each citation of the workflow's specification, companion,
  guidance, handbook, skills, or command path in prose — `arkhai-change-workflow`'s
  requirement by id and its guidance or handbook by section name — with no link to or
  address of the workflow's repository (D6, MCW-9k0c). `AGENTS.md` names the installed
  workflow as `arkhai-change-workflow`, its committed range, and the local
  configuration, says to install it to drive a change and leaves setting it up to its
  handbook, and reads the workflow's guidance through `change-workflow config load`
  in place of `.agents/skills/` and `docs/guidance/workflow/` (MCW-iqh1, D15).
  Verify: `make check-doc-citations` unscoped naming no path section 9 removed, `make
  check-guidance`, and `make check-capability-index`.
  Done: every citation outside the archive rewritten — `AGENTS.md` (the change
  workflow's paragraph, "What every session reads", and the workflow guidance cited
  by section name), `openspec/README.md` (its placement table drops the workflow's
  guidance and handbook rows), `openspec/specs/README.md`, `planning-governance`'s
  Evidence, `docs/guidance/repository/README.md` and `test-targets.md` (its example
  check now `check-guidance`), `docs/release-handbook.md`, the `Makefile`'s comments,
  the scripts' docstrings, the change index's goal section and row notes, and 49
  other changes' documents (notes). No link to or address of the workflow's
  repository. `make check-doc-citations` unscoped: no path section 9 removed; two
  older broken citations remain, neither section 9's (notes). `make check-guidance`
  (97 files) and `make check-capability-index`: passed. Unit:
  `test_check_doc_citations.py`, `test_check_comment_hygiene.py`,
  `test_check_guidance.py`: 97 passed.
- [x] 10.2 Apply the `market-change-workflow` delta to its `spec.md` by hand — MCW-9k0c,
  MCW-iqh1, and MCW-w7nb added, MCW-5tgp modified — and its `## Evidence` section's
  bullet on the provisions, which names the deleted
  `test_change_workflow_assumptions.py`, rewritten to say review holds the statement
  complete (D14); write their `index.md` entries under "1. The workflow's roles"
  (MCW-5tgp's summary revised) and "4. This repository's workflow values" (MCW-9k0c,
  MCW-iqh1, MCW-w7nb) (D23). Verify: `make check-spec-index
  CHANGE=extract-change-workflow-repository` and a diff against the delta in the
  handoff.
  Done: MCW-9k0c, MCW-iqh1, and MCW-w7nb added and MCW-5tgp replaced, verbatim from
  the delta; the Evidence's provisions bullet says no test reads the statement and
  review holds it complete, beside bullets for the template and for building without
  the workflow (`test_tests_workflow.py`, `test_workflow_targets.py`); the Purpose
  names the distribution. Outside the plan: MCW-s4bx's two scenarios ran
  `scripts/change-workflow`, so the delta gains MCW-s4bx as MODIFIED, the command
  alone corrected, applied the same way. Index entries written as planned. `make
  check-spec-index CHANGE=extract-change-workflow-repository`: passed. Each of the
  delta's five requirements appears in `spec.md` character for character.
  `change-workflow openspec validate extract-change-workflow-repository --strict`:
  valid.
- [x] 10.3 Amend `market-change-workflow`'s companion: "This repository is the
  workflow's first adopter" (it adopts `arkhai-change-workflow` within its range, and
  builds, tests, and releases without it, D26); "How this repository provides the
  workflow's roles" (both configuration files; no test reads `config --json` and
  review holds the statement complete when a change edits `[workflow] version`,
  `.agents/workflow.toml`, the statement, or a make target it names; its table of the
  skills' exemptions goes with the skills, D14); "The engine's own assumptions" (no
  path of the engine's left in the tree); "What each check enforces" (the two checks
  now the engine's, D10); the validation and diff targets not to be run while a round
  view is open (D26); and the hosted runner named as the workflow repository's work.
  Verify: `make check-doc-citations CHANGE=extract-change-workflow-repository`.
  Done: "This repository is the workflow's first adopter" gains the adoption by
  distribution within `[workflow] version`, with the local configuration and its
  template (MCW-9k0c, MCW-iqh1), and building, testing, and releasing without the
  workflow, with the seven targets' round-view instruction (MCW-w7nb, D26). "How this
  repository provides the workflow's roles": both configuration files, review holding
  the statement complete on D14's four edits, the skills' naming nothing the
  workflow's to verify (CW-n8tr), and the skills' exemptions section removed. "The
  engine's own assumptions" aligned with the release's table. "What each check
  enforces" cites by section name. The models are the local configuration's; the
  hosted runner is the workflow repository's work. `make check-doc-citations
  CHANGE=extract-change-workflow-repository`: the companion cites no missing path.
- [x] 10.4 Verify the section: `make check-change
  CHANGE=extract-change-workflow-repository`, `make check-guidance`, and `make
  test-release-tooling`.
  Done: `change-workflow run pre-commit extract-change-workflow-repository`: `make
  validate-local` passed — packaging and every suite of `make test`, the scripts'
  1485 and the Ansible project's 214 among them, under the owner's per-run grant of
  `~/.ansible`; the default checks passed — index, tasks, skills, `spec-index`,
  decisions, and the strict OpenSpec validation; `check-repository` passed but the
  scoped citations, which round 2's triage then cleared. `make check-guidance`: 97
  files, passed.
  End-to-end: none exercises the workflow's tooling; none owed.

Section 10 notes (handoff):

- Other changes' documents: 42 task lists' closeout lines now cite
  `arkhai-change-workflow`'s guidance, "Closeout", and two task lists' closeout
  validation the installed `change-workflow openspec`. Five changes still in this
  index work on the workflow itself — `workflow-round-review-without-merges`,
  `remove-workflow-log-conversion`, `add-change-intake`, and in part
  `build-test-before-environments` and `test-affected-suite-selection` — and now
  name its parts in prose as `arkhai-change-workflow`'s; where they belong is not this
  change's to settle: an unowned row under "Unowned work with no campaign" records it,
  with the row on the next-step computation's round join.
- Two broken citations the unscoped check reports are older than section 9 and not
  the workflow's: the change index's row citing the native Ansible gate's shell script, and
  `renewable-compute-lease-deadlines`' design citing an archived change's review,
  which is untracked. Left as found.
- `test_check_guidance.py`'s fixtures keep a workflow layer under
  `docs/guidance/workflow/`: they test the check's generic handling of a
  workflow-tagged file, not this repository's layout.
- The fresh-context check found two statements false of the tree, both fixed: the
  builds, suites, and releases work without the workflow, while `check-repository`,
  `check-guidance`, a change's citations, and `record-capacity` reach its command.
- Implementation review 69's triage, 69 F1: section 4's owed CI line (4.6) became
  "Shown by validation … by validations 49 and 51", since section 9 removed what it
  asked for, so `change-workflow evidence` lists `tests.yml` as owed by section 9
  alone.
- Implementation review 69's triage, 69 F2: the citations of paths section 9 removed,
  in this change's `design.md`, `proposal.md`, and earlier task notes, are rewritten
  so no path the tree lacks is cited — each names the file without its root
  directory, or by where it lay or what it was. `make check-doc-citations
  CHANGE=extract-change-workflow-repository` and `change-workflow run pre-commit
  extract-change-workflow-repository`: passed, `check-repository`'s seven checks
  included. 9.8's task text and dated verification lines are left as written.

## 11. Closeout

- [x] 11.1 Comment hygiene: run `make check-comment-hygiene`; any finding, or a
  comment the change added that still names history or the change, returns the change
  to implementation.
  Done: `make check-comment-hygiene`: passed. The comments and docstrings the change
  adds since `dev` (the `Makefile`, `tests.yml`, the configuration's comments, and
  the repository's scripts and tests) describe the current system and name no change,
  review, task, or migration.
- [x] 11.2 Import placement: check the imports the change added in this repository's
  scripts against the engineering guidance's "Imports go at module level"; one that
  should move returns the change to implementation.
  Done: every import the change adds since `dev` is at module level; no local import
  added.
- [x] 11.3 Documentation compliance: re-check D1–D26 against the workflow's placement
  rules and `openspec/README.md`'s placement table, and that each document the change
  wrote here describes the current state.
  Done: each decision's destination follows the workflow's placement table and
  `openspec/README.md`'s: the workflow's rules and behaviour went with its
  specification, companion, handbook, and guidance to the workflow's repository; this
  repository's provision of the workflow's roles is `market-change-workflow`'s; its
  cross-system description of the adoption is `ARCHITECTURE.md`'s (11.9); its root
  facts — the workflow, the range, the local configuration — are `AGENTS.md`'s; and
  the goal's retirement is the change index's. The documents the change wrote here
  (`AGENTS.md`, `openspec/README.md`, `market-change-workflow`'s documents, the
  repository guidance, `ARCHITECTURE.md`) describe the current state, naming the
  workflow by its distribution with no wording relative to the change.
- [x] 11.4 Narrative compression: shorten completed task notes to final behaviour,
  the gate's evidence (9.2), material validation evidence, and destinations.
  Done: sections 1–10's notes shortened from 1,900 lines to about 1,060, every task's
  planned text, `End-to-end:` line, and owed or shown line kept verbatim and 9.2's
  evidence in full; rationale worth keeping moved first to `design.md`, "Implementation
  record". `change-workflow check tasks` passes, and `change-workflow evidence` lists
  `tests.yml` as owed by section 9 alone, as before.
- [x] 11.5 Roadmap currency: no roadmap goal holds the change workflow; record that
  disposition in the design-promotion record.
  Done: no goal of `docs/development/ROADMAP.md` holds the change workflow; it is
  unchanged, recorded in the design-promotion record.
- [x] 11.6 Campaign index currency: in `openspec/changes/README.md`, retire the
  lesser goal "Make the change workflow a tool any repository can adopt" (D19): its
  current state says this repository adopts the workflow, as
  `arkhai-change-workflow`, within its declared range, and that the goal's open
  changes and gaps moved to the workflow's repository in 2026-11; the gap rows "The
  workflow is not a separately versioned distribution" and the diagrams' redraw close
  with this change; the goal's entry leaves the goal index, and its archived rows,
  this change's among them, join "Archived and superseded", each change appearing
  once, this change's own row moving with them and archive cleanup setting it
  `archived`. Run `make check-change-index`.
  Done: the goal's entry left the goal index and its section the active campaigns; its
  current state and its six rows, this change's among them, are "Retired lesser goal —
  Make the change workflow a tool any repository can adopt" under "Archived and
  superseded". The two gap rows this change owned closed. The goal's one open,
  unowned gap — loading guidance by its tags — moved to "Unowned work with no
  campaign" rather than leaving with the goal. No other row's status or `Depends on`
  changed, and the goal had no dependency graph. `make check-change-index`: passed.
- [x] 11.7 Packaging: `make check-packaging`, `make check-architecture-change
  CHANGE=extract-change-workflow-repository`, and `make check-agent-skills`, since the
  change touched `.agents/`, `.claude/`, and `.codex/`.
  Done: `make check-packaging`: passed; `make check-architecture-change
  CHANGE=extract-change-workflow-repository`: passed, the change owns no architecture
  row (also run as `change-workflow run pre-archive`: passed); `make
  check-agent-skills`: passed.
- [x] 11.8 End-to-end pipeline: record the pipeline run the latest passing validation
  gathered, with its result; no scenario exercises the change's behaviour.
  Done: validation 76, passed at `b4d496716`: pipeline run 45646128001, success —
  e2e-vm 513 passed, e2e-bare-metal 249, e2e-apicredits 4; with the owed `tests.yml`
  run 45646139287 (the `test · test-deployment-packaging` job's log showing no step
  installing the change workflow, and the scripts' 1485 tests passing: 9.8's owed
  observation), the local kind, and Helm, all passed. No scenario exercises the
  change's behaviour (the record's coverage section). The closeout commit's code is
  `b4d496716`'s: the merge of `dev` after it, `688a5b547`, changed only inert paths,
  and closeout changes no code.
- [x] 11.9 Promotion: complete the design-promotion record. In this repository
  write: `docs/development/ARCHITECTURE.md`, a new "The change workflow" subsection
  under "Build, packaging, and initialization", for how this repository adopts the
  workflow — naming it only as `arkhai-change-workflow` (D6, D9), within its committed
  range (D7, D11) — and the owner's principles that this repository builds, tests, and
  releases without the workflow, which is how it is changed rather than part of its
  validation (D26), and that it keeps no test of its configuration or wiring of the
  workflow (D14); and confirm the destinations already written — the `change-workflow`
  specification, index, companion, diagrams, and handbook in section 8 and 7.3, now
  in the workflow's repository, `market-change-workflow` and `AGENTS.md` in section
  10, the `Makefile`'s help text in 9.4, and D14's requests delivered to the
  workflow's repository in 9.1. Record D2, D17, D22, D23, and D24 as having no
  permanent destination, as the proposal says.
  Done: `docs/development/ARCHITECTURE.md` gains "The change workflow" under "Build,
  packaging, and initialization", with its document-map row: the workflow named only
  as `arkhai-change-workflow`, one installed version checked against the committed
  `[workflow] version`, the local configuration and its template, building, testing,
  and releasing without it, and no test of its configuration or wiring, review holding
  the statement of its roles complete. Confirmed already written: `change-workflow`'s
  specification, index, companion, diagrams, and handbook (sections 7 and 8), now the
  released `arkhai-change-workflow`'s; `market-change-workflow` and `AGENTS.md`
  (section 10); the `Makefile`'s help text (9.4); D14's requests delivered (9.1, log
  seq 92). `design.md`'s design-promotion record names every decision's location, D2,
  D17, D22, D23, and D24 with none. `market-change-workflow`'s `index.md` already
  indexes the delta's ids (10.2): `make check-spec-index
  CHANGE=extract-change-workflow-repository`: passed.
- [x] 11.10 Guidance placement: read the guidance sections the change added, moved,
  or rewrote — the renamed engineering headings, `AGENTS.md`'s layer table and
  exceptions rows — against the
  layer test, adjacency, and exception placement; run `make check-guidance`.
  Done: the renamed engineering headings stay engineering, renamed in place; the
  repository guidance's two edits (`docs/guidance/repository/README.md` naming the
  workflow layer and its tags by the installed guidance, and `test-targets.md`'s
  example check) are repository guidance spanning systems, where they were;
  `AGENTS.md`'s layer table names the workflow layer as the installed guidance, and its
  one exception row the change added, the citation check's admission of the local
  configuration, spans every document naming that file, so it sits in the root table.
  The wheel's exception row left with the wheel (9.6). `ARCHITECTURE.md`'s new
  section is description, not guidance. Nothing moved. `make check-guidance`: 97
  files, 4 exception rows, passed.
- [x] 11.11 Documentation citations: `make check-doc-citations
  CHANGE=extract-change-workflow-repository`, every match resolved; then
  `change-workflow openspec validate extract-change-workflow-repository --strict`,
  the installed command having replaced `scripts/change-workflow`.
  Done: `make check-doc-citations CHANGE=extract-change-workflow-repository`: every
  cited path resolves; `change-workflow run pre-commit
  extract-change-workflow-repository`, the strict validation among its default
  checks: passed (11.12's note).
- [x] 11.12 Archival: archive with `--skip-specs`, both capabilities' specifications
  having been written by hand (D23): `change-workflow openspec archive
  extract-change-workflow-repository -y --skip-specs`; the delta files stay in the
  archived change as its record.
  Done: archived with `--skip-specs`. `market-change-workflow`'s `spec.md` already
  holds each of the delta's five requirements character for character (10.2), and
  `change-workflow`'s specification left with the workflow, so a merge would duplicate
  the first and the archive would refuse the second. No permanent `spec.md` changed in
  the archive. `change-workflow run pre-commit extract-change-workflow-repository`
  before it, the strict validation of the change among its default checks, and after
  it, validating every specification strictly: both passed, once the archive's
  citations check, which no longer counts the change's deltas, had found two citations
  of `change-workflow`'s permanent `spec.md` by its removed path, in D23 and in 8.1's
  task text; both now name it as the `spec.md` under that capability's directory, their
  meaning unchanged, as 69 F2 rewrote the change's other citations of removed paths.
