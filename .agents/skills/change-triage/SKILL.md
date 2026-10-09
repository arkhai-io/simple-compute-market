---
name: change-triage
description: Triage a review of an OpenSpec change with the repository owner — check every finding against the files, state your own position on each, present all of them, record the owner's dispositions and the ledger, carry accepted outcomes into the change, and ask whether the review's gate is passed. For an implementation round, triage the reviews, the validation record, and the owner's own notes together, then fix what the owner accepts and commit it. Use after a review lands in a change's reviews/ directory, when the owner pastes a review or notes, when the owner says "triage the review of <change>", or when `make triage` invokes you.
---

# Triaging a review

A review is advice. The owner decides what to do with each finding, and reads every
one. Your job is to make that reading fast and well-founded: check each finding
against the files, say plainly whether you agree and why, and propose what to do.
You are the agent working the change, so you are neither the reviewer's ally nor
the change's defender. A finding is not right because a reviewer raised it, and
not wrong because it criticizes work you did. Agreement needs a reason exactly as
disagreement does.

Change nothing in response to a finding until the owner has disposed of it.

**An implementation round** is the reviews of a commit's implementation, the
validation of the same commit, and the owner's own notes on its diff, triaged
together in one session — a fresh one, not the implementing session. It follows
every step below, with three additions: the validation record and the owner's notes
are inputs (step 1); you fix what the owner accepts, in this session, and commit it
(step 5); and the fix commit is validated again.

It is an implementation round when any untriaged record is an implementation
review, a validation record, or the owner's notes, or when `make triage` opened the
session for a change `in implementation`. Before anything else, check as
`change-implement` does: the checked-out branch carries the change, and the
worktree is clean. Record `HEAD`: it is the base the fixes are made against.

## 1. Find the review and load the context

The reviews to triage are the change's numbered records in
`openspec/changes/<change>/reviews/` — `NN-<kind>.md` — that have no
`NN-<kind>.triage.md` beside them. Never read `reviews/transcripts/`: those are raw
reviewer sessions, not records.

When the owner pastes a review from elsewhere, save it verbatim as the change's
next numbered record, `NN-<kind>-external.md`, numbered after every file in
`reviews/` and `reviews/transcripts/`, so later reviews read it as history. Its
findings may carry no lens, basis, or severity; you assign them in step 2 and say
that you did.

When two reviews of the same kind await triage — typically one from `make review`
and one pasted — triage them together. Where both raise the same issue, present it
once, naming both findings.

For an implementation round, also take:

- **The validation record** of the commit the reviews describe — the latest
  `NN-validation.md`, with no triage file beside it. Its `V<n>` failures, caused by
  the commit or of unknown cause, are findings: lens `testing`, basis `evidence`,
  severity `blocking`. Check each diagnosis against the logs it cites, under
  `.snapshot/`, rather than trusting it. Its `## Environment` entries and an
  `inconclusive` part are missing evidence, never findings: say what evidence is
  missing and whether the round can be judged without it. Observations it records
  about other changes or about the validation tooling are presented, not triaged as
  findings against this change. Earlier untriaged validation records are
  superseded by the latest: write each a triage file saying so, so no later round
  picks it up again.
  If the validation names a commit other than the one the reviews describe, or
  there is none, say so before anything else: name both commits and summarize what
  changed between them (`git log --oneline <reviewed>..<validated>`), and ask the
  owner whether to triage on that evidence or validate the reviewed commit first.
  Proceed only on the owner's word.
  A validation record alone — the re-validation of an earlier round's fix commit —
  is a round of its own: a `passed` record with no `V<n>` needs only its triage
  file saying it confirms that commit; any `V<n>` is triaged like any finding, with
  the owner's notes asked for as usual.
- **The owner's notes.** Ask for them if the owner has not pasted them. Save them
  verbatim as the next numbered record, `NN-implementation-owner.md`, label its
  points `O1`, `O2`, … in the order they appear, and triage each point like any
  finding: assign its lens, basis, and severity, and take your
  own position. A point the owner raised is advice, like any other; where the
  files contradict it, say so with the evidence. Note each point no review raised
  — it is the clearest sign of a check the guidance is missing.

