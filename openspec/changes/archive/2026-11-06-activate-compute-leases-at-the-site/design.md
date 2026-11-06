# Design — compute lease activation at the site

## Context

`kit/site` owns the capacity reservation and its lease tail as one row,
`capacity_reservations`. Commit is idempotent and records the window once, truncation
only moves the end earlier, admission accounts the full agreed window, and
`list_lease_due` selects leased rows by `lease_end_utc`. The row records the lease's
window, its executor target and its create and release handles, but nothing records
that the resource behind the lease was provisioned and the lease began running in
earnest.

`unify-compute-delivery-path` orders every compute delivery as commit, dispatch,
activation, billing start and access, and needs the site to record activation once,
idempotently, by reservation identity, with an instant of its own that billing start
and any later dispute can rest on. `renewable-compute-lease-deadlines` then gives an
unactivated lease a delivery deadline, written at commit, and expires the lease that
never activates; it needs a fact its expiry claim can race against. The deadline
needs the pool-authority port; activation needs nothing, so activation is this change
and lands first.

Storefronts reach the site's reservation lifecycle through one chain, and every
storefront capacity effect passes its guard (`docs/development/ARCHITECTURE.md`,
"Capacity publication and multi-domain storefront composition"): the kit's
`CapacityEffects` and `CapacityRuntime` (`kit/capacity-publication`), core's
`AggregateCapacityClient` and the `SiteCapacityAuthority` protocol it routes to
(`core/storefront`), the site client (`kit/site-client`), and the site's capacity
router (`kit/site`). The compute provisioning contract's `LeaseView` is the compute
family's typed read of the same row, carrying its lease-lifecycle fields and signed
end reports. Two services host the ledger table: compute provisioning and API credits.

## Goals / Non-Goals

**Goals:** one fact recording activation; one conditional, idempotent activation
transition reachable through the storefront's guarded capacity effects; that fact
visible on both views of the lease; existing leases unchanged.

**Non-goals:** the delivery deadline and everything that reads or writes it (its
column, pool tag, commit snapshot, expiry claim, lapse cause and switch), renewal,
extension, payment or refund operations, and wiring the delivery callers.

## Decisions

### D1 — One fact, `activated_at_utc`, and a derived phase

The reservation row gains one nullable column, `activated_at_utc`. Activation is the
conditional transition that writes it where it is null, in one transaction, from the
site's clock; nothing updates it afterwards. It is admissible only on a lease: a
`leased` reservation with a lease end.

- In `leased` with a lease end and `activated_at_utc` null, activation writes the
  instant and returns the reservation.
- In `leased` with `activated_at_utc` set, a retry returns the reservation unchanged,
  with the same instant.
- From `reserved`, `releasing`, `release_failed`, `unmanaged`, `released` and
  `force_released` it is refused and writes nothing: activation cannot commit a hold,
  resurrect a lease, or undo a release an expiry or an operator claimed first.
- On a `leased` reservation with no lease end — an open-ended hold, which the ledger
  records with no lease tail — it is refused and writes nothing.

The request names the reservation and carries nothing else: no payment fact, no
billing kind, no target time and no instant. Activation never changes the lease's
window. A truncation before activation, or between a lost acknowledgement and its
retry, is simply the current end the response carries: activation neither extends it
nor restores the commit end. Admission is untouched: it accounts the full agreed
window before and after activation.

Activation is a fact of a lease's tail, so a reservation committed with no end is not
activated. Every compute commit carries a finite end — the VM and bare-metal commits,
and the open-ended compute terms, which resolve their horizon into the agreement's
duration at acceptance — and the only open-ended commits are API credits' quota grants,
which no caller activates. Refusing the open-ended hold keeps every activated
reservation one the compute contract classifies as a lease, so D3's `LeaseView` can
always show it; admitting it would make a quota grant activatable and put the
compute contract's view out of reach of a reservation it had activated (design review
08, F1).

