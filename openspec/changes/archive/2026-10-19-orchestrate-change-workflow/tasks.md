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

Notes record final behaviour, material evidence, deferrals, and destinations;
the rationale behind each fix round is in `design.md`'s decisions under the round
that made it, and what the fresh-context checks raised and a round declined is
under "Declined at the fresh-context compliance checks". Test files are named as
they stand after section 6e split the tooling into `scripts/change_workflow/`.

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
      Done. One object schema, `outcome` and `message` required, an `if`/`then`
      per outcome, `additionalProperties` false, draft-07 (D3); `return_to` is
      design, planning, or implementation; `next` is free text, routing being the
      computation's. The wrapper's own validator handles exactly the schema's
      keywords and raises on any other. Unit (`test_change_workflow_outcome.py`):
      each outcome valid; each required field missing reported; an unknown
      outcome, an undefined field, and a `return_to` that is not earlier refused;
      an unenforceable keyword raises.
- [x] 1.2 Add `scripts/run_change_step.py` with the log's writer and reader: append
      one line to the change's `reviews/workflow.jsonl` with `seq`, `at`, the step,
      its session and commit; read the last lines. Its `note` operation appends the
      orchestrator's `round` (D13) and `orchestrator` (D14) lines, so the wrapper is
      the log's only writer. The change's directory is found through
      `scripts/find_change.py`, so an archived change's log moves with it. Unit:
      `seq` increases across appends and notes, a malformed line is reported with
      its line number rather than skipped, and a note without its required fields
      is refused.
      Done. Appends hold an exclusive `flock` from reading the last `seq` to
      writing, since validation and review append side by side; readers take a
      shared lock. A `round` line carries `sections` (sessions of section ids,
      integers or strings), `by`, `after`, and the round's starting `commit`; an
      `orchestrator` line `by`, `decision`, `reason`, and, as D3, D14, and D15
      give them, `resolves`, `reads`, `next`, `kind`, `branch`, and `change`, each
      refused when malformed. Commands: `note <change> round|orchestrator`, `log
      <change> [--last N] [--branch B]`. Unit (`test_change_workflow_log.py`): as
      the task names, plus a refused line leaving the log unwritten and an
      archived change's log found by name.
