# Design — one compute delivery path

## Context

VM and bare metal commit, dispatch and disclose through different paths. Bare metal
commits from now; VM recovery substitutes 3600 seconds twice, and
`vm_fulfillment_service._parse_start_utc` substitutes now for a missing start and
accepts legacy minute-format timing. The accepted Agreement, not those fallbacks,
owns the window. Exact normalized requests and recorded resource identities remain
recovery inputs; legacy minute-format persisted timestamps remain readable, which is
not a reason to guess a new Agreement start.

Provisioning owns physical fulfillment and live results. Core forms
`StorefrontFulfillmentContext` and invokes the domain hook, validating its returned
identity. The shared path runs inside that hook, never beside or instead of it.
Payment settle and Alkahest's ready continuation reach the same hook. This change
does not replace settlement-stage evidence validation.

The foundation, `agreed-evidence-and-early-termination`, owns end service and its
durable admission and end-plus-filing operations; this change consumes them as
contracts, which are not yet implemented on this branch.

## Goals / Non-Goals

One compute-family delivery implementation; immutable Agreement windows; activation
before billing and availability; stable effect recovery; a classified end handoff;
no credential disclosure after a locally admitted end.

No second end service, payment journal, dispute policy, renewal, Alkahest dispute
adapter, or broader obligation-discovery and evidence extraction.

## Decisions

### D1. A separate compute-family delivery distribution and one record

The path is a library distribution at `domains/compute/delivery`, source
`compute_delivery`, under the family layout `align-package-paths-with-layers`
targets. It depends on compute contracts and client interfaces and on the neutral
lifecycle libraries, not on storefronts or deployed services, so the site service's
install gains no servicing or persistence dependency. It classifies as a compute
specialization library under the existing architecture check, with no override.
Cross-mechanism convergence that delegates to the path lives in this distribution
or above it, never in the physical base kit; the vocabulary package at the family
root and the neutral `kit/fulfillment` are not its owners, and a separate project
below the family root is not vocabulary.

The foundation owns the shared port slice: `kit/deal-lifecycle` supplies the payment
adapter's authorization and effect protocols and the evidence envelopes;
`kit/deal-servicing` supplies the neutral delivery authorization phases and
decisions. The foundation's `ActivatedDeliveryRef` carries the negotiation,
commitment, reservation and fulfillment identities, the verified site activation
record reference and active instant, and the ready-evidence digest and envelope
(kind, version and an opaque domain payload). Generic servicing does not interpret
the payload; the composition injects compute validation, so no upward family import
is needed. One foundation-owned phase enum — reserve, commit, dispatch, activate,
start, disclose — is shared by `admit` and `authorize_delivery`; an unknown phase
refuses.

Each domain composition closes over the path and its ports inside its fulfillment
hook; `StorefrontFulfillmentPorts` is unchanged and core's identity validation
remains. The hook distinguishes waiting-for-delivery from deferred completion.
Available maps to fulfilled. Before dispatch, a pending authority or persistence
state, a future start, or repair-required timing leaves the selected mechanism's
operation awaiting delivery through its existing journaled runtime operation, never
as a deferred hook outcome: Alkahest servicing rechecks every cycle without error
backoff, with the accepted start as the earliest dispatch time, and hosted payment
recovery rediscovers pending delivery through its existing periodic reconciliation
worker. Once a workload exists, deferred is used only when the durable domain
convergence record names the deployed completion worker. Repair-required is
operator-visible, never invents terms, and records its retry owner. Terminal maps
to failed only after D5's handoff is durable. Mechanism-specific evidence and claim
continuations stay outside the path.

One negotiation-keyed record in the storefront database holds the accepted window
and site, the reservation and fulfillment identities, servicing-decision references,
delivery-owned intents, acknowledgements and checkpoints. It holds no credentials,
payment balances, final-request log or financial end. End service owns the
revision-bearing admission port and the single end-plus-optional-filing operation;
delivery calls them in the same storefront transaction for admission and
compare-and-set. No transaction spans remote I/O, and neither owner imports the
other's concrete repository.

