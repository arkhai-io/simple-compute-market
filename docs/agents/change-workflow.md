# The change workflow

How an OpenSpec change moves from design to archive with agent skills: which skill
each step uses and how to start it, how one orchestrating session carries a change
through its steps, what a review leaves behind, and where the owner's corrections
are recorded. The phases, the closeout parts, and the rules each step follows are
in [`openspec/README.md`](../../openspec/README.md); the status a change is in, and
what it waits on, are in its row of the
[change index](../../openspec/changes/README.md). The workflow's contract is the
[`change-workflow` specification](../../openspec/specs/change-workflow/spec.md),
and why it is shaped as it is, its
[architecture companion](../../openspec/specs/change-workflow/architecture.md).

## Skills

Each step is a leaf skill under `.agents/skills/`, loaded by Claude Code from
`.claude/skills/` and by Codex from `.codex/skills/`, both links to the one source
(`make check-agent-skills` fails otherwise). A skill does one step and stops. The
owner starts a step by hand, or lets the orchestrating session start each in turn
(below). Start each in a fresh session unless its row says otherwise, or you send
implementation's work to a session you name ("Continuing an implementation
session", below), so it reads the change's files rather than an earlier session's
memory.

| Step | Skill | Start it with | Writes |
|---|---|---|---|
| Design | `change-design` | `make design CHANGE=<change>` | `design.md`, `proposal.md`, the spec deltas, the index row, one commit once the design is settled |
| Design review | `change-review` | `make review CHANGE=<change> KIND=design` | `reviews/NN-design.md` |
| Planning | `change-plan` | `make plan CHANGE=<change>`, once the design review's triage advances the change | `tasks.md`, ending with the closeout task, one commit |
| Implementation | `change-implement` | `make implement CHANGE=<change> [SECTION=<n> \| SECTIONS=<n-m>]` | each section's code and tests, its task notes, one commit per section |
| Implementation review | `change-review` | `make review CHANGE=<change> KIND=implementation` | `reviews/NN-implementation.md` |
| Validation | `change-validate` | `make validate CHANGE=<change>` | `reviews/NN-validation.md`; pushes `HEAD`, runs the pipeline (`make run-e2e`, `make fetch-e2e-logs`), and dispatches and reads each CI workflow the change's complete sections owe (`make run-ci`, `make validate-ci`) |
| Triage | `change-triage` | `make triage CHANGE=<change>` | `reviews/NN-<kind>.triage.md` ending with `## Next`, the exit it chose in prose; an outcome naming that exit and the records it triaged; `interventions.jsonl`, accepted fixes in one commit, the index row when a phase-closing review's triage advances the change; whatever it edited that no fix commit holds, in one commit of its own |
| Pre-closeout review | `change-review` | `make review CHANGE=<change> KIND=pre-closeout` | `reviews/NN-pre-closeout.md` |
| Merge | `change-merge` | `make merge CHANGE=<change> [FROM=<branch>]`, once the pre-closeout triage advances the change | the branch the change lands on — `dev` unless `FROM` names another — merged into the change's branch, its conflicts resolved and the change's code reconciled with it, in the merge commit or one after it; the index row (`ready for closeout`) when it advances with `HEAD` validated |
| Closeout | `change-closeout` | `make closeout CHANGE=<change>` | permanent documents, the promotion record, the archived change, one commit |
| Closeout review | `change-review` | `make review CHANGE=<change> KIND=closeout` | `reviews/NN-closeout.md` |
| Archive cleanup | `change-archive-cleanup` | `make archive-cleanup CHANGE=<change>` | the index (dependents released, row `archived`), any waiver as a ledger line, one commit, `reviews/pull-request.md`; the capacity figure its latest validation measured (`make record-capacity`), in a commit of its own, or none when nothing was measured; then tears down the change's validation namespace and images (`make -C helm teardown`) and, for a change worked in its own clone, copies its history into your workspace (`make change-history`) |
| Orchestration | `change-orchestrate` | `make orchestrate CHANGE=<change>` | the change's clone and branch, `orchestrator` and `round` lines in the workflow log — your directions among them, on your word — the conversion of a change's records on your word, the owner's notes on a round, the ledger line of a waived design review, workflow commits on your word, its own observations of the tooling |

