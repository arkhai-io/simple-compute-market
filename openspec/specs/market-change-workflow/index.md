# How this repository runs the change workflow — index

Prefix: `MCW`

This is the specification's organization: its parts and groups, each requirement by
id with a summary line. [`spec.md`](spec.md) holds the requirements flat, in no
meaningful order; [`README.md`](README.md) is the readable description.

## 1. The workflow's roles

- [MCW-5tgp](spec.md#requirement-mcw-5tgp-this-repository-provides-the-workflows-roles) — `.agents/workflow.toml` declares the workflow's fields, and the repository states how it fills each role outside them; every named target and path appears in one or the other.

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
- [MCW-k3vy](spec.md#requirement-mcw-k3vy-the-pre-push-checks-are-one-make-target) — the pre-push checks are one target, `make pre-push`, which the configuration's `pre-push` and the Git hook both run.
- [MCW-r4tx](spec.md#requirement-mcw-r4tx-this-repositorys-hooks-and-validation-parts) — the configuration relocks, runs `make check-repository` before every commit, clears the wheelhouse, packages, and tests before a functional one, and declares the pipeline, owed CI, local, and Helm parts.
- [MCW-uqlq](spec.md#requirement-mcw-uqlq-a-clones-bootstrap-is-make-init) — a clone's bootstrap is `make init`, run as the clone is made; implementation and validation wait on it.

## 5. This repository's checks

- [MCW-c4ek](spec.md#requirement-mcw-c4ek-a-changes-closing-checks-enforce-written-rules) — the closing checks fail on a decision with no destination, history wording, a double version bump, an unexplained local import, or a capability index gap.
- [MCW-s8gk](spec.md#requirement-mcw-s8gk-the-public-content-checks-refuse-private-keys-and-provider-credentials) — the public-content checks refuse private keys and provider-format credentials through a pinned scanner, passing development fixtures.
- [MCW-u2dt](spec.md#requirement-mcw-u2dt-an-audit-reports-every-scanner-rule-and-gates-nothing) — an on-demand audit reports what every scanner rule but the default key rule finds in the tracked tree, gating nothing.
- [MCW-l5rv](spec.md#requirement-mcw-l5rv-every-lock-carries-the-lock-revision-the-minimum-uv-writes) — every committed lock carries the minimum uv's lock revision, and the repository's relock and refresh commands refuse an older uv.

## Retired ids

- MCW-ca51 — the merge brought in `dev` unless the owner named another branch; the branch a change lands on is now recorded with its clone or given as an argument (`change-workflow`'s CW-s3ju and CW-hdxi).
- MCW-y37w — the step table named no Fable or Astra model; a repository now lists the models it prefers per step and keeps no forbidden list (`change-workflow`'s CW-ebmo and CW-zq4h).
