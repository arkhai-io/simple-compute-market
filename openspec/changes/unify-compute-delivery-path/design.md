# Design — one compute delivery path

## Context

The post-commitment lifecycle (`agreed-evidence-and-early-termination`, archived
2026-11-03) and the site's lease activation (`activate-compute-leases-at-the-site`,
archived 2026-11-06) are implemented on this branch. Between them they already give
both compute storefronts:

- a per-deal `servicing_delivery` record in each storefront's own database, holding
  the Agreement start and term end, the verified commitment instant, the accepted
  `delivery_deadline_seconds`, `available_at`, the delivery phase and a revision
  (`kit/deal-servicing/src/market_deal_servicing/journal.py`, `DeliveryRecord`);
- revision-bearing admission that refuses a protected step once an end is due, and
  establishes non-delivery with its filing when `available` misses
  `min(term_end, max(start, committed) + delivery_deadline_seconds)` (`EndSession.admit`);
- `EndService.authorize_delivery` and `EndService.begin_billing`, with the billing
  intent journaled once per deal (`kit/deal-servicing/src/market_deal_servicing/end.py`);
- `record_end` with its atomically journaled `delivery_end` filing, and the physical
  end driven through each domain's `DomainEndPort`;
- the site's `activate_lease`, reachable only through the storefront's guarded
  `CapacityEffects`, writing `activated_at_utc` once from the site's clock.

