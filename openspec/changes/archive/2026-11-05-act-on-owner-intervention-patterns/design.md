# Design: accept uncontested triage outcomes, and write down what the owner does

Status: settled in the design discussion of 2026-11-04. The owner set the direction
first (D1–D14, recorded before the discussion opened). The discussion then settled
the batch rule, how revisits and interrupts work, the reviewer's alternatives, the
guidance-review skill, waivers, the mechanical checks, and the wording and placement
of each guidance edit. Corrections found while loading the change reshaped several
of these; they are folded into the context below. The triage of design review 20
amended D15 (the review runner's interrupt, and the run's identity as a held lock),
D17's place in the cadence, D20 (a period ledger), and D24 (the key-block measure, and
a seventh check for the lock revision). The triage of design review 31 made D15 record
the window between its last lock check and the signal as an accepted risk, gave D24's
private-key check to gitleaks, and put D24's uv-version guard in `uv_project.py` for
the repository's relock and refresh commands. The triage of design review 38 replaced gitleaks' default
private-key rule with a repository rule that cannot join two blocks, and made its
commit scans read merge patches. Implementation's gate on that rule (section 5) passed
every key case and returned the change to design over gitleaks' other default rules,
which fired 114 times on the tree; the design discussion of 2026-11-05 reviewed each
finding and settled D25–D30: a credential the scan found is replaced, the gate runs
the default rules minus the four that misfire, and a full-rule audit beside it is run
by hand before an official build ships. The triage of design review 55 narrowed D24
item 7's guard to the repository's relock and refresh commands, a plain `uv run` left
to the revision check, and made D30 carry D25–D29 into the closeout task.

After round 1, `dev` was merged in, bringing a restructured workflow: one command,
`scripts/change-workflow`, over the `scripts/change_workflow/` package; the workflow's
specification split into `change-workflow`, the engine any adopting repository runs
(prefix `CW`), and `market-change-workflow`, how this repository runs it (prefix
`MCW`), each organized by an `index.md` of requirement ids; and each capability's
companion renamed from `architecture.md` to `README.md`
(`openspec/README.md#a-capability-organized-by-an-index`). Planning then re-targeted
this change without changing what it decides. The delta's rules now follow dev's
convention of one rule per requirement, each with an id: the engine's —
interrupts, revisits, waivers, guidance reviews, default acceptance, the table,
reviewers' alternatives, and the ledger's two new entries — in `change-workflow`, with
`CW-9pbk`, `CW-3tvs`, `CW-j1nv` and `CW-neua` modified where default acceptance
contradicts them, and `CW-zkhs` and `CW-e7lm` for a waived part of validation (D22); this repository's — the closing checks, the secret scan and its
audit, and the lock revision — in `market-change-workflow`. Their `index.md` entries
are written with the deltas, since the index check fails a change whose delta adds an
id its index omits. Destinations that named `change-workflow`'s `architecture.md` name
its `README.md`, under the same headings; the "Secret scanning" section lives in
`market-change-workflow`'s `README.md`, as the merge placed it. The context below names
the requirements as they stand after the merge.

## Context

### Triage

- **Every finding reaches the owner, one per message.** In
  `openspec/specs/change-workflow/spec.md`, `CW-j1nv` requires every finding to be
  presented, none withheld for being minor or uncontested, and `CW-neua` disposes of
  one only when the owner states a disposition. `CW-3tvs` requires an orchestrated
  triage to present one decision or finding per turn. `CW-neua` requires the owner's
  disposition of each finding before any is acted on, and its scenario "A reviewer and
  the implementing agent agree" says so outright.
- **The skill forbids proposing a batch.** `.agents/skills/change-triage/SKILL.md`
  section 3 orders findings most severe first, after any decision that could change
  them. The owner may answer several at once, but the agent never proposes it.
- **The reason is recorded.** `openspec/specs/change-workflow/README.md`, "Triage",
  says a summary up front invites dispositions before the arguments are read, and
  that a question about one finding is not acceptance of another. "The owner is
  interrupted only for judgement" lists each finding's disposition and the
  another-round question among the owner's moments, and the document's opening says
  the owner reads every finding. A default-accepted finding is still read, in a
  table, but is never presented as a summary inviting a disposition, and silence
  never disposes of a discussed finding.
- **The gate question is asked every round.** `CW-9pbk` requires
  triage to ask whether the dispositions merit another review round before any fix.
