# Change Workflow Architecture

The [normative contract](spec.md) defines the phases a change moves through, its
review records, triage, the intervention ledger, validation, and the push guard.
This document explains why the workflow is shaped as it is. How to run each step is
in [`docs/agents/change-workflow.md`](../../../docs/agents/change-workflow.md).

## What the workflow is for

A change's design and its guidance are where the repository owner's judgement
matters: deciding what a change does, and refining the rules so later reviews find
less. Everything else around a change is transport — carrying a review from one
agent to another, resuming a session that stalled, running the same validation
sequence before every review. The workflow makes agents do the transport. Each
phase's procedure is written once, as a skill any agent harness can load; reviews
are exchanged as files; validation runs unattended; and the owner reads every
finding and decides every design question.

## Leaf skills from one source

Each step is its own skill (`change-design`, `change-plan`, `change-review`,
`change-triage`, `change-implement`, `change-validate`, `change-closeout`,
`change-archive-cleanup`), started by the owner. A step does one thing and stops,
so its failure modes are visible on their own; an orchestrator that advances a
change through every step, and chooses what to work on next, is meant to be built on
these once their failure modes are known, and is not part of this capability.

A skill has one source under `.agents/skills/`, and each harness loads it through a
link (`.claude/skills/`, `.codex/skills/`). Two copies drift, and the drift is
silent: the rule that differs is the one nobody re-reads. `make check-agent-skills`
fails on a missing link, a copy, or a link that does not resolve.

## Fresh sessions are the unit of implementation

Compliance with the repository guidance degrades as a session grows, and sharply
once it compacts. `AGENTS.md` is loaded as system context and survives, but the
documents it requires reading enter through tool calls, are ordinary conversation,
and are summarized away; the summary keeps the task state and drops the rules.
Before compaction the same rules sit ever further behind tool output.

A fresh session per `tasks.md` section is therefore the default. Planning sizes
each section to fit one; the session reads the guidance, the change, and its
section; and anything a later session needs goes into the change's files before
the section is committed. A fresh-context agent checks the section's diff against
the guidance before commit: it does not share the implementer's degradation. The
owner may let a session continue into later sections while its context is still
small enough to trust; each is still checked and committed on its own.

Within a Claude Code session, a hook that runs after compaction sends the session
back to the documents themselves. It never injects a digest of their rules: the
hook's context is capped far below the documents' size, and a digest is a second
copy that drifts. Codex has no equivalent, so section sizing is what both harnesses
rely on.

## Reviews are files

A review is one Markdown file in the change's `reviews/` directory, and the only
record of its findings. Later reviews and triage read earlier findings and their
dispositions from these files rather than from any session's memory, which is what
lets a pre-closeout review ask a different session whether earlier feedback was
addressed, survive compaction, and run under either harness. A structured copy
beside each review would be a second source that can disagree with it.

A re-review continues its own reviewer, so the reviewer weighs a revision with the
context that led to its findings; it still reads the triage from the records. A
reviewer's raw session is kept as a transcript, but no review or triage step reads
one: a transcript carries the session context the file exchange exists to keep out.
The reviewer runs read-only and never writes the record itself; its answer is
published only when it has the review format, so an error or a truncated answer never
becomes history.

`reviews/` is untracked: it is working history, and anything durable in it reaches
permanent documentation through promotion. It moves with the change into the
archive and stays there until an export flow carries it elsewhere.

## A finding has a lens, a basis, and a severity

A flat list of finding classes conflates two questions: what kind of attention a
finding needs, and what it rests on. Test coverage is both a kind of attention and
an application of written guidance, so a `coverage` class and a `compliance` class
overlap. A finding therefore carries a lens (`direction`, `consistency`, `testing`,
`documentation`, `architecture`, `scope`, `readiness`) and a basis
(`specification`, `guidance`, `evidence`, `judgement`) as separate axes, with a
severity beside them.

The basis is what makes the owner's corrections useful. A `guidance` finding that
reached a review means a written rule was not mechanically enforced, and the
question is which check should have caught it. A `judgement` finding the owner
accepts is an unwritten rule, and the question is whether to write it.

## Triage

The implementing agent states a position on every finding — agree, disagree, or
partly — with a reason either way, so that deference to the reviewer is visible
rather than the default. Every finding reaches the owner, one per message, each
after any decision that could change it: a summary up front invites dispositions
before the arguments are read, and a question about one finding is not acceptance
of another. A finding is disposed of only when the owner says so.

The intervention ledger (`interventions.jsonl`, tracked) records only the owner's
course corrections: deciding otherwise than the agent proposed, or adding context
that changes the work. Most dispositions accept the proposal and are recorded only
in the triage file; the ledger exists to show where the agents' judgement needed
correcting, and the owner's periodic guidance reviews read it. It is tracked so it
travels with the change through archival.

## Validation observes a committed slice

