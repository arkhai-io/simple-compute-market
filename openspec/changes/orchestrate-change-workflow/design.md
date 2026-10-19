## Context

Each step of a change is a leaf skill under `.agents/skills/`, started by the owner
through its `make` target. Every target but one opens an interactive Claude Code
session: `make design`, `make implement`, `make triage`, `make validate`,
`make closeout`, and `make archive-cleanup` each run `claude "/change-<step>
<change>"`. Only `make review` runs unattended: `run_change_review.py` (retired) runs
`codex exec` in a read-only sandbox, keeps its transcript under
`reviews/transcripts/`, and records the reviewer's session in the review file as
`<!-- reviewer-session: ID -->` so the next review resumes it.

The skills already know where they stop and what follows. Implementation's report
names the next targets in order; validation stops for the owner's word on an
environmental remedy (`change-validate` §5); implementation asks whether to continue
into the next section (§8); several entry checks stop and ask the owner. That
knowledge reaches the owner as prose at the end of an interactive session, and the
owner carries it to the next terminal.

Two facts about the harness shape the design. A Claude Code subagent cannot ask the
user anything, and a non-interactive run (`claude -p`) cannot prompt at all: a tool
it was not granted is denied and listed in the run's `permission_denials`. And a
`-p` run can be resumed with its whole history (`claude -p --resume <id>`), or
taken over interactively (`claude --resume <id>`) once its turn has ended; it cannot
be attached to while it runs.

The pattern is established elsewhere: a small state machine whose nodes are agent
sessions, which pauses for a person and resumes from saved state. LangGraph's
interrupts pause a node through `interrupt()`, persist state in a checkpointer keyed
by a thread id, and resume with `Command(resume=value)`; Agent Teams Lite runs one
fresh-context subagent per spec-driven phase, returning structured results, with
user approval between phases. Claude Code's own dynamic workflows take no mid-run
user input, so they cannot hold a gated discussion. None fits this repository's
steps closely enough to adopt; the decisions below take the same shape with the
harness the leaf skills already run in.

## Goals / Non-Goals

**Goals.** The owner holds one session per change and stops choosing and opening
the next one. Steps that need nobody run unattended and report when they need the
owner; discussions stay live conversations with the owner. Where the change stands
is computed from files, so any session can pick it up.

**Non-Goals.** See the proposal: one change at a time, no choice of work across
changes, none of the owner's judgement removed, no shareable logs, no change to what
a step checks, and no step run on another harness than its own.

## Decisions

### D1 — A delegated step runs as a headless process through its `make` target

Each `make` target gains an unattended form (`UNATTENDED=1`), which runs the step
through one wrapper, `scripts/run_change_step.py`: `claude -p` with the step's skill,
its allow-list (D6), the outcome schema (D3) through `--json-schema`, and the event
stream (D7). The wrapper records the session id and resumes the session with
`--resume`. Review keeps `codex exec` (D11). A step the orchestrator runs and a step
the owner runs by hand with `UNATTENDED=1` are the same process, and the owner can
take a stopped step over with `claude --resume <id>`.

A question from the step is a resume, never a restart: the step ends its turn with a
`question` outcome, the orchestrator puts it to the owner, and resumes the same
session with the answer, so the step keeps its history and carries on. This is the
proxy every "stop and ask the owner" in a skill goes through when it runs
delegated. The resume names the run it answers, by its `seq` in the log, and the
wrapper refuses a run that is not waiting — its step's latest run, ended with a
question, or stopped with no decision line resolving it: with validation and the
review run side by side (D9) the log's last run is not necessarily the one that
asked, and an answer sent to the last run reached a finished validation (45 R1).
The computation's `owner` result carries the waiting run's `seq`, and
`make change-next CHANGE=<change>` prints the result in plain form; there is no
`make resume`, since the owner reruns a step supervised rather than resuming one
by hand.

Rejected: a subagent of the orchestrator's session — no allow-lists, since its
prompts reach the owner, but it cannot be started by hand through `make`, cannot be
taken over from another terminal, and shares the orchestrator's process. Mixed
(review on Codex, the rest as subagents): two mechanisms and two ways to resume.
Doing nothing (the orchestrator names the target to run): no orchestration.

### D2 — A discussion step is the same process, resumed for each of the owner's turns

Design, triage, and planning run through the wrapper like any step. Each reply the
step makes ends its turn with an outcome whose `message` the orchestrator shows the
owner; the owner's answer resumes the step. The step's loading — the guidance
documents, specifications, code, and reviews — stays in its own session, out of
the orchestrator's. The orchestrator reads every message to know what to do next,
and shows it as written (D17). What a relayed turn costs is the step's own: every
turn of a session, attended or not, replays the whole conversation from the prompt
cache, which is cheap while the cache is warm and costs a full rewrite of the
context when it has expired. The pilot's design discussion showed warm turns well
under a dollar, and a session's opening and each cache miss each near six dollars
on the model it ran on (D19). A discussion step keeps one decision or finding per
turn: batched turns gave thinner answers, and an earlier decision can change a
later question. When relaying gets in the way, the owner
resumes the step directly with `claude --resume <id>` between turns and hands back;
the orchestrator re-reads the files.

Rejected: the discussion in the orchestrator's own session — no relay, but every
discussion's loading accumulates there until it compacts. A subagent relayed through
`SendMessage` — the same relay cost, a second mechanism beside D1, and no takeover
from another terminal. The owner conversing with a subagent in the agent panel —
the switching between views would be the owner's, which the orchestrator exists to
remove.

### D3 — Every run appends one outcome line to the change's workflow log

The wrapper appends one JSON line per run to `reviews/workflow.jsonl` in the change's
directory: the step's schema-validated final answer, with the session id, the
commit, the time, and, for a run that crashed or ended without an outcome, a
`stopped` line the wrapper writes itself with the exit status. A `stopped` line's
`denials` always come from the run's own `permission_denials`, never from the
step's account of them. `reviews/` is
untracked and moves with the change when it is archived, like the transcripts.

Outcomes: `finished` (with `next`), `question` (with `awaiting`), `returned` (a
proposed return to an earlier phase, with `return_to` and its evidence), `blocked`
(with `blocked_on`), and `stopped` (with `reason` and `denials`). Every line
carries `denials`, the run's own record of the tool calls it was denied, gathered
over every turn of the run (a background task finishing can wake a session for a
second turn with its own `result` event) and each with the harness's reason for
it. The orchestrator
adds `round` lines (D13) and `orchestrator` lines (D14) through the wrapper's
`note` operation, so the wrapper is the log's only writer. Each line keeps the
step's `message`, so a restart shows the last thing a step said without parsing its
transcript.

