# Site Capacity Architecture

The [normative contract](spec.md) defines reservation and projection behavior. This document explains why capacity admission is a separate authority from storefront publication and fulfillment execution.

## Admission authority

A site is the serialization point for competing reservations in one failure domain. Storefronts may cache and aggregate availability, but only the site can atomically decide whether capacity remains admissible.

```text
storefront projection (advisory)
            ↓ request
site reservation ledger (authoritative)
            ↓ committed reservation
fulfillment scheduling
```

Putting the ledger outside storefronts allows several sellers or processes to share supply without treating independently refreshed caches as locks. It also lets a reservation outlive the storefront process that initiated it.

## Declared capacity and connection identity

What a site sells is declared by capacity declarations: a Physical Resource's shape
and quantity across every dimension it names, its pool, the categorical attributes
claims match, and, where it is delivered through a host, that host's `host_id`. A
host record is connection identity — how the provisioner reaches a machine — and
supplies no capacity. The resource-pool projection is built from declarations: every
declaration projects, and no entry carries host connection identity. A host record's
connection is joined to a declaration only where it is used, at dispatch, which
refuses a host with no record. Joining earlier would add nothing a projection
consumer reads and would carry the provisioner's connection address to storefronts.

A listing whose delivery has no usable host is the same as a listing with no host,
and neither appears. Where a declaration's pool is backed and the pool's provider
delivers through a host, the declaration has a usable host only when it names one
that is registered and enabled. A disabled host, a host never registered, and no
host at all leave a backed listing equally undeliverable, so one predicate,
`declaration_has_usable_host` in `market_resource_pools.host_requirement`, decides
all three, and every layer that decides what is offered applies it itself: admission
(probe, reserve, resize), the rebind recheck, settlement scheduling, and the ledger's
offered read. A declaration without a usable host is neither admitted nor placed,
and projects not enabled. The rule does not apply in an unbacked pool, whose
listings deliver nothing through a host and legitimately name none, nor where the
provider needs no host. Disabling a host thereby drains it: nothing new lands on
it, while an assignment already made keeps its host and its create waits at
dispatch until the host is enabled again.

Which hosts take new delivery is the host registry's fact, and the site keeps no
copy of it. The composition that owns hosts supplies a `DeliverableHosts` report,
the identifiers of registered, enabled hosts, and the ledger and the scheduler read
it in the session of the transaction that decides. The fact keeps one authority and
is read where it is kept, so the decision is judged against the host state its own
transaction sees, and nothing is copied, migrated, or put on a wire. That holds only
if the transaction has begun before the first read the decision rests on. The SQLite
driver begins one only at the first write, and a host write does not take the
ledger's lock, so each ledger decision path — probe, reserve, resize, the
own-session rebind, and the offered read — begins `BEGIN IMMEDIATE` after lapsing
stale holds, which commits, and before reading, as scheduling's unit of work already
does; a host write through another session then commits only after the decision
ends. The cost is that a projection read waits behind another writer, within the
busy timeout. The site learns
only `host_id`s, which declarations already carry, and no connection information.
This is the shape the release guard and the host pool-change hooks already have: a
narrow interface a lower layer defines without naming the upper one. A composition
can supply it only where hosts share the ledger's database, which holds for every
host-delivering provider, since all run inside the compute provisioning service. A
site-side copy, such as an eligibility column a host hook keeps current, was
rejected: it is a second copy of a host fact that drifts wherever a write path misses
the hook. So was reading the set before the decision and passing it in, which lets a
disable commit between the read and the decision. A composition that supplies a host
requirement but no report treats every named host as usable; one that supplies no
requirement, as API credits does, applies no host rule.

Projected `enabled` follows admission. A storefront mirrors admission's constraints
from its projections only to avoid committing to what admission will refuse, so
the projection states what admission enforces: a declaration's projected `enabled`
is its own `enabled` and a usable host. Storefronts already close a disabled
source's listings and reopen them under their original identities when it returns,
and their inventory guard refuses a listing whose declaration is no longer enabled,
so no storefront, wire shape, or event changes for it. An additive per-member field
such as `host_enabled` was rejected, since no consumer needs the distinction and
every consumer would have to learn it; so was omitting such a declaration from the
projections, which would hide it from consumers for no gain. The operator's own
listing keeps each declaration's stored `enabled`, so an operator sees what they
declared.

