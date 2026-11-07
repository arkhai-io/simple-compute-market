---
name: guidance-review
description: Run a guidance review with the repository owner, interactively in their workspace and outside any change's steps — read every change's ledger, triage records and workflow log since the last review's period, report the dispositions, default acceptances and their revisits against the default rule's measured baseline, a sample audit of `Classification:` lines, waiver recommendations by criterion, and the terms the owner asked about; cluster the owner's corrections into false, unwritten and unenforced guidance; list candidate guidance edits for the owner to pick; write a change's proposal on the owner's word; and append the period's line to the period ledger whatever the owner picks. Use when the owner says "guidance review", "review the guidance", or asks what the owner's corrections say about the guidance since the last review.
---

# Reviewing the guidance against the owner's corrections

The owner's corrections are the evidence of where the guidance is wrong, missing, or
unenforced, and the revisits of default acceptances are the evidence of whether the
default rule is drawn in the right place. A guidance review reads them over a period,
reports what they say, and lists the edits the owner may pick. The owner decides every
edit; you propose, measure, and record.

The **default rule** is the one triage accepts findings by (`change-workflow`'s
CW-d5ac; `docs/agents/change-workflow.md`, "Default acceptance"). Where it was chosen
it was measured as **Rule E**, one of several candidate rules, and its baseline below
carries that name.

This is not a step of a change. It has no node in the workflow graph, no row in the
step table, no outcome, and nothing records it in a change's workflow log. The owner
runs it interactively, in their workspace, which alone holds every cleaned-up change's
records (`docs/agents/change-workflow.md`, "History and removal"). Nothing runs it
unattended; if you are in an unattended run, stop and say so. A change's clone is not
the workspace: if `git remote` lists `workspace`, you are in a clone, whose archive is
lost with it; stop and ask the owner to run the review in their workspace.

It edits nothing tracked unless the owner picks edits and asks for a change (step 5),
and then only that change's proposal and its row in the change index, in a checkout
of their own. Apart from that, the one file it writes is the period ledger's line
(step 6).

## What reaches the repository

Everything you write that the repository keeps — a proposal, its design, a summary
the owner commits — is public (`AGENTS.md`, "Public repository discipline"). Only
aggregates — counts, rates — and the principles drawn from them reach it: no
correction's wording, and no private name, path, identifier, or log. The period ledger
is untracked, and holds figures only.

## 1. Find the period and read its records

The period ledger is `openspec/changes/archive/guidance-reviews.jsonl` in the owner's
workspace: one JSON object per line, one line per guidance review, untracked and
ignored by Git. The period starts at its last line's `end`, or, before the first
review, at a time the owner gives; ask for it, and do not guess one. It ends now,
unless the owner names an earlier end. Both are UTC timestamps, and a record belongs
to the period when its time is after the start and at or before the end, so no record
falls into two periods.

The changes to read are every change, active or archived, with a workflow-log line
inside the period. List them from `openspec/changes/` and `openspec/changes/archive/`.
Find each one's records with `scripts/change-workflow find --records <change>`, which
looks in this checkout; for a change still worked in its own clone, whose records the
workspace does not yet hold, `scripts/change-workflow clone where <change>` names the
clone, and you read its records, and its ledger, there. For each change, read:

- its workflow log, `workflow.jsonl` under its records: each line's `at` places it in
  the period; a triage's outcome line names the records it `triaged`; an orchestrator
  line with `by: owner` and `resumes` is a revisit after the fixes, of a default
  acceptance or of the advancing exit;
- its triage records, `NN-<kind>.triage.md` beside each review, for the records a
  triage inside the period triaged: each finding's position, proposed outcome,
  `Classification:` line where it was accepted by default, and the owner's
  disposition. A finding is counted in the period of its first triage; a resumed
  triage naming it again in a later period counts there only as a revisit;
