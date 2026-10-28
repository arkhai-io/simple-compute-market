## Why

The next step of a change is inferred: `scripts/change_next_step.py` reads the
index row, the reviews and their triage files, the task list, and the workflow
log, and works out where the change stands
(`openspec/specs/change-workflow/spec.md#requirement-the-next-step-is-computed-from-the-files`).
A triage tells it only one of three fixed tokens in its file's `## Next` —
`Advance`, `Another round`, or `Returned` — and the computation turns that token
into a step by reading the phase around it.

Each new handoff has to be taught to that inference. A triage that returned the
change wrote no token, and the computation stranded the change on a triage that
would never finish; the fix added a third token and the rules for setting the
returned review aside. A path the inference does not know has to go through the
owner by hand: a design review of a triage's fix before it is implemented, or a
section implemented out of the plan's order, is reached only by an owner decision
line naming `next` or a round line the owner records.

The step that finishes knows where the change goes next. Having it say so, by
name, would make the handoff explicit, let a step or the owner direct any path the
workflow supports without a new token, and leave the computation checking a named
step rather than inferring one.

## What Changes

- The workflow's graph is stated as one table in code: each node a step, qualified
  by its review kind — a triage by the kind of review it triages; its exits; the
  join it waits on; the guards on each edge, each naming the step that satisfies
  it; and its entry guards, the conditions without which its step cannot carry out
  its work. Archive cleanup exits to a terminal `done`. The computation interprets
  the table in place of its per-phase rules. The `change-workflow` architecture
  shows it as a draw.io diagram laid out by hand, which a test holds to the table's
  nodes and edges, and `make change-graph` reports where it departs from the table,
  to redraw it from.
- Every step's outcome names the exit it takes as a structured target in `next` —
  `{"step": "review", "kind": "pre-closeout"}`, `{"step": "round"}`,
  `{"step": "plan"}` — and a triage's outcome names the records it triaged. A
  triage chooses among its node's exits on the owner's disposition, so `Advance`,
  `Another round`, and `Returned` give way to the target each leads to; a review
  names its triage, and a validation the target the computation gave it — the
  round's triage, or the exit whose guard it remedies. `## Next` stays in the triage
  file as prose, and nothing routes on it.
- The computation checks a named exit against the graph instead of inferring it: an
  exit whose guard is not met names the guard's remedy — a validation of `HEAD` —
  and keeps the exit as its target; a guard no step can satisfy, or an exit the node
  does not declare, names the owner.
- The owner redirects one change by a decision naming any node as its target, and no
  exit guard is checked against it; the target's entry guards are, and an
  unwaivable one — the archive, which no direction crosses either way — refuses it,
  while a waivable one takes it as its override. The waivers of a design review and
  of archive cleanup's validation become such directions, whose reason says what
  they skip. Every direction is the owner's.
- An interactive run records its own outcome with `run_change_step.py record`,
  which reads the session's id from `CLAUDE_CODE_SESSION_ID`; an interactive session
  of any step closed before it records leaves that step in progress, for the owner
  to resume or record by hand.
- A change's records are converted to the new format when its branch first carries
  the new code, by a committed `convert` command, which rewrites the log's lines in
  place, appends one line recording the conversion, and the owner's direction to
  where the change stands, which it proposes from the latest routing decision and
  the owner confirms, attesting each triage no marked outcome names, all in one
  replacement of the log made under the log's lock; it refuses a change with a
  triage in progress. The log's readers and appenders reopen the log when the file
  they locked was replaced, so no line is lost to the replacement. Every new log
  line carries a format marker; the computation reads only the
  new format, detects a change not yet converted by a line without the marker, or
  by records with no log, and names the owner with the command for it. A later
  change removes the command and the detection once every change not yet cleaned up
  is converted.
- A direction to validation names the target the validation is for, and
  validation's entry guard refuses one without it; the log's writer checks the
  nested target's unwaivable entry guards, and the computation's own validations
  have theirs checked on their exit, so a round's validation starts beside its
  review.

## Capabilities

### Modified Capabilities

- `change-workflow`: the workflow graph, the routing requirement, the step outcome
  and its recording by interactive runs, triage's `## Next`, the owner's
  directions, and the phase requirement's account of a triage that advances the
  change.

### New Capabilities

None.

## Non-Goals

- Do not move routing into the model. The computation stays code, tested under
  `scripts/tests`, and still holds every gate; what changes is whether it infers
  the next step or checks a named one
  (`openspec/specs/change-workflow/architecture.md#routing-is-code-with-the-model-as-backstop`).
- Do not orchestrate several changes from one session, or choose across changes
  what to work on next.
- Do not change what any step does once it is started.
- Do not return an archived change to an earlier phase: a closeout triage that needs
  a code correction stops for the owner, as now.

## Impact

- `scripts/change_next_step.py` and its tests; the outcome, log, wrapper, review,
  and command-line modules under `scripts/change_workflow/` and their tests;
  `.agents/change-outcome.schema.json`; a `make change-graph` target; a `convert`
  command of `scripts/run_change_step.py`.
- The records and workflow logs of every change not yet cleaned up, each converted
  when its branch takes the new code; this change's in round 2.
- Every leaf skill's handoff and a new interactive ending under `.agents/skills/`,
  the plan, closeout, and archive cleanup entry checks, and the orchestrate skill.
- `.claude/change-steps.toml`: every step may run `printenv
  CLAUDE_CODE_SESSION_ID`.
- The `change-workflow` spec and architecture, and `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- Opened from `parallel-change-workflows`' closeout review 157, finding 1: the
  owner chose the narrow `Returned` token there and this change for the general
  version. `Advance`, `Another round`, and `Returned` are what it generalises.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` (spec and architecture)
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The workflow graph as a table in code, its nodes, exits, joins, and guards with
  their remedies (D1, D4): `openspec/specs/change-workflow/spec.md`, and its diagram
  and rationale in `openspec/specs/change-workflow/architecture.md` ("Routing is
  code, with the model as backstop").
- A durable change to the workflow is an OpenSpec change; an intervention is a
  per-change, irregular transition, deliberate and the owner's alone (D1, D5):
  `openspec/specs/change-workflow/architecture.md`.
- A step's exit as a structured target in its outcome, and triage's `triaged` (D2,
  D3, D6): `openspec/specs/change-workflow/spec.md`; the files hold a change's state
  and the log the transitions chosen on it (D3): `architecture.md`.
- An unmet guard names its remedy; an undeclared exit names the owner (D4):
  `spec.md`.
- The owner's directions to any node, past its exit guards and within its entry
  guards: an unwaivable one refuses the direction, a waivable one takes it as its
  override; a direction to validation names the target it is for, whose
  unwaivable entry guards are checked too (D5): `spec.md`,
  and the orchestrate skill.
- Interactive runs record their outcome through `record` (D11): `spec.md`,
  `architecture.md` ("Steps run headless and resume with the owner's answers"), and
  `docs/agents/change-workflow.md`.
- The computation reads only the format in which outcomes name their exits, marked
  on every log line, and brings a change not yet converted to the owner with the
  conversion command (D7): `spec.md`, the command until the later change that
  removes it, the marker for good.
- Entry guards on nodes, unwaivable or waivable, and exit guards on edges (D1, D5):
  `spec.md`, and the distinction's rationale in `architecture.md`.
- Returning an archived change to an earlier phase is not supported (D5):
  `architecture.md`, "Current limits".
