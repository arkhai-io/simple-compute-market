## Context

`scripts/change_next_step.py` computes a change's next step from its index row, its
review records and their triage, its task list, its workflow log, and the round
view. The workflow it routes is a directed graph, but nowhere is that graph stated:
it is spread across eight skills' entry checks and handoffs, the per-phase methods
of the computation (`_design`, `_implementation`, `_round`, `_pre_closeout`,
`_closeout`) with fragments in `_STEP_PHASE`, `_PHASE_STEPS`, and `_REVIEW_PHASE`,
and the per-target special cases of `note_orchestrator` (`scripts/change_workflow/log.py`)
and `directed()`.

Routing information enters in two places only. A triage records the owner's
judgement as one of three tokens under its file's `## Next` — `Advance`,
`Another round`, `Returned` — which the computation turns into a step by reading
the phase around it. The owner's decision lines in the workflow log carry `next`
and `kind`, each kind of decision with its own acceptance rule: a confirmed return,
a repeat review (accepted from the orchestrating session too), the waiver of
another design review, and the waiver of archive cleanup's validation. Every new
path costs a token or a special case; `Returned` was added that way by
`parallel-change-workflows`' closeout review 157, F1, where the owner chose the
narrow fix and opened this change for the general one.

Two further facts shape the design. Every outcome already carries a free-text
`next`, required on `finished`, which the orchestrate and validate skills declare
is not a route; `return_to` and `blocked_on` are structured destinations beside
it. And routing on a triage's choice rests on file times: `governing()` compares a
triage file's time with a review's publication, and `return_confirmed()` accepts a
confirmation only after the triage file was last written, because a triage run's
log line does not name the review it triaged.

Not every step can decide what follows it. Validation and the implementation review
run side by side, and neither sees the other's record or whether the owner has
read the round; `parallel-change-workflows`' log shows validation's `next`
repeatedly deferring to the computation. Design, review, closeout, and archive
cleanup each have one successor.

## Goals / Non-Goals

**Goals:**

- State the workflow's graph explicitly — nodes, exits, joins, guards, and each
  guard's remedy — in one place, from which a diagram and the specification are
  drawn.
- Have every step name the exit it takes, as a structured target, and the
  computation check it against the graph rather than infer it.
- Give the owner one deliberate mechanism to redirect a change outside the graph's
  regular exits.

**Non-Goals:**

- Routing does not move into the model: the computation stays code, tested under
  `scripts/tests`, and holds every guard.
- No orchestration of several changes from one session.
- No step's work changes once it is started.
- Returning an archived change to an earlier phase.

## Decisions

### D1 — The workflow graph is an explicit table in code

The graph is one table in code beside the computation: each node is a step
qualified by its review kind where it has one (`review` of kind `design` has other
exits than `review` of kind `closeout`); each node declares its exits, the join it
waits on (the round's triage waits for the owner's reading, the validation, and the
implementation review), and the guards on each edge, each guard naming the step
that satisfies it (D4). The computation interprets the table in place of the
per-phase methods. `make change-graph` renders it as a Mermaid diagram, and the
diagram in `openspec/specs/change-workflow/architecture.md` is held to that
rendering by a test, so the documentation cannot drift from the code.

Guards sit on a step's exits only; an owner's direction (D5) checks none. The table
states today's routing, which round 1 reproduces exactly (13 F1):