- **A message reaches the owner only at a turn's end.** An unattended triage's
  `question` waits for the owner's reply; its `finished` outcome comes after its
  fixes are committed and pushed (`change-triage` steps 5–6), and the orchestrating
  session recomputes and starts the next step at once (`change-orchestrate`, "Run the
  computed step"). Nothing reaches the owner without either waiting for them or
  arriving after the fixes, and no procedure lets the orchestrating session stop a
  running step on the owner's word.
- **Parts of an interrupt already exist.** Each unattended run records its process,
  step and change under `<git-dir>/change-runs/` while it runs
  (`scripts/change_workflow/running.py`), reviews included
  (`scripts/change_workflow/review.py`). The wrapper turns SIGTERM into a run logged
  `stopped` with its session (`scripts/change_workflow/wrapper.py`,
  `_termination_ends_the_run`), and `resume` accepts a `stopped` run. It refuses one
  that ended otherwise, a `finished` triage included, and the log refuses a direction
  to triage while no review of its kind awaits one.
- **A finding states one suggested action.** `change-review`'s format ends each
  finding with `**Suggested action:**`, and asks for alternatives only in direction
  findings. The publishing check requires Lens, Basis, Severity and Evidence
  (`scripts/change_workflow/review.py`, `FIELDS`). A triage that thinks the suggested
  action is not the best fix says `partly`.
- **The spec lets the agent decline a `minor` finding** (`CW-7d5f`). A decline is a
  disagreement, so it is still presented.
- **Revisions already have a ledger form.** The ledger (`CW-zidp`) logs only
  corrections. An entry that revises an earlier one starts its `owner_disposition`
  with `revises <review> <finding>:` (`docs/agents/change-workflow.md`, "The ledger").
  A default acceptance writes no ledger entry, so nothing for `revises` to point at.

### Guidance

- **Issues.** `AGENTS.md` "Issue tracker" says "GitHub Issues handle intake and
  triage through the `gh` CLI". "Triage labels" maps five labels for that tracker.
  `issue-tracker.md` under `docs/agents/` configures `/triage` and `/wayfinder`, and
  `triage-labels.md` beside it maps labels "in mattpocock/skills": both come from an
  external skill set none of whose skills is installed (`.agents/skills/` holds only
  the `change-*` and `openspec-*` skills). The issue-discovery harness files its own
  issues (`docs/development/ISSUE_DISCOVERY.md`), cites neither document, and is a
  separate tool.
- **Defects found during a change.** The guidance that leans toward narrowness is:
  `openspec/README.md`, which calls a growing closeout task a scope-creep signal;
  `change-review`'s design scope lens ("should any of it be its own change?"), its
  pre-closeout scope lens ("what scope crept in"), and its implementation consistency
  lens ("and only that"); `change-implement`'s "and no more"; and `change-triage`'s
  `fix`, "and no more". `change-design`'s "a change that can close out on its own is
  preferred to one waiting on another" concerns scope that would add a prerequisite,
  not a found defect, and stays.
- **Vocabulary.** `docs/agents/domain.md` sends agents to `CONTEXT-MAP.md` and a
  `CONTEXT.md` per context, and gaps to `/domain-modeling`; none exists, and it says
  to proceed silently when they are missing. Product terms live in
  `docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities", and each
  capability's specification; the change workflow's own terms have no definitions
  section. `align-package-paths-with-layers` has an open point resting on
  `domain.md`'s directory-drawn platform context.
- **ADRs.** `AGENTS.md` "Domain docs" and `domain.md` describe ADRs in `docs/adr/`,
  which has never existed; the text came with the same external template.
- **Promoting principles.** The design skill lists principles the owner stated that
  no document records, for the owner to pick from.
- **Stored-state migrations.** `docs/development/ARCHITECTURE.md`, "Build, packaging,
  and initialization", makes schema changes additive by default, with expand and
  contract for the rest. `docs/development/DEPLOYMENT_AND_CONFIG.md` records upgrades
  that departed from it.
- **Unenforced rules.** `check_public_content.py` has no private-key-block rule;
  `openspec/specs/README.md` has no row for `contact-exchange-settlement`; no check
  covers destinations, history wording beyond change IDs and task numbers, version
  bumps, or local imports.

## Evidence

### Triage dispositions

#### Method

The data is the triage records and workflow logs of every change triaged in this
repository's workflow, archived between 2026-10-14 and 2026-11-03. Each triage record
holds each finding's lens, basis, severity, the agent's position and proposed outcome,
and the owner's disposition. A change's records are untracked, so the figures come
from the owner's workspace copies.

- **Dispositions.** Each disposition was labelled from its recorded wording:
  - accepted as proposed;
  - accepted with added context, meaning a condition, a scope limit, or a fact the
    agent lacked;
  - overridden or questioned.

  The label "accepted as proposed" includes the recommended option when the outcome
  was a choice.
- **Presented text.** For 313 findings in 17 changes, triaged under orchestration from
  2026-10-19, the workflow log keeps the full text the agent presented. Three facts
  were read from that text: whether it laid out alternatives, whether it said what
  would change its recommendation, and whether it called the fix clear.
- **Topics.** What each fix affects was tagged from the finding's title, lens and
  proposed outcome alone, without its disposition.
- **Gates.** Each gate's recommendation was read from the agent's last gate question
  in its session. It was paired with the exit the session took, and with the triage
  record's `## Next` where the session stopped before finishing.

The labelling is an agent's reading of recorded text. Small differences in a handful
of findings would not change the conclusions.

#### Findings

Over all 478 findings: 79% were accepted as proposed, 8% accepted with added context,
and 13% overridden or questioned.

By position in the round, which the skill orders most severe first:

| Position | Accepted as proposed | Added context | Overridden or questioned |
|---|---|---|---|
| First (164) | 69% | 12% | 20% |
| Second (101) | 76% | 9% | 15% |
| Third and later (213) | 89% | 5% | 7% |

By what the agent proposed:

| Proposal | Accepted as proposed |
|---|---|
| Agrees, proposes an edit (125) | 93% |
| Agrees, proposes a fix (97) | 85% |
| A choice between options (115) | 61% |
| Code fixed to match the specification or design (51) | 90% |
| Wording edit to a document or specification (94) | 97% |

Single features of the 313 presented findings, by intervention rate (added context or
overridden):

| Feature | Present | Absent |
|---|---|---|
| Agent names what would change its recommendation | 36% (80) | 14% (233) |
| Agent lays out alternatives | 31% (94) | 15% (219) |
| Agent calls the fix clear | 14% (51) | 21% (262) |
| Severity `blocking` | 30% (81) | 16% (232) |
| Record is a validation record | 62% (16) | 18% (297) |
| Record is the owner's notes | 30% (33) | 18% (280) |

By topic, the fix affects:

| Topic | Intervention rate |
|---|---|
| Specification wording (31) | 3% |
| Code made to do what the specification says (7) | 0% |
| An interface or representation (28) | 29% |
| A migration or compatibility path (10) | 50% |
| The validation environment (10) | 50% |
| The change's scope (13) | 23% |

Calling the fix clear adds little once alternatives and change-of-mind conditions are
known. Whether production behaviour changes predicts nothing (14 such findings).

At the gates, the agent recommended advancing 56 times and the owner advanced 55
times. It recommended another round 20 times and the owner agreed 18 times.

Waivers of validation or of a design re-review numbered 35. The owner proposed 34 of
them. The reasons:

- the commit could not affect validation (8);
- a known environmental failure (8);
- the review and validation records were at different commits (7);
- skipping a design re-review of a small decision (6);
- other (6).

#### Candidate batch rules

Every candidate starts from rule A. Under A, the agent agrees, proposes an edit or
fix, and names nothing that would change its recommendation, and the finding comes
from a review, not a validation record or the owner's notes. The figures are over the
313 presented findings. The held-out check fits nothing on the later changes:
"earlier" is the 232 findings of changes dated up to 2026-10-28, and "later" is the
81 findings of the nine changes after it.

| Rule | Covered | Added context | Overridden | Earlier: covered / context / overridden | Later: covered / context / overridden |
|---|---|---|---|---|---|
| A | 118 (38%) | 5 | 1 | 82 / 2 / 0 | 36 / 3 / 1 |
| B: A, no alternatives laid out | 108 (35%) | 5 | 1 | 74 / 2 / 0 | 34 / 3 / 1 |
| C: B, not `blocking` | 85 (27%) | 3 | 1 | 64 / 2 / 0 | 21 / 1 / 1 |
| D: B, the fix affects no interface, migration, scope or validation environment | 90 (29%) | 2 | 1 | 62 / 0 / 0 | 28 / 2 / 1 |
| E: D, not `blocking` | 73 (23%) | 1 | 1 | 54 / 0 / 0 | 19 / 1 / 1 |

What the residue holds:

- **The one override is the same finding in every rule.** It was a decision about
  where an archived change's fix lands. No triage-time fact distinguishes it.
- **The added-context cases outside D and E are architecture findings.** Each was
  accepted with a condition, such as "record the wider point as a roadmap gap", or
  with a fact the agent lacked, such as "no production deployment has this, so no
  upgrade handling".
- **On the held-out changes every rule sits near 10%.** The rules separate over all
  the data, by added context more than by override.

A search over every combination of up to four of these features found rules covering
more of the earlier changes at about 2% intervention. On the later changes those rules
rose to 10–14%, so the extra width does not generalize. The candidates above are
stated in the workflow's own terms rather than fitted.

### What the owner's corrections say about the guidance

#### Method

- **Inputs.**
  - The intervention ledgers of every change carrying one: 506 corrections, 365 from
    triage, 131 from design discussions, and 10 from planning. The count was
    rechecked during the design discussion: 506 entries across 35 ledgers.
  - The 63 triaged findings whose basis is written guidance, each with the reviewer's
    own text naming the rule.
  - The 53 whose basis is the reviewer's judgement.
- **Two kinds of signal**, as `openspec/specs/change-workflow/README.md` frames
  them:
  - A guidance finding that reached a review means a written rule was not followed or
    not enforced.
  - A judgement finding the owner accepts, or a correction the owner makes, is a
    candidate unwritten rule.
- **Process.** Each correction's general principle was extracted and clustered. Each
  cluster was checked against the current guidance and the repository's `check-*`
  targets. The citations below were spot-checked against the files.
- **Overcounting.** Nine changes from one Goal 8 plan carry copies of the same
  dispositions, so counts leaning on them overstate independent recurrence. Their
  dispute and lifecycle decisions are already promoted into `deal-lifecycle` and
  `settlement-configuration`, and were not treated as gaps.

#### Findings

- **Most corrections rest on unwritten judgement.** 232 of the 506 have basis
  `judgement`, and 150 have lens `direction`.
- **Written guidance is right but unenforced.** The 63 guidance findings are mostly
  documentation (33) and testing (12), and the owner accepted 52 as proposed.
- **Guidance that contradicts the owner's practice:**
  - **Issues.** The owner declined a proposed issue in at least five product changes
    and seven workflow corrections.
  - **Defects found during a change.** Seven product changes and seven workflow
    corrections fixed a small defect in the current change, against guidance that
    leans toward narrowness.
  - **Migrations.** The owner overrode three of the four findings that cited the
    migration rule. D13 keeps the rule.
  - **Promoting principles.** In six changes the owner narrowed which principles to
    promote. D14 keeps the flow.
- **Unwritten rules the owner applies:**
  - no guard code for an indescribable case (five changes);
  - amend a rule or comply (six product changes, three workflow corrections);
  - prefer an existing library (four);
  - when a validation may be waived (nine changes, matching the 34 owner-initiated
    waivers above);
  - preferences stated to an agent that stay in that agent's memory (four
    corrections).
- **Written rules that nothing enforces:**

  | Rule | Changes | Enforced today |
  |---|---|---|
  | Every accepted decision names a permanent destination | 6 (9 with ledgers) | no |
  | Comments describe the current system | 4 | `check-comment-hygiene` matches change IDs, task and section numbers only |
  | Test at the level that can prove the behaviour | 4 | no; not mechanizable |
  | One version bump per changed package | 3 | no |
  | Public-repository discipline | 3 | no pattern for private-key blocks |
  | Import placement | 2 (4 with ledgers) | no |
  | The capability index lists every capability | 1 | no; `contact-exchange-settlement` has no row today |

## Decisions

### Triage

### D1 — Default-accepted findings are reported in one table, not asked

Triage reports every default-accepted finding in one table — its label, severity, the
finding in one line, and its outcome — under the heading "Accepted by default":

