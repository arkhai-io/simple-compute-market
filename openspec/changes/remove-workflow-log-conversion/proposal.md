## Why

Every line the workflow tooling appends to a change's workflow log carries the log's
format marker, `"format": 2`, and the next-step computation reads only that format.
A change whose log holds a line without the marker, or whose numbered records have
no log, is brought to the owner with `change-workflow convert <change>`, which
rewrites the older lines in place and records where the change stands
(`arkhai-change-workflow`'s CW-4rqr and CW-qj77).

The command and the detection exist only for changes whose records were written
before the format: a change worked on another branch runs that branch's tooling
until it merges the code that reads the format, and is converted then
(`arkhai-change-workflow`'s companion, "Current limits"). Once every change
not yet cleaned up has been converted, nothing will ever need them again, and they
keep the older reading of triage files — the `## Next` tokens and `## Gate` —
alive in the engine's `convert` module, the only place it remains.

## What Changes

- Remove the `convert` command, the engine's `convert` module, and their tests.
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

All of it is `arkhai-change-workflow`'s, the installed change workflow:

- the engine's `convert` module, its command line, its next-step computation, and
  possibly its log writer, and their tests;
- the `change-orchestrate` skill, the `change-workflow` specification and companion,
  and the workflow's handbook.

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