| Node | Exits a step names | Join | Guards on the exits, and their remedy |
|---|---|---|---|
| `design` | `review` `design` | — | — |
| `review` `design` | `triage` | — | — |
| `triage` of a design review | `plan`; `review` `design`; `design` (a return) | — | `plan`: a dependency gating planning released (owner). A return: the owner's confirmation (owner) |
| `plan` | `round`; `review` `pre-closeout` when the plan adds nothing to implement | — | `round`: a dependency gating implementation released (owner). `review` `pre-closeout`: `HEAD` validated, records exempt (`validate`) |
| `round` / `implement` | `triage` | the round's sections checked (`implement`, its next session), the owner's reading (`round-view`), its validation (`validate`), its implementation review (`review` `implementation`) | in a clone, the bootstrap finished (`wait`; failed: owner) |
| `validate`, `review` `implementation` | `triage` | as above | — |
| `triage` of an implementation round | `round`; `implement` with sections; `review` `pre-closeout` after the last round; `review` `implementation`; `plan` or `design` (a return) | — | `round`, `implement`, `review` `pre-closeout`: the fix commit validated, records exempt (`validate`; failed or inconclusive: owner). `review` `implementation`: a fix committed since the review is read (`round-view`) and validated (`validate`). A return: the owner's confirmation (owner) |
| `review` `pre-closeout` | `triage` | — | — |
| `triage` of a pre-closeout review | `closeout`; `review` `pre-closeout`; `plan` or `design` (a return) | — | `closeout`: `HEAD` validated, `openspec/` and `docs/` exempt (`validate`; failed or inconclusive: owner). `review` `pre-closeout`: a fix outside `openspec/` and `docs/` validated (`validate`). A return: the owner's confirmation (owner) |
| `closeout` | `review` `closeout` | — | — |
| `review` `closeout` | `triage` | — | — |
| `triage` of a closeout review | `archive-cleanup`; `review` `closeout` | — | `archive-cleanup`: when a path outside `openspec/` and `docs/` changed since the first closeout review, `HEAD` validated (`validate`; failed or inconclusive: owner) |
| `archive-cleanup` | none: the change is done | — | — |

`validate`, named as a guard's remedy, carries the exit it clears as its `target`
(D4). A triage's join is read from the files as today's; a step that waits on the
owner — a question, a stop, a proposed return — holds its node until answered or
resolved, as now.

A durable change to the workflow is an OpenSpec change, so changing the table is a
code change reviewed as one; an intervention in one change's path is the owner's
decision (D5), not an edit of the graph. The formal graph serves diagrams and the
specification, and makes the workflow system easier to lift out of this
repository should that be wanted.

Rejected:

- *The graph as tracked data* (a TOML file of nodes, exits, and named guards,
  interpreted by the computation): changing a path would be a data edit rather than
  code, but a durable change to the workflow is an OpenSpec change either way, and
  the file format, loader, and schema check are cost with little benefit.
- *Inference kept, the graph published as documentation only*: legible, but no
  single place to change a path, and every new path still costs a token or a
  special case.
- *Deferring*: the next path would repeat `Returned`'s cost.

### D2 — A target is an object in the computation's result shape

A step's exit, an owner's direction, and the computation's result name a step the
same way: an object `{"step": …}` with `kind` for a review and `sections` for
implementation, as the computation already prints its results. A return names its
target as a step (`{"step": "plan"}`, `{"step": "design"}`), not as a phase.
`{"step": "round"}` is the plan's next round, so a triage never copies the plan's
mapping; `{"step": "implement", "sections": […]}` names sections out of the plan's
order, and becomes, through the computation, a `round` result for those sections,
recorded as a round line as it starts, so a round line stays the one record of a
round's sections, base commit, and preceding records. A string form such as
`review:pre-closeout` is rendered for diagrams and documents only, never parsed.

The vocabulary is the workflow's own — steps, review kinds, sections — with no
name that only makes sense in this repository.

Rejected:

- *A qualified string* (`review:pre-closeout`, `implement:5,6;7`): every reader
  parses it, the schema checker would need a `pattern` keyword it does not support,
  and section lists repeat the `--sections` mini-syntax.
- *A phase only*: cannot tell another review from advancing within a phase, which
  is the ambiguity `Advance` is deprecated for.

### D3 — The outcome is the record of a step's exit

Every step's outcome carries its exit as the D2 target in `next`; the prose that
`next` holds today moves into `message`. A step with one exit names it; validation
and review name their join, the round's triage. A triage's outcome also names the
records it triaged, in `triaged`, which the wrapper requires on a triage run. The
computation routes on the governing review's latest triage outcome — the latest
triage line whose `triaged` names it. A triage file with no finished or returned
triage line naming its review is a triage in progress. A return is confirmed by the
owner's decision that resolves its run, so neither `governing()` nor
`return_confirmed()` reads a file's time; the file-time rules and the `## Gate`
reading are deleted, since every older record is converted (D7).

