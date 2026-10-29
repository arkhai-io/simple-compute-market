---
name: change-plan
description: Write or amend the implementation plan — tasks.md — for an OpenSpec change whose design review's triage advanced it, its sections coherent, verifiable slices ordered by the design's implementation cadence, ending with the closeout task, and report the cadence's mapping onto the sections. Asks the owner nothing. Use when a change is `ready for planning` or `in planning` in openspec/changes/README.md, or when the owner says "plan <change>" or "proceed to planning", typically continuing the design session.
---

# Planning an OpenSpec change

Design settled what the change does. Planning settles how it is delivered: the
sections, their order, the files each decision touches, the evidence each section
owes, where each decision is documented permanently, and the closeout. Planning
makes no design decisions.

This skill usually runs in the session that held the design discussion, because
that context makes a better plan. But the plan is read by implementation sessions
that start fresh and see only the files. Everything the plan relies on must be in
the change's files before a task depends on it.

Planning asks the owner nothing: the owner reviews the design, not the plan, and
the order of the plan's sections is the design's implementation cadence. It has two
outcomes: the plan is written, its sections ordered by that cadence, and the
change is ready for implementation; or planning finds a decision the design does
not make, or a cadence its sections cannot be cut to, and returns the change to
design.

## Running unattended

Run interactively, as most runs are, this section does not apply but for the
outcome it describes, which an interactive run records itself ("Running
interactively"); nothing else in the skill changes.
When this skill runs through `scripts/run_change_step.py` —
`make plan UNATTENDED=1`, or the orchestrating session — nobody can answer in
the session, and every turn ends with an outcome matching
`.agents/change-outcome.schema.json`, whose `message` the owner reads as written:

- **A stop for the owner is a question.** Wherever this skill says to stop and
  ask, tell, or wait for the owner, end the turn with `question`: `message` says
  what you found, the options, and your recommendation; `awaiting` names what you
  need. The owner's answer resumes this session; carry on from it.
- **A denied call stops the step only when it cannot go on.** Run one command per
  Bash call: a chained command runs only when every command in it is allowed, so
  if a chained command is denied, run its commands one call at a time. If a single
  command or any other tool call is denied, finish every part of the work that does
  not depend on it. If the step cannot complete without that call, end with
  `stopped`, `reason` naming that exact call and why the step needed it, and
  `denials` listing the calls as you saw them; the wrapper replaces them with the
  run's own record. Otherwise go on and end as the step ends: the wrapper records
  the denial on the outcome whatever it is, and the orchestrating session reads it
  before the change moves on. One denied call is not a denied tool: never report
  the tool as not allowed. A call a deny rule refused is forbidden: no other tool
  does it. A call denied because no rule allows it — the harness reports it as
  don't ask mode — may be done instead by a tool this step's rules allow for the
  same work, such as the Edit tool for a shell write or Read or Grep for a shell
  read; name the substitute in your message. Never ask about a denial as a
  question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **Git runs in this checkout.** Run Git in the current checkout, never with `-C`:
  the step already runs in the checkout it reads, and no rule allows `git -C`, since
  a wildcard after `-C` would also span a push. Run Make here too, never `make -C
  <a checkout>`: `-C` names only a subdirectory a skill names.
- **The end is an outcome.** Once the plan is written and checked, its report
  (section 6) written, and the status set and the plan committed and pushed
  (section 7), end with `finished`, its `message` the report, `next` the plan's
  next round, `{"step": "round"}`, and `rounds` the cadence's mapping onto the
  sections (section 7) — or, when the plan adds nothing to implement, `next` the
  pre-closeout review, `{"step": "review", "kind": "pre-closeout"}`, and no
  `rounds`. Planning asks no question.
- **A return to design is proposed, not made.** When planning exposes a design
  question (section 3), or finds no cadence it can cut its sections to (section 4),
  end with `returned`, `next` `{"step": "design"}`, and `evidence`
  naming where you recorded what planning found; leave the status as it is. The
  owner confirms the return, and the design step then sets the status. Before
  ending, commit what planning has written — what `design.md` gained, the plan so
  far — as one work-in-progress commit naming the change and why it returns, and
  push it with `make push-branch`: no session is left to commit it, and a dirty
  checkout blocks every later step's guarded push. A stop, by contrast, commits
  nothing: its work waits uncommitted for the resumed session, and one stopped
  because a repository guard refused or `HEAD` moved leaves the checkout as it
  was.

## Running interactively

Run in an interactive session — `make plan` without `UNATTENDED=1`, or the slash
command — no wrapper records the run, so its last act records the outcome it would
end with unattended, as "Running unattended" gives it, `rounds` included:

```text
python3 scripts/run_change_step.py record <change> plan --outcome '<the outcome, as JSON>'
```

`record` checks the outcome against `.agents/change-outcome.schema.json` and
appends it to the change's workflow log with the session's id, `HEAD`, and
`interactive: true`, and the next-step computation routes on it as on an
unattended run's. It reads the session's id from `CLAUDE_CODE_SESSION_ID`, which
`printenv CLAUDE_CODE_SESSION_ID` shows; where the variable is unset it refuses,
and `--session <id>` gives the id. Record the outcome the session ends with —
`finished` or `returned` (sections 3 and 4) — never a stop, which the owner,
present, settles in the session: a recorded stop would wait for a resume only the
wrapper makes. When `record` refuses, correct what it names
and run it again. A session closed before it records leaves planning in progress,
even once the status says `ready for implementation`: only the plan's outcome
carries its exit and its `rounds`, so the computation names planning again, to be
resumed, or its outcome recorded with the command above.

## 1. Check that planning may start

Read the evidence from the files and the workflow log, even if this session held
the design discussion: the session's memory of a triage can be out of date, and
reviews and triage may have happened elsewhere. Read the change's row in
`openspec/changes/README.md` — status, `Depends on`, notes. Then confirm:

- `python3 scripts/change_next_step.py <change>` names `plan`, whatever the status
  says: the exit the design review's triage recorded, or the owner's direction to
  planning — a confirmed return of the change to planning, or the waiver of another
  design review for what the design step settled after a confirmed return to
  design, which the orchestrating session records on the owner's word as a
  direction naming no run, with a ledger line. `python3 scripts/run_change_step.py
  log <change>` shows the line the computation's reason names. Commit a waiver's
  ledger line with the plan (section 7). Whatever else the computation names — a
  design review, a triage in progress, the owner — is the step that comes first,
  and its reason says why.
- No dependency in the row's `Depends on` gates `design` or `planning` and is
  unlanded. A dependency gating implementation does not stop planning; the plan
  notes it.

If any of these fails, stop and tell the owner why — unattended, end `stopped`
with the reason, since planning asks no question.

Set the change's `Status` to `in planning`.

## 2. Load what the plan needs

If this session did not hold the design discussion, read `AGENTS.md` and every
document it requires first. Then read, whether or not you have seen it before —
the files are what the implementer will see:

- the change's `proposal.md`, `design.md`, `specs/`, and current `tasks.md`;
- `openspec/README.md#plan-closeout-requirements`, and `openspec/config.yaml`'s
  rules for tasks;
- `openspec instructions tasks --change <change>` for the tasks template;
- the permanent spec and architecture companion of every capability the change
  touches, and `openspec/specs/README.md`;
- the code each decision changes: enough to name the files, the package
  boundaries, and the existing tests a section extends;
- another change's records, where a section rests on them — a dependency's
  validation evidence, say — wherever `python3 scripts/find_change.py --records
  <change>` says they are: this checkout, or, from a change's clone, the owner's
  workspace, which holds the history of every cleaned-up change.

## 3. Record the conversation before planning from it

Read `design.md` as an implementer would. Wherever a task will depend on something
the discussion settled but the file does not say — a rationale, an example, a
rejected alternative, a constraint the owner stated — write it into `design.md`
first, as part of the decision it belongs to. This is recording, not deciding.

If planning exposes a question the design did not answer, it is a design decision,
and no review has seen it. Planning stops: never settle it inside a task, and never
plan on an answer the design review did not cover.

1. Tell the owner what planning found and why it stopped. Interactively, set the
   change's status back to `in design` and go on with steps 2–4 in this session.
   Unattended, end the turn `returned` instead, as "Running unattended" says, and
   leave the status: the owner confirms the return, and the design step sets it.
2. Settle the question as `change-design` settles a decision, and record it in
   `design.md`.
3. Ask the owner whether the change needs another design review for it, or whether
   they waive the review. A waiver is the owner's call. Record it as a ledger entry
   with `"review": "plan"`, the decision as `finding`, lens `readiness`, basis
   `judgement`, and a null severity, stating what was waived and why; this session
   goes on to plan, and its outcome names the plan's exit. When the owner wants the
   review instead, commit what `design.md` gained, as section 7 commits the plan,
   and end the session as a return: record `returned`, `next` `{"step":
   "design"}`, `evidence` naming the decision in `design.md`, then the owner's
   confirmation of it, directing the review of what this session settled rather
   than design, the seq being the one `record` printed:

   ```text
   python3 scripts/run_change_step.py note <change> orchestrator --by owner --resolves <seq> --next review --kind design --decision "return confirmed: another design review of <the decision>" --reason "<the owner's words>"
   ```

   Planning starts afresh once that review's triage names it.
4. With the review waived, set the status to `ready for planning` and resume
   planning.

## 4. Write the plan

**Preserve history.** Never delete a checked task, rewrite what it says was done,
or change its completion state. When the reviewed design changes what follows from
a completed task, amend it with a correction note, or append a task that carries
the correction. An unchecked task the reviewed design superseded may be replaced;
say at the top of the replaced section that it was replanned against the reviewed
design.

**Sections are slices.** Each section:

- opens with one line on what it delivers and the decisions (`D<n>`) and
  requirements it implements;
- names the files and packages it touches;
- is a coherent slice that can be verified, sized by what it changes and what
  proves it: a section that crosses several package layers, or whose tasks one
  verification point cannot prove together, is split. `tasks.md` says nothing of
  sessions or rounds: the design's implementation cadence settles them, and
  planning reports its mapping onto the sections in its outcome (section 7),
  never in the plan, which is agnostic of whether a coding harness implements it;
- ends at a verification point — the focused suites that prove it, each named with
  its level as `docs/development/TESTING.md` defines them (unit, library
  integration, application integration through the typed client, system), at the
  lowest level that can prove the behavior; `make test`; and the packaging check
  when it changes a dependency or lock. A section whose title promises a behavior
  of the running application — publication, a write refused — includes at least one
  application-integration case for it, not only lower-level evidence of its parts;
- names the end-to-end scenarios (pytest markers in `e2e-tests/`) that exercise
  the section's behaviour once deployed, or says that none does and whether one is
  owed. Validation runs the Helm checks and the pipeline on every commit; it reads
  this list to report whether the pipeline's result is evidence for the section;
- names in its verification only evidence an implementation session can produce.
  Evidence only a push produces — a CI workflow run such as `tests.yml`'s, which a
  change branch's push does not trigger — goes on its own `Owed by validation:`
  line of the verification task, beside `End-to-end:`, giving the workflow, the
  job, and what the job must show:

  ```
  Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
  `azure/setup-helm` installs v4.3.0, and `make -C helm test-render` prints
  `helm v4.3.0` before the first render and passes.
  ```

  It gates no task: once the section is complete, every validation of the change
  dispatches the workflow and judges the job, and a round advances only on a
  passing validation. Only a workflow `scripts/ci_evidence.py` lists can be owed,
  since validation dispatches no other; owing another is a design question
  (section 3).

**Order by real dependencies, then by the cadence.** Lower layers before the layers
composing them — foundation kit before kit before domain before composition root —
and focused behavioral verification before documentation work, per the task rules
in `openspec/config.yaml`. Within that, number the sections in the order of the
implementation cadence `design.md` records, each round's sections before the
next round's, so each round is a run of consecutive sections. When the sections
cannot be cut that way — a round's work depends on a later round's — the design
must decide: planning returns the change to design (section 3). A design from
before the cadence was a design decision records none: plan without a mapping,
and say so in the report; the owner is asked for each round as it starts.

**Every task is traceable.** Each names what it answers to — a design decision, a
delta requirement, or a repository obligation such as the verification, packaging,
promotion, and closeout work `openspec/README.md` and `openspec/config.yaml` require,
cited — and the evidence that proves it. A feature task with nothing to trace to is
either missing from the design or not part of this change.

**Give edits under `.claude/` to the orchestrator.** Every step is denied edits
there, so a task that changes the step table or the project's Claude Code
settings says it is the orchestrator's, made on the owner's word before the
section's session starts, and that the session commits it with its section; the
rest of the section stays the implementer's.

**Name the permanent destinations.** For every entry under the proposal's
`Knowledge to promote`, confirm or correct its destination and name it exactly —
file and heading — including `openspec/specs/README.md` for a new capability or
companion, and `docs/development/ARCHITECTURE.md` where the design says so.
Provisional destinations the design delegated to planning are settled here; tell
the owner which you moved and why.

**End with the closeout task**, its eleven parts from
`openspec/README.md#plan-closeout-requirements` in that order, each made specific
to this change:
the roadmap goal and gap row it closes, its index row, the end-to-end scenarios
that exercise it, the permanent documents it promotes, and the archive's merge or
`--skip-specs`. Dependents are released at archive cleanup, not by a closeout
task.

## 5. Check the plan

Before presenting it:

- every decision in `design.md` and every delta requirement maps to at least one
  task, and every task maps back to a decision, a requirement, or a cited
  repository obligation;
- no open question has its answer prescribed by a task
  (`openspec/README.md#open-questions-and-prescribed-tasks`);
- every section has a verification point, its covering end-to-end scenarios or a
  statement that none covers it, and a size its verification point can prove;
- `make check-change CHANGE=<change>` reports no failure but its citations
  check's, which may name only files the change will create. Among its checks,
  the strict OpenSpec validation passes, and the task-list check holds every
  numbered task under its own section's heading, which is how every later step
  reads the plan.

## 6. Report the plan

Do not paste `tasks.md`, and ask nothing: the report is for the owner to read, not
to accept. Show:

- each section in one line: what it delivers, the decisions it implements, its
  verification, and anything that makes it large or risky;
- the decision-to-section map, so the owner can see nothing was dropped;
- the rounds and sessions of the cadence, by section;
- what you recorded into `design.md` in step 3;
- the permanent destinations you settled or moved;
- dependencies that gate implementation.

Run interactively, the owner may still redirect the plan as they read it. A change
to the order of the sections, or to the rounds they fall in, is a change to the
cadence, which is the design's: it returns the change to design (section 3). When
the owner changes or reverses another recommendation of yours — a split, a
destination — append a line to the change's `interventions.jsonl` with
`"review": "plan"`, the affected section as `finding` (`§3`), lens `scope` or
`architecture`, basis `judgement`, and a null severity, and say that you did.

## 7. Hand off

When the plan is written and checked, set the change's `Status` to
`ready for implementation` yourself. Planning has no review of its own: its sizing
and closeout are examined by the first implementation review.

Commit the plan as one commit — `tasks.md`, what you recorded into `design.md`,
the index row, and the ledger lines planning wrote or the waiver left — whose
message names the change and says it is planned. Then push it with `make
push-branch`, the guarded push of exactly `HEAD`; if it refuses, stop and report
its reasons.

Map the cadence onto the sections: a list of rounds, each a list of the sessions
that implement it, each a list of section ids in order —
`[[[1, 2]], [[3], [4]]]` is a round of sections 1 and 2 in one session, then a
round of 3 and 4 in a session each. Name every section before the closeout
section. It is the `rounds` of your `finished` outcome, which the wrapper logs on
the plan's line, or `record` does for an interactive run ("Running interactively"),
where the next-step computation reads it; give it in the report too. An amended plan
maps only its sections not yet complete, leaving the rounds already recorded as
they are.

Implementation starts in a new session with `change-implement`, round by round as
the mapping gives them.
