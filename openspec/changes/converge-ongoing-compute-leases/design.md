# Design

## Context and authority

This is rate-part servicing inside the foundation's end service, not a second
lifecycle. `agreed-evidence-and-early-termination` owns final requests, evidence,
commands, watch/cursors, seller self-correction and buyer delivery ends. The protocol ends at
commitment; subsequent records are lifecycle and evidence. The storefront and site
are one seller from the buyer's perspective. Buyer guarantees rest on authority
records and kept signed bytes, never the seller's cooperation.

Current storefronts verify approval before delivery but do not continuously
converge rate funding, authority stops and physical effects. This design proposes
that integration; it makes no current-runtime or hosted-readiness claim.

## Goals and non-goals

Both compute compositions converge after commitment, report physical and financial
work separately, and recover durable effects across restart and authority outages.
No payment ledger, site renewal protocol, local payment-stop
scheduler or minimum spend is introduced. Spot owns rate mechanics, mandates,
period arithmetic, partial-period terms, publication and online notice commands.
Unify owns the one delivery state machine. Activation owns hosted enablement.

## Decisions

### D1. Ownership and section-level gates

**Recommendation supplied here (external F4):** `kit/deal-servicing` owns the storefront end-service loop, observation state,
evidence/journal, domain-neutral physical ports, and consumption of the
foundation-owned delivery authorization protocol (phases and decisions).
It imports no mechanism kit, dispute kit or compute specialization. The compute
specialization imports this protocol; compositions inject concrete adapters and
domain lease/admission/activation/release ports.

Implementation gates are foundation lifecycle contracts and spot rate mechanics.
The dependency on `unify-compute-delivery-path` is **section-level**, not its archive:
unify tasks 1–3 supply the path, hook seam, activation and undelivered handoff;
converge tasks 1–3 compose spot's rate authorize/start_billing implementation and drive servicing; unify's rate qualification
(task 4.4) and converge task 4 then use those implementations. Neither change waits
for the other's archive to implement its prerequisite section. Reverify shared
contracts at the delivered revisions before each handoff. Scenario execution also
requires the doubles' runnable payment/mediation sections, not their consumer
qualification or archive. Request these edges in the campaign index Notes rather
than keeping whole-change dependencies that form a cycle.

The shared lifecycle requirement archive order is foundation first, then this
change: the seller-list MODIFIED block preserves the foundation's full bounded-page,
continuation-token, identity, extension and state clauses while adding diagnostics.
Spot does not replace that requirement. The settlement retry MODIFIED block retains
existing idempotent completion, re-drive and retrieve semantics and adds only the
neutral lifecycle journal allowance. Do not promote duplicate foundation requirements.

### D2. Durable state, completion and diagnostics

Persist commitment/Agreement binding, domain operation/lease identity, verified
record cursors, funding observation/timer, selected earliest final request,
immutable operation descriptors, rotation/re-anchoring status and completion history. Keep exact evidence bytes
in the foundation's evidence store. End-service behavior belongs to `deal-lifecycle`,
not a second contract in `settlement-servicing`.

Physical completion requires authenticated proof of capacity release (the existing
capacity-released callback or verified terminal lease/fulfillment release read),
proof of no dispatch, or a labelled authenticated manual acknowledgement. Unknown
dispatch is adopted and ended first. A signed `lease_ended` is end intent and
attribution evidence, not proven teardown: initial and `release_failed` reports
leave physical completion false. An earlier end never resurrects a resource.

Financial completion is revision-scoped: all required parts have a verified authority
stop/end (not payout), all end-related case effects and seller self-corrections are
resolved, and no operation is pending or unknown. An unstarted rate part requires a
verified stop/end too; a once part uses its own term end or earlier authority stop.
A remaining dispute-window hold is not unfinished end work. Filing acceptance alone is insufficient. The end revision identifies the
selected earliest request and the set of relevant cases/ruling revisions; new
earlier evidence or relevant case changes reopen financial work without deleting
history. Once-only deals use the same facts and are financially complete when no
end-related authority work remains. Watches/retention continue after both facts.

**Recommendation supplied here (external F5):** extend seller lifecycle `read`/`list`: both facts and their evidence references,
end revision, gap ages, pending case/operation references, repair reasons, and
manual principal/reason/operation provenance. Include pending cooperative billing stops,
billing continuing after delivery end, running rate deals awaiting re-anchoring,
and once-only retiring-key dependencies labelled must drain. Running/unstarted remain until a
final request is due; ending means at least one completion fact is false; ended
requires both true. Permanent refusal or missing required evidence/credential
shows repair required while preserving both facts. Buyer reads retain their
foundation-owned delivery/evidence projection, not administrator-only diagnostics.

