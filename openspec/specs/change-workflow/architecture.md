# Change Workflow Architecture

The [normative contract](spec.md) defines the phases a change moves through, its
review records, triage, the intervention ledger, validation, the push guard, and the
orchestrating session that advances a change through its steps. This document
explains why the workflow is shaped as it is. How to run each step is in
[`docs/agents/change-workflow.md`](../../../docs/agents/change-workflow.md).

## What the workflow is for

A change's design and its guidance are where the repository owner's judgement
matters: deciding what a change does, and refining the rules so later reviews find
less. Everything else around a change is transport — carrying a review from one
agent to another, resuming a session that stalled, running the same validation
sequence before every review, choosing which step runs next. The workflow makes
agents do the transport. Each phase's procedure is written once, as a skill any
agent harness can load; reviews are exchanged as files; validation runs unattended;
an orchestrating session carries the change from one step to the next; and the owner
reads every finding and decides every design question.

## Leaf skills from one source

Each step is its own skill (`change-design`, `change-plan`, `change-review`,
`change-triage`, `change-implement`, `change-validate`, `change-closeout`,
`change-archive-cleanup`). A step does one thing and stops, so its failure modes are
visible on their own. The owner may start any step by hand; `change-orchestrate`
starts them in turn, and is built on the leaf skills rather than replacing them, so
a step the orchestrating session runs and a step the owner runs are the same step.

A skill has one source under `.agents/skills/`, and each harness loads it through a
link (`.claude/skills/`, `.codex/skills/`). Two copies drift, and the drift is
silent: the rule that differs is the one nobody re-reads. `make check-agent-skills`
fails on a missing link, a copy, or a link that does not resolve.

## Sections are slices, sessions are the owner's

Compliance with the repository guidance degrades as a session grows, and sharply
once it compacts. `AGENTS.md` is loaded as system context and survives, but the
documents it requires reading enter through tool calls, are ordinary conversation,
and are summarized away; the summary keeps the task state and drops the rules.
Before compaction the same rules sit ever further behind tool output.

A plan nevertheless says nothing of sessions. A `tasks.md` section is a coherent
slice that one verification point proves, sized by what it changes and what proves
it; whether one session implements it, several sessions one each, or a coding
harness at all, is not the plan's concern, so the same plan serves any of them. How
many sessions implement the work, and how much each round covers before it is
reviewed, is the change's implementation cadence, settled in the design discussion:
the order of implementation can bear on the design, and a cadence settled there is
not asked about once the owner's attention has moved on. The design states it in
terms of the work, since section numbers do not exist yet; planning orders its
sections by it and reports, in its outcome rather than in `tasks.md`, the sessions
and rounds that implement them. The orchestrating session records each round from
that mapping as it starts, and asks the owner only for a change with no mapping.

Each session still starts with no prior conversation, reads the guidance, the
change, and its sections, and records anything a later session needs in the
change's files before each section is committed. A fresh-context agent checks each
section's diff against the guidance before commit: it does not share the
implementer's degradation. The risk of a growing session stays advice to weigh, not
a rule a plan enforces.

Within a Claude Code session, a hook that runs after compaction sends the session
back to the documents themselves. It never injects a digest of their rules: the
hook's context is capped far below the documents' size, and a digest is a second
copy that drifts. Codex has no equivalent.

## Steps run headless and resume with the owner's answers

A step the orchestrating session delegates runs as a headless Claude Code process
through one wrapper, `scripts/run_change_step.py`, which each step's `make` target
reaches with `UNATTENDED=1`. The wrapper gives the run the step's skill, its
permissions, and the outcome schema, records the run's session, and appends one
line to the change's workflow log. A step the orchestrating session runs and one the
owner runs by hand with `UNATTENDED=1` are the same process, and the owner can take
a stopped step over with `claude --resume <session>`. A subagent of the
orchestrating session would share its process, could not be started through `make`
or taken over from another terminal, and would need a second mechanism beside the
review's.

A question from a step is a resume, never a restart. The step ends its turn with a
`question` outcome; the owner's answer resumes the same session, which keeps its
history and carries on. The resume names the run it answers by its place in the
log, and the wrapper refuses a run that is not waiting, since with validation and a
review running side by side the log's last run is not necessarily the one that
asked. Design and triage are discussions held this way: each reply is a turn whose
message the orchestrating session shows the owner, and the owner's reply resumes
the step. The step's loading — guidance, specifications, code, reviews — stays in
its own session rather than accumulating in the orchestrating one, at the cost of
every turn replaying its session from the prompt cache. A discussion keeps one
decision or finding per turn: batched turns gave thinner answers, and an earlier
decision can change a later question. Planning resumes the design session, which is
usually still warm and holds the design's context.

