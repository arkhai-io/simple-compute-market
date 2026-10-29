---
name: change-archive-cleanup
description: Clean up an archived OpenSpec change once its closeout review's triage has advanced it — release the changes that depend on it, set its index row to `archived`, keep its reviews, commit, draft the merge commit message and pull request description, record the capacity figure its latest validation measured, tear down its validation namespace and images, push, and copy its history into the owner's workspace. Use when the next-step computation names archive cleanup — a closeout triage's exit, or the owner's direction — and the change's row still says `in closeout`, when the owner says "clean up the archive of <change>", or when `make archive-cleanup` invokes you.
---

# Cleaning up an archived change

Closeout archived the change and committed it; the closeout review read the archive,
and its triage recorded that the change advances. The change has not landed yet: a change
lands when its index row says `archived`, and this skill writes that. It does what
closeout deliberately left until the review agreed — releasing the changes that
wait on this one — and prepares the change to merge.

Archive cleanup changes the campaign index, the change's ledger when the owner
waives its validation check (step 1), and the capacity figure in
`helm/validation-capacity.toml` when the change's latest validation measured one
(step 7). It then tears down the change's validation namespace and images, and,
for a change worked in its own clone, copies the change's history into the owner's
workspace as its last act. The archived change, its specs, and the permanent
documents are as the closeout review read them; a defect found now in any of them
is not this skill's to fix — stop and tell the owner.

## Running unattended

