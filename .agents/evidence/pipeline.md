# The pipeline evidence kind

The `pipeline` kind shows the end-to-end scenarios passing for the commit under
validation: a run of the repository's end-to-end pipeline on GitHub Actions whose head
is that commit, dispatched on the change's branch once its push has landed, and its
logs collected once the run ends. No local suite stands in for it, and the pipeline
deploys no chart, so it and the `helm` kind each show what only it can.

The pipeline runs one lane per market domain, each its own job and its own compose
project, so one domain's failure never hides another's evidence;
[`TESTING.md`](../../docs/development/TESTING.md) describes the lanes and the scenarios
each runs.

## Reading its evidence

The collect waits for the run dispatched for the commit, newer than the marker the
dispatch printed — a commit validated before never collects its earlier run — and for
it to finish. Each attempt is a directory named by the UTC time the collect started,
`%Y%m%dT%H%M%S.%fZ`, so path order is time order and the last attempt is the current
one. It holds:

- `actions.log`, the run's whole log;
- each lane's `compose-logs.txt`, under its artifact's directory, the lane's
  containers' logs;
- `summary.json`, naming the run, its conclusion, the logs kept, whether it passed,
  and, when no run or log could be had, an `error` saying why.

The collect fails unless the run concluded `success`. An attempt is written whatever
happened, so a collect that found no run leaves an attempt saying so: present
evidence, failed, which the gathering never replaces on its own. Only a new attempt
of the kind dispatches a new run, which validation makes once it has diagnosed the
failure as environmental and the owner has allowed it.

## Telling its failures apart

For each failing scenario, read the lane's job in `actions.log`, then the lane's
`compose-logs.txt`: the service whose own log explains the failure, and the code or
configuration it points at. A run that never started, was cancelled by a newer
dispatch on the same branch, or met a runner outage is environmental, its remedy a
new attempt; `gh` not signed in is environmental, its remedy signing in. A run that
concluded `failure` with a scenario failing is diagnosed from its logs like any
failure.

## Its section of the record

`## Pipeline` names each lane, with the scenarios it ran and their results, and the
record's header line names the run and its conclusion:

```markdown
- **Pipeline:** run <id>, <conclusion> | waived

## Pipeline

<each lane, with the scenarios it ran and their results>
```

Validation's report names the run and its conclusion.

## Its cleanup

None: the run and its logs are GitHub's and the attempt's.

## In a plan

This repository's end-to-end scenarios are pytest markers in `e2e-tests/`. A section's
`End-to-end:` line names the markers that exercise its behaviour once deployed —
including any it adds — or says that none does. Validation reads them, and adds any
scenario the change's diff added or modified under `e2e-tests/`, to say whether the
pipeline's result is evidence for the change; the coverage table of the record names
each with its lane. The `helm` kind runs the scenarios the default charts can serve,
its served list `HELM_SCENARIOS` in `scripts/validate_slice.py`, and reports every
other as not run against Helm.