An `orchestrator` line is a decision — the orchestrator's own routing or recovery,
or the owner's, relayed — and names what it decides: `by` (`owner` or
`orchestrator`), `reads` (the `seq` of the run whose denials it has read, D6a),
`resolves` (the `seq` of the run it settles, which alone stops waiting on the
owner: a decision clears nothing it does not name), and, when it directs a step,
`next` (with `kind` for a review), which the next-step computation names until
that step has run. Settled at the first implementation round's triage (04 F3): the
first form, a decision as free text that cleared every run before it, let one
decision about a stopped review silence a validation question waiting beside it.
`reads` is distinct from `resolves` because a run can be denied a call and still
end with a question or a proposed return: its denials are read first, and its
question is answered or its return decided after, so a reading settles nothing of
the outcome, and a line that resolves a run counts as having read it (28 F1). A
stopped run is read the same way, and its reading resolves nothing: a stop the
owner recovers is resumed by its `seq` with a one-run grant (D6a), and the resumed
run's line is then the step's latest, so the stop is history; only a stop that is
not recovered — the step rerun fresh, fixed first, or abandoned — is settled by a
`resolves` line, since the wrapper refuses to resume a run a line has resolved
(52 F1). A directed review names its
`kind`, without which the computation could name no review; a directed step of
any other kind is a confirmed return and resolves the returned run, which would
otherwise wait ahead of the directive; a repeat review the owner directs outside
a triage names no run, waiting on no run (28 F3).

```jsonl
{"seq":12,"at":"2026-10-21T09:15:40Z","step":"orchestrator","outcome":"round","sections":[[0]],"by":"owner","after":3}
{"seq":13,"at":"2026-10-21T10:58:22Z","step":"implement","session":"9c07…","commit":"e2d81b4a","sections":[0],"outcome":"returned","return_to":"design","message":"Task 0.4: patch has no provider field; refusing it needs a decision the design does not make.","evidence":"tasks.md §0 notes","denials":[]}
{"seq":14,"at":"2026-10-21T11:20:05Z","step":"orchestrator","outcome":"orchestrator","by":"owner","resolves":13,"next":"design","decision":"return to design confirmed","reason":"task 0.4 needs a provider decision the design does not make"}
{"seq":20,"at":"2026-10-22T16:31:07Z","step":"validate","session":"51aa…","commit":"7f3c6e90","outcome":"question","message":"Helm part failed: a retained volume carries resource-policy keep. Remedy: delete it.","awaiting":"environmental remedy","denials":[]}
{"seq":22,"at":"2026-10-22T17:45:10Z","step":"review","session":"codex:019a…","commit":"7f3c6e90","outcome":"stopped","reason":"exit 1: codex authentication expired","denials":[]}
{"seq":23,"at":"2026-10-22T17:50:41Z","step":"orchestrator","outcome":"orchestrator","by":"orchestrator","resolves":22,"next":"review","kind":"implementation","decision":"rerun the review","reason":"codex authentication renewed"}
```

The log holds only what the files cannot: session ids, the owner's round
agreements, the owner's and the orchestrator's decisions, and the last outcome.
Where the log and the change's files disagree —
a status edited by hand — the files win, and the orchestrator says so. A `returned`
line does not move the index status: the owner confirms the return, and the step
then started sets the status, as now. The confirmation is a decision line that
resolves the `returned` run and names the phase's step as `next`, so the
computation routes there until the step runs and sets the status (04 F1).

Rejected: the final answer only, kept in the orchestrator's context — a restart
loses session ids and round agreements. The step writing its own outcome file — a
crashed or refused run writes nothing.

### D13 — The implementation cadence is settled in the design

How many sessions implement the work, and how much of it each round covers before
the round view, validation, review, and triage, is a decision of the design
discussion, recorded in `design.md` as the change's implementation cadence, in
terms of the work rather than section numbers, which do not exist yet — for
example "one round, one session", or "round 1: the contract changes; round 2: the
handlers and the migration". The order of implementation can bear on the design,
and settling the cadence there means nothing about it is asked once the owner has
moved on (G1b). Planning numbers the sections in that order and maps the cadence
onto them: its `finished` outcome carries `rounds`, the sections each session of each
round implements — `[[[1, 2]], [[3], [4]]]` is a round of sections 1 and 2 in one
session, then a round of 3 and 4 in a session each — which the wrapper logs on the
plan's line, where the owner and `make change-next` can see it. A plan whose
sections cannot be cut that way needs a decision and returns to design. The
computation names the next round's sections from that line once the previous round
has advanced, and the orchestrator records them, as named, in a `round` line `by:
plan` just before starting the round's implementation: copying the computation's
list is routing, not interpretation (D17). A `round` line's `after` is the highest
record number when it is written, so each round's `after` is taken once the
previous round's records exist, and the round's records are those above it (69
F1). Every round recorded at once would leave the latest taken for the current one
and all sharing one `after`. The governing plan line is the latest `finished` plan
line, and the next round is the first of its `rounds` with a section `tasks.md`
does not show complete; an amended plan maps only its incomplete sections, leaving
earlier rounds as recorded. The computation holds the mapping to that: a complete
section in the next round is left out of it, as the closeout section is, and a
round naming a section `tasks.md` lacks goes to the owner before it is recorded,
since a round line naming it could not be classified (77 F2). When the latest
plan line has no `rounds`, or an incomplete section is in no planned round — a
change planned before the mapping existed, a section a triage appended — the
computation names the owner, asked once per round, the answer recorded `by: owner` as that round starts (70 F1). The mapping
lives only in the log, like the rest of what orchestration depends on; a checkout
without the log is asked. A change designed before the
cadence was a design decision, with no cadence and no `round` line, is asked about
once, before implementation, and its answer is recorded `by: owner`. A round
agreed before the orchestrator existed — this change's own first five sections —
is recorded after the fact with `--after` naming that number (X1); without a round
line the computation can only ask for a round, and the records of the one that
happened go unread. A round of several sections
runs back to back with no stop between them; a small change is usually one round of
every section up to closeout. The plan describes what to change and is agnostic of
sessions, rounds, and whether a coding harness implements it at all: a section is a
coherent, verifiable slice, sized by what it changes and what proves it. One section
per session is not enforced; the risk of a session degrading as it grows stays
advice in `change-implement`, for the owner to weigh.

Rejected: round breaks written into `tasks.md` at planning, alone or as a default
the owner overrides — that puts session logistics into a plan that should not know
about them. The orchestrator agreeing each round with the owner before
implementation — a question asked after the owner's attention has gone to other
work, and the pilot's agreed round of four sections was recorded as three
sessions on the skill's own advice about long sessions.

#### The revision's implementation cadence

The sections the revision after section 6 adds — ordered models, cost recording,
advancing on conditions, and the skills' touchpoints — are implemented as one round
in one session, in that order, then validated and reviewed together: they build on
one another, and the skills describe what the scripts before them built. Settled
with the owner at planning, which found the revision's design had no cadence of its
own; the owner waived another design review for it.

### D14 — A script computes the next step; the orchestrator is its backstop

`scripts/change_next_step.py <change>` reads the change's index row and status, its
`Depends on`, `reviews/` and their triage files' `## Next`, `tasks.md`, the log, and the open
round view's state that `scripts/round_view.py` keeps in Git, and prints the next
step as data — for example
`{"step":"triage","reason":"05-validation.md and 06-implementation.md have no triage"}`
or `{"step":"owner","reason":"round agreement needed before implementation"}`. Among
the results that wait for the owner:

- a round view is open: `owner`, awaiting the owner's notes on the round, then
  `make round-done` (D9);
- a prerequisite named in `Depends on` has no directory on this branch: `owner`,
  merging dev once the prerequisite's proposal lands (D5);
- a prerequisite gating `design` is not archived: `owner`, design waits on it (D5);
- a prerequisite gating `design` is archived on this branch: `owner`, proposing the
  release (D5a);