An implementation slice is committed before it is reviewed, so validation describes
one commit and must not change the checkout: a step that rewrites a tracked file
validates a tree that is not the commit, then pushes and runs end to end against the
commit that was never checked. Validation therefore fails rather than repairs. It
never relocks: `make lock` would silently repair the stale lock `make
check-packaging` exists to report, so relocking belongs to implementation, and a
stale lock sends the slice back.

The wheelhouse in `.dist` is shared by every branch built in the checkout, and
environments sync internal packages with an upgrade, so a higher version another
branch left behind is installed in place of the one the commit builds. Each part
therefore starts from `make dist-clean`.

Validation has a local part, a Helm part, and the end-to-end pipeline, which starts
first because it is the slowest. The Helm part deploys a fresh release with no
retained volumes, so a run never starts from state another commit wrote, and runs
the pipeline scenarios the default charts can serve, reporting every other one as
not run against Helm rather than as passed. It assumes full control of the Docker
daemon, the allowed kube context, the release, the port-forwards, and the
wheelhouse.

"Fixes nothing" protects the commit, not the machine. A failure diagnosed as
environmental is put to the owner with its remedy and its part rerun on the owner's
word; only failures the commit caused, or whose cause is unknown, become findings.
A result is `passed`, `failed`, or `inconclusive`, the last meaning no failure was
the commit's but some part produced no evidence.

## An implementation round is triaged together, in a fresh session

The owner's reading of a round, the implementation review, and the validation of the
same commit are triaged in one session that is not the implementing one. Validation
results go to triage, not to the reviewer: a reviewer given them would wait an hour
for the pipeline, could fix nothing, and judges the code the same either way; and
fixes for failures and findings often touch the same code. The owner's notes are
saved verbatim and evaluated like any finding, not obeyed, so a note the files
contradict is answered with the evidence.

The owner reads a round as uncommitted changes in the checkout, because that is
where the owner reads and runs tests: `make round-view` resets the branch to the
round's base with the files unchanged, and `make round-done` returns it. A worktree
beside the checkout leaves the commits and validation untouched but needs a second
editor project each round and lacks the owner's test setup; an editor comparison
against a base ref reads as a comparison, not as the changes being worked. While a
view is open, every step that describes or publishes a commit refuses.

## Pushing is guarded, never repaired

Validation pushes the change's own branch, because the pipeline runs against the
pushed branch. An unattended push needs a mechanical definition of that branch, so
the guard refuses a detached `HEAD`, a dirty worktree, `main` or `dev`, and an
upstream of another name, and the push sends exactly `HEAD`, never forced. Each
refused state means something unexpected happened; an agent repairing it would hide
that.

## Phases, gates, and archival

A change moves through design, planning, implementation, and closeout, and a phase
ending in a review is finished only when the owner passes that review's gate in
triage. Planning starts only after the design gate, so a review that redirects the
design never discards a plan; a design question planning exposes returns the change
to design.

Closeout and archival are one phase. Closeout writes the documents OpenSpec does not
synchronize, then archives the change, which merges its deltas into
`openspec/specs/`, so the closeout review reads the specifications as they will
land rather than inferring them from the delta. The steps after the archive find the
change by name under its dated directory; design, planning, and implementation have
nothing to do with an archived change and refuse it.

Closeout changes documentation only. The code was last reviewed at pre-closeout and
the closeout review reads documentation, so a closeout code edit would go unreviewed
as code; comment hygiene and import placement are therefore done before the
pre-closeout review and only confirmed at closeout. A code defect a closeout review
does find stops for the owner, who directs the correction and decides whether it
needs another reader; reopening the change for a full round is not required for what
is expected to be rare.

Archive cleanup follows the closeout gate as a step of its own, with its own entry
checks, rather than as the end of triage: it releases the change's dependents, sets
it `archived`, and drafts the merge, and is the point at which the change lands.

## The index states what may start

The active-change index is what the orchestrator will read to decide what starts
next, so a row's status names its phase and its state within it (`ready for`, `in`,
`blocked in`), and dependencies on other changes sit in their own column with the
phase each gates. A single word such as `active` cannot carry that decision; it
erases the difference between a change waiting for design and one waiting for a
plan, which separate skills perform.

When a dependency lands, its dependents' designs rest on a codebase it has just
altered, so archive cleanup returns each dependent not yet implementing to design.
That ties reverification to a step that already runs. A dependent already in
implementation, or blocked for its own reason, keeps its status.

Every step that edits the index runs `make check-change-index`. The citation check
cannot see those edits: it is scoped to a change's own documents, and the index's
links are relative directory links. The check covers active changes only; archived
rows are recent history and may be pruned at any time.

## Current limits

- One change is worked at a time in one checkout: validation takes the whole
  environment, and the wheelhouse, the branch, and the Helm release are shared.
  Working changes in parallel is `parallel-change-workflows`'.
- The Helm run serves only the scenarios the default charts can: the charts lack the
  pipeline's full topology, which `helm-e2e-pipeline-parity` owns.
- Sessions are started by the owner; no orchestrator advances a change or chooses
  the next one.
- Review transcripts persist only in the untracked `reviews/` directory until an
  export flow exists.
