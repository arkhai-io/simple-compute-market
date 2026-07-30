# Design: Capacity Settlement Scheduler

## Design goals

The design separates accepted capacity from the concrete scheduling decision and separates that decision from provider-specific execution. It favors a small, deterministic policy that can be understood and tested now while preserving an interface for richer policies later.

The scheduler is an orchestrator. A policy receives only an already-filtered set of eligible candidates and chooses one. Policies do not load allocations, inspect agreements, query provider models, persist assignments, or decide whether explicit requests are valid.

## Standard vocabulary

1. **Capacity Reservation** — accepted capacity plus agreement identity, requested shape or units, lifecycle state, and expiry.
2. **Capacity Settlement Assignment** — the idempotent decision mapping one unchanged reservation to one concrete pooled resource.
3. **Physical Settlement** — provider-specific execution on that assigned resource.
4. **Provisioned Resource / Active Workload** — the resulting running resource or service.

An assignment does not imply that physical settlement has started, succeeded, or remains active.

## Responsibilities

### `PhysicalSettlementScheduler`

- load and validate the Capacity Reservation;
- validate represented agreement, market, and terms relationships;
- reject inactive or expired reservations;
- return an existing assignment without rerunning policy;
- construct executor-neutral requirements and candidates;
- enforce pool and resource eligibility;
- handle exact-resource constraints;
- invoke the configured policy for automatic selection;
- record the Capacity Settlement Assignment.

### `SettlementSchedulingPolicy`

The protocol lives in `arkhai-compute-provisioning` so services can supply independent policies without importing one another. It selects one candidate from an already eligible sequence and does not own validation or persistence.

### `DeterministicRoundRobinPolicy`

The initial VM-service policy lives separately from scheduler orchestration because it is one member of a future policy family. It maintains a pool cursor and a per-pool resource cursor.

## Eligibility

Every resource eligible for physical settlement belongs to exactly one Resource Pool. A resource with no pool is not connected to physical settlement. A resource represented in multiple pools misrepresents true system capacity and is invalid configuration.

An eligible candidate must:

- exist and be enabled;
- belong to exactly one existing enabled pool;
- match the reserved resource kind;
- match all required generic attributes;
- have sufficient available units for the reservation;
- expose the opaque provider metadata required by the downstream settlement boundary.

Provider reachability, credentials, executor topology, and actual provisioning success are evaluated during physical settlement rather than by generic policy code.

An explicit resource request bypasses scheduling policy choice only. It passes every allocation, agreement, expiry, pool, resource, shape, attribute, and capacity check used by automatic scheduling. Explicit selection does not advance round-robin cursors.

## Deterministic round-robin policy

The MVP policy performs two deterministic choices:

1. Group eligible candidates by pool, sort pool IDs, and select the pool after the last automatically selected pool.
2. Sort resource IDs in the selected pool and select the resource after the last automatically selected resource for that pool.

If the prior cursor value is no longer eligible, selection starts at the first sorted eligible value. Disabled or exhausted pools never enter the policy input. A retry that finds an existing assignment returns it and does not advance either cursor.

This policy provides basic distribution and deterministic tie-breaking. It is not DRF: it does not identify competing consumers, track dominant shares, or compare multidimensional allocations.

## Pool disablement

Disabling a pool is a draining operation. It immediately removes the pool from new Capacity Settlement Assignments. Existing reservations, assignments, physical settlements, and active workloads do not prevent disablement and are not invalidated by it.

POOLS-2 does not migrate unassigned reservations or existing assignments to another pool. A reservation constrained to a concrete resource in a disabled pool fails eligibility.

## Domain boundary

Generic scheduling consumes allocation identity, agreement identity, market, requested units, resource kind, pool identity, available units, provider identity, and opaque attributes. It must not import VM hosts, hypervisors, Kubernetes nodes, inference workers, storage-provider models, or their ORM sessions.

A VM resource may carry an opaque provider reference in its attributes. The VM fulfillment provider resolves that reference during physical settlement. Other domains can supply different resource kinds and opaque attributes while reusing the same scheduler and policy contracts.

## Validation errors

- `SettlementEntityNotFoundError` — a referenced allocation, agreement, pool, or resource does not exist.
- `SettlementRequestMismatchError` — existing entities or terms do not correspond to the request, or the allocation is not active.
- `CapacityReservationExpiredError` — the allocation existed but its hold expired.
- `NoEligibleSettlementResourceError` — the request is valid but no candidate can currently satisfy it.

The error taxonomy is intentionally small. Entity type and identity should be retained in messages or structured fields rather than introducing a class for every noun.

## Persistence and atomicity

The durable transaction is:

1. lock the reservation;
2. validate state and request relationships;
3. return an existing unchanged assignment if present;
4. lock policy cursor state;
5. re-evaluate eligible candidates;
6. claim capacity on the selected concrete resource;
7. persist the assignment;
8. advance policy cursors;
9. commit.

A Python lock protects only one scheduler object in one process and is not the final concurrency mechanism. Process-local assignment and cursor repositories are an explicitly documented intermediate implementation.

## Alternatives considered

### Re-run selection on every request

Rejected because retries could move an accepted reservation between resources and make downstream settlement non-idempotent.

### Let explicit resources bypass eligibility

Rejected because an exact-resource request is a placement constraint, not permission to use disabled, exhausted, orphaned, or incompatible capacity.

### Block pool disablement while assignments exist

Rejected because assignment is not workload liveness. Disablement is better modeled as draining new work.

### Implement DRF in POOLS-2

Rejected as scope creep. The current problem is deterministic eligible placement, while classical DRF requires competing consumer identities and multidimensional share accounting. POOLS-6 preserves the design questions for a later session.

### Import an existing full scheduler

Deferred. Established schedulers generally own worker models, queues, or cluster runtimes larger than this policy boundary. Richer policy evaluation is tracked independently from this deterministic baseline.

## Design promotion record

| Accepted decision | Permanent location or disposition |
|---|---|
| Capacity reservation, settlement assignment, provider execution, and provisioned output are distinct lifecycle stages | `openspec/specs/site-capacity/spec.md#capacity-settlement-lifecycle`; `openspec/specs/physical-provisioning/spec.md#capacity-settlement-lifecycle` |
| Scheduling is provider- and executor-neutral and policy receives only eligible candidates | `openspec/specs/fulfillment/spec.md#scheduling-and-assignment` |
| Automatic placement is deterministic pool-then-resource round-robin; explicit resources bypass choice but not eligibility | `openspec/specs/fulfillment/spec.md#scheduling-and-assignment` |
| Schedulable resources belong to one enabled pool and disablement drains new assignments | `openspec/specs/resource-pool-management/spec.md#scheduling-membership-and-draining` |
| Process-local assignment and cursor state is not distributed idempotency | `openspec/specs/fulfillment/spec.md#scheduling-and-assignment` |
| Durable assignment/cursor persistence, caller cutover, and multi-replica recovery | Transferred to `pools-7-storefront-fulfillment-cutover` sections 3–4, 7, and 9 |
| Deferring the initial concrete claim until scheduling | Superseded by `openspec/specs/site-capacity/spec.md#internal-capacity-accounting`: admission creates a private bucket debit and scheduling may atomically rebind it |
| Original package and commercial-identity placement | Superseded by `market_fulfillment` ownership and the reservation-local identity rules in `openspec/specs/fulfillment/spec.md` |
