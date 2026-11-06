# Market Change Workflow Specification

## Purpose

Define how this repository runs the change workflow (`change-workflow`): how it
provides each role the workflow asks of an adopting repository; the parts its
validation has — local, Helm, the end-to-end pipeline, and CI — and what each
builds and compares; the isolation of each change's Helm validation in a namespace
of its own, under its change's image tag, and the memory those namespaces share;
and its workflow values — its protected branches, the pre-push check its guarded
push runs, the branch a change lands on, the models it forbids, and a clone's
bootstrap.

Requirements are organized by `index.md`; their order here carries no meaning.

## Requirements

### Requirement: MCW-5tgp This repository provides the workflow's roles

This repository's configuration, `.agents/workflow.toml`, MUST declare the fields the
workflow defines, and this repository MUST state how it provides each role the
configuration does not hold: the make target, path, or document that fills it. Every
make target and repository path the workflow's skills and step table name MUST appear
in that statement or in the configuration.

#### Scenario: The local validation role

- **WHEN** a reader looks up how this repository validates a commit locally
- **THEN** the configuration's `local` validation part names `make validate-local`

#### Scenario: The protected branches role

- **WHEN** a reader looks up this repository's protected branches
- **THEN** the configuration names `main` and `dev`, which the guarded push refuses

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

### Requirement: MCW-uqlq A clone's bootstrap is `make init`

This repository's bootstrap of a change's clone MUST be `make init`, run in the
clone as it is made, whose success the workflow waits on before implementation or
validation starts there.

#### Scenario: A change's clone is made

- **WHEN** the orchestrating session creates a change's clone
- **THEN** `make init` runs in the clone in the background, and its status is
  recorded as running until it succeeds or fails

### Requirement: MCW-c4ek A change's closing checks enforce written rules

A change's closing checks MUST fail when a decision headed `D<n>` under its design's
`## Decisions` has no bullet starting `D<n>` in its proposal's knowledge to promote;
when a comment or docstring line its diff adds uses history wording on the check's
list; when a package version differs from its version at the merge-base with the
branch the change lands on by more than one SemVer step; when an import its diff adds
inside a function has no comment giving its reason; or when a capability with a
specification has no row in the capability index, or a row links no capability.

#### Scenario: A decision names no destination

- **WHEN** a design records `### D7` and the proposal's knowledge to promote has no
  bullet starting `D7`
- **THEN** the closing checks fail, naming D7

#### Scenario: A comment describes history

- **WHEN** a change's diff adds the comment "# previously read from the pool table"
- **THEN** the closing checks fail, naming the file and line

#### Scenario: A package is bumped twice

- **WHEN** a package at 0.4.0 on the merge-base is at 0.4.2 on the change's branch
- **THEN** the closing checks fail, naming the package and both versions

#### Scenario: A larger bump replaces a smaller one

- **WHEN** a package at 0.4.0 on the merge-base, bumped to 0.4.1 for a fix, is bumped
  to 0.5.0 for an incompatible edit
- **THEN** the version check passes

#### Scenario: A local import has no reason

- **WHEN** a change's diff adds an import inside a function with no comment beside or
  above it
- **THEN** the closing checks fail, naming the file and line

#### Scenario: A capability has no index row

- **WHEN** `openspec/specs/<capability>/spec.md` exists and the capability index has
  no row linking it
- **THEN** the closing checks fail, naming the capability

### Requirement: MCW-s8gk The public-content checks refuse private keys and provider credentials

The public-content checks MUST refuse a private key, or a credential in a format one of
the scanner's provider-specific rules recognizes, in added content, a merge's own
resolution included, through a maintained secret scanner at a pinned release, whether
a key is wrapped at any length or written as one escaped string, reporting its
location without its content. They MUST pass a key block whose short body holds no key
material, however many such blocks share a file, and MUST pass the repository's
development fixtures: published development keys, public contract addresses, and code
that names a key.

#### Scenario: A key fixture carries no key material

- **WHEN** a test fixture holds a private-key block whose body is the word `fixture`
- **THEN** the public-content checks pass it

#### Scenario: Two key fixtures share a file

- **WHEN** an added file holds two private-key blocks, each with a short fixture body,
  one after the other
- **THEN** the public-content checks pass it, reading neither block as running into
  the other

#### Scenario: A key is added in a merge resolution

- **WHEN** an outgoing merge commit adds a private-key block with key material that
  neither of its parents holds
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the key

#### Scenario: A real key is staged

- **WHEN** a staged addition holds a private-key block with base64 key lines, wrapped
  at any length
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the key

#### Scenario: A key is embedded as one escaped string

- **WHEN** an added source line holds a private-key block as one string, its line
  breaks written as `\n` escapes, with key material for a body
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the key

#### Scenario: A provider token is staged

