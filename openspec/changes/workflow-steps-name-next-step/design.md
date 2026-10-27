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
exits than `review` of kind `closeout`, and `triage` of a design review other exits
than `triage` of a closeout review); each node declares its exits, the join it
waits on (the round's triage waits for the owner's reading, the validation, and the
implementation review), the guards on each edge, each guard naming the step
that satisfies it (D4), and its entry guards. The computation interprets the table
in place of the per-phase methods. `make change-graph` renders it as a Mermaid
diagram, and the diagram in `openspec/specs/change-workflow/architecture.md` is
held to that rendering by a test, so the documentation cannot drift from the code.

A guard is of one of two kinds (21 F1):

- An *exit guard* sits on an edge: a condition on a step's chosen exit, such as
  `HEAD` validated before closeout. An owner's direction (D5) checks none (13 F1).
- An *entry guard* sits on a node: a condition without which its step cannot, or
  should not, carry out its work, such as an archive for archive cleanup. It is
  checked on every entry, by a step's exit or by a direction. One that is
  *unwaivable* refuses every entry while unmet; one that is *waivable* takes the
  owner's direction as its override, and on a step's exit is met first by the exit
  guard that remedies it. An entry guard unmet on a step's exit names the owner.

The table states today's routing, which round 1 reproduces exactly (13 F1); the
triages' kinds and the entry guards are round 2's:

| Node | Exits a step names | Join | Guards on the exits, and their remedy |
|---|---|---|---|
| `design` | `review` `design` | — | — |
| `review` `design` | `triage` `design` | — | — |
| `triage` `design` | `plan`; `review` `design`; `design` (a return) | — | `plan`: a dependency gating planning released (owner). A return: the owner's confirmation (owner) |
| `plan` | `round`; `review` `pre-closeout` when the plan adds nothing to implement | — | `round`: a dependency gating implementation released (owner). `review` `pre-closeout`: `HEAD` validated, records exempt (`validate`) |
| `round` / `implement` | `triage` `implementation` | the round's sections checked (`implement`, its next session), the owner's reading (`round-view`), its validation (`validate`), its implementation review (`review` `implementation`) | in a clone, the bootstrap finished (`wait`; failed: owner) |
| `review` `implementation` | `triage` `implementation` | as above | — |
| `validate` | the target it carries: `triage` `implementation` in a round's join, or the exit whose guard it remedies | as above, in a round | the guards of the target, checked again |
| `triage` `implementation` | `round`; `implement` with sections; `review` `pre-closeout` after the last round; `review` `implementation`; `plan` or `design` (a return) | — | `round`, `implement`, `review` `pre-closeout`: the fix commit validated, records exempt (`validate`; failed or inconclusive: owner). `review` `implementation`: a fix committed since the review is read (`round-view`) and validated (`validate`). A return: the owner's confirmation (owner) |
| `review` `pre-closeout` | `triage` `pre-closeout` | — | — |
| `triage` `pre-closeout` | `closeout`; `review` `pre-closeout`; `plan` or `design` (a return) | — | `closeout`: `HEAD` validated, `openspec/` and `docs/` exempt (`validate`; failed or inconclusive: owner). `review` `pre-closeout`: a fix outside `openspec/` and `docs/` validated (`validate`). A return: the owner's confirmation (owner) |
| `closeout` | `review` `closeout` | — | — |
| `review` `closeout` | `triage` `closeout` | — | — |
| `triage` `closeout` | `archive-cleanup`; `review` `closeout` | — | `archive-cleanup`: when a path outside `openspec/` and `docs/` changed since the first closeout review, `HEAD` validated (`validate`; failed or inconclusive: owner) |
| `archive-cleanup` | `done` | — | — |
| `done` | none: the change is done, and no step runs | — | — |

The entry guards:

