---
name: change-triage
description: Triage a review of an OpenSpec change with the repository owner — check every finding against the files, state your own position on each, present all of them, record the owner's dispositions and the ledger, ask whether the accepted fixes merit another review round, carry accepted outcomes into the change, and record in `## Next` whether the change advances. For an implementation round, triage the reviews, the validation record, and the owner's own notes together, then fix what the owner accepts and commit it. Use after a review lands in a change's reviews/ directory, when the owner pastes a review or notes, when the owner says "triage the review of <change>", or when `make triage` invokes you.
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
`change-implement` does: the checked-out branch carries the change, or the change's
log holds the owner's decision that it runs on this branch
(`python3 scripts/run_change_step.py log <change> --branch <branch>` prints it),
and the worktree is clean, and `make round-view-closed` passes — while the owner reads the
round (`make round-view`), the branch points at its base, and a fix committed then
would squash the round into it; ask the owner to run `make round-done` first.
Record `HEAD`: it is the base the fixes are made against.

## Running unattended

Run interactively, as most runs are, this section does not apply, and nothing else
in the skill changes. When this skill runs through `scripts/run_change_step.py` —
`make triage UNATTENDED=1`, or the orchestrating session — nobody can answer in
the session, and every turn ends with an outcome matching
`.agents/change-outcome.schema.json`, whose `message` the owner reads as written:

- **A stop for the owner is a question.** Wherever this skill says to stop and
  ask, tell, or wait for the owner, end the turn with `question`: `message` says
  what you found, the options, and your recommendation; `awaiting` names what you
  need. The owner's answer resumes this session; carry on from it.
- **A denied call stops the step only when it cannot go on.** Run one command per
  Bash call: a chained command runs only when every command in it is allowed, so
  if a chained command is denied, run its commands one call at a time. If a single
  command or any other tool call is denied, finish every part of the work that does
  not depend on it. If the step cannot complete without that call, end with
  `stopped`, `reason` naming that exact call and why the step needed it, and
  `denials` listing the calls as you saw them; the wrapper replaces them with the
  run's own record. Otherwise go on and end as the step ends: the wrapper records
  the denial on the outcome whatever it is, and the orchestrating session reads it
  before the change moves on. One denied call is not a denied tool: never report
  the tool as not allowed. Never do by another tool what a denied call would have
  done, and never ask about a denial as a question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **Every reply is a turn.** This step is a discussion: each reply to the owner
  ends its turn with an outcome, the reply in full as its `message` — `question`
  while you wait for the owner's answer or disposition. The orchestrating session
  shows the owner every message and resumes this session with each reply.
- **The end is an outcome.** Each finding you present (step 3) and the question
  whether another round is merited (step 6) is a `question`. When the dispositions
  are recorded, the accepted fixes committed, and `## Next` written, end with
  `finished`, `next` naming what `## Next` leads to. A triage with nothing to
  dispose of asks nothing and ends `finished` (step 6). At a closeout triage, a
  finding whose fix needs code is a `question` naming the correction it needs
  (step 5): the change is archived, so no step takes it back to implementation,
  and the owner directs the correction.

## 1. Find the review and load the context

The change's directory is what `python3 scripts/find_change.py <change>` prints:
`openspec/changes/<change>/`, or, once closeout has archived it, its dated
directory under `openspec/changes/archive/` — a closeout review is always of an
archived change. The reviews to triage are its numbered records in `reviews/` —
`NN-<kind>.md` — that have no `NN-<kind>.triage.md` beside them. Never read
`reviews/transcripts/`: those are raw reviewer sessions, not records.

When the owner pastes a review from elsewhere, save it verbatim as the change's
next numbered record, `NN-<kind>-external.md`, numbered after every file in
`reviews/` and `reviews/transcripts/`, so later reviews read it as history. Never
overwrite a record: if the name exists when you write, take the next number. Its
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
  findings against this change. Read every untriaged validation record, not only
  the latest: an earlier record's `V<n>` failures are presented too, merged with
  any later evidence about them — a later record can show a failure fixed or
  environmental, but its disposition is still the owner's. Only an earlier record
  with no `V<n>` is marked superseded without presenting anything: write it a
  triage file saying so, so no later round picks it up again.
