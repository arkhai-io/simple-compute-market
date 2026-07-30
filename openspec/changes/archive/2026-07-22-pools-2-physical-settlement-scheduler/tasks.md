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

## Follow-on disposition

These checked items record completion, transfer, or supersession of the original
follow-on inventory; they do not claim transferred work was implemented here.

- [x] Transfer durable Capacity Settlement Assignment and round-robin cursor persistence to `pools-7-storefront-fulfillment-cutover` sections 3–4.
- [x] Supersede deferred initial concrete-resource claiming with the private capacity-bucket debit and atomic scheduling-time rebind model in `openspec/specs/site-capacity/spec.md#internal-capacity-accounting`.
- [x] Complete exactly-one-pool membership enforcement through the resource-pool scheduling-membership invariant and database constraints implemented with the fulfillment cutover.
- [x] Transfer caller-facing scheduler/fulfillment wiring to `pools-7-storefront-fulfillment-cutover` section 9.
- [x] Transfer multi-process concurrency and restart idempotency evidence to `pools-7-storefront-fulfillment-cutover` sections 3–4 and 7.
- [x] Run the complete repository integration suite and strict OpenSpec validation in the canonical development environment.

## Archive synchronization

- [x] Promote deterministic pool-then-resource round-robin, explicit-resource eligibility, process-local limitations, and scheduling error distinctions to `openspec/specs/fulfillment/spec.md#scheduling-and-assignment`.
- [x] Promote the reservation scheduling view without commercial identity to `openspec/specs/site-capacity/spec.md#requirement-reservation-scheduling-view`.
- [x] Confirm exactly-one-pool membership and draining behavior in `openspec/specs/resource-pool-management/spec.md#scheduling-membership-and-draining`.
- [x] Record permanent destinations, transferred work, and superseded accounting design in `design.md`.
