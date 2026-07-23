# Physical Provisioning Architecture

The [normative contract](spec.md) defines executor dispatch, jobs, and release. This document explains how the compute service composes generic lifecycle machinery with domain adapters.

## Compute composition

The compute service owns transport, persistence, job execution infrastructure, lease lifecycle, and registration of concrete adapter bundles. Domain adapters own infrastructure-specific request validation, invocation, result interpretation, and credentials.

```text
compute service composition
    ├── generic jobs and lease lifecycle
    ├── site and resource-pool authorities
    ├── fulfillment scheduler/registry
    └── VM, bare-metal, or future adapter bundles
```

This replaces a VM-shaped provisioning core with an executor-neutral composition root. Generic services can dispatch by recorded executor or provider identity without importing a concrete domain implementation.

## Registration boundary

Adapters register executor actions and FulfillmentProviders explicitly. Duplicate executor/action registrations and duplicate exact `(provider, resource_kind)` registrations fail during startup because silent replacement would make persisted records execute under a different implementation. Provider and executor registration remain independent: fulfillment create/status/teardown and lease-release actions have different contracts and may evolve separately. VM and bare-metal adapters may both use Ansible while routing through `("ansible", "compute.gpu")` and `("ansible", "bare_metal")`; neither adapter is a fallback for the other kind.

## Durable jobs, transient workers

A persisted job gives accepted work a durable identity, status, request snapshot, result, and diagnostic history. The in-process queue is only the execution mechanism. It does not become the database, retry authority, or provider policy engine.

This distinction makes accepted work observable while avoiding false recovery promises. A process restart does not by itself prove that every queued or running action is safely resumed; recovery must be explicit where required.

## Selected-resource execution

Concrete providers operate on the Settlement Resource selected by fulfillment scheduling. The VM and bare-metal Ansible adapters each validate their own domain request and selected resource through a scoped provider route, then snapshot prepared inputs before dispatch. Administrative pool edits therefore affect later operations rather than rewriting the accepted execution.

Operational inventory is authoritative service state, not a checked-in Ansible inventory. Bootstrap inventory may import hosts, and an adapter may render transient execution inventory, but operator mutations and job-history references remain tied to persisted resources.

## Proof-driven release

Lease expiry or early termination dispatches teardown through the recorded executor identity. The site authority releases capacity only after teardown succeeds. Failure retains the reservation and records a retryable release state. An explicit force release is an operator override with distinct audit meaning, not fabricated proof of executor success.

Readiness checks use local service dependencies. Slower outbound provider or storefront diagnostics belong to operator surfaces so an external failure does not unnecessarily make a healthy API/worker process unready.

## Current limits

The compute service does not yet provide a durable generic fulfillment recovery aggregate, infer provider-to-executor linkage, or establish universal multi-storefront event routing. Optional notification adapters are delivery mechanisms, not ownership authorities.

## Related contracts

- [Fulfillment](../fulfillment/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Resource-pool management](../resource-pool-management/spec.md)
