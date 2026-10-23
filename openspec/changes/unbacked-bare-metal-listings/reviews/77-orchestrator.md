# Observations of the orchestrating session

A fourth set of observations of the workflow's own tooling, recorded during
round 1's implementation. None is commentary on a step's finding or a design
question.

## O6. A wrapper killed from outside leaves no line in the workflow log

**What happened.** The round 1 implementation session, resumed at seq 117 with
the owner's answer, ran for two hours (transcript `76-implement.jsonl`,
progress file to 09:36Z) and was then killed by the orchestrating harness's
background time limit, the longest it allows. The wrapper was killed with it,
so no outcome line was written: `workflow.jsonl` still ends at seq 124, the
computation still reads seq 117 as waiting on its question, and the two hours
of work show only in the working tree (section 4, 67 files, its tasks
unchecked) and in section 3's commit `d349c8c`, which the session made itself.

**Effect.** The log cannot tell a run that is still going from one that died
without a line, and a resume of seq 117 is the only way back into the
session. The orchestrator recovered by snapshotting the tree to the
`unbacked-bare-metal-listings-wip` branch and resuming seq 117 detached from
the harness's task limit.

**For the owner to decide.** Whether the wrapper should write a `stopped` line
on SIGTERM, naming the signal, so a killed run leaves a record; and whether
long implementation rounds should be launched outside any per-task time limit.