**Additive projection cutover.** The shared record is introduced additively.
Immutable evidence, exact requests and real Alkahest state stay with their owners;
the old VM and bare-metal delivery-progress rows become read-only projections, not
writers. One migration transaction adopts the negotiation, accepted digest and
window, reservation and fulfillment identities in both domains after authoritative
reconciliation: held or committed becomes an exact commit intent, dispatched becomes
dispatched, provider-ready becomes ready evidence only. Activation, billing start
and availability are never inferred from old credentials or a physical active flag;
live readiness, activation and admission are revalidated before availability.
Ambiguous, missing or conflicting evidence stays repair-required and keeps its
resource. Access already disclosed is not retroactively revoked by the migration.

Live result reads for adopted resources are enabled before any stored access
material, authenticated response bodies included, is deleted. Every foreground and
recovery writer switches together, through a **mandatory bridge release**: both
storefront bridge versions, which check a minimum writer and schema floor before
any writer starts, are deployed first and recorded as the oldest supported rollback
binaries; every unbridged process is stopped and unbridged startup against the
database is prohibited; the operator acknowledges that state; only then does the
migration run and the floor rise above the bridge. Refusal is qualified with the
actual pre-cutover bridge artifacts against migrated database copies. Unbridged
binaries are unsupported, never rollback candidates. Downgrade requires a reviewed
forward repair or an explicit development reset, never a silent return to old
writers. This supersedes both domains' reset-only delivery-schema rules for verified
lifecycle adoption only, not for historical evidence validation; malformed evidence
and chain-name payment sentinels are never copied or trusted.

### D2. The Agreement window survives every retry

Commit `lease_start_utc = Agreement.start_utc` and `lease_end_utc = start +
duration` at settlement, under the same reservation identity on every attempt. The
terms change owns the horizon as `duration_seconds` and the foundation's single
term-end `early_termination.settles_through`; delivery introduces no end-treatment
field and no local billing arithmetic. There is no now or missing-duration
fallback and no replacement resource on ambiguous old timing. Late settlement
shortens service and never shifts the absolute end.

Forward reservations are kept, with zero early-provisioning lead time: dispatch,
activation, billing start and disclosure occur no earlier than
`Agreement.start_utc`. Before then a committed deal is waiting-for-delivery with a
durable wake time and the retry owner D1 records, and rechecks admission on wake,
so hardware is never used outside the admission window; a nonzero lead time would
need explicitly accounted capacity, not a timer. The renewable change anchors the
activation deadline at `max(committed_at_utc, lease_start_utc) + delivery_deadline_seconds`,
the deal's commitment instant that delivery supplies with the site commit and the
option's published deadline, which the site reads from its pool under the same name.
Available never means early access. Settlement after the end enters D5, without guessing
which party caused the lateness.

Reservation acknowledgement-gap recovery uses the negotiation-keyed exact-request
idempotency slice of `capacity-reservation-lifecycle-hardening`, which gates
sections 1–2 of this change's plan rather than the whole of that change. That slice
compares normalized claim dimensions and attributes, the selected pool and site,
the offering mode and the lease window; rejects changed reuse; and returns the
recorded identity and state across held, committed and released. Replacing a known
expired hold is a separate explicit placement, never the resolution of an
unresolved reserve intent; expired or released recovery enters repair-required or
the classified end handoff, never a fresh hold. Delivery validates the returned
facts against its immutable intent, and reserve, commit, schedule and begin all
resolve the same authoritative identity.

### D3. Pure authorization and a separate billing-start effect

`authorize_delivery(deal, phase)` is a decision, not a payment mutation. The
financial check runs before commit, dispatch, start and disclose; admission also
guards reserve and activate under the same foundation-owned enum.
`kit/deal-servicing` alone durably records allow, refuse or pending with the
reason, operation ID and evidence references before use; delivery retains a
decision reference and checkpoint, not a second decision journal. Start means
permission to attempt billing start, not the start effect itself. An unknown
authority outcome stays pending. Prepaid and current Alkahest deals compose an
explicit no-financial-action implementation that allows only after the selected
stage's typed, versioned evidence validates and local admission passes. A missing
adapter-table entry never implies allow; a missing required rate adapter blocks
composition; an unsupported `watch` or `exceptional_end` reports unsupported.

Every protected transition, activation included, rechecks the foundation's
admission and its revision; a financial allow never overrides a local due end. D7
reuses the same port for credential reads.

