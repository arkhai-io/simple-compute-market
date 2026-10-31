# Design — one compute delivery path

## Context

VM and bare metal currently commit, dispatch and disclose through different paths.
Bare metal commits from now; VM recovery substitutes 3600 seconds twice, and
vm_fulfillment_service._parse_start_utc substitutes now for missing start and accepts
legacy minute-format timing. The accepted Agreement, not those fallbacks, owns the
window. Exact normalized requests and recorded resource identities remain recovery
inputs; legacy minute-format persisted timestamps remain readable, not a reason to
guess a new Agreement start.

Provisioning owns physical fulfillment and live results. Core forms
StorefrontFulfillmentContext and invokes the domain hook, validating its returned
identity. The shared path runs inside that hook, never beside or instead of it.
Payment settle and Alkahest's ready continuation reach the same hook. This change
does not replace settlement-stage evidence validation.

The foundation owns end service and its durable admission/end-plus-filing operations.
These are dependency contracts, not implemented capabilities on this branch.

## Goals / Non-Goals

One compute-family delivery implementation, immutable Agreement windows, activation
before billing and availability, stable effect recovery, classified end handoff,
and no credential replay after a locally admitted end.

No second end service, payment journal, dispute policy, renewal,
Alkahest dispute adapter, or broader obligation-discovery/evidence extraction.

## Decisions

### D1. A separate compute-family delivery distribution and one record

**Recommendation (02 F5/F11/F12):** create the library distribution
domains/compute/delivery, source compute_delivery, rather than add commercial
orchestration to arkhai-compute-provisioning. It depends on compute contracts/client
interfaces and neutral lifecycle libraries, not storefronts or deployed services.
**Recommendation (04 F2/F7):** use the target family layout of
align-package-paths-with-layers now. This path already classifies as a compute
specialization library; no checker edit or override is needed. Cross-mechanism
convergence that delegates here belongs in this delivery distribution (or above
it), never in the physical base kit.
This avoids adding servicing/persistence dependencies to the site service's install.
The vocabulary package at the family root and neutral kit/fulfillment remain
unsuitable owners; a separate project below the family root is not vocabulary.

The foundation owns the shared port slice: kit/deal-lifecycle supplies payment
adapter authorization/effect protocols and evidence envelopes, and kit/deal-servicing
supplies the neutral delivery authorization phases/decisions.
**Recommendation (04 F3/F5):** foundation's neutral ActivatedDeliveryRef carries
negotiation, commitment, reservation and fulfillment identities, the verified site
activation record reference and active instant, and ready-evidence digest/envelope
(kind/version and opaque domain payload). Generic servicing does not interpret the
payload; composition injects compute validation. No upward family import is required.
One foundation-owned phase enum is shared by admit and authorize_delivery: reserve,
commit, dispatch, activate, start and disclose; unknown phases refuse.

Each domain composition closes over this path and its ports inside its fulfillment
hook; StorefrontFulfillmentPorts stays unchanged. Core identity validation remains.
**Recommendation (03 F1):** distinguish waiting-for-delivery from deferred-completion.
Available maps to fulfilled. Before dispatch, pending authority/persistence, a future
start or repair-required timing leaves the selected mechanism's operation awaiting
delivery through its existing journaled runtime operation, never a deferred hook
outcome. Alkahest servicing rechecks every cycle without error backoff; the accepted
start remains the earliest dispatch time. Hosted payment recovery uses its existing
periodic reconciliation worker to rediscover pending delivery. After a workload
exists, deferred is used only when its durable domain convergence record identifies
the deployed completion worker. Repair-required is operator-visible and never
invents terms; its retry owner remains recorded. Terminal maps to failed only after
D5 is durable. Mechanism-specific evidence/claim continuations remain outside.

One negotiation-keyed record in the storefront database holds accepted window/site,
reservation/fulfillment IDs, servicing-decision references, delivery-owned intents,
acknowledgements and checkpoints.
It holds no credentials, payment balances, final-request log or financial end.
End service owns the revision-bearing admission port and single end-plus-optional-
filing operation from agreed-evidence-and-early-termination. Delivery consumes
those operations in the same storefront transaction for admission/CAS; no transaction
spans remote I/O and neither owner imports the other's concrete repository.

