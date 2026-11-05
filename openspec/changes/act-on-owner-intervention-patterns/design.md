# Design: accept uncontested triage outcomes, and write down what the owner does

Status: proposal. The owner settled the direction under "Decided" on 2026-11-04,
while reviewing how they dispose of findings and what their corrections say about the
guidance. Everything under "Open questions" is undecided. The batch rule's exact
width, and the wording of each guidance edit, are settled in this change's design
session from the evidence below.

## Context

### Triage

- **Every finding reaches the owner, one per message.** "Triage of every finding" in
  `openspec/specs/change-workflow/spec.md` requires every finding to be presented,
  none withheld for being minor or uncontested, and disposed of only when the owner
  states a disposition. "Discussion steps stay conversations with the owner" requires
  an orchestrated triage to present one decision or finding per turn.
- **The skill forbids proposing a batch.** `.agents/skills/change-triage/SKILL.md`
  section 3 orders findings most severe first, after any decision that could change
  them. The owner may answer several at once, but the agent never proposes it.
- **The reason is recorded.** `openspec/specs/change-workflow/architecture.md`,
  "Triage", says a summary up front invites dispositions before the arguments are
  read, and that a question about one finding is not acceptance of another. Both hold
  for this change: a default-accepted finding is never presented as a summary inviting
  a disposition, and silence never disposes of a discussed finding.
- **The gate question is asked every round.** "Phases and owner touchpoints" requires
  triage to ask whether the dispositions merit another review round before any fix.
  Section 6 of the skill has the agent recommend from what the fixes change.
- **Revisions already have a ledger form.** "Intervention ledger" logs only
  corrections. An entry that revises an earlier one starts its `owner_disposition`
  with `revises <review> <finding>:` (`docs/agents/change-workflow.md`, "The ledger").

### Guidance

- **Issues.** `AGENTS.md` "Issue tracker" says "GitHub Issues handle intake and
  triage through the `gh` CLI". "Triage labels" maps five labels for that tracker.
  `docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md` are generic
  templates; the latter still says "Edit the right-hand column to match whatever
  vocabulary you actually use".
  - The issue-discovery harness files its own deduplicated issues
    (`docs/development/ISSUE_DISCOVERY.md`). That is a separate tool.
- **Defects found during a change.** `openspec/README.md`, after the closeout parts,
  calls a growing closeout task "a signal the change may have scope-crept". The
  design skill's settling step says "a change that can close out on its own is
  preferred to one waiting on another".
- **Vocabulary.**
  - `docs/agents/domain.md`, "Use the glossary's vocabulary", sends agents to each
    context's `CONTEXT.md` and gaps to a `/domain-modeling` skill. Neither exists.
  - `AGENTS.md` "Domain docs" cites `docs/adr/`, which does not exist.
  - `docs/development/ARCHITECTURE.md` has a "Shared vocabulary and identities"
    section and a one-name-per-concept rule.
- **Promoting principles.** The design skill lists principles the owner stated that
  no document records, for the owner to pick from.
- **Stored-state migrations.** `docs/development/ARCHITECTURE.md`, "Operators", makes
  schema changes additive by default, with expand and contract for the rest.
  `docs/development/DEPLOYMENT_AND_CONFIG.md` records four upgrades that departed from
  it.

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
- **An added condition costs little after the fact.** The fix stands, and the owner
  adds the condition when reading the table. An override costs a fix made and then
  undone.

A search over every combination of up to four of these features found rules covering
more of the earlier changes at about 2% intervention. On the later changes those rules
rose to 10–14%, so the extra width does not generalize. The candidates above are
stated in the workflow's own terms rather than fitted.

### What the owner's corrections say about the guidance

#### Method

- **Inputs.**
  - The intervention ledgers of every change carrying one: 506 corrections, 365 from
    triage, 131 from design discussions, and 10 from planning.
  - The 63 triaged findings whose basis is written guidance, each with the reviewer's
    own text naming the rule.
  - The 53 whose basis is the reviewer's judgement.