```markdown
#### Accepted by default

| Finding | Severity | The finding | Outcome |
|---|---|---|---|
| 04 F5 | should | design.md cites a ROADMAP heading that was renamed | edit: cite `#goal-8-post-commitment-lifecycle` |
| 04 F7 | minor | proposal's impact list omits `docs/agents/change-workflow.md` | edit: add it under Guidance |
```

When the triage asks the owner anything — its last discussed finding, or the
question whether another round is merited — the table rides on that last question,
after its `→` line, so a revisit there is an ordinary disposition made before any
fix. When the triage asks nothing, the table goes in its final report. The findings
are accepted without the owner's confirmation and their fixes are made with the
round's other accepted fixes.

- **Rejected: the table only in the final report.** Every revisit would arrive after
  the fix is committed and the next step has started.
- **Rejected: holding the next step until the owner acknowledges the table.** A
  confirmation under another name, leaving the owner's window idle.
- **Rejected: one batched question, "accept these?".** It keeps the spec's wording
  but still costs a turn every round, which D1's purpose removes.

### D2 — Advancing is the default exit

When the agent recommends advancing, triage takes the advancing exit without asking
and reports it beside the table. A recommendation of another round is argued and
asked, as today. A triage with nothing to discuss and an advancing recommendation
asks nothing and finishes.

### D3 — The batch rule is Rule E

A finding is accepted by default when all of these hold, and is discussed otherwise:

- it comes from a review, not a validation record, the owner's notes, or the
  orchestrating session's observations;
- its severity is not `blocking`;
- the agent's position is `agree`, and its proposed outcome is one `edit` or one
  `fix`;
- neither the reviewer (D17) nor the agent lays out an alternative, and the agent
  names nothing that would change its recommendation;
- the fix touches no interface or representation, migration or compatibility path,
  the change's scope, or the validation environment.

It covered 23% of presented findings, with one accepted with a condition and one
overridden. It starts conservative and is widened only on evidence (D21): its
`blocking` exclusion is the one input besides the record that the agent does not
judge, which matters while agents learn the rule (D18), and D17 adds a second.
Validation records (62% intervention), the owner's notes (30%) and the orchestrating
session's observations are excluded by the first condition. An agreed `task` or
`none` was not measured and is not admitted.

- **Rejected: Rule D.** Seventeen more findings, all `blocking`, at one more
  added-context case; it rests wholly on the agent's own judgements.
- **Rejected: Rules B and C.** They readmit the interface, migration and
  validation-environment topics, with 29–50% intervention.

### D4 — Revisits stay outside the workflow graph

A revisit adds no node or edge: it resumes an existing step under the owner's
direction (D16). If revisits become frequent enough to complicate rounds, normalizing
them into the graph is a later change, which a guidance review proposes (D21).

### D15 — The owner can interrupt a running step

The orchestrating session is free while a step runs a long task, so the owner can
reach it mid-step. `scripts/change-workflow stop <change> [--step <step>]`
reads the change's run records and sends SIGTERM to the recorded process: the one
run, or, with validation and a review side by side, the step named. The wrapper's
existing handler logs the run `stopped` with its session. The review runner gains the
same handling: SIGTERM raised as the wrapper's termination inside `review_and_log`
reaches its existing interruption path, which logs the review `stopped`, and its
record is removed as the run ends. Every runner ends the reviewer or agent process it
started before the run is logged, as `run_claude` already does and `run_codex` does
not today, so no orphaned reviewer goes on to write output after the stop.

`stop` signals only a process it verifies is still the recorded run. Each run holds an
exclusive lock on its record file for as long as it runs; a record counts as a live run
only while its lock is held, for `stop` and for the round view's check alike. `stop`
checks the lock when it selects the run and again immediately before it signals. A
stale record — its lock free, the run killed before it could remove it — or a run that
ends before the second check is a refusal that signals nothing. The kernel releases the
lock however the process ends, SIGKILL included, and the lock's file descriptor is not
inherited by the run's children, so neither a reused process id nor a surviving child
can pass for the run.

The second check and the signal are two system calls, and the lock cannot make them
atomic (31 F1): a run that ends between them leaves its process id to be signalled.
That window is an accepted risk. The signal reaches another process only if the kernel
hands out its whole process-id range — 32768 ids at the smallest `pid_max`, usually
4194304 — between the two calls, and the new process belongs to the same user, since
a signal to another user's process fails. No test can deliberately trigger that, so
guarding it would be the speculative guard code D8 rules out. The tests cover a stale
record and a run that ends between selection and the second check.

The orchestrating session
records the owner's interrupt as an owner's decision line that resolves nothing, then
does what the owner says: resume the session with the owner's words, rerun, or resolve
the stop and direct the change elsewhere, as it recovers any stop. An interrupted
review publishes nothing and is rerun. A stop commits nothing, so the stopped step's
work waits uncommitted for its resume.

A run holds its record from before its agent or reviewer starts until after its line
is written, so a stop can reach it outside the time that process runs (64 F1). The
signal ends the run only while the process runs. For the rest of the time the record
is held, the run holds the signal: one held before the process starts ends the run as
it would start, and one held after the process has exited ends nothing, so the run
logs the outcome it reached — a published review `finished`, a step's own outcome —
and the owner's interrupt, recorded as their decision, resolves no run. Killing the
run there would leave no line for work already done.

- **Rejected: a stop at any moment logs `stopped`** (64 F1). After the reviewer or
  agent has exited, that means deleting a published review, or logging `stopped` over
  a step whose outcome, commits included, is reached.
- **Rejected: an ending state that `stop` refuses** (64 F1). The run can still begin
  ending between the stop's last check and its signal, so the signal must be held
  anyway; the state adds a record rewrite and a refusal for a clearer message.

- **Rejected: the harness's own stop of the background command.** Whether SIGTERM
  reaches the wrapper through make is not the workflow's to guarantee; a SIGKILL
  leaves no log line.
- **Rejected: delivering words into a running session.** Headless runs take no input
  mid-turn; that would be a harness capability.
- **Rejected: a separate cancel operation for reviews** (20 F1). A second command for
  the same act; the review runner's existing interruption path needs only the signal.
- **Rejected: comparing the process's recorded start time** (20 F2). It needs
  `/proc/<pid>/stat` on Linux and another source elsewhere, a platform branch for the
  guarantee the held lock gives through `fcntl` on both.
- **Rejected: signalling through a process handle** (31 F1). `pidfd_open` and
  `pidfd_send_signal` bind the signal to the process, but are Linux-only: the same
  platform branch as the start time.
- **Rejected: a per-run control channel** (31 F1). A FIFO beside each record, read by a
  thread in the run, which signals itself, closes the window on every platform. It adds
  a thread and a protocol to every runner to remove a risk no test can trigger.

### D16 — A revisit after the fixes resumes the finished triage

When the owner revisits a default acceptance, or the advancing exit, after the
triage finished, the orchestrating session stops the step running after it (D15),
then records the owner's direction naming the triage's run:

```text
scripts/change-workflow note <change> orchestrator --by owner \
  --resumes <triage-seq> --decision "revisits 04 F5" --reason "<the owner's words>"
```

The wrapper resumes a `finished` triage run only against such a direction, and only
while it is the latest triage of its review. The resumed triage, which holds every
finding's context, amends the fix in a new commit, appends the ledger line (D19),
ends `finished` again and names its exit again, so a revisit may become another
round or a return. Its outcome is the later one naming those reviews, so it governs.
The stopped next step is resolved by a decision line, not resumed, since its tree
moved under it. After archive cleanup reaches `done` nothing is left to resume, and a
revisit belongs on the pull request.

- **Rejected: carrying the revisit into the next triage as a point of the owner's
  notes.** After a design review the plan and a round of code would be built on the
  wrong edit; after a closeout review there is no next triage.
- **Rejected: the owner's direction to the step that owns the work.** No node takes a
  closeout or pre-closeout revisit, and that step lacks the triage's reasoning.
- **Rejected: resuming only while nothing after the triage has committed.** A
  resumed triage that finds its amendment contradicting later commits takes the
  existing return path, so the split adds a rule without removing a risk.

### D17 — Reviewers state alternatives on every finding

Every finding carries a required `- **Alternatives:**` field: `none — <why the fix is
evident>`, or each option a reasonable owner might choose, with its trade-off. The
publishing check rejects a review missing it, as it rejects one missing Evidence.
"None" is permitted and is a statement, not an omission. A reviewer's alternative
sends the finding to discussion (D3). For a pasted external review, triage assigns
the field as it assigns lens, basis and severity there.

```markdown
### F5 — design.md cites a ROADMAP heading that was renamed

