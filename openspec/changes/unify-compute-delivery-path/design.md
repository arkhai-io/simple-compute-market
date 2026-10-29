# Design — one compute delivery path

## Context

This change reconciles Goal 8's delivery design with
`agreed-evidence-and-early-termination` (D6–D10). That frame owns commitment,
lifecycle, end service, final requests, the payment/dispute adapter tables and the
evidence stores. Its authority model wins: buyer guarantees rest on authority records
and kept signed bytes, not on a cooperative storefront's local checkpoints.

The current tree still has distinct paths:

- `domains/vms/storefront/src/market_storefront/payment_settlement.py` verifies a
  receipt, inserts delivery and launches `_provision`. VM derives its lease end from
  Agreement timing. `services/fulfillment_resume_runtime.py` substitutes 3600 seconds
  in two recovery paths when duration is absent.
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/fulfillment_service.py`
  commits from `now`, then persists the returned window and begins fulfillment.
- Both already have refund/admission ordering and durable provisioning identities to
  preserve. The provider-neutral fulfillment aggregate owns physical execution and
  live result reads; it explicitly does not own commercial agreement identity or
  storefront deal state (`openspec/specs/fulfillment/spec.md`).
- The existing VM delivery-priority requirement allows live progress after a failed
  checkpoint; durable admission and external-operation intent must become explicit
  exceptions. Otherwise a restart could repeat a protected effect without its intent.

These are design inputs, not claims that the dependency changes are implemented.
Reverify the composition seams after those changes land, without reopening the
settled authority boundary.

## Goals / Non-Goals

**Goals:** one delivery implementation for both compute domains; the Agreement's
absolute window on every attempt; activation of every delivered lease; durable
protected transitions; an undelivered handoff into the existing end/self-filing path;
no new credential disclosure after the locally admitted end.

**Non-goals:** implementing a second end service, lifecycle route, payment journal,
rate adapter or dispute policy; a billing horizon; active-lease renewal; generalized
settlement-start/evidence-publication unification; an Alkahest dispute adapter.

## Decisions

### D1. Compute-family placement and one delivery record

**Recommendation:** put the path in `provisioning/compute/src/compute_provisioning/`
as a `delivery` module/package beside the existing family mechanisms, with a
storefront-side delivery repository and injected client/port interfaces. It is
compute-family code: it speaks site leases, activation and provisioning results.
Do not put it in `kit/fulfillment`, make the vocabulary-only `domains/compute` own
persistence, or import a storefront or deployed provisioning service into it.
The family module does not read provisioning repositories; it calls the public
provisioning client supplied by composition. If dependency weight requires a later
split, the API remains family-scoped; no new distribution is needed for this plan.

**Recommendation:** keep one delivery record per negotiation in the storefront's
database, also for prepaid deals. It holds accepted timing/site binding, capacity
reservation and fulfillment identities, delivery checkpoints, authorization decisions
and stable external-effect intents/acknowledgements. It does not hold payment balances,
a second final-request log, a financial end instant, credentials or a rate-servicing
state machine. Rate servicing references it by negotiation ID. Existing domain rows
become adapters/projections or are migrated; they must not remain competing writers.

End service in `kit/deal-servicing` remains the one owner of the earliest final
request and its journal. Its narrow admission/domain port coordinates with the
delivery repository. **Recommendation:** implement local admission, checkpoint CAS
and end recording through a shared storefront transaction boundary with a revision
check. Neither generic servicing nor the family path imports the other one's concrete
repository. There is no database transaction across authority or provider I/O.

### D2. The Agreement window survives every retry

Use `lease_start_utc = Agreement.start_utc` and
`lease_end_utc = start_utc + duration_seconds`. Commit/recommit the exact same window
and reservation identity after restart, including the Alkahest path. For rate deals,
terms validation owns `max_term_seconds == duration_seconds`; delivery consumes it,
not a second term codec. The seller's listing bounds have already been materialized
into the Agreement by `negotiate-open-ended-compute-terms`. The earlier recommendation
to consider a prorated provisioning-time credit on prepaid deals remains seller
pricing work for that terms design, not a new delivery/refund rule here.

Bare metal's commit from `now` and VM's two one-hour substitutions are removed. A
missing/invalid timing record is repair-required; it does not invent a new window or
replace a running resource. An elapsed end before delivery takes D5. A late settlement
shortens service rather than moving the seller's absolute bound. Existing in-flight
rows with a resource are adopted by their recorded identity; an irreconcilable old
window is surfaced for repair, never silently recommitted to different terms.

### D3. Authorization composes end admission and payment policy

`authorize_delivery(deal, phase)` runs before `commit`, `dispatch`, `start` and
`disclose`. The `disclose` phase admits initial availability, not each subsequent
credential read; those use D7's recorded local guard. Each decision records
negotiation, phase, attempt/operation identity,
allow/refuse/pending outcome, reason and evidence references before the caller uses
it. A refused transition takes D5 where delivery has not become available; `pending`
or an unknown authority result stays pending and resolves through the owning
adapter, never by assuming refusal or success. A decision applies to one transition
attempt, not permanent authorization for all later retries.

Every transition also uses end service's admission port, including reconciliation and
restart. The final request is not copied into a hook-owned log. A fresh financial
allow is insufficient if end service refuses admission; a request that wins after
dispatch makes recovery adopt and end that fulfillment under the existing lifecycle
rule. The path owns the call sites; `agreed-evidence-and-early-termination` owns
"delivery admission ordered against final requests" and how the earliest request wins.

The default prepaid hook performs no additional financial work and answers allow
once recorded. It does not bypass existing commitment-evidence validation or local end
admission, and a `once` part acquires no artificial `start` event.

The rate implementation belongs to `converge-ongoing-compute-leases`, using the
payment adapter from `spot-deals-through-arkhai-payments`:

- At commit/dispatch, verify the payment authority's commitment/reservation and
  start/stop records, not a horizon. Before `start`, approval reserves the first batch;
  a missing funded-through time on an unstarted part is not a refusal by itself.
- At `start`, verified provisioning evidence is supplied (commit and fulfillment
  identities plus the provider's ready result and evidence digest, no credentials).
  The hook journals and issues payee-only `start` through the seller half/payment
  adapter; `started` requires the verified authority record. An unknown outcome is
  resolved under that same operation key, not a second start.
- At disclose, verify the recorded start and the authority's current stop/pending-stop
  records, plus local delivery eligibility. A future pending stop is not an immediate
  end: its effective instant is authority-hosted, and `watch`/end service own action
  at that instant. Do not locally schedule an authority stop or override its notice.

This describes the seam's obligations, not a second implementation of rate mechanics.
There is no payee vouch or renewable billing horizon. Payment truth is the authority's
verified records read by the adapter. A remote stop can race any read; the local
admission check does not claim atomicity with a remote authority.

### D4. Checkpoints and effect intents are different

The delivery checkpoints advance on acknowledgements, while an effect intent with
its stable key is persisted **before** each external call. This avoids calling a
checkpoint "activated" before the site has acknowledged it. Provider-ready is
separate from buyer-available. The names are storefront delivery state, not the
provisioning aggregate's `active` or the seller half's lifecycle-state vocabulary.

| Checkpoint | Meaning | Recovery obligation |
|---|---|---|
| `authorized` | commit gate and exact commit intent recorded; no resource dispatched | reconcile/retry the same commit; repeat admission and the dispatch gate before dispatch |
| `dispatched` | fulfillment acceptance/dispatch acknowledged under its recorded identity; provisioning may still be pending | query/adopt that fulfillment; an unacknowledged dispatch intent is resolved with the same reservation/request, never a replacement |
| `started` | ready provisioning evidence validated and the start gate acknowledged; rate start verified at the authority, prepaid financial step a no-op | resolve the same start operation, recheck end admission, then retry activation |
| `activated` | site acknowledged activation to the agreed end | a lost activation acknowledgement is retried idempotently; expiry instead takes D5 |
| `available` | disclose gate passed and service readiness recorded durably | no buyer read is needed; continue toward steady state unless end service has ended it |
| `active` | normal delivery convergence complete | ongoing servicing owns observation; credential reads still enforce D6 |

The actual order is commit gate/commit, dispatch gate/dispatch and provision, start
gate/start, activate, disclose gate/availability, active. `authorized` is **not** an
early disclose authorization. External-operation keys and admission revisions survive
restart; local claim expiry permits recovery but not duplication. At each adjacent
checkpoint and each intent/ack gap, recovery reads authoritative state and resumes or
ends the same resource. No network I/O holds the local transaction open.

A required journal/checkpoint failure leaves protected effects pending and loudly
reported. Commercial delivery is not abandoned solely due to bookkeeping failure,
but it cannot proceed unjournaled. Existing physical resources remain adopted while
persistence is retried. This narrows the VM delivery-priority requirement without
weakening its no-abandonment goal.

### D5. Undelivered is an end-service input, not a refund implementation

A terminal delivery failure before `available` records a local final request with
actor, cause and source and supplies the seller half an `exceptional_end(at)` intent,
where `at = Agreement.start_utc`, as D8 of
`agreed-evidence-and-early-termination` requires. Triggers include terminal hook
refusal, provisioning failure, an elapsed Agreement window, and the site's signed
end report showing expiry in `awaiting_activation`.

The final request's physical time is the failure/end time; the intent's `at` is the
deal's start. They are not two competing storefront end decisions. End service owns
the journal that commits the filing with the final request and retries it after a
crash. No dispatch means proof-driven release without teardown; dispatched work is
adopted and terminated through end service's existing domain port. A local failure
does not wait for the payment or dispute authority to recover before ending delivery.

The dispute adapter maps the intent; the dispute authority realizes its outcome as
stop now plus reversal since `at`, within the holds, and applies it. The path sends
no amounts, direct payee stop or refund command. This covers a rate part started but
never made available and the held `once` parts, including a setup part. An already
observed lawful authority stop still goes through end service; it is not replaced by
a seller-created financial instant. Self-filing an undelivered failure does not erase
the stop's actor/cause or supersede the earliest final request.

For deals with no lifecycle/dispute adapter (today's Alkahest), retain the accepted
mechanism's existing failure/reclaim behavior and report unsupported self-filing,
not fictitious authority success. The physical path and activation are still shared.
This change does not create that adapter or promise a new refund guarantee for it.

A cooperative seller files; it is not the buyer's guarantee. A seller who disappears
or refuses still leaves the buyer its own stop/case over held money. Site reports,
authority records and kept signed bytes, not storefront honesty, support that case.
Post-availability site failure uses the lifecycle's actual service-end instant, not
this undelivered-at-start rule; D8 owns that behavior too.

### D6. Activation always names the agreed end

After the start checkpoint and before availability, call the activation operation
from `renewable-compute-lease-deadlines` with the original Agreement end, for reserved,
on-demand and spot deals, including Alkahest. Persist the intent before the call and
retry the same call after a lost acknowledgement. The site stamps the active instant;
the storefront does not infer it from a buyer read. If expiry already claimed the
lease, do not resurrect it: take D5.

The awaiting-activation allowance, deadline/expiry race, signed `lease_ended` report
and site's lapse policy belong to that dependency. The activation deadline becomes
the agreed end for every delivered deal; no rate hook supplies a shorter deadline.
The renewal half is deferred until independently needed by a site operator. These
seller-side deadlines do not cap billing or guarantee recovery when a seller is
adversarial; authority stops, disputes and holds do that.

### D7. Credential reads use local admission, not live payment snapshots

The buyer-authenticated access/result routes require `available` or `active` and
local eligibility under end service's recorded earliest final request. They use the
same local admission ordering as delivery transitions. A due end or an earlier
undelivered failure refuses disclosure, even when provisioning still reports active.
A future final request admits reads only before its time; a local clock check is
still needed if teardown is delayed.

Read provider credentials outside a database transaction, then recheck the delivery
revision/end admission before authorizing the response; discard fetched material
when the check loses to a local end. **Recommendation:** use the shared transaction/
revision seam from D1 as the disclosure linearization point. A read admitted before
an end may already be in flight on the network when that end commits: the guarantee
orders local authorization, not receipt of bytes on a remote machine.

Keep the provisioning result API's existing read-only/no-payment semantics. This is
a storefront access guard, not a change to the provisioning aggregate. Never cache
access material or put it in evidence/decision records. Do not fetch a payment
snapshot on every credential read. Remote stops become local ends through rate
servicing; its healthy observation bound is not an absolute no-access-after-remote-stop
promise. Credentials already disclosed are revoked by physical termination, not by
blocking a later read. `converge-ongoing-compute-leases` owns the remaining servicing
and access-bound discussion.

## Ownership and dependency gates

| Owner | Owns | This change consumes |
|---|---|---|
| `agreed-evidence-and-early-termination` / `kit/deal-servicing` | final requests, earliest end, admission rule, end effects and journaled self-filing, routes/evidence | admission/domain port and one final-request plus exceptional-end handoff |
| `renewable-compute-lease-deadlines` | awaiting-activation deadline and site activation/expiry/report | activation to Agreement end and observed awaiting-activation expiry |
| This change / compute family | protected transition call sites, delivery record, activation callers, access admission | injected ports, never mechanism-ID branches |
| `spot-deals-through-arkhai-payments` | rate payment adapter, operation identity, verified authority records | payment effects reached through the seller half |
| `converge-ongoing-compute-leases` | rate hook implementation and ongoing servicing in `kit/deal-servicing` | D3 hook contract and delivery evidence/checkpoints |
| `kit-owned-listing-and-fulfillment-lifecycles` | broader start/evidence/verification extraction | the one compute delivery path, not a competing path |

Implementation of prepaid delivery requires the first two dependencies. Rate
composition/qualification additionally requires the rate adapter and servicing;
publication remains fail-closed without them. The archived
`resolve-compute-family-findings` is the current recovery/admission baseline; preserve
its safeguards rather than introducing a competing recovery owner.

## Rejected alternatives

- Billing horizon or payee vouch: it protects only against an honest crash, not a seller that keeps advancing it; the buyer's stop and case are the guarantee.
- A rate-specific activation horizon or active renewal loop: no authority guarantee depends on it; activation to the agreed end closes the immediate gap and renewal is deferred.
- Direct undelivered refund/stop, a post-stop refund journal or reverse-before-stop: end service journals `exceptional_end(start)` and the dispute authority applies the correction under the holds.
- Backdated/effective-time payee stop: stops are never backdated; the dispute authority stops now and reverses since the evidenced instant.
- Minimum spend or its refund rule: provisioning cost is seller pricing/acceptance policy; presets may use an honestly named setup `once` part.
- Storefront-local notice scheduling: pending stops and notice live at the payment authority and survive a dead storefront.
- A second end-deal route, final-request log or financial end decision: lifecycle/end service owns them; buyer ends use `end_delivery` and authority actions.
- A gate only in polling or only once at delivery start: it misses later protected transitions and recovery races.
- `authorized` meaning disclose was allowed before provisioning: authorization is phase-scoped and availability must follow verified start and activation.
- Starting rate billing after disclosure: recovery would serve access without a recorded start.
- A storefront provisioning timer duplicating the site: expiry is the site's clock and claim; a dead storefront cannot run such a timer.
- A live payment snapshot per credential read or absolute no-access-after-remote-stop: neither makes two authorities atomic, and the former couples physical reads to payment availability.
- A family-neutral path in `kit/fulfillment`: commercial delivery and site activation are compute-family responsibilities, separate from provider execution.

## Open questions

None blocking this implementation basis. Placement, separate delivery record and the
local transaction/revision technique above are recommendations supplied here; revisit
the technique if dependency implementation exposes a different durable admission seam
that preserves the same ordering, without introducing another end owner.

## Design promotion record

Planned destinations; promotion follows implementation review, not this design edit.

| Accepted decision | Permanent destination |
|---|---|
| D1 family ownership and ports | `docs/development/ARCHITECTURE.md` (Family kits, Fulfillment); new `compute-delivery` architecture companion |
| D1 delivery record; D2 window; D3 hook; D4 recovery | new `compute-delivery` spec and architecture companion; `openspec/specs/fulfillment/architecture.md` (boundary only) |
| D4 delivery-priority exception; D6 activation caller | `openspec/specs/vm-storefront-fulfillment/spec.md` and architecture companion; new `compute-delivery` spec |
| D5 undelivered caller of lifecycle | new `compute-delivery` spec/architecture; `docs/development/ARCHITECTURE.md` (Release), referencing the lifecycle owner |
| D6 activation to agreed end; D7 access admission | new `compute-delivery` spec/architecture; `docs/development/ARCHITECTURE.md` (Authority boundaries, Fulfillment status and results) |
| Capability documentation | `openspec/specs/README.md` adds `compute-delivery`; planned spec/companion created under that capability at closeout |
| Goal/campaign currency | `docs/development/ROADMAP.md` Goal 8 and `openspec/changes/README.md` delivery row, at implementation closeout |