- **Two kinds of signal**, as `openspec/specs/change-workflow/architecture.md` frames
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
  documentation (33) and testing (12), and the owner accepted 52 as proposed. So the
  written rules are right, and enforcement is the gap.
- **Guidance that contradicts the owner's practice:**
  - **Issues.** The owner declined a proposed issue in at least five product changes
    and seven workflow corrections.
  - **Defects found during a change.** Seven product changes and seven workflow
    corrections fixed a small defect in the current change, against guidance that
    leans toward splitting.
  - **Migrations.** The owner overrode three of the four findings that cited the
    migration rule. This is decided below: the rule stays.
  - **Promoting principles.** In six changes the owner narrowed which principles to
    promote. This is decided below: the flow stays.
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
  | Comments describe the current system | 4 | `check-comment-hygiene` matches only task and section numbers and file names |
  | Test at the level that can prove the behaviour | 4 | no |
  | One version bump per changed package | 3 | no |
  | Public-repository discipline | 3 | no pattern for private-key blocks |
  | Import placement | 2 (4 with ledgers) | no |
  | The capability index lists every capability | 1 | no; `contact-exchange-settlement` has no row today |

## Decided

### Triage

- **D1 — Default-accepted findings are reported at the end of the round, not asked.**
  Triage reports them in one table after the discussed findings are disposed of. They
  are accepted without the owner's confirmation, alongside an advancing exit. The
  owner reads the table and may interrupt, or revisit a finding later, through the
  orchestrating session.
- **D2 — Advancing is the default exit.** When the agent recommends advancing, triage
  advances without asking. A recommendation of another round is argued and asked, as
  today.
- **D3 — The batch's width is set from the evidence.** It uses the triage-time facts
  measured above:
  - the reviewer's severity and the record the finding came from;
  - the agent's stance and proposed outcome;
  - whether the agent sees an alternative, or a fact that would change its mind;
  - what the fix affects.

  The owner earlier accepted excluding `blocking` findings. That exclusion is part of
  what design confirms against the table.
- **D4 — Revisits stay outside the workflow graph.** If revisits of default
  acceptances become frequent enough to complicate rounds, normalizing them into the
  graph is a later change.

### Guidance

- **D5 — The issue-tracker guidance is corrected.** It is false: the owner does not
  use GitHub Issues. The issue-discovery harness's own filing is not affected.
- **D6 — Where a defect found during a change is fixed is stated as the owner's
  practice, with nuance.** The owner weighs a defect's size and how well it is
  understood against a change's process overhead. A separate change, or an unowned
  gap, is for a defect large enough or vague enough to merit it. The owner holds this
  as a preference, not a correctness rule, and will consider wording that says so.
- **D7 — No rule tells agents to recommend the narrowest fix.** The owner's scope
  growth usually comes from proposing to refactor and unify the VM and bare-metal
  domains, which is larger than fixing one service. `ARCHITECTURE.md` favours one
  behaviour composed from a shared kit. A narrowest-fix rule would work against both.
- **D8 — No speculative guard code.** Production code adds no refusal, warning, probe
  or hardening for a case that nobody can describe, or that no integration or
  end-to-end test could deliberately trigger.
- **D9 — Amend a rule or comply.** When work conflicts with a written rule, the rule
  is amended first or the work complies; a private exception is never recorded. This
  includes the owner's standing rule that the testing layers change only by changing
  `TESTING.md`.
- **D10 — Prefer an existing open-source library.** Use one wherever it meets the
  requirements, and build our own only when none does. The relay plugin was built
  because no library met its requirements.
- **D11 — Agents keep a consistent vocabulary.** Agents often invent vocabulary. When
  the owner cannot follow an agent's language, that usually means what it describes
  is wrong, or that the vocabulary guide needs clarifying. The owner then asks what a
  mechanism is for and what the words mean. A consistent vocabulary is needed to
  maintain the codebase.
