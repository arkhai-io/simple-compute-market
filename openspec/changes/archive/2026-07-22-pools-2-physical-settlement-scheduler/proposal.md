# POOLS-2: Capacity Settlement Scheduler

## Context

POOLS-1 establishes Resource Pools as provider-configuration and physical-capacity boundaries. Capacity Reservations already let a seller accept a bounded amount of capacity, but the system still needs an explicit step that chooses the concrete pooled resource on which physical settlement will run.

Without that boundary, reservation, placement, and provisioning become conflated. Retries can repeat placement decisions, provider-specific host models can leak into shared contracts, and pool administration cannot reliably express "stop assigning new work here" independently of existing workloads.

The lifecycle used by this change is:

**Capacity Reservation → Capacity Settlement Assignment → Physical Settlement → Provisioned Resource / Active Workload**

A Capacity Settlement Assignment is a scheduling decision, not evidence that provisioning succeeded or that the resource remains active.

## Why

POOLS-2 introduces an explicit, idempotent scheduling boundary between accepted capacity and provider-specific physical settlement. The scheduler validates the reservation and its agreement relationship, filters concrete resources by generic eligibility, and records one assignment for the unchanged reservation.

The first policy is intentionally modest. Deterministic round-robin provides basic fairness and proves that policy is replaceable without introducing multidimensional fairness, quotas, topology, or provider-specific placement into this change.

## Goals

- Establish executor-neutral request, candidate, assignment, result, error, and policy contracts.
- Create at most one Capacity Settlement Assignment for an unchanged reservation.
- Validate allocation identity, agreement relationship, state, expiry, market, terms, pool state, membership, resource kind, attributes, and capacity.
- Select only resources that belong to exactly one enabled Resource Pool.
- Treat explicit resource identifiers as policy bypasses, never eligibility bypasses.
- Provide deterministic round-robin selection across eligible pools and then eligible resources.
- Treat pool disablement as draining new assignments while preserving existing work.
- Keep generic scheduling independent of VM hosts and other market-specific executor persistence.
- Leave a stable policy interface for later scheduling algorithms.

## Non-goals

- Caller-facing endpoint wiring or automatic invocation from the settlement flow.
- Full Dominant Resource Fairness or other multidimensional fairness policies.
- Buyer-selected pool constraints; current use cases request generic capacity or a specific concrete resource.
- Provider health probing, credentials validation, or execution-time reachability checks.
- Automatic migration of existing assignments when a pool is disabled.
- Reassignment after provisioning failure.
- Priority, quota, preemption, affinity, anti-affinity, cost, or topology-aware placement.

## What changes

- Add executor-neutral scheduling contracts in `arkhai-compute-provisioning`.
- Add a replaceable `SettlementSchedulingPolicy` protocol in the kit.
- Add a deterministic round-robin policy implementation in the VM provisioning service.
- Make `PhysicalSettlementScheduler` responsible for validation, idempotency, candidate construction, explicit-resource handling, and assignment recording.
- Remove VM `Host` joins and executor-specific interpretation from generic scheduling.
- Define Resource Pool disablement as draining new assignments.
- Add normative deltas for site capacity, resource pools, and physical provisioning.
- Add POOLS-6 as deferred work for multidimensional fair policies.

## Intermediate-state limitations

The repository still reserves against a concrete site-ledger line item before POOLS-2 scheduling. The scheduler credits the reservation's own held units during eligibility checks. Capacity Settlement Assignments and round-robin cursors are also process-local, so retries are idempotent only within the running service instance.

The durable target atomically locks the reservation, checks for an existing assignment, locks scheduling state, evaluates eligibility, claims concrete capacity, persists the assignment, advances cursors, and commits. Moving the concrete capacity claim and assignment state into that transaction remains follow-on work.

## Operational impact

Disabling a pool immediately prevents new assignments to its resources. Existing reservations, assignments, physical settlements, and workloads continue. Operators can therefore drain a pool without first terminating active work.

Scheduling failures distinguish missing entities, mismatched requests, expired reservations, and absence of eligible resources so callers can choose appropriate recovery behavior.

## Closure reconciliation

Subsequent package extraction moved provider-neutral scheduling contracts and policy to `arkhai-kit-fulfillment` (`market_fulfillment`). Generic scheduling is keyed by `capacity_reservation_id` and validates reservation-local physical requirements; commercial agreement, market, and terms identity remain at the storefront. Multidimensional `dimensions`/`available` maps supersede the original single-unit carrier language.

The implemented deterministic scheduler remains process-local. Durable assignment/cursor persistence, production caller wiring, and restart/multi-replica evidence are transferred to `pools-7-storefront-fulfillment-cutover`. The earlier intent to defer the initial concrete capacity claim until scheduling is superseded by private admission-time bucket debits with atomic scheduling-time rebind.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge promoted

- Scheduling and assignment behavior is recorded in `openspec/specs/fulfillment/spec.md#scheduling-and-assignment`.
- Reservation scheduling data and authority are recorded in `openspec/specs/site-capacity/spec.md#requirement-reservation-scheduling-view`.
- Pool membership and draining semantics are recorded in `openspec/specs/resource-pool-management/spec.md#scheduling-membership-and-draining`.
- Repository-wide lifecycle vocabulary and authority boundaries are recorded in `docs/development/ARCHITECTURE.md`.
