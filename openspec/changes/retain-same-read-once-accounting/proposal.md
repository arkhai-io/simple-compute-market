## Why

A normal seller watch already reads verified payment state and atomically records its observation, final stops and cursor. A separate accounting read could disagree with that state or multiply service calls. Repeating the same financial sequence must preserve the first durable receipt rather than treat a refreshed signature as changed finance.

## What Changes

Add an optional neutral once-accounting reader capability. The payments adapter derives bounded TEST once-only accounting from its ordinary verified read. Seller servicing retains a small immutable assertion in its existing evidence store and marks conflicting same-sequence finance unqualified. Public lifecycle reads and watch results keep their existing shape.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deal-lifecycle`: same-read optional accounting and atomic durable evidence.

## Non-Goals

No new payment request, rate accounting, LIVE accounting, payment authorization, physical action, pruning policy, schema migration or HTTP contract. Accounting never admits a return.

## Impact

The lifecycle kit adds neutral dataclasses and an optional protocol; the payments and servicing kits consume them. Existing SQLite evidence storage and migration ownership remain unchanged. Lifecycle and payments receive additive minor versions, servicing an internal patch; both consumers require lifecycle 0.6.0. Release integration also updates the bare-metal buyer and storefront to require payments 0.10.0, and the VM storefront to require the updated bare-metal storefront. These three dependent metadata changes receive patch versions; ordinary downstream locks are regenerated from repository wheels.

## Permanent documentation impact

- Existing capability specification: delta under `specs/deal-lifecycle/spec.md`.
- Existing architecture: `openspec/specs/deal-lifecycle/architecture.md`, same-read observation and evidence.
- Cross-system architecture: unchanged; no new dependency direction, subsystem or authority.
