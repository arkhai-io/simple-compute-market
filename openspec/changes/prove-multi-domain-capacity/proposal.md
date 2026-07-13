## Why

A shared site authority routes allocation jobs and deal events for more than one executor and storefront domain.

## What Changes

- Add allocation-id keyed job-kind dispatch, deal-ref event routing, a second executor kind, and a second storefront domain sharing capacity.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: A shared site authority routes allocation jobs and deal events for more than one executor and storefront domain.

## Non-Goals

- New non-compute resource domains are out of scope.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