Every step but the review opens an interactive Claude Code session. With
`UNATTENDED=1` the same target runs the step headless instead, through
`scripts/run_change_step.py`: held to its step's permissions in
`.claude/change-steps.toml`, on its step's models, ending with an outcome appended
to the change's workflow log. `make plan` unattended resumes the design step's
session; `FRESH=1` starts a fresh one. The review always runs unattended.

Every step's outcome names the exit it takes as a target — `{"step": "review",
"kind": "design"}`, `{"step": "round"}`, `{"step": "plan"}` — and a triage's names
the records it triaged. An outcome is checked against
`.agents/change-outcome.schema.json`, and its target against the workflow graph, so
one naming no node is refused. Run interactively, a
step records its own outcome as its last act:

```text
python3 scripts/run_change_step.py record <change> <step> --outcome '<the outcome, as JSON>'
```

It checks the outcome as the wrapper checks an unattended run's, and appends it with
the session's id, which it reads from `CLAUDE_CODE_SESSION_ID` (`printenv
CLAUDE_CODE_SESSION_ID` shows it) or is given with `--session`, `HEAD`, and
`interactive: true`. It refuses without a session id, and inside an unattended run,
whose outcome the wrapper records. An interactive session closed before it records
leaves its step in progress where only its outcome says where the change goes: the
computation names the step again, to be resumed, or its outcome recorded. Where the
files say it — a round's checked sections, a validation's record — the computation
reads them, and only the session's report is lost.

An unattended step runs one command per Bash call, and does a read the permissions
refuse through the Read tool instead. Two shapes are refused by the harness itself,
whatever the step's rules allow, and each costs a denial on the run's line: a
`find` over `/` or `/etc`, and a path that climbs with `..` after a `cd`
(`cd <dir>; cat ../tasks.md`, or `cd ..`). Read such a file with the Read tool, or
name its path from the repository root. A wrapper stopped by SIGTERM logs its run
`stopped`, naming the signal, with the session to resume; one killed by SIGKILL
leaves no line.

Every step that commits — design, planning, implementation, triage, closeout, and
archive cleanup — pushes each commit right after through `make push-branch`, the
guarded push of exactly `HEAD`, the only push a step may make. A pushed branch
starts nothing: validation dispatches the end-to-end pipeline itself.

Validation dispatches CI workflows too, for evidence only a run of one produces.
`make run-ci WORKFLOW=<file>` dispatches a workflow on the current branch and
prints the newest run of it there before the dispatch as `CI_AFTER_RUN`; it
refuses any workflow `scripts/ci_evidence.py` does not list, naming the list, which
holds `tests.yml` and nothing that publishes, and only you extend it. `make
validate-ci WORKFLOW=<file> CI_AFTER_RUN=<id>` is validation's `ci` part: it waits
for the dispatch's run of `HEAD` newer than that one, keeps its job logs under
`.snapshot/validation/<short commit>/ci/`, and classes each failure — a failing test's
ID and exception type from pytest's short summary, or a failing step with its
error lines — against the
same job in the latest completed `dev` run of the workflow whose commit the branch
contains: `inherited` when that run fails it the same way, `new`, or
`uncomparable`.

A change's Helm part runs in its own namespace, `validate-<change>`, on images
tagged for the change (`docs/development/DEPLOYMENT_AND_CONFIG.md`, "Validation
namespaces"). `make validate-parallel CLONES="<clone> <clone>"` checks that
isolation on the development cluster: it runs two clones' Helm parts at the same
moment and reports whether each kept to its own namespace, tags, and scenario pod,
and left the other's release, volumes, and pods untouched, under
`.snapshot/parallel-validation/<time>/`. It deploys two changes' releases, so it is
a check of the tooling run by hand, not part of any change's validation.

The order is the one the phases give: design and its review until the design
review's triage advances the change; planning; then, per implementation round,
implementation, its review beside validation of the same commit, and one triage of
both; a pre-closeout review and its triage; the merge of the branch the change
lands on; closeout; the
closeout review and its triage; archive cleanup. A review is not a gate: its triage names its exit among
those its node declares — the step that advances the change, the plan's next round
after an implementation round; another review of the same kind; or, before
closeout, a return to design or planning — asking the owner which once every
finding is disposed and before any fix; its file's `## Next` records the choice in
prose, and nothing routes on it. Once the owner confirms a return, what it leads to
is implemented and reviewed afresh.

