# Design: accept uncontested triage outcomes by default

Status: proposal. The owner settled the direction under "Decided" on 2026-11-04,
while reviewing how they dispose of findings. Everything under "Open questions" is
undecided, and the batch rule's exact width is settled in this change's design
session from the evidence below.

## Context

- **Every finding reaches the owner, one per message.** "Triage of every finding"
  in `openspec/specs/change-workflow/spec.md` requires every finding to be
  presented, none withheld for being minor or uncontested, and disposed of only
  when the owner states a disposition. "Discussion steps stay conversations with
  the owner" requires an orchestrated triage to present one decision or finding
  per turn.
- **The skill forbids proposing a batch.** `.agents/skills/change-triage/SKILL.md`
  section 3 orders findings most severe first, after any decision that could
  change them. The owner may answer several at once, but the agent never proposes
  it.
- **The reason is recorded.** `openspec/specs/change-workflow/architecture.md`,
  "Triage", says a summary up front invites dispositions before the arguments are
  read, and that a question about one finding is not acceptance of another. Both
  hold for this change: a default-accepted finding is never presented as a summary
  inviting a disposition, and silence never disposes of a discussed finding.
- **The gate question is asked every round.** "Phases and owner touchpoints"
  requires triage to ask whether the dispositions merit another review round
  before any fix. Section 6 of the skill has the agent recommend from what the
  fixes change.
- **Revisions already have a ledger form.** "Intervention ledger" logs only
  corrections. An entry that revises an earlier one starts its
  `owner_disposition` with `revises <review> <finding>:`
  (`docs/agents/change-workflow.md`, "The ledger").

## Evidence

### Method

The data is the triage records and workflow logs of every change triaged in this
repository's workflow, archived between 2026-10-14 and 2026-11-03. Each triage
record holds each finding's lens, basis, severity, the agent's position and
proposed outcome, and the owner's disposition. A change's records are untracked,
so the figures come from the owner's workspace copies.

- **Dispositions.** Each disposition was labelled from its recorded wording:
  - accepted as proposed;
  - accepted with added context, meaning a condition, a scope limit, or a fact the
    agent lacked;
  - overridden or questioned.

  The label "accepted as proposed" includes the recommended option when the
  outcome was a choice.
- **Presented text.** For 313 findings in 17 changes, triaged under orchestration
  from 2026-10-19, the workflow log keeps the full text the agent presented.
  Three facts were read from that text: whether it laid out alternatives, whether
  it said what would change its recommendation, and whether it called the fix
  clear.
- **Topics.** What each fix affects was tagged from the finding's title, lens and
  proposed outcome alone, without its disposition.
- **Gates.** Each gate's recommendation was read from the agent's last gate
  question in its session. It was paired with the exit the session took, and with
  the triage record's `## Next` where the session stopped before finishing.

The labelling is an agent's reading of recorded text. Small differences in a
handful of findings would not change the conclusions.

### Findings

Over all 478 findings: 79% were accepted as proposed, 8% accepted with added
context, and 13% overridden or questioned.

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

Single features of the 313 presented findings, by intervention rate (added context
or overridden):

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

Calling the fix clear adds little once alternatives and change-of-mind conditions
are known. Whether production behaviour changes predicts nothing (14 such
findings).

At the gates, the agent recommended advancing 56 times and the owner advanced 55
times. It recommended another round 20 times and the owner agreed 18 times.

Waivers of validation or of a design re-review numbered 35. The owner proposed 34
of them. The reasons:

- the commit could not affect validation (8);
- a known environmental failure (8);
- the review and validation records were at different commits (7);
- skipping a design re-review of a small decision (6);
- other (6).

### Candidate batch rules

Every candidate starts from rule A. Under A, the agent agrees, proposes an edit or
fix, and names nothing that would change its recommendation, and the finding comes
from a review, not a validation record or the owner's notes. The figures are over
the 313 presented findings. The held-out check fits nothing on the later changes:
"earlier" is the 232 findings of changes dated up to 2026-10-28, and "later" is
the 81 findings of the nine changes after it.

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
- **An added condition costs little after the fact.** The fix stands, and the
  owner adds the condition when reading the table. An override costs a fix made
  and then undone.

