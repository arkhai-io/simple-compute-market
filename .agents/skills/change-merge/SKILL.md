---
name: change-merge
description: Merge the branch an OpenSpec change will land on — the branch it was branched from, or another the owner names — into the change's branch once its pre-closeout review's triage advanced it — resolve every conflict, reconcile the change's own code with what that branch renamed or removed even where Git reported no conflict, run the suites, conclude and push the merge, then judge whether the merge merits another pre-closeout review and whether its validation may be waived, asking the owner to confirm either before taking it; or repair what a failed validation of the merged HEAD found; or, after the archive, merge that branch again, keeping the change archived, and choose between a merge review and archive cleanup without asking. Use when the next-step computation names `merge`, when the owner says "merge <branch> into <change>", or when `make merge` invokes you.
---

# Merging a change's base into it before closeout

A change is reviewed against the branch it was branched from as it stood then, and
merges into that branch as it stands when it lands. Between the two, the branch
moves: an interface the change's code calls is renamed, a lock is refreshed, a test
harness is rewritten. Git merges text, not meaning: code the change added that calls
what the branch removed merges without a conflict and fails only when it runs. So
once the change's implementation is reviewed and triaged, and before closeout writes
its permanent documents, you merge that branch into the change's branch, reconcile
the change with it, and hand the merged `HEAD` to the validation before closeout,
which then tests the change as it will land.

**The branch you merge** — the *base* below — is the one your invocation names
after the change: `<change> from <branch>`. The engine names the branch the owner
gives it (`make merge FROM=<branch>`), else the branch the change's last finished
merge recorded in its outcome's `landing`, else the branch the change's clone
recorded as the one it lands on, and refuses to start with none. Invoked with no
branch, ask the owner which branch the change will land on; never assume one.

**Every finished outcome records what you fetched**, as `landing`: `{"remote":
<the remote you fetched from, as this checkout names it>, "branch": <the base>,
"commit": <the full object name of the commit you fetched>}`, or `"remote": "."`
for a base this checkout holds itself and you fetched from nowhere. Record it
whether or not anything merged. The log's writer refuses a finished merge without
it, or with a remote this checkout does not name, or with a commit `HEAD` does not
contain; a question or a stop carries none. Archive cleanup fetches what the last
finished merge recorded, and a later merge given no branch brings in its branch.

You also decide what the merge needs next, and the owner confirms what costs more
than the default:

- **No review, validation** — the default: the merge's resolutions are mechanical
  or corrections a reviewer would only confirm. You advance to closeout without
  asking, and the computation validates the merged `HEAD` first.
- **Another pre-closeout review** — the merge changed what the change does. You
  recommend it and the owner confirms or declines it.
- **No validation** — you may recommend waiving the validation of the merged
  `HEAD`, and only the owner can waive it.

The computation sends you back here when the validation of the merged `HEAD`
fails: you hold what each side changed, so you repair what it found
("Repairing a failed validation").

## Running unattended

Run interactively, this section does not apply but for the outcome it describes,
which an interactive run records itself ("Running interactively"). When this skill
runs through `scripts/change-workflow start --unattended` — `make merge UNATTENDED=1`, or the
orchestrating session — nobody can answer in the session, and every turn ends with
an outcome matching `.agents/change-outcome.schema.json`, whose `message` the owner
reads as written:

- **A stop for the owner is a question.** Wherever this skill says to ask the
  owner, end the turn with `question`: `message` says what you found, the options,
  and your recommendation; `awaiting` names what you need. The owner's answer
  resumes this session; carry on from it.
- **A denied call stops the step only when it cannot go on.** Run one command per
  Bash call: a chained command runs only when every command in it is allowed. If a
  call is denied, finish every part of the work that does not depend on it. If the
  step cannot complete without it, end with `stopped`, `reason` naming that exact
  call and why the step needed it, and `denials` listing the calls as you saw them.
  A call a deny rule refused is forbidden: no other tool does it, except where the
  rule exists only to keep file writes on the Edit and Write tools — the step
  table's comments name those rules: sed's in-place forms, find's deleting,
  running, and writing actions, and the diff family's output-to-file forms —
  whose refused shell write may be made with the Edit or Write tool this step's
  rules allow. A call denied because no rule allows it — the harness reports it
  as don't ask mode — may be done instead by a tool this step's rules allow for
  the same work, such as the Edit tool for a shell write or Read or Grep for a
  shell read. Either way, name the substitute in your message. Never ask about a
  denial as a question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop — a
  repository guard refusing, `HEAD` moving under you — end with `stopped`, `reason`
  saying why, and `denials` empty.