- a step's latest run went on past a denied tool: `owner`, carrying the denials,
  until a decision line reads that run (D6a), whatever phase the change is in
  now — the run may be the one that moved it on, a design triage advancing
  sets the next phase's status in the same run (39 F2) — while a question,
  return, or block waits only in the phase it was raised in; its question or
  return then waits as below;
- a step's latest run asked, returned, was blocked, or stopped: `owner`, until
  its session is resumed with the answer or a decision line resolves that run
  (D3); a decision that names `next` routes to that step until it has run, which
  is how a confirmed return reaches the phase's step (04 F1) and a repeat review
  the owner asked for reaches the reviewer;
- a review whose triage recorded another round: the review of the same kind
  again once `HEAD` differs from the reviewed commit in more than changes' records
  — the round's accepted fixes committed — a pre-closeout or implementation one
  once that commit is validated; with no fix committed, the review runs again on
  the same commit (04 F2, G1).

Everything else advances without the owner (D16). A triage that recorded `advance`
moves the change to its phase's next step: planning after a design review;
validation of the fix commit, then the next round or the pre-closeout review after
an implementation round; closeout once the latest validation of `HEAD` passed after
a pre-closeout review; and archive cleanup after a closeout review, once the
latest validation passed for `HEAD`, or for an ancestor `HEAD` differs from only in
records, whenever `HEAD` differs from the closeout review's reviewed commit in a
path outside `openspec/` and `docs/` — `.agents/` and `.claude/` counted outside,
since a skill or table edit changes behaviour — so a code correction a closeout
triage directed is validated before archive cleanup commits and drafts the pull
request, the check the gate used to be (69 F7). A documentation-only correction is
covered by the checks triage already runs, and costs no pipeline run (70 F9). A round's
validation and review start once the owner's notes on the round view are saved.
These conditions are the computation's; the
orchestrator runs that step and never routes on its own reading. The transitions
are already fixed by each skill's entry check and handoff; in code they are
testable under `scripts/tests`, and the owner can run the same command by hand,
or `make change-next CHANGE=<change>` for it in plain form. A task list whose numbered
task sits under another section's heading is not routed on: the script answers
`unclassified` naming the task and the heading, as the backstop to
`make check-tasks CHANGE=<change>`, which the skills that act on the list —
implementation and closeout at their entry checks, planning after writing the
plan — run first (39 F1: a heading lost in an edit handed section 6's tasks to
section 5, and the script named sections 1–5 to implement again).

When the script fails — an error, a state it cannot classify, files and log that
disagree — the orchestrator receives its output and the inputs it read, works out
what happened, and either decides, when the matter is routing or recovery (a step
that died before writing an outcome, a status set by hand), or raises it with the
owner, when the answer would decide a finding, settle a design question, or change
a status. Either way it records an `orchestrator` line with what it decided and why;
those lines are the evidence for what the script should learn next.

Rejected: routing by the skill alone — only as reliable as the model's reading on a
given turn, and least reliable late in a long session. A transition table written
into the skill — still read by the model, and untestable.

### D5 — A design blocked on a prerequisite shapes it and halts

When a design cannot proceed without another change, the design step, with the
owner, defines the prerequisite's requirements and initial proposal and ends with a
`blocked` outcome. The workflow halts there. The proposal is never written on the
blocked branch:

1. The design step creates a worktree on a new branch from dev,
   `git worktree add ../<prereq>-proposal -b propose-<prereq> dev`, and writes the
   prerequisite's directory and its `ready for design` index row there.
2. The owner commits in that worktree and opens its pull request.
3. Once it merges, the blocked branch merges dev, so the proposal reaches the
   blocked branch only through dev's history.
4. The blocked change then stays `in design`, with the prerequisite in `Depends on`
   gating `design` and `Notes` naming it. `change-design`'s entry check already
   stops while a dependency gating `design` is unarchived, so no status of its own
   is needed; `blocked in design` is reserved for reasons that are not another
   change.
5. The owner starts the prerequisite's workflow on its own branch from dev; once it
   is archived and merged to dev, and dev is merged into the blocked branch, the
   original workflow restarts with its prerequisite met (D5a).

`make check-change-index` requires a `Depends on` entry to name a listed change, so
the dependency is recorded only after step 3, when the prerequisite's row is on the
blocked branch.

Rejected: the orchestrator creating the prerequisite's branch and starting its
workflow — choosing to start other work is the owner's. Stacking the prerequisite
on the blocked branch — two changes in one pull request, and a prerequisite another
change needs could not land alone. Writing the proposal on the blocked branch and
cherry-picking it to a proposal branch — it works only if the blocked branch merges
dev before the prerequisite is archived; otherwise the merge base lacks the
proposal, and merging dev back leaves the blocked branch's unarchived copy beside
dev's archived one without a conflict. The worktree makes that duplicate impossible
rather than relying on an ordering rule. The owner copying the files by hand — the
same hazard, and no single commit to point at.

#### D5a — The restart releases the dependency on the owner's word

Archive cleanup releases a change's dependents by editing their rows, but the
blocked change's dependency exists only on its branch. After dev is merged in, the
blocked row depends on an archived change, which `make check-change-index` rejects.
`change_next_step.py` recognizes that state; the orchestrator proposes the release,
and on the owner's word drops the dependency, leaving the status `in design`, runs
`make check-change-index`, and resumes design.

### D6 — A run through the wrapper is held to its step's allow-list

Every run through the wrapper, discussions included, uses
`--permission-mode dontAsk` with the step's allow and deny rules from
`.claude/change-steps.toml`, which the wrapper reads. The rules are specific to
Claude Code, so they live in Claude Code's own directory — whose contents say
what a Claude Code session in this repository may do, and which the common deny
already covers — rather than with the harness-neutral skills or under `scripts/`
(02 O2; the outcome schema, harness-neutral, lives with the skills as
`.agents/change-outcome.schema.json`, 02 O3). The table is TOML because the
scripts run on the standard library, which reads TOML and not YAML, and the
table's comments carry each row's reason, which JSON cannot hold. An interactive
run is unaffected: the owner's own permission settings apply, with prompts.

| Step | Allowed | Denied |
|---|---|---|
| design, plan | read; edit `openspec/`, `docs/`; the pinned OpenSpec validator; `make check-*`; for a prerequisite (D5), `git worktree add` on a new branch from dev and edits under that worktree's `openspec/` | commits of code, any push |
| triage | design's, and implement's, since it fixes what the owner accepts and commits | any push |
| implement | edit the repository; `make` test, lock, and check targets; `uv run`; `git add`, `git commit`; the Agent tool | any push, `make push-branch`, `make run-e2e` |
| validate | read; write `reviews/NN-validation.md` only, by an `Edit(path)` rule, since an `Edit` rule covers every editing tool and a `Write(path)` rule is not honoured (X4, 29 A1); `make validate-*`, `push-branch`, `run-e2e`, `round-e2e-baseline`, `fetch-e2e-logs`; `gh run list`, `gh run view`, `gh auth status`; `docker`, `kubectl`, `helm` | `make lock`, commits, any other push; any other edit for want of an allow rule — a bare `Edit` deny would deny the record too |
| closeout | edit `openspec/`, `docs/`; `openspec archive`; `make check-*`; commits | code edits, any push |
| archive cleanup | edit the index; write `reviews/pull-request.md`, by an `Edit(path)` rule likewise; commits | any push, creating the pull request |

