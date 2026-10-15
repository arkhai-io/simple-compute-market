## Context

Each step of a change is a leaf skill under `.agents/skills/`, started by the owner
through its `make` target. Every target but one opens an interactive Claude Code
session: `make design`, `make implement`, `make triage`, `make validate`,
`make closeout`, and `make archive-cleanup` each run `claude "/change-<step>
<change>"`. Only `make review` runs unattended: `scripts/run_change_review.py` runs
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
changes, no gate removed, no shareable logs, and no change to what a step checks.

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
delegated.

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
so relaying costs a second rendering of each message; that is the price of keeping
the loading out of the top-level session. When relaying gets in the way, the owner
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
(with `blocked_on`), and `stopped` (with `reason` and `denials`). The orchestrator
adds `round` lines (D13) and `orchestrator` lines (D14) through the wrapper's
`note` operation, so the wrapper is the log's only writer. Each line keeps the
step's `message`, so a restart shows the last thing a step said without parsing its
transcript.

```jsonl
{"seq":12,"at":"2026-10-21T09:15:40Z","step":"orchestrator","outcome":"round","sections":[[0]],"by":"owner"}
{"seq":13,"at":"2026-10-21T10:58:22Z","step":"implement","session":"9c07…","commit":"e2d81b4a","sections":[0],"outcome":"returned","return_to":"design","message":"Task 0.4: patch has no provider field; refusing it needs a decision the design does not make.","evidence":"tasks.md §0 notes"}
{"seq":20,"at":"2026-10-22T16:31:07Z","step":"validate","session":"51aa…","commit":"7f3c6e90","outcome":"question","message":"Helm part failed: a retained volume carries resource-policy keep. Remedy: delete it.","awaiting":"environmental remedy"}
{"seq":22,"at":"2026-10-22T17:45:10Z","step":"review","session":"codex:019a…","commit":"7f3c6e90","outcome":"stopped","reason":"exit 1: codex authentication expired","denials":[]}
```

The log holds only what the files cannot: session ids, the owner's round
agreements, and the last outcome. Where the log and the change's files disagree —
a status edited by hand — the files win, and the orchestrator says so. A `returned`
line does not move the index status: the owner confirms the return, and the step
then started sets the status, as now.

Rejected: the final answer only, kept in the orchestrator's context — a restart
loses session ids and round agreements. The step writing its own outcome file — a
crashed or refused run writes nothing.

### D13 — The owner agrees each implementation round before it starts

How many sections a session implements, and how many make a round before the round
view, validation, review, and triage, is decided by the owner with the orchestrator
before implementation, and recorded as a `round` line. A round of several sections
runs back to back with no stop between them; a small change is usually one round of
every section up to closeout. The plan describes what to change and is agnostic of
sessions, rounds, and whether a coding harness implements it at all: a section is a
coherent, verifiable slice, sized by what it changes and what proves it. One section
per session is not enforced; the risk of a session degrading as it grows stays
advice in `change-implement`, for the owner to weigh.

Rejected: round breaks written into `tasks.md` at planning, alone or as a default
the owner overrides — that puts session logistics into a plan that should not know
about them.

### D14 — A script computes the next step; the orchestrator is its backstop

`scripts/change_next_step.py <change>` reads the change's index row and status, its
`Depends on`, `reviews/` and their triage gates, `tasks.md`, the log, and the open
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
  release (D5a). The
orchestrator runs that step and never routes on its own reading. The transitions
are already fixed by each skill's entry check and handoff; in code they are
testable under `scripts/tests`, and the owner can run the same command by hand.

When the script fails — an error, a state it cannot classify, files and log that
disagree — the orchestrator receives its output and the inputs it read, works out
what happened, and either decides, when the matter is routing or recovery (a step
that died before writing an outcome, a status set by hand), or raises it with the
owner, when the answer would pass a gate, settle a design question, or change a
status. Either way it records an `orchestrator` line with what it decided and why;
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
`scripts/change_steps.toml`, which the wrapper reads. The rules are specific to
Claude Code, so they live with the wrapper rather than in the harness-neutral
skills. An interactive run is unaffected: the owner's own permission settings apply,
with prompts.

| Step | Allowed | Denied |
|---|---|---|
| design, plan | read; edit `openspec/`, `docs/`; the pinned OpenSpec validator; `make check-*`; for a prerequisite (D5), `git worktree add` on a new branch from dev and edits under that worktree's `openspec/` | commits of code, any push |
| triage | design's, and implement's, since it fixes what the owner accepts and commits | any push |
| implement | edit the repository; `make` test, lock, and check targets; `uv run`; `git add`, `git commit`; the Agent tool | any push, `make push-branch`, `make run-e2e` |
| validate | read; write `reviews/NN-validation.md` only; `make validate-*`, `push-branch`, `run-e2e`, `round-e2e-baseline`, `fetch-e2e-logs`; `gh run list`, `gh auth status`; `docker`, `kubectl`, `helm` | editing tracked files, `make lock`, commits, any other push |
| closeout | edit `openspec/`, `docs/`; `openspec archive`; `make check-*`; commits | code edits, any push |
| archive cleanup | edit the index; write `reviews/pull-request.md`; commits | any push, creating the pull request |

