# The change workflow

How an OpenSpec change moves from design to archive with agent skills: which skill
each step uses and how to start it, how one orchestrating session carries a change
through its steps, what a review leaves behind, and where the owner's corrections
are recorded. The phases, the closeout parts, and the rules each step follows are
in [`openspec/README.md`](../../openspec/README.md); the status a change is in, and
what it waits on, are in its row of the
[change index](../../openspec/changes/README.md). The workflow's contract is the
[`change-workflow` specification](../../openspec/specs/change-workflow/spec.md),
and why it is shaped as it is, its
[architecture companion](../../openspec/specs/change-workflow/architecture.md).

## Skills

Each step is a leaf skill under `.agents/skills/`, loaded by Claude Code from
`.claude/skills/` and by Codex from `.codex/skills/`, both links to the one source
(`make check-agent-skills` fails otherwise). A skill does one step and stops. The
owner starts a step by hand, or lets the orchestrating session start each in turn
(below). Start each in a fresh session unless its row says otherwise, so it reads
the change's files rather than an earlier session's memory.

| Step | Skill | Start it with | Writes |
|---|---|---|---|
| Design | `change-design` | `make design CHANGE=<change>` | `design.md`, `proposal.md`, the spec deltas, the index row |
| Design review | `change-review` | `make review CHANGE=<change> KIND=design` | `reviews/NN-design.md` |
| Planning | `change-plan` | `make plan CHANGE=<change>`, once the design review's triage advances the change | `tasks.md`, ending with the closeout task |
| Implementation | `change-implement` | `make implement CHANGE=<change> [SECTION=<n> \| SECTIONS=<n-m>]` | each section's code and tests, its task notes, one commit per section |
| Implementation review | `change-review` | `make review CHANGE=<change> KIND=implementation` | `reviews/NN-implementation.md` |
| Validation | `change-validate` | `make validate CHANGE=<change>` | `reviews/NN-validation.md`; pushes `HEAD` and runs the pipeline |
| Triage | `change-triage` | `make triage CHANGE=<change>` | `reviews/NN-<kind>.triage.md` ending with `## Next`, `interventions.jsonl`, accepted fixes, the index row when a phase-closing review's triage advances the change |
| Pre-closeout review | `change-review` | `make review CHANGE=<change> KIND=pre-closeout` | `reviews/NN-pre-closeout.md` |
| Closeout | `change-closeout` | `make closeout CHANGE=<change>` | permanent documents, the promotion record, the archived change, one commit |
| Closeout review | `change-review` | `make review CHANGE=<change> KIND=closeout` | `reviews/NN-closeout.md` |
| Archive cleanup | `change-archive-cleanup` | `make archive-cleanup CHANGE=<change>` | the index (dependents released, row `archived`), any waiver as a ledger line, one commit, `reviews/pull-request.md` |
| Orchestration | `change-orchestrate` | `make orchestrate CHANGE=<change>` | `orchestrator` and `round` lines in the workflow log, the owner's notes on a round, its own observations of the tooling |

Every step but the review opens an interactive Claude Code session. With
`UNATTENDED=1` the same target runs the step headless instead, through
`scripts/run_change_step.py`: held to its step's permissions in
`.claude/change-steps.toml`, on its step's models, ending with an outcome appended
to the change's workflow log. `make plan` unattended resumes the design step's
session; `FRESH=1` starts a fresh one. The review always runs unattended.

An unattended step runs one command per Bash call, and does a read the permissions
refuse through the Read tool instead. Two shapes are refused by the harness itself,
whatever the step's rules allow, and each costs a denial on the run's line: a
`find` over `/` or `/etc`, and a path that climbs with `..` after a `cd`
(`cd <dir>; cat ../tasks.md`, or `cd ..`). Read such a file with the Read tool, or
name its path from the repository root. A wrapper stopped by SIGTERM logs its run
`stopped`, naming the signal, with the session to resume; one killed by SIGKILL
leaves no line.

The order is the one the phases give: design and its review until the design
review's triage advances the change; planning; then, per implementation round,
implementation, its review beside validation of the same commit, and one triage of
both; a pre-closeout review and its triage; closeout; the closeout review and its
triage; archive cleanup. A review is not a gate: its triage records under `## Next`
whether the change advances (`Advance`) or another review round runs (`Another
round`), asking the owner which once every finding is disposed and before any fix.