Run interactively, as most runs are, this section does not apply but for the
outcome it describes, which an interactive run records itself ("Running
interactively"); nothing else in the skill changes.
When this skill runs through `scripts/run_change_step.py` —
`make archive-cleanup UNATTENDED=1`, or the orchestrating session — nobody can answer in
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
  <a checkout>`: `-C` names only a subdirectory a skill names, such as `make -C
  helm teardown`.
- **The end is an outcome.** When the cleanup and any figure are committed and
  pushed, the pull request drafted, and the history copied (step 10), end with
  `finished`, `next` the terminal node, `{"step": "done"}`, and the message naming
  the pull request's opening from the drafts, which the orchestrating session does
  at `done`; you never create it. A failed teardown and a history copy that refused a file end `finished` too,
  with what failed and how to rerun it in the message. A row already `archived`
  (step 1) ends `finished` once steps 7 to 10 have run again, saying the rest of
  cleanup had run.

## Running interactively

Run in an interactive session — `make archive-cleanup` without `UNATTENDED=1`, or
the slash command — no wrapper records the run, so its last act records the
outcome it would end with unattended, as "Running unattended" gives it:

```text
python3 scripts/run_change_step.py record <change> archive-cleanup --outcome '<the outcome, as JSON>'
```

`record` checks the outcome against `.agents/change-outcome.schema.json` and
appends it to the change's workflow log with the session's id, `HEAD`, and
`interactive: true`, and the next-step computation routes on it as on an
unattended run's. It reads the session's id from `CLAUDE_CODE_SESSION_ID`, which
`printenv CLAUDE_CODE_SESSION_ID` shows; where the variable is unset it refuses,
and `--session <id>` gives the id. Record the outcome the session ends with —
`finished` — never a question or a stop, which the owner, present, settles in the
session: a recorded stop would wait for a resume only the wrapper makes. When
`record` refuses, correct what it names and run it again. Run after
the history copy (step 10), the record reaches the owner's workspace with the next
copy. Once the row says `archived` the computation names `done` whatever the log
holds, so a session closed after that without recording loses only its report;
closed earlier, it leaves archive cleanup in progress, and the computation names it
again, to be resumed, or its outcome recorded with the command above.

## 1. Check that cleanup may start

- **Branch.** The checked-out branch is the one this change is worked on. If it does
  not carry this change's latest commits, or its name belongs to another change,
  stop and ask the owner — unless the change's log holds the owner's decision
  that it runs on this branch: run `git branch --show-current`, then
  `python3 scripts/run_change_step.py log <change> --branch <that branch>`; a line
  it prints is that decision, and the branch is accepted.
- **Archived.** `python3 scripts/find_change.py --archived <change>` prints a
  directory under `openspec/changes/archive/`. Read every file of the change from
  there.
- **Status.** The change's row in `openspec/changes/README.md` is `in closeout`. A
  row already `archived` means steps 3 to 6 ran, after the checks below held: say
  so, skip the Route and Validated checks — the computation names `done` for an
  archived row, and a figure step 7 committed would otherwise read as an
  unvalidated change — and go on from step 7, each step after it being safe to
  repeat.
- **Route.** `python3 scripts/change_next_step.py <change>` names
  `archive-cleanup`: the exit of the latest closeout review's triage, once any
  validation it owes cleared `HEAD`, or the owner's direction to archive cleanup.
  When it names a validation of `HEAD`, or the owner, with archive cleanup as its
  `target`, the triage advanced and the validation it owes is missing: go on to the
  Validated check. When it names anything else — a triage in progress, another
  review — stop: whether the change advances is recorded in triage, and the
  computation's reason says what comes first.
- **Validated.** When `git diff --name-only <commit> HEAD`, from the commit the
  first closeout review read (its `reviewed-commit` marker), names a path outside
  `openspec/` and `docs/` — a correction to code, a skill, or the step table — the
  latest validation record is `passed` and names `HEAD`, or an ancestor `HEAD`
  differs from only in changes' ledgers and reviews. Otherwise the owner has waived
  the check or not, judging the paths named — as for another change's commit on a
  branch two changes share, which the merge carries all the same. When the
  computation named archive cleanup from the owner's direction — its reason says
  `the owner directed archive-cleanup at seq <n>`, and `python3
  scripts/run_change_step.py log <change>` shows that line — the direction is the
  waiver, its reason the owner's. Otherwise stop and ask the owner, naming the paths
  and the commits that changed them, whether the correction is validated first
  (`make validate CHANGE=<change>`) or they waive the check. Interactively, the
  owner answers in the session: record a waiver as their direction, and compute
  again, which then names archive cleanup:

  ```text
  python3 scripts/run_change_step.py note <change> orchestrator --by owner --next archive-cleanup --decision "waives archive cleanup's validation" --reason "<the owner's words, naming the paths>"
  ```

  Record a waiver as one line of the
  archived change's `interventions.jsonl` (`"finding": "validated"`, under the
  closeout review's record name, the owner's reason as the disposition), with the
  Edit tool, and commit it with the index edit (step 5). The check itself stands: a
  merge carries every commit on the branch, whichever change wrote it.
- **Worktree.** It is clean, and `make round-view-closed` passes.

If any check fails, stop and say why.

## 2. Load the context

Read in full: `openspec/README.md#plan-closeout-requirements` (part 6 states the
dependent rules), and `openspec/changes/README.md` — its legend, the change's row
and campaign, and every row and dependency graph that names the change. From the
archived change read `proposal.md`, `design.md`'s design-promotion record,
`tasks.md`'s closeout section with its end-to-end evidence, and the latest passing
validation record in `reviews/`.

## 3. Release the dependents

For every row whose `Depends on` lists this change:

- Remove the change from its `Depends on`, leaving `—` when nothing remains.
- When its status is `ready for planning`, `in planning`, or `ready for
  implementation`, set it to `ready for design`, and say in its `Notes` that its
  design is reverified against the codebase this change left. Its design rests on
  code this change has just altered.
- When its status is `blocked in` a phase, keep it, and record in its `Notes` that
  design reverification is owed once the blocker clears.
- Any other status — `ready for design`, `in design`, or `in implementation`, whose
  implementation has begun — is kept as it is. Do not read its `tasks.md` to decide.

A row that does not list the change in `Depends on` but describes it in its `Notes`
as still to land is rewritten to say it has; its status is not touched.

## 4. Mark the change archived

In the same edit, set the change's row to `archived`, and rewrite its `Notes` in the
form the index's other archived rows use: `Archived <date>`, from the archive
directory's name, and where it was promoted, from the design-promotion record,
followed by anything still owned elsewhere that the old notes named. Mark the change
`(archived)` in every campaign dependency graph that shows it.

Leave the change's `reviews/` where it is, transcripts included: it is untracked, so
it costs the repository nothing, and it is the review history until an export flow
exists. For a change worked in its own clone, step 10 copies it into the owner's
workspace.