That order is a graph: one table in `scripts/change_workflow/graph.py` declares
each step — a review by its kind, a triage by the kind of review it triages — its
exits, the records a join waits for, the guards on each exit with the step that
satisfies each, and the entry guards without which a step cannot do its work.
The `change-workflow` architecture shows it as a diagram laid out by hand,
`docs/development/diagrams/change-workflow-graph.drawio` and its SVG export, and a
test fails when the source, or the copy of it the export embeds, draws a box or an
edge the table does not, or misses one. A change to the table redraws the source in
draw.io, from what `make change-graph` reports — each box and edge to add, change,
or remove — and exports the SVG again with the source embedded; the SVG is never
edited by hand.
`scripts/change_next_step.py` routes on the exit the last step named, and on your
latest direction, checking each against the table, as the `change-workflow`
specification's "The next step is computed from the files" requires: an unmet
guard names the step that satisfies it, and an exit the table does not allow comes
to you.

A step that finds the change in the wrong state refuses and says why. Design and
implementation take only an active change. Closeout archives the change as its last
step, so every step after it — the closeout review, its triage, validation, archive
cleanup — finds the change under `openspec/changes/archive/` by its name
(`python3 scripts/find_change.py <change>`). `make review KIND=closeout` refuses a
change that is not archived, and `make archive-cleanup` one that is not. Planning,
the merge, closeout, and archive cleanup ask the next-step computation as they
start, and go on only when it names them — archive cleanup also when it names a validation
before it, which it then checks for your waiver.

`make check-change CHANGE=<change>` runs a step's closing checks — comment hygiene,
the agent skills, the change's citations and task list, the change index, and the
pinned strict OpenSpec validation — printing only failures and one pass line. `make
check-tasks CHANGE=<change>` fails when a numbered task sits under another section's
heading; the steps that act on a task list run it first.

Ask the owner questions in prose, never through a multiple-choice selector
(`AGENTS.md`, "Asking the owner").

## Orchestrating a change

`make orchestrate CHANGE=<change>` opens one Claude Code session that carries the
change through its steps: it runs the step `scripts/change_next_step.py` computes,
each unattended through its `make` target, shows each step's message as written,
and sends your reply back as written. It forms no view of a finding or a design
question. It commits nothing while a step runs. It also creates the change's clone
and branch (below), and on your word commits changes to the workflow itself —
skills, the step table — anything else you instruct, and merges of `dev`, in the
change's clone, on its branch, so they take effect for its next step and land with
it; it never writes the change's feature work of its own accord. It stops for you
at the design discussion's questions, your
reading of each implementation round, the triage discussion, and anything no rule
settles — an environmental remedy, a denial that needs a rule, a proposed return, a
stopped step; every other step follows without asking.

**Starting and resuming.** The session keeps no state of its own: on every start
and after compaction it recomputes where the change stands from the files and the
workflow log. Resuming a change is running `make orchestrate` again.
`make change-next CHANGE=<change>` prints the same computation in plain form — the
step, its reason, and for a run waiting on you its `seq` and what it asks.