A step that finds the change in the wrong state refuses and says why. Design and
implementation take only an active change. Closeout archives the change as its last
step, so every step after it — the closeout review, its triage, validation, archive
cleanup — finds the change under `openspec/changes/archive/` by its name
(`python3 scripts/find_change.py <change>`). `make review KIND=closeout` refuses a
change that is not archived, and `make archive-cleanup` one that is not.

`make check-change CHANGE=<change>` runs a step's closing checks — comment hygiene,
the agent skills, the change's citations and task list, the change index, and the
pinned strict OpenSpec validation — printing only failures and one pass line. `make
check-tasks CHANGE=<change>` fails when a numbered task sits under another section's
heading; the steps that act on a task list run it first.

Ask the owner questions in prose, never through a multiple-choice selector
(`AGENTS.md`, "Asking the owner").

## Orchestrating a change

`make orchestrate CHANGE=<change>` opens one Claude Code session that carries the
change through its steps: it runs the step `scripts/change_next_step.py` computes,
each unattended through its `make` target, shows each step's message as written,
and sends your reply back as written. It forms no view of a finding or a design
question. It commits nothing while a step runs; when a step closes leaving work its
own skill does not commit, the session commits that work as its own commit and
pushes it. It stops for you at the design discussion's questions,
your reading of each implementation round, the triage discussion, and anything no
rule settles — an environmental remedy, a denial that needs a rule, a proposed
return, a stopped step; every other step follows without asking.

**Starting and resuming.** The session keeps no state of its own: on every start
and after compaction it recomputes where the change stands from the files and the
workflow log. Resuming a change is running `make orchestrate` again.
`make change-next CHANGE=<change>` prints the same computation in plain form — the
step, its reason, and for a run waiting on you its `seq` and what it asks.

**Stating the cadence.** The design settles the change's implementation cadence:
how many sessions implement the work and how much each round covers before it is
reviewed, written in terms of the work, such as "one round, one session" or "round
1: the contract changes; round 2: the handlers and the migration". Planning orders
its sections by it and reports the mapping as the `rounds` on its log line; the
orchestrating session records each round as it starts. A change planned with no
cadence is asked about once per round.

**Following a running step.** The session says when it starts a long unattended
turn. `make change-watch CHANGE=<change>` follows each step's progress file in
another terminal — one line per tool call — moving to the next step's as it starts,
and into the archive when closeout moves the change there.

**Answering and taking over.** A step that asks ends its turn with a question; your
answer, relayed by the orchestrating session, resumes the same session by the
waiting run's `seq`. Between turns you can take a step over with
`claude --resume <session>`, the session id on its log line, and hand back; never
resume one concurrently. The orchestrating session rereads the files afterwards.

**Maintaining the step table.** `.claude/change-steps.toml` gives each step its
skill, its allow and deny rules, and its models in priority order with their
effort. No step may edit it: a rule or model changes as a tracked edit you commit.
The orchestrating session reads each run's denials from its log line
(`python3 scripts/run_change_step.py denials <change> <seq>`) and proposes the
narrowest rule for a gap, either granted for one resumed run or as a table edit. A
row never names a Fable or Astra model, nor two models of one vendor. `REVIEW_MODEL`
and `REVIEW_EFFORT` (below) are yours for a review run by hand, not the table's.

**Reading the cost.** `make change-cost CHANGE=<change>` totals the change's
unattended runs by step, by round, and by whether a run opened its session, missed
the prompt cache, or read it, with the misses and the gap before each. Dollars a run
could not be told from its session's other turns show as a range. The figures are
the harness's list prices.

**Completing names.** Source `scripts/completions/make-change.bash` from your
`~/.bashrc`, after bash-completion, to complete `CHANGE=` with the active changes —
the archived ones after `archive-cleanup` — and `KIND=` with the review kinds.

## Reviews

