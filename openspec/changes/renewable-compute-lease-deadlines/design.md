# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against four rounds of independent design review of the
goal, the first of which proposed this split and the fourth of which moved its
activation callers into `unify-compute-delivery-path`. This change's own design review may reopen any of them
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
- `resolve-compute-family-findings` D5 removes `ReservationState.provisioning` and
  `provisioning_failed`, which nothing writes, under a migration that converts any
  stored row; the word leaves the site's state vocabulary, and this change's phase
  value must not bring it back.
- `inject-site-pool-authority` (in design) settles the port through which the site
  ledger reads pool facts; the index rules that it should land before any new site
  read of pool state, and this change adds two.

## Goals / Non-Goals

**Goals:** every compute lease has a deadline the site enforces alone, recorded at
commit and kept alive by the storefront; renewal and expiry cannot race into a wrong
release; what an unrenewed lease does is the site operator's policy; provisioning has
its own time and is not billable; the site classifies no lease.

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

- **`awaiting_activation`**, set at commit (D3): the **activation deadline**, which
  bounds delivery. The first renewal after delivery — *activation* — is one
  conditional transition, `leased AND renewal_phase == awaiting_activation`, that *replaces*
  the deadline with the instant the storefront names, earlier or later, capped by
  the end, and flips the phase. A reserved deal activates to its agreed end, the
  horizon it fully funded; a per-period deal to its verified funded horizon.
  Activation is idempotent: in `active` with the same or an earlier instant it
  returns the lease unchanged, so a lost acknowledgement is retried safely, and a
  later instant is a renewal.
- **`active`**: renewal is monotonic — only from `leased`, only to a later instant,
  never past `lease_end_utc`, refused from `releasing`, so a stale caller can neither
  resurrect a claimed lease nor shorten a funded one.

A lease committed before this change has a null deadline and no phase, and behaves
exactly as today: null means no deadline, not reserved. The phase is named for the
transition that ends it, the site's own word for what happens; `provisioning` was
rejected because `resolve-compute-family-findings` is migrating that word out of
the same table as a legacy state, and the next reader of the literal could not
tell which concept it named. The site is told when the lease
must be renewed by, never why; the field is a lease concept, and nothing commercial
crosses the boundary.

*Rejected:* one monotonic deadline from commit — a two-hour provisioning allowance would
then refuse a funded horizon twenty minutes out and authorize the lease to the allowance
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

### D3. Commit records an activation deadline from the pool's provisioning allowance

Vocabulary: a **commit** is the existing site operation that turns a reserved hold
into a lease once settlement is verified; the **provisioning allowance**,
`provisioning_allowance_seconds`, is a Resource Pool policy tag stating the time the
pool's operator allows between a lease beginning and the resource becoming available
— time, not money, and distinct from the minimum spend, which prices a buyer's
repeated behaviour; the **activation deadline** is the lease's `renew_by_utc` in
its `awaiting_activation` phase. The allowance's purpose is to bound the site's exposure to
a storefront that goes silent between commit and delivery, and to enforce the
operator's own delivery time against a storefront that is alive and failing to
deliver; it is not a buyer-facing promise, which would be a listing term the
storefront resolves and publishes, and none is proposed.

Who states it follows the host requirement's precedent: each *provider* declares
whether its pools carry a provisioning allowance and supplies the provider's default,
as plain data the provisioning composition passes — `vm.ansible` and
`bare_metal.ansible` do, with defaults that differ because their provisioning does;
the API-credits composition's provider declares none. A pool of a provider that
declares it may state its own value, validated at every pool write as deliverable
modes are, and the packaged seed pools carry the provider defaults. The commit
resolves the pool's value, else the provider's default; a pool whose provider
declares none resolves none.

