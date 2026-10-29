## Why

The owner reads a committed implementation round through the round view: `make
round-view` resets the change's branch to the round's base and shows the round's
commits as uncommitted changes in the owner's checkout
(`openspec/specs/change-workflow/architecture.md#current-limits`). A merge of `dev`
made inside the round shows `dev`'s changes beside the round's own, with nothing to
tell them apart.

`parallel-change-workflows` met this twice. Its round 2 view held 98 files, 69 of
them from one merge of `dev` that brought in a Helm render fix, and the owner could
not read the round for it. Its pilot's view held 118 files, eleven of them from
merges inside the round. Holding merges to round boundaries is no answer: a merge
from `dev` often carries an urgent fix, which a round must build on rather than
ignore and then rediscover or duplicate.

## What Changes

- The round view shows only the branch's own changes in a round and its merges'
  conflict resolutions, not the changes a merge of `dev` brought in.
- The owner's leaning, carried from `parallel-change-workflows`' design: a
  synthetic base. The view resets to a commit that merges the round's base with
  each `dev` commit the round merged, so the difference from it is the round's own
  work.

Open for design, not decided here:

- how a synthetic base fits `scripts/round_view.py`, which holds the view's base to
  be an ancestor of the round's head: where `done` carries the owner's commits
  onto the head, where the view refuses a branch that has left the base's line,
  and where a refresh resets over new commits. A synthetic base is off that line;
- what the view shows when the round's base and the merged `dev` commits do not
  merge cleanly without the round's own resolution;
- whether the implementation review and validation, which read the same round,
  should see it the same way.

## Capabilities

### Modified Capabilities

- `change-workflow`: the round view, and the current limit that says it mixes in
  merges.

### New Capabilities

None.

## Non-Goals

- Do not restrict when `dev` may be merged into a change's branch.
- Do not change how a round is validated or reviewed, beyond what reading it
  without merges requires.

## Impact

- `scripts/round_view.py` and its tests, and `make round-view` / `make round-done`.
- The orchestrate skill's round-view reading, the `change-workflow` spec and
  architecture, and `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- Opened from `parallel-change-workflows`: its open question 2 (observation 94 O1),
  deferred here by its round 4 triage (145 F1). Its design records the candidates
  and why the alternatives were rejected: merging `dev` only between rounds, and
  listing a merge's paths beside the view.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` (spec and architecture)
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
