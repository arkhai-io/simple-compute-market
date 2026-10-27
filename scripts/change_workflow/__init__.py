"""The tooling that runs the steps of an OpenSpec change and keeps its workflow log.

Each module holds one concern, on the standard library alone:

- `outcome` — the outcome a step ends with, checked against its schema;
- `log` — the change's workflow log, the orchestrating session's notes, and the
  owner's branch decisions; it is the log's only writer;
- `records` — the numbered records in a change's `reviews/`, the validation they
  hold, and the commits they name;
- `steps` — the step table: each step's skill, permissions, and models;
- `stream` — a Claude Code run's event stream, transcript, progress, and denials;
- `harness` — the Claude Code and Codex commands, and how each harness says it
  cannot serve a model;
- `cost` — what each run cost;
- `running` — the record of each run in progress in a checkout, which a round view
  reads before it moves the checkout;
- `wrapper` — running a step unattended, and resuming a waiting run;
- `review` — a review run read-only and published as a numbered record;
- `watch` — following the steps as they run, and a run's denials report;
- `cli` — the command line, which `scripts/run_change_step.py` runs.

Contract: openspec/specs/change-workflow/spec.md, "Unattended step runs end with a
structured outcome".
"""