- **Lens:** documentation
- **Basis:** evidence
- **Severity:** should
- **Evidence:** `design.md:88`, `docs/development/ROADMAP.md:212`
- **Alternatives:** none — the heading has one current name
```

This gives Rule E's weakest criterion — the agent's own reading that no alternative
exists — an independent reading from the reviewer, usually another model, at no run
cost.

- **Rejected: an optional field.** An absent line cannot tell "none" from "not
  considered".

### D18 — A default acceptance records its classification

Each default-accepted finding's triage entry carries a `Classification:` line, written
when its position is decided and before any finding is presented, stating how it met
each condition of D3. Its `Owner disposition` reads "accepted by default".

```markdown
- **Classification:** accepted by default — from 04-design; should; agree, one edit; no alternative (the heading has one current name), reviewer's none; nothing would change it; touches one citation in design.md
- **Owner disposition:** accepted by default
```

A guidance review (D20) samples these against their findings, which finds a drift in
how agents read "no alternative" across many triages — the realistic failure, since a
dropped alternative is invisible in a one-line table.

- **Rejected: an independent per-triage classification check by a subagent.** A run
  per triage, narrowing the batch whenever two readings differ; D17 serves most of its
  purpose.
- **Rejected: the next review auditing default acceptances.** Late, and a workflow
  duty in a review about the change.
- **Rejected: watching only the revisit rate.** Blind to the failure it is meant to
  catch.

### D19 — A revisited default acceptance is a ledger entry marked as such

A correction of a default acceptance, before its fix (D1) or after (D16), is a ledger
entry whose `owner_disposition` starts `revisits default acceptance:`. A later
revision of that entry uses `revises <review> <finding>:` as today. The ledger's
shape does not change. A revisit of the advancing exit (D2), which `CW-r8vz` also
logs, is such an entry with `"finding": "next"` under the review's record, as a
waived commit rule is `"finding": "commit"`; a guidance review counts it under the
advancing exit, not among revisited findings.

```json
{"review": "04-design", "finding": "F5", "section": null, "lens": "documentation", "basis": "evidence", "severity": "should", "agent_position": "agree: the heading was renamed; accepted by default", "owner_disposition": "revisits default acceptance: cite the goal's row in ROADMAP's table instead, which survives renames", "summary": "Default-accepted citation fix redirected to a stable target"}
```

Whether a revisit came before or after the fix is in the workflow log: an
after-the-fact revisit has its `--resumes` direction.

### D20 — `guidance-review`, an interactive skill for guidance reviews

`.agents/skills/guidance-review/` is a skill the owner runs in their workspace, which
alone holds every cleaned-up change's records. It is not a step of a change: no graph
node, no step-table row, no outcome. It:

1. reads every ledger, triage record and workflow log since the last guidance review —
   from the end of the last period its period ledger records, or, before the first
   review, from a date the owner gives;
2. reports the disposition figures, default acceptances and their revisits (before
   the fix and after), an audit of a sample of `Classification:` lines against their
   findings, waiver recommendations and how many the owner accepted, by criterion
   (D22), and the terms the owner asked about (D11);
3. clusters the owner's corrections into guidance that is false, rules applied but
   unwritten, and rules written but unenforced, and checks each cluster against the
   guidance and the checks;
4. lists candidate edits for the owner to pick, as design lists principles (D14),
   including whether to keep, narrow or widen Rule E and whether any waiver criterion
   has earned acceptance by default;
5. on the owner's word, writes the proposal of a change carrying the picks, stating
   the period it covered;
6. whatever the owner picks, nothing included, appends one line to its period ledger:
   the period's start and end, the headline figures — default acceptances, revisits
   before and after the fix, the audit's sample and its disagreements, waiver
   recommendations and acceptances — and the proposal it wrote, or `none`.

The period ledger is an untracked file in the owner's workspace beside the cleaned-up
change records it measures: `openspec/changes/archive/guidance-reviews.jsonl`, one JSON
object per line, ignored by a `.gitignore` entry this change adds. The archive's
readers take only directories as archived changes (`scripts/change_workflow/find.py`,
`scripts/check_comment_hygiene.py`), so a file there is read by none of them, and the
`openspec/changes/**/reviews/` ignore rule does not reach it, hence its own entry. A
review that picks nothing stays
a read-only session apart from that line, and the next review starts where the last
line ends and has the earlier figures to compare with (D21).

Its method is this design's "Evidence" sections, which move into the skill. What
reaches the repository is aggregates and the principles drawn from them, under
`AGENTS.md`'s public-repository rules.

- **Rejected: a change of its own.** D18's sampling and D21's reading would point at
  nothing until it landed.
- **Rejected: no skill.** Each guidance review would re-derive its method.
- **Rejected: the newest proposal as the cursor** (20 F5). A review whose owner picks
  nothing writes no proposal, so the next would count that period twice or need a date
  from memory.
- **Rejected: a tracked table of periods.** A review that picks nothing would commit
  outside any change.
- **Rejected: the owner giving the start date each time.** The history would live in
  the owner's memory.

### D21 — The revisit rate is read by the guidance review, against the rule's baseline

No numeric threshold narrows or widens Rule E. Each guidance review reports the
period's default acceptances, revisits and audit results beside Rule E's measured
baseline — 2.7% intervention overall, about 10% on the held-out changes — and proposes
keeping, narrowing or widening the rule, or opening D4's change; the owner decides.
Fixed thresholds over samples this small would be noise.

### D22 — Steps recommend waivers; only the owner waives

A step that meets a guard the owner may waive recommends a waiver when a written
criterion holds, naming the criterion and its evidence, in the message it already
sends the owner: triage at a review and validation of different commits, design
finishing after a return, validation on a known environmental failure, archive
cleanup before its validation. This follows the merge before closeout, which already
judges and recommends. The criteria, in `docs/agents/change-workflow.md`, "Waivers":

> A waiver may be recommended when:
> - the commits the guard would validate differ from validated ones only in paths no
>   part of validation exercises — `openspec/`, `docs/`, the change's records — naming
>   the paths;
> - a failure is a known environmental one, already diagnosed in an earlier
>   validation record of this change, naming that record;
> - a review and a validation name different commits whose difference is records or
>   documentation only;
> - a decision made after a return to design is confined to one requirement's wording,
>   or to a choice the design review already weighed, naming it.
>
> The recommendation names its criterion and its evidence. Only the owner waives.

A waiver is always a ledger line; a recommended one's `agent_position` names the
recommendation and criterion, and a recommendation the owner declines is a correction.
Planning that settles a design question itself recommends waiving another design
review as design does after a return. A step that commits nothing leaves the line to
one that does: validation's to the triage that reads its record in a round, or, for
a record no triage reads, to archive cleanup; a design review's waiver to the
orchestrating session, committed with planning or, declined, with that review's
triage.
So a guidance review can count recommendations and acceptances by criterion, the
evidence a later review would use to propose waivers taken by default.

- **Rejected: waivers taken by default.** A waiver skips evidence; until acceptance is
  measured, a wrong default costs a broken pipeline found later.
- **Rejected: criteria without recommendations.** The owner would still spot every
  waiver.

Under 84 O1, the owner's waiver of the Helm and pipeline parts "for the remainder of
this change" (66 V1) reached no validation: nothing carried a standing waiver to the
step, which knew only a waiver of an environmental failure, and recorded that part as
`inconclusive`, sending every validation back to the owner. The owner chose that
validation read the waiver from the log and that the waivable parts be formalized:

- **Any part may be waived** — local, Helm, the pipeline, an owed CI run — by the
  owner alone. The owner can already waive validation entirely; forbidding a part
  would only push them to that when a part blocks them. The local part's `make test`
  is broader than a change confined to the workflow's scripts needs, kept whole only
  because the step table admits it more simply than each suite.
- **A waived part is an omission of evidence**, recorded as `waived`, neither passed,
  failed, nor inconclusive, and counted in no result; an environmental failure the
  owner waives is recorded so too (`CW-e7lm`).
- **A waiver for later validations is the owner's decision in the workflow log**,
  naming the parts and the condition, which validation reads before running any part;
  an instruction in its invocation is not a waiver. It lapses, and the part runs,
  when the commits since the part last ran include a merge or break the condition —
  validation 85, the first after the merge of dev, showed the waived pipeline's value
  there. Validating with every part waived is no validation; that is the owner's
  direction past the guard.
- **Its record.** A standing waiver given as a triage's disposition is that triage's
  ledger line, as 66 V1's is; one given outside a triage, with no step's
  recommendation, is the owner's decision in the workflow log alone, where a guidance
  review finds the waivers no step recommended.

- **Rejected: the orchestrating session passes the waiver in `ARGUMENTS`.** It had
  been done so, unofficially; a validation started by hand misses it, and two places
  must remember it.
- **Rejected: a waived part is `inconclusive`.** Every validation would stop for a
  ruling the owner already gave, as seq 101 did.
- **Rejected: deferring it.** Each later validation would run every part.

### Guidance

### D5 — The issue-tracker guidance is replaced by where deferred work goes

`issue-tracker.md` and `triage-labels.md` under `docs/agents/` are deleted, and
`AGENTS.md`'s "Triage labels" section with them. "Issue tracker" becomes "Deferred
work":

> Deferred work is recorded in the open change that owns its area, in a new change,
> or as an unowned gap in `openspec/changes/README.md` or
> `docs/development/ROADMAP.md`. This repository does not use GitHub Issues for its
> own work; the issue-discovery harness files its own issues
> (`docs/development/ISSUE_DISCOVERY.md`).

- **Rejected: rewriting the documents for the harness only.** `ISSUE_DISCOVERY.md`
  already owns that.

### D6 — Defects found during a change are fixed in it, in proportion

One home, `openspec/README.md`, gains a paragraph after the closeout parts:

> **Defects found during a change.** A defect found while working a change is fixed in
> that change when its fix is understood and small beside the change, even where it
> lies outside the change's stated scope: a change of its own costs a design, reviews,
> validation and a closeout, which a small fix does not repay. A defect that is large,
> or not understood well enough to fix without a design of its own, gets its own
> change, or an unowned gap where no change owns its area (`AGENTS.md`, "Deferred
> work"). This is a judgement of proportion, not a rule that changes stay narrow, and
> growth that unifies behaviour the architecture wants shared (`ARCHITECTURE.md`,
> "Composition from above and below") is not scope creep. A defect fixed outside the
> stated scope is recorded where the change's reviewers will see it: in the task
> notes, or in the triage record.

The scope-creep sentence becomes:

> If a plan's closeout task grows unusually large on its own, decide deliberately
> whether the growth belongs to the change — a found defect fixed in place, or
> unification the architecture favours — or is separate work better split, rather
> than noticing only once the section is hard to review.

The skills align to it and cite it: `change-review`'s design and pre-closeout scope
lenses ask whether new scope is a small understood fix, kept, or large or vague work,
split; its implementation consistency lens admits a found defect the notes record;
`change-triage`'s `fix` and `edit` cover a small out-of-scope defect, and a large or
vague one is `none`, recorded where "Deferred work" says; `change-design`'s splitting
question asks it the same way. `change-implement` fixes a small, understood defect it
finds and records it in the section's notes as outside the plan, so the round's
review and the owner's reading see it.

- **Rejected: stating the paragraph in each skill.** Copies drift.
- **Rejected: a home in `AGENTS.md`.** It is a rule of the change workflow, not the
  repository's engineering guidance.
- **Rejected: implementation only recording a found defect for triage.** A round trip
  the diff, the review and the notes already make visible.

### D7 — No rule tells agents to recommend the narrowest fix

The owner's scope growth usually comes from proposing to refactor and unify the VM
and bare-metal domains, which is larger than fixing one service. `ARCHITECTURE.md`
favours one behaviour composed from a shared kit. A narrowest-fix rule would work
against both.

### D8 — No speculative guard code

Production code adds no refusal, warning, probe or hardening for a case that nobody
can describe, or that no integration or end-to-end test could deliberately trigger.

### D9 — Amend a rule or comply

When work conflicts with a written rule, the rule is amended first or the work
complies; a private exception is never recorded. This includes the owner's standing
rule that the testing layers change only by changing `TESTING.md`.

### D10 — Prefer an existing open-source library

Use one wherever it meets the requirements, and build our own only when none does.
The relay plugin was built because no library met its requirements.

### D11 — The vocabulary has named homes and one rule

| Terms of | Home |
|---|---|
| the market across subsystems | `docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities" |
| one subsystem | that capability's `openspec/specs/<capability>/spec.md` |
| the change workflow | `openspec/specs/change-workflow/spec.md`, "Terms" |

