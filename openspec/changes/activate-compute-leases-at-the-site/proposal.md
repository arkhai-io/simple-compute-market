# Compute lease activation at the site

## Why

Every compute deal passes through a moment when its resource is ready and its lease
begins to run in earnest: `unify-compute-delivery-path` activates the lease there,
before billing starts and before access is disclosed, in both domains and on every
recovery path. The site has no such transition today. A lease is `leased` from commit
to release, with nothing recording that the resource was ever provisioned against it.

This change gives the site that transition and nothing else: an activation phase, an
idempotent activation call by reservation identity, and the typed contract and
client every compute caller uses for it. It reads no pool policy and carries no
deadline, so it depends on nothing outside the goal and lands before
`renewable-compute-lease-deadlines`, which adds the delivery deadline that an
unactivated lease expires at and depends on the pool-authority port.

## What Changes

- Add nullable `renewal_phase`, `renew_by_utc` and `activated_at_utc` to the site's lease row, with a
  service-owned migration that leaves every existing row null. `lease_end_utc` keeps
  meaning the agreed end and moves only through truncation. The phase takes the
  values `awaiting_activation` and `active`; this change sets only `active`, and
  `renew_by_utc` stays null until the deadline change writes it at commit.
- Add one conditional activation transition: from `leased`, in phase
  `awaiting_activation` or null, to phase `active`, setting the lease's due instant to
  its current `lease_end_utc`. The request names the reservation and carries no
  payment fact and no target time. Retried in `active` it returns the current lease
  unchanged; from `releasing`, terminal, failed-release or operator-owned states it
  refuses without a write. Activation never changes the reservation's end, and a
  verified earlier truncation is adopted, never extended.
- Expose activation and lease inspection — the phase, the nullable due instant and
  `activated_at_utc`, the instant the transition writes once and never moves — through
  the site's typed authority, HTTP models,
  router and client, and through the shared compute contract and client, offering-mode
  neutral, under the existing authenticated service boundary with exact response
  verification.
- A null-phase lease — one with no deadline written, which is every lease before the
  deadline change is switched on — reads as null and activates like any other on a site
  that exposes the operation; the legacy no-op is only for a site that exposes none,
  with a verified legacy view.

## Capabilities

### Modified Capabilities

- `site-capacity`: the activation phase and the activation transition.
- `compute-provisioning-contract`: typed activation and lease inspection.

### New Capabilities

None.

## Non-Goals

- The delivery deadline: the pool's `delivery_deadline_seconds`, the accepted value
  and its anchor at commit, the expiry claim of the observed tuple, the
  `activation_deadline_lapsed` cause and the `activation_deadlines_enabled` switch.
  All of it is `renewable-compute-lease-deadlines`, which writes the deadline this
  change's activation then replaces with the agreed end.
- Renewal of active leases, lease extension, any payment or refund operation.
- Wiring the compute delivery callers: `unify-compute-delivery-path` owns that.

## Dependencies and Related Changes

- No dependency outside Goal 8. The work is site-local and the site imports nothing
  new.
- `unify-compute-delivery-path` depends on this change and activates every compute
  commit caller once, including recovery and Alkahest, through the contract this
  change ships.
- `renewable-compute-lease-deadlines` depends on this change: it writes
  `renew_by_utc` and `awaiting_activation` at commit into the fields this change adds,
  and conditions expiry on the phase this change's activation sets.
- `capacity-reservation-lifecycle-hardening` owns hold expiry indexing on the same
  table; this change's migration adds columns only and coordinates its order with
  that change's migrations.

## Impact and acceptance boundary

Site persistence and migration, one ledger transition, the typed site authority,
models, router and client, and the shared compute contract and client. Exercised
through the site API with a real embedded database and no storefront, payment
authority or deadline: activation from each admissible phase, idempotent retry,
refusal from every non-admissible state, adoption of an earlier truncation, and
null-phase leases activating like any other on a site with the operation. It does not claim that any delivery caller
activates; that is `unify-compute-delivery-path`'s evidence.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — capacity reservation: the activation phase.
- [x] Existing subsystem specifications — `site-capacity`,
  `compute-provisioning-contract`.
- [ ] New subsystem specification.
- [ ] No permanent documentation change.

### Knowledge to promote

- D1 (phase and transition) to `openspec/specs/site-capacity/spec.md` and its
  architecture companion; capacity reservation in `docs/development/ARCHITECTURE.md`.
- D2 (typed activation and inspection) to
  `openspec/specs/compute-provisioning-contract/spec.md`.