**Recommendation (01 F6 / 02 F9): additive projection cutover.** Introduce the shared
record additively. Keep immutable evidence/exact requests and real Alkahest state in
their owners; make old VM and bare-metal delivery-progress rows read-only projections, not writers.
Under one migration transaction adopt negotiation, accepted digest/window, reservation
and fulfillment identities in both domains after authoritative reconciliation:
held/committed -> exact
commit intent; dispatched -> dispatched; provider-ready -> ready evidence only.
Never infer activation, billing start or availability from old credentials or a
physical active flag. Revalidate live readiness, activation and admission before
availability. Ambiguous/missing/conflicting evidence stays repair-required and keeps
its resource. Already-disclosed access is not retroactively revoked by this migration.

Enable live result reads for adopted resources before deleting all stored access
material, including authenticated response bodies. Switch every foreground/recovery
writer together. **Recommendation (03 F3): mandatory bridge release.** First deploy
both storefront bridge versions that check a minimum writer/schema floor before any
writer starts. Record those actual release artifacts as the oldest supported rollback
binaries; stop all unbridged processes and prohibit unbridged startup against this
database. Cutover requires that operator acknowledgement, not a marker magically
fencing code that never reads it. Only then migrate and raise the floor above the
bridge. Qualify refusal with the actual pre-cutover bridge artifacts against migrated
database copies. Unbridged binaries are unsupported, never rollback candidates. Downgrade requires a reviewed forward repair or explicit
development reset, never a silent return to old writers. This supersedes both domains' reset-only delivery-schema rules only for verified
lifecycle adoption, not historical evidence validation. Malformed evidence and
chain-name payment sentinels are never copied or trusted.

### D2. The Agreement window survives every retry

Commit lease_start_utc = Agreement.start_utc and lease_end_utc = start + duration,
at settlement, under the same reservation identity on every attempt. Terms owns max_term_seconds == duration_seconds and foundation's single term-end
early_termination.settles_through field, not delivery. No retired end_partial_period
field or local billing arithmetic is introduced here.
No now/missing-duration fallback and no replacement resource on ambiguous old timing.
Late settlement shortens service, never shifts the absolute end.

**Recommendation (02 F2):** keep forward reservations, with zero early-provisioning
lead time in this plan: dispatch, activation, billing start and disclosure occur no
earlier than Agreement.start_utc. Before then, a committed deal is waiting-for-delivery with a durable wake time and
an identified retry owner per D1, and rechecks admission on wake. This avoids using hardware outside
the admission window; a future nonzero lead time would need explicitly accounted
capacity, not just a timer. Renewable anchors the provisional deadline at
max(commit_time, lease_start_utc) + allowance. Available never means early access.
Settlement after the end enters D5, without guessing which party caused lateness.

Reservation acknowledgement-gap recovery consumes the negotiation-keyed exact-request
idempotency slice of capacity-reservation-lifecycle-hardening. It is a section-1/2
implementation gate, not a dependency on that change's entire hardening scope.
The hardening slice must compare normalized claim dimensions/attributes, selected
pool/site, offering mode and lease window, reject changed reuse, and return the
recorded identity/state across held, committed and released states. Ordinary known
expired-hold replacement is separate explicit placement, never resolution of an
unresolved reserve intent. Expired/released recovery enters repair-required or the
classified end handoff, never a fresh hold. Delivery also validates returned facts
against its immutable intent. Reserve, commit, schedule and begin all resolve the
same authoritative identity.

### D3. Pure authorization and a separate billing-start effect

authorize_delivery(deal, phase) is a decision, not a payment mutation. The financial check is required before commit, dispatch, start and disclose;
admission also guards reserve and activate with the same foundation-owned enum. kit/deal-servicing alone durably records allow/refuse/pending, reason, operation ID
and evidence references before use; delivery retains a decision reference/checkpoint,
not another decision journal. Start means
permission to attempt billing start, not the start effect itself. Unknown authority
outcomes stay pending. Explicitly compose no-financial-action for prepaid and current Alkahest: allow only
after selected-stage typed/versioned evidence validation and local admission.
Missing adapter table entries never imply allow; a missing required rate adapter
blocks composition. Unsupported watch/exceptional_end still reports unsupported.

Every protected transition, activation included, rechecks foundation admission
and its revision; a financial allow never overrides a local due end.
D7 reuses that port for subsequent credential reads.