`make review` runs the reviewer read-only on the review row's models: Codex in its
read-only sandbox first, and `change-review` on Claude, held to reading, when Codex
is not installed, not signed in, or at its usage limit; the record and its log line
name the reviewer's harness and model. It captures the reviewer's final message,
checks that it is a review of the kind and change asked for — its sections in
order, and every finding carrying a lens, a basis, a severity, and evidence — and
only then publishes it under the next number. A review continues the previous
reviewer's session of the same kind on the same harness, so a second design review
knows what the first asked; `FRESH=1` starts a new one. `REVIEW_BASE` is the branch
the diff is taken against (`dev` by default), and `REVIEW_MODEL` and
`REVIEW_EFFORT` are the owner's choice of reviewer for one run, outside the step
table's policy: `REVIEW_MODEL` replaces the review's models with the one named, a
`claude-` model running on Claude and any other on Codex, with no fallback, and the
record and its log line mark the run as an override. The orchestrating session
never sets them. A pre-closeout review refuses until the latest validation passed
and names `HEAD`, or an ancestor that differs only in the change's ledger and
reviews; `UNVALIDATED=1` overrides that. `make design-review CHANGE=<change>` is
shorthand for `KIND=design`.

A review run elsewhere — in a browser session, by another tool — is pasted into
triage, which saves it verbatim as the next record, `NN-<kind>-external.md`, and
triages it with any other review of the same kind.

Before an implementation round is triaged the owner reads it:
`make round-view CHANGE=<change>` pushes `HEAD`, starts the end-to-end pipeline, and
shows the round as uncommitted changes in the checkout, over the commit recorded as
the round started; `make round-done` returns the branch to the round's commit.
While a round view is open, every step that could commit refuses (`make
round-view-closed`). The owner's notes on the round go to triage with the reviews;
under orchestration, the orchestrating session opens and closes the view and saves
the notes.

### The review directory

Each change keeps its review history in `reviews/`, which is untracked and moves
with the change into the archive:

```text
openspec/changes/<change>/reviews/
  01-design.md                       a review: summary, assessment, questions, findings
  01-design.triage.md                each finding's position and the owner's disposition
  02-implementation.md               an implementation review, run beside 03
  03-validation.md                   validation of the same commit
  04-implementation-owner.md         the owner's notes on the round, verbatim
  02-implementation.triage.md        one triage file beside each record triaged
  03-validation.triage.md
  04-implementation-owner.triage.md
  05-design-external.md              a review pasted from elsewhere
  06-orchestrator.md                 the orchestrating session's observations of the tooling
  pull-request.md                    archive cleanup's merge drafts
  workflow.jsonl                     one line per unattended run and per orchestrator decision
  transcripts/
    01-design.log                    the reviewer's whole session
    07-implement.jsonl               an unattended step's event stream
    07-implement.progress            one line per tool call, as `make change-watch` shows it
```

Files are numbered in the order they were produced, so the directory reads as the
change's history; no file is overwritten, and a run whose answer was not a review
publishes nothing and is kept beside its transcript as
`transcripts/NN-<kind>.rejected.md`. A numbered review is the
only record of its findings. Transcripts are kept for the owner's export of the
change's history, and no review or triage step reads them. Archive cleanup leaves
the directory in place.

`workflow.jsonl` is written by `scripts/run_change_step.py` alone: each run's
outcome with its session, commit, model, cost, and denials; each `round` line; and
each `orchestrator` line, a decision naming the run it resolves or whose denials it
read and the step it directs. `python3 scripts/run_change_step.py log <change>`
prints it.

The three steps that edit the index — triage when a phase-closing review's triage
advances the change, closeout, and archive cleanup — run `make check-change-index`
after each edit. It checks each row's cell count; its link to its change's
directory (an `archived` row links its archive, and a row linking an archive is
`archived` or `in closeout`); its status against the legend; that each dependency
is listed and not archived; and that every active change directory has exactly one
row. An archived change needs no row: archived rows may be pruned from the index
over time.

## The ledger

`interventions.jsonl`, beside the change's other files and tracked, records each
time the owner corrected course: decided otherwise than the agent proposed, or
added context or a condition that changes the work. A disposition that accepts the
agent's proposal is recorded only in the triage file. One JSON object per line:

```json
{"review": "03-design", "finding": "F2", "section": null, "lens": "consistency", "basis": "evidence", "severity": "blocking", "agent_position": "agree: <reason>", "owner_disposition": "<what the owner decided>", "summary": "<one line>"}
```

`review` names the record the finding came from, or `design` for a redirection no
review raised; `section` is the `tasks.md` section, or `null`. An entry that revises
an earlier one starts its `owner_disposition` with `revises <review> <finding>:`.
When the owner waives archive cleanup's validation of a correction outside
`openspec/` and `docs/`, archive cleanup records it as a line under the closeout
review's record with `"finding": "validated"` and the owner's reason. Read together,
a change's ledgers show where the guidance or the skills fell short.