- **Git runs in this checkout**, never with `-C`, and Make here too. The merge you
  start is never abandoned: no rule allows `git merge --abort`, `git reset`, or
  `git checkout`, and a merge stopped at a conflict you ask about stays in progress
  for the owner's answer.
- **A turn's end is its outcome.** Never end a turn with work still running. Wait
  for a background command inside one Bash call, with `scripts/change-workflow wait
  <output-file> '<pattern>'` matching the line it prints when it ends, repeated when
  the wait gives up; when it says the command ended with no line matching, read the
  output rather than waiting again — never with `tail -f`, which hangs when that line
  is the last.
- **The end is an outcome.** Once the merge is concluded and pushed and its exit
  chosen (step 7), end with `finished`, `next` that exit — `{"step": "closeout"}`
  or `{"step": "review", "kind": "pre-closeout"}` — `landing` what step 3 fetched,
  or for a repair the landing of the merge it repairs ("Repairing a failed
  validation"), and `message` the report (step 8). When the merge shows the change's design or plan no longer holds, end with
  `returned`, `next` `{"step": "plan"}` or `{"step": "design"}`, and `evidence`
  naming where you recorded what you found; the owner confirms the return. After
  the archive the exits are `{"step": "review", "kind": "merge"}` and `{"step":
  "archive-cleanup"}`, and there is no return ("After the archive").

## Running interactively

Run in an interactive session — `make merge` without `UNATTENDED=1`, or the slash
command — no wrapper records the run, so its last act records the outcome it would
end with unattended:

```text
scripts/change-workflow record <change> merge --outcome '<the outcome, as JSON>'
```

Record `finished`, with its `landing` — which only a repair of a merge logged
before the record existed omits — or `returned`, never a question or a stop, which
the owner, present, settles in the session. When `record` refuses the
`landing`, correct what it names and record again. When the owner waived the
validation of the merged `HEAD`, record their direction after the outcome: step 7's
command before closeout, "After the archive"'s after it.

## 1. Check that the merge may start

- **Branch.** The checked-out branch is the one this change is worked on. If it
  does not carry the change's latest commits, or its name belongs to another
  change, stop and ask the owner — unless the change's log holds the owner's
  decision that it runs on this branch (`scripts/change-workflow log <change>
  --branch <branch>` prints it).
- **Base.** Your invocation names it. It is not the change's own branch.
- **Route.** `scripts/change-workflow next <change>` names `merge`: the
  pre-closeout triage's exit, a failed validation of the merged `HEAD`, or the
  owner's direction. For an archived change its reason begins `late-merge:` — the
  owner's direction to the merge after the archive, archive cleanup's first exit
  finding the landing branch moved, or a failed validation of the `HEAD` it merged —
  and the run follows "After the archive" as well. When a merge is in progress it
  names the owner, `merging`;
  that is yours to continue only when this session started it and is resumed with
  the owner's answer. Otherwise, when it names anything else, stop: its reason says
  what comes first.
- **Worktree.** It is clean, but for a merge this session started, and
  `scripts/change-workflow check round-view` passes.
- **Repair or merge.** Read the latest validation record in `reviews/`. When it
  names `HEAD` and failed, this run repairs it: go to "Repairing a failed
  validation". Otherwise go on.

## 2. Load the context

Read in full: the documents `scripts/change-workflow config load merge` prints; the change's
`proposal.md`, `design.md`, and `tasks.md`, the section notes above all, which say
which files each section owns and which suites and end-to-end scenarios prove it;
the latest pre-closeout review and its triage, and after the archive the latest
closeout review's and any merge review's too; and the latest validation record.

## 3. Merge

1. Fetch the base from the remote that has it — the remote the branch tracks in the
   owner's workspace, which a clone has under the same name (`git remote` lists
   them; `origin` in this repository): `git fetch <remote> <base>`; for a change
   worked in its own clone, a branch only the owner's workspace holds comes from its
   `workspace` remote, `git fetch workspace <base>`. The base is then
   `<remote>/<base>`, written `<base>` below. Note the commit you fetched, `git
   rev-parse <remote>/<base>`, with the remote and the base, for your outcome's
   `landing`; a base this checkout holds itself is recorded with the remote `.` and
   `git rev-parse <base>`. List what it gained: `git log
   --oneline HEAD..<base>`. When it lists nothing, the base is merged already:
   nothing is merged, and `HEAD` and its validation stand. Go to step 7, which
   advances without asking: to closeout, or after the archive to archive cleanup.
