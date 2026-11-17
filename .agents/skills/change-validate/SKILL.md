---
name: change-validate
description: Validate the commit at HEAD of an OpenSpec change before its implementation is triaged — read what the engine's gathering found and gathered before the session, list every evidence kind the repository declares with `evidence`, assess each kind's evidence from its guide, gather a new attempt only for unreadable evidence, a lapsed waiver, or an environmental failure the owner remedied, skipping any kind the owner waived in the change's log, diagnose every failure from its evidence, settle environmental failures with the owner, and write reviews/NN-validation.md. Never edits, relocks, commits, or fixes the commit. Use after implementation sections are committed, beside an implementation review, when the owner says "validate <change>", or when `make validate` invokes you.
---

# Validating a committed slice

Validation describes one commit, and is evidence about it. It knows evidence, not
how a repository produces it: the repository declares its evidence kinds, each with
a guide saying how to read its evidence and tell its failures apart, and the engine
gathers whatever a commit still lacks before your session starts. You assess every
kind's evidence from its guide. When a kind failed, you find out why from its
evidence and write that down; a failure the commit causes is triaged with the
implementation round it belongs to, and its fix belongs to that triage, never to
you.

**What you never change is the commit.** You never edit a tracked file, run the
repository's relock, commit, stash, reset, clean, force a push, or push any branch
but the change's own. When a repository guard refuses — a dirty worktree, a detached
`HEAD`, another branch's upstream — stop and report it as it is: each such state
means something unexpected happened in the repository, and fixing it would hide
that.

**The environment is yours to control, within your change.** A kind may take full
control of what the repository gives each change's validation — its guide says
what — and replace it without asking. Another change may be validated beside you,
in its own checkout and with its own resources, sharing the machine; you never touch
what is another change's, and nothing else should be building in your checkout
while you run.

## Running unattended