The ledger states each declaration's offered `enabled` in one read,
`list_offered_resources`, which takes the declarations, the host requirement, the
pools' providers and deliverable offering modes, and the deliverable-host report in
one transaction. The capacity-bucket projection, the advisory snapshot, and the
compute service's resource-pool projection are all built from it, so the domain
views that projection builds, bare metal's `available` among them, cannot drift from
the capacity-bucket projection, and no projection builder reads a host. The read
judges a pool by whether it declares a deliverable offering mode, as admission does,
rather than by its backing: an unbacked pool delivers nothing, so a pool declaring no
deliverable mode keeps its declarations' own `enabled`, and the site takes no new
read of pool state while its edge into the pool authority stands. A missing pool, or
one whose modes do not parse, is judged to deliver, so the read fails closed rather
than offering what admission would refuse. Applying the rule in each projection
builder instead was rejected: it calls the rule from two places and reads hosts in a
session apart from the declarations. This makes the ledger hold projection logic
beside its records; a ledger would better be closer to a raw data structure, with
projection logic kept apart from it, but the ledger already mixes the two, and
separating them is a change of its own.

The alternatives each left capacity with more than one authority. Adding vCPU, RAM,
and disk columns to hosts would have folded sellable capacity into records whose
job is SSH users, key material, and addressing, and an Ansible inventory is a poor
carrier for declarations because it exists to describe how to reach a machine.
Keeping GPUs on hosts and moving the other dimensions to declarations would have
left two partial authorities in one service. So declarations own every dimension,
and a host record describes no hardware at all: it carries no GPU count or model,
and its storage has no column for either. Keeping them as descriptive fields would
have left a second, unchecked statement of hardware beside the declaration. A host
API request or an INI entry that still carries them has them ignored, as any field
or variable the host contract does not define is ignored: refusing or warning would
be code kept until something retires it, guarding a mistake — expecting a field
that affects nothing to be recorded — that is easily diagnosed and fixed. Before
the columns were dropped, the ordered migration read them for capacity once, at
upgrade: a host with GPUs that no declaration named received a declaration derived
from it. No host write declares capacity —
not a host definitions document, not an INI inventory submitted to the import
route, and not the host API — because a declaration made as a side effect of listing a host would sell
it before its administrator decided how, and would make one host behave
differently by the entry point that wrote it.

One declaration type serves every entry point — single registration, a mounted or
submitted definitions document, and capacity import — with the same validation and
the same refusals, so a declaration means the same thing however it arrives. Every
declaration names its pool, and a stored row with none is malformed: it is reported
by the administrative listing, so an operator can find and re-declare it, but is
projected, admitted, scheduled, and moved as a member of no pool, rather than read
as `default` or as a pool named for its resource.

Administration composes with the ledger's serialization rather than around it. A
declaration's checks against stored state (a pool move while the resource holds a
live reservation, a host another declaration names) are true only until something
else commits, so a caller writing declarations into its own transaction holds the
ledger's serialization lock through that transaction's commit, and the ledger's
in-session writers refuse to run without it.

## Private accounting

Multidimensional balances are represented by private capacity buckets and current reservation debits. The public reservation identifies its lifecycle and reserved dimensions; it does not expose a backing bucket or physical-resource identity. Scheduling may atomically move the debit when selection binds the reservation to another eligible bucket.

Admission and scheduling use the same fit semantics. Every requested dimension must be present and sufficient; a missing dimension means zero availability rather than an unconstrained match. This avoids accepting a request under one predicate and selecting a resource under another.

## Reservation lifecycle

A hold protects negotiation-time intent for a bounded period. Commit makes capacity durable for execution. Release returns capacity only through the owning lifecycle. Expiry and early termination may initiate release, but physical capacity remains held until executor or provider teardown succeeds or an operator explicitly force-releases it.

