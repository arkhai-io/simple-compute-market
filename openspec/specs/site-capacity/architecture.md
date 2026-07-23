# Site Capacity Architecture

The [normative contract](spec.md) defines reservation and projection behavior. This document explains why capacity admission is a separate authority from storefront publication and fulfillment execution.

## Admission authority

A site is the serialization point for competing reservations in one failure domain. Storefronts may cache and aggregate availability, but only the site can atomically decide whether capacity remains admissible.

```text
storefront projection (advisory)
            ↓ request
site reservation ledger (authoritative)
            ↓ committed reservation
fulfillment scheduling
```

Putting the ledger outside storefronts allows several sellers or processes to share supply without treating independently refreshed caches as locks. It also lets a reservation outlive the storefront process that initiated it.

## Private accounting

Multidimensional balances are represented by private capacity buckets and current reservation debits. The public reservation identifies its lifecycle and reserved dimensions; it does not expose a backing bucket or physical-resource identity. Scheduling may atomically move the debit when selection binds the reservation to another eligible bucket.

Admission and scheduling use the same fit semantics. Every requested dimension must be present and sufficient; a missing dimension means zero availability rather than an unconstrained match. This avoids accepting a request under one predicate and selecting a resource under another.

## Reservation lifecycle

A hold protects negotiation-time intent for a bounded period. Commit makes capacity durable for execution. Release returns capacity only through the owning lifecycle. Expiry and early termination may initiate release, but physical capacity remains held until executor or provider teardown succeeds or an operator explicitly force-releases it.

## Projection boundaries

The site exposes two independent storefront views:

- per-resource inventory for deliberately individual-resource offerings;
- grouped currently available shapes for fungible capacity publication.

Each view has its own revision and canonical digest. Grouped rows use deterministic criteria and counts, omit physical-resource identifiers, and are never allocation targets. These properties let storefronts replace one cached projection without conflating publication convenience with admission truth.

## Event privacy and convergence

Capacity events are anonymous availability changes. Broadcasting deal context would leak one storefront's customer activity to another seller sharing the site. Deal-scoped outcomes therefore use an owner-specific channel.

Revisions make missed events detectable. A consumer that sees a gap refreshes a complete snapshot rather than attempting to infer unknown intermediate deltas. Reconciliation reacts to every capacity change, not only changes caused by the local storefront.

## Routing identity

`site_id` is selected and trusted at the storefront aggregation boundary, where it is bound to a configured provisioning connection. Provisioning-local rows are already scoped by their database authority and do not encode routing endpoints or credentials into reservation identifiers.

## Current limits

The current ledger is not a distributed consensus system for active-active replicas. Generic deal-event ownership across arbitrary storefront topologies and universal aggregation across every physical resource type are not established by the capacity contract.

## Related contracts

- [Storefront publication](../storefront-publication/spec.md)
- [Fulfillment](../fulfillment/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