- [x] 1.3 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`.
      Focused suite 54 passed (`uv run --no-project --with pytest`, as `make
      test-release-tooling` runs `scripts/`); `make test`, `make check-packaging`,
      `make check-comment-hygiene` passed. End-to-end: none (contributor tooling).

Later fixes to this section — the decision line's fields and refusals (04 F3, 28
F1, 28 F3), a round recorded after the fact (X1), the owner's direction past
archive cleanup's validation (119 F1) — are in `design.md`'s first, second, and
seventh rounds' decisions.

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
      Done. A `[common]` row gives every step read-only Git (the diff family's
      `--output` denied), the read-only utilities and `find` without its writing
      actions, the computation, the log reader, `make round-view-closed`, `make
      check-change-index`, `make change-cost`, and OpenSpec's read commands, and
      denies pushes, history rewrites, the round view, and edits of `.claude/`;
      each step's row is D6's. Record writes take the `Edit(path)` form (29 A1).
      The rules were seeded by the pilot's denials (7.3). Untested: design's
      `git worktree add` and `../*-proposal/` rules, since no design was blocked
      on a prerequisite. Unit (`test_change_workflow_steps.py`): sample commands
      matched against each row; validation alone may push; no step may edit the
      table or `.claude/`; a malformed table refused.
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
      Done. `claude -p "/change-<step> <change>"` with `--setting-sources
      project`, the step's rules, the schema without its top-level `allOf` (D3),
      the step's model and effort (6a), and an appended prompt saying the run is
      unattended; implementation takes `--sections`, planning resumes the design
      session or `--fresh`. A crash, no outcome, an error result, a malformed
      outcome, or a runner that raises is logged `stopped`; an interrupt is
      re-raised after its line is written. Every line carries the run's denials,
      gathered over every turn with the harness's reason, and a run that went on
      past one keeps its own outcome (X2, X3). Unit
      (`test_change_workflow_wrapper.py`).
- [x] 2.3 `run_change_step.py resume <change> --answer <text> [--allow <rule>]`:
      resume the last session of the step with `--resume <id>` and the owner's
      answer, with any rule granted for that one run (D6). Unit: the resumed
      command carries the session and the granted rule, and the next run of the
      step does not.
      Done, with `--seq` mandatory since 45 R1: a run that is not waiting — not
      its step's latest, resolved by a decision line, or ended other than with a
      question or a stop — is refused. The answer is sent as "The owner's answer:
      …"; a grant is recorded on the resumed line. Unit, as the task names.
- [x] 2.4 Event stream and progress (D7): write the stream to
      `reviews/transcripts/NN-<step>.jsonl`, numbered after every record in
      `reviews/` and `reviews/transcripts/`, and a progress file beside it with
      one line per tool call and its time. Unit: the transcript's number follows
      existing records, and the progress file lists the fake stream's tool calls.
      Done: the transcript is claimed by exclusive create and holds every line of
      output; `NN-<step>.progress` holds one `HH:MM:SSZ <tool> <summary>` line per
      tool call; both are held open across an archive (7.3). Unit
      (`test_change_workflow_stream.py`).
- [x] 2.5 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`; one hand run of `run_change_step.py run plan` on a
      scratch copy of a change, recorded here with its outcome line, to confirm the
      `claude -p` flags the unit tests assume.
      Focused suite 105 passed; `make test`, `make check-packaging`, `make
      check-comment-hygiene` passed. Hand runs (Claude Code 2.1.300, this change
      copied into a detached scratch worktree): two runs `stopped` on Claude
      Code's refusal of the schema, which fixed it (D3); then exit 0, the plan
      step ending with its own `stopped` outcome on a denied compound Bash call,
      logged with the stream's `permission_denials`. Confirmed: the flag order,
      `--setting-sources project` accepted, the stream's `session_id`, `result`,
      `structured_output`, `permission_denials`, and `is_error`, and a
      slash-command prompt invoking the skill; `--resume` and a granted rule were
      confirmed by the pilot (7.2). Observed: Claude Code ran commands it classes
      read-only without a rule, and denied a `cd …; for …` compound.

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
      Done; the old script and its test are deleted, their 54 tests moved, and
      the permanent spec's Evidence line repointed to `run_change_step.py review`
      when the script went. `finished` (`next: triage`) names the record, its
      kind, the reviewed commit, and the session, all read from the record's last
      markers; any refusal or failure is `stopped` with `HEAD` as the commit.
      Unit (`test_change_workflow_review.py`).
- [x] 3.2 `Makefile`: `make review` and `make design-review` call the wrapper's
      `review` step with their current arguments; `make design`, `make triage`,
      `make implement` (with `SECTION`/`SECTIONS`), `make validate`,
      `make closeout`, and `make archive-cleanup` run the wrapper when
      `UNATTENDED=1` and are unchanged otherwise; add `make plan CHANGE=<change>`
      after `make design`, interactive by default, its unattended form resuming
      the design step's session from the log (D8).
      Done; `make plan` takes `FRESH=1`, `implement` passes `SECTIONS` else
      `SECTION`, `validate` passes `HELM_ALL_SCENARIOS=1`. Unit (`make -n`, in
      `test_run_change_step.py`): every target's interactive and unattended
      commands.
- [x] 3.3 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`; `make -n` of each target with and without
      `UNATTENDED=1`, recorded here; one real `make review KIND=design` on a
      scratch copy of a change, confirming the record, marker, and outcome line.
      Focused suite 178 passed; `make test`, `make check-packaging`, `make
      check-comment-hygiene` passed; `make -n` of each target as 3.2 describes. A
      real `make review KIND=design` on the scratch worktree: exit 0, the record
      published with its `reviewer-session` and `reviewed-commit` markers, and a
      `finished` line naming it.

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
      Done; the triage gates became `## Next` at 6c. The result's steps are
      `design`, `plan`, `round`, `implement` (with `sections`), `round-view`,
      `validate`, `review` (with `kind`), `validate-and-review`, `triage`,
      `closeout`, `archive-cleanup`, `owner`, `done`, and `unclassified` (with
      what it read). A waiting run holds the change until it is resumed or a
      decision line resolves or reads it, and a directed step routes until it has
      run (D3, D14). The index is read through `check_change_index.index_rows`.
      `make check-comment-hygiene` exempts exactly the `TASKS_FILE` definition
      line, a named rule since 02 O1.
- [x] 4.2 The owner results: a round view open (D9, 01 F3); a prerequisite whose
      directory is not on the branch (D5, 01 F2); a design-gating dependency not
      archived (01 F1); a design-gating dependency archived on this branch, the
      release proposed (D5a); a status that disagrees with the log, where the
      files prevail.
      Done. A dependency holds the change when it gates the current phase or an
      earlier one: no directory here → owner, merge dev; archived here → owner,
      release; otherwise it waits. A blocked design whose prerequisite has
      arrived but is not yet in `Depends on` → design, to record it. A
      disagreement is reported beside the step the files give.
- [x] 4.3 Tests in `scripts/tests/test_change_next_step.py`: unit, over fixture
      change directories and logs, for every rule and owner result above and an
      unclassifiable state; the round-view case in a temporary Git repository,
      with a view opened by `round_view.start` and closed by `round_view.done`,
      since a real repository is the lowest level that proves it.
      Done, as the task names.
- [x] 4.4 Verification: `uv run pytest -q scripts/tests/test_change_next_step.py`
      (unit, with the temporary repository); `make test`; the script run by hand
      on this change and on the pilot change, its results recorded here.
      Focused suite 67 passed; `make test`, `make check-packaging`, `make
      check-comment-hygiene` passed. By hand: this change, the owner for a round
      of sections 5–7; the pilot, design; an archived change, `done`; another
      active change, the owner for a round.

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
      Done as one "Running unattended" section in each skill (D12), naming each
      skill's own ends; `change-plan`'s and `change-implement`'s entry checks
      accept a return the owner confirmed. The denial rule was revised at rounds
      1, 2, and 6 (X3, X5, 28 F1, 103 R3).
- [x] 5.2 `change-plan` sizes a section as a coherent, verifiable slice and drops
      "one section per session" from its description and handoff;
      `change-implement` implements the sections it was given, drops §8's
      question, and keeps the warning about a growing session as advice (D13).
      Done.
- [x] 5.3 `change-design` gains the prerequisite path: shape the prerequisite with
      the owner, write it in a worktree on a new branch from dev, end `blocked`;
      after dev is merged in, keep the change `in design` with the dependency
      gating design; on release, drop only the dependency (D5, D5a).
      Done as "When the design needs another change first", under step 4. Not
      exercised unattended: no design was blocked.
- [x] 5.4 Verification: `make check-agent-skills`; a fresh-context read of each
      edited skill against D12, recording anything it found.
      `make check-agent-skills`, `make check-comment-hygiene`, `make
      check-packaging`, `make test` passed. The read's findings — entry checks
      that accepted no return, stops mapped to the wrong outcome, commands the
      skills call that the table denied — were fixed before commit.

Fix rounds 1–4 (records 02–55; decisions in `design.md` under the first to fourth
rounds): the decision line's `resolves`, `reads`, `next`, and `kind` (04 F3, 28 F1,
28 F3, 52 F1); a confirmed return routed (04 F1); a repeat review after a failed
gate (04 F2); `note round --after` (X1); denials gathered over every turn and kept
on every line (X2, X3); the table's read utilities and record rules (X4, 07 A1, 29
A1); D6a's reading and the `denials` command (X5); the table and schema moved
(02 O2, O3) and `.agents/` citations checked; `make check-comment-hygiene` ported
to `scripts/check_comment_hygiene.py` with the same result before and after (02
O1); `validate_slice.py` printing a line per step (07 A2); validation waiting on a
background part inside one Bash call, with no redirect (29 A2, 41 A1, 54 A1); `make
check-tasks` and the computation's backstop (39 F1); unread denials waiting in any
phase (39 F2); `resume --seq` and `make change-next` (45 R1, 55 O1); `make
change-watch` given on every long unattended turn (55 O2); and task 6.4 (55 O3).
Each round passed its focused suites, `make test`, `make check-comment-hygiene`,
`make check-agent-skills`, `make check-change-index`, `make check-packaging`, and
the strict validation, and a fresh-context check of its diff whose findings were
fixed before commit.

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
      Done; revised by 6d.7 to the revised design (no gates; rounds from the plan).
- [x] 6.2 `Makefile`: `make orchestrate CHANGE=<change>`, after `make design`,
      opening `claude "/change-orchestrate <change>"`.
      Done; it finds the change active or archived, so an archived change's
      closeout review or cleanup can be resumed.
- [x] 6.3 Verification: `make check-agent-skills`; `make test`; a fresh-context
      read of the skill against D2, D8–D10, D13, D14, and the delta's
      orchestrating-session requirement, recording anything it found. The working
      evidence is section 7.
      `make check-agent-skills`, `make check-comment-hygiene`, `make
      check-change-index`, `make check-tasks`, `make check-packaging`, the strict
      validation, and `make test` (`scripts/tests` 954) passed; the read found
      nothing.
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
      Done; it defers to `_make` or the newer `_comp_cmd_make`, both tested. 11
      tests in real Bash (`test_make_change_completion.py`), skipped without
      bash-completion.

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
      Done. The table edit was the orchestrator's, on the owner's word, since no
      step may edit `.claude/`. Deferred to the owner: the review row sits under
      design's comment, which now heads it.
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
      Done. Unavailability is read from a failed run's result and output ("hit
      your … limit", "usage limit", "not logged in", "invalid api key", the
      program missing), with the limit's reset time; a network error reruns the
      same command (D18). The line records the harness, model, and effort, and
      `unavailable` for each model passed over.
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
      Done. Codex's unavailability is read from its `ERROR` lines only, since the
      rest of its output holds the files it read. The record ends with
      `reviewer-session`, `reviewer`, one `reviewer-unavailable` per model passed
      over, and `reviewed-commit`. A Claude review's line carries its transcript
      and denials. Since the fifth round (77 F3 / 74 O1), `REVIEW_MODEL` replaces
      the whole row, on either harness, as the owner's override, marked
      `reviewer-override` on the record and `override: true` on the line.
- [x] 6a.4 `make orchestrate` opens the orchestrating session on Opus 5.5 at medium
      effort (D17).
      Done.
- [x] 6a.5 Verification: unit tests in `scripts/tests/test_run_change_step.py` with
      the injected runner — the loader's refusals; entry selection and fallback on
      each unavailability signal; two network retries then `stopped`; resume
      refused on another model; a Claude review without the schema, published and
      tagged; an untagged marker resumed on Codex; `REVIEW_MODEL` overriding only
      the Codex entry. `uv run --no-project --with pytest pytest -q scripts/tests`;
      `make test`. No end-to-end scenario covers it (contributor tooling).
      Unit (fake runners): as the task names, the fallback on the wrapper's turn
      given two Claude models directly, since the loader admits one per row.
      `scripts/tests` 991 passed; `make test`, `make check-packaging`, `make
      check-comment-hygiene`, `make check-tasks` passed.

Fifth round's fixes to this section: `common` denies the diff family's `--output`
(77 F1); the owner's review override (77 F3 / 74 O1). Decisions in `design.md`.

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
      Done. `cost` also keeps `session_usd` and `entries` as the next run's
      reference; a run that reached no model carries `session_usd` forward. Tokens
      and turns of every attempt count; a fresh run's dollars after a network
      retry are the last attempt's. Reviews record cost on either harness,
      stopped or published.
- [x] 6b.2 `scripts/change_cost.py` and `make change-cost CHANGE=<change>`: totals
      by step and by round — a line's round is the `round` line in force, lines
      before any are design and planning, lines from the first pre-closeout review
      on are closeout — partial dollars as a range, and the cache misses with
      their gaps (D19, 70 F7).
      Done, with a grouping by cache — session openings, misses, warm resumes. The
      closeout bucket starts at the first pre-closeout review that finished. Every
      step may run it (74 O3 / R4).
- [x] 6b.3 Verification: unit tests over fake streams — a resumed run's dollars
      differenced, its tokens not; two result events summed; a crashed predecessor
      and an unlogged turn marking `usd_partial`; the gap after a takeover; the
      report's buckets and miss list over a fixture log.
      `uv run --no-project --with pytest pytest -q scripts/tests`; `make test`.
      No end-to-end scenario covers it.
      Unit (`test_change_workflow_cost.py`, `test_change_cost.py`): as the task
      names. `scripts/tests` 1009 passed; `make test`, `make
      check-comment-hygiene` passed.

## 6c. Advancing on conditions: `## Next`, rounds from the plan, and the branch decision

Delivers D16's routing, D14's advance conditions, D13's round mapping, and D15's
recorded branch decision (69 F1, F2, F7; 70 F1, F5, F9). Touches
`.agents/change-outcome.schema.json`, `scripts/change_next_step.py`,
`scripts/run_change_step.py`, and their tests.

- [x] 6c.1 The outcome schema: a `finished` plan outcome may carry `rounds`, a list
      of rounds, each a list of sessions, each a list of section ids (D13). The
      wrapper logs it on the plan's line.
      Done; the wrapper's validator gains `anyOf` and `minItems`. Claude Code
      accepts the nested schema (7.2).
- [x] 6c.2 `## Next`: the computation reads a review's triage file's `## Next`
      token, `Advance` or `Another round`; a review triage file without one is a
      triage in progress; validation and owner-notes triage files are not routed
      on; a legacy `## Gate` beginning `Passed` reads as `Advance`, any other goes
      to the owner (D16, 69 F2).
      Done. Two reviews triaged together may carry the token in one file only:
      the governing review is the latest, or an earlier one triaged with it.
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
      Done. Closeout measures paths from the first closeout review's commit, so a
      fix an earlier closeout round committed is validated too; another round with
      no fix reruns the review whatever the validation said.
- [x] 6c.4 Rounds (D13, 70 F1): the governing plan line is the latest `finished`
      plan line; the next round is the first of its `rounds` with a section
      `tasks.md` shows incomplete; the computation's result names that round's
      sessions for the orchestrator to record `by: plan` as it starts. With no
      `rounds`, or an incomplete section in no planned round, it names the owner.
      Done. A closeout section or a complete section is left out of its round; a
      round naming a section the list lacks goes to the owner (77 F2); a round
      line records its starting commit, the round view's base (74 R3).
- [x] 6c.5 The branch decision (D15, 70 F4): `note … orchestrator` accepts `--branch`
      and `--change`, recorded on the line; `run_change_step.py log` can filter for
      it, so a branch check can find the line naming the checked-out branch.
      Done: both required, `by: owner` only; `--change` defaults to the log's own.
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
      Unit, as the task names; `test_round_view.py` (real Git) for the round
      view's base. `scripts/tests` 1047 passed; `make test`, `make
      check-comment-hygiene`, `make check-tasks`, `make check-packaging` passed.

## 6d. The skills: touchpoints, relaying without judging, and the cadence

Delivers D12's skill changes for D8, D13, D15, D16, and D17 (69 F3, F5; 70 F2, F3,
F4). Touches `.agents/skills/` (`change-design`, `change-plan`, `change-triage`,
`change-closeout`, `change-archive-cleanup`, `change-implement`, `change-validate`,
`change-review`, `change-orchestrate`).

- [x] 6d.1 `change-design`: the discussion settles the implementation cadence and
      records it in `design.md` in terms of the work; its handoff describes the
      advance, not a gate (D13, D16).
      Done.
- [x] 6d.2 `change-plan`: asks nothing; orders sections by the design's cadence and
      reports the mapping as `rounds` in its outcome, never in `tasks.md`; a plan
      that cannot cut the work that way, or needs any decision, ends `returned` to
      design; its hand-off sets `ready for implementation` itself (D8, D13, G1a).
      Done; a design with no cadence is planned without a mapping, so the owner is
      asked per round (D13).
- [x] 6d.3 `change-triage`: ends with `## Next` in place of the gate, with the token
      first; asks, once every finding and owner-notes point is disposed and before
      any fix, whether another round is merited, recommending from what the fixes
      will change; records `Advance` itself only with nothing to dispose of; the
      evidence files' closing line names the review's triage file (D16).
      Done; `## Next` is written last, after the fix commit. The orchestrating
      session's `NN-orchestrator.md` is triaged like the owner's notes; an
      unattended closeout triage's code fix is a `question`.
- [x] 6d.4 `change-closeout` and `change-archive-cleanup`: their entry checks read
      the latest pre-closeout or closeout triage's `## Next` beginning `Advance`,
      a legacy `Passed` gate read the same (70 F4).
      Done; closeout also accepts a row still `in implementation` whose triage
      advanced before its fix commit was validated, once that validation passed.
- [x] 6d.5 The branch checks of `change-implement`, `change-triage`,
      `change-validate`, `change-closeout`, and `change-archive-cleanup` accept a
      branch that is not the change's own when the change's log holds the owner's
      branch decision naming the checked-out branch (D15, 70 F4).
      Done.
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
      Done; a `.claude/` edit a plan gives is the orchestrator's, made on the
      owner's word before its section's session, which commits it (74 R1).
- [x] 6d.8 Verification: `make check-agent-skills`; a fresh-context read of each
      changed skill against D8, D12, D13, D15, D16, D17 and the delta's
      "Phases and owner touchpoints", "Discussion steps stay conversations with
      the owner", and "An orchestrating session advances one change"; `make test`.
      No end-to-end scenario covers it.
      `make check-agent-skills`, `make check-doc-citations`, `make
      check-comment-hygiene`, `make check-tasks`, `make check-change-index`, and
      `make test` (`scripts/tests` 1047) passed; the read's findings were fixed.

Fifth round's checks, over 6a–6d and their fixes (review 77, owner's notes 74,
validation 78): `scripts/tests` 1061 and every `make test` suite passed; `make
check-comment-hygiene`, `make check-agent-skills`, `make check-doc-citations`, `make
check-tasks`, `make check-change-index`, and the strict validation passed.

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
      Done: `common`, `outcome`, `log`, `records`, `steps`, `stream`, `harness`,
      `cost`, `wrapper`, `review`, `watch`, and `cli`, listed in the package
      docstring, importing one another without a cycle; definitions moved as they
      were, apart from `cli.main`'s split and names made public where another
      module uses them.
- [x] 6e.2 The tests move with the modules they test, unchanged in what they
      assert; a test changed in substance means the move changed behaviour.
      Done: 182 tests before and after, in `test_change_workflow_<module>.py`
      and `test_run_change_step.py`, with shared fixtures in
      `scripts/tests/change_workflow_fixtures.py` and `scripts/tests/conftest.py`
      putting `scripts/` on the path; only references changed (382 `assert` lines
      before and after).
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
      Done: `scripts/check_change.py`. Every check runs whatever the others
      report; the validator runs through `bunx`, else `npx --yes`; an archived
      change is validated with `--specs --strict`. A change with no spec deltas
      fails the validation every time, which the skills take as expected. Unit
      (`test_check_change.py`, a fake runner): as the task names.
- [x] 6e.4 Verification: the moved suites (unit, `scripts/tests`, fake runners;
      `test_round_view.py` at repository level, real Git), each passing with no
      assertion changed; `make test`; `make check-comment-hygiene`; `make
      check-doc-citations CHANGE=orchestrate-change-workflow`, since the change's
      documents cite `scripts/run_change_step.py`; the entry point's commands run
      as before (`python3 scripts/run_change_step.py log <change>`). No end-to-end
      scenario covers it (contributor tooling).
      The moved suites 435 passed, as before the move; `make test`
      (`scripts/tests` 1073), `make check-change`, and `make check-packaging`
      passed; the entry point's `log` and the computation ran through the
      package.

Sixth round's fixes (review 101, validation 102, observations 103; decisions in
`design.md`): a review continues the latest reviewer of its kind by number (101
F1); a step's `stopped` outcome checked with the run's denials in it, its message
kept (103 R4); a substitute after a `mode` denial (103 R3). 102 V1, an e2e-vm
failure in the buyer CLI's two `settlement contact` registrations, was not this
change's; the fix commit's validation reran it, and validation 120 passed every
lane. Whether that registration defect becomes a change of its own is the
owner's. Checks: `scripts/tests` 1076, `make test`, `make check-change`, `make
check-packaging` passed.

## 7. Pilot

Delivers D15's evidence: `fix-resource-pool-provider-at-creation` worked by the
orchestrator from `ready for design` through archive cleanup on this branch. The
pilot's own design, plan, reviews, and archive belong to that change; this
section records what they showed about the orchestrator.

- [x] 7.1 Run `make orchestrate CHANGE=fix-resource-pool-provider-at-creation`
      through every step to archive cleanup, on whatever tooling is committed when
      the pilot resumes, the owner's branch decision recorded once (D15, 69 F8,
      70 F10). Replanned against the revised design: the per-step branch
      confirmation is replaced by that one decision.
      Done: from `ready for design` (pilot log seq 1) to archive cleanup (seq 92,
      `fd89560b6`), the branch decision recorded once (seq 58). Three flows: the
      section-6 tooling (seq 1–17, reviews at 23, 43, 53; no model or cost on
      the lines); Codex tasks relayed by hand while Claude was at its weekly
      limit (seq 18–62; no session, denials, or cost); and the revised tooling
      (seq 63–93, every line naming its model, all but seq 73 its cost).
- [x] 7.2 Record here the evidence `design.md`'s Pilot section names: every
      `stopped` outcome and its denials, every `orchestrator` line and the state
      the script could not classify, the relay's latency in the design
      discussion, whether validation's background fetch survived a question,
      whether `--resume` applied a granted rule, and the `reason` value a denial
      by a deny rule records; for each item, which flow produced it — the
      hand-relayed Codex tasks, the section-6 tooling, or the revised tooling (69 F8).
      Done. Seq numbers are the pilot's log unless "this log" says so.
      - **A deny rule's denial records no reason** (revised tooling): the 6a–6d
        round's eight `Edit(.claude/**)` denials carry none beside a `mode`
        denial in the same run (this log's seq 76; 74 R2). A deny rule is
        matched against the command as typed: `git diff --output=/dev/null`
        was refused, `git diff HEAD '--output=/dev/null'` ran, so the rules
        dropped the space before `--output` (7.3).
      - **Every stop.** Section-6 tooling: seq 1, a network error before any
        work, and seq 2, its resume finding no conversation (hence 6a.2's retry
        of the same command); seq 17, Claude's weekly limit. Codex relay: seq 35
        and two more usage limits recorded only in the owner's lines continuing
        them (seq 39, 59). Revised tooling, all `mode` denials: seq 68, closeout's
        `sed -i` on a spec and the validator through `npx` (a gap, 103 R2); seq
        70 and 85, the step refusing the Edit tool its row allowed until resumed
        (103 R3's evidence); seq 73, no denial, the wrapper failing when the
        archive moved `reviews/` (7.3); seq 88, archive cleanup's `git -C … diff`,
        its stop malformed (103 R4); seq 90, the archived ledger's Edit (103 R5 /
        R6); seq 92, the draft's `Write` (103 R7). Runs that went on past a
        denial: seq 10 (design's `python3 -c` lens lookup, then Grep, read as a
        workaround at seq 11; a gap under 103 R3) and seq 77 (the closeout review
        on Claude denied three checks, since given to its row). No pilot run met a
        deny rule.
      - **Orchestrator lines.** No `unclassified` result was recorded. The
        orchestrating session decided routing or recovery itself at seq 3, 19,
        24, 30, 41 (a round view's base, which 74 R3 now records), 57, 64, 74, and
        76; its denial readings are seq 11, 69, 72, 78, 86, 89, and 93. This
        log's seq 82 reran fresh a review whose Codex session could not be
        resumed ("no rollout found").
      - **The relay's latency** (section-6 tooling, seq 5–16, from the
        transcripts' `result` events): the opening turn 330 s; a turn presenting
        the next decision 14–25 s; one recording a decision or reading code 78
        s and 119 s. The gaps between lines, 99 s to 2.5 hours, are almost all
        the owner's. What relaying adds, and whether relayed text drifted, the
        log does not show.
      - **Validation's background fetch across a question:** not exercised; since
        41 A1 a validation never ends a turn with a background command running.
      - **`--resume` and a granted rule:** the resumed turn is held to the rules
        it is given — a one-run grant (this log's seq 31; the pilot's seq 92) and
        a table edit between runs (seq 70) both applied. A grant admits only the
        calls it matches (this log's seq 21).
      - **The schema's `rounds`:** Claude Code accepts the nested schema on every
        run since 6c; no plan has emitted `rounds` yet, so no `round` line `by:
        plan` has been recorded.
      - **`## Next`:** a triage with nothing to dispose of recorded `Advance —
        nothing to dispose of` and the change advanced without the owner (seq
        66).
- [x] 7.3 Each allow-list gap the pilot found is a proposed edit to
      `.claude/change-steps.toml`, committed by the owner; each script gap is a
      rule added to `change_next_step.py` with its test; each is noted here.
      Done. Script gaps: a closeout run that archives its change keeps its
      transcript, progress, and log line, since `Stream` holds both files open
      across the rename and the wrapper finds the log again after the run, and a
      missing file reads as an unavailable harness only when it names the
      program launched (pilot 34 R1, 103 R1; unit tests archive a change during
      a fake run); a step's malformed stop keeps its message (103 R4). Archive
      cleanup's validation check may be waived by the owner, recorded as a
      ledger line, and reached under orchestration by the owner's direction
      (103 R5 / R6, 119 F1). Table edits, committed by the owner: the validator
      through `npx` on the design, plan, triage, and closeout rows (103 R2);
      archive cleanup's `Edit` of an archived change's ledger and of its draft
      at `archive/*/reviews/pull-request.md` — a mid-path `**` did not admit the
      archived path, a trailing one does (103 R7; absolute against relative
      paths ruled out); the `--output` deny rules without the space (7.2); the
      design row's lens rule and the review row's three checks. A review that
      cannot resume its Codex session stays a failed run, rerun fresh (this
      log's seq 81–82; seventh round's decisions).
- [x] 7.4 Update `design.md`'s Risks with what the pilot confirmed or disproved.
      Done, each Risk ending with what the pilot showed, and a new Risk: a
      closeout run archiving its change under the wrapper.
- [x] 7.5 From the runs on the revised tooling — the pilot's later steps, this
      change's own remaining rounds — record `make change-cost`'s report, the cache
      misses and their gaps, every fallback to another model, and every step that
      advanced without the owner; these are D16 to D19's evidence and the data the
      design's two open questions wait on.
      Done, for every run logged before section 7's session; later runs are on the
      log, and `make change-cost` reports them.
      - **The pilot** (seq 63–93): 19 runs, $12.10–$12.73, 378 turns, 32
        minutes; closeout $4.35–$4.98 over 4 runs, triage $4.39 over 9, the
        Claude review $2.60, validation $0.32, archive cleanup $0.45; 7 session
        openings $5.85, 11 warm resumes $5.10–$5.72, one miss (triage seq 81,
        after 1 h 10 m, $1.16).
      - **This change** (seq 80 on): 34 runs, $37.61–$93.28, 746 turns, 1 h 48 m;
        round 6a–6d $12.29–$67.95, round 6e $25.32; implementation $19.11–$74.77
        over 2 runs, triage $17.33 over 25, validation $1.17 over 4, the Codex
        reviews 1.5M tokens; 11 openings $24.50, 22 warm resumes $13.11, one miss
        (implementation seq 80, after 10 minutes, partial since its predecessor
        stopped at its limit without a total).
      - **Fallbacks:** one, the pilot's closeout review (seq 77), on Claude Opus
        5.5 while Codex was at its usage limit, named so on its record and line;
        one-model steps stopped with their reset time instead (this log's seq 78).
      - **Advancing without the owner:** in the pilot, validation, the
        pre-closeout review, its triage with nothing to dispose of, closeout, the
        closeout review, and archive cleanup (seq 63–88); in this log, the fix
        commits' validations and each round's review and validation after the
        owner's notes. Every other stop was a touchpoint.
      - **The open questions:** session openings are the largest measured share
        ($5.85 of $12.10; $24.50 of $37.61), but an opening's dollars are its
        whole run, and the report does not separate loading from work. Two
        misses against 33 warm resumes — one an hour's lifetime would have
        spanned, one it would not — do not yet settle the cache lifetime.

Section 7 evidence: `scripts/tests` 1080 passed; `make test`, `make check-change`,
and `make check-packaging` passed. Seventh round's fixes (review 119, validation
120; decisions in `design.md`): the owner's direction past archive cleanup's
validation (119 F1); `make change-watch` following a run into the archive (119
F2); a review that cannot resume its Codex session rerun fresh (seq 81–82, no code
change). Checks: `scripts/tests` 1084 and `make test` passed, and `make
check-packaging` passed on `ca75e897b` at the pre-closeout triage (126 F2), whose
fix makes `change-triage` run it after every fix round.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in its order.

- [x] 8.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments this change added to `scripts/`; anything to rewrite returns the
      change to implementation.
      `make check-comment-hygiene`: both scans OK. The comments and docstrings the
      change added to `scripts/`, the `Makefile`, and the step table (its diff
      against the merge base with dev) name no review, round, task, change, or
      migration; their mentions of `## Gate` describe the legacy triage format the
      computation still reads. Nothing to rewrite.
