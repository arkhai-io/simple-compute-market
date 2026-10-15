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

- [ ] 1.1 Add `scripts/change_outcome.schema.json`: the five outcomes —
      `finished` (with `next`), `question` (with `awaiting`), `returned` (with
      `return_to` and `evidence`), `blocked` (with `blocked_on`), `stopped` (with
      `reason` and `denials`) — each carrying the step's `message`. D3's example
      lines validate against it; unit tests in
      `scripts/tests/test_run_change_step.py` check each outcome's required fields
      and reject an unknown outcome.
- [ ] 1.2 Add `scripts/run_change_step.py` with the log's writer and reader: append
      one line to the change's `reviews/workflow.jsonl` with `seq`, `at`, the step,
      its session and commit; read the last lines. Its `note` operation appends the
      orchestrator's `round` (D13) and `orchestrator` (D14) lines, so the wrapper is
      the log's only writer. The change's directory is found through
      `scripts/find_change.py`, so an archived change's log moves with it. Unit:
      `seq` increases across appends and notes, a malformed line is reported with
      its line number rather than skipped, and a note without its required fields
      is refused.
- [ ] 1.3 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`.

## 2. Running a Claude Code step through the wrapper

Delivers the headless run, its resume, its permissions, and its event stream (D1,
D6, D7; the wrapper side of D12 and 01 F5; requirements "Unattended step runs end
with a structured outcome" and "Unattended runs are held to their step's
permissions").

- [ ] 2.1 Add `scripts/change_steps.toml` with D6's table: each step's skill and
      its allow and deny rules, including design's `git worktree add` from dev and
      edits under that worktree's `openspec/` (D5), and validation's guarded push
      as the only push.
- [ ] 2.2 `run_change_step.py run <step> <change>`: `claude -p` with the step's
      skill prompt, `--permission-mode dontAsk`, the step's rules from
      `change_steps.toml`, the outcome schema through `--json-schema`, and
      `--output-format stream-json --verbose`; record the session id; append the
      validated outcome. A run that exits non-zero, or ends with no outcome or one
      the schema rejects, is logged `stopped` by the wrapper with its exit status.
      A `stopped` line's `denials` come from the run's `permission_denials`, never
      from the step's account (D3, 01 F5). Unit (fake runner and fake stream): each
      outcome is logged with session and commit; a crash, an empty and a malformed
      outcome each log `stopped`; denials are taken from the stream.
- [ ] 2.3 `run_change_step.py resume <change> --answer <text> [--allow <rule>]`:
      resume the last session of the step with `--resume <id>` and the owner's
      answer, with any rule granted for that one run (D6). Unit: the resumed
      command carries the session and the granted rule, and the next run of the
      step does not.
- [ ] 2.4 Event stream and progress (D7): write the stream to
      `reviews/transcripts/NN-<step>.jsonl`, numbered after every record in
      `reviews/` and `reviews/transcripts/`, and a progress file beside it with
      one line per tool call and its time. Unit: the transcript's number follows
      existing records, and the progress file lists the fake stream's tool calls.
- [ ] 2.5 Verification: `uv run pytest -q scripts/tests/test_run_change_step.py`
      (unit); `make test`; one hand run of `run_change_step.py run plan` on a
      scratch copy of a change, recorded here with its outcome line, to confirm the
      `claude -p` flags the unit tests assume.

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
