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

Selection creates a binding. Retrying an equivalent request returns the existing assignment, durably recorded on the settlement aggregate so equivalence survives a process restart; a conflicting request is rejected rather than silently moving the reservation.

`schedule_resource` and `begin_fulfillment` are two separate calls, orchestrated by the caller, rather than one atomic "reserve and fulfill" operation, because the selected physical resource may be commercially material before fulfillment actually begins -- a caller may need to see (and price around) which resource was selected before committing to dispatch it. A thin convenience wrapper may compose both for a caller that doesn't need that preview, but it uses the same two underlying application paths rather than a third combined one.

## Provider boundary

A FulfillmentProvider receives the selected resource and resolved execution inputs. It may validate that selection but may not substitute another placement. Create, status, and teardown are provider actions over the scheduler's decision.

Provider registration and executor registration are separate namespaces. A provider contract does not imply a lease-release executor, and an executor does not imply support for provider-neutral fulfillment.

## Identities and envelopes

Opaque identifiers keep routing and commercial meaning out of shared carriers. `capacity_reservation_id` is the scheduling and begin-fulfillment idempotency boundary; `settlement_resource_id` identifies selected supply; fulfillment, operation, result, and provisioned-resource identifiers describe later lifecycle records.

Provider-specific payloads cross persistence or package boundaries in versioned envelopes. A non-empty kind and positive schema version select an explicit validator. Unknown versions fail rather than inheriting today's provider assumptions.

## Durable persistence and recovery

One `SettlementRecord` aggregate exists per `capacity_reservation_id`, covering the entire physical settlement lifecycle: scheduling, fulfillment acceptance, provider dispatch, provider-status convergence, and teardown all read and write the same durable row, not separate process-local structures. `schedule_resource` and `begin_fulfillment` retries are idempotent against this row rather than in-memory state, and survive a process restart. The two-level round-robin scheduling cursor is likewise a durable row (`SchedulingCursor`), not process-local policy state.

Recovery from a stuck or interrupted provider operation is provisioning-owned: a periodic convergence worker claims eligible rows under SQLite's single-writer contract (a short, self-contained write-reservation transaction, not portable row locking or a distributed multi-replica protocol), performs provider I/O outside any open transaction, and applies the outcome only while it still holds the claim. See [the fulfillment spec](spec.md#fulfillment-convergence-worker) and [durable settlement persistence](spec.md#durable-settlement-persistence) for the normative contract this section summarizes.

The implemented scheduling baseline remains deterministic two-level round-robin with multidimensional eligibility; more advanced fairness policy is not implied by the request or carrier abstractions.

## Related contracts

- [Site capacity](../site-capacity/spec.md)
- [Resource-pool management](../resource-pool-management/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)


## Fulfillment acceptance and dispatch acknowledgement

Fulfillment acceptance freezes provider input before side effects. One transaction serializes acceptance, loads the selected resource and provider configuration, prepares the provider-specific envelope, and persists it with `dispatch_pending`. Dispatch happens after commit. A second short transaction records normalized provider metadata and advances the aggregate to `dispatching`. The acknowledgement gap is intentional: recovery redispatches the immutable envelope with the same executor idempotency key, allowing the provider to return the original job.

Shared orchestration never interprets Ansible fields. Teardown receives a provider-neutral settlement-result view, while the Ansible adapter validates its own metadata and derives the exact target it created.

## Atomic legacy-lease cutover

Active workloads and provider-operation identities are financially and operationally significant, while unused pre-release reservation rows are not authoritative. The cutover therefore joins reservation and resource-pool data around the legacy lease population, validates the complete population before writing, and commits all generated settlement aggregates and provisioned-resource rows in one transaction. Ambiguity is handled by aborting the cutover rather than by speculative repair.

Per-candidate state derivation and provider-envelope preparation are implemented as a pure, domain-owned compiler (one already-read historical row in, a durable row draft or a validation error out — no database session). The enumerating migration owns everything the compiler does not: the SQL join, cross-candidate identity/target deduplication, comparison against already-persisted rows, and the single atomic write. Keeping per-candidate logic free of database access lets every historical state and validation branch be tested directly, independent of a live schema, while the population-level concerns that only make sense against a real connection are tested separately against one.

## Fulfillment result ownership

The fulfillment kit owns lifecycle identity, durable output identity through `provisioned_resource_id`, and the outer `fulfillment.result.v1` envelope. Domain adapters own nested versioned result payloads and credential schemas. Provider-domain object identifiers used to execute or tear down work remain in versioned provider metadata; they are not duplicated on generic `ProvisionedResource` rows. Active result reads close the database transaction before provider I/O, fetch a fresh domain result on every call, and fail atomically when that fetch cannot be completed.

This split creates two different consistency guarantees in the same response, deliberately. The outer envelope's aggregate-derived fields (state, failure detail, provisioned-resource identity) are durable-row reads and are therefore stable across repeated calls for as long as the aggregate itself hasn't changed. The inner `domain_result` is a live external read and carries no such guarantee — nothing in this design promises two calls return equal credentials, and a caller comparing them for equality is relying on a property this system does not provide. Choosing to fetch fresh on every call, rather than caching or memoizing, trades request cost for never serving stale access material; a credential-fetch failure therefore rejects the whole result rather than falling back to a cached or partial one, since there is nothing durable behind it to fall back to.

## Storefront pull composition

A bare-metal storefront composes the public scheduler and fulfillment client rather than importing provisioning repositories or workers. The storefront reloads its accepted listing/site/domain binding, targets capacity reservation at that exact site, schedules the accepted Physical Resource, and calls begin with the returned settlement resource. It persists opaque lifecycle correlations so duplicate calls and process restart resume the same provisioning aggregate.

Status and result delivery are pull-based. The storefront polls the recorded site and fulfillment identity, requires the durable outer state to be `active`, validates the nested bare-metal domain envelope, and records one buyer-safe receipt and access result. The receipt carries an opaque fulfillment reference, machine and physical-host accounting identities, and lease bounds; the access result carries the completed action and public SSH user. Storefront normalization removes adapter `details` wholesale and never copies provider metadata, authority URLs, private credentials, or raw execution output. Provider credential refresh remains behind the provisioning authority rather than turning storefront persistence into a credential store.

Teardown remains split by authority. The storefront requests teardown for the recorded fulfillment and polls provisioning convergence; only authoritative teardown success permits release of the recorded Capacity Reservation. The durable reservation-to-site map keeps release routed to the same authority across restart, and idempotent terminal state prevents a duplicate capacity return.
