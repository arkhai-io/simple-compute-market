# Design

The decisions below were settled with the owner in the goal-level design of
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)
on 2026-10-28, across the goal's five changes. This change's own design session
verifies them against the code as its three dependencies left it and adds the spec
deltas; it does not reopen them without a finding.

## Context

Verified against the tree on 2026-10-28; re-verify before planning, since all three
dependencies change it.

- `CapacityReservation` (`kit/site/src/market_site/db.py`) carries nullable
  `lease_start_utc` and `lease_end_utc`, `hold_expires_at`, `release_job_id`,
  `release_requested_at`. `commit` records the window; `truncate_lease` moves the end
  earlier from `leased` only; `list_lease_due` selects `leased` rows whose end has
  passed; `_windows_overlap` and `_held_dimensions` read the window for admission.
  The spec says that once committed, truncation is the only operation that moves a
  lease's end (`site-capacity`, "Lease truncation neither resurrects nor extends a
  lease"), and every lease write is a conditional transition.
- `LeaseWatchdog` (compute provisioning service) ticks every
  `lease_watchdog_poll_interval_seconds` (60) and calls `check_leases`, whose cycle
  drains the capacity-release outbox, releases what `list_time_bounded_reservations_due`
  returns, and processes `releasing` reservations. Pool policy tags today are
  `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`,
  `pricing`, `listing_shapes`, `asking_rates`, and the deliverable and advertisable
  declarations.
- VM's `VmPaymentsCoordinator.start` verifies the receipt, deposits, inserts the
  delivery, spawns `_provision`, which sets `ready` or `failed` and does nothing
  after; `list_unsettled_payment_negotiations` skips deals with a delivery record;
  `delivery_facts` records `lease_end_utc = start + duration` and
  `funding_expiration_unix = mandate.expires`. Bare metal's `settle_payment` starts
  delivery once; `reconcile_payments_once` converges `accepted`, `refunding`, and
  verified-without-lifecycle deals. Neither re-reads the transaction after delivery.
  Each storefront runs its own reconciliation timer on the kit loop controller.
- Refund is seller-initiated `reverse`, ordered against delivery start by
  compare-and-set in each domain's tables; nothing issues `start` or `stop`.
- The buyer's settle paths (`domains/vms/buyer/.../arkhai_payments.py`, bare metal's
  `PaymentStage.settle`) approve, poll, then call the storefront; the run log records
  `payment_approved` with the transaction ID. No buyer-side stop exists.
- The storefront operator CLIs read the storefront's configuration and database
  directly for `config` and `settlement status`; no command issues a payment event.

## Goals / Non-Goals

**Goals:** a running per-period deal is served exactly while it is funded and wanted,
with a fail-safe on each side that needs no cooperation from the other; both compute
domains get it through one implementation.

**Non-Goals:** seller preemption; pooled funding; the liability ledger; push
delivery; lease extension.

## Decisions

### D1. The funded horizon is a renewal deadline at the site, beside the agreed end

The reservation gains a nullable `renew_by_utc`. `lease_end_utc` keeps meaning the
agreed end, recorded at commit and moved only by truncation. A lease whose
`renew_by_utc` passes unrenewed expires early, exactly as it expires at its end: the
watchdog's due query reads the earlier of the two. Renewal is a new conditional
transition: only from `leased`, only to a later instant, never past `lease_end_utc`;
truncating the end truncates the deadline with it. The spec's "truncation is the only
operation that moves a committed end" stays true of the end; the deadline is the one
thing renewal moves. A prepaid deal records no deadline and behaves exactly as today.
Admission's overlap check reads the agreed end, not the deadline, since the capacity
is committed through the end even while the funded horizon sits earlier — otherwise a
forward reservation could be admitted into a window the running deal then renews into.

The site is told when the lease must be renewed by, never why: nothing commercial
crosses the boundary, and the field is a lease concept.

*Rejected:* committing the lease open-ended (null end) and having the storefront
truncate when funding lapses — a dead storefront then serves unfunded time to the
seller's bound. *Rejected:* a rolling finite end the storefront extends — it needs a
lease-extension operation and makes the agreed end a projection of a payment fact.
*Rejected:* a separate "cap" field over a movable end — the same model with a worse
name; the agreed end already is the cap.

### D2. What an unrenewed lease does is the site's policy

