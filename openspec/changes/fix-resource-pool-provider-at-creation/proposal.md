## Why

`ResourcePoolService.replace_pool` and `update_pool` permit an in-place executor
swap: when the supplied provider differs from the pool's own, the service calls
`delete_config` on the old provider's handler, reassigns `pool.provider`, and
writes configuration through the new one. Every member the pool already holds is
thereby reinterpreted as belonging to a different executor, silently and inside
one request. A member admitted as VM-deliverable becomes bare-metal-deliverable
without any check that the host, the reservation, or the obligation it backs can
survive that.

The same argument that made a pool's backing declaration immutable at creation
(`pool-declared-advertisement-and-backing`, archived 2026-09-22) applies to its
provider: both are the routing context every member inherits, and both change what
an existing reservation's authority means. `ResourcePoolService` already refuses a
backing change through `_require_backing_unchanged`; the provider has no such
guard.

This was Section 0 of `pools-9-retire-local-physical-authority`, added there on
2026-09-09 from Goal 7's design review because that campaign owned the
provisioning-side authority rules. It was split out on 2026-09-25: it is a
provisioning-side rule with no storefront surface, it lands independently of the
storefront cutover, and that cutover's start trigger is undefined by design.

## What Changes

- Replace and patch reject a request whose provider differs from the pool's
  own. Rejection leaves the pool exactly as it was: the existing provider
  configuration is not deleted on the way out.
- Provider configuration stays replaceable and patchable within the declared
  provider.
- Moving inventory to another executor is a second pool declaring the intended
  provider plus member migration. That path depends on
  `capacity-resource-administration`'s drain invariant (archived 2026-09-21): a
  reservation's pool is resolved through the resource's current `pool_id`, so a
  member may not move under a live obligation.

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
  provider now fails with the same refusal shape a backing change produces.
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

- Split out of `pools-9-retire-local-physical-authority` on 2026-09-25, whose
  `design.md` records the origin. No ordering dependency in either direction.
- Depends on `capacity-resource-administration`'s drain invariant, already
  landed, for the migration path this rule makes the only one.
- Follows the refusal pattern `pool-declared-advertisement-and-backing`
  established for the immutable backing declaration.