- **D12 — The owner's working preferences belong in the repository.** Preferences
  such as fixing small defects in the current change go into the skill or guidance
  document that governs them, not into an agent's private memory. This change
  reviews the agent's memory as it stands and promotes the candidates the owner
  picks.

### Not changed

- **D13 — The migration rule stays.** Whether anything is deployed is a decision the
  team manages, not a fact inside the repository. A feature branch does not know where
  its change will run. After 1.0.0, merges to `main` may come to mean official
  launches, but that is not true yet. So no exception for undeployed state can be
  derived from the repository.
- **D14 — Promoting principles stays as it is.** The design agent documents candidate
  principles, and the owner picks and clarifies each promotion. Guidance changes take
  most of the owner's review attention, because they shape how the product evolves,
  not only how it is now.

## Starting recommendations

### The batch rule

Rule E: the agent agrees with the finding and proposes one edit or fix. It sees no
alternative worth laying out and nothing that would change its recommendation. The
finding comes from a review. It is not `blocking`. Its fix affects no interface or
representation, migration or compatibility path, scope, or validation environment.

- **Why E.**
  - It keeps the `blocking` exclusion the owner accepted.
  - Its topic exclusions remove the remaining added-context cases without a fitted
    condition.
  - It covered 23% of presented findings: 1 accepted with a condition and 1
    overridden.
- **Widening later.** The batch can be widened to D or B once its measured revisit
  rate shows what a wider rule would cost.

### Where deferred work goes (D5)

The `AGENTS.md` section becomes something like this:

> Deferred work is recorded in the open change that owns its area, or in a new
> change, or as an unowned gap in `openspec/changes/README.md` or
> `docs/development/ROADMAP.md`. This repository does not use GitHub Issues for its
> own work.

`docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md` are deleted, and
the "Triage labels" section goes with them.

### Where a defect found during a change is fixed (D6)

A draft for `openspec/README.md` and the triage skill's `fix` outcome:

> A defect found while working a change is fixed in that change when its fix is
> understood and small beside the change, even outside the change's stated scope. A
> defect large enough, or not yet understood well enough, to need its own design gets
> a change of its own, or an unowned gap when nothing owns it. This is the owner's
> preference for keeping process overhead in proportion. It is not a rule that a
> change must stay narrow.

The scope-creep sentence in `openspec/README.md` keeps its point about deciding
deliberately, but no longer implies that growth is a fault. The design skill's
preference for changes that close out alone is reworded to match.

### Vocabulary (D11)

- **Name one home for the vocabulary.** Point `docs/agents/domain.md` at it, and
  remove the references to `CONTEXT.md`, `/domain-modeling` and `docs/adr/`, or create
  what they name.
- **The rule.** Agents use the established term. A term new to the reader is defined
  where it first appears and flagged as new, and is added to the vocabulary if it
  stays.
- **Clarification as a signal.** When the owner asks what a mechanism is for or what
  a term means, the agent answers in established terms, and either corrects the
  description or proposes the vocabulary entry.

### Memory candidates (D12)

The agent's memory for this repository, reviewed on 2026-11-04:

- **Already in the repository:**
  - questions asked in prose, never a selector (`AGENTS.md`, "Asking the owner");
  - the triage presentation format (`change-triage`, section 3);
  - the orchestrator relays and routes without its own view on findings
    (`change-orchestrate`);
  - the orchestrator opens the round view (`change-orchestrate`);
  - step runs are never time-limited (`change-orchestrate`);
  - checking the branch before writing to a change (several skills).
- **Candidates for promotion:**
  - **No GitHub issues.** Covered by D5.
  - **Fix small defects in the current change.** Covered by D6.
  - **Notes and proposals across changes.** Recording an open question in another
    active change's documents, or writing a new change's proposal, on the current
    branch does not breach one change per branch. That rule is about implementing
    another change. Home: `docs/agents/change-workflow.md`.
  - **State bookkeeping, don't ask it.** Documentation destinations, test placement
    and evidence bullets are stated, not asked, in a design discussion. The design
    skill covers destinations only. Home: `change-design`, "Classify each decision".
  - **A skill is never stricter than the guidance it restates.** The owner pushes back
    on over-strict rules in skills. Home: `docs/agents/change-workflow.md`, "Skills".
  - **Several implementation sections in one session.** The owner may run several
    sections in one session when context is small, and review them together; each
    section is still checked and committed alone. Design confirms whether rounds
    already cover this.