A subsystem's definition wins inside that subsystem. `change-workflow`'s
specification gains a `## Terms` section, seeded with the workflow's terms: round,
round view, pass, exit, direction, guard, join, record, waiver, default acceptance,
revisit, interrupt. A section outside `## Requirements` passes the pinned strict
validator (`fulfillment/spec.md` carries `## Responsibilities` and `## Ownership`);
a delta carries only requirements, so closeout writes the section by hand, as it
writes an architecture companion, and a later change adding a term names that edit.

`docs/agents/domain.md` is rewritten to name the homes and state the rule: use the
established term; don't drift to a synonym `ARCHITECTURE.md` rules out; a term new to
the reader is defined where it first appears and marked as new, and one that stays is
added to its home in the same change; when the owner asks what a mechanism is for or
what a word means, the agent answers in established terms, then corrects the
description or proposes the entry. Its `CONTEXT.md`, `CONTEXT-MAP.md` and
`/domain-modeling` references go. The owner's clarifying questions are tallied by the
guidance review from the workflow logs (D20), not by a new record.
`align-package-paths-with-layers`'s open point on `CONTEXT.md` dissolves; its design
reverifies once this change lands.

- **Rejected: creating the `CONTEXT.md` files.** A second copy of the product terms,
  and no home for workflow terms.
- **Rejected: one glossary document.** Subsystem terms copied or left out, and the
  workflow's terms leave with its extraction anyway.
- **Rejected: a ledger line per clarification.** A clarification is not a correction.

### D23 — The ADR guidance is dropped

`AGENTS.md` "Domain docs" loses its ADR sentence, and `domain.md` loses "ADRs are not
OpenSpec specs" and "Flag ADR conflicts". Nothing replaces them: the repository has
never had ADRs. Adopting them would be a change of its own, not proposed.

### D12 — The owner's working preferences move into the repository

From the agent's memory, reviewed on 2026-11-04:

- **No GitHub issues:** D5. **Fix small defects in the current change:** D6.
- **Notes and proposals across changes**, in `docs/agents/change-workflow.md`:

  > One change is implemented per branch. Recording an open question or a note in
  > another active change's documents, or writing the proposal of a follow-up change,
  > on the current branch is not working that change; the edit lands with the current
  > change. A *prerequisite* — a change this one must wait for — is proposed from `dev`
  > instead (`change-design`, "When the design needs another change first"), since it
  > must land first.

- **State bookkeeping, don't ask it**, in `change-design`, "Classify each decision":

  > Never ask the owner where documentation should live, at which test level a
  > behaviour is proven, or which evidence a section records: state each as a
  > provisional answer — the documentation destination in `proposal.md`, the test
  > level from `TESTING.md` — for planning and review to confirm or move.

- **A skill restates guidance only to cite it**, in `docs/agents/change-workflow.md`,
  "Skills":

  > A skill that restates a rule from the guidance restates it briefly where its step
  > applies it, and cites it; it is never stricter than its source. A step that needs a
  > stricter rule proposes amending the guidance (`AGENTS.md`, amend a rule or comply).

  Restatement exists because compaction drops documents read through tool calls while
  the skill stays salient; every restatement spends context and can drift. Whether a
  reliable reload of cited guidance after compaction would let skills cite instead is
  an open question recorded in `layer-engineering-guidance`'s design.
- **Not promoted:** several implementation sections in one session, which the
  implementation cadence already covers; and two entries that are the agent's notes
  on unrelated initiatives.

### D24 — The change's closing checks enforce seven written rules

All but the private-key and lock-revision rules run in `make check-change CHANGE=<change>`, against the
change's documents or its diff from its merge-base with the branch it lands on, which
every step that commits already runs:

1. **Destinations.** Each `### D<n>` heading under `design.md`'s `## Decisions`
   appears as `D<n>` at the start of a bullet in `proposal.md`'s "Knowledge to
   promote"; a decision with nothing to promote says `- D<n>: no permanent destination
   — <reason>`. `change-design` records decisions under such headings from now on; a
   design with none passes and is reported as not checked, since most active changes
   write decisions as bullets.
2. **History wording.** A comment or docstring line the diff adds in a `.py`,
   `.toml`, `.yml` or `.yaml` file must not use "previously", "formerly", "used to",
   "no longer", "moved from", "was renamed" or "originally". "Now" and "legacy" stay
   off the list, since current-state comments and fixtures use them. A false positive
   is reworded; there is no exception marker (D9). A TOML or YAML line is read alone,
   so a `#` line inside a YAML block scalar or a TOML multi-line string is read as a
   comment (64 F3): such blocks here hold embedded shell or configuration — a
   workflow's `run:`, a chart's config file — whose comments the rule covers, and a
   string line that trips the check is reworded. Rejected: excluding block content,
   which would stop checking every embedded comment to spare a rare string; and
   excluding it except under `run:`, which ties a repository-wide check to GitHub
   Actions' key name and still misses embedded configuration.
3. **One version bump.** Each `pyproject.toml` version that differs from the
   merge-base is exactly one SemVer step from it — next patch, minor or major, lower
   parts reset — which admits a larger bump replacing a smaller one
   (`docs/development/RELEASING.md`, "Versioning policy"). A missing bump is not
   checked; the rule does not require one.