Run `make check-change-index` and `make check-doc-citations CHANGE=<change>`; both
must report nothing. The citation check reads only the change's own documents, so
the index check is the one that sees this edit.

## 5. Commit

Commit the index edit, with a waiver's ledger line when step 1 recorded one, as
one commit whose message names the change and says its archive is cleaned up and
which dependents it released. Then push it with `make push-branch`, the guarded
push of exactly `HEAD`; if it refuses, stop and report its reasons.

## 6. Draft the merge

Draft, for the owner to use when the branch is merged:

- **A merge commit message** — a subject naming what the change makes true, and a
  body of a few lines: the behavior it adds or changes, and the permanent documents
  that now describe it.
- **A pull request description** — what the change does and why, from the proposal;
  where its decisions now live, from the promotion record; how it was validated —
  the pipeline run, its result, the commit it ran at, and the scenarios that
  exercised the change — from the closeout section and the validation record; and
  what it deliberately leaves to other changes, by their names.

Both are as public as the code, so `AGENTS.md#public-repository-discipline`
applies to every word. When the branch carries another change that is not archived,
say so: the pull request would merge that change too, so the owner decides when to
open it, and the drafts cover this change only.

Write both to `reviews/pull-request.md` in the archived change, beside the review
history, and show them in the report.

## 7. Record the capacity figure

Run `make record-capacity CHANGE=<change>`. It reads the change's latest validation
record, and the summary of the last Helm attempt of the commit it names. When that
attempt measured the namespace's memory, it writes the figure, with when it was
measured and this change's name, into `helm/validation-capacity.toml`, replacing
any earlier one; commit that file alone, the message naming the change and the
figure. When there is nothing to record — no metrics source answered on the
cluster, the validation ran no Helm part, or there is no validation record — the
target writes nothing and says why: leave any recorded figure as it is, and commit
nothing. A non-zero exit means a record or summary could not be read: say so in
the report, record nothing, and go on. Run again after an earlier run, it writes
the same figure, and a file unchanged is not committed.

Add to the pull request description's notes, in `reviews/pull-request.md`, what it
reported — on a rerun, as a line appended to the file rather than an edit of what
is there, since an earlier run may have copied the file into the owner's workspace,
where only a file that grew is brought up to date: the figure recorded, or that no figure was recorded and the reason it
gave. When a figure was recorded, say too that a merge conflict over
`helm/validation-capacity.toml` keeps the figure whose `measured_at` is later.

## 8. Tear down the validation namespace

Run `make -C helm teardown CHANGE=<change>`. It deletes the change's validation
namespace, with its release, volumes, and Secrets, in the kube context validation
deploys to (`docker-desktop`) whatever context is current, and removes the images
its validation built under the change's tags; nothing else is touched. A namespace or
image already gone is not a failure. When it fails — Docker or the cluster not
answering, an image in use — do not retry or work around it: say so in the report,
with the command to rerun once the cause is gone, and go on.

## 9. Push

When step 7 committed a figure, push it with `make push-branch`, the guarded push
of exactly `HEAD`; if it refuses, stop and report its reasons.

## 10. Copy the history, last

A change worked in its own clone — its `.git/config` names a `[remote "workspace"]`
— keeps its records and evidence only there, untracked. As the last act, after
everything above, run `make change-history CHANGE=<change>`: it copies the archived
change's `reviews/` and the validation evidence its records name into the owner's
workspace, at the same paths, where sessions working other changes find them. It is
safe to repeat: files already there are left, files that grew are extended, and a
file that differs otherwise is refused, named, and never overwritten. Report each
refused file: the owner reconciles it, and removing the clone refuses until they
do. What the workflow writes after this — the outcome of this run, a later round on
the pull request — reaches the workspace with the next copy, which removing the
clone (`make change-clone-remove`, the owner's) makes first. A change worked in the
owner's workspace has its history there already: skip this step.

## 11. Report

Tell the owner:

- each dependent released, its status before and after, and why;
- any row whose notes were rewritten;
- the commits, and the index and citation checks' results;
- the capacity figure recorded, or that none was, and why;
- the teardown's result;
- the history copy's result, each refused file named;
- the two drafts, and anything on the branch that the pull request would also carry.