- its intervention ledger, `interventions.jsonl` in the change's directory: every
  entry added in the period, each placed by the commit that added it (`git log -p`
  over the ledger), whatever record it names — the triages' corrections, a
  `revisits default acceptance:` entry, each waiver line, and the design
  discussion's and planning's corrections, which name `design` or no triaged record;
- the owner's messages in the step sessions the log names, where the triage record
  does not carry what the owner asked — for the terms the owner asked about.

Say which changes you read and which you could not, and why.

## 2. Report the figures

Present each figure with the period's counts beside it, and the earlier periods' from
the ledger for comparison:

- **Dispositions.** Every finding triaged in the period, labelled from its recorded
  disposition: accepted as proposed — the recommended option of a choice among them —
  accepted with added context, meaning a condition, a scope limit, or a fact the agent
  lacked, or overridden or questioned. Give the overall split, and the split by
  position in the round, by what the agent proposed (an edit, a fix, a choice, a
  `task` or `none`), and by record — review, validation record, the owner's notes, the
  orchestrating session's observations.
- **What the discussed findings showed.** For the findings presented to the owner,
  the intervention rate — added context or overridden — with and without each feature
  of the presented text: the agent laid out alternatives, named what would change its
  recommendation, called the fix clear; the reviewer's `Alternatives:` named options;
  the severity was `blocking`. And by topic, tagged from the finding's title, lens and
  proposed outcome alone, never its disposition: specification wording, code made to
  match a specification, an interface or representation, a migration or compatibility
  path, the validation environment, the change's scope.
- **Default acceptances and their revisits.** How many findings were accepted by
  default, and how many of those the owner revisited: before the fix, a `revisits
  default acceptance:` entry with no `--resumes` direction for it in the log; after
  the fix, one with. An entry with `"finding": "next"` revisits the advancing exit,
  not a finding, and is counted under the advancing exit alone. Set the period's
  revisit rate beside Rule E's measured baseline:
  2.7% intervention overall, and about 10% on the changes held out from the
  measurement — those after the date the rule was compared on, which no candidate was
  fitted to. Fixed thresholds over samples this small would be noise; read the rate,
  and the revisits themselves.
- **The advancing exit.** How often triage advanced by default, how often it
  recommended another round and the owner agreed, and how often the owner revisited
  an advancing exit: a `revisits default acceptance:` entry with `"finding":
  "next"`, before the fix or, with its `--resumes` direction, after.
- **The classification audit.** Sample default acceptances across the period's
  changes — all of them when there are a dozen or fewer, else at least ten, spread
  across changes and triages — and read each `Classification:` line against its
  finding and the reviewer's `Alternatives:` field: did each condition of the default
  rule hold as the line says? The likeliest drift is in "no alternative": an
  alternative the finding's text implies and the line does not record. Report the
  sample's size, each disagreement with its finding, and whether the disagreements
  share a cause.
- **Waivers.** Each waiver a step recommended, by criterion
  (`docs/agents/change-workflow.md`, "Waivers"), and the merge's, by its own judgement,
  with how many the owner took; a recommended waiver the owner declined is a ledger
  correction. Note waivers the owner gave that no step recommended, by reason.
- **Terms the owner asked about.** Each word or mechanism the owner asked an agent to
  explain, with how often, and whether its home defines it — the homes `AGENTS.md`'s
  "Domain docs" names. An undefined term the owner asked about is a candidate entry,
  unless the change that met it added the entry then.

The labelling is your reading of recorded text: say so, and say which counts a
different reading of a handful of findings would move.

## 3. Cluster the owner's corrections

Extract each correction's general principle — from the ledger's entries, and from
accepted judgement findings — and cluster them. Where several changes carry copies of
the same dispositions, such as changes planned together from one plan, count them
once, and say so. Check each cluster against the guidance (the documents
`scripts/change-workflow config load common` prints, `docs/agents/change-workflow.md`,
the skills) and the
repository's `check-*` targets, and place it in one of three kinds:

