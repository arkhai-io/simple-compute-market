## Why

Each step of an OpenSpec change is a leaf skill, started by the owner through its
`make` target in a fresh session: `make design`, `make review`, `make triage`,
`make implement` once per section, `make validate`, `make closeout`, and `make
archive-cleanup`. The skills do the transport inside each step, but between steps
the owner still does it: reading where the change stands, choosing the next target,
opening a new terminal session for it, and carrying the outcome to the step after.
For a change with several implementation sections and review rounds, that is a
dozen or more sessions, and most of the owner's time between them goes to deciding
which session comes next, which the files already determine.

The leaf skills were built first so their failure modes would be known before
anything advanced a change automatically. The `agent-driven-change-workflow` and
`capacity-shape-envelope` cycles have now run every step, so the orchestrator its
proposal deferred can be built on them.

## What Changes

- Add an orchestrating skill, `change-orchestrate`, run as the owner's one
  top-level session for a change (`make orchestrate CHANGE=<change>`). It holds no
  state of its own: where the change stands is computed from the files and a
  workflow log, so a new session resumes a change after compaction or a restart.
- A script, `scripts/change_next_step.py`, computes the next step from the change's
  index row, reviews and their triage, `tasks.md`, and the log. The orchestrator
  runs that step; when the script cannot classify the state, the orchestrator works
  out what happened and decides routing or recovery itself, or raises it with the
  owner.
- Every step runs through one wrapper, `scripts/run_change_step.py`, reached through
  its `make` target's unattended form: a headless Claude Code session (Codex for
  reviews, as now), held to the step's allow-list, its session recorded so it can be
  resumed. A step the orchestrator runs and a step the owner runs by hand are the
  same process, and the owner can take a stopped step over.
- Every run ends with a structured outcome, appended to the change's
  `reviews/workflow.jsonl`: finished, and the next step; a question for the owner,
  the answer resuming the same session; a proposed return to an earlier phase; blocked
  on a prerequisite; or stopped, with its reason and any tools it was denied.
- Design, triage, and planning are discussions: the same headless sessions, resumed
  for each of the owner's turns, with each message shown in the top-level session.
- How many sections a session implements, and how many make a round, is agreed
  with the owner before implementation. The plan stays agnostic of sessions:
  `change-plan` and `change-implement` stop sizing and stopping by "one section
  per session".
- A design blocked on a prerequisite shapes the prerequisite's requirements and
  initial proposal, which land on dev first, records the dependency, and halts. The
  owner starts the prerequisite's workflow; the original restarts, releasing the
  dependency on the owner's word, once the prerequisite is merged.
- The orchestrator opens and closes the round view, notifies the owner when a step
  needs them, and records each step's event stream as a transcript.
- The orchestrator never passes a gate and never answers a design question.
- Piloted on `fix-resource-pool-provider-at-creation`, from `ready for design`
  through archive cleanup, on this change's branch.

## Non-Goals

- **Several changes at once.** The orchestrator advances one change in one
  checkout. Working changes in parallel is `parallel-change-workflows`'; once it
  lands, orchestrating several changes is a follow-up.
- **Choosing what to work on next across changes.** Campaign priority and scheduling
  from the index stay with the owner, including starting a prerequisite's workflow.
- **Removing human gates.** Every review stops for the owner, as now.
- **Shareable session logs.** Publishing step transcripts and reviews where the
  owner's team can read them is separate work; this change keeps `reviews/` and
  transcripts where they are.
- **Changing what a leaf skill checks.** Each step's procedure stays its skill's;
  this change adds how it is started, how it asks the owner, and how it reports.

## Capabilities

### Modified Capabilities

- `change-workflow`: an orchestrating session advances one change through its
  steps, each run through one wrapper as its leaf skill, holding design, triage,
  and planning as conversations with the owner, and bringing every gate and
  question to the owner; every run ends with a structured outcome naming what comes
  next, including a return to design or a prerequisite change; implementation
  sections are no longer bound one to a session.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — none; the workflow is contributor
      process, not system architecture.
- [x] Existing subsystem specification — `openspec/specs/change-workflow/spec.md`.
- [ ] New subsystem specification
- [x] Contributor guidance — `docs/agents/change-workflow.md`, and `AGENTS.md`'s
      change workflow section.

### Knowledge to promote

- The orchestrating session, the wrapper and its outcomes, what only the owner
  decides, and sections no longer bound to sessions —
  `openspec/specs/change-workflow/spec.md`.
- Why steps are headless sessions resumed with the owner's answers, why routing is
  code with the model as backstop, the permission model, the prerequisite flow, and
  the principles the owner stated (a plan is agnostic of sessions and harnesses;
  one change per branch, a prerequisite's proposal landing on dev first; routing is
  deterministic; restrictions apply only to unattended runs) —
  `openspec/specs/change-workflow/architecture.md`.
- How to start and resume an orchestrated change, agree a round, and maintain the
  allow-lists — `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- Builds on `agent-driven-change-workflow` (archived), whose leaf skills, `make`
  targets, review records, and index statuses it drives.
- Related to `parallel-change-workflows`: orchestrating several changes at once
  waits for it. Either may land first.
- Pilot: `fix-resource-pool-provider-at-creation`, worked through every step by the
  orchestrator on this change's branch.

## Impact

`.agents/skills/` (a new `change-orchestrate` skill; how every leaf skill asks and
reports when run unattended; `change-plan`'s and `change-implement`'s section
sizing; `change-design`'s prerequisite path), the workflow `make` targets and a new
`make orchestrate`, new scripts (`scripts/run_change_step.py`, absorbing
`scripts/run_change_review.py`; `scripts/change_next_step.py`;
`scripts/check_comment_hygiene.py`, a port of the Makefile's check) with their
tests, the outcome schema (`.agents/change-outcome.schema.json`) and the step
permission table (`.claude/change-steps.toml`),
the `change-workflow` specification and architecture companion,
`docs/agents/change-workflow.md`, and `AGENTS.md`. No service code changes, beyond
the pilot change's own.