4. **Private keys**, through gitleaks (MIT), a maintained secret scanner, at a pinned
   release, as D10 asks (31 F3). It runs beside `scripts/check_public_content.py`
   wherever that runs — the pre-commit hook on staged additions, the guarded push and
   the pre-push hook on every outgoing commit, and the Public content workflow on every
   commit since the event base — with its output redacted, so a finding names its
   location without the key. `check_public_content.py` keeps its own rules (home paths,
   planning paths, the private denylist), which no general scanner knows.

   Gitleaks' default `private-key` rule does not serve as it stands (38 F1). It accepts
   any 64 or more characters between a `BEGIN … PRIVATE KEY-----` header and the next
   `KEY-----`, so a short fixture's own END marker comes too soon to end the match, and
   the match runs on to the next block's header: the two fixtures in
   `provisioning/compute/service/tests/integration/test_hosts_api.py`, at lines 521 and
   749, join into one false key whenever a scan sees both — the tree, a commit adding
   the file, any hunk holding both. So a repository `.gitleaks.toml` extends gitleaks'
   default configuration, turns its `private-key` rule off, and adds a block rule of its
   own: the same 64-character minimum body, but a body that holds no run of five dashes,
   so a match ends at its own block's END marker and never reaches the next header —
   roughly `-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY-----(?:[^-]|-{1,4}[^-]){64,}-----END`.
   A real key, wrapped at any length or written as one escaped string, has a body of
   base64 and `\n` escapes well past 64 characters and is refused; a fixture whose body
   is `fixture`, `material` or `legacy-fixture` passes, however many share a file. The
   repository owns that one rule and the list of default rules it turns off (D26); the
   scan modes, the redaction, and every other rule stay gitleaks'.

   Every commit-range invocation passes `--diff-merges=separate` through gitleaks'
   `--log-opts` (38 F2). Gitleaks reads commits through `git log -p -U0`, which prints
   no patch for a merge unless a merge-diff option is given, so a key written only while
   resolving a merge would reach no patch it inspects. `separate`, git's `-m`, is the
   comparison with every parent that `check_public_content.py` makes.

   The first work on this check runs the pinned release, with the repository rule,
   against the repository's tree, two fixtures in one file, a key wrapped at short
   lines, a key embedded as one escaped string, a key added in an intermediate outgoing
   commit that a later commit deletes, and a key introduced only in a merge resolution.
   If the pinned release cannot turn off or replace its default rule from an extending
   configuration, a fixture is refused, or a key passes, the change returns to design
   rather than working around it.

   A body edited into an existing block beneath an unchanged header is a known
   limitation: a diff-reading scanner sees no header in that patch. So is a random
   credential in no provider's format, which the gate does not look for (D26).
   `ARCHITECTURE.md`'s "Public repository content checks" records both, with how to
   install the pinned release, why the repository replaces the default key rule and
   turns off three others, and the audit (D29); review remains the safeguard there.
5. **Local imports.** An import inside a function that the diff adds to a `.py` file
   has a comment on its own line or the line above giving its reason
   (`openspec/README.md`, closeout part 2). Whether the reason is sound stays with
   review.
6. **The capability index.** Every `openspec/specs/<capability>/` with a `spec.md`
   has a row in `openspec/specs/README.md` linking it, and every row links one that
   exists. The `contact-exchange-settlement` row is added in this change.
7. **One lock revision** (21 R1), in `scripts/check_locks.py`, which `check-packaging`
   and CI run: every committed `uv.lock` carries the lock revision the repository's
   minimum uv writes, 5, and a lock carrying another fails, naming it and both
   revisions. With it:
   - `MINIMUM` in `scripts/check_uv_version.py` rises to the first uv release that
     writes revision 5, established by running uv during implementation; CI's pins in
     `tests.yml` and `e2e.yml` and `docs/development/BUILD_AND_PACKAGING.md` move to
     it. The check stays a minimum, not an exact pin.
   - `scripts/uv_project.py` runs the uv-version check before its `lock` and `reinit`
     commands run uv (31 F2). The repository's relock and environment refresh go
     through it: `make lock`, `make review-locks`, and every package's `make reinit`
     and `make init`. `make lock` keeps its `check-uv-version` prerequisite, so it
     refuses before building wheels. A plain `uv run` that relocks a changed project
     is not guarded; the revision check fails on what it writes before it lands
     (55 F1). Making every repository `uv run` pass `--locked` was rejected: about 90
     Makefile lines and a check to keep them, still leaving a hand-typed `uv run`
     unguarded, while most package `test` targets already run the guarded `reinit`
     first.
   - The locks still at revision 3 are relocked to 5.

   `BUILD_AND_PACKAGING.md`'s explanation and `check_uv_version.py`'s docstring cover
   both directions of the drift: an older uv rewrites a newer one's lock as surely as
   the reverse.

The rule "test at the level that can prove the behaviour" stays with review: it is not
mechanizable.

The seventh check exists because agents on different uv releases rewrite each other's
locks. A relock of most locks made with a uv newer than CI's pin raised them from
revision 3 to 5. Then a change clone's bootstrap, running `reinit` on the pinned
release, wrote four of them back to 3. That dirtied the worktree under a design step,
and its guarded push was refused. A second change has seen the same drift. Nothing
caught it: the minimum admitted both releases, `reinit` checked no version, and
`check-locks` asks only whether a lock satisfies its project. The raised minimum stops
an older uv writing; the revision check stops any uv's rewrite from landing unseen,
newer ones included, until tooling pins uv exactly. Because the drift is happening now,
it is the first work of round 1's checks session. Until that lands, every machine that
runs the workflow's steps needs a uv at or above the new minimum.

- **Rejected: a change of its own for the checks.** The owner keeps them with the
  rules they enforce.
- **Rejected: a per-line base64 threshold for key blocks** (20 F4). A key rewrapped at
  short lines passes, and a key in an escaped source string has no body line at all.
- **Rejected: allowlisting fixture words, or refusing every key block** (20 F4). The
  first needs a checker edit for every new fixture word. The second makes every fixture
  build its header at runtime.
- **Rejected: an in-house whole-body key rule** (31 F3). Measuring the body across
  real and escaped breaks, as 20 F4 settled, needs the whole post-image of each changed
  file to see a header the patch leaves out, and a way to tie a block to added lines.
  That is a secret scanner of our own where a maintained one exists.
- **Rejected: detect-secrets, or pre-commit-hooks' `detect-private-key`** (31 F3). Both
  are understood to match the header alone, so both refuse the fixtures: the first
  would need a baseline of them, and the second has no commit-range mode for outgoing
  commits and CI.
- **Rejected: gitleaks' default rule, with `test_hosts_api.py`'s fixtures rewritten**
  (38 F1). It fixes that file only: the next file with two short fixtures, or a fixture
  followed by any later key header, fails again, and only when a scan's diff happens to
  hold both blocks.
- **Rejected: gitleaks' default rule, with the fixtures allowlisted** (38 F1), by a
  `gitleaks:allow` comment on each or a configuration allowlist. Each new fixture needs
  an entry, as 20 F4 found for fixture words, and D9 refuses exception markers; an
  allowlist by path would admit a real key in a test.
- **Rejected: another scanner, such as TruffleHog** (38 F1), whose key detector drops
  blocks it cannot parse. It is AGPL-3.0 and much heavier, and its staged and
  commit-range behaviour would have to be proven again.
- **Rejected: keeping the uv minimum at 0.12 and relocking back to revision 3** (21 R1).
  The owner raises the minimum instead, toward the release that already writes the
  repository's locks.
- **Rejected: an exact uv pin in this change** (21 R1). The revision check holds the
  locks steady without one. Pinning is later tooling work.

### The secret scan's rules

Section 5's gate ran gitleaks 8.30.1 over the tree with D24's configuration: the key
rule held every case, and the default rules D24 had kept unmeasured reported 114
findings in 47 tracked files — `generic-api-key` 74, `jwt` 38, `curl-auth-header` 2.
Read one by one, they are:

- 30 not secrets of any kind: a comment, type annotations and identifiers
  (`private_key: Ed25519PrivateKey`), a constant's name, migration revision names,
  idempotency keys, and public contract and token addresses;
- 40 of Anvil's published development keys, and one deterministic identity its file
  marks as a fixture, in `dev-env/`, the e2e configurations, the storefronts'
  `.env.*.docker` files, documentation examples and test constants;
- 5 placeholder test credentials: `X-Admin-Key: test-api-key` in curl examples,
  synthetic passwords in a codec fixture, and the base64 of "supplied-key";
- 38 JWTs of the frp grant test vector, signed with RFC 8032's published test keys;
- 1 credential not marked as a fixture (D25).

### D25 — The README's root password is replaced with placeholders