After ready evidence and activation, delivery calls end service's
`begin_billing(operation_key, activated_delivery_ref) → intent_ref, outcome`
with a stable operation key. End service alone persists the immutable
billing-start intent and key and the evidence before calling the payment adapter,
which derives per-part keys deterministically; end service resolves an unknown
outcome without allocating another start identity. Delivery stores only the
end-service intent reference and the acknowledged checkpoint, never a second start
intent or key. The no-financial-action implementation returns a no-op and creates
no artificial once part or Alkahest start.

The family supplies `ActivatedDeliveryRef` with every identity and D6's verified
site activation reference and instant, never access secrets. Spot's adapter
implements rate `authorize` and `start_billing`, authority interpretation and
per-part translation; convergence composes and drives the neutral servicing
decision and effect journal, not a second adapter. A remote authority read and
local admission are not globally atomic.

### D4. Acknowledged checkpoints and recoverable effect intents

| Checkpoint | Meaning / recovery |
|---|---|
| authorized | servicing decision reference and exact commit intent durable; resolve the same reserve/commit |
| dispatched | fulfillment dispatch acknowledged; query or adopt the recorded fulfillment |
| activated | validated provider readiness and site activation acknowledged; preserve any earlier end |
| started | billing-start effect acknowledged (a verified authority record for a rate part; a no-op for prepaid) |
| available | disclose authorization and readiness durable; no buyer read required |
| converged | the selected stage's required evidence, readiness or claim-binding continuation acknowledged, or explicitly no continuation for that stage |

The order is commit gate and commit; wait until the start; dispatch gate, dispatch
and ready; local admission and activate; start gate and `start_billing`; disclose
gate and available; converged. The old ambiguous "active" delivery name is retired;
physical active and the site's `renewal_phase` active remain their owners' distinct
facts. Converged does not wait for unrelated collection or payout and does not move
claims-engine submission into delivery. Access requires available or converged and
D7, never convergence alone.

Delivery-owned intents are persisted before the remote reserve, commit, dispatch
and activation calls; for billing it retains the reference to end service's
journaled intent. Acknowledgements advance checkpoints. Recovery checks authority
state under the same keys and repeats admission at every gap. Required writes defer
effects; bookkeeping alone never abandons a running resource. Local claim expiry
permits recovery, not duplication. Each checkpoint's effect is recoverable.
`kit-owned-listing-and-fulfillment-lifecycles` owns obligation discovery and
terminal driving across mechanisms and consumes this path rather than
reimplementing it.

### D5. Classified delivery-end handoff, never a refund implementation

Delivery supplies the cause, actor, source, accepted start, observed failure time,
identities and evidence to the foundation's `record_end` operation, with the
optional `exceptional_end` filing through the agreement's dispute adapter. That
owner selects and records the earliest final request and journals the command
atomically. Delivery writes no second end log and computes no amounts or payment
corrections.

`end_delivery` carries no `at`; the storefront signs its receipt time as evidence.
It grants the storefront no authority to stop billing for the buyer. The buyer half
first stops at the payment authority under its own entitlement; if the authority is
unreachable it journals that stop and retries under the same key, and billing
continues until the stop lands. The buyer may additionally file `buyer_end` with
the signed request and receipt; that case carries the exact Agreement verified
against the mandate's deal hash, goes to a person in triage, and is realized as the
payer's own stop at `at` with the payer's notice and `partialPeriod`. There is no
mechanical `buyer_end` ruling. Delivery consumes the foundation's evidence and
admission result, not a second policy.

| Observed evidence before availability | Authority-backed cause input | Caller handoff |
|---|---|---|
| Buyer `end_delivery`, verified payer stop or ruling | Signed request or authority record and instant | Supply the existing final request and evidence for the foundation to compare with the non-delivery basis |
| Start refused | Verified refusal reason or payment record: payer stop, mandate state, exhaustion, seller fault or unknown | Pass the reason and record; never classify by event name; missing pre-start funding is not exhaustion |
| Provisioning failure or activation lapse | Fixed observation and any earlier buyer or ruling record | Supply seller non-delivery evidence for the foundation's classification |
| Window elapsed or payee stopped before availability | Start basis and never-delivered evidence, unserved setup included | The clock or the seller's own stop never erases non-delivery |
| Late settlement with no independently established cause | No proof of buyer fault | Do not dispatch; supply never-delivered evidence without inventing an exemption |

