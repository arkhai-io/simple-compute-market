---
name: change-validate
description: Validate the commit at HEAD of an OpenSpec change before its implementation is triaged — push it and run the end-to-end pipeline, run the local and Helm validation parts meanwhile, diagnose every failure from its logs, settle environmental failures with the owner, and write reviews/NN-validation.md. Never edits, relocks, commits, or fixes the commit. Use after implementation sections are committed, beside an implementation review, when the owner says "validate <change>", or when `make validate` invokes you.
---

# Validating a committed slice

Validation describes one commit, and is evidence about it. When a part fails, you
find out why from its logs and write that down; a failure the commit causes is
triaged with the implementation round it belongs to, and its fix belongs to that
triage, never to you.

**What you never change is the commit.** You never edit a tracked file, run
`make lock`, commit, stash, reset, clean, force a push, or push any branch but the
change's own. When a repository guard refuses — a dirty worktree, a detached
`HEAD`, another branch's upstream — stop and report it as it is: each such state
means something unexpected happened in the repository, and fixing it would hide
that.

**The environment is yours to control.** Validation assumes full control of the
developer's machine: the Docker daemon, the allowed kube context, the release in
it, the port-forwards, and the wheelhouse in `.dist`. The scripts stop
port-forwards and uninstall the release without asking. One change is validated at
a time; nothing else should be building in the checkout while you run.

## 1. Check that this commit may be validated

- **Branch.** The checked-out branch carries the change: its directory and latest
  commits are on it. Several changes are often in flight in one checkout; if the
  branch belongs to another change, stop and ask the owner.
- **Worktree.** `git status --porcelain --untracked-files=all` is empty. Ignored
  files do not count.
- **Commit.** Record `git rev-parse HEAD` and the branch. Every part below describes
  that commit; if `HEAD` moves while you work, stop: the evidence no longer belongs
  to one commit.
- **Instructions.** If the invocation says `HELM_ALL_SCENARIOS=1`, the Helm part
  runs every pipeline scenario, ignoring its exclusion list, to establish which the
  charts cannot serve (step 3).

## 2. Start the pipeline first

The pipeline is by far the slowest part, so it runs while everything else does:

1. `gh auth status` — without it the dispatch fails after the push.
2. `make push-branch` — the guarded push of exactly `HEAD`, never forced. If it
   refuses, stop and report its reasons.
3. Record the newest end-to-end run ID before dispatching —
   `gh run list --workflow e2e.yml --limit 1 --json databaseId --jq '.[0].databaseId'`
   — then `make run-e2e`, which dispatches the workflow on the branch.
4. `make fetch-e2e-logs E2E_AFTER_RUN=<that ID>`, in the background. It waits for
   a run of `HEAD` newer than that ID to be listed — so a commit validated before
   never fetches its earlier run — then for it to finish, and downloads its logs
   under `.snapshot/e2e-logs/<run-id>/`. Its last lines name the run and its
   conclusion; a successful fetch means the logs arrived, not that the run passed.

Run long commands in the background and wait for them to finish, rather than
inside a call that will time out.

## 3. Run the local and Helm parts

Run them one after the other while the pipeline runs: they share the machine's
Docker and CPU. Both start with `make dist-clean`, so every wheel tested is built
from this commit rather than left in `.dist` by another branch.

1. `make validate-local` — `make check-packaging`, then `make test`.
2. `make validate-helm`, or `make validate-helm HELM_ALL_SCENARIOS=1` when the
   invocation asked for it. Preflights first, before anything slow: the kube
   context (`HELM_CONTEXT`, `docker-desktop` unless the owner names another), the
   storefront environment, the Docker daemon, a `Ready` node, the chart's
   out-of-band Secrets, a warning if the Docker credential helper does not answer,
   the port-forwards stopped and their ports free, and no release volume carrying
   `helm.sh/resource-policy: keep` — one would survive the uninstall and hand its
   state to the new deployment. Then the images, the storefront environment
   reinstalled from them, the render checks with the chart-to-loader check running
   this commit's code, the release uninstalled and its volumes gone, a local
   deployment from no persistent state, the pipeline's scenarios against the
   forwarded services, and unforward.

Run the Helm part even when the local part failed, so one triage sees every
failure — unless the local part failed because the worktree was not clean, which
means the tree is no longer the commit; then stop.

Each attempt of a part writes its summary and every step's log under
`.snapshot/validation/<short commit>/<part>/<attempt>/`, and prints that path. The
Helm part lists the pipeline scenarios it did not run because the charts cannot
serve them; those are never passes.

## 4. Diagnose every failure

