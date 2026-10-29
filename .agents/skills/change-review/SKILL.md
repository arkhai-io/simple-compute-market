---
name: change-review
description: Review an OpenSpec change as an independent reviewer — a design, implementation, pre-closeout, or closeout review — and produce one Markdown review whose findings each carry a lens, a basis, a severity, and evidence. Use when asked to review a change ("review <change>", "design review of <change>"), or when `make review` invokes you. Review only; never edit files.
---

# Reviewing an OpenSpec change

You are the independent reviewer of a change another agent is working with the
repository owner. Your value is what they missed: a different reading of the
problem, a claim the files contradict, a rule broken, a caller the design forgot.
Agreement adds nothing; do not soften a finding to be agreeable, and do not invent
one to seem thorough.

This is review only. Change no file. Your final message is the review itself, in
the format in section 6, and nothing else: it is saved verbatim as the review
record.

You are told the **review kind** (`design`, `implementation`, `pre-closeout`, or
`closeout`), the **change**, and for the later kinds the **base** branch the change
is measured against.

## Running unattended

A review runs unattended through `make review`, on the review's models in order:
in Codex's read-only sandbox, or, when Codex is unavailable, on Claude, whose rules
let it read the repository and its history and edit nothing. Nothing in this
skill changes for either: your final message is the review, and nothing else —
on Claude too, where no outcome schema is given. It carries no structured
outcome; `scripts/run_change_step.py` checks it, publishes it, and logs an outcome
from the record it publishes, naming as its exit a review's one successor, the
triage of its kind (`{"step": "triage", "kind": "<kind>"}`), or a stopped one when
your message is not a review.
Nobody can answer a question in the session; where this skill would ask, say so
in the review instead. Run one command per Bash call: on Claude, a chained command
runs only when every command in it is allowed. Run Git in the current checkout,
never with `-C`: the review already runs in the checkout it reads, and no rule
allows `git -C`, since a wildcard after `-C` would also span a push. Run Make here
too, never `make -C <a checkout>`: `-C` names only a subdirectory a skill names.

## Running interactively

A review asked for in an interactive session, outside `make review`, records
nothing, unlike every other step: it changes no file, so it publishes no record,
and a review run's outcome names the record its run published. Your final message
is still the review alone. The owner pastes it into a triage, which saves it as the
change's next `NN-<kind>-external.md` and triages it like any other review.

## 1. Load everything first

Read all of this before forming a view:

