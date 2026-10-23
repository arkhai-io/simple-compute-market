# Observations of the orchestrating session

Observations of the workflow's own tooling across the steps of
`unbacked-bare-metal-listings`, recorded for the next triage. None is commentary
on a step's finding or a design question.

## O1. A headless step run inherits the orchestrating session's id, so a resume reopens the wrong conversation

**What happened.** The design step's first run (workflow log seq 1) ended with a
question. Its log line records `session` as `47fb56bb-a6e7-56ca-a2e9-60a7a2db6d59`,
which is the orchestrating session's own id: the environment the orchestrator runs
in sets `CLAUDE_CODE_SESSION_ID` to that value, and `scripts/change_workflow/harness.py`'s
`claude_command` passes no `--session-id`, so the headless child took the parent's.
Resuming seq 1 with the owner's answer (seq 7) therefore loaded the orchestrating
conversation under the design step's permissions, with none of the design session's
context, and that run stopped itself with the explanation on its log line.

**Evidence.**
- `reviews/workflow.jsonl` seq 1: `"session": "47fb56bb-a6e7-56ca-a2e9-60a7a2db6d59"`,
  the same value as the orchestrating session's `CLAUDE_CODE_SESSION_ID`.
- `reviews/transcripts/01-design.jsonl` and `02-design.jsonl`: every event carries
  that session id.
- seq 7: `"outcome": "stopped"`, its `reason` naming the fault, `"gap_s": 1`,
  `"cache_hit": false`, and a negative partial `usd` (`-17.70`, `usd_partial`
  true), since the cost reader subtracted the parent conversation's earlier turns.
- seq 1's denied `Monitor` call watched subagent outputs under the orchestrating
  session's task directory, showing the child wrote into the parent's session.

**Effect.** No answer can reach a step that asks, in this environment: every resume
of a run started from the orchestrating session reopens the orchestrator. The
design session's investigation (seq 1's message) is intact on its log line; its only
file edit was the index row set to `in design`.

**A fix in the tooling, for the owner to decide.** Give each fresh headless run its
own session: pass `--session-id <new uuid>` in `claude_command` when `session` is
None, or run the child with `CLAUDE_CODE_SESSION_ID` removed from its environment.
The resume path already passes `--resume <session>` and needs no change once the
recorded id is the child's own. The cost reader's negative partial dollars (seq 7)
follow from the same fault and need no separate fix.

## O2. The stop hook asks the orchestrating session to commit a step's uncommitted work

`~/.claude/stop-hook-git-check.sh` ends each of the orchestrator's turns asking it
to commit and push any uncommitted change. While a design step runs, its index-row
edit is uncommitted by design, and the orchestrator must not commit it. The hook
is the owner's own, outside the repository, so this is noted only so the triage
knows why those turns ended with the request unactioned.
