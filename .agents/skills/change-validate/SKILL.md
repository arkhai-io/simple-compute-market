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

**The environment is yours to control, within your change.** Validation assumes
full control of its checkout's wheelhouse in `.dist`, of the images tagged for its
change, and of its change's namespace in the allowed kube context: the scripts
scale, delete, and replace what that namespace holds without asking. Another
change may be validated beside you, in its own clone, namespace, and tags, sharing
the Docker daemon, the node's memory, and the CPU; you never touch its namespace or
images, and nothing else should be building in your checkout while you run.

## Running unattended

Run interactively, as most runs are, this section does not apply, and nothing else
in the skill changes. When this skill runs through `scripts/run_change_step.py` —
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
  a wildcard after `-C` would also span a push.
- **The end is an outcome.** An environmental failure (section 5) is a
  `question` naming the evidence and the remedy, awaiting the owner's word; once
  answered, take only the action the answer names, and rerun the part. When the
  record is written, end with `finished`, `next` naming triage when the record has
  a `V<n>` or the round's review awaits triage, the implementation review when it
  has not landed, and otherwise what follows a passing validation of this commit —
  the next round, the pre-closeout review, closeout, or archive cleanup, as the
  next-step computation names it. `next` is the owner's to read, never a route.

## 1. Check that this commit may be validated