The foundation alone classifies these inputs. It compares an earlier buyer,
payer-stop or ruling record with the never-delivered basis (the Agreement start),
not arrival order; only a record that controls that basis suppresses the seller's
self-penalty filing. A terms end or a payee stop alone does not suppress
non-delivery. Foundation D8 owns the policy and the never-delivered timing:
`min(start, failure observation)` after the start, and before a future start the
filing is journaled now and executed at the Agreement start, never future-dated.
Delivery supplies the accepted start and the fixed failure-observation time and
does not choose `at`. Retries preserve the original evidence and key. A prior term
end does not erase an already established seller non-delivery obligation. An
unsupported assertion of buyer-caused lateness is not a reason to keep payment:
only authority records and kept signed bytes establish buyer actions.

No-dispatch proof permits end service's release without teardown; dispatched work
is adopted and ended, not replaced. The site report is end intent and evidence,
not proof of hardware release; proven release is a separate completion fact.
Physical recovery does not wait for authorities. The seller half files
`exceptional_end(at)` with the Agreement's dispute authority through the dispute
adapter, journaled with the end, and sends no stop or reverse of its own, so the
authority never reconciles seller-side effects.

Arkhai mediation's only mechanical ruling is a payee-filed self-penalty request at
least as strong as the standard request. Through mediation's own stop entry
`{account, notice: PT0S, partialPeriod: "chosen"}`, the standard request stops rate
parts now with `returned`, reverses their earnings since `at`, returns the unserved
share of once parts by time, then reverses `min(premature_stop_penalty, earned
amounts still held)` to the payer across parts in mandate order; a bond award is
reserved for hosted bonds. On-demand always uses `returned`: that is its contract.
Setup is owed from approval, so it returns wholly if the seller never delivered and
not at all once it has. These are dispute-authority rules the foundation and mediation own,
never amounts or payment operations for delivery to implement. The package of stop,
refunds and capped penalty needs one ruling; a partial seller-direct path would
still need a dispute, and the authority records disputes so it can act on bad
sellers. On-demand's "won't preempt" is enforced by remedy — the buyer's case over
held money and the premature-stop penalty — not by mandate restriction; the seller's
own exit is this mechanically ruled self-penalty. Seller stop entries represent
entitlements only, such as spot's notice entry; a spot seller's emergency exit is
the `exceptional_end` filing. No exceptional-end self-correction through the payment
adapter exists.

An Alkahest deal with no exceptional-end dispute adapter reports an unsupported
filing and keeps its existing recovery and reclaim semantics; no fictitious
authority success is reported. After availability, the foundation's service-end
rule applies instead. A cooperative seller's filing is no guarantee about arbitrary
sellers.

### D6. Reservation-only activation before billing

Delivery activates after provider-ready evidence, no earlier than the Agreement
start, and before billing start and availability. The request names only the
reservation. The site's returned end is validated against the immutable commit end
or a verified earlier end recorded by end service: an unexplained mismatch is
repair-required; a valid earlier truncation is adopted, never extended to the
original Agreement end. The active instant is the site's fact. Unknown
acknowledgements are journaled and retried under the same identity; an expiry
claimed first refuses activation and enters D5. A truncation before activation, or
between a lost acknowledgement and its retry, survives unchanged. Activation never
changes the reservation's end.

**Staged enablement.** The renewable change ships the compute composition's
safeguard switch off while provider support and default validation remain. This
change owns enablement, after every storefront and recovery caller is deployed:
compatible storefronts first, then the updated site with the switch off, then
qualification of every caller in explicitly enabled owned lanes, then the
repository's compute-composition default changes for new commits. The renewable
change introduces the setting in
`provisioning/compute/service/src/compute_provisioning_service/container.py` and its
configuration owner (paths to be reverified); the plan's section 4 owns that
post-qualification edit. Hosted operators enable only after their own
caller-readiness gate, and public records state readiness, never private target
identifiers. Existing null-phase leases stay null.

