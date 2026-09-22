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

## Advertisement, delivery, and backing

A pool makes three separate declarations about offering modes and admission.

`deliverable_modes` is an execution claim: the modes the pool's provider
configuration can deliver. Every execution layer rechecks it, and an initial set is
derived only from configuration that proves delivery. `advertisable_modes` is a
publication claim: the modes the pool's listings may name. They are separate
because a seller who trades by private arrangement can prove no delivery and must
still be able to list. Reading advertisement out of the deliverable set would give
that seller nothing, while treating the deliverable set as advisory for some
listings would let a pool proving no VM delivery advertise VMs.

`capacity_backing` says whether an admission authority stands behind the pool. A
backed pool may advertise only what it delivers, otherwise a buyer could reach
admission for a mode its provider will refuse. An unbacked pool must deliver
nothing. No layer reads backing at admission; the empty deliverable set is what
keeps an unbacked pool out of reservation, scheduling, and dispatch, through
rechecks those layers already perform. That keeps the new declaration from spreading
backing checks across the site and fulfillment authorities.

Backing is fixed at creation because every listing derived from a pool inherits
it, and changing it in place would reinterpret listings already published. Moving
supply between backed and unbacked is a second pool with its resources migrated
across.

Both declarations are required on every write rather than defaulted. A default
backing would assert whether anything stands behind a listing, and a default
advertisable set would widen or silently narrow what a pool may sell. Requiring
them also makes every pool carry them, which is what lets a consumer of the
resource-pool projection tell a producer predating the declarations (no pool
carries them) from a defective one (some pool lacks them). For the same reason a
consumer reads them only through the shared resolver, and advertisement membership
exists only on a resolved declaration: a raw read would turn an absent declaration
into an empty one and erase that distinction.

## Current limits

Pool administration does not establish pool priority, weighted scheduling, or fairness policy. Provider-specific operational health and execution success belong to provisioning adapters and lifecycle services, not pool metadata.

## Related contracts

- [Fulfillment](../fulfillment/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Site capacity](../site-capacity/spec.md)