Every run ends with an outcome — finished, a question, a proposed return to an
earlier phase, blocked on a prerequisite, or stopped — and the wrapper writes a
`stopped` line itself for a run that crashed or ended without one, since a step
writing its own outcome file writes nothing when it fails. The log is the wrapper's
alone and holds only what the files cannot: session ids, rounds, decisions, the last
outcome of each run, and its cost. Where the log and the change's files disagree,
the files win. A proposed return does not move the status: the owner confirms it as
a decision line, and the step it directs sets its phase's status as it always has.

The wrapper writes each run's event stream to a transcript under `reviews/` and a
progress file of one line per tool call, so whether a long step is stuck can be
read rather than waited out; `make change-watch` follows the progress files as each
step starts, into the archive when closeout moves the change there.

## Routing is code, with the model as backstop

Where a change stands, and what runs next, is computed by
`scripts/change_next_step.py` from the index row, the reviews and their triage, the
task list, the workflow log, and the round view's state, and printed as data. The
transitions are each skill's entry check and handoff written once as rules, so they
can be tested under `scripts/tests`, and the owner can run the same computation
(`make change-next`). Routing by the orchestrating session's own reading would be
only as reliable as the model on a given turn, and least reliable late in a long
session; a transition table written into a skill would still be read by a model, and
untestable.

The orchestrating session holds no state of its own. On every start and after
compaction it runs the computation and reads the log's last lines, so any session
picks a change up where the last one left it. When the computation errors, cannot
classify a state, or meets files and a log that disagree, the session works out what
happened: it decides routing or recovery itself — a step that died before writing an
outcome, a status set by hand — and brings to the owner anything that would decide
a finding, settle a design question, or change a status. Either way it records an
`orchestrator` line with what it decided and why. Those lines are the evidence for
what the computation should learn next.

A decision line names what it decides — the run it resolves, the run whose denials
it read, the step it directs — because a decision that cleared every run before it
let one decision about a stopped review silence a validation question waiting
beside it. Reading a run's denials and settling its outcome are separate lines: a run
can be denied a call and still end with a question, which is answered after its
denials are read.

## Restrictions bind unattended runs only

An unattended run uses Claude Code's `dontAsk` permission mode with its step's allow
and deny rules from `.claude/change-steps.toml`, so a tool it was not given is
denied and recorded rather than prompting a person nobody is watching. The rules
turn each skill's "never" lines into rules the harness enforces: validation's
"never changes the commit" stops being an instruction only. The table lives in
Claude Code's own directory because its rules are that harness's syntax, and it is
TOML because the scripts run on the standard library and its comments carry each
row's reason. No step may edit it or the project's Claude Code settings, so no step
widens its own or a later step's permissions; a step's permissions change as a
tracked edit the owner commits, or by a grant for one resumed run. An interactive
run is unaffected: the owner's own settings apply, with prompts.

Auto mode was rejected because what a step may do would rest on a classifier's call
per action, unreviewable in advance; a permission-prompt tool routing prompts to the
orchestrating session would leave an hour-long validation blocked on a prompt while
the owner is away, where a denial ends cleanly and resumably; bypass is ruled out by
validation driving Docker, the cluster, and the push.

A denial is read from the run's own record, never from the step's message: the
record names the call, while the message generalizes ("Bash is not allowed" for a
chain missing one utility). The harness's reason classifies it: `mode` is a gap in
the table, `rule` met a deny rule — a forbidden action — and `subcommandResults`
refused a shell command by one of its parts without saying which way, so the
command's parts are matched against the step's deny rules. A step that cannot go on without a
denied call stops naming it; one that can goes on, and every denial is recorded on
its outcome either way. After a `mode` denial, the same work done by a tool the
step's rules allow for it — the Edit tool for a shell write — is the rules being
used, not a workaround, and the orchestrating session reads it as a gap; after a
deny-rule denial, no other tool may do the work. A gap is answered with the
narrowest rule that matches the call. A deny rule is matched against the command as
typed, so it holds the plain and quoted forms of an option but not a word a shell
assembles from pieces: the deny rules stop a step's mistakes, and its skill stops
the rest.

## A prerequisite is proposed from dev and halts its dependent