- **The commits.** A review published by `make review` ends with
  `<!-- reviewed-commit: <commit> -->`; a validation record names its `Commit:`.
  For a pasted external review, ask the owner which commit the reviewer saw — a
  snapshot from `make code-snapshot` names it, `<repository>-<short commit>.zip` —
  and append the same `reviewed-commit` comment to the saved record. Name
  every record's commit at the top of its triage file, then compare them before
  anything else. When they differ, the records are a round
  only if the owner waives the rule, judging the changes between the commits: name
  both, summarize what changed (`git log --oneline <reviewed>..<validated>`), and
  ask. Record a waiver in the triage file of each record involved and as one
  ledger line (`"finding": "commit"`, under the review's record name, the owner's
  reason as the disposition). Without a waiver, stop: the reviewed commit is
  validated, or the validated commit reviewed, before the round is triaged.
  A validation record alone — the re-validation of an earlier round's fix commit —
  is triaged only for its `V<n>` failures, each like any finding; a `passed` or
  `inconclusive` one is not routed to triage at all. No round view preceded it, so
  no owner's notes are asked for. Its triage file ends "Evidence for the round
  triaged in `<NN-review>.triage.md`.", naming the earlier round's review, and the
  `## Next` that review's triage recorded still stands.
- **The owner's notes.** Ask for them if the owner has not pasted them. The owner
  reads the round before validation and review, with `make round-view
  CHANGE=<change>`, which shows it as uncommitted changes in the checkout until
  `make round-done`. Save them
  exactly as pasted as the next numbered record, `NN-implementation-owner.md`.
  Label the points `O1`, `O2`, … in the order they appear — in the triage file and
  the ledger only, never in the saved notes — and triage each point like any
  finding: assign its lens, basis, and severity, and take your
  own position. A point the owner raised is advice, like any other; where the
  files contradict it, say so with the evidence. Note each point no review raised
  — it is the clearest sign of a check the guidance is missing.
- **The orchestrating session's observations**, when it wrote any: a numbered
  record `NN-orchestrator.md` of the workflow tooling's misbehaviour across steps.
  Label its points `R1`, `R2`, … and triage each as you do the owner's notes; its
  ledger lines name the record (`NN-orchestrator`), and its triage file ends with
  the evidence line below.

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