- [x] 8.2 Import placement — confirm: no function-local import added in
      `scripts/run_change_step.py`, `scripts/change_next_step.py`, or their tests.
      Confirmed for every file the change added or touched under `scripts/`,
      including the `scripts/change_workflow/` package section 6e split those
      modules into: the diff's added lines hold no indented `import` or `from …
      import`.
- [x] 8.3 Documentation compliance: re-check D1–D19, D5a, and D6a against
      `openspec/README.md`'s placement rules.
      Each decision is normative behaviour in the delta, rationale in the
      `change-workflow` companion, or contributor how-to in
      `docs/agents/change-workflow.md`; D15 is change history, its mechanism in the
      skills; none is repository-wide, so `ARCHITECTURE.md` gains nothing (the
      record in `design.md`). Against the code: the contributor guide's Skills
      table, its "gate" wording, and its `make review` paragraph (Codex only)
      were stale and are rewritten in 8.9. One stale line is code, outside
      closeout's edits: the `Makefile`'s `archive-cleanup` help says "once its
      closeout gate has passed"; left for the closeout review and its triage.
- [x] 8.4 Narrative compression of sections 1–7's notes.
      Done. Moved to `design.md` first: the schema's draft-07 and top-level
      combinator findings (D3), the design review's own triage step (D14), the
      one "Running unattended" section per skill (D12), the network retry's same
      command (D18), the cost's list prices (D19), and every item the
      fresh-context checks raised and a round declined ("Declined at the
      fresh-context compliance checks"); each round's fix rationale was already
      under its round's decisions. The task texts are unchanged.
- [x] 8.5 Roadmap currency: record that no goal in `docs/development/ROADMAP.md`
      covers contributor workflow, or update it.
      No goal covers contributor workflow; no edit.
- [x] 8.6 Campaign index currency: this change's row `in closeout`, under
      independent active changes, with no campaign graph; the pilot's row is its
      own archive cleanup's; `parallel-change-workflows`' `Depends on` is
      unchanged. `make check-change-index`.
      Done: the row `in closeout`, its notes rewritten for closeout and, after the
      archive, its link pointed at the archive (8.11); no other row's `Depends
      on` or status touched; the legend reworded from gates (8.9). `make
      check-change-index`: OK.
- [x] 8.7 Packaging: `make check-packaging`, `make check-architecture-change
      CHANGE=orchestrate-change-workflow`, and `make check-agent-skills`.
      `make check-packaging`: every check OK, wheels built. `make
      check-architecture-change`: owns no architecture row. `make
      check-agent-skills`: OK.
- [x] 8.8 End-to-end pipeline: record a passing run on the closeout commit and its
      scenarios, or an explicit blocker naming its cause and owner. The change's
      own code is contributor tooling the pipeline does not run; the pilot's
      validations are its working evidence.
      The latest passing validation, 120, names `5d6472e67`: local, Helm, and
      pipeline run 39316136850 (e2e-apicredits, e2e-vm, e2e-bare-metal) all
      passed. No end-to-end scenario exercises this change (contributor
      tooling); its working evidence is the pilot (section 7). Its two later
      commits, `ca75e897b` (the seventh round's fixes) and `b3b1f2abf` (the
      pre-closeout triage's), are unvalidated by the owner's waiver (this log's
      seq 133, extended at the pre-closeout triage); closeout changes
      documentation only, so no later run would describe other code.
- [x] 8.9 Promotion, completing the design-promotion record:
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
        rewritten at the fifth round's triage (77 F3 / 74 O1); and what archive
        cleanup writes gains the waiver's ledger line (7.3).
      - `AGENTS.md` "Change workflow" — names `make orchestrate`.
      - `openspec/specs/change-workflow/spec.md` "Evidence" — already repointed
        from `run_change_review.py` (retired) to `run_change_step.py review` in
        section 3, when the script was deleted; record it here. It also gains
        `scripts/change_workflow/`, the package behind that entry point, and
        `make check-change` (`scripts/check_change.py`) (6e).
      - `openspec/specs/README.md` and `docs/development/ARCHITECTURE.md` — no
        change: no new capability or companion, and the workflow is contributor
        process.
      Done, each as listed. The companion also rewrites "Leaf skills from one
      source", "Phases, triage, and archival" (formerly titled for gates), and
      "The index states what may start" for the orchestrating session and the
      triage's `## Next`, and adds to "Current limits" that choosing work across
      changes stays with the owner and that a wrapper run is followed from
      another terminal. The spec's Evidence also names the orchestrating skill,
      the schema, the step table, the computation, `make change-watch`, `make
      change-cost`, the completion script, and `make check-tasks`. The contributor
      guide's Skills table also gains the orchestration row, and its triage row
      `## Next`. The design-promotion record is at the end of `design.md`.