Both domains already order admission in the same transaction as their own progress
rows: VM's `vm_delivery_records` (`domains/vms/storefront/src/market_storefront/payment_repository.py`)
and bare metal's `bare_metal_fulfillment_lifecycle`
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/migrations.py`).

What is still missing or divergent:

- No storefront calls `authorize_delivery`, `begin_billing` or `activate_lease`.
- VM substitutes the current time for a missing start (`_parse_start_utc` in
  `services/vm_fulfillment_service.py`) and an hour for a missing duration
  (`services/fulfillment_resume_runtime.py`). Bare metal commits the Agreement window
  from its servicing record on its live path; commit-from-now survives only in its
  registered core hook `fulfill_bare_metal`, which builds its service without a
  lifecycle (so also without admission) and which nothing calls.
- Only VM enters fulfillment through core's `fulfill_domain`; bare metal's payment
  settle and Alkahest continuation call its service directly.
- Both domains dispatch a deal whose Agreement starts later as soon as it settles.
- VM stores the tenant password (`vm_delivery_records.tenant_credentials` and core's
  `credentials` table) and serves the stored copy from `settle` and `settle-status`.
- Both storefronts keep authenticated response bodies in the replay store, and an
  exact retry receives the recorded body, credentials included, after an end.
- `kit/site`'s `reserve` is idempotent only on `deal_ref.escrow_uid`. VM's settlement
  and recovery reserves carry no `escrow_uid` and no TTL, so a reserve whose
  acknowledgement is lost is reserved again, leaving an orphan that never expires.
- No Alkahest payment adapter exists, so `authorize_delivery` would refuse every
  Alkahest deal, although `deal-lifecycle` requires an explicit no-financial-action
  composition for current Alkahest.

## Goals / Non-Goals

**Goals:** one compute-family implementation of the delivery order for both domains;
the Agreement's window on every commit and recovery; nothing physical, financial or
disclosed before the Agreement start; activation before billing start and
availability; recovery of every step without a replacement resource; a classified
hand-off of an undelivered deal; no credential disclosed after a locally admitted
end, exact retries included.

**Non-goals:** a second end service, payment journal or dispute policy; renewal; the
site's delivery deadline and its switch; a provisioning lead time before the
Agreement start; extracting the storefront authentication middleware into a kit, or
redesigning the replay store; an Alkahest dispute adapter; the rate hook and rate
servicing.

## Decisions

### D1 — One family path behind domain ports; progress stays in each domain's row

The path is a library distribution at `domains/compute/delivery` (source
`compute_delivery`): a compute specialization, the family's kit for delivery beside
`provisioning/compute` for physical provisioning. It depends on the provisioning
family's wire contracts, the neutral lifecycle kits (`kit/deal-lifecycle` and its
contracts, `kit/deal-servicing`), `kit/capacity-publication`, the site client, the
core carriers and the identity kit, never on a storefront; it imports nothing from
`arkhai-compute` or `kit/fulfillment`, so it declares neither.

It owns the order of delivery — window derivation, the future-start wait, commit,
dispatch, readiness, activation, billing start, availability, the end hand-off,
recovery decisions and the access check — and keeps no table. Each storefront
contributes two ports, `typing.Protocol`s the library declares and calls, and passes
its implementations in when composed, as each already implements the foundation's
`DomainEndPort`:

- `DeliveryProgress`, over the domain's existing progress row, read and written in
  the caller's transaction: load the reservation and fulfillment identities, the
  step and `activated_at_utc`; record the reservation, the dispatch (before
  `begin_fulfillment`), the fulfillment and the activation, each written once.
- `ComputeDeliveryDomain`, what only the domain knows: its reserve claim, its
  accepted acceptance-time hold if it has one (VM's; bare metal has none), its exact
  fulfillment request (VM's fulfillment context, bare metal's materialization), its
  ready evidence from a fulfillment result, and its continuation after availability
  (an Alkahest claim, evidence publication), or none.

As built, `ComputeDeliveryDomain` also answers `accepted_deal`: the deal's verified
settlement as its commitment reference, the listing's durable capacity binding that
selects the site, and the payment adapter the storefront's table resolves, or none;
`DeliveryProgress` also releases the domain worker's convergence claim on a deal that
waits; and the library declares `SiteFulfillment`, the provisioning family's begin,
status, result and lease reads routed by site, which each storefront adapts its own
client to. Progress methods take the connection of the transaction the library opens
on end service's database, where both domains' rows already live. The site client
supplies the refusal and unsigned-answer errors the library classifies.

The library exposes one operation, `drive(negotiation_id) → DeliveryOutcome`, with
outcomes `waiting(wake_at)`, `pending`, `repair_required(reason)`, `available`,
`converged` and `ended`. Each domain's fulfillment hook (D3), each domain's
existing recovery worker (D4) and `kit-owned-listing-and-fulfillment-lifecycles`'
convergence worker call it; the hook maps the outcome to `fulfilled`, `deferred` or
`failed`.

`drive` fails closed on what it cannot read, rather than leaving each port
implementation to decide:

- A deal with no `servicing_delivery` record or no verified settlement evidence is
  `repair_required(no_accepted_deal)`, and nothing is written.
- An accepted deal with no progress row is a first drive: the row is created under
  admission for `reserve`, as both domains create theirs from verified settlement
  evidence today.
- An unknown stored step, a malformed or conflicting recorded identity, a port
  result of the wrong kind, or an empty fulfillment result is `repair_required` with
  its reason. The recorded resource is kept; nothing is reserved, dispatched,
  activated or recorded available on it.

`repair_required` carries a reason from a closed set the `compute-delivery`
specification names: `no_accepted_deal`, `timing_invalid`, `progress_unreadable`,
`domain_result_invalid`, `activation_unexplained` and `site_unanswered`. Every
`repair_required` and `ended` outcome carries the deal's recorded reservation and
fulfillment identities and the reference of the authority evidence it rests on — the
site's signed answer or the end record — so a repair or an end report can be
explained without re-reading the deal. Six outcomes suffice: a first drive is the
start of the normal path, and a missing deal and unreadable progress ask the same of
a caller, which the reason distinguishes.

Each progress table gains one nullable column, `activated_at_utc`: the instant the
site returned when it activated the lease. The site writes its value once and never
changes it, so the copy records the acknowledged answer and cannot drift; it gives
`begin_billing` its instant without another site read and tells recovery whether
activation was acknowledged. Every other fact has a home already: the window,
commitment instant, deadline, wake time and `available_at` in `servicing_delivery`;
authorization decisions and the single billing intent in `servicing_intents`; the
reservation and fulfillment identities in the domain row; convergence in the
domain's existing fields. VM's stored `fulfillment_phase` value `activate`, which
means "the provider reported active", becomes `ready`, so "activate" names only the
site's transition.

The two ports are the seam a later change moves behind when it merges the two
domains' progress rows into one family record; the path's code does not change then.
A third compute domain contributes its two port implementations and changes nothing
in the library.

Rejected:

- **A new family delivery record** with the domain rows as read-only projections: a
  third copy of the window and identities beside `servicing_delivery` and the domain
  rows, which keep VM's context and bare metal's materialization anyway, and a
  cutover with a writer-floor bridge release that reverses the repository's schema
  rule.
- **Extending the foundation's `servicing_delivery`** with reservation, fulfillment
  and activation fields: makes end service the owner of physical delivery progress,
  widening a repository-wide kit that API credits composes and that `ARCHITECTURE.md`
  gives end, admission and filing journals only.
- **Wiring each domain separately**: keeps two implementations of the order.

### D2 — Existing databases upgrade by additive startup migrations

Each storefront's migration list gains, in the release that ships the code needing
it: VM — add `vm_delivery_records.activated_at_utc`; rename stored
`fulfillment_phase='activate'` to `'ready'`; clear `tenant_credentials`, the core
`credentials` rows written for VM listings, and the access material in recorded
replay bodies (D5). Bare metal — add
`bare_metal_fulfillment_lifecycle.activated_at_utc`, as its migration 0013 added
columns to the same table, and clear the access material in recorded replay bodies.

Core's replay table records no route, so a recorded body's route cannot be known.
Each storefront's migration therefore clears access material by its shape, over every
recorded body in core's `auth_replay_reservations`: VM removes the `tenant_credentials`
member, and bare metal removes `host`, `port` and `username` from a body whose
`method` is `ssh`, the shape of its access response. Those fields appear in no other
route's body. A stripped body is still a recorded body, so its row stays completed and
its exact retry still resolves to the recorded operation. A storefront migration
editing rows of a core table is the same shape as clearing core's `credentials` rows
above. The live credential read ships in the same release as
the clearing, so no running deal is left unreadable.

In-flight deals continue on their existing rows. A deal already `available` before
the upgrade is never activated retroactively; its null activation means only that
none is recorded, as the site's own rule says. The repository's rule that
incompatible seller evidence and delivery schemas require fresh databases is
untouched, because these changes are compatible.

Rejected: a bridge release with a writer floor and operator acknowledgement, needed
only by the rejected new record; a fresh-database reset, which the repository
reserves for incompatible schemas.

### D3 — Both domains enter delivery through core's fulfillment hook

Bare metal's payment settle and its Alkahest continuation call core's `fulfill_domain`
with a `StorefrontFulfillmentContext`, as VM's do. `fulfill_bare_metal` stays the
module-level hook registered in the domain contract and builds its service — and,
under D1, the shared path — from the clients in `ports` and the runtime's lifecycle
in `domain_input`, replacing today's lifecycle-less construction. Core's identity
check then runs on every bare-metal delivery, and the only registered entry is the one
that admits and commits the Agreement window. Callers that read the begin result's
state read it from the returned `StorefrontFulfillmentLifecycle`, the bare-metal row
travelling as `domain_result`.

No core code or type changes: `ports` and the opaque `domain_input` already carry
everything bare metal needs, as VM passes its failure policy through `domain_input`.

Rejected: keeping bare metal's direct calls and deleting the dead hook, which leaves
two entry routes and core's identity check VM-only; leaving the hook in place, which
keeps a registered path that skips admission.

### D4 — A deal that starts later commits at settlement and waits for its start

Every commit and recovery uses `Agreement.start_utc` and `start_utc +
duration_seconds` under the same reservation identity. There is no now-start, no
default duration and no replacement resource for missing or conflicting timing,
which is repair-required. Late settlement shortens service and never moves the end.

Capacity is committed at settlement. Before `start_utc` nothing physical happens:
no dispatch, activation, billing start or disclosure. `drive` returns
`waiting(wake_at=start_at)` and releases the convergence claim; each domain's
existing worker brings the deal back — VM's periodic resume pass for payment deals,
the servicing worker for Alkahest deals in both domains, `BareMetalLifecycle.cycle`
for bare-metal payment deals — and the path rechecks admission on waking, so an end
recorded while the deal waited stops it before dispatch.

Hardware is never used outside the window the site admitted, so a back-to-back
predecessor on the same capacity is never disturbed; billing and activation never
precede the start the buyer accepted; and the foundation's deadline, anchored at
`max(committed, start)`, measures from where delivery begins. Provisioning time falls
inside the window, as for every deal that starts immediately.

Rejected: provisioning at settlement, which uses unadmitted capacity and bills or
activates before the start; a lead time `L` before the start, which needs the site to
admit and price `[start − L, end]` and is a separate change if wanted; deferring,
which would run this change's new activation and billing calls before the start.

### D5 — Credentials are read live, and credential responses are not replayed

VM `settle` and `settle-status` fetch the endpoint and account live from
provisioning's fulfillment `result` read, through the path's access check, as bare
metal's `access` already does. VM stops writing `tenant_credentials` and core's
`credentials` rows; D2 clears the existing copies.

The access check requires `available` (or `converged`), the Agreement start reached
and admission; it fetches outside any transaction, then rechecks the revision and
due end before the response is signed, discarding the fetched bytes if an end won.
Physical teardown revokes material already disclosed; no claim is made about bytes
already in flight. No payment snapshot is read on an access request.

The credential-capable routes — VM `settle` and `settle-status`, bare-metal `access`
and `status` — are declared as such beside their operation names. The VM and
bare-metal response middleware record their outcomes without access material, and
an exact retry of a credential read runs the read again through the access check, so
after an end it is refused with a signed answer. An exact retry of VM `settle`
resumes the same settle operation and rebuilds only the access part of its answer.
Request reservation, first-use skew, changed-request rejection and response signing
are unchanged. The declaration is `marketplace-identity`'s per-route exact-retry
resolution; `redesign-authenticated-requests` generalizes it with this declaration's
clauses kept.

Placement: the access check is the family library's, composing the neutral admission
of `kit/deal-servicing` and the result read of `kit/fulfillment`; it is not a
repository-wide kit, because API credits composes no seller half, admission or
availability record today. Stopping VM's storage is a VM-only edit. The replay
exclusion is a minimal edit in each compute storefront's middleware, driven by the
declaration as data, so that `kit-owned-storefront-auth-and-persistence`, which owns
collapsing the three storefronts' middleware into one set, reads the same
declaration and redoes nothing here. Core does not change: the middleware knows the
route's operation both when it records an outcome and when it resolves an exact
retry, so the declaration needs no route column in the replay table, and a body with
its access material stripped is non-null, so the row records a completed outcome as
before. Records written before the upgrade are cleared by shape (D2).

Rejected: a route column and a body-free completed state in core's replay table,
which costs a core schema and API edit and still identifies no record written before
it; leaving replay to `redesign-authenticated-requests`, which leaves the
password replayable and at rest in the replay table until it lands; keeping stored
credentials behind a guard, which keeps three copies of the secret at rest and the
domains divergent; a core retry policy now, which designs ahead of the change that
owns it; extracting the middleware into a kit in this change, which adds API credits,
a kit and the storefront shell's open questions as a prerequisite; a shared
credential-route helper in the delivery library, which would put authentication in a
delivery library and move twice.

### D6 — Reserve replay is keyed by the deal's placement at the site

`kit/site`'s `reserve` accepts `deal_ref.placement_key = "<negotiation_id>:<placement>"`
as an idempotency key beside `escrow_uid`. An exact replay under that key returns the
recorded reservation in whatever state it is in — held, committed or released — and
a replay that changes the claim, pool, site, offering mode or window is refused with
nothing written. The key is optional and lives in `deal_ref`, so older callers are
unaffected and no wire version changes.

The placement names the purpose: VM's acceptance-time hold passes
`<negotiation_id>:hold`, and a reservation placed at settlement or recovery passes
`<negotiation_id>:settlement`. A known-lapsed hold is therefore replaced by a different
placement, while a lost settlement acknowledgement replays its own.

A live hold is adopted, never duplicated. When the domain supplies an accepted hold,
delivery commits it under the deal before anything else, as VM's settlement does
today:

| The site's answer to committing the hold | What delivery does |
|---|---|
| Commit succeeds | The hold is the deal's reservation, recorded through the progress port |
| No answer, or an unsigned one | Retry the commit; never a fresh reserve |
| Refused, and the hold is verified lapsed | Reserve under `:settlement` |
| Refused while the hold was live | D11's seller failure |
| The `:settlement` reserve is refused | D11's seller failure |

A hold is verified lapsed when the replay under `:hold` returns it expired or
released, or, for a hold placed before the upgrade and so carrying no key, when its
recorded expiry has passed. Today's fallback to a fresh reserve on any commit error
is removed: a commit whose answer was lost may have succeeded, and a second
reservation beside it is the orphan this decision exists to prevent.

The site records, beside the key, the request it was admitted for — resource type,
claim attributes, offering mode, dimensions, and the window as asked (its start and
duration) — and judges a replay against that record, not against the row: commit and
truncation move the row's window after admission, and the exact replay of a
truncated lease must still find it. The hold's TTL is not part of the request. A
refused replay answers 409, a malformed key 422. A keyed reserve whose `escrow_uid`
already holds a reservation placed without a key adopts it under the key, so a
bare-metal deal reserved before the upgrade is found by its key once released;
one held under another key is refused. A resize records no key on its new row.

Delivery validates the returned
reservation against its request; an expired or released result is repair-required or
the end hand-off (D11), never a fresh hold. Both domains recover through this key;
bare metal keeps `escrow_uid` and drops its full-list scan of the site's reservations.

This is the reserve-replay slice `capacity-reservation-lifecycle-hardening` designed
(`openspec/changes/capacity-reservation-lifecycle-hardening/design.md`), folded in
here; that change keeps expiry indexing and retention.

Rejected: a site operation converting a live hold into a settlement placement in one
step, which adds a site operation and wire surface for what the existing commit and
the `:hold` replay already establish; waiting for that change, which no one has
started; a storefront lookup
before reserving again, which reads every reservation at the site, cannot refuse a
changed request and leaves a race with a dying process's request; deferring, which
would keep VM's orphaned reservations on a recovery path this change rewires.

### D7 — A site that cannot activate has not activated

Storefronts and sites are upgraded together (`ARCHITECTURE.md`, "Operators"), and the
activation change keeps no compatibility path for a site without activation. A
caller that cannot activate — an unknown route, an unsigned answer, an unreachable
site — has not activated: the delivery stays repair-required and is retried, and
nothing treats the lease as active. `renewable-compute-lease-deadlines` owns its own
switch and enablement independently; this change wires every caller through the
typed contract so that enablement needs no caller edit.

Rejected: a no-op for a site without the route, keyed on a signed view lacking
`activated_at_utc` — the activation change's rejected D4.

### D8 — Activation goes through `CapacityEffects`; a refusal is read through `LeaseView`

After ready evidence, admission for `activate`, and no earlier than the Agreement
start, the path calls `CapacityEffects.activate_lease` for the binding's site. On 200
it records the site's `activated_at_utc` through the progress port and adopts the
lease's current end, an earlier truncation included; activation never extends or
restores an end. On 409 it reads the lease through the compute contract's `LeaseView`
(`get_lease`, as bare metal's site recovery already does): a `releasing` or
`released` lease goes to the end hand-off, anything else is repair-required. On 404
the delivery is repair-required. A retry after a lost acknowledgement is safe,
because activation is idempotent by reservation identity.

### D9 — Billing start uses the foundation's delivery types as built

After activation and a `start` authorization, the path calls
`EndService.begin_billing(operation_key, evidence)` with a stable key and a
`DeliveryEvidence` carrying the negotiation, the commitment, `reservation_ref`,
`fulfillment_ref`, `activated_delivery = ActivatedDeliveryRef(record_ref=<capacity
reservation id>, activated_at=<the site's instant in integer seconds>)` and
`ready = ReadyEvidenceRef(schema_id, resource_ref, digest)`, built by the domain's
port. The reservation identity is the activation's stable reference. Delivery keeps
no billing intent of its own: end service journals the one intent per deal, and
recovery repeats the call under the same key.

`deal-lifecycle`'s requirement "Billing-start intent and evidence have one owner"
describes the bundle as a single `ActivatedDeliveryRef`; its wording is corrected to
name `DeliveryEvidence` and its nested `ActivatedDeliveryRef`, as the code has them.

Rejected: the richer reference with an opaque `(kind, version, payload)` envelope
that an earlier draft assumed the foundation supplied; it does not.

### D10 — Alkahest deals authorize through a once-only adapter in `kit/alkahest`

`kit/alkahest` provides a payment adapter that composes `OnceDeliveryPolicy` with a
validator of the selected stage's typed, versioned commitment evidence, as
`kit/arkhai-payments`' adapter composes it for once-only payments. It supports no
payment commands, so `submit_payment` refuses them, and its billing start is a
no-op that creates no artificial start. Each compute storefront's payment-adapter
table gains the Alkahest entry. A missing entry never implies allow, and an Alkahest
deal's `delivery_end` filing stays unsupported, with its existing recovery and
reclaim semantics.

Rejected: skipping authorization for Alkahest, which breaks `deal-lifecycle`;
placing the adapter in the family library, which would make a family library know a
mechanism its name does not carry.

### D11 — Undelivered deals are handed to the end operation with classified evidence

Before availability, a refusal, provisioning failure, elapsed window or lapsed
activation enters `record_end`. Delivery supplies the actor, cause and source, the
Agreement start, the fixed failure-observation time, the resource identities and the
evidence — verified refusal reasons and payment records, never an event kind — and
consumes the foundation's classification and timing: an earlier buyer, payer-stop or
ruling record that controls the never-delivered basis suppresses the seller's
filing; a clock or a payee stop alone does not erase non-delivery; before a future
start the filing is journaled now and acts at the Agreement start. Delivery computes
no amounts, keeps no second end log and sends no payment stop or reverse; the seller
half files `delivery_end(cause=payee)` through the Agreement's dispute adapter, with
`delivered` taken from the durable `available` record. Late settlement without an
authority-backed cause is never-delivered evidence, not buyer fault.

Any site refusal of the commit after a reservation was made — including a
replacement placement that finds no capacity, but not the refused commit of a hold
verified lapsed, which D6 replaces under `:settlement` — is a seller failure before
dispatch:
`record_end` with the seller-failure classification and the `delivery_end` filing at
the Agreement start, and the reservation released through end service's no-dispatch
path, an unknown release acknowledgement retried under the same key and never
replaced by a new reservation. The refusal for an accepted delivery deadline beyond
the pool's policy is `renewable-compute-lease-deadlines`' to produce, consuming this
classification. Dispatched work is adopted and ended, never replaced; the site's
end report is intent and evidence, not proof of release.

**An end after availability (22 F2, settled in the triage of implementation round
1).** An end due after availability does not stop the domain's continuation, which
settles service already delivered: an Alkahest seller's claim stopped by an end
would leave the escrow to the buyer's reclaim, a refund the once-only mechanism does
not grant. Every drive of an available deal runs the continuation, then reconciles a
due end: `pending` while the continuation is unacknowledged, so the domain's worker
keeps driving, then `ended` through end service's physical end once it is
acknowledged or the domain has none; with no end due, `available` or `converged` as
before. No delivery failure is recorded beside such an end. Rejected: the end
skipping the continuation (the reviewer's first alternative), which loses the claim;
keeping `available` and `converged` for an ended deal and documenting it, which
leaves `drive` misreporting where the deal stands. A drive whose own call reaches
availability with an end already due returns `ended`, or `pending` and then `ended`
on the hook's retry while the continuation is unacknowledged, which a hook maps to
failed for a deal that was delivered; that needs an end falling due between the
disclose authorization and the continuation in one call, and the end is durable by
then. While the continuation is pending the path does not drive the physical end;
the route that records an end already drives it.

### D12 — The specification deltas

- `compute-delivery` (new): D1, D4, D5's access check, D6's use, D7, D8, D9's use and
  D11.
- `vm-storefront-fulfillment` (modified against the current requirements): the site's
  activation joins end service as a writer of the lease after commit; delivery
  converges through the family path; credentials are read live and never stored; a
  step after physical fulfillment includes activation and billing start; the
  credential routes regenerate on exact retry.
- `physical-provisioning`: bare metal enters through core's hook (added).
- `marketplace-identity`: the exact-reuse rule gains the credential-route declaration.
- `site-capacity`: the placement key (added).
- `deal-lifecycle`: D9's wording correction.

Every requirement carries WHEN/THEN scenarios that observe behaviour, never a
restatement of the requirement.

### D13 — Index rows

This change depends on no other change before it proceeds. Its row records that
`add-arkhai-payments-lane-double` gates only the lane runs of the filing and restart
drives, that the reserve-replay slice moved here from
`capacity-reservation-lifecycle-hardening`, and that
`kit-owned-storefront-auth-and-persistence` must honour the credential-route
declaration. Those changes' rows and `renewable-compute-lease-deadlines`' row
(whose deadline-refusal drive is its own) carry matching notes.

### D14 — Implementation cadence

Two rounds, each implemented in two sessions, then closeout.

- **Round 1 — authority and library foundations.** Session 1: `kit/site`'s placement
  key with its `site-capacity` requirement, and the Alkahest once-only adapter in
  `kit/alkahest`. Session 2: the `domains/compute/delivery` library — the ports,
  `drive`, window derivation, the future-start wait, activation, billing start, the
  end hand-off and the access check — proven by family-library integration against
  port fakes and the real lifecycle journal.
- **Round 2 — both storefronts on the path, then qualification.** Session 1: VM — its
  port implementations, its hook running the path, the window fallbacks removed, live
  credential reads with stored copies cleared, replay exclusion for its credential
  routes, its hold using the placement key. Session 2: bare metal — its port
  implementations, entry through core's hook, its migration, replay exclusion for its
  credential routes; then the lane drives across both domains (activation, delayed
  settlement, restart and acknowledgement gaps, a commit refusal), with mediation and
  filing lane runs gated by `add-arkhai-payments-lane-double`.

The site and library contracts are reviewed before either storefront is rewritten.

### D15 — Lane qualification waits for the Agreement's instants, and restarts are recovery steps

Settled while implementing section 8, and ratified by the owner in the triage of
the round's implementation review (39 F1), which restated task 8.3 to this
evidence boundary. The lanes' controls hold and step loops;
none moves the wall clock. A late settlement must be late to the second the
servicing record keeps, and a forward deal must reach its start, so a stage
waits for an instant the Agreement fixes (`wait_until`, bounded), then advances
what acts on it explicitly; `docs/development/TESTING.md`'s stage discipline
admits that one wait. A restart is emulated by one step of the storefront's
recovery loop, what a restarted storefront runs first. VM's canonical deal
cannot be re-driven that way, since its settle call holds the delivery's claim
while provisioning settles, so VM's recovery is shown by the forward deal, which
only the resume pass carries past its start. The lanes reach a seller failure
before dispatch through a settlement placement that finds no capacity; no
existing control loses an acknowledgement or makes the site refuse a live
commit, so those interleavings stay with library and application integration.

Rejected: a requested start in the past to make settlement late, which tests a
deal no buyer asks for; an injected storefront clock, a test seam in every
service for one assertion; fault injection at the site, a new control surface
in `kit/site` for interleavings integration tests already prove.

## Dependencies

- `agreed-evidence-and-early-termination` and `activate-compute-leases-at-the-site`
  are archived; this change consumes their implemented contracts.
- `add-arkhai-payments-lane-double`: only the lane runs of the filing and restart
  drives. Library integration uses the clock-injected payments engine in
  `kit/arkhai-payments` fixtures and the in-process mediation fake; no kit depends on
  runnable tooling.
- This change lands before `converge-ongoing-compute-leases`, which implements the
  rate hook against this path and owns the rate qualification matrix, and before
  `renewable-compute-lease-deadlines`, which adds the site's deadline, supplies its
  anchor through this path's single commit step, and owns its switch.
- `kit-owned-listing-and-fulfillment-lifecycles` consumes `drive` and the access
  check; `kit-owned-storefront-auth-and-persistence` absorbs the credential-route
  declaration into its shared middleware; `redesign-authenticated-requests`
  generalizes the declaration, archiving after this change with a superset block.

## Open Questions

None.

## Design promotion record

Planned destinations, completed at closeout:

| Accepted decision | Permanent destination |
|---|---|
| D1 family path, ports, `drive` | `compute-delivery` spec and architecture companion; `docs/development/ARCHITECTURE.md` "Family kits" and "Fulfillment"; `openspec/specs/fulfillment/architecture.md` (boundary only) |
| D2 additive upgrade | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `vm-storefront-fulfillment` architecture companion |
| D3 bare metal through the hook | `physical-provisioning` spec and architecture companion |
| D4 window and future-start wait | `compute-delivery` spec and architecture companion |
| D5 live access and credential routes | `compute-delivery`, `vm-storefront-fulfillment` and `marketplace-identity` specs; `ARCHITECTURE.md` "Fulfillment status and results" and "Marketplace identity" |
| D6 placement key | `site-capacity` spec and architecture companion; `ARCHITECTURE.md` "Capacity reservation" |
| D7, D8 activation | `compute-delivery` spec |
| D9 billing-start evidence | `compute-delivery` spec; `deal-lifecycle` spec (wording) |
| D10 Alkahest adapter | `deal-lifecycle` architecture companion (adapter composition) |
| D11 end hand-off | `compute-delivery` spec, referencing `deal-lifecycle` |
| 53 F1 the settle wait's terminal `ended` | `compute-delivery` spec |
| D15 lane qualification | `docs/development/TESTING.md` "The discipline every scenario follows", the VM and bare-metal lane entries and "The real-provisioning lane" (written in section 8) |
| Capability index | `openspec/specs/README.md` adds `compute-delivery` |
| Goal and campaign currency | `docs/development/ROADMAP.md` Goal 8; `openspec/changes/README.md` |