**Stating the cadence.** The design settles the change's implementation cadence:
how many sessions implement the work and how much each round covers before it is
reviewed, written in terms of the work, such as "one round, one session" or "round
1: the contract changes; round 2: the handlers and the migration". Planning orders
its sections by it and reports the mapping as the `rounds` on its log line; the
orchestrating session records each round as it starts. A change planned with no
cadence is asked about once per round.

**Following a running step.** The session says when it starts a long unattended
turn. `make change-watch CHANGE=<change>` follows each step's progress file in
another terminal — one line per tool call — moving to the next step's as it starts,
and into the archive when closeout moves the change there. Run it from your
workspace: a change worked in its own clone is followed in the clone, where its
steps write.

**Answering and taking over.** A step that asks ends its turn with a question; your
answer, relayed by the orchestrating session, resumes the same session by the
waiting run's `seq`. Between turns you can take a step over with
`claude --resume <session>`, the session id on its log line, run in the checkout
the step ran in, since a session is keyed by its checkout's path; hand back, and
never resume one concurrently. The orchestrating session rereads the files
afterwards. A step you run interactively records its own outcome with `record`;
when you closed one before it recorded, the computation names its step again: tell
the orchestrating session, which then starts nothing for it, and resume the session
or record its outcome yourself, naming the closed session with `--session`. The
orchestrating session gives you the command and never runs it.

**Directing a change.** You can send a change to any node of the graph outside the
exits its steps take — another review, a validation before a step, a step past a
guard that is not met, a confirmed return — by telling the orchestrating session,
which records your direction, `by: owner`:

```text
python3 scripts/run_change_step.py note <change> orchestrator --by owner --next validate --target closeout --decision "validate HEAD before closeout" --reason "<why, and what it skips>"
```

`--next` names the step, `--kind` a review's kind or the kind of review a triage
triages, `--sections` sections out of the plan's order, and `--target` — qualified
by `--kind` and `--sections` in turn — what a validation is for; `--resolves` names
a run the direction settles, such as a return it confirms. The computation names
the directed step until a run of it is logged, and the step sets its own status. A
direction checks no exit guard on its way, so its reason says what it skips; it is
refused, naming the guard, while an unwaivable entry guard of a node it names is
not met — design, planning, or implementation of an archived change, the closeout
review, its triage, or archive cleanup of one not archived, a triage with nothing
awaiting it, a validation naming no target, and `done`, which only archive cleanup
reaches. The waivers of another design review
and of archive cleanup's validation are such directions. The orchestrating session
never directs a step of its own accord, and never records a step's exit for it.

**Converting a change's records.** A change whose workflow log holds a line without
the log's format marker, `"format": 2` — written by the tooling from before steps
named their exits — or which has numbered records and no log, is read as nothing
until it is converted, and the computation brings it to you with the command:

```text
python3 scripts/run_change_step.py convert <change>
```

Run between steps, never while one runs. Alone, it writes nothing: it shows the
direction it proposes to where the change stands, or why it proposes none, and
every review its conversion line will name, flagging each that no recorded triage
outcome names, with the first line of the `## Next` or `## Gate` it read.
`--confirm` writes it, attesting that each flagged triage finished; `--next`, with
`--kind`, `--sections`, and `--target` as `note` takes them, gives the direction in
the proposal's place; `--confirm --decline` declines a pending return it proposes
to confirm. If you will not attest a flagged triage, write nothing: its own session
finishes it and records its outcome, and the command is run again. It refuses a
change already converted, or one with a triage still in progress.

**Maintaining the step table.** `.claude/change-steps.toml` gives each step its
skill, its allow and deny rules, and its models in priority order with their
effort. No step may edit it: a rule or model changes as a tracked edit, which you
commit, or which the orchestrating session commits on your word in the change's
clone.
The orchestrating session reads each run's denials from its log line
(`python3 scripts/run_change_step.py denials <change> <seq>`) and proposes the
narrowest rule for a gap, either granted for one run or as a table edit. A
row never names a Fable or Astra model, nor two models of one vendor. `REVIEW_MODEL`
and `REVIEW_EFFORT` (below) are yours for a review run by hand, not the table's.