After ready evidence and activation, call end service's
begin_billing(operation_key, activated_delivery_ref) -> intent_ref, outcome. Delivery supplies a stable operation key; end service alone persists the
immutable billing-start intent/key and evidence before calling the payment adapter,
which derives per-part keys deterministically; end service resolves unknown outcomes without
allocating another start identity. Delivery stores only the end-service intent
reference and acknowledged checkpoint, never a second start intent/key.
The explicit no-financial-action implementation returns a no-op and creates no
artificial once-part or Alkahest start.

The family supplies ActivatedDeliveryRef with all identities and D6's verified site
activation reference/instant, never access secrets. Spot's adapter implements rate
authorize/start_billing, authority interpretation and per-part translation; converge
composes/drives the neutral servicing decision/effect journal, not a second adapter. Their requirements are referenced, not
copied here.
A remote authority read and local admission are not globally atomic.

### D4. Acknowledged checkpoints and recoverable effect intents

| Checkpoint | Meaning / recovery |
|---|---|
| authorized | servicing decision reference and exact commit intent durable; resolve same reserve/commit |
| dispatched | fulfillment dispatch acknowledged; query/adopt the recorded fulfillment |
| activated | validated provider readiness and site activation acknowledged; preserve any earlier end |
| started | billing-start effect acknowledged (verified authority record for rate; no-op for prepaid) |
| available | disclose authorization and readiness durable; no buyer read required |
| converged | selected stage's required evidence/readiness/claim-binding continuation acknowledged, or explicitly no continuation for that stage |

Order: commit gate/commit; wait until start; dispatch gate/dispatch/ready; local
admission/activate; start gate/start_billing; disclose gate/available; converged.
The old ambiguous delivery active name is retired; physical active and site
renewal_phase active remain their owners' distinct facts. Converged does not wait
for unrelated collection/payout or move claims-engine submission into delivery.
Access uses available/converged and D7, not convergence alone.

Persist delivery-owned intents before remote reserve, commit, dispatch and activation
calls; for billing, retain the reference to end service's journaled intent. Acknowledgements advance checkpoints. Recovery checks authority state under
the same keys and repeats admission at every gap. Required writes defer effects;
bookkeeping alone never abandons a running resource. Local claim expiry permits
recovery, not duplication. This change recovers each checkpoint effect.
Kit-owned listing/fulfillment lifecycles owns obligation discovery and terminal
driving across mechanisms, and consumes this path rather than reimplementing it.

### D5. Classified delivery-end handoff, never a refund implementation

Supply cause, actor, source, accepted start, observed failure time, identities and
evidence to foundation's record_end operation with optional exceptional_end
filing through the agreement's dispute adapter. That owner selects/records the earliest final request and journals
the command atomically.
Delivery neither writes a second end log nor computes amounts or payment corrections.
end_delivery carries no at; the storefront signs its receipt time as evidence.
It grants the storefront no authority to stop billing for the buyer. The buyer half
first stops at the payment authority using its own entitlement. If unreachable,
the buyer half journals that stop and retries under the same key; billing continues
until the stop lands. The buyer may additionally file buyer_end with the signed
request and receipt. That case carries the exact Agreement verified against the
mandate's deal hash, goes to a person in triage, and is realized as the payer's own
stop at at with its notice and partialPeriod. There is no mechanical buyer_end ruling.
Delivery consumes the foundation's evidence/admission result, not a second policy.

| Observed evidence before availability | Authority-backed cause input | Caller handoff |
|---|---|---|
| Buyer end_delivery, verified payer stop or ruling | Signed request/authority record and instant | Supply existing final request and evidence for foundation to compare with non-delivery basis |
| Start refused | Verified refusal reason/payment record: payer stop, mandate state, exhaustion, seller fault or unknown | Pass reason/record, never classify by event name; missing pre-start funding is not exhaustion |
| Provisioning failure or activation lapse | Fixed observation and any earlier buyer/ruling record | Supply seller non-delivery evidence for foundation classification |
| Window elapsed or payee stopped before availability | Start basis and never-delivered evidence, including unserved setup | Do not let the clock or seller's own stop erase non-delivery |
| Late settlement with no independently established cause | No proof of buyer fault | Do not dispatch; supply never-delivered evidence without inventing an exemption |

**Recommendation (04 F4):** foundation alone classifies these inputs. Compare an
earlier buyer/payer-stop/ruling record with the never-delivered basis (Agreement
start), not arrival order; only one that controls that basis suppresses a seller self-penalty filing.
Terms end or payee stop alone does not suppress non-delivery. Foundation D8 owns
this policy and the never-delivered timing. Delivery supplies the
accepted start and fixed failure-observation time; it does not choose `at`. That
owner uses min(start, failure observation) after start, with the pre-start exception
of journaling now and executing at Agreement start, never future-dating the command.
Retries preserve the original evidence and key.
A prior term end does not erase an already established seller non-delivery obligation.
Reject an unsupported assertion of buyer-caused lateness as a reason to keep payment:
only authority records and kept signed bytes establish buyer actions.