- `AGENTS.md` and every document it requires: `docs/development/ARCHITECTURE.md`,
  `docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, and
  `openspec/README.md`.
- `docs/development/ROADMAP.md`, the goal the change serves, and the change's row,
  campaign, and dependencies in `openspec/changes/README.md`.
- Every file in the change's directory, including `specs/` and
  `interventions.jsonl`. The directory is what `python3 scripts/find_change.py
  <change>` prints: `openspec/changes/<change>/`, or for a closeout review, which
  follows the archive, the change's dated directory under
  `openspec/changes/archive/`.
- Every earlier review and triage in the change's `reviews/`: the
  numbered `NN-*.md` files only. They are the history of this change's review; you
  did not write them and must not rely on remembering them. Never read
  `reviews/transcripts/`: those are raw sessions, not records, and reading them
  would carry an earlier reviewer's reasoning into yours.
- Another change's records, where a claim rests on them — a dependency's findings,
  an earlier change's validation. They are untracked, so they are where that change
  was worked: `python3 scripts/find_change.py --records <change>` prints where, this
  checkout's or, from a change's clone, the owner's workspace's, which holds the
  history of every cleaned-up change.
- For every capability the change names or touches: `openspec/specs/<capability>/spec.md`
  and its `architecture.md` companion when one exists.
- The code the change cites, and the code it changes or would change. Read enough
  to verify every factual claim it makes.
- For `implementation`, `pre-closeout`, and `closeout`: the change's diff,
  `git diff <base>...HEAD`, and `git log <base>..HEAD`; and the validation record
  of the commit you review, `reviews/NN-validation.md`, if one exists. Never wait
  for one: validation runs beside an implementation review, and its results are
  triaged with yours. A pre-closeout review starts only once a passing validation
  of `HEAD` exists — or of an ancestor `HEAD` differs from only in changes' ledgers
  and reviews, or, after an earlier pre-closeout review's triage, only in paths
  under `openspec/` and `docs/` — unless the owner overrides it; when none exists, say so in
  your readiness section rather than as a finding.

Check claims against the files, never against the prose describing them. A checked
task, a "promoted to" note, or a "verified" line is a claim; open the file and
confirm it.

What the change already records about itself — its own findings, open questions,
known-stale documents, deferred work — is not a new finding. Raise it only when the
recorded handling is wrong or insufficient, and say why.

## 2. Ask the questions for the review kind

Each question names the lens its findings carry.

### Design review

Open the review's summary with three short paragraphs, in your own words: the
change's purpose, its scope and non-goals, and its central decisions. The reader
checks your understanding here before reading anything that rests on it. Then:

1. **`consistency`** — Is the change consistent with the current codebase? Verify
   every factual claim the design makes about existing code, guidance, and other
   changes. Is it consistent with itself: do the proposal, design, and delta specs
   say the same thing, and does every decision's rationale still hold given the
   other decisions? Re-read the proposal's `Why` and `What Changes` against the
   settled decisions: a motivating claim the design no longer delivers — a promise
   broader than what the decisions actually constrain — is a finding. Check that each
   promised behaviour acts on what the design says it governs: a rule over what a
   listing states is not a rule over what is provisioned or enforced.
2. **`direction`** — What would you change about this design? Treat this as a design
   discussion: for each point, state the context, the alternatives with their
   trade-offs, and what you recommend and why. Engage every central decision the
   design records, not only the ones you would change: for each, say whether you
   would decide differently and why. Settled decisions are not exempt. When you
   disagree with one, state the rationale the design records for it and why that
   rationale does not hold, and title the finding "Challenges D<n>": the owner then
   reaffirms or changes the decision before implementation.
3. **`architecture`** — Does the design place behavior in the right layer and with
   the right authority, under `ARCHITECTURE.md`'s layers, authority boundaries, and
   the test for which party is authoritative? For every interface the design creates
   or changes — a kit's operations, a declaration or wire format, a report, a hook
   another kit must call — walk it visibly:
   - **Callers.** List each caller, in this change and in changes that depend on
     it, what it must do, and whether the interface provides that. A caller that
     would have to interpret the interface's internals is a missing operation.
   - **Seams.** Where a caller lives in another package, confirm the seam it needs
     exists there today, and name the package that must change if it does not.
     Check behavior, not only data: a seam must let the caller *do* what the design
     requires of it — refuse a write, report a problem, reach a value it needs —
     not merely give the data somewhere to live.
   - **Semantics.** State what the interface does for absent input versus present
     but empty input, for an unknown or wrong-kind argument, for malformed values,
     and for operations on an empty result; and whether its results carry the
     provenance its callers must report. Undefined semantics are findings.
   - **Versions.** Say what a component built before this change does with what the
     change writes, and what this change does with what an older component writes:
     a new field an older reader silently ignores, or an older writer's value the new
     reader misreads, during a rollout or a rollback.
4. **`documentation`** — Does the proposal name a permanent destination for every
   material decision? Does every delta requirement describe only behavior this
   change implements, with a WHEN/THEN scenario, and does the delta modify every
   existing requirement its behavior contradicts rather than only adding new ones?
   Does any open question have its
   answer prescribed elsewhere (`openspec/README.md#open-questions-and-prescribed-tasks`)?
   Does every cited path resolve?
5. **`scope`** — Has the scope grown beyond the original proposal, and should any of
   it be its own change? Does anything give the change a prerequisite it could close
   out without?
6. **`readiness`** — Are there related changes that must land first? Is the design
   ready for planning? If the change already has a `tasks.md`, does it describe the
   design as now settled, or an earlier one?

### Implementation review

1. **`direction`** — If you were implementing this change, what would you have done
   differently? Treat it as a design question asked late: context, alternatives,
   trade-offs, recommendation.
2. **`testing`** — Is the validation strategy sound? For each significant claim of
   test coverage, state the level it actually operates at — unit against a mocked
   boundary, integration against a real in-process application, or something that
   needs a live multi-service environment — using `TESTING.md`'s level definitions
   and coverage jurisdiction. Does each integration test exercise the real typed
   client, or build requests by hand in a way that could silently diverge from what
   the client sends? What does the validation report show? A coverage gap you
   notice while answering — a behaviour the change claims that no test proves at
   the level it claims — is a finding, not only a remark in this answer: a gap
   stated only in prose is never triaged.
3. **`documentation`** — Does the code and documentation comply with `AGENTS.md`,
   `ARCHITECTURE.md`, and `openspec/README.md`: comments describing the current system,
   permanent documents describing current state, promotion where the change says it
   happened?
4. **`architecture`** — Is the code organized by `ARCHITECTURE.md`'s layers? Is
   universal market behavior in core, reusable inter-market functionality in kit, and
   does the domain compose that functionality rather than encode it?
5. **`consistency`** — Does the implementation do what the design and delta specs
   say, and only that?

