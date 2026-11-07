# Compute lease activation at the site

## Why

Every compute deal passes through a moment when its resource is ready and its lease
begins to run in earnest: `unify-compute-delivery-path` activates the lease there,
before billing starts and before access is disclosed, in both domains and on every
recovery path. The site has no such transition today. A lease is `leased` from commit
to release, with nothing recording that the resource was ever provisioned against it.

This change gives the site that transition and nothing else: one recorded instant, an
idempotent activation by reservation identity, and the path every storefront takes
to it. It reads no pool policy and carries no deadline, so it depends on nothing
outside the goal and lands before `renewable-compute-lease-deadlines`, which adds the
delivery deadline an unactivated lease expires at and depends on the pool-authority
port.

## What Changes

- Add one nullable column, `activated_at_utc`, to the site's reservation row, with an
  ordered migration in each service that hosts the ledger — compute provisioning and
  API credits — leaving every existing row null. Whether the site has recorded a
  lease's activation is derived from it; no phase is stored. Null means no activation
  recorded, never that a lease predating the column was not delivered.
- Add one conditional activation transition, admissible only on a lease — a `leased`
  reservation with a lease end: it writes `activated_at_utc` from the site's clock
  where it is null, in one transaction, and never updates it. A retry on an activated
  lease returns it unchanged; from any other state, and on an open-ended hold,
  activation is refused with nothing written. The request names the reservation
  and carries no payment fact, no target time and no instant. Activation never changes
  the lease's window, so an earlier truncation is adopted, never extended.
- Expose activation through the storefront's guarded capacity path, beside commit and
  truncation: the site's ledger and capacity router, the site client, core's
  `SiteCapacityAuthority` protocol and `AggregateCapacityClient`, and the kit's
  `CapacityEffects` and `CapacityRuntime`. It answers 200 with the recorded
  reservation, 404 for an unknown reservation, and 409 from any state but `leased` and
  for a reservation with no lease end.
- Show `activated_at_utc` on both views of the lease: the site's reservation view and
  the compute provisioning contract's `LeaseView`. The compute contract gains no
  activation route.
- Name activation among the storefront capacity effects that `market-composition` and
  `storefront-publication` bind to the listing's binding and its admission guard.

## Capabilities

### Modified Capabilities

- `site-capacity`: the activation instant, the transition, its answers and the
  migration.
- `compute-provisioning-contract`: `activated_at_utc` on the lease view.
- `market-composition`: activation among the capacity effects that pass the kit's
  guarded boundary under the persisted binding.
- `storefront-publication`: activation among the operations the binding's backing
  delegate guards.

### New Capabilities

None.

## Non-Goals

- The delivery deadline: its column, the pool's `delivery_deadline_seconds`, the
  accepted value and its anchor at commit, the expiry claim, the
  `activation_deadline_lapsed` cause and the `activation_deadlines_enabled` switch.
  All of it is `renewable-compute-lease-deadlines`, which derives "awaiting
  activation" from its own deadline and this change's instant.
- Renewal of active leases, lease extension, any payment or refund operation.
- Wiring the compute delivery callers: `unify-compute-delivery-path` owns that.
- Any compatibility path for a site without activation: storefronts and sites are
  deployed together.

## Dependencies and Related Changes

- No dependency. The work is the site's ledger and the client chain over it, and no
  package imports anything new.
- `unify-compute-delivery-path` depends on this change and activates every compute
  commit caller once, including recovery and Alkahest, through `CapacityEffects`.
- `renewable-compute-lease-deadlines` depends on this change: it adds its deadline
  column and conditions expiry on whether the lease is activated.
- Both, and `lapse-billing-with-the-site-lease`, describe the columns and the legacy
  no-op this design replaced; `design.md` names each difference for their own design
  work to reconcile.
- The site ledger keeps a compute lease's tail on the same row as API credits' quota
  grants, so API credits takes this change's migration though it has no leases.
  Separating the two is unowned work recorded in `openspec/changes/README.md`; this
  change does not depend on it.

## Impact and acceptance boundary

Site persistence and two migrations, one ledger transition, the site's router and
client, core's capacity protocol and aggregate, the kit's capacity effects, and the
compute contract's lease view. Exercised through the site API with a real embedded
database and no storefront, payment authority or deadline: activation of a leased
lease, an idempotent retry returning the same instant, refusal with no write from
every other state and on an open-ended hold, adoption of an earlier truncation before activation and between a
lost acknowledgement and its retry, the instant surviving restart and truncation, and
existing rows migrating with null in both services; and through the client chain:
activation routed to the binding's site and refused for an unbacked listing, and the
instant visible on `LeaseView`. It does not claim that any delivery caller activates;
that is `unify-compute-delivery-path`'s evidence.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — capacity reservation flow; the storefront
  capacity effects; deployment topology.
- [x] Existing subsystem specifications — `site-capacity`,
  `compute-provisioning-contract`, `market-composition`, `storefront-publication`,
  and the `site-capacity` and `market-composition` architecture companions.
- [ ] New subsystem specification.
- [ ] No permanent documentation change.

### Knowledge to promote

- D1 (the instant, the transition and the derived phase) to
  `openspec/specs/site-capacity/spec.md` and the reservation-lifecycle section of
  `openspec/specs/site-capacity/architecture.md`; the capacity reservation flow in
  `docs/development/ARCHITECTURE.md`.
- D2 (the write path) to `openspec/specs/market-composition/spec.md` and
  `openspec/specs/storefront-publication/spec.md`; the capacity effects named in
  `openspec/specs/market-composition/architecture.md` and
  `docs/development/ARCHITECTURE.md`.
- D3 (both views) to `openspec/specs/compute-provisioning-contract/spec.md`.
- D4 (storefront and site deployed together) to "Operators", under deployment
  topology, in `docs/development/ARCHITECTURE.md`, which already states that one
  business upgrades both together; closeout adds that no compatibility path is kept
  for an operation the site lacks.
- D5 (the answers) to `openspec/specs/site-capacity/spec.md`.
- D6 (both migrations) to `openspec/specs/site-capacity/spec.md`, and the shared
  row's consequence to "Current limits" in `openspec/specs/site-capacity/architecture.md`.
- D7 (no event, no push) to `openspec/specs/site-capacity/spec.md` and the
  reservation-lifecycle section of `openspec/specs/site-capacity/architecture.md`.
- D8: no permanent destination — the implementation cadence is this change's plan,
  not current behaviour.
- D9 (the instant's representation) to `openspec/specs/site-capacity/spec.md`.
- D10 (decided at implementation: the aggregate's route order raising the most
  informative refusal, and `CapacityEffects` refusing a result tagged with another
  site) to the storefront composition kit in
  `openspec/specs/market-composition/architecture.md`.
