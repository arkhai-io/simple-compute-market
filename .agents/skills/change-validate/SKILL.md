---
name: change-validate
description: Validate the commit at HEAD of an OpenSpec change before its implementation is triaged — push it and run the end-to-end pipeline, run the local and Helm validation parts meanwhile, diagnose every failure from its logs, and write reviews/NN-validation.md. Observes only; never edits, relocks, commits, or fixes. Use after implementation sections are committed, beside an implementation review, when the owner says "validate <change>", or when `make validate` invokes you.
---

# Validating a committed slice

Validation describes one commit and leaves the checkout exactly as it found it. It
is evidence, not repair: when a part fails, you find out why from its logs and
write that down, and the failure is triaged with the implementation round it
belongs to. A fix belongs to that triage, never to you.

You never edit a tracked file, run `make lock`, commit, stash, reset, clean, force a
push, push any branch but the change's own, or change the kube context. When a
guard refuses — a dirty worktree, a detached `HEAD`, another branch's upstream, the
wrong kube context — stop and report it as it is: every refused state means
something unexpected happened, and fixing it would hide that.

## 1. Check that this commit may be validated

- **Branch.** The checked-out branch carries the change: its directory and latest
  commits are on it. Several changes are often in flight in one checkout; if the
  branch belongs to another change, stop and ask the owner.
- **Worktree.** `git status --porcelain --untracked-files=all` is empty. Ignored
  files do not count.
- **Commit.** Record `git rev-parse HEAD` and the branch. Every part below describes
  that commit; if `HEAD` moves while you work, stop: the evidence no longer belongs
  to one commit.

## 2. Start the pipeline first

The pipeline is by far the slowest part, so it runs while everything else does:

1. `make push-branch` — the guarded push of exactly `HEAD`, never forced. If it
   refuses, stop and report its reasons.
2. Record the newest end-to-end run ID before dispatching —
   `gh run list --workflow e2e.yml --limit 1 --json databaseId --jq '.[0].databaseId'`
   — then `make run-e2e`, which dispatches the workflow on the branch.
3. `make fetch-e2e-logs E2E_AFTER_RUN=<that ID>`, in the background. It waits for
   a run of `HEAD` newer than that ID to be listed — so a commit validated before
   never fetches its earlier run — then for it to finish, and downloads its logs under
   `.snapshot/e2e-logs/<run-id>/`. Its last lines name the run and its
   conclusion; a successful fetch means the logs arrived, not that the run passed.

Run long commands in the background and wait for them to finish, rather than
inside a call that will time out.

## 3. Run the local and Helm parts

Run them one after the other while the pipeline runs: they share the machine's
Docker and CPU.

1. `make validate-local` — `make dist-clean`, so every wheel tested is built from
   this commit rather than left by another branch, then `make check-packaging`
   and `make test`. Both parts remove the shared wheelhouse; tell the owner before
   you start if another session may be building in this checkout.
2. `make validate-helm` — `make dist-clean` and `make build-dev`, the VM
   storefront environment reinstalled from the rebuilt wheels, the chart render
   checks with the chart-to-loader check running against this commit's code,
   deploy and forward, the pipeline's scenarios
   against the forwarded services, and unforward. It deploys to `HELM_CONTEXT`
   only (`docker-desktop` unless the owner names another) and replaces the
   release running there.

Run the Helm part even when the local part failed, so one triage sees every
failure — unless the local part failed because the worktree was not clean, which
means the tree is no longer the commit; then stop.

Each part prints a summary and writes it, with every step's log, under
`.snapshot/validation/<short commit>/<part>/`. The Helm part lists the pipeline scenarios
it did not run because the charts cannot serve them; those are never passes.

## 4. Diagnose every failure

For each failed step and each failing pipeline scenario, read its log — the step
log, `actions.log`, and the lane's `compose-logs.txt` — and establish:

- what failed: the test, the assertion or error, and the log lines that show it;
- why, as far as the logs show: the service whose own log explains the failure,
  and the code or configuration the evidence points at;
- whether the cause is the change, the environment (a registry or network
  failure, a runner problem), or not yet known; say how sure you are and what
  would settle it.

Read failures from the logs; never report only an exit status. Do not rerun a
failed step to get a pass. If you rerun one to tell a flake from a failure, report
both results.

## 5. Write the validation record

Write `openspec/changes/<change>/reviews/NN-validation.md`, numbered after every
file in `reviews/` and `reviews/transcripts/` at the moment you write it — a review
started beside this validation may have taken a number since you began:

```markdown
# Validation — <change> — <short commit>

- **Commit:** <full commit> on <branch>
- **Result:** passed | failed
- **Pipeline:** run <id>, <conclusion>

## Local

| Step | Result | Duration |
|---|---|---|

## Helm

| Step | Result | Duration |
|---|---|---|

Not run against Helm: <scenario> — <what the charts or `make forward` do not provide>; …

## Pipeline

<each lane, with the scenarios it ran and their results>

## Failures

### V1 — <the failure in one line>

- **Part:** local | helm | pipeline
- **Evidence:** <log paths and the lines that show it>
- **Cause:** change | environment | unknown

<the diagnosis, and what would settle it if the cause is unknown>
```

Write `None.` under `## Failures` when every part passed. Failures are labelled
`V<n>`, so triage can carry them beside review findings without renumbering.

## 6. Report

Tell the owner the commit, each part's result, the pipeline run and its
conclusion, the scenarios not run against Helm, and each failure with its
diagnosis. Then say what comes next: the implementation round — this record, the
implementation review of the same commit, and the owner's own notes — is triaged
together with `change-triage`, which fixes what the owner accepts; the fix commit
is then validated again.