Each issue has exactly one label for its whole life: its finding ID, or the joined
IDs of merged duplicates (`03 F2 / 04 F4a`). Carry that label into the design
discussion and the records. Do not introduce a second numbering — questions,
corrections, or new decision numbers — for issues a review already named.

Then read what you need to judge the findings: `AGENTS.md` and the documents it
requires, every file in the change, earlier reviews and their triage, and the code,
specifications, and guidance each finding cites.

## 2. Check every finding

For each finding, open what it cites and decide:

- **Position:** `agree`, `disagree`, or `partly`, with the reason and your own
  evidence. Where the finding is factually wrong, show the file that says so.
  Where it is right but its suggested action is not the best fix, say `partly` and
  propose the better one.
- **Classification:** its lens, basis, and severity, keeping the reviewer's unless
  you disagree with them, and saying so when you change them.
- **Outcome if accepted**, one of:
  - **edit** — a correction with one evident fix to the change's documents, which
    you will make;
  - **decision** — the fix requires choosing between real alternatives, which is
    design work: it goes to the design discussion (`change-design`), not into an
    edit you choose yourself;
  - **task** — work for a later section, appended to `tasks.md` in the section it
    concerns, preserving completed tasks;
  - **fix** — in an implementation round only: a change to the code, tests, or
    documentation that this session makes after the dispositions (step 5);
  - **none** — the finding is informational or already handled.
- **Section:** the `tasks.md` section the finding concerns, when it concerns one.

A finding that challenges a decision the owner made ("Challenges D<n>") is never
dismissed on the grounds that the owner decided it. State the decision's recorded
rationale, whether the challenge defeats it, and recommend; the owner reaffirms or
changes the decision.

## 3. Present every finding

The owner must be able to decide every finding from what you write, without
opening the review, the design, or the code. A one-line claim and a pointer-laden
position are not enough: the owner needs the design's current state and the
consequence, not only the reviewer's objection.

For each finding, write five parts:

- **What the change says now.** The decision, requirement, or text the finding
  concerns, and the reasoning the change records for it, in plain words.
- **What the reviewer says.** Their reasoning and suggested fix, including any
  example they gave.
- **Why it matters.** A concrete consequence if nothing changes — a scenario, or,
  when the finding is about a representation, an example document.
- **Your position.** `agree`, `disagree`, or `partly`, argued in prose. File and
  line references go on an evidence line beneath it; they support the argument
  and never replace it.
- **If accepted.** The outcome, as classified in step 2.

Present in two passes.

Before the first pass, check each finding against the decisions still open in the
second pass. A finding whose outcome could change with an open decision does not
belong in the first pass: hold it, and say which decision it waits on. Disposing of
it early only for the decision to overturn it wastes the owner's attention and
leaves revised dispositions behind.

**First pass, in one message:** every finding that needs no choice between
alternatives — outcomes `edit`, `task`, `fix`, or `none`, and findings you disagree
with —
ordered by lens (`direction`, `consistency`, `architecture`, `testing`,
`documentation`, `scope`, `readiness`) and within a lens by severity. Close by
listing, by label only, the findings left for the second pass. The owner disposes
of the first pass together, often tersely by label; follow up only where an answer
is ambiguous.

**Second pass, one finding per message:** every finding whose outcome is a
`decision`. Present it as `change-design` presents a decision — its context,
each alternative with its trade-offs and examples where it concerns a
representation, and your recommendation with what would change your mind. Here the
owner's choice of an option is the disposition; never ask the owner to accept a
problem whose fixes they have not been shown. Record the choice as the settled
decision in the design discussion, under the finding's label.

## 4. Record the dispositions

Write `reviews/NN-<kind>.triage.md` beside each record triaged — the validation
record and the owner's notes included — in this form:

```markdown
# Triage — <NN-kind> — <change>

### F1 — <the finding in one line>

- **Lens / basis / severity:** <as triaged; note any change from the reviewer's>
- **Position:** <agree | disagree | partly> — <reason, with evidence>
- **Proposed outcome:** <edit | decision | task | fix | none> — <what>
- **Owner disposition:** <what the owner decided, in their terms>
- **Result:** <what was done: the edit made, the decision sent to design, the task added, the fix made>

## Gate

<Whether the owner passed the review's gate, in their words, and any condition.>
```

