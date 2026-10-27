# Observations of the orchestrating session

A second set of observations of the workflow's own tooling, recorded after the
design review's triage. None is commentary on a step's finding or a design
question.

## O3. A denial inside a step's subagent reaches neither the workflow log nor the transcript

**What happened.** The triage's closing message (workflow log seq 84) says "One
call was denied. It was a background wait I tried while the verification agents
ran, and it was not needed. The wrapper records it." The wrapper recorded
nothing: seq 84's `denials` is empty, the harness `result` event in
`transcripts/59-triage.jsonl` carries `permission_denials: []`, and the parent
transcript holds no wait, sleep or Monitor call. The denied call therefore ran
inside one of the triage's verification subagents, whose events the harness
does not surface to the parent's result.

**Effect.** The orchestrating session reads every denial through the log line,
as the skill requires, and that reading is only as complete as the harness's
report. A subagent can be denied a call, or do denied work another way, with
nothing on the line for the orchestrator to classify. This run's case was
harmless, since the step itself reported it.

**For the owner to decide.** Whether the wrapper should also read each
subagent's transcript for denials, if the harness exposes them, or whether a
step's rules should forbid subagents from the tools its own row denies. Nothing
in this change depends on it.
