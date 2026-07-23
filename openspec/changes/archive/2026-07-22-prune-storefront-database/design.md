## Context

The migrated pruning list named legacy policy/decision tables, `negotiation_messages`, and `resource_transition_events`. Current schema construction already removes the policy/decision tables. The remaining candidates are operational persistence rather than dormant write-only audit state.

## Goals / Non-Goals

**Goals:**
- Reconcile every candidate with current code and permanent contracts.
- Remove the stale broad pruning requirement from active work.

**Non-Goals:**
- Use absence of an ordinary `SELECT` as sufficient evidence that a table is dead.
- Remove recovery, continuation, idempotency, or operator-observability state.

## Decisions

### Close the change without synchronizing its delta

- Legacy decision, outcome, policy, and policy-composite tables are already absent and dropped during schema initialization.
- `negotiation_messages` is read by VM and API-credit negotiation continuation and detail views; the negotiation specification requires message persistence.
- `resource_transition_events` provides atomic duplicate suppression through its unique idempotency key and insert result.
- `stage_events` has authenticated system-event and e2e readers.

The migrated statement that persistence should contain only production-read state is invalid because constraint/idempotency state can be operational without a conventional query reader. Any future schema cleanup must enumerate exact objects and prove reader, writer, recovery, constraint, migration, and compatibility effects.

## Evidence

- Schema cleanup and core persistence: `core/storefront/src/core_storefront/sqlite_client.py`.
- Negotiation continuation: VM and API-credit `utils/sync_negotiation.py` implementations.
- Resource transition idempotency: `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`.
- Permanent negotiation ownership: `openspec/specs/negotiation-protocol/spec.md`.

## Risks / Trade-offs

- **[Dormant schema remains elsewhere]** → Open a narrow change with exact table evidence rather than restoring this generic rule.

## Promotion Record

No requirement is promoted. The rejected delta remains only in the archived change as provenance.
