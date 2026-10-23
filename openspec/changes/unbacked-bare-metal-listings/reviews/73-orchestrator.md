# Observations of the orchestrating session

A third set of observations of the workflow's own tooling, recorded after
planning. None is commentary on a step's finding or a design question.

## O4. The planning line carries five subagent denials that belong to the design run

**What happened.** Workflow log seq 98, the planning run, lists fifteen denials.
Five of them name subagents ("Verify design corrections C1-C8", "Investigate
Helm defects 11.2 11.4 11.5", "Investigate defects 11.1 11.3 11.6", "Investigate
Alkahest questions 12.1-12.6") and repeat calls already read on lines 12 to 19
as the design run's (seq 11). Planning resumes the design session, and the
first version of the subagent-denial reader (`4c4d04c`'s predecessor, `1de6ee1`)
read every subagent transcript under the session's directory, not only those
the resumed run itself started.

**Fix.** `4c4d04c` keeps the run's tool-call ids and reads only the subagents
whose record names one of them as the starting call. Later lines are unaffected;
seq 98's five stale entries stay as recorded, since the log is append-only, and
the orchestrator's readings on lines after 98 say so.

## O5. The harness refuses some read-only calls on its own, with no rule involved

Two shapes are refused by the harness itself ("the Bash call was refused"), not
by a permission rule, as direct tests under the step's own rules showed: a
`find` over `/` or `/etc`, and a path that climbs with `..` after a `cd`
(`cd <dir>; cat ../tasks.md`, `cd ..`). Each reaches the log line as a denial
with reason `mode`, and no rule can admit it; the orchestrator's readings on
seq 98 record them as gaps no rule answers. Steps avoid them by reading with
the Read tool or by naming paths from the repository root.
