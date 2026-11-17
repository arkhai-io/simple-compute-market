# Tasks

The engine's tests below are named by level as
`docs/guidance/engineering/test-levels.md` defines them: **unit** for a pure function
(the configuration's check, the owed-line reader, pattern matching), and **library
integration** for the engine's commands driven in process against a real temporary
Git repository, the harness and the network doubled at the engine's own wrappers.
No end-to-end scenario exercises the workflow's tooling: in every section below,
validation's pipeline result is not evidence for the change, and none is owed. The
change alters the tool that validates it, so each section's commit leaves the
configuration loadable and `scripts/change-workflow run pre-commit` passing.

## 1. Evidence kinds in the configuration

Delivers `[validation.evidence.<kind>]` in place of `[validation.parts]`, its check,
and this repository's configuration and seeded guides, every current reader moved to
kinds so the engine stays runnable (D6, D11, D16; CW-g4oz, CW-k7gd, CW-g1gn, CW-v2dq,
CW-o6kc, CW-r5qk's pattern rule, CW-t3ev's pattern rule). Files:
`scripts/change_workflow/config.py`, `hooks.py`, `cli.py`, `history.py`,
`.agents/workflow.toml`, `.agents/evidence/`, `openspec/specs/change-workflow/index.md`,
`scripts/tests/test_change_workflow_config.py`,
`test_change_workflow_hooks.py`, `test_change_history.py`, and the comment in
`scripts/tests/test_change_workflow_log.py` 1.1 names.

- [ ] 1.1 Rewrite the comment at `scripts/tests/test_change_workflow_log.py:1005` that
  names section numbers ("splits open section 4 into 4 to 6") to describe the
  behaviour it sets up, so the repository's comment check passes and every later
  commit's `pre-commit` can (a found defect, `docs/guidance/workflow/changes.md#defects-found-during-a-change`;
  record it in this task's note). Verify: `make check-comment-hygiene` passes.
- [ ] 1.2 Add `openspec/specs/change-workflow/index.md`'s entries for the sixteen ids
  the change's deltas add — under "## 2. Implementation and validation", "###
  Validation": CW-t3ev, CW-g1gn, CW-p4rs, CW-r5qk, CW-e2vd, CW-a8ss, CW-g6th; under
  "## 4. The engine", "### Hooks": CW-h3ks, CW-b7fl, CW-a4fl, CW-i9np; "### Skills
  from one source": CW-n8tr; under "## 5. The public surface", "### A repository's
  configuration": CW-d1nj, CW-g2rs, CW-k7gd, CW-c5nt — each linked to its
  requirement's heading, which the index check resolves against the deltas, so the
  repository's closing checks pass on every commit before the archive (a repository
  obligation, `openspec/README.md#the-index-check`); closeout's promotion revises
  them (10.9). Verify: `make check-spec-index CHANGE=add-skill-extension-points`
  passes.
- [ ] 1.3 In `config.py`, replace `Part` and `_parts` with an evidence kind read from
  `[validation.evidence.<kind>]`: `required` (`always` or `owed`), `evidence` (a
  pattern), `run` or `start` and `collect`, `guide`, optional `after` and `cleanup`;
  drop `owed` as a key, owing following from `required = "owed"` (D5, D6; CW-g4oz).
  Keep `[validation] preflight`. Verify: unit tests in
  `test_change_workflow_config.py` read a four-kind configuration and refuse a
  `[validation.parts]` table as an unknown key.