Every step's row also allows the read-only shell utilities the skills reach for
(`ls`, `cat`, `head`, `tail`, `wc`, `grep`, `echo`, `diff`, `find` without its
writing actions), since a chained command runs only when every command in it is
allowed and the first round's validation and triage stopped on chains of exactly
those (07 A1); `make round-view-closed` is matched with a trailing variable (X4);
and every step may run the next-step computation, so a step can see where the
change stands, and `make change-cost`, the read-only cost report (74 O3). The
read-only Git commands are held read-only by deny rules on the diff family's
`--output`, which writes its output to a file: `git diff`, `git show`, and `git
log` are allowed only without it, since git accepts no abbreviation of the option
(77 F1). No row admits a shell loop: `bash -c` cannot be allowed without
allowing any command (29 A2). A step waits on a background command inside one
Bash call, with a blocking read-only `tail -f … | grep -m1` on the line the
command prints when it ends, repeated when the call times out, and never by
ending its turn: under the wrapper a turn's end is an outcome, and the harness's
notification of a finished background task arrives only after the turn, so a
turn ended with work in flight is logged as a stop (41 A1). The background
command runs as written, with no shell redirect of its output: a redirect is a
write no rule admits, and the harness keeps the output in a file the `tail`
reads (54 A1).

Each row also names the models its step runs on, in priority order, with each
one's effort, and the wrapper runs the first that is available (D18).

The allow-lists turn each skill's "never" lines into rules the harness enforces:
validation's "never changes the commit" stops being an instruction only. A run that
cannot go on without a denied tool ends `stopped` with its reason; one that can —
a chained command denied for one part, rerun one command at a time — goes on and
ends as it ends, and either way the wrapper records every denial on the line from
the run's own record (D3; X2, X3). The orchestrator reads each as D6a says before
the change moves on. Edits to the table are proposed, never silent, and logged.

#### D6a — The orchestrator reads every denial from the record

A denial is read from the run's log line, never from the step's message: the
record is the harness's and names the call, the message is the model's and
generalizes (the first round's steps reported "Bash is not allowed" for a chain
missing `echo`; X5). The reading, in `change-orchestrate`:

1. A recorded denial carries the harness's reason when the harness gave one.
   `mode` — no allow rule under `dontAsk` — is a gap in the table. A denial with no
   reason met a deny rule: the harness reports a reason only for a decision of the
   permission mode, as the round of sections 6a–6d showed, its eight deny-rule
   denials carrying none beside a `mode` denial in the same run (74 R2). That is a
   forbidden action, the skill's "never" line enforced. Any other value goes to
   the owner.
2. `run_change_step.py denials <change> <seq>` lists each denial with the tool
   calls the run made after it, from the transcript. After a deny-rule denial, a
   later call that did the denied call's work by another means is a workaround:
   the run's outcome is not trusted until the owner has seen it. After a `mode`
   denial, the same work done by a tool the step's rules allow for it — the Edit
   tool for a shell write, Read or Grep for a shell read — is not one: the rules
   already allow that work, and the call is read as a gap (103 R3).
3. For a gap, the orchestrator proposes the narrowest rule that matches the call —
   `Bash(gh run view *)`, not `Bash(gh *)` — and says which it is: a one-run
   `--allow` on the resume, for a stopped run that needs the call to go on, or a
   tracked table edit the owner commits, for a call the step's skill makes routine.
   A deny-rule denial is never granted for one run: the grant cannot override it.
4. The reading is recorded as a decision line that `reads` the run, `by:
   orchestrator`, its `decision` beginning `gap:`, `forbidden:`, or `workaround:`
   with the call and the rule. The reading settles nothing of the run's outcome
   (28 F1): a run that ended with a question or a proposed return is answered or
   decided after it, and a stopped run is recovered after it — resumed by its
   `seq` with the one-run grant of step 3, which the wrapper refuses for a run a
   line has resolved — or, when it is not recovered, settled by a `resolves` line
   (52 F1). A forbidden or workaround reading goes to the owner, whose disposition
   is a second line, `by: owner`.

A run that went on past a denial waits in the computation like a stop, until a
line reads it, so the reading happens whether or not the orchestrator was awake
when the line was written; its question or return then waits as it would without
the denial.

Rejected: auto mode — what a step may do would rest on a classifier's call per
action, unreviewable in advance. A permission-prompt tool routing each prompt to
the orchestrator — an MCP server to build, and an hour-long validation blocked on a
prompt while the owner is away, where a denial ends cleanly and resumably. Bypass —
validation drives Docker, the cluster, and the push.

### D7 — The wrapper records the event stream, and the owner is notified when it is their turn

The wrapper runs each step with `--output-format stream-json --verbose`, writes the
stream to `reviews/transcripts/NN-<step>.jsonl` beside the review transcripts, and
keeps a short progress file of each tool call and its time. The orchestrator
answers "how is it going?" from the progress file; the owner follows it in another
terminal with `make change-watch CHANGE=<change>`, which moves to each new step's
progress file as it starts. Whenever the orchestrator starts a long-running
unattended turn — validation, implementation, a review, closeout, or a discussion
step resumed for a turn that applies fixes or runs the checks — it says so and
gives that command (55 O2): the harness's task panel shows nothing for a wrapper
run, and following one from inside the orchestrating session is left to a later
change. When a step ends `question` or `stopped`, or a long step finishes, the
orchestrator sends a push notification; Remote Control lets the owner answer from
elsewhere.

Rejected: outcomes only — "is it stuck?" can only be answered by waiting.

### D8 — Planning resumes the design session; closeout and archive cleanup are delegated

Planning resumes the design step's session, after the design review and its triage,
since `change-plan` is better written with the design's context; it reads the design
triage's `## Next`
from the files as its entry check requires. Design and planning are usually
minutes apart, so the design session's cache is usually warm, and resuming it is
cheaper and better informed than a fresh session (69 F9). It asks nothing of the
owner: the owner reviews the design, not the plan, and the order of the plan's
sections is settled in the design (D13). A plan that needs a decision the design
does not make ends `returned` to design. `make plan CHANGE=<change>` opens
`/change-plan <change>` interactively, and its unattended form (D1) resumes the
design step's session recorded in the log; `FRESH=1` starts a fresh session
instead, on the owner's word, since the orchestrator judges no session's size. Closeout and
archive cleanup are delegated: closeout's points put to the owner become `question`
outcomes, and a part that needs a code edit becomes `returned` to implementation.
Archive cleanup drafts the pull request; the owner creates it.

### D9 — The orchestrator opens and closes the round view

After a round's sections are committed, the orchestrator runs `make round-view` in
its own session, under the owner's permissions, which pushes the round and
dispatches the pipeline. The view's base is the commit the round's `round` line
recorded as `HEAD` when the round started, so commits landing between rounds — a
design revision, another change's sections on a shared branch — are not shown as
the round's; a round line naming none, one recorded after the fact, falls back to
the latest triaged validation's commit (74 R3). It waits for the owner's word.
When the owner gives notes on the round, the orchestrator saves them verbatim as
the change's next numbered record, `reviews/NN-implementation-owner.md`, which triage already takes as the
owner's findings, so a restart cannot lose them. It then runs `make round-done`, and
starts validation and the implementation review side by side, validation adopting
the running pipeline through `make round-e2e-baseline`. This is
`change-implement`'s existing order.

