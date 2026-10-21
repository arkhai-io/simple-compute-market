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
| Design | `change-design` | `make design CHANGE=<change>` | `design.md`, `proposal.md`, the spec deltas, the index row, one commit once the design is settled |
| Design review | `change-review` | `make review CHANGE=<change> KIND=design` | `reviews/NN-design.md` |
| Planning | `change-plan` | `make plan CHANGE=<change>`, once the design review's triage advances the change | `tasks.md`, ending with the closeout task, one commit |
| Implementation | `change-implement` | `make implement CHANGE=<change> [SECTION=<n> \| SECTIONS=<n-m>]` | each section's code and tests, its task notes, one commit per section |
| Implementation review | `change-review` | `make review CHANGE=<change> KIND=implementation` | `reviews/NN-implementation.md` |
| Validation | `change-validate` | `make validate CHANGE=<change>` | `reviews/NN-validation.md`; pushes `HEAD` and runs the pipeline |
| Triage | `change-triage` | `make triage CHANGE=<change>` | `reviews/NN-<kind>.triage.md` ending with `## Next`, `interventions.jsonl`, accepted fixes in one commit, the index row when a phase-closing review's triage advances the change; whatever it edited that no fix commit holds, in one commit of its own |
| Pre-closeout review | `change-review` | `make review CHANGE=<change> KIND=pre-closeout` | `reviews/NN-pre-closeout.md` |
| Closeout | `change-closeout` | `make closeout CHANGE=<change>` | permanent documents, the promotion record, the archived change, one commit |
| Closeout review | `change-review` | `make review CHANGE=<change> KIND=closeout` | `reviews/NN-closeout.md` |
| Archive cleanup | `change-archive-cleanup` | `make archive-cleanup CHANGE=<change>` | the index (dependents released, row `archived`), any waiver as a ledger line, one commit, `reviews/pull-request.md` |
| Orchestration | `change-orchestrate` | `make orchestrate CHANGE=<change>` | the change's clone and branch, `orchestrator` and `round` lines in the workflow log, the owner's notes on a round, the ledger line of a waived design review, workflow commits on your word, its own observations of the tooling |

Every step but the review opens an interactive Claude Code session. With
`UNATTENDED=1` the same target runs the step headless instead, through
`scripts/run_change_step.py`: held to its step's permissions in
`.claude/change-steps.toml`, on its step's models, ending with an outcome appended
to the change's workflow log. `make plan` unattended resumes the design step's
session; `FRESH=1` starts a fresh one. The review always runs unattended.

Every step that commits — design, planning, implementation, triage, closeout, and
archive cleanup — pushes each commit right after through `make push-branch`, the
guarded push of exactly `HEAD`, the only push a step may make. A pushed branch
starts nothing: validation dispatches the end-to-end pipeline itself.

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
pushes it. It also creates the change's clone and branch (below), and on your word
commits changes to the workflow itself — skills, the step table, anything else you
name — in the change's clone, on its branch, so they take effect for its next step
and land with it. It stops for you at the design discussion's questions, your
reading of each implementation round, the triage discussion, and anything no rule
settles — an environmental remedy, a denial that needs a rule, a proposed return, a
stopped step; every other step follows without asking.

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
`claude --resume <session>`, the session id on its log line, run in the checkout
the step ran in, since a session is keyed by its checkout's path; hand back, and
never resume one concurrently. The orchestrating session rereads the files
afterwards.

**Maintaining the step table.** `.claude/change-steps.toml` gives each step its
skill, its allow and deny rules, and its models in priority order with their
effort. No step may edit it: a rule or model changes as a tracked edit, which you
commit, or which the orchestrating session commits on your word in the change's
clone.
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

## A change in its own clone

Each change can be worked in a clone of your workspace of its own, so several
changes run at once without moving each other's branch: your workspace — your
editor project — meets a change's workflow only when you read one of its rounds.
Clones live beside the workspace, one directory per change under
`<workspace>.changes/<change>/`. A clone holds the change's branch, its
`reviews/` with the workflow log and transcripts, its wheelhouse and
environments, `.snapshot/`, and its step sessions.