- **Not for the repository.** Two entries are the agent's own working notes on
  unrelated initiatives, not repository guidance.

## Open questions

- **Q1 — The agent's judgement is part of the rule.**
  - Severity, lens and basis are the reviewer's.
  - The stance, the outcome, whether an alternative exists, what would change the
    recommendation, and what the fix affects are the agent's own judgement.
  - The evidence was gathered while agents did not know a rule rewarded any of these.
    An agent that does know might drop alternatives or conditions to batch a finding.

  Options:
  - (a) Classify before writing any presentation, and record the classification's
    reasons in the triage file.
  - (b) Have the fresh-context compliance check, or the next review, audit a sample of
    default acceptances.
  - (c) Accept the risk and watch the revisit rate.
- **Q2 — How a revisit reaches the work.** The triage commits its fixes before the
  owner reads the table, so a revisit may arrive after the fix commit, or after the
  next step has started.
  - (a) The orchestrating session resumes the finished triage session with the owner's
    words. Triage amends the fix in a new commit and appends the ledger line.
  - (b) The revision is carried into the next round's triage as a point of the owner's
    notes.
  - (c) While the next step has not started, (a); after, (b).
- **Q3 — How a revisited default acceptance is recorded in the ledger.**
  - An owner's correction of a default acceptance is a course correction, so it is
    logged.
  - Whether it uses `revises <review> <finding>:`, which today marks a revised entry,
    or a distinct marker, decides whether a ledger review can count batch revisits
    apart from revised dispositions.
- **Q4 — Do the orchestrating session's own records qualify?** They mostly raise
  tooling observations whose outcome is often none. Rule E admits only an edit or a
  fix, so most would still be discussed. Whether any should be excluded outright is
  open.
- **Q5 — Agent-recommended waivers.**
  - Of the 35 recorded waivers, the owner initiated 34, often for commits that changed
    only specifications, comments or tests.
  - The skills say how to record a waiver, not when one is warranted.
  - Whether this change writes when a waiver is warranted, and has agents recommend
    one, is open.
- **Q6 — The revisit-rate trigger.** At what measured rate of revisited default
  acceptances the rule is narrowed, or D4's workflow-graph change is opened, and which
  review reads it.
- **Q7 — The wording of D6.** Whether the draft above states the preference with the
  nuance the owner wants, and whether it belongs in `openspec/README.md`, the triage
  skill, the design skill, or all three.
- **Q8 — Where the vocabulary lives (D11).**
  - (a) `ARCHITECTURE.md`'s "Shared vocabulary and identities", extended into a
    glossary.
  - (b) The `CONTEXT.md` files `docs/agents/domain.md` already names, created per
    context.
  - (c) One glossary document beside `ARCHITECTURE.md`.

  It is also open whether the owner's clarifying questions should be tallied, so a
  later review sees which terms keep needing explanation.
- **Q9 — Which memory candidates are promoted, and where.**
- **Q10 — Mechanical checks.** The unenforced rules in the table above could each get
  a check:
  - a spec delta named in the proposal and closeout lists;
  - history wording in a diff's comments;
  - exactly one version bump per changed package;
  - private-key blocks;
  - unexplained function-local imports;
  - the capability index.

  Whether they belong here, or in a change of their own that needs no owner decisions,
  is open. The cheapest, the capability-index row for `contact-exchange-settlement`,
  is a one-line fix either way.
- **Q11 — The issue-tracker documents.** Whether they are deleted, as recommended,
  or kept and rewritten to describe the issue-discovery harness's filing only.
