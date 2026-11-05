# How this repository runs the change workflow — index

Prefix: `MCW`

This is the specification's organization: its parts and groups, each requirement by
id with a summary line. [`spec.md`](spec.md) holds the requirements flat, in no
meaningful order; [`README.md`](README.md) is the readable description.

## 1. The workflow's roles

- [MCW-5tgp](spec.md#requirement-mcw-5tgp-this-repository-provides-the-workflows-roles) — the repository states how it fills each workflow role, covering every target, path, and engine assumption named.

## 2. Validation

### Building and the pipeline

- [MCW-v3tf](spec.md#requirement-mcw-v3tf-validation-builds-the-packages-it-tests-from-the-commit) — each building part builds its internal packages from the validated commit, never from shared wheelhouse leftovers.
- [MCW-zk52](spec.md#requirement-mcw-zk52-end-to-end-evidence-comes-from-the-commits-own-pipeline-run) — end-to-end evidence comes from a pipeline run whose head commit is the validated commit.

### CI evidence

- [MCW-gvqb](spec.md#requirement-mcw-gvqb-owed-ci-evidence-names-its-workflow-its-job-and-what-the-job-must-show) — owed CI evidence names its workflow, its job, and what that job must show.
- [MCW-3i99](spec.md#requirement-mcw-3i99-validation-dispatches-the-owed-ci-workflows-from-a-fixed-list) — validation dispatches owed workflows only from a fixed, non-publishing list the owner extends by tracked change.
- [MCW-7hr1](spec.md#requirement-mcw-7hr1-an-owed-job-is-judged-from-the-commits-own-run) — an owed job is judged from the commit's own run; a failing job or absent observation fails.
- [MCW-2lzw](spec.md#requirement-mcw-2lzw-every-other-failing-job-is-compared-with-dev) — other failing jobs are compared with the latest contained `dev` run; failures `dev` shares are not failures.
- [MCW-3yqn](spec.md#requirement-mcw-3yqn-a-failure-with-no-dev-run-to-compare-is-of-unknown-cause) — a failure with no comparable `dev` run, or not comparable, is of unknown cause.

### Helm

- [MCW-qeja](spec.md#requirement-mcw-qeja-validation-builds-the-images-and-runs-the-helm-render-checks) — validation builds the service images and runs the Helm render checks; a skipped chart-to-loader check fails.
- [MCW-8h0r](spec.md#requirement-mcw-8h0r-the-helm-end-to-end-run-covers-a-listed-set-of-scenarios-from-no-persistent-state) — the Helm run covers a listed set of scenarios from no persistent state; unlisted ones are reported not run.

## 3. The Helm validation namespace

- [MCW-fnuh](spec.md#requirement-mcw-fnuh-each-helm-validation-deploys-into-its-changes-namespace-under-its-changes-tag) — the Helm part deploys only into the change's own namespace, with images under a per-change tag.
- [MCW-a0hu](spec.md#requirement-mcw-a0hu-a-helm-deployment-starts-from-removed-volumes-and-recreated-secrets) — before deploying, the previous deployment's volumes are removed and out-of-band Secrets created; upgrade preferred.
- [MCW-notv](spec.md#requirement-mcw-notv-the-helm-scenarios-run-in-the-namespace-which-is-kept-and-scaled-down) — scenarios run inside the namespace; logs and events are kept and workloads then scaled to zero.
- [MCW-7bia](spec.md#requirement-mcw-7bia-a-memory-preflight-estimates-whether-a-deployment-fits) — a memory preflight estimates fit against node capacity; not fitting is environmental, no figure only warns.
- [MCW-epkd](spec.md#requirement-mcw-epkd-a-pod-failing-for-memory-is-classified-from-the-evidence) — a memory failure after the preflight is environmental only when evidence shows node contention.
- [MCW-7ts3](spec.md#requirement-mcw-7ts3-archive-cleanup-removes-the-namespace-and-images-and-records-the-memory-measured) — archive cleanup removes the namespace and images and records measured memory, keeping the later figure at merges.

## 4. This repository's workflow values

- [MCW-farr](spec.md#requirement-mcw-farr-this-repositorys-protected-branches-are-main-and-dev) — the protected branches are `main` and `dev`, which the guarded push refuses.
- [MCW-q8vd](spec.md#requirement-mcw-q8vd-the-pre-push-check-refuses-recognizable-private-content) — the pre-push check rejects private paths and denylisted identifiers across every commit, failing closed.
- [MCW-ca51](spec.md#requirement-mcw-ca51-the-merge-brings-in-dev-unless-the-owner-names-another-branch) — the branch a change lands on, and the merge brings in, is `dev` unless the owner names another.
- [MCW-y37w](spec.md#requirement-mcw-y37w-the-step-table-names-no-fable-or-astra-model) — Fable and Astra models are forbidden; the step table names none and the wrapper refuses one.
- [MCW-uqlq](spec.md#requirement-mcw-uqlq-a-clones-bootstrap-is-make-init) — a clone's bootstrap is `make init`, run as the clone is made; implementation and validation wait on it.

## Retired ids

None.