Whether the site has recorded a lease's activation is derived, not stored: it has
exactly when `activated_at_utc` is set. The deadline change adds its own deadline column, under a
name it chooses, and derives "awaiting activation" as a deadline set on a lease not
yet activated; its due instant is the end for an activated lease and otherwise the
earlier of deadline and end, and its expiry claim compares the observed end, deadline
and `activated_at_utc`. Nothing in the row is a second copy of another field, so no
two fields can disagree and truncation needs no capping of a copied instant.

`activated_at_utc` is the site's record that the lease began running against a
provisioned resource: a fact of the lease's lifecycle, and the activation's stable
reference together with the reservation identity. It is not evidence of delivery: the
deal lifecycle judges delivery by the storefront's durable `available` record against
the accepted deadline
(`openspec/changes/archive/2026-11-03-agreed-evidence-and-early-termination/design.md`,
D8). No other value in the row can stand in for it: the lease start is the agreed
window, the row's update time moves with every write, provider readiness is
fulfillment's checkpoint, and a retry's request time is later than the fact.
Existing rows migrate with null, an honest unknown rather than a guess. Null therefore
means only that no activation is recorded: on a reservation that predates the column
it says nothing about whether the resource was delivered, and no consumer reads it as
evidence that it was not (design review 08, F3). The deadline change tells its own
newly committed leases apart by the deadline it writes at commit.

Rejected:

- **Three columns here** — `renewal_phase`, `renew_by_utc` and `activated_at_utc`,
  so the schema changes once. The phase duplicates `activated_at_utc` (its only value
  this change could write is `active`, written in the same transaction), and
  `renew_by_utc` has no writer here but a copy of the end that a later truncation
  leaves stale. The names belong to the renewal design that now sits outside Goal 8
  in `lapse-billing-with-the-site-lease`, and a phase value `active` beside
  `LeaseView.status: active` would give one word two meanings on one view. A
  migration in the deadline change is cheap beside a permanently redundant row.
- **The same three columns renamed** (`activation_phase`, `activate_by_utc`) — fixes
  the names but keeps the redundancy and the copy.
- **A phase column with the instant, the deadline column later** — the phase is a
  second copy of the instant until the deadline change writes another value.
- **Reusing the retired `provisioning` reservation state** — activation is orthogonal
  to reservation state, and the lifecycle removed that state.
- **A caller-supplied activation instant or target deadline** — the instant is the
  site's fact, written by the transition; a deadline is the deadline change's to
  compute.
- **A payment-aware transition** — the site knows no payment mechanism; billing start
  follows activation in unify and is end service's intent.

### D2 — Activation is written only through the site capacity API

Activation is a storefront capacity effect, so it takes the path every such effect
takes, beside commit and truncate:

- the ledger's `activate_lease(capacity_reservation_id)`;
- the route `POST /api/v1/capacity/reservations/{capacity_reservation_id}/activate-lease`,
  addressed by its path and carrying no body fields, in the server's authenticated
  route table and the site client's route contracts, held in step by the existing
  route-parity test;
- `SiteCapacityClient.activate_lease`;
- `activate_lease` on core's `SiteCapacityAuthority` protocol, which every
  implementation gains, and on `AggregateCapacityClient`, routed to the named site as
  truncation is;
- `CapacityEffects.activate_lease(binding, …)` under the binding guard truncation
  passes, and `CapacityRuntime`'s delegate.

The `market-composition` and `storefront-publication` requirements that name the
storefront capacity effects name activation among them, so it reloads and compares
the same binding and passes the backing delegate's guard before any site call.

Rejected:

- **An activation route on the compute provisioning contract's lease routes** — it
  would bypass `CapacityEffects`' guard, and give the compute contract a writer on a
  row the site's capacity API owns.
- **Both routes** — one transition with two writers.
- **Calling the site client directly from the delivery path** — skips the aggregate's
  routing and the binding guard.
- **Activation on `SiteAuthorityPort`** — that port carries the reservation facts the
  compute lease watchdog consumes; the watchdog never activates.

