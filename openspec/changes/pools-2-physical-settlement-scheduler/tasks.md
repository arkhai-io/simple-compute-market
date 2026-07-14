# POOLS-2 tasks

## Implemented

- [x] Extract provider-neutral Resource Pool administration into `kit/resource-pools`.
- [x] Add capacity-reservation watchdog service and configuration.
- [x] Add executor-neutral settlement request, requirement, candidate, assignment, policy, resource, and error contracts.
- [x] Rename the process-local assignment map to `_capacity_settlement_assignments`.
- [x] Replace pseudo-DRF selection with deterministic pool/resource round-robin.
- [x] Remove VM `Host` imports and joins from the scheduler.
- [x] Validate allocation existence, state, expiry, agreement, market, and terms when represented by the reservation.
- [x] Apply normal eligibility checks to explicit resource requests.
- [x] Treat pool disablement as draining and remove assignment-based disable guards.
- [x] Add focused scheduler and contract tests.
- [x] Add POOLS-6 deferred fair-scheduling change.
- [x] Update ARCHITECTURE.md and POOLS-2 normative deltas.

## Remaining follow-on work

- [ ] Persist Capacity Settlement Assignments and round-robin cursors transactionally.
- [ ] Move the concrete resource capacity claim from initial reservation into the assignment transaction.
- [ ] Enforce exactly-one-pool membership at the database layer after migration/backfill.
- [ ] Wire the scheduler into caller-facing settlement endpoints.
- [ ] Add multi-process concurrency and restart integration tests for durable idempotency.
- [ ] Run the complete repository integration suite and strict OpenSpec validation in the canonical development environment.
