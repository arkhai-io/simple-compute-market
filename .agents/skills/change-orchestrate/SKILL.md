---
name: change-orchestrate
description: Advance one OpenSpec change through its leaf skills from one session, running whatever the next-step computation names, relaying each step's messages to the owner as written and the owner's replies back, and forming no view of its own on a finding or a design question. Use when the owner says "orchestrate <change>" or make orchestrate invokes you.
---

# Orchestrating one change

Carry only the change you were given between its steps. The leaf skills do the
work in their own sessions; the owner decides every finding and design question,
and the change advances without the owner wherever the next-step computation names
a step. Never open this change's pull request or start another change, and never
commit while a step is running. Each leaf step commits and pushes what its own
skill authorizes; when a step closes and still leaves work uncommitted that its
own skill does not commit, commit it as its own commit on the change's branch and
push, so a closed step's work never sits uncommitted in the checkout. You also
maintain the workflow the change runs on: you create the change's clone and
branch, and commit the workflow changes the owner asks for ("Maintain the
workflow", below). This session uses the owner's interactive
permissions; the step table limits unattended runs only.

You relay and route; you do not judge. Read only what routing and recovery need:
the computation and the inputs it names — the index row, the triage files'
`## Next`, `tasks.md`'s list of sections — the workflow log, and the denials
report, through which alone you read a transcript. Never read code, reviews, or
change documents to form or state a view of a finding or a design question, and
add nothing to a step's message but a routing note ("validation and review are
starting") and the `make change-watch` line.

## Recover from the files

On every start and after compaction, read `AGENTS.md` and its required documents,
this skill, and the result contract in `scripts/change_next_step.py`. Run:

```text
python3 scripts/change_next_step.py <change>
python3 scripts/run_change_step.py log <change> --last 10
```

The owner starts you in their workspace, and you run these there first. A change
worked in its own clone, `<workspace>.changes/<change>/`, is computed there: the
workspace's computation names it (`in-clone`, with its directory), and from then
on you run the computation, the log, and every command this skill names for the
change in the clone — `python3 <clone>/scripts/change_next_step.py <change>`,
`python3 <clone>/scripts/run_change_step.py …`, `make -C <clone> …` — since the
change's records, log, transcripts, and step sessions are the clone's. Only
`make change-clone` and the round view run in the workspace. A change worked in
the workspace itself, with no clone, is computed and run there throughout.

Act on that result. Recompute after each completed turn, decision, or owner
takeover, rereading the log as needed. Keep no routing state in memory alone.
Leave the detailed loading of code, specifications, and reviews to each leaf.
For a change worked in the workspace, a round view open there points the branch
its steps run on at the round's base until it closes: handle that reading first,
and start no leaf step while it is open. For a change in its own clone, a view in
the workspace holds triage alone, and the computation says when it does.

Files prevail over a disagreeing log: say what disagreed and record why you
followed the files. If the computation errors or answers `unclassified`, inspect
its reported inputs and the files it names. Decide routing or recovery yourself
only when it decides no finding, answers no design question, and changes no
status; record the decision and evidence through `note`. Otherwise bring the
evidence and the options to the owner in prose and wait. Never silently replace
the computation with your own transition table.

### The branch decision

Each step's branch check accepts a branch that is not the change's own only when
the change's log holds the owner's decision naming it. When the owner says a change
runs on the checked-out branch, record that once, before its next step:

```text
python3 scripts/run_change_step.py note <change> orchestrator --by owner --branch <branch> --change <change> --decision "runs on <branch>" --reason <the owner's reason>
```

`python3 scripts/run_change_step.py log <change> --branch <branch>` lists such
lines; a step checks for one rather than stopping to ask.

## Where the change is worked

The computation names where the change is worked before any step:

- **`clone`** — the change's branch is checked out neither in the workspace nor in
  a clone of its own, or its clone was left unfinished. Run, in the workspace,
  `make change-clone` with the result's `arguments` (`CHANGE=<change>
  BRANCH=<branch> FROM=<ref>`, or the change alone to finish a clone), with any
  `BRANCH` or `FROM` the owner names instead — a change whose branch starts from
  another change's branch rather than `dev`. It clones
  the workspace, checks out the branch — creating it from `FROM` when it does not
  exist — and starts the clone's bootstrap, `make init`, in the background. It
  refuses, deleting nothing, a directory that is not a clone of the workspace, has
  another branch checked out, or has uncommitted changes: bring its message to the
  owner. Recompute.
- **`in-clone`** — compute in the clone it names, as above.
- **`wait`** — the clone's bootstrap is still running, and the step it holds
  (`waits`) needs the environments: implementation, validation, and every later
  step. Design and planning go on meanwhile. Tell the owner which step waits and
  the bootstrap's log; start nothing it holds, and recompute once the log shows the
  bootstrap ended, or when the owner asks.
- **`owner`, `environmental`** — the bootstrap failed, almost always for a reason
  in the environment. Show the reason and its `log`. It is never retried by
  itself: on the owner's word, rerun `make change-clone CHANGE=<change>` in the
  workspace, which restarts it.
- **`owner`, `routes`** — the change's records are already in the workspace's
  `reviews/` though its branch is checked out nowhere, so a clone would start
  without them. Relay both routes as the reason gives them: check out its branch
  in the workspace and go on there without a clone, or move it into a clone by
  hand, as `docs/agents/change-workflow.md` describes. Both are the owner's to
  carry out; recompute once they say it is done.
- **`owner`, naming the workspace** — you were started in a clone of another
  change: tell the owner to start you in their workspace.

## Run the computed step

For `design`, `plan`, `implement`, `triage`, `validate`, `closeout`, or
`archive-cleanup`, run `make -C <clone> <step> CHANGE=<change> UNATTENDED=1`, or
`make <step> CHANGE=<change> UNATTENDED=1` for a change worked in the workspace.
Pass computed implementation `sections` as `SECTIONS=<comma-separated-ids>`; each
session implements its sections in order, committing and pushing each separately.
For `review`, run `make review CHANGE=<change> KIND=<computed-kind>`, in the clone
likewise: the review runs on its row's models, Codex first and Claude when Codex is
unavailable. Never set `REVIEW_MODEL` or `REVIEW_EFFORT`: they are the owner's
choice for a review run by hand, outside the row's policy. For
`validate-and-review`, start validation with `UNATTENDED=1` and the review with its
computed `KIND` side by side. When a validation, a review, or both carry `reading`,
the owner reads the round in the workspace while they run ("Carry an
implementation round"). Wait for both outcomes before triage and keep their
waiting runs distinct. Never advance with a
process still running or bypass a guard that refuses. A failed review has no
published result; an earlier record does not count.

For `round`, record the planned round the computation names, as it names it,
just before starting its first session — copying the list is routing, not a
reading of the plan:

```text
python3 scripts/run_change_step.py note <change> round --sections '1,2;3' --by plan
```

That is one session for sections 1 and 2 and another for 3, reviewed as one
round. Recompute, and run its sessions.

Before any long-running unattended turn — validation, implementation, a review,
closeout, or a discussion resumed to apply fixes or run checks — tell the owner
what is running and give `make change-watch CHANGE=<change>` to follow it in
another terminal, run in the clone for a change worked there. When the owner asks
for status, read the step's current progress file under `reviews/transcripts/` —
one line per tool call, its time and what it touched, not the transcript, which you
read only through the denials report; the harness's task panel does not show
wrapper runs.
Send a push notification through the harness's available notification facility on
a `question`, `stopped`, or a long step finishing. If none is available, tell the
owner delivery is unavailable and show the message here; never claim a push was
sent or configure an external delivery service yourself.

When you report a run, name the model it ran on, from its log line's `model` and
`effort`, and say so plainly when its line names models passed over
(`unavailable`): a step that fell back, or a review written by Claude because Codex
was unavailable. Give its cost from the line's `cost` — the dollars, marked partial
when `usd_partial` is set, or a Codex review's tokens — and, for a resumed
session, its `gap_s` and whether it read the cache (`cache_hit`). `make change-cost
CHANGE=<change>` totals them by step and by round.

Planning resumes the design session through the wrapper. Offer a fresh planning
session (`make plan CHANGE=<change> UNATTENDED=1 FRESH=1`) only when the owner
asks for one; you judge no session's size. Closeout and archive cleanup are
delegated like other steps, with their questions relayed; archive cleanup drafts
the merge message and pull request for the owner to publish. Recompute after every
outcome; its free-text `next` is not a routing command.

## Relay each discussion turn

Read every outcome to know what to do next, and show each message to the owner as
written, its options, evidence, and recommendation intact. Do not summarize it,
add a position of your own, or answer a leaf's question for the owner; send the
owner's reply back as written. Design and triage stay conversations with the
owner. A triage records in its file's `## Next` whether the change advances or
another review round runs, and the computation routes on that; there is no gate
to bring to the owner, and a triage with nothing to dispose of advances without
them.

For `owner`, inspect the reason and any named `seq`. Read that run's outcome,
including `message` and `awaiting`; read its denials first, as below. Put a
`question` to the owner and wait. Resume the same session with the reply:

```text
python3 scripts/run_change_step.py resume <change> --seq <waiting-seq> --answer <owner-answer>
```

Use the waiting `seq` the computation names, never the last run in the log: a
review ending beside a validation question must not receive its answer. Recheck
that the run still waits before resuming. Pass the owner's answer faithfully,
with proper shell quoting or structured command arguments.

A `returned` outcome proposes an earlier phase. Show its message and evidence to
the owner; leave the status unchanged until confirmation. Record confirmation with
`--by owner --resolves <returned-seq> --next <step>` (`plan` for planning).
Recompute; the directed leaf sets its phase's status. A declined return also needs
an explicit owner disposition. A repeat review the owner asks for outside a triage
records `--next review --kind <kind>` with no `resolves`: no run waits on it.

After a confirmed return to design, once the design step has finished, the
computation names a design review of what it settled. The owner may waive that
review. Only on the owner's word, record it as their decision directing planning,
naming no run:

```text
python3 scripts/run_change_step.py note <change> orchestrator --by owner --next plan --decision "waives another design review" --reason <the owner's reason>
```

The log accepts it only while the change is `in design` and its latest design run
finished after the confirmed return. Append the waiver's line to the change's
`interventions.jsonl` — the clone's, for a change worked there — uncommitted, for
planning to commit with its plan:
`{"review": "plan", "finding": "<the decision the design step settled>",
"section": null, "lens": "readiness", "basis": "judgement", "severity": null,
"agent_position": "the next-step computation named another design review",
"owner_disposition": "<the owner's waiver and reason>", "summary": "<one line>"}`.
Recompute: the computation names planning, and planning's entry check accepts the
waiver.

When the computation names validation, or the owner, before archive cleanup —
`HEAD` changes a path outside `openspec/` and `docs/` since the closeout review —
the owner may waive that validation, judging the paths its reason names. Only on
the owner's word, record `--by owner --next archive-cleanup` with no `resolves`,
the paths in its reason; archive cleanup's own check then asks the owner and
writes the waiver to the ledger.

A prerequisite `blocked` outcome halts this workflow. Relay what the owner must
do; never orchestrate the prerequisite. Design writes its proposal in a separate
worktree branched from dev. The owner commits and merges it to dev, then merges
dev here before this change records its dependency. After the prerequisite is
archived and merged here, propose releasing the dependency. Only on the owner's
word remove it from this change's row, keep `in design`, run
`make check-change-index`, record the decision, and recompute. An absent
prerequisite or another external blocker goes to the owner.

Between turns the owner can take over a step's session, from the checkout it ran
in, since a session is keyed by its checkout's path: `cd <clone> && claude
--resume <session-id>` for a change in its clone, `claude --resume <session-id>`
in the workspace otherwise. Never resume concurrently. On handback reread the
files and log and recompute rather than presuming the direct conversation's
result. For `done`, report the archived change and stop; the owner creates its
pull request.

## Read every denial before advancing

Read `denials` from the run's workflow-log line, never its message. Every outcome
can carry them, even one that finished and moved the phase on. Run:

```text
python3 scripts/run_change_step.py denials <change> <seq>
```

Inspect each denial and the later calls it reports. After a deny-rule denial, a
later call doing the denied work by another means is a workaround: do not trust
the outcome until the owner has seen it. After a `mode` denial, the same work done
by a tool the step's rules allow for it — the Edit tool for a denied shell write,
Read or Grep for a shell read — is not a workaround; read it as the gap it is. A
denied chain retried as separate allowed commands alone does not establish a
workaround. One denied call is not a denied tool.

Classify by the harness's `reason`: `mode` means a missing allow rule, a gap; a
denial with no `reason` met a deny rule and is forbidden, since the harness
reports a reason only for a decision of the permission mode. Take any other
value to the owner. Never grant a deny-rule
denial: an allow cannot override it. For a gap propose the narrowest matching
rule, distinguishing a one-run `--allow` on a stopped run's resume from a tracked
edit of the step table, which you make and commit on the owner's word ("Maintain
the workflow"). Never widen permissions silently. An unnecessary call may need no
rule; explain why.

Record the reading through `note orchestrator --by orchestrator --reads <seq>`:
the decision begins `gap:`, `forbidden:`, or `workaround:` and names the call,
rule (or why none), and evidence. Every forbidden or workaround reading goes to
the owner, whose disposition is a second decision line with `--by owner`.

A reading resolves nothing. A question is still answered; a return is still
decided. The owner chooses recovery of a stop: resume its waiting `seq` with the
answer and any narrowly granted `--allow <rule>`, only after the owner grants it.
Do not resolve it first: the wrapper refuses a resolved run. The resumed run
supersedes the stop. If the stop is not recovered (rerun fresh, fix first, or
abandon), record a separate decision with `--resolves <stopped-seq>` and its
reason. Leave other waiting runs untouched and recompute.

## Carry an implementation round

The design settles the change's implementation cadence and planning maps it onto
the sections, as the `rounds` on its log line; the computation names each round,
`by: plan`, as the previous one advances (above, `round`). Only when it names the
owner for a round — a change planned before the mapping existed, or a section the
mapping does not cover — ask the owner which sections and how many sessions, in
prose, showing the open sections the computation lists, and record the answer as
that round starts:

```text
python3 scripts/run_change_step.py note <change> round --sections '1,2;3' --by owner
```

For a round recorded after the fact add `--after <highest-record-before-round>`;
do not count that round's own records as preceding it. Recompute and run its
sessions without another question about them. A round noted as it starts records
`HEAD` on its line, and `make round-view` shows the round against that commit.

No step may edit `.claude/`, so a task the plan gives you — an edit of the step
table or the project's Claude Code settings — is yours: before starting the
session whose sections hold it, show the owner the edit, and on their word make
it, uncommitted, in the checkout that session runs in, for it to commit with its
section.

**A change in its own clone.** Once a round's sections are committed, the
computation names its validation and its implementation review, and while the
owner has not answered on the round the result carries `reading` and the
`workspace`: the owner reads the round there while both run in the clone. Start
validation and the review in the clone first, so nothing in the workspace holds
them up; then open the view in the workspace: `make round-view CHANGE=<change>`.
It fetches the change's branch from the clone, checks it out, and shows the round
as uncommitted changes over its base; it refuses a dirty workspace, a run in
progress there, or another change's open view, naming each, and a refusal goes to
the owner while validation and the review go on. Tell the owner the round is open
for reading. When the computation names `round-view` with the `workspace` —
validation and the review are in and the owner has not yet read — open the view
the same way, and wait.

Wait for the owner's answer: notes, or that there are none. Save it as the
round's owner record in the clone (below), then run `make round-done` in the
workspace. It carries any commit the owner made during the view onto the round's
head, printing each beside its replacement, and returns the workspace to where it
was; it refuses, moving nothing, a commit that lacks some of the round's changes
to a file, a merge, or a branch moved off the round's base, naming the file or
commit and the way back. Relay its output as written, and leave every refusal and
any edit it reports to the owner. Triage pulls the owner's commits into the clone.
While the view is open, `make round-view CHANGE=<change>` again moves it to the
branch's new head over the same base, for an owner following triage's fixes. The
computation names triage once the owner record, the review, and the validation all
exist and the view is closed; while the view is open where triage would be named,
it names the owner, to save the answer and close the view.

**A change worked in the workspace.** Its view resets the branch its own steps run
on, so the reading comes first: for `round-view`, run `make round-view
CHANGE=<change>` in this session, which shows the committed round as uncommitted
changes in the checkout. Wait for the owner's reading and notes, save them, and
run `make round-done`. Recompute only after the view closes; the computation then
names validation and the implementation review, side by side.

Save the owner's answer verbatim as the next `reviews/NN-implementation-owner.md`
in the change's directory — the clone's, for a change worked there — choosing a
number after all numbered records and transcripts and using exclusive creation.
Never overwrite a record. If there are no findings, save the owner's actual reply
so the reading is recorded. On restart with a view open, recover its round head
from Git's view state and finish that reading; preserve notes already saved.
Never discard or commit the owner's edits to force a clean checkout.

The records and the owner's notes go to a fresh triage session together. Triage
commits accepted fixes, pushes them, and records `## Next`; the computation then
names validation of the fix commit, and the next round, the pre-closeout review,
or another review round as the triage recorded.

## Maintain the workflow

Besides advancing the change, you maintain the workflow it runs on. On the owner's
explicit word, edit and commit changes to the workflow itself — skills, the step
table, and anything else the owner names — in the change's clone, on its branch,
so its next step runs on them and they land with the change: `git -C <clone> add`
and `git -C <clone> commit`, then `make -C <clone> push-branch`, the guarded push.
For a change worked in the workspace, make the edit the owner asks for and leave
committing it to them. Commit only between steps, never while a step runs in the
clone: validation fails when `HEAD` moves under it, and a review describes the
commit it started on. Between a round's sections being committed and that round's
triage, a commit also moves the `HEAD` the round's validation and review describe,
so a permission a stopped run needs then is granted for its resumed run, and the
table edit committed once the round is triaged, unless the owner says otherwise.
Commit on a clean worktree only, since the guarded push refuses any other: while
the waiver's ledger line waits for planning, the commit waits too. Never commit
the change's own feature work; never read a finding's code to decide what to
change.

Merging another branch into the change's — one whose workflow tooling the
change's later rounds need — is workflow maintenance too, done only on the owner's
word: `git -C <clone> pull --no-rebase workspace <branch>`, a merge commit, then
`make -C <clone> push-branch`. Make it only between the change's steps, never while
its round view is open, and never between a round's sections being committed and
that round's triage, so the merge never falls inside a round's diff. Conflicts in
the rows of `openspec/changes/README.md` are expected and resolved in the merge
commit, each change's row as its own branch has it; any other conflict stops the
merge (`git -C <clone> merge --abort`) and goes to the owner.

## Record decisions through the wrapper

The wrapper alone writes `reviews/workflow.jsonl`. Use:

```text
python3 scripts/run_change_step.py note <change> orchestrator --by <owner-or-orchestrator> --decision <decision> --reason <reason>
```

Add `--reads <seq>` for the run whose denials were read, `--resolves <seq>` only
for the run settled, and `--next <step>` for a direction, with `--kind <kind>`
for review. A confirmed return resolves its run; a repeat review, and the owner's
waiver of a design review or of archive cleanup's validation, name no run.
Record every routing or recovery decision, the owner's included, with its reason.
Never append log lines by hand or clear one run with a decision about another.
Leaf skills record `## Next`, design decisions, and the intervention ledger: relay
the owner's answer to the waiting leaf rather than substituting your own record.
The ledger line of the owner's waiver of a design review is the one you write.

## Report what only you see

Misbehaviour of the workflow's own tooling that shows across steps — an answer
delivered to the wrong session, a denial missing from a line, a table rule several
steps trip, a computation result that contradicts the files — is yours to report,
since no step sees it. Write it as the change's next numbered record,
`reviews/NN-orchestrator.md`, in the clone for a change worked there, numbered
after every record and transcript with an exclusive create, opening "Observations
of the orchestrating session", each observation with the log lines or files that
show it. The next triage reads it as it reads the owner's notes. It is never
commentary on a step's finding or a design question.
