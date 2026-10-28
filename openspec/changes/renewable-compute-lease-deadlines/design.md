# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against three independent design reviews of the goal, one of
which proposed this split. This change's own design review may reopen any of them
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

**Goals:** a per-period lease has a deadline the site enforces alone; renewal and
expiry cannot race into a wrong release; what an unrenewed lease does is the site
operator's policy; provisioning has its own time and is not billable.

**Non-Goals:** deciding whether to renew; lease extension; a shared deadline across
reservations.

## Decisions

### D1. The funded horizon is a renewal deadline beside the agreed end

The reservation gains a nullable `renew_by_utc`. `lease_end_utc` keeps meaning the
agreed end, recorded at commit and moved only by truncation. A lease whose deadline
passes unrenewed expires early, exactly as it expires at its end; the due query reads
the earlier of the two. Renewal is a new conditional transition: only from `leased`,
only to a later instant, never past `lease_end_utc`; refused from `releasing`, so a
stale caller cannot resurrect a claimed lease. Truncating the end truncates the
deadline with it. A prepaid deal records no deadline and behaves exactly as today.
Admission's overlap check reads the agreed end, not the deadline, since the capacity
is committed through the end even while the horizon sits earlier.

The site is told when the lease must be renewed by, never why. The field is a lease
concept, and nothing commercial crosses the boundary.

*Rejected:* committing the lease open-ended (null end) with the storefront truncating
when funding lapses — a dead storefront then serves unfunded time to the seller's
bound. *Rejected:* a rolling finite end the storefront extends — it needs a lease
extension and makes the agreed end a projection of a payment fact. *Rejected:* a
separate cap field over a movable end — the same model with a worse name.

### D2. Expiry claims against the deadline it read

`list_lease_due` returns each due row with the deadline that made it due, and the
release transition is conditioned on `state == leased AND <that deadline field> ==
<the value read>` — a compare-and-set inside the ledger's serialized section, as
every lease write already is. A renewal that moved the deadline between the read and
the claim makes the claim fail; nothing is written; the next cycle re-evaluates. A
deadline that has elapsed but is not yet claimed may still be renewed: verified
funding is verified funding, and refusing it would evict a funded buyer over watchdog
latency. The rule is written as a requirement: *the deadline is enforced by the
claim, not by the clock.*

*Rejected:* locking the row across the cycle — the lifecycle deliberately makes
provider calls outside any transaction. *Rejected:* refusing renewal after the
deadline — it turns the poll interval into a buyer-facing timeout. Revisit trigger: a
deployment running two watchdog instances, which would need a worker identity and a
row lease as the fulfillment convergence passes use.

### D3. The initial deadline is the pool's provisioning budget

A Resource Pool policy tag, `provisioning_budget_seconds`, with a site-wide default,
read by the site itself at commit: a per-period commit records `renew_by_utc = commit
+ budget`. The storefront passes nothing and knows nothing of it; its first verified
snapshot after `start` is what moves the deadline onto the funded horizon
(`converge-ongoing-compute-leases`). A provision that overruns the budget expires as
an unfunded lease would, which is the operator's promise of delivery time being
enforced. Provisioning time is non-billable by construction, since the storefront
issues `start` only at verified delivery, and is accounted apart: the lease view
exposes the active instant the site already records, so provisioning time is that
instant less the commit.

Which deal is per-period the site learns from the commit — a flag the storefront
passes, as it passes the lease window — not from any commercial term.

*Rejected:* a storefront term for the budget — the site knows its pools' hardware.
*Rejected:* reusing `max_reservation_hold_seconds` or `hold_ttl_seconds` — they
bound an uncommitted hold under Goal 5's posture, not a leased one. *Rejected:* no
deadline until `start` — the fail-safe would be absent for the window that needs it.
Revisit trigger: `billable-capacity-reservations` landing, when the provisioning
window becomes a candidate for the same pricing machinery; noted there.

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
lapsed and the policy that applied. The lease view exposes `renew_by_utc`, the active
instant, and the lapse policy.

## Open questions

- Whether the deadline's due query joins the index
  `capacity-reservation-lifecycle-hardening` adds for hold expiry, or that change
  lands first; settled in design by which is further along.
- Whether a `grace` bound is site-wide (a maximum any pool may state) or only per
  pool; settled in design.

## Implementation cadence (recommended)

One round: the column and migration, the renew transition, the claim rule, the two
policy tags and their reads, the due query, the event cause, the view, and the site's
integration suite with its two-session races. One session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2 | `openspec/specs/site-capacity/spec.md` and architecture companion; `ARCHITECTURE.md`, "Capacity reservation" |
| D3 | `resource-pool-management` spec; `physical-provisioning` spec; `DEPLOYMENT_AND_CONFIG.md` pool hints |
| D4 | `site-capacity` spec; `physical-provisioning` spec; `ARCHITECTURE.md`, "Recovery workers"; `DEPLOYMENT_AND_CONFIG.md` |
| D5 | `physical-provisioning` spec; `compute-provisioning-contract` spec |
