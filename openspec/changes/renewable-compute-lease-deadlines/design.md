# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
revised the same day against three independent design reviews of the goal, one of
which proposed this split, and again against a second review of the revision. This change's own design review may reopen any of them
with a finding; its design session verifies them against the code and adds the spec
deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- `CapacityReservation` (`kit/site/src/market_site/db.py`) carries nullable
  `lease_start_utc` and `lease_end_utc`, `hold_expires_at`, `release_job_id`,
  `release_requested_at`. `commit` records the window; `truncate_lease` moves the end
  earlier from `leased` only; `list_lease_due(now)` selects `leased` rows with a
  non-null end that has passed, then the lifecycle's `_request_release` begins
  `releasing` as a transition conditioned on `state == leased`; `_windows_overlap`
  and `_held_dimensions` read the window for admission. The spec says every lease
  write is a conditional transition and that, once committed, truncation is the only
  operation that moves a lease's end (`site-capacity`).
- `LeaseWatchdog` ticks every `lease_watchdog_poll_interval_seconds` (60) and calls
  `check_leases`, whose cycle drains the release outbox, releases what
  `list_time_bounded_reservations_due` returns, and processes `releasing` rows,
  performing provider calls outside any transaction. The chart runs one instance.
- Pool policy tags are `listing_cardinality_mode`, `max_reservation_hold_seconds`,
  `region`, `sla`, `pricing`, `listing_shapes`, `asking_rates`, and the deliverable
  and advertisable declarations; `max_reservation_hold_seconds` is the precedent for
  a site-side duration policy the ledger reads.
- The site records a lease's executor target when the fulfillment becomes active
  (`site-capacity`, "A reservation's lease tail is written once"), so the delivery
  instant is already a site fact.
- API credits commits with `lease_end_utc=None` for quota holds; this change does
  not touch that path.

## Goals / Non-Goals

**Goals:** every lease has a deadline the site enforces alone, armed at commit and
kept alive by the storefront; renewal and expiry cannot race into a wrong release;
what an unrenewed lease does is the site operator's policy; provisioning has its own
time and is not billable; the site classifies no lease.

**Non-Goals:** deciding whether to renew; lease extension; a shared deadline across
reservations.

## Decisions

### D1. A renewal deadline beside the agreed end, in two phases

The reservation gains a nullable `renew_by_utc` and a `renewal_phase`. `lease_end_utc`
keeps meaning the agreed end, recorded at commit and moved only by truncation. A lease
whose deadline passes unrenewed expires early, exactly as it expires at its end; the
due query reads the earlier of the two. Truncating the end truncates the deadline
with it. Admission's overlap check reads the agreed end, not the deadline, since the
capacity is committed through the end even while the horizon sits earlier.

The deadline has two phases, because it bounds two different things:

- **`provisioning`**, set at commit (D3): the deadline bounds delivery. The first
  renewal after delivery — *activation* — is one conditional transition, `leased AND
  renewal_phase == provisioning`, that *replaces* the deadline with the instant the
  storefront names, earlier or later, capped by the end, and flips the phase. A
  reserved deal activates to its agreed end, the horizon it fully funded; a
  per-period deal to its verified funded horizon.
- **`active`**: renewal is monotonic — only from `leased`, only to a later instant,
  never past `lease_end_utc`, refused from `releasing`, so a stale caller can neither
  resurrect a claimed lease nor shorten a funded one.

A lease committed before this change has a null deadline and no phase, and behaves
exactly as today: null means unarmed, not reserved. The site is told when the lease
must be renewed by, never why; the field is a lease concept, and nothing commercial
crosses the boundary.

*Rejected:* one monotonic deadline from commit — a two-hour provisioning budget would
then refuse a funded horizon twenty minutes out and authorize the lease to the budget
unfunded. *Rejected:* letting any renewal move the deadline earlier — a replayed old
horizon could then shorten a funded lease.

*Rejected:* committing the lease open-ended (null end) with the storefront truncating
when funding lapses — a dead storefront then serves unfunded time to the seller's
bound. *Rejected:* a rolling finite end the storefront extends — it needs a lease
extension and makes the agreed end a projection of a payment fact. *Rejected:* a
separate cap field over a movable end — the same model with a worse name.

### D2. Expiry claims against the deadline and phase it read

`list_lease_due` returns each due row with the deadline and phase that made it due,
and the release transition is conditioned on `state == leased AND <that deadline
field> == <the value read> AND renewal_phase == <the phase read>` — a compare-and-set
inside the ledger's serialized section, as every lease write already is. A renewal or
activation that moved the deadline between the read and the claim makes the claim
fail; nothing is written; the next cycle re-evaluates. A deadline that has elapsed but
is not yet claimed may still be renewed or activated: verified funding is verified
funding, and refusing it would evict a funded buyer over watchdog latency. The rule is
written as a requirement: *the deadline is enforced by the claim, not by the clock.*