### D3 — `activated_at_utc` is on both views of the lease

Every lease-lifecycle field of the row — window, executor target, create and release
handles, failure — appears both in the site's reservation view and in the compute
contract's `LeaseView`; only capacity-accounting fields are confined to the site view.
`activated_at_utc` is a lease-lifecycle fact, so it follows the same pattern:

```yaml
# site reservation view (the activation response, and every read after it)
reservation:
  capacity_reservation_id: res-7f3c
  state: leased
  lease_start_utc: "2026-11-10T12:00:00+00:00"
  lease_end_utc: "2026-12-10T12:00:00+00:00"
  activated_at_utc: "2026-11-10T12:07:41.204118+00:00"
  # ...every other field the view carries today

# LeaseView
contract_version: "3.0"
capacity_reservation_id: res-7f3c
offering_mode: vm
status: active
lease_start_utc: "2026-11-10T12:00:00Z"
lease_end_utc: "2026-12-10T12:00:00Z"
activated_at_utc: "2026-11-10T12:07:41.204118Z"
```

An unactivated lease shows `activated_at_utc: null` on both. `LeaseView` gains it as
an optional field mapped by `lease_view()`; an older major-3 client ignores the field,
so the contract stays at major 3. The compute contract gains no activation route
(D2). After a refused activation (D5), a storefront learns the lease's state through
the `LeaseView` read it already uses for end reports, which carries `status` and the
instant.

Rejected: **the site view alone** — the compute family's lease view would describe a
lease's window, target and handles but not whether it was activated, breaking the
pattern the two views follow, and an operator's lease list could not find a delivered
lease that was never activated.

### D4 — A site without activation is not a supported deployment

A storefront and the site it calls are deployed and upgraded together; no supported
deployment runs a storefront ahead of its site, as `compute-provisioning-contract`'s
version rule already requires of the provisioning service and its callers. This
change ships before any caller of activation exists. A caller that cannot activate —
an unknown route, an unsigned answer, an unreachable site — has not activated: the
delivery is repair-required, and nothing treats the lease as already active.
`activated_at_utc` is an ordinary nullable field, with no rule about its key's
presence.

Rejected: **a no-op for a site without the route**, where a caller holding a signed
reservation view that lacks the `activated_at_utc` key treats the lease as already
active. The activation call cannot show that a route is missing — an unsigned 404 is
also what anything between the client and the site may give — so the rule would rest
on the key's absence from a signed read, a permanent wire constraint the typed
`LeaseView` cannot even carry, and a legacy branch in every caller for a deployment
shape the repository never produces.

### D5 — Activation answers as commit does

- **200** with the reservation as the site recorded it, on the first activation and
  on every retry of an activated lease;
- **404** for an unknown reservation;
- **409** from any state but `leased`, naming the state, and from a `leased`
  reservation with no lease end, saying it has no lease tail; nothing is written.

Commit is the precedent; truncation's `reservation: null` for both unknown and refused
would merge the two outcomes a caller must tell apart — a release or expiry that
claimed the lease first, and a reservation the site does not know. A caller reads the
lease's state after a 409 rather than parsing the answer's text.

### D6 — Both services hosting the ledger migrate

Compute provisioning and API credits each gain one ordered migration adding the
nullable `activated_at_utc` column to `capacity_reservations`, leaving every existing
row null, as each added `release_requested_at`. No backfill: a lease start or commit
time would be a guess. Without API credits' migration its reads of the mapped table
fail.

API credits takes the migration only because it hosts the whole site ledger as its
quota ledger, and that ledger keeps a compute lease's tail on the same row as every
quota grant; nothing in API credits reads or writes the column. Separating the lease
tail from the reservation, so lease migrations stop landing in a service with no
leases, is recorded as unowned work in `openspec/changes/README.md` (design review 08,
F1). Migrations are ordered by their dated identifiers, so this change needs no
coordination with `capacity-reservation-lifecycle-hardening`'s later migrations on the
same table.

