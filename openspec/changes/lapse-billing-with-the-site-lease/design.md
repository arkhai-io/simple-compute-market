# Design

These decisions were settled with the owner on 2026-10-28 as part of Goal 8's
design and set aside from that goal on 2026-10-29 when its guarantees were moved onto
the authorities alone; they are kept here as one change so the two halves land
together. This change's own design review may reopen any of them with a finding;
its design session verifies them against the tree as `renewable-compute-lease-deadlines`
and `converge-ongoing-compute-leases` leave it and adds the spec deltas.

## Context

To be verified when the change is designed.

- `renewable-compute-lease-deadlines` gives every compute lease a delivery deadline, on the activation phase `activate-compute-leases-at-the-site` adds,
  at commit, recorded in `renew_by_utc` with phase `awaiting_activation`, replaced
  once at activation; it records renewal and the lapse policy as deferred options.
- The rate servicing loop (`converge-ongoing-compute-leases`) runs physical work and
  bounded authority work per deal each cycle and keeps a renewable funding timer; it
  neither renews the site's lease nor bounds billing.
- A rate part's earnings are held until its stop plus the dispute window; a stop
  takes effect at receipt and is never backdated; the payment authority stops a part
  itself on exhaustion and at its absolute end (`agreed-evidence-and-early-termination`
  D5).

## Goals / Non-Goals

**Goals:** a dead storefront's billing and lease lapse at the same instant, within
one cycle, with no action by anyone; the buyer's worst case for an end the storefront
did not observe is the option's reserve-ahead; a site operator bounds its exposure
to an absent storefront by a policy of its own.

**Non-Goals:** any change to what the buyer may do at the authorities; deciding
whether to renew.

## Decisions

### D1. A billing horizon the payee advances

A rate part carries a `vouchedThrough` instant that only the payee advances, with a
`vouch {part, through}` event: monotonic, never past the transaction's
`fundedThrough`, refused on a stopped part. A period may begin only while the
current instant is before `vouchedThrough`; when the instant passes it unadvanced,
the payment authority stops the part with cause `terms`, settled to that instant
under the part's end treatment. `vouch` is not journaled per cycle: it is idempotent
and monotonic, and the loop records the last instant it vouched in the deal's
continuation state before the call.

The storefront advances the horizon each cycle to the earliest of now plus the
option's `reserve_ahead_seconds`, `fundedThrough`, and the agreed end, and renews the
site's lease to the same instant in the same cycle (D2), so billing and the physical
lease lapse together whatever happens to the storefront. Nothing accrues that the
storefront did not vouch for while alive. A misbehaving seller can advance the
horizon whatever it delivers; the horizon bounds the honest crash, and the buyer's
own stop and case remain its protection against dishonesty.

This is the one capability this change asks of the payments service: the field, the
payee-only event, the lapse stop, and a vector of a running rate part vouched,
lapsed, and stopped by the service. The first question for the service's
maintainers is whether a lapsed payee-supplied horizon can stop a part without a
payee-issued event under its billing model.

*Rejected:* a storefront-scheduled stop at the horizon — it dies with the storefront.

### D2. A renewable deadline on an active lease

After activation the reservation's `renew_by_utc` enters phase `active` and becomes
a renewal deadline: renewal is a conditional transition from `leased` that moves it
later only, never past `lease_end_utc`, and is refused from `releasing`, so a stale
caller can neither resurrect a claimed lease nor shorten a funded one. Truncating the
end truncates the deadline with it. Admission's overlap check reads the agreed end,
not the deadline, since the capacity is committed through the end even while the
horizon sits earlier. The due query reads the earlier of deadline and end; the
release transition is conditioned on the deadline and phase the query read, as
`renewable-compute-lease-deadlines` D2 conditions activation expiry, so an elapsed
but unclaimed deadline may still be renewed: the deadline is enforced by the claim,
not by the clock.

The site is told when the lease must be renewed by, never why; the field is a lease
concept, and nothing commercial crosses the boundary.

*Rejected:* committing the lease open-ended with the storefront truncating when
funding lapses — a dead storefront then serves unfunded time to the seller's bound.
*Rejected:* a rolling finite end the storefront extends — a lease extension, and an
agreed end that is a projection of a payment fact.

### D3. What an unrenewed lease does is the site's policy

A pool policy tag, `renewal_lapse`, with a site-wide default, read by the watchdog
through the pool port when a deadline has passed unrenewed:

- `reclaim` — expire at the deadline; the default, and today's expiry;
- `grace` with a duration — expire that much later, bounded by a site-wide maximum,
  reported in the lease view and diagnostics;
- `continue` — run to the agreed end; operator-accepted risk, under which an
  exhausted buyer may run on while the storefront is unreachable, since only the
  storefront can verify exhaustion.

The site need know nothing about payments to apply any of the three. The storefront
renews only on verified funding and terminates on a verified end, so a lapse the
site sees is only ever the unverifiable case — the payment authority unreachable,
or the storefront itself down — and under D1 billing has lapsed at the same instant.
The `lease_ended` event gains cause `renewal_lapsed`, carrying the deadline, its
phase and the policy that applied; the lease view exposes the deadline, the phase
and the policy.

*Rejected:* a storefront-side grace — the outage posture is the site operator's
risk appetite about its hardware, and the site is where expiry already runs.

### D4. The vouch-and-renew step

In the rate servicing loop's authority work, for an active deal with a verified
snapshot: vouch, then renew, to the one instant of D1, each instant recorded before
its call; a snapshot that cannot be fetched or verified vouches and renews nothing,
and the site's lapse policy decides what follows. Re-anchoring across an identity
rotation vouches under the new key from the first snapshot it verifies.

## Open questions

- Whether the renewal deadline's due query joins the index
  `capacity-reservation-lifecycle-hardening` adds for hold expiry; settled in design.
- Whether a `grace` maximum is site-wide only or also per pool; settled in design.

## Implementation cadence (recommended)

Two rounds. Round 1: the site — the renew transition, the claim rule, the lapse
policy tag and its read, the event cause, the view, and the site's two-session races.
Round 2: the kit's `vouch` against the double's extension and the loop's step, with
the lane scenarios: a storefront paused mid-deal whose billing and lease lapse
together; a site withdrawal while the storefront is paused, with the charge bounded
by reserve-ahead; a deadline lapsing under each policy.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D4 | `openspec/specs/settlement-servicing/spec.md` and architecture companion; `deal-lifecycle` spec |
| D2, D3 | `openspec/specs/site-capacity/spec.md` and architecture companion; `physical-provisioning` spec; `resource-pool-management` spec; `ARCHITECTURE.md`, "Capacity reservation" and "Recovery workers"; `DEPLOYMENT_AND_CONFIG.md` |