- [ ] 1.4 Add the check's refusals, each naming the field (D11; CW-w8ne): an undefined
  key or wrong type; `required` outside `always`/`owed`; neither or both of `run` and
  `start` with `collect`; an `after` naming no kind declared before it, or a started
  kind's `after` naming a `run` kind (CW-g4oz's two scenarios); a pattern holding
  neither or both of `{tree}` and `{commit}` (CW-t3ev); a pattern whose fixed
  directory `git check-ignore` does not report ignored (CW-g1gn's scenario); an owed
  kind's pattern without `{owed}`, and `{owed}` outside an owed kind (CW-r5qk's
  scenario); a kind with no `guide`, or one missing or empty (CW-k7gd's scenario).
  Verify: one unit test per refusal, each asserting the field named.
- [ ] 1.5 Extend placeholder availability (CW-v2dq): `{tree}` and `{commit}` in a
  kind's commands and pattern and in `after-functional-change` and
  `pre-commit-functional`; `{kind}` in review and triage hooks; `{inputs}` in step
  hooks; and accept hook keys `before-<step>` and `after-<step>` for each step in
  `graph.STEPS`, refusing any other `before-`/`after-` key (D7, D11). The hooks are
  only declared here; section 5 runs them. Verify: unit tests for each placeholder
  refused where unavailable, and for `before-validate` accepted and
  `before-round` refused.
- [ ] 1.6 `config` and `config --json` list each kind's fields, its guide among them,
  and each step hook as declared or absent (CW-o6kc). Verify: a library-integration
  test of `config --json` naming every kind's `guide`.
- [ ] 1.7 Move every current reader to kinds without changing behaviour yet:
  `config parts` and `run validation … run|start|collect` resolve kinds by name
  (section 3 replaces them), and `history` takes its evidence directories from each
  pattern's fixed directory (`config.evidence()`). Verify: the existing
  `test_change_workflow_hooks.py` and `test_change_history.py` cases pass against a
  kinds configuration.
- [ ] 1.8 Rewrite `.agents/workflow.toml`'s validation as four kinds (D16; MCW-r4tx):
  `local` (`always`, `run`, pattern `.snapshot/evidence/{tree}/local/*/summary.json`),
  `helm` (`always`, `run`, `after = "local"`, the capacity and teardown cleanup,
  `.snapshot/evidence/{tree}/helm/*/summary.json`), `pipeline` (`always`, `start` and
  `collect`, `.snapshot/evidence/{commit}/pipeline/*/summary.json`), `ci` (`owed`,
  `start` and `collect`, `.snapshot/evidence/{commit}/ci-{owed}/*/summary.json`),
  each with `guide = ".agents/evidence/<kind>.md"`, commands as today until section 4.
  The configuration is denied to every step (CW-z5me): this task is the
  orchestrator's, made on the owner's word before the section's session starts, and
  the session commits it with the section. Verify: `scripts/change-workflow check
  config` passes.
- [ ] 1.9 Seed `.agents/evidence/local.md`, `helm.md`, `pipeline.md`, and `ci.md`, each
  non-empty prose naming what the kind shows, so the check passes; section 7 writes
  their full content (CW-k7gd). Verify: `scripts/change-workflow check config`
  passes and `make check-agent-skills` is unaffected.
- [ ] 1.10 Verification point: the unit and library-integration suites above;
  `scripts/change-workflow run pre-commit add-skill-extension-points` and the
  functional checks it runs before this commit pass.
  End-to-end: none — no scenario exercises the workflow's tooling.

## 2. Evidence identity, owed lines, and presence

Delivers the tree and commit identities, owed lines naming their kind and a safe
argument, and `scripts/change-workflow evidence <change> [--json]` (D2, D3, D4, D5;
CW-t3ev, CW-p4rs, CW-r5qk, CW-e2vd, CW-zkhs). Files:
`scripts/change_workflow/` (a new `evidence.py`, `tasks.py`, `cli.py`, `log.py`'s
waiver reading), `scripts/tests/test_check_tasks.py`, a new
`scripts/tests/test_change_workflow_evidence.py`.

- [ ] 2.1 Compute identity (D2; CW-t3ev): the tree as `git write-tree` of the
  worktree as tested, its changes — staged, unstaged, untracked and not ignored —
  added to a temporary index (`GIT_INDEX_FILE`), never the checkout's own index; the
  commit as `HEAD`'s full object name. Verify: library-integration tests: a clean
  worktree's tree equals `HEAD^{tree}`; a dirty worktree's tree equals the tree of the
  commit that then commits exactly those changes; an ignored file changes nothing;
  the checkout's index is unchanged afterwards.
- [ ] 2.2 Extend the owed-line reader in `tasks.py` (D5; CW-r5qk): `Owed by validation
  (<kind> <argument>):` names its kind; a line naming no kind is the one owed kind,
  its argument the first word in backticks, refused when more than one kind is owed
  or it has no backticked argument; an argument that is empty, `.`, `..`, or holds
  `/`, whitespace, `*`, `?`, `[`, or `]` is refused, naming the section. `check
  tasks` reports a refusal. Verify: unit tests for each form and each refusal,
  including CW-r5qk's `(ci ..)` scenario and a legacy line read as `ci tests.yml`.
- [ ] 2.3 Add `evidence <change> [--json]` (D4; CW-e2vd): for each kind, its
  requirement — `always`, owed once per argument complete sections owe, `not
  required`, or `waived` with the decision's `seq` from the log's standing waivers
  (`log.waived_parts`, read as kinds) — its pattern filled with `HEAD`'s tree or
  commit and any owed argument, and every match, the last in path order marked
  current; an owed-line refusal reported in place of a status. Present means matched
  whoever wrote it (D3; CW-p4rs). Verify: library-integration tests for CW-e2vd's
  two scenarios, CW-r5qk's two-workflow scenario, CW-t3ev's amended-message
  scenario (tree kinds present, the commit kind missing), and CW-zkhs's earlier-tree
  scenario.
- [ ] 2.4 Verification point: `test_change_workflow_evidence.py` and
  `test_check_tasks.py`; `run pre-commit` passes. End-to-end: none.

## 3. Gathering and cleanup by kind

Delivers `gather`, replacing `run validation … preflight|run|start|collect` and
`config parts`, the functional hooks' `{tree}`, `run cleanup` over kinds, and history
by the evidence records name (D4, D7's gathering, D15; CW-g6th's command, CW-x9bt,
CW-ikmm's rerun, CW-q5fy's kinds, CW-e7lm's waivers). Files: `scripts/change_workflow/`
(`hooks.py`, `cli.py`, `evidence.py`, `running.py`, `history.py`, `graph.py`'s
`HOOK_STEPS`), `test_change_workflow_hooks.py`, `test_change_workflow_cli.py`,
`test_change_history.py`, `test_change_workflow_evidence.py`.

- [ ] 3.1 Add `gather <change>`: the preflight, the guarded push of `HEAD`, every
  missing `start` kind and owed argument dispatched, the missing `run` kinds in
  order keeping `after`, then each started kind collected; present evidence never
  touched; a waived kind skipped unless a merge since it was last assessed lapses
  the waiver (CW-g6th; CW-e7lm). A failing kind fails `gather`'s exit status but
  every other kind still runs. Verify: library-integration tests for CW-g6th's
  "Gathering leaves present evidence alone" and CW-g4oz's dispatch-before-run order,
  with the commands doubled as shell scripts writing at the pattern.
- [ ] 3.2 Add `gather <change> --kind <kind> [--owed <argument>] [--lapsed]`: a new
  attempt of that kind whatever is present, of one owed argument or each owed
  without `--owed`; a waived kind refused without `--lapsed` (D4; CW-g6th). Verify:
  library-integration tests for CW-g6th's one-workflow rerun scenario and the
  refusal of a waived kind.
- [ ] 3.3 Key a start's marker by tree or commit, kind, and owed argument, fill
  `{after}` from it, fill `{tree}`, `{commit}`, and `{owed}` in a kind's commands,
  and close each kind with its line naming the kind, argument, identity, result,
  exit status, and evidence (CW-x9bt); record each invocation as `invoked` on the
  run's line (CW-q5fy). Verify: CW-x9bt's two scenarios and CW-q5fy's Helm scenario
  as library-integration tests.
- [ ] 3.4 Fill `{tree}` and `{commit}` in `after-functional-change` and
  `pre-commit-functional` from the worktree the hook runs on (CW-v2dq; D3).
  Verify: a library-integration test of `run pre-commit` with a hook echoing
  `{tree}` matching the tree of the commit then made.
- [ ] 3.5 Remove `run validation … preflight|run|start|collect` and `config parts`,
  `gather` and `evidence` replacing them (D15); `HOOK_STEPS` admits `gather` for
  validate and the wrapper (section 5). `run cleanup <change>` runs every kind's
  `cleanup` in declaration order as one list (CW-ikmm). Verify: the CLI tests
  assert the removed subcommands exit 2 and CW-ikmm's two scenarios pass.
- [ ] 3.6 `history` copies the evidence paths the change's records name, under each
  pattern's fixed directory, with each record's tree and commit (CW-hak6, unchanged
  in intent). Verify: `test_change_history.py` copies a record's cited
  `.snapshot/evidence/<tree>/local/<attempt>/` directory.
- [ ] 3.7 Verification point: the suites above; `run pre-commit` passes. End-to-end:
  none.

## 4. This repository's kinds, scripts, and commands

Delivers this repository's scripts writing each kind's evidence at its pattern with
UTC timestamp attempts, its configuration's commands passing the identity,
`pre-commit-functional` leaving `local` evidence, and the validation and
orchestrating skills moved to the new commands (D16; MCW-r4tx, MCW-5tgp). Files:
`scripts/validate_slice.py`, `scripts/ci_evidence.py`, `scripts/fetch-e2e-logs.py`,
`scripts/validate_parallel.py`, the `Makefile` targets `validate-local`,
`validate-helm`, `run-e2e`, `fetch-e2e-logs`, `run-ci`, `validate-ci`,
`record-capacity`, `.agents/workflow.toml`, `.claude/change-steps.toml`,
`.agents/skills/change-validate/SKILL.md`, `.agents/skills/change-orchestrate/SKILL.md`,
their tests.

- [ ] 4.1 `validate_slice.py` writes each attempt of `local` and `helm` under
  `.snapshot/evidence/<tree>/<kind>/<UTC timestamp>/`, its `summary.json` and logs
  there, given the tree (`TREE=`), and reads the latest Helm attempt for the capacity
  figure from there (D2, D4's path order; MCW-r4tx). Verify: `test_validate_slice.py`
  asserts the new paths, timestamp ordering, and `record-capacity` reading the
  current attempt.
- [ ] 4.2 `ci_evidence.py` and `fetch-e2e-logs.py` write the `ci` and `pipeline`
  evidence under `.snapshot/evidence/<commit>/ci-<workflow>/<UTC timestamp>/` and
  `.snapshot/evidence/<commit>/pipeline/<UTC timestamp>/`, each with a
  `summary.json`, given the commit (`COMMIT=`); markers unchanged (MCW-zk52,
  MCW-7hr1, MCW-2lzw). Verify: `test_ci_evidence.py` and `test_fetch_e2e_logs.py`.
- [ ] 4.3 `validate_parallel.py` follows the new layout. Verify:
  `test_validate_parallel.py`.
- [ ] 4.4 The configuration's kind commands pass `TREE={tree}` or `COMMIT={commit}`,
  and `pre-commit-functional` leaves `local` evidence for `{tree}` — through a
  target that clears the wheelhouse, checks packaging, and runs every suite on the
  worktree as it stands, writing at `local`'s pattern (MCW-r4tx's second scenario).
  The configuration is the orchestrator's to edit, on the owner's word, before the
  session starts; the session commits it. Verify: after a functional commit,
  `scripts/change-workflow evidence add-skill-extension-points` lists `local`
  present for `HEAD`'s tree.
- [ ] 4.5 The step table grants `scripts/change-workflow gather *` to validate and
  `scripts/change-workflow evidence *` to validate, review, triage, merge, closeout,
  and archive cleanup, and drops grants to removed subcommands. Every step is
  denied edits under `.claude/`: this task is the orchestrator's, on the owner's
  word before the section's session starts; the session commits it with the
  section. Verify: `test_change_workflow_steps.py` passes, and the assumptions test
  passes.
- [ ] 4.6 Move `change-validate` and `change-orchestrate` to the new commands only —
  `evidence` in place of `config parts`, `gather` and `gather --kind` in place of
  `run validation`, evidence paths in place of `.snapshot/validation/` — leaving
  their repository material for section 7. Verify: `make check-agent-skills` and
  the assumptions test pass, and a search of `.agents/skills/` finds no `run
  validation` or `config parts`.
- [ ] 4.7 Verification point: the suites above; `run pre-commit` passes; the live
  check of 4.4. End-to-end: none.

## 5. Actions and hooks around steps

Delivers the engine's table of actions before and after each step, the built-in
gathering before validate and cleanup before archive cleanup, the repository's step
hooks with their failure rules, the inputs directory, and `run before|after` (D7,
D8; CW-g6th, CW-ikmm, CW-h3ks, CW-b7fl, CW-a4fl, CW-i9np, CW-b2xr, CW-q5fy). Files:
`scripts/change_workflow/graph.py`, `wrapper.py`, `hooks.py`, `cli.py`,
`running.py`, `log.py`, `history.py`, `workflow.mk`,
`test_change_workflow_wrapper.py`, `test_change_workflow_hooks.py`,
`test_change_workflow_cli.py`, `test_change_workflow_graph.py`.

- [ ] 5.1 Add, beside `HOOK_STEPS` in `graph.py`, the table of each step's actions
  before and after it, holding `gather` before `validate` and `run cleanup` before
  `archive-cleanup` (D7). Verify: a unit test of the table's entries.
- [ ] 5.2 Give each run an inputs directory, `reviews/runs/<run>/before/` and
  `…/after/`, named on its log line; write `status.md` with each action's or hook's
  closing line, exit status, and log path; keep each hook's printed output as a log;
  pass it as `{inputs}` (CW-i9np; CW-q5fy). `history` copies it (CW-hak6). Verify:
  library-integration tests for the layout, the log line's field, and CW-i9np's
  large-artifact scenario's layout.
- [ ] 5.3 The wrapper runs the built-in action, then `before-<step>`, before the
  session, a review's and triage's hooks given `{kind}`; an absent or empty hook runs
  nothing and the run says so; a failing action or hook never prevents the session,
  its failure in `status.md` and the session's prompt naming the directory; a hook
  the check refuses refuses the step (D7, D8; CW-g6th, CW-h3ks, CW-b7fl). Verify:
  library-integration tests with the harness doubled for CW-g6th's failing-local
  scenario, CW-b7fl's scenario, and CW-h3ks's absent-hook scenario.
- [ ] 5.4 After a `finished` outcome and before it is logged as final, the wrapper
  runs `after-<step>`; on failure it resumes the same session once with the
  failure; a second failure ends the run as a question naming the hook, with one
  final outcome logged (CW-a4fl). Verify: library-integration tests for CW-a4fl's
  implementation scenario and the second failure becoming a question.
- [ ] 5.5 Add `run before|after <step> <change>` for interactive runs, held to its
  step (CW-h3ks; CW-u4pc). Verify: library-integration tests running it for
  implement and refusing it for another step's marker.
- [ ] 5.6 Document each step hook as a commented target in `workflow.mk`, with no
  default (D8). Verify: the fragment's comments name every `before-`/`after-` hook,
  it defines no new target, and the assumptions test passes.
- [ ] 5.7 Verification point: the suites above; `run pre-commit` passes.
  End-to-end: none.

## 6. A review's hooks

Delivers the review runner's `before-review` and `after-review`, and no hooks for an
interactive review (D7; CW-h3ks, CW-a4fl). Files: `scripts/change_workflow/review.py`,
`scripts/tests/test_change_workflow_review.py`.

- [ ] 6.1 `review.py` runs `before-review` with `{kind}` before starting the
  reviewer, giving it the run's inputs directory to read, and `after-review` once
  it has published the record and before it logs the outcome as final (CW-h3ks).
  Verify: library-integration tests with the reviewer doubled: the reviewer's prompt
  names the directory, and `after-review` sees the published record.
- [ ] 6.2 A failing `after-review` resumes no reviewer and ends the run as a question
  naming the hook, the record standing and never published again; an interactive
  review runs no hooks and says so (CW-a4fl; CW-h3ks). Verify: CW-a4fl's review
  scenario as a library-integration test, and a test that no second record is
  claimed.
- [ ] 6.3 Verification point: `test_change_workflow_review.py`; `run pre-commit`
  passes. End-to-end: none.

## 7. The guides and the validation skills

Delivers the four guides in full and `change-validate`, `change-archive-cleanup`, and
`change-merge` rewritten around evidence kinds with no repository material (D1, D4,
D6, D10, D14; CW-a8ss, CW-k7gd, CW-g2rs, CW-c5nt, CW-i9np, CW-n8tr). Files:
`.agents/evidence/*.md`, `.agents/skills/change-validate/SKILL.md`,
`change-archive-cleanup/SKILL.md`, `change-merge/SKILL.md`.

- [ ] 7.1 Write the guides from what leaves the skills, restating nothing the
  configuration holds (CW-g2rs): `helm.md` — its evidence files, preflights and
  warnings, the memory classification (MCW-epkd), the namespace and served scenarios,
  its record section, what its cleanup writes and that a merge conflict keeps the
  later `measured_at`; `pipeline.md` — its logs, lanes, `compose-logs.txt`, the
  collect's meaning, where scenarios are named (pytest markers under `e2e-tests/`,
  D14), `HELM_ALL_SCENARIOS`'s served list; `ci.md` — the dispatchable list
  (`scripts/ci_evidence.py`), the `dev` baseline's classes, the owed observation,
  the owed-line example (D14); `local.md` — its steps, attempts, and the worktree
  messages; each naming its UTC timestamp attempts. Verify: `scripts/change-workflow
  check config` passes, and a reading of each guide against its configuration entry
  finds no restated command or pattern.
- [ ] 7.2 Rewrite `change-validate`: the gathering already ran before the session
  (read `status.md` and the inputs directory's messages first); `evidence` for what
  is present, missing, waived, or not required; each kind assessed from its guide —
  present failing evidence diagnosed, unreadable gathered again with the reason, a
  rerun only after an environmental diagnosis and the owner's word, through
  `gather --kind`; the record's `Tree:`, `Evidence:` with each kind's result and
  source, the current attempt's path and any new attempt's reason, a section per
  kind as its guide says; waivers by kind; the contradiction notice (D4, D10;
  CW-a8ss, CW-c5nt, CW-e7lm). No repository target, path, or tool remains. Verify:
  the inverted test of section 9 reports nothing for this skill, and
  `make check-agent-skills` passes.
- [ ] 7.3 Rewrite `change-archive-cleanup` — the cleanups ran before the session; a
  tracked file one wrote is committed alone as its guide says; the pull request draft
  names the evidence the record names — and `change-merge` — a file a cleanup writes
  resolved as its guide says; the scenarios as the pipeline guide names them; no
  example remote (D7, D9; CW-ikmm, CW-k7gd). Verify: as 7.2.
- [ ] 7.4 Verification point: the skills check and the inverted test for these three
  skills; `run pre-commit` passes. End-to-end: none.

## 8. Neutral skills

Delivers every other workflow skill free of repository material, reading its inputs
directory and naming contradictions (D9, D12, D13, D14, D10; CW-n8tr, CW-i9np,
CW-c5nt, CW-k7gd, CW-5h8e). Files: `.agents/skills/change-plan/`, `change-implement/`,
`change-orchestrate/`, `change-closeout/`, `change-review/`, `change-design/`,
`change-triage/`, `guidance-review/` `SKILL.md`.

- [ ] 8.1 `change-closeout`: the repository's own parts "in the section the root
  guidance names", not restated; "the repository's comment check"; `scripts/
  change-workflow check tasks`; no `ARCHITECTURE.toml` (D9). `change-review` and
  `change-plan` name the repository's own closeout parts by role. Verify: the
  inverted test reports nothing for these skills.
- [ ] 8.2 `change-plan`: owed lines `Owed by validation (<kind> <argument>):`, the
  kinds and their guides learned from `config --json`, scenarios as the guide of the
  kind that runs them says, no `scripts/ci_evidence.py` or `openspec/config.yaml`
  path (D5, D14; CW-5h8e, CW-d1nj). `change-implement`: scenarios likewise, its
  command forms kept under the exemption owned by `sandbox-unattended-workflow-steps`
  (D9). `change-design`: the roadmap through `load.design`. `change-triage`: its
  worked example rewritten neutrally. Verify: as 8.1.
- [ ] 8.3 `change-orchestrate`: "a value of the owner's machine reaches a command
  through the environment" for `HELM_ALL_SCENARIOS`; its waiver example by kinds in
  general; one sentence per skipped hook; a second after-hook failure's question
  relayed without judging it (D13; CW-h3ks, CW-yvo1). Verify: as 8.1.
- [ ] 8.4 Every skill's opening, beside "Running unattended", reads its run's inputs
  directory — `status.md` and every top-level Markdown message in full, other files
  where a message directs — and names a contradiction it notices between a guide or
  message and its own text, following its own text; interactively it runs `run
  before <step> <change>` first and `run after` before recording (CW-i9np, CW-c5nt,
  CW-h3ks). `change-review` reads the evidence guides wherever it reads a validation
  record, and the inputs directories of the runs it reviews (D12; CW-k7gd).
  Verify: a reading of each skill's opening; `make check-agent-skills` passes.
- [ ] 8.5 Verification point: the skills check and the inverted test; `run
  pre-commit` passes. End-to-end: none.

## 9. The skills' neutrality test

Delivers CW-m4ps's test inverted for skills, with the exemption list (D9; CW-n8tr,
CW-m4ps, MCW-5tgp). Files: `scripts/tests/test_change_workflow_assumptions.py`, and
`openspec/specs/market-change-workflow/README.md`'s "How this repository provides
the workflow's roles" only where the test reads it.

- [ ] 9.1 Invert the test for skills: a make target or repository path a skill names
  is the workflow's own — `docs/guidance/workflow/`, OpenSpec's tree, the change
  index, the make fragment's targets, `scripts/change-workflow` — or in an exemption
  list naming `sandbox-unattended-workflow-steps` as its owner (implementation's
  command forms), or the test fails naming the target and the skill (CW-n8tr,
  CW-m4ps's skill scenario). The step table and the make fragment stay held to this
  repository's statement (MCW-5tgp). Verify: the test passes on the skills as
  sections 7 and 8 left them, and a fixture skill naming `make
  check-comment-hygiene` fails it.
- [ ] 9.2 Verification point: `test_change_workflow_assumptions.py`; `run pre-commit`
  passes. End-to-end: none.

## 10. Closeout

The workflow's closeout parts (`docs/guidance/workflow/closeout.md`), in order, with
this repository's own parts at its seventh position.

- [ ] 10.1 Comment hygiene — run the repository's comment check and read the comments
  the change added in `scripts/change_workflow/` and the scripts for history wording
  or a change reference; anything to rewrite returns the change to implementation.
- [ ] 10.2 Import placement — check the imports the change added in
  `scripts/change_workflow/evidence.py` and the edited modules; one to move returns
  the change to implementation.
- [ ] 10.3 Documentation compliance — check D1 to D17 against the placement rules and
  `openspec/README.md#documentation-placement`, and each permanent document written
  for the current state, with no wording relative to the change.
- [ ] 10.4 Narrative compression — shorten sections 1 to 9's notes to final
  behaviour, evidence, deferrals, and destinations, moving rationale into
  `design.md` first.
- [ ] 10.5 Roadmap currency — record that no goal of `docs/development/ROADMAP.md`
  is affected: the change serves the lesser goal "Make the change workflow a tool any
  repository can adopt" in `openspec/changes/README.md`.
- [ ] 10.6 Campaign index currency — in `openspec/changes/README.md`, the change's row
  (its notes and status); the lesser goal's "Current state", where validation and the
  closeout task no longer describe this repository's material in the skills; its
  gap "A skill can vary per repository only by being edited" removed as closed; a new
  unowned gap for hooks for every node (design's Open Questions). Leave
  `extract-change-workflow-repository`'s `Depends on` for archive cleanup. Run
  `scripts/change-workflow check index`.
- [ ] 10.7 Packaging — `scripts/change-workflow run pre-archive add-skill-extension-points`
  (`make check-packaging`, `make check-architecture-change`); the skills check runs
  among `run pre-commit`'s defaults.
- [ ] 10.8 End-to-end pipeline — record the run the latest passing validation names,
  its result, that no scenario exercises the workflow's tooling, and the commit it
  describes.
- [ ] 10.9 Promotion — write, beside the deltas the archive merges into
  `openspec/specs/change-workflow/spec.md` and `market-change-workflow/spec.md`:
  - `openspec/specs/change-workflow/index.md`: the sixteen entries 1.2 added, their
    summary lines checked against the requirements as implemented; summary lines
    revised for CW-zkhs,
    CW-e7lm, CW-g4oz, CW-x9bt, CW-ikmm, CW-b2xr, CW-v2dq, CW-q5fy, CW-o6kc, CW-5h8e,
    CW-m4ps; no id retired.
  - `openspec/specs/market-change-workflow/index.md`: summary lines revised for
    MCW-r4tx and MCW-5tgp.
  - `openspec/specs/change-workflow/README.md`: "Validation observes a committed
    slice" (D1–D5: evidence kinds, tree or commit identity and the unignored-file
    risk, presence whoever wrote it, assessment and `gather`, requirement by kind);
    "A step run's life" and "The hooks" (D7, D8: actions around steps, step hooks,
    failures, the inputs directory); beside "Routing is code, with the model as
    backstop", deterministic work in the engine and judgement in the skill (D7);
    "A repository's configuration" (D6, D10, D11: the two injections, a guide
    restating nothing, no defence against the repository's own extensions, the
    check); "Leaf skills from one source" (D9); "The orchestrator relays and routes"
    (D13); "Interfaces are tiered" (D15: `evidence`, `gather`, `run before|after`
    public; `run validation` and `config parts` gone); "What an adopting repository
    provides" (validation's roles as evidence kinds, step hooks optional); "Current
    limits" — remove the limit naming this change, add hooks for every node and
    identity by declared inputs.
  - `openspec/specs/market-change-workflow/README.md`: "Validation's parts" (D16: the
    four kinds, their identities and paths, timestamp attempts, `local` evidence
    from the functional checks) and "How this repository provides the workflow's
    roles".
  - `docs/change-workflow-handbook.md`: "Customization" (step hooks, guides) and
    "What each step does" (validation's gathering before the session).
  - The design-promotion record in `design.md`, a row for each of D1 to D17, those
    for D14, D15, and D17 saying why each has no permanent destination, as the
    proposal's "Knowledge to promote" gives it.
  Run `make check-spec-index CHANGE=add-skill-extension-points`.
- [ ] 10.10 Guidance placement — this change adds `.agents/evidence/` guides, which
  are extensions to steps and carry no layer tag (D6); confirm no file under
  `docs/guidance/` changed, or check each that did, then run `make check-guidance`.
- [ ] 10.11 Documentation citations — `make check-doc-citations
  CHANGE=add-skill-extension-points`, resolving every match; then
  `scripts/change-workflow openspec validate add-skill-extension-points --strict`.
- [ ] 10.12 Archival — `scripts/change-workflow openspec archive
  add-skill-extension-points -y`, merging the deltas (no `--skip-specs`: no
  permanent `spec.md` was edited by hand); read each merged requirement once; point
  the row at the archive; `scripts/change-workflow run pre-commit
  add-skill-extension-points`.