For each failed step and each failing pipeline scenario, read its log — the step
log, `actions.log`, and the lane's `compose-logs.txt` — and the state it points at,
such as pod logs and events. Establish:

- what failed: the test, the assertion or error, and the log lines that show it;
- why, as far as the evidence shows: the service whose own log explains it, and the
  code or configuration it points at;
- the cause: **commit** (the change's code, tests, or configuration),
  **environment** (the machine, the cluster, a registry, the network, state left by
  an earlier deployment), or **unknown**; say how sure you are and what would
  settle it.

Read failures from the logs; never report only an exit status. Unknown is never
treated as environment: a failure you cannot place is triaged.

## 5. Settle environmental failures with the owner

A failure you diagnose as environmental with good confidence is not a finding about
the change, and triage cannot fix it. Settle it now:

1. Stop, and tell the owner the failure, its evidence, and the remedy — for
   example, the retained volume to delete, the process holding a port, the daemon
   to restart.
2. Wait for the owner's word: either the owner carries out the remedy, or names the
   action for you to take. Take only the action named.
3. Rerun that part. It is a new attempt with its own directory; the earlier
   attempt stays as evidence, and the record reports both.

When the owner declines, or the remedy cannot be applied now, the part is
`inconclusive`. Never rerun a failed step only to get a pass: a rerun is to tell an
environmental fault from a failure, or to validate after a remedy, and its first
result is always reported.

A defect in the validation tooling itself — a check that misled you, a preflight
that would have caught this, a step that depends on state it should not — goes in
the record's section about the validation, not among the failures.

## 6. Name the scenarios that cover the change

The change's task notes name the end-to-end scenarios each section's verification
relies on. Read them, and add any scenario the change's diff added or modified under
`e2e-tests/`. For each, give its basis and its result on each lane that ran it. When
no scenario exercises the change's behaviour, say so plainly; triage needs to know
that a green pipeline is not evidence for this change.

## 7. Write the validation record

Write `openspec/changes/<change>/reviews/NN-validation.md`, numbered after every
file in `reviews/` and `reviews/transcripts/` at the moment you write it — a review
started beside this validation may have taken a number since you began.

The result, overall and per part, is one of:

- `passed` — every part ran and passed;
- `failed` — at least one failure is caused by the commit, or its cause is unknown;
- `inconclusive` — no failure is caused by the commit, but some part produced no
  evidence for an environmental reason the owner declined or could not remedy.

```markdown
# Validation — <change> — <short commit>

- **Commit:** <full commit> on <branch>
- **Result:** passed | failed | inconclusive — <one line why>
- **Parts:** local <result> · helm <result> · pipeline <result>
- **Pipeline:** run <id>, <conclusion>

## Local

| Attempt | Step | Result | Duration |
|---|---|---|---|

## Helm

| Attempt | Step | Result | Duration |
|---|---|---|---|

Not run against Helm: <scenario> — <what the charts or `make forward` do not provide>; …

## Pipeline

<each lane, with the scenarios it ran and their results>

## Coverage of this change

| Scenario | Basis | Lane | Result |
|---|---|---|---|

<or: no end-to-end scenario exercises this change's behaviour>

## Environment

<each environmental failure: its evidence, the remedy, what the owner decided, and
the attempt that followed; or `None.`>

## Failures

### V1 — <the failure in one line>

- **Part:** local | helm | pipeline
- **Evidence:** <attempt, log paths, and the lines that show it>
- **Cause:** commit | unknown

<the diagnosis, and what would settle it if the cause is unknown>

## About the validation

<defects in the validation tooling this run exposed; or `None.`>
```

Only failures caused by the commit, or of unknown cause, go under `## Failures`,
labelled `V<n>` so triage can carry them beside review findings; write `None.` when
there are none. Environmental failures go under `## Environment` and are never
findings.

When the run used `HELM_ALL_SCENARIOS=1`, the scenarios on the exclusion list ran
to test the list, not the commit, and the script's `e2e` step fails whenever one
of them does. Judge the Helm part by the other scenarios alone. Under `## Helm`,
list each listed scenario with what it showed: failed only for a service the
charts do not provide (expected; the list holds), failed for another reason (a
failure, diagnosed like any other), or passed (the list is stale). Report a stale
or wrong list under "About the validation".

## 8. Report

Tell the owner the commit, the result and each part's, the pipeline run and its
conclusion, the coverage of the change, the scenarios not run against Helm, each
environmental failure and how it was settled, each failure with its diagnosis, and
anything under "About the validation". Then say what comes next: the
implementation round — this record, the implementation review of the same commit,
and the owner's own notes — is triaged together with `change-triage`, which fixes
what the owner accepts; the fix commit is then validated again.
