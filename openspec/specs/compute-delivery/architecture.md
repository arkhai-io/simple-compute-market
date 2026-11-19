# Compute Delivery Architecture

The [normative contract](spec.md) defines the compute family's delivery order. This
companion explains its shape, the reasons for its boundaries, and its current limits.

## Position

`domains/compute/delivery` (distribution `arkhai-compute-delivery`, source
`compute_delivery`) is a compute specialization library: the family's delivery order,
beside `provisioning/compute`, which is the family's physical provisioning. It depends
on the provisioning family's wire contracts, the neutral lifecycle kits
(`kit/deal-lifecycle` and its contracts, `kit/deal-servicing`),
`kit/capacity-publication`'s guarded `CapacityEffects`, the site client (for the
refusal and unsigned-answer errors it classifies), core's result envelope and the
identity kit. It imports no storefront, no settlement mechanism, nothing from
`arkhai-compute` and nothing from `kit/fulfillment`, whose surface it reaches through
the provisioning contracts' wire models.

It owns the order — window derivation, the future-start wait, commit, dispatch,
readiness, activation, billing start, availability, the end hand-off, recovery
decisions and the access check — and keeps no table. The facts it orders already have
homes: the Agreement window, commitment instant, accepted delivery deadline,
`available_at` and revision in end service's `servicing_delivery`; authorization
decisions and the single billing intent in end service's intents; reservation,
dispatch, fulfillment and activation in each domain's own progress row.

Two placements were rejected and stay rejected:

- **A family delivery record** holding the window and identities, with the domain rows
  as projections, would be a third copy beside `servicing_delivery` and the domain
  rows, which keep VM's fulfillment context and bare metal's materialization anyway.
- **Widening `servicing_delivery`** with physical progress would make end service, a
  repository-wide kit API credits composes, the owner of compute delivery.

The access check is the library's too, not a repository-wide kit's: it composes end
service's admission with the provisioning result read, and API credits composes no
seller half, admission or availability record.

## Ports and `drive`

A storefront composes `ComputeDeliveryPath` with its end service, its guarded
`CapacityEffects`, and three implementations of protocols the library declares:

- `DeliveryProgress` over the domain's existing progress row. Every method takes the
  `sqlite3.Connection` of the transaction the path opens on end service's database,
  where both domains' rows live, so a progress write commits with the admission that
  permits it. It reports the row as `RecordedProgress` in the path's step vocabulary
  (`reserve`, `commit`, `dispatch`, `fulfillment`, `activated`), writes each identity
  once, and releases the domain worker's convergence claim on a deal that waits.
- `ComputeDeliveryDomain`, what only the domain knows: the accepted deal (its verified
  settlement as the commitment reference, the listing's capacity binding that selects
  the site, and the payment adapter its table resolves, or none), its reserve claim,
  its accepted acceptance-time hold if it has one, its exact fulfillment request, its
  ready evidence from a fulfillment result, and its continuation after availability.
- `SiteFulfillment`, the provisioning family's begin, status, result and lease reads
  routed by site, which each storefront adapts its own provisioning client to.