- **WHEN** a staged addition holds a token in a provider's published format, such as a
  GitHub personal access token
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the token

#### Scenario: A development fixture is added

- **WHEN** an added line holds one of Anvil's published development keys, a contract
  address, or the annotation `private_key: Ed25519PrivateKey`
- **THEN** the public-content checks pass it

### Requirement: MCW-u2dt An audit reports every scanner rule and gates nothing

An audit run on demand MUST report, by rule, file and line without content, what every
rule of the pinned scanner but its default private-key rule finds in the tracked tree,
and MUST gate nothing.

#### Scenario: The audit reports what the gate passes

- **WHEN** the tracked tree holds a random 40-character password with no provider
  format, and the owner runs the audit
- **THEN** the audit reports its rule, file and line without echoing it, exits
  successfully, and the public-content checks still pass the line

### Requirement: MCW-l5rv Every lock carries the lock revision the minimum uv writes

The packaging checks MUST fail when a committed lock carries a lock revision other than
the one the repository's minimum uv writes, and every command the repository provides
to relock a project or refresh its environment MUST first refuse a uv older than that
minimum; a plain `uv run` that relocks a changed project is not guarded, and the
revision check fails on what it writes before it lands.

#### Scenario: A lock is written by another uv release

- **WHEN** a committed `uv.lock` carries a lock revision other than the one the
  repository's minimum uv writes
- **THEN** the packaging checks fail, naming the lock and both revisions

#### Scenario: A lock is rewritten with an older uv

- **WHEN** a project is relocked, or a package's environment is refreshed, which may
  rewrite its lock, with a uv older than the repository's minimum
- **THEN** the command refuses before running uv, naming both versions

### Requirement: MCW-r4tx This repository's hooks and validation parts

This repository's configuration MUST relock after a functional change; run its own
closing checks, `make check-repository`, before every commit, while `make
check-change` runs the workflow's whole `pre-commit` for the owner; before a
functional commit, clear the wheelhouse, so that the packaging check builds every
wheel from the commit and no suite tests a wheel another commit built, then check
packaging and run every suite; check packaging and the
change's architecture exceptions before the archive; and declare validation's
pipeline, owed CI, local, and Helm parts, the Helm part after the local one, with a
cleanup that records the capacity measured and removes the change's namespace and
images.

#### Scenario: Validation runs this repository's parts

- **WHEN** validation runs in this repository with no part waived and a complete
  section owing `tests.yml`
- **THEN** it starts the pipeline and the owed CI run, then runs the local part,
  then the Helm part

### Requirement: MCW-k3vy The pre-push checks are one make target

The pre-push checks MUST be one make target, `make pre-push`, which runs both
public-content checks under Git's hook contract, and which both the configuration's
`pre-push` and the Git hook `scripts/hooks/pre-push` run.

#### Scenario: The Git hook runs the checks

- **WHEN** an owner's `git push` runs the repository's pre-push hook
- **THEN** the hook runs `make pre-push` with the remote, which runs both
  public-content checks the guarded push runs

## Evidence

- This repository's hooks, validation parts, protected branches, inert paths,
  models, and documents to load: `.agents/workflow.toml`.
- How this repository provides each role the configuration does not hold, and meets
  each of the engine's own assumptions: `README.md`, held complete, with the
  configuration's commands, for the targets and paths the skills, step table, and
  make fragment name by `scripts/tests/test_change_workflow_assumptions.py`;
  rationale and current limits: `README.md`; the requirements' organization:
  `index.md`.
- Validation: `make validate-local`, `make validate-helm`, and `make validate-ci`
  (`scripts/validate_slice.py`); run selection for the validated commit:
  `scripts/fetch-e2e-logs.py`; the workflows validation may dispatch and the
  comparison of a CI run's failures with `dev`'s: `make run-ci`
  (`scripts/ci_evidence.py`).
- A change's validation namespace and image tags: `scripts/change_namespace.py`,
  with `CHANGE=` on every `helm/Makefile` target and `IMAGE_SUFFIX` on the build
  targets; manual access: `make -C helm forward` and `make -C helm resume`;
  teardown: `make -C helm teardown`; the memory one release needs:
  `helm/validation-capacity.toml`, written by `make record-capacity`; two clones'
  Helm parts at once: `make validate-parallel` (`scripts/validate_parallel.py`).
- The pre-push checks: `make pre-push`, running `scripts/check_public_content.py
  --pre-push` and `scripts/check_secrets.py --pre-push`, which the configuration's
  `pre-push` and `scripts/hooks/pre-push` both run.
- The closing checks: `make check-repository` (`scripts/check_change.py`), the
  configuration's `pre-commit`; `make check-change`, running `scripts/change-workflow
  run pre-commit`.
- The clone's bootstrap: `make init`, the configuration's `post-clone`.