Manual recovery is seller `submit` kind `acknowledge_physical_recovery`, authorized
only to the storefront administrator. Its payload binds the deal, resource/end
revision and reason, with a stable operation key; changed key reuse is rejected.
It is dispatched locally to end service, not either authority adapter. Command `at`
is the observed recovery instant (never future); the accepted result names the
immutable local audit record and updated physical fact, not an authority record.
Unknown transport outcomes resolve by seller read/same-key retry. It records audited
physical evidence only, never money or site-signed evidence. Contracts and typed
client expose this local result alongside authority-command outcomes.

**Recommendations supplied here:** retain revision history; warn on a physical
gap beyond the configured watchdog-plus-teardown budget, and on authority work
beyond one retry budget, surfacing permanent refusals immediately. Budgets derive
from measured domain latency. Warnings never stop servicing or call a priced
notice gap an overcharge. Seller diagnostics never claim reserve-ahead caps buyer
billing after an unnoticed end.

### D3. Two queues, one registered step

**Recommendation supplied here (external F16):** register one end-service loop with the storefront loop controller. One step runs
physical work, bounded authority work with independent error handling, then a
second physical pass for newly due ends. Pausing pauses that loop; stepping runs
all three passes. Authority failures cannot prevent physical work, including the
second pass; physical failure cannot prevent authority work. Reuse the foundation's
cursor-after-journal and same-key unknown-outcome recovery rather than respecify it.

The authority queue consumes verified records, refreshes funding timers and drives
journaled commands. An entitled stop remains pending until its authority effective
time; it is not an immediate stop on observation. A verified funded-through value
is a replaceable timer, never a speculative lease truncation. Funding can advance
it. At expiry read the payment authority before ending: verified renewal replaces
the timer; a verified exhaustion stop is an authority final request with no
classification. Only an unreachable or unverifiable authority produces a bare-timer
final request and pending classification under D5. This read is bounded, so an
outage does not block physical work. A top-up within one polling interval is not
seller fault when the authority can verify it. Missing pre-start funding is not exhaustion. No site deadline follows funding.

### D4. Adapter-based admission and activation before billing

**Recommendation supplied here (external F4):** the neutral kit asks the injected payment adapter for a deal-level
`authorize(phase, evidence)` decision, never interprets hosted per-part snapshot
fields. The foundation payment protocol owns that operation and
`start_billing(activated_delivery_evidence)`; spot implements rate checks and
once-only adapters return allow/no-op. Publication/acceptance must fail closed if
the installed adapter cannot supply the required contract.

Authorization before commit/dispatch/disclosure checks verified authority evidence,
reservation and effective/pending stops through that adapter. Provision and activate
the lease to the Agreement's end or a verified earlier end recorded by end service
**before** issuing rate start as an effect, not an authorization step. A future
entitled stop preserves service until that earlier end; unexplained mismatches or
failed activation suppress start. Re-read/admit on lost activation acknowledgement
so truncation between activation and retry is preserved. End service alone journals the immutable billing-start key and
activated-delivery evidence before I/O; unify's delivery checkpoint stores a
reference, not a second start intent. Resolve unknown start by read/same-key retry
before disclosure. Start refusal supplies classified undelivered evidence through unify to the
foundation's timing policy, not a rate-owned choice of correction instant.

Unify/foundation own local dispatch/disclosure serialization and physical revocation.
This hook consumes those guarantees rather than repeating them. A healthy remote
stop still has a polling/watchdog/teardown observation window, not instantaneous
revocation. Each party has one
`notice_seconds` on its stop entitlement. Measured servicing latency and
reserve-ahead sizing are seller capacity-risk recommendations, not codec gates or
extra buyer charges. With storefront absent, service may run to the maximum lease
end; an optional activation deadline protects seller capacity, not buyer money.

### D5. Classified ends, held money and revised remedies