No-dispatch proof permits end service's release without teardown; dispatched work
is adopted and ended, not replaced. The site report is end intent/evidence, not proof
of hardware release. Proven release is a separate completion fact. Physical recovery
does not wait for authorities. The seller half files exceptional_end(at) with the
Agreement's dispute authority through the dispute adapter, journaled with the end.
The seller sends no stop or reverse of its own for that filing. Its fixed timing
above remains: never future-dated; a pre-start failure journals immediately and
files at Agreement start. The authority need not reconcile seller-side effects.

**Final owner supersession (04 F4):** this replaces E-A, E-C and E-E as amended,
the explicit-entry correction and the favourable-stop note. Arkhai mediation's only
mechanical ruling is a payee-filed self-penalty request at least as strong as the
standard request. Through mediation's own stop entry
`{account, notice: PT0S, partialPeriod: "chosen"}`, the standard request stops rate
parts now with returned, reverses their earnings since at, returns the unserved
share of once parts by time, then reverses min(premature_stop_penalty, earned
amounts still held) to the payer across parts in mandate order. Bond award stays
reserved for hosted bonds.
On-demand always uses returned: that is the on-demand contract. Setup's term ends
at activation, so its return is all if undelivered and none once delivered.
These are dispute-authority rules to reference from foundation/mediation, never
amounts or payment operations for delivery to implement.

Foundation's reconciled design includes exceptional_end in dispute-adapter intents
and mediation's request vocabulary/published mapping. The package of stop, refunds
and capped penalty (bond reserved) needs one ruling;
a partial seller-direct path would still need a dispute. Arkhai also records disputes
to act on bad sellers. On-demand's "won't preempt" is enforced by remedy—a buyer's
case over held money and the premature-stop penalty—not by mandate restrictions. The seller's own exit
is this mechanically ruled self-penalty.