**Granting a rule for one run.** A rule you grant reaches one run, fresh or
resumed, and is never added to the table: the run's log line records it as
`granted`, and the step's next run is held to its table again. A fresh run takes
it through its step's target, several rules separated by `;`, each passed to the
script as its own `--allow`:

```text
make validate CHANGE=<change> UNATTENDED=1 ALLOW='Bash(gh run download *);Bash(make check-packaging)'
```

A resumed run takes it as `--allow` on `python3 scripts/run_change_step.py resume`.
Since a grant commits nothing, it recovers a stop met between a round's sections
being committed and its triage, when no table edit may be committed. A deny rule is
never granted.

**Commits.** Each step that writes tracked work — design, planning,
implementation, triage, closeout, archive cleanup — commits it and pushes it with
`make push-branch`; validation and review commit nothing. A step commits partial
work only when it returns the change to an earlier phase: it records why, commits
what it has as work in progress with no task checked, and pushes it. A stopped run
leaves its work uncommitted for its resume, or, on your word, for the orchestrating
session to commit to a separate work-in-progress branch; one stopped by a refusing
guard or a moved `HEAD` commits nothing. Work left uncommitted after a step finished is that
step's defect: the orchestrating session brings it to you and commits it only on
your word. The branch is the guard against unfinished work: only `dev` is
protected.

**The merge before closeout.** Once the pre-closeout triage advances the change,
the merge step (`change-merge`) brings the branch the change lands on into the
change's branch, so the validation before closeout tests the change as it will
land. That is the branch it was branched from: `make merge` merges `dev` unless
`FROM=<branch>` names another, which you give the orchestrating session for a
change branched from elsewhere. It resolves every conflict, and reconciles the
change's own code — its end-to-end scenarios above all, which no local suite runs —
with what that branch renamed or removed, which merges
without a conflict and fails only when it runs. Then it judges what the merge
needs. Its default, taken without asking, is closeout after a passing validation of
the merged `HEAD`. Another pre-closeout review, when the merge changed what the
change does, and closeout without that validation are each yours to confirm: the
merge asks, and a waived validation is your direction to closeout. A failed
validation of the merged `HEAD` sends the change back to the merge, which repairs
what it found; an inconclusive one comes to you. After a review of the merge, its
triage advances to the merge again, which merges what the branch gained meanwhile, if
anything, and otherwise advances.

**Merging `dev` at other times.** On your word, the orchestrating session merges
`dev` into the change's branch between steps — never while a round view is open, nor between a
round's sections being committed and that round's triage, so a merge never moves
the commit a round's validation and review describe. It resolves conflicts in the
change index, change documents, the step table, and skills itself, and brings a
conflict in code to you as it stands. One you leave to implementation goes, once
your decision is recorded, to an implementation run with no sections:

```text
make implement CHANGE=<change> UNATTENDED=1 ARGUMENTS='resolve the merge conflicts in <files>'
```

It resolves them, runs the suites of the sections owning them, concludes the
merge, and pushes. While the merge is in progress, `make change-next`, run in the
checkout holding the merge — the change's clone, for a change worked there — names
you, "a merge is in progress", whatever else the change's state says.

**Continuing an implementation session.** An implementation run starts a fresh
session unless you send the work to an earlier one: the next section to a session
small enough to carry it, or a fix to the session that made the edits, whose context
holds them. The orchestrating session does so only on your word, naming the session
from its run's log line:

```text
make implement CHANGE=<change> UNATTENDED=1 SECTIONS=8B SESSION_ID=<session>
```

The wrapper continues it on the model it ran on and records `continues`, the seq of
the run it continues. It refuses a session with no implementation run in the
change's log, and one waiting on your answer, which is resumed with the answer.

**A run's earlier outcomes.** A finished background command or a wake-up can give
a session another turn after it reported. The run's line is logged from its last
turn, and keeps each earlier turn's outcome under `earlier`; the orchestrating
session shows you those messages too.