*Rejected:* locking the row across the cycle — the lifecycle deliberately makes
provider calls outside any transaction. *Rejected:* refusing renewal after the
deadline — it turns the poll interval into a buyer-facing timeout. Revisit trigger: a
deployment running two watchdog instances, which would need a worker identity and a
row lease as the fulfillment convergence passes use.

### D3. Every commit arms the pool's provisioning budget; the site classifies nothing

A Resource Pool policy tag, `provisioning_budget_seconds`, with a site-wide default,
read by the site itself at commit: *every* commit records `renew_by_utc = commit +
budget` in phase `provisioning`. The storefront passes nothing and the site learns
nothing about how the deal is billed: a deadline is a deadline, whoever set it and
whyever. After delivery the storefront activates every lease through the same call —
a reserved deal to its agreed end, a per-period deal to its funded horizon
(`converge-ongoing-compute-leases`) — and a reserved deal never calls again. A
provision that overruns the budget expires as an unfunded lease would, which is the
operator's promise of delivery time being enforced, and a reserved deal whose
storefront dies between commit and delivery now expires too, instead of holding
capacity to its agreed end. Provisioning time is non-billable by construction, since
the storefront issues `start` only at verified delivery, and is accounted apart: the
site stamps the active instant it already records at activation, so provisioning
time is that instant less the commit.

*Rejected:* a `requires_renewal` flag on the commit — correct behaviour, but a bit
whose only meaning is "the storefront will call back", and two lease behaviours where
one will do. *Rejected:* a per-period flag — a commercial classification at the site.
*Rejected:* a storefront term for the budget — the site knows its pools' hardware.
*Rejected:* reusing `max_reservation_hold_seconds` or `hold_ttl_seconds` — they
bound an uncommitted hold under Goal 5's posture, not a leased one. *Rejected:* no
deadline until `start` — the fail-safe would be absent for the window that needs it.
Revisit trigger: `billable-capacity-reservations` landing, when the provisioning
window becomes a candidate for the same pricing machinery; noted there. A second
trigger: a domain path found to commit leases it never revisits after delivery, which
would argue for arming per lease.

### D4. What an unrenewed lease does is the site's policy

A pool policy tag, `renewal_lapse`, with a site-wide default, read by the watchdog
when a deadline has passed unrenewed:

- `reclaim` — expire at the deadline; the default, and today's expiry;
- `grace` with a duration — expire that much later; bounded, and reported in the
  lease view and diagnostics so the exposure is visible;
- `continue` — run to the agreed end; operator-accepted credit risk, under which an
  exhausted buyer may run on while the storefront is unreachable, since only the
  storefront can verify exhaustion.

The site need know nothing about payments to apply any of the three. What makes this
correct is the division of labour: the storefront renews only on *verified* funding
and *terminates* on a verified end, so a lapse the site sees is only ever the
unverifiable case — the payments service unreachable, or the storefront itself down.
The guarantee the goal states — a deal is served exactly while it is funded and
wanted — holds under `reclaim`; `grace` extends it by a bounded operator choice, and
`continue` suspends it by an explicit one.

*Rejected:* a storefront-side grace — the outage posture is the site operator's risk
appetite about their hardware, and the site is where expiry already runs.
*Rejected:* codifying one answer.

### D5. The event and the view

The `lease_ended` event gains cause `renewal_lapsed`, carrying the deadline that
lapsed, its phase, and the policy that applied. The lease view exposes
`renew_by_utc`, `renewal_phase`, the active instant, and the lapse policy.

## Open questions

- Whether the deadline's due query joins the index
  `capacity-reservation-lifecycle-hardening` adds for hold expiry, or that change
  lands first; settled in design by which is further along.
- Whether a `grace` bound is site-wide (a maximum any pool may state) or only per
  pool; settled in design.

## Implementation cadence (recommended)

One round: the two columns and migration, the activation and renew transitions, the
claim rule, the two policy tags and their reads, the due query, the event cause, the
view, and the site's integration suite with its two-session races — activation
against expiry, renewal against expiry, a replayed earlier horizon refused in
`active`. One session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2 | `openspec/specs/site-capacity/spec.md` and architecture companion; `ARCHITECTURE.md`, "Capacity reservation" |
| D3 | `resource-pool-management` spec; `physical-provisioning` spec; `DEPLOYMENT_AND_CONFIG.md` pool hints |
| D4 | `site-capacity` spec; `physical-provisioning` spec; `ARCHITECTURE.md`, "Recovery workers"; `DEPLOYMENT_AND_CONFIG.md` |
| D5 | `physical-provisioning` spec; `compute-provisioning-contract` spec |