`drive(negotiation_id)` advances one deal as far as it can go now and returns one of
six outcomes: `waiting(wake_at)`, `pending`, `repair_required(reason)`, `available`,
`converged` or `ended`. Callers are each domain's fulfillment hook, which maps the
outcome to fulfilled, deferred or failed (`DeliveryOutcome.hook_disposition`), and
each domain's re-drive of unfinished deliveries ([dispatch and
recovery](#dispatch-and-recovery)). Six outcomes suffice because a first drive is
the start of the normal path, and a missing deal and unreadable progress ask the same
of a caller; the closed repair reason distinguishes them.

The path holds no lock. A caller serializes the drives of one deal: VM through its
durable convergence claim, bare metal through its per-deal lock. An exception from a
fulfillment or lease read, or from billing start's payment authority, propagates with
every earlier step recorded, so the next drive resumes there.

`drive` fails closed. What it cannot read — a missing servicing record or verified
settlement, unparseable timing, an unknown stored step, identities that contradict the
step, a port answer of the wrong kind, a fulfillment result that is empty or shows no
ready evidence, a malformed site answer — is `repair_required` with the recorded
identities and the evidence reference it rests on (`servicing_delivery:<id>`,
`delivery_progress:<id>`, `settlement:<id>`, `reservation:<id>`, `fulfillment:<id>`),
and the recorded resource is kept rather than replaced.

## The delivery order

```text
accepted deal ─► window ─► commit (adopt hold │ reserve :settlement) ─► wait for start
   ─► authorize dispatch ─► record dispatch ─► begin_fulfillment ─► record fulfillment
   ─► poll ─► ready evidence ─► admit activate ─► activate_lease ─► record activation
   ─► authorize start ─► begin_billing ─► authorize disclose + record available
   ─► continuation ─► converged
any refusal, failure, elapsed window or lapsed activation before available ─► end hand-off
```

Before commit, dispatch, billing start and disclosure the path calls end service's
`authorize_delivery` for that phase; before activation it passes admission for
`activate`. Authorization evidence holds only what is fixed before the phase — commit
binds the commitment, dispatch adds the reservation, start and disclose carry the full
bundle — because end service keys an authorization by phase and admission revision
and refuses a same-revision retry whose evidence changed. The dispatch record and the
availability record are written in their authorization's own transaction, so each
commits with the admission that permits it or not at all.

### The Agreement window and the future-start wait

The window comes from `servicing_delivery`'s `start_at` and `term_end` alone. A
commit answer whose start differs from the Agreement's, or whose end is later, is
conflicting timing; an earlier committed end is accepted, since only truncation moves a
lease's end. Late settlement shortens service and never moves the end.

Capacity is committed at settlement. Before the start nothing physical, financial or
disclosed happens: `drive` returns `waiting(wake_at=start)` and releases the
convergence claim, and each storefront's `delivery-recovery` loop brings the deal back
through the family's re-drive ([dispatch and recovery](#dispatch-and-recovery)), as
the settlement servicing worker's ready step also does for a bare-metal Alkahest
deal, rechecking admission, so an end recorded while the deal waited stops it before
dispatch. Hardware is therefore never used outside the window the site admitted, and
the deadline end service measures from `max(committed, start)` measures from where
delivery begins. A provisioning lead time before the start would need the site to
admit and price a wider window, and is not offered.

### Commit and hold adoption

A reserve carries `deal_ref.placement_key = "<negotiation_id>:<placement>"`, under
which the site returns the recorded reservation to an exact replay and refuses a
changed one ([site capacity](../site-capacity/architecture.md#reservation-lifecycle)).
A reservation placed at settlement or recovery uses `:settlement`; VM's acceptance
hold uses `:hold`. A lost settlement acknowledgement therefore replays its own
placement, while a lapsed hold is replaced by a different one.

A live hold is adopted, never duplicated:

| The site's answer to committing the hold | What delivery does |
|---|---|
| Commit succeeds | The hold is the deal's reservation, recorded through the progress port |
| No answer, an unsigned answer, or another status | Retry the commit; never a fresh reserve |
| Refused (404 or 409), and the hold is verified lapsed | Reserve under `:settlement` |
| Refused while the hold was live | Seller failure before dispatch |
| The `:settlement` reserve is refused, finds no capacity, or comes back released | Seller failure before dispatch |

A hold is verified lapsed when its `:hold` replay returns it expired or released, or,
for a hold carrying no key, when its recorded expiry has passed; a keyless hold with no
recorded expiry never is. A `:hold` replay the site refuses, or one that finds another
reservation, means the domain mis-describes its hold (`domain_result_invalid`), and
nothing is released, since the site answers a found and a newly placed reservation
alike. A reservation the site holds is recorded even when an end won meanwhile,
because the end operation releases what is recorded.

Commit authorization comes first, before any reserve or hold adoption, so a commit
end service refuses touches no capacity. Any refusal when no end is due is
`repair_required(no_accepted_deal)`: the payment authority's refusal of the
commitment, which no retry changes, never read from the free-text reason. The refused
deal holds nothing delivery reserved; an acceptance hold the domain placed at
negotiation, VM's under a positive `hold_ttl_seconds`, is left to lapse at its TTL.

End service journals one authorization answer per phase and admission revision: the
first `allow` or `refuse` journaled for a phase at a revision stands for that
revision, and a later drive asking again receives it. A rate deal's payment adapter
reads a fresh signed snapshot every time, so its answer can change while the revision
stands still — a slow or stale read, or a stop the payment watch has not yet
recorded. End service then answers `pending`, journaling nothing, and the path
returns `pending` with nothing further done, so a later drive asks again. A changed
answer therefore only holds a phase back, never advances one: the watch's record of
an end moves the revision, and admission then answers. Once the delivery deadline
passes, end service's deadline rule, behind its payment observation barrier, records
seller non-delivery and journals the filing; the path answers `pending` while
admission awaits that observation. A refusal by end service is not a site refusal:
only the site's refusal of a commit enters [the end hand-off](#the-end-hand-off).

### Dispatch and recovery

Dispatch is recorded through the progress port before `begin_fulfillment` is called.
A recorded dispatch with no fulfillment identity repeats the same request, which
provisioning answers with the fulfillment it already accepted for the reservation; a
recorded fulfillment is polled and never replaced. Every drive past dispatch asks
admission before polling, so a create that never settles cannot outlast a due end or
the window. Each lost acknowledgement recovers the same resource: reserve through the
placement key, dispatch through the recorded step and identity, activation by
repeating it for the same reservation, billing start under the same key.

A delivery that waits, defers or loses its caller is driven again by one routine,
`recover_deliveries` (`compute_delivery.recovery`), which each storefront's
`delivery-recovery` loop runs over three ports its domain fills (`DeliveryRecovery`):
`unfinished_deliveries`, the deals whose delivery started and has not finished;
`claim`, the deal under the domain's own serialization; and `revalidate`, its
settlement stage's re-check of the deal's evidence against its authority. The routine
owns the order — list, claim, re-check, drive — so the two domains cannot drift apart
in it, and the path's own reconciliation decides what each drive does. A deal is
driven only when the claim admits it and its evidence re-checks, since every drive
may take a protected step: a deal another worker holds, or whose evidence does not
re-check, an unreachable authority included, waits for a later pass, and a failure on
one deal is logged without holding back the rest.

VM supplies its incomplete-deliveries query, its durable claim lease, held for the
re-check and the drive, and its selected stage's evidence re-check, and drives
through `drive_vm_delivery`, the drive its hook runs, which records the outcome in its
delivery record and runs the seller's failure policy. Bare metal supplies its
lifecycle-row query, an answer whether the deal's lock is free, since its hook takes
that lock for the drive itself, and its settlement service's `verified_evidence`, the
accepted entry's recovery gate, and drives through its fulfillment service's
`deliver`, and so through the hook, which runs the same gate again before the drive.

### Activation, then billing, then availability

After ready evidence the path activates the lease through `CapacityEffects`, records
the site's `activated_at_utc` (whole seconds) once, and leaves the lease's end alone,
so an earlier truncation stands. A 409 is read through the compute contract's
`LeaseView`: `releasing` or `released` is a lapsed activation for the end hand-off;
anything else is `activation_unexplained`. A 404, an unsigned answer or an unreachable
site is `site_unanswered`: the site has not activated, and the deal is retried. There
is no compatibility path for a site without activation, because storefronts and sites
are upgraded together ([`ARCHITECTURE.md`, "Operators"](../../../docs/development/ARCHITECTURE.md#operators)).

Billing start calls `EndService.begin_billing` under `<negotiation_id>:billing-start`
with a `DeliveryEvidence` whose `ActivatedDeliveryRef` names the capacity reservation
and the site's instant, and whose ready reference the domain port builds. The path
keeps no billing intent: end service journals the one intent, and recovery repeats the
call under the same key. Two guards precede it: while the site's activation instant
is ahead of this storefront's clock the deal stays pending, since end service refuses
an activation in its own future; and ready evidence that differs from what billing
start already journaled is `domain_result_invalid`, since end service refuses a retry
whose evidence changed. A once-only adapter's billing start is a no-op.

`available` means readiness, activation, billing start and disclose authorization are
durable, without any buyer read. `converged` adds that the domain's continuation is
acknowledged, or that it has none.

### An end after availability

An end due after availability does not stop the continuation, which settles service
already delivered: an Alkahest claim stopped by an end would leave the escrow to the
buyer's reclaim, a refund the once-only mechanism does not grant. Every drive of an
available deal runs the continuation, then reconciles a due end: `pending` while the
continuation is unacknowledged, then `ended` once it is acknowledged or the domain has
none. No delivery failure is recorded beside such an end, and the path does not drive
the physical end while the continuation is pending, since the route that recorded the
end already drives it.

### The end hand-off

Before availability, a refusal, provisioning failure, elapsed window or lapsed
activation enters end service's `record_end` in one transaction that runs admission
first, retains the observed failure as a `seller_assertion` evidence item under a
source fixed by what failed (`delivery:commit-refused:<reservation>`,
`delivery:fulfillment-failed:<fulfillment>`, `delivery:activation-lapsed:<reservation>`,
`delivery:window-elapsed:<negotiation>`), and records the end with its never-delivered
`delivery_end` filing acting no earlier than the Agreement start. An earlier lawful end
already due controls the classification instead, with no filing. The path then ends
the physical side through end service's no-dispatch path under the terminate intent's
key; a failure there leaves the intent pending for the next drive to repeat. The path
computes no amounts, sends no payment stop or reverse, and never dispatches the filing:
the seller half's servicing does. A buyer's lawful end reaches end service through its
own route; the path's next admission ends the deal, and it records nothing of its own.

## The access check and credential-capable routes

`ComputeDeliveryPath.read_access(negotiation_id, fetch)` requires `available` or
`converged`, the Agreement start reached and admission for `disclose`; it calls
`fetch` with the fulfillment and reservation identities outside any transaction, then
admits `disclose` again at the current instant — at the revision admitted before the
fetch and at the current one if it changed — and discards the fetched material if an
end won. A truncation still in the future discloses. No payment adapter is called, so
a credential read reaches no payment authority. Physical teardown revokes material
already disclosed; nothing claims to retract a response already in flight.

Each compute storefront declares its credential-capable routes beside their operation
names — VM's `settle` and `settle-status`, bare metal's `access` and `status` — as a
map from operation to the response members holding access material. Its response
middleware records those routes' outcomes without that material, and an exact retry
runs the route again instead of replaying, so after an end it is refused with a
signed answer ([marketplace identity](../marketplace-identity/spec.md)). An exact retry
of VM's `settle` resumes the same stage operation and rebuilds only its
acknowledgement's access part. The declaration is data in each storefront's own
middleware, so the shared middleware that later replaces them reads the same
declaration. Core's replay table records no route, so each storefront clears access
material from recorded bodies by shape at startup (see
[`DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup)).

## Domain compositions

| | VM | Bare metal |
|---|---|---|
| Entry | Core's `fulfill_domain` hook, from payment settle and the Alkahest settlement job's fulfill step; the re-drive calls `drive_vm_delivery`, the hook's own drive, directly | Core's `fulfill_domain` hook, through the fulfillment service's `deliver`, from payment settle, the Alkahest ready step, the re-drive and a status read; the hook refuses without the storefront's lifecycle in `domain_input` |
| Progress row | `vm_delivery_records` | `bare_metal_fulfillment_lifecycle` |
| Hold | Its acceptance hold, placed under `:hold` with its exact request recorded | None; reserves carry `escrow_uid` beside the placement key |
| Scheduling | Inside its `SiteFulfillment.begin_fulfillment`, because its request names no resource | In `fulfillment_request`, before the dispatch authorization, because its request names the assigned resource; assignment is idempotent by reservation and is not provider execution |
| Ready evidence | `vm.connection-details.v1` over the endpoint, readiness and resource identities | `bare_metal.ssh-access.v1`, a digest of the SSH endpoint, tenant account and readiness |
| Continuation | The Alkahest stage's claim; recording connection details and the fulfilled listing | Recording the result and receipt; for Alkahest, whether settlement recorded the obligation's fulfillment |
| Recovery worker | The `delivery-recovery` loop's re-drive over its incomplete-deliveries query and claim lease, revalidating through the selected stage's `recover_evidence` | The `delivery-recovery` loop's re-drive over its lifecycle-row query and per-deal lock, revalidating through `verified_evidence`; the settlement gate revalidates (rechecking the Alkahest chain) on every drive |

Each storefront's payment-adapter table holds `kit/alkahest`'s once-only adapter with
its own commitment validator, because the commitments differ: VM's is the escrow
reference and its evidence carries a schema version, bare metal's is the Agreement
digest and its evidence compares the Agreement bytes. A bare-metal status read drives
a deal whose fulfillment is active and not yet available before answering, so the
administrator's settle wait and a buyer's status read reach availability; its access
read does not drive. Both storefronts' settle waits take `ended` as terminal for a
deal whose end took effect before delivery.

## Current limits

- End service's `record_end` takes the caller's classification, so the path, like
  VM's failure action and bare metal's lifecycle, chooses between its observed seller
  failure and an earlier lawful end that is due by reading the final-request journal
  itself. Moving that choice behind an end-service method is unowned work recorded in
  the [change index](../../changes/README.md).
- A drive whose own call reaches availability with an end already due returns `ended`,
  or `pending` then `ended`, which a hook maps to failed for a deal that was delivered.
  It needs an end falling due between the disclose authorization and the continuation
  in one call, and the end is durable by then.
- The lanes show a restart as one recovery-loop step and a seller failure before
  dispatch as a settlement placement that finds no capacity; acknowledgement gaps and
  a refused live commit are proven by library and application integration, since no
  lane control injects them ([`deal-scenarios.md`](../../../docs/guidance/repository/deal-scenarios.md#the-discipline-every-scenario-follows)).
- A payment deal's `delivery_end` filing is not dispatched in a lane until the lanes
  run a mediation double; an Alkahest deal's filing is unsupported.

## Related contracts

- [Deal lifecycle](../deal-lifecycle/spec.md) — end service, admission, authorization
  and billing start
- [Site capacity](../site-capacity/spec.md) — the placement key and activation
- [VM storefront fulfillment](../vm-storefront-fulfillment/spec.md) and
  [physical provisioning](../physical-provisioning/spec.md) — the two compositions
- [Fulfillment](../fulfillment/spec.md) — the provisioning result read