**Reading the cost.** `make change-cost CHANGE=<change>` totals the change's
unattended runs by step, by round, and by whether a run opened its session, missed
the prompt cache, or read it, with the misses and the gap before each. Dollars a run
could not be told from its session's other turns show as a range. The figures are
the harness's list prices.

**Completing names.** Source `scripts/completions/make-change.bash` from your
`~/.bashrc`, after bash-completion, to complete `CHANGE=` with the active changes —
the archived ones after `archive-cleanup` — and `KIND=` with the review kinds.

## A change in its own clone

Each change can be worked in a clone of your workspace of its own, so several
changes run at once without moving each other's branch: your workspace — your
editor project — meets a change's workflow only when you read one of its rounds.
Clones live beside the workspace, one directory per change under
`<workspace>.changes/<change>/`. A clone holds the change's branch, its
`reviews/` with the workflow log and transcripts, its wheelhouse and
environments, `.snapshot/`, and its step sessions.

**Creating it.** `make orchestrate CHANGE=<change>`, started in the workspace,
creates the clone when the change's branch is checked out neither there nor in a
clone, by running `make change-clone CHANGE=<change> [BRANCH=feat/<change>]
[FROM=dev]` in the workspace, with another `BRANCH` or `FROM` when you name one —
a branch started from another change's branch; you can run it by hand too. It
clones the workspace locally, sets the clone's `origin` to the workspace's and
adds a `workspace` remote naming the workspace, and checks out the branch — the
existing one, or a new one from `FROM` — at its furthest point between the
workspace's copy and `origin`'s, refusing one where the two have diverged; the
branch tracks `origin`'s, never the workspace's. It links the clone's
`.claude/settings.local.json` to the workspace's and starts `make init` in the
background. It is safe to run again: it finishes a clone left incomplete, restarts
a failed bootstrap, and refuses, deleting nothing, a directory that is not a clone
of the workspace, has another branch checked out, or has uncommitted changes.

**The bootstrap.** `make init` in the clone is running, succeeded, or failed —
failed when it exited non-zero or its process died without recording a status —
and its log is in the clone's Git directory. Design and planning go on while it
runs; implementation, validation, and every later step wait for it. A failed
bootstrap comes to you naming its log, almost always for a reason in the
environment, and is never retried by itself: `make change-clone CHANGE=<change>`
restarts it.

**Running steps.** From the clone on, the orchestrating session computes the
change there and drives every step with `make -C <clone> <step> CHANGE=<change>
UNATTENDED=1`, so the log, the transcripts, and the step sessions are the clone's.
To take a step over, resume its session from the clone:
`cd <clone> && claude --resume <session>`.

**Reading a round.** Once a round's sections are committed, validation and the
implementation review start in the clone, and you read the round in your
workspace beside them. `make round-view CHANGE=<change>`, run in the workspace,
refuses a dirty workspace, naming the files, an unattended run in progress there,
and another change's open view; it fast-forwards the workspace's copy of the
change's branch from the clone, refusing one that has diverged or holds a commit
of yours triage has not pulled, checks it out, and resets it to the round's base,
so the round shows as uncommitted changes. Run again while the view is open, it
moves the view to the branch's new head over the same base, to follow triage's
fixes, unless you have edits or commits in the view. The clone's branch never
moves. `make round-done` returns the branch to the round's head and the workspace
to where it was — staying on the branch when you have uncommitted edits, which it
leaves for you.

A commit you make on the branch during the view — your editor's "commit all"
included — is carried onto the round's head when the view closes, each holding
exactly the paths it changed, with its author and message; `make round-done`
prints each beside its replacement, and drops one that holds nothing beyond the
round. Where the round also changed a path, the commit must hold every change the
round made to it: `make round-done` refuses, moving nothing and naming the file
and the way back (`git reset --mixed <head>`, then commit again on the round's
head), a commit holding part of a file the round changed, an edit inside a line
the round changed, an edit of a file the round added, a binary file, a symlink, or
a mode the round changed when not as the round left it, a merge, and a branch
moved off the round's base by an amend, reset, or rebase. Triage pulls your
commits into the clone, fast-forward only, and presents each as one of your points
on the round.