`triaged` is a non-empty list of distinct record names in the ledger's `NN-<kind>`
form, the file name without `.md`. Each names a numbered record in the change's
`reviews/` with its triage file beside it, and at least one is a review — design,
implementation, pre-closeout, or closeout, `-external` included; the others may be
the validation, the owner's notes, or the orchestrating session's observations
triaged with it. The wrapper records a triage outcome that breaks the rule as
stopped, naming the reference; `record` refuses it. A review an
earlier outcome named may be named again, and the later outcome governs. Whether
a record belongs to the triage the computation meant is not checked: the writer
cannot know it, and the triage file beside the record is its observable form
(13 F4).

`## Next` stays in the triage file as prose — the target and the owner's words —
for whoever reads the history; nothing routes on it. The plan, closeout, and
archive cleanup entry checks ask the computation and proceed when it names their
step, instead of reading `## Next`.

The files hold a change's state — its index row, records, and task list — and the
log holds the transitions chosen on that state: steps' exits and the owner's
decisions. Each prevails in its own domain.

The outcome's `next` becomes the object; the schema accepts an object `next`, and a
string only while the skills that write it switch within one round.

Rejected:

- *Both, checked against each other* (a machine-read `## Next` and the outcome):
  two statements of one choice with a disagreement rule, and the file-time rules
  remain.
- *The file as the record, in the new vocabulary*: keeps the file-time rules and
  leaves the outcome's structured fields unused for routing.

### D4 — A guard that is not met names its remedy, and the target is kept

Each guard in the table names the step that satisfies it, or the owner where no
step can. When a step's chosen exit is declared and a guard on it is not met, the
computation names the guard's remedy and carries the chosen exit as `target` in
its result; once the guard holds it names the target. A guard no step can satisfy —
a validation of `HEAD` that failed or was inconclusive, an unconfirmed return, a
failed bootstrap — names the owner with the target and what is missing. A named
exit its node does not declare names the owner, with the step's choice and the
node's exits, single-exit nodes included: a step naming an exit it does not have is
a skill's defect or an intervention, and an intervention is the owner's (D5).

The guards are today's: `HEAD` validated, with changes' records exempt, or paths
under `openspec/` and `docs/` from the pre-closeout triage on; a fix committed
since a review; a path outside `openspec/` and `docs/` changed since the first
closeout review; the round's join; the owner's confirmation of a return; the
clone's bootstrap; a dependency released. Guards are evaluated on every computation
from the files, so a target whose guard changed after it was named is routed on
its current state.

```json
{"step": "validate", "target": {"step": "round"},
 "reason": "triage seq 140 chose the plan's next round; it needs a passing validation of HEAD (a1b2c3d), and the latest validation describes 9f8e7d6"}
```

Rejected:

- *Every unmet guard stops for the owner*: every fix commit's validation would
  interrupt the owner, against "the owner is interrupted only for judgement".
- *The step names the whole path*: puts the guards in the model, and a path goes
  stale when a guard's state changes while the step runs.

### D5 — The owner directs any node, and no guard is checked

An intervention is a deliberate, per-change, irregular transition, and the owner's
alone. The owner directs any node of the table with a decision line `by: owner`
whose `next` is a D2 target, with a reason; it may resolve a waiting run. The
computation names it until a later run of that node is logged. No edge from the
change's current node is needed, and no guard is checked: a guard is a condition
on a step's exit (D1, D4), and a direction the owner made deliberately is not
refused by one. A direction that causes a problem is the owner's to correct, by
another direction (13 F1). The directed step's entry check passes, since it asks
the computation, which names it; the step sets its own status as it starts,
accepting the change in that state because the log holds the owner's direction.
The waiver of another design review and the waiver of archive cleanup's validation
are plain directions, whose `reason` says what they skip; archive cleanup, finding
the direction in the log, still writes the waiver's ledger line. Every decision
line carrying `next` is the owner's: the orchestrating session no longer directs a
repeat review on its own, and never records a step's exit on its behalf.

```json
{"seq": 88, "step": "orchestrator", "outcome": "orchestrator", "by": "owner",
 "next": {"step": "design"}, "decision": "back to design from closeout",
 "reason": "closeout part 3 found D4's placement contradicts the spec's ownership rule"}
{"seq": 97, "step": "orchestrator", "outcome": "orchestrator", "by": "owner",
 "next": {"step": "archive-cleanup"},
 "decision": "waive archive cleanup's validation",
 "reason": "the only path outside openspec/ and docs/ is another change's ledger"}
```

