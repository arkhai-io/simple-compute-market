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

What backing means lives in one delegate, `CapacityBacking` in
`kit/resource-pools-contracts`, beside the label it interprets. The declared label
selects it — `capacity_backing(label)` returns `BACKED` or `UNBACKED` and refuses a
label with no delegate — and the label stays what declarations, bindings, and the
projection carry, and what a published listing carries where its market's registry
schema publishes backing. Whether a market publishes backing at all is that schema's
decision, not the delegate's: the compute schema does, so a buyer can filter on it, and
the API-credit schema does not, since every credit listing is backed. Every decision that differs between backed
and unbacked supply is one of the delegate's operations: the declaration rules above,
admitting a capacity effect, placing a hold, judging supply against its declaration
and then, where availability bounds it, against availability, which labels
availability reconciliation may touch, and which settlement clauses an unbacked
listing keeps. Consumers ask it to act and never learn the category, so none
branches on the label, and a further category is a change to the delegate rather
than to its callers. A delegate exposing flags for callers to test would only move
those branches; one that performed effects would need clients and bindings its
contracts package may not import, so each operation takes the caller's work as an
argument and decides whether and how it runs.

The delegate is a kit rather than core or the compute family because backing applies
to every market whose listings are admitted against capacity an authority holds — VM
and bare metal against physical capacity, API credits against quota — and to no
market without such an authority. It sits beside the label because both sides of the
provisioning boundary consult it: the site's declaration rules, and the storefronts'
bindings, reconciliation, negotiation, and settlement. Two questions are answered by
the registry without the caller naming a category: `legacy_producer_backing()`, what a
pool from a producer predating the declarations resolves to, and `admitted_backing()`,
the backing of a reservation a site admitted with no listing behind it.

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
