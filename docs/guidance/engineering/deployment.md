---
tags: [engineering, deployment]
---

# Deployment

How a service starts in a deployment — what holds it back and what does not — and
how a local release rehearses a deployment's shape. The Kubernetes forms are
[Kubernetes](kubernetes.md); how a service's migrations run is
[Migrations](migrations.md).

## A deployment does not wait on a service's dependencies

No deployment holds a service back with a step before it starts — an init container,
a wait script — that waits for or validates an external dependency, such as a chain,
an upstream API, a site, or another service, and no service waits for one in process
either. The service starts with its dependencies unreachable, reports each one it
cannot reach in its system status as degraded, and its own loops retry it; a
misaddressed dependency is indistinguishable at start from one that is down, so it is
reported the same way rather than refused. The one step a deployment runs for a
service before it starts is that service's own migration, which acts on the
service's own state ([Migrations](migrations.md)). The Kubernetes form, a startup
probe on a process check, is in [Kubernetes](kubernetes.md).

## A service refuses to start on its own incoherent state, never on a dependency

A service refuses to start when its own configuration contradicts itself or its
stored state cannot be served as it stands, since waiting repairs neither; a
dependency it cannot reach is reported, not refused
([A deployment does not wait on a service's dependencies](#a-deployment-does-not-wait-on-a-services-dependencies)).

## A local release configures a service through the values a deployment uses

The local release is where a deployment's shape is rehearsed, so it configures each
service through the same values, files, and secrets a deployment supplies, never
through a development-only mode. A service paying through an external provider, for
example, reaches a local double of that provider through the same settings section,
CA bundle mount, and secret overlay a deployment uses, never through a
development-only authentication switch.
