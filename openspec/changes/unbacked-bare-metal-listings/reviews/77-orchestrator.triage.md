# Triage — 77-orchestrator — unbacked-bare-metal-listings

These are the orchestrating session's observations, and the record names no commit. The
record numbers its one point O6; it is labelled R1 here.

### R1 — A wrapper killed from outside leaves no line in the workflow log

- **Lens / basis / severity:** process / evidence / minor (assigned; the record gives none)
- **Position:** agree. A wrapper killed with its session writes no outcome, so the log
  cannot tell a run still going from one that died, and the next-step computation keeps
  reading the last line.
- **Proposed outcome:** none in this change: the owner's direction on the SIGTERM line and
  on the launch limit recorded for the workflow tooling, or the handler added to this
  round's commit if the owner preferred. Asked: (1) should the wrapper write a `stopped`
  line on SIGTERM, (2) should long rounds launch outside any per-task limit, (3) here or
  in the workflow tooling.
- **Owner disposition:** "1. Yes. 2. no 3. this commit." Later, through the orchestrating
  session before 83 R1: "I have changed my mind on the two-hour kill. Keep doing as you
  were." — long runs keep launching outside the per-task limit.
- **Result:** `scripts/change_workflow/wrapper.py` installs a SIGTERM handler on the main
  thread for the run (`_termination_ends_the_run`), and a terminated run writes a `stopped`
  outcome naming the signal; a wrapper unit test sends SIGTERM to a running turn.
  `docs/agents/change-workflow.md` says so. Nothing changed for point 2. Ledger entry
  appended.

Evidence for the round triaged in `85-implementation.triage.md`.