A design that cannot proceed without another change shapes that change's
requirements and initial proposal with the owner, and halts. The proposal is written
in a worktree on a new branch from dev and reaches the blocked branch only by
merging dev once it lands, so the blocked branch never holds a copy of its own:
writing it on the blocked branch and cherry-picking it would leave, after dev is
merged back, the unarchived copy beside dev's archived one without a conflict, and
stacking the prerequisite on the blocked branch would put two changes in one pull
request and stop the prerequisite landing alone. One change per branch is the rule
this keeps.

The blocked change then stays `in design`, with the prerequisite in `Depends on`
gating design; `blocked in design` is kept for reasons that are not another change.
Starting the prerequisite's workflow is the owner's, as choosing any other work is.
Once the prerequisite is archived and merged in, the dependency names an archived
change, which the index check rejects; the computation recognizes that state, and on
the owner's word the dependency is dropped and design resumes.

## The owner is interrupted only for judgement

A change stops for the owner at four kinds of moment: the design discussion's
questions; the owner's notes on each implementation round, read through the round
view; the triage discussion — each finding's disposition, and, once every finding is
disposed and before any fix, whether the fixes merit another review round, asked
while the owner is still present; and the interrupts no rule can settle, such as an
environmental remedy validation proposes, a denial that needs a rule, a proposed
return, a stopped step, or a prerequisite to release. Every other transition
advances on conditions the computation checks.

Reviews are not gates. A gate at each review would ask the owner a question whose
answer does not vary, and asking it leaves the owner's window idle while their
attention is elsewhere; a routing question at each review would be the same
interruption under another name. A
review's triage records, under `## Next`, whether the change advances or another
round runs, its first word a fixed token the computation reads alone, since routing
on free text is a model's reading again. A triage with nothing to dispose of advances
without the owner. An implementation or pre-closeout round advances only on a
`passed` validation of its final commit, and after a closeout review a correction
outside `openspec/` and `docs/` is validated before archive cleanup, so a code
correction reaches the merge validated unless the owner waives it. The owner's own look at the pull request before merging is outside
the workflow.

## The orchestrator relays and routes

The orchestrating session starts steps, shows each step's message to the owner as
written, and sends the owner's reply back as written. It reads what routing and
recovery need — the computation and the inputs it names, the workflow log, and the
denials report — and never code, reviews, or change documents to form a view of a
finding or a design question. An orchestrating session that stated its own position
on each finding read again what the step had read, which cost tokens and blurred
whose recommendation the owner was weighing. It runs at medium effort: it needs a
large context for a change's relayed turns, not the effort of judging them.

What only the orchestrating session sees is still reported. Misbehaviour of the
workflow's tooling that shows across steps — an answer delivered to the wrong
session, a denial missing from a line, a table rule several steps trip — it writes
as the change's next numbered record, marked as its own observations, which the
next triage reads like the owner's notes. Defects of that kind were found by the
orchestrating session alone; relaying with no observations would have lost them.

## Models are policy, with no same-vendor fallback

Each row of the step table names its step's models in priority order, each with its
harness and effort, and the wrapper runs the first available; a model is
unavailable when its program is missing, it is not signed in, or it reports a usage
limit. An unset model would inherit the account's default, which ran steps on the
most expensive model without anyone choosing it. Design, triage, implementation, and
closeout run on Opus at high effort, which caught more problems and explained its
decisions better; validation and archive cleanup, which run commands and edit a
row, on Sonnet at medium.

The table refuses a row naming Fable or Astra, which the workflow never chooses, and
a row listing two models of one vendor: an outage or a usage limit takes both down,
so a second model of the same vendor is no fallback. Codex appears only where its
sandbox can hold a step to its limits, which is the review alone, falling back to
Claude when Codex is unavailable: a review on a second model reads the work with
another eye, a review on Claude is better than none, and halting on a missing
reviewer only costs the owner time. A step whose one model is unavailable stops with
the time its limit resets. A network error is retried, never a reason to fall back.
A waiting run resumes only on the model it ran on, since a session cannot move
between harnesses. The owner may name any model for a review run by hand, outside
the policy on purpose; the record says so, and the orchestrating session never does.

## Every run records its cost

Each log line carries the model and effort that ran and what the run cost: for a
Claude run its own dollars, turns, duration, and tokens, and for a Codex review the
tokens it reports. A resumed session's dollar total is its running total, so a run's
dollars are that total less the session's previous one, and are marked partial when
something intervened — a crashed run, or turns the owner took over. A resumed run
also records the gap since its session's last turn and whether it read the prompt
cache. The figures are the harness's list prices, not an invoice.

