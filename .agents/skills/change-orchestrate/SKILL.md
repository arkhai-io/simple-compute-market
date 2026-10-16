---
name: change-orchestrate
description: Advance one OpenSpec change through its leaf skills from one session, using the next-step computation and workflow log, relaying discussion turns and every gate to the owner. Use when the owner says "orchestrate <change>" or make orchestrate invokes you.
---

# Orchestrating one change

Carry only the change you were given between its steps. The leaf skills do the
work in their own sessions; the owner decides every gate and design question.
Never commit, create this change's branch, open its pull request, or start another
change. The owner commits design-phase work and permission-table edits; leaf
steps commit what their own skills authorize. This session uses the owner's
interactive permissions; the step table limits unattended runs only.

## Recover from the files

On every start and after compaction, read `AGENTS.md` and its required documents,
this skill, and the result contract in `scripts/change_next_step.py`. Run:

```text
python3 scripts/change_next_step.py <change>
python3 scripts/run_change_step.py log <change> --last 10
```

Act on that result. Recompute after each completed turn, decision, or owner
takeover, rereading the log as needed. Keep no routing state in memory alone.
Leave the detailed loading of code, specifications, and reviews to each leaf.
If a round view is open, handle that reading first: the branch points at its base
until it closes. Start no leaf step while it is open.

Files prevail over a disagreeing log: say what disagreed and record why you
followed the files. If the computation errors or answers `unclassified`, inspect
its reported inputs and the files. Decide routing or recovery yourself only when
it passes no gate, answers no design question, and changes no status; record the
decision and evidence through `note`. Otherwise bring the evidence, options,
and your recommendation to the owner in prose and wait. Never silently replace
the computation with your own transition table.

## Run the computed step

For `design`, `plan`, `implement`, `triage`, `validate`, `closeout`, or
`archive-cleanup`, run `make <step> CHANGE=<change> UNATTENDED=1`. Pass computed
implementation `sections` as `SECTIONS=<comma-separated-ids>`; each session
implements its agreed sections in order, committing each separately. For
`review`, run `make review CHANGE=<change> KIND=<computed-kind>`: review already
uses the wrapper and Codex. For `validate-and-review`, start validation with
`UNATTENDED=1` and the review with its computed `KIND` side by side. Wait for both
outcomes before triage and keep their waiting runs distinct. Never advance with a
process still running or bypass a guard that refuses. A failed review has no
published result; an earlier record does not count.

Before any long-running unattended turn, tell the owner what is running and give
`make change-watch CHANGE=<change>` to follow it in another terminal. This
includes a discussion resumed to apply fixes or run checks. Read its current
progress file under `reviews/transcripts/` when the owner asks for status; the
harness's task panel does not show wrapper runs. Send a push notification through
the harness's available notification facility on a `question`, `stopped`, or a
long step finishing. If none is available, tell the owner delivery is unavailable
and show the message here; never claim a push was sent or configure an external
delivery service yourself.

Planning normally resumes the design session through the wrapper. If that
session has grown large, offer a fresh planning session (`make plan
CHANGE=<change> UNATTENDED=1 FRESH=1`) and use it on the owner's choice. Closeout
and archive cleanup are delegated like other steps, with their questions relayed;
archive cleanup drafts the merge message and pull request for the owner to publish.
Recompute after every outcome; its free-text `next` is not a routing command.

## Relay each discussion turn

Read every outcome and show each discussion message in full, keeping its options,
evidence, and recommendation intact. Do not summarize away a finding or answer
a leaf's question for the owner. Design, planning, and triage stay conversations;
every gate goes to the owner even if every finding is uncontested.

For `owner`, inspect the reason and any named `seq`. Read that run's outcome,
including `message` and `awaiting`; read its denials first, as below. Put a
`question` to the owner and wait. Resume the same session with the reply:

```text
python3 scripts/run_change_step.py resume <change> --seq <waiting-seq> --answer <owner-answer>
```

Use the waiting `seq` the computation names, never the last run in the log: a
review ending beside a validation question must not receive its answer. Recheck
that the run still waits before resuming. Pass the owner's answer faithfully,
with proper shell quoting or structured command arguments.

A `returned` outcome proposes an earlier phase. Bring its evidence and
recommendation to the owner; leave the status unchanged until confirmation.
Record confirmation with `--by owner --resolves <returned-seq> --next <step>`
(`plan` for planning). Recompute; the directed leaf sets its phase's status.
A declined return also needs an explicit owner disposition. A repeat review the
owner requests after a failed gate records `--next review --kind <kind>` with no
`resolves`: a failed gate is a triage-file state, not a waiting run.