The explicit seller restitution entry, payee-stop-without-entry/favourable rule,
payee notice waiver, payer early release and several-stop-entries-per-account
dependency/spot gate were removed. Seller stop entries represent entitlements only (for example
spot's notice entry); a spot seller's emergency exit is exceptional_end filing.
No exceptional-end self-correction through the payment adapter remains accepted.

An Alkahest deal with no exceptional-end dispute adapter reports unsupported filing
and retains existing recovery/reclaim semantics; no fictitious authority success
is reported. After availability, foundation's actual service-end rule applies instead.
Cooperative seller filing is not a guarantee about arbitrary sellers.

### D6. Reservation-only activation before billing

Activate after provider-ready evidence, no earlier than Agreement start, and before
billing start and availability. The request names only the reservation.
Validate the site's returned end against the immutable commit end or a verified
earlier end recorded by end service. An unexplained mismatch is repair-required;
a valid earlier truncation is adopted, never extended to the original Agreement end.
The active instant is the site's fact. Journal/retry unknown acknowledgements under
the same identity; expiry claimed first refuses activation and enters D5.
A truncation before activation or between a lost acknowledgement and retry must
survive unchanged. Activation never changes the reservation's end.

**Recommendation (02 F4): staged enablement.** Renewable ships the explicit compute
composition safeguard switch off, while provider support/default validation remains.
This change owns enablement only after every storefront/recovery caller is deployed.
Deploy compatible storefronts first, then the updated site with the switch off;
qualify callers in explicitly enabled owned lanes, then change the repository's
compute-composition default for new commits. Renewable introduces the setting in
provisioning/compute/service/src/compute_provisioning_service/container.py and its
configuration owner (reverify relocated paths). Section 4, not task 2.3, owns that
post-qualification edit. Hosted operators enable only after their caller-readiness
gate; public records state readiness, never private target identifiers. Existing
null-phase leases stay null.

For a verified legacy null-phase leased view, activation is a no-op; an absent
activation route is tolerated only with that verified legacy view/capability.
An awaiting-activation lease with no route, unknown phase, unverified legacy
assumption, or an end mismatch is deferred repair-required. Never guess that an
unreachable activation endpoint succeeded. This permits rolling deployment without
unactivated delivered leases being reclaimed. Site-only evidence cannot enable it.
Renewal remains a deferred seller-side option, not buyer protection.

### D7. Live credential reads, including authenticated replay

VM settle/settle-status remains its buyer access surface: fetch live through the
shared guard while preserving the existing response model. Bare metal's access/
result surface uses the same guard. VM buyer's hosted path and core buyer's
orchestrator continue polling the typed settle-status contract; no new endpoint,
CLI or persisted-credential fallback is introduced. Coordinate client changes with
buyers-use-the-storefront-client if that change lands first.

Require available/converged, start reached and foundation's local time/revision
admission. Fetch provider credentials outside the transaction, then recheck the
revision and due end before signing/authorizing the response. Discard fetched bytes
if an end wins. Physical termination revokes previously disclosed material.

Both VM seller_auth and bare-metal response_auth must exempt credential-capable
settle/status/access/result responses from retained response bodies. Retain the
request digest/identity needed to reject changed requests, and response signing;
exact retry re-enters the read/guard and may now be refused. Existing cached access
bodies are purged at cutover; no credentials appear in replay storage, decisions,
logs or projections. Replay of mutation acknowledgements is otherwise unchanged.
The marketplace-identity MODIFIED delta here owns the narrow per-route exact-retry
resolution declaration: re-run for credential-capable routes, recorded-outcome by
default elsewhere. Mutating settle retries resume the same domain operation and
regenerate only the access response, never repeat a mutation. Reservation, first-use
skew, changed-request rejection and signing remain unchanged. Coordinate with
redesign-authenticated-requests without waiting for its wider horizon/storage design:
it generalizes this same declaration, not a second flag. Archive unify first,
redesign second with its MODIFIED block a superset; if order reverses, re-diff unify
as a superset before archival.

No payment snapshot on each read. Local authorization, not receipt of in-flight
bytes or an absolute remote-stop access bound, is the guarantee. Watch turns remote
authority stops into local ends. Foundation supplies ordering, not another cache.

## Ownership and dependency gates

- Foundation: neutral delivery ports/evidence envelope, revision-bearing admission,
  record_end/begin_billing and cause/timing semantics. Servicing alone journals
  authorization decisions; delivery retains references. No local substitutes.
- Renewable: activation/conditional expiry/report extension; transitively requires
  inject-site-pool-authority. This change owns final deployed safeguard enablement.
- Capacity-reservation-lifecycle-hardening: negotiation-keyed reserve replay slice.
- Converge and spot-deals: rate decisions/effects/adapters. Prepaid implementation
  need not wait for rate qualification; publication stays fail-closed until composed.
- Add-arkhai-payments-lane-double: HTTP lane qualification in tasks 3.3/4.3/4.4.
  Library integration uses the clock-injected payments engine in kit/arkhai-payments
  fixtures directly; the lane HTTP double wraps that same engine. Mediation fakes
  retain triage plus the sole qualifying seller self-penalty mechanical ruling. No kit depends on runnable tooling.
- Kit-owned listing/fulfillment: broader convergence discovery/terminal driving,
  dependent on this path for protected-effect recovery and access retirement;
  place its calling convergence here or above, never in the base kit.

## Rejected alternatives

- Provisioning base-kit placement: unnecessary lifecycle/persistence install weight.
- Start hidden in authorization or before activation: ambiguous keys and avoidable
  billing-before-expiry races; start is a separately keyed post-activation effect.
- Early dispatch without accounted lead-time capacity: can exceed the agreed window.
- Restoring the original end on activation: resurrects an earlier admitted end.
- Self-penalty for every refused transition: conflates lawful ends with seller failure.
- A buyer-fault guess for late settlement: no authority-backed evidence supports it.
- Billing horizons, local notice schedulers, direct refunds and a second end journal:
  contradict the authority boundary. Authority stops/holds/cases protect buyers.
- Retained credential-response replay: bypasses local admission after an end.
- Compound termination authority at payments: deferred by the owner until hosted
  bonds are designed. A transaction-level event could end billing at an authorized
  past time, settle rate parts returned, refund unserved once parts and forfeit a
  bond, but would still need dispute-authority recording for action on bad sellers.
  Foundation owns this rejected/deferred alternative; delivery adds no such port.

## Second-review coordination

The coordinated plan supplies these sibling edits; the table retains ownership and
re-check obligations, not authority to duplicate a sibling implementation:

| Finding | Owner and edit needed |
|---|---|
| 03 F2 / 04 F8 | capacity-reservation-lifecycle-hardening section 3: normalized request equivalence (dimensions/attributes, pool/site, mode, lease window), conflict refusal, identity/state recovery across held/committed/released; distinguish explicit expired-hold replacement from unresolved-effect replay |
| 04 F1 | redesign-authenticated-requests: consume/generalize this identity retry declaration, preserve reservation/skew/changed-reuse/signing and credential re-run/no-body clauses; unify then redesign archive order, or re-diff as supersets if reversed |
| 04 F3/F5/F6 | foundation: ActivatedDeliveryRef with all D3 fields; sole servicing decision journal and delivery references; named begin_billing entry before adapter start_billing; shared phase enum and explicit evidence-gated no-financial-action for current Alkahest |
| 04 F4 | Applied in foundation's plan: verified refusal/payment records classify against never-delivered start basis, not event kind/arrival; clock or payee stop cannot erase unserved non-delivery; exceptional_end is a journaled dispute filing and mediation alone rules the seller self-penalty; buyer_end triage/end_delivery evidence aligned and seller-direct correction/extra-stop-entry gates removed |
| 04 F5 | Ownership reconciled: spot implements payment authorize/start_billing and verifies foundation's exceptional_end filing; converge composes/drives the journals without duplicating their implementation. Unify 4.4 consumes converge 3.1 and matrix rows 4/8 executed by converge 4.1, retaining only non-rate qualification |
| 04 F7 | kit-owned-listing-and-fulfillment-lifecycles design/proposal/spec/tasks: calling convergence goes in domains/compute/delivery or above, not compute_provisioning base; consume protected checkpoints/access retirement here and keep obligation discovery there |
| 04 F10 | parent-owned index: domains/compute/delivery, reservation-only current-end activation, section-level foundation/renewable/hardening and lane/rate qualification gates; record implementation readiness after the focused cross-change re-check |
| 04 F10 | parent-owned roadmap: Goal 8 current-end activation and seller self-penalty dispute filing (mediation's only mechanical ruling); amend only missing-start fallback clause of capacity row, keep start-on-activation gap; converge D4 current end, not original Agreement end |

Archive ordering: foundation -> renewable -> unify for site/event/default overlap;
unify -> redesign-authenticated-requests for identity. Every later MODIFIED block
must retain all clauses/scenarios its predecessors keep; implementation re-diffs
against the then-current permanent requirement, not an earlier design snapshot.
No whole-change dependency cycle is introduced by this ordering.

## Open questions

No unowned design choice here. Recommendations above are defaults supplied under
owner delegation. Foundation defines the shared protocol/evidence/journal, spot interprets rate
financial evidence, and convergence composes rate execution. These named contracts
are coordinated before implementation; missing implementations remain gates, not
license to duplicate them.
The focused cross-change re-check reconciled placement, compatibility, cause evidence
and qualification ownership. Sibling seams and archive-order commitments are
coordinated; implementation is ready subject to the recorded gates. No runtime
implementation or qualification is claimed.

## Design promotion record

Planned, not current-state documentation:

| Accepted decision | Permanent destination |
|---|---|
| D1 distribution, neutral protocol boundary, core hook | docs/development/ARCHITECTURE.md (Family kits, Fulfillment), compute-delivery architecture |
| D1 additive adoption, credential retirement, downgrade refusal | vm-storefront-fulfillment and physical-provisioning specs/architectures; compute-delivery spec/architecture |
| D2 windows and future starts; D3 ports; D4 checkpoints/recovery | compute-delivery spec/architecture; fulfillment architecture (boundary only) |
| D5 caller classification | compute-delivery spec/architecture; reference deal-lifecycle policy |
| D6 post-qualification default (archive after renewable's off-by-default introduction) | resource-pool-management spec; deployment configuration |
| D6 activation/enablement; D7 access and replay | compute-delivery spec/architecture; vm-storefront-fulfillment; docs/development/DEPLOYMENT_AND_CONFIG.md; ARCHITECTURE.md authority/results sections |
| D7 retry declaration and retained proof/refusal contract | marketplace-identity spec; ARCHITECTURE.md authentication boundary |
| Capability index | openspec/specs/README.md adds compute-delivery |
| Goal/campaign currency | ROADMAP.md Goal 8 and only the capacity row's missing-start clause; keep start-on-activation gap; changes/README.md dependency/status rows |
