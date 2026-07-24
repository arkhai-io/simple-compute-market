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

Selection, any capacity rebind, and the fairness cursor advance share one database transaction. Retrying an equivalent request returns the durable assignment; a conflicting request is rejected rather than silently moving the reservation.

## Provider boundary

A FulfillmentProvider receives the selected resource and resolved execution inputs. It may validate that selection but may not substitute another placement. Create, status, and teardown are provider actions over the scheduler's decision.

Provider registration and executor registration are separate namespaces. A provider contract does not imply a lease-release executor, and an executor does not imply support for provider-neutral fulfillment.

## Identities and envelopes

Opaque identifiers keep routing and commercial meaning out of shared carriers. `capacity_reservation_id` is the scheduling and begin-fulfillment idempotency boundary; `settlement_resource_id` identifies selected supply; fulfillment, operation, result, and provisioned-resource identifiers describe later lifecycle records.

Provider-specific payloads cross persistence or package boundaries in versioned envelopes. A non-empty kind and positive schema version select an explicit validator. Unknown versions fail rather than inheriting today's provider assumptions.

## Durable aggregate and lifecycle convergence

The provisioning database owns one Settlement Record aggregate per Capacity Reservation, its provisioned-resource children, immutable versioned prepared operations, and durable fairness cursors. SQLite scheduling reserves the single writer slot before reading mutable scheduling state; databases with row-lock support lock the reservation. This makes capacity reassignment, assignment persistence, and cursor advancement one rollback-safe unit.

The public lifecycle is credential-owned and versioned: schedule and dry-run remain separate from acceptance; claimed workers exclusively dispatch immutable create/teardown commands and converge status without holding database locks during provider calls. Pull-based status and result reads reconstruct durable state on demand. VM credentials rotate at result-read time, transient credential rows are consumed, and only a monotonic generation remains durable.

Storefronts persist the trusted owning site and immutable lifecycle requests before remote calls. Their reconciler resumes after restart and never broadcasts after reservation. Whole-fulfillment teardown remains provisioning-owned and releases physical capacity only after provider success. Authenticated result push is not a current correctness path; pull is authoritative.

## Related contracts

- [Site capacity](../site-capacity/spec.md)
- [Resource-pool management](../resource-pool-management/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
