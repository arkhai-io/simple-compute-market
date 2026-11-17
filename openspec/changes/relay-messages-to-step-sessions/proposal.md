# Relay messages to a change's step sessions

## Why

A triage states its own position on every finding and puts each one it does not
accept by default to the owner (`openspec/specs/change-workflow/spec.md`, CW-j1nv and
CW-neua). When the triage disagrees with the reviewer, the owner hears the triage's
side and the reviewer's original finding, and nothing more. The reviewer never hears
the triage's answer, so it cannot concede, hold its position with new evidence, or
weigh the triage's proposed fix against its own.

The workflow can resume a reviewer's session today, in two narrow cases: to send back
a draft the format check refused, and when the next review of the same kind starts
(CW-clhl and the review runner, `scripts/change_workflow/review.py`). Neither serves a
waiting triage. A new review of the same kind runs every question of its kind again
and is logged as a step of its own. A fresh reviewer starts without the reasoning that
found the issue. In both cases the point is lost: the reviewer has already noticed the
issue, and the owner wants to correct its reasoning, or offer it new suggestions, and
have it weigh the possible solutions again.

`relay-vm-access-without-a-dashboard` met this in the triage of its design review 06.
The triage disputed both the mechanism and the severity of finding F1, and the owner
wanted the reviewer's own answer before deciding:

- A session outside the change resumed the reviewer's Codex session by hand, read-only,
  with the triage's position as its prompt.
- It saved the reply as `08-design-external.md`, a record that claims to come from
  outside the workflow.
- The owner then told the orchestrating session about the record, so the triage would
  read it.

The reviewer conceded the mechanism, lowered the severity, and added two corrections
the triage had missed, which changed the triage's recommendation. The exchange was
worth having, but every step of it happened outside the workflow, and its result
reached the triage through a file instead of through the orchestrating session.

The same change met a second gap. A session above the orchestrating session — a
**coordinator**, holding context the change's own sessions do not — had input for the
change's steps:
- constraints from outside the change that the implementation had to meet;
- owner notes for an implementation round;
- the reviewer exchange above.

The coordinator has no way to reach the orchestrating session. Each time, it wrote its
input in its reply, and the owner pasted it into the orchestrating session by hand.

## What Changes

- **The owner can consult a review's reviewer through the orchestrating session.** On
  the owner's direction, the orchestrating session resumes the session of the reviewer
  that wrote the review the waiting triage is triaging. It sends the owner's message to
  that reviewer and relays the reply back. The reviewer runs on its own harness and
  model, read-only, as in the review. The reply returns through the orchestrating
  session, to the owner and to the waiting step's session, which continues with it.
  It is not written to a file for the step to find.
- **A coordinator can message an orchestrating session.** A message names the change
  and its target: the waiting design or triage session, or the reviewer through the
  consultation above. The orchestrating session relays it to that target automatically,
  without asking the owner, and attributes it to the coordinator. The handbook and the
  orchestrate skill state the procedure.
- **Each relay is logged.** The change's workflow log records each consultation and
  each coordinator message: who sent it, its target, the reviewer's session for a
  consultation, and the outcome. The reviewer's session is kept as review transcripts
  are.

### Decided by the owner

- **D1 — A consultation continues the reviewer's own session.** It never starts a fresh
  reviewer, and never falls back to another harness or model. A session that cannot be
  resumed is refused, with the reason.
- **D2 — Consulting the reviewer is the owner's option, taken on their word.** No step
  consults the reviewer by itself, and a triage does not consult it before presenting
  a disputed finding.
- **D3 — One direction, one exchange.** The reviewer answers once. Its reply may change
  the triage's recommendation. The owner directs another exchange if they want one.
- **D4 — The reply returns through the orchestrating session, not through a file.** No
  numbered record is written for it, and no record of the external kind is used to
  carry it.
- **D5 — This change lands before `add-workflow-harness-adapters` and
  `add-change-intake`, and neither covers it.** Harness adapters generalize launching
  and resuming any step on any harness, and intake prepares a change that arrives from
  outside the workflow. This change uses the review runner's existing resume support
  for Codex and Claude. Whichever of it and `add-workflow-harness-adapters` lands
  second moves that resume behind the adapter.

