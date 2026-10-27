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

- Every step's handoff names the step to run next, as the step the orchestrating
  session would start if it were run again: `Advance` becomes the step it leads to
  (`plan`, `review pre-closeout`, `archive-cleanup`), `Another round` a named
  repeat (`review implementation`, round 2), and `Returned to planning` the step
  `plan`. A finished step's subagent, or the orchestrating session after the
  subagent returns, writes it.
- The vocabulary covers what the owner reaches today only by a decision line: a
  design review of a triage's fix before implementation, or an implementation
  session for a named section out of the plan's order.
- The computation checks the named step's preconditions instead of inferring the
  step: a round advances only on a passing validation of its final commit, and
  archive cleanup waits for a validation when code changed, whatever step was
  named. A named step whose preconditions fail is refused, with what it needs.
- The existing directed decisions (an owner line with `next`) and owner-recorded
  rounds are folded into the same mechanism, or kept beside it, as design decides.

Open for design, not decided here:

- the vocabulary of step names, and how a section, a round, or a review kind is
  named in it;
- where the named step lives — a triage file's `## Next`, a step's outcome, a log
  line — and which of those the computation reads when they disagree;
- which writer may name which step: what a leaf may direct, what only the owner
  may, and whether the orchestrating session writes the name on a leaf's behalf;
- recovery: a step that crashed before naming its successor, a status edited by
  hand, a named step whose preconditions changed after it was written, and a
  restart in another checkout;
- whether inference stays as the fallback for records written before this change.

## Capabilities

### Modified Capabilities

- `change-workflow`: the routing requirement, each skill's handoff, triage's
  `## Next`, the orchestrating session's decision lines, and the step outcome.

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

## Impact

- `scripts/change_next_step.py` and its tests, and the outcome and log modules
  under `scripts/change_workflow/`.
- Every leaf skill's handoff under `.agents/skills/`, and the orchestrate skill.
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

To be determined at design completion.
