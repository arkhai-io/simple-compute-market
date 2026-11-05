# Proposal

## Why

Real compute delivery can already be purchased with Arkhai payments, but relay and bounded-cleanup qualification tasks currently name Alkahest-specific pytest drivers. An explicit equivalent proof method is needed to qualify the existing Arkhai buyer path without duplicating those scenario engines or claiming unrun modules passed.

## What Changes

- Define Arkhai real-hardware qualification through the shipped buyer CLI and existing independent operator observations.
- Map all remaining relay/direct/concurrent VM and bare-metal cleanup observations to that method, preserving completed implementation and original driver coverage.
- Reuse shared SSH, GPU checks, bounded-data probes and canonical APIs; add reusable source helpers only where a demonstrated gap prevents the method.
- Document the verified reusable procedure after execution; keep environment-specific orchestration and raw evidence outside this public repository.

No payment-provider SDK, new settlement mechanism, replacement allocator, new default pipeline lane, host-specific configuration or LIVE-money test is introduced. Hosted funding belongs to the external payment authority. Hardware results remain unproven until the procedures actually run.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: Arkhai real-provisioning qualification has explicit evidence equivalence, ownership and recovery boundaries alongside existing real pytest lanes.

## Impact

Planning amendments affect `prove-relay-provisioning` section 16 and `bound-bare-metal-working-data` section 4 on this branch. Existing pytest markers and product support remain available. Conditional helper factoring is confined to `e2e-tests/tests/e2e/roles/helpers/real_provisioning.py` and bare-metal working-data helpers, with lowest-level tests. Durable method documentation belongs to `docs/development/TESTING.md`, `docs/development/VALIDATION_RUNBOOK.md` and the test-compatibility architecture companion. No wire or database migration.