- **guidance that is false:** the guidance says one thing and the owner repeatedly
  does another;
- **rules applied but unwritten:** the owner applies a principle no document states;
- **rules written but unenforced:** a written rule reviews keep catching breaches of,
  which no check enforces, and whether one could.

A guidance finding that reached a review is evidence of a written rule not followed
or not enforced; a judgement finding the owner accepts, or a correction the owner
makes, is a candidate unwritten rule. Report each cluster with its count of changes
and corrections and where the guidance stands on it.

## 4. List the candidate edits

List each candidate edit for the owner to pick, as a design lists principles for the
owner to promote: what it would change, in which document or check, the evidence for
it, and your recommendation. Among them always:

- whether to keep, narrow, or widen the default rule, from its revisits and the audit:
  narrowed where revisits or disagreements share a cause, widened only on evidence
  that a class it excludes is corrected about as rarely as the class it admits;
- whether any waiver criterion has earned acceptance by default, from how often the
  owner took its recommendations;
- whether revisits have become frequent enough to fold into the workflow graph.

Test a proposed rule as Rule E was tested: state it in the workflow's own terms rather
than fitting it to the data, and measure it on the earlier changes and, held out, on
the later ones. A rule fitted to cover more of the earlier changes at a lower rate
did not hold on the later ones when Rule E was chosen — about 2% rose to 10–14% — so a
widening that holds only on the data it was drawn from is no evidence.

Ask in prose, each option and your recommendation written out (`AGENTS.md`, "Asking
the owner"). The owner may pick, narrow, reword, or pick nothing.

## 5. Write the proposal, on the owner's word

When the owner picks edits and asks for a change, write its `proposal.md` as
`openspec/README.md` asks of a proposal: why — the period it covered and the figures
behind each edit, in aggregate — what changes, and its permanent documentation impact.
Write it, with its `ready for design` row in the change index, in a worktree on a new
branch from `origin/dev`, as `change-design` writes a prerequisite's proposal ("When
the design needs another change first"), never on a branch another change is worked
on, and check the index there as that procedure does. The owner commits it and opens
its pull request. The change then goes through the workflow like any other; its design
discussion settles the edits' wording.

## 6. Record the period

Whatever the owner picks, nothing included, append one line to
`openspec/changes/archive/guidance-reviews.jsonl` — creating it if this is the first
review — with the Write or Edit tool, as one JSON object:

```json
{"start": "2026-11-05T00:00:00Z", "end": "2026-12-03T16:40:00Z", "changes": 9, "findings": 140, "default_acceptances": 38, "revisits_before_fix": 1, "revisits_after_fix": 0, "advancing_revisits": 0, "audit_sample": 12, "audit_disagreements": 1, "waivers": {"paths": {"recommended": 4, "accepted": 4}, "environmental": {"recommended": 2, "accepted": 1}, "commits": {"recommended": 1, "accepted": 1}, "design": {"recommended": 0, "accepted": 0}, "merge": {"recommended": 1, "accepted": 1}}, "proposal": "<change>"}
```

- `start` and `end`: the period, as UTC timestamps; the next review starts at this
  `end`.
- `changes` and `findings`: how many changes and triaged findings it read.
- `default_acceptances`, `revisits_before_fix`, `revisits_after_fix`, and
  `advancing_revisits`: step 2's figures.
- `audit_sample` and `audit_disagreements`: the audit's size and its disagreements.
- `waivers`: the recommendations and how many the owner took, by criterion — `paths`,
  `environmental`, `commits` and `design`, the four criteria in the order "Waivers"
  lists them — and `merge`, the merge's own judgement.
- `proposal`: the change whose proposal it wrote, by name, or `"none"`.

A review that picks nothing writes no proposal and still records its period, so the
next review does not count it twice and has its figures to compare with.

## 7. Report

Tell the owner what the review read, the figures, the clusters, the edits picked, the
proposal written or none, and the line recorded.