### Open for design, not decided here

- **The channel.** How a coordinator's message reaches the orchestrating session: an
  engine command that appends it to the change's state for the orchestrating session to
  read between turns, which is harness-neutral and recorded; the harness's own messaging
  between sessions; or the command for the record, with the harness's messaging to wake
  the orchestrating session. Where a message waits while a step runs, and in what order
  several are relayed.
- **A coordinator message's standing.** Under CW-neua no agent's agreement disposes of
  a finding. Whether a coordinator message that carries the owner's words — a
  disposition, a direction, a waiver — may be relayed as the owner's, or whether those
  must always come from the owner directly. In either case, how the log attributes it.
- **The consultation's targets.** Whether the owner, or a coordinator, may consult a
  reviewer only while a triage of that reviewer's review is waiting, or also while the
  review's design or implementation discussion is open. Which reviewer is meant when a
  triage triages two reviews together.
- **What the reviewer is sent.** The owner's or coordinator's words as written, inside
  a frame the engine adds: the review and finding it concerns, the triage's position on
  it, any commits since the reviewed commit, that the reviewer is read-only, and that
  it answers once. Whether the reply has a shape — for example, a stance per finding,
  held, revised or withdrawn, with its severity and preferred alternative — and whether
  a format check holds it to that shape.
- **How the waiting step takes the reply.** Whether it resumes the step's session as a
  turn of its own, attributed to the reviewer, or is carried in the owner's next reply.
  How a triage file records the exchange in its position and result for a finding.
- **The engine surface.** Whether a consultation is a run of its own, with a log line
  and a step name outside the graph, or an entry on the waiting run's line. Whether a
  coordinator message is a new log line kind. Both are judged against `change-workflow`'s
  compatibility requirement (CW-c2tw).
- **When the reviewer cannot answer.** A usage limit, an unavailable model, or an
  expired session: the consultation stops and the owner is told, with no fallback (D1).
  Whether the engine checks that a session can be resumed before it relays anything.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `change-workflow`: the owner's consultation of a review's reviewer through the
  orchestrating session; a coordinator's message to an orchestrating session and its
  relay; their log entries.

### New Capabilities

None.

## Non-Goals

- A consultation a step starts by itself (D2).
- A debate. One direction is one exchange (D3).
- A new review. A consultation runs no question of the review kind, publishes no
  review, and adds no graph node.
- What a coordinator decides, or how it coordinates the work around a change. This
  change gives it a way to reach an orchestrating session; its work is its own.
- Running a writing step on another harness. That is `add-workflow-harness-adapters`'.
- Taking in a change that arrives from outside the workflow. That is
  `add-change-intake`'.

## Impact

- `scripts/change_workflow/review.py` (resuming the reviewer for a consultation),
  `scripts/change_workflow/cli.py` (the consultation and message commands),
  `scripts/change_workflow/log.py` and `scripts/change_workflow/next_step.py` (their log
  entries, and a message waiting for its target), and their tests.
- `.agents/skills/change-orchestrate/` (relaying a consultation and a coordinator's
  message), `.agents/skills/change-triage/` and `.agents/skills/change-design/` (taking
  a reviewer's reply or a coordinator's message as a turn).
- `openspec/specs/change-workflow/` (`spec.md`, `index.md`, `README.md`) and
  `docs/change-workflow-handbook.md`.

### Workflow engine interfaces

- A new command, or subcommand, for a consultation, and one for a coordinator's
  message. Compatible additions.
- New log entries for each, as design settles (the engine surface, above). If they add
  a line kind or a step name, design judges that against CW-c2tw.
- The graph and the review kinds are unchanged.

## Dependencies and Related Changes

- None. It lands before `add-workflow-harness-adapters` and `add-change-intake` (D5).
- `add-workflow-harness-adapters` will move the consultation's resume behind the
  harness adapter, if it lands second.
- `host-change-workflow-runner` attributes directions to whoever gave them. This
  change's attribution of a coordinator message is designed so that work can take it
  over.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: `change-workflow`'s
`spec.md` and `README.md` for the consultation, the coordinator's message and their
log entries; `docs/change-workflow-handbook.md` for how the owner consults a reviewer
and how a coordinator messages an orchestrating session.
