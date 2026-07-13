## Context

The site ledger already implements hold, commit, release, versioned events, and cross-mode accounting. Shared lifecycle helpers currently live partly in `core_storefront`, while the VM-hosted provisioning service wires lease watchdog and VM/bare-metal release delegates through transitional re-exports. That shape obscures which state is authoritative and makes later package extraction carry upward storefront dependencies.

## Goals / Non-Goals

**Goals:**

- Define a lower site-authority port independent of executor lifecycle.
- Keep capacity unavailable until executor release succeeds.
- Isolate release failure and operator recovery in compute provisioning.
- Remove transitional re-exports after callers migrate.
- Preserve current allocation identities, events, and HTTP behavior.

**Non-Goals:**

- Move generic site authority into a storefront.
- Move or extract the deployable compute service.
- Change executor action payloads or job APIs.
- Generalize non-compute scheduling.

## Decisions

### Site authority owns facts; compute lifecycle owns actions

The site boundary owns Physical Resources, Resource Pools, Capacity Reservations, committed allocations, deal ownership references, capacity versions, and append-only events. It exposes hold, commit, inspect, release, and event-subscription operations.

Compute lifecycle owns leases, watchdog timing, executor selection, teardown/reclaim attempts, retry, force release, and release-failure diagnostics. It cannot mark capacity released until the configured executor delegate succeeds, except through an explicit audited force-release operation.

### Depend on a narrow injected port

Lease lifecycle consumes a structural port for allocation lookup, begin-release bookkeeping, successful release, and failed-release recording. It does not import storefront composition, HTTP clients, or concrete VM/bare-metal services. Production composition adapts the existing site ledger; tests use behaviorally equivalent fakes.

### Keep deal and capacity event channels distinct

Anonymous versioned capacity deltas remain suitable for projection subscribers. Deal-scoped lifecycle events retain the allocation's recorded deal reference and owner. The lower site layer records/routs ownership data without interpreting storefront domain payloads.

### Preserve transactional and idempotency invariants

Hold/commit/release and cross-mode conflict checks remain atomic in the site ledger. Duplicate release commands return the existing allocation state rather than executing a second capacity transition. Failed executor release leaves the allocation unavailable and records a repairable failure.

### Remove shims in the same cutover

Migrate callers from transitional `core_storefront`/VM re-export paths to the selected lower port and compute-lifecycle modules, then delete the re-exports. No compatibility aliases remain because all repository callers move together.

### Verification and rollback

Run site-ledger unit tests, lifecycle delegate tests, VM and bare-metal release integration tests, and a focused storefront projection scenario. Rollback restores the previous package set and database-compatible code; no schema rewrite is planned.

## Risks / Trade-offs

- **A port that mirrors one implementation could preserve accidental coupling.** Mitigation: specify operations in allocation lifecycle terms and test both in-memory and HTTP-backed adapters where present.
- **Moving event responsibility can duplicate or drop events.** Mitigation: preserve event IDs/idempotency keys and assert one observable capacity transition per committed release.
- **Force release can violate physical truth.** Accepted as an explicit operator recovery action; it must remain distinguishable from successful executor release.
- **Cross-package movement can create cycles.** Mitigation: lower site modules depend only on carrier/domain-neutral packages; composition remains above them.