**History and removal.** A change's records and evidence are untracked, so no
merge carries them out of its clone. Archive cleanup, as its last act, runs `make
change-history CHANGE=<change>` in the clone, which copies the archived change's
`reviews/` and the validation evidence its records name
(`.snapshot/validation/<commit>/`, `.snapshot/e2e-logs/<run>/`) into your
workspace at the same paths. Your workspace therefore holds the history of every
cleaned-up change, and a session working another change finds it with `python3
scripts/find_change.py --records <change>`, which looks in its own checkout first,
then in your workspace. The copy is safe to run again: it copies what is missing,
leaves what is the same, extends a file the clone has since grown — the workflow log
and transcripts only grow — and refuses, naming it and overwriting nothing, any file
that differs otherwise. Once the change has merged, remove its clone with `make
change-clone-remove CHANGE=<change>` in your workspace. It refuses at once while a
run is in progress in the clone or its bootstrap is still running. Otherwise it
copies the history again first, then deletes the clone only when every file of that
history is in your workspace with the clone's contents, the branch is merged into
`origin`'s `dev` — a squash or rebase merge counts when merging the branch again
would apply cleanly and change nothing — and the clone holds no commit `origin`
lacks, no uncommitted change, and no stash; otherwise it names each problem and deletes nothing. Archive
cleanup never removes the clone, since the pull request may need another round.

**A change worked in the workspace.** A change can still be worked in your
workspace with no clone, its branch checked out there; the tooling tells the cases
apart by whether a clone holds the change's branch. Its round view resets that
branch in place, so you read the round before validation and the review start, and
the view is never refreshed.

**Moving a change already under way into a clone.** A change whose records are in
the workspace's `reviews/` is not cloned automatically: a clone copies what Git
tracks, and `reviews/` is ignored. The orchestrating session brings it to you with
two routes: check out its branch in the workspace and go on there, or move it into
a clone by hand:

1. Settle any run waiting on an answer, in the workspace, since its session is
   keyed to the workspace's path.
2. Merge `dev` into the change's branch, so its tooling knows clones.
3. Run `make change-clone CHANGE=<change>` in the workspace.
4. Copy the change's `reviews/`, and the validation evidence its records name
   (`.snapshot/validation/<commit>/`, `.snapshot/e2e-logs/<run>/`), to the same
   paths in the clone; check with `diff -r` that the copies are identical, then
   remove the workspace's.

## Reviews

`make review` runs the reviewer read-only on the review row's models: Codex in its
read-only sandbox first, and `change-review` on Claude, held to reading, when Codex
is not installed, not signed in, or at its usage limit; the record and its log line
name the reviewer's harness and model. It captures the reviewer's final message,
checks that it is a review of the kind and change asked for — its sections in
order, and every finding carrying a lens, a basis, a severity, and evidence — and
only then publishes it under the next number. A review continues the previous
reviewer's session of the same kind on the same harness, so a second design review
knows what the first asked; `FRESH=1` starts a new one. `REVIEW_BASE` is the branch
the diff is taken against (`dev` by default), and `REVIEW_MODEL` and
`REVIEW_EFFORT` are the owner's choice of reviewer for one run, outside the step
table's policy: `REVIEW_MODEL` replaces the review's models with the one named, a
`claude-` model running on Claude and any other on Codex, with no fallback, and the
record and its log line mark the run as an override. The orchestrating session
never sets them. A pre-closeout review refuses until the latest validation passed
and names `HEAD`, or an ancestor that differs only in the change's ledger and
reviews; `UNVALIDATED=1` overrides that, as does your direction to the
pre-closeout review, logged and not yet used by a run of it. `make design-review CHANGE=<change>` is
shorthand for `KIND=design`.