A pool policy tag with a site-wide default, read by the watchdog when a lease's
`renew_by_utc` has passed unrenewed: `reclaim` (expire at the deadline; the default
and today's expiry), `grace` with a duration (expire that much later), or `continue`
(run to the agreed end; the site holds the storefront accountable outside the
codebase). The site need know nothing about payments to apply any of the three.

What makes this correct is the division of labour: the storefront renews only on
*verified* funding and *terminates* on a verified end (a stop event, exhaustion), so
a lapse the site sees is only ever the unverifiable case — the payments service
unreachable, or the storefront itself down. Under `continue` an exhausted buyer is
still cut off, because exhaustion is verified and terminated by the storefront.

*Rejected:* a storefront-side grace on renewal. The outage posture is the site
operator's risk appetite about their hardware, and the site is where every lease's
expiry already runs.

### D3. One continuation in the mechanism kit, composed by each compute domain

A per-period deal's continuation lives in `kit/arkhai-payments`' seller stage and
runs as a storefront lifecycle loop on the kit loop controller, so the end-to-end
stages can hold and step it. Each compute domain contributes its delivery predicate
(when the fulfillment is delivered and credentials are retrievable), its lease handle
(reservation and site), and its teardown hook (terminate at the site), and nothing
else; the kit owns the snapshot reads, the renewals, the stops, and the restart
recomputation. Per cycle, for each delivered per-period deal:

1. If no `start` is in the snapshot's events and delivery is verified, issue `start`.
2. Verify the snapshot. If it carries a `stop`, or its `fundedThrough` is not ahead of
   now, record the cause (`buyer_cancel`, `funding_ended`, `site_withdrawal` as the
   stop's cause and the intent already recorded say) and terminate the lease at
   once through the terminate route.
3. Otherwise renew the lease to `fundedThrough`, capped by the agreed end.

A snapshot that cannot be fetched or verified renews nothing and terminates nothing;
the site's lapse policy decides. On restart the loop recomputes every deal's state
from its snapshot and its stop intent, issuing nothing already in the events. Its
polling cadence plus the domain's teardown time must fit inside the option's
`reserve_ahead`; the storefront refuses to publish a per-period option whose
`reserve_ahead` is shorter than that floor.

### D4. Billing begins at verified delivery, through the `start` event

The storefront issues `start` when delivery is verified — the same fact that gates
the buyer's access — and that begins the first period; a prepaid deal issues no
`start`. A buyer who issues `start` earlier pays for provisioning time by its own
choice, and the continuation takes whichever `start` the event sequence shows first.
The lease's initial `renew_by_utc` is commit plus `reserve_ahead`, so a storefront
that dies before issuing `start` still leaves a lease that expires; the first verified
snapshot after `start` moves it to the funded horizon. An approved per-period deal
whose delivery failed is stopped and reversed by the reconciliation pass, since no
period started and its reserved batch is returnable.

### D5. Stopping payment first is always safe for the buyer; reclaiming first for the seller

Each party holds one lever it can pull without anyone's cooperation, and the
storefront reconciles whichever came first:

- The **buyer's** cancel stops the transaction at the payments service first — the
  mandate names the payer as a stop authority — then calls the end-deal route for
  prompt teardown. The payer stop is authoritative the moment the service records
  it; a buyer who never calls the storefront is still not paying, and the
  continuation terminates the lease when it next sees the stop.
- The **site** reports its intent to reclaim the moment it forms it, to the
  storefront only (it knows no mechanism and holds no credential), through the
  outbox. The storefront issues the payee stop at the reported instant, backdated
  where the service permits.
- The **seller** ends billing through the storefront, which also terminates the
  lease; if the storefront is unreachable, through the operator stop command (D6),
  which stops charging without stopping service and so harms nobody but the seller.

A storefront that keeps billing after the site reclaimed, or never backdates, is
answered by the buyer's own stop and a dispute against the payments service's event
record and the signed site reports an honest storefront retains. A site that is a
separate business from the storefront is the seller's responsibility to the buyer, as
a subcontractor is; the Agreement binds the seller principal.

### D6. The seller's stop lever works with the storefront process down

An operator command (`market-storefront settlement stop <negotiation>`, name to be
settled) reads the mandate and transaction ID from the storefront's stored
`settlement_data` and issues the payee stop with the operator's credential, without
the running process. It records the stop intent if it can, and the continuation
reconciles on return if it cannot. The site's report is likewise durable in the
outbox while the storefront is down.

### D7. The lease's end ends the billing

On every lease-ended report — the site's expiry at the agreed end, expiry at an
unrenewed deadline, termination, force-release — the storefront issues the payee stop
at the reported effective instant unless a stop is already in the events. Today
nothing reacts financially to expiry because a prepaid hold needs nothing; a
per-period deal that reached the seller's bound would otherwise bill until the buyer
noticed.

## Accepted gaps (recorded in the goal as unowned)

- **Pooled funding.** One balance behind N leases: the payments service owns reporting
  a per-transaction funded horizon from a shared balance; the site would need a lease
  pool, one renewal deadline many reservations share, renewed once, so a top-up does
  not renew N leases. Neither exists.
- **Storefront–site liability.** What the storefront owes the site, with penalties for
  failing to relay a stop; the `continue` lapse policy is where it attaches. The
  leverage runs the other way today — the storefront holds the site's money — which is
  why nothing enforces it, and why it must once the two separate.
- **Backdated payee stops** depend on the service exposing an effective time on
  `EventCommand`, confirmed by `settle-ongoing-compute-through-arkhai-payments`.

## Open questions

- Whether the renewal deadline's due query joins the index
  `capacity-reservation-lifecycle-hardening` adds to the expiry scan, or that change
  lands first; settled in design by which is further along.
- The continuation's default cadence and the `reserve_ahead` floor each domain
  passes the kit; settled in design from each domain's measured teardown time in the
  mock profile and a stated margin for the real one.

## Implementation cadence (recommended)

Three rounds. Round 1: the site — `renew_by_utc`, the renew transition, the lapse
policy tag, the watchdog's due query and report causes, the overlap rule, with the
site's integration tests. Round 2: the kit continuation and both domains' hooks, the
payee stop at a lease's end, the reconciliation of undelivered deals, the operator stop
command. Round 3: the buyer's payer-stop-first cancel and the end-to-end scenarios in
both lanes. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/site-capacity/spec.md` and architecture companion; `ARCHITECTURE.md`, "Capacity reservation" |
| D2 | `site-capacity` spec; `physical-provisioning` spec; `ARCHITECTURE.md`, "Recovery workers"; `DEPLOYMENT_AND_CONFIG.md` pool hints |
| D3 | `settlement-servicing` spec and architecture companion; `market-composition` spec (the loop) |
| D4 | `settlement-servicing` spec |
| D5 | `ARCHITECTURE.md`, "Deciding which party is authoritative"; `settlement-servicing` architecture companion |
| D6 | `settlement-servicing` spec; the storefront operator CLI reference |
| D7 | `settlement-servicing` spec; `physical-provisioning` spec |
