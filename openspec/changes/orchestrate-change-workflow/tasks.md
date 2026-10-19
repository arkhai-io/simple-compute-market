Sections are ordered by what each builds on: the outcome and the log every run
writes; the wrapper that runs a Claude Code step; reviews and the `make` targets
through the wrapper; the next-step computation; the leaf skills' unattended
reporting; the orchestrator; then, planned against the design revised after section
6, the ordered models, cost recording, advancing on conditions, and the skills'
touchpoints (6a–6d); the pilot; closeout. Every script is tested in
`scripts/tests/` with an injected command runner, at unit level, except where a
real Git repository is the lowest level that proves the behaviour. No end-to-end
scenario in `e2e-tests/` covers this change and none is owed: it is contributor
tooling that runs the pipeline, not behaviour the pipeline deploys. The pilot
(section 7) is its end-to-end evidence.

## 1. The outcome schema and the workflow log

Delivers the structured outcome every unattended run ends with and the log the
wrapper alone writes (D3; requirement "Unattended step runs end with a structured
outcome").

- [x] 1.1 Add the outcome schema, now `.agents/change-outcome.schema.json` (added
      under `scripts/`, moved at round 1, 02 O3): the five outcomes —
      `finished` (with `next`), `question` (with `awaiting`), `returned` (with
      `return_to` and `evidence`), `blocked` (with `blocked_on`), `stopped` (with
      `reason` and `denials`) — each carrying the step's `message`. D3's example
      lines validate against it; unit tests in
      `scripts/tests/test_run_change_step.py` check each outcome's required fields
      and reject an unknown outcome.
      Done. One object schema with `outcome` and `message` required and an
      `allOf` of `if`/`then` per outcome, not a top-level `oneOf`, since
      `--json-schema` hands Claude Code an object schema (a premise section 2's
      hand runs proved wrong for a top-level `allOf`; see 2.5); `additionalProperties`
      is false, so a step cannot set a field the wrapper records; `return_to` is
      one of `design`, `planning`, `implementation`; `next` is free text, since
      routing is `change_next_step.py`'s (D14), not the step's. The scripts run on
      the standard library, so `run_change_step.py` carries a small validator for
      exactly the keywords the schema uses and raises on any other, so a schema
      edit it cannot enforce fails loudly — an unknown keyword or `type`. The
      outcome parts of D3's example lines 13 and 20 conform (tested with their
      wording paraphrased, the wrapper's fields stripped); line 22, a
      wrapper-written `stopped`, shows no `message`, but `message` is
      required on every outcome and section 2's wrapper writes one on its own
      `stopped` lines, so every outcome line in the log conforms. Unit
      (`test_run_change_step.py`): each outcome valid; each required field,
      `message` included, missing from each outcome reported; unknown outcome,
      undefined field, and a `return_to` that is not earlier rejected; an
      unenforceable keyword or type raises.
- [x] 1.2 Add `scripts/run_change_step.py` with the log's writer and reader: append
      one line to the change's `reviews/workflow.jsonl` with `seq`, `at`, the step,
      its session and commit; read the last lines. Its `note` operation appends the
      orchestrator's `round` (D13) and `orchestrator` (D14) lines, so the wrapper is
      the log's only writer. The change's directory is found through
      `scripts/find_change.py`, so an archived change's log moves with it. Unit:
      `seq` increases across appends and notes, a malformed line is reported with
      its line number rather than skipped, and a note without its required fields
      is refused.
      Done. `record_outcome` validates and appends; `append_entry` holds an
      exclusive `flock` from reading the last `seq` to writing, because validation
      and review append side by side. A `round` line's `sections` lists the
      round's sessions, each a list of section ids (`1,2;3` on the command line);
      an id is an integer or a string, since plans name sections like `5B`; it
      requires `by`. An `orchestrator` line requires `decision` and `reason`. The
      command line has `note <change> round|orchestrator` and
      `log <change> [--last N]`. A reader takes a shared lock, so a line being
      appended is never read half-written; a last line saved without its newline
      is not joined to the next; a run's `extra` fields may not repeat its step,
      session, commit, or outcome fields, nor set `seq` or `at`. Unit: everything
      the task names, an archived change's log found by name included, plus a
      refused line leaves the log unwritten, an unknown step and repeated run
      fields are refused, a missing final newline, and the command line's note,
      log, and unknown-change paths.
- [x] 1.3 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`.
      `uv run --no-project --with pytest pytest -q
      scripts/tests/test_run_change_step.py` (unit): 54 passed; `scripts/` has no
      project, so `--no-project`, as `make test-release-tooling` runs it.
      `make test`: passed, including `scripts/tests` through
      `test-release-tooling`, before the fresh-context fixes, which touched only
      `run_change_step.py` and its test; the focused suite passed after them.
      `make check-packaging`, `make check-comment-hygiene`: passed. End-to-end:
      no scenario in `e2e-tests/` covers this section, as the plan's preamble
      says; it is contributor tooling.

Handoff. Section 2 builds on `record_outcome(path, step, outcome, session=,
commit=, extra=)`, `append_entry`, `read_log`, and `log_path`, and should write
its own `stopped` lines through `record_outcome` with a `message` (the reason),
so every outcome line conforms. `StepError` is the error `main` reports; section 2
adds `run` and `resume` subcommands to `main`. The module docstring describes only
the log; extend it as the wrapper grows. Its contract cites the delta's heading
"Unattended step runs end with a structured outcome", which reaches
`openspec/specs/change-workflow/spec.md` at archive.

Round 1 fixes (triage of records 02, 04, 07, and 24, at `82ca2c94`). 04 F3
(A+): `note_orchestrator` takes `by`, `resolves` (the `seq` of a step's run in
the log, refused otherwise), `next_step` (a known step), and `kind` (with
`next = review` only); the command line takes `--by`, `--resolves`, `--next`,
`--kind`. X1: `note_round` takes `after`, and `note round --after <N>`, for a
round recorded after the fact; a negative or non-integer `after` is refused. The
schema's `denials` is described as a field of any outcome. Unit
(`test_run_change_step.py`): a decision line with each field, each refusal, a
decision that may resolve only a step's run, the command line's new options, a
round given its `after`. The round line for sections 1–5 (`--sections 1,2,3,4,5
--after 1 --by owner`) is the orchestrator's to record after this commit; it was
not recorded here.

## 2. Running a Claude Code step through the wrapper

Delivers the headless run, its resume, its permissions, and its event stream (D1,
D6, D7; the wrapper side of D12 and 01 F5; requirements "Unattended step runs end
with a structured outcome" and "Unattended runs are held to their step's
permissions").

- [x] 2.1 Add the step table, now `.claude/change-steps.toml` (added under
      `scripts/`, moved at round 1, 02 O2), with D6's table: each step's skill and
      its allow and deny rules, including design's `git worktree add` from dev and
      edits under that worktree's `openspec/` (D5), and validation's guarded push
      as the only push.
      Done. A `[common]` row adds read-only Git, `find_change.py`, the log
      reader, `make round-view-closed`, and `make check-change-index` to every
      step, and denies `git push`, history rewrites, opening or closing the
      round view, and editing the step table or `.claude/`, the one
      settings source an unattended run loads, so no step widens its own or a
      later step's permissions; each `[steps.<step>]` row names its skill, and planning's names
      `resume_from = "design"` (D8). Beyond D6's table: closeout may edit
      `AGENTS.md`, since 8.9 promotes to it, and run `python3 scripts/check_*`;
      implementation and triage may also run `make dist*`, `make reinit*`,
      `uv sync*`, `make -C * test*`, and `uv run` only for pytest (a bare
      `uv run *` would run `git push` past the deny); triage denies
      `make run-e2e` as implementation does; validation may run
      `make check-push-ready` and `make dist-clean`, and denies `Edit`,
      `git add`, `docker push`, and `helm push`; design and planning deny every `git commit`, not only code's,
      since the owner commits design-phase work (D10). `docker *`, `kubectl *`,
      and `helm *` stay broad for validation, as D6 allows them, so D6's
      "editing tracked files" denial rests on `Edit` and the narrow `Write`
      alone: a container with a mount, or `make dist-clean`, is not ruled out.
      The subagent tool is `Task` and there is no `TodoWrite` in Claude Code
      2.1.300 (the hand run's `init` event lists the tools), so the table names
      `Task`. Unit: the table
      names each Claude Code step (review is Codex's); matching sample commands
      against each step's rules by glob, no step but validation is allowed
      `git push`, `uv run git push`, `make push-branch`, or `make run-e2e`;
      `docker push`, or `helm push`; every step may run `make round-view-closed`
      and none may open or close the view; no step may edit the table or
      `.claude/`; validation denies `make lock`, `git commit`, and `Edit`; a
      table with a row lacking a skill, an unknown key, step, or table, a rule
      list given as a string, or a `resume_from` naming no row is refused. The
      glob matching approximates Claude Code's rule matching. The hand runs
      (2.5) show only that Claude Code starts with `common`'s and planning's
      rules, from an earlier version of the table; no rule was seen to allow or
      deny a call there, and every other step's rules have never been passed to
      Claude Code. Untested: design's `git worktree add` rule and its
      `../*-proposal/` edit rules, which reach outside the working directory;
      the pilot exercises them only if its design is blocked on a prerequisite.
      The rules are a first seed: the pilot's denials refine them (7.3).
- [x] 2.2 `run_change_step.py run <step> <change>`: `claude -p` with the step's
      skill prompt, `--permission-mode dontAsk`, the step's rules from
      `change_steps.toml`, the outcome schema through `--json-schema`, and
      `--output-format stream-json --verbose`; record the session id; append the
      validated outcome. A run that exits non-zero, or ends with no outcome or one
      the schema rejects, is logged `stopped` by the wrapper with its exit status.
      A `stopped` line's `denials` come from the run's `permission_denials`, never
      from the step's account (D3, 01 F5). Unit (fake runner and fake stream): each
      outcome is logged with session and commit; a crash, an empty and a malformed
      outcome each log `stopped`; denials are taken from the stream.
      Done. The command is `claude -p <prompt>` with the prompt straight after
      `-p` (the rule lists are variadic), `--setting-sources project` so the
      owner's own allow rules never widen a step's, and `--append-system-prompt`
      saying the run is unattended and how to end a turn (section 5 puts the same
      into the skills). The skill is invoked as `/change-<step> <change>`, with
      `--sections` (implementation's, `2`, `1-3`, or `1,3`; logged as a list)
      and free `--arguments`. Claude Code is given the schema without its
      top-level `allOf` (`harness_schema`), since the API refuses a top-level
      combinator in a tool's input schema; the wrapper checks the full schema at
      the end. A run that ends `is_error` is also logged `stopped`. Each line adds
      `exit_status` and `transcript`; `run` exits 1 when the line is `stopped`.
      Unit (`test_run_change_step.py`, fake runner and fake stream): the command's
      flags, rules, and schema; each outcome logged with session and commit;
      crash, no outcome, error result, and malformed outcome each `stopped`;
      denials from the stream replacing the step's, and kept for a failed run;
      implementation's sections; planning resuming design's session, or starting
      fresh without one; review refused as not a Claude Code step.
      After the fresh-context check: a runner that raises (`claude` missing, an
      interrupt) still logs `stopped`, `exit_status` null, and an interrupt is
      re-raised after the line is written; planning resumes the latest session
      of design or planning, and `--fresh` starts it anew (D8's offer of a fresh
      session), but refuses to resume past a design or planning run that
      recorded no session, as `resume` does; only implementation takes
      `--sections`, and a backwards range is refused; a run denied any tool is
      logged `stopped` naming the denials, whatever it answered, since the delta
      requires it and a step that carried on may have worked around the denial;
      progress goes to stderr, so stdout carries only the outcome line. Each is
      unit-tested, except that `_run_claude` kills a `claude` process still
      running when reading its output fails, which is the subprocess boundary
      itself.
- [x] 2.3 `run_change_step.py resume <change> --answer <text> [--allow <rule>]`:
      resume the last session of the step with `--resume <id>` and the owner's
      answer, with any rule granted for that one run (D6). Unit: the resumed
      command carries the session and the granted rule, and the next run of the
      step does not.
      Done. It resumes the latest log line of a Claude Code step (orchestrator
      notes are skipped), and refuses when that line names no session, since a
      run that crashed before reporting one is the step's last act, not the one
      before it. The answer is sent as "The owner's answer: …", so one starting
      with `-` is never read as a flag. It logs the outcome under that step,
      carries its `sections`, and records any `granted` rules on the resumed
      run's line. Unit: as the task names, plus an implementation resumed keeps
      its sections, nothing to resume, a last run with no session, and an empty
      answer are refused, and each run of a resumed discussion claims its own
      transcript.
- [x] 2.4 Event stream and progress (D7): write the stream to
      `reviews/transcripts/NN-<step>.jsonl`, numbered after every record in
      `reviews/` and `reviews/transcripts/`, and a progress file beside it with
      one line per tool call and its time. Unit: the transcript's number follows
      existing records, and the progress file lists the fake stream's tool calls.
      Done. The transcript is claimed by exclusive create before the run, and
      every line of the merged output is written to it, events or not; the
      progress file is `NN-<step>.progress`, one `HH:MM:SSZ <tool> <summary>` line
      per tool call, also echoed to the terminal. Unit: as the task names, plus a
      line that is not an event is kept in the transcript and not read.
- [x] 2.5 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`; one hand run of `run_change_step.py run plan` on a
      scratch copy of a change, recorded here with its outcome line, to confirm the
      `claude -p` flags the unit tests assume.
      Unit: `uv run --no-project --with pytest pytest -q
      scripts/tests/test_run_change_step.py`, 87 passed before the fresh-context
      fixes. `make test`: passed, including `scripts/tests`, on the tree before the two schema fixes the hand runs forced (`$schema` draft-07, `harness_schema`), which touched only `run_change_step.py`, the schema, and their test; the focused suite passed after them.
      `make check-comment-hygiene`: passed. The fresh-context fixes ran after
      `make test`; the focused suite passed after them (94), as did
      `make check-packaging`: passed. A second fresh-context check followed; its
      fixes (the table's pushes and self-edits, validating the step table,
      denied runs ending `stopped`, killing a run whose output fails) ran with
      the focused suite (105 passed) and `make check-comment-hygiene`, not with
      `make test` or `make check-packaging` again: they touched only
      `run_change_step.py`, `change_steps.toml`, and the test.
      Hand runs (Claude Code 2.1.300), in a detached worktree of `979b4ec1` with
      this section's scripts as they stood before both fresh-context checks
      copied in (`claude_command`'s flags unchanged since, the table since
      narrowed) and this change copied as
      `scratch-orchestrate`, with no index row, so the plan's entry check could
      not pass:
      1. `exit 1`, logged `stopped` by the wrapper, twice (log seq 1 and 2,
         transcripts 01 and 03; the first was the run the auto-mode check
         reported as denied, which had in fact run): Claude Code refused
         `"$schema"` draft 2020-12 ("no schema with key or ref"). The schema now
         declares draft-07, which has `if`/`then`.
      2. `exit 1`, logged `stopped`: "API Error: 400 … input_schema does not
         support oneOf, allOf, or anyOf at the top level". The premise in 1.1's
         note was wrong; hence `harness_schema`.
      3. Exit 0, 4 turns, $0.29. The skill ran from the `/change-plan` prompt,
         one compound Bash call (`cd …; for f in …; do cat $f; done`) was denied
         under `dontAsk`, and the step ended with its own `stopped` outcome as
         the appended prompt directs, read from the `result` event's
         `structured_output`:
         `{"seq": 4, "step": "plan", "session": "551cffba-…", "commit":
         "979b4ec1…", "exit_status": 0, "transcript": "transcripts/05-plan.jsonl",
         "outcome": "stopped", "message": "Planning for scratch-orchestrate
         stopped before it began. A Bash call was denied … no index row …",
         "reason": "This Bash call was denied in don't-ask mode: …", "denials":
         [{"tool_name": "Bash", "tool_use_id": "toolu_01QJ…", "tool_input":
         {"command": "cd openspec/changes/scratch-orchestrate; for f in …"}}]}`.
         The step's own `denials` had a different shape (`tool`, `command`); the
         logged ones are the stream's `permission_denials`, as D3 requires.
      Confirmed: the flag order, that Claude Code accepts `--setting-sources
      project` (not that the owner's own allow rules are then excluded, which
      this project's settings, holding no permissions, could not show), the
      stream's
      `session_id`, `result`, `structured_output`, `permission_denials`, and
      `is_error` fields, and a slash-command prompt invoking the skill. Not
      confirmed here: `--resume` (no question to answer), and whether a
      granted rule applies to a resumed turn (a Risk the pilot checks).

Handoff. A plain read-only Bash call (`ls -R …; grep -n …`) ran under `dontAsk`
though no rule names `ls` or `grep`: Claude Code appears to allow commands it
classes read-only on its own, while a `cd …; for …` compound was denied. The
pilot should expect denials of that shape and seed rules from them (7.3). The
scratch worktree's transcripts also hold `02-plan.jsonl`, empty, owned by root,
and with no log line, written at 11:44 local, between the first hand run and the
second; this session started no run then, and its origin is unexplained. A
claimed transcript with no line is what a wrapper killed outright (SIGKILL,
which no handler sees) still leaves: D14's "step that died before writing an
outcome". Section 3
adds the `review` step to this module's `Wrapper` and `main`, absorbing
`run_change_review.py`; reuse `next_transcript`'s numbering rule there, and note
that the review's `.log` transcripts and records share the numbering.

Round 1 fixes. 02 O2 and 02 O3: the table is `.claude/change-steps.toml` and the
schema `.agents/change-outcome.schema.json` (the moves, `STEP_TABLE`, `SCHEMA`,
and common's deny were the orchestrator's, committed as `6abaa3ef` and
`82ca2c94`; the docstring, the Makefile comment, the skills' citations, the
documents, and the tests are this round's); `check_doc_citations.py` verifies
`.agents/` paths too, so the skills' citation of the schema stays checked, with
`AGENTS.md`'s rule and the Makefile comment saying so. X2: `Stream` gathers
`permission_denials` over every `result` event, keyed by `tool_use_id`, and
takes each denial's `decision_reason_type` from the `permission_denied` system
event with that id as `reason`; a run woken for a second turn by a background
task no longer loses its first turn's denials. X3 and X5 (option 2):
`run_outcome` logs the step's own outcome with the run's denials on every line,
and no longer turns a finished run with a denial into `stopped`; the appended
prompt says one command per Bash call, a denied chain rerun one command at a
time, independent work finished before a stop, the exact call named, nothing
done by another tool. D6a: `denials <change> <seq>` prints each denial on a run's
line with its reason and the tool calls the run made after it, from the
transcript. X4 and 07 A1: the table's rules — the read-only utilities and
`find` without its writing actions on `common`, `make round-view-closed*`,
`gh run view *` on validate, validate's bare `Edit` deny removed — were the
orchestrator's edits; the tests here match the chained command of log line 1,
`gh run view`, each utility, each writing `find`, the guard with a variable, and
validate's record `Write` allowed with no `Edit` of a tracked file (an `Edit`
rule covers every editing tool, so the test's matcher does too). Unit: denials
gathered over two turns with the reason; a finished run with a denial logged
finished; the `denials` report, with no denial, no transcript, and no such seq;
every outcome logged with `denials`.

## 3. Reviews and the `make` targets through the wrapper

Delivers D11 and D1's unattended targets: the review runner absorbed into the
wrapper, with a run-specific success (01 F4), and `UNATTENDED=1` on every step's
target, with planning's new target (D8).

- [x] 3.1 Move the retired `run_change_review.py`'s behaviour into
      `run_change_step.py`'s `review` step: the reviewer-session marker, resuming
      the reviewer's session, the transcript, claiming a numbered record per run
      and removing it when the reviewer fails or its review is invalid, and the
      pre-closeout validation check. The outcome is `finished` naming the record
      this run published and the reviewed commit, otherwise `stopped` with the
      runner's reason; an earlier record never counts. Move
      the retired `test_run_change_review.py`'s cases to
      `scripts/tests/test_run_change_step.py`, and delete the old script and test
      file. Unit: a failed run beside an existing `01-design.md` logs `stopped`.
      Done. The review code moved as it was, into `run_change_step.py`, under a
      `review <change> --kind …` command taking the old options; `ReviewError` is
      now a `StepError`, the Codex runner type is `CodexRunner`, and the numbering
      rule is one helper, `next_number`, shared with section 2's transcripts.
      `review_and_log` logs the outcome: `finished` (`next: triage`) with
      `record` (the published file's name), `kind`, the reviewed commit, and the
      session as `codex:<id>`, all read back from the markers this run's record
      ends with; any `ReviewError`, including a refusal before the reviewer
      starts, is `stopped` with its message as the reason and `HEAD` as the
      commit; a reviewer that cannot start (`codex` missing) or is interrupted
      is logged `stopped` with `HEAD` too, and an interrupt is then re-raised,
      as `run` does. The session and commit are the last markers in the record,
      since a review may quote an earlier record's; `prior_session` likewise
      takes the last session marker, where the old runner took the first. A
      review's `stopped` line has no `exit_status` or `transcript` field: the
      runner's reason names Codex's exit ("the reviewer exited N") and the
      transcript, and the review keeps its own `.log` transcript naming. Codex's
      progress and the "Review written to <record>" line (now the file's name,
      not its repository path) go to stderr, so stdout carries only the outcome
      line; a unit test shows that for a stopped review, not a published one,
      since `main` runs the module's review functions rather than an injected
      runner. All 54 tests of the old file moved (`reviewer.` → `step.`; the
      Codex session fixture renamed `CODEX_SESSION`); `make review`'s now
      expects the wrapper's command, and the three `make -n` tests run through
      the new `_make_n`, clear of inherited variables. The old script and test
      file are deleted. The permanent spec's Evidence
      line cited the deleted script and now names `run_change_step.py review`,
      so the citation resolves. Unit, new: a published review logged
      `finished` with its record, commit, and session; a failed run beside an
      earlier record of its kind logged `stopped`, no `record`; a pre-closeout
      review refused before it runs, an interrupted review, and the command's
      non-zero exit, each `stopped`; a review quoting earlier markers logged with
      its own; a reviewer that cannot start logged `stopped` with `HEAD`.
- [x] 3.2 `Makefile`: `make review` and `make design-review` call the wrapper's
      `review` step with their current arguments; `make design`, `make triage`,
      `make implement` (with `SECTION`/`SECTIONS`), `make validate`,
      `make closeout`, and `make archive-cleanup` run the wrapper when
      `UNATTENDED=1` and are unchanged otherwise; add `make plan CHANGE=<change>`
      after `make design`, interactive by default, its unattended form resuming
      the design step's session from the log (D8).
      Done. `STEP_RUN` names the wrapper's `run`; each target chooses with
      `$(if $(filter 1,$(UNATTENDED)),…)`, its interactive form unchanged.
      `implement` passes `--sections` from `SECTIONS`, else `SECTION`; `validate`
      passes `HELM_ALL_SCENARIOS=1` as `--arguments`; `make plan` takes `FRESH=1`
      (only `1`, as `UNATTENDED`) for `--fresh` (2.2) and is added to `.PHONY`. Unit (`make -n`, with
      `MAKEFLAGS` and the step variables cleared from the environment, since a
      calling make passes its own command-line variables down): every step
      target's interactive and unattended commands, implementation's sections,
      planning's `FRESH` (and `FRESH=0` not fresh), validation's
      `HELM_ALL_SCENARIOS`, and `make review`; the suite also passes with
      `UNATTENDED=1` exported.
- [x] 3.3 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`; `make -n` of each target with and without
      `UNATTENDED=1`, recorded here; one real `make review KIND=design` on a
      scratch copy of a change, confirming the record, marker, and outcome line.
      Unit: `uv run --no-project --with pytest pytest -q
      scripts/tests/test_run_change_step.py`, 175 passed, then 178 after the
      fresh-context fixes, which ran with the focused suite and
      `make check-comment-hygiene` only.
      `make check-comment-hygiene`, `make check-packaging`: passed. `make test`:
      passed, `scripts/tests` included.
      `make -n` (with `CHANGE=X`, after `find_change.py` and `round_view.py`):
      `design` → `claude "/change-design X"`, unattended
      `python3 scripts/run_change_step.py run design "X"`; likewise `plan`,
      `triage`, `validate`, `closeout`, `archive-cleanup`, and `implement`;
      `implement SECTIONS=1-3` → `claude "/change-implement X sections 1-3"`,
      unattended `… run implement "X" --sections "1-3"`; `SECTION=2` →
      `section 2`, `--sections "2"`; `plan UNATTENDED=1 FRESH=1` → `… run plan
      "X" --fresh`; `validate UNATTENDED=1 HELM_ALL_SCENARIOS=1` → `… run
      validate "X" --arguments "with HELM_ALL_SCENARIOS=1"`; `review KIND=design`
      → `python3 scripts/run_change_step.py review "X" --kind "design" --base
      "dev" --model "gpt-6-sol" --effort "high"`.
      Real review: `make -C <scratch worktree> review CHANGE=scratch-orchestrate
      KIND=design`, the worktree of 2.5 with this section's `scripts/` files and
      `Makefile` copied in: exit 0; Codex published `reviews/06-design.md`
      (numbered after section 2's five plan transcripts), its transcript
      `transcripts/06-design.log`, the record ending
      `<!-- reviewer-session: 01a13f09-… -->` and
      `<!-- reviewed-commit: 979b4ec1… -->`, and logged
      `{"seq": 5, "step": "review", "session": "codex:01a13f09-…", "commit":
      "979b4ec1…", "kind": "design", "record": "06-design.md", "outcome":
      "finished", "next": "triage", "message": "06-design.md written; triage is
      next"}`. The worktree's `HEAD` is still `979b4ec1`, with these files as
      uncommitted copies; the reviewed commit is that `HEAD`. It was a fresh
      reviewer: continuing an earlier reviewer's session was not exercised, nor
      did the run show what stdout held beyond the log line `make` printed.
      `make check-doc-citations CHANGE=orchestrate-change-workflow` now reports
      `run_change_review.py` (retired) and its test as missing: only this change's
      `design.md`, `proposal.md`, and `tasks.md` cite them, describing what the
      change removes. Closeout's citation check (8.10) has to resolve those, by
      the narrative compression (8.4) rewording them or by the owner accepting
      them as the change's record of what it removed.

Handoff. Deleting `run_change_review.py` meant editing the permanent
`openspec/specs/change-workflow/spec.md` Evidence line now, not at closeout: the
Evidence section sits outside any requirement, so the delta cannot carry it, and
a citation of a deleted file is a blocking defect. 8.9's promotion record should
list it. Reviews stayed module functions (`run_review`, `review_and_log`) rather
than joining `Wrapper`, as section 2's handoff suggested: the Codex runner,
transcript, and numbering are their own, and moving them would have rewritten the
moved tests. `docs/agents/change-workflow.md` does not yet name `make plan`,
`UNATTENDED=1`, or the workflow log; 8.9 owns that.

## 4. The next-step computation

Delivers `scripts/change_next_step.py` (D14; D5, D5a, D9, D13; 01 F1, F2, F3;
requirements "The next step is computed from the files" and "A design blocked on a
prerequisite halts").

- [x] 4.1 Read the index row (status, `Depends on`, `Notes`), `reviews/` and their
      triage gates, `tasks.md`'s sections and checks, the log, and
      `round_view.open_view()`; print `{"step": ..., "reason": ...}`, or an
      `unclassified` result naming what it read when no rule applies. The rules
      follow each skill's entry check and handoff: design and its review until the
      gate passes, planning, the round agreement before implementation (D13), the
      agreed sections, the round view, validation and the implementation review
      side by side, triage, pre-closeout, closeout, the closeout review, archive
      cleanup.
      Done. `compute(root, change)` returns `{"step", "reason", …}`; the steps it
      names are `design`, `plan`, `implement` (with the round's next session's
      `sections`), `round-view`, `validate`, `review` (with its `kind`),
      `validate-and-review`, `triage`, `closeout`, `archive-cleanup`, plus
      `owner`, `done` (archived), and `unclassified` (with `read`, a summary of
      every input). Rules, in order: an open round view; no index row; the
      status (`archived`, `deferred`, `blocked in` → owner); a dependency gating
      the current phase or an earlier one (4.2); then one function per phase.
      Design: an untriaged design review → triage; a design discussion whose last
      run finished → the design review; else design. Planning: a written plan
      (last plan run finished) → the owner accepts it; else plan. Implementation:
      no agreed round, or `ready for implementation` with the last round done →
      the owner agrees a round, naming the open sections; the round's first
      session with an open section → implement; the round implemented and no
      record numbered after it → round view; then validation and the
      implementation review, whichever is missing (both → side by side); any of
      the round's records untriaged → triage; a validation not clearing `HEAD`
      (the wrapper's `validation_problem`, so fixes after triage are validated
      again) → validate; sections left → the owner agrees the next round; every
      section before closeout checked → the pre-closeout review, its triage, and
      a gate not passed → owner. Closeout: not yet archived, or archived but not
      committed (closeout resumes after its archive step) → closeout; archived →
      the closeout review, its triage, then archive cleanup once the gate passed,
      or the owner. Before any phase rule, a step of the current phase whose
      latest run asked, returned, was blocked, or stopped yields the owner,
      naming it (`resume`, `return_to`, `blocked_on`, `denials`), for every step,
      triage, validation, and review included, so a question is always answered
      by resuming its session; a review counts for the phase its `kind` belongs
      to; an `orchestrator` line clears what came before it, so the orchestrating
      session can rerun a stopped step once it has recorded why; a design blocked
      on a prerequisite is left to 4.2's rules. A written plan yields the owner
      with `resume: plan`, since the planning session sets the status when the
      owner accepts. A gate is passed when the triage's `## Gate` begins
      "Passed": the triage skill's template asks only for the owner's words, and
      existing triage files begin so by convention, not by contract. A section is
      a `## N. Title` heading; it is complete when it has tasks and none is open;
      one whose title contains "closeout" (plans write "Closeout", "Plan
      closeout", "Repository closeout") is never part of a round. A pasted
      `-external` review counts as its kind. An untriaged design review routes
      to the triage step, where `change-design` §1 would triage it inside the
      design session: both skills can triage it, and a separate step keeps the
      design session's turns to the discussion. A malformed `Depends on` entry
      is unclassified.
      To tell a round's records from earlier ones, a `round` line now records
      `after`, the highest record number when it was agreed (`note_round`,
      section 1's, extended; unit-tested there). The index row is read through
      `check_change_index.index_rows`, its new public reader, whose `Row` now
      carries `Notes`. The task list's file name is the constant `TASKS_FILE`;
      `make check-comment-hygiene` rejects any literal `tasks.md` in Python,
      which a script that reads the file cannot avoid, so the check now exempts
      exactly that definition line by its content, with a Makefile comment
      saying why; a mention anywhere else in the script still fails (checked by
      hand). This changes a repository check, which the plan did not name: the
      owner decides whether it stands (the alternatives are matching only
      comments, which grep does poorly, or building the name indirectly, which
      would evade the check rather than answer it); until then it is this
      section's proposal, and `AGENTS.md`'s description of the check ("rejects
      … `tasks.md` references") is true except for that one line. Settled at
      round 1 (02 O1): the exemption stands, as a named rule of the check's
      Python port.
- [x] 4.2 The owner results: a round view open (D9, 01 F3); a prerequisite whose
      directory is not on the branch (D5, 01 F2); a design-gating dependency not
      archived (01 F1); a design-gating dependency archived on this branch, the
      release proposed (D5a); a status that disagrees with the log, where the
      files prevail.
      Done. A dependency is read from `Depends on` with its phase (none means
      implementation) and holds the change when it gates the current phase or an
      earlier one: no directory on the branch → owner, merge dev; archived here →
      owner, `release`; otherwise → owner, waits. A design whose last run ended
      `blocked` on a change with no directory here → owner, merge dev; once that
      change's directory has arrived but `Depends on` does not name it → design,
      to record it. A disagreement is reported, not routed: when the log's last
      step belongs to a later phase than the status, the step the files give is
      returned with a `disagreement` naming both. A blocked design whose
      prerequisite is archived here no longer holds design, so once the owner
      releases the dependency (D5a) design resumes.
- [x] 4.3 Tests in `scripts/tests/test_change_next_step.py`: unit, over fixture
      change directories and logs, for every rule and owner result above and an
      unclassifiable state; the round-view case in a temporary Git repository,
      with a view opened by `round_view.start` and closed by `round_view.done`,
      since a real repository is the lowest level that proves it.
      Done: 67 tests. Unit, over fixture index rows, change directories, records
      with triage files, and logs written through the wrapper, with `HEAD`, the
      round view, and whether the archive is committed injected: every rule
      above, each owner result (a question, return, block, and stop each, for
      design, implementation, triage, validation beside a finished review,
      closeout, and archive cleanup; an `orchestrator` line clearing a stop; a
      design review's stop not holding implementation; a confirmed return no
      longer waiting), each dependency result (no directory, not archived,
      archived, gating a later phase, malformed, and the release letting design
      resume), the closeout section's title variants, an external review, an
      uncommitted archive, a pruned archived row, the disagreement, and
      unclassified states (no row, a status outside the legend, no sections, a
      round naming an unknown section, an unknown change, a malformed log).
      The round-view case runs in a temporary Git repository: open, the result
      waits on the owner naming the view; closed, it moves on to the round view
      step.
- [x] 4.4 Verification: `uv run pytest -q scripts/tests/test_change_next_step.py`
      (unit, with the temporary repository); `make test`; the script run by hand
      on this change and on the pilot change, its results recorded here.
      `uv run --no-project --with pytest pytest -q
      scripts/tests/test_change_next_step.py`: 46 passed, then 67 after the
      fresh-context fixes; all of `scripts/tests` together: 821, then 842. `make check-comment-hygiene`, `make check-packaging`:
      passed. `make test`: passed, `scripts/tests` included, before the
      fresh-context fixes, which touched only `change_next_step.py`, its test,
      and `note_round`'s docstring, and ran with the focused suites and
      `make check-comment-hygiene`. By hand, after the fixes:
      - `orchestrate-change-workflow`, at `in implementation` with no round line
        (its sections so far were agreed in chat, before rounds existed):
        `{"step": "owner", "reason": "agree the next implementation round: which
        sections, and how many sessions", "round": ["5", "6", "7"]}`, section 4
        being checked; before it was, the same with `"4"` first.
      - `fix-resource-pool-provider-at-creation`: `{"step": "design", "reason":
        "ready for design"}`.
      - `agent-driven-change-workflow` (archived): `{"step": "done"}`; and
        `name-unverifiable-responses` (`in implementation`): owner, agree a round
        of section 3.
      This change's index row still read `ready for implementation` after
      section 1, which should have set `in implementation`; corrected here, with
      its `Notes`.

Handoff. The rules take the skills' entry checks and handoffs at their word, so
gaps will show in the pilot as `unclassified` results or `orchestrator` lines
(7.3): for example, a discussion step that finished but left its status (design
finished is treated as ready for review), a triage that committed fixes (read only
through the validation no longer naming `HEAD`), and owner notes saved with no
review or validation yet (the round view is then treated as done). A round's
records are those numbered above its `after`, so records written before a round
was agreed, under no orchestrator, never count for it. The orchestrator (6.1) must
save a record of the owner's reading even when the owner has no notes ("No
notes."), since that record is how the computation knows the round view happened;
without one it names the round view again.

Round 1 fixes. 04 F3: `pending` no longer cuts the log at the latest
orchestrator line; a run waits until a decision line `resolves` its `seq`, so a
decision about one step's run leaves another's question waiting. 04 F1: a
decision with `next` routes to that step until a run of it (of its `kind`, for a
review) is logged after the decision — `directed`, after the pending rule — so a
confirmed return reaches the phase's step, whose entry check sets the status. 04
F2 (both): a pre-closeout or closeout review whose gate did not pass is repeated
once `HEAD` differs from its reviewed commit (the record's last `reviewed-commit`
marker) in more than changes' records, `fixed_since`, through the wrapper's
`_changed_since` (injected in tests); for pre-closeout, `validate` first while
the validation does not clear `HEAD`; otherwise the owner, who may direct a
repeat review with a decision line. X2/X3 (option 2): a run that ended other
than `stopped` with denials on its line waits like a stop, for the orchestrator's
reading. X1: the rules read a round recorded after the fact by its `after`. By
hand, after the fixes: the router on this change was not run; the call
(`python3 scripts/change_next_step.py orchestrate-change-workflow`) was denied to
this triage session, as was `run_change_step.py denials … 3`. Unit
(`test_change_next_step.py`, 80 tests): a stop waits until a decision resolves
it and a decision naming no run clears nothing; a validation question waits
beside a resolved review stop; a finished run with a denial waits until read; a
confirmed return routes to design and an unconfirmed one to the owner; a
directed step that ran is no longer directed; a failed pre-closeout gate with
`HEAD` at the reviewed commit waits, with `HEAD` moved goes to validate then to
the review again, and with only records changed waits; a failed closeout gate
with a fix goes to the review again; a directed repeat review; a round recorded
after the fact owns the records above its `after`.

## 5. The leaf skills report through the wrapper

Delivers D12, D13's skill changes, and D5's design path; the skills' text only, as
D12 limits it.

- [x] 5.1 Every `change-*` skill under `.agents/skills/` gains how it runs
      unattended: each "stop and ask the owner" ends its turn with a `question`
      outcome; a denied tool ends it `stopped` with its reason, never a question
      or a workaround; its last turn ends with an outcome matching
      the outcome schema. Discussion steps (design, planning,
      triage) end each reply with its `message`. `change-validate` §5's
      environmental remedy is a `question`; `change-closeout`'s point needing a
      code edit is `returned` to implementation (D8). Interactive use is unchanged.
      Done as one "Running unattended" section in each skill, before its step 1,
      opening "Run interactively … this section does not apply", rather than an
      edit at each of the skills' 38 stops: a stop to ask, tell, or wait for the
      owner is a `question` (what was found, the options, a recommendation); a
      plain stop (a guard refusing, `HEAD` moving) is `stopped` with no denials;
      a denied tool is `stopped` with the calls as seen, which the wrapper
      replaces, never a workaround or a question; each skill then names its own
      ends — design `finished` to its review or `blocked` on a prerequisite (its
      exact change name); planning's presentation a `question`, then `finished`,
      and an exposed design question `returned` to design, status untouched;
      triage's findings and gate `question`s, and a closeout fix needing code
      `returned` to implementation; implementation `finished`, a wrong plan
      `returned` to design or planning with nothing committed, an external input
      or an oversized section a `question`; validation's environmental remedy a
      `question` (§5) taking only the action named; closeout's points
      `question`s and a code edit `returned` to implementation; archive
      cleanup `finished`, an already-archived row included. Design, planning,
      and triage say every reply is a turn, its `message` the reply in full.
      `change-review` says only that nothing changes: Codex's final message is
      the review, and the wrapper derives the outcome. A `returned` outcome
      leaves the status; so that the step started next can accept the change,
      `change-plan`'s entry check now takes a change whose return from
      implementation the owner confirmed, and `change-implement`'s one `in
      closeout` whose return the owner confirmed, each setting its own phase.
- [x] 5.2 `change-plan` sizes a section as a coherent, verifiable slice and drops
      "one section per session" from its description and handoff;
      `change-implement` implements the sections it was given, drops §8's
      question, and keeps the warning about a growing session as advice (D13).
      Done. `change-plan`: its description, its section-sizing bullet (a coherent
      slice one verification point proves; the plan says nothing of sessions,
      rounds, or harnesses, which the owner decides before implementation), its
      plan check, and its handoff (rounds the owner agrees). `change-implement`:
      its description and title, its opening (a session implements the sections
      it was given; a growing session is the owner's to weigh), the oversized
      section's wording, and step 8, which goes on through the sections given
      and then stops and reports, recommending a fresh session when it is
      large, with no question.
- [x] 5.3 `change-design` gains the prerequisite path: shape the prerequisite with
      the owner, write it in a worktree on a new branch from dev, end `blocked`;
      after dev is merged in, keep the change `in design` with the dependency
      gating design; on release, drop only the dependency (D5, D5a).
      Done as "When the design needs another change first", under step 4, in
      five steps: shape the prerequisite's requirements and initial proposal
      with the owner; write it in `git worktree add ../<prerequisite>-proposal -b
      propose-<prerequisite> dev`, with its `ready for design` row, checked by
      `make -C ../<prerequisite>-proposal check-change-index`; the owner commits
      and opens its pull request, and the design halts (`blocked`); once dev
      is merged in, record the dependency gating design, keep `in design`, and
      halt again (`blocked`); once the prerequisite is archived and merged in,
      drop only the dependency on the owner's word. Step 1's entry check names
      the release, and the opening's list of edits allowed before the design is
      settled includes the prerequisite's proposal and dependency.
- [x] 5.4 Verification: `make check-agent-skills`; a fresh-context read of each
      edited skill against D12, recording anything it found.
      `make check-agent-skills`, `make check-comment-hygiene`, `make
      check-packaging` (after the fixes): passed. `make
      test`: passed, before the read's fixes, which touched only the skills and
      the step table; `test_run_change_step.py` passed after them
      (179). The read found, all fixed: no step would accept a return to
      planning or implementation (the entry checks above); design's opening
      still limited its edits; design's prerequisite stops were `question`s by
      the general rule (now `blocked`, step 4's too, so a stale question does
      not come back once the dependency is released); `blocked_on` must be the
      exact name `change_next_step.py` resolves; closeout's `evidence` named
      nothing recorded; `change-review`'s note contradicted itself; plain stops
      and `denials` were unmapped; archive cleanup's already-archived stop;
      implementation's oversized section; triage's closeout fix needing code,
      which runs steps an unattended triage may not; implementation's and
      validation's `next`; implementation's title; "section N" where those
      skills say "step N". And commands the skills call for that the step table
      denied, now allowed: archive cleanup's `make check-*` (it runs
      `make check-doc-citations`), design's `make -C ../*-proposal
      check-change-index`, bare `openspec validate`, `instructions`, `list`,
      `show`, and `status` for every step, and `openspec archive` for closeout.
      End-to-end: none, as the plan's preamble says.

Handoff. The permanent `openspec/specs/change-workflow/spec.md` Purpose still
says "implementation one section per fresh session", and the delta does not reach
it, since it is not a requirement: 8.9 should rewrite it with the renamed
requirement. The design step's `../*-proposal/` rules and `make -C` rule are
untested; the pilot reaches them only if its design is blocked on a prerequisite.
Under orchestration, D5a's release is the orchestrator's (6.1): the design skill's
own release step is the interactive path. The orchestrator must answer a
`returned` outcome by having the owner confirm it and then starting the step
returned to, whose entry check now accepts it. Section 6's skill can rely on
every leaf skill ending each unattended turn with an outcome; the stops the
skills only say "stop" at are mapped generally, not one by one, so the pilot
should watch for a stop that ends as the wrong outcome.

Round 1 fixes. X3 and X5: every skill's "A denied tool stops the step" bullet
says one command per Bash call, a denied chain rerun one command at a time,
independent work finished before the stop, the exact call named and never the
tool, nothing done by another tool; the seven citations name
`.agents/change-outcome.schema.json` (02 O3). 04 F1: `change-plan` section 3
step 1 sets `in design` interactively and ends `returned` unattended, leaving the
status. 04 F2: `change-triage`'s gate section says what the computation does with
a fix commit after a failed gate. 07 A2: `change-validate` section 2 says a
running part prints a line per step and where its step logs are.
`make check-agent-skills`: passed.

Round 2 fixes, section 5. 28 F1: every skill's denial bullet, now "A denied call
stops the step only when it cannot go on", says a step finishes what does not
depend on the denied call, ends `stopped` naming that call only when it cannot
complete without it, and otherwise goes on and ends as it ends, the denial
recorded on the outcome for the orchestrator's reading; the wrapper's appended
prompt says the same. 29 A2: `change-validate` section 2 says to wait on a
background command through the harness's notification or a read-only `tail`,
never a shell loop, since `bash -c` has no rule and will not get one.
`make check-agent-skills`: passed.

Fixes concerning no section. 02 O1: `scripts/check_comment_hygiene.py` is a
direct port of the Makefile's shell target — the same two scans, file types,
exclusions (`.claude/` among them, unchanged, so the step table now under it is
outside the change-name scan), patterns, and the one exemption as a named rule
(`EXEMPT`: the `TASKS_FILE` definition line of `scripts/change_next_step.py`);
the target is one line calling it; the script and its test are scanned like any
file, so the pattern is written as a pattern and the test builds its samples at
run time. `make check-comment-hygiene` before the port: both scans OK; after:
both scans OK. Unit (`test_check_comment_hygiene.py`, 32 tests): each pattern,
each file type and excluded directory, the exemption and a second mention, the
change names with and without dates and the `archive` filter, each file type and
exclusion of the name scan, the command's output and exit status. 07 A2:
`validate_slice.py` prints a flushed line as each step starts (its command and
log) and ends (result and seconds), through an injected `echo`; its only output
was the final summary. Unit (`test_validate_slice.py`): the lines of a local
part that fails at `test`; the flushed print. 02 O3: `check_doc_citations.py`
verifies `.agents/` paths (unit: a resolving and an absent `.agents/` citation,
a `.claude/` one not checked).

Round 1 checks. Focused suites (unit, `uv run --no-project --with pytest`):
`test_run_change_step.py`, `test_change_next_step.py`,
`test_check_comment_hygiene.py`, `test_check_doc_citations.py`,
`test_validate_slice.py`: 344 passed together before the fresh-context check,
346 after its fixes. `make test`: passed, every suite, `scripts/tests` included,
before the fresh-context fixes, which touched only `run_change_step.py`,
`change_next_step.py`, and their tests; the focused suites passed after them.
`make check-comment-hygiene`: passed, both scans, before the port and after it
and after every later edit. `make check-agent-skills`, `make check-change-index`,
`make check-packaging`, `openspec validate orchestrate-change-workflow --strict`:
passed. `make check-doc-citations CHANGE=orchestrate-change-workflow` reports
five citations, all of what the change removes or has not yet written:
`run_change_review.py` (retired; design, proposal, tasks) and its test (tasks),
which section 3 deleted and 8.10 resolves, and
`.agents/skills/change-orchestrate/SKILL.md` (6.1), which section 6 creates;
nothing else. The router and the `denials` subcommand are proven by their unit
tests; running them by hand on this change was denied to this triage session.
Fresh-context check of the diff against `82ca2c94` (a subagent, read-only,
reading the worktree since `git diff` was denied to it): comment hygiene,
import placement, test seams, and public-repository discipline satisfied; it
found, and this round fixed, three things — `denials` on a review's line, which
has no transcript, now reports "recorded no denial" rather than refusing; a
triage run's phase is read from the review or validation it followed, so a
design-phase triage that stopped no longer holds implementation (two tests); a
fixture run id in a test looked like a real pipeline run and is now obviously a
fixture. Declined: distinguishing a Git error from "not an ancestor" in
`fixed_since` (both are read as a fix having landed) — `_changed_since` is the
wrapper's existing seam with that contract, and a Git error there surfaces at
the next validation, which refuses an unreadable `HEAD`; and the credential-
helper test's `PATH` patching in `test_validate_slice.py`, which predates this
change.

Round 2 fixes, sections 1, 2, and 4 (review 28 and validation 29 of `b133afbb`,
triaged in `reviews/28-implementation.triage.md` and `29-validation.triage.md`).
Section 1, the log's writer. 28 F1 (option 1): `note_orchestrator` takes
`reads`, the run whose denials the decision has read, beside `resolves`, refused
for a run that recorded no denial; `note … orchestrator --reads`. 28 F3: it
refuses `next` of a non-review step without `resolves` (the only such directive
is a confirmed return, which the returned run would otherwise wait ahead of) and
`next = review` without `kind`; the repeat review after a failed gate stays the
line that names no run. Section 4, the computation. 28 F1: `pending()` holds a
run with unread denials for their reading first, whatever its outcome, then a
question for its resume and a return or block for the decision resolving it; a
line that resolves a run counts as having read it, and a stopped run is read and
resolved by one line; a blocked design's denials are read before the
prerequisite rules take it. 28 F2: the records pattern admits a change's ledger
and reviews under `archive/<dated directory>/`, and still not a file directly
under `archive/`, so a closeout triage's ledger commit is not a fix. Section 2,
the step table. 29 A1: the orchestrator's edits, carried here — the validate and
archive-cleanup record rules in the `Edit(path)` form, since the harness does
not honour a `Write(path)` allow rule (which corrects X4's cause: removing the
bare `Edit` deny was harmless), and `Bash(python3 scripts/change_next_step.py*)`
on common; the test matcher honours an `Edit(pattern)` rule for every editing
tool and a bare tool name, and ignores a `Write(pattern)` rule; the record tests
say the validate row admits its record to `Write` and `Edit` and nothing else,
likewise archive cleanup's draft and the index, and every step may run the
computation. The `Write(…)` twins beside `Edit(…)` rules in the design, plan,
and closeout rows are dead but harmless and are the owner's to drop (7.3).
Delta: the decision-line sentence in the owner's wording (resolves, reads,
kind), the scenarios "The owner confirms a return" and "The owner directs a
repeat review" as log lines with their refused negatives, and "A question
carries denials". Design: D3, D6, D6a, D12, D14, and the second round's
decisions list.

Round 2 checks. Focused suites (unit, `uv run --no-project --with pytest`):
`test_run_change_step.py` and `test_change_next_step.py`, 286 passed; the whole
of `scripts/tests`, 917 passed. `make test`: passed, every suite, before the
fresh-context check's fixes, which touched only `change_next_step.py`, the two
suites, and `change-validate`'s wrapping; the focused suites and `scripts/tests`
passed after them. `make check-comment-hygiene`: passed after two test strings
were reworded (an archived path with a date-and-name literal and a change
document's name both read as history). `make check-agent-skills`, `make
check-change-index`, `make check-packaging`, `openspec validate
orchestrate-change-workflow --strict`: passed. `make check-doc-citations
CHANGE=orchestrate-change-workflow`: the same five citations as round 1, all of
what the change removes or has not yet written; nothing else. Fresh-context
check of the diff against `b133afbb` (a subagent, read-only): hygiene, test
seams, public-repository discipline, and the consistency of the skills, the
prompt, D12, and the delta on the denial rule satisfied; it found, and this
round fixed, four things — the unread-denials message named the raw outcome word
("its returned waits"), a blocked design's denials were never surfaced for
reading, `directed()`'s docstring said a repeat review names no run in every
case, and the question-with-denials test ended at "validate again" rather than
the review its name promised; and two nits — the re-wrapping of the validate
sentence (done) and the dead `Write(…)` twins in three rows (declined: a table
edit, the owner's). Two calls were denied to this session and done by the
allowed tool instead: a shell append to the ledger (`printf >>`) and a `sed` on
a test file, both edits the step's `Edit` rule admits; a third, a `make test`
chained with a redirect and `echo`, was rerun as plain `make test`.

Round 3 fixes, sections 2, 4, and 5 (review 39 and validation 41 of `3e9566af`,
and the orchestrator's observation R1 from the workflow log, triaged in
`reviews/39-implementation.triage.md`, `41-validation.triage.md`, and
`45-implementation-owner.triage.md`). 39 F1: the round-2 notes' rewrite had
dropped this section 6's heading, so the computation read 6.1–6.3 as section
5's and named sections 1–5 to implement again; the heading is restored, and a
task list is checked before anything acts on it: `scripts/check_tasks.py`
(`make check-tasks CHANGE=<change>`) fails on a numbered task that sits under
another section's `## N.` heading, naming the task and the heading, only under
a recognised heading so a list in another format passes; `change-implement` and
`change-closeout` run it at their entry checks and `change-plan` after writing
the plan; and, as recommended, the computation uses the same function as its
backstop, answering `unclassified` naming the task, since a skill that skipped
the check or an edit after it would otherwise reach the router; the backstop
applies in the implementation phase, the one routed on sections, so a deferred
or blocked change with a malformed list still gets its owner result. The check
reports the same defect in one other change, outside this one and left alone:
`never-strand-the-host-on-passthrough` (a task of 5 under `## 5a.`). The
orchestrator's scan had also named `repair-storefront-alkahest-configuration`,
whose tasks of 5 sit under an unnumbered deferred-work heading after
`## 4. Closeout`; the check leaves tasks under an unnumbered heading alone, so
it passes, while `read_sections` still counts them as the last section's. 39 F2:
`pending()` holds the latest run of any step with unread denials whatever the
phase, before the phase-filtered pass for a question, return, or block, since
the run may be the one that moved the change on; tests for a design triage with
denials after `ready for planning` and a pre-closeout triage with denials after
`ready for closeout`, and a stopped design run with denials holding
implementation until a line resolves it; the two phase tests that used a
stopped fixture with denials now use a crash without any. 45 R1: `resume`
takes a mandatory `--seq` and refuses a seq that is not a step's run, not its
step's latest run, resolved by a decision line, or ended other than with a
question or a stop; the computation's `owner` result carries the waiting run's
`seq`; `make next CHANGE=<change>` (renamed `make change-next` at round 4, 55 O1)
prints the computation in plain form (`--plain`); no `make resume`. 39 F3: 6.1's
denial and decision clauses
rewritten around `reads` and `resolves`. 41 A1: `change-validate` section 2
says to wait on a background part inside one Bash call with a blocking
read-only `tail`, repeated when it times out, never by ending the turn, and to
run the Helm part in the foreground. The orchestrator's table edit,
`Bash(git check-ignore*)` on common (log seq 46), is carried here. Design: D1
(a resume names its run; `make change-next`), D14 (the phase-blind reading; the
task-list backstop). 8.9 names `make change-next` and `make check-tasks` for the
contributor guide.

Round 3 checks. Focused suites (unit, `uv run --no-project --with pytest`):
`test_run_change_step.py`, `test_change_next_step.py`, and the new
`test_check_tasks.py`, 304 passed before the fresh-context check's fixes, 309
after; the whole of `scripts/tests`, 940 passed after them. `make test`:
passed, every suite, before the fresh-context check's fixes, which touched only
`change_next_step.py`, `run_change_step.py`, `check_tasks.py`, their tests, and
`change-validate`'s wording; `scripts/tests` passed after them. `make
check-comment-hygiene`: passed after three test strings were joined at run time
(a task number beside the word that names it reads as history). `make
check-agent-skills`, `make check-change-index`, `make check-packaging`
(before and after the fixes), `openspec validate orchestrate-change-workflow
--strict`: passed. `make check-doc-citations CHANGE=orchestrate-change-workflow`:
the same five citations as rounds 1 and 2, all of what the change removes or has
not yet written; nothing else. `make check-tasks` on this change: OK; the
computation's plain form shows this triage's question with its `seq`.
Fresh-context check of the diff against `3e9566af` (a subagent, read-only,
reading the files since script execution was denied to it): hygiene, import
placement, test seams, and public-repository discipline satisfied; it found,
and this round fixed, four things — `task_problems` kept the last numbered
heading across an unnumbered one and compared ids case-sensitively (now reset
on any other `##` heading, compared lower-cased, two tests); the backstop ran
before the status rules, turning a deferred or blocked change with a malformed
list `unclassified` (now in the implementation phase only, one test); the
phase-blind pass released a stopped run on a `reads` line where the in-phase
pass needs `resolves` (now `resolves` for a stop in either pass, the docstring
reworded, the test extended); and `resume` accepted a question a decision line
had resolved (now refused whatever the outcome, one test) — plus the coverage
it asked for (a plan run's denials after `ready for implementation`, an earlier
phase's question with denials, `--plain` with a list value) and four nits (the
check script's docstring, the validate sentence naming the line to match and
why the Helm part is foreground, a dict's name and a set built once, a test's
name). Declined: reading the task list once rather than twice in the
computation, a small file and a simpler signature. Two calls were denied to
this session, both `python3 -c` scans the orchestrator read at seq 50; neither
was needed, the suites and `make check-tasks` proving what they would have
shown.

Round 4 fixes (triage of 52-implementation, 54-validation, and
55-implementation-owner, all of `e8c1723f`). 52 F1: the documents said a stopped
run's denial reading is the line that also resolves it, and `resume` refuses a
resolved run, so the one-run grant D6a prescribes could never be used; D3, D6a
step 4, 6.1, and the docstrings of `note_orchestrator`, `pending`, and
`_waiting` now say a stop's reading resolves nothing, a recovered stop is
resumed with the grant and its resumed run supersedes it, and a stop not
recovered is settled by `resolves`; no behaviour changed; the grant test is
rewritten in that order (stop, `reads` line, resume with the grant, a second
resume refused) and the router gains a test that a read stop waits for the
owner until its resumed run moves the change on. 52 F2: D6's waiting rule is
41 A1's (a blocking read-only `tail` inside one Bash call, repeated on timeout,
never the harness's notification), the 29 A2 record notes the supersession, and
the third round's decisions are recorded in `design.md`. 55 O1: `make next` and
`make watch` are `make change-next` and `make change-watch`, in the Makefile,
D1, D7, D14, and 8.9. 55 O2: 6.1 and D7 say the orchestrating session gives
`make change-watch CHANGE=<change>` on starting any long-running unattended
turn, a discussion step resumed for fixes or checks included; no wrapper
change. 55 O3: task 6.4, bash completion of change names, and a line in the
proposal. 54 A1: `change-validate` section 2 says the background fetch runs
with no shell redirect; D6 says why. The index row's notes name the fourth
round.

Round 4 checks. Focused suites (unit, `uv run --no-project --with pytest`):
`test_run_change_step.py`, `test_change_next_step.py`, `test_check_tasks.py`,
312 passed. `make test`: passed, every suite; `scripts/tests` 943 passed.
`make check-comment-hygiene`, `make check-agent-skills`, `make
check-change-index`, `make check-tasks`, `make check-packaging`, `openspec
validate orchestrate-change-workflow --strict`: passed. `make
check-doc-citations CHANGE=orchestrate-change-workflow`: the same five
citations as rounds 1–3, all of what the change removes or has not yet written;
nothing else. Fresh-context check of the diff against `e8c1723f` (a read-only
subagent, which could run the suites and the hygiene check): comment hygiene,
consistency across the repository, test order and level, and
public-repository discipline satisfied; `resume` and `pending()` confirmed to
behave as the new wording says. It found one thing, fixed: `pending()`'s
docstring said every stopped run waits in any phase, where only one with
denials does. Nits taken: `_waiting`'s docstring reflowed and worded like
`pending()`'s; 6.1's grammar. Declined: asserting the step the router names
after the resumed run, since the test proves the stop's release and the step
named after is other tests' subject. Three calls were denied to this session:
two `ls` of bash-completion's files outside the repository, read by the
orchestrator at seq 63, and a `python3 -c` computing the router's answer for
that nit; none was needed.

## 6. The orchestrating session

Delivers `change-orchestrate` (D2, D7's notifications, D8, D9, D10, D13's round
line, D14's backstop, never passing a gate; requirements "An orchestrating
session advances one change" and "Discussion steps stay conversations with the
owner").

- [x] 6.1 Add `.agents/skills/change-orchestrate/SKILL.md`, linked from
      `.claude/skills/` and `.codex/skills/`: on every start and after compaction,
      run `change_next_step.py` and read the log's last lines; run the step it
      names through the wrapper; relay each discussion message and resume with the
      owner's reply; put each `question` to the owner; bring every gate and
      `returned` proposal to the owner; agree each round and record it with
      `note`; open the round view, save the owner's notes verbatim as the next
      `NN-implementation-owner.md`, then close it; start validation and the
      implementation review side by side; send a push notification on `question`,
      `stopped`, or a long step finishing; read each denial as D6a says — from
      the run's line, never the step's message; by the harness's reason, a gap
      or a forbidden action; `run_change_step.py denials <change> <seq>` for the
      calls after it, a later call doing the denied work being a workaround; for
      a gap the narrowest rule, as a one-run grant or a tracked table edit; the
      reading recorded as a decision line that `reads` the run, `by:
      orchestrator`, and resolves nothing: a run that asked or proposed a
      return is answered or decided after its reading, and a stopped run is
      resumed after it with the one-run grant, or, when it is not recovered,
      settled by a `resolves` line (52 F1); a forbidden or workaround reading
      going to the owner —; resume a waiting run by its `seq`, the one the
      computation's `owner` result names, never the log's last run; on starting
      any long-running unattended turn — validation, implementation, a review,
      closeout, or a discussion step resumed for a turn that applies fixes or
      runs the checks — say so and give `make change-watch CHANGE=<change>`,
      which follows the step in another terminal (55 O2); record each decision,
      its own or the owner's, as D3's line:
      `resolves` the run it settles and no other, `reads` the run whose denials
      it read, `next` the step it directs with `kind` for a review — a confirmed
      return resolves the returned run, a repeat review after a failed gate
      names no run (39 F3); when the script is
      unclassified, decide routing or recovery itself and record an
      `orchestrator` line, or bring the matter to the owner. It commits nothing,
      passes no gate, answers no design question, and advances only its change.
- [x] 6.2 `Makefile`: `make orchestrate CHANGE=<change>`, after `make design`,
      opening `claude "/change-orchestrate <change>"`.
- [x] 6.3 Verification: `make check-agent-skills`; `make test`; a fresh-context
      read of the skill against D2, D8–D10, D13, D14, and the delta's
      orchestrating-session requirement, recording anything it found. The working
      evidence is section 7.
- [x] 6.4 Bash completion of change names on the workflow targets (55 O3):
      `scripts/completions/make-change.bash`, sourced by the owner from
      `~/.bashrc`, wrapping bash-completion's `make` completion with
      `_init_completion -n =` (bash splits words at `=`) so that `CHANGE=`
      completes from the directories under `openspec/changes/` — from
      `openspec/changes/archive/`, date prefix stripped, when the target on the
      line is `archive-cleanup` — and `KIND=` from the four review kinds, and
      defers to `_make` for everything else; a test in `scripts/tests/` that runs
      bash with `COMP_WORDS` and `COMP_CWORD` set and asserts `COMPREPLY`,
      skipped where bash-completion is not installed; the sourcing line in
      `docs/agents/change-workflow.md` is 8.9's.

Section 6 evidence and handoff. The skill is shared through both
harness links; `make check-agent-skills` passes. The Make target uses the general
change finder so an archived change can resume its closeout review or cleanup.
The completion tests exercise real Bash, its installed word-reassembly helper,
and make completion against fixture directories (library integration, no
application); 11 passed with `uv run --no-project --with pytest pytest -q
scripts/tests/test_make_change_completion.py`. Unlike the plan's assumed `_make`,
this installation uses `_comp_cmd_make`; the wrapper supports either name and
the tests exercise both dispatch paths, the legacy name through an adapter to
the installed implementation. Missing bash-completion skips the suite. End-to-end:
no marker in `e2e-tests/` exercises this section; section 7's pilot remains the
working evidence, including actual push-notification availability and session
relaying. Sourcing instructions remain with 8.9. The scoped citation check now
passes: retired review-tool filenames are explicitly historical names rather
than citations to deleted paths; earlier completed tasks and their history stay
in place. `make -n orchestrate CHANGE=orchestrate-change-workflow` prints the
general change lookup and the expected interactive Claude invocation; it does
not start a session. `bash -n scripts/completions/make-change.bash`,
`make check-comment-hygiene`, `make check-change-index`, `make check-tasks`, and
`openspec validate orchestrate-change-workflow --strict`: passed. Fresh-context
check of the diff against `823d9996`, all untracked files and both links included:
no findings against the required guidance, D2, D8–D10, D13, D14, or the delta;
no overstated evidence claims; nothing to fix or decline. `make test`: passed,
every included suite, with 954 passed in `scripts/tests` (the completion suite's
11 included). `make check-packaging`: passed, including wheel builds, lock,
Python-version, project-layout, and architecture checks. Both commands first
failed because the sandbox mounted the existing uv cache read-only; rerunning
with cache access passed, without changing dependencies or locks. The index
notes now name section 6's pending review; its status stays `in implementation`.
No pilot run, live notification, or discussion resume is claimed here. The
pilot must confirm those behaviours and collect the evidence 7.2 names; all
permanent-documentation promotion remains at 8.9.

## 6a. Ordered models per step and the review on either harness

Delivers D18 and D11's fallback (69 F4, 70 F6): each step runs on its row's ordered
models, never Fable or Astra, with no same-vendor fallback, and the review falls back
from Codex to Claude. Touches `.claude/change-steps.toml`,
`scripts/run_change_step.py`, `scripts/tests/test_run_change_step.py`, and the
`Makefile`'s `review` and `orchestrate` targets. Planned after section 6 against the
design revised after it (design reviews 69 and 70).

- [x] 6a.1 `.claude/change-steps.toml`: every row gains `models`, D18's policy — Opus
      5.5 high for design, triage, implement, and closeout (planning resumes
      design's session and its model); Sonnet 5.5 medium for validate and archive
      cleanup; a `[steps.review]` row, `skill = "change-review"`, models
      `codex gpt-6-sol high` then `claude claude-opus-5-5 high`, its Claude entry
      held read-only (reading, read-only Git, the common read utilities, no edit).
      `load_steps` accepts `models`, requires it, and refuses a row naming a Fable
      or Astra model, two models of one vendor, an entry without a model, or a
      Codex entry on any row but the review (D18).
      Done. The table edit was the orchestrator's, on the owner's word: the step
      table sits under `common`'s `Edit(.claude/**)` deny, which holds this step
      too, so the implementing session's edits of it were denied and it wrote the
      edit out for the owner instead. The edited table has `models` in every row as
      D18 gives them and a `[steps.review]` row (Codex `gpt-6-sol` high, then
      Claude `claude-opus-5-5` high, `deny = ["Edit"]`, no allow of its own, so
      `common`'s reading rules alone). It differs from the proposed one: no header
      paragraph on `models`, plan's comment unchanged, the review row denying only
      `Edit` (the same in effect under `dontAsk`, since nothing else it would deny
      is allowed), and the review row placed between design's comment and
      `[steps.design]`, so that comment now heads the review row — the owner's to
      tidy, since no step may edit the table. `Model` and `StepRules.models`;
      `load_steps` requires `models` and refuses, naming the row, an empty list, an
      entry without a model or with another key, an unknown harness, a Fable or
      Astra model, two entries of one harness (one vendor), and a Codex entry off
      the review row.
- [x] 6a.2 The wrapper runs a step's first available entry, passing `--model` and
      `--effort` to `claude -p`, and records `model` and `effort` on the line. An
      entry is unavailable when its program is missing, it is not signed in, or it
      reports a usage limit; the wrapper then tries the next. This replaces the
      fixed `STEP_MODEL` (`claude-opus-5-5`) the orchestrator added to
      `claude_command` before this round, on the owner's word, so the round itself
      would not run on the account's default model. A network error is
      retried twice, then the run ends `stopped` with no fallback. A resume runs
      only on the model the waiting run used, and ends `stopped` with the reset
      time when it is unavailable (D18, 69 F4).
      Done. `STEP_MODEL` is gone; `claude_command` takes the model and passes
      `--model` and `--effort` (Claude Code's `--effort` checked in `claude --help`),
      and takes an optional schema and system prompt. `Wrapper._turn` runs the
      models in order, a fresh `Stream` per attempt into one transcript;
      `unreachable` reads a failed run's result and its non-event output: "hit your
      … limit", "usage limit", "not logged in", "please run /login", "invalid api
      key", or a missing program (`FileNotFoundError`) is unavailable and falls to
      the next model, named under `unavailable` with what it said (a limit's reset
      time with it); a network error ("Can't reach the API server", `EAI_AGAIN`,
      "connection error", …) is retried twice with the same command, then stops the
      run, no fallback; all unavailable stops it, "no model of the step is
      available: …". The patterns are this change's own and the pilot's transcripts'
      (this log's seq 21, the pilot's seq 1 and 17). The line records `harness`,
      `model`, and `effort` — the last model tried even when none ran, with
      `unavailable` saying so, since a resume of that run continues its session on
      that model. `resume`, and planning resuming design, run on the waiting line's
      model (a line from before models were recorded: the row's first). `run` and
      `resume` refuse the review, which runs through `review`. A network retry
      reruns the same command: a fresh run that failed reaching the API left no
      conversation to resume (the pilot's seq 1 and 3).
- [x] 6a.3 The review through the table: `run_change_step.py review` takes its
      models from `[steps.review]`; `REVIEW_MODEL` and `REVIEW_EFFORT` are unset by
      default in the `Makefile` and, when given, override the Codex entry for one
      run. A review on Claude runs `change-review` with the review row's rules and
      no `--json-schema`; its final text passes the same record check and is
      published as Codex's is, its outcome derived the same way. The
      `reviewer-session` marker carries its harness, `codex:` or `claude:`; an
      untagged marker is Codex; a review continues the previous reviewer only on
      the same harness, else starts fresh. The record and the line name the
      reviewer's harness and model (D11, 70 F6).
      Done. `run_review` reads `[steps.review]`; `review_models` replaces only the
      Codex entry with `--model`/`--effort`. Each model is tried in order: Codex
      through the existing runner, its transcript now appended so one log holds
      every attempt, its unavailability read from its own `ERROR` lines only, since
      the rest of its output holds the files the reviewer read; Claude through
      `claude -p` with the review row's rules, no schema, `REVIEW_UNATTENDED`
      appended, its `result` written as the draft and checked as Codex's is. The
      record ends with `reviewer-session: <harness>:<id>`, `reviewer: <harness>
      <model> <effort>`, one `reviewer-unavailable` per model passed over, and
      `reviewed-commit`; `tagged_session` reads an untagged marker as Codex.
      `review_outcome` reads the reviewer back from the markers; a Claude review's
      line also carries `transcript` and `denials` (`transcript_denials`, sharing
      `Stream.take`), so the computation holds it for the denial reading like any
      run; a stopped review's line carries the models passed over and a Claude
      attempt's denials and transcript, through `ReviewError.record`. `Makefile`:
      `REVIEW_MODEL`/`REVIEW_EFFORT` unset by default, the `review` help text.
- [x] 6a.4 `make orchestrate` opens the orchestrating session on Opus 5.5 at medium
      effort (D17).
      Done: `claude --model claude-opus-5-5 --effort medium "/change-orchestrate
      <change>"`.
- [x] 6a.5 Verification: unit tests in `scripts/tests/test_run_change_step.py` with
      the injected runner — the loader's refusals; entry selection and fallback on
      each unavailability signal; two network retries then `stopped`; resume
      refused on another model; a Claude review without the schema, published and
      tagged; an untagged marker resumed on Codex; `REVIEW_MODEL` overriding only
      the Codex entry. `uv run --no-project --with pytest pytest -q scripts/tests`;
      `make test`. No end-to-end scenario covers it (contributor tooling).
      Unit (`test_run_change_step.py`, fake runners): the policy as the table gives
      it; the review row only reads; each loader refusal naming the row; each Claude
      unavailability signal stopping a one-model step; the reset time on the line;
      fallback from an unavailable model to the next, on the wrapper's turn with two
      Claude models given directly, since the loader admits one Claude model per
      row and a step's fallback is otherwise unreachable today; two network
      retries then `stopped`, and a retry that runs; an ordinary failure not read
      as unavailability; resume and planning on the waiting line's model, a line
      from before models on the row's first, a resume whose model (not the row's
      first) is at its limit trying that model alone; the Codex entry and its
      override; Codex missing, not signed in, or at its limit falling back to
      Claude, published and tagged, no schema, the review row's rules; a Claude
      review's denials, on a published line and a stopped one; a reviewer's output
      quoting "usage limit" not read as Codex unavailable; a Claude reviewer
      continued only by Claude; no reviewer available, naming each model; a
      review's network error retried, no fallback; an untagged marker resumed in
      Codex; `make review` with and without the override; `make orchestrate`.
      Results: `test_run_change_step.py` 242 passed against the edited table, then
      245 after the fresh-context fixes; `make test` passed, every suite
      (`scripts/tests` 988), before those fixes, which touched only
      `run_change_step.py` and its test; `make test-release-tooling` (all of
      `scripts/tests`) 991 passed after them. `make check-packaging`,
      `make check-comment-hygiene` (after three test strings were built from a
      variable), `make check-tasks`: passed. End-to-end: none, as the preamble says.

Section 6a evidence and handoff. The implementing session first stopped here: the
table edit was denied to it, and it wrote the edit out as
`reviews/proposed-change-steps.toml` with `reviews/test_with_proposed_table.py`, a
scaffold running this test module against it (242 passed). Both files are still in
the change's untracked `reviews/`, its `rm` of them denied; the owner may delete
them. Fresh-context check of the diff against `20095e00` (a subagent, read-only):
no layering, comment, test-level, or packaging breach; fixed what it found — a
Codex failure read as unavailable from file contents in its output (now its
`ERROR` lines only), a stopped review's line missing the models passed over and a
Claude attempt's denials, the step fallback untested and the "tries no other" test
proving nothing (both rewritten, above), a docstring's wrapping, a test's name,
and this note, stale once the table landed; it also found `docs/agents/
change-workflow.md`'s `make review` paragraph (Codex only, `REVIEW_MODEL`
choosing the reviewer) now wrong, added to 8.9. Declined: omitting the model from
a line where none ran (a resume continues on it, as 6a.2 says); the table's
placement and wording (the owner's, above). Until 6d.6, `change-review`'s
"Running unattended" still says reviews run in Codex, which a Claude reviewer
reads beside `REVIEW_UNATTENDED`.

Fixes at the fifth round's triage (review 77, the owner's notes 74). **77 F1:**
`common` denies `Bash(git diff* --output*)`, `Bash(git show* --output*)`, and
`Bash(git log* --output*)`, since the diff family writes its output to a file
with `--output` and the prefix rules allowed it (the triage session ran `git diff
--output=/dev/null` undenied); the table edit was the orchestrator's, committed
with the fix. D6 and D11 say so. **77 F3 / 74 O1:** `REVIEW_MODEL` and
`REVIEW_EFFORT` are the owner's override for a review run by hand, outside the
table's policy on purpose: `review_models` returns the named model alone, its
harness read from its name (`claude-` on Claude, any other on Codex), its effort
the one given or the table's for that harness, with no fallback; an effort alone
replaces every entry's. The record gains `<!-- reviewer-override: owner -->` and
the line `override: true`, a stopped line too; `change-orchestrate` never sets
either; the `Makefile` comment and help, the `review` subcommand's help,
`docs/agents/change-workflow.md`, D11, D18, the proposal, and the delta's "ordered
models" requirement with a scenario say so. Verification (unit,
`test_run_change_step.py`, fake runners): the owner's model replacing the row for
both harnesses and an effort alone; a review on the owner's Fable model recorded
as an override; a review on the row's models carrying none; the owner's
unavailable model with no fallback; `make review` passing the owner's model; no
step allowed the diff family's `--output`; every step allowed `make change-cost`.
Results are in the round's evidence under 6d.

## 6b. Every run records its cost

Delivers D19 (69 F6, 70 F7): each log line's model, cost, gap, and cache hit, and
`make change-cost`. Touches `scripts/run_change_step.py`, a new
`scripts/change_cost.py` and its test, and the `Makefile`.

- [x] 6b.1 The wrapper writes `cost` on every Claude run's line: tokens, turns, and
      duration summed over the run's `result` events; dollars from the last event
      less the total on the session's last logged run, marked `usd_partial` when
      the previous run had no result or the session's conversation file gained
      turns the wrapper did not run; `gap_s` since the session's last turn of any
      kind; `cache_hit` from the first turn's cache read. A Codex review's line
      records the tokens it reports (D19).
      Done. `run_cost` sums `usage` tokens (input, output, cache read, cache
      creation), `num_turns`, and `duration_ms` over the result events of every
      attempt of the run (a network retry's spent turns included), and takes
      `usd` as the last `total_cost_usd` less the session's last logged
      `session_usd`; `measured_before` and `measured_cost` decide `usd_partial`
      (the session's last line left no `session_usd` — a crash, or a line from
      before costs — or its conversation file holds more user and assistant turns
      than that line's `entries`), `gap_s` (from the conversation file's last
      `timestamp`, else the last line's `at`), and `cache_hit` (the first
      assistant event's `cache_read_input_tokens` above 0), the last two on
      resumed runs only. The conversation file is
      `~/.claude/projects/<root, every non-alphanumeric a dash>/<session>.jsonl`
      (`conversation_file`, the `Wrapper.conversation` seam), the layout this
      machine's sessions show. `cost` also keeps `session_usd` and `entries` as
      the next run's reference, named as such in the module docstring; a run
      that reached no model, its conversation unchanged, carries `session_usd`
      forward so the next run is not marked partial. A review's line: a Codex
      run's `{"tokens": …}`, summed over the attempts its transcript holds; a
      Claude run measured as a step is, a continued reviewer's `gap_s` from the
      log alone (its conversation file already holds the run's turns); a stopped
      review that ran records its cost too.
- [x] 6b.2 `scripts/change_cost.py` and `make change-cost CHANGE=<change>`: totals
      by step and by round — a line's round is the `round` line in force, lines
      before any are design and planning, lines from the first pre-closeout review
      on are closeout — partial dollars as a range, and the cache misses with
      their gaps (D19, 70 F7).
      Done, with a third grouping D19 asks for, by cache — session openings,
      resumed runs that missed, resumed runs that read it — so openings, misses,
      and warm turns can be told apart. The closeout bucket starts at the first
      pre-closeout review that finished, not one refused before it ran. Partial
      dollars show as `$low–$high`, low without the partial runs. The target is
      added to `.PHONY` with `change-next` and `change-watch`, which replace a
      stale `next` there.
- [x] 6b.3 Verification: unit tests over fake streams — a resumed run's dollars
      differenced, its tokens not; two result events summed; a crashed predecessor
      and an unlogged turn marking `usd_partial`; the gap after a takeover; the
      report's buckets and miss list over a fixture log.
      `uv run --no-project --with pytest pytest -q scripts/tests`; `make test`.
      No end-to-end scenario covers it.
      Unit (`test_run_change_step.py`, fake streams and an injected conversation
      directory): a fresh run's cost is its session's total; a resumed run's
      dollars differenced, its tokens its own, its cache hit; two result events
      summed; a crashed predecessor and turns the wrapper did not run marking
      `usd_partial`, the second with the gap after the takeover and a cache miss;
      the gap from the log without a conversation file; a run that reached no
      model leaving the total as it was; a network retry's turns counted; a Codex
      review's tokens, a rejected one's too; a Claude review's cost, and a
      continued Claude reviewer's dollars, gap, and cache hit; `make change-cost`.
      Unit (`test_change_cost.py`, fixture logs): bucketing by the round in force,
      a refused pre-closeout review not starting closeout; the totals by step,
      round, and cache, partial dollars as a range; the miss list; a log without
      costs; the command. Results: the two suites 259 passed before the
      fresh-context check, 263 after; `make test` passed, every suite
      (`scripts/tests` 1005), before its fixes, which touched only
      `run_change_step.py`, `change_cost.py`, and their tests; `make
      test-release-tooling` (all of `scripts/tests`) 1009 passed after them.
      `make check-comment-hygiene`: passed. End-to-end: none, as the preamble
      says. Not run: `make change-cost` on this change, denied to this session;
      its lines before this section carry no `cost`, so it would report none.

Section 6b handoff. Fresh-context check of the diff against `1fa58ac5` (a
subagent, read-only): no guidance breach; fixed what it found — a refused
pre-closeout review starting the closeout bucket; a stopped review recording no
cost; a continued Claude reviewer recorded without `gap_s`; a run that reached no
model marking its successor partial; tokens of retried attempts and of earlier
Codex attempts dropped; the report not separating openings, misses, and warm turns;
`session_usd` and `entries` undocumented. Declined: recording a Claude attempt's
spend when a review falls back from Claude to Codex — the review row puts Codex
first, so Claude never runs before Codex. Dollars of a fresh run retried after a
network error are the last attempt's session total only, each attempt being its
own session; the tokens and turns of all attempts are counted. The cost figures
are the harness's list prices (`costBasis` in the result's `modelUsage`), not an
invoice.

Fix at the fifth round's triage (**74 O3 / R4**): every step may run `make
change-cost`, by the orchestrator's edit of `common`'s allow (`Bash(make
change-cost*)`) on the owner's grant, committed with the fix; D6 names it.

## 6c. Advancing on conditions: `## Next`, rounds from the plan, and the branch decision

Delivers D16's routing, D14's advance conditions, D13's round mapping, and D15's
recorded branch decision (69 F1, F2, F7; 70 F1, F5, F9). Touches
`.agents/change-outcome.schema.json`, `scripts/change_next_step.py`,
`scripts/run_change_step.py`, and their tests.

- [x] 6c.1 The outcome schema: a `finished` plan outcome may carry `rounds`, a list
      of rounds, each a list of sessions, each a list of section ids (D13). The
      wrapper logs it on the plan's line.
      Done: `rounds`, three nested arrays of at least one item, each id an integer
      or a non-empty string (`anyOf`, nested, which `harness_schema` keeps: only a
      top-level combinator is refused). The wrapper's validator gains `anyOf` and
      `minItems`; the outcome's fields are logged as they are, so the plan's line
      carries it. Not confirmed against Claude Code: that `--json-schema` accepts a
      nested `anyOf` and `minItems` — the first unattended plan run shows it.
- [x] 6c.2 `## Next`: the computation reads a review's triage file's `## Next`
      token, `Advance` or `Another round`; a review triage file without one is a
      triage in progress; validation and owner-notes triage files are not routed
      on; a legacy `## Gate` beginning `Passed` reads as `Advance`, any other goes
      to the owner (D16, 69 F2).
      Done: `Record.next_token` reads the bare `## Next` heading (`## Next:
      Advance` on one line too, `## Next round` not), any other first words going
      to the owner (`not_advancing`). Two reviews triaged together may carry the
      token in one file only: `governing` takes the latest review, or, while its
      triage has no `## Next`, an earlier review whose triage file was written
      after the latest was published; an earlier round's review never governs.
- [x] 6c.3 The advance conditions (D14): a design triage's `Advance` names
      planning; an implementation round's names validation of the fix commit, then
      the next planned round or, after the last, the pre-closeout review, only on a
      `passed` validation naming the round's final commit, an `inconclusive` one
      naming the owner; a pre-closeout triage's names closeout once validation of
      `HEAD` passed; a closeout triage's names archive cleanup, after a passed
      validation of `HEAD` when `HEAD` differs from the reviewed commit in a path
      outside `openspec/` and `docs/` (`.agents/` and `.claude/` outside); `Another
      round` names the review of the same kind, after the fix commit's validation
      for implementation and pre-closeout. The gate rules these replace are removed.
      Done. `validated` names validation when the latest record describes another
      commit (an ancestor differing only in records clears it, as before) and the
      owner when it describes `HEAD` without `passed`, `inconclusive` included;
      `validation_problem` gains `require_passed` and the wrapper module
      `latest_validation` and `validation_result` for it. Another round
      (`another_round`) validates only a fix committed since the reviewed commit
      (`fixed_since`, kept), so with no fix the review runs again whatever the
      validation said. A round's untriaged validation that passed or was
      inconclusive opens no triage on its own (`needs_no_triage`), though a
      triage opened for the round's other records lists it. Closeout measures
      "a path outside `openspec/` and `docs/`" from the first closeout review's
      reviewed commit, the archive, so a code fix an earlier closeout round
      committed is validated even when the latest review read it. A plan that
      finished but left the change `in planning` goes to the owner. The pending
      reading's closeout steps include validation.
- [x] 6c.4 Rounds (D13, 70 F1): the governing plan line is the latest `finished`
      plan line; the next round is the first of its `rounds` with a section
      `tasks.md` shows incomplete; the computation's result names that round's
      sessions for the orchestrator to record `by: plan` as it starts. With no
      `rounds`, or an incomplete section in no planned round, it names the owner.
      Done: `next_round` returns `{"step": "round", "sections": <sessions>, "by":
      "plan"}`; the owner is named when the latest plan line has no `rounds` or
      the first open section is in no planned round, the delta's wording (a later
      unmapped section does not hold a mapped round). A closeout section a plan
      maps is left out of the round, and a recorded round naming one is not held
      open by it.
- [x] 6c.5 The branch decision (D15, 70 F4): `note … orchestrator` accepts `--branch`
      and `--change`, recorded on the line; `run_change_step.py log` can filter for
      it, so a branch check can find the line naming the checked-out branch.
      Done: `note_orchestrator(branch=, change=)` requires both and `by: owner`;
      the command's `--change` defaults to the log's own change, where steps
      look; `log <change> --branch <branch>` prints only the owner's decisions
      naming that branch and change (`branch_decisions`).
- [x] 6c.6 Verification: unit tests in `scripts/tests/test_change_next_step.py` over
      fixture changes — each delta scenario added by the revision: a triage
      without `## Next`; a legacy `Passed` gate; an implementation round advancing
      through validation; an inconclusive validation; a closeout correction
      awaiting validation and a documentation correction not; another round with
      and without a fix; a two-round plan mapped and its second round named only
      after the first advanced; an amended plan; no mapping naming the owner — and
      in `test_run_change_step.py`, the schema's `rounds` and the note's branch
      fields. `uv run --no-project --with pytest pytest -q scripts/tests`;
      `make test`; `make check-tasks CHANGE=orchestrate-change-workflow`. No
      end-to-end scenario covers it.
      Unit (`test_change_next_step.py`, fixture changes; `test_run_change_step.py`):
      each scenario the task names — a triage without `## Next` (design, closeout);
      a legacy `Passed` gate and a legacy gate not passed (design, pre-closeout,
      closeout); a design triage's three tokens; a token on the heading line; an
      implementation round advancing through its fix commit's validation to the
      next planned round, and the last to the pre-closeout review; an
      inconclusive validation, with and without a round; a pre-closeout `Advance`
      validated then closeout; a closeout correction awaiting validation (an
      `.agents/` path) and a documentation one not; another round with a fix
      (implementation, pre-closeout) and without one (an inconclusive
      validation not holding it); a closeout round's code fix validated before
      cleanup; a two-round plan whose second round is named only after the first
      advanced; an amended plan; a first open section unmapped and a later one
      not holding a mapped round; a closeout section mapped; `## Next round`
      not read as `## Next`; two reviews triaged together; an earlier round's
      token not deciding a triage in progress — and the schema's `rounds` and
      their refusals, and the branch decision recorded, found, defaulted, and
      refused. Results: the focused suites 381 passed before the fresh-context
      check, 389 after; `make test` passed every suite but `scripts/tests` before
      the check's fixes, whose one failure was a test the fixes rewrote, the edit
      landing during the run; `make test-release-tooling` (all of `scripts/tests`)
      1047 passed after them. `make check-comment-hygiene`, `make check-tasks`,
      `make check-packaging`: passed. By hand,
      `python3 scripts/change_next_step.py` on this change: the owner, for this
      session's own stopped run at seq 76, which this resumed run supersedes; on
      the pilot: its triage's question at seq 55. End-to-end: none.

Section 6c handoff. Fresh-context check of the diff against `615cbf43` (a
subagent, read-only): no guidance breach; fixed what it found — a closeout round's
code fix reaching archive cleanup unvalidated; `## Next round` read as `## Next`;
two reviews triaged together stuck in progress; another round with no fix held by
a validation that did not pass; an unmapped later section holding a mapped round;
a mapped closeout section looping; an inconclusive validation with no round
re-validating forever; a docstring's gate wording and wrapping; a misfiled branch
decision (now defaulted to the log's change); `last_entries` unused by `main`;
unused test constants and a duplicate test. Declined: a decision line that
accepts an inconclusive validation — a passing validation is what clears it, and
the owner result says so. `scripts/check_change_index.py`'s docstring, which
spoke of triage "at a phase-closing gate", now speaks of a phase-closing review's
triage that advances. Left for the next triage: `scripts/find_change.py`'s
docstring cites the requirement "Phases and owner gates", which the archive
renames "Phases and owner touchpoints"; it resolves until then, and it is code,
which closeout does not edit, so it is reworded in implementation, by the round
after this one, or at the triage.

Fixes at the fifth round's triage. **77 F2:** `next_round` sends a planned round
naming a section the task list lacks to the owner before anything is recorded,
since a round line naming it would leave the round unclassifiable, and leaves a
complete section out of its round as it does the closeout section. **74 R3:** a
round noted as it starts records `commit`, `HEAD` then (`note_round`'s `commit`,
none for a round given `--after`), and `round_view.py start` with no base takes
the latest round line's commit, falling back to the latest triaged validation for
a line that names none; this change's two round lines name none. D9 and the
script's docstring say so. Verification (unit, `test_change_next_step.py`): a
round naming a missing section going to the owner with no `round`; a complete
section left out. Unit (`test_run_change_step.py`): `note round` in a Git
repository recording `HEAD`, and none with `--after`. Repository level
(`test_round_view.py`, real Git): the base taken from the latest round line past
a commit landed between rounds, and the fallback when the latest line names none.
Results are in the round's evidence under 6d.

## 6d. The skills: touchpoints, relaying without judging, and the cadence

Delivers D12's skill changes for D8, D13, D15, D16, and D17 (69 F3, F5; 70 F2, F3,
F4). Touches `.agents/skills/` (`change-design`, `change-plan`, `change-triage`,
`change-closeout`, `change-archive-cleanup`, `change-implement`, `change-validate`,
`change-review`, `change-orchestrate`).

- [x] 6d.1 `change-design`: the discussion settles the implementation cadence and
      records it in `design.md` in terms of the work; its handoff describes the
      advance, not a gate (D13, D16).
      Done: a bullet of section 5 (settled with the owner like any decision,
      recommended from the work's slices and risk), a line of section 6 recording
      it, and section 7's handoff naming `## Next`.
- [x] 6d.2 `change-plan`: asks nothing; orders sections by the design's cadence and
      reports the mapping as `rounds` in its outcome, never in `tasks.md`; a plan
      that cannot cut the work that way, or needs any decision, ends `returned` to
      design; its hand-off sets `ready for implementation` itself (D8, D13, G1a).
      Done: the description, opening, and "Running unattended" (no question, its
      discussion bullet removed, `finished` carrying `rounds`, a failed entry check
      `stopped`); the entry check reads the design triage's `## Next`; sections
      ordered by the cadence, a cadence the sections cannot be cut to returned to
      design, and a design recording none — one from before the cadence was a
      decision — planned without a mapping, so the owner is asked per round
      (D13); section 6 a report, not a presentation, an interactive redirection
      of the order or rounds being the design's; section 7 sets the status and
      gives the mapping's form.
- [x] 6d.3 `change-triage`: ends with `## Next` in place of the gate, with the token
      first; asks, once every finding and owner-notes point is disposed and before
      any fix, whether another round is merited, recommending from what the fixes
      will change; records `Advance` itself only with nothing to dispose of; the
      evidence files' closing line names the review's triage file (D16).
      Done: the template's `## Next`, written last, after the fix commit, so the
      computation never routes past uncommitted fixes, and the same in each
      review's triage file when two are triaged together; section 5 asks step 6's
      question first; section 6, "Advance, or another round", the recommendation
      from what the fixes change, `Advance — nothing to dispose of` with nothing
      to dispose of, what the computation does with each token, and the status
      table keyed to an advancing triage. Beyond the task: the orchestrating
      session's `NN-orchestrator.md` record is an input triaged like the owner's
      notes; a lone re-validation is triaged only for its `V<n>`, asks for no
      notes, and names the earlier review's triage; an unattended closeout
      triage's code fix is a `question`, not a return to implementation, since
      the change is archived and implementation refuses it.
- [x] 6d.4 `change-closeout` and `change-archive-cleanup`: their entry checks read
      the latest pre-closeout or closeout triage's `## Next` beginning `Advance`,
      a legacy `Passed` gate read the same (70 F4).
      Done, and wording elsewhere in both from gates to advancing. Closeout also
      accepts a row still `in implementation` whose pre-closeout triage advanced
      before its fix commit was validated, once that validation passed, since the
      triage could not set `ready for closeout` then. Archive cleanup also checks
      the validation the computation requires of a correction outside
      `openspec/` and `docs/` since the archive, for a run started by hand.
- [x] 6d.5 The branch checks of `change-implement`, `change-triage`,
      `change-validate`, `change-closeout`, and `change-archive-cleanup` accept a
      branch that is not the change's own when the change's log holds the owner's
      branch decision naming the checked-out branch (D15, 70 F4).
      Done: each runs `git branch --show-current`, then `python3
      scripts/run_change_step.py log <change> --branch <that branch>`, one
      command per call, both allowed to every step by `common`.
- [x] 6d.6 `change-review`: its "Running unattended" covers Claude as well as
      Codex, its final message the review either way (D11).
- [x] 6d.7 `change-orchestrate`: relays each message as written and forms no view of
      a finding or design question, reading only the computation and its inputs,
      the log, and the denials report; records each planned round `by: plan` as it
      starts, asking the owner only for a change with no mapping; drops the round
      discussion and the gate relay; gives `make change-watch` for each
      long-running turn; reports a fallback to another model and a run's cost when
      it reports the run; writes its own observations of the tooling as a numbered
      record for the next triage (D7, D13, D16, D17, D18, D19).
      Done: the description and opening (relays and routes, what it reads, what
      it adds to a message); the branch decision and how steps find it; the
      `round` step recorded `by: plan`; model, fallback, and cost reported from
      the line; a fresh planning session only on the owner's asking; the relay
      without a position or a gate; the owner asked for a round only when the
      computation names them; "Report what only you see", `NN-orchestrator.md`.
      Also `change-implement`'s opening and report name the cadence and
      `## Next`.
- [x] 6d.8 Verification: `make check-agent-skills`; a fresh-context read of each
      changed skill against D8, D12, D13, D15, D16, D17 and the delta's
      "Phases and owner touchpoints", "Discussion steps stay conversations with
      the owner", and "An orchestrating session advances one change"; `make test`.
      No end-to-end scenario covers it.
      `make check-agent-skills`, `make check-doc-citations`, `make
      check-comment-hygiene`: passed. Fresh-context read (a subagent, read-only,
      the diff against `615cbf43` with the 6c scripts as the behaviour
      described): no leftover gate, plan acceptance, round agreement with a
      mapping, or orchestrator view of a finding; no history or bad citation; the
      branch check's commands allowed by `common`. Fixed what it found: planning's
      discussion bullet and a failed entry check read as questions; a design with
      no cadence returned to design, where D13 asks the owner per round; an
      interactive plan's mapping no step reads; an unattended plan redirected
      after it finished; archive cleanup missing the closeout correction's
      validation; an unattended closeout triage returning an archived change to
      implementation; validation's `next` always naming triage; the
      orchestrator's record unknown to triage; a lone re-validation's closing
      line and notes; `## Next` written before the fix commit; a closeout
      triage's "stop" read as a question; a progress file read as a transcript.
      Declined: limiting the orchestrator's start to its skill and the
      computation's contract — `AGENTS.md` and its documents are repository
      rules, not a change's documents or a finding, which D17 bars.
      `make test`: passed, every suite (`scripts/tests` 1047), after the read's
      fixes. `make check-tasks`, `make check-change-index`: passed. End-to-end:
      none, as the preamble says.

Section 6d handoff. The skills are only text: none of their new paths has run
unattended yet. The first runs on this tooling show whether planning ends
`finished` with `rounds` that `--json-schema` accepts (6c.1's open point), whether
a triage writes `## Next` last and alike in two review files, and whether the
orchestrator records a `round` line `by: plan` from the computation's result. The
two scaffolding files 6a left in this change's `reviews/`
(`proposed-change-steps.toml`, `test_with_proposed_table.py`) stay for the
orchestrating session to remove. `make change-cost` was not then allowed to steps
and was not run (allowed since the fifth round's triage, under 6b); this change's
lines before 6b carry no `cost`. Still owed
outside this round: `scripts/find_change.py`'s citation of "Phases and owner
gates" (6c's handoff), and the table's placement of the review row under
design's comment (6a.1), the owner's to tidy. The session grew large across four
sections and their checks; the next round should start fresh.

Fixes at the fifth round's triage, and the round's fix evidence. **74 R1:** an
edit under `.claude/` is denied to every step, so `change-plan` gives such a task
to the orchestrator, made on the owner's word before its section's session
starts; `change-orchestrate` makes it so, uncommitted; `change-implement` accepts
it in the worktree check, never attempts it, and commits it with the section;
`change-triage` says the same of an accepted fix there. **74 R2:** a denial with
no `reason` met a deny rule — D6a, `change-orchestrate`, the delta's permissions
requirement, and `Stream`'s docstring; the evidence is in 7.2. The round's other
fixes are noted under 6a (77 F1, 77 F3 / 74 O1), 6b (74 O3 / R4), and 6c (77 F2,
74 R3); 74 O2 is section 6e, and 74 O4 / O5 an open question in
`parallel-change-workflows`' proposal. Evidence, over all of them: the focused
suites (`test_run_change_step.py`, `test_change_next_step.py`,
`test_change_cost.py` unit with fake runners; `test_round_view.py` at repository
level, real Git) 435 passed after the compliance check's fixes; `make test`
passed, every suite, before them (`scripts/tests` 1059) and after (1061), and
every check below was rerun after them;
`make check-comment-hygiene` (after one test's record name was built from a
variable), `make check-agent-skills`, `make check-doc-citations
CHANGE=orchestrate-change-workflow`, `make check-tasks
CHANGE=orchestrate-change-workflow`, `make check-change-index`, and `openspec
validate orchestrate-change-workflow --strict`: passed. `openspec validate
parallel-change-workflows --strict` fails as it did before, a proposal with no
deltas. No dependency changed, so no relock or packaging check. Fresh-context
compliance check of the diff against `5be661863` (a subagent, read-only): no
history in comments, no import cycle (`round_view.py` now imports
`run_change_step`, which imports neither it nor the computation); fixed what it
found — the override missing from a stopped line of a review refused before it
ran or interrupted (now set for every line of the run, with a test), three
missing tests (an effort-only override; a refused override; a Codex override
taking the table's effort), `change-implement`'s worktree check refusing the
orchestrator's `.claude/` edit, the delta's permissions and model requirements,
D13 silent on 77 F2, 70 F6's entry and 8.9's two lines stale, 7.2's stale
parenthetical, a missing line in `change-triage`, the round view's docstring
naming a migration rather than `--after`, and overlong lines. Declined: dropping
the space from the `--output` deny rules against a quoted option — the table is
the owner's, the harness's matching of a quoted argument is unverified, and the
pilot's real denial (7.2) decides it.

## 6e. The workflow tooling as a package

Delivers 74 O2: `scripts/run_change_step.py`, grown past two thousand lines holding
the log, the step table, both harnesses, cost, the review runner, and the command
line, becomes a standard-library package structured as the buyer CLIs are — a
`cli.py` dispatching each command to its own module, beside the plumbing they
share — with no change in behaviour. Added at the fifth round's triage and
implemented after the pilot resumes, on the owner's word; the plan maps no round
for it, so the owner is asked for its round (D13). Touches `scripts/`, a new
`scripts/change_workflow/`, `scripts/change_next_step.py`, `scripts/change_cost.py`,
`scripts/round_view.py`, and `scripts/tests/`.

- [x] 6e.1 `scripts/change_workflow/`, standard library only, one module per
      concern: the outcome schema check; the workflow log, its `note` lines, and
      branch decisions; the step table, its models, and their policy; the event
      stream, transcripts, and denials; the Claude and Codex harness runs and
      their unavailability; cost measurement; the wrapper's `run` and `resume`;
      the review runner, its records, and markers; `watch` and the denials
      report; and `cli.py`, dispatching each subcommand to its module.
      `scripts/run_change_step.py` stays as a thin entry point, so the `Makefile`
      targets, the step table's rules naming it (`Bash(python3
      scripts/run_change_step.py log*)`), and the skills are unchanged;
      `change_next_step.py`, `change_cost.py`, and `round_view.py` import from the
      package.
      Done: `common` (the root, steps, kinds, `StepError`, the clock), `outcome`,
      `log` (with `last_run`), `records` (the numbered records, the validation
      record and `validation_problem`, `git_head` and `changed_since`, shared by
      the wrapper, the review, and the computation), `steps`, `stream`,
      `harness` (both commands, both runners, Codex's `Progress`, `unreachable`),
      `cost`, `wrapper`, `review`, `watch` (with the denials report), and `cli`;
      the package docstring lists them. The old module's docstring is shared out
      among `log`, `wrapper`, `review`, `stream`, `cost`, and `outcome`;
      `steps`, `records`, `harness`, `watch`, and `cli` have docstrings written
      for them, `steps`' citing the delta's permissions requirement as the step
      table already does. The definitions moved as they were, apart from three
      structural edits: `cli.main` is split into `_parser()` and `main`, its
      description a constant equal to the old docstring's first line;
      `unreachable`'s return type is the `Reached` alias; and names one module
      now takes from another are public (`utc_now`, `run_claude`, `run_codex`,
      `git_head`, `changed_since`, `NUMBERED`, `tool_summary`, `call_summary`,
      and `_RECORD` renamed `RECORD_PATH`). The imports follow the order
      `common` ← `outcome`, `records`, `steps`, `stream` ← `log`, `harness`,
      `watch` ← `cost` ← `wrapper`, `review` ← `cli`, with no cycle; `log` and
      `review` also import the script module `find_change`, which resolves
      because `scripts/` is on the path whenever the package is.
      `run_change_step.py` is the entry point alone, its `main` the `cli`'s.
- [x] 6e.2 The tests move with the modules they test, unchanged in what they
      assert; a test changed in substance means the move changed behaviour.
      Done: the 182 tests of `test_run_change_step.py` are now
      `test_change_workflow_<module>.py` for `outcome` (11), `log` (24), `steps`
      (17), `stream` (4), `harness` (3), `wrapper` (35), `records` (3), `review`
      (45), `cost` (12), and `watch` (4), and the command line's and the `make`
      targets' 24 stay in `test_run_change_step.py`, beside 6e.3's new `make -n`
      test; 182 before, 182 after.
      Their shared helpers and constants are `scripts/tests/change_workflow_fixtures.py`,
      renamed public (`log_file`, `make_wrapper`, `event_lines`, `review_text`,
      …); `scripts/tests/conftest.py` puts `scripts/` on the path, so tests import
      the package by name. Only references changed: `step.X` became the name
      imported from its module, and a helper's name its public one; no assertion,
      fixture value, or test body otherwise. The compliance check counted 382
      `assert` lines before and after, and the same `pytest.raises` and
      `parametrize` lines. `test_change_next_step.py` and
      `test_change_cost.py` import the log's writers from the package instead of
      `sys.modules["run_change_step"]`, and `change_directory` from
      `find_change`.
- [x] 6e.3 One target for a step's closing checks, added on the owner's word after the
      fifth round: `make check-change CHANGE=<change>` runs
      `check-comment-hygiene`, `check-agent-skills`, `check-doc-citations
      CHANGE=`, `check-tasks CHANGE=`, `check-change-index`, and the pinned
      `openspec validate <change> --strict`, printing only failures and one pass
      line; `change-implement`, `change-triage`, `change-plan`, `change-design`,
      and `change-closeout` name it in place of their separate check lists, and
      each of those steps' rows already allows `Bash(make check-*)`. Each tool call
      replays the session's context — the fifth round's fix turn took 182 turns
      and 21.5M cache-read tokens, about 118k per turn — so six checks as six
      calls cost six replays (D19's data). Verification: a test that the target
      fails when any one check fails and passes when all pass.
      Done: `scripts/check_change.py`, the target's one line. Every check runs
      whatever the others report; a failing one prints its name, command, and
      output, and a last line counts the failures; all passing prints one line.
      The validator is `@fission-ai/openspec@1.14.0` through `bunx` where it is
      installed, else `npx --yes`, since `bunx` is not on every machine; an
      archived change is validated with `--specs --strict`, as closeout and a
      closeout triage validated it. The five skills name it: implementation's
      and triage's checks before committing, planning's plan check, design's
      documents check, and closeout's checks against the promoted state and
      after the archive; their other single checks (closeout's comment-hygiene
      confirmation, its index edit, packaging's `check-agent-skills`) are
      steps of their own and stay. A change with no spec deltas fails the
      validation every time; implementation, triage, and closeout say to take
      that failure as expected. Unit (`test_check_change.py`, a fake runner):
      all six passing print one line naming each, and the runner is given their
      six commands in order; each one failing alone fails, shows only its own
      output, and every check still runs; `npx` without `bunx`; an archived
      change found as archived and validated with `--specs`; an unknown change
      refused before any check; the usage error. `make -n check-change` (in
      `test_run_change_step.py`) shows only that the target's recipe is the
      script, so the target's exit status is the script's by make's own rule,
      not by a test. By hand: `make check-change` on this change and on the
      archived pilot, each one pass line.
- [x] 6e.4 Verification: the moved suites (unit, `scripts/tests`, fake runners;
      `test_round_view.py` at repository level, real Git), each passing with no
      assertion changed; `make test`; `make check-comment-hygiene`; `make
      check-doc-citations CHANGE=orchestrate-change-workflow`, since the change's
      documents cite `scripts/run_change_step.py`; the entry point's commands run
      as before (`python3 scripts/run_change_step.py log <change>`). No end-to-end
      scenario covers it (contributor tooling).
      Unit, `uv run --no-project --with pytest`: the moved suites with
      `test_change_next_step.py`, `test_change_cost.py`, and `test_round_view.py`
      (repository level, real Git) 435 passed, the count the four files they came
      from passed at the fifth round; the computation's, the round view's, and the
      cost suite each pass alone too, so none relies on another file's imports.
      `test_check_change.py` and `test_run_change_step.py` 47 passed. `make test`:
      passed, every suite (`scripts/tests` 1073: 1061 at the fifth round and this
      section's 12 new tests). `make check-change
      CHANGE=orchestrate-change-workflow` — comment hygiene, agent skills,
      citations, tasks, index, strict validation — passed. By hand, `python3
      scripts/run_change_step.py log orchestrate-change-workflow --last 1` printed
      the round line, and `python3 scripts/change_next_step.py
      orchestrate-change-workflow` named section 6e, both through the package.
      `make test` ran before the compliance check's fixes, which touched only two
      skills, `check_change.py`'s docstring, its test, a fixture comment, and the
      change's documents; after them, all of `scripts/tests` 1073 passed, `make
      check-change` passed, and `make check-packaging` passed (no dependency
      changed; run as `AGENTS.md` asks before a commit). End-to-end: none, as the
      preamble says.

Section 6e handoff. Fresh-context compliance check of the diff against
`fd89560b6` (a subagent, read-only, which diffed each moved definition and each
split test against the originals): no behaviour change, no assertion changed, no
function-local import, no history in comments. Fixed what it found: implementation
and triage now run the strict validation through `make check-change`, so both say
a change with no spec deltas fails it every time and that failure is expected
(implementation's "passes at closeout" line, which contradicted closeout, is
gone); `check_change.py`'s docstring said `--specs` checks only the archive's
merges; how `run_checks` finds a change archived was untested (now tested); a
fixture comment had lost "in Codex"; 8.9 did not plan the spec's Evidence list
naming the package and `check_change.py` (added); 6e.3's decision was not in
`design.md` (added under the fifth round's decisions); and the notes above
overstated the docstrings' provenance, the moved code's sameness, the
dependency order, and what 6e.3's tests show (corrected). Declined: dropping
`steps.py`'s citation of the delta's "Unattended runs are held to their step's
permissions" — the step table cites the same requirement, and it resolves once
the archive merges the delta, as the package's own citation does. For the next
session: tests now import scripts by name through `scripts/tests/conftest.py`,
which a new script's test may do too; the older tests still load modules by file,
and both work side by side. Steps' rules for `make check-*` already admit
`make check-change`; the review row admits only its three named checks, so a
Claude reviewer cannot run it, which is as intended, since it would run the
validator. This session stayed moderate in size; the pilot (7) can start fresh.

## 7. Pilot

Delivers D15's evidence: `fix-resource-pool-provider-at-creation` worked by the
orchestrator from `ready for design` through archive cleanup on this branch. The
pilot's own design, plan, reviews, and archive belong to that change; this
section records what they showed about the orchestrator.

- [ ] 7.1 Run `make orchestrate CHANGE=fix-resource-pool-provider-at-creation`
      through every step to archive cleanup, on whatever tooling is committed when
      the pilot resumes, the owner's branch decision recorded once (D15, 69 F8,
      70 F10). Replanned against the revised design: the per-step branch
      confirmation is replaced by that one decision.
- [ ] 7.2 Record here the evidence `design.md`'s Pilot section names: every
      `stopped` outcome and its denials, every `orchestrator` line and the state
      the script could not classify, the relay's latency in the design
      discussion, whether validation's background fetch survived a question,
      whether `--resume` applied a granted rule, and the `reason` value a denial
      by a deny rule records; for each item, which flow produced it — the
      hand-relayed Codex tasks, the section-6 tooling, or the revised tooling (69 F8).
      Recorded so far: a deny-rule denial records no reason at all — the round of
      6a–6d's eight `Edit(.claude/**)` denials carry none beside a `mode` denial
      in the same run (this log's seq 76, read at seq 77; 74 R2), revised
      tooling; D6a and `change-orchestrate` now read a denial with no reason as a
      deny-rule match. Owed by the pilot: a real denial of `git diff --output=…`
      by `common`'s deny rule (77 F1), which no step can provoke from a test,
      and of the quoted `git diff HEAD '--output=x'`, which the rule's space
      before `--output` may let through if the harness matches the command as
      typed; if it does, the rule drops the space.
- [ ] 7.3 Each allow-list gap the pilot found is a proposed edit to
      `.claude/change-steps.toml`, committed by the owner; each script gap is a
      rule added to `change_next_step.py` with its test; each is noted here.
      Pilot gap (fix-resource-pool-provider-at-creation 34 R1): archival during
      a closeout run moves `reviews/` under the wrapper; the transcript path
      computed before the run then fails, the `FileNotFoundError` is misreported
      as the CLI being unavailable, and the outcome line recreates an active
      directory. Owed: narrow the unavailable classification to launch failures,
      and resolve the change's directory after a closeout run.
- [ ] 7.4 Update `design.md`'s Risks with what the pilot confirmed or disproved.
- [ ] 7.5 From the runs on the revised tooling — the pilot's later steps, this
      change's own remaining rounds — record `make change-cost`'s report, the cache
      misses and their gaps, every fallback to another model, and every step that
      advanced without the owner; these are D16 to D19's evidence and the data the
      design's two open questions wait on.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [ ] 8.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments this change added to `scripts/`; anything to rewrite returns the
      change to implementation.
- [ ] 8.2 Import placement — confirm: no function-local import added in
      `scripts/run_change_step.py`, `scripts/change_next_step.py`, or their tests.
- [ ] 8.3 Documentation compliance: re-check D1–D19, D5a, and D6a against
      `openspec/README.md`'s placement rules.
- [ ] 8.4 Narrative compression of sections 1–7's notes.
- [ ] 8.5 Roadmap currency: record that no goal in `docs/development/ROADMAP.md`
      covers contributor workflow, or update it.
- [ ] 8.6 Campaign index currency: this change's row `in closeout`, under
      independent active changes, with no campaign graph; the pilot's row is its
      own archive cleanup's; `parallel-change-workflows`' `Depends on` is
      unchanged. `make check-change-index`.
- [ ] 8.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=orchestrate-change-workflow`, and `make check-agent-skills`.
- [ ] 8.8 End-to-end pipeline: record a passing run on the closeout commit and its
      scenarios, or an explicit blocker naming its cause and owner. The change's
      own code is contributor tooling the pipeline does not run; the pilot's
      validations are its working evidence.
- [ ] 8.9 Promotion, completing the design-promotion record:
      - `openspec/specs/change-workflow/spec.md` — written by the archive (8.11)
        from the delta: the five added requirements and "Implementation sections
        and sessions" replacing "One implementation section per fresh session".
      - `openspec/specs/change-workflow/architecture.md` — rewrite "Fresh sessions
        are the unit of implementation" as "Sections are slices, sessions are the
        owner's" (D13: a plan is agnostic of sessions and harnesses); add "Steps
        run headless and resume with the owner's answers" (D1, D2, D3, D8), "Routing
        is code, with the model as backstop" (D14, D10, D9's recovery),
        "Restrictions bind unattended runs only" (D6, D12), and "A prerequisite is
        proposed from dev and halts its dependent" (D5, D5a: one change per branch,
        the proposal landing on dev first); add "The owner is interrupted only for
        judgement" (D16: touchpoints replace gates; the cadence a design decision,
        D13), "The orchestrator relays and routes" (D17), "Models are policy, with
        no same-vendor fallback" (D18: the workflow never chooses Fable or Astra;
        the owner's override of a review run by hand may), and "Every run records
        its cost" (D19); update "Current limits" with one change at a time and leaf
        steps on Claude Code only.
      - `openspec/README.md` closeout requirements, part 6, the legend of
        `openspec/changes/README.md` (`archived`, a dependency landing), and the
        Purpose paragraph of `openspec/specs/change-workflow/spec.md` — reworded
        from gates to the triage's `## Next`; the Purpose paragraph by hand, since
        no delta reaches it (69 F11).
      - `docs/agents/change-workflow.md` — the "Skills" table gains
        `change-orchestrate`, `make plan`, `UNATTENDED=1`, `make change-next`,
        `make change-watch`, `make check-tasks`, `make check-change` (6e.3), and
        `make change-cost`; a new
        "Orchestrating a change" section: starting and resuming, stating the
        cadence in a design, following a running step, answering and taking over a
        step, maintaining `.claude/change-steps.toml`'s rules and models, reading
        the cost report, and sourcing the completion script (6.4);
        "The review directory" gains `workflow.jsonl` and the step transcripts;
        the paragraph on `make review` says the review runs on the review row's
        models, Codex then Claude (6a's fresh-context check); its sentence on
        `REVIEW_MODEL` and `REVIEW_EFFORT` as the owner's override was already
        rewritten at the fifth round's triage (77 F3 / 74 O1).
      - `AGENTS.md` "Change workflow" — names `make orchestrate`.
      - `openspec/specs/change-workflow/spec.md` "Evidence" — already repointed
        from `run_change_review.py` (retired) to `run_change_step.py review` in
        section 3, when the script was deleted; record it here. It also gains
        `scripts/change_workflow/`, the package behind that entry point, and
        `make check-change` (`scripts/check_change.py`) (6e).
      - `openspec/specs/README.md` and `docs/development/ARCHITECTURE.md` — no
        change: no new capability or companion, and the workflow is contributor
        process.
- [ ] 8.10 Documentation citations:
      `make check-doc-citations CHANGE=orchestrate-change-workflow`, then
      `openspec validate orchestrate-change-workflow --strict`.
- [ ] 8.11 Archival: `openspec archive orchestrate-change-workflow -y`, merging the
      delta into `openspec/specs/change-workflow/spec.md`. After archive cleanup,
      rename the permanent spec's scenarios "A closeout gate is passed" and "A
      pre-closeout gate is passed" to say the triage advances, which the pinned
      validator refused in the delta (D16).