A restart recovers from Git and the files alone. While the view is open,
`round_view.py`'s state names the round's head and `change_next_step.py` waits for
the owner's notes and the close (D14); the branch then sits at the round's base, so
nothing else about the change is read until the view is closed. After
`round-done`, the round's commits are on the branch with no validation naming
`HEAD`, so validation and review are next, and the baseline the view recorded for
that head lets validation adopt the pipeline already running.

### D10 — The orchestrator holds no state of its own

`make orchestrate CHANGE=<change>` opens `claude "/change-orchestrate <change>"`,
after `make design`. On every start, and after compaction, the orchestrator runs
`change_next_step.py`, which reads the open round view's state among its inputs, and
reads the log's last lines; it keeps nothing else. It commits nothing: steps commit
as their skills say, and the owner commits design-phase work, creates branches, and
opens pull requests, including a prerequisite proposal's. The one branch a step
creates is a prerequisite proposal's, from dev, in its own worktree (D5).

### D11 — Reviews keep Codex, under the same wrapper

The wrapper takes over what `run_change_review.py` does — the reviewer-session
marker, resuming the reviewer's session, the transcript, and claiming a new
numbered record for the run, removed when the reviewer fails or its review is
invalid. A review's outcome is deterministic: when the run published its claimed
record, `finished`, naming that record and the reviewed commit, and triage is next;
otherwise `stopped`, with the runner's reason. An earlier review file never counts.
Codex needs no output schema for this.

When Codex is unavailable — not installed, not signed in, or out of quota — the
review falls back to `change-review` on Claude, through the wrapper, as the review
row's ordered models say (D18). The record and the log line name the reviewer's
harness and model, and the orchestrator says so when it reports the review. A
review on a second model is preferred, since it reads the work with another
model's eye; a review on Claude is better than none, and halting on a missing
reviewer only costs the owner time (G6a, the practice of the first cloud run).

The review has a row in the step table, `skill = "change-review"`, whose Claude
entry is held read-only: reading, read-only Git with the diff family's `--output`
denied (D6, 77 F1), and the common read utilities, with no edit. A review on
Claude runs without the outcome schema: its final text is the review, checked and
published as Codex's is, and its outcome derived the same way. The record's `reviewer-session` carries its harness, `codex:<id>` or
`claude:<id>`, and a review continues the previous reviewer's session only on the
same harness, otherwise starting fresh; an untagged marker, written before the tag
existed, is a Codex session. The table is the workflow's policy. `REVIEW_MODEL`
and `REVIEW_EFFORT` are unset by default and are the owner's choice for a review
run by hand, outside that policy on purpose, a forbidden model included:
`REVIEW_MODEL` replaces the review's models with the one named, its harness read
from its name — a `claude-` model on Claude, any other on Codex — with no fallback,
and its effort the one given or the table's for that harness; `REVIEW_EFFORT` alone
replaces every entry's effort. The record carries a `reviewer-override` marker and
its log line `override: true`, and the orchestrating session never sets either
(77 F3, 74 O1; earlier 69 F4, 70 F6).

### D12 — The skills change how they ask and report, not what they check

When a skill runs through the wrapper, every "stop and ask the owner" ends its turn
with a `question` outcome; a denied call ends it `stopped`, naming that exact
call, only when the step cannot complete without it, never a question or a
workaround; a call a deny rule refused is done by no other tool, and one denied
in `dontAsk` mode for want of a rule may be done by a tool the step's rules allow
for the same work, the step naming the substitute (103 R3); a chained command
denied because one part lacks a rule is rerun one command at a time, since the
denial is of the chain and not of its parts; a step
finishes every part of its work that does not depend on a denied call, and one
that can complete goes on and ends as it ends, the denial recorded on its outcome
for the orchestrator's reading (X3, X5, 28 F1); and its last turn ends with an
outcome matching `.agents/change-outcome.schema.json`. Interactive use is
unchanged. Beyond that:

- `change-plan` sizes a section as a coherent, verifiable slice rather than to one
  session, and drops "one section per session" from its handoff (D13).
- `change-implement` implements the sections it was given, drops §8's question,
  and keeps the warning about a growing session as advice (D13).
- `change-design` gains the blocked-on-prerequisite path (D5, D5a), and settles
  the implementation cadence before it is recorded (D13).
- `change-plan` asks nothing of the owner: it orders its sections by the design's
  cadence, and a plan needing a decision ends `returned` to design (D8, D16).
- `change-triage` ends with `## Next` in place of the gate, asking at the end of the
  dispositions, before any fix, whether another round is merited (D16).
- `change-closeout`'s and `change-archive-cleanup`'s entry checks read the latest
  pre-closeout or closeout triage's `## Next` beginning `Advance`, a legacy `## Gate`
  beginning `Passed` read the same, and `change-design`'s handoff describes the
  advance rather than a gate (70 F4).
- The branch checks of `change-implement`, `change-triage`, `change-validate`,
  `change-closeout`, and `change-archive-cleanup` accept a branch that is not the
  change's own when the change's log holds an `orchestrator` line `by: owner` with
  `branch` naming the checked-out branch and `change` naming the change (D15).
- `change-review`'s "Running unattended" covers a review on Claude as on Codex,
  its final message the review either way (D11).
- `change-orchestrate` relays and routes without judging findings (D17), records
  each planned round as it starts (D13), and reports fallbacks and cost
  (D18, D19).

### D15 — The pilot runs on this change's branch

`fix-resource-pool-provider-at-creation` is worked through every step by the
orchestrator on this change's branch, once the orchestrator's sections are
committed. The owner's word that the pilot runs on this branch is one recorded
decision, an `orchestrator` line `by: owner` carrying `"branch":
"feat/orchestrate-change-workflow"` and the pilot's `change`, which each step's
branch check accepts rather than stopping at every step (69 F8, 70 F4, D16).
Both changes archive here and land as one pull request. This is a deliberate
exception to one change per branch: the pilot is this change's own end-to-end
evidence, and its lessons reach this change's triage and closeout directly.

Rejected: landing the orchestrator first and piloting afterwards — the orchestrator
would close out with no evidence it works. A pilot branch stacked on this one — a
second branch to keep current, for a small pilot.

### D16 — The owner is interrupted only for judgement

A change stops for the owner at four kinds of moment, and advances on its own at
every other:

1. the design discussion's questions;
2. the owner's notes on a round, read through the round view, before its triage;
3. the triage discussion: each finding's disposition, and, at the end of the
   dispositions and before any fix is made, whether the round's accepted fixes
   merit another review round — triage recommends, from what the fixes will
   change, and the owner decides while still present;
4. the interrupts no rule can settle: an environmental remedy validation proposes,
   a denial that needs a rule or was forbidden (D6a), a proposed return, a step that
   stopped, a design `blocked` on a prerequisite, D5a's release of a landed
   prerequisite on the owner's word, a round of a change with no planned mapping
   (D13), and the one recorded decision that the pilot runs on this branch (D15).