- [x] 8.10 Documentation citations:
      `make check-doc-citations CHANGE=orchestrate-change-workflow`, then
      `openspec validate orchestrate-change-workflow --strict`.
      Both passed within `make check-change CHANGE=orchestrate-change-workflow`
      (with comment hygiene, agent skills, the task list, and the index), against
      the promoted documents: every citation resolves, the retired review
      runner's name included.
- [x] 8.11 Archival: `openspec archive orchestrate-change-workflow -y`, merging the
      delta into `openspec/specs/change-workflow/spec.md`. Right after the archive
      merges the delta, before the closeout commit and its review, rename the
      permanent spec's scenarios "A closeout gate is passed" and "A pre-closeout
      gate is passed" to say the triage advances, which the pinned validator
      refused in the delta (D16), and check the result with `make check-change
      CHANGE=orchestrate-change-workflow` (126 F1).
      Archived to `openspec/changes/archive/2026-10-19-orchestrate-change-workflow/`
      with the pinned validator (`npx --yes @fission-ai/openspec@1.14.0`, `bunx`
      not being installed here), the deltas merged rather than skipped, since the
      permanent spec did not yet carry them: 8 requirements added, 6 modified, 2
      renamed ("Phases and owner gates" to "Phases and owner touchpoints", "One
      implementation section per fresh session" to "Implementation sections and
      sessions"; the plan's "five added" undercounted). The merged spec's diff
      reads each requirement once, as the delta states it, the Purpose and
      Evidence edited by hand before the archive kept, and nothing else changed.
      The two scenarios are renamed "A closeout review's triage advances the
      change" and "A pre-closeout review's triage advances the change". The index
      row links the archive. `make check-change CHANGE=orchestrate-change-workflow`,
      on the archived change (`openspec validate --specs --strict`), passed.