| Node | Entry guard | Waivable |
|---|---|---|
| `design`, `plan`, `round` / `implement` | the change is not archived | no |
| `review` `pre-closeout` | the latest validation passed for `HEAD`, or for an ancestor it differs from only in records — after a pre-closeout triage, only in paths under `openspec/` and `docs/` | yes: the owner's direction is its override, as `UNVALIDATED=1` is today |
| `review` `closeout`, `triage` `closeout`, `archive-cleanup` | the change is archived | no |
| `triage` of each kind | a review of its kind awaits triage | no |
| `done` | reached only by archive cleanup's exit | no: never directed |
| `validate` | it carries a target that is a node of the table | no |

Closeout has no archive guard, since it is the step that archives.

The computation names `validate` always with a `target` (D4): in a round's join,
the round's triage; as a guard's remedy, the exit it clears; after the owner's
direction to validation, the target the direction names (D5). Validation's entry
guard holds every entry to that rule, a direction's included (30 F2). It does not
check the target's own entry guards: a round's validation starts beside the
implementation review, before the review its target triages is published, so the
target's entry guards are checked on validation's exit, as on every exit, and a
direction's nested target is checked by the log's writer (D5, 36 F1). Validation
names that target as its exit, and the computation checks the target's guards
again, so a passed validation clears the guard and a failed or inconclusive one
names the owner (21 F2). Under orchestration validation takes the target from the
computation's result; an interactive `make validate` reads it by running the
computation. A
triage's join is read from the files as today's; a step that waits on the
owner — a question, a stop, a proposed return — holds its node until answered or
resolved, as now. `done` is the terminal node: archive cleanup names it, and the
computation names it, as `{"step": "done", "reason": "archived"}` as it does today,
so the orchestrating session stops (21 F2).

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
same way: an object `{"step": …}` with `kind` for a review, and for a triage the
kind of review it triages (`{"step": "triage", "kind": "pre-closeout"}`), and
`sections` for implementation, as the computation already prints its results. A
review or a triage without its kind, or with an empty or unknown one, is no node,
and is refused wherever a target is written (21 F3). A return names its
target as a step (`{"step": "plan"}`, `{"step": "design"}`), not as a phase.
`{"step": "done"}` is the terminal node archive cleanup names. A direction to
validation nests the target the validation is for,
`{"step": "validate", "target": {"step": "closeout"}}`, and is refused without one
by validation's entry guard (D1, 30 F2); the computation's own result names
validation the same way.
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
`next` holds today moves into `message`. A step with one exit names it; a review
names its triage, of its kind; validation names the target the computation gave it
(D1); archive cleanup names `done`. A triage's outcome also names the
records it triaged, in `triaged`, which the wrapper requires on a triage run. The
computation routes on the governing review's latest triage outcome — the latest
triage line whose `triaged` names it, or the conversion line that names it (D7). A
triage file with no finished or returned triage or conversion line naming its
review is a triage in progress. A return is confirmed by the
owner's decision that resolves its run, so neither `governing()` nor
`return_confirmed()` reads a file's time; the file-time rules and the `## Gate`
reading are deleted, since a change's records are converted before the new
computation routes on them (D7).

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
a skill's defect or an intervention, and an intervention is the owner's (D5). A
validation naming a target other than the one the computation gave it is such an
exit. An exit whose target's entry guard is not met names the owner too, with the
guard (D1).

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

### D5 — The owner directs any node, past its exit guards, within its entry guards

