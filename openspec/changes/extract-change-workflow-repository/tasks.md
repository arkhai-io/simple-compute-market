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
  and `test_change_workflow_citations.py`, which sections 3 and 5
  create). Correction: the index check names fourteen ids, the `market-change-workflow`
  delta's two among them, which 10.2 indexes; the citation of a test file a later
  section creates is now by its bare name, which the citations check does not resolve.

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
- [x] 2.7 Verify the section: its suites, and `scripts/change-workflow run
  pre-commit extract-change-workflow-repository` with this repository's configuration
  unchanged, which still passes.
  End-to-end: none exercises the workflow's tooling; none owed.
  Checked by a later session on the evidence below and in 3.5's note. Of the two
  `check-repository` failures, the citations of files later sections create are now
  cited by their bare names; the index check still fails on the fourteen ids the
  change's deltas add, which 8.2 and 10.2 index, the gap
  `pass-checks-at-every-commit` owns, as 1.6 was checked through it.
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
  `test_change_workflow_citations.py`, which sections 3 and 5 create.

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
- [x] 3.5 Verify the section: its suites, with the repository's existing
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
  naming `test_change_workflow_citations.py` alone, which section 5
  creates.
  Re-verified by a fresh session on `c1d30dd59` with 4.1's edits uncommitted beside
  it (below), the tree of that pre-commit run
  (`2afff8a8`, `make validate-local` exit 0 in the change's log) differing from the
  commit's only in `tasks.md`: sections 1–3's suites together — the twenty files
  named in 1.2–1.6, 2.7, and this task — 1,469 passed, none skipped, the sandbox
  tests run; `make check-agent-skills`: passed; `make check-repository` failing on
  the same two checks alone, until the citation of section 5's test file became its
  bare name, as 7.1 and 8.5 cite it, leaving the index check alone failing.
  `scripts/change-workflow run pre-commit` then: `make lock` passed; `make
  validate-local` ran packaging and every suite to the end, each passing (3,684
  scripts' tests among them, no failure in its log), and was marked failed only by
  its tree guard, since `tasks.md` was edited during the run; the default checks and
  strict OpenSpec validation passed; `make check-repository` failed on the index
  check alone. These runs had 4.1's uncommitted edits of
  `.agents/workflow.toml` and `.claude/settings.json` in the worktree, with the
  local file `change-workflow install` wrote, so the configuration-unchanged run
  remains the earlier one; the suites passing under both shapes is what section 2's
  handoff expects.

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

- [x] 4.1 The orchestrator's, on the owner's word, before the section's session: edit
  the protected `.agents/workflow.toml` — add `[workflow] version = ">=0.1, <0.2"`,
  remove `[models]`, and make `load.common` name `docs/guidance/repository/` in place
  of `docs/guidance/` — and `.claude/settings.json`'s post-compaction hook to run
  `change-workflow hook post-compaction`; then install the tree's wheel and run
  `change-workflow install` in the workspace, writing the user skill directories and
  `.agents/workflow.local.toml` from the template (D5, D8, D11). The session commits
  both protected files with its section.
  Done by the orchestrator on the owner's word: both files' edits were in the worktree
  as the task gives them, and are committed with the section. The tree's wheel
  (0.1.0, built before this section's edits) was installed and `change-workflow
  install` run in this change's clone only, not the workspace, by the owner's
  direction, so the clone's local file is its own, written from the template, and
  the clone's link to the workspace's local file was not made.
- [x] 4.2 Enforce the shape: `[workflow] version` and `[guidance] engineering`
  required; a field in the wrong file refused, naming the file it belongs in; with no
  local file, `start` refuses, naming the missing field and `change-workflow install`,
  while `check config` and `config --json` report and exit 0 (D4, D5, D11; CW-f8yy,
  CW-4pm4, CW-hu0z). Verify: library integration cases in
  `test_change_workflow_config.py` and `test_change_workflow_cli_steps.py` ("Models are
  committed", "A step starts with no local configuration", "No range is declared").
  Done: `config.check` refuses a committed file declaring no `workflow.version`
  (`committed=True`; `load` passes false when only a local file exists, so a checkout
  with no committed file still reads as every field absent), right after the range is
  read; `[models]` and `[guidance]` in the committed file are refused naming
  `.agents/workflow.local.toml`, and `models` is no committed table, so a step's
  models are declared once by construction. `require` names each missing field with
  the file it belongs in, a local one with `change-workflow install`;
  `require_for_step` asks the pointer of every step and the orchestrating session,
  and the step's models of an unattended run as before; the review asks the pointer
  and its models before it reads them; and `Configuration.documents`, which `config
  load` and the post-compaction hook print, asks the pointer, since an interactive
  session, which no `start` guards, would otherwise read no engineering guidance and
  not know it. `check config` prints, after its OK line, a `MISSING:` line naming
  each local field the checkout lacks, exiting 0; `config --json` is unchanged.
  Library integration, `test_change_workflow_config.py` (in-process `main` over
  temporary checkouts): "Models are committed" and "No range is declared", each
  through `config --json`, `check config`, and `config load`; "CI checks the
  configuration" (no local file: exit 0, the missing line, a committed fault still
  refused); a complete local file reporting nothing missing; `config load plan` with
  no pointer refused, naming it and `change-workflow install`; no committed file,
  with and without a local file beside it, asking no range; `start design
  --unattended` with neither file refused for the protected branches, the pointer,
  and the models, each with its file: passed. Unit, the same file: `[models]` and
  `[guidance]` in a committed text refused naming the local file; `require_for_step`
  for an interactive step, an unattended one, and the orchestrating session: passed.
  `test_change_workflow_cli_steps.py`: "A step starts with no local configuration" —
  unattended, refused naming `guidance.engineering`, `models.design`, and
  `change-workflow install`; interactive, the pointer; nothing launched or logged:
  passed. `test_change_workflow_cli.py`: `start orchestrate` with models but no
  pointer refused, launching nothing: passed. `test_change_workflow_review.py`: a
  review with no pointer refused before any reviewer runs: passed.
  `test_post_compaction_context.py`: with no local file, the hook names the pointer
  and `change-workflow install` and still tells the session to re-read; with a
  pointer applying none, it names the workflow's guidance: passed.
  The test configuration now has two files: `change_workflow_fixtures.configured`
  writes `ACCEPTED`, the range `>=0.1`, before a committed text declaring none, and
  the local file `LOCAL_CONFIGURED` (the pointer as `none`, and every step's models)
  unless given `local=None`, excluded from Git as the repository ignores it;
  `configuration_checked` is `config.check` of a text so opened, for a unit test of
  anything but the range. The tests of this repository's own configuration read it
  as its template's install leaves it (`as_installed`), not the developer's own
  local file.
- [x] 4.3 `change-workflow fragment` prints the installed `workflow.mk`'s path, and the
  fragment's default becomes `CHANGE_WORKFLOW ?= change-workflow`; this repository's
  `Makefile` keeps including the in-tree fragment and gains `make install-workflow`,
  installing the tree's wheel with `uv tool install --force` and running
  `change-workflow install` (D8, D15, CW-dvz5). Verify: `test_change_workflow_cli.py`,
  `test_make_change_completion.py`, and `make install-workflow` in the section's
  handoff.
  Done: `fragment` prints `Distribution.path("fragment")` and reads no
  configuration, though, like every subcommand but `install` and `--version`, it
  needs a repository and installed skills of its version. The fragment's
  `CHANGE_WORKFLOW ?= change-workflow`, its header naming the installed command and
  CW-r3ka and CW-dvz5 rather than a tree path. The root `Makefile` keeps
  `include scripts/change_workflow/workflow.mk`; `make install-workflow` runs `uv tool
  install --force --reinstall scripts/change-workflow-wheel` — `--reinstall`, since an
  edit of the engine or a skill keeps the version, and uv would otherwise keep the
  build it has — then `change-workflow install`; `check-change` calls
  `$(CHANGE_WORKFLOW)`, so it runs the installed engine like the fragment's targets.
  Library integration, `test_change_workflow_cli.py`: `fragment` prints the
  distribution's fragment in a checkout whose configuration `config` refuses; every
  fragment target's dry run now calls `change-workflow`: passed. External process:
  `test_change_workflow_cli.py`, a Makefile including the fragment at the path the
  tree's command prints dry-runs `design` as `change-workflow start design "X"`; and
  `test_change_workflow_wheel.py`, CW-dvz5's scenario on the installed command — its
  `fragment` prints the `fragment` role `config --json` names, inside the tool
  directory, and a Makefile holding `include $(shell <installed> fragment)` dry-runs
  `design` as `change-workflow start design "X"`: passed.
  `test_make_change_completion.py`: passed. `make install-workflow` run with
  `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, and `HOME` in a temporary directory and its bin
  first on `PATH`, since the real `~/.claude/skills/` and `~/.codex/skills/` are
  protected from this step: it built and installed `arkhai-change-workflow==0.1.0`
  from the tree, then wrote 11 skills of 0.1.0 into each user skill directory, each
  stamped 0.1.0, and left the checkout's existing local file alone; the installed
  `fragment` printed the tool directory's `workflow.mk`.
- [x] 4.4 The eleven workflow skills, the handbook, and the fragment invoke
  `change-workflow …` in place of `scripts/change-workflow …`, which stays in the tree
  through this half (D8, CW-r3ka); remove the `change-*` and `guidance-review` links
  from `.claude/skills/` and `.codex/skills/`, the skills' sources staying under
  `.agents/skills/` for the wheel (D8, D18, CW-d8de). Verify:
  `test_change_workflow_assumptions.py` (the skills' targets and paths), `make
  check-agent-skills`, and `change-workflow check skills` after the orchestrator's
  reinstall.
  Done: every `scripts/change-workflow` in the eleven skills and the handbook reads
  `change-workflow`, and the orchestrating skill's clone paragraph no longer names a
  path to the command. The engine's own messages and docstrings name it too — the
  unattended preamble, the review's, the next-step computation's `convert` and
  `record` hints, the log's conversion refusal, the guarded push's refusal, and
  `config`'s default-check commands — so what a session is told to run is the
  command every step runs. The 22 links went with `git rm`; OpenSpec's six stay.
  The handbook's "Customization" now gives the committed and local files and the
  installed skills, and `market-change-workflow`'s companion rows on the command and
  the skills' source say what is installed and what stays in the tree.
  `check skills` now refuses a project skill entry of a workflow skill's name, link
  or copy, which CW-d8de rules out, so a branch merging the old links back fails it;
  the post-compaction hook no longer names `.agents/skills/<skill>/SKILL.md` as the
  skill to re-read.
  `test_change_workflow_assumptions.py` no longer admits `scripts/change-workflow` as
  the engine's (`ENGINE`), so a skill naming the tree's command fails, naming it:
  passed, with the new case. Unit, `test_check_agent_skills.py`: the workflow's
  sources asking no link, and a link and a copy of `change-plan` refused in each
  harness: passed. `scripts/change-workflow check skills` against the tracked
  links: passed; `make check-agent-skills`, through the installed 0.1.0 engine built
  before this section, which lacks the new refusal: passed. `change-workflow check
  skills` after the reinstall is the orchestrator's, before the next session (4.6).
- [x] 4.5 `tests.yml`'s test job installs the tree's wheel and runs `change-workflow
  install` before `make`, so the scripts' suites and every engine command CI runs meet
  installed skills (D8). Verify: the job's definition in the handoff.
  Done: the `test` job's `test-deployment-packaging` entry, the one whose `make`
  runs `test-release-tooling`, gains after `make dist-ci` a step "Install the change
  workflow from the tree": `uv tool install --force scripts/change-workflow-wheel`,
  the tool's bin directory (`uv tool dir --bin`) added to `GITHUB_PATH`, and
  `change-workflow install` run from `$RUNNER_TEMP`, outside the checkout, so it
  writes the skills and no local file, and CI checks the committed configuration
  alone, as D5 has it. What it proves is that the workflow installs from the tree
  and that a make target calling `change-workflow` finds it: the scripts' suites
  run the tree's package or `scripts/change-workflow`, which checks nothing
  installed, and the root Makefile's target the graph test runs is given the tree's
  command. Unit, `test_tests_workflow.py` (the install step conditioned on that
  entry, before the `make` step, its `change-workflow install` run outside the
  checkout, and that entry running `test-release-tooling`): passed; the job's
  definition is the step as quoted here.
- [x] 4.6 Verify the section: its suites; `scripts/change-workflow run pre-commit
  extract-change-workflow-repository` and `change-workflow config load implement`
  against the edited configuration; and the handoff naming that the orchestrator
  reinstalls (`make install-workflow`) before the next session, since the skills
  changed.
  End-to-end: none exercises the workflow's tooling; none owed.
  Owed by validation (ci tests.yml): the `test · test-deployment-packaging` job, run
  under `SANDBOX_REQUIRED=1`, its log showing the wheel installed from the tree,
  `change-workflow install` run, and the change workflow's suites passed with none of
  the sandbox tests skipped.
  Done: the section's suites, each after its last edit — `test_change_workflow_config.py`,
  `test_change_workflow_cli_steps.py`, `test_change_workflow_cli.py`,
  `test_change_workflow_review.py`, `test_change_workflow_wheel.py`,
  `test_make_change_completion.py`, `test_change_workflow_assumptions.py`,
  `test_check_agent_skills.py`, `test_tests_workflow.py`,
  `test_post_compaction_context.py`, `test_change_workflow_graph.py`, and the
  suites whose fixtures changed: passed. `scripts/change-workflow run pre-commit`
  against the edited configuration: `make lock` passed, changing no lock; `make
  validate-local` passed — packaging, and every suite, the scripts' 3,700 passing,
  none skipped; the default checks and the strict OpenSpec validation passed; `make
  check-repository` failed on `check-spec-index` alone, the fourteen ids of the
  change's deltas that 8.2 and 10.2 index. `change-workflow config load implement`,
  the installed engine, and `scripts/change-workflow config load implement` each
  print the 84 documents, the pointer's engineering guidance first, then the
  workflow's, then `load.common`, each once; `scripts/change-workflow check config`:
  passed. The orchestrator's reinstall is in the handoff below.

Section 4 notes (handoff):

- The orchestrator reinstalls before the next session runs a step, since the skills,
  the engine, and the fragment changed: `make install-workflow` in the workspace and
  in this clone. The installed stamp is the version, which this section keeps at
  0.1.0, so the skills as installed before it pass every stamp check while their
  text is the old one; `make check-agent-skills` passed through that older
  installation, which lacks the new project-entry refusal. A developer reinstalls
  after each engine or skill edit, and 6.1 is that reinstall for section 6.
- Judgments for the round's review and triage, each reading a requirement's letter:
  - CW-4pm4's "A step starts with no local configuration" says `start design`
    names the missing models. An unattended run does; an interactive one, which runs
    on the owner's own model, names the pointer alone, since requiring a model it
    does not use would refuse what the step does not need. The delta could say "an
    unattended `start design`" before section 8 promotes it.
  - CW-hu0z's pointer is required by `config load` and the post-compaction hook as
    well as by `start` and the review: D7 notes interactive sessions never pass
    through `start`, and without it they would read no engineering guidance and not
    know it. `check config` and `config --json` still report it missing and exit 0.
  - CW-f8yy's "No range is declared" is read for a committed file: a checkout with
    no committed configuration declares no field, the range among them, whether or
    not a local file is beside it.
  - `fragment` is refused, like every subcommand but `install` and `--version`,
    while the installed skills are stale, as CW-1rhd's letter has it. For (iii)'s
    `include $(shell change-workflow fragment)`, make then shows that refusal,
    naming `change-workflow install`, before its own error on the empty include.
- Outside the plan, each small beside the switch it follows from: the engine's own
  messages name `change-workflow` (4.4); `check skills` refuses a project entry of a
  workflow skill's name, CW-d8de's letter, which section 3 left unchecked; the
  documents the switch made false are corrected — `AGENTS.md`'s "What every session
  reads", `openspec/README.md`'s check table, `market-change-workflow`'s companion
  (the default checks' and pre-commit's commands, the guidance every step reads, the
  engine's command and the skills' source), the workflow guidance's closeout command
  names, and the handbook's "Customization"; the graph target's test runs it with
  `CHANGE_WORKFLOW=scripts/change-workflow`, so it checks the tree's diagram rather
  than whatever the machine has installed; and the tests of this repository's own
  configuration read it through its template (`as_installed`), since CI's checkout
  has no local file and a developer's may differ.
- Left for later sections, each recorded where it is owned: `.agents/workflow.toml`'s
  `[openspec]` comment still names `scripts/change-workflow openspec`, a protected
  file the orchestrator may correct; `market-change-workflow`'s `spec.md` names
  `scripts/change-workflow` in three scenarios, normative text section 10 amends with
  that capability's delta; `change-workflow`'s specification, companion, and index
  name it throughout, section 8's; the orchestrating skill cites
  `scripts/change_workflow/next_step.py` and `graph.py`, which section 5's citations
  by requirement id replace; and the handbook's procedure for installing is 7.3's.
- The repository's own suites `test_check_secrets.py`, `test_check_public_content.py`,
  and `test_validate_parallel.py` write the range into their configurations as a
  literal, not from the workflow's fixtures, which leave with the workflow (9.3).
- The fresh-context check's findings fixed: CW-d8de's project entries unrefused;
  overstated 4.2, 4.3, and 4.5 evidence (each claim now names the test that shows
  it, and the orchestrating session's and local-file-only cases gained tests);
  CI's install writing a local file into its checkout; the pointer unenforced in
  `config load`; documents the switch made false; the repository's suites importing
  the workflow's fixtures; comment and wording nits. Declined: `install-workflow`
  calling `$(CHANGE_WORKFLOW) install`, since the recipe runs the command it has just
  installed, whatever `CHANGE_WORKFLOW` names.

## 5. Citations by section and requirement id; unique engineering headings

Delivers the skills and the workflow's guidance citing engineering guidance by
section name, the workflow's guidance by section, and its specification by id, with
`check config`'s reports and the engineering guidance's repeated headings made unique
(D4, D6; CW-7x0z, CW-n8tr, CW-d2rw). Touches the eleven workflow skills,
`docs/guidance/workflow/*.md`, `docs/guidance/engineering/` (`integration-tests.md`,
`system-tests.md`, `contract-fixtures.md`, `test-levels.md`, `testing-python.md`)
and every citation of the renamed headings, `scripts/change_workflow/config.py`,
`scripts/check_guidance.py`, and their tests.

- [x] 5.1 Make the three repeated headings unique — "Integration tests", "System
  tests", "Contract fixtures", each a file's title and a section of another — and
  re-point every citation of a renamed anchor (D4, 15 F5). Verify: `make
  check-guidance` (the anchor check) and no heading repeated beneath
  `docs/guidance/engineering/`, held by a unit test of 5.3's resolver over this
  repository's guidance.
  Done: the two files' titles give way, since the level sections of
  `test-levels.md` keep the parallel "Unit tests", "Integration tests", "Smoke
  tests", "System tests", which other documents cite in prose: `integration-tests.md`
  is "Application integration tests", the rules it holds; `system-tests.md` "System
  test scenarios"; and `testing-python.md`'s section, the Python names and places of
  the fixtures `contract-fixtures.md` defines, "Contract fixture modules", its one
  citation, in `docs/guidance/repository/test-placement.md`, re-pointed, and the
  link texts naming the two files by their old titles follow them. Content check,
  `test_check_guidance.py`: no heading beneath `docs/guidance/engineering/` heads two
  sections, read with the guidance check's own heading syntax over the real tree.
  Library integration, the same file, the plan's resolver test: the workflow's
  `check config`, run as a process in a temporary checkout whose pointer is a link
  to this repository's engineering guidance, which its `config --json` shows it
  reads, reports no cited section unresolved or ambiguous: passed. `make
  check-guidance`: passed. Both live among this repository's tests, reaching the
  engine through its command (CW-r3ka), since the engineering guidance is this
  repository's and leaves with no workflow.
- [x] 5.2 The skills cite engineering guidance by section name, never a path or file
  name, the workflow's guidance by section, and the workflow's specification by
  requirement id; the workflow's guidance names engineering guidance in prose by
  section, with no link (D4, D6; CW-7x0z, CW-n8tr, CW-d2rw). Verify:
  `test_change_workflow_assumptions.py`, extended to fail on any path into
  `docs/guidance/` in a skill ("A skill names an engineering guidance file").
  Done: every path into `docs/guidance/` in the eleven skills is now a citation by
  section name, in one form the engine parses — `the engineering guidance's section
  "Imports go at module level"`, `the workflow guidance's sections "Comment hygiene"
  and "Import placement"` — eleven engineering sections and fourteen of the
  workflow's, each heading one section; a file cited whole cites its title, or, for
  `comments.md`, `documentation.md`, `testing.md`, and `dependencies-python.md`, the
  section the sentence relies on. The orchestrating skill's paths into
  `scripts/change_workflow/` went: the graph is cited as CW-ak1z and CW-66kx, and
  the computation's results are the skill's own sections that route on them, since
  no requirement words the result's shape. The seven links from the workflow's
  guidance to engineering guidance became the sections' names in prose, with no
  link, and its README states the rule as CW-d2rw has it. `test_change_workflow_assumptions.py` no longer admits a
  path into the workflow's or the engineering guidance, nor the engine's package, as
  the workflow's own: "A skill names an engineering guidance file" fails naming
  each path, and the skills pass; and no code span of a workflow skill is the bare
  name of a guidance file, as `test-levels.md` was, CW-7x0z's "never by a file's
  name": passed.
- [x] 5.3 `check config` reports each engineering section a shipped skill cites that
  no file beneath the pointer heads, and each that several sections head, naming the
  files, exiting 0 for both (CW-7x0z). Verify: library integration cases in
  `test_change_workflow_config.py` ("A user's guidance lacks a cited section", "A cited
  section name repeats").
  Done: `sections.py`, new: the section names a text cites of either guidance, a
  directory's headings outside fenced blocks, and the names that head no section or
  several. `config.cited_sections` reads the names the shipped skills and the
  workflow's guidance cite of the engineering guidance, and `check config` prints
  an `UNRESOLVED:` line for each no file beneath the pointer heads and an
  `AMBIGUOUS:` line for each several sections head, naming the files and the
  skills citing it, still exiting 0; nothing while the pointer applies none. Unit,
  `test_change_workflow_sections.py` (one name or several, wrapped names, a quotation
  outside a citation, fenced headings, resolution): passed. Library integration,
  `test_change_workflow_config.py` (in-process `main` over temporary checkouts): "A
  user's guidance lacks a cited section" and "A cited section name repeats", each
  exiting 0 and naming the section and a skill citing it, the second both files; a
  pointer applying none reporting nothing unresolved or ambiguous: passed.
- [x] 5.4 The guidance check refuses a link from workflow guidance to engineering
  guidance (CW-d2rw, MCW-c4ek's link rule). Verify: `test_check_guidance.py` and `make
  check-guidance`.
  Done: `check_guidance.py` refuses a link from a file tagged `workflow` to one
  tagged `engineering`, naming both and saying the workflow's guidance names the
  section instead; its fixture's workflow guidance names its engineering section in
  prose; its OK and failure lines and `market-change-workflow`'s companion, which
  lists what the check refuses, say so. Unit, `test_check_guidance.py` (the link
  refused, the section named in prose admitted): passed. `make check-guidance` over
  this repository: passed.
- [x] 5.5 The distribution's test fails on a skill citing a section of the workflow's
  guidance that the installed guidance does not head (CW-lm42). Verify:
  `test_change_workflow_citations.py` (new, under `scripts/tests/`); its requirement-id half is
  section 8's.
  Done: `test_change_workflow_citations.py`, new: every section of the workflow's
  guidance a shipped skill cites heads exactly one section of the guidance the
  distribution ships (`documents.RUNNING`), and CW-lm42's "A skill cites a section the
  guidance lost" fails naming the skill and the section. Unit: passed.
- [x] 5.6 Verify the section: its suites, `make check-guidance`, and `scripts/change-workflow
  run pre-commit extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites, each after its last edit —
  `test_change_workflow_sections.py`, `test_change_workflow_citations.py`,
  `test_change_workflow_config.py`, `test_change_workflow_assumptions.py`,
  `test_check_guidance.py`, `test_check_agent_skills.py`,
  `test_post_compaction_context.py`, `test_change_workflow_documents.py`,
  `test_check_doc_citations.py`, `test_change_workflow_wheel.py` (`sections.py`
  shipped through the package's `force-include`): passed. `make check-guidance`,
  `make check-doc-citations CHANGE=extract-change-workflow-repository`, and `make
  check-comment-hygiene`: passed. `scripts/change-workflow check config` in this
  checkout reports no cited section unresolved. `scripts/change-workflow run
  pre-commit`: `make lock` passed, changing no lock; `make validate-local` passed —
  packaging, and every suite, the scripts' 3,717 passing; the default checks and the
  strict OpenSpec validation passed; `make check-repository` failed on
  `check-spec-index` alone, the fourteen ids 8.2 and 10.2 index.

Section 5 notes (handoff):

- The citation form is the interface the engine parses (`sections.py`): `the
  engineering guidance's section "<name>"`, or `sections "<a>" and "<b>"`, and the
  same with `workflow guidance's`. A citation written otherwise — "its section", a
  file name — is neither reported by `check config` nor held by the distribution's
  test; `test_change_workflow_assumptions.py` holds paths and bare file names out of
  the skills, not the phrasing. Section 8.5's requirement-id half can sit beside
  `unresolved_citations` in `test_change_workflow_citations.py`.
- `check config` also reads the engineering sections the workflow's own guidance
  cites, beyond CW-7x0z's "a shipped skill cites", since that guidance cites them the
  same way and ships with the skills; the triage may keep it or narrow it to the
  letter.
- Outside the plan: the orchestrating skill no longer cites
  `scripts/change_workflow/next_step.py` for the computation's result, which no
  requirement words; it cites its own sections that route on each result. If the
  result's shape is to be a public interface, the specification would need it, which
  is section 8's or a later change's to decide. The workflow guidance's README
  restates the layer rule as CW-d2rw has it, `market-change-workflow`'s companion
  lists the guidance check's new refusal, and the check's own lines say so.
- `change-workflow`'s companion, "Leaf skills from one source", still describes the
  skills citing guidance by path; section 8.3 promotes D4 and D6 there.
- The fresh-context check's findings fixed: the orchestrating skill citing CW-4rqr
  for a result contract the specification does not hold; a note calling the
  replaced links "by link in prose"; the assumptions test's stale docstring; 5.1's
  evidence named a unit test where it is a content check, and its integration test
  now shows the pointer read; bare guidance file names unchecked; the guidance
  check's description and lines; two overstated 5.3 claims; citation wording;
  stale link texts. Declined: none.

## 6. Two default checks moved into the engine, and the roles as structured output

Delivers `spec-index` and `decisions` as default checks, the delta paths in `check
spec-index --json`, and `roles` in `config --json`, read by this repository's
assumptions test (D10, D14; CW-c8lw, CW-368t, CW-ora1, MCW-5tgp). Touches
`scripts/change_workflow/` (new `spec_index.py` and `decisions.py`, `config.py`,
`hooks.py`, `cli.py`), `check_spec_index.py` and `check_decision_destinations.py`
under `scripts/`, which leave it, `scripts/check_doc_citations.py`,
`scripts/check_change.py`, the `Makefile`, `scripts/tests/test_change_workflow_assumptions.py`,
and their tests.

- [x] 6.1 The orchestrator's, on the owner's word, before the section's session:
  `make install-workflow`, so the session runs the skills section 5 rewrote.
  Done by the orchestrator on the owner's word: `make install-workflow` ran in this
  change's clone only, not the workspace, reinstalling the tree's wheel and writing
  the 0.1.0 skills into the user skill directories.
- [x] 6.2 Move the specification index check and the decision destinations check into
  the engine as `spec-index` and `decisions`, run by `pre-commit` and `check change`
  before the declared commands and turned off only by name; `make check-repository`
  stops running them, and `make check-spec-index` and `make
  check-decision-destinations` call the engine; the two scripts go (D10, CW-c8lw).
  Verify: `test_check_spec_index.py` and `test_check_decision_destinations.py` moved to
  the engine's command, `test_change_workflow_hooks.py` (six default checks, "A
  decision names no destination"), `test_check_change.py`.
  Done: the scripts moved with `git mv` to `spec_index.py` and `decisions.py` in the
  engine's package, each finding the change through `find` rather than the command,
  and the subcommands `check spec-index [<change>] [--json]` and `check decisions
  <change>`. `config.DEFAULT_CHECKS` is `index`, `tasks`, `skills`, `spec-index`,
  `decisions`, `openspec`, so `defaults.disable` names either and `config` lists
  each; `hooks` runs both in process. An archived change's deltas count for nothing,
  the archive having merged them, and its design is read where the archive moved it.
  `check_change.py` runs neither; `make check-spec-index` and `make
  check-decision-destinations` call `$(CHANGE_WORKFLOW) check …`, so, like
  `check-change`, they run the installed engine. The comment-hygiene exemption of
  the design and proposal file names moved with the module. Unit,
  `test_change_workflow_spec_index.py` and `test_change_workflow_decisions.py` (the
  moved suites, their parsing cases unchanged, every delta case through
  `change_deltas`): passed; library integration, the same files, through the
  command's `main` in process over temporary checkouts — the failing and passing
  checks, a usage error, an unknown change refused, an archived change's deltas not
  counted, and its design read from the archive: passed. Unit,
  `test_change_workflow_hooks.py`: `Hooks.named("pre-commit")` runs the six in order
  and then the declared command, and `Hooks.check_change` the six alone; one
  disabled by name is skipped; and CW-c8lw's "A decision names no destination"
  through `Hooks.named("pre-commit")` with the engine's own decisions check, the
  other default checks doubled through the constructor, failing on it and naming D7:
  passed. `test_check_change.py` (seven checks, none of the two): passed;
  `test_check_comment_hygiene.py`: passed. `make check-spec-index` and `make
  check-decision-destinations`, run with `CHANGE_WORKFLOW=scripts/change-workflow`,
  since the installed 0.1.0 predates both subcommands: the first fails on the
  fourteen ids 8.2 and 10.2 index, the second passes on the change's 24 decisions.
  `run test-before` at `d069c97bc`: `test_change_workflow_hooks.py` fails there at
  collection, importing `decisions`, which shows less than an assertion.
- [x] 6.3 `check spec-index <change> --json` reports the specification paths the
  change's deltas create, and `scripts/check_doc_citations.py` reads them in place of
  importing a delta reader (D10, CW-368t). Verify: `test_check_doc_citations.py`
  ("A citation check meets a specification the change creates").
  Done: `--json` prints `change`, `result`, `problems`, and `created`, each
  capability's `spec.md` that does not exist and that a delta adding a requirement
  will write, and exits as the check does, 1 when it fails, so a caller reads
  `created` whatever the check found. `workflow_command.created_specifications`
  runs it and reads `created`, refusing with the command's reason when it prints no
  object; `check_doc_citations.py` imports no delta reader. Library integration,
  `test_check_doc_citations.py` (CW-368t's scenario: the change's own citation of
  the created `spec.md` accepted, through the command as a process; the five deltas
  that add nothing still refused): passed. `test_workflow_command.py` (the paths read
  while the index check fails beside them, a refusal's reason, a report with no
  `created` refused): passed. Library integration,
  `test_change_workflow_spec_index.py` (the created path listed, an existing
  capability's and a removal-only delta's not, beside a failing result; a passing
  check's object whole): passed.
- [x] 6.4 `config --json` lists `roles`, each role by name with the configuration
  fields that provide it; the distribution's test holds the companion's roles table to
  it; `test_change_workflow_assumptions.py` reads the roles from `config --json` and the
  fragment from `change-workflow fragment`, with no local configuration (D14; CW-ora1,
  MCW-5tgp). Verify: `test_change_workflow_config.py` and
  `test_change_workflow_assumptions.py` ("The workflow adds a role").
  Done: `config.ROLES`, seventeen roles in the companion's order, each
  `{"role", "fields"}` in `config --json`'s `roles`, a field written with a
  placeholder (`load.<step>`) where it names a key per step. Three of the
  companion's provisions were reworded so each names its fields in code: the
  cleanup row names `validation.evidence`, the tests row `sandbox.writable.<step>`,
  and the guidance row `guidance.engineering` before `load.common`; and the
  paragraph above the table says the roles are `config --json`'s and the test reads
  them there. Content check, `test_change_workflow_config.py`: the distribution's
  companion's table, read under its heading alone, names each role `roles` lists in
  its order, its provisions naming exactly that role's fields; unit, every field a
  key of a table the configuration defines, a `<step>` key every step's: passed. Library integration, the same file: with
  no local file, `config --json` gives `roles` in full: passed.
  `test_change_workflow_assumptions.py` runs `scripts/change-workflow config --json`
  and `fragment` as processes in a temporary Git checkout holding no configuration,
  committed or local, and reads the roles and the fragment from them, no longer
  parsing `change-workflow`'s companion: passed; unit, "The workflow adds a role"
  (MCW-5tgp), a role given as `config --json` would list it failing the comparison,
  naming the role: passed. `run test-before` at `d069c97bc`: its two
  role tests fail there, `config --json` listing no `roles`.
- [x] 6.5 Verify the section: its suites, and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`, the two checks now run by the engine.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites together, after the last fixes —
  `test_change_workflow_spec_index.py`, `test_change_workflow_decisions.py`,
  `test_change_workflow_hooks.py`, `test_check_change.py`,
  `test_check_doc_citations.py`, `test_workflow_command.py`,
  `test_change_workflow_config.py`, `test_change_workflow_assumptions.py`,
  `test_check_comment_hygiene.py`, `test_change_workflow_cli.py`,
  `test_change_workflow_review.py`: passed. `scripts/change-workflow run pre-commit`:
  `make lock` passed; `make validate-local` passed — packaging, and every suite, the
  scripts' 3,728 passing, its tree guard holding before and after; the default
  checks now run six: the index, tasks, skills, and decisions checks and the strict
  OpenSpec validation passed, and the spec-index check failed on the fourteen ids of
  the change's deltas that 8.2 and 10.2 index, as `check-repository`'s index check
  did before it; `make check-repository`, no longer running either check, failed
  only on one citation in this section's own handoff, of the removed script by
  path, now its bare name; then `make check-repository` passed whole and
  `scripts/change-workflow check change` failed on the spec-index check alone. The
  tree `validate-local` passed differs from the commit's only in `tasks.md`.

Section 6 notes (handoff):

- The orchestrator reinstalls before the next session runs a step (`make
  install-workflow` in this clone, and in the workspace when it runs the workflow):
  the installed 0.1.0 predates `check spec-index` and `check decisions`, so until
  then an installed engine's `run pre-commit` and `make check-change` run the four
  older default checks, `make check-spec-index` and `make
  check-decision-destinations` fail on an unknown subcommand, and the installed
  skills carry the change-implement and change-closeout text before this section.
  `scripts/change-workflow`, which every pre-commit of this session ran, has both.
- `check spec-index --json` is structured output a repository script relies on
  (`workflow_command.created_specifications`): section 8.3's "Interfaces are tiered"
  should list it beside `config --json`'s fields, and "The command and its tiers"
  the two new `check` subcommands.
- Left for section 8: `change-workflow`'s companion still lists four default checks
  under "The hooks", and its spec, until 8.1 applies the delta, CW-c8lw's four; the
  companion's roles table and the paragraph above it are already as `roles` has
  them, since the distribution's test holds the table to `config.ROLES` — a
  promotion there that renames a role must rename it in `ROLES` too.
- Left for section 10: MCW-c4ek still says a change's closing checks fail on a
  decision with no destination, which holds of `run pre-commit` as a whole;
  `market-change-workflow`'s "What each check enforces" and "The closing checks"
  now name the two as the workflow's default checks, and its paragraph on the
  assumptions test says the roles come from `config --json`, so 10.3 has the
  configuration files and "The engine's own assumptions" left.
- Outside the plan: documents this section made false are corrected —
  `openspec/README.md`'s "The index check", the workflow guidance's closeout
  "Promotion" paragraph, change-implement's and change-closeout's lists of what
  `pre-commit` runs, the comment-hygiene exemption's path, and the change's own
  proposal and section heading, which cite the removed scripts by bare name. The
  unscoped citation check now also names the removed `check_spec_index.py` in
  `pass-checks-at-every-commit`'s proposal, beside the stale citations other open
  proposals already carry; that change's design is reverified against the code, so
  its proposal is left to it.
- Deferred: the engine reads fenced blocks three ways (`decisions` as CommonMark,
  `spec_index` and `sections` toggling on any fence), recorded as unowned work in
  the change index under the workflow's lesser goal.
- The fresh-context check's findings fixed: a comment left above `Role` that
  describes `_DEFAULT_SHOWN`; the hooks test's double set after construction, now
  passed through `_hooks`; a spec-index test named for a citation check it does
  not run; `git init` and docstrings implying the command ran as a process where
  `main` runs in process; the archived-change case now through `main`; overstated
  6.2 and 6.4 notes; the role-field check now against each table's keys; the
  assumptions test reaching the command through `workflow_command` rather than its
  own copy of the path; "states no role" wording; `market-change-workflow`'s
  paragraph on the roles; a duplicate decisions test. Declined: editing
  `pass-checks-at-every-commit`'s proposal (above); adding `check spec-index --json`
  to the tier table now, which 8.3 promotes with the rest of "Interfaces are tiered";
  the companion's four default checks, 8.3's with D10.

## 7. The workflow's documents self-contained, and the move's procedure

Delivers documents the coordinator can lift whole, the handbook's procedures for
installing, crossing, and the move, and the workflow's tests runnable without this
repository's other files (D6, D7, D8, D16, D17, D18). Touches
`openspec/specs/change-workflow/README.md`, `docs/guidance/workflow/*.md`,
`docs/change-workflow-handbook.md`, and the workflow's tests and fixtures under
`scripts/tests/`.

- [x] 7.1 The workflow's documents link only within their own set: the companion's
  four links to `market-change-workflow` become neutral text about an adopting
  repository's own capability, and no workflow document links to this repository's
  documents (D6). Verify: a unit test over the wheel's document set,
  `test_change_workflow_citations.py`, failing on a relative link leaving it.
  Done: the companion's four links to `market-change-workflow` say that an adopting
  repository states its own provisions, kinds, and resources; its "Current limits"
  name the open changes that own a limit as code, with no link into this
  repository's changes, and the limit on the two checks section 6 moved into the
  engine went; the handbook names the change index as a path, not a link. Unit,
  `test_change_workflow_citations.py`: every relative link of a Markdown document
  the distribution ships — its documents by role and each skill's directory, read in
  the tree's layout, which the lift keeps, and skipped for an installed
  distribution — resolves to a file or directory of that set; a link leaving it, to
  a repository document or to a directory above the set, is named with its document
  and line, while links within it, to a heading, to a URL, and written as code are
  not: passed. `run test-before` at `fe3690681`: the tree's check fails there.
- [x] 7.2 The workflow's tests and fixtures name the files they need from the
  workflow's own set, and run with only the paths section 7.3 lists present (D16, D17).
  Verify: the workflow's suites run from a temporary checkout holding only those paths,
  recorded in the handoff.
  Done: the workflow's tests that held this repository's own provisions — its
  configuration and template, its root Makefile's targets, its settings' hook — move
  to a repository test, `scripts/tests/test_market_change_workflow.py`, which reaches
  the engine only through `scripts/change-workflow` (CW-r3ka): a test of the
  configuration runs the command in a temporary checkout holding the committed file,
  the template written as the local file, and the documents they name, so neither a
  developer's local file nor CI's missing one is read; a test of the Makefile
  dry-runs the root Makefile; the hook's runs the settings' command from the path,
  as Claude Code does; the ignore rule's runs `git check-ignore`, and the table
  comments' reads the file. What the workflow's suites keep runs on their fixtures:
  the fragment's targets are dry-run with the fragment as the makefile, CW-z5me's
  settings case and the interactive-models case run on a fixture configuration, and
  the `as_installed` fixture went. Two of the moved tests are now stated from
  `config --json`'s fields and scopes: the gathering's order is the workflow's to
  prove on its fixture kinds, so the repository holds its kinds' declarations, and the
  settings' protection is read from each step's first model's scope. The lifted
  checkout: `git ls-files` of exactly the handbook's paths copied from the worktree
  into a fresh Git repository under `~/.cache` (the sandbox's private `/tmp` hides one
  under `/tmp` from the sandbox tests), its suites run with `uv run --no-project
  --with pytest pytest scripts/tests`, since the lifted tree has no Makefile: 2,209
  passed, none skipped, the sandbox tests run. Before the move of the repository's
  tests, the same run failed 48, every one reading this repository's configuration,
  Makefile, or settings. `test_market_change_workflow.py`, 27 cases: library
  integration where the command runs as a process, the rest the Makefile's dry runs,
  `git check-ignore`, and the file's text: passed; the suites the
  move edited, after the fresh-context check's fixes, which also restored the
  protected branches' assertion the old configuration check made —
  `test_change_workflow_config.py`, `test_change_workflow_cli.py`,
  `test_change_workflow_cli_steps.py`, `test_change_workflow_gather.py`,
  `test_change_workflow_graph.py`, `test_post_compaction_context.py`,
  `test_change_workflow_command.py` (whose import rule holds the new test, which
  loads `workflow_command`, to importing no engine): passed.
- [x] 7.3 The handbook gains: installing the workflow and the local configuration;
  that one version is installed per machine, managed like any tool a repository pins,
  each repository declaring its range (D7, D8, the owner's principle); when an open
  change crosses to the installed workflow (D18); and the procedure for the move —
  the exact path list the coordinator lifts with `git filter-repo`, keeping paths, the
  wheel's project file to rename to the new repository's root, and the test for which
  settings are local, for the workflow repository's own repository guidance (D5, D16,
  D17). Verify: the path list matches what the wheel packages plus its tests, held by
  `test_change_workflow_wheel.py`.
  Done: "Installing the workflow", with "When an open change crosses to the installed
  workflow" under it, opens the handbook; "Moving the workflow to its own repository"
  closes it, its 67 paths in one fenced block: the engine, its command and its
  project, the schema, the eleven skills, the handbook, the workflow's guidance, the
  specification, index, companion, and diagrams, and `conftest.py`,
  `change_workflow_fixtures.py`, and 44 test files. The capability's `diagrams.md`,
  repository guidance linking this repository's documents, is not lifted. Unit,
  `test_change_workflow_wheel.py`: the list is exactly the project's `force-include`
  sources, its project, and `scripts/change-workflow`, beside its test files; every
  test file importing the engine or the workflow's fixtures is listed; no listed one
  imports a script of the repository's; every path exists, a directory written with
  its `/`: passed. Its wheel tests now skip on a missing `uv` from their fixture, so
  the list's test runs without it. `run test-before` at `fe3690681`: it fails there.
- [x] 7.4 Verify the section: its suites and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.
  Done: the section's suites, after the last fixes — `test_change_workflow_citations.py`,
  `test_change_workflow_wheel.py`, `test_market_change_workflow.py`,
  `test_change_workflow_assumptions.py`, `test_change_workflow_command.py`,
  `test_change_workflow_config.py`, `test_change_workflow_cli.py`,
  `test_change_workflow_cli_steps.py`, `test_change_workflow_gather.py`,
  `test_change_workflow_graph.py`, `test_post_compaction_context.py`,
  `test_check_doc_citations.py`: passed; the lifted checkout's 2,209 (7.2), run
  before those fixes, which moved no test. `scripts/change-workflow run pre-commit`
  on the staged section: `make lock` passed; `make validate-local` passed —
  packaging, and every suite, the scripts' 3,735 passing, its tree guard holding;
  the default checks passed but the spec-index check, failing on the fourteen ids
  8.2 and 10.2 index; `make check-repository` passed. The tree it passed differs from
  the commit's only in `tasks.md`.

Section 7 notes (handoff):

- The lifted checkout is made by copying `git ls-files` of each listed path from the
  worktree into a fresh repository and committing it; build it outside `/tmp`, whose
  sandbox-private copy hides it from the sandbox tests, which then fail on a missing
  command. The lifted suites need pytest alone.
- The move's path list is the handbook's one fenced block under "Moving the workflow
  to its own repository", which `test_change_workflow_wheel.py` reads: a test file
  importing `change_workflow` or `change_workflow_fixtures` must be listed, and a
  listed one may import no script of the repository's. A new workflow test is listed
  there; a new repository test of the workflow goes in
  `test_market_change_workflow.py`, reaching the engine through the command.
- `scripts/tests/conftest.py` is listed, so it is the workflow's, but every
  repository test runs under it too and it imports the engine: section 9.3's removal
  must leave a repository `conftest.py` that does not, keeping `scripts/` on the path.
- Left for section 8, D6's self-containment in prose, which the link test cannot
  see: `spec.md`'s opening ("This repository's own part of the workflow is
  `market-change-workflow`'s") and its Evidence paragraph naming `make
  test-release-tooling`, `test_change_workflow_assumptions.py`, and
  `market-change-workflow`, and naming `scripts/change-workflow hook
  post-compaction` where the settings run `change-workflow`; the companion's "In
  this repository design, triage…" on models, now local, and "this repository
  included" in "Current limits".
- Outside the plan: "Current limits" no longer names the open change owning a
  limit, the change index holding owners; the limit on the engine's layering lost a
  claim no task of this change makes; `change-workflow convert` replaces the tree's
  command there.
- The fresh-context check's findings fixed: two overstated test names and their
  docstrings (the kinds' declarations, and `config load`'s engineering guidance
  before `load.common`); the configuration check now in the installed checkout, with
  the protected branches' assertion the move had dropped; the moved file's
  docstring on which tests read which checkout; the link test's fence and heading
  cases; an unused constant; two comments crediting the fragment; the limits'
  wrapping; the handbook restating the local-settings rule, now citing the
  companion's "A repository's configuration", which D5 is promoted to in 8.3, the
  move's procedure keeping the rule for the new repository's guidance as 7.3 asks.
  Declined: none; the prose of finding 8 is left to section 8 (above).

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