`make change-cost` totals them by step, by round, and by whether a run opened its
session, missed the cache, or read it, because a discussion's cost lies in its
replays: a warm turn presenting one decision costs cents, a session's opening or a
cache miss rewrites its whole context. The record is what the open questions of
loading less guidance per session and of a longer cache lifetime wait on; the
account's console shows totals, not which step or turn spent them.

## Reviews are files

A review is one Markdown file in the change's `reviews/` directory, and the only
record of its findings. Later reviews and triage read earlier findings and their
dispositions from these files rather than from any session's memory, which is what
lets a pre-closeout review ask a different session whether earlier feedback was
addressed, survive compaction, and run under either harness. A structured copy
beside each review would be a second source that can disagree with it.

A re-review continues its own reviewer on the same harness, so the reviewer weighs a
revision with the context that led to its findings; it still reads the triage from
the records. A reviewer's raw session is kept as a transcript, but no review or
triage step reads one: a transcript carries the session context the file exchange
exists to keep out. The reviewer runs read-only and never writes the record itself;
its answer is published only when it has the review format, so an error or a
truncated answer never becomes history, and a run that published nothing is a
failed run however many earlier records exist.

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
round's base — the commit recorded as the round started, so commits landing between
rounds are not shown as the round's — with the files unchanged, and `make
round-done` returns it. A worktree beside the checkout leaves the commits and
validation untouched but needs a second editor project each round and lacks the
owner's test setup; an editor comparison against a base ref reads as a comparison,
not as the changes being worked. While a view is open, every step that describes or
publishes a commit refuses, and the orchestrating session waits for the owner's
notes, saving them as a numbered record before it closes the view, so a restart
cannot lose them.

## Pushing is guarded, never repaired

Validation pushes the change's own branch, because the pipeline runs against the
pushed branch. An unattended push needs a mechanical definition of that branch, so
the guard refuses a detached `HEAD`, a dirty worktree, `main` or `dev`, and an
upstream of another name, and the push sends exactly `HEAD`, never forced. Each
refused state means something unexpected happened; an agent repairing it would hide
that.

## Phases, triage, and archival

A change moves through design, planning, implementation, and closeout, and a phase
ending in a review is finished only when that review's triage records that the
change advances. Planning starts only after the design review's triage advances it,
so a review that redirects the design never discards a plan; a design question
planning exposes returns the change to design.

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

Archive cleanup follows the closeout review's advancing triage as a step of its own,
with its own entry checks, rather than as the end of triage: it releases the
change's dependents, sets it `archived`, and drafts the merge, and is the point at
which the change lands. Its check that a correction outside `openspec/` and `docs/`
was validated stands even for another change's commit on a shared branch, since the
merge carries every commit on it; the owner may waive it, judging the paths named,
and the waiver is a ledger line.

## The index states what may start

The active-change index is what the next-step computation reads to decide what
starts next, so a row's status names its phase and its state within it (`ready
for`, `in`, `blocked in`), and dependencies on other changes sit in their own column
with the phase each gates. A single word such as `active` cannot carry that
decision; it erases the difference between a change waiting for design and one
waiting for a plan, which separate skills perform.

When a dependency lands, its dependents' designs rest on a codebase it has just
altered, so archive cleanup returns each dependent not yet implementing to design.
That ties reverification to a step that already runs. A dependent already in
implementation, or blocked for its own reason, keeps its status.

Every step that edits the index runs `make check-change-index`. The citation check
cannot see those edits: it is scoped to a change's own documents, and the index's
links are relative directory links. The check covers active changes only; archived
rows are recent history and may be pruned at any time.

## Current limits

- One change is orchestrated at a time, in one checkout: validation takes the whole
  environment, and the wheelhouse, the branch, and the Helm release are shared.
  Working changes in parallel is `parallel-change-workflows`'.
- Leaf steps other than the review run on Claude Code only. Codex can hold only the
  review to its step's limits; running other steps on Codex with the step table's
  guarantees and its record of denials is not built.
- Choosing what to work on next across changes, and starting a prerequisite's
  workflow, stay with the owner.
- The Helm run serves only the scenarios the default charts can: the charts lack the
  pipeline's full topology, which `helm-e2e-pipeline-parity` owns.
- Following a wrapper run from inside the orchestrating session is not built: the
  harness's task panel does not show it, and the owner follows it with
  `make change-watch` in another terminal.
- Review and step transcripts persist only in the untracked `reviews/` directory
  until an export flow exists.
