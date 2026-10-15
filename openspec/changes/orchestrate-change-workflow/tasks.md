Sections are ordered by what each builds on: the outcome and the log every run
writes; the wrapper that runs a Claude Code step; reviews and the `make` targets
through the wrapper; the next-step computation; the leaf skills' unattended
reporting; the orchestrator; the pilot; closeout. Every script is tested in
`scripts/tests/` with an injected command runner, at unit level, except where a
real Git repository is the lowest level that proves the behaviour. No end-to-end
scenario in `e2e-tests/` covers this change and none is owed: it is contributor
tooling that runs the pipeline, not behaviour the pipeline deploys. The pilot
(section 7) is its end-to-end evidence.

## 1. The outcome schema and the workflow log

Delivers the structured outcome every unattended run ends with and the log the
wrapper alone writes (D3; requirement "Unattended step runs end with a structured
outcome").

- [x] 1.1 Add `scripts/change_outcome.schema.json`: the five outcomes —
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

## 2. Running a Claude Code step through the wrapper

Delivers the headless run, its resume, its permissions, and its event stream (D1,
D6, D7; the wrapper side of D12 and 01 F5; requirements "Unattended step runs end
with a structured outcome" and "Unattended runs are held to their step's
permissions").

- [x] 2.1 Add `scripts/change_steps.toml` with D6's table: each step's skill and
      its allow and deny rules, including design's `git worktree add` from dev and
      edits under that worktree's `openspec/` (D5), and validation's guarded push
      as the only push.
      Done. A `[common]` row adds read-only Git, `find_change.py`, the log
      reader, `make round-view-closed`, and `make check-change-index` to every
      step, and denies `git push`, history rewrites, opening or closing the
      round view, and editing `scripts/change_steps.toml` or `.claude/`, the one
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

## 3. Reviews and the `make` targets through the wrapper

Delivers D11 and D1's unattended targets: the review runner absorbed into the
wrapper, with a run-specific success (01 F4), and `UNATTENDED=1` on every step's
target, with planning's new target (D8).

- [ ] 3.1 Move `scripts/run_change_review.py`'s behaviour into
      `run_change_step.py`'s `review` step: the reviewer-session marker, resuming
      the reviewer's session, the transcript, claiming a numbered record per run
      and removing it when the reviewer fails or its review is invalid, and the
      pre-closeout validation check. The outcome is `finished` naming the record
      this run published and the reviewed commit, otherwise `stopped` with the
      runner's reason; an earlier record never counts. Move
      `scripts/tests/test_run_change_review.py`'s cases to
      `scripts/tests/test_run_change_step.py`, and delete the old script and test
      file. Unit: a failed run beside an existing `01-design.md` logs `stopped`.
- [ ] 3.2 `Makefile`: `make review` and `make design-review` call the wrapper's
      `review` step with their current arguments; `make design`, `make triage`,
      `make implement` (with `SECTION`/`SECTIONS`), `make validate`,
      `make closeout`, and `make archive-cleanup` run the wrapper when
      `UNATTENDED=1` and are unchanged otherwise; add `make plan CHANGE=<change>`
      after `make design`, interactive by default, its unattended form resuming
      the design step's session from the log (D8).
- [ ] 3.3 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`; `make -n` of each target with and without
      `UNATTENDED=1`, recorded here; one real `make review KIND=design` on a
      scratch copy of a change, confirming the record, marker, and outcome line.

## 4. The next-step computation

Delivers `scripts/change_next_step.py` (D14; D5, D5a, D9, D13; 01 F1, F2, F3;
requirements "The next step is computed from the files" and "A design blocked on a
prerequisite halts").

- [ ] 4.1 Read the index row (status, `Depends on`, `Notes`), `reviews/` and their
      triage gates, `tasks.md`'s sections and checks, the log, and
      `round_view.open_view()`; print `{"step": ..., "reason": ...}`, or an
      `unclassified` result naming what it read when no rule applies. The rules
      follow each skill's entry check and handoff: design and its review until the
      gate passes, planning, the round agreement before implementation (D13), the
      agreed sections, the round view, validation and the implementation review
      side by side, triage, pre-closeout, closeout, the closeout review, archive
      cleanup.
- [ ] 4.2 The owner results: a round view open (D9, 01 F3); a prerequisite whose
      directory is not on the branch (D5, 01 F2); a design-gating dependency not
      archived (01 F1); a design-gating dependency archived on this branch, the
      release proposed (D5a); a status that disagrees with the log, where the
      files prevail.
- [ ] 4.3 Tests in `scripts/tests/test_change_next_step.py`: unit, over fixture
      change directories and logs, for every rule and owner result above and an
      unclassifiable state; the round-view case in a temporary Git repository,
      with a view opened by `round_view.start` and closed by `round_view.done`,
      since a real repository is the lowest level that proves it.
- [ ] 4.4 Verification: `uv run pytest -q scripts/tests/test_change_next_step.py`
      (unit, with the temporary repository); `make test`; the script run by hand
      on this change and on the pilot change, its results recorded here.

## 5. The leaf skills report through the wrapper

Delivers D12, D13's skill changes, and D5's design path; the skills' text only, as
D12 limits it.

- [ ] 5.1 Every `change-*` skill under `.agents/skills/` gains how it runs
      unattended: each "stop and ask the owner" ends its turn with a `question`
      outcome; a denied tool ends it `stopped` with its reason, never a question
      or a workaround; its last turn ends with an outcome matching
      `scripts/change_outcome.schema.json`. Discussion steps (design, planning,
      triage) end each reply with its `message`. `change-validate` §5's
      environmental remedy is a `question`; `change-closeout`'s point needing a
      code edit is `returned` to implementation (D8). Interactive use is unchanged.
- [ ] 5.2 `change-plan` sizes a section as a coherent, verifiable slice and drops
      "one section per session" from its description and handoff;
      `change-implement` implements the sections it was given, drops §8's
      question, and keeps the warning about a growing session as advice (D13).
- [ ] 5.3 `change-design` gains the prerequisite path: shape the prerequisite with
      the owner, write it in a worktree on a new branch from dev, end `blocked`;
      after dev is merged in, keep the change `in design` with the dependency
      gating design; on release, drop only the dependency (D5, D5a).
- [ ] 5.4 Verification: `make check-agent-skills`; a fresh-context read of each
      edited skill against D12, recording anything it found.

## 6. The orchestrating session

Delivers `change-orchestrate` (D2, D7's notifications, D8, D9, D10, D13's round
line, D14's backstop, never passing a gate; requirements "An orchestrating
session advances one change" and "Discussion steps stay conversations with the
owner").

- [ ] 6.1 Add `.agents/skills/change-orchestrate/SKILL.md`, linked from
      `.claude/skills/` and `.codex/skills/`: on every start and after compaction,
      run `change_next_step.py` and read the log's last lines; run the step it
      names through the wrapper; relay each discussion message and resume with the
      owner's reply; put each `question` to the owner; bring every gate and
      `returned` proposal to the owner; agree each round and record it with
      `note`; open the round view, save the owner's notes verbatim as the next
      `NN-implementation-owner.md`, then close it; start validation and the
      implementation review side by side; send a push notification on `question`,
      `stopped`, or a long step finishing; read each denial against the step's
      row and propose a grant or a tracked table edit; when the script is
      unclassified, decide routing or recovery itself and record an
      `orchestrator` line, or bring the matter to the owner. It commits nothing,
      passes no gate, answers no design question, and advances only its change.
- [ ] 6.2 `Makefile`: `make orchestrate CHANGE=<change>`, after `make design`,
      opening `claude "/change-orchestrate <change>"`.
- [ ] 6.3 Verification: `make check-agent-skills`; `make test`; a fresh-context
      read of the skill against D2, D8–D10, D13, D14, and the delta's
      orchestrating-session requirement, recording anything it found. The working
      evidence is section 7.

## 7. Pilot

Delivers D15's evidence: `fix-resource-pool-provider-at-creation` worked by the
orchestrator from `ready for design` through archive cleanup on this branch. The
pilot's own design, plan, reviews, and archive belong to that change; this
section records what they showed about the orchestrator.

- [ ] 7.1 Run `make orchestrate CHANGE=fix-resource-pool-provider-at-creation`
      through every step to archive cleanup, the owner confirming each entry
      check's branch mismatch.
- [ ] 7.2 Record here the evidence `design.md`'s Pilot section names: every
      `stopped` outcome and its denials, every `orchestrator` line and the state
      the script could not classify, the relay's latency in the design
      discussion, whether validation's background fetch survived a question, and
      whether `--resume` applied a granted rule.
- [ ] 7.3 Each allow-list gap the pilot found is a proposed edit to
      `scripts/change_steps.toml`, committed by the owner; each script gap is a
      rule added to `change_next_step.py` with its test; each is noted here.
- [ ] 7.4 Update `design.md`'s Risks with what the pilot confirmed or disproved.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [ ] 8.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments this change added to `scripts/`; anything to rewrite returns the
      change to implementation.
- [ ] 8.2 Import placement — confirm: no function-local import added in
      `scripts/run_change_step.py`, `scripts/change_next_step.py`, or their tests.
- [ ] 8.3 Documentation compliance: re-check D1–D15, D5a, and D13 against
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
        the proposal landing on dev first); update "Current limits" with one change
        at a time and gates never passed by the orchestrator.
      - `docs/agents/change-workflow.md` — the "Skills" table gains
        `change-orchestrate`, `make plan`, and `UNATTENDED=1`; a new "Orchestrating
        a change" section: starting and resuming, agreeing a round, answering and
        taking over a step, maintaining `scripts/change_steps.toml`; "The review
        directory" gains `workflow.jsonl` and the step transcripts.
      - `AGENTS.md` "Change workflow" — names `make orchestrate`.
      - `openspec/specs/README.md` and `docs/development/ARCHITECTURE.md` — no
        change: no new capability or companion, and the workflow is contributor
        process.
- [ ] 8.10 Documentation citations:
      `make check-doc-citations CHANGE=orchestrate-change-workflow`, then
      `openspec validate orchestrate-change-workflow --strict`.
- [ ] 8.11 Archival: `openspec archive orchestrate-change-workflow -y`, merging the
      delta into `openspec/specs/change-workflow/spec.md`.
