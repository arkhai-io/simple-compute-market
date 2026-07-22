## Why

The capacity check accepts optional vCPU, RAM, and GPU requirements and returns eligible ranked hosts.

## What Changes

- Audit the proposed host-ranking endpoint against the current site-capacity and fulfillment scheduling authorities.
- State: **Rejected as superseded; archive without synchronizing the delta.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: The capacity check accepts optional vCPU, RAM, and GPU requirements and returns eligible ranked hosts.

## Related Changes

- Archived POOLS-6 multidimensional admission and active POOLS-7 fulfillment scheduling now own authoritative fit and candidate ordering.
- The existing host-capacity endpoint is a diagnostic for one already selected host. Expanding it into authoritative ranked placement would duplicate or bypass those boundaries.

## Non-Goals

- Do not add ranking to the legacy one-host diagnostic endpoint.
- Do not synchronize this rejected delta into the permanent physical-provisioning specification.
- A future read-only operator search requires a fresh change with an explicit use case and no assignment authority.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
