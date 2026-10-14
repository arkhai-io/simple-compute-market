# The change workflow

How an OpenSpec change moves from design to archive with agent skills: which skill
each step uses and how to start it, what a review leaves behind, and where the
owner's corrections are recorded. The phases, the closeout parts, and the rules
each step follows are in [`openspec/README.md`](../../openspec/README.md); the
status a change is in, and what it waits on, are in its row of the
[change index](../../openspec/changes/README.md). The workflow's contract is the
[`change-workflow` specification](../../openspec/specs/change-workflow/spec.md),
and why it is shaped as it is, its
[architecture companion](../../openspec/specs/change-workflow/architecture.md).

## Skills

Each step is a leaf skill under `.agents/skills/`, loaded by Claude Code from
`.claude/skills/` and by Codex from `.codex/skills/`, both links to the one source
(`make check-agent-skills` fails otherwise). A skill does one step and stops; the
owner decides what runs next. Start each in a fresh session unless its row says
otherwise, so it reads the change's files rather than an earlier session's memory.

| Step | Skill | Start it with | Writes |
|---|---|---|---|
| Design | `change-design` | `make design CHANGE=<change>` | `design.md`, `proposal.md`, the spec deltas, the index row |
| Design review | `change-review` | `make review CHANGE=<change> KIND=design` | `reviews/NN-design.md` |
| Planning | `change-plan` | `/change-plan <change>`, usually in the design session once its review's gate passes | `tasks.md`, ending with the closeout task |
| Implementation | `change-implement` | `make implement CHANGE=<change> [SECTION=<n> \| SECTIONS=<n-m>]` | the section's code and tests, its task notes, one commit |
| Implementation review | `change-review` | `make review CHANGE=<change> KIND=implementation` | `reviews/NN-implementation.md` |
| Validation | `change-validate` | `make validate CHANGE=<change>` | `reviews/NN-validation.md`; pushes `HEAD` and runs the pipeline |
| Triage | `change-triage` | `make triage CHANGE=<change>` | `reviews/NN-<kind>.triage.md`, `interventions.jsonl`, accepted fixes, the index row at a phase-closing gate |
| Pre-closeout review | `change-review` | `make review CHANGE=<change> KIND=pre-closeout` | `reviews/NN-pre-closeout.md` |
| Closeout | `change-closeout` | `make closeout CHANGE=<change>` | permanent documents, the promotion record, the archived change, one commit |
| Closeout review | `change-review` | `make review CHANGE=<change> KIND=closeout` | `reviews/NN-closeout.md` |
| Archive cleanup | `change-archive-cleanup` | `make archive-cleanup CHANGE=<change>` | the index (dependents released, row `archived`), one commit, `reviews/pull-request.md` |

The order is the one the phases give: design and its review until the design gate
passes; planning; then, per implementation section or group of sections,
implementation, its review beside validation of the same commit, and one triage of
both; a pre-closeout review and its triage; closeout; the closeout review and its
triage; archive cleanup. Every review is a gate only the owner passes, in triage.

A step that finds the change in the wrong state refuses and says why. Design and
implementation take only an active change. Closeout archives the change as its last
step, so every step after it — the closeout review, its triage, validation, archive
cleanup — finds the change under `openspec/changes/archive/` by its name
(`python3 scripts/find_change.py <change>`). `make review KIND=closeout` refuses a
change that is not archived, and `make archive-cleanup` one that is not.

Ask the owner questions in prose, never through a multiple-choice selector
(`AGENTS.md`, "Asking the owner").

## Reviews

`make review` runs the reviewer in Codex with a read-only sandbox, so it never
edits the tree. It captures the reviewer's final message, checks that it is a
review of the kind and change asked for — its sections in order, and every finding
carrying a lens, a basis, a severity, and evidence — and only then publishes it
under the next number. A review continues the previous reviewer's session of the
same kind, so a second design review knows what the first asked; `FRESH=1` starts
a new one. `REVIEW_BASE` is the branch the diff is taken against (`dev` by default),
and `REVIEW_MODEL` and `REVIEW_EFFORT` pick the reviewer. A pre-closeout review
refuses until the latest validation passed and names `HEAD`, or an ancestor that
differs only in the change's ledger and reviews; `UNVALIDATED=1` overrides that.
`make design-review CHANGE=<change>` is shorthand for `KIND=design`.

A review run elsewhere — in a browser session, by another tool — is pasted into
triage, which saves it verbatim as the next record, `NN-<kind>-external.md`, and
triages it with any other review of the same kind.

Before an implementation round is triaged the owner reads it:
`make round-view CHANGE=<change>` pushes `HEAD`, starts the end-to-end pipeline, and
shows the round as uncommitted changes in the checkout; `make round-done` returns
the branch to the round's commit. While a round view is open, every step that could
commit refuses (`make round-view-closed`). The owner's notes on the round go to
triage with the reviews.

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
  pull-request.md                    archive cleanup's merge drafts
  transcripts/
    01-design.log                    the reviewer's whole session
```

Files are numbered in the order they were produced, so the directory reads as the
change's history; no file is overwritten, and a run whose answer was not a review
publishes nothing and is kept beside its transcript as
`transcripts/NN-<kind>.rejected.md`. A numbered review is the
only record of its findings. Transcripts are kept for the owner's export of the
change's history, and no review or triage step reads them. Archive cleanup leaves
the directory in place.

The three steps that edit the index — triage at a phase-closing gate, closeout,
and archive cleanup — run `make check-change-index` after each edit. It checks each
row's cell count; its link to its change's directory (an `archived` row links its
archive, and a row linking an archive is `archived` or `in closeout`); its status
against the legend; that each dependency is listed and not archived; and that every
active change directory has exactly one row. An archived change needs no row:
archived rows may be pruned from the index over time.

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
Read together, a change's ledgers show where the guidance or the skills fell short.
