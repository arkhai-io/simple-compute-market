# Fulfillment Architecture

The [normative contract](spec.md) defines scheduling and provider-neutral execution. This document explains the capability's position above site and resource-pool authorities and the boundary between placement and execution.

## Capability position

Fulfillment depends downward on authoritative capacity and pool metadata:

```text
market_fulfillment
    ├── market_site
    └── market_resource_pools
```

The lower authorities must not import fulfillment, including through type-only imports. Site capacity remains usable without a provisioning scheduler, and pool administration remains usable without a provider execution contract.

Within fulfillment, carrier modules remain independent from operational schedulers. This keeps identifiers, requests, resources, envelopes, and provider protocols usable by adapters without importing service composition.

## Scheduling boundary

Scheduling starts from an admitted Capacity Reservation. It enumerates enabled pooled candidates, applies the same multidimensional fit semantics used by admission, and selects one Settlement Resource.

An explicit-resource request is an additional constraint, not an authorization bypass. The named resource must still exist, belong to an eligible enabled pool, and satisfy every requested dimension. Deterministic candidate ordering and policy state make the current two-level round-robin policy reproducible.

Selection creates a binding. Retrying an equivalent request returns the existing assignment where the process-local lifecycle can prove equivalence; a conflicting request is rejected rather than silently moving the reservation.

## Provider boundary

A FulfillmentProvider receives the selected resource and resolved execution inputs. It may validate that selection but may not substitute another placement. Create, status, and teardown are provider actions over the scheduler's decision.

Provider registration and executor registration are separate namespaces. A provider contract does not imply a lease-release executor, and an executor does not imply support for provider-neutral fulfillment.

## Identities and envelopes

Opaque identifiers keep routing and commercial meaning out of shared carriers. `capacity_reservation_id` is the scheduling and begin-fulfillment idempotency boundary; `settlement_resource_id` identifies selected supply; fulfillment, operation, result, and provisioned-resource identifiers describe later lifecycle records.

Provider-specific payloads cross persistence or package boundaries in versioned envelopes. A non-empty kind and positive schema version select an explicit validator. Unknown versions fail rather than inheriting today's provider assumptions.

## Current persistence limit

Scheduler assignments, policy cursors, and generic fulfillment registry entries are process-local. The architecture does not claim restart-safe or distributed assignment idempotency, cross-replica fairness, or a durable generic Settlement Record aggregate. Those guarantees require explicit persistence and concurrency design.

The implemented baseline is deterministic two-level round-robin with multidimensional eligibility. More advanced fairness policy is not implied by the request or carrier abstractions.

## Related contracts

- [Site capacity](../site-capacity/spec.md)
- [Resource-pool management](../resource-pool-management/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)


## Fulfillment acceptance and dispatch acknowledgement

Fulfillment acceptance freezes provider input before side effects. One transaction serializes acceptance, loads the selected resource and provider configuration, prepares the provider-specific envelope, and persists it with `dispatch_pending`. Dispatch happens after commit. A second short transaction records normalized provider metadata and advances the aggregate to the submitted/dispatching state. The acknowledgement gap is intentional: recovery redispatches the immutable envelope with the same executor idempotency key, allowing the provider to return the original job.

Shared orchestration never interprets Ansible fields. Teardown receives a provider-neutral settlement-result view, while the Ansible adapter validates its own metadata and derives the exact target it created.
