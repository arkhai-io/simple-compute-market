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
`provisioning/compute` for physical provisioning. It depends on the compute
contracts, the neutral lifecycle kits (`kit/deal-lifecycle`, `kit/deal-servicing`),
`kit/capacity-publication` and `kit/fulfillment`, never on a storefront.

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
- `ComputeDeliveryDomain`, what only the domain knows: its reserve claim, its exact
  fulfillment request (VM's fulfillment context, bare metal's materialization), its
  ready evidence from a fulfillment result, and its continuation after availability
  (an Alkahest claim, evidence publication), or none.

The library exposes one operation, `drive(negotiation_id) → DeliveryOutcome`, with
outcomes `waiting(wake_at)`, `pending`, `repair_required(reason)`, `available`,
`converged` and `ended`. Each domain's fulfillment hook (D3), each domain's
existing recovery worker (D4) and `kit-owned-listing-and-fulfillment-lifecycles`'
convergence worker call it; the hook maps the outcome to `fulfilled`, `deferred` or
`failed`.

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
replay bodies of the declared credential routes (D5). Bare metal — add
`bare_metal_fulfillment_lifecycle.activated_at_utc`, as its migration 0013 added
columns to the same table. The live credential read ships in the same release as
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
declaration and redoes nothing here. Core does not change.

Rejected: leaving replay to `redesign-authenticated-requests`, which leaves the
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
`<negotiation_id>:hold` and settlement or recovery passes `<negotiation_id>:settlement`.
A known-lapsed hold is therefore replaced by a different placement, while a lost
settlement acknowledgement replays its own. Delivery validates the returned
reservation against its request; an expired or released result is repair-required or
the end hand-off (D11), never a fresh hold. Both domains recover through this key;
bare metal keeps `escrow_uid` and drops its full-list scan of the site's reservations.

This is the reserve-replay slice `capacity-reservation-lifecycle-hardening` designed
(`openspec/changes/capacity-reservation-lifecycle-hardening/design.md`), folded in
here; that change keeps expiry indexing and retention.

Rejected: waiting for that change, which no one has started; a storefront lookup
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
replacement placement that finds no capacity — is a seller failure before dispatch:
`record_end` with the seller-failure classification and the `delivery_end` filing at
the Agreement start, and the reservation released through end service's no-dispatch
path, an unknown release acknowledgement retried under the same key and never
replaced by a new reservation. The refusal for an accepted delivery deadline beyond
the pool's policy is `renewable-compute-lease-deadlines`' to produce, consuming this
classification. Dispatched work is adopted and ended, never replaced; the site's
end report is intent and evidence, not proof of release.

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
| Capability index | `openspec/specs/README.md` adds `compute-delivery` |
| Goal and campaign currency | `docs/development/ROADMAP.md` Goal 8; `openspec/changes/README.md` |