An intervention is a deliberate, per-change, irregular transition, and the owner's
alone. The owner directs any node of the table with a decision line `by: owner`
whose `next` is a D2 target, with a reason; it may resolve a waiting run. The
computation names it until a later run of that node is logged. No edge from the
change's current node is needed, and no exit guard is checked: an exit guard is a
condition on a step's exit (D1, D4), and a direction the owner made deliberately is
not refused by one. A direction that causes a problem is the owner's to correct, by
another direction (13 F1). The target's entry guards are checked (21 F1): the log's
writer refuses a direction while an unwaivable entry guard of any node it names is
not met — its target, and the target nested in a direction to validation (36 F1) —
naming the guard, since the step could not carry out its work, and a waivable entry
guard takes the direction as its override. The directed step's entry check — its own,
as the pre-closeout review's validation check, or the computation it asks — accepts
the direction in the log as that override; the step sets its own status as it
starts, accepting the change in that state because the log holds the owner's
direction.
A direction to validation names the target it is for, so the owner can have a
validation before a step a direction would otherwise reach unchecked: a passed
validation leads to the target, its entry guards checked, and a failed or
inconclusive one names the owner. No exit guard of an earlier edge applies, since
the owner directed it (30 F2). A directed validation whose target could never be
entered, such as archive cleanup of a change not archived, is refused while the
owner is present rather than run to an exit the archive guard refuses (36 F1).
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

The archive is the boundary no direction crosses. An archived change is not
returned to an earlier phase: design, planning, and implementation refuse it, and
its deltas are already merged into `openspec/specs/`. A change not yet archived is
not directed past it: the closeout review, its triage, and archive cleanup need the
archive, and archive cleanup would otherwise mark `archived` a change whose deltas
were never merged. Both are unwaivable entry guards, so the log's writer refuses
either direction, naming the archive or its absence, and the computation never
names a step that would refuse it. A closeout triage that needs a code correction
stops for the owner, who directs it in that session, as now. A problem found while
closeout runs, before it archives, is a direction like any other.

Rejected:

- *Every guard checked against a direction*, with `waives` naming the guard a
  direction skips (review 13 F1's suggestion): a direction the owner made
  deliberately would be refused by an exit guard, and the owner, not a guard,
  answers for an irregular transition. Only entry guards are checked, and only the
  unwaivable ones refuse (21 F1).
- *Directions unrestricted, each step's entry check making way* (21 F1's first
  alternative): a direction that no step could carry out, such as archive cleanup of
  a change not archived, would be accepted and fail later as a stopped run, rather
  than being refused while the owner is present.
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
`--sections` — and builds the object; a direction to validation adds `--target`,
the step it is for, which `--kind` and `--sections` then qualify (30 F2). `note_orchestrator` checks three things in
place of its special cases: a `next` is the owner's, its target is a node of the
table, and the unwaivable entry guards of every node it names are met, a nested
target's included (36 F1). A direction checks no exit
guard and overrides a waivable entry guard (D5), so a decision line names none.

Rejected: keeping a string `next` and a `kind` field on decision lines alone, two
shapes for one concept.

### D7 — A change's records are converted when it takes the new code

The computation reads only the new format, and never reads an older one as the new
(13 F2). A change worked on another branch — in its own clone, whose orchestrating
session runs that clone's `scripts/` — runs the older tooling until its branch
merges the `dev` that carries this change: converting its records before then
would leave its older computation reading shapes it does not know, and its older
wrapper appending older lines after the conversion. So each change's records are
converted at the one point that is safe for it, when its branch first carries the
new code, and that point is not this change's to choose (21 F4).

Every line the new tooling appends to a workflow log — the wrapper's, `record`'s,
and the decision writer's — carries the log's format marker, `"format": 2`. The
computation detects a change not yet converted by the marker's absence: a log with
a line that lacks it, or numbered records under `reviews/` and no log. It names the
owner with the conversion command for it, rather than routing on either. The rule
needs no knowledge of an older line's shapes, so it catches an older `returned`
outcome, which carries no `next`, a change worked interactively whose records have
no log at all, and a line an older wrapper appends after the conversion. It reads
no triage file's first words, so a new triage awaiting its outcome is not taken for
an older one (13 F2), and a new change has a log from its first recorded run, the
design's (D11), before its first review is published (30 F1).

A committed command, `python3 scripts/run_change_step.py convert <change>`,
converts one change's records in the checkout that holds them, its clone or the
workspace, in three parts:

- The log's lines, in place, each keeping its seq, so every `resolves` and `reads`
  still names its run: a decision line's string `next` and `kind` become the D2
  object, a `returned` outcome's `return_to` gains its target, an outcome's prose
  `next`, which nothing routes on, moves into its `message`, and each line gains
  the format marker.
- One line appended, `step` `convert`, `outcome` `converted`, recording the
  conversion: `triaged` names every review with a triage file, so none reads as a
  triage in progress. It names no exit, and is no step's run: the computation
  routes past it on the last step's exit and the owner's latest direction (36 F2).
- The owner's direction to the node the change stands at, appended after it as a
  D5 decision line `by: owner`, which the log's writer checks as it checks every
  direction. The command proposes the direction, and the owner, whom the
  computation named, confirms it or gives `--next` in its place. It proposes from
  the latest triage file's token as that token leads in its phase today —
  `Advance` and a `## Gate` beginning `Passed` the phase's advancing exit,
  `Another round` the review of the same kind, `Returned` the step a recorded
  confirmation directed. A direction checks no exit guard, so where the edge from
  that triage's node to the proposed node carries an exit guard not met, evaluated
  by the table's own guards, the command proposes the guard's remedy carrying the
  node as its target: `{"step": "validate", "target": {"step": "round"}}` for a
  round's fix commit not yet validated. Where the log holds a step's run after the
  latest triage's, the token no longer states the present: the command proposes
  nothing, names those runs, and requires `--next`. A return not yet confirmed,
  its run rewritten in place, is proposed as the direction to its target that
  resolves that run's seq; the owner declining it writes no direction, and the
  return waits for the owner as any return does.

```json
{"seq": 46, "step": "convert", "outcome": "converted", "format": 2,
 "triaged": ["13-design", "21-design", "30-design", "36-design"],
 "message": "converted the change's records"}
{"seq": 47, "step": "orchestrator", "outcome": "orchestrator", "by": "owner", "format": 2,
 "next": {"step": "review", "kind": "design"},
 "decision": "the change stands at a design review",
 "reason": "36-design's triage chose another round; confirmed at conversion"}
```

Where the change stands is the owner's assertion, made with the owner present, so
it is recorded as the owner's direction and needs no node of the table; the phase
requirement's exception for the owner's directions covers a converted change's
phase-ending triages, which have no triage outcome of their own (36 F2). The
history is not rebuilt as triage lines, one per older triage: an older triage line
names no review, so every older triage would gain an appended line, placed after
the runs its exit already led to, and the computation would name those runs again
(30 F1). The conversion and the direction come last, and state the present.

The command writes the converted log — the rewritten lines, the conversion line,
and the direction — to a temporary file beside the log, checks that the log is
unchanged since it read it, starting over if it is not, and renames the file over
the log; a change with records and no log gains its log the same way. An
interrupted conversion so leaves either the older log, still detected, or the
converted one whole, never marked lines without their conversion line, and a retry
is running the command again (36 F3). A rerun after a line without the marker was
appended — the converting run's own last line, which the wrapper that started it
appends unmarked — converts again: it rewrites what is unmarked and states the
present again, and, a run then following the latest triage, requires `--next`.

The command refuses a change already converted, and a change with a triage in
progress: a triage file with neither `## Next` nor `## Gate`, by the older reading,
which lives only in the command, unless a triage outcome carrying the marker names
its review. It names the review and the two ways to finish it — on the code it
started with, or resumed under the new skill, which records its outcome with
`record` — after which the command is run again (36 F4). A triage file whose
`## Next` begins with other words is a finished triage that today's code brings to
the owner; it counts as triaged, and the owner's direction settles where it leads.

Round 2 runs the command on this change. Cleaned-up changes are history and are
left as they are. With no older reading, `## Next` is free prose, and a triage file
whose outcome is not yet recorded is a triage in progress whatever its first words.

The command and the detection are temporary: a change opened at this change's
closeout removes them once every change not yet cleaned up is converted.
The marker stays, as the log's format for any later change to it. The computation's
routing keeps no older reading meanwhile.