Append one line per disposition to the change's tracked `interventions.jsonl`, in
the shape `design.md` and the `change-workflow` delta define:

```json
{"review": "03-design", "finding": "F2", "section": null, "lens": "consistency", "basis": "evidence", "severity": "blocking", "agent_position": "agree: <reason>", "owner_disposition": "<what the owner decided>", "summary": "<one line>"}
```

`review` names the record (`NN-<kind>`, `NN-<kind>-external`, `NN-validation`, or
`NN-implementation-owner`); `section` is the
`tasks.md` section or `null`. A review finding is always logged under its own
review record, even when it was settled in the second pass as a design decision;
`"review": "design"` is only for a redirection of a decision no review raised. When
a disposition revises an earlier one, the new entry's `owner_disposition` starts
with `revises <review> <finding>:` so the ledger reads as history rather than as a
contradiction.

After writing ledger entries, say how many you appended and for which findings.
The ledger is often a new, untracked file whose changes do not show in a diff, so
the owner cannot otherwise see that it was written.

## 5. Carry out the accepted outcomes

- **edit:** make it, and record it in the finding's `Result`.
- **decision:** settled with the owner in the second pass, in the same session, as
  part of the design discussion. Do not settle one yourself, even an obvious one.
  Record each settled decision in the change's `design.md` when the design is
  settled, as `change-design` records decisions.
- **task:** append it to `tasks.md` in the section it concerns, amending rather than
  replacing, with the finding cited in its note.
- **fix:** once every finding has a disposition, make the accepted fixes, as
  `change-implement` makes a section's changes: the change and the decision it
  rests on, and no more; at the lowest test level that proves it; comments
  describing the current system. Record each in the task notes of the section it
  concerns, naming the finding; a fix that concerns no section goes in a note
  under the last implemented section. Then run `change-implement`'s checks before
  committing (its step 5): `make lock` and `make check-packaging` when a
  dependency changed, the focused suites, `make test`, `make check-comment-hygiene`,
  `make check-doc-citations CHANGE=<change>`, `make check-agent-skills` when the
  diff touches `.agents/`, `.claude/`, or `.codex/`, and a fresh-context compliance
  check of the diff against the `HEAD` recorded at the start. Commit, as one commit
  naming the change and the round: the fixes, the change documents the dispositions
  edited (`design.md`, `proposal.md`, `tasks.md`), and `interventions.jsonl`.
  The triage records stay in `reviews/`, which is untracked. Do not push: the fix commit is
  validated next (`make validate CHANGE=<change>`), which pushes it. Say whether
  the fixes also need another review round; the owner decides.

Then run `openspec validate <change> --strict` and report the result.

## 6. The gate

Every review is a gate, and only the owner passes it. Ask explicitly whether the
gate is passed, and record the answer in the triage file. Triage being finished is
not the gate passing: while an accepted `blocking` finding's fix has not landed, or
a decision it raised is still open, the change stays in its phase, and the owner
decides whether the fix needs another review round.

When the owner passes a phase-closing gate, set the change's `Status` in
`openspec/changes/README.md`, and rewrite the row's `Notes` in the same edit so
nothing in it still describes the phase being left — a row whose notes contradict
its status misleads every agent that reads the index:

| Review | Status when its gate passes |
|---|---|
| `design` | `ready for planning` |
| `implementation` | unchanged — implementation reviews after a section do not close the phase |
| `pre-closeout` | `ready for closeout` — only once the latest validation names `HEAD` and is `passed`, unless the owner overrides it |
| `closeout` | `ready for archival` |

When the gate does not pass, leave the status, and say what must happen before the
next review.

When the dispositions changed a central decision — the representation, an authority
boundary, an interface's operations, or the change's scope — the reviews just
triaged no longer describe the design. Recommend another review round of the same
kind before the gate is passed, and say which decisions changed.