For a verified legacy null-phase leased view, activation is a no-op; an absent
activation route is tolerated only with that verified legacy view or capability. An
awaiting-activation lease with no route, an unknown phase, an unverified legacy
assumption or an end mismatch is deferred as repair-required. An unreachable
activation endpoint is never assumed to have succeeded. This permits rolling
deployment without reclaiming delivered leases that were never activated; site-only
evidence cannot enable it. Renewal remains a deferred seller-side option, not buyer
protection.

### D7. Live credential reads, including authenticated replay

VM settle and settle-status remain its buyer access surface: credentials are fetched
live through the shared guard while the existing response model is preserved. Bare
metal's access and result surface uses the same guard. The VM buyer's hosted path
and the core buyer's orchestrator continue polling the typed settle-status contract;
no new endpoint, CLI or persisted-credential fallback is introduced. Client changes
are coordinated with `buyers-use-the-storefront-client` if it lands first.

A read requires available or converged, the start reached, and the foundation's
local time and revision admission. Provider credentials are fetched outside the
transaction, then the revision and due end are rechecked before the response is
signed and authorized; fetched bytes are discarded if an end wins. Physical
termination revokes previously disclosed material.

Both VM `seller_auth` and bare-metal `response_auth` exempt credential-capable
settle, status, access and result responses from retained response bodies. They
retain the request digest and identity needed to reject changed requests, and
response signing; an exact retry re-enters the read and guard and may now be
refused. Existing cached access bodies are purged at cutover; no credential appears
in replay storage, decisions, logs or projections. Replay of mutation
acknowledgements is otherwise unchanged. The `marketplace-identity` MODIFIED delta
here owns the narrow per-route exact-retry resolution declaration: re-run for
credential-capable routes, recorded-outcome by default elsewhere. Mutating settle
retries resume the same domain operation and regenerate only the access response,
never repeating a mutation. Reservation, first-use skew, changed-request rejection
and signing are unchanged. `redesign-authenticated-requests` generalizes this same
declaration, not a second flag, and this change does not wait for its wider horizon
and storage design: unify archives first and redesign second with its MODIFIED
block a superset; if the order reverses, unify's block is re-diffed as the superset
before archival.

There is no payment snapshot on each read. Local authorization — not receipt of
in-flight bytes, and not an absolute remote-stop access bound — is the guarantee.
`watch` turns remote authority stops into local ends; the foundation supplies the
ordering, not another cache.

## Dependencies

- `agreed-evidence-and-early-termination`, whole: the neutral delivery ports and
  evidence envelope, the revision-bearing admission, `record_end` and
  `begin_billing`, and the cause and timing semantics. Servicing alone journals
  authorization decisions; delivery retains references.
- `renewable-compute-lease-deadlines`, whole: activation, conditional expiry and the
  report extension; it transitively requires `inject-site-pool-authority`. This
  change owns the final deployed enablement of the safeguard.
- `capacity-reservation-lifecycle-hardening`: only its negotiation-keyed reserve
  replay slice, which gates sections 1–2 of the plan.
- `add-arkhai-payments-lane-double`: HTTP lane qualification in the plan's tasks
  3.3 and 4.3. Library integration uses the clock-injected payments engine in
  `kit/arkhai-payments` fixtures directly, which the lane double wraps; the
  mediation fake keeps triage plus the sole qualifying seller self-penalty ruling.
  No kit depends on runnable tooling.
- This change lands before `converge-ongoing-compute-leases`, which depends on it
  as a whole change, implements the rate hook against its seam, and owns the whole
  rate qualification matrix, including the activate/start/disclose race and the
  started-but-undisclosed recovery. The prepaid path and the hook interface do not
  wait for rate servicing; rate publication and materialization stay fail-closed
  until that servicing is composed. `spot-deals-through-arkhai-payments` supplies
  the rate adapter the hook calls.
- `kit-owned-listing-and-fulfillment-lifecycles`: broader convergence discovery and
  terminal driving, dependent on this path for protected-effect recovery and access
  retirement; its calling convergence lives here or above, never in the base kit.

