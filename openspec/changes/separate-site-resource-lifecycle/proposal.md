## Why

Generic site resource/allocation/event persistence is independent of lease watchdog and executor teardown policy.

## What Changes

- Narrow the lower ledger interface, move delegate-based lease lifecycle into shared provisioning support, and add failed-release monitoring.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: Generic site resource/allocation/event persistence is independent of lease watchdog and executor teardown policy.

## Non-Goals

- Do not make the generic site layer understand VM teardown states.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
