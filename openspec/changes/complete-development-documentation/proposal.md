## Why

Role-facing behavior and troubleshooting are scattered or missing, while several legacy documentation gaps describe intended work without a concrete audience. Documentation should follow the person acting on it—buyer, seller, registry operator, provisioner, or test contributor—while OpenSpec owns current normative behavior and intended changes.

## What Changes

- Move verified current usage constraints and troubleshooting into the relevant role quickstart, operator guide, or contributor guide.
- Keep the corresponding current behavioral contract in the owning OpenSpec capability specification.
- Verify and document the remaining baked-contract, escrow, schema, negotiation-watchdog recovery, and GPU-passthrough gaps for a named role audience.
- Remove generic known-issues and development-document dumping grounds once every entry has a role-facing or OpenSpec destination.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `planning-governance`: Documentation ownership follows role audience; OpenSpec remains canonical for current normative behavior and intended changes.

## Non-Goals

- Do not duplicate normative OpenSpec requirements in prose documentation.
- Do not keep implementation intentions in role guides; link to the owning active change instead.

## Impact

Documentation structure and contributor workflow change. Runtime APIs, persistence, packaging, and deployment behavior do not change.
