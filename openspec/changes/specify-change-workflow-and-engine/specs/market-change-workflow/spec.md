## ADDED Requirements

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository MUST state, for each role the change workflow asks of an adopting
repository, how it provides that role: the make target, path, branch, or document
that fills it. Every make target and repository path the workflow's skills, step
table, and make fragment name MUST appear in that statement, and so MUST the
engine's own assumptions about this repository, marked as maintained by review.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the statement names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the statement names `main` and `dev`, which the guarded push refuses

### Requirement: MCW-v3tf Validation builds the packages it tests from the commit

Each part of this repository's validation that builds MUST build the internal
packages it tests from the commit under validation, never from wheels another branch
left in the shared wheelhouse.

#### Scenario: Another branch left a wheel in the wheelhouse

- **WHEN** the shared wheelhouse holds a wheel another branch built of a package the
  validated commit changes
- **THEN** validation tests the package as built from the validated commit

### Requirement: MCW-zk52 End-to-end evidence comes from the commit's own pipeline run

Validation's end-to-end evidence MUST come from a pipeline run whose head commit is
the commit under validation.

#### Scenario: An earlier pipeline run exists on the branch

- **WHEN** validation dispatches the end-to-end pipeline and an earlier, finished
  run exists on the same branch
- **THEN** validation reports the run whose head commit is the validated commit,
  never the earlier one

### Requirement: MCW-gvqb Owed CI evidence names its workflow, its job, and what the job must show

Evidence a section owes validation from CI MUST be named by its workflow, its job,
and what that job must show.

#### Scenario: A section owes a CI job's result

- **WHEN** a section's change can be shown only by a job of a CI workflow no push of
  the change's branch triggers
- **THEN** the section's notes name the workflow, the job, and what the job must
  show as owed by validation, and validation dispatches that workflow and judges
  that job

### Requirement: MCW-3i99 Validation dispatches the owed CI workflows from a fixed list

Validation MUST dispatch, on the change's branch, each workflow a section complete
at the validated commit names as owed, and MUST dispatch only workflows on a fixed
list that holds none that publishes; adding to the list MUST be a tracked change by
the owner.

#### Scenario: A plan owes a workflow that publishes

- **WHEN** a section names `publish-pypi.yml` as owed by validation
- **THEN** the dispatch is refused, naming the workflows validation may dispatch, and
  nothing is published

#### Scenario: A dispatched run is cancelled

- **WHEN** the run validation dispatched is cancelled by a newer dispatch on the same
  branch
- **THEN** the part produced no evidence for an environmental reason, which goes to
  the owner with its remedy, and the part is rerun on the owner's word

### Requirement: MCW-7hr1 An owed job is judged from the commit's own run

Validation MUST judge each owed job, and what that job must show, from a run whose
head commit is the commit under validation; a named job that fails, or an
observation that is absent, MUST be a failure.

#### Scenario: Owed CI evidence beside jobs that fail on `dev`

- **WHEN** a complete section owes `tests.yml`'s `test · test-deployment-packaging`
  job passing, and the dispatched run passes that job and fails two others whose
  failing tests also fail, with the same exception types, in `dev`'s latest run of
  `tests.yml` at a commit the branch contains
- **THEN** validation judges the owed job passed, reports the two others as already
  failing on `dev`, naming that run and its commit, and neither is a failure

### Requirement: MCW-2lzw Every other failing job is compared with `dev`

Validation MUST compare each failure of every other failing job of the dispatched
run (a failing test's ID and exception type where reported, else the failing step
and its error) with the same job in the latest completed run of the workflow on
`dev` whose head commit the validated commit contains, naming that run and its
commit. A failure that run shows too MUST be reported as already failing on `dev`
and MUST NOT be a failure; any other MUST be diagnosed as any failure is.

#### Scenario: A job not owed fails only on the branch

- **WHEN** a job no section owes fails in the dispatched run and passes in `dev`'s
  latest run of the same workflow at a commit the branch contains
- **THEN** validation diagnoses it as any failure, and one caused by the commit or of
  unknown cause fails validation

#### Scenario: A new failure in a job that already fails on `dev`

- **WHEN** a job no section owes fails on `dev` with one test, and the dispatched
  run's same job fails with that test and another
- **THEN** validation reports the first as already failing on `dev` and diagnoses the
  other as any failure

#### Scenario: A test that fails on `dev` fails another way on the branch