`domains/vms/provisioning/iac/README.md`, "Configure Build Variables (Optional)",
wrote a `root_password` and `root_filename` into `build-vars.yaml` with no fixture
marker. They have exactly the form `vm-setup`'s `golden-image-build.yml` generates —
40 ASCII letters and digits, and `root_ssh_<6 hex>_ed25519` — and the password becomes
a golden image's root password. Both lines become placeholders, `<the existing key's
password>` and `<its filename>`, as a small, understood defect fixed in this change
(D6), in the first commit of section 5's resumed session, since the design step does
not edit `domains/`. No customer image was built with the value, so nothing outside the
repository is rotated; the value stays in public history, which no edit removes.

- **Rejected: its own change.** A design, reviews, validation and a closeout for two
  lines, which D6 exists to avoid.
- **Rejected: marking the value as an example.** It has the shape of the role's real
  output, so the comment would assert what nobody can check (`AGENTS.md`, "Test
  fixtures and local development configuration").
- **Rejected: an unowned gap.** It leaves a plausible credential in operator
  documentation meanwhile.

### D26 — The gate runs gitleaks' default rules minus four, beside an audit of all of them

The public-content checks run every gitleaks default rule except four: `private-key`,
replaced by the repository's block rule (D24 item 4); `generic-api-key`, a keyword and
entropy heuristic that matches identifiers, public addresses and published development
keys as readily as secrets; `jwt` and `curl-auth-header`, which match test vectors and
documented placeholder headers. With them off the tree has no finding and every key
case still passes, and the provider-specific rules — cloud keys, source-host tokens,
chat and payment tokens — stay, matching fixed formats that almost never misfire.
Turning a rule off is an edit to the rule list, not a marker beside a fixture (D9); a
later fixture that trips a provider rule is another such edit.

The one finding a secret scan exists for, D25's password, came from `generic-api-key`,
and the gate does not catch its class: a random credential in no provider's format has
the character class of the identifiers the same rule matched, and separating them is
entropy tuning of the repository's own, the scanner 31 F3 declined to build. The audit
(D29), run by hand before an official build ships, finds that class over the whole
tree, as the gate run found D25; review remains the safeguard for each change.

- **Rejected: the repository's key rule alone.** It claims exactly the key requirement
  and never moves with a gitleaks upgrade, but drops every provider rule, so a leaked
  cloud token would pass.
- **Rejected: keeping `generic-api-key` with allowlists by shape** — contract
  addresses, Anvil's ten keys, identifiers. An identifier allowlist passes D25's
  password, which has that shape, so it keeps the cost and loses the catch.
- **Rejected: `generic-api-key` as a warning that refuses nothing.** It would print on
  every fixture and key annotation a change touches, and a warning read by agents is
  acted on unpredictably.
- **Rejected: allowlisting the fixtures by path or value, or rewriting them to build
  their values at runtime.** An exception list (D9, 38 F1), and the churn 20 F4
  declined, across 47 files.

### D27 — The requirement says what the gate refuses and passes

The delta requirement's public-content clause refuses a private key or a credential in
a format one of the scanner's provider-specific rules recognizes, and passes the
repository's development fixtures: published development keys, public contract
addresses, and code that names a key. Its scenarios "A provider token is staged" and
"A development fixture is added" pin both sides, the second keeping `generic-api-key`
from returning unnoticed.

- **Rejected: leaving the requirement at keys.** The check would enforce rules no
  requirement states.

### D28 — The tree test asserts the whole tree clean under the gate

`scripts/tests/test_check_secrets.py`'s scan of the repository's tree asserts no
finding of any rule under the shipped configuration, not only key findings, so a
gitleaks release whose new rule the tree trips fails that test when the pin moves,
not at someone's commit. A provider-token case builds its token at runtime, as the key
cases already assemble their headers, so the test file passes its own hook.

- **Rejected: asserting key findings only.** A noisy new rule would surface as a
  refused commit.

### D29 — `make audit-secrets`

`make audit-secrets` runs `scripts/check_secrets.py --audit`: every gitleaks default
rule but `private-key`, plus the repository's key rule, over `HEAD`'s tracked tree,
read as the tree test reads it — one parentless commit of `HEAD^{tree}` in a temporary
shared clone — so untracked and ignored files are never scanned. It reports each
finding by rule, file and line, redacted; exits 0 when it ran, since its output is for
reading and lists the fixtures D26 describes; and exits non-zero only when gitleaks
could not run. It keeps no baseline (D9), and no hook, push, CI job or
`check-packaging` runs it. Its caller is the owner, by hand, before an official build
ships; `docs/development/RELEASING.md`, "Cutting a release", gains that step.

The two configurations differ by the three rules the gate also turns off:

```toml
# scripts/gitleaks-audit.toml — the audit
[extend]
useDefault = true
disabledRules = ["private-key"]

