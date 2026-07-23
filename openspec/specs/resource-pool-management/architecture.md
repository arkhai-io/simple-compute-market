# Resource-Pool Management Architecture

The [normative contract](spec.md) defines pool administration. This document explains why pools own provisioning routing metadata but not scheduling or execution policy.

## Ownership boundary

A Resource Pool groups candidate Physical Resources and records the provider kind and provider-specific configuration needed after selection. It owns stable pool identity, enabled state, tags, configuration, and membership.

It does not choose a Settlement Resource and does not define the FulfillmentProvider contract. Keeping those responsibilities separate prevents administrative configuration from becoming an implicit scheduling algorithm and avoids a reverse dependency from the pool authority into fulfillment.

## Provider configuration

The generic pool package stores opaque provider configuration only after a provider-owned handler validates and normalizes it. This allows an adapter to enforce its own schema without teaching the pool authority about Ansible, Kubernetes, bare metal, or a future executor.

Resolved configuration is routing input. A fulfillment operation snapshots the accepted provider inputs at dispatch so later administrative edits do not silently rewrite an in-flight operation.

## Membership and draining

Membership expresses which resources are candidates under a pool's routing context. Disabling a pool blocks new assignment but preserves membership and records needed by existing workloads. This is draining, not deletion.

Hard deletion is intentionally absent because an existing assignment, job, or lease must remain explainable even after operators stop selling through that pool.

## Administrative reconciliation

Declarative YAML import is an operator reconciliation surface rather than a second persistence model. Strict validation rejects unknown structure. Dry-run computes the exact change without mutation. Apply is atomic, and canonical export makes equivalent state stable for review and automation. Omitted pools are disabled rather than erased.

## Current limits

Pool administration does not establish pool priority, weighted scheduling, or fairness policy. Provider-specific operational health and execution success belong to provisioning adapters and lifecycle services, not pool metadata.

## Related contracts

- [Fulfillment](../fulfillment/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Site capacity](../site-capacity/spec.md)