Sibling obligations this design relies on: the hardening change's section 3 supplies
the normalized request equivalence, conflict refusal and identity recovery named in
D2; `redesign-authenticated-requests` consumes and generalizes D7's retry
declaration; the foundation supplies `ActivatedDeliveryRef` with every D3 field, the
sole servicing decision journal, the named `begin_billing` entry, the shared phase
enum and the evidence-gated no-financial-action for current Alkahest;
`kit-owned-listing-and-fulfillment-lifecycles` places its calling convergence in
`domains/compute/delivery` or above and keeps obligation discovery there.

Archive order: foundation, then renewable, then unify for the site, event and
default overlap; unify before `redesign-authenticated-requests` for identity. Every
later MODIFIED block retains all clauses and scenarios its predecessors keep, and
implementation re-diffs against the then-current permanent requirement, not an
earlier design snapshot. No whole-change dependency cycle exists in this order.

## Rejected alternatives

- Provisioning base-kit placement: unnecessary lifecycle and persistence install weight.
- Start hidden in authorization, or before activation: ambiguous keys and avoidable
  billing-before-expiry races; start is a separately keyed post-activation effect.
- Early dispatch without accounted lead-time capacity: can exceed the agreed window.
- Restoring the original end on activation: resurrects an earlier admitted end.
- A self-penalty for every refused transition: conflates lawful ends with seller failure.
- A buyer-fault guess for late settlement: no authority-backed evidence supports it.
- Billing horizons, local notice schedulers, direct refunds and a second end journal:
  contradict the authority boundary; authority stops, holds and cases protect buyers.
- Retained credential-response replay: bypasses local admission after an end.
- Compound termination authority at payments: deferred by the owner until hosted
  bonds are designed. A transaction-level event could end billing at an authorized
  past time, settle rate parts returned, refund unserved once parts and forfeit a
  bond, but would still need dispute-authority recording for action on bad sellers.
  The foundation owns this deferred alternative; delivery adds no such port.
- A cutover marker that no binary reads: the bridge release fences old writers by
  a floor they check themselves.

## Open questions

None. The recommendations above are defaults supplied under the owner's delegation:
the foundation defines the shared protocol, evidence and journal; spot interprets
rate financial evidence; convergence composes rate execution. Missing
implementations remain gates, not licence to duplicate them. No runtime
implementation or qualification is claimed by this design.

## Status

Reconciled onto `agreed-evidence-and-early-termination` on 2026-10-29. Shaped by
reviews 01–04 of the reconciled plan: the family distribution and its placement
under the target layout (02, 04), the additive projection cutover and mandatory
bridge release (01, 02, 03), the waiting-for-delivery distinction (03), the
`ActivatedDeliveryRef` envelope and shared phase enum (04), forward reservations
with zero lead time (02), the foundation-owned classification of non-delivery
against the Agreement start (04), staged activation enablement (02), and the
hardening-slice reserve replay and credential-retry declaration coordinated with
their owning changes (03, 04). On Goal 8's fourth review round the rate
qualification rows moved to convergence's matrix and the dependency on
`converge-ongoing-compute-leases` became whole-change ordering.

## Design promotion record

Planned destinations, not current-state documentation:

| Accepted decision | Permanent destination |
|---|---|
| D1 distribution, neutral protocol boundary, core hook | `docs/development/ARCHITECTURE.md` (Family kits, Fulfillment); compute-delivery architecture |
| D1 additive adoption, credential retirement, downgrade refusal | `vm-storefront-fulfillment` and `physical-provisioning` specs and architectures; compute-delivery spec and architecture |
| D2 windows and future starts; D3 ports; D4 checkpoints and recovery | compute-delivery spec and architecture; fulfillment architecture (boundary only) |
| D5 caller classification | compute-delivery spec and architecture; reference to deal-lifecycle policy |
| D6 post-qualification default (archived after renewable's off-by-default introduction) | `resource-pool-management` spec; deployment configuration |
| D6 activation and enablement; D7 access and replay | compute-delivery spec and architecture; `vm-storefront-fulfillment`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `ARCHITECTURE.md` authority and results sections |
| D7 retry declaration and retained proof/refusal contract | `marketplace-identity` spec; `ARCHITECTURE.md` authentication boundary |
| Capability index | `openspec/specs/README.md` adds compute-delivery |
| Goal and campaign currency | `ROADMAP.md` Goal 8 and only the capacity row's missing-start clause, keeping the start-on-activation gap; `changes/README.md` dependency and status rows |
