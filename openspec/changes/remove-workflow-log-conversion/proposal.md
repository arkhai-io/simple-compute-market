## Why

Every line the workflow tooling appends to a change's workflow log carries the log's
format marker, `"format": 2`, and the next-step computation reads only that format.
A change whose log holds a line without the marker, or whose numbered records have
no log, is brought to the owner with `python3 scripts/run_change_step.py convert
<change>`, which rewrites the older lines in place and records where the change
stands (`openspec/specs/change-workflow/spec.md#requirement-the-next-step-is-computed-from-the-files`).

The command and the detection exist only for changes whose records were written
before the format: a change worked on another branch runs that branch's tooling
until it merges the code that reads the format, and is converted then
(`openspec/specs/change-workflow/architecture.md#current-limits`). Once every change
not yet cleaned up has been converted, nothing will ever need them again, and they
keep the older reading of triage files — the `## Next` tokens and `## Gate` —
alive in `scripts/change_workflow/convert.py`, the only place it remains.

## What Changes

- Remove the `convert` command, `scripts/change_workflow/convert.py`, and their
  tests.
- Remove the computation's detection of a change not yet converted, and its result
  naming the command.
- Remove the conversion clauses and scenarios from the `change-workflow`
  specification, and the conversion from its architecture companion, the
  contributor guide, and the orchestrate skill.
- Keep the format marker on every line, as the log's format for any later change to
  it.

Open for design, not decided here:

- what a log line without the marker means once nothing converts it — refused,
  brought to the owner, or impossible by then;
- whether the conversion line (`step` `convert`) stays readable as naming the reviews
  it triaged, for the logs that hold one;
- whether the readers' and appenders' check of the file they locked against the
  log's name, which protects a line appended while the log is replaced, stays once
  nothing replaces the log;
- how the owner establishes that every change not yet cleaned up has been
  converted, which is this change's activation condition.

## Capabilities

### Modified Capabilities

- `change-workflow`: the next-step requirement's conversion clauses and scenarios.

### New Capabilities

None.

## Non-Goals

- Do not change the log's format, or what any writer appends.
- Do not convert or rewrite any change's records; cleaned-up changes' history stays
  as it is.

## Impact

- `scripts/change_workflow/convert.py`, `scripts/change_workflow/cli.py`,
  `scripts/change_next_step.py`, and possibly `scripts/change_workflow/log.py`, and
  their tests under `scripts/tests/`.
- `.agents/skills/change-orchestrate/SKILL.md`, the `change-workflow` spec and
  architecture, and `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- Opened by `workflow-steps-name-next-step`'s closeout, whose design (D7) made the
  command and the detection temporary. Its implementation waits until every change
  not yet cleaned up has been converted.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` (spec and architecture)
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