A lease's activation is one instant, `activated_at_utc`, which the site records once from its own clock when the lease begins running against a provisioned resource. It is admissible only on a lease, a `leased` reservation with a lease end: activation cannot commit a hold, resurrect a lease, or undo a release an expiry or an operator claimed first, and an open-ended hold, which has no lease tail, is never activated, so every activated reservation is one the compute contract's `LeaseView` can show. Whether a lease is activated is derived from the instant and stored nowhere else, so no second field can disagree with it and truncation needs no capping of a copy. Activation changes neither the state, nor the window an earlier truncation may have shortened, nor admission, which accounts the full agreed window before and after it. Null means only that no activation is recorded: a reservation stored before the column existed records none, and that says nothing about whether its resource was delivered. The instant is a fact of the lease's lifecycle, not delivery evidence, which the deal lifecycle judges from the storefront's own records. Activation records no capacity event, because availability does not move, and pushes nothing, because the storefront that asked holds the answer; capacity release remains the one transition a site pushes to a storefront. A request carries the reservation identity alone and no instant, so the recorded instant is the site's whatever time the caller acted.

A reserve may name its placement in `deal_ref.placement_key`, `<negotiation_id>:<placement>`, which the ledger lifts into a unique `placement_key` column and keys replay by, beside `escrow_uid`. With the key it records the request it admitted — resource type, claim attributes (the pool among them), offering mode, dimensions, and the window as asked, its start and duration — and judges a replay against that record rather than the row, because commit and truncation move the row's window after admission and the exact replay of a truncated lease must still find it. An exact replay returns the recorded reservation in whatever state it has reached, held, committed or released, admitting nothing; a changed replay raises the ledger's conflict error, which the reserve route answers 409, and a malformed key is refused 422. The hold's TTL is not compared: a replay returns the hold whose expiry admission fixed. The site is the ledger itself, so a replay at another site finds no key. A keyed reserve whose `escrow_uid` already holds a reservation placed without a key adopts it under the key, so a deal reserved before keys existed is found by its key once released; one held under another key refuses the reserve. A resize lifts no key onto its new row, which would put two rows under one key. Keying the placement's purpose, not only the deal, lets a deal replace a lapsed hold under a different placement while a lost settlement acknowledgement replays its own. A storefront lookup before reserving again was rejected: it reads every reservation at the site, cannot refuse a changed request, and races a dying process's request.

Every state `ReservationState` defines is one a lifecycle transition writes, and no ledger operation writes a state its caller names: release takes whether it is forced, not a target state. A generic state writer would be the one way a reservation could enter a state its lifecycle forbids, so tests reach a state through the real transitions or seed the row, as `docs/development/TESTING.md` permits for state no API expresses.

Two states nothing wrote, `provisioning` and `provisioning_failed`, are not defined, and no supported database holds a row in either: compute provisioning's v0.3.0 floor converted them — a `provisioning` row to `unmanaged`, whose capacity stays held until an operator repairs it, and a `provisioning_failed` row to `force_released`, whose capacity stays free, each with a failure reason naming the state it held — and the API-credit service migrates no database its own chain did not build.

## Resize as one transaction, not two calls in either order

When a negotiated shape changes for an already-held reservation, the ledger supersedes it (`resize_reservation`) rather than mutating it in place or composing two ordinary `reserve()`/`release()` calls. Two simpler designs were considered and rejected because each has a real correctness bug the other doesn't:

- **Reserve-new-then-release-old** evaluates the new shape's availability while the old hold is still artificially consuming capacity. A resource that would satisfy the new request the instant the old hold clears can incorrectly report as unavailable, because that capacity is invisible until release actually happens — a false negative, most visible exactly when the new shape targets the same resource or pool the old hold already occupies.
- **Release-old-then-reserve-new** as two separate calls fixes that visibility problem but reintroduces a different risk: if the new reservation then fails, the old one is already gone, leaving the negotiation with nothing.

Both properties — evaluating the new shape's availability *as if* the old hold were already released, and leaving the old reservation completely untouched if the new shape can't be satisfied — are only simultaneously achievable inside one transaction that releases-then-reserves internally, committing only on success and rolling back in full on failure. This generalizes the atomic-rebind pattern scheduling already uses for moving a settlement assignment between resources, to the case that pattern doesn't cover on its own: source and destination can legitimately be the same resource or pool, which is exactly when the visibility problem shows up.

## Intended-end evidence

