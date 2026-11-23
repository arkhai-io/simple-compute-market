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

- [x] 1.1 Write the wheel's project, `scripts/change-workflow-wheel/pyproject.toml`:
  distribution `arkhai-change-workflow`, version `0.1.0`, MIT, Hatchling, the
  `change-workflow` console entry point on `change_workflow.cli:main`, the package
  `scripts/change_workflow/`, and, as package data under it, the eleven workflow skills
  (`.agents/skills/change-*`, `.agents/skills/guidance-review`), `docs/guidance/workflow/`,
  `openspec/specs/change-workflow/` (`spec.md`, `index.md`, `README.md`, `diagrams/`),
  `docs/change-workflow-handbook.md`, `.agents/change-outcome.schema.json`, and
  `workflow.mk` (D8, D9). First prove that Hatchling builds it with these sources
  outside the project's directory (`uv build --wheel scripts/change-workflow-wheel`)
  and that the wheel lists every file; if it cannot, stop the section and report it,
  since the layout is D24's. Verify: the wheel's file list in the section's handoff.
  Done: Hatchling builds it with `bypass-selection = true` and a `force-include` table
  of paths relative to the project directory (`"../change_workflow" = "change_workflow"`,
  each document under `change_workflow/data/`); `only-include` and `sources` refuse a
  path outside the project (`must be relative`), so `force-include` is the form.
  `__pycache__` is left out without an exclude. The wheel's file list is in the
  section's notes. `openspec/specs/change-workflow/diagrams.md`, the capability's own
  guidance, is not among the four documents the task names, and does not ship.