- **WHEN** a job no section owes fails on `dev` with a test raising `TimeoutError`,
  and the dispatched run's same job fails that test with an `AssertionError`
- **THEN** validation does not report it as already failing on `dev`, and diagnoses
  it as any failure

### Requirement: MCW-3yqn A failure with no `dev` run to compare is of unknown cause

Where no completed run of the workflow on `dev` has a head commit the validated
commit contains, or a job's failures cannot be compared, the failure MUST be of
unknown cause.

#### Scenario: No `dev` run of the branch's code

- **WHEN** a job no section owes fails, and no completed run of the workflow on `dev`
  has a head commit the branch contains
- **THEN** the failure is of unknown cause, so validation fails and it is triaged

### Requirement: MCW-qeja Validation builds the images and runs the Helm render checks

Validation MUST build the service images and run the Helm render checks, with the
chart-to-loader check able to run; a skipped chart-to-loader check MUST fail
validation.

#### Scenario: The chart-to-loader check is skipped

- **WHEN** the Helm render checks run and the chart-to-loader check reports itself
  skipped
- **THEN** validation fails, naming the skipped check

### Requirement: MCW-8h0r The Helm end-to-end run covers a listed set of scenarios from no persistent state

Validation MUST include a Helm end-to-end run of the scenarios the charts serve,
named in an explicit list, starting from no persistent state an earlier deployment
left. Every pipeline scenario not on that list MUST be reported as not run against
Helm, never as passed.

#### Scenario: A pipeline scenario the charts do not serve

- **WHEN** the pipeline runs a scenario that is not on the Helm run's list
- **THEN** the validation report lists it as not run against Helm, and its evidence
  comes from the pipeline alone

#### Scenario: A deploy fails on volumes left by an earlier install

- **WHEN** the Helm part finds a release volume that survived the uninstall, or a
  deploy fails on persistent state another commit wrote
- **THEN** validation tells the owner the evidence and the remedy, reruns the part
  as a new attempt once the owner has acted or named the action, and the failure is
  not a triage finding

### Requirement: MCW-fnuh Each Helm validation deploys into its change's namespace under its change's tag

Validation's Helm part MUST deploy into a namespace of its change's own, derived
from the change's name, and MUST NOT install, upgrade, remove, or scale a release or
volume in any other namespace. The images it deploys MUST carry a tag fixed per
change, so that two changes' builds never write one tag; it MUST NOT tag them by
commit.

#### Scenario: Two changes are validated at once

- **WHEN** two changes' Helm parts run at the same time on one cluster
- **THEN** each builds its own images under its own tags, deploys into its own
  namespace, and runs its scenarios against its own release, and neither removes,
  replaces, or reaches the other's

### Requirement: MCW-a0hu A Helm deployment starts from removed volumes and recreated Secrets

Before deploying, the Helm part MUST remove every volume the change's previous
deployment wrote, including the volumes created for its tests out of band, and MUST
create the namespace's out-of-band Secrets. It SHOULD upgrade the release in place
from zero replicas, and MAY uninstall and install it when the upgrade is refused,
saying so.

#### Scenario: A change is validated again

- **WHEN** a change's earlier validation left its namespace scaled to zero with its
  volumes
- **THEN** validation deletes those volumes, recreates the Secrets, and upgrades the
  release, whose pods start new on the images just built against empty volumes

#### Scenario: An earlier run crashed with its workloads up

- **WHEN** validation finds the change's workloads running from a run that ended
  without scaling them down
- **THEN** it scales them to zero before deleting the volumes

### Requirement: MCW-notv The Helm scenarios run in the namespace, which is kept and scaled down

The Helm part's scenarios MUST run inside the namespace and MUST NOT depend on a
local port. After the scenarios it MUST keep every pod's log and the namespace's
events with the attempt's evidence, and MUST scale the namespace's workloads to
zero.

#### Scenario: A Helm attempt's scenarios end

- **WHEN** a Helm attempt's scenarios end, passed or failed
- **THEN** the attempt's evidence holds every pod's log and the namespace's events,
  and the namespace's workloads are at zero replicas

### Requirement: MCW-7bia A memory preflight estimates whether a deployment fits

A preflight MUST compare the memory a release is recorded to need, times the
releases that would be running, with what the node can allocate, and MUST treat a
deployment that would not fit as an environmental failure; it is an estimate and
reserves nothing. When no figure is recorded, or usage cannot be measured, it MUST
warn and go on.