Rejected:

- *A legacy reader for records no triage outcome names* (D7 as first settled): the
  same inputs as a new triage whose outcome is not yet recorded, so it could route a
  new `## Next` as an older token (review 13 F2), and the file-time rules would
  survive with it.
- *A reader of both formats, kept until every change has moved over* (21 F4): no
  conversion, but the older routing — tokens and file times — stays inside the code
  this change rewrites.
- *A one-off conversion of every change, as a task of this change, with no command
  and no check* (D7 as settled by 13 F2): a change on another branch still runs the
  older tooling after the task, so no point exists at which every record is in the
  new format, and a change the task misses would be read as the new format (21 F4).
- *Cutting over when no other change is in flight*: a pause across every active
  change, with nothing to detect one missed.
- *Detection by an older line's shapes* — a string `next`, a decision line's
  `kind` (D7 as settled by 21 F4): misses an older `returned` outcome, which has no
  `next`, and a change with records and no log (30 F1).
- *Each older triage converted in place, its run matched to its review by file
  time* (review 30 F1's suggestion): keeps the history line by line in the new
  vocabulary, but a triage with no logged run, any interactive one, has no position
  in the log at which its exit would not repeat a run that followed it.
- *Appended triage lines, with only the confirmation's link mended*: leaves the
  detection's gaps and the appended exits that repeat the runs after them.
- *`convert` as a node whose exit is the node the change stands at* (D7 as settled
  by 30 F1): no edge declares that exit, so no exit guard is defined on it, and
  where the change stands is the owner's assertion, which D5 already records
  (36 F2).
- *A fixed declared exit for `convert`, then the owner's direction* (review 36 F2's
  suggestion): no node means waiting for the owner's direction, and adding one is
  mechanism for a temporary command.
- *The conversion line as an exit checked against the edge from the latest
  triage's node*: keeps the table's guards without the proposal, but is defined
  only where the change stands at an exit of that triage, and has a step that is
  not a triage write a triage's exit.
- *A completion marker written after the conversion line* (review 36 F3's
  alternative): a second check on every route, for a state the single replacement
  never leaves.

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
  `ready for implementation` and recorded no outcome — the step is still in
  progress: the computation names it, and no step after it, with a `disagreement`
  naming the missing outcome and the `record` command. A plan's outcome is what
  carries its exit and its `rounds`, which no status can supply (21 F5).
- A change not yet converted — a log line without the format marker, or records
  with no log — names the owner with the `convert` command (D7).
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
  decision lines' object `next` and owner-only directions, the triage's `kind`, the
  entry guards and the writer's refusals on them, validation's carried target and
  a direction's nested one, the terminal `done`, the result's `target` and the
  undeclared-exit rule, routing on outcomes, and the `triaged` rule, the file-time
  rules and the older readings deleted, with the log's format marker, the
  `convert` command, and the detection of a change not yet converted (D7),
  run on this change's records, since the computation it lands reads only the new
  format; then every skill's handoff and interactive ending, triage's prose
  `## Next`, the entry checks asking the computation and the pre-closeout review's
  accepting a direction as its override, the orchestrate skill, the contributor guide,
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
- The conversion rewrites the field shapes of a change's log in place, the first
  time the workflow rewrites a record. A change whose branch takes the new code
  stops at the owner until its records are converted, which the owner does by one
  command when the computation names it.
- Where a converted change stands is the owner's direction at conversion, not a
  reconstruction: the command's proposal folds in an unmet exit guard's remedy and
  proposes nothing after a later run, but a wrong direction routes the change
  wrongly, which the owner corrects by another. The older history keeps its own
  lines, readable as they were written.
- The command and the detection outlive this change until every change not yet
  cleaned up has taken the new code; their removal is a later change's.
- A direction may name a node that makes no sense from where the change stands;
  only its unwaivable entry guards and the owner hold it.

## Open Questions

None.
