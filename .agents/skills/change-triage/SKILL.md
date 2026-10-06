---
name: change-triage
description: Triage a review of an OpenSpec change with the repository owner — check every finding against the files, state your own position on each, present all of them, record the owner's dispositions and the ledger, carry accepted outcomes into the change, and ask whether the review's gate is passed. Use after a review lands in a change's reviews/ directory, when the owner pastes a review from elsewhere, or when the owner says "triage the review of <change>".
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
  - **task** — work for implementation, appended to `tasks.md` in the section it
    concerns, preserving completed tasks;
  - **none** — the finding is informational or already handled.
- **Section:** the `tasks.md` section the finding concerns, when it concerns one.

A finding that challenges a decision the owner made ("Challenges D<n>") is never
dismissed on the grounds that the owner decided it. State the decision's recorded
rationale, whether the challenge defeats it, and recommend; the owner reaffirms or
changes the decision.

## 3. Present every finding

Present all of them, none withheld for being minor or uncontested, ordered by lens
— `direction` first, then `consistency`, `architecture`, `testing`,
`documentation`, `scope`, `readiness` — and within a lens by severity. For each:

- the finding in one line, with its review and number (`03-design F2`);
- what it claims, recapped so the owner need not open the review;
- your position, with its reason and evidence;
- the outcome you propose if it is accepted.

Then ask for a disposition of each. The owner often answers tersely by number;
follow up only where an answer is ambiguous or a decision needs more than a word.

## 4. Record the dispositions

Write `reviews/NN-<kind>.triage.md` beside each review triaged, in this form:

```markdown
# Triage — <NN-kind> — <change>

### F1 — <the finding in one line>

- **Lens / basis / severity:** <as triaged; note any change from the reviewer's>
- **Position:** <agree | disagree | partly> — <reason, with evidence>
- **Proposed outcome:** <edit | decision | task | none> — <what>
- **Owner disposition:** <what the owner decided, in their terms>
- **Result:** <what was done: the edit made, the decision sent to design, the task added>

## Gate

<Whether the owner passed the review's gate, in their words, and any condition.>
```

Append one line per disposition to the change's tracked `interventions.jsonl`, in
the shape `design.md` and the `change-workflow` delta define:

```json
{"review": "03-design", "finding": "F2", "section": null, "lens": "consistency", "basis": "evidence", "severity": "blocking", "agent_position": "agree: <reason>", "owner_disposition": "<what the owner decided>", "summary": "<one line>"}
```

`review` names the record (`NN-<kind>` or `NN-<kind>-external`); `section` is the
`tasks.md` section or `null`.

## 5. Carry out the accepted outcomes

- **edit:** make it, and record it in the finding's `Result`.
- **decision:** list the decisions for the design discussion and leave them open.
  Do not settle a design decision during triage, even an obvious one; the owner
  settles designs in `change-design`.
- **task:** append it to `tasks.md` in the section it concerns, amending rather than
  replacing, with the finding cited in its note.

Then run `openspec validate <change> --strict` and report the result.

## 6. The gate

Every review is a gate, and only the owner passes it. Ask explicitly whether the
gate is passed, and record the answer in the triage file. Triage being finished is
not the gate passing: while an accepted `blocking` finding's fix has not landed, or
a decision it raised is still open, the change stays in its phase, and the owner
decides whether the fix needs another review round.

When the owner passes a phase-closing gate, set the change's `Status` in
`openspec/changes/README.md`:

| Review | Status when its gate passes |
|---|---|
| `design` | `ready for planning` |
| `implementation` | unchanged — implementation reviews after a section do not close the phase |
| `pre-closeout` | `ready for closeout` |
| `closeout` | `ready for archival` |

When the gate does not pass, leave the status, and say what must happen before the
next review.