The allow-lists turn each skill's "never" lines into rules the harness enforces:
validation's "never changes the commit" stops being an instruction only. A run that
needed a denied tool ends `stopped` with its reason; the wrapper records the
denials from the run's `permission_denials` (D3). The orchestrator reads each
against the step's row and the skill: a gap in the list gets a proposed rule — grant
once by resuming with it, or add it to the table as a tracked change for the owner
to commit; an action the skill forbids is a finding, and the denial stands; anything
unclear goes to the owner. Edits to the table are proposed, never silent, and
logged.

Rejected: auto mode — what a step may do would rest on a classifier's call per
action, unreviewable in advance. A permission-prompt tool routing each prompt to
the orchestrator — an MCP server to build, and an hour-long validation blocked on a
prompt while the owner is away, where a denial ends cleanly and resumably. Bypass —
validation drives Docker, the cluster, and the push.

### D7 — The wrapper records the event stream, and the owner is notified when it is their turn

The wrapper runs each step with `--output-format stream-json --verbose`, writes the
stream to `reviews/transcripts/NN-<step>.jsonl` beside the review transcripts, and
keeps a short progress file of each tool call and its time. The orchestrator
answers "how is it going?" from the progress file; the owner can read it in another
terminal. When a step ends `question` or `stopped`, or a long step finishes, the
orchestrator sends a push notification; Remote Control lets the owner answer from
elsewhere.

Rejected: outcomes only — "is it stuck?" can only be answered by waiting.

### D8 — Planning resumes the design session; closeout and archive cleanup are delegated

Planning resumes the design step's session, after the design review and its triage,
since `change-plan` is better written with the design's context; it reads the gate
from the files as its entry check requires, and is a discussion step. When the
design session has grown large, the orchestrator offers a fresh one. Closeout and
archive cleanup are delegated: closeout's points put to the owner become `question`
outcomes, and a part that needs a code edit becomes `returned` to implementation.
Archive cleanup drafts the pull request; the owner creates it.

### D9 — The orchestrator opens and closes the round view

After a round's sections are committed, the orchestrator runs `make round-view` in
its own session, under the owner's permissions, which pushes the round and
dispatches the pipeline. It waits for the owner's word. When the owner gives notes
on the round, the orchestrator saves them verbatim as the change's next numbered
record, `reviews/NN-implementation-owner.md`, which triage already takes as the
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

### D12 — The skills change how they ask and report, not what they check

When a skill runs through the wrapper, every "stop and ask the owner" ends its turn
with a `question` outcome; a denied tool ends it `stopped` with its reason, never
a question or a workaround; and its last turn ends with an outcome matching
`scripts/change_outcome.schema.json`. Interactive use is unchanged. Beyond that:

- `change-plan` sizes a section as a coherent, verifiable slice rather than to one
  session, and drops "one section per session" from its handoff (D13).
- `change-implement` implements the sections it was given, drops §8's question,
  and keeps the warning about a growing session as advice (D13).
- `change-design` gains the blocked-on-prerequisite path (D5, D5a).

### D15 — The pilot runs on this change's branch

`fix-resource-pool-provider-at-creation` is worked through every step by the
orchestrator on this change's branch, once the orchestrator's sections are
committed; each step's branch check stops at the mismatch and the owner confirms.
Both changes archive here and land as one pull request. This is a deliberate
exception to one change per branch: the pilot is this change's own end-to-end
evidence, and its lessons reach this change's triage and closeout directly.

Rejected: landing the orchestrator first and piloting afterwards — the orchestrator
would close out with no evidence it works. A pilot branch stacked on this one — a
second branch to keep current, for a small pilot.

### Never passing a gate

The orchestrator passes no gate and answers no design question; every gate and
question reaches the owner. Practice may show some gates safe to soften; that is a
later decision, made on the pilot's evidence.

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

## Open Questions

None.

## Pilot

`fix-resource-pool-provider-at-creation`, from `ready for design` through archive
cleanup, on this change's branch (D15). The pilot records, for this change's
triage: every `stopped` outcome and its denials, every `orchestrator` line and the
transition the script could not classify, the relay's latency on the design
discussion, and whether validation's background fetch survived a question.
