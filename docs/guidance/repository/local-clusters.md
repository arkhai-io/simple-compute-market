---
tags: [repository, deployment, helm]
---

# Local clusters

How work here deploys to a local Kubernetes cluster, by whoever deploys — a person or
an agent. The local releases and the targets that bring them up are
[`DEPLOYMENT_AND_CONFIG.md`, "Release topology"](../../development/DEPLOYMENT_AND_CONFIG.md#release-topology).

## A local cluster is deployed with `deploy-local`

A local development cluster is deployed with `make -C helm deploy-local`, never
`make -C helm deploy` or the root `make deploy`, whether a person or an agent is
deploying, because a local cluster is redeployed with whatever code is checked out, and a
retained volume keeps the state that code wrote — a database another branch
migrated — for the next deployment to start from. Pre-review validation run in
`default` refuses to deploy over a release volume that carries the
`helm.sh/resource-policy: keep` annotation and stops to ask, so a local deploy
without the `helm/local-values.yaml` overlay costs the next validation a
decision; a change's validation runs in its own namespace instead and deletes its
volumes itself
([`market-change-workflow`'s "The change's namespace"](../../../openspec/specs/market-change-workflow/README.md#the-changes-namespace)).
`make -C helm deploy` is for a
deployment whose state must survive reinstalling.

## A local release configures a service through the values a deployment uses

**A local release configures a service through the values a deployment uses**
([`deployment.md`](../engineering/deployment.md#a-local-release-configures-a-service-through-the-values-a-deployment-uses)).
Payments are the example: both
storefronts settle in `arkhai.payments.v1` against the payments lane double
through `[Settlement.arkhai_payments]` in their `config`, the `caBundle` option on
the `payments-ca-bundle` ConfigMap, and the payments `api_key` in their runtime
Secret's overlay, never `development_auth`.

## A scenario needing release 2

An end-to-end scenario that needs release 2 states `make helm-topology-up` on its
Makefile target and in its suite module's docstring; the Helm validation scenarios
need release 1 alone.
