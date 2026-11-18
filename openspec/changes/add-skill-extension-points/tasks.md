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

- [x] 1.1 Rewrite the comment at `scripts/tests/test_change_workflow_log.py:1005` that
  names section numbers ("splits open section 4 into 4 to 6") to describe the
  behaviour it sets up, so the repository's comment check passes and every later
  commit's `pre-commit` can (a found defect, `docs/guidance/workflow/changes.md#defects-found-during-a-change`;
  record it in this task's note). Verify: `make check-comment-hygiene` passes.
  - Done: a defect outside the change's scope, from an earlier commit — the comment
    named section numbers, which the comment check refuses. It now says a replan
    after a return renumbers the open round's sections. `make check-comment-hygiene`
    passes.
- [x] 1.2 Add `openspec/specs/change-workflow/index.md`'s entries for the sixteen ids
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
  - Done: the sixteen entries are under the four groups named, each linked to its
    requirement's heading slug. `make check-spec-index CHANGE=add-skill-extension-points`
    passes.
- [x] 1.3 In `config.py`, replace `Part` and `_parts` with an evidence kind read from
  `[validation.evidence.<kind>]`: `required` (`always` or `owed`), `evidence` (a
  pattern), `run` or `start` and `collect`, `guide`, optional `after` and `cleanup`;
  drop `owed` as a key, owing following from `required = "owed"` (D5, D6; CW-g4oz).
  Keep `[validation] preflight`. Verify: unit tests in
  `test_change_workflow_config.py` read a four-kind configuration and refuse a
  `[validation.parts]` table as an unknown key.
  - Done: `config.Kind` replaces `Part`. `owed` is a property, `required == "owed"`.
    `identity` (tree or commit) is read from the pattern, and `directory` is the
    pattern's fixed directory (`fixed_directory`). `Configuration.kinds` and `kind()`
    replace `parts` and `part()`, and the required field `PARTS` became `EVIDENCE`,
    `validation.evidence`. Unit tests: `test_a_four_kind_configuration_is_read`, the
    `[validation.parts.local]` row of
    `test_a_malformed_configuration_is_refused_naming_the_field`, and
    `test_a_patterns_fixed_directory_ends_at_its_first_unfixed_segment`. All pass.
