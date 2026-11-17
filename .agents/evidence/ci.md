# The CI evidence kind

The `ci` kind shows what only a push produces: a run of a CI workflow a complete
section owes, dispatched on the change's branch for the commit under validation, and
its jobs compared with the same workflow's latest run on `dev`. No push of a change's
branch triggers these workflows, so an implementation session can never produce this
evidence.

## What may be owed

Only the workflows `scripts/ci_evidence.py` lists in `DISPATCHABLE` can be dispatched,
and none of them publishes: several workflows that accept a dispatch publish, so a plan
line naming one would publish from a feature branch. The list lives in the script so it
binds interactive runs too. Only the owner extends it. A line owing another workflow is
refused by the dispatch, which names the list: its observation is then absent, a
failure of unknown cause for triage to take to design.

## Reading its evidence

The collect waits on GitHub, for the run of the commit newer than the marker the
dispatch printed. It reads only the dispatch's run, never a pull request's run of the
same commit, which tests a merge. Each attempt is a directory named by the UTC time
it started, `%Y%m%dT%H%M%S.%fZ`, so path order is time order and the last attempt is
the current one. It keeps, under `runs/<run>/`, the run's whole log (`actions.log`),
its jobs and steps as GitHub reports them (`run.json`), and each job's log
(`jobs/<job>.log`); and the same for the baseline: the latest completed `dev` run of
the workflow, not a pull request's, whose head commit the validated commit contains —
usually the merge base — skipping a newer `dev` run of code the branch lacks.

`summary.json`'s `evidence` names the run and its conclusion, the baseline and its
commit, and, for each job, its conclusion, failing steps, error lines, and failures —
each failing test's ID and exception type from pytest's short summary, or, for a job
that printed none, its failing step with the runner's error lines — each classed:

- `inherited`: the baseline's same job fails that test with the same type and
  outcome, or that step with the same error lines;
- `new`;
- `uncomparable`: no baseline, or one that could not be chosen, fetched, or read; a
  job the baseline lacks or skipped; a job of which either log holds no line; a
  failing test whose line names no exception type; a job failing at no named step;
  error lines saying only that the step failed; or one side naming failing tests where
  the other names only the same step failing.

The job's `reason`, or the failure's, says why. When no job failed, a baseline that
could not be had is only a warning. The attempt passes when the run produced evidence
and every failure is `inherited`: it says nothing of whether an owed job passed and
showed what it owes, which validation judges. A run with no evidence fails the
attempt's `evidence` step, `evidence.no_evidence` saying why: the fetch failed (a run
never listed, or its log not fetched; the `fetch` step's log says which), the fetch
kept no run, the run could not be read, or it was cancelled or is not completed.

The commit is checked before and after the collect: an attempt whose step fails with
"HEAD is now …" describes no one commit, so validation stops.

## Telling its failures apart

`tests.yml` fails on `dev` in jobs unrelated to any change, so a run's conclusion
alone says little.

- **The owed job.** Judge it from its log under `jobs/`: it passed, and its log shows
  what the owed line says it must. An owed job that failed, or an observation its log
  does not show, is a failure caused by the commit or of unknown cause, whatever its
  failures' classes: an owed job failing on `dev` too still owes what it owes.
- **Every other failing job**, by class: `inherited` is already failing on `dev`,
  reported naming the baseline and never a finding; `new` is diagnosed like any
  failure — commit, environment, or unknown — from the job's log; `uncomparable` is of
  unknown cause, so a finding.
- **No evidence.** A run that produced none for a reason the logs place outside the
  commit — `gh` not signed in, a runner outage, a run cancelled by a newer dispatch on
  the same branch, a run never listed — is environmental: its remedy is signing in,
  waiting out the outage, or a new attempt of that workflow alone, which dispatches
  again and collects past the new dispatch's marker. A fetch that kept no run, or a
  run that could not be read, is diagnosed from the `fetch` and `run` steps' logs like
  any failure, and is of unknown cause when they do not place it.

The kind's result is `passed` when every owed job passed and showed its observation
and no other failure is a finding; `failed` with a finding; and `inconclusive` when its
run produced no evidence and the owner declined a new attempt.

## Its section of the record

The record's header line names each workflow's run, and `## CI` holds a row per owed
job:

```markdown
- **CI:** <workflow> run <id>, <conclusion> — <the owed jobs' result>; <the jobs failing not owed, and whether every failure is also in dev's run>

## CI

| Workflow | Run | Owed by | Job | Owed observation | Result |
|---|---|---|---|---|---|
| <file> | <id> | §<section>, <task> | <job> | <what the job must show> | passed \| failed |

Baseline: dev's <file> run `<id>` at `<short commit>` (<the merge base, or how it relates to it>); or: no completed dev run of code the branch contains.

Not owed: `<job>` — <conclusion>, <each failure: the test and its exception type, or the failing step, with its class and, for an inherited one, how it fails in the baseline>; …
```

Both are left out when nothing is owed. Validation's report names each run, with its
owed observations and its baseline.

## Its cleanup

None: the runs are GitHub's, and each attempt keeps its logs.

## In a plan

A section whose change only a run of a dispatchable workflow can show owes it on its
own line of the verification task, beside `End-to-end:`, naming the kind and the
workflow, then the job and what it must show:

```
Owed by validation (ci tests.yml): job `test · test-deployment-packaging` —
`azure/setup-helm` installs v4.3.0, and `make -C helm test-render` prints
`helm v4.3.0` before the first render and passes.
```

Once the section is complete, every validation of the change dispatches the workflow
and judges the job. Owing a workflow the list does not hold is a design question.