Consume foundation D8's closed cause classification, timing and correction journal
contract; do not duplicate its source table. A timer is this change's additional
source. After the expiry read in D3 fails at T, use
`record_end(final_request, correction: pending_classification)` atomically. A later
verified exhaustion stop at/before T discharges that obligation; billing beyond T
resolves it into the fixed `exceptional_end(T)` intent; inconclusive evidence leaves
it pending. Consume foundation's `resolve_correction(end_revision, intent | discharged,
evidence_ref)` for this transition and for earlier evidence after an end, with no
synthetic second final request or second journal. Physical work does not await
classification.

The seller's `exceptional_end(at)` is an SCM correction intent, not a payment
operation, dispute or self-filing. Payments knows accounts, money movement and
mandate lifecycle authorizations, not buyer/seller roles or implicit beneficial
actions. SCM mandate derivation adds an explicit stop entry on every part,
`{account: seller, notice: PT0S, partialPeriod: returned}`, visible to the buyer's
mandate check. The adapter sends `stop {part}` under that entry and
`reverse {part, amount}` under the existing reverse authority: rate earnings since
at, each once part's unserved share by its own term, and any full bond award.
No exceptional-end kind or field is sent to payments. Setup ends at activation:
all returned if undelivered, none if delivered. Foundation owns never-future timing,
including pre-start intents journaled immediately and executed at Agreement start.
Keep prior triggers and stable effect identities.

On-demand grants the seller only this immediate entry, not an entitled-notice
entry. The mandate cannot enforce the seller's promise not to preempt; a buyer case
over held money and the bond is the remedy. A spot seller needs both its negotiated
notice entry and the immediate entry. Several stop entries per account per part
are an unscheduled, gated payments dependency, not an existing primitive or an
implementation commitment here. Until supported, spot has no immediate seller stop;
emergency exit waits out its notice unless the owner decides otherwise. Do not
synthesize a second entitlement or advertise immediate restitution for that spot
configuration. Keep unresolved correction work visible.

Earlier evidence creates a revision-bound payment correction, not a new exceptional-end
case or an append-as-amendment assumption. Resolve unknown original effects before
new effects. The payment adapter computes remaining per-part work from the mandate
and verified prior events, including independent dispute outcomes, and must not
repeat prior reversals or bond awards. **Recommendation (04 F6/F12):** consume a
foundation-declared payment-adapter correction capability bound to contract/vector
revision, covering replay, overlapping runner/storefront commands and earlier-end
revisions. Absent verified coverage, report repair required and keep financial
work unresolved rather than guess a remaining amount. This is an adapter contract
gate based on SCM adapter qualification, not a new payment-service primitive,
local ruling or dispute-adapter capability. Convergence qualifies its
composition; foundation/spot own the contract and hosted implementation.

Partial-period pricing, explicit stop-entry notices and term-end treatment remain
foundation/spot-owned payment terms; normal stops need no local corrective reverse.
The explicit exceptional-end reversals above are self-correction, not a second
pricing implementation in end service. Holds and case extensions remain authoritative
only when verified at payments. Both authorities down leaves durable unresolved
work, not a recovery deadline. A malicious seller may bill until buyer stop,
exhaustion or maximum term; held earnings and timely buyer action at the agreed
dispute authority protect recovery. Promote these limits to deal-lifecycle architecture.

### D6. Commands and recovery

Exercise the foundation/spot buyer flow, do not reimplement it. With nonzero payer
notice the buyer stops at the payment authority and sends a hint; service continues
until watch observes the effective stop. `end_delivery` is explicit end-now-regardless
and the unreachable-payment-authority path with buyer_end(at) evidence. Keep exact
site reports and signed acknowledgements through foundation ingestion/read.

On `end_delivery` the storefront signs its own receipt time (the request has no
`at`) and ends delivery there. Its cooperative stop uses the buyer's own treatment
at receipt plus payer notice with payer partialPeriod, never a notice waiver or
the seller's immediate restitution entry. Journal/retry that dispute-free path,
including through payment outage, only where a mandate entry authorizes the
storefront to issue it. Otherwise stopping payments remains the buyer half's job;
a peer message alone is not a payment stop. Consume foundation's payment-adapter
command/journal without inferring authority from favourable effects. Buyer
stop-first remains preferred; buyer_end is a human-triaged case,
not a mechanical ruling. The case carries the exact Agreement verified against the
mandate's deal hash, not a required payment attachment.

**Recommendation supplied here (03 F1 / 04 F6):** use stateless operator recovery
through injected adapters and a caller-retained command file. A seller-authenticated
read-only export of the foundation evidence store supplies exact Agreement,
commitment/mandate, authority bindings, signed evidence and known effect references;
produce it while online and retain it outside the stopped storefront. This change
adds the export to seller lifecycle contracts/client and CLI; no private key is
exported. Unlike relying on an optional payments attachment, this has an explicit
producer and works with the existing evidence contract. Missing required bytes
refuses recovery rather than reconstructing an Agreement.

Before I/O the runner durably writes an immutable operation envelope containing key,
fixed kind/time/payload, commitment and authority binding, administrator/reason,
evidence digests/references and exact adapter-derived per-part descriptors. Replay
consumes this file, reads first and retries identical descriptors; it never rebuilds
`exceptional_end(now)` or reallocates a key. Export exact results separately, so
interruption before any result is saved is recoverable without storefront persistence.

Before correction the runner and online replay read verified payment events, adopt
already satisfied matching effects and resolve unknown ones under their original
identities. **Recommendation (04 F6):** semantic effect identities shared by both
paths bind commitment, correction basis/revision, part and effect purpose; distinct
caller keys cannot duplicate the same effect. Different or earlier bases require
the qualified overlapping/revision correction contract in D5, not merely a read
that could race another writer. If that contract cannot ensure safe convergence,
refuse new correction and expose repair required. Watch discovers the operator's
payment events on restart and reconciles journaled obligations; no duplicate
exceptional-end cases are created. Entitled notice still goes directly to payments.
Manual physical acknowledgement alone uses online administrator submit in D2.
No offline storefront database writer or separate payment implementation is built.

### D7. Restart, declarations and activation

Restart recovers journaled effects/cursors, not historical approval or lease status
alone. During identity overlap the loop requests spot's fresh verified snapshot for
running rate deals, persists exact re-anchoring evidence before retiring old-key
dependence, and reports unanchored deals as repair reasons before retirement.
Once-only dependencies are inventoried as must drain. Spot owns cryptographic and
rotation policy; this change owns durable consumption and seller read/list status. Publication, acceptance and materialization
require servicing declarations. Startup with accepted rate deals but no loop is
refused as incoherent; dependency outages alone are recoverable, not refusal.
Withdrawal disables new deals only. Existing commitments keep servicing/evidence.
Proposed-contract servicing is lane-only. Production activation verifies the hosted
per-part/notice/hold revision and support for the stop terms actually offered
through its own deployment gate; a permitted charged/charged subset need not wait
for returned/prorated support.

## Scenarios and evidence

This change is the single owner of the rate-servicing lane matrix. Execute spot's
prepared entry points, including maximum term and on-demand seller restitution
through its explicit entry; spot records preparation, not duplicate qualification.
Qualify the spot multi-entry dependency separately: before support, an emergency
uses the notice entry and cannot claim immediate stop.
Unify owns once-only activation expiry and the path seam; its consumer-dependent
rate qualification uses this matrix after the section handoff in D1.

| # | Scenario | Required observation |
|---|---|---|
| 0 | On-demand baseline | setup once + rate, provision/activate/start/disclose, priced payer stop + hint, both facts |
| 1 | Buyer end with payments down | pre/during/post dispatch, receipt-timed end_delivery acknowledgement and journaled cooperative stop; buyer_end triage and both-down replay |
| 2 | Site withdraws with storefront absent | buyer independent stop/case; late report, classified seller self-correction; release proven separately |
| 3 | Interrupted authority effects | same case/effect-key resolution, partial reverse after stop; earlier evidence during partial correction or append/close race remains unresolved until verified revision effects |
| 4 | Stop between start and disclosure | local admission blocks disclosure; measured remote observation windows |
| 5 | Rate deal activation deadline expires | no-dispatch proof or adoption/release; exceptional_end at start, setup entirely returned |
| 6 | Funding expiry and last-poll top-up | read before end; reachable renewal replaces timer and verified exhaustion is an authority end; only outage/unverifiable state ends on bare timer, with hidden top-up requiring later self-correction |
| 7 | Spot notice then earlier payer stop | authority hosts pending stop during absence; earliest wins, authority partial-period terms |
| 8 | Activated and started but never disclosed | disclosure fails, self-correction at deal start, buyer-case backstop |
| 9 | Maximum term | absolute authority end with its own partialPeriod, including late start and a mid-period end; physical recovery, no exceptional_end |
| 10 | On-demand seller emergency | only explicit seller PT0S/returned entry is present and buyer-checked; stop/reverse messages have no exceptional-end field; buyer case/bond remedies preemption, not mandate prevention |
| 11 | Identity rotation overlap | old receipt verified during overlap, current snapshot re-anchors the running rate deal before retirement, exact old bytes retained; once-only dependencies drain; revoked/stale anchors and livemode changes refused |

The nine diagram pairs illustrate cases 0–8; cases 9–11 extend the qualification
matrix without duplicating diagrams. **Recommendation supplied here (Sol F3):**
lane interruptions are loop pause/resume, not process restart evidence. Durable restart proof belongs to production-application
integration tests rebuilding against the same database in both domains; retain the
permanent bare-metal lane no-restart contract. Lost-response replay in lanes proves
cross-service effect convergence only.

Use the lane-double-owned evidence classes *Qualification against the published
contract*, *Qualification against a proposed contract*, and *Live evidence* by name;
their definitions remain in that change's D6. For rows 7 and 9 record the buyer's
explicit non-default started_period acceptance for interim charged terms; separately
observe default-policy refusal and returned-capable acceptance once vendored.
Spot owns identity re-anchoring policy and evidence production;
scenario 11 here qualifies its overlap/recovery behavior in both lanes.

**Recommendation supplied here:** cross-service lane scenarios use real UTC time,
short fixture periods/deadlines and bounded readiness/event waits through existing
controls. Use tooling's typed due-work barriers with per-authority watermarks,
pending effects and blocked dependencies; future work stays pending and blocked
effects never count as completion. Doubles run wall-clock mode here; do not jump their injected clocks ahead
of storefront/site time. Fixture validation bounds clock skew and wait budgets and
fails setup if clocks disagree. No site clock-injection surface is added. Library
integration keeps deterministic injected clocks for expiry/race permutations; lanes
only qualify the network transitions, never duplicate arithmetic coverage. Kits use
the single clock-injected payments authority engine owned by kit/arkhai-payments
fixtures directly; HTTP doubles wrap it with controls and mediation composition.
No kit depends on runnable tooling.

## Rejected alternatives and accepted limitations

Reject seller horizon/vouch, locally scheduled payment stops, required minimum
spend, backdated stops, mandatory reverse-before-stop, a parallel financial-end log,
one completion fact, end-intent as release proof, exceptional-end dispute filing,
mechanical mediation rulings, append-as-amendment, and an offline
second database writer. None strengthens buyer authority-backed guarantees.
Periodic collection, pooled funding, liability ledgers, push observation and lease
top-up are outside scope. Seller site renewal is optional capacity policy. Buyer
recovery requires kept evidence and action within dispute protection; no seller
cooperation or instant adjudication is promised.

## Permanent documentation destinations

D1/D3/D7 composition ownership goes to market-composition and repository ARCHITECTURE.
D2–D6 end-service contracts and guarantee limits go to deal-lifecycle spec/architecture.
The adapter-mediated journal exception to retryable settlement goes to
settlement-servicing; adapter decisions remain mechanism-owned continuation.
Scenario boundaries go to test-compatibility; diagram pairs to
`docs/development/diagrams/`. Tasks record exact promotion destinations. No permanent
document is changed while this remains design-stage work.

## Second-review handoff

The collector must reconcile the prerequisite-owned contracts before implementation:

- Foundation: keep closed correction classification/timing and the neutral journal;
  add pending classification and atomic later correction resolution (D5); remove the
  executable funding-timer requirement/scenarios owned here. Expose the qualified
  payment-correction descriptor/capability contract consumed by D5/D6, not a dispute
  netting feature. Apply receipt-time cooperative stops only through explicit
  authorization, never notice waiver; otherwise the buyer half stops payments.
  Keep exceptional_end solely SCM vocabulary and cases Agreement-bound.
- Spot: implement authorize/start_billing and SCM correction-to-stop/reverse mapping;
  require explicit seller restitution entries and buyer checks, gate several stop
  entries per account/part, and retain notice-only emergency fallback until supported;
  produce re-anchoring evidence consumed here. Keep only kit/vector qualification,
  not duplicate rate-lane time/evidence-class requirements.
- Unified delivery: name foundation protocol, spot interpretation and convergence
  composition separately; rate qualification waits for spot adapter plus this wiring.
- Terms: retain declaration/three-door rules; transfer startup/continued-servicing
  execution to this change. Activation consumes that contract rather than restating it.

Recommendations supplied for 03 F1 / 04 F6/F12 are the read-only seller export,
immutable caller-retained envelope, shared semantic correction-effect identities
and version/vector-bound overlapping/revision reconciliation. Recovery identities/reconciliation add no payment primitive. Spot's distinct
multi-stop-entry dependency remains unscheduled and gated; until it lands,
emergency stop waits out seller notice. Missing safe correction evidence blocks
that work with repair required.
Keep this change in design for a coordinated review of the changed payment path
and recovery/journal interfaces; the parent chooses advancement and edits the index.