A prerequisite `blocked` outcome halts this workflow. Relay what the owner must
do; never orchestrate the prerequisite. Design writes its proposal in a separate
worktree branched from dev. The owner commits and merges it to dev, then merges
dev here before this change records its dependency. After the prerequisite is
archived and merged here, propose releasing the dependency. Only on the owner's
word remove it from this change's row, keep `in design`, run
`make check-change-index`, record the decision, and recompute. An absent
prerequisite or another external blocker goes to the owner.

Between turns the owner can take over with `claude --resume <session-id>`; never
resume concurrently. On handback reread the files and log and recompute rather
than presuming the direct conversation's result. For `done`, report the archived
change and stop; the owner creates its pull request.

## Read every denial before advancing

Read `denials` from the run's workflow-log line, never its message. Every outcome
can carry them, even one that finished and moved the phase on. Run:

```text
python3 scripts/run_change_step.py denials <change> <seq>
```

Inspect each denial and the later calls it reports. A later call doing the denied
work by another means is a workaround: do not trust the outcome until the owner
has seen it. A denied chain retried as separate allowed commands alone does not
establish a workaround. One denied call is not a denied tool.

Classify by the harness's `reason`: `mode` means a missing allow rule, a gap; a
deny-rule match is forbidden. Until its value is verified, any value other than
`mode` is not a gap; take an unknown value to the owner. Never grant a deny-rule
denial: an allow cannot override it. For a gap propose the narrowest matching
rule, distinguishing a one-run `--allow` on a stopped run's resume from a routine
tracked edit in `.claude/change-steps.toml` for the owner to commit. Never widen
permissions silently. An unnecessary call may need no rule; explain why.

Record the reading through `note orchestrator --by orchestrator --reads <seq>`:
the decision begins `gap:`, `forbidden:`, or `workaround:` and names the call,
rule (or why none), and evidence. Every forbidden or workaround reading goes to
the owner, whose disposition is a second decision line with `--by owner`.

A reading resolves nothing. A question is still answered; a return is still
decided. The owner chooses recovery of a stop: resume its waiting `seq` with the
answer and any narrowly granted `--allow <rule>`, only after the owner grants it.
Do not resolve it first: the wrapper refuses a resolved run. The resumed run
supersedes the stop. If the stop is not recovered (rerun fresh, fix first, or
abandon), record a separate decision with `--resolves <stopped-seq>` and its
reason. Leave other waiting runs untouched and recompute.

## Agree and carry an implementation round

When the computation asks for a round, discuss which unfinished sections, how
many sessions, and how many sections are reviewed together. Give options and a
recommendation in prose. Warn about long sessions without imposing one section
per session. Before implementation record the owner's agreement:

```text
python3 scripts/run_change_step.py note <change> round --sections '1,2;3' --by owner
```

This is one session for 1 and 2, another for 3, all reviewed as one round. For
an agreement recorded after the fact add `--after <highest-record-before-round>`;
do not count that round's own records as preceding it. Recompute and run its
computed sessions without another permission question about agreed sections.

For `round-view`, run `make round-view CHANGE=<change>` in this session: it
pushes and dispatches the pipeline, then shows the committed round as uncommitted
changes in the owner's checkout. Wait for the owner's reading and notes. Save
the notes verbatim as the next `reviews/NN-implementation-owner.md`, choosing a
number after all numbered records and transcripts and using exclusive creation.
Never overwrite a record. If there are no findings, save the owner's actual reply
so the reading is recorded. On restart with a view open, recover its round head
from Git's view state and finish that reading; preserve notes already saved.

Once the owner finishes, run `make round-done`. Preserve any edits it reports;
never discard or commit them to force a clean checkout. Recompute only after the
view closes. Validation adopts the view's pipeline through its baseline. Start
validation and the implementation review side by side when computed; their
records and the owner's notes go to a fresh triage session together. Triage
commits accepted fixes, which are validated again and reviewed again when the
owner requires. Green checks never pass a gate on the owner's behalf.

## Record decisions through the wrapper

The wrapper alone writes `reviews/workflow.jsonl`. Use:

```text
python3 scripts/run_change_step.py note <change> orchestrator --by <owner-or-orchestrator> --decision <decision> --reason <reason>
```

Add `--reads <seq>` for the run whose denials were read, `--resolves <seq>` only
for the run settled, and `--next <step>` for a direction, with `--kind <kind>`
for review. A confirmed return resolves its run; a repeat review names no run.
Record every routing or recovery decision, the owner's included, with its reason.
Never append log lines by hand or clear one run with a decision about another.
Leaf skills record gates, design decisions, and the intervention ledger: relay
the owner's answer to the waiting leaf rather than substituting your own record.