`make validate` refuses while a round view is open in this checkout (`make
round-view` of a change worked in the owner's workspace): the branch then points
at the round's base, not its commit. If you were started some other way, `make
round-view-closed` says the same; stop and ask the owner to run `make round-done`.
A view the owner opens in their workspace for a change worked in its own clone
moves nothing here, and validation runs beside it.

- **Branch.** The checked-out branch carries the change: its directory and latest
  commits are on it. Several changes are often in flight in one checkout; if the
  branch belongs to another change, stop and ask the owner — unless the change's
  log holds the owner's decision that it runs on this branch: run
  `git branch --show-current`, then
  `python3 scripts/run_change_step.py log <change> --branch <that branch>`; a line
  it prints is that decision, and the branch is accepted.
- **Worktree.** `git status --porcelain --untracked-files=all` is empty. Ignored
  files do not count.
- **Commit.** Record `git rev-parse HEAD` and the branch. Every part below describes
  that commit; if `HEAD` moves while you work, stop: the evidence no longer belongs
  to one commit.
- **Instructions.** If the invocation says `HELM_ALL_SCENARIOS=1`, the Helm part
  runs every pipeline scenario rather than only those the default charts serve, to
  find which the charts serve now (step 3).

## 2. Start the pipeline first

The pipeline is by far the slowest part, so it runs while everything else does:

1. `gh auth status` — without it the dispatch fails after the push.
2. `make push-branch` — the guarded push of exactly `HEAD`, never forced. If it
   refuses, stop and report its reasons.
3. Record the newest end-to-end run ID —
   `gh run list --workflow e2e.yml --limit 1 --json databaseId --jq '.[0].databaseId'`
   — then `make run-e2e`, which dispatches the workflow on the branch. The steps
   that commit push their commits, but a push starts no run: the pipeline runs on
   dispatch and nightly, so the run that describes `HEAD` is the one you dispatch.
4. `make fetch-e2e-logs E2E_AFTER_RUN=<that ID>`, in the background. It waits for
   a run of `HEAD` newer than that ID to be listed — so a commit validated before
   never fetches its earlier run — then for it to finish, and downloads its logs
   under `.snapshot/e2e-logs/<run-id>/`. Its last lines name the run and its
   conclusion; a successful fetch means the logs arrived, not that the run passed.
   Run it as written, with no shell redirect of its output: a redirect is a
   write no rule admits unattended, and the harness keeps a background command's
   output in a file, which is what the wait below reads.

Run long commands in the background and wait for them to finish, rather than
inside a call that will time out. Wait inside one Bash call, with a blocking
read-only `tail -f … | grep -m1` on the command's output matching the line it
prints when it ends — a part's result line, the fetch's run-and-conclusion line
— never by ending the turn: under the wrapper a turn's end is an outcome, so a
turn ended with a part in flight is logged as a stop. A single call blocks for
at most ten minutes, and the pipeline can take longer, so when the `tail` times
out, repeat it, still without ending the turn. Never a shell loop: `bash -c` has
no allow rule unattended and will not get one, since no rule admits a loop
without admitting any command. The Helm part can outlast one call too — its
scenarios may take up to thirty minutes, and another change's validation may share
the machine — so it runs in the background and is waited for the same way, on its
`<part> validation of <commit>, attempt <n>: PASSED` or `FAILED` line, or the
`ERROR:` line of a part that could not start. A running
part prints one line as each step starts, naming the step's log under
`.snapshot/validation/`, and one as it ends, so its output shows how far it has
got.

## 3. Run the local and Helm parts

Run them one after the other while the pipeline runs: they share the machine's
Docker and CPU. Both start with `make dist-clean`, so every wheel tested is built
from this commit rather than left in `.dist` by another branch.

1. `make validate-local` — `make check-packaging`, then `make test`.
2. `make validate-helm CHANGE=<change>`, adding `HELM_ALL_SCENARIOS=1` when the
   invocation asked for it. It runs in the change's own namespace,
   `validate-<change>` (a name longer than a namespace allows is cut and ends in
   a short hash), which its summary names. Preflights first,
   before anything slow: the kube context (`HELM_CONTEXT`, `docker-desktop` unless
   the owner names another), the storefront environment, the Docker daemon, a
   `Ready` node, Foundry's `cast`, which derives the namespace's Secrets, a
   warning if the Docker credential helper does not answer, and the capacity
   preflight: a warning when no metrics source answers (`metrics`), so no memory
   is recorded; a warning when `helm/validation-capacity.toml` records no figure
   (`capacity`), so the check is skipped; and otherwise the namespaces running
   the validation release, plus this one, times the figure, against the node's
   allocatable memory. Then the images, built under the change's own tags; the
   storefront environment reinstalled from them; the render checks, with the
   chart-to-loader check running this commit's code; the release replaced —
   workloads an earlier run left up scaled to zero, its pods and volumes deleted
   and gone, the namespace's Secrets created, the release upgraded in place from
   zero (or uninstalled and installed when the chart refuses the upgrade, a
   warning on the `deploy` step), resumed, and each workload rolled out; the
   served scenarios as a pod in the namespace (`helm test`, reaching services by
   name); and, once the release has been touched, whatever the deploy or the
   scenarios did, the namespace's evidence kept and its workloads scaled to zero —
   only the scale-down when the checkout is no longer the commit. A part that
   stops before it touches the release, at a preflight, the build, or the render
   checks, keeps no namespace evidence. Only a run without `CHANGE`, in
   `default`, refuses first a release volume carrying
   `helm.sh/resource-policy: keep`, which an owner's own deploy left there.

Run the Helm part even when the local part failed, so one triage sees every
failure — unless the local part failed because the worktree was not clean or
`HEAD` moved, which the scripts check after every step and report as "the worktree
changed" or "HEAD is now …": the tree is no longer the commit, so stop.

Each attempt of a part writes its summary and every step's log under
`.snapshot/validation/<short commit>/<part>/<attempt>/`, and prints that path. The
Helm part lists the pipeline scenarios it did not run because the charts cannot
serve them; those are never passes. Its attempt also keeps the namespace's
evidence: the scenario pod's log and exit status (`scenarios.log`,
`scenarios.exit`, and `evidence.scenarios` in `summary.json`, its step passing
only on the pod's own exit status of 0); every pod's log under `pods/`, with a
restarted container's previous log; each pod's status (`pods.json`); the
namespace's events (`events.log`) and the nodes' (`node-events.log`); the
validation release's workloads in every other namespace, with their replicas, at
the preflight and at the end (`evidence.other_namespaces_at_start`,
`evidence.other_namespaces`); the rendered requests and limits (`resources.txt`)
and whether they changed since the namespace's previous validation
(`evidence.resources.changed`); and the namespace's sampled memory, when a metrics
source measured it (`memory.peak_bytes`).

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

**The Helm part's memory.** Another change's validation may run on the same node,
and two capacity preflights can pass together, so a pod can still fail for memory.
Classify such a failure from the attempt's evidence, never from the symptom alone,
since a commit that raises a request, lowers a limit, or leaks fails the same way:

- **Environment**, when a pod could not be scheduled for memory — `events.log` has
  `FailedScheduling` naming insufficient memory, which says the node's allocatable
  memory is already taken — or was evicted for memory — `events.log` has
  `Evicted` naming the node low on memory, which the node's memory pressure in
  `node-events.log` confirms when its events were still kept — while another
  change's namespace had the validation release up: a `validate-…` namespace
  other than this one with a replica above zero in
  `evidence.other_namespaces_at_start` or `evidence.other_namespaces`. Those are
  read at the preflight and at the end, not at the failure, so say which showed
  it. The owner's own release in `default` is not another change's validation. The remedy is
  scaling that namespace's release to zero (`kubectl scale --namespace <namespace>
  --replicas=0 deployments,statefulsets --selector
  app.kubernetes.io/instance=<release>`), or rerunning once its validation has
  ended. When the commit also changed the rendered requests or limits
  (`evidence.resources.changed`), say so beside the remedy: the rerun with nothing
  else running is what tells contention from the commit's own demand, and a pod
  that again cannot be scheduled then is the commit's.
- **Commit**, when a container was killed at its own limit — `pods.json` gives
  `OOMKilled` as a container's last or current termination reason,
  `resources.txt` gives that container a memory limit, and `node-events.log`
  shows no system out-of-memory kill or memory pressure on the node at the time;
  read its `pods/<pod>.previous.log` for what it was doing — or when, outside the
  case above, the commit changed the rendered requests or limits
  (`evidence.resources.changed` is true: compare `resources.txt` with the
  previous validation's file it names).
- **Unknown** otherwise — an `OOMKilled` with no limit or beside the node's own
  memory pressure, contention only from `default`, or evidence an `evidence`
  warning left empty — so `failed` and triaged.

A `capacity` step that failed with a detail beginning `environmental:` is the
preflight finding the release would not fit: an environmental failure, put to the
owner with the remedy the detail gives. A `capacity` failure without that prefix —
an unreadable capacity file, or the cluster's memory or other namespaces that
could not be read — is diagnosed like any failure. A warning is not a failure;
report every warning step under `## Helm`, with what it means for the run:
`credential helper` (image builds may fail to look up registry credentials),
`metrics` (no memory recorded), `capacity` (the capacity check skipped), `deploy`
(the upgrade was refused and the release uninstalled and installed), `memory` (a
sample failed), `evidence` (that evidence was not kept, and its key is empty), and
`scenario pod` (its exit status could not be read).

## 5. Settle environmental failures with the owner

A failure you diagnose as environmental with good confidence is not a finding about
the change, and triage cannot fix it. Settle it now:

1. Stop, and tell the owner the failure, its evidence, and the remedy — for
   example, another change's namespace to scale to zero, a volume that outlived
   its deletion (`volumes gone`) to delete, the daemon to restart.
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

Write `reviews/NN-validation.md` in the change's directory — what
`python3 scripts/find_change.py <change>` prints, under the archive once closeout
has archived the change — numbered after every
file in `reviews/` and `reviews/transcripts/` at the moment you write it — a review
started beside this validation may have taken a number since you began. Never
overwrite a record: if the name exists, take the next number.

The result, overall and per part, is one of:

- `passed` — every part ran and passed;
- `failed` — at least one failure is caused by the commit, or its cause is unknown;
- `inconclusive` — no failure is caused by the commit, but some part produced no
  evidence for an environmental reason the owner declined or could not remedy.

`make review KIND=pre-closeout` reads the `Commit:` and `Result:` lines, so keep
them exactly as the template shows: the full commit, then the result word, with no
backticks or emphasis around either.

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

Namespace: <the summary's namespace>. Scenario pod: <pod>, exit <status>. Peak
memory: <bytes, or none measured>. Warnings: <each warning step and what it means,
or none>.

| Attempt | Step | Result | Duration |
|---|---|---|---|

Not run against Helm: <scenario> — <what the charts do not provide>; …

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

When the run used `HELM_ALL_SCENARIOS=1`, the scenarios outside the served list
(`HELM_SCENARIOS` in `scripts/validate_slice.py`) ran to test the list, not the
commit, and the script's `e2e` step fails whenever one of them does. Judge the Helm
part by the served scenarios alone. Under `## Helm`, list each other scenario with
what it showed: failed because the charts do not serve it (expected), failed for
another reason (diagnose it like any failure), or passed (it can join the list).
Report a list that should grow under "About the validation".

## 8. Report

Tell the owner the commit, the result and each part's, the pipeline run and its
conclusion, the coverage of the change, the scenarios not run against Helm, each
environmental failure and how it was settled, each failure with its diagnosis, and
anything under "About the validation". Then say what comes next. When this is a
round's validation beside its review, or it has a `V<n>`: the implementation
round — this record, the implementation review of the same commit, and the
owner's own notes — is triaged together in a fresh session,
`make triage CHANGE=<change>`, which fixes what the owner accepts; the fix commit
is then validated again. When it is the passing validation of a fix commit, of
`HEAD` before closeout, or of a closeout correction, the change moves on without a
triage, to whatever the triage before it recorded.