A plan names evidence only a push produces — a CI workflow's run, which a change
branch's push does not trigger — on its own line of a section's verification task,
beside `End-to-end:`: `Owed by validation:`, the workflow, the job, and what the
job must show. It gates no task. Once every task of the section is checked, every
validation of the change dispatches the workflow and judges the job, and its record
gains a `ci` part on its `Parts` line, a `**CI:**` line, and a `## CI` section:
each owed job and its observation with its result, the `dev` baseline run and its
commit, and every other failing job's failures with their class. An `inherited`
failure is already failing on `dev` and is no finding; a `new` one is diagnosed
like any failure, and an `uncomparable` one is of unknown cause, so triaged. With
nothing owed, the part reads `ci not owed`. Closeout records the owed observations
from the latest passing validation's `## CI`.

A review run elsewhere — in a browser session, by another tool — is pasted into
triage, which saves it verbatim as the next record, `NN-<kind>-external.md`, and
triages it with any other review of the same kind.

Before an implementation round is triaged the owner reads it:
`make round-view CHANGE=<change>` shows the round as uncommitted changes over the
commit recorded as the round started, and `make round-done` returns the branch to
the round's commit. For a change in its own clone the view is in the owner's
workspace, beside the round's validation and review ("A change in its own clone",
above). For a change worked in the workspace the view moves the branch its steps
run on, so it comes first, and while it is open every step that could commit
refuses (`make round-view-closed`). The owner's notes on the round go to triage
with the reviews; under orchestration, the orchestrating session opens and closes
the view and saves the notes. When the round's triage names another implementation
review as its exit over a fix it committed, the owner reads the fix the same way before the repeat pass is
triaged: `make round-view CHANGE=<change> BASE=<commit>`, over the commit that
triage's review read, which the next-step computation names as `base`.

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
  06-orchestrator.md                 the orchestrating session's observations of the tooling
  pull-request.md                    archive cleanup's merge drafts
  workflow.jsonl                     one line per run, unattended or recorded, and per orchestrator decision
  transcripts/
    01-design.log                    the reviewer's whole session
    07-implement.jsonl               an unattended step's event stream
    07-implement.progress            one line per tool call, as `make change-watch` shows it
```

Files are numbered in the order they were produced, so the directory reads as the
change's history; no file is overwritten, and a run whose answer was not a review
publishes nothing and is kept beside its transcript as
`transcripts/NN-<kind>.rejected.md`. A numbered review is the
only record of its findings. Transcripts are kept for the owner's export of the
change's history, and no review or triage step reads them. Archive cleanup leaves
the directory in place; for a change worked in its own clone it also copies it into
your workspace, which holds the history of every cleaned-up change ("History and
removal", above).

`workflow.jsonl` is written by `scripts/run_change_step.py` alone: each unattended
run's outcome with its session, commit, model, cost, and denials; each interactive
run's outcome as `record` appends it, marked `interactive`; each `round` line; each
`orchestrator` line, a decision naming the run it resolves or whose denials it read
and, for your direction, the target it directs; and a conversion's `convert` line.
Every line carries the log's format marker, `"format": 2`. `python3
scripts/run_change_step.py log <change>` prints it.

The three steps that edit the index — triage when a phase-closing review's triage
advances the change, closeout, and archive cleanup — run `make check-change-index`
after each edit. It checks each row's cell count; its link to its change's
directory (an `archived` row links its archive, and a row linking an archive is
`archived` or `in closeout`); its status against the legend; that each dependency
is listed and not archived; and that every active change directory has exactly one
row. An archived change needs no row: archived rows may be pruned from the index
over time.

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
When the owner waives archive cleanup's validation of a correction outside
`openspec/` and `docs/` — by their direction to archive cleanup — archive cleanup
records it as a line under the closeout review's record with `"finding":
"validated"` and the owner's reason. Read together,
a change's ledgers show where the guidance or the skills fell short.