The ledger records one immutable `lease_ended` event with the transition that
forms end intent, before executor teardown. Repeating that transition returns
the same event. The event binds reservation/site, instant, cause and source state,
including termination/failure reasons and any applicable deadline phase. The
service's separately acknowledged report outbox borrows the same transaction,
so rollback removes both; direct release, expiry, explicit termination, failed
release and operator force-release are all covered.

Compute provisioning signs and persists the original wrapper under
`arkhai.site.lease-ended.v1`. Owner-scoped push and authenticated
`LeaseView.end_reports` recovery return identical signed bytes even after signer
changes. Unsupported push parks per configured peer, transient failures retry,
and old events are never redirected on peer reconfiguration. Explicit resumption
follows receiver upgrade. See
[report delivery](../physical-provisioning/architecture.md#lease-end-report-delivery).

This report states intended end, not successful teardown or financial state.
A due end terminates immediately; a future end truncates the lease without
extending its immutable horizon, using second precision. Storefront end service
keeps actor/cause/source and translates physical intent without importing payment
logic into the site. A separate capacity-released callback reports proven return
and alone permits normal storefront availability reconciliation. Failure keeps
capacity unavailable; force-release remains an explicit audited override.

## Projection boundaries

The site exposes two independent storefront views:

- per-resource inventory for deliberately individual-resource offerings;
- grouped currently available shapes for fungible capacity publication.

Each view has its own revision and canonical digest. Grouped rows use deterministic criteria and counts, omit physical-resource identifiers, and are never allocation targets. These properties let storefronts replace one cached projection without conflating publication convenience with admission truth.

## Event privacy and convergence

Capacity events are anonymous availability changes. Broadcasting deal context would leak one storefront's customer activity to another seller sharing the site. Deal-scoped outcomes therefore use an owner-specific channel.

Revisions make missed events detectable. A consumer that sees a gap refreshes a complete snapshot rather than attempting to infer unknown intermediate deltas. Reconciliation reacts to every capacity change, not only changes caused by the local storefront.

A change of a host's state — enabling, disabling, or registering it — changes what the site offers without recording a capacity event or advancing the capacity version, as enabling or disabling a pool does. Projection revisions and digests are computed when a projection is read, so a projection whose contents the change alters advances its revision and digest at its next read, and a storefront sees it at its next projection poll; registering a host no declaration names alters neither projection. Source-publication reconciliation then closes or reopens the listings. Admission refuses at once, so the residual is one poll interval in which a listing is advertised that fails reservation in the ordinary capacity class. A hook having the ledger emit a delta from inside each host write was rejected: a hook on every host write path for a gain of one poll interval.

## Routing identity

`site_id` is selected and trusted at the storefront aggregation boundary, where it is bound to a configured provisioning connection. Provisioning-local rows are already scoped by their database authority and do not encode routing endpoints or credentials into reservation identifiers.

## Projected feasibility matching

Ranking multiple sites for a claim (`most_available` placement) and
authoritative admission at a single site use the same claim-matching
semantics, but not the same code path by default. The core-layer
aggregator's default matcher is deliberately coarse (pool/resource
identity and quantitative dimensions only) — it cannot depend on any
kit-layer package, so it cannot know a domain's categorical attributes
(region, GPU model) the way the site's own admission path does. A
domain composing the aggregator MAY inject an exact `ClaimMatcher` that
delegates to its backing site's own authoritative matching function,
so ranking and admission agree on every field the site actually checks,
without moving site-specific matching logic into the core layer. This
is composition, not a shared implementation: the aggregator's own
default remains available to any domain whose backing site doesn't
warrant the exact match, and the same package-layering rule that keeps
core backend-agnostic still applies.

## Current limits

The current ledger is not a distributed consensus system for active-active replicas. Generic deal-event ownership across arbitrary storefront topologies and universal aggregation across every physical resource type are not established by the capacity contract.

A compute lease's tail shares the reservation row with API credits' quota grants, because the API-credits service hosts the whole site ledger as its quota ledger. A column the ledger maps for leases therefore lands in that service's migration chain too, though nothing there reads or writes it and no quota grant, an open-ended hold, is ever activated. Separating the lease tail from the reservation is unowned work recorded in the [change index](../../changes/README.md).

## Related contracts

- [Storefront publication](../storefront-publication/spec.md)
- [Fulfillment](../fulfillment/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