[[rules]]
id = "private-key-block"
regex = '''(?i)-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----(?:[^-]|-{1,4}[^-]){64,}-----END'''
keywords = ["-----begin"]
```

```toml
# .gitleaks.toml — the gate the hooks, the guarded push and CI run
[extend]
path = "scripts/gitleaks-audit.toml"
disabledRules = ["generic-api-key", "jwt", "curl-auth-header"]
```

Section 5's gate confirms that the pinned release loads a configuration extended by
path that itself extends the defaults, the path resolved from the repository root
where `check_secrets.py` runs gitleaks. If it does not, the two files are each
self-contained, the key rule written in both, and a test asserts the two rules are
identical; that fallback is settled here, so it is not a return to design.

Tests: unit cases with an injected runner showing `--audit` passes the audit
configuration and the tree source; a library integration case in which a random
40-character password, built at runtime, is reported by the audit and passed by the
gate.

- **Rejected: the audit running gitleaks' defaults with no repository
  configuration.** Every audit would report the default key rule's false join of the
  two fixtures in `test_hosts_api.py`.
- **Rejected: a baseline of known findings.** An exception list kept in the
  repository (D9).
- **Rejected: its own change.** Its configuration is what the gate's extends; split, the
  gate's would be built self-contained now and as an extension later.

### D30 — Section 5 resumes from its notes

Section 5 finishes round 1's checks session in one session, from its gate notes: the
README placeholders (D25); the two configurations (D29) and the tree assertion (D28);
5.1's record with the nested-extension check; then 5.2–5.5 with the audit target and
its tests. Planning amends section 5's tasks once the design review advances, keeping
its notes, and amends closeout's 11.3 to re-check D1–D30 and 11.9 to name the
destinations of D25–D29, `docs/development/RELEASING.md` among them (55 F2). No other
section and no other round moves.

### Not changed

### D13 — The migration rule stays

Whether anything is deployed is a decision the team manages, not a fact inside the
repository. A feature branch does not know where its change will run. After 1.0.0,
merges to `main` may come to mean official launches, but that is not true yet. So no
exception for undeployed state can be derived from the repository.

### D14 — Promoting principles stays as it is

The design agent documents candidate principles, and the owner picks and clarifies
each promotion. Guidance changes take most of the owner's review attention, because
they shape how the product evolves, not only how it is now. Of the principles stated
in this design discussion, one is promoted: the owner can always reach a running step
(D15), in `change-workflow`'s architecture companion. That defaults widen only on
evidence serves the guidance review alone, so it lives in that skill (D20).

## Implementation cadence

- **Round 1 — the code, two sessions.** One session for the workflow tooling: the
  `stop` command with the held-lock run identity and the review runner's signal
  handling (D15), resuming a finished triage under the owner's direction with the
  `note --resumes` direction (D16), and the `Alternatives` field in the review
  publishing check and in `change-review`'s required finding format together (D17), so
  round 1's own review is written in the format its publisher checks. One session for
  the seven checks and the capability-index row (D24), the lock revision first, with
  the raised uv minimum and the relock, and gitleaks' repository rule and merge-patch
  scan confirmed against the fixture and key cases before it is wired in. Its section 5
  returned to design at that confirmation and resumes in one session (D30): the README
  placeholders, the gate and audit configurations with their nested extension
  confirmed, then the scan, its wiring and `make audit-secrets`. Skills should describe tooling that exists, so
  the code comes first; the two sessions are independent, and are reviewed and
  validated together.
- **Round 2 — the skills and guidance, two sessions.** One session for the workflow
  skills: `change-triage`'s rule, table, classification and revisits (D1–D3, D16,
  D18, D19); `change-orchestrate`'s interrupt and revisit procedures (D15, D16);
  `change-review`'s scope and consistency lenses (D6); waivers (D22); the defect-fixing
  alignment of `change-implement` and `change-design` (D6, D12). One session for the
  guidance and the new skill: `AGENTS.md`, `docs/agents/domain.md`, the issue
  documents, `openspec/README.md`, `docs/agents/change-workflow.md` (D5, D6, D8–D12,
  D23), and `guidance-review` (D20).
- Then closeout.

## Implementation record

What implementation settled within the decisions, the defects it found and fixed in
place (D6), and the points its fresh-context checks raised and declined. Closeout
moved them here from the task notes, which keep the evidence.

- **The run's lock (D15).** `flock`, not `lockf`: a POSIX record lock belongs to the
  process, so an in-process reader would always acquire it, and its close would drop
  the run's lock. A record is written aside, locked, then renamed into place, so no
  reader sees it unlocked. `stop` reads the runs of the change's clone when it has
  one, as `watch` does, since a cloned change's steps run and record there.
- **Holding the signal (D15, 64 F1, 64 F2).** `termination_deferred()` holds SIGTERM
  for as long as a run holds its record; `termination_ends_the_run()` covers each
  runner call only, raises at entry a signal held before it, and sets its handler
  inside its `try`, so a pending signal cannot leave it unrestored. An interrupted
  review's `stopped` line carries the reviewer's session, read from the interrupted
  attempt's own output, and its cost; a rejected review's line carries its session
  too. Declined: a wrapper test for a signal between network retries, which the
  before-start test's entry check covers.
- **The revisit direction (D16).** Beyond the two refusals planned, the log's writer
  refuses a direction naming a triage a run resuming it supersedes, even while that
  run waits; a finished triage naming no review; and `--resumes` with `--next`, since
  the resumed triage names the exit. The next-step computation needed no change: it
  already takes the last exit logged and holds a stopped run until a line resolves it.
  Nothing in code stops a resume of the stopped step a revisit leaves; "resolved
  rather than resumed" rests on `change-orchestrate`, which orders the stop, the
  direction, the resume, and then the resolution, since resolved before the resume the
  computation would name the first triage's exit again.
- **The review field parser (D17).** Its field pattern ran past a line's end, so an
  empty field took the next line as its value; a value is now the rest of the field's
  own line, and a nested list reads as empty, so several alternatives are written on
  the one line, separated by `; or`.
- **The uv guard (D24 item 7).** `uv_project.py` imports the version check inside the
  function that runs it, its reason beside it: the image Dockerfiles copy that script
  alone to run `image` and `install-wheel`, which install a committed lock and are not
  checked. The eight locks still at revision 3 named no internal package, so `make
  lock` passed uv no `--upgrade-package` for them and uv, finding nothing changed,
  left them at their revision; a later rise of the minimum leaves such locks behind
  again, and the revision check names them. `install.sh` pins uv 0.8.13 and only syncs
  its own install copy, which reads a revision-5 lock and leaves it unchanged. Found
  and fixed in place: the root `Makefile`'s `init-prerequisites` and the registry's
  `init-uv` installed uv 0.8.13 where none was installed, which the guarded `reinit`
  would refuse; both install the minimum.
- **Running gitleaks (D24 item 4, D29).** `check_secrets.py` runs gitleaks from the
  repository root whatever repository it scans, passing the scanned repository as its
  source, because gitleaks resolves `[extend] path` from its working directory; so the
  nested extension loads and D29's fallback was not needed. The hooks run both
  public-content checks, each reporting even after the other refused, and need Python
  3.11, since the installer reads `tomllib`. Found and fixed in place: the VM IaC
  README's credential (D25).
- **The closing checks (D24).** The destinations check names a change's design and
  proposal files in code, so comment hygiene exempts it there, as it exempts the task
  file's name in the computation. A local import whose only comment is tool directives
  (`noqa`, `type: ignore`, and the like) gives no reason; one followed by a reason
  does. Run on this branch, the history-wording check found three comments sections 1
  and 3 had added, which were reworded. Found and fixed in place: the roles test
  collected only `change-*` skills, so it never read `guidance-review`; it reads every
  workflow skill, and still not OpenSpec's own.
- **Guidance reviews (D20, D11).** The skill refuses to run unattended or in a clone,
  whose archive is lost with it; its period is UTC timestamps, a record belonging to
  it after the start and at or before the end; a finding is counted in the period of
  its first triage; and a revisit of the advancing exit counts under that exit, not
  among revisited findings. The owner's term questions are read from the step
  sessions, not tallied from the workflow logs as D11 had it, since the logs do not
  hold them.
- **Declined in the guidance and skills.** "Implementation rules" placed elsewhere
  than `ARCHITECTURE.md`, since D8 and D10 name it; and removing the triage skill's
  "The owner decides what to do with each finding", kept as the principle, since
  every default acceptance is the owner's to revisit.

## Design promotion record

The `spec.md` requirements named by id were written by the archive from the change's
deltas; every other location was written by hand, in implementation or at closeout.

| Accepted decision | Permanent location |
|---|---|
| D1, the table of default acceptances | `openspec/specs/change-workflow/spec.md` (CW-t9bx); `openspec/specs/change-workflow/README.md#the-owner-is-interrupted-only-for-judgement`; `docs/agents/change-workflow.md#default-acceptance` |
| D2, advancing is the default exit | `openspec/specs/change-workflow/spec.md` (CW-9pbk, CW-3tvs); `openspec/specs/change-workflow/README.md#the-owner-is-interrupted-only-for-judgement`; `docs/agents/change-workflow.md#default-acceptance` |
| D3, the default rule, its rationale and baseline | `openspec/specs/change-workflow/spec.md` (CW-d5ac, CW-j1nv, CW-neua); `openspec/specs/change-workflow/README.md#triage`; `docs/agents/change-workflow.md#default-acceptance` |
| D4, revisits outside the graph | `openspec/specs/change-workflow/README.md#triage` |
| D5, deferred work | `AGENTS.md#deferred-work` |
| D6, defects found during a change | `openspec/README.md#defects-found-during-a-change`; the review, triage, design and implementation skills |
| D7 | no permanent destination — a decision not to add a rule |
| D8, no speculative guard code | `docs/development/ARCHITECTURE.md#no-speculative-guard-code` |
| D9, amend a rule or comply | `AGENTS.md#amend-a-rule-or-comply` |
| D10, prefer an existing library | `docs/development/ARCHITECTURE.md#prefer-an-existing-library` |
| D11, the vocabulary's homes and the workflow's terms | `docs/agents/domain.md`; `openspec/specs/change-workflow/spec.md#terms`; `AGENTS.md#domain-docs` |
| D12, the promoted preferences | `docs/agents/change-workflow.md#skills`; `.agents/skills/change-design/SKILL.md`, "Classify each decision" |
| D13 | no permanent destination — the existing rule stays as written |
| D14, the owner can always reach a running step | `openspec/specs/change-workflow/README.md#the-orchestrator-relays-and-routes` |
| D15, interrupting a running step | `openspec/specs/change-workflow/spec.md` (CW-k2rv, CW-h7lq, CW-w4ne); `openspec/specs/change-workflow/README.md#the-orchestrator-relays-and-routes`, and the `stop` subcommand in `#interfaces-are-tiered`; `docs/agents/change-workflow.md#orchestrating-a-change` |
| D16, revisiting a default acceptance | `openspec/specs/change-workflow/spec.md` (CW-r8vz); `openspec/specs/change-workflow/README.md#triage` and `#steps-run-headless-and-resume-with-the-owners-answers`; `docs/agents/change-workflow.md#orchestrating-a-change` |
| D17, reviewers' alternatives | `openspec/specs/change-workflow/spec.md` (CW-a2lf); `openspec/specs/change-workflow/README.md#reviews-are-files`; `docs/agents/change-workflow.md#reviews` |
| D18, the classification record | `openspec/specs/change-workflow/spec.md` (CW-d5ac); `openspec/specs/change-workflow/README.md#triage`; `docs/agents/change-workflow.md#default-acceptance` |
| D19, the revisit marker | `openspec/specs/change-workflow/spec.md` (CW-v1rk); `openspec/specs/change-workflow/README.md#the-intervention-ledger`; `docs/agents/change-workflow.md#the-ledger` |
| D20, guidance reviews | `openspec/specs/change-workflow/spec.md` (CW-g6ua); `openspec/specs/change-workflow/README.md#guidance-reviews`; `.agents/skills/guidance-review/SKILL.md` |
| D21, how the revisit rate is read | `openspec/specs/change-workflow/README.md#guidance-reviews` |
| D22, waiver recommendations and waived parts of validation | `openspec/specs/change-workflow/spec.md` (CW-q3dm, CW-n6wy, CW-zkhs, CW-e7lm); `openspec/specs/change-workflow/README.md#the-owner-is-interrupted-only-for-judgement`, `#validation-observes-a-committed-slice` and `#the-intervention-ledger`; `docs/agents/change-workflow.md#waivers` |
| D23 | no permanent destination — guidance is removed |
| D24, the seven checks | `openspec/specs/market-change-workflow/spec.md` (MCW-c4ek, MCW-s8gk, MCW-l5rv); `openspec/specs/market-change-workflow/README.md#the-closing-checks`, `#one-lock-revision` and `#secret-scanning`; `docs/agents/change-workflow.md#skills`; `docs/development/ARCHITECTURE.md#public-repository-content-checks`; `docs/development/BUILD_AND_PACKAGING.md#locks`; `openspec/specs/README.md`, the `contact-exchange-settlement` row |
| D25 | no permanent destination — a defect fixed in place |
| D26, the gate's rules | `openspec/specs/market-change-workflow/README.md#secret-scanning`; the comments of `.gitleaks.toml` |
| D27, what the gate refuses and passes | `openspec/specs/market-change-workflow/spec.md` (MCW-s8gk) |
| D28, the tree test as the guard on an upgrade | `openspec/specs/market-change-workflow/README.md#secret-scanning` |
| D29, the audit | `openspec/specs/market-change-workflow/spec.md` (MCW-u2dt); `openspec/specs/market-change-workflow/README.md#secret-scanning`; `docs/development/RELEASING.md#cutting-a-release` |
| D30 | no permanent destination — the change's own cadence |
| Roadmap currency | no impact: the change serves no goal of `docs/development/ROADMAP.md` and closes no gap row there |
| Campaign index currency | the change's row in `openspec/changes/README.md`, under "Independent active changes", set to `in closeout` and linked to its archive; no campaign graph holds it |

## Open Questions

None. What is deferred has its trigger in a decision: widening or narrowing Rule E,
waivers by default, and normalizing revisits into the graph are proposed by a guidance
review (D4, D21, D22); adopting ADRs is not proposed (D23); and whether skills can
cite instead of restating is `layer-engineering-guidance`'s open question (D12).
