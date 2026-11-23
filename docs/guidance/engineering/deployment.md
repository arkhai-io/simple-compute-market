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
either.

- A service serves degraded only where it has meaningful work to do without the
  dependency. A service that has such work starts with the dependency unreachable,
  reports it degraded, and retries. A service that can do no meaningful work without
  it exits when it is unreachable, and the orchestrator's restarts are its retries.
- Either way, configuration that can never work, an absent or malformed setting, is
  refused at startup, naming it. A well-formed address that reaches nothing is
  unreachable, never refused as wrong.
- Native sidecars that are part of one service's own unit, such as its own state
  store or its database connection, may hold the service back until their startup
  probes pass. Each must refuse configuration it cannot use and exit on what it
  cannot reach, so the wait hides no failure that cannot heal. A dependency outside
  the unit is never waited on.

The one step a deployment runs for a
service before it starts is that service's own migration, which acts on the
service's own state ([Migrations](migrations.md)). The Kubernetes form, a startup
probe on a process check, is in [Kubernetes](kubernetes.md).

## A service refuses to start on its own incoherent state, never on a dependency

A service refuses to start when its own configuration contradicts itself or its
stored state cannot be served as it stands, since waiting repairs neither; a
dependency it cannot reach is reported, or exited on where the service has no
meaningful work without it, never refused as wrong configuration
([A deployment does not wait on a service's dependencies](#a-deployment-does-not-wait-on-a-services-dependencies)).

## A local release configures a service through the values a deployment uses

The local release is where a deployment's shape is rehearsed, so it configures each
service through the same values, files, and secrets a deployment supplies, never
through a development-only mode. A service paying through an external provider, for
example, reaches a local double of that provider through the same settings section,
CA bundle mount, and secret overlay a deployment uses, never through a
development-only authentication switch.
