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

- [ ] 1.1 Write the wheel's project, `scripts/change-workflow-wheel/pyproject.toml`:
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
- [ ] 1.2 Add `scripts/change_workflow/documents.py`: each document by its role
  (`specification`, `index`, `companion`, `diagrams`, `guidance`, `handbook`, `schema`,
  `fragment`, and the skills), found through `importlib.resources` when installed and
  at its tree path when the package runs from `scripts/` (D6, CW-lm42). Route
  `outcome.SCHEMA` and `diagram.DIAGRAMS` through it. Verify: unit tests for both
  modes, `scripts/tests/test_change_workflow_documents.py` (new).
- [ ] 1.3 `config --json` gains `workflow`: `version` and each document by role, no
  directory to look inside (D6, CW-lm42); `change-workflow --version` prints the
  version and reads no configuration (CW-5kl9). The version comes from the installed
  distribution's metadata, or the project file's when run from the tree. Verify:
  library integration cases in `test_change_workflow_config.py` and
  `test_change_workflow_cli.py`.
- [ ] 1.4 Every line `log.py` appends carries `workflow`, the engine's version; no
  reader routes on it and `format` stays 2 (D12, CW-d867). Verify: unit cases in
  `test_change_workflow_log.py` (a line written under each of two versions), and the
  next-step suite unchanged (`test_change_next_step.py`).
- [ ] 1.5 Declare the exception (D24): an `overrides` row in `AGENTS.md`, "Exceptions
  to shared guidance", against `packaging-python.md`'s "One import package per
  distribution", "Nothing remaps the package", and "Data files live inside the
  package", and `packaging-hatchling.md`'s "The wheel target names the one package",
  for `scripts/change-workflow-wheel/`, lasting until the second half removes it; and
  `scripts/check_project_layout.py` admitting that one project, naming the row. Verify:
  `test_check_project_layout.py` (the wheel admitted, any other remap still refused)
  and `make check-guidance`.
- [ ] 1.6 Verify the section: build the wheel, install it into a temporary tool
  directory with `uv tool install`, and run the installed `change-workflow --version`
  and `config --json` in a temporary repository, each named document existing — a
  library integration test, `scripts/tests/test_change_workflow_wheel.py` (new),
  skipped with its reason where `uv` is absent; plus the section's suites and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.

## 2. The configuration's new shape, read

Delivers the committed range, the local configuration, and the engineering pointer as
the engine reads them, each checked when declared; their enforcement as required, and
the one-home rule, wait for section 4, after the orchestrator moves this repository's
fields (D4, D5, D6, D11, D13; CW-f8yy, CW-4pm4, CW-hu0z, CW-l7hn, CW-r6kd for the
local file, MCW-iqh1). Touches `scripts/change_workflow/` (`config.py`, `hook.py`,
`clone.py`, `scope.py`), `.gitignore`, `.agents/workflow.local.template.toml` (new),
and their tests.

- [ ] 2.1 `config.py` reads `[workflow] version` before the rest of the file: a
  comma-separated subset of PEP 440 specifiers (`>=`, `<=`, `>`, `<`, `==`, `!=`, `~=`)
  over release numbers, parsed on the standard library; an installed version outside
  it refuses every subcommand that reads the configuration but `install` and
  `--version`, naming the version, the range, and the fix, and a newer table is then
  reported as the mismatch, not as unknown (D11, CW-f8yy). Verify: unit tests of the
  parser and the check, and library integration cases in
  `test_change_workflow_config.py` ("The installed version is too old").