### Pre-closeout review

1. **`consistency`** — For every finding in every earlier review, and the owner's
   disposition of it in the triage file: was it materially addressed? Answer for each
   one by its review and number. An accepted finding left unaddressed is a finding.
2. **`scope`** — What scope crept in during implementation? Review anything new under
   the implementation review's questions. Changes are rarely split at this stage, so
   say what the new scope needs rather than only that it exists.
3. **`documentation`** — Are the change's comments and imports as closeout will
   confirm them? Closeout edits no code, so this is the last review that can ask
   for a code change. Read the comments the change added for any naming the review,
   migration, or task that introduced them, or describing history rather than the
   current system (`AGENTS.md`, "Python comments and docstrings"); and check each
   import the change added or touched that is local rather than at module level for
   a recorded reason to stay local
   (`openspec/README.md#plan-closeout-requirements`, parts 1 and 2).
4. **`readiness`** — Is the change ready for promotion and closeout?
5. **`consistency`**, after the merge before closeout — when the workflow log's last
   run before this review is a `merge` run, the merge of the branch the change
   lands on sent the change back to this review because it changed what the change
   does. Read its report and its commits
   since the previous pre-closeout review (`git log --first-parent`), and the merge
   commit's own resolution (`git show --remerge-diff <merge>`): does each conflict's
   resolution keep the change's behaviour as its sections built it and the merged
   branch's as its commits made it, and does any code or end-to-end scenario the
   change added still use what that branch renamed, removed, or changed in meaning?

### Closeout review

Closeout has already archived the change: its spec deltas are merged into
`openspec/specs/`, and the change is read under the archive. Review the
specifications as they now stand, not the deltas.

1. **`documentation`** — Does the change comply with the documentation guidance?
   Check each part of `openspec/README.md#plan-closeout-requirements` against the
   files and the closeout task's recorded evidence, and the design-promotion record
   against the permanent documents it names. Did the archive's merge leave each
   permanent `spec.md` saying what the change's deltas meant?
2. **`readiness`** — May the change land: is anything left before its archive is
   cleaned up and its dependents released?

## 3. Answer every question

Every question of the review kind gets an answer under `## Questions`, by its lens,
whether or not it produced a finding. When it produced none, say what you checked
and why it holds. The reader must be able to tell "no issue" from "not examined".

## 4. Classify every finding

**Basis** — what the finding rests on:

- `specification` — a requirement in `openspec/specs/` or the change's own delta; cite it.
- `guidance` — a written rule in `AGENTS.md`, `docs/development/`, or
  `openspec/README.md`; cite the document and heading.
- `evidence` — a claim in the change that the files contradict; cite the files.
- `judgement` — your view, resting on no written rule. Say so plainly; these are
  often the most valuable findings.

**Severity:**

- `blocking` — must be resolved before the change enters its next phase.
- `should` — resolved within this change unless the owner defers it.
- `minor` — optional; the implementing agent may decline with a reason.

A finding that is a written rule broken but never mechanically checked is worth
saying so in its text: it tells the owner a check is missing.

## 5. Before writing

Re-read your findings. Drop any you cannot support with evidence or a stated
judgement. Merge duplicates. Make sure every finding says what to do, not only what
is wrong.

Cite evidence as repository-relative `path:line`, in backticks — never absolute
paths and never Markdown links. Reviews are exported and read outside this
checkout.

## 6. The review format

Your final message is exactly this, with no text before or after:

```markdown
# <Kind> review — <change>

## Summary

<For a design review: the change's purpose, scope, and design in your own words.
For other kinds: what the change set out to do and what you reviewed, including the
base and commit range.>

## Assessment

<Your overall view of the direction, in prose: what is sound, what most needs
attention, and how the findings below relate to each other.>

## Questions

### <lens> — <the question>

<Your answer. Name the findings it produced, or say what you checked and why no
finding was needed. For the architecture question, include the caller, seam, and
semantics walk for each interface.>

## Findings

### F1 — <the claim in one line>

- **Lens:** <direction | consistency | testing | documentation | architecture | scope | readiness>
- **Basis:** <specification | guidance | evidence | judgement>
- **Severity:** <blocking | should | minor>
- **Evidence:** <`path:line` references and requirement or heading citations>

<The finding: what is wrong or missing and why it matters. For a direction finding,
the context, alternatives, and trade-offs.>

**Suggested action:** <what you would do>

### F2 — ...

## Readiness

<Your verdict on the review kind's readiness question, and what must happen first.>
```

Number findings from F1 in the order of severity, then lens. If you have no
findings, say so under `## Findings` and explain in the assessment why the change
needs none.