Reviews are no longer gates. A review's triage file ends with `## Next`, whose
first words are a fixed token, `Advance` or `Another round`, followed by the owner's
words; the computation reads the token alone, as it read `Passed` (D14), since
routing on free text was rejected at 28 F1. A triage file with no `## Next` is a
triage still in progress: the computation names triage, or the run waiting in it,
never a review. The round's `## Next` is the review's triage file's; the triage
files of its validation and the owner's notes end "Evidence for the round triaged
in `NN-<review>.triage.md`" and are not routed on. A legacy `## Gate` beginning
`Passed` reads as `Advance`, and any other legacy gate goes to the owner, so nothing
already passed reopens. An implementation or pre-closeout round advances only on a
`passed` validation naming its final commit; an `inconclusive` one is missing
evidence and goes to the owner. A triage with no finding and no point of the
owner's notes to dispose of records `Advance` itself (69 F2, F3). Pre-closeout and
closeout triage are discussions like any other: with findings they stop for the
owner, without them they advance. The owner's own look at the pull request on
GitHub before merging is outside the workflow. The orchestrator answers no design
question and decides no finding; it advances only on conditions the computation
checks, and the conditions replace the gates, whose answer was always yes and whose
asking left the owner's window idle while their attention was on other work.

The pinned validator refuses a MODIFIED requirement that renames a scenario, so the
delta keeps two of "Index transitions"' scenario titles, "A closeout gate is passed"
and "A pre-closeout gate is passed", with bodies that say the triage advances; once
archive cleanup has run, the permanent spec's two titles are renamed to match.

Rejected: keeping every gate — the owner was asked a question whose answer never
varied. Renaming the gate a routing question at each review — the same
interruption under another name; the benefit is in not stopping. Keeping
pre-closeout and closeout as gates — neither has ever been refused, and both
still stop for the owner whenever their triage has a finding.

### D17 — The orchestrator relays and routes; it does not judge

The orchestrating session starts steps, shows each step's message to the owner as
written, and sends the owner's reply back as written. It reads no code, reviews, or
change documents to form or state a view of a finding or a design question. What it
reads is what routing and recovery need: the computation and the inputs it names —
the index row, the triage files' `## Next`, `tasks.md`'s list of sections — the
workflow log, and the denials report, through which alone it reads a transcript
(D6a); that also serves D14's backstop and D5a's release (69 F5). The line is not
always sharp, and the pilot's orchestrator lines are where it is checked. It adds
nothing to a step's message but a routing note — "validation and review are starting" — and the `make change-watch`
line (D7). It runs on Opus 5.5 at medium effort, passed by `make orchestrate`: it
needs a large context for a change's relayed turns, not the effort of judging them.

What only the orchestrator sees is still reported. Misbehaviour of the wrapper or
the computation that shows across steps — an answer delivered to the wrong session,
a denial missing from a line, a table rule several steps trip — the orchestrator
writes as the change's next numbered record, marked as its own observations, for
the next triage; never as commentary on a step's finding.

Rejected: the orchestrator stating its own position on each finding — it read again
what the step had read, which cost tokens and blurred whose recommendation the owner
was weighing, though its conclusions were sometimes better. Relaying with no
observations of its own — the wrapper and computation defects found in this
change's rounds (X1–X5, 45 R1) came from the orchestrator alone.

### D18 — Each step runs on an ordered list of models

Each row of `.claude/change-steps.toml` names its step's models in priority order,
each with its harness and effort; the wrapper runs the first available and the log
line names the entry that ran. A harness is unavailable when its program is
missing, it is not signed in, or it reports a usage limit — Claude's "hit your …
limit", Codex's usage-limit error; the wrapper then falls to the next entry. A
network error is retried twice and then ends the run `stopped`, with no fallback,
and any other failure is a failed run as before. A waiting run is resumed only on
the model it ran on, since a session cannot move between harnesses: when that model
is unavailable, the resume ends `stopped` with the time the limit resets (69 F4). The
policy:

| Step | Models, in order |
|---|---|
| design (and planning, resuming its session), triage, implement, closeout | Claude Opus 5.5, high |
| validate, archive cleanup | Claude Sonnet 5.5, medium |
| review | Codex `gpt-6-sol`, high; then Claude Opus 5.5, high |

```toml
[steps.review]
skill = "change-review"
models = [
  { harness = "codex",  model = "gpt-6-sol",       effort = "high" },
  { harness = "claude", model = "claude-opus-5-5", effort = "high" },
]

[steps.validate]
skill = "change-validate"
models = [{ harness = "claude", model = "claude-sonnet-5-5", effort = "medium" }]
```

Design and triage need Opus at high effort: earlier tests found it caught more
problems and explained its decisions better. Implementation and closeout stay
there until the cost data (D19) shows otherwise, since their cost is judged to come
from replayed context and the orchestrator's reading, not the model. Validation
runs commands and reads their logs, and archive cleanup edits a row and drafts a
pull request; Sonnet at medium suits both.

The table loader refuses a row naming Fable or Astra, which the workflow never
chooses — only the owner's own override of a review run by hand may name them
(D11) — and a row listing two models of one vendor: an outage or a usage limit
takes both down, so a second model of the same vendor is no fallback. Codex
appears only where its sandbox can hold the step to its limits, which today is the review alone: a
`workspace-write` sandbox cannot refuse a commit or a relock. A step whose one
model is unavailable ends `stopped` with the reason and the time the limit resets,
and waits.

Rejected: an unset model, inheriting the default — the pilot's steps ran on the
most expensive model without anyone choosing it. Claude models falling back to one
another. Codex as a fallback for any step — without D6's table and denials record,
a Codex step would be held to its skill's words only; running leaf steps on Codex
with those guarantees is later work, alongside parallel workflows and shared
artifacts.

### D19 — Every run records its cost

Each log line carries the model and effort that ran and a `cost` object: for a
Claude run, the dollars, turns, duration, and input, output, cache-read, and
cache-write tokens; for a Codex review, the tokens it reports. The fields differ in
kind, as the pilot's transcripts show: a resumed session's `total_cost_usd` is its
running total, while its token counts are the run's own. Tokens, turns, and
duration are summed over the run's `result` events (D3); the dollars are taken from
the last, and are the run's total less the total
on the session's last logged run, and the line is marked `usd_partial` when
something intervened — the previous run crashed without a result, or the session's
own conversation file gained turns the wrapper did not run, as when the owner took
the session over (69 F6). A resumed run also records the gap since its session's
last turn of any kind and whether its first turn hit the prompt cache.

```jsonl
{"seq":74,"step":"triage","outcome":"question","session":"057b…","model":"claude-opus-5-5","effort":"high","gap_s":412,"cache_hit":true,"cost":{"usd":0.31,"turns":2,"duration_s":17.5,"input":2,"output":972,"cache_read":249533,"cache_write":1211},"message":"…","denials":[]}
{"seq":75,"step":"review","outcome":"finished","session":"codex:01a1…","kind":"implementation","model":"gpt-6-sol","cost":{"tokens":403900},"record":"52-implementation.md"}
```

`make change-cost CHANGE=<change>` totals the lines by step and by round — a
line's round is the `round` line in force when it was written, lines before any are
design and planning, and lines from the first pre-closeout review on are closeout
(70 F7) — shows partial dollars as a range, and lists
the cache misses with their gaps, so the cost of session openings, of misses, and
of warm turns can be told apart. The orchestrator's own session is not a wrapper
run and is not recorded.

Rejected: a report parsing the transcripts on demand — Codex logs and Claude
transcripts differ, and every report would reparse them. Nothing — the account's
console shows totals, not which step or turn spent them.

### Decisions at the first implementation round's triage

Beside the amendments above, each under its finding's label:

- **04 F3 (A+)** — decision lines carry `by`, `resolves`, and `next`; see D3, D14.
- **04 F1** — a confirmed return is a decision line resolving the `returned` run
  with `next` the phase's step; `change-plan` section 3 sets `in design` only
  interactively and ends `returned` unattended; see D3.
- **04 F2 (both)** — a failed pre-closeout or closeout gate is followed by the
  review of the same kind once a fix commit lands (and, for pre-closeout, is
  validated), read from the review's reviewed commit against `HEAD`; a repeat
  review with no fix is a decision line with `next`; see D14.
- **X1** — `note round --after`; see D13.
- **X2, X3 (option 2)** — the outcome stands and every denial is recorded; see D3,
  D6, D12.
- **X4, 07 A1** — the table's rules; see D6.
- **X5, D6a** — the orchestrator's reading; see D6a.
- **02 O2, 02 O3** — the table under `.claude/`, the schema under `.agents/`,
  TOML kept; see D6. `check-doc-citations` verifies `.agents/` paths too, so the
  skills' citation of the schema stays checked.
- **02 O1** — `make check-comment-hygiene` runs `scripts/check_comment_hygiene.py`,
  a direct port of the shell target: the same scans, file types, exclusions, and
  the one exemption as a named rule, with unit tests. What the check catches is
  unchanged; the step table, under `.claude/`, is outside its change-name scan as
  that exclusion already stood.
- **07 A2** — `validate_slice.py` prints one flushed line as each step starts and
  ends, so a part can be watched while it runs; its summary was its only output.

### Decisions at the second implementation round's triage

- **28 F1 (option 1)** — a decision line `reads` the run whose denials it read,
  beside `resolves`; a run with unread denials waits for the reading first, then
  for its question's answer or its return's decision as before; the skills and
  the wrapper prompt say a step stops only when it cannot go on without the denied
  call; see D3, D6a, D12, D14. Rejected: a resolved question that waits until the
  step's next line (a special rule for one outcome, and a return's reading would
  resolve it unconfirmed); routing on the `gap:`/`forbidden:`/`workaround:` prefix
  (a routing rule on free text).
- **28 F3** — a directed review names its kind, a directed step of any other kind
  resolves the returned run, and a repeat review names no run; the delta shows
  both as log lines; see D3.
- **28 F2** — an archived change's ledger and reviews are records, so a closeout
  triage's ledger commit is not a fix; see D14.
- **29 A1** — the record rules take the `Edit(path)` form, since `Write(path)`
  allow rules are not honoured; this corrects X4's cause, whose `Edit` deny
  removal was harmless; see D6.
- **29 A2** — validation waits on a background part through a read-only `tail`,
  never a shell loop; no rule for `bash -c`; see D6. Its other option, the
  harness's notification, was superseded by 41 A1.

### Decisions at the third implementation round's triage

- **39 F1** — a task whose leading `N.` is not its `## N.` heading's fails
  `make check-tasks CHANGE=<change>`, run by the skills that act on the list at
  their entry checks (`change-plan` after writing the plan); the computation uses
  the same function as its backstop in the implementation phase; see D14.
- **39 F2** — unread denials wait whatever the phase, before any step runs; a
  question, return, or block waits only in its phase; see D14.
- **39 F3** — task 6.1 reworded around `reads` and `resolves`, with the question
  and return cases and the repeat-review exception; see D3, D6a.
- **41 A1** — validation waits on a background part inside one Bash call with a
  blocking read-only `tail`, repeated when the call times out, never by ending
  the turn; the Helm part runs in the foreground; see D6 (carried into the design
  at the fourth round, 52 F2).
- **45 R1 (option 2)** — a resume names its run by `seq`, and the wrapper refuses
  a run that is not waiting; the computation's `owner` result carries the `seq`;
  `make change-next` prints the computation in plain form; no `make resume`; see
  D1.

### Decisions at the fourth implementation round's triage

- **52 F1** — a stopped run's reading `reads` it and resolves nothing; a recovered
  stop is resumed with the one-run grant, and the resumed run supersedes it; a
  stop not recovered is settled by `resolves`; see D3, D6a.
- **52 F2** — D6's waiting rule corrected to 41 A1's; the third round's decisions
  recorded above.
- **55 O1** — `make next` and `make watch` renamed `make change-next` and `make
  change-watch`; see D1, D7.
- **55 O2** — the orchestrator gives `make change-watch` on starting any
  long-running unattended turn; the harness's panel deferred; see D7.
- **55 O3 (option 2)** — bash completion of change names and review kinds on the
  workflow targets is task 6.4 of this change, and a line of the proposal.
- **54 A1** — the background fetch runs with no shell redirect; see D6 and
  `change-validate` section 2.

### Decisions at the design revision after section 6

Made after section 6, from the pilot's first rounds and a run on Claude's cloud
environment, each under its decision's label:

- **G1** — the owner is interrupted only for judgement; reviews are no longer
  gates; triage records `## Next`; see D14, D16. **G1a** — planning asks nothing,
  and a plan needing a decision returns to design; see D8. **G1b** — the
  implementation cadence is a design decision; see D13. **G1c** — a round with no
  finding advances. **G1d** — the Codex closeout review stays; the owner's look at
  the pull request is outside the workflow.
- **G2** — the orchestrator relays and routes, and raises only its own
  observations; see D17.
- **G3, G7** — every run records its cost, its gap, and its cache hit;
  discussion turns stay one per decision; see D2, D19.
- **G4, G6** — each step's models in priority order, never Fable or Astra, no
  same-vendor fallback, the review falling back to Claude; see D11, D18.

### Decisions at the design review's triage (69)

- **69 F1** — planning emits `rounds`; the orchestrator copies each into a `round`
  line `by: plan` as the round starts; see D13.
- **69 F2, F3** — `## Next`'s fixed token, absence, governing file, legacy gates,
  and inconclusive validation; triage finishes without the owner only with nothing
  to dispose of; see D16.
- **69 F4** — the review's row, schema, harness-tagged sessions, unavailability
  signals, resume on the same model, and the table over `REVIEW_MODEL`; see D11,
  D12, D18.
- **69 F5** — the orchestrator forms no view; its routing reads enumerated; see D17.
- **69 F6** — per-field cost semantics, `usd_partial`, and a line's round; see D19.
- **69 F7** — archive cleanup after a validated closeout correction; see D14.
- **69 F8** — the pilot's Codex lines are a manual relay; one recorded branch
  decision; see D15 and Pilot.
- **69 F9** — planning keeps resuming the design session; `FRESH=1` on the owner's
  word; see D8.
- **69 F10, F11** — stale statements corrected; the permanent documents stating
  the gate model are in the proposal's impact.

### Decisions at the second design review's triage (70)

- **70 F1** — the next planned round is the first in the latest plan's `rounds` with
  an incomplete section; an amended plan maps only incomplete sections; with no
  mapping, the owner is asked once per round; no tracked copy of the mapping; see
  D13.
- **70 F2, F3, F5** — delta wording: `tasks.md` holds no distribution while
  planning's outcome carries it; advancing alone needs no owner-notes point either;
  the validation and inconclusive rules in requirement text.
- **70 F4** — closeout's and archive cleanup's entry checks read `## Next`; branch
  checks accept a recorded `branch` decision; see D12, D15.