2. Before merging, record what the base changed and what the change depends on —
   the merge base is `git merge-base HEAD <base>`:
   - `git diff --stat <merge-base> <base>` and `git log --oneline
     <merge-base>..<base>`;
   - the change's own diff, `git diff --stat <merge-base> HEAD`.
3. `git merge --no-edit <base>`. A merge with no conflict concludes itself as a
   commit: go to step 4, and add its repairs as a commit of their own (step 6).

**Resolve each conflict** (`git diff --name-only --diff-filter=U`) so both sides
hold: the change's behaviour as its sections built it, and the base's as its
commits made it (`git log --merge -p -- <file>` shows each side).

- **The change index** (`openspec/changes/README.md`): each change's row as its own
  branch has it — this change's from this branch, every other row from the base.
- **Change documents** under `openspec/changes/`: this change's from this branch,
  another change's from the base.
- **Locks and other derived files** (`uv.lock`): take the base's side of the
  conflicted hunks with the Edit tool; step 5's `after-functional-change` rebuilds
  them, which in this repository relocks, settling the change's own dependencies
  against the base's. A `pyproject.toml` conflict is resolved by hand first: both
  sides' dependencies, and the higher of two version bumps of one package.
- **Code, tests, and configuration**: edit each file so both sides hold, with
  comments describing the system that results. Where the two cannot both hold, the
  resolution is a decision: ask the owner, with the options and your
  recommendation, leaving the merge in progress.

`git add` each resolved file, but conclude nothing yet.

## 4. Reconcile what merged without a conflict

A conflict marks only text both sides edited. The change's own code and tests can
call what the base renamed, removed, or changed the meaning of, in files the base
never touched, and merge cleanly. Find each such place:

- For each file the base changed (step 3's list) that defines something the
  change's diff uses — a module it imports, a class or function it calls, a
  fixture, a harness client, a configuration key, a schema, a Make target — read
  the base's diff of it, and search the change's diff for every name the base
  removed or renamed and every signature it changed.
- The end-to-end scenarios under `e2e-tests/` above all: no local suite runs them,
  so a stale call in a scenario the change added is found only by the pipeline.
  Read each scenario the change added or extended against the base's changes to
  the harness and fixtures it uses.
- Where the base reworked a pattern the change's code also follows — it moved
  every caller of an interface to a new one — the change's new callers move too,
  even where the old interface still works.

Fix each place, as the base's other callers were fixed. A fix that would change
what the change does, rather than how it reaches what the base now offers, is a
decision: ask the owner.

## 5. Check

Run each, and fix what it reports:

- the suites the verification tasks name of the sections owning each file you
  resolved or reconciled;
- `scripts/change-workflow run pre-commit <change>`. The paths the worktree
  changes decide what it runs: with resolutions or reconciliations outside the
  inert paths there, it runs `after-functional-change`, which rebuilds a lock
  whose side you took, then `pre-commit-functional` and `pre-commit`; otherwise
  `pre-commit` alone. So when the base brought a path outside the inert paths
  that the worktree no longer shows, because the merge concluded itself, run
  `scripts/change-workflow run after-functional-change <change>` first: if it
  changed a path outside the inert paths, `run pre-commit` then runs every hook;
  if not, run `scripts/change-workflow run pre-commit-functional <change>` by name
  before `run pre-commit`, so the suites run once. `git add` what the hooks
  rebuilt.

A failure the base alone causes — failing on the base as well — is not the
merge's: say so in the report, and do not fix the base here.

## 6. Conclude and push

With conflicts, conclude the merge with its resolutions and reconciliations in it,
without opening an editor: `git commit -m "<Git's merge subject>" -m "<each
conflicted file and how it was resolved; each reconciliation and why>"`, the
subject the first line of `.git/MERGE_MSG`. Without conflicts, the merge concluded
itself: commit the reconciliations on their own, the message naming the change,
that they reconcile it with the base, and each fix. Push with `scripts/change-workflow push`;
if it refuses, stop and report its reasons.

## 7. Choose the exit

After the archive, choose the exit as "After the archive" says instead of this
step. Before closeout, judge the merge, then take the exit it merits:

- **Review.** Recommend another pre-closeout review when the merge changed what
  the change does, so the pre-closeout review just triaged no longer describes it:
  a conflict in the change's code resolved by a decision; a reconciliation that
  changed the change's behaviour, interfaces, or the decisions its design records;
  or a contract the change depends on that the base changed in meaning, not only
  in name. Recommend none when the conflicts were the index, change documents,
  locks, and version bumps, and the reconciliations moved the change's calls to
  what the base renamed or reshaped, which a reviewer would only confirm.
- **Validation.** The merged `HEAD` is validated before the review or closeout that
  follows, unless the merge changed only the repository's inert paths, which the
  guard exempts by itself. Recommend waiving it only when nothing the
  base brought can reach what the change ships or how it is tested — no shared
  package, lock, image, chart, or harness — and say what you checked. Never
  recommend waiving it after a reconciliation of the change's own code.

Then:

- Recommending no review and validation, or nothing was merged: take the
  advancing exit, `{"step": "closeout"}`, without asking.
- Recommending a review, or a waived validation: ask the owner, giving each
  judgement with its evidence, and take the exit their answer names. A review is
  `{"step": "review", "kind": "pre-closeout"}`. A declined review is closeout. A
  waived validation is closeout too, with the owner's words in your message: the
  waiver takes effect as the owner's direction to closeout, which checks no exit
  guard. Unattended, the orchestrating session records it after your run.
  Interactively, record it yourself after your outcome:

  ```text
  scripts/change-workflow note <change> orchestrator --by owner --decision "closeout without validating the merged HEAD" --reason "<the owner's words>" --resolves <your run's seq> --next closeout
  ```

When the exit is closeout and the latest validation passed for `HEAD`, or for an
ancestor `HEAD` differs from only in the inert paths, set the change's
`Status` in `openspec/changes/README.md` to `ready for closeout`, rewrite the row's
`Notes` in the same edit so nothing in them describes the implementation phase,
run `scripts/change-workflow check index`, and commit and push the row. Otherwise leave the
status: closeout accepts a change still `in implementation` once the computation
names it.

## Repairing a failed validation

The latest validation record names the merged `HEAD` and failed. Read each of its
failures, with the logs it cites:

- A failure the merge caused — a stale call, a lock that resolved differently, a
  fixture the base changed — is yours: fix it as step 4 does, run step 5's checks,
  commit the repair naming the change and the validation record, push it, and take
  the exit you took before (step 7), whose guard validates the repaired `HEAD`.
  A repair fetches nothing: its outcome carries the `landing` of the merge it
  repairs, read from the latest finished merge line that records one in the whole
  log — `grep '"step": "merge"' <records>/workflow.jsonl`,
  `scripts/change-workflow find --records <change>` naming the records — so the
  last finished merge's
  record stays the branch the merge brought in. Only when no finished merge in the
  log recorded one — a merge logged before the record existed — does the repair
  finish without it.
- A failure the merge did not cause — one the change's own code had before the
  merge, or one the base has — is not yours to fix: ask the owner, with the
  evidence and your recommendation, since only they decide whether it returns the
  change to implementation, is fixed on the base, or is waived.

Never finish while the latest validation of `HEAD` failed and you committed no
repair: the computation would name this step again for the same record.

## After the archive

Once archive cleanup has run, the branch the change lands on may move again — while
closeout ran, or while the pull request waits — and the change is merged with it
again: the merge after the archive, `late-merge`, which the computation names as
`merge`, its reason beginning `late-merge:`. The change is archived: its deltas are
merged into `openspec/specs/`, its row says `archived`, and no step returns it to an
earlier phase. Merge, reconcile, check, conclude, and push as steps 1 to 6 say, a
repair as "Repairing a failed validation" says, and resolve as before closeout, with
these rules besides:

- **The change index.** This change's row from its branch, still `archived`; every
  other row from the landing branch. A row the landing branch brought whose `Depends
  on` names this change is released by every rule of archive cleanup's step 3 —
  this change removed from its `Depends on`, leaving `—` when nothing remains; a
  status of `ready for planning`, `in planning`, or `ready for implementation` set
  to `ready for design`, its `Notes` saying its design is reverified; a `blocked in`
  status kept, its `Notes` saying reverification is owed once the blocker clears —
  since archive cleanup run again does not release it.
- **The archived change's directory** as this branch has it.
- **`openspec/specs/`, each `index.md`, and the permanent documents:** both sides.
  Every requirement says what each change meant, every id is unique, and each
  change's index entries are kept; two changes' edits to one requirement are merged
  into one that says both, never one side taken whole.
- **The validation capacity figure** (`helm/validation-capacity.toml`): the one
  whose `measured_at` is later.
- **The row's status is never set to `ready for closeout`:** step 7's status edit
  does not apply.
- **`reviews/pull-request.md`**, untracked, never conflicts: append a note on what
  you merged — the branch, its commits since the merge base by subject, each
  conflict and reconciliation — and how the merged `HEAD` is to be validated: the
  exit's guard, or the waiver you recommend. Archive cleanup run again appends the
  validation's result. Never rewrite what is there, since archive cleanup may have
  copied it into the owner's workspace, where only a file that grew is brought up to
  date.

**Choose the exit yourself, and take it without asking** — the orchestrating
session follows it. Name the merge review, `{"step": "review", "kind": "merge"}`,
when any of these holds, and archive cleanup, `{"step": "archive-cleanup"}`, when
none does:

- a conflict resolved outside the mechanical files — the change index, other
  changes' documents, files the repository's hooks rebuild such as a lock, version-
  only bumps, and a file a validation part's cleanup writes, such as the capacity
  figure;
- a reconciliation of the change's own code or end-to-end scenarios (step 4);
- a file outside those mechanical files that both sides changed since the merge
  base, even where Git merged it without a conflict — two changes' edits to one
  specification can merge into a contradiction (`git diff --name-only <merge-base>
  <base>` against `git diff --name-only <merge-base> HEAD`, from before the merge);
- a contract the change depends on that the landing branch changed in meaning, not
  only in name.

When the landing branch gained nothing, nothing is merged: name archive cleanup,
and `HEAD` and its validation stand. Say in your report which criteria held, with
their evidence.

**Validation.** The merged `HEAD` is validated before the exit you named — with the
inert paths exempt before archive cleanup, records only before the merge review —
and a failed validation brings the change back here to repair it. Only the owner
waives it. Recommend a waiver only when a criterion of `docs/agents/change-workflow.md`'s
"Waivers" holds, naming it and its evidence, and never after a reconciliation of
the change's own code. The waiver is the owner's direction past the guard to the
exit you named — the merge review when you named it, archive cleanup otherwise — so
a review you chose is not skipped with the validation: skipping both is the owner's
direction to archive cleanup, its reason saying it skips both. Say the
recommendation in your report and finish naming your exit; the orchestrating
session asks the owner and records their answer. Interactively, record the owner's
waiver yourself after your outcome, its `--next` the exit you named:

```text
scripts/change-workflow note <change> orchestrator --by owner --decision "<the exit> without validating the HEAD merged after the archive" --reason "<the owner's words>" --resolves <your run's seq> --next review --kind merge
```

with `--next archive-cleanup` and no `--kind` when you named archive cleanup.
Never step 7's direction to closeout: closeout has run.

**Ask instead of returning.** No exit returns: design, planning, and implementation
refuse an archived change. Where a conflict cannot be resolved so that both sides
hold, or the landing branch has invalidated the change's design, ask the owner with
the options and your recommendation, leaving the merge in progress: they resolve it
as they direct, land the change and follow up in a new change, or take it off the
workflow.

## 8. Report

Tell the owner:

- the base merged, and what it brought: its commits since the merge base, by
  subject;
- each conflict and how it was resolved;
- each reconciliation of the change's code that merged without a conflict, and how
  you found it;
- each check with its result, and any failure the base alone causes;
- your judgement on a review and on validation, with the evidence, and the exit
  taken — or, for a repair, each failure, its cause, and the fix.