- [x] 1.2 Add `scripts/change_workflow/documents.py`: each document by its role
  (`specification`, `index`, `companion`, `diagrams`, `guidance`, `handbook`, `schema`,
  `fragment`, and the skills), found through `importlib.resources` when installed and
  at its tree path when the package runs from `scripts/` (D6, CW-lm42). Route
  `outcome.SCHEMA` and `diagram.DIAGRAMS` through it. Verify: unit tests for both
  modes, `scripts/tests/test_change_workflow_documents.py` (new).
  Done: `documents.Distribution(package)` is installed when the package holds `data/`,
  which the tree's never does; `path(role)`, `documents()`, `skills()` (the tree's
  `change-*` and `guidance-review` beside OpenSpec's skills, or the package's every
  one), `version()` (the metadata through an injected `metadata_version`, or the
  tree's project file), and `described()` for `config --json`. `outcome.SCHEMA` and
  `diagram.DIAGRAMS` are now absolute paths in the distribution, so `check graph`
  checks the distribution's diagram in any repository, naming it relative to the
  repository only where it lies there. Unit, `test_change_workflow_documents.py`
  (both modes, and this checkout's tree): passed; `test_change_workflow_graph.py`,
  `test_change_workflow_cli.py`, `test_change_workflow_outcome.py`: passed.
- [x] 1.3 `config --json` gains `workflow`: `version` and each document by role, no
  directory to look inside (D6, CW-lm42); `change-workflow --version` prints the
  version and reads no configuration (CW-5kl9). The version comes from the installed
  distribution's metadata, or the project file's when run from the tree. Verify:
  library integration cases in `test_change_workflow_config.py` and
  `test_change_workflow_cli.py`.
  Done: `--version` is argparse's version action, so it prints before any
  repository is looked for. Library integration: `config --json` in a temporary
  checkout names the tree's eight documents, existing, as `documents.described()`
  gives them (in-process `main`); `scripts/change-workflow --version` run as a
  subprocess outside any repository, and in a repository whose configuration
  `config` refuses there, prints the version: passed.
- [x] 1.4 Every line `log.py` appends carries `workflow`, the engine's version; no
  reader routes on it and `format` stays 2 (D12, CW-d867). Verify: unit cases in
  `test_change_workflow_log.py` (a line written under each of two versions), and the
  next-step suite unchanged (`test_change_next_step.py`).
  Done: `log.numbered` adds `workflow` beside `format`, from an injected `version`
  (`documents.version` by default), and refuses a writer setting it, as it refuses
  `seq`, `at`, and `format`; the line a conversion appends carries it too, through
  `numbered`, while the older lines it rewrites keep only what `convert.rewritten`
  gives them, since they are not appended. Unit, `test_change_workflow_log.py` (two lines under 0.4.1 and 0.4.2,
  both format 2, neither older nor newer; a writer setting it refused): passed, with
  five exact-line assertions given the field as `documents.version()` gives it, and
  one in `test_change_workflow_review.py`;
  `test_change_next_step.py` unchanged: passed.
- [x] 1.5 Declare the exception (D24): an `overrides` row in `AGENTS.md`, "Exceptions
  to shared guidance", against `packaging-python.md`'s "One import package per
  distribution", "Nothing remaps the package", and "Data files live inside the
  package", and `packaging-hatchling.md`'s "The wheel target names the one package",
  for `scripts/change-workflow-wheel/`, lasting until the second half removes it; and
  `scripts/check_project_layout.py` admitting that one project, naming the row. Verify:
  `test_check_project_layout.py` (the wheel admitted, any other remap still refused)
  and `make check-guidance`.
  Done: `check_project_layout.ADMITTED` maps the project to the row; the admitted
  project skips only the wheel target's rule, still held to the backend and `[tool.uv]`
  rules. Unit, `test_check_project_layout.py` (the same remap admitted at
  `scripts/change-workflow-wheel` and refused elsewhere; the admitted project's
  setuptools backend and `find-links` refused): passed. `make check-guidance` and
  `make check-project-layout`: passed. The other packaging checks
  (`check-uv-setup`, `check-locks`, `check-python-version`, `check-build-requirements`,
  `check-architecture`, `check-release-components`) pass with the project present.
- [x] 1.6 Verify the section: build the wheel, install it into a temporary tool
  directory with `uv tool install`, and run the installed `change-workflow --version`
  and `config --json` in a temporary repository, each named document existing — a
  library integration test, `scripts/tests/test_change_workflow_wheel.py` (new),
  skipped with its reason where `uv` is absent; plus the section's suites and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: `test_change_workflow_wheel.py` builds the wheel with `uv build` and installs
  it with `uv tool install` into temporary `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`; it
  runs real external processes, so it is integration of the external-process form,
  skipped where `uv` is absent as the plan asks, though `make test-release-tooling`
  always runs under `uv`. It holds the wheel's packaged files equal, byte for byte,
  to the engine's modules and fragment and every document of the tree; the installed
  `--version` prints the tree's version; and the installed `config --json`, in a
  temporary repository holding no copy of the workflow, names every role inside the
  tool directory and none in this checkout: passed. `scripts/change-workflow run
  pre-commit`: `make validate-local` passed (packaging and every suite, 3,599 scripts'
  tests among them); the strict OpenSpec validation and the default checks passed;
  `make check-repository` failed only on two checks that fail at the plan's commit as
  well: `check-spec-index` (the delta's twelve added ids are not in `index.md` until
  section 8 writes them) and `check-doc-citations` (the change's documents cite
  `.agents/workflow.local.template.toml` and `.agents/workflow.local.toml`, which
  section 2 creates and ignores, and `scripts/tests/test_change_workflow_install.py`
  and `scripts/tests/test_change_workflow_citations.py`, which sections 3 and 5
  create).

Section 1 notes (handoff):

- The wheel's file list, as `uv build --wheel scripts/change-workflow-wheel` builds
  it: `change_workflow/` with its 43 modules and `workflow.mk`; under
  `change_workflow/data/`: `change-outcome.schema.json`,
  `change-workflow-handbook.md`, `guidance/` (the seven files of
  `docs/guidance/workflow/`), `specification/` (`spec.md`, `index.md`, `README.md`,
  and `diagrams/` with its four `.drawio` sources and four SVGs), and `skills/` (the
  eleven skills' `SKILL.md`); and the `dist-info`'s `METADATA`, `WHEEL`,
  `entry_points.txt`, and `RECORD`. A build with no `--out-dir` writes
  `scripts/change-workflow-wheel/dist/`, which `.gitignore`'s `dist/` covers.
- A document added to the workflow's set needs a `force-include` line and a role in
  `documents`; `test_change_workflow_wheel.py` fails until both agree with the tree.
  A skill added under `.agents/skills/` named `change-*` is the workflow's by
  `documents.skills()`'s rule, and the wheel test fails until its line is added.
- The modules cite CW-5kl9, CW-lm42, and CW-d867, which only the change's delta holds
  until section 8 applies it to `spec.md`; the preliminary merge waits for section 8.
- Outside the plan: `scripts/tests/test_change_next_step.py` held a comment
  `make check-comment-hygiene` refuses at the plan's commit ("Section 3 joins…"),
  reworded to name the sections by ordinal.
- The fresh-context check's findings fixed: a comment naming a range check that did
  not exist yet, and one naming an installer; `documents` missing from the package's
  module list; the CW-5kl9 test now runs `--version` in a repository whose
  configuration `config` refuses, as well as outside any; exact-line assertions take
  the version from `documents.version()` rather than a literal. Declined: dropping
  the wheel test's skip, which the plan asks for.

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
  library, padding release numbers with zeros, `~=` keeping the release's series; a
  version with anything after its release numbers, a pre-release or development
  release, sorts before its release, as PEP 440 orders them.
  `config.check` reads the range (`_accepted`) right after parsing the TOML, before
  any table is checked, against an injected `installed` (`documents.version` by
  default). The field is checked when declared and not yet required (section 4).
  Unit: specifiers read and malformed ranges refused, admission across `>=`, `<`,
  `!=`, `~=` and of a development release and a release candidate, and the check refusing 0.4.2 against `>=0.5, <0.6` without naming the
  later table: passed. Library integration (in-process `main` over a temporary
  directory): "The installed version is too old" — `config load design` refuses
  naming the engine's version, the range, and `change-workflow install`, and no
  unknown table; a range admitting the engine reads on, `config --json` listing
  `workflow.version` declared: passed. `install` does not exist yet; it will read no
  configuration (section 3).
- [x] 2.2 The engine reads `.agents/workflow.local.toml` beside the committed file:
  `[guidance]`, `[models]`, and `[sandbox] writable.*`, the local writable paths
  extending the committed ones; `config --json` reports `local` (`file`, `exists`),
  each required local field it lacks as `missing`, distinct from `absent`, and
  succeeds with no local file, giving the committed fields and the distribution's in
  full (D5, CW-4pm4's CI scenarios). Verify: library integration cases in
  `test_change_workflow_config.py`.
  Done: `config.load` reads both files; `check(..., local=<text>)` takes the local
  tables (`_local_tables`), its models joining the committed ones, a step's models
  declared in both refused, and its writable paths extending the committed ones,
  checked against the committed protected paths too. A local table or key the
  committed file holds is refused naming `.agents/workflow.toml`; the converse, a
  local field in the committed file, waits for section 4. `config --json` gives
  `local` and `guidance`, and `resolution` lists `workflow.version` and
  `guidance.engineering`, the latter and every `models.*` `missing` when absent;
  `config`'s listing names the local file on its second line. Library integration
  (in-process `main`, temporary Git checkouts): no local file — exit 0, `local`
  absent, every required local field `missing`, `guidance.engineering` null, every
  committed field as the resolution of the committed file alone gives it, `workflow`
  in full, and `config`'s second line naming the local file absent; a local file's
  models, pointer, and writable paths read; seven malformed local files refused,
  each naming the field, table, or file at fault; a local writable path under a
  committed protected one refused: passed.
- [x] 2.3 The pointer (D4, CW-hu0z): `engineering = { path }` or `{ none = <reason> }`,
  one key; a missing or Markdown-less directory and an empty reason refused; a `load`
  entry that is or lies beneath the pointer refused; `config --json`'s
  `guidance.engineering` as `{"path"}`, `{"none"}`, or `null`. Verify: library
  integration cases in `test_change_workflow_config.py`, the scenarios of CW-hu0z.
  Done: `config.Engineering` and `_engineering`; an absolute `path` is refused, as
  CW-hu0z admits only the root's or `~`'s; `_overlapping` refuses an entry that is
  the pointer's directory, lies beneath it, or is a directory holding it. Library
  integration: CW-hu0z's three scenarios, a `~` pointer printed whole, eight
  malformed pointers, four overlapping entries, and an entry beside the pointer
  admitted: passed.
- [x] 2.4 `config load <step>` and `config load common` print, in order, the
  pointer's Markdown files, the installed workflow guidance, then `load.common` and
  `load.<step>`, each once; the post-compaction hook re-reads what `config load
  common` prints (D6, CW-l7hn). Verify: library integration cases in
  `test_change_workflow_config.py` and `test_change_workflow_command.py`.
  Done: `Configuration.documents` prints the pointer's files, then the distribution's
  guidance, then `load.common` and `load.<step>`, each relative to the root where it
  lies in it and whole otherwise, each once; the hook reads the same list, and its
  branch for a configuration naming no document went, since the workflow's guidance
  always names some. Library integration: the existing load cases now open with the
  workflow's guidance; `config load plan` with a pointer; the hook naming pointer,
  workflow guidance, and `load.common` in order (`test_post_compaction_context.py`);
  and `scripts/change-workflow config load common` run as a process in this checkout,
  the workflow's guidance before `AGENTS.md`, each once: passed.
- [x] 2.5 A change's clone links `.agents/workflow.local.toml` to the workspace's, as
  it links `.claude/settings.local.json` (CW-4pm4); the sandbox protects the local
  file beside `.agents/workflow.toml` (D13, CW-r6kd). Verify: `test_change_clone.py`
  and `test_change_workflow_scope.py`, `test_change_workflow_sandbox.py` (the write
  refused, under `needs_bwrap`).
  Done: `clone.LINKED` links both files, `done` naming "local configuration"; a
  local file that is not the link is refused, nothing deleted, but for an empty one,
  the sandbox's empty form of an absent protected file, which holds no setting and
  is replaced by the link. `scope.PROTECTED`
  holds `.agents/workflow.local.toml`, so a local file absent at launch is created
  empty and mounted read-only, as every absent protected path is. Library
  integration, `test_change_clone.py` (the link made, resumed, a file in its place
  refused, an empty one replaced): passed; unit, `test_change_workflow_scope.py`: passed; external
  process, `test_change_workflow_sandbox.py` under `needs_bwrap` (the write to an
  existing local file and to an absent one both fail, the absent one left empty),
  run, not skipped: passed.
- [x] 2.6 Add `.agents/workflow.local.toml` to `.gitignore`, and commit
  `.agents/workflow.local.template.toml`: the pointer at `docs/guidance/engineering/`
  and the models `.agents/workflow.toml` declares today, each with its comment (D5,
  MCW-iqh1). Verify: `git check-ignore .agents/workflow.local.toml` and the template
  read by 2.2's parser in a test.
  Done: `git check-ignore .agents/workflow.local.toml` prints it, and the template is
  not ignored, both held by a test; the template, beside this repository's committed
  configuration with `[models]` removed and `load.common`'s `docs/guidance/` read as
  `docs/guidance/repository/` (section 4.1's edit), is read whole, its pointer
  resolved and every step's and the orchestrator's model declared: passed.
- [ ] 2.7 Verify the section: its suites, and `scripts/change-workflow run
  pre-commit extract-change-workflow-repository` with this repository's configuration
  unchanged, which still passes.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites — `test_change_workflow_config.py`,
  `test_change_workflow_command.py`, `test_post_compaction_context.py`,
  `test_change_clone.py`, `test_change_workflow_scope.py`,
  `test_change_workflow_sandbox.py`, `test_check_doc_citations.py`: passed.
  `scripts/change-workflow run pre-commit`, this repository's configuration
  unchanged: `make validate-local` passed (packaging and every suite, 3,661 scripts'
  tests among them); the default checks and strict OpenSpec validation passed; `make
  check-repository` failed only on the two checks that fail at the plan's commit:
  `check-spec-index` (section 8's index entries) and `check-doc-citations`, now
  naming only `scripts/tests/test_change_workflow_install.py` and
  `scripts/tests/test_change_workflow_citations.py`, which sections 3 and 5 create.

Section 2 notes (handoff):

- Outside the plan: `scripts/check_doc_citations.py` admits one absent path,
  `.agents/workflow.local.toml` (`LOCAL_ONLY`), which Git ignores and no branch
  holds, under a new `overrides` row of `AGENTS.md`'s exceptions against
  `documentation.md`'s "Citations resolve"; `market-change-workflow`'s companion's
  row for the check says so. Without it every permanent document naming the local
  file, the specifications sections 8 and 10 write among them, fails the check.
- An absent protected path is created empty before a step launches, the local file
  among them: a clone's link to a workspace with no local file creates the
  workspace's empty, and a clone made before the link holds an empty file of its
  own. `clone` replaces an empty local file with its link, and section 3's
  `install` must treat an empty local file as absent, writing the template there,
  or the orchestrator's install in 4.1 writes nothing; this change's own clone was
  made before the link, so run `scripts/change-workflow clone
  extract-change-workflow-repository` from the workspace once the workspace's local
  file is written.
- A clone now holds a second link, so every test fixture making a workspace that
  ignores `.claude/settings.local.json` ignores `.agents/workflow.local.toml` too
  (`test_change_history.py`, `test_change_next_step.py`, `test_round_view.py`,
  `test_validate_parallel.py`), as this repository's `.gitignore` does.
- Two tests read this repository's committed configuration and change with 4.1's
  edit: `test_this_repositorys_template_is_read_as_a_local_configuration` removes
  `[models]` and re-points `docs/guidance/` only where they are, so it holds after
  4.1; `test_config_load_prints_the_workflows_guidance_before_the_repositorys_documents`
  finds `AGENTS.md` and reads the workflow's guidance just before it, whatever the
  checkout's pointer adds first. 4.1's `load.common` must stop naming
  `docs/guidance/` before a local file with the pointer is written, or every command
  reading the configuration refuses the overlap.
- `config load`'s output now opens with the workflow's guidance, whole paths outside
  the tree the engine runs from; in this checkout, still without a pointer, the
  engineering guidance comes from `load.common`'s `docs/guidance/` as before.
- The fresh-context check's findings fixed: the empty local file above; the
  citation exemption narrowed from every ignored path to the one file and declared;
  comments in `.gitignore` and the template naming the installer before it exists;
  a test docstring describing 4.1's edit; the command test depending on the
  checkout's local file; pre-releases ordered before their release; two overstated
  notes; contract lines. Declined: none.

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
  Done: `Adapter.skills` names the user skill directory, `~/.claude/skills/` and
  `~/.codex/skills/`, each also among its adapter's protected paths, so an absent one
  is created as a directory before launch and the manifest inside it is covered.
  `documents.Distribution.installed_paths()` gives an installed engine's package and
  its `dist-info` beside it, none from the tree; `scope.INSTALLED` holds them and
  `scope.resolve(installed=…)` protects them as the engine's, and the configuration's
  writable-path check counts them, which no test exercises, the tree's engine having
  none. Unit, `test_change_workflow_documents.py` (an installed layout's package and
  its own `dist-info`, not another tool's; none for the tree),
  `test_change_workflow_scope.py` (an absent user skill directory protected from the
  adapter, given installed paths protected from the engine, the tree's engine
  protecting none) and `test_change_workflow_harness.py`: passed. External process,
  `test_change_workflow_sandbox.py` under `needs_bwrap`, run, not skipped: inside a
  writable `~/.claude`, editing an installed skill and adding one fail read-only
  while another write there succeeds, and a write to an installed package beneath
  the granted `~/.local/share/uv` fails while one beside it succeeds: passed.
- [x] 3.2 `install.py`: write the version's skills into each user skill directory,
  stamp each with the version, and keep a manifest of the names it wrote; remove a
  retired skill the manifest names; refuse, writing nothing, a skill of a shipped name
  the manifest does not record; and, in a checkout, write `.agents/workflow.local.toml`
  where none exists, from `.agents/workflow.local.template.toml` when present and
  otherwise as a skeleton naming each required local field, never overwriting one
  (D8, CW-1rhd, CW-sv3u). Verify: library integration tests under a temporary `HOME`,
  `scripts/tests/test_change_workflow_install.py` (new), every scenario of CW-1rhd and
  CW-sv3u.
  Done: `install.py`; the stamp is `.change-workflow-version` in each installed
  skill's directory and the manifest `.change-workflow-manifest.json` in each user
  skill directory, holding the version and the names written. An empty local file,
  the sandbox's empty form of an absent protected file, is written as an absent one;
  CW-sv3u's "MUST NOT overwrite a local configuration that exists" is read as one
  holding anything. Outside a repository no local file is written. `install` reads
  no configuration. Library integration, `test_change_workflow_install.py` (in-process
  `main`, temporary `HOME` and repositories, a temporary installed distribution):
  the skills, stamps, and manifest written into both directories; CW-1rhd's
  "A skill of the workflow's name is not the installer's" (refused, nothing written
  in either directory nor the local file) and "A later version retires a skill";
  CW-sv3u's two scenarios; an empty local file written; the skeleton naming the
  pointer and every model, which leaves every local field missing; nothing written
  outside a checkout; `install` run beside a range that refuses the engine and over
  stale skills: passed.
- [x] 3.3 Every subcommand but `install` and `--version` refuses when an installed
  skill's stamp differs from the engine's version, or a supported harness's user skill
  directory lacks a shipped skill or the manifest, naming what and `change-workflow
  install` (CW-1rhd). Verify: library integration cases in
  `test_change_workflow_install.py`.
  Done: `cli.main` refuses through `install.require_installed` before finding the
  repository, for every subcommand but `install`, the `openspec` pass-through and
  `check skills` included; `--version` exits while the arguments are parsed. The check applies to
  an installed engine alone: the engine run from its source tree
  (`scripts/change-workflow`) has the tree's own sources for skills, which no
  installation stamps, so it checks nothing installed — without this every engine
  command in this checkout, and every in-process test, would refuse until the
  owner installs. Library integration, `test_change_workflow_install.py`: CW-1rhd's
  "The engine is upgraded without its skills" (`next` refusing, naming 0.4.1, 0.4.2,
  and `change-workflow install`) and "A skill is missing" (Codex's `change-plan`),
  a directory without its manifest refusing `config --json`, `check skills` and
  `openspec --version` refusing over stale skills, and the tree's engine checking
  nothing: passed. External process, `test_change_workflow_wheel.py`: under a
  temporary `HOME` the installed command prints `--version`, refuses `config --json`
  until `change-workflow install` has run, then names every document: passed.
- [x] 3.4 `check skills` holds both halves: the installed skills as 3.3 checks them,
  and, for skills the repository commits, one source under `.agents/skills/` linked
  from each harness's project skill directory, asking no project link of the
  workflow's own sources (D21, CW-d8de). Verify: `test_check_agent_skills.py`.
  Done: `skills.problems(root, workflow)` asks no project link of the distribution's
  own skill names, whether or not one is there; the installed half is the check
  every subcommand of an installed engine makes first, `check skills` among them
  (3.3), so the module holds the committed half alone. Unit,
  `test_check_agent_skills.py` (the workflow's sources unlinked passing beside a
  committed skill that must still be linked; the running distribution's skills
  asked no link): passed. CW-d8de's "An installed skill is stale" through the
  command is 3.3's `check skills` case: passed. `make check-agent-skills` against the
  tracked links: passed.
- [ ] 3.5 Verify the section: its suites, with the repository's existing
  `make check-agent-skills` still passing against the tracked links, which section 4
  removes; and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites — `test_change_workflow_install.py`,
  `test_check_agent_skills.py`, `test_change_workflow_scope.py`,
  `test_change_workflow_sandbox.py`, `test_change_workflow_harness.py`,
  `test_change_workflow_documents.py`, `test_change_workflow_config.py`,
  `test_change_workflow_wheel.py`, `test_change_workflow_cli.py`,
  `test_change_workflow_command.py`, `test_change_workflow_hooks.py`: passed; `make
  check-agent-skills`: passed. `scripts/change-workflow run pre-commit`: `make
  validate-local` passed (packaging and every suite); the default checks and strict
  OpenSpec validation passed; `make check-repository` failed only on
  `check-spec-index` (section 8's index entries) and `check-doc-citations`, now
  naming `scripts/tests/test_change_workflow_citations.py` alone, which section 5
  creates.

Section 3 notes (handoff):

- Judgments for the round's review and triage, each departing from a requirement's
  letter:
  - Only an installed engine checks the installed skills (`install.require_installed`):
    CW-1rhd says every subcommand but `install` and `--version`, and CW-d8de that
    `check skills` holds both halves, neither naming the engine's form. The engine
    run from its source tree has the tree's sources for skills, which nothing
    stamps; checking there would refuse every command in a checkout until the owner
    installs, and every in-process test. Once 4.3 makes the fragment call
    `change-workflow`, every step and make target runs the installed engine and is
    checked; `scripts/change-workflow` stays unchecked until (iii) removes it. If the
    triage wants the letter kept, the delta's CW-1rhd and CW-d8de should say "of an
    installed engine" before section 8 promotes them.
  - An empty local file is no local configuration, to `install` and to `config`
    alike: the sandbox creates every absent protected path empty, the local file
    among them, and CW-sv3u's "MUST NOT overwrite a local configuration that exists"
    would otherwise leave a checkout stuck with an empty one. CW-sv3u could say so.
- The installed engine's protection is its package and its `dist-info`. A step
  whose writable paths hold the tool's environment (`~/.local/share/uv` here holds
  `uv tool`'s) can still add a `.pth` file or replace the entry script or the
  environment's interpreter beside them; section 8.3 should record this under the
  companion's "Current limits", or a later change protect the environment's root.
- Installing the workflow writes into the owner's real `~/.claude/skills/` and
  `~/.codex/skills/`; no session of this change did, the orchestrator's 4.1 does.
  Until then the tracked project links still load the skills from `.agents/skills/`.
- 4.1's install must run after the workspace's empty local file, if a step created
  one, is gone or empty: `install` writes over an empty one; `clone` replaces this
  change's clone's empty file with the link (section 2's handoff).
- The fresh-context check's findings fixed: "no longer ships" wording `make
  check-history-wording` refuses; stale help text for `check skills`; the installed
  half moved out of `skills.main`, where the gate before it made it unreachable;
  evidence gaps (an installed layout's paths, `--version` and `openspec` under stale
  skills, an existing local file with no template); an empty local file read as none
  by `config` too; wrapping. Declined: protecting the tool environment's root, which
  would also protect a shared environment the engine is installed into, recorded
  above for 8.3; amending the delta, which is the triage's to decide.

## 4. The switch: this repository runs the installed workflow

Delivers this repository's configuration in its new shape, the shape enforced, the
command on the path, and the workflow's project skill links gone, so every session
runs the workflow installed from the tree (D4, D5, D7, D8, D11, D15, D18; CW-r3ka,
CW-f8yy, CW-4pm4, CW-hu0z, CW-dvz5, CW-d8de). Touches `.agents/workflow.toml`,
`.claude/settings.json`, `.claude/skills/`, `.codex/skills/`, the eleven workflow
skills, `scripts/change_workflow/` (`config.py`, `cli.py`, `workflow.mk`), the
`Makefile`, `.github/workflows/tests.yml`, `docs/change-workflow-handbook.md`, and
their tests.

- [ ] 4.1 The orchestrator's, on the owner's word, before the section's session: edit
  the protected `.agents/workflow.toml` — add `[workflow] version = ">=0.1, <0.2"`,
  remove `[models]`, and make `load.common` name `docs/guidance/repository/` in place
  of `docs/guidance/` — and `.claude/settings.json`'s post-compaction hook to run
  `change-workflow hook post-compaction`; then install the tree's wheel and run
  `change-workflow install` in the workspace, writing the user skill directories and
  `.agents/workflow.local.toml` from the template (D5, D8, D11). The session commits
  both protected files with its section.
- [ ] 4.2 Enforce the shape: `[workflow] version` and `[guidance] engineering`
  required; a field in the wrong file refused, naming the file it belongs in; with no
  local file, `start` refuses, naming the missing field and `change-workflow install`,
  while `check config` and `config --json` report and exit 0 (D4, D5, D11; CW-f8yy,
  CW-4pm4, CW-hu0z). Verify: library integration cases in
  `test_change_workflow_config.py` and `test_change_workflow_cli_steps.py` ("Models are
  committed", "A step starts with no local configuration", "No range is declared").
- [ ] 4.3 `change-workflow fragment` prints the installed `workflow.mk`'s path, and the
  fragment's default becomes `CHANGE_WORKFLOW ?= change-workflow`; this repository's
  `Makefile` keeps including the in-tree fragment and gains `make install-workflow`,
  installing the tree's wheel with `uv tool install --force` and running
  `change-workflow install` (D8, D15, CW-dvz5). Verify: `test_change_workflow_cli.py`,
  `test_make_change_completion.py`, and `make install-workflow` in the section's
  handoff.
- [ ] 4.4 The eleven workflow skills, the handbook, and the fragment invoke
  `change-workflow …` in place of `scripts/change-workflow …`, which stays in the tree
  through this half (D8, CW-r3ka); remove the `change-*` and `guidance-review` links
  from `.claude/skills/` and `.codex/skills/`, the skills' sources staying under
  `.agents/skills/` for the wheel (D8, D18, CW-d8de). Verify:
  `test_change_workflow_assumptions.py` (the skills' targets and paths), `make
  check-agent-skills`, and `change-workflow check skills` after the orchestrator's
  reinstall.
- [ ] 4.5 `tests.yml`'s test job installs the tree's wheel and runs `change-workflow
  install` before `make`, so the scripts' suites and every engine command CI runs meet
  installed skills (D8). Verify: the job's definition in the handoff.
- [ ] 4.6 Verify the section: its suites; `scripts/change-workflow run pre-commit
  extract-change-workflow-repository` and `change-workflow config load implement`
  against the edited configuration; and the handoff naming that the orchestrator
  reinstalls (`make install-workflow`) before the next session, since the skills
  changed.
  End-to-end: none exercises the workflow's tooling; none owed.
  Owed by validation (ci tests.yml): the `test · test-deployment-packaging` job, run
  under `SANDBOX_REQUIRED=1`, its log showing the wheel installed from the tree,
  `change-workflow install` run, and the change workflow's suites passed with none of
  the sandbox tests skipped.

## 5. Citations by section and requirement id; unique engineering headings

Delivers the skills and the workflow's guidance citing engineering guidance by
section name, the workflow's guidance by section, and its specification by id, with
`check config`'s reports and the engineering guidance's repeated headings made unique
(D4, D6; CW-7x0z, CW-n8tr, CW-d2rw). Touches the eleven workflow skills,
`docs/guidance/workflow/*.md`, `docs/guidance/engineering/` (`integration-tests.md`,
`system-tests.md`, `contract-fixtures.md`, `test-levels.md`, `testing-python.md`)
and every citation of the renamed headings, `scripts/change_workflow/config.py`,
`scripts/check_guidance.py`, and their tests.

- [ ] 5.1 Make the three repeated headings unique — "Integration tests", "System
  tests", "Contract fixtures", each a file's title and a section of another — and
  re-point every citation of a renamed anchor (D4, 15 F5). Verify: `make
  check-guidance` (the anchor check) and no heading repeated beneath
  `docs/guidance/engineering/`, held by a unit test of 5.3's resolver over this
  repository's guidance.
- [ ] 5.2 The skills cite engineering guidance by section name, never a path or file
  name, the workflow's guidance by section, and the workflow's specification by
  requirement id; the workflow's guidance names engineering guidance in prose by
  section, with no link (D4, D6; CW-7x0z, CW-n8tr, CW-d2rw). Verify:
  `test_change_workflow_assumptions.py`, extended to fail on any path into
  `docs/guidance/` in a skill ("A skill names an engineering guidance file").
- [ ] 5.3 `check config` reports each engineering section a shipped skill cites that
  no file beneath the pointer heads, and each that several sections head, naming the
  files, exiting 0 for both (CW-7x0z). Verify: library integration cases in
  `test_change_workflow_config.py` ("A user's guidance lacks a cited section", "A cited
  section name repeats").
- [ ] 5.4 The guidance check refuses a link from workflow guidance to engineering
  guidance (CW-d2rw, MCW-c4ek's link rule). Verify: `test_check_guidance.py` and `make
  check-guidance`.
- [ ] 5.5 The distribution's test fails on a skill citing a section of the workflow's
  guidance that the installed guidance does not head (CW-lm42). Verify:
  `scripts/tests/test_change_workflow_citations.py` (new); its requirement-id half is
  section 8's.
- [ ] 5.6 Verify the section: its suites, `make check-guidance`, and `scripts/change-workflow
  run pre-commit extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.

## 6. Two default checks moved into the engine, and the roles as structured output

Delivers `spec-index` and `decisions` as default checks, the delta paths in `check
spec-index --json`, and `roles` in `config --json`, read by this repository's
assumptions test (D10, D14; CW-c8lw, CW-368t, CW-ora1, MCW-5tgp). Touches
`scripts/change_workflow/` (new `spec_index.py` and `decisions.py`, `config.py`,
`hooks.py`, `cli.py`), `scripts/check_spec_index.py`,
`scripts/check_decision_destinations.py`, `scripts/check_doc_citations.py`,
`scripts/check_change.py`, the `Makefile`, `scripts/tests/test_change_workflow_assumptions.py`,
and their tests.

- [ ] 6.1 The orchestrator's, on the owner's word, before the section's session:
  `make install-workflow`, so the session runs the skills section 5 rewrote.
- [ ] 6.2 Move the specification index check and the decision destinations check into
  the engine as `spec-index` and `decisions`, run by `pre-commit` and `check change`
  before the declared commands and turned off only by name; `make check-repository`
  stops running them, and `make check-spec-index` and `make
  check-decision-destinations` call the engine; the two scripts go (D10, CW-c8lw).
  Verify: `test_check_spec_index.py` and `test_check_decision_destinations.py` moved to
  the engine's command, `test_change_workflow_hooks.py` (six default checks, "A
  decision names no destination"), `test_check_change.py`.
- [ ] 6.3 `check spec-index <change> --json` reports the specification paths the
  change's deltas create, and `scripts/check_doc_citations.py` reads them in place of
  importing a delta reader (D10, CW-368t). Verify: `test_check_doc_citations.py`
  ("A citation check meets a specification the change creates").
- [ ] 6.4 `config --json` lists `roles`, each role by name with the configuration
  fields that provide it; the distribution's test holds the companion's roles table to
  it; `test_change_workflow_assumptions.py` reads the roles from `config --json` and the
  fragment from `change-workflow fragment`, with no local configuration (D14; CW-ora1,
  MCW-5tgp). Verify: `test_change_workflow_config.py` and
  `test_change_workflow_assumptions.py` ("The workflow adds a role").
- [ ] 6.5 Verify the section: its suites, and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`, the two checks now run by the engine.
  End-to-end: none exercises the workflow's tooling; none owed.

## 7. The workflow's documents self-contained, and the move's procedure

Delivers documents the coordinator can lift whole, the handbook's procedures for
installing, crossing, and the move, and the workflow's tests runnable without this
repository's other files (D6, D7, D8, D16, D17, D18). Touches
`openspec/specs/change-workflow/README.md`, `docs/guidance/workflow/*.md`,
`docs/change-workflow-handbook.md`, and the workflow's tests and fixtures under
`scripts/tests/`.

- [ ] 7.1 The workflow's documents link only within their own set: the companion's
  four links to `market-change-workflow` become neutral text about an adopting
  repository's own capability, and no workflow document links to this repository's
  documents (D6). Verify: a unit test over the wheel's document set,
  `test_change_workflow_citations.py`, failing on a relative link leaving it.
- [ ] 7.2 The workflow's tests and fixtures name the files they need from the
  workflow's own set, and run with only the paths section 7.3 lists present (D16, D17).
  Verify: the workflow's suites run from a temporary checkout holding only those paths,
  recorded in the handoff.
- [ ] 7.3 The handbook gains: installing the workflow and the local configuration;
  that one version is installed per machine, managed like any tool a repository pins,
  each repository declaring its range (D7, D8, the owner's principle); when an open
  change crosses to the installed workflow (D18); and the procedure for the move —
  the exact path list the coordinator lifts with `git filter-repo`, keeping paths, the
  wheel's project file to rename to the new repository's root, and the test for which
  settings are local, for the workflow repository's own repository guidance (D5, D16,
  D17). Verify: the path list matches what the wheel packages plus its tests, held by
  `test_change_workflow_wheel.py`.
- [ ] 7.4 Verify the section: its suites and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.

## 8. The specification, its companion, and its diagrams current for the release

Delivers the `change-workflow` delta applied to the permanent specification with its
index entries, the companion's promotions and its diagrams redrawn, and the
distribution's test of cited requirement ids, so the release carries its own
documents (D20, D23; every requirement of the `change-workflow` delta; CW-lm42).
Touches `openspec/specs/change-workflow/` (`spec.md`, `index.md`, `README.md`,
`diagrams/`), and `test_change_workflow_citations.py`.

- [ ] 8.1 Apply the `change-workflow` delta to `openspec/specs/change-workflow/spec.md`
  by hand: the twelve added requirements (CW-5kl9, CW-lm42, CW-f8yy, CW-1rhd, CW-sv3u,
  CW-4pm4, CW-hu0z, CW-7x0z, CW-d867, CW-dvz5, CW-ora1, CW-368t) and the eight modified
  (CW-r3ka, CW-d8de, CW-f3qk, CW-c8lw, CW-l7hn, CW-d2rw, CW-n8tr, CW-r6kd), each as the
  delta words it (D23). Verify: `make check-spec-index` and a diff of each requirement
  against its delta in the handoff.
- [ ] 8.2 Write `index.md`'s entries as promotion would: under 4, "The command"
  CW-dvz5, "Hooks" CW-368t, "The log and its format" CW-d867, "Skills from one source"
  CW-1rhd; under 5, "The engine's interfaces" CW-5kl9 and CW-lm42, "Compatibility"
  CW-f8yy, "A repository's configuration" CW-sv3u and CW-4pm4, "The repository's
  guidance" CW-hu0z and CW-7x0z, "What an adopting repository provides" CW-ora1; each
  modified requirement's summary revised where it no longer holds; no id retired (D23).
  Verify: `make check-spec-index CHANGE=extract-change-workflow-repository`.
- [ ] 8.3 Promote to the companion, `openspec/specs/change-workflow/README.md`, each
  destination the proposal's knowledge to promote names there, before the release is
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
- [ ] 8.4 Redraw `change-workflow-engine-parts.drawio` and the step run's diagram, and
  export both SVGs: the evidence modules, the actions and hooks around a step, the
  configuration's validation entries as entries, not parts, and the parts this change
  adds (D20). Verify: `change-workflow check graph` and the SVGs open in the
  companion.
- [ ] 8.5 The distribution's test fails on a `CW-` id a skill or the workflow's
  guidance cites that `workflow.specification` does not hold (CW-lm42). Verify:
  `test_change_workflow_citations.py`.
- [ ] 8.6 Verify the first half whole: `make test-release-tooling`, `make
  check-change CHANGE=extract-change-workflow-repository`, the wheel rebuilt and
  installed from the tree with `make install-workflow` and `change-workflow config
  --json` naming every document, and the handoff stating that the first half is
  complete on its own for the preliminary pull request (D1).
  End-to-end: none exercises the workflow's tooling; none owed.

## 9. The gate, and the switch to the released workflow

Delivers this repository on the coordinator's release, with no copy of the workflow
in its tree (D2, D7, D11, D15, D24; MCW-9k0c). Touches `.agents/workflow.toml`, the
`Makefile`, `.github/workflows/tests.yml`, `AGENTS.md`'s exceptions table,
`scripts/check_project_layout.py`, and removes `scripts/change-workflow`,
`scripts/change_workflow/`, `scripts/change-workflow-wheel/`, the workflow's tests
and fixtures under `scripts/tests/`, `.agents/skills/change-*`,
`.agents/skills/guidance-review`, `.agents/change-outcome.schema.json`,
`docs/guidance/workflow/`, `openspec/specs/change-workflow/`, and
`docs/change-workflow-handbook.md`.

- [ ] 9.1 Decision gate (D2): record in this task's note the coordinator's evidence —
  the workflow repository's public URL; the release's tag, its commit, and the
  distribution's version; the release's artifact named by distribution, version, and
  digest, never by the registry's host, project, or path; and how to install it,
  keeping out of the tree any guide naming the registry. Before writing anything
  else, check it: the tag resolves to the commit in the public repository, the
  artifact of that version and digest is fetchable, and the install the guide gives
  succeeds. End the session `stopped`, naming what is missing, when any of it is
  absent or fails.
- [ ] 9.2 The orchestrator's, on the owner's word, once 9.1 passes: set the protected
  `.agents/workflow.toml`'s `[workflow] version` to the release's line (D11), and
  install the release and run `change-workflow install`. The session commits the file
  with its section.
- [ ] 9.3 Remove the workflow's copy from the tree, its tests and fixtures with it;
  the `Makefile` includes `$(shell change-workflow fragment)`, saying when the command
  is missing, and drops `make install-workflow`; `tests.yml` installs the release from
  the public repository's tag the gate records; `make check-repository`'s remaining
  checks call `change-workflow` (D7, D15; MCW-9k0c).
- [ ] 9.4 Remove the `overrides` row from `AGENTS.md` and the layout check's
  admission of the wheel (D24). Verify: `test_check_project_layout.py` and `make
  check-guidance`.
- [ ] 9.5 Verify the section: `make test-release-tooling`, `change-workflow
  --version` within the range, `make check-change
  CHANGE=extract-change-workflow-repository` passing but for the citations section 10
  rewrites, and no tracked path left of those this section removes.
  End-to-end: none exercises the workflow's tooling; none owed.
  Owed by validation (ci tests.yml): the `test · test-deployment-packaging` job, its
  log showing the release installed from the public repository's tag and the
  repository's scripts' suites passed.

## 10. This repository's documents cite the workflow, and `market-change-workflow` amended

Delivers every document of this repository citing the workflow in prose, and its own
capability amended by hand (D6, D14, D23; MCW-5tgp, MCW-9k0c, MCW-iqh1). Touches the
documents outside the archive that cite `openspec/specs/change-workflow/` or
`docs/guidance/workflow/` (`AGENTS.md`, `openspec/README.md`,
`openspec/specs/README.md`, `docs/development/ARCHITECTURE.md`, the capabilities'
documents, the repository guidance), and `openspec/specs/market-change-workflow/`
(`spec.md`, `index.md`, `README.md`).

- [ ] 10.1 Rewrite each citation of the workflow's specification, companion,
  guidance, or handbook in prose by name, requirement id, and section, with one link
  to the workflow's repository where a document first names it; `AGENTS.md` names the
  installed workflow, its range, and the local configuration in place of
  `.agents/skills/` and the in-tree specification; `openspec/specs/README.md` drops
  `change-workflow`'s row (D6, MCW-9k0c). Verify: `make check-doc-citations` unscoped
  naming no path the second half removed, and `make check-capability-index`.
- [ ] 10.2 Apply the `market-change-workflow` delta to its `spec.md` by hand — MCW-9k0c
  and MCW-iqh1 added, MCW-5tgp modified — and write their `index.md` entries under "1.
  The workflow's roles" (MCW-5tgp's summary revised) and "4. This repository's
  workflow values" (MCW-9k0c, MCW-iqh1) (D23). Verify: `make check-spec-index
  CHANGE=extract-change-workflow-repository` and a diff against the delta in the
  handoff.
- [ ] 10.3 Amend `market-change-workflow`'s companion: "This repository is the
  workflow's first adopter" (it adopts the released workflow within its range), "How
  this repository provides the workflow's roles" (both configuration files, the roles
  read from `config --json`), "The engine's own assumptions" (no path of the engine's
  left in the tree), and "What each check enforces" (the two checks now the engine's)
  (D10, D14). Verify: `make check-doc-citations
  CHANGE=extract-change-workflow-repository`.
- [ ] 10.4 Verify the section: `make check-change
  CHANGE=extract-change-workflow-repository`, `make check-guidance`, and `make
  test-release-tooling`.
  End-to-end: none exercises the workflow's tooling; none owed.

## 11. Closeout

- [ ] 11.1 Comment hygiene: run `make check-comment-hygiene`; any finding, or a
  comment the change added that still names history or the change, returns the change
  to implementation.
- [ ] 11.2 Import placement: check the imports the change added in this repository's
  scripts against the engineering guidance's "Imports go at module level"; one that
  should move returns the change to implementation.
- [ ] 11.3 Documentation compliance: re-check D1–D24 against the workflow's placement
  rules and `openspec/README.md`'s placement table, and that each document the change
  wrote here describes the current state.
- [ ] 11.4 Narrative compression: shorten completed task notes to final behaviour,
  the gate's evidence (9.1), material validation evidence, and destinations.
- [ ] 11.5 Roadmap currency: no roadmap goal holds the change workflow; record that
  disposition in the design-promotion record.
- [ ] 11.6 Campaign index currency: in `openspec/changes/README.md`, the lesser goal
  "Make the change workflow a tool any repository can adopt" — its current state
  saying this repository adopts the workflow from its repository within its declared
  range; the gap rows "The workflow is not a separately versioned distribution" and
  the diagrams' redraw closed; each open workflow change's row noting that it moves to
  the workflow's repository; this change's row updated (D19). Run `make
  check-change-index`.
- [ ] 11.7 Packaging: `make check-packaging`, `make check-architecture-change
  CHANGE=extract-change-workflow-repository`, and `make check-agent-skills`, since the
  change touched `.agents/`, `.claude/`, and `.codex/`.
- [ ] 11.8 End-to-end pipeline: record the pipeline run the latest passing validation
  gathered, with its result; no scenario exercises the change's behaviour.
- [ ] 11.9 Promotion: complete the design-promotion record. In this repository
  write: `docs/development/ARCHITECTURE.md`, a new "The change workflow" subsection
  under "Build, packaging, and initialization", for how this repository adopts the
  workflow; and confirm the destinations already written — the `change-workflow`
  specification, index, companion, diagrams, and handbook in section 8 and 7.3, now
  in the workflow's repository, and `market-change-workflow` in section 10. Record D2,
  D17, D22, D23, and D24 as having no permanent destination, as the proposal says.
- [ ] 11.10 Guidance placement: read the guidance sections the change added, moved,
  or rewrote — the renamed engineering headings, `AGENTS.md`'s rows — against the
  layer test, adjacency, and exception placement; run `make check-guidance`.
- [ ] 11.11 Documentation citations: `make check-doc-citations
  CHANGE=extract-change-workflow-repository`, every match resolved; then
  `change-workflow openspec validate extract-change-workflow-repository --strict`,
  the installed command having replaced `scripts/change-workflow`.
- [ ] 11.12 Archival: archive with `--skip-specs`, both capabilities' specifications
  having been written by hand (D23): `change-workflow openspec archive
  extract-change-workflow-repository -y --skip-specs`; the delta files stay in the
  archived change as its record.
