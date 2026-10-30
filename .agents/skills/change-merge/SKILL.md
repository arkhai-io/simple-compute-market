---
name: change-merge
description: Merge the branch an OpenSpec change will land on — the branch it was branched from, or another the owner names — into the change's branch once its pre-closeout review's triage advanced it — resolve every conflict, reconcile the change's own code with what that branch renamed or removed even where Git reported no conflict, run the suites, conclude and push the merge, then judge whether the merge merits another pre-closeout review and whether its validation may be waived, asking the owner to confirm either before taking it; or repair what a failed validation of the merged HEAD found. Use when the next-step computation names `merge`, when the owner says "merge <branch> into <change>", or when `make merge` invokes you.
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
after the change: `<change> from <branch>`. `make merge` names the branch the owner
gives it, or its default. Invoked with no branch, ask the owner which branch the
change will land on; never assume one.

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
runs through `scripts/run_change_step.py` — `make merge UNATTENDED=1`, or the
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
  A call a deny rule refused is forbidden: no other tool does it. A call denied
  because no rule allows it may be done instead by a tool this step's rules allow
  for the same work, such as the Edit tool for a shell write or Read for a shell
  read; name the substitute in your message. Never ask about a denial as a
  question.
- **A stop with nothing to ask is stopped.** Where this skill says only to stop — a
  repository guard refusing, `HEAD` moving under you — end with `stopped`, `reason`
  saying why, and `denials` empty.
- **Git runs in this checkout**, never with `-C`, and Make here too. The merge you
  start is never abandoned: no rule allows `git merge --abort`, `git reset`, or
  `git checkout`, and a merge stopped at a conflict you ask about stays in progress
  for the owner's answer.
- **A turn's end is its outcome.** Never end a turn with work still running. Wait
  for a background command inside one Bash call, with a blocking `tail -f … | grep
  -m1` on its output matching the line it prints when it ends.
- **The end is an outcome.** Once the merge is concluded and pushed and its exit
  chosen (step 7), end with `finished`, `next` that exit — `{"step": "closeout"}`
  or `{"step": "review", "kind": "pre-closeout"}` — and `message` the report (step
  8). When the merge shows the change's design or plan no longer holds, end with
  `returned`, `next` `{"step": "plan"}` or `{"step": "design"}`, and `evidence`
  naming where you recorded what you found; the owner confirms the return.

## Running interactively

Run in an interactive session — `make merge` without `UNATTENDED=1`, or the slash
command — no wrapper records the run, so its last act records the outcome it would
end with unattended:

```text
python3 scripts/run_change_step.py record <change> merge --outcome '<the outcome, as JSON>'
```

Record `finished` or `returned`, never a question or a stop, which the owner,
present, settles in the session. When the owner waived the validation of the merged
`HEAD`, record their direction after the outcome (step 7).

## 1. Check that the merge may start

- **Branch.** The checked-out branch is the one this change is worked on. If it
  does not carry the change's latest commits, or its name belongs to another
  change, stop and ask the owner — unless the change's log holds the owner's
  decision that it runs on this branch (`python3 scripts/run_change_step.py log
  <change> --branch <branch>` prints it).
- **Base.** Your invocation names it. It is not the change's own branch.
- **Route.** `python3 scripts/change_next_step.py <change>` names `merge`: the
  pre-closeout triage's exit, a failed validation of the merged `HEAD`, or the
  owner's direction. When a merge is in progress it names the owner, `merging`;
  that is yours to continue only when this session started it and is resumed with
  the owner's answer. Otherwise, when it names anything else, stop: its reason says
  what comes first.
- **Worktree.** It is clean, but for a merge this session started, and `make
  round-view-closed` passes.
- **Repair or merge.** Read the latest validation record in `reviews/`. When it
  names `HEAD` and failed, this run repairs it: go to "Repairing a failed
  validation". Otherwise go on.

## 2. Load the context