Explain each finding as you would to someone across a table: what the change
does now and the reasoning it records for it, what the reviewer argues and
suggests (with any example they gave), what goes wrong if nothing changes — a
scenario, or an example document when the finding is about a representation —
and where you stand, `agree`, `disagree`, or `partly`, and why. That is the
content, not a layout. Write it as a few plain paragraphs that read as one
argument. Never open a paragraph with a run-in bold label ("**What the reviewer
says.**", "**Why it matters.**", "**My position:**"), and never give a part its own
heading or bullet: a reader sees those as a form to fill in, whatever their
typography.

A finding looks like this:

```markdown
### 🟡✅ 20 F2 — tasks.md still says stage 07c hasn't run against a stack
*consistency*

The note on the round-3 fix under section 6 ends "Stage 07c has not run against a
stack: the fix commit's validation runs it." That was true when it was written,
but validation 18 has since run the whole pipeline at `443f9505`, stage 07c
included, and passed, and the ledger records it as confirming the fix. The
reviewer points out that the task notes and the ledger now disagree.

I agree. Someone recording the end-to-end evidence at 7.9 from `tasks.md` alone
would take 07c for unproven and ask for a pipeline run that has already happened.
Narrative compression at closeout would catch it, but it is a one-sentence
correction, and until then the record is wrong.

Evidence: `tasks.md:576`, `reviews/18-validation.md:3`

→ **edit:** replace the sentence with "Validation 18 ran stage 07c at `443f9505`;
it passed."
```

The heading starts with the severity (🔴 blocking, 🟠 should, 🟡 minor) and your
position (✅ agree, ◐ partly, ❌ disagree), then the label and the finding in one
line. The italic line beneath names only the finding's lens, so the owner knows
what kind of defect it is before reading on; its basis and severity go in the
triage record. File and line references go on the evidence line; they support the
argument and never replace it. A finding that is an obvious agreed edit gets one
paragraph. End every finding with a single `→` outcome line.

Present one finding per message, each discussed in full, and wait for the
owner's answer before the next. A summary of every finding up front invites a
disposition before the owner has read the argument, so open the first message
with only an agenda: each finding's label and heading emoji, one line, no
positions.

A finding is disposed of only when the owner states a disposition for its label.
A question about it, a discussion of another finding, or moving on disposes of
nothing; never infer acceptance from silence. Before asking whether another round
is merited, name any finding still without a disposition and ask about it. The owner may answer
several at once or say to batch the rest; never propose it.

Order the findings so that each comes after any decision that could change its
outcome, and otherwise most severe first: disposing of a finding only for a later
decision to overturn it wastes the owner's attention and leaves revised
dispositions behind.

A finding whose outcome is a `decision` is presented as `change-design` presents
one: its context, each alternative with its trade-offs, with an example where it
concerns a representation, and your recommendation with what would change your
mind — in the same prose layout, without a heading or label per part. The owner's
choice of an alternative is the disposition; never ask the owner to accept a
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

## Next

<Advance | Another round> — <the owner's words, and any condition>
```

`## Next` is the triage's last edit, written once step 6 is answered and the
accepted fixes are committed (step 5): `scripts/change_next_step.py` routes the
change on its first words alone, one of two fixed tokens, `Advance` or `Another
round`, and reads a review's triage file without `## Next` as a triage still in
progress, so the change does not move on while its fixes are uncommitted. When two
reviews are triaged together, write the same `## Next` in each review's triage
file. Only a review's triage file has `## Next`. The triage file of a validation
record, of the owner's notes, or of the orchestrating session's observations ends
instead with the line "Evidence for the round triaged in
`<NN-review>.triage.md`.", and is not routed on.

Append a line to the change's tracked `interventions.jsonl` only for a disposition
by which the owner corrects course: deciding otherwise than you proposed — another
outcome, another alternative, a position reversed — or adding context or a
condition that changes the work. A disposition that accepts your proposal as it
stands is not an intervention, and most are not; the triage file records it. Use
the shape `design.md` and the `change-workflow` delta define:

```json
{"review": "03-design", "finding": "F2", "section": null, "lens": "consistency", "basis": "evidence", "severity": "blocking", "agent_position": "agree: <reason>", "owner_disposition": "<what the owner decided>", "summary": "<one line>"}
```

`review` names the record (`NN-<kind>`, `NN-<kind>-external`, `NN-validation`,
`NN-implementation-owner`, or `NN-orchestrator`); `section` is the
`tasks.md` section or `null`. A review finding is always logged under its own
review record, even when it was settled as a design decision;
`"review": "design"` is only for a redirection of a decision no review raised. When
a disposition revises an earlier one, the new entry's `owner_disposition` starts
with `revises <review> <finding>:` so the ledger reads as history rather than as a
contradiction.

After writing ledger entries, say how many you appended and for which findings.
The ledger is often a new, untracked file whose changes do not show in a diff, so
the owner cannot otherwise see that it was written.

## 5. Carry out the accepted outcomes

Ask step 6's question first: once every finding and every point of the owner's
notes has a disposition, and before any outcome is carried out, the owner decides
whether the round's accepted fixes merit another review round, while still present.

- **edit:** make it, and record it in the finding's `Result`.
- **decision:** settled with the owner when it was presented, in the same session, as
  part of the design discussion. Do not settle one yourself, even an obvious one.
  Record each settled decision in the change's `design.md` when the design is
  settled, as `change-design` records decisions.
- **task:** append it to `tasks.md` in the section it concerns, amending rather than
  replacing, with the finding cited in its note.
- **fix, at a closeout triage:** the change is archived, and its code was reviewed
  and validated before closeout, so a closeout triage makes documentation fixes
  only. A finding whose fix needs code is not fixed by the steps below: stop, tell
  the owner what needs to change and why, and wait. The owner decides whether a
  correction is needed and directs it in this session — typically a short design,
  plan, and implementation of it, then `make validate CHANGE=<change>`, which finds
  the archived change, before archive cleanup. Once it is validated, suggest
  a review of the fix's diff — an external one, or `make review KIND=implementation`
  — and say why; whether to have it is the owner's call, and nothing requires it.
- **fix:** once every finding has a disposition, make the accepted fixes, as
  `change-implement` makes a section's changes: the change and the decision it
  rests on, and no more; at the lowest test level that proves it; comments
  describing the current system. Every step is denied edits under `.claude/`, so
  an accepted fix there — the step table, the project's Claude Code settings — is
  made by the orchestrating session or the owner, on the owner's word, and you
  commit it with the round's fixes. Record each in the task notes of the section it
  concerns, naming the finding; a fix that concerns no section goes in a note
  under the last implemented section. Then run `change-implement`'s checks before
  committing (its step 5): `make lock` and `make check-packaging` when a
  dependency changed, the focused suites, `make test`, `make check-comment-hygiene`,
  `make check-doc-citations CHANGE=<change>` (before closeout it may report only
  files the change's tasks create at closeout; name them, and fix anything else),
  `make check-agent-skills` when the
  diff touches `.agents/`, `.claude/`, or `.codex/`, and a fresh-context compliance
  check of the diff against the `HEAD` recorded at the start. In the fix's task
  note, record each check as `change-implement` records a section's evidence: each
  suite with its level as `TESTING.md` defines them and its result, `make test`'s
  result, and what the fresh-context check found and what was fixed or declined —
  so the next review and validation can see what the fix was proven by.
  Commit, as one commit
  naming the change and the round: the fixes, the change documents the dispositions
  edited (`design.md`, `proposal.md`, `tasks.md`), and `interventions.jsonl`.
  The triage records stay in `reviews/`, which is untracked. Do not push: the fix commit is
  validated next (`make validate CHANGE=<change>`), which pushes it.

Then validate and report the result: `openspec validate <change> --strict` for an
active change, or, for an archived one — a closeout triage — `openspec validate
--specs --strict`, since its deltas are merged and the permanent specifications are
what its fixes touched. `python3 scripts/find_change.py <change>` says which.

## 6. Advance, or another round

A review is not a gate: the change advances on what the triage records, and the
owner is asked only what needs their judgement. Once every finding and every point
of the owner's notes has a disposition, and before any fix is made, ask the owner
whether the accepted fixes merit another review round of the same kind.
Recommend, from what the fixes will change: another round when the dispositions
changed a central decision — the representation, an authority boundary, an
interface's operations, or the change's scope — so the reviews just triaged no
longer describe the change, naming the decisions that changed; advancing when the
fixes are corrections the reviewer would only confirm. Record the answer under
`## Next` (step 4) once the fixes are committed: `Advance`, or `Another round`,
followed by the owner's words.

A triage with no finding to present and no point of the owner's notes to dispose of
asks nothing: write `## Next` as `Advance — nothing to dispose of`, and finish.

What follows is the computation's, from that token
(`scripts/change_next_step.py`): after a design review, planning; after an
implementation round, validation of the fix commit, then the next planned round or
the pre-closeout review, once that validation passed; after a pre-closeout review,
closeout once validation of `HEAD` passed; after a closeout review, archive
cleanup, after a validation of `HEAD` when a path outside `openspec/` and `docs/`
changed since the commit it reviewed. `Another round` leads to the review of the
same kind again, after the fix commit's validation for an implementation or
pre-closeout review.

When the triage of a phase-closing review records `Advance`, set the change's
`Status` in `openspec/changes/README.md`, and rewrite the row's `Notes` in the same
edit so nothing in it still describes the phase being left — a row whose notes
contradict its status misleads every agent that reads the index — then run
`make check-change-index`:

| Review | Status when its triage advances |
|---|---|
| `design` | `ready for planning` |
| `implementation` | unchanged — implementation reviews after a section do not close the phase |
| `pre-closeout` | `ready for closeout` — only once the latest validation is `passed` and names `HEAD`, or an ancestor `HEAD` differs from only in changes' ledgers and reviews, unless the owner overrides it |
| `closeout` | unchanged — `in closeout` until archive cleanup writes `archived` |

A closeout triage that advances ends triage. Do not release dependents, set the row
to `archived`, or draft the merge yourself: that is archive cleanup's, in a fresh
session. Tell the owner archive cleanup is next, and end — unattended, `finished`. With `Another round`,
leave the status, and say what the next review of the same kind reads.