**Creating it.** `make orchestrate CHANGE=<change>`, started in the workspace,
creates the clone when the change's branch is checked out neither there nor in a
clone, by running `make change-clone CHANGE=<change> [BRANCH=feat/<change>]
[FROM=dev]` in the workspace, with another `BRANCH` or `FROM` when you name one —
a branch started from another change's branch; you can run it by hand too. It
clones the workspace locally, sets the clone's `origin` to the workspace's and
adds a `workspace` remote naming the workspace, and checks out the branch — the
existing one, or a new one from `FROM` — at its furthest point between the
workspace's copy and `origin`'s, refusing one where the two have diverged; the
branch tracks `origin`'s, never the workspace's. It links the clone's
`.claude/settings.local.json` to the workspace's and starts `make init` in the
background. It is safe to run again: it finishes a clone left incomplete, restarts
a failed bootstrap, and refuses, deleting nothing, a directory that is not a clone
of the workspace, has another branch checked out, or has uncommitted changes.

**The bootstrap.** `make init` in the clone is running, succeeded, or failed —
failed when it exited non-zero or its process died without recording a status —
and its log is in the clone's Git directory. Design and planning go on while it
runs; implementation, validation, and every later step wait for it. A failed
bootstrap comes to you naming its log, almost always for a reason in the
environment, and is never retried by itself: `make change-clone CHANGE=<change>`
restarts it.

**Running steps.** From the clone on, the orchestrating session computes the
change there and drives every step with `make -C <clone> <step> CHANGE=<change>
UNATTENDED=1`, so the log, the transcripts, and the step sessions are the clone's.
To take a step over, resume its session from the clone:
`cd <clone> && claude --resume <session>`.

**Reading a round.** Once a round's sections are committed, validation and the
implementation review start in the clone, and you read the round in your
workspace beside them. `make round-view CHANGE=<change>`, run in the workspace,
refuses a dirty workspace, naming the files, an unattended run in progress there,
and another change's open view; it fast-forwards the workspace's copy of the
change's branch from the clone, refusing one that has diverged or holds a commit
of yours triage has not pulled, checks it out, and resets it to the round's base,
so the round shows as uncommitted changes. Run again while the view is open, it
moves the view to the branch's new head over the same base, to follow triage's
fixes, unless you have edits or commits in the view. The clone's branch never
moves. `make round-done` returns the branch to the round's head and the workspace
to where it was — staying on the branch when you have uncommitted edits, which it
leaves for you.

A commit you make on the branch during the view — your editor's "commit all"
included — is carried onto the round's head when the view closes, each holding
exactly the paths it changed, with its author and message; `make round-done`
prints each beside its replacement, and drops one that holds nothing beyond the
round. Where the round also changed a path, the commit must hold every change the
round made to it: `make round-done` refuses, moving nothing and naming the file
and the way back (`git reset --mixed <head>`, then commit again on the round's
head), a commit holding part of a file the round changed, an edit inside a line
the round changed, an edit of a file the round added, a binary file, a symlink, or
a mode the round changed when not as the round left it, a merge, and a branch
moved off the round's base by an amend, reset, or rebase. Triage pulls your
commits into the clone, fast-forward only, and presents each as one of your points
on the round.

**A change worked in the workspace.** A change can still be worked in your
workspace with no clone, its branch checked out there; the tooling tells the cases
apart by whether a clone holds the change's branch. Its round view resets that
branch in place, so you read the round before validation and the review start, and
the view is never refreshed.

**Moving a change already under way into a clone.** A change whose records are in
the workspace's `reviews/` is not cloned automatically: a clone copies what Git
tracks, and `reviews/` is ignored. The orchestrating session brings it to you with
two routes: check out its branch in the workspace and go on there, or move it into
a clone by hand:

1. Settle any run waiting on an answer, in the workspace, since its session is
   keyed to the workspace's path.
2. Merge `dev` into the change's branch, so its tooling knows clones.
3. Run `make change-clone CHANGE=<change>` in the workspace.
4. Copy the change's `reviews/`, and the validation evidence its records name
   (`.snapshot/validation/<commit>/`, `.snapshot/e2e-logs/<run>/`), to the same
   paths in the clone; check with `diff -r` that the copies are identical, then
   remove the workspace's.

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
`make round-view CHANGE=<change>` shows the round as uncommitted changes over the
commit recorded as the round started, and `make round-done` returns the branch to
the round's commit. For a change in its own clone the view is in the owner's
workspace, beside the round's validation and review ("A change in its own clone",
above). For a change worked in the workspace the view moves the branch its steps
run on, so it comes first, and while it is open every step that could commit
refuses (`make round-view-closed`). The owner's notes on the round go to triage
with the reviews; under orchestration, the orchestrating session opens and closes
the view and saves the notes.

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