An archived change is not returned to an earlier phase: design, planning, and
implementation refuse it, and its deltas are already merged into
`openspec/specs/`. The log's writer refuses a direction of an archived change to
design, planning, or implementation, naming the archive, so the computation never
names a step that would refuse it. A closeout triage that needs a code correction
stops for the owner, who directs it in that session, as now. A problem found while closeout runs,
before it archives, is a direction like any other.

Rejected:

- *A direction checked against its target's entry guards*, guards declared on nodes
  as well as on edges, with `waives` naming the guard a direction skips (review 13
  F1's suggestion): a direction the owner made deliberately would be refused by a
  guard, and the owner, not a guard, answers for an irregular transition.
- *Interventions as declared owner-only edges*: the diagram would show every
  possible intervention, but each new kind would need an OpenSpec change before it
  could be used once, while an intervention is the transition the workflow did not
  plan for.
- *Today's per-kind decision rules*, mapped to the new vocabulary: the special
  cases stay, and a return from closeout to design stays unreachable.
- *An `unarchive` node*, reverting the archive commit: raises questions of its own
  (which commit to revert when later commits touched the same specifications, what
  becomes of the closeout review's records) and is not in this change.

### D6 — Decision lines carry the same target

A decision line's `next` is the D2 object, with `kind` folded into it; `resolves`
and `reads` are unchanged. The CLI keeps its flags — `--next`, `--kind`, and
`--sections` — and builds the object. `note_orchestrator` checks two things in
place of its special cases: a `next` is the owner's, and its target is a node of
the table. A direction checks no guard (D5), so a decision line names none.

Rejected: keeping a string `next` and a `kind` field on decision lines alone, two
shapes for one concept.

### D7 — Records from before this change are migrated

The computation reads only the new format. The records of every change not yet
cleaned up are converted to it as a task of this change, so once the task is done
no record in an older format remains, and there is nothing to tell apart (13 F2).
No migration command is committed, and the computation keeps no reading of, and no
check for, an older format: the conversion is one-off work, done once.

The task converts, for each change not yet cleaned up — archived ones in closeout
included, this change among them — in the checkout that holds its records, its
clone or the workspace:

- each triaged review whose triage file carries a `## Next` token or a `## Gate`
  and that no triage outcome names: a triage line is appended naming it in
  `triaged`, with the target the token leads to in its phase today — `Advance` and a
  `## Gate` beginning `Passed` the phase's advancing exit, `Another round` the
  review of the same kind, and `Returned` a `returned` outcome naming the step its
  confirmation directs, which the owner's existing confirmation resolves by seq;
- the log's older field shapes, in place: a decision line's string `next` and
  `kind` become the D2 object, a `returned` outcome's `return_to` gains its target,
  and an outcome's prose `next`, which nothing routes on, moves into its `message`.

A change with a triage in progress when the task runs is converted once that triage
has finished. Cleaned-up changes are history and are left as they are. With no
older reading, `## Next` is free prose, and a triage file whose outcome is not yet
recorded is a triage in progress whatever its first words.

Rejected:

- *A legacy reader for records no triage outcome names* (D7 as first settled): the
  same inputs as a new triage whose outcome is not yet recorded, so it could route a
  new `## Next` as an older token (review 13 F2), and the file-time rules would
  survive with it.
- *A committed migration command, with a check for unmigrated changes*: the
  conversion happens once, within this change, after which every record is in the
  new format; a command and a check would be kept for records that no longer
  exist.

### D8 — Recovery

- An unattended run that ends without an outcome is recorded `stopped` by the
  wrapper, as now, and the computation names the owner for it.
- An interactive session of any step closed before it recorded its outcome leaves
  that step in progress: when the last exit or direction names a step and no run of
  it is logged, the computation names that step, its reason saying that if no
  session of it is open, an interactive session ended without recording, to be
  resumed or recorded by hand with `record` (D11). Only the owner runs interactive
  sessions and knows whether one is open, so no start or stop marker is recorded
  (13 F3). Where the files have moved on past the log — a plan that set the status
  `ready for implementation` and recorded no outcome — the `disagreement` names the
  missing outcome and the `record` command.
- A status edited by hand: the files hold state and prevail on it; an exit or
  direction that contradicts the status is reported as a `disagreement`, as now.
- A named target whose guard changed is routed on the current state (D4); one its
  node no longer declares, after a merge of `dev` changed the table, names the
  owner.
- A restart in another checkout finds the log with the records, by the clone's
  existing location rules; archive cleanup's history copy carries it.
- A chosen exit or a direction is used up once a later run of its target node is
  logged; a run still in progress has no line, so the computation names its step
  while it runs, and its entry check passes.

### D11 — An interactive run records its own outcome

Each skill gains an interactive ending: its last act runs

```text
python3 scripts/run_change_step.py record <change> <step> --outcome '<the outcome>'
```

which validates the outcome against the schema and appends it with the session,
`HEAD`, and `interactive: true`. Claude Code exports the session's id to every
shell command it starts as `CLAUDE_CODE_SESSION_ID` (found in the installed 2.1.306
and 2.1.311 releases); the variable is not documented, so `record` refuses to
write a line without a session id unless given `--session`, failing loudly if the
harness stops exporting it. `record` refuses inside an unattended run, which the
wrapper marks in its run's environment, so a step's outcome is never written
twice. The step table allows every step `printenv CLAUDE_CODE_SESSION_ID`, and no
broader reading of the environment. An interactive step stays a plain Claude Code
session under the owner's own permissions; the spec's "an interactive run behaves
as it does without the wrapper" holds except that it records its outcome.

Rejected:

- *The wrapper runs interactive sessions too*, recording an outcome file the skill
  writes when the session exits: one writer and a stop recorded for a session
  closed without reporting, at the cost of wrapping every interactive session; with
  the session id available to a command, the skill can record itself.
- *A launcher recording each interactive run's start and termination* (review 13
  F3): it would tell an abandoned session from a running one, but the remedy —
  resume it or record by hand — is the same, the owner already knows whether a
  session is open, and a step started by its slash command never passes through a
  launcher.
- *The owner records every interactive run by hand*: a manual step whose omission
  strands the change.
- *Files for interactive runs*: a machine-read `## Next` again, contradicting D3.

### The implementation cadence

Two rounds:

- **Round 1**, one session: the workflow graph as a table in code, the computation
  interpreting it with today's behaviour exactly — proven by the existing
  `scripts/tests/test_change_next_step.py` passing unchanged — and its diagram,
  `make change-graph`, and the documentation check.
- **Round 2**, two sessions: first the new records and routing on them — the
  schema's object `next` and `triaged`, the wrapper's requirement, `record`, the
  decision lines' object `next` and owner-only directions, the result's `target` and
  the undeclared-exit rule, routing on outcomes, and the `triaged` rule, the
  file-time rules and the older readings deleted, with the conversion of every
  change's records not yet cleaned up (D7), this change's included, since the
  computation it lands reads only the new format; then every skill's handoff and interactive ending, triage's prose `## Next`, the
  entry checks asking the computation, the orchestrate skill, the contributor guide,
  and the step table's `printenv CLAUDE_CODE_SESSION_ID` rule, which the
  orchestrating session makes on the owner's word since no step may edit `.claude/`.

The refactor is the riskiest part and has a ready proof in today's tests, so it is
reviewed and validated before anything changes what routing means. The wrapper
checks each run's outcome against the schema on disk when the run ends, so round
2's own runs are recorded by the schema they change: the schema accepts a string
or an object `next` until the skills write the object, an order planning keeps
within round 2.

## Risks / Trade-offs

- `CLAUDE_CODE_SESSION_ID` is undocumented; a harness release could drop it, and
  `record` then refuses until it is given `--session`.
- An interactive session closed before `record` leaves its step in progress with
  no trace of why; the computation's reason says what to do.
- The conversion rewrites the field shapes of every in-flight change's log in place,
  the first time the workflow rewrites a record; a change in a clone is converted in
  its clone, and one the task misses is read as the new format, which it is not.
- Round 2's first session converts this change's records, and its own outcome is
  then appended by the wrapper that started it, running today's code; planning
  orders round 2 so that line is in the new shape, or is converted, as it orders the
  schema's string-or-object `next`.
- A direction may name a node that makes no sense from where the change stands;
  nothing but the owner holds it.

## Open Questions

None.