- **70 F6** — the Codex entry pinned to `gpt-6-sol`; untagged markers are Codex;
  `REVIEW_MODEL` overrides the Codex entry only (superseded by 77 F3, below); see
  D11, D18.
- **70 F7** — tokens summed over a run's result events; a closeout bucket; the gap
  from the session's last turn; see D19.
- **70 F8** — the capability line and D16's interrupts.
- **70 F9** — closeout validation only when a path outside `openspec/` and `docs/`
  changed; see D14.
- **70 F10** — the pilot resumes on whatever tooling is committed then; see Pilot.

### Decisions at the fifth implementation round's triage

The round of sections 6a–6d, triaged from review 77, the owner's notes and the
orchestrator's observations (74), and validation 78.

- **77 F1 (option a)** — `common` denies the diff family's `--output` on `git
  diff`, `git show`, and `git log`; see D6, D11. Rejected: a process sandbox for
  the Claude reviewer (unverified on the owner's machine, and a worktree lacks the
  ignored `reviews/` the reviewer reads); rewording D11 to admit the shell route.
- **77 F3 / 74 O1 (option a)** — `REVIEW_MODEL` and `REVIEW_EFFORT` stay, as the
  owner's whole-entry override of a review run by hand, deliberately outside the
  table's policy and marked on the record and its line; see D11, D18. Rejected:
  deleting them (the owner wants to choose any model, Fable and Astra included,
  for a review run by hand); an environment variable for every wrapper step (an
  orchestrating session started from the same shell would inherit it); a flag on
  the script alone.
- **77 F2** — a planned round naming a section the task list lacks goes to the
  owner before it is recorded; a complete section is left out of its round; see
  D13 and `next_round`.
- **74 O2 (option 2)** — `scripts/run_change_step.py` is split into a
  standard-library package, `scripts/change_workflow/`, behind the same entry
  point, as section 6e, implemented after the pilot resumes. Rejected: in the fix
  commit (it would bury the fixes in a move); a follow-up change (closeout would
  describe a layout about to change).
- **After the fifth round, on the owner's word** — one target for a step's
  closing checks, `make check-change CHANGE=<change>`, running comment hygiene,
  the agent skills, the change's citations and task list, the change index, and
  the pinned strict validation, printing only failures and one pass line; the
  skills that ran them one by one name it. Every tool call replays the session's
  context, so six checks as six calls cost six replays (D19). Part of section 6e.
- **74 O4 / O5 (option a)** — validation and the review keep waiting for `make
  round-done`; running them while the owner reads is recorded as an open question
  in `parallel-change-workflows`' proposal, which meets the same problem. Rejected
  here: a worktree for validation and review, which changes the assumption both
  rest on, that the checkout is the commit.
- **74 R1** — a task editing `.claude/` is the orchestrator's, made on the owner's
  word before its section's session starts and committed by the session;
  `change-plan`, `change-orchestrate`, and `change-implement` say so.
- **74 R2** — a denial with no reason met a deny rule; see D6a.
- **74 R3** — a round line records `HEAD` as the round starts, and the round view's
  default base is that commit; see D9.
- **74 O3 / R4** — every step may run `make change-cost`; see D6.

### Decisions at the sixth implementation round's triage

The round of section 6e, triaged from review 101, validation 102, and the
orchestrator's observations (103); the owner had no notes (99).

- **103 R3 (option b)** — what a step may do after a denial follows the denial's
  reason. A call a deny rule refused is forbidden, and no other tool does it; a
  call denied in `dontAsk` mode for want of a rule may be done by a tool the
  step's rules allow for the same work, the step naming the substitute, and the
  orchestrator reads that as a gap, not a workaround; see D6a, D12. The rules
  already allow that work, and a row grants an edit only by path. Rejected: every
  substitute a workaround for the owner (steps stopped or hesitated over an edit
  their row allows, three times in the pilot); dropping the rule (a deny-rule
  denial would lose its stated "never").
- **101 F1** — the review that continues is the latest of its kind by record
  number, not by name; see D11.
- **103 R4** — the wrapper checks a step's outcome with the run's denials in it,
  and a rejected outcome keeps the step's message ahead of the reason; see D3.
- **102 V1** — the e2e-vm failure is not this change's; the fix commit's
  validation reruns it, and the owner decides after it whether the buyer CLI's
  duplicate `settlement contact` registration becomes a change of its own or
  joins an existing one.
- **103 R1, R5 / R6, R7, R2** — pilot gaps recorded on task 7.3.

## Risks / Trade-offs

- **Relayed discussions cost a second rendering of every message**, and the relayed
  text could drift from the step's. Accepted for the context it saves; the pilot's
  design discussion measures it. If it is too slow or drifts, discussions move into
  the orchestrator's session (D2's first rejected option), relying on D10 to survive
  compaction.
- **Allow-lists need upkeep.** The orchestrator proposes each gap with its rule; the
  pilot's denials seed the table.
- **A step may work around a denied tool rather than stop.** D12 tells it not to;
  the transcript shows when one did.
- **A background command a step started may not survive the step ending its turn.**
  Validation's `make fetch-e2e-logs` runs in the background while the Helm part
  runs; if validation stops to ask the owner, the fetch may end with the process.
  It can be restarted from its `E2E_AFTER_RUN` id, which validation already records;
  the pilot confirms whether it needs to be.
- **`--resume` with different allow rules** is assumed to apply the new rules to the
  resumed turn; the pilot confirms it.
- **Advancing without the owner moves work along on conditions alone.** A
  condition the computation gets wrong carries the change a step too far before
  anyone looks; each advance is a line in the log, and the next touchpoint shows it.
- **A Claude review of Claude's work loses the second model's reading.** The record
  names the reviewer, so the owner can ask for a Codex round when one is available.
- **Every turn of a discussion replays its session.** Accepted for one decision per
  turn; D19 measures it.

## Open Questions

- **Loading less per session.** Each step loads every guidance document `AGENTS.md`
  lists, whatever the skill needs. Loading per skill would lower every turn's replay
  but changes how `AGENTS.md` lists the guidance. Revisit when D19's data shows
  session openings and replay dominate the cost.
- **A longer prompt-cache lifetime for discussion steps.** It costs more to write
  and survives slower replies. Revisit when D19's record of cache misses and their
  gaps shows how often a longer lifetime would have hit.

## Pilot

`fix-resource-pool-provider-at-creation`, from `ready for design` through archive
cleanup, on this change's branch (D15). The pilot records, for this change's
triage: every `stopped` outcome and its denials, every `orchestrator` line and the
transition the script could not classify, the relay's latency on the design
discussion, and whether validation's background fetch survived a question.

The pilot's lines from seq 19 to its round-2 triage ran as Codex tasks relayed by
hand, outside the wrapper — no session, denials record, or cost — while Claude was
at its usage limit; they are evidence about limits and a cross-harness relay, not
about the wrapper. The owner continues the pilot outside this session to its next
workflow stage, then resumes it from the orchestrating session on whatever tooling
is committed then: the section-6 tooling, if the revision's sections are not yet
implemented, or the revised tooling if they are (69 F8, 70 F10). Section 7 records
which of its evidence came from which flow. Evidence for D16 to D19 — advancing
without gates, the relay without judgement, models and fallback, and cost — comes
from whatever runs on the revised tooling: the pilot's later steps if it is still
open, this change's own remaining rounds, and the next change orchestrated.