### D7 — Activation records no capacity event and pushes nothing

Capacity events are anonymous availability changes, and activation changes neither
admission nor availability; recording an executor target, the nearest precedent,
writes lease-tail evidence with no event. The storefront that requested activation
holds its answer, and capacity release remains the one transition a provisioner pushes
to a storefront. A `lease_activated` event was rejected: nothing consumes it, and it
would put deal timing on a feed shared across sellers.

### D8 — Implementation cadence

One round, implemented in one session, before its review: the site side (the column,
both migrations, the ledger transition, the route and the site client) and the caller
chain (core's protocol, the aggregate, `CapacityEffects` and `CapacityRuntime`, and
`LeaseView`), then closeout. Each slice is a handful of methods and tests, and the
risk is local to the site's ledger and the clients over it.

### D9 — The instant is ISO-8601 UTC text, as the row's other instants

`activated_at_utc` is written as `release_requested_at` is, from the site's clock as
an ISO-8601 UTC string, and `LeaseView` parses it to a datetime as it does the lease
window. Integer seconds, the `lease_ended` report's encoding, is the event contract's
and would give the row two formats for instants.

### D10 — Decided at implementation: the aggregate's route order and the site check

Two questions the design left to the code were settled while implementing section 4,
the first by the owner at the pre-closeout triage (review 23, F1).

**Route order raises the most informative refusal.** `AggregateCapacityClient.activate_lease`
keeps a route-order path for a caller that names no site, as the protocol's optional
`site_id` allows. Truncation's route order swallows each site's exception and returns
`None`; activation's cannot, because a site refuses an activation with an error (404 or
409), never `None`, so swallowing would turn every refusal into a silent `None`. Route
order therefore raises when no site activates the reservation, as commit's does. As
first written it raised the last site's error, so a 409 from the site holding a
released reservation could be hidden by a later site's 404, losing D5's distinction;
a warm cache made it likelier, since the owning site is tried first. Route order now
ranks failures: a site's refusal with a status other than 404, then a failure with no
status (a site that could not be asked, which may hold the reservation), then a 404,
keeping the later of equal rank. The status is read by attribute, since core cannot
import the site client's error type. Commit's route order had the same flaw and takes
the same ranking, outside the plan, on the owner's word, because D5 makes activation
answer as commit does. Rejected: a required `site_id`, which breaks `CapacityClient`'s
signature and differs from commit and truncation; and leaving it as a recorded limit.
The path is latent — `CapacityEffects` always names the binding's site — and a first
version that ranked only non-404 over 404 let an unreachable later site hide a 409.

**`CapacityEffects` refuses a result tagged with another site.** Beyond returning the
reservation at the binding's site, `CapacityEffects.activate_lease` refuses
(`CapacityBindingError`) a result the aggregate tags with a site other than the
binding's, as `reserve` does. The implementation's fresh-context check called this a
speculative guard, since `AggregateCapacityClient` always tags a site-named result with
that site; it was kept because `CapacityEffects` is composed over whatever aggregate a
storefront builds — bare metal builds its own — and `reserve` already checks the same
seam, so a test with a mocked aggregate can trigger it.

## Dependents whose documents now differ

Three dependents' documents describe the design this change replaced; each reconciles
in its own design work, and this change edits none of them:

- `renewable-compute-lease-deadlines` writes `awaiting_activation` and `renew_by_utc`
  into columns this change does not add, caps a copied deadline on truncation, and
  compares a stored phase in its expiry claim. Under D1 it adds its own deadline
  column and migrations in both hosting services, derives the phase from
  `activated_at_utc`, and puts its deadline on both views as D3 does.
