---
tags: [engineering, kubernetes]
---

# Kubernetes

The Kubernetes form of [Configuration](configuration.md) and
[Deployment](deployment.md): how configuration reaches a pod, what a pod's
environment holds, how probes and storage are set, and how a test pod is labelled.
A chart's forms are [Helm](helm.md).

## Configuration travels through mounted files

All application configuration travels through mounted files, never individual pod
`env` entries; this holds equally for the application's Deployment and for the test
pods run beside it.

- Non-secret configuration renders into a ConfigMap, mounted at the configuration
  directory as a profile file. Adding a non-secret key changes only the values the
  ConfigMap renders from, never the Deployment template.
- Secret material that cannot go in a ConfigMap — key material, credentials —
  renders into a Secret whose data holds its own profile file, mounted at the same
  configuration directory. The loader sees no difference between a file mounted from
  a ConfigMap and one mounted from a Secret: the Secret's profile name is added to
  the active profiles beside the non-secret ones.
- A pod sets only the resolver variables — the list of profiles to layer and the
  directory the mounted files live in — as environment variables.

## Service links are off where a loader reads a prefixed override layer

Kubernetes injects variables for every Service in the namespace into each pod unless
the pod sets `enableServiceLinks: false`. A Service whose name begins with a
configuration loader's environment prefix lands its variables in that loader's
override layer: a Service named `orders-db` gives every pod `ORDERS_DB_SERVICE_HOST`,
which a loader reading `ORDERS_` overrides takes as a setting. A pod whose loader
reads a prefixed override layer sets `enableServiceLinks: false`.

## A startup probe on a process check

A container is given a `startupProbe` on a process check that calls no dependency,
so a slow start holds the liveness and readiness probes off rather than being judged
by them.

## A single-writer store deploys with `Recreate`

A service whose store tolerates one writer, such as SQLite, deploys with the
`Recreate` strategy over a `ReadWriteOnce` volume: the overlapping window of old and
new pods a `RollingUpdate` would produce against the shared volume is one the
single-writer model does not tolerate. The same strategy keeps two versions of a
service from sharing its database ([Migrations](migrations.md)).

## Test pods carry no workload selector label

A test pod run beside a release carries none of the labels a workload's selector
requires, such as the `app.kubernetes.io/name` every Deployment selector matches. So
a log query over a Deployment's selector finds only the service's pods, and no
Service routes traffic to a test pod. Adding a distinguishing label to the Deployment
selectors instead is not available: a selector is immutable, and changing one forces
each release to recreate its Deployments, so the test pod is the one that differs.