- [x] 1.4 Add the check's refusals, each naming the field (D11; CW-w8ne): an undefined
  key or wrong type; `required` outside `always`/`owed`; neither or both of `run` and
  `start` with `collect`; an `after` naming no kind declared before it, or a started
  kind's `after` naming a `run` kind (CW-g4oz's two scenarios); a pattern holding
  neither or both of `{tree}` and `{commit}` (CW-t3ev); a pattern whose fixed
  directory `git check-ignore` does not report ignored (CW-g1gn's scenario); an owed
  kind's pattern without `{owed}`, and `{owed}` outside an owed kind (CW-r5qk's
  scenario); a kind with no `guide`, or one missing or empty (CW-k7gd's scenario).
  Verify: one unit test per refusal, each asserting the field named.
  - Done: unit tests, with Git's ignoring doubled at `config.check`'s `unignored`
    seam:
    - `test_a_malformed_kind_is_refused_naming_the_field`, one row per refusal, each
      asserting the field named;
    - `test_a_kind_naming_an_empty_guide_is_refused`;
    - `test_an_evidence_directory_git_does_not_ignore_is_refused`, for the
      unignored-directory refusal.
    All pass. Beyond the plan's list, the check also refuses the following, each a
    row of the first test:
    - a missing `evidence`;
    - a pattern naming any placeholder but the identity and `{owed}`;
    - an absolute pattern or guide, or one holding `..`;
    - a pattern with no fixed directory;
    - a guide that is no file.
  - Git is asked about the evidence directories once per load: one `git check-ignore`
    covers every kind's fixed directory (`config.git_unignored`).
    - Outside a Git checkout nothing is refused, since nothing is tracked there.
    - Any other status from Git is told apart by `git rev-parse
      --is-inside-work-tree`'s exit status, never by Git's (translated) message.
  - Two tests drive the real Git, and both pass:
    - `test_an_evidence_pattern_under_a_tracked_directory`, CW-g1gn's scenario, a
      library-integration test through `config`, `config --json`, and `check config`
      on a real repository;
    - `test_outside_a_git_checkout_no_evidence_directory_is_refused`.
  - Other tests that load a configuration from a temporary directory outside Git
    reach the real Git on its not-a-checkout path. The Hooks unit tests double it.
- [x] 1.5 Extend placeholder availability (CW-v2dq): `{tree}` and `{commit}` in a
  kind's commands and pattern and in `after-functional-change` and
  `pre-commit-functional`; `{kind}` in review and triage hooks; `{inputs}` in step
  hooks; and accept hook keys `before-<step>` and `after-<step>` for each step in
  `graph.STEPS`, refusing any other `before-`/`after-` key (D7, D11). The hooks are
  only declared here; section 5 runs them. Verify: unit tests for each placeholder
  refused where unavailable, and for `before-validate` accepted and
  `before-round` refused.
  - Done: `config.STEP_HOOKS` holds `before-`/`after-` for each step in `graph.STEPS`.
    A misspelt step hook is refused as naming no step.
    - Unit tests: the placeholder and step-hook rows of
      `test_a_malformed_configuration_is_refused_naming_the_field` (`{tree}` in
      `pre-commit`, `{commit}` in `pre-archive`, `{inputs}` in `pre-commit`, `{kind}`
      in `before-implement`, `{tree}` in `after-validate`, `before-round`,
      `after-implementation`), the kind command rows of
      `test_a_malformed_kind_is_refused_naming_the_field`, and
      `test_placeholders_are_accepted_where_they_are_available`, which covers
      `before-validate`, `before-review` with `{kind}` and `{inputs}`, and
      `after-triage`.
    - A kind's `cleanup` takes the tree and the commit, as every command of a kind
      does (CW-v2dq); `run cleanup` fills them in section 3.
    - The check admits `{tree}` and `{commit}` from here, but `run validation` and
      the functional hooks fill neither until section 3 (3.3, 3.4): a command naming
      them is refused at run time until then, and none does before section 4.
    - All pass.
- [x] 1.6 `config` and `config --json` list each kind's fields, its guide among them,
  and each step hook as declared or absent (CW-o6kc). Verify: a library-integration
  test of `config --json` naming every kind's `guide`.
  - Done: `test_config_as_json_names_every_kinds_guide_and_each_step_hook`, a
    library-integration test through `cli.main` on a real temporary Git checkout
    holding the four kinds' guides and ignoring `.snapshot/`. It passes.
- [x] 1.7 Move every current reader to kinds without changing behaviour yet:
  `config parts` and `run validation … run|start|collect` resolve kinds by name
  (section 3 replaces them), and `history` takes its evidence directories from each
  pattern's fixed directory (`config.evidence()`). Verify: the existing
  `test_change_workflow_hooks.py` and `test_change_history.py` cases pass against a
  kinds configuration.
  - Done: `hooks.py`, `cli.py` (`config parts`, a waiver's kinds), and `history.py`
    read kinds. `config parts --json` keeps its keys, `part` among them, and its
    `evidence` is now the kind's pattern.
    - `test_change_workflow_hooks.py` and `test_change_history.py` pass against kinds
      configurations, the history ones with patterns fixing the two directories they
      copy from.
    - The test fixture `configured` writes each test kind's guide and, in a Git
      checkout, ignores `.snapshot/` through `.git/info/exclude`.
      `ignore_evidence` does the same for a checkout cloned after it, as two tests in
      `test_change_workflow_cli.py` and `test_change_workflow_review.py` needed.
    - `test_change_clone.py` and the assumptions test read kinds.
  - Behaviour shifts with 1.8's configuration until sections 3 and 4, though the
    engine's code paths are unchanged:
    - `config parts` and each kind's closing line name a pattern under
      `.snapshot/evidence/`, where nothing writes yet; `change-validate` still reads
      them as evidence directories (section 4 moves the skill and the scripts).
    - `history` copies only under `.snapshot/evidence/` and still looks up a
      validated commit's first twelve characters (section 3.6 reworks it).
- [x] 1.8 Rewrite `.agents/workflow.toml`'s validation as four kinds (D16; MCW-r4tx):
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
  - Done by this session: the owner lifted the deny rule on the configuration for
    it (log seq 37).
    - The kinds keep today's order, `pipeline`, `ci`, `local`, `helm`, so `config
      parts` lists them as before, and `local` and `helm` are the gathering's run
      kinds in that order.
    - `scripts/change-workflow check config` is outside implementation's rules, so
      the check was read through `scripts/change-workflow config --json`, which
      checks the whole file the same way. It passes, as does
      `test_the_repositorys_own_configuration_passes_its_check`, which runs `check
      config` in process.
- [x] 1.9 Seed `.agents/evidence/local.md`, `helm.md`, `pipeline.md`, and `ci.md`, each
  non-empty prose naming what the kind shows, so the check passes; section 7 writes
  their full content (CW-k7gd). Verify: `scripts/change-workflow check config`
  passes and `make check-agent-skills` is unaffected.
  - Done: each guide is one paragraph naming what its kind shows and restating none
    of its configuration entry. The configuration check passes (read as in 1.8), and
    `make check-agent-skills` passes.
- [x] 1.10 Verification point: the unit and library-integration suites above;
  `scripts/change-workflow run pre-commit add-skill-extension-points` and the
  functional checks it runs before this commit pass.
  End-to-end: none — no scenario exercises the workflow's tooling.
  - Correction: checked although `run pre-commit` does not pass whole. Its only
    failures are below, none this section's and none it can fix:
    - `after-functional-change` passed.
    - `pre-commit-functional` failed only on the two step-table tests below; every
      other suite of `make test` passed, the scripts' 3179 passed.
    - `pre-commit`: its default checks passed, and `make check-repository` failed
      only on documentation citations. Those name
      `scripts/change_workflow/evidence.py` and
      `scripts/tests/test_change_workflow_evidence.py`, which section 2 creates.
    - A history-wording hit in a comment this section added was fixed, and the
      repository's checks were rerun.
  - Evidence:
    - The scripts' suites (`make test-release-tooling`): 3179 passed, 2 failed.
    - The two failures are `test_change_workflow_steps.py`'s
      `test_no_step_may_edit_the_configuration` and
      `test_no_step_may_edit_its_own_permissions`. They fail at `HEAD` before this
      section (`run test-before … --at HEAD`). The cause is the orchestrator's commit
      `57b7baaad`, which lifted those deny rules in `.claude/change-steps.toml` for
      this session.
    - This session cannot restore them: the harness refuses every edit under
      `.claude/`, whatever the table says. Restoring them is the orchestrator's, when
      the session ends.
  - The new config tests fail at the round's base as they are collected, since they
    import fixtures only this section adds (`run test-before`).
  - End-to-end: none — confirmed; no scenario under `e2e-tests/` exercises the
    workflow's tooling.
  - Handoff to section 2:
    - `Kind.identity` and `Kind.directory` are ready for `evidence`.
    - Filling a pattern needs a fill that does not shell-quote; `config.fill` quotes,
      so add a separate one.
    - `config.PlannedRun.entry()` still says `part`, for `config parts`' consumers,
      until section 3 removes the subcommand.

## 2. Evidence identity, owed lines, and presence

Delivers the tree and commit identities, owed lines naming their kind and a safe
argument, and `scripts/change-workflow evidence <change> [--json]` (D2, D3, D4, D5;
CW-t3ev, CW-p4rs, CW-r5qk, CW-e2vd, CW-zkhs). Files:
`scripts/change_workflow/` (a new `evidence.py`, `tasks.py`, `cli.py`, `log.py`'s
waiver reading), `scripts/tests/test_check_tasks.py`, a new
`scripts/tests/test_change_workflow_evidence.py`.

- [x] 2.1 Compute identity (D2; CW-t3ev): the tree as `git write-tree` of the
  worktree as tested, its changes — staged, unstaged, untracked and not ignored —
  added to a temporary index (`GIT_INDEX_FILE`), never the checkout's own index; the
  commit as `HEAD`'s full object name. Verify: library-integration tests: a clean
  worktree's tree equals `HEAD^{tree}`; a dirty worktree's tree equals the tree of the
  commit that then commits exactly those changes; an ignored file changes nothing;
  the checkout's index is unchanged afterwards.
  - Done in the new `scripts/change_workflow/evidence.py`:
    - `worktree_tree` copies the checkout's index (`git rev-parse --git-path index`)
      into a temporary directory, runs `git add --all` and `git write-tree` with
      `GIT_INDEX_FILE` naming the copy, and drops it.
    - `head_tree` and `head_commit` read `HEAD^{tree}` and `HEAD`.
  - Library-integration tests in `test_change_workflow_evidence.py`, on a real
    temporary repository, all passing:
    - `test_a_clean_worktrees_tree_is_heads`;
    - `test_a_dirty_worktrees_tree_is_the_tree_its_commit_then_holds`: a staged
      change with a further unstaged edit, an untracked file, and a deletion;
    - `test_an_ignored_file_changes_no_tree`;
    - `test_the_checkouts_index_is_left_as_it_was`: the index file's bytes and `git
      status` are unchanged.
- [x] 2.2 Extend the owed-line reader in `tasks.py` (D5; CW-r5qk): `Owed by validation
  (<kind> <argument>):` names its kind; a line naming no kind is the one owed kind,
  its argument the first word in backticks, refused when more than one kind is owed
  or it has no backticked argument; an argument that is empty, `.`, `..`, or holds
  `/`, whitespace, `*`, `?`, `[`, or `]` is refused, naming the section. `check
  tasks` reports a refusal. Verify: unit tests for each form and each refusal,
  including CW-r5qk's `(ci ..)` scenario and a legacy line read as `ci tests.yml`.
  - Done: `tasks.read_owed` reads each owed line as a `tasks.Owed`: its section, its
    line, its kind and argument, or its refusal.
    - Lines are read against `tasks.owed_kinds(configuration)`, the names of the
      kinds declared owed. `owed_lines(tasks, owed)` keeps the complete sections'.
    - A refused line keeps the kind it names only when that kind is owed, so
      `evidence` reports it under that kind; one naming a kind that is not owed is
      reported under no kind, apart from the kind's own entry.
    - Beyond the plan, two more lines are refused: one naming a kind that is not
      owed, and one where no kind is owed. So is a line of neither form.
    - `check tasks` loads the configuration and refuses any owed line in any section,
      exiting 1 with each refusal's line; its OK message now says so.
  - Unit tests in `test_check_tasks.py`, all passing:
    - `test_an_owed_line_names_its_kind_and_argument`, each form, a line naming no
      kind read as `ci tests.yml` among them;
    - `test_an_owed_line_is_refused_naming_its_section`, one row per refusal — each
      glob character alone, `]` included, and `(ci ..)` among them;
    - `test_a_refused_line_keeps_the_owed_kind_it_names`;
    - `test_only_the_sections_given_as_complete_owe_anything`;
    - `test_the_owed_lines_of_a_task_list_are_its_complete_sections`, reading a file.
  - A command-level test, `test_the_command_reports_a_refused_owed_line`, passes:
    CW-r5qk's `(ci ..)` scenario through `check tasks` against a configuration on
    disk, outside Git. The existing `check tasks` command tests now load the
    configuration too.
  - `log.waived_parts` is now `log.waived_kinds`, its refusals naming evidence kinds.
    `config parts` (until section 3 removes it) groups owed arguments by kind and
    refuses a task list with a refused line.
- [x] 2.3 Add `evidence <change> [--json]` (D4; CW-e2vd): for each kind, its
  requirement — `always`, owed once per argument complete sections owe, `not
  required`, or `waived` with the decision's `seq` from the log's standing waivers
  (`log.waived_parts`, read as kinds) — its pattern filled with `HEAD`'s tree or
  commit and any owed argument, and every match, the last in path order marked
  current; an owed-line refusal reported in place of a status. Present means matched
  whoever wrote it (D3; CW-p4rs). Verify: library-integration tests for CW-e2vd's
  two scenarios, CW-r5qk's two-workflow scenario, CW-t3ev's amended-message
  scenario (tree kinds present, the commit kind missing), and CW-zkhs's earlier-tree
  scenario.
  - Done: `evidence.change_report` lists each kind in declaration order:
    - an `always` kind once;
    - an owed kind once per argument the complete sections owe it, in first-owed
      order, with the sections owing it; then each refused line naming it, as
      `refused` with its refusal; or, owing none, once as `not required`;
    - a refused line naming no owed kind, after every kind.
  - Each entry also carries:
    - its identity, and its pattern filled with `HEAD`'s tree, its commit, and the
      argument (`*` for a kind not required), never shell-quoted (`evidence.filled`);
    - every match in path order, the last `current`;
    - a waived kind's waiver `seq` and decision.
  - `scripts/change-workflow evidence <change> [--json]` prints it, exiting 0 however
    much is missing and 1 when it cannot be read.
  - Library-integration tests in `test_change_workflow_evidence.py`, all passing:
    - CW-e2vd's two scenarios (`test_only_local_evidence_exists`,
      `test_a_rerun_beside_a_failed_attempt`);
    - CW-r5qk's two-workflow, pipeline, and `(ci ..)` scenarios, and a refused line
      naming a kind owed always listed apart from that kind;
    - CW-t3ev's amended-message scenario, whose commit is amended by Git;
    - CW-zkhs's earlier-tree scenario;
    - CW-p4rs, evidence placed at the pattern by hand;
    - a waived kind;
    - the command's lines and JSON;
    - its refusal with no kinds declared.
- [x] 2.4 Verification point: `test_change_workflow_evidence.py` and
  `test_check_tasks.py`; `run pre-commit` passes. End-to-end: none.
  - Correction: checked though `run pre-commit` does not pass whole, as in 1.10.
    - `after-functional-change` and `pre-commit` passed; the repository's checks
      passed, citations included, now that `evidence.py` exists.
    - `pre-commit-functional` failed only on the same two step-table tests, which
      fail from `57b7baaad`'s lifted deny rules. Every other suite of `make test`
      passed, the scripts' 3217 passed.
    - After the fresh-context check's fixes, both section 2 test files were rerun:
      56 passed.
  - End-to-end: none — confirmed.
  - Handoff to section 3:
    - `evidence.change_report` is what `gather` needs to find what is missing: each
      entry's `status`, `kind`, and `owed`.
    - `evidence.worktree_tree` is what the functional hooks' `{tree}` takes.
    - `evidence.filled` fills a pattern unquoted, where `config.fill` quotes a
      command's values.

## 3. Gathering and cleanup by kind

Delivers `gather`, replacing `run validation … preflight|run|start|collect` and
`config parts`, the functional hooks' `{tree}`, `run cleanup` over kinds, and history
by the evidence records name (D4, D7's gathering, D15; CW-g6th's command, CW-x9bt,
CW-ikmm's rerun, CW-q5fy's kinds, CW-e7lm's waivers). Files: `scripts/change_workflow/`
(`hooks.py`, `cli.py`, `evidence.py`, `running.py`, `history.py`, `graph.py`'s
`HOOK_STEPS`), `test_change_workflow_hooks.py`, `test_change_workflow_cli.py`,
`test_change_history.py`, `test_change_workflow_evidence.py`.

- [x] 3.1 Add `gather <change>`: the preflight, the guarded push of `HEAD`, every
  missing `start` kind and owed argument dispatched, the missing `run` kinds in
  order keeping `after`, then each started kind collected; present evidence never
  touched; a waived kind skipped unless a merge since it was last assessed lapses
  the waiver (CW-g6th; CW-e7lm). A failing kind fails `gather`'s exit status but
  every other kind still runs. Verify: library-integration tests for CW-g6th's
  "Gathering leaves present evidence alone" and CW-g4oz's dispatch-before-run order,
  with the commands doubled as shell scripts writing at the pattern.
  - Done in a new module, `scripts/change_workflow/gather.py`, since the guarded
    push imports the hook runner and the gathering needs both.
    - `Gathering.missing` reads `evidence.change_report` and gathers each `missing`
      entry. A `waived` entry with nothing present is gathered only when the lapse
      seam names why. A refused owed line fails the gathering.
    - The push runs only when a start is due. A refused push skips every start, as a
      failed attempt, and still runs the run kinds.
    - A failed preflight gathers nothing, keeping the configuration's "a failure
      ending validation as environmental". Otherwise evidence gathered in a refused
      environment would count as present.
    - The gathering refuses a worktree whose tree is not `HEAD`'s, so `{tree}` is the
      tree `evidence` reads.
  - The lapse is mechanical (`merge_lapse`), read per kind: a merge among the
    commits since the kind last ran, which is the `commit` of the latest validation
    whose logged `invoked` names the kind, or else the latest validation.
    - With no validation logged, nothing lapses.
    - A commit Git cannot read lapses the waiver.
    - A lapsed attempt's closing line says why. A lapsed waiver over present evidence
      is reported as present, not gathered.
    - A run's `invoked` names the kinds its gathering ran, but not those it found
      present. So "since it last ran" falls back to the latest validation when no
      run invoked the kind.
  - Tests, in a new `scripts/tests/test_change_workflow_gather.py` rather than the
    files the plan named, beside the module. They are library integration: a real
    temporary repository, `evidence` reading what each kind's shell command wrote at
    its pattern, and the push and the lapse doubled at the gathering's seams. All
    pass:
    - `test_the_gathering_starts_every_dispatch_then_runs_then_collects`;
    - `test_a_long_kind_declared_before_a_dispatched_one`, CW-g4oz's scenario;
    - `test_gathering_leaves_present_evidence_alone`, CW-g6th's scenario;
    - a failing kind, a refused push, a failed preflight, an absent preflight, and a
      worktree that is not `HEAD`'s;
    - `test_only_validation_gathers`;
    - a waived kind skipped, a waiver lapsed (through the seam), and a lapsed waiver
      over present evidence;
    - `merge_lapse` reading a real merge per kind, and an unreadable commit;
    - `test_the_command_gathers_a_waived_kind_a_merge_lapsed`, the lapse read from
      the log and Git through `cli.main`.
    `test_validation_gathers_this_repositorys_kinds` doubles the hook runner's shell,
    since this repository's commands build and deploy.
  - Round-triage edit, review 36 F2: the task above says "since it was last
    assessed", and the delta's CW-e7lm said the same. CW-g6th, D7, and `merge_lapse`
    measure the merge from the last validation that *ran* the kind. CW-e7lm is now
    split: the waiver's condition is measured from the last validation that assessed
    the kind, and the merge from the last one that ran it, or the latest validation
    when none did. Its merge scenario says "last ran". `change-validate`'s Waivers
    paragraph says the same. No code changed: the invocation errs only toward
    gathering a waived kind again, and a lapse over present evidence gathers
    nothing.
- [x] 3.2 Add `gather <change> --kind <kind> [--owed <argument>] [--lapsed]`: a new
  attempt of that kind whatever is present, of one owed argument or each owed
  without `--owed`; a waived kind refused without `--lapsed` (D4; CW-g6th). Verify:
  library-integration tests for CW-g6th's one-workflow rerun scenario and the
  refusal of a waived kind.
  - Done: `Gathering.again`.
    - `--owed` must name an argument a complete section owes.
    - `--lapsed` is refused for a kind not waived.
    - `--owed` and `--lapsed` without `--kind` are usage errors.
    - `--lapsed` is a flag, the skill writing the reason in the record; the
      invocation records `lapsed: "gathered with --lapsed"`.
    - The proposal's interface row now reads `gather <change> [--kind <kind>
      [--owed <argument>] [--lapsed]]`, as D7 and this task have it, `--lapsed`
      qualifying `--kind`.
  - Library-integration tests, all passing:
    - `test_one_owed_workflow_is_rerun_after_an_environmental_failure`, CW-g6th's
      scenario, the new attempt current by path order;
    - `test_a_kind_is_gathered_again_whatever_is_present`;
    - `test_a_waived_kind_is_refused_without_lapsed`;
    - `test_a_new_attempt_is_refused_naming_why`;
    - `test_an_owed_kind_no_section_owes_has_nothing_to_gather`;
    - `test_the_command_gathers_and_keeps_what_it_ran`, through `cli.main`, with
      the session's kept invocations read back.
- [x] 3.3 Key a start's marker by tree or commit, kind, and owed argument, fill
  `{after}` from it, fill `{tree}`, `{commit}`, and `{owed}` in a kind's commands,
  and close each kind with its line naming the kind, argument, identity, result,
  exit status, and evidence (CW-x9bt); record each invocation as `invoked` on the
  run's line (CW-q5fy). Verify: CW-x9bt's two scenarios and CW-q5fy's Helm scenario
  as library-integration tests.
  - Done:
    - `hooks.marker_key(identity, kind, owed)`. `Hooks.start`, `keep_marker`, and
      `kept_marker` are the hook runner's for the gathering.
    - A kind's `{tree}` is `HEAD`'s tree, which the gathering checks the worktree
      holds; `{commit}` is `HEAD`'s.
    - Each attempt closes with `[change-workflow] gather <kind> [<argument>] at
      <tree|commit> <id>: <result>; evidence <current match|none>`.
    - `Invoked.part` is now `Invoked.kind`, so a run's `invoked` entries say
      `"hook": "gather", "kind": …`.
  - Library-integration tests, all passing:
    - `test_two_owed_runs_are_collected_side_by_side`;
    - `test_the_pipeline_is_collected_past_the_marker_its_start_printed`, which also
      reads the marker kept for `<commit> pipeline`;
    - `test_each_kind_closes_with_its_line`;
    - `test_a_later_start_replaces_its_marker` and
      `test_a_start_that_failed_or_printed_nothing_keeps_no_marker_and_is_not_collected`;
    - CW-q5fy's Helm scenario as `test_validations_helm_kind_fails` in
      `test_change_workflow_hooks.py`: a wrapper run with the harness doubled, whose
      step runs `gather --kind helm` through `cli.main` on a real repository.
- [x] 3.4 Fill `{tree}` and `{commit}` in `after-functional-change` and
  `pre-commit-functional` from the worktree the hook runs on (CW-v2dq; D3).
  Verify: a library-integration test of `run pre-commit` with a hook echoing
  `{tree}` matching the tree of the commit then made.
  - Done: `Hooks.identities` reads the tree only for a command naming it, as each
    functional hook starts, so `pre-commit-functional` sees the tree after
    `after-functional-change`'s relock.
  - Tests, both passing:
    - `test_a_functional_hooks_tree_is_the_tree_its_commit_then_holds`, library
      integration: `run pre-commit` through `cli.main` on a real repository. Its
      `after-functional-change` writes a file into the worktree, as a relock does,
      and its `pre-commit-functional` writes `{tree} {commit}` outside the worktree;
      the tree matches the commit then made, the written file included;
    - `test_only_the_functional_hooks_read_the_tree`, a unit test.
- [x] 3.5 Remove `run validation … preflight|run|start|collect` and `config parts`,
  `gather` and `evidence` replacing them (D15); `HOOK_STEPS` admits `gather` for
  validate and the wrapper (section 5). `run cleanup <change>` runs every kind's
  `cleanup` in declaration order as one list (CW-ikmm). Verify: the CLI tests
  assert the removed subcommands exit 2 and CW-ikmm's two scenarios pass.
  - Done:
    - `run`'s choices lose `validation`, and `config` loses `parts`.
    - `config.PlannedRun`, `plan`, `plan_lines`, and `plan_json` are gone, as are
      `hooks.VALIDATION`, `PREFLIGHT`, and `PHASES`.
    - `HOOK_STEPS["gather"]` is `{"validate"}`; the wrapper's use is section 5's.
    - `run cleanup` fills `{tree}` and `{commit}`.
  - Tests, all passing:
    - `test_run_takes_each_form_alone_and_validation_has_no_run`, in the hooks file:
      `run validation …` and `config parts` exit 2;
    - CW-ikmm's two scenarios (`test_a_changes_validation_left_resources`,
      `test_a_parts_cleanup_finds_nothing`);
    - `test_a_cleanup_is_given_the_checkouts_tree_and_commit`.
  - The step-table test now asserts `HOOK_STEPS["gather"]`. The step table itself
    (4.5) still grants `run *`, which no longer reaches validation.
  - `change-validate` still names `run validation` and `config parts` until 4.6, so
    between this commit and section 4's the skill names commands that are gone.
- [x] 3.6 `history` copies the evidence paths the change's records name, under each
  pattern's fixed directory, with each record's tree and commit (CW-hak6, unchanged
  in intent). Verify: `test_change_history.py` copies a record's cited
  `.snapshot/evidence/<tree>/local/<attempt>/` directory.
  - Done: a citation under an evidence directory now takes the whole path below it.
    - A cited file brings the attempt directory holding it, and a directory inside
      another copied is copied once.
    - Each record's `**Tree:**` and `**Commit:**` name a key under each directory,
      by its full object name.
    - The pipeline run's id and the twelve-character commit are not read, since no
      kind keys evidence by them.
    - A citation ending a sentence leaves its full stop out
      (`test_a_citation_ending_a_sentence_names_the_path_without_its_full_stop`).
  - `test_change_history.py`, all passing:
    - `test_the_first_copy_brings_the_records_and_named_evidence_to_the_same_paths`
      copies the record's tree and commit directories and the cited
      `.snapshot/evidence/<tree>/helm/<attempt>/` from its cited `summary.json`,
      leaving the tree's other attempt;
    - the absent-evidence and no-kind tests.
  - `test_change_clone.py`'s removal tests use full commits.
  - Round-triage fix, review 36 F1: history read only the layout this repository's
    patterns use. It copied a cited file with the directory holding it, and looked
    up each tree and commit as a directory directly under each fixed directory. With
    a pattern configuration admits, such as `.snapshot/runs/{tree}.json` or
    `run-{tree}/`, it copied the whole evidence directory and reported the named
    evidence absent. Now each kind's pattern is the authority:
    - A validated tree or commit is looked up only under the kinds keyed by that
      identity. The lookup globs each pattern as far as its identity's segment
      (`identity_glob`), with `{owed}` matching anything, and copies what matches,
      file or directory. `named_evidence` returns each key with its identity.
    - A directory a pattern reaches before its identity's segment is never copied
      whole. A cited file in one is copied alone, and a cited directory that is one is
      not copied.
    - Tests:
      - `test_change_history.py` (library integration, a real temporary clone):
        `test_the_kinds_pattern_says_which_evidence_the_records_name` for a
        file-shaped, an embedded-identity, and an owed per-argument pattern, each
        beside another tree's evidence. Each fails at `09584f30a` through `run
        test-before --at`: the unnamed sibling is copied, or the named evidence is
        reported absent.
      - `test_change_clone.py`'s removal fixtures now name a `**Tree:**`, since
        their one kind is tree-keyed.
      - Both suites: 103 passed.
    - The fresh-context check found five problems, all fixed:
      - a pattern with `{owed}` before its identity still copied a per-argument
        directory whole, so the shared directories are now every pattern's segments
        before its identity, not only the fixed directory;
      - a dropped cited directory the docstring didn't mention;
      - two docstring phrases and a stale test comment;
      - `change-validate` still measuring the merge lapse from the last assessment
        (see 36 F2 under 3.1).
    - `run pre-commit` on the fixes for 36 F1 and F2 passed whole:
      - `after-functional-change`: passed, exit 0;
      - `pre-commit-functional` (`make validate-local`: check-packaging and test
        passed, every suite): passed, exit 0;
      - `pre-commit`: passed, exit 0.
      - This note changes the tree that run checked.
    - End-to-end: none — no scenario exercises the workflow's tooling.
- [x] 3.7 Verification point: the suites above; `run pre-commit` passes. End-to-end:
  none.
  - Correction: checked though `run pre-commit` does not pass whole, as in 1.10.
    `pre-commit` passed; `pre-commit-functional` failed only on the same two
    step-table tests (`57b7baaad`'s lifted deny rules), every other suite passing.
    After the fresh-context check's fixes, `run pre-commit` ran again with the same
    result: the scripts' 3227 passed but for the same two; `pre-commit` passed.
  - End-to-end: none — confirmed.
  - `run test-before` on `test_change_history.py` fails at the round's base, mostly
    in setup, since the base engine refuses a kinds configuration.
  - Handoff to section 4:
    - The repository's kind commands can now take `TREE={tree}` and
      `COMMIT={commit}`.
    - `pre-commit-functional` can name `{tree}`.
    - `scripts/change-workflow gather` and `evidence` are what `change-validate` and
      `change-orchestrate` move to.

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

- [x] 4.1 `validate_slice.py` writes each attempt of `local` and `helm` under
  `.snapshot/evidence/<tree>/<kind>/<UTC timestamp>/`, its `summary.json` and logs
  there, given the tree (`TREE=`), and reads the latest Helm attempt for the capacity
  figure from there (D2, D4's path order; MCW-r4tx). Verify: `test_validate_slice.py`
  asserts the new paths, timestamp ordering, and `record-capacity` reading the
  current attempt.
  - Done:
    - A part's identity is its kind's (`IDENTITY`): the tree for `local` and `helm`,
      the commit for `ci`. `--tree` or `--commit` gives it, and the part refuses
      to start when the checkout holds another; without it, the part describes
      what the checkout holds.
    - The tree is computed as the engine computes `{tree}`: the checkout's index
      copied, `git add --all` and `git write-tree` on the copy (`worktree_tree`).
      A repository script reaches the engine only through its command
      (`scripts/workflow_command.py`), and no command prints the worktree's tree,
      so the script holds its own copy. Its test may not import the engine either
      (`test_no_script_but_the_engines_own_imports_the_engine`), so each
      computation is held to Git's own answer, the tree the commit then holds, in
      its own suite.
    - The clean-worktree checks became identity checks, steps `tree before`/`tree
      after` (`commit before`/`after` for `ci`), and after every step. A tree kind
      runs on a worktree with changes, as the functional checks before a commit do;
      a change to its tree mid-part fails the step with "the worktree changed",
      listing what the worktree holds against `HEAD`.
    - An attempt is `%Y%m%dT%H%M%S.%fZ` of its UTC start, so path order is time
      order. An attempt already started at the same instant is refused.
    - `summary.json` names `kind` (was `part`), `tree`, `commit` (`HEAD` as it
      started), and `attempt`. The printed last line keeps its form, `Attempt
      <attempt> logs and summary.json: <path>`.
    - `record-capacity` reads the latest record's validated commit, its tree through
      `git rev-parse <commit>^{tree}`, and the last Helm attempt of that tree in path
      order. A commit the checkout cannot read records nothing, saying why.
    - The previous validation's `resources.txt` is the latest attempt by name,
      across trees, in place of the file's modification time.
  - Tests in `test_validate_slice.py`, all passing:
    - unit tests through the doubled runner, reader, and tree: the new paths and
      fields; a worktree with changes tested and kept under its tree; a tree given
      that the worktree does not hold, refused before anything runs; a step changing
      the tree; two attempts in time order, the later current; the same instant
      refused; a branch switch mid-Helm; each part taking only its own identity; a
      workflow name reaching another directory, refused;
    - library integration on a real temporary repository: the worktree's tree, with
      staged, unstaged, untracked, and ignored files, is the tree its commit then
      holds, the checkout's index unchanged; an attempt with no tree given; and
      `record-capacity` reading the current attempt of a real commit's tree;
    - the Makefile targets' command lines with and without `TREE` and `COMMIT`
      (`make -n`).
- [x] 4.2 `ci_evidence.py` and `fetch-e2e-logs.py` write the `ci` and `pipeline`
  evidence under `.snapshot/evidence/<commit>/ci-<workflow>/<UTC timestamp>/` and
  `.snapshot/evidence/<commit>/pipeline/<UTC timestamp>/`, each with a
  `summary.json`, given the commit (`COMMIT=`); markers unchanged (MCW-zk52,
  MCW-7hr1, MCW-2lzw). Verify: `test_ci_evidence.py` and `test_fetch_e2e_logs.py`.
  - Done, differing from the plan's file list: the `ci` evidence is written by
    `validate_slice.py ci` (`make validate-ci`, the kind's `collect`), under
    `<commit>/ci-<workflow>/<attempt>/`. `ci_evidence.py` only dispatches and
    classes, so only its docstring changed. Dispatch markers are unchanged.
  - `fetch-e2e-logs.py --evidence <commit>` (`make fetch-e2e-logs COMMIT=<commit>`)
    keeps the commit's run under `<commit>/pipeline/<attempt>/`, with a
    `summary.json` naming the run, its conclusion, the logs kept, `passed`, and an
    `error`. The summary is written whatever happened, so a fetch that found no run
    leaves an attempt saying why. No archive is made, and the fetch exits 1 unless
    the run concluded `success`. Without `COMMIT`, the manual fetch is as before;
    `docs/development/TESTING.md` says so.
  - Tests, all passing: `test_fetch_e2e_logs.py`, unit tests through its doubled
    runner (the evidence's path and summary, a short commit kept under its full
    name, a run never listed, the exit status by conclusion, `--evidence` alone, the
    target's command); `test_ci_evidence.py` unchanged; the `ci` part's tests in
    `test_validate_slice.py` assert its new directory.
- [x] 4.3 `validate_parallel.py` follows the new layout. Verify:
  `test_validate_parallel.py`.
  - Done: it reads an attempt named by time. `test_validate_parallel.py`, unit tests
    with the launches and reads doubled, passes: 47 passed.
- [x] 4.4 The configuration's kind commands pass `TREE={tree}` or `COMMIT={commit}`,
  and `pre-commit-functional` leaves `local` evidence for `{tree}` — through a
  target that clears the wheelhouse, checks packaging, and runs every suite on the
  worktree as it stands, writing at `local`'s pattern (MCW-r4tx's second scenario).
  The configuration is the orchestrator's to edit, on the owner's word, before the
  session starts; the session commits it. Verify: after a functional commit,
  `scripts/change-workflow evidence add-skill-extension-points` lists `local`
  present for `HEAD`'s tree.
  - Done by this session, the owner having lifted the configuration's deny rule for
    it (log seq 42):
    - `pre-commit-functional = ["make validate-local TREE={tree}"]`, the `local`
      kind's own run. `make validate-local` clears the wheelhouse, checks packaging,
      and runs every suite.
    - `local` and `helm` pass `TREE={tree}`; the `pipeline` and `ci` collects pass
      `COMMIT={commit}`.
  - `scripts/change-workflow config --json` reads the file with the whole check, and
    it passes (`check config` is outside implementation's rules, as in 1.8).
    `test_the_repository_declares_every_hook` asserts the hook is the kind's run.
  - The live check follows the commit: recording its result here would change the
    tree it checks. The session's report gives it. Before the commit, `run
    pre-commit`'s `validate-local` ran the whole `make test` on the worktree, and
    its `tree before` and `tree after` steps held.
- [x] 4.5 The step table grants `scripts/change-workflow gather *` to validate and
  `scripts/change-workflow evidence *` to validate, review, triage, merge, closeout,
  and archive cleanup, and drops grants to removed subcommands. Every step is
  denied edits under `.claude/`: this task is the orchestrator's, on the owner's
  word before the section's session starts; the session commits it with the
  section. Verify: `test_change_workflow_steps.py` passes, and the assumptions test
  passes.
  - Not yet done; the edit is not in the worktree. The first session tried to restore
    the lifted deny lines, and the harness refused the edit under `.claude/` even
    with the deny rule lifted (log seq 37): no allow rule names `.claude/`. The edit
    is the orchestrator's, or a run's granted `Edit(.claude/change-steps.toml)`:
    - `[steps.validate]` allow: `Bash(scripts/change-workflow gather *)` and
      `Bash(scripts/change-workflow evidence *)`;
    - review, triage, merge, closeout, and archive cleanup allow:
      `Bash(scripts/change-workflow evidence *)`;
    - restore the four deny lines `57b7baaad` commented out: `Edit(.claude/**)`,
      `Write(.claude/**)`, `Edit(.agents/workflow.toml)`, and
      `Write(.agents/workflow.toml)`. Until they are back,
      `test_no_step_may_edit_the_configuration` and
      `test_no_step_may_edit_its_own_permissions` fail in every `make test`.
    No grant names a removed subcommand: `run *` stays for the hooks. The session
    making section 4 updates `test_change_workflow_steps.py` to assert the new
    grants.
  - Done: the orchestrator committed the edit as `323db78be`, on the owner's word
    (log seq 42), before this session. It restored the `.claude/**` deny lines;
    those on `.agents/workflow.toml` stay lifted for this session.
  - `test_change_workflow_steps.py`, unit tests over the step table, passes but for
    `test_no_step_may_edit_the_configuration`. That test fails until the
    orchestrator restores the configuration's deny lines after this session. New
    tests:
    - `test_validation_gathers_and_the_steps_reading_a_validation_read_the_evidence`;
    - `test_no_rule_names_validation_through_run_or_config`.
    Validation's row in `HOOK_COMMANDS` names no `run` form.
  - The assumptions test passes.
- [x] 4.6 Move `change-validate` and `change-orchestrate` to the new commands only —
  `evidence` in place of `config parts`, `gather` and `gather --kind` in place of
  `run validation`, evidence paths in place of `.snapshot/validation/` — leaving
  their repository material for section 7. Verify: `make check-agent-skills` and
  the assumptions test pass, and a search of `.agents/skills/` finds no `run
  validation` or `config parts`.
  - Done. `change-validate` changes:
    - step 1's plan is `evidence`;
    - steps 2 and 3's starts, runs, and collects are one `gather <change>`, run in
      the background and waited for on the harness's `[exited with code` line, since
      the gathering prints a closing line per kind and none last;
    - a rerun is `gather --kind`, and a lapsed waiver's kind `gather --kind …
      --lapsed`;
    - the paths are `.snapshot/evidence/`, and step 3 describes the pipeline's
      collect.
  - The record's `Parts:` line, the four kinds' material, and the guides stay for
    section 7 (7.2). `change-orchestrate`'s waiver note says the decision names
    evidence kinds and that the gathering skips them; its example's wording is
    section 8's (8.3).
  - `make check-agent-skills` and the assumptions test pass. A search of
    `.agents/skills/` finds no `run validation` or `config parts`.
- [x] 4.7 Verification point: the suites above; `run pre-commit` passes; the live
  check of 4.4. End-to-end: none.
  - Correction: checked though `run pre-commit` does not pass whole.
    - `after-functional-change` passed.
    - `pre-commit-functional` is now `make validate-local`. It fails only on
      `test_no_step_may_edit_the_configuration`, from the configuration's deny lines
      lifted for this session; every other suite passed. So the `local` evidence it
      leaves for this commit's tree says `FAILED`, naming that test, until a later
      functional commit runs it with the deny restored.
    - `pre-commit` passed once a history-wording hit in a docstring this section
      added was fixed.
  - End-to-end: none — confirmed; no scenario under `e2e-tests/` exercises the
    workflow's tooling.
  - Outside the plan: `scripts/tests/test_change_clone.py`'s `_waited` raised
    `ChildProcessError` once, inside the full suite run by `validate-local`.
    - The bootstrap's spawn drops its `Popen` object, and Python's `subprocess`
      reaps a dropped child that has ended as the next `Popen` starts. So
      `os.waitpid` can find the child already gone, a timing-dependent failure.
    - `_waited` now takes that as the child having ended. The file passes, 80
      tests.
  - Outside the plan: `evidence.worktree_tree` (2.1) gave a stale tree.
    - It copied the checkout's index with `shutil.copyfile`, dating the copy now.
      Git rereads a file rewritten at the same size in the second the index was
      written only by comparing the file's time with the index's own. So a copy
      dated later passed such a change over, and the tree was `HEAD`'s.
    - Seen once: `test_a_worktree_that_is_not_heads_is_refused` did not raise inside
      `validate-local`'s full suite.
    - Both copies, the engine's and `validate_slice.py`'s, now use `shutil.copy2`,
      which keeps the index's time.
    - Fixed with a test in each suite,
      `test_a_change_in_the_second_the_index_was_written_changes_the_tree`. It is
      library integration on a real repository, and fails with `copyfile` and
      passes with `copy2`.
  - The fresh-context check's findings fixed:
    - comments still saying a part describes the commit;
    - design-decision numbers in a test docstring;
    - a test named for removed subcommands;
    - a skill sentence contradicting the pipeline collect's exit status;
    - "part" beside "kind" in edited sentences;
    - `main`'s reader run in the root it was given.
  - Its finding of two tree computations: a test holding them to one answer imported
    the engine, which the command boundary's test refuses, so it was removed. Each
    is held to Git's answer instead (4.1).
  - Declined from the fresh-context check:
    - Renaming `TREE` and `COMMIT` to prefixed names: the plan and D6 name them, and
      no Makefile or script reads either otherwise. Command-line make variables do
      reach the nested makes and tests, and a `COMMIT` in the owner's environment
      would put `make fetch-e2e-logs` in evidence mode. Section 7's guides may say
      so.
    - `--event workflow_dispatch` for the pipeline's collect: the target never
      passed it, `e2e.yml` runs only on schedule and dispatch, and the task keeps
      the collect as it was.
  - Handoff to section 5:
    - `gather` is what the wrapper's built-in action before `validate` runs.
    - `change-validate` still runs it itself (step 2) until then; section 7 rewrites
      that step to read what the gathering before the session left.
    - A pipeline attempt whose fetch found no run is present evidence, failed, so
      the gathering never retries it. Only `gather --kind pipeline` makes a new
      attempt, which dispatches a new run. Section 7's pipeline guide should say so.
    - `make validate-local`'s summary names `HEAD` as `commit` even when it ran
      before the commit it describes. The tree is the identity.

## 5. Actions and hooks around steps

Delivers the engine's table of actions before and after each step, the built-in
gathering before validate and cleanup before archive cleanup, the repository's step
hooks with their failure rules, the inputs directory, and `run before|after` (D7,
D8; CW-g6th, CW-ikmm, CW-h3ks, CW-b7fl, CW-a4fl, CW-i9np, CW-b2xr, CW-q5fy). Files:
`scripts/change_workflow/graph.py`, `wrapper.py`, `hooks.py`, `cli.py`,
`running.py`, `log.py`, `history.py`, `workflow.mk`,
`test_change_workflow_wrapper.py`, `test_change_workflow_hooks.py`,
`test_change_workflow_cli.py`, `test_change_workflow_graph.py`.

- [x] 5.1 Add, beside `HOOK_STEPS` in `graph.py`, the table of each step's actions
  before and after it, holding `gather` before `validate` and `run cleanup` before
  `archive-cleanup` (D7). Verify: a unit test of the table's entries.
  - Done: `graph.STEP_ACTIONS`, keyed by `(BEFORE|AFTER, step)`, each value a tuple
    of `HOOK_STEPS` names; `step_actions(when, step)` reads it.
  - Unit test `test_the_engine_gathers_before_validation_and_cleans_up_before_archive_cleanup`
    in `test_change_workflow_graph.py` passes. It also holds each action to the hook
    table's listing of its step.
- [x] 5.2 Give each run an inputs directory, `reviews/runs/<run>/before/` and
  `…/after/`, named on its log line; write `status.md` with each action's or hook's
  closing line, exit status, and log path; keep each hook's printed output as a log;
  pass it as `{inputs}` (CW-i9np; CW-q5fy). `history` copies it (CW-hak6). Verify:
  library-integration tests for the layout, the log line's field, and CW-i9np's
  large-artifact scenario's layout.
  - Done in a new module, `scripts/change_workflow/around.py`, which the wrapper,
    the CLI, and (section 6) the review runner share:
    - `<run>` is `<UTC start>-<step>`, claimed by an exclusive `mkdir`, so a second
      run in one second takes `-2` (`claim_inputs`). The line's `inputs` names it
      relative to `reviews/`.
    - Each action or hook's output, its own and every program's it ran, goes to
      `<name>.log` through `output_to`, which points file descriptors 1 and 2 and
      `sys.stdout`/`sys.stderr` at the log. The wrapper's standard output carries
      only the line a caller parses, so nothing an action prints may reach it.
    - `status.md` holds, per action or hook, its exit status, its log, and the
      engine's lines from the log: those starting `[change-workflow]` or `ERROR:`.
      An absent or empty hook is "Not declared; nothing ran." or "Declared empty;
      nothing ran.", with no log.
    - What an action or hook ran is kept under a session id the engine makes for
      it, then taken onto the run's line, so whatever an action keeps through the
      engine lands there, the push's `pre-push` among it (by construction; no test
      pushes from the wrapper's gathering), and nothing lands under the session of
      whoever started the wrapper (an orchestrating session's, say).
    - `gather.main` takes the keep directory (`invocations`), so `around` calls it
      rather than composing a gathering of its own.
    - `history` already copies all of `reviews/`, so no code changed for it.
  - Library-integration tests, all passing:
    - in a new `scripts/tests/test_change_workflow_around.py`: the layout, the line's
      field, and the prompt
      (`test_a_runs_inputs_are_named_on_its_line_and_hold_what_each_hook_printed`);
      CW-i9np's large artifact as its layout, a 3 MB file beside `message.md`, in
      neither the prompt nor `status.md`
      (`test_a_hook_passes_a_large_artifact_beside_its_message`); a unit test of
      the claim;
    - in `test_change_history.py`: `test_a_runs_inputs_directory_is_copied_with_the_records`.
- [x] 5.3 The wrapper runs the built-in action, then `before-<step>`, before the
  session, a review's and triage's hooks given `{kind}`; an absent or empty hook runs
  nothing and the run says so; a failing action or hook never prevents the session,
  its failure in `status.md` and the session's prompt naming the directory; a hook
  the check refuses refuses the step (D7, D8; CW-g6th, CW-h3ks, CW-b7fl). Verify:
  library-integration tests with the harness doubled for CW-g6th's failing-local
  scenario, CW-b7fl's scenario, and CW-h3ks's absent-hook scenario.
  - Done in `wrapper.py`:
    - The directory is claimed, and the actions run, inside the run's held-signal
      block, so a stop given meanwhile ends the run as its session would start.
    - The prompt names `reviews/runs/<run>/before`, labelled as the target note is,
      after the skill's invocation and anything given to it. Every run's prompt now
      ends with it, so the tests asserting a prompt use `prompted` (fixtures).
    - Nothing runs before a resumed run's session: it read its inputs as it
      started. A resumed run still claims a directory, for what runs after it.
    - A triage's `{kind}` is the next-step computation's (`triage_kind`, a seam on
      the wrapper); a hook naming `{kind}` when it names none fails as a command
      lacking a value does.
    - A step hook runs through `Hooks.engine_hook`, held to no step's listing; the
      actions run marked as the step's run, so the hook table still holds them.
    - `gather` now says, for each kind present, that it skipped it and which match
      is current, so the gathering's `status.md` names every kind.
    - What the actions and hooks ran is on `invoked`, before and after what the
      session invoked. A skipped hook is not, since it ran nothing.
  - Library-integration tests in `test_change_workflow_around.py`, the harness
    doubled by `FakeClaude`, each hook a real `sh` command, all passing. Each
    scenario's test covers the engine's half: the session starts with the failure
    in its inputs. What the skill then does — diagnose, stop and ask, or say the
    hook was absent, as the orchestrating session does — is section 8's text, and no
    test with the harness doubled can show it.
    - CW-g6th's failing-local scenario on a real Git repository
      (`test_the_local_suite_fails_during_gathering`), and present evidence left
      alone before the session;
    - CW-b7fl's (`test_an_environment_refresh_fails_before_implementation`);
    - CW-h3ks's absent hook, shown for design and plan, and an empty one
      (`test_no_hook_is_declared_before_a_step`); the review's own is section 6's;
    - CW-ikmm's cleanup before archive cleanup's session
      (`test_archive_cleanup_starts_after_every_kinds_cleanup`);
    - a hook the check refuses, refusing the step before anything runs or is logged;
    - a triage's hook given `{kind}`, the kind seam doubled; `triage_kind` itself by
      a unit test in `test_change_workflow_wrapper.py`;
    - nothing run before a resumed session.
  - Not exercised by a test: a stop given while the actions run, and a hook naming
    `{kind}` when the computation names none.
  - `test_change_workflow_hooks.py`'s CW-q5fy Helm scenario now reads the kind the
    wrapper's own gathering ran, which no longer needs the session to gather it.
- [x] 5.4 After a `finished` outcome and before it is logged as final, the wrapper
  runs `after-<step>`; on failure it resumes the same session once with the
  failure; a second failure ends the run as a question naming the hook, with one
  final outcome logged (CW-a4fl). Verify: library-integration tests for CW-a4fl's
  implementation scenario and the second failure becoming a question.
  - Done: `Wrapper._after_finished`. The resumed turn runs on the session's model,
    into the same transcript, with the same target for a validation.
    - Its first outcome is kept as `earlier`.
    - A turn that ends other than finished is logged as it ended, the hook not run
      again.
    - The after directory is found where the change's records are once the session
      ends, since closeout archives the change it runs for.
    - A second run of a hook writes `<name>-2.log`, and `status.md` gains its
      section.
    - An action or hook the engine cannot run at all counts as a failure, written
      to `status.md` in its place (`Wrapper._moment`).
  - Library-integration tests, all passing:
    - CW-a4fl's implementation scenario, its fix a file the doubled session's resumed
      turn writes (`test_a_hook_after_implementation_finds_a_lint_failure`), the
      resumed turn on the session and model the first ran;
    - the second failure as a question;
    - a resumed turn that asks, logged as it asked;
    - what the engine cannot run after a session counted as a failure;
    - no after-hook after a question;
    - a validation's target kept through the resumed turn.
  - Not exercised by a test: the after directory found once closeout has archived
    the change.
- [x] 5.5 Add `run before|after <step> <change>` for interactive runs, held to its
  step (CW-h3ks; CW-u4pc). Verify: library-integration tests running it for
  implement and refusing it for another step's marker.
  - Done: `around.interactive`, reached through `run`'s `before`/`after` choices,
    which take the step, then the change.
    - Within a session the directory is `reviews/runs/session-<session>-<step>/`,
      so `run after` finds it again, and `record` names it as the line's `inputs`.
      Outside one, a new directory is claimed. What ran is kept for the session's
      line.
    - A marker naming another step refuses it; `run before review` runs nothing
      and says that a review run interactively is no run.
  - Library-integration tests through `cli.main`, all passing: implement's before,
    after, and `record` naming the directory and taking what ran; the refusal for
    another step's marker; the interactive review; and the usage errors. A unit
    test refuses a session id that would name another directory.
- [x] 5.6 Document each step hook as a commented target in `workflow.mk`, with no
  default (D8). Verify: the fragment's comments name every `before-`/`after-` hook,
  it defines no new target, and the assumptions test passes.
  - Done: a comment block ends the fragment, one `# <hook>:` line per step hook.
  - `test_the_fragment_documents_every_step_hook_and_defines_none` passes. It checks
    the comment lines and that a real `make` finds no `before-implement` target.
    The assumptions test passes: its collector reads `make <word>` in the fragment
    as a target named, so the comment names none.
- [x] 5.7 Verification point: the suites above; `run pre-commit` passes.
  End-to-end: none.
  - `run pre-commit` passed whole: `after-functional-change`, `pre-commit-functional`
    (`make validate-local`, every suite, the scripts' 3291 passing, its `local`
    evidence `PASSED` for the worktree's tree), and `pre-commit` with the
    repository's checks. The step-table tests pass again, the configuration's deny
    lines being restored.
    - An earlier run failed its `tree after` step because the worktree was edited
      while it ran, every suite passing; and on the comment check, a test spelling
      the task list's file name, now `next_step.TASKS_FILE`.
    - This note, written after the run, changes the tree it checked, so validation
      gathers `local` for the commit.
  - `run test-before` on `test_change_workflow_around.py` fails at `HEAD` before the
    section as it is collected, since `around` is new.
  - End-to-end: none — confirmed; no scenario under `e2e-tests/` exercises the
    workflow's tooling.
  - The fresh-context check's findings, fixed:
    - design-decision numbers in two test docstrings, now requirement ids;
    - the gathering composed again in `around`, now `gather.main` given the keep
      directory;
    - two guards with no test, now tested;
    - a test module's docstring overstating what it doubles;
    - notes naming whole scenarios where the tests show the engine's half, and
      claims no test exercised, now said so.
  - Declined from the fresh-context check: the triage-only `{kind}` rule stated in
    both the wrapper and the CLI, and the CLI borrowing the wrapper's seams for
    `run before|after`. Each caller reads the kind its own way: the wrapper as a
    run starts, the CLI for a session already open. The wrapper's seams are the
    command's one set of them, so a second set would only duplicate it.
  - Handoff to section 6:
    - `around.Around(...).before(directory)` and `.after(directory)` are what the
      review runner calls.
    - `claim_inputs(reviews, "review", clock)` names its directory.
    - `run before|after review` already says that an interactive review runs no
      hooks (5.5).
    - The question a second after-hook failure ends in is `around.after_question`,
      worded for a resumed session; a review's, which resumes nothing, needs its own
      wording.

## 6. A review's hooks

Delivers the review runner's `before-review` and `after-review`, and no hooks for an
interactive review (D7; CW-h3ks, CW-a4fl). Files: `scripts/change_workflow/review.py`,
`scripts/tests/test_change_workflow_review.py`.

- [x] 6.1 `review.py` runs `before-review` with `{kind}` before starting the
  reviewer, giving it the run's inputs directory to read, and `after-review` once
  it has published the record and before it logs the outcome as final (CW-h3ks).
  Verify: library-integration tests with the reviewer doubled: the reviewer's prompt
  names the directory, and `after-review` sees the published record.
  - Done:
    - `_review_and_log` claims the run's directory, named on every line however the
      run ends, and builds one `ReviewHooks`, an `Around` for the review with the
      review's base or the landing branch, and `{kind}`.
    - `run_review` runs its before moment once every guard has passed, just before
      the reviewer starts. It names the directory at the end of the reviewer's first
      prompt; a format correction's prompt does not name it.
    - `_review_and_log` runs the after moment once the record is published, before
      the line.
    - The line's `invoked` is what ran before, the reviewer's own, then what ran
      after.
    - The CLI now passes its environment to the review, so the review's hooks run in
      it as every other step's do.
    - A review the configuration cannot be read for has no hooks, and `run_review`
      refuses it as before.
  - Library-integration tests in `test_change_workflow_review.py`, the reviewer
    doubled by the Codex writer, each hook a real `sh` command, all passing:
    - `test_a_reviews_hooks_run_around_its_reviewer`: the prompt names the directory,
      the hook gets `{kind}`, and `after-review` copies the published record;
    - CW-h3ks's scenario, the engine's half (`test_no_hook_is_declared_before_a_review`);
      the orchestrating session's sentence is section 8's;
    - a failing `before-review` prevents nothing;
    - a review its guard refuses runs no hook;
    - the hooks run in the environment given.
  - The prompt and line assertions of four existing review tests now include the
    inputs.
- [x] 6.2 A failing `after-review` resumes no reviewer and ends the run as a question
  naming the hook, the record standing and never published again; an interactive
  review runs no hooks and says so (CW-a4fl; CW-h3ks). Verify: CW-a4fl's review
  scenario as a library-integration test, and a test that no second record is
  claimed.
  - Done: `after_review_question`, its wording beside `around.after_question`
    through `around.hook_question`.
    - An interactive review's `run before|after review` (5.5) says it runs no hooks
      and makes no directory.
  - Outside the plan: the next-step computation named `resume` for any step's
    question, and `resume` refuses a review line. So a review's question named a
    step no command takes. `next_step._waiting` now names no `resume` for a
    review's question, and the owner settles it by their direction. Section 8.3's
    orchestrating skill should relay it so.
    - Test: `test_a_reviews_question_names_no_resume` in `test_change_next_step.py`.
  - Library-integration tests, all passing:
    - CW-a4fl's review scenario (`test_a_hook_after_a_review_fails`): one reviewer
      call, the line a question naming the hook and the record, the record kept,
      no `02-` file anywhere under `reviews/`, and one line logged;
    - the interactive review, for `before` and `after`, in
      `test_change_workflow_around.py`.
- [x] 6.3 Verification point: `test_change_workflow_review.py`; `run pre-commit`
  passes. End-to-end: none.
  - `run test-before` on `test_change_workflow_review.py` at section 5's commit
    fails on its assertions: the four updated tests and the four new ones then
    present. The section's later tests came after it ran.
  - Outside the plan, a defect in section 5's actions, fixed:
    - A hook's commands run in the process's environment
      (`hooks.command_environment`), not the one the hook runner is given. So the
      marker and the engine's own session id `around` made never reached them, and
      an engine command a hook ran would have been kept under the session of
      whoever started the wrapper.
    - `around.environment` now makes the action's environment the process's own
      while it runs.
    - Test: `test_a_hooks_commands_run_as_the_steps_run_never_under_the_callers_session`.
  - The fresh-context check's findings, fixed:
    - two docstrings still naming only `finished` and `stopped`;
    - the review's `Around` composed twice, now one `ReviewHooks`;
    - the `environ` the CLI never passed;
    - a guard on a list no caller left out;
    - the absent-hook scenario untested;
    - the two questions' shared wording.
  - The check's plausible finding, a review's question naming a resume no command
    takes, is fixed as 6.2 says.
  - `run pre-commit` passed whole: `after-functional-change`, `pre-commit-functional`
    (`make validate-local`, every suite, the scripts' 3300 passing, its `local`
    evidence `PASSED`), and `pre-commit`. `test_change_workflow_review.py`: 108
    passed.
    - An earlier run failed only on the comment check, which reads a literal review
      record's name as a reference. The tests now build it from the kind.
    - This note changes the tree that run checked, as 5.7's did.
  - End-to-end: none — confirmed; no scenario under `e2e-tests/` exercises the
    workflow's tooling.
  - Handoff to section 7 and on:
    - Every run's prompt now ends with its inputs note, and every line names
      `inputs`. Section 7's `change-validate` reads the gathering's
      `before/status.md` there instead of running `gather` itself, which the wrapper
      has done since section 5. Until then the skill's own `gather` finds
      everything present and gathers nothing.
    - Section 8.3: a review's question after a failing `after-review` names no
      resume. The orchestrating session relays it for the owner's direction.
    - Section 8.4: `run before|after <step> <change>` prints the inputs directory as
      its last line, `[change-workflow] inputs: reviews/runs/…`.
  - The session has grown large over two sections. The next sections should start
    in a fresh session.

## 7. The guides and the validation skills

Delivers the four guides in full and `change-validate`, `change-archive-cleanup`, and
`change-merge` rewritten around evidence kinds with no repository material (D1, D4,
D6, D10, D14; CW-a8ss, CW-k7gd, CW-g2rs, CW-c5nt, CW-i9np, CW-n8tr). Files:
`.agents/evidence/*.md`, `.agents/skills/change-validate/SKILL.md`,
`change-archive-cleanup/SKILL.md`, `change-merge/SKILL.md`.

- [x] 7.1 Write the guides from what leaves the skills, restating nothing the
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
  - Done: each guide has the headings CW-k7gd asks of one — what the kind shows,
    reading its evidence, telling its failures apart, its section of the record, its
    cleanup, and what a plan names for it.
    - `helm.md` carries what left `change-validate` (the preflights, the namespace
      evidence, the memory and capacity classification, the warnings, the
      every-scenario judgement), `change-archive-cleanup`, and `change-merge` (the
      capacity figure, committed alone, a conflict keeping the later `measured_at`).
    - `pipeline.md` carries the collect, the no-run attempt that only a new attempt
      replaces (4.7's handoff), the lanes, and the scenarios as pytest markers under
      `e2e-tests/`, with the Helm kind's served list.
    - `ci.md` carries the dispatchable list, the baseline's classes, the owed job's
      judgement, the kind's result rule, and the owed-line example, now in the
      `(ci tests.yml)` form.
    - `local.md` carries its steps as the script names them, the attempt naming, the
      worktree messages, and why an attempt's `commit` may not be the validated one.
  - `scripts/change-workflow config` reads the file with the whole check, the
    guides' among it, and passes (`check config` is outside implementation's rules,
    as in 1.8). A reading against each entry: no guide names its kind's command,
    pattern, requirement, `after`, or cleanup commands. Each says what its cleanup
    does and writes, which CW-k7gd asks of it, and the attempt directory's name,
    which is the scripts' convention, not the configuration's.
- [x] 7.2 Rewrite `change-validate`: the gathering already ran before the session
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
  - Done: a new "The run's inputs" section, before step 1, reads `status.md` and the
    hook's messages, runs `run before|after validate` interactively, and carries the
    contradiction notice (8.4's opening, written here for this skill).
    - Step 2 reads what the gathering found; `gather --kind` is now only a new
      attempt, for unreadable evidence, a lapsed waiver, or an environmental failure
      the owner allowed.
    - Step 3 assesses each kind as present and passed, present and failed,
      unreadable, or missing, with its source.
    - The record adds `Tree:` (which `history` reads) and `Evidence:` in place of
      `Parts:`, a section per kind as its guide lays it out with its current and
      earlier attempts' paths, and `Kind:` in place of `Part:` in a failure.
    - A waiver's last assessment is read from `Evidence:`, or an older record's
      `Parts:`.
    - An after-hook's failure is explained in the resumed turn, validation acting on
      nothing (D7).
  - `make check-agent-skills` passes. The inverted test is section 9's; until then,
    a scratch run of its collection over this skill finds only the outcome schema,
    the make fragment's targets, and `scripts/change-workflow`.
- [x] 7.3 Rewrite `change-archive-cleanup` — the cleanups ran before the session; a
  tracked file one wrote is committed alone as its guide says; the pull request draft
  names the evidence the record names — and `change-merge` — a file a cleanup writes
  resolved as its guide says; the scenarios as the pipeline guide names them; no
  example remote (D7, D9; CW-ikmm, CW-k7gd). Verify: as 7.2.
  - Done:
    - `change-archive-cleanup`: step 7 reads the cleanup's closing line from
      `status.md`, naming `run cleanup` only to rerun a failure; step 8 commits a file
      as its kind's guide describes it; step 6's draft names the record's commit,
      tree, and each kind's evidence; no example remote; the public-content rule by
      its engineering guidance, in the case the root guidance selects.
    - `change-merge`: a tracked file a cleanup writes resolved as its kind's guide
      says, before closeout and after the archive; the scenarios found as the guide
      of the kind running them says; no example remote and no lock file's name; step
      2 reads the evidence guides.
    - Both gain "The run's inputs", as 7.2.
  - As 7.2: the skills check passes. The scratch collection finds, besides the
    workflow's own paths and the fragment's targets, only
    `docs/guidance/engineering/repository-content.md` in `change-archive-cleanup`,
    the engineering guidance section 9's test admits (9.1).
  - Outside the plan, a defect the engine's cleanup before the session made in
    `change-archive-cleanup`, fixed: a tracked file the cleanup wrote was committed
    only at step 8, so step 1's Worktree check, step 4's pre-commit checks, step 5's
    guarded push, and a validation the Validated check sent for all met a dirty
    worktree. The Worktree check now commits each such file alone before anything
    else, a stop for validation commits it first, and the Validated check passes
    over such commits as it does ledgers and reviews (D2: the file changes a tree no
    evidence needs to describe).
- [x] 7.4 Verification point: the skills check and the inverted test for these three
  skills; `run pre-commit` passes. End-to-end: none.
  - `run pre-commit` passed whole: `after-functional-change`, `pre-commit-functional`
    (`make validate-local`: `dist-clean`, `check-packaging`, and `test`, every suite,
    passing), and `pre-commit` with the repository's checks. `make
    check-agent-skills` passes.
    - This note changes the tree that run checked, as 5.7's did.
  - The inverted test does not exist until section 9, so it is not run here; the
    scratch run of its collection stands in (7.2, 7.3), and section 9's verification
    runs it over these skills.
  - End-to-end: none — confirmed; no scenario under `e2e-tests/` exercises the
    workflow's tooling.
  - The fresh-context check's findings, fixed:
    - `change-archive-cleanup`'s worktree ordering (7.3);
    - task 7.4 itself, dropped by an edit, restored;
    - the guides describing the printed summary line as `summary.json`'s, which
      `change-validate` step 3 would have read as every summary unreadable;
    - interactive `run before` placed before validation's and archive cleanup's own
      checks, though it pushes, gathers, and tears down;
    - `change-validate` step 8 pointing at report items no guide named, now named in
      the Helm, pipeline, and CI guides;
    - `volumes gone` classed environmental whatever its detail;
    - the Helm kind's storefront check pods and their warnings, missing, as in the
      old skill;
    - a failed preflight's closing line said to name what it reported, which only
      its log holds;
    - the Helm kind's wheelhouse clearing and the storefront environments' remedy,
      and the CI kind's "HEAD is now" stop, which had left the skills unplaced;
    - `ci.md` restating its requirement, `pipeline.md` restating its start order,
      and "part" in `local.md`.
  - Declined from the fresh-context check:
    - The uv preflight's detail: the preflight is no kind's, so no guide holds it;
      its log names both versions, and `docs/guidance/repository/locks.md` holds the
      minimum and its reason.
    - The refusal of a kept volume in `default`: only a Helm run without a change
      reaches it, which validation never makes.
    - `helm.md` describing what its cleanup removes as well as what it writes: archive
      cleanup reports a failed removal, and needs to know what it was.
    - `openspec/specs/change-workflow/README.md` still saying the validation skill
      keeps the Helm material: closeout's promotion (10.9) rewrites that section.
  - Handoff to section 8:
    - Each step skill's opening gains "The run's inputs", as `change-validate`,
      `change-archive-cleanup`, and `change-merge` now have it: the actions and hook
      before the session, `status.md` and the messages read first, what a failure
      means for the step, `run before|after` interactively, and the contradiction
      notice.
    - The guides now hold what `change-plan`, `change-implement`, and
      `change-orchestrate` still say of scenarios, the dispatchable list, and the
      owed-line example; section 8 points those skills at the guides.

## 8. Neutral skills

Delivers every other workflow skill free of repository material, reading its inputs
directory and naming contradictions (D9, D12, D13, D14, D10; CW-n8tr, CW-i9np,
CW-c5nt, CW-k7gd, CW-5h8e). Files: `.agents/skills/change-plan/`, `change-implement/`,
`change-orchestrate/`, `change-closeout/`, `change-review/`, `change-design/`,
`change-triage/`, `guidance-review/` `SKILL.md`.

- [x] 8.1 `change-closeout`: the repository's own parts "in the section the root
  guidance names", not restated; "the repository's comment check"; `scripts/
  change-workflow check tasks`; no `ARCHITECTURE.toml` (D9). `change-review` and
  `change-plan` name the repository's own closeout parts by role. Verify: the
  inverted test reports nothing for these skills.
  - Done: closeout's step 3 replaces its two restated parts with one, "The
    repository's own parts", run as their section says, `run pre-archive` where a
    part calls for it, and evidence a part records read with its kind's guide. The
    roadmap, the placement table, the cross-system documents, and the capability
    index are named by role. Review and plan name the closeout parts by role.
  - `change-review` also loses `AGENTS.md`, `ARCHITECTURE.md`, `openspec/README.md`,
    and the market's core, kit, and domain from its documentation and architecture
    lenses, the design and merge reviews' included, and its `guidance` basis, now the
    documents `config load review` prints and the repository's architecture
    document.
  - The inverted test is section 9's (9.2 runs it over these skills). The scratch
    collection finds in the three only the workflow's own paths, the engineering
    guidance, and the fragment's targets; a reading found the package layers in
    prose besides (`change-plan`'s ordering, `change-review`'s lenses), fixed after
    the fresh-context check.
- [x] 8.2 `change-plan`: owed lines `Owed by validation (<kind> <argument>):`, the
  kinds and their guides learned from `config --json`, scenarios as the guide of the
  kind that runs them says, no `scripts/ci_evidence.py` or `openspec/config.yaml`
  path (D5, D14; CW-5h8e, CW-d1nj). `change-implement`: scenarios likewise, its
  command forms kept under the exemption owned by `sandbox-unattended-workflow-steps`
  (D9). `change-design`: the roadmap through `load.design`. `change-triage`: its
  worked example rewritten neutrally. Verify: as 8.1.
  - Done:
    - `change-plan` loads the kinds from `config --json` and their guides; its owed
      line is `Owed by validation (<kind> <argument>):` with the argument's rule, what
      may be owed the kind's guide's; the task rules come with OpenSpec's
      `instructions` output, which carries the configuration's `rules`.
    - `change-implement`: scenarios and owed lines likewise; the repository's
      dependency layers and internal dependencies by role; `make -C helm
      test-render` gone from its Git bullet, `make -C <package> test` and `make -C
      <package> migrate` kept for the exemption.
    - `change-design`: the roadmap `config load design` names.
    - `change-triage`: the worked example a refund scenario, its edit line included,
      no stage or pipeline; the default-acceptance examples' roadmap heading
      invented; its Git bullet's Helm example gone; "gathers the evidence it lacks"
      for "dispatches the pipeline"; a validation diagnosis checked against its
      evidence as its kind's guide says, not "under `.snapshot/`"; "kind" for "part".
    - `change-design`: also the architecture document by role and "library" for
      "kit".
  - Verify, as 8.1: the scratch collection finds, in these four skills, only the
    workflow's own paths, the engineering guidance, the fragment's targets, and
    implementation's exempt command forms.
- [x] 8.3 `change-orchestrate`: "a value of the owner's machine reaches a command
  through the environment" for `HELM_ALL_SCENARIOS`; its waiver example by kinds in
  general; one sentence per skipped hook; a second after-hook failure's question
  relayed without judging it (D13; CW-h3ks, CW-yvo1). Verify: as 8.1.
  - Done. Besides the plan's four:
    - `HELM_ALL_SCENARIOS` is not named, since the make fragment passes no such
      variable;
    - a review's question after a failing `after-review` names no resume, and the
      owner's word is their direction (6.2's handoff);
    - the owner's handbook by role.
  - Verify, as 8.1: the scratch collection finds only the workflow's own paths, the
    step table, and the fragment's targets.
- [x] 8.4 Every skill's opening, beside "Running unattended", reads its run's inputs
  directory — `status.md` and every top-level Markdown message in full, other files
  where a message directs — and names a contradiction it notices between a guide or
  message and its own text, following its own text; interactively it runs `run
  before <step> <change>` first and `run after` before recording (CW-i9np, CW-c5nt,
  CW-h3ks). `change-review` reads the evidence guides wherever it reads a validation
  record, and the inputs directories of the runs it reviews (D12; CW-k7gd).
  Verify: a reading of each skill's opening; `make check-agent-skills` passes.
  - Done: "The run's inputs" follows "Running interactively" in each of the nine
    step skills, saying what a failing before-hook means for that step:
    - implementation stops and asks (CW-b7fl's scenario);
    - validation diagnoses the gathering's failures, and archive cleanup reports the
      cleanup's;
    - planning, which asks nothing, stops;
    - every other step says what the failure means and asks when it cannot go on.
    It also says how an after-hook's failure resumes the session.
  - `change-review`'s says the runner names the directory last in its first prompt,
    that a failing `after-review` goes to the owner, and that an interactive review
    has no inputs and runs no hooks. Its load step reads the evidence guides with a
    validation record and every reviewed run's inputs, from each line's `inputs`.
  - `change-orchestrate` and `guidance-review` are no steps and have no inputs; the
    guidance review loses `AGENTS.md`, naming the public case and the terms' home by
    the root guidance.
  - A reading of each opening; `make check-agent-skills` passes.
- [x] 8.5 Verification point: the skills check and the inverted test; `run
  pre-commit` passes. End-to-end: none.
  - `run pre-commit` passed whole: `after-functional-change`, `pre-commit-functional`
    (`make validate-local`, every suite passing), and `pre-commit`. `make
    check-agent-skills` passes. This note changes the tree that run checked.
  - The inverted test is section 9's, which runs it over every skill (9.2).
  - End-to-end: none — confirmed.
  - The fresh-context check's findings, fixed:
    - `change-triage`'s worked example still naming stage 07c in its edit line, its
      `.snapshot/` path, and "part";
    - the package layers (kit, domain, composition root) and `ARCHITECTURE.md` in
      `change-plan`, `change-review`'s design and merge lenses, and `change-design`;
    - `change-closeout` sending an evidence part to "the command it runs", which
      for this repository's end-to-end part is a dispatch closeout may not make: it
      now takes such evidence from the latest passing validation record, whatever
      command the part names;
    - `change-review`'s inputs bullet splitting its validation bullet;
    - the 8.1 and 8.2 notes' overstatements.
  - Declined from the fresh-context check, deferred:
    - `dev` and `origin` named as the landing branch and its remote in procedures
      the plan did not list — `change-design`'s prerequisite proposal, `change-implement`'s
      merge resolution, `change-orchestrate`'s merges and pull request,
      `guidance-review`'s proposal branch. They are no target or path, which
      CW-n8tr's test reads; naming them by role means rewriting those procedures,
      left to closeout's campaign index currency (10.6) to record as a gap of the
      lesser goal, or to `extract-change-workflow-repository`.
    - `change-implement`'s `docker compose -p <change>-local …` with no matching
      step-table rule: the step table and its command forms are
      `sandbox-unattended-workflow-steps`'s.
  - Handoff to section 9: the skills name, outside the workflow's own paths, only
    the engineering guidance (`docs/guidance/engineering/`), the outcome schema, the
    step table and `.claude/`, the engine's package (`scripts/change_workflow/`, in
    `change-orchestrate`), and implementation's `make -C <package> test` and
    `make -C <package> migrate`.

## 9. The skills' neutrality test

Delivers CW-m4ps's test inverted for skills, with the exemption list (D9; CW-n8tr,
CW-m4ps, MCW-5tgp). Files: `scripts/tests/test_change_workflow_assumptions.py`, and
`openspec/specs/market-change-workflow/README.md`'s "How this repository provides
the workflow's roles" only where the test reads it.

- [x] 9.1 Invert the test for skills: a make target or repository path a skill names
  is the workflow's own — `docs/guidance/workflow/`, OpenSpec's tree, the change
  index, the make fragment's targets, `scripts/change-workflow` — or in an exemption
  list naming `sandbox-unattended-workflow-steps` as its owner (implementation's
  command forms), or the test fails naming the target and the skill (CW-n8tr,
  CW-m4ps's skill scenario). The step table and the make fragment stay held to this
  repository's statement (MCW-5tgp). Verify: the test passes on the skills as
  sections 7 and 8 left them, and a fixture skill naming `make
  check-comment-hygiene` fails it.
  - Done in `scripts/tests/test_change_workflow_assumptions.py`:
    - `skill_names` collects the skills apart from `collected`, which now reads the
      step table and the fragment alone, still held to this repository's statement
      and configuration.
    - `not_the_workflows` refuses every skill name that is neither the workflow's
      own (`workflows_own`) nor exempted, naming the skills. The workflow's own is:
      - a target the fragment defines, run here or in a checkout `-C` names by a
        placeholder (`make -C <clone> implement`), never in one of the repository's
        directories;
      - `scripts/change-workflow`, `scripts/change_workflow/`, and the outcome schema;
      - the guidance directories `docs/guidance/workflow/` and
        `docs/guidance/engineering/`, and a Markdown file beneath `docs/guidance/`
        whose frontmatter tags it `workflow` or `engineering` (CW-n6dm: the
        frontmatter states a file's layer, wherever it sits);
      - OpenSpec's two trees as the workflow knows them: `openspec/changes/` and
        `openspec/specs/`, the change index, the archive, the guidance reviews'
        ledger in it, and a change or capability named by a placeholder. One named
        by its name is refused, as are the capability index and `openspec/README.md`.
    - The exemptions are a table, "What the workflow's skills name of this
      repository", added to `openspec/specs/market-change-workflow/README.md` and
      read by `exemptions`. It holds four names, each owned by
      `sandbox-unattended-workflow-steps`:
      - `make -C <package> test` and `make -C <package> migrate`;
      - the step table, `.claude/change-steps.toml`, and `.claude/`.
      The table is in a document because the repository's comment check refuses a
      change's name in a test.
  - Differing from the plan's list, the workflow's own also covers the engineering
    guidance, the engine's package, and the outcome schema. CW-n8tr lists the
    workflow's guidance, OpenSpec's tree, the change index, the fragment's targets,
    and the engine's command:
    - The engineering guidance is the layer below the workflow's, which the workflow's
      guidance links, so the workflow cannot go without it. Eight skills cite it.
    - The package and the schema are the engine's own, both in the engine's
      assumptions table.
    This reading of "its guidance" and "the engine's command" is for the round's
    review and triage to confirm, or to return to design.
  - Unit tests on fixture skills, all passing:
    - `test_a_skill_naming_a_repositorys_check_is_named`, CW-n8tr's and CW-m4ps's
      scenarios: `make check-comment-hygiene`, which the statement's tables list,
      `make check-uv-version`, which only the configuration's commands name, and a
      new target, each refused, naming the skill;
    - `test_a_skill_may_name_the_workflows_own_targets_and_paths`;
    - `test_a_skill_naming_a_repositorys_paths_is_named`, a fragment target run in
      `helm` among them;
    - `test_an_exempted_name_is_admitted`, the table read from a fixture.
  - Two tests read this repository's skills and table, and both pass:
    - `test_every_target_and_path_a_skill_names_is_the_workflows_own`;
    - `test_every_exemption_is_named_by_a_skill_and_owned_by_an_open_change`, so an
      exemption goes once nothing names it or its owner is archived.
  - `test_every_target_and_path_the_step_table_and_the_fragment_name_is_provided_here`
    keeps MCW-5tgp's check for the step table and the fragment.
  - `run test-before` at the round's base, run before the exemptions moved to the
    table, failed on the skill test's assertion, not at collection. It named every
    repository target and path the skills then held, `AGENTS.md`,
    `openspec/README.md`, and `scripts/validate_slice.py` among them. Every other
    test passed there. Run again after the move, the two tests reading this
    repository fail at the base for the table's absence, before any skill is read;
    the first run is the one that shows the skills refused.
  - `market-change-workflow/README.md`'s provisions paragraph now says the test holds
    the step table and the fragment to its tables. Closeout's promotion (10.9) owes
    the rest:
    - that section's prose;
    - `change-workflow/README.md`'s description of the test and of what the skills
      keep.
- [x] 9.2 Verification point: `test_change_workflow_assumptions.py`; `run pre-commit`
  passes. End-to-end: none.
  - `test_change_workflow_assumptions.py`: 18 passed, its skill test reading every
    skill as sections 7 and 8 left them; this is the inverted test 7.2 to 8.5 refer
    to.
  - `run pre-commit` passed whole: `after-functional-change`, `pre-commit-functional`
    (`make validate-local`, every suite passing), and `pre-commit`.
    - An earlier run failed `pre-commit` on two checks: the comment check, which read
      the fixtures' change-document names and the owner check's `proposal.md` as
      change references, and the history-wording check, on "no longer" in a
      docstring. The fixtures now use other file names, the owner check reads the
      change's directory, and the docstring says what holds.
    - This note changes the tree that run checked.
  - End-to-end: none — confirmed.
  - The fresh-context check's findings, fixed:
    - the test spelling the exemptions' owner, a change's name, which the comment
      check refuses: the exemptions moved to the README table (9.1);
    - OpenSpec's trees admitting any change or capability by name and the capability
      index;
    - the step table and `.claude/` admitted as the workflow's own, though the
      allowlist they hold is the sandboxing change's to replace: now exemptions it
      owns;
    - a fragment target admitted in any `-C` directory, now only a placeholder
      checkout's;
    - a guidance file admitted by directory alone, now by its frontmatter's layer;
    - the exemption test pinning the owner set, and checking no owner was open;
    - the fixture test's claims beyond its assertions;
    - two comments describing the plan;
    - the 9.1 note's lists.
  - Declined from the fresh-context check: amending CW-n8tr's wording for the
    engineering guidance, the engine's package, and the outcome schema. The reading
    is recorded in 9.1 for the round's review and triage; a requirement's wording
    is design's.
  - Handoff to closeout: 10.9's promotion owes the rest of `market-change-workflow`'s
    "How this repository provides the workflow's roles" and `change-workflow`'s
    description of the test and of what the skills keep. 10.6's index currency may
    record, beside hooks for every node, the landing branch named `dev` and `origin`
    in skills (8.5).

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