- `unify-compute-delivery-path` applies a no-op for a site without the route (D4
  removes it), names the site's `renewal_phase` (D1 removes it), and activates
  "through the provisioning client" (D2: through `CapacityEffects`; it reads a refused
  lease's state through `LeaseView`).
- `lapse-billing-with-the-site-lease` reuses `renew_by_utc` as a renewal deadline
  after activation; a renewal design would add a renewal deadline of its own.

## Open questions

None.

## Permanent documentation destinations

| Accepted decision | Destination |
|---|---|
| D1 the instant, the transition, the derived phase | `openspec/specs/site-capacity/spec.md`; `openspec/specs/site-capacity/architecture.md`, reservation lifecycle; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D2 the write path | `openspec/specs/market-composition/spec.md`, `openspec/specs/storefront-publication/spec.md`; `openspec/specs/market-composition/architecture.md` and `docs/development/ARCHITECTURE.md`, the capacity effects each names |
| D3 both views | `openspec/specs/compute-provisioning-contract/spec.md` |
| D4 deployed together | `docs/development/ARCHITECTURE.md`, "Operators" under deployment topology, which already states that one business upgrades sites and storefronts together |
| D5, D9 | `openspec/specs/site-capacity/spec.md` |
| D6 both migrations | `openspec/specs/site-capacity/spec.md`; `openspec/specs/site-capacity/architecture.md`, "Current limits" |
| D7 no event, no push | `openspec/specs/site-capacity/spec.md`; `openspec/specs/site-capacity/architecture.md`, "Reservation lifecycle" |
| D8 cadence | no permanent destination |
| D10 route order and the site check | `openspec/specs/market-composition/architecture.md`, "Storefront composition kit" |

## Design promotion record

Promoted at closeout. The four `spec.md` files are written by the archive, which merges
the change's deltas.

| Accepted decision | Permanent location |
|---|---|
| D1 the instant, the transition, the derived phase | `openspec/specs/site-capacity/spec.md`, "A lease records when it was activated" and "Activation records its instant once and changes nothing else" (archive); `openspec/specs/site-capacity/architecture.md#reservation-lifecycle`; `docs/development/ARCHITECTURE.md#capacity-reservation` |
| D2 the write path | `openspec/specs/market-composition/spec.md`, "Kit-owned capacity and publication lifecycle", and `openspec/specs/storefront-publication/spec.md`, "A listing's origin site is not its admission authority" (archive, modified); `openspec/specs/market-composition/architecture.md#storefront-composition-kit`; `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition`; and `openspec/specs/physical-provisioning/spec.md`, "A lease's executor identity and evidence are fixed once recorded", whose list of a lease's writers now names the site's activation and whose own "activation" now says the fulfillment's (by hand: no delta covers it) |
| D3 both views | `openspec/specs/compute-provisioning-contract/spec.md`, "A lease view shows when the lease was activated" (archive) |
| D4 deployed together | `docs/development/ARCHITECTURE.md#operators` |
| D5 the answers | `openspec/specs/site-capacity/spec.md`, "Activation records its instant once and changes nothing else" (archive) |
| D6 both migrations | `openspec/specs/site-capacity/spec.md`, "A lease records when it was activated" (archive); `openspec/specs/site-capacity/architecture.md#current-limits` |
| D7 no event, no push | `openspec/specs/site-capacity/spec.md`, "Activation records its instant once and changes nothing else" (archive); `openspec/specs/site-capacity/architecture.md#reservation-lifecycle` |
| D8 cadence | no permanent destination: the plan's, not current behaviour |
| D9 the instant's representation | `openspec/specs/site-capacity/spec.md`, "A lease records when it was activated" (archive) |
| D10 route order and the site check | `openspec/specs/market-composition/architecture.md#storefront-composition-kit` |
| Activation by reservation identity alone | `openspec/specs/site-capacity/spec.md`, "Activation is addressed by reservation identity alone" (archive) |
| Roadmap currency | `docs/development/ROADMAP.md`, Goal 8: the gap row rewritten as archived, and the current state naming the site's activation with no caller wired |
| Campaign index currency | `openspec/changes/README.md`: this change's row's notes and its link to the archive; the Goal 8 graph and every other row unchanged |
| Capability index | `openspec/specs/README.md` unchanged: no capability added |
