## Why

`ResourcePoolService.replace_pool` and `update_pool` permit an in-place executor
swap: when the supplied provider differs from the pool's own, the service calls
`delete_config` on the old provider's handler, reassigns `pool.provider`, and
writes configuration through the new one. Every member the pool already holds is
thereby reinterpreted as belonging to a different executor, silently and inside
one request. A member admitted as VM-deliverable becomes bare-metal-deliverable
without any check that the host, the reservation, or the obligation it backs can
survive that.

A pool's backing declaration is immutable at creation for the same reason:
both are the routing context every member inherits, and both change what an
existing reservation's authority means. `ResourcePoolService` already refuses a
backing change through `_require_backing_unchanged`; the provider has no such
guard.

## What Changes

- Replace and patch reject a request whose provider differs from the pool's
  own. Rejection leaves the pool exactly as it was: the existing provider
  configuration is not deleted on the way out.
- Provider configuration stays replaceable and patchable within the declared
  provider.
- Moving inventory to another executor is a second pool declaring the intended
  provider plus member migration. The drain invariant already forbids a member
  from leaving a pool under a live obligation, which is what makes that path
  safe.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `resource-pool-management`: a pool's provider is fixed at creation.

## Non-Goals

- Do not add a pool-move or member-migration command; the two-pool path uses
  the existing pool and member administration APIs.
- Do not change how providers are registered or how their configuration is
  validated.
- Do not touch the storefront.

## Impact

- `kit/resource-pools`' `ResourcePoolService.replace_pool` and `update_pool`,
  and the pool administration routes and canonical client that reach them.
- No wire shape changes; a request that previously succeeded by swapping the
  provider fails with the same refusal shape a backing change produces.
- No fixture or e2e setup is known to rely on an in-place swap; task 0.5
  confirms.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/resource-pool-management/spec.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A pool's provider is fixed at creation; replace and patch refuse a differing
  provider without deleting existing configuration; inventory moves executors
  by a second pool and member migration —
  `openspec/specs/resource-pool-management/spec.md`.

## Dependencies and Related Changes

- Depends on the drain invariant `capacity-resource-administration` (archived)
  established, for the migration path this rule makes the only one.
- Follows the refusal pattern the immutable backing declaration established in
  `ResourcePoolService`.
- Independent of `pools-9-retire-local-physical-authority`; either order.
