## Why

Cross-domain compute provisioning runs from provisioning/compute while VM and bare-metal semantics remain domain-owned.

## What Changes

- Complete the ownership moves, composition cleanup, executor split, and caller/image migration without preserving obsolete shims.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: Cross-domain compute provisioning runs from provisioning/compute while VM and bare-metal semantics remain domain-owned.

## Non-Goals

- Do not move deterministic domain schemas into the provisioner.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