#### Scenario: Usage cannot be measured

- **WHEN** the cluster has no metrics source
- **THEN** the preflight warns that no memory figure will be recorded, and the part
  goes on

#### Scenario: No memory figure is recorded yet

- **WHEN** a validation's preflight runs before any archive cleanup has recorded
  the memory a release needs
- **THEN** it warns that the check was skipped, and the part goes on

### Requirement: MCW-epkd A pod failing for memory is classified from the evidence

A pod that fails for memory after a passed preflight MUST be classified as any
validation failure is, from the namespace's events, the other namespaces' workloads
at the time, and the rendered requests and limits: as environmental only when that
evidence shows contention for the node's memory, and otherwise as caused by the
commit or of unknown cause.

#### Scenario: Two validations pass the preflight together

- **WHEN** two changes' preflights pass before either deploys, and one's pods then
  cannot be scheduled or are evicted for memory while the other's workloads are up
- **THEN** that validation's failure is diagnosed as environmental, with the remedy
  of scaling another change's namespace to zero or running again once it is down

#### Scenario: A commit's own pod is killed for memory

- **WHEN** a pod is killed at its own memory limit after a passed preflight, and the
  commit changed the rendered requests or limits or the evidence shows no
  contention
- **THEN** the failure is reported as caused by the commit or of unknown cause, so
  validation fails and the failure is triaged

### Requirement: MCW-7ts3 Archive cleanup removes the namespace and images and records the memory measured

Archive cleanup MUST remove the change's namespace and images and, when the change's
latest validation measured memory, MUST record it, with when it was measured; when
that validation measured none, it MUST keep the figure already recorded and say
that it recorded none. Where two branches' recorded figures conflict at a merge, the
one measured later MUST be kept.

#### Scenario: A change's archive is cleaned up

- **WHEN** archive cleanup runs for a change validated on Helm
- **THEN** the change's namespace and images are removed, and the memory its latest
  validation measured, if it measured any, is recorded for the preflight

#### Scenario: Archive cleanup after a validation that measured nothing

- **WHEN** archive cleanup runs and the change's latest validation recorded no
  memory
- **THEN** it leaves the recorded figure as it is, or absent, and says in its report
  and the pull-request draft that it recorded none

### Requirement: MCW-farr This repository's protected branches are `main` and `dev`

This repository's protected branches MUST be `main` and `dev`, and the guarded push
MUST refuse either.

#### Scenario: The guarded push runs on `dev`

- **WHEN** the guarded push runs with `dev` checked out
- **THEN** its check refuses, naming the branch, and nothing is pushed

### Requirement: MCW-q8vd The pre-push check refuses recognizable private content

This repository's pre-push check, which the guarded push runs, MUST reject
recognizable personal home paths, private assistant planning and session paths, and
identifiers in a configured local denylist, from ref names, added content,
filenames, and commit messages. It MUST inspect intermediate commits, not only the
final tree, and MUST omit matched values from its diagnostics. An unreadable
configured denylist or unavailable comparison refs MUST fail closed. It does not
replace review.

#### Scenario: Private content is removed in a later commit

- **WHEN** an outgoing commit adds recognizable private content and a later commit
  removes it
- **THEN** the guarded push refuses the history without printing the matched value

### Requirement: MCW-ca51 The merge brings in `dev` unless the owner names another branch

The branch a change lands on, which the merge before closeout brings in where the
owner names no other, MUST be `dev` in this repository.

#### Scenario: The merge runs with no branch named

- **WHEN** the merge before closeout runs for a change whose owner named no branch
- **THEN** it merges `dev` into the change's branch

### Requirement: MCW-y37w The step table names no Fable or Astra model

This repository forbids Fable and Astra models for its unattended steps: the step
table MUST NOT name one, and the wrapper MUST refuse to load a table that does,
naming the row.

#### Scenario: A row names a forbidden model

- **WHEN** the step table names a Fable model
- **THEN** the wrapper refuses to load the table, naming the row

### Requirement: MCW-uqlq A clone's bootstrap is `make init`

This repository's bootstrap of a change's clone MUST be `make init`, run in the
clone as it is made, whose success the workflow waits on before implementation or
validation starts there.

#### Scenario: A change's clone is made

- **WHEN** the orchestrating session creates a change's clone
- **THEN** `make init` runs in the clone in the background, and its status is
  recorded as running until it succeeds or fails