A search over every combination of up to four of these features found rules
covering more of the earlier changes at about 2% intervention. On the later changes
those rules rose to 10–14%, so the extra width does not generalize. The candidates
above are stated in the workflow's own terms rather than fitted.

## Decided

- **D1 — Default-accepted findings are reported at the end of the round, not
  asked.** Triage reports them in one table after the discussed findings are
  disposed of. They are accepted without the owner's confirmation, alongside an
  advancing exit. The owner reads the table and may interrupt, or revisit a
  finding later, through the orchestrating session.
- **D2 — Advancing is the default exit.** When the agent recommends advancing,
  triage advances without asking. A recommendation of another round is argued and
  asked, as today.
- **D3 — The batch's width is set from the evidence.** It uses the triage-time
  facts measured above.
  - The reviewer's severity and the record the finding came from.
  - The agent's stance and proposed outcome.
  - Whether the agent sees an alternative, or a fact that would change its mind.
  - What the fix affects.

  The owner earlier accepted excluding `blocking` findings. That exclusion is part
  of what design confirms against the table.
- **D4 — Revisits stay outside the workflow graph.** If revisits of default
  acceptances become frequent enough to complicate rounds, normalizing them into
  the graph is a later change.

## Starting recommendation

Rule E: the agent agrees with the finding and proposes one edit or fix. It sees
no alternative worth laying out and nothing that would change its recommendation.
The finding comes from a review. It is not `blocking`. Its fix affects no
interface or representation, migration or compatibility path, scope, or
validation environment.

- **Why E.**
  - It keeps the `blocking` exclusion the owner accepted.
  - Its topic exclusions remove the remaining added-context cases without a
    fitted condition.
  - It covered 23% of presented findings: 1 accepted with a condition and 1
    overridden.
- **Widening later.** The batch can be widened to D or B once its measured revisit
  rate shows what a wider rule would cost.

## Open questions

- **Q1 — The agent's judgement is part of the rule.**
  - Severity, lens and basis are the reviewer's.
  - The stance, the outcome, whether an alternative exists, what would change the
    recommendation, and what the fix affects are the agent's own judgement.
  - The evidence was gathered while agents did not know a rule rewarded any of
    these. An agent that does know might drop alternatives or conditions to batch
    a finding.

  Options:
  - (a) Classify before writing any presentation, and record the classification's
    reasons in the triage file.
  - (b) Have the fresh-context compliance check, or the next review, audit a
    sample of default acceptances.
  - (c) Accept the risk and watch the revisit rate.
- **Q2 — How a revisit reaches the work.** The triage commits its fixes before
  the owner reads the table, so a revisit may arrive after the fix commit, or
  after the next step has started.
  - (a) The orchestrating session resumes the finished triage session with the
    owner's words. Triage amends the fix in a new commit and appends the ledger
    line.
  - (b) The revision is carried into the next round's triage as a point of the
    owner's notes.
  - (c) While the next step has not started, (a); after, (b).
- **Q3 — How a revisited default acceptance is recorded in the ledger.**
  - An owner's correction of a default acceptance is a course correction, so it
    is logged.
  - Whether it uses `revises <review> <finding>:`, which today marks a revised
    entry, or a distinct marker, decides whether a ledger review can count batch
    revisits apart from revised dispositions.
- **Q4 — Do the orchestrating session's own records qualify?** They mostly raise
  tooling observations whose outcome is often none. Rule E admits only an edit or
  a fix, so most would still be discussed. Whether any should be excluded
  outright is open.
- **Q5 — Agent-recommended waivers.**
  - Of the 35 recorded waivers, the owner initiated 34, often for commits that
    changed only specifications, comments or tests.
  - Archive cleanup already exempts `openspec/` and `docs/` from its validation
    check, but no step recommends a waiver for comment-only or test-only commits.
  - Whether this change takes that in, or leaves it for a change of its own, is
    open.
- **Q6 — The revisit-rate trigger.** At what measured rate of revisited default
  acceptances the rule is narrowed, or D4's workflow-graph change is opened, and
  which review reads it.
