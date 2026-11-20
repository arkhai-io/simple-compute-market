---
tags: [repository, helm, kubernetes, deployment]
---

# Helm charts

What every chart here renders for the service it deploys, as instances of
[`kubernetes.md`](../engineering/kubernetes.md), [`helm.md`](../engineering/helm.md),
and [`deployment.md`](../engineering/deployment.md). Where the charts differ, and how
the storefront charts render an agent, is
[`DEPLOYMENT_AND_CONFIG.md`, "Kubernetes: ConfigMap and Secret mounting"](../../development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting).
What their render tests assert is [`chart-render-tests.md`](chart-render-tests.md).

## Configuration travels through mounted files

This repository's charts deliver configuration through mounted files
([`kubernetes.md`, "Configuration travels through mounted files"](../engineering/kubernetes.md#configuration-travels-through-mounted-files)),
the application Deployment and the Helm test pods alike: a ConfigMap
rendered from the chart's `values.yaml` mounts at `CONFIG_DIRECTORY` as a
`config-<profile>.yml` file, a Secret holding its own `config-<profile>.yml`
key mounts beside it, and a pod sets only `ACTIVE_PROFILES` and
`CONFIG_DIRECTORY`.

## A deployment does not wait on a service's dependencies

**A deployment does not wait on a service's dependencies**
([`deployment.md`](../engineering/deployment.md#a-deployment-does-not-wait-on-a-services-dependencies)).
The one init container a chart runs for a service is that service's own
migration — the provisioning service's, each storefront agent's, the bare-metal
storefront's, and each registry instance's (see
[`migrations-at-startup.md`](migrations-at-startup.md)). Both
storefront charts give their container a `startupProbe` on `/health`, a process
check that calls no dependency
([`kubernetes.md`](../engineering/kubernetes.md#a-startup-probe-on-a-process-check)).
Each storefront
chart's render tests assert that no `wait-for-` container renders, that exactly
one init container does — the storefront's migration command from the
application's image over its data volume — and that the `startupProbe` does; the
provisioning and registry charts' render tests assert their migration init
container the same way.

## A check of a setting the chart cannot see

A chart renders a check of a setting it cannot see only where a value names the
check's target, and that value is the release's statement that the setting exists.
The VM chart's `<agent>-mediation-check` pod is rendered this way, where the agent's
`tests.mediationOrigin` names a dispute authority, since the agent's
`[[DisputeCredential]]` lives in the runtime Secret's overlay
([`DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through configuration"](../../development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration)).

## An integer above 2^53 is a string

Write an integer above 2^53 in a values file as a string
([`helm.md`](../engineering/helm.md#an-integer-above-253-is-a-string)).

## Helm test pods carry no workload selector label

**Helm test pods carry no workload selector label**
([`kubernetes.md`](../engineering/kubernetes.md#test-pods-carry-no-workload-selector-label)).
Each chart labels its Helm
test pod through its own `<chart>.testLabels` helper: chart, version, managed-by,
instance, and `app.kubernetes.io/component: test`, but never
`app.kubernetes.io/name`, which every Deployment selector requires, so
`kubectl logs -l <selector>` or `kubectl logs deploy/<name>` finds only the
service's pods.
`helm/tests/test_release_topology.py` renders both topology releases and asserts
that no Pod annotated `helm.sh/hook: test` carries all of any Deployment's
`matchLabels` or any Service's selector, and that each release renders its expected
test pods.