*Every commit records an activation deadline when the reservation's pool resolves an
allowance, and leaves the lease without one when it resolves none.* A lease with no
deadline expires only at its end, as every lease does today; so every compute lease
gets an activation deadline and API credits' quota holds get none, by the same rule
and with no exemption written anywhere. The storefront passes nothing, the site
learns nothing about how the deal is billed, and the two pool facts this change
reads — the allowance and the lapse policy (D4) — are read through the port
`inject-site-pool-authority` settles, which is why that change lands before this
one's implementation: two more reads through the import it removes would widen the
divergence it exists to close. This change's design proceeds against the decided
port.

After delivery the storefront activates every compute lease through the same call —
a reserved deal to its agreed end, a per-period deal to its vouched horizon
(`converge-ongoing-compute-leases`) — and a reserved deal never calls again. This is
a change to reserved deals, stated as one, and the callers are not this change's:
every compute commit caller — VM's `_commit_capacity_hold` and
`_commit_fresh_reservation`, its resume path, bare metal's `fulfillment_service`,
and the Alkahest delivery paths — becomes an activation caller once, in
[`unify-compute-delivery-path`](../unify-compute-delivery-path/), which depends on
this change and wires activation into the one delivery path both domains compose. A
provision that overruns the allowance expires as an unfunded lease would, and a
reserved deal whose storefront dies between commit and delivery now expires too,
instead of holding capacity to its agreed end; what that costs the buyer of a prepaid
deal is the delivery path's committed refund, triggered by this change's
`renewal_lapsed` event in the awaiting-activation phase. For a per-period deal
provisioning time is non-billable by construction, since the period clock starts at
`start`, and the site accounts it apart by stamping the active instant it already
records at activation; for a prepaid deal the term runs from the agreed start, and a
prorated refund of provisioning time is a recommendation left to
`negotiate-open-ended-compute-terms`' session.

*Rejected:* a `requires_renewal` or per-period flag on the commit — a bit whose only
meaning is "the caller will call back", or a commercial classification at the site.
*Rejected:* a site-wide default — one number for VM and bare metal alike, whose
provisioning differs by an order of magnitude. *Rejected:* a storefront term for the
allowance; reusing `max_reservation_hold_seconds` or `hold_ttl_seconds`; no deadline
until `start`. Revisit triggers: `billable-capacity-reservations` landing, when the
provisioning window becomes a candidate for the same pricing machinery, noted there;
`inject-site-pool-authority` stalling past the point where this change is otherwise
ready, in which case the allowance and lapse policy can be carried on the commit
request instead and the site reads no pool state — a storefront passing a number it
does not understand, which is the thing to revisit, not the dependency.

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
lapsed, its phase, and the policy that applied; a storefront reads the phase to tell
an undelivered deal from an unrenewed one. The lease view exposes `renew_by_utc`,
`renewal_phase`, the active instant, and the lapse policy.

## Open questions

- Whether the deadline's due query joins the index
  `capacity-reservation-lifecycle-hardening` adds for hold expiry, or that change
  lands first; settled in design by which is further along.
- Whether a `grace` bound is site-wide (a maximum any pool may state) or only per
  pool; settled in design.

## Implementation cadence (recommended)

One round, the site alone: the two columns and migration, the activation and renew
transitions, the claim rule, the provider declarations and the two policy tags with
their reads through the port, the due query, the event cause, the view, and the
site's integration suite with its two-session races (activation against expiry,
renewal against expiry, a replayed earlier horizon refused in `active`, repeat
activation, a lease committed before the change untouched). The activation callers
and the lane evidence — a reserved deal running past the pool's allowance after
activation, a crash before activation expiring at it, an API-credit purchase
unchanged — are `unify-compute-delivery-path`'s. One session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2 | `openspec/specs/site-capacity/spec.md` and architecture companion; `ARCHITECTURE.md`, "Capacity reservation" |
| D3 | `resource-pool-management` spec; `physical-provisioning` spec; `DEPLOYMENT_AND_CONFIG.md` pool hints |
| D4 | `site-capacity` spec; `physical-provisioning` spec; `ARCHITECTURE.md`, "Recovery workers"; `DEPLOYMENT_AND_CONFIG.md` |
| D5 | `physical-provisioning` spec; `compute-provisioning-contract` spec |
