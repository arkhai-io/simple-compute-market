# The change workflow handbook

The change workflow carries an OpenSpec change from its proposal to a merged pull
request: design, planning, implementation in reviewed rounds, closeout, and the
archive. It exists so that your attention, as the repository's owner, goes only where
your judgement matters — deciding what a change does, and correcting the work where
the guidance fell short — while agents do the transport around it: carrying a review
from one agent to another, running the same validation before every review, resuming
a session that stalled, and choosing which step runs next.

Each step is a skill an agent harness loads, run headless or in an interactive
session. A Python engine, `scripts/change-workflow`, starts each step, records its
outcome in the change's workflow log, and computes which step runs next from the
change's files. One orchestrating session can carry a change through every step,
stopping for you only at a design question, your reading of an implementation round,
a triage's discussion, and anything no rule settles. This handbook tells you how to
operate it. What the workflow does is its contract, the
[`change-workflow` specification](../openspec/specs/change-workflow/spec.md),
organized by its [index](../openspec/specs/change-workflow/index.md), and how it
works and why is its [companion](../openspec/specs/change-workflow/README.md); what
a change's work must contain is the workflow's guidance, under
[`docs/guidance/workflow/`](guidance/workflow/README.md). You should not need either
to run a change.

## Contents

- [Orchestrating a change](#orchestrating-a-change)
  - [Starting a change](#starting-a-change)
  - [What a change asks of you](#what-a-change-asks-of-you)
  - [Reading a round](#reading-a-round)
  - [Triage and default acceptance](#triage-and-default-acceptance)
  - [Interventions](#interventions)
  - [Less common interventions](#less-common-interventions)
- [Parallel changes](#parallel-changes)
- [The steps](#the-steps)
  - [Running a step on its own](#running-a-step-on-its-own)
  - [What each step does](#what-each-step-does)
  - [Review options](#review-options)
- [State](#state)
  - [Where a change's state lives](#where-a-changes-state-lives)
  - [A change's files](#a-changes-files)
  - [The ledger](#the-ledger)
  - [Intervening on the state by hand](#intervening-on-the-state-by-hand)
- [The engine](#the-engine)
- [Customization](#customization)

## Orchestrating a change

### Starting a change

`make orchestrate CHANGE=<change>` opens one Claude Code session that carries the
change through its steps. It runs the step the next-step computation names, each
unattended, shows you each step's message as written, and sends your reply back as
written. It forms no view of its own on a finding or a design question, and writes no
feature work of its own accord.

Started in your workspace, it first creates the change's own clone beside the
workspace, under `<workspace>.changes/<change>/`, when no checkout holds the change's
branch ("Parallel changes", below). Give `FROM=<branch>` to `make change-clone` for a
change landing on a branch other than the one your workspace has checked out, since
the clone records that branch as the one the change lands on. The clone's bootstrap
runs in the background; design and planning go on meanwhile, and implementation and
validation wait for it. A failed bootstrap comes to you naming its log, almost always
for a reason in the environment, and is never retried by itself: `make change-clone
CHANGE=<change>` restarts it.

The orchestrating session keeps no state of its own, so resuming a change is running
`make orchestrate` again. `make change-next CHANGE=<change>` prints the same
computation in plain form: the step, its reason, and, for a run waiting on you, its
`seq` and what it asks.

The session says when it starts a long unattended turn. `make change-watch
CHANGE=<change>` follows each step's progress in another terminal, one line per tool
call; for a change in its own clone, run it in the clone. `make change-cost
CHANGE=<change>` totals the change's unattended runs by step, by round, and by
whether a run opened its session, missed the prompt cache, or read it, at the
harness's list prices; dollars a run could not be told from its session's other turns
are marked partial.

### What a change asks of you

A change runs through the steps below ("The steps" describes each). It stops for you
at these moments, and follows every other transition without asking:

1. **The design discussion.** The design step loads the change's context and puts
   each open decision to you with its options, their trade-offs, and its
   recommendation, one at a time. Your answers settle the design. You settle the
   change's implementation cadence here too: how many sessions implement the work and
   how much each round covers before it is reviewed; a change planned with no cadence
   is asked about once per round.
2. **The design review's triage.** An independent reviewer reads the design; its
   triage discusses each finding with you ("Triage and default acceptance", below).
   Planning then follows without asking you anything.
3. **Each implementation round.** Once a round's sections are committed, validation
   and an implementation review start, and you read the round ("Reading a round",
   below). The round's triage takes the review, the validation, and your notes
   together, makes the fixes you accept, and commits them.
4. **The pre-closeout review's triage**, once every section is implemented. The merge
   of the branch the change lands on follows; it asks you to confirm only another
   pre-closeout review, or closeout without validating the merged `HEAD`.
5. **The closeout review's triage**, after closeout has promoted the change's
   durable knowledge and archived it. Archive cleanup follows: it drafts the merge
   commit message and the pull request description, and copies the change's history
   into your workspace.
6. **The pull request.** Your own review of the pull request, and its merge, are
   outside the workflow. Once it has merged, remove the change's clone ("Parallel
   changes", below).

Between these, it stops for anything no rule can settle: a validation that failed or
was inconclusive, an environmental remedy validation proposes, a denial that needs a
rule, a proposed return to design, planning, or, from closeout, implementation, a
stopped step, or a prerequisite to release. A step that asks ends its turn
with a question; your answer, relayed by the orchestrating session, resumes the same
session. A session can take another turn after it reported; the orchestrating session
shows you each earlier turn's message too.

### Reading a round

You read each implementation round as uncommitted changes in your own workspace,
beside validation and the review, which run in the clone. `make round-view
CHANGE=<change>`, run in the workspace, checks out the change's branch, fast-forwarded
from the clone, and resets it to the round's base, so the round shows as uncommitted
changes in your editor. It refuses a dirty workspace, naming the files, an unattended
run in progress there, another change's open view, and a branch that has diverged
from the clone's or holds a commit of yours triage has not pulled. Run again while the
view is open, it moves the view to the branch's new head over the same base, to follow
triage's fixes, unless you have edits or commits in the view. `make round-done`
returns the branch to the round's head and the workspace to where it was, staying on
the branch when you have uncommitted edits, which it leaves for you. Under
orchestration the orchestrating session opens and closes the view and saves your
notes as the round's record.

A commit you make on the branch during the view — your editor's "commit all"
included — is carried onto the round's head when the view closes, each holding
exactly the paths it changed, with its author and message; `make round-done` prints
each beside its replacement, and drops one that holds nothing beyond the round. Where
the round also changed a path, your commit must hold every change the round made to
it: `make round-done` refuses, moving nothing, and names the file and the way back —
`git reset --mixed <head>`, then commit again on the round's head. Triage pulls your
commits into the clone, fast-forward only, and presents each as one of your points on
the round.

When a round's triage names another implementation review over a fix it committed,
read the fix the same way before that repeat pass is triaged: `make round-view
CHANGE=<change> BASE=<commit>`, over the commit that triage's review read, which
`make change-next` names as `base`.

### Triage and default acceptance

Every review is triaged with you. The triaging agent checks each finding against the
files, states whether it agrees and why, and proposes what to do. A review finding
that meets every condition of the default rule is accepted by default rather than put
to you on its own: it is not blocking, the agent agrees and proposes one edit or fix,
no alternative is laid out and the agent names nothing that would change its
recommendation, and the fix touches no interface or representation, migration or
compatibility path, the change's scope, or the validation environment. Every other finding — and every point of
your own notes on a round — is discussed with you, one per message, and disposed of
only by your word. The default acceptances reach you in one table with the triage's
last question, or in its final report when it asks nothing:

```markdown
#### Accepted by default

| Finding | Severity | The finding | Outcome |
|---|---|---|---|
| 04 F5 | should | design.md cites a companion heading that was renamed | edit: cite `#current-limits` |
```

A correction in reply to that question is an ordinary disposition, made before any
fix. Advancing is the default exit: a triage recommending it takes it without asking
and reports it beside the table, while a recommendation of another review round is
argued and asked. A correction after the fixes revisits the finished triage
("Revisiting a default acceptance", below).

A review run elsewhere — in a browser session, by another tool — is pasted into
triage, which saves it verbatim as the change's next record, `NN-<kind>-external.md`,
and triages it with any other review of its kind.

### Interventions

These are the interventions a change normally needs. Tell the orchestrating session
in your own words; it records each as your decision in the change's workflow log.

**Waivers.** A step that meets a guard you may waive recommends a waiver only when a
written criterion holds, naming the criterion and its evidence; with none holding it
recommends none. The criteria: commits that differ from validated ones only in paths
no part of validation exercises; a failure already diagnosed as environmental in an
earlier validation record; a review and a validation of commits differing only in
records or documentation; a decision after a return to design confined to one
requirement's wording or a choice the design review weighed. Only you waive, and a
waiver a step recommended is a ledger line whether you take it or not. The merge
before closeout judges whether its own validation may be waived and asks you to
confirm.

Any part of validation may be waived, by you alone: a waived part is an omission of
evidence, recorded as `waived` and counted in no result. A waiver for later
validations is your decision in the change's workflow log, naming the parts and the
condition; under orchestration the orchestrating session records it, and otherwise
you do:

```text
scripts/change-workflow note <change> orchestrator --by owner --decision "waive the deployment part of validation for the rest of this change, while nothing it touches affects the services it deploys" --reason "<your words>"
```

Validation runs a waived part anyway, saying the waiver lapsed, when the commits since
the last validation that ran it include a merge or the condition no longer holds.

**Directing a change.** You can send a change to any step outside the exits its
steps take — another review, a validation before a step, a step past a guard that is
not met, a confirmed return. The orchestrating session records your direction:

```text
scripts/change-workflow note <change> orchestrator --by owner --next validate --target closeout --decision "validate HEAD before closeout" --reason "<why, and what it skips>"
```

`--next` names the step, `--kind` a review's kind or the kind of review a triage
triages, `--sections` sections out of the plan's order, and `--target` what a
validation is for; `--resolves` names a run the direction settles, such as a return
it confirms. The computation names the directed step until a run of it is logged. A
direction checks no guard on the exit it replaces, so give the reason what it skips;
it is refused where its target cannot be entered at all, such as design of an
archived change.

**Interrupting a running step.** The orchestrating session stays free while a step
runs, so you can reach it mid-step; on your word it stops the run:

```text
scripts/change-workflow stop <change> [--step <step>]
```

Name the step when validation and a review run side by side. A stop commits nothing,
and the session records your interrupt as your decision:

```text
scripts/change-workflow note <change> orchestrator --by owner --decision "interrupt <step>" --reason "<your words>"
```

Then say how to recover it: resumed with your words, rerun, or resolved with
`--resolves` and the change directed elsewhere.

**Taking a step over.** Between turns you can take a step over with `claude --resume
<session>`, the session id on its log line, run in the checkout the step ran in —
for a change in its own clone, `cd <clone> && claude --resume <session>` — since a
session is keyed by its checkout's path. Hand back when done, and never resume a
session while the orchestrating session does; it reads the change's files again once
you hand back. When you closed an interactive step before it recorded, tell the
orchestrating session: it starts nothing for that step and gives you the command to
resume or record it, which you run.

**Revisiting a default acceptance.** You can revisit a finding a triage accepted by
default, or the advancing exit it took. Before its fixes, answer the triage's last
question with your disposition. After the triage finished, the orchestrating session,
on your word:

1. stops the step started after the triage, if one is running;
2. records your direction naming the triage's run:

   ```text
   scripts/change-workflow note <change> orchestrator --by owner --resumes <triage-seq> --decision "revisits 04 F5" --reason "<your words>"
   ```

3. resumes that triage with your words, `scripts/change-workflow resume <change>
   --seq <triage-seq> --answer "<your words>"`: the triage amends its fix in a new
   commit, logs the revisit in the ledger, and names its exit again;
4. then resolves the stopped step with `--resolves`. Resolved before the resume, the
   computation would name the first triage's exit again until the resumed triage
   ends.

The direction takes no `--next`, since the resumed triage names the exit, and one
resume spends it. Once archive cleanup has reached `done`, a revisit belongs on the
pull request.

**Granting a rule for one run.** A step that was denied a call it needed stops, and
the orchestrating session reads the run's denials (`scripts/change-workflow denials
<change> <seq>`) and proposes the narrowest rule for the gap. A rule you grant reaches
one run and is never added to the step table. A fresh run takes it through its
target, several rules separated by `;`:

```text
make validate CHANGE=<change> UNATTENDED=1 ALLOW='Bash(gh run download *);Bash(gh run view *)'
```

A resumed run takes it as `--allow` on `scripts/change-workflow resume`. A grant
commits nothing, so it recovers a stop met between a round's sections being committed
and its triage, when no table edit may be committed. A deny rule is never granted.

**Merging the landing branch at other times.** On your word, the orchestrating
session merges the landing branch into the change's branch between steps — never
while a round view is open, nor between a round's sections being committed and that
round's triage. It resolves conflicts in the change index, change documents, the step
table, and skills itself, and brings a conflict in code to you. One you leave to
implementation goes, once your decision is recorded, to an implementation run with no
sections:

```text
make implement CHANGE=<change> UNATTENDED=1 ARGUMENTS='resolve the merge conflicts in <files>'
```

While the merge is in progress, `make change-next`, run in the checkout holding it,
names you.

### Less common interventions

**A stopped step and its commits.** Each step that writes tracked work commits and
pushes it through the guarded push; validation and review commit nothing. A stopped
run leaves its work uncommitted for its resume, or, on your word, for the
orchestrating session to commit to a separate work-in-progress branch. Work left
uncommitted after a step finished is that step's defect, which the orchestrating
session brings to you.

**The merge after the archive.** When the landing branch has moved by archive
cleanup, cleanup's first exit names the merge after the archive, which runs without
asking; after the pull request opens, it runs only on your word. It keeps the change
archived and judges for itself whether its resolutions need a merge review. It never
returns the change to an earlier phase: where both sides cannot hold, it asks you,
leaving the merge in progress, and you resolve it as you direct, land the change and
follow up in a new change, or take it off the workflow. To merge the landing branch
again once archive cleanup has reached `done`, tell the orchestrating session, which
records:

```text
scripts/change-workflow note <change> orchestrator --by owner --next late-merge --decision "merge the landing branch after the archive" --reason "<your words>"
```

Restore a row you pruned from the change index, as archive cleanup left it, before
you direct the merge. Waiving that merge's validation is your direction to the exit
the merge named, recorded with the merge's run:

```text
scripts/change-workflow note <change> orchestrator --by owner --resolves <merge-seq> --next review --kind merge --decision "the merge review without validating the merged HEAD" --reason "<your words>"
```

with `--next archive-cleanup` and no `--kind` when the merge named archive cleanup,
or when you skip both, saying so in the reason.

**Continuing an implementation session.** An implementation run starts a fresh
session unless you send the work to an earlier one: the next section to a session
small enough to carry it, or a fix to the session that made the edits. The
orchestrating session does so only on your word, naming the session from its run's
log line:

```text
make implement CHANGE=<change> UNATTENDED=1 SECTIONS=8B SESSION_ID=<session>
```

**A change worked in the workspace.** A change can still be worked in your workspace
with no clone, its branch checked out there. Its round view resets that branch in
place, so you read the round before validation and the review start, and while the
view is open those steps refuse to start; close it with `make round-done`. The view is
not refreshed.

**Moving a change already under way into a clone.** A change whose records are in the
workspace is not cloned automatically, since a clone copies only what Git tracks; the
orchestrating session brings it to you with two routes: check out its branch in the
workspace and go on there, or move it into a clone by hand:

1. Settle any run waiting on an answer, in the workspace, since its session is keyed
   to the workspace's path.
2. Merge the branch the change lands on into the change's branch, so its tooling
   knows clones.
3. Run `make change-clone CHANGE=<change>` in the workspace.
4. Copy the change's `reviews/`, and the validation evidence its records name, to the
   same paths in the clone; check with `diff -r` that the copies are identical, then
   remove the workspace's.

**Converting a change's records.** A change whose records predate the log's current
format is brought to you with the conversion:

```text
scripts/change-workflow convert <change>
```

Run it between steps, never while one runs. Alone, it writes nothing: it shows the
direction it proposes and every review its conversion line will name, flagging each
no recorded triage outcome names. `--confirm` writes it, attesting that each flagged
triage finished; `--next`, with `--kind`, `--sections`, and `--target` as `note`
takes them, gives your direction in the proposal's place; `--confirm --decline`
declines a pending return it proposes to confirm. If you will not attest a flagged
triage, write nothing: let its own session finish and record its outcome, then run
the command again.

## Parallel changes

Each change can be worked in its own clone of your workspace, so several changes run
at once without moving each other's branch. A clone lives beside the workspace, one
per change under `<workspace>.changes/<change>/`, and holds the change's branch, its
records, its built environments, its validation evidence, and its step sessions. Start
each change with `make orchestrate CHANGE=<change>` in its own terminal; each
orchestrating session drives its steps in its own clone, `make -C <clone> <step>
CHANGE=<change> UNATTENDED=1`, so each change's log, transcripts, and sessions are its
clone's. Your workspace meets a change's workflow only when you read one of its rounds.

![Where a change's state lives](../openspec/specs/change-workflow/diagrams/change-workflow-state.svg)

Where parallel changes still meet:

- **Your workspace holds one round view at a time.** A second change's `make
  round-view` refuses while another change's view is open; close the first with `make
  round-done`. Each change's triage waits on your reading of its round, so rounds
  queue on you.
- **Your attention.** Every change stops for its own design questions, round readings,
  and triage discussions. Several changes reaching those moments at once wait for you
  in turn.
- **Deployed validation.** Where validation deploys the change's services, the
  repository can give each change resources of its own — a namespace, image tags —
  while the machines they run on are shared, so parallel validations run slower, never
  wrong, where the repository checks capacity.
- **Shared tools and accounts.** Build and package caches are shared, each tool
  locking its own. CI runners, the Git remote, and the harnesses' accounts are shared;
  a usage limit stops every change's runs at once.
- **The change index and the landing branch.** Each branch edits its own row of the
  change index, and adjacent rows may conflict at a merge, resolved there. Every merge
  of the landing branch into a change brings in whatever the other changes landed.

Which resources are per change, shared, or checked depends on what the repository
builds and deploys; the repository's own workflow guidance lists them.

**Removing a clone.** A change's records and evidence are untracked, so no merge
carries them out of its clone. Archive cleanup, as its last act, copies them into your
workspace, so your workspace holds the history of every cleaned-up change, and
`scripts/change-workflow find --records <change>` finds it. Once the change has
merged, remove its clone with `make change-clone-remove CHANGE=<change>` in your
workspace, giving `BASE=<branch>` when the clone recorded no landing branch. It
refuses while a run or the bootstrap is in progress in the clone; otherwise it copies
the history again, then deletes the clone only when that history is all in your
workspace, the branch is merged into its landing branch on its upstream's remote — a
squash or rebase merge counts when merging the branch again would change nothing —
and the clone holds no unpushed commit, no uncommitted change, and no stash. Otherwise
it names each problem and deletes nothing. Archive cleanup never removes the clone,
since the pull request may need another round.

`make change-clone CHANGE=<change> [BRANCH=feat/<change>]` creates a clone by hand.
It is safe to run again: it finishes a clone left incomplete, restarts a failed
bootstrap, and refuses, deleting nothing, a directory that is not a clone of the
workspace, has another branch checked out, or has uncommitted changes.

## The steps

![The workflow's steps and the exits between them](../openspec/specs/change-workflow/diagrams/change-workflow-graph.svg)

The graph above is the workflow's: each box a step, with what must hold to enter it;
each edge an exit a step may take, labelled with when it is taken and what must hold
first; the round's join a hexagon. A step that finishes names the exit it takes, and
the engine checks it against the graph. Where something must hold before an exit is
taken — a commit validated, say — and does not, the engine names the step that makes
it hold, such as validation; where no step can, as after a failed validation, it names
you.

### Running a step on its own

Each step is a skill. Start it by hand with its target, or let the orchestrating
session start each in turn. Start each in a fresh session, so it reads the change's
files rather than an earlier session's memory, unless you continue an implementation
session on purpose.

| Step | Skill | Start it with |
|---|---|---|
| Design | `change-design` | `make design CHANGE=<change>` |
| Design review | `change-review` | `make review CHANGE=<change> KIND=design`, or `make design-review CHANGE=<change>` |
| Planning | `change-plan` | `make plan CHANGE=<change>`, once the design review's triage advances the change |
| Implementation | `change-implement` | `make implement CHANGE=<change> [SECTION=<n> \| SECTIONS=<n-m>]` |
| Implementation review | `change-review` | `make review CHANGE=<change> KIND=implementation` |
| Validation | `change-validate` | `make validate CHANGE=<change>` |
| Triage | `change-triage` | `make triage CHANGE=<change>` |
| Pre-closeout review | `change-review` | `make review CHANGE=<change> KIND=pre-closeout` |
| Merge | `change-merge` | `make merge CHANGE=<change> [FROM=<branch>]` |
| Closeout | `change-closeout` | `make closeout CHANGE=<change>` |
| Closeout review | `change-review` | `make review CHANGE=<change> KIND=closeout` |
| Merge review | `change-review` | `make review CHANGE=<change> KIND=merge`, when the merge after the archive names it |
| Archive cleanup | `change-archive-cleanup` | `make archive-cleanup CHANGE=<change>` |
| Orchestration | `change-orchestrate` | `make orchestrate CHANGE=<change>` |

Every step but the review opens an interactive Claude Code session. Add
`UNATTENDED=1` to run it headless instead, held to its step's permissions and run on
its step's models; it ends with an outcome logged to the change's workflow log. `make
plan` unattended resumes the design step's session; add `FRESH=1` for a fresh one. The
review always runs unattended, since an interactive review would record nothing.

A step you run interactively records its own outcome as its last act:

```text
scripts/change-workflow record <change> <step> --outcome '<the outcome, as JSON>'
```

It reads the session's id from `CLAUDE_CODE_SESSION_ID` (`printenv
CLAUDE_CODE_SESSION_ID` shows it), or takes `--session <id>`. If you close an
interactive session before it records, the next-step computation names its step
again: resume that session, or record its outcome yourself, naming the closed session
with `--session`.

A step that finds the change in the wrong state refuses and says why. Steps that
commit push each commit through the guarded push; a pushed branch starts nothing.

### What each step does

**Design** (`change-design`) holds the design discussion with you: it loads the
change's context, puts each open decision to you with its options, trade-offs, and
recommendation, and records the settled design in the change's proposal, design, and
specification deltas. It refuses an archived change. It exits to the design review.

**Reviews** (`change-review`) are read by an independent reviewer, read-only, on the
configuration's review models, which publishes one record of findings, each with a
lens, a basis, a severity, its evidence, and its alternatives. There are five kinds:
the design review, after design; the implementation review of each round; the
pre-closeout review, of the whole implementation; the closeout review, of the archived
change; and the merge review, of a merge after the archive. Each exits to its triage.
The pre-closeout review enters only once the latest validation passed for `HEAD`, or
for an ancestor it differs from only in records, or, after a pre-closeout triage, only
in inert paths, unless you override it; the closeout and merge reviews enter only an
archived change.

**Triage** (`change-triage`) takes a review — with an implementation round, its
validation and your notes — once one of its kind awaits triage, and discusses it with
you ("Triage and default acceptance", above). It records each disposition and the
ledger's lines, carries out what you accepted, and commits it; an implementation
round's triage fixes code as well as documents. Its exits depend on the review it
triages:

| Triage of | Advancing | Another round | A return |
|---|---|---|---|
| a design review | planning, once no unreleased dependency gates it | another design review | design, once you confirm it |
| an implementation round | the plan's next round, or the pre-closeout review after the last, once the fix commit is validated | another implementation review of the fix, once it is validated; you read the fix before that review's triage | planning or design, once you confirm it |
| a pre-closeout review | the merge | another pre-closeout review, once a fix outside the inert paths is validated | planning or design, once you confirm it |
| a closeout review | archive cleanup, once a correction outside the inert paths is validated | another closeout review | none: an archived change has no earlier phase |
| a merge review | archive cleanup, once a fix outside the inert paths is validated | another merge review, likewise | none |

**Planning** (`change-plan`) writes the change's task list, `tasks.md`: sections that
are coherent, verifiable slices, ordered by the design's cadence into rounds, ending
with the closeout task. It asks you nothing. It refuses an archived change. It exits to
the first round, held while a dependency gating implementation is unreleased, or, when
there is nothing to implement, to the pre-closeout review once `HEAD` is validated.

**Implementation** (`change-implement`) implements the sections of one round, each in
the session the cadence gives it: it loads the guidance and the change, implements and
verifies each section, checks its diff for compliance in a fresh context, records a
handoff in the task notes, and commits and pushes each section on its own. It refuses
an archived change, and in a clone waits for the bootstrap. The round's triage then
waits for four things: the round's sections checked, your reading of the round, its
validation, and its implementation review.

**Validation** (`change-validate`) validates the commit at `HEAD`: it pushes it,
runs each part of validation the repository configures — its own checks and suites,
and, as the repository provides them, a deployment and an end-to-end pipeline —
skipping any part you waived, diagnoses every failure from its logs, and writes the
change's next validation record. It commits nothing. It always runs for a target, the
step it validates for: a passed validation clears the way to it, a failed or
inconclusive one names you, except that a failed validation of a merged `HEAD` goes
back to the merge, which repairs what it found.

**The merge** (`change-merge`) brings the branch the change lands on into the
change's branch once the pre-closeout triage advances it: it resolves every conflict,
reconciles the change's own code with what that branch renamed or removed, runs the
suites, and concludes and pushes the merge. It refuses an archived change. It judges
whether its resolutions merit another pre-closeout review: if not, it exits to
closeout once the merged `HEAD` is validated and no dependency gates closeout; if so,
it asks you to confirm that review. A return it proposes waits for your confirmation.
`make merge` merges `FROM=<branch>` when you give one, and otherwise the branch the
last finished merge recorded, else the one the change's clone recorded; a change with
none, such as one worked in your workspace with no clone and no merge yet, needs
`FROM`.

**Closeout** (`change-closeout`) works through the closeout task's parts in order,
the workflow's and the repository's own, promotes the change's durable knowledge into
the permanent documents, checks their citations, archives the change last so its
specification deltas merge into the specifications, and commits. It changes only the
repository's inert paths, changes' records, and the archive's own writes — the
change's documents and their move into the archive, its index row, and the merged
specifications; a part that would change anything else sends the change back to
implementation. It exits to the closeout review.

**Archive cleanup** (`change-archive-cleanup`) fetches and records the branch the
change lands on, releases the changes that depend on it, sets its index row to
`archived`, commits, drafts the merge commit message and the pull request description,
runs the cleanup of validation's parts, pushes, and copies the change's history into
your workspace. It enters only an archived change. It exits to done, unless the
landing branch moved while the change was closed out, when it exits to the merge after
the archive.

**The merge after the archive** runs the merge's skill on an archived change whose
archive cleanup has run, its index row still `archived`. It exits to archive cleanup
again, or to a merge review when its resolutions need one, each once the merged `HEAD`
is validated.

**Orchestration** (`change-orchestrate`) is the session that runs the others
("Orchestrating a change", above).

### Review options

`make review CHANGE=<change> KIND=<kind>` runs the reviewer on the configuration's
review models, in their order, and publishes its answer only once it has the review
format. A review continues the previous reviewer's session of the same kind on the
same harness; `FRESH=1` starts a new one. For one run you may also give:

- `REVIEW_BASE=<branch>`, the branch the diff is taken against, by default the one
  the change's clone recorded as its landing branch; a review other than the design's
  refuses with neither.
- `REVIEW_MODEL=<model>` and `REVIEW_EFFORT=<effort>`, your choice of reviewer outside
  the models' policy: a `claude-` model runs on Claude and any other on Codex, with no
  fallback, and the run is marked as an override. The orchestrating session never sets
  them.
- `UNVALIDATED=1`, for a pre-closeout review, which otherwise refuses until the latest
  validation passed and names `HEAD` or an ancestor its entry accepts ("What each step
  does", above). Your direction to the pre-closeout review overrides it too.

## State

### Where a change's state lives

A change's state is spread over four places, each holding what the others cannot (the
diagram under "Parallel changes" draws them):

- **The checkout the change is worked in** — its own clone, or your workspace for a
  change worked in place — holds its branch, its tracked files, and its untracked
  records under `reviews/`, with the validation evidence and the round's base.
- **Your workspace** holds the round view you read, and, once archive cleanup has
  copied it, the history of every cleaned-up change.
- **The branch's remote** holds what the guarded push sent, which the pipeline and the
  pull request read.
- **The harness** keeps each session's own transcript on the machine that ran it,
  which a resume reads; the workflow's records name each session by its id.

### A change's files

A change lives in `openspec/changes/<change>/` until closeout archives it into
`openspec/changes/archive/`, under a dated name; `scripts/change-workflow find
<change>` prints where it is. Tracked, and so in the pull request:

- `proposal.md`, `design.md`, and `tasks.md`: what the change does and why, its
  settled decisions, and its plan with each task's notes and evidence;
- `specs/`: its specification deltas, merged into `openspec/specs/` at the archive;
- `interventions.jsonl`: the ledger of your corrections ("The ledger", below).

Untracked, under `reviews/`, numbered in the order they were produced:

- `NN-<kind>.md`: each review, validation record (`NN-validation.md`), your notes on a
  round (`NN-implementation-owner.md`), and the orchestrating session's observations
  (`NN-orchestrator.md`);
- `NN-<kind>.triage.md`: each record's triage, with its dispositions and, for a
  review, the exit it chose;
- `workflow.jsonl`: the change's workflow log, one line per step run, interactive
  run's outcome, the orchestrating session's notes, and your decisions;
  `scripts/change-workflow log <change>` prints it;
- `transcripts/`: each run's transcript and progress file.

The change's row in the [change index](../openspec/changes/README.md) gives its
status and what it waits on.

### The ledger

`interventions.jsonl`, beside the change's other files and tracked, records each time
you corrected course: decided otherwise than the agent proposed, or added context or a
condition that changes the work. A disposition that accepts the agent's proposal is
recorded only in the triage file, except a recommended waiver, which is a line whether
you take it or not. A revisit of a default acceptance is marked as one. Read together,
a change's ledgers show where the guidance or the skills fell short, which is what a
guidance review reads them for.

### Intervening on the state by hand

Change the state between steps, never while one runs. The engine is the workflow log's
only writer: record a decision, a direction, or an interrupt with
`scripts/change-workflow note`, as "Interventions" shows, rather than editing the log.
The next-step computation reads the change's files and its log, so a triage file no
recorded outcome names reads as a triage in progress, whatever it says, and a step
closed before it recorded is named again until it records. A change's records leave
its clone only by archive cleanup's copy, or by hand, as "Moving a change already
under way into a clone" does.

## The engine

The workflow is not only skills. A Python engine, on the standard library alone, runs
them: one command, `scripts/change-workflow`, whose subcommands dispatch to the package
beside it, `scripts/change_workflow/`. Everything the engine does is reached through
that command; the make targets are thin calls of it, a convenience outside its public
surface.

![The engine's parts](../openspec/specs/change-workflow/diagrams/change-workflow-engine-parts.svg)

The engine's parts, by what they do:

- **The command** parses a subcommand and hands it to the module that does the work.
- **The repository's configuration** is read, and checked whole, from
  `.agents/workflow.toml`; the hooks module runs the repository's commands at each
  point of a step's work, and validation's parts ("Customization", below).
- **Starting a step**: the wrapper runs an unattended step. It reads the step table
  for the step's skill and permissions, chooses the first available of the step's
  models, starts the harness — Claude Code or Codex — headless, reads its event stream
  into a transcript, a progress file, and the run's denials, checks the outcome the run
  ends with, and measures what it cost. The review runs read-only and publishes its
  answer as the change's next record.
- **The log** module is the workflow log's only writer.
- **Reading a change** finds a change by name, active or archived, and reads its
  numbered records, the change index, and its task list.
- **Routing**: the graph is one table in code, and the next-step computation reads a
  change's files and log and names the step that runs next by it. Because routing is
  code, it is the same each time, and `make change-next` shows you exactly what the
  orchestrating session will run.
- **A change's places**: creating, reading, and removing a change's clone, copying its
  history into your workspace, and the round view.
- **Guards and support**: the guarded push, which pushes only the change's own branch,
  and never a protected one; `wait`, which lets an unattended step wait for a
  background command; the check that every skill loads from its one source; the
  post-compaction hook; `watch`; and the cost report.

One step's run, from its start to its logged outcome, with the orchestrating
session's relay beside it:

![One step's run, from its start to its logged outcome](../openspec/specs/change-workflow/diagrams/change-workflow-step-run.svg)

A step starts through `scripts/change-workflow start`, which checks the change and
opens its log. Unattended, the wrapper starts the harness and, when the run ends,
appends one line to the log with the run's session, model, cost, and denials. A run
that ends with a question waits; your answer resumes the same session through
`scripts/change-workflow resume`. The command's subcommands, and which another party
may rely on, are the companion's
[The command and its tiers](../openspec/specs/change-workflow/README.md#the-command-and-its-tiers).

## Customization

A repository adopts and tunes the workflow in a few files:

- **`.agents/workflow.toml`**, the repository's configuration: the protected branches
  the guarded push refuses; the inert paths, a change to which runs only the light
  pre-commit checks and, after the pre-closeout review, needs no new validation; the
  repository's commands as hooks on the workflow's moments (after a step's last
  functional change, before every commit, before a commit with a functional change,
  before the archive, before a push, as a clone is made); the OpenSpec command;
  validation's parts, each with its commands, whether it is owed, and its cleanup; the
  documents every step and each step reads as it starts; the models each step and the
  orchestrating session run on, each an ordered list of a harness, a model, and an
  effort; and how often a review whose draft fails the format check is sent back. A
  default check is turned off only by naming it with a reason. The engine refuses a
  step's models naming two of one vendor.
- **`.claude/change-steps.toml`**, the step table: each step's skill and its allow and
  deny rules. A rule you grant for one run ("Interventions", above) never enters it.
- **`.agents/skills/`**: each step's skill, one source every harness loads.
- **The repository's guidance**, which every step reads: how the repository fills the
  roles the workflow leaves to it — its validation parts, its checks, its branches —
  and the rules a change's work is held to.

No step edits the configuration or the step table: each changes as a tracked edit you
commit, or the orchestrating session commits on your word in the change's clone. The
skills and the guidance change like any other file, through a change.

The configuration's fields, and why each is one, are the companion's
[A repository's configuration](../openspec/specs/change-workflow/README.md#a-repositorys-configuration).