Run interactively, as most runs are, this section does not apply but for the
outcome it describes, which an interactive run records itself ("Running
interactively"); nothing else in the skill changes.
When this skill runs through `scripts/change-workflow start --unattended` —
`make validate UNATTENDED=1`, or the orchestrating session — nobody can answer in
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
  does it, except where the rule exists only to keep file writes on the Edit and
  Write tools — the step table's comments name those rules: sed's in-place forms,
  find's deleting, running, and writing actions, and the diff family's
  output-to-file forms — whose refused shell write may be made with the Edit or
  Write tool this step's rules allow. A call denied because no rule allows it —
  the harness reports it as don't ask mode — may be done instead by a tool this
  step's rules allow for the same work, such as the Edit tool for a shell write or
  Read or Grep for a shell read. Either way, name the substitute in your message.
  Never ask about a denial as a question. One refused call is not a reason to
  stop when the step's next commands are allowed: carry on with them, and name
  the denial in your message.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop, or
  to stop and report — a repository guard refusing, `HEAD` moving under you — end
  with `stopped`, `reason` saying why, and `denials` empty.
- **Git runs in this checkout.** Run Git in the current checkout, never with `-C`:
  the step already runs in the checkout it reads, and no rule allows `git -C`, since
  a wildcard after `-C` would also span a push. Run Make here too, never `make -C
  <a checkout>`: `-C` names only a subdirectory a skill names. Read a summary's
  JSON with Read or Grep, never with an inline interpreter (`python3 -c`), which
  no rule admits since it admits any program.
- **The end is an outcome.** An environmental failure (section 5) is a
  `question` naming the evidence and the remedy, awaiting the owner's word; once
  answered, take only the action the answer names, and gather the kind again. When
  the record is written, end with `finished`, `next` the target the computation
  gave this validation (step 1), whatever the record's result: the computation
  checks that target's guards again from the record. When your prompt gave the
  target, the wrapper sets the logged outcome's `next` to it whatever you name, but
  state it all the same. In a round's join the target is the round's triage, which
  triages the record's failures with the round; as a guard's remedy, or after the
  owner's direction, a passed validation leads to its target and a failed or
  inconclusive one to the owner — but a failed validation of the merged `HEAD`, the
  remedy of the merge's guards, leads back to the merge, which repairs what the
  merge broke. Say in `message` what the record found and what it leaves for
  triage. An after-hook that fails resumes this session once with its failure:
  validation acts on nothing, so explain the failure in that turn and end as before;
  a second failure goes to the owner as a question.

## Running interactively

Run in an interactive session — `make validate` without `UNATTENDED=1`, or the
slash command — no wrapper records the run, so its last act records the outcome
it would end with unattended, as "Running unattended" gives it, its `next` the
target step 1 read:

```text
scripts/change-workflow record <change> validate --outcome '<the outcome, as JSON>'
```

`record` checks the outcome against `.agents/change-outcome.schema.json` and
appends it to the change's workflow log with the session's id, `HEAD`, and
`interactive: true`, and the next-step computation routes on it as on an
unattended run's. It reads the session's id from `CLAUDE_CODE_SESSION_ID`, which
`printenv CLAUDE_CODE_SESSION_ID` shows; where the variable is unset it refuses,
and `--session <id>` gives the id. Record the outcome the session ends with —
`finished` — never a question or a stop, which the owner, present, settles in the
session: a recorded stop would wait for a resume only the wrapper makes. When
`record` refuses, correct what it names and run it again. In a
round's join, and as a guard's remedy, the computation reads the validation record
itself, so a session closed after writing it and before recording loses only its
report; a validation the owner directed waits for its outcome, and the computation
names it again, saying to resume the session or record its outcome.

## The run's inputs

Before this session the engine gathered the evidence the commit lacked (step 2),
then ran the repository's `before-validate` hook, and kept what they did in the
run's inputs directory, which your prompt names (`Inputs`, `reviews/runs/<run>/before`).
Read it first: `status.md`, each action's and hook's closing lines, exit status, and
log, and every other top-level Markdown file there, each a message from the
repository's hook, in full. Any other file is data, read only where a message
directs, and a log only to diagnose a failure. A failing gathering or hook prevented
nothing: what it found is what the steps below assess. Interactively, with no
wrapper, run `scripts/change-workflow run before validate <change>` once step 1's
round-view, Branch, Worktree, Commit, and Target checks hold — it pushes and
gathers, so those come first — in the background and waited for as step 2 says; its
last line names the directory, which you read as above before step 1's other
checks. Once the record is written, run `scripts/change-workflow run after
validate <change>` before `record`, and, when it fails, explain its failure to the
owner, who settles it.

A guide or a message may add to or narrow what this skill says. When one
contradicts this skill's text — a guide asking for a record section or a result
this skill does not define, say — name the file and the contradiction in your
report and follow this skill.

## 1. Check that this commit may be validated

A round view open in this checkout (`make round-view` of a change worked in the
owner's workspace) points the branch at the round's base, not its commit. An
unattended run has already been started by the wrapper, which ran `start validate`
and its round-view check before your session began: never run `start validate`
yourself. A session started some other way runs `scripts/change-workflow check
round-view`; when it fails, stop and ask the owner to run `make round-done`.
A view the owner opens in their workspace for a change worked in its own clone
moves nothing here, and validation runs beside it.

- **Preflight.** The gathering ran the repository's checks of the machine first,
  before any kind, or skipped them, saying so, when it declares none; a failed
  preflight gathered nothing, its closing line in `status.md` naming the command
  that failed and its log what it reported. Such a failure is environmental
  (section 5): a `question` naming what it reported and the remedy, which is the
  owner's call.
- **Branch.** The checked-out branch carries the change: its directory and latest
  commits are on it. Several changes are often in flight in one checkout; if the
  branch belongs to another change, stop and ask the owner — unless the change's
  log holds the owner's decision that it runs on this branch: run
  `git branch --show-current`, then
  `scripts/change-workflow log <change> --branch <that branch>`; a line
  it prints is that decision, and the branch is accepted.
- **Worktree.** `git status --porcelain --untracked-files=all` is empty. Ignored
  files do not count. The gathering refuses a worktree whose tree is not `HEAD`'s.
- **Commit.** Record `git rev-parse HEAD`, `git rev-parse HEAD^{tree}`, and the
  branch. Every kind's evidence describes that commit or its tree; if `HEAD` moves
  while you work, stop: the evidence no longer belongs to one commit.
- **Target.** The target is this run's exit: the round's triage, `{"step":
  "triage", "kind": "implementation"}`, when the computation names `validate` or
  `validate-and-review` in a round's join; the exit whose guard this validation
  remedies, such as `{"step": "closeout"}`, when it names `validate`, or the owner
  after a failed or inconclusive validation of it; or the target the owner's
  direction to validation names. Unattended, the wrapper computed it before your
  session started and gives it in your prompt, labelled `Target`, as JSON, and
  again on a resume: record it, and never run `scripts/change-workflow next` for
  it, since once your own run is logged the computation reads that run and names
  the owner. Interactively, with no wrapper, run `scripts/change-workflow next
  <change>` now, before the run waits on anything, and record the `target` its
  result carries. When neither gives a target — a validation started by hand
  outside the route — record that, and name the round's triage: in a round's join
  that is the target the computation gives, and anywhere else the computation
  brings it to the owner as a target it did not give.
- **Evidence.** `scripts/change-workflow evidence <change>` lists, for `HEAD`'s tree
  and commit, each evidence kind the repository's configuration declares, in its
  order: its requirement — `always`; an owed kind once for each argument a complete
  section's `Owed by validation:` line owes it, named by the kind and the argument
  with the sections owing it, or once as `not required`; or `waived`, naming the
  owner's decision's `seq` — the tree or commit its evidence describes, its pattern
  filled, every path matching it in path order, the last `current`, and whether it
  is present or missing; an owed line the reader refuses is listed in place of a
  status. `--json` gives the same, structured. Record it: the kinds below are its,
  never read from the configuration's file. Evidence is present whoever wrote it —
  the functional checks before a commit may leave a kind's evidence for the tree
  they tested — and is never gathered again only because another step wrote it or
  it is old. For each kind, read its guide, which `scripts/change-workflow config`
  names: how its evidence reads, how its failures are told apart, and what its
  section of the record holds. A value of the owner's machine reaches a kind's
  command through the environment, as its guide says; never pass one yourself.
- **Waivers.** Any kind may be waived, and only by the owner. A waiver for later
  validations is the owner's decision in the change's workflow log, naming the
  kinds it waives (`waives`) and the condition they are waived on, such as "nothing
  the change touches affects the services the end-to-end tests validate"; an
  instruction in the invocation is not a waiver. `evidence` marks each waived kind
  with the decision's `seq` and words, so read them there. An older decision
  recorded before waivers named their kinds is free text in `workflow.jsonl`:
  read the log's owner decisions for one too. For each kind such a decision
  waives, find the last validation record of the change whose `Evidence:` line —
  an older record's `Parts:` line — assessed that kind, and its `Commit:`. The
  waiver lapses, and the kind is gathered, when the commits since then include a
  merge (`git log --merges <that commit>..HEAD`), since a merge brings in code the
  change did not write, or when the condition does not hold over what they change
  (`git diff --stat <that commit> HEAD`); with no such record, judge the condition
  over the change's own diff. The gathering lapses a waiver on a merge itself, its
  closing line for the kind saying so; whether the condition still holds is yours
  to judge. Otherwise the kind is `waived`: it is not gathered, and the record
  names the decision's `seq`, its condition, and what you checked. A lapsed waiver
  is written in the kind's section too, naming the decision's `seq` and why it
  lapsed — the merge, or how the condition broke — and a kind the gathering
  skipped is gathered with `scripts/change-workflow gather <change> --kind <kind>
  --lapsed`, run as step 2 says: the engine refuses to gather a kind the log waives
  without it. A waived kind is an omission of evidence, neither passed, failed, nor
  inconclusive, and the result is judged on the kinds assessed. When every kind is
  waived there is nothing to validate: write no record, and tell the owner that
  waiving validation entirely is their direction past the guard it remedies.
- **Owed evidence.** Evidence only a push produces — a CI workflow's run, which a
  change branch's push does not trigger — is owed by validation rather than gating a
  task. For each owed argument `evidence` lists, read its `Owed by validation:`
  lines in `tasks.md`, as the clean worktree holds it at `HEAD`: what must be
  shown, and the section and task owing it. Every validation of the change assesses
  them, a fix commit's included, since a later commit can break what an earlier one
  showed; a commit kind's evidence describes one commit, so a new commit's is
  gathered anew — unless the owner waived the kind (above). A kind `evidence` lists
  as `not required` is not gathered, and the record says so. What the owed kind may
  run, and what a line owing something else means, are its guide's.

## 2. Read what the gathering found

Before your session the engine gathered every required kind and owed argument that
was missing and not waived, and touched no present evidence: it ran the preflight;
then, when a dispatched kind was missing, the guarded push of exactly `HEAD`, never
forced, since the run that describes `HEAD` is the one dispatched for it; then
every missing kind's start, each returning at once, so the slowest kinds run while
everything else does; then every missing kind that runs here, one after another in
the configuration's order, never one beside another; then each started kind's
collect, which waits for the run of `HEAD` newer than the marker its start printed
— a commit validated before never collects its earlier run — and for it to finish.
A waived kind was skipped, saying so, unless a merge lapsed its waiver (step 1). A
failing kind failed the gathering, and every other kind still ran; a refused push
dispatched nothing and still ran the kinds that run here.

The gathering's `status.md` holds its closing lines, one per kind: `[change-workflow]
gather <kind>[ <argument>] at <tree|commit> <id>: passed, exit 0; evidence <its
current path>`, or `failed, exit <n>:` and each failed command with its exit status,
its evidence then the current path or `none`; a kind found present says it skipped
it and which match is current; a gathering refused before it ran anything leaves an
`ERROR:` line instead. A failed kind may still have left evidence, an attempt saying
why it failed: the evidence, never the closing line alone, is what you assess.

Then run `scripts/change-workflow evidence <change>` again, which names every kind's
current evidence, whoever wrote it.

**Gathering again.** You gather only a new attempt of one kind, and only for a
reason this skill gives: evidence that cannot be read, a waiver lapsed (step 1), or
an environmental failure the owner has remedied or allowed a new attempt of
(section 5). Run `scripts/change-workflow gather <change> --kind <kind>`, with
`--owed <argument>` for one owed argument, as written, in the background, with the
harness's longest `timeout`, 7200000 ms — a dispatched run can take longer than the
default ten minutes — and with no shell redirect of its output: a redirect is a
write no rule admits unattended, and the harness keeps a background command's
output in a file, which is what the wait reads. Wait inside one Bash call, with
`scripts/change-workflow wait <output-file> '^\[exited with code '`, the line the
harness ends the file with — a regular expression, so its bracket is escaped —
never by ending the turn: under the wrapper a turn's end is an outcome, so a turn
ended with the gathering in flight is logged as a stop. The wait returns that line
as soon as it is in the file, even if it was written before the wait began, and
gives up after nine minutes, inside one call's ten-minute limit, so give its call
that limit; the gathering can take longer, so when the wait gives up, run it again,
still without ending the turn. Then read the output whole. No step follows a file
with `tail -f`: it hangs when the line waited for is the last one written, and no
rule allows it. Never a shell loop: `bash -c` has no allow rule unattended and will
not get one, since no rule admits a loop without admitting any command. The new
attempt is current by path order; the earlier one stays as evidence, and the record
reports both, the new attempt's path beside its reason. Never gather again for a
pass.

## 3. Assess each kind

For each kind `evidence` lists as required, read its current evidence as its guide
says:

- **Present and passed** — the kind passed, whoever wrote it.
- **Present and failed** — diagnose the failure from the evidence (section 4); never
  gather it again to see whether it passes.
- **Present and unreadable** — a summary missing or not what its guide describes, an
  attempt cut off — gather a new attempt, and say in the record why the first could
  not be read.
- **Missing** after the gathering — the gathering's closing line and log say why: an
  environmental cause is settled as section 5 says; anything else is a failure of
  unknown cause.

Its source is `present` when the evidence was there before the gathering, and
`gathered` when the gathering before the session or a new attempt you made wrote it.
A kind whose evidence its guide says describes no one tree or commit — the worktree
changed, or `HEAD` moved, while it ran — describes neither `HEAD` nor its tree, so
stop.

## 4. Diagnose every failure

For each failure, read its evidence as the kind's guide directs — the logs it keeps,
and the state they point at. Establish:

- what failed: the test, the assertion or error, and the log lines that show it;
- why, as far as the evidence shows: the component whose own log explains it, and
  the code or configuration it points at;
- the cause: **commit** (the change's code, tests, or configuration),
  **environment** (the machine, a cluster, a registry, the network, state left by
  an earlier run), or **unknown**; say how sure you are and what would settle it.

Read failures from the evidence; never report only an exit status. Unknown is never
treated as environment: a failure you cannot place is triaged. Where a guide tells a
kind's failures apart — what is environmental, what is the commit's, what a warning
means — classify by it.

## 5. Settle environmental failures with the owner

A failure you diagnose as environmental with good confidence is not a finding about
the change, and triage cannot fix it. Settle it now:

1. Stop, and tell the owner the failure, its evidence, and the remedy, as the kind's
   guide gives it, or as the evidence shows. When it is a known environmental
   failure, already diagnosed in an earlier validation record of this change,
   recommend beside the remedy that the owner may waive the kind instead, naming
   that record, as `change-workflow`'s CW-q3dm gives the criterion; with no
   criterion holding, recommend none. Only the owner waives: a kind they waive is
   `waived`, an omission of evidence counted in no result, while one they decline
   to remedy is `inconclusive`.
2. Wait for the owner's word: either the owner carries out the remedy, or names the
   action for you to take. Take only the action named.
3. Gather that kind again, as step 2 says, the reason written beside the new
   attempt's path.

When the owner declines, or the remedy cannot be applied now, the kind is
`inconclusive`. A waiver you recommended goes in the record's `## Environment`,
taken or declined, with its criterion: validation commits nothing, so the triage
that reads the record writes its ledger line, and archive cleanup writes it for a
record no triage reads — a validation of the merged `HEAD`, or one before closeout
or archive cleanup. Never gather again only to get a pass: a new attempt is to tell
an environmental fault from a failure, or to validate after a remedy, and its first
result is always reported.

A defect in the validation tooling itself — a check that misled you, a preflight
that would have caught this, a step that depends on state it should not, a guide
that is wrong — goes in the record's section about the validation, not among the
failures.

## 6. Name the scenarios that cover the change

The change's task notes name, on each section's `End-to-end:` line, the end-to-end
scenarios its verification relies on. Read them, and add any scenario the change's
diff added or modified, as the guide of the kind that runs them says where a
scenario is named. For each, give its basis and its result on each lane that ran
it. When no scenario exercises the change's behaviour, say so plainly; triage needs
to know that a green end-to-end run is not evidence for this change.

## 7. Write the validation record

Write the validation record at the path `scripts/change-workflow find
--next-record validation <change>` prints, run at the moment you write it:
`reviews/NN-validation.md` in the change's directory, under the archive once
closeout has archived the change, numbered after every record and transcript as
the engine numbers its own. Never count the number yourself, and never take it
from the workflow log, whose `seq` numbers its lines, not records. A review started
beside this validation may have taken a number since you began, which is why you
ask when you write; never overwrite a record: if the path exists, ask again.

The result, overall and per kind, is one of:

- `passed` — every kind assessed passed;
- `failed` — at least one failure is caused by the commit, or its cause is unknown;
- `inconclusive` — no failure is caused by the commit, but some kind has no
  evidence for an environmental reason the owner declined or could not remedy.

A kind the owner waived is `waived` on the `Evidence:` line and counts in no
result: the overall result is judged on the kinds assessed. A kind waived before it
was gathered has a section holding only the line `Waived: <the owner's decision, by
its log seq>; <the condition, and what you checked of it>`. A kind waived after an
environmental failure keeps its attempts as any kind does, adding the line
`Waived: <the environmental failure waived>; <the owner's words>`. A waiver that
lapsed is the line `Waiver lapsed: <the decision, by its log seq>; <the merge, or
how the condition broke>` above the kind's evidence.

`make review KIND=pre-closeout` reads the `Commit:` and `Result:` lines, and the
change's history reads `Commit:` and `Tree:`, so keep them exactly as the template
shows: the full object name, then the result word, with no backticks or emphasis
around any of them.

```markdown
# Validation — <change> — <short commit>

- **Commit:** <full commit> on <branch>
- **Tree:** <full tree>
- **Result:** passed | failed | inconclusive — <one line why>
- **Evidence:** <each entry `evidence` lists, by its kind and any owed argument, then its result and source, as `suites passed (present) · deploy failed (gathered) · ci build.yml passed (gathered) · e2e waived`, and a kind not required as `ci not required`> (each result passed, failed, inconclusive, or waived; each source present or gathered)
<any header line a kind's guide adds>

## <a section per kind, in `evidence`'s order, named and laid out as its guide says>

Current: <the current attempt's path>. <each earlier attempt's path, and each new attempt's path with its reason: unreadable, a waiver lapsed, or environmental and gathered again on the owner's word>

<what the guide says the section holds>

## Coverage of this change

| Scenario | Basis | Lane | Result |
|---|---|---|---|

<or: no end-to-end scenario exercises this change's behaviour>

## Environment

<each environmental failure: its evidence, the remedy, any waiver you recommended
with its criterion and the earlier record, what the owner decided, and the attempt
that followed; or `None.`>

## Failures

### V1 — <the failure in one line>

- **Kind:** <the evidence kind, and any owed argument>
- **Evidence:** <attempt, log paths, and the lines that show it>
- **Cause:** commit | unknown

<the diagnosis, and what would settle it if the cause is unknown>

## About the validation

<defects in the validation tooling or its guides this run exposed, and any
contradiction between a guide or message and this skill; or `None.`>
```

Only failures caused by the commit, or of unknown cause, go under `## Failures`,
labelled `V<n>` so triage can carry them beside review findings; write `None.` when
there are none. What a section owes is read from `tasks.md`, never written there: a
line that names the wrong thing to show is reported, and the plan's correction is
implementation's. Environmental failures go under `## Environment` and are never
findings.

## 8. Report

Tell the owner the commit and its tree, the result and each kind's with its source,
each kind waived and each waiver that lapsed, with the decision and why, each new
attempt and its reason, what each kind's guide asks the report to name, the coverage
of the change, each environmental failure and how it was settled, each failure with
its diagnosis, any contradiction you noticed between a guide or message and this
skill, and anything under "About the validation". Then say what comes next. When
this is a round's validation beside its review, or it has a `V<n>`: the
implementation round — this record, the implementation review of the same commit,
and the owner's own notes — is triaged together in a fresh session,
`make triage CHANGE=<change>`, which fixes what the owner accepts; the fix commit
is then validated again. When it is the passing validation of a fix commit, of
`HEAD` before closeout, or of a closeout correction, the change moves on without a
triage, to whatever the triage before it recorded.