Read in full: `AGENTS.md` and every document it requires; the change's
`proposal.md`, `design.md`, and `tasks.md`, the section notes above all, which say
which files each section owns and which suites and end-to-end scenarios prove it;
the latest pre-closeout review and its triage; and the latest validation record.

## 3. Merge

1. Fetch the base from the remote that has it: `git fetch origin <base>`; for a
   change worked in its own clone, a branch only the owner's workspace holds comes
   from its `workspace` remote, `git fetch workspace <base>`. The base is then
   `<remote>/<base>`, written `<base>` below. List what it gained: `git log
   --oneline HEAD..<base>`. When it lists nothing, the base is merged already:
   nothing is merged, and `HEAD` and its validation stand. Go to step 7, which
   advances to closeout without asking.
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
- **Locks** (`uv.lock`): take the base's side of the conflicted hunks with the Edit
  tool, then regenerate them with `make lock`, which settles the change's own
  dependencies against the base's. A `pyproject.toml` conflict is resolved by hand
  first: both sides' dependencies, and the higher of two version bumps of one
  package.
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

- `make lock`, when a lock or a `pyproject.toml` merged, then `make
  check-packaging`;
- the suites the verification tasks name of the sections owning each file you
  resolved or reconciled;
- `make test`;
- `make check-change CHANGE=<change>`.

A failure the base alone causes — failing on the base as well — is not the
merge's: say so in the report, and do not fix the base here.

## 6. Conclude and push

With conflicts, conclude the merge with its resolutions and reconciliations in it,
without opening an editor: `git commit -m "<Git's merge subject>" -m "<each
conflicted file and how it was resolved; each reconciliation and why>"`, the
subject the first line of `.git/MERGE_MSG`. Without conflicts, the merge concluded
itself: commit the reconciliations on their own, the message naming the change,
that they reconcile it with the base, and each fix. Push with `make push-branch`;
if it refuses, stop and report its reasons.

## 7. Choose the exit

Judge the merge, then take the exit it merits:

- **Review.** Recommend another pre-closeout review when the merge changed what
  the change does, so the pre-closeout review just triaged no longer describes it:
  a conflict in the change's code resolved by a decision; a reconciliation that
  changed the change's behaviour, interfaces, or the decisions its design records;
  or a contract the change depends on that the base changed in meaning, not only
  in name. Recommend none when the conflicts were the index, change documents,
  locks, and version bumps, and the reconciliations moved the change's calls to
  what the base renamed or reshaped, which a reviewer would only confirm.
- **Validation.** The merged `HEAD` is validated before the review or closeout that
  follows, unless the merge changed only paths under `openspec/` and `docs/`,
  which the guard exempts by itself. Recommend waiving it only when nothing the
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
  python3 scripts/run_change_step.py note <change> orchestrator --by owner --decision "closeout without validating the merged HEAD" --reason "<the owner's words>" --resolves <your run's seq> --next closeout
  ```

When the exit is closeout and the latest validation passed for `HEAD`, or for an
ancestor `HEAD` differs from only under `openspec/` and `docs/`, set the change's
`Status` in `openspec/changes/README.md` to `ready for closeout`, rewrite the row's
`Notes` in the same edit so nothing in them describes the implementation phase,
run `make check-change-index`, and commit and push the row. Otherwise leave the
status: closeout accepts a change still `in implementation` once the computation
names it.

## Repairing a failed validation

The latest validation record names the merged `HEAD` and failed. Read each of its
failures, with the logs it cites:

- A failure the merge caused — a stale call, a lock that resolved differently, a
  fixture the base changed — is yours: fix it as step 4 does, run step 5's checks,
  commit the repair naming the change and the validation record, push it, and take
  the exit you took before (step 7), whose guard validates the repaired `HEAD`.
- A failure the merge did not cause — one the change's own code had before the
  merge, or one the base has — is not yours to fix: ask the owner, with the
  evidence and your recommendation, since only they decide whether it returns the
  change to implementation, is fixed on the base, or is waived.

Never finish while the latest validation of `HEAD` failed and you committed no
repair: the computation would name this step again for the same record.

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
