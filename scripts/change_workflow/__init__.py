"""The workflow's engine: the tooling that runs the steps of an OpenSpec change,
keeps its workflow log, and computes its next step.

Each module holds one concern, on the standard library alone, and reaches its
siblings by relative import:

- `common` — what every part shares: the repository a command acts on, found from
  the working directory, the engine's error, and its clock;
- `graph` — the workflow's graph: its nodes, their exits, joins, and guards, which
  the next-step computation interprets, and the steps and review kinds it declares,
  the engine's only list of either;
- `diagram` — the architecture's hand-laid diagram of the graph, held to the table
  (`scripts/change-workflow check graph`);
- `outcome` — the outcome a step ends with, checked against its schema, and the
  records a triage's outcome names;
- `log` — the change's workflow log, the orchestrating session's notes, and the
  owner's branch decisions; it is the log's only writer;
- `records` — the numbered records in a change's `reviews/`, the validation they
  hold, and the commits they name;
- `find` — a change's directory by its name, active or archived, and its records,
  in this checkout or the owner's workspace;
- `index` — the change index, `openspec/changes/README.md`: its rows, each row's
  status and dependencies, and the check that holds it to the change directories;
- `tasks` — the check that every task of a change's task list sits under its own
  section's heading;
- `next_step` — the next-step computation: where a change stands, read from its
  files and its log, and the step it names;
- `config` — the repository's workflow configuration, `.agents/workflow.toml`, read
  and checked whole, and the subcommands that read it: `config`, `config load`,
  `config parts`, and `check config`;
- `hooks` — running the repository's hooks and validation's parts through `run`,
  each ending with the engine's closing line, and the marker kept from a part's
  dispatch for its collect; `pre-commit`'s default checks alone (`check change`);
  and the repository's OpenSpec command (`openspec`);
- `steps` — the step table: each step's skill and the permission rules an
  unattended run of it is held to, and what a model a step runs on is; which models
  it runs on are the configuration's;
- `stream` — a Claude Code run's event stream, transcript, progress, and denials;
- `subagents` — the denials a run's subagents met, read from their transcripts;
- `harness` — the Claude Code and Codex commands, and how each harness says it
  cannot serve a model;
- `cost` — what each run cost;
- `cost_report` — what a change's runs cost, by step and by round;
- `running` — the record of each run in progress in a checkout, held locked while
  the run goes on, which a round view reads before it moves the checkout and `stop`
  reads to signal the run; and the SIGTERM handling that turns that signal into the
  run's `stopped` line while its agent or reviewer runs, and holds it for the rest
  of the run, for steps and reviews alike; and each session's invocations through
  `run` and the guarded push, kept until the session's log line records them;
- `wrapper` — running a step unattended, and resuming a waiting run;
- `review` — a review run read-only and published as a numbered record;
- `watch` — following the steps as they run, and a run's denials report;
- `convert` — a change's records brought into the workflow log's format, on the
  owner's confirmation, with the direction to where the change stands;
- `clone` — a change's own clone of the owner's workspace: creating, reading, and
  removing it;
- `history` — a change's history copied from its clone into the owner's workspace;
- `round_view` — an implementation round shown as uncommitted changes for the owner
  to read;
- `push` — the guarded push of a change's own branch;
- `wait` — blocking until a file holds a line matching a pattern, so an unattended
  step waits for a background command inside one call;
- `skills` — the check that every agent skill is loaded from its one shared source;
- `hook` — what a Claude Code session re-reads after its context is compacted;
- `cli` — the engine's command, `scripts/change-workflow`, its subcommands
  dispatched to the modules above.

Beside them, `workflow.mk` is the make fragment whose targets call the command, for
a repository's `Makefile` to include; it carries no compatibility promise.

Contract: openspec/specs/change-workflow/spec.md, CW-r3ka, CW-5qne, CW-m7fk, and
CW-c2tw.
"""