- [ ] 2.2 The engine reads `.agents/workflow.local.toml` beside the committed file:
  `[guidance]`, `[models]`, and `[sandbox] writable.*`, the local writable paths
  extending the committed ones; `config --json` reports `local` (`file`, `exists`),
  each required local field it lacks as `missing`, distinct from `absent`, and
  succeeds with no local file, giving the committed fields and the distribution's in
  full (D5, CW-4pm4's CI scenarios). Verify: library integration cases in
  `test_change_workflow_config.py`.
- [ ] 2.3 The pointer (D4, CW-hu0z): `engineering = { path }` or `{ none = <reason> }`,
  one key; a missing or Markdown-less directory and an empty reason refused; a `load`
  entry that is or lies beneath the pointer refused; `config --json`'s
  `guidance.engineering` as `{"path"}`, `{"none"}`, or `null`. Verify: library
  integration cases in `test_change_workflow_config.py`, the scenarios of CW-hu0z.
- [ ] 2.4 `config load <step>` and `config load common` print, in order, the
  pointer's Markdown files, the installed workflow guidance, then `load.common` and
  `load.<step>`, each once; the post-compaction hook re-reads what `config load
  common` prints (D6, CW-l7hn). Verify: library integration cases in
  `test_change_workflow_config.py` and `test_change_workflow_command.py`.
- [ ] 2.5 A change's clone links `.agents/workflow.local.toml` to the workspace's, as
  it links `.claude/settings.local.json` (CW-4pm4); the sandbox protects the local
  file beside `.agents/workflow.toml` (D13, CW-r6kd). Verify: `test_change_clone.py`
  and `test_change_workflow_scope.py`, `test_change_workflow_sandbox.py` (the write
  refused, under `needs_bwrap`).
- [ ] 2.6 Add `.agents/workflow.local.toml` to `.gitignore`, and commit
  `.agents/workflow.local.template.toml`: the pointer at `docs/guidance/engineering/`
  and the models `.agents/workflow.toml` declares today, each with its comment (D5,
  MCW-iqh1). Verify: `git check-ignore .agents/workflow.local.toml` and the template
  read by 2.2's parser in a test.
- [ ] 2.7 Verify the section: its suites, and `scripts/change-workflow run
  pre-commit extract-change-workflow-repository` with this repository's configuration
  unchanged, which still passes.
  End-to-end: none exercises the workflow's tooling; none owed.

## 3. The installer, the version stamp, and what is installed protected

Delivers `change-workflow install` and the checks of installed skills, and the
sandbox's protection of them and of the installed engine (D8, D13, D21; CW-1rhd,
CW-sv3u, CW-d8de, CW-r6kd). Touches `scripts/change_workflow/` (a new `install.py`,
`skills.py`, `harness.py`, `claude_code.py`, `codex.py`, `scope.py`, `cli.py`) and
their tests.

- [ ] 3.1 Each adapter names its harness's user skill directory (Claude Code's under
  `~/.claude`, Codex's under `~/.codex`) and protects it and the installer's manifest
  there; the engine protects its own installed distribution, found from its own
  location (D13, CW-r6kd). Verify: `test_change_workflow_scope.py`, and
  `test_change_workflow_sandbox.py` under `needs_bwrap` (a write to an installed skill
  and to the installed engine beneath a writable path both refused).
- [ ] 3.2 `install.py`: write the version's skills into each user skill directory,
  stamp each with the version, and keep a manifest of the names it wrote; remove a
  retired skill the manifest names; refuse, writing nothing, a skill of a shipped name
  the manifest does not record; and, in a checkout, write `.agents/workflow.local.toml`
  where none exists, from `.agents/workflow.local.template.toml` when present and
  otherwise as a skeleton naming each required local field, never overwriting one
  (D8, CW-1rhd, CW-sv3u). Verify: library integration tests under a temporary `HOME`,
  `scripts/tests/test_change_workflow_install.py` (new), every scenario of CW-1rhd and
  CW-sv3u.
- [ ] 3.3 Every subcommand but `install` and `--version` refuses when an installed
  skill's stamp differs from the engine's version, or a supported harness's user skill
  directory lacks a shipped skill or the manifest, naming what and `change-workflow
  install` (CW-1rhd). Verify: library integration cases in
  `test_change_workflow_install.py`.
- [ ] 3.4 `check skills` holds both halves: the installed skills as 3.3 checks them,
  and, for skills the repository commits, one source under `.agents/skills/` linked
  from each harness's project skill directory, asking no project link of the
  workflow's own sources (D21, CW-d8de). Verify: `test_check_agent_skills.py`.
- [ ] 3.5 Verify the section: its suites, with the repository's existing
  `make check-agent-skills` still passing against the tracked links, which section 4
  removes; and `scripts/change-workflow run pre-commit
  extract-change-workflow-repository`.
  End-to-end: none exercises the workflow's tooling; none owed.

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
