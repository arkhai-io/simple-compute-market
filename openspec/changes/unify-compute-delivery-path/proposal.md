## Why

The two compute domains reach commit, dispatch, disclosure, and the end of a deal
through different code with different windows. VM's `VmPaymentsCoordinator.start`
verifies the approval receipt, inserts the delivery, spawns `_provision`, and records
`lease_end_utc = start + duration` from the Agreement; bare metal's
`fulfillment_service.py` commits `lease_start = now`, `lease_end = now + duration`,
ignoring the Agreement's `start_utc`, and exposes delivery through its own
`/fulfillments/{negotiation_id}/access` and `/result` routes. VM substitutes an hour
for a missing duration on resume (`fulfillment_resume_runtime.py:95`, `:264`). Neither
activates the lease after delivery, because nothing at the site asks it to yet
([`renewable-compute-lease-deadlines`](../renewable-compute-lease-deadlines/)), and
neither has a place where a mechanism could say "do not deliver" before a transition.
`kit-owned-listing-and-fulfillment-lifecycles` proposes a unified fulfillment path for
the family and has not designed it; `ARCHITECTURE.md` says a divergence of this kind is
resolved by choosing one behaviour and composing it.

This is the delivery change of the roadmap goal that sells compute by the period until
either party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)),
split from [`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/) on
the goal's fourth review round so that every compute commit caller is rewired once —
for activation, for the window, and for the authorization hook — before the
continuation that uses the hook is built.

## What Changes

- One **compute-family delivery path** both domains compose — commit, dispatch,
  disclosure, activation, and the undelivered path — in place of VM's and bare metal's
  separate code; each domain keeps only its provider-specific preparation and its
  access surface.
- **The window from the Agreement** in both domains: `lease_start_utc = start_utc`,
  `lease_end_utc = start_utc + duration_seconds`, committed against that absolute end
  and recommitted unchanged on resume or retry; bare metal's commit from `now` is
  retired, and VM's two resume-time substitutions of an hour go with it. When
  settlement completes so late that no window remains, the path refuses delivery and
  takes the undelivered path.
- **Every compute commit caller becomes an activation caller**: after delivery the
  path activates the lease at the site through the one call
  `renewable-compute-lease-deadlines` adds — a reserved deal to its agreed end, a
  per-period deal to the horizon the mechanism names — and the site stamps the active
  instant.
- A **delivery authorization hook**, `authorize_delivery(deal, phase)` for the phases
  `commit`, `dispatch`, `start`, and `disclose`, called before each transition and
  recording its decision durably before answering. The path supplies the hook's
  interface and a default that answers yes at once with nothing to do, which is what
  every prepaid deal gets; the per-period implementation is
  `converge-ongoing-compute-leases`'.
- A persistent **delivery state machine** — `authorized`, `dispatched`, `started`,
  `activated`, `available`, `active` — each step written before the effect it
  precedes, with a recovery obligation per boundary and a crash injected between
  each adjacent pair as the acceptance test; `started` is the hook's step, trivial for
  a prepaid deal.
- The **undelivered path**, committed behaviour rather than a configurable failure
  action: a deal the site reclaims before activation — its `lease_ended` with cause
  `renewal_lapsed` in the awaiting-activation phase — or that the hook refuses is
  ended with nothing to tear down where nothing was dispatched, else terminated; a
  prepaid deal is refunded in full through the existing seller-initiated reverse; a
  per-period deal is handed to its hook to stop and return the reserved batch.
- The **credential read enforces the recorded delivery state and decision** on every
  read, never a live snapshot, serialized with local termination by the decision
  row's compare-and-set — the first of the four access guarantees, the one that is
  absolute and local.
- Both lanes prove a reserved deal activated and running past the pool's allowance,
  a crash before activation expiring at it with the buyer refunded, delayed
  settlement against an absolute bound in both domains, the crash matrix across the
  state machine, and an API-credit purchase unchanged.

## Capabilities

### Modified Capabilities

Expected: `fulfillment` (the path and its state machine), `vm-storefront-fulfillment`,
`physical-provisioning` (activation as a caller obligation), `settlement-servicing`
(the hook's interface and the undelivered path's refund). `.openspec.yaml` sets
`skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- The hook's per-period implementation, the continuation, the journal, and the
  horizon: `converge-ongoing-compute-leases`.
- The site's deadline, activation, and lapse policy: `renewable-compute-lease-deadlines`.
- The rest of the fulfillment unification `kit-owned-listing-and-fulfillment-lifecycles`
  proposes; this takes the protected transitions, activation, and the access rule and
  leaves it the rest.

## Dependencies and Related Changes

- Depends on `buyer-initiated-compute-termination` (the request log the undelivered
  path and the credential read serialize against; the `lease_ended` event) and
  `renewable-compute-lease-deadlines` (the activation transition and the
  `renewal_lapsed` cause with its phase).
- `converge-ongoing-compute-leases` depends on it and supplies the hook's per-period
  implementation.
- Takes the narrow part of `kit-owned-listing-and-fulfillment-lifecycles`' unified
  path and leaves it the rest; that change's design records the hand-off.
- `resolve-compute-family-findings` touches the same VM resume and admission paths;
  this change is designed against its tree.

## Impact

A compute-family delivery path (its home decided in design: the family kit, or
`kit/fulfillment` if it proves family-neutral) that both compute storefronts compose
in place of their own commit, dispatch, disclosure, and activation code; both
storefronts' payment coordinators and fulfillment services; the credential read
routes; the compute deal stages in both lanes.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Fulfillment" and "Release"
- [x] Existing subsystem specification: `fulfillment`, `vm-storefront-fulfillment`,
  `physical-provisioning`, `settlement-servicing`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- One delivery path for the compute family, its window from the Agreement, its state
  machine and the recovery obligation per boundary — `fulfillment` spec and
  architecture companion; `ARCHITECTURE.md`, "Fulfillment".
- Every compute lease is activated after delivery by the path, once — `fulfillment`
  and `physical-provisioning` specs.
- The undelivered path is committed behaviour; a prepaid deal the site reclaims
  before delivery is refunded in full — `settlement-servicing` spec.
- No disclosure after a locally committed end — `fulfillment` spec;
  `ARCHITECTURE.md`, "Deciding which party is authoritative".
